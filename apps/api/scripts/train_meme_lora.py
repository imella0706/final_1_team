"""Validate seed data and train a Qwen2.5-7B meme-copy LoRA adapter.

This is an offline research utility. It never runs as part of the FastAPI service.
Run with ``--validate-only`` before installing the optional GPU dependencies.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import UTC, datetime
from importlib.metadata import version as package_version
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.modules.ad_copy.output_validator import validate_copy_output
from app.modules.ad_copy.prompt import (
    AGE_GROUP_LABELS,
    BUSINESS_TYPE_LABELS,
    CHANNEL_LABELS,
    PROMPT_VERSION,
    SITUATION_LABELS,
    TARGET_LABELS,
    TONE_LABELS,
)
from app.modules.ad_copy.schemas import AdCopyContent, AdCopyRequest
from app.modules.ad_copy.service import build_prompt_messages
from app.modules.ad_copy.trend_context import load_trend_card


BASE_MODEL = "Qwen/Qwen2.5-7B-Instruct"
MEME_ID = "gogumafarm:1bf390d89536004b"
API_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = API_ROOT.parents[1]
DEFAULT_TRAIN_FILE = API_ROOT / "evals" / "lora" / "train.seed.jsonl"
DEFAULT_VALIDATION_FILE = API_ROOT / "evals" / "lora" / "validation.seed.jsonl"
DEFAULT_COMPARISON_FILES = [
    API_ROOT / "evals" / "ad_copy_cases.json",
    API_ROOT / "evals" / "meme_ad_copy_cases.json",
    API_ROOT / "evals" / "few_shot_examples.json",
]
DEFAULT_TREND_CARD_FILE = PROJECT_ROOT / "gather_data" / "trendcard.json"
IMMUTABLE_REVISION_PATTERN = re.compile(r"^[0-9a-f]{40}$")


class SeedMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    split: Literal["train", "validation"]
    meme_id: str
    source_kind: Literal["assistant_authored_scaffold", "human_curated"]
    source_lineage_id: str = Field(min_length=1)
    business_name: str = Field(min_length=1)
    product_names: list[str] = Field(min_length=1)
    business_signature: str = Field(min_length=1)
    product_signatures: list[str] = Field(min_length=1)
    template_family: str = Field(min_length=1)
    review_status: Literal["seed_needs_review", "reviewed"]
    rights_review_status: Literal["seed_needs_review", "reviewed"]


class GoldCopy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    headline: str = Field(min_length=1, max_length=100)
    body: str = Field(min_length=1, max_length=2000)
    cta: str = Field(min_length=1, max_length=200)
    hashtags: list[str] = Field(min_length=1, max_length=10)
    core_message: str = Field(min_length=1, max_length=500)
    customer_emotion: str = Field(min_length=1, max_length=300)
    marketing_angle: str = Field(min_length=1, max_length=500)
    camera_angle: str = "45_degree_close_up"
    composition: str = "two_product_set"
    lighting: str = "soft_natural_window_light"
    background: str = "minimal_korean_local_cafe"
    color_palette: list[str] = Field(default_factory=lambda: ["warm_beige_cream"])
    depth_of_field: str = "shallow_depth_of_field"
    empty_space: str = "top_20_percent"


class SeedExample(BaseModel):
    model_config = ConfigDict(extra="forbid")

    example_id: str = Field(min_length=1)
    metadata: SeedMetadata
    request: dict[str, Any]
    gold: GoldCopy


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--train-file", type=Path, default=DEFAULT_TRAIN_FILE)
    parser.add_argument(
        "--validation-file",
        type=Path,
        default=DEFAULT_VALIDATION_FILE,
    )
    parser.add_argument(
        "--overlap-file",
        action="append",
        type=Path,
        default=[],
        help=(
            "Additional JSON/JSONL corpus whose business and product names must not "
            "overlap. May be repeated; the standard ad-copy eval file is always checked."
        ),
    )
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Validate data, schema, and leakage guards without importing Torch or TRL.",
    )
    parser.add_argument(
        "--allow-unreviewed-seeds",
        action="store_true",
        help="Permit scaffold-only seed rows. Use only for an engineering smoke run.",
    )
    parser.add_argument(
        "--base-revision",
        help="Required immutable 40-character Hugging Face commit SHA for training.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="New, empty directory for adapter checkpoints and the run manifest.",
    )
    parser.add_argument("--epochs", type=float, default=3.0)
    parser.add_argument("--learning-rate", type=float, default=2e-4)
    parser.add_argument("--max-length", type=int, default=16384)
    parser.add_argument("--gradient-accumulation-steps", type=int, default=8)
    parser.add_argument("--lora-r", type=int, default=16)
    parser.add_argument("--lora-alpha", type=int, default=32)
    parser.add_argument("--lora-dropout", type=float, default=0.05)
    parser.add_argument("--seed", type=int, default=42)
    return parser.parse_args()


def _signature(value: str) -> str:
    return re.sub(r"[^0-9a-z가-힣]+", "", value.casefold())


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_jsonl(path: Path, expected_split: str) -> list[SeedExample]:
    if not path.is_file():
        raise SystemExit(f"Seed file does not exist: {path}")

    examples: list[SeedExample] = []
    for line_number, raw_line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        if not raw_line.strip():
            continue
        try:
            raw = json.loads(raw_line)
            example = SeedExample.model_validate(raw)
        except (json.JSONDecodeError, ValidationError) as error:
            raise SystemExit(f"Invalid seed row {path}:{line_number}: {error}") from error
        if example.metadata.split != expected_split:
            raise SystemExit(
                f"Unexpected split at {path}:{line_number}: "
                f"{example.metadata.split!r}, expected {expected_split!r}"
            )
        examples.append(example)
    if not examples:
        raise SystemExit(f"Seed file is empty: {path}")
    return examples


def _collect_named_values(payload: Any) -> tuple[set[str], set[str], set[str]]:
    businesses: set[str] = set()
    products: set[str] = set()
    lineages: set[str] = set()

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            business_name = value.get("business_name")
            if isinstance(business_name, str) and business_name.strip():
                businesses.add(_signature(business_name))
            product_names = value.get("product_names")
            if isinstance(product_names, list):
                products.update(
                    _signature(item)
                    for item in product_names
                    if isinstance(item, str) and item.strip()
                )
            lineage = value.get("source_lineage_id")
            if isinstance(lineage, str) and lineage.strip():
                lineages.add(lineage.strip())
            for nested in value.values():
                visit(nested)
        elif isinstance(value, list):
            for nested in value:
                visit(nested)

    visit(payload)
    return businesses, products, lineages


def _load_comparison_keys(paths: list[Path]) -> tuple[set[str], set[str], set[str]]:
    businesses: set[str] = set()
    products: set[str] = set()
    lineages: set[str] = set()
    for path in paths:
        if not path.is_file():
            raise SystemExit(f"Overlap comparison file does not exist: {path}")
        try:
            if path.suffix.casefold() == ".jsonl":
                payload: Any = [
                    json.loads(line)
                    for line in path.read_text(encoding="utf-8").splitlines()
                    if line.strip()
                ]
            else:
                payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            raise SystemExit(f"Invalid overlap comparison file {path}: {error}") from error
        found_businesses, found_products, found_lineages = _collect_named_values(payload)
        businesses.update(found_businesses)
        products.update(found_products)
        lineages.update(found_lineages)
    return businesses, products, lineages


def _validate_metadata(example: SeedExample) -> None:
    metadata = example.metadata
    request = example.request
    business_name = request.get("business_name")
    product_names = request.get("product_names")
    if business_name != metadata.business_name:
        raise SystemExit(f"{example.example_id}: metadata/request business_name mismatch")
    if product_names != metadata.product_names:
        raise SystemExit(f"{example.example_id}: metadata/request product_names mismatch")
    if metadata.business_signature != _signature(metadata.business_name):
        raise SystemExit(f"{example.example_id}: invalid business_signature")
    expected_product_signatures = [_signature(item) for item in metadata.product_names]
    if metadata.product_signatures != expected_product_signatures:
        raise SystemExit(f"{example.example_id}: invalid product_signatures")
    if metadata.meme_id != MEME_ID:
        raise SystemExit(
            f"{example.example_id}: this scaffold only accepts meme_id {MEME_ID}"
        )


def _build_gold_content(request: AdCopyRequest, gold: GoldCopy) -> AdCopyContent:
    caption = f"{gold.headline}\n{gold.body}"
    hashtags_text = " ".join(gold.hashtags)
    publish_body = f"{caption}\n\n{gold.cta}\n{hashtags_text}"
    product_items = [
        {
            "product_name": product,
            "role": "primary" if index == 0 else "secondary",
        }
        for index, product in enumerate(request.product_names)
    ]
    feature_items = [
        {
            "feature_text": feature,
            "copy_usage_rule": "고객 노출 본문에 사실 그대로 자연스럽게 반영",
            "visual_usage_rule": "입력 특징을 과장하지 않는 제품 시각 단서로 반영",
        }
        for feature in request.features
    ]
    visual_products = [
        {
            "product_name": product,
            "visual_role": "main" if index == 0 else "supporting",
            "must_be_visible": True,
        }
        for index, product in enumerate(request.product_names)
    ]
    feature_visualization = [
        {"feature_text": feature, "visual_translation": [feature]}
        for feature in request.features
    ]

    payload = {
        "marketing_strategy": {
            "business_summary": {
                "business_name": request.business_name,
                "business_type_korean": BUSINESS_TYPE_LABELS[request.business_type.value],
                "situation_korean": SITUATION_LABELS[request.situation.value],
                "age_groups_korean": [
                    AGE_GROUP_LABELS[item.value] for item in request.age_groups
                ],
                "target_audiences_korean": [
                    TARGET_LABELS[item.value] for item in request.target_audiences
                ],
                "tone_korean": TONE_LABELS[request.tone.value],
                "channel_korean": CHANNEL_LABELS[request.channel.value],
            },
            "mandatory_products": product_items,
            "mandatory_features": feature_items,
            "core_message": gold.core_message,
            "customer_emotion": gold.customer_emotion,
            "marketing_angle": gold.marketing_angle,
            "recommended_cta_direction": "입력된 상호의 방문 또는 확인 유도",
            "avoid_points": request.prohibited_terms[:10],
        },
        "headlines": [gold.headline],
        "body_copies": [gold.body],
        "ctas": [gold.cta],
        "hashtags": gold.hashtags,
        "channel_recommendation": {
            "format_name": "Instagram feed caption",
            "writing_direction": "밈을 응용한 첫 문장 뒤에 상품 사실과 혜택, CTA를 배치",
            "image_direction": "대표 상품을 중심으로 보조 상품은 관계가 보이게 배치",
            "placement_tip": "이미지에는 짧은 헤드라인, 캡션에는 검증된 상품 정보를 배치",
            "overlay_headline": gold.headline,
            "caption": caption,
            "publish_cta": gold.cta,
            "publish_hashtags": gold.hashtags,
            "publish_title": gold.headline,
            "publish_body": publish_body,
            "promotion_template": (
                "이미지: 4:5 상품 사진\n제목: overlay_headline\n"
                "캡션: caption\n마무리: publish_cta\n해시태그: publish_hashtags"
            ),
            "image_insert_guide": "대표 상품이 보이는 이미지를 피드 첫 장에 배치",
        },
        "validation_check": {
            "all_products_included": True,
            "all_features_included": True,
            "prohibited_terms_used": False,
            "visual_brief_uses_enum_only": True,
            "hashtags_removed": True,
            "language_quality": "human-review seed Korean",
        },
        "visual_brief": {
            "products_to_show": visual_products,
            "feature_visualization": feature_visualization,
            "camera_angle": gold.camera_angle,
            "composition": (
                gold.composition
                if len(request.product_names) > 1
                else "centered_product_hero"
            ),
            "lighting": gold.lighting,
            "background": gold.background,
            "color_palette": gold.color_palette,
            "depth_of_field": gold.depth_of_field,
            "empty_space": gold.empty_space,
            "avoid": [
                "readable_text",
                "logo",
                "watermark",
                "menu_board",
                "store_sign",
                "random_people",
                "distorted_food",
            ],
        },
        "safety_notes": [],
    }
    return AdCopyContent.model_validate(payload)


def _materialize(example: SeedExample) -> tuple[dict[str, Any], AdCopyRequest, AdCopyContent]:
    _validate_metadata(example)
    request = AdCopyRequest.model_validate(
        {
            **example.request,
            "model": BASE_MODEL,
            "trend_card_id": example.metadata.meme_id,
        }
    )
    if request.channel.value != "instagram":
        raise SystemExit(f"{example.example_id}: current TrendCard only supports instagram")

    trend_card = load_trend_card(
        example.metadata.meme_id,
        path=DEFAULT_TREND_CARD_FILE,
        require_channel=request.channel.value,
        prohibited_terms=request.prohibited_terms,
    )
    content = _build_gold_content(request, example.gold)
    validation = validate_copy_output(content, request, trend_card)
    if not validation.valid:
        raise SystemExit(
            f"{example.example_id}: gold output failed production validation: "
            + "; ".join(validation.warnings)
        )

    customer_text = " ".join(
        [
            *content.headlines,
            *content.body_copies,
            *content.ctas,
            content.channel_recommendation.caption,
            content.channel_recommendation.publish_body,
        ]
    )
    missing_required = [term for term in request.required_terms if term not in customer_text]
    missing_features = [feature for feature in request.features if feature not in customer_text]
    if missing_required:
        raise SystemExit(
            f"{example.example_id}: gold output misses required_terms: {missing_required}"
        )
    if missing_features:
        raise SystemExit(
            f"{example.example_id}: gold output misses verbatim features: {missing_features}"
        )

    training_row = {
        "prompt": build_prompt_messages(request, trend_card=trend_card),
        "completion": [
            {
                "role": "assistant",
                "content": content.model_dump_json(exclude_none=True),
            }
        ],
    }
    return training_row, request, content


def _validate_split_isolation(
    train_examples: list[SeedExample], validation_examples: list[SeedExample]
) -> None:
    def keys(examples: list[SeedExample]) -> tuple[set[str], set[str], set[str], set[str]]:
        ids = {example.example_id for example in examples}
        businesses = {example.metadata.business_signature for example in examples}
        products = {
            signature
            for example in examples
            for signature in example.metadata.product_signatures
        }
        lineages = {example.metadata.source_lineage_id for example in examples}
        if len(ids) != len(examples):
            raise SystemExit("Duplicate example_id within a seed split")
        if len(lineages) != len(examples):
            raise SystemExit("Duplicate source_lineage_id within a seed split")
        return ids, businesses, products, lineages

    train_ids, train_businesses, train_products, train_lineages = keys(train_examples)
    val_ids, val_businesses, val_products, val_lineages = keys(validation_examples)
    overlaps = {
        "example_id": train_ids & val_ids,
        "business": train_businesses & val_businesses,
        "product": train_products & val_products,
        "source_lineage": train_lineages & val_lineages,
    }
    conflicts = {name: values for name, values in overlaps.items() if values}
    if conflicts:
        raise SystemExit(f"Train/validation leakage detected: {conflicts}")


def _validate_comparison_isolation(
    examples: list[SeedExample], comparison_paths: list[Path]
) -> None:
    businesses, products, lineages = _load_comparison_keys(comparison_paths)
    seed_businesses = {example.metadata.business_signature for example in examples}
    seed_products = {
        signature
        for example in examples
        for signature in example.metadata.product_signatures
    }
    seed_lineages = {example.metadata.source_lineage_id for example in examples}
    conflicts = {
        "business": seed_businesses & businesses,
        "product": seed_products & products,
        "source_lineage": seed_lineages & lineages,
    }
    conflicts = {name: sorted(values) for name, values in conflicts.items() if values}
    if conflicts:
        raise SystemExit(f"Comparison-corpus leakage detected: {conflicts}")


def _validate_cli(args: argparse.Namespace) -> None:
    if args.epochs <= 0:
        raise SystemExit("--epochs must be greater than 0")
    if args.learning_rate <= 0:
        raise SystemExit("--learning-rate must be greater than 0")
    if args.max_length < 512:
        raise SystemExit("--max-length must be at least 512")
    if args.gradient_accumulation_steps < 1:
        raise SystemExit("--gradient-accumulation-steps must be at least 1")
    if args.lora_r < 1 or args.lora_alpha < 1:
        raise SystemExit("--lora-r and --lora-alpha must be at least 1")
    if not 0 <= args.lora_dropout < 1:
        raise SystemExit("--lora-dropout must be in [0, 1)")


def _require_reviewed(examples: list[SeedExample], allow_unreviewed: bool) -> None:
    unreviewed = [
        example.example_id
        for example in examples
        if example.metadata.review_status != "reviewed"
        or example.metadata.rights_review_status != "reviewed"
    ]
    if unreviewed and not allow_unreviewed:
        raise SystemExit(
            "Training is blocked because scaffold rows still need human/content-rights "
            "review. Review the rows and change both review metadata fields to 'reviewed', "
            "or use --allow-unreviewed-seeds only for an engineering smoke run. Rows: "
            + ", ".join(unreviewed)
        )


def _prepare_output_dir(path: Path | None) -> Path:
    if path is None:
        raise SystemExit("--output-dir is required for training")
    resolved = path.resolve()
    protected_directories = [
        API_ROOT.resolve(),
        (API_ROOT / "app").resolve(),
        (API_ROOT / "evals").resolve(),
        (API_ROOT / "scripts").resolve(),
    ]
    if any(
        resolved == protected or resolved.is_relative_to(protected)
        for protected in protected_directories
    ):
        raise SystemExit(f"Refusing unsafe output directory: {resolved}")
    if resolved.exists() and any(resolved.iterdir()):
        raise SystemExit(
            f"Output directory must not already contain files: {resolved}. "
            "Choose a new run directory; this script never deletes existing artifacts."
        )
    resolved.mkdir(parents=True, exist_ok=True)
    return resolved


def _train(
    args: argparse.Namespace,
    train_rows: list[dict[str, Any]],
    validation_rows: list[dict[str, Any]],
    comparison_paths: list[Path],
) -> None:
    if not args.base_revision or not IMMUTABLE_REVISION_PATTERN.fullmatch(
        args.base_revision
    ):
        raise SystemExit(
            "Training requires --base-revision set to an immutable 40-character "
            "Hugging Face commit SHA. Do not train against the mutable 'main' revision."
        )

    try:
        import torch
        from datasets import Dataset
        from peft import LoraConfig
        from transformers import AutoModelForCausalLM, AutoTokenizer, set_seed
        from trl import SFTConfig, SFTTrainer
    except ImportError as error:
        raise SystemExit(
            "LoRA dependencies are not installed. From apps/api, install the project and "
            "requirements-lora.txt before training."
        ) from error

    if not torch.cuda.is_available():
        raise SystemExit(
            "CUDA GPU was not detected. Qwen2.5-7B LoRA training is intentionally blocked "
            "on CPU. Use --validate-only on this machine or move the run to a CUDA host."
        )

    output_dir = _prepare_output_dir(args.output_dir)
    set_seed(args.seed)
    dtype = torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16
    device = torch.cuda.get_device_properties(0)
    vram_gb = round(device.total_memory / (1024**3), 2)
    print(f"CUDA device: {device.name} ({vram_gb} GiB); dtype={dtype}", flush=True)
    if vram_gb < 40:
        print(
            "WARNING: less than 40 GiB VRAM was detected. The production prompt and full "
            "JSON completion are long, so this full-precision-base LoRA configuration may "
            "run out of memory. Use a larger host before reducing max length.",
            flush=True,
        )

    tokenizer = AutoTokenizer.from_pretrained(
        BASE_MODEL,
        revision=args.base_revision,
        trust_remote_code=False,
    )
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    token_lengths = [
        len(
            tokenizer.apply_chat_template(
                [*row["prompt"], *row["completion"]],
                tokenize=True,
                add_generation_prompt=False,
            )
        )
        for row in [*train_rows, *validation_rows]
    ]
    too_long = [length for length in token_lengths if length > args.max_length]
    if too_long:
        raise SystemExit(
            f"{len(too_long)} examples exceed --max-length={args.max_length}; "
            f"longest={max(too_long)}. Refusing silent truncation of the production "
            "prompt or gold JSON. Increase max length on a GPU with enough memory."
        )
    print(
        f"Tokenized sequence length: min={min(token_lengths)}, "
        f"max={max(token_lengths)} (limit={args.max_length})",
        flush=True,
    )
    model = AutoModelForCausalLM.from_pretrained(
        BASE_MODEL,
        revision=args.base_revision,
        torch_dtype=dtype,
        trust_remote_code=False,
    )
    model.config.use_cache = False

    peft_config = LoraConfig(
        task_type="CAUSAL_LM",
        r=args.lora_r,
        lora_alpha=args.lora_alpha,
        lora_dropout=args.lora_dropout,
        bias="none",
        target_modules=[
            "q_proj",
            "k_proj",
            "v_proj",
            "o_proj",
            "gate_proj",
            "up_proj",
            "down_proj",
        ],
    )
    training_args = SFTConfig(
        output_dir=str(output_dir),
        num_train_epochs=args.epochs,
        learning_rate=args.learning_rate,
        per_device_train_batch_size=1,
        per_device_eval_batch_size=1,
        gradient_accumulation_steps=args.gradient_accumulation_steps,
        gradient_checkpointing=True,
        gradient_checkpointing_kwargs={"use_reentrant": False},
        bf16=dtype == torch.bfloat16,
        fp16=dtype == torch.float16,
        max_length=args.max_length,
        completion_only_loss=True,
        assistant_only_loss=False,
        packing=False,
        eval_strategy="epoch",
        save_strategy="epoch",
        save_total_limit=2,
        logging_steps=1,
        report_to="none",
        seed=args.seed,
        data_seed=args.seed,
        dataloader_num_workers=0,
        remove_unused_columns=True,
        push_to_hub=False,
    )
    trainer = SFTTrainer(
        model=model,
        args=training_args,
        train_dataset=Dataset.from_list(train_rows),
        eval_dataset=Dataset.from_list(validation_rows),
        processing_class=tokenizer,
        peft_config=peft_config,
    )
    trainer.train()
    trainer.save_model(str(output_dir))
    tokenizer.save_pretrained(str(output_dir))

    manifest = {
        "created_at": datetime.now(UTC).isoformat(),
        "base_model": BASE_MODEL,
        "base_revision": args.base_revision,
        "prompt_version": PROMPT_VERSION,
        "train_file": str(args.train_file.resolve()),
        "train_sha256": _sha256(args.train_file),
        "validation_file": str(args.validation_file.resolve()),
        "validation_sha256": _sha256(args.validation_file),
        "comparison_corpora": [
            {
                "path": str(path.resolve()),
                "sha256": _sha256(path),
            }
            for path in comparison_paths
        ],
        "trend_card_file": str(DEFAULT_TREND_CARD_FILE.resolve()),
        "trend_card_sha256": _sha256(DEFAULT_TREND_CARD_FILE),
        "train_examples": len(train_rows),
        "validation_examples": len(validation_rows),
        "seed": args.seed,
        "completion_only_loss": True,
        "token_length_min": min(token_lengths),
        "token_length_max": max(token_lengths),
        "max_length": args.max_length,
        "training": {
            "epochs": args.epochs,
            "learning_rate": args.learning_rate,
            "per_device_train_batch_size": 1,
            "per_device_eval_batch_size": 1,
            "gradient_accumulation_steps": args.gradient_accumulation_steps,
            "effective_train_batch_size": args.gradient_accumulation_steps,
            "gradient_checkpointing": True,
            "packing": False,
            "eval_strategy": "epoch",
            "save_strategy": "epoch",
        },
        "runtime": {
            "dtype": str(dtype),
            "cuda_version": torch.version.cuda,
            "gpu_name": device.name,
            "gpu_vram_gb": vram_gb,
        },
        "lora": {
            "r": args.lora_r,
            "alpha": args.lora_alpha,
            "dropout": args.lora_dropout,
            "target_modules": sorted(peft_config.target_modules),
        },
        "dependencies": {
            package: package_version(package)
            for package in (
                "torch",
                "transformers",
                "accelerate",
                "datasets",
                "peft",
                "trl",
            )
        },
    }
    (output_dir / "brandmate_training_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"Adapter and manifest saved to: {output_dir}", flush=True)


def main() -> None:
    args = parse_args()
    _validate_cli(args)
    train_examples = _load_jsonl(args.train_file, "train")
    validation_examples = _load_jsonl(args.validation_file, "validation")
    all_examples = [*train_examples, *validation_examples]
    _validate_split_isolation(train_examples, validation_examples)
    comparison_paths = [*DEFAULT_COMPARISON_FILES, *args.overlap_file]
    _validate_comparison_isolation(all_examples, comparison_paths)

    materialized = [_materialize(example) for example in all_examples]
    train_count = len(train_examples)
    train_rows = [item[0] for item in materialized[:train_count]]
    validation_rows = [item[0] for item in materialized[train_count:]]
    print(
        f"Validated {len(train_rows)} train and {len(validation_rows)} validation rows; "
        f"comparison corpora: {len(comparison_paths)}.",
        flush=True,
    )
    if args.validate_only:
        return

    _require_reviewed(all_examples, args.allow_unreviewed_seeds)
    _train(args, train_rows, validation_rows, comparison_paths)


if __name__ == "__main__":
    main()
