from __future__ import annotations

from dataclasses import dataclass, field
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
    provider: str = "sam2"
    metrics: dict[str, float | int | bool | str] = field(default_factory=dict)


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
            return SegmentationResult(np.zeros((height, width), np.uint8), 0, 0, provider="sam2")

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
        return SegmentationResult(combined, len(boxes), mask_count, provider="sam2")


class HQSAMSegmenter:
    """SAM-HQ adapter using the same bounding-box prompts as SAM 2.

    The implementation is optional and loaded lazily so the default pipeline can
    run without installing or downloading SAM-HQ dependencies.
    """

    def __init__(self, config: dict[str, Any]) -> None:
        if not config.get("enabled", False):
            raise ValueError("models.hq_sam.enabled must be true")
        self.model_id = str(config.get("model_id", "syscv-community/sam-hq-vit-base"))
        self.device = str(config.get("device", "auto"))
        self.multimask_output = bool(config.get("multimask_output", True))
        self.hq_token_only = bool(config.get("hq_token_only", True))
        self._processor: Any | None = None
        self._model: Any | None = None

    def _resolve_device(self) -> str:
        if self.device != "auto":
            return self.device
        try:
            import torch
        except ImportError:
            return "cpu"
        return "cuda" if torch.cuda.is_available() else "cpu"

    def _load_model(self) -> tuple[Any, Any, str]:
        if self._processor is None or self._model is None:
            try:
                from transformers import SamHQModel, SamHQProcessor
            except ImportError as exc:
                raise SegmenterRuntimeError(
                    "SAM-HQ requires a recent transformers version with SamHQModel. "
                    "Install requirements-colab.txt or requirements-local.txt."
                ) from exc
            device = self._resolve_device()
            try:
                self._processor = SamHQProcessor.from_pretrained(self.model_id)
                self._model = SamHQModel.from_pretrained(self.model_id)
                self._model.to(device)
                self._model.eval()
            except Exception as exc:
                raise SegmenterRuntimeError(
                    "Unable to load SAM-HQ model "
                    f"{self.model_id}: {type(exc).__name__}: {exc}"
                ) from exc
        return self._processor, self._model, self._resolve_device()

    def segment(
        self, image: np.ndarray, boxes: list[tuple[int, int, int, int]]
    ) -> SegmentationResult:
        height, width = image.shape[:2]
        if not boxes:
            return SegmentationResult(
                np.zeros((height, width), np.uint8), 0, 0, provider="hq_sam"
            )

        try:
            import torch
            from PIL import Image
        except ImportError as exc:
            raise SegmenterRuntimeError(
                "SAM-HQ requires torch and Pillow. Install requirements-colab.txt or requirements-local.txt."
            ) from exc

        processor, model, device = self._load_model()
        rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        pil_image = Image.fromarray(rgb)
        input_boxes = [[list(map(float, box)) for box in boxes]]
        try:
            inputs = processor(
                images=pil_image,
                input_boxes=input_boxes,
                return_tensors="pt",
            )
            inputs = inputs.to(device)
            with torch.no_grad():
                outputs = model(
                    **inputs,
                    multimask_output=self.multimask_output,
                    hq_token_only=self.hq_token_only,
                )
            masks = processor.image_processor.post_process_masks(
                outputs.pred_masks.detach().cpu(),
                inputs["original_sizes"].detach().cpu(),
                inputs["reshaped_input_sizes"].detach().cpu(),
            )[0]
            scores = outputs.iou_scores.detach().cpu()
        except Exception as exc:
            raise SegmenterRuntimeError(f"SAM-HQ inference failed: {exc}") from exc

        combined = np.zeros((height, width), dtype=np.uint8)
        mask_count = 0
        score_values: list[float] = []
        mask_array = masks.detach().cpu().numpy()
        if mask_array.ndim == 3:
            mask_array = mask_array[:, None, :, :]
        if scores.ndim == 3:
            score_array = scores.numpy()[0]
        else:
            score_array = np.zeros(mask_array.shape[:2], dtype=np.float32)

        for box_index in range(mask_array.shape[0]):
            candidate_masks = mask_array[box_index]
            if candidate_masks.ndim == 2:
                candidate_masks = candidate_masks[None, :, :]
            if box_index < score_array.shape[0]:
                score_row = score_array[box_index]
                best_index = int(np.argmax(score_row)) if len(score_row) else 0
                score_values.append(float(score_row[best_index]) if len(score_row) else 0.0)
            else:
                areas = [np.count_nonzero(candidate) for candidate in candidate_masks]
                best_index = int(np.argmax(areas)) if areas else 0
            selected = (candidate_masks[best_index] > 0).astype(np.uint8) * 255
            if selected.shape != combined.shape:
                selected = cv2.resize(
                    selected, (width, height), interpolation=cv2.INTER_NEAREST
                )
            combined = np.maximum(combined, selected)
            mask_count += 1

        return SegmentationResult(
            combined,
            len(boxes),
            mask_count,
            provider="hq_sam",
            metrics={
                "model_id": self.model_id,
                "mean_iou_score": round(float(np.mean(score_values)), 6)
                if score_values
                else 0.0,
                "hq_token_only": self.hq_token_only,
                "multimask_output": self.multimask_output,
            },
        )


