"""Evaluate the ad-copy-to-image pipeline and write CLIP Score reports."""

import argparse
import asyncio
import hashlib
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean, stdev
from time import perf_counter
from typing import Any

import httpx

from app.core.config import settings
from app.evaluation.metrics import percentile
from app.evaluation.vision_metrics import (
    InvalidImagePayloadError,
    VisionMetricDependencyError,
    _load_clip_model,
    calculate_clip_score,
    decode_image_base64,
)
from app.extensions.ad_content.image_service import (
    ImageModelNotConfiguredError,
    ImageModelProviderError,
    generate_ad_image,
)
from app.extensions.ad_content.image_prompt import build_clip_eval_prompt
from app.extensions.ad_content.product_visualizer import visualize_products
from app.extensions.ad_content.prompt_normalizer import normalize_image_prompt
from app.extensions.ad_content.schemas import AdImageRequest, ImageModel
from app.modules.ad_copy.models import get_model_spec
from app.modules.ad_copy.schemas import AdCopyRequest, AdModel
from app.modules.ad_copy.service import (
    InvalidModelOutputError,
    ModelNotConfiguredError,
    ModelProviderError,
    generate_ad_copy,
)
from app.modules.model_runtime.llm.registry import (
    get_text_model_config,
    resolve_api_key,
    resolve_base_url,
)


API_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = API_ROOT.parents[1]
DEFAULT_DATASET = API_ROOT / "evals" / "ad_copy_cases.json"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "outputs" / "evaluations"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--copy-model", choices=[model.value for model in AdModel])
    parser.add_argument("--image-models", nargs="*", choices=[model.value for model in ImageModel])
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--concurrency", type=int, default=1)
    parser.add_argument("--case-limit", type=int)
    parser.add_argument("--clip-model", default="openai/clip-vit-base-patch32")
    parser.add_argument(
        "--skip-clip",
        action="store_true",
        help="Skip CLIP Score calculation for fast local smoke tests.",
    )
    parser.add_argument("--image-width", type=int)
    parser.add_argument("--image-height", type=int)
    parser.add_argument("--guidance-scale", type=float)
    parser.add_argument("--num-inference-steps", type=int)
    parser.add_argument("--vision-judge-model")
    parser.add_argument("--vision-judge-base-url", default="https://api.openai.com/v1")
    parser.add_argument("--vision-judge-api-key-env", default="OPENAI_API_KEY")
    parser.add_argument("--vision-judge-timeout-seconds", type=float, default=60)
    return parser.parse_args()


def load_cases(path: Path, case_limit: int | None) -> list[dict[str, Any]]:
    cases = json.loads(path.read_text(encoding="utf-8"))
    return cases[:case_limit] if case_limit else cases


def build_copy_request(case: dict[str, Any], copy_model: AdModel) -> AdCopyRequest:
    return AdCopyRequest.model_validate({**case["request"], "model": copy_model})


def media_type_extension(media_type: str) -> str:
    return {
        "image/jpeg": ".jpg",
        "image/jpg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
    }.get(media_type.lower(), ".png")


def safe_filename(value: str) -> str:
    cleaned = "".join(
        character if character.isalnum() or character in {"-", "_"} else "_"
        for character in value
    )
    return "_".join(part for part in cleaned.split("_") if part)[:140] or "image"


def save_generated_image(
    image_base64: str,
    media_type: str,
    image_dir: Path,
    case_id: str,
    image_model: ImageModel,
    repeat: int,
) -> Path:
    model_dir = image_dir / safe_filename(image_model.value)
    model_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{safe_filename(case_id)}__r{repeat}{media_type_extension(media_type)}"
    path = model_dir / filename
    path.write_bytes(decode_image_base64(image_base64))
    return path


def deterministic_seed(case_id: str, image_model: ImageModel, repeat: int) -> int:
    seed_source = f"{case_id}|{image_model.value}|{repeat}"
    digest = hashlib.sha256(seed_source.encode("utf-8")).hexdigest()
    return int(digest[:8], 16)


def git_commit() -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=PROJECT_ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return result.stdout.strip()


