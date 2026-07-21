from __future__ import annotations

from dataclasses import asdict, dataclass
from time import perf_counter
from typing import Any

import cv2
import numpy as np


class DetectorConfigurationError(ValueError):
    pass


class DetectorRuntimeError(RuntimeError):
    pass


@dataclass(slots=True)
class Detection:
    class_id: int
    label: str
    confidence: float
    box_xyxy: tuple[int, int, int, int]
    box_xywh: tuple[float, float, float, float]
    box_xywhn: tuple[float, float, float, float]
    is_target_class: bool

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["box_xyxy"] = list(self.box_xyxy)
        data["box_xywh"] = list(self.box_xywh)
        data["box_xywhn"] = list(self.box_xywhn)
        return data


@dataclass(slots=True)
class DetectionResult:
    image_width: int
    image_height: int
    model_name: str
    device: str
    inference_ms: float
    detections: list[Detection]

    @property
    def target_detections(self) -> list[Detection]:
        return [d for d in self.detections if d.is_target_class]

    def to_dict(self) -> dict[str, Any]:
        return {
            "image_width": self.image_width,
            "image_height": self.image_height,
            "model_name": self.model_name,
            "device": self.device,
            "inference_ms": round(self.inference_ms, 3),
            "detection_count": len(self.detections),
            "target_detection_count": len(self.target_detections),
            "detections": [d.to_dict() for d in self.detections],
            "sam_box_prompts_xyxy": [
                list(d.box_xyxy) for d in self.target_detections
            ],
        }


def resolve_foreground_detector_config(config: dict[str, Any]) -> dict[str, Any]:
    """선택된 탐지기 프로필을 일반 YOLO 탐지 설정으로 펼친다.

    음식 특화 모델과 COCO 기본 모델은 클래스명이 다르므로, 가중치만 바꾸지 않고
    target_classes·food_classes·container_classes를 함께 전환한다.
    """

    profiles = config.get("profiles")
    if not profiles:
        return dict(config)
    if not isinstance(profiles, dict):
        raise DetectorConfigurationError("foreground_detector.profiles는 객체여야 합니다.")

    active_profile = str(config.get("active_profile", "food_specialized"))
    profile = profiles.get(active_profile)
    if not isinstance(profile, dict):
        available = ", ".join(sorted(str(name) for name in profiles))
        raise DetectorConfigurationError(
            f"알 수 없는 음식 탐지 프로필입니다: {active_profile}. 선택 가능: {available}"
        )

    resolved = {
        key: value
        for key, value in config.items()
        if key not in {"profiles", "active_profile"}
    }
    resolved.update(profile)
    resolved["active_profile"] = active_profile
    return resolved


class UltralyticsDetector:
    def __init__(self, config: dict[str, Any]) -> None:
        if not config.get("enabled", False):
            raise DetectorConfigurationError(
                "configs/pipeline.yaml의 models.detector.enabled를 true로 설정하세요."
            )

        self.weights = str(config.get("weights", "yolo11n.pt"))
        self.confidence_threshold = float(config.get("confidence_threshold", 0.25))
        self.iou_threshold = float(config.get("iou_threshold", 0.45))
        self.image_size = int(config.get("image_size", 960))
        self.device = str(config.get("device", "cpu"))
        self.max_detections = int(config.get("max_detections", 100))
        self.save_all_classes = bool(config.get("save_all_classes", True))
        self.target_classes = {
            str(name).strip().lower()
            for name in config.get("target_classes", [])
            if str(name).strip()
        }
        self._model = None

    def _load_model(self):
        if self._model is not None:
            return self._model

        try:
            from ultralytics import YOLO
        except ImportError as exc:
            raise DetectorRuntimeError(
                "ultralytics가 설치되지 않았습니다. pip install -r requirements-colab.txt를 실행하세요."
            ) from exc

        try:
            self._model = YOLO(self.weights)
        except Exception as exc:
            raise DetectorRuntimeError(
                f"YOLO 모델을 불러오지 못했습니다: {self.weights}"
            ) from exc

        return self._model

    def detect(self, image: np.ndarray) -> DetectionResult:
        if image is None or image.size == 0:
            raise DetectorRuntimeError("입력 이미지가 비어 있습니다.")

        height, width = image.shape[:2]
        model = self._load_model()

        started = perf_counter()
        try:
            predictions = model.predict(
                source=image,
                conf=self.confidence_threshold,
                iou=self.iou_threshold,
                imgsz=self.image_size,
                device=self.device,
                max_det=self.max_detections,
                verbose=False,
            )
        except Exception as exc:
            raise DetectorRuntimeError(f"YOLO 추론 중 오류가 발생했습니다: {exc}") from exc

        elapsed_ms = (perf_counter() - started) * 1000
        detections: list[Detection] = []

        if predictions:
            prediction = predictions[0]
            names = prediction.names
            if prediction.boxes is not None:
                for box in prediction.boxes:
                    class_id = int(box.cls.item())
                    label = str(names[class_id])
                    confidence = float(box.conf.item())

                    xyxy = box.xyxy[0].detach().cpu().tolist()
                    xywh = box.xywh[0].detach().cpu().tolist()
                    xywhn = box.xywhn[0].detach().cpu().tolist()

                    x1 = max(0, min(width - 1, round(xyxy[0])))
                    y1 = max(0, min(height - 1, round(xyxy[1])))
                    x2 = max(0, min(width - 1, round(xyxy[2])))
                    y2 = max(0, min(height - 1, round(xyxy[3])))

                    is_target = (
                        not self.target_classes or label.lower() in self.target_classes
                    )
                    if not self.save_all_classes and not is_target:
                        continue

                    detections.append(
                        Detection(
                            class_id=class_id,
                            label=label,
                            confidence=round(confidence, 6),
                            box_xyxy=(x1, y1, x2, y2),
                            box_xywh=tuple(round(float(v), 4) for v in xywh),
                            box_xywhn=tuple(round(float(v), 6) for v in xywhn),
                            is_target_class=is_target,
                        )
                    )

        detections.sort(key=lambda d: d.confidence, reverse=True)
        return DetectionResult(
            image_width=width,
            image_height=height,
            model_name=self.weights,
            device=self.device,
            inference_ms=elapsed_ms,
            detections=detections,
        )


def draw_detections(
    image: np.ndarray,
    detection_result: DetectionResult,
    target_only: bool = False,
) -> np.ndarray:
    canvas = image.copy()

    for detection in detection_result.detections:
        if target_only and not detection.is_target_class:
            continue

        x1, y1, x2, y2 = detection.box_xyxy
        cv2.rectangle(canvas, (x1, y1), (x2, y2), (255, 255, 255), 2)
        text = f"{detection.label} {detection.confidence:.2f}"
        cv2.putText(
            canvas,
            text,
            (x1, max(20, y1 - 8)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            (255, 255, 255),
            2,
            cv2.LINE_AA,
        )

    return canvas
