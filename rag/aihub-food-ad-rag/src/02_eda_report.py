from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict

import pandas as pd
import yaml


def load_pipeline_config(config_path: str) -> Dict[str, Any]:
    config_file = Path(config_path)

    if not config_file.exists():
        raise FileNotFoundError(f"Config file not found: {config_file}")

    with config_file.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def save_json(data: Dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def save_csv(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False, encoding="utf-8-sig")


def build_distribution(
    df: pd.DataFrame,
    column: str,
    output_column_name: str,
) -> pd.DataFrame:
    if column not in df.columns:
        return pd.DataFrame(columns=[output_column_name, "count", "ratio"])

    dist = (
        df[column]
        .fillna("")
        .astype(str)
        .replace("", "(missing)")
        .value_counts()
        .reset_index()
    )

    dist.columns = [output_column_name, "count"]
    dist["ratio"] = dist["count"] / len(df)

    return dist


def build_missing_value_report(df: pd.DataFrame) -> pd.DataFrame:
    rows = []

    for col in df.columns:
        missing_count = int(df[col].isna().sum())

        if df[col].dtype == "object":
            empty_count = int((df[col].fillna("").astype(str).str.strip() == "").sum())
        else:
            empty_count = 0

        total_missing = max(missing_count, empty_count)

        rows.append(
            {
                "column": col,
                "missing_count": total_missing,
                "missing_ratio": total_missing / len(df) if len(df) > 0 else 0,
                "dtype": str(df[col].dtype),
            }
        )

    result = pd.DataFrame(rows).sort_values("missing_ratio", ascending=False)
    return result


def build_image_size_report(df: pd.DataFrame) -> pd.DataFrame:
    numeric_cols = [
        "image_width",
        "image_height",
        "image_size_bytes",
        "image_weight",
        "serving_weight",
        "nutrition_g",
        "nutrition_energy",
        "nutrition_cal",
        "nutrition_fat",
        "nutrition_protein",
        "nutrition_sodium",
    ]

    rows = []

    for col in numeric_cols:
        if col not in df.columns:
            continue

        series = pd.to_numeric(df[col], errors="coerce")

        rows.append(
            {
                "column": col,
                "count": int(series.notna().sum()),
                "missing_count": int(series.isna().sum()),
                "min": float(series.min()) if series.notna().any() else None,
                "mean": float(series.mean()) if series.notna().any() else None,
                "median": float(series.median()) if series.notna().any() else None,
                "max": float(series.max()) if series.notna().any() else None,
            }
        )

    return pd.DataFrame(rows)


def build_eda_summary(df: pd.DataFrame) -> Dict[str, Any]:
    summary: Dict[str, Any] = {}

    summary["row_count"] = int(len(df))
    summary["column_count"] = int(len(df.columns))

    if "json_valid" in df.columns:
        summary["valid_json_count"] = int(df["json_valid"].fillna(False).sum())
        summary["invalid_json_count"] = int(len(df) - summary["valid_json_count"])

    if "image_path" in df.columns:
        summary["matched_image_count"] = int(df["image_path"].notna().sum())
        summary["missing_image_count"] = int(df["image_path"].isna().sum())

    if "original_food_name" in df.columns:
        food_name = df["original_food_name"].fillna("").astype(str).str.strip()
        summary["food_name_available_count"] = int((food_name != "").sum())
        summary["food_name_missing_count"] = int((food_name == "").sum())
        summary["unique_food_name_count"] = int(food_name[food_name != ""].nunique())

    if "food_code" in df.columns:
        food_code = df["food_code"].fillna("").astype(str).str.strip()
        summary["food_code_available_count"] = int((food_code != "").sum())
        summary["food_code_missing_count"] = int((food_code == "").sum())
        summary["unique_food_code_count"] = int(food_code[food_code != ""].nunique())

    if "image_size_bytes" in df.columns:
        image_size = pd.to_numeric(df["image_size_bytes"], errors="coerce")
        summary["total_image_size_gb"] = float(image_size.sum() / (1024**3))
        summary["avg_image_size_mb"] = float(image_size.mean() / (1024**2))

    if "image_width" in df.columns and "image_height" in df.columns:
        width = pd.to_numeric(df["image_width"], errors="coerce")
        height = pd.to_numeric(df["image_height"], errors="coerce")
        summary["avg_image_width"] = float(width.mean())
        summary["avg_image_height"] = float(height.mean())
        summary["min_image_width"] = float(width.min())
        summary["min_image_height"] = float(height.min())
        summary["max_image_width"] = float(width.max())
        summary["max_image_height"] = float(height.max())

    return summary


def save_simple_html_table(
    df: pd.DataFrame, title: str, output_path: Path, max_rows: int = 100
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)

    html = f"""
<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <title>{title}</title>
    <style>
        body {{
            font-family: Arial, sans-serif;
            margin: 32px;
            line-height: 1.5;
        }}
        table {{
            border-collapse: collapse;
            width: 100%;
            font-size: 14px;
        }}
        th, td {{
            border: 1px solid #ddd;
            padding: 8px;
        }}
        th {{
            background-color: #f5f5f5;
        }}
    </style>
</head>
<body>
    <h1>{title}</h1>
    {df.head(max_rows).to_html(index=False)}
</body>
</html>
"""

    output_path.write_text(html, encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate EDA report from raw metadata parquet."
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
        help="Input raw_metadata.parquet path.",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="outputs/reports/eda_raw",
        help="EDA report output directory.",
    )

    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config = load_pipeline_config(args.config)
    paths = config.get("paths", {})

    input_path = Path(
        args.input
        or paths.get("raw_metadata_path", "data/metadata/raw_metadata.parquet")
    )
    output_dir = Path(args.output_dir)

    print("[INFO] AIHub Food Ad RAG - EDA Report")
    print(f"[INFO] input      : {input_path}")
    print(f"[INFO] output_dir : {output_dir}")

    if not input_path.exists():
        raise FileNotFoundError(f"Input metadata file not found: {input_path}")

    ensure_dir(output_dir)

    df = pd.read_parquet(input_path)

    summary = build_eda_summary(df)
    save_json(summary, output_dir / "eda_summary.json")

    food_name_dist = build_distribution(
        df,
        column="original_food_name",
        output_column_name="original_food_name",
    )
    save_csv(food_name_dist, output_dir / "food_name_distribution.csv")

    food_code_dist = build_distribution(
        df,
        column="food_code",
        output_column_name="food_code",
    )
    save_csv(food_code_dist, output_dir / "food_code_distribution.csv")

    image_ext_dist = build_distribution(
        df,
        column="image_extension",
        output_column_name="image_extension",
    )
    save_csv(image_ext_dist, output_dir / "image_extension_distribution.csv")

    missing_report = build_missing_value_report(df)
    save_csv(missing_report, output_dir / "missing_value_report.csv")

    image_size_report = build_image_size_report(df)
    save_csv(image_size_report, output_dir / "image_size_report.csv")

    save_simple_html_table(
        food_name_dist,
        title="Top Food Name Distribution",
        output_path=output_dir / "top_food_names.html",
        max_rows=100,
    )

    print("[DONE] EDA report generated.")
    print(f"[DONE] summary                  : {output_dir / 'eda_summary.json'}")
    print(
        f"[DONE] food_name_distribution   : {output_dir / 'food_name_distribution.csv'}"
    )
    print(
        f"[DONE] food_code_distribution   : {output_dir / 'food_code_distribution.csv'}"
    )
    print(
        f"[DONE] missing_value_report     : {output_dir / 'missing_value_report.csv'}"
    )
    print(f"[DONE] image_size_report        : {output_dir / 'image_size_report.csv'}")
    print(f"[DONE] top_food_names.html      : {output_dir / 'top_food_names.html'}")
    print("[SUMMARY]")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
