from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from review_queue.contracts import (
    ReviewDecisionRecord,
)
from review_queue.decisions import load_review_decisions

DEFAULT_DATASET_NAME = "sns_trend"
DEFAULT_VERSION = "v3"
DEFAULT_ARTIFACT_NAME = "trendcard_drafts"
CURATED_ROOT = Path(__file__).resolve().parents[2] / "data" / "curated" / "sns_trend" / "v3"
QUEUE_ROOT = CURATED_ROOT / "review_queue"
DECISIONS_ROOT = CURATED_ROOT / "review_decisions"
DRAFTS_ROOT = CURATED_ROOT / "trendcard_drafts"

CSV_COLUMNS = (
    "meme_id",
    "name",
    "search_keywords",
    "collected_week",
    "status",
    "reviewer",
    "reviewed_at",
    "has_risk",
    "meaning",
    "usage_rules",
    "prohibited_usage",
)


class TrendCardDraftBuildError(ValueError):
    """Raised when trendcard drafts cannot be built from review decisions."""


@dataclass(frozen=True)
class TrendCardDraftBuildResult:
    output_dir: Path
    drafts_json_path: Path
    drafts_csv_path: Path
    summary_path: Path
    draft_count: int
    drafts_json_sha256: str
    drafts_csv_sha256: str


def build_trendcard_drafts(
    *,
    week: str,
    run_id: str,
    decisions_path: Path,
    queue_path: Path,
    output_dir: Path,
    overwrite: bool = False,
) -> TrendCardDraftBuildResult:
    decisions_path = Path(decisions_path)
    queue_path = Path(queue_path)
    output_dir = Path(output_dir)

    if not decisions_path.exists():
        raise TrendCardDraftBuildError(f"review decisions file does not exist: {decisions_path}")
    if not queue_path.exists():
        raise TrendCardDraftBuildError(f"review queue file does not exist: {queue_path}")

    _prepare_output_dir(output_dir, overwrite=overwrite)

    decisions = load_review_decisions(decisions_path)

    with queue_path.open("r", encoding="utf-8") as f:
        queue_payload = json.load(f)

    raw_candidates = queue_payload.get("candidates", [])
    cand_map: dict[str, dict[str, Any]] = {
        c["candidate_id"]: c for c in raw_candidates if isinstance(c, dict) and "candidate_id" in c
    }

    # Filter accepted decisions
    accepted_decisions = [d for d in decisions if d.review_decision == "accept"]
    if not accepted_decisions:
        raise TrendCardDraftBuildError(
            f"no 'accept' decisions found in {decisions_path}. Cannot build empty draft package."
        )

    drafts: list[dict[str, Any]] = []
    skipped_ineligible_count = 0

    for dec in accepted_decisions:
        cand_id = dec.candidate_id
        if cand_id not in cand_map:
            raise TrendCardDraftBuildError(
                f"accepted candidate_id '{cand_id}' not found in queue file {queue_path}"
            )

        cand_info = cand_map[cand_id]

        # Promotion Gate Verification
        eligible = cand_info.get("eligible_for_processed", True)
        usage_policy = cand_info.get("usage_policy", "candidate")

        if not eligible or usage_policy == "reference_only":
            skipped_ineligible_count += 1
            continue

        draft_item = _convert_to_trendcard_draft(cand_info, dec, week)
        drafts.append(draft_item)

    if not drafts:
        raise TrendCardDraftBuildError(
            f"all accepted decisions ({len(accepted_decisions)}) were ineligible for processed release."
        )

    drafts_json_path = output_dir / "sns_trend_trendcard_drafts.json"
    drafts_csv_path = output_dir / "sns_trend_trendcard_drafts.csv"
    summary_path = output_dir / "trendcard_draft_summary.json"

    # Save JSON
    json_payload = {
        "artifact_name": DEFAULT_ARTIFACT_NAME,
        "week": week,
        "run_id": run_id,
        "draft_count": len(drafts),
        "created_at": datetime_utc_now_iso(),
        "drafts": drafts,
    }
    json_bytes = json.dumps(json_payload, indent=2, ensure_ascii=False).encode("utf-8")
    drafts_json_path.write_bytes(json_bytes)
    json_hash = hashlib.sha256(json_bytes).hexdigest()

    # Save CSV
    csv_bytes = _write_drafts_csv(drafts, drafts_csv_path)
    csv_hash = hashlib.sha256(csv_bytes).hexdigest()

    # Save Summary
    summary_payload = {
        "artifact_name": DEFAULT_ARTIFACT_NAME,
        "week": week,
        "run_id": run_id,
        "created_at": datetime_utc_now_iso(),
        "accepted_decision_count": len(accepted_decisions),
        "draft_count": len(drafts),
        "skipped_ineligible_count": skipped_ineligible_count,
        "drafts_json_path": str(drafts_json_path),
        "drafts_csv_path": str(drafts_csv_path),
        "drafts_json_sha256": json_hash,
        "drafts_csv_sha256": csv_hash,
    }
    summary_path.write_text(json.dumps(summary_payload, indent=2, ensure_ascii=False), encoding="utf-8")

    return TrendCardDraftBuildResult(
        output_dir=output_dir,
        drafts_json_path=drafts_json_path,
        drafts_csv_path=drafts_csv_path,
        summary_path=summary_path,
        draft_count=len(drafts),
        drafts_json_sha256=json_hash,
        drafts_csv_sha256=csv_hash,
    )


