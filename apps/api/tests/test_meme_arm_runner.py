import asyncio
import json
from pathlib import Path

import httpx
import pytest

from app.evaluation import meme_arm_runner
from app.evaluation.meme_arm_runner import (
    GenerationEndpoint,
    MemeExperimentDataError,
    _structured_output_is_unsupported,
    build_arm_messages,
    find_example_leakage,
    load_meme_experiment,
    marker_compliance,
    resolve_generation_endpoint,
    visible_hallucination_terms,
    visible_required_term_compliance_rate,
    visible_toxicity_terms,
)
from scripts.evaluate_meme_arms import (
    assess_decision_eligibility,
    build_paired_analysis,
    enforce_execution_safety,
    markdown_report,
    operational_failure_reasons,
    record_operationally_valid,
    rebuild_saved_report,
    summarize_arm,
    trial_generation_seed,
    write_candidate_artifacts,
)
from app.modules.ad_copy.output_validator import build_fallback_copy
from app.modules.ad_copy.schemas import AdCopyRequest
from app.modules.model_runtime.schemas import TextRuntimeProvider


API_ROOT = Path(__file__).resolve().parents[1]
EXPERIMENT_PATH = API_ROOT / "evals" / "meme_5arm_experiment.json"


def _prompt_text(messages: list[dict[str, str]]) -> str:
    return "\n".join(message["content"] for message in messages)


def test_experiment_loads_one_card_cases_and_examples() -> None:
    loaded = load_meme_experiment(EXPERIMENT_PATH)

    assert loaded.trend_card.meme_id == "gogumafarm:1bf390d89536004b"
    assert loaded.trend_card_path.name == "trendcard.json"
    assert len(loaded.cases) == 8
    assert len(loaded.examples) == 3
    assert {case.case_type for case in loaded.cases} == {
        "single_product",
        "multi_product",
        "promotion",
        "far_transfer",
    }
    assert [arm.id for arm in loaded.config.arms if arm.enabled] == [
        "trendcard",
        "few_shot_good",
        "few_shot_good_bad",
        "structured_cot",
    ]
    lora = next(arm for arm in loaded.config.arms if arm.strategy == "lora")
    assert not lora.enabled
    assert lora.disabled_reason


def test_arm_prompts_change_only_the_declared_strategy_block() -> None:
    loaded = load_meme_experiment(EXPERIMENT_PATH)
    case = loaded.cases[0]
    request = AdCopyRequest.model_validate(
        {**case.request, "model": loaded.config.base_model}
    )
    prompts = {
        arm.strategy: _prompt_text(
            build_arm_messages(
                request,
                loaded.trend_card,
                arm,
                loaded.examples,
            )
        )
        for arm in loaded.config.arms
        if arm.enabled
    }

    assert all(loaded.trend_card.meme_id in prompt for prompt in prompts.values())
    assert "흑임자 크림라떼" not in prompts["trendcard"]
    assert "흑임자 크림라떼" in prompts["few_shot_good"]
    assert "니가 좋아, 흑임자 크림라떼, 아이스, 흑임자 크림." not in (
        prompts["few_shot_good"]
    )
    assert "니가 좋아, 흑임자 크림라떼, 아이스, 흑임자 크림." in (
        prompts["few_shot_good_bad"]
    )
    assert "내부 작성 절차" in prompts["structured_cot"]
    assert "흑임자 크림라떼" not in prompts["structured_cot"]


def test_example_leakage_detector_uses_facts_absent_from_current_request() -> None:
    loaded = load_meme_experiment(EXPERIMENT_PATH)
    case = loaded.cases[0]
    request = AdCopyRequest.model_validate(
        {**case.request, "model": loaded.config.base_model}
    )
    content = build_fallback_copy(request, [], loaded.trend_card)

    assert marker_compliance(content, loaded.trend_card)
    assert find_example_leakage(request, content, loaded.examples) == []

    leaked = content.model_copy(
        update={"headlines": ["니가 좋아, 흑임자 크림라떼"]}
    )
    leakage = find_example_leakage(request, leaked, loaded.examples)
    assert "흑임자 크림라떼" in leakage
    assert "흑임자" in leakage


