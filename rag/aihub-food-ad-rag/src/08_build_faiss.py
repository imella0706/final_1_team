from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, Tuple

import faiss
import numpy as np
import pandas as pd
import yaml


def load_pipeline_config(config_path: str | Path) -> Dict[str, Any]:
    config_file = Path(config_path)

    if not config_file.exists():
        raise FileNotFoundError(f"Config file not found: {config_file}")

    with config_file.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def ensure_parent_dir(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def save_json(data: Dict[str, Any], path: Path) -> None:
    ensure_parent_dir(path)

    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def save_csv(df: pd.DataFrame, path: Path) -> None:
    ensure_parent_dir(path)
    df.to_csv(path, index=False, encoding="utf-8-sig")


def load_embeddings(embedding_path: Path) -> np.ndarray:
    if not embedding_path.exists():
        raise FileNotFoundError(f"Embedding file not found: {embedding_path}")

    embeddings = np.load(embedding_path)

    if embeddings.ndim != 2:
        raise ValueError(
            f"Embeddings must be 2D array. Current shape: {embeddings.shape}"
        )

    if embeddings.shape[0] == 0:
        raise ValueError("Embeddings are empty.")

    embeddings = embeddings.astype(np.float32)

    return embeddings


def normalize_embeddings(embeddings: np.ndarray) -> np.ndarray:
    """
    cosine similarity 검색을 위해 L2 normalize한다.

    CLIP 단계에서 이미 normalize했더라도
    FAISS 구축 직전에 한 번 더 보정한다.
    """
    norms = np.linalg.norm(embeddings, axis=1, keepdims=True)

    # 0 vector 방지
    norms[norms == 0] = 1.0

    normalized = embeddings / norms
    return normalized.astype(np.float32)


def build_faiss_index(
    embeddings: np.ndarray,
    index_type: str = "IndexFlatIP",
    normalize: bool = True,
) -> faiss.Index:
    """
    FAISS 인덱스를 생성한다.

    IndexFlatIP:
    - Inner Product 기반
    - normalize된 벡터에서는 cosine similarity와 동일하게 동작
    - 데이터가 1만~수십만 건 수준일 때 실무적으로 간단하고 안정적

    IndexFlatL2:
    - L2 거리 기반
    """
    if normalize:
        embeddings = normalize_embeddings(embeddings)

    dimension = embeddings.shape[1]

    if index_type == "IndexFlatIP":
        index = faiss.IndexFlatIP(dimension)
    elif index_type == "IndexFlatL2":
        index = faiss.IndexFlatL2(dimension)
    else:
        raise ValueError(
            f"Unsupported index_type: {index_type}. "
            "Supported: IndexFlatIP, IndexFlatL2"
        )

    index.add(embeddings)

    return index


def validate_metadata_and_embeddings(
    embeddings: np.ndarray,
    metadata_df: pd.DataFrame,
) -> None:
    if len(metadata_df) != embeddings.shape[0]:
        raise ValueError(
            "Metadata row count and embedding count mismatch. "
            f"metadata={len(metadata_df)}, embeddings={embeddings.shape[0]}"
        )

    required_cols = [
        "embedding_id",
        "image_path",
        "original_food_name",
        "business_category",
        "product_group",
    ]

    missing_cols = [col for col in required_cols if col not in metadata_df.columns]

    if missing_cols:
        raise ValueError(f"Metadata missing required columns: {missing_cols}")


def build_mapping_df(metadata_df: pd.DataFrame) -> pd.DataFrame:
    """
    FAISS index row와 메타데이터를 연결하는 mapping 파일 생성.

    faiss_index_id:
    - FAISS 검색 결과에서 나오는 row id
    - embedding_metadata.parquet의 행 순서와 동일해야 함
    """
    mapping_df = metadata_df.reset_index(drop=True).copy()

    mapping_df.insert(0, "faiss_index_id", range(len(mapping_df)))

    selected_cols = [
        "faiss_index_id",
        "embedding_id",
        "source_row_index",
        "image_path",
        "original_food_name",
        "product_name",
        "food_code",
        "business_category",
        "product_group",
        "caption",
        "prompt_keywords",
        "text_for_embedding",
    ]

    existing_cols = [col for col in selected_cols if col in mapping_df.columns]

    return mapping_df[existing_cols]


def test_faiss_search(
    index: faiss.Index,
    embeddings: np.ndarray,
    top_k: int = 5,
) -> Tuple[np.ndarray, np.ndarray]:
    """
    첫 번째 임베딩으로 간단한 검색 테스트를 수행한다.
    """
    if embeddings.shape[0] == 0:
        raise ValueError("Embeddings are empty.")

    query = embeddings[:1].astype(np.float32)

    if isinstance(index, faiss.IndexFlatIP):
        query = normalize_embeddings(query)

    scores, indices = index.search(query, top_k)

    return scores, indices


def build_summary(
    embeddings: np.ndarray,
    index: faiss.Index,
    index_type: str,
    normalize: bool,
    metadata_df: pd.DataFrame,
    faiss_output: Path,
    mapping_output: Path,
    test_scores: np.ndarray,
    test_indices: np.ndarray,
) -> Dict[str, Any]:
    summary = {
        "embedding_count": int(embeddings.shape[0]),
        "embedding_dimension": int(embeddings.shape[1]),
        "metadata_count": int(len(metadata_df)),
        "faiss_index_total": int(index.ntotal),
        "index_type": index_type,
        "normalize_embeddings": bool(normalize),
        "faiss_output": str(faiss_output),
        "mapping_output": str(mapping_output),
        "test_search_indices": test_indices.tolist(),
        "test_search_scores": test_scores.tolist(),
    }

    if "business_category" in metadata_df.columns:
        summary["business_category_count"] = (
            metadata_df["business_category"].value_counts().to_dict()
        )

    if "product_group" in metadata_df.columns:
        summary["product_group_count"] = (
            metadata_df["product_group"].value_counts().to_dict()
        )

    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build FAISS index from CLIP image embeddings."
    )

    parser.add_argument(
        "--config",
        type=str,
        default="configs/pipeline_config.yaml",
        help="Pipeline config path.",
    )
    parser.add_argument(
        "--embeddings",
        type=str,
        default="data/embeddings/image_embeddings.npy",
        help="Input image embeddings npy path.",
    )
    parser.add_argument(
        "--metadata",
        type=str,
        default="data/embeddings/embedding_metadata.parquet",
        help="Embedding metadata parquet path.",
    )
    parser.add_argument(
        "--faiss-output",
        type=str,
        default="data/embeddings/faiss.index",
        help="Output FAISS index path.",
    )
    parser.add_argument(
        "--mapping-output",
        type=str,
        default="data/embeddings/faiss_mapping.csv",
        help="Output FAISS mapping CSV path.",
    )
    parser.add_argument(
        "--report-dir",
        type=str,
        default="outputs/reports/faiss",
        help="FAISS report directory.",
    )
    parser.add_argument(
        "--index-type",
        type=str,
        default=None,
        choices=["IndexFlatIP", "IndexFlatL2"],
        help="FAISS index type.",
    )
    parser.add_argument(
        "--no-normalize",
        action="store_true",
        help="Do not normalize embeddings before building index.",
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=5,
        help="Top K for test search.",
    )

    return parser.parse_args()


