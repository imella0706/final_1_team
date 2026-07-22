import asyncio
import json
import re
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from app.evaluation import meme_arm_runner
from scripts import evaluate_meme_arms as evaluation_script
from app.evaluation.meme_schemas import MemeJudgeResult
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
    build_dry_run_report,
    build_paired_analysis,
    deterministic_validation_evidence,
    evaluate_trial,
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


def test_few_shot_examples_teach_complete_korean_publish_contract() -> None:
    loaded = load_meme_experiment(EXPERIMENT_PATH)

    for example in loaded.examples:
        good = example.good_output
        assert good.product_name_preserved
        assert good.language == "ko"
        assert good.failure_codes == []
        assert good.publish_cta
        assert good.publish_hashtags
        assert all(tag.startswith("#") and tag.count("#") == 1 for tag in good.publish_hashtags)
        assert any(
            product_name in good.primary_copy
            or product_name in good.channel_post_opening
            for product_name in example.input["product_names"]
        )
        assert all(
            required_term in (
                f"{good.primary_copy} {good.channel_post_opening} "
                f"{good.publish_cta} {' '.join(good.publish_hashtags)}"
            )
            for required_term in example.input["required_terms"]
        )
        assert example.bad_output.failure_codes

    current_case_facts = {
        "청포도 요거트 스무디",
        "청포도 과육",
        "요거트 베이스",
        "모퉁이온도",
    }
    serialized_examples = json.dumps(
        [example.model_dump(mode="json") for example in loaded.examples],
        ensure_ascii=False,
    )
    assert all(fact not in serialized_examples for fact in current_case_facts)
    assert (
        re.search(
            r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff]",
            serialized_examples,
        )
        is None
    )


def test_few_shot_prompt_explains_annotation_fields_are_not_output_fields() -> None:
    loaded = load_meme_experiment(EXPERIMENT_PATH)
    case = loaded.cases[0]
    request = AdCopyRequest.model_validate(
        {**case.request, "model": loaded.config.base_model}
    )
    arm = next(
        arm for arm in loaded.config.arms if arm.strategy == "few_shot_good_bad"
    )

    prompt = _prompt_text(
        build_arm_messages(request, loaded.trend_card, arm, loaded.examples)
    )

    assert "channel_recommendation.caption의 첫 문장" in prompt
    assert "상품명을 원문 그대로 유지" in prompt
    assert "required_terms" in prompt
    assert "자연스러운 한국어" in prompt
    assert "bad.failure_codes" in prompt
    assert "최종 광고 JSON에 새 필드로 추가하지 마세요" in prompt


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


def test_paired_analysis_does_not_treat_judge_advice_as_release_gate() -> None:
    loaded = load_meme_experiment(EXPERIMENT_PATH)
    arms = [arm for arm in loaded.config.arms if arm.enabled][:2]
    records = [
        _paired_record(arms[0].id, judge_score=5.0, operational_valid=True),
        _paired_record(arms[1].id, judge_score=4.0, operational_valid=True),
    ]
    # Historical Judge output may contain an incorrect exact-match finding.
    records[0]["judge"]["hard_failures"] = ["필수어가 누락되었다고 추정"]

    analysis = build_paired_analysis(
        arms,
        records,
        judge_enabled=True,
        fixtures_reviewed=True,
        decision_eligible=True,
    )

    assert analysis["status"] == "complete"
    assert [item["arm_id"] for item in analysis["ranking"]] == [
        arms[0].id,
        arms[1].id,
    ]
    assert analysis["winner_arm_id"] == arms[0].id
    assert (
        analysis["arm_scores_on_paired_blocks"][0][
            "judge_advisory_finding_rate_percent"
        ]
        == 100.0
    )


def test_deterministic_validation_codes_are_authoritative() -> None:
    record = {
        "generation_success": True,
        "rule_valid": False,
        "rule_warnings": ["caption 첫 문장에 마커가 없습니다."],
        "production_failure_codes": ["trend_marker_missing_in_caption"],
        "required_term_compliance_rate": 1.0,
        "hashtag_compliance_rate": 1.0,
        "example_leakage_terms": [],
        "hallucination_terms": [],
        "toxicity_terms": [],
    }

    evidence = deterministic_validation_evidence(record)

    assert evidence["authoritative"] is True
    assert evidence["passed"] is False
    assert evidence["failure_codes"] == ["trend_marker_missing_in_caption"]
    assert evidence["failure_details"] == ["caption 첫 문장에 마커가 없습니다."]


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
    assert result.initial_request_count == 1
    assert result.repair_request_count == 0
    assert not result.repair_attempted
    assert result.raw_initial_content == result.raw_content
    assert result.normalized_initial_validation.valid
    assert result.usage["total_tokens"] == 280
    assert result.actual_model == "qwen-test-revision"


