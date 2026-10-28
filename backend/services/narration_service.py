"""Local speech synthesis adapter for Kokoro-ONNX."""

from __future__ import annotations

import hashlib
import logging
import os
import time
from pathlib import Path

import numpy as np
from kokoro_onnx import Kokoro


logger = logging.getLogger(__name__)
PROJECT_ROOT = Path(__file__).resolve().parents[2]


class LocalNarrator:
    """Load a local Kokoro model and synthesize one utterance at a time.

    Synthesized utterances are cached on disk keyed by the model identity,
    voice, language, speed, and text hash, so repeat renders (and the fixed
    sample lesson) never resynthesize unchanged narration.
    """

    engine_name = "kokoro"

    def __init__(
        self,
        model_path: Path | None = None,
        voices_path: Path | None = None,
        cache_dir: Path | None = None,
    ):
        initialization_start = time.monotonic()
        self.synthesis_seconds = 0.0
        self.model_path = model_path or Path(
            os.getenv("BLU_KOKORO_MODEL", PROJECT_ROOT / "models/kokoro-onnx/kokoro-v1.0.int8.onnx")
        )
        self.voices_path = voices_path or Path(
            os.getenv("BLU_KOKORO_VOICES", PROJECT_ROOT / "models/kokoro-onnx/voices-v1.0.bin")
        )
        self.cache_dir = Path(
            cache_dir or os.getenv("BLU_KOKORO_CACHE", PROJECT_ROOT / "models/tts-cache/kokoro")
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

    def _cache_path(self, voice: str, language: str, speed: float, cleaned: str) -> Path:
        model_identity = f"{self.model_path.name}|{self.model_path.stat().st_mtime_ns}"
        digest = hashlib.sha256(
            f"v1|{model_identity}|{voice}|{language}|{speed}|{cleaned}".encode("utf-8")
        ).hexdigest()
        return self.cache_dir / f"{language}-{digest}.wav"

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
        cleaned = " ".join(str(text).split())
        cache_path = self._cache_path(voice, language, speed, cleaned)
        if cache_path.is_file():
            import soundfile as sf

            samples, sample_rate = sf.read(cache_path, dtype="float32")
            audio = np.asarray(samples, dtype=np.float32)
            if audio.ndim == 1 and audio.size > 0 and sample_rate > 0:
                logger.info("Kokoro cache hit path=%s", cache_path.name)
                return audio, int(sample_rate)

        synthesis_start = time.monotonic()
        samples, sample_rate = self._engine.create(
            text.strip(), voice=voice, speed=speed, lang=language
        )
        self.synthesis_seconds += time.monotonic() - synthesis_start
        audio = np.asarray(samples, dtype=np.float32)
        if audio.ndim != 1 or audio.size == 0 or sample_rate <= 0:
            raise RuntimeError("Kokoro returned empty or invalid audio.")
        try:
            import soundfile as sf

            self.cache_dir.mkdir(parents=True, exist_ok=True)
            sf.write(cache_path, audio, int(sample_rate), subtype="PCM_16")
        except OSError as exc:
            logger.warning("Could not cache Kokoro narration %s: %s", cache_path, exc)
        return audio, int(sample_rate)

