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


# [Design Intent] L2 집계는 "사람 수"를 확정하는 단계가 아니라, YOLO bbox
# 출력을 sampled frame/time/grid 기준 observation table로 정규화하는 오프라인 배치다.


REPO_ROOT = Path(__file__).resolve().parents[1]

EVENT_COLUMNS = [
    "analysis_id",
    "date_id",
    "video_id",
    "frame_index",
    "timestamp_ms",
    "observed_at",
    "time_bucket",
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

FRAME_COLUMNS = [
    "analysis_id",
    "date_id",
    "video_id",
    "frame_index",
    "timestamp_ms",
    "observed_at",
    "time_bucket",
    "person_detection_count",
]

SUMMARY_COLUMNS = [
    "analysis_id",
    "date_id",
    "time_bucket",
    "zone_id",
    "roi_id",
    "sampled_frame_count",
    "person_detection_observations",
    "mean_persons_per_sampled_frame",
    "p95_persons_per_sampled_frame",
    "max_persons_per_sampled_frame",
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
            "Run L2 frame sampling, person detection/event reuse, event export, "
            "and frame-normalized time/grid aggregation for matched AIHub clips."
        )
    )
    parser.add_argument(
        "--sample-dir",
        action="append",
        type=Path,
        help="Directory containing videos/ and labels/ subdirectories.",
    )
    parser.add_argument(
        "--from-evaluation-dir",
        action="append",
        type=Path,
        help=(
            "Directory containing L2-3 clip evaluation subdirectories. "
            "Use this to reuse prediction_candidates.csv instead of rerunning YOLO."
        ),
    )
    parser.add_argument("--model", type=Path, help="YOLO weight path")
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
    parser.add_argument(
        "--clip-stems",
        nargs="+",
        default=None,
        help="Optional explicit clip stems to include.",
    )
    parser.add_argument(
        "--expected-clip-count",
        default=None,
        type=int,
        help="Fail if the selected matched clip count differs from this value.",
    )
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument(
        "--analysis-id",
        default="",
        help="Optional stable analysis id. Defaults to output directory name.",
    )
    return parser.parse_args()


def validate_args(args: argparse.Namespace) -> str:
    has_sample_dirs = bool(args.sample_dir)
    has_evaluation_dirs = bool(args.from_evaluation_dir)
    if has_sample_dirs == has_evaluation_dirs:
        raise ValueError(
            "provide exactly one input mode: --sample-dir for fresh YOLO inference "
            "or --from-evaluation-dir for L2-3 prediction reuse"
        )
    if has_sample_dirs:
        for sample_dir in args.sample_dir:
            videos_dir = sample_dir / "videos"
            labels_dir = sample_dir / "labels"
            if not videos_dir.is_dir():
                raise FileNotFoundError(f"videos directory not found: {videos_dir}")
            if not labels_dir.is_dir():
                raise FileNotFoundError(f"labels directory not found: {labels_dir}")
        if args.model is None:
            raise ValueError("--model is required with --sample-dir")
    if has_evaluation_dirs:
        for evaluation_dir in args.from_evaluation_dir:
            if not evaluation_dir.is_dir():
                raise FileNotFoundError(
                    f"evaluation directory not found: {evaluation_dir}"
                )
    if args.model is not None and not args.model.is_file():
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
    if args.expected_clip_count is not None and args.expected_clip_count <= 0:
        raise ValueError("--expected-clip-count must be greater than 0")
    if args.clip_stems:
        normalized_stems = [Path(stem).stem for stem in args.clip_stems]
        duplicate_stems = sorted(
            {stem for stem in normalized_stems if normalized_stems.count(stem) > 1}
        )
        if duplicate_stems:
            raise ValueError(f"duplicate requested clip stems: {duplicate_stems}")
    return args.analysis_id or args.output_dir.name


