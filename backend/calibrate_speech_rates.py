"""Measure real chars-per-second speaking rates for the budget estimator.

Synthesizes fixed representative sentences with the actual local narrators
(Kokoro for en/hi, Indic Parler-TTS for kn) and reports characters per second.
Run once while offline-capable models are installed:

    .\\.venv\\Scripts\\python.exe -m backend.calibrate_speech_rates

The printed rates feed DEFAULT_SPEAKING_RATES in
backend/services/duration_budget.py or the BLU_SPEAKING_RATES_JSON override.
"""

from __future__ import annotations

import time
from pathlib import Path

import soundfile as sf

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = PROJECT_ROOT / "output" / "measurements"

SAMPLES = {
    ("kokoro", "en"): (
        "A for loop repeats one instruction for every value in a list. "
        "Python takes the first value, runs the body, and moves to the next item."
    ),
    ("kokoro", "hi"): (
        "फ़ॉर लूप सूची की हर वस्तु के लिए एक निर्देश दोहराता है। "
        "पायथन पहली वस्तु लेता है, निर्देश चलाता है, फिर अगली वस्तु पर जाता है।"
    ),
    ("parler", "kn"): (
        "ಫಾರ್ ಲೂಪ್ ಪಟ್ಟಿಯಲ್ಲಿನ ಪ್ರತಿ ಮೌಲ್ಯಕ್ಕೂ ಒಂದು ಸೂಚನೆಯನ್ನು ಪುನರಾವರ್ತಿಸುತ್ತದೆ. "
        "ಪೈಥಾನ್ ಮೊದಲ ಮೌಲ್ಯವನ್ನು ತೆಗೆದುಕೊಂಡು ಅದನ್ನು ಪ್ರಿಂಟ್ ಮಾಡುತ್ತದೆ."
    ),
}


def main() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    measured: dict[str, float] = {}
    for (engine, language), text in SAMPLES.items():
        started = time.monotonic()
        if engine == "kokoro":
            from backend.services.narration_service import LocalNarrator

            narrator: object = LocalNarrator()
            audio, sample_rate = narrator.synthesize(  # type: ignore[attr-defined]
                text, voice="hf_alpha", language=("en-us" if language == "en" else "hi")
            )
        else:
            from backend.services.indic_narrator import IndicParlerNarrator

            narrator = IndicParlerNarrator()
            audio, sample_rate = narrator.synthesize(text, language=language)  # type: ignore[attr-defined]
        synthesis = time.monotonic() - started
        init = float(getattr(narrator, "initialization_seconds", 0.0))
        audio_seconds = len(audio) / sample_rate
        rate = len(text) / audio_seconds
        measured[f"{engine}|{language}"] = round(rate, 2)
        out_path = OUTPUT_DIR / f"calibration-{engine}-{language}.wav"
        sf.write(out_path, audio, sample_rate)
        print(
            f"{engine}/{language}: chars={len(text)} audio={audio_seconds:.2f}s "
            f"rate={rate:.2f} chars/s synthesis={synthesis:.2f}s init={init:.2f}s "
            f"rtf={synthesis / audio_seconds:.2f}x -> {out_path.name}"
        )
    print("BLU_SPEAKING_RATES_JSON=" + str(measured).replace("'", '"'))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
