from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import faiss
import numpy as np
import pandas as pd

# ============================================================
# Path configuration
# ============================================================

PROJECT_ROOT = Path(__file__).resolve().parents[1]

INPUT_EMBEDDINGS_PATH = (
    PROJECT_ROOT
    / "data"
    / "embeddings"
    / "diverse_sampling"
    / "diverse_image_embeddings.npy"
)

INPUT_METADATA_PATH = (
    PROJECT_ROOT
    / "data"
    / "embeddings"
    / "diverse_sampling"
    / "diverse_embedding_metadata.parquet"
)

OUTPUT_DIR = PROJECT_ROOT / "data" / "embeddings" / "diverse_sampling"

OUTPUT_INDEX_PATH = OUTPUT_DIR / "diverse_faiss.index"
OUTPUT_MAPPING_PATH = OUTPUT_DIR / "diverse_faiss_mapping.csv"
OUTPUT_MAPPING_PARQUET_PATH = OUTPUT_DIR / "diverse_faiss_mapping.parquet"
OUTPUT_SUMMARY_PATH = OUTPUT_DIR / "diverse_faiss_summary.json"


# ============================================================
# Utility
# ============================================================


def validate_input_files() -> None:
    required_files = [
        INPUT_EMBEDDINGS_PATH,
        INPUT_METADATA_PATH,
    ]

    missing_files = [str(path) for path in required_files if not path.exists()]

    if missing_files:
        raise FileNotFoundError(
            "필수 입력 파일이 없습니다.\n" + "\n".join(missing_files)
        )


def load_embeddings() -> np.ndarray:
    embeddings = np.load(INPUT_EMBEDDINGS_PATH).astype(np.float32)

    if embeddings.ndim != 2:
        raise ValueError(f"임베딩 배열은 2차원이어야 합니다: {embeddings.shape}")

    if len(embeddings) == 0:
        raise ValueError("임베딩 배열이 비어 있습니다.")

    if not np.isfinite(embeddings).all():
        raise ValueError("임베딩에 NaN 또는 무한대 값이 포함되어 있습니다.")

    return embeddings


def load_metadata(
    embedding_count: int,
) -> pd.DataFrame:
    metadata = pd.read_parquet(INPUT_METADATA_PATH).reset_index(drop=True)

    if len(metadata) != embedding_count:
        raise ValueError(
            "메타데이터 행 수와 임베딩 수가 일치하지 않습니다.\n"
            f"metadata rows: {len(metadata):,}\n"
            f"embedding rows: {embedding_count:,}"
        )

    return metadata


def build_mapping(
    metadata: pd.DataFrame,
) -> pd.DataFrame:
    mapping = metadata.copy().reset_index(drop=True)

    mapping.insert(
        0,
        "faiss_index_id",
        np.arange(
            len(mapping),
            dtype=np.int64,
        ),
    )

    preferred_columns = [
        "faiss_index_id",
        "diverse_embedding_id",
        "diverse_embedding_key",
        "embedding_id",
        "embedding_array_index",
        "representative_id",
        "source_row_index",
        "image_path",
        "relative_image_path",
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
        "resolution_score",
        "quality_score",
        "representative_score",
        "caption",
        "prompt_keywords",
        "text_for_embedding",
        "embedding_match_method",
    ]

    existing_columns = [
        column for column in preferred_columns if column in mapping.columns
    ]

    remaining_columns = [
        column for column in mapping.columns if column not in existing_columns
    ]

    return mapping[existing_columns + remaining_columns]


def build_faiss_index(
    embeddings: np.ndarray,
) -> tuple[faiss.Index, np.ndarray]:
    normalized_embeddings = np.ascontiguousarray(
        embeddings.copy(),
        dtype=np.float32,
    )

    faiss.normalize_L2(normalized_embeddings)

    dimension = normalized_embeddings.shape[1]

    index = faiss.IndexFlatIP(dimension)

    index.add(normalized_embeddings)

    if index.ntotal != len(normalized_embeddings):
        raise RuntimeError("FAISS 인덱스의 벡터 수가 임베딩 수와 일치하지 않습니다.")

    return index, normalized_embeddings


