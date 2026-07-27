"""학습된 YOLO 세그멘테이션 모델로 접시 전체와 보이는 음식을 분리한다.

학습 가중치가 없는 개발 환경에서는 호출하지 않으며, 파이프라인은 기존의
SAM + 기하학 보완 경로로 안전하게 되돌아간다.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np


@dataclass
class PlateSegmentationResult:
    """접시/음식 인스턴스 분할 결과."""

    plate_mask: np.ndarray | None
    food_mask: np.ndarray | None
    detections: int
    metrics: dict[str, Any]


class PlateSegmentationService:
    """``plate_full`` 및 ``food_visible`` 클래스를 사용하는 YOLO11-seg 어댑터."""

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = config or {}
        self._model: Any | None = None

    @property
    def enabled(self) -> bool:
        return bool(self.config.get("enabled", False))

    def _load(self) -> None:
        if self._model is not None:
            return
        weights = Path(str(self.config.get("weights", "models/yolo11n_plate_seg.pt")))
        if not weights.is_file():
            raise FileNotFoundError(f"접시 분할 가중치가 없습니다: {weights}")
        try:
            from ultralytics import YOLO
        except ImportError as exc:  # pragma: no cover - 설치 환경에 따라 달라진다.
            raise RuntimeError("접시 분할에는 ultralytics가 필요합니다.") from exc
        self._model = YOLO(str(weights))

    @staticmethod
    def _merge_largest(mask_candidates: list[np.ndarray], shape: tuple[int, int]) -> np.ndarray | None:
        if not mask_candidates:
            return None
        resized = [cv2.resize(mask, (shape[1], shape[0]), interpolation=cv2.INTER_NEAREST) for mask in mask_candidates]
        # 접시는 한 장의 큰 인스턴스여야 하므로 가장 넓은 마스크만 사용한다.
        return max(resized, key=lambda mask: int(np.count_nonzero(mask))).astype(np.uint8)

    def _resolve_device(self) -> str | int:
        device = self.config.get("device", "auto")
        if isinstance(device, str) and device.strip().lower() == "auto":
            try:
                import torch
            except ImportError:
                return "cpu"
            return 0 if torch.cuda.is_available() else "cpu"
        return device

    def segment(self, image: np.ndarray) -> PlateSegmentationResult:
        self._load()
        assert self._model is not None
        device = self._resolve_device()
        result = self._model.predict(
            source=image,
            conf=float(self.config.get("confidence_threshold", 0.25)),
            iou=float(self.config.get("iou_threshold", 0.45)),
            imgsz=int(self.config.get("image_size", 1024)),
            device=device,
            verbose=False,
        )[0]
        if result.masks is None or result.boxes is None:
            return PlateSegmentationResult(None, None, 0, {"reason": "mask_not_detected"})

        names = result.names
        plate_class = str(self.config.get("plate_class", "plate_full"))
        food_class = str(self.config.get("food_class", "food_visible"))
        masks = result.masks.data.detach().float().cpu().numpy()
        classes = result.boxes.cls.detach().cpu().numpy().astype(int)
        scores = result.boxes.conf.detach().cpu().numpy()
        plate_masks: list[np.ndarray] = []
        food_masks: list[np.ndarray] = []
        for mask, class_id in zip(masks, classes, strict=True):
            class_name = str(names.get(int(class_id), class_id)) if isinstance(names, dict) else str(names[int(class_id)])
            binary_mask = (mask >= 0.5).astype(np.uint8) * 255
            if class_name == plate_class:
                plate_masks.append(binary_mask)
            elif class_name == food_class:
                food_masks.append(binary_mask)

        shape = image.shape[:2]
        plate_mask = self._merge_largest(plate_masks, shape)
        food_mask = self._merge_largest(food_masks, shape)
        return PlateSegmentationResult(
            plate_mask=plate_mask,
            food_mask=food_mask,
            detections=len(classes),
            metrics={
                "plate_instances": len(plate_masks),
                "food_instances": len(food_masks),
                "mean_confidence": round(float(scores.mean()), 4) if len(scores) else None,
                "device": str(device),
            },
        )
