from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

import cv2
import numpy as np


@dataclass(frozen=True, slots=True)
class FoodSupportRecoveryResult:
    mask: np.ndarray
    metrics: dict[str, float | int | bool | str]


def _odd(value: int) -> int:
    value = max(1, int(value))
    return value if value % 2 else value + 1


def _binary(mask: np.ndarray) -> np.ndarray:
    return np.where(mask >= 128, 255, 0).astype(np.uint8)


def _line_samples(
    start_x: int,
    start_y: int,
    end_x: int,
    end_y: int,
) -> tuple[np.ndarray, np.ndarray]:
    sample_count = max(abs(end_x - start_x), abs(end_y - start_y)) + 1
    xs = np.rint(np.linspace(start_x, end_x, sample_count)).astype(np.int32)
    ys = np.rint(np.linspace(start_y, end_y, sample_count)).astype(np.int32)
    return xs, ys


def _segment_matches_continuation(
    anchor: tuple[int, int, int, int],
    candidate: tuple[int, int, int, int],
    *,
    maximum_angle_degrees: float,
    maximum_axis_distance: float,
    maximum_gap: float,
) -> bool:
    ax1, ay1, ax2, ay2 = anchor
    bx1, by1, bx2, by2 = candidate
    anchor_vector = np.array([ax2 - ax1, ay2 - ay1], dtype=np.float32)
    candidate_vector = np.array([bx2 - bx1, by2 - by1], dtype=np.float32)
    anchor_length = float(np.linalg.norm(anchor_vector))
    candidate_length = float(np.linalg.norm(candidate_vector))
    if anchor_length < 1.0 or candidate_length < 1.0:
        return False

    anchor_unit = anchor_vector / anchor_length
    candidate_unit = candidate_vector / candidate_length
    cosine = float(np.clip(abs(np.dot(anchor_unit, candidate_unit)), 0.0, 1.0))
    angle = float(np.degrees(np.arccos(cosine)))
    if angle > maximum_angle_degrees:
        return False

    anchor_start = np.array([ax1, ay1], dtype=np.float32)
    candidate_points = np.array([[bx1, by1], [bx2, by2]], dtype=np.float32)
    offsets = candidate_points - anchor_start
    axis_distances = np.abs(
        offsets[:, 0] * anchor_unit[1] - offsets[:, 1] * anchor_unit[0]
    )
    if float(axis_distances.min()) > maximum_axis_distance:
        return False

    projections = offsets @ anchor_unit
    candidate_min = float(projections.min())
    candidate_max = float(projections.max())
    if candidate_max < 0.0:
        gap = -candidate_max
    elif candidate_min > anchor_length:
        gap = candidate_min - anchor_length
    else:
        gap = 0.0
    return gap <= maximum_gap


