from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from review_queue.contracts import CandidateRecord, load_candidate_records
from review_queue.normalization import load_alias_index, load_generic_term_index
from review_queue.scoring import ScoredCandidate, load_scoring_config, score_candidates


DEFAULT_DATASET_NAME = "sns_trend"
DEFAULT_VERSION = "v3"
DEFAULT_ARTIFACT_NAME = "review_queue"
DEFAULT_SOURCE_ARTIFACT_NAME = "meme_card_candidates"
DEFAULT_CONFIG_DIR = Path(__file__).resolve().parent / "config"
CSV_COLUMNS = (
    "rank",
    "candidate_id",
    "term",
    "display_term",
    "source_families",
    "source_count",
    "eligible_source_count",
    "usage_policy",
    "eligible_for_processed",
    "requires_evidence",
    "requires_risk_review",
    "total_score",
    "frequency_score",
    "recency_score",
    "cross_platform_score",
    "source_reliability_score",
    "generic_term_penalty",
    "risk_penalty",
    "evidence_urls",
    "source_landing_run_ids",
    "source_paths",
    "scoring_config_version",
)


class ReviewQueueBuildError(ValueError):
    """Raised when the review queue cannot be built deterministically."""


@dataclass(frozen=True)
class ReviewQueueBuildResult:
    output_dir: Path
    queue_json_path: Path
    queue_csv_path: Path
    scoring_config_snapshot_path: Path
    summary_path: Path
    candidate_count: int
    queue_json_sha256: str
    queue_csv_sha256: str


def discover_candidate_paths(input_root: Path, week: str) -> list[Path]:
    if not input_root.exists():
        raise ReviewQueueBuildError(f"candidate input root does not exist: {input_root}")

    paths = sorted(input_root.glob(f"*/*_meme_card_candidates_{week}.json"))
    if not paths:
        raise ReviewQueueBuildError(
            f"no candidate artifacts found for week={week}: {input_root}"
        )
    return paths


