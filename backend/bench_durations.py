"""Real end-to-end requested-vs-actual duration benchmark (uses real TTS).

Runs the production pipeline (sample planning, local translation for kn,
Kokoro/Parler narration, measured timing, Pillow frames, FFmpeg export) for
selected language:duration combos and prints a requested-vs-actual table with
per-stage timings and peak memory.

    .\\.venv\\Scripts\\python.exe -m backend.bench_durations --combos en:30,hi:30,kn:30

Fresh synthesis is distinguished from cached replay in the output: narrators
log cache hits, and repeat runs of the same combo are near-instant.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from backend.schemas import LessonRequest
from backend.services.duration_budget import within_tolerance
from backend.services.export_service import export_lesson, verify_mp4
from backend.services.lesson_service import build_sample_lesson_with_pool
from backend.services.profiling import gpu_status, mb, peak_rss_sampler

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = PROJECT_ROOT / "output" / "bench" / "durations"


def build_lesson(language: str, duration: int):
    """English/Hindi samples with their grow pool; Kannada translates (no pool)."""
    sample, grow_pool = build_sample_lesson_with_pool(
        LessonRequest(topic="How does a Python loop work?", language=language, duration_seconds=duration)
    )
    if language == "en":
        return sample, grow_pool, None
    if language == "hi":
        return sample, grow_pool, None
    from backend.services.translation_service import LessonTranslator

    translator = LessonTranslator()
    translation_start = time.monotonic()
    translated = translator.translate_lesson(sample, "kn")
    return translated, None, {
        "translation_seconds": round(time.monotonic() - translation_start, 2),
        "translation_model_seconds": round(translator.translation_seconds, 2),
    }


def resolve_narrator(language: str):
    if language == "kn":
        from backend.services.indic_narrator import IndicParlerNarrator

        return IndicParlerNarrator(), "kn"
    from backend.services.narration_service import LocalNarrator

    return LocalNarrator(), ("hi" if language == "hi" else "en-us")


def run_combo(language: str, duration: int) -> dict[str, object]:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_path = OUTPUT_DIR / f"bench-{language}-{duration}s.mp4"
    for stale in (
        output_path,
        output_path.with_suffix(".srt"),
        output_path.with_suffix(".json"),
    ):
        if stale.exists():
            stale.unlink()

    build_start = time.monotonic()
    lesson, grow_pool, extra = build_lesson(language, duration)
    narrator, speech_language = resolve_narrator(language)
    build_seconds = time.monotonic() - build_start

    with peak_rss_sampler() as sampler:
        result = export_lesson(
            lesson,
            narrator,
            output_path,
            voice=("" if language == "kn" else "hf_alpha"),
            language=speech_language,
            upstream_stage_seconds=extra,
            narration_grow_pool=grow_pool,
        )
    peak_mb = mb(sampler["bytes"])
    media_info = verify_mp4(output_path)

    return {
        "requested": duration,
        "actual": round(result.duration_seconds, 2),
        "delta_pct": round(100 * (result.duration_seconds / duration - 1), 1),
        "within_tolerance": within_tolerance(result.duration_seconds, duration),
        "speech_seconds": round(result.speech_seconds, 2),
        "pause_seconds": round(result.pause_seconds, 2),
        "corrections": len(result.duration_corrections or []),
        "peak_rss_mb": peak_mb,
        "build_seconds": round(build_seconds, 2),
        "stages_seconds": {
            key: round(value, 2) for key, value in result.stage_seconds.items()
        },
        "narrator_init_seconds": result.stage_seconds.get("tts_initialization", 0.0),
        "ffprobe": {
            "duration": media_info["duration_seconds"],
            "dimensions": f'{media_info["width"]}x{media_info["height"]}',
            "video_codec": media_info["video_codec"],
            "audio_codec": media_info["audio_codec"],
        },
    }


def main() -> int:
    import logging
    import os

    if os.getenv("BLU_DEBUG"):
        logging.basicConfig(level=logging.DEBUG, format="%(name)s %(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--combos",
        default="en:30,en:60,en:90,hi:30,hi:60,hi:90,kn:30",
        help="Comma-separated language:duration pairs.",
    )
    args = parser.parse_args()

    print("GPU status:", json.dumps(gpu_status()))
    rows = []
    for combo in args.combos.split(","):
        language, _, duration_text = combo.strip().partition(":")
        row = run_combo(language, int(duration_text))
        rows.append(row)
        print(
            f"{language} {row['requested']}s -> actual {row['actual']}s "
            f"({row['delta_pct']:+.1f}%) within_tolerance={row['within_tolerance']} "
            f"speech={row['speech_seconds']}s pauses={row['pause_seconds']}s "
            f"corrections={row['corrections']} peak_rss={row['peak_rss_mb']}MB",
            flush=True,
        )
        print(f"  stages: {row['stages_seconds']}", flush=True)

    report_path = OUTPUT_DIR / f"duration-report-{int(time.time())}.json"
    report_path.write_text(json.dumps(rows, indent=2), encoding="utf-8")
    print(f"wrote {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
