from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import cv2
import numpy as np


@dataclass(frozen=True, slots=True)
class PlateEdgeRepairResult:
    image: np.ndarray
    mask: np.ndarray
    metrics: dict[str, float | int | bool | str]


def _odd(value: int) -> int:
    value = max(1, int(value))
    return value if value % 2 else value + 1


def _remove_large_components(mask: np.ndarray, max_area: int) -> np.ndarray:
    if max_area <= 0 or not np.any(mask):
        return mask

    component_count, labels, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    filtered = np.zeros_like(mask)
    for component_id in range(1, component_count):
        area = int(stats[component_id, cv2.CC_STAT_AREA])
        if area <= max_area:
            filtered[labels == component_id] = 255
    return filtered


def _estimate_rim_color(
    image_bgr: np.ndarray,
    rim_line_mask: np.ndarray,
    food_mask: np.ndarray,
    *,
    minimum_samples: int,
) -> tuple[np.ndarray | None, int]:
    sample_mask = (rim_line_mask > 0) & (food_mask == 0)
    if not np.any(sample_mask):
        return None, 0

    hsv = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2HSV)
    saturation = hsv[:, :, 1]
    value = hsv[:, :, 2]
    colored_rim = sample_mask & (saturation >= 35) & (value <= 230)
    if int(np.count_nonzero(colored_rim)) < minimum_samples:
        colored_rim = sample_mask

    sample_count = int(np.count_nonzero(colored_rim))
    if sample_count < minimum_samples:
        return None, sample_count
    return np.median(image_bgr[colored_rim], axis=0).astype(np.uint8), sample_count


def _estimate_colored_rim_color(
    image_bgr: np.ndarray,
    rim_line_mask: np.ndarray,
    food_mask: np.ndarray,
    *,
    minimum_samples: int,
    saturation_min: int,
    value_max: int,
) -> tuple[np.ndarray | None, int]:
    sample_mask = (rim_line_mask > 0) & (food_mask == 0)
    if not np.any(sample_mask):
        return None, 0

    hsv = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2HSV)
    saturation = hsv[:, :, 1]
    value = hsv[:, :, 2]
    colored = (
        sample_mask
        & (saturation >= int(saturation_min))
        & (value <= int(value_max))
    )
    sample_count = int(np.count_nonzero(colored))
    if sample_count < int(minimum_samples):
        return None, sample_count
    return np.median(image_bgr[colored], axis=0).astype(np.uint8), sample_count


def _estimate_dominant_hue_rim_color(
    image_bgr: np.ndarray,
    rim_line_mask: np.ndarray,
    food_mask: np.ndarray,
    *,
    minimum_samples: int,
    saturation_min: int,
    value_min: int,
    value_max: int,
    hue_window: int,
    hue_min: int | None = None,
    hue_max: int | None = None,
) -> tuple[np.ndarray | None, int]:
    sample_mask = (rim_line_mask > 0) & (food_mask == 0)
    if not np.any(sample_mask):
        return None, 0

    hsv = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2HSV)
    hue = hsv[:, :, 0]
    saturation = hsv[:, :, 1]
    value = hsv[:, :, 2]
    colored = (
        sample_mask
        & (saturation >= int(saturation_min))
        & (value >= int(value_min))
        & (value <= int(value_max))
    )
    if hue_min is not None and hue_max is not None:
        hue_min = int(hue_min) % 180
        hue_max = int(hue_max) % 180
        if hue_min <= hue_max:
            hue_allowed = (hue >= hue_min) & (hue <= hue_max)
        else:
            hue_allowed = (hue >= hue_min) | (hue <= hue_max)
        colored = colored & hue_allowed
    if int(np.count_nonzero(colored)) < int(minimum_samples):
        return None, int(np.count_nonzero(colored))

    hue_values = hue[colored].astype(np.int32)
    hist = np.bincount(hue_values, minlength=180)
    dominant_hue = int(np.argmax(hist))
    window = max(1, int(hue_window))
    hue_distance = np.abs(hue.astype(np.int16) - dominant_hue)
    hue_distance = np.minimum(hue_distance, 180 - hue_distance)
    dominant = colored & (hue_distance <= window)
    sample_count = int(np.count_nonzero(dominant))
    if sample_count < int(minimum_samples):
        dominant = colored
        sample_count = int(np.count_nonzero(dominant))
    return np.median(image_bgr[dominant], axis=0).astype(np.uint8), sample_count


def _build_ellipse_rim_line_mask(
    plate_mask: np.ndarray,
    thickness: int,
    *,
    inset: int = 0,
) -> np.ndarray:
    fit_mask = plate_mask
    inset = max(0, int(inset))
    if inset:
        fit_mask = cv2.erode(
            plate_mask,
            cv2.getStructuringElement(
                cv2.MORPH_ELLIPSE,
                (_odd(inset * 2 + 1), _odd(inset * 2 + 1)),
            ),
        )
        if not np.any(fit_mask):
            fit_mask = plate_mask

    contours, _ = cv2.findContours(fit_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return np.zeros_like(plate_mask)
    contour = max(contours, key=cv2.contourArea)
    if len(contour) < 5:
        return np.zeros_like(plate_mask)

    line = np.zeros_like(plate_mask)
    cv2.ellipse(line, cv2.fitEllipse(contour), 255, thickness=max(1, int(thickness)))
    plate_guard = cv2.dilate(plate_mask, np.ones((3, 3), np.uint8))
    return cv2.bitwise_and(line, plate_guard)


def _build_hue_rim_observed_mask(
    image_bgr: np.ndarray,
    plate_mask: np.ndarray,
    food_mask: np.ndarray,
    *,
    hue_min: int,
    hue_max: int,
    saturation_min: int,
    value_min: int,
    value_max: int,
    allow_food_overlap: bool,
) -> np.ndarray:
    hsv = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2HSV)
    hue = hsv[:, :, 0]
    saturation = hsv[:, :, 1]
    value = hsv[:, :, 2]
    hue_min = int(hue_min) % 180
    hue_max = int(hue_max) % 180
    if hue_min <= hue_max:
        hue_allowed = (hue >= hue_min) & (hue <= hue_max)
    else:
        hue_allowed = (hue >= hue_min) | (hue <= hue_max)
    observed = np.where(
        (plate_mask > 0)
        & hue_allowed
        & (saturation >= int(saturation_min))
        & (value >= int(value_min))
        & (value <= int(value_max)),
        255,
        0,
    ).astype(np.uint8)
    if not allow_food_overlap:
        observed = cv2.bitwise_and(observed, cv2.bitwise_not(food_mask))
    return observed


