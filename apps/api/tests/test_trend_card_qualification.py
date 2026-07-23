from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from types import SimpleNamespace
from pathlib import Path

import pytest

from app.evaluation.meme_arm_runner import MemeEvalCase
from app.evaluation.trend_card_runner import (
    CardWorkItem,
    LoadedTrendCardCandidate,
    TrendCardCandidateSpec,
    build_work_items,
    candidate_preflight,
    eligibility_for_case,
    load_candidate,
    load_trend_card_qualification,
    qualification_candidate_id,
    request_for_card_case,
    trial_generation_seed,
)
from app.modules.ad_copy.output_validator import build_fallback_copy, validate_copy_output
from app.modules.ad_copy.trend_context import TrendCardNotUsableError, load_trend_card
from scripts import evaluate_trend_cards as qualification_script


API_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = API_ROOT / "evals" / "trend_card_qualification.json"


def test_manifest_loads_three_cards_and_neutral_cases() -> None:
    loaded = load_trend_card_qualification(MANIFEST_PATH)

    assert loaded.config.strategy == "trendcard"
    assert loaded.config.quality_status == "evidence_only"
    assert [candidate.spec.id for candidate in loaded.candidates] == [
        "trendcard",
        "trendcard1",
        "trendcard2",
    ]
    assert all(candidate.schema_valid for candidate in loaded.candidates)
    assert len(loaded.cases) == 8


def test_runtime_request_overrides_legacy_case_card_id() -> None:
    loaded = load_trend_card_qualification(MANIFEST_PATH)
    case = loaded.cases[0]
    legacy_id = case.request["trend_card_id"]

    runtime_ids = {
        request_for_card_case(loaded, case, candidate).trend_card_id
        for candidate in loaded.candidates
    }

    assert legacy_id == "gogumafarm:1bf390d89536004b"
    assert runtime_ids == {
        candidate.trend_card.meme_id
        for candidate in loaded.candidates
        if candidate.trend_card is not None
    }
    assert len(runtime_ids) == 3


def test_draft_card_is_parsed_without_production_activation(tmp_path: Path) -> None:
    source = json.loads(
        (API_ROOT.parents[1] / "gather_data" / "trendcard.json").read_text(
            encoding="utf-8"
        )
    )
    source["curation_meta"]["status"] = "draft"
    draft_path = tmp_path / "draft-card.json"
    draft_path.write_text(json.dumps(source, ensure_ascii=False), encoding="utf-8")
    spec = TrendCardCandidateSpec(
        id="draft-card",
        label="Draft card",
        path=draft_path.name,
    )

    candidate = load_candidate(tmp_path / "manifest.json", spec)

    assert candidate.schema_valid
    assert candidate.trend_card is not None
    assert candidate.trend_card.curation_meta.status == "draft"
    with pytest.raises(TrendCardNotUsableError):
        load_trend_card(path=draft_path)


def test_incompatible_card_is_skipped_without_aborting_other_cards() -> None:
    loaded = load_trend_card_qualification(MANIFEST_PATH)
    compatible = loaded.candidates[0]
    assert compatible.trend_card is not None
    incompatible = replace(
        loaded.candidates[1],
        trend_card=loaded.candidates[1].trend_card.model_copy(
            update={"suitable_channels": ["naver_blog"]}
        ),
    )
    case = loaded.cases[0]

    eligibility = eligibility_for_case(loaded, incompatible, case)
    work = build_work_items(loaded, [compatible, incompatible], [case], repeats=2)

    assert not eligibility.eligible
    assert eligibility.reasons == ["channel_not_supported"]
    assert len(work) == 2
    assert all(item.candidate.spec.id == compatible.spec.id for item in work)


