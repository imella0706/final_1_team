from __future__ import annotations

import ast
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from tqdm import tqdm
from utils.reproducibility import DEFAULT_RANDOM_SEED, set_global_seed

PROJECT_ROOT = Path(__file__).resolve().parents[1]

INPUT_METADATA = PROJECT_ROOT / "data" / "metadata" / "tagged_metadata.parquet"

OUTPUT_DIR = PROJECT_ROOT / "data" / "metadata" / "diverse_sampling"

OUTPUT_METADATA = OUTPUT_DIR / "diverse_candidate_metadata.parquet"
OUTPUT_PREVIEW = OUTPUT_DIR / "diverse_candidate_preview.csv"
OUTPUT_SUMMARY = OUTPUT_DIR / "diverse_candidate_summary.json"


# ============================================================
# Utility
# ============================================================


def safe_float(value: Any, default: float = np.nan) -> float:
    """
    값을 float로 안전하게 변환한다.
    """
    try:
        if value is None:
            return default

        if isinstance(value, str) and not value.strip():
            return default

        result = float(value)

        if math.isnan(result):
            return default

        return result

    except (TypeError, ValueError):
        return default


def minmax_normalize(series: pd.Series) -> pd.Series:
    """
    Series를 0~1 범위로 정규화한다.
    값이 모두 같으면 1.0으로 처리한다.
    """
    numeric = pd.to_numeric(series, errors="coerce")

    minimum = numeric.min()
    maximum = numeric.max()

    if pd.isna(minimum) or pd.isna(maximum):
        return pd.Series(np.zeros(len(series)), index=series.index)

    if maximum == minimum:
        return pd.Series(np.ones(len(series)), index=series.index)

    return (numeric - minimum) / (maximum - minimum)


# ============================================================
# View type
# ============================================================


def extract_view_type(row: pd.Series) -> str:
    """
    촬영 방향을 추출한다.

    우선순위:
    1. image_path 또는 relative_image_path의 폴더명
    2. view_group_code
    3. caption_camera_angle
    """

    path_candidates = [
        row.get("image_path", ""),
        row.get("relative_image_path", ""),
        row.get("annotation_path", ""),
    ]

    normalized_path = " / ".join(
        str(value).replace("\\", "/").lower()
        for value in path_candidates
        if value is not None
    )

    if "정위" in normalized_path:
        return "front"

    if "측면" in normalized_path:
        return "side"

    view_group_code = str(row.get("view_group_code", "")).lower()
    camera_angle = str(row.get("caption_camera_angle", "")).lower()

    front_terms = [
        "front",
        "top",
        "overhead",
        "bird",
        "정면",
        "정위",
        "위에서",
    ]

    side_terms = [
        "side",
        "lateral",
        "45 degree",
        "45-degree",
        "측면",
    ]

    combined = f"{view_group_code} {camera_angle}"

    if any(term in combined for term in front_terms):
        return "front"

    if any(term in combined for term in side_terms):
        return "side"

    return "unknown"


# ============================================================
# Bounding box parsing
# ============================================================


def parse_possible_json(value: Any) -> Any:
    """
    문자열로 저장된 dict/list를 복구한다.
    """
    if isinstance(value, (dict, list)):
        return value

    if not isinstance(value, str):
        return value

    stripped = value.strip()

    if not stripped:
        return value

    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        pass

    try:
        return ast.literal_eval(stripped)
    except (ValueError, SyntaxError):
        return value


