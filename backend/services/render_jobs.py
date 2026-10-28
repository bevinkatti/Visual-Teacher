"""Bounded, in-memory render jobs and controlled local media paths."""

from __future__ import annotations

import logging
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import Callable, Literal, Protocol
from uuid import uuid4

from backend.schemas import Lesson, RenderJobResponse
from backend.services.duration_budget import DurationBudgetError
from backend.services.export_service import export_lesson
from backend.services.narration_service import LocalNarrator


logger = logging.getLogger(__name__)
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MEDIA_DIR = PROJECT_ROOT / "output" / "videos" / "lessons"
_LESSON_ID_PATTERN = re.compile(r"^[a-f0-9]{12}$")
_JOB_ID_PATTERN = re.compile(r"^[a-f0-9]{32}$")


class Executor(Protocol):
    def submit(self, fn, /, *args, **kwargs): ...


class RenderJobNotFound(KeyError):
    pass


class RenderNotReady(RuntimeError):
    pass


class RenderQueueFull(RuntimeError):
    pass


class RenderLanguageUnsupported(ValueError):
    pass


_SCRIPT_RANGES = {
    "hi": ("\u0900", "\u097f"),
    "kn": ("\u0c80", "\u0cff"),
}
_SCRIPT_NAMES = {"hi": "Hindi", "kn": "Kannada"}


def _has_requested_script(lesson: Lesson) -> bool:
    text = " ".join(
        part
        for scene in lesson.scenes
        for part in (scene.title, scene.narration, scene.caption)
    )
    letters = [char for char in text if char.isalpha()]
    if not letters or lesson.language not in _SCRIPT_RANGES:
        return False
    low, high = _SCRIPT_RANGES[lesson.language]
    in_script = sum(low <= char <= high for char in letters)
    return in_script / len(letters) >= 0.2


@dataclass
class _RenderJob:
    job_id: str
    lesson_id: str
    output_filename: str
    video_path: Path
    captions_path: Path
    manifest_path: Path
    status: Literal["queued", "rendering", "completed", "failed"] = "queued"
    duration_seconds: float | None = None
    target_duration_seconds: int | None = None
    duration_within_tolerance: bool | None = None
    upstream_stage_seconds: dict[str, float] | None = None
    grow_pool: dict[int, list[str]] | None = None
    error: str | None = None