def test_enabled_lora_routes_other_arms_to_same_server() -> None:
    loaded = load_meme_experiment(EXPERIMENT_PATH)
    raw = loaded.config.model_dump(mode="json")
    for arm in raw["arms"]:
        if arm["strategy"] == "lora":
            arm.update(
                {
                    "enabled": True,
                    "base_url": "http://127.0.0.1:8000/v1",
                    "model": "brandmate-meme",
                    "base_revision": "a" * 40,
                    "adapter_revision": "run-001-manifest-sha256",
                }
            )
    config = type(loaded.config).model_validate(raw)
    baseline = next(arm for arm in config.arms if arm.strategy == "trendcard")
    lora = next(arm for arm in config.arms if arm.strategy == "lora")

    baseline_endpoint = resolve_generation_endpoint(config, baseline)
    lora_endpoint = resolve_generation_endpoint(config, lora)

    assert baseline_endpoint.base_url == lora_endpoint.base_url
    assert baseline_endpoint.model == config.base_model
    assert lora_endpoint.model == "brandmate-meme"
    assert baseline_endpoint.source == "shared_lora_server_base"


def test_visible_metrics_include_instagram_publish_body() -> None:
    loaded = load_meme_experiment(EXPERIMENT_PATH)
    case = loaded.cases[0]
    request = AdCopyRequest.model_validate(
        {**case.request, "model": loaded.config.base_model}
    )
    content = build_fallback_copy(request, [], loaded.trend_card)
    recommendation = content.channel_recommendation.model_copy(
        update={
            "publish_body": (
                content.channel_recommendation.publish_body
                + "\n입력에 없는 전국 1위 인증. 혐오 표현."
            )
        }
    )
    modified = content.model_copy(
        update={"channel_recommendation": recommendation}
    )

    assert visible_required_term_compliance_rate(request, modified) == 1.0
    assert "1위" in visible_hallucination_terms(request, modified)
    assert "인증" in visible_hallucination_terms(request, modified)
    assert "혐오" in visible_toxicity_terms(modified)


def test_structured_fallback_only_accepts_relevant_provider_error() -> None:
    supported_error = httpx.Response(
        400,
        json={"error": {"message": "response_format json_schema is unsupported"}},
    )
    vllm_grammar_error = httpx.Response(
        422,
        json={"error": {"message": "Failed to compile grammar for this schema"}},
    )
    unrelated_error = httpx.Response(
        400,
        json={"error": {"message": "model does not exist"}},
    )

    assert _structured_output_is_unsupported(supported_error)
    assert _structured_output_is_unsupported(vllm_grammar_error)
    assert not _structured_output_is_unsupported(unrelated_error)


def test_paired_analysis_suppresses_ranking_when_any_arm_is_missing() -> None:
    loaded = load_meme_experiment(EXPERIMENT_PATH)
    arms = [arm for arm in loaded.config.arms if arm.enabled][:2]
    records = [
        {
            "case_id": "case-1",
            "repeat": 1,
            "arm_id": arms[0].id,
            "generation_success": True,
            "judge_success": True,
            "rule_valid": True,
            "judge": {"overall_score": 5.0, "hard_failures": []},
        },
        {
            "case_id": "case-1",
            "repeat": 1,
            "arm_id": arms[1].id,
            "generation_success": False,
            "judge_success": False,
            "rule_valid": False,
        },
    ]

    analysis = build_paired_analysis(
        arms,
        records,
        judge_enabled=True,
        fixtures_reviewed=True,
        decision_eligible=True,
    )
    assert analysis["status"] == "incomplete_paired_coverage"
    assert analysis["ranking"] == []


def _paired_record(
    arm_id: str,
    *,
    judge_score: float,
    operational_valid: bool,
) -> dict:
    return {
        "case_id": "case-1",
        "case_type": "single_product",
        "repeat": 1,
        "arm_id": arm_id,
        "generation_success": True,
        "judge_success": True,
        "rule_valid": operational_valid,
        "operational_valid": operational_valid,
        "required_term_compliance_rate": 1.0,
        "hashtag_compliance_rate": 1.0,
        "example_leakage_terms": [],
        "hallucination_terms": [],
        "toxicity_terms": [],
        "judge": {"overall_score": judge_score, "hard_failures": []},
    }


