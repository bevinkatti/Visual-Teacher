"""Unit tests for the local IndicTrans2 lesson translator (model-free fakes)."""

from pathlib import Path

import pytest

from backend.schemas import LessonRequest
from backend.services.lesson_service import build_sample_lesson
from backend.services.translation_service import LessonTranslator, TranslationUnavailable


KANNADA_WORD = "ಕನ್ನಡ"


class ScriptedTranslator(LessonTranslator):
    """Bypasses the real model and returns fixed target-script text per sentence."""

    def __init__(self, output: str):
        super().__init__(model_dir=Path("unused-model-dir"))
        self._output = output
        self.calls: list[list[str]] = []

    def translate_sentences(self, sentences: list[str], target_language: str) -> list[str]:
        self.calls.append(list(sentences))
        return [self._output for _ in sentences]


def english_lesson():
    return build_sample_lesson(
        LessonRequest(topic="How does a python loop work", duration_seconds=30)
    )


def test_translate_lesson_rewrites_learner_text_and_keeps_execution_data():
    translated = ScriptedTranslator(f"{KANNADA_WORD} ಪಾಠ.").translate_lesson(
        english_lesson(), "kn"
    )

    assert translated.language == "kn"
    for scene in translated.scenes:
        assert KANNADA_WORD in scene.title
        assert KANNADA_WORD in scene.narration
        assert KANNADA_WORD in scene.caption
    for source, result in zip(english_lesson().scenes, translated.scenes, strict=True):
        if source.execution_data is None:
            assert result.execution_data is None
        else:
            assert result.execution_data == source.execution_data


def test_translate_lesson_leaves_non_prose_visual_data_unchanged():
    lesson = english_lesson()
    scenes = [
        scene.model_copy(
            update={"visual_data": {"code": "for i in range(3):", "purpose": "show iteration"}}
        )
        for scene in lesson.scenes
    ]
    english = lesson.model_copy(update={"scenes": scenes})

    translated = ScriptedTranslator(f"{KANNADA_WORD} ಪಾಠ.").translate_lesson(english, "kn")

    for scene in translated.scenes:
        assert scene.visual_data["code"] == "for i in range(3):"
        assert KANNADA_WORD in scene.visual_data["purpose"]


def test_translate_lesson_translates_cause_effect_labels_as_one_bounded_batch():
    lesson = build_sample_lesson(
        LessonRequest(topic="How does photosynthesis work?", duration_seconds=30)
    )
    translator = ScriptedTranslator(f"{KANNADA_WORD} ಪಾಠ")

    translated = translator.translate_lesson(lesson, "kn")
    scene = next(item for item in translated.scenes if item.cause_effect_data is not None)

    assert scene.cause_effect_data is not None
    assert all(KANNADA_WORD in label for label in scene.cause_effect_data.inputs)
    assert KANNADA_WORD in scene.cause_effect_data.mechanism
    assert all(KANNADA_WORD in label for label in scene.cause_effect_data.outputs)
    cause_effect_batch = next(batch for batch in translator.calls if "sunlight" in batch)
    assert {
        "sunlight",
        "water",
        "carbon dioxide",
        "chloroplasts in a leaf",
        "glucose",
        "oxygen",
    }.issubset(cause_effect_batch)


def test_wrong_script_output_is_refused():
    with pytest.raises(TranslationUnavailable, match="script"):
        ScriptedTranslator("plain english output").translate_lesson(english_lesson(), "kn")


def test_unknown_target_language_is_refused_before_any_model_load():
    with pytest.raises(TranslationUnavailable, match="no local translator"):
        LessonTranslator(model_dir=Path("unused-model-dir")).translate_lesson(
            english_lesson(), "fr"
        )


def test_missing_model_directory_is_reported_as_unavailable():
    translator = LessonTranslator(model_dir=Path("Z:/definitely-missing-model"))
    with pytest.raises(TranslationUnavailable, match="missing"):
        translator.translate_sentences(["Short sentence."], "kn")
