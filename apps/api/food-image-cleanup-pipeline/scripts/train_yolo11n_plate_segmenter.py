"""YOLO11-seg로 plate_full 및 food_visible 인스턴스 분할 모델을 학습한다."""

from __future__ import annotations

import argparse
from pathlib import Path


def parse_args() -> argparse.Namespace:
    project_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description="YOLO11-seg 접시 보존 모델을 학습합니다.")
    parser.add_argument("--data", type=Path, default=project_root / "data/training/plate_segmentation/yolo_plate_segmentation/dataset.yaml")
    parser.add_argument("--weights", default="yolo11n-seg.pt")
    parser.add_argument("--epochs", type=int, default=100)
    parser.add_argument("--imgsz", type=int, default=1024)
    parser.add_argument("--batch", type=int, default=-1)
    parser.add_argument("--device", default=None)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--project", type=Path, default=project_root / "runs/plate_segmenter")
    parser.add_argument("--name", default="yolo11n_plate_seg_v1")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.data.is_file():
        raise SystemExit(f"dataset.yaml을 찾을 수 없습니다: {args.data}")
    import torch
    from ultralytics import YOLO

    device = args.device if args.device is not None else ("0" if torch.cuda.is_available() else "cpu")
    model = YOLO(args.weights)
    model.train(
        data=str(args.data), epochs=args.epochs, imgsz=args.imgsz, batch=args.batch,
        device=device, workers=args.workers, seed=args.seed, project=str(args.project),
        name=args.name, pretrained=True, patience=25, optimizer="auto", plots=True,
    )
    best = args.project / args.name / "weights/best.pt"
    if not best.is_file():
        raise SystemExit(f"학습 후 best.pt를 찾지 못했습니다: {best}")
    print(f"학습 모델: {best}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
