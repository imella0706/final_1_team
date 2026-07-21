from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from app.core.config import PipelineConfig
from app.services.background_generation import FluxBackgroundGenerator
from app.services.background_prompt import build_background_prompt
from app.services.contact_shadow import add_contact_shadow
from app.services.detection import UltralyticsDetector
from app.services.edge_decontamination import remove_color_spill
from app.services.foreground_extraction import alpha_composite, extract_rgba, foreground_mask
from app.services.foreground_placement import fit_background
from app.services.inpainting import BigLaMaInpainter, removal_mask_from_boxes
from app.services.matting import BiRefNetMattingService
from app.services.removal_detection import RemovalTargetDetector
from app.services.segmentation import SAM2Segmenter
from app.services.semantic_validation import OpenCLIPSemanticValidator
from app.services.validation import validate_result
from app.services.quality import analyze_quality
from app.services.harmonization import harmonize_foreground
from app.utils.image_io import load_image, resize_for_processing, save_image


@dataclass(slots=True)
class BackgroundReplacementResult:
    output_path: Path
    report_path: Path
    foreground_path: Path
    passed: bool


class BackgroundReplacementPipeline:
    """Creates a new background while retaining the original food and container pixels."""

    def __init__(self, config: PipelineConfig) -> None:
        self.config = config

    def run(self, input_path: str | Path, metadata: dict[str, Any] | None = None) -> BackgroundReplacementResult:
        input_path = Path(input_path)
        metadata = metadata or {}
        original = resize_for_processing(load_image(input_path, self.config.image), self.config.image.max_long_side)
        before = analyze_quality(original, self.config.quality)
        stages: dict[str, dict[str, Any]] = {"step_1_input_quality": {"status": "completed", "quality": before.to_dict()}}

        detector = UltralyticsDetector(dict(self.config.models.get("foreground_detector", self.config.models.get("detector", {}))))
        detection = detector.detect(original)
        food_labels = set(self.config.models.get("foreground_detector", {}).get("food_classes", []))
        container_labels = set(self.config.models.get("foreground_detector", {}).get("container_classes", []))
        food_boxes = [item.box_xyxy for item in detection.target_detections if item.label in food_labels]
        container_boxes = [item.box_xyxy for item in detection.target_detections if item.label in container_labels]
        if not food_boxes and not container_boxes:
            height, width = original.shape[:2]
            margin_x, margin_y = round(width * 0.12), round(height * 0.12)
            food_boxes = [(margin_x, margin_y, width - margin_x, height - margin_y)]
            stages["step_2_detection_fallback"] = {
                "status": "fallback",
                "reason": "YOLO COCO 클래스에서 음식·용기를 찾지 못해 중앙 전경 상자를 사용했습니다.",
            }
        if "step_2_detection_fallback" in stages:
            stages["step_2_detection_fallback"]["reason"] = (
                "YOLO COCO 클래스에서 음식·용기를 찾지 못해 중앙 전경 상자를 사용했습니다."
            )
        segmenter = SAM2Segmenter(dict(self.config.models.get("segmenter", {})))
        food_segmentation = segmenter.segment(original, food_boxes)
        container_segmentation = segmenter.segment(original, container_boxes)
        structural_foreground = foreground_mask(food_segmentation.mask, container_segmentation.mask)
        stages["step_2_sam2_food_container"] = {
            "status": "completed", "food_boxes": len(food_boxes), "container_boxes": len(container_boxes),
            "mask_count": food_segmentation.mask_count + container_segmentation.mask_count,
        }

        matting = BiRefNetMattingService(dict(self.config.models.get("matting", {})))
        alpha = matting.refine(original, structural_foreground)
        alpha_path = self.config.paths.mask_dir / f"{input_path.stem}_foreground_alpha.png"
        save_image(alpha, alpha_path)
        stages["step_3_birefnet_alpha"] = {"status": "completed", "provider": "birefnet" if matting.enabled else "sam_fallback", "alpha_path": str(alpha_path)}

        protect_kernel = int(self.config.models.get("foreground_protection", {}).get("dilation", 11))
        protect_kernel = protect_kernel + 1 if protect_kernel % 2 == 0 else protect_kernel
        protected = cv2.dilate(alpha, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (max(1, protect_kernel), max(1, protect_kernel))))
        stages["step_4_foreground_protection"] = {"status": "completed", "dilation": protect_kernel}

        cleaned = original.copy()
        removal_config = dict(self.config.models.get("removal_detector", {}))
        inpainter_config = dict(self.config.models.get("inpainter", {}))
        safe_removal = np.zeros_like(alpha)
        if removal_config.get("enabled", False) and inpainter_config.get("enabled", False):
            removal = RemovalTargetDetector(removal_config).detect(original)
            removal_mask = removal_mask_from_boxes(original.shape[:2], removal.boxes, int(inpainter_config.get("mask_dilation", 9)))
            safe_removal = cv2.bitwise_and(removal_mask, cv2.bitwise_not(protected))
            if np.any(safe_removal):
                cleaned = BigLaMaInpainter(inpainter_config).inpaint(original, safe_removal)
            stages["step_5_safe_lama_removal"] = {"status": "completed", "detections": len(removal.boxes), "applied": bool(np.any(safe_removal))}
        else:
            stages["step_5_safe_lama_removal"] = {"status": "skipped"}

        foreground_bgr = cleaned.copy()
        foreground_bgra = extract_rgba(foreground_bgr, alpha)
        foreground_path = self.config.paths.intermediate_dir / f"{input_path.stem}_foreground.png"
        save_image(foreground_bgra, foreground_path)
        stages["step_6_rgba_extraction"] = {"status": "completed", "foreground_path": str(foreground_path)}

        prompt_info = build_background_prompt(metadata)
        stages["step_7_background_prompt"] = {"status": "completed", "prompt": prompt_info.prompt, "light_direction": prompt_info.light_direction}
        generator = FluxBackgroundGenerator(dict(self.config.models.get("background_generator", {})))
        background = generator.generate(prompt_info.prompt, original.shape[1], original.shape[0])
        background = fit_background(background, original.shape[:2])
        background_path = self.config.paths.intermediate_dir / f"{input_path.stem}_generated_background.jpg"
        save_image(background, background_path, self.config.image.jpeg_quality)
        stages["step_8_flux_background"] = {"status": "completed", "background_path": str(background_path)}

        stages["step_9_foreground_placement"] = {"status": "completed", "placement": prompt_info.placement, "mode": "original_canvas"}
        shadowed_background = add_contact_shadow(background, alpha, dict(self.config.models.get("contact_shadow", {})))
        stages["step_10_contact_shadow"] = {"status": "completed", "light_direction": prompt_info.light_direction}

        # IC-Light is deliberately not allowed to replace food pixels.  Its optional output can
        # be supplied later; this stage retains the original foreground and applies bounded colour adaptation.
        stages["step_11_relighting"] = {"status": "skipped", "reason": "IC-Light V1 adapter requires separately licensed local weights"}
        decontaminated = remove_color_spill(foreground_bgr, alpha, shadowed_background)
        harmonized = harmonize_foreground(decontaminated, alpha, shadowed_background, dict(self.config.models.get("harmonization", {})))
        processed = alpha_composite(extract_rgba(harmonized, alpha), shadowed_background)
        stages["step_12_harmonization"] = {"status": "completed", "edge_decontamination": True}

        after = analyze_quality(processed, self.config.quality)
        validation = validate_result(before, after, self.config.validation)
        semantic_config = dict(self.config.models.get("semantic_validator", {}))
        semantic_passed = True
        if semantic_config.get("enabled", False):
            similarity = OpenCLIPSemanticValidator(semantic_config).similarity_masked(original, processed, alpha)
            minimum = float(semantic_config.get("minimum_similarity", 0.80))
            semantic_passed = similarity >= minimum
            stages["step_13_foreground_validation"] = {"status": "completed", "similarity": round(similarity, 6), "minimum_similarity": minimum, "passed": semantic_passed}
        else:
            stages["step_13_foreground_validation"] = {"status": "skipped"}

        output_path = self.config.paths.output_dir / f"{input_path.stem}_background_replaced.jpg"
        report_path = self.config.paths.report_dir / f"{input_path.stem}_background_replacement_report.json"
        save_image(processed, output_path, self.config.image.jpeg_quality)
        report_path.write_text(json.dumps({"input_path": str(input_path), "output_path": str(output_path), "foreground_path": str(foreground_path), "stages": stages, "validation": validation.to_dict(), "pipeline_version": "0.2.0"}, ensure_ascii=False, indent=2), encoding="utf-8")
        return BackgroundReplacementResult(output_path, report_path, foreground_path, validation.passed and semantic_passed)
