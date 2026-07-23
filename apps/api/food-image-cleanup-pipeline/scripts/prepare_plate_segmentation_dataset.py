"""CVAT COCO 인스턴스 주석을 YOLO 분할 학습 데이터로 변환한다."""

from __future__ import annotations

import argparse
import csv
import json
import shutil
from collections import Counter
from pathlib import Path

import cv2
import numpy as np


CLASS_NAMES = ("plate_full", "food_visible")


def parse_args() -> argparse.Namespace:
    project_root = Path(__file__).resolve().parents[1]
    root = project_root / "data/training/plate_segmentation"
    parser = argparse.ArgumentParser(description="CVAT COCO 주석을 YOLO 분할 데이터셋으로 변환합니다.")
    parser.add_argument("--coco-json", type=Path, required=True)
    parser.add_argument("--images-dir", type=Path, required=True)
    parser.add_argument("--split-manifest", type=Path, default=root / "plate_annotation_manifest.csv")
    parser.add_argument("--output-root", type=Path, default=root / "yolo_plate_segmentation")
    parser.add_argument("--copy-images", action="store_true")
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


def load_splits(path: Path) -> dict[str, str]:
    if not path.is_file():
        raise SystemExit(f"분할 목록을 찾을 수 없습니다: {path}")
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    # 접시가 없는 사진은 검수 단계에서 skipped/rejected로 표시한다. 이 사진은
    # 학습 데이터셋에 넣지 않으며 split도 요구하지 않는다.
    included_rows = [
        row
        for row in rows
        if row.get("plate_full_status", "pending").strip().lower() in {"completed", "approved"}
        and row.get("food_visible_status", "pending").strip().lower() in {"completed", "approved"}
    ]
    if not included_rows:
        raise SystemExit("검수 완료된 이미지가 없습니다. CSV의 두 status를 completed 또는 approved로 설정하세요.")
    splits = {
        row["image_file_name"]: row.get("target_split", "").strip().lower()
        for row in included_rows
    }
    invalid = {name: split for name, split in splits.items() if split not in {"train", "val", "test"}}
    if invalid:
        preview = ", ".join(list(invalid)[:5])
        raise SystemExit(f"CSV target_split에 train/val/test를 모두 입력하세요. 예: {preview}")
    return splits


def polygon_rows(annotation: dict, category_index: int, width: int, height: int) -> list[str]:
    segmentation = annotation.get("segmentation")
    if isinstance(segmentation, dict):
        try:
            from pycocotools import mask as coco_mask
        except ImportError as exc:
            raise ValueError("RLE 마스크에는 pycocotools가 필요합니다.") from exc
        decoded = coco_mask.decode(segmentation)
        if decoded.ndim == 3:
            decoded = decoded[..., 0]
        contours, _ = cv2.findContours(
            (decoded.astype(np.uint8) * 255), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )
        segmentation = [contour.reshape(-1).astype(float).tolist() for contour in contours]
    if not isinstance(segmentation, list) or not segmentation:
        raise ValueError("유효한 폴리곤 또는 RLE 마스크가 아닙니다.")
    result: list[str] = []
    for polygon in segmentation:
        if not isinstance(polygon, list) or len(polygon) < 6 or len(polygon) % 2:
            continue
        values = []
        for x, y in zip(polygon[0::2], polygon[1::2]):
            values.append(f"{min(1.0, max(0.0, float(x) / width)):.6f}")
            values.append(f"{min(1.0, max(0.0, float(y) / height)):.6f}")
        result.append(f"{category_index} " + " ".join(values))
    return result


def main() -> int:
    args = parse_args()
    if args.output_root.exists() and any(args.output_root.iterdir()):
        raise SystemExit(f"기존 산출물 보존을 위해 비어 있는 폴더만 사용합니다: {args.output_root}")
    splits = load_splits(args.split_manifest)
    payload = json.loads(args.coco_json.read_text(encoding="utf-8"))
    category_ids = {entry["id"]: entry["name"] for entry in payload.get("categories", [])}
    missing = set(CLASS_NAMES) - set(category_ids.values())
    if missing:
        raise SystemExit(f"COCO 카테고리가 부족합니다: {sorted(missing)}")
    class_by_id = {key: CLASS_NAMES.index(value) for key, value in category_ids.items() if value in CLASS_NAMES}
    annotations: dict[int, list[dict]] = {}
    for annotation in payload.get("annotations", []):
        if annotation.get("category_id") in class_by_id:
            annotations.setdefault(annotation["image_id"], []).append(annotation)

    counts: Counter[str] = Counter()
    skipped: Counter[str] = Counter()
    for split in ("train", "val", "test"):
        (args.output_root / "images" / split).mkdir(parents=True)
        (args.output_root / "labels" / split).mkdir(parents=True)
    for image in payload.get("images", []):
        name = image["file_name"]
        split = splits.get(name)
        if not split:
            skipped["not_in_manifest"] += 1
            continue
        image_annotations = annotations.get(image["id"], [])
        rows: list[str] = []
        for annotation in image_annotations:
            try:
                rows.extend(polygon_rows(annotation, class_by_id[annotation["category_id"]], image["width"], image["height"]))
            except ValueError:
                skipped["unsupported_mask"] += 1
        if not rows or not any(row.startswith("0 ") for row in rows):
            skipped["no_plate_full"] += 1
            continue
        source = args.images_dir / name
        if not source.is_file():
            skipped["image_missing"] += 1
            continue
        link_or_copy(source, args.output_root / "images" / split / name, args.copy_images)
        (args.output_root / "labels" / split / f"{Path(name).stem}.txt").write_text("\n".join(rows) + "\n", encoding="utf-8")
        counts[split] += 1
    if not counts["train"] or not counts["val"] or not counts["test"]:
        raise SystemExit(f"모든 split에 plate_full 주석이 있어야 합니다: {dict(counts)}")
    yaml = args.output_root / "dataset.yaml"
    yaml.write_text(
        f"path: {args.output_root.as_posix()}\ntrain: images/train\nval: images/val\ntest: images/test\nnames:\n  0: plate_full\n  1: food_visible\n",
        encoding="utf-8",
    )
    audit = args.output_root / "dataset_audit.json"
    audit.write_text(json.dumps({"counts": counts, "skipped": skipped, "classes": CLASS_NAMES}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"데이터셋 생성 완료: {yaml}")
    print(json.dumps({"counts": counts, "skipped": skipped}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
