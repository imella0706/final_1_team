#!/usr/bin/env python3
"""Create an L3-4 clip-local tracking ID QA video and summary artifacts."""

from __future__ import annotations

import argparse
import csv
import json
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np

try:
    from scripts.visitor_flow_l3_privacy_media import (
        load_roi_config,
        mask_person_bbox_tops,
        roi_polygon_pixels,
    )
except ModuleNotFoundError:  # pragma: no cover - direct script execution fallback
    from visitor_flow_l3_privacy_media import (  # type: ignore[no-redef]
        load_roi_config,
        mask_person_bbox_tops,
        roi_polygon_pixels,
    )


# [Design Intent] L3-4 is an experimental QA stage, not an official processed
# dataset. It writes only under outputs/ and creates clip-local tracking evidence
# for later L3-5 line-crossing validation.
REPO_ROOT = Path(__file__).resolve().parents[1]
OUTPUTS_ROOT = REPO_ROOT / "outputs"


@dataclass(frozen=True)
class TrackDetection:
    track_id: int | None
    confidence: float
    x1: float
    y1: float
    x2: float
    y2: float

    @property
    def bbox(self) -> tuple[float, float, float, float]:
        return self.x1, self.y1, self.x2, self.y2

    def bottom_center(self) -> tuple[float, float]:
        return ((self.x1 + self.x2) / 2.0, self.y2)


