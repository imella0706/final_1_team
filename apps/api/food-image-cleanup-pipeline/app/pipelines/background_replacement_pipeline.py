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
from app.services.generated_plate import find_generated_plate_region
from app.services.grounding_dino import (
    GroundingDINODetector,
    GroundingDINORuntimeError,
    split_plate_and_food_boxes,
)
from app.services.harmonization import harmonize_foreground
from app.services.inpainting import BigLaMaInpainter, removal_mask_from_boxes
from app.services.matting import BiRefNetMattingService
from app.services.plate_mask import PlateMaskService
from app.services.plate_preservation import (
    build_plate_preservation_alpha,
    validate_plate_preservation_alpha,
)
from app.services.plate_segmentation import PlateSegmentationService
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

        # 1차 탐지는 개방형 어휘 GroundingDINO로 수행한다. 음식 전용 YOLO는
        # 모델 다운로드 실패, GPU 메모리 부족, 무검출 때만 부족한 클래스를 보완한다.
        grounding_config = dict(self.config.models.get("grounding_dino_detector", {}))
        if grounding_config.get("enabled", False):
            try:
                grounding_detections = GroundingDINODetector(grounding_config).detect(original)
                plate_boxes, detected_food_boxes, _ = split_plate_and_food_boxes(
                    grounding_detections
                )
                food_boxes = detected_food_boxes
                container_boxes = plate_boxes
                stages["step_2_grounding_dino_detection"] = {
                    "status": "completed",
                    "food_boxes": len(food_boxes),
                    "container_boxes": len(container_boxes),
                    "detections": len(grounding_detections),
                    "model_id": grounding_config.get("model_id"),
                    "prompts": grounding_config.get("prompts", []),
                }
            except GroundingDINORuntimeError as exc:
                stages["step_2_grounding_dino_detection"] = {
                    "status": "unavailable",
                    "reason": str(exc),
                }
        else:
            stages["step_2_grounding_dino_detection"] = {"status": "disabled"}

        # GroundingDINO가 음식 또는 접시 중 하나를 놓친 경우에만 YOLO 결과로
        # 빈 쪽을 보완한다. 성공한 GroundingDINO 상자를 YOLO로 덮어쓰지 않는다.
        try:
            detection = UltralyticsDetector(detector_config).detect(original)
            yolo_food_boxes = [
                item.box_xyxy for item in detection.target_detections if item.label in food_labels
            ]
            yolo_container_boxes = [
                item.box_xyxy
                for item in detection.target_detections
                if item.label in container_labels
            ]
            used_for_food_fallback = not food_boxes and bool(yolo_food_boxes)
            used_for_container_fallback = not container_boxes and bool(yolo_container_boxes)
            if not food_boxes:
                food_boxes = yolo_food_boxes
            if not container_boxes:
                container_boxes = yolo_container_boxes
            stages["step_2_yolo_detection"] = {
                "status": "completed",
                "food_boxes": len(yolo_food_boxes),
                "container_boxes": len(yolo_container_boxes),
                "model": detection.model_name,
                "profile": detector_config.get("active_profile", "direct"),
                "used_as_fallback": used_for_food_fallback or used_for_container_fallback,
                "fallback_for": [
                    name
                    for name, used in (
                        ("food", used_for_food_fallback),
                        ("container", used_for_container_fallback),
                    )
                    if used
                ],
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
                    "reason": "GroundingDINO와 YOLO에서 음식 또는 용기를 찾지 못했습니다.",
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
        stabilized_food, food_stabilization_metrics = matting.stabilize_sam_mask(
            food_segmentation.mask
        )
        stabilized_container, container_stabilization_metrics = matting.stabilize_sam_mask(
            container_segmentation.mask
        )
        # 학습된 접시 전용 모델이 있으면 외곽을 먼저 얻는다. 아직 가중치가
        # 없거나 추론이 실패하면 기존 SAM + 타원/윤곽 보완 경로를 사용한다.
        plate_segmenter_config = dict(self.config.models.get("plate_segmenter", {}))
        learned_plate_mask = None
        learned_food_mask = None
        plate_segmenter_stage: dict[str, Any]
        if plate_segmenter_config.get("enabled", False):
            try:
                learned = PlateSegmentationService(plate_segmenter_config).segment(original)
                learned_plate_mask = learned.plate_mask
                learned_food_mask = learned.food_mask
                plate_segmenter_stage = {
                    "status": "completed" if learned_plate_mask is not None else "no_plate_mask",
                    "detections": learned.detections,
                    "metrics": learned.metrics,
                    "weights": plate_segmenter_config.get("weights"),
                }
            except (FileNotFoundError, RuntimeError, ImportError) as exc:
                plate_segmenter_stage = {"status": "fallback", "reason": str(exc)}
        else:
            plate_segmenter_stage = {"status": "disabled"}

        plate_seed_mask = learned_plate_mask if learned_plate_mask is not None else structural_foreground
        plate_result = PlateMaskService(
            dict(self.config.models.get("plate_mask", {}))
        ).complete(plate_seed_mask)
        plate_mask_path = self.config.paths.mask_dir / f"{input_path.stem}_plate_mask.png"
        save_image(plate_result.mask, plate_mask_path)
        debug_artifacts["plate_mask"] = str(plate_mask_path)
        # The generated background must never show through the original serving
        # plate.  Keep food and plate as independent source-pixel layers.
        # ``food_visible`` is optional while the plate segmentation model is
        # being introduced.  A successful plate-only prediction therefore must
        # not make the whole pipeline fail: keep the SAM food mask as the
        # authoritative fallback and merge an all-zero learned mask.
        if learned_food_mask is None or learned_food_mask.shape != stabilized_food.shape:
            learned_food_mask_for_merge = np.zeros_like(stabilized_food)
            plate_segmenter_stage["food_visible_source"] = "sam_fallback"
        else:
            learned_food_mask_for_merge = learned_food_mask
            plate_segmenter_stage["food_visible_source"] = "plate_segmenter"
        stabilized_food_source = foreground_mask(stabilized_food, learned_food_mask_for_merge)
        stabilized_foreground = foreground_mask(
            foreground_mask(stabilized_food_source, stabilized_container), plate_result.mask
        )
        generated_plate_config = dict(
            self.config.models.get("generated_plate_composition", {})
        )
        generated_plate_mode = bool(generated_plate_config.get("enabled", True)) and str(
            generated_plate_config.get("mode", "generated_plate")
        ).lower() == "generated_plate"
        has_learned_food_visible_mask = (
            learned_food_mask is not None
            and learned_food_mask.shape == stabilized_food.shape
            and bool(np.any(learned_food_mask))
        )
        # 생성 접시 모드에서는 원본 접시·식탁보를 최종 전경에서 제외한다.
        # 음식 마스크가 비어 있는 예외 상황만 기존 구조 마스크로 되돌려 안전하게 중단한다.
        food_only_mask = (
            stabilized_food_source
            if np.any(stabilized_food_source)
            else stabilized_food
        )
        active_foreground_mask = food_only_mask if generated_plate_mode else stabilized_foreground
        stabilization_metrics = {
            "food": food_stabilization_metrics,
            "container": container_stabilization_metrics,
            "plate": plate_result.metrics,
            "plate_segmenter": plate_segmenter_stage,
        }
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
            "plate_mask_path": str(plate_mask_path),
            "stabilization": stabilization_metrics,
            "composition_mode": "generated_plate" if generated_plate_mode else "preserve_original_plate",
        }
        stages["step_2_plate_full_segmentation"] = plate_segmenter_stage

        food_mask_path = self.config.paths.mask_dir / f"{input_path.stem}_food_sam_mask.png"
        save_image(stabilized_food_source, food_mask_path)
        debug_artifacts["food_sam_mask"] = str(food_mask_path)

        if (
            generated_plate_mode
            and bool(generated_plate_config.get("require_food_visible_mask", True))
            and not has_learned_food_visible_mask
        ):
            stages["step_2_food_visible_segmentation"] = {
                "status": "required_mask_unavailable",
                "reason": "generated_plate 모드는 원본 접시를 제외하기 위해 학습된 food_visible 분할 마스크가 필요합니다.",
                "food_mask_path": str(food_mask_path),
                "plate_segmenter_enabled": bool(plate_segmenter_config.get("enabled", False)),
                "plate_segmenter_weights": plate_segmenter_config.get("weights"),
            }
            return self._rejected_result(
                report_path,
                input_path=input_path,
                foreground_path=None,
                stages=stages,
                validation=None,
                status="food_visible_segmentation_required",
                reason="원본 접시를 제거하는 합성을 위해 food_visible 분할 모델이 필요합니다. YOLO11-seg 접시·음식 모델을 학습한 뒤 plate_segmenter를 활성화하세요.",
                debug_artifacts=debug_artifacts,
            )
        # 최종 알파는 항상 SAM 음식·접시 분할 마스크만 사용한다. BiRefNet은
        # 이 파이프라인에서 호출하거나 모델 가중치를 불러오지 않는다.
        matting_input = active_foreground_mask
        plate_preservation_config = dict(
            self.config.models.get("plate_preservation", {})
        )
        # The serving plate is never sent through the generic matting fallback.
        # That fallback feathers both sides of the rim and was the direct cause
        # of the transparent / missing plate edge in the composite.
        plate_alpha = build_plate_preservation_alpha(
            plate_result.mask,
            feather_kernel=int(plate_preservation_config.get("feather_kernel", 5)),
        )
        plate_alpha_path = self.config.paths.mask_dir / f"{input_path.stem}_plate_alpha.png"
        save_image(plate_alpha, plate_alpha_path)
        debug_artifacts["plate_preservation_alpha"] = str(plate_alpha_path)
        food_sam_alpha = matting._sam_fallback(
            matting_input, "sam_only_alpha_pipeline"
        ).alpha
        alpha = (
            food_sam_alpha
            if generated_plate_mode
            else np.maximum(food_sam_alpha, plate_alpha).astype(np.uint8)
        )
        plate_validation = validate_plate_preservation_alpha(
            plate_result.mask,
            alpha,
            minimum_coverage=float(plate_preservation_config.get("minimum_coverage", 0.995)),
            maximum_internal_gap_ratio=float(
                plate_preservation_config.get("maximum_internal_gap_ratio", 0.002)
            ),
            validation_erosion_px=int(
                plate_preservation_config.get("validation_erosion_px", 2)
            ),
        )
        sam_plate_validation = validate_plate_preservation_alpha(
            plate_result.mask,
            alpha,
            minimum_coverage=float(plate_preservation_config.get("minimum_coverage", 0.995)),
            maximum_internal_gap_ratio=float(
                plate_preservation_config.get("maximum_internal_gap_ratio", 0.002)
            ),
            validation_erosion_px=int(
                plate_preservation_config.get("validation_erosion_px", 2)
            ),
        )
        alpha_path = self.config.paths.mask_dir / f"{input_path.stem}_sam_alpha.png"
        save_image(alpha, alpha_path)
        debug_artifacts["sam_alpha_mask"] = str(alpha_path)
        stages["step_3_sam_alpha"] = {
            "status": "completed",
            "provider": "sam",
            "alpha_path": str(alpha_path),
            "metrics": {"sam_area": int(np.count_nonzero(matting_input))},
        }
        stages["step_3_plate_preservation"] = {
            "status": (
                "skipped_generated_plate_mode"
                if generated_plate_mode
                else "completed" if plate_validation.metrics["passed"] else "failed"
            ),
            "plate_alpha_path": str(plate_alpha_path),
            "final_alpha": plate_validation.metrics,
            "sam_alpha": sam_plate_validation.metrics,
            "used_in_final_alpha": not generated_plate_mode,
        }
        if not generated_plate_mode and not plate_validation.metrics["passed"]:
            return self._rejected_result(
                report_path,
                input_path=input_path,
                foreground_path=None,
                stages=stages,
                validation=None,
                status="plate_preservation_failed",
                reason="접시 전체 보존 검증에 실패하여 합성 결과를 저장하지 않습니다.",
                debug_artifacts=debug_artifacts,
            )

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
        prompt_metadata = {
            **metadata,
            "camera_angle_label": selected_angle,
            "generated_plate": generated_plate_mode,
        }
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
        max_candidate_attempts = max(
            candidate_count,
            int(generator_config.get("max_candidate_attempts", candidate_count)),
        )
        background_candidates: list[tuple[np.ndarray, dict[str, Any]]] = []
        valid_background_candidates: list[tuple[np.ndarray, dict[str, Any]]] = []
        placement_config = dict(self.config.models.get("foreground_placement", {}))
        planned_width_ratio = float(
            placement_config.get(
                "top_width_ratio" if selected_angle == "top" else "angle_45_width_ratio",
                0.40 if selected_angle == "top" else 0.48,
            )
        )
        # 생성 접시 모드에서는 후보마다 탐지된 접시 중심을 실제 배치 기준으로 쓴다.
        # 기존 모드에서는 화면 중앙의 배치 영역만 감사한다.
        region_half_size = min(0.38, max(0.24, planned_width_ratio * 0.5 + 0.08))
        placement_region = (
            0.5 - region_half_size,
            0.5 - region_half_size,
            0.5 + region_half_size,
            0.5 + region_half_size,
        )

        def count_detections_in_placement_region(detections: list[Any], image_width: int, image_height: int) -> int:
            rx1, ry1, rx2, ry2 = placement_region
            count = 0
            for detection in detections:
                x1, y1, x2, y2 = detection.box_xyxy
                box_center_x = ((x1 + x2) * 0.5) / max(image_width, 1)
                box_center_y = ((y1 + y2) * 0.5) / max(image_height, 1)
                if rx1 <= box_center_x <= rx2 and ry1 <= box_center_y <= ry2:
                    count += 1
            return count

        food_audit_detector = UltralyticsDetector(detector_config)
        object_audit_config = dict(self.config.models.get("background_audit_detector", {}))
        object_audit_detector = UltralyticsDetector(object_audit_config)
        for index in range(max_candidate_attempts):
            candidate_seed = None if base_seed is None else int(base_seed) + index
            candidate = generator.generate(
                prompt_info.prompt, original.shape[1], original.shape[0], seed=candidate_seed
            )
            candidate = fit_background(candidate, original.shape[:2])
            generated_plate_region = (
                find_generated_plate_region(candidate) if generated_plate_mode else None
            )
            detected_food_count: int | None = None
            detected_object_count: int | None = None
            center_object_count: int | None = None
            detection_error: str | None = None
            object_audit_error: str | None = None
            try:
                candidate_detection = food_audit_detector.detect(candidate)
                detected_food_count = sum(
                    item.label in food_labels for item in candidate_detection.target_detections
                )
            except Exception as exc:
                detection_error = type(exc).__name__
            try:
                object_detection = object_audit_detector.detect(candidate)
                detected_object_count = len(object_detection.target_detections)
                center_object_count = count_detections_in_placement_region(
                    object_detection.target_detections,
                    candidate.shape[1],
                    candidate.shape[0],
                )
            except Exception as exc:
                object_audit_error = type(exc).__name__
            score = score_background_candidate(
                candidate,
                original,
                food_detections=detected_food_count,
                object_detections=detected_object_count,
                center_object_detections=center_object_count,
                camera_angle=selected_angle,
                requires_generated_plate=generated_plate_mode,
                generated_plate_score=(
                    generated_plate_region.score
                    if generated_plate_region is not None and generated_plate_region.found
                    else None
                ),
                minimum_geometry_score=float(
                    generated_plate_config.get("minimum_plate_score", 0.45)
                ),
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
                        "object_detections": detected_object_count,
                        "placement_area_object_detections": center_object_count,
                        "placement_region_normalized_xyxy": [round(value, 4) for value in placement_region],
                        "geometry_score": score.geometry_score,
                        "generated_plate_score": score.generated_plate_score,
                        "generated_plate": (
                            {
                                "found": generated_plate_region.found,
                                "center_x": round(generated_plate_region.center_x, 4),
                                "center_y": round(generated_plate_region.center_y, 4),
                                "width_ratio": round(generated_plate_region.width_ratio, 4),
                                "height_ratio": round(generated_plate_region.height_ratio, 4),
                                "score": round(generated_plate_region.score, 4),
                                "source": generated_plate_region.source,
                            }
                            if generated_plate_region is not None
                            else None
                        ),
                        "valid": score.valid,
                        "rejection_reasons": list(score.rejection_reasons),
                        "food_detection_audit_error": detection_error,
                        "object_detection_audit_error": object_audit_error,
                    },
                )
            )
            if score.valid:
                valid_background_candidates.append(background_candidates[-1])
                if len(valid_background_candidates) >= candidate_count:
                    break
        if not valid_background_candidates:
            stages["step_8_background_generation"] = {
                "status": "candidate_generation_failed",
                "requested_candidate_count": candidate_count,
                "attempt_count": len(background_candidates),
                "candidates": [candidate_metadata for _, candidate_metadata in background_candidates],
            }
            return self._rejected_result(
                report_path,
                input_path=input_path,
                foreground_path=foreground_path,
                stages=stages,
                validation=None,
                status="background_candidate_generation_failed",
                reason="음식·식기·시점·테이블 평면 조건을 모두 통과한 빈 배경 후보를 만들지 못했습니다.",
                debug_artifacts=debug_artifacts,
            )
        background, selected_candidate = max(valid_background_candidates, key=lambda item: item[1]["score"])
        background_path = self.config.paths.intermediate_dir / f"{input_path.stem}_generated_background.jpg"
        save_image(background, background_path, self.config.image.jpeg_quality)
        stages["step_8_background_generation"] = {
            "status": "completed",
            "background_path": str(background_path),
            "candidate_count": len(valid_background_candidates),
            "attempt_count": len(background_candidates),
            "selected_candidate": selected_candidate["index"],
            "candidates": [metadata for _, metadata in background_candidates],
        }

        selected_plate = selected_candidate.get("generated_plate")
        placement_anchor: tuple[float, float] | None = None
        width_ratio = planned_width_ratio
        if generated_plate_mode and selected_plate and selected_plate.get("found"):
            placement_anchor = (
                float(selected_plate["center_x"]),
                float(selected_plate["center_y"]),
            )
            plate_short_side = min(
                float(selected_plate["width_ratio"]),
                float(selected_plate["height_ratio"]),
            )
            width_ratio = float(
                np.clip(
                    plate_short_side
                    * float(generated_plate_config.get("food_width_ratio_of_plate", 0.56)),
                    float(generated_plate_config.get("minimum_food_width_ratio", 0.12)),
                    float(generated_plate_config.get("maximum_food_width_ratio", 0.42)),
                )
            )

        def compose(candidate_alpha: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray, dict[str, Any]]:
            placed_foreground, placed_alpha, placement_metrics = place_foreground(
                cleaned,
                candidate_alpha,
                placement=prompt_info.placement,
                width_ratio=width_ratio,
                safe_padding_px=int(placement_config.get("safe_padding_px", 28)),
                canvas_margin_px=int(placement_config.get("canvas_margin_px", 42)),
                alpha_crop_threshold=int(placement_config.get("alpha_crop_threshold", 1)),
                anchor_center=placement_anchor,
                minimum_width_ratio=(0.08 if generated_plate_mode else 0.30),
            )
            shadow_config = dict(self.config.models.get("contact_shadow", {}))
            if selected_angle == "top" and not generated_plate_mode:
                # 탑뷰 접시는 이동한 실루엣 그림자 대신 접시 테두리의 얇은 접촉 고리가 자연스럽다.
                shadow_config.update(
                    {
                        "mode": "rim",
                        "rim_width": 4,
                        "vertical_offset": 0,
                        "horizontal_offset": 0,
                        "blur_radius": 9,
                        "opacity": 0.10,
                    }
                )
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
            "target_width_ratio_range": [
                0.08 if generated_plate_mode else 0.30,
                0.70,
            ],
            "composition_mode": "generated_plate" if generated_plate_mode else "preserve_original_plate",
            "generated_plate": selected_plate,
        }
        stages["step_10_contact_shadow"] = {
            "status": "completed",
            "light_direction": prompt_info.light_direction,
            "camera_angle": selected_angle,
            "mode": "rim" if selected_angle == "top" and not generated_plate_mode else "drop",
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
                    original, active_foreground_mask, candidate, candidate_alpha
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
        final_mask_label = "sam"
        if semantic_config.get("enabled", False):
            semantic_passed = evaluate(processed, placed_alpha, "sam")
        else:
            attempts.append(
                {"mask": "not_evaluated", "similarity": None, "passed": False, "error": "disabled"}
            )

        stages["step_13_foreground_validation"] = {
            "status": "completed" if semantic_passed else "failed",
            "minimum_similarity": minimum_similarity,
            "attempts": attempts,
            "final_mask": final_mask_label,
            "background_placement_area_free": selected_candidate[
                "placement_area_object_detections"
            ] in (None, 0),
            "geometry": {
                "camera_angle": selected_angle,
                "placement": placement_metrics["placement"],
                "width_ratio": placement_metrics["width_ratio"],
                "within_target_range": max(0.08 if generated_plate_mode else 0.30, width_ratio - 0.08)
                <= float(placement_metrics["width_ratio"])
                <= min(0.70, width_ratio + 0.08),
            },
        }
        before_foreground = analyze_quality(
            original, self.config.quality, mask=active_foreground_mask
        )
        after_foreground = analyze_quality(
            processed, self.config.quality, mask=active_foreground_mask
        )
        validation = validate_result(before_foreground, after_foreground, self.config.validation)
        validation_data = validation.to_dict()
        validation_data["scope"] = (
            "food_only_foreground" if generated_plate_mode else "stabilized_foreground_only"
        )
        background_object_validated = selected_candidate["placement_area_object_detections"] is not None
        background_placement_area_free = selected_candidate["placement_area_object_detections"] == 0
        minimum_placement_width = max(0.08 if generated_plate_mode else 0.30, width_ratio - 0.08)
        maximum_placement_width = min(0.70, width_ratio + 0.08)
        geometry_valid = bool(
            minimum_placement_width <= float(placement_metrics["width_ratio"]) <= maximum_placement_width
            and placement_metrics["placement"] == prompt_info.placement
        )
        stages["step_14_background_geometry_validation"] = {
            "status": "completed"
            if (not background_object_validated or background_placement_area_free) and geometry_valid
            else "failed",
            "background_placement_area_detection": {
                "status": "completed" if background_object_validated else "unavailable",
                "object_detections": selected_candidate["placement_area_object_detections"],
                "passed": background_placement_area_free if background_object_validated else None,
            },
            "geometry": {
                "camera_angle": selected_angle,
                "placement": placement_metrics["placement"],
                "width_ratio": placement_metrics["width_ratio"],
                "allowed_width_ratio_range": [
                    round(minimum_placement_width, 4),
                    round(maximum_placement_width, 4),
                ],
                "passed": geometry_valid,
                "generated_plate": selected_plate,
            },
        }
        if background_object_validated and not background_placement_area_free:
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
