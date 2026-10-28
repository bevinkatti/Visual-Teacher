"""Local IndicTrans2 translation of English lesson text into Indian-language scripts.

The lesson is always planned in English; this service translates scene titles,
narration, captions, whitelisted visual_data values, and bounded cause/effect
labels afterwards. Code and execution_data are never translated.
"""

from __future__ import annotations

import logging
import os
import re
import time
from pathlib import Path

from backend.schemas import CauseEffectData, Lesson


logger = logging.getLogger(__name__)
PROJECT_ROOT = Path(__file__).resolve().parents[2]

TARGET_TRANSCRIPT_CODES = {
    "hi": "hin_Deva",
    "kn": "kan_Knda",
    "mr": "mar_Deva",
    "ta": "tam_Taml",
    "te": "tel_Telu",
    "bn": "ben_Beng",
}
_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?।])\s+")
MAX_SENTENCE_CHARACTERS = 420

# Only these visual_data keys carry learner-facing prose; everything else
# (code snippets, technical labels) stays exactly as the planner wrote it.
TRANSLATABLE_VISUAL_KEYS = frozenset(
    {"topic", "subtitle", "purpose", "left", "right", "relationship", "input", "process", "output"}
)


class TranslationUnavailable(RuntimeError):
    """The local translation model is missing, unusable, or returned no usable text."""


