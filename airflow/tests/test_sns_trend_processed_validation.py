from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from sns_trend.validation import (
    ProcessedValidationError,
    check_dvc_processed_only,
    validate_processed_package,
)


def _card(**overrides: object) -> dict[str, object]:
    card: dict[str, object] = {
        "schema_version": "2.0",
        "meme_id": "manual:test-card",
        "display_name": "테스트 카드",
        "core_asset": "text",
        "usable_assets": ["copy"],
        "is_mock": True,
        "curation_meta": {"mode": "manual", "status": "reviewed"},
        "trend_meta": {
            "status": "active",
            "collected_week": "2026-W30",
            "sources": ["manual"],
        },
        "_source_file": "manual_test-card.json",
        "_source_family": "manual",
    }
    card.update(overrides)
    return card


def _write_package(root: Path, *, card: dict[str, object] | None = None) -> Path:
    processed_dir = root / "data" / "processed" / "sns_trend" / "v2" / "cross"
    processed_dir.mkdir(parents=True)
    active_card = card or _card()
    payload = {
        "dataset_name": "sns_trend",
        "version": "v2",
        "dataset_stage": "processed",
        "artifact_name": "cross_platform_signal_top_candidates",
        "card_count": 1,
        "cards": [active_card],
    }
    (processed_dir / "cross_platform_signal_top_candidates.json").write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )

    with (processed_dir / "cross_platform_signal_top_candidates.csv").open(
        "w",
        encoding="utf-8",
        newline="",
    ) as file:
        writer = csv.DictWriter(
            file,
            fieldnames=[
                "file_name",
                "source_family",
                "schema_version",
                "meme_id",
                "display_name",
                "core_asset",
                "usable_assets",
                "is_mock",
                "curation_mode",
                "curation_status",
                "trend_status",
                "collected_week",
                "source_count",
                "sources",
            ],
        )
        writer.writeheader()
        writer.writerow(
            {
                "file_name": active_card["_source_file"],
                "source_family": active_card["_source_family"],
                "schema_version": active_card["schema_version"],
                "meme_id": active_card["meme_id"],
                "display_name": active_card["display_name"],
                "core_asset": active_card["core_asset"],
                "usable_assets": "copy",
                "is_mock": "True",
                "curation_mode": "manual",
                "curation_status": "reviewed",
                "trend_status": "active",
                "collected_week": "2026-W30",
                "source_count": "1",
                "sources": "manual",
            }
        )
    return processed_dir


def test_validate_processed_package_passes_for_matching_json_and_csv(tmp_path: Path) -> None:
    processed_dir = _write_package(tmp_path)

    summary = validate_processed_package(
        repo_root=tmp_path,
        processed_dir=processed_dir,
        expected_card_count=1,
        api_loader_smoke=False,
        dvc_check=True,
    )

    assert summary["status"] == "passed"
    assert summary["card_count"] == 1
    assert summary["csv"]["row_count"] == 1
    assert summary["dvc"]["status"] == "not_configured"
    assert summary["warnings"][0]["code"] == "mock_cards"


def test_validate_processed_package_rejects_csv_json_identity_mismatch(
    tmp_path: Path,
) -> None:
    processed_dir = _write_package(tmp_path, card=_card(display_name="JSON 이름"))
    csv_path = processed_dir / "cross_platform_signal_top_candidates.csv"
    csv_text = csv_path.read_text(encoding="utf-8").replace("JSON 이름", "CSV 이름")
    csv_path.write_text(csv_text, encoding="utf-8")

    with pytest.raises(ProcessedValidationError, match="display_name"):
        validate_processed_package(
            repo_root=tmp_path,
            processed_dir=processed_dir,
            expected_card_count=1,
        )


def test_check_dvc_processed_only_rejects_landing_dvc(tmp_path: Path) -> None:
    landing_dvc = tmp_path / "data" / "landing" / "sns_trend" / "week=2026-W30" / "raw.dvc"
    landing_dvc.parent.mkdir(parents=True)
    landing_dvc.write_text("outs: []\n", encoding="utf-8")

    with pytest.raises(ProcessedValidationError, match="landing/curated"):
        check_dvc_processed_only(tmp_path)
