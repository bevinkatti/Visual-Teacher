import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
import soundfile as sf
from PIL import Image, ImageChops, ImageDraw

from backend.schemas import LessonRequest, Scene
from backend.services.export_service import (
    TimelineEntry,
    _caption_cues_for_timeline,
    _make_audio,
    _render_frames,
    _write_srt,
    build_timeline,
    verify_mp4,
)
from backend.services.lesson_service import build_sample_lesson
from backend.services.render_jobs import _has_requested_script
from backend.services.scene_renderer import (
    DEVANAGARI_FONT_PATH,
    DEVANAGARI_UI_FONT_PATH,
    FONT_BOLD_PATH,
    FONT_MONO_PATH,
    FONT_PATH,
    KANNADA_FONT_PATH,
    KANNADA_UI_BOLD_FONT_PATH,
    KANNADA_UI_FONT_PATH,
    HEIGHT,
    WIDTH,
    SceneRenderer,
    _draw_script_aware,
    _font,
    _font_for_text,
    _load_font,
    _script_font,
    _script_aware_textlength,
    _wrap,
)


def sample_lesson():
    return build_sample_lesson(
        LessonRequest(topic="How does a Python loop work?", duration_seconds=30)
    )


@pytest.mark.parametrize(
    ("topic", "third_visual", "terms"),
    [
        ("What is RAG?", "cause_effect", ("retrieval", "prompt", "passages")),
        ("What is deep learning?", "cycle", ("layers", "weights", "prediction")),
        ("What is a neural network?", "cause_effect", ("weight", "activation", "signal")),
    ],
)
def test_engineering_samples_teach_the_requested_mechanism(topic, third_visual, terms):
    lesson = build_sample_lesson(LessonRequest(topic=topic, duration_seconds=30))
    narration = " ".join(scene.narration for scene in lesson.scenes).lower()

    assert lesson.source == "sample" and lesson.fallback is False
    assert len(lesson.scenes) == 3
    assert lesson.scenes[0].visual_type == "title_card"
    assert lesson.scenes[1].visual_type == "process_flow"
    assert lesson.scenes[2].visual_type == third_visual
    assert all(term in narration for term in terms)
    assert "a good example makes the idea easy to picture" not in narration
    assert "teach it simply" not in narration

    flow_labels = " ".join(lesson.scenes[1].visual_data.values()).lower()
    if "rag" in topic.lower():
        assert all(term in flow_labels for term in ("retrieve", "prompt", "answer"))
    elif "deep learning" in topic.lower():
        assert "layer" in flow_labels and "prediction" in flow_labels
        assert lesson.scenes[2].cycle_data is not None
    else:
        assert "weight" in flow_labels and "activation" in flow_labels
        assert lesson.scenes[2].cause_effect_data is not None


@pytest.mark.parametrize("topic", ["What is RAG?", "What is deep learning?", "What is a neural network?"])
def test_engineering_demonstrations_animate_as_scene_state_changes(topic):
    lesson = build_sample_lesson(LessonRequest(topic=topic, duration_seconds=30))
    scene = lesson.scenes[2]
    renderer = SceneRenderer()

    early = renderer.render(
        scene, scene_progress=0.2, lesson_progress=0.7, scene_number=3, scene_count=3
    )
    late = renderer.render(
        scene, scene_progress=0.9, lesson_progress=0.95, scene_number=3, scene_count=3
    )

    assert ImageChops.difference(early, late).getbbox() is not None


def test_fixed_sample_is_validated_and_teaches_python_loop_progressively():
    lesson = sample_lesson()

    assert len(lesson.scenes) == 3
    assert [scene.visual_type for scene in lesson.scenes] == [
        "title_card",
        "code_execution",
        "concept_diagram",
    ]
    assert lesson.scenes[1].execution_data is not None
    assert lesson.scenes[1].execution_data.values == ["apple", "pear", "plum"]
    assert "no next value" in lesson.scenes[2].narration.lower()


def test_hindi_sample_uses_devanagari_script_and_local_font():
    lesson = build_sample_lesson(
        LessonRequest(topic="How Python for-loops work", language="hi", duration_seconds=30),
        fallback_reason="unavailable",
    )

    assert lesson.source == "sample" and lesson.fallback
    assert _has_requested_script(lesson)
    assert "apple" in lesson.scenes[1].narration
    assert any("अगली" in scene.title or "अगली" in scene.narration for scene in lesson.scenes)
    assert _font_for_text("पायथन लूप", 24).getmask("पायथन लूप").getbbox() is not None
    rendered = SceneRenderer().render(
        lesson.scenes[0],
        scene_progress=0.5,
        lesson_progress=0.25,
        scene_number=1,
        scene_count=3,
    )
    assert rendered.size == (WIDTH, HEIGHT)


