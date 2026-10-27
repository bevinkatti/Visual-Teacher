import pytest
from pydantic import ValidationError

from backend.schemas import CodeExecutionData, LessonRequest, Scene
from backend.services.lesson_service import build_sample_lesson
from backend.services.visual_registry import (
    build_code_execution_timeline,
    renderer_key,
    select_scene_visual_type,
    visual_state_at_progress,
)


def test_code_execution_timeline_reveals_values_and_output_deterministically():
    data = CodeExecutionData(
        variable_name="fruit",
        iterable_name="fruits",
        values=["apple", "pear", "plum"],
    )

    timeline = build_code_execution_timeline(data)

    assert timeline[0]["phase"] == "ready"
    assert timeline[0]["active_line"] == 1
    assert timeline[1]["phase"] == "next_value"
    assert timeline[1]["value"] == "apple"
    assert timeline[1]["output"] == []
    assert timeline[2]["phase"] == "run_body"
    assert timeline[2]["active_line"] == 2
    assert timeline[2]["output"] == ["apple"]
    assert timeline[-1]["phase"] == "complete"
    assert timeline[-1]["output"] == ["apple", "pear", "plum"]
    assert [frame["end_progress"] for frame in timeline] == sorted(
        frame["end_progress"] for frame in timeline
    )
    assert visual_state_at_progress(timeline, 0.0) == timeline[0]
    assert visual_state_at_progress(timeline, 1.0) == timeline[-1]
    assert visual_state_at_progress(timeline, -1.0) == timeline[0]


def test_execution_data_is_bounded_and_never_accepts_code_or_control_characters():
    with pytest.raises(ValidationError):
        CodeExecutionData(variable_name="for", iterable_name="items", values=["a", "b"])
    with pytest.raises(ValidationError):
        CodeExecutionData(variable_name="item", iterable_name="items", values=["a" + chr(10) + "b", "c"])
    with pytest.raises(ValidationError):
        CodeExecutionData(
            variable_name="item",
            iterable_name="items",
            values=["a", "b"],
            code="import os",
        )
    with pytest.raises(ValidationError):
        Scene(
            title="Missing data",
            narration="This scene has no bounded iteration data.",
            caption="No execution data",
            visual_type="code_execution",
        )


def test_topic_selection_uses_code_execution_only_with_structured_program_data():
    lesson = build_sample_lesson(
        LessonRequest(topic="How Python for-loops work", duration_seconds=30)
    )
    execution_scene = lesson.scenes[1]
    assert renderer_key(execution_scene) == "code_execution"
    assert select_scene_visual_type("How Python loops work", execution_scene).visual_type == "code_execution"

    legacy_code_scene = Scene(
        title="Display this code safely",
        narration="Code is shown as text but is never run.",
        caption="Code is display only.",
        visual_type="code",
        visual_data={"code": "print('hello')"},
    )
    selected = select_scene_visual_type("How do plants move water?", legacy_code_scene)
    assert selected.visual_type == "concept_diagram"
    assert selected.execution_data is None
    assert renderer_key(selected) == "concept_diagram"


def test_legacy_visual_types_resolve_to_current_renderer_registry_keys():
    lesson = build_sample_lesson(LessonRequest(topic="An arbitrary topic", duration_seconds=30))

    assert renderer_key(lesson.scenes[0]) == "concept_diagram"
    assert renderer_key(lesson.scenes[1]) == "process_flow"

