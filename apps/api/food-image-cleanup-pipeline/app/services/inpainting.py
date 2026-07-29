from __future__ import annotations

from pathlib import Path
from typing import Any

import cv2
import numpy as np


class InpainterRuntimeError(RuntimeError):
    """Raised when the local Big-LaMa TorchScript model cannot run."""


def removal_mask_from_boxes(
    shape: tuple[int, int], boxes: list[tuple[int, int, int, int]], dilation: int = 9
) -> np.ndarray:
    """Create a padded binary inpainting mask from removal-target boxes."""
    height, width = shape
    mask = np.zeros((height, width), dtype=np.uint8)
    for x1, y1, x2, y2 in boxes:
        cv2.rectangle(mask, (x1, y1), (x2, y2), 255, thickness=-1)
    size = max(1, int(dilation))
    if size % 2 == 0:
        size += 1
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (size, size))
    return cv2.dilate(mask, kernel)


class BigLaMaInpainter:
    """Runs the downloaded IOPaint Big-LaMa TorchScript checkpoint locally."""

    def __init__(self, config: dict[str, Any]) -> None:
        if not config.get("enabled", False):
            raise ValueError("models.inpainter.enabled must be true")
        self.weights = Path(str(config.get("weights", "models/big-lama.pt")))
        self.device = str(config.get("device", "auto"))
        self._model: Any | None = None
        self._torch: Any | None = None
        self._runtime_device: Any | None = None

    def _load_model(self) -> Any:
        if self._model is not None:
            return self._model
        if not self.weights.is_file():
            raise InpainterRuntimeError(
                f"Big-LaMa weights are missing: {self.weights}. "
                "Run python -m scripts.download_models --models big-lama"
            )
        try:
            import torch
        except ImportError as exc:
            raise InpainterRuntimeError("Big-LaMa requires PyTorch") from exc
        device_name = "cuda" if self.device == "auto" and torch.cuda.is_available() else self.device
        if device_name == "auto":
            device_name = "cpu"
        runtime_device = torch.device(device_name)
        try:
            # TorchScript checkpoints may retain CUDA parameters.  Move both the
            # model and every inference tensor to this single resolved device.
            self._model = torch.jit.load(str(self.weights), map_location=runtime_device)
            self._model = self._model.to(runtime_device).eval()
            self._torch = torch
            self._runtime_device = runtime_device
        except Exception as exc:
            raise InpainterRuntimeError(f"Unable to load Big-LaMa: {self.weights}") from exc
        return self._model

    def inpaint(self, image: np.ndarray, mask: np.ndarray) -> np.ndarray:
        if mask.shape != image.shape[:2]:
            raise ValueError("The inpainting mask must match the image size")
        if not np.any(mask):
            return image.copy()

        model = self._load_model()
        torch = self._torch
        runtime_device = self._runtime_device
        assert torch is not None and runtime_device is not None
        height, width = image.shape[:2]
        pad_bottom = (-height) % 8
        pad_right = (-width) % 8
        padded_image = cv2.copyMakeBorder(
            image, 0, pad_bottom, 0, pad_right, cv2.BORDER_REFLECT
        )
        padded_mask = cv2.copyMakeBorder(mask, 0, pad_bottom, 0, pad_right, cv2.BORDER_CONSTANT)
        rgb = cv2.cvtColor(padded_image, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
        image_tensor = torch.from_numpy(rgb.transpose(2, 0, 1)).unsqueeze(0).to(runtime_device)
        mask_tensor = (
            torch.from_numpy((padded_mask > 0).astype(np.float32))
            .unsqueeze(0)
            .unsqueeze(0)
            .to(runtime_device)
        )
        with torch.no_grad():
            output = model(image_tensor, mask_tensor)[0].permute(1, 2, 0).cpu().numpy()
        output = np.clip(output * 255, 0, 255).astype(np.uint8)[:height, :width]
        return cv2.cvtColor(output, cv2.COLOR_RGB2BGR)
