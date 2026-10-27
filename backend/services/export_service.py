"""Measured narration timeline, frame rendering, and MP4 export."""

from __future__ import annotations

import json
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
from backend.services.scene_renderer import HEIGHT, WIDTH, SceneRenderer
from backend.services.visual_registry import (
    build_code_execution_timeline,
    visual_state_at_progress,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
FPS = 24


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


def _write_srt(path: Path, timeline: list[TimelineEntry]) -> None:
    cues = []
    for index, item in enumerate(timeline, start=1):
        start = item.start_seconds
        end = start + item.audio_seconds
        cues.extend((str(index), f"{_timestamp_srt(start)} --> {_timestamp_srt(end)}", item.scene.caption, ""))
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
    entry_index = 0
    for frame_index in range(frame_count):
        timestamp = frame_index / fps
        while entry_index < len(timeline) - 1 and timestamp >= timeline[entry_index].end_seconds:
            entry_index += 1
        entry = timeline[entry_index]
        local_time = max(0.0, timestamp - entry.start_seconds)
        local_progress = min(1.0, local_time / entry.audio_seconds)
        total_progress = min(1.0, timestamp / total_duration)
        visual_state = visual_state_at_progress(visual_timelines[entry_index], local_progress)
        frame = renderer.render(
            entry.scene,
            scene_progress=local_progress,
            lesson_progress=total_progress,
            scene_number=entry_index + 1,
            scene_count=len(lesson.scenes),
            visual_state=visual_state,
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
    total_start = time.monotonic()
    audio_start = time.monotonic()
    generated: list[tuple[np.ndarray, int]] = []
    for scene in lesson.scenes:
        generated.append(
            narrator.synthesize(scene.narration, voice=voice, language=language, speed=speed)
        )
    stage_seconds["narration"] = time.monotonic() - audio_start
    stage_seconds["tts_synthesis"] = stage_seconds["narration"]

    with tempfile.TemporaryDirectory(prefix="blu-lesson-", dir=output_path.parent) as temp:
        work_dir = Path(temp)
        audio_path = work_dir / "narration.wav"
        measured: list[float] = []
        for index in range(len(lesson.scenes)):
            # Audio slices are recorded exactly in the PCM file; reread each isolated
            # utterance duration before establishing the timeline.
            samples, rate = generated[index]
            isolated_path = work_dir / f"scene-{index:02d}.wav"
            sf.write(isolated_path, samples, rate, subtype="PCM_16")
            measured.append(float(sf.info(isolated_path).duration))
        timeline = build_timeline(lesson.scenes, measured)
        _make_audio(generated, timeline, audio_path)
        visual_timelines = [
            build_code_execution_timeline(entry.scene.execution_data)
            if entry.scene.visual_type == "code_execution" and entry.scene.execution_data is not None
            else []
            for entry in timeline
        ]

        render_start = time.monotonic()
        frames_dir = work_dir / "frames"
        frame_count = _render_frames(
            lesson, timeline, frames_dir, visual_timelines=visual_timelines
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

        _write_srt(captions_path, timeline)
        stage_seconds["total"] = time.monotonic() - total_start
        output_duration = float(media_info["duration_seconds"])
        manifest = {
            "lesson_id": lesson.id,
            "topic": lesson.topic,
            "source": lesson.source,
            "voice": voice,
            "voice_language": language,
            "audio_sample_rate_hz": generated[0][1],
            "duration_seconds": output_duration,
            "dimensions": [media_info["width"], media_info["height"]],
            "frame_rate": media_info["frame_rate"],
            "video_codec": media_info["video_codec"],
            "audio_codec": media_info["audio_codec"],
            "timing_basis": "Measured duration of each synthesized scene WAV plus the validated scene pause.",
            "stages_seconds": stage_seconds,
            "scenes": [
                {
                    "title": item.scene.title,
                    "start_seconds": item.start_seconds,
                    "audio_seconds": item.audio_seconds,
                    "pause_seconds": item.pause_seconds,
                    "end_seconds": item.end_seconds,
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
    )
