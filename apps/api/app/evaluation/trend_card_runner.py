"""Core types and preflight helpers for TrendCard qualification runs.

This module intentionally does not use :func:`load_trend_card`.  Production
loading requires a human-reviewed card, while qualification must be able to
inspect a draft without changing or activating the source artifact.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from app.evaluation.meme_arm_runner import (
    MemeEvalArm,
    MemeEvalCase,
    MemeExperimentDataError,
    MemeFixtureReview,
    MemeGenerationSettings,
    MemeJudgeSettings,
    build_arm_messages,
    resolve_generation_endpoint,
)
from app.modules.ad_copy.schemas import AdCopyRequest
from app.modules.ad_copy.trend_context import TrendCard


FIXED_STRATEGY_ID = "trendcard"
EVIDENCE_ONLY_STATUS = "evidence_only"


class TrendCardCandidateSpec(BaseModel):
    """One immutable input artifact in a qualification batch."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=80, pattern=r"^[a-z0-9_-]+$")
    label: str = Field(min_length=1, max_length=160)
    path: str = Field(min_length=1)
    enabled: bool = True
    notes: str = Field(default="", max_length=500)


class TrendCardQualificationConfig(BaseModel):
    """Configuration for a fixed-strategy, many-card qualification run."""

    model_config = ConfigDict(extra="forbid")

    experiment_id: str = Field(min_length=1, max_length=120)
    description: str = Field(min_length=1, max_length=500)
    base_model: str = Field(min_length=1, max_length=200)
    strategy: Literal["trendcard"] = FIXED_STRATEGY_ID
    quality_status: Literal["evidence_only"] = EVIDENCE_ONLY_STATUS
    dataset_path: str = Field(min_length=1)
    fixture_review_path: str = Field(min_length=1)
    cards: list[TrendCardCandidateSpec] = Field(min_length=1)
    generation: MemeGenerationSettings
    judge: MemeJudgeSettings

    @model_validator(mode="after")
    def validate_unique_candidates(self) -> "TrendCardQualificationConfig":
        ids = [candidate.id for candidate in self.cards]
        if len(ids) != len(set(ids)):
            raise ValueError("TrendCard candidate id must be unique")
        return self

    @property
    def arms(self) -> list[MemeEvalArm]:
        """Compatibility surface used by the existing generation endpoint resolver."""

        return [fixed_strategy_arm()]


@dataclass(frozen=True)
class LoadedTrendCardCandidate:
    """A candidate plus parse evidence; invalid cards do not abort the batch."""

    spec: TrendCardCandidateSpec
    path: Path
    artifact_sha256: str | None
    trend_card: TrendCard | None
    load_error: str | None

    @property
    def schema_valid(self) -> bool:
        return self.trend_card is not None and self.load_error is None


@dataclass(frozen=True)
class LoadedTrendCardQualification:
    config_path: Path
    config: TrendCardQualificationConfig
    dataset_path: Path
    fixture_review_path: Path
    candidates: list[LoadedTrendCardCandidate]
    cases: list[MemeEvalCase]
    fixture_review: MemeFixtureReview


class CardCaseEligibility(BaseModel):
    """Whether one card can be exercised on one neutral advertising case."""

    model_config = ConfigDict(extra="forbid")

    case_id: str
    channel: str
    eligible: bool
    reasons: list[str] = Field(default_factory=list)


@dataclass(frozen=True)
class CardWorkItem:
    case: MemeEvalCase
    candidate: LoadedTrendCardCandidate
    repeat: int


def fixed_strategy_arm() -> MemeEvalArm:
    """Return the one strategy shared by every candidate card."""

    return MemeEvalArm(
        id=FIXED_STRATEGY_ID,
        label="Fixed production TrendCard strategy",
        strategy="trendcard",
        enabled=True,
    )


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise MemeExperimentDataError(f"Unable to read qualification JSON: {path}") from error


