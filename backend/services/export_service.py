"""Measured narration timeline, frame rendering, and MP4 export."""

from __future__ import annotations

import json
import logging
import math
import os
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Protocol

import numpy as np
import soundfile as sf

from backend.schemas import Lesson, Scene
from backend.services.duration_budget import (
    DurationBudgetError,
    enforce_narration_budget,
    narrator_engine,
    speech_budget_seconds,
    spoken_length,
    split_sentences,
    tolerance_seconds,
    trim_to_char_budget,
)
from backend.services.scene_renderer import HEIGHT, WIDTH, SceneRenderer
from backend.services.visual_registry import (
    build_code_execution_timeline,
    visual_state_at_progress,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
FPS = 24
logger = logging.getLogger(__name__)


class Narrator(Protocol):
    def synthesize(self, text: str, *, voice: str, language: str, speed: float) -> tuple[np.ndarray, int]: ...


@dataclass(frozen=True)
class TimelineEntry:
    scene: Scene
    audio_seconds: float
    pause_seconds: float
    start_seconds: float
    end_seconds: float


@dataclass(frozen=True)
class CaptionCue:
    text: str
    start_seconds: float
    end_seconds: float


@dataclass(frozen=True)
class ExportResult:
    video_path: Path
    captions_path: Path
    manifest_path: Path
    duration_seconds: float
    width: int
    height: int
    fps: int
    codec: str
    audio_codec: str
    stage_seconds: dict[str, float]
    timeline: list[TimelineEntry]
    target_duration_seconds: int = 0
    within_tolerance: bool = True
    duration_corrections: list[dict[str, object]] | None = None
    speech_seconds: float = 0.0
    pause_seconds: float = 0.0


def build_timeline(scenes: list[Scene], measured_audio_seconds: list[float]) -> list[TimelineEntry]:
    if not scenes or len(scenes) != len(measured_audio_seconds):
        raise ValueError("Each scene must have one measured narration duration.")
    timeline: list[TimelineEntry] = []
    cursor = 0.0
    for scene, audio_seconds in zip(scenes, measured_audio_seconds, strict=True):
        if not math.isfinite(audio_seconds) or audio_seconds <= 0:
            raise ValueError("Measured narration durations must be positive and finite.")
        pause = scene.pause_seconds
        end = cursor + audio_seconds + pause
        timeline.append(TimelineEntry(scene, audio_seconds, pause, cursor, end))
        cursor = end
    return timeline


def _timestamp_srt(seconds: float) -> str:
    milliseconds = round(seconds * 1000)
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1000)
    return f"{hours:02}:{minutes:02}:{secs:02},{millis:03}"


def build_caption_cues(
    narration: str,
    *,
    start_seconds: float,
    audio_seconds: float,
    max_characters: int = 48,
    max_words: int = 8,
) -> list[CaptionCue]:
    """Break spoken narration into readable cues across its measured audio span.

    The TTS engines return scene audio without word timestamps. Cue boundaries
    therefore follow spoken text length over the measured utterance duration;
    this keeps the visible words in the same order and approximately the same
    cadence as the narration without additional synthesis or alignment models.
    """
    sentences = split_sentences(narration)
    chunks: list[str] = []
    for sentence in sentences or [narration.strip()]:
        current: list[str] = []
        for word in sentence.split():
            candidate = " ".join((*current, word))
            if current and (len(candidate) > max_characters or len(current) >= max_words):
                chunks.append(" ".join(current))
                current = [word]
            else:
                current.append(word)
        if current:
            chunks.append(" ".join(current))

    chunks = [chunk for chunk in chunks if chunk]
    if not chunks:
        chunks = [narration.strip() or " "]
    weights = [max(1, spoken_length(chunk)) for chunk in chunks]
    total_weight = sum(weights)
    cues: list[CaptionCue] = []
    elapsed_weight = 0
    for index, (chunk, weight) in enumerate(zip(chunks, weights, strict=True)):
        cue_start = start_seconds + audio_seconds * elapsed_weight / total_weight
        elapsed_weight += weight
        cue_end = (
            start_seconds + audio_seconds
            if index == len(chunks) - 1
            else start_seconds + audio_seconds * elapsed_weight / total_weight
        )
        cues.append(CaptionCue(chunk, cue_start, cue_end))
    return cues


