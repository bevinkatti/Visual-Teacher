"""Download the local IndicTrans2 and Indic Parler-TTS models into models/.

Run once while online; the pipeline then runs fully offline:

    .\\.venv\\Scripts\\python.exe -m backend.download_local_models

Indic Parler-TTS mini is Apache-2.0; IndicTrans2 dist-200M is MIT. Both are
redistribution-friendly for this repository's hackathon use.
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

# The official Apache-2.0 voice model (938M params, ~3.6 GB fp32). There is no
# official "mini" variant on the Hub; `indic-parler-tts-pretrained` is the same
# architecture and is kept as the automatic fallback.
TARGETS = [
    ("ai4bharat/indictrans2-en-indic-dist-200M", PROJECT_ROOT / "models" / "indictrans2-en-indic-dist-200M"),
    ("ai4bharat/indic-parler-tts", PROJECT_ROOT / "models" / "indic-parler-tts"),
]
FALLBACK_TTS = ("ai4bharat/indic-parler-tts-pretrained", PROJECT_ROOT / "models" / "indic-parler-tts")
# Voice descriptions are encoded with the T5 text-encoder tokenizer; only the
# small tokenizer files are needed, not the flan-t5-large weights.
DESCRIPTION_TOKENIZER = (
    "google/flan-t5-large",
    PROJECT_ROOT / "models" / "flan-t5-large-tokenizer",
    ["tokenizer_config.json", "tokenizer.json", "special_tokens_map.json", "spiece.model"],
)


def _download(snapshot_download, repo_id: str, local_dir: Path) -> None:
    print(f"Downloading {repo_id} into {local_dir} ...")
    snapshot_download(repo_id=repo_id, local_dir=str(local_dir))
    print(f"Finished {repo_id}.")


def main() -> int:
    try:
        from huggingface_hub import snapshot_download
    except ImportError:
        print("huggingface_hub is missing; install backend/requirements.txt first.")
        return 1

    try:
        _download(snapshot_download, *TARGETS[0])
    except Exception as exc:  # noqa: BLE001 - report and stop; translation is required
        print(f"IndicTrans2 download failed: {exc}")
        return 1

    try:
        _download(snapshot_download, *TARGETS[1])
    except Exception as exc:  # noqa: BLE001 - fall back to the other Apache-2.0 voice model
        print(f"Voice model download failed ({exc}); trying the pretrained fallback.")
        try:
            _download(snapshot_download, *FALLBACK_TTS)
        except Exception as fallback_exc:  # noqa: BLE001
            print(f"Indic Parler-TTS download failed: {fallback_exc}")
            return 1

    repo_id, local_dir, patterns = DESCRIPTION_TOKENIZER
    print(f"Downloading {repo_id} tokenizer into {local_dir} ...")
    snapshot_download(repo_id=repo_id, local_dir=str(local_dir), allow_patterns=patterns)
    print(f"Finished {repo_id} tokenizer.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
