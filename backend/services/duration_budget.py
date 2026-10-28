"""Narration budget allocation, trimming, and target-duration enforcement.

The selected lesson duration is a genuine target, not a prompt suggestion.
This module allocates a speakable budget across scenes BEFORE expensive
synthesis, shortens narration that cannot fit, and gives the exporter the
tolerance rule it verifies against measured audio. Trimming is sentence-aware
and conservative: the first sentence of a scene is always kept, and every
correction is recorded so the manifest can show exactly what changed.
"""

from __future__ import annotations

import json
import os
import re
import unicodedata
from dataclasses import dataclass

from backend.schemas import Lesson


DURATION_TOLERANCE = 0.10  # a rendered lesson may exceed its target by at most 10%
BUDGET_SAFETY_FRACTION = 0.04  # keep a little speech headroom when allocating
BUDGET_SLACK_SECONDS = 0.75  # absolute slack removed from the speech budget

_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?।])\s+")

# Mean synthesizable characters per second, measured on this laptop with the
# real narrators (see backend/calibrate_speech_rates.py), expressed in
# spoken-length units: combining marks (matras, viramas) are excluded because
# they inflate Indic code-point counts without adding spoken time. English and
# Hindi use Kokoro-ONNX; Kannada uses Indic Parler-TTS. These are estimation
# inputs for budgeting only -- measured audio always sets the final timing.
DEFAULT_SPEAKING_RATES: dict[tuple[str, str], float] = {
    ("kokoro", "en"): 21.0,
    ("kokoro", "hi"): 15.5,
    ("parler", "kn"): 14.0,
}
_RATE_ENV_VAR = "BLU_SPEAKING_RATES_JSON"


class DurationBudgetError(RuntimeError):
    """Narration cannot fit the requested duration within tolerance."""


def _rate_key(engine: str, language: str) -> tuple[str, str]:
    return engine.lower(), language.lower()


def _default_rate(engine: str, language: str) -> float:
    if language == "en":
        return DEFAULT_SPEAKING_RATES[("kokoro", "en")]
    if language == "hi":
        return DEFAULT_SPEAKING_RATES[("kokoro", "hi")]
    return DEFAULT_SPEAKING_RATES[("parler", "kn")]


def speaking_rate(engine: str, language: str) -> float:
    """Chars-per-second for one narrator engine and language (calibratable)."""
    rates = dict(DEFAULT_SPEAKING_RATES)
    raw = os.getenv(_RATE_ENV_VAR)
    if raw:
        try:
            overrides = json.loads(raw)
        except json.JSONDecodeError:
            overrides = {}
        for key, value in overrides.items():
            engine_name, _, language_code = key.partition("|")
            try:
                rates[_rate_key(engine_name, language_code)] = float(value)
            except (KeyError, TypeError, ValueError):
                continue
    return rates.get(_rate_key(engine, language)) or _default_rate(engine, language)


def narrator_engine(narrator: object) -> str:
    """Identify the narration engine without importing heavy model modules."""
    return str(getattr(narrator, "engine_name", "kokoro")).lower()


def spoken_length(text: str) -> int:
    """Characters that count toward speech time (combining marks excluded)."""
    return sum(1 for char in text if unicodedata.category(char) != "Mn")


def split_sentences(text: str) -> list[str]:
    parts = [part.strip() for part in _SENTENCE_BOUNDARY.split(text) if part.strip()]
    if not parts and text.strip():
        return [text.strip()]
    return parts


def trim_to_char_budget(text: str, max_characters: int) -> tuple[str, int]:
    """Keep whole leading sentences that fit; always keep at least one sentence.

    Budgets are measured in spoken-length units (see :func:`spoken_length`).
    Returns the trimmed text and how many sentences were dropped. Mid-sentence
    truncation never happens, and the result is never empty for non-empty text.
    """
    sentences = split_sentences(text)
    if not sentences:
        return text, 0
    kept: list[str] = []
    total = 0
    for index, sentence in enumerate(sentences):
        addition = spoken_length(sentence) + (1 if kept else 0)
        if index > 0 and total + addition > max_characters:
            break
        kept.append(sentence)
        total += addition
    return " ".join(kept), len(sentences) - len(kept)


