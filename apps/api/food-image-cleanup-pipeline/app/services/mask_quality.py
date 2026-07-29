from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import cv2
import numpy as np


@dataclass(frozen=True, slots=True)
class MaskQualityResult:
    passed: bool
    confidence: float
    reasons: tuple[str, ...]
    metrics: dict[str, float | int | bool | str]


def _binary(mask: np.ndarray) -> np.ndarray:
    if mask.ndim != 2:
        raise ValueError("mask must be single-channel")
    return np.where(mask >= 128, 255, 0).astype(np.uint8)


def _component_metrics(mask: np.ndarray) -> tuple[int, float]:
    count, _, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    if count <= 1:
        return 0, 0.0
    areas = stats[1:, cv2.CC_STAT_AREA].astype(np.float64)
    total = float(areas.sum())
    return int(len(areas)), float(areas.max() / max(total, 1.0))


def _internal_hole_ratio(mask: np.ndarray) -> float:
    padded = cv2.copyMakeBorder(mask, 1, 1, 1, 1, cv2.BORDER_CONSTANT, value=0)
    background = np.where(padded == 0, 255, 0).astype(np.uint8)
    cv2.floodFill(background, None, (0, 0), 0)
    holes = background[1:-1, 1:-1]
    return float(np.count_nonzero(holes) / max(np.count_nonzero(mask), 1))


