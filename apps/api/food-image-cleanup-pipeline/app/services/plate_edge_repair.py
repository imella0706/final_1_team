from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import cv2
import numpy as np

from app.services.rim_observation import observe_container_rim


@dataclass(frozen=True, slots=True)
class PlateEdgeRepairResult:
    image: np.ndarray
    mask: np.ndarray
    metrics: dict[str, float | int | bool | str]
    alpha_extension_mask: np.ndarray | None = None


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
    # Geometry derived only from the plate mask must never paint outside it.
    # A separate, evidence-backed observed-rim fit may extend the support later.
    return cv2.bitwise_and(line, plate_mask)


def _build_shape_rim_line_mask(
    plate_mask: np.ndarray,
    thickness: int,
    *,
    shape_type: str,
    inset: int = 0,
) -> np.ndarray:
    if shape_type == "ellipse":
        return _build_ellipse_rim_line_mask(
            plate_mask,
            thickness,
            inset=inset,
        )

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
    contours, _ = cv2.findContours(
        fit_mask,
        cv2.RETR_EXTERNAL,
        cv2.CHAIN_APPROX_NONE,
    )
    line = np.zeros_like(plate_mask)
    if not contours:
        return line
    contour = max(contours, key=cv2.contourArea)
    cv2.drawContours(line, [contour], -1, 255, max(1, int(thickness)))
    return cv2.bitwise_and(line, plate_mask)


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


def _build_observed_rim_fitted_line_mask(
    image_bgr: np.ndarray,
    plate_mask: np.ndarray,
    *,
    thickness: int,
    boundary_width: int,
    plate_dilation: int,
    minimum_component_area: int,
    minimum_pixels: int,
    observed_dilation: int,
    minimum_overlap_ratio: float,
    maximum_aspect_ratio: float,
    minimum_area_ratio: float,
    maximum_area_ratio: float,
    maximum_center_shift_ratio: float,
    hue_min: int,
    hue_max: int,
    saturation_min: int,
    value_min: int,
    value_max: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, dict[str, Any]]:
    """Fit the expected rim to real colored rim pixels near the plate boundary."""
    empty = np.zeros_like(plate_mask)
    plate_dilation = max(0, int(plate_dilation))
    if plate_dilation:
        plate_guard = cv2.dilate(
            plate_mask,
            cv2.getStructuringElement(
                cv2.MORPH_ELLIPSE,
                (_odd(plate_dilation * 2 + 1), _odd(plate_dilation * 2 + 1)),
            ),
        )
    else:
        plate_guard = plate_mask

    boundary_width = max(1, int(boundary_width))
    inner_plate = cv2.erode(
        plate_mask,
        cv2.getStructuringElement(
            cv2.MORPH_ELLIPSE,
            (_odd(boundary_width * 2 + 1), _odd(boundary_width * 2 + 1)),
        ),
    )
    boundary_band = cv2.bitwise_and(plate_guard, cv2.bitwise_not(inner_plate))
    observed = _build_hue_rim_observed_mask(
        image_bgr,
        plate_guard,
        np.zeros_like(plate_mask),
        hue_min=hue_min,
        hue_max=hue_max,
        saturation_min=saturation_min,
        value_min=value_min,
        value_max=value_max,
        allow_food_overlap=True,
    )
    observed = cv2.bitwise_and(observed, boundary_band)
    observed = _filter_small_components(observed, max(1, int(minimum_component_area)))

    ys, xs = np.where(observed > 0)
    observed_pixels = int(len(xs))
    metrics: dict[str, Any] = {
        "enabled": True,
        "used": False,
        "observed_pixels": observed_pixels,
    }
    if observed_pixels < max(5, int(minimum_pixels)):
        metrics["reason"] = "insufficient_observed_rim_pixels"
        return empty, observed, empty, metrics

    points = np.column_stack((xs, ys)).astype(np.float32).reshape(-1, 1, 2)
    fitted_ellipse = cv2.fitEllipse(points)
    (center_x, center_y), (axis_a, axis_b), angle = fitted_ellipse
    aspect_ratio = max(axis_a, axis_b) / max(min(axis_a, axis_b), 1.0)
    fitted_area = float(np.pi * axis_a * axis_b * 0.25)
    plate_area = float(np.count_nonzero(plate_mask))
    area_ratio = fitted_area / max(plate_area, 1.0)

    plate_contours, _ = cv2.findContours(
        plate_mask,
        cv2.RETR_EXTERNAL,
        cv2.CHAIN_APPROX_SIMPLE,
    )
    center_shift_ratio = 0.0
    if plate_contours:
        plate_contour = max(plate_contours, key=cv2.contourArea)
        if len(plate_contour) >= 5:
            (plate_center_x, plate_center_y), (plate_axis_a, plate_axis_b), _ = (
                cv2.fitEllipse(plate_contour)
            )
            center_shift_ratio = float(
                np.hypot(center_x - plate_center_x, center_y - plate_center_y)
                / max(plate_axis_a, plate_axis_b, 1.0)
            )

    line = np.zeros_like(plate_mask)
    cv2.ellipse(line, fitted_ellipse, 255, thickness=max(1, int(thickness)))
    line = cv2.bitwise_and(line, plate_guard)
    filled = np.zeros_like(plate_mask)
    cv2.ellipse(filled, fitted_ellipse, 255, thickness=-1)
    filled = cv2.bitwise_and(filled, plate_guard)

    observed_near = cv2.dilate(
        observed,
        cv2.getStructuringElement(
            cv2.MORPH_ELLIPSE,
            (_odd(observed_dilation), _odd(observed_dilation)),
        ),
    )
    line_pixels = int(np.count_nonzero(line))
    overlap_pixels = int(np.count_nonzero(cv2.bitwise_and(line, observed_near)))
    overlap_ratio = overlap_pixels / max(line_pixels, 1)
    metrics.update(
        {
            "line_pixels": line_pixels,
            "overlap_pixels": overlap_pixels,
            "overlap_ratio": round(float(overlap_ratio), 6),
            "ellipse_center_x": round(float(center_x), 3),
            "ellipse_center_y": round(float(center_y), 3),
            "ellipse_axis_a": round(float(axis_a), 3),
            "ellipse_axis_b": round(float(axis_b), 3),
            "ellipse_angle": round(float(angle), 3),
            "ellipse_aspect_ratio": round(float(aspect_ratio), 6),
            "ellipse_area_ratio": round(float(area_ratio), 6),
            "center_shift_ratio": round(float(center_shift_ratio), 6),
        }
    )
    if aspect_ratio > float(maximum_aspect_ratio):
        metrics["reason"] = "ellipse_aspect_ratio_rejected"
        return empty, observed, empty, metrics
    if not float(minimum_area_ratio) <= area_ratio <= float(maximum_area_ratio):
        metrics["reason"] = "ellipse_area_ratio_rejected"
        return empty, observed, empty, metrics
    if center_shift_ratio > float(maximum_center_shift_ratio):
        metrics["reason"] = "ellipse_center_shift_rejected"
        return empty, observed, empty, metrics
    if overlap_ratio < float(minimum_overlap_ratio):
        metrics["reason"] = "ellipse_color_overlap_rejected"
        return empty, observed, empty, metrics

    metrics["used"] = True
    metrics["reason"] = "observed_rim_ellipse_accepted"
    return line, observed, filled, metrics