def _caption_cues_for_timeline(timeline: list[TimelineEntry]) -> list[list[CaptionCue]]:
    return [
        build_caption_cues(
            entry.scene.narration,
            start_seconds=entry.start_seconds,
            audio_seconds=entry.audio_seconds,
        )
        for entry in timeline
    ]


def _write_srt(
    path: Path,
    timeline: list[TimelineEntry],
    caption_timelines: list[list[CaptionCue]] | None = None,
) -> None:
    cues = []
    caption_index = 0
    for scene_cues in caption_timelines or _caption_cues_for_timeline(timeline):
        for cue in scene_cues:
            caption_index += 1
            cues.extend((
                str(caption_index),
                f"{_timestamp_srt(cue.start_seconds)} --> {_timestamp_srt(cue.end_seconds)}",
                cue.text,
                "",
            ))
    path.write_text("\n".join(cues), encoding="utf-8")


def _make_audio(narrations: list[tuple[np.ndarray, int]], timeline: list[TimelineEntry], path: Path) -> None:
    sample_rates = {sample_rate for _, sample_rate in narrations}
    if len(sample_rates) != 1:
        raise ValueError("All narration segments must use the same sample rate.")
    sample_rate = sample_rates.pop()
    parts: list[np.ndarray] = []
    for (samples, rate), entry in zip(narrations, timeline, strict=True):
        if rate != sample_rate:
            raise ValueError("Narration sample rate changed between scenes.")
        parts.append(np.asarray(samples, dtype=np.float32))
        silence_length = round(entry.pause_seconds * sample_rate)
        if silence_length:
            parts.append(np.zeros(silence_length, dtype=np.float32))
    sf.write(path, np.concatenate(parts), sample_rate, subtype="PCM_16")


def _render_frames(
    lesson: Lesson,
    timeline: list[TimelineEntry],
    frames_dir: Path,
    *,
    fps: int = FPS,
    visual_timelines: list[list[dict[str, object]]] | None = None,
    caption_timelines: list[list[CaptionCue]] | None = None,
) -> int:
    renderer = SceneRenderer()
    total_duration = timeline[-1].end_seconds
    # Keep one full frame beyond the audio boundary so container packet rounding
    # cannot shorten the final AAC samples under FFmpeg's -shortest option.
    frame_count = max(1, math.ceil(total_duration * fps) + 1)
    frames_dir.mkdir(parents=True, exist_ok=False)
    if visual_timelines is None:
        visual_timelines = [
            build_code_execution_timeline(entry.scene.execution_data)
            if entry.scene.visual_type == "code_execution" and entry.scene.execution_data is not None
            else []
            for entry in timeline
        ]
    caption_timelines = caption_timelines or _caption_cues_for_timeline(timeline)
    entry_index = 0
    for frame_index in range(frame_count):
        timestamp = frame_index / fps
        while entry_index < len(timeline) - 1 and timestamp >= timeline[entry_index].end_seconds:
            entry_index += 1
        entry = timeline[entry_index]
        local_time = max(0.0, timestamp - entry.start_seconds)
        local_progress = min(1.0, local_time / entry.audio_seconds)
        cue = next(
            (
                item for item in caption_timelines[entry_index]
                if item.start_seconds <= timestamp < item.end_seconds
            ),
            caption_timelines[entry_index][-1],
        )
        caption_progress = min(
            1.0,
            max(0.0, (timestamp - cue.start_seconds) / max(0.001, cue.end_seconds - cue.start_seconds)),
        )
        total_progress = min(1.0, timestamp / total_duration)
        visual_state = visual_state_at_progress(visual_timelines[entry_index], local_progress)
        frame = renderer.render(
            entry.scene,
            scene_progress=local_progress,
            lesson_progress=total_progress,
            scene_number=entry_index + 1,
            scene_count=len(lesson.scenes),
            visual_state=visual_state,
            caption_visible=local_time < entry.audio_seconds,
            caption_text=cue.text,
            caption_progress=caption_progress,
        )
        if frame.size != (WIDTH, HEIGHT):
            raise RuntimeError("Scene renderer returned a frame with the wrong dimensions.")
        frame.save(frames_dir / f"frame-{frame_index:06d}.png", format="PNG", optimize=False)
    return frame_count


