from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

# ============================================================
# Path configuration
# ============================================================

PROJECT_ROOT = Path(__file__).resolve().parents[1]

INPUT_PATH = (
    PROJECT_ROOT
    / "data"
    / "metadata"
    / "diverse_sampling"
    / "diverse_candidate_metadata.parquet"
)

OUTPUT_DIR = PROJECT_ROOT / "data" / "metadata" / "diverse_sampling"

OUTPUT_PATH = OUTPUT_DIR / "selected_representatives.parquet"
OUTPUT_CSV = OUTPUT_DIR / "selected_representatives.csv"
OUTPUT_EXCLUDED = OUTPUT_DIR / "excluded_candidates.csv"
OUTPUT_SUMMARY = OUTPUT_DIR / "representative_selection_summary.json"


# ============================================================
# Utility functions
# ============================================================


def ensure_numeric(
    df: pd.DataFrame,
    columns: list[str],
) -> pd.DataFrame:
    """
    지정된 컬럼들을 숫자형으로 변환한다.
    변환할 수 없는 값은 NaN으로 처리한다.
    """
    result = df.copy()

    for column in columns:
        if column not in result.columns:
            result[column] = np.nan

        result[column] = pd.to_numeric(
            result[column],
            errors="coerce",
        )

    return result


def normalize_food_name(value: object) -> str:
    """
    음식명을 그룹 키로 사용할 수 있도록 정규화한다.
    """
    if value is None:
        return "unknown_food"

    text = str(value).strip()

    if not text:
        return "unknown_food"

    return text


def prepare_selection_columns(df: pd.DataFrame) -> pd.DataFrame:
    """
    대표 이미지 선정을 위한 우선순위 컬럼을 정리한다.
    """
    result = df.copy()

    result["original_food_name"] = result["original_food_name"].apply(
        normalize_food_name
    )

    result["view_type"] = (
        result["view_type"].fillna("unknown").astype(str).str.strip().str.lower()
    )

    numeric_columns = [
        "bbox_ratio",
        "center_score",
        "blur_score",
        "blur_score_normalized",
        "resolution_pixels",
        "resolution_score",
        "quality_score",
        "representative_score",
    ]

    result = ensure_numeric(
        result,
        numeric_columns,
    )

    if "bbox_40_70_match" not in result.columns:
        result["bbox_40_70_match"] = result["bbox_ratio"].between(
            0.40, 0.70, inclusive="both"
        )

    result["bbox_40_70_match"] = result["bbox_40_70_match"].fillna(False).astype(bool)

    if "bbox_found" not in result.columns:
        result["bbox_found"] = result["bbox_ratio"].notna()

    result["bbox_found"] = result["bbox_found"].fillna(False).astype(bool)

    # 정위와 측면을 우선하고 unknown은 후순위로 둔다.
    view_priority_map = {
        "front": 2,
        "side": 2,
        "unknown": 0,
    }

    result["view_priority"] = (
        result["view_type"].map(view_priority_map).fillna(0).astype(int)
    )

    # Bounding Box가 실제 존재하고 40~70% 범위이면 가장 높은 우선순위
    result["bbox_priority"] = np.select(
        [
            result["bbox_found"] & result["bbox_40_70_match"],
            result["bbox_found"],
        ],
        [
            2,
            1,
        ],
        default=0,
    )

    # 음식 다양성을 확인하기 위한 키
    result["food_view_key"] = (
        result["original_food_name"].astype(str)
        + "__"
        + result["view_type"].astype(str)
    )

    return result