async def preflight_environment(
    copy_model: AdModel,
    image_models: list[ImageModel],
    clip_model: str,
    skip_clip: bool,
) -> None:
    errors: list[str] = []

    try:
        config = get_text_model_config(copy_model.value)
        base_url = resolve_base_url(config).rstrip("/")
        api_key = resolve_api_key(config)
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(f"{base_url}/models", headers=headers)
            response.raise_for_status()
    except Exception as error:
        errors.append(
            "LLM 서버 확인 실패: "
            f"{copy_model.value} endpoint에 연결할 수 없습니다. "
            "Ollama/LM Studio/Hugging Face 설정을 확인하세요. "
            f"원인={type(error).__name__}: {error}"
        )

    image_provider = settings.image_provider.lower()
    if image_provider == "comfyui":
        unsupported_models = [
            model.value for model in image_models if model != ImageModel.FLUX_SCHNELL
        ]
        if unsupported_models:
            errors.append(
                "ComfyUI 로컬 provider는 현재 FLUX.1 Schnell만 지원합니다: "
                + ", ".join(unsupported_models)
            )
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.get(
                    f"{settings.comfyui_base_url.rstrip('/')}/system_stats"
                )
                response.raise_for_status()
        except Exception as error:
            errors.append(
                "ComfyUI 확인 실패: "
                f"{settings.comfyui_base_url}에 연결할 수 없습니다. "
                "ComfyUI를 --lowvram으로 실행했는지 확인하세요. "
                f"원인={type(error).__name__}: {error}"
            )
    elif image_provider == "huggingface":
        if settings.llm_api_key is None:
            errors.append(
                "Hugging Face 이미지 생성에는 BRANDMATE_LLM_API_KEY가 필요합니다."
            )
    else:
        errors.append(
            "지원하지 않는 BRANDMATE_IMAGE_PROVIDER입니다: "
            f"{settings.image_provider}. comfyui 또는 huggingface를 사용하세요."
        )

    if not skip_clip:
        try:
            # [Design Intent] 이미지 생성까지 끝낸 뒤 CLIP 로딩에서 실패하면 반쪽짜리 run이
            # 남는다. 평가 시작 전에 CLIP 모델을 먼저 로드해 dependency/cache 문제를 조기 차단한다.
            _load_clip_model(clip_model)
        except VisionMetricDependencyError as error:
            errors.append(f"CLIP 의존성 확인 실패: {error}")
        except Exception as error:
            errors.append(
                "CLIP 모델 로드 실패: "
                f"{clip_model}을 로드할 수 없습니다. "
                "safetensors 캐시 또는 Hugging Face 네트워크 상태를 확인하세요. "
                f"원인={type(error).__name__}: {error}"
            )

    if errors:
        message = "\n".join(f"- {error}" for error in errors)
        raise SystemExit(
            "비전 평가 사전 점검 실패. run 폴더를 만들지 않고 종료합니다.\n"
            f"{message}"
        )


def parse_json_object(content: str) -> dict[str, Any]:
    cleaned = content.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.removeprefix("```json").removeprefix("```")
        cleaned = cleaned.removesuffix("```").strip()
    data, _ = json.JSONDecoder().raw_decode(cleaned)
    if not isinstance(data, dict):
        raise ValueError("Judge response must be a JSON object.")
    return data