def _refine_component_with_grabcut(
    image_bgr: np.ndarray,
    component: np.ndarray,
    line_votes: np.ndarray,
    candidate_scoring_mask: np.ndarray,
    *,
    minimum_line_votes: int,
    config: dict[str, Any],
) -> tuple[np.ndarray, bool]:
    component_mask = np.where(component, 255, 0).astype(np.uint8)
    if not bool(config.get("grabcut_refinement_enabled", True)):
        return component_mask, False

    x, y, width, height = cv2.boundingRect(component_mask)
    padding = max(3, int(config.get("grabcut_padding", 9)))
    x0 = max(0, x - padding)
    y0 = max(0, y - padding)
    x1 = min(component_mask.shape[1], x + width + padding)
    y1 = min(component_mask.shape[0], y + height + padding)
    component_roi = component_mask[y0:y1, x0:x1]
    component_pixels = int(np.count_nonzero(component_roi))
    if component_pixels < max(8, int(config.get("grabcut_minimum_pixels", 24))):
        return component_mask, False

    allowed_dilation = _odd(
        int(config.get("grabcut_allowed_dilation", 5))
    )
    allowed = cv2.dilate(
        component_roi,
        cv2.getStructuringElement(
            cv2.MORPH_ELLIPSE,
            (allowed_dilation, allowed_dilation),
        ),
    )
    grabcut_mask = np.full(component_roi.shape, cv2.GC_BGD, np.uint8)
    grabcut_mask[allowed > 0] = cv2.GC_PR_BGD
    grabcut_mask[component_roi > 0] = cv2.GC_PR_FGD

    strong_vote_threshold = max(
        minimum_line_votes + 1,
        int(config.get("grabcut_strong_vote_threshold", 5)),
    )
    strong_seed = (
        (component_roi > 0)
        & (
            line_votes[y0:y1, x0:x1]
            >= strong_vote_threshold
        )
        & (candidate_scoring_mask[y0:y1, x0:x1] > 0)
    )
    minimum_seed_pixels = max(
        4,
        int(config.get("grabcut_minimum_seed_pixels", 8)),
    )
    if int(np.count_nonzero(strong_seed)) < minimum_seed_pixels:
        return component_mask, False
    grabcut_mask[strong_seed] = cv2.GC_FGD

    background_model = np.zeros((1, 65), np.float64)
    foreground_model = np.zeros((1, 65), np.float64)
    try:
        cv2.grabCut(
            image_bgr[y0:y1, x0:x1],
            grabcut_mask,
            None,
            background_model,
            foreground_model,
            max(1, int(config.get("grabcut_iterations", 2))),
            cv2.GC_INIT_WITH_MASK,
        )
    except cv2.error:
        return component_mask, False

    refined_roi = np.where(
        (
            (grabcut_mask == cv2.GC_FGD)
            | (grabcut_mask == cv2.GC_PR_FGD)
        )
        & (allowed > 0),
        255,
        0,
    ).astype(np.uint8)
    preserve_vote_threshold = max(
        strong_vote_threshold,
        int(config.get("grabcut_preserve_vote_threshold", 6)),
    )
    high_confidence_geometry = np.where(
        (component_roi > 0)
        & (
            line_votes[y0:y1, x0:x1]
            >= preserve_vote_threshold
        ),
        255,
        0,
    ).astype(np.uint8)
    refined_roi = cv2.bitwise_or(
        refined_roi,
        high_confidence_geometry,
    )
    refined_pixels = int(np.count_nonzero(refined_roi))
    minimum_retained_ratio = float(
        config.get("grabcut_minimum_retained_ratio", 0.25)
    )
    maximum_growth_ratio = float(
        config.get("grabcut_maximum_growth_ratio", 1.20)
    )
    if not (
        component_pixels * minimum_retained_ratio
        <= refined_pixels
        <= component_pixels * maximum_growth_ratio
    ):
        return component_mask, False

    refined = np.zeros_like(component_mask)
    refined[y0:y1, x0:x1] = refined_roi
    return refined, True


