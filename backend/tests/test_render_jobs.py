import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.schemas import LessonRequest
from backend.services.lesson_service import build_sample_lesson
from backend.services.render_jobs import (
    RenderJobManager,
    RenderJobNotFound,
    RenderLanguageUnsupported,
    RenderQueueFull,
)


class ManualExecutor:
    def __init__(self):
        self.tasks = []

    def submit(self, fn, /, *args, **kwargs):
        self.tasks.append((fn, args, kwargs))

    def run_next(self):
        fn, args, kwargs = self.tasks.pop(0)
        fn(*args, **kwargs)


def sample_lesson(topic="A local render job"):
    return build_sample_lesson(LessonRequest(topic=topic, duration_seconds=30))


def fake_exporter(lesson, _narrator, output_path: Path, **_kwargs):
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(b"actual-test-mp4-bytes")
    captions_path = output_path.with_suffix(".srt")
    captions_path.write_text(
        "1\n00:00:00,000 --> 00:00:01,000\nनमस्ते → ಕನ್ನಡ\n",
        encoding="utf-8",
    )
    manifest_path = output_path.with_suffix(".json")
    manifest_path.write_text(json.dumps({"lesson_id": lesson.id}), encoding="utf-8")
    return SimpleNamespace(
        video_path=output_path,
        captions_path=captions_path,
        manifest_path=manifest_path,
        duration_seconds=3.25,
    )


def test_render_job_is_queued_then_serves_only_real_completed_files(tmp_path, monkeypatch):
    executor = ManualExecutor()
    manager = RenderJobManager(
        media_dir=tmp_path / "safe-media",
        exporter=fake_exporter,
        narrator_factory=object,
        executor=executor,
    )
    lesson = sample_lesson()
    manager.register_lesson(lesson)
    monkeypatch.setattr("backend.main.render_jobs", manager)
    client = TestClient(app)

    started = client.post(f"/api/lessons/{lesson.id}/render")
    assert started.status_code == 202
    queued = started.json()
    assert queued["status"] == "queued"
    assert queued["output_filename"].startswith(f"lesson-{lesson.id}-")
    assert queued["video_url"] is None
    assert queued["download_url"] is None
    assert client.get(f"/api/media/{queued['job_id']}/video").status_code == 409

    executor.run_next()
    completed = client.get(f"/api/renders/{queued['job_id']}")
    body = completed.json()
    assert completed.status_code == 200
    assert body["status"] == "completed"
    assert body["duration_seconds"] == 3.25
    assert body["output_filename"].endswith(".mp4")
    assert body["video_url"] == f"/api/media/{queued['job_id']}/video"
    assert body["download_url"] == f"/api/media/{queued['job_id']}/download"
    assert body["manifest_url"] == f"/api/media/{queued['job_id']}/manifest"

    video = client.get(body["video_url"])
    download = client.get(body["download_url"])
    captions = client.get(body["captions_url"])
    manifest = client.get(body["manifest_url"])
    assert video.status_code == 200
    assert video.headers["content-type"] == "video/mp4"
    assert video.content == b"actual-test-mp4-bytes"
    assert download.status_code == 200
    assert "attachment" in download.headers["content-disposition"]
    assert download.content == video.content
    assert captions.status_code == 200
    assert manifest.status_code == 200
    assert manifest.json()["lesson_id"] == lesson.id
    assert "नमस्ते → ಕನ್ನಡ" in captions.content.decode("utf-8")
    record = manager._jobs[queued["job_id"]]
    assert record.video_path.parent == (tmp_path / "safe-media").resolve()


def test_render_failure_has_no_media_links_and_can_be_retried(tmp_path, monkeypatch):
    executor = ManualExecutor()

    def failed_exporter(*_args):
        raise RuntimeError("synthetic render failure")

    manager = RenderJobManager(
        media_dir=tmp_path / "safe-media",
        exporter=failed_exporter,
        narrator_factory=object,
        executor=executor,
    )
    lesson = sample_lesson("A render that fails")
    manager.register_lesson(lesson)
    monkeypatch.setattr("backend.main.render_jobs", manager)
    client = TestClient(app)

    first = client.post(f"/api/lessons/{lesson.id}/render").json()
    executor.run_next()
    failed = client.get(f"/api/renders/{first['job_id']}").json()
    assert failed["status"] == "failed"
    assert failed["video_url"] is None
    assert failed["download_url"] is None
    assert failed["captions_url"] is None
    assert "export failed" in failed["error"].lower()
    assert client.get(f"/api/media/{first['job_id']}/video").status_code == 409

    retry = client.post(f"/api/lessons/{lesson.id}/render").json()
    assert retry["job_id"] != first["job_id"]
    assert retry["status"] == "queued"


def test_render_queue_is_bounded_and_client_cannot_choose_paths(tmp_path):
    executor = ManualExecutor()
    manager = RenderJobManager(
        media_dir=tmp_path / "safe-media",
        exporter=fake_exporter,
        narrator_factory=object,
        executor=executor,
        max_active_jobs=1,
    )
    first = sample_lesson("First lesson")
    second = sample_lesson("Second lesson")
    manager.register_lesson(first)
    manager.register_lesson(second)
    manager.start(first.id)

    with pytest.raises(RenderQueueFull):
        manager.start(second.id)
    with pytest.raises(RenderJobNotFound):
        manager.start("..\\outside\\file")


def test_repeat_render_request_is_idempotent_while_job_is_queued(tmp_path):
    executor = ManualExecutor()
    manager = RenderJobManager(
        media_dir=tmp_path / "safe-media",
        exporter=fake_exporter,
        narrator_factory=object,
        executor=executor,
    )
    lesson = sample_lesson()
    manager.register_lesson(lesson)

    first = manager.start(lesson.id)
    second = manager.start(lesson.id)

    assert second.job_id == first.job_id
    assert len(executor.tasks) == 1


def test_hindi_render_routes_to_local_hindi_voice(tmp_path):
    executor = ManualExecutor()
    captured = {}

    def capture_export(lesson, narrator, output_path, **kwargs):
        captured.update(kwargs)
        return fake_exporter(lesson, narrator, output_path)

    manager = RenderJobManager(
        media_dir=tmp_path / "safe-media",
        exporter=capture_export,
        narrator_factory=object,
        executor=executor,
    )
    lesson = sample_lesson().model_copy(update={
        "language": "hi",
        "scenes": [scene.model_copy(update={
            "title": "लूप का परिचय",
            "narration": "लूप हर फल के लिए एक निर्देश चलाता है।",
            "caption": "हर फल को एक बार देखें।",
        }) for scene in sample_lesson().scenes],
    })
    manager.register_lesson(lesson)

    manager.start(lesson.id)
    executor.run_next()

    assert captured == {"voice": "hf_alpha", "language": "hi"}


@pytest.mark.parametrize("language, message", [
    ("kn", "no local Kannada voice"),
    ("hi", "not written in Hindi script"),
])
def test_unavailable_or_wrong_script_voice_fails_explicitly(tmp_path, language, message, monkeypatch):
    manager = RenderJobManager(
        media_dir=tmp_path / "safe-media",
        exporter=fake_exporter,
        narrator_factory=object,
        executor=ManualExecutor(),
    )
    lesson = sample_lesson().model_copy(update={"language": language})
    manager.register_lesson(lesson)
    monkeypatch.setattr("backend.main.render_jobs", manager)
    response = TestClient(app).post(f"/api/lessons/{lesson.id}/render")

    with pytest.raises(RenderLanguageUnsupported, match=message):
        manager.start(lesson.id)
    assert response.status_code == 422
    assert message in response.json()["detail"]
