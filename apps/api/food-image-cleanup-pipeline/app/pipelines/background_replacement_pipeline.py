from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from app.core.config import PipelineConfig
from app.services.background_generation import FluxBackgroundGenerator
from app.services.background_candidate_selection import score_background_candidate
from app.services.background_prompt import build_background_prompt
from app.services.camera_angle import CameraAngleClassifier
from app.services.contact_shadow import add_contact_shadow
from app.services.detection import (
    DetectorRuntimeError,
    UltralyticsDetector,
    resolve_foreground_detector_config,
)
from app.services.edge_decontamination import remove_color_spill
from app.services.foreground_extraction import alpha_composite, extract_rgba, foreground_mask
from app.services.foreground_placement import fit_background, place_foreground
from app.services.harmonization import harmonize_foreground
from app.services.inpainting import BigLaMaInpainter, removal_mask_from_boxes
from app.services.matting import BiRefNetMattingService
from app.services.quality import analyze_quality
from app.services.removal_detection import RemovalTargetDetector
from app.services.segmentation import SAM2Segmenter
from app.services.semantic_validation import OpenCLIPSemanticValidator
from app.services.validation import validate_result
from app.utils.image_io import load_image, resize_for_processing, save_image


@dataclass(slots=True)
class BackgroundReplacementResult:
    """A completed advertising image or an explicit safe rejection result."""

    output_path: Path | None
    report_path: Path
    foreground_path: Path | None
    passed: bool
    status: str
    reason: str | None = None


