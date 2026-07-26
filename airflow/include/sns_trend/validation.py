from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_PROCESSED_DIR = (
    REPO_ROOT
    / "data"
    / "processed"
    / "sns_trend"
    / "v2"
    / "cross_platform_signal_top_candidates"
)
DEFAULT_JSON_NAME = "cross_platform_signal_top_candidates.json"
DEFAULT_CSV_NAME = "cross_platform_signal_top_candidates.csv"

REQUIRED_CSV_COLUMNS = {
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
}


class ProcessedValidationError(ValueError):
    """Raised when the sns_trend processed package is not safe to consume."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _read_json(path: Path) -> Any:
    if not path.exists():
        raise ProcessedValidationError(f"JSON payload not found: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ProcessedValidationError(f"JSON payload is not readable: {path}") from error


def _read_csv_rows(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    if not path.exists():
        raise ProcessedValidationError(f"CSV index not found: {path}")
    try:
        with path.open("r", encoding="utf-8", newline="") as file:
            reader = csv.DictReader(file)
            if reader.fieldnames is None:
                raise ProcessedValidationError(f"CSV header is missing: {path}")
            return list(reader), list(reader.fieldnames)
    except (OSError, UnicodeError, csv.Error) as error:
        raise ProcessedValidationError(f"CSV index is not readable: {path}") from error


def _as_dict(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ProcessedValidationError(f"{label} must be a JSON object")
    return value


def _split_pipe(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split("|") if item.strip()]


def _bool_string(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value).strip().casefold()


def _string(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def _card_sources(card: dict[str, Any]) -> list[str]:
    trend_meta = _as_dict(card.get("trend_meta", {}), "trend_meta")
    sources = trend_meta.get("sources", [])
    if not isinstance(sources, list):
        raise ProcessedValidationError(f"trend_meta.sources must be a list: {card.get('meme_id')}")
    return [_string(source) for source in sources if _string(source)]


def _card_identity(card: dict[str, Any]) -> dict[str, Any]:
    curation_meta = _as_dict(card.get("curation_meta", {}), "curation_meta")
    trend_meta = _as_dict(card.get("trend_meta", {}), "trend_meta")
    usable_assets = card.get("usable_assets", [])
    if not isinstance(usable_assets, list):
        raise ProcessedValidationError(f"usable_assets must be a list: {card.get('meme_id')}")

    return {
        "file_name": _string(card.get("_source_file")),
        "source_family": _string(card.get("_source_family")),
        "schema_version": _string(card.get("schema_version")),
        "meme_id": _string(card.get("meme_id")),
        "display_name": _string(card.get("display_name")),
        "core_asset": _string(card.get("core_asset")),
        "usable_assets": [_string(asset) for asset in usable_assets],
        "is_mock": _bool_string(card.get("is_mock")),
        "curation_mode": _string(curation_meta.get("mode")),
        "curation_status": _string(curation_meta.get("status")),
        "trend_status": _string(trend_meta.get("status")),
        "collected_week": _string(trend_meta.get("collected_week")),
        "sources": _card_sources(card),
    }


def _validate_payload(
    payload: Any,
    *,
    expected_card_count: int | None,
    expected_schema_version: str | None,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    payload_obj = _as_dict(payload, "processed payload")
    cards = payload_obj.get("cards")
    if not isinstance(cards, list):
        raise ProcessedValidationError("processed payload must contain cards list")
    if not cards:
        raise ProcessedValidationError("processed payload cards list is empty")
    if not all(isinstance(card, dict) for card in cards):
        raise ProcessedValidationError("all cards must be JSON objects")

    declared_count = payload_obj.get("card_count")
    if declared_count != len(cards):
        raise ProcessedValidationError(
            f"payload card_count={declared_count} does not match cards={len(cards)}"
        )
    if expected_card_count is not None and len(cards) != expected_card_count:
        raise ProcessedValidationError(
            f"expected {expected_card_count} cards, found {len(cards)}"
        )

    identities = [_card_identity(card) for card in cards]
    meme_ids = [identity["meme_id"] for identity in identities]
    missing_ids = [index for index, meme_id in enumerate(meme_ids) if not meme_id]
    if missing_ids:
        raise ProcessedValidationError(f"cards with missing meme_id: {missing_ids}")

    duplicate_ids = sorted(meme_id for meme_id, count in Counter(meme_ids).items() if count > 1)
    if duplicate_ids:
        raise ProcessedValidationError(f"duplicate meme_id values: {', '.join(duplicate_ids)}")

    schema_versions = Counter(identity["schema_version"] for identity in identities)
    if len(schema_versions) != 1:
        raise ProcessedValidationError(f"mixed schema_version values: {dict(schema_versions)}")
    if expected_schema_version and next(iter(schema_versions)) != expected_schema_version:
        raise ProcessedValidationError(
            f"expected schema_version={expected_schema_version}, "
            f"found {next(iter(schema_versions))}"
        )

    bad_curation = [
        identity["meme_id"]
        for identity in identities
        if identity["curation_status"] != "reviewed"
    ]
    if bad_curation:
        raise ProcessedValidationError(
            "cards must have curation_meta.status=reviewed: "
            f"{', '.join(bad_curation[:10])}"
        )

    bad_trend = [
        identity["meme_id"] for identity in identities if identity["trend_status"] != "active"
    ]
    if bad_trend:
        raise ProcessedValidationError(
            "cards must have trend_meta.status=active: "
            f"{', '.join(bad_trend[:10])}"
        )

    warnings: list[dict[str, Any]] = []
    mock_count = sum(1 for identity in identities if identity["is_mock"] == "true")
    if mock_count:
        warnings.append(
            {
                "code": "mock_cards",
                "message": "processed package contains mock TrendCards",
                "count": mock_count,
            }
        )

    week_counts = Counter(identity["collected_week"] for identity in identities)
    if len(week_counts) > 1:
        warnings.append(
            {
                "code": "mixed_collected_week",
                "message": "trend_meta.collected_week values are mixed",
                "counts": dict(sorted(week_counts.items())),
            }
        )

    return payload_obj, identities, warnings


def _validate_csv(
    rows: list[dict[str, str]],
    columns: list[str],
    identities: list[dict[str, Any]],
) -> dict[str, Any]:
    missing_columns = sorted(REQUIRED_CSV_COLUMNS.difference(columns))
    if missing_columns:
        raise ProcessedValidationError(
            "CSV index is missing required columns: " + ", ".join(missing_columns)
        )
    if len(rows) != len(identities):
        raise ProcessedValidationError(
            f"CSV row count={len(rows)} does not match JSON card count={len(identities)}"
        )

    rows_by_meme_id = {row.get("meme_id", ""): row for row in rows}
    if len(rows_by_meme_id) != len(rows):
        raise ProcessedValidationError("CSV index contains duplicate meme_id values")

    failures: list[str] = []
    for identity in identities:
        meme_id = identity["meme_id"]
        row = rows_by_meme_id.get(meme_id)
        if row is None:
            failures.append(f"{meme_id}: missing CSV row")
            continue

        scalar_checks = {
            "file_name": identity["file_name"],
            "source_family": identity["source_family"],
            "schema_version": identity["schema_version"],
            "display_name": identity["display_name"],
            "core_asset": identity["core_asset"],
            "curation_mode": identity["curation_mode"],
            "curation_status": identity["curation_status"],
            "trend_status": identity["trend_status"],
            "collected_week": identity["collected_week"],
        }
        for column, expected in scalar_checks.items():
            if _string(row.get(column)) != expected:
                failures.append(
                    f"{meme_id}: CSV {column}={row.get(column)!r} != JSON {expected!r}"
                )

        if _bool_string(row.get("is_mock")) != identity["is_mock"]:
            failures.append(
                f"{meme_id}: CSV is_mock={row.get('is_mock')!r} "
                f"!= JSON {identity['is_mock']!r}"
            )

        csv_assets = _split_pipe(row.get("usable_assets"))
        if csv_assets != identity["usable_assets"]:
            failures.append(
                f"{meme_id}: CSV usable_assets={csv_assets!r} "
                f"!= JSON {identity['usable_assets']!r}"
            )

        csv_sources = _split_pipe(row.get("sources"))
        json_sources = identity["sources"]
        if set(csv_sources) != set(json_sources):
            failures.append(
                f"{meme_id}: CSV sources={csv_sources!r} != JSON sources={json_sources!r}"
            )
        if _string(row.get("source_count")) != str(len(json_sources)):
            failures.append(
                f"{meme_id}: CSV source_count={row.get('source_count')!r} "
                f"!= JSON source count {len(json_sources)}"
            )

    if failures:
        preview = "; ".join(failures[:10])
        suffix = f"; ... {len(failures) - 10} more" if len(failures) > 10 else ""
        raise ProcessedValidationError(f"CSV/JSON consistency failures: {preview}{suffix}")

    return {
        "columns": columns,
        "row_count": len(rows),
        "required_columns": sorted(REQUIRED_CSV_COLUMNS),
    }


def smoke_test_api_loader(repo_root: Path, payload_path: Path) -> dict[str, Any]:
    api_root = repo_root / "apps" / "api"
    if not api_root.exists():
        raise ProcessedValidationError(f"FastAPI app root not found: {api_root}")

    # [Design Intent] Use the same loader as the API so the data gate verifies the
    # actual service contract, not just a parallel schema approximation.
    sys.path.insert(0, str(api_root))
    try:
        from app.modules.ad_copy.trend_context import load_trend_cards
    except Exception as error:  # pragma: no cover - depends on local environment
        raise ProcessedValidationError("FastAPI TrendCard loader cannot be imported") from error

    try:
        cards = load_trend_cards(path=payload_path)
    except Exception as error:  # pragma: no cover - delegated to API loader
        raise ProcessedValidationError("FastAPI TrendCard loader rejected payload") from error

    return {
        "status": "passed",
        "card_count": len(cards),
        "first_meme_id": cards[0].meme_id if cards else None,
    }


def check_dvc_processed_only(repo_root: Path, *, require_dvc: bool = False) -> dict[str, Any]:
    data_root = repo_root / "data"
    sns_trend_dvc_files = sorted(
        path.relative_to(repo_root).as_posix()
        for path in data_root.glob("**/*.dvc")
        if "sns_trend" in path.parts
    )
    invalid = [
        path
        for path in sns_trend_dvc_files
        if path.startswith("data/landing/sns_trend/")
        or path.startswith("data/curated/sns_trend/")
    ]
    processed = [
        path for path in sns_trend_dvc_files if path.startswith("data/processed/sns_trend/")
    ]

    if invalid:
        raise ProcessedValidationError(
            "DVC must not track sns_trend landing/curated paths: " + ", ".join(invalid)
        )
    if require_dvc and not processed:
        raise ProcessedValidationError("No sns_trend processed .dvc file found")

    status = "configured" if processed else "not_configured"
    return {
        "status": status,
        "sns_trend_dvc_files": sns_trend_dvc_files,
        "processed_dvc_files": processed,
    }


def validate_processed_package(
    *,
    repo_root: Path = REPO_ROOT,
    processed_dir: Path | None = None,
    json_path: Path | None = None,
    csv_path: Path | None = None,
    expected_card_count: int | None = 20,
    expected_schema_version: str | None = "2.0",
    api_loader_smoke: bool = False,
    dvc_check: bool = False,
    require_dvc: bool = False,
) -> dict[str, Any]:
    resolved_processed_dir = processed_dir or DEFAULT_PROCESSED_DIR
    resolved_json_path = json_path or resolved_processed_dir / DEFAULT_JSON_NAME
    resolved_csv_path = csv_path or resolved_processed_dir / DEFAULT_CSV_NAME

    payload = _read_json(resolved_json_path)
    payload_obj, identities, warnings = _validate_payload(
        payload,
        expected_card_count=expected_card_count,
        expected_schema_version=expected_schema_version,
    )
    csv_rows, csv_columns = _read_csv_rows(resolved_csv_path)
    csv_summary = _validate_csv(csv_rows, csv_columns, identities)

    schema_versions = Counter(identity["schema_version"] for identity in identities)
    source_families = Counter(identity["source_family"] for identity in identities)
    collected_weeks = Counter(identity["collected_week"] for identity in identities)

    summary: dict[str, Any] = {
        "dataset_name": payload_obj.get("dataset_name", "sns_trend"),
        "version": payload_obj.get("version"),
        "dataset_stage": payload_obj.get("dataset_stage"),
        "artifact_name": payload_obj.get("artifact_name"),
        "status": "passed",
        "processed_dir": str(resolved_processed_dir),
        "json_path": str(resolved_json_path),
        "csv_path": str(resolved_csv_path),
        "checksums": {
            "json": sha256_file(resolved_json_path),
            "csv": sha256_file(resolved_csv_path),
        },
        "card_count": len(identities),
        "csv": csv_summary,
        "schema_versions": dict(sorted(schema_versions.items())),
        "source_family_counts": dict(sorted(source_families.items())),
        "collected_week_counts": dict(sorted(collected_weeks.items())),
        "warnings": warnings,
    }

    if api_loader_smoke:
        summary["api_loader_smoke"] = smoke_test_api_loader(repo_root, resolved_json_path)
    if dvc_check or require_dvc:
        summary["dvc"] = check_dvc_processed_only(repo_root, require_dvc=require_dvc)

    return summary


def _parse_path(value: str | None) -> Path | None:
    return Path(value) if value else None


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate sns_trend processed package.")
    parser.add_argument("--repo-root", default=str(REPO_ROOT))
    parser.add_argument("--processed-dir", default=str(DEFAULT_PROCESSED_DIR))
    parser.add_argument("--json-path", default=None)
    parser.add_argument("--csv-path", default=None)
    parser.add_argument("--expected-card-count", type=int, default=20)
    parser.add_argument("--expected-schema-version", default="2.0")
    parser.add_argument("--api-loader-smoke", action="store_true")
    parser.add_argument("--dvc-check", action="store_true")
    parser.add_argument("--require-dvc", action="store_true")
    parser.add_argument("--summary-path", default=None)
    args = parser.parse_args()

    try:
        summary = validate_processed_package(
            repo_root=Path(args.repo_root),
            processed_dir=Path(args.processed_dir),
            json_path=_parse_path(args.json_path),
            csv_path=_parse_path(args.csv_path),
            expected_card_count=args.expected_card_count,
            expected_schema_version=args.expected_schema_version,
            api_loader_smoke=args.api_loader_smoke,
            dvc_check=args.dvc_check,
            require_dvc=args.require_dvc,
        )
    except Exception as error:
        failure = {
            "status": "failed",
            "error_type": type(error).__name__,
            "error_message": str(error),
        }
        print(json.dumps(failure, ensure_ascii=False, indent=2), file=sys.stderr)
        raise SystemExit(1) from error

    if args.summary_path:
        write_json(Path(args.summary_path), summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
