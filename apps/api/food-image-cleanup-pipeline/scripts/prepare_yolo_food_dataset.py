"""음식 메타데이터를 YOLO11 객체 탐지 데이터셋으로 변환한다.

원본 주석 JSON을 다시 읽지 않고, food_description_data/metadata.csv에 이미
정리된 음식 Bounding Box를 사용한다. 이 데이터셋은 음식 위치 탐지용 단일
클래스(food) 데이터셋이다. 접시·컵 등 용기 클래스는 별도 주석이 없으므로
이 스크립트에서 임의로 만들지 않는다.
"""

from __future__ import annotations

import argparse
import csv
import random
import shutil
from collections import Counter
from pathlib import Path

from PIL import Image


CLASS_NAMES = ["food"]


def parse_args() -> argparse.Namespace:
    project_root = Path(__file__).resolve().parents[1]
    default_source = (
        project_root.parents[2]
        / "data/processed/aihub_food_image_text/v2/food_description_data"
    )
    parser = argparse.ArgumentParser(description="음식 메타데이터를 YOLO 데이터셋으로 변환합니다.")
    parser.add_argument("--source-root", type=Path, default=default_source)
    parser.add_argument(
        "--output-root",
        type=Path,
        default=project_root / "data/training/yolo_food_detection",
    )
    parser.add_argument("--val-ratio", type=float, default=0.15)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--copy-images",
        action="store_true",
        help="기본 하드링크 대신 이미지를 복사합니다. 다른 드라이브일 때 사용하세요.",
    )
    return parser.parse_args()


def link_or_copy(source: Path, destination: Path, copy_images: bool) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        destination.unlink()
    if not copy_images:
        try:
            destination.hardlink_to(source)
            return
        except OSError:
            # 서로 다른 볼륨이거나 권한이 없는 경우만 복사로 안전하게 전환한다.
            pass
    shutil.copy2(source, destination)


def normalized_box(row: dict[str, str], image_path: Path) -> tuple[float, float, float, float] | None:
    if row.get("bbox_found", "").strip().lower() != "true":
        return None
    try:
        x = float(row["bbox_x"])
        y = float(row["bbox_y"])
        width = float(row["bbox_width"])
        height = float(row["bbox_height"])
        with Image.open(image_path) as image:
            image_width, image_height = image.size
    except (KeyError, ValueError, OSError):
        return None

    if width <= 1 or height <= 1 or image_width <= 1 or image_height <= 1:
        return None
    # 원본 좌표가 이미지 외부로 약간 나간 경우 경계 안으로 제한한다.
    left = max(0.0, min(x, float(image_width)))
    top = max(0.0, min(y, float(image_height)))
    right = max(left, min(x + width, float(image_width)))
    bottom = max(top, min(y + height, float(image_height)))
    if right - left <= 1 or bottom - top <= 1:
        return None
    return (
        ((left + right) / 2) / image_width,
        ((top + bottom) / 2) / image_height,
        (right - left) / image_width,
        (bottom - top) / image_height,
    )


def main() -> int:
    args = parse_args()
    if not 0.05 <= args.val_ratio < 0.5:
        raise SystemExit("--val-ratio는 0.05 이상 0.5 미만이어야 합니다.")

    metadata_path = args.source_root / "metadata.csv"
    images_root = args.source_root / "images"
    if not metadata_path.is_file() or not images_root.is_dir():
        raise SystemExit(f"데이터 원본을 찾을 수 없습니다: {args.source_root}")

    with metadata_path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))

    valid_rows: list[tuple[dict[str, str], Path, tuple[float, float, float, float]]] = []
    skipped = Counter()
    for row in rows:
        relative_path = row.get("final_image_path", "")
        source_path = args.source_root / relative_path
        if not source_path.is_file():
            skipped["image_missing"] += 1
            continue
        box = normalized_box(row, source_path)
        if box is None:
            skipped["invalid_bbox"] += 1
            continue
        valid_rows.append((row, source_path, box))

    if len(valid_rows) < 100:
        raise SystemExit(f"유효한 Bounding Box가 너무 적습니다: {len(valid_rows)}")

    # 같은 음식의 정면/측면 사진이 학습과 검증에 동시에 들어가지 않도록 음식명 단위로 분할한다.
    food_groups = sorted({row.get("original_food_name") or row["final_image_id"] for row, _, _ in valid_rows})
    random.Random(args.seed).shuffle(food_groups)
    val_group_count = max(1, round(len(food_groups) * args.val_ratio))
    val_foods = set(food_groups[:val_group_count])

    if args.output_root.exists() and any(args.output_root.iterdir()):
        raise SystemExit(
            f"출력 폴더가 이미 존재합니다. 기존 학습 데이터를 보존하기 위해 덮어쓰지 않습니다: {args.output_root}"
        )
    for split in ("train", "val"):
        (args.output_root / "images" / split).mkdir(parents=True)
        (args.output_root / "labels" / split).mkdir(parents=True)

    split_counts = Counter()
    for row, source_path, box in valid_rows:
        food_name = row.get("original_food_name") or row["final_image_id"]
        split = "val" if food_name in val_foods else "train"
        file_name = row["final_image_file_name"]
        destination_image = args.output_root / "images" / split / file_name
        destination_label = args.output_root / "labels" / split / f"{Path(file_name).stem}.txt"
        link_or_copy(source_path, destination_image, args.copy_images)
        destination_label.write_text(
            f"0 {box[0]:.6f} {box[1]:.6f} {box[2]:.6f} {box[3]:.6f}\n",
            encoding="utf-8",
        )
        split_counts[split] += 1

    dataset_yaml = args.output_root / "dataset.yaml"
    dataset_yaml.write_text(
        f"path: {args.output_root.as_posix()}\ntrain: images/train\nval: images/val\nnames:\n  0: food\n",
        encoding="utf-8",
    )
    audit_path = args.output_root / "dataset_audit.txt"
    audit_path.write_text(
        "\n".join(
            [
                "음식 YOLO11 탐지 데이터셋 감사 결과",
                f"원본 메타데이터 행: {len(rows)}",
                f"유효 음식 Bounding Box: {len(valid_rows)}",
                f"학습 이미지: {split_counts['train']}",
                f"검증 이미지: {split_counts['val']}",
                f"고유 음식명: {len(food_groups)}",
                f"검증 음식명: {len(val_foods)}",
                f"제외 사유: {dict(skipped) or '없음'}",
                "클래스: 0=food",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    print(audit_path.read_text(encoding="utf-8"), end="")
    print(f"dataset.yaml: {dataset_yaml}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
