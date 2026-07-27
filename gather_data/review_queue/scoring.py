from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Any

from review_queue.contracts import CandidateRecord, make_candidate_id
from review_queue.normalization import (
    AliasIndex,
    GenericTermIndex,
    normalized_match_key,
    resolve_candidate_key,
)


class ScoringConfigError(ValueError):
    """Raised when review queue scoring config is invalid."""


@dataclass(frozen=True)
class ScoringConfig:
    scoring_config_version: str
    frequency_max_score: int
    recency_current_week: int
    recency_previous_week: int
    recency_older_week: int
    cross_platform_score: dict[int, int]
    source_reliability_score: dict[str, int]
    generic_term_penalty: int
    risk_penalty: int
    risk_terms: frozenset[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "scoring_config_version": self.scoring_config_version,
            "frequency_score": {"max_score": self.frequency_max_score},
            "recency_score": {
                "current_week": self.recency_current_week,
                "previous_week": self.recency_previous_week,
                "older_week": self.recency_older_week,
            },
            "cross_platform_score": {
                str(key): value for key, value in self.cross_platform_score.items()
            },
            "source_reliability_score": dict(self.source_reliability_score),
            "generic_term_penalty": self.generic_term_penalty,
            "risk_penalty": self.risk_penalty,
            "risk_terms": sorted(self.risk_terms),
        }


@dataclass(frozen=True)
class SourceSignal:
    source_family: str
    source_landing_run_id: str
    collected_week: str
    occurrence_count: int | None
    frequency_score: float
    evidence_urls: tuple[str, ...]
    source_path: str | None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["evidence_urls"] = list(self.evidence_urls)
        return payload


@dataclass(frozen=True)
class ScoredCandidate:
    candidate_id: str
    term: str
    display_term: str
    source_families: tuple[str, ...]
    source_count: int
    eligible_source_count: int
    usage_policy: str
    eligible_for_processed: bool
    requires_evidence: bool
    requires_risk_review: bool
    evidence_urls: tuple[str, ...]
    source_signals: tuple[SourceSignal, ...]
    score_breakdown: dict[str, float | int]
    total_score: float
    scoring_config_version: str

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["source_families"] = list(self.source_families)
        payload["evidence_urls"] = list(self.evidence_urls)
        payload["source_signals"] = [
            source_signal.to_dict() for source_signal in self.source_signals
        ]
        return payload


def load_scoring_config(path: Path) -> ScoringConfig:
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ScoringConfigError(f"scoring config must be a JSON object: {path}")

    return ScoringConfig(
        scoring_config_version=_required_string(payload, "scoring_config_version"),
        frequency_max_score=_nested_int(payload, "frequency_score", "max_score"),
        recency_current_week=_nested_int(payload, "recency_score", "current_week"),
        recency_previous_week=_nested_int(payload, "recency_score", "previous_week"),
        recency_older_week=_nested_int(payload, "recency_score", "older_week"),
        cross_platform_score=_cross_platform_score(payload),
        source_reliability_score=_source_reliability_score(payload),
        generic_term_penalty=_required_int(payload, "generic_term_penalty"),
        risk_penalty=_required_int(payload, "risk_penalty"),
        risk_terms=_risk_terms(payload),
    )


def score_candidates(
    records: list[CandidateRecord],
    *,
    current_week: str,
    aliases: AliasIndex | None,
    generic_terms: GenericTermIndex | None,
    scoring_config: ScoringConfig,
) -> list[ScoredCandidate]:
    source_frequency_scores = _source_frequency_scores(records, aliases, scoring_config)
    grouped_records = _group_records(records, aliases)
    scored = [
        _score_group(
            candidate_key,
            group_records,
            current_week=current_week,
            generic_terms=generic_terms,
            scoring_config=scoring_config,
            source_frequency_scores=source_frequency_scores,
        )
        for candidate_key, group_records in grouped_records.items()
    ]
    return sorted(
        scored,
        key=lambda candidate: (
            -candidate.total_score,
            candidate.term,
            candidate.candidate_id,
        ),
    )