def test_mixed_devanagari_caption_uses_latin_font_for_latin_terms():
    actual = Image.new("RGB", (240, 44), (0, 0, 0))
    expected = Image.new("RGB", (240, 44), (0, 0, 0))
    actual_draw = ImageDraw.Draw(actual)
    expected_draw = ImageDraw.Draw(expected)
    indic_font = _font_for_text("फल fruit", 24)
    latin_font = _font(24)
    phrase = "फल fruit"

    _draw_script_aware(actual_draw, (4, 4), phrase, indic_font, (255, 255, 255))
    expected_draw.text((4, 4), "फल", font=_script_font(24, False, "devanagari"), fill=(255, 255, 255))
    latin_x = 4 + expected_draw.textlength("फल", font=_script_font(24, False, "devanagari"))
    expected_draw.text((latin_x, 4), " fruit", font=latin_font, fill=(255, 255, 255))

    assert ImageChops.difference(actual, expected).getbbox() is None


def test_mixed_script_wrapping_uses_the_measured_font_runs():
    image = Image.new("RGB", (1280, 80), (0, 0, 0))
    draw = ImageDraw.Draw(image)
    text = "हर चक्र में fruit बदलता है और output में एक पंक्ति जुड़ती है। " * 5
    font = _font_for_text(text, 20)

    lines = _wrap(draw, text, font, 1070)

    assert len(lines) > 1
    assert all(_script_aware_textlength(draw, line, font) <= 1070 for line in lines)

    unspaced = _wrap(draw, "x" * 240, font, 1070)
    assert len(unspaced) > 1
    assert all(_script_aware_textlength(draw, line, font) <= 1070 for line in unspaced)


def test_missing_bundled_font_fails_with_its_path(monkeypatch, tmp_path):
    from backend.services import scene_renderer

    missing = tmp_path / "missing-noto.ttf"
    monkeypatch.setattr(scene_renderer, "FONT_PATH", missing)
    monkeypatch.setattr(scene_renderer, "FONT_BOLD_PATH", missing)
    _font.cache_clear()
    try:
        with pytest.raises(FileNotFoundError, match="Required bundled font") as exc:
            _font(29)
        assert str(missing) in str(exc.value)
    finally:
        _font.cache_clear()


def test_bundled_variable_font_selects_weight_axis():
    regular = _load_font(FONT_PATH, 28, bold=False)
    bold = _load_font(FONT_PATH, 28, bold=True)

    assert regular.getmask("Blu").getbbox() is not None
    assert bold.getmask("Blu").getbbox() is not None
    assert bytes(regular.getmask("Blu")) != bytes(bold.getmask("Blu"))


def test_kannada_fallback_preserves_script_and_bundled_noto_glyphs():
    lesson = build_sample_lesson(
        LessonRequest(topic="How Python for-loops work", language="kn", duration_seconds=30),
        fallback_reason="timeout",
    )
    text = " ".join(part for scene in lesson.scenes for part in (scene.title, scene.narration, scene.caption))
    kannada_letters = [char for char in text if "\u0c80" <= char <= "\u0cff"]
    alphabetic_letters = [char for char in text if char.isalpha()]

    assert lesson.language == "kn" and lesson.fallback
    assert len(lesson.scenes) == 3
    assert len(kannada_letters) / len(alphabetic_letters) > 0.2
    assert _font_for_text("ಕನ್ನಡ ಕಲಿಕೆ", 24).getmask("ಕನ್ನಡ ಕಲಿಕೆ").getbbox() is not None
    assert all(path.is_file() for path in (
        FONT_PATH,
        FONT_BOLD_PATH,
        FONT_MONO_PATH,
        DEVANAGARI_FONT_PATH,
        DEVANAGARI_UI_FONT_PATH,
        KANNADA_FONT_PATH,
        KANNADA_UI_FONT_PATH,
        KANNADA_UI_BOLD_FONT_PATH,
    ))

    rendered = SceneRenderer().render(
        lesson.scenes[0],
        scene_progress=0.5,
        lesson_progress=0.25,
        scene_number=1,
        scene_count=3,
    )
    assert rendered.size == (WIDTH, HEIGHT)


