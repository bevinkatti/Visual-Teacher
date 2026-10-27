"""Reusable Pillow scene renderer used to build deterministic 720p lesson frames."""

from __future__ import annotations

import math
from functools import lru_cache
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from backend.schemas import Scene
from backend.services.visual_registry import (
    build_code_execution_timeline,
    renderer_key,
    visual_state_at_progress,
)


WIDTH = 1280
HEIGHT = 720
BG = (5, 13, 29)
PANEL = (9, 24, 48)
PANEL_ALT = (14, 36, 67)
WHITE = (241, 247, 255)
MUTED = (155, 180, 205)
BLUE = (62, 128, 255)
CYAN = (65, 208, 225)
YELLOW = (243, 190, 99)
GREEN = (86, 219, 172)
FONT_PATH = Path(r"C:\Windows\Fonts\segoeui.ttf")
FONT_BOLD_PATH = Path(r"C:\Windows\Fonts\segoeuib.ttf")
FONT_MONO_PATH = Path(r"C:\Windows\Fonts\consola.ttf")
DEVANAGARI_FONT_PATH = Path(r"C:\Windows\Fonts\Nirmala.ttc")
KANNADA_FONT_PATH = Path(r"C:\Windows\Fonts\tunga.ttf")


@lru_cache(maxsize=32)
def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    path = FONT_BOLD_PATH if bold else FONT_PATH
    try:
        return ImageFont.truetype(str(path), size=size)
    except OSError:
        return ImageFont.load_default()


@lru_cache(maxsize=8)
def _mono_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    try:
        return ImageFont.truetype(str(FONT_MONO_PATH), size=size)
    except OSError:
        return _font(size)


@lru_cache(maxsize=48)
def _script_font(size: int, bold: bool, script: str) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    if script == "devanagari":
        path = DEVANAGARI_FONT_PATH
    elif script == "kannada":
        path = KANNADA_FONT_PATH
    else:
        return _font(size, bold)
    try:
        return ImageFont.truetype(str(path), size=size)
    except OSError:
        return _font(size, bold)


