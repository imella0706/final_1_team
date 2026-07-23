from __future__ import annotations

from pathlib import Path
from typing import Any

import cv2
import numpy as np


class SemanticValidationError(RuntimeError):
    """Raised when OpenCLIP cannot evaluate image semantic similarity."""


class OpenCLIPSemanticValidator:
    """Computes cosine similarity between the original and processed image."""

    def __init__(self, config: dict[str, Any]) -> None:
        if not config.get("enabled", False):
            raise ValueError("models.semantic_validator.enabled must be true")
        self.model_name = str(config.get("model_name", "ViT-B-32"))
        self.pretrained = str(config.get("pretrained", "laion2b_s34b_b79k"))
        self.cache_dir = Path(str(config.get("cache_dir", "models/openclip")))
        self.device = str(config.get("device", "auto"))
        self._model: Any | None = None
        self._preprocess: Any | None = None
        self._torch: Any | None = None
        self._device: str | None = None

    def _load(self) -> None:
        if self._model is not None:
            return
        try:
            import open_clip
            import torch
        except ImportError as exc:
            raise SemanticValidationError(
                "OpenCLIP requires open_clip_torch. Install requirements-local.txt."
            ) from exc
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        device = "cuda" if self.device == "auto" and torch.cuda.is_available() else self.device
        if device == "auto":
            device = "cpu"
        try:
            model, _, preprocess = open_clip.create_model_and_transforms(
                self.model_name,
                pretrained=self.pretrained,
                cache_dir=str(self.cache_dir),
                device=device,
            )
            self._model = model.eval()
            self._preprocess = preprocess
            self._torch = torch
            self._device = device
        except Exception as exc:
            raise SemanticValidationError(
                "Unable to load OpenCLIP weights. Run python -m scripts.download_models --models openclip"
            ) from exc

    def similarity(self, original: np.ndarray, processed: np.ndarray) -> float:
        self._load()
        assert self._model is not None and self._preprocess is not None
        assert self._torch is not None and self._device is not None
        from PIL import Image

        original_pil = Image.fromarray(cv2.cvtColor(original, cv2.COLOR_BGR2RGB))
        processed_pil = Image.fromarray(cv2.cvtColor(processed, cv2.COLOR_BGR2RGB))
        batch = self._torch.stack(
            [self._preprocess(original_pil), self._preprocess(processed_pil)]
        ).to(self._device)
        with self._torch.no_grad():
            features = self._model.encode_image(batch)
            features = features / features.norm(dim=-1, keepdim=True)
            return float((features[0] @ features[1]).item())

    def similarity_masked(self, original: np.ndarray, processed: np.ndarray, mask: np.ndarray) -> float:
        """Compare only preserved food/container pixels, not intentionally replaced backgrounds."""
        reference, candidate = self.masked_comparison_images(original, processed, mask)
        return self.similarity(reference, candidate)

    @staticmethod
    def masked_comparison_images(
        original: np.ndarray, processed: np.ndarray, mask: np.ndarray, padding: int = 12
    ) -> tuple[np.ndarray, np.ndarray]:
        """Return matched crops with every replaced-background pixel neutralized."""
        if original.shape[:2] != mask.shape or processed.shape[:2] != mask.shape:
            raise ValueError("mask must match both images")
        alpha = np.clip(mask.astype(np.float32) / 255.0, 0.0, 1.0)
        binary = alpha > 0
        if not np.any(binary):
            raise ValueError("foreground mask is empty")
        ys, xs = np.where(binary)
        y1, y2 = max(0, ys.min() - padding), min(mask.shape[0], ys.max() + padding + 1)
        x1, x2 = max(0, xs.min() - padding), min(mask.shape[1], xs.max() + padding + 1)
        crop_alpha = alpha[y1:y2, x1:x2, None]
        neutral = np.full_like(original[y1:y2, x1:x2], 127)
        reference = np.clip(
            original[y1:y2, x1:x2].astype(np.float32) * crop_alpha
            + neutral.astype(np.float32) * (1.0 - crop_alpha),
            0,
            255,
        ).astype(np.uint8)
        candidate = np.clip(
            processed[y1:y2, x1:x2].astype(np.float32) * crop_alpha
            + neutral.astype(np.float32) * (1.0 - crop_alpha),
            0,
            255,
        ).astype(np.uint8)
        return reference, candidate

    @staticmethod
    def paired_masked_comparison_images(
        original: np.ndarray,
        original_mask: np.ndarray,
        processed: np.ndarray,
        processed_mask: np.ndarray,
        padding: int = 12,
    ) -> tuple[np.ndarray, np.ndarray]:
        """Compare foreground crops even when the dish was resized or relocated."""
        def crop(image: np.ndarray, mask: np.ndarray) -> np.ndarray:
            ys, xs = np.where(mask > 0)
            if len(xs) == 0:
                raise ValueError("foreground mask is empty")
            y1, y2 = max(0, ys.min() - padding), min(mask.shape[0], ys.max() + padding + 1)
            x1, x2 = max(0, xs.min() - padding), min(mask.shape[1], xs.max() + padding + 1)
            alpha = (mask[y1:y2, x1:x2].astype(np.float32) / 255.0)[:, :, None]
            view = image[y1:y2, x1:x2]
            neutral = np.full_like(view, 127)
            return np.clip(view.astype(np.float32) * alpha + neutral * (1.0 - alpha), 0, 255).astype(np.uint8)

        reference, candidate = crop(original, original_mask), crop(processed, processed_mask)
        candidate = cv2.resize(candidate, (reference.shape[1], reference.shape[0]), interpolation=cv2.INTER_LANCZOS4)
        return reference, candidate