def _convert_to_trendcard_draft(
    cand_info: dict[str, Any],
    dec: ReviewDecisionRecord,
    week: str,
) -> dict[str, Any]:
    candidate_id = cand_info["candidate_id"]
    display_term = dec.display_name_override or cand_info.get("display_term") or cand_info.get("term", "")
    term = cand_info.get("term", display_term)

    meaning_text = dec.review_note if dec.review_note.strip() else "[DRAFT] 사람 검수필요: 해당 밈의 발생 배경과 의미 작성"
    risk_notes = dec.risk_review_notes or cand_info.get("risk_review_notes") or ""
    has_risk = bool(cand_info.get("requires_risk_review", False) or risk_notes)

    return {
        "meme_id": candidate_id,
        "name": display_term,
        "search_keywords": [display_term, term] if display_term != term else [term],
        "meaning": meaning_text,
        "text_patterns": ["[DRAFT] 문구 패턴 템플릿 작성"],
        "copy_markers": ["[DRAFT] 핵심 키워드 마커 작성"],
        "usage_rules": ["[DRAFT] 추천 사용 상황 작성"],
        "prohibited_usage": ["[DRAFT] 금지 사용 상황 작성"],
        "rights_risk": {
            "has_risk": has_risk,
            "risk_type": "brand_or_copyright" if has_risk else "none",
            "description": risk_notes if risk_notes else "[DRAFT] 저작권/상표권 리스크 검토 결과",
        },
        "trend_meta": {
            "collected_week": week,
            "status": "active",
            "is_mock": False,
            "curation_meta": {
                "status": "reviewed",
                "reviewer": dec.reviewer,
                "reviewed_at": dec.reviewed_at,
                "decision_source": dec.decision_source,
            },
        },
    }


def _write_drafts_csv(drafts: list[dict[str, Any]], csv_path: Path) -> bytes:
    rows = []
    for d in drafts:
        row = {
            "meme_id": d["meme_id"],
            "name": d["name"],
            "search_keywords": ", ".join(d["search_keywords"]),
            "collected_week": d["trend_meta"]["collected_week"],
            "status": d["trend_meta"]["status"],
            "reviewer": d["trend_meta"]["curation_meta"]["reviewer"],
            "reviewed_at": d["trend_meta"]["curation_meta"]["reviewed_at"],
            "has_risk": str(d["rights_risk"]["has_risk"]),
            "meaning": d["meaning"],
            "usage_rules": ", ".join(d["usage_rules"]),
            "prohibited_usage": ", ".join(d["prohibited_usage"]),
        }
        rows.append(row)

    temp_csv = csv_path.with_suffix(".tmp")
    with temp_csv.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for r in rows:
            writer.writerow(r)

    csv_bytes = temp_csv.read_bytes()
    temp_csv.replace(csv_path)
    return csv_bytes


def _prepare_output_dir(output_dir: Path, overwrite: bool) -> None:
    if output_dir.exists():
        if not overwrite:
            raise TrendCardDraftBuildError(
                f"output directory already exists: {output_dir}. Use --overwrite to replace it."
            )
    else:
        output_dir.mkdir(parents=True, exist_ok=True)


def datetime_utc_now_iso() -> str:
    import datetime

    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build TrendCard Drafts from accepted Review Decisions & Review Queue"
    )
    parser.add_argument("--week", required=True, help="ISO week (e.g. 2026-W31)")
    parser.add_argument("--run-id", required=True, help="Airflow or CLI run ID")
    parser.add_argument("--decisions-path", help="Explicit path to review_decisions.json")
    parser.add_argument("--queue-path", help="Explicit path to sns_trend_review_queue.json")
    parser.add_argument("--output-dir", help="Explicit output directory")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite output directory if exists")
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)

    week = args.week
    run_id = args.run_id

    decisions_path = (
        Path(args.decisions_path)
        if args.decisions_path
        else DECISIONS_ROOT / f"week={week}" / "sns_trend_review_decisions.json"
    )
    queue_path = (
        Path(args.queue_path)
        if args.queue_path
        else QUEUE_ROOT / f"week={week}" / f"run_id={run_id}" / "sns_trend_review_queue.json"
    )
    output_dir = (
        Path(args.output_dir)
        if args.output_dir
        else DRAFTS_ROOT / f"week={week}" / f"run_id={run_id}"
    )

    try:
        result = build_trendcard_drafts(
            week=week,
            run_id=run_id,
            decisions_path=decisions_path,
            queue_path=queue_path,
            output_dir=output_dir,
            overwrite=args.overwrite,
        )
        print(f"Successfully built {result.draft_count} TrendCard drafts:")
        print(f"  JSON: {result.drafts_json_path} (sha256={result.drafts_json_sha256[:8]}...)")
        print(f"  CSV:  {result.drafts_csv_path} (sha256={result.drafts_csv_sha256[:8]}...)")
        print(f"  Summary: {result.summary_path}")
    except Exception as e:
        print(f"ERROR building trendcard drafts: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
