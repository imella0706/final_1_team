from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any, Dict, List

import pandas as pd
import torch
import yaml
from PIL import Image, UnidentifiedImageError
from tqdm import tqdm
from transformers import BlipForConditionalGeneration, BlipProcessor
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


def configure_cpu(cpu_threads: int) -> None:
    """
    CPU 환경에서 torch 연산 스레드를 제한/설정한다.
    너무 높게 잡으면 오히려 Windows에서 느려질 수 있다.
    """
    if cpu_threads <= 0:
        return

    os.environ["OMP_NUM_THREADS"] = str(cpu_threads)
    os.environ["MKL_NUM_THREADS"] = str(cpu_threads)

    torch.set_num_threads(cpu_threads)
    torch.set_num_interop_threads(max(1, min(2, cpu_threads)))


def get_device(preferred_device: str) -> str:
    preferred_device = str(preferred_device).lower().strip()

    if preferred_device == "cuda" and torch.cuda.is_available():
        return "cuda"

    return "cpu"


def safe_open_image(image_path: str | Path, max_image_size: int = 512) -> Image.Image:
    """
    CPU 속도를 위해 이미지를 RGB로 열고 최대 크기를 제한한다.
    BLIP 입력은 processor가 다시 전처리하므로 원본 3000px 전체를 넣을 필요가 없다.
    """
    path = Path(str(image_path))

    if not path.exists():
        raise FileNotFoundError(f"image not found: {path}")

    image = Image.open(path).convert("RGB")

    if max_image_size and max(image.size) > max_image_size:
        image.thumbnail((max_image_size, max_image_size))

    return image


def generate_caption_one(
    image: Image.Image,
    processor: BlipProcessor,
    model: BlipForConditionalGeneration,
    device: str,
    max_new_tokens: int,
) -> str:
    """
    CPU 안정성을 위해 한 장씩 생성한다.
    """
    inputs = processor(
        images=image,
        return_tensors="pt",
    )

    inputs = {k: v.to(device) for k, v in inputs.items()}

    with torch.inference_mode():
        outputs = model.generate(
            **inputs,
            max_new_tokens=max_new_tokens,
            num_beams=1,
        )

    caption = processor.decode(outputs[0], skip_special_tokens=True)
    return caption.strip()


def build_prompt_keywords(row: pd.Series, caption: str) -> str:
    values = [
        row.get("business_category", ""),
        row.get("product_group", ""),
        row.get("original_food_name", ""),
        row.get("product_name", ""),
        row.get("food_code", ""),
        caption,
    ]

    keywords = []

    for value in values:
        if value is None:
            continue

        text = str(value).strip()

        if text and text not in keywords:
            keywords.append(text)

    return ", ".join(keywords)


def infer_visual_tags(row: pd.Series, caption: str) -> Dict[str, str]:
    business_category = str(row.get("business_category", "")).strip()
    product_group = str(row.get("product_group", "")).strip()
    caption_lower = caption.lower()

    lighting = "natural_light"

    if any(word in caption_lower for word in ["dark", "night", "dim"]):
        lighting = "low_light"
    elif any(word in caption_lower for word in ["bright", "white", "studio"]):
        lighting = "bright_light"

    composition = "single_food_centered"

    if any(word in caption_lower for word in ["table", "plate", "dish", "bowl"]):
        composition = "food_on_table"

    if any(
        word in caption_lower for word in ["multiple", "various", "assorted", "many"]
    ):
        composition = "multiple_items"

    camera_angle = "front_or_45_degree"

    if any(word in caption_lower for word in ["top", "overhead"]):
        camera_angle = "top_view"

    if business_category == "cafe":
        ad_use_case = "cafe_menu_promotion"
    elif business_category == "bakery":
        ad_use_case = "bakery_product_promotion"
    elif business_category == "dessert":
        ad_use_case = "dessert_product_promotion"
    elif business_category == "pub":
        ad_use_case = "pub_side_menu_promotion"
    else:
        ad_use_case = "restaurant_menu_promotion"

    visual_style_hint = (
        f"{business_category}_{product_group}" if product_group else business_category
    )

    return {
        "caption_lighting": lighting,
        "caption_composition": composition,
        "caption_camera_angle": camera_angle,
        "ad_use_case": ad_use_case,
        "visual_style_hint": visual_style_hint,
    }


def make_empty_caption_record() -> Dict[str, Any]:
    return {
        "caption": "",
        "caption_status": "pending",
        "caption_error": "",
        "prompt_keywords": "",
        "caption_lighting": "",
        "caption_composition": "",
        "caption_camera_angle": "",
        "ad_use_case": "",
        "visual_style_hint": "",
    }


