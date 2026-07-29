#!/usr/bin/env python
"""Create a versioned daily keyword snapshot from YouTube videos."""

from __future__ import annotations

import argparse
import json
from datetime import date
from datetime import datetime
from datetime import timezone
import logging
from pathlib import Path
import re
from typing import Any, Iterable, Sequence

from youtube_trends.collector import (
    CollectionError,
    build_youtube_service,
    fetch_trending_videos,
    read_video_csv,
)
from youtube_trends.config import (
    DEFAULT_REGION_CODE,
    HISTORY_V2_DIR,
    REPO_ROOT,
    CollectionOptions,
    ConfigurationError,
    collection_options_from_env,
    configure_console,
    configure_logging,
    current_run_date,
    env_text,
    load_environment,
    parse_iso_week,
    parse_run_date,
    parse_run_id,
    require_api_key,
)
from youtube_trends.csv_io import DataFileError, atomic_write_csv
from youtube_trends.keywords import (
    DEFAULT_STOPWORDS,
    KeywordAnalysisError,
    build_keyword_snapshot,
    extract_keyword_occurrences,
)


REGION_CODE = DEFAULT_REGION_CODE
TOTAL_VIDEOS = 100
HISTORY_DIR = HISTORY_V2_DIR
STOPWORDS = DEFAULT_STOPWORDS
KEYWORD_FIELDS = ["keyword", "count"]
DEFAULT_CURATED_ROOT = REPO_ROOT / "data" / "curated" / "sns_trend"
DEFAULT_CURATED_VERSION = "v3"
RAW_FILENAME_PATTERN = re.compile(
    r"^youtube_trending_[A-Z]{2}_(\d{4})(\d{2})(\d{2})\.csv$"
)


def build_parser(defaults: CollectionOptions | None = None) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Create a keyword,count snapshot from a raw video CSV or the live API."
    )
    parser.add_argument(
        "--input-csv",
        type=Path,
        help="reuse a collector CSV instead of calling the API",
    )
    parser.add_argument("--region", default=defaults.region_code if defaults else None)
    parser.add_argument("--limit", type=int, default=defaults.total_videos if defaults else None)
    parser.add_argument("--page-size", type=int, default=defaults.page_size if defaults else None)
    parser.add_argument("--timeout", type=float, default=defaults.timeout if defaults else None)
    parser.add_argument("--retries", type=int, default=defaults.retries if defaults else None)
    parser.add_argument("--date", dest="run_date", help="snapshot date in YYYY-MM-DD format")
    parser.add_argument("--history-dir", type=Path, default=HISTORY_DIR)
    parser.add_argument("--output-file", type=Path, help="explicit output CSV path")
    parser.add_argument(
        "--tokenizer",
        choices=("regex", "okt"),
        default=None,
    )
    parser.add_argument(
        "--fail-if-exists",
        action="store_true",
        help="do not replace an existing output file",
    )
    parser.add_argument(
        "--week",
        help="ISO week in YYYY-Www format for curated sns_trend artifacts",
    )
    parser.add_argument(
        "--run-id",
        help="landing run id used as curated artifact provenance",
    )
    parser.add_argument(
        "--emit-curated-meme-card-candidates",
        action="store_true",
        help="write curated/sns_trend/vN/meme_card_candidates/youtube JSON",
    )
    parser.add_argument(
        "--curated-version",
        default=DEFAULT_CURATED_VERSION,
        help="curated sns_trend dataset version, e.g. v3",
    )
    parser.add_argument(
        "--curated-root",
        type=Path,
        default=DEFAULT_CURATED_ROOT,
        help="root directory for curated sns_trend artifacts",
    )
    parser.add_argument(
        "--log-level",
        choices=("DEBUG", "INFO", "WARNING", "ERROR"),
        default="INFO",
    )
    return parser


def _date_from_input(path: Path) -> date | None:
    match = RAW_FILENAME_PATTERN.fullmatch(path.name)
    if not match:
        return None
    try:
        return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except ValueError as exc:
        raise ConfigurationError(f"invalid date in input filename: {path.name}") from exc


def _same_path(left: Path, right: Path) -> bool:
    return left.resolve(strict=False) == right.resolve(strict=False)


