#!/usr/bin/env python3
"""Build a label-based visitor-flow smoke-test report for AI Hub CCTV samples."""

from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from statistics import mean
from typing import Any


TIME_BUCKET_ORDER = {
    "morning": 1,
    "afternoon": 2,
    "evening": 3,
    "night": 4,
}


@dataclass(frozen=True)
class ClipSummary:
    stem: str
    video_file: str
    label_file: str
    date: str
    time: str
    day: str
    weather: str
    camera_id: str
    time_bucket: str
    fps: float
    total_frame: int
    play_time: str
    total_person: int
    unique_person_ids: int
    person_annotation_rows: int
    avg_persons_per_frame: float
    max_persons_per_frame: int
    store_event_count: int
    store_in_count: int
    store_out_count: int


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sample-dir", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--grid-cols", default=3, type=int)
    parser.add_argument("--grid-rows", default=3, type=int)
    return parser.parse_args()


def parse_clip_name(stem: str) -> dict[str, str]:
    match = re.match(
        r"(?P<date>\d{4}-\d{2}-\d{2})_(?P<time>\d{2}-\d{2}-\d{2})_"
        r"(?P<day>[a-z]+)_(?P<weather>[a-z]+)_out_ju-ja_(?P<camera_id>C\d{4})$",
        stem,
    )
    if not match:
        raise ValueError(f"Unexpected clip stem: {stem}")
    return match.groupdict()


def bucket_from_hour(hour: int) -> str:
    if 9 <= hour < 12:
        return "morning"
    if 12 <= hour < 16:
        return "afternoon"
    if 16 <= hour < 20:
        return "evening"
    if 20 <= hour < 24:
        return "night"
    return "other"


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def bottom_center(bbox: list[float]) -> tuple[float, float]:
    x1, _y1, x2, y2 = bbox
    return ((x1 + x2) / 2, y2)


def grid_cell(x: float, y: float, width: int, height: int, cols: int, rows: int) -> str:
    col = min(cols - 1, max(0, int(x / width * cols)))
    row = min(rows - 1, max(0, int(y / height * rows)))
    return f"r{row + 1}c{col + 1}"


