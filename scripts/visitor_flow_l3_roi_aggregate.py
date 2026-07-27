#!/usr/bin/env python3
"""Apply a manual camera ROI to existing L2 visitor-flow artifacts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import pandas as pd


# [Design Intent] L3-1 is a deterministic CPU post-processing stage. It reuses
# L2 bbox observations so ROI changes do not trigger YOLO inference again.
REPO_ROOT = Path(__file__).resolve().parents[1]

REQUIRED_L2_FILES = {
    "analysis": "analysis.json",
    "events": "events.parquet",
    "frames": "frames.parquet",
}

REQUIRED_EVENT_COLUMNS = {
    "analysis_id",
    "date_id",
    "video_id",
    "frame_index",
    "time_bucket",
    "bbox_x1",
    "bbox_y1",
    "bbox_x2",
    "bbox_y2",
    "point_x_norm",
    "point_y_norm",
}

REQUIRED_FRAME_COLUMNS = {
    "analysis_id",
    "date_id",
    "video_id",
    "frame_index",
    "time_bucket",
    "person_detection_count",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Apply a manual normalized polygon to L2 bbox observations and create "
            "L3-1 ROI event, frame, summary, analysis, and overlay artifacts."
        )
    )
    parser.add_argument("--input-dir", required=True, type=Path)
    parser.add_argument("--roi-config", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument(
        "--analysis-id",
        default="",
        help="Stable L3 analysis id. Defaults to the output directory name.",
    )
    parser.add_argument(
        "--preview-video-id",
        default="",
        help="Optional clip stem for the overlay. Defaults to the busiest ROI frame.",
    )
    parser.add_argument(
        "--preview-frame-index",
        type=int,
        default=None,
        help="Optional sampled frame index for the overlay.",
    )
    return parser.parse_args()


def resolve_repo_path(path: Path) -> Path:
    path = path.expanduser()
    if path.is_absolute():
        return path
    return REPO_ROOT / path


def polygon_area(polygon: list[tuple[float, float]]) -> float:
    return (
        abs(
            sum(
                x1 * y2 - x2 * y1
                for (x1, y1), (x2, y2) in zip(
                    polygon,
                    polygon[1:] + polygon[:1],
                )
            )
        )
        / 2.0
    )


def load_roi_config(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"ROI config not found: {path}")
    config = json.loads(path.read_text(encoding="utf-8"))
    required = {
        "schema_version",
        "camera_id",
        "primary_roi_id",
        "coordinate_space",
        "position_point",
        "definition_source",
        "boundary_inclusive",
        "polygon",
    }
    missing = sorted(required - set(config))
    if missing:
        raise ValueError(f"ROI config is missing fields: {missing}")
    if config["coordinate_space"] != "normalized_image":
        raise ValueError("coordinate_space must be normalized_image")
    if config["position_point"] != "bbox_bottom_center":
        raise ValueError("position_point must be bbox_bottom_center")
    if config["definition_source"] != "manual_polygon":
        raise ValueError("definition_source must be manual_polygon")
    if config["boundary_inclusive"] is not True:
        raise ValueError("L3-1 requires boundary_inclusive=true")

    raw_polygon = config["polygon"]
    if not isinstance(raw_polygon, list) or len(raw_polygon) < 3:
        raise ValueError("polygon must contain at least three points")
    polygon: list[tuple[float, float]] = []
    for index, point in enumerate(raw_polygon):
        if not isinstance(point, dict) or "x" not in point or "y" not in point:
            raise ValueError(f"polygon[{index}] must contain x and y")
        x = float(point["x"])
        y = float(point["y"])
        if not 0.0 <= x <= 1.0 or not 0.0 <= y <= 1.0:
            raise ValueError(f"polygon[{index}] must be inside normalized range 0..1")
        polygon.append((x, y))
    if len(set(polygon)) < 3 or polygon_area(polygon) <= 1e-9:
        raise ValueError("polygon must contain at least three non-collinear points")
    return config


def point_on_segment(
    point_x: float,
    point_y: float,
    start: tuple[float, float],
    end: tuple[float, float],
    tolerance: float = 1e-9,
) -> bool:
    start_x, start_y = start
    end_x, end_y = end
    cross = (point_x - start_x) * (end_y - start_y) - (point_y - start_y) * (
        end_x - start_x
    )
    if abs(cross) > tolerance:
        return False
    return (
        min(start_x, end_x) - tolerance <= point_x <= max(start_x, end_x) + tolerance
        and min(start_y, end_y) - tolerance
        <= point_y
        <= max(start_y, end_y) + tolerance
    )


def point_in_polygon(
    point_x: float,
    point_y: float,
    polygon: list[tuple[float, float]],
) -> bool:
    """Return True for points inside or on the boundary of a polygon."""
    inside = False
    for start, end in zip(polygon, polygon[1:] + polygon[:1]):
        if point_on_segment(point_x, point_y, start, end):
            return True
        start_x, start_y = start
        end_x, end_y = end
        crosses_y = (start_y > point_y) != (end_y > point_y)
        if not crosses_y:
            continue
        intersection_x = start_x + (
            (point_y - start_y) * (end_x - start_x) / (end_y - start_y)
        )
        if point_x < intersection_x:
            inside = not inside
    return inside


def validate_input_artifacts(
    input_dir: Path,
) -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame]:
    missing = [
        input_dir / filename
        for filename in REQUIRED_L2_FILES.values()
        if not (input_dir / filename).is_file()
    ]
    if missing:
        raise FileNotFoundError(f"missing L2 artifacts: {missing}")
    analysis = json.loads(
        (input_dir / REQUIRED_L2_FILES["analysis"]).read_text(encoding="utf-8")
    )
    events = pd.read_parquet(input_dir / REQUIRED_L2_FILES["events"])
    frames = pd.read_parquet(input_dir / REQUIRED_L2_FILES["frames"])
    missing_event_columns = sorted(REQUIRED_EVENT_COLUMNS - set(events.columns))
    missing_frame_columns = sorted(REQUIRED_FRAME_COLUMNS - set(frames.columns))
    if missing_event_columns:
        raise ValueError(f"events.parquet is missing columns: {missing_event_columns}")
    if missing_frame_columns:
        raise ValueError(f"frames.parquet is missing columns: {missing_frame_columns}")
    if frames.duplicated(["video_id", "frame_index"]).any():
        raise ValueError("frames.parquet contains duplicate video_id/frame_index rows")
    return analysis, events, frames


def validate_camera_scope(
    camera_id: str,
    events: pd.DataFrame,
    frames: pd.DataFrame,
) -> None:
    video_ids = set(events["video_id"].astype(str)) | set(
        frames["video_id"].astype(str)
    )
    mismatched = sorted(video_id for video_id in video_ids if camera_id not in video_id)
    if mismatched:
        raise ValueError(
            f"ROI camera_id={camera_id} does not match video ids: {mismatched}"
        )


def apply_roi_to_events(
    events: pd.DataFrame,
    analysis_id: str,
    roi_id: str,
    polygon: list[tuple[float, float]],
) -> pd.DataFrame:
    result = events.copy()
    source_ids = result["analysis_id"].astype(str)
    if source_ids.nunique() > 1:
        raise ValueError("events.parquet must contain exactly one source analysis_id")
    result.insert(1, "source_analysis_id", source_ids)
    result["analysis_id"] = analysis_id
    inside = [
        point_in_polygon(float(x), float(y), polygon)
        for x, y in zip(result["point_x_norm"], result["point_y_norm"])
    ]
    result["is_in_front_of_shop"] = pd.Series(inside, index=result.index, dtype=bool)
    result["roi_id"] = result["is_in_front_of_shop"].map({True: roi_id, False: "none"})
    return result


def build_roi_frames(
    frames: pd.DataFrame,
    roi_events: pd.DataFrame,
    analysis_id: str,
) -> pd.DataFrame:
    result = frames.copy()
    source_ids = result["analysis_id"].astype(str)
    if source_ids.nunique() > 1:
        raise ValueError("frames.parquet must contain exactly one source analysis_id")
    result.insert(1, "source_analysis_id", source_ids)
    result["analysis_id"] = analysis_id

    event_counts = (
        roi_events.groupby(["video_id", "frame_index"])
        .size()
        .rename("event_observation_count")
        .reset_index()
    )
    result = result.merge(event_counts, on=["video_id", "frame_index"], how="left")
    result["event_observation_count"] = (
        result["event_observation_count"].fillna(0).astype(int)
    )
    if not result["event_observation_count"].equals(
        result["person_detection_count"].astype(int)
    ):
        mismatched = result.loc[
            result["event_observation_count"]
            != result["person_detection_count"].astype(int),
            [
                "video_id",
                "frame_index",
                "person_detection_count",
                "event_observation_count",
            ],
        ]
        raise ValueError(
            "L2 event rows do not match frame detection counts: "
            f"{mismatched.head(10).to_dict(orient='records')}"
        )

    inside_counts = (
        roi_events.loc[roi_events["is_in_front_of_shop"]]
        .groupby(["video_id", "frame_index"])
        .size()
        .rename("roi_observation_count")
        .reset_index()
    )
    result = result.merge(inside_counts, on=["video_id", "frame_index"], how="left")
    result["roi_observation_count"] = (
        result["roi_observation_count"].fillna(0).astype(int)
    )
    result["outside_roi_observation_count"] = (
        result["person_detection_count"].astype(int) - result["roi_observation_count"]
    )
    if (result["outside_roi_observation_count"] < 0).any():
        raise ValueError("ROI event count exceeds the L2 frame detection count")
    result["roi_observation_share"] = np.where(
        result["person_detection_count"] > 0,
        result["roi_observation_count"] / result["person_detection_count"],
        0.0,
    ).round(6)
    result = result.drop(columns="event_observation_count")
    return result


def quantile_95(values: pd.Series) -> float:
    return round(float(values.quantile(0.95)), 6)


def build_roi_summary(
    roi_frames: pd.DataFrame,
    analysis_id: str,
    roi_id: str,
) -> pd.DataFrame:
    group_keys = ["date_id", "time_bucket"]
    summary = (
        roi_frames.groupby(group_keys, as_index=False)
        .agg(
            sampled_frame_count=("frame_index", "size"),
            total_person_detection_observations=("person_detection_count", "sum"),
            roi_observations=("roi_observation_count", "sum"),
            outside_roi_observations=("outside_roi_observation_count", "sum"),
            mean_persons_per_sampled_frame=("person_detection_count", "mean"),
            mean_roi_observations_per_sampled_frame=("roi_observation_count", "mean"),
            p95_roi_observations_per_sampled_frame=(
                "roi_observation_count",
                quantile_95,
            ),
            max_roi_observations_per_sampled_frame=("roi_observation_count", "max"),
        )
        .sort_values(group_keys)
        .reset_index(drop=True)
    )
    summary.insert(0, "analysis_id", analysis_id)
    summary.insert(3, "roi_id", roi_id)
    summary["mean_persons_per_sampled_frame"] = summary[
        "mean_persons_per_sampled_frame"
    ].round(6)
    summary["mean_roi_observations_per_sampled_frame"] = summary[
        "mean_roi_observations_per_sampled_frame"
    ].round(6)
    summary["roi_observation_share"] = np.where(
        summary["total_person_detection_observations"] > 0,
        summary["roi_observations"] / summary["total_person_detection_observations"],
        0.0,
    ).round(6)
    return summary


def source_video_map(analysis: dict[str, Any]) -> dict[str, Path]:
    mapping: dict[str, Path] = {}
    for path_text in analysis.get("source_videos", []):
        path = resolve_repo_path(Path(str(path_text)))
        mapping[path.stem] = path
    if not mapping:
        for clip in analysis.get("clip_summaries", []):
            path = resolve_repo_path(Path(str(clip.get("video", ""))))
            if path.name:
                mapping[path.stem] = path
    return mapping


def select_preview_frame(
    roi_frames: pd.DataFrame,
    video_id: str,
    frame_index: int | None,
) -> pd.Series:
    selected = roi_frames
    if video_id:
        selected = selected.loc[selected["video_id"].astype(str) == video_id]
        if selected.empty:
            raise ValueError(
                f"preview video id not found in sampled frames: {video_id}"
            )
    if frame_index is not None:
        selected = selected.loc[selected["frame_index"].astype(int) == frame_index]
        if selected.empty:
            raise ValueError(
                "preview frame index not found for the selected sampled frame scope: "
                f"{frame_index}"
            )
    return selected.sort_values(
        ["roi_observation_count", "person_detection_count", "video_id", "frame_index"],
        ascending=[False, False, True, True],
    ).iloc[0]


def draw_text_box(
    frame: np.ndarray,
    lines: list[str],
    origin: tuple[int, int] = (24, 36),
) -> None:
    font = cv2.FONT_HERSHEY_SIMPLEX
    font_scale = 0.72
    thickness = 2
    line_height = 34
    widths = [
        cv2.getTextSize(line, font, font_scale, thickness)[0][0] for line in lines
    ]
    x, first_baseline = origin
    box_width = max(widths, default=0) + 24
    box_height = line_height * len(lines) + 14
    cv2.rectangle(
        frame,
        (x - 12, first_baseline - 28),
        (x - 12 + box_width, first_baseline - 28 + box_height),
        (20, 20, 20),
        -1,
    )
    for index, line in enumerate(lines):
        cv2.putText(
            frame,
            line,
            (x, first_baseline + index * line_height),
            font,
            font_scale,
            (255, 255, 255),
            thickness,
            cv2.LINE_AA,
        )


def render_roi_overlay(
    output_path: Path,
    source_analysis: dict[str, Any],
    roi_events: pd.DataFrame,
    roi_frames: pd.DataFrame,
    config: dict[str, Any],
    preview_video_id: str,
    preview_frame_index: int | None,
) -> dict[str, Any]:
    frame_row = select_preview_frame(
        roi_frames=roi_frames,
        video_id=preview_video_id,
        frame_index=preview_frame_index,
    )
    video_id = str(frame_row["video_id"])
    frame_index = int(frame_row["frame_index"])
    videos = source_video_map(source_analysis)
    video_path = videos.get(video_id)
    if video_path is None or not video_path.is_file():
        raise FileNotFoundError(f"source video not found for preview: {video_id}")

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"failed to open preview video: {video_path}")
    try:
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
        ok, frame = cap.read()
    finally:
        cap.release()
    if not ok:
        raise RuntimeError(f"failed to read preview frame={frame_index}: {video_path}")

    height, width = frame.shape[:2]
    polygon_norm = [
        (float(point["x"]), float(point["y"])) for point in config["polygon"]
    ]
    polygon_px = np.array(
        [
            [
                min(width - 1, max(0, round(x * width))),
                min(height - 1, max(0, round(y * height))),
            ]
            for x, y in polygon_norm
        ],
        dtype=np.int32,
    )
    tint = frame.copy()
    cv2.fillPoly(tint, [polygon_px], (0, 215, 255))
    frame = cv2.addWeighted(tint, 0.14, frame, 0.86, 0.0)
    cv2.polylines(frame, [polygon_px], True, (0, 215, 255), 4, cv2.LINE_AA)

    selected_events = roi_events.loc[
        (roi_events["video_id"].astype(str) == video_id)
        & (roi_events["frame_index"].astype(int) == frame_index)
    ]
    for event in selected_events.itertuples(index=False):
        inside = bool(event.is_in_front_of_shop)
        color = (60, 210, 80) if inside else (150, 150, 150)
        x1 = min(width - 1, max(0, round(float(event.bbox_x1))))
        y1 = min(height - 1, max(0, round(float(event.bbox_y1))))
        x2 = min(width - 1, max(0, round(float(event.bbox_x2))))
        y2 = min(height - 1, max(0, round(float(event.bbox_y2))))
        point_x = min(width - 1, max(0, round(float(event.point_x_norm) * width)))
        point_y = min(height - 1, max(0, round(float(event.point_y_norm) * height)))
        cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2, cv2.LINE_AA)
        cv2.circle(frame, (point_x, point_y), 6, (0, 0, 255), -1, cv2.LINE_AA)

    roi_count = int(frame_row["roi_observation_count"])
    draw_text_box(
        frame,
        [
            f"ROI: {config['primary_roi_id']}",
            f"Current ROI occupancy: {roi_count}",
            f"Sampled frame: {frame_index} (not unique people)",
        ],
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(output_path), frame):
        raise RuntimeError(f"failed to write ROI overlay: {output_path}")
    return {
        "video_id": video_id,
        "frame_index": frame_index,
        "timestamp_ms": int(frame_row["timestamp_ms"]),
        "current_roi_occupancy": roi_count,
        "person_detection_count": int(frame_row["person_detection_count"]),
        "path": str(output_path),
    }


def build_roi_analysis(
    analysis_id: str,
    input_dir: Path,
    output_dir: Path,
    source_analysis: dict[str, Any],
    config: dict[str, Any],
    roi_events: pd.DataFrame,
    roi_frames: pd.DataFrame,
    roi_summary: pd.DataFrame,
    preview: dict[str, Any],
) -> dict[str, Any]:
    total_observations = int(len(roi_events))
    roi_observations = int(roi_events["is_in_front_of_shop"].sum())
    peak = roi_summary.sort_values(
        ["mean_roi_observations_per_sampled_frame", "date_id", "time_bucket"],
        ascending=[False, True, True],
    ).iloc[0]
    date_summary = (
        roi_frames.groupby("date_id", as_index=False)
        .agg(
            sampled_frame_count=("frame_index", "size"),
            total_person_detection_observations=("person_detection_count", "sum"),
            roi_observations=("roi_observation_count", "sum"),
        )
        .sort_values("date_id")
    )
    date_summary["mean_roi_observations_per_sampled_frame"] = (
        date_summary["roi_observations"] / date_summary["sampled_frame_count"]
    ).round(6)
    date_summary["roi_observation_share"] = np.where(
        date_summary["total_person_detection_observations"] > 0,
        date_summary["roi_observations"]
        / date_summary["total_person_detection_observations"],
        0.0,
    ).round(6)
    return {
        "analysis_id": analysis_id,
        "scope": "L3-1_manual_roi_sampled_observation",
        "source_analysis_id": source_analysis.get("analysis_id"),
        "source_l2_dir": str(input_dir),
        "camera_id": config["camera_id"],
        "sample_every_sec": source_analysis.get("sample_every_sec"),
        "clip_count": int(roi_frames["video_id"].nunique()),
        "sampled_frames": int(len(roi_frames)),
        "person_detection_observations": total_observations,
        "roi_observations": roi_observations,
        "outside_roi_observations": total_observations - roi_observations,
        "roi_observation_share": round(
            roi_observations / total_observations if total_observations else 0.0,
            6,
        ),
        "primary_comparison_metric": "mean_roi_observations_per_sampled_frame",
        "peak_date_id": str(peak["date_id"]),
        "peak_time_bucket": str(peak["time_bucket"]),
        "peak_roi_observations": int(peak["roi_observations"]),
        "peak_mean_roi_observations_per_sampled_frame": float(
            peak["mean_roi_observations_per_sampled_frame"]
        ),
        "peak_p95_roi_observations_per_sampled_frame": float(
            peak["p95_roi_observations_per_sampled_frame"]
        ),
        "peak_max_roi_observations_per_sampled_frame": int(
            peak["max_roi_observations_per_sampled_frame"]
        ),
        "roi_config": config,
        "date_summary": date_summary.to_dict(orient="records"),
        "preview": preview,
        "artifacts": {
            "roi_config_json": str(output_dir / "roi_config.json"),
            "roi_events_parquet": str(output_dir / "roi_events.parquet"),
            "roi_frames_parquet": str(output_dir / "roi_frames.parquet"),
            "roi_summary_parquet": str(output_dir / "roi_summary.parquet"),
            "roi_dashboard_summary_csv": str(output_dir / "roi_dashboard_summary.csv"),
            "roi_analysis_json": str(output_dir / "roi_analysis.json"),
            "roi_overlay_preview": preview["path"],
        },
        "limitations": [
            "ROI values are sampled-frame bbox observations, not unique visitors or line-crossing events.",
            "The manual polygon is valid only while the C0241 camera position and crop remain unchanged.",
            "ROI inclusion uses bbox bottom-center in normalized image coordinates without ground-plane calibration.",
            "Zero-detection sampled frames remain in frame-normalized ROI metrics.",
        ],
    }


def main() -> None:
    args = parse_args()
    input_dir = resolve_repo_path(args.input_dir)
    config_path = resolve_repo_path(args.roi_config)
    output_dir = resolve_repo_path(args.output_dir)
    analysis_id = args.analysis_id or output_dir.name

    source_analysis, events, frames = validate_input_artifacts(input_dir)
    config = load_roi_config(config_path)
    validate_camera_scope(str(config["camera_id"]), events, frames)
    polygon = [(float(point["x"]), float(point["y"])) for point in config["polygon"]]
    roi_events = apply_roi_to_events(
        events=events,
        analysis_id=analysis_id,
        roi_id=str(config["primary_roi_id"]),
        polygon=polygon,
    )
    roi_frames = build_roi_frames(
        frames=frames,
        roi_events=roi_events,
        analysis_id=analysis_id,
    )
    roi_summary = build_roi_summary(
        roi_frames=roi_frames,
        analysis_id=analysis_id,
        roi_id=str(config["primary_roi_id"]),
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    preview = render_roi_overlay(
        output_path=output_dir / "previews" / "roi_overlay_preview.jpg",
        source_analysis=source_analysis,
        roi_events=roi_events,
        roi_frames=roi_frames,
        config=config,
        preview_video_id=args.preview_video_id,
        preview_frame_index=args.preview_frame_index,
    )
    roi_analysis = build_roi_analysis(
        analysis_id=analysis_id,
        input_dir=input_dir,
        output_dir=output_dir,
        source_analysis=source_analysis,
        config=config,
        roi_events=roi_events,
        roi_frames=roi_frames,
        roi_summary=roi_summary,
        preview=preview,
    )

    (output_dir / "roi_config.json").write_text(
        json.dumps(config, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    roi_events.to_parquet(output_dir / "roi_events.parquet", index=False)
    roi_frames.to_parquet(output_dir / "roi_frames.parquet", index=False)
    roi_summary.to_parquet(output_dir / "roi_summary.parquet", index=False)
    roi_summary.to_csv(output_dir / "roi_dashboard_summary.csv", index=False)
    (output_dir / "roi_analysis.json").write_text(
        json.dumps(roi_analysis, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(f"analysis_id={analysis_id}")
    print(f"camera_id={config['camera_id']}")
    print(f"clip_count={roi_analysis['clip_count']}")
    print(f"sampled_frames={roi_analysis['sampled_frames']}")
    print(f"person_detection_observations={len(roi_events)}")
    print(f"roi_observations={roi_analysis['roi_observations']}")
    print(f"roi_observation_share={roi_analysis['roi_observation_share']}")
    print(f"peak_time_bucket={roi_analysis['peak_time_bucket']}")
    print(f"output_dir={output_dir}")


if __name__ == "__main__":
    main()