def _limit_unique_videos(
    videos: Iterable[Any],
    limit: int,
) -> list[Any]:
    selected: list[Any] = []
    seen_ids: set[str] = set()
    for video in videos:
        video_id = str(video.video_id)
        if not video_id or video_id in seen_ids:
            continue
        seen_ids.add(video_id)
        selected.append(video)
        if len(selected) >= limit:
            break
    return selected


def _keyword_count_rows(rows: Iterable[dict[str, object]]) -> list[dict[str, object]]:
    keyword_rows = [
        {
            "keyword": str(row["display_keyword"]),
            "count": int(row["occurrence_count"]),
        }
        for row in rows
    ]
    keyword_rows.sort(key=lambda row: (-int(row["count"]), str(row["keyword"])))
    return keyword_rows


def _parse_dataset_version(value: str) -> str:
    normalized = value.strip().lower()
    if not re.fullmatch(r"v[1-9]\d*", normalized):
        raise ConfigurationError("curated-version must use vN format")
    return normalized


def _utc_now_z() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )


def curated_meme_card_candidates_path(
    *,
    week: str,
    version: str = DEFAULT_CURATED_VERSION,
    root: Path = DEFAULT_CURATED_ROOT,
) -> Path:
    return (
        root
        / version
        / "meme_card_candidates"
        / "youtube"
        / f"youtube_meme_card_candidates_{week}.json"
    )


def build_curated_meme_card_candidates_document(
    *,
    keyword_rows: Sequence[dict[str, object]],
    week: str,
    run_id: str,
    run_date: date,
    region: str,
    source_keyword_csv: Path,
    source_video_count: int,
    version: str = DEFAULT_CURATED_VERSION,
) -> dict[str, object]:
    # [Design Intent] Keep this artifact explicitly pre-review so it cannot be
    # mistaken for the official processed TrendCard payload.
    terms = [str(row["keyword"]) for row in keyword_rows]
    return {
        "schema_version": "1.0",
        "dataset_name": "sns_trend",
        "version": version,
        "stage": "curated",
        "artifact_name": "meme_card_candidates",
        "source_family": "youtube",
        "curation_status": "rule_filtered",
        "review_status": "pending",
        "promotion_requirement": "human_review_and_cross_platform_evidence",
        "auto_promote_to_processed": False,
        "collected_week": week,
        "run_date": run_date.isoformat(),
        "source_landing_run_id": run_id,
        "region": region,
        "source_keyword_csv": str(source_keyword_csv),
        "source_video_count": source_video_count,
        "term_count": len(terms),
        "terms": terms,
        "term_scores": [
            {"keyword": str(row["keyword"]), "count": int(row["count"])}
            for row in keyword_rows
        ],
        "created_at_utc": _utc_now_z(),
    }