def matched_video_paths(
    sample_dirs: list[Path],
    clip_stems: list[str] | None,
    expected_clip_count: int | None,
) -> list[Path]:
    requested_stems = [Path(stem).stem for stem in clip_stems or []]
    videos_by_stem: dict[str, Path] = {}
    labels_by_stem: dict[str, Path] = {}
    duplicate_stems: set[str] = set()

    for sample_dir in sample_dirs:
        for path in (sample_dir / "videos").rglob("*.mp4"):
            if requested_stems and path.stem not in requested_stems:
                continue
            if path.stem in videos_by_stem:
                duplicate_stems.add(path.stem)
            videos_by_stem[path.stem] = path
        for path in (sample_dir / "labels").rglob("*.json"):
            if requested_stems and path.stem not in requested_stems:
                continue
            if path.stem in labels_by_stem:
                duplicate_stems.add(path.stem)
            labels_by_stem[path.stem] = path
    if duplicate_stems:
        raise ValueError(f"duplicate media stems across input dirs: {sorted(duplicate_stems)}")

    common_stems = sorted(videos_by_stem.keys() & labels_by_stem.keys())
    if not common_stems:
        raise FileNotFoundError(f"no matched mp4/json pairs under: {sample_dirs}")

    missing_labels = sorted(videos_by_stem.keys() - labels_by_stem.keys())
    missing_videos = sorted(labels_by_stem.keys() - videos_by_stem.keys())
    if missing_labels or missing_videos:
        raise ValueError(
            "unmatched video/label stems: "
            f"missing_labels={missing_labels}, missing_videos={missing_videos}"
        )
    if requested_stems:
        missing_requested = sorted(set(requested_stems) - set(common_stems))
        if missing_requested:
            raise ValueError(f"requested clips not found: {missing_requested}")
        common_stems = requested_stems
    if expected_clip_count is not None and len(common_stems) != expected_clip_count:
        raise ValueError(
            f"expected {expected_clip_count} matched clips, found {len(common_stems)}"
        )
    return [videos_by_stem[stem] for stem in common_stems]


def matched_evaluation_clip_dirs(
    evaluation_dirs: list[Path],
    clip_stems: list[str] | None,
    expected_clip_count: int | None,
) -> list[Path]:
    requested_stems = [Path(stem).stem for stem in clip_stems or []]
    clip_dirs_by_stem: dict[str, Path] = {}
    duplicate_stems: set[str] = set()
    for evaluation_dir in evaluation_dirs:
        if (evaluation_dir / "evaluation_summary.json").is_file():
            candidates = [evaluation_dir]
        else:
            candidates = [
                path
                for path in evaluation_dir.iterdir()
                if path.is_dir() and (path / "evaluation_summary.json").is_file()
            ]
        for clip_dir in candidates:
            if requested_stems and clip_dir.name not in requested_stems:
                continue
            if clip_dir.name in clip_dirs_by_stem:
                duplicate_stems.add(clip_dir.name)
            clip_dirs_by_stem[clip_dir.name] = clip_dir
    if duplicate_stems:
        raise ValueError(
            f"duplicate evaluation clip dirs: {sorted(duplicate_stems)}"
        )

    stems = sorted(clip_dirs_by_stem)
    if requested_stems:
        missing_requested = sorted(set(requested_stems) - set(stems))
        if missing_requested:
            raise ValueError(f"requested evaluation clips not found: {missing_requested}")
        stems = requested_stems
    if not stems:
        raise FileNotFoundError(f"no evaluation clip dirs under: {evaluation_dirs}")
    if expected_clip_count is not None and len(stems) != expected_clip_count:
        raise ValueError(
            f"expected {expected_clip_count} evaluation clips, found {len(stems)}"
        )
    return [clip_dirs_by_stem[stem] for stem in stems]


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


def resolve_repo_path(path_text: str) -> Path:
    path = Path(path_text).expanduser()
    if path.is_absolute():
        return path
    return REPO_ROOT / path


def time_fields(
    video_id: str,
    frame_index: int,
    fps: float,
    bucket_minutes: int,
) -> dict[str, Any]:
    clip_start_time = parse_clip_start_time(video_id)
    timestamp_sec = frame_index / fps
    observed_at = clip_start_time + timedelta(seconds=timestamp_sec)
    time_bucket = floor_time_bucket(observed_at, bucket_minutes)
    return {
        "date_id": observed_at.date().isoformat(),
        "timestamp_ms": int(round(timestamp_sec * 1000)),
        "observed_at": observed_at.isoformat(timespec="seconds"),
        "time_bucket": time_bucket.strftime("%Y-%m-%d %H:%M:%S"),
    }


