"""Reusable Pillow scene renderer: deterministic 720p frames with motion design.

Every visual state is a pure function of scene progress, so exported MP4
frames and the browser preview stay in sync. Motion follows ease-out curves
and reveals that explain the teaching step instead of decorating it.
"""

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
ASSET_FONT_DIR = Path(__file__).resolve().parents[1] / "assets" / "fonts"
BG = (5, 13, 29)
PANEL = (9, 24, 48)
PANEL_ALT = (14, 36, 67)
WHITE = (241, 247, 255)
MUTED = (155, 180, 205)
BLUE = (62, 128, 255)
CYAN = (65, 208, 225)
YELLOW = (243, 190, 99)
GREEN = (86, 219, 172)
RED = (255, 122, 122)
DIM_TEXT = (58, 82, 112)
FONT_PATH = ASSET_FONT_DIR / "NotoSans-Latin-Variable.ttf"
FONT_BOLD_PATH = FONT_PATH
FONT_MONO_PATH = ASSET_FONT_DIR / "NotoSans-Mono-Variable.ttf"
DEVANAGARI_FONT_PATH = ASSET_FONT_DIR / "NotoSans-Devanagari-Variable.ttf"
DEVANAGARI_UI_FONT_PATH = ASSET_FONT_DIR / "NotoSans-Devanagari-UI-Variable.ttf"
KANNADA_FONT_PATH = ASSET_FONT_DIR / "NotoSans-Kannada-Variable.ttf"
KANNADA_UI_FONT_PATH = ASSET_FONT_DIR / "NotoSans-Kannada-UI-Regular.ttf"
KANNADA_UI_BOLD_FONT_PATH = ASSET_FONT_DIR / "NotoSans-Kannada-UI-SemiBold.ttf"
TAMIL_FONT_PATH = ASSET_FONT_DIR / "NotoSans-Tamil-Variable.ttf"
TELUGU_FONT_PATH = ASSET_FONT_DIR / "NotoSans-Telugu-Variable.ttf"
BENGALI_FONT_PATH = ASSET_FONT_DIR / "NotoSans-Bengali-Variable.ttf"

# script name -> (first codepoint, last codepoint, variable font path)
SCRIPT_REGISTRY = {
    "devanagari": (0x0900, 0x097F, DEVANAGARI_FONT_PATH),
    "kannada": (0x0C80, 0x0CFF, KANNADA_FONT_PATH),
    "tamil": (0x0B80, 0x0BFF, TAMIL_FONT_PATH),
    "telugu": (0x0C00, 0x0C7F, TELUGU_FONT_PATH),
    "bengali": (0x0980, 0x09FF, BENGALI_FONT_PATH),
}


# --------------------------------------------------------------------- motion


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def _seg(progress: float, start: float, end: float) -> float:
    """Eased 0..1 progress for one time window inside the scene."""
    return _clamp01((progress - start) / max(1e-6, end - start))


def _ease_out_cubic(t: float) -> float:
    t = _clamp01(t)
    return 1 - (1 - t) ** 3


def _ease_in_out(t: float) -> float:
    t = _clamp01(t)
    return 4 * t * t * t if t < 0.5 else 1 - ((-2 * t + 2) ** 3) / 2


def _ease_out_back(t: float, overshoot: float = 1.6) -> float:
    t = _clamp01(t) - 1
    return t * t * ((overshoot + 1) * t + overshoot) + 1


def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def _mix(
    c1: tuple[int, int, int],
    c2: tuple[int, int, int],
    t: float,
) -> tuple[int, int, int]:
    t = _clamp01(t)
    return tuple(int(round(_lerp(a, b, t))) for a, b in zip(c1, c2))  # type: ignore[return-value]


def _appear(
    color: tuple[int, int, int],
    t: float,
    base: tuple[int, int, int] = PANEL,
) -> tuple[int, int, int]:
    """Fade a fill or text color in from the panel tone as its window opens."""
    return _mix(base, color, _ease_out_cubic(t))


def _slide(t: float, distance: float) -> float:
    """Offset that shrinks from ``distance`` to 0 as the window opens."""
    return (1 - _ease_out_cubic(t)) * distance


def _pulse(progress: float, cycles: float = 2.0) -> float:
    """0..1..0 breathing value; zero at the scene start and end."""
    if progress <= 0 or progress >= 1:
        return 0.0
    return max(0.0, math.sin(progress * math.tau * cycles)) ** 2


def _typewriter(text: str, t: float) -> str:
    if not text:
        return text
    shown = int(round(len(text) * (_ease_out_cubic(t) * 0.4 + _clamp01(t) * 0.6)))
    return text[:shown]


def _reveal_lines(lines: list[str], t: float) -> list[str]:
    """Typewriter across wrapped lines; returns the partially revealed lines."""
    if not lines:
        return lines
    total = sum(len(line) for line in lines)
    budget = int(round(total * _clamp01(t)))
    revealed: list[str] = []
    for line in lines:
        if budget <= 0:
            break
        take = min(len(line), budget)
        revealed.append(line[:take])
        budget -= take
    return revealed


def _pop_scale(t: float, base: float = 0.55) -> float:
    """Scale factor that springs from ``base`` to 1 with slight overshoot."""
    return base + (1 - base) * _ease_out_back(t)


def _shrink_box(
    box: tuple[int, int, int, int],
    scale: float,
) -> tuple[int, int, int, int]:
    x0, y0, x1, y1 = box
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    hw, hh = (x1 - x0) / 2 * scale, (y1 - y0) / 2 * scale
    return (int(cx - hw), int(cy - hh), int(cx + hw), int(cy + hh))


