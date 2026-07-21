"""준비된 음식 데이터셋으로 YOLO11n 음식 위치 탐지 모델을 학습한다."""

from __future__ import annotations

import argparse
from pathlib import Path


def parse_args() -> argparse.Namespace:
    project_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description="YOLO11n 음식 위치 탐지 모델을 학습합니다.")
    parser.add_argument(
        "--data",
        type=Path,
        default=project_root / "data/training/yolo_food_detection/dataset.yaml",
    )
    parser.add_argument("--weights", default="yolo11n.pt", help="사전학습 가중치 또는 기존 체크포인트")
    parser.add_argument("--epochs", type=int, default=100)
    parser.add_argument("--imgsz", type=int, default=960)
    parser.add_argument("--batch", type=int, default=-1, help="-1이면 GPU 메모리에 맞춰 자동 설정")
    parser.add_argument("--device", default=None, help="예: 0, cpu. 생략하면 CUDA 우선 자동 선택")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--project",
        type=Path,
        default=project_root / "runs/yolo_food_detector",
    )
    parser.add_argument("--name", default="yolo11n_food_v1")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.data.is_file():
        raise SystemExit(f"dataset.yaml을 찾을 수 없습니다. 먼저 prepare_yolo_food_dataset.py를 실행하세요: {args.data}")

    import torch
    from ultralytics import YOLO

    device = args.device if args.device is not None else ("0" if torch.cuda.is_available() else "cpu")
    if device == "cpu":
        print("경고: CPU 학습은 매우 오래 걸립니다. 가능하면 CUDA GPU를 사용하세요.")

    model = YOLO(args.weights)
    model.train(
        data=str(args.data),
        epochs=args.epochs,
        imgsz=args.imgsz,
        batch=args.batch,
        device=device,
        workers=args.workers,
        seed=args.seed,
        project=str(args.project),
        name=args.name,
        exist_ok=False,
        pretrained=True,
        patience=25,
        optimizer="auto",
        plots=True,
    )
    # Ultralytics 버전에 따라 train()은 metrics dict를 반환하므로 반환값에 의존하지 않는다.
    run_dir = args.project / args.name
    best_weights = run_dir / "weights/best.pt"
    if not best_weights.is_file():
        raise SystemExit(f"학습은 끝났지만 best.pt를 찾지 못했습니다: {run_dir}")
    print(f"학습 완료 모델: {best_weights}")
    print("다음 단계: 검증 mAP와 실제 네이버 업로드 사진의 탐지 결과를 확인한 뒤에만 운영 설정에 연결하세요.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
