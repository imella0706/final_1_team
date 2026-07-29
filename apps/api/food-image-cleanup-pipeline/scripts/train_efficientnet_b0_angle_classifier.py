"""torchvision EfficientNet-B0로 음식 사진 촬영 각도 분류기를 학습한다."""

from __future__ import annotations

import argparse
import csv
import json
import random
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    from tqdm.auto import tqdm
except ImportError:  # 최소 환경에서는 진행률 표시 없이 학습은 계속할 수 있다.
    class _ProgressFallback:
        def __init__(self, iterable):
            self.iterable = iterable

        def __iter__(self):
            return iter(self.iterable)

        def set_postfix(self, **_kwargs) -> None:
            return None

    def tqdm(iterable, **_kwargs):
        return _ProgressFallback(iterable)

from scripts.angle_classifier_metrics import classification_metrics, save_confusion_matrix_png


def parse_args() -> argparse.Namespace:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description="EfficientNet-B0 촬영 각도 분류기를 학습합니다.")
    parser.add_argument("--data-dir", type=Path, default=root / "data/training/efficientnet_b0_angle/dataset")
    parser.add_argument("--output-dir", type=Path, default=root / "runs/efficientnet_b0_angle")
    parser.add_argument("--epochs", type=int, default=50)
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--learning-rate", type=float, default=3e-4, help="새 분류기 헤드 학습률")
    parser.add_argument("--backbone-learning-rate", type=float, default=5e-5, help="사전학습 백본 미세조정 학습률")
    parser.add_argument("--weight-decay", type=float, default=1e-4)
    parser.add_argument("--num-workers", type=int, default=2)
    parser.add_argument("--patience", type=int, default=10)
    parser.add_argument("--freeze-epochs", type=int, default=5, help="초기 백본 동결 에포크 수")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--device", default="auto", help="auto, cpu, cuda 또는 cuda:0")
    return parser.parse_args()


def select_device(requested: str):
    import torch

    if requested == "auto":
        return torch.device("cuda" if torch.cuda.is_available() else "cpu")
    return torch.device(requested)


def make_loaders(data_dir: Path, batch_size: int, num_workers: int, device):
    from torch.utils.data import DataLoader
    from torchvision import datasets, transforms
    from torchvision.models import EfficientNet_B0_Weights

    weights = EfficientNet_B0_Weights.DEFAULT
    normalize = transforms.Normalize(mean=weights.transforms().mean, std=weights.transforms().std)
    train_transform = transforms.Compose(
        [
            transforms.Resize(256),
            # 촬영 각도는 접시 테두리·테이블 평면 등 전역 구조가 중요하다.
            transforms.RandomResizedCrop(224, scale=(0.92, 1.0), ratio=(0.9, 1.1)),
            transforms.RandomHorizontalFlip(p=0.5),
            transforms.ColorJitter(brightness=0.10, contrast=0.10, saturation=0.05),
            transforms.ToTensor(),
            normalize,
        ]
    )
    eval_transform = transforms.Compose([transforms.Resize(256), transforms.CenterCrop(224), transforms.ToTensor(), normalize])
    train_dataset = datasets.ImageFolder(data_dir / "train", transform=train_transform)
    val_dataset = datasets.ImageFolder(data_dir / "val", transform=eval_transform)
    if train_dataset.classes != val_dataset.classes:
        raise RuntimeError(f"train/val 클래스가 다릅니다: {train_dataset.classes} / {val_dataset.classes}")
    common = {"batch_size": batch_size, "num_workers": num_workers, "pin_memory": device.type == "cuda"}
    return (
        train_dataset,
        val_dataset,
        DataLoader(train_dataset, shuffle=True, **common),
        DataLoader(val_dataset, shuffle=False, **common),
    )


def evaluate(model, loader, class_names: list[str], device, criterion, epoch: int | None = None) -> dict[str, object]:
    import torch

    model.eval()
    confusion = [[0 for _ in class_names] for _ in class_names]
    loss_total, sample_count = 0.0, 0
    description = f"Epoch {epoch:02d} 검증" if epoch is not None else "검증"
    with torch.no_grad():
        progress = tqdm(loader, desc=description, dynamic_ncols=True, leave=False, file=sys.stdout)
        for images, targets in progress:
            images, targets = images.to(device, non_blocking=True), targets.to(device, non_blocking=True)
            logits = model(images)
            loss = criterion(logits, targets)
            batch_size = targets.size(0)
            loss_total += float(loss.item()) * batch_size
            sample_count += batch_size
            predictions = logits.argmax(dim=1)
            for actual, predicted in zip(targets.tolist(), predictions.tolist()):
                confusion[actual][predicted] += 1
            progress.set_postfix(val_loss=f"{loss_total / sample_count:.4f}")
    metrics = classification_metrics(confusion, class_names)
    metrics["loss"] = loss_total / sample_count if sample_count else 0.0
    return metrics


