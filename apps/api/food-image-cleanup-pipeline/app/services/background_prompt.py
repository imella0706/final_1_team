from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class BackgroundPrompt:
    prompt: str
    placement: str
    light_direction: str


def build_background_prompt(metadata: dict[str, Any]) -> BackgroundPrompt:
    """Build a constrained, food-free commercial-background prompt for FLUX."""
    supplied_prompt = str(metadata.get("background_prompt", "")).strip()
    if supplied_prompt:
        return BackgroundPrompt(
            prompt=supplied_prompt,
            placement=str(metadata.get("foreground_position", "center_lower")),
            light_direction=str(metadata.get("light_direction", "left")),
        )
    business = str(metadata.get("business_type", "modern cafe"))
    category = str(metadata.get("food_category", "food"))
    angle = str(metadata.get("camera_angle", "45-degree"))
    mood = str(metadata.get("desired_mood", "warm natural"))
    light = str(metadata.get("light_direction", "left"))
    placement = str(metadata.get("foreground_position", "center_lower"))
    colors = ", ".join(str(value).replace("_", " ") for value in metadata.get("food_color", []))
    complement = f"palette complementing {colors}," if colors else "balanced neutral palette,"
    prompt = (
        f"Photorealistic {business} interior for {category} advertising, "
        f"clean table aligned for a {angle} food photograph, "
        f"soft diffused light from the {light}, {mood} mood, {complement} "
        f"clear empty placement area in the {placement.replace('_', ' ')}, "
        "commercial food photography background, empty table, no food, no plate, "
        "no bowl, no cup, no utensils, no people, no text, no logo, no watermark"
    )
    return BackgroundPrompt(prompt=prompt, placement=placement, light_direction=light)