def _build_color_aligned_rim_line_mask(
    image_bgr: np.ndarray,
    plate_mask: np.ndarray,
    food_mask: np.ndarray,
    *,
    thickness: int,
    inset_min: int,
    inset_max: int,
    inset_step: int,
    hue_min: int,
    hue_max: int,
    saturation_min: int,
    value_min: int,
    value_max: int,
    top_ratio: float,
    allow_food_overlap: bool,
) -> tuple[np.ndarray, int, int]:
    observed = _build_hue_rim_observed_mask(
        image_bgr,
        plate_mask,
        food_mask,
        hue_min=hue_min,
        hue_max=hue_max,
        saturation_min=saturation_min,
        value_min=value_min,
        value_max=value_max,
        allow_food_overlap=allow_food_overlap,
    )
    top_arc = _top_plate_arc_mask(plate_mask, top_ratio)
    observed = cv2.bitwise_and(observed, top_arc)
    if not np.any(observed):
        return np.zeros_like(plate_mask), 0, 0

    best_mask = np.zeros_like(plate_mask)
    best_inset = 0
    best_score = -1
    inset_step = max(1, int(inset_step))
    for inset in range(max(0, int(inset_min)), max(0, int(inset_max)) + 1, inset_step):
        candidate = _build_ellipse_rim_line_mask(
            plate_mask,
            thickness,
            inset=inset,
        )
        candidate = cv2.bitwise_and(candidate, top_arc)
        score = int(np.count_nonzero(cv2.bitwise_and(candidate, observed)))
        if score > best_score:
            best_mask = candidate
            best_inset = inset
            best_score = score
    return best_mask, best_inset, max(0, best_score)


def _top_plate_arc_mask(plate_mask: np.ndarray, top_ratio: float) -> np.ndarray:
    ys, xs = np.where(plate_mask > 0)
    if len(xs) == 0:
        return np.zeros_like(plate_mask)
    top_ratio = min(max(float(top_ratio), 0.05), 1.0)
    y_min, y_max = int(ys.min()), int(ys.max())
    cutoff = y_min + int(round((y_max - y_min + 1) * top_ratio))
    arc = np.zeros_like(plate_mask)
    arc[: max(y_min + 1, cutoff), :] = 255
    return cv2.bitwise_and(arc, plate_mask)


def _connect_top_rim_bridge_target(
    rim_line_mask: np.ndarray,
    plate_mask: np.ndarray,
    repair_mask: np.ndarray,
    *,
    top_ratio: float,
    bridge_dilation: int,
    horizontal_margin: int,
) -> np.ndarray:
    top_arc = _top_plate_arc_mask(plate_mask, top_ratio)
    top_rim = cv2.bitwise_and(rim_line_mask, top_arc)
    if not np.any(top_rim) or not np.any(repair_mask):
        return np.zeros_like(rim_line_mask)

    bridge_anchor = cv2.dilate(
        repair_mask,
        cv2.getStructuringElement(
            cv2.MORPH_ELLIPSE,
            (_odd(bridge_dilation), _odd(bridge_dilation)),
        ),
    )
    local_bridge = cv2.bitwise_and(top_rim, bridge_anchor)
    ys, xs = np.where(local_bridge > 0)
    if len(xs) == 0:
        return local_bridge

    x_min = max(0, int(xs.min()) - max(0, int(horizontal_margin)))
    x_max = min(top_rim.shape[1] - 1, int(xs.max()) + max(0, int(horizontal_margin)))
    connected_bridge = np.zeros_like(top_rim)
    connected_bridge[:, x_min : x_max + 1] = 255
    connected_bridge = cv2.bitwise_and(connected_bridge, top_rim)
    return cv2.bitwise_or(local_bridge, connected_bridge)


def _filter_small_components(mask: np.ndarray, min_area: int) -> np.ndarray:
    if min_area <= 1 or not np.any(mask):
        return mask

    component_count, labels, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    filtered = np.zeros_like(mask)
    for component_id in range(1, component_count):
        area = int(stats[component_id, cv2.CC_STAT_AREA])
        if area >= min_area:
            filtered[labels == component_id] = 255
    return filtered


def _detect_missing_rim_segments(
    image_bgr: np.ndarray,
    rim_line_mask: np.ndarray,
    plate_mask: np.ndarray,
    repair_mask: np.ndarray,
    rim_color: np.ndarray,
    *,
    top_ratio: float,
    color_distance_threshold: float,
    anchor_dilation: int,
    close_kernel: int,
    min_component_area: int,
) -> tuple[np.ndarray, dict[str, int | float | bool]]:
    top_arc = _top_plate_arc_mask(plate_mask, top_ratio)
    expected_rim = cv2.bitwise_and(rim_line_mask, top_arc)
    if not np.any(expected_rim):
        return np.zeros_like(rim_line_mask), {
            "enabled": True,
            "expected_pixels": 0,
            "observed_pixels": 0,
            "missing_pixels": 0,
        }

    lab = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2LAB).astype(np.float32)
    rim_lab = cv2.cvtColor(
        np.uint8([[rim_color.reshape(3)]]), cv2.COLOR_BGR2LAB
    )[0, 0].astype(np.float32)
    color_distance = np.linalg.norm(lab - rim_lab.reshape(1, 1, 3), axis=2)
    observed_rim = np.where(
        (expected_rim > 0) & (color_distance <= float(color_distance_threshold)),
        255,
        0,
    ).astype(np.uint8)
    observed_rim = cv2.dilate(
        observed_rim,
        cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3)),
    )

    missing = cv2.bitwise_and(expected_rim, cv2.bitwise_not(observed_rim))
    if np.any(repair_mask):
        anchor = cv2.dilate(
            repair_mask,
            cv2.getStructuringElement(
                cv2.MORPH_ELLIPSE,
                (_odd(anchor_dilation), _odd(anchor_dilation)),
            ),
        )
        missing = cv2.bitwise_and(missing, anchor)

    if close_kernel > 1:
        missing = cv2.morphologyEx(
            missing,
            cv2.MORPH_CLOSE,
            cv2.getStructuringElement(
                cv2.MORPH_ELLIPSE,
                (_odd(close_kernel), _odd(close_kernel)),
            ),
        )
        missing = cv2.bitwise_and(missing, expected_rim)
    missing = _filter_small_components(missing, min_component_area)

    return missing, {
        "enabled": True,
        "expected_pixels": int(np.count_nonzero(expected_rim)),
        "observed_pixels": int(np.count_nonzero(cv2.bitwise_and(observed_rim, expected_rim))),
        "missing_pixels": int(np.count_nonzero(missing)),
        "color_distance_threshold": float(color_distance_threshold),
        "anchor_dilation": int(anchor_dilation),
    }