def build_event_row(
    analysis_id: str,
    video_id: str,
    frame_index: int,
    timing: dict[str, Any],
    xyxy: list[float],
    confidence: float,
    width: int,
    height: int,
    grid_cols: int,
    grid_rows: int,
) -> dict[str, Any]:
    x1, y1, x2, y2 = (float(value) for value in xyxy)
    point_x_norm = ((x1 + x2) / 2.0) / width
    point_y_norm = y2 / height
    point_x_norm = min(1.0, max(0.0, point_x_norm))
    point_y_norm = min(1.0, max(0.0, point_y_norm))
    return {
        "analysis_id": analysis_id,
        "date_id": timing["date_id"],
        "video_id": video_id,
        "frame_index": frame_index,
        "timestamp_ms": timing["timestamp_ms"],
        "observed_at": timing["observed_at"],
        "time_bucket": timing["time_bucket"],
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
            grid_cols=grid_cols,
            grid_rows=grid_rows,
        ),
    }


def build_frame_row(
    analysis_id: str,
    video_id: str,
    frame_index: int,
    timing: dict[str, Any],
    person_detection_count: int,
) -> dict[str, Any]:
    return {
        "analysis_id": analysis_id,
        "date_id": timing["date_id"],
        "video_id": video_id,
        "frame_index": frame_index,
        "timestamp_ms": timing["timestamp_ms"],
        "observed_at": timing["observed_at"],
        "time_bucket": timing["time_bucket"],
        "person_detection_count": int(person_detection_count),
    }


def collect_clip_events(
    model: YOLO,
    video_path: Path,
    analysis_id: str,
    args: argparse.Namespace,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    video_id = video_path.stem
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"failed to open video: {video_path}")

    event_rows: list[dict[str, Any]] = []
    frame_rows: list[dict[str, Any]] = []
    try:
        metadata = video_metadata(cap, video_path)
        sample_step_frames = max(1, round(metadata["fps"] * args.sample_every_sec))
        frame_indices = list(range(0, metadata["frame_count"], sample_step_frames))

        for frame_index in frame_indices:
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
            ok, frame = cap.read()
            if not ok:
                raise RuntimeError(f"failed to read frame={frame_index}: {video_path}")

            timing = time_fields(
                video_id=video_id,
                frame_index=frame_index,
                fps=metadata["fps"],
                bucket_minutes=args.time_bucket_minutes,
            )
            result = model.predict(
                frame,
                classes=[0],
                conf=args.conf,
                device=args.device,
                imgsz=args.imgsz,
                verbose=False,
            )[0]

            if result.boxes is None or len(result.boxes) == 0:
                frame_rows.append(
                    build_frame_row(
                        analysis_id=analysis_id,
                        video_id=video_id,
                        frame_index=frame_index,
                        timing=timing,
                        person_detection_count=0,
                    )
                )
                print(f"video={video_id}, frame={frame_index}, detections=0")
                continue

            xyxy_values = result.boxes.xyxy.cpu().tolist()
            confidence_values = result.boxes.conf.cpu().tolist()
            for xyxy, confidence in zip(xyxy_values, confidence_values):
                event_rows.append(
                    build_event_row(
                        analysis_id=analysis_id,
                        video_id=video_id,
                        frame_index=frame_index,
                        timing=timing,
                        xyxy=xyxy,
                        confidence=float(confidence),
                        width=metadata["width"],
                        height=metadata["height"],
                        grid_cols=args.grid_cols,
                        grid_rows=args.grid_rows,
                    )
                )
            frame_rows.append(
                build_frame_row(
                    analysis_id=analysis_id,
                    video_id=video_id,
                    frame_index=frame_index,
                    timing=timing,
                    person_detection_count=len(xyxy_values),
                )
            )

            print(
                f"video={video_id}, frame={frame_index}, "
                f"detections={len(xyxy_values)}"
            )
    finally:
        cap.release()

    clip_summary = {
        "video_id": video_id,
        "date_id": parse_clip_start_time(video_id).date().isoformat(),
        "source_mode": "fresh_yolo_inference",
        "video": str(video_path),
        "fps": metadata["fps"],
        "frame_count": metadata["frame_count"],
        "width": metadata["width"],
        "height": metadata["height"],
        "sampled_frames": len(frame_indices),
        "person_detection_observations": len(event_rows),
    }
    return event_rows, frame_rows, clip_summary


