"""Lightweight profiling helpers: peak RSS and honest GPU status reporting.

No new dependencies: peak memory uses the Windows process memory API through
ctypes (resource.getrusage elsewhere). GPU status is reported only when the
runtime actually exposes an accelerator -- a GPU being installed is not
reported as acceleration.
"""

from __future__ import annotations

import ctypes
import logging
import platform
import threading
import time
from contextlib import contextmanager

logger = logging.getLogger(__name__)
_SAMPLE_INTERVAL_SECONDS = 0.2


def peak_rss_bytes() -> int:
    """Peak resident set size of this process (Windows + POSIX)."""
    if platform.system() == "Windows":
        class _PROCESS_MEMORY_COUNTERS(ctypes.Structure):
            _fields_ = [
                ("cb", ctypes.c_ulong),
                ("PageFaultCount", ctypes.c_ulong),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        counters = _PROCESS_MEMORY_COUNTERS()
        counters.cb = ctypes.sizeof(_PROCESS_MEMORY_COUNTERS)
        psapi = ctypes.windll.psapi  # type: ignore[attr-defined]
        psapi.GetProcessMemoryInfo.argtypes = (
            ctypes.c_void_p,
            ctypes.POINTER(_PROCESS_MEMORY_COUNTERS),
            ctypes.c_ulong,
        )
        psapi.GetProcessMemoryInfo.restype = ctypes.c_int
        handle = ctypes.windll.kernel32.GetCurrentProcess()  # type: ignore[attr-defined]
        if not psapi.GetProcessMemoryInfo(
            ctypes.c_void_p(handle), ctypes.byref(counters), counters.cb
        ):
            return 0
        return int(counters.PeakWorkingSetSize)
    try:
        import resource

        return int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss) * 1024
    except Exception:  # pragma: no cover - non-Windows fallback only
        return 0


def gpu_status() -> dict[str, object]:
    """Report accelerators that are actually usable, or say CPU-only plainly."""
    status: dict[str, object] = {
        "torch_cuda_available": False,
        "onnxruntime_providers": [],
        "acceleration": "cpu-only",
    }
    try:
        import torch

        status["torch_version"] = torch.__version__
        status["torch_cuda_available"] = bool(torch.cuda.is_available())
        if torch.cuda.is_available():
            status["gpu_name"] = torch.cuda.get_device_name(0)
            status["acceleration"] = "cuda"
    except Exception as exc:  # pragma: no cover - torch missing or broken
        status["torch_error"] = str(exc)
    try:
        import onnxruntime

        providers = onnxruntime.get_available_providers()
        status["onnxruntime_providers"] = providers
        if any("CUDA" in provider or "DirectML" in provider for provider in providers):
            status["acceleration"] = "gpu-capable-onnxruntime"
    except Exception as exc:  # pragma: no cover
        status["onnxruntime_error"] = str(exc)
    return status


@contextmanager
def peak_rss_sampler(interval: float = _SAMPLE_INTERVAL_SECONDS):
    """Sample RSS in a background thread; yields a dict updated live."""
    peak = {"bytes": peak_rss_bytes()}
    stop = threading.Event()

    def _sample() -> None:
        while not stop.is_set():
            current = peak_rss_bytes()
            if current > peak["bytes"]:
                peak["bytes"] = current
            stop.wait(interval)

    thread = threading.Thread(target=_sample, daemon=True, name="blu-rss-sampler")
    thread.start()
    try:
        yield peak
    finally:
        stop.set()
        thread.join(timeout=1.0)


def mb(num_bytes: int | float) -> float:
    return round(float(num_bytes) / (1024 * 1024), 1)


def log_stage(job_id: str, stage: str, seconds: float, peak_bytes: int | None = None) -> None:
    extra = f" peak_rss_mb={mb(peak_bytes)}" if peak_bytes is not None else ""
    logger.info("render job %s stage=%s seconds=%.3f%s", job_id, stage, seconds, extra)


def monotonic() -> float:
    return time.monotonic()
