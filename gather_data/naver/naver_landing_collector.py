# -*- coding: utf-8 -*-
"""Collect Naver landing artifacts for the sns_trend dataset."""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from step1_collect import collect, to_dataframe
from step2_datalab import collect_datalab_search_trend


KST = timezone(timedelta(hours=9))
REPO_ROOT = Path(__file__).resolve().parents[2]
LANDING_DATA_ROOT = REPO_ROOT / "data" / "landing" / "sns_trend"
CURATED_DATA_ROOT = REPO_ROOT / "data" / "curated" / "sns_trend"
DEFAULT_CURATED_VERSION = "v3"
DEFAULT_KEYWORD = "카페"
DEFAULT_SOURCES = ("blog", "news")
CRAWLER_RUN_SUMMARY_FILENAME = "crawler_run_summary.json"
CRAWLER_ERROR_FILENAME = "error.json"
STOPWORDS = {
    "네이버",
    "블로그",
    "뉴스",
    "오늘",
    "정말",
    "생각",
    "때문",
    "그리고",
    "관련",
    "기자",
}


class NaverLandingError(RuntimeError):
    """Fatal Naver landing collection failure."""


def now_kst() -> datetime:
    return datetime.now(KST)


def now_utc_z() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def clean_text(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def parse_iso_week(value: str) -> str:
    normalized = clean_text(value).upper()
    if not re.fullmatch(r"\d{4}-W\d{2}", normalized):
        raise NaverLandingError("--week must use YYYY-Www format")
    year, week = normalized.split("-W", 1)
    week_number = int(week)
    if not 1 <= week_number <= 53:
        raise NaverLandingError("--week number must be between 01 and 53")
    return f"{year}-W{week_number:02d}"


def parse_run_date(value: str) -> date:
    try:
        return datetime.strptime(clean_text(value), "%Y-%m-%d").date()
    except ValueError as exc:
        raise NaverLandingError("--date must use YYYY-MM-DD format") from exc


def parse_dataset_version(value: str) -> str:
    normalized = clean_text(value).lower()
    if not re.fullmatch(r"v[1-9]\d*", normalized):
        raise NaverLandingError("dataset version must use vN format, for example v3")
    return normalized


def parse_run_id(value: str) -> str:
    normalized = clean_text(value)
    if not normalized:
        raise NaverLandingError("--run-id must not be empty")
    if not re.fullmatch(r"[A-Za-z0-9_.:+@=-]+", normalized):
        raise NaverLandingError("--run-id contains unsupported characters")
    return normalized


def parse_sources(value: str) -> tuple[str, ...]:
    sources = tuple(source.strip() for source in value.split(",") if source.strip())
    invalid = [source for source in sources if source not in DEFAULT_SOURCES]
    if invalid:
        raise NaverLandingError(f"unsupported sources: {invalid}")
    if not sources:
        raise NaverLandingError("--sources must include at least one source")
    return sources


def landing_run_directory(
    *,
    week: str,
    run_id: str,
    root: Path = LANDING_DATA_ROOT,
) -> Path:
    return root / f"week={week}" / "raw" / "naver" / f"run_id={run_id}"


def curated_meme_card_candidates_path(
    *,
    version: str,
    week: str,
    root: Path = CURATED_DATA_ROOT,
) -> Path:
    return (
        root
        / version
        / "meme_card_candidates"
        / "naver"
        / f"naver_meme_card_candidates_{week}.json"
    )


def output_directory(args: argparse.Namespace) -> Path:
    if args.output_dir:
        return Path(args.output_dir)
    if not args.week or not args.run_id:
        raise NaverLandingError("--week and --run-id are required without --output-dir")
    return landing_run_directory(
        week=parse_iso_week(args.week),
        run_id=parse_run_id(args.run_id),
    )


def collect_search_dataframes(
    *,
    keyword: str,
    sources: tuple[str, ...],
    limit: int,
) -> dict[str, pd.DataFrame]:
    frames: dict[str, pd.DataFrame] = {}
    for source in sources:
        items = collect(source, keyword=keyword, limit=limit)
        frame = to_dataframe(items, source)
        if frame.empty:
            raise NaverLandingError(f"Naver {source} search returned no rows")
        frames[source] = frame
    return frames


def write_dataframe_csv(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False, encoding="utf-8-sig")


def tokenize_texts(texts: list[str]) -> list[str]:
    try:
        from kiwipiepy import Kiwi
    except ImportError:
        words: list[str] = []
        for text in texts:
            words.extend(re.findall(r"[가-힣A-Za-z0-9]{2,}", text))
        return words

    kiwi = Kiwi()
    words = []
    for text in texts:
        for token in kiwi.tokenize(text):
            if token.tag in {"NNG", "NNP"} and len(token.form) >= 2:
                words.append(token.form)
    return words


def build_word_frequency_rows(
    frames: dict[str, pd.DataFrame],
    *,
    stopwords: set[str] = STOPWORDS,
    top_n: int = 50,
) -> list[dict[str, Any]]:
    texts: list[str] = []
    for frame in frames.values():
        for column in ("title", "description"):
            if column in frame.columns:
                texts.extend(clean_text(value) for value in frame[column].fillna(""))

    counter = Counter(
        word
        for word in tokenize_texts(texts)
        if len(word) >= 2 and word not in stopwords
    )
    return [
        {"keyword": keyword, "count": count}
        for keyword, count in counter.most_common(top_n)
    ]


def write_word_frequency_csv(rows: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["keyword", "count"])
        writer.writeheader()
        writer.writerows(rows)


def write_curated_meme_card_candidates(
    *,
    rows: list[dict[str, Any]],
    version: str,
    week: str,
    run_id: str,
    keyword: str,
    source_article_count: int,
    root: Path = CURATED_DATA_ROOT,
) -> Path:
    terms = [str(row["keyword"]) for row in rows]
    output_path = curated_meme_card_candidates_path(
        version=version,
        week=week,
        root=root,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": "1.0",
        "dataset_name": "sns_trend",
        "version": version,
        "stage": "curated",
        "artifact_name": "meme_card_candidates",
        "source_family": "naver",
        "curation_status": "rule_filtered",
        "review_status": "pending",
        "usage_policy": "reference_only",
        "auto_promote_to_processed": False,
        "promotion_requirement": "human_review_and_cross_platform_evidence",
        "note": (
            "Naver Search/DataLab output is used for trend monitoring only. "
            "Do not promote directly to processed without human review and "
            "cross-platform evidence."
        ),
        "collected_week": week,
        "source_landing_run_id": run_id,
        "keyword": keyword,
        "generated_at": now_utc_z(),
        "source_article_count": source_article_count,
        "term_count": len(terms),
        "terms": terms,
        "display_terms": terms,
        "term_scores": rows,
    }
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return output_path


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Collect Naver landing artifacts for sns_trend."
    )
    parser.add_argument("--keyword", default=DEFAULT_KEYWORD)
    parser.add_argument("--week")
    parser.add_argument("--run-id")
    parser.add_argument("--date", default=now_kst().date().isoformat())
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--sources", default="blog,news")
    parser.add_argument("--output-dir")
    parser.add_argument("--include-datalab", action="store_true")
    parser.add_argument("--datalab-start-date")
    parser.add_argument("--datalab-end-date")
    parser.add_argument("--datalab-time-unit", default="week", choices=("date", "week", "month"))
    parser.add_argument("--emit-curated-meme-card-candidates", action="store_true")
    parser.add_argument("--curated-version", default=DEFAULT_CURATED_VERSION)
    parser.add_argument("--curated-root", default=str(CURATED_DATA_ROOT))
    parser.add_argument("--top-n", type=int, default=50)
    parser.add_argument("--fail-if-exists", action="store_true")
    return parser.parse_args(argv)


