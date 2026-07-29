from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import cv2
import numpy as np


@dataclass(frozen=True, slots=True)
class RimObservationResult:
    line_mask: np.ndarray
    observed_mask: np.ndarray
    fill_mask: np.ndarray
    color_bgr: np.ndarray | None
    confidence: float
    metrics: dict[str, float | int | bool | str | list[float]]


def _odd(value: int) -> int:
    value = max(1, int(value))
    return value if value % 2 else value + 1


def _largest_contour(mask: np.ndarray) -> np.ndarray | None:
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    return max(contours, key=cv2.contourArea) if contours else None


def _expected_contour(
    plate: np.ndarray,
    shape_type: str,
    thickness: int,
) -> tuple[np.ndarray, np.ndarray]:
    contour = _largest_contour(plate)
    line = np.zeros_like(plate)
    fill = np.zeros_like(plate)
    if contour is None:
        return line, fill
    if shape_type == "ellipse" and len(contour) >= 5:
        ellipse = cv2.fitEllipse(contour)
        cv2.ellipse(line, ellipse, 255, max(1, int(thickness)))
        cv2.ellipse(fill, ellipse, 255, -1)
    else:
        cv2.drawContours(line, [contour], -1, 255, max(1, int(thickness)))
        cv2.drawContours(fill, [contour], -1, 255, -1)
    return line, fill


def _cluster_candidate_colors(
    image_bgr: np.ndarray,
    candidate: np.ndarray,
    cluster_count: int,
) -> list[tuple[np.ndarray, np.ndarray]]:
    ys, xs = np.where(candidate > 0)
    if len(xs) < 5:
        return []
    lab = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2LAB)
    samples = lab[ys, xs].astype(np.float32)
    clusters = max(1, min(int(cluster_count), len(samples)))
    cv2.setRNGSeed(0)
    _, labels, _ = cv2.kmeans(
        samples,
        clusters,
        None,
        (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 0.25),
        5,
        cv2.KMEANS_PP_CENTERS,
    )
    results: list[tuple[np.ndarray, np.ndarray]] = []
    for cluster_id in range(clusters):
        selected = labels.reshape(-1) == cluster_id
        if not np.any(selected):
            continue
        mask = np.zeros(candidate.shape, np.uint8)
        mask[ys[selected], xs[selected]] = 255
        color = np.median(image_bgr[ys[selected], xs[selected]], axis=0).astype(
            np.uint8
        )
        results.append((mask, color))
    return results