def collect_evaluation_clip_events(
    clip_dir: Path,
    analysis_id: str,
    args: argparse.Namespace,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    summary_path = clip_dir / "evaluation_summary.json"
    frame_summary_path = clip_dir / "frame_error_summary.csv"
    candidates_path = clip_dir / "prediction_candidates.csv"
    if not frame_summary_path.is_file():
        raise FileNotFoundError(f"frame summary not found: {frame_summary_path}")
    if not candidates_path.is_file():
        raise FileNotFoundError(f"prediction candidates not found: {candidates_path}")

    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    video_path = resolve_repo_path(str(summary["video"]))
    video_id = video_path.stem
    if clip_dir.name != video_id:
        raise ValueError(f"clip dir/video mismatch: {clip_dir.name} != {video_id}")
    inference_floor = summary.get("inference_confidence_floor")
    if inference_floor is not None and float(inference_floor) > args.conf:
        raise ValueError(
            f"{clip_dir} was generated with inference_confidence_floor={inference_floor}, "
            f"which is higher than --conf={args.conf}"
        )

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"failed to open video: {video_path}")
    try:
        metadata = video_metadata(cap, video_path)
    finally:
        cap.release()

    frame_summary = pd.read_csv(frame_summary_path)
    frame_rows_for_threshold = frame_summary.loc[
        (frame_summary["confidence_threshold"] - args.conf).abs() < 1e-9
    ].copy()
    if frame_rows_for_threshold.empty:
        raise ValueError(f"--conf={args.conf} not found in {frame_summary_path}")
    frame_rows_for_threshold = frame_rows_for_threshold.sort_values("frame_index")

    candidates = pd.read_csv(candidates_path)
    selected_candidates = candidates.loc[candidates["confidence"] >= args.conf].copy()
    expected_predictions = int(frame_rows_for_threshold["prediction_count"].sum())
    if len(selected_candidates) != expected_predictions:
        raise ValueError(
            f"prediction count mismatch for {clip_dir}: "
            f"frame_error_summary={expected_predictions}, "
            f"prediction_candidates>={args.conf}={len(selected_candidates)}"
        )

    event_rows: list[dict[str, Any]] = []
    frame_rows: list[dict[str, Any]] = []
    for _, frame_row in frame_rows_for_threshold.iterrows():
        frame_index = int(frame_row["frame_index"])
        timing = time_fields(
            video_id=video_id,
            frame_index=frame_index,
            fps=metadata["fps"],
            bucket_minutes=args.time_bucket_minutes,
        )
        frame_rows.append(
            build_frame_row(
                analysis_id=analysis_id,
                video_id=video_id,
                frame_index=frame_index,
                timing=timing,
                person_detection_count=int(frame_row["prediction_count"]),
            )
        )

    for _, prediction in selected_candidates.iterrows():
        frame_index = int(prediction["frame_index"])
        timing = time_fields(
            video_id=video_id,
            frame_index=frame_index,
            fps=metadata["fps"],
            bucket_minutes=args.time_bucket_minutes,
        )
        event_rows.append(
            build_event_row(
                analysis_id=analysis_id,
                video_id=video_id,
                frame_index=frame_index,
                timing=timing,
                xyxy=[
                    float(prediction["bbox_x1"]),
                    float(prediction["bbox_y1"]),
                    float(prediction["bbox_x2"]),
                    float(prediction["bbox_y2"]),
                ],
                confidence=float(prediction["confidence"]),
                width=metadata["width"],
                height=metadata["height"],
                grid_cols=args.grid_cols,
                grid_rows=args.grid_rows,
            )
        )

    clip_summary = {
        "video_id": video_id,
        "date_id": parse_clip_start_time(video_id).date().isoformat(),
        "source_mode": "l2_3_evaluation_reuse",
        "source_evaluation_dir": str(clip_dir),
        "video": str(video_path),
        "model": summary.get("model"),
        "device": summary.get("device"),
        "imgsz": summary.get("imgsz"),
        "inference_confidence_floor": inference_floor,
        "fps": metadata["fps"],
        "frame_count": metadata["frame_count"],
        "width": metadata["width"],
        "height": metadata["height"],
        "sampled_frames": len(frame_rows),
        "person_detection_observations": len(event_rows),
    }
    return event_rows, frame_rows, clip_summary