def select_representatives(
    df: pd.DataFrame,
    include_unknown_view: bool = False,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    음식명 × 촬영 방향별 대표 이미지 1장을 선택한다.

    우선순위:
    1. front 또는 side
    2. bbox 40~70% 구간
    3. center_score
    4. blur_score
    5. resolution_score
    6. quality_score
    """

    working_df = prepare_selection_columns(df)

    # 실제 요구사항은 정위·측면 각각 1장이므로 기본적으로 unknown 제외
    if not include_unknown_view:
        valid_view_mask = working_df["view_type"].isin(["front", "side"])
        selection_pool = working_df.loc[valid_view_mask].copy()
        unknown_view_df = working_df.loc[~valid_view_mask].copy()
    else:
        selection_pool = working_df.copy()
        unknown_view_df = working_df.iloc[0:0].copy()

    # 중요:
    # 단순 weighted score 하나로 정하지 않고
    # 사용자가 정한 우선순위를 계층적으로 적용한다.
    sort_columns = [
        "original_food_name",
        "view_type",
        "bbox_priority",
        "center_score",
        "blur_score_normalized",
        "resolution_score",
        "quality_score",
        "representative_score",
    ]

    ascending = [
        True,  # 음식명
        True,  # view type
        False,  # bbox 우선순위
        False,  # 중앙성
        False,  # 선명도
        False,  # 해상도
        False,  # 기존 품질점수
        False,  # 동률 해소용 종합점수
    ]

    selection_pool = selection_pool.sort_values(
        by=sort_columns,
        ascending=ascending,
        na_position="last",
        kind="mergesort",
    )

    # 음식명 × 촬영 방향별 첫 번째 이미지만 유지
    selected_df = selection_pool.drop_duplicates(
        subset=[
            "original_food_name",
            "view_type",
        ],
        keep="first",
    ).copy()

    selected_df["representative_selected"] = True
    selected_df["selection_rank_within_food_view"] = 1

    selected_indices = set(selected_df.index.tolist())

    excluded_from_valid_view = selection_pool.loc[
        ~selection_pool.index.isin(selected_indices)
    ].copy()

    excluded_from_valid_view["representative_selected"] = False
    excluded_from_valid_view["exclusion_reason"] = (
        "lower_priority_within_same_food_and_view"
    )

    if not unknown_view_df.empty:
        unknown_view_df["representative_selected"] = False
        unknown_view_df["exclusion_reason"] = "unknown_view_type"

    excluded_df = pd.concat(
        [
            excluded_from_valid_view,
            unknown_view_df,
        ],
        ignore_index=True,
    )

    selected_df = selected_df.reset_index(drop=True)
    excluded_df = excluded_df.reset_index(drop=True)

    # 최종 추적용 ID
    selected_df.insert(
        0,
        "representative_id",
        [f"REP_{index:06d}" for index in range(len(selected_df))],
    )

    return selected_df, excluded_df


def build_summary(
    input_df: pd.DataFrame,
    selected_df: pd.DataFrame,
    excluded_df: pd.DataFrame,
) -> dict:
    """
    대표 이미지 선정 결과를 요약한다.
    """

    food_view_counts = selected_df.groupby("original_food_name")["view_type"].nunique()

    foods_with_both_views = int((food_view_counts >= 2).sum())

    foods_with_one_view = int((food_view_counts == 1).sum())

    bbox_match_count = int(selected_df["bbox_40_70_match"].fillna(False).sum())

    selected_count = len(selected_df)

    return {
        "input_candidate_count": int(len(input_df)),
        "selected_representative_count": int(selected_count),
        "excluded_candidate_count": int(len(excluded_df)),
        "unique_food_count": int(selected_df["original_food_name"].nunique()),
        "front_image_count": int((selected_df["view_type"] == "front").sum()),
        "side_image_count": int((selected_df["view_type"] == "side").sum()),
        "foods_with_front_and_side": foods_with_both_views,
        "foods_with_only_one_view": foods_with_one_view,
        "bbox_40_70_selected_count": bbox_match_count,
        "bbox_40_70_selected_ratio": (
            float(bbox_match_count / selected_count) if selected_count > 0 else 0.0
        ),
        "average_center_score": float(selected_df["center_score"].fillna(0).mean()),
        "average_blur_score": float(selected_df["blur_score"].fillna(0).mean()),
        "average_resolution_pixels": float(
            selected_df["resolution_pixels"].fillna(0).mean()
        ),
        "output_parquet": str(OUTPUT_PATH),
        "output_csv": str(OUTPUT_CSV),
        "excluded_csv": str(OUTPUT_EXCLUDED),
    }


# ============================================================
# Main
# ============================================================


def main() -> None:
    if not INPUT_PATH.exists():
        raise FileNotFoundError(
            "1단계 결과 파일이 없습니다.\n"
            f"확인 경로: {INPUT_PATH}\n"
            "먼저 10_prepare_diverse_candidates.py를 실행하세요."
        )

    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    print(f"[INFO] Loading candidates: {INPUT_PATH}")

    candidate_df = pd.read_parquet(INPUT_PATH)

    print(f"[INFO] Candidate rows: " f"{len(candidate_df):,}")

    selected_df, excluded_df = select_representatives(
        candidate_df,
        include_unknown_view=False,
    )

    # Parquet 저장
    selected_df.to_parquet(
        OUTPUT_PATH,
        index=False,
    )

    # Excel/검수용 CSV 저장
    selected_df.to_csv(
        OUTPUT_CSV,
        index=False,
        encoding="utf-8-sig",
    )

    excluded_df.to_csv(
        OUTPUT_EXCLUDED,
        index=False,
        encoding="utf-8-sig",
    )

    summary = build_summary(
        input_df=candidate_df,
        selected_df=selected_df,
        excluded_df=excluded_df,
    )

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

    print("\n[OK] Representative selection completed")
    print(f"[OK] Selected: {OUTPUT_PATH}")
    print(f"[OK] CSV: {OUTPUT_CSV}")
    print(f"[OK] Excluded: {OUTPUT_EXCLUDED}")
    print(f"[OK] Summary: {OUTPUT_SUMMARY}")
    print()
    print(
        json.dumps(
            summary,
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
