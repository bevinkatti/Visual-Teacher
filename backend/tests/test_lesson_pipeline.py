import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
import soundfile as sf

from backend.schemas import LessonRequest
from backend.services.export_service import (
    TimelineEntry,
    _make_audio,
    _render_frames,
    _write_srt,
    build_timeline,
    verify_mp4,
)
from backend.services.lesson_service import build_sample_lesson
from backend.services.render_jobs import _has_requested_script
from backend.services.scene_renderer import HEIGHT, WIDTH, SceneRenderer, _font_for_text


def sample_lesson():
    return build_sample_lesson(
        LessonRequest(topic="How does a Python loop work?", duration_seconds=30)
    )


def test_fixed_sample_is_validated_and_teaches_python_loop_progressively():
    lesson = sample_lesson()

    assert len(lesson.scenes) == 3
    assert [scene.visual_type for scene in lesson.scenes] == [
        "concept_diagram",
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


def test_audio_assembly_includes_scene_pause_and_srt_ends_at_measured_speech(tmp_path: Path):
    scenes = sample_lesson().scenes[:1]
    samples = np.ones(2400, dtype=np.float32)
    timeline = build_timeline(scenes, [0.1])
    audio_path = tmp_path / "audio.wav"
    _make_audio([(samples, 24000)], timeline, audio_path)
    captions_path = tmp_path / "captions.srt"
    _write_srt(captions_path, timeline)

    assert sf.info(audio_path).duration == pytest.approx(0.45, abs=1 / 24000)
    assert "00:00:00,000 --> 00:00:00,100" in captions_path.read_text(encoding="utf-8")


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