def find_bbox_candidates(obj: Any) -> list[dict[str, float]]:
    """
    JSON 전체를 재귀 탐색하여 Bounding Box 후보를 찾는다.

    지원 형식 예:
    {
        "x": 100,
        "y": 200,
        "width": 1200,
        "height": 900
    }

    {
        "bbox": [x, y, width, height]
    }

    {
        "x_min": ...,
        "y_min": ...,
        "x_max": ...,
        "y_max": ...
    }
    """
    candidates: list[dict[str, float]] = []

    if isinstance(obj, dict):
        normalized = {
            str(key).lower(): parse_possible_json(value) for key, value in obj.items()
        }

        # x, y, width, height
        key_sets = [
            ("x", "y", "width", "height"),
            ("left", "top", "width", "height"),
            ("bbox_x", "bbox_y", "bbox_width", "bbox_height"),
        ]

        for x_key, y_key, w_key, h_key in key_sets:
            if all(key in normalized for key in (x_key, y_key, w_key, h_key)):
                x = safe_float(normalized[x_key])
                y = safe_float(normalized[y_key])
                width = safe_float(normalized[w_key])
                height = safe_float(normalized[h_key])

                if not np.isnan(x) and not np.isnan(y) and width > 0 and height > 0:
                    candidates.append(
                        {
                            "bbox_x": x,
                            "bbox_y": y,
                            "bbox_width": width,
                            "bbox_height": height,
                        }
                    )

        # x_min, y_min, x_max, y_max
        minmax_sets = [
            ("x_min", "y_min", "x_max", "y_max"),
            ("xmin", "ymin", "xmax", "ymax"),
        ]

        for xmin_key, ymin_key, xmax_key, ymax_key in minmax_sets:
            if all(
                key in normalized for key in (xmin_key, ymin_key, xmax_key, ymax_key)
            ):
                xmin = safe_float(normalized[xmin_key])
                ymin = safe_float(normalized[ymin_key])
                xmax = safe_float(normalized[xmax_key])
                ymax = safe_float(normalized[ymax_key])

                width = xmax - xmin
                height = ymax - ymin

                if width > 0 and height > 0:
                    candidates.append(
                        {
                            "bbox_x": xmin,
                            "bbox_y": ymin,
                            "bbox_width": width,
                            "bbox_height": height,
                        }
                    )

        # bbox: [x, y, width, height]
        bbox_value = normalized.get("bbox")

        if isinstance(bbox_value, (list, tuple)) and len(bbox_value) >= 4:
            x = safe_float(bbox_value[0])
            y = safe_float(bbox_value[1])
            width = safe_float(bbox_value[2])
            height = safe_float(bbox_value[3])

            if width > 0 and height > 0:
                candidates.append(
                    {
                        "bbox_x": x,
                        "bbox_y": y,
                        "bbox_width": width,
                        "bbox_height": height,
                    }
                )

        for value in normalized.values():
            candidates.extend(find_bbox_candidates(value))

    elif isinstance(obj, list):
        for item in obj:
            candidates.extend(find_bbox_candidates(item))

    return candidates


def load_bbox_from_annotation(annotation_path: str) -> dict[str, Any]:
    """
    Annotation JSON에서 Bounding Box를 읽는다.

    여러 Bounding Box가 존재할 경우 면적이 가장 큰 박스를 대표 객체로 사용한다.
    """
    empty_result = {
        "bbox_found": False,
        "bbox_x": np.nan,
        "bbox_y": np.nan,
        "bbox_width": np.nan,
        "bbox_height": np.nan,
        "bbox_parse_error": "",
    }

    try:
        path = Path(str(annotation_path))

        if not path.is_absolute():
            path = PROJECT_ROOT / path

        if not path.exists():
            empty_result["bbox_parse_error"] = "annotation_not_found"
            return empty_result

        with path.open("r", encoding="utf-8-sig") as file:
            data = json.load(file)

        # 가능하면 2d_annotation을 우선 사용한다.
        preferred_nodes = []

        if isinstance(data, dict):
            data_node = data.get("data")

            if isinstance(data_node, dict):
                preferred_nodes.extend(
                    [
                        data_node.get("2d_annotation"),
                        data_node.get("2D_annotation"),
                        data_node.get("annotation"),
                    ]
                )

            preferred_nodes.extend(
                [
                    data.get("2d_annotation"),
                    data.get("2D_annotation"),
                    data.get("annotation"),
                ]
            )

        candidates: list[dict[str, float]] = []

        for node in preferred_nodes:
            if node is not None:
                candidates.extend(find_bbox_candidates(node))

        # 지정 노드에서 찾지 못하면 전체 JSON 탐색
        if not candidates:
            candidates = find_bbox_candidates(data)

        if not candidates:
            empty_result["bbox_parse_error"] = "bbox_not_found"
            return empty_result

        largest_bbox = max(
            candidates,
            key=lambda item: item["bbox_width"] * item["bbox_height"],
        )

        return {
            "bbox_found": True,
            **largest_bbox,
            "bbox_parse_error": "",
        }

    except Exception as exc:
        empty_result["bbox_parse_error"] = f"{type(exc).__name__}: {exc}"
        return empty_result


