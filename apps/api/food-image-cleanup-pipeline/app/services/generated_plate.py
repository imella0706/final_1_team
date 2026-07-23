"""생성 배경 안의 중앙 접시 후보를 찾아 음식 배치 기준점으로 사용한다."""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np


@dataclass(frozen=True)
class GeneratedPlateRegion:
    found: bool
    center_x: float = 0.5
    center_y: float = 0.5
    width_ratio: float = 0.0
    height_ratio: float = 0.0
    score: float = 0.0
    source: str = "none"


def find_generated_plate_region(image: np.ndarray) -> GeneratedPlateRegion:
    """밝은 원형·타원형 접시 후보 중 중앙에 가까운 가장 큰 후보를 선택한다."""
    if image is None or image.ndim != 3:
        return GeneratedPlateRegion(found=False)

    height, width = image.shape[:2]
    # 파이프라인 이미지 I/O는 OpenCV BGR 배열을 사용한다.
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    blur = cv2.GaussianBlur(gray, (9, 9), 1.5)
    candidates: list[GeneratedPlateRegion] = []

    circles = cv2.HoughCircles(
        blur, cv2.HOUGH_GRADIENT, dp=1.2,
        minDist=max(80, min(width, height) // 3), param1=80, param2=28,
        minRadius=max(40, min(width, height) // 10),
        maxRadius=max(60, int(min(width, height) * 0.46)),
    )
    if circles is not None:
        for cx, cy, radius in np.round(circles[0]).astype(int):
            candidates.append(
                _candidate_from_ellipse(
                    float(cx), float(cy), float(radius * 2), float(radius * 2),
                    width, height, source="hough_circle"
                )
            )

    _, bright = cv2.threshold(blur, 155, 255, cv2.THRESH_BINARY)
    bright = cv2.morphologyEx(
        bright, cv2.MORPH_CLOSE,
        cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (17, 17)),
    )
    contours, _ = cv2.findContours(bright, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    for contour in contours:
        if len(contour) < 5 or cv2.contourArea(contour) < width * height * 0.035:
            continue
        (cx, cy), (ellipse_w, ellipse_h), _ = cv2.fitEllipse(contour)
        if min(ellipse_w, ellipse_h) / max(ellipse_w, ellipse_h) < 0.58:
            continue
        candidates.append(
            _candidate_from_ellipse(
                float(cx), float(cy), float(ellipse_w), float(ellipse_h),
                width, height, source="bright_ellipse"
            )
        )

    valid = [
        candidate for candidate in candidates
        if 0.14 <= candidate.width_ratio <= 0.90
        and 0.14 <= candidate.height_ratio <= 0.90
        and 0.16 <= candidate.center_x <= 0.84
        and 0.16 <= candidate.center_y <= 0.84
    ]
    return max(valid, key=lambda candidate: candidate.score) if valid else GeneratedPlateRegion(found=False)


def _candidate_from_ellipse(
    cx: float, cy: float, ellipse_w: float, ellipse_h: float,
    width: int, height: int, *, source: str,
) -> GeneratedPlateRegion:
    center_x, center_y = cx / width, cy / height
    width_ratio, height_ratio = ellipse_w / width, ellipse_h / height
    center_distance = float(np.hypot(center_x - 0.5, center_y - 0.5))
    center_score = max(0.0, 1.0 - center_distance / 0.45)
    size_score = min(1.0, (width_ratio * height_ratio) / 0.18)
    roundness_score = min(ellipse_w, ellipse_h) / max(ellipse_w, ellipse_h)
    return GeneratedPlateRegion(
        found=True, center_x=center_x, center_y=center_y,
        width_ratio=width_ratio, height_ratio=height_ratio,
        score=float(0.45 * center_score + 0.35 * size_score + 0.20 * roundness_score),
        source=source,
    )