def _build_missing_rim_surface_fill_mask(
    missing_rim_mask: np.ndarray,
    plate_mask: np.ndarray,
    protected_food_mask: np.ndarray,
    *,
    top_ratio: float,
    dilation: int,
    close_kernel: int,
) -> np.ndarray:
    if not np.any(missing_rim_mask):
        return np.zeros_like(missing_rim_mask)

    top_arc = _top_plate_arc_mask(plate_mask, top_ratio)
    fill_mask = cv2.dilate(
        missing_rim_mask,
        cv2.getStructuringElement(
            cv2.MORPH_ELLIPSE,
            (_odd(dilation), _odd(dilation)),
        ),
    )
    fill_mask = cv2.bitwise_and(fill_mask, plate_mask)
    fill_mask = cv2.bitwise_and(fill_mask, top_arc)
    fill_mask = cv2.bitwise_and(fill_mask, cv2.bitwise_not(protected_food_mask))

    if close_kernel > 1:
        fill_mask = cv2.morphologyEx(
            fill_mask,
            cv2.MORPH_CLOSE,
            cv2.getStructuringElement(
                cv2.MORPH_ELLIPSE,
                (_odd(close_kernel), _odd(close_kernel)),
            ),
        )
        fill_mask = cv2.bitwise_and(fill_mask, plate_mask)
        fill_mask = cv2.bitwise_and(fill_mask, top_arc)
        fill_mask = cv2.bitwise_and(fill_mask, cv2.bitwise_not(protected_food_mask))
    return fill_mask


def _interpolate_rim_color_map(
    image_bgr: np.ndarray,
    rim_line_mask: np.ndarray,
    line_target: np.ndarray,
    rim_color: np.ndarray,
    *,
    color_distance_threshold: float,
    observed_dilation: int,
    inpaint_radius: float,
    minimum_observed_pixels: int,
) -> tuple[np.ndarray, dict[str, int | float | bool]]:
    if not np.any(line_target):
        return image_bgr.copy(), {
            "enabled": True,
            "observed_pixels": 0,
            "used_fallback_color": True,
        }

    lab = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2LAB).astype(np.float32)
    rim_lab = cv2.cvtColor(
        np.uint8([[rim_color.reshape(3)]]), cv2.COLOR_BGR2LAB
    )[0, 0].astype(np.float32)
    color_distance = np.linalg.norm(lab - rim_lab.reshape(1, 1, 3), axis=2)
    observed = np.where(
        (rim_line_mask > 0) & (color_distance <= float(color_distance_threshold)),
        255,
        0,
    ).astype(np.uint8)
    if observed_dilation > 1:
        observed = cv2.dilate(
            observed,
            cv2.getStructuringElement(
                cv2.MORPH_ELLIPSE,
                (_odd(observed_dilation), _odd(observed_dilation)),
            ),
        )
        observed = cv2.bitwise_and(observed, rim_line_mask)

    observed_pixels = int(np.count_nonzero(cv2.bitwise_and(observed, line_target)))
    if observed_pixels < int(minimum_observed_pixels):
        fallback = np.zeros_like(image_bgr)
        fallback[:, :] = rim_color.reshape(1, 1, 3)
        return fallback, {
            "enabled": True,
            "observed_pixels": observed_pixels,
            "used_fallback_color": True,
        }

    color_canvas = image_bgr.copy()
    missing_target = cv2.bitwise_and(line_target, cv2.bitwise_not(observed))
    inpaint_mask = cv2.dilate(
        missing_target,
        cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3)),
    )
    inpaint_mask = cv2.bitwise_and(inpaint_mask, rim_line_mask)
    if np.any(inpaint_mask):
        color_canvas = cv2.inpaint(
            color_canvas,
            inpaint_mask,
            float(inpaint_radius),
            cv2.INPAINT_TELEA,
        )
    return color_canvas, {
        "enabled": True,
        "observed_pixels": observed_pixels,
        "inpaint_pixels": int(np.count_nonzero(inpaint_mask)),
        "used_fallback_color": False,
        "color_distance_threshold": float(color_distance_threshold),
    }