def test_paired_analysis_never_ranks_rule_invalid_arms() -> None:
    loaded = load_meme_experiment(EXPERIMENT_PATH)
    arms = [arm for arm in loaded.config.arms if arm.enabled][:2]
    records = [
        _paired_record(arms[0].id, judge_score=5.0, operational_valid=False),
        _paired_record(arms[1].id, judge_score=4.0, operational_valid=False),
    ]

    analysis = build_paired_analysis(
        arms,
        records,
        judge_enabled=True,
        fixtures_reviewed=True,
        decision_eligible=True,
    )

    assert analysis["status"] == "no_operationally_eligible_arm"
    assert analysis["ranking"] == []
    assert analysis["winner_arm_id"] is None


def test_paired_analysis_ranks_only_operationally_eligible_arms() -> None:
    loaded = load_meme_experiment(EXPERIMENT_PATH)
    arms = [arm for arm in loaded.config.arms if arm.enabled][:2]
    records = [
        _paired_record(arms[0].id, judge_score=5.0, operational_valid=False),
        _paired_record(arms[1].id, judge_score=4.0, operational_valid=True),
    ]

    analysis = build_paired_analysis(
        arms,
        records,
        judge_enabled=True,
        fixtures_reviewed=True,
        decision_eligible=True,
    )

    assert analysis["status"] == "complete"
    assert [item["arm_id"] for item in analysis["ranking"]] == [arms[1].id]
    assert analysis["winner_arm_id"] == arms[1].id


def test_historical_record_operational_validity_is_derived_conservatively() -> None:
    valid = {
        "generation_success": True,
        "rule_valid": True,
        "required_term_compliance_rate": 1.0,
        "hashtag_compliance_rate": 1.0,
        "example_leakage_terms": [],
        "hallucination_terms": [],
        "toxicity_terms": [],
    }
    invalid = {**valid, "required_term_compliance_rate": 0.5}

    assert record_operationally_valid(valid)
    assert not record_operationally_valid(invalid)
    assert operational_failure_reasons(invalid) == ["required_terms_missing"]


def test_instagram_publish_package_is_part_of_operational_gate() -> None:
    base = {
        "generation_success": True,
        "rule_valid": True,
        "required_term_compliance_rate": 1.0,
        "hashtag_compliance_rate": 1.0,
        "example_leakage_terms": [],
        "hallucination_terms": [],
        "toxicity_terms": [],
        "channel": "instagram",
        "output": {
            "headlines": ["니가 좋아, 청포도 스무디"],
            "body_copies": ["산뜻하게 즐겨요."],
            "ctas": ["매장에서 만나보세요."],
            "hashtags": ["#청포도스무디"],
            "channel_recommendation": {
                "format_name": "Instagram",
                "caption": "니가 좋아, 청포도 스무디.\n#청포도스무디",
                "publish_cta": "매장에서 만나보세요.",
                "publish_hashtags": ["#청포도스무디"],
                "publish_body": "니가 좋아, 청포도 스무디.\n#청포도스무디",
            },
        },
    }

    reasons = operational_failure_reasons(base)

    assert "instagram_caption_contains_hashtags" in reasons
    assert "instagram_publish_body_missing_cta" in reasons
    assert not record_operationally_valid(base)


def test_single_case_smoke_is_not_decision_eligible() -> None:
    loaded = load_meme_experiment(EXPERIMENT_PATH)
    arms = [arm for arm in loaded.config.arms if arm.enabled]

    eligible, reasons = assess_decision_eligibility(
        loaded,
        arms,
        loaded.cases[:1],
        1,
    )

    assert not eligible
    assert "not_all_fixture_cases_selected" in reasons
    assert "repeats_below_configured_experiment" in reasons


def test_reviewed_but_incomplete_scope_is_still_engineering_smoke() -> None:
    loaded = load_meme_experiment(EXPERIMENT_PATH)
    arms = [arm for arm in loaded.config.arms if arm.enabled][:2]
    records = [
        _paired_record(arms[0].id, judge_score=5.0, operational_valid=True),
        _paired_record(arms[1].id, judge_score=4.0, operational_valid=True),
    ]

    analysis = build_paired_analysis(
        arms,
        records,
        judge_enabled=True,
        fixtures_reviewed=True,
        decision_eligible=False,
        decision_ineligibility_reasons=["not_all_fixture_cases_selected"],
    )

    assert analysis["status"] == "engineering_smoke"
    assert analysis["ranking"] == []
    assert analysis["winner_arm_id"] is None


def test_generation_seed_is_paired_across_arms_and_varies_by_repeat() -> None:
    first = trial_generation_seed(20260721, "case-1", 1)
    same_pair = trial_generation_seed(20260721, "case-1", 1)
    next_repeat = trial_generation_seed(20260721, "case-1", 2)

    assert first == same_pair
    assert first != next_repeat


