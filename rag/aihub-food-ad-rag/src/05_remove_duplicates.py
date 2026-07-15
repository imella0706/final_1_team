from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List, Tuple

import imagehash
import pandas as pd
import yaml
from PIL import Image, UnidentifiedImageError
from tqdm import tqdm


def load_pipeline_config(config_path: str | Path) -> Dict[str, Any]:
    config_file = Path(config_path)

    if not config_file.exists():
        raise FileNotFoundError(f"Config file not found: {config_file}")

    with config_file.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def ensure_parent_dir(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def save_json(data: Dict[str, Any], path: Path) -> None:
    ensure_parent_dir(path)

    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def save_csv(df: pd.DataFrame, path: Path) -> None:
    ensure_parent_dir(path)
    df.to_csv(path, index=False, encoding="utf-8-sig")


def compute_phash(image_path: str | Path) -> str:
    """
    이미지 perceptual hash 계산.
    거의 같은 이미지를 찾는 데 사용한다.
    """
    path = Path(str(image_path))

    with Image.open(path) as img:
        img = img.convert("RGB")
        phash = imagehash.phash(img)

    return str(phash)


def hamming_distance(hash_a: str, hash_b: str) -> int:
    """
    imagehash 문자열 간 거리 계산.
    값이 작을수록 유사한 이미지다.
    """
    return imagehash.hex_to_hash(hash_a) - imagehash.hex_to_hash(hash_b)


def build_hash_records(df: pd.DataFrame) -> pd.DataFrame:
    records: List[Dict[str, Any]] = []

    for idx, row in tqdm(df.iterrows(), total=len(df), desc="Computing pHash"):
        image_path = row.get("image_path")

        record = {
            "row_index": idx,
            "image_path": image_path,
            "phash": "",
            "hash_ok": False,
            "hash_error": "",
        }

        try:
            if image_path is None or str(image_path).strip() == "":
                raise ValueError("empty image_path")

            path = Path(str(image_path))

            if not path.exists():
                raise FileNotFoundError(f"file not found: {path}")

            record["phash"] = compute_phash(path)
            record["hash_ok"] = True

        except (UnidentifiedImageError, OSError, ValueError, FileNotFoundError) as e:
            record["hash_error"] = str(e)

        records.append(record)

    return pd.DataFrame(records)


def mark_duplicates_by_exact_hash(
    df: pd.DataFrame,
    hash_df: pd.DataFrame,
) -> pd.DataFrame:
    """
    1차 중복 제거:
    phash가 완전히 같은 이미지를 중복으로 처리한다.

    같은 hash 그룹에서 첫 번째 이미지만 keep.
    """
    result = df.reset_index(drop=True).copy()
    hash_df = hash_df.reset_index(drop=True).copy()

    result["phash"] = hash_df["phash"]
    result["hash_ok"] = hash_df["hash_ok"]
    result["hash_error"] = hash_df["hash_error"]

    result["duplicate_group_id"] = ""
    result["duplicate_status"] = "unique"
    result["duplicate_keep"] = True
    result["duplicate_reason"] = ""

    valid_hash = result[result["hash_ok"] == True].copy()

    duplicated_hashes = valid_hash["phash"][
        valid_hash["phash"].duplicated(keep=False)
    ].unique()

    group_id = 0

    for phash in duplicated_hashes:
        group_indices = result.index[result["phash"] == phash].tolist()

        if len(group_indices) <= 1:
            continue

        group_id += 1
        group_name = f"exact_hash_{group_id:06d}"

        keep_index = group_indices[0]

        for idx in group_indices:
            result.at[idx, "duplicate_group_id"] = group_name

            if idx == keep_index:
                result.at[idx, "duplicate_status"] = "duplicate_representative"
                result.at[idx, "duplicate_keep"] = True
                result.at[idx, "duplicate_reason"] = (
                    "representative_of_exact_hash_group"
                )
            else:
                result.at[idx, "duplicate_status"] = "duplicate_removed"
                result.at[idx, "duplicate_keep"] = False
                result.at[idx, "duplicate_reason"] = "same_phash_as_representative"

    # hash 계산 실패 이미지는 제거하지 않고 유지한다.
    result.loc[result["hash_ok"] == False, "duplicate_status"] = "hash_failed_keep"
    result.loc[result["hash_ok"] == False, "duplicate_keep"] = True
    result.loc[result["hash_ok"] == False, "duplicate_reason"] = (
        "hash_failed_keep_for_safety"
    )

    return result


def mark_near_duplicates(
    df: pd.DataFrame,
    threshold: int,
    max_compare_per_group: int = 2000,
) -> pd.DataFrame:
    """
    2차 중복 제거:
    같은 food_code 또는 original_food_name 그룹 안에서
    pHash hamming distance가 threshold 이하인 이미지를 near duplicate로 처리한다.

    전체 N^2 비교를 피하기 위해 음식명 그룹 단위로 비교한다.
    """
    result = df.copy()

    if threshold < 0:
        return result

    group_cols = []

    if "food_code" in result.columns:
        group_cols.append("food_code")
    elif "original_food_name" in result.columns:
        group_cols.append("original_food_name")

    if not group_cols:
        return result

    near_group_counter = 0

    valid_df = result[
        (result["hash_ok"] == True)
        & (result["duplicate_keep"] == True)
        & (result["phash"].fillna("") != "")
    ].copy()

    for _, group in tqdm(valid_df.groupby(group_cols), desc="Checking near duplicates"):
        group_indices = group.index.tolist()

        if len(group_indices) <= 1:
            continue

        # 너무 큰 그룹은 계산량을 막기 위해 exact hash만 사용한다.
        if len(group_indices) > max_compare_per_group:
            continue

        kept_indices: List[int] = []

        for idx in group_indices:
            current_hash = result.at[idx, "phash"]

            is_duplicate = False
            duplicate_of = None

            for kept_idx in kept_indices:
                kept_hash = result.at[kept_idx, "phash"]
                dist = hamming_distance(current_hash, kept_hash)

                if dist <= threshold:
                    is_duplicate = True
                    duplicate_of = kept_idx
                    break

            if is_duplicate:
                near_group_counter += 1
                group_name = f"near_hash_{near_group_counter:06d}"

                result.at[idx, "duplicate_group_id"] = group_name
                result.at[idx, "duplicate_status"] = "near_duplicate_removed"
                result.at[idx, "duplicate_keep"] = False
                result.at[idx, "duplicate_reason"] = (
                    f"phash_distance<={threshold};duplicate_of_row={duplicate_of}"
                )
            else:
                kept_indices.append(idx)

    return result


def build_duplicate_summary(df: pd.DataFrame) -> Dict[str, Any]:
    total_count = len(df)
    keep_count = (
        int(df["duplicate_keep"].sum())
        if "duplicate_keep" in df.columns
        else total_count
    )
    removed_count = total_count - keep_count

    summary: Dict[str, Any] = {
        "total_count": int(total_count),
        "deduplicated_count": int(keep_count),
        "removed_duplicate_count": int(removed_count),
        "removed_duplicate_ratio": (
            float(removed_count / total_count) if total_count > 0 else 0.0
        ),
    }

    if "duplicate_status" in df.columns:
        summary["duplicate_status_count"] = (
            df["duplicate_status"].value_counts().to_dict()
        )

    if "hash_ok" in df.columns:
        summary["hash_ok_count"] = int(df["hash_ok"].sum())
        summary["hash_failed_count"] = int((df["hash_ok"] == False).sum())

    if "phash" in df.columns:
        summary["unique_phash_count"] = int(
            df["phash"].replace("", pd.NA).dropna().nunique()
        )

    return summary


def save_duplicate_reports(result_df: pd.DataFrame, report_dir: Path) -> None:
    ensure_dir(report_dir)

    status_dist = (
        result_df["duplicate_status"]
        .fillna("")
        .astype(str)
        .replace("", "(missing)")
        .value_counts()
        .reset_index()
    )
    status_dist.columns = ["duplicate_status", "count"]
    status_dist["ratio"] = status_dist["count"] / len(result_df)

    save_csv(status_dist, report_dir / "duplicate_status_distribution.csv")

    removed = result_df[result_df["duplicate_keep"] == False].copy()

    columns = [
        "original_food_name",
        "food_code",
        "business_category",
        "product_group",
        "image_path",
        "phash",
        "duplicate_group_id",
        "duplicate_status",
        "duplicate_reason",
    ]

    existing_cols = [col for col in columns if col in removed.columns]

    if existing_cols:
        removed = removed[existing_cols]

    save_csv(removed, report_dir / "removed_duplicates.csv")

    hash_failed = result_df[result_df["hash_ok"] == False].copy()

    failed_cols = [
        "original_food_name",
        "food_code",
        "image_path",
        "hash_error",
    ]

    existing_failed_cols = [col for col in failed_cols if col in hash_failed.columns]

    if existing_failed_cols:
        hash_failed = hash_failed[existing_failed_cols]

    save_csv(hash_failed, report_dir / "hash_failed_images.csv")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Remove duplicate or near-duplicate images using perceptual hash."
    )

    parser.add_argument(
        "--config",
        type=str,
        default="configs/pipeline_config.yaml",
        help="Pipeline config path.",
    )
    parser.add_argument(
        "--input",
        type=str,
        default=None,
        help="Input quality filtered metadata parquet path.",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Output deduplicated metadata parquet path.",
    )
    parser.add_argument(
        "--report-dir",
        type=str,
        default="outputs/reports/duplicate_filter",
        help="Duplicate filter report directory.",
    )
    parser.add_argument(
        "--phash-threshold",
        type=int,
        default=None,
        help="Near duplicate pHash threshold. Use 0 for exact only.",
    )
    parser.add_argument(
        "--exact-only",
        action="store_true",
        help="Only remove exact same pHash duplicates.",
    )
    parser.add_argument(
        "--keep-removed",
        action="store_true",
        help="If set, output all rows with duplicate columns. Otherwise output only duplicate_keep=True rows.",
    )

    return parser.parse_args()


