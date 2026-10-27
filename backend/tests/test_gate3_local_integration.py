"""Opt-in local model -> render -> media route integration check.

Run with ``$env:BLU_RUN_LOCAL_MEDIA_INTEGRATION='1'; pytest ...``. This test
uses the installed local Ollama model and the real narration/FFmpeg pipeline.
"""

import json
import os
import time

import pytest
from fastapi.testclient import TestClient

from backend.main import app, render_jobs
from backend.services.export_service import verify_mp4


pytestmark = pytest.mark.skipif(
    os.getenv("BLU_RUN_LOCAL_MEDIA_INTEGRATION") != "1",
    reason="set BLU_RUN_LOCAL_MEDIA_INTEGRATION=1 to run local Ollama and media export",
)


def test_local_lesson_api_renders_and_serves_real_mp4():
    client = TestClient(app)
    lesson_response = client.post(
        "/api/lessons",
        json={
            "topic": "How do plants move water from roots to leaves?",
            "level": "beginner",
            "language": "en",
            "duration_seconds": 30,
        },
    )
    assert lesson_response.status_code == 200, lesson_response.text
    lesson = lesson_response.json()
    assert lesson["source"] in {"ollama", "sample"}
    assert lesson["fallback"] == (lesson["source"] == "sample")

    start_response = client.post(f"/api/lessons/{lesson['id']}/render")
    assert start_response.status_code == 202, start_response.text
    job = start_response.json()
    deadline = time.monotonic() + 900
    while job["status"] in {"queued", "rendering"} and time.monotonic() < deadline:
        time.sleep(1)
        status_response = client.get(f"/api/renders/{job['job_id']}")
        assert status_response.status_code == 200, status_response.text
        job = status_response.json()

    assert job["status"] == "completed", job
    assert job["video_url"] and job["download_url"] and job["captions_url"] and job["manifest_url"]
    record = render_jobs._jobs[job["job_id"]]
    info = verify_mp4(record.video_path)
    assert info["video_codec"] == "h264"
    assert info["audio_codec"] == "aac"
    assert info["width"] == 1280 and info["height"] == 720
    assert float(info["frame_rate"].split("/")[0]) / float(info["frame_rate"].split("/")[1]) == 24

    manifest = json.loads(record.manifest_path.read_text(encoding="utf-8"))
    assert manifest["timing_basis"].startswith("Measured duration")
    assert len(manifest["scenes"]) == len(lesson["scenes"])
    assert all(scene["audio_seconds"] > 0 for scene in manifest["scenes"])

    video = client.get(job["video_url"])
    download = client.get(job["download_url"])
    captions = client.get(job["captions_url"])
    manifest_response = client.get(job["manifest_url"])
    assert video.status_code == 200 and video.content.startswith(b"\x00\x00\x00")
    assert download.status_code == 200 and "attachment" in download.headers["content-disposition"]
    assert captions.status_code == 200 and captions.content
    assert manifest_response.status_code == 200
    assert manifest_response.json()["lesson_id"] == lesson["id"]
    assert download.content == video.content

    print(
        json.dumps(
            {
                "lesson_source": lesson["source"],
                "fallback": lesson["fallback"],
                "scene_count": len(lesson["scenes"]),
                "output_filename": job["output_filename"],
                "ffprobe": info,
                "captions_bytes": len(captions.content),
                "scene_audio_seconds": [scene["audio_seconds"] for scene in manifest["scenes"]],
                "output_path": str(record.video_path),
            },
            ensure_ascii=False,
        )
    )