TRACK_EVENT_FIELDS = [
    "source_frame_index",
    "clip_frame_index",
    "timestamp_sec",
    "track_id",
    "confidence",
    "bbox_x1",
    "bbox_y1",
    "bbox_x2",
    "bbox_y2",
    "bottom_center_x",
    "bottom_center_y",
    "is_in_roi",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Render a WebM QA video with clip-local tracking IDs and write track "
            "event/summary artifacts for L3-4."
        )
    )
    parser.add_argument("--video", required=True, type=Path)
    parser.add_argument("--model", required=True, type=Path)
    parser.add_argument("--roi-config", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--device", default="cpu", help="Inference device: cpu, cuda, 0")
    parser.add_argument("--imgsz", default=960, type=int)
    parser.add_argument("--conf", default=0.50, type=float)
    parser.add_argument(
        "--tracker",
        default="bytetrack.yaml",
        help="Ultralytics tracker config, e.g. bytetrack.yaml or botsort.yaml.",
    )
    parser.add_argument("--start-sec", default=60.0, type=float)
    parser.add_argument("--max-seconds", default=60.0, type=float)
    parser.add_argument(
        "--trail-length",
        default=30,
        type=int,
        help="Number of recent bottom-center points to draw per active track.",
    )
    parser.add_argument(
        "--max-gap-frames",
        default=3,
        type=int,
        help="Frame gap larger than this is recorded as a fragmentation candidate.",
    )
    parser.add_argument(
        "--disable-privacy-mask",
        action="store_true",
        help="Disable upper-bbox mosaic on the operator QA video.",
    )
    parser.add_argument("--mask-top-ratio", default=0.40, type=float)
    parser.add_argument("--mask-padding-ratio", default=0.03, type=float)
    parser.add_argument("--mosaic-block-size", default=12, type=int)
    return parser.parse_args()


def resolve_repo_path(path: Path) -> Path:
    expanded = path.expanduser()
    if expanded.is_absolute():
        return expanded.resolve()
    return (REPO_ROOT / expanded).resolve()


def validate_output_dir(output_dir: Path) -> None:
    try:
        output_dir.relative_to(OUTPUTS_ROOT.resolve())
    except ValueError as error:
        raise ValueError("L3-4 tracking QA output must be under outputs/.") from error


def validate_args(
    args: argparse.Namespace,
    video_path: Path,
    model_path: Path,
    roi_config_path: Path,
    output_dir: Path,
) -> None:
    for label, path in (
        ("video", video_path),
        ("model", model_path),
        ("ROI config", roi_config_path),
    ):
        if not path.is_file():
            raise FileNotFoundError(f"{label} not found: {path}")
    validate_output_dir(output_dir)
    if not 0.0 <= args.conf <= 1.0:
        raise ValueError("--conf must be between 0.0 and 1.0")
    if args.imgsz <= 0:
        raise ValueError("--imgsz must be greater than 0")
    if args.start_sec < 0:
        raise ValueError("--start-sec must be 0 or greater")
    if args.max_seconds <= 0:
        raise ValueError("--max-seconds must be greater than 0")
    if args.trail_length < 0:
        raise ValueError("--trail-length must be 0 or greater")
    if args.max_gap_frames < 0:
        raise ValueError("--max-gap-frames must be 0 or greater")
    if not 0.0 < args.mask_top_ratio <= 1.0:
        raise ValueError("--mask-top-ratio must be greater than 0.0 and at most 1.0")
    if not 0.0 <= args.mask_padding_ratio <= 1.0:
        raise ValueError("--mask-padding-ratio must be between 0.0 and 1.0")
    if args.mosaic_block_size < 2:
        raise ValueError("--mosaic-block-size must be at least 2")


def stable_track_color(track_id: int | None) -> tuple[int, int, int]:
    if track_id is None:
        return (170, 170, 170)
    palette = [
        (38, 198, 218),
        (102, 187, 106),
        (255, 202, 40),
        (171, 71, 188),
        (239, 83, 80),
        (66, 165, 245),
        (255, 112, 67),
        (156, 204, 101),
    ]
    return palette[track_id % len(palette)]


def tensor_values(values: Any) -> list[Any]:
    if values is None:
        return []
    if hasattr(values, "cpu"):
        values = values.cpu()
    if hasattr(values, "tolist"):
        return values.tolist()
    return list(values)


def extract_tracked_detections(result: Any) -> list[TrackDetection]:
    if result.boxes is None or len(result.boxes) == 0:
        return []

    xyxy_values = tensor_values(result.boxes.xyxy)
    confidence_values = tensor_values(result.boxes.conf)
    raw_ids = tensor_values(getattr(result.boxes, "id", None))
    if not raw_ids:
        raw_ids = [None] * len(xyxy_values)

    detections: list[TrackDetection] = []
    for xyxy, confidence, raw_id in zip(xyxy_values, confidence_values, raw_ids):
        x1, y1, x2, y2 = (float(value) for value in xyxy)
        track_id = None if raw_id is None else int(raw_id)
        detections.append(
            TrackDetection(
                track_id=track_id,
                confidence=float(confidence),
                x1=x1,
                y1=y1,
                x2=x2,
                y2=y2,
            )
        )
    return detections


def detection_is_in_roi(
    detection: TrackDetection,
    roi_polygon: np.ndarray,
) -> bool:
    point_x, point_y = detection.bottom_center()
    return cv2.pointPolygonTest(roi_polygon, (float(point_x), float(point_y)), False) >= 0


def draw_roi(frame: np.ndarray, polygon: np.ndarray, roi_id: str) -> None:
    tint = frame.copy()
    cv2.fillPoly(tint, [polygon], (0, 215, 255))
    cv2.addWeighted(tint, 0.10, frame, 0.90, 0.0, dst=frame)
    cv2.polylines(frame, [polygon], True, (0, 215, 255), 4, cv2.LINE_AA)
    label = f"L3-4 Tracking QA | ROI: {roi_id} | operator only"
    label_size = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.72, 2)[0]
    cv2.rectangle(frame, (12, 10), (36 + label_size[0], 52), (20, 20, 20), -1)
    cv2.putText(
        frame,
        label,
        (24, 39),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.72,
        (255, 255, 255),
        2,
        cv2.LINE_AA,
    )


def draw_track_trails(
    frame: np.ndarray,
    detections: list[TrackDetection],
    track_histories: dict[int, deque[tuple[int, int]]],
) -> None:
    for detection in detections:
        if detection.track_id is None:
            continue
        points = list(track_histories[detection.track_id])
        if len(points) < 2:
            continue
        color = stable_track_color(detection.track_id)
        for start, end in zip(points, points[1:]):
            cv2.line(frame, start, end, color, 3, cv2.LINE_AA)