def _resolve_path(config_path: Path, value: str) -> Path:
    path = Path(value)
    if not path.is_absolute():
        path = config_path.parent / path
    return path.resolve()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_candidate(
    config_path: Path,
    spec: TrendCardCandidateSpec,
) -> LoadedTrendCardCandidate:
    """Parse one card without applying the production reviewed-status gate."""

    path = _resolve_path(config_path, spec.path)
    artifact_sha256: str | None = None
    try:
        raw = path.read_bytes()
        # Hash exact source bytes.  Text-mode newline normalization on Windows
        # would otherwise make CRLF card hashes differ between load and report.
        artifact_sha256 = hashlib.sha256(raw).hexdigest()
        trend_card = TrendCard.model_validate_json(raw)
    except (OSError, UnicodeError, ValidationError) as error:
        return LoadedTrendCardCandidate(
            spec=spec,
            path=path,
            artifact_sha256=artifact_sha256,
            trend_card=None,
            load_error=f"{type(error).__name__}: {error}",
        )
    return LoadedTrendCardCandidate(
        spec=spec,
        path=path,
        artifact_sha256=artifact_sha256,
        trend_card=trend_card,
        load_error=None,
    )


def load_trend_card_qualification(
    config_path: Path,
) -> LoadedTrendCardQualification:
    """Load a qualification manifest while isolating candidate parse failures."""

    resolved_config = config_path.resolve()
    try:
        config = TrendCardQualificationConfig.model_validate(_read_json(resolved_config))
        dataset_path = _resolve_path(resolved_config, config.dataset_path)
        fixture_review_path = _resolve_path(resolved_config, config.fixture_review_path)
        cases = [MemeEvalCase.model_validate(item) for item in _read_json(dataset_path)]
        fixture_review = MemeFixtureReview.model_validate(_read_json(fixture_review_path))
    except (ValidationError, TypeError) as error:
        raise MemeExperimentDataError(
            f"Invalid TrendCard qualification manifest or fixture: {resolved_config}"
        ) from error

    if not cases:
        raise MemeExperimentDataError("TrendCard qualification cases must not be empty")
    if len({case.id for case in cases}) != len(cases):
        raise MemeExperimentDataError("TrendCard qualification case ids must be unique")

    # Cases are card-neutral in the qualification harness.  Existing fixtures
    # may still carry the legacy single-card id, which is replaced at runtime.
    for case in cases:
        try:
            AdCopyRequest.model_validate(
                {
                    **case.request,
                    "model": config.base_model,
                    "trend_card_id": None,
                }
            )
        except ValidationError as error:
            raise MemeExperimentDataError(
                f"Invalid TrendCard qualification case: {case.id}"
            ) from error

    candidates = [load_candidate(resolved_config, spec) for spec in config.cards]
    return LoadedTrendCardQualification(
        config_path=resolved_config,
        config=config,
        dataset_path=dataset_path,
        fixture_review_path=fixture_review_path,
        candidates=candidates,
        cases=cases,
        fixture_review=fixture_review,
    )


def request_for_card_case(
    loaded: LoadedTrendCardQualification,
    case: MemeEvalCase,
    candidate: LoadedTrendCardCandidate,
) -> AdCopyRequest:
    """Build a request whose card id is always the candidate currently under test."""

    if candidate.trend_card is None:
        raise MemeExperimentDataError(
            f"Candidate card is unavailable: {candidate.spec.id}"
        )
    return AdCopyRequest.model_validate(
        {
            **case.request,
            "model": loaded.config.base_model,
            "trend_card_id": candidate.trend_card.meme_id,
        }
    )


def card_case_eligibility(
    candidate: LoadedTrendCardCandidate,
    request: AdCopyRequest,
) -> CardCaseEligibility:
    """Run non-mutating production-relevant gates for one card/case pair."""

    card = candidate.trend_card
    reasons: list[str] = []
    if card is None:
        reasons.append("card_schema_invalid")
    else:
        if not card.supports("copy"):
            reasons.append("copy_asset_not_supported")
        if card.rights_risk.level == "high":
            reasons.append("rights_risk_high")
        if card.suitable_channels and request.channel.value not in card.suitable_channels:
            reasons.append("channel_not_supported")

        prohibited = [
            term.strip().casefold()
            for term in request.prohibited_terms
            if term.strip()
        ]
        if any(
            term in marker.casefold()
            for term in prohibited
            for marker in card.copy_markers
        ):
            reasons.append("copy_marker_conflicts_with_prohibited_term")

    return CardCaseEligibility(
        case_id="",
        channel=request.channel.value,
        eligible=not reasons,
        reasons=list(dict.fromkeys(reasons)),
    )


