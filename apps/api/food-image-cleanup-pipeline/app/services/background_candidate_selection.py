from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np


@dataclass(frozen=True, slots=True)
class BackgroundCandidateScore:
    score: float
    center_empty_score: float
    color_temperature_score: float
    food_free_score: float
    food_detections: int | None
    center_object_detections: int | None
    geometry_score: float
    generated_plate_score: float | None
    valid: bool
    rejection_reasons: tuple[str, ...]


def score_background_candidate(
    background: np.ndarray,
    reference: np.ndarray,
    *,
    food_detections: int | None,
    object_detections: int | None = None,
    center_object_detections: int | None = None,
    camera_angle: str = "45",
    placement_region: tuple[float, float, float, float] | None = None,
    minimum_geometry_score: float = 0.72,
    requires_generated_plate: bool = False,
    generated_plate_score: float | None = None,
) -> BackgroundCandidateScore:
    """Score food-free candidates without judging the preserved foreground.

    The centre is deliberately evaluated for low edge density: it is the planned
    placement area for the original dish, not a demand for an unnaturally blank
    whole image.  Generated candidates with detected food always lose to an
    equally suitable food-free candidate.
    """
    height, width = background.shape[:2]
    if placement_region is None:
        placement_region = (0.25, 0.25, 0.75, 0.75)
    left, top, right, bottom = placement_region
    left, right = sorted((float(np.clip(left, 0.0, 1.0)), float(np.clip(right, 0.0, 1.0))))
    top, bottom = sorted((float(np.clip(top, 0.0, 1.0)), float(np.clip(bottom, 0.0, 1.0))))
    x1, x2 = int(width * left), max(int(width * right), 1)
    y1, y2 = int(height * top), max(int(height * bottom), 1)
    centre = background[y1:y2, x1:x2]
    edges = cv2.Canny(cv2.cvtColor(centre, cv2.COLOR_BGR2GRAY), 70, 140)
    edge_density = float(np.count_nonzero(edges)) / max(edges.size, 1)
    center_empty_score = float(np.clip(1.0 - edge_density * 7.0, 0.0, 1.0))

    # BGR red-blue difference is a stable, cheap proxy for warm/cool balance.
    reference_temperature = float(reference[:, :, 2].mean() - reference[:, :, 0].mean())
    candidate_temperature = float(background[:, :, 2].mean() - background[:, :, 0].mean())
    color_temperature_score = float(
        np.clip(1.0 - abs(reference_temperature - candidate_temperature) / 70.0, 0.0, 1.0)
    )
    # A food-specialized detector can mistake a round table rim or wood grain for
    # food.  It is retained as diagnostic data, but only an audited object inside
    # the planned placement region blocks a candidate.
    food_free_score = 1.0 if center_object_detections == 0 else 0.0
    if requires_generated_plate:
        geometry_score = float(generated_plate_score or 0.0)
    elif camera_angle == "top":
        # Round tabletops create strong frame-wide edges; judge the placement
        # surface instead of rejecting the table rim as a false horizon.
        geometry_score = center_empty_score
    else:
        lower = background[int(height * 0.55) :, :]
        lower_edges = cv2.Canny(cv2.cvtColor(lower, cv2.COLOR_BGR2GRAY), 70, 140)
        geometry_score = float(np.clip(np.count_nonzero(lower_edges) / max(lower_edges.size * 0.015, 1), 0.0, 1.0))
    reasons: list[str] = []
    if object_detections is None or center_object_detections is None:
        reasons.append("background_object_audit_unavailable")
    elif center_object_detections > 0:
        reasons.append("placement_area_object_detected")
    if requires_generated_plate and (
        generated_plate_score is None or generated_plate_score < minimum_geometry_score
    ):
        reasons.append("generated_plate_not_detected")
    if geometry_score < minimum_geometry_score:
        reasons.append("camera_or_table_plane_mismatch")
    valid = not reasons
    score = 0.45 * center_empty_score + 0.25 * color_temperature_score + 0.30 * food_free_score
    return BackgroundCandidateScore(
        score=round(score, 6),
        center_empty_score=round(center_empty_score, 6),
        color_temperature_score=round(color_temperature_score, 6),
        food_free_score=food_free_score,
        food_detections=food_detections,
        center_object_detections=center_object_detections,
        geometry_score=round(geometry_score, 6),
        generated_plate_score=(
            round(float(generated_plate_score), 6)
            if generated_plate_score is not None
            else None
        ),
        valid=valid,
        rejection_reasons=tuple(reasons),
    )