def test_timeline_uses_audio_durations_plus_configured_pauses():
    scenes = sample_lesson().scenes
    measured = [2.41, 3.07, 4.2]

    timeline = build_timeline(scenes, measured)

    assert [row.audio_seconds for row in timeline] == measured
    assert timeline[0].start_seconds == 0
    assert timeline[0].end_seconds == pytest.approx(2.76)
    assert timeline[1].start_seconds == pytest.approx(2.76)
    assert timeline[1].end_seconds == pytest.approx(6.18)
    assert timeline[2].end_seconds == pytest.approx(10.73)


@pytest.mark.parametrize("duration", [0, -1, float("nan"), float("inf")])
def test_timeline_rejects_invalid_audio_durations(duration):
    with pytest.raises(ValueError, match="positive and finite"):
        build_timeline(sample_lesson().scenes[:1], [duration])


def test_timeline_rejects_scene_duration_mismatch():
    with pytest.raises(ValueError, match="one measured narration duration"):
        build_timeline(sample_lesson().scenes, [2.0])


def test_frame_count_rounds_up_to_cover_measured_audio_duration(tmp_path, monkeypatch):
    lesson = sample_lesson()
    scene = lesson.scenes[0]
    timeline = [TimelineEntry(scene, audio_seconds=1.01, pause_seconds=0, start_seconds=0, end_seconds=1.01)]
    frames_dir = tmp_path / "frames"
    saved = []

    class FakeImage:
        size = (WIDTH, HEIGHT)

        def save(self, path, **_kwargs):
            saved.append(path)

    class FakeRenderer:
        def render(self, *_args, **_kwargs):
            return FakeImage()

    monkeypatch.setattr("backend.services.export_service.SceneRenderer", FakeRenderer)

    count = _render_frames(lesson, timeline, frames_dir, fps=24)

    assert count == 26
    assert len(saved) == 26


def test_renderer_emits_1280_by_720_explanatory_caption_frame():
    scene = sample_lesson().scenes[1]
    image = SceneRenderer().render(
        scene,
        scene_progress=0.55,
        lesson_progress=0.4,
        scene_number=2,
        scene_count=3,
    )

    assert image.size == (WIDTH, HEIGHT)
    assert image.getpixel((10, 10)) != image.getpixel((640, 360))


def test_concept_and_code_scenes_animate_and_stay_deterministic():
    lesson = build_sample_lesson(
        LessonRequest(topic="How does a Python loop work?", duration_seconds=30)
    )
    renderer = SceneRenderer()
    concept_scene = lesson.scenes[2]
    code_scene = Scene(
        title="Read the code",
        narration="Look at each line before it runs.",
        caption="Display only.",
        visual_type="code",
        visual_data={"code": "for i in range(3):\n    print(i)\nprint('done')"},
    )

    concept_early = renderer.render(
        concept_scene, scene_progress=0.3, lesson_progress=0.6, scene_number=3, scene_count=3
    )
    concept_late = renderer.render(
        concept_scene, scene_progress=0.75, lesson_progress=0.8, scene_number=3, scene_count=3
    )
    concept_repeat = renderer.render(
        concept_scene, scene_progress=0.3, lesson_progress=0.6, scene_number=3, scene_count=3
    )
    code_early = renderer.render(
        code_scene, scene_progress=0.12, lesson_progress=0.5, scene_number=1, scene_count=3
    )
    code_late = renderer.render(
        code_scene, scene_progress=0.6, lesson_progress=0.5, scene_number=1, scene_count=3
    )

    # Animation: frames at different scene progress visibly differ.
    assert ImageChops.difference(concept_early, concept_late).getbbox() is not None
    assert ImageChops.difference(code_early, code_late).getbbox() is not None
    # Determinism: identical progress reproduces the identical frame.
    assert ImageChops.difference(concept_early, concept_repeat).getbbox() is None


def test_audio_assembly_includes_scene_pause_and_srt_ends_at_measured_speech(tmp_path: Path):
    scenes = [sample_lesson().scenes[0].model_copy(update={"narration": "A short captioned sentence."})]
    samples = np.ones(2400, dtype=np.float32)
    timeline = build_timeline(scenes, [0.1])
    audio_path = tmp_path / "audio.wav"
    _make_audio([(samples, 24000)], timeline, audio_path)
    captions_path = tmp_path / "captions.srt"
    _write_srt(captions_path, timeline)

    assert sf.info(audio_path).duration == pytest.approx(0.45, abs=1 / 24000)
    assert "00:00:00,000 --> 00:00:00,100" in captions_path.read_text(encoding="utf-8")


