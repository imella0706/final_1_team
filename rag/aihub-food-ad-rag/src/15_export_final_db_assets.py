from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FINAL_DB_ROOT = PROJECT_ROOT / "data" / "final_db"


REQUIRED_DB_FILES = [
    "metadata.parquet",
    "prompt_metadata.parquet",
    "summary.json",
]


MANAGEMENT_COLUMNS = [
    "database_name",
    "final_image_id",
    "faiss_index_id",
    "final_image_path",
    "final_image_file_name",
    "image_path",
    "original_food_name",
    "product_name",
    "food_code",
    "business_category",
    "product_group",
    "view_type",
    "bbox_ratio",
    "bbox_40_70_match",
    "center_score",
    "blur_score",
    "actual_width",
    "actual_height",
    "representative_score",
    "caption",
    "prompt_keywords",
    "caption_lighting",
    "caption_composition",
    "caption_camera_angle",
    "ad_use_case",
    "visual_style_hint",
    "text_for_embedding",
    "retrieval_text",
    "ad_prompt_hint",
]


LLM_COLUMNS = [
    "final_image_id",
    "final_image_path",
    "business_category",
    "product_group",
    "product_name",
    "original_food_name",
    "food_code",
    "caption",
    "prompt_keywords",
    "retrieval_text",
    "ad_prompt_hint",
    "caption_lighting",
    "caption_composition",
    "caption_camera_angle",
    "ad_use_case",
    "visual_style_hint",
]


def read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def write_json(data: Any, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=2)


def discover_db_dirs(final_db_root: Path, requested: list[str] | None) -> list[Path]:
    if requested:
        candidates = [final_db_root / name for name in requested]
    else:
        candidates = [
            path
            for path in final_db_root.iterdir()
            if path.is_dir() and not path.name.lower() == "images"
        ]

    result = []
    for db_dir in candidates:
        if all((db_dir / file_name).exists() for file_name in REQUIRED_DB_FILES):
            result.append(db_dir)

    return sorted(result, key=lambda path: path.name)


def to_jsonable(value: Any) -> Any:
    if pd.isna(value):
        return None
    if hasattr(value, "item"):
        try:
            return value.item()
        except ValueError:
            pass
    return value


def merge_metadata(metadata: pd.DataFrame, prompt_metadata: pd.DataFrame) -> pd.DataFrame:
    prompt_cols = [
        column
        for column in [
            "final_image_id",
            "retrieval_text",
            "ad_prompt_hint",
            "text_for_embedding",
        ]
        if column in prompt_metadata.columns
    ]

    if "final_image_id" not in metadata.columns or "final_image_id" not in prompt_cols:
        return metadata.copy()

    prompt_subset = prompt_metadata[prompt_cols].drop_duplicates("final_image_id")
    overlapping_cols = [
        column
        for column in prompt_subset.columns
        if column != "final_image_id" and column in metadata.columns
    ]

    if overlapping_cols:
        prompt_subset = prompt_subset.drop(columns=overlapping_cols)

    return metadata.merge(prompt_subset, on="final_image_id", how="left")


def build_management_inventory(db_name: str, db_dir: Path) -> pd.DataFrame:
    metadata = pd.read_parquet(db_dir / "metadata.parquet")
    prompt_metadata = pd.read_parquet(db_dir / "prompt_metadata.parquet")

    merged = merge_metadata(metadata, prompt_metadata)
    merged.insert(0, "database_name", db_name)

    if "faiss_index_id" not in merged.columns:
        merged.insert(1, "faiss_index_id", range(len(merged)))

    ordered_columns = [column for column in MANAGEMENT_COLUMNS if column in merged.columns]
    extra_columns = [column for column in merged.columns if column not in ordered_columns]

    return merged[ordered_columns + extra_columns]