def run_self_search(
    index: faiss.Index,
    normalized_embeddings: np.ndarray,
    top_k: int = 5,
) -> dict[str, Any]:
    query_count = min(
        20,
        len(normalized_embeddings),
    )

    distances, indices = index.search(
        normalized_embeddings[:query_count],
        min(top_k, index.ntotal),
    )

    self_match_count = 0

    for query_index in range(query_count):
        if len(indices[query_index]) == 0:
            continue

        if int(indices[query_index][0]) == query_index:
            self_match_count += 1

    top1_scores = (
        distances[:, 0] if distances.shape[1] > 0 else np.array([], dtype=np.float32)
    )

    return {
        "self_search_query_count": int(query_count),
        "self_match_at_1_count": int(self_match_count),
        "self_match_at_1_rate": (
            float(self_match_count / query_count) if query_count > 0 else 0.0
        ),
        "average_top1_score": (
            float(top1_scores.mean()) if len(top1_scores) > 0 else 0.0
        ),
        "minimum_top1_score": (
            float(top1_scores.min()) if len(top1_scores) > 0 else 0.0
        ),
        "maximum_top1_score": (
            float(top1_scores.max()) if len(top1_scores) > 0 else 0.0
        ),
    }


def build_summary(
    embeddings: np.ndarray,
    index: faiss.Index,
    mapping: pd.DataFrame,
    self_search_result: dict[str, Any],
) -> dict[str, Any]:
    summary = {
        "index_type": type(index).__name__,
        "similarity_metric": "inner_product_on_l2_normalized_vectors",
        "embedding_shape": [int(value) for value in embeddings.shape],
        "embedding_dimension": int(embeddings.shape[1]),
        "index_total": int(index.ntotal),
        "mapping_count": int(len(mapping)),
        "unique_food_count": (
            int(mapping["original_food_name"].nunique())
            if "original_food_name" in mapping.columns
            else 0
        ),
        "view_type_distribution": (
            {
                str(key): int(value)
                for key, value in (
                    mapping["view_type"].value_counts(dropna=False).to_dict().items()
                )
            }
            if "view_type" in mapping.columns
            else {}
        ),
        "bbox_40_70_count": (
            int(mapping["bbox_40_70_match"].fillna(False).sum())
            if "bbox_40_70_match" in mapping.columns
            else 0
        ),
        "output_index": str(OUTPUT_INDEX_PATH),
        "output_mapping_csv": str(OUTPUT_MAPPING_PATH),
        "output_mapping_parquet": str(OUTPUT_MAPPING_PARQUET_PATH),
        **self_search_result,
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

    print(f"[INFO] Loading embeddings: " f"{INPUT_EMBEDDINGS_PATH}")

    embeddings = load_embeddings()

    print(f"[INFO] Embedding shape: " f"{embeddings.shape}")

    print(f"[INFO] Loading metadata: " f"{INPUT_METADATA_PATH}")

    metadata = load_metadata(embedding_count=len(embeddings))

    mapping = build_mapping(metadata)

    print("[INFO] Building FAISS IndexFlatIP...")

    index, normalized_embeddings = build_faiss_index(embeddings)

    faiss.write_index(
        index,
        str(OUTPUT_INDEX_PATH),
    )

    mapping.to_csv(
        OUTPUT_MAPPING_PATH,
        index=False,
        encoding="utf-8-sig",
    )

    mapping.to_parquet(
        OUTPUT_MAPPING_PARQUET_PATH,
        index=False,
    )

    self_search_result = run_self_search(
        index=index,
        normalized_embeddings=normalized_embeddings,
        top_k=5,
    )

    summary = build_summary(
        embeddings=embeddings,
        index=index,
        mapping=mapping,
        self_search_result=self_search_result,
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

    print("\n[OK] Diverse FAISS index generated")
    print(f"[OK] Index: " f"{OUTPUT_INDEX_PATH}")
    print(f"[OK] Mapping CSV: " f"{OUTPUT_MAPPING_PATH}")
    print(f"[OK] Mapping Parquet: " f"{OUTPUT_MAPPING_PARQUET_PATH}")
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
