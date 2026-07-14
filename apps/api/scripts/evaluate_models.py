"""Evaluate ad-copy models and write JSON/Markdown reports."""

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean
from time import perf_counter
from typing import Any

from app.evaluation.metrics import (
    context_adherence_score,
    hallucination_terms,
    hashtag_compliance_rate,
    headline_diversity_score,
    is_english_image_prompt,
    percentile,
    tone_manner_proxy_score,
    toxicity_terms,
)
from app.modules.ad_copy.models import MODEL_CATALOG, get_model_spec
from app.modules.ad_copy.schemas import AdCopyRequest, AdModel
from app.modules.ad_copy.service import (
    InvalidModelOutputError,
    ModelNotConfiguredError,
    ModelProviderError,
    generate_ad_copy,
)


API_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = API_ROOT.parents[1]
DEFAULT_DATASET = API_ROOT / "evals" / "ad_copy_cases.json"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "outputs" / "evaluations"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--models", nargs="*", choices=[model.value for model in AdModel])
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--concurrency", type=int, default=1)
    parser.add_argument("--case-limit", type=int)
    parser.add_argument("--gpu-vram-gb", type=float)
    return parser.parse_args()


def load_cases(path: Path, case_limit: int | None) -> list[dict[str, Any]]:
    cases = json.loads(path.read_text(encoding="utf-8"))
    return cases[:case_limit] if case_limit else cases


async def evaluate_trial(
    case: dict[str, Any],
    model: AdModel,
    repeat: int,
    semaphore: asyncio.Semaphore,
) -> dict[str, Any]:
    queued_at = perf_counter()
    async with semaphore:
        started_at = perf_counter()
        queue_wait_ms = round((started_at - queued_at) * 1000, 2)
        request = AdCopyRequest.model_validate({**case["request"], "model": model})
        record: dict[str, Any] = {
            "case_id": case["id"],
            "repeat": repeat,
            "model": model.value,
            "provider": get_model_spec(model).provider,
            "queue_wait_ms": queue_wait_ms,
        }

        try:
            result = await generate_ad_copy(request)
        except (ModelProviderError, ModelNotConfiguredError) as error:
            record.update(
                {
                    "success": False,
                    "error_type": type(error).__name__,
                    "error": str(error),
                    "wall_latency_ms": round((perf_counter() - started_at) * 1000, 2),
                    "json_compliant_first_attempt": None,
                }
            )
            return record
        except InvalidModelOutputError as error:
            record.update(
                {
                    "success": False,
                    "error_type": type(error).__name__,
                    "error": str(error),
                    "wall_latency_ms": round((perf_counter() - started_at) * 1000, 2),
                    "json_compliant_first_attempt": False,
                }
            )
            return record

        unsupported_terms = hallucination_terms(request, result)
        unsafe_terms = toxicity_terms(result)
        record.update(
            {
                "success": True,
                "error_type": None,
                "error": None,
                "wall_latency_ms": round((perf_counter() - started_at) * 1000, 2),
                "model_latency_ms": result.latency_ms,
                "attempts": result.attempts,
                "json_compliant_first_attempt": not result.output_repaired,
                "context_adherence_score": context_adherence_score(request, result),
                "tone_manner_proxy_score": tone_manner_proxy_score(request, result),
                "hallucination_terms": unsupported_terms,
                "toxicity_terms": unsafe_terms,
                "hashtag_compliance_rate": hashtag_compliance_rate(result),
                "image_prompt_english": is_english_image_prompt(result),
                "headline_diversity_score": headline_diversity_score(result),
                "output": result.model_dump(),
            }
        )
        return record


def average(records: list[dict[str, Any]], key: str) -> float | None:
    values = [record[key] for record in records if record.get(key) is not None]
    return round(mean(values), 4) if values else None


def percent(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator * 100, 2) if denominator else None


