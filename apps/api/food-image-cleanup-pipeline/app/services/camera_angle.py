"""EfficientNet-B0 기반 음식 사진 촬영 각도(top/45) 분류 서비스."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np


@dataclass(frozen=True, slots=True)
class CameraAnglePrediction:
    label: str
    confidence: float | None
    probabilities: dict[str, float]
    status: str
    model_path: str | None
    reason: str | None = None


class CameraAngleClassifier:
    """학습된 torchvision EfficientNet-B0 체크포인트로 촬영 시점을 예측한다."""

    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config

    def predict(self, image_bgr: np.ndarray) -> CameraAnglePrediction:
        fallback = str(self.config.get("fallback_angle", "45")).strip().lower()
        if fallback not in {"top", "45"}:
            fallback = "45"
        if not self.config.get("enabled", True):
            return CameraAnglePrediction(fallback, None, {}, "disabled", None, "classifier_disabled")
        weights = Path(str(self.config.get("weights", "models/efficientnet_best.pt")))
        if not weights.is_file():
            return CameraAnglePrediction(
                fallback, None, {}, "unavailable", str(weights), "weights_not_found"
            )
        try:
            model, class_names, device = _load_model(str(weights.resolve()), str(self.config.get("device", "auto")))
            probabilities = _predict_probabilities(model, class_names, device, image_bgr)
            label, confidence = max(probabilities.items(), key=lambda item: item[1])
            if label not in {"top", "45"}:
                raise ValueError(f"unsupported_class:{label}")
            threshold = float(self.config.get("minimum_confidence", 0.60))
            if confidence < threshold and bool(self.config.get("fallback_on_low_confidence", False)):
                return CameraAnglePrediction(
                    fallback,
                    confidence,
                    probabilities,
                    "low_confidence_fallback",
                    str(weights),
                    f"confidence_below_{threshold:.2f}",
                )
            return CameraAnglePrediction(
                label,
                confidence,
                probabilities,
                "completed" if confidence >= threshold else "low_confidence",
                str(weights),
                f"confidence_below_{threshold:.2f}" if confidence < threshold else None,
            )
        except Exception as exc:
            return CameraAnglePrediction(
                fallback,
                None,
                {},
                "unavailable",
                str(weights),
                f"{type(exc).__name__}: {exc}",
            )


@lru_cache(maxsize=4)
def _load_model(weights_path: str, device_request: str):
    import torch
    from torch import nn
    from torchvision.models import efficientnet_b0

    device = torch.device(
        "cuda" if device_request == "auto" and torch.cuda.is_available() else device_request
    )
    if device_request == "auto" and not torch.cuda.is_available():
        device = torch.device("cpu")
    checkpoint = torch.load(weights_path, map_location="cpu", weights_only=False)
    class_names = [str(item).strip().lower() for item in checkpoint["class_names"]]
    if set(class_names) != {"top", "45"}:
        raise ValueError(f"checkpoint_class_names={class_names}")
    model = efficientnet_b0(weights=None)
    model.classifier[1] = nn.Linear(model.classifier[1].in_features, len(class_names))
    model.load_state_dict(checkpoint["model_state_dict"])
    model.to(device)
    model.eval()
    return model, tuple(class_names), device


def _predict_probabilities(model, class_names: tuple[str, ...], device, image_bgr: np.ndarray) -> dict[str, float]:
    import torch
    from PIL import Image
    from torchvision import transforms
    from torchvision.models import EfficientNet_B0_Weights

    if image_bgr.ndim != 3 or image_bgr.shape[2] != 3:
        raise ValueError("expected_bgr_image")
    weights = EfficientNet_B0_Weights.DEFAULT
    transform = weights.transforms()
    image_rgb = np.ascontiguousarray(image_bgr[:, :, ::-1])
    tensor = transform(Image.fromarray(image_rgb)).unsqueeze(0).to(device)
    with torch.no_grad():
        scores = torch.softmax(model(tensor), dim=1)[0].detach().cpu().tolist()
    return {label: float(score) for label, score in zip(class_names, scores)}