def test_generation_call_sends_seed_and_records_usage(monkeypatch) -> None:
    loaded = load_meme_experiment(EXPERIMENT_PATH)
    case = loaded.cases[0]
    arm = next(arm for arm in loaded.config.arms if arm.strategy == "trendcard")
    request = AdCopyRequest.model_validate(
        {**case.request, "model": loaded.config.base_model}
    )
    content = build_fallback_copy(request, [], loaded.trend_card)
    captured = {}
    response_payload = {
        "model": "qwen-test-revision",
        "usage": {"prompt_tokens": 200, "completion_tokens": 80, "total_tokens": 280},
        "choices": [
            {"message": {"content": json.dumps(content.model_dump(mode="json"))}}
        ],
    }

    class FakeClient:
        def __init__(self, timeout):
            captured["timeout"] = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return False

        async def post(self, url, *, headers, json):
            captured.update({"url": url, "headers": headers, "payload": json})
            return httpx.Response(
                200,
                json=response_payload,
                request=httpx.Request("POST", url),
            )

    endpoint = GenerationEndpoint(
        base_url="https://qwen.example/v1",
        model="Qwen/Qwen2.5-7B-Instruct",
        api_key="test-key",
        provider=TextRuntimeProvider.HUGGING_FACE_ROUTER,
        supports_system_role=True,
        supports_structured_output=True,
        source="base",
    )
    monkeypatch.setattr(
        meme_arm_runner,
        "resolve_generation_endpoint",
        lambda experiment, selected_arm: endpoint,
    )
    monkeypatch.setattr(meme_arm_runner.httpx, "AsyncClient", FakeClient)

    result = asyncio.run(
        meme_arm_runner.generate_arm_copy(
            request,
            loaded.config,
            loaded.trend_card,
            arm,
            loaded.examples,
            12345,
        )
    )

    assert captured["payload"]["seed"] == 12345
    assert result.request_count == 1
    assert result.usage["total_tokens"] == 280
    assert result.actual_model == "qwen-test-revision"


def test_unreviewed_fixtures_are_limited_to_explicit_one_case_smoke() -> None:
    loaded = load_meme_experiment(EXPERIMENT_PATH)

    with pytest.raises(MemeExperimentDataError, match="아직 사람·권리 검수 전"):
        enforce_execution_safety(
            loaded,
            loaded.cases[:1],
            1,
            12,
            allow_large_run=False,
            allow_unreviewed_fixtures=False,
        )

    enforce_execution_safety(
        loaded,
        loaded.cases[:1],
        1,
        12,
        allow_large_run=False,
        allow_unreviewed_fixtures=True,
    )

    with pytest.raises(MemeExperimentDataError, match="1 case × 1 repeat"):
        enforce_execution_safety(
            loaded,
            loaded.cases,
            3,
            288,
            allow_large_run=True,
            allow_unreviewed_fixtures=True,
        )


def _summary_record(*, generation_success: bool, judge_success: bool | None):
    record = {
        "case_id": "case-1",
        "case_type": "single_product",
        "repeat": 1,
        "arm_id": "trendcard",
        "generation_success": generation_success,
        "rule_valid": False,
        "generation_http_request_count": 1,
        "generation_usage": {},
    }
    if generation_success:
        record.update(
            {
                "marker_compliant": False,
                "example_leakage_terms": [],
                "hallucination_terms": [],
                "context_adherence_score": 0.5,
                "required_term_compliance_rate": 1.0,
                "generation_latency_ms": 100.0,
                "judge_success": judge_success,
            }
        )
    if judge_success:
        record.update(
            {
                "judge_http_request_count": 1,
                "judge_usage": {},
                "judge": {
                    "naturalness": 4,
                    "pattern_fidelity": 3,
                    "product_relevance": 4,
                    "factuality": 5,
                    "channel_readiness": 4,
                    "overall_score": 4.0,
                    "hard_failures": [],
                    "reason": "테스트",
                },
            }
        )
    return record