def _score_group(
    candidate_key: str,
    group_records: list[CandidateRecord],
    *,
    current_week: str,
    generic_terms: GenericTermIndex | None,
    scoring_config: ScoringConfig,
    source_frequency_scores: dict[tuple[str, str], float],
) -> ScoredCandidate:
    ordered_records = sorted(
        group_records,
        key=lambda record: (
            _source_order(record.source_family),
            record.display_term,
            record.source_landing_run_id,
        ),
    )
    source_families = tuple(
        sorted({record.source_family for record in ordered_records}, key=_source_order)
    )
    eligible_sources = {
        record.source_family for record in ordered_records if record.eligible_for_processed
    }
    evidence_urls = tuple(
        sorted(
            {
                evidence_url
                for record in ordered_records
                for evidence_url in record.evidence_urls
            }
        )
    )
    source_signals = tuple(
        SourceSignal(
            source_family=record.source_family,
            source_landing_run_id=record.source_landing_run_id,
            collected_week=record.collected_week,
            occurrence_count=record.occurrence_count,
            frequency_score=source_frequency_scores.get(
                (record.source_family, candidate_key),
                0.0,
            ),
            evidence_urls=record.evidence_urls,
            source_path=record.source_path,
        )
        for record in ordered_records
    )

    frequency_score = max(
        (
            source_signal.frequency_score
            for source_signal in source_signals
            if _is_frequency_scoring_source(source_signal.source_family)
        ),
        default=0.0,
    )
    recency_score = max(
        _recency_score(record.collected_week, current_week, scoring_config)
        for record in ordered_records
    )
    cross_platform_score = scoring_config.cross_platform_score.get(
        min(len(source_families), max(scoring_config.cross_platform_score)),
        0,
    )
    source_reliability_score = sum(
        scoring_config.source_reliability_score.get(source_family, 0)
        for source_family in source_families
    )
    generic_term_penalty = (
        scoring_config.generic_term_penalty
        if generic_terms is not None and generic_terms.contains(candidate_key)
        else 0
    )
    requires_risk_review = _has_risk_term(candidate_key, scoring_config)
    risk_penalty = scoring_config.risk_penalty if requires_risk_review else 0
    total_score = (
        frequency_score
        + recency_score
        + cross_platform_score
        + source_reliability_score
        - generic_term_penalty
        - risk_penalty
    )

    return ScoredCandidate(
        candidate_id=make_candidate_id(candidate_key),
        term=candidate_key,
        display_term=_preferred_display_term(ordered_records),
        source_families=source_families,
        source_count=len(source_families),
        eligible_source_count=len(eligible_sources),
        usage_policy="candidate" if eligible_sources else "reference_only",
        eligible_for_processed=bool(eligible_sources),
        requires_evidence=not evidence_urls,
        requires_risk_review=requires_risk_review,
        evidence_urls=evidence_urls,
        source_signals=source_signals,
        score_breakdown={
            "frequency_score": frequency_score,
            "recency_score": recency_score,
            "cross_platform_score": cross_platform_score,
            "source_reliability_score": source_reliability_score,
            "generic_term_penalty": generic_term_penalty,
            "risk_penalty": risk_penalty,
        },
        total_score=round(total_score, 6),
        scoring_config_version=scoring_config.scoring_config_version,
    )


def _source_frequency_scores(
    records: list[CandidateRecord],
    aliases: AliasIndex | None,
    scoring_config: ScoringConfig,
) -> dict[tuple[str, str], float]:
    counts_by_source: dict[str, dict[str, int]] = {}
    for record in records:
        if record.occurrence_count is None:
            continue
        candidate_key = resolve_candidate_key(record.term, aliases)
        source_counts = counts_by_source.setdefault(record.source_family, {})
        source_counts[candidate_key] = max(
            source_counts.get(candidate_key, 0),
            record.occurrence_count,
        )

    scores: dict[tuple[str, str], float] = {}
    for source_family, source_counts in counts_by_source.items():
        sorted_counts = sorted(set(source_counts.values()))
        for candidate_key, count in source_counts.items():
            scores[(source_family, candidate_key)] = _rank_score(
                count,
                sorted_counts,
                scoring_config.frequency_max_score,
            )
    return scores


