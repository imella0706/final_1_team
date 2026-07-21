from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np


class MattingRuntimeError(RuntimeError):
    """Raised when BiRefNet cannot produce an alpha matte."""


@dataclass(slots=True)
class MattingResult:
    """A BiRefNet refinement accepted only when it agrees with the SAM structure mask."""

    alpha: np.ndarray
    used_birefnet: bool
    metrics: dict[str, float | int]
    fallback_reason: str | None = None


class BiRefNetMattingService:
    """Refine a structural SAM mask into a continuous alpha matte with BiRefNet."""

    def __init__(self, config: dict[str, Any]) -> None:
        self.enabled = bool(config.get("enabled", False))
        self.model_id = str(config.get("model_id", "ZhengPeng7/BiRefNet_HR"))
        self.cache_dir = Path(str(config.get("cache_dir", "models/birefnet")))
        self.device = str(config.get("device", "auto"))
        self.input_size = int(config.get("input_size", 1024))
        self.threshold = float(config.get("threshold", 0.50))
        self.feather_kernel = int(config.get("feather_kernel", 5))
        self.allowed_dilation = int(config.get("allowed_dilation", 11))
        self.minimum_iou = float(config.get("minimum_iou", 0.55))
        self.minimum_area_ratio = float(config.get("minimum_area_ratio", 0.60))
        self.maximum_area_ratio = float(config.get("maximum_area_ratio", 1.40))
        self.maximum_extra_components = int(config.get("maximum_extra_components", 2))
        self.sam_closing_kernel = int(config.get("sam_closing_kernel", 15))
        self.sam_min_component_area = int(config.get("sam_min_component_area", 256))
        self.sam_fill_holes = bool(config.get("sam_fill_holes", True))
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

    @staticmethod
    def _component_count(mask: np.ndarray) -> int:
        return max(0, int(cv2.connectedComponents((mask > 0).astype(np.uint8))[0]) - 1)

    def _feather(self, binary_mask: np.ndarray) -> np.ndarray:
        kernel = max(1, self.feather_kernel)
        kernel = kernel + 1 if kernel % 2 == 0 else kernel
        if kernel == 1:
            return (binary_mask > 0).astype(np.uint8) * 255
        feathered = cv2.GaussianBlur(
            (binary_mask > 0).astype(np.uint8) * 255,
            (kernel, kernel),
            0,
        )
        allowed = cv2.dilate(
            (binary_mask > 0).astype(np.uint8) * 255,
            cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (kernel, kernel)),
        )
        return cv2.bitwise_and(feathered, allowed)

    @staticmethod
    def _fill_enclosed_holes(binary_mask: np.ndarray) -> np.ndarray:
        """Fill background regions not connected to the image edge.

        Food advertising keeps an opaque dish together with its food.  A mask
        hole inside that dish would otherwise reveal the generated background
        through the preserved foreground.
        """

        padded = cv2.copyMakeBorder(binary_mask, 1, 1, 1, 1, cv2.BORDER_CONSTANT, value=0)
        inverse = (padded == 0).astype(np.uint8) * 255
        cv2.floodFill(inverse, None, (0, 0), 0)
        holes = inverse[1:-1, 1:-1]
        return cv2.bitwise_or(binary_mask, holes)

    def stabilize_sam_mask(self, structural_mask: np.ndarray) -> tuple[np.ndarray, dict[str, int]]:
        """Remove SAM speckle and fill interior transparency before compositing."""

        binary = (structural_mask >= 128).astype(np.uint8) * 255
        raw_area = int(np.count_nonzero(binary))
        raw_components = self._component_count(binary)

        kernel_size = max(1, self.sam_closing_kernel)
        kernel_size = kernel_size + 1 if kernel_size % 2 == 0 else kernel_size
        if kernel_size > 1:
            binary = cv2.morphologyEx(
                binary,
                cv2.MORPH_CLOSE,
                cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (kernel_size, kernel_size)),
            )

        component_count, labels, stats, _ = cv2.connectedComponentsWithStats(binary, 8)
        stabilized = np.zeros_like(binary)
        minimum_area = max(1, self.sam_min_component_area)
        for label_id in range(1, component_count):
            if int(stats[label_id, cv2.CC_STAT_AREA]) >= minimum_area:
                stabilized[labels == label_id] = 255

        if self.sam_fill_holes and np.any(stabilized):
            stabilized = self._fill_enclosed_holes(stabilized)

        metrics = {
            "raw_area": raw_area,
            "raw_components": raw_components,
            "stabilized_area": int(np.count_nonzero(stabilized)),
            "stabilized_components": self._component_count(stabilized),
            "closing_kernel": kernel_size,
            "minimum_component_area": minimum_area,
            "hole_filling": int(self.sam_fill_holes),
        }
        return stabilized, metrics

    def _sam_fallback(self, structural_mask: np.ndarray, reason: str) -> MattingResult:
        sam_binary = (structural_mask >= 128).astype(np.uint8) * 255
        return MattingResult(
            alpha=self._feather(sam_binary),
            used_birefnet=False,
            metrics={"sam_area": int(np.count_nonzero(sam_binary))},
            fallback_reason=reason,
        )

    def _evaluate_candidate(
        self, sam_binary: np.ndarray, candidate_binary: np.ndarray
    ) -> tuple[dict[str, float | int], str | None]:
        sam_area = int(np.count_nonzero(sam_binary))
        candidate_area = int(np.count_nonzero(candidate_binary))
        intersection = int(np.count_nonzero((sam_binary > 0) & (candidate_binary > 0)))
        union = int(np.count_nonzero((sam_binary > 0) | (candidate_binary > 0)))
        area_ratio = candidate_area / max(sam_area, 1)
        iou = intersection / max(union, 1)
        sam_components = self._component_count(sam_binary)
        candidate_components = self._component_count(candidate_binary)
        metrics: dict[str, float | int] = {
            "sam_area": sam_area,
            "alpha_area": candidate_area,
            "area_ratio": round(area_ratio, 6),
            "iou": round(iou, 6),
            "sam_components": sam_components,
            "alpha_components": candidate_components,
        }
        if sam_area == 0 or candidate_area == 0:
            return metrics, "empty_sam_or_birefnet_mask"
        if iou < self.minimum_iou:
            return metrics, "birefnet_iou_below_threshold"
        if not self.minimum_area_ratio <= area_ratio <= self.maximum_area_ratio:
            return metrics, "birefnet_area_ratio_out_of_range"
        if candidate_components > sam_components + self.maximum_extra_components:
            return metrics, "birefnet_component_count_too_high"
        return metrics, None

    def refine(self, image: np.ndarray, structural_mask: np.ndarray) -> MattingResult:
        """Use BiRefNet only as a quality-gated SAM-mask refinement."""
        if image.shape[:2] != structural_mask.shape:
            raise ValueError("structural_mask must match the image size")
        if not self.enabled:
            return self._sam_fallback(structural_mask, "birefnet_disabled")
        try:
            self._load()
            assert self._model is not None and self._torch is not None and self._device is not None
            rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
            resized = cv2.resize(rgb, (self.input_size, self.input_size), interpolation=cv2.INTER_AREA)
            tensor = self._torch.from_numpy(resized.transpose(2, 0, 1)).float().div(255.0)
            tensor = tensor.unsqueeze(0).to(self._device)
            with self._torch.no_grad():
                result = self._model(tensor)
            logits = result[-1] if isinstance(result, (tuple, list)) else result.logits
            probability = logits[0, 0].sigmoid().float().cpu().numpy()
        except Exception as exc:
            return self._sam_fallback(structural_mask, f"birefnet_runtime_error:{type(exc).__name__}")

        probability = cv2.resize(
            probability, (image.shape[1], image.shape[0]), interpolation=cv2.INTER_CUBIC
        )
        # Min-Max normalization changes the semantic meaning of the model confidence.
        # A fixed sigmoid threshold is reproducible across images and model runs.
        candidate = (np.clip(probability, 0.0, 1.0) >= self.threshold).astype(np.uint8) * 255
        dilation = max(1, self.allowed_dilation)
        dilation = dilation + 1 if dilation % 2 == 0 else dilation
        allowed = cv2.dilate(
            (structural_mask >= 128).astype(np.uint8) * 255,
            cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (dilation, dilation)),
        )
        candidate = cv2.bitwise_and(candidate, allowed)
        candidate, candidate_stabilization = self.stabilize_sam_mask(candidate)
        sam_binary = (structural_mask >= 128).astype(np.uint8) * 255
        metrics, reason = self._evaluate_candidate(sam_binary, candidate)
        metrics["candidate_stabilized_area"] = candidate_stabilization["stabilized_area"]
        metrics["candidate_stabilized_components"] = candidate_stabilization[
            "stabilized_components"
        ]
        if reason:
            return self._sam_fallback(structural_mask, reason)
        return MattingResult(
            alpha=self._feather(candidate),
            used_birefnet=True,
            metrics=metrics,
        )