def summarize_clip(label_path: Path, video_path: Path, grid_cols: int, grid_rows: int) -> tuple[ClipSummary, Counter[str]]:
    data = read_json(label_path)
    meta = parse_clip_name(label_path.stem)
    video = data["video"]
    width, height = video["resolution"][:2]
    annotations = data.get("annotations", [])
    events = data.get("events", [])

    frame_counts = Counter(row["frame"] for row in annotations)
    person_ids = {row["id"] for row in annotations}
    grid_counts: Counter[str] = Counter()

    for row in annotations:
        x, y = bottom_center(row["bbox"])
        grid_counts[grid_cell(x, y, width, height, grid_cols, grid_rows)] += 1

    store_events = [event for event in events if str(event.get("action", "")).startswith("store_")]
    store_action_counts = Counter(event.get("action", "") for event in store_events)
    hour = int(meta["time"][:2])

    summary = ClipSummary(
        stem=label_path.stem,
        video_file=str(video_path),
        label_file=str(label_path),
        date=meta["date"],
        time=meta["time"].replace("-", ":"),
        day=meta["day"],
        weather=meta["weather"],
        camera_id=meta["camera_id"],
        time_bucket=bucket_from_hour(hour),
        fps=float(video["fps"]),
        total_frame=int(video["total_frame"]),
        play_time=str(video["play_time"]),
        total_person=int(video["total_person"]),
        unique_person_ids=len(person_ids),
        person_annotation_rows=len(annotations),
        avg_persons_per_frame=round(mean(frame_counts.values()), 3) if frame_counts else 0.0,
        max_persons_per_frame=max(frame_counts.values(), default=0),
        store_event_count=len(store_events),
        store_in_count=store_action_counts["store_in"],
        store_out_count=store_action_counts["store_out"],
    )
    return summary, grid_counts


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    args = parse_args()
    # [Design Intent] Enforce the standard curated dataset layout to avoid mixing local extraction names with dataset-stage terminology.
    video_dir = args.sample_dir / "videos"
    label_dir = args.sample_dir / "labels"
    args.output_dir.mkdir(parents=True, exist_ok=True)

    label_paths = sorted(label_dir.glob("*.json"))
    if not label_paths:
        raise SystemExit(f"No labels found: {label_dir}")

    summaries: list[ClipSummary] = []
    heatmap_rows: list[dict[str, Any]] = []

    for label_path in label_paths:
        video_path = video_dir / f"{label_path.stem}.mp4"
        if not video_path.exists():
            raise FileNotFoundError(f"Missing matched video for {label_path.name}: {video_path}")
        summary, grid_counts = summarize_clip(label_path, video_path, args.grid_cols, args.grid_rows)
        summaries.append(summary)
        for cell_id, count in sorted(grid_counts.items()):
            heatmap_rows.append(
                {
                    "stem": summary.stem,
                    "time": summary.time,
                    "time_bucket": summary.time_bucket,
                    "grid_cell": cell_id,
                    "person_annotation_rows": count,
                }
            )

    summaries.sort(key=lambda row: (TIME_BUCKET_ORDER.get(row.time_bucket, 99), row.time))
    summary_rows = [summary.__dict__ for summary in summaries]
    fieldnames = list(summary_rows[0].keys())

    write_csv(args.output_dir / "summary.csv", summary_rows, fieldnames)
    write_csv(
        args.output_dir / "grid_heatmap.csv",
        heatmap_rows,
        ["stem", "time", "time_bucket", "grid_cell", "person_annotation_rows"],
    )

    bucket_rows: list[dict[str, Any]] = []
    by_bucket: dict[str, list[ClipSummary]] = defaultdict(list)
    for summary in summaries:
        by_bucket[summary.time_bucket].append(summary)

    for bucket, rows in sorted(by_bucket.items(), key=lambda item: TIME_BUCKET_ORDER.get(item[0], 99)):
        bucket_rows.append(
            {
                "time_bucket": bucket,
                "clip_count": len(rows),
                "total_person": sum(row.total_person for row in rows),
                "avg_total_person_per_clip": round(mean(row.total_person for row in rows), 3),
                "max_persons_per_frame": max(row.max_persons_per_frame for row in rows),
                "store_event_count": sum(row.store_event_count for row in rows),
            }
        )

    write_csv(
        args.output_dir / "bucket_summary.csv",
        bucket_rows,
        [
            "time_bucket",
            "clip_count",
            "total_person",
            "avg_total_person_per_clip",
            "max_persons_per_frame",
            "store_event_count",
        ],
    )

    peak_bucket = max(bucket_rows, key=lambda row: row["avg_total_person_per_clip"])
    analysis = {
        # [Design Intent] Keep the first MVP report evidence-based and avoid unsupported purchase/visitor claims.
        "scope": "label_based_smoke_test",
        "sample_dir": str(args.sample_dir),
        "clip_count": len(summaries),
        "camera_id": sorted({row.camera_id for row in summaries}),
        "date": sorted({row.date for row in summaries}),
        "excluded_claims": [
            "actual_store_visits",
            "purchase_conversion",
            "customer_identity",
            "gender_age_targeting",
        ],
        "peak_time_bucket": peak_bucket["time_bucket"],
        "bucket_summary": bucket_rows,
        "recommended_next_step": "Run YOLO person detection on the same 8 mp4 clips and compare with label-based person counts.",
    }
    (args.output_dir / "analysis.json").write_text(
        json.dumps(analysis, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(f"wrote {args.output_dir}")
    print(f"clips={len(summaries)} peak_time_bucket={peak_bucket['time_bucket']}")


if __name__ == "__main__":
    main()
