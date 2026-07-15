from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path, PurePath
from typing import Any

import faiss
import numpy as np
import pandas as pd
from tqdm import tqdm

# ============================================================
# Project paths
# ============================================================

PROJECT_ROOT = Path(__file__).resolve().parents[1]

INPUT_METADATA_PATH = (
    PROJECT_ROOT
    / "data"
    / "embeddings"
    / "diverse_sampling"
    / "diverse_embedding_metadata.parquet"
)

INPUT_EMBEDDINGS_PATH = (
    PROJECT_ROOT
    / "data"
    / "embeddings"
    / "diverse_sampling"
    / "diverse_image_embeddings.npy"
)

INPUT_FAISS_INDEX_PATH = (
    PROJECT_ROOT / "data" / "embeddings" / "diverse_sampling" / "diverse_faiss.index"
)

INPUT_MAPPING_PATH = (
    PROJECT_ROOT
    / "data"
    / "embeddings"
    / "diverse_sampling"
    / "diverse_faiss_mapping.parquet"
)

DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data" / "final_db" / "5gb_v2_diverse"


# ============================================================
# Utilities
# ============================================================


def safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or pd.isna(value):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def normalize_path(path_value: Any) -> Path:
    """
    Windows 절대경로, 상대경로 모두 처리한다.
    """
    if path_value is None:
        return Path()

    raw_path = str(path_value).strip()

    if not raw_path:
        return Path()

    path = Path(raw_path)

    if path.is_absolute():
        return path

    return PROJECT_ROOT / path


def serialize_value(value: Any) -> Any:
    """
    PyArrow가 직접 저장하지 못하는 Path 계열 객체를 문자열로 변환한다.
    list, tuple, dict 내부에 포함된 Path 객체도 재귀적으로 처리한다.
    """
    if isinstance(value, PurePath):
        return str(value)

    if isinstance(value, dict):
        return {str(key): serialize_value(item) for key, item in value.items()}

    if isinstance(value, tuple):
        return [serialize_value(item) for item in value]

    if isinstance(value, list):
        return [serialize_value(item) for item in value]

    return value


def make_dataframe_serializable(dataframe: pd.DataFrame) -> pd.DataFrame:
    """
    DataFrame의 object 컬럼에 포함된 WindowsPath/PosixPath를 문자열로 변환한다.
    원본 DataFrame은 변경하지 않는다.
    """
    result = dataframe.copy()

    for column in result.columns:
        if result[column].dtype != "object":
            continue
        result[column] = result[column].map(serialize_value)

    return result


