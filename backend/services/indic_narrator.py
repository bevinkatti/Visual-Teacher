"""Local Indic Parler-TTS narration adapter (Apache-2.0 weights) for Indic languages.

Kokoro-ONNX covers English and Hindi; this adapter adds languages such as
Kannada with the AI4Bharat Indic Parler-TTS mini model running on CPU. Audio
is cached on disk keyed by language, voice description, and text so repeat
renders (and the fixed sample lesson) synthesize only once.
"""

from __future__ import annotations

import hashlib
import logging
import os
import time
from pathlib import Path

import numpy as np


logger = logging.getLogger(__name__)
PROJECT_ROOT = Path(__file__).resolve().parents[2]

DEFAULT_MODEL_DIR = PROJECT_ROOT / "models" / "indic-parler-tts"
DEFAULT_CACHE_DIR = PROJECT_ROOT / "models" / "tts-cache" / "indic-parler"

# Voice descriptions follow the model card guidance: a spoken description of
# the speaker doubles as the voice selector for this adapter.
VOICE_DESCRIPTIONS = {
    "kn": (
        "Kannada female teacher with a clear voice and even pacing. "
        "The recording is of very high quality with the speaker speaking clearly."
    ),
    "hi": (
        "Hindi female teacher with a clear voice and even pacing. "
        "The recording is of very high quality with the speaker speaking clearly."
    ),
    "mr": (
        "Marathi female teacher with a clear voice and moderate pace. "
        "The recording is of very high quality with the speaker speaking clearly."
    ),
    "ta": (
        "Tamil female teacher with a clear voice and moderate pace. "
        "The recording is of very high quality with the speaker speaking clearly."
    ),
    "te": (
        "Telugu female teacher with a clear voice and moderate pace. "
        "The recording is of very high quality with the speaker speaking clearly."
    ),
    "bn": (
        "Bengali female teacher with a clear voice and moderate pace. "
        "The recording is of very high quality with the speaker speaking clearly."
    ),
}

_SENTENCE_BOUNDARIES = (".", "!", "?", "।")
MAX_CHUNK_CHARACTERS = 240
CHUNK_GAP_SECONDS = 0.15


class IndicNarratorUnavailable(RuntimeError):
    """The local Indic Parler-TTS model is missing or unusable."""


def _split_chunks(text: str) -> list[str]:
    """Split narration into bounded sentence chunks for stable CPU synthesis."""
    sentences: list[str] = []
    current = ""
    for character in text:
        current = f"{current}{character}"
        if character in _SENTENCE_BOUNDARIES:
            sentences.append(current.strip())
            current = ""
    if current.strip():
        sentences.append(current.strip())

    chunks: list[str] = []
    for sentence in sentences:
        if len(sentence) <= MAX_CHUNK_CHARACTERS:
            chunks.append(sentence)
            continue
        words = sentence.split(" ")
        chunk = ""
        for word in words:
            candidate = f"{chunk} {word}".strip()
            if len(candidate) > MAX_CHUNK_CHARACTERS and chunk:
                chunks.append(chunk)
                chunk = word
            else:
                chunk = candidate
        if chunk:
            chunks.append(chunk)
    return [chunk for chunk in chunks if chunk]