def load_existing_checkpoint(checkpoint_path: Path) -> pd.DataFrame | None:
    if not checkpoint_path.exists():
        return None

    try:
        return pd.read_parquet(checkpoint_path)
    except Exception:
        return None


def caption_tagging_cpu_safe(
    df: pd.DataFrame,
    processor: BlipProcessor,
    model: BlipForConditionalGeneration,
    device: str,
    max_new_tokens: int,
    max_image_size: int,
    checkpoint_path: Path,
    checkpoint_every: int,
    resume: bool,
) -> pd.DataFrame:
    """
    CPU용 안정 실행 함수.
    한 장씩 처리하고 주기적으로 checkpoint parquet 저장.
    """
    result_df = df.reset_index(drop=True).copy()

    caption_cols = list(make_empty_caption_record().keys())

    for col in caption_cols:
        if col not in result_df.columns:
            result_df[col] = ""

    if resume:
        checkpoint_df = load_existing_checkpoint(checkpoint_path)

        if checkpoint_df is not None and len(checkpoint_df) == len(result_df):
            print(f"[INFO] Resuming from checkpoint: {checkpoint_path}")
            result_df = checkpoint_df.reset_index(drop=True).copy()

    for idx in tqdm(range(len(result_df)), desc="Generating captions CPU"):
        current_status = str(result_df.at[idx, "caption_status"]).strip()

        if resume and current_status == "success":
            continue

        row = result_df.loc[idx]
        image_path = row.get("image_path")

        try:
            image = safe_open_image(image_path, max_image_size=max_image_size)

            caption = generate_caption_one(
                image=image,
                processor=processor,
                model=model,
                device=device,
                max_new_tokens=max_new_tokens,
            )

            visual_tags = infer_visual_tags(row, caption)

            result_df.at[idx, "caption"] = caption
            result_df.at[idx, "caption_status"] = "success"
            result_df.at[idx, "caption_error"] = ""
            result_df.at[idx, "prompt_keywords"] = build_prompt_keywords(row, caption)

            for key, value in visual_tags.items():
                result_df.at[idx, key] = value

        except (
            FileNotFoundError,
            UnidentifiedImageError,
            OSError,
            RuntimeError,
            ValueError,
        ) as e:
            result_df.at[idx, "caption"] = ""
            result_df.at[idx, "caption_status"] = "failed"
            result_df.at[idx, "caption_error"] = str(e)

        if checkpoint_every > 0 and (idx + 1) % checkpoint_every == 0:
            ensure_parent_dir(checkpoint_path)
            result_df.to_parquet(checkpoint_path, index=False)
            print(f"[CHECKPOINT] saved: {checkpoint_path} at row {idx + 1}")

    ensure_parent_dir(checkpoint_path)
    result_df.to_parquet(checkpoint_path, index=False)

    return result_df


def build_caption_summary(df: pd.DataFrame) -> Dict[str, Any]:
    total_count = len(df)

    success_count = (
        int((df["caption_status"] == "success").sum())
        if "caption_status" in df.columns
        else 0
    )
    failed_count = (
        int((df["caption_status"] == "failed").sum())
        if "caption_status" in df.columns
        else 0
    )
    pending_count = (
        int((df["caption_status"] == "pending").sum())
        if "caption_status" in df.columns
        else 0
    )

    summary: Dict[str, Any] = {
        "total_count": int(total_count),
        "caption_success_count": int(success_count),
        "caption_failed_count": int(failed_count),
        "caption_pending_count": int(pending_count),
        "caption_success_ratio": (
            float(success_count / total_count) if total_count > 0 else 0.0
        ),
        "caption_failed_ratio": (
            float(failed_count / total_count) if total_count > 0 else 0.0
        ),
    }

    if "caption_status" in df.columns:
        summary["caption_status_count"] = df["caption_status"].value_counts().to_dict()

    if "caption_lighting" in df.columns:
        summary["caption_lighting_count"] = (
            df["caption_lighting"].value_counts().to_dict()
        )

    if "caption_composition" in df.columns:
        summary["caption_composition_count"] = (
            df["caption_composition"].value_counts().to_dict()
        )

    if "ad_use_case" in df.columns:
        summary["ad_use_case_count"] = df["ad_use_case"].value_counts().to_dict()

    return summary


