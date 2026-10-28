"""Render the fixed Kannada sample lesson to a verified MP4 (offline gate check).

    .\\.venv\\Scripts\\python.exe -m backend.run_kannada_sample
"""

from __future__ import annotations

import json
import time


def main() -> int:
    from backend.schemas import LessonRequest
    from backend.services.lesson_service import build_sample_lesson
    from backend.services.render_jobs import RenderJobManager

    lesson = build_sample_lesson(
        LessonRequest(
            topic="how does a python loop work",
            level="beginner",
            language="kn",
            duration_seconds=60,
        )
    )
    manager = RenderJobManager()
    manager.register_lesson(lesson)
    started = time.monotonic()
    response = manager.start(lesson.id)
    print(f"job={response.job_id} status={response.status}", flush=True)

    deadline = time.monotonic() + 3600
    while time.monotonic() < deadline:
        job = manager.get_job(response.job_id)
        if job.status in {"completed", "failed"}:
            break
        time.sleep(15)

    job = manager.get_job(response.job_id)
    print(
        json.dumps(
            {
                "status": job.status,
                "duration_seconds": job.duration_seconds,
                "output_filename": job.output_filename,
                "error": job.error,
                "wall_seconds": round(time.monotonic() - started, 1),
            },
            ensure_ascii=False,
        ),
        flush=True,
    )
    return 0 if job.status == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