def build_llm_payloads(db_name: str, inventory: pd.DataFrame) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []

    existing_columns = [column for column in LLM_COLUMNS if column in inventory.columns]

    for _, row in inventory.iterrows():
        item = {
            "database_name": db_name,
            "reference": {
                column: to_jsonable(row.get(column)) for column in existing_columns
            },
            "prompt_context": {
                "business_category": to_jsonable(row.get("business_category")),
                "product_group": to_jsonable(row.get("product_group")),
                "product_name": to_jsonable(row.get("product_name")),
                "visual_caption": to_jsonable(row.get("caption")),
                "visual_keywords": to_jsonable(row.get("prompt_keywords")),
                "retrieval_text": to_jsonable(row.get("retrieval_text")),
                "ad_prompt_hint": to_jsonable(row.get("ad_prompt_hint")),
            },
        }
        payloads.append(item)

    return payloads


def build_master_summary(final_db_root: Path, db_dirs: list[Path]) -> dict[str, Any]:
    versions = []

    for db_dir in db_dirs:
        summary = read_json(db_dir / "summary.json")

        if "version_name" not in summary:
            summary["version_name"] = db_dir.name
        if "database_name" not in summary:
            summary["database_name"] = db_dir.name
        if "output_dir" not in summary:
            summary["output_dir"] = str(db_dir.relative_to(PROJECT_ROOT))

        files = summary.get("files")
        if not isinstance(files, dict):
            summary["files"] = {
                "images_dir": str(db_dir / "images"),
                "metadata": str(db_dir / "metadata.parquet"),
                "prompt_metadata": str(db_dir / "prompt_metadata.parquet"),
                "embeddings": str(db_dir / "embeddings.npy"),
                "faiss_index": str(db_dir / "faiss.index"),
                "mapping": str(db_dir / "mapping.csv"),
                "summary": str(db_dir / "summary.json"),
                "management_inventory": str(db_dir / "db_management_inventory.csv"),
                "llm_prompt_payloads": str(db_dir / "llm_prompt_payloads.json"),
            }
        else:
            files["management_inventory"] = str(db_dir / "db_management_inventory.csv")
            files["llm_prompt_payloads"] = str(db_dir / "llm_prompt_payloads.json")

        versions.append(summary)

    return {
        "version_count": len(versions),
        "versions": versions,
        "final_db_root": str(final_db_root),
        "master_summary_path": str(final_db_root / "final_db_summary.json"),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export management CSV, LLM prompt JSON, and master final DB summary."
    )
    parser.add_argument(
        "--final-db-root",
        type=str,
        default=str(DEFAULT_FINAL_DB_ROOT),
    )
    parser.add_argument(
        "--db-names",
        type=str,
        default=None,
        help="Comma-separated DB folder names. Default: all complete DB folders.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    final_db_root = Path(args.final_db_root)

    if not final_db_root.is_absolute():
        final_db_root = PROJECT_ROOT / final_db_root

    requested = None
    if args.db_names:
        requested = [name.strip() for name in args.db_names.split(",") if name.strip()]

    db_dirs = discover_db_dirs(final_db_root, requested)

    if not db_dirs:
        raise FileNotFoundError(f"No complete final DB folders found: {final_db_root}")

    for db_dir in db_dirs:
        db_name = db_dir.name
        inventory = build_management_inventory(db_name, db_dir)
        payloads = build_llm_payloads(db_name, inventory)

        inventory_path = db_dir / "db_management_inventory.csv"
        payload_path = db_dir / "llm_prompt_payloads.json"

        inventory.to_csv(inventory_path, index=False, encoding="utf-8-sig")
        write_json(payloads, payload_path)

        print(f"[OK] {db_name}: {inventory_path}")
        print(f"[OK] {db_name}: {payload_path}")

    master_summary = build_master_summary(final_db_root, db_dirs)
    master_summary_path = final_db_root / "final_db_summary.json"
    write_json(master_summary, master_summary_path)

    print(f"[OK] master summary: {master_summary_path}")


if __name__ == "__main__":
    main()
