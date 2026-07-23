"""학습된 EfficientNet-B0 촬영 각도 분류기를 검증 세트에서 평가한다."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from scripts.angle_classifier_metrics import save_confusion_matrix_png
from scripts.train_efficientnet_b0_angle_classifier import evaluate, make_loaders, select_device


def parse_args() -> argparse.Namespace:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description="EfficientNet-B0 촬영 각도 분류기를 평가합니다.")
    parser.add_argument("--weights", type=Path, required=True)
    parser.add_argument("--data-dir", type=Path, default=root / "data/training/efficientnet_b0_angle/dataset")
    parser.add_argument("--output-dir", type=Path, default=root / "runs/efficientnet_b0_angle_evaluation")
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--num-workers", type=int, default=2)
    parser.add_argument("--device", default="auto")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.weights.is_file():
        raise SystemExit(f"가중치 파일을 찾지 못했습니다: {args.weights}")
    import torch
    from torch import nn
    from torchvision.models import efficientnet_b0

    device = select_device(args.device)
    checkpoint = torch.load(args.weights, map_location="cpu", weights_only=False)
    class_names = checkpoint["class_names"]
    _train_dataset, val_dataset, _train_loader, val_loader = make_loaders(
        args.data_dir, args.batch_size, args.num_workers, device
    )
    if val_dataset.classes != class_names:
        raise SystemExit(f"체크포인트 클래스와 검증 데이터 클래스가 다릅니다: {class_names} / {val_dataset.classes}")
    model = efficientnet_b0(weights=None)
    model.classifier[1] = nn.Linear(model.classifier[1].in_features, len(class_names))
    model.load_state_dict(checkpoint["model_state_dict"])
    model.to(device)
    metrics = evaluate(model, val_loader, class_names, device, nn.CrossEntropyLoss())
    args.output_dir.mkdir(parents=True, exist_ok=True)
    report = {
        "model": str(args.weights.resolve()),
        "evaluated_at_utc": datetime.now(timezone.utc).isoformat(),
        "device": str(device),
        "class_names": class_names,
        "metrics": metrics,
    }
    (args.output_dir / "metrics.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    save_confusion_matrix_png(metrics["confusion_matrix"], class_names, args.output_dir / "confusion_matrix.png")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"평가 보고서: {args.output_dir / 'metrics.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
