#!/usr/bin/env python3
"""Aggregate L3-5 line-crossing events from clip-local track events."""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import pandas as pd


# [Design Intent] L3-5 must not rerun YOLO or ByteTrack. It consumes L3-4
# track_events.csv and a manual normalized crossing line, so operators can
# adjust line definitions without paying GPU inference cost again.
REPO_ROOT = Path(__file__).resolve().parents[1]
OUTPUTS_ROOT = REPO_ROOT / "outputs"
TRACK_EVENTS_PATH = Path("tracks") / "track_events.csv"
TRACKING_SUMMARY_PATH = Path("qa") / "tracking_qa_summary.json"
TRACKING_VIDEO_PATH = Path("media") / "tracking_id_qa.webm"
CROSSING_EVENTS_PATH = Path("crossings") / "crossing_events.csv"
CROSSING_SUMMARY_PATH = Path("qa") / "crossing_summary.json"
CROSSING_QA_VIDEO_PATH = Path("media") / "line_crossing_qa.webm"

TRACK_EVENT_REQUIRED_COLUMNS = {
    "source_frame_index",
    "clip_frame_index",
    "timestamp_sec",
    "track_id",
    "confidence",
    "bottom_center_x",
    "bottom_center_y",
    "is_in_roi",
}

CROSSING_EVENT_COLUMNS = [
    "event_index",
    "track_id",
    "line_id",
    "direction_key",
    "event_label",
    "crossing_clip_frame_index",
    "crossing_source_frame_index",
    "crossing_timestamp_sec",
    "previous_clip_frame_index",
    "current_clip_frame_index",
    "previous_signed_distance_px",
    "current_signed_distance_px",
    "intersection_x",
    "intersection_y",
    "intersection_x_norm",
    "intersection_y_norm",
    "confidence_before",
    "confidence_after",
    "previous_is_in_roi",
    "current_is_in_roi",
]


@dataclass(frozen=True)
class Point:
    x: float
    y: float


@dataclass(frozen=True)
class CrossingLine:
    start: Point
    end: Point


@dataclass(frozen=True)
class TrackPoint:
    track_id: int
    source_frame_index: int
    clip_frame_index: int
    timestamp_sec: float
    confidence: float
    point: Point
    is_in_roi: bool


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Compute L3-5 crossing events from L3-4 track_events.csv and render "
            "an optional operator QA WebM."
        )
    )
    parser.add_argument(
        "--tracking-dir",
        required=True,
        type=Path,
        help="L3-4 tracking QA output directory.",
    )
    parser.add_argument(
        "--crossing-config",
        required=True,
        type=Path,
        help="Manual crossing line config JSON.",
    )
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument(
        "--line-margin-px",
        default=3.0,
        type=float,
        help="Signed distance around the line treated as neutral jitter band.",
    )
    parser.add_argument(
        "--min-event-gap-frames",
        default=6,
        type=int,
        help="Minimum frame gap before the same track can emit another crossing.",
    )
    parser.add_argument(
        "--skip-video",
        action="store_true",
        help="Write CSV/JSON only and skip line_crossing_qa.webm rendering.",
    )
    return parser.parse_args()


def resolve_repo_path(path: Path) -> Path:
    path = path.expanduser()
    if path.is_absolute():
        return path.resolve()
    return (REPO_ROOT / path).resolve()


def validate_output_dir(output_dir: Path) -> None:
    try:
        output_dir.relative_to(OUTPUTS_ROOT.resolve())
    except ValueError as error:
        raise ValueError("L3-5 line crossing output must be under outputs/.") from error


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def validate_crossing_config(config: dict[str, Any]) -> None:
    required_keys = {
        "camera_id",
        "primary_line_id",
        "coordinate_space",
        "position_point",
        "definition_source",
        "line",
        "direction_labels",
    }
    missing = sorted(required_keys - set(config))
    if missing:
        raise ValueError(f"crossing config missing keys: {missing}")
    if config["coordinate_space"] != "normalized_image":
        raise ValueError("coordinate_space must be normalized_image")
    if config["position_point"] != "bbox_bottom_center":
        raise ValueError("position_point must be bbox_bottom_center")
    if config["definition_source"] != "manual_line":
        raise ValueError("definition_source must be manual_line")
    raw_line = config["line"]
    if not isinstance(raw_line, list) or len(raw_line) != 2:
        raise ValueError("line must contain exactly two points")
    for index, point in enumerate(raw_line):
        if not isinstance(point, dict) or not {"x", "y"} <= set(point):
            raise ValueError(f"line[{index}] must contain x and y")
        x = float(point["x"])
        y = float(point["y"])
        if not 0.0 <= x <= 1.0 or not 0.0 <= y <= 1.0:
            raise ValueError(f"line[{index}] must be inside normalized range 0..1")
    labels = config["direction_labels"]
    if not {"negative_to_positive", "positive_to_negative"} <= set(labels):
        raise ValueError("direction_labels must define both crossing directions")