def save_history_csv(history: list[dict[str, object]], output_path: Path) -> None:
    columns = (
        "epoch", "train_loss", "train_accuracy", "loss", "accuracy", "balanced_accuracy", "macro_f1",
        "learning_rate", "backbone_learning_rate",
    )
    with output_path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=columns)
        writer.writeheader()
        for row in history:
            writer.writerow({column: row.get(column) for column in columns})


def save_training_curves(history: list[dict[str, object]], output_path: Path) -> None:
    """매 epoch마다 갱신되는 손실·평가 지표 그래프를 저장한다."""

    if not history:
        return
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("matplotlib이 없어 training_curves.png 저장을 건너뜁니다.", flush=True)
        return

    epochs = [int(row["epoch"]) for row in history]
    figure, loss_axis = plt.subplots(figsize=(10, 6))
    loss_axis.plot(epochs, [float(row["train_loss"]) for row in history], marker="o", label="Train loss")
    loss_axis.plot(epochs, [float(row["loss"]) for row in history], marker="o", label="Validation loss")
    loss_axis.set_xlabel("Epoch")
    loss_axis.set_ylabel("Loss")
    loss_axis.grid(True, alpha=0.3)
    metric_axis = loss_axis.twinx()
    metric_axis.plot(epochs, [float(row["accuracy"]) for row in history], "s--", label="Accuracy")
    metric_axis.plot(epochs, [float(row["balanced_accuracy"]) for row in history], "s--", label="Balanced accuracy")
    metric_axis.plot(epochs, [float(row["macro_f1"]) for row in history], "^:", label="Macro F1")
    metric_axis.set_ylabel("Score")
    metric_axis.set_ylim(0.0, 1.0)
    left_lines, left_labels = loss_axis.get_legend_handles_labels()
    right_lines, right_labels = metric_axis.get_legend_handles_labels()
    loss_axis.legend(left_lines + right_lines, left_labels + right_labels, loc="best")
    figure.tight_layout()
    figure.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close(figure)


def set_backbone_trainable(model, trainable: bool) -> None:
    for parameter in model.features.parameters():
        parameter.requires_grad = trainable