def build_events_dataframe(rows: list[dict[str, Any]]) -> pd.DataFrame:
    dataframe = pd.DataFrame(rows, columns=EVENT_COLUMNS)
    if dataframe.empty:
        return dataframe
    dataframe["observed_at"] = pd.to_datetime(dataframe["observed_at"])
    return dataframe


def build_frames_dataframe(rows: list[dict[str, Any]]) -> pd.DataFrame:
    dataframe = pd.DataFrame(rows, columns=FRAME_COLUMNS)
    if dataframe.empty:
        return dataframe
    dataframe["observed_at"] = pd.to_datetime(dataframe["observed_at"])
    dataframe["person_detection_count"] = dataframe[
        "person_detection_count"
    ].astype(int)
    return dataframe


def quantile_95(values: pd.Series) -> float:
    return round(float(values.quantile(0.95)), 6)


def grid_labels(rows: int, cols: int) -> list[str]:
    return [f"r{row}_c{col}" for row in range(rows) for col in range(cols)]


def build_summary_dataframe(
    events: pd.DataFrame,
    frames: pd.DataFrame,
    analysis_id: str,
    grid_cols: int,
    grid_rows: int,
) -> pd.DataFrame:
    if frames.empty:
        return pd.DataFrame(columns=SUMMARY_COLUMNS)

    group_keys = ["analysis_id", "date_id", "time_bucket"]
    frame_base = frames[
        ["analysis_id", "date_id", "time_bucket", "video_id", "frame_index"]
    ].copy()
    zones = pd.DataFrame({"zone_id": grid_labels(rows=grid_rows, cols=grid_cols)})
    frame_zone = frame_base.merge(zones, how="cross")

    if events.empty:
        zone_counts = pd.DataFrame(
            columns=[
                "analysis_id",
                "date_id",
                "time_bucket",
                "video_id",
                "frame_index",
                "zone_id",
                "zone_frame_detection_count",
            ]
        )
    else:
        zone_counts = (
            events.groupby(group_keys + ["video_id", "frame_index", "zone_id"])
            .size()
            .rename("zone_frame_detection_count")
            .reset_index()
        )
    frame_zone = frame_zone.merge(
        zone_counts,
        on=group_keys + ["video_id", "frame_index", "zone_id"],
        how="left",
    )
    frame_zone["zone_frame_detection_count"] = (
        frame_zone["zone_frame_detection_count"].fillna(0).astype(int)
    )

    grouped = (
        frame_zone.groupby(group_keys + ["zone_id"], as_index=False)
        .agg(
            sampled_frame_count=("zone_frame_detection_count", "size"),
            person_detection_observations=("zone_frame_detection_count", "sum"),
            mean_persons_per_sampled_frame=("zone_frame_detection_count", "mean"),
            p95_persons_per_sampled_frame=(
                "zone_frame_detection_count",
                quantile_95,
            ),
            max_persons_per_sampled_frame=("zone_frame_detection_count", "max"),
        )
        .sort_values(["date_id", "time_bucket", "zone_id"])
    )
    grouped["analysis_id"] = analysis_id
    grouped["roi_id"] = "none"
    grouped["in_front_of_shop_observations"] = 0
    grouped["active_person_tracks"] = 0
    grouped["mean_persons_per_sampled_frame"] = grouped[
        "mean_persons_per_sampled_frame"
    ].round(6)
    grouped["max_persons_per_sampled_frame"] = grouped[
        "max_persons_per_sampled_frame"
    ].astype(int)

    max_mean = float(grouped["mean_persons_per_sampled_frame"].max())
    grouped["density_score"] = grouped["mean_persons_per_sampled_frame"].apply(
        lambda value: round(float(value) / max_mean, 6) if max_mean else 0.0
    )
    grouped["hotspot_rank"] = (
        grouped.groupby(["date_id", "time_bucket"])["mean_persons_per_sampled_frame"]
        .rank(method="dense", ascending=False)
        .astype(int)
    )
    grouped["business_gap"] = pd.to_datetime(grouped["time_bucket"]).apply(
        business_gap_label
    )
    grouped["marketing_signal"] = grouped.apply(marketing_signal_label, axis=1)
    return grouped[SUMMARY_COLUMNS]


