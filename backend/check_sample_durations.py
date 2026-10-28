"""Check estimated sample-lesson durations against targets (dev tool)."""
from backend.schemas import LessonRequest
from backend.services.duration_budget import speaking_rate, spoken_length
from backend.services.lesson_service import build_sample_lesson

for lang in ("en", "hi", "kn"):
    for dur in (30, 45, 60, 90):
        lesson = build_sample_lesson(
            LessonRequest(topic="How does a Python loop work?", language=lang, duration_seconds=dur)
        )
        engine = "parler" if lang == "kn" else "kokoro"
        rate = speaking_rate(engine, lang)
        speech = sum(spoken_length(s.narration) / rate for s in lesson.scenes)
        pauses = sum(s.pause_seconds for s in lesson.scenes)
        est = speech + pauses
        detail = ""
        if dur == 30:
            detail = " | scene_spoken=" + ",".join(
                str(spoken_length(s.narration)) for s in lesson.scenes
            )
        print(
            f"{lang} {dur}s: scenes={len(lesson.scenes)} "
            f"chars={sum(len(s.narration) for s in lesson.scenes)} "
            f"est={est:.1f}s ({100 * (est / dur - 1):+.1f}%){detail}"
        )