def _build_bracketed_rim_gap_target(
    expected_rim_line: np.ndarray,
    observed_rim: np.ndarray,
    fitted_rim_fill: np.ndarray,
    repair_seed: np.ndarray,
    *,
    top_ratio: float,
    observed_dilation: int,
    anchor_close_kernel: int,
    repair_anchor_dilation: int,
    minimum_gap_width: int,
    maximum_gap_width: int,
    endpoint_margin: int,
) -> tuple[np.ndarray, dict[str, Any]]:
    """Fill only top-rim gaps that have real rim-color anchors on both sides."""
    empty = np.zeros_like(expected_rim_line)
    top_arc = _top_plate_arc_mask(fitted_rim_fill, top_ratio)
    expected = cv2.bitwise_and(expected_rim_line, top_arc)
    if not np.any(expected) or not np.any(observed_rim):
        return empty, {
            "enabled": True,
            "gap_count": 0,
            "reason": "missing_expected_or_observed_rim",
        }

    observed_near = cv2.dilate(
        observed_rim,
        cv2.getStructuringElement(
            cv2.MORPH_ELLIPSE,
            (_odd(observed_dilation), _odd(observed_dilation)),
        ),
    )
    anchored = cv2.bitwise_and(expected, observed_near)
    expected_columns = np.any(expected > 0, axis=0)
    anchored_columns = np.any(anchored > 0, axis=0)
    if anchor_close_kernel > 1:
        row = (anchored_columns.astype(np.uint8) * 255).reshape(1, -1)
        row = cv2.morphologyEx(
            row,
            cv2.MORPH_CLOSE,
            cv2.getStructuringElement(
                cv2.MORPH_RECT,
                (_odd(anchor_close_kernel), 1),
            ),
        )
        anchored_columns = row.reshape(-1) > 0

    anchor_x = np.flatnonzero(anchored_columns & expected_columns)
    if len(anchor_x) < 2:
        return empty, {
            "enabled": True,
            "gap_count": 0,
            "anchor_columns": int(len(anchor_x)),
            "reason": "insufficient_bracketing_anchors",
        }

    repair_near = cv2.dilate(
        repair_seed,
        cv2.getStructuringElement(
            cv2.MORPH_ELLIPSE,
            (_odd(repair_anchor_dilation), _odd(repair_anchor_dilation)),
        ),
    )
    minimum_gap_width = max(1, int(minimum_gap_width))
    maximum_gap_width = max(minimum_gap_width, int(maximum_gap_width))
    endpoint_margin = max(0, int(endpoint_margin))
    target = np.zeros_like(expected)
    accepted_widths: list[int] = []
    first_anchor = int(anchor_x.min())
    last_anchor = int(anchor_x.max())
    x = first_anchor + 1
    while x < last_anchor:
        if anchored_columns[x] or not expected_columns[x]:
            x += 1
            continue
        start = x
        while (
            x <= last_anchor
            and expected_columns[x]
            and not anchored_columns[x]
        ):
            x += 1
        end = x - 1
        if x > last_anchor or not anchored_columns[x]:
            continue
        width = end - start + 1
        if not minimum_gap_width <= width <= maximum_gap_width:
            continue

        left = max(first_anchor, start - endpoint_margin)
        right = min(last_anchor, end + endpoint_margin)
        candidate = np.zeros_like(expected)
        candidate[:, left : right + 1] = expected[:, left : right + 1]
        if not np.any(cv2.bitwise_and(candidate, repair_near)):
            continue
        target = cv2.bitwise_or(target, candidate)
        accepted_widths.append(width)

    return target, {
        "enabled": True,
        "gap_count": len(accepted_widths),
        "gap_widths": accepted_widths,
        "anchor_columns": int(len(anchor_x)),
        "target_pixels": int(np.count_nonzero(target)),
        "reason": "bracketed_gaps_selected" if accepted_widths else "no_eligible_gap",
    }