# ============================================================
# Scores
# ============================================================


def calculate_bbox_features(row: pd.Series) -> pd.Series:
    """
    Bounding Box 비율과 중앙성 점수를 계산한다.
    """
    image_width = safe_float(row.get("actual_width", row.get("image_width")))

    image_height = safe_float(row.get("actual_height", row.get("image_height")))

    bbox_x = safe_float(row.get("bbox_x"))
    bbox_y = safe_float(row.get("bbox_y"))
    bbox_width = safe_float(row.get("bbox_width"))
    bbox_height = safe_float(row.get("bbox_height"))

    result = {
        "bbox_ratio": np.nan,
        "bbox_center_x": np.nan,
        "bbox_center_y": np.nan,
        "normalized_center_distance": np.nan,
        "center_score": 0.0,
        "bbox_40_70_match": False,
    }

    if image_width <= 0 or image_height <= 0 or bbox_width <= 0 or bbox_height <= 0:
        return pd.Series(result)

    image_area = image_width * image_height
    bbox_area = bbox_width * bbox_height

    bbox_ratio = bbox_area / image_area

    bbox_center_x = bbox_x + bbox_width / 2
    bbox_center_y = bbox_y + bbox_height / 2

    image_center_x = image_width / 2
    image_center_y = image_height / 2

    center_distance = math.sqrt(
        (bbox_center_x - image_center_x) ** 2 + (bbox_center_y - image_center_y) ** 2
    )

    maximum_distance = math.sqrt(image_center_x**2 + image_center_y**2)

    normalized_distance = (
        center_distance / maximum_distance if maximum_distance > 0 else 1.0
    )

    center_score = max(0.0, 1.0 - normalized_distance)

    result.update(
        {
            "bbox_ratio": bbox_ratio,
            "bbox_center_x": bbox_center_x,
            "bbox_center_y": bbox_center_y,
            "normalized_center_distance": normalized_distance,
            "center_score": center_score,
            "bbox_40_70_match": 0.40 <= bbox_ratio <= 0.70,
        }
    )

    return pd.Series(result)


def calculate_bbox_range_score(ratio: float) -> float:
    """
    현재 정책인 40~70%에 대한 점수를 계산한다.

    - 40~70% 이내: 1점
    - 범위를 벗어나면 가장 가까운 경계에서 멀어질수록 감점
    """
    if pd.isna(ratio):
        return 0.0

    if 0.40 <= ratio <= 0.70:
        return 1.0

    if ratio < 0.40:
        return max(0.0, 1.0 - (0.40 - ratio) / 0.40)

    return max(0.0, 1.0 - (ratio - 0.70) / 0.30)


# ============================================================
# Main
# ============================================================


