from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import cv2
import numpy as np


@dataclass(slots=True)
class PlateMaskResult:
    """A conservative plate layer derived from the structural SAM foreground."""

    mask: np.ndarray
    used_ellipse_completion: bool
    metrics: dict[str, float | int | bool]


class PlateMaskService:
    """Complete a large round/elliptical serving plate without generating pixels.

    The service only restores alpha coverage.  Foreground RGB pixels continue to
    come from the input image, so a recovered plate rim never changes the dish
    design or introduces diffusion-model artefacts.
    """

    def __init__(self, config: dict[str, Any]) -> None:
        self.enabled = bool(config.get("enabled", True))
        self.minimum_area_ratio = float(config.get("minimum_area_ratio", 0.08))
        self.maximum_aspect_ratio = float(config.get("maximum_aspect_ratio", 1.65))
        self.minimum_ellipse_iou = float(config.get("minimum_ellipse_iou", 0.65))
        self.maximum_ellipse_area_ratio = float(config.get("maximum_ellipse_area_ratio", 1.35))
        self.edge_repair_kernel = int(config.get("edge_repair_kernel", 7))

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

    def complete(self, structural_mask: np.ndarray) -> PlateMaskResult:
        if structural_mask.ndim != 2:
            raise ValueError("structural_mask must be a single-channel mask")
        binary = (structural_mask >= 128).astype(np.uint8) * 255
        largest = self._largest_component(binary)
        height, width = binary.shape
        source_area = int(np.count_nonzero(largest))
        metrics: dict[str, float | int | bool] = {
            "source_area": source_area,
            "source_area_ratio": round(source_area / max(height * width, 1), 6),
            "used_ellipse_completion": False,
        }
        if not self.enabled or source_area == 0 or source_area / max(height * width, 1) < self.minimum_area_ratio:
            return PlateMaskResult(largest, False, metrics)

        contours, _ = cv2.findContours(largest, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            return PlateMaskResult(largest, False, metrics)
        contour = max(contours, key=cv2.contourArea)
        repaired = self._fill_holes(largest)
        used_ellipse = False
        if len(contour) >= 5:
            (_, _), (axis_a, axis_b), _ = cv2.fitEllipse(contour)
            aspect_ratio = max(axis_a, axis_b) / max(min(axis_a, axis_b), 1.0)
            ellipse_mask = np.zeros_like(binary)
            cv2.ellipse(ellipse_mask, cv2.fitEllipse(contour), 255, thickness=-1)
            ellipse_area = int(np.count_nonzero(ellipse_mask))
            intersection = int(np.count_nonzero((ellipse_mask > 0) & (largest > 0)))
            union = int(np.count_nonzero((ellipse_mask > 0) | (largest > 0)))
            ellipse_iou = intersection / max(union, 1)
            ellipse_area_ratio = ellipse_area / max(source_area, 1)
            metrics.update(
                {
                    "ellipse_iou": round(ellipse_iou, 6),
                    "ellipse_area_ratio": round(ellipse_area_ratio, 6),
                    "ellipse_aspect_ratio": round(aspect_ratio, 6),
                }
            )
            if (
                aspect_ratio <= self.maximum_aspect_ratio
                and ellipse_iou >= self.minimum_ellipse_iou
                and ellipse_area_ratio <= self.maximum_ellipse_area_ratio
            ):
                repaired = ellipse_mask
                used_ellipse = True

        kernel_size = max(1, self.edge_repair_kernel)
        kernel_size += 1 if kernel_size % 2 == 0 else 0
        if kernel_size > 1:
            repaired = cv2.morphologyEx(
                repaired,
                cv2.MORPH_CLOSE,
                cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (kernel_size, kernel_size)),
            )
        repaired = self._fill_holes(repaired)
        metrics["used_ellipse_completion"] = used_ellipse
        metrics["repaired_area"] = int(np.count_nonzero(repaired))
        metrics["edge_repair_kernel"] = kernel_size
        return PlateMaskResult(repaired, used_ellipse, metrics)