def _interpolate_plate_surface_map(
    image_bgr: np.ndarray,
    plate_mask: np.ndarray,
    target_mask: np.ndarray,
    protected_food_mask: np.ndarray,
    *,
    sample_dilation: int,
    inpaint_radius: float,
    minimum_observed_pixels: int,
) -> tuple[np.ndarray, dict[str, int | float | bool]]:
    if not np.any(target_mask):
        return image_bgr.copy(), {
            "enabled": True,
            "observed_pixels": 0,
            "target_pixels": 0,
            "used_fallback_inpaint": False,
        }

    sample_region = cv2.dilate(
        target_mask,
        cv2.getStructuringElement(
            cv2.MORPH_ELLIPSE,
            (_odd(sample_dilation), _odd(sample_dilation)),
        ),
    )
    sample_region = cv2.bitwise_and(sample_region, plate_mask)
    sample_region = cv2.bitwise_and(sample_region, cv2.bitwise_not(target_mask))
    sample_region = cv2.bitwise_and(sample_region, cv2.bitwise_not(protected_food_mask))
    observed_pixels = int(np.count_nonzero(sample_region))

    color_canvas = image_bgr.copy()
    inpaint_mask = cv2.bitwise_and(target_mask, cv2.bitwise_not(sample_region))
    if observed_pixels < int(minimum_observed_pixels):
        if np.any(inpaint_mask):
            color_canvas = cv2.inpaint(
                color_canvas,
                inpaint_mask,
                float(inpaint_radius),
                cv2.INPAINT_TELEA,
            )
        return color_canvas, {
            "enabled": True,
            "observed_pixels": observed_pixels,
            "target_pixels": int(np.count_nonzero(target_mask)),
            "inpaint_pixels": int(np.count_nonzero(inpaint_mask)),
            "used_fallback_inpaint": True,
        }

    if np.any(inpaint_mask):
        color_canvas = cv2.inpaint(
            color_canvas,
            inpaint_mask,
            float(inpaint_radius),
            cv2.INPAINT_TELEA,
        )
    return color_canvas, {
        "enabled": True,
        "observed_pixels": observed_pixels,
        "target_pixels": int(np.count_nonzero(target_mask)),
        "inpaint_pixels": int(np.count_nonzero(inpaint_mask)),
        "used_fallback_inpaint": False,
    }


def _blend_rim_color(
    image_bgr: np.ndarray,
    mask: np.ndarray,
    rim_color: np.ndarray,
    *,
    opacity: float,
    feather_kernel: int,
) -> np.ndarray:
    if not np.any(mask):
        return image_bgr
    opacity = min(max(float(opacity), 0.0), 1.0)
    if opacity <= 0:
        return image_bgr

    alpha = (mask > 0).astype(np.float32)
    if feather_kernel > 1:
        feather_kernel = _odd(feather_kernel)
        alpha = cv2.GaussianBlur(alpha, (feather_kernel, feather_kernel), 0)
        max_alpha = float(alpha.max())
        if max_alpha > 0:
            alpha = alpha / max_alpha
    alpha = (alpha * opacity)[:, :, None]
    if rim_color.ndim == 3 and rim_color.shape == image_bgr.shape:
        color = rim_color.astype(np.float32)
    else:
        color = rim_color.astype(np.float32).reshape(1, 1, 3)
    blended = image_bgr.astype(np.float32) * (1.0 - alpha) + color * alpha
    return np.clip(blended, 0, 255).astype(np.uint8)


def _build_plate_mask_rim_completion_target(
    image_bgr: np.ndarray,
    rim_line_mask: np.ndarray,
    plate_mask: np.ndarray,
    protected_food_mask: np.ndarray,
    *,
    top_ratio: float,
    hue_min: int,
    hue_max: int,
    saturation_min: int,
    value_min: int,
    value_max: int,
    observed_dilation: int,
    close_kernel: int,
    allow_food_overlap: bool,
) -> np.ndarray:
    top_arc = _top_plate_arc_mask(plate_mask, top_ratio)
    expected = cv2.bitwise_and(rim_line_mask, top_arc)
    if not allow_food_overlap:
        expected = cv2.bitwise_and(expected, cv2.bitwise_not(protected_food_mask))
    if not np.any(expected):
        return np.zeros_like(rim_line_mask)

    hsv = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2HSV)
    hue = hsv[:, :, 0]
    saturation = hsv[:, :, 1]
    value = hsv[:, :, 2]
    hue_min = int(hue_min) % 180
    hue_max = int(hue_max) % 180
    if hue_min <= hue_max:
        hue_allowed = (hue >= hue_min) & (hue <= hue_max)
    else:
        hue_allowed = (hue >= hue_min) | (hue <= hue_max)
    observed = np.where(
        (expected > 0)
        & hue_allowed
        & (saturation >= int(saturation_min))
        & (value >= int(value_min))
        & (value <= int(value_max)),
        255,
        0,
    ).astype(np.uint8)
    if observed_dilation > 1:
        observed = cv2.dilate(
            observed,
            cv2.getStructuringElement(
                cv2.MORPH_ELLIPSE,
                (_odd(observed_dilation), _odd(observed_dilation)),
            ),
        )
        observed = cv2.bitwise_and(observed, expected)

    missing = cv2.bitwise_and(expected, cv2.bitwise_not(observed))
    if close_kernel > 1:
        missing = cv2.morphologyEx(
            missing,
            cv2.MORPH_CLOSE,
            cv2.getStructuringElement(
                cv2.MORPH_ELLIPSE,
                (_odd(close_kernel), _odd(close_kernel)),
            ),
        )
        missing = cv2.bitwise_and(missing, expected)
    return missing