def test_evaluate_trial_judges_initial_output_and_records_repair_stages(
    monkeypatch,
) -> None:
    loaded = load_meme_experiment(EXPERIMENT_PATH)
    case = loaded.cases[0]
    arm = next(arm for arm in loaded.config.arms if arm.id == "trendcard")
    request = AdCopyRequest.model_validate(
        {**case.request, "model": loaded.config.base_model}
    )
    final_content = build_fallback_copy(request, [], loaded.trend_card)
    initial_content = final_content.model_copy(deep=True)
    initial_content.headlines[0] = "모델이 처음 만든 초안"
    validation = SimpleNamespace(valid=True, warnings=[], failure_codes=[])
    generated = SimpleNamespace(
        content=final_content,
        raw_content="final-json",
        initial_content=initial_content,
        raw_initial_content="initial-json",
        initial_validation=SimpleNamespace(
            valid=False,
            warnings=["초안 실패"],
            failure_codes=["trend_marker_missing_in_primary_copy"],
        ),
        normalized_initial_content=initial_content,
        normalized_initial_validation=SimpleNamespace(
            valid=False,
            warnings=["초안 실패"],
            failure_codes=["trend_marker_missing_in_primary_copy"],
        ),
        repair_content=final_content,
        raw_repair_content="repair-json",
        repair_validation=validation,
        repair_attempted=True,
        repair_success=True,
        repair_error=None,
        validation=validation,
        latency_ms=10.0,
        request_count=2,
        initial_request_count=1,
        repair_request_count=1,
        usage={"total_tokens": 30},
        initial_usage={"total_tokens": 20},
        repair_usage={"total_tokens": 10},
        actual_model="qwen-test",
        structured_output_fallback=False,
        endpoint_model="qwen-test",
        endpoint_source="base",
        base_revision=None,
        adapter_revision=None,
    )
    judged_headlines = []

    async def fake_generate(*args, **kwargs):
        return generated

    async def fake_judge(request, trend_card, content, **kwargs):
        judged_headlines.extend(content.headlines)
        return SimpleNamespace(
            result=MemeJudgeResult(
                naturalness=4,
                pattern_fidelity=4,
                product_relevance=4,
                factuality=4,
                channel_readiness=4,
                hard_failures=["참고 의견"],
                reason="정성 평가",
            ),
            latency_ms=5.0,
            usage={"total_tokens": 10},
            actual_model="judge-test",
        )

    monkeypatch.setattr(evaluation_script, "generate_arm_copy", fake_generate)
    monkeypatch.setattr(
        evaluation_script,
        "judge_meme_copy_with_metadata",
        fake_judge,
    )

    record = asyncio.run(
        evaluate_trial(
            loaded,
            case,
            arm,
            repeat=1,
            judge_enabled=True,
            semaphore=asyncio.Semaphore(1),
        )
    )

    assert judged_headlines[0] == "모델이 처음 만든 초안"
    assert record["judge_target"] == "initial_output"
    assert record["initial_output"]["headlines"][0] == "모델이 처음 만든 초안"
    assert record["repair_output"] == final_content.model_dump(mode="json")
    assert record["output"] == final_content.model_dump(mode="json")
    assert record["repair_attempted"] is True
    assert record["repair_success"] is True
    assert record["judge"]["advisory_findings"] == ["참고 의견"]
    assert "hard_failures" not in record["judge"]


