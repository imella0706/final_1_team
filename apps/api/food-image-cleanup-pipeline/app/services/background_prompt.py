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
    generated_plate = bool(metadata.get("generated_plate", False))
    supplied_prompt = str(
        metadata.get("background_prompt_base", metadata.get("background_prompt", ""))
    ).strip()
    # A frontal interior cannot be a physically plausible support surface for a
    # top-down dish.  Keep the business mood only as a material choice and make
    # the geometry unambiguous for the generator.
    if angle_label == "top":
        return BackgroundPrompt(
            prompt=_topdown_table_prompt(metadata, generated_plate=generated_plate),
            placement=placement,
            light_direction=str(metadata.get("light_direction", "left")),
            camera_angle=angle_label,
        )
    if supplied_prompt:
        # 기존 업종 프롬프트에는 "no plate"가 포함될 수 있다. 생성 접시 모드에서는
        # 해당 부정 조건을 제거하지 않으면 같은 프롬프트 안에서 접시 생성과 제거를
        # 동시에 요구하게 되어 후보 품질이 크게 흔들린다.
        if generated_plate:
            supplied_prompt = _allow_generated_plate(supplied_prompt)
        return BackgroundPrompt(
            prompt=_apply_camera_angle_constraint(
                f"{supplied_prompt.rstrip(', ')}, {_plate_constraint(generated_plate)}",
                angle_label,
            ),
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
        f"commercial food photography background, {_plate_constraint(generated_plate)}, "
        "no bowl, no cup, no utensils, no people, no text, no logo, no watermark"
    )
    return BackgroundPrompt(
        prompt=_apply_camera_angle_constraint(prompt, angle_label),
        placement=placement,
        light_direction=light,
        camera_angle=angle_label,
    )


def _topdown_table_prompt(metadata: dict[str, Any], *, generated_plate: bool) -> str:
    business = str(metadata.get("business_type", "cafe")).replace("_", " ")
    mood = str(metadata.get("desired_mood", "warm natural"))
    light = str(metadata.get("light_direction", "left"))
    return (
        f"Photorealistic premium {business} advertising tabletop, "
        "strict overhead top-down food photography, camera directly above the table at 90 degrees, "
        "a single continuous matte natural wooden table surface filling the entire frame, "
        f"soft diffuse daylight from the {light}, {mood} mood, subtle realistic wood grain, "
        f"{_plate_constraint(generated_plate)}, "
        "no food, no bowl, no cup, no glass, no utensils, no napkin, "
        "no decoration, no plant, no people, no text, no logo, no watermark, "
        "no horizon, no wall, no window, no chair, no interior, no side view, no eye-level view"
    )


def _plate_constraint(generated_plate: bool) -> str:
    if generated_plate:
        return (
            "one empty round white ceramic dinner plate centered on the table, "
            "fully visible with a clean intact rim, large enough to hold one dish"
        )
    return "empty table, no plate"


def _allow_generated_plate(prompt: str) -> str:
    """생성 접시 모드와 충돌하는 사용자 프롬프트의 접시 금지 문구만 제거한다."""
    cleaned = prompt
    for phrase in (
        "no plate,",
        "no plate",
        "no plates,",
        "no plates",
    ):
        cleaned = cleaned.replace(phrase, "")
    return cleaned


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