def repair_plate_edge(
    image_bgr: np.ndarray,
    plate_mask: np.ndarray,
    food_mask: np.ndarray,
    config: dict[str, Any],
) -> PlateEdgeRepairResult:
    """Fill small occluders on the preserved plate rim without expanding alpha.

    This is intentionally a narrow preserve-mode repair.  The alpha layer has
    already decided where the original plate is kept; this step only repairs
    source RGB pixels along the outer rim when skewers or fragmented foreground
    make the plate edge look cut.
    """
    enabled = bool(config.get("enabled", False))
    empty = np.zeros(plate_mask.shape[:2], dtype=np.uint8)
    if not enabled:
        return PlateEdgeRepairResult(
            image=image_bgr,
            mask=empty,
            metrics={"status": "disabled", "applied": False},
        )
    if image_bgr.ndim != 3 or plate_mask.ndim != 2 or food_mask.ndim != 2:
        raise ValueError("image_bgr must be BGR and masks must be single-channel")
    if plate_mask.shape != food_mask.shape or plate_mask.shape != image_bgr.shape[:2]:
        raise ValueError("image and masks must have matching height and width")

    plate = np.where(plate_mask >= 128, 255, 0).astype(np.uint8)
    food = np.where(food_mask >= 128, 255, 0).astype(np.uint8)
    if not np.any(plate) or not np.any(food):
        return PlateEdgeRepairResult(
            image=image_bgr,
            mask=empty,
            metrics={"status": "empty_input", "applied": False},
        )

    ring_width = max(1, int(config.get("ring_width", 28)))
    erosion_kernel = _odd(ring_width * 2 + 1)
    inner_plate = cv2.erode(
        plate,
        cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (erosion_kernel, erosion_kernel)),
    )
    rim_ring = cv2.bitwise_and(plate, cv2.bitwise_not(inner_plate))

    food_core_erosion = max(0, int(config.get("food_core_erosion", 17)))
    if food_core_erosion:
        food_core_kernel = _odd(food_core_erosion * 2 + 1)
        protected_food = cv2.erode(
            food,
            cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (food_core_kernel, food_core_kernel)),
        )
    else:
        protected_food = np.zeros_like(food)
    completion_food_core_erosion = max(
        0,
        int(config.get("plate_mask_rim_completion_food_core_erosion", 31)),
    )
    if completion_food_core_erosion:
        completion_food_core_kernel = _odd(completion_food_core_erosion * 2 + 1)
        completion_protected_food = cv2.erode(
            food,
            cv2.getStructuringElement(
                cv2.MORPH_ELLIPSE,
                (completion_food_core_kernel, completion_food_core_kernel),
            ),
        )
    else:
        completion_protected_food = protected_food

    repair_mask = cv2.bitwise_and(rim_ring, food)
    repair_mask = cv2.bitwise_and(repair_mask, cv2.bitwise_not(protected_food))

    close_kernel = int(config.get("close_kernel", 5))
    if close_kernel > 1:
        close_kernel = _odd(close_kernel)
        repair_mask = cv2.morphologyEx(
            repair_mask,
            cv2.MORPH_CLOSE,
            cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (close_kernel, close_kernel)),
        )

    max_component_area = int(config.get("max_component_area", 24000))
    repair_mask = _remove_large_components(repair_mask, max_component_area)
    if not np.any(repair_mask):
        return PlateEdgeRepairResult(
            image=image_bgr,
            mask=repair_mask,
            metrics={
                "status": "empty_repair_mask",
                "applied": False,
                "ring_width": ring_width,
                "food_core_erosion": food_core_erosion,
            },
        )

    inpaint_radius = float(config.get("inpaint_radius", 7.0))
    method = str(config.get("method", "telea")).lower()
    inpaint_flag = cv2.INPAINT_NS if method == "ns" else cv2.INPAINT_TELEA
    repaired = cv2.inpaint(image_bgr, repair_mask, inpaint_radius, inpaint_flag)
    rim_line_pixels = 0
    rim_line_sample_count = 0
    synthetic_rim_bridge_pixels = 0
    synthetic_rim_band_pixels = 0
    synthetic_rim_color_sample_count = 0
    plate_mask_rim_completion_pixels = 0
    color_aligned_rim_pixels = 0
    color_aligned_rim_inset = 0
    color_aligned_rim_overlap_pixels = 0
    missing_rim_core_pixels = 0
    missing_rim_surface_pixels = 0
    missing_rim_metrics: dict[str, int | float | bool] = {"enabled": False}
    rim_surface_interpolation_metrics: dict[str, int | float | bool] = {
        "enabled": False
    }
    rim_color_interpolation_metrics: dict[str, int | float | bool] = {
        "enabled": False
    }
    if bool(config.get("restore_rim_line", True)):
        rim_line_width = max(1, int(config.get("rim_line_width", 5)))
        rim_line_mask = _build_ellipse_rim_line_mask(plate, rim_line_width)
        inner_rim_line_pixels = 0
        inner_rim_line_mask = np.zeros_like(rim_line_mask)
        if bool(config.get("restore_inner_rim_line", True)):
            inner_rim_line_mask = _build_ellipse_rim_line_mask(
                plate,
                max(1, int(config.get("inner_rim_line_width", rim_line_width))),
                inset=int(config.get("inner_rim_line_inset", 22)),
            )
            inner_rim_line_pixels = int(np.count_nonzero(inner_rim_line_mask))
            rim_line_mask = cv2.bitwise_or(rim_line_mask, inner_rim_line_mask)
        color_aligned_rim_line_mask = np.zeros_like(rim_line_mask)
        if bool(config.get("color_aligned_rim_enabled", True)):
            (
                color_aligned_rim_line_mask,
                color_aligned_rim_inset,
                color_aligned_rim_overlap_pixels,
            ) = _build_color_aligned_rim_line_mask(
                image_bgr,
                plate,
                food,
                thickness=max(
                    1,
                    int(config.get("color_aligned_rim_line_width", rim_line_width)),
                ),
                inset_min=int(config.get("color_aligned_rim_inset_min", 4)),
                inset_max=int(config.get("color_aligned_rim_inset_max", 42)),
                inset_step=int(config.get("color_aligned_rim_inset_step", 2)),
                hue_min=int(config.get("synthetic_rim_color_hue_min", 35)),
                hue_max=int(config.get("synthetic_rim_color_hue_max", 95)),
                saturation_min=int(
                    config.get("synthetic_rim_color_saturation_min", 45)
                ),
                value_min=int(config.get("synthetic_rim_color_value_min", 30)),
                value_max=int(config.get("synthetic_rim_color_value_max", 210)),
                top_ratio=float(config.get("color_aligned_rim_top_ratio", 0.36)),
                allow_food_overlap=bool(
                    config.get("color_aligned_rim_allow_food_overlap", False)
                ),
            )
            color_aligned_rim_pixels = int(np.count_nonzero(color_aligned_rim_line_mask))
            if color_aligned_rim_overlap_pixels >= int(
                config.get("color_aligned_rim_min_overlap_pixels", 32)
            ):
                rim_line_mask = cv2.bitwise_or(rim_line_mask, color_aligned_rim_line_mask)
        rim_line_sample_count_min = int(config.get("rim_line_min_samples", 128))
        rim_color, rim_line_sample_count = _estimate_rim_color(
            image_bgr,
            rim_line_mask,
            food,
            minimum_samples=rim_line_sample_count_min,
        )
        if rim_color is not None:
            target_dilation = _odd(int(config.get("rim_line_target_dilation", 9)))
            line_anchor = cv2.dilate(
                repair_mask,
                cv2.getStructuringElement(
                    cv2.MORPH_ELLIPSE, (target_dilation, target_dilation)
                ),
            )
            bridge_pixels = 0
            if bool(config.get("rim_line_bridge_occlusions", True)):
                bridge_dilation = _odd(int(config.get("rim_line_bridge_dilation", 75)))
                bridge_target = _connect_top_rim_bridge_target(
                    rim_line_mask,
                    plate,
                    repair_mask,
                    top_ratio=float(config.get("rim_line_bridge_top_ratio", 0.38)),
                    bridge_dilation=bridge_dilation,
                    horizontal_margin=int(config.get("rim_line_bridge_horizontal_margin", 36)),
                )
                bridge_pixels = int(np.count_nonzero(bridge_target))
                line_anchor = cv2.bitwise_or(line_anchor, bridge_target)
            if bool(config.get("rim_missing_detection_enabled", True)):
                missing_rim_target, missing_rim_metrics = _detect_missing_rim_segments(
                    image_bgr,
                    rim_line_mask,
                    plate,
                    repair_mask,
                    rim_color,
                    top_ratio=float(config.get("rim_missing_top_ratio", 0.34)),
                    color_distance_threshold=float(
                        config.get("rim_missing_color_distance", 42.0)
                    ),
                    anchor_dilation=int(config.get("rim_missing_anchor_dilation", 95)),
                    close_kernel=int(config.get("rim_missing_close_kernel", 11)),
                    min_component_area=int(
                        config.get("rim_missing_min_component_area", 12)
                    ),
                )
                line_anchor = cv2.bitwise_or(line_anchor, missing_rim_target)
            else:
                missing_rim_target = np.zeros_like(rim_line_mask)
            line_target = cv2.bitwise_and(rim_line_mask, line_anchor)
            rim_line_pixels = int(np.count_nonzero(line_target))
            if rim_line_pixels:
                opacity = float(config.get("rim_line_opacity", 0.85))
                rim_blend_source = rim_color
                if bool(config.get("rim_color_interpolation_enabled", True)):
                    rim_blend_source, rim_color_interpolation_metrics = (
                        _interpolate_rim_color_map(
                            image_bgr,
                            rim_line_mask,
                            line_target,
                            rim_color,
                            color_distance_threshold=float(
                                config.get("rim_color_interpolation_distance", 48.0)
                            ),
                            observed_dilation=int(
                                config.get("rim_color_interpolation_observed_dilation", 5)
                            ),
                            inpaint_radius=float(
                                config.get("rim_color_interpolation_inpaint_radius", 5.0)
                            ),
                            minimum_observed_pixels=int(
                                config.get("rim_color_interpolation_min_pixels", 96)
                            ),
                        )
                    )
                if bool(config.get("rim_missing_surface_fill_enabled", True)):
                    missing_surface_target = _build_missing_rim_surface_fill_mask(
                        missing_rim_target,
                        plate,
                        protected_food,
                        top_ratio=float(config.get("rim_missing_surface_top_ratio", 0.34)),
                        dilation=int(config.get("rim_missing_surface_dilation", 17)),
                        close_kernel=int(
                            config.get("rim_missing_surface_close_kernel", 9)
                        ),
                    )
                    missing_surface_target = cv2.bitwise_or(
                        missing_surface_target,
                        cv2.bitwise_and(repair_mask, cv2.bitwise_not(protected_food)),
                    )
                    missing_surface_target = cv2.bitwise_and(
                        missing_surface_target,
                        cv2.bitwise_not(rim_line_mask),
                    )
                    missing_rim_surface_pixels = int(
                        np.count_nonzero(missing_surface_target)
                    )
                    if missing_rim_surface_pixels:
                        surface_blend_source, rim_surface_interpolation_metrics = (
                            _interpolate_plate_surface_map(
                                repaired,
                                plate,
                                missing_surface_target,
                                protected_food,
                                sample_dilation=int(
                                    config.get(
                                        "rim_missing_surface_sample_dilation",
                                        37,
                                    )
                                ),
                                inpaint_radius=float(
                                    config.get(
                                        "rim_missing_surface_inpaint_radius",
                                        9.0,
                                    )
                                ),
                                minimum_observed_pixels=int(
                                    config.get(
                                        "rim_missing_surface_min_pixels",
                                        256,
                                    )
                                ),
                            )
                        )
                        repaired = _blend_rim_color(
                            repaired,
                            missing_surface_target,
                            surface_blend_source,
                            opacity=float(
                                config.get("rim_missing_surface_opacity", 0.92)
                            ),
                            feather_kernel=int(
                                config.get("rim_missing_surface_feather_kernel", 7)
                            ),
                        )
                        repair_mask = cv2.bitwise_or(
                            repair_mask,
                            missing_surface_target,
                        )
                repaired = _blend_rim_color(
                    repaired,
                    line_target,
                    rim_blend_source,
                    opacity=opacity,
                    feather_kernel=int(config.get("rim_line_feather_kernel", 7)),
                )
                if bool(config.get("rim_missing_core_blend_enabled", True)):
                    missing_core_target = cv2.bitwise_and(
                        line_target,
                        missing_rim_target,
                    )
                    missing_rim_core_pixels = int(np.count_nonzero(missing_core_target))
                    if missing_rim_core_pixels:
                        repaired = _blend_rim_color(
                            repaired,
                            missing_core_target,
                            rim_blend_source,
                            opacity=float(config.get("rim_missing_core_opacity", 0.88)),
                            feather_kernel=int(
                                config.get("rim_missing_core_feather_kernel", 3)
                            ),
                        )
                        repair_mask = cv2.bitwise_or(repair_mask, missing_core_target)
                repair_mask = cv2.bitwise_or(repair_mask, line_target)
                if bool(config.get("synthetic_rim_bridge_enabled", True)):
                    bridge_source_mask = color_aligned_rim_line_mask
                    if not np.any(bridge_source_mask):
                        bridge_source_mask = inner_rim_line_mask
                    if not np.any(bridge_source_mask):
                        bridge_source_mask = rim_line_mask
                    bridge_seed = cv2.bitwise_or(repair_mask, missing_rim_target)
                    synthetic_bridge_target = _connect_top_rim_bridge_target(
                        bridge_source_mask,
                        plate,
                        bridge_seed,
                        top_ratio=float(config.get("synthetic_rim_bridge_top_ratio", 0.30)),
                        bridge_dilation=int(
                            config.get("synthetic_rim_bridge_dilation", 95)
                        ),
                        horizontal_margin=int(
                            config.get("synthetic_rim_bridge_horizontal_margin", 64)
                        ),
                    )
                    if bool(config.get("synthetic_rim_bridge_connect_full_top", True)):
                        top_arc = _top_plate_arc_mask(
                            plate,
                            float(config.get("synthetic_rim_bridge_top_ratio", 0.30)),
                        )
                        top_inner_rim = cv2.bitwise_and(bridge_source_mask, top_arc)
                        if np.any(top_inner_rim) and np.any(synthetic_bridge_target):
                            ys, xs = np.where(synthetic_bridge_target > 0)
                            x_min = max(
                                0,
                                int(xs.min())
                                - max(
                                    0,
                                    int(
                                        config.get(
                                            "synthetic_rim_bridge_horizontal_margin",
                                            64,
                                        )
                                    ),
                                ),
                            )
                            x_max = min(
                                top_inner_rim.shape[1] - 1,
                                int(xs.max())
                                + max(
                                    0,
                                    int(
                                        config.get(
                                            "synthetic_rim_bridge_horizontal_margin",
                                            64,
                                        )
                                    ),
                                ),
                            )
                            full_bridge = np.zeros_like(top_inner_rim)
                            full_bridge[:, x_min : x_max + 1] = 255
                            synthetic_bridge_target = cv2.bitwise_or(
                                synthetic_bridge_target,
                                cv2.bitwise_and(full_bridge, top_inner_rim),
                            )
                    if bool(config.get("synthetic_rim_bridge_dilate", True)):
                        synthetic_bridge_target = cv2.dilate(
                            synthetic_bridge_target,
                            cv2.getStructuringElement(
                                cv2.MORPH_ELLIPSE,
                                (
                                    _odd(
                                        int(
                                            config.get(
                                                "synthetic_rim_bridge_extra_width",
                                                3,
                                            )
                                        )
                                    ),
                                    _odd(
                                        int(
                                            config.get(
                                                "synthetic_rim_bridge_extra_width",
                                                3,
                                            )
                                        )
                                    ),
                                ),
                            ),
                        )
                        synthetic_bridge_target = cv2.bitwise_and(
                            synthetic_bridge_target,
                            cv2.dilate(plate, np.ones((3, 3), np.uint8)),
                        )
                    synthetic_rim_bridge_pixels = int(
                        np.count_nonzero(synthetic_bridge_target)
                    )
                    colored_rim_color, synthetic_rim_color_sample_count = (
                        _estimate_dominant_hue_rim_color(
                            image_bgr,
                            bridge_source_mask,
                            food,
                            minimum_samples=int(
                                config.get("synthetic_rim_color_min_samples", 48)
                            ),
                            saturation_min=int(
                                config.get("synthetic_rim_color_saturation_min", 45)
                            ),
                            value_min=int(
                                config.get("synthetic_rim_color_value_min", 30)
                            ),
                            value_max=int(config.get("synthetic_rim_color_value_max", 210)),
                            hue_window=int(config.get("synthetic_rim_color_hue_window", 14)),
                            hue_min=int(config.get("synthetic_rim_color_hue_min", 35)),
                            hue_max=int(config.get("synthetic_rim_color_hue_max", 95)),
                        )
                    )
                    if colored_rim_color is None:
                        colored_rim_color, synthetic_rim_color_sample_count = (
                            _estimate_colored_rim_color(
                                image_bgr,
                                rim_line_mask,
                                food,
                                minimum_samples=int(
                                    config.get("synthetic_rim_color_min_samples", 48)
                                ),
                                saturation_min=int(
                                    config.get("synthetic_rim_color_saturation_min", 45)
                                ),
                                value_max=int(
                                    config.get("synthetic_rim_color_value_max", 210)
                                ),
                            )
                        )
                    if colored_rim_color is None:
                        colored_rim_color = rim_color
                    synthetic_band_target = synthetic_bridge_target
                    if bool(config.get("synthetic_rim_band_enabled", True)):
                        band_width = max(1, int(config.get("synthetic_rim_band_width", 11)))
                        synthetic_band_target = cv2.dilate(
                            synthetic_bridge_target,
                            cv2.getStructuringElement(
                                cv2.MORPH_ELLIPSE,
                                (_odd(band_width), _odd(band_width)),
                            ),
                        )
                        top_arc = _top_plate_arc_mask(
                            plate,
                            float(config.get("synthetic_rim_band_top_ratio", 0.30)),
                        )
                        synthetic_band_target = cv2.bitwise_and(
                            synthetic_band_target,
                            top_arc,
                        )
                        synthetic_band_target = cv2.bitwise_and(
                            synthetic_band_target,
                            cv2.dilate(plate, np.ones((3, 3), np.uint8)),
                        )
                        if not bool(config.get("synthetic_rim_band_allow_food_overlap", True)):
                            synthetic_band_target = cv2.bitwise_and(
                                synthetic_band_target,
                                cv2.bitwise_not(protected_food),
                            )
                        synthetic_rim_band_pixels = int(
                            np.count_nonzero(synthetic_band_target)
                        )
                        if synthetic_rim_band_pixels:
                            repaired = _blend_rim_color(
                                repaired,
                                synthetic_band_target,
                                colored_rim_color,
                                opacity=float(
                                    config.get("synthetic_rim_band_opacity", 0.90)
                                ),
                                feather_kernel=int(
                                    config.get("synthetic_rim_band_feather_kernel", 5)
                                ),
                            )
                    if synthetic_rim_bridge_pixels:
                        repaired = _blend_rim_color(
                            repaired,
                            synthetic_bridge_target,
                            colored_rim_color,
                            opacity=float(
                                config.get("synthetic_rim_bridge_opacity", 0.98)
                            ),
                            feather_kernel=int(
                                config.get("synthetic_rim_bridge_feather_kernel", 3)
                            ),
                        )
                        repair_mask = cv2.bitwise_or(
                            repair_mask,
                            synthetic_bridge_target,
                        )
                if bool(config.get("plate_mask_rim_completion_enabled", True)):
                    completion_source_mask = color_aligned_rim_line_mask
                    if not np.any(completion_source_mask):
                        completion_source_mask = inner_rim_line_mask
                    if not np.any(completion_source_mask):
                        completion_source_mask = rim_line_mask
                    completion_color, completion_sample_count = (
                        _estimate_dominant_hue_rim_color(
                            image_bgr,
                            completion_source_mask,
                            food,
                            minimum_samples=int(
                                config.get("synthetic_rim_color_min_samples", 48)
                            ),
                            saturation_min=int(
                                config.get("synthetic_rim_color_saturation_min", 45)
                            ),
                            value_min=int(
                                config.get("synthetic_rim_color_value_min", 30)
                            ),
                            value_max=int(
                                config.get("synthetic_rim_color_value_max", 210)
                            ),
                            hue_window=int(
                                config.get("synthetic_rim_color_hue_window", 14)
                            ),
                            hue_min=int(config.get("synthetic_rim_color_hue_min", 35)),
                            hue_max=int(config.get("synthetic_rim_color_hue_max", 95)),
                        )
                    )
                    if completion_color is None:
                        completion_color = rim_color
                    else:
                        synthetic_rim_color_sample_count = max(
                            synthetic_rim_color_sample_count,
                            completion_sample_count,
                        )
                    completion_target = _build_plate_mask_rim_completion_target(
                        repaired,
                        completion_source_mask,
                        plate,
                        completion_protected_food,
                        top_ratio=float(
                            config.get("plate_mask_rim_completion_top_ratio", 0.30)
                        ),
                        hue_min=int(config.get("synthetic_rim_color_hue_min", 35)),
                        hue_max=int(config.get("synthetic_rim_color_hue_max", 95)),
                        saturation_min=int(
                            config.get("synthetic_rim_color_saturation_min", 45)
                        ),
                        value_min=int(config.get("synthetic_rim_color_value_min", 30)),
                        value_max=int(config.get("synthetic_rim_color_value_max", 210)),
                        observed_dilation=int(
                            config.get("plate_mask_rim_completion_observed_dilation", 7)
                        ),
                        close_kernel=int(
                            config.get("plate_mask_rim_completion_close_kernel", 9)
                        ),
                        allow_food_overlap=bool(
                            config.get(
                                "plate_mask_rim_completion_allow_food_overlap",
                                False,
                            )
                        ),
                    )
                    if bool(config.get("plate_mask_rim_completion_expand", True)):
                        completion_target = cv2.dilate(
                            completion_target,
                            cv2.getStructuringElement(
                                cv2.MORPH_ELLIPSE,
                                (
                                    _odd(
                                        int(
                                            config.get(
                                                "plate_mask_rim_completion_width",
                                                5,
                                            )
                                        )
                                    ),
                                    _odd(
                                        int(
                                            config.get(
                                                "plate_mask_rim_completion_width",
                                                5,
                                            )
                                        )
                                    ),
                                ),
                            ),
                        )
                        completion_target = cv2.bitwise_and(
                            completion_target,
                            cv2.dilate(plate, np.ones((3, 3), np.uint8)),
                        )
                        if not bool(
                            config.get(
                                "plate_mask_rim_completion_allow_food_overlap",
                                False,
                            )
                        ):
                            completion_target = cv2.bitwise_and(
                                completion_target,
                                cv2.bitwise_not(completion_protected_food),
                            )
                    plate_mask_rim_completion_pixels = int(
                        np.count_nonzero(completion_target)
                    )
                    if plate_mask_rim_completion_pixels:
                        repaired = _blend_rim_color(
                            repaired,
                            completion_target,
                            completion_color,
                            opacity=float(
                                config.get("plate_mask_rim_completion_opacity", 0.88)
                            ),
                            feather_kernel=int(
                                config.get(
                                    "plate_mask_rim_completion_feather_kernel",
                                    5,
                                )
                            ),
                        )
                        repair_mask = cv2.bitwise_or(repair_mask, completion_target)

    return PlateEdgeRepairResult(
        image=repaired,
        mask=repair_mask,
        metrics={
            "status": "completed",
            "applied": True,
            "target_pixels": int(np.count_nonzero(repair_mask)),
            "ring_width": ring_width,
            "food_core_erosion": food_core_erosion,
            "plate_mask_rim_completion_food_core_erosion": completion_food_core_erosion,
            "close_kernel": close_kernel,
            "max_component_area": max_component_area,
            "inpaint_radius": inpaint_radius,
            "method": method,
            "rim_line_pixels": rim_line_pixels,
            "inner_rim_line_pixels": inner_rim_line_pixels
            if "inner_rim_line_pixels" in locals()
            else 0,
            "color_aligned_rim_pixels": color_aligned_rim_pixels,
            "color_aligned_rim_inset": color_aligned_rim_inset,
            "color_aligned_rim_overlap_pixels": color_aligned_rim_overlap_pixels,
            "rim_line_sample_count": rim_line_sample_count,
            "synthetic_rim_bridge_pixels": synthetic_rim_bridge_pixels,
            "synthetic_rim_band_pixels": synthetic_rim_band_pixels,
            "synthetic_rim_color_sample_count": synthetic_rim_color_sample_count,
            "plate_mask_rim_completion_pixels": plate_mask_rim_completion_pixels,
            "rim_line_bridge_occlusions": bool(
                config.get("rim_line_bridge_occlusions", True)
            ),
            "rim_line_bridge_pixels": bridge_pixels
            if "bridge_pixels" in locals()
            else 0,
            "missing_rim_detection": missing_rim_metrics,
            "rim_surface_interpolation": rim_surface_interpolation_metrics,
            "missing_rim_surface_pixels": missing_rim_surface_pixels,
            "rim_color_interpolation": rim_color_interpolation_metrics,
            "missing_rim_core_pixels": missing_rim_core_pixels,
        },
    )