def draw_detections(
    frame: np.ndarray,
    detections: list[TrackDetection],
    roi_polygon: np.ndarray,
    track_histories: dict[int, deque[tuple[int, int]]],
) -> tuple[int, int, int]:
    height, width = frame.shape[:2]
    active_track_ids: set[int] = set()
    roi_track_ids: set[int] = set()
    unassigned_count = 0

    for detection in detections:
        left = min(width - 1, max(0, round(detection.x1)))
        top = min(height - 1, max(0, round(detection.y1)))
        right = min(width - 1, max(0, round(detection.x2)))
        bottom = min(height - 1, max(0, round(detection.y2)))
        point_x = min(width - 1, max(0, round((detection.x1 + detection.x2) / 2.0)))
        point_y = min(height - 1, max(0, round(detection.y2)))
        in_roi = detection_is_in_roi(detection, roi_polygon)
        if detection.track_id is None:
            unassigned_count += 1
        else:
            active_track_ids.add(detection.track_id)
            if in_roi:
                roi_track_ids.add(detection.track_id)
            track_histories[detection.track_id].append((point_x, point_y))

        color = stable_track_color(detection.track_id)
        track_label = "person-?" if detection.track_id is None else f"person-{detection.track_id}"
        cv2.rectangle(frame, (left, top), (right, bottom), color, 3, cv2.LINE_AA)
        cv2.circle(frame, (point_x, point_y), 6, (0, 0, 255), -1, cv2.LINE_AA)

        # Draw filled background box for high contrast person label
        font = cv2.FONT_HERSHEY_SIMPLEX
        font_scale = 0.65
        text_thick = 2
        (tw, th), baseline = cv2.getTextSize(track_label, font, font_scale, text_thick)
        box_top = max(10, top - th - 12)
        box_bottom = box_top + th + 8
        box_left = left
        box_right = left + tw + 14

        # Filled color banner
        cv2.rectangle(frame, (box_left, box_top), (box_right, box_bottom), color, -1)
        cv2.rectangle(frame, (box_left, box_top), (box_right, box_bottom), (0, 0, 0), 1)
        # Text inside box
        cv2.putText(
            frame,
            track_label,
            (box_left + 7, box_bottom - 5),
            font,
            font_scale,
            (255, 255, 255),
            text_thick,
            cv2.LINE_AA,
        )

    draw_track_trails(frame, detections, track_histories)
    draw_big_screen_counts(frame, len(roi_track_ids), len(active_track_ids))
    return len(active_track_ids), len(roi_track_ids), unassigned_count


def draw_big_screen_counts(frame: np.ndarray, roi_count: int, tracked_count: int) -> None:
    height, width = frame.shape[:2]
    font = cv2.FONT_HERSHEY_SIMPLEX
    font_scale = 0.85
    thick = 2

    line1 = f"In front of shop : {roi_count}"
    line2 = f"Person being tracked : {tracked_count}"

    card_w = 500
    card_h = 160
    margin_x = 35
    margin_y = 75

    box_right = width - margin_x
    box_left = box_right - card_w
    box_bottom = height - margin_y
    box_top = box_bottom - card_h

    # Draw crisp white background card
    cv2.rectangle(frame, (box_left, box_top), (box_right, box_bottom), (255, 255, 255), -1)
    cv2.rectangle(frame, (box_left, box_top), (box_right, box_bottom), (40, 40, 40), 2)

    x_text = box_left + 22
    y2 = box_top + 90
    y3 = box_top + 138

    # Line 2: In front of shop (Golden Amber)
    cv2.putText(frame, line1, (x_text, y2), font, font_scale, (0, 120, 210), thick, cv2.LINE_AA)

    # Line 3: Person being tracked (Dark Green)
    cv2.putText(frame, line2, (x_text, y3), font, font_scale, (0, 140, 0), thick, cv2.LINE_AA)


