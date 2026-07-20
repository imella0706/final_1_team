#!/usr/bin/env python3
"""Create L2 visitor-flow event and aggregation artifacts from C0241 clips."""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import cv2
import pandas as pd
from ultralytics import YOLO


# [Design Intent] L2-1은 "사람 수"를 확정하는 단계가 아니라, YOLO bbox 출력을
# 시간/화면 grid 기준 observation event table로 정규화하는 오프라인 배치 단계다.


EVENT_COLUMNS = [
    "analysis_id",
    "video_id",
    "frame_index",
    "timestamp_ms",
    "observed_at",
    "object_class",
    "confidence",
    "bbox_x1",
    "bbox_y1",
    "bbox_x2",
    "bbox_y2",
    "point_x_norm",
    "point_y_norm",
    "roi_id",
    "is_in_front_of_shop",
    "zone_id",
]

SUMMARY_COLUMNS = [
    "analysis_id",
    "time_bucket",
    "zone_id",
    "roi_id",
    "person_detection_observations",
    "in_front_of_shop_observations",
    "active_person_tracks",
    "density_score",
    "hotspot_rank",
    "business_gap",
    "marketing_signal",
]

FILENAME_DATETIME_PATTERN = re.compile(
    r"(?P<date>\d{4}-\d{2}-\d{2})_(?P<time>\d{2}-\d{2}-\d{2})"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run L2-1 frame sampling, person detection, event export, and "
            "time/grid aggregation for matched AIHub clips."
        )
    )
    parser.add_argument(
        "--sample-dir",
        required=True,
        type=Path,
        help="Directory containing videos/ and labels/ subdirectories.",
    )
    parser.add_argument("--model", required=True, type=Path, help="YOLO weight path")
    parser.add_argument("--device", default="cpu", help="Inference device: cpu, cuda, 0")
    parser.add_argument("--imgsz", default=960, type=int, help="YOLO inference image size")
    parser.add_argument(
        "--conf",
        required=True,
        type=float,
        help="Detection confidence threshold selected from L1 calibration.",
    )
    parser.add_argument(
        "--sample-every-sec",
        default=10.0,
        type=float,
        help="Frame sampling interval in seconds.",
    )
    parser.add_argument("--grid-cols", default=6, type=int, help="Screen grid columns")
    parser.add_argument("--grid-rows", default=4, type=int, help="Screen grid rows")
    parser.add_argument(
        "--time-bucket-minutes",
        default=60,
        type=int,
        help="Aggregation bucket size in minutes.",
    )
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument(
        "--analysis-id",
        default="",
        help="Optional stable analysis id. Defaults to output directory name.",
    )
    return parser.parse_args()


def validate_args(args: argparse.Namespace) -> str:
    videos_dir = args.sample_dir / "videos"
    labels_dir = args.sample_dir / "labels"
    if not videos_dir.is_dir():
        raise FileNotFoundError(f"videos directory not found: {videos_dir}")
    if not labels_dir.is_dir():
        raise FileNotFoundError(f"labels directory not found: {labels_dir}")
    if not args.model.is_file():
        raise FileNotFoundError(f"model not found: {args.model}")
    if not 0.0 <= args.conf <= 1.0:
        raise ValueError("--conf must be between 0.0 and 1.0")
    if args.imgsz <= 0:
        raise ValueError("--imgsz must be greater than 0")
    if args.sample_every_sec <= 0:
        raise ValueError("--sample-every-sec must be greater than 0")
    if args.grid_cols <= 0 or args.grid_rows <= 0:
        raise ValueError("--grid-cols and --grid-rows must be greater than 0")
    if args.time_bucket_minutes <= 0:
        raise ValueError("--time-bucket-minutes must be greater than 0")
    return args.analysis_id or args.output_dir.name


def matched_video_paths(sample_dir: Path) -> list[Path]:
    videos_by_stem = {path.stem: path for path in (sample_dir / "videos").glob("*.mp4")}
    labels_by_stem = {path.stem: path for path in (sample_dir / "labels").glob("*.json")}
    common_stems = sorted(videos_by_stem.keys() & labels_by_stem.keys())
    if not common_stems:
        raise FileNotFoundError(f"no matched mp4/json pairs under: {sample_dir}")

    missing_labels = sorted(videos_by_stem.keys() - labels_by_stem.keys())
    missing_videos = sorted(labels_by_stem.keys() - videos_by_stem.keys())
    if missing_labels or missing_videos:
        raise ValueError(
            "unmatched video/label stems: "
            f"missing_labels={missing_labels}, missing_videos={missing_videos}"
        )
    return [videos_by_stem[stem] for stem in common_stems]