def main() -> None:
    set_global_seed(DEFAULT_RANDOM_SEED)
    if not INPUT_METADATA.exists():
        raise FileNotFoundError(f"입력 파일이 없습니다: {INPUT_METADATA}")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print(f"[INFO] Loading metadata: {INPUT_METADATA}")
    df = pd.read_parquet(INPUT_METADATA).copy()

    required_columns = [
        "annotation_path",
        "image_path",
        "original_food_name",
        "blur_score",
        "actual_width",
        "actual_height",
    ]

    missing_columns = [
        column for column in required_columns if column not in df.columns
    ]

    if missing_columns:
        raise KeyError(f"필수 컬럼이 없습니다: {missing_columns}")

    print(f"[INFO] Rows: {len(df):,}")

    # 촬영 방향
    print("[INFO] Extracting view type...")
    df["view_type"] = df.apply(extract_view_type, axis=1)

    # Bounding Box
    print("[INFO] Parsing Bounding Box from annotations...")

    bbox_records = []

    for annotation_path in tqdm(
        df["annotation_path"].tolist(),
        total=len(df),
        desc="Bounding Box",
    ):
        bbox_records.append(load_bbox_from_annotation(annotation_path))

    bbox_df = pd.DataFrame(bbox_records)
    df = pd.concat(
        [
            df.reset_index(drop=True),
            bbox_df.reset_index(drop=True),
        ],
        axis=1,
    )

    # Bounding Box 비율 및 중앙성
    print("[INFO] Calculating bbox ratio and center score...")

    bbox_features = df.apply(
        calculate_bbox_features,
        axis=1,
    )

    df = pd.concat(
        [
            df.reset_index(drop=True),
            bbox_features.reset_index(drop=True),
        ],
        axis=1,
    )

    # 해상도
    df["resolution_pixels"] = pd.to_numeric(
        df["actual_width"], errors="coerce"
    ) * pd.to_numeric(df["actual_height"], errors="coerce")

    # 점수 정규화
    df["blur_score_normalized"] = minmax_normalize(df["blur_score"])

    df["resolution_score"] = minmax_normalize(df["resolution_pixels"])

    df["bbox_range_score"] = df["bbox_ratio"].apply(calculate_bbox_range_score)

    # 정렬·확인용 대표 점수
    # 실제 우선순위는 이후 단계에서 계층적으로 적용하고,
    # 이 점수는 동률 해소와 품질 비교용으로 사용한다.
    df["representative_score"] = (
        0.35 * df["bbox_range_score"]
        + 0.30 * df["center_score"]
        + 0.20 * df["blur_score_normalized"]
        + 0.15 * df["resolution_score"]
    )

    # 파일 저장
    df.to_parquet(
        OUTPUT_METADATA,
        index=False,
    )

    preview_columns = [
        "original_food_name",
        "business_category",
        "product_group",
        "view_type",
        "image_path",
        "bbox_found",
        "bbox_ratio",
        "bbox_40_70_match",
        "center_score",
        "blur_score",
        "blur_score_normalized",
        "actual_width",
        "actual_height",
        "resolution_score",
        "representative_score",
    ]

    existing_preview_columns = [
        column for column in preview_columns if column in df.columns
    ]

    (
        df[existing_preview_columns]
        .sort_values(
            "representative_score",
            ascending=False,
        )
        .head(1000)
        .to_csv(
            OUTPUT_PREVIEW,
            index=False,
            encoding="utf-8-sig",
        )
    )

    summary = {
        "input_rows": int(len(df)),
        "unique_food_count": int(df["original_food_name"].nunique()),
        "view_type_distribution": {
            str(key): int(value)
            for key, value in (
                df["view_type"].value_counts(dropna=False).to_dict().items()
            )
        },
        "bbox_found_count": int(df["bbox_found"].fillna(False).sum()),
        "bbox_missing_count": int((~df["bbox_found"].fillna(False)).sum()),
        "bbox_40_70_count": int(df["bbox_40_70_match"].fillna(False).sum()),
        "bbox_ratio_statistics": {
            "mean": safe_float(df["bbox_ratio"].mean(), 0.0),
            "median": safe_float(df["bbox_ratio"].median(), 0.0),
            "min": safe_float(df["bbox_ratio"].min(), 0.0),
            "max": safe_float(df["bbox_ratio"].max(), 0.0),
        },
        "output_metadata": str(OUTPUT_METADATA),
        "output_preview": str(OUTPUT_PREVIEW),
    }

    with OUTPUT_SUMMARY.open(
        "w",
        encoding="utf-8",
    ) as file:
        json.dump(
            summary,
            file,
            ensure_ascii=False,
            indent=2,
        )

    print("\n[OK] Diverse candidate metadata generated")
    print(f"[OK] Metadata: {OUTPUT_METADATA}")
    print(f"[OK] Preview: {OUTPUT_PREVIEW}")
    print(f"[OK] Summary: {OUTPUT_SUMMARY}")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
