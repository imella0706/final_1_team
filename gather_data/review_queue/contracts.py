from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


SUPPORTED_SOURCES = {"youtube", "gogumafarm", "careet", "naver"}
ELIGIBLE_PROCESSED_SOURCES = {"youtube", "gogumafarm", "careet"}


class CandidateContractError(ValueError):
    """Raised when a source candidate artifact breaks the review queue contract."""


@dataclass(frozen=True)
class CandidateRecord:
    candidate_id: str
    term: str
    display_term: str
    source_family: str
    source_landing_run_id: str
    collected_week: str
    occurrence_count: int | None
    evidence_urls: tuple[str, ...]
    usage_policy: str
    eligible_for_processed: bool
    requires_evidence: bool
    source_path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["evidence_urls"] = list(self.evidence_urls)
        return payload


def canonicalize_term(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value or "")
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


def make_candidate_id(term: str) -> str:
    canonical = canonicalize_term(term).casefold()
    if not canonical:
        raise CandidateContractError("candidate term is empty after normalization")
    digest = hashlib.sha1(canonical.encode("utf-8")).hexdigest()[:12]
    return f"cand_{digest}"


def load_candidate_payload(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise CandidateContractError(f"candidate payload must be an object: {path}")
    return payload


def records_from_candidate_payload(
    payload: dict[str, Any],
    *,
    source_path: Path | None = None,
) -> list[CandidateRecord]:
    source_family = _require_string(payload, "source_family")
    if source_family not in SUPPORTED_SOURCES:
        raise CandidateContractError(f"unsupported source_family: {source_family}")

    terms = _require_string_list(payload, "terms")
    display_terms = _optional_string_list(payload, "display_terms")
    collected_week = _require_string(payload, "collected_week")
    source_landing_run_id = _require_string(payload, "source_landing_run_id")
    count_by_term = _term_score_count_map(payload)
    usage_policy = _usage_policy_for_source(payload, source_family)
    eligible_for_processed = (
        source_family in ELIGIBLE_PROCESSED_SOURCES and usage_policy != "reference_only"
    )
    source_path_value = str(source_path) if source_path is not None else None

    records: list[CandidateRecord] = []
    seen_terms: set[str] = set()
    for index, raw_term in enumerate(terms):
        term = canonicalize_term(raw_term)
        if not term:
            continue
        term_key = term.casefold()
        if term_key in seen_terms:
            continue
        seen_terms.add(term_key)

        display_term = _display_term_for_index(display_terms, index, term)
        evidence_urls = _evidence_urls_for_term(payload, term)
        records.append(
            CandidateRecord(
                candidate_id=make_candidate_id(term),
                term=term,
                display_term=display_term,
                source_family=source_family,
                source_landing_run_id=source_landing_run_id,
                collected_week=collected_week,
                occurrence_count=count_by_term.get(term_key),
                evidence_urls=tuple(evidence_urls),
                usage_policy=usage_policy,
                eligible_for_processed=eligible_for_processed,
                requires_evidence=not evidence_urls,
                source_path=source_path_value,
            )
        )

    if not records:
        raise CandidateContractError(
            f"candidate payload has no usable terms: {source_family}"
        )
    return records


def load_candidate_records(paths: list[Path]) -> list[CandidateRecord]:
    records: list[CandidateRecord] = []
    for path in paths:
        payload = load_candidate_payload(path)
        records.extend(records_from_candidate_payload(payload, source_path=path))
    return records


def _require_string(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise CandidateContractError(f"missing required string field: {key}")
    return value.strip()


def _require_string_list(payload: dict[str, Any], key: str) -> list[str]:
    value = payload.get(key)
    if not isinstance(value, list) or not value:
        raise CandidateContractError(f"missing required list field: {key}")
    if not all(isinstance(item, str) for item in value):
        raise CandidateContractError(f"field must contain only strings: {key}")
    return value


def _optional_string_list(payload: dict[str, Any], key: str) -> list[str]:
    value = payload.get(key, [])
    if value is None:
        return []
    if not isinstance(value, list):
        raise CandidateContractError(f"field must be a list when present: {key}")
    if not all(isinstance(item, str) for item in value):
        raise CandidateContractError(f"field must contain only strings: {key}")
    return value


def _term_score_count_map(payload: dict[str, Any]) -> dict[str, int]:
    value = payload.get("term_scores", [])
    if value is None:
        return {}
    if not isinstance(value, list):
        raise CandidateContractError("term_scores must be a list when present")

    count_by_term: dict[str, int] = {}
    for item in value:
        if not isinstance(item, dict):
            raise CandidateContractError("term_scores entries must be objects")
        keyword = item.get("keyword")
        count = item.get("count")
        if not isinstance(keyword, str) or not keyword.strip():
            raise CandidateContractError("term_scores keyword must be a string")
        if not isinstance(count, int) or count < 0:
            raise CandidateContractError("term_scores count must be a non-negative int")
        count_by_term[canonicalize_term(keyword).casefold()] = count
    return count_by_term


def _usage_policy_for_source(payload: dict[str, Any], source_family: str) -> str:
    if source_family == "naver":
        return "reference_only"
    value = payload.get("usage_policy", "candidate")
    if not isinstance(value, str) or not value.strip():
        raise CandidateContractError("usage_policy must be a non-empty string")
    return value.strip()


def _display_term_for_index(
    display_terms: list[str],
    index: int,
    fallback_term: str,
) -> str:
    if index >= len(display_terms):
        return fallback_term
    display_term = canonicalize_term(display_terms[index])
    return display_term or fallback_term


def _evidence_urls_for_term(payload: dict[str, Any], term: str) -> list[str]:
    evidence = payload.get("evidence_urls_by_term", {})
    if evidence is None:
        return []
    if not isinstance(evidence, dict):
        raise CandidateContractError("evidence_urls_by_term must be an object")
    urls = evidence.get(term) or evidence.get(term.casefold()) or []
    if not isinstance(urls, list):
        raise CandidateContractError("evidence URL entry must be a list")
    if not all(isinstance(item, str) for item in urls):
        raise CandidateContractError("evidence URLs must be strings")
    return [url for url in urls if url.strip()]
