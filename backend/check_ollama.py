"""Opt-in local Ollama integration check and three-topic benchmark."""

from __future__ import annotations

import argparse
import json
import time

from backend.schemas import LessonRequest
from backend.services.ollama_planner import OllamaPlanner, OllamaPlannerError


TOPICS = [
    "How do fractions show parts of a whole?",
    "Why does the Moon appear to change shape?",
    "How does a Python for loop repeat a command?",
]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--benchmark",
        action="store_true",
        help="Run three representative topics through the installed local model.",
    )
    args = parser.parse_args()
    topics = TOPICS if args.benchmark else TOPICS[:1]
    planner = OllamaPlanner()
    results = []

    for index, topic in enumerate(topics, start=1):
        request = LessonRequest(
            topic=topic,
            level="beginner",
            language="en",
            duration_seconds=30,
        )
        start = time.perf_counter()
        try:
            lesson = planner.plan(request)
        except OllamaPlannerError as exc:
            result = {
                "topic": topic,
                "call": index,
                "valid": False,
                "fallback": False,
                "error": exc.reason,
                "message": str(exc),
                "generation_seconds": time.perf_counter() - start,
            }
            results.append(result)
            print(json.dumps({"model": planner.model, "results": results}, indent=2))
            return 1
        results.append(
            {
                "topic": topic,
                "call": index,
                "call_phase": "first_call" if index == 1 else "subsequent_call",
                "generation_seconds": round(time.perf_counter() - start, 3),
                "valid": True,
                "source": lesson.source,
                "fallback": lesson.fallback,
                "scene_count": len(lesson.scenes),
            }
        )

    print(json.dumps({"model": planner.model, "results": results}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
