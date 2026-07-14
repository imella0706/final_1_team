from __future__ import annotations

import math
import os
import unicodedata
from pathlib import Path
from typing import Any

from .models import Storyboard


PALETTE = {
    "ink": "#171717",
    "paper": "#F4F4F1",
    "yellow": "#FFD84D",
    "coral": "#FF6B5E",
    "teal": "#39C6B1",
    "violet": "#6557D9",
    "white": "#FFFFFF",
    "muted": "#A5A5A5",
}


def _display_text(value: str) -> str:
    """Drop emoji/symbol glyphs that commonly render as empty boxes in CJK fonts."""

    return "".join(
        character
        for character in value
        if character.isspace()
        or unicodedata.category(character)[0] in {"L", "N", "P", "Z"}
    ).strip()


def _font_candidates(bold: bool) -> list[Path]:
    configured = os.getenv("TREND_DEMO_FONT")
    candidates = [Path(configured)] if configured else []
    candidates.extend(
        [
            Path("C:/Windows/Fonts/malgunbd.ttf" if bold else "C:/Windows/Fonts/malgun.ttf"),
            Path("C:/Windows/Fonts/NotoSansKR-VF.ttf"),
            Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc" if bold else "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
            Path("/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf" if bold else "/usr/share/fonts/truetype/nanum/NanumGothic.ttf"),
        ]
    )
    return candidates


def _font(size: int, *, bold: bool = False) -> Any:
    from PIL import ImageFont

    for path in _font_candidates(bold):
        if path.exists():
            return ImageFont.truetype(str(path), size=size)
    return ImageFont.load_default(size=size)


def _ease_out(value: float) -> float:
    value = min(max(value, 0.0), 1.0)
    return 1.0 - (1.0 - value) ** 3


def _pulse(value: float) -> float:
    return 1.0 + math.sin(value * math.pi * 4.0) * 0.025 * (1.0 - value)


def _fit_lines(draw: Any, text: str, font: Any, max_width: int) -> list[str]:
    output: list[str] = []
    for paragraph in text.splitlines() or [""]:
        words = paragraph.split()
        if not words:
            output.append("")
            continue
        current = ""
        for word in words:
            candidate = f"{current} {word}".strip()
            if draw.textbbox((0, 0), candidate, font=font)[2] <= max_width:
                current = candidate
                continue
            if current:
                output.append(current)
                current = ""
            fragment = ""
            for character in word:
                candidate = fragment + character
                if fragment and draw.textbbox((0, 0), candidate, font=font)[2] > max_width:
                    output.append(fragment)
                    fragment = character
                else:
                    fragment = candidate
            current = fragment
        if current:
            output.append(current)
    return output


def _center_text(
    draw: Any,
    text: str,
    *,
    font: Any,
    center_x: int,
    top: int,
    max_width: int,
    fill: str,
    spacing: int,
) -> int:
    lines = _fit_lines(draw, text, font, max_width)
    y = top
    for line in lines:
        box = draw.textbbox((0, 0), line, font=font)
        width = box[2] - box[0]
        height = box[3] - box[1]
        draw.text((center_x - width / 2, y), line, font=font, fill=fill)
        y += height + spacing
    return y