async def judge_generated_image(
    image_base64: str,
    media_type: str,
    prompt: str,
    model: str,
    base_url: str,
    api_key: str,
    timeout_seconds: float,
) -> dict[str, Any]:
    # [Design Intent] GPT/VLM Judge는 유료 외부 API라 기본 평가 경로에 강제하지 않는다.
    # CLI 옵션으로 명시했을 때만 호출하고, 결과는 자동 지표를 보완하는 2차 QA 점수로 저장한다.
    rubric = """
Return JSON only with this schema:
{
  "quality_score": 1-5,
  "brand_fit_score": 1-5,
  "object_accuracy_score": 1-5,
  "visual_error_score": 1-5,
  "overall_score": 1-5,
  "rationale": "short Korean explanation"
}

Scoring rules:
- quality_score: visual polish, lighting, composition, commercial image quality
- brand_fit_score: fit for a Korean local business advertisement
- object_accuracy_score: whether visible objects match the prompt
- visual_error_score: 5 means no visible artifact, 1 means severe artifact
- overall_score: final usefulness as an advertisement image
"""
    payload = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": f"Image generation prompt:\n{prompt}\n\n{rubric}",
                    },
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{media_type};base64,{image_base64}",
                        },
                    },
                ],
            }
        ],
        "temperature": 0,
        "max_completion_tokens": 500,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(timeout=timeout_seconds) as client:
        response = await client.post(
            f"{base_url.rstrip('/')}/chat/completions",
            headers=headers,
            json=payload,
        )
        response.raise_for_status()
    content = response.json()["choices"][0]["message"]["content"]
    result = parse_json_object(content)
    for key in (
        "quality_score",
        "brand_fit_score",
        "object_accuracy_score",
        "visual_error_score",
        "overall_score",
    ):
        result[key] = float(result[key])
    return result


