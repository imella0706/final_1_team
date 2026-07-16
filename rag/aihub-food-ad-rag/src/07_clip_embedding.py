from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Tuple

import numpy as np
import open_clip
import pandas as pd
import torch
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


def configure_cpu(cpu_threads: int) -> None:
    """
    CPU 환경에서 torch 스레드 수를 설정한다.
    """
    if cpu_threads <= 0:
        return

    os.environ["OMP_NUM_THREADS"] = str(cpu_threads)
    os.environ["MKL_NUM_THREADS"] = str(cpu_threads)

    torch.set_num_threads(cpu_threads)
    torch.set_num_interop_threads(max(1, min(2, cpu_threads)))


def get_device(device_name: str) -> torch.device:
    """
    현재 코드는 안정성을 위해 cuda/cpu를 지원한다.
    Intel Arc GPU는 CUDA가 아니므로 여기서는 cpu로 사용하는 것을 기본 권장한다.
    """
    device_name = str(device_name).lower().strip()

    if device_name == "cuda":
        if torch.cuda.is_available():
            return torch.device("cuda")
        print("[WARN] CUDA requested but not available. Falling back to CPU.")
        return torch.device("cpu")

    if device_name == "auto":
        if torch.cuda.is_available():
            return torch.device("cuda")
        return torch.device("cpu")

    return torch.device("cpu")


def safe_open_image(image_path: str | Path) -> Image.Image:
    path = Path(str(image_path))

    if not path.exists():
        raise FileNotFoundError(f"image not found: {path}")

    image = Image.open(path).convert("RGB")
    return image


def load_clip_model(
    model_name: str,
    pretrained: str,
    device: torch.device,
) -> Tuple[torch.nn.Module, Any, Any]:
    """
    OpenCLIP 모델과 전처리 함수를 로드한다.
    """
    model, _, preprocess = open_clip.create_model_and_transforms(
        model_name=model_name,
        pretrained=pretrained,
    )

    model.to(device)
    model.eval()

    tokenizer = open_clip.get_tokenizer(model_name)

    return model, preprocess, tokenizer


def build_text_for_embedding(row: pd.Series) -> str:
    """
    이미지 검색뿐 아니라 텍스트 검색도 가능하게 하기 위한 대표 텍스트를 만든다.

    10단계 caption이 있으면 caption을 포함하고,
    없으면 음식명/업종/상품군 중심으로 구성한다.
    """
    values = [
        row.get("business_category", ""),
        row.get("product_group", ""),
        row.get("original_food_name", ""),
        row.get("product_name", ""),
        row.get("food_code", ""),
        row.get("caption", ""),
        row.get("prompt_keywords", ""),
    ]

    parts: List[str] = []

    for value in values:
        if value is None:
            continue

        text = str(value).strip()

        if text and text not in parts:
            parts.append(text)

    return " | ".join(parts)


def encode_image_batch(
    image_paths: List[str],
    model: torch.nn.Module,
    preprocess: Any,
    device: torch.device,
) -> Tuple[np.ndarray, List[Dict[str, Any]]]:
    """
    이미지 배치를 CLIP 임베딩으로 변환한다.

    실패한 이미지는 별도 기록하고,
    성공한 이미지만 임베딩 배열로 반환한다.
    """
    tensors = []
    records = []

    for image_path in image_paths:
        record = {
            "image_path": image_path,
            "embedding_status": "failed",
            "embedding_error": "",
        }

        try:
            image = safe_open_image(image_path)
            image_tensor = preprocess(image)
            tensors.append(image_tensor)
            record["embedding_status"] = "success"

        except (FileNotFoundError, UnidentifiedImageError, OSError, ValueError) as e:
            record["embedding_error"] = str(e)

        records.append(record)

    if not tensors:
        return np.empty((0, 0), dtype=np.float32), records

    batch_tensor = torch.stack(tensors).to(device)

    with torch.inference_mode():
        image_features = model.encode_image(batch_tensor)
        image_features = image_features / image_features.norm(dim=-1, keepdim=True)

    image_embeddings = image_features.detach().cpu().numpy().astype(np.float32)

    return image_embeddings, records


def encode_text_batch(
    texts: List[str],
    model: torch.nn.Module,
    tokenizer: Any,
    device: torch.device,
) -> np.ndarray:
    """
    텍스트도 CLIP 임베딩으로 변환한다.
    검색 API에서 텍스트 쿼리와 이미지 임베딩을 비교할 때 활용 가능하다.
    """
    if not texts:
        return np.empty((0, 0), dtype=np.float32)

    tokens = tokenizer(texts).to(device)

    with torch.inference_mode():
        text_features = model.encode_text(tokens)
        text_features = text_features / text_features.norm(dim=-1, keepdim=True)

    text_embeddings = text_features.detach().cpu().numpy().astype(np.float32)

    return text_embeddings