def speech_budget_seconds(lesson: Lesson) -> float:
    """Seconds of speech the lesson may use after pauses and safety margin."""
    pauses = sum(scene.pause_seconds for scene in lesson.scenes)
    budget = (
        lesson.target_duration_seconds * (1.0 - BUDGET_SAFETY_FRACTION)
        - pauses
        - BUDGET_SLACK_SECONDS
    )
    # Even the shortest target must keep at least three seconds of speech.
    return max(3.0, budget)


def estimate_speech_seconds(text: str, rate: float) -> float:
    return spoken_length(text) / rate if rate > 0 else float("inf")


@dataclass(frozen=True)
class BudgetPlan:
    target_seconds: int
    speech_budget: float
    speaking_rate: float
    estimated_seconds: list[float]
    scene_char_budgets: list[int]

    @property
    def estimated_total_seconds(self) -> float:
        return sum(self.estimated_seconds)

    @property
    def fits(self) -> bool:
        return self.estimated_total_seconds <= self.speech_budget


def plan_narration_budget(lesson: Lesson, rate: float) -> BudgetPlan:
    """Split the speech budget across scenes proportionally to current text.

    Each scene keeps a floor of its first sentence so trimming can never
    silence a scene entirely.
    """
    speech_budget = speech_budget_seconds(lesson)
    narrations = [scene.narration for scene in lesson.scenes]
    estimates = [estimate_speech_seconds(text, rate) for text in narrations]
    total_estimate = sum(estimates)
    char_budgets: list[int] = []
    if total_estimate <= speech_budget or total_estimate <= 0:
        char_budgets = [spoken_length(text) for text in narrations]
    else:
        scale = speech_budget / total_estimate
        for text in narrations:
            sentences = split_sentences(text)
            floor = spoken_length(sentences[0]) if sentences else spoken_length(text)
            char_budgets.append(max(floor, int(spoken_length(text) * scale)))
    return BudgetPlan(
        target_seconds=lesson.target_duration_seconds,
        speech_budget=speech_budget,
        speaking_rate=rate,
        estimated_seconds=estimates,
        scene_char_budgets=char_budgets,
    )


def enforce_narration_budget(lesson: Lesson, engine: str) -> tuple[Lesson, list[dict[str, object]]]:
    """Gross-overshoot safety net BEFORE synthesis; report every change.

    Real per-sentence speaking rates vary too much for a single average rate to
    police the fine budget, so this only trims narration whose estimate exceeds
    the export tolerance. The measured post-synthesis pass in the exporter does
    the fine correction in both directions.
    """
    rate = speaking_rate(engine, lesson.language)
    plan = plan_narration_budget(lesson, rate)
    tolerance = tolerance_seconds(lesson.target_duration_seconds)
    if plan.estimated_total_seconds <= tolerance:
        return lesson, []

    corrections: list[dict[str, object]] = []
    updated_scenes = []
    for index, scene in enumerate(lesson.scenes):
        budget = plan.scene_char_budgets[index]
        if spoken_length(scene.narration) <= budget:
            updated_scenes.append(scene)
            continue
        trimmed_narration, dropped = trim_to_char_budget(scene.narration, budget)
        trimmed_caption, _ = trim_to_char_budget(scene.caption, spoken_length(trimmed_narration))
        corrections.append(
            {
                "stage": "pre_synthesis",
                "scene_index": index,
                "original_characters": len(scene.narration),
                "budget_characters": budget,
                "dropped_sentences": dropped,
                "estimated_seconds_before": round(plan.estimated_seconds[index], 2),
            }
        )
        updated_scenes.append(
            scene.model_copy(update={"narration": trimmed_narration, "caption": trimmed_caption})
        )
    return lesson.model_copy(update={"scenes": updated_scenes}), corrections


def tolerance_seconds(target: int) -> float:
    return target * (1.0 + DURATION_TOLERANCE)


def within_tolerance(total_seconds: float, target: int) -> bool:
    return total_seconds <= tolerance_seconds(target)

