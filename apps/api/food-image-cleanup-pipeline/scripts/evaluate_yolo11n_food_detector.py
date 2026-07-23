"""학습된 YOLO11n 음식 위치 탐지 모델을 검증 세트에서 평가한다."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path


def parse_args() -> argparse.Namespace:
    project_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description="YOLO11n 음식 탐지 모델의 검증 지표를 저장합니다.")
    parser.add_argument("--weights", type=Path, required=True, help="학습 결과 best.pt 경로")
    parser.add_argument(
        "--data",
        type=Path,
        default=project_root / "data/training/yolo_food_detection/dataset.yaml",
    )
    parser.add_argument("--imgsz", type=int, default=960)
    parser.add_argument("--device", default=None, help="예: 0, cpu. 생략하면 CUDA 우선 자동 선택")
    parser.add_argument(
        "--project",
        type=Path,
        default=project_root / "runs/yolo_food_detector_evaluation",
    )
    parser.add_argument("--name", default="yolo11n_food_v1")
    return parser.parse_args()


def metric_value(value: object) -> float | None:
    try:
        return float(value)  # numpy scalar도 JSON 숫자로 바꾼다.
    except (TypeError, ValueError):
        return None


def main() -> int:
    args = parse_args()
    if not args.weights.is_file():
        raise SystemExit(f"가중치 파일을 찾을 수 없습니다: {args.weights}")
    if not args.data.is_file():
        raise SystemExit(f"dataset.yaml을 찾을 수 없습니다: {args.data}")

    import torch
    from ultralytics import YOLO

    device = args.device if args.device is not None else ("0" if torch.cuda.is_available() else "cpu")
    model = YOLO(str(args.weights))
    metrics = model.val(
        data=str(args.data),
        imgsz=args.imgsz,
        device=device,
        split="val",
        plots=True,
        project=str(args.project),
        name=args.name,
        exist_ok=True,
    )

    run_dir = Path(getattr(metrics, "save_dir", args.project / args.name))
    summary = {
        "model": str(args.weights.resolve()),
        "dataset": str(args.data.resolve()),
        "evaluated_at_utc": datetime.now(timezone.utc).isoformat(),
        "device": str(device),
        "class_names": {"0": "food"},
        "metrics": {
            "precision": metric_value(metrics.box.mp),
            "recall": metric_value(metrics.box.mr),
            "mAP50": metric_value(metrics.box.map50),
            "mAP75": metric_value(metrics.box.map75),
            "mAP50_95": metric_value(metrics.box.map),
        },
        "result_directory": str(run_dir.resolve()),
    }
    report_path = run_dir / "metrics.json"
    report_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"평가 보고서: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