def test_invalid_candidate_is_card_local_preflight_failure(tmp_path: Path) -> None:
    loaded = load_trend_card_qualification(MANIFEST_PATH)
    missing = load_candidate(
        tmp_path / "manifest.json",
        TrendCardCandidateSpec(
            id="missing-card",
            label="Missing card",
            path="missing.json",
        ),
    )

    preflight = candidate_preflight(loaded, missing, loaded.cases[:1])
    work = build_work_items(
        loaded,
        [loaded.candidates[0], missing],
        loaded.cases[:1],
        repeats=1,
    )

    assert preflight["preflight_status"] == "invalid"
    assert preflight["case_eligibility"][0]["reasons"] == ["card_schema_invalid"]
    assert len(work) == 1


def test_full_dry_run_preflights_all_cards_without_external_calls() -> None:
    loaded = load_trend_card_qualification(MANIFEST_PATH)

    report = qualification_script.build_dry_run_report(
        loaded,
        loaded.candidates,
        loaded.cases,
        repeats=3,
        judge_enabled=False,
    )

    assert report["mode"] == "dry_run"
    assert report["external_api_called"] is False
    assert report["source_artifacts_mutated"] is False
    assert report["quality_status"] == "evidence_only"
    assert report["batch_card_preflight_success"] is True
    assert report["planned_calls"]["eligible_generation_trials"] == 72
    assert len(report["prompt_snapshots"]) == 24
    assert {
        item["preflight_status"] for item in report["card_preflights"]
    } == {"ready"}
    assert all(
        snapshot["source_artifact_unchanged"] is True
        for snapshot in report["card_snapshots"]
    )


def test_generation_seed_is_paired_across_cards_and_id_uses_card_hash() -> None:
    seed_a = trial_generation_seed(20260721, "case-1", 1)
    seed_b = trial_generation_seed(20260721, "case-1", 1)
    next_repeat = trial_generation_seed(20260721, "case-1", 2)
    id_a = qualification_candidate_id("exp", "case-1", 1, "card", "a" * 64)
    id_b = qualification_candidate_id("exp", "case-1", 1, "card", "b" * 64)

    assert seed_a == seed_b
    assert seed_a != next_repeat
    assert id_a != id_b


def test_trial_records_card_and_canonical_output_hash(monkeypatch) -> None:
    loaded = load_trend_card_qualification(MANIFEST_PATH)
    candidate = loaded.candidates[0]
    case: MemeEvalCase = loaded.cases[0]
    request = request_for_card_case(loaded, case, candidate)
    assert candidate.trend_card is not None
    content = build_fallback_copy(request, [], candidate.trend_card)
    validation = validate_copy_output(content, request, candidate.trend_card)

    async def fake_generate(*args, **kwargs):
        return SimpleNamespace(
            content=content,
            raw_content=json.dumps(content.model_dump(mode="json"), ensure_ascii=False),
            initial_content=content,
            normalized_initial_content=content,
            repair_content=None,
            validation=validation,
            initial_validation=validation,
            normalized_initial_validation=validation,
            repair_validation=None,
            repair_attempted=False,
            repair_success=False,
            repair_error=None,
            latency_ms=1.0,
            request_count=1,
            usage={},
            actual_model="test-model",
            structured_output_fallback=False,
            endpoint_model="test-model",
            endpoint_source="test",
            base_revision=None,
            adapter_revision=None,
        )

    monkeypatch.setattr(qualification_script, "generate_arm_copy", fake_generate)
    item = CardWorkItem(case=case, candidate=candidate, repeat=1)

    record = asyncio.run(
        qualification_script.evaluate_trial(
            loaded,
            item,
            judge_enabled=False,
            semaphore=asyncio.Semaphore(1),
        )
    )

    output = qualification_script.build_meme_judge_input(
        request,
        candidate.trend_card,
        content,
    ).customer_visible_result.model_dump(mode="json")
    assert record["card_id"] == candidate.spec.id
    assert record["card_sha256"] == candidate.artifact_sha256
    assert record["card_artifact_sha256"] == candidate.artifact_sha256
    assert record["output_sha256"] == qualification_script.canonical_json_sha256(output)
    assert record["output_id"].startswith(record["trial_id"])
    assert record["customer_visible_output"] == output
    assert record["trend_card_id"] == candidate.trend_card.meme_id
    assert record["quality_status"] == "evidence_only"
    assert record["judge_success"] is None