def _group_records(
    records: list[CandidateRecord],
    aliases: AliasIndex | None,
) -> dict[str, list[CandidateRecord]]:
    grouped: dict[str, list[CandidateRecord]] = {}
    for record in records:
        candidate_key = resolve_candidate_key(record.term, aliases)
        if not candidate_key:
            continue
        grouped.setdefault(candidate_key, []).append(record)
    return dict(sorted(grouped.items()))


def _rank_score(count: int, sorted_counts: list[int], max_score: int) -> float:
    if not sorted_counts:
        return 0.0
    if len(sorted_counts) == 1:
        return float(max_score)
    rank = sorted_counts.index(count)
    return round(max_score * rank / (len(sorted_counts) - 1), 6)


def _recency_score(
    collected_week: str,
    current_week: str,
    scoring_config: ScoringConfig,
) -> int:
    current = _iso_week_start(current_week)
    collected = _iso_week_start(collected_week)
    if current is None or collected is None:
        return scoring_config.recency_older_week
    week_delta = (current - collected).days // 7
    if week_delta == 0:
        return scoring_config.recency_current_week
    if week_delta == 1:
        return scoring_config.recency_previous_week
    return scoring_config.recency_older_week


def _iso_week_start(value: str) -> date | None:
    if "-W" not in value:
        return None
    year_text, week_text = value.split("-W", 1)
    try:
        return date.fromisocalendar(int(year_text), int(week_text), 1)
    except ValueError:
        return None


def _preferred_display_term(records: list[CandidateRecord]) -> str:
    for record in records:
        if record.eligible_for_processed:
            return record.display_term
    return records[0].display_term


def _has_risk_term(candidate_key: str, scoring_config: ScoringConfig) -> bool:
    normalized_candidate = normalized_match_key(candidate_key)
    return any(risk_term in normalized_candidate for risk_term in scoring_config.risk_terms)


def _is_frequency_scoring_source(source_family: str) -> bool:
    return source_family != "naver"


def _source_order(source_family: str) -> int:
    order = {
        "gogumafarm": 0,
        "careet": 1,
        "youtube": 2,
        "naver": 3,
    }
    return order.get(source_family, 99)


def _required_string(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ScoringConfigError(f"missing required string field: {key}")
    return value.strip()


def _required_int(payload: dict[str, Any], key: str) -> int:
    value = payload.get(key)
    if not isinstance(value, int) or value < 0:
        raise ScoringConfigError(f"missing non-negative int field: {key}")
    return value


def _nested_int(payload: dict[str, Any], section: str, key: str) -> int:
    value = payload.get(section)
    if not isinstance(value, dict):
        raise ScoringConfigError(f"missing config section: {section}")
    return _required_int(value, key)


def _cross_platform_score(payload: dict[str, Any]) -> dict[int, int]:
    value = payload.get("cross_platform_score")
    if not isinstance(value, dict) or not value:
        raise ScoringConfigError("cross_platform_score must be a non-empty object")
    scores: dict[int, int] = {}
    for raw_key, raw_score in value.items():
        try:
            key = int(raw_key)
        except (TypeError, ValueError) as exc:
            raise ScoringConfigError("cross_platform_score keys must be ints") from exc
        if key < 1 or not isinstance(raw_score, int) or raw_score < 0:
            raise ScoringConfigError("cross_platform_score values must be non-negative")
        scores[key] = raw_score
    return dict(sorted(scores.items()))


def _source_reliability_score(payload: dict[str, Any]) -> dict[str, int]:
    value = payload.get("source_reliability_score")
    if not isinstance(value, dict) or not value:
        raise ScoringConfigError("source_reliability_score must be a non-empty object")
    scores: dict[str, int] = {}
    for source_family, raw_score in value.items():
        if not isinstance(source_family, str) or not source_family.strip():
            raise ScoringConfigError("source_reliability_score keys must be strings")
        if not isinstance(raw_score, int) or raw_score < 0:
            raise ScoringConfigError("source_reliability_score values must be ints")
        scores[source_family.strip()] = raw_score
    return scores


def _risk_terms(payload: dict[str, Any]) -> frozenset[str]:
    value = payload.get("risk_terms", [])
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ScoringConfigError("risk_terms must be a string list")
    return frozenset(normalized_match_key(item) for item in value if normalized_match_key(item))