def file_size_bytes(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def bytes_to_gb(value: int) -> float:
    return value / (1024**3)


def validate_input_files() -> None:
    required_files = [
        INPUT_METADATA_PATH,
        INPUT_EMBEDDINGS_PATH,
        INPUT_FAISS_INDEX_PATH,
        INPUT_MAPPING_PATH,
    ]

    missing_files = [str(path) for path in required_files if not path.exists()]

    if missing_files:
        raise FileNotFoundError(
            "필수 입력 파일이 없습니다.\n" + "\n".join(missing_files)
        )


def clear_output_directory(
    output_dir: Path,
    overwrite: bool,
) -> None:
    """
    기존 출력 폴더 처리.
    """
    if output_dir.exists():
        if not overwrite:
            raise FileExistsError(
                f"출력 폴더가 이미 존재합니다: {output_dir}\n"
                "--overwrite 옵션을 추가하거나 기존 폴더를 백업하세요."
            )

        shutil.rmtree(output_dir)

    output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    (output_dir / "images").mkdir(
        parents=True,
        exist_ok=True,
    )


# ============================================================
# Load and validate
# ============================================================


def load_inputs() -> tuple[
    pd.DataFrame,
    np.ndarray,
    faiss.Index,
    pd.DataFrame,
]:
    metadata = pd.read_parquet(INPUT_METADATA_PATH).reset_index(drop=True)

    embeddings = np.load(INPUT_EMBEDDINGS_PATH).astype(np.float32)

    index = faiss.read_index(str(INPUT_FAISS_INDEX_PATH))

    mapping = pd.read_parquet(INPUT_MAPPING_PATH).reset_index(drop=True)

    row_counts = {
        "metadata": len(metadata),
        "embeddings": len(embeddings),
        "faiss_index": index.ntotal,
        "mapping": len(mapping),
    }

    if len(set(row_counts.values())) != 1:
        raise ValueError(
            "입력 파일 간 데이터 개수가 일치하지 않습니다.\n"
            + json.dumps(
                row_counts,
                ensure_ascii=False,
                indent=2,
            )
        )

    if embeddings.ndim != 2:
        raise ValueError(f"임베딩은 2차원 배열이어야 합니다: {embeddings.shape}")

    if len(metadata) == 0:
        raise ValueError("대표 이미지 메타데이터가 비어 있습니다.")

    if "image_path" not in metadata.columns:
        raise KeyError(
            "diverse_embedding_metadata.parquet에 " "image_path 컬럼이 없습니다."
        )

    return metadata, embeddings, index, mapping


# ============================================================
# Image selection by target size
# ============================================================


def prepare_file_information(
    metadata: pd.DataFrame,
) -> pd.DataFrame:
    """
    실제 이미지 파일 경로와 파일 크기를 확인한다.
    """
    result = metadata.copy()

    result["source_image_path"] = result["image_path"].apply(normalize_path)

    result["source_image_exists"] = result["source_image_path"].apply(
        lambda path: path.exists()
    )

    result["source_image_size_bytes"] = result["source_image_path"].apply(
        file_size_bytes
    )

    return result


def sort_for_diversity(
    metadata: pd.DataFrame,
) -> pd.DataFrame:
    """
    음식 종류 다양성을 우선하면서 정위·측면을 고르게 선택한다.

    11단계에서 이미 음식명 × 방향별 대표 이미지 1장을 선정했으므로,
    여기서는 음식 단위 Round-Robin 순서를 구성한다.

    순서:
    1차: 각 음식의 대표 이미지 1장
    2차: 같은 음식의 나머지 촬영 방향 1장
    """
    result = metadata.copy()

    view_order = {
        "front": 0,
        "side": 1,
        "unknown": 2,
    }

    result["view_sort_order"] = (
        result["view_type"].map(view_order).fillna(2).astype(int)
    )

    result = result.sort_values(
        by=[
            "original_food_name",
            "view_sort_order",
            "bbox_40_70_match",
            "center_score",
            "blur_score_normalized",
            "resolution_score",
        ],
        ascending=[
            True,
            True,
            False,
            False,
            False,
            False,
        ],
        na_position="last",
        kind="mergesort",
    )

    result["food_selection_round"] = result.groupby("original_food_name").cumcount()

    result = result.sort_values(
        by=[
            "food_selection_round",
            "business_category",
            "product_group",
            "original_food_name",
            "view_sort_order",
        ],
        ascending=True,
        na_position="last",
        kind="mergesort",
    )

    return result.reset_index(drop=True)


def select_by_target_size(
    metadata: pd.DataFrame,
    target_size_gb: float,
) -> pd.DataFrame:
    """
    목표 이미지 용량까지 대표 이미지를 선택한다.

    모든 대표 이미지의 총 용량이 목표보다 작으면
    전체 대표 이미지를 사용한다.
    """
    ordered = sort_for_diversity(metadata)

    valid = ordered.loc[
        ordered["source_image_exists"] & ordered["source_image_size_bytes"].gt(0)
    ].copy()

    target_bytes = int(target_size_gb * (1024**3))

    cumulative_sizes = valid["source_image_size_bytes"].cumsum()

    selected_mask = cumulative_sizes <= target_bytes

    selected = valid.loc[selected_mask].copy()

    # 첫 파일부터 목표 용량보다 큰 예외 방지
    if selected.empty and not valid.empty:
        selected = valid.iloc[[0]].copy()

    # 전체 대표 이미지 용량이 목표보다 작으면 모두 사용
    total_valid_size = int(valid["source_image_size_bytes"].sum())

    if total_valid_size <= target_bytes:
        selected = valid.copy()

    return selected.reset_index(drop=True)


# ============================================================
# Subset rebuilding
# ============================================================


def extract_selected_arrays(
    selected_metadata: pd.DataFrame,
    full_embeddings: np.ndarray,
    full_mapping: pd.DataFrame,
) -> tuple[np.ndarray, pd.DataFrame]:
    """
    선택한 대표 이미지에 해당하는 임베딩과 매핑을 추출한다.
    """
    if "diverse_embedding_id" not in selected_metadata.columns:
        raise KeyError("metadata에 diverse_embedding_id 컬럼이 없습니다.")

    selected_indices = (
        pd.to_numeric(
            selected_metadata["diverse_embedding_id"],
            errors="raise",
        )
        .astype(np.int64)
        .to_numpy()
    )

    if selected_indices.min() < 0:
        raise ValueError("음수 diverse_embedding_id가 존재합니다.")

    if selected_indices.max() >= len(full_embeddings):
        raise IndexError("diverse_embedding_id가 임베딩 배열 범위를 벗어났습니다.")

    subset_embeddings = np.asarray(
        full_embeddings[selected_indices],
        dtype=np.float32,
    )

    mapping_lookup = full_mapping.copy()

    if "diverse_embedding_id" not in mapping_lookup.columns:
        raise KeyError("mapping에 diverse_embedding_id 컬럼이 없습니다.")

    subset_mapping = selected_metadata[["diverse_embedding_id"]].merge(
        mapping_lookup,
        on="diverse_embedding_id",
        how="left",
        validate="one_to_one",
        suffixes=("", "_mapping"),
    )

    if len(subset_mapping) != len(selected_metadata):
        raise RuntimeError("선택 메타데이터와 매핑 개수가 일치하지 않습니다.")

    return subset_embeddings, subset_mapping


def build_subset_faiss(
    embeddings: np.ndarray,
) -> faiss.Index:
    """
    선택된 임베딩으로 최종 DB 전용 FAISS 인덱스를 재생성한다.
    """
    normalized = np.ascontiguousarray(
        embeddings.copy(),
        dtype=np.float32,
    )

    faiss.normalize_L2(normalized)

    dimension = normalized.shape[1]

    index = faiss.IndexFlatIP(dimension)

    index.add(normalized)

    return index


# ============================================================
# Output metadata
# ============================================================


def build_final_metadata(
    selected_metadata: pd.DataFrame,
) -> pd.DataFrame:
    result = selected_metadata.copy().reset_index(drop=True)

    result.insert(
        0,
        "final_image_id",
        [f"DIV_IMG_{index:06d}" for index in range(len(result))],
    )

    result.insert(
        1,
        "final_db_row_index",
        np.arange(
            len(result),
            dtype=np.int64,
        ),
    )

    result["final_image_file_name"] = [
        (f"DIV_IMG_{index:06d}" f"{Path(str(path)).suffix.lower() or '.jpg'}")
        for index, path in enumerate(result["source_image_path"])
    ]

    result["final_image_path"] = "images/" + result["final_image_file_name"]

    return result


def build_prompt_metadata(
    final_metadata: pd.DataFrame,
) -> pd.DataFrame:
    """
    광고 콘텐츠 생성 프롬프트와 검색 결과에 필요한 컬럼만 저장한다.
    """
    preferred_columns = [
        "final_image_id",
        "final_db_row_index",
        "final_image_path",
        "original_food_name",
        "product_name",
        "food_code",
        "business_category",
        "product_group",
        "view_type",
        "caption",
        "prompt_keywords",
        "caption_lighting",
        "caption_composition",
        "caption_camera_angle",
        "ad_use_case",
        "visual_style_hint",
        "text_for_embedding",
        "bbox_ratio",
        "bbox_40_70_match",
        "center_score",
        "blur_score",
        "resolution_score",
        "representative_score",
    ]

    existing_columns = [
        column for column in preferred_columns if column in final_metadata.columns
    ]

    return final_metadata[existing_columns].copy()


def build_final_mapping(
    subset_mapping: pd.DataFrame,
    final_metadata: pd.DataFrame,
) -> pd.DataFrame:
    """
    최종 FAISS ID와 이미지·메타데이터 연결.
    """
    result = subset_mapping.copy().reset_index(drop=True)

    if "faiss_index_id" in result.columns:
        result = result.drop(columns=["faiss_index_id"])

    result.insert(
        0,
        "faiss_index_id",
        np.arange(
            len(result),
            dtype=np.int64,
        ),
    )

    final_columns = final_metadata[
        [
            "final_image_id",
            "final_db_row_index",
            "final_image_path",
            "final_image_file_name",
        ]
    ].copy()

    result = pd.concat(
        [
            final_columns.reset_index(drop=True),
            result.reset_index(drop=True),
        ],
        axis=1,
    )

    return result


# ============================================================
# Image copy
# ============================================================


def copy_selected_images(
    final_metadata: pd.DataFrame,
    output_images_dir: Path,
    no_copy_images: bool,
) -> tuple[int, list[dict[str, str]]]:
    """
    선택 이미지를 최종 DB 폴더에 복사한다.
    """
    if no_copy_images:
        return 0, []

    copied_count = 0
    failures: list[dict[str, str]] = []

    records = final_metadata.to_dict(orient="records")

    for record in tqdm(
        records,
        desc="Copying images",
        total=len(records),
    ):
        source_path = Path(str(record["source_image_path"]))

        destination_path = output_images_dir / record["final_image_file_name"]

        try:
            shutil.copy2(
                source_path,
                destination_path,
            )

            copied_count += 1

        except Exception as exc:
            failures.append(
                {
                    "source_path": str(source_path),
                    "destination_path": str(destination_path),
                    "error": (f"{type(exc).__name__}: {exc}"),
                }
            )

    return copied_count, failures


# ============================================================
# Summary
# ============================================================


def build_summary(
    target_size_gb: float,
    source_metadata: pd.DataFrame,
    final_metadata: pd.DataFrame,
    embeddings: np.ndarray,
    index: faiss.Index,
    mapping: pd.DataFrame,
    copied_count: int,
    copy_failures: list[dict[str, str]],
    no_copy_images: bool,
) -> dict[str, Any]:
    selected_image_size_bytes = int(final_metadata["source_image_size_bytes"].sum())

    food_view_counts = final_metadata.groupby("original_food_name")[
        "view_type"
    ].nunique()

    bbox_selected_count = int(final_metadata["bbox_40_70_match"].fillna(False).sum())

    summary = {
        "database_name": "5gb_v2_diverse",
        "database_version": "v2_diverse",
        "sampling_policy": [
            "maximize_unique_food_types",
            "select_one_front_and_one_side_per_food",
            "prefer_bbox_ratio_0.40_to_0.70",
            "prefer_high_center_score",
            "prefer_high_blur_score",
            "prefer_high_resolution",
        ],
        "target_size_gb": float(target_size_gb),
        "actual_image_size_gb": bytes_to_gb(selected_image_size_bytes),
        "actual_image_size_bytes": (selected_image_size_bytes),
        "available_representative_count": int(len(source_metadata)),
        "final_record_count": int(len(final_metadata)),
        "unique_food_count": int(final_metadata["original_food_name"].nunique()),
        "front_image_count": int((final_metadata["view_type"] == "front").sum()),
        "side_image_count": int((final_metadata["view_type"] == "side").sum()),
        "foods_with_front_and_side": int((food_view_counts >= 2).sum()),
        "foods_with_one_view": int((food_view_counts == 1).sum()),
        "bbox_40_70_selected_count": (bbox_selected_count),
        "bbox_40_70_selected_ratio": (
            float(bbox_selected_count / len(final_metadata))
            if len(final_metadata) > 0
            else 0.0
        ),
        "average_bbox_ratio": safe_float(final_metadata["bbox_ratio"].mean()),
        "average_center_score": safe_float(final_metadata["center_score"].mean()),
        "average_blur_score": safe_float(final_metadata["blur_score"].mean()),
        "embedding_shape": [safe_int(value) for value in embeddings.shape],
        "faiss_index_type": (type(index).__name__),
        "faiss_index_total": int(index.ntotal),
        "mapping_count": int(len(mapping)),
        "images_copied": not no_copy_images,
        "copied_image_count": int(copied_count),
        "copy_failure_count": int(len(copy_failures)),
        "business_category_distribution": {
            str(key): int(value)
            for key, value in (
                final_metadata["business_category"]
                .value_counts(dropna=False)
                .to_dict()
                .items()
            )
        },
        "product_group_distribution": {
            str(key): int(value)
            for key, value in (
                final_metadata["product_group"]
                .value_counts(dropna=False)
                .to_dict()
                .items()
            )
        },
    }

    return summary


# ============================================================
# Main
# ============================================================


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "대표 이미지 샘플링 결과를 이용하여 "
            "두 번째 Food Retrieval DB를 생성합니다."
        )
    )

    parser.add_argument(
        "--target-size-gb",
        type=float,
        default=5.0,
        help="목표 이미지 용량(GB), 기본값 5.0",
    )

    parser.add_argument(
        "--output-dir",
        type=str,
        default=str(DEFAULT_OUTPUT_DIR),
        help="최종 DB 출력 폴더",
    )

    parser.add_argument(
        "--no-copy-images",
        action="store_true",
        help="검증용으로 실제 이미지는 복사하지 않음",
    )

    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="기존 출력 폴더가 있으면 삭제 후 재생성",
    )

    return parser.parse_args()


