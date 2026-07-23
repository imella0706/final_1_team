from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from app.evaluation.human_labels import (
    CSV_COLUMNS,
    HumanLabelDataError,
    load_human_evaluation_labels,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _label(**overrides: object) -> dict[str, object]:
    label: dict[str, object] = {
        "output_id": "output-001",
        "output_sha256": "a" * 64,
        "trial_id": "trial-001",
        "card_id": "card-001",
        "card_sha256": "b" * 64,
        "case_id": "case-001",
        "rater_id": "rater-a",
        "naturalness": 4,
        "pattern_fidelity": 5,
        "product_relevance": 4,
        "factuality": 5,
        "channel_readiness": 4,
        "acceptable": "yes",
        "comment": None,
    }
    label.update(overrides)
    return label


def _write_json(path: Path, labels: list[dict[str, object]]) -> None:
    path.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "rubric_version": "meme-human-rubric-v1",
                "labels": labels,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def test_load_json_supports_independent_raters_for_one_output(tmp_path: Path) -> None:
    path = tmp_path / "labels.json"
    _write_json(
        path,
        [
            _label(rater_id="rater-a", comment="  자연스럽습니다.  "),
            _label(rater_id="rater-b", naturalness=3, acceptable="no", comment=""),
        ],
    )

    loaded = load_human_evaluation_labels(path)

    assert [label.rater_id for label in loaded.labels] == ["rater-a", "rater-b"]
    assert loaded.labels[0].comment == "자연스럽습니다."
    assert loaded.labels[1].comment is None


def test_load_csv_parses_scores_and_optional_comment(tmp_path: Path) -> None:
    path = tmp_path / "labels.csv"
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerow(
            {
                "schema_version": "1.0",
                "rubric_version": "meme-human-rubric-v1",
                **_label(comment=""),
            }
        )
        writer.writerow(
            {
                "schema_version": "1.0",
                "rubric_version": "meme-human-rubric-v1",
                **_label(output_id="output-002", trial_id="trial-002", rater_id="rater-b"),
            }
        )

    loaded = load_human_evaluation_labels(path)

    assert loaded.labels[0].naturalness == 4
    assert loaded.labels[0].comment is None
    assert loaded.labels[1].output_id == "output-002"


@pytest.mark.parametrize(
    ("overrides", "error_text"),
    [
        ({"naturalness": 0}, "greater than or equal to 1"),
        ({"channel_readiness": 6}, "less than or equal to 5"),
        ({"acceptable": "maybe"}, "Input should be 'yes' or 'no'"),
    ],
)
def test_loader_rejects_invalid_scores_and_decisions(
    tmp_path: Path,
    overrides: dict[str, object],
    error_text: str,
) -> None:
    path = tmp_path / "invalid.json"
    _write_json(path, [_label(**overrides)])

    with pytest.raises(HumanLabelDataError, match=error_text):
        load_human_evaluation_labels(path)


def test_loader_rejects_duplicate_rating_by_same_rater(tmp_path: Path) -> None:
    path = tmp_path / "duplicate.json"
    _write_json(path, [_label(), _label()])

    with pytest.raises(HumanLabelDataError, match="Duplicate human rating"):
        load_human_evaluation_labels(path)


def test_loader_rejects_conflicting_identity_for_one_output(tmp_path: Path) -> None:
    path = tmp_path / "conflict.json"
    _write_json(path, [_label(), _label(rater_id="rater-b", card_id="card-002")])

    with pytest.raises(HumanLabelDataError, match="must use the same trial_id"):
        load_human_evaluation_labels(path)


def test_loader_rejects_invalid_artifact_hash(tmp_path: Path) -> None:
    path = tmp_path / "bad-hash.json"
    _write_json(path, [_label(output_sha256="not-a-sha256")])

    with pytest.raises(HumanLabelDataError, match="String should match pattern"):
        load_human_evaluation_labels(path)


def test_loader_rejects_unknown_rubric_version(tmp_path: Path) -> None:
    path = tmp_path / "wrong-rubric.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "rubric_version": "meme-human-rubric-v2",
                "labels": [_label()],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(HumanLabelDataError, match="meme-human-rubric-v1"):
        load_human_evaluation_labels(path)


def test_loader_rejects_conflicting_hash_for_one_card(tmp_path: Path) -> None:
    path = tmp_path / "card-hash-conflict.json"
    _write_json(
        path,
        [
            _label(),
            _label(
                output_id="output-002",
                output_sha256="c" * 64,
                trial_id="trial-002",
                rater_id="rater-b",
                card_sha256="d" * 64,
            ),
        ],
    )

    with pytest.raises(HumanLabelDataError, match="same card_sha256"):
        load_human_evaluation_labels(path)


@pytest.mark.parametrize(
    "template_name",
    ["human_labels.template.json", "human_labels.template.csv"],
)
def test_blank_templates_cannot_be_loaded_as_completed_labels(template_name: str) -> None:
    template_path = PROJECT_ROOT / "evals" / template_name

    with pytest.raises(HumanLabelDataError):
        load_human_evaluation_labels(template_path)
