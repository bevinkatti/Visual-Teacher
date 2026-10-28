"""Duration-budget regression tests: deterministic, no real TTS or FFmpeg.

The fake narrator produces PCM whose duration is exactly proportional to the
spoken-length model the budget estimator uses, so the pipeline's measured
timeline is verifiable without model loads. FFmpeg/ffprobe are stubbed; the
probe reports the true duration of the assembled narration WAV, so duration
assertions exercise the real audio-assembly code path.
"""

import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
import soundfile as sf

from backend.schemas import LessonRequest, Scene
from backend.services.duration_budget import (
    DEFAULT_SPEAKING_RATES,
    DurationBudgetError,
    enforce_narration_budget,
    plan_narration_budget,
    speaking_rate,
    split_sentences,
    spoken_length,
    tolerance_seconds,
    trim_to_char_budget,
    within_tolerance,
)
from backend.services.export_service import export_lesson
from backend.services.lesson_service import build_sample_lesson, build_sample_lesson_with_pool
from backend.services.ollama_planner import planner_word_budget
from backend.services.render_jobs import RenderJobManager


class ManualExecutor:
    def __init__(self):
        self.tasks = []

    def submit(self, fn, /, *args, **kwargs):
        self.tasks.append((fn, args, kwargs))

    def run_next(self):
        fn, args, kwargs = self.tasks.pop(0)
        fn(*args, **kwargs)


class FakeNarrator:
    """Deterministic narrator: seconds = spoken_length / (rate / slow_factor)."""

    engine_name = "kokoro"

    def __init__(
        self,
        engine: str = "kokoro",
        inflate_first: int = 0,
        inflate_factor: float = 1.0,
        slow_factor: float = 1.0,
        fast_factor: float = 1.0,
    ):
        self.engine_name = engine
        self.inflate_first = inflate_first
        self.inflate_factor = inflate_factor
        self.slow_factor = slow_factor
        self.fast_factor = fast_factor
        self.calls: list[str] = []

    def synthesize(self, text: str, *, voice: str = "", language: str = "en", speed: float = 1.0):
        self.calls.append(str(text))
        rate = speaking_rate(self.engine_name, language) / self.slow_factor * self.fast_factor
        seconds = spoken_length(" ".join(str(text).split())) / rate
        if len(self.calls) <= self.inflate_first:
            seconds *= self.inflate_factor
        return np.full(int(seconds * 16000), 0.01, dtype=np.float32), 16000


