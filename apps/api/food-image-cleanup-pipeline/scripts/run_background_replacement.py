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
    args = parser.parse_args()
    metadata = json.loads(Path(args.metadata).read_text(encoding="utf-8")) if args.metadata else {}
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