def business_gap_label(time_bucket: pd.Timestamp) -> str:
    # [Design Intent] 실제 점포 영업시간이 없으므로 임시 rule만 둔다. 사용자 입력
    # 영업시간과 연결되기 전까지는 확정 추천이 아니라 후보 신호다.
    hour = int(time_bucket.hour)
    if hour < 10:
        return "before_default_open_hours"
    if hour >= 21:
        return "late_evening_after_default_peak"
    return "within_default_open_hours"


def marketing_signal_label(row: pd.Series) -> str:
    observations = int(
        row.get(
            "person_detection_observations",
            row.get("total_person_detection_observations", 0),
        )
    )
    gap = str(row["business_gap"])
    if observations <= 0:
        return "no_observation"
    if gap == "before_default_open_hours":
        return "morning_promotion_candidate"
    if gap == "late_evening_after_default_peak":
        return "evening_takeout_or_signage_candidate"
    return "storefront_visibility_candidate"


def build_dashboard_summary(summary: pd.DataFrame, frames: pd.DataFrame) -> pd.DataFrame:
    if frames.empty:
        return pd.DataFrame(
            columns=[
                "date_id",
                "time_bucket",
                "sampled_frame_count",
                "total_person_detection_observations",
                "mean_persons_per_sampled_frame",
                "p95_persons_per_sampled_frame",
                "max_persons_per_sampled_frame",
                "relative_crowding_score",
                "top_zone_id",
                "top_zone_observations",
                "top_zone_mean_persons_per_sampled_frame",
                "marketing_signal",
            ]
        )

    group_keys = ["date_id", "time_bucket"]
    if summary.empty:
        top_zones = pd.DataFrame(
            columns=[
                "date_id",
                "time_bucket",
                "top_zone_id",
                "top_zone_observations",
                "top_zone_mean_persons_per_sampled_frame",
            ]
        )
    else:
        idx = summary.groupby(group_keys)["mean_persons_per_sampled_frame"].idxmax()
        top_zones = summary.loc[
            idx,
            [
                "date_id",
                "time_bucket",
                "zone_id",
                "person_detection_observations",
                "mean_persons_per_sampled_frame",
            ],
        ].rename(
            columns={
                "zone_id": "top_zone_id",
                "person_detection_observations": "top_zone_observations",
                "mean_persons_per_sampled_frame": (
                    "top_zone_mean_persons_per_sampled_frame"
                ),
            }
        )
    totals = (
        frames.groupby(group_keys, as_index=False)
        .agg(
            sampled_frame_count=("person_detection_count", "size"),
            total_person_detection_observations=(
                "person_detection_count",
                "sum",
            ),
            mean_persons_per_sampled_frame=("person_detection_count", "mean"),
            p95_persons_per_sampled_frame=("person_detection_count", quantile_95),
            max_persons_per_sampled_frame=("person_detection_count", "max"),
        )
        .sort_values(["date_id", "time_bucket"])
    )
    totals["mean_persons_per_sampled_frame"] = totals[
        "mean_persons_per_sampled_frame"
    ].round(6)
    totals["business_gap"] = pd.to_datetime(totals["time_bucket"]).apply(
        business_gap_label
    )
    totals["marketing_signal"] = totals.apply(marketing_signal_label, axis=1)
    max_mean = float(totals["mean_persons_per_sampled_frame"].max())
    totals["relative_crowding_score"] = totals[
        "mean_persons_per_sampled_frame"
    ].apply(lambda value: round(float(value) / max_mean, 6) if max_mean else 0.0)
    dashboard = totals.merge(top_zones, on=group_keys, how="left")
    return dashboard[
        [
            "date_id",
            "time_bucket",
            "sampled_frame_count",
            "total_person_detection_observations",
            "mean_persons_per_sampled_frame",
            "p95_persons_per_sampled_frame",
            "max_persons_per_sampled_frame",
            "relative_crowding_score",
            "top_zone_id",
            "top_zone_observations",
            "top_zone_mean_persons_per_sampled_frame",
            "marketing_signal",
        ]
    ]