def test_generation_repairs_normalized_validation_failure_once(monkeypatch) -> None:
    loaded = load_meme_experiment(EXPERIMENT_PATH)
    case = loaded.cases[0]
    arm = next(arm for arm in loaded.config.arms if arm.strategy == "trendcard")
    request = AdCopyRequest.model_validate(
        {**case.request, "model": loaded.config.base_model}
    )
    valid_content = build_fallback_copy(request, [], loaded.trend_card)
    initial_recommendation = valid_content.channel_recommendation.model_copy(
        update={
            "caption": "청포도 요거트 스무디를 산뜻하게 즐겨보세요.",
            "publish_body": "모델이 임의로 조립한 게시물",
        }
    )
    invalid_initial = valid_content.model_copy(
        update={
            "headlines": ["산뜻한 청포도 요거트 스무디"],
            "channel_recommendation": initial_recommendation,
        }
    )
    response_bodies = [
        json.dumps(content.model_dump(mode="json"), ensure_ascii=False)
        for content in (invalid_initial, valid_content)
    ]
    payloads: list[dict] = []

    class FakeClient:
        def __init__(self, timeout):
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return False

        async def post(self, url, *, headers, json):
            payloads.append(json)
            return httpx.Response(
                200,
                json={
                    "model": "qwen-test-revision",
                    "usage": {
                        "prompt_tokens": 100,
                        "completion_tokens": 50,
                        "total_tokens": 150,
                    },
                    "choices": [
                        {"message": {"content": response_bodies[len(payloads) - 1]}}
                    ],
                },
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
    experiment = loaded.config.model_copy(
        update={
            "generation": loaded.config.generation.model_copy(
                update={"max_attempts": 2}
            )
        }
    )
    monkeypatch.setattr(
        meme_arm_runner,
        "resolve_generation_endpoint",
        lambda selected_experiment, selected_arm: endpoint,
    )
    monkeypatch.setattr(meme_arm_runner.httpx, "AsyncClient", FakeClient)

    result = asyncio.run(
        meme_arm_runner.generate_arm_copy(
            request,
            experiment,
            loaded.trend_card,
            arm,
            loaded.examples,
            12345,
        )
    )

    assert len(payloads) == 2
    assert payloads[0]["temperature"] == experiment.generation.temperature
    assert payloads[1]["temperature"] == 0.2
    repair_prompt = payloads[1]["messages"][-1]["content"]
    assert "trend_marker_missing_in_primary_copy" in repair_prompt
    assert "trend_marker_missing_in_caption_opening" in repair_prompt
    assert result.initial_content == invalid_initial
    assert not result.initial_validation.valid
    assert not result.normalized_initial_validation.valid
    assert result.repair_attempted
    assert result.repair_success
    assert result.repair_error is None
    assert result.repair_content is not None
    assert result.validation.valid
    assert result.request_count == 2
    assert result.initial_request_count == 1
    assert result.repair_request_count == 1
    assert result.usage["total_tokens"] == 300


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


def test_dry_run_request_ceiling_accounts_for_repair_and_schema_fallback() -> None:
    loaded = load_meme_experiment(EXPERIMENT_PATH)
    arms = [arm for arm in loaded.config.arms if arm.enabled][:2]

    report = build_dry_run_report(
        loaded,
        arms,
        loaded.cases[:1],
        repeats=1,
        judge_enabled=True,
    )

    planned = report["planned_calls"]
    trials = len(arms)
    max_attempts = loaded.config.generation.max_attempts
    assert planned["generator_http_requests_minimum"] == trials
    assert planned["generator_http_requests_maximum"] == (
        trials * max_attempts * 2
    )
    assert planned["external_http_requests_worst_case"] == (
        trials * max_attempts * 2 + trials
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


def test_arm_summary_separates_initial_repair_and_final_rates() -> None:
    loaded = load_meme_experiment(EXPERIMENT_PATH)
    arm = next(arm for arm in loaded.config.arms if arm.id == "trendcard")
    repaired = _summary_record(generation_success=True, judge_success=True)
    repaired.update(
        {
            "initial_validation": {"valid": False},
            "repair_attempted": True,
            "repair_success": True,
            "rule_valid": True,
            "hashtag_compliance_rate": 1.0,
        }
    )

    summary = summarize_arm(arm, [repaired])

    assert summary["initial_rule_pass_rate_percent"] == 0.0
    assert summary["repair_attempt_rate_percent"] == 100.0
    assert summary["repair_success_rate_percent"] == 100.0
    assert summary["rule_pass_rate_percent"] == 100.0


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
    assert "최종 output JSON" in rendered
    assert "candidate_outputs/candidate-test.json" in rendered
    artifact = json.loads(
        (candidate_dir / "candidate-test.json").read_text(encoding="utf-8")
    )
    assert artifact["output"]["headlines"][0] == "니가 좋아, 청포도 스무디"
