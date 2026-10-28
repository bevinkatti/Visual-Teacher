import pytest
from pydantic import ValidationError

from backend.schemas import (
    CauseEffectData,
    CodeExecutionData,
    FractionModelData,
    LessonRequest,
    Scene,
)
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

    assert renderer_key(lesson.scenes[0]) == "title_card"
    assert renderer_key(lesson.scenes[1]) == "process_flow"


def test_fraction_area_model_is_bounded_and_available_in_deterministic_sample():
    scene = Scene(
        title="Shade three equal parts",
        narration="Three of four equal pieces make three fourths.",
        caption="3 of 4 equal pieces are selected.",
        visual_type="fraction_model",
        fraction_data=FractionModelData(numerator=3, denominator=4),
    )
    assert renderer_key(scene) == "fraction_model"

    lesson = build_sample_lesson(
        LessonRequest(topic="How do fractions show parts of a whole?", duration_seconds=30)
    )
    fraction_scene = next(item for item in lesson.scenes if item.visual_type == "fraction_model")
    assert fraction_scene.fraction_data == FractionModelData(numerator=3, denominator=4)

    with pytest.raises(ValidationError):
        FractionModelData(numerator=5, denominator=4)
    with pytest.raises(ValidationError):
        Scene(
            title="Missing fraction data",
            narration="This scene has no structured area model.",
            caption="Invalid fraction scene.",
            visual_type="fraction_model",
        )


def test_cause_effect_uses_bounded_inputs_mechanism_outputs():
    lesson = build_sample_lesson(
        LessonRequest(topic="How does photosynthesis work?", duration_seconds=30)
    )
    scene = next(item for item in lesson.scenes if item.visual_type == "cause_effect")
    assert renderer_key(scene) == "cause_effect"
    assert scene.cause_effect_data == CauseEffectData(
        inputs=["sunlight", "water", "carbon dioxide"],
        mechanism="chloroplasts in a leaf",
        outputs=["glucose", "oxygen"],
    )
    assert "glucose" in scene.narration

    with pytest.raises(ValidationError):
        CauseEffectData(
            inputs=["light"], mechanism="leaf", outputs=["sugar"]
        )
    with pytest.raises(ValidationError):
        Scene(
            title="Missing mechanism data",
            narration="Inputs and outputs should be shown through a process.",
            caption="Invalid cause and effect.",
            visual_type="cause_effect",
        )


def test_engineering_topics_get_specific_offline_visual_sequences():
    topics = {
        "What is RAG?": "grounded answer",
        "How does an API request work?": "http request",
        "What is an LLM?": "next token",
        "What is artificial intelligence?": "useful patterns",
        "What is machine learning?": "learns patterns",
        "What is deep learning?": "later layers",
        "What is a neural network?": "weighted connections",
    }
    for topic, expected_label in topics.items():
        scene = Scene(
            title="Explain the mechanism",
            narration="Follow the information through each stage.",
            caption="Trace how the system changes the input.",
        )
        selected = select_scene_visual_type(topic, scene, scene_index=1)
        assert selected.visual_type == "process_flow"
        assert expected_label in " ".join(selected.visual_data.values()).lower()
        assert renderer_key(selected) == "process_flow"

    training_scene = Scene(
        title="Train a model",
        narration="Each update uses the prediction error.",
        caption="Examples, error, and weight updates repeat.",
    )
    training = select_scene_visual_type(
        "How do you train a machine learning model?", training_scene, scene_index=1
    )
    assert training.visual_type == "cycle"
    assert training.cycle_data is not None
    assert training.cycle_data.stages[-1] == "update model weights"
    assert renderer_key(training) == "cycle"


def test_translation_unavailable_keeps_the_existing_hindi_sample_fallback():
    lesson = build_sample_lesson(
        LessonRequest(
            topic="How do fractions show parts of a whole?",
            language="hi",
            duration_seconds=30,
        ),
        fallback_reason="translation_unavailable",
    )

    assert any("भिन्न" in scene.title or "समझ" in scene.title for scene in lesson.scenes)
    assert lesson.language == "hi"

