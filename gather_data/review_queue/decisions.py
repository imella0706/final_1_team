from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from review_queue.contracts import (
    DecisionValidationError,
    ReviewDecisionError,
    ReviewDecisionRecord,
)


def validate_review_decisions(
    decisions: list[ReviewDecisionRecord],
    queue_candidates: list[dict[str, Any]],
) -> dict[str, Any]:

    candidate_map: dict[str, dict[str, Any]] = {}
    for item in queue_candidates:
        if isinstance(item, dict) and "candidate_id" in item:
            candidate_map[item["candidate_id"]] = item

    accepted_candidate_ids: list[str] = []
    accepted_count = 0
    rejected_count = 0
    held_count = 0

    seen_decision_ids: set[str] = set()

    for decision in decisions:
        cand_id = decision.candidate_id

        if cand_id in seen_decision_ids:
            raise DecisionValidationError(f"duplicate decision for candidate_id: {cand_id}")
        seen_decision_ids.add(cand_id)

        if cand_id not in candidate_map:
            raise DecisionValidationError(
                f"candidate_id '{cand_id}' does not exist in the review queue"
            )

        cand_info = candidate_map[cand_id]
        usage_policy = cand_info.get("usage_policy", "")
        eligible = cand_info.get("eligible_for_processed", True)

        if decision.review_decision == "accept":
            if not eligible or usage_policy == "reference_only":
                raise DecisionValidationError(
                    f"candidate_id '{cand_id}' is reference-only/ineligible for processed "
                    "and cannot be accepted"
                )
            accepted_count += 1
            accepted_candidate_ids.append(cand_id)
        elif decision.review_decision == "reject":
            rejected_count += 1
        elif decision.review_decision == "hold":
            held_count += 1

    return {
        "total_decisions": len(decisions),
        "accepted_count": accepted_count,
        "rejected_count": rejected_count,
        "held_count": held_count,
        "accepted_candidate_ids": accepted_candidate_ids,
        "eligible_accepted_count": len(accepted_candidate_ids),
    }


def save_review_decisions(
    decisions: list[ReviewDecisionRecord],
    json_path: Path,
    csv_path: Path | None = None,
) -> dict[str, str]:

    json_path = Path(json_path)
    json_path.parent.mkdir(parents=True, exist_ok=True)

    records_data = [d.to_dict() for d in decisions]

    temp_json = json_path.with_suffix(".tmp")
    with temp_json.open("w", encoding="utf-8") as f:
        json.dump({"decisions": records_data, "decision_count": len(decisions)}, f, indent=2, ensure_ascii=False)
    temp_json.replace(json_path)

    if csv_path is not None:
        csv_path = Path(csv_path)
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        fieldnames = [
            "candidate_id",
            "review_decision",
            "reviewer",
            "reviewed_at",
            "review_note",
            "override_reason",
            "display_name_override",
            "risk_review_notes",
            "decision_source",
        ]
        temp_csv = csv_path.with_suffix(".tmp")
        with temp_csv.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for record in records_data:
                writer.writerow(record)
        temp_csv.replace(csv_path)

    return {
        "json_path": str(json_path),
        "csv_path": str(csv_path) if csv_path else "",
    }


def load_review_decisions(json_path: Path) -> list[ReviewDecisionRecord]:
    json_path = Path(json_path)
    if not json_path.exists():
        raise ReviewDecisionError(f"review decision file does not exist: {json_path}")

    with json_path.open("r", encoding="utf-8") as f:
        payload = json.load(f)

    if not isinstance(payload, dict) or "decisions" not in payload:
        raise ReviewDecisionError(f"invalid review decision JSON structure: {json_path}")

    raw_decisions = payload["decisions"]
    if not isinstance(raw_decisions, list):
        raise ReviewDecisionError("decisions field must be a list")

    return [ReviewDecisionRecord.from_dict(item) for item in raw_decisions]


def validate_decisions_json_csv_consistency(json_path: Path, csv_path: Path) -> bool:
    decisions_json = load_review_decisions(json_path)

    csv_path = Path(csv_path)
    if not csv_path.exists():
        raise ReviewDecisionError(f"review decision CSV file does not exist: {csv_path}")

    decisions_csv: list[dict[str, str]] = []
    with csv_path.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            decisions_csv.append(row)

    if len(decisions_json) != len(decisions_csv):
        raise DecisionValidationError(
            f"count mismatch between JSON ({len(decisions_json)}) and CSV ({len(decisions_csv)})"
        )

    for index, (item_json, item_csv) in enumerate(zip(decisions_json, decisions_csv)):
        if item_json.candidate_id != item_csv.get("candidate_id"):
            raise DecisionValidationError(
                f"candidate_id mismatch at index {index}: json='{item_json.candidate_id}', csv='{item_csv.get('candidate_id')}'"
            )
        if item_json.review_decision != item_csv.get("review_decision"):
            raise DecisionValidationError(
                f"review_decision mismatch at index {index}: json='{item_json.review_decision}', csv='{item_csv.get('review_decision')}'"
            )

    return True