def score_segmentation_mask(
    mask: np.ndarray,
    boxes: list[tuple[int, int, int, int]],
) -> dict[str, float | int]:
    binary = mask > 0
    total_pixels = int(np.count_nonzero(binary))
    if total_pixels == 0:
        return {
            "mask_pixels": 0,
            "inside_box_ratio": 0.0,
            "box_fill_ratio": 0.0,
            "score": 0.0,
        }

    box_mask = np.zeros(mask.shape[:2], dtype=bool)
    height, width = mask.shape[:2]
    for x1, y1, x2, y2 in boxes:
        raw_left, raw_right = sorted((int(x1), int(x2)))
        raw_top, raw_bottom = sorted((int(y1), int(y2)))
        left, right = max(0, raw_left), min(width, raw_right)
        top, bottom = max(0, raw_top), min(height, raw_bottom)
        if right > left and bottom > top:
            box_mask[top:bottom, left:right] = True

    inside_pixels = int(np.count_nonzero(binary & box_mask))
    box_pixels = int(np.count_nonzero(box_mask))
    inside_box_ratio = inside_pixels / max(total_pixels, 1)
    box_fill_ratio = inside_pixels / max(box_pixels, 1)
    score = inside_box_ratio * 0.75 + min(box_fill_ratio, 0.85) * 0.25
    return {
        "mask_pixels": total_pixels,
        "inside_box_ratio": round(float(inside_box_ratio), 6),
        "box_fill_ratio": round(float(box_fill_ratio), 6),
        "score": round(float(score), 6),
    }


def _box_mask(
    shape: tuple[int, int],
    boxes: list[tuple[int, int, int, int]],
) -> np.ndarray:
    height, width = shape
    mask = np.zeros((height, width), dtype=np.uint8)
    for x1, y1, x2, y2 in boxes:
        raw_left, raw_right = sorted((int(x1), int(x2)))
        raw_top, raw_bottom = sorted((int(y1), int(y2)))
        left, right = max(0, raw_left), min(width, raw_right)
        top, bottom = max(0, raw_top), min(height, raw_bottom)
        if right > left and bottom > top:
            mask[top:bottom, left:right] = 255
    return mask


def _filter_patch_components(
    patch: np.ndarray,
    *,
    max_component_area: int,
    min_component_area: int,
    max_total_area: int | None = None,
) -> tuple[np.ndarray, int, int, bool]:
    component_count, labels, stats, _ = cv2.connectedComponentsWithStats(
        patch, connectivity=8
    )
    filtered = np.zeros_like(patch)
    kept_components = 0
    rejected_components = 0
    total_area = 0
    total_area_limited = False
    component_areas = [
        (component_id, int(stats[component_id, cv2.CC_STAT_AREA]))
        for component_id in range(1, component_count)
    ]
    component_areas.sort(key=lambda item: item[1], reverse=True)
    for component_id, area in component_areas:
        if min_component_area <= area <= max_component_area:
            if max_total_area is not None and total_area + area > max_total_area:
                total_area_limited = True
                rejected_components += 1
                continue
            filtered[labels == component_id] = 255
            kept_components += 1
            total_area += area
        else:
            rejected_components += 1
    return filtered, kept_components, rejected_components, total_area_limited


def _patch_config_for_target(config: dict[str, Any], target_name: str) -> dict[str, Any]:
    patch_config = dict(config.get("patch_missing", {}))
    target_config = patch_config.get(target_name)
    if isinstance(target_config, dict):
        patch_config.update(target_config)
    return patch_config


