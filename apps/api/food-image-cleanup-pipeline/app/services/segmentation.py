from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import cv2
import numpy as np


class SegmenterRuntimeError(RuntimeError):
    """Raised when SAM 2 cannot produce a mask from detection prompts."""


@dataclass(slots=True)
class SegmentationResult:
    mask: np.ndarray
    prompt_count: int
    mask_count: int


class SAM2Segmenter:
    """SAM 2.1 Tiny adapter using YOLO bounding boxes as prompts."""

    def __init__(self, config: dict[str, Any]) -> None:
        if not config.get("enabled", False):
            raise ValueError("models.segmenter.enabled must be true")
        self.weights = str(config.get("weights", "sam2.1_t.pt"))
        self.device = str(config.get("device", "auto"))
        self._model: Any | None = None

    def _load_model(self) -> Any:
        if self._model is None:
            try:
                from ultralytics import SAM
            except ImportError as exc:
                raise SegmenterRuntimeError(
                    "SAM 2 requires the ultralytics package. Install requirements-local.txt."
                ) from exc
            try:
                self._model = SAM(self.weights)
            except Exception as exc:
                raise SegmenterRuntimeError(
                    f"Unable to load SAM 2.1 weights: {self.weights}"
                ) from exc
        return self._model

    def segment(
        self, image: np.ndarray, boxes: list[tuple[int, int, int, int]]
    ) -> SegmentationResult:
        height, width = image.shape[:2]
        if not boxes:
            return SegmentationResult(np.zeros((height, width), np.uint8), 0, 0)

        try:
            results = self._load_model().predict(
                source=image,
                bboxes=[list(box) for box in boxes],
                device=None if self.device == "auto" else self.device,
                verbose=False,
            )
        except Exception as exc:
            raise SegmenterRuntimeError(f"SAM 2 inference failed: {exc}") from exc

        combined = np.zeros((height, width), dtype=np.uint8)
        mask_count = 0
        for result in results:
            masks = getattr(result, "masks", None)
            if masks is None or masks.data is None:
                continue
            for mask in masks.data:
                array = mask.detach().cpu().numpy().astype(np.uint8) * 255
                if array.shape != combined.shape:
                    array = cv2.resize(array, (width, height), interpolation=cv2.INTER_NEAREST)
                combined = np.maximum(combined, array)
                mask_count += 1
        return SegmentationResult(combined, len(boxes), mask_count)
