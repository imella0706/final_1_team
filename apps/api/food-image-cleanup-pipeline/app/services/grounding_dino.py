"""GroundingDINO를 이용해 CVAT 검수용 접시/음식 초안 상자를 만든다."""

from __future__ import annotations

import inspect
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from PIL import Image


class GroundingDINORuntimeError(RuntimeError):
    """GroundingDINO 초기화 또는 추론 실패."""


@dataclass(slots=True)
class GroundingDetection:
    label: str
    score: float
    box_xyxy: tuple[int, int, int, int]


class GroundingDINODetector:
    """Transformers의 GroundingDINO 구현을 쓰는 가벼운 어댑터.

    원본 GroundingDINO 저장소는 CUDA 확장 빌드를 요구할 수 있으므로, 같은 모델
    계열을 지원하는 Transformers 어댑터를 사용한다. 이 방식은 Colab에서도 별도
    CUDA 컴파일 없이 초안 생성에 쓸 수 있다.
    """

    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        self.model_id = str(config.get("model_id", "IDEA-Research/grounding-dino-tiny"))
        self.device = str(config.get("device", "auto"))
        # This directory is a portable model snapshot, not merely the Hugging
        # Face cache.  It lets Colab reuse weights stored on Drive.
        self.cache_dir = Path(config.get("cache_dir", "models/grounding-dino"))
        self._processor: Any | None = None
        self._model: Any | None = None

    def _load(self) -> None:
        if self._processor is not None and self._model is not None:
            return
        try:
            import torch
            from transformers import AutoModelForZeroShotObjectDetection, AutoProcessor
        except ImportError as exc:  # pragma: no cover - dependency environment dependent
            raise GroundingDINORuntimeError(
                "GroundingDINO 초안 생성에는 transformers와 torch가 필요합니다."
            ) from exc
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            local_snapshot_ready = (self.cache_dir / "config.json").is_file()
            model_source = str(self.cache_dir) if local_snapshot_ready else self.model_id
            load_kwargs: dict[str, Any] = {"local_files_only": local_snapshot_ready}
            self._processor = AutoProcessor.from_pretrained(model_source, **load_kwargs)
            self._model = AutoModelForZeroShotObjectDetection.from_pretrained(
                model_source, **load_kwargs
            )
            target_device = "cuda" if self.device == "auto" and torch.cuda.is_available() else self.device
            if target_device == "auto":
                target_device = "cpu"
            self._model.to(target_device)
            self._model.eval()
        except Exception as exc:
            raise GroundingDINORuntimeError(
                f"GroundingDINO 모델을 준비할 수 없습니다: {self.model_id}"
            ) from exc

    def _post_process(
        self,
        outputs: Any,
        input_ids: Any,
        *,
        target_sizes: list[tuple[int, int]],
    ) -> list[dict[str, Any]]:
        assert self._processor is not None
        method = self._processor.post_process_grounded_object_detection
        box_threshold = float(self.config.get("box_threshold", 0.28))
        text_threshold = float(self.config.get("text_threshold", 0.22))
        kwargs: dict[str, Any] = {"target_sizes": target_sizes}

        try:
            parameters = inspect.signature(method).parameters
        except (TypeError, ValueError):
            parameters = {}

        if not parameters or "box_threshold" in parameters:
            kwargs["box_threshold"] = box_threshold
        elif "threshold" in parameters:
            kwargs["threshold"] = box_threshold

        if not parameters or "text_threshold" in parameters:
            kwargs["text_threshold"] = text_threshold

        if not parameters or "input_ids" in parameters:
            return method(outputs, input_ids=input_ids, **kwargs)
        return method(outputs, **kwargs)

    def detect(self, image_bgr: np.ndarray) -> list[GroundingDetection]:
        self._load()
        assert self._processor is not None and self._model is not None
        try:
            import torch

            prompts = self.config.get("prompts", ["plate", "dish", "bowl", "food"])
            text = ". ".join(str(item).strip(" .") for item in prompts if str(item).strip()) + "."
            image_rgb = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB)
            pil = Image.fromarray(image_rgb)
            inputs = self._processor(images=pil, text=text, return_tensors="pt")
            device = next(self._model.parameters()).device
            inputs = {key: value.to(device) if hasattr(value, "to") else value for key, value in inputs.items()}
            with torch.no_grad():
                outputs = self._model(**inputs)
            height, width = image_bgr.shape[:2]
            results = self._post_process(
                outputs,
                inputs["input_ids"],
                target_sizes=[(height, width)],
            )[0]
        except Exception as exc:
            raise GroundingDINORuntimeError(f"GroundingDINO 추론 실패: {exc}") from exc

        detected: list[GroundingDetection] = []
        for box, score, label in zip(results["boxes"], results["scores"], results["labels"], strict=True):
            label_text = str(label).lower()
            x1, y1, x2, y2 = [int(round(float(value))) for value in box.tolist()]
            x1, x2 = sorted((max(0, x1), min(width, x2)))
            y1, y2 = sorted((max(0, y1), min(height, y2)))
            if x2 <= x1 or y2 <= y1:
                continue
            detected.append(GroundingDetection(label_text, float(score), (x1, y1, x2, y2)))
        return detected


def split_plate_and_food_boxes(
    detections: list[GroundingDetection],
) -> tuple[list[tuple[int, int, int, int]], list[tuple[int, int, int, int]], list[GroundingDetection]]:
    """언어 검출 라벨을 접시 후보와 음식 후보로 분류한다."""

    plate_terms = ("plate", "dish", "bowl", "saucer", "tray")
    food_terms = (
        "food",
        "meal",
        "dish",
        "bread",
        "cake",
        "dessert",
        "pizza",
        "sandwich",
        "skewer",
        "chopstick",
        "satay stick",
        "food stick",
    )
    plate_boxes = [item.box_xyxy for item in detections if any(term in item.label for term in plate_terms)]
    food_boxes = [item.box_xyxy for item in detections if any(term in item.label for term in food_terms)]
    return plate_boxes, food_boxes, detections