class IndicParlerNarrator:
    """Synthesize Indic-language narration with the local Parler-TTS model."""

    engine_name = "parler"

    def __init__(
        self,
        model_dir: Path | None = None,
        cache_dir: Path | None = None,
    ):
        self.model_dir = model_dir or Path(os.getenv("BLU_PARLER_DIR", str(DEFAULT_MODEL_DIR)))
        self.cache_dir = Path(os.getenv("BLU_PARLER_CACHE", str(DEFAULT_CACHE_DIR)))
        self._model = None
        self._tokenizer = None
        self._description_tokenizer = None
        self.synthesis_seconds = 0.0
        self.initialization_seconds = 0.0

    @property
    def available(self) -> bool:
        return self.model_dir.is_dir()

    def _ensure_loaded(self) -> None:
        if self._model is not None:
            return
        if not self.available:
            raise IndicNarratorUnavailable(
                f"Indic Parler-TTS model directory is missing: {self.model_dir}"
            )
        load_start = time.monotonic()
        try:
            import torch
            from parler_tts import ParlerTTSForConditionalGeneration
            from transformers import AutoTokenizer
        except ImportError as exc:
            raise IndicNarratorUnavailable(
                f"Local narration dependencies are missing: {exc}"
            ) from exc

        try:
            self._model = ParlerTTSForConditionalGeneration.from_pretrained(
                str(self.model_dir), torch_dtype=torch.float32
            )
            self._model.eval()
            self._tokenizer = AutoTokenizer.from_pretrained(str(self.model_dir))
            # The voice description is encoded with the T5 text-encoder
            # tokenizer, not the repo-root prompt tokenizer (official usage).
            description_dir = os.getenv(
                "BLU_PARLER_DESCRIPTION_TOKENIZER",
                str(PROJECT_ROOT / "models" / "flan-t5-large-tokenizer"),
            )
            if Path(description_dir).is_dir():
                self._description_tokenizer = AutoTokenizer.from_pretrained(description_dir)
            else:
                self._description_tokenizer = AutoTokenizer.from_pretrained(
                    str(self._model.config.text_encoder._name_or_path)
                )
        except Exception as exc:
            self._model = None
            raise IndicNarratorUnavailable(
                f"Indic Parler-TTS could not be loaded: {exc}"
            ) from exc
        self.initialization_seconds = time.monotonic() - load_start
        logger.info(
            "Indic Parler-TTS initialization_seconds=%.3f sampling_rate=%s",
            self.initialization_seconds,
            self._model.config.sampling_rate,
        )

    def _cache_path(self, language: str, voice: str, text: str) -> Path:
        digest = hashlib.sha256(
            f"v1|{language}|{voice}|{text}".encode("utf-8")
        ).hexdigest()
        return self.cache_dir / f"{language}-{digest}.wav"

    def _synthesized_chunk(self, text: str, voice: str) -> tuple[np.ndarray, int]:
        import torch

        description = self._description_tokenizer(voice, return_tensors="pt")
        prompt = self._tokenizer(text, return_tensors="pt")
        # The model's generation_config requires sampled decoding; greedy
        # decoding collapses to silence until max_length. A text-derived seed
        # keeps each chunk reproducible without overriding that config.
        seed = int(hashlib.sha256(f"{voice}|{text}".encode("utf-8")).hexdigest()[:8], 16)
        torch.manual_seed(seed)
        with torch.no_grad():
            generation = self._model.generate(
                input_ids=description.input_ids,
                attention_mask=description.attention_mask,
                prompt_input_ids=prompt.input_ids,
                prompt_attention_mask=prompt.attention_mask,
            )
        samples = generation.cpu().numpy().squeeze().astype(np.float32)
        if samples.ndim != 1 or samples.size == 0:
            raise IndicNarratorUnavailable("Parler-TTS returned empty audio.")
        peak = float(np.max(np.abs(samples)))
        if peak < 0.005:
            raise IndicNarratorUnavailable("Parler-TTS returned silent audio.")
        return samples, int(self._model.config.sampling_rate)

    def synthesize(
        self,
        text: str,
        *,
        voice: str = "",
        language: str = "kn",
        speed: float = 1.0,
    ) -> tuple[np.ndarray, int]:
        """Return float32 PCM and the sample rate for the narration text.

        ``voice`` may be empty to use the built-in description for the
        language. ``speed`` is accepted for interface parity with the Kokoro
        narrator; Parler-TTS pacing is controlled by the voice description.
        """
        cleaned = " ".join(str(text).split())
        if not cleaned:
            raise ValueError("Narration text is empty.")
        description = voice or VOICE_DESCRIPTIONS.get(language)
        if not description:
            raise IndicNarratorUnavailable(
                f"No local Parler-TTS voice for language {language!r}."
            )

        import soundfile as sf

        cache_path = self._cache_path(language, description, cleaned)
        if cache_path.is_file():
            samples, sample_rate = sf.read(cache_path, dtype="float32")
            logger.info("Parler-TTS cache hit path=%s", cache_path.name)
            return np.asarray(samples, dtype=np.float32), int(sample_rate)

        self._ensure_loaded()
        chunks = _split_chunks(cleaned)
        pieces: list[np.ndarray] = []
        sample_rate = 0
        synthesis_start = time.monotonic()
        for chunk in chunks:
            samples, rate = self._synthesized_chunk(chunk, description)
            sample_rate = rate
            pieces.append(samples)
            pieces.append(np.zeros(int(round(CHUNK_GAP_SECONDS * rate)), dtype=np.float32))
        self.synthesis_seconds += time.monotonic() - synthesis_start
        audio = np.concatenate(pieces).astype(np.float32)

        self.cache_dir.mkdir(parents=True, exist_ok=True)
        sf.write(cache_path, audio, sample_rate)
        logger.info(
            "Parler-TTS synthesis chunks=%d audio_seconds=%.3f synthesis_seconds=%.3f",
            len(chunks),
            len(audio) / sample_rate,
            self.synthesis_seconds,
        )
        return audio, sample_rate