def draw_footer(
    frame: np.ndarray,
    source_frame_index: int,
    timestamp_sec: float,
    active_tracks: int,
    roi_tracks: int,
    unassigned_count: int,
) -> None:
    height, width = frame.shape[:2]
    cv2.rectangle(frame, (0, height - 52), (width, height), (0, 0, 0), -1)
    cv2.putText(
        frame,
        (
            f"frame={source_frame_index} time={timestamp_sec:.1f}s "
            f"active_tracks={active_tracks} roi_tracks={roi_tracks} "
            f"unassigned={unassigned_count} | clip-local IDs, not unique visitors"
        ),
        (18, height - 16),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.70,
        (255, 255, 255),
        2,
        cv2.LINE_AA,
    )


def create_video_writer(output_path: Path, fps: float, width: int, height: int) -> Any:
    if output_path.suffix.lower() != ".webm":
        raise ValueError("tracking QA video output must end with .webm")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    writer = cv2.VideoWriter(
        str(output_path),
        cv2.VideoWriter_fourcc(*"VP80"),
        fps,
        (width, height),
    )
    if not writer.isOpened():
        raise RuntimeError(f"failed to open WebM writer: {output_path}")
    return writer


def write_track_events_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=TRACK_EVENT_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def build_track_summary(
    rows: list[dict[str, Any]],
    processed_frames: int,
    max_gap_frames: int,
) -> dict[str, Any]:
    by_track: dict[int, list[dict[str, Any]]] = defaultdict(list)
    frame_active_ids: dict[int, set[int]] = defaultdict(set)
    unassigned_observations = 0
    for row in rows:
        track_id = row["track_id"]
        frame_index = int(row["clip_frame_index"])
        if track_id in ("", None):
            unassigned_observations += 1
            continue
        track_id_int = int(track_id)
        by_track[track_id_int].append(row)
        frame_active_ids[frame_index].add(track_id_int)

    track_summaries: list[dict[str, Any]] = []
    total_fragmentation_gap_count = 0
    for track_id, track_rows in sorted(by_track.items()):
        frames = sorted({int(row["clip_frame_index"]) for row in track_rows})
        gaps = [
            current - previous - 1
            for previous, current in zip(frames, frames[1:])
            if current - previous - 1 > max_gap_frames
        ]
        total_fragmentation_gap_count += len(gaps)
        confidences = [float(row["confidence"]) for row in track_rows]
        first_frame = frames[0]
        last_frame = frames[-1]
        span_frames = last_frame - first_frame + 1
        track_summaries.append(
            {
                "track_id": track_id,
                "first_clip_frame_index": first_frame,
                "last_clip_frame_index": last_frame,
                "span_frames": span_frames,
                "observation_count": len(track_rows),
                "coverage_ratio_within_span": round(len(frames) / span_frames, 6),
                "fragmentation_gap_count": len(gaps),
                "max_gap_frames": max(gaps, default=0),
                "mean_confidence": round(float(np.mean(confidences)), 6),
            }
        )

    active_counts = [len(frame_active_ids[index]) for index in range(processed_frames)]
    return {
        "processed_frames": processed_frames,
        "track_observations": sum(len(rows) for rows in by_track.values()),
        "unassigned_observations": unassigned_observations,
        "unique_clip_track_ids": len(by_track),
        "max_active_tracks_per_frame": max(active_counts, default=0),
        "mean_active_tracks_per_frame": round(
            float(np.mean(active_counts)) if active_counts else 0.0,
            6,
        ),
        "tracks_with_single_observation": sum(
            1 for item in track_summaries if item["observation_count"] == 1
        ),
        "fragmentation_gap_count": total_fragmentation_gap_count,
        "track_summaries": track_summaries,
    }


def event_row(
    detection: TrackDetection,
    source_frame_index: int,
    clip_frame_index: int,
    timestamp_sec: float,
    is_in_roi: bool,
) -> dict[str, Any]:
    point_x, point_y = detection.bottom_center()
    return {
        "source_frame_index": source_frame_index,
        "clip_frame_index": clip_frame_index,
        "timestamp_sec": round(timestamp_sec, 6),
        "track_id": "" if detection.track_id is None else detection.track_id,
        "confidence": round(detection.confidence, 6),
        "bbox_x1": round(detection.x1, 3),
        "bbox_y1": round(detection.y1, 3),
        "bbox_x2": round(detection.x2, 3),
        "bbox_y2": round(detection.y2, 3),
        "bottom_center_x": round(point_x, 3),
        "bottom_center_y": round(point_y, 3),
        "is_in_roi": bool(is_in_roi),
    }


