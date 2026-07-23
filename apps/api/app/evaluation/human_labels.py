"""Validated human labels for calibrating the meme-copy judge."""

from __future__ import annotations

import csv
import json
import re
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)


HumanScore = Annotated[int, Field(strict=True, ge=1, le=5)]
AcceptableDecision = Literal["yes", "no"]
Sha256Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]

RUBRIC_VERSION = "meme-human-rubric-v1"

SCORE_FIELDS = (
    "naturalness",
    "pattern_fidelity",
    "product_relevance",
    "factuality",
    "channel_readiness",
)
CSV_COLUMNS = (
    "schema_version",
    "rubric_version",
    "output_id",
    "output_sha256",
    "trial_id",
    "card_id",
    "card_sha256",
    "case_id",
    "rater_id",
    *SCORE_FIELDS,
    "acceptable",
    "comment",
)


class HumanLabelDataError(ValueError):
    """Raised when a human-label artifact cannot be read or validated."""


class HumanEvaluationLabel(BaseModel):
    """One independent rater's assessment of one generated output."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    output_id: str = Field(min_length=1, max_length=200)
    output_sha256: Sha256Digest
    trial_id: str = Field(min_length=1, max_length=200)
    card_id: str = Field(min_length=1, max_length=200)
    card_sha256: Sha256Digest
    case_id: str = Field(min_length=1, max_length=200)
    rater_id: str = Field(min_length=1, max_length=200)
    naturalness: HumanScore
    pattern_fidelity: HumanScore
    product_relevance: HumanScore
    factuality: HumanScore
    channel_readiness: HumanScore
    acceptable: AcceptableDecision
    comment: str | None = Field(default=None, max_length=2000)

    @field_validator("comment", mode="before")
    @classmethod
    def normalize_optional_comment(cls, value: object) -> object:
        if isinstance(value, str):
            stripped = value.strip()
            return stripped or None
        return value


class HumanEvaluationLabelSet(BaseModel):
    """A versioned collection that can contain multiple independent raters."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"]
    rubric_version: Literal["meme-human-rubric-v1"]
    labels: list[HumanEvaluationLabel] = Field(min_length=1, max_length=100_000)

    @model_validator(mode="after")
    def validate_rating_identities(self) -> "HumanEvaluationLabelSet":
        seen_ratings: set[tuple[str, str]] = set()
        output_identities: dict[str, tuple[str, str, str, str, str]] = {}
        card_hashes: dict[str, str] = {}

        for label in self.labels:
            rating_key = (label.output_id, label.rater_id)
            if rating_key in seen_ratings:
                raise ValueError(
                    "Duplicate human rating for output_id/rater_id: "
                    f"{label.output_id}/{label.rater_id}"
                )
            seen_ratings.add(rating_key)

            identity = (
                label.trial_id,
                label.card_id,
                label.case_id,
                label.output_sha256,
                label.card_sha256,
            )
            previous = output_identities.setdefault(label.output_id, identity)
            if previous != identity:
                raise ValueError(
                    "Ratings for one output_id must use the same trial_id, card_id, "
                    "case_id, output_sha256, and card_sha256: "
                    f"{label.output_id}"
                )

            previous_card_hash = card_hashes.setdefault(label.card_id, label.card_sha256)
            if previous_card_hash != label.card_sha256:
                raise ValueError(
                    "Ratings for one card_id must use the same card_sha256: "
                    f"{label.card_id}"
                )

        return self


def _read_json_payload(path: Path) -> Any:
    with path.open("r", encoding="utf-8-sig") as file:
        return json.load(file)


def _csv_score(value: object) -> object:
    """Convert CSV integer text while leaving malformed placeholders invalid."""

    if isinstance(value, str):
        stripped = value.strip()
        if re.fullmatch(r"[0-9]+", stripped):
            return int(stripped)
    return value


def _read_csv_payload(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        fieldnames = reader.fieldnames
        if fieldnames is None:
            raise HumanLabelDataError(f"Human-label CSV has no header: {path}")
        if len(fieldnames) != len(set(fieldnames)):
            raise HumanLabelDataError(f"Human-label CSV has duplicate columns: {path}")

        missing = sorted(set(CSV_COLUMNS) - set(fieldnames))
        unexpected = sorted(set(fieldnames) - set(CSV_COLUMNS))
        if missing or unexpected:
            details = []
            if missing:
                details.append(f"missing={','.join(missing)}")
            if unexpected:
                details.append(f"unexpected={','.join(unexpected)}")
            raise HumanLabelDataError(
                f"Human-label CSV columns do not match the schema ({'; '.join(details)}): "
                f"{path}"
            )

        labels: list[dict[str, Any]] = []
        versions: set[str] = set()
        rubric_versions: set[str] = set()
        for row in reader:
            version = (row.pop("schema_version", None) or "").strip()
            rubric_version = (row.pop("rubric_version", None) or "").strip()
            versions.add(version)
            rubric_versions.add(rubric_version)
            for field in SCORE_FIELDS:
                row[field] = _csv_score(row.get(field))
            labels.append(row)

    if len(versions) != 1:
        raise HumanLabelDataError(
            f"Human-label CSV must contain exactly one schema_version: {path}"
        )
    if len(rubric_versions) != 1:
        raise HumanLabelDataError(
            f"Human-label CSV must contain exactly one rubric_version: {path}"
        )
    return {
        "schema_version": versions.pop(),
        "rubric_version": rubric_versions.pop(),
        "labels": labels,
    }


def load_human_evaluation_labels(path: str | Path) -> HumanEvaluationLabelSet:
    """Load and validate one JSON or CSV human-calibration label artifact."""

    resolved = Path(path).resolve()
    try:
        if resolved.suffix.casefold() == ".json":
            payload = _read_json_payload(resolved)
        elif resolved.suffix.casefold() == ".csv":
            payload = _read_csv_payload(resolved)
        else:
            raise HumanLabelDataError(
                f"Human-label files must use a .json or .csv extension: {resolved}"
            )
        return HumanEvaluationLabelSet.model_validate(payload)
    except HumanLabelDataError:
        raise
    except (OSError, UnicodeError, csv.Error, json.JSONDecodeError, ValidationError) as error:
        raise HumanLabelDataError(
            f"Human-label file is not readable or valid: {resolved}: {error}"
        ) from error