def recover_food_supports(
    image_bgr: np.ndarray,
    plate_mask: np.ndarray,
    base_food_mask: np.ndarray,
    candidate_masks: Iterable[np.ndarray | None],
    config: dict[str, Any],
) -> FoodSupportRecoveryResult:
    """Recover thin food supports that cross the serving-container boundary.

    SAM food masks often lose wooden skewer tips because most of the detected
    object is inside the plate. A Hough segment must cross the plate boundary
    before collinear exterior segments can be added. Raw SAM/HQ-SAM masks are
    optional silhouette evidence, so a missed skewer tip can still be recovered.
    Detached cutlery does not qualify merely for being long and thin.
    """

    empty = np.zeros(plate_mask.shape[:2], dtype=np.uint8)
    if not bool(config.get("enabled", True)):
        return FoodSupportRecoveryResult(
            empty,
            {"status": "disabled", "applied": False},
        )
    if image_bgr.ndim != 3 or plate_mask.ndim != 2 or base_food_mask.ndim != 2:
        raise ValueError("image_bgr must be BGR and masks must be single-channel")
    if image_bgr.shape[:2] != plate_mask.shape or plate_mask.shape != base_food_mask.shape:
        raise ValueError("image and masks must have matching height and width")

    plate = _binary(plate_mask)
    base_food = _binary(base_food_mask)
    if not np.any(plate):
        return FoodSupportRecoveryResult(
            empty,
            {"status": "empty_plate_mask", "applied": False},
        )

    candidate = np.zeros_like(plate)
    candidate_count = 0
    for mask in candidate_masks:
        if mask is None or mask.shape != plate.shape or not np.any(mask):
            continue
        candidate = cv2.bitwise_or(candidate, _binary(mask))
        candidate_count += 1
    plate_area = float(np.count_nonzero(plate))
    equivalent_diameter = max(1.0, float(np.sqrt(4.0 * plate_area / np.pi)))
    outside_distance = max(
        6,
        int(
            round(
                equivalent_diameter
                * float(config.get("maximum_outside_distance_ratio", 0.30))
            )
        ),
    )
    inside_depth = max(
        4,
        int(
            round(
                equivalent_diameter
                * float(config.get("inside_anchor_depth_ratio", 0.18))
            )
        ),
    )
    outside_distance_map = cv2.distanceTransform(
        (plate == 0).astype(np.uint8),
        cv2.DIST_L2,
        5,
    )
    inside_distance_map = cv2.distanceTransform(
        (plate > 0).astype(np.uint8),
        cv2.DIST_L2,
        5,
    )
    outside_guard = np.where(
        (plate > 0) | (outside_distance_map <= outside_distance),
        255,
        0,
    ).astype(np.uint8)
    search_band = np.where(
        ((plate == 0) & (outside_distance_map <= outside_distance))
        | ((plate > 0) & (inside_distance_map <= inside_depth)),
        255,
        0,
    ).astype(np.uint8)

    gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (3, 3), 0)
    canny_low = int(config.get("canny_low", 35))
    canny_high = int(config.get("canny_high", 120))
    edges = cv2.Canny(gray, canny_low, canny_high)
    edges = cv2.bitwise_and(edges, search_band)

    minimum_line_length = max(
        12,
        int(
            round(
                equivalent_diameter
                * float(config.get("minimum_line_length_ratio", 0.045))
            )
        ),
    )
    maximum_line_length = max(
        minimum_line_length,
        int(
            round(
                equivalent_diameter
                * float(config.get("maximum_line_length_ratio", 0.55))
            )
        ),
    )
    lines = cv2.HoughLinesP(
        edges,
        1,
        np.pi / 360.0,
        threshold=max(8, int(config.get("hough_threshold", 22))),
        minLineLength=minimum_line_length,
        maxLineGap=max(
            2,
            int(
                round(
                    equivalent_diameter
                    * float(config.get("maximum_line_gap_ratio", 0.018))
                )
            ),
        ),
    )
    if lines is None:
        return FoodSupportRecoveryResult(
            empty,
            {
                "status": "no_line_candidates",
                "applied": False,
                "candidate_mask_count": candidate_count,
            },
        )

    corridor_width = max(
        3,
        int(
            round(
                equivalent_diameter
                * float(config.get("corridor_width_ratio", 0.014))
            )
        ),
    )
    minimum_inside_samples = max(2, int(config.get("minimum_inside_samples", 4)))
    minimum_outside_samples = max(2, int(config.get("minimum_outside_samples", 5)))
    minimum_radial_alignment = float(
        config.get("minimum_radial_alignment", 0.35)
    )
    moments = cv2.moments(plate, binaryImage=True)
    center_x = float(moments["m10"] / max(moments["m00"], 1.0))
    center_y = float(moments["m01"] / max(moments["m00"], 1.0))
    anchor_probe_extension = max(
        2,
        int(
            round(
                equivalent_diameter
                * float(config.get("anchor_probe_extension_ratio", 0.08))
            )
        ),
    )
    all_segments: list[tuple[int, int, int, int]] = []
    anchor_indices: set[int] = set()

    line_values = np.asarray(lines)
    if line_values.size % 4 != 0:
        return FoodSupportRecoveryResult(
            mask=empty,
            metrics={
                "enabled": True,
                "applied": False,
                "reason": "invalid_hough_line_shape",
                "hough_line_shape": list(line_values.shape),
            },
        )
    normalized_lines = line_values.reshape(-1, 4)

    for raw_line in normalized_lines:
        start_x, start_y, end_x, end_y = (int(value) for value in raw_line)
        length = float(np.hypot(end_x - start_x, end_y - start_y))
        if not minimum_line_length <= length <= maximum_line_length:
            continue
        segment = (start_x, start_y, end_x, end_y)
        segment_index = len(all_segments)
        all_segments.append(segment)

        unit_x = (end_x - start_x) / max(length, 1.0)
        unit_y = (end_y - start_y) / max(length, 1.0)
        probe_start_x = int(
            round(start_x - unit_x * anchor_probe_extension)
        )
        probe_start_y = int(
            round(start_y - unit_y * anchor_probe_extension)
        )
        probe_end_x = int(
            round(end_x + unit_x * anchor_probe_extension)
        )
        probe_end_y = int(
            round(end_y + unit_y * anchor_probe_extension)
        )
        xs, ys = _line_samples(
            probe_start_x,
            probe_start_y,
            probe_end_x,
            probe_end_y,
        )
        valid = (
            (xs >= 0)
            & (xs < plate.shape[1])
            & (ys >= 0)
            & (ys < plate.shape[0])
        )
        xs, ys = xs[valid], ys[valid]
        if len(xs) < minimum_inside_samples + minimum_outside_samples:
            continue
        inside = plate[ys, xs] > 0
        if (
            int(np.count_nonzero(inside)) < minimum_inside_samples
            or int(np.count_nonzero(~inside)) < minimum_outside_samples
        ):
            continue

        transitions = np.flatnonzero(inside[:-1] != inside[1:])
        if not len(transitions):
            continue
        transition = int(
            transitions[np.argmin(np.abs(transitions - len(xs) // 2))]
        )
        boundary_x = float(xs[transition])
        boundary_y = float(ys[transition])
        normal_x = boundary_x - center_x
        normal_y = boundary_y - center_y
        normal_length = max(1.0, float(np.hypot(normal_x, normal_y)))
        radial_alignment = abs(
            unit_x * normal_x / normal_length
            + unit_y * normal_y / normal_length
        )
        if radial_alignment < minimum_radial_alignment:
            continue
        anchor_indices.add(segment_index)

    if not anchor_indices:
        return FoodSupportRecoveryResult(
            empty,
            {
                "status": "no_boundary_crossing_lines",
                "applied": False,
                "candidate_mask_count": candidate_count,
                "line_candidates": int(len(lines)),
            },
        )

    selected_indices = set(anchor_indices)
    continuation_angle = float(
        config.get("continuation_maximum_angle_degrees", 8.0)
    )
    continuation_axis_distance = max(
        2.0,
        equivalent_diameter
        * float(config.get("continuation_axis_distance_ratio", 0.015)),
    )
    continuation_gap = max(
        3.0,
        equivalent_diameter
        * float(config.get("continuation_maximum_gap_ratio", 0.12)),
    )
    continuation_passes = max(1, int(config.get("continuation_passes", 2)))
    for _ in range(continuation_passes):
        added: set[int] = set()
        for candidate_index, candidate_segment in enumerate(all_segments):
            if candidate_index in selected_indices:
                continue
            xs, ys = _line_samples(*candidate_segment)
            valid = (
                (xs >= 0)
                & (xs < plate.shape[1])
                & (ys >= 0)
                & (ys < plate.shape[0])
            )
            xs, ys = xs[valid], ys[valid]
            if not len(xs) or not np.any(plate[ys, xs] == 0):
                continue
            if any(
                _segment_matches_continuation(
                    all_segments[selected_index],
                    candidate_segment,
                    maximum_angle_degrees=continuation_angle,
                    maximum_axis_distance=continuation_axis_distance,
                    maximum_gap=continuation_gap,
                )
                for selected_index in selected_indices
            ):
                added.add(candidate_index)
        if not added:
            break
        selected_indices.update(added)

    line_votes = np.zeros_like(plate, dtype=np.uint16)
    for selected_index in selected_indices:
        start_x, start_y, end_x, end_y = all_segments[selected_index]
        if selected_index in anchor_indices:
            length = max(
                1.0,
                float(np.hypot(end_x - start_x, end_y - start_y)),
            )
            unit_x = (end_x - start_x) / length
            unit_y = (end_y - start_y) / length
            start_x = int(
                round(start_x - unit_x * anchor_probe_extension)
            )
            start_y = int(
                round(start_y - unit_y * anchor_probe_extension)
            )
            end_x = int(
                round(end_x + unit_x * anchor_probe_extension)
            )
            end_y = int(
                round(end_y + unit_y * anchor_probe_extension)
            )
        line_mask = np.zeros_like(plate)
        cv2.line(
            line_mask,
            (start_x, start_y),
            (end_x, end_y),
            255,
            thickness=corridor_width,
            lineType=cv2.LINE_AA,
        )
        line_votes += (line_mask > 0).astype(np.uint16)

    minimum_line_votes = max(1, int(config.get("minimum_line_votes", 1)))
    recovered = np.where(
        (line_votes >= minimum_line_votes) & (search_band > 0),
        255,
        0,
    ).astype(np.uint8)
    candidate_dilation = _odd(int(config.get("candidate_dilation", 5)))
    candidate_scoring_mask = (
        cv2.dilate(
            candidate,
            cv2.getStructuringElement(
                cv2.MORPH_ELLIPSE,
                (candidate_dilation, candidate_dilation),
            ),
        )
        if np.any(candidate)
        else candidate
    )
    if np.any(candidate) and bool(
        config.get("expand_with_candidate_mask", False)
    ):
        geometry_guard = cv2.dilate(
            recovered,
            cv2.getStructuringElement(
                cv2.MORPH_ELLIPSE,
                (candidate_dilation, candidate_dilation),
            ),
        )
        recovered = cv2.bitwise_or(
            recovered,
            cv2.bitwise_and(candidate, geometry_guard),
        )

    food_guard_size = _odd(int(config.get("base_food_guard_dilation", 5)))
    food_guard = cv2.dilate(
        base_food,
        cv2.getStructuringElement(
            cv2.MORPH_ELLIPSE,
            (food_guard_size, food_guard_size),
        ),
    )
    recovered = cv2.bitwise_and(recovered, cv2.bitwise_not(food_guard))
    recovered = cv2.bitwise_and(recovered, outside_guard)
    recovered = cv2.morphologyEx(
        recovered,
        cv2.MORPH_CLOSE,
        np.ones((3, 3), np.uint8),
    )
    if not np.any(recovered):
        return FoodSupportRecoveryResult(
            empty,
            {
                "status": "no_exterior_support_pixels",
                "applied": False,
                "candidate_mask_count": candidate_count,
                "line_candidates": int(len(lines)),
                "boundary_crossing_lines": len(anchor_indices),
                "selected_lines": len(selected_indices),
            },
        )

    attachment_guard = cv2.dilate(
        plate,
        cv2.getStructuringElement(
            cv2.MORPH_ELLIPSE,
            (
                _odd(int(config.get("attachment_guard_dilation", 11))),
                _odd(int(config.get("attachment_guard_dilation", 11))),
            ),
        ),
    )
    component_count, labels, stats, _ = cv2.connectedComponentsWithStats(
        (recovered > 0).astype(np.uint8),
        connectivity=8,
    )
    filtered = np.zeros_like(recovered)
    minimum_component_area = max(3, int(config.get("minimum_component_area", 12)))
    maximum_component_area = max(
        minimum_component_area,
        int(
            round(
                plate_area * float(config.get("maximum_component_plate_area_ratio", 0.012))
            )
        ),
    )
    minimum_outside_reach = max(
        3.0,
        equivalent_diameter
        * float(config.get("minimum_outside_reach_ratio", 0.045)),
    )
    minimum_component_aspect_ratio = max(
        1.0,
        float(config.get("minimum_component_aspect_ratio", 1.45)),
    )
    minimum_candidate_overlap = max(
        0.0,
        float(config.get("minimum_component_candidate_overlap", 0.05)),
    )
    geometry_only_minimum_reach = max(
        minimum_outside_reach,
        equivalent_diameter
        * float(
            config.get(
                "geometry_only_minimum_outside_reach_ratio",
                0.10,
            )
        ),
    )
    geometry_only_minimum_peak_votes = max(
        1,
        int(config.get("geometry_only_minimum_peak_line_votes", 3)),
    )
    allow_geometry_only = bool(config.get("allow_geometry_only", False))
    kept_components = 0
    candidate_supported_components = 0
    geometry_only_components = 0
    grabcut_refined_components = 0
    component_rejections = {
        "area": 0,
        "attachment": 0,
        "outside": 0,
        "reach": 0,
        "aspect": 0,
        "evidence": 0,
    }
    for component_id in range(1, component_count):
        component = labels == component_id
        area = int(stats[component_id, cv2.CC_STAT_AREA])
        if not minimum_component_area <= area <= maximum_component_area:
            component_rejections["area"] += 1
            continue
        if not np.any(attachment_guard[component]):
            component_rejections["attachment"] += 1
            continue
        if not np.any((plate == 0) & component):
            component_rejections["outside"] += 1
            continue
        component_outside_reach = float(
            outside_distance_map[component].max()
        )
        if component_outside_reach < minimum_outside_reach:
            component_rejections["reach"] += 1
            continue
        points = np.column_stack(np.where(component)[::-1]).astype(np.float32)
        _, (component_width, component_height), _ = cv2.minAreaRect(points)
        component_major = max(component_width, component_height)
        component_minor = max(1.0, min(component_width, component_height))
        if component_major / component_minor < minimum_component_aspect_ratio:
            component_rejections["aspect"] += 1
            continue
        candidate_overlap = (
            float(
                np.count_nonzero(
                    (candidate_scoring_mask > 0) & component
                )
                / area
            )
            if np.any(candidate)
            else 0.0
        )
        candidate_supported = candidate_overlap >= minimum_candidate_overlap
        geometry_only_supported = (
            allow_geometry_only
            and component_outside_reach >= geometry_only_minimum_reach
            and int(line_votes[component].max())
            >= geometry_only_minimum_peak_votes
        )
        if not candidate_supported and not geometry_only_supported:
            component_rejections["evidence"] += 1
            continue
        refined_component, was_refined = _refine_component_with_grabcut(
            image_bgr,
            component,
            line_votes,
            candidate_scoring_mask,
            minimum_line_votes=minimum_line_votes,
            config=config,
        )
        filtered[refined_component > 0] = 255
        kept_components += 1
        grabcut_refined_components += int(was_refined)
        candidate_supported_components += int(candidate_supported)
        geometry_only_components += int(
            geometry_only_supported and not candidate_supported
        )

    outside_pixels = int(
        np.count_nonzero((filtered > 0) & (plate == 0))
    )
    recovered_pixels = int(np.count_nonzero(filtered))
    maximum_total_area = max(
        1,
        int(
            round(
                plate_area * float(config.get("maximum_total_plate_area_ratio", 0.02))
            )
        ),
    )
    if recovered_pixels > maximum_total_area:
        return FoodSupportRecoveryResult(
            empty,
            {
                "status": "area_limit_rejected",
                "applied": False,
                "candidate_mask_count": candidate_count,
                "line_candidates": int(len(lines)),
                "boundary_crossing_lines": len(anchor_indices),
                "selected_lines": len(selected_indices),
                "recovered_pixels": recovered_pixels,
                "maximum_total_pixels": maximum_total_area,
            },
        )

    return FoodSupportRecoveryResult(
        filtered,
        {
            "status": "completed",
            "applied": bool(recovered_pixels),
            "candidate_mask_count": candidate_count,
            "line_candidates": int(len(lines)),
            "boundary_crossing_lines": len(anchor_indices),
            "selected_lines": len(selected_indices),
            "kept_components": kept_components,
            "candidate_supported_components": candidate_supported_components,
            "geometry_only_components": geometry_only_components,
            "grabcut_refined_components": grabcut_refined_components,
            **{
                f"rejected_{reason}_components": count
                for reason, count in component_rejections.items()
            },
            "recovered_pixels": recovered_pixels,
            "outside_plate_pixels": outside_pixels,
            "equivalent_plate_diameter": round(equivalent_diameter, 3),
            "maximum_outside_distance": outside_distance,
            "corridor_width": corridor_width,
        },
    )