def _font_for_text(text: str, size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    if any("\u0900" <= char <= "\u097f" for char in text):
        return _script_font(size, bold, "devanagari")
    if any("\u0c80" <= char <= "\u0cff" for char in text):
        return _script_font(size, bold, "kannada")
    return _font(size, bold)


def _wrap(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, width: int) -> list[str]:
    lines: list[str] = []
    for paragraph in text.splitlines() or [""]:
        words = paragraph.split()
        if not words:
            lines.append("")
            continue
        current = words[0]
        for word in words[1:]:
            candidate = f"{current} {word}"
            if draw.textlength(candidate, font=font) <= width:
                current = candidate
            else:
                lines.append(current)
                current = word
        lines.append(current)
    return lines


def _draw_centered(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    text: str,
    font: ImageFont.ImageFont,
    fill: tuple[int, int, int],
    *,
    spacing: int = 7,
) -> None:
    x0, y0, x1, y1 = box
    lines = _wrap(draw, text, font, x1 - x0 - 30)
    line_h = font.size + spacing if hasattr(font, "size") else 22
    total_h = len(lines) * line_h - spacing
    y = y0 + (y1 - y0 - total_h) // 2
    for line in lines:
        draw.text((x0 + (x1 - x0 - draw.textlength(line, font=font)) / 2, y), line, font=font, fill=fill)
        y += line_h


class SceneRenderer:
    """Render title, diagram/flow, and code walkthrough scene types."""

    def __init__(self) -> None:
        self._background = Image.new("RGB", (WIDTH, HEIGHT), BG)
        d = ImageDraw.Draw(self._background)
        for y in range(HEIGHT):
            amount = y / HEIGHT
            color = (5 + int(3 * amount), 13 + int(8 * amount), 29 + int(13 * amount))
            d.line((0, y, WIDTH, y), fill=color)
        for x in range(80, WIDTH, 80):
            d.line((x, 84, x, 566), fill=(9, 26, 48), width=1)
        d.ellipse((900, -210, 1420, 310), outline=(14, 46, 83), width=2)
        d.ellipse((-260, 410, 350, 1020), outline=(11, 35, 63), width=2)
        d.rectangle((0, 0, WIDTH, 5), fill=BLUE)

    def render(
        self,
        scene: Any,
        *,
        scene_progress: float,
        lesson_progress: float,
        scene_number: int,
        scene_count: int,
        visual_state: dict[str, Any] | None = None,
    ) -> Image.Image:
        progress = max(0.0, min(1.0, scene_progress))
        image = self._background.copy()
        draw = ImageDraw.Draw(image)

        draw.rounded_rectangle((62, 28, 97, 63), radius=10, fill=BLUE)
        draw.text((70, 31), "b.", font=_font(24, True), fill=WHITE)
        draw.text((112, 39), "BLU  /  VISUAL TEACHER", font=_font(14, True), fill=MUTED)
        draw.text((1056, 43), f"{scene_number:02d}  /  {scene_count:02d}", font=_font(14, True), fill=YELLOW)
        draw.line((62, 83, 1218, 83), fill=(27, 55, 87), width=1)

        draw.text((74, 112), f"SCENE {scene_number:02d}  ·  {renderer_key(scene).replace('_', ' ').upper()}", font=_font(13, True), fill=CYAN)
        title_font = _font_for_text(scene.title, 42, True)
        title_lines = _wrap(draw, scene.title, title_font, 1100)
        y = 142
        for line in title_lines[:2]:
            draw.text((74, y), line, font=title_font, fill=WHITE)
            y += 47

        visual_box = (64, 230, 1216, 558)
        draw.rounded_rectangle(visual_box, radius=18, fill=PANEL, outline=(27, 62, 102), width=2)
        key = renderer_key(scene)
        dispatch = {
            "concept_diagram": self._draw_concept,
            "process_flow": self._draw_flow,
            "legacy_code": self._draw_code,
            "code_execution": self._draw_code_execution,
        }
        if key == "code_execution":
            if visual_state is None and scene.execution_data is not None:
                visual_timeline = build_code_execution_timeline(scene.execution_data)
                visual_state = visual_state_at_progress(visual_timeline, progress)
            dispatch[key](draw, scene, progress, visual_state)
        elif key == "legacy_code":
            dispatch[key](draw, scene.visual_data, progress)
        else:
            dispatch[key](draw, scene.visual_data, progress)

        caption_box = (62, 584, 1218, 694)
        draw.rounded_rectangle(caption_box, radius=12, fill=(4, 11, 23), outline=(27, 55, 87), width=1)
        draw.text((86, 597), "CAPTION", font=_font(12, True), fill=CYAN)
        caption_font = _font_for_text(scene.caption, 20)
        caption_lines = _wrap(draw, scene.caption, caption_font, 1070)
        line_y = 619
        for line in caption_lines[:3]:
            draw.text((86, line_y), line, font=caption_font, fill=WHITE)
            line_y += 23

        draw.rounded_rectangle((62, 706, 1218, 712), radius=3, fill=(22, 46, 75))
        draw.rounded_rectangle((62, 706, 62 + int(1156 * max(0.0, min(1.0, lesson_progress))), 712), radius=3, fill=BLUE)
        return image

    @staticmethod
    def _draw_concept(draw: ImageDraw.ImageDraw, data: dict[str, str], progress: float) -> None:
        left = data.get("left") or next(iter(data.values()), "Start")
        relationship = data.get("relationship") or data.get("process") or "connects to"
        right = data.get("right") or data.get("output") or "Result"
        nodes = [(left, "INPUT", BLUE), (relationship, "RELATIONSHIP", CYAN), (right, "RESULT", YELLOW)]
        positions = [(106, 324, 385, 452), (457, 294, 823, 482), (895, 324, 1174, 452)]
        visible = min(3, max(1, int(progress * 3) + 1))
        for index, ((label, eyebrow, accent), box) in enumerate(zip(nodes, positions, strict=True)):
            x0, y0, x1, y1 = box
            active = index < visible
            outline = accent if active else (37, 64, 94)
            fill = (15, 43, 78) if active else PANEL_ALT
            draw.rounded_rectangle(box, radius=16, fill=fill, outline=outline, width=3 if active else 2)
            draw.text((x0 + 18, y0 + 14), eyebrow, font=_font(11, True), fill=accent if active else MUTED)
            _draw_centered(draw, (x0 + 10, y0 + 30, x1 - 10, y1 - 8), label, _font_for_text(label, 23 if index == 1 else 21, True), WHITE if active else MUTED)
            if index < 2:
                start_x = x1 + 12
                end_x = positions[index + 1][0] - 12
                color = CYAN if active and index + 1 < visible else (37, 64, 94)
                draw.line((start_x, 388, end_x, 388), fill=color, width=4)
                draw.polygon(((end_x - 12, 379), (end_x, 388), (end_x - 12, 397)), fill=color)
        draw.text((107, 500), "A relationship you can see", font=_font(15), fill=MUTED)

    @staticmethod
    def _draw_code(draw: ImageDraw.ImageDraw, data: dict[str, str], progress: float) -> None:
        x0, y0, x1, y1 = 142, 274, 1138, 520
        draw.rounded_rectangle((x0, y0, x1, y1), radius=15, fill=(17, 16, 23), outline=(68, 59, 82), width=2)
        code = data.get("code", "for i in range(3):\n    print(i)").splitlines()
        active_line = 1 if progress < 0.55 else 2
        for i, line in enumerate(code[:4], start=1):
            ly = y0 + 52 + (i - 1) * 57
            if i == active_line:
                draw.rounded_rectangle((x0 + 20, ly - 7, x1 - 20, ly + 41), radius=8, fill=(51, 40, 69))
            color = BLUE if i == 1 else GREEN
            draw.text((x0 + 50, ly), line, font=_mono_font(30), fill=color)
        draw.text((x0 + 54, y1 - 52), "OUTPUT", font=_font(12, True), fill=YELLOW)
        output = data.get("output", "0  1  2").split()
        shown = max(1, min(len(output), int(progress * len(output)) + 1))
        out_x = x0 + 180
        for token in output[:shown]:
            draw.rounded_rectangle((out_x, y1 - 61, out_x + 74, y1 - 28), radius=9, fill=(37, 51, 44))
            _draw_centered(draw, (out_x, y1 - 61, out_x + 74, y1 - 28), token, _font(16, True), GREEN)
            out_x += 88

    @staticmethod
    def _draw_flow(draw: ImageDraw.ImageDraw, data: dict[str, str], progress: float) -> None:
        preferred = ("input", "process", "step_2", "step_3", "output")
        steps = [(key, data[key]) for key in preferred if data.get(key)]
        if len(steps) < 2:
            steps = list(data.items())[:4]
        steps = steps[:4]
        if not steps:
            steps = [("start", "Observe"), ("result", "Understand")]
        start_x, y0 = 92, 326
        gap = 34
        node_w = (1096 - gap * (len(steps) - 1)) // len(steps)
        active = min(len(steps) - 1, int(progress * len(steps)))
        for index, (key, label) in enumerate(steps):
            x = start_x + index * (node_w + gap)
            visible = index <= active
            accent = (BLUE, CYAN, YELLOW, GREEN)[index]
            border = accent if visible else (35, 64, 97)
            fill = (14, 47, 82) if visible else PANEL_ALT
            draw.rounded_rectangle((x, y0, x + node_w, y0 + 126), radius=13, fill=fill, outline=border, width=3 if index == active else 2)
            draw.text((x + 15, y0 + 13), f"{index + 1:02d}  /  {key.replace('_', ' ').upper()}", font=_font(10, True), fill=accent if visible else MUTED)
            _draw_centered(draw, (x + 8, y0 + 32, x + node_w - 8, y0 + 116), label, _font_for_text(label, 19, True), WHITE if visible else MUTED)
            if index < len(steps) - 1:
                ax = x + node_w + 7
                end = ax + gap - 12
                color = CYAN if index < active else (35, 64, 97)
                draw.line((ax, y0 + 63, end, y0 + 63), fill=color, width=4)
                draw.polygon(((end - 9, y0 + 55), (end, y0 + 63), (end - 9, y0 + 71)), fill=color)
        draw.text((start_x, 480), "Each stage changes the state for the next one.", font=_font(16), fill=MUTED)

    @staticmethod
    def _draw_code_execution(
        draw: ImageDraw.ImageDraw,
        scene: Scene,
        progress: float,
        state: dict[str, Any] | None,
    ) -> None:
        data = scene.execution_data
        if data is None:
            SceneRenderer._draw_code(draw, scene.visual_data, progress)
            return
        if state is None:
            state = visual_state_at_progress(build_code_execution_timeline(data), progress) or {}

        left = (90, 266, 690, 526)
        right = (716, 266, 1190, 526)
        draw.rounded_rectangle(left, radius=13, fill=(4, 12, 25), outline=(30, 68, 111), width=2)
        draw.rounded_rectangle(right, radius=13, fill=(8, 27, 52), outline=(30, 68, 111), width=2)
        draw.text((112, 281), "PYTHON  /  DISPLAY ONLY", font=_font(11, True), fill=CYAN)
        lines = [f"for {data.variable_name} in {data.iterable_name}:", f"    print({data.variable_name})"]
        for line_number, line in enumerate(lines, start=1):
            y = 331 + (line_number - 1) * 62
            if line_number == state.get("active_line"):
                draw.rounded_rectangle((104, y - 8, 674, y + 43), radius=7, fill=(13, 47, 84), outline=(28, 91, 146), width=1)
            draw.text((126, y), line, font=_mono_font(24), fill=CYAN if line_number == 1 else GREEN)

        draw.text((742, 281), data.iterable_name.upper(), font=_font(11, True), fill=MUTED)
        values_text = "[ " + "   ·   ".join(data.values) + " ]"
        draw.text((742, 309), values_text, font=_font_for_text(values_text, 19, True), fill=WHITE)
        draw.line((742, 346, 1163, 346), fill=(28, 60, 96), width=1)
        iteration = int(state.get("iteration", 0))
        draw.text((742, 360), "ITERATION", font=_font(10, True), fill=MUTED)
        draw.text((742, 381), f"{iteration} / {len(data.values)}", font=_font(25, True), fill=BLUE if state.get("phase") != "complete" else GREEN)
        draw.text((915, 360), data.variable_name, font=_font(10, True), fill=MUTED)
        value = state.get("value")
        draw.text((915, 381), f'= "{value}"' if value is not None else "= —", font=_mono_font(18), fill=YELLOW)
        draw.text((742, 423), f"OUTPUT  /  print({data.variable_name})", font=_font(10, True), fill=MUTED)
        output = state.get("output", [])
        if output:
            for index, item in enumerate(output[-4:]):
                x = 742 + index * 102
                draw.rounded_rectangle((x, 447, x + 91, 483), radius=8, fill=(10, 54, 55), outline=(21, 115, 112), width=1)
                _draw_centered(draw, (x + 4, 449, x + 87, 481), str(item), _font(14, True), GREEN)
        else:
            draw.text((742, 452), "nothing printed yet", font=_font(13), fill=(117, 145, 171))

        status = str(state.get("status", "Ready to begin"))
        if len(status) > 60:
            status = status[:57] + "..."
        draw.rounded_rectangle((90, 536, 1190, 552), radius=7, fill=(12, 41, 70))
        draw.text((104, 535), status, font=_font_for_text(status, 12, True), fill=GREEN if state.get("phase") == "complete" else CYAN)
