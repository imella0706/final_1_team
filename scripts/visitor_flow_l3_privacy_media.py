#!/usr/bin/env python3
"""Create privacy-masked L3-2 ROI media as experimental output artifacts."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

import cv2
import numpy as np


# [Design Intent] L3-2 creates reviewable privacy-filter candidates under outputs/.
# It never overwrites source video or writes directly to the official processed dataset.
REPO_ROOT = Path(__file__).resolve().parents[1]
OUTPUTS_ROOT = REPO_ROOT / "outputs"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run person detection, mosaic the upper part of every person bbox, and "
            "create privacy-masked ROI video/image candidates under outputs/."
        )
    )
    parser.add_argument("--video", required=True, type=Path)
    parser.add_argument("--model", required=True, type=Path)
    parser.add_argument("--roi-config", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--device", default="cpu", help="Inference device: cpu, cuda, 0")
    parser.add_argument("--imgsz", default=960, type=int)
    parser.add_argument("--conf", default=0.50, type=float)
    parser.add_argument("--start-sec", default=60.0, type=float)
    parser.add_argument("--max-seconds", default=60.0, type=float)
    parser.add_argument(
        "--mask-top-ratio",
        default=0.40,
        type=float,
        help="Fraction of each person bbox, measured from the top, to mosaic.",
    )
    parser.add_argument(
        "--mosaic-block-size",
        default=12,
        type=int,
        help="Approximate source pixels represented by one mosaic block.",
    )
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
        raise ValueError(
            "L3-2 candidate output must be under outputs/. Promote reviewed artifacts "
            "to data/processed in a separate approval step."
        ) from error


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
    if not 0.0 < args.mask_top_ratio <= 1.0:
        raise ValueError("--mask-top-ratio must be greater than 0.0 and at most 1.0")
    if args.mosaic_block_size < 2:
        raise ValueError("--mosaic-block-size must be at least 2")


def load_roi_config(path: Path) -> dict[str, Any]:
    config = json.loads(path.read_text(encoding="utf-8"))
    required = {
        "camera_id",
        "primary_roi_id",
        "coordinate_space",
        "position_point",
        "polygon",
    }
    missing = sorted(required - set(config))
    if missing:
        raise ValueError(f"ROI config is missing fields: {missing}")
    if config["coordinate_space"] != "normalized_image":
        raise ValueError("ROI coordinate_space must be normalized_image")
    if config["position_point"] != "bbox_bottom_center":
        raise ValueError("ROI position_point must be bbox_bottom_center")

    polygon = config["polygon"]
    if not isinstance(polygon, list) or len(polygon) < 3:
        raise ValueError("ROI polygon must contain at least three points")
    for index, point in enumerate(polygon):
        if not isinstance(point, dict) or "x" not in point or "y" not in point:
            raise ValueError(f"ROI polygon[{index}] must contain x and y")
        x = float(point["x"])
        y = float(point["y"])
        if not 0.0 <= x <= 1.0 or not 0.0 <= y <= 1.0:
            raise ValueError(f"ROI polygon[{index}] must be inside normalized range 0..1")
    return config


def roi_polygon_pixels(
    config: dict[str, Any],
    width: int,
    height: int,
) -> np.ndarray:
    return np.array(
        [
            [
                min(width - 1, max(0, round(float(point["x"]) * width))),
                min(height - 1, max(0, round(float(point["y"]) * height))),
            ]
            for point in config["polygon"]
        ],
        dtype=np.int32,
    )


def clip_box(
    box: tuple[float, float, float, float],
    width: int,
    height: int,
) -> tuple[int, int, int, int] | None:
    x1, y1, x2, y2 = box
    left = min(width, max(0, int(np.floor(min(x1, x2)))))
    top = min(height, max(0, int(np.floor(min(y1, y2)))))
    right = min(width, max(0, int(np.ceil(max(x1, x2)))))
    bottom = min(height, max(0, int(np.ceil(max(y1, y2)))))
    if right <= left or bottom <= top:
        return None
    return left, top, right, bottom


def mosaic_region(region: np.ndarray, block_size: int) -> np.ndarray:
    height, width = region.shape[:2]
    if height == 0 or width == 0:
        return region
    small_width = max(1, int(np.ceil(width / block_size)))
    small_height = max(1, int(np.ceil(height / block_size)))
    reduced = cv2.resize(
        region,
        (small_width, small_height),
        interpolation=cv2.INTER_AREA,
    )
    return cv2.resize(
        reduced,
        (width, height),
        interpolation=cv2.INTER_NEAREST,
    )


def mask_person_bbox_tops(
    frame: np.ndarray,
    boxes: list[tuple[float, float, float, float]],
    top_ratio: float,
    block_size: int,
) -> list[tuple[int, int, int, int]]:
    """Mosaic the upper portion of each clipped person bbox in place."""
    height, width = frame.shape[:2]
    masked_regions: list[tuple[int, int, int, int]] = []
    for box in boxes:
        clipped = clip_box(box, width=width, height=height)
        if clipped is None:
            continue
        left, top, right, bottom = clipped
        mask_bottom = min(bottom, max(top + 1, round(top + (bottom - top) * top_ratio)))
        frame[top:mask_bottom, left:right] = mosaic_region(
            frame[top:mask_bottom, left:right],
            block_size=block_size,
        )
        masked_regions.append((left, top, right, mask_bottom))
    return masked_regions


def extract_detections(result: Any) -> list[tuple[float, float, float, float, float]]:
    if result.boxes is None or len(result.boxes) == 0:
        return []
    boxes = result.boxes.xyxy.cpu().tolist()
    confidences = result.boxes.conf.cpu().tolist()
    return [
        (float(x1), float(y1), float(x2), float(y2), float(confidence))
        for (x1, y1, x2, y2), confidence in zip(boxes, confidences)
    ]


def detection_is_in_roi(
    detection: tuple[float, float, float, float, float],
    roi_polygon: np.ndarray,
) -> bool:
    x1, _y1, x2, y2, _confidence = detection
    point = (float((x1 + x2) / 2.0), float(y2))
    return cv2.pointPolygonTest(roi_polygon, point, False) >= 0


def draw_roi(frame: np.ndarray, polygon: np.ndarray, roi_id: str) -> None:
    tint = frame.copy()
    cv2.fillPoly(tint, [polygon], (0, 215, 255))
    cv2.addWeighted(tint, 0.12, frame, 0.88, 0.0, dst=frame)
    cv2.polylines(frame, [polygon], True, (0, 215, 255), 4, cv2.LINE_AA)
    label = f"Analysis ROI: {roi_id} | privacy-masked example"
    label_size = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.72, 2)[0]
    cv2.rectangle(frame, (12, 10), (36 + label_size[0], 50), (20, 20, 20), -1)
    cv2.putText(
        frame,
        label,
        (24, 38),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.72,
        (255, 255, 255),
        2,
        cv2.LINE_AA,
    )


def draw_detections(
    frame: np.ndarray,
    detections: list[tuple[float, float, float, float, float]],
    roi_polygon: np.ndarray,
) -> int:
    height, width = frame.shape[:2]
    roi_count = 0
    for detection in detections:
        x1, y1, x2, y2, confidence = detection
        clipped = clip_box((x1, y1, x2, y2), width=width, height=height)
        if clipped is None:
            continue
        left, top, right, bottom = clipped
        in_roi = detection_is_in_roi(detection, roi_polygon)
        roi_count += int(in_roi)
        color = (40, 220, 40) if in_roi else (150, 150, 150)
        point_x = min(width - 1, max(0, round((x1 + x2) / 2.0)))
        point_y = min(height - 1, max(0, round(y2)))
        location = "ROI" if in_roi else "outside ROI"
        cv2.rectangle(frame, (left, top), (right - 1, bottom - 1), color, 2)
        cv2.circle(frame, (point_x, point_y), 5, (0, 0, 255), -1)
        cv2.putText(
            frame,
            f"person {confidence:.2f} | {location}",
            (left, max(68, top - 8)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.65,
            color,
            2,
            cv2.LINE_AA,
        )
    return roi_count


def draw_footer(
    frame: np.ndarray,
    source_frame_index: int,
    timestamp_sec: float,
    detection_count: int,
    roi_count: int,
) -> None:
    height, width = frame.shape[:2]
    cv2.rectangle(frame, (0, height - 58), (width, height), (0, 0, 0), -1)
    cv2.putText(
        frame,
        (
            f"frame={source_frame_index} time={timestamp_sec:.1f}s "
            f"detections={detection_count} roi={roi_count} "
            "| privacy-masked analysis example, not unique people"
        ),
        (18, height - 18),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.78,
        (255, 255, 255),
        2,
        cv2.LINE_AA,
    )


def create_video_writer(output_path: Path, fps: float, width: int, height: int) -> Any:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    writer = cv2.VideoWriter(
        str(output_path),
        cv2.VideoWriter_fourcc(*"mp4v"),
        fps,
        (width, height),
    )
    if not writer.isOpened():
        raise RuntimeError(f"failed to open MP4 writer: {output_path}")
    return writer


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

    # [Design Intent] Import the inference runtime only for CLI execution so pure
    # privacy-filter unit tests do not initialize model-serving dependencies.
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
    video_output = output_dir / "media" / "roi_preview_masked.mp4"
    image_output = output_dir / "images" / "roi_overlay_preview_masked.jpg"
    summary_output = output_dir / "qa" / "masking_qa_summary.json"
    writer = create_video_writer(video_output, fps=fps, width=width, height=height)
    model = YOLO(str(model_path))

    print(f"video={video_path}")
    print(f"frames_to_render={render_frame_count}, fps={fps:.2f}, size={width}x{height}")
    print(f"conf={args.conf:.2f}, device={args.device}, imgsz={args.imgsz}")
    print(
        f"mask_top_ratio={args.mask_top_ratio:.2f}, "
        f"mosaic_block_size={args.mosaic_block_size}"
    )
    print(f"output_dir={output_dir}")

    started_at = time.perf_counter()
    processed_frames = 0
    detection_observations = 0
    roi_detection_observations = 0
    masked_region_observations = 0
    representative_frame: np.ndarray | None = None
    representative_score = (-1, -1)
    representative_source_frame_index = start_frame_index
    try:
        while processed_frames < render_frame_count:
            ok, frame = cap.read()
            if not ok:
                break

            result = model.predict(
                frame,
                classes=[0],
                conf=args.conf,
                device=args.device,
                imgsz=args.imgsz,
                verbose=False,
            )[0]
            detections = extract_detections(result)
            masked_regions = mask_person_bbox_tops(
                frame,
                boxes=[detection[:4] for detection in detections],
                top_ratio=args.mask_top_ratio,
                block_size=args.mosaic_block_size,
            )
            draw_roi(
                frame,
                polygon=roi_polygon,
                roi_id=str(roi_config["primary_roi_id"]),
            )
            roi_count = draw_detections(
                frame,
                detections=detections,
                roi_polygon=roi_polygon,
            )
            source_frame_index = start_frame_index + processed_frames
            timestamp_sec = source_frame_index / fps
            draw_footer(
                frame,
                source_frame_index=source_frame_index,
                timestamp_sec=timestamp_sec,
                detection_count=len(detections),
                roi_count=roi_count,
            )
            writer.write(frame)

            score = (roi_count, len(detections))
            if score > representative_score:
                representative_score = score
                representative_frame = frame.copy()
                representative_source_frame_index = source_frame_index

            processed_frames += 1
            detection_observations += len(detections)
            roi_detection_observations += roi_count
            masked_region_observations += len(masked_regions)
            if processed_frames % max(1, round(fps * 10)) == 0:
                print(
                    f"processed_frames={processed_frames}/{render_frame_count}, "
                    f"masked_regions={masked_region_observations}"
                )
    finally:
        cap.release()
        writer.release()

    if processed_frames != render_frame_count:
        raise RuntimeError(
            f"privacy media ended early: expected={render_frame_count}, "
            f"actual={processed_frames}"
        )
    if representative_frame is None:
        raise RuntimeError("no representative frame was produced")

    image_output.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(image_output), representative_frame):
        raise RuntimeError(f"failed to write representative image: {image_output}")

    elapsed_sec = time.perf_counter() - started_at
    processing_fps = processed_frames / elapsed_sec if elapsed_sec else 0.0
    summary = {
        "schema_version": 1,
        "stage": "L3-2_privacy_safe_roi_media",
        "storage_stage": "experimental_candidate",
        "camera_id": roi_config["camera_id"],
        "roi_id": roi_config["primary_roi_id"],
        "source_video": str(video_path),
        "source_video_preserved": True,
        "settings": {
            "model": str(model_path),
            "device": args.device,
            "imgsz": args.imgsz,
            "confidence_threshold": args.conf,
            "start_sec": args.start_sec,
            "max_seconds": args.max_seconds,
            "mask_method": "person_bbox_upper_mosaic",
            "mask_top_ratio": args.mask_top_ratio,
            "mosaic_block_size": args.mosaic_block_size,
        },
        "results": {
            "width": width,
            "height": height,
            "source_fps": fps,
            "processed_frames": processed_frames,
            "detection_observations": detection_observations,
            "roi_detection_observations": roi_detection_observations,
            "masked_region_observations": masked_region_observations,
            "representative_source_frame_index": representative_source_frame_index,
            "representative_timestamp_sec": representative_source_frame_index / fps,
            "processing_elapsed_sec": round(elapsed_sec, 3),
            "processing_fps": round(processing_fps, 3),
            "realtime_factor": round(processing_fps / fps, 3),
        },
        "artifacts": {
            "masked_video": str(video_output),
            "masked_representative_image": str(image_output),
            "qa_summary": str(summary_output),
        },
        "promotion_policy": {
            "current_location": "outputs",
            "promote_to": "data/processed",
            "condition": "manual privacy QA approval and stable artifact contract",
            "dvc_gcs_scope": "data/processed only",
        },
        "limitations": [
            "This is person-bbox upper-region mosaicing, not face detection or face recognition.",
            "A person missed by YOLO is not masked by this stage.",
            "The AIHub MVP source already includes dataset-provided de-identification; "
            "this stage adds a second heuristic privacy filter.",
            "The media contains frame-level detections, not unique visitors or line-crossing events.",
        ],
    }
    summary_output.parent.mkdir(parents=True, exist_ok=True)
    summary_output.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(f"processed_frames={processed_frames}")
    print(f"masked_region_observations={masked_region_observations}")
    print(f"processing_elapsed_sec={elapsed_sec:.3f}")
    print(f"processing_fps={processing_fps:.3f}")
    print(f"masked_video={video_output}")
    print(f"masked_image={image_output}")
    print(f"qa_summary={summary_output}")


if __name__ == "__main__":
    main()
