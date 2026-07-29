"""Convert reviewed CVAT COCO masks to YOLO segmentation data.

Version 2 includes images that have only ``food_visible`` annotations.  The
original converter is intentionally left unchanged because it is stricter and
requires ``plate_full`` for every training image.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path

from scripts.prepare_plate_segmentation_dataset import (
    CLASS_NAMES,
    link_or_copy,
    polygon_rows,
)


def parse_args() -> argparse.Namespace:
    project_root = Path(__file__).resolve().parents[1]
    root = project_root / "data/training/plate_segmentation"
    parser = argparse.ArgumentParser(
        description=(
            "Convert CVAT COCO annotations to a YOLO segmentation dataset. "
            "Unlike v1, food_visible-only images are included."
        )
    )
    parser.add_argument("--coco-json", type=Path, required=True)
    parser.add_argument("--images-dir", type=Path, required=True)
    parser.add_argument(
        "--split-manifest",
        type=Path,
        default=root / "plate_annotation_manifest.csv",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=root / "yolo_plate_segmentation_v2",
    )
    parser.add_argument("--copy-images", action="store_true")
    return parser.parse_args()


def load_splits(path: Path) -> dict[str, str]:
    if not path.is_file():
        raise SystemExit(f"Split manifest not found: {path}")
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    splits = {
        row["image_file_name"]: row.get("target_split", "").strip().lower()
        for row in rows
    }
    invalid = {name: split for name, split in splits.items() if split not in {"train", "val", "test"}}
    if invalid:
        preview = ", ".join(list(invalid)[:5])
        raise SystemExit(f"CSV target_split must be train/val/test. Examples: {preview}")
    return splits


def main() -> int:
    args = parse_args()
    if args.output_root.exists() and any(args.output_root.iterdir()):
        raise SystemExit(f"Use an empty output folder to protect existing data: {args.output_root}")

    splits = load_splits(args.split_manifest)
    payload = json.loads(args.coco_json.read_text(encoding="utf-8"))
    category_ids = {entry["id"]: entry["name"] for entry in payload.get("categories", [])}
    missing = set(CLASS_NAMES) - set(category_ids.values())
    if missing:
        raise SystemExit(f"COCO categories are missing: {sorted(missing)}")
    class_by_id = {
        key: CLASS_NAMES.index(value)
        for key, value in category_ids.items()
        if value in CLASS_NAMES
    }

    annotations: dict[int, list[dict]] = {}
    for annotation in payload.get("annotations", []):
        if annotation.get("category_id") in class_by_id:
            annotations.setdefault(annotation["image_id"], []).append(annotation)

    counts: Counter[str] = Counter()
    skipped: Counter[str] = Counter()
    label_mix: Counter[str] = Counter()
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
                rows.extend(
                    polygon_rows(
                        annotation,
                        class_by_id[annotation["category_id"]],
                        image["width"],
                        image["height"],
                    )
                )
            except ValueError:
                skipped["unsupported_mask"] += 1

        has_plate_full = any(row.startswith("0 ") for row in rows)
        has_food_visible = any(row.startswith("1 ") for row in rows)
        if not has_plate_full and not has_food_visible:
            skipped["no_supported_labels"] += 1
            continue

        source = args.images_dir / name
        if not source.is_file():
            skipped["image_missing"] += 1
            continue

        link_or_copy(source, args.output_root / "images" / split / name, args.copy_images)
        (args.output_root / "labels" / split / f"{Path(name).stem}.txt").write_text(
            "\n".join(rows) + "\n",
            encoding="utf-8",
        )
        counts[split] += 1
        if has_plate_full and has_food_visible:
            label_mix["plate_full_and_food_visible"] += 1
        elif has_plate_full:
            label_mix["plate_full_only"] += 1
        else:
            label_mix["food_visible_only"] += 1

    if not counts["train"] or not counts["val"] or not counts["test"]:
        raise SystemExit(f"Every split needs at least one labeled image: {dict(counts)}")

    yaml = args.output_root / "dataset.yaml"
    yaml.write_text(
        f"path: {args.output_root.as_posix()}\n"
        "train: images/train\n"
        "val: images/val\n"
        "test: images/test\n"
        "names:\n"
        "  0: plate_full\n"
        "  1: food_visible\n",
        encoding="utf-8",
    )
    audit = args.output_root / "dataset_audit.json"
    audit.write_text(
        json.dumps(
            {
                "counts": counts,
                "skipped": skipped,
                "label_mix": label_mix,
                "classes": CLASS_NAMES,
                "mode": "v2_include_food_visible_only",
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"Dataset created: {yaml}")
    print(json.dumps({"counts": counts, "skipped": skipped, "label_mix": label_mix}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