def write_curated_meme_card_candidates(
    payload: dict[str, object],
    *,
    output_path: Path,
    overwrite: bool,
) -> Path:
    if output_path.exists() and not overwrite:
        raise DataFileError(f"curated output already exists: {output_path}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_suffix(output_path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(output_path)
    return output_path


def get_trending_videos(
    *,
    api_key: str | None = None,
    options: CollectionOptions | None = None,
    service: Any | None = None,
) -> list[dict[str, str]]:
    """Compatibility wrapper returning title and comma-joined tags."""
    load_environment()
    resolved = options or collection_options_from_env()
    youtube = service or build_youtube_service(
        api_key or require_api_key(), timeout=resolved.timeout
    )
    return [
        {"title": video.title, "tags": ",".join(video.tags)}
        for video in fetch_trending_videos(youtube, resolved)
    ]


def extract_keywords(texts: Iterable[object]) -> list[str]:
    """Compatibility wrapper using the deterministic regex tokenizer."""
    return extract_keyword_occurrences(texts, tokenizer_name="regex")


def main(argv: Sequence[str] | None = None) -> int:
    configure_console()
    parser = build_parser()
    args = parser.parse_args(argv)
    load_environment()
    configure_logging(args.log_level)

    try:
        tokenizer_name = args.tokenizer or env_text("YOUTUBE_TOKENIZER", "regex")
        if tokenizer_name not in {"regex", "okt"}:
            raise ConfigurationError("YOUTUBE_TOKENIZER must be 'regex' or 'okt'")
        inferred_date = _date_from_input(args.input_csv) if args.input_csv else None
        if args.input_csv and not args.run_date and inferred_date is None:
            raise ConfigurationError(
                "--date is required when the input filename has no YYYYMMDD date"
            )
        run_date = (
            parse_run_date(args.run_date)
            if args.run_date
            else inferred_date or current_run_date()
        )
        output = args.output_file or (
            args.history_dir / f"keywords_{run_date.isoformat()}.csv"
        )
        if args.input_csv and _same_path(args.input_csv, output):
            raise ConfigurationError("input CSV and output CSV must be different files")
        if args.fail_if_exists and output.exists():
            raise DataFileError(f"output already exists: {output}")

        if args.input_csv:
            if any(
                value is not None
                for value in (args.page_size, args.timeout, args.retries)
            ):
                raise ConfigurationError(
                    "--page-size, --timeout, and --retries apply only to live collection"
                )
            raw_snapshot = read_video_csv(args.input_csv)
            videos = list(raw_snapshot.videos)
            if args.limit is not None:
                if not 1 <= args.limit <= 500:
                    raise ConfigurationError("limit must be between 1 and 500")
                videos = _limit_unique_videos(videos, args.limit)
            if (
                raw_snapshot.region_code
                and args.region
                and raw_snapshot.region_code != args.region.upper()
            ):
                raise ConfigurationError(
                    "--region does not match the input CSV region_code"
                )
            region = raw_snapshot.region_code or args.region or env_text(
                "YOUTUBE_REGION_CODE", DEFAULT_REGION_CODE
            )
            region = region.strip().upper()
            if not re.fullmatch(r"[A-Z]{2}", region):
                raise ConfigurationError("region code must be two ASCII letters")
            provenance = (
                "collector_csv_v2"
                if raw_snapshot.schema_version == 2
                else "legacy_collector_csv"
            )
        else:
            options = collection_options_from_env(
                region_code=args.region,
                total_videos=args.limit,
                page_size=args.page_size,
                timeout=args.timeout,
                retries=args.retries,
            )
            service = build_youtube_service(require_api_key(), timeout=options.timeout)
            videos = fetch_trending_videos(service, options)
            region = options.region_code
            inferred_date = None
            provenance = "live_api"

        rows = build_keyword_snapshot(
            videos,
            snapshot_date=run_date,
            region=region,
            tokenizer_name=tokenizer_name,
            provenance=provenance,
        )
        keyword_rows = _keyword_count_rows(rows)
        atomic_write_csv(
            output,
            KEYWORD_FIELDS,
            keyword_rows,
            overwrite=not args.fail_if_exists,
        )
        curated_output: Path | None = None
        if args.emit_curated_meme_card_candidates:
            if not args.week or not args.run_id:
                raise ConfigurationError(
                    "--week and --run-id are required with "
                    "--emit-curated-meme-card-candidates"
                )
            week = parse_iso_week(args.week)
            run_id = parse_run_id(args.run_id)
            version = _parse_dataset_version(args.curated_version)
            curated_output = curated_meme_card_candidates_path(
                week=week,
                version=version,
                root=args.curated_root,
            )
            payload = build_curated_meme_card_candidates_document(
                keyword_rows=keyword_rows,
                week=week,
                run_id=run_id,
                run_date=run_date,
                region=region,
                source_keyword_csv=output,
                source_video_count=len({video.video_id for video in videos}),
                version=version,
            )
            write_curated_meme_card_candidates(
                payload,
                output_path=curated_output,
                overwrite=not args.fail_if_exists,
            )
    except ConfigurationError as exc:
        logging.error("configuration error: %s", exc)
        return 2
    except (CollectionError, DataFileError, KeywordAnalysisError, OSError) as exc:
        logging.error("keyword snapshot failed: %s", exc)
        return 1

    print(
        f"saved {len(rows)} keywords from {len({video.video_id for video in videos})} "
        f"videos to {output}"
    )
    if curated_output is not None:
        print(f"saved YouTube curated meme card candidates to {curated_output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