def test_srt_caption_cues_follow_measured_scene_audio_and_exclude_pauses(tmp_path: Path):
    scenes = [
        sample_lesson().scenes[0].model_copy(update={"pause_seconds": 0.5}),
        sample_lesson().scenes[1].model_copy(update={"pause_seconds": 0.25}),
    ]
    timeline = build_timeline(scenes, [1.25, 2.5])
    captions_path = tmp_path / "timed-captions.srt"

    _write_srt(captions_path, timeline)
    cues = captions_path.read_text(encoding="utf-8")
    caption_timeline = _caption_cues_for_timeline(timeline)

    assert caption_timeline[0][0].start_seconds == 0
    assert caption_timeline[0][-1].end_seconds == pytest.approx(1.25)
    assert caption_timeline[1][0].start_seconds == pytest.approx(1.75)
    assert caption_timeline[1][-1].end_seconds == pytest.approx(4.25)
    assert "Denominator: total equal parts." not in cues
    assert all(cue.text in cues for scene_cues in caption_timeline for cue in scene_cues)


def test_rendered_caption_text_advances_with_the_narration_timeline(monkeypatch, tmp_path: Path):
    shown_captions = []

    class StubFrame:
        size = (WIDTH, HEIGHT)

        def save(self, *_args, **_kwargs):
            return None

    class StubRenderer:
        def render(self, _scene, **kwargs):
            shown_captions.append((
                kwargs["caption_text"],
                kwargs["caption_progress"],
                kwargs["caption_visible"],
            ))
            return StubFrame()

    lesson = sample_lesson()
    scene = lesson.scenes[0].model_copy(
        update={"narration": "Alpha begins. Bravo follows. Charlie finishes.", "pause_seconds": 0}
    )
    timeline = build_timeline([scene], [3.0])
    monkeypatch.setattr("backend.services.export_service.SceneRenderer", StubRenderer)

    frame_count = _render_frames(
        lesson,
        timeline,
        tmp_path / "phrase-caption-frames",
        fps=4,
        visual_timelines=[[]],
    )

    assert frame_count == 13
    assert [shown_captions[index][0] for index in (0, 4, 8)] == [
        "Alpha begins.", "Bravo follows.", "Charlie finishes.",
    ]
    assert shown_captions[0][1] == 0
    assert shown_captions[-1][2] is False


def test_video_caption_panel_is_hidden_during_the_silent_scene_pause(monkeypatch, tmp_path: Path):
    caption_visibility = []

    class StubFrame:
        size = (WIDTH, HEIGHT)

        def save(self, *_args, **_kwargs):
            return None

    class StubRenderer:
        def render(self, _scene, **kwargs):
            caption_visibility.append(kwargs["caption_visible"])
            return StubFrame()

    lesson = sample_lesson()
    timeline = build_timeline(lesson.scenes[:1], [0.1])
    monkeypatch.setattr("backend.services.export_service.SceneRenderer", StubRenderer)

    frame_count = _render_frames(
        lesson,
        timeline,
        tmp_path / "caption-frames",
        fps=4,
        visual_timelines=[[]],
    )

    assert frame_count == 3
    assert caption_visibility == [True, False, False]


def test_ffprobe_verifier_requires_720p_h264_aac_and_24fps(monkeypatch, tmp_path: Path):
    payload = {
        "format": {"duration": "31.25"},
        "streams": [
            {
                "codec_type": "video",
                "codec_name": "h264",
                "width": 1280,
                "height": 720,
                "r_frame_rate": "24/1",
                "avg_frame_rate": "24/1",
            },
            {"codec_type": "audio", "codec_name": "aac"},
        ],
    }
    monkeypatch.setattr(
        "backend.services.export_service.subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout=json.dumps(payload), stderr=""),
    )

    info = verify_mp4(tmp_path / "sample.mp4", ffprobe_path="ffprobe")

    assert info == {
        "duration_seconds": 31.25,
        "width": 1280,
        "height": 720,
        "frame_rate": "24/1",
        "video_codec": "h264",
        "audio_codec": "aac",
    }


def test_ffprobe_verifier_rejects_wrong_video_codec(monkeypatch, tmp_path: Path):
    payload = {
        "format": {"duration": "31.25"},
        "streams": [
            {
                "codec_type": "video",
                "codec_name": "vp9",
                "width": 1280,
                "height": 720,
                "r_frame_rate": "24/1",
            },
            {"codec_type": "audio", "codec_name": "aac"},
        ],
    }
    monkeypatch.setattr(
        "backend.services.export_service.subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout=json.dumps(payload), stderr=""),
    )

    with pytest.raises(RuntimeError, match="1280x720 H.264"):
        verify_mp4(tmp_path / "sample.mp4", ffprobe_path="ffprobe")