def line_pixels(config: dict[str, Any], *, width: int, height: int) -> CrossingLine:
    validate_crossing_config(config)
    raw_start, raw_end = config["line"]
    start = Point(float(raw_start["x"]) * width, float(raw_start["y"]) * height)
    end = Point(float(raw_end["x"]) * width, float(raw_end["y"]) * height)
    if math.hypot(end.x - start.x, end.y - start.y) <= 1e-9:
        raise ValueError("line endpoints must not be identical")
    return CrossingLine(start=start, end=end)


def signed_distance_to_line(point: Point, line: CrossingLine) -> float:
    dx = line.end.x - line.start.x
    dy = line.end.y - line.start.y
    length = math.hypot(dx, dy)
    cross = dx * (point.y - line.start.y) - dy * (point.x - line.start.x)
    return cross / length


def side_of_line(point: Point, line: CrossingLine, *, margin_px: float) -> int:
    distance = signed_distance_to_line(point, line)
    if abs(distance) <= margin_px:
        return 0
    return 1 if distance > 0 else -1


def segment_intersection(
    previous: Point,
    current: Point,
    line: CrossingLine,
) -> Point | None:
    rx = current.x - previous.x
    ry = current.y - previous.y
    sx = line.end.x - line.start.x
    sy = line.end.y - line.start.y
    denominator = rx * sy - ry * sx
    if abs(denominator) <= 1e-9:
        return None

    qpx = line.start.x - previous.x
    qpy = line.start.y - previous.y
    t = (qpx * sy - qpy * sx) / denominator
    u = (qpx * ry - qpy * rx) / denominator
    if not 0.0 <= t <= 1.0 or not 0.0 <= u <= 1.0:
        return None
    return Point(previous.x + t * rx, previous.y + t * ry)