def run(args: argparse.Namespace) -> Path:
    run_date = parse_run_date(args.date)
    stamp = run_date.strftime("%Y%m%d")
    week = parse_iso_week(args.week) if args.week else ""
    run_id = parse_run_id(args.run_id) if args.run_id else ""
    version = parse_dataset_version(args.curated_version)
    sources = parse_sources(args.sources)
    if args.limit < 1 or args.limit > 1000:
        raise NaverLandingError("--limit must be between 1 and 1000")
    if args.top_n < 1:
        raise NaverLandingError("--top-n must be at least 1")
    if args.emit_curated_meme_card_candidates and (not week or not run_id):
        raise NaverLandingError(
            "--week and --run-id are required to emit curated candidates"
        )

    run_dir = output_directory(args)
    if args.fail_if_exists and run_dir.exists() and any(run_dir.iterdir()):
        raise NaverLandingError(f"output directory already exists: {run_dir}")
    run_dir.mkdir(parents=True, exist_ok=True)

    frames = collect_search_dataframes(
        keyword=args.keyword,
        sources=sources,
        limit=args.limit,
    )
    outputs: dict[str, str] = {}
    counts: dict[str, int] = {}
    for source, frame in frames.items():
        output_path = run_dir / f"naver_{source}_{args.keyword}_{stamp}.csv"
        write_dataframe_csv(frame, output_path)
        outputs[f"{source}_csv"] = str(output_path)
        counts[source] = len(frame)

    datalab_rows = []
    if args.include_datalab:
        datalab_start = args.datalab_start_date or (run_date - timedelta(days=28)).isoformat()
        datalab_end = args.datalab_end_date or run_date.isoformat()
        datalab_rows = collect_datalab_search_trend(
            keyword=args.keyword,
            start_date=datalab_start,
            end_date=datalab_end,
            time_unit=args.datalab_time_unit,
        )
        datalab_path = run_dir / f"datalab_{args.keyword}_{stamp}.csv"
        write_dataframe_csv(pd.DataFrame(datalab_rows), datalab_path)
        outputs["datalab_csv"] = str(datalab_path)

    word_rows = build_word_frequency_rows(frames, top_n=args.top_n)
    if not word_rows:
        raise NaverLandingError("no Naver word frequency rows were produced")
    word_freq_path = run_dir / f"naver_word_freq_{stamp}.csv"
    write_word_frequency_csv(word_rows, word_freq_path)
    outputs["word_freq_csv"] = str(word_freq_path)

    curated_path: Path | None = None
    if args.emit_curated_meme_card_candidates:
        curated_path = write_curated_meme_card_candidates(
            rows=word_rows,
            version=version,
            week=week,
            run_id=run_id,
            keyword=args.keyword,
            source_article_count=sum(counts.values()),
            root=Path(args.curated_root),
        )
        outputs["curated_meme_card_candidates"] = str(curated_path)

    summary_path = run_dir / CRAWLER_RUN_SUMMARY_FILENAME
    write_json(
        summary_path,
        {
            "schema_version": "1.0",
            "source": "naver",
            "status": "success",
            "week": week or None,
            "run_id": run_id or None,
            "run_date": run_date.isoformat(),
            "keyword": args.keyword,
            "sources": list(sources),
            "limit": args.limit,
            "include_datalab": bool(args.include_datalab),
            "article_count": sum(counts.values()),
            "source_counts": counts,
            "word_freq_count": len(word_rows),
            "datalab_count": len(datalab_rows),
            "collected_at": now_utc_z(),
            "outputs": {**outputs, "crawler_run_summary": str(summary_path)},
        },
    )
    return run_dir


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        run_dir = run(args)
    except Exception as exc:
        try:
            run_dir = output_directory(args)
            write_json(
                run_dir / CRAWLER_ERROR_FILENAME,
                {
                    "schema_version": "1.0",
                    "source": "naver",
                    "status": "failed",
                    "error_type": exc.__class__.__name__,
                    "message": str(exc),
                    "failed_at": now_utc_z(),
                },
            )
        except Exception:
            pass
        print(f"Naver landing collection failed: {exc}", file=sys.stderr)
        return 1

    print(f"saved Naver landing artifacts to {run_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