def summarize_model(
    model: AdModel,
    records: list[dict[str, Any]],
    duration_seconds: float,
) -> dict[str, Any]:
    successes = [record for record in records if record["success"]]
    schema_eligible = [
        record
        for record in records
        if record.get("json_compliant_first_attempt") is not None
    ]
    latencies = [record["wall_latency_ms"] for record in successes]
    queue_waits = [record["queue_wait_ms"] for record in records]
    hallucinated = sum(bool(record["hallucination_terms"]) for record in successes)
    toxic = sum(bool(record["toxicity_terms"]) for record in successes)

    return {
        "model": model.value,
        "provider": get_model_spec(model).provider,
        "requests": len(records),
        "model_quality": {
            "json_compliance_rate_percent": percent(
                sum(bool(record["json_compliant_first_attempt"]) for record in schema_eligible),
                len(schema_eligible),
            ),
            "context_adherence_score_5": (
                round(average(successes, "context_adherence_score") * 5, 2)
                if successes
                else None
            ),
            "tone_manner_proxy_score_5": (
                round(average(successes, "tone_manner_proxy_score") * 5, 2)
                if successes
                else None
            ),
            "hallucination_rate_percent": percent(hallucinated, len(successes)),
            "toxicity_rate_percent": percent(toxic, len(successes)),
            "hashtag_compliance_rate_percent": (
                round(average(successes, "hashtag_compliance_rate") * 100, 2)
                if successes
                else None
            ),
            "english_image_prompt_rate_percent": percent(
                sum(record["image_prompt_english"] for record in successes),
                len(successes),
            ),
            "headline_diversity_score": average(successes, "headline_diversity_score"),
        },
        "serving_quality": {
            "task_success_rate_percent": percent(len(successes), len(records)),
            "mean_latency_ms": round(mean(latencies), 2) if latencies else None,
            "p50_latency_ms": percentile(latencies, 0.50),
            "p95_latency_ms": percentile(latencies, 0.95),
            "p99_latency_ms": percentile(latencies, 0.99),
            "mean_client_queue_wait_ms": round(mean(queue_waits), 2),
            "p95_client_queue_wait_ms": percentile(queue_waits, 0.95),
            "throughput_requests_per_second": round(
                len(records) / duration_seconds,
                4,
            )
            if duration_seconds
            else None,
            "tpot_ms": None,
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
    }


async def evaluate_model(
    model: AdModel,
    cases: list[dict[str, Any]],
    repeats: int,
    concurrency: int,
) -> tuple[list[dict[str, Any]], float]:
    semaphore = asyncio.Semaphore(concurrency)
    started_at = perf_counter()
    tasks = [
        evaluate_trial(case, model, repeat, semaphore)
        for case in cases
        for repeat in range(1, repeats + 1)
    ]
    records = await asyncio.gather(*tasks)
    return records, perf_counter() - started_at


def markdown_report(report: dict[str, Any]) -> str:
    lines = [
        "# BrandMate 모델 평가 보고서",
        "",
        f"- 생성 시각: {report['metadata']['generated_at']}",
        f"- 평가 케이스: {report['metadata']['case_count']}개",
        f"- 반복 횟수: {report['metadata']['repeats']}회",
        f"- 동시성: {report['metadata']['concurrency']}",
        "",
        "## LLM Model Quality",
        "",
        "| 모델 | 성공률 | JSON | 문맥(5) | 톤(5) | 환각률 | 해시태그 | 영문 이미지 프롬프트 |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for summary in report["model_summaries"]:
        quality = summary["model_quality"]
        serving = summary["serving_quality"]
        lines.append(
            f"| {summary['model']} | {serving['task_success_rate_percent']}% | "
            f"{quality['json_compliance_rate_percent']}% | "
            f"{quality['context_adherence_score_5']} | "
            f"{quality['tone_manner_proxy_score_5']} | "
            f"{quality['hallucination_rate_percent']}% | "
            f"{quality['hashtag_compliance_rate_percent']}% | "
            f"{quality['english_image_prompt_rate_percent']}% |"
        )

    lines.extend(
        [
            "",
            "## Serving Quality",
            "",
            "| 모델 | Mean | P50 | P95 | P99 | 처리량(req/s) |",
            "| --- | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for summary in report["model_summaries"]:
        serving = summary["serving_quality"]
        lines.append(
            f"| {summary['model']} | {serving['mean_latency_ms']}ms | "
            f"{serving['p50_latency_ms']}ms | {serving['p95_latency_ms']}ms | "
            f"{serving['p99_latency_ms']}ms | "
            f"{serving['throughput_requests_per_second']} |"
        )

    lines.extend(
        [
            "",
            "## 현재 측정 제한",
            "",
            "- TPOT: 비스트리밍 Hosted API이므로 정확한 토큰별 타임스탬프가 없어 미측정",
            "- Provider Queue Waiting Time: 외부 Provider 내부 대기열이 공개되지 않아 미측정",
            "- GPU Utilization / VRAM Usage: 자체 vLLM 또는 NIM 서버 배포 후 측정 가능",
            "- Vision 지표: 실제 이미지 생성 모델 연결 후 CLIP, ImageReward, Aesthetic 평가 가능",
            "- Tone 점수와 Hallucination은 현재 규칙 기반 프록시이며 추후 Judge 평가로 교체 가능",
            "",
        ]
    )
    return "\n".join(lines)


async def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    args = parse_args()
    if args.repeats < 1 or args.concurrency < 1:
        raise SystemExit("repeats와 concurrency는 1 이상이어야 합니다.")

    cases = load_cases(args.dataset, args.case_limit)
    selected_models = (
        [AdModel(model) for model in args.models]
        if args.models
        else [spec.id for spec in MODEL_CATALOG]
    )
    all_records: list[dict[str, Any]] = []
    summaries = []

    for model in selected_models:
        print(f"평가 중: {model.value}", flush=True)
        records, duration = await evaluate_model(
            model,
            cases,
            args.repeats,
            args.concurrency,
        )
        all_records.extend(records)
        summaries.append(summarize_model(model, records, duration))

    report = {
        "metadata": {
            "generated_at": datetime.now(UTC).isoformat(),
            "dataset": str(args.dataset),
            "case_count": len(cases),
            "repeats": args.repeats,
            "concurrency": args.concurrency,
            "declared_gpu_vram_gb": args.gpu_vram_gb,
        },
        "vision_quality": {
            "status": "not_available",
            "reason": "실제 이미지 생성 모델이 아직 연결되지 않았습니다.",
            "planned_metrics": [
                "clip_score",
                "aesthetic_score",
                "failure_rate",
                "diversity_score",
                "gpt_4o_vision_judge",
                "human_preference",
                "image_reward",
            ],
        },
        "model_summaries": summaries,
        "trials": all_records,
    }

    args.output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    json_path = args.output_dir / f"llm-evaluation-{timestamp}.json"
    markdown_path = args.output_dir / f"llm-evaluation-{timestamp}.md"
    json_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    markdown_path.write_text(markdown_report(report), encoding="utf-8")

    print(f"JSON 보고서: {json_path}")
    print(f"Markdown 보고서: {markdown_path}")


if __name__ == "__main__":
    asyncio.run(main())
