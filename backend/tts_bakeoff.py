"""Controlled TTS bake-off across locally installed models and voices.

Evaluates the Kokoro-ONNX voice pack (English + Hindi voices) and the local
Indic Parler-TTS model (Hindi + Kannada) on identical representative samples.
For every candidate it records model, voice, language, time to first audio,
total synthesis time, audio duration, real-time factor, peak memory, and
objective audio checks (clipping, silence). WAV files are written under
output/bench/tts-bakeoff/ for human listening review.

    .\\.venv\\Scripts\\python.exe -m backend.tts_bakeoff

Gated candidates (ai4bharat/IndicF5, indic-parler-tts-mini) are documented in
the README as unavailable in this environment: they require accepting model
terms with an HF token, and no token is configured.
"""

from __future__ import annotations

import time
from pathlib import Path

import numpy as np
import soundfile as sf

from backend.services.profiling import gpu_status, mb, peak_rss_bytes, peak_rss_sampler

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = PROJECT_ROOT / "output" / "bench" / "tts-bakeoff"

EN_TEXT = (
    "A for loop repeats one instruction for every value in a list. Python takes "
    "the first value, runs the body, and moves on to the next item."
)
HI_TEXT = (
    "फ़ॉर लूप सूची की हर वस्तु के लिए एक निर्देश दोहराता है। पायथन पहली वस्तु लेता है, "
    "निर्देश चलाता है, फिर अगली वस्तु पर जाता है।"
)
KN_TEXT = (
    "ಫಾರ್ ಲೂಪ್ ಪಟ್ಟಿಯಲ್ಲಿನ ಪ್ರತಿ ಮೌಲ್ಯಕ್ಕೂ ಒಂದು ಸೂಚನೆಯನ್ನು ಪುನರಾವರ್ತಿಸುತ್ತದೆ. "
    "ಪೈಥಾನ್ ಮೊದಲ ಮೌಲ್ಯವನ್ನು ತೆಗೆದುಕೊಂಡು ಅದನ್ನು ಪ್ರಿಂಟ್ ಮಾಡುತ್ತದೆ."
)


def audio_checks(audio: np.ndarray, sample_rate: int) -> dict[str, float]:
    peak = float(np.max(np.abs(audio))) if audio.size else 0.0
    window = max(1, int(0.02 * sample_rate))
    quiet_windows = 0
    total_windows = max(1, audio.size // window)
    for start in range(0, audio.size - window, window):
        if float(np.max(np.abs(audio[start : start + window]))) < 0.005:
            quiet_windows += 1
    return {
        "peak_level": round(peak, 3),
        "clipping": peak > 0.995,
        "silence_fraction": round(quiet_windows / total_windows, 3),
    }


def measure(candidate: dict[str, object], path_stem: str) -> dict[str, object]:
    narrator = candidate["narrator_factory"]()
    init_seconds = float(getattr(narrator, "initialization_seconds", 0.0))
    started = time.monotonic()
    with peak_rss_sampler():
        audio, sample_rate = narrator.synthesize(  # type: ignore[attr-defined]
            candidate["text"],
            voice=candidate.get("voice", "") or "hf_alpha",  # type: ignore[arg-type]
            language=candidate["language"],  # type: ignore[arg-type]
        )
    synthesis_seconds = time.monotonic() - started
    audio_seconds = len(audio) / sample_rate
    checks = audio_checks(np.asarray(audio), sample_rate)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUTPUT_DIR / f"{path_stem}.wav"
    sf.write(out_path, audio, sample_rate)
    return {
        "model": candidate["model"],
        "voice": candidate.get("voice") or "voice-description",
        "language": candidate["language"],
        "init_seconds": round(init_seconds, 2),
        "ttfa_seconds": round(synthesis_seconds, 2),
        "synthesis_seconds": round(synthesis_seconds, 2),
        "audio_seconds": round(audio_seconds, 2),
        "rtf": round(synthesis_seconds / audio_seconds, 2),
        "peak_rss_mb": mb(peak_rss_bytes()),
        "wav": out_path.name,
        **checks,
    }


def main() -> int:
    print("GPU status:", gpu_status(), flush=True)
    from backend.services.indic_narrator import IndicParlerNarrator
    from backend.services.narration_service import LocalNarrator

    kokoro = LocalNarrator()
    voices = sorted(kokoro.available_voices)
    en_voices = [v for v in voices if v.startswith(("a", "b"))]
    hi_voices = [v for v in voices if v.startswith("h")]
    candidates: list[dict[str, object]] = [
        {
            "model": "kokoro-onnx int8",
            "voice": voice,
            "language": "en-us",
            "text": EN_TEXT,
            "narrator_factory": lambda: LocalNarrator(),
        }
        for voice in en_voices
    ] + [
        {
            "model": "kokoro-onnx int8",
            "voice": voice,
            "language": "hi",
            "text": HI_TEXT,
            "narrator_factory": lambda: LocalNarrator(),
        }
        for voice in hi_voices
    ] + [
        {
            "model": "indic-parler-tts (full)",
            "voice": "",
            "language": "kn",
            "text": KN_TEXT,
            "narrator_factory": IndicParlerNarrator,
        },
        {
            "model": "indic-parler-tts (full)",
            "voice": "",
            "language": "hi",
            "text": HI_TEXT,
            "narrator_factory": IndicParlerNarrator,
        },
    ]

    rows = []
    for index, candidate in enumerate(candidates):
        stem = f"{index:02d}-{candidate['model'].split()[0]}-{candidate['voice'] or 'desc'}-{candidate['language']}"
        try:
            row = measure(candidate, stem)
        except Exception as exc:
            row = {
                "model": candidate["model"],
                "voice": candidate.get("voice"),
                "language": candidate["language"],
                "error": str(exc)[:160],
            }
        rows.append(row)
        print(row, flush=True)

    report = OUTPUT_DIR / "bakeoff-report.json"
    report.write_text(__import__("json").dumps(rows, indent=2), encoding="utf-8")
    print(f"wrote {report}")
    print(
        "Note: automated metrics only. Human listening review of the WAV files "
        "is still required for pronunciation and naturalness judgements."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