def _glow_box(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    radius: int,
    color: tuple[int, int, int],
    strength: float,
    width: int = 2,
) -> None:
    """Soft glow approximation: concentric outlines blended toward the panel."""
    strength = _clamp01(strength)
    if strength <= 0.02:
        draw.rounded_rectangle(box, radius=radius, outline=color, width=width)
        return
    for step in (3, 2, 1):
        tinted = _mix((16, 34, 58), color, 0.25 + 0.25 * step)
        grow = step * 2
        draw.rounded_rectangle(
            (box[0] - grow, box[1] - grow, box[2] + grow, box[3] + grow),
            radius=radius + grow,
            outline=tinted,
            width=1,
        )
    draw.rounded_rectangle(
        box,
        radius=radius,
        outline=_mix(color, WHITE, 0.25 * strength),
        width=width,
    )


# ------------------------------------------------------- fonts and wrapping


_BOLD_FONT_IDS: dict[int, bool] = {}


def _load_font(path: Path, size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    try:
        font = ImageFont.truetype(str(path), size=size)
    except OSError as exc:
        raise FileNotFoundError(f"Required bundled font could not be loaded: {path}") from exc
    try:
        axes = font.get_variation_axes()
    except OSError:
        # Pillow reports OSError for static fonts, which have no variation axes.
        axes = []
    if axes:
        values = [axis["default"] for axis in axes]
        for index, axis in enumerate(axes):
            name = axis.get("name", b"").decode("ascii", errors="ignore").casefold()
            if name in {"weight", "wght"}:
                values[index] = min(axis["maximum"], max(axis["minimum"], 700 if bold else 400))
        try:
            font.set_variation_by_axes(values)
        except (AttributeError, OSError, ValueError) as exc:
            raise RuntimeError(f"Could not select the requested weight for bundled font: {path}") from exc
    _BOLD_FONT_IDS[id(font)] = bool(bold)
    return font


@lru_cache(maxsize=32)
def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    return _load_font(FONT_BOLD_PATH if bold else FONT_PATH, size, bold)


@lru_cache(maxsize=8)
def _mono_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    return _load_font(FONT_MONO_PATH, size)


@lru_cache(maxsize=64)
def _script_font(
    size: int,
    bold: bool,
    script: str,
    includes_latin: bool = False,
) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    if script == "devanagari":
        path = DEVANAGARI_UI_FONT_PATH if includes_latin else DEVANAGARI_FONT_PATH
    elif script == "kannada":
        path = (KANNADA_UI_BOLD_FONT_PATH if bold else KANNADA_UI_FONT_PATH) if includes_latin else KANNADA_FONT_PATH
    elif script == "tamil":
        path = TAMIL_FONT_PATH
    elif script == "telugu":
        path = TELUGU_FONT_PATH
    elif script == "bengali":
        path = BENGALI_FONT_PATH
    else:
        return _font(size, bold)
    return _load_font(path, size, bold)


def _char_script(char: str) -> str | None:
    if char.isascii():
        return "latin"
    for name, (low, high, _path) in SCRIPT_REGISTRY.items():
        if low <= ord(char) <= high:
            return name
    return None


def _font_for_text(text: str, size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for char in text:
        script = _char_script(char)
        if script in {None, "latin"}:
            continue
        includes_latin = any(item.isascii() and item.isalpha() for item in text)
        return _script_font(size, bold, script, includes_latin)
    return _font(size, bold)


def _is_bold_font(font: ImageFont.ImageFont) -> bool:
    """Weight used when this font object was created (Pillow cannot report it)."""
    return _BOLD_FONT_IDS.get(id(font), False)


def _font_key(font: ImageFont.ImageFont, bold: bool) -> str:
    return f"{int(getattr(font, 'size', 20))}|{int(bool(bold or _is_bold_font(font)))}|{getattr(font, 'path', '')}"


@lru_cache(maxsize=768)
def _wrap_cached(text: str, size: int, bold: bool, font_path: str, width: int) -> tuple[str, ...]:
    font = _font_for_measure(size, bold, font_path)
    lines: list[str] = []
    for paragraph in text.splitlines() or [""]:
        words = paragraph.split()
        if not words:
            lines.append("")
            continue
        current = ""
        for word in words:
            candidate = f"{current} {word}" if current else word
            if _measure(candidate, size, bold, font_path) <= width:
                current = candidate
                continue
            if current:
                lines.append(current)
                current = ""
            if _measure(word, size, bold, font_path) <= width:
                lines.append(word)
                continue
            fragment = ""
            for char in word:
                candidate_fragment = fragment + char
                if fragment and _measure(candidate_fragment, size, bold, font_path) > width:
                    lines.append(fragment)
                    fragment = char
                else:
                    fragment = candidate_fragment
            current = fragment
        if current:
            lines.append(current)
    return tuple(lines)


@lru_cache(maxsize=64)
def _font_for_measure(size: int, bold: bool, font_path: str):
    if font_path:
        return _load_font(Path(font_path), size, bold)
    return _font(size, bold)


@lru_cache(maxsize=2048)
def _measure(text: str, size: int, bold: bool, font_path: str) -> float:
    font = _font_for_measure(size, bold, font_path)
    if not (text and any(not item.isascii() for item in text)):
        return font.getlength(text)
    return sum(run_font.getlength(value) for value, run_font in _script_runs(text, size, bold))


def _wrap(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, width: int) -> list[str]:
    key = _font_key(font, False)
    size, bold, font_path = key.split("|", 2)
    return list(_wrap_cached(text, int(size), bold == "1", font_path, int(width)))


def _script_runs(text: str, size: int, bold: bool) -> list[tuple[str, ImageFont.ImageFont]]:
    runs: list[tuple[str, ImageFont.ImageFont]] = []
    current_script: str | None = None
    current_chars: list[str] = []

    def flush() -> None:
        nonlocal current_chars
        if current_chars and current_script is not None:
            if current_script == "latin":
                run_font = _font(size, bold)
            else:
                run_font = _script_font(size, bold, current_script)
            runs.append(("".join(current_chars), run_font))
            current_chars = []

    for char in text:
        script = _char_script(char)
        if script is None:
            script = current_script or "latin"
        if current_script is not None and script != current_script:
            flush()
        current_script = script
        current_chars.append(char)
    flush()
    return runs


def _script_aware_textlength(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.ImageFont,
    *,
    bold: bool = False,
) -> float:
    key = _font_key(font, bold)
    size, effective_bold, font_path = key.split("|", 2)
    return _measure(text, int(size), effective_bold == "1", font_path)


def _draw_script_aware(
    draw: ImageDraw.ImageDraw,
    position: tuple[float, float],
    text: str,
    font: ImageFont.ImageFont,
    fill: tuple[int, int, int],
    *,
    bold: bool = False,
) -> None:
    """Draw Latin and Indic runs with the matching bundled font assets."""
    if not (text and any(not item.isascii() for item in text)):
        draw.text(position, text, font=font, fill=fill)
        return
    key = _font_key(font, bold)
    size, effective_bold, _font_path = key.split("|", 2)
    x, y = position
    for value, run_font in _script_runs(text, int(size), effective_bold == "1"):
        draw.text((x, y), value, font=run_font, fill=fill)
        x += run_font.getlength(value)


def _draw_centered(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    text: str,
    font: ImageFont.ImageFont,
    fill: tuple[int, int, int],
    *,
    spacing: int = 7,
    bold: bool = False,
) -> None:
    x0, y0, x1, y1 = box
    lines = _wrap(draw, text, font, x1 - x0 - 30)
    line_h = font.size + spacing if hasattr(font, "size") else 22
    total_h = len(lines) * line_h - spacing
    y = y0 + (y1 - y0 - total_h) // 2
    for line in lines:
        text_width = _script_aware_textlength(draw, line, font, bold=bold)
        _draw_script_aware(draw, (x0 + (x1 - x0 - text_width) / 2, y), line, font, fill, bold=bold)
        y += line_h


# ------------------------------------------------------------- scene renderer


class SceneRenderer:
    """Render title, diagram/flow, and code walkthrough scene types."""

    def __init__(self) -> None:
        self._background = self._build_background()

    @staticmethod
    def _build_background() -> Image.Image:
        background = Image.new("RGB", (WIDTH, HEIGHT), BG)
        draw = ImageDraw.Draw(background)
        for y in range(HEIGHT):
            amount = y / HEIGHT
            color = (5 + int(3 * amount), 13 + int(8 * amount), 29 + int(13 * amount))
            draw.line((0, y, WIDTH, y), fill=color)
        for x in range(64, WIDTH, 64):
            draw.line((x, 84, x, 566), fill=(8, 23, 43), width=1)
        for y in range(120, 566, 64):
            draw.line((62, y, 1218, y), fill=(7, 20, 39), width=1)
        draw.ellipse((900, -210, 1420, 310), outline=(14, 46, 83), width=2)
        draw.ellipse((-260, 410, 350, 1020), outline=(11, 35, 63), width=2)
        draw.rectangle((0, 0, WIDTH, 5), fill=BLUE)
        return background

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
        hairline = int(1156 * _ease_out_cubic(_seg(progress, 0.0, 0.08)))
        if hairline:
            draw.line((62, 83, 62 + hairline, 83), fill=(32, 74, 118), width=1)

        eyebrow = _typewriter(
            f"SCENE {scene_number:02d}  ·  {renderer_key(scene).replace('_', ' ').upper()}",
            _seg(progress, 0.0, 0.06),
        )
        draw.text((74, 112), eyebrow, font=_font(13, True), fill=CYAN)

        title_t = _ease_out_cubic(_seg(progress, 0.03, 0.12))
        title_font = _font_for_text(scene.title, 42, True)
        title_lines = _wrap(draw, scene.title, title_font, 1100)[:2]
        title_y = 142 + _slide(title_t, 22)
        title_color = _appear(WHITE, title_t)
        underline_target = 0.0
        for line in title_lines:
            _draw_script_aware(draw, (74 + (1 - title_t) * 26, title_y), line, title_font, title_color, bold=True)
            underline_target = max(underline_target, _script_aware_textlength(draw, line, title_font, bold=True))
            title_y += 47
        underline = int(underline_target * _ease_out_cubic(_seg(progress, 0.08, 0.18)))
        if underline:
            glow = _pulse(progress, 1.0) * 0.5
            draw.rounded_rectangle(
                (76, 236, 76 + underline, 240),
                radius=2,
                fill=_mix(BLUE, CYAN, glow),
            )

        key = renderer_key(scene)
        dispatch = {
            "title_card": self._draw_title_card,
            "concept_diagram": self._draw_concept,
            "concept": self._draw_concept,
            "process_flow": self._draw_flow,
            "flow": self._draw_flow,
            "code": self._draw_code,
            "legacy_code": self._draw_code,
            "fraction_model": self._draw_fraction_model,
            "cause_effect": self._draw_cause_effect,
        }
        body = dispatch.get(key)
        if body is not None:
            body(draw, scene, progress)
        else:
            state = visual_state
            if state is None and getattr(scene, "execution_data", None) is not None:
                state = visual_state_at_progress(
                    build_code_execution_timeline(scene.execution_data), progress
                )
            self._draw_code_execution(draw, scene, progress, state or {})

        # Caption panel with typewriter reveal synced to the scene audio.
        panel_t = _ease_out_cubic(_seg(progress, 0.0, 0.05))
        panel_y = 584 + _slide(panel_t, 14)
        draw.rounded_rectangle(
            (62, panel_y, 1218, panel_y + 110),
            radius=12,
            fill=(4, 11, 23),
            outline=(27, 55, 87),
            width=1,
        )
        draw.text((86, panel_y + 13), "CAPTION", font=_font(12, True), fill=CYAN)
        caption_font = _font_for_text(scene.caption, 20)
        caption_lines = _wrap(draw, scene.caption, caption_font, 1070)
        while len(caption_lines) > 4 and getattr(caption_font, "size", 20) > 10:
            caption_font = _font_for_text(scene.caption, getattr(caption_font, "size", 20) - 2)
            caption_lines = _wrap(draw, scene.caption, caption_font, 1070)
        if len(caption_lines) > 4:
            # Never fail a render over caption length: translated captions can
            # run long. Keep the first three lines plus an ellipsis tail; the
            # narration still carries the full sentence.
            caption_lines = caption_lines[:3] + [caption_lines[3][:44].rstrip() + "…"]
        shown_lines = _reveal_lines(caption_lines, _seg(progress, 0.02, 0.88))
        line_y = panel_y + 35
        line_spacing = 23 if len(caption_lines) <= 3 else 18
        cursor_line = len(shown_lines) - 1
        for index, line in enumerate(shown_lines):
            color = WHITE if index < cursor_line else _mix(MUTED, WHITE, 0.75)
            _draw_script_aware(draw, (86, line_y), line, caption_font, color)
            if index == cursor_line and 0.02 < progress < 0.9 and int(progress * 240) % 2 == 0:
                cursor_x = 86 + _script_aware_textlength(draw, line, caption_font)
                draw.rectangle((cursor_x + 3, line_y + 2, cursor_x + 5, line_y + 17), fill=CYAN)
            line_y += line_spacing

        # Lesson progress bar with eased fill and a glowing head.
        filled = _ease_in_out(_clamp01(lesson_progress))
        head_x = 62 + int(1156 * filled)
        draw.rounded_rectangle((62, 706, 1218, 712), radius=3, fill=(22, 46, 75))
        if filled > 0.005:
            draw.rounded_rectangle((62, 706, head_x, 712), radius=3, fill=BLUE)
            draw.ellipse((head_x - 5, 704, head_x + 5, 714), fill=CYAN)
            draw.ellipse((head_x - 9, 702, head_x + 9, 716), outline=_mix(CYAN, BG, 0.55), width=1)
        return image

    @staticmethod
    def _draw_title_card(draw: ImageDraw.ImageDraw, scene: Scene, progress: float) -> None:
        card_t = _ease_out_cubic(_seg(progress, 0.0, 0.10))
        card = (126, 260 + _slide(card_t, 26), 1154, 530 + _slide(card_t, 26))
        _glow_box(draw, card, radius=22, color=(45, 104, 168), strength=0.3 + 0.3 * _pulse(progress, 1.0))
        draw.rounded_rectangle(card, radius=22, fill=(12, 34, 62), outline=(45, 104, 168), width=2)

        angle = progress * 300
        cx, cy = card[2] - 46, card[1] + 46
        for step in range(24):
            a0 = angle + step * 9
            shade = _mix((26, 60, 100), CYAN, step / 24)
            draw.arc((cx - 22, cy - 22, cx + 22, cy + 22), start=a0, end=a0 + 5, fill=shade, width=3)

        kicker = _typewriter("TODAY'S TOPIC", _seg(progress, 0.06, 0.18))
        draw.text((164, 289), kicker, font=_font(12, True), fill=CYAN)

        topic = scene.visual_data.get("topic", scene.title)
        title_size = 34
        title_font = _font_for_text(topic, title_size, True)
        title_lines = _wrap(draw, topic, title_font, 900)
        while len(title_lines) > 2 and title_size > 20:
            title_size -= 2
            title_font = _font_for_text(topic, title_size, True)
            title_lines = _wrap(draw, topic, title_font, 900)
        if len(title_lines) > 3:
            raise ValueError("Title-card topic is too long to fit safely in the 720p scene area.")
        title_y = (330 if len(title_lines) <= 2 else 313) + _slide(_seg(progress, 0.12, 0.30), 18)
        line_step = title_size + 7
        for index, line in enumerate(title_lines):
            window_start = 0.12 + index * 0.06
            slide_t = _ease_out_cubic(_seg(progress, window_start, window_start + 0.14))
            shown = _typewriter(line, _seg(progress, window_start + 0.02, window_start + 0.18))
            if shown:
                _draw_script_aware(draw, (164 + (1 - slide_t) * 30, title_y), shown, title_font, WHITE, bold=True)
            title_y += line_step

        subtitle = scene.visual_data.get("subtitle")
        if subtitle:
            subtitle_t = _ease_out_cubic(_seg(progress, 0.34, 0.50))
            subtitle_size = 18
            subtitle_font = _font_for_text(subtitle, subtitle_size)
            subtitle_lines = _wrap(draw, subtitle, subtitle_font, 900)
            while len(subtitle_lines) > 2 and subtitle_size > 12:
                subtitle_size -= 2
                subtitle_font = _font_for_text(subtitle, subtitle_size)
                subtitle_lines = _wrap(draw, subtitle, subtitle_font, 900)
            if len(subtitle_lines) > 2:
                raise ValueError("Title-card subtitle is too long to fit safely in the 720p scene area.")
            for index, line in enumerate(subtitle_lines):
                shown = _typewriter(line, _seg(progress, 0.38 + index * 0.06, 0.58 + index * 0.06))
                _draw_script_aware(
                    draw,
                    (166, 443 + index * 22 + _slide(subtitle_t, 12)),
                    shown,
                    subtitle_font,
                    _appear(MUTED, subtitle_t, base=(12, 34, 62)),
                )
        bar_t = _ease_out_cubic(_seg(progress, 0.15, 0.85))
        draw.rounded_rectangle((164, 493, 1116, 499), radius=3, fill=(22, 46, 75))
        width = int(952 * bar_t)
        if width:
            draw.rounded_rectangle((164, 493, 164 + width, 499), radius=3, fill=BLUE)
            head = 164 + width
            draw.ellipse((head - 6, 491, head + 6, 501), fill=_mix(BLUE, CYAN, _pulse(progress, 3.0)))

    @staticmethod
    def _draw_concept(draw: ImageDraw.ImageDraw, data_or_scene: Any, progress: float) -> None:
        data = data_or_scene.visual_data if isinstance(data_or_scene, Scene) else data_or_scene
        left = data.get("left") or next(iter(data.values()), "Start")
        relationship = data.get("relationship") or data.get("process") or "connects to"
        right = data.get("right") or data.get("output") or "Result"
        nodes = [(left, "INPUT", BLUE), (relationship, "RELATIONSHIP", CYAN), (right, "RESULT", YELLOW)]
        boxes = [(106, 324, 385, 452), (457, 294, 823, 482), (895, 324, 1174, 452)]
        windows = [(0.02, 0.18), (0.20, 0.38), (0.42, 0.60)]
        slide_from = [(-70.0, 0.0), (0.0, 46.0), (70.0, 0.0)]

        for index in range(3):
            start, end = windows[index]
            t_raw = _seg(progress, start, end)
            t_eased = _ease_out_back(t_raw)
            dx, dy = slide_from[index]
            x0, y0, x1, y1 = boxes[index]
            box = (
                int(x0 + (1 - _ease_out_cubic(t_raw)) * dx),
                int(y0 + (1 - _ease_out_cubic(t_raw)) * dy),
                int(x1 + (1 - _ease_out_cubic(t_raw)) * dx),
                int(y1 + (1 - _ease_out_cubic(t_raw)) * dy),
            )
            label, eyebrow, accent = nodes[index]
            outline = _appear(accent, t_raw, base=(37, 64, 94))
            strength = 0.55 * _pulse(progress - index * 0.12, 1.0) if t_raw >= 0.999 else 0.0
            _glow_box(draw, box, radius=16, color=outline, strength=strength)
            draw.rounded_rectangle(
                box,
                radius=16,
                fill=_appear((15, 43, 78), t_raw),
                outline=outline,
                width=3 if index == 1 else 2,
            )
            draw.text(
                (box[0] + 18, box[1] + 14),
                _typewriter(eyebrow, _seg(progress, end - 0.05, end)),
                font=_font(11, True),
                fill=_appear(accent, t_raw, base=DIM_TEXT),
            )
            _draw_centered(
                draw,
                box,
                label,
                _font_for_text(label, 23 if index == 1 else 21, True),
                _appear(WHITE, t_raw),
                bold=True,
            )

        connector_pairs = [
            (boxes[0], boxes[1], windows[1][0]),
            (boxes[1], boxes[2], windows[2][0]),
        ]
        for index, (source, target, gate) in enumerate(connector_pairs):
            t = _ease_out_cubic(_seg(progress, gate, gate + 0.16))
            if t <= 0.01:
                continue
            y = 388
            start_x = source[2] + 14
            target_x = target[0] - 14
            end_x = start_x + int((target_x - start_x) * t)
            draw.line((start_x, y, end_x, y), fill=_mix((35, 64, 97), CYAN, t), width=4)
            # A packet rides the connector's leading edge, showing the idea
            # flowing from one node into the next (same language as the
            # process-flow packet).
            if t < 0.92:
                draw.ellipse((end_x - 7, y - 7, end_x + 7, y + 7), fill=WHITE)
                draw.ellipse((end_x - 3, y - 3, end_x + 3, y + 3), fill=CYAN)
            elif t >= 0.92:
                draw.polygon(((end_x - 12, y - 9), (end_x, y), (end_x - 12, y + 9)), fill=CYAN)
                settled_t = _seg(progress, gate + 0.16, gate + 0.24)
                if settled_t > 0:
                    mid_x = (start_x + target_x) // 2
                    drift = int(6 * (settled_t - 0.5))
                    draw.ellipse(
                        (mid_x - 5 + drift, y - 5, mid_x + 5 + drift, y + 5),
                        fill=_mix(BG, CYAN, 0.5 + 0.5 * settled_t),
                    )

        footnote_t = _seg(progress, 0.66, 0.80)
        if footnote_t > 0:
            draw.text(
                (107, 500),
                _typewriter("Each idea builds the next one.", footnote_t),
                font=_font(15),
                fill=_appear(MUTED, footnote_t, base=BG),
            )

    @staticmethod
    def _draw_flow(draw: ImageDraw.ImageDraw, data_or_scene: Any, progress: float) -> None:
        data = data_or_scene.visual_data if isinstance(data_or_scene, Scene) else data_or_scene
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
        node_centers: list[tuple[int, int]] = []

        for index, (key, label) in enumerate(steps):
            window_start = 0.02 + index * 0.09
            t_raw = _seg(progress, window_start, window_start + 0.14)
            t_eased = _ease_out_back(t_raw)
            x = start_x + index * (node_w + gap) + (1 - t_eased) * 44
            y = y0 + (1 - _ease_out_cubic(t_raw)) * 18
            node_centers.append((x + node_w // 2, y + 63))
            if t_raw <= 0.01:
                continue
            accent = (BLUE, CYAN, YELLOW, GREEN)[index]
            border = _appear(accent, t_raw, base=(35, 64, 97))
            strength = 0.5 * _pulse(progress - index * 0.15, 1.2) if t_raw >= 0.999 else 0.0
            _glow_box(draw, (x, y, x + node_w, y + 126), radius=13, color=border, strength=strength)
            draw.rounded_rectangle(
                (x, y, x + node_w, y + 126),
                radius=13,
                fill=_appear((14, 47, 82), t_raw),
                outline=border,
                width=2,
            )
            draw.text(
                (x + 15, y + 13),
                _typewriter(
                    f"{index + 1:02d}  /  {key.replace('_', ' ').upper()}",
                    _seg(progress, window_start + 0.06, window_start + 0.14),
                ),
                font=_font(10, True),
                fill=_appear(accent, t_raw, base=DIM_TEXT),
            )
            _draw_centered(
                draw,
                (x, y, x + node_w, y + 116),
                _typewriter(label, _seg(progress, window_start + 0.05, window_start + 0.2)),
                _font_for_text(label, 19, True),
                _appear(WHITE, t_raw),
                bold=True,
            )

        # A packet travels the pipeline, showing state flowing forward.
        if len(node_centers) >= 2 and progress > 0.05:
            head = _clamp01((progress - 0.08) / max(1e-6, 0.86)) * (len(node_centers) - 1)
            segment = min(int(head), len(node_centers) - 2)
            local = _clamp01(head - segment)
            (ax, ay), (bx, by) = node_centers[segment], node_centers[segment + 1]
            px, py = int(_lerp(ax, bx, local)), int(_lerp(ay, by, local))
            draw.line((ax + 24, ay, bx - 24, by), fill=(35, 64, 97), width=3)
            draw.line((ax + 24, ay, px, py), fill=_mix(CYAN, WHITE, 0.25), width=3)
            for tail in range(1, 4):
                tx = int(_lerp(ax, px, max(0.0, local - tail * 0.05)))
                draw.ellipse((tx - 4, py - 4, tx + 4, py + 4), fill=_mix(BG, CYAN, 0.35 / tail))
            draw.ellipse((px - 7, py - 7, px + 7, py + 7), fill=WHITE)
            draw.ellipse((px - 3, py - 3, px + 3, py + 3), fill=CYAN)

    @staticmethod
    def _draw_fraction_model(draw: ImageDraw.ImageDraw, scene: Scene, progress: float) -> None:
        data = scene.fraction_data
        if data is None:
            SceneRenderer._draw_concept(draw, scene, progress)
            return

        numerator, denominator = data.numerator, data.denominator
        left, right = 154, 1126
        top, bottom = 333, 434
        outline_t = _seg(progress, 0.08, 0.20)
        if outline_t <= 0:
            return

        draw.rounded_rectangle(
            (left - 12, top - 12, right + 12, bottom + 12),
            radius=15,
            fill=_appear((8, 25, 46), outline_t),
            outline=_appear((43, 84, 128), outline_t),
            width=2,
        )
        cell_width = (right - left) / denominator
        per_cell = 0.44 / numerator
        for index in range(denominator):
            x0 = int(left + index * cell_width + 3)
            x1 = int(left + (index + 1) * cell_width - 3)
            cell = (x0, top, x1, bottom)
            draw.rounded_rectangle(
                cell,
                radius=7,
                fill=(12, 34, 58),
                outline=(47, 81, 116),
                width=2,
            )
            if index >= numerator:
                continue

            fill_t = _seg(
                progress,
                0.25 + index * per_cell,
                0.25 + (index + 1) * per_cell,
            )
            if fill_t <= 0:
                continue
            fill_right = x0 + int((x1 - x0) * fill_t)
            draw.rounded_rectangle(
                (x0 + 2, top + 2, max(x0 + 2, fill_right), bottom - 2),
                radius=5,
                fill=_mix((14, 50, 78), BLUE, 0.25 + 0.75 * fill_t),
            )
            draw.rounded_rectangle(cell, radius=7, outline=(76, 165, 242), width=2)

        notation_t = _seg(progress, 0.73, 0.84)
        if notation_t > 0:
            notation = f"{numerator} / {denominator}"
            _draw_centered(
                draw,
                (420, 455, 860, 526),
                notation,
                _font(34, True),
                _appear(WHITE, notation_t, base=BG),
                bold=True,
            )

    @staticmethod
    def _draw_cause_effect(draw: ImageDraw.ImageDraw, scene: Scene, progress: float) -> None:
        data = scene.cause_effect_data
        if data is None:
            SceneRenderer._draw_concept(draw, scene, progress)
            return

        input_box = (84, 0, 348, 0)
        mechanism_box = (492, 350, 788, 474)
        output_box = (932, 0, 1196, 0)
        node_height = 58
        node_gap = 14

        def stack_boxes(count: int, x0: int, x1: int) -> list[tuple[int, int, int, int]]:
            total_height = count * node_height + (count - 1) * node_gap
            start_y = 412 - total_height // 2
            return [
                (x0, start_y + index * (node_height + node_gap), x1, start_y + index * (node_height + node_gap) + node_height)
                for index in range(count)
            ]

        inputs = stack_boxes(len(data.inputs), input_box[0], input_box[2])
        outputs = stack_boxes(len(data.outputs), output_box[0], output_box[2])

        def center_y(box: tuple[int, int, int, int]) -> int:
            return (box[1] + box[3]) // 2

        mechanism_t = _seg(progress, 0.27, 0.40)
        incoming_t = _seg(progress, 0.38, 0.65)
        outgoing_t = _seg(progress, 0.65, 0.84)

        for index, box in enumerate(inputs):
            x_start, y_start = box[2] + 8, center_y(box)
            x_end, y_end = mechanism_box[0] - 8, center_y(mechanism_box)
            if mechanism_t > 0:
                draw.line((x_start, y_start, x_end, y_end), fill=(37, 67, 98), width=3)
            px = int(_lerp(x_start, x_end, incoming_t))
            py = int(_lerp(y_start, y_end, incoming_t))
            if incoming_t > 0:
                draw.line((x_start, y_start, px, py), fill=_mix(CYAN, WHITE, 0.35 * incoming_t), width=3)
                draw.ellipse((px - 6, py - 6, px + 6, py + 6), fill=WHITE)

        for index, box in enumerate(outputs):
            x_start, y_start = mechanism_box[2] + 8, center_y(mechanism_box)
            x_end, y_end = box[0] - 8, center_y(box)
            if mechanism_t > 0:
                draw.line((x_start, y_start, x_end, y_end), fill=(37, 67, 98), width=3)
            px = int(_lerp(x_start, x_end, outgoing_t))
            py = int(_lerp(y_start, y_end, outgoing_t))
            if outgoing_t > 0:
                draw.line((x_start, y_start, px, py), fill=_mix(YELLOW, WHITE, 0.35 * outgoing_t), width=3)
                draw.ellipse((px - 6, py - 6, px + 6, py + 6), fill=WHITE)

        def draw_node(
            box: tuple[int, int, int, int],
            label: str,
            appear_t: float,
            accent: tuple[int, int, int],
            font_size: int,
        ) -> None:
            if appear_t <= 0:
                return
            fill = _appear((13, 38, 66), appear_t)
            border = _appear(accent, appear_t, base=(37, 64, 94))
            draw.rounded_rectangle(box, radius=13, fill=fill, outline=border, width=2)
            _draw_centered(
                draw,
                box,
                label,
                _font_for_text(label, font_size, True),
                _appear(WHITE, appear_t),
                spacing=3,
                bold=True,
            )

        for index, (box, label) in enumerate(zip(inputs, data.inputs, strict=True)):
            appear_t = _seg(progress, 0.08 + index * 0.075, 0.24 + index * 0.075)
            draw_node(box, label, appear_t, BLUE, 17)

        draw_node(mechanism_box, data.mechanism, mechanism_t, CYAN, 22)

        for index, (box, label) in enumerate(zip(outputs, data.outputs, strict=True)):
            appear_t = _seg(progress, 0.66 + index * 0.08, 0.81 + index * 0.08)
            draw_node(box, label, appear_t, (YELLOW, GREEN)[index % 2], 17)

    @staticmethod
    def _draw_code(draw: ImageDraw.ImageDraw, data_or_scene: Any, progress: float) -> None:
        data = data_or_scene.visual_data if isinstance(data_or_scene, Scene) else data_or_scene
        x0, y0, x1, y1 = 142, 274, 1138, 520
        panel_t = _ease_out_cubic(_seg(progress, 0.0, 0.1))
        slide = _slide(panel_t, 20)
        panel_y, panel_bottom = y0 + slide, y1 + slide
        draw.rounded_rectangle((x0, panel_y, x1, panel_bottom), radius=15, fill=(17, 16, 23), outline=(68, 59, 82), width=2)
        code = data.get("code", "for i in range(3):\n    print(i)").splitlines()
        revealed = _reveal_lines(code[:4], _seg(progress, 0.05, 0.38))
        # Line slots are dynamic: legacy snippets may hold up to four lines.
        line_y = {index: panel_y + 44 + (index - 1) * 38 for index in range(1, 5)}
        highlight_t = _ease_in_out(_seg(progress, 0.5, 0.62))
        if highlight_t > 0.02:
            highlight_y = _lerp(line_y[1], line_y[2], highlight_t) - 7
            _glow_box(draw, (x0 + 20, highlight_y, x1 - 20, highlight_y + 48), radius=8, color=(64, 94, 138), strength=0.6)
            draw.rounded_rectangle((x0 + 20, highlight_y, x1 - 20, highlight_y + 48), radius=8, fill=(51, 40, 69))
        for i, line in enumerate(code[:4], start=1):
            shown = revealed[i - 1] if i - 1 < len(revealed) else ""
            if shown:
                draw.text((x0 + 50, line_y[i]), shown, font=_mono_font(30), fill=BLUE if i == 1 else GREEN)
        draw.text((x0 + 54, panel_bottom - 52), "OUTPUT", font=_font(12, True), fill=YELLOW)
        output = data.get("output", "0  1  2").split()
        shown_count = max(1, min(len(output), int(progress * len(output)) + 1))
        out_x = x0 + 180
        for index, token in enumerate(output[:shown_count]):
            token_t = _seg(progress, 0.55 + index * 0.09, 0.64 + index * 0.09)
            if token_t <= 0.01:
                out_x += 88
                continue
            box = _shrink_box((out_x, panel_bottom - 61, out_x + 74, panel_bottom - 28), _pop_scale(token_t))
            draw.rounded_rectangle(box, radius=9, fill=(37, 51, 44), outline=_mix((21, 80, 60), GREEN, token_t * 0.6), width=1)
            _draw_centered(draw, box, token, _font(16, True), GREEN)
            out_x += 88

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
        left_t = _ease_out_cubic(_seg(progress, 0.0, 0.1))
        right_t = _ease_out_cubic(_seg(progress, 0.02, 0.12))
        left_box = (left[0] + _slide(left_t, 50), left[1], left[2], left[3])
        right_box = (right[0] - _slide(right_t, 50), right[1], right[2], right[3])
        _glow_box(draw, left_box, radius=13, color=(30, 68, 111), strength=0.25)
        _glow_box(draw, right_box, radius=13, color=(30, 68, 111), strength=0.25)
        draw.rounded_rectangle(left_box, radius=13, fill=(4, 12, 25), outline=(30, 68, 111), width=2)
        draw.rounded_rectangle(right_box, radius=13, fill=(8, 27, 52), outline=(30, 68, 111), width=2)
        draw.text((left_box[0] + 22, left_box[1] + 15), "PYTHON  /  DISPLAY ONLY", font=_font(11, True), fill=CYAN)

        lines = [f"for {data.variable_name} in {data.iterable_name}:", f"    print({data.variable_name})"]
        revealed = _reveal_lines(lines, _seg(progress, 0.08, 0.30))
        for line_number, line in enumerate(lines, start=1):
            y = left_box[1] + 65 + (line_number - 1) * 62
            shown = revealed[line_number - 1] if line_number - 1 < len(revealed) else ""
            is_active = line_number == int(state.get("active_line", 1))
            if is_active and progress > 0.12:
                strength = 0.35 + 0.4 * _pulse(progress, 1.5)
                _glow_box(draw, (left_box[0] + 14, y - 8, left_box[2] - 16, y + 43), radius=7, color=(28, 91, 146), strength=strength)
                draw.rounded_rectangle((left_box[0] + 14, y - 8, left_box[2] - 16, y + 43), radius=7, fill=(13, 47, 84))
            if shown:
                draw.text((left_box[0] + 36, y), shown, font=_mono_font(24), fill=CYAN if line_number == 1 else GREEN)

        rx, ry = right_box[0] + 26, right_box[1] + 15
        draw.text((rx, ry), data.iterable_name.upper(), font=_font(11, True), fill=MUTED)
        chips_y = ry + 28
        chip_w, chip_h, chip_gap = 118, 34, 18
        iteration = int(state.get("iteration", 0))
        for index, value in enumerate(data.values):
            chip_x = rx + index * (chip_w + chip_gap)
            chip_t = _seg(progress, 0.14 + index * 0.05, 0.24 + index * 0.05)
            if chip_t <= 0.01:
                continue
            chip_box = _shrink_box((chip_x, chips_y, chip_x + chip_w, chips_y + chip_h), _pop_scale(chip_t, 0.7))
            is_current = index == iteration and state.get("phase") != "complete"
            border = (GREEN, CYAN, YELLOW)[index % 3]
            if is_current:
                _glow_box(draw, chip_box, radius=9, color=GREEN, strength=0.5 + 0.5 * _pulse(progress, 2.0))
                draw.rounded_rectangle(chip_box, radius=9, fill=(12, 62, 48), outline=GREEN, width=2)
            else:
                draw.rounded_rectangle(chip_box, radius=9, fill=(14, 38, 62), outline=_appear(border, chip_t, base=(24, 48, 76)), width=1)
            _draw_centered(draw, chip_box, value, _font(14, True), WHITE if is_current else MUTED)

        divider_y = chips_y + chip_h + 16
        draw.line((rx, divider_y, right_box[2] - 26, divider_y), fill=(28, 60, 96), width=1)
        metrics_y = divider_y + 12
        draw.text((rx, metrics_y), "ITERATION", font=_font(10, True), fill=MUTED)
        draw.text(
            (rx, metrics_y + 21),
            f"{iteration} / {len(data.values)}",
            font=_font(25, True),
            fill=BLUE if state.get("phase") != "complete" else GREEN,
        )
        draw.text((rx + 173, metrics_y), data.variable_name, font=_font(10, True), fill=MUTED)
        value = state.get("value")
        value_text = f'= "{value}"' if value is not None else "= —"
        draw.text((rx + 173, metrics_y + 21), value_text, font=_mono_font(18), fill=YELLOW)
        out_label_y = metrics_y + 63
        draw.text((rx, out_label_y), f"OUTPUT  /  print({data.variable_name})", font=_font(10, True), fill=MUTED)
        output = state.get("output", [])
        chip_y = out_label_y + 24
        for index, item in enumerate(output[-4:]):
            born_at = 0.2 + (len(output) - len(output[-4:]) + index) * (0.5 / max(1, len(data.values)))
            pop_t = _seg(progress, born_at, born_at + 0.06)
            if pop_t <= 0.01:
                continue
            box = _shrink_box((rx + index * 102, chip_y, rx + index * 102 + 91, chip_y + 36), _pop_scale(pop_t))
            draw.rounded_rectangle(box, radius=8, fill=(10, 54, 55), outline=_mix((21, 115, 112), GREEN, _pulse(progress, 2.0) * 0.4), width=1)
            _draw_centered(draw, box, str(item), _font(14, True), GREEN)
        if not output:
            draw.text((rx, chip_y + 5), _typewriter("nothing printed yet", _seg(progress, 0.3, 0.5)), font=_font(13), fill=(117, 145, 171))

        status = str(state.get("status", "Ready to begin"))
        if len(status) > 60:
            status = status[:57] + "..."
        complete = state.get("phase") == "complete"
        bar_color = GREEN if complete else CYAN
        bar_t = _seg(progress, 0.05, 0.2)
        draw.rounded_rectangle((90, 536, 1190, 552), radius=7, fill=_appear((12, 41, 70), bar_t, base=BG))
        _draw_script_aware(
            draw,
            (104, 535),
            _typewriter(status, _seg(progress, 0.1, 0.3)),
            _font_for_text(status, 12, True),
            _appear(bar_color, bar_t, base=BG),
            bold=True,
        )