def _draw_product(draw: Any, *, x: int, y: int, size: int, product: str) -> None:
    cup_width = int(size * 0.62)
    left = x - cup_width // 2
    top = y - size // 2
    draw.rounded_rectangle(
        (left, top + int(size * 0.16), left + cup_width, top + size),
        radius=max(int(size * 0.08), 2),
        fill=PALETTE["paper"],
        outline=PALETTE["ink"],
        width=max(size // 45, 2),
    )
    draw.rounded_rectangle(
        (left - int(size * 0.04), top + int(size * 0.12), left + cup_width + int(size * 0.04), top + int(size * 0.25)),
        radius=max(int(size * 0.05), 2),
        fill=PALETTE["yellow"],
        outline=PALETTE["ink"],
        width=max(size // 55, 2),
    )
    label_font = _font(max(size // 13, 10), bold=True)
    label = _display_text(product)[:12]
    box = draw.textbbox((0, 0), label, font=label_font)
    draw.text(
        (x - (box[2] - box[0]) / 2, top + int(size * 0.52)),
        label,
        font=label_font,
        fill=PALETTE["ink"],
    )


def _render_frame(storyboard: Storyboard, time_seconds: float, width: int, height: int) -> Any:
    from PIL import Image, ImageDraw

    scale = width / 540.0
    scene_index = next(
        (
            index
            for index, scene in enumerate(storyboard.scenes)
            if scene.start <= time_seconds < scene.end
        ),
        len(storyboard.scenes) - 1,
    )
    scene = storyboard.scenes[scene_index]
    progress = (time_seconds - scene.start) / max(scene.end - scene.start, 0.001)
    entrance = _ease_out(min(progress / 0.28, 1.0))
    backgrounds = ["ink", "paper", "teal", "violet"]
    foregrounds = ["white", "ink", "ink", "white"]
    image = Image.new("RGB", (width, height), PALETTE[backgrounds[scene_index]])
    draw = ImageDraw.Draw(image)

    margin = int(34 * scale)
    small = _font(max(int(16 * scale), 11), bold=True)
    body = _font(max(int(22 * scale), 13))
    title = _font(max(int(43 * scale), 20), bold=True)
    foreground = PALETTE[foregrounds[scene_index]]
    muted = PALETTE["muted"] if scene_index in {0, 3} else "#575757"

    draw.text((margin, int(35 * scale)), "TREND → AD  /  LOCAL DATA DEMO", font=small, fill=muted)
    bar_y = height - int(42 * scale)
    draw.rounded_rectangle(
        (margin, bar_y, width - margin, bar_y + max(int(5 * scale), 3)),
        radius=3,
        fill="#555555" if scene_index in {0, 3} else "#C8C8C8",
    )
    draw.rounded_rectangle(
        (
            margin,
            bar_y,
            margin + int((width - 2 * margin) * time_seconds / storyboard.duration_seconds),
            bar_y + max(int(5 * scale), 3),
        ),
        radius=3,
        fill=PALETTE["yellow"],
    )

    if scene_index == 0:
        accent_size = int(135 * scale * _pulse(progress))
        draw.ellipse(
            (
                width // 2 - accent_size // 2,
                int(170 * scale) - accent_size // 2,
                width // 2 + accent_size // 2,
                int(170 * scale) + accent_size // 2,
            ),
            fill=PALETTE["yellow"],
        )
        draw.text(
            (width // 2, int(170 * scale)),
            "01",
            anchor="mm",
            font=_font(max(int(32 * scale), 16), bold=True),
            fill=PALETTE["ink"],
        )
        y = int((390 - 45 * (1 - entrance)) * scale)
        _center_text(draw, _display_text(scene.on_screen_text), font=title, center_x=width // 2, top=y, max_width=width - 2 * margin, fill=foreground, spacing=int(14 * scale))
        _center_text(draw, "CSV에서 찾은 밈 후보", font=body, center_x=width // 2, top=int(590 * scale), max_width=width - 2 * margin, fill=muted, spacing=int(8 * scale))

    elif scene_index == 1:
        card_x = int((-70 + 104 * entrance) * scale)
        card_y = int(175 * scale)
        card_right = width - margin
        card_bottom = int(680 * scale)
        draw.rounded_rectangle(
            (card_x, card_y, card_right, card_bottom),
            radius=max(int(8 * scale), 4),
            fill=PALETTE["white"],
            outline=PALETTE["ink"],
            width=max(int(3 * scale), 2),
        )
        draw.rounded_rectangle(
            (card_x + int(28 * scale), card_y + int(30 * scale), card_x + int(165 * scale), card_y + int(72 * scale)),
            radius=max(int(8 * scale), 4),
            fill=PALETTE["coral"],
        )
        draw.text((card_x + int(44 * scale), card_y + int(39 * scale)), storyboard.trend.source.upper(), font=small, fill=PALETTE["ink"])
        _center_text(draw, _display_text(storyboard.trend.title), font=title, center_x=(card_x + card_right) // 2, top=card_y + int(145 * scale), max_width=card_right - card_x - int(70 * scale), fill=PALETTE["ink"], spacing=int(12 * scale))
        context = storyboard.trend.summary or storyboard.trend.context or "최신 로컬 스냅샷에서 선택"
        _center_text(draw, context[:90], font=body, center_x=(card_x + card_right) // 2, top=card_y + int(350 * scale), max_width=card_right - card_x - int(70 * scale), fill="#5D5D5D", spacing=int(9 * scale))
        draw.text((margin, int(745 * scale)), "검색 → 점수화 → 선택", font=body, fill=foreground)

    elif scene_index == 2:
        product_scale = 0.78 + 0.22 * entrance
        center_y = int(345 * scale)
        draw.ellipse(
            (
                width // 2 - int(150 * scale),
                center_y - int(150 * scale),
                width // 2 + int(150 * scale),
                center_y + int(150 * scale),
            ),
            fill=PALETTE["coral"],
            outline=PALETTE["ink"],
            width=max(int(3 * scale), 2),
        )
        _draw_product(
            draw,
            x=width // 2,
            y=center_y,
            size=int(230 * scale * product_scale),
            product=storyboard.product,
        )
        _center_text(draw, _display_text(storyboard.product), font=title, center_x=width // 2, top=int(570 * scale), max_width=width - 2 * margin, fill=foreground, spacing=int(12 * scale))
        _center_text(draw, _display_text(storyboard.audience), font=body, center_x=width // 2, top=int(720 * scale), max_width=width - 2 * margin, fill="#24463F", spacing=int(8 * scale))

    else:
        y = int((270 - 40 * (1 - entrance)) * scale)
        draw.rounded_rectangle(
            (margin, int(160 * scale), width - margin, int(720 * scale)),
            radius=max(int(8 * scale), 4),
            fill=PALETTE["paper"],
        )
        _center_text(draw, _display_text(storyboard.cta), font=title, center_x=width // 2, top=y, max_width=width - int(120 * scale), fill=PALETTE["ink"], spacing=int(12 * scale))
        _center_text(draw, _display_text(storyboard.product), font=body, center_x=width // 2, top=int(500 * scale), max_width=width - int(120 * scale), fill="#555555", spacing=int(8 * scale))
        draw.rounded_rectangle(
            (int(145 * scale), int(610 * scale), width - int(145 * scale), int(665 * scale)),
            radius=max(int(8 * scale), 4),
            fill=PALETTE["yellow"],
            outline=PALETTE["ink"],
            width=max(int(2 * scale), 1),
        )
        draw.text((width // 2, int(637 * scale)), "CTA", anchor="mm", font=small, fill=PALETTE["ink"])

    draw.text(
        (margin, height - int(78 * scale)),
        f"{scene_index + 1:02d} / {len(storyboard.scenes):02d}   {scene.role.upper()}",
        font=small,
        fill=muted,
    )
    return image


def render_animatic(
    storyboard: Storyboard,
    output_path: Path,
    *,
    width: int = 540,
    height: int = 960,
    fps: int = 24,
    gif_path: Path | None = None,
    codec: str = "mp4v",
) -> dict[str, int | float | str]:
    try:
        import cv2
        import numpy as np
        from PIL import Image
    except ImportError as exc:
        raise RuntimeError(
            "Video rendering requires Pillow, NumPy, and OpenCV. "
            "Install demo/requirements.txt or use --prompt-only."
        ) from exc

    if width <= 0 or height <= 0 or fps <= 0:
        raise ValueError("width, height, and fps must be positive")
    if len(codec) != 4:
        raise ValueError("codec must be a four-character code")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    writer = cv2.VideoWriter(
        str(output_path),
        cv2.VideoWriter_fourcc(*codec),
        float(fps),
        (width, height),
    )
    if not writer.isOpened():
        raise RuntimeError(f"OpenCV could not open video writer with codec {codec!r}")

    frame_count = int(math.ceil(storyboard.duration_seconds * fps))
    gif_frames: list[Any] = []
    gif_step = max(int(round(fps / 8)), 1)
    try:
        for frame_index in range(frame_count):
            time_seconds = frame_index / fps
            frame = _render_frame(storyboard, time_seconds, width, height)
            writer.write(cv2.cvtColor(np.asarray(frame), cv2.COLOR_RGB2BGR))
            if gif_path is not None and frame_index % gif_step == 0:
                gif_frames.append(
                    frame.resize((max(width // 2, 1), max(height // 2, 1)), Image.Resampling.LANCZOS)
                )
    finally:
        writer.release()

    if not output_path.exists() or output_path.stat().st_size == 0:
        raise RuntimeError("Video writer completed without a playable output file")

    if gif_path is not None and gif_frames:
        gif_path.parent.mkdir(parents=True, exist_ok=True)
        gif_frames[0].save(
            gif_path,
            save_all=True,
            append_images=gif_frames[1:],
            duration=int(1000 * gif_step / fps),
            loop=0,
            disposal=2,
        )

    return {
        "path": str(output_path),
        "width": width,
        "height": height,
        "fps": fps,
        "frames": frame_count,
        "duration_seconds": storyboard.duration_seconds,
        "codec": codec,
    }


def extract_frame(video_path: Path, image_path: Path, *, frame_index: int = 0) -> None:
    import cv2

    capture = cv2.VideoCapture(str(video_path))
    try:
        capture.set(cv2.CAP_PROP_POS_FRAMES, max(frame_index, 0))
        ok, frame = capture.read()
        if not ok:
            raise RuntimeError(f"Could not read frame {frame_index} from {video_path}")
        image_path.parent.mkdir(parents=True, exist_ok=True)
        if not cv2.imwrite(str(image_path), frame):
            raise RuntimeError(f"Could not write preview frame to {image_path}")
    finally:
        capture.release()