def observe_container_rim(
    image_bgr: np.ndarray,
    plate_mask: np.ndarray,
    food_mask: np.ndarray,
    *,
    shape_type: str,
    config: dict[str, Any],
) -> RimObservationResult:
    if image_bgr.ndim != 3 or plate_mask.ndim != 2 or food_mask.ndim != 2:
        raise ValueError("image_bgr must be BGR and masks must be single-channel")
    if image_bgr.shape[:2] != plate_mask.shape or plate_mask.shape != food_mask.shape:
        raise ValueError("image and masks must have matching height and width")

    plate = np.where(plate_mask >= 128, 255, 0).astype(np.uint8)
    food = np.where(food_mask >= 128, 255, 0).astype(np.uint8)
    empty = np.zeros_like(plate)
    if not np.any(plate):
        return RimObservationResult(
            empty,
            empty,
            empty,
            None,
            0.0,
            {"used": False, "reason": "empty_plate_mask", "confidence": 0.0},
        )

    thickness = max(1, int(config.get("line_width", 5)))
    base_line, base_fill = _expected_contour(plate, shape_type, thickness)
    guard_px = max(0, int(config.get("plate_guard_dilation", 12)))
    guard = (
        cv2.dilate(
            plate,
            cv2.getStructuringElement(
                cv2.MORPH_ELLIPSE,
                (_odd(guard_px * 2 + 1), _odd(guard_px * 2 + 1)),
            ),
        )
        if guard_px
        else plate
    )
    boundary_width = max(2, int(config.get("boundary_width", 48)))
    inner = cv2.erode(
        plate,
        cv2.getStructuringElement(
            cv2.MORPH_ELLIPSE,
            (_odd(boundary_width * 2 + 1), _odd(boundary_width * 2 + 1)),
        ),
    )
    boundary_band = cv2.bitwise_and(guard, cv2.bitwise_not(inner))

    gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
    grad_x = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
    grad_y = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
    gradient = cv2.magnitude(grad_x, grad_y)
    valid_values = gradient[boundary_band > 0]
    if valid_values.size == 0:
        return RimObservationResult(
            base_line,
            empty,
            base_fill,
            None,
            0.0,
            {"used": False, "reason": "empty_boundary_band", "confidence": 0.0},
        )
    percentile = float(config.get("gradient_percentile", 68.0))
    minimum_gradient = float(config.get("minimum_gradient", 18.0))
    gradient_threshold = max(
        minimum_gradient, float(np.percentile(valid_values, percentile))
    )
    candidate = np.where(
        (boundary_band > 0) & (gradient >= gradient_threshold), 255, 0
    ).astype(np.uint8)

    food_core_erosion = max(0, int(config.get("food_core_erosion", 9)))
    if food_core_erosion:
        food_core = cv2.erode(
            food,
            cv2.getStructuringElement(
                cv2.MORPH_ELLIPSE,
                (_odd(food_core_erosion * 2 + 1), _odd(food_core_erosion * 2 + 1)),
            ),
        )
        candidate = cv2.bitwise_and(candidate, cv2.bitwise_not(food_core))

    clusters = _cluster_candidate_colors(
        image_bgr,
        candidate,
        int(config.get("color_cluster_count", 4)),
    )
    minimum_pixels = max(5, int(config.get("minimum_observed_pixels", 96)))
    observed_dilation = _odd(int(config.get("observed_dilation", 7)))
    expected_dilation = _odd(int(config.get("expected_line_dilation", 15)))
    expected_near = cv2.dilate(
        base_line,
        cv2.getStructuringElement(
            cv2.MORPH_ELLIPSE, (expected_dilation, expected_dilation)
        ),
    )
    plate_area = float(np.count_nonzero(plate))
    plate_contour = _largest_contour(plate)
    plate_center = None
    plate_axes = None
    if plate_contour is not None and len(plate_contour) >= 5:
        plate_ellipse = cv2.fitEllipse(plate_contour)
        plate_center = plate_ellipse[0]
        plate_axes = plate_ellipse[1]
    interior_sample = cv2.erode(
        plate,
        cv2.getStructuringElement(
            cv2.MORPH_ELLIPSE,
            (_odd(max(3, boundary_width // 2)), _odd(max(3, boundary_width // 2))),
        ),
    )
    interior_sample = cv2.bitwise_and(interior_sample, cv2.bitwise_not(food))
    if not np.any(interior_sample):
        interior_sample = cv2.bitwise_and(plate, cv2.bitwise_not(food))
    interior_lab = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2LAB)[
        interior_sample > 0
    ]
    interior_color_lab = (
        np.median(interior_lab, axis=0).astype(np.float32)
        if len(interior_lab)
        else None
    )

    best: tuple[
        float, np.ndarray, np.ndarray, np.ndarray, np.ndarray, dict[str, float | int]
    ] | None = None
    for cluster_mask, cluster_color in clusters:
        cluster_mask = cv2.bitwise_and(cluster_mask, expected_near)
        ys, xs = np.where(cluster_mask > 0)
        if len(xs) < minimum_pixels:
            continue

        line = base_line.copy()
        fill = base_fill.copy()
        fit_metrics: dict[str, float | int] = {}
        if shape_type == "ellipse" and len(xs) >= 5:
            points = np.column_stack((xs, ys)).astype(np.float32).reshape(-1, 1, 2)
            ellipse = cv2.fitEllipse(points)
            (center_x, center_y), (axis_a, axis_b), _ = ellipse
            aspect_ratio = max(axis_a, axis_b) / max(min(axis_a, axis_b), 1.0)
            area_ratio = (
                float(np.pi * axis_a * axis_b * 0.25) / max(plate_area, 1.0)
            )
            center_shift = 0.0
            if plate_center is not None and plate_axes is not None:
                center_shift = float(
                    np.hypot(center_x - plate_center[0], center_y - plate_center[1])
                    / max(plate_axes[0], plate_axes[1], 1.0)
                )
            if aspect_ratio > float(config.get("maximum_ellipse_aspect_ratio", 2.2)):
                continue
            if not float(config.get("minimum_ellipse_area_ratio", 0.45)) <= area_ratio <= float(
                config.get("maximum_ellipse_area_ratio", 1.20)
            ):
                continue
            if center_shift > float(config.get("maximum_center_shift_ratio", 0.12)):
                continue
            line = np.zeros_like(plate)
            fill = np.zeros_like(plate)
            cv2.ellipse(line, ellipse, 255, thickness)
            cv2.ellipse(fill, ellipse, 255, -1)
            line = cv2.bitwise_and(line, guard)
            fill = cv2.bitwise_and(fill, guard)
            fit_metrics = {
                "ellipse_aspect_ratio": round(float(aspect_ratio), 6),
                "ellipse_area_ratio": round(float(area_ratio), 6),
                "center_shift_ratio": round(float(center_shift), 6),
            }

        observed_near = cv2.dilate(
            cluster_mask,
            cv2.getStructuringElement(
                cv2.MORPH_ELLIPSE, (observed_dilation, observed_dilation)
            ),
        )
        line_pixels = int(np.count_nonzero(line))
        overlap_pixels = int(np.count_nonzero(cv2.bitwise_and(line, observed_near)))
        overlap_ratio = overlap_pixels / max(line_pixels, 1)
        x_span = (int(xs.max()) - int(xs.min()) + 1) / max(image_bgr.shape[1], 1)
        y_span = (int(ys.max()) - int(ys.min()) + 1) / max(image_bgr.shape[0], 1)
        spatial_span = min(1.0, x_span + y_span)
        pixel_score = min(1.0, len(xs) / max(minimum_pixels * 4, 1))
        color_contrast = 0.0
        colorfulness = float(
            cv2.cvtColor(
                cluster_color.reshape(1, 1, 3),
                cv2.COLOR_BGR2HSV,
            )[0, 0, 1]
            / 255.0
        )
        if interior_color_lab is not None:
            cluster_lab = cv2.cvtColor(
                cluster_color.reshape(1, 1, 3),
                cv2.COLOR_BGR2LAB,
            )[0, 0].astype(np.float32)
            color_contrast = min(
                1.0,
                float(np.linalg.norm(cluster_lab - interior_color_lab))
                / max(float(config.get("color_contrast_scale", 90.0)), 1.0),
            )
        score = float(
            0.42 * overlap_ratio
            + 0.16 * spatial_span
            + 0.08 * pixel_score
            + 0.22 * color_contrast
            + 0.12 * colorfulness
        )
        metrics = {
            "observed_pixels": int(len(xs)),
            "line_pixels": line_pixels,
            "overlap_pixels": overlap_pixels,
            "overlap_ratio": round(float(overlap_ratio), 6),
            "spatial_span": round(float(spatial_span), 6),
            "color_contrast": round(float(color_contrast), 6),
            "colorfulness": round(colorfulness, 6),
            **fit_metrics,
        }
        if best is None or score > best[0]:
            best = (score, line, cluster_mask, fill, cluster_color, metrics)

    if best is None:
        return RimObservationResult(
            base_line,
            empty,
            base_fill,
            None,
            0.0,
            {
                "used": False,
                "reason": "no_stable_boundary_color_cluster",
                "confidence": 0.0,
                "gradient_threshold": round(gradient_threshold, 3),
                "candidate_pixels": int(np.count_nonzero(candidate)),
                "cluster_count": len(clusters),
                "shape_type": shape_type,
            },
        )

    score, line, observed, fill, color, fit_metrics = best
    minimum_confidence = float(config.get("minimum_confidence", 0.58))
    used = score >= minimum_confidence
    metrics: dict[str, float | int | bool | str | list[float]] = {
        "used": bool(used),
        "reason": (
            "adaptive_boundary_observation_accepted"
            if used
            else "adaptive_boundary_confidence_too_low"
        ),
        "confidence": round(score, 6),
        "minimum_confidence": minimum_confidence,
        "gradient_threshold": round(gradient_threshold, 3),
        "candidate_pixels": int(np.count_nonzero(candidate)),
        "cluster_count": len(clusters),
        "shape_type": shape_type,
        "representative_color_bgr": [int(value) for value in color],
        **fit_metrics,
    }
    return RimObservationResult(
        line,
        observed,
        fill,
        color,
        score,
        metrics,
    )
