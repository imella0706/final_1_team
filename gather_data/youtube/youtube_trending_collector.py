#!/usr/bin/env python
"""Collect a raw YouTube most-popular snapshot for one region."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import logging
from pathlib import Path
from typing import Any, Sequence

from youtube_trends.collector import (
    LEGACY_VIDEO_FIELDS,
    CollectionError,
    VideoRecord,
    build_youtube_service,
    fetch_trending_videos,
    write_video_csv,
)
from youtube_trends.config import (
    DEFAULT_PAGE_SIZE,
    DEFAULT_REGION_CODE,
    DEFAULT_RETRIES,
    DEFAULT_TIMEOUT,
    DEFAULT_TOTAL_VIDEOS,
    RAW_DATA_DIR,
    CollectionOptions,
    ConfigurationError,
    collection_options_from_env,
    configure_console,
    configure_logging,
    current_run_date,
    landing_run_directory,
    load_environment,
    parse_iso_week,
    parse_run_id,
    parse_run_date,
    require_api_key,
)
from youtube_trends.csv_io import DataFileError, atomic_write_json


REGION_CODE = DEFAULT_REGION_CODE
MAX_RESULTS = DEFAULT_PAGE_SIZE
TOTAL_VIDEOS = DEFAULT_TOTAL_VIDEOS


def build_parser(defaults: CollectionOptions | None = None) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Collect a YouTube most-popular video snapshot."
    )
    parser.add_argument(
        "--region",
        default=defaults.region_code if defaults else None,
        help="ISO 3166-1 alpha-2 region code",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=defaults.total_videos if defaults else None,
        help="number of videos to collect",
    )
    parser.add_argument(
        "--page-size",
        type=int,
        default=defaults.page_size if defaults else None,
        help="API page size (1-50)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=defaults.timeout if defaults else None,
        help="HTTP timeout in seconds",
    )
    parser.add_argument(
        "--retries",
        type=int,
        default=defaults.retries if defaults else None,
        help="retry count for transient API errors",
    )
    parser.add_argument("--date", dest="run_date", help="output date in YYYY-MM-DD format")
    parser.add_argument(
        "--week",
        help="landing partition in Asia/Seoul ISO week format (YYYY-Www)",
    )
    parser.add_argument(
        "--run-id",
        help="Airflow or local run identifier used to isolate landing artifacts",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="output directory; landing mode defaults to the canonical data/landing path",
    )
    parser.add_argument("--output-file", type=Path, help="explicit output CSV path")
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


def _collected_at() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _landing_context(args: argparse.Namespace) -> tuple[str, str] | None:
    if args.week is None and args.run_id is None:
        return None
    if args.week is None or args.run_id is None:
        raise ConfigurationError("--week and --run-id must be provided together")
    if args.output_file is not None:
        raise ConfigurationError(
            "--output-file cannot be used with --week/--run-id landing mode"
        )
    return parse_iso_week(args.week), parse_run_id(args.run_id)


def _write_error_artifact(
    *,
    run_directory: Path | None,
    week: str | None,
    run_id: str | None,
    started_at: str,
    exit_code: int,
    error: Exception,
) -> None:
    if run_directory is None:
        return
    payload = {
        "schema_version": "1.0",
        "source": "youtube",
        "status": "failed",
        "week": week,
        "run_id": run_id,
        "started_at": started_at,
        "ended_at": _collected_at(),
        "exit_code": exit_code,
        "error_type": type(error).__name__,
        "message": str(error),
    }
    try:
        atomic_write_json(run_directory / "error.json", payload)
    except (DataFileError, OSError) as artifact_error:
        logging.error("failed to write landing error artifact: %s", artifact_error)


def get_trending_videos(
    *,
    api_key: str | None = None,
    region_code: str = REGION_CODE,
    total_videos: int = TOTAL_VIDEOS,
    page_size: int = MAX_RESULTS,
    timeout: float = DEFAULT_TIMEOUT,
    retries: int = DEFAULT_RETRIES,
    service: Any | None = None,
) -> list[dict[str, Any]]:
    """Compatibility wrapper returning the original dictionary shape."""
    load_environment()
    options = CollectionOptions(
        region_code=region_code,
        total_videos=total_videos,
        page_size=page_size,
        timeout=timeout,
        retries=retries,
    )
    youtube = service or build_youtube_service(api_key or require_api_key(), timeout=timeout)
    records = fetch_trending_videos(youtube, options)
    collected_at = _collected_at()
    return [
        {
            key: value
            for key, value in record.to_csv_row(
                region_code=options.region_code,
                collected_at=collected_at,
            ).items()
            if key in LEGACY_VIDEO_FIELDS
        }
        for record in records
    ]


def save_to_csv(
    videos: Sequence[VideoRecord | dict[str, Any]],
    filename: str | Path,
    *,
    region_code: str = REGION_CODE,
    overwrite: bool = True,
) -> None:
    records: list[VideoRecord] = []
    for video in videos:
        if isinstance(video, VideoRecord):
            records.append(video)
        else:
            records.append(
                VideoRecord.from_csv_row(
                    {key: str(value) for key, value in video.items()}
                )
            )
    write_video_csv(
        Path(filename),
        records,
        region_code=region_code,
        collected_at=_collected_at(),
        overwrite=overwrite,
    )


def main(argv: Sequence[str] | None = None) -> int:
    configure_console()
    parser = build_parser()
    args = parser.parse_args(argv)
    load_environment()
    configure_logging(args.log_level)
    started_at = _collected_at()
    landing_week: str | None = None
    landing_run_id: str | None = None
    run_directory: Path | None = None

    try:
        landing = _landing_context(args)
        if landing is not None:
            landing_week, landing_run_id = landing
            run_directory = args.output_dir or landing_run_directory(
                week=landing_week,
                run_id=landing_run_id,
            )
        options = collection_options_from_env(
            region_code=args.region,
            total_videos=args.limit,
            page_size=args.page_size,
            timeout=args.timeout,
            retries=args.retries,
        )
        run_date = (
            parse_run_date(args.run_date)
            if args.run_date
            else current_run_date()
        )
        if landing_week is not None:
            output_name = (
                f"youtube_trending_{options.region_code}_{landing_week}.csv"
            )
        else:
            output_name = (
                f"youtube_trending_{options.region_code}_{run_date.strftime('%Y%m%d')}.csv"
            )
        output_base = run_directory if landing_week is not None else (
            args.output_dir or RAW_DATA_DIR
        )
        output = args.output_file or (output_base / output_name)
        if args.fail_if_exists and output.exists():
            raise DataFileError(f"output already exists: {output}")
        api_key = require_api_key()
        service = build_youtube_service(api_key, timeout=options.timeout)
        videos = fetch_trending_videos(service, options)
        write_video_csv(
            output,
            videos,
            region_code=options.region_code,
            collected_at=_collected_at(),
            overwrite=not args.fail_if_exists,
        )
    except ConfigurationError as exc:
        logging.error("configuration error: %s", exc)
        _write_error_artifact(
            run_directory=run_directory,
            week=landing_week,
            run_id=landing_run_id,
            started_at=started_at,
            exit_code=2,
            error=exc,
        )
        return 2
    except (CollectionError, DataFileError, OSError) as exc:
        logging.error("collection failed: %s", exc)
        _write_error_artifact(
            run_directory=run_directory,
            week=landing_week,
            run_id=landing_run_id,
            started_at=started_at,
            exit_code=1,
            error=exc,
        )
        return 1

    if run_directory is not None:
        summary = {
            "schema_version": "1.0",
            "source": "youtube",
            "status": "success",
            "week": landing_week,
            "run_id": landing_run_id,
            "started_at": started_at,
            "ended_at": _collected_at(),
            "region_code": options.region_code,
            "requested_count": options.total_videos,
            "collected_count": len(videos),
            "output_file": str(output),
        }
        try:
            atomic_write_json(run_directory / "run_summary.json", summary)
        except (DataFileError, OSError) as exc:
            logging.error("failed to write landing run summary: %s", exc)
            _write_error_artifact(
                run_directory=run_directory,
                week=landing_week,
                run_id=landing_run_id,
                started_at=started_at,
                exit_code=1,
                error=exc,
            )
            return 1

    print(f"saved {len(videos)} videos to {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
