from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict

import pandas as pd
import yaml
from tqdm import tqdm
from utils.reproducibility import DEFAULT_RANDOM_SEED, set_global_seed

# Windows에서 src/utils import 문제 방지
CURRENT_DIR = Path(__file__).resolve().parent
if str(CURRENT_DIR) not in sys.path:
    sys.path.append(str(CURRENT_DIR))

from utils.metadata_utils import (
    collect_image_files,
    extract_metadata_record,
    list_json_files,
)


def load_pipeline_config(config_path: str) -> Dict[str, Any]:
    config_file = Path(config_path)

    if not config_file.exists():
        raise FileNotFoundError(f"Config file not found: {config_file}")

    with config_file.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def ensure_parent_dir(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def build_category_stats(df: pd.DataFrame) -> pd.DataFrame:
    """
    음식명/음식코드 기준 통계를 생성한다.
    현재 Validation JSON에는 한글 대/중/소분류가 없으므로
    original_food_name과 food_code 중심으로 통계를 만든다.
    """
    group_cols = [
        "original_major_category",
        "original_middle_category",
        "original_sub_category",
        "original_food_name",
        "food_code",
    ]

    for col in group_cols:
        if col not in df.columns:
            df[col] = ""

    stats = (
        df.groupby(group_cols, dropna=False)
        .size()
        .reset_index(name="image_count")
        .sort_values("image_count", ascending=False)
    )

    return stats


def build_summary(
    df: pd.DataFrame, json_count: int, image_count: int
) -> Dict[str, Any]:
    matched_image_count = (
        int(df["image_path"].notna().sum()) if "image_path" in df.columns else 0
    )
    valid_json_count = int(df["json_valid"].sum()) if "json_valid" in df.columns else 0

    food_name_count = 0
    if "original_food_name" in df.columns:
        food_name_count = int((df["original_food_name"].fillna("") != "").sum())

    summary = {
        "json_file_count": int(json_count),
        "image_file_count": int(image_count),
        "parsed_record_count": int(len(df)),
        "valid_json_count": valid_json_count,
        "invalid_json_count": int(len(df) - valid_json_count),
        "matched_image_count": matched_image_count,
        "missing_image_count": int(len(df) - matched_image_count),
        "food_name_extracted_count": food_name_count,
        "food_name_missing_count": int(len(df) - food_name_count),
        "unique_food_name_count": (
            int(df["original_food_name"].nunique(dropna=True))
            if "original_food_name" in df.columns
            else 0
        ),
        "unique_food_code_count": (
            int(df["food_code"].nunique(dropna=True))
            if "food_code" in df.columns
            else 0
        ),
    }

    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Parse AI Hub food JSON annotations into metadata parquet."
    )

    parser.add_argument(
        "--config",
        type=str,
        default="configs/pipeline_config.yaml",
        help="Pipeline config path.",
    )
    parser.add_argument(
        "--raw-dir",
        type=str,
        default=None,
        help="Raw data root directory. If omitted, use pipeline_config.yaml.",
    )
    parser.add_argument(
        "--image-dir",
        type=str,
        default=None,
        help="Raw image directory. If omitted, use pipeline_config.yaml.",
    )
    parser.add_argument(
        "--annotation-dir",
        type=str,
        default=None,
        help="Raw annotation directory. If omitted, use pipeline_config.yaml.",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Output parquet path. If omitted, use pipeline_config.yaml.",
    )
    parser.add_argument(
        "--category-stats-output",
        type=str,
        default=None,
        help="Category stats CSV output path.",
    )
    parser.add_argument(
        "--summary-output",
        type=str,
        default="outputs/reports/parse_metadata_summary.json",
        help="Parse summary JSON output path.",
    )
    parser.add_argument(
        "--sample-limit",
        type=int,
        default=None,
        help="For quick test. Parse only first N JSON files.",
    )

    return parser.parse_args()


def main() -> None:
    set_global_seed(DEFAULT_RANDOM_SEED)
    args = parse_args()
    config = load_pipeline_config(args.config)

    paths = config.get("paths", {})

    raw_dir = Path(args.raw_dir or paths.get("raw_dir", "data/raw"))
    image_dir = Path(args.image_dir or paths.get("raw_images_dir", "data/raw/images"))
    annotation_dir = Path(
        args.annotation_dir or paths.get("raw_annotations_dir", "data/raw/annotations")
    )

    output_path = Path(
        args.output
        or paths.get("raw_metadata_path", "data/metadata/raw_metadata.parquet")
    )
    category_stats_output = Path(
        args.category_stats_output
        or paths.get("category_stats_path", "data/metadata/category_stats.csv")
    )
    summary_output = Path(args.summary_output)

    print("[INFO] AIHub Food Ad RAG - Metadata Parsing")
    print(f"[INFO] raw_dir        : {raw_dir}")
    print(f"[INFO] image_dir      : {image_dir}")
    print(f"[INFO] annotation_dir : {annotation_dir}")
    print(f"[INFO] output         : {output_path}")

    if not annotation_dir.exists():
        raise FileNotFoundError(f"Annotation directory not found: {annotation_dir}")

    if not image_dir.exists():
        raise FileNotFoundError(f"Image directory not found: {image_dir}")

    image_map = collect_image_files(image_dir)
    json_files = list_json_files(annotation_dir)

    if args.sample_limit is not None:
        json_files = json_files[: args.sample_limit]

    print(f"[INFO] image files found: {len(image_map):,}")
    print(f"[INFO] json files found : {len(json_files):,}")

    if not json_files:
        raise RuntimeError("No JSON files found. Check data/raw/annotations.")

    records = []

    for json_path in tqdm(json_files, desc="Parsing JSON"):
        record = extract_metadata_record(
            json_path=json_path,
            image_map=image_map,
            raw_root=raw_dir,
        )
        records.append(record)

    df = pd.DataFrame(records)

    ensure_parent_dir(output_path)
    df.to_parquet(output_path, index=False)

    stats = build_category_stats(df)
    ensure_parent_dir(category_stats_output)
    stats.to_csv(category_stats_output, index=False, encoding="utf-8-sig")

    summary = build_summary(
        df=df,
        json_count=len(json_files),
        image_count=len(image_map),
    )

    ensure_parent_dir(summary_output)
    with summary_output.open("w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print("[DONE] Metadata parsing completed.")
    print(f"[DONE] parquet saved : {output_path}")
    print(f"[DONE] stats saved   : {category_stats_output}")
    print(f"[DONE] summary saved : {summary_output}")
    print("[SUMMARY]")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