def bool_from_value(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and not pd.isna(value):
        return bool(value)
    return str(value).strip().lower() in {"true", "1", "yes", "y"}


def load_track_events(path: Path) -> pd.DataFrame:
    events = pd.read_csv(path)
    missing = sorted(TRACK_EVENT_REQUIRED_COLUMNS - set(events.columns))
    if missing:
        raise ValueError(f"track events missing columns: {missing}")
    events = events.copy()
    events = events[events["track_id"].notna()]
    events = events[events["track_id"].astype(str).str.strip() != ""]
    numeric_columns = [
        "source_frame_index",
        "clip_frame_index",
        "timestamp_sec",
        "track_id",
        "confidence",
        "bottom_center_x",
        "bottom_center_y",
    ]
    for column in numeric_columns:
        events[column] = pd.to_numeric(events[column], errors="raise")
    events["track_id"] = events["track_id"].astype(int)
    events["source_frame_index"] = events["source_frame_index"].astype(int)
    events["clip_frame_index"] = events["clip_frame_index"].astype(int)
    events["is_in_roi"] = events["is_in_roi"].map(bool_from_value)
    return events.sort_values(["track_id", "clip_frame_index"]).reset_index(drop=True)


def track_point_from_row(row: pd.Series) -> TrackPoint:
    return TrackPoint(
        track_id=int(row["track_id"]),
        source_frame_index=int(row["source_frame_index"]),
        clip_frame_index=int(row["clip_frame_index"]),
        timestamp_sec=float(row["timestamp_sec"]),
        confidence=float(row["confidence"]),
        point=Point(float(row["bottom_center_x"]), float(row["bottom_center_y"])),
        is_in_roi=bool_from_value(row["is_in_roi"]),
    )


def crossing_event_row(
    *,
    event_index: int,
    previous: TrackPoint,
    current: TrackPoint,
    line_id: str,
    direction_key: str,
    event_label: str,
    intersection: Point,
    previous_distance: float,
    current_distance: float,
    width: int,
    height: int,
) -> dict[str, Any]:
    return {
        "event_index": event_index,
        "track_id": current.track_id,
        "line_id": line_id,
        "direction_key": direction_key,
        "event_label": event_label,
        "crossing_clip_frame_index": current.clip_frame_index,
        "crossing_source_frame_index": current.source_frame_index,
        "crossing_timestamp_sec": round(current.timestamp_sec, 6),
        "previous_clip_frame_index": previous.clip_frame_index,
        "current_clip_frame_index": current.clip_frame_index,
        "previous_signed_distance_px": round(previous_distance, 3),
        "current_signed_distance_px": round(current_distance, 3),
        "intersection_x": round(intersection.x, 3),
        "intersection_y": round(intersection.y, 3),
        "intersection_x_norm": round(intersection.x / width, 6),
        "intersection_y_norm": round(intersection.y / height, 6),
        "confidence_before": round(previous.confidence, 6),
        "confidence_after": round(current.confidence, 6),
        "previous_is_in_roi": previous.is_in_roi,
        "current_is_in_roi": current.is_in_roi,
    }


def detect_crossing_events(
    events: pd.DataFrame,
    line: CrossingLine,
    config: dict[str, Any],
    *,
    width: int,
    height: int,
    line_margin_px: float,
    min_event_gap_frames: int,
) -> list[dict[str, Any]]:
    labels = config["direction_labels"]
    line_id = str(config["primary_line_id"])
    crossing_rows: list[dict[str, Any]] = []
    next_event_index = 1

    for track_id, track_rows in events.groupby("track_id", sort=True):
        last_non_neutral: TrackPoint | None = None
        last_non_neutral_side = 0
        last_event_frame: int | None = None

        for _, row in track_rows.sort_values("clip_frame_index").iterrows():
            current = track_point_from_row(row)
            current_side = side_of_line(
                current.point,
                line,
                margin_px=line_margin_px,
            )
            if current_side == 0:
                continue
            if last_non_neutral is None:
                last_non_neutral = current
                last_non_neutral_side = current_side
                continue
            if current_side == last_non_neutral_side:
                last_non_neutral = current
                continue
            if (
                last_event_frame is not None
                and current.clip_frame_index - last_event_frame < min_event_gap_frames
            ):
                last_non_neutral = current
                last_non_neutral_side = current_side
                continue

            intersection = segment_intersection(
                last_non_neutral.point,
                current.point,
                line,
            )
            if intersection is None:
                last_non_neutral = current
                last_non_neutral_side = current_side
                continue

            direction_key = (
                "negative_to_positive"
                if last_non_neutral_side < 0 and current_side > 0
                else "positive_to_negative"
            )
            crossing_rows.append(
                crossing_event_row(
                    event_index=next_event_index,
                    previous=last_non_neutral,
                    current=current,
                    line_id=line_id,
                    direction_key=direction_key,
                    event_label=str(labels[direction_key]),
                    intersection=intersection,
                    previous_distance=signed_distance_to_line(
                        last_non_neutral.point,
                        line,
                    ),
                    current_distance=signed_distance_to_line(current.point, line),
                    width=width,
                    height=height,
                )
            )
            next_event_index += 1
            last_event_frame = current.clip_frame_index
            last_non_neutral = current
            last_non_neutral_side = current_side

    crossing_rows.sort(
        key=lambda row: (
            int(row["crossing_clip_frame_index"]),
            int(row["track_id"]),
            float(row["intersection_x"]),
        )
    )
    for index, row in enumerate(crossing_rows, start=1):
        row["event_index"] = index

    return crossing_rows


def build_crossing_summary(
    *,
    crossing_rows: list[dict[str, Any]],
    track_events: pd.DataFrame,
    tracking_summary: dict[str, Any],
    crossing_config: dict[str, Any],
    output_dir: Path,
    track_events_path: Path,
    tracking_summary_path: Path,
    crossing_config_path: Path,
    qa_video_path: Path | None,
    line_margin_px: float,
    min_event_gap_frames: int,
) -> dict[str, Any]:
    event_counts = {
        str(label): 0
        for label in crossing_config.get("direction_labels", {}).values()
    }
    for row in crossing_rows:
        event_counts[str(row["event_label"])] = (
            event_counts.get(str(row["event_label"]), 0) + 1
        )
    return {
        "schema_version": 1,
        "stage": "L3-5_line_crossing_direction_events",
        "storage_stage": "experimental_candidate",
        "camera_id": crossing_config["camera_id"],
        "line_id": crossing_config["primary_line_id"],
        "label": crossing_config.get("label", ""),
        "settings": {
            "line_margin_px": line_margin_px,
            "min_event_gap_frames": min_event_gap_frames,
            "position_point": crossing_config["position_point"],
            "direction_labels": crossing_config["direction_labels"],
        },
        "inputs": {
            "track_events_csv": str(track_events_path),
            "tracking_qa_summary": str(tracking_summary_path),
            "crossing_config": str(crossing_config_path),
        },
        "source_tracking": {
            "source_video": tracking_summary.get("source_video"),
            "roi_id": tracking_summary.get("roi_id"),
            "tracker": tracking_summary.get("settings", {}).get("tracker"),
            "confidence_threshold": tracking_summary.get("settings", {}).get(
                "confidence_threshold"
            ),
            "processed_frames": tracking_summary.get("results", {}).get(
                "processed_frames"
            ),
            "source_fps": tracking_summary.get("results", {}).get("source_fps"),
        },
        "results": {
            "input_track_observations": int(len(track_events)),
            "input_unique_track_ids": int(track_events["track_id"].nunique()),
            "total_crossing_events": len(crossing_rows),
            "direction_event_counts": event_counts,
            "unique_track_ids_crossed": len(
                {int(row["track_id"]) for row in crossing_rows}
            ),
            "crossing_clip_frame_indices": [
                int(row["crossing_clip_frame_index"]) for row in crossing_rows
            ],
        },
        "artifacts": {
            "crossing_events_csv": str(output_dir / CROSSING_EVENTS_PATH),
            "crossing_summary": str(output_dir / CROSSING_SUMMARY_PATH),
            "line_crossing_qa_video": None if qa_video_path is None else str(qa_video_path),
        },
        "qa_policy": {
            "manual_review_required": True,
            "review_focus": [
                "whether track trajectories visibly cross the red manual line",
                "whether upward/downward labels match the camera view",
                "duplicate events caused by ID switches or line-edge jitter",
                "missed events caused by occlusion or fragmented tracks",
            ],
        },
        "limitations": [
            "Line crossing counts are movement events inside the analyzed clip, not unique visitors.",
            "The current C0241 L3-5 line is for screen upward/downward walkway flow, not store entry or exit.",
            "If a track ID switches near the line, crossing events may be duplicated or missed.",
            "This result must not be expanded to daily traffic without full continuous footage and manual count validation.",
        ],
    }


def create_video_writer(path: Path, *, fps: float, width: int, height: int) -> cv2.VideoWriter:
    path.parent.mkdir(parents=True, exist_ok=True)
    writer = cv2.VideoWriter(
        str(path),
        cv2.VideoWriter_fourcc(*"VP80"),
        fps,
        (width, height),
    )
    if not writer.isOpened():
        raise RuntimeError(f"failed to open WebM writer: {path}")
    return writer


def draw_line(frame: np.ndarray, line: CrossingLine, line_id: str) -> None:
    start = (round(line.start.x), round(line.start.y))
    end = (round(line.end.x), round(line.end.y))
    cv2.line(frame, start, end, (0, 0, 255), 5, cv2.LINE_AA)
    label = f"L3-5 Line Crossing QA | {line_id} | operator only"
    cv2.rectangle(frame, (12, 58), (720, 104), (20, 20, 20), -1)
    cv2.putText(
        frame,
        label,
        (24, 88),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.78,
        (255, 255, 255),
        2,
        cv2.LINE_AA,
    )


def draw_crossing_footer(
    frame: np.ndarray,
    *,
    cumulative_counts: dict[str, int],
    frame_events: list[dict[str, Any]],
) -> None:
    height, width = frame.shape[:2]
    cv2.rectangle(frame, (0, height - 64), (width, height), (0, 0, 0), -1)
    count_text = " | ".join(
        f"{label}={count}" for label, count in sorted(cumulative_counts.items())
    )
    if not count_text:
        count_text = "no crossing events"
    footer = f"line-crossing events: {count_text} | movement events, not unique people"
    cv2.putText(
        frame,
        footer,
        (24, height - 24),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.72,
        (255, 255, 255),
        2,
        cv2.LINE_AA,
    )
    for row in frame_events:
        point = (round(float(row["intersection_x"])), round(float(row["intersection_y"])))
        cv2.circle(frame, point, 12, (0, 0, 255), -1, cv2.LINE_AA)
        cv2.putText(
            frame,
            str(row["event_label"]),
            (point[0] + 14, point[1] - 10),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            (0, 0, 255),
            2,
            cv2.LINE_AA,
        )


def render_qa_video(
    *,
    tracking_video_path: Path,
    output_path: Path,
    crossing_rows: list[dict[str, Any]],
    crossing_config: dict[str, Any],
) -> None:
    cap = cv2.VideoCapture(str(tracking_video_path))
    if not cap.isOpened():
        raise RuntimeError(f"failed to open tracking QA video: {tracking_video_path}")
    fps = float(cap.get(cv2.CAP_PROP_FPS))
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    if fps <= 0 or width <= 0 or height <= 0:
        cap.release()
        raise RuntimeError(
            f"invalid tracking QA video metadata: fps={fps}, size={width}x{height}"
        )

    crossing_line = line_pixels(crossing_config, width=width, height=height)
    writer = create_video_writer(output_path, fps=fps, width=width, height=height)
    events_by_frame: dict[int, list[dict[str, Any]]] = {}
    for row in crossing_rows:
        events_by_frame.setdefault(int(row["crossing_clip_frame_index"]), []).append(row)

    cumulative_counts = {
        str(label): 0
        for label in crossing_config.get("direction_labels", {}).values()
    }
    frame_index = 0
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            frame_events = events_by_frame.get(frame_index, [])
            for row in frame_events:
                label = str(row["event_label"])
                cumulative_counts[label] = cumulative_counts.get(label, 0) + 1
            draw_line(
                frame,
                line=crossing_line,
                line_id=str(crossing_config["primary_line_id"]),
            )
            draw_crossing_footer(
                frame,
                cumulative_counts=cumulative_counts,
                frame_events=frame_events,
            )
            writer.write(frame)
            frame_index += 1
    finally:
        cap.release()
        writer.release()


def write_crossing_events(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows, columns=CROSSING_EVENT_COLUMNS).to_csv(path, index=False)


def main() -> None:
    args = parse_args()
    tracking_dir = resolve_repo_path(args.tracking_dir)
    crossing_config_path = resolve_repo_path(args.crossing_config)
    output_dir = resolve_repo_path(args.output_dir)
    validate_output_dir(output_dir)
    if args.line_margin_px < 0:
        raise ValueError("--line-margin-px must be 0 or greater")
    if args.min_event_gap_frames < 0:
        raise ValueError("--min-event-gap-frames must be 0 or greater")

    track_events_path = tracking_dir / TRACK_EVENTS_PATH
    tracking_summary_path = tracking_dir / TRACKING_SUMMARY_PATH
    tracking_video_path = tracking_dir / TRACKING_VIDEO_PATH
    for label, path in (
        ("track events", track_events_path),
        ("tracking summary", tracking_summary_path),
        ("crossing config", crossing_config_path),
    ):
        if not path.is_file():
            raise FileNotFoundError(f"{label} not found: {path}")

    track_events = load_track_events(track_events_path)
    tracking_summary = load_json(tracking_summary_path)
    crossing_config = load_json(crossing_config_path)
    validate_crossing_config(crossing_config)
    width = int(tracking_summary["results"]["width"])
    height = int(tracking_summary["results"]["height"])
    crossing_line = line_pixels(crossing_config, width=width, height=height)

    crossing_rows = detect_crossing_events(
        track_events,
        crossing_line,
        crossing_config,
        width=width,
        height=height,
        line_margin_px=args.line_margin_px,
        min_event_gap_frames=args.min_event_gap_frames,
    )

    crossing_events_output = output_dir / CROSSING_EVENTS_PATH
    crossing_summary_output = output_dir / CROSSING_SUMMARY_PATH
    qa_video_output = None if args.skip_video else output_dir / CROSSING_QA_VIDEO_PATH
    write_crossing_events(crossing_events_output, crossing_rows)
    if qa_video_output is not None:
        if not tracking_video_path.is_file():
            raise FileNotFoundError(f"tracking QA video not found: {tracking_video_path}")
        render_qa_video(
            tracking_video_path=tracking_video_path,
            output_path=qa_video_output,
            crossing_rows=crossing_rows,
            crossing_config=crossing_config,
        )

    summary = build_crossing_summary(
        crossing_rows=crossing_rows,
        track_events=track_events,
        tracking_summary=tracking_summary,
        crossing_config=crossing_config,
        output_dir=output_dir,
        track_events_path=track_events_path,
        tracking_summary_path=tracking_summary_path,
        crossing_config_path=crossing_config_path,
        qa_video_path=qa_video_output,
        line_margin_px=args.line_margin_px,
        min_event_gap_frames=args.min_event_gap_frames,
    )
    crossing_summary_output.parent.mkdir(parents=True, exist_ok=True)
    crossing_summary_output.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    print(f"track_events={track_events_path}")
    print(f"crossing_config={crossing_config_path}")
    print(f"output_dir={output_dir}")
    print(f"input_track_observations={len(track_events)}")
    print(f"input_unique_track_ids={track_events['track_id'].nunique()}")
    print(f"total_crossing_events={len(crossing_rows)}")
    for label, count in summary["results"]["direction_event_counts"].items():
        print(f"{label}={count}")
    print(f"crossing_events_csv={crossing_events_output}")
    print(f"crossing_summary={crossing_summary_output}")
    if qa_video_output is not None:
        print(f"line_crossing_qa_video={qa_video_output}")


if __name__ == "__main__":
    main()
