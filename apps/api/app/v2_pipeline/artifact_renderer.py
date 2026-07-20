"""Channel-specific result artifacts for the v2 test pipeline only."""
from __future__ import annotations

import base64
import json
from io import BytesIO
from pathlib import Path



def channel_text(copy: dict, channel: str) -> str:
    """Select existing generated copy; never rewrite it."""
    recommendation = copy.get("channel_recommendation", {})
    if channel == "instagram":
        return str(recommendation.get("overlay_headline") or recommendation.get("publish_title") or "")
    return str(recommendation.get("blog_title") or recommendation.get("publish_title") or "")


def _overlay_font(size: int):
    """Pick a Korean-capable font when the host provides one.

    This is output rendering only; it does not alter generated copy or any
    prompt value.  Malgun is available on many Windows hosts, while Nanum is
    the common equivalent on Colab/Linux.
    """
    from PIL import ImageFont

    candidates = (
        "malgun.ttf",
        "C:/Windows/Fonts/malgun.ttf",
        "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    )
    for candidate in candidates:
        try:
            return ImageFont.truetype(candidate, size)
        except OSError:
            continue
    return ImageFont.load_default()


def save_channel_artifacts(output_dir: Path, image_id: str, channel: str, copy: dict,
                           image_base64: str, media_type: str) -> dict[str, str]:
    """Persist raw generated image, generated copy, and a text-overlay image."""
    try:
        from PIL import Image, ImageDraw
    except ImportError as exc:
        raise RuntimeError(
            "Pillow is required to save the generated image with text. "
            "Install it in the API virtual environment before a real run."
        ) from exc
    root = output_dir / "artifacts" / channel / image_id
    root.mkdir(parents=True, exist_ok=True)
    suffix = ".png" if media_type == "image/png" else ".webp" if media_type == "image/webp" else ".jpg"
    raw_path = root / f"generated{suffix}"
    raw_path.write_bytes(base64.b64decode(image_base64))
    copy_path = root / "ad_copy.json"
    copy_path.write_text(json.dumps(copy, ensure_ascii=False, indent=2), encoding="utf-8")
    text = channel_text(copy, channel)
    overlay_path = root / "generated_with_text.png"
    image = Image.open(BytesIO(raw_path.read_bytes())).convert("RGBA")
    canvas = Image.new("RGBA", image.size, (0, 0, 0, 0))
    if text:
        draw = ImageDraw.Draw(canvas)
        font = _overlay_font(max(28, image.width // 20))
        box = draw.textbbox((0, 0), text, font=font)
        padding = max(20, image.width // 50)
        draw.rounded_rectangle((padding, padding, min(image.width-padding, box[2]+padding*2), box[3]+padding*2), radius=12, fill=(0,0,0,150))
        draw.text((padding*2, padding*2), text, font=font, fill="white")
    Image.alpha_composite(image, canvas).convert("RGB").save(overlay_path, "PNG")
    return {"raw_image": str(raw_path), "ad_copy": str(copy_path), "image_with_text": str(overlay_path)}
