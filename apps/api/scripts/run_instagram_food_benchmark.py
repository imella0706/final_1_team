"""Benchmark Instagram ad generation across food photos and model combinations.

The command is a dry run by default. It selects ten diverse food photos from the
dataset metadata, builds the exact same Instagram request for every model
combination, and writes a plan. Add ``--execute`` to call the configured model
runtimes. Failed trials are logged and do not stop the remaining matrix.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import csv
import hashlib
import json
import shutil
import sys
import unicodedata
from collections import Counter, defaultdict
from contextlib import AsyncExitStack
from datetime import UTC, datetime
from io import BytesIO
from itertools import product
from pathlib import Path
from statistics import mean
from time import perf_counter
from typing import Any

from PIL import Image, ImageDraw, ImageFont, ImageOps

from app.evaluation.metrics import (
    context_adherence_score,
    hallucination_terms,
    hashtag_compliance_rate,
    headline_diversity_score,
    is_english_image_prompt,
    tone_manner_proxy_score,
    toxicity_terms,
)
from app.extensions.ad_content.schemas import AdContentRequest, ImageModel, VisionModel
from app.modules.ad_copy.schemas import AdChannel, AdModel


API_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = API_ROOT.parents[1]
DEFAULT_IMAGES_DIR = PROJECT_ROOT / "data" / "images"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "outputs" / "instagram-food-benchmark"
DEFAULT_MANIFEST = API_ROOT / "evals" / "instagram_food_benchmark_10.json"
DEFAULT_TREND_CARD_ID = "gogumafarm:1bf390d89536004b"

# This balanced set compares local, Hugging Face, NVIDIA and OpenAI copy runtimes.
# A user can replace or narrow any list with repeated CLI options.
DEFAULT_LLM_MODELS = (
    AdModel.LOCAL_QWEN_2_5_1_5B,
    AdModel.LOCAL_QWEN_2_5_7B,
    AdModel.LOCAL_MISTRAL_7B,
    AdModel.QWEN_2_5_7B,
    AdModel.NVIDIA_LLAMA_3_1_8B,
    AdModel.OPENAI_GPT_5_4_NANO,
    AdModel.OPENAI_GPT_5_4_MINI,
    AdModel.OPENAI_GPT_5_4,
)
DEFAULT_VISION_MODELS = (
    VisionModel.LOCAL_QWEN_3_VL_2B,
    VisionModel.LOCAL_QWEN_3_VL_4B,
    VisionModel.LOCAL_QWEN_2_5_VL_7B,
    VisionModel.LOCAL_QWEN_3_VL_8B,
    VisionModel.OPENAI_GPT_5_4_MINI,
)
DEFAULT_IMAGE_MODELS = (
    ImageModel.SDXL_BASE,
    ImageModel.SDXL_TURBO,
    ImageModel.OPENAI_GPT_IMAGE_1_MINI,
)

# Reproducible, manually checked food set. It spans bakery, cafe, pub and four
# distinct restaurant cuisines without using the known cafe/tea misclassification
# around DIV_IMG_000131. Selection falls back to category quotas for other datasets.
DEFAULT_CASE_IDS = (
    "DIV_IMG_000010",  # 마늘빵
    "DIV_IMG_000046",  # 감자토스트
    "DIV_IMG_000065",  # BLT샌드위치
    "DIV_IMG_000067",  # 단호박샐러드
    "DIV_IMG_000188",  # 어묵튀김
    "DIV_IMG_000196",  # 마라살꼬치
    "DIV_IMG_000235",  # 깐풍치킨(뼈)
    "DIV_IMG_000346",  # 가리비초밥
    "DIV_IMG_000496",  # 단호박피자
    "DIV_IMG_000518",  # 날치알크림파스타
)

# Ten cases are allocated across the categories that exist in the local subset.
# Within a category we prefer distinct product groups, which avoids a benchmark
# dominated by near-identical dishes.
CATEGORY_QUOTAS = {
    "bakery": 2,
    "cafe": 2,
    "pub": 2,
    "restaurant": 4,
}
MAX_DATA_URL_LENGTH = 3_800_000
FONT_CANDIDATES = (
    Path("C:/Windows/Fonts/malgunbd.ttf"),
    Path("C:/Windows/Fonts/malgun.ttf"),
    Path("C:/Windows/Fonts/NotoSansKR-Bold.ttf"),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--images-dir", type=Path, default=DEFAULT_IMAGES_DIR)
    parser.add_argument("--metadata-csv", type=Path)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--case-limit", type=int, default=10)
    parser.add_argument(
        "--llm-model",
        choices=[model.value for model in AdModel],
        action="append",
    )
    parser.add_argument(
        "--vision-model",
        choices=[model.value for model in VisionModel],
        action="append",
    )
    parser.add_argument(
        "--image-model",
        choices=[model.value for model in ImageModel],
        action="append",
    )
    parser.add_argument(
        "--matrix-mode",
        choices=("full", "one-factor"),
        default="one-factor",
        help=(
            "full runs the Cartesian product. one-factor changes one model family "
            "at a time around the first model in each list."
        ),
    )
    parser.add_argument("--max-runs", type=int)
    parser.add_argument("--concurrency", type=int, default=1)
    parser.add_argument(
        "--local-llm-concurrency",
        type=int,
        default=1,
        help="Maximum simultaneous trials using an Ollama LLM.",
    )
    parser.add_argument(
        "--local-image-concurrency",
        type=int,
        default=1,
        help="Maximum simultaneous trials using a local ComfyUI image model.",
    )
    parser.add_argument("--image-width", type=int, default=768)
    parser.add_argument("--image-height", type=int, default=1024)
    parser.add_argument(
        "--image-provider-override",
        choices=("huggingface", "comfyui"),
        help="Override BRANDMATE_IMAGE_PROVIDER for this benchmark process only.",
    )
    parser.add_argument(
        "--disable-vision-analysis",
        action="store_true",
        help="Keep the reference image for image generation but skip Vision analysis.",
    )
    parser.add_argument(
        "--save-text-overlay",
        action="store_true",
        help="Also save a PNG with the generated Instagram headline rendered on it.",
    )
    parser.add_argument(
        "--compare-meme",
        action="store_true",
        help=(
            "Run paired without_meme and with_meme trials for every case and "
            "model combination."
        ),
    )
    parser.add_argument(
        "--trend-card-id",
        default=DEFAULT_TREND_CARD_ID,
        help="TrendCard id used by the with_meme arm.",
    )
    parser.add_argument(
        "--render-overlays-from-run",
        type=Path,
        help="Add text-overlay PNGs to an already completed benchmark run without model calls.",
    )
    parser.add_argument(
        "--copy-source-images-from-run",
        type=Path,
        help="Copy the exact source photo into every completed trial directory.",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Actually call models. Without this flag only manifest and plan are saved.",
    )
    return parser.parse_args()


def find_metadata_csv(images_dir: Path, explicit_path: Path | None = None) -> Path:
    if explicit_path:
        if not explicit_path.is_file():
            raise FileNotFoundError(explicit_path)
        return explicit_path
    candidates = sorted(images_dir.glob("prompt_metadata*.csv"))
    if not candidates:
        raise FileNotFoundError(f"No prompt_metadata*.csv found under {images_dir}")
    return candidates[0]


def load_metadata(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as file:
        rows = list(csv.DictReader(file))
    required = {
        "final_image_id",
        "product_name",
        "business_category",
        "product_group",
        "caption",
        "prompt_keywords",
    }
    missing = required - set(rows[0] if rows else {})
    if missing:
        raise ValueError(f"Metadata is missing required columns: {sorted(missing)}")
    return rows


def _available_rows(
    rows: list[dict[str, str]],
    images_dir: Path,
) -> list[dict[str, str]]:
    available: list[dict[str, str]] = []
    for row in rows:
        image_id = row["final_image_id"].strip()
        path = images_dir / f"{image_id}.jpg"
        if path.is_file() and row["product_name"].strip():
            resolved = path.resolve()
            try:
                stored_path = resolved.relative_to(PROJECT_ROOT).as_posix()
            except ValueError:
                stored_path = str(resolved)
            available.append({**row, "local_image_path": stored_path})
    return available


def _pick_distinct_groups(
    rows: list[dict[str, str]],
    count: int,
) -> list[dict[str, str]]:
    ordered = sorted(rows, key=lambda row: row["final_image_id"])
    selected: list[dict[str, str]] = []
    used_groups: set[str] = set()
    for row in ordered:
        group = row["product_group"].strip()
        if group and group not in used_groups:
            selected.append(row)
            used_groups.add(group)
        if len(selected) == count:
            return selected
    for row in ordered:
        if row not in selected:
            selected.append(row)
        if len(selected) == count:
            break
    return selected


def select_cases(
    rows: list[dict[str, str]],
    images_dir: Path,
    limit: int = 10,
) -> list[dict[str, Any]]:
    if limit < 1:
        raise ValueError("case-limit must be at least 1.")
    available = _available_rows(rows, images_dir)
    if len(available) < limit:
        raise ValueError(f"Only {len(available)} matched photos are available; need {limit}.")

    available_by_id = {row["final_image_id"]: row for row in available}
    preferred = [available_by_id[image_id] for image_id in DEFAULT_CASE_IDS if image_id in available_by_id]
    selected: list[dict[str, str]] = preferred[:limit] if len(preferred) >= limit else []

    if not selected:
        grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
        for row in available:
            grouped[row["business_category"].strip()].append(row)
        for category, quota in CATEGORY_QUOTAS.items():
            selected.extend(_pick_distinct_groups(grouped.get(category, []), quota))

    if len(selected) < limit:
        selected_ids = {row["final_image_id"] for row in selected}
        remaining = [row for row in available if row["final_image_id"] not in selected_ids]
        selected.extend(_pick_distinct_groups(remaining, limit - len(selected)))
    selected = selected[:limit]

    cases = []
    for index, row in enumerate(selected, start=1):
        product_name = row["product_name"].strip()
        caption = row["caption"].strip()
        keywords = row["prompt_keywords"].strip()
        style_hint = row.get("visual_style_hint", "").strip()
        # Dataset captions are retained below for auditing, but are intentionally
        # excluded from model input. Some rows describe the wrong food (for example,
        # scallop sushi as a banana), and food codes/style labels are internal data
        # rather than customer-facing selling points. Vision analysis is the visual
        # source of truth for every benchmark request.
        features = [f"업로드 사진 속 {product_name}의 실제 형태와 색감을 중심으로 소개"]
        request = {
            "business_name": f"{product_name} 테스트 가게",
            "business_type": row["business_category"].strip(),
            "situation": "new_menu",
            "age_groups": ["twenties", "thirties"],
            "target_audiences": ["office_workers", "couples"],
            "tone": "emotional",
            "product_names": [product_name],
            "features": features,
            "channel": AdChannel.INSTAGRAM.value,
            "promotion": None,
            "required_terms": [product_name],
            "prohibited_terms": ["최고", "무조건", "무료"],
            # product_group is an internal English taxonomy value (for example
            # "bread") and must not leak into Korean customer-facing hashtags.
            "interests": ["맛집", product_name],
            "audience_detail": "음식 사진을 보고 방문이나 주문을 고려하는 인스타그램 이용자",
            "additional_request": (
                "업로드 사진에 없는 재료나 효능을 만들지 말고, 음식명과 실제 사진을 "
                "중심으로 자연스러운 한국어 인스타그램 광고를 작성하세요."
            ),
        }
        cases.append(
            {
                "id": f"food-{index:02d}-{row['final_image_id']}",
                "image_id": row["final_image_id"],
                "image_path": row["local_image_path"],
                "food": {
                    "product_name": product_name,
                    "original_food_name": row.get("original_food_name", "").strip(),
                    "business_category": row["business_category"].strip(),
                    "product_group": row["product_group"].strip(),
                    "caption": caption,
                    "prompt_keywords": keywords,
                    "ad_use_case": row.get("ad_use_case", "").strip(),
                    "visual_style_hint": style_hint,
                },
                "instagram_request": request,
            }
        )
    return cases


def write_manifest(
    path: Path,
    cases: list[dict[str, Any]],
    metadata_path: Path,
) -> None:
    resolved_metadata = metadata_path.resolve()
    try:
        stored_metadata = resolved_metadata.relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        stored_metadata = str(resolved_metadata)
    payload = {
        "version": 1,
        "channel": AdChannel.INSTAGRAM.value,
        "selection": {
            "method": "category quotas plus distinct product groups",
            "category_quotas": CATEGORY_QUOTAS,
            "metadata": stored_metadata,
        },
        "cases": cases,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def selected_enums(raw_values: list[str] | None, enum_type, defaults: tuple) -> list:
    return [enum_type(value) for value in raw_values] if raw_values else list(defaults)


def model_combinations(args: argparse.Namespace) -> list[dict[str, Any]]:
    llms = selected_enums(args.llm_model, AdModel, DEFAULT_LLM_MODELS)
    visions = selected_enums(args.vision_model, VisionModel, DEFAULT_VISION_MODELS)
    images = selected_enums(args.image_model, ImageModel, DEFAULT_IMAGE_MODELS)
    if args.matrix_mode == "full":
        combinations = list(product(llms, visions, images))
    else:
        baseline = (llms[0], visions[0], images[0])
        combinations = [baseline]
        combinations.extend((model, visions[0], images[0]) for model in llms[1:])
        combinations.extend((llms[0], model, images[0]) for model in visions[1:])
        combinations.extend((llms[0], visions[0], model) for model in images[1:])
    # Preserve order while removing any accidental duplicate combination.
    unique = list(dict.fromkeys(combinations))
    return [
        {"llm_model": llm, "vision_model": vision, "image_model": image}
        for llm, vision, image in unique
    ]


def build_plan(
    cases: list[dict[str, Any]],
    combinations: list[dict[str, Any]],
    max_runs: int | None = None,
    *,
    compare_meme: bool = False,
    trend_card_id: str = DEFAULT_TREND_CARD_ID,
) -> list[dict[str, str]]:
    plan = []
    base_items = product(cases, combinations)
    arms: tuple[tuple[str | None, bool | None, str | None], ...] = (
        (
            ("without_meme", False, None),
            ("with_meme", True, trend_card_id),
        )
        if compare_meme
        else ((None, None, None),)
    )
    for (case, combination), (meme_arm, use_trend_card, selected_card_id) in product(
        base_items, arms
    ):
        values = (
            case["id"],
            *((meme_arm,) if meme_arm else ()),
            combination["llm_model"].value,
            combination["vision_model"].value,
            combination["image_model"].value,
        )
        trial_id = "__".join(
            value.replace("/", "_").replace(":", "_") for value in values
        )
        plan.append(
            {
                "trial_id": trial_id,
                "case_id": case["id"],
                "image_id": case["image_id"],
                "product_name": case["food"]["product_name"],
                "source_image": case["image_path"],
                "llm_model": combination["llm_model"].value,
                "vision_model": combination["vision_model"].value,
                "image_model": combination["image_model"].value,
                **(
                    {
                        "meme_arm": meme_arm,
                        "use_trend_card": use_trend_card,
                        "trend_card_id": selected_card_id,
                    }
                    if meme_arm
                    else {}
                ),
            }
        )
    return plan[:max_runs] if max_runs else plan


def normalized_image_data_url(path: Path) -> tuple[str, dict[str, Any]]:
    """Return an RGB JPEG data URL without changing the source image."""
    with Image.open(path) as source:
        original_format = source.format or "unknown"
        original_size = source.size
        image = ImageOps.exif_transpose(source).convert("RGB")
        image.thumbnail((1024, 1024), Image.Resampling.LANCZOS)
        quality = 90
        while quality >= 55:
            output = BytesIO()
            image.save(output, format="JPEG", quality=quality, optimize=True)
            encoded = base64.b64encode(output.getvalue()).decode("ascii")
            data_url = f"data:image/jpeg;base64,{encoded}"
            if len(data_url) <= MAX_DATA_URL_LENGTH:
                return data_url, {
                    "source_format": original_format,
                    "source_size": list(original_size),
                    "model_input_size": list(image.size),
                    "jpeg_quality": quality,
                    "data_url_length": len(data_url),
                    "source_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                }
            quality -= 5
    raise ValueError(f"Could not fit image under {MAX_DATA_URL_LENGTH} data URL chars: {path}")


def resolve_project_path(path_value: str) -> Path:
    path = Path(path_value)
    return path if path.is_absolute() else PROJECT_ROOT / path


def _load_overlay_font(size: int) -> ImageFont.FreeTypeFont:
    for path in FONT_CANDIDATES:
        if path.is_file():
            return ImageFont.truetype(str(path), size=size)
    raise FileNotFoundError(
        "No Korean font was found. Expected Malgun Gothic or Noto Sans KR."
    )


def _wrap_overlay_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.FreeTypeFont,
    max_width: int,
    max_lines: int,
) -> list[str]:
    clean = " ".join(str(text).split())
    if not clean:
        return []
    lines: list[str] = []
    current = ""
    for character in clean:
        candidate = current + character
        width = draw.textbbox((0, 0), candidate, font=font)[2]
        if current and width > max_width:
            lines.append(current.rstrip())
            current = character.lstrip()
            if len(lines) == max_lines:
                break
        else:
            current = candidate
    if current and len(lines) < max_lines:
        lines.append(current.rstrip())
    if len(lines) == max_lines and "".join(lines) != clean.replace(" ", ""):
        last = lines[-1]
        while last and draw.textbbox((0, 0), f"{last}…", font=font)[2] > max_width:
            last = last[:-1]
        lines[-1] = f"{last.rstrip()}…"
    return lines


def _fit_overlay_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    max_width: int,
    max_size: int,
    min_size: int,
    max_lines: int = 2,
) -> tuple[ImageFont.FreeTypeFont, list[str]]:
    for size in range(max_size, min_size - 1, -2):
        font = _load_overlay_font(size)
        lines = _wrap_overlay_text(draw, text, font, max_width, max_lines)
        if lines and "…" not in lines[-1]:
            return font, lines
    font = _load_overlay_font(min_size)
    return font, _wrap_overlay_text(draw, text, font, max_width, max_lines)


def render_text_overlay(
    image_path: Path,
    output_path: Path,
    headline: str,
    subtitle: str = "",
) -> Path:
    """Render Korean Instagram copy over a generated image, preserving the source."""
    # The Korean Windows font used for poster text has no color-emoji glyphs.
    # Replace emoji symbols with a supported heart instead of rendering tofu boxes.
    headline = "".join(
        "♥" if unicodedata.category(character) == "So" else character
        for character in headline
    )
    with Image.open(image_path) as source:
        image = ImageOps.exif_transpose(source).convert("RGBA")
    width, height = image.size
    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    gradient_start = int(height * 0.52)
    gradient_height = max(1, height - gradient_start)
    for y in range(gradient_start, height):
        ratio = (y - gradient_start) / gradient_height
        alpha = int(205 * ratio**1.45)
        draw.line((0, y, width, y), fill=(24, 18, 14, alpha))

    padding = max(24, round(width * 0.075))
    max_width = width - padding * 2
    headline_font, headline_lines = _fit_overlay_text(
        draw,
        headline,
        max_width,
        max_size=max(44, round(width * 0.064)),
        min_size=max(28, round(width * 0.036)),
    )
    subtitle_font, subtitle_lines = _fit_overlay_text(
        draw,
        subtitle,
        max_width,
        max_size=max(22, round(width * 0.032)),
        min_size=max(17, round(width * 0.022)),
        max_lines=1,
    ) if subtitle.strip() else (None, [])
    headline_height = round(headline_font.size * 1.28)
    subtitle_height = round(subtitle_font.size * 1.35) if subtitle_font else 0
    gap = round(width * 0.02) if subtitle_lines else 0
    total_height = len(headline_lines) * headline_height + len(subtitle_lines) * subtitle_height + gap
    y = height - padding - total_height

    for line in headline_lines:
        stroke_width = max(1, round(width * 0.002))
        if "♥" in line:
            before_heart, _, after_heart = line.partition("♥")
            draw.text(
                (padding, y),
                before_heart,
                font=headline_font,
                fill=(255, 255, 255, 255),
                stroke_width=stroke_width,
                stroke_fill=(0, 0, 0, 120),
            )
            heart_x = padding + draw.textlength(before_heart, font=headline_font)
            draw.text(
                (heart_x, y),
                "♥",
                font=headline_font,
                fill=(255, 214, 64, 255),
                stroke_width=stroke_width,
                stroke_fill=(0, 0, 0, 120),
            )
            if after_heart:
                after_x = heart_x + draw.textlength("♥", font=headline_font)
                draw.text(
                    (after_x, y),
                    after_heart,
                    font=headline_font,
                    fill=(255, 255, 255, 255),
                    stroke_width=stroke_width,
                    stroke_fill=(0, 0, 0, 120),
                )
        else:
            draw.text(
                (padding, y),
                line,
                font=headline_font,
                fill=(255, 255, 255, 255),
                stroke_width=stroke_width,
                stroke_fill=(0, 0, 0, 120),
            )
        y += headline_height
    if subtitle_lines and subtitle_font:
        y += gap
        for line in subtitle_lines:
            draw.text(
                (padding, y),
                line,
                font=subtitle_font,
                fill=(255, 255, 255, 225),
                stroke_width=max(1, round(width * 0.0015)),
                stroke_fill=(0, 0, 0, 100),
            )
            y += subtitle_height

    output_path.parent.mkdir(parents=True, exist_ok=True)
    Image.alpha_composite(image, overlay).convert("RGB").save(
        output_path,
        format="PNG",
        optimize=True,
    )
    return output_path


def render_existing_run_overlays(run_dir: Path) -> list[dict[str, str]]:
    run_dir = run_dir.resolve()
    trials_dir = run_dir / "trials"
    if not trials_dir.is_dir():
        raise FileNotFoundError(f"Benchmark trials directory not found: {trials_dir}")
    records: list[dict[str, str]] = []
    for trial_dir in sorted(path for path in trials_dir.iterdir() if path.is_dir()):
        result_path = trial_dir / "result.json"
        if not result_path.is_file():
            continue
        payload = json.loads(result_path.read_text(encoding="utf-8"))
        source_candidates = [
            path
            for path in trial_dir.glob("generated.*")
            if path.name != "generated-with-copy.png"
        ]
        if not source_candidates:
            continue
        recommendation = payload.get("channel_recommendation") or payload.get("copy", {}).get(
            "channel_recommendation", {}
        )
        copy_payload = payload.get("copy", {})
        headline = (
            recommendation.get("overlay_headline")
            or recommendation.get("publish_title")
            or next(iter(copy_payload.get("headlines", [])), "")
        )
        products = payload.get("input", {}).get("product_names", [])
        if not headline:
            continue
        output_path = trial_dir / "generated-with-copy.png"
        render_text_overlay(source_candidates[0], output_path, headline)
        records.append(
            {
                "trial_id": trial_dir.name,
                "headline": headline,
                "subtitle": "",
                "source_image": str(source_candidates[0]),
                "image_with_copy": str(output_path),
            }
        )
    manifest_path = run_dir / "text-overlay-manifest.json"
    manifest_path.write_text(
        json.dumps(records, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"Text overlays: {len(records)}")
    print(f"Overlay manifest: {manifest_path}")
    return records


def copy_existing_run_source_images(run_dir: Path) -> list[dict[str, str]]:
    """Copy each planned source photo beside its completed trial artifacts."""
    run_dir = run_dir.resolve()
    plan_path = run_dir / "plan.json"
    if not plan_path.is_file():
        raise FileNotFoundError(f"Benchmark plan not found: {plan_path}")
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    records: list[dict[str, str]] = []
    for item in plan:
        trial_dir = run_dir / "trials" / item["trial_id"]
        source_path = resolve_project_path(item["source_image"]).resolve()
        if not trial_dir.is_dir() or not source_path.is_file():
            continue
        destination = trial_dir / f"source-original-{source_path.name}"
        shutil.copy2(source_path, destination)
        source_hash = hashlib.sha256(source_path.read_bytes()).hexdigest()
        copied_hash = hashlib.sha256(destination.read_bytes()).hexdigest()
        if source_hash != copied_hash:
            destination.unlink(missing_ok=True)
            raise OSError(f"Source image copy hash mismatch: {source_path}")
        records.append(
            {
                "trial_id": item["trial_id"],
                "image_id": item["image_id"],
                "source_image": str(source_path),
                "saved_source_image": str(destination),
                "sha256": source_hash,
            }
        )
    manifest_path = run_dir / "source-image-manifest.json"
    manifest_path.write_text(
        json.dumps(records, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"Source images: {len(records)}")
    print(f"Source manifest: {manifest_path}")
    return records


def build_request(
    case: dict[str, Any],
    plan_item: dict[str, str],
    data_url: str,
    args: argparse.Namespace,
) -> AdContentRequest:
    copy_payload = {
        **case["instagram_request"],
        "model": plan_item["llm_model"],
        "channel": AdChannel.INSTAGRAM.value,
    }
    if "use_trend_card" in plan_item:
        copy_payload["use_trend_card"] = plan_item["use_trend_card"]
        copy_payload["trend_card_id"] = plan_item.get("trend_card_id")
    return AdContentRequest(
        copy=copy_payload,
        use_vision_analysis=not args.disable_vision_analysis,
        vision_model=VisionModel(plan_item["vision_model"]),
        image_model=ImageModel(plan_item["image_model"]),
        image_width=args.image_width,
        image_height=args.image_height,
        reference_image_data_url=data_url,
    )


def _extension(media_type: str) -> str:
    return {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}.get(
        media_type.lower(), "png"
    )


def _append_jsonl(path: Path, record: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(record, ensure_ascii=False) + "\n")


async def execute_trial(
    case: dict[str, Any],
    plan_item: dict[str, str],
    args: argparse.Namespace,
    run_dir: Path,
    jsonl_path: Path,
    semaphore: asyncio.Semaphore,
    local_llm_semaphore: asyncio.Semaphore,
    local_image_semaphore: asyncio.Semaphore,
    uses_comfyui: bool,
) -> dict[str, Any]:
    async with AsyncExitStack() as resources:
        if plan_item["llm_model"].startswith("local/"):
            await resources.enter_async_context(local_llm_semaphore)
        if uses_comfyui and not plan_item["image_model"].startswith("openai/"):
            await resources.enter_async_context(local_image_semaphore)
        # Acquire the broad concurrency slot last. Trials waiting for a scarce
        # local runtime must not occupy slots that hosted API trials can use.
        await resources.enter_async_context(semaphore)

        started = perf_counter()
        record: dict[str, Any] = {**plan_item, "success": False}
        try:
                data_url, preprocessing = normalized_image_data_url(
                    resolve_project_path(case["image_path"])
                )
                request = build_request(case, plan_item, data_url, args)
                # Lazy import keeps manifest generation usable even when server-only
                # dependencies (database driver, credentials) are not installed.
                from app.extensions.ad_content.router import generate_content

                response = await generate_content(request)
                output_dir = run_dir / "trials" / plan_item["trial_id"]
                output_dir.mkdir(parents=True, exist_ok=True)
                source_path = resolve_project_path(case["image_path"]).resolve()
                saved_source_path = output_dir / f"source-original-{source_path.name}"
                shutil.copy2(source_path, saved_source_path)
                image_path = output_dir / f"generated.{_extension(response.image.media_type)}"
                image_path.write_bytes(base64.b64decode(response.image.image_base64))
                copy_result = response.copy_result
                image_with_copy = None
                if args.save_text_overlay:
                    recommendation = copy_result.channel_recommendation
                    overlay_headline = (
                        recommendation.overlay_headline
                        or recommendation.publish_title
                        or copy_result.headlines[0]
                    )
                image_with_copy = render_text_overlay(
                    image_path,
                    output_dir / "generated-with-copy.png",
                    overlay_headline,
                )
                response_payload = response.model_dump(mode="json", by_alias=True)
                response_payload["image"]["image_base64"] = "[saved_to_generated_image]"
                (output_dir / "result.json").write_text(
                    json.dumps(response_payload, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                fallback_used = any(
                    "fallback copy" in note.lower() for note in copy_result.safety_notes
                )
                record.update(
                    success=True,
                    preprocessing=preprocessing,
                    copy_model_routed=copy_result.routed_model,
                    copy_attempts=copy_result.attempts,
                    copy_output_repaired=copy_result.output_repaired,
                    fallback_copy_used=fallback_used,
                    copy_safety_notes=copy_result.safety_notes,
                    image_model_actual=response.image.model,
                    copy_latency_ms=copy_result.latency_ms,
                    image_latency_ms=response.image.latency_ms,
                    context_adherence_score=context_adherence_score(
                        request.copy_request, copy_result
                    ),
                    tone_manner_proxy_score=tone_manner_proxy_score(
                        request.copy_request, copy_result
                    ),
                    hashtag_compliance_rate=hashtag_compliance_rate(copy_result),
                    headline_diversity_score=headline_diversity_score(copy_result),
                    image_prompt_english=is_english_image_prompt(copy_result),
                    hallucination_terms=hallucination_terms(
                        request.copy_request, copy_result
                    ),
                    toxicity_terms=toxicity_terms(copy_result),
                    generated_image=str(image_path.resolve()),
                    saved_source_image=str(saved_source_path.resolve()),
                    generated_image_with_copy=(
                        str(image_with_copy.resolve()) if image_with_copy else None
                    ),
                    result_json=str((output_dir / "result.json").resolve()),
                    headline=copy_result.headlines[0],
                    instagram_caption=copy_result.channel_recommendation.caption,
                    validation=response.validation,
                )
        except Exception as error:  # noqa: BLE001 - benchmark continues after failures
            record.update(error_type=type(error).__name__, error=str(error))
        record["wall_latency_ms"] = round((perf_counter() - started) * 1000, 2)
        _append_jsonl(jsonl_path, record)
        status = "OK" if record["success"] else "FAIL"
        print(
            f"[{status}] {record['trial_id']} - {record['wall_latency_ms']}ms",
            flush=True,
        )
        return record


def _average(records: list[dict[str, Any]], key: str) -> float | None:
    values = [float(record[key]) for record in records if record.get(key) is not None]
    return round(mean(values), 4) if values else None


def aggregate(records: list[dict[str, Any]], dimension: str) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        grouped[record[dimension]].append(record)
    summaries = []
    for model, trials in grouped.items():
        successes = [record for record in trials if record["success"]]
        summaries.append(
            {
                "model": model,
                "trials": len(trials),
                "successes": len(successes),
                "success_rate_percent": round(len(successes) / len(trials) * 100, 2),
                "mean_wall_latency_ms": _average(successes, "wall_latency_ms"),
                "mean_context_adherence": _average(successes, "context_adherence_score"),
                "mean_hashtag_compliance": _average(successes, "hashtag_compliance_rate"),
                "mean_headline_diversity": _average(successes, "headline_diversity_score"),
                "native_copy_success_rate_percent": (
                    round(
                        sum(not r.get("fallback_copy_used", False) for r in successes)
                        / len(successes)
                        * 100,
                        2,
                    )
                    if successes
                    else None
                ),
                "fallback_copy_rate_percent": (
                    round(
                        sum(bool(r.get("fallback_copy_used")) for r in successes)
                        / len(successes)
                        * 100,
                        2,
                    )
                    if successes
                    else None
                ),
                "mean_copy_attempts": _average(successes, "copy_attempts"),
                "valid_image_rate_percent": (
                    round(
                        sum(bool(r.get("validation", {}).get("image_valid")) for r in successes)
                        / len(successes)
                        * 100,
                        2,
                    )
                    if successes
                    else None
                ),
            }
        )
    return sorted(summaries, key=lambda item: item["model"])


def write_manual_review_csv(path: Path, records: list[dict[str, Any]]) -> None:
    fields = [
        "trial_id",
        "case_id",
        "product_name",
        "source_image",
        "saved_source_image",
        "llm_model",
        "vision_model",
        "image_model",
        "meme_arm",
        "trend_card_id",
        "generated_image",
        "generated_image_with_copy",
        "food_identity_1_to_5",
        "reference_similarity_1_to_5",
        "korean_copy_quality_1_to_5",
        "instagram_suitability_1_to_5",
        "visual_quality_1_to_5",
        "review_note",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        for record in records:
            if record["success"]:
                writer.writerow({field: record.get(field, "") for field in fields})


async def run(args: argparse.Namespace) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if args.render_overlays_from_run:
        records = render_existing_run_overlays(args.render_overlays_from_run)
        return 0 if records else 1
    if args.copy_source_images_from_run:
        records = copy_existing_run_source_images(args.copy_source_images_from_run)
        return 0 if records else 1
    if args.image_provider_override:
        from app.core.config import settings

        settings.image_provider = args.image_provider_override
    if args.concurrency < 1:
        raise ValueError("concurrency must be at least 1.")
    if args.local_llm_concurrency < 1:
        raise ValueError("local-llm-concurrency must be at least 1.")
    if args.local_image_concurrency < 1:
        raise ValueError("local-image-concurrency must be at least 1.")
    if args.max_runs is not None and args.max_runs < 1:
        raise ValueError("max-runs must be at least 1.")

    images_dir = args.images_dir.resolve()
    metadata_path = find_metadata_csv(images_dir, args.metadata_csv)
    cases = select_cases(load_metadata(metadata_path), images_dir, args.case_limit)
    write_manifest(args.manifest, cases, metadata_path)
    combinations = model_combinations(args)
    plan = build_plan(
        cases,
        combinations,
        args.max_runs,
        compare_meme=args.compare_meme,
        trend_card_id=args.trend_card_id,
    )

    timestamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    run_dir = args.output_dir / timestamp
    run_dir.mkdir(parents=True, exist_ok=True)
    plan_path = run_dir / "plan.json"
    plan_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    counts = Counter(item["product_name"] for item in plan)
    print(f"Cases: {len(cases)}, combinations per case: {len(combinations)}")
    print(f"Planned trials: {len(plan)} ({len(counts)} foods)")
    print(f"Manifest: {args.manifest.resolve()}")
    print(f"Plan: {plan_path.resolve()}")
    if not args.execute:
        print("Dry run complete. Add --execute to call the configured runtimes.")
        return 0

    case_map = {case["id"]: case for case in cases}
    jsonl_path = run_dir / "trials.jsonl"
    semaphore = asyncio.Semaphore(args.concurrency)
    local_llm_semaphore = asyncio.Semaphore(args.local_llm_concurrency)
    local_image_semaphore = asyncio.Semaphore(args.local_image_concurrency)
    from app.core.config import settings

    uses_comfyui = settings.image_provider == "comfyui"
    records = await asyncio.gather(
        *(
            execute_trial(
                case_map[item["case_id"]],
                item,
                args,
                run_dir,
                jsonl_path,
                semaphore,
                local_llm_semaphore,
                local_image_semaphore,
                uses_comfyui,
            )
            for item in plan
        )
    )
    if args.matrix_mode == "one-factor":
        baseline = combinations[0]
        llm_records = [
            record
            for record in records
            if record["vision_model"] == baseline["vision_model"].value
            and record["image_model"] == baseline["image_model"].value
        ]
        vision_records = [
            record
            for record in records
            if record["llm_model"] == baseline["llm_model"].value
            and record["image_model"] == baseline["image_model"].value
        ]
        image_records = [
            record
            for record in records
            if record["llm_model"] == baseline["llm_model"].value
            and record["vision_model"] == baseline["vision_model"].value
        ]
    else:
        llm_records = vision_records = image_records = records
    report = {
        "generated_at": datetime.now(UTC).isoformat(),
        "matrix_mode": args.matrix_mode,
        "case_count": len(cases),
        "combination_count": len(combinations),
        "trial_count": len(records),
        "success_count": sum(record["success"] for record in records),
        "by_llm_model": aggregate(llm_records, "llm_model"),
        "by_vision_model": aggregate(vision_records, "vision_model"),
        "by_image_model": aggregate(image_records, "image_model"),
        "by_meme_arm": (
            aggregate(records, "meme_arm")
            if any(record.get("meme_arm") for record in records)
            else []
        ),
        "trials": records,
    }
    report_path = run_dir / "report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    write_manual_review_csv(run_dir / "manual-review.csv", records)
    print(f"Report: {report_path.resolve()}")
    print(f"Success: {report['success_count']}/{report['trial_count']}")
    return 0 if report["success_count"] == report["trial_count"] else 1


def main() -> None:
    raise SystemExit(asyncio.run(run(parse_args())))


if __name__ == "__main__":
    main()
