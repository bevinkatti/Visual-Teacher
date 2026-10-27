"""Local speech synthesis adapter for Kokoro-ONNX."""

from __future__ import annotations

import os
import time
from pathlib import Path

import numpy as np
from kokoro_onnx import Kokoro


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class LocalNarrator:
    """Load a local Kokoro model and synthesize one utterance at a time."""

    def __init__(self, model_path: Path | None = None, voices_path: Path | None = None):
        initialization_start = time.monotonic()
        self.synthesis_seconds = 0.0
        self.model_path = model_path or Path(
            os.getenv("BLU_KOKORO_MODEL", PROJECT_ROOT / "models/kokoro-onnx/kokoro-v1.0.int8.onnx")
        )
        self.voices_path = voices_path or Path(
            os.getenv("BLU_KOKORO_VOICES", PROJECT_ROOT / "models/kokoro-onnx/voices-v1.0.bin")
        )
        missing = [str(path) for path in (self.model_path, self.voices_path) if not path.is_file()]
        if missing:
            raise FileNotFoundError(
                "Kokoro local assets are missing: " + ", ".join(missing)
            )
        self._engine = Kokoro(str(self.model_path), str(self.voices_path))
        self._voices = set(self._engine.get_voices())
        self.initialization_seconds = time.monotonic() - initialization_start

    @property
    def available_voices(self) -> set[str]:
        return set(self._voices)

    def synthesize(
        self,
        text: str,
        *,
        voice: str = "hf_alpha",
        language: str = "en-us",
        speed: float = 1.0,
    ) -> tuple[np.ndarray, int]:
        if voice not in self._voices:
            raise ValueError(f"Voice {voice!r} is not present in the local Kokoro voice pack.")
        synthesis_start = time.monotonic()
        samples, sample_rate = self._engine.create(
            text.strip(), voice=voice, speed=speed, lang=language
        )
        self.synthesis_seconds += time.monotonic() - synthesis_start
        audio = np.asarray(samples, dtype=np.float32)
        if audio.ndim != 1 or audio.size == 0 or sample_rate <= 0:
            raise RuntimeError("Kokoro returned empty or invalid audio.")
        return audio, int(sample_rate)
