"""접시 보존 분할 모델의 정량 평가와 외곽 보존 지표를 기록한다."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def parse_args() -> argparse.Namespace:
    project_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description="YOLO11-seg 접시 보존 모델을 평가합니다.")
    parser.add_argument("--weights", type=Path, required=True)
    parser.add_argument("--data", type=Path, default=project_root / "data/training/plate_segmentation/yolo_plate_segmentation/dataset.yaml")
    parser.add_argument("--imgsz", type=int, default=1024)
    parser.add_argument("--device", default=None)
    parser.add_argument("--output", type=Path, default=project_root / "data/reports/plate_segmenter_metrics.json")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.weights.is_file() or not args.data.is_file():
        raise SystemExit("가중치와 dataset.yaml 경로를 확인하세요.")
    import torch
    from ultralytics import YOLO

    device = args.device if args.device is not None else ("0" if torch.cuda.is_available() else "cpu")
    metrics = YOLO(str(args.weights)).val(data=str(args.data), imgsz=args.imgsz, device=device, split="test", plots=True)
    box = getattr(metrics, "box", None)
    seg = getattr(metrics, "seg", None)
    payload = {
        "weights": str(args.weights),
        "data": str(args.data),
        "box_map50": getattr(box, "map50", None),
        "box_map": getattr(box, "map", None),
        "seg_map50": getattr(seg, "map50", None),
        "seg_map": getattr(seg, "map", None),
        "acceptance": {
            "plate_full_seg_map50_minimum": 0.80,
            "note": "mAP만으로는 접시 테두리 완전성을 보장하지 않으므로 어려운 100장 평가셋의 시각 검토를 병행합니다.",
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
