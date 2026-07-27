from __future__ import annotations

import argparse
import json
import sys
import traceback
from pathlib import Path

from app.core.config import load_config
from app.pipelines.background_replacement_pipeline import BackgroundReplacementPipeline


def main() -> int:
    parser = argparse.ArgumentParser(description="음식·용기 전경 보존 배경 교체 파이프라인")
    parser.add_argument("--input", required=True, help="입력 음식 사진")
    parser.add_argument("--metadata", help="배경 프롬프트용 UTF-8 JSON 파일")
    parser.add_argument("--config", default="configs/pipeline.yaml")
    parser.add_argument(
        "--detector-profile",
        choices=("food_specialized", "coco_yolo11n"),
        help="음식 특화 best.pt 또는 기본 COCO yolo11n.pt 탐지기를 이번 실행에만 선택합니다.",
    )
    parser.add_argument(
        "--enable-matting",
        action="store_true",
        help="호환성 옵션입니다. BiRefNet은 사용하지 않고 SAM 알파만 사용합니다.",
    )
    parser.add_argument(
        "--enable-background-generator", action="store_true", help="배경 생성기를 활성화합니다."
    )
    parser.add_argument(
        "--diagnostic-center-fallback",
        action="store_true",
        help="연결 테스트에서만 탐지 실패 시 중앙 사각형을 사용합니다. 운영에서는 사용하지 마세요.",
    )
    parser.add_argument(
        "--business-type",
        help="Override metadata business_type for this run.",
    )
    parser.add_argument(
        "--desired-mood",
        help="Override metadata desired_mood for this run.",
    )
    parser.add_argument(
        "--composition-mode",
        choices=("preserve_original_plate", "generated_plate"),
        help=(
            "preserve_original_plate keeps the original plate with the food; "
            "generated_plate extracts food only and places it on the generated plate."
        ),
    )
    parser.add_argument(
        "--allow-sam-food-mask-for-generated-plate",
        action="store_true",
        help="Allow generated_plate tests to use the SAM food mask when food_visible is unavailable.",
    )
    parser.add_argument(
        "--enable-hq-sam",
        action="store_true",
        help="Enable optional SAM-HQ candidate masks for this run.",
    )
    parser.add_argument(
        "--hq-sam-model-id",
        default=None,
        help="Override the Hugging Face SAM-HQ model id for this run.",
    )
    parser.add_argument(
        "--hq-sam-selection-mode",
        choices=("box_coverage", "hq_sam", "sam2", "larger_area", "patch_missing"),
        default=None,
        help="How to choose between SAM2 and SAM-HQ masks.",
    )
    args = parser.parse_args()
    metadata = json.loads(Path(args.metadata).read_text(encoding="utf-8")) if args.metadata else {}
    if args.business_type:
        metadata["business_type"] = args.business_type
    if args.desired_mood:
        metadata["desired_mood"] = args.desired_mood
    if args.composition_mode:
        metadata["composition_mode"] = args.composition_mode
    if args.allow_sam_food_mask_for_generated_plate:
        metadata["require_food_visible_mask"] = False
    try:
        config = load_config(args.config)
        if args.detector_profile:
            config.models.setdefault("foreground_detector", {})[
                "active_profile"
            ] = args.detector_profile
        # BiRefNet은 기존·생성 접시 모드 모두에서 사용하지 않는다. 과거 노트북의
        # --enable-matting 인수도 호환성만 유지하며 모델 로딩을 활성화하지 않는다.
        config.models.setdefault("matting", {})["enabled"] = False
        if args.enable_background_generator:
            config.models.setdefault("background_generator", {})["enabled"] = True
        if args.diagnostic_center_fallback:
            config.models.setdefault("foreground_detector", {})[
                "allow_center_fallback_for_diagnostics"
            ] = True
        if args.enable_hq_sam:
            config.models.setdefault("hq_sam", {})["enabled"] = True
        if args.hq_sam_model_id:
            config.models.setdefault("hq_sam", {})["model_id"] = args.hq_sam_model_id
        if args.hq_sam_selection_mode:
            config.models.setdefault("hq_sam", {})[
                "selection_mode"
            ] = args.hq_sam_selection_mode
        result = BackgroundReplacementPipeline(config).run(args.input, metadata)
        print(f"상태: {result.status}")
        print(f"결과 이미지: {result.output_path or '저장하지 않음'}")
        print(f"전경 PNG: {result.foreground_path or '생성하지 않음'}")
        print(f"검증 보고서: {result.report_path}")
        if result.reason:
            print(f"사유: {result.reason}")
        return 0 if result.status == "completed" else 2
    except Exception as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