def main() -> None:
    args = parse_args()

    config = load_pipeline_config(args.config)
    faiss_config = config.get("faiss", {})

    embeddings_path = Path(args.embeddings)
    metadata_path = Path(args.metadata)
    faiss_output = Path(args.faiss_output)
    mapping_output = Path(args.mapping_output)
    report_dir = Path(args.report_dir)

    index_type = args.index_type or faiss_config.get("index_type", "IndexFlatIP")
    normalize = not args.no_normalize
    normalize = (
        bool(faiss_config.get("normalize_embeddings", normalize))
        if not args.no_normalize
        else False
    )

    print("[INFO] AIHub Food Ad RAG - Build FAISS Index")
    print(f"[INFO] embeddings_path : {embeddings_path}")
    print(f"[INFO] metadata_path   : {metadata_path}")
    print(f"[INFO] faiss_output    : {faiss_output}")
    print(f"[INFO] mapping_output  : {mapping_output}")
    print(f"[INFO] report_dir      : {report_dir}")
    print(f"[INFO] index_type      : {index_type}")
    print(f"[INFO] normalize       : {normalize}")

    if not metadata_path.exists():
        raise FileNotFoundError(f"Embedding metadata not found: {metadata_path}")

    embeddings = load_embeddings(embeddings_path)
    metadata_df = pd.read_parquet(metadata_path)

    validate_metadata_and_embeddings(
        embeddings=embeddings,
        metadata_df=metadata_df,
    )

    embeddings_for_index = (
        normalize_embeddings(embeddings) if normalize else embeddings.astype(np.float32)
    )

    index = build_faiss_index(
        embeddings=embeddings_for_index,
        index_type=index_type,
        normalize=False,
    )

    ensure_parent_dir(faiss_output)
    faiss.write_index(index, str(faiss_output))

    mapping_df = build_mapping_df(metadata_df)
    save_csv(mapping_df, mapping_output)

    report_dir.mkdir(parents=True, exist_ok=True)

    top_k = min(args.top_k, embeddings_for_index.shape[0])
    test_scores, test_indices = test_faiss_search(
        index=index,
        embeddings=embeddings_for_index,
        top_k=top_k,
    )

    summary = build_summary(
        embeddings=embeddings_for_index,
        index=index,
        index_type=index_type,
        normalize=normalize,
        metadata_df=metadata_df,
        faiss_output=faiss_output,
        mapping_output=mapping_output,
        test_scores=test_scores,
        test_indices=test_indices,
    )

    save_json(summary, report_dir / "faiss_build_summary.json")
    save_csv(mapping_df.head(50), report_dir / "faiss_mapping_sample.csv")

    print("[DONE] FAISS index build completed.")
    print(f"[DONE] faiss index : {faiss_output}")
    print(f"[DONE] mapping     : {mapping_output}")
    print(f"[DONE] summary     : {report_dir / 'faiss_build_summary.json'}")
    print("[SUMMARY]")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
