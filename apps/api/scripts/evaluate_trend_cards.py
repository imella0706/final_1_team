"""Evaluate many TrendCards under one fixed production prompt strategy.

The command emits qualification evidence only.  It never edits a source card,
changes ``curation_meta``, or activates a card for production use.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import random
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean
from time import perf_counter
from typing import Any

from app.evaluation.meme_arm_runner import (
    MemeEvalCase,
    MemeExperimentDataError,
    find_example_leakage,
    generate_arm_copy,
    marker_compliance,
    parse_failure_type,
    visible_context_adherence_score,
    visible_hallucination_terms,
    visible_required_term_compliance_rate,
    visible_toxicity_terms,
)
from app.evaluation.metrics import hashtag_compliance_rate
from app.evaluation.text_judge import (
    InvalidMemeJudgeOutputError,
    JUDGE_PROMPT_VERSION,
    MemeJudgeNotConfiguredError,
    MemeJudgeProviderError,
    build_meme_judge_input,
    judge_meme_copy_with_metadata,
)
from app.evaluation.trend_card_runner import (
    EVIDENCE_ONLY_STATUS,
    FIXED_STRATEGY_ID,
    CardWorkItem,
    LoadedTrendCardCandidate,
    LoadedTrendCardQualification,
    build_card_messages,
    build_work_items,
    candidate_preflight,
    file_sha256,
    fixed_strategy_arm,
    load_trend_card_qualification,
    qualification_candidate_id,
    request_for_card_case,
    resolve_fixed_generation_endpoint,
    trial_generation_seed,
)
from app.modules.ad_copy.prompt import PROMPT_VERSION
from app.modules.ad_copy.schemas import AdCopyResponse
from app.modules.model_runtime.llm.registry import (
    get_text_model_config,
    resolve_api_key,
)


API_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = API_ROOT / "evals" / "trend_card_qualification.json"
DEFAULT_OUTPUT_DIR = API_ROOT / "outputs" / "evaluations" / "trend_cards"
DEFAULT_EXTERNAL_REQUEST_LIMIT = 20
JUDGE_SCORE_KEYS = (
    "naturalness",
    "pattern_fidelity",
    "product_relevance",
    "factuality",
    "channel_readiness",
    "overall_score",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--cards", nargs="*", help="candidate card ids; default: all enabled")
    parser.add_argument("--case-limit", type=int)
    parser.add_argument("--repeats", type=int)
    parser.add_argument("--concurrency", type=int)
    parser.add_argument("--skip-judge", action="store_true")
    parser.add_argument("--allow-large-run", action="store_true")
    parser.add_argument(
        "--allow-unreviewed-fixtures",
        action="store_true",
        help="allow a one-case, one-repeat evidence smoke with unreviewed cases",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="validate inputs and render preflight without external API calls",
    )
    return parser.parse_args()


def select_candidates(
    loaded: LoadedTrendCardQualification,
    requested: list[str] | None,
) -> list[LoadedTrendCardCandidate]:
    by_id = {candidate.spec.id: candidate for candidate in loaded.candidates}
    if requested:
        unknown = sorted(set(requested) - set(by_id))
        if unknown:
            raise MemeExperimentDataError(
                f"Unknown TrendCard candidate ids: {', '.join(unknown)}"
            )
        selected = [by_id[candidate_id] for candidate_id in requested]
        disabled = [candidate.spec.id for candidate in selected if not candidate.spec.enabled]
        if disabled:
            raise MemeExperimentDataError(
                f"Disabled TrendCard candidates cannot run: {', '.join(disabled)}"
            )
        return selected
    return [candidate for candidate in loaded.candidates if candidate.spec.enabled]


def select_cases(
    loaded: LoadedTrendCardQualification,
    case_limit: int | None,
) -> list[MemeEvalCase]:
    if case_limit is not None and case_limit < 1:
        raise MemeExperimentDataError("case-limit must be at least 1")
    return loaded.cases[:case_limit] if case_limit else loaded.cases


def _judge_preflight(loaded: LoadedTrendCardQualification) -> dict[str, Any]:
    config = get_text_model_config("openai/gpt-4.1-mini")
    api_key = resolve_api_key(config)
    return {
        "ready": bool(api_key),
        "model": loaded.config.judge.model,
        "base_url": loaded.config.judge.base_url,
        "api_key_configured": bool(api_key),
    }


def build_prompt_snapshots(
    loaded: LoadedTrendCardQualification,
    candidates: list[LoadedTrendCardCandidate],
    cases: list[MemeEvalCase],
    *,
    supports_system_role: bool,
) -> list[dict[str, Any]]:
    snapshots: list[dict[str, Any]] = []
    for candidate in candidates:
        preflight = candidate_preflight(loaded, candidate, cases)
        eligible_case_ids = {
            item["case_id"]
            for item in preflight["case_eligibility"]
            if item["eligible"]
        }
        for case in cases:
            if case.id not in eligible_case_ids:
                continue
            request = request_for_card_case(loaded, case, candidate)
            messages = build_card_messages(
                request,
                candidate,
                supports_system_role=supports_system_role,
            )
            serialized = json.dumps(
                messages,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            snapshots.append(
                {
                    "prompt_id": (
                        f"{case.id}:{candidate.spec.id}:"
                        f"{(candidate.artifact_sha256 or 'unavailable')[:12]}"
                    ),
                    "case_id": case.id,
                    "candidate_card_id": candidate.spec.id,
                    "trend_card_id": request.trend_card_id,
                    "card_artifact_sha256": candidate.artifact_sha256,
                    "strategy": FIXED_STRATEGY_ID,
                    "sha256": hashlib.sha256(serialized.encode()).hexdigest(),
                    "messages": messages,
                }
            )
    return snapshots


def _card_snapshot(candidate: LoadedTrendCardCandidate) -> dict[str, Any]:
    current_sha: str | None = None
    if candidate.path.is_file():
        current_sha = file_sha256(candidate.path)
    return {
        "candidate_card_id": candidate.spec.id,
        "label": candidate.spec.label,
        "path": str(candidate.path),
        "artifact_sha256": candidate.artifact_sha256,
        "post_run_artifact_sha256": current_sha,
        "source_artifact_unchanged": (
            candidate.artifact_sha256 == current_sha
            if candidate.artifact_sha256 is not None and current_sha is not None
            else None
        ),
        "load_error": candidate.load_error,
        "trend_card": (
            candidate.trend_card.model_dump(mode="json")
            if candidate.trend_card is not None
            else None
        ),
    }


def build_dry_run_report(
    loaded: LoadedTrendCardQualification,
    candidates: list[LoadedTrendCardCandidate],
    cases: list[MemeEvalCase],
    repeats: int,
    judge_enabled: bool,
) -> dict[str, Any]:
    endpoint_error: str | None = None
    endpoint_source: str | None = None
    endpoint_model: str | None = None
    supports_system_role = True
    try:
        endpoint = resolve_fixed_generation_endpoint(loaded.config)
        endpoint_source = endpoint.source
        endpoint_model = endpoint.model
        supports_system_role = endpoint.supports_system_role
    except Exception as error:  # readiness evidence must not expose credentials
        endpoint_error = str(error)

    preflights = [candidate_preflight(loaded, candidate, cases) for candidate in candidates]
    work = build_work_items(loaded, candidates, cases, repeats)
    generation_trials = len(work)
    max_attempts = int(loaded.config.generation.max_attempts)
    prompt_snapshots = build_prompt_snapshots(
        loaded,
        candidates,
        cases,
        supports_system_role=supports_system_role,
    )
    batch_card_preflight_success = bool(preflights) and all(
        item["preflight_status"] in {"ready", "partially_eligible"}
        for item in preflights
    )
    return {
        "mode": "dry_run",
        "external_api_called": False,
        "quality_status": EVIDENCE_ONLY_STATUS,
        "source_artifacts_mutated": False,
        "experiment_id": loaded.config.experiment_id,
        "base_model": loaded.config.base_model,
        "strategy": loaded.config.strategy,
        "case_count": len(cases),
        "candidate_card_count": len(candidates),
        "repeats": repeats,
        "generation_seed": loaded.config.generation.generation_seed,
        "fixture_review": {
            **loaded.fixture_review.model_dump(mode="json"),
            "decision_ready": loaded.fixture_review.decision_ready,
        },
        "artifact_sha256": {
            "config": file_sha256(loaded.config_path),
            "dataset": file_sha256(loaded.dataset_path),
            "fixture_review": file_sha256(loaded.fixture_review_path),
            "cards": {
                candidate.spec.id: candidate.artifact_sha256
                for candidate in candidates
            },
        },
        "batch_card_preflight_success": batch_card_preflight_success,
        "endpoint": {
            "ready": endpoint_error is None,
            "error": endpoint_error,
            "source": endpoint_source,
            "model": endpoint_model,
        },
        "judge": _judge_preflight(loaded) if judge_enabled else {"enabled": False},
        "planned_calls": {
            "eligible_generation_trials": generation_trials,
            "generator_http_requests_minimum": generation_trials,
            "generator_http_requests_maximum": generation_trials * max_attempts * 2,
            "judge_http_requests_maximum": generation_trials if judge_enabled else 0,
        },
        "card_preflights": preflights,
        "card_snapshots": [_card_snapshot(candidate) for candidate in candidates],
        "prompt_snapshots": prompt_snapshots,
    }


def enforce_execution_safety(
    loaded: LoadedTrendCardQualification,
    cases: list[MemeEvalCase],
    repeats: int,
    worst_case_requests: int,
    *,
    allow_large_run: bool,
    allow_unreviewed_fixtures: bool,
) -> None:
    if worst_case_requests > DEFAULT_EXTERNAL_REQUEST_LIMIT and not allow_large_run:
        raise MemeExperimentDataError(
            f"This run can issue up to {worst_case_requests} external requests. "
            "Inspect --dry-run first, then pass --allow-large-run if intended."
        )
    if not loaded.fixture_review.decision_ready:
        if not allow_unreviewed_fixtures:
            raise MemeExperimentDataError(
                "Case fixtures are not human/rights reviewed. Use --case-limit 1 "
                "--repeats 1 --allow-unreviewed-fixtures for evidence smoke only."
            )
        if len(cases) != 1 or repeats != 1:
            raise MemeExperimentDataError(
                "Unreviewed fixtures permit only 1 case x 1 repeat evidence smoke"
            )


def _validation_snapshot(validation: Any) -> dict[str, Any] | None:
    if validation is None:
        return None
    return {
        "valid": bool(getattr(validation, "valid", False)),
        "warnings": list(getattr(validation, "warnings", []) or []),
        "failure_codes": list(getattr(validation, "failure_codes", []) or []),
    }


def deterministic_validation_evidence(record: dict[str, Any]) -> dict[str, Any]:
    """Preserve deterministic failures without turning evidence into activation."""

    if not record.get("generation_success"):
        return {
            "authoritative": True,
            "passed": False,
            "failure_codes": ["generation_failed"],
        }
    codes = [
        str(code)
        for code in (record.get("production_failure_codes") or [])
        if isinstance(code, str) and code.strip()
    ]
    if not record.get("rule_valid") and not codes:
        codes.append("production_rule_validation_failed")
    required_rate = record.get("required_term_compliance_rate")
    if not isinstance(required_rate, (int, float)) or required_rate < 1:
        codes.append("required_terms_noncompliant")
    hashtag_rate = record.get("hashtag_compliance_rate")
    if not isinstance(hashtag_rate, (int, float)) or hashtag_rate < 1:
        codes.append("hashtag_format_noncompliant")
    for field, code in (
        ("example_leakage_terms", "few_shot_example_leakage"),
        ("hallucination_terms", "unsupported_claim_detected"),
        ("toxicity_terms", "unsafe_expression_detected"),
    ):
        if record.get(field):
            codes.append(code)
    codes = list(dict.fromkeys(codes))
    return {
        "authoritative": True,
        "passed": not codes,
        "failure_codes": codes,
    }


def canonical_json_sha256(value: Any) -> str:
    """Hash canonical UTF-8 JSON for stable human-label joins."""

    serialized = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _metric_response(
    loaded: LoadedTrendCardQualification,
    item: CardWorkItem,
    content_dump: dict[str, Any],
) -> AdCopyResponse:
    assert item.candidate.trend_card is not None
    return AdCopyResponse(
        **content_dump,
        model=loaded.config.base_model,
        prompt_version="trend-card-qualification-v1",
        trend_card_id=item.candidate.trend_card.meme_id,
    )


async def evaluate_trial(
    loaded: LoadedTrendCardQualification,
    item: CardWorkItem,
    judge_enabled: bool,
    semaphore: asyncio.Semaphore,
) -> dict[str, Any]:
    queued_at = perf_counter()
    async with semaphore:
        started_at = perf_counter()
        candidate = item.candidate
        card = candidate.trend_card
        assert card is not None
        request = request_for_card_case(loaded, item.case, candidate)
        paired_seed = trial_generation_seed(
            loaded.config.generation.generation_seed,
            item.case.id,
            item.repeat,
        )
        prompt_id = (
            f"{item.case.id}:{candidate.spec.id}:"
            f"{(candidate.artifact_sha256 or 'unavailable')[:12]}"
        )
        trial_id = qualification_candidate_id(
            loaded.config.experiment_id,
            item.case.id,
            item.repeat,
            candidate.spec.id,
            candidate.artifact_sha256,
        )
        record: dict[str, Any] = {
            "candidate_id": trial_id,
            "trial_id": trial_id,
            "output_id": None,
            "card_id": candidate.spec.id,
            "card_sha256": candidate.artifact_sha256,
            "candidate_card_id": candidate.spec.id,
            "card_artifact_sha256": candidate.artifact_sha256,
            "output_sha256": None,
            "trend_card_id": card.meme_id,
            "case_id": item.case.id,
            "case_type": item.case.case_type,
            "channel": request.channel.value,
            "repeat": item.repeat,
            "strategy": FIXED_STRATEGY_ID,
            "prompt_id": prompt_id,
            "generation_seed": paired_seed,
            "quality_status": EVIDENCE_ONLY_STATUS,
            "queue_wait_ms": round((started_at - queued_at) * 1000, 2),
        }
        try:
            generated = await generate_arm_copy(
                request,
                loaded.config,  # type: ignore[arg-type]
                card,
                fixed_strategy_arm(),
                [],
                paired_seed,
            )
        except Exception as error:
            record.update(
                {
                    "generation_success": False,
                    "schema_valid": False,
                    "rule_valid": False,
                    "error_type": parse_failure_type(error),
                    "error": str(error),
                    "generation_http_request_count": getattr(error, "request_count", 0),
                    "generation_usage": getattr(error, "usage", {}),
                    "generation_actual_model": getattr(error, "actual_model", None),
                    "judge_success": None,
                    "wall_latency_ms": round(
                        (perf_counter() - started_at) * 1000,
                        2,
                    ),
                }
            )
            record["deterministic_validation"] = deterministic_validation_evidence(record)
            return record

        content_dump = generated.content.model_dump(mode="json")
        customer_visible_output = build_meme_judge_input(
            request,
            card,
            generated.content,
        ).customer_visible_result.model_dump(mode="json")
        record["customer_visible_output"] = customer_visible_output
        record["output_sha256"] = canonical_json_sha256(customer_visible_output)
        record["output_id"] = f"{trial_id}-{record['output_sha256'][:12]}"
        initial_content = getattr(generated, "initial_content", None)
        normalized_initial_content = getattr(generated, "normalized_initial_content", None)
        repair_content = getattr(generated, "repair_content", None)
        metrics_result = _metric_response(loaded, item, content_dump)
        leakage = find_example_leakage(request, generated.content, [])
        record.update(
            {
                "generation_success": True,
                "schema_valid": True,
                "rule_valid": generated.validation.valid,
                "rule_warnings": generated.validation.warnings,
                "production_failure_codes": list(
                    getattr(generated.validation, "failure_codes", []) or []
                ),
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
                "marker_compliant": marker_compliance(generated.content, card),
                "example_leakage_terms": leakage,
                "context_adherence_score": visible_context_adherence_score(
                    request,
                    generated.content,
                ),
                "required_term_compliance_rate": (
                    visible_required_term_compliance_rate(request, generated.content)
                ),
                "hallucination_terms": visible_hallucination_terms(
                    request,
                    generated.content,
                ),
                "toxicity_terms": visible_toxicity_terms(generated.content),
                "hashtag_compliance_rate": hashtag_compliance_rate(metrics_result),
                "output": content_dump,
                "raw_output": generated.raw_content,
                "initial_output": (
                    initial_content.model_dump(mode="json")
                    if initial_content is not None
                    else content_dump
                ),
                "normalized_initial_output": (
                    normalized_initial_content.model_dump(mode="json")
                    if normalized_initial_content is not None
                    else content_dump
                ),
                "repair_output": (
                    repair_content.model_dump(mode="json")
                    if repair_content is not None
                    else None
                ),
                "initial_validation": _validation_snapshot(
                    getattr(generated, "initial_validation", None)
                ),
                "normalized_initial_validation": _validation_snapshot(
                    getattr(generated, "normalized_initial_validation", None)
                ),
                "repair_validation": _validation_snapshot(
                    getattr(generated, "repair_validation", None)
                ),
                "repair_attempted": bool(getattr(generated, "repair_attempted", False)),
                "repair_success": bool(getattr(generated, "repair_success", False)),
                "repair_error": getattr(generated, "repair_error", None),
            }
        )
        record["deterministic_validation"] = deterministic_validation_evidence(record)

        if judge_enabled:
            try:
                # Card qualification measures the production result users receive.
                judge_call = await judge_meme_copy_with_metadata(
                    request,
                    card,
                    generated.content,
                    base_url_override=loaded.config.judge.base_url,
                    model_override=loaded.config.judge.model,
                    timeout_seconds=loaded.config.judge.timeout_seconds,
                )
                judge_data = judge_call.result.model_dump(mode="json")
                judge_data["advisory_findings"] = judge_data.pop("hard_failures", [])
                judge_data["advisory_only"] = True
                record.update(
                    {
                        "judge_success": True,
                        "judge": judge_data,
                        "judge_target": "final_output",
                        "judge_latency_ms": judge_call.latency_ms,
                        "judge_usage": judge_call.usage,
                        "judge_actual_model": judge_call.actual_model,
                        "judge_http_request_count": 1,
                    }
                )
            except (
                MemeJudgeNotConfiguredError,
                MemeJudgeProviderError,
                InvalidMemeJudgeOutputError,
            ) as error:
                record.update(
                    {
                        "judge_success": False,
                        "judge_error_type": type(error).__name__,
                        "judge_error": str(error),
                        "judge_http_request_count": 1,
                        "judge_usage": {},
                    }
                )
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
        for name, value in (record.get(key) or {}).items():
            if isinstance(name, str) and isinstance(value, int):
                totals[name] = totals.get(name, 0) + value
    return totals


def summarize_card(
    loaded: LoadedTrendCardQualification,
    candidate: LoadedTrendCardCandidate,
    cases: list[MemeEvalCase],
    repeats: int,
    records: list[dict[str, Any]],
) -> dict[str, Any]:
    preflight = candidate_preflight(loaded, candidate, cases)
    expected_trials = preflight["eligible_case_count"] * repeats
    generated = [record for record in records if record.get("generation_success")]
    judged = [record for record in generated if record.get("judge_success")]
    repair_attempted = [record for record in generated if record.get("repair_attempted")]
    judge_scores = {
        key: (
            round(mean(record["judge"][key] for record in judged), 3)
            if judged
            else None
        )
        for key in JUDGE_SCORE_KEYS
    }
    deterministic_passes = sum(
        bool((record.get("deterministic_validation") or {}).get("passed"))
        for record in records
    )
    return {
        "candidate_card_id": candidate.spec.id,
        "label": candidate.spec.label,
        "trend_card_id": (
            candidate.trend_card.meme_id if candidate.trend_card is not None else None
        ),
        "card_artifact_sha256": candidate.artifact_sha256,
        "preflight_status": preflight["preflight_status"],
        "quality_status": EVIDENCE_ONLY_STATUS,
        "status_transition_attempted": False,
        "eligible_case_count": preflight["eligible_case_count"],
        "skipped_case_count": preflight["skipped_case_count"],
        "expected_trials": expected_trials,
        "observed_trials": len(records),
        "generation_success_rate_percent": _percent(len(generated), expected_trials),
        "deterministic_pass_rate_percent": _percent(
            deterministic_passes,
            expected_trials,
        ),
        "rule_pass_rate_percent": _percent(
            sum(bool(record.get("rule_valid")) for record in records),
            expected_trials,
        ),
        "marker_compliance_rate_percent": _percent(
            sum(bool(record.get("marker_compliant")) for record in generated),
            len(generated),
        ),
        "repair_attempt_rate_percent": _percent(
            len(repair_attempted),
            len(generated),
        ),
        "repair_success_rate_percent": _percent(
            sum(bool(record.get("repair_success")) for record in repair_attempted),
            len(repair_attempted),
        ),
        "hallucination_rate_percent": _percent(
            sum(bool(record.get("hallucination_terms")) for record in generated),
            len(generated),
        ),
        "toxicity_rate_percent": _percent(
            sum(bool(record.get("toxicity_terms")) for record in generated),
            len(generated),
        ),
        "required_term_compliance_rate": _average(
            generated,
            "required_term_compliance_rate",
        ),
        "context_adherence_score": _average(generated, "context_adherence_score"),
        "judge_completion_rate_percent": _percent(len(judged), expected_trials),
        "judge_scores": judge_scores,
        "mean_generation_latency_ms": _average(generated, "generation_latency_ms"),
        "generation_http_request_count": sum(
            int(record.get("generation_http_request_count") or 0)
            for record in records
        ),
        "judge_http_request_count": sum(
            int(record.get("judge_http_request_count") or 0)
            for record in records
        ),
        "generation_usage": _sum_usage(records, "generation_usage"),
        "judge_usage": _sum_usage(records, "judge_usage"),
        "quality_evidence": {
            "judge_overall_mean": judge_scores["overall_score"],
            "validator_pass_rate_percent": _percent(
                deterministic_passes,
                expected_trials,
            ),
            "note": (
                "No acceptance threshold is applied; human calibration and rights "
                "review are outside this evidence-only harness."
            ),
        },
    }


def _candidate_filename(record: dict[str, Any], index: int) -> str:
    candidate_id = str(record.get("candidate_id") or f"candidate-{index + 1}")
    safe = re.sub(r"[^0-9A-Za-z._-]+", "-", candidate_id).strip("-._")
    return f"{safe or f'candidate-{index + 1}'}.json"


def write_candidate_artifacts(report: dict[str, Any], run_dir: Path) -> Path:
    candidate_dir = run_dir / "candidate_outputs"
    candidate_dir.mkdir(parents=True, exist_ok=True)
    for index, record in enumerate(report.get("trials") or []):
        path = candidate_dir / _candidate_filename(record, index)
        path.write_text(
            json.dumps(record, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    return candidate_dir


def markdown_report(report: dict[str, Any]) -> str:
    metadata = report["metadata"]
    lines = [
        "# TrendCard qualification evidence",
        "",
        f"- Experiment: `{metadata['experiment_id']}`",
        f"- Strategy: `{metadata['strategy']}`",
        f"- Quality status: `{metadata['quality_status']}`",
        f"- Cases: {metadata['case_count']} x {metadata['repeats']} repeats",
        "- Source card mutation: none",
        "",
        "| Card | Preflight | Eligible cases | Generation | Validator | Judge overall | Status |",
        "| --- | --- | ---: | ---: | ---: | ---: | --- |",
    ]
    for summary in report["card_summaries"]:
        judge = summary["judge_scores"].get("overall_score")
        lines.append(
            f"| {summary['label']} | {summary['preflight_status']} | "
            f"{summary['eligible_case_count']} | "
            f"{summary['generation_success_rate_percent']} | "
            f"{summary['deterministic_pass_rate_percent']} | "
            f"{judge if judge is not None else '-'} | "
            f"{summary['quality_status']} |"
        )
    lines.extend(
        [
            "",
            "This report is evidence only. It does not promote, review, or activate a card.",
            "",
        ]
    )
    return "\n".join(lines)


async def run(args: argparse.Namespace) -> int:
    loaded = load_trend_card_qualification(args.config)
    candidates = select_candidates(loaded, args.cards)
    cases = select_cases(loaded, args.case_limit)
    repeats = args.repeats if args.repeats is not None else loaded.config.generation.repeats
    concurrency = (
        args.concurrency
        if args.concurrency is not None
        else loaded.config.generation.concurrency
    )
    if not 1 <= repeats <= 20 or not 1 <= concurrency <= 20:
        raise MemeExperimentDataError("repeats and concurrency must be between 1 and 20")
    judge_enabled = loaded.config.judge.enabled and not args.skip_judge

    if args.dry_run:
        report = build_dry_run_report(
            loaded,
            candidates,
            cases,
            repeats,
            judge_enabled,
        )
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0

    work = build_work_items(loaded, candidates, cases, repeats)
    generation_trials = len(work)
    judge_requests = generation_trials if judge_enabled else 0
    worst_case_requests = (
        generation_trials * int(loaded.config.generation.max_attempts) * 2
        + judge_requests
    )
    enforce_execution_safety(
        loaded,
        cases,
        repeats,
        worst_case_requests,
        allow_large_run=args.allow_large_run,
        allow_unreviewed_fixtures=args.allow_unreviewed_fixtures,
    )
    if work:
        try:
            resolve_fixed_generation_endpoint(loaded.config)
        except Exception as error:
            raise MemeExperimentDataError(
                f"Generation endpoint preflight failed: {error}"
            ) from error
    if judge_enabled and work and not _judge_preflight(loaded)["ready"]:
        raise MemeExperimentDataError("Judge API key is not configured")

    random.Random(loaded.config.generation.shuffle_seed).shuffle(work)
    semaphore = asyncio.Semaphore(concurrency)
    started_at = perf_counter()
    records = await asyncio.gather(
        *[
            evaluate_trial(loaded, item, judge_enabled, semaphore)
            for item in work
        ]
    )
    duration_seconds = perf_counter() - started_at
    summaries = [
        summarize_card(
            loaded,
            candidate,
            cases,
            repeats,
            [
                record
                for record in records
                if record["candidate_card_id"] == candidate.spec.id
            ],
        )
        for candidate in candidates
    ]
    try:
        endpoint = resolve_fixed_generation_endpoint(loaded.config)
        supports_system_role = endpoint.supports_system_role
    except Exception:
        supports_system_role = True
    prompt_snapshots = build_prompt_snapshots(
        loaded,
        candidates,
        cases,
        supports_system_role=supports_system_role,
    )
    report = {
        "metadata": {
            "generated_at": datetime.now(UTC).isoformat(),
            "experiment_id": loaded.config.experiment_id,
            "config_path": str(loaded.config_path),
            "dataset_path": str(loaded.dataset_path),
            "fixture_review_path": str(loaded.fixture_review_path),
            "base_model": loaded.config.base_model,
            "strategy": loaded.config.strategy,
            "quality_status": EVIDENCE_ONLY_STATUS,
            "source_artifacts_mutated": False,
            "production_prompt_version": PROMPT_VERSION,
            "judge_model": loaded.config.judge.model if judge_enabled else None,
            "judge_prompt_version": JUDGE_PROMPT_VERSION if judge_enabled else None,
            "case_count": len(cases),
            "candidate_card_count": len(candidates),
            "repeats": repeats,
            "concurrency": concurrency,
            "generation_seed": loaded.config.generation.generation_seed,
            "shuffle_seed": loaded.config.generation.shuffle_seed,
            "duration_seconds": round(duration_seconds, 3),
            "generation_trial_count": len(records),
            "fixture_review_decision_ready": loaded.fixture_review.decision_ready,
            "generation_usage": _sum_usage(records, "generation_usage"),
            "judge_usage": _sum_usage(records, "judge_usage"),
        },
        "experiment_config_snapshot": loaded.config.model_dump(mode="json"),
        "fixture_review": {
            **loaded.fixture_review.model_dump(mode="json"),
            "decision_ready": loaded.fixture_review.decision_ready,
        },
        "card_preflights": [
            candidate_preflight(loaded, candidate, cases)
            for candidate in candidates
        ],
        "card_snapshots": [_card_snapshot(candidate) for candidate in candidates],
        "prompt_snapshots": prompt_snapshots,
        "card_summaries": summaries,
        "trials": records,
    }

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    run_dir = args.output_dir.resolve() / timestamp
    run_dir.mkdir(parents=True, exist_ok=False)
    json_path = run_dir / "report.json"
    markdown_path = run_dir / "report.md"
    json_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    write_candidate_artifacts(report, run_dir)
    markdown_path.write_text(markdown_report(report), encoding="utf-8")
    print(f"JSON report: {json_path}")
    print(f"Markdown report: {markdown_path}")
    return 0


def main() -> None:
    # Windows shells may default to cp949 while card names contain emoji.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
    try:
        raise SystemExit(asyncio.run(run(parse_args())))
    except MemeExperimentDataError as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(2) from error


if __name__ == "__main__":
    main()
