"""AIHub 음식 이미지에서 접시/음식 인스턴스 분할 주석 작업 목록을 만든다."""

from __future__ import annotations

import argparse
import csv
import random
import shutil
from collections import defaultdict
from pathlib import Path


def parse_args() -> argparse.Namespace:
    project_root = Path(__file__).resolve().parents[1]
    default_source = (
        project_root.parents[2]
        / "data/processed/aihub_food_image_text/v2/food_description_data"
    )
    parser = argparse.ArgumentParser(
        description="AIHub 이미지에서 CVAT 접시 분할 주석 작업 목록을 생성합니다."
    )
    parser.add_argument("--source-root", type=Path, default=default_source)
    parser.add_argument(
        "--output-root",
        type=Path,
        default=project_root / "data/training/plate_segmentation",
    )
    parser.add_argument("--sample-size", type=int, default=500)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--copy-images", action="store_true")
    parser.add_argument(
        "--reset-output",
        action="store_true",
        help="기존 접시 분할 작업 폴더를 삭제하고 새 500장 작업 목록을 만듭니다.",
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
            pass
    shutil.copy2(source, destination)


def eligible_rows(source_root: Path) -> list[dict[str, str]]:
    metadata = source_root / "metadata.csv"
    if not metadata.is_file():
        raise SystemExit(f"metadata.csv를 찾을 수 없습니다: {metadata}")
    with metadata.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    return [
        row
        for row in rows
        if row.get("image_exists", "").lower() == "true"
        and row.get("quality_pass", "").lower() == "true"
        and row.get("final_image_path")
    ]


def main() -> int:
    args = parse_args()
    rows = eligible_rows(args.source_root)
    if args.sample_size < 1 or args.sample_size > len(rows):
        raise SystemExit(f"--sample-size는 1~{len(rows)} 범위여야 합니다.")
    if args.output_root.exists() and any(args.output_root.iterdir()):
        if not args.reset_output:
            raise SystemExit(
                f"기존 산출물 보존을 위해 비어 있는 폴더만 사용합니다: {args.output_root}. "
                "새 500장 작업을 다시 만들려면 내용을 백업한 뒤 --reset-output을 명시하세요."
            )
        # 사용자 명령에 --reset-output이 명시된 경우에만, 정확한 작업 루트만 삭제한다.
        shutil.rmtree(args.output_root)

    # 같은 음식/시점에 몰리지 않도록 food_view_key 단위로 균등 추출한다.
    groups: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        group = row.get("food_view_key") or row.get("original_food_name") or row["final_image_id"]
        groups[group].append(row)
    rng = random.Random(args.seed)
    group_keys = list(groups)
    rng.shuffle(group_keys)
    selected: list[dict[str, str]] = []
    while group_keys and len(selected) < args.sample_size:
        next_round: list[str] = []
        for key in group_keys:
            if len(selected) >= args.sample_size:
                break
            candidates = groups[key]
            if candidates:
                selected.append(candidates.pop(rng.randrange(len(candidates))))
            if candidates:
                next_round.append(key)
        group_keys = next_round

    images_dir = args.output_root / "cvat_images"
    manifest = args.output_root / "plate_annotation_manifest.csv"
    images_dir.mkdir(parents=True)
    fields = [
        "image_file_name", "source_image_path", "food_name", "view_type",
        "business_category", "food_view_key", "split_group", "target_split",
        "plate_full_status", "food_visible_status", "review_note",
    ]
    with manifest.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in selected:
            source = args.source_root / row["final_image_path"]
            name = row["final_image_file_name"]
            link_or_copy(source, images_dir / name, args.copy_images)
            writer.writerow({
                "image_file_name": name,
                "source_image_path": str(source),
                "food_name": row.get("original_food_name", ""),
                "view_type": row.get("view_type", ""),
                "business_category": row.get("business_category", ""),
                "food_view_key": row.get("food_view_key", ""),
                "split_group": row.get("duplicate_group_id") or row.get("food_view_key", ""),
                "target_split": "",
                "plate_full_status": "pending",
                "food_visible_status": "pending",
                "review_note": "",
            })
    readme = args.output_root / "CVAT_ANNOTATION_GUIDE.md"
    readme.write_text(
        "# 접시 보존 분할 주석\n\n"
        "CVAT에서 `plate_full`, `food_visible` 두 인스턴스 라벨을 만듭니다.\n\n"
        "- `plate_full`: 음식에 가려진 중앙까지 포함한 접시 외곽 전체입니다. 접시 무늬·테두리는 포함하고 식탁보·테이블은 제외합니다.\n"
        "- `food_visible`: 실제로 보이는 음식 픽셀만 표시합니다. 접시와 겹쳐도 됩니다.\n"
        "- 접시가 없거나 외곽을 신뢰할 수 없으면 두 라벨을 만들지 말고 CSV 상태를 `skipped`로 바꿉니다.\n"
        "- 같은 촬영 세트는 `split_group`을 같게 유지합니다. 주석 뒤 `target_split`에 train/val/test를 70/15/15로 작성합니다.\n"
        "- COCO Instances 1.0 형식으로 내보낸 뒤 `prepare_plate_segmentation_dataset.py`를 실행합니다.\n",
        encoding="utf-8",
    )
    print(f"주석 대상: {len(selected)}장")
    print(f"CVAT 업로드 폴더: {images_dir}")
    print(f"작업 목록: {manifest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
