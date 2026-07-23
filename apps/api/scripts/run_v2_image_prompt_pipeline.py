"""v2 food image-prompt batch pipeline.

Reads prompt_metadata.csv and llm_prompt_payloads.json from the v2 dataset,
matches each image to its existing prompt data, and invokes the existing
ad-content orchestration (`generate_content`) for each channel.

Supported batch sizes: 10, 50, 100.

Usage examples
--------------
# 10-image dry-run (validates matching only, no model calls):
python scripts/run_v2_image_prompt_pipeline.py \\
    --input-dir  "data/processed/aihub_food_image_text/v2" \\
    --output-dir "data/outputs/v2_model_results" \\
    --batch-size 10 \\
    --llm-model "Qwen/Qwen2.5-7B-Instruct" \\
    --image-model "black-forest-labs/FLUX.1-schnell" \\
    --dry-run

# 10-image real run:
python scripts/run_v2_image_prompt_pipeline.py \\
    --input-dir  "data/processed/aihub_food_image_text/v2" \\
    --output-dir "data/outputs/v2_model_results" \\
    --batch-size 10 \\
    --llm-model "Qwen/Qwen2.5-7B-Instruct" \\
    --image-model "black-forest-labs/FLUX.1-schnell"

# Resume after interruption:
python scripts/run_v2_image_prompt_pipeline.py \\
    --input-dir  "data/processed/aihub_food_image_text/v2" \\
    --output-dir "data/outputs/v2_model_results" \\
    --batch-size 10 \\
    --llm-model "Qwen/Qwen2.5-7B-Instruct" \\
    --image-model "black-forest-labs/FLUX.1-schnell" \\
    --resume

Prompt protection
-----------------
- No prompt file or function is modified.
- ad_prompt_hint is passed verbatim to the image model.
- SHA-256 of ad_prompt_hint is recorded for integrity verification.
- API keys are read from the existing .env via app.core.config.settings.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Path setup: ensure the api package root is on sys.path so that
# `from app.xxx import ...` works when the script is run from any CWD.
# ---------------------------------------------------------------------------
_SCRIPT_DIR = Path(__file__).resolve().parent
_API_ROOT = _SCRIPT_DIR.parent  # apps/api/
if str(_API_ROOT) not in sys.path:
    sys.path.insert(0, str(_API_ROOT))

# Now import pipeline modules (all from app.v2_pipeline, no prompt files touched)
from app.extensions.ad_content.schemas import ImageModel  # noqa: E402
from app.modules.ad_copy.schemas import AdModel  # noqa: E402
from app.v2_pipeline.loader import load_records, select_batch  # noqa: E402
from app.v2_pipeline.model_selection import (  # noqa: E402
    available_image_models,
    available_llm_models,
    model_slug,
)
from app.v2_pipeline.validator import validate_batch  # noqa: E402
from app.v2_pipeline.runner import run_batch  # noqa: E402

# ---------------------------------------------------------------------------
ALLOWED_BATCH_SIZES = [10, 50, 100]
DEFAULT_MAX_RETRIES = 2


# ---------------------------------------------------------------------------
# Custom argparse action: validate --batch-size after int conversion
# argparse converts the string to int via type=int first, then calls this action.
# ---------------------------------------------------------------------------
class _BatchSizeAction(argparse.Action):
    def __call__(self, parser, namespace, values, option_string=None):
        # values is already int here (type=int applied by argparse before action)
        try:
            int_val = int(values)
        except (TypeError, ValueError):
            parser.error(
                f"Invalid batch size: {values!r}. "
                f"Allowed values are 10, 50, and 100."
            )
            return
        if int_val not in ALLOWED_BATCH_SIZES:
            parser.error(
                f"Invalid batch size: {int_val}. "
                f"Allowed values are 10, 50, and 100."
            )
        setattr(namespace, self.dest, int_val)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    # Required
    parser.add_argument(
        "--input-dir",
        type=Path,
        required=True,
        metavar="DIR",
        help="Path to the v2 dataset root "
        "(e.g. data/processed/aihub_food_image_text/v2).",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        metavar="DIR",
        help="Root output directory "
        "(e.g. data/outputs/v2_model_results). "
        "Batch-specific subdirectory is created automatically.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        required=True,
        action=_BatchSizeAction,
        dest="batch_size",
        metavar="{10,50,100}",
        help=(
            "Number of images to process. "
            "Allowed values: 10, 50, 100. "
            "Whole-dataset processing is not supported."
        ),
    )

    # Optional
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Validate images and prompt matching only. No model calls.",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        default=False,
        help="Skip image IDs already recorded as success in state.json.",
    )
    parser.add_argument(
        "--max-retries",
        type=int,
        default=DEFAULT_MAX_RETRIES,
        metavar="N",
        help=f"Extra retry attempts after first failure (default: {DEFAULT_MAX_RETRIES}).",
    )
    image_model_group = parser.add_mutually_exclusive_group(required=True)
    image_model_group.add_argument(
        "--image-model",
        type=str,
        choices=[model.value for model in available_image_models()],
        metavar="MODEL",
        help="Image generation model to use for this run.",
    )
    image_model_group.add_argument(
        "--all-image-models",
        action="store_true",
        help="Test every image model in the existing production image-model enum.",
    )
    llm_model_group = parser.add_mutually_exclusive_group(required=True)
    llm_model_group.add_argument(
        "--llm-model",
        type=str,
        choices=[model.value for model in available_llm_models()],
        metavar="MODEL",
        help=(
            "Existing advertising-copy model. The same runtime model is used "
            "by the existing visualizer/reference-analysis step."
        ),
    )
    llm_model_group.add_argument(
        "--all-llm-models",
        action="store_true",
        help="Test every canonical LLM in the existing production model catalog.",
    )
    parser.add_argument(
        "--sampling",
        type=str,
        choices=["sequential"],  # "random" can be added later with --seed
        default="sequential",
        help="Record selection strategy (default: sequential).",
    )
    parser.add_argument(
        "--channels",
        nargs="+",
        choices=["instagram", "naver_blog"],
        default=["instagram", "naver_blog"],
        help="Channels to generate independently (default: instagram naver_blog).",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        metavar="N",
        help="Random seed (reserved for future --sampling random support).",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        default=False,
        help="Suppress per-item log output to stdout.",
    )
    return parser


def _resolve_batch_output_dir(output_dir: Path, batch_size: int) -> Path:
    """Return the batch-specific output subdirectory."""
    return output_dir / f"batch_{batch_size}"


def main() -> int:
    # Guard: --batch-size is required — argparse handles missing arg automatically,
    # but we add an explicit message for clarity.
    if "--batch-size" not in sys.argv:
        print(
            "error: --batch-size is required. "
            f"Choose one of: {', '.join(str(v) for v in ALLOWED_BATCH_SIZES)}.",
            file=sys.stderr,
        )
        return 2

    parser = build_parser()
    args = parser.parse_args()

    input_dir: Path = args.input_dir.resolve()
    batch_output_dir: Path = _resolve_batch_output_dir(
        args.output_dir.resolve(), args.batch_size
    )

    print(f"input_dir  : {input_dir}")
    print(f"output_dir : {batch_output_dir}")
    print(f"batch_size : {args.batch_size}")
    print(f"dry_run    : {args.dry_run}")
    print(f"resume     : {args.resume}")
    print(f"max_retries: {args.max_retries}")
    print(f"image_model: {args.image_model}")
    print(f"llm_model  : {args.llm_model}")

    # 1. Load records
    try:
        all_records = load_records(input_dir)
    except (FileNotFoundError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    # 2. Select batch (deterministic)
    try:
        batch = select_batch(all_records, args.batch_size)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(
        f"\nLoaded {len(all_records)} total records → selected {len(batch)} for batch."
    )

    # 3. Pre-flight validation
    results_dir = batch_output_dir / "results"
    from app.v2_pipeline.validator import validate_batch

    report = validate_batch(batch, results_dir)

    if report.warnings:
        print(f"\nValidation warnings ({len(report.warnings)}):")
        for w in report.warnings:
            print(f"  [WARN] {w.image_id}: {w.message}")

    if not report.is_valid:
        print(f"\nValidation FAILED ({len(report.errors)} error(s)):", file=sys.stderr)
        for e in report.errors:
            print(f"  [ERROR] {e.image_id}: {e.message}", file=sys.stderr)
        return 1

    print(f"\nValidation OK — {len(batch)} record(s) ready.")

    # 4. Resolve model matrix. Explicit --all flags can create many paid
    # provider-backed runs, but never expand the fixed data batch.
    try:
        image_models = list(available_image_models()) if args.all_image_models else [ImageModel(args.image_model)]
    except ValueError:
        valid = [m.value for m in ImageModel]
        print(
            f"error: Unknown image model '{args.image_model}'. "
            f"Valid options: {valid}",
            file=sys.stderr,
        )
        return 1

    try:
        llm_models = list(available_llm_models()) if args.all_llm_models else [AdModel(args.llm_model)]
    except ValueError:
        valid = [m.value for m in available_llm_models()]
        print(
            f"error: Unknown LLM model '{args.llm_model}'. Valid options: {valid}",
            file=sys.stderr,
        )
        return 1

    print(f"llm_models : {[model.value for model in llm_models]}")
    print(f"image_models: {[model.value for model in image_models]}")

    # 5. Run batch (dry-run or real)
    exit_codes = []
    for channel in args.channels:
        for llm_model in llm_models:
            for image_model in image_models:
                # Result/state paths are per channel and model pair. This makes
                # --resume safe and prevents one model's result from replacing another.
                model_run = f"llm_{model_slug(llm_model)}__image_{model_slug(image_model)}"
                channel_output_dir = batch_output_dir / channel / "models" / model_run
                print(f"channel    : {channel}")
                print(f"model_run  : {model_run}")
                exit_codes.append(asyncio.run(run_batch(
                    records=batch, batch_size=args.batch_size, output_dir_root=channel_output_dir,
                    max_retries=args.max_retries, resume=args.resume, dry_run=args.dry_run,
                    image_model=image_model, llm_model=llm_model,
                    verbose=not args.quiet, channel=channel,
                )))
    return 1 if any(exit_codes) else 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