def build_analysis_json(
    args: argparse.Namespace,
    analysis_id: str,
    clip_summaries: list[dict[str, Any]],
    events: pd.DataFrame,
    frames: pd.DataFrame,
    dashboard_summary: pd.DataFrame,
) -> dict[str, Any]:
    total_observations = int(len(events))
    if dashboard_summary.empty:
        peak_date_id = None
        peak_bucket = None
        peak_mean = 0.0
        peak_p95 = 0.0
        peak_max = 0
        top_zone = None
        peak_bucket_observations = 0
        top_zone_observations = 0
        top_zone_mean = 0.0
    else:
        peak_bucket_row = dashboard_summary.sort_values(
            ["mean_persons_per_sampled_frame", "date_id", "time_bucket"],
            ascending=[False, True, True],
        ).iloc[0]
        peak_date_id = str(peak_bucket_row["date_id"])
        peak_bucket = str(peak_bucket_row["time_bucket"])
        peak_mean = float(peak_bucket_row["mean_persons_per_sampled_frame"])
        peak_p95 = float(peak_bucket_row["p95_persons_per_sampled_frame"])
        peak_max = int(peak_bucket_row["max_persons_per_sampled_frame"])
        peak_bucket_observations = int(
            peak_bucket_row["total_person_detection_observations"]
        )
        top_zone = str(peak_bucket_row["top_zone_id"])
        top_zone_observations = int(peak_bucket_row["top_zone_observations"])
        top_zone_mean = float(
            peak_bucket_row["top_zone_mean_persons_per_sampled_frame"]
        )

    sample_dirs = [str(path) for path in args.sample_dir or []]
    evaluation_dirs = [str(path) for path in args.from_evaluation_dir or []]
    source_videos = [str(item.get("video", "")) for item in clip_summaries]
    source_model = str(args.model) if args.model is not None else None
    source_device = str(args.device)
    source_imgsz = int(args.imgsz)
    if args.from_evaluation_dir and clip_summaries:
        source_model = str(clip_summaries[0].get("model"))
        source_device = str(clip_summaries[0].get("device"))
        source_imgsz = int(clip_summaries[0].get("imgsz", args.imgsz))

    return {
        "analysis_id": analysis_id,
        "scope": "L2-4_frame_normalized_two_date_dashboard_artifacts",
        "source_mode": (
            "l2_3_evaluation_reuse"
            if args.from_evaluation_dir
            else "fresh_yolo_inference"
        ),
        "sample_dirs": sample_dirs,
        "evaluation_dirs": evaluation_dirs,
        "source_videos": source_videos,
        "model": source_model,
        "device": source_device,
        "imgsz": source_imgsz,
        "aggregation_device": "cpu",
        "confidence_threshold": args.conf,
        "sample_every_sec": args.sample_every_sec,
        "grid": {"cols": args.grid_cols, "rows": args.grid_rows},
        "time_bucket_minutes": args.time_bucket_minutes,
        "clip_count": len(clip_summaries),
        "sampled_frames": int(len(frames)),
        "person_detection_observations": total_observations,
        "primary_comparison_metric": "mean_persons_per_sampled_frame",
        "peak_date_id": peak_date_id,
        "peak_time_bucket": peak_bucket,
        "peak_time_bucket_observations": peak_bucket_observations,
        "peak_mean_persons_per_sampled_frame": round(peak_mean, 6),
        "peak_p95_persons_per_sampled_frame": round(peak_p95, 6),
        "peak_max_persons_per_sampled_frame": peak_max,
        "top_zone_id": top_zone,
        "top_zone_observations": top_zone_observations,
        "top_zone_mean_persons_per_sampled_frame": round(top_zone_mean, 6),
        "date_summary": (
            dashboard_summary.groupby("date_id", as_index=False)
            .agg(
                sampled_frame_count=("sampled_frame_count", "sum"),
                total_person_detection_observations=(
                    "total_person_detection_observations",
                    "sum",
                ),
            )
            .assign(
                mean_persons_per_sampled_frame=lambda frame: (
                    frame["total_person_detection_observations"]
                    / frame["sampled_frame_count"]
                ).round(6)
            )
            .to_dict(orient="records")
            if not dashboard_summary.empty
            else []
        ),
        "artifacts": {
            "events_parquet": str(args.output_dir / "events.parquet"),
            "frames_parquet": str(args.output_dir / "frames.parquet"),
            "summary_parquet": str(args.output_dir / "summary.parquet"),
            "analysis_json": str(args.output_dir / "analysis.json"),
            "dashboard_summary_csv": str(args.output_dir / "dashboard_summary.csv"),
        },
        "clip_summaries": clip_summaries,
        "limitations": [
            "Counts are frame-level person bbox observations, not unique visitors.",
            "Tracking is not used in L2, so repeated appearances of the same person are counted repeatedly.",
            "Grid zones are screen-space buckets, not real ground-plane coordinates.",
            "ROI counting is not enabled in L2; roi_id remains none and is_in_front_of_shop remains false.",
            "Marketing signals are rule-based hypotheses for dashboard validation, not verified business outcomes.",
            "Frame-normalized metrics include zero-detection sampled frames in the denominator.",
        ],
    }