def build_embeddings(
    df: pd.DataFrame,
    model: torch.nn.Module,
    preprocess: Any,
    tokenizer: Any,
    device: torch.device,
    batch_size: int,
    include_text_embeddings: bool,
) -> Tuple[np.ndarray, np.ndarray | None, pd.DataFrame, pd.DataFrame]:
    """
    전체 데이터에 대해 이미지 임베딩을 생성한다.

    반환:
    - image_embeddings
    - text_embeddings 또는 None
    - embedding_metadata_df
    - failed_df
    """
    metadata_records: List[Dict[str, Any]] = []
    failed_records: List[Dict[str, Any]] = []

    image_embedding_chunks: List[np.ndarray] = []
    text_embedding_chunks: List[np.ndarray] = []

    embedding_id = 0
    total = len(df)

    for start_idx in tqdm(
        range(0, total, batch_size), desc="Generating CLIP embeddings"
    ):
        end_idx = min(start_idx + batch_size, total)
        batch_df = df.iloc[start_idx:end_idx].copy()

        image_paths = batch_df["image_path"].astype(str).tolist()

        image_embeddings, status_records = encode_image_batch(
            image_paths=image_paths,
            model=model,
            preprocess=preprocess,
            device=device,
        )

        success_local_indices = [
            i
            for i, record in enumerate(status_records)
            if record["embedding_status"] == "success"
        ]

        if len(success_local_indices) != len(image_embeddings):
            raise RuntimeError(
                "Internal error: success image count and embedding count mismatch."
            )

        successful_texts: List[str] = []

        for emb_array_idx, local_idx in enumerate(success_local_indices):
            original_row = batch_df.iloc[local_idx]
            status_record = status_records[local_idx]

            text_for_embedding = build_text_for_embedding(original_row)
            successful_texts.append(text_for_embedding)

            metadata_records.append(
                {
                    "embedding_id": embedding_id,
                    "source_row_index": int(batch_df.index[local_idx]),
                    "image_path": status_record["image_path"],
                    "original_food_name": original_row.get("original_food_name", ""),
                    "product_name": original_row.get("product_name", ""),
                    "food_code": original_row.get("food_code", ""),
                    "business_category": original_row.get("business_category", ""),
                    "product_group": original_row.get("product_group", ""),
                    "caption": original_row.get("caption", ""),
                    "prompt_keywords": original_row.get("prompt_keywords", ""),
                    "text_for_embedding": text_for_embedding,
                }
            )

            embedding_id += 1

        for local_idx, status_record in enumerate(status_records):
            if status_record["embedding_status"] != "success":
                original_row = batch_df.iloc[local_idx]

                failed_records.append(
                    {
                        "source_row_index": int(batch_df.index[local_idx]),
                        "image_path": status_record["image_path"],
                        "original_food_name": original_row.get(
                            "original_food_name", ""
                        ),
                        "food_code": original_row.get("food_code", ""),
                        "business_category": original_row.get("business_category", ""),
                        "product_group": original_row.get("product_group", ""),
                        "embedding_status": status_record["embedding_status"],
                        "embedding_error": status_record["embedding_error"],
                    }
                )

        if image_embeddings.shape[0] > 0:
            image_embedding_chunks.append(image_embeddings)

            if include_text_embeddings:
                text_embeddings = encode_text_batch(
                    texts=successful_texts,
                    model=model,
                    tokenizer=tokenizer,
                    device=device,
                )
                text_embedding_chunks.append(text_embeddings)

    if image_embedding_chunks:
        final_image_embeddings = np.vstack(image_embedding_chunks).astype(np.float32)
    else:
        final_image_embeddings = np.empty((0, 0), dtype=np.float32)

    final_text_embeddings = None

    if include_text_embeddings:
        if text_embedding_chunks:
            final_text_embeddings = np.vstack(text_embedding_chunks).astype(np.float32)
        else:
            final_text_embeddings = np.empty((0, 0), dtype=np.float32)

    embedding_metadata_df = pd.DataFrame(metadata_records)
    failed_df = pd.DataFrame(failed_records)

    return (
        final_image_embeddings,
        final_text_embeddings,
        embedding_metadata_df,
        failed_df,
    )


