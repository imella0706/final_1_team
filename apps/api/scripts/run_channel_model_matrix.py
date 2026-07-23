"""Cross-test local models for Instagram and Naver Blog with uploaded photos.

The command is a dry run unless --execute is supplied. Instagram evaluates the
copy x vision x image model product. Naver Blog evaluates copy x vision because
that channel reuses uploaded photos and skips image generation.
"""

import argparse
import asyncio
import base64
import json
import mimetypes
import sys
from datetime import UTC, datetime
from itertools import product
from pathlib import Path
from time import perf_counter
from typing import Any

from fastapi import HTTPException

from app.extensions.ad_content.router import generate_content
from app.extensions.ad_content.schemas import (
    AdContentRequest,
    BlogImageInput,
    ImageModel,
    VisionModel,
)
from app.modules.ad_copy.schemas import AdChannel, AdModel


API_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = API_ROOT.parents[1]
DEFAULT_INPUT = API_ROOT / "evals" / "channel_model_matrix.example.json"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "outputs" / "channel-model-matrix"

DEFAULT_COPY_MODELS = (
    AdModel.LOCAL_QWEN_2_5_1_5B,
    AdModel.LOCAL_QWEN_2_5_7B,
    AdModel.LOCAL_MISTRAL_7B,
)
DEFAULT_VISION_MODELS = (
    VisionModel.LOCAL_QWEN_3_VL_2B,
    VisionModel.LOCAL_QWEN_3_VL_4B,
    VisionModel.LOCAL_QWEN_2_5_VL_7B,
    VisionModel.LOCAL_QWEN_3_VL_8B,
)
DEFAULT_IMAGE_MODELS = (
    ImageModel.SDXL_BASE,
    ImageModel.SDXL_TURBO,
    ImageModel.FLUX_SCHNELL,
)
DEFAULT_CHANNELS = (AdChannel.INSTAGRAM, AdChannel.NAVER_BLOG)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--photo", type=Path, action="append", default=[])
    parser.add_argument("--input-json", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument(
        "--copy-model",
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
        "--channel",
        choices=[AdChannel.INSTAGRAM.value, AdChannel.NAVER_BLOG.value],
        action="append",
    )
    parser.add_argument("--max-runs", type=int)
    parser.add_argument("--concurrency", type=int, default=1)
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Actually call models. Without this flag only the matrix plan is saved.",
    )
    return parser.parse_args()


def _valid_image_bytes(image_bytes: bytes) -> bool:
    return (
        image_bytes.startswith(b"\x89PNG\r\n\x1a\n")
        or image_bytes.startswith(b"\xff\xd8\xff")
        or (image_bytes.startswith(b"RIFF") and image_bytes[8:12] == b"WEBP")
    )


def image_to_data_url(path: Path) -> str:
    image_bytes = path.read_bytes()
    if not _valid_image_bytes(image_bytes):
        raise ValueError(f"Not a valid PNG, JPEG, or WebP image: {path}")
    media_type = mimetypes.guess_type(path.name)[0] or "image/png"
    encoded = base64.b64encode(image_bytes).decode("ascii")
    return f"data:{media_type};base64,{encoded}"


def load_input(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("copy"), dict):
        raise ValueError("input-json must contain a 'copy' object.")
    return payload


def selected_values(
    raw_values: list[str] | None,
    enum_type,
    defaults: tuple,
) -> list:
    return [enum_type(value) for value in raw_values] if raw_values else list(defaults)


def build_matrix(args: argparse.Namespace) -> list[dict[str, Any]]:
    copy_models = selected_values(args.copy_model, AdModel, DEFAULT_COPY_MODELS)
    vision_models = selected_values(args.vision_model, VisionModel, DEFAULT_VISION_MODELS)
    image_models = selected_values(args.image_model, ImageModel, DEFAULT_IMAGE_MODELS)
    channels = selected_values(args.channel, AdChannel, DEFAULT_CHANNELS)
    cases: list[dict[str, Any]] = []

    if AdChannel.INSTAGRAM in channels:
        for copy_model, vision_model, image_model in product(
            copy_models,
            vision_models,
            image_models,
        ):
            cases.append(
                {
                    "channel": AdChannel.INSTAGRAM,
                    "copy_model": copy_model,
                    "vision_model": vision_model,
                    "image_model": image_model,
                }
            )

    if AdChannel.NAVER_BLOG in channels:
        for copy_model, vision_model in product(copy_models, vision_models):
            cases.append(
                {
                    "channel": AdChannel.NAVER_BLOG,
                    "copy_model": copy_model,
                    "vision_model": vision_model,
                    "image_model": image_models[0],
                }
            )

    return cases[: args.max_runs] if args.max_runs else cases


def case_id(case: dict[str, Any]) -> str:
    values = (
        case["channel"].value,
        case["copy_model"].value,
        case["vision_model"].value,
        case["image_model"].value,
    )
    return "__".join(value.replace("/", "_").replace(":", "_") for value in values)