def build_review_queue(
    *,
    week: str,
    run_id: str,
    candidate_paths: Sequence[Path],
    output_root: Path,
    alias_config_path: Path,
    generic_terms_config_path: Path,
    scoring_config_path: Path,
    overwrite: bool = False,
) -> ReviewQueueBuildResult:
    if not week.strip():
        raise ReviewQueueBuildError("week is required")
    if not run_id.strip():
        raise ReviewQueueBuildError("run_id is required")
    if not candidate_paths:
        raise ReviewQueueBuildError("at least one candidate artifact is required")

    normalized_candidate_paths = [path.resolve() for path in candidate_paths]
    _assert_paths_exist(normalized_candidate_paths)

    output_dir = output_root / f"week={week}" / f"run_id={run_id}"
    _prepare_output_dir(output_dir, overwrite=overwrite)

    aliases = load_alias_index(alias_config_path)
    generic_terms = load_generic_term_index(generic_terms_config_path)
    scoring_config = load_scoring_config(scoring_config_path)
    records = load_candidate_records(list(normalized_candidate_paths))
    scored_candidates = score_candidates(
        records,
        current_week=week,
        aliases=aliases,
        generic_terms=generic_terms,
        scoring_config=scoring_config,
    )

    queue_json_path = output_dir / "sns_trend_review_queue.json"
    queue_csv_path = output_dir / "sns_trend_review_queue.csv"
    scoring_config_snapshot_path = output_dir / "scoring_config_snapshot.json"
    summary_path = output_dir / "review_queue_summary.json"

    queue_payload = _queue_payload(
        week=week,
        run_id=run_id,
        candidate_paths=normalized_candidate_paths,
        scored_candidates=scored_candidates,
        scoring_config_version=scoring_config.scoring_config_version,
    )
    _write_json(queue_json_path, queue_payload)
    _write_csv(queue_csv_path, scored_candidates)
    _write_json(scoring_config_snapshot_path, scoring_config.to_dict())

    queue_json_sha256 = _sha256_file(queue_json_path)
    queue_csv_sha256 = _sha256_file(queue_csv_path)
    scoring_config_snapshot_sha256 = _sha256_file(scoring_config_snapshot_path)
    _write_json(
        summary_path,
        _summary_payload(
            week=week,
            run_id=run_id,
            records=records,
            scored_candidates=scored_candidates,
            candidate_paths=normalized_candidate_paths,
            queue_json_path=queue_json_path,
            queue_csv_path=queue_csv_path,
            scoring_config_snapshot_path=scoring_config_snapshot_path,
            queue_json_sha256=queue_json_sha256,
            queue_csv_sha256=queue_csv_sha256,
            scoring_config_snapshot_sha256=scoring_config_snapshot_sha256,
        ),
    )

    return ReviewQueueBuildResult(
        output_dir=output_dir,
        queue_json_path=queue_json_path,
        queue_csv_path=queue_csv_path,
        scoring_config_snapshot_path=scoring_config_snapshot_path,
        summary_path=summary_path,
        candidate_count=len(scored_candidates),
        queue_json_sha256=queue_json_sha256,
        queue_csv_sha256=queue_csv_sha256,
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    candidate_paths = (
        [Path(path) for path in args.candidate_path]
        if args.candidate_path
        else discover_candidate_paths(Path(args.input_root), args.week)
    )
    result = build_review_queue(
        week=args.week,
        run_id=args.run_id,
        candidate_paths=candidate_paths,
        output_root=Path(args.output_root),
        alias_config_path=Path(args.alias_config),
        generic_terms_config_path=Path(args.generic_terms_config),
        scoring_config_path=Path(args.scoring_config),
        overwrite=args.overwrite,
    )
    print(f"review_queue_dir={result.output_dir}")
    print(f"candidate_count={result.candidate_count}")
    print(f"queue_json_sha256={result.queue_json_sha256}")
    print(f"queue_csv_sha256={result.queue_csv_sha256}")
    return 0


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build deterministic sns_trend review queue JSON/CSV artifacts.",
    )
    parser.add_argument("--week", required=True, help="Asia/Seoul ISO week, e.g. 2026-W31")
    parser.add_argument("--run-id", required=True, help="Immutable review queue run id")
    parser.add_argument(
        "--input-root",
        default="data/curated/sns_trend/v3/meme_card_candidates",
        help="Root containing source-family meme_card_candidates artifacts",
    )
    parser.add_argument(
        "--candidate-path",
        action="append",
        default=[],
        help="Explicit candidate artifact path. May be repeated.",
    )
    parser.add_argument(
        "--output-root",
        default="data/curated/sns_trend/v3/review_queue",
        help="Review queue output root",
    )
    parser.add_argument(
        "--alias-config",
        default=str(DEFAULT_CONFIG_DIR / "aliases.json"),
        help="Explicit alias config path",
    )
    parser.add_argument(
        "--generic-terms-config",
        default=str(DEFAULT_CONFIG_DIR / "generic_terms.json"),
        help="Generic term penalty config path",
    )
    parser.add_argument(
        "--scoring-config",
        default=str(DEFAULT_CONFIG_DIR / "scoring_v1.json"),
        help="Versioned scoring config path",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite an existing run output directory. Off by default.",
    )
    return parser.parse_args(argv)


def _queue_payload(
    *,
    week: str,
    run_id: str,
    candidate_paths: Sequence[Path],
    scored_candidates: Sequence[ScoredCandidate],
    scoring_config_version: str,
) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "dataset_name": DEFAULT_DATASET_NAME,
        "version": DEFAULT_VERSION,
        "stage": "curated",
        "artifact_name": DEFAULT_ARTIFACT_NAME,
        "source_artifact_name": DEFAULT_SOURCE_ARTIFACT_NAME,
        "collected_week": week,
        "run_id": run_id,
        "review_status": "pending",
        "decision_artifact_policy": "review_decisions are stored separately",
        "candidate_count": len(scored_candidates),
        "scoring_config_version": scoring_config_version,
        "input_paths": [path.as_posix() for path in candidate_paths],
        "candidates": [
            _candidate_payload(rank, candidate)
            for rank, candidate in enumerate(scored_candidates, start=1)
        ],
    }


def _candidate_payload(rank: int, candidate: ScoredCandidate) -> dict[str, Any]:
    payload = candidate.to_dict()
    payload["rank"] = rank
    return payload