def main() -> None:
    args = parse_args()
    analysis_id = validate_args(args)
    args.output_dir.mkdir(parents=True, exist_ok=True)

    all_event_rows: list[dict[str, Any]] = []
    all_frame_rows: list[dict[str, Any]] = []
    clip_summaries: list[dict[str, Any]] = []
    if args.from_evaluation_dir:
        clip_dirs = matched_evaluation_clip_dirs(
            evaluation_dirs=args.from_evaluation_dir,
            clip_stems=args.clip_stems,
            expected_clip_count=args.expected_clip_count,
        )
        for clip_dir in clip_dirs:
            print(f"[L2-4] reusing evaluation clip={clip_dir.name}")
            event_rows, frame_rows, clip_summary = collect_evaluation_clip_events(
                clip_dir=clip_dir,
                analysis_id=analysis_id,
                args=args,
            )
            all_event_rows.extend(event_rows)
            all_frame_rows.extend(frame_rows)
            clip_summaries.append(clip_summary)
    else:
        video_paths = matched_video_paths(
            sample_dirs=args.sample_dir,
            clip_stems=args.clip_stems,
            expected_clip_count=args.expected_clip_count,
        )
        model = YOLO(str(args.model))
        for video_path in video_paths:
            print(f"[L2] processing video={video_path.name}")
            event_rows, frame_rows, clip_summary = collect_clip_events(
                model=model,
                video_path=video_path,
                analysis_id=analysis_id,
                args=args,
            )
            all_event_rows.extend(event_rows)
            all_frame_rows.extend(frame_rows)
            clip_summaries.append(clip_summary)

    events = build_events_dataframe(all_event_rows)
    frames = build_frames_dataframe(all_frame_rows)
    summary = build_summary_dataframe(
        events=events,
        frames=frames,
        analysis_id=analysis_id,
        grid_cols=args.grid_cols,
        grid_rows=args.grid_rows,
    )
    dashboard_summary = build_dashboard_summary(summary=summary, frames=frames)
    analysis = build_analysis_json(
        args=args,
        analysis_id=analysis_id,
        clip_summaries=clip_summaries,
        events=events,
        frames=frames,
        dashboard_summary=dashboard_summary,
    )

    events.to_parquet(args.output_dir / "events.parquet", index=False)
    frames.to_parquet(args.output_dir / "frames.parquet", index=False)
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
    print(f"primary_comparison_metric={analysis['primary_comparison_metric']}")
    print(f"peak_date_id={analysis['peak_date_id']}")
    print(f"peak_time_bucket={analysis['peak_time_bucket']}")
    print(
        "peak_mean_persons_per_sampled_frame="
        f"{analysis['peak_mean_persons_per_sampled_frame']}"
    )
    print(f"top_zone_id={analysis['top_zone_id']}")
    print(f"output_dir={args.output_dir}")


if __name__ == "__main__":
    main()