def build_request(
    base_input: dict[str, Any],
    case: dict[str, Any],
    photo_data_urls: list[str],
    photo_paths: list[Path],
) -> AdContentRequest:
    copy_payload = {
        **base_input["copy"],
        "model": case["copy_model"].value,
        "channel": case["channel"].value,
    }
    blog_images = [
        BlogImageInput(id=f"photo-{index}", name=path.name, data_url=data_url)
        for index, (path, data_url) in enumerate(
            zip(photo_paths, photo_data_urls, strict=True),
            start=1,
        )
    ]
    return AdContentRequest(
        copy=copy_payload,
        use_vision_analysis=bool(base_input.get("use_vision_analysis", True)),
        vision_model=case["vision_model"],
        image_model=case["image_model"],
        image_width=int(base_input.get("image_width", 768)),
        image_height=int(base_input.get("image_height", 1024)),
        reference_image_data_url=photo_data_urls[0],
        blog_images=blog_images if case["channel"] == AdChannel.NAVER_BLOG else [],
    )


async def run_case(
    base_input: dict[str, Any],
    case: dict[str, Any],
    photo_data_urls: list[str],
    photo_paths: list[Path],
    semaphore: asyncio.Semaphore,
) -> dict[str, Any]:
    async with semaphore:
        identifier = case_id(case)
        started = perf_counter()
        record: dict[str, Any] = {
            "id": identifier,
            "channel": case["channel"].value,
            "copy_model": case["copy_model"].value,
            "vision_model": case["vision_model"].value,
            "image_model_requested": case["image_model"].value,
            "success": False,
        }
        try:
            request = build_request(base_input, case, photo_data_urls, photo_paths)
            response = await generate_content(request)
        except HTTPException as error:
            record.update(
                error_type="HTTPException",
                error=str(error.detail),
                status_code=error.status_code,
            )
        except Exception as error:  # noqa: BLE001 - matrix must continue
            record.update(error_type=type(error).__name__, error=str(error))
        else:
            channel_output = response.copy_result.channel_recommendation
            record.update(
                success=True,
                copy_model_routed=response.copy_result.routed_model,
                copy_latency_ms=response.copy_result.latency_ms,
                image_model_actual=response.image.model,
                image_latency_ms=response.image.latency_ms,
                headline=response.copy_result.headlines[0],
                instagram_caption=channel_output.caption,
                naver_blog_title=channel_output.publish_title
                or channel_output.blog_title,
                validation=response.validation,
                artifacts=response.artifacts,
            )
        record["wall_latency_ms"] = round((perf_counter() - started) * 1000, 2)
        status = "OK" if record["success"] else "FAIL"
        print(f"[{status}] {identifier} · {record['wall_latency_ms']}ms", flush=True)
        return record


def serializable_case(case: dict[str, Any]) -> dict[str, str]:
    return {key: value.value for key, value in case.items()}


async def run(args: argparse.Namespace) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    base_input = load_input(args.input_json)
    cases = build_matrix(args)
    timestamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    run_dir = args.output_dir / timestamp
    run_dir.mkdir(parents=True, exist_ok=True)
    plan_path = run_dir / "matrix-plan.json"
    summary_path = run_dir / "matrix-summary.json"
    plan_path.write_text(
        json.dumps([serializable_case(case) for case in cases], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    instagram_count = sum(case["channel"] == AdChannel.INSTAGRAM for case in cases)
    blog_count = sum(case["channel"] == AdChannel.NAVER_BLOG for case in cases)
    print(f"Matrix: {len(cases)} runs (Instagram {instagram_count}, Naver Blog {blog_count})")
    print(f"Plan: {plan_path}")
    if not args.execute:
        print("Dry run complete. Add --execute and at least one --photo to call models.")
        return 0
    if not args.photo:
        raise ValueError("At least one --photo is required with --execute.")
    if args.concurrency < 1:
        raise ValueError("concurrency must be at least 1.")

    photo_paths = [path.resolve() for path in args.photo]
    for path in photo_paths:
        if not path.is_file():
            raise FileNotFoundError(path)
    photo_data_urls = [image_to_data_url(path) for path in photo_paths]
    semaphore = asyncio.Semaphore(args.concurrency)
    records = await asyncio.gather(
        *(
            run_case(base_input, case, photo_data_urls, photo_paths, semaphore)
            for case in cases
        )
    )
    summary = {
        "generated_at": datetime.now(UTC).isoformat(),
        "input_json": str(args.input_json.resolve()),
        "photos": [str(path) for path in photo_paths],
        "total": len(records),
        "successes": sum(record["success"] for record in records),
        "records": records,
    }
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"Summary: {summary_path}")
    print(f"Success: {summary['successes']}/{summary['total']}")
    return 0 if summary["successes"] == summary["total"] else 1


def main() -> None:
    raise SystemExit(asyncio.run(run(parse_args())))


if __name__ == "__main__":
    main()
