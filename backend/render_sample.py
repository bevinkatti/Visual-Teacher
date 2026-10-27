"""Render the deterministic Python-loop sample as a narrated MP4."""

from __future__ import annotations

import json
from pathlib import Path

from backend.schemas import LessonRequest
from backend.services.export_service import export_lesson
from backend.services.lesson_service import build_sample_lesson
from backend.services.narration_service import LocalNarrator


def main() -> None:
    project_root = Path(__file__).resolve().parents[1]
    lesson = build_sample_lesson(
        LessonRequest(
            topic="How does a Python loop work?",
            level="beginner",
            language="en",
            duration_seconds=30,
        )
    )
    result = export_lesson(
        lesson,
        LocalNarrator(),
        project_root / "output/videos/python-loop-sample.mp4",
        voice="hf_alpha",
        language="en-us",
    )
    print(
        json.dumps(
            {
                "video": str(result.video_path),
                "captions": str(result.captions_path),
                "manifest": str(result.manifest_path),
                "duration_seconds": result.duration_seconds,
                "dimensions": [result.width, result.height],
                "fps": result.fps,
                "video_codec": result.codec,
                "audio_codec": result.audio_codec,
                "stages_seconds": result.stage_seconds,
                "scene_timing": [
                    {
                        "title": row.scene.title,
                        "audio_seconds": row.audio_seconds,
                        "pause_seconds": row.pause_seconds,
                        "start_seconds": row.start_seconds,
                        "end_seconds": row.end_seconds,
                    }
                    for row in result.timeline
                ],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
