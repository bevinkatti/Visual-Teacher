"""Benchmark the local translation and Kannada TTS chain on CPU.

Run after `python -m backend.download_local_models`:

    .\\.venv\\Scripts\\python.exe -m backend.bench_stage4

Prints measured per-stage timings and writes a sample WAV under output/.
"""

from __future__ import annotations

import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

SENTENCES = [
    "A for loop repeats one instruction for every value in a list.",
    "Python reads the loop line first, then assigns the first value to fruit.",
]


def main() -> int:
    from backend.services.indic_narrator import IndicParlerNarrator
    from backend.services.translation_service import LessonTranslator, TranslationUnavailable

    print("== IndicTrans2 translation benchmark ==", flush=True)
    translator = LessonTranslator()
    load_start = time.monotonic()
    try:
        translated = translator.translate_sentences(SENTENCES, "kn")
    except TranslationUnavailable as exc:
        print(f"Translation unavailable: {exc}")
        return 1
    print(f"load_seconds={time.monotonic() - load_start:.2f}")
    print(f"translate_seconds={translator.translation_seconds:.2f} for {len(SENTENCES)} sentences")
    for original, output in zip(SENTENCES, translated, strict=True):
        print(f"  {original}\n  -> {output}")

    print("== Indic Parler-TTS (Kannada) benchmark ==", flush=True)
    narrator = IndicParlerNarrator()
    audio, sample_rate = narrator.synthesize(translated[0], language="kn")
    audio_seconds = len(audio) / sample_rate
    print(f"initialization_seconds={narrator.initialization_seconds:.2f}")
    print(
        f"synthesis_seconds={narrator.synthesis_seconds:.2f} "
        f"audio_seconds={audio_seconds:.2f} "
        f"real_time_factor={narrator.synthesis_seconds / audio_seconds:.1f}x"
    )
    output_path = PROJECT_ROOT / "output" / "bench-kannada.wav"
    import soundfile as sf

    sf.write(output_path, audio, sample_rate)
    print(f"wrote {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
