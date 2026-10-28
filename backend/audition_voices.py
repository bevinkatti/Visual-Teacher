"""Audition candidate third-language voices and English voices (CPU, offline).

    .\\.venv\\Scripts\\python.exe -m backend.audition_voices

Writes WAV clips and a UTF-8 summary under output/audition/ for human review.
"""

from __future__ import annotations

import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = PROJECT_ROOT / "output" / "audition"

SENTENCE = "A for loop repeats one instruction for every value in a list."
ENGLISH_SENTENCE = "In a loop, every item in the list gets exactly one turn."
INDIC_LANGUAGES = ["mr", "ta", "te", "bn", "kn"]
ENGLISH_VOICES = ["hf_alpha", "hf_beta", "hm_omega", "hm_psi", "af_heart"]


def _write(name: str, audio, sample_rate: int) -> float:
    import soundfile as sf

    path = OUT_DIR / name
    sf.write(path, audio, sample_rate)
    seconds = len(audio) / sample_rate
    print(f"  wrote {name} ({seconds:.1f}s)", flush=True)
    return seconds


def main() -> int:
    import numpy as np

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []

    from backend.services.translation_service import LessonTranslator
    from backend.services.indic_narrator import IndicParlerNarrator
    from backend.services.narration_service import LocalNarrator

    print("== Part A: Indic Parler-TTS language audition ==", flush=True)
    translator = LessonTranslator()
    narrator = IndicParlerNarrator()
    for language in INDIC_LANGUAGES:
        started = time.monotonic()
        try:
            translated = translator.translate_sentences([SENTENCE], language)[0]
            audio, sample_rate = narrator.synthesize(translated, language=language)
            seconds = _write(f"parler-{language}.wav", audio, sample_rate)
            lines.append(
                f"parler-{language}.wav | synth {time.monotonic() - started:.0f}s | "
                f"audio {seconds:.1f}s | {translated}"
            )
        except Exception as exc:  # noqa: BLE001 - audition must continue per language
            lines.append(f"parler-{language}.wav | FAILED: {exc}")
            print(f"  {language} failed: {exc}", flush=True)

    print("== Part B: Kokoro English voice audition ==", flush=True)
    kokoro = LocalNarrator()
    for voice in ENGLISH_VOICES:
        try:
            audio, sample_rate = kokoro.synthesize(
                ENGLISH_SENTENCE, voice=voice, language="en-us", speed=1.0
            )
            _write(f"kokoro-en-{voice}.wav", np.asarray(audio, dtype=np.float32), sample_rate)
            lines.append(f"kokoro-en-{voice}.wav | English accent test")
        except Exception as exc:  # noqa: BLE001
            lines.append(f"kokoro-en-{voice}.wav | FAILED: {exc}")
            print(f"  {voice} failed: {exc}", flush=True)

    summary = OUT_DIR / "SUMMARY.txt"
    summary.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"summary: {summary}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