def eligibility_for_case(
    loaded: LoadedTrendCardQualification,
    candidate: LoadedTrendCardCandidate,
    case: MemeEvalCase,
) -> CardCaseEligibility:
    """Return eligibility with the case identity attached."""

    if candidate.trend_card is None:
        channel = str(case.request.get("channel") or "")
        return CardCaseEligibility(
            case_id=case.id,
            channel=channel,
            eligible=False,
            reasons=["card_schema_invalid"],
        )
    request = request_for_card_case(loaded, case, candidate)
    result = card_case_eligibility(candidate, request)
    return result.model_copy(update={"case_id": case.id})


def candidate_preflight(
    loaded: LoadedTrendCardQualification,
    candidate: LoadedTrendCardCandidate,
    cases: list[MemeEvalCase] | None = None,
) -> dict[str, Any]:
    """Create serializable card and per-case preflight evidence."""

    selected_cases = cases if cases is not None else loaded.cases
    eligibility = [
        eligibility_for_case(loaded, candidate, case) for case in selected_cases
    ]
    card = candidate.trend_card
    eligible_count = sum(item.eligible for item in eligibility)
    if not candidate.schema_valid:
        status = "invalid"
    elif eligible_count == 0:
        status = "no_eligible_cases"
    elif eligible_count < len(eligibility):
        status = "partially_eligible"
    else:
        status = "ready"
    return {
        "candidate_card_id": candidate.spec.id,
        "label": candidate.spec.label,
        "path": str(candidate.path),
        "artifact_sha256": candidate.artifact_sha256,
        "schema_valid": candidate.schema_valid,
        "load_error": candidate.load_error,
        "preflight_status": status,
        "trend_card_id": card.meme_id if card is not None else None,
        "display_name": card.display_name if card is not None else None,
        "curation_status": (
            card.curation_meta.status if card is not None else None
        ),
        "draft_evaluation_allowed": bool(
            card is not None and card.curation_meta.status != "reviewed"
        ),
        "rights_risk": card.rights_risk.level if card is not None else None,
        "suitable_channels": list(card.suitable_channels) if card is not None else [],
        "eligible_case_count": eligible_count,
        "skipped_case_count": len(eligibility) - eligible_count,
        "case_eligibility": [item.model_dump(mode="json") for item in eligibility],
    }


def build_card_messages(
    request: AdCopyRequest,
    candidate: LoadedTrendCardCandidate,
    *,
    supports_system_role: bool = True,
) -> list[dict[str, str]]:
    """Build the same production strategy for every card."""

    if candidate.trend_card is None:
        raise MemeExperimentDataError(
            f"Candidate card is unavailable: {candidate.spec.id}"
        )
    return build_arm_messages(
        request,
        candidate.trend_card,
        fixed_strategy_arm(),
        [],
        supports_system_role=supports_system_role,
    )


def resolve_fixed_generation_endpoint(
    config: TrendCardQualificationConfig,
):
    """Resolve the shared base endpoint using the existing registry logic."""

    return resolve_generation_endpoint(config, fixed_strategy_arm())  # type: ignore[arg-type]


def trial_generation_seed(base_seed: int, case_id: str, repeat: int) -> int:
    """Pair randomness across cards for a given case and repeat."""

    source = f"{base_seed}:{case_id}:{repeat}".encode()
    return int(hashlib.sha256(source).hexdigest()[:8], 16) % 2_147_483_648


def qualification_candidate_id(
    experiment_id: str,
    case_id: str,
    repeat: int,
    candidate_card_id: str,
    card_sha256: str | None,
) -> str:
    """Identify a generated candidate by the exact card artifact revision."""

    source = (
        f"{experiment_id}:{case_id}:{repeat}:{candidate_card_id}:"
        f"{card_sha256 or 'unavailable'}"
    ).encode()
    return f"candidate-{hashlib.sha256(source).hexdigest()[:12]}"


def build_work_items(
    loaded: LoadedTrendCardQualification,
    candidates: list[LoadedTrendCardCandidate],
    cases: list[MemeEvalCase],
    repeats: int,
) -> list[CardWorkItem]:
    """Build ``(case, card, repeat)`` work, omitting only ineligible pairs."""

    work: list[CardWorkItem] = []
    for case in cases:
        for repeat in range(1, repeats + 1):
            for candidate in candidates:
                if eligibility_for_case(loaded, candidate, case).eligible:
                    work.append(
                        CardWorkItem(
                            case=case,
                            candidate=candidate,
                            repeat=repeat,
                        )
                    )
    return work
