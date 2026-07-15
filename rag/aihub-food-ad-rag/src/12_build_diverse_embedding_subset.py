from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

# ============================================================
# Path configuration
# ============================================================

PROJECT_ROOT = Path(__file__).resolve().parents[1]

SELECTED_METADATA_PATH = (
    PROJECT_ROOT
    / "data"
    / "metadata"
    / "diverse_sampling"
    / "selected_representatives.parquet"
)

EMBEDDING_METADATA_PATH = (
    PROJECT_ROOT / "data" / "embeddings" / "embedding_metadata.parquet"
)

FULL_EMBEDDINGS_PATH = PROJECT_ROOT / "data" / "embeddings" / "image_embeddings.npy"

OUTPUT_DIR = PROJECT_ROOT / "data" / "embeddings" / "diverse_sampling"

OUTPUT_EMBEDDINGS_PATH = OUTPUT_DIR / "diverse_image_embeddings.npy"

OUTPUT_METADATA_PATH = OUTPUT_DIR / "diverse_embedding_metadata.parquet"

OUTPUT_METADATA_CSV_PATH = OUTPUT_DIR / "diverse_embedding_metadata.csv"

OUTPUT_UNMATCHED_PATH = OUTPUT_DIR / "unmatched_representatives.csv"

OUTPUT_DUPLICATES_PATH = OUTPUT_DIR / "duplicate_embedding_matches.csv"

OUTPUT_SUMMARY_PATH = OUTPUT_DIR / "diverse_embedding_summary.json"


# ============================================================
# Utility functions
# ============================================================


def normalize_path(value: Any) -> str:
    """
    Windows와 Linux/Colab 경로 차이를 줄이기 위해
    이미지 경로를 비교 가능한 문자열로 정규화한다.

    예:
    C:\\aihub-food-ad-rag\\data\\raw\\images\\VS1\\...
    ->
    data/raw/images/vs1/...
    """
    if value is None:
        return ""

    text = str(value).strip()

    if not text:
        return ""

    text = text.replace("\\", "/")
    text = os.path.normpath(text).replace("\\", "/")
    text = text.lower()

    # 프로젝트 경로가 절대경로로 저장된 경우 상대경로 부분만 사용
    markers = [
        "data/raw/images/",
        "data/final_db/",
    ]

    for marker in markers:
        if marker in text:
            return marker + text.split(marker, 1)[1]

    # 드라이브 문자 및 중복 슬래시 정리
    while "//" in text:
        text = text.replace("//", "/")

    return text


def file_name_key(value: Any) -> str:
    """
    경로 전체 매칭이 실패한 경우를 위한 파일명 기반 보조 키.
    """
    normalized = normalize_path(value)

    if not normalized:
        return ""

    return Path(normalized).name.lower()


def validate_input_files() -> None:
    """
    필수 입력 파일 존재 여부를 확인한다.
    """
    required_files = [
        SELECTED_METADATA_PATH,
        EMBEDDING_METADATA_PATH,
        FULL_EMBEDDINGS_PATH,
    ]

    missing_files = [str(path) for path in required_files if not path.exists()]

    if missing_files:
        missing_text = "\n".join(missing_files)

        raise FileNotFoundError("필수 입력 파일이 없습니다.\n" f"{missing_text}")


def prepare_embedding_metadata(
    embedding_metadata: pd.DataFrame,
    embeddings: np.ndarray,
) -> pd.DataFrame:
    """
    임베딩 메타데이터에 실제 NumPy 배열 위치를 추가한다.

    embedding_id가 배열 위치와 같다고 가정하지 않고,
    metadata의 행 순서를 embedding_array_index로 사용한다.
    """
    result = embedding_metadata.copy().reset_index(drop=True)

    if len(result) != len(embeddings):
        raise ValueError(
            "embedding_metadata 행 수와 embeddings 행 수가 다릅니다.\n"
            f"metadata rows: {len(result):,}\n"
            f"embedding rows: {len(embeddings):,}"
        )

    if "image_path" not in result.columns:
        raise KeyError("embedding_metadata.parquet에 image_path 컬럼이 없습니다.")

    result["embedding_array_index"] = np.arange(
        len(result),
        dtype=np.int64,
    )

    result["normalized_image_path"] = result["image_path"].apply(normalize_path)

    result["image_file_name_key"] = result["image_path"].apply(file_name_key)

    return result


