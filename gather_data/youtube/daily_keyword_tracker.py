#!/usr/bin/env python
"""Create a versioned daily keyword snapshot from YouTube videos."""

from __future__ import annotations

import argparse
from datetime import date
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
    CollectionOptions,
    ConfigurationError,
    collection_options_from_env,
    configure_console,
    configure_logging,
    current_run_date,
    env_text,
    load_environment,
    parse_run_date,
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
        atomic_write_csv(
            output,
            KEYWORD_FIELDS,
            _keyword_count_rows(rows),
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
