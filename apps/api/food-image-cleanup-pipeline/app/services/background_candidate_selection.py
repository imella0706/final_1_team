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


def score_background_candidate(
    background: np.ndarray,
    reference: np.ndarray,
    *,
    food_detections: int | None,
) -> BackgroundCandidateScore:
    """Score food-free candidates without judging the preserved foreground.

    The centre is deliberately evaluated for low edge density: it is the planned
    placement area for the original dish, not a demand for an unnaturally blank
    whole image.  Generated candidates with detected food always lose to an
    equally suitable food-free candidate.
    """
    height, width = background.shape[:2]
    x1, x2 = int(width * 0.25), int(width * 0.75)
    y1, y2 = int(height * 0.25), int(height * 0.75)
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
    food_free_score = 1.0 if food_detections in (None, 0) else 0.0
    score = 0.45 * center_empty_score + 0.25 * color_temperature_score + 0.30 * food_free_score
    return BackgroundCandidateScore(
        score=round(score, 6),
        center_empty_score=round(center_empty_score, 6),
        color_temperature_score=round(color_temperature_score, 6),
        food_free_score=food_free_score,
        food_detections=food_detections,
    )