def patch_missing_segmentation_result(
    sam2_result: SegmentationResult,
    hq_result: SegmentationResult,
    boxes: list[tuple[int, int, int, int]],
    config: dict[str, Any],
    target_name: str = "foreground",
) -> tuple[SegmentationResult, dict[str, float | int | bool]]:
    patch_config = _patch_config_for_target(config, target_name)
    base = np.where(sam2_result.mask > 0, 255, 0).astype(np.uint8)
    hq = np.where(hq_result.mask > 0, 255, 0).astype(np.uint8)
    if not np.any(base) or not np.any(hq):
        return sam2_result, {
            "patch_pixels": 0,
            "kept_components": 0,
            "rejected_components": 0,
            "applied": False,
        }

    boundary_dilation = int(patch_config.get("boundary_dilation", 21))
    boundary_dilation = boundary_dilation + 1 if boundary_dilation % 2 == 0 else boundary_dilation
    boundary_anchor = cv2.dilate(
        base,
        cv2.getStructuringElement(
            cv2.MORPH_ELLIPSE, (max(1, boundary_dilation), max(1, boundary_dilation))
        ),
    )

    candidate = cv2.bitwise_and(hq, cv2.bitwise_not(base))
    if bool(patch_config.get("only_near_sam_boundary", True)):
        candidate = cv2.bitwise_and(candidate, boundary_anchor)
    if bool(patch_config.get("only_inside_boxes", True)):
        candidate = cv2.bitwise_and(candidate, _box_mask(base.shape, boxes))

    max_area_ratio = float(patch_config.get("max_patch_area_ratio", 0.08))
    max_patch_area = max(1, int(np.count_nonzero(base) * max_area_ratio))
    max_total_area_ratio = float(
        patch_config.get("max_total_patch_area_ratio", max_area_ratio)
    )
    max_total_patch_area = max(1, int(np.count_nonzero(base) * max_total_area_ratio))
    min_component_area = int(patch_config.get("min_component_area", 64))
    candidate, kept_components, rejected_components, total_area_limited = _filter_patch_components(
        candidate,
        max_component_area=max_patch_area,
        min_component_area=min_component_area,
        max_total_area=max_total_patch_area,
    )
    if not np.any(candidate):
        return sam2_result, {
            "patch_pixels": 0,
            "kept_components": kept_components,
            "rejected_components": rejected_components,
            "boundary_dilation": boundary_dilation,
            "max_patch_area": max_patch_area,
            "max_total_patch_area": max_total_patch_area,
            "applied": False,
            "total_area_limited": total_area_limited,
        }

    merged = cv2.bitwise_or(base, candidate)
    return SegmentationResult(
        merged,
        sam2_result.prompt_count,
        sam2_result.mask_count + hq_result.mask_count,
        provider="sam2_hq_patch",
        metrics={
            **sam2_result.metrics,
            "patch_source": "hq_sam",
            "patch_pixels": int(np.count_nonzero(candidate)),
        },
    ), {
        "patch_pixels": int(np.count_nonzero(candidate)),
        "kept_components": kept_components,
        "rejected_components": rejected_components,
        "boundary_dilation": boundary_dilation,
        "max_patch_area": max_patch_area,
        "max_total_patch_area": max_total_patch_area,
        "min_component_area": min_component_area,
        "total_area_limited": total_area_limited,
        "applied": True,
    }


def select_segmentation_result(
    sam2_result: SegmentationResult,
    hq_result: SegmentationResult | None,
    boxes: list[tuple[int, int, int, int]],
    config: dict[str, Any],
    target_name: str = "foreground",
) -> tuple[SegmentationResult, dict[str, Any]]:
    sam2_score = score_segmentation_mask(sam2_result.mask, boxes)
    if hq_result is None:
        return sam2_result, {
            "selected": "sam2",
            "selection_mode": "sam2_only",
            "sam2": sam2_score,
        }

    hq_score = score_segmentation_mask(hq_result.mask, boxes)
    selection_mode = str(config.get("selection_mode", "box_coverage")).lower()
    patch_metrics: dict[str, float | int | bool] | None = None
    if selection_mode == "patch_missing":
        selected, patch_metrics = patch_missing_segmentation_result(
            sam2_result,
            hq_result,
            boxes,
            config,
            target_name,
        )
    elif selection_mode == "hq_sam":
        selected = hq_result
    elif selection_mode == "larger_area":
        selected = (
            hq_result
            if int(hq_score["mask_pixels"]) > int(sam2_score["mask_pixels"])
            else sam2_result
        )
    elif selection_mode == "sam2":
        selected = sam2_result
    else:
        tolerance = float(config.get("minimum_score_gain", 0.0))
        selected = (
            hq_result
            if float(hq_score["score"]) >= float(sam2_score["score"]) + tolerance
            else sam2_result
        )

    return selected, {
        "selected": selected.provider,
        "selection_mode": selection_mode,
        "sam2": sam2_score,
        "hq_sam": hq_score,
        "hq_sam_metrics": hq_result.metrics,
        "patch_missing": patch_metrics,
    }
