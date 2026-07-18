from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List

import cv2
import numpy as np
import pandas as pd
import yaml
from PIL import Image, UnidentifiedImageError
from tqdm import tqdm
from utils.reproducibility import DEFAULT_RANDOM_SEED, set_global_seed


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


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        if pd.isna(value):
            return default
        return float(value)
    except Exception:
        return default


def compute_blur_score(image_path: Path) -> float:
    """
    OpenCV Laplacian variance로 블러 정도를 계산한다.
    값이 낮을수록 흐릿한 이미지일 가능성이 높다.
    """
    image = cv2.imdecode(
        np.fromfile(str(image_path), dtype=np.uint8), cv2.IMREAD_GRAYSCALE
    )

    if image is None:
        return -1.0

    score = cv2.Laplacian(image, cv2.CV_64F).var()
    return float(score)


def inspect_image(
    image_path_value: Any,
    min_width: int,
    min_height: int,
    blur_threshold: float,
) -> Dict[str, Any]:
    """
    단일 이미지 품질 검사.
    """
    result: Dict[str, Any] = {
        "quality_pass": False,
        "quality_status": "unknown",
        "quality_reasons": "",
        "quality_score": 0.0,
        "actual_width": None,
        "actual_height": None,
        "actual_file_size_bytes": None,
        "blur_score": None,
        "image_open_ok": False,
        "image_exists": False,
    }

    if image_path_value is None or str(image_path_value).strip() == "":
        result["quality_status"] = "missing_image_path"
        result["quality_reasons"] = "image_path is empty"
        return result

    image_path = Path(str(image_path_value))

    if not image_path.exists():
        result["quality_status"] = "file_not_found"
        result["quality_reasons"] = "image file does not exist"
        return result

    result["image_exists"] = True

    file_size = image_path.stat().st_size
    result["actual_file_size_bytes"] = int(file_size)

    if file_size <= 0:
        result["quality_status"] = "empty_file"
        result["quality_reasons"] = "file size is 0"
        return result

    reasons: List[str] = []
    score = 100.0

    try:
        with Image.open(image_path) as img:
            img.verify()

        with Image.open(image_path) as img:
            width, height = img.size

        result["image_open_ok"] = True
        result["actual_width"] = int(width)
        result["actual_height"] = int(height)

    except (UnidentifiedImageError, OSError, ValueError) as e:
        result["quality_status"] = "image_open_failed"
        result["quality_reasons"] = f"cannot open image: {str(e)}"
        result["quality_score"] = 0.0
        return result

    if result["actual_width"] < min_width:
        reasons.append(f"width<{min_width}")
        score -= 30

    if result["actual_height"] < min_height:
        reasons.append(f"height<{min_height}")
        score -= 30

    blur_score = compute_blur_score(image_path)
    result["blur_score"] = blur_score

    if blur_score < 0:
        reasons.append("blur_score_failed")
        score -= 30
    elif blur_score < blur_threshold:
        reasons.append(f"blur_score<{blur_threshold}")
        score -= 40

    score = max(0.0, min(100.0, score))
    result["quality_score"] = float(score)

    if reasons:
        result["quality_pass"] = False
        result["quality_status"] = "rejected"
        result["quality_reasons"] = "|".join(reasons)
    else:
        result["quality_pass"] = True
        result["quality_status"] = "passed"
        result["quality_reasons"] = ""

    return result


def build_quality_summary(df: pd.DataFrame) -> Dict[str, Any]:
    total_count = len(df)
    pass_count = int(df["quality_pass"].sum()) if "quality_pass" in df.columns else 0
    rejected_count = total_count - pass_count

    summary: Dict[str, Any] = {
        "total_count": int(total_count),
        "quality_pass_count": int(pass_count),
        "quality_rejected_count": int(rejected_count),
        "quality_pass_ratio": (
            float(pass_count / total_count) if total_count > 0 else 0.0
        ),
        "quality_rejected_ratio": (
            float(rejected_count / total_count) if total_count > 0 else 0.0
        ),
    }

    if "quality_status" in df.columns:
        summary["quality_status_count"] = df["quality_status"].value_counts().to_dict()

    if "quality_score" in df.columns:
        score = pd.to_numeric(df["quality_score"], errors="coerce")
        summary["quality_score_min"] = (
            float(score.min()) if score.notna().any() else None
        )
        summary["quality_score_mean"] = (
            float(score.mean()) if score.notna().any() else None
        )
        summary["quality_score_median"] = (
            float(score.median()) if score.notna().any() else None
        )
        summary["quality_score_max"] = (
            float(score.max()) if score.notna().any() else None
        )

    if "blur_score" in df.columns:
        blur = pd.to_numeric(df["blur_score"], errors="coerce")
        summary["blur_score_min"] = float(blur.min()) if blur.notna().any() else None
        summary["blur_score_mean"] = float(blur.mean()) if blur.notna().any() else None
        summary["blur_score_median"] = (
            float(blur.median()) if blur.notna().any() else None
        )
        summary["blur_score_max"] = float(blur.max()) if blur.notna().any() else None

    if "actual_width" in df.columns and "actual_height" in df.columns:
        width = pd.to_numeric(df["actual_width"], errors="coerce")
        height = pd.to_numeric(df["actual_height"], errors="coerce")
        summary["actual_width_min"] = (
            float(width.min()) if width.notna().any() else None
        )
        summary["actual_height_min"] = (
            float(height.min()) if height.notna().any() else None
        )
        summary["actual_width_mean"] = (
            float(width.mean()) if width.notna().any() else None
        )
        summary["actual_height_mean"] = (
            float(height.mean()) if height.notna().any() else None
        )

    return summary


