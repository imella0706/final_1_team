from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any


# [Design Intent] Airflow DAG와 검증 로직을 분리해 로컬 테스트와 Airflow 실행이 같은 코드를 쓰게 한다.
REQUIRED_COLUMNS = {
    "id",
    "collected_at",
    "published_at",
    "keyword",
    "trend_term",
    "text",
    "url",
    "engagement_count",
}

TEXT_MAX_LENGTH = 500
NULL_TEXT_RATE_MAX = 0.0
DUPLICATE_ID_RATE_MAX = 0.0
DUPLICATE_URL_RATE_MAX = 0.2


class CsvValidationError(ValueError):
    pass


def resolve_week(default: str | None = None) -> str:
    if default:
        return default
    year, week, _ = datetime.now().isocalendar()
    return f"{year}-W{week:02d}"


def build_paths(base_dir: str | Path, week: str | None = None) -> dict[str, Path]:
    target_week = resolve_week(week)
    root = Path(base_dir)
    return {
        "week": target_week,
        "input": root
        / "data"
        / "landing"
        / "processed"
        / "sns_meme_trend"
        / f"week={target_week}"
        / f"trend_meme_{target_week}.csv",
        "summary": root
        / "logs"
        / "data_pipeline"
        / "airflow"
        / "dag_id=brandmate_weekly_meme_csv_validation"
        / f"week={target_week}"
        / "validation_summary.json",
        "error": root
        / "logs"
        / "data_pipeline"
        / "airflow"
        / "dag_id=brandmate_weekly_meme_csv_validation"
        / f"week={target_week}"
        / "error.json",
    }


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def read_csv_rows(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    if not path.exists():
        raise CsvValidationError(f"CSV file not found: {path}")

    with path.open("r", encoding="utf-8", newline="") as file:
        reader = csv.DictReader(file)
        if reader.fieldnames is None:
            raise CsvValidationError("CSV header is missing")
        rows = list(reader)
        return rows, list(reader.fieldnames)


def validate_schema(columns: list[str]) -> dict[str, Any]:
    missing = sorted(REQUIRED_COLUMNS.difference(columns))
    extra = sorted(set(columns).difference(REQUIRED_COLUMNS))
    if missing:
        raise CsvValidationError(f"missing required columns: {', '.join(missing)}")
    return {
        "required_columns": sorted(REQUIRED_COLUMNS),
        "columns": columns,
        "extra_columns": extra,
    }


def _blank(value: str | None) -> bool:
    return value is None or value.strip() == ""


def _duplicate_rate(values: list[str]) -> float:
    normalized = [value.strip() for value in values if not _blank(value)]
    if not normalized:
        return 0.0
    return round((len(normalized) - len(set(normalized))) / len(normalized), 6)


def validate_quality(rows: list[dict[str, str]]) -> dict[str, Any]:
    row_count = len(rows)
    if row_count == 0:
        raise CsvValidationError("CSV has no data rows")

    null_text_count = sum(1 for row in rows if _blank(row.get("text")))
    long_text_count = sum(1 for row in rows if len((row.get("text") or "").strip()) > TEXT_MAX_LENGTH)
    duplicate_id_rate = _duplicate_rate([row.get("id", "") for row in rows])
    duplicate_url_rate = _duplicate_rate([row.get("url", "") for row in rows])
    null_text_rate = round(null_text_count / row_count, 6)

    failures: list[str] = []
    if null_text_rate > NULL_TEXT_RATE_MAX:
        failures.append(f"null_text_rate={null_text_rate} exceeds {NULL_TEXT_RATE_MAX}")
    if duplicate_id_rate > DUPLICATE_ID_RATE_MAX:
        failures.append(f"duplicate_id_rate={duplicate_id_rate} exceeds {DUPLICATE_ID_RATE_MAX}")
    if duplicate_url_rate > DUPLICATE_URL_RATE_MAX:
        failures.append(f"duplicate_url_rate={duplicate_url_rate} exceeds {DUPLICATE_URL_RATE_MAX}")
    if long_text_count > 0:
        failures.append(f"{long_text_count} text values exceed max length {TEXT_MAX_LENGTH}")

    if failures:
        raise CsvValidationError("; ".join(failures))

    return {
        "row_count": row_count,
        "null_text_rate": null_text_rate,
        "duplicate_id_rate": duplicate_id_rate,
        "duplicate_url_rate": duplicate_url_rate,
        "long_text_count": long_text_count,
    }


def validate_weekly_csv(base_dir: str | Path, week: str | None = None) -> dict[str, Any]:
    paths = build_paths(base_dir, week)
    input_path = paths["input"]
    rows, columns = read_csv_rows(input_path)
    schema = validate_schema(columns)
    quality = validate_quality(rows)

    return {
        "dataset": "sns_meme_trend",
        "period_type": "weekly",
        "period": paths["week"],
        "status": "passed",
        "input_path": str(input_path),
        "checksum": sha256_file(input_path),
        "schema": schema,
        **quality,
    }


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def run_validation(base_dir: str | Path, week: str | None = None) -> dict[str, Any]:
    paths = build_paths(base_dir, week)
    try:
        summary = validate_weekly_csv(base_dir, week)
        write_json(paths["summary"], summary)
        if paths["error"].exists():
            paths["error"].unlink()
        return summary
    except Exception as exc:
        error = {
            "dataset": "sns_meme_trend",
            "period_type": "weekly",
            "period": paths["week"],
            "status": "failed",
            "input_path": str(paths["input"]),
            "error_type": type(exc).__name__,
            "error_message": str(exc),
        }
        write_json(paths["error"], error)
        raise