async def evaluate_trial(
    case: dict[str, Any],
    copy_model: AdModel,
    image_model: ImageModel,
    repeat: int,
    clip_model: str,
    vision_judge_model: str | None,
    vision_judge_base_url: str,
    vision_judge_api_key: str | None,
    vision_judge_timeout_seconds: float,
    image_output_dir: Path,
    image_width: int | None,
    image_height: int | None,
    guidance_scale_override: float | None,
    num_inference_steps_override: int | None,
    skip_clip: bool,
    semaphore: asyncio.Semaphore,
) -> dict[str, Any]:
    queued_at = perf_counter()
    async with semaphore:
        started_at = perf_counter()
        queue_wait_ms = round((started_at - queued_at) * 1000, 2)
        copy_request = build_copy_request(case, copy_model)
        record: dict[str, Any] = {
            "case_id": case["id"],
            "repeat": repeat,
            "copy_model": copy_model.value,
            "copy_provider": get_model_spec(copy_model).provider,
            "image_model": image_model.value,
            "queue_wait_ms": queue_wait_ms,
            "copy_generation_success": False,
            "image_generation_success": False,
            "image_payload_valid": None,
            "clip_score": None,
            "vision_judge_overall_score": None,
            "error_type": None,
            "error": None,
        }

        try:
            copy = await generate_ad_copy(copy_request)
            product_visualization = await visualize_products(copy_request, copy)
            image_prompt, negative_prompt = normalize_image_prompt(
                copy,
                copy_request,
                product_visualization,
            )
            clip_eval_prompt = build_clip_eval_prompt(
                copy,
                copy_request,
                product_visualization,
            )
        except (ModelProviderError, ModelNotConfiguredError, InvalidModelOutputError) as error:
            record.update(
                {
                    "error_type": type(error).__name__,
                    "error": str(error),
                    "wall_latency_ms": round((perf_counter() - started_at) * 1000, 2),
                }
            )
            return record

        record.update(
            {
                "copy_generation_success": True,
                "copy_latency_ms": copy.latency_ms,
                "image_prompt": image_prompt,
                "clip_eval_prompt": clip_eval_prompt,
                "negative_prompt": negative_prompt,
            }
        )

        try:
            seed = deterministic_seed(case["id"], image_model, repeat)
            width = image_width if image_width is not None else case.get("image_width", 1024)
            height = image_height if image_height is not None else case.get("image_height", 1280)
            guidance_scale = (
                guidance_scale_override
                if guidance_scale_override is not None
                else case.get("guidance_scale", 3.5)
            )
            num_inference_steps = (
                num_inference_steps_override
                if num_inference_steps_override is not None
                else case.get("num_inference_steps", 28)
            )
            image = await generate_ad_image(
                AdImageRequest(
                    model=image_model,
                    prompt=image_prompt,
                    negative_prompt=negative_prompt,
                    width=width,
                    height=height,
                    guidance_scale=guidance_scale,
                    num_inference_steps=num_inference_steps,
                    seed=seed,
                )
            )
        except (ImageModelProviderError, ImageModelNotConfiguredError) as error:
            record.update(
                {
                    "error_type": type(error).__name__,
                    "error": str(error),
                    "wall_latency_ms": round((perf_counter() - started_at) * 1000, 2),
                }
            )
            return record

        record.update(
            {
                "image_generation_success": True,
                "image_latency_ms": image.latency_ms,
                "media_type": image.media_type,
                "width": width,
                "height": height,
                "guidance_scale": guidance_scale,
                "num_inference_steps": num_inference_steps,
                "seed": seed,
            }
        )

        try:
            image_path = save_generated_image(
                image_base64=image.image_base64,
                media_type=image.media_type,
                image_dir=image_output_dir,
                case_id=case["id"],
                image_model=image_model,
                repeat=repeat,
            )
            image_bytes = decode_image_base64(image.image_base64)
            clip_result = None
            if not skip_clip:
                clip_result = calculate_clip_score(
                    prompt=clip_eval_prompt,
                    image_bytes=image_bytes,
                    model_name=clip_model,
                )
        except InvalidImagePayloadError as error:
            record.update(
                {
                    "image_payload_valid": False,
                    "error_type": type(error).__name__,
                    "error": str(error),
                    "wall_latency_ms": round((perf_counter() - started_at) * 1000, 2),
                }
            )
            return record
        except VisionMetricDependencyError as error:
            record.update(
                {
                    "image_payload_valid": True,
                    "image_path": str(
                        Path("images") / image_path.relative_to(image_output_dir)
                    ),
                    "metric_error_type": type(error).__name__,
                    "metric_error": str(error),
                    "wall_latency_ms": round((perf_counter() - started_at) * 1000, 2),
                }
            )
            return record
        except (RuntimeError, ValueError) as error:
            record.update(
                {
                    "image_payload_valid": True,
                    "image_path": str(
                        Path("images") / image_path.relative_to(image_output_dir)
                    ),
                    "metric_error_type": type(error).__name__,
                    "metric_error": str(error),
                    "wall_latency_ms": round((perf_counter() - started_at) * 1000, 2),
                }
            )
            return record

        record.update(
            {
                "image_payload_valid": True,
                "image_path": str(
                    Path("images") / image_path.relative_to(image_output_dir)
                ),
                "wall_latency_ms": round((perf_counter() - started_at) * 1000, 2),
            }
        )
        if clip_result is not None:
            record.update(
                {
                    "clip_score": clip_result["score"],
                    "clip_model": clip_result["model_name"],
                }
            )
        else:
            record["metric_skipped"] = "clip_score"

        if vision_judge_model:
            if not vision_judge_api_key:
                record.update(
                    {
                        "judge_error_type": "MissingVisionJudgeApiKey",
                        "judge_error": "Vision judge model was set but API key was missing.",
                    }
                )
                return record

            judge_started_at = perf_counter()
            try:
                judge_result = await judge_generated_image(
                    image_base64=image.image_base64,
                    media_type=image.media_type,
                    prompt=image_prompt,
                    model=vision_judge_model,
                    base_url=vision_judge_base_url,
                    api_key=vision_judge_api_key,
                    timeout_seconds=vision_judge_timeout_seconds,
                )
            except (
                httpx.HTTPError,
                KeyError,
                json.JSONDecodeError,
                TypeError,
                ValueError,
            ) as error:
                record.update(
                    {
                        "judge_error_type": type(error).__name__,
                        "judge_error": str(error),
                    }
                )
                return record

            record.update(
                {
                    "vision_judge_model": vision_judge_model,
                    "vision_judge_latency_ms": round(
                        (perf_counter() - judge_started_at) * 1000,
                        2,
                    ),
                    "vision_judge": judge_result,
                    "vision_judge_overall_score": judge_result["overall_score"],
                }
            )
        return record


def percent(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator * 100, 2) if denominator else None


def average(values: list[float]) -> float | None:
    return round(mean(values), 6) if values else None


def standard_deviation(values: list[float]) -> float | None:
    if not values:
        return None
    return round(stdev(values), 6) if len(values) > 1 else 0.0