def stub_ffmpeg_and_frames(monkeypatch):
    """Stub FFmpeg encode + FFprobe probe; probe reports the real WAV duration."""
    durations: dict[str, float] = {}

    def fake_run(command, capture_output=True, text=True, check=False):
        exe = Path(command[0]).name.lower()
        if exe.startswith("ffmpeg"):
            # The audio WAV is the second -i input; output is last.
            second_i = command.index("-i", command.index("-i") + 1)
            audio_path = Path(command[second_i + 1])
            output_path = Path(command[-1])
            output_path.write_bytes(b"fake-mp4-bytes")
            durations[str(output_path)] = float(sf.info(audio_path).duration)
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        payload = {
            "format": {"duration": f"{durations[str(command[-1])]:.6f}"},
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
        return SimpleNamespace(returncode=0, stdout=json.dumps(payload), stderr="")

    monkeypatch.setattr("backend.services.export_service.subprocess.run", fake_run)
    monkeypatch.setattr(
        "backend.services.export_service._render_frames", lambda *args, **kwargs: 1
    )


def test_trim_keeps_first_sentence_even_when_over_budget():
    trimmed, dropped = trim_to_char_budget("First idea. Second point. Third point.", 10)
    assert trimmed == "First idea."
    assert dropped == 2


def test_trim_never_returns_empty_text():
    trimmed, dropped = trim_to_char_budget("एक ही वाक्य।", 2)
    assert trimmed == "एक ही वाक्य।"
    assert dropped == 0


def test_plan_and_enforce_trim_oversized_narration():
    lesson = build_sample_lesson(
        LessonRequest(topic="How does a Python loop work?", duration_seconds=30)
    )
    long_scene = Scene(
        title=lesson.scenes[0].title,
        narration="One sentence. " * 40,
        caption=lesson.scenes[0].caption,
        visual_type="concept_diagram",
    )
    oversized = lesson.model_copy(
        update={"scenes": [long_scene, *lesson.scenes[1:]]}
    )
    trimmed, corrections = enforce_narration_budget(oversized, "kokoro")

    assert corrections and all(item["stage"] == "pre_synthesis" for item in corrections)
    plan = plan_narration_budget(trimmed, speaking_rate("kokoro", trimmed.language))
    # Per-scene sentence floors can keep the estimate slightly above the strict
    # budget; what matters is that it now sits inside the export tolerance.
    assert plan.estimated_total_seconds <= tolerance_seconds(30)
    assert spoken_length(trimmed.scenes[0].narration) < spoken_length(
        oversized.scenes[0].narration
    )
    # Captions never promise more than the trimmed narration says.
    assert spoken_length(trimmed.scenes[0].caption) <= spoken_length(
        trimmed.scenes[0].narration
    )


@pytest.mark.parametrize("language", ["en", "hi", "kn"])
@pytest.mark.parametrize("target", [30, 45, 60, 90])
def test_requested_duration_matches_export_for_all_twelve_combos(
    language, target, tmp_path, monkeypatch
):
    stub_ffmpeg_and_frames(monkeypatch)
    lesson = build_sample_lesson(
        LessonRequest(
            topic="How does a Python loop work?", language=language, duration_seconds=target
        )
    )
    narrator = FakeNarrator(engine="parler" if language == "kn" else "kokoro")

    result = export_lesson(
        lesson,
        narrator,
        tmp_path / "lesson.mp4",
        voice="voice",
        language=language,
    )

    # Acceptance: a rendered lesson must never blow past its target (+10%).
    assert result.duration_seconds <= target * 1.10 + 0.05, (
        f"{language} {target}s exported {result.duration_seconds:.1f}s"
    )
    assert result.within_tolerance
    # A sanity floor: the fallback lesson may run short, never silent-short.
    assert result.duration_seconds >= target * 0.4
    # Speech plus intentional pauses equals the assembled narration exactly.
    assert result.speech_seconds + result.pause_seconds == pytest.approx(
        result.duration_seconds, abs=0.05
    )
    # Each scene was synthesized exactly once and appears exactly once.
    assert len(narrator.calls) == len(lesson.scenes)
    assert len(result.timeline) == len(lesson.scenes)
    assert result.target_duration_seconds == target


def test_export_corrects_measured_overshoot_with_one_resynthesis_round(
    tmp_path, monkeypatch
):
    stub_ffmpeg_and_frames(monkeypatch)
    lesson = build_sample_lesson(
        LessonRequest(topic="How does a Python loop work?", duration_seconds=90)
    )
    # First synthesis round runs 1.6x long (estimation error), later calls are
    # exact; the multi-sentence 90s scenes leave room for sentence trimming.
    narrator = FakeNarrator("kokoro", inflate_first=4, inflate_factor=1.6)

    result = export_lesson(
        lesson, narrator, tmp_path / "lesson.mp4", voice="voice", language="en"
    )

    post = [item for item in result.duration_corrections if item["stage"] == "post_synthesis"]
    assert post, "expected a measured post-synthesis correction"
    assert len(narrator.calls) > 4, "offending scenes must be re-synthesized"
    assert result.duration_seconds <= 99.0
    assert result.within_tolerance


def test_export_fails_loudly_when_narration_cannot_fit(tmp_path, monkeypatch):
    stub_ffmpeg_and_frames(monkeypatch)
    lesson = build_sample_lesson(
        LessonRequest(topic="How does a Python loop work?", duration_seconds=30)
    )
    slow_narrator = FakeNarrator("kokoro", slow_factor=10.0)

    with pytest.raises(DurationBudgetError, match="30-second lesson"):
        export_lesson(
            lesson, slow_narrator, tmp_path / "lesson.mp4", voice="voice", language="en"
        )


def test_export_grows_under_running_samples_using_measured_rates(
    tmp_path, monkeypatch
):
    stub_ffmpeg_and_frames(monkeypatch)
    lesson, grow_pool = build_sample_lesson_with_pool(
        LessonRequest(topic="How does a Python loop work?", duration_seconds=30)
    )
    assert grow_pool, "authored samples must keep an unused pool tail"
    # The narrator speaks 1.6x faster than the calibrated rate, so the first
    # measure under-runs; the exporter must grow scenes back toward the target.
    narrator = FakeNarrator("kokoro", fast_factor=1.6)

    result = export_lesson(
        lesson,
        narrator,
        tmp_path / "lesson.mp4",
        voice="voice",
        language="en",
        narration_grow_pool=grow_pool,
    )

    growth = [item for item in result.duration_corrections if item["stage"] == "post_growth"]
    assert growth, "under-running narration must grow from the pool"
    assert len(narrator.calls) > len(lesson.scenes)
    assert result.duration_seconds >= 27.0
    assert result.within_tolerance
    # Grown scenes stay balanced: no scene may hog the lesson.
    scene_audios = [entry.audio_seconds for entry in result.timeline]
    assert max(scene_audios) <= min(scene_audios) * 3 + 1.0


def test_export_tolerates_under_run_when_no_grow_pool_exists(tmp_path, monkeypatch):
    stub_ffmpeg_and_frames(monkeypatch)
    lesson = build_sample_lesson(
        LessonRequest(topic="How does a Python loop work?", duration_seconds=30)
    )
    narrator = FakeNarrator("kokoro", fast_factor=1.6)

    result = export_lesson(
        lesson, narrator, tmp_path / "lesson.mp4", voice="voice", language="en"
    )

    # Model-planned lessons cannot grow: under-run is honest, overshoot is not.
    assert result.duration_seconds < 27.0
    assert result.within_tolerance


def test_render_job_reports_a_clear_duration_budget_failure(tmp_path):
    class ManualExecutor:
        def __init__(self):
            self.tasks = []

        def submit(self, fn, /, *args, **kwargs):
            self.tasks.append((fn, args, kwargs))

    def failing_exporter(lesson, narrator, output_path, **kwargs):
        raise DurationBudgetError(
            "Narration for a 30-second lesson still measures 51.0s after budget "
            "trimming; refusing to export an oversized video."
        )

    manager = RenderJobManager(
        media_dir=tmp_path / "media",
        exporter=failing_exporter,
        narrator_factory=object,
        executor=ManualExecutor(),
    )
    lesson = build_sample_lesson(
        LessonRequest(topic="How does a Python loop work?", duration_seconds=30)
    )
    manager.register_lesson(lesson)
    response = manager.start(lesson.id)
    executor_tasks = manager._executor.tasks
    fn, args, kwargs = executor_tasks.pop(0)
    fn(*args, **kwargs)

    job = manager.get_job(response.job_id)
    assert job.status == "failed"
    assert "30-second lesson" in (job.error or "")
    assert job.duration_seconds is None



def test_enforce_keeps_authored_samples_inside_export_tolerance():
    """The filler aims at the full duration, so the guard may shave a sentence."""
    for duration in (30, 45, 60, 90):
        lesson = build_sample_lesson(
            LessonRequest(topic="How does a Python loop work?", duration_seconds=duration)
        )
        enforced, corrections = enforce_narration_budget(lesson, "kokoro")
        plan = plan_narration_budget(enforced, speaking_rate("kokoro", "en"))
        assert plan.estimated_total_seconds <= tolerance_seconds(duration)
        assert all(item["dropped_sentences"] >= 0 for item in corrections)
        # Corrections only ever shorten.
        for scene, original in zip(enforced.scenes, lesson.scenes, strict=True):
            assert spoken_length(scene.narration) <= spoken_length(original.narration)


def test_planner_word_budget_scales_with_target():
    assert planner_word_budget(30) == 102
    assert planner_word_budget(90) == planner_word_budget(30) * 3