def verify_mp4(path: Path, ffprobe_path: str | None = None) -> dict[str, object]:
    """Fail closed unless FFprobe confirms the required video and audio streams."""
    ffprobe = ffprobe_path or os.getenv("FFPROBE_BIN") or shutil.which("ffprobe")
    if not ffprobe:
        raise FileNotFoundError("FFprobe is not available on PATH; set FFPROBE_BIN to its executable.")
    result = subprocess.run(
        [
            ffprobe,
            "-v",
            "error",
            "-show_entries",
            "format=duration:stream=codec_type,codec_name,width,height,r_frame_rate,avg_frame_rate",
            "-of",
            "json",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"FFprobe could not inspect the exported MP4: {result.stderr.strip()}")
    info = json.loads(result.stdout)
    streams = info.get("streams", [])
    video = next((stream for stream in streams if stream.get("codec_type") == "video"), None)
    audio = next((stream for stream in streams if stream.get("codec_type") == "audio"), None)
    if not video or not audio:
        raise RuntimeError("FFprobe found no video or audio stream in the exported MP4.")
    if video.get("codec_name") != "h264" or (video.get("width"), video.get("height")) != (WIDTH, HEIGHT):
        raise RuntimeError("FFprobe found a video stream that does not match 1280x720 H.264.")
    if audio.get("codec_name") != "aac":
        raise RuntimeError("FFprobe found an audio stream that is not AAC.")
    frame_rate = video.get("avg_frame_rate") or video.get("r_frame_rate")
    if not frame_rate or frame_rate in {"0/0", "N/A"}:
        raise RuntimeError("FFprobe could not determine the exported video frame rate.")
    if abs(float(Fraction(frame_rate)) - FPS) > 0.01:
        raise RuntimeError(f"FFprobe found {frame_rate} fps; expected {FPS} fps.")
    duration = float(info.get("format", {}).get("duration", 0))
    if duration <= 0:
        raise RuntimeError("FFprobe found an invalid MP4 duration.")
    return {
        "duration_seconds": duration,
        "width": int(video["width"]),
        "height": int(video["height"]),
        "frame_rate": frame_rate,
        "video_codec": video["codec_name"],
        "audio_codec": audio["codec_name"],
    }


def export_lesson(
    lesson: Lesson,
    narrator: Narrator,
    output_path: Path,
    *,
    voice: str = "hf_alpha",
    language: str = "en-us",
    speed: float = 1.0,
    ffmpeg_path: str | None = None,
    upstream_stage_seconds: dict[str, float] | None = None,
    narration_grow_pool: dict[int, list[str]] | None = None,
) -> ExportResult:
    """Synthesize, measure, render, and export one lesson without fixed scene timings."""
    output_path = output_path.resolve()
    captions_path = output_path.with_suffix(".srt")
    manifest_path = output_path.with_suffix(".json")
    for path in (output_path, captions_path, manifest_path):
        if path.exists():
            raise FileExistsError(f"Refusing to overwrite an existing output: {path}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg = ffmpeg_path or os.getenv("FFMPEG_BIN") or shutil.which("ffmpeg")
    if not ffmpeg:
        raise FileNotFoundError("FFmpeg is not available on PATH; set FFMPEG_BIN to its executable.")

    stage_seconds: dict[str, float] = {
        "tts_initialization": float(getattr(narrator, "initialization_seconds", 0.0))
    }
    if upstream_stage_seconds:
        stage_seconds.update(upstream_stage_seconds)
    total_start = time.monotonic()
    target = lesson.target_duration_seconds
    engine = narrator_engine(narrator)
    # The selected duration is a real budget: trim over-length narration before
    # any expensive synthesis, and record every correction for the manifest.
    working_lesson, duration_corrections = enforce_narration_budget(lesson, engine)
    working_scenes: list[Scene] = list(working_lesson.scenes)
    generated: list[tuple[np.ndarray, int]] = []

    def _synthesize(index: int) -> tuple[np.ndarray, int]:
        synthesis_start = time.monotonic()
        audio = narrator.synthesize(
            working_scenes[index].narration, voice=voice, language=language, speed=speed
        )
        stage_seconds["narration"] = stage_seconds.get("narration", 0.0) + (
            time.monotonic() - synthesis_start
        )
        return audio

    stage_seconds["narration"] = 0.0
    for index in range(len(working_scenes)):
        generated.append(_synthesize(index))
    stage_seconds["tts_synthesis"] = stage_seconds["narration"]

    with tempfile.TemporaryDirectory(prefix="blu-lesson-", dir=output_path.parent) as temp:
        work_dir = Path(temp)
        audio_path = work_dir / "narration.wav"

        def _measure_and_build_timeline() -> tuple[list[float], list[TimelineEntry]]:
            measured: list[float] = []
            for index in range(len(working_scenes)):
                # Audio slices are recorded exactly in the PCM file; reread each isolated
                # utterance duration before establishing the timeline.
                samples, rate = generated[index]
                isolated_path = work_dir / f"scene-{index:02d}.wav"
                sf.write(isolated_path, samples, rate, subtype="PCM_16")
                measured.append(float(sf.info(isolated_path).duration))
            return measured, build_timeline(working_scenes, measured)

        measured, timeline = _measure_and_build_timeline()
        tolerance = tolerance_seconds(target)

        def run_measured_growth() -> None:
            """Grow under-running scenes from the authored pool using MEASURED
            per-scene speaking rates. One sentence per scene per sweep, with a
            real re-measure after every addition (per-sentence rates vary far
            too much for stale numbers to bound the budget). The shrink pass
            still guards against overshoot afterwards.
            """
            nonlocal measured, timeline
            if not narration_grow_pool:
                return
            if timeline[-1].end_seconds >= target * 0.90:
                return
            budget_speech = speech_budget_seconds(working_lesson)
            # Pacing cap keeps scenes balanced, but with real headroom: a long
            # pooled sentence must still be addable, otherwise growth starves
            # while the budget has room and the lesson lands far under target.
            share = budget_speech / max(1, len(working_scenes))
            scene_cap = max(3.0, share * 1.35, share + 6.0)
            grew = True
            while grew:
                grew = False
                for index in sorted(narration_grow_pool):
                    pool = narration_grow_pool.get(index)
                    if not pool:
                        continue
                    if measured[index] <= 0.05:
                        continue
                    scene_rate = (
                        spoken_length(working_scenes[index].narration) / measured[index]
                    )
                    sentence = pool[0]
                    projected = spoken_length(sentence) / scene_rate
                    logger.debug(
                        "grow try scene=%d measured=%.2f projected=%.2f cap=%.2f sum=%.2f budget=%.2f pool=%d",
                        index, measured[index], projected, scene_cap,
                        sum(measured), budget_speech, len(pool),
                    )
                    if measured[index] + projected > scene_cap:
                        logger.debug("grow skip scene=%d (scene cap)", index)
                        continue
                    if sum(measured) + projected > budget_speech:
                        logger.debug("grow skip scene=%d (budget)", index)
                        continue
                    del pool[0]
                    working_scenes[index] = working_scenes[index].model_copy(
                        update={
                            "narration": f"{working_scenes[index].narration} {sentence}".strip()
                        }
                    )
                    generated[index] = _synthesize(index)
                    duration_corrections.append(
                        {
                            "stage": "post_growth",
                            "scene_index": index,
                            "added_sentence": sentence,
                            "scene_rate_chars_per_second": round(scene_rate, 2),
                        }
                    )
                    grew = True
                    # Re-measure after EVERY addition: one sentence can swing
                    # the composition's pace, and an overshooting sweep would
                    # trigger the shrink pass and undo the growth.
                    measured, timeline = _measure_and_build_timeline()

        run_measured_growth()

        if timeline[-1].end_seconds > tolerance:
            # One controlled correction: rebuild scene budgets from the measured
            # audio, trim only what still does not fit, and re-synthesize exactly
            # those scenes. If even one sentence per scene cannot fit, fail loudly
            # instead of silently exporting an oversized video.
            scale = speech_budget_seconds(working_lesson) / sum(measured)
            for index, scene in enumerate(working_scenes):
                new_budget = int(spoken_length(scene.narration) * scale)
                if new_budget >= spoken_length(scene.narration):
                    continue
                trimmed, dropped = trim_to_char_budget(scene.narration, new_budget)
                if spoken_length(trimmed) >= spoken_length(scene.narration):
                    continue
                trimmed_caption, _ = trim_to_char_budget(scene.caption, spoken_length(trimmed))
                duration_corrections.append(
                    {
                        "stage": "post_synthesis",
                        "scene_index": index,
                        "measured_audio_seconds": round(measured[index], 2),
                        "budget_characters": new_budget,
                        "dropped_sentences": dropped,
                    }
                )
                working_scenes[index] = scene.model_copy(
                    update={"narration": trimmed, "caption": trimmed_caption}
                )
                generated[index] = _synthesize(index)
            measured, timeline = _measure_and_build_timeline()
            # Shrinking by whole sentences can undershoot (kept sentences may
            # speak faster than the dropped ones); top back up from the pool.
            run_measured_growth()
            logger.info(
                "duration: after measured correction total=%.2f tolerance=%.2f corrections=%d",
                timeline[-1].end_seconds, tolerance, len(duration_corrections),
            )
            if timeline[-1].end_seconds > tolerance:
                raise DurationBudgetError(
                    f"Narration for a {target}-second lesson still measures "
                    f"{timeline[-1].end_seconds:.1f}s after budget trimming; refusing to "
                    "export an oversized video. Pick a longer target or a shorter topic."
                )

        speech_seconds = sum(measured)
        total_pauses = sum(scene.pause_seconds for scene in working_scenes)
        _make_audio(generated, timeline, audio_path)
        working_lesson = working_lesson.model_copy(update={"scenes": working_scenes})
        visual_timelines = [
            build_code_execution_timeline(entry.scene.execution_data)
            if entry.scene.visual_type == "code_execution" and entry.scene.execution_data is not None
            else []
            for entry in timeline
        ]
        caption_timelines = _caption_cues_for_timeline(timeline)

        render_start = time.monotonic()
        frames_dir = work_dir / "frames"
        frame_count = _render_frames(
            working_lesson,
            timeline,
            frames_dir,
            visual_timelines=visual_timelines,
            caption_timelines=caption_timelines,
        )
        stage_seconds["scene_render"] = time.monotonic() - render_start

        encode_start = time.monotonic()
        command = [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-n",
            "-framerate",
            str(FPS),
            "-i",
            str(frames_dir / "frame-%06d.png"),
            "-i",
            str(audio_path),
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "21",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "160k",
            "-movflags",
            "+faststart",
            "-shortest",
            str(output_path),
        ]
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            raise RuntimeError(f"FFmpeg export failed: {result.stderr.strip()}")
        stage_seconds["encode"] = time.monotonic() - encode_start

        verify_start = time.monotonic()
        media_info = verify_mp4(output_path)
        stage_seconds["ffprobe_verification"] = time.monotonic() - verify_start

        _write_srt(captions_path, timeline, caption_timelines)
        stage_seconds["total"] = time.monotonic() - total_start
        output_duration = float(media_info["duration_seconds"])
        duration_within_tolerance = output_duration <= tolerance
        manifest = {
            "lesson_id": lesson.id,
            "topic": lesson.topic,
            "source": lesson.source,
            "voice": voice,
            "voice_language": language,
            "audio_sample_rate_hz": generated[0][1],
            "duration_seconds": output_duration,
            "target_duration_seconds": target,
            "duration_within_tolerance": duration_within_tolerance,
            "speech_seconds": round(speech_seconds, 3),
            "pause_seconds": round(total_pauses, 3),
            "duration_corrections": duration_corrections,
            "dimensions": [media_info["width"], media_info["height"]],
            "frame_rate": media_info["frame_rate"],
            "video_codec": media_info["video_codec"],
            "audio_codec": media_info["audio_codec"],
            "timing_basis": (
                "Measured duration of each synthesized scene WAV plus the validated scene "
                "pause; narration is budgeted against the requested target duration."
            ),
            "caption_timing_basis": (
                "Caption text comes from narration; cue intervals follow spoken-text length "
                "across each scene's measured TTS audio duration."
            ),
            "stages_seconds": stage_seconds,
            "scenes": [
                {
                    "title": item.scene.title,
                    "start_seconds": item.start_seconds,
                    "audio_seconds": item.audio_seconds,
                    "pause_seconds": item.pause_seconds,
                    "end_seconds": item.end_seconds,
                    "captions": [
                        {
                            "text": cue.text,
                            "start_seconds": cue.start_seconds,
                            "end_seconds": cue.end_seconds,
                        }
                        for cue in caption_timelines[index]
                    ],
                    "visual_timeline": visual_timelines[index],
                }
                for index, item in enumerate(timeline)
            ],
        }
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    return ExportResult(
        video_path=output_path,
        captions_path=captions_path,
        manifest_path=manifest_path,
        duration_seconds=output_duration,
        width=WIDTH,
        height=HEIGHT,
        fps=FPS,
        codec="h264",
        audio_codec="aac",
        stage_seconds=stage_seconds,
        timeline=timeline,
        target_duration_seconds=target,
        within_tolerance=duration_within_tolerance,
        duration_corrections=duration_corrections,
        speech_seconds=speech_seconds,
        pause_seconds=total_pauses,
    )
