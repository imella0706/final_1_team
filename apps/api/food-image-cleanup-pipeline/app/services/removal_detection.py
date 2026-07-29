from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from app.services.detection import Detection, UltralyticsDetector


@dataclass(slots=True)
class RemovalDetectionResult:
    detections: list[Detection]

    @property
    def boxes(self) -> list[tuple[int, int, int, int]]:
        return [item.box_xyxy for item in self.detections]


class RemovalTargetDetector:
    """Runs YOLO11n for configured removable classes such as cutlery."""

    def __init__(self, config: dict[str, Any]) -> None:
        detector_config = dict(config)
        detector_config["enabled"] = True
        detector_config["save_all_classes"] = False
        self._detector = UltralyticsDetector(detector_config)

    def detect(self, image: np.ndarray) -> RemovalDetectionResult:
        result = self._detector.detect(image)
        return RemovalDetectionResult(result.target_detections)