def _write_csv(path: Path, scored_candidates: Sequence[ScoredCandidate]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for rank, candidate in enumerate(scored_candidates, start=1):
            writer.writerow(_candidate_csv_row(rank, candidate))


def _candidate_csv_row(rank: int, candidate: ScoredCandidate) -> dict[str, Any]:
    breakdown = candidate.score_breakdown
    source_landing_run_ids = sorted(
        {source.source_landing_run_id for source in candidate.source_signals}
    )
    source_paths = sorted(
        {source.source_path for source in candidate.source_signals if source.source_path}
    )
    return {
        "rank": rank,
        "candidate_id": candidate.candidate_id,
        "term": candidate.term,
        "display_term": candidate.display_term,
        "source_families": "|".join(candidate.source_families),
        "source_count": candidate.source_count,
        "eligible_source_count": candidate.eligible_source_count,
        "usage_policy": candidate.usage_policy,
        "eligible_for_processed": str(candidate.eligible_for_processed).lower(),
        "requires_evidence": str(candidate.requires_evidence).lower(),
        "requires_risk_review": str(candidate.requires_risk_review).lower(),
        "total_score": _format_score(candidate.total_score),
        "frequency_score": _format_score(breakdown["frequency_score"]),
        "recency_score": _format_score(breakdown["recency_score"]),
        "cross_platform_score": _format_score(breakdown["cross_platform_score"]),
        "source_reliability_score": _format_score(
            breakdown["source_reliability_score"]
        ),
        "generic_term_penalty": _format_score(breakdown["generic_term_penalty"]),
        "risk_penalty": _format_score(breakdown["risk_penalty"]),
        "evidence_urls": "|".join(candidate.evidence_urls),
        "source_landing_run_ids": "|".join(source_landing_run_ids),
        "source_paths": "|".join(source_paths),
        "scoring_config_version": candidate.scoring_config_version,
    }


def _summary_payload(
    *,
    week: str,
    run_id: str,
    records: Sequence[CandidateRecord],
    scored_candidates: Sequence[ScoredCandidate],
    candidate_paths: Sequence[Path],
    queue_json_path: Path,
    queue_csv_path: Path,
    scoring_config_snapshot_path: Path,
    queue_json_sha256: str,
    queue_csv_sha256: str,
    scoring_config_snapshot_sha256: str,
) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "dataset_name": DEFAULT_DATASET_NAME,
        "version": DEFAULT_VERSION,
        "stage": "curated",
        "artifact_name": "review_queue_summary",
        "collected_week": week,
        "run_id": run_id,
        "source_record_count": len(records),
        "candidate_count": len(scored_candidates),
        "candidate_count_by_usage_policy": _count_by(
            candidate.usage_policy for candidate in scored_candidates
        ),
        "candidate_count_by_source_family": _source_family_counts(scored_candidates),
        "eligible_candidate_count": sum(
            1 for candidate in scored_candidates if candidate.eligible_for_processed
        ),
        "reference_only_candidate_count": sum(
            1
            for candidate in scored_candidates
            if candidate.usage_policy == "reference_only"
        ),
        "requires_evidence_count": sum(
            1 for candidate in scored_candidates if candidate.requires_evidence
        ),
        "requires_risk_review_count": sum(
            1 for candidate in scored_candidates if candidate.requires_risk_review
        ),
        "top_candidate_ids": [
            candidate.candidate_id for candidate in scored_candidates[:20]
        ],
        "input_paths": [path.as_posix() for path in candidate_paths],
        "artifacts": {
            "queue_json": queue_json_path.name,
            "queue_json_sha256": queue_json_sha256,
            "queue_csv": queue_csv_path.name,
            "queue_csv_sha256": queue_csv_sha256,
            "scoring_config_snapshot": scoring_config_snapshot_path.name,
            "scoring_config_snapshot_sha256": scoring_config_snapshot_sha256,
        },
    }


def _source_family_counts(
    scored_candidates: Sequence[ScoredCandidate],
) -> dict[str, int]:
    counts: dict[str, int] = {}
    for candidate in scored_candidates:
        for source_family in candidate.source_families:
            counts[source_family] = counts.get(source_family, 0) + 1
    return dict(sorted(counts.items()))


def _count_by(values: Sequence[str] | Any) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    return dict(sorted(counts.items()))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _format_score(value: float | int) -> str:
    if isinstance(value, int):
        return str(value)
    return f"{value:.6f}".rstrip("0").rstrip(".")


def _assert_paths_exist(paths: Sequence[Path]) -> None:
    missing = [path for path in paths if not path.exists()]
    if missing:
        raise ReviewQueueBuildError(
            "candidate artifact does not exist: "
            + ", ".join(path.as_posix() for path in missing)
        )


def _prepare_output_dir(path: Path, *, overwrite: bool) -> None:
    if path.exists():
        if not overwrite:
            raise ReviewQueueBuildError(f"review queue output already exists: {path}")
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=False)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ReviewQueueBuildError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