@pytest.mark.parametrize(
    ("record", "expected_score"),
    [
        (_summary_record(generation_success=True, judge_success=True), 4.0),
        (_summary_record(generation_success=True, judge_success=None), None),
        (_summary_record(generation_success=False, judge_success=None), None),
    ],
)
def test_arm_summary_and_markdown_handle_missing_judge_results(
    record,
    expected_score,
) -> None:
    loaded = load_meme_experiment(EXPERIMENT_PATH)
    arm = next(arm for arm in loaded.config.arms if arm.id == "trendcard")
    summary = summarize_arm(arm, [record])
    assert isinstance(summary, dict)
    assert summary["judge_scores"]["overall_score"] == expected_score

    report = {
        "metadata": {
            "generated_at": "2026-07-21T00:00:00Z",
            "trend_card_id": loaded.trend_card.meme_id,
            "base_model": loaded.config.base_model,
            "case_count": 1,
            "repeats": 1,
            "judge_model": loaded.config.judge.model,
        },
        "paired_analysis": {
            "status": "incomplete_paired_coverage",
            "paired_coverage_percent": 0.0,
            "ranking": [],
        },
        "arm_summaries": [summary],
    }
    rendered = markdown_report(report)
    assert "TrendCard only" in rendered
    assert "## Paired 순위" in rendered


def test_saved_report_rebuild_replaces_null_summaries_without_calls() -> None:
    loaded = load_meme_experiment(EXPERIMENT_PATH)
    report = {
        "metadata": {"judge_model": loaded.config.judge.model},
        "experiment_config_snapshot": loaded.config.model_dump(mode="json"),
        "fixture_review": {"decision_ready": False},
        "arm_summaries": [None],
        "trials": [
            _summary_record(generation_success=False, judge_success=None)
        ],
    }

    repaired = rebuild_saved_report(report)

    assert repaired["arm_summaries"][0]["arm_id"] == "trendcard"
    assert repaired["arm_summaries"][0]["judge_scores"]["overall_score"] is None
    assert repaired["paired_analysis"]["status"] == "fixture_not_reviewed"


def test_markdown_contains_each_candidate_output_and_artifact_link(tmp_path) -> None:
    loaded = load_meme_experiment(EXPERIMENT_PATH)
    arm = next(arm for arm in loaded.config.arms if arm.id == "trendcard")
    record = _summary_record(generation_success=True, judge_success=True)
    record.update(
        {
            "candidate_id": "candidate-test",
            "generation_seed": 123,
            "generation_actual_model": "qwen-test",
            "hashtag_compliance_rate": 1.0,
            "output": {
                "headlines": ["니가 좋아, 청포도 스무디"],
                "body_copies": ["청포도 과육으로 산뜻하게 즐겨요."],
                "ctas": ["매장에서 만나보세요."],
                "hashtags": ["#청포도스무디"],
                "channel_recommendation": {
                    "format_name": "Instagram",
                    "caption": "니가 좋아, 청포도 스무디.",
                    "publish_cta": "매장에서 만나보세요.",
                    "publish_hashtags": ["#청포도스무디"],
                    "publish_title": "니가 좋아, 청포도 스무디",
                    "publish_body": (
                        "니가 좋아, 청포도 스무디.\n\n"
                        "매장에서 만나보세요.\n#청포도스무디"
                    ),
                },
            },
        }
    )
    report = {
        "metadata": {
            "generated_at": "2026-07-21T00:00:00Z",
            "trend_card_id": loaded.trend_card.meme_id,
            "base_model": loaded.config.base_model,
            "case_count": 1,
            "repeats": 1,
            "judge_model": loaded.config.judge.model,
        },
        "experiment_config_snapshot": loaded.config.model_dump(mode="json"),
        "prompt_snapshots": [],
        "paired_analysis": {
            "status": "fixture_not_reviewed",
            "decision_eligible": False,
            "paired_coverage_percent": 100.0,
            "winner_arm_id": None,
            "ranking": [],
        },
        "arm_summaries": [summarize_arm(arm, [record])],
        "trials": [record],
    }

    rendered = markdown_report(report)
    candidate_dir = write_candidate_artifacts(report, tmp_path)

    assert "## 후보별 생성 출력" in rendered
    assert "니가 좋아, 청포도 스무디" in rendered
    assert "전체 생성 output JSON" in rendered
    assert "candidate_outputs/candidate-test.json" in rendered
    artifact = json.loads(
        (candidate_dir / "candidate-test.json").read_text(encoding="utf-8")
    )
    assert artifact["output"]["headlines"][0] == "니가 좋아, 청포도 스무디"