def main() -> int:
    args = parse_args()
    if not (args.data_dir / "train").is_dir() or not (args.data_dir / "val").is_dir():
        raise SystemExit(f"ImageFolder 데이터셋이 없습니다. 데이터 준비를 먼저 실행하세요: {args.data_dir}")
    if args.epochs < 1 or args.batch_size < 1 or args.freeze_epochs < 0:
        raise SystemExit("epochs·batch-size는 1 이상, freeze-epochs는 0 이상이어야 합니다.")

    import torch
    from torch import nn
    from torchvision.models import EfficientNet_B0_Weights, efficientnet_b0

    random.seed(args.seed)
    torch.manual_seed(args.seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(args.seed)
    device = select_device(args.device)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    train_dataset, val_dataset, train_loader, val_loader = make_loaders(
        args.data_dir, args.batch_size, args.num_workers, device
    )
    class_names = train_dataset.classes
    model = efficientnet_b0(weights=EfficientNet_B0_Weights.DEFAULT)
    model.classifier[1] = nn.Linear(model.classifier[1].in_features, len(class_names))
    set_backbone_trainable(model, trainable=args.freeze_epochs <= 0)
    model.to(device)

    class_counts = [train_dataset.targets.count(index) for index in range(len(class_names))]
    class_weights = torch.tensor(
        [sum(class_counts) / (len(class_counts) * count) for count in class_counts], dtype=torch.float32, device=device
    )
    criterion = nn.CrossEntropyLoss(weight=class_weights, label_smoothing=0.05)
    optimizer = torch.optim.AdamW(
        [
            {"params": model.features.parameters(), "lr": args.backbone_learning_rate},
            {"params": model.classifier.parameters(), "lr": args.learning_rate},
        ],
        weight_decay=args.weight_decay,
    )
    scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(optimizer, mode="max", factor=0.5, patience=2)
    scaler = torch.amp.GradScaler("cuda", enabled=device.type == "cuda")

    print("=" * 80, flush=True)
    print("EfficientNet-B0 촬영 각도 분류 학습 시작", flush=True)
    print(f"장치: {device}", flush=True)
    print(f"클래스: {class_names}", flush=True)
    print(f"클래스별 학습 이미지: {dict(zip(class_names, class_counts))}", flush=True)
    print(f"학습/검증 이미지: {len(train_dataset)} / {len(val_dataset)}", flush=True)
    print(f"에포크: {args.epochs}, 초기 백본 동결: {args.freeze_epochs}", flush=True)
    print("=" * 80, flush=True)

    history: list[dict[str, object]] = []
    best_accuracy, stale_epochs = -1.0, 0
    for epoch in range(1, args.epochs + 1):
        if epoch == args.freeze_epochs + 1 and args.freeze_epochs > 0:
            set_backbone_trainable(model, trainable=True)
            print(f"Epoch {epoch}: 백본 동결을 해제하고 미세조정을 시작합니다.", flush=True)
        model.train()
        loss_total, samples, correct = 0.0, 0, 0
        progress = tqdm(
            train_loader, desc=f"Epoch {epoch:02d}/{args.epochs:02d} 학습", dynamic_ncols=True, leave=True, file=sys.stdout
        )
        for images, targets in progress:
            images, targets = images.to(device, non_blocking=True), targets.to(device, non_blocking=True)
            optimizer.zero_grad(set_to_none=True)
            with torch.amp.autocast("cuda", enabled=device.type == "cuda"):
                logits = model(images)
                loss = criterion(logits, targets)
            scaler.scale(loss).backward()
            scaler.step(optimizer)
            scaler.update()
            batch_size = targets.size(0)
            loss_total += float(loss.item()) * batch_size
            samples += batch_size
            predictions = logits.argmax(dim=1)
            correct += int((predictions == targets).sum().item())
            progress.set_postfix(
                loss=f"{loss_total / samples:.4f}",
                acc=f"{correct / samples:.4f}",
                lr=f"{optimizer.param_groups[1]['lr']:.2e}",
            )

        metrics = evaluate(model, val_loader, class_names, device, criterion, epoch=epoch)
        train_loss = loss_total / samples if samples else 0.0
        train_accuracy = correct / samples if samples else 0.0
        metrics.update(
            {
                "epoch": epoch,
                "train_loss": train_loss,
                "train_accuracy": train_accuracy,
                "learning_rate": optimizer.param_groups[1]["lr"],
                "backbone_learning_rate": optimizer.param_groups[0]["lr"],
            }
        )
        history.append(metrics)
        scheduler.step(float(metrics["balanced_accuracy"]))
        save_history_csv(history, args.output_dir / "training_history.csv")
        save_training_curves(history, args.output_dir / "training_curves.png")
        print(
            f"[Epoch {epoch:02d}/{args.epochs:02d}] "
            f"train_loss={train_loss:.4f} | train_acc={train_accuracy:.4f} | "
            f"val_loss={float(metrics['loss']):.4f} | val_acc={float(metrics['accuracy']):.4f} | "
            f"balanced_acc={float(metrics['balanced_accuracy']):.4f} | macro_f1={float(metrics['macro_f1']):.4f}",
            flush=True,
        )

        checkpoint = {
            "model_state_dict": model.state_dict(),
            "class_names": class_names,
            "model_name": "torchvision.efficientnet_b0",
            "image_size": 224,
            "epoch": epoch,
            "metrics": metrics,
        }
        torch.save(checkpoint, args.output_dir / "last.pt")
        if float(metrics["balanced_accuracy"]) > best_accuracy:
            best_accuracy = float(metrics["balanced_accuracy"])
            stale_epochs = 0
            torch.save(checkpoint, args.output_dir / "best.pt")
            save_confusion_matrix_png(metrics["confusion_matrix"], class_names, args.output_dir / "best_confusion_matrix.png")
            print(f"새 최고 모델 저장: balanced_accuracy={best_accuracy:.4f}", flush=True)
        else:
            stale_epochs += 1
            print(f"검증 성능 미개선: {stale_epochs}/{args.patience}", flush=True)
            if stale_epochs >= args.patience:
                print(f"조기 종료: 검증 균형 정확도가 {args.patience}회 연속 개선되지 않았습니다.", flush=True)
                break

    best = torch.load(args.output_dir / "best.pt", map_location="cpu", weights_only=False)
    final_report = {
        "model": "torchvision.efficientnet_b0",
        "trained_at_utc": datetime.now(timezone.utc).isoformat(),
        "device": str(device),
        "class_names": class_names,
        "train_class_counts": dict(zip(class_names, class_counts)),
        "best_epoch": best["epoch"],
        "best_validation": best["metrics"],
        "history": history,
        "checkpoint": str((args.output_dir / "best.pt").resolve()),
    }
    (args.output_dir / "training_report.json").write_text(
        json.dumps(final_report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"학습 완료 모델: {args.output_dir / 'best.pt'}", flush=True)
    print(f"학습 보고서: {args.output_dir / 'training_report.json'}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