def prepare_selected_metadata(
    selected_metadata: pd.DataFrame,
) -> pd.DataFrame:
    """
    대표 이미지 메타데이터에 매칭 키를 추가한다.
    """
    result = selected_metadata.copy().reset_index(drop=True)

    if "image_path" not in result.columns:
        raise KeyError(
            "selected_representatives.parquet에 " "image_path 컬럼이 없습니다."
        )

    result["selected_row_index"] = np.arange(
        len(result),
        dtype=np.int64,
    )

    result["normalized_image_path"] = result["image_path"].apply(normalize_path)

    result["image_file_name_key"] = result["image_path"].apply(file_name_key)

    return result


def find_duplicate_embedding_paths(
    embedding_metadata: pd.DataFrame,
) -> pd.DataFrame:
    """
    하나의 정규화 경로가 여러 임베딩 행에 연결되는 경우를 찾는다.
    """
    duplicated_mask = embedding_metadata.duplicated(
        subset=["normalized_image_path"],
        keep=False,
    )

    duplicates = embedding_metadata.loc[
        duplicated_mask & embedding_metadata["normalized_image_path"].ne("")
    ].copy()

    return duplicates.sort_values(
        [
            "normalized_image_path",
            "embedding_array_index",
        ]
    )


def merge_by_full_path(
    selected_metadata: pd.DataFrame,
    embedding_metadata: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    1차적으로 전체 정규화 경로를 사용하여 매칭한다.
    """
    embedding_lookup_columns = [
        "normalized_image_path",
        "embedding_array_index",
        "embedding_id",
        "source_row_index",
    ]

    available_lookup_columns = [
        column
        for column in embedding_lookup_columns
        if column in embedding_metadata.columns
    ]

    embedding_lookup = embedding_metadata[available_lookup_columns].drop_duplicates(
        subset=["normalized_image_path"],
        keep="first",
    )

    merged = selected_metadata.merge(
        embedding_lookup,
        on="normalized_image_path",
        how="left",
        suffixes=("", "_embedding"),
    )

    matched = merged.loc[merged["embedding_array_index"].notna()].copy()

    unmatched = merged.loc[merged["embedding_array_index"].isna()].copy()

    matched["embedding_match_method"] = "normalized_full_path"

    return matched, unmatched


def merge_unmatched_by_file_name(
    unmatched_metadata: pd.DataFrame,
    embedding_metadata: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    전체 경로 매칭에 실패한 경우,
    파일명이 임베딩 메타데이터에서 유일할 때만 보조 매칭한다.

    동일 파일명이 여러 경로에 존재하면 잘못 연결될 수 있으므로
    유일한 파일명만 사용한다.
    """
    if unmatched_metadata.empty:
        return unmatched_metadata.copy(), unmatched_metadata.copy()

    file_name_counts = embedding_metadata["image_file_name_key"].value_counts()

    unique_file_names = set(file_name_counts[file_name_counts == 1].index.tolist())

    unique_embedding_metadata = embedding_metadata.loc[
        embedding_metadata["image_file_name_key"].isin(unique_file_names)
    ].copy()

    lookup_columns = [
        "image_file_name_key",
        "embedding_array_index",
        "embedding_id",
        "source_row_index",
    ]

    available_lookup_columns = [
        column
        for column in lookup_columns
        if column in unique_embedding_metadata.columns
    ]

    file_name_lookup = unique_embedding_metadata[
        available_lookup_columns
    ].drop_duplicates(
        subset=["image_file_name_key"],
        keep="first",
    )

    # 기존 매칭 실패 컬럼 제거 후 다시 병합
    columns_to_remove = [
        "embedding_array_index",
        "embedding_id",
        "source_row_index",
    ]

    clean_unmatched = unmatched_metadata.drop(
        columns=[
            column
            for column in columns_to_remove
            if column in unmatched_metadata.columns
        ],
        errors="ignore",
    )

    fallback_merged = clean_unmatched.merge(
        file_name_lookup,
        on="image_file_name_key",
        how="left",
    )

    fallback_matched = fallback_merged.loc[
        fallback_merged["embedding_array_index"].notna()
    ].copy()

    still_unmatched = fallback_merged.loc[
        fallback_merged["embedding_array_index"].isna()
    ].copy()

    fallback_matched["embedding_match_method"] = "unique_file_name"

    return fallback_matched, still_unmatched


def build_output_metadata(
    matched_metadata: pd.DataFrame,
) -> pd.DataFrame:
    """
    두 번째 DB 임베딩 메타데이터를 정리한다.
    """
    result = matched_metadata.copy()

    result["embedding_array_index"] = pd.to_numeric(
        result["embedding_array_index"],
        errors="raise",
    ).astype(np.int64)

    # 원래 대표 이미지 선정 순서 유지
    result = result.sort_values("selected_row_index").reset_index(drop=True)

    # 부분 임베딩 배열 내 새 위치
    result.insert(
        0,
        "diverse_embedding_id",
        np.arange(
            len(result),
            dtype=np.int64,
        ),
    )

    result.insert(
        1,
        "diverse_embedding_key",
        [f"DIV_EMB_{index:06d}" for index in range(len(result))],
    )

    return result


def build_summary(
    selected_count: int,
    output_metadata: pd.DataFrame,
    unmatched_metadata: pd.DataFrame,
    full_embeddings: np.ndarray,
    subset_embeddings: np.ndarray,
    duplicate_count: int,
) -> dict[str, Any]:
    """
    임베딩 추출 결과 요약 정보를 생성한다.
    """
    match_method_distribution = {
        str(key): int(value)
        for key, value in (
            output_metadata["embedding_match_method"]
            .value_counts(dropna=False)
            .to_dict()
            .items()
        )
    }

    summary = {
        "selected_representative_count": int(selected_count),
        "matched_embedding_count": int(len(output_metadata)),
        "unmatched_representative_count": int(len(unmatched_metadata)),
        "embedding_match_rate": (
            float(len(output_metadata) / selected_count) if selected_count > 0 else 0.0
        ),
        "duplicate_embedding_path_count": int(duplicate_count),
        "full_embedding_shape": [int(value) for value in full_embeddings.shape],
        "diverse_embedding_shape": [int(value) for value in subset_embeddings.shape],
        "embedding_dtype": str(subset_embeddings.dtype),
        "unique_food_count": int(output_metadata["original_food_name"].nunique()),
        "view_type_distribution": {
            str(key): int(value)
            for key, value in (
                output_metadata["view_type"]
                .value_counts(dropna=False)
                .to_dict()
                .items()
            )
        },
        "match_method_distribution": (match_method_distribution),
        "output_embeddings": str(OUTPUT_EMBEDDINGS_PATH),
        "output_metadata": str(OUTPUT_METADATA_PATH),
        "unmatched_output": str(OUTPUT_UNMATCHED_PATH),
    }

    return summary


# ============================================================
# Main
# ============================================================


def main() -> None:
    validate_input_files()

    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    print(f"[INFO] Loading representatives: " f"{SELECTED_METADATA_PATH}")

    selected_metadata = pd.read_parquet(SELECTED_METADATA_PATH)

    print(f"[INFO] Selected representative rows: " f"{len(selected_metadata):,}")

    print(f"[INFO] Loading embedding metadata: " f"{EMBEDDING_METADATA_PATH}")

    embedding_metadata = pd.read_parquet(EMBEDDING_METADATA_PATH)

    print(f"[INFO] Loading embeddings: " f"{FULL_EMBEDDINGS_PATH}")

    full_embeddings = np.load(
        FULL_EMBEDDINGS_PATH,
        mmap_mode="r",
    )

    print(f"[INFO] Full embedding shape: " f"{full_embeddings.shape}")

    prepared_selected = prepare_selected_metadata(selected_metadata)

    prepared_embedding_metadata = prepare_embedding_metadata(
        embedding_metadata,
        full_embeddings,
    )

    duplicate_paths = find_duplicate_embedding_paths(prepared_embedding_metadata)

    duplicate_paths.to_csv(
        OUTPUT_DUPLICATES_PATH,
        index=False,
        encoding="utf-8-sig",
    )

    # 1차: 전체 경로 매칭
    full_path_matched, unmatched = merge_by_full_path(
        prepared_selected,
        prepared_embedding_metadata,
    )

    # 2차: 파일명이 유일한 경우에만 파일명 매칭
    file_name_matched, still_unmatched = merge_unmatched_by_file_name(
        unmatched,
        prepared_embedding_metadata,
    )

    matched_metadata = pd.concat(
        [
            full_path_matched,
            file_name_matched,
        ],
        ignore_index=True,
    )

    output_metadata = build_output_metadata(matched_metadata)

    # 중복 임베딩 배열 위치가 있는지 확인
    duplicated_embedding_indices = output_metadata["embedding_array_index"].duplicated(
        keep=False
    )

    if duplicated_embedding_indices.any():
        duplicated_rows = output_metadata.loc[
            duplicated_embedding_indices,
            [
                "original_food_name",
                "view_type",
                "image_path",
                "embedding_array_index",
            ],
        ]

        raise ValueError(
            "여러 대표 이미지가 동일한 임베딩 행에 연결되었습니다.\n"
            f"{duplicated_rows.head(20).to_string(index=False)}"
        )

    embedding_indices = output_metadata["embedding_array_index"].to_numpy(
        dtype=np.int64
    )

    # mmap 상태의 원본에서 필요한 행만 메모리로 복사
    subset_embeddings = np.asarray(
        full_embeddings[embedding_indices],
        dtype=np.float32,
    )

    if len(subset_embeddings) != len(output_metadata):
        raise RuntimeError("부분 임베딩 수와 메타데이터 행 수가 일치하지 않습니다.")

    # 새 임베딩 배열 저장
    np.save(
        OUTPUT_EMBEDDINGS_PATH,
        subset_embeddings,
    )

    # 메타데이터 저장
    output_metadata.to_parquet(
        OUTPUT_METADATA_PATH,
        index=False,
    )

    output_metadata.to_csv(
        OUTPUT_METADATA_CSV_PATH,
        index=False,
        encoding="utf-8-sig",
    )

    # 미매칭 대표 이미지 저장
    still_unmatched.to_csv(
        OUTPUT_UNMATCHED_PATH,
        index=False,
        encoding="utf-8-sig",
    )

    summary = build_summary(
        selected_count=len(selected_metadata),
        output_metadata=output_metadata,
        unmatched_metadata=still_unmatched,
        full_embeddings=full_embeddings,
        subset_embeddings=subset_embeddings,
        duplicate_count=len(duplicate_paths),
    )

    with OUTPUT_SUMMARY_PATH.open(
        "w",
        encoding="utf-8",
    ) as file:
        json.dump(
            summary,
            file,
            ensure_ascii=False,
            indent=2,
        )

    print("\n[OK] Diverse embedding subset generated")
    print(f"[OK] Embeddings: " f"{OUTPUT_EMBEDDINGS_PATH}")
    print(f"[OK] Metadata: " f"{OUTPUT_METADATA_PATH}")
    print(f"[OK] Metadata CSV: " f"{OUTPUT_METADATA_CSV_PATH}")
    print(f"[OK] Unmatched: " f"{OUTPUT_UNMATCHED_PATH}")
    print(f"[OK] Summary: " f"{OUTPUT_SUMMARY_PATH}")
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