def _build_contour_bracketed_gap_target(
    expected_rim_line: np.ndarray,
    observed_rim: np.ndarray,
    fitted_rim_fill: np.ndarray,
    repair_seed: np.ndarray,
    *,
    observed_dilation: int,
    anchor_close_kernel: int,
    repair_anchor_dilation: int,
    minimum_gap_length: int,
    maximum_gap_length: int,
    endpoint_margin: int,
    line_width: int,
    maximum_gap_count: int,
    maximum_total_gap_fraction: float,
    allowed_region: np.ndarray | None = None,
) -> tuple[np.ndarray, dict[str, Any]]:
    """Select only contour gaps with observed anchors at both endpoints."""
    empty = np.zeros_like(expected_rim_line)
    contours, _ = cv2.findContours(
        fitted_rim_fill,
        cv2.RETR_EXTERNAL,
        cv2.CHAIN_APPROX_NONE,
    )
    if not contours or not np.any(expected_rim_line) or not np.any(observed_rim):
        return empty, {
            "enabled": True,
            "gap_count": 0,
            "reason": "missing_contour_or_observed_rim",
        }

    contour = max(contours, key=cv2.contourArea).reshape(-1, 2)
    if len(contour) < 8:
        return empty, {
            "enabled": True,
            "gap_count": 0,
            "reason": "contour_too_short",
        }
    observed_near = cv2.dilate(
        observed_rim,
        cv2.getStructuringElement(
            cv2.MORPH_ELLIPSE,
            (_odd(observed_dilation), _odd(observed_dilation)),
        ),
    )
    anchored = observed_near[contour[:, 1], contour[:, 0]] > 0
    if anchor_close_kernel > 1:
        cyclic = np.concatenate([anchored, anchored, anchored]).astype(np.uint8)
        cyclic = cv2.morphologyEx(
            (cyclic * 255).reshape(1, -1),
            cv2.MORPH_CLOSE,
            cv2.getStructuringElement(
                cv2.MORPH_RECT,
                (_odd(anchor_close_kernel), 1),
            ),
        ).reshape(-1) > 0
        anchored = cyclic[len(anchored) : len(anchored) * 2]
    if int(np.count_nonzero(anchored)) < 2:
        return empty, {
            "enabled": True,
            "gap_count": 0,
            "anchor_points": int(np.count_nonzero(anchored)),
            "reason": "insufficient_bracketing_anchors",
        }

    repair_near = cv2.dilate(
        repair_seed,
        cv2.getStructuringElement(
            cv2.MORPH_ELLIPSE,
            (_odd(repair_anchor_dilation), _odd(repair_anchor_dilation)),
        ),
    )
    length = len(contour)
    minimum_gap_length = max(1, int(minimum_gap_length))
    maximum_gap_length = max(minimum_gap_length, int(maximum_gap_length))
    endpoint_margin = max(0, int(endpoint_margin))
    starts = [
        index
        for index in range(length)
        if not anchored[index] and anchored[(index - 1) % length]
    ]
    candidates: list[tuple[float, int, np.ndarray]] = []
    for start in starts:
        end = start
        while not anchored[end % length] and end - start < length:
            end += 1
        gap_length = end - start
        if not minimum_gap_length <= gap_length <= maximum_gap_length:
            continue
        indices = [
            index % length
            for index in range(
                start - endpoint_margin,
                end + endpoint_margin + 1,
            )
        ]
        points = contour[indices]
        point_mask = np.zeros_like(expected_rim_line)
        cv2.polylines(
            point_mask,
            [points.reshape(-1, 1, 2)],
            False,
            255,
            max(1, int(line_width)),
        )
        candidate = cv2.bitwise_and(point_mask, expected_rim_line)
        if allowed_region is not None:
            candidate = cv2.bitwise_and(candidate, allowed_region)
        if not np.any(candidate):
            continue
        repair_overlap = int(
            np.count_nonzero(cv2.bitwise_and(candidate, repair_near))
        )
        if repair_overlap == 0:
            continue
        score = repair_overlap / max(np.count_nonzero(candidate), 1)
        candidates.append((float(score), gap_length, candidate))

    candidates.sort(key=lambda item: (item[0], -item[1]), reverse=True)
    maximum_gap_count = max(1, int(maximum_gap_count))
    maximum_total_length = max(
        minimum_gap_length,
        int(round(length * max(0.0, float(maximum_total_gap_fraction)))),
    )
    target = np.zeros_like(expected_rim_line)
    accepted_lengths: list[int] = []
    total_length = 0
    for _, gap_length, candidate in candidates:
        if len(accepted_lengths) >= maximum_gap_count:
            break
        if total_length + gap_length > maximum_total_length:
            continue
        target = cv2.bitwise_or(target, candidate)
        accepted_lengths.append(gap_length)
        total_length += gap_length

    return target, {
        "enabled": True,
        "gap_count": len(accepted_lengths),
        "gap_lengths": accepted_lengths,
        "anchor_points": int(np.count_nonzero(anchored)),
        "contour_points": length,
        "candidate_gap_count": len(candidates),
        "maximum_gap_count": maximum_gap_count,
        "maximum_total_gap_length": maximum_total_length,
        "selected_total_gap_length": total_length,
        "target_pixels": int(np.count_nonzero(target)),
        "reason": (
            "contour_bracketed_gaps_selected"
            if accepted_lengths
            else "no_eligible_contour_gap"
        ),
    }


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
    support_mask: np.ndarray | None = None,
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
    if support_mask is not None:
        alpha *= (support_mask > 0).astype(np.float32)
    alpha = (alpha * opacity)[:, :, None]
    if rim_color.ndim == 3 and rim_color.shape == image_bgr.shape:
        color = rim_color.astype(np.float32)
    else:
        color = rim_color.astype(np.float32).reshape(1, 1, 3)
    blended = image_bgr.astype(np.float32) * (1.0 - alpha) + color * alpha
    return np.clip(blended, 0, 255).astype(np.uint8)