def main() -> None:
    args = parse_args()

    config = load_pipeline_config(args.config)
    paths = config.get("paths", {})
    duplicate_config = config.get("duplicate_filter", {})

    input_path = Path(
        args.input
        or paths.get(
            "quality_filtered_metadata_path",
            "data/metadata/quality_filtered_metadata.parquet",
        )
    )
    output_path = Path(
        args.output
        or paths.get(
            "deduplicated_metadata_path",
            "data/metadata/deduplicated_metadata.parquet",
        )
    )
    report_dir = Path(args.report_dir)

    default_threshold = int(duplicate_config.get("phash_threshold", 5))
    phash_threshold = int(
        args.phash_threshold if args.phash_threshold is not None else default_threshold
    )

    if args.exact_only:
        phash_threshold = -1

    print("[INFO] AIHub Food Ad RAG - Remove Duplicates")
    print(f"[INFO] input           : {input_path}")
    print(f"[INFO] output          : {output_path}")
    print(f"[INFO] report_dir      : {report_dir}")
    print(f"[INFO] phash_threshold : {phash_threshold}")
    print(f"[INFO] exact_only      : {args.exact_only}")
    print(f"[INFO] keep_removed    : {args.keep_removed}")

    if not input_path.exists():
        raise FileNotFoundError(f"Input metadata not found: {input_path}")

    df = pd.read_parquet(input_path)

    if "image_path" not in df.columns:
        raise ValueError("Input metadata must contain image_path column.")

    hash_df = build_hash_records(df)

    result_df = mark_duplicates_by_exact_hash(df, hash_df)

    if phash_threshold >= 0:
        result_df = mark_near_duplicates(
            result_df,
            threshold=phash_threshold,
        )

    summary = build_duplicate_summary(result_df)

    ensure_parent_dir(output_path)

    if args.keep_removed:
        output_df = result_df
    else:
        output_df = result_df[result_df["duplicate_keep"] == True].copy()

    output_df.to_parquet(output_path, index=False)

    save_json(summary, report_dir / "duplicate_filter_summary.json")
    save_duplicate_reports(result_df, report_dir)

    print("[DONE] Duplicate filtering completed.")
    print(f"[DONE] output metadata : {output_path}")
    print(f"[DONE] summary         : {report_dir / 'duplicate_filter_summary.json'}")
    print(f"[DONE] removed report  : {report_dir / 'removed_duplicates.csv'}")
    print("[SUMMARY]")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