def display_metric(value: Any, fallback: str = "Not measured") -> Any:
    return fallback if value is None else value


def summarize_model(
    copy_model: AdModel,
    image_model: ImageModel,
    records: list[dict[str, Any]],
    duration_seconds: float,
) -> dict[str, Any]:
    clip_scores = [
        float(record["clip_score"])
        for record in records
        if record.get("clip_score") is not None
    ]
    judge_scores = [
        float(record["vision_judge_overall_score"])
        for record in records
        if record.get("vision_judge_overall_score") is not None
    ]
    successes = [
        record
        for record in records
        if (
            record["copy_generation_success"]
            and record["image_generation_success"]
            and record["image_payload_valid"] is True
        )
    ]
    latencies = [
        float(record["wall_latency_ms"])
        for record in successes
        if record.get("wall_latency_ms") is not None
    ]
    image_latencies = [
        float(record["image_latency_ms"])
        for record in successes
        if record.get("image_latency_ms") is not None
    ]
    image_failures = [
        record
        for record in records
        if (
            not record["copy_generation_success"]
            or not record["image_generation_success"]
            or record["image_payload_valid"] is False
        )
    ]
    metric_failures = [
        record
        for record in records
        if record.get("metric_error_type") or record.get("judge_error_type")
    ]
    queue_waits = [float(record["queue_wait_ms"]) for record in records]

    return {
        "copy_model": copy_model.value,
        "image_model": image_model.value,
        "requests": len(records),
        "vision_quality": {
            "clip_score_mean": average(clip_scores),
            "clip_score_std": standard_deviation(clip_scores),
            "clip_score_samples": len(clip_scores),
            "clip_score_success_rate_percent": percent(len(clip_scores), len(records)),
            "vision_judge_overall_mean": average(judge_scores),
            "vision_judge_overall_std": standard_deviation(judge_scores),
            "vision_judge_samples": len(judge_scores),
            "vision_judge_success_rate_percent": percent(len(judge_scores), len(records)),
            "metric_failure_rate_percent": percent(len(metric_failures), len(records)),
            "failure_rate_percent": percent(len(image_failures), len(records)),
        },
        "serving_quality": {
            "task_success_rate_percent": percent(len(successes), len(records)),
            "image_generation_success_rate_percent": percent(len(successes), len(records)),
            "mean_latency_ms": round(mean(latencies), 2) if latencies else None,
            "p50_latency_ms": percentile(latencies, 0.50),
            "p95_latency_ms": percentile(latencies, 0.95),
            "p99_latency_ms": percentile(latencies, 0.99),
            "mean_image_latency_ms": (
                round(mean(image_latencies), 2) if image_latencies else None
            ),
            "p95_image_latency_ms": percentile(image_latencies, 0.95),
            "mean_client_queue_wait_ms": round(mean(queue_waits), 2) if queue_waits else None,
            "p95_client_queue_wait_ms": percentile(queue_waits, 0.95),
            "throughput_requests_per_second": (
                round(len(records) / duration_seconds, 4) if duration_seconds else None
            ),
            "provider_queue_wait_ms": None,
            "gpu_utilization_percent": None,
            "vram_peak_gb": None,
        },
        "errors": {
            error_type: sum(record.get("error_type") == error_type for record in records)
            for error_type in {
                record["error_type"] for record in records if record.get("error_type")
            }
        },
        "metric_errors": {
            error_type: sum(
                record.get("metric_error_type") == error_type for record in records
            )
            for error_type in {
                record["metric_error_type"]
                for record in records
                if record.get("metric_error_type")
            }
        },
    }