def parse_clip_start_time(video_id: str) -> datetime:
    match = FILENAME_DATETIME_PATTERN.search(video_id)
    if not match:
        raise ValueError(f"cannot parse clip datetime from video_id: {video_id}")
    value = f"{match.group('date')} {match.group('time').replace('-', ':')}"
    return datetime.strptime(value, "%Y-%m-%d %H:%M:%S")


def floor_time_bucket(value: datetime, bucket_minutes: int) -> datetime:
    midnight = value.replace(hour=0, minute=0, second=0, microsecond=0)
    elapsed_minutes = int((value - midnight).total_seconds() // 60)
    floored_minutes = (elapsed_minutes // bucket_minutes) * bucket_minutes
    return midnight + timedelta(minutes=floored_minutes)


def zone_id_from_point(
    point_x_norm: float,
    point_y_norm: float,
    grid_cols: int,
    grid_rows: int,
) -> str:
    col = min(grid_cols - 1, max(0, int(point_x_norm * grid_cols)))
    row = min(grid_rows - 1, max(0, int(point_y_norm * grid_rows)))
    return f"r{row}_c{col}"


def video_metadata(cap: cv2.VideoCapture, video_path: Path) -> dict[str, Any]:
    metadata = {
        "fps": float(cap.get(cv2.CAP_PROP_FPS)),
        "frame_count": int(cap.get(cv2.CAP_PROP_FRAME_COUNT)),
        "width": int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
        "height": int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
    }
    if metadata["fps"] <= 0:
        raise RuntimeError(f"invalid video fps: {video_path}")
    if (
        metadata["frame_count"] <= 0
        or metadata["width"] <= 0
        or metadata["height"] <= 0
    ):
        raise RuntimeError(f"invalid video metadata: {video_path} {metadata}")
    return metadata


def collect_clip_events(
    model: YOLO,
    video_path: Path,
    analysis_id: str,
    args: argparse.Namespace,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    video_id = video_path.stem
    clip_start_time = parse_clip_start_time(video_id)
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"failed to open video: {video_path}")

    rows: list[dict[str, Any]] = []
    try:
        metadata = video_metadata(cap, video_path)
        sample_step_frames = max(1, round(metadata["fps"] * args.sample_every_sec))
        frame_indices = list(range(0, metadata["frame_count"], sample_step_frames))

        for frame_index in frame_indices:
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
            ok, frame = cap.read()
            if not ok:
                raise RuntimeError(f"failed to read frame={frame_index}: {video_path}")

            timestamp_sec = frame_index / metadata["fps"]
            timestamp_ms = int(round(timestamp_sec * 1000))
            observed_at = clip_start_time + timedelta(seconds=timestamp_sec)
            result = model.predict(
                frame,
                classes=[0],
                conf=args.conf,
                device=args.device,
                imgsz=args.imgsz,
                verbose=False,
            )[0]

            if result.boxes is None or len(result.boxes) == 0:
                print(f"video={video_id}, frame={frame_index}, detections=0")
                continue

            xyxy_values = result.boxes.xyxy.cpu().tolist()
            confidence_values = result.boxes.conf.cpu().tolist()
            for xyxy, confidence in zip(xyxy_values, confidence_values):
                x1, y1, x2, y2 = (float(value) for value in xyxy)
                point_x_norm = ((x1 + x2) / 2.0) / metadata["width"]
                point_y_norm = y2 / metadata["height"]
                point_x_norm = min(1.0, max(0.0, point_x_norm))
                point_y_norm = min(1.0, max(0.0, point_y_norm))

                rows.append(
                    {
                        "analysis_id": analysis_id,
                        "video_id": video_id,
                        "frame_index": frame_index,
                        "timestamp_ms": timestamp_ms,
                        "observed_at": observed_at.isoformat(timespec="seconds"),
                        "object_class": "person",
                        "confidence": round(float(confidence), 6),
                        "bbox_x1": round(x1, 2),
                        "bbox_y1": round(y1, 2),
                        "bbox_x2": round(x2, 2),
                        "bbox_y2": round(y2, 2),
                        "point_x_norm": round(point_x_norm, 6),
                        "point_y_norm": round(point_y_norm, 6),
                        "roi_id": "none",
                        "is_in_front_of_shop": False,
                        "zone_id": zone_id_from_point(
                            point_x_norm=point_x_norm,
                            point_y_norm=point_y_norm,
                            grid_cols=args.grid_cols,
                            grid_rows=args.grid_rows,
                        ),
                    }
                )

            print(
                f"video={video_id}, frame={frame_index}, "
                f"detections={len(xyxy_values)}"
            )
    finally:
        cap.release()

    clip_summary = {
        "video_id": video_id,
        "fps": metadata["fps"],
        "frame_count": metadata["frame_count"],
        "width": metadata["width"],
        "height": metadata["height"],
        "sampled_frames": len(frame_indices),
        "person_detection_observations": len(rows),
    }
    return rows, clip_summary


def build_events_dataframe(rows: list[dict[str, Any]]) -> pd.DataFrame:
    dataframe = pd.DataFrame(rows, columns=EVENT_COLUMNS)
    if dataframe.empty:
        return dataframe
    dataframe["observed_at"] = pd.to_datetime(dataframe["observed_at"])
    return dataframe


def build_summary_dataframe(
    events: pd.DataFrame,
    analysis_id: str,
    time_bucket_minutes: int,
) -> pd.DataFrame:
    if events.empty:
        return pd.DataFrame(columns=SUMMARY_COLUMNS)

    working = events.copy()
    working["time_bucket"] = working["observed_at"].apply(
        lambda value: floor_time_bucket(value.to_pydatetime(), time_bucket_minutes)
    )
    grouped = (
        working.groupby(["analysis_id", "time_bucket", "zone_id", "roi_id"], as_index=False)
        .agg(
            person_detection_observations=("object_class", "size"),
            in_front_of_shop_observations=("is_in_front_of_shop", "sum"),
        )
        .sort_values(["time_bucket", "zone_id"])
    )
    grouped["active_person_tracks"] = 0

    max_observations = int(grouped["person_detection_observations"].max())
    grouped["density_score"] = grouped["person_detection_observations"].apply(
        lambda value: round(value / max_observations, 6) if max_observations else 0.0
    )
    grouped["hotspot_rank"] = grouped["person_detection_observations"].rank(
        method="dense", ascending=False
    ).astype(int)
    grouped["business_gap"] = grouped["time_bucket"].apply(business_gap_label)
    grouped["marketing_signal"] = grouped.apply(marketing_signal_label, axis=1)

    grouped["time_bucket"] = grouped["time_bucket"].dt.strftime("%Y-%m-%d %H:%M:%S")
    return grouped[SUMMARY_COLUMNS]


def business_gap_label(time_bucket: pd.Timestamp) -> str:
    # [Design Intent] 실제 점포 영업시간이 없으므로 임시 rule만 둔다. L2-2에서
    # 사용자 입력 영업시간과 연결되기 전까지는 확정 추천이 아니라 후보 신호다.
    hour = int(time_bucket.hour)
    if hour < 10:
        return "before_default_open_hours"
    if hour >= 21:
        return "late_evening_after_default_peak"
    return "within_default_open_hours"


def marketing_signal_label(row: pd.Series) -> str:
    observations = int(row["person_detection_observations"])
    gap = str(row["business_gap"])
    if observations <= 0:
        return "no_observation"
    if gap == "before_default_open_hours":
        return "morning_promotion_candidate"
    if gap == "late_evening_after_default_peak":
        return "evening_takeout_or_signage_candidate"
    return "storefront_visibility_candidate"


def build_dashboard_summary(summary: pd.DataFrame) -> pd.DataFrame:
    if summary.empty:
        return pd.DataFrame(
            columns=[
                "time_bucket",
                "total_person_detection_observations",
                "top_zone_id",
                "top_zone_observations",
                "marketing_signal",
            ]
        )

    idx = summary.groupby("time_bucket")["person_detection_observations"].idxmax()
    top_zones = summary.loc[idx, ["time_bucket", "zone_id", "person_detection_observations"]]
    totals = (
        summary.groupby("time_bucket", as_index=False)
        .agg(
            total_person_detection_observations=(
                "person_detection_observations",
                "sum",
            ),
            marketing_signal=("marketing_signal", "first"),
        )
        .sort_values("time_bucket")
    )
    dashboard = totals.merge(top_zones, on="time_bucket", how="left")
    return dashboard.rename(
        columns={
            "zone_id": "top_zone_id",
            "person_detection_observations": "top_zone_observations",
        }
    )


def build_analysis_json(
    args: argparse.Namespace,
    analysis_id: str,
    clip_summaries: list[dict[str, Any]],
    events: pd.DataFrame,
    summary: pd.DataFrame,
) -> dict[str, Any]:
    total_observations = int(len(events))
    if summary.empty:
        peak_bucket = None
        top_zone = None
    else:
        peak_row = summary.sort_values(
            ["person_detection_observations", "density_score"],
            ascending=[False, False],
        ).iloc[0]
        peak_bucket = str(peak_row["time_bucket"])
        top_zone = str(peak_row["zone_id"])

    return {
        "analysis_id": analysis_id,
        "scope": "L2-1_time_grid_person_detection_observation_aggregation",
        "sample_dir": str(args.sample_dir),
        "model": str(args.model),
        "device": args.device,
        "imgsz": args.imgsz,
        "confidence_threshold": args.conf,
        "sample_every_sec": args.sample_every_sec,
        "grid": {"cols": args.grid_cols, "rows": args.grid_rows},
        "time_bucket_minutes": args.time_bucket_minutes,
        "clip_count": len(clip_summaries),
        "sampled_frames": int(sum(item["sampled_frames"] for item in clip_summaries)),
        "person_detection_observations": total_observations,
        "peak_time_bucket": peak_bucket,
        "top_zone_id": top_zone,
        "artifacts": {
            "events_parquet": str(args.output_dir / "events.parquet"),
            "summary_parquet": str(args.output_dir / "summary.parquet"),
            "analysis_json": str(args.output_dir / "analysis.json"),
            "dashboard_summary_csv": str(args.output_dir / "dashboard_summary.csv"),
        },
        "clip_summaries": clip_summaries,
        "limitations": [
            "Counts are frame-level person bbox observations, not unique visitors.",
            "Tracking is not used in L2-1, so repeated appearances of the same person are counted repeatedly.",
            "Grid zones are screen-space buckets, not real ground-plane coordinates.",
            "ROI counting is not enabled in L2-1; roi_id remains none and is_in_front_of_shop remains false.",
            "Marketing signals are rule-based hypotheses for dashboard validation, not verified business outcomes.",
        ],
    }


def main() -> None:
    args = parse_args()
    analysis_id = validate_args(args)
    video_paths = matched_video_paths(args.sample_dir)
    args.output_dir.mkdir(parents=True, exist_ok=True)

    model = YOLO(str(args.model))
    all_rows: list[dict[str, Any]] = []
    clip_summaries: list[dict[str, Any]] = []
    for video_path in video_paths:
        print(f"[L2-1] processing video={video_path.name}")
        rows, clip_summary = collect_clip_events(
            model=model,
            video_path=video_path,
            analysis_id=analysis_id,
            args=args,
        )
        all_rows.extend(rows)
        clip_summaries.append(clip_summary)

    events = build_events_dataframe(all_rows)
    summary = build_summary_dataframe(
        events=events,
        analysis_id=analysis_id,
        time_bucket_minutes=args.time_bucket_minutes,
    )
    dashboard_summary = build_dashboard_summary(summary)
    analysis = build_analysis_json(
        args=args,
        analysis_id=analysis_id,
        clip_summaries=clip_summaries,
        events=events,
        summary=summary,
    )

    events.to_parquet(args.output_dir / "events.parquet", index=False)
    summary.to_parquet(args.output_dir / "summary.parquet", index=False)
    dashboard_summary.to_csv(args.output_dir / "dashboard_summary.csv", index=False)
    (args.output_dir / "analysis.json").write_text(
        json.dumps(analysis, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(f"analysis_id={analysis_id}")
    print(f"clip_count={len(clip_summaries)}")
    print(f"sampled_frames={analysis['sampled_frames']}")
    print(f"person_detection_observations={analysis['person_detection_observations']}")
    print(f"peak_time_bucket={analysis['peak_time_bucket']}")
    print(f"top_zone_id={analysis['top_zone_id']}")
    print(f"output_dir={args.output_dir}")


if __name__ == "__main__":
    main()
