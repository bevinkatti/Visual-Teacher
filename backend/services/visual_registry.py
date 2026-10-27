"""Typed visual selection and deterministic, non-executing visual timelines."""

from __future__ import annotations

import re
from typing import Any

from backend.schemas import CodeExecutionData, Scene


PROGRAMMING_TOPIC = re.compile(
    r"\b(python|javascript|typescript|program(?:ming)?|code|algorithm|for[- ]?loops?|while loops?)\b",
    re.IGNORECASE,
)


def is_programming_topic(topic: str) -> bool:
    return bool(PROGRAMMING_TOPIC.search(topic))


def select_scene_visual_type(topic: str, scene: Scene) -> Scene:
    """Keep code-focused visuals for code topics; use concept visuals elsewhere."""
    if is_programming_topic(topic):
        if scene.execution_data is not None:
            return scene.model_copy(update={"visual_type": "code_execution"})
        return scene
    if scene.visual_type in {"code", "code_execution"}:
        return scene.model_copy(
            update={"visual_type": "concept_diagram", "execution_data": None}
        )
    return scene


def renderer_key(scene: Scene) -> str:
    """Resolve both current names and legacy names to a typed renderer key."""
    if scene.visual_type in {"concept", "concept_diagram"}:
        return "concept_diagram"
    if scene.visual_type in {"flow", "process_flow"}:
        return "process_flow"
    if scene.visual_type == "code_execution" and scene.execution_data is not None:
        return "code_execution"
    return "legacy_code"


def build_code_execution_timeline(
    data: CodeExecutionData,
) -> list[dict[str, Any]]:
    """Build normalized keyframes shared by the video renderer and browser.

    The data is declarative: this function creates display states only. It never
    parses or evaluates model-generated Python code.
    """
    count = len(data.values)
    ready_end = 0.1
    complete_start = 0.9
    step_width = (complete_start - ready_end) / count
    keyframes: list[dict[str, Any]] = [
        {
            "start_progress": 0.0,
            "end_progress": ready_end,
            "phase": "ready",
            "active_line": 1,
            "iteration": 0,
            "value": None,
            "output": [],
            "status": "Ready to begin",
        }
    ]
    for index, value in enumerate(data.values):
        start = ready_end + index * step_width
        middle = start + step_width * 0.38
        end = start + step_width
        previous_output = data.values[:index]
        keyframes.extend(
            [
                {
                    "start_progress": start,
                    "end_progress": middle,
                    "phase": "next_value",
                    "active_line": 1,
                    "iteration": index + 1,
                    "value": value,
                    "output": previous_output,
                    "status": f"Read item {index + 1} of {count}",
                },
                {
                    "start_progress": middle,
                    "end_progress": end,
                    "phase": "run_body",
                    "active_line": 2,
                    "iteration": index + 1,
                    "value": value,
                    "output": data.values[: index + 1],
                    "status": f"Print {value}",
                },
            ]
        )
    keyframes.append(
        {
            "start_progress": complete_start,
            "end_progress": 1.0,
            "phase": "complete",
            "active_line": 1,
            "iteration": count,
            "value": None,
            "output": data.values,
            "status": "No values remain · loop stops",
        }
    )
    return keyframes


def visual_state_at_progress(
    keyframes: list[dict[str, Any]], progress: float
) -> dict[str, Any] | None:
    if not keyframes:
        return None
    bounded = max(0.0, min(1.0, float(progress)))
    for frame in keyframes:
        if bounded < frame["end_progress"]:
            return frame
    return keyframes[-1]