class LessonTranslator:
    """Translate an English-scene Lesson using the local IndicTrans2 model."""

    def __init__(self, model_dir: Path | None = None):
        self.model_dir = model_dir or Path(
            os.getenv(
                "BLU_INDICTRANS_DIR",
                str(PROJECT_ROOT / "models" / "indictrans2-en-indic-dist-200M"),
            )
        )
        self._processor = None
        self._tokenizer = None
        self._model = None
        self.translation_seconds = 0.0

    def _ensure_loaded(self) -> None:
        if self._model is not None:
            return
        if not self.model_dir.is_dir():
            raise TranslationUnavailable(
                f"IndicTrans2 model directory is missing: {self.model_dir}"
            )
        load_start = time.monotonic()
        try:
            import torch
            from IndicTransToolkit import IndicProcessor
            from transformers import AutoModelForSeq2SeqLM, AutoTokenizer
        except ImportError as exc:
            raise TranslationUnavailable(
                f"Local translation dependencies are missing: {exc}"
            ) from exc

        try:
            self._processor = IndicProcessor(inference=True)
            self._tokenizer = AutoTokenizer.from_pretrained(
                str(self.model_dir), trust_remote_code=True
            )
            self._model = AutoModelForSeq2SeqLM.from_pretrained(
                str(self.model_dir),
                torch_dtype=torch.float32,
                trust_remote_code=True,
            )
            self._model.eval()
        except Exception as exc:
            self._tokenizer = None
            self._model = None
            raise TranslationUnavailable(f"IndicTrans2 could not be loaded: {exc}") from exc
        logger.info(
            "IndicTrans2 initialization_seconds=%.3f", time.monotonic() - load_start
        )

    def translate_sentences(self, sentences: list[str], target_language: str) -> list[str]:
        """Translate English sentences; the caller gets one output per input."""
        if not sentences:
            return []
        self._ensure_loaded()
        import torch

        transcript = TARGET_TRANSCRIPT_CODES[target_language]
        start = time.monotonic()
        try:
            preprocessed = self._processor.preprocess_batch(
                sentences, src_lang="eng_Latn", tgt_lang=transcript
            )
            encoded = self._tokenizer(
                preprocessed,
                return_tensors="pt",
                padding=True,
                truncation=True,
                max_length=256,
            )
            with torch.no_grad():
                generated = self._model.generate(
                    **encoded,
                    num_beams=1,
                    do_sample=False,
                    max_new_tokens=256,
                )
            decoded = self._tokenizer.batch_decode(generated, skip_special_tokens=True)
            decoded = self._processor.postprocess_batch(decoded, lang=transcript)
        except Exception as exc:
            raise TranslationUnavailable(f"IndicTrans2 generation failed: {exc}") from exc
        finally:
            self.translation_seconds += time.monotonic() - start
        if isinstance(decoded, str):
            decoded = [decoded]
        if not isinstance(decoded, list) or len(decoded) != len(sentences):
            raise TranslationUnavailable(
                "IndicTrans2 returned the wrong number of sentences."
            )
        return [self._clean(text) for text in decoded]

    @staticmethod
    def _clean(text: object) -> str:
        return " ".join(str(text).split()) if isinstance(text, str) else ""

    def _split_sentences(self, text: str) -> list[str]:
        sentences = [part.strip() for part in _SENTENCE_BOUNDARY.split(text) if part.strip()]
        merged: list[str] = []
        for sentence in sentences:
            if (
                merged
                and len(sentence) < 40
                and len(merged[-1]) + len(sentence) < MAX_SENTENCE_CHARACTERS
            ):
                merged[-1] = f"{merged[-1]} {sentence}"
                continue
            if len(sentence) <= MAX_SENTENCE_CHARACTERS:
                merged.append(sentence)
                continue
            # Hard-bound very long sentences on word boundaries so a single
            # oversized narration can never blow up generation time.
            chunk = ""
            for word in sentence.split(" "):
                if chunk and len(chunk) + len(word) + 1 > MAX_SENTENCE_CHARACTERS:
                    merged.append(chunk)
                    chunk = word
                else:
                    chunk = f"{chunk} {word}".strip()
            if chunk:
                merged.append(chunk)
        return merged

    def _translate_blocks(self, texts: list[str], target_language: str) -> list[str]:
        """Translate many scene labels in one model batch, preserving each block."""
        sentence_groups = [self._split_sentences(text) for text in texts]
        translated = self.translate_sentences(
            [sentence for group in sentence_groups for sentence in group],
            target_language,
        )
        if any(not output for output in translated):
            raise TranslationUnavailable(
                "IndicTrans2 returned empty text for part of the lesson."
            )
        blocks: list[str] = []
        position = 0
        for group in sentence_groups:
            end = position + len(group)
            blocks.append(" ".join(translated[position:end]))
            position = end
        return blocks

    def _translate_block(self, text: str, target_language: str) -> str:
        return self._translate_blocks([text], target_language)[0]

    def _target_script_ratio(self, text: str, target_language: str) -> float:
        ranges = {"hi": ("\u0900", "\u097f"), "kn": ("\u0c80", "\u0cff")}
        low, high = ranges[target_language]
        letters = [char for char in text if char.isalpha()]
        if not letters:
            return 0.0
        return sum(low <= char <= high for char in letters) / len(letters)

    def translate_lesson(self, lesson: Lesson, target_language: str) -> Lesson:
        """Return a copy of the lesson with learner-facing text in the target script."""
        if target_language not in TARGET_TRANSCRIPT_CODES:
            raise TranslationUnavailable(
                f"Language {target_language!r} has no local translator."
            )
        scenes = []
        for scene in lesson.scenes:
            visual_keys = [
                key for key in scene.visual_data if key in TRANSLATABLE_VISUAL_KEYS
            ]
            texts = [scene.title, scene.narration, scene.caption]
            texts.extend(scene.visual_data[key] for key in visual_keys)
            cause_effect_label_count = 0
            if scene.cause_effect_data is not None:
                data = scene.cause_effect_data
                labels = [*data.inputs, data.mechanism, *data.outputs]
                texts.extend(labels)
                cause_effect_label_count = len(labels)

            translated = self._translate_blocks(texts, target_language)
            updates: dict[str, object] = {
                "title": translated[0],
                "narration": translated[1],
                "caption": translated[2],
            }
            visual_translations = dict(
                zip(visual_keys, translated[3 : 3 + len(visual_keys)], strict=True)
            )
            updates["visual_data"] = {
                key: visual_translations.get(key, value)
                for key, value in scene.visual_data.items()
            }
            if scene.cause_effect_data is not None:
                data = scene.cause_effect_data
                start = 3 + len(visual_keys)
                translated_labels = translated[start : start + cause_effect_label_count]
                input_end = len(data.inputs)
                output_start = input_end + 1
                try:
                    updates["cause_effect_data"] = CauseEffectData.model_validate(
                        {
                            "inputs": translated_labels[:input_end],
                            "mechanism": translated_labels[input_end],
                            "outputs": translated_labels[output_start:],
                        },
                        strict=True,
                    )
                except ValueError as exc:
                    raise TranslationUnavailable(
                        "Translated visual labels do not fit the visual schema."
                    ) from exc
            scenes.append(scene.model_copy(update=updates))
        translated = lesson.model_copy(
            update={"scenes": scenes, "language": target_language}
        )

        # Honest quality gate: most learner-facing letters must now use the
        # target script, otherwise the caller should fall back to the sample.
        joined = " ".join(scene.narration for scene in translated.scenes)
        if self._target_script_ratio(joined, target_language) < 0.2:
            raise TranslationUnavailable(
                "IndicTrans2 output did not use the requested script; refusing it."
            )
        logger.info(
            "Lesson translated language=%s translation_seconds=%.3f",
            target_language,
            self.translation_seconds,
        )
        return translated
