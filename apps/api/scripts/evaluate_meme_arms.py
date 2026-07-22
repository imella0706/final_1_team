"""Run a blinded, single-TrendCard comparison of prompt strategies and LoRA."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import html
import json
import random
import re
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean
from time import perf_counter
from typing import Any

from pydantic import ValidationError

from app.evaluation.meme_arm_runner import (
    LoadedMemeExperiment,
    MemeEvalArm,
    MemeEvalCase,
    MemeExperimentDataError,
    build_arm_messages,
    find_example_leakage,
    generate_arm_copy,
    load_meme_experiment,
    marker_compliance,
    parse_failure_type,
    resolve_generation_endpoint,
    visible_context_adherence_score,
    visible_hallucination_terms,
    visible_required_term_compliance_rate,
    visible_toxicity_terms,
)
from app.evaluation.metrics import (
    hashtag_compliance_rate,
)
from app.evaluation.text_judge import (
    InvalidMemeJudgeOutputError,
    JUDGE_PROMPT_VERSION,
    MemeJudgeNotConfiguredError,
    MemeJudgeProviderError,
    judge_meme_copy_with_metadata,
)
from app.modules.ad_copy.schemas import AdCopyRequest, AdCopyResponse
from app.modules.ad_copy.prompt import PROMPT_VERSION
from app.modules.model_runtime.llm.registry import (
    get_text_model_config,
    resolve_api_key,
)


API_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = API_ROOT.parents[1]
DEFAULT_CONFIG = API_ROOT / "evals" / "meme_5arm_experiment.json"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "outputs" / "evaluations" / "meme"
JUDGE_SCORE_KEYS = (
    "naturalness",
    "pattern_fidelity",
    "product_relevance",
    "factuality",
    "channel_readiness",
    "overall_score",
)
DEFAULT_EXTERNAL_REQUEST_LIMIT = 20

OPERATIONAL_FAILURE_LABELS = {
    "generation_failed": "광고 문구 생성 실패",
    "production_rule_validation_failed": "Production validator 실패",
    "required_term_metric_unavailable": "필수어 반영률을 계산할 수 없음",
    "required_terms_missing": "필수어 누락",
    "hashtag_metric_unavailable": "해시태그 형식 준수율을 계산할 수 없음",
    "hashtag_format_noncompliant": "해시태그 형식 오류",
    "few_shot_example_leakage": "Few-shot 예시 정보 누출",
    "unsupported_claim_detected": "입력으로 뒷받침되지 않는 표현 감지",
    "unsafe_expression_detected": "유해 표현 감지",
    "channel_recommendation_missing": "채널 게시물 정보 누락",
    "korean_customer_copy_missing": "고객 노출 문구에 한국어가 없음",
    "instagram_caption_contains_hashtags": "Instagram caption에 해시태그가 섞임",
    "instagram_publish_cta_missing": "Instagram publish_cta 누락",
    "instagram_publish_body_missing_cta": "Instagram publish_body에 CTA 누락",
    "instagram_publish_hashtags_missing": "Instagram publish_hashtags 누락",
    "instagram_publish_body_missing_hashtags": (
        "Instagram publish_body에 publish_hashtags 누락"
    ),
}


def _output_contract_failure_reasons(record: dict[str, Any]) -> list[str]:
    output = record.get("output")
    if not isinstance(output, dict):
        return []

    recommendation = output.get("channel_recommendation")
    if not isinstance(recommendation, dict):
        return ["channel_recommendation_missing"]

    visible_values: list[str] = []
    for field in ("headlines", "body_copies", "ctas", "hashtags"):
        values = output.get(field)
        if isinstance(values, list):
            visible_values.extend(value for value in values if isinstance(value, str))
    for field in (
        "overlay_headline",
        "caption",
        "publish_cta",
        "publish_title",
        "publish_body",
        "blog_title",
    ):
        value = recommendation.get(field)
        if isinstance(value, str):
            visible_values.append(value)

    reasons: list[str] = []
    if visible_values and not re.search(r"[가-힣]", " ".join(visible_values)):
        reasons.append("korean_customer_copy_missing")

    format_name = str(recommendation.get("format_name") or "").casefold()
    channel = str(record.get("channel") or "").casefold()
    if channel != "instagram" and format_name != "instagram":
        return reasons

    caption = str(recommendation.get("caption") or "").strip()
    publish_body = str(recommendation.get("publish_body") or "")
    publish_cta = str(recommendation.get("publish_cta") or "").strip()
    publish_hashtags = recommendation.get("publish_hashtags")

    if re.search(r"(?<!\w)#[0-9A-Za-z가-힣_]+", caption):
        reasons.append("instagram_caption_contains_hashtags")
    if not publish_cta:
        reasons.append("instagram_publish_cta_missing")
    elif publish_cta not in publish_body:
        reasons.append("instagram_publish_body_missing_cta")
    if not isinstance(publish_hashtags, list) or not publish_hashtags:
        reasons.append("instagram_publish_hashtags_missing")
    else:
        missing_hashtags = [
            tag
            for tag in publish_hashtags
            if isinstance(tag, str) and tag.strip() and tag.strip() not in publish_body
        ]
        if missing_hashtags:
            reasons.append("instagram_publish_body_missing_hashtags")
    return reasons


def operational_failure_reasons(record: dict[str, Any]) -> list[str]:
    """Return deterministic release-gate failures for one trial.

    The release gate remains separate from the qualitative LLM Judge score and
    can derive validity for reports created before ``operational_valid`` was
    persisted.
    """

    if not record.get("generation_success"):
        return ["generation_failed"]

    reasons: list[str] = []
    if not record.get("rule_valid"):
        warnings = record.get("rule_warnings")
        if isinstance(warnings, list) and warnings:
            reasons.extend(f"production_rule: {warning}" for warning in warnings)
        else:
            reasons.append("production_rule_validation_failed")

    required_rate = record.get("required_term_compliance_rate")
    if not isinstance(required_rate, (int, float)):
        reasons.append("required_term_metric_unavailable")
    elif float(required_rate) < 1.0:
        reasons.append("required_terms_missing")

    hashtag_rate = record.get("hashtag_compliance_rate")
    if not isinstance(hashtag_rate, (int, float)):
        reasons.append("hashtag_metric_unavailable")
    elif float(hashtag_rate) < 1.0:
        reasons.append("hashtag_format_noncompliant")

    for field, label in (
        ("example_leakage_terms", "few_shot_example_leakage"),
        ("hallucination_terms", "unsupported_claim_detected"),
        ("toxicity_terms", "unsafe_expression_detected"),
    ):
        if record.get(field):
            reasons.append(label)
    reasons.extend(_output_contract_failure_reasons(record))
    return reasons


def record_operationally_valid(record: dict[str, Any]) -> bool:
    """Whether one output passes every deterministic release gate."""

    return not operational_failure_reasons(record)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument(
        "--render-report",
        type=Path,
        help="기존 report.json의 요약과 report.md만 재생성하며 외부 API는 호출하지 않음",
    )
    parser.add_argument("--arms", nargs="*", help="arm id 목록. 생략하면 활성 arm 전체")
    parser.add_argument("--case-limit", type=int)
    parser.add_argument("--repeats", type=int)
    parser.add_argument("--concurrency", type=int)
    parser.add_argument("--skip-judge", action="store_true")
    parser.add_argument(
        "--allow-large-run",
        action="store_true",
        help="최대 외부 HTTP 요청이 20회를 넘는 평가를 명시적으로 허용",
    )
    parser.add_argument(
        "--allow-unreviewed-fixtures",
        action="store_true",
        help="사람 검수 전 fixture로 1 case × 1 repeat engineering smoke만 허용",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="JSON/프롬프트/API 설정만 검증하고 외부 API는 호출하지 않음",
    )
    return parser.parse_args()


def select_arms(loaded: LoadedMemeExperiment, requested: list[str] | None) -> list[MemeEvalArm]:
    by_id = {arm.id: arm for arm in loaded.config.arms}
    if requested:
        unknown = sorted(set(requested) - set(by_id))
        if unknown:
            raise MemeExperimentDataError(f"알 수 없는 arm id: {', '.join(unknown)}")
        selected = [by_id[arm_id] for arm_id in requested]
        disabled = [arm for arm in selected if not arm.enabled]
        if disabled:
            details = "; ".join(
                f"{arm.id}: {arm.disabled_reason or '비활성'}" for arm in disabled
            )
            raise MemeExperimentDataError(f"비활성 arm은 실행할 수 없습니다: {details}")
        return selected
    return [arm for arm in loaded.config.arms if arm.enabled]


def select_cases(
    loaded: LoadedMemeExperiment,
    case_limit: int | None,
) -> list[MemeEvalCase]:
    if case_limit is not None and case_limit < 1:
        raise MemeExperimentDataError("case-limit은 1 이상이어야 합니다")
    return loaded.cases[:case_limit] if case_limit else loaded.cases


def assess_decision_eligibility(
    loaded: LoadedMemeExperiment,
    arms: list[MemeEvalArm],
    cases: list[MemeEvalCase],
    repeats: int,
) -> tuple[bool, list[str]]:
    """Require the configured experiment, not a smoke subset, for a decision."""

    reasons: list[str] = []
    enabled_arm_ids = {arm.id for arm in loaded.config.arms if arm.enabled}
    if {arm.id for arm in arms} != enabled_arm_ids:
        reasons.append("not_all_enabled_arms_selected")
    if {case.id for case in cases} != {case.id for case in loaded.cases}:
        reasons.append("not_all_fixture_cases_selected")
    if repeats < loaded.config.generation.repeats:
        reasons.append("repeats_below_configured_experiment")
    if len(arms) < 2:
        reasons.append("fewer_than_two_arms")
    return not reasons, reasons


def candidate_id(experiment_id: str, case_id: str, repeat: int, arm_id: str) -> str:
    source = f"{experiment_id}:{case_id}:{repeat}:{arm_id}".encode()
    return f"candidate-{hashlib.sha256(source).hexdigest()[:12]}"


def trial_generation_seed(base_seed: int, case_id: str, repeat: int) -> int:
    """Return one paired seed shared by every arm for a case/repeat."""

    source = f"{base_seed}:{case_id}:{repeat}".encode()
    return int(hashlib.sha256(source).hexdigest()[:8], 16) % 2_147_483_648


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_prompt_snapshots(
    loaded: LoadedMemeExperiment,
    arms: list[MemeEvalArm],
    cases: list[MemeEvalCase],
) -> list[dict[str, Any]]:
    snapshots: list[dict[str, Any]] = []
    for case in cases:
        request = request_for_case(loaded, case)
        for arm in arms:
            endpoint = resolve_generation_endpoint(loaded.config, arm)
            messages = build_arm_messages(
                request,
                loaded.trend_card,
                arm,
                loaded.examples,
                supports_system_role=endpoint.supports_system_role,
            )
            serialized = json.dumps(
                messages,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            snapshots.append(
                {
                    "prompt_id": f"{case.id}:{arm.id}",
                    "case_id": case.id,
                    "arm_id": arm.id,
                    "sha256": hashlib.sha256(serialized.encode()).hexdigest(),
                    "messages": messages,
                }
            )
    return snapshots


def request_for_case(loaded: LoadedMemeExperiment, case: MemeEvalCase) -> AdCopyRequest:
    return AdCopyRequest.model_validate(
        {**case.request, "model": loaded.config.base_model}
    )


def _judge_preflight(loaded: LoadedMemeExperiment) -> dict[str, Any]:
    config = get_text_model_config("openai/gpt-4.1-mini")
    api_key = resolve_api_key(config)
    return {
        "ready": bool(api_key),
        "model": loaded.config.judge.model,
        "base_url": loaded.config.judge.base_url,
        "api_key_configured": bool(api_key),
    }


def build_dry_run_report(
    loaded: LoadedMemeExperiment,
    arms: list[MemeEvalArm],
    cases: list[MemeEvalCase],
    repeats: int,
    judge_enabled: bool,
) -> dict[str, Any]:
    arm_checks: list[dict[str, Any]] = []
    for arm in arms:
        endpoint_error: str | None = None
        endpoint_source: str | None = None
        endpoint_model: str | None = None
        try:
            endpoint = resolve_generation_endpoint(loaded.config, arm)
            endpoint_source = endpoint.source
            endpoint_model = endpoint.model
        except Exception as error:  # readiness is reported without exposing credentials
            endpoint_error = str(error)

        prompt_checks = []
        for case in cases:
            request = request_for_case(loaded, case)
            messages = build_arm_messages(
                request,
                loaded.trend_card,
                arm,
                loaded.examples,
            )
            prompt_text = "\n".join(message["content"] for message in messages)
            prompt_checks.append(
                {
                    "case_id": case.id,
                    "message_count": len(messages),
                    "trend_card_included": loaded.trend_card.meme_id in prompt_text,
                    "good_examples_included": (
                        "TrendCard 응용 참고 예시" in prompt_text
                        or "TrendCard 응용 대조 예시" in prompt_text
                    ),
                    "bad_examples_included": "피해야 할 예시" in prompt_text,
                    "internal_planning_included": "내부 작성 절차" in prompt_text,
                }
            )
        arm_checks.append(
            {
                "arm_id": arm.id,
                "strategy": arm.strategy,
                "endpoint_ready": endpoint_error is None,
                "endpoint_error": endpoint_error,
                "endpoint_source": endpoint_source,
                "endpoint_model": endpoint_model,
                "declared_base_revision": arm.base_revision,
                "declared_adapter_revision": arm.adapter_revision,
                "prompt_checks": prompt_checks,
            }
        )

    generator_calls = len(arms) * len(cases) * repeats
    judge_calls = generator_calls if judge_enabled else 0
    return {
        "mode": "dry_run",
        "external_api_called": False,
        "experiment_id": loaded.config.experiment_id,
        "base_model": loaded.config.base_model,
        "trend_card": {
            "meme_id": loaded.trend_card.meme_id,
            "display_name": loaded.trend_card.display_name,
            "path": str(loaded.trend_card_path),
        },
        "case_count": len(cases),
        "few_shot_example_count": len(loaded.examples),
        "artifact_sha256": {
            "config": file_sha256(loaded.config_path),
            "trend_card": file_sha256(loaded.trend_card_path),
            "dataset": file_sha256(loaded.dataset_path),
            "few_shot": file_sha256(loaded.few_shot_path),
            "fixture_review": file_sha256(loaded.fixture_review_path),
        },
        "fixture_review": {
            **loaded.fixture_review.model_dump(mode="json"),
            "decision_ready": loaded.fixture_review.decision_ready,
        },
        "repeats": repeats,
        "generation_seed": loaded.config.generation.generation_seed,
        "active_arms": [arm.id for arm in arms],
        "disabled_arms": [
            {"arm_id": arm.id, "reason": arm.disabled_reason}
            for arm in loaded.config.arms
            if not arm.enabled
        ],
        "planned_calls": {
            "generation_trials": generator_calls,
            "generator_http_requests_nominal": generator_calls,
            "judge_http_requests_maximum": judge_calls,
            "external_http_requests_nominal": generator_calls + judge_calls,
            "external_http_requests_worst_case": generator_calls * 2 + judge_calls,
            "note": (
                "structured response_format를 provider가 거절하면 같은 prompt를 한 번 더 "
                "보낼 수 있어 worst_case에서는 생성 HTTP 요청을 trial당 2회로 계산합니다."
            ),
        },
        "judge": _judge_preflight(loaded) if judge_enabled else {"enabled": False},
        "arm_checks": arm_checks,
    }


def enforce_execution_safety(
    loaded: LoadedMemeExperiment,
    cases: list[MemeEvalCase],
    repeats: int,
    worst_case_requests: int,
    *,
    allow_large_run: bool,
    allow_unreviewed_fixtures: bool,
) -> None:
    if worst_case_requests > DEFAULT_EXTERNAL_REQUEST_LIMIT and not allow_large_run:
        raise MemeExperimentDataError(
            f"이 설정은 외부 HTTP 요청이 최대 {worst_case_requests}회일 수 있습니다. "
            "먼저 --dry-run으로 수를 확인하고, 전체 실행을 의도했다면 "
            "--allow-large-run을 추가하세요."
        )
    if not loaded.fixture_review.decision_ready:
        if not allow_unreviewed_fixtures:
            raise MemeExperimentDataError(
                "평가/few-shot fixture가 아직 사람·권리 검수 전입니다. "
                "engineering smoke만 의도했다면 --case-limit 1 --repeats 1 "
                "--allow-unreviewed-fixtures를 사용하세요."
            )
        if len(cases) != 1 or repeats != 1:
            raise MemeExperimentDataError(
                "미검수 fixture는 1 case × 1 repeat engineering smoke만 허용합니다."
            )


def _metric_response(
    request: AdCopyRequest,
    loaded: LoadedMemeExperiment,
    content_dump: dict[str, Any],
) -> AdCopyResponse:
    return AdCopyResponse(
        **content_dump,
        model=loaded.config.base_model,
        prompt_version="meme-arm-evaluation-v1",
        trend_card_id=loaded.trend_card.meme_id,
    )


async def evaluate_trial(
    loaded: LoadedMemeExperiment,
    case: MemeEvalCase,
    arm: MemeEvalArm,
    repeat: int,
    judge_enabled: bool,
    semaphore: asyncio.Semaphore,
) -> dict[str, Any]:
    queued_at = perf_counter()
    async with semaphore:
        started_at = perf_counter()
        request = request_for_case(loaded, case)
        paired_seed = trial_generation_seed(
            loaded.config.generation.generation_seed,
            case.id,
            repeat,
        )
        record: dict[str, Any] = {
            "candidate_id": candidate_id(
                loaded.config.experiment_id,
                case.id,
                repeat,
                arm.id,
            ),
            "case_id": case.id,
            "case_type": case.case_type,
            "channel": request.channel.value,
            "repeat": repeat,
            "arm_id": arm.id,
            "strategy": arm.strategy,
            "prompt_id": f"{case.id}:{arm.id}",
            "generation_seed": paired_seed,
            "queue_wait_ms": round((started_at - queued_at) * 1000, 2),
        }
        try:
            generated = await generate_arm_copy(
                request,
                loaded.config,
                loaded.trend_card,
                arm,
                loaded.examples,
                paired_seed,
            )
        except Exception as error:
            record.update(
                {
                    "generation_success": False,
                    "schema_valid": False,
                    "rule_valid": False,
                    "operational_valid": False,
                    "operational_failure_reasons": ["generation_failed"],
                    "error_type": parse_failure_type(error),
                    "error": str(error),
                    "generation_http_request_count": getattr(
                        error,
                        "request_count",
                        0,
                    ),
                    "generation_usage": getattr(error, "usage", {}),
                    "generation_actual_model": getattr(
                        error,
                        "actual_model",
                        None,
                    ),
                    "wall_latency_ms": round((perf_counter() - started_at) * 1000, 2),
                }
            )
            return record

        content_dump = generated.content.model_dump(mode="json")
        metrics_result = _metric_response(request, loaded, content_dump)
        leakage = find_example_leakage(request, generated.content, loaded.examples)
        unsupported = visible_hallucination_terms(request, generated.content)
        unsafe = visible_toxicity_terms(generated.content)
        required_term_rate = visible_required_term_compliance_rate(
            request,
            generated.content,
        )
        record.update(
            {
                "generation_success": True,
                "schema_valid": True,
                "rule_valid": generated.validation.valid,
                "rule_warnings": generated.validation.warnings,
                "error_type": None,
                "error": None,
                "generation_latency_ms": generated.latency_ms,
                "generation_http_request_count": generated.request_count,
                "generation_usage": generated.usage,
                "generation_actual_model": generated.actual_model,
                "structured_output_fallback": generated.structured_output_fallback,
                "endpoint_model": generated.endpoint_model,
                "endpoint_source": generated.endpoint_source,
                "base_revision": generated.base_revision,
                "adapter_revision": generated.adapter_revision,
                "marker_compliant": marker_compliance(
                    generated.content,
                    loaded.trend_card,
                ),
                "example_leakage_terms": leakage,
                "context_adherence_score": visible_context_adherence_score(
                    request,
                    generated.content,
                ),
                "required_term_compliance_rate": required_term_rate,
                "hallucination_terms": unsupported,
                "toxicity_terms": unsafe,
                "hashtag_compliance_rate": hashtag_compliance_rate(metrics_result),
                "output": content_dump,
                "raw_output": generated.raw_content,
            }
        )
        record["operational_failure_reasons"] = operational_failure_reasons(record)
        record["operational_valid"] = not record["operational_failure_reasons"]

        if judge_enabled:
            try:
                judge_call = await judge_meme_copy_with_metadata(
                    request,
                    loaded.trend_card,
                    generated.content,
                    base_url_override=loaded.config.judge.base_url,
                    model_override=loaded.config.judge.model,
                    timeout_seconds=loaded.config.judge.timeout_seconds,
                )
                judged = judge_call.result
                record["judge_success"] = True
                record["judge"] = judged.model_dump(mode="json")
                record["judge_latency_ms"] = judge_call.latency_ms
                record["judge_usage"] = judge_call.usage
                record["judge_actual_model"] = judge_call.actual_model
                record["judge_http_request_count"] = 1
            except (
                MemeJudgeNotConfiguredError,
                MemeJudgeProviderError,
                InvalidMemeJudgeOutputError,
            ) as error:
                record["judge_success"] = False
                record["judge_error_type"] = type(error).__name__
                record["judge_error"] = str(error)
                record["judge_http_request_count"] = 1
                record["judge_usage"] = {}
        else:
            record["judge_success"] = None

        record["wall_latency_ms"] = round((perf_counter() - started_at) * 1000, 2)
        return record


def _percent(count: int, total: int) -> float | None:
    return round(count / total * 100, 2) if total else None


def _average(records: list[dict[str, Any]], key: str) -> float | None:
    values = [record[key] for record in records if record.get(key) is not None]
    return round(mean(values), 4) if values else None


def _sum_usage(records: list[dict[str, Any]], key: str) -> dict[str, int]:
    totals: dict[str, int] = {}
    for record in records:
        usage = record.get(key) or {}
        for name, value in usage.items():
            if isinstance(name, str) and isinstance(value, int):
                totals[name] = totals.get(name, 0) + value
    return totals


def summarize_arm(arm: MemeEvalArm, records: list[dict[str, Any]]) -> dict[str, Any]:
    generated = [record for record in records if record["generation_success"]]
    judged = [record for record in generated if record.get("judge_success")]
    judge_scores = {
        key: (
            round(mean(record["judge"][key] for record in judged), 3)
            if judged
            else None
        )
        for key in JUDGE_SCORE_KEYS
    }
    by_case_type: dict[str, Any] = {}
    for case_type in sorted({record["case_type"] for record in records}):
        subset = [record for record in records if record["case_type"] == case_type]
        subset_judged = [record for record in subset if record.get("judge_success")]
        by_case_type[case_type] = {
            "trials": len(subset),
            "rule_pass_rate_percent": _percent(
                sum(bool(record.get("rule_valid")) for record in subset),
                len(subset),
            ),
            "operational_pass_rate_percent": _percent(
                sum(record_operationally_valid(record) for record in subset),
                len(subset),
            ),
            "judge_overall_score": (
                round(
                    mean(
                        record["judge"]["overall_score"]
                        for record in subset_judged
                    ),
                    3,
                )
                if subset_judged
                else None
            ),
        }

    required_term_average = _average(
        generated,
        "required_term_compliance_rate",
    )
    return {
        "arm_id": arm.id,
        "label": arm.label,
        "strategy": arm.strategy,
        "trials": len(records),
        "generation_success_rate_percent": _percent(len(generated), len(records)),
        "rule_pass_rate_percent": _percent(
            sum(bool(record.get("rule_valid")) for record in records),
            len(records),
        ),
        "operational_pass_rate_percent": _percent(
            sum(record_operationally_valid(record) for record in records),
            len(records),
        ),
        "marker_compliance_rate_percent": _percent(
            sum(bool(record.get("marker_compliant")) for record in generated),
            len(generated),
        ),
        "example_leakage_rate_percent": _percent(
            sum(bool(record.get("example_leakage_terms")) for record in generated),
            len(generated),
        ),
        "hallucination_rate_percent": _percent(
            sum(bool(record.get("hallucination_terms")) for record in generated),
            len(generated),
        ),
        "context_adherence_score": _average(generated, "context_adherence_score"),
        "required_term_compliance_rate_percent": (
            round(required_term_average * 100, 2)
            if required_term_average is not None
            else None
        ),
        "mean_generation_latency_ms": _average(generated, "generation_latency_ms"),
        "generation_http_request_count": sum(
            int(record.get("generation_http_request_count") or 0)
            for record in records
        ),
        "generation_usage": _sum_usage(records, "generation_usage"),
        "judge_completion_rate_percent": _percent(len(judged), len(generated)),
        "judge_http_request_count": sum(
            int(record.get("judge_http_request_count") or 0)
            for record in records
        ),
        "judge_usage": _sum_usage(records, "judge_usage"),
        "judge_scores": judge_scores,
        "judge_hard_failure_rate_percent": _percent(
            sum(bool(record["judge"]["hard_failures"]) for record in judged),
            len(judged),
        ),
        "by_case_type": by_case_type,
    }


def build_paired_analysis(
    arms: list[MemeEvalArm],
    records: list[dict[str, Any]],
    *,
    judge_enabled: bool,
    fixtures_reviewed: bool,
    decision_eligible: bool,
    decision_ineligibility_reasons: list[str] | None = None,
) -> dict[str, Any]:
    """Compare only case/repeat blocks completed by every selected arm."""

    arm_ids = {arm.id for arm in arms}
    block_keys = sorted({(record["case_id"], record["repeat"]) for record in records})
    by_block: dict[tuple[str, int], dict[str, dict[str, Any]]] = {}
    for record in records:
        key = (record["case_id"], record["repeat"])
        by_block.setdefault(key, {})[record["arm_id"]] = record

    complete_keys: list[tuple[str, int]] = []
    for key in block_keys:
        block = by_block[key]
        if set(block) != arm_ids:
            continue
        if not all(item.get("generation_success") for item in block.values()):
            continue
        if judge_enabled and not all(item.get("judge_success") for item in block.values()):
            continue
        complete_keys.append(key)

    paired_by_arm: dict[str, list[dict[str, Any]]] = {
        arm.id: [by_block[key][arm.id] for key in complete_keys]
        for arm in arms
    }
    arm_scores = []
    for arm in arms:
        paired = paired_by_arm[arm.id]
        judged = [record for record in paired if record.get("judge_success")]
        operationally_valid = [
            record for record in paired if record_operationally_valid(record)
        ]
        ranking_eligible = bool(paired) and all(
            record_operationally_valid(record)
            and not bool((record.get("judge") or {}).get("hard_failures"))
            for record in paired
        )
        arm_scores.append(
            {
                "arm_id": arm.id,
                "paired_trials": len(paired),
                "judge_overall_score": (
                    round(mean(record["judge"]["overall_score"] for record in judged), 3)
                    if judged
                    else None
                ),
                "rule_pass_rate_percent": _percent(
                    sum(bool(record.get("rule_valid")) for record in paired),
                    len(paired),
                ),
                "operational_pass_rate_percent": _percent(
                    len(operationally_valid),
                    len(paired),
                ),
                "judge_hard_failure_rate_percent": _percent(
                    sum(bool(record["judge"]["hard_failures"]) for record in judged),
                    len(judged),
                ),
                "ranking_eligible": ranking_eligible,
            }
        )

    paired_coverage = _percent(len(complete_keys), len(block_keys))
    eligible_scores = [item for item in arm_scores if item["ranking_eligible"]]
    eligible_arm_ids = [item["arm_id"] for item in eligible_scores]
    operational_status = (
        "eligible_arms_present"
        if eligible_scores
        else "no_operationally_eligible_arm"
    )
    if not fixtures_reviewed:
        status = "fixture_not_reviewed"
        ranking: list[dict[str, Any]] = []
    elif not decision_eligible:
        status = "engineering_smoke"
        ranking = []
    elif not judge_enabled:
        status = "judge_disabled"
        ranking = []
    elif len(complete_keys) != len(block_keys):
        status = "incomplete_paired_coverage"
        ranking = []
    elif not eligible_scores:
        status = "no_operationally_eligible_arm"
        ranking = []
    else:
        status = "complete"
        ordered = sorted(
            eligible_scores,
            key=lambda item: item["judge_overall_score"] or -1,
            reverse=True,
        )
        ranking = []
        previous_score: float | None = None
        previous_rank = 0
        for index, item in enumerate(ordered, start=1):
            score = item["judge_overall_score"]
            rank = previous_rank if score == previous_score else index
            ranking.append({"rank": rank, **item})
            previous_score = score
            previous_rank = rank

    first_place = [item for item in ranking if item["rank"] == 1]
    winner_arm_id = first_place[0]["arm_id"] if len(first_place) == 1 else None

    return {
        "status": status,
        "total_case_repeat_blocks": len(block_keys),
        "complete_paired_blocks": len(complete_keys),
        "paired_coverage_percent": paired_coverage,
        "decision_eligible": decision_eligible,
        "decision_ineligibility_reasons": decision_ineligibility_reasons or [],
        "operational_status": operational_status,
        "operationally_eligible_arm_ids": eligible_arm_ids,
        "complete_block_ids": [
            {"case_id": case_id, "repeat": repeat}
            for case_id, repeat in complete_keys
        ],
        "arm_scores_on_paired_blocks": arm_scores,
        "ranking": ranking,
        "winner_arm_id": winner_arm_id,
        "winner_status": (
            "unique_winner"
            if winner_arm_id
            else "tie"
            if len(first_place) > 1
            else "no_winner"
        ),
        "note": (
            "순위는 모든 arm의 생성과 judge가 같은 case/repeat에서 완료되고 "
            "fixture 사람 검수와 전체 실험 범위가 충족되며, 해당 arm이 모든 deterministic "
            "운영 규칙과 Judge hard-failure gate를 통과한 경우에만 표시합니다. "
            "동점은 같은 rank입니다."
        ),
    }


def _candidate_artifact_filename(record: dict[str, Any], index: int) -> str:
    candidate = str(record.get("candidate_id") or f"candidate-{index + 1}")
    safe_candidate = re.sub(r"[^0-9A-Za-z._-]+", "-", candidate).strip("-._")
    return f"{safe_candidate or f'candidate-{index + 1}'}.json"


def _markdown_json(value: Any) -> list[str]:
    serialized = json.dumps(value, ensure_ascii=False, indent=2)
    longest_run = max(
        (len(match.group(0)) for match in re.finditer(r"`+", serialized)),
        default=0,
    )
    fence = "`" * max(3, longest_run + 1)
    return [f"{fence}json", serialized, fence]


def _customer_visible_output(output: dict[str, Any]) -> dict[str, Any]:
    recommendation = output.get("channel_recommendation")
    if not isinstance(recommendation, dict):
        recommendation = {}
    return {
        "headlines": output.get("headlines") or [],
        "body_copies": output.get("body_copies") or [],
        "ctas": output.get("ctas") or [],
        "hashtags": output.get("hashtags") or [],
        "channel_recommendation": {
            field: recommendation.get(field)
            for field in (
                "overlay_headline",
                "caption",
                "publish_cta",
                "publish_hashtags",
                "publish_title",
                "publish_body",
                "blog_title",
                "blog_sections",
            )
            if recommendation.get(field) not in (None, "", [])
        },
    }


def _display_operational_failure(reason: Any) -> str:
    text_reason = str(reason)
    if text_reason.startswith("production_rule: "):
        return text_reason.removeprefix("production_rule: ")
    return OPERATIONAL_FAILURE_LABELS.get(text_reason, text_reason)


def _ordered_trials(report: dict[str, Any]) -> list[dict[str, Any]]:
    raw_trials = report.get("trials") or []
    trials = [record for record in raw_trials if isinstance(record, dict)]
    config = report.get("experiment_config_snapshot") or {}
    arms = config.get("arms") if isinstance(config, dict) else []
    arm_order = {
        arm.get("id"): index
        for index, arm in enumerate(arms or [])
        if isinstance(arm, dict)
    }
    prompt_snapshots = report.get("prompt_snapshots") or []
    case_order: dict[str, int] = {}
    for snapshot in prompt_snapshots:
        if not isinstance(snapshot, dict):
            continue
        case_id = snapshot.get("case_id")
        if isinstance(case_id, str) and case_id not in case_order:
            case_order[case_id] = len(case_order)
    return sorted(
        trials,
        key=lambda record: (
            case_order.get(str(record.get("case_id")), len(case_order)),
            str(record.get("case_id") or ""),
            int(record.get("repeat") or 0),
            arm_order.get(record.get("arm_id"), len(arm_order)),
            str(record.get("arm_id") or ""),
        ),
    )


def _candidate_detail_markdown(report: dict[str, Any]) -> list[str]:
    lines = [
        "## 후보별 생성 출력",
        "",
        (
            "각 후보를 펼치면 고객 노출 문구, 전체 생성 JSON, 검증 실패 사유와 "
            "Judge 평가를 확인할 수 있습니다."
        ),
        "",
    ]
    for index, record in enumerate(_ordered_trials(report)):
        case_id = str(record.get("case_id") or "unknown-case")
        arm_id = str(record.get("arm_id") or "unknown-arm")
        repeat = record.get("repeat") or "-"
        generated = bool(record.get("generation_success"))
        operational = record_operationally_valid(record)
        status = (
            "생성 실패"
            if not generated
            else "운영 통과"
            if operational
            else "운영 실패"
        )
        summary = html.escape(
            f"{case_id} · repeat {repeat} · {arm_id} · {status}",
            quote=True,
        )
        artifact_name = _candidate_artifact_filename(record, index)
        lines.extend(
            [
                "<details>",
                f"<summary>{summary}</summary>",
                "",
                f"- Candidate ID: `{record.get('candidate_id') or '-'}`",
                f"- 생성 seed: `{record.get('generation_seed', '-')}`",
                (
                    "- 실제 응답 모델: `"
                    f"{record.get('generation_actual_model') or '기록 없음'}`"
                ),
                f"- Production validator: `{'통과' if record.get('rule_valid') else '실패'}`",
                f"- 운영 gate: `{'통과' if operational else '실패'}`",
                "",
            ]
        )
        if generated and isinstance(record.get("output"), dict):
            output = record["output"]
            lines.extend(["### 고객 노출 문구", ""])
            lines.extend(_markdown_json(_customer_visible_output(output)))
            lines.extend(["", "### 전체 생성 output JSON", ""])
            lines.extend(_markdown_json(output))
        else:
            lines.extend(
                [
                    "### 생성 오류",
                    "",
                    str(record.get("error") or "기록된 오류 메시지가 없습니다."),
                ]
            )

        rule_warnings = record.get("rule_warnings") or []
        operational_failures = operational_failure_reasons(record)
        lines.extend(["", "### 검증 결과", ""])
        if rule_warnings:
            lines.append("Production validator 경고:")
            lines.extend(f"- {warning}" for warning in rule_warnings)
        else:
            lines.append("- Production validator 경고 없음")
        if operational_failures:
            lines.append("- 운영 실패 사유:")
            lines.extend(
                f"  - {_display_operational_failure(reason)}"
                for reason in operational_failures
            )
        else:
            lines.append("- 운영 실패 사유 없음")

        judge = record.get("judge")
        lines.extend(["", "### Judge", ""])
        if isinstance(judge, dict):
            lines.extend(_markdown_json(judge))
        elif record.get("judge_error"):
            lines.append(f"Judge 실패: {record['judge_error']}")
        else:
            lines.append("Judge 결과 없음")
        lines.extend(
            [
                "",
                f"[이 후보의 전체 trial JSON](candidate_outputs/{artifact_name})",
                "",
                "</details>",
                "",
            ]
        )
    if len(lines) == 4:
        lines.append("저장된 trial이 없습니다.")
        lines.append("")
    return lines


def write_candidate_artifacts(report: dict[str, Any], run_dir: Path) -> Path:
    """Write one inspectable JSON artifact per candidate without model calls."""

    candidate_dir = run_dir / "candidate_outputs"
    candidate_dir.mkdir(parents=True, exist_ok=True)
    for index, record in enumerate(_ordered_trials(report)):
        path = candidate_dir / _candidate_artifact_filename(record, index)
        path.write_text(
            json.dumps(record, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    return candidate_dir


def markdown_report(report: dict[str, Any]) -> str:
    metadata = report["metadata"]
    paired = report["paired_analysis"]

    def percent_text(value: float | None) -> str:
        return "-" if value is None else f"{value}%"

    lines = [
        "# 단일 TrendCard 실험 보고서",
        "",
        f"- 생성 시각: {metadata['generated_at']}",
        f"- TrendCard: {metadata['trend_card_id']}",
        f"- 설정 생성 모델: {metadata['base_model']}",
        (
            "- 실제 응답 생성 모델: "
            + ", ".join(metadata.get("generation_actual_models") or ["기록 없음"])
        ),
        f"- 평가 케이스: {metadata['case_count']}개 × {metadata['repeats']}회",
        f"- Judge: {metadata['judge_model'] or '사용 안 함'}",
        f"- Judge prompt: {metadata.get('judge_prompt_version') or '기록 없음'}",
        f"- 의사결정 가능: {'예' if paired.get('decision_eligible') else '아니요 (engineering smoke)'}",
        f"- Paired 비교 상태: {paired['status']}",
        f"- 공식 winner: {paired.get('winner_arm_id') or '없음'}",
        f"- Paired coverage: {percent_text(paired['paired_coverage_percent'])}",
        "",
        "아래 표는 전체 trial 진단 요약입니다. 최종 순위는 paired 비교 조건을 충족한 경우에만 "
        "별도로 표시됩니다.",
        "",
        "| 실험군 | 생성 성공 | Production validator | 운영 통과 | 마커 존재(any field) | 예시 누출 | Judge 종합 | Judge hard fail |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for summary in report["arm_summaries"]:
        if not isinstance(summary, dict):
            lines.append("| 요약 생성 실패 | - | - | - | - | - | - | - |")
            continue
        judge_scores = summary.get("judge_scores") or {}
        judge_score = judge_scores.get("overall_score")
        lines.append(
            f"| {summary['label']} | "
            f"{percent_text(summary['generation_success_rate_percent'])} | "
            f"{percent_text(summary['rule_pass_rate_percent'])} | "
            f"{percent_text(summary.get('operational_pass_rate_percent'))} | "
            f"{percent_text(summary['marker_compliance_rate_percent'])} | "
            f"{percent_text(summary['example_leakage_rate_percent'])} | "
            f"{judge_score if judge_score is not None else '-'} | "
            f"{percent_text(summary['judge_hard_failure_rate_percent'])} |"
        )

    lines.extend(["", "## Paired 순위", ""])
    if paired["ranking"]:
        for item in paired["ranking"]:
            lines.append(
                f"{item['rank']}. {item['arm_id']} "
                f"(Judge {item['judge_overall_score']})"
            )
    else:
        lines.append(
            "순위를 표시하지 않습니다. fixture 검수, 전체 실험 범위, Judge 사용, "
            "paired completion, deterministic 운영 gate와 Judge hard failure를 확인하세요."
        )

    lines.append("")
    lines.extend(_candidate_detail_markdown(report))
    lines.extend(
        [
            "## 해석 주의",
            "",
            "- 동일한 Qwen 2.5 7B, TrendCard, 케이스, 생성 설정을 사용하며 arm별 prompt 전략만 바뀝니다.",
            "- Judge에는 arm 이름, 생성 모델, few-shot 여부를 전달하지 않습니다.",
            "- Judge 정성 점수는 deterministic 운영 검증을 대체하지 않으며, 운영 gate를 통과한 arm만 순위 후보가 됩니다.",
            "- 현재 한 개 밈만 평가하므로 결과는 이 TrendCard의 smoke 결과이며 다른 밈으로 일반화할 수 없습니다.",
            "- LoRA가 비활성이면 이 보고서에는 네 개 prompt arm만 포함됩니다.",
            "",
        ]
    )
    return "\n".join(lines)


def rebuild_saved_report(report: dict[str, Any]) -> dict[str, Any]:
    """Rebuild derived summaries from preserved trials without model calls."""

    trials = report.get("trials")
    config_snapshot = report.get("experiment_config_snapshot")
    if not isinstance(trials, list) or not isinstance(config_snapshot, dict):
        raise MemeExperimentDataError(
            "report.json에 trials 또는 experiment_config_snapshot이 없습니다."
        )
    selected_arm_ids = {
        record.get("arm_id")
        for record in trials
        if isinstance(record, dict) and isinstance(record.get("arm_id"), str)
    }
    try:
        arms = [
            MemeEvalArm.model_validate(raw_arm)
            for raw_arm in config_snapshot.get("arms", [])
            if raw_arm.get("id") in selected_arm_ids
        ]
    except (AttributeError, TypeError, ValidationError) as error:
        raise MemeExperimentDataError(
            "저장된 report의 arm 설정을 복구할 수 없습니다."
        ) from error
    if not arms:
        raise MemeExperimentDataError("저장된 report에서 실행 arm을 찾을 수 없습니다.")

    fixture_review = report.get("fixture_review") or {}
    metadata = report.get("metadata") or {}
    judge_enabled = bool(metadata.get("judge_model"))
    for record in trials:
        if isinstance(record, dict):
            reasons = operational_failure_reasons(record)
            record["operational_failure_reasons"] = reasons
            record["operational_valid"] = not reasons
    metadata["generation_actual_models"] = sorted(
        {
            model
            for record in trials
            if isinstance(record, dict)
            and isinstance((model := record.get("generation_actual_model")), str)
        }
    )
    metadata["judge_actual_models"] = sorted(
        {
            model
            for record in trials
            if isinstance(record, dict)
            and isinstance((model := record.get("judge_actual_model")), str)
        }
    )
    report["arm_summaries"] = [
        summarize_arm(
            arm,
            [record for record in trials if record.get("arm_id") == arm.id],
        )
        for arm in arms
    ]
    report["paired_analysis"] = build_paired_analysis(
        arms,
        trials,
        judge_enabled=judge_enabled,
        fixtures_reviewed=bool(fixture_review.get("decision_ready")),
        decision_eligible=bool(metadata.get("decision_eligible")),
        decision_ineligibility_reasons=list(
            metadata.get("decision_ineligibility_reasons") or []
        ),
    )
    metadata["report_rebuilt_at"] = datetime.now(UTC).isoformat()
    report["metadata"] = metadata
    return report


def render_saved_report(json_path: Path) -> tuple[Path, Path]:
    """Repair derived JSON sections and render Markdown without external calls."""

    resolved = json_path.resolve()
    try:
        raw = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise MemeExperimentDataError(
            f"기존 report.json을 읽을 수 없습니다: {resolved}"
        ) from error
    if not isinstance(raw, dict):
        raise MemeExperimentDataError("기존 report는 JSON 객체여야 합니다.")

    repaired = rebuild_saved_report(raw)
    backup_path = resolved.with_name("report.original.json")
    if not backup_path.exists():
        shutil.copy2(resolved, backup_path)
    temporary_path = resolved.with_name("report.repairing.json")
    temporary_path.write_text(
        json.dumps(repaired, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary_path.replace(resolved)
    write_candidate_artifacts(repaired, resolved.parent)
    markdown_path = resolved.with_name("report.md")
    markdown_path.write_text(markdown_report(repaired), encoding="utf-8")
    return resolved, markdown_path


async def run(args: argparse.Namespace) -> int:
    loaded = load_meme_experiment(args.config)
    arms = select_arms(loaded, args.arms)
    cases = select_cases(loaded, args.case_limit)
    repeats = (
        args.repeats
        if args.repeats is not None
        else loaded.config.generation.repeats
    )
    concurrency = (
        args.concurrency
        if args.concurrency is not None
        else loaded.config.generation.concurrency
    )
    if not 1 <= repeats <= 20 or not 1 <= concurrency <= 20:
        raise MemeExperimentDataError("repeats와 concurrency는 1 이상 20 이하여야 합니다")
    judge_enabled = loaded.config.judge.enabled and not args.skip_judge

    if args.dry_run:
        report = build_dry_run_report(
            loaded,
            arms,
            cases,
            repeats,
            judge_enabled,
        )
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0

    generation_trials = len(arms) * len(cases) * repeats
    judge_requests = generation_trials if judge_enabled else 0
    worst_case_requests = generation_trials * 2 + judge_requests
    enforce_execution_safety(
        loaded,
        cases,
        repeats,
        worst_case_requests,
        allow_large_run=args.allow_large_run,
        allow_unreviewed_fixtures=args.allow_unreviewed_fixtures,
    )

    endpoint_failures = []
    for arm in arms:
        try:
            resolve_generation_endpoint(loaded.config, arm)
        except Exception as error:
            endpoint_failures.append(f"{arm.id}: {error}")
    if endpoint_failures:
        raise MemeExperimentDataError(
            "생성 endpoint 사전 점검 실패: " + "; ".join(endpoint_failures)
        )
    if judge_enabled and not _judge_preflight(loaded)["ready"]:
        raise MemeExperimentDataError(
            "GPT-4.1-mini judge API key가 없어 평가를 시작하지 않았습니다."
        )

    work = [
        (case, arm, repeat)
        for case in cases
        for repeat in range(1, repeats + 1)
        for arm in arms
    ]
    random.Random(loaded.config.generation.shuffle_seed).shuffle(work)
    semaphore = asyncio.Semaphore(concurrency)
    started_at = perf_counter()
    tasks = [
        evaluate_trial(
            loaded,
            case,
            arm,
            repeat,
            judge_enabled,
            semaphore,
        )
        for case, arm, repeat in work
    ]
    records = await asyncio.gather(*tasks)
    duration_seconds = perf_counter() - started_at
    decision_eligible, decision_ineligibility_reasons = assess_decision_eligibility(
        loaded,
        arms,
        cases,
        repeats,
    )
    summaries = [
        summarize_arm(
            arm,
            [record for record in records if record["arm_id"] == arm.id],
        )
        for arm in arms
    ]
    paired_analysis = build_paired_analysis(
        arms,
        records,
        judge_enabled=judge_enabled,
        fixtures_reviewed=loaded.fixture_review.decision_ready,
        decision_eligible=decision_eligible,
        decision_ineligibility_reasons=decision_ineligibility_reasons,
    )
    prompt_snapshots = build_prompt_snapshots(loaded, arms, cases)
    report = {
        "metadata": {
            "generated_at": datetime.now(UTC).isoformat(),
            "experiment_id": loaded.config.experiment_id,
            "config_path": str(loaded.config_path),
            "dataset_path": str(loaded.dataset_path),
            "few_shot_path": str(loaded.few_shot_path),
            "fixture_review_path": str(loaded.fixture_review_path),
            "trend_card_path": str(loaded.trend_card_path),
            "trend_card_id": loaded.trend_card.meme_id,
            "base_model": loaded.config.base_model,
            "generation_actual_models": sorted(
                {
                    model
                    for record in records
                    if isinstance(
                        (model := record.get("generation_actual_model")),
                        str,
                    )
                }
            ),
            "production_prompt_version": PROMPT_VERSION,
            "judge_model": loaded.config.judge.model if judge_enabled else None,
            "judge_actual_models": sorted(
                {
                    model
                    for record in records
                    if isinstance((model := record.get("judge_actual_model")), str)
                }
            ),
            "judge_prompt_version": JUDGE_PROMPT_VERSION if judge_enabled else None,
            "decision_eligible": decision_eligible,
            "decision_ineligibility_reasons": decision_ineligibility_reasons,
            "case_count": len(cases),
            "repeats": repeats,
            "concurrency": concurrency,
            "generation_seed": loaded.config.generation.generation_seed,
            "shuffle_seed": loaded.config.generation.shuffle_seed,
            "duration_seconds": round(duration_seconds, 3),
            "generation_trial_count": len(records),
            "generator_http_request_count": sum(
                int(record.get("generation_http_request_count") or 0)
                for record in records
            ),
            "judge_http_request_count": sum(
                int(record.get("judge_http_request_count") or 0)
                for record in records
            ),
            "generation_usage": _sum_usage(records, "generation_usage"),
            "judge_usage": _sum_usage(records, "judge_usage"),
            "artifact_sha256": {
                "config": file_sha256(loaded.config_path),
                "trend_card": file_sha256(loaded.trend_card_path),
                "dataset": file_sha256(loaded.dataset_path),
                "few_shot": file_sha256(loaded.few_shot_path),
                "fixture_review": file_sha256(loaded.fixture_review_path),
            },
        },
        "experiment_config_snapshot": loaded.config.model_dump(mode="json"),
        "trend_card_snapshot": loaded.trend_card.model_dump(mode="json"),
        "prompt_snapshots": prompt_snapshots,
        "paired_analysis": paired_analysis,
        "disabled_arms": [
            {"arm_id": arm.id, "reason": arm.disabled_reason}
            for arm in loaded.config.arms
            if not arm.enabled
        ],
        "fixture_review": {
            **loaded.fixture_review.model_dump(mode="json"),
            "decision_ready": loaded.fixture_review.decision_ready,
        },
        "arm_summaries": summaries,
        "trials": records,
    }

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    run_dir = args.output_dir / timestamp
    run_dir.mkdir(parents=True, exist_ok=False)
    json_path = run_dir / "report.json"
    markdown_path = run_dir / "report.md"
    json_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    write_candidate_artifacts(report, run_dir)
    markdown_path.write_text(markdown_report(report), encoding="utf-8")
    print(f"JSON 보고서: {json_path}")
    print(f"Markdown 보고서: {markdown_path}")
    return 0


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = parse_args()
    try:
        if args.render_report is not None:
            json_path, markdown_path = render_saved_report(args.render_report)
            print(f"복구된 JSON 보고서: {json_path}")
            print(f"Markdown 보고서: {markdown_path}")
            raise_code = 0
        else:
            raise_code = asyncio.run(run(args))
    except MemeExperimentDataError as error:
        raise SystemExit(f"평가 설정 오류: {error}") from error
    raise SystemExit(raise_code)


if __name__ == "__main__":
    main()