def _border_touch_ratio(mask: np.ndarray, width: int) -> float:
    width = max(1, min(int(width), min(mask.shape) // 4))
    border = np.zeros_like(mask)
    border[:width, :] = 255
    border[-width:, :] = 255
    border[:, :width] = 255
    border[:, -width:] = 255
    return float(
        np.count_nonzero(cv2.bitwise_and(mask, border))
        / max(np.count_nonzero(mask), 1)
    )


def _solidity(mask: np.ndarray) -> float:
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return 0.0
    contour = max(contours, key=cv2.contourArea)
    hull = cv2.convexHull(contour)
    return float(cv2.contourArea(contour) / max(cv2.contourArea(hull), 1.0))


def _bounded_score(value: float, minimum: float, maximum: float) -> float:
    if minimum <= value <= maximum:
        return 1.0
    if value < minimum:
        return max(0.0, value / max(minimum, 1e-6))
    return max(0.0, maximum / max(value, 1e-6))


def assess_food_mask_quality(
    food_mask: np.ndarray,
    *,
    plate_mask: np.ndarray | None = None,
    config: dict[str, Any] | None = None,
) -> MaskQualityResult:
    config = config or {}
    food = _binary(food_mask)
    height, width = food.shape
    pixels = int(np.count_nonzero(food))
    area_ratio = pixels / max(height * width, 1)
    component_count, largest_component_ratio = _component_metrics(food)
    border_touch_ratio = _border_touch_ratio(
        food, int(config.get("border_width", 3))
    )
    minimum_area_ratio = float(config.get("minimum_area_ratio", 0.002))
    maximum_area_ratio = float(config.get("maximum_area_ratio", 0.70))
    minimum_largest_ratio = float(
        config.get("minimum_largest_component_ratio", 0.18)
    )
    maximum_border_touch_ratio = float(
        config.get("maximum_border_touch_ratio", 0.20)
    )

    overlap_ratio = 1.0
    if plate_mask is not None and plate_mask.shape == food.shape and np.any(plate_mask):
        plate = _binary(plate_mask)
        overlap_ratio = float(
            np.count_nonzero((food > 0) & (plate > 0)) / max(pixels, 1)
        )
    minimum_plate_overlap_ratio = float(
        config.get("minimum_plate_overlap_ratio", 0.10)
    )

    reasons: list[str] = []
    if pixels == 0:
        reasons.append("empty_food_mask")
    if not minimum_area_ratio <= area_ratio <= maximum_area_ratio:
        reasons.append("food_area_ratio_out_of_range")
    if largest_component_ratio < minimum_largest_ratio:
        reasons.append("food_mask_too_fragmented")
    if border_touch_ratio > maximum_border_touch_ratio:
        reasons.append("food_mask_touches_image_border")
    if overlap_ratio < minimum_plate_overlap_ratio:
        reasons.append("food_plate_overlap_too_low")

    confidence = float(
        np.mean(
            [
                _bounded_score(area_ratio, minimum_area_ratio, maximum_area_ratio),
                min(1.0, largest_component_ratio / max(minimum_largest_ratio, 1e-6)),
                max(
                    0.0,
                    1.0
                    - border_touch_ratio
                    / max(maximum_border_touch_ratio, 1e-6),
                ),
                min(1.0, overlap_ratio / max(minimum_plate_overlap_ratio, 1e-6)),
            ]
        )
    )
    minimum_confidence = float(config.get("minimum_confidence", 0.55))
    passed = pixels > 0 and not reasons and confidence >= minimum_confidence
    metrics: dict[str, float | int | bool | str] = {
        "passed": bool(passed),
        "confidence": round(confidence, 6),
        "pixels": pixels,
        "area_ratio": round(area_ratio, 6),
        "component_count": component_count,
        "largest_component_ratio": round(largest_component_ratio, 6),
        "border_touch_ratio": round(border_touch_ratio, 6),
        "plate_overlap_ratio": round(overlap_ratio, 6),
        "minimum_confidence": minimum_confidence,
    }
    return MaskQualityResult(passed, confidence, tuple(reasons), metrics)


def assess_plate_mask_quality(
    plate_mask: np.ndarray,
    *,
    source_mask: np.ndarray | None = None,
    shape_type: str = "unknown",
    shape_confidence: float = 0.0,
    config: dict[str, Any] | None = None,
) -> MaskQualityResult:
    config = config or {}
    plate = _binary(plate_mask)
    height, width = plate.shape
    pixels = int(np.count_nonzero(plate))
    area_ratio = pixels / max(height * width, 1)
    component_count, largest_component_ratio = _component_metrics(plate)
    border_touch_ratio = _border_touch_ratio(
        plate, int(config.get("border_width", 3))
    )
    hole_ratio = _internal_hole_ratio(plate)
    solidity = _solidity(plate)

    source_pixels = 0
    expansion_ratio = 1.0
    if source_mask is not None and source_mask.shape == plate.shape:
        source = _binary(source_mask)
        source_pixels = int(np.count_nonzero(source))
        expansion_ratio = pixels / max(source_pixels, 1)

    minimum_area_ratio = float(config.get("minimum_area_ratio", 0.03))
    maximum_area_ratio = float(config.get("maximum_area_ratio", 0.85))
    minimum_largest_ratio = float(
        config.get("minimum_largest_component_ratio", 0.90)
    )
    maximum_border_touch_ratio = float(
        config.get("maximum_border_touch_ratio", 0.12)
    )
    maximum_hole_ratio = float(config.get("maximum_hole_ratio", 0.03))
    minimum_solidity = float(config.get("minimum_solidity", 0.60))
    maximum_expansion_ratio = float(config.get("maximum_expansion_ratio", 1.40))

    reasons: list[str] = []
    if pixels == 0:
        reasons.append("empty_plate_mask")
    if not minimum_area_ratio <= area_ratio <= maximum_area_ratio:
        reasons.append("plate_area_ratio_out_of_range")
    if largest_component_ratio < minimum_largest_ratio:
        reasons.append("plate_mask_fragmented")
    if border_touch_ratio > maximum_border_touch_ratio:
        reasons.append("plate_mask_touches_image_border")
    if hole_ratio > maximum_hole_ratio:
        reasons.append("plate_mask_has_internal_holes")
    if solidity < minimum_solidity:
        reasons.append("plate_mask_low_solidity")
    if source_pixels and expansion_ratio > maximum_expansion_ratio:
        reasons.append("plate_completion_expanded_too_far")

    confidence = float(
        np.mean(
            [
                _bounded_score(area_ratio, minimum_area_ratio, maximum_area_ratio),
                min(1.0, largest_component_ratio / max(minimum_largest_ratio, 1e-6)),
                max(0.0, 1.0 - border_touch_ratio / max(maximum_border_touch_ratio, 1e-6)),
                max(0.0, 1.0 - hole_ratio / max(maximum_hole_ratio, 1e-6)),
                min(1.0, solidity / max(minimum_solidity, 1e-6)),
                min(
                    1.0,
                    maximum_expansion_ratio / max(expansion_ratio, 1e-6),
                ),
                min(1.0, max(0.0, float(shape_confidence))),
            ]
        )
    )
    minimum_confidence = float(config.get("minimum_confidence", 0.60))
    passed = pixels > 0 and not reasons and confidence >= minimum_confidence
    metrics: dict[str, float | int | bool | str] = {
        "passed": bool(passed),
        "confidence": round(confidence, 6),
        "pixels": pixels,
        "area_ratio": round(area_ratio, 6),
        "component_count": component_count,
        "largest_component_ratio": round(largest_component_ratio, 6),
        "border_touch_ratio": round(border_touch_ratio, 6),
        "internal_hole_ratio": round(hole_ratio, 6),
        "solidity": round(solidity, 6),
        "source_pixels": source_pixels,
        "completion_expansion_ratio": round(expansion_ratio, 6),
        "shape_type": str(shape_type),
        "shape_confidence": round(float(shape_confidence), 6),
        "minimum_confidence": minimum_confidence,
    }
    return MaskQualityResult(passed, confidence, tuple(reasons), metrics)
