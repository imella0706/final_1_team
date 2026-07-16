from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Any, Dict, List, Tuple

import faiss
import numpy as np
import pandas as pd
import yaml
from tqdm import tqdm


def load_yaml(path: str | Path) -> Dict[str, Any]:
    file_path = Path(path)

    if not file_path.exists():
        raise FileNotFoundError(f"YAML file not found: {file_path}")

    with file_path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def ensure_parent_dir(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def save_json(data: Dict[str, Any], path: Path) -> None:
    ensure_parent_dir(path)

    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def save_csv(df: pd.DataFrame, path: Path) -> None:
    ensure_parent_dir(path)
    df.to_csv(path, index=False, encoding="utf-8-sig")


def bytes_to_gb(value: float) -> float:
    return float(value) / (1024**3)


def gb_to_bytes(value: float) -> int:
    return int(float(value) * (1024**3))


def normalize_embeddings(embeddings: np.ndarray) -> np.ndarray:
    embeddings = embeddings.astype(np.float32)
    norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return (embeddings / norms).astype(np.float32)


def build_faiss_index(
    embeddings: np.ndarray, index_type: str = "IndexFlatIP"
) -> faiss.Index:
    if embeddings.ndim != 2:
        raise ValueError(f"Embeddings must be 2D. Current shape: {embeddings.shape}")

    dimension = embeddings.shape[1]

    if index_type == "IndexFlatIP":
        index = faiss.IndexFlatIP(dimension)
        embeddings = normalize_embeddings(embeddings)
    elif index_type == "IndexFlatL2":
        index = faiss.IndexFlatL2(dimension)
    else:
        raise ValueError(f"Unsupported FAISS index type: {index_type}")

    index.add(embeddings.astype(np.float32))
    return index


def load_inputs(
    metadata_path: Path,
    embedding_metadata_path: Path,
    image_embeddings_path: Path,
) -> Tuple[pd.DataFrame, pd.DataFrame, np.ndarray]:
    if not metadata_path.exists():
        raise FileNotFoundError(f"Metadata not found: {metadata_path}")

    if not embedding_metadata_path.exists():
        raise FileNotFoundError(
            f"Embedding metadata not found: {embedding_metadata_path}"
        )

    if not image_embeddings_path.exists():
        raise FileNotFoundError(f"Image embeddings not found: {image_embeddings_path}")

    metadata_df = pd.read_parquet(metadata_path)
    embedding_metadata_df = pd.read_parquet(embedding_metadata_path)
    image_embeddings = np.load(image_embeddings_path).astype(np.float32)

    if len(embedding_metadata_df) != image_embeddings.shape[0]:
        raise ValueError(
            "embedding_metadata row count and image_embeddings count mismatch. "
            f"metadata={len(embedding_metadata_df)}, embeddings={image_embeddings.shape[0]}"
        )

    return metadata_df, embedding_metadata_df, image_embeddings


def prepare_working_df(
    embedding_metadata_df: pd.DataFrame,
    image_embeddings: np.ndarray,
) -> pd.DataFrame:
    """
    final DB 선별용 DataFrame 생성.
    embedding_metadata.parquet의 행 순서와 image_embeddings.npy의 행 순서는 동일해야 한다.
    """
    df = embedding_metadata_df.reset_index(drop=True).copy()
    df["embedding_array_index"] = range(len(df))

    if "image_path" not in df.columns:
        raise ValueError("embedding_metadata must contain image_path column.")

    if "business_category" not in df.columns:
        df["business_category"] = "restaurant"

    if "product_group" not in df.columns:
        df["product_group"] = "delivery_food"

    image_sizes = []

    for image_path in df["image_path"]:
        path = Path(str(image_path))

        if path.exists():
            image_sizes.append(path.stat().st_size)
        else:
            image_sizes.append(0)

    df["final_image_size_bytes"] = image_sizes
    df["final_image_exists"] = df["final_image_size_bytes"] > 0

    df = df[df["final_image_exists"] == True].copy()

    if len(df) == 0:
        raise ValueError("No existing image files found for final DB.")

    return df


def get_target_versions(db_size_policy: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    configs/db_size_policy.yaml에서 target DB 설정을 읽는다.
    설정이 없으면 기본 5/10/20GB로 생성한다.
    """
    versions = db_size_policy.get("versions")

    if isinstance(versions, list) and versions:
        result = []

        for item in versions:
            if isinstance(item, dict):
                result.append(item)

        if result:
            return result

    return [
        {"name": "5gb", "target_size_gb": 5},
        {"name": "10gb", "target_size_gb": 10},
        {"name": "20gb", "target_size_gb": 20},
    ]


def get_category_ratios(db_size_policy: Dict[str, Any]) -> Dict[str, float]:
    """
    최종 DB에서 업종별 비율을 적용한다.
    설정이 없으면 기본 비율 사용.
    """
    ratios = db_size_policy.get("business_category_ratio")

    if isinstance(ratios, dict) and ratios:
        return {str(k): float(v) for k, v in ratios.items()}

    return {
        "cafe": 0.20,
        "bakery": 0.18,
        "dessert": 0.18,
        "restaurant": 0.30,
        "pub": 0.14,
    }


def select_rows_for_size(
    df: pd.DataFrame,
    target_size_gb: float,
    category_ratios: Dict[str, float],
    random_state: int = 42,
) -> pd.DataFrame:
    """
    목표 용량에 맞춰 데이터를 선별한다.

    기준:
    - 이미지 실제 파일 크기 합산 기준
    - business_category 비율을 최대한 반영
    - 각 카테고리 내부에서는 product_group, original_food_name 기준으로 섞어서 선택
    """
    target_bytes = gb_to_bytes(target_size_gb)

    total_available_bytes = int(df["final_image_size_bytes"].sum())

    if total_available_bytes <= target_bytes:
        return df.copy().reset_index(drop=True)

    selected_parts = []

    for business_category, ratio in category_ratios.items():
        category_df = df[df["business_category"] == business_category].copy()

        if len(category_df) == 0:
            continue

        category_target_bytes = int(target_bytes * ratio)

        # 다양성을 위해 음식명 기준으로 섞는다.
        sort_cols = []

        if "product_group" in category_df.columns:
            sort_cols.append("product_group")

        if "original_food_name" in category_df.columns:
            sort_cols.append("original_food_name")

        if sort_cols:
            category_df = (
                category_df.sample(frac=1.0, random_state=random_state)
                .sort_values(sort_cols)
                .reset_index(drop=True)
            )
        else:
            category_df = category_df.sample(
                frac=1.0, random_state=random_state
            ).reset_index(drop=True)

        category_df["cumulative_size_bytes"] = category_df[
            "final_image_size_bytes"
        ].cumsum()
        selected = category_df[
            category_df["cumulative_size_bytes"] <= category_target_bytes
        ].copy()

        # 너무 적게 선택되는 경우 최소 1개는 보장
        if len(selected) == 0 and len(category_df) > 0:
            selected = category_df.head(1).copy()

        selected_parts.append(
            selected.drop(columns=["cumulative_size_bytes"], errors="ignore")
        )

    if selected_parts:
        selected_df = pd.concat(selected_parts, axis=0).drop_duplicates(
            subset=["embedding_array_index"]
        )
    else:
        selected_df = pd.DataFrame()

    selected_bytes = (
        int(selected_df["final_image_size_bytes"].sum()) if len(selected_df) else 0
    )

    # 카테고리 비율로 채우고도 목표 용량에 많이 못 미치면 전체 pool에서 추가로 채운다.
    if selected_bytes < target_bytes:
        remaining_df = df[
            ~df["embedding_array_index"].isin(selected_df["embedding_array_index"])
        ].copy()
        remaining_df = remaining_df.sample(
            frac=1.0, random_state=random_state
        ).reset_index(drop=True)
        remaining_df["cumulative_size_bytes"] = remaining_df[
            "final_image_size_bytes"
        ].cumsum()

        remaining_budget = target_bytes - selected_bytes
        extra_df = remaining_df[
            remaining_df["cumulative_size_bytes"] <= remaining_budget
        ].copy()
        extra_df = extra_df.drop(columns=["cumulative_size_bytes"], errors="ignore")

        if len(extra_df) > 0:
            selected_df = pd.concat([selected_df, extra_df], axis=0)

    selected_df = selected_df.drop_duplicates(subset=["embedding_array_index"])
    selected_df = selected_df.sort_values("embedding_array_index").reset_index(
        drop=True
    )

    return selected_df


def copy_images_for_final_db(
    selected_df: pd.DataFrame,
    image_output_dir: Path,
    copy_images: bool = True,
) -> pd.DataFrame:
    """
    최종 DB images 폴더로 이미지 복사.
    같은 파일명이 충돌하지 않도록 final_image_id 기반 파일명을 사용한다.
    """
    result_df = selected_df.reset_index(drop=True).copy()
    ensure_dir(image_output_dir)

    final_image_paths = []
    final_image_file_names = []

    for idx, row in tqdm(
        result_df.iterrows(), total=len(result_df), desc="Copying images"
    ):
        source_path = Path(str(row["image_path"]))
        suffix = source_path.suffix.lower()

        final_file_name = f"img_{idx:08d}{suffix}"
        final_path = image_output_dir / final_file_name

        if copy_images:
            shutil.copy2(source_path, final_path)

        final_image_file_names.append(final_file_name)
        final_image_paths.append(str(final_path))

    result_df.insert(0, "final_image_id", range(len(result_df)))
    result_df["final_image_file_name"] = final_image_file_names
    result_df["final_image_path"] = final_image_paths

    return result_df


def build_prompt_metadata(final_metadata_df: pd.DataFrame) -> pd.DataFrame:
    """
    광고 프롬프트/RAG에서 바로 쓰기 좋은 경량 메타데이터 생성.
    """
    df = final_metadata_df.copy()

    prompt_rows = []

    for _, row in df.iterrows():
        business_category = str(row.get("business_category", "")).strip()
        product_group = str(row.get("product_group", "")).strip()
        product_name = str(
            row.get("product_name", "") or row.get("original_food_name", "")
        ).strip()
        food_code = str(row.get("food_code", "")).strip()
        caption = str(row.get("caption", "")).strip()
        prompt_keywords = str(row.get("prompt_keywords", "")).strip()
        text_for_embedding = str(row.get("text_for_embedding", "")).strip()

        retrieval_text_parts = [
            business_category,
            product_group,
            product_name,
            food_code,
            caption,
            prompt_keywords,
            text_for_embedding,
        ]

        retrieval_text = " | ".join(
            [part for part in retrieval_text_parts if part and part.lower() != "nan"]
        )

        prompt_rows.append(
            {
                "final_image_id": row.get("final_image_id"),
                "final_image_path": row.get("final_image_path"),
                "business_category": business_category,
                "product_group": product_group,
                "product_name": product_name,
                "original_food_name": row.get("original_food_name", ""),
                "food_code": food_code,
                "caption": caption,
                "prompt_keywords": prompt_keywords,
                "text_for_embedding": text_for_embedding,
                "retrieval_text": retrieval_text,
                "ad_prompt_hint": build_ad_prompt_hint(
                    business_category=business_category,
                    product_group=product_group,
                    product_name=product_name,
                    caption=caption,
                ),
            }
        )

    return pd.DataFrame(prompt_rows)


def build_ad_prompt_hint(
    business_category: str,
    product_group: str,
    product_name: str,
    caption: str,
) -> str:
    """
    이미지 생성/광고 문구 생성 모델에 넘길 수 있는 간단한 힌트 텍스트.
    """
    parts = []

    if business_category:
        parts.append(f"business category: {business_category}")

    if product_group:
        parts.append(f"product group: {product_group}")

    if product_name:
        parts.append(f"main product: {product_name}")

    if caption:
        parts.append(f"visual reference: {caption}")

    return ", ".join(parts)


def build_final_mapping(final_metadata_df: pd.DataFrame) -> pd.DataFrame:
    """
    FAISS index id와 최종 이미지/메타데이터 연결 파일 생성.
    """
    mapping_df = final_metadata_df.reset_index(drop=True).copy()

    mapping_df.insert(0, "faiss_index_id", range(len(mapping_df)))

    selected_cols = [
        "faiss_index_id",
        "final_image_id",
        "embedding_id",
        "embedding_array_index",
        "final_image_path",
        "final_image_file_name",
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


def build_final_summary(
    version_name: str,
    target_size_gb: float,
    final_metadata_df: pd.DataFrame,
    embeddings: np.ndarray,
    output_dir: Path,
) -> Dict[str, Any]:
    image_size_bytes = int(final_metadata_df["final_image_size_bytes"].sum())

    summary = {
        "version_name": version_name,
        "target_size_gb": float(target_size_gb),
        "actual_image_size_gb": bytes_to_gb(image_size_bytes),
        "actual_image_size_bytes": image_size_bytes,
        "record_count": int(len(final_metadata_df)),
        "embedding_shape": list(embeddings.shape),
        "output_dir": str(output_dir),
        "files": {
            "images_dir": str(output_dir / "images"),
            "metadata": str(output_dir / "metadata.parquet"),
            "prompt_metadata": str(output_dir / "prompt_metadata.parquet"),
            "embeddings": str(output_dir / "embeddings.npy"),
            "faiss_index": str(output_dir / "faiss.index"),
            "mapping": str(output_dir / "mapping.csv"),
            "summary": str(output_dir / "summary.json"),
        },
    }

    if "business_category" in final_metadata_df.columns:
        summary["business_category_count"] = (
            final_metadata_df["business_category"].value_counts().to_dict()
        )

    if "product_group" in final_metadata_df.columns:
        summary["product_group_count"] = (
            final_metadata_df["product_group"].value_counts().to_dict()
        )

    if "original_food_name" in final_metadata_df.columns:
        summary["unique_food_name_count"] = int(
            final_metadata_df["original_food_name"].nunique()
        )

    return summary


def create_final_db_version(
    version_name: str,
    target_size_gb: float,
    working_df: pd.DataFrame,
    image_embeddings: np.ndarray,
    output_root: Path,
    index_type: str,
    category_ratios: Dict[str, float],
    copy_images: bool,
    random_state: int,
) -> Dict[str, Any]:
    output_dir = output_root / version_name
    images_dir = output_dir / "images"

    ensure_dir(output_dir)
    ensure_dir(images_dir)

    selected_df = select_rows_for_size(
        df=working_df,
        target_size_gb=target_size_gb,
        category_ratios=category_ratios,
        random_state=random_state,
    )

    final_metadata_df = copy_images_for_final_db(
        selected_df=selected_df,
        image_output_dir=images_dir,
        copy_images=copy_images,
    )

    selected_embedding_indices = (
        final_metadata_df["embedding_array_index"].astype(int).to_numpy()
    )
    selected_embeddings = image_embeddings[selected_embedding_indices].astype(
        np.float32
    )

    prompt_metadata_df = build_prompt_metadata(final_metadata_df)
    mapping_df = build_final_mapping(final_metadata_df)

    faiss_index = build_faiss_index(
        embeddings=selected_embeddings,
        index_type=index_type,
    )

    metadata_output = output_dir / "metadata.parquet"
    prompt_metadata_output = output_dir / "prompt_metadata.parquet"
    embeddings_output = output_dir / "embeddings.npy"
    faiss_output = output_dir / "faiss.index"
    mapping_output = output_dir / "mapping.csv"
    summary_output = output_dir / "summary.json"

    final_metadata_df.to_parquet(metadata_output, index=False)
    prompt_metadata_df.to_parquet(prompt_metadata_output, index=False)
    np.save(embeddings_output, normalize_embeddings(selected_embeddings))
    faiss.write_index(faiss_index, str(faiss_output))
    save_csv(mapping_df, mapping_output)

    summary = build_final_summary(
        version_name=version_name,
        target_size_gb=target_size_gb,
        final_metadata_df=final_metadata_df,
        embeddings=selected_embeddings,
        output_dir=output_dir,
    )

    save_json(summary, summary_output)

    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create final Advertisement Retrieval DB packages."
    )

    parser.add_argument(
        "--pipeline-config",
        type=str,
        default="configs/pipeline_config.yaml",
    )
    parser.add_argument(
        "--db-size-policy",
        type=str,
        default="configs/db_size_policy.yaml",
    )
    parser.add_argument(
        "--metadata",
        type=str,
        default=None,
        help="Default: data/metadata/deduplicated_metadata.parquet",
    )
    parser.add_argument(
        "--embedding-metadata",
        type=str,
        default="data/embeddings/embedding_metadata.parquet",
    )
    parser.add_argument(
        "--image-embeddings",
        type=str,
        default="data/embeddings/image_embeddings.npy",
    )
    parser.add_argument(
        "--output-root",
        type=str,
        default=None,
        help="Default from pipeline_config final_db_dir.",
    )
    parser.add_argument(
        "--index-type",
        type=str,
        default="IndexFlatIP",
        choices=["IndexFlatIP", "IndexFlatL2"],
    )
    parser.add_argument(
        "--versions",
        type=str,
        default=None,
        help="Comma separated versions to create. Example: 5gb,10gb",
    )
    parser.add_argument(
        "--no-copy-images",
        action="store_true",
        help="Do not physically copy images. Useful for quick test.",
    )
    parser.add_argument(
        "--random-state",
        type=int,
        default=42,
    )

    return parser.parse_args()


def main() -> None:
    args = parse_args()

    pipeline_config = load_yaml(args.pipeline_config)
    db_size_policy = load_yaml(args.db_size_policy)

    paths = pipeline_config.get("paths", {})

    metadata_path = Path(
        args.metadata
        or paths.get(
            "deduplicated_metadata_path", "data/metadata/deduplicated_metadata.parquet"
        )
    )
    embedding_metadata_path = Path(args.embedding_metadata)
    image_embeddings_path = Path(args.image_embeddings)
    output_root = Path(args.output_root or paths.get("final_db_dir", "data/final_db"))

    print("[INFO] AIHub Food Ad RAG - Make Final DB")
    print(f"[INFO] metadata             : {metadata_path}")
    print(f"[INFO] embedding_metadata   : {embedding_metadata_path}")
    print(f"[INFO] image_embeddings     : {image_embeddings_path}")
    print(f"[INFO] output_root          : {output_root}")
    print(f"[INFO] index_type           : {args.index_type}")
    print(f"[INFO] copy_images          : {not args.no_copy_images}")

    _, embedding_metadata_df, image_embeddings = load_inputs(
        metadata_path=metadata_path,
        embedding_metadata_path=embedding_metadata_path,
        image_embeddings_path=image_embeddings_path,
    )

    working_df = prepare_working_df(
        embedding_metadata_df=embedding_metadata_df,
        image_embeddings=image_embeddings,
    )

    versions = get_target_versions(db_size_policy)
    category_ratios = get_category_ratios(db_size_policy)

    if args.versions:
        requested_names = {
            name.strip() for name in args.versions.split(",") if name.strip()
        }
        versions = [
            version
            for version in versions
            if str(version.get("name")) in requested_names
        ]

    if not versions:
        raise ValueError("No final DB versions selected.")

    ensure_dir(output_root)

    all_summaries = []

    for version in versions:
        version_name = str(version.get("name"))
        target_size_gb = float(version.get("target_size_gb"))

        print(
            f"[INFO] Creating final DB version: {version_name}, target={target_size_gb}GB"
        )

        summary = create_final_db_version(
            version_name=version_name,
            target_size_gb=target_size_gb,
            working_df=working_df,
            image_embeddings=image_embeddings,
            output_root=output_root,
            index_type=args.index_type,
            category_ratios=category_ratios,
            copy_images=not args.no_copy_images,
            random_state=args.random_state,
        )

        all_summaries.append(summary)

        print(f"[DONE] {version_name} completed.")
        print(json.dumps(summary, ensure_ascii=False, indent=2))

    master_summary = {
        "version_count": len(all_summaries),
        "versions": all_summaries,
    }

    save_json(master_summary, output_root / "final_db_summary.json")

    print("[DONE] Final DB creation completed.")
    print(f"[DONE] master summary: {output_root / 'final_db_summary.json'}")


if __name__ == "__main__":
    main()