def save_caption_reports(df: pd.DataFrame, report_dir: Path) -> None:
    ensure_dir(report_dir)

    status_dist = (
        df["caption_status"]
        .fillna("")
        .astype(str)
        .replace("", "(missing)")
        .value_counts()
        .reset_index()
    )
    status_dist.columns = ["caption_status", "count"]
    status_dist["ratio"] = status_dist["count"] / len(df)

    save_csv(status_dist, report_dir / "caption_status_distribution.csv")

    failed = df[df["caption_status"] != "success"].copy()

    failed_cols = [
        "original_food_name",
        "food_code",
        "business_category",
        "product_group",
        "image_path",
        "caption_status",
        "caption_error",
    ]

    existing_failed_cols = [col for col in failed_cols if col in failed.columns]

    if existing_failed_cols:
        failed = failed[existing_failed_cols]

    save_csv(failed, report_dir / "caption_failed_images.csv")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="CPU-safe image caption tagging using BLIP."
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
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
    )
    parser.add_argument(
        "--report-dir",
        type=str,
        default="outputs/reports/caption_tagging",
    )
    parser.add_argument(
        "--model-name",
        type=str,
        default=None,
    )
    parser.add_argument(
        "--device",
        type=str,
        default="cpu",
    )
    parser.add_argument(
        "--cpu-threads",
        type=int,
        default=4,
    )
    parser.add_argument(
        "--max-new-tokens",
        type=int,
        default=25,
    )
    parser.add_argument(
        "--max-image-size",
        type=int,
        default=384,
    )
    parser.add_argument(
        "--sample-limit",
        type=int,
        default=None,
    )
    parser.add_argument(
        "--checkpoint-path",
        type=str,
        default="outputs/checkpoints/caption_tagging_checkpoint.parquet",
    )
    parser.add_argument(
        "--checkpoint-every",
        type=int,
        default=100,
    )
    parser.add_argument(
        "--resume",
        action="store_true",
    )

    return parser.parse_args()


def main() -> None:
    set_global_seed(DEFAULT_RANDOM_SEED)
    args = parse_args()

    configure_cpu(args.cpu_threads)

    config = load_pipeline_config(args.config)
    paths = config.get("paths", {})
    caption_config = config.get("caption_tagging", {})

    input_path = Path(
        args.input
        or paths.get(
            "deduplicated_metadata_path",
            "data/metadata/deduplicated_metadata.parquet",
        )
    )

    output_path = Path(
        args.output
        or paths.get(
            "tagged_metadata_path",
            "data/metadata/tagged_metadata.parquet",
        )
    )

    report_dir = Path(args.report_dir)
    checkpoint_path = Path(args.checkpoint_path)

    model_name = args.model_name or caption_config.get(
        "model_name",
        "Salesforce/blip-image-captioning-base",
    )

    device = get_device(args.device)

    print("[INFO] AIHub Food Ad RAG - CPU Safe Caption Tagging")
    print(f"[INFO] input            : {input_path}")
    print(f"[INFO] output           : {output_path}")
    print(f"[INFO] report_dir       : {report_dir}")
    print(f"[INFO] checkpoint_path  : {checkpoint_path}")
    print(f"[INFO] model_name       : {model_name}")
    print(f"[INFO] device           : {device}")
    print(f"[INFO] cpu_threads      : {args.cpu_threads}")
    print(f"[INFO] max_new_tokens   : {args.max_new_tokens}")
    print(f"[INFO] max_image_size   : {args.max_image_size}")
    print(f"[INFO] checkpoint_every : {args.checkpoint_every}")
    print(f"[INFO] resume           : {args.resume}")
    print(f"[INFO] sample_limit     : {args.sample_limit}")

    if not input_path.exists():
        raise FileNotFoundError(f"Input metadata not found: {input_path}")

    df = pd.read_parquet(input_path)

    if args.sample_limit is not None:
        df = df.head(args.sample_limit).copy()

    if "image_path" not in df.columns:
        raise ValueError("Input metadata must contain image_path column.")

    print("[INFO] Loading BLIP processor/model...")
    processor = BlipProcessor.from_pretrained(model_name)
    model = BlipForConditionalGeneration.from_pretrained(model_name)
    model.to(device)
    model.eval()

    tagged_df = caption_tagging_cpu_safe(
        df=df,
        processor=processor,
        model=model,
        device=device,
        max_new_tokens=args.max_new_tokens,
        max_image_size=args.max_image_size,
        checkpoint_path=checkpoint_path,
        checkpoint_every=args.checkpoint_every,
        resume=args.resume,
    )

    ensure_parent_dir(output_path)
    tagged_df.to_parquet(output_path, index=False)

    summary = build_caption_summary(tagged_df)

    save_json(summary, report_dir / "caption_tagging_summary.json")
    save_caption_reports(tagged_df, report_dir)

    print("[DONE] Caption tagging completed.")
    print(f"[DONE] output metadata : {output_path}")
    print(f"[DONE] summary         : {report_dir / 'caption_tagging_summary.json'}")
    print("[SUMMARY]")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