def save_distribution(df: pd.DataFrame, column: str, output_path: Path) -> None:
    if column not in df.columns:
        save_csv(pd.DataFrame(columns=[column, "count", "ratio"]), output_path)
        return

    dist = (
        df[column]
        .fillna("")
        .astype(str)
        .replace("", "(missing)")
        .value_counts()
        .reset_index()
    )

    dist.columns = [column, "count"]
    dist["ratio"] = dist["count"] / len(df)

    save_csv(dist, output_path)


def save_score_distribution(df: pd.DataFrame, output_path: Path) -> None:
    if "quality_score" not in df.columns:
        save_csv(pd.DataFrame(columns=["score_range", "count", "ratio"]), output_path)
        return

    score = pd.to_numeric(df["quality_score"], errors="coerce").fillna(0)

    bins = [-1, 0, 20, 40, 60, 80, 100]
    labels = ["0", "1-20", "21-40", "41-60", "61-80", "81-100"]

    score_range = pd.cut(score, bins=bins, labels=labels)

    result = score_range.value_counts().sort_index().reset_index()

    result.columns = ["score_range", "count"]
    result["ratio"] = result["count"] / len(df)

    save_csv(result, output_path)


def save_rejected_images(df: pd.DataFrame, output_path: Path) -> None:
    if "quality_pass" not in df.columns:
        save_csv(pd.DataFrame(), output_path)
        return

    rejected = df[df["quality_pass"] == False].copy()

    columns = [
        "original_food_name",
        "food_code",
        "business_category",
        "product_group",
        "image_path",
        "quality_status",
        "quality_reasons",
        "quality_score",
        "blur_score",
        "actual_width",
        "actual_height",
        "actual_file_size_bytes",
    ]

    existing_cols = [col for col in columns if col in rejected.columns]

    if existing_cols:
        rejected = rejected[existing_cols]

    save_csv(rejected, output_path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Filter low-quality images from category enriched metadata."
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
        help="Input category enriched metadata parquet path.",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Output quality filtered metadata parquet path.",
    )
    parser.add_argument(
        "--report-dir",
        type=str,
        default="outputs/reports/quality_filter",
        help="Quality filter report directory.",
    )
    parser.add_argument(
        "--min-width",
        type=int,
        default=None,
        help="Minimum image width.",
    )
    parser.add_argument(
        "--min-height",
        type=int,
        default=None,
        help="Minimum image height.",
    )
    parser.add_argument(
        "--blur-threshold",
        type=float,
        default=None,
        help="Laplacian variance blur threshold.",
    )
    parser.add_argument(
        "--keep-rejected",
        action="store_true",
        help="If set, save all records with quality columns. Otherwise save only passed records.",
    )

    return parser.parse_args()


def main() -> None:
    set_global_seed(DEFAULT_RANDOM_SEED)
    args = parse_args()

    config = load_pipeline_config(args.config)
    paths = config.get("paths", {})
    quality_config = config.get("quality_filter", {})

    input_path = Path(
        args.input
        or paths.get(
            "category_enriched_metadata_path",
            "data/metadata/category_enriched_metadata.parquet",
        )
    )
    output_path = Path(
        args.output
        or paths.get(
            "quality_filtered_metadata_path",
            "data/metadata/quality_filtered_metadata.parquet",
        )
    )
    report_dir = Path(args.report_dir)

    min_width = int(args.min_width or quality_config.get("min_width", 300))
    min_height = int(args.min_height or quality_config.get("min_height", 300))
    blur_threshold = float(
        args.blur_threshold or quality_config.get("blur_threshold", 100)
    )

    print("[INFO] AIHub Food Ad RAG - Quality Filter")
    print(f"[INFO] input          : {input_path}")
    print(f"[INFO] output         : {output_path}")
    print(f"[INFO] report_dir     : {report_dir}")
    print(f"[INFO] min_width      : {min_width}")
    print(f"[INFO] min_height     : {min_height}")
    print(f"[INFO] blur_threshold : {blur_threshold}")
    print(f"[INFO] keep_rejected  : {args.keep_rejected}")

    if not input_path.exists():
        raise FileNotFoundError(f"Input metadata not found: {input_path}")

    df = pd.read_parquet(input_path)

    if "image_path" not in df.columns:
        raise ValueError("Input metadata must contain image_path column.")

    quality_records = []

    for image_path in tqdm(df["image_path"], desc="Inspecting images"):
        quality_records.append(
            inspect_image(
                image_path_value=image_path,
                min_width=min_width,
                min_height=min_height,
                blur_threshold=blur_threshold,
            )
        )

    quality_df = pd.DataFrame(quality_records)
    result_df = pd.concat([df.reset_index(drop=True), quality_df], axis=1)

    summary = build_quality_summary(result_df)

    ensure_parent_dir(output_path)

    if args.keep_rejected:
        output_df = result_df
    else:
        output_df = result_df[result_df["quality_pass"] == True].copy()

    output_df.to_parquet(output_path, index=False)

    ensure_dir(report_dir)

    save_json(summary, report_dir / "quality_filter_summary.json")
    save_distribution(
        result_df, "quality_status", report_dir / "quality_status_distribution.csv"
    )
    save_distribution(
        result_df, "quality_reasons", report_dir / "quality_reason_distribution.csv"
    )
    save_score_distribution(result_df, report_dir / "quality_score_distribution.csv")
    save_rejected_images(result_df, report_dir / "rejected_images.csv")

    print("[DONE] Quality filtering completed.")
    print(f"[DONE] output metadata : {output_path}")
    print(f"[DONE] summary         : {report_dir / 'quality_filter_summary.json'}")
    print(f"[DONE] rejected images : {report_dir / 'rejected_images.csv'}")
    print("[SUMMARY]")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
