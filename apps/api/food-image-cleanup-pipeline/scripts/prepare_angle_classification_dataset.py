"""확정된 촬영 각도 CSV를 torchvision ImageFolder 데이터셋으로 변환한다."""

from __future__ import annotations

import argparse
import csv
import json
import shutil
from collections import Counter
from pathlib import Path


IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
DEFAULT_CLASSES = ("top", "45")


def parse_args() -> argparse.Namespace:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description="각도 라벨 CSV를 EfficientNet ImageFolder 데이터셋으로 구성합니다.")
    parser.add_argument(
        "--labels",
        type=Path,
        default=root / "data/training/EfficientNet-B0 angle/labels/angle_label_review.csv",
        help="final_angle이 확정된 CSV",
    )
    parser.add_argument(
        "--images-dir",
        type=Path,
        default=root / "data/training/EfficientNet-B0 angle/images",
        help="train/val 원본 이미지 디렉터리",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=root / "data/training/efficientnet_b0_angle/dataset",
        help="생성할 ImageFolder 루트",
    )
    parser.add_argument(
        "--classes",
        default=",".join(DEFAULT_CLASSES),
        help="필수 클래스 순서. 기본값: top,45",
    )
    parser.add_argument("--min-per-class", type=int, default=2, help="train/val 각각의 클래스 최소 이미지 수")
    parser.add_argument("--copy-mode", choices=("copy", "hardlink"), default="copy")
    return parser.parse_args()


def normalized_class(value: str | None) -> str:
    return (value or "").strip().lower()


def copy_image(source: Path, destination: Path, mode: str) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if mode == "hardlink":
        destination.hardlink_to(source)
    else:
        shutil.copy2(source, destination)


def main() -> int:
    args = parse_args()
    classes = tuple(part.strip().lower() for part in args.classes.split(",") if part.strip())
    if not classes:
        raise SystemExit("--classes에 하나 이상의 클래스를 지정하세요.")
    if len(classes) != len(set(classes)):
        raise SystemExit("--classes에 중복 클래스가 있습니다.")
    if args.output_dir.exists() and any(args.output_dir.iterdir()):
        raise SystemExit(f"출력 폴더가 비어 있지 않습니다. 기존 데이터를 삭제하지 않았습니다: {args.output_dir}")
    if not args.labels.is_file():
        raise SystemExit(f"라벨 CSV를 찾지 못했습니다: {args.labels}")
    if not args.images_dir.is_dir():
        raise SystemExit(f"이미지 디렉터리를 찾지 못했습니다: {args.images_dir}")

    with args.labels.open("r", encoding="utf-8-sig", newline="") as file:
        rows = list(csv.DictReader(file))
    required_columns = {"split", "image_path", "image_file_name", "final_angle"}
    if not rows or not required_columns.issubset(rows[0]):
        raise SystemExit(f"라벨 CSV에 필요한 열이 없습니다: {sorted(required_columns)}")

    invalid: list[str] = []
    selected: list[dict[str, str]] = []
    for row in rows:
        label = normalized_class(row.get("final_angle"))
        split = (row.get("split") or "").strip().lower()
        if label not in classes:
            invalid.append(f"{row.get('image_path', '')}: final_angle={row.get('final_angle', '')!r}")
            continue
        if split not in {"train", "val"}:
            invalid.append(f"{row.get('image_path', '')}: split={split!r}")
            continue
        relative = Path(row["image_path"])
        if relative.is_absolute() or ".." in relative.parts:
            invalid.append(f"안전하지 않은 image_path: {row['image_path']}")
            continue
        source = args.images_dir / relative
        if not source.is_file() or source.suffix.lower() not in IMAGE_EXTENSIONS:
            invalid.append(f"이미지를 찾지 못함: {source}")
            continue
        selected.append({**row, "final_angle": label, "split": split})
    if invalid:
        preview = "\n".join(invalid[:20])
        raise SystemExit(f"라벨 검증 실패 {len(invalid)}건입니다. CSV를 수정한 뒤 재실행하세요.\n{preview}")

    counts = Counter((row["split"], row["final_angle"]) for row in selected)
    missing = [
        f"{split}/{label}: {counts[(split, label)]}장"
        for split in ("train", "val")
        for label in classes
        if counts[(split, label)] < args.min_per_class
    ]
    if missing:
        raise SystemExit(
            "학습할 모든 각도 클래스는 각각 train/val 분할에 최소 이미지가 필요합니다.\n"
            + "\n".join(missing)
            + "\n현재 라벨을 보완하거나, 학습할 클래스는 --classes로 명시하세요."
        )

    args.output_dir.mkdir(parents=True, exist_ok=True)
    copied_rows: list[dict[str, str]] = []
    for row in selected:
        source = args.images_dir / Path(row["image_path"])
        destination = args.output_dir / row["split"] / row["final_angle"] / source.name
        copy_image(source, destination, args.copy_mode)
        copied_rows.append(
            {
                "split": row["split"],
                "class_name": row["final_angle"],
                "source_image_path": row["image_path"],
                "dataset_image_path": destination.relative_to(args.output_dir).as_posix(),
            }
        )

    with (args.output_dir / "manifest.csv").open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=("split", "class_name", "source_image_path", "dataset_image_path"))
        writer.writeheader()
        writer.writerows(copied_rows)
    # torchvision ImageFolder는 디렉터리명을 알파벳순으로 정렬한다. 저장한 맵도
    # 같은 순서를 따라야 추론 단계에서 클래스 인덱스가 뒤바뀌지 않는다.
    imagefolder_classes = sorted(classes)
    (args.output_dir / "class_map.json").write_text(
        json.dumps({label: index for index, label in enumerate(imagefolder_classes)}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    summary = {
        "source_labels": str(args.labels.resolve()),
        "copy_mode": args.copy_mode,
        "classes": imagefolder_classes,
        "counts": {split: {label: counts[(split, label)] for label in classes} for split in ("train", "val")},
        "total_images": len(copied_rows),
    }
    (args.output_dir / "dataset_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"ImageFolder 데이터셋 생성 완료: {args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