def main() -> None:
    args = parse_args()
    video_path = resolve_repo_path(args.video)
    model_path = resolve_repo_path(args.model)
    roi_config_path = resolve_repo_path(args.roi_config)
    output_dir = resolve_repo_path(args.output_dir)
    validate_args(
        args,
        video_path=video_path,
        model_path=model_path,
        roi_config_path=roi_config_path,
        output_dir=output_dir,
    )

    # [Design Intent] Import Ultralytics only in CLI execution. Unit tests can
    # validate parsing, summary, and drawing helpers without loading model runtime.
    from ultralytics import YOLO

    roi_config = load_roi_config(roi_config_path)
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"failed to open video: {video_path}")

    fps = float(cap.get(cv2.CAP_PROP_FPS))
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    if fps <= 0 or frame_count <= 0 or width <= 0 or height <= 0:
        cap.release()
        raise RuntimeError(
            f"invalid video metadata: fps={fps}, frames={frame_count}, "
            f"size={width}x{height}"
        )

    start_frame_index = min(frame_count - 1, round(fps * args.start_sec))
    render_frame_count = min(
        frame_count - start_frame_index,
        max(1, round(fps * args.max_seconds)),
    )
    cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame_index)

    roi_polygon = roi_polygon_pixels(roi_config, width=width, height=height)
    video_output = output_dir / "media" / "tracking_id_qa.webm"
    events_output = output_dir / "tracks" / "track_events.csv"
    summary_output = output_dir / "qa" / "tracking_qa_summary.json"
    writer = create_video_writer(video_output, fps=fps, width=width, height=height)
    model = YOLO(str(model_path))
    track_histories: dict[int, deque[tuple[int, int]]] = defaultdict(
        lambda: deque(maxlen=args.trail_length)
    )

    print(f"video={video_path}")
    print(f"frames_to_render={render_frame_count}, fps={fps:.2f}, size={width}x{height}")
    print(
        f"tracker={args.tracker}, conf={args.conf:.2f}, device={args.device}, "
        f"imgsz={args.imgsz}"
    )
    print(f"privacy_mask_enabled={not args.disable_privacy_mask}")
    print(f"output_dir={output_dir}")

    started_at = time.perf_counter()
    processed_frames = 0
    rows: list[dict[str, Any]] = []
    try:
        while processed_frames < render_frame_count:
            ok, frame = cap.read()
            if not ok:
                break
            result = model.track(
                frame,
                classes=[0],
                conf=args.conf,
                device=args.device,
                imgsz=args.imgsz,
                tracker=args.tracker,
                persist=True,
                verbose=False,
            )[0]
            detections = extract_tracked_detections(result)
            if not args.disable_privacy_mask:
                mask_person_bbox_tops(
                    frame,
                    boxes=[detection.bbox for detection in detections],
                    top_ratio=args.mask_top_ratio,
                    block_size=args.mosaic_block_size,
                    padding_ratio=args.mask_padding_ratio,
                )

            draw_roi(frame, polygon=roi_polygon, roi_id=str(roi_config["primary_roi_id"]))
            active_tracks, roi_tracks, unassigned_count = draw_detections(
                frame,
                detections=detections,
                roi_polygon=roi_polygon,
                track_histories=track_histories,
            )
            source_frame_index = start_frame_index + processed_frames
            timestamp_sec = source_frame_index / fps
            for detection in detections:
                rows.append(
                    event_row(
                        detection=detection,
                        source_frame_index=source_frame_index,
                        clip_frame_index=processed_frames,
                        timestamp_sec=timestamp_sec,
                        is_in_roi=detection_is_in_roi(detection, roi_polygon),
                    )
                )

            draw_footer(
                frame,
                source_frame_index=source_frame_index,
                timestamp_sec=timestamp_sec,
                active_tracks=active_tracks,
                roi_tracks=roi_tracks,
                unassigned_count=unassigned_count,
            )
            writer.write(frame)
            processed_frames += 1
            if processed_frames % max(1, round(fps * 10)) == 0:
                print(
                    f"processed_frames={processed_frames}/{render_frame_count}, "
                    f"track_rows={len(rows)}, active_tracks={active_tracks}"
                )
    finally:
        cap.release()
        writer.release()

    if processed_frames != render_frame_count:
        raise RuntimeError(
            f"tracking QA ended early: expected={render_frame_count}, "
            f"actual={processed_frames}"
        )

    elapsed_sec = time.perf_counter() - started_at
    write_track_events_csv(events_output, rows)
    track_summary = build_track_summary(
        rows=rows,
        processed_frames=processed_frames,
        max_gap_frames=args.max_gap_frames,
    )
    processing_fps = processed_frames / elapsed_sec if elapsed_sec else 0.0
    summary = {
        "schema_version": 1,
        "stage": "L3-4_tracking_id_qa",
        "storage_stage": "experimental_candidate",
        "camera_id": roi_config["camera_id"],
        "roi_id": roi_config["primary_roi_id"],
        "source_video": str(video_path),
        "settings": {
            "model": str(model_path),
            "device": args.device,
            "imgsz": args.imgsz,
            "confidence_threshold": args.conf,
            "tracker": args.tracker,
            "start_sec": args.start_sec,
            "max_seconds": args.max_seconds,
            "trail_length": args.trail_length,
            "max_gap_frames": args.max_gap_frames,
            "privacy_mask_enabled": not args.disable_privacy_mask,
            "mask_top_ratio": None if args.disable_privacy_mask else args.mask_top_ratio,
            "mask_padding_ratio": None
            if args.disable_privacy_mask
            else args.mask_padding_ratio,
            "mosaic_block_size": None
            if args.disable_privacy_mask
            else args.mosaic_block_size,
        },
        "results": {
            "width": width,
            "height": height,
            "source_fps": fps,
            "source_frame_count": frame_count,
            "start_frame_index": start_frame_index,
            "processed_frames": processed_frames,
            "processing_elapsed_sec": round(elapsed_sec, 3),
            "processing_fps": round(processing_fps, 3),
            "realtime_factor": round(processing_fps / fps, 3),
            **track_summary,
        },
        "artifacts": {
            "tracking_video": str(video_output),
            "track_events_csv": str(events_output),
            "tracking_qa_summary": str(summary_output),
        },
        "qa_policy": {
            "manual_review_required": True,
            "review_focus": [
                "same person keeps the same track_id across adjacent frames",
                "ID switches during occlusion or close crossing",
                "short single-observation tracks and fragmented track candidates",
                "whether bbox bottom-center trajectories are stable enough for L3-5 line crossing",
            ],
        },
        "limitations": [
            "Track IDs are clip-local ephemeral IDs, not customer identities or unique visitors across clips.",
            "Without ground-truth person identity labels, this stage cannot automatically prove ID switch correctness.",
            "Fragmentation gap counts are heuristic QA flags, not final tracking accuracy metrics.",
            "This stage prepares L3-5 line-crossing validation but does not count line-crossing events.",
        ],
    }
    summary_output.parent.mkdir(parents=True, exist_ok=True)
    summary_output.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(f"processed_frames={processed_frames}")
    print(f"unique_clip_track_ids={track_summary['unique_clip_track_ids']}")
    print(f"max_active_tracks_per_frame={track_summary['max_active_tracks_per_frame']}")
    print(f"fragmentation_gap_count={track_summary['fragmentation_gap_count']}")
    print(f"processing_elapsed_sec={elapsed_sec:.3f}")
    print(f"processing_fps={processing_fps:.3f}")
    print(f"tracking_video={video_output}")
    print(f"track_events_csv={events_output}")
    print(f"qa_summary={summary_output}")


if __name__ == "__main__":
    main()