class RenderJobManager:
    """Run at most one renderer worker; callers never supply filesystem paths."""

    def __init__(
        self,
        *,
        media_dir: Path = DEFAULT_MEDIA_DIR,
        exporter: Callable = export_lesson,
        narrator_factory: Callable = LocalNarrator,
        indic_narrator_factory: Callable | None = None,
        executor: Executor | None = None,
        max_lessons: int = 100,
        max_active_jobs: int = 3,
    ):
        self.media_dir = media_dir.resolve()
        self._exporter = exporter
        self._narrator_factory = narrator_factory
        self._indic_narrator_factory = indic_narrator_factory
        self._executor = executor or ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="blu-render"
        )
        self._max_lessons = max_lessons
        self._max_active_jobs = max_active_jobs
        self._lock = RLock()
        self._lessons: dict[str, Lesson] = {}
        self._jobs: dict[str, _RenderJob] = {}
        self._upstream_seconds: dict[str, dict[str, float]] = {}
        self._grow_pools: dict[str, dict[int, list[str]]] = {}
        # Narration models are expensive to load (the Kannada Parler model is
        # multi-gigabyte); keep one instance per role alive across render jobs.
        self._narrator_cache: dict[str, object] = {}

    def register_lesson(
        self,
        lesson: Lesson,
        *,
        upstream_stage_seconds: dict[str, float] | None = None,
        grow_pool: dict[int, list[str]] | None = None,
    ) -> None:
        if not _LESSON_ID_PATTERN.fullmatch(lesson.id):
            raise ValueError("Lesson ID is not a server-generated safe identifier.")
        with self._lock:
            self._lessons[lesson.id] = lesson.model_copy(deep=True)
            if upstream_stage_seconds:
                self._upstream_seconds[lesson.id] = dict(upstream_stage_seconds)
            if grow_pool:
                self._grow_pools[lesson.id] = {
                    index: list(sentences) for index, sentences in grow_pool.items()
                }
            while len(self._lessons) > self._max_lessons:
                oldest_id = next(iter(self._lessons))
                self._lessons.pop(oldest_id, None)

    def start(self, lesson_id: str) -> RenderJobResponse:
        if not _LESSON_ID_PATTERN.fullmatch(lesson_id):
            raise RenderJobNotFound("Lesson was not found.")
        with self._lock:
            lesson = self._lessons.get(lesson_id)
            if lesson is None:
                raise RenderJobNotFound("Lesson was not found.")

            if lesson.language in _SCRIPT_RANGES and not _has_requested_script(lesson):
                raise RenderLanguageUnsupported(
                    f"This lesson is not written in {_SCRIPT_NAMES[lesson.language]} script, "
                    "so it cannot be rendered as that language's narration."
                )

            for existing in reversed(tuple(self._jobs.values())):
                if existing.lesson_id == lesson_id:
                    self._refresh_missing_media(existing)
                    if existing.status in {"queued", "rendering", "completed"}:
                        return self._to_response(existing)

            active_jobs = sum(
                job.status in {"queued", "rendering"} for job in self._jobs.values()
            )
            if active_jobs >= self._max_active_jobs:
                raise RenderQueueFull("The local render queue is full. Retry after a job finishes.")

            job_id = uuid4().hex
            output_filename = f"lesson-{lesson_id}-{job_id}.mp4"
            video_path = (self.media_dir / output_filename).resolve()
            captions_path = video_path.with_suffix(".srt")
            manifest_path = video_path.with_suffix(".json")
            if video_path.parent != self.media_dir:
                raise RuntimeError("Generated media path escaped the configured media directory.")
            if any(path.exists() for path in (video_path, captions_path, manifest_path)):
                raise FileExistsError("Generated render path already exists; refusing to overwrite it.")

            job = _RenderJob(
                job_id=job_id,
                lesson_id=lesson_id,
                output_filename=output_filename,
                video_path=video_path,
                captions_path=captions_path,
                manifest_path=manifest_path,
                target_duration_seconds=int(lesson.target_duration_seconds),
                upstream_stage_seconds=self._upstream_seconds.get(lesson_id),
                grow_pool=self._grow_pools.get(lesson_id),
            )
            self._jobs[job_id] = job
            try:
                self._executor.submit(self._run_job, job_id, lesson)
            except Exception:
                logger.exception("Could not queue lesson render job %s", job_id)
                job.status = "failed"
                job.error = "The render could not be queued. Please retry."
            return self._to_response(job)

    def get_job(self, job_id: str) -> RenderJobResponse:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or not _JOB_ID_PATTERN.fullmatch(job_id):
                raise RenderJobNotFound("Render job was not found.")
            self._refresh_missing_media(job)
            return self._to_response(job)

    def get_media_file(
        self, job_id: str, kind: Literal["video", "download", "captions", "manifest"]
    ) -> Path:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or not _JOB_ID_PATTERN.fullmatch(job_id):
                raise RenderJobNotFound("Render job was not found.")
            self._refresh_missing_media(job)
            if job.status != "completed":
                raise RenderNotReady("Render media is not available yet.")
            path = {
                "captions": job.captions_path,
                "manifest": job.manifest_path,
            }.get(kind, job.video_path)
            if not path.is_file() or path.resolve().parent != self.media_dir:
                job.status = "failed"
                job.error = "The generated media file is unavailable. Please render again."
                job.duration_seconds = None
                raise RenderNotReady(job.error)
            return path

    def _resolve_indic_narrator(self):
        """Kannada narration uses the local Indic Parler-TTS voice."""
        if self._indic_narrator_factory is not None:
            return self._indic_narrator_factory()
        from backend.services.indic_narrator import IndicParlerNarrator

        return IndicParlerNarrator()

    def _cached_narrator(self, role: str, factory: Callable):
        """Reuse one narrator instance per role; model loads dominate repeat jobs."""
        with self._lock:
            cached = self._narrator_cache.get(role)
        if cached is not None:
            return cached
        instance = factory()
        with self._lock:
            self._narrator_cache[role] = instance
        return instance

    @staticmethod
    def _indic_voice_description() -> str:
        from backend.services.indic_narrator import VOICE_DESCRIPTIONS

        return VOICE_DESCRIPTIONS["kn"]

    def _run_job(self, job_id: str, lesson: Lesson) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return
            job.status = "rendering"

        try:
            if lesson.language == "kn":
                narrator = self._cached_narrator("indic", self._resolve_indic_narrator)
                voice, speech_language = self._indic_voice_description(), "kn"
            else:
                narrator = self._cached_narrator("kokoro", self._narrator_factory)
                voice, speech_language = (
                    ("hf_alpha", "hi") if lesson.language == "hi" else ("hf_alpha", "en-us")
                )
            result = self._exporter(
                lesson,
                narrator,
                job.video_path,
                voice=voice,
                language=speech_language,
                upstream_stage_seconds=job.upstream_stage_seconds,
                narration_grow_pool=job.grow_pool,
            )
            video_path = Path(result.video_path).resolve()
            captions_path = Path(result.captions_path).resolve()
            manifest_path = Path(result.manifest_path).resolve()
            if (
                video_path != job.video_path
                or captions_path != job.captions_path
                or manifest_path != job.manifest_path
            ):
                raise RuntimeError("Renderer returned a path outside the assigned job outputs.")
            if not video_path.is_file() or not captions_path.is_file() or not manifest_path.is_file():
                raise RuntimeError("Renderer completed without all expected media files.")
            with self._lock:
                job.status = "completed"
                job.duration_seconds = float(result.duration_seconds)
                job.duration_within_tolerance = bool(getattr(result, "within_tolerance", True))
        except DurationBudgetError as exc:
            logger.warning("Lesson render job %s missed its duration target: %s", job_id, exc)
            with self._lock:
                job.status = "failed"
                job.duration_seconds = None
                job.error = str(exc)
        except Exception:
            logger.exception("Lesson render job %s failed", job_id)
            with self._lock:
                job.status = "failed"
                job.duration_seconds = None
                job.error = "Local narration or MP4 export failed. Check backend logs and retry."

    def _refresh_missing_media(self, job: _RenderJob) -> None:
        if job.status == "completed" and (
            not job.video_path.is_file()
            or not job.captions_path.is_file()
            or not job.manifest_path.is_file()
        ):
            job.status = "failed"
            job.duration_seconds = None
            job.error = "The generated media file is unavailable. Please render again."

    @staticmethod
    def _to_response(job: _RenderJob) -> RenderJobResponse:
        completed = job.status == "completed"
        return RenderJobResponse(
            job_id=job.job_id,
            lesson_id=job.lesson_id,
            status=job.status,
            output_filename=job.output_filename,
            duration_seconds=job.duration_seconds,
            target_duration_seconds=job.target_duration_seconds,
            duration_within_tolerance=job.duration_within_tolerance,

            video_url=f"/api/media/{job.job_id}/video" if completed else None,
            download_url=f"/api/media/{job.job_id}/download" if completed else None,
            captions_url=f"/api/media/{job.job_id}/captions" if completed else None,
            manifest_url=f"/api/media/{job.job_id}/manifest" if completed else None,
            error=job.error,
        )