def main() -> None:
    args = parse_args()

    validate_input_files()

    output_dir = Path(args.output_dir)

    if not output_dir.is_absolute():
        output_dir = PROJECT_ROOT / output_dir

    clear_output_directory(
        output_dir=output_dir,
        overwrite=args.overwrite,
    )

    output_images_dir = output_dir / "images"

    print("[INFO] Loading diverse sampling results...")

    (
        source_metadata,
        full_embeddings,
        _source_index,
        source_mapping,
    ) = load_inputs()

    prepared_metadata = prepare_file_information(source_metadata)

    missing_image_count = int((~prepared_metadata["source_image_exists"]).sum())

    print(f"[INFO] Available representatives: " f"{len(prepared_metadata):,}")

    print(f"[INFO] Missing source images: " f"{missing_image_count:,}")

    selected_metadata = select_by_target_size(
        metadata=prepared_metadata,
        target_size_gb=args.target_size_gb,
    )

    if selected_metadata.empty:
        raise RuntimeError("최종 DB에 포함할 이미지가 없습니다.")

    subset_embeddings, subset_mapping = extract_selected_arrays(
        selected_metadata=selected_metadata,
        full_embeddings=full_embeddings,
        full_mapping=source_mapping,
    )

    # 실제 파일 복사를 위해 Path 객체를 유지하는 원본 메타데이터
    final_metadata = build_final_metadata(selected_metadata)

    # Parquet/CSV 저장용: WindowsPath/PosixPath를 문자열로 변환
    final_metadata_serializable = make_dataframe_serializable(final_metadata)

    prompt_metadata = build_prompt_metadata(final_metadata_serializable)

    final_index = build_subset_faiss(subset_embeddings)

    final_mapping = build_final_mapping(
        subset_mapping=subset_mapping,
        final_metadata=final_metadata_serializable,
    )
    final_mapping = make_dataframe_serializable(final_mapping)

    if not (
        len(final_metadata_serializable)
        == len(prompt_metadata)
        == len(subset_embeddings)
        == final_index.ntotal
        == len(final_mapping)
    ):
        raise RuntimeError(
            "최종 산출물 간 데이터 개수가 일치하지 않습니다.\n"
            f"metadata={len(final_metadata_serializable)}\n"
            f"prompt_metadata={len(prompt_metadata)}\n"
            f"embeddings={len(subset_embeddings)}\n"
            f"faiss={final_index.ntotal}\n"
            f"mapping={len(final_mapping)}"
        )

    # 직렬화 오류를 이미지 복사 전에 먼저 검증한다.
    final_metadata_serializable.to_parquet(
        output_dir / "metadata.parquet",
        index=False,
    )

    prompt_metadata.to_parquet(
        output_dir / "prompt_metadata.parquet",
        index=False,
    )

    np.save(
        output_dir / "embeddings.npy",
        subset_embeddings,
    )

    faiss.write_index(
        final_index,
        str(output_dir / "faiss.index"),
    )

    final_mapping.to_csv(
        output_dir / "mapping.csv",
        index=False,
        encoding="utf-8-sig",
    )

    # 파일 저장 검증 후 실제 이미지를 복사한다.
    copied_count, copy_failures = copy_selected_images(
        final_metadata=final_metadata,
        output_images_dir=output_images_dir,
        no_copy_images=args.no_copy_images,
    )

    if copy_failures:
        pd.DataFrame(copy_failures).to_csv(
            output_dir / "image_copy_failures.csv",
            index=False,
            encoding="utf-8-sig",
        )

    summary = build_summary(
        target_size_gb=args.target_size_gb,
        source_metadata=source_metadata,
        final_metadata=final_metadata,
        embeddings=subset_embeddings,
        index=final_index,
        mapping=final_mapping,
        copied_count=copied_count,
        copy_failures=copy_failures,
        no_copy_images=args.no_copy_images,
    )

    with (output_dir / "summary.json").open(
        "w",
        encoding="utf-8",
    ) as file:
        json.dump(
            summary,
            file,
            ensure_ascii=False,
            indent=2,
        )

    print("\n[OK] Diverse final DB generated")
    print(f"[OK] Output: {output_dir}")
    print(
        json.dumps(
            summary,
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
