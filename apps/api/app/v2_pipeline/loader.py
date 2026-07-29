"""Data loader for v2 image-prompt batch processing."""
from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

PROMPT_METADATA_SUBPATH = "food_description_data/prompt_metadata.csv"
REQUIRED_COLUMNS = {"final_image_id", "final_image_path", "product_name", "business_category", "prompt_keywords", "caption", "ad_use_case", "visual_style_hint", "caption_lighting", "caption_composition", "caption_camera_angle", "original_food_name"}


@dataclass(frozen=True)
class DataRecord:
    final_image_id: str
    final_image_path: str
    abs_image_path: Path
    original_food_name: str
    product_name: str
    business_category: str
    prompt_keywords: str  # Stored and passed without text transformation.
    caption: str
    ad_use_case: str
    visual_style_hint: str
    caption_lighting: str
    caption_composition: str
    caption_camera_angle: str
    row_index: int


def load_records(input_dir: Path) -> list[DataRecord]:
    csv_path = input_dir / PROMPT_METADATA_SUBPATH
    if not csv_path.exists():
        raise FileNotFoundError(f"prompt_metadata.csv not found: {csv_path}")
    records: list[DataRecord] = []
    # utf-8-sig removes only an optional file BOM from the CSV header; values,
    # including prompt text, are read without stripping or rewriting.
    with csv_path.open(encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        if reader.fieldnames is None:
            raise ValueError("prompt_metadata.csv has no header row.")
        missing = REQUIRED_COLUMNS - set(reader.fieldnames)
        if missing:
            raise ValueError(f"prompt_metadata.csv is missing required columns: {sorted(missing)}")
        for row_index, row in enumerate(reader):
            relative_path = row["final_image_path"].strip()
            records.append(DataRecord(
                final_image_id=row["final_image_id"].strip(), final_image_path=relative_path,
                abs_image_path=(input_dir / "food_description_data" / relative_path).resolve(),
                original_food_name=row["original_food_name"].strip(), product_name=row["product_name"].strip(),
                business_category=row["business_category"].strip(), prompt_keywords=row["prompt_keywords"],
                caption=row["caption"], ad_use_case=row["ad_use_case"].strip(),
                visual_style_hint=row["visual_style_hint"].strip(), caption_lighting=row["caption_lighting"].strip(),
                caption_composition=row["caption_composition"].strip(),
                caption_camera_angle=row["caption_camera_angle"].strip(), row_index=row_index,
            ))
    records.sort(key=lambda r: (r.final_image_id, r.final_image_path, r.row_index))
    return records


def select_batch(records: list[DataRecord], batch_size: int) -> list[DataRecord]:
    if batch_size not in {10, 50, 100}:
        raise ValueError(f"Invalid batch size: {batch_size}. Allowed values are 10, 50, and 100.")
    if len(records) < batch_size:
        raise ValueError(f"Insufficient data: requested {batch_size} items but only {len(records)} records are available.")
    return records[:batch_size]
