"""One-shot environment verification for Stage 4 (translation + Indic TTS)."""

import sys

results = []

try:
    import torch

    results.append(("torch", torch.__version__))
except Exception as exc:  # noqa: BLE001
    results.append(("torch", f"FAIL: {exc}"))

try:
    import transformers

    results.append(("transformers", transformers.__version__))
except Exception as exc:  # noqa: BLE001
    results.append(("transformers", f"FAIL: {exc}"))

try:
    from IndicTransToolkit import IndicProcessor

    results.append(("IndicTransToolkit", f"IndicProcessor ok: {IndicProcessor}"))
except Exception as exc:  # noqa: BLE001
    results.append(("IndicTransToolkit", f"FAIL: {exc}"))

try:
    from parler_tts import ParlerTTSForConditionalGeneration

    results.append(("parler_tts", "import ok"))
except Exception as exc:  # noqa: BLE001
    results.append(("parler_tts", f"FAIL: {type(exc).__name__}: {exc}"))

try:
    from huggingface_hub import snapshot_download

    results.append(("huggingface_hub", "import ok"))
except Exception as exc:  # noqa: BLE001
    results.append(("huggingface_hub", f"FAIL: {exc}"))

for name, status in results:
    print(f"{name:>18}: {status}", flush=True)
sys.exit(0)