class BackgroundReplacementPipeline:
    """Generate only a background and fail closed when the preserved foreground is unreliable."""

    def __init__(self, config: PipelineConfig) -> None:
        self.config = config

    def _write_report(
        self,
        report_path: Path,
        *,
        input_path: Path,
        output_path: Path | None,
        foreground_path: Path | None,
        stages: dict[str, dict[str, Any]],
        validation: dict[str, Any] | None,
        status: str,
        reason: str | None,
        debug_artifacts: dict[str, str],
    ) -> None:
        report_path.write_text(
            json.dumps(
                {
                    "status": status,
                    "reason": reason,
                    "input_path": str(input_path),
                    "output_path": str(output_path) if output_path else None,
                    "foreground_path": str(foreground_path) if foreground_path else None,
                    "debug_artifacts": debug_artifacts,
                    "stages": stages,
                    "validation": validation or {},
                    "pipeline_version": "0.3.0",
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    def _rejected_result(
        self,
        report_path: Path,
        *,
        input_path: Path,
        foreground_path: Path | None,
        stages: dict[str, dict[str, Any]],
        validation: dict[str, Any] | None,
        status: str,
        reason: str,
        debug_artifacts: dict[str, str],
    ) -> BackgroundReplacementResult:
        self._write_report(
            report_path,
            input_path=input_path,
            output_path=None,
            foreground_path=foreground_path,
            stages=stages,
            validation=validation,
            status=status,
            reason=reason,
            debug_artifacts=debug_artifacts,
        )
        return BackgroundReplacementResult(
            output_path=None,
            report_path=report_path,
            foreground_path=foreground_path,
            passed=False,
            status=status,
            reason=reason,
        )

    def run(
        self, input_path: str | Path, metadata: dict[str, Any] | None = None
    ) -> BackgroundReplacementResult:
        input_path = Path(input_path)
        metadata = metadata or {}
        report_path = self.config.paths.report_dir / f"{input_path.stem}_background_replacement_report.json"
        original = resize_for_processing(
            load_image(input_path, self.config.image), self.config.image.max_long_side
        )
        before = analyze_quality(original, self.config.quality)
        stages: dict[str, dict[str, Any]] = {
            "step_1_input_quality": {"status": "completed", "quality": before.to_dict()}
        }
        debug_artifacts: dict[str, str] = {}

        detector_config = resolve_foreground_detector_config(
            dict(
                self.config.models.get(
                    "foreground_detector", self.config.models.get("detector", {})
                )
            )
        )
        food_labels = set(detector_config.get("food_classes", []))
        container_labels = set(detector_config.get("container_classes", []))
        food_boxes: list[tuple[int, int, int, int]] = []
        container_boxes: list[tuple[int, int, int, int]] = []
        try:
            detection = UltralyticsDetector(detector_config).detect(original)
            food_boxes = [
                item.box_xyxy for item in detection.target_detections if item.label in food_labels
            ]
            container_boxes = [
                item.box_xyxy
                for item in detection.target_detections
                if item.label in container_labels
            ]
            stages["step_2_yolo_detection"] = {
                "status": "completed",
                "food_boxes": len(food_boxes),
                "container_boxes": len(container_boxes),
                "model": detection.model_name,
                "profile": detector_config.get("active_profile", "direct"),
            }
        except DetectorRuntimeError as exc:
            stages["step_2_yolo_detection"] = {"status": "unavailable", "reason": str(exc)}
        if not food_boxes and not container_boxes:
            diagnostic_fallback = bool(
                detector_config.get("allow_center_fallback_for_diagnostics", False)
            )
            if not food_boxes:
                stages["step_2_detection_fallback"] = {
                    "status": "diagnostic_fallback" if diagnostic_fallback else "food_detection_failed",
                    "reason": "YOLO11n에서 음식 또는 용기를 찾지 못했습니다.",
                    "advertising_output_allowed": diagnostic_fallback,
                }
                if not diagnostic_fallback:
                    return self._rejected_result(
                        report_path,
                        input_path=input_path,
                        foreground_path=None,
                        stages=stages,
                        validation=None,
                        status="food_detection_failed",
                        reason="음식 탐지 실패: 운영 모드에서는 중앙 사각형 대체 경로를 사용하지 않습니다.",
                        debug_artifacts=debug_artifacts,
                    )
                height, width = original.shape[:2]
                margin_x, margin_y = round(width * 0.12), round(height * 0.12)
                food_boxes = [(margin_x, margin_y, width - margin_x, height - margin_y)]

        segmenter = SAM2Segmenter(dict(self.config.models.get("segmenter", {})))
        food_segmentation = segmenter.segment(original, food_boxes)
        container_segmentation = segmenter.segment(original, container_boxes)
        structural_foreground = foreground_mask(food_segmentation.mask, container_segmentation.mask)
        sam_path = self.config.paths.mask_dir / f"{input_path.stem}_sam_structural_mask.png"
        save_image(structural_foreground, sam_path)
        debug_artifacts["sam_structural_mask"] = str(sam_path)

        matting = BiRefNetMattingService(dict(self.config.models.get("matting", {})))
        stabilized_foreground, stabilization_metrics = matting.stabilize_sam_mask(
            structural_foreground
        )
        stabilized_sam_path = (
            self.config.paths.mask_dir / f"{input_path.stem}_sam_stabilized_mask.png"
        )
        save_image(stabilized_foreground, stabilized_sam_path)
        debug_artifacts["sam_stabilized_mask"] = str(stabilized_sam_path)
        stages["step_2_sam2_food_container"] = {
            "status": "completed",
            "food_boxes": len(food_boxes),
            "container_boxes": len(container_boxes),
            "mask_count": food_segmentation.mask_count + container_segmentation.mask_count,
            "sam_mask_path": str(sam_path),
            "stabilized_sam_mask_path": str(stabilized_sam_path),
            "stabilization": stabilization_metrics,
        }

        matting_result = matting.refine(original, stabilized_foreground)
        alpha = matting_result.alpha
        sam_alpha = matting._sam_fallback(stabilized_foreground, "explicit_sam_retry").alpha
        alpha_path = self.config.paths.mask_dir / f"{input_path.stem}_birefnet_alpha.png"
        save_image(alpha, alpha_path)
        debug_artifacts["birefnet_alpha_mask"] = str(alpha_path)
        stages["step_3_birefnet_alpha"] = {
            "status": "completed" if matting_result.used_birefnet else "sam_fallback",
            "provider": "birefnet" if matting_result.used_birefnet else "sam",
            "alpha_path": str(alpha_path),
            "metrics": matting_result.metrics,
            "fallback_reason": matting_result.fallback_reason,
        }

        protect_kernel = int(self.config.models.get("foreground_protection", {}).get("dilation", 11))
        protect_kernel = protect_kernel + 1 if protect_kernel % 2 == 0 else protect_kernel
        protected = cv2.dilate(
            alpha,
            cv2.getStructuringElement(
                cv2.MORPH_ELLIPSE, (max(1, protect_kernel), max(1, protect_kernel))
            ),
        )
        stages["step_4_foreground_protection"] = {
            "status": "completed",
            "dilation": protect_kernel,
        }

        cleaned = original.copy()
        removal_config = dict(self.config.models.get("removal_detector", {}))
        inpainter_config = dict(self.config.models.get("inpainter", {}))
        if removal_config.get("enabled", False) and inpainter_config.get("enabled", False):
            removal = RemovalTargetDetector(removal_config).detect(original)
            removal_mask = removal_mask_from_boxes(
                original.shape[:2], removal.boxes, int(inpainter_config.get("mask_dilation", 9))
            )
            safe_removal = cv2.bitwise_and(removal_mask, cv2.bitwise_not(protected))
            if np.any(safe_removal):
                cleaned = BigLaMaInpainter(inpainter_config).inpaint(original, safe_removal)
            stages["step_5_safe_lama_removal"] = {
                "status": "completed",
                "detections": len(removal.boxes),
                "applied": bool(np.any(safe_removal)),
            }
        else:
            stages["step_5_safe_lama_removal"] = {"status": "skipped"}

        foreground_path = self.config.paths.intermediate_dir / f"{input_path.stem}_foreground_rgba.png"
        save_image(extract_rgba(cleaned, alpha), foreground_path)
        debug_artifacts["rgba_foreground_preview"] = str(foreground_path)
        stages["step_6_rgba_extraction"] = {
            "status": "completed",
            "foreground_path": str(foreground_path),
        }

        angle_config = dict(self.config.models.get("camera_angle_classifier", {}))
        classifier = CameraAngleClassifier(angle_config)
        manual_angle = bool(metadata.get("camera_angle_manual", False))
        if manual_angle:
            selected_angle = str(metadata.get("camera_angle_label", "45")).strip().lower()
            if selected_angle not in {"top", "45"}:
                selected_angle = "45"
            stages["step_7_camera_angle_classification"] = {
                "status": "manual_override",
                "label": selected_angle,
                "reason": "metadata_camera_angle_manual",
            }
        else:
            angle_prediction = classifier.predict(original)
            selected_angle = angle_prediction.label
            stages["step_7_camera_angle_classification"] = {
                "status": angle_prediction.status,
                "label": selected_angle,
                "confidence": round(angle_prediction.confidence, 6)
                if angle_prediction.confidence is not None
                else None,
                "probabilities": {
                    name: round(score, 6) for name, score in angle_prediction.probabilities.items()
                },
                "model": angle_prediction.model_path,
                "reason": angle_prediction.reason,
            }
        prompt_metadata = {**metadata, "camera_angle_label": selected_angle}
        prompt_info = build_background_prompt(prompt_metadata)
        stages["step_7_background_prompt"] = {
            "status": "completed",
            "prompt": prompt_info.prompt,
            "light_direction": prompt_info.light_direction,
            "camera_angle": prompt_info.camera_angle,
            "placement": prompt_info.placement,
        }
        generator_config = dict(self.config.models.get("background_generator", {}))
        generator = FluxBackgroundGenerator(generator_config)
        candidate_count = (
            int(np.clip(generator_config.get("candidate_count", 3), 3, 4))
            if generator_config.get("candidate_selection_enabled", True)
            else 1
        )
        base_seed = generator_config.get("seed")
        background_candidates: list[tuple[np.ndarray, dict[str, Any]]] = []
        for index in range(candidate_count):
            candidate_seed = None if base_seed is None else int(base_seed) + index
            candidate = generator.generate(
                prompt_info.prompt, original.shape[1], original.shape[0], seed=candidate_seed
            )
            candidate = fit_background(candidate, original.shape[:2])
            detected_food_count: int | None = None
            detection_error: str | None = None
            try:
                candidate_detection = UltralyticsDetector(detector_config).detect(candidate)
                detected_food_count = sum(
                    item.label in food_labels for item in candidate_detection.target_detections
                )
            except Exception as exc:
                # A candidate is not rejected solely because the optional audit could not load.
                detection_error = type(exc).__name__
            score = score_background_candidate(
                candidate, original, food_detections=detected_food_count
            )
            candidate_path = (
                self.config.paths.intermediate_dir
                / f"{input_path.stem}_generated_background_candidate_{index + 1}.jpg"
            )
            save_image(candidate, candidate_path, self.config.image.jpeg_quality)
            debug_artifacts[f"background_candidate_{index + 1}"] = str(candidate_path)
            background_candidates.append(
                (
                    candidate,
                    {
                        "index": index + 1,
                        "seed": candidate_seed,
                        "path": str(candidate_path),
                        "score": score.score,
                        "center_empty_score": score.center_empty_score,
                        "color_temperature_score": score.color_temperature_score,
                        "food_free_score": score.food_free_score,
                        "food_detections": score.food_detections,
                        "food_detection_audit_error": detection_error,
                    },
                )
            )
        background, selected_candidate = max(background_candidates, key=lambda item: item[1]["score"])
        background_path = self.config.paths.intermediate_dir / f"{input_path.stem}_generated_background.jpg"
        save_image(background, background_path, self.config.image.jpeg_quality)
        stages["step_8_background_generation"] = {
            "status": "completed",
            "background_path": str(background_path),
            "candidate_count": candidate_count,
            "selected_candidate": selected_candidate["index"],
            "candidates": [metadata for _, metadata in background_candidates],
        }

        placement_config = dict(self.config.models.get("foreground_placement", {}))
        width_ratio = float(
            placement_config.get(
                "top_width_ratio" if selected_angle == "top" else "angle_45_width_ratio",
                0.62 if selected_angle == "top" else 0.64,
            )
        )

        def compose(candidate_alpha: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray, dict[str, Any]]:
            placed_foreground, placed_alpha, placement_metrics = place_foreground(
                cleaned,
                candidate_alpha,
                placement=prompt_info.placement,
                width_ratio=width_ratio,
            )
            shadow_config = dict(self.config.models.get("contact_shadow", {}))
            if selected_angle == "top":
                # 탑뷰 접시는 수직으로 떨어지는 짧고 균일한 접지 그림자가 자연스럽다.
                shadow_config.update({"vertical_offset": 2, "horizontal_offset": 0, "blur_radius": 13, "opacity": 0.15})
            shadowed = add_contact_shadow(background, placed_alpha, shadow_config)
            decontaminated = remove_color_spill(placed_foreground, placed_alpha, shadowed)
            harmonized = harmonize_foreground(
                decontaminated,
                placed_alpha,
                shadowed,
                dict(self.config.models.get("harmonization", {})),
            )
            return (
                alpha_composite(extract_rgba(harmonized, placed_alpha), shadowed),
                placed_alpha,
                harmonized,
                placement_metrics,
            )

        processed, placed_alpha, placed_foreground, placement_metrics = compose(alpha)
        stages["step_9_foreground_placement"] = {
            "status": "completed",
            **placement_metrics,
            "target_width_ratio_range": [0.55, 0.70],
        }
        stages["step_10_contact_shadow"] = {
            "status": "completed",
            "light_direction": prompt_info.light_direction,
            "camera_angle": selected_angle,
        }
        stages["step_11_relighting"] = {
            "status": "skipped",
            "reason": "원본 음식 픽셀 보존 정책",
        }
        stages["step_12_harmonization"] = {
            "status": "completed",
            "edge_decontamination": True,
        }

        semantic_config = dict(self.config.models.get("semantic_validator", {}))
        minimum_similarity = float(semantic_config.get("minimum_similarity", 0.80))
        attempts: list[dict[str, Any]] = []
        validator = OpenCLIPSemanticValidator(semantic_config) if semantic_config.get("enabled", False) else None

        def evaluate(candidate: np.ndarray, candidate_alpha: np.ndarray, label: str) -> bool:
            try:
                assert validator is not None
                reference_view, candidate_view = validator.paired_masked_comparison_images(
                    original, stabilized_foreground, candidate, candidate_alpha
                )
                comparison_reference_path = (
                    self.config.paths.intermediate_dir
                    / f"{input_path.stem}_semantic_{label}_reference.png"
                )
                comparison_candidate_path = (
                    self.config.paths.intermediate_dir
                    / f"{input_path.stem}_semantic_{label}_candidate.png"
                )
                save_image(reference_view, comparison_reference_path)
                save_image(candidate_view, comparison_candidate_path)
                debug_artifacts[f"semantic_{label}_reference"] = str(comparison_reference_path)
                debug_artifacts[f"semantic_{label}_candidate"] = str(comparison_candidate_path)
                similarity = validator.similarity(reference_view, candidate_view)
                passed = similarity >= minimum_similarity
                attempts.append(
                    {
                        "mask": label,
                        "similarity": round(similarity, 6),
                        "passed": passed,
                    }
                )
                return passed
            except Exception as exc:
                attempts.append(
                    {"mask": label, "similarity": None, "passed": False, "error": type(exc).__name__}
                )
                return False

        semantic_passed = False
        final_alpha = alpha
        final_mask_label = "birefnet" if matting_result.used_birefnet else "sam"
        if semantic_config.get("enabled", False):
            semantic_passed = evaluate(
                processed, placed_alpha, "birefnet" if matting_result.used_birefnet else "sam"
            )
            if not semantic_passed and matting_result.used_birefnet:
                final_alpha = sam_alpha
                final_mask_label = "sam_retry"
                processed, placed_alpha, placed_foreground, placement_metrics = compose(sam_alpha)
                sam_foreground_path = (
                    self.config.paths.intermediate_dir / f"{input_path.stem}_sam_retry_foreground_rgba.png"
                )
                save_image(extract_rgba(cleaned, sam_alpha), sam_foreground_path)
                debug_artifacts["sam_retry_rgba_foreground_preview"] = str(sam_foreground_path)
                semantic_passed = evaluate(processed, placed_alpha, "sam_retry")
        else:
            attempts.append(
                {"mask": "not_evaluated", "similarity": None, "passed": False, "error": "disabled"}
            )

        stages["step_13_foreground_validation"] = {
            "status": "completed" if semantic_passed else "failed",
            "minimum_similarity": minimum_similarity,
            "attempts": attempts,
            "final_mask": final_mask_label,
            "background_food_free": selected_candidate["food_detections"] in (None, 0),
            "geometry": {
                "camera_angle": selected_angle,
                "placement": placement_metrics["placement"],
                "width_ratio": placement_metrics["width_ratio"],
                "within_target_range": 0.55 <= float(placement_metrics["width_ratio"]) <= 0.70,
            },
        }
        before_foreground = analyze_quality(
            original, self.config.quality, mask=stabilized_foreground
        )
        after_foreground = analyze_quality(
            processed, self.config.quality, mask=stabilized_foreground
        )
        validation = validate_result(before_foreground, after_foreground, self.config.validation)
        validation_data = validation.to_dict()
        validation_data["scope"] = "stabilized_foreground_only"
        background_food_validated = selected_candidate["food_detections"] is not None
        background_food_free = selected_candidate["food_detections"] == 0
        geometry_valid = bool(
            0.55 <= float(placement_metrics["width_ratio"]) <= 0.70
            and placement_metrics["placement"] == prompt_info.placement
        )
        stages["step_14_background_geometry_validation"] = {
            "status": "completed" if (not background_food_validated or background_food_free) and geometry_valid else "failed",
            "background_food_detection": {
                "status": "completed" if background_food_validated else "unavailable",
                "food_detections": selected_candidate["food_detections"],
                "passed": background_food_free if background_food_validated else None,
            },
            "geometry": {
                "camera_angle": selected_angle,
                "placement": placement_metrics["placement"],
                "width_ratio": placement_metrics["width_ratio"],
                "passed": geometry_valid,
            },
        }
        if background_food_validated and not background_food_free:
            rejected_path = self.config.paths.intermediate_dir / f"{input_path.stem}_rejected_composite.jpg"
            save_image(processed, rejected_path, self.config.image.jpeg_quality)
            debug_artifacts["rejected_composite"] = str(rejected_path)
            return self._rejected_result(
                report_path,
                input_path=input_path,
                foreground_path=foreground_path,
                stages=stages,
                validation=validation_data,
                status="background_food_detected",
                reason="생성 배경에서 음식이 검출되어 합성 결과를 저장하지 않았습니다.",
                debug_artifacts=debug_artifacts,
            )
        if not geometry_valid:
            return self._rejected_result(
                report_path,
                input_path=input_path,
                foreground_path=foreground_path,
                stages=stages,
                validation=validation_data,
                status="geometry_validation_failed",
                reason="전경 배치 기하 검증에 실패하여 합성 결과를 저장하지 않았습니다.",
                debug_artifacts=debug_artifacts,
            )
        if not semantic_passed:
            rejected_path = self.config.paths.intermediate_dir / f"{input_path.stem}_rejected_composite.jpg"
            save_image(processed, rejected_path, self.config.image.jpeg_quality)
            debug_artifacts["rejected_composite"] = str(rejected_path)
            return self._rejected_result(
                report_path,
                input_path=input_path,
                foreground_path=foreground_path,
                stages=stages,
                validation=validation_data,
                status="semantic_validation_failed",
                reason="OpenCLIP 검증 실패: 합성 광고 이미지를 저장하지 않고 원본 전경/원본 이미지를 반환합니다.",
                debug_artifacts=debug_artifacts,
            )

        output_path = self.config.paths.output_dir / f"{input_path.stem}_background_replaced.jpg"
        save_image(processed, output_path, self.config.image.jpeg_quality)
        debug_artifacts["final_composite"] = str(output_path)
        self._write_report(
            report_path,
            input_path=input_path,
            output_path=output_path,
            foreground_path=foreground_path,
            stages=stages,
            validation=validation_data,
            status="completed",
            reason=None,
            debug_artifacts=debug_artifacts,
        )
        return BackgroundReplacementResult(
            output_path=output_path,
            report_path=report_path,
            foreground_path=foreground_path,
            passed=validation.passed,
            status="completed",
        )