async def evaluate_model(
    copy_model: AdModel,
    image_model: ImageModel,
    cases: list[dict[str, Any]],
    repeats: int,
    concurrency: int,
    clip_model: str,
    vision_judge_model: str | None,
    vision_judge_base_url: str,
    vision_judge_api_key: str | None,
    vision_judge_timeout_seconds: float,
    image_output_dir: Path,
    image_width: int | None,
    image_height: int | None,
    guidance_scale: float | None,
    num_inference_steps: int | None,
    skip_clip: bool,
) -> tuple[list[dict[str, Any]], float]:
    semaphore = asyncio.Semaphore(concurrency)
    started_at = perf_counter()
    tasks = [
        evaluate_trial(
            case,
            copy_model,
            image_model,
            repeat,
            clip_model,
            vision_judge_model,
            vision_judge_base_url,
            vision_judge_api_key,
            vision_judge_timeout_seconds,
            image_output_dir,
            image_width,
            image_height,
            guidance_scale,
            num_inference_steps,
            skip_clip,
            semaphore,
        )
        for case in cases
        for repeat in range(1, repeats + 1)
    ]
    records = await asyncio.gather(*tasks)
    return records, perf_counter() - started_at


def markdown_report(report: dict[str, Any]) -> str:
    vision_judge_enabled = report["metadata"]["vision_judge_model"] is not None
    lines = [
        "# BrandMate 비전 모델 평가 보고서",
        "",
        f"- 생성 시각: {report['metadata']['generated_at']}",
        f"- 평가 케이스: {report['metadata']['case_count']}개",
        f"- 반복 횟수: {report['metadata']['repeats']}회",
        f"- 동시성: {report['metadata']['concurrency']}",
        f"- Copy 모델: {report['metadata']['copy_model']}",
        f"- CLIP 모델: {report['metadata']['clip_model']}",
        f"- Vision Judge 모델: {report['metadata']['vision_judge_model'] or 'disabled'}",
        "",
        "## Vision Model Quality",
        "",
        "| Copy 모델 | Image 모델 | 요청 수 | CLIP Mean | CLIP Std | CLIP Samples | "
        "Judge Mean | Judge Samples | Metric Failure | Image Failure |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for summary in report["model_summaries"]:
        quality = summary["vision_quality"]
        judge_fallback = "Disabled" if not vision_judge_enabled else "Not measured"
        lines.append(
            f"| {summary['copy_model']} | {summary['image_model']} | {summary['requests']} | "
            f"{display_metric(quality['clip_score_mean'])} | "
            f"{display_metric(quality['clip_score_std'])} | "
            f"{quality['clip_score_samples']} | "
            f"{display_metric(quality['vision_judge_overall_mean'], judge_fallback)} | "
            f"{quality['vision_judge_samples']} | "
            f"{quality['metric_failure_rate_percent']}% | "
            f"{quality['failure_rate_percent']}% |"
        )

    lines.extend(
        [
            "",
            "## Serving Quality",
            "",
            "| Image 모델 | 이미지 생성 성공률 | Pipeline Mean | P50 | P95 | P99 | Image Mean | "
            "Image P95 | Queue Mean | Queue P95 | 처리량(req/s) |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for summary in report["model_summaries"]:
        serving = summary["serving_quality"]
        lines.append(
            f"| {summary['image_model']} | "
            f"{serving['image_generation_success_rate_percent']}% | "
            f"{serving['mean_latency_ms']}ms | "
            f"{serving['p50_latency_ms']}ms | {serving['p95_latency_ms']}ms | "
            f"{serving['p99_latency_ms']}ms | "
            f"{serving['mean_image_latency_ms']}ms | "
            f"{serving['p95_image_latency_ms']}ms | "
            f"{serving['mean_client_queue_wait_ms']}ms | "
            f"{serving['p95_client_queue_wait_ms']}ms | "
            f"{serving['throughput_requests_per_second']} |"
        )

    lines.extend(
        [
            "",
            "## 현재 측정 제한",
            "",
            "- Aesthetic Score: predictor weight 경로를 정한 뒤 runner에 추가",
            "- Diversity Score: 동일 프롬프트의 복수 이미지 생성 후 임베딩 거리로 추가",
            "- Provider Queue Waiting Time: provider 내부 대기열 정보가 없어 미측정",
            "- GPU Utilization / VRAM Usage: NVML 기반 샘플링을 붙인 뒤 측정",
            "- Vision Judge: --vision-judge-model을 지정한 경우에만 유료 API로 선택 실행",
            "- Human Preference: 2차 검증 지표로 분리",
            "",
        ]
    )
    return "\n".join(lines)


async def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    args = parse_args()
    if args.repeats < 1 or args.concurrency < 1:
        raise SystemExit("repeats와 concurrency는 1 이상이어야 합니다.")
    if args.image_width is not None and args.image_width < 64:
        raise SystemExit("image-width는 64 이상이어야 합니다.")
    if args.image_height is not None and args.image_height < 64:
        raise SystemExit("image-height는 64 이상이어야 합니다.")
    if args.num_inference_steps is not None and args.num_inference_steps < 1:
        raise SystemExit("num-inference-steps는 1 이상이어야 합니다.")

    cases = load_cases(args.dataset, args.case_limit)
    copy_model = AdModel(args.copy_model) if args.copy_model else AdModel.QWEN_2_5_7B
    selected_image_models = (
        [ImageModel(model) for model in args.image_models]
        if args.image_models
        else [ImageModel.FLUX_SCHNELL]
    )
    vision_judge_api_key = (
        os.getenv(args.vision_judge_api_key_env)
        if args.vision_judge_model
        else None
    )

    await preflight_environment(
        copy_model,
        selected_image_models,
        args.clip_model,
        args.skip_clip,
    )

    run_started_at = datetime.now()
    run_date = run_started_at.strftime("%Y%m%d")
    run_time = run_started_at.strftime("%H%M%S")
    run_id = f"{run_date}-{run_time}"
    run_dir = args.output_dir / "vision" / run_date / run_time
    image_output_dir = run_dir / "images"
    all_records: list[dict[str, Any]] = []
    summaries = []

    for image_model in selected_image_models:
        print(
            f"비전 평가 중: copy={copy_model.value}, image={image_model.value}",
            flush=True,
        )
        records, duration = await evaluate_model(
            copy_model,
            image_model,
            cases,
            args.repeats,
            args.concurrency,
            args.clip_model,
            args.vision_judge_model,
            args.vision_judge_base_url,
            vision_judge_api_key,
            args.vision_judge_timeout_seconds,
            image_output_dir,
            args.image_width,
            args.image_height,
            args.guidance_scale,
            args.num_inference_steps,
            args.skip_clip,
        )
        all_records.extend(records)
        summaries.append(summarize_model(copy_model, image_model, records, duration))

    report = {
        "metadata": {
            "run_id": run_id,
            "run_date": run_date,
            "run_time": run_time,
            "generated_at": datetime.now(UTC).isoformat(),
            "git_commit": git_commit(),
            "dataset": str(args.dataset),
            "case_count": len(cases),
            "repeats": args.repeats,
            "concurrency": args.concurrency,
            "copy_model": copy_model.value,
            "image_models": [model.value for model in selected_image_models],
            "clip_model": args.clip_model,
            "clip_enabled": not args.skip_clip,
            "image_width_override": args.image_width,
            "image_height_override": args.image_height,
            "guidance_scale_override": args.guidance_scale,
            "num_inference_steps_override": args.num_inference_steps,
            "vision_judge_model": args.vision_judge_model,
            "vision_judge_base_url": (
                args.vision_judge_base_url if args.vision_judge_model else None
            ),
            "image_output_dir": "images",
        },
        "model_summaries": summaries,
        "trials": all_records,
    }

    run_dir.mkdir(parents=True, exist_ok=True)
    json_path = run_dir / "report.json"
    markdown_path = run_dir / "report.md"
    json_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    markdown_path.write_text(markdown_report(report), encoding="utf-8")

    saved_images = sorted(image_output_dir.rglob("*")) if image_output_dir.exists() else []
    saved_image_files = [
        path
        for path in saved_images
        if path.is_file() and path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}
    ]

    print(f"JSON 보고서: {json_path}")
    print(f"Markdown 보고서: {markdown_path}")
    if saved_image_files:
        print(f"생성 이미지 폴더: {image_output_dir}")
        print(f"생성 이미지 수: {len(saved_image_files)}")
    else:
        print("생성 이미지 없음: 이미지 생성 실패 또는 저장 가능한 이미지가 없습니다.")


if __name__ == "__main__":
    asyncio.run(main())
