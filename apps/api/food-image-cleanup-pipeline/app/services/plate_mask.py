from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import cv2
import numpy as np


@dataclass(slots=True)
class PlateMaskResult:
    """A conservative container layer derived from the structural foreground."""

    mask: np.ndarray
    used_ellipse_completion: bool
    metrics: dict[str, float | int | bool | str]
    shape_type: str = "unknown"
    used_contour_completion: bool = False


class PlateMaskService:
    """Complete a serving container without assuming every plate is round.

    Elliptical masks may use an ellipse fit. Rectangular trays and irregular
    bowls keep their measured contour and only use a bounded convex/closing
    completion. Low-confidence geometry falls back to the source component.
    """

    def __init__(self, config: dict[str, Any]) -> None:
        self.enabled = bool(config.get("enabled", True))
        self.minimum_area_ratio = float(config.get("minimum_area_ratio", 0.08))
        self.maximum_aspect_ratio = float(config.get("maximum_aspect_ratio", 1.65))
        self.minimum_ellipse_iou = float(config.get("minimum_ellipse_iou", 0.65))
        self.maximum_ellipse_area_ratio = float(config.get("maximum_ellipse_area_ratio", 1.35))
        self.edge_repair_kernel = int(config.get("edge_repair_kernel", 7))
        self.minimum_shape_confidence = float(
            config.get("minimum_shape_confidence", 0.60)
        )
        self.contour_completion_enabled = bool(
            config.get("contour_completion_enabled", True)
        )
        self.minimum_contour_solidity = float(
            config.get("minimum_contour_solidity", 0.72)
        )
        self.minimum_rectangularity = float(
            config.get("minimum_rectangularity", 0.68)
        )
        self.maximum_contour_area_ratio = float(
            config.get("maximum_contour_area_ratio", 1.25)
        )
        self.polygon_epsilon_ratio = float(
            config.get("polygon_epsilon_ratio", 0.025)
        )
        self.maximum_polygon_vertices = int(
            config.get("maximum_polygon_vertices", 10)
        )

    @staticmethod
    def _largest_component(mask: np.ndarray) -> np.ndarray:
        component_count, labels, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
        if component_count <= 1:
            return np.zeros_like(mask)
        label_id = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
        return np.where(labels == label_id, 255, 0).astype(np.uint8)

    @staticmethod
    def _fill_holes(mask: np.ndarray) -> np.ndarray:
        padded = cv2.copyMakeBorder(mask, 1, 1, 1, 1, cv2.BORDER_CONSTANT, value=0)
        inverse = (padded == 0).astype(np.uint8) * 255
        cv2.floodFill(inverse, None, (0, 0), 0)
        return cv2.bitwise_or(mask, inverse[1:-1, 1:-1])

    @staticmethod
    def _mask_iou(first: np.ndarray, second: np.ndarray) -> float:
        intersection = int(np.count_nonzero((first > 0) & (second > 0)))
        union = int(np.count_nonzero((first > 0) | (second > 0)))
        return intersection / max(union, 1)

    def complete(self, structural_mask: np.ndarray) -> PlateMaskResult:
        if structural_mask.ndim != 2:
            raise ValueError("structural_mask must be a single-channel mask")
        binary = (structural_mask >= 128).astype(np.uint8) * 255
        largest = self._largest_component(binary)
        height, width = binary.shape
        source_area = int(np.count_nonzero(largest))
        metrics: dict[str, float | int | bool | str] = {
            "source_area": source_area,
            "source_area_ratio": round(source_area / max(height * width, 1), 6),
            "used_ellipse_completion": False,
            "used_contour_completion": False,
            "shape_type": "unknown",
            "shape_confidence": 0.0,
            "fallback_to_source_mask": False,
        }
        if not self.enabled or source_area == 0 or source_area / max(height * width, 1) < self.minimum_area_ratio:
            return PlateMaskResult(largest, False, metrics)

        contours, _ = cv2.findContours(largest, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            return PlateMaskResult(largest, False, metrics)
        contour = max(contours, key=cv2.contourArea)
        repaired = largest.copy()
        used_ellipse = False
        used_contour = False
        shape_type = "irregular"
        shape_confidence = 0.0
        contour_area = float(cv2.contourArea(contour))
        perimeter = float(cv2.arcLength(contour, True))
        hull = cv2.convexHull(contour)
        hull_area = float(cv2.contourArea(hull))
        solidity = contour_area / max(hull_area, 1.0)
        rotated_rect = cv2.minAreaRect(contour)
        rect_width, rect_height = rotated_rect[1]
        rect_area = float(rect_width * rect_height)
        rectangularity = contour_area / max(rect_area, 1.0)
        approx = cv2.approxPolyDP(
            hull,
            max(1.0, perimeter * self.polygon_epsilon_ratio),
            True,
        )
        polygon_vertices = int(len(approx))
        hull_mask = np.zeros_like(binary)
        cv2.drawContours(hull_mask, [hull], -1, 255, thickness=-1)
        hull_area_ratio = int(np.count_nonzero(hull_mask)) / max(source_area, 1)
        metrics.update(
            {
                "contour_solidity": round(solidity, 6),
                "contour_rectangularity": round(rectangularity, 6),
                "polygon_vertices": polygon_vertices,
                "contour_area_ratio": round(hull_area_ratio, 6),
            }
        )
        is_polygonal_container = (
            4 <= polygon_vertices <= self.maximum_polygon_vertices
            and rectangularity >= self.minimum_rectangularity
        )
        if len(contour) >= 5:
            fitted_ellipse = cv2.fitEllipse(contour)
            (_, _), (axis_a, axis_b), _ = fitted_ellipse
            aspect_ratio = max(axis_a, axis_b) / max(min(axis_a, axis_b), 1.0)
            ellipse_mask = np.zeros_like(binary)
            cv2.ellipse(ellipse_mask, fitted_ellipse, 255, thickness=-1)
            ellipse_area = int(np.count_nonzero(ellipse_mask))
            ellipse_iou = self._mask_iou(ellipse_mask, largest)
            ellipse_area_ratio = ellipse_area / max(source_area, 1)
            ellipse_iou_score = max(
                0.0,
                min(
                    1.0,
                    (ellipse_iou - self.minimum_ellipse_iou)
                    / max(1.0 - self.minimum_ellipse_iou, 1e-6),
                ),
            )
            ellipse_area_score = max(
                0.0,
                1.0
                - abs(ellipse_area_ratio - 1.0)
                / max(self.maximum_ellipse_area_ratio - 1.0, 1e-6),
            )
            ellipse_aspect_score = max(
                0.0,
                1.0
                - (aspect_ratio - 1.0)
                / max(self.maximum_aspect_ratio - 1.0, 1e-6),
            )
            ellipse_confidence = float(
                np.mean(
                    [
                        ellipse_iou_score,
                        ellipse_area_score,
                        ellipse_aspect_score,
                    ]
                )
            )
            metrics.update(
                {
                    "ellipse_iou": round(ellipse_iou, 6),
                    "ellipse_area_ratio": round(ellipse_area_ratio, 6),
                    "ellipse_aspect_ratio": round(aspect_ratio, 6),
                    "ellipse_confidence": round(ellipse_confidence, 6),
                }
            )
            if (
                not is_polygonal_container
                and aspect_ratio <= self.maximum_aspect_ratio
                and ellipse_iou >= self.minimum_ellipse_iou
                and ellipse_area_ratio <= self.maximum_ellipse_area_ratio
                and ellipse_confidence >= self.minimum_shape_confidence
            ):
                repaired = ellipse_mask
                used_ellipse = True
                shape_type = "ellipse"
                shape_confidence = ellipse_confidence

        if not used_ellipse:
            solidity_score = max(
                0.0,
                min(
                    1.0,
                    (solidity - self.minimum_contour_solidity)
                    / max(1.0 - self.minimum_contour_solidity, 1e-6),
                ),
            )
            rectangularity_score = max(
                0.0,
                min(
                    1.0,
                    (rectangularity - self.minimum_rectangularity)
                    / max(1.0 - self.minimum_rectangularity, 1e-6),
                ),
            )
            expansion_score = max(
                0.0,
                1.0
                - max(0.0, hull_area_ratio - 1.0)
                / max(self.maximum_contour_area_ratio - 1.0, 1e-6),
            )
            contour_confidence = float(
                np.mean(
                    [
                        solidity_score,
                        rectangularity_score,
                        expansion_score,
                    ]
                )
            )
            shape_type = "quadrilateral" if is_polygonal_container else "irregular"
            shape_confidence = contour_confidence
            metrics["contour_confidence"] = round(contour_confidence, 6)
            if (
                self.contour_completion_enabled
                and contour_confidence >= self.minimum_shape_confidence
                and solidity >= self.minimum_contour_solidity
                and hull_area_ratio <= self.maximum_contour_area_ratio
            ):
                # The convex hull follows the measured contour; it does not
                # replace trays or bowls with a generic rectangle.
                repaired = hull_mask
                used_contour = True
            else:
                metrics["fallback_to_source_mask"] = True

        kernel_size = max(1, self.edge_repair_kernel)
        kernel_size += 1 if kernel_size % 2 == 0 else 0
        if kernel_size > 1 and not bool(metrics["fallback_to_source_mask"]):
            repaired = cv2.morphologyEx(
                repaired,
                cv2.MORPH_CLOSE,
                cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (kernel_size, kernel_size)),
            )
        if not bool(metrics["fallback_to_source_mask"]):
            repaired = self._fill_holes(repaired)
        metrics["used_ellipse_completion"] = used_ellipse
        metrics["used_contour_completion"] = used_contour
        metrics["shape_type"] = shape_type
        metrics["shape_confidence"] = round(shape_confidence, 6)
        metrics["repaired_area"] = int(np.count_nonzero(repaired))
        metrics["completion_area_ratio"] = round(
            float(np.count_nonzero(repaired) / max(source_area, 1)),
            6,
        )
        metrics["edge_repair_kernel"] = kernel_size
        return PlateMaskResult(
            repaired,
            used_ellipse,
            metrics,
            shape_type,
            used_contour,
        )
