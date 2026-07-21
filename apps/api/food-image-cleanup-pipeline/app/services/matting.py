from __future__ import annotations

from pathlib import Path
from typing import Any

import cv2
import numpy as np


class MattingRuntimeError(RuntimeError):
    """Raised when BiRefNet cannot produce an alpha matte."""


class BiRefNetMattingService:
    """Refine a structural SAM mask into a continuous alpha matte with BiRefNet."""

    def __init__(self, config: dict[str, Any]) -> None:
        self.enabled = bool(config.get("enabled", False))
        self.model_id = str(config.get("model_id", "ZhengPeng7/BiRefNet_HR"))
        self.cache_dir = Path(str(config.get("cache_dir", "models/birefnet")))
        self.device = str(config.get("device", "auto"))
        self.input_size = int(config.get("input_size", 1024))
        self._model: Any | None = None
        self._torch: Any | None = None
        self._device: Any | None = None

    def _load(self) -> None:
        if self._model is not None:
            return
        try:
            import torch
            from transformers import AutoModelForImageSegmentation
        except ImportError as exc:
            raise MattingRuntimeError(
                "BiRefNet requires transformers, torch and torchvision. "
                "Install requirements-local.txt or requirements-colab.txt."
            ) from exc
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        device_name = "cuda" if self.device == "auto" and torch.cuda.is_available() else self.device
        if device_name == "auto":
            device_name = "cpu"
        try:
            local_config = self.cache_dir / "config.json"
            model_source = str(self.cache_dir) if local_config.is_file() else self.model_id
            self._model = AutoModelForImageSegmentation.from_pretrained(
                model_source,
                trust_remote_code=True,
                cache_dir=str(self.cache_dir),
                local_files_only=local_config.is_file(),
            ).to(device_name).eval()
        except Exception as exc:
            raise MattingRuntimeError(f"Unable to load BiRefNet: {self.model_id}") from exc
        self._torch, self._device = torch, device_name

    def refine(self, image: np.ndarray, structural_mask: np.ndarray) -> np.ndarray:
        """Limit BiRefNet alpha to a dilated SAM foreground to reject stray objects."""
        if image.shape[:2] != structural_mask.shape:
            raise ValueError("structural_mask must match the image size")
        if not self.enabled:
            return structural_mask.astype(np.uint8)
        self._load()
        assert self._model is not None and self._torch is not None and self._device is not None
        rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        resized = cv2.resize(rgb, (self.input_size, self.input_size), interpolation=cv2.INTER_AREA)
        tensor = self._torch.from_numpy(resized.transpose(2, 0, 1)).float().div(255.0)
        tensor = tensor.unsqueeze(0).to(self._device)
        with self._torch.no_grad():
            result = self._model(tensor)
        logits = result[-1] if isinstance(result, (tuple, list)) else result.logits
        alpha = logits[0, 0].sigmoid().float().cpu().numpy()
        alpha = cv2.resize(alpha, (image.shape[1], image.shape[0]), interpolation=cv2.INTER_CUBIC)
        alpha = cv2.normalize(alpha, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (11, 11))
        allowed = cv2.dilate(structural_mask, kernel)
        return cv2.bitwise_and(alpha, allowed)
