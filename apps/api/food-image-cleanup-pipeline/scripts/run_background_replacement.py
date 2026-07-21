from __future__ import annotations

import argparse
import json
import sys
import traceback
from pathlib import Path

from app.core.config import load_config
from app.pipelines.background_replacement_pipeline import BackgroundReplacementPipeline


def main() -> int:
    parser = argparse.ArgumentParser(description="음식·용기 보존 배경 교체 파이프라인")
    parser.add_argument("--input", required=True, help="입력 음식 사진")
    parser.add_argument("--metadata", help="배경 프롬프트용 UTF-8 JSON 파일")
    parser.add_argument("--config", default="configs/pipeline.yaml")
    parser.add_argument("--enable-matting", action="store_true", help="BiRefNet 알파 매트를 활성화합니다")
    parser.add_argument("--enable-background-generator", action="store_true", help="FLUX.1 Schnell 배경 생성을 활성화합니다")
    args = parser.parse_args()
    metadata = json.loads(Path(args.metadata).read_text(encoding="utf-8")) if args.metadata else {}
    try:
        config = load_config(args.config)
        if args.enable_matting:
            config.models.setdefault("matting", {})["enabled"] = True
        if args.enable_background_generator:
            config.models.setdefault("background_generator", {})["enabled"] = True
        result = BackgroundReplacementPipeline(config).run(args.input, metadata)
        print(f"결과 이미지: {result.output_path}")
        print(f"전경 PNG: {result.foreground_path}")
        print(f"검증 보고서: {result.report_path}")
        print(f"검증 통과: {result.passed}")
        return 0
    except Exception as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