def build_embedding_summary(
    input_count: int,
    image_embeddings: np.ndarray,
    text_embeddings: np.ndarray | None,
    failed_df: pd.DataFrame,
    model_name: str,
    pretrained: str,
    device: torch.device,
) -> Dict[str, Any]:
    success_count = int(image_embeddings.shape[0])
    failed_count = int(len(failed_df))

    summary: Dict[str, Any] = {
        "input_count": int(input_count),
        "embedding_success_count": success_count,
        "embedding_failed_count": failed_count,
        "embedding_success_ratio": (
            float(success_count / input_count) if input_count > 0 else 0.0
        ),
        "embedding_failed_ratio": (
            float(failed_count / input_count) if input_count > 0 else 0.0
        ),
        "image_embedding_shape": list(image_embeddings.shape),
        "text_embedding_shape": (
            list(text_embeddings.shape) if text_embeddings is not None else None
        ),
        "model_name": model_name,
        "pretrained": pretrained,
        "device": str(device),
        "embedding_dtype": str(image_embeddings.dtype),
        "normalized": True,
    }

    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate CLIP image embeddings from metadata."
    )

    parser.add_argument(
        "--config",
        type=str,
        default="configs/pipeline_config.yaml",
    )
    parser.add_argument(
        "--input",
        type=str,
        default=None,
        help="Input metadata parquet. Default: deduplicated_metadata_path.",
    )
    parser.add_argument(
        "--image-embeddings-output",
        type=str,
        default="data/embeddings/image_embeddings.npy",
    )
    parser.add_argument(
        "--text-embeddings-output",
        type=str,
        default="data/embeddings/text_embeddings.npy",
    )
    parser.add_argument(
        "--metadata-output",
        type=str,
        default="data/embeddings/embedding_metadata.parquet",
    )
    parser.add_argument(
        "--report-dir",
        type=str,
        default="outputs/reports/clip_embedding",
    )
    parser.add_argument(
        "--model-name",
        type=str,
        default=None,
    )
    parser.add_argument(
        "--pretrained",
        type=str,
        default=None,
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=None,
    )
    parser.add_argument(
        "--device",
        type=str,
        default=None,
    )
    parser.add_argument(
        "--cpu-threads",
        type=int,
        default=4,
    )
    parser.add_argument(
        "--sample-limit",
        type=int,
        default=None,
    )
    parser.add_argument(
        "--include-text-embeddings",
        action="store_true",
        help="Also generate text embeddings from metadata/caption text.",
    )

    return parser.parse_args()


def main() -> None:
    args = parse_args()

    configure_cpu(args.cpu_threads)

    config = load_pipeline_config(args.config)
    paths = config.get("paths", {})
    clip_config = config.get("clip_embedding", {})

    input_path = Path(
        args.input
        or paths.get(
            "deduplicated_metadata_path",
            "data/metadata/deduplicated_metadata.parquet",
        )
    )

    image_embeddings_output = Path(args.image_embeddings_output)
    text_embeddings_output = Path(args.text_embeddings_output)
    metadata_output = Path(args.metadata_output)
    report_dir = Path(args.report_dir)

    model_name = args.model_name or clip_config.get("model_name", "ViT-B-32")
    pretrained = args.pretrained or clip_config.get("pretrained", "openai")
    batch_size = int(args.batch_size or clip_config.get("batch_size", 16))
    device_name = args.device or clip_config.get("device", "auto")
    device = get_device(device_name)

    print("[INFO] AIHub Food Ad RAG - CLIP Embedding")
    print(f"[INFO] input                   : {input_path}")
    print(f"[INFO] image_embeddings_output : {image_embeddings_output}")
    print(f"[INFO] text_embeddings_output  : {text_embeddings_output}")
    print(f"[INFO] metadata_output         : {metadata_output}")
    print(f"[INFO] report_dir              : {report_dir}")
    print(f"[INFO] model_name              : {model_name}")
    print(f"[INFO] pretrained              : {pretrained}")
    print(f"[INFO] batch_size              : {batch_size}")
    print(f"[INFO] device                  : {device}")
    print(f"[INFO] cpu_threads             : {args.cpu_threads}")
    print(f"[INFO] sample_limit            : {args.sample_limit}")
    print(f"[INFO] include_text_embeddings : {args.include_text_embeddings}")

    if not input_path.exists():
        raise FileNotFoundError(f"Input metadata not found: {input_path}")

    df = pd.read_parquet(input_path)

    if args.sample_limit is not None:
        df = df.head(args.sample_limit).copy()

    if "image_path" not in df.columns:
        raise ValueError("Input metadata must contain image_path column.")

    print("[INFO] Loading CLIP model...")
    model, preprocess, tokenizer = load_clip_model(
        model_name=model_name,
        pretrained=pretrained,
        device=device,
    )

    image_embeddings, text_embeddings, embedding_metadata_df, failed_df = (
        build_embeddings(
            df=df,
            model=model,
            preprocess=preprocess,
            tokenizer=tokenizer,
            device=device,
            batch_size=batch_size,
            include_text_embeddings=args.include_text_embeddings,
        )
    )

    ensure_parent_dir(image_embeddings_output)
    np.save(image_embeddings_output, image_embeddings)

    if args.include_text_embeddings and text_embeddings is not None:
        ensure_parent_dir(text_embeddings_output)
        np.save(text_embeddings_output, text_embeddings)

    ensure_parent_dir(metadata_output)
    embedding_metadata_df.to_parquet(metadata_output, index=False)

    ensure_dir(report_dir)

    summary = build_embedding_summary(
        input_count=len(df),
        image_embeddings=image_embeddings,
        text_embeddings=text_embeddings,
        failed_df=failed_df,
        model_name=model_name,
        pretrained=pretrained,
        device=device,
    )

    save_json(summary, report_dir / "clip_embedding_summary.json")
    save_csv(failed_df, report_dir / "embedding_failed_images.csv")

    print("[DONE] CLIP embedding completed.")
    print(f"[DONE] image embeddings : {image_embeddings_output}")
    print(f"[DONE] metadata         : {metadata_output}")
    print(f"[DONE] summary          : {report_dir / 'clip_embedding_summary.json'}")

    if args.include_text_embeddings:
        print(f"[DONE] text embeddings  : {text_embeddings_output}")

    print("[SUMMARY]")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
