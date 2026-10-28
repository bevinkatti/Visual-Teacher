import logging
import os
import time
from threading import Lock

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from backend.schemas import Lesson, LessonRequest, RenderJobResponse
from backend.services.lesson_service import build_sample_lesson_with_pool
from backend.services.ollama_planner import OllamaPlanner, OllamaPlannerError
from backend.services.translation_service import TranslationUnavailable
from backend.services.render_jobs import (
    RenderJobManager,
    RenderJobNotFound,
    RenderLanguageUnsupported,
    RenderNotReady,
    RenderQueueFull,
)


logger = logging.getLogger(__name__)
render_jobs = RenderJobManager()

app = FastAPI(
    title="Blu Visual Teacher",
    version="0.1.0",
    description="Local-first visual lesson generation API.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "lesson_engine": "ollama_with_sample_fallback",
        "llm": "local_configured",
        "model": os.getenv("BLU_OLLAMA_MODEL", "qwen2.5:3b"),
        "fallback_available": True,
    }


_translator = None
_translator_lock = Lock()


def _build_translator():
    """One shared translator instance; loading IndicTrans2 costs about 9 seconds."""
    global _translator
    with _translator_lock:
        if _translator is None:
            from backend.services.translation_service import LessonTranslator

            _translator = LessonTranslator()
        return _translator


@app.post("/api/lessons", response_model=Lesson)
def create_lesson(request: LessonRequest):
    planning_start = time.monotonic()
    try:
        lesson = OllamaPlanner().plan(request)
        upstream_stage_seconds = {"planning": time.monotonic() - planning_start}
    except OllamaPlannerError as exc:
        logger.warning(
            "Ollama lesson planning failed (%s): %s; returning the deterministic sample fallback.",
            exc.reason,
            exc,
        )
        lesson, grow_pool = build_sample_lesson_with_pool(request, fallback_reason=exc.reason)
        render_jobs.register_lesson(
            lesson,
            upstream_stage_seconds={"planning": time.monotonic() - planning_start},
            grow_pool=grow_pool,
        )
        return lesson
    if request.language != "en":
        translation_start = time.monotonic()
        try:
            lesson = _build_translator().translate_lesson(lesson, request.language)
            upstream_stage_seconds["translation"] = time.monotonic() - translation_start
        except TranslationUnavailable as exc:
            logger.warning(
                "Local translation into %s failed (%s); returning the deterministic sample fallback.",
                request.language,
                exc,
            )
            lesson, grow_pool = build_sample_lesson_with_pool(
                request, fallback_reason="translation_unavailable"
            )
            render_jobs.register_lesson(
                lesson,
                upstream_stage_seconds=upstream_stage_seconds,
                grow_pool=grow_pool,
            )
            return lesson
    render_jobs.register_lesson(lesson, upstream_stage_seconds=upstream_stage_seconds)
    return lesson


@app.post(
    "/api/lessons/{lesson_id}/render",
    response_model=RenderJobResponse,
    status_code=202,
)
def start_lesson_render(lesson_id: str):
    try:
        return render_jobs.start(lesson_id)
    except RenderJobNotFound as exc:
        raise HTTPException(status_code=404, detail="Lesson was not found.") from exc
    except RenderLanguageUnsupported as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RenderQueueFull as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/api/renders/{job_id}", response_model=RenderJobResponse)
def get_render_status(job_id: str):
    try:
        return render_jobs.get_job(job_id)
    except RenderJobNotFound as exc:
        raise HTTPException(status_code=404, detail="Render job was not found.") from exc


def _get_media(job_id: str, kind: str):
    try:
        return render_jobs.get_media_file(job_id, kind)
    except RenderJobNotFound as exc:
        raise HTTPException(status_code=404, detail="Render job was not found.") from exc
    except RenderNotReady as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.get("/api/media/{job_id}/video")
def play_rendered_video(job_id: str):
    path = _get_media(job_id, "video")
    return FileResponse(path, media_type="video/mp4")


@app.get("/api/media/{job_id}/download")
def download_rendered_video(job_id: str):
    path = _get_media(job_id, "download")
    return FileResponse(path, media_type="video/mp4", filename=path.name)


@app.get("/api/media/{job_id}/captions")
def download_rendered_captions(job_id: str):
    path = _get_media(job_id, "captions")
    return FileResponse(
        path,
        media_type="application/x-subrip",
        filename=path.name,
    )


@app.get("/api/media/{job_id}/manifest")
def get_rendered_manifest(job_id: str):
    path = _get_media(job_id, "manifest")
    return FileResponse(path, media_type="application/json")
