from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class BackgroundPrompt:
    prompt: str
    placement: str
    light_direction: str
    camera_angle: str


def build_background_prompt(metadata: dict[str, Any]) -> BackgroundPrompt:
    """Build a constrained, food-free commercial-background prompt for FLUX."""
    angle_label = str(metadata.get("camera_angle_label", "45")).strip().lower()
    if angle_label not in {"top", "45"}:
        angle_label = "45"
    placement = "center" if angle_label == "top" else "center_lower"
    supplied_prompt = str(
        metadata.get("background_prompt_base", metadata.get("background_prompt", ""))
    ).strip()
    if supplied_prompt:
        return BackgroundPrompt(
            prompt=_apply_camera_angle_constraint(supplied_prompt, angle_label),
            placement=placement,
            light_direction=str(metadata.get("light_direction", "left")),
            camera_angle=angle_label,
        )
    business = str(metadata.get("business_type", "modern cafe"))
    category = str(metadata.get("food_category", "food"))
    mood = str(metadata.get("desired_mood", "warm natural"))
    light = str(metadata.get("light_direction", "left"))
    colors = ", ".join(str(value).replace("_", " ") for value in metadata.get("food_color", []))
    complement = f"palette complementing {colors}," if colors else "balanced neutral palette,"
    prompt = (
        f"Photorealistic {business} interior for {category} advertising, "
        "clean empty table surface, "
        f"soft diffused light from the {light}, {mood} mood, {complement} "
        f"clear empty placement area in the {placement.replace('_', ' ')}, "
        "commercial food photography background, empty table, no food, no plate, "
        "no bowl, no cup, no utensils, no people, no text, no logo, no watermark"
    )
    return BackgroundPrompt(
        prompt=_apply_camera_angle_constraint(prompt, angle_label),
        placement=placement,
        light_direction=light,
        camera_angle=angle_label,
    )


def _apply_camera_angle_constraint(base_prompt: str, angle_label: str) -> str:
    """업종 프롬프트의 분위기는 보존하면서 카메라 기하를 단일 시점으로 고정한다."""

    cleaned = base_prompt
    for phrase in (
        "eye-level commercial food photography composition,",
        "eye-level commercial food photography composition",
        "eye-level camera angle,",
        "eye-level camera angle",
    ):
        cleaned = cleaned.replace(phrase, "")
    if angle_label == "top":
        geometry = (
            "strict overhead top-down food photography, camera directly above the table at 90 degrees, "
            "flat tabletop filling the whole frame, centered empty placement area, "
            "no horizon, no wall, no window, no chair, no side view, no eye-level view"
        )
    else:
        geometry = (
            "elevated 45-degree food photography, camera angled down toward the table, "
            "visible tabletop in the lower foreground and softly blurred interior in the background, "
            "empty placement area in the center lower, no overhead top-down view"
        )
    return f"{cleaned.rstrip(', ')}, {geometry}"