def _restore_source_pixels(
    image_bgr: np.ndarray,
    source_bgr: np.ndarray,
    mask: np.ndarray,
    *,
    feather_kernel: int,
) -> np.ndarray:
    if not np.any(mask):
        return image_bgr
    alpha = mask.astype(np.float32) / 255.0
    feather_kernel = _odd(feather_kernel)
    if feather_kernel > 1:
        alpha = cv2.GaussianBlur(alpha, (feather_kernel, feather_kernel), 0)
    alpha = alpha[:, :, None]
    blended = (
        image_bgr.astype(np.float32) * (1.0 - alpha)
        + source_bgr.astype(np.float32) * alpha
    )
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
    *,
    shape_type: str | None = None,
    plate_quality: dict[str, Any] | None = None,
    food_quality: dict[str, Any] | None = None,
    protected_detail_mask: np.ndarray | None = None,
    source_image_bgr: np.ndarray | None = None,
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
    protected_detail = (
        np.where(protected_detail_mask >= 128, 255, 0).astype(np.uint8)
        if protected_detail_mask is not None
        else np.zeros_like(plate)
    )
    source_image = source_image_bgr if source_image_bgr is not None else image_bgr
    if protected_detail.shape != plate.shape or source_image.shape != image_bgr.shape:
        raise ValueError("protected detail and source image must match the input image")
    resolved_shape_type = str(
        shape_type or config.get("shape_type", "ellipse")
    ).strip().lower()
    if resolved_shape_type not in {"ellipse", "quadrilateral", "irregular"}:
        resolved_shape_type = "irregular"
    quality_gate_enabled = bool(config.get("quality_gate_enabled", True))
    plate_quality_passed = (
        True if plate_quality is None else bool(plate_quality.get("passed", False))
    )
    food_quality_passed = (
        True if food_quality is None else bool(food_quality.get("passed", False))
    )
    synthetic_quality_allowed = (
        not quality_gate_enabled
        or (plate_quality_passed and food_quality_passed)
    )
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
    detail_guard_width = max(1, int(config.get("protected_detail_guard_width", 5)))
    protected_detail_guard = cv2.dilate(
        protected_detail,
        cv2.getStructuringElement(
            cv2.MORPH_ELLIPSE,
            (_odd(detail_guard_width), _odd(detail_guard_width)),
        ),
    )
    repair_mask = cv2.bitwise_and(
        repair_mask,
        cv2.bitwise_not(protected_detail_guard),
    )

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
    alpha_extension_mask = np.zeros_like(plate)
    observed_rim_fit_metrics: dict[str, Any] = {"enabled": False, "used": False}
    adaptive_rim_observation_metrics: dict[str, Any] = {
        "enabled": False,
        "used": False,
    }
    observed_source_rim_mask = np.zeros_like(plate)
    bracketed_gap_metrics: dict[str, Any] = {"enabled": False, "gap_count": 0}
    synthetic_rim_bridge_mode = str(
        config.get("synthetic_rim_bridge_mode", "observed_gap")
    ).strip().lower()
    synthetic_rim_bridge_outside_plate_pixels = 0
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
        rim_line_mask = _build_shape_rim_line_mask(
            plate,
            rim_line_width,
            shape_type=resolved_shape_type,
        )
        inner_rim_line_pixels = 0
        inner_rim_line_mask = np.zeros_like(rim_line_mask)
        if bool(config.get("restore_inner_rim_line", True)):
            inner_rim_line_mask = _build_shape_rim_line_mask(
                plate,
                max(1, int(config.get("inner_rim_line_width", rim_line_width))),
                shape_type=resolved_shape_type,
                inset=int(config.get("inner_rim_line_inset", 22)),
            )
            inner_rim_line_pixels = int(np.count_nonzero(inner_rim_line_mask))
            rim_line_mask = cv2.bitwise_or(rim_line_mask, inner_rim_line_mask)
        color_aligned_rim_line_mask = np.zeros_like(rim_line_mask)
        if (
            resolved_shape_type == "ellipse"
            and bool(config.get("color_aligned_rim_enabled", True))
        ):
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
                            support_mask=plate,
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
                    support_mask=plate,
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
                            support_mask=plate,
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
                    bridge_support_mask = plate
                    fitted_rim_fill = plate
                    observed_rim = np.zeros_like(plate)
                    adaptive_rim_color: np.ndarray | None = None
                    adaptive_rim_config = dict(
                        config.get("adaptive_rim_observation", {})
                    )
                    adaptive_rim_enabled = bool(
                        adaptive_rim_config.get("enabled", True)
                    )
                    if adaptive_rim_enabled:
                        adaptive_observation = observe_container_rim(
                            image_bgr,
                            plate,
                            food,
                            shape_type=resolved_shape_type,
                            config=adaptive_rim_config,
                        )
                        adaptive_rim_observation_metrics = {
                            "enabled": True,
                            **adaptive_observation.metrics,
                        }
                        if bool(adaptive_observation.metrics.get("used", False)):
                            bridge_source_mask = adaptive_observation.line_mask
                            observed_rim = adaptive_observation.observed_mask
                            fitted_rim_fill = adaptive_observation.fill_mask
                            adaptive_rim_color = adaptive_observation.color_bgr
                            outside_tolerance = max(
                                0,
                                int(
                                    config.get(
                                        "synthetic_rim_bridge_plate_outside_tolerance",
                                        9,
                                    )
                                ),
                            )
                            bridge_support_mask = cv2.dilate(
                                plate,
                                cv2.getStructuringElement(
                                    cv2.MORPH_ELLIPSE,
                                    (
                                        _odd(outside_tolerance * 2 + 1),
                                        _odd(outside_tolerance * 2 + 1),
                                    ),
                                ),
                            )
                            if bool(
                                config.get(
                                    "observed_source_rim_preservation_enabled",
                                    True,
                                )
                            ):
                                source_width = max(
                                    1,
                                    int(
                                        config.get(
                                            "observed_source_rim_dilation",
                                            3,
                                        )
                                    ),
                                )
                                observed_source_rim_mask = cv2.dilate(
                                    observed_rim,
                                    cv2.getStructuringElement(
                                        cv2.MORPH_ELLIPSE,
                                        (_odd(source_width), _odd(source_width)),
                                    ),
                                )
                                source_corridor = cv2.dilate(
                                    bridge_source_mask,
                                    cv2.getStructuringElement(
                                        cv2.MORPH_ELLIPSE,
                                        (
                                            _odd(source_width + 2),
                                            _odd(source_width + 2),
                                        ),
                                    ),
                                )
                                observed_source_rim_mask = cv2.bitwise_and(
                                    observed_source_rim_mask,
                                    source_corridor,
                                )
                                observed_source_rim_mask = cv2.bitwise_and(
                                    observed_source_rim_mask,
                                    bridge_support_mask,
                                )
                                observed_source_rim_mask = cv2.bitwise_and(
                                    observed_source_rim_mask,
                                    cv2.bitwise_not(protected_detail_guard),
                                )
                        else:
                            synthetic_quality_allowed = False
                    elif bool(config.get("observed_rim_fit_enabled", True)):
                        (
                            observed_fit_line,
                            observed_rim,
                            fitted_rim_fill,
                            observed_rim_fit_metrics,
                        ) = _build_observed_rim_fitted_line_mask(
                            image_bgr,
                            plate,
                            thickness=max(
                                1,
                                int(
                                    config.get(
                                        "observed_rim_fit_line_width",
                                        config.get(
                                            "color_aligned_rim_line_width",
                                            rim_line_width,
                                        ),
                                    )
                                ),
                            ),
                            boundary_width=int(
                                config.get("observed_rim_fit_boundary_width", 52)
                            ),
                            plate_dilation=int(
                                config.get("observed_rim_fit_plate_dilation", 9)
                            ),
                            minimum_component_area=int(
                                config.get("observed_rim_fit_min_component_area", 8)
                            ),
                            minimum_pixels=int(
                                config.get("observed_rim_fit_min_pixels", 256)
                            ),
                            observed_dilation=int(
                                config.get("observed_rim_fit_observed_dilation", 7)
                            ),
                            minimum_overlap_ratio=float(
                                config.get("observed_rim_fit_min_overlap_ratio", 0.55)
                            ),
                            maximum_aspect_ratio=float(
                                config.get("observed_rim_fit_max_aspect_ratio", 1.35)
                            ),
                            minimum_area_ratio=float(
                                config.get("observed_rim_fit_min_area_ratio", 0.55)
                            ),
                            maximum_area_ratio=float(
                                config.get("observed_rim_fit_max_area_ratio", 1.05)
                            ),
                            maximum_center_shift_ratio=float(
                                config.get(
                                    "observed_rim_fit_max_center_shift_ratio",
                                    0.08,
                                )
                            ),
                            hue_min=int(config.get("synthetic_rim_color_hue_min", 35)),
                            hue_max=int(config.get("synthetic_rim_color_hue_max", 95)),
                            saturation_min=int(
                                config.get("synthetic_rim_color_saturation_min", 45)
                            ),
                            value_min=int(
                                config.get("synthetic_rim_color_value_min", 30)
                            ),
                            value_max=int(
                                config.get("synthetic_rim_color_value_max", 210)
                            ),
                        )
                        if bool(observed_rim_fit_metrics.get("used", False)):
                            bridge_source_mask = observed_fit_line
                            outside_tolerance = max(
                                0,
                                int(
                                    config.get(
                                        "synthetic_rim_bridge_plate_outside_tolerance",
                                        9,
                                    )
                                ),
                            )
                            bridge_support_mask = cv2.dilate(
                                plate,
                                cv2.getStructuringElement(
                                    cv2.MORPH_ELLIPSE,
                                    (
                                        _odd(outside_tolerance * 2 + 1),
                                        _odd(outside_tolerance * 2 + 1),
                                    ),
                                ),
                            )

                    observation_used = bool(
                        adaptive_rim_observation_metrics.get("used", False)
                    ) or bool(observed_rim_fit_metrics.get("used", False))
                    if not synthetic_quality_allowed:
                        synthetic_bridge_target = np.zeros_like(plate)
                        bracketed_gap_metrics = {
                            "enabled": True,
                            "gap_count": 0,
                            "reason": (
                                "low_confidence_fallback_original_mask"
                                if plate_quality_passed and food_quality_passed
                                else "food_or_plate_mask_quality_rejected"
                            ),
                        }
                    elif (
                        synthetic_rim_bridge_mode == "observed_contour_gap"
                        and observation_used
                    ):
                        contour_gap_allowed_region = None
                        if (
                            resolved_shape_type == "ellipse"
                            and bool(
                                config.get(
                                    "synthetic_rim_bridge_ellipse_top_only",
                                    True,
                                )
                            )
                        ):
                            contour_gap_allowed_region = _top_plate_arc_mask(
                                fitted_rim_fill,
                                float(
                                    config.get(
                                        "synthetic_rim_bridge_ellipse_top_ratio",
                                        0.36,
                                    )
                                ),
                            )
                        (
                            synthetic_bridge_target,
                            bracketed_gap_metrics,
                        ) = _build_contour_bracketed_gap_target(
                            bridge_source_mask,
                            observed_rim,
                            fitted_rim_fill,
                            bridge_seed,
                            observed_dilation=int(
                                config.get(
                                    "synthetic_rim_bridge_gap_observed_dilation",
                                    7,
                                )
                            ),
                            anchor_close_kernel=int(
                                config.get(
                                    "synthetic_rim_bridge_gap_anchor_close_kernel",
                                    5,
                                )
                            ),
                            repair_anchor_dilation=int(
                                config.get("synthetic_rim_bridge_dilation", 95)
                            ),
                            minimum_gap_length=int(
                                config.get(
                                    "synthetic_rim_bridge_gap_min_length",
                                    3,
                                )
                            ),
                            maximum_gap_length=int(
                                config.get(
                                    "synthetic_rim_bridge_gap_max_length",
                                    280,
                                )
                            ),
                            endpoint_margin=int(
                                config.get(
                                    "synthetic_rim_bridge_gap_endpoint_margin",
                                    4,
                                )
                            ),
                            line_width=max(
                                1,
                                int(
                                    adaptive_rim_config.get(
                                        "line_width",
                                        config.get(
                                            "observed_rim_fit_line_width",
                                            rim_line_width,
                                        ),
                                    )
                                ),
                            ),
                            maximum_gap_count=int(
                                config.get(
                                    "synthetic_rim_bridge_gap_max_count",
                                    4,
                                )
                            ),
                            maximum_total_gap_fraction=float(
                                config.get(
                                    "synthetic_rim_bridge_gap_max_total_fraction",
                                    0.16,
                                )
                            ),
                            allowed_region=contour_gap_allowed_region,
                        )
                    elif (
                        synthetic_rim_bridge_mode == "observed_gap"
                        and observation_used
                    ):
                        (
                            synthetic_bridge_target,
                            bracketed_gap_metrics,
                        ) = _build_bracketed_rim_gap_target(
                            bridge_source_mask,
                            observed_rim,
                            fitted_rim_fill,
                            bridge_seed,
                            top_ratio=float(
                                config.get("synthetic_rim_bridge_top_ratio", 0.30)
                            ),
                            observed_dilation=int(
                                config.get(
                                    "synthetic_rim_bridge_gap_observed_dilation",
                                    7,
                                )
                            ),
                            anchor_close_kernel=int(
                                config.get(
                                    "synthetic_rim_bridge_gap_anchor_close_kernel",
                                    5,
                                )
                            ),
                            repair_anchor_dilation=int(
                                config.get("synthetic_rim_bridge_dilation", 95)
                            ),
                            minimum_gap_width=int(
                                config.get(
                                    "synthetic_rim_bridge_gap_min_width",
                                    3,
                                )
                            ),
                            maximum_gap_width=int(
                                config.get(
                                    "synthetic_rim_bridge_gap_max_width",
                                    280,
                                )
                            ),
                            endpoint_margin=int(
                                config.get(
                                    "synthetic_rim_bridge_gap_endpoint_margin",
                                    4,
                                )
                            ),
                        )
                    else:
                        synthetic_bridge_target = _connect_top_rim_bridge_target(
                            bridge_source_mask,
                            plate,
                            bridge_seed,
                            top_ratio=float(
                                config.get("synthetic_rim_bridge_top_ratio", 0.30)
                            ),
                            bridge_dilation=int(
                                config.get("synthetic_rim_bridge_dilation", 95)
                            ),
                            horizontal_margin=int(
                                config.get("synthetic_rim_bridge_horizontal_margin", 64)
                            ),
                        )
                        if bool(
                            config.get("synthetic_rim_bridge_connect_full_top", False)
                        ):
                            top_arc = _top_plate_arc_mask(
                                plate,
                                float(
                                    config.get(
                                        "synthetic_rim_bridge_top_ratio",
                                        0.30,
                                    )
                                ),
                            )
                            top_inner_rim = cv2.bitwise_and(
                                bridge_source_mask,
                                top_arc,
                            )
                            if np.any(top_inner_rim) and np.any(
                                synthetic_bridge_target
                            ):
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
                        extra_width = int(
                            config.get("synthetic_rim_bridge_extra_width", 3)
                        )
                        synthetic_bridge_target = cv2.dilate(
                            synthetic_bridge_target,
                            cv2.getStructuringElement(
                                cv2.MORPH_ELLIPSE,
                                (
                                    _odd(extra_width),
                                    _odd(extra_width),
                                ),
                            ),
                        )
                        rim_corridor = cv2.dilate(
                            bridge_source_mask,
                            cv2.getStructuringElement(
                                cv2.MORPH_ELLIPSE,
                                (_odd(extra_width), _odd(extra_width)),
                            ),
                        )
                        synthetic_bridge_target = cv2.bitwise_and(
                            synthetic_bridge_target,
                            rim_corridor,
                        )
                    if not bool(
                        config.get(
                            "synthetic_rim_bridge_allow_food_overlap",
                            False,
                        )
                    ):
                        if bool(
                            config.get(
                                "synthetic_rim_bridge_allow_thin_foreground_overlap",
                                True,
                            )
                        ):
                            thin_radius = max(
                                1,
                                int(
                                    config.get(
                                        "synthetic_rim_bridge_thin_foreground_radius",
                                        4,
                                    )
                                ),
                            )
                            food_distance = cv2.distanceTransform(
                                (food > 0).astype(np.uint8),
                                cv2.DIST_L2,
                                5,
                            )
                            thick_food_core = np.where(
                                food_distance > float(thin_radius),
                                255,
                                0,
                            ).astype(np.uint8)
                            thick_food_protection = cv2.dilate(
                                thick_food_core,
                                cv2.getStructuringElement(
                                    cv2.MORPH_ELLIPSE,
                                    (
                                        _odd(thin_radius * 2 + 1),
                                        _odd(thin_radius * 2 + 1),
                                    ),
                                ),
                            )
                            synthetic_bridge_target = cv2.bitwise_and(
                                synthetic_bridge_target,
                                cv2.bitwise_not(thick_food_protection),
                            )
                        else:
                            synthetic_bridge_target = cv2.bitwise_and(
                                synthetic_bridge_target,
                                cv2.bitwise_not(food),
                            )
                    synthetic_bridge_target = cv2.bitwise_and(
                        synthetic_bridge_target,
                        bridge_support_mask,
                    )
                    synthetic_bridge_target = cv2.bitwise_and(
                        synthetic_bridge_target,
                        cv2.bitwise_not(protected_detail_guard),
                    )
                    bridge_plate_area_ratio = float(
                        np.count_nonzero(synthetic_bridge_target)
                        / max(np.count_nonzero(plate), 1)
                    )
                    maximum_bridge_area_ratio = float(
                        config.get(
                            "synthetic_rim_bridge_max_plate_area_ratio",
                            0.008,
                        )
                    )
                    if bridge_plate_area_ratio > maximum_bridge_area_ratio:
                        synthetic_bridge_target = np.zeros_like(
                            synthetic_bridge_target
                        )
                        synthetic_quality_allowed = False
                        bracketed_gap_metrics = {
                            **bracketed_gap_metrics,
                            "reason": "synthetic_bridge_area_ratio_rejected",
                            "bridge_plate_area_ratio": round(
                                bridge_plate_area_ratio,
                                6,
                            ),
                            "maximum_bridge_plate_area_ratio": (
                                maximum_bridge_area_ratio
                            ),
                        }
                    synthetic_rim_bridge_pixels = int(
                        np.count_nonzero(synthetic_bridge_target)
                    )
                    synthetic_rim_bridge_outside_plate_pixels = int(
                        np.count_nonzero(
                            (synthetic_bridge_target > 0) & (plate == 0)
                        )
                    )
                    if bool(
                        config.get("plate_edge_alpha_extension_enabled", True)
                    ):
                        alpha_extension_mask = cv2.bitwise_and(
                            synthetic_bridge_target,
                            cv2.bitwise_not(plate),
                        )
                    colored_rim_color = adaptive_rim_color
                    if colored_rim_color is not None:
                        synthetic_rim_color_sample_count = int(
                            adaptive_rim_observation_metrics.get(
                                "observed_pixels",
                                0,
                            )
                        )
                    else:
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
                            fitted_rim_fill,
                            float(config.get("synthetic_rim_band_top_ratio", 0.30)),
                        )
                        synthetic_band_target = cv2.bitwise_and(
                            synthetic_band_target,
                            top_arc,
                        )
                        synthetic_band_target = cv2.bitwise_and(
                            synthetic_band_target,
                            bridge_support_mask,
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
                                support_mask=bridge_support_mask,
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
                            support_mask=bridge_support_mask,
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
                    completion_target = cv2.bitwise_and(
                        completion_target,
                        cv2.bitwise_not(protected_detail_guard),
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
                            support_mask=plate,
                        )
                        repair_mask = cv2.bitwise_or(repair_mask, completion_target)

    if np.any(observed_source_rim_mask):
        repaired = _restore_source_pixels(
            repaired,
            source_image,
            observed_source_rim_mask,
            feather_kernel=int(
                config.get("observed_source_rim_feather_kernel", 3)
            ),
        )
        repair_mask = cv2.bitwise_or(repair_mask, observed_source_rim_mask)
        if bool(config.get("plate_edge_alpha_extension_enabled", True)):
            alpha_extension_mask = cv2.bitwise_or(
                alpha_extension_mask,
                cv2.bitwise_and(
                    observed_source_rim_mask,
                    cv2.bitwise_not(plate),
                ),
            )
    if np.any(protected_detail):
        repaired = _restore_source_pixels(
            repaired,
            source_image,
            protected_detail,
            feather_kernel=int(
                config.get("protected_detail_feather_kernel", 3)
            ),
        )

    return PlateEdgeRepairResult(
        image=repaired,
        mask=repair_mask,
        alpha_extension_mask=alpha_extension_mask,
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
            "synthetic_rim_bridge_mode": synthetic_rim_bridge_mode,
            "synthetic_rim_bridge_outside_plate_pixels": (
                synthetic_rim_bridge_outside_plate_pixels
            ),
            "synthetic_rim_band_pixels": synthetic_rim_band_pixels,
            "synthetic_rim_color_sample_count": synthetic_rim_color_sample_count,
            "observed_rim_fit": observed_rim_fit_metrics,
            "adaptive_rim_observation": adaptive_rim_observation_metrics,
            "observed_source_rim_pixels": int(
                np.count_nonzero(observed_source_rim_mask)
            ),
            "observed_source_rim_outside_plate_pixels": int(
                np.count_nonzero(
                    (observed_source_rim_mask > 0) & (plate == 0)
                )
            ),
            "bracketed_rim_gap": bracketed_gap_metrics,
            "shape_type": resolved_shape_type,
            "quality_gate_enabled": quality_gate_enabled,
            "plate_quality_passed": plate_quality_passed,
            "food_quality_passed": food_quality_passed,
            "synthetic_rim_allowed": synthetic_quality_allowed,
            "alpha_extension_pixels": int(np.count_nonzero(alpha_extension_mask)),
            "protected_detail_pixels": int(np.count_nonzero(protected_detail)),
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
