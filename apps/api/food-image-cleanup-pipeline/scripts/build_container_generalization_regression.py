from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import cv2
import numpy as np


CONTAINER_KEYWORDS = {
    "tray": ("tray", "platter"),
    "bowl": ("bowl",),
    "cup": ("cup", "glass", "mug"),
    "plate": ("plate", "dish"),
}


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a fixed, diverse raw-image regression set."
    )
    parser.add_argument("--dataset-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--sample-count", type=int, default=50)
    parser.add_argument("--thumbnail-size", type=int, default=240)
    return parser.parse_args()


def _container_hint(caption: str) -> str:
    lowered = caption.lower()
    for label, keywords in CONTAINER_KEYWORDS.items():
        if any(keyword in lowered for keyword in keywords):
            return label
    return "unknown"


def _appearance_hint(image: np.ndarray, row: dict[str, str]) -> tuple[str, dict[str, float]]:
    height, width = image.shape[:2]
    try:
        x = float(row.get("bbox_x") or 0)
        y = float(row.get("bbox_y") or 0)
        box_width = float(row.get("bbox_width") or width)
        box_height = float(row.get("bbox_height") or height)
    except ValueError:
        x, y, box_width, box_height = 0.0, 0.0, float(width), float(height)
    margin_x = box_width * 0.18
    margin_y = box_height * 0.18
    x1 = max(0, int(round(x - margin_x)))
    y1 = max(0, int(round(y - margin_y)))
    x2 = min(width, int(round(x + box_width + margin_x)))
    y2 = min(height, int(round(y + box_height + margin_y)))
    crop = image[y1:y2, x1:x2]
    if crop.size == 0:
        crop = image
    small = cv2.resize(crop, (128, 128), interpolation=cv2.INTER_AREA)
    hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)
    saturation = float(np.median(hsv[:, :, 1]))
    value = float(np.median(hsv[:, :, 2]))
    color_std = float(np.mean(np.std(small.astype(np.float32), axis=(0, 1))))
    if value >= 185 and saturation <= 42:
        appearance = "white_or_clear"
    elif value <= 95:
        appearance = "dark"
    elif saturation >= 75:
        appearance = "colored"
    else:
        appearance = "neutral"
    return appearance, {
        "crop_median_saturation": round(saturation, 3),
        "crop_median_value": round(value, 3),
        "crop_color_std": round(color_std, 3),
    }


def _select_stratified(
    records: list[dict[str, Any]],
    sample_count: int,
) -> list[dict[str, Any]]:
    buckets: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        key = (
            str(record["container_hint"]),
            str(record["appearance_hint"]),
            str(record["view_type"]),
        )
        buckets[key].append(record)
    for bucket in buckets.values():
        bucket.sort(key=lambda item: str(item["final_image_id"]))

    selected: list[dict[str, Any]] = []
    keys = sorted(buckets)
    while len(selected) < sample_count and keys:
        remaining: list[tuple[str, str, str]] = []
        for key in keys:
            bucket = buckets[key]
            if bucket and len(selected) < sample_count:
                selected.append(bucket.pop(0))
            if bucket:
                remaining.append(key)
        keys = remaining
    return selected


def _contact_sheet(
    selected: list[dict[str, Any]],
    output_path: Path,
    thumbnail_size: int,
) -> None:
    columns = 5
    tile_width = thumbnail_size + 20
    tile_height = thumbnail_size + 58
    rows = (len(selected) + columns - 1) // columns
    sheet = np.full((rows * tile_height, columns * tile_width, 3), 248, np.uint8)
    for index, record in enumerate(selected):
        image = cv2.imread(str(record["image_path"]))
        if image is None:
            continue
        height, width = image.shape[:2]
        scale = min(thumbnail_size / width, thumbnail_size / height)
        resized = cv2.resize(
            image,
            (max(1, int(width * scale)), max(1, int(height * scale))),
            interpolation=cv2.INTER_AREA,
        )
        tile = np.full((tile_height, tile_width, 3), 248, np.uint8)
        x = (tile_width - resized.shape[1]) // 2
        tile[4 : 4 + resized.shape[0], x : x + resized.shape[1]] = resized
        cv2.putText(
            tile,
            str(record["final_image_id"]),
            (8, thumbnail_size + 26),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.42,
            (20, 20, 20),
            1,
            cv2.LINE_AA,
        )
        label = f'{record["container_hint"]}/{record["appearance_hint"]}'
        cv2.putText(
            tile,
            label[:32],
            (8, thumbnail_size + 48),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.36,
            (45, 45, 45),
            1,
            cv2.LINE_AA,
        )
        row, column = divmod(index, columns)
        sheet[
            row * tile_height : (row + 1) * tile_height,
            column * tile_width : (column + 1) * tile_width,
        ] = tile
    cv2.imwrite(str(output_path), sheet, [cv2.IMWRITE_JPEG_QUALITY, 90])


def main() -> None:
    args = _parse_args()
    dataset_root = args.dataset_root.resolve()
    metadata_path = dataset_root / "metadata.csv"
    if not metadata_path.exists():
        raise FileNotFoundError(metadata_path)
    args.output_dir.mkdir(parents=True, exist_ok=True)

    with metadata_path.open("r", encoding="utf-8-sig", newline="") as handle:
        metadata = list(csv.DictReader(handle))
    records: list[dict[str, Any]] = []
    for row in metadata:
        image_path = dataset_root / str(row.get("final_image_path", ""))
        image = cv2.imread(str(image_path))
        if image is None:
            continue
        appearance, appearance_metrics = _appearance_hint(image, row)
        records.append(
            {
                "final_image_id": row.get("final_image_id", image_path.stem),
                "product_name": row.get("product_name", ""),
                "product_group": row.get("product_group", ""),
                "business_category": row.get("business_category", ""),
                "view_type": row.get("view_type", "unknown"),
                "caption": row.get("caption", ""),
                "container_hint": _container_hint(row.get("caption", "")),
                "appearance_hint": appearance,
                "image_path": str(image_path),
                **appearance_metrics,
            }
        )
    selected = _select_stratified(records, max(1, int(args.sample_count)))
    manifest_path = args.output_dir / "container_generalization_manifest.csv"
    fieldnames = list(selected[0]) if selected else []
    with manifest_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(selected)

    summary = {
        "dataset_root": str(dataset_root),
        "available_images": len(records),
        "selected_images": len(selected),
        "container_distribution": dict(
            Counter(str(item["container_hint"]) for item in selected)
        ),
        "appearance_distribution": dict(
            Counter(str(item["appearance_hint"]) for item in selected)
        ),
        "view_distribution": dict(
            Counter(str(item["view_type"]) for item in selected)
        ),
        "manifest": str(manifest_path),
        "contact_sheet": str(args.output_dir / "container_generalization_contact_sheet.jpg"),
    }
    (args.output_dir / "container_generalization_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    _contact_sheet(
        selected,
        args.output_dir / "container_generalization_contact_sheet.jpg",
        max(96, int(args.thumbnail_size)),
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
