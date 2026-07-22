#!/usr/bin/env python3
"""Render a browser-playable L2 qualitative YOLO preview video."""

from __future__ import annotations

import argparse
from pathlib import Path

import cv2
from ultralytics import YOLO


# [Design Intent] L2 집계 수치와 별개로 연속 프레임의 탐지 품질을 사람이 직접
# 감사할 수 있도록 bbox/grid overlay 영상을 오프라인 artifact로 생성한다.
# 이 영상의 frame별 detection 수는 L2-1의 10초 sampling 집계에 포함하지 않는다.


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create an annotated WebM video for L2 qualitative visual QA."
    )
    parser.add_argument("--video", required=True, type=Path)
    parser.add_argument("--model", required=True, type=Path)
    parser.add_argument("--conf", required=True, type=float)
    parser.add_argument("--device", default="cpu", help="Inference device: cpu, cuda, 0")
    parser.add_argument("--imgsz", default=960, type=int)
    parser.add_argument("--grid-cols", default=6, type=int)
    parser.add_argument("--grid-rows", default=4, type=int)
    parser.add_argument(
        "--max-seconds",
        default=0.0,
        type=float,
        help="Render only the first N seconds. 0 renders the full clip.",
    )
    parser.add_argument(
        "--start-sec",
        default=0.0,
        type=float,
        help="Start rendering from this second in the source video.",
    )
    parser.add_argument("--output", required=True, type=Path)
    return parser.parse_args()


def validate_args(args: argparse.Namespace) -> None:
    if not args.video.is_file():
        raise FileNotFoundError(f"video not found: {args.video}")
    if not args.model.is_file():
        raise FileNotFoundError(f"model not found: {args.model}")
    if not 0.0 <= args.conf <= 1.0:
        raise ValueError("--conf must be between 0.0 and 1.0")
    if args.imgsz <= 0:
        raise ValueError("--imgsz must be greater than 0")
    if args.grid_cols <= 0 or args.grid_rows <= 0:
        raise ValueError("--grid-cols and --grid-rows must be greater than 0")
    if args.max_seconds < 0:
        raise ValueError("--max-seconds must be 0 or greater")
    if args.start_sec < 0:
        raise ValueError("--start-sec must be 0 or greater")
    if args.output.suffix.lower() != ".webm":
        raise ValueError("--output must end with .webm for browser playback")


def zone_id_from_bottom_center(
    x1: float,
    y2: float,
    x2: float,
    width: int,
    height: int,
    grid_cols: int,
    grid_rows: int,
) -> str:
    point_x = min(width - 1, max(0, round((x1 + x2) / 2.0)))
    point_y = min(height - 1, max(0, round(y2)))
    col = min(grid_cols - 1, int((point_x / width) * grid_cols))
    row = min(grid_rows - 1, int((point_y / height) * grid_rows))
    return f"r{row}_c{col}"


def draw_grid(frame, grid_cols: int, grid_rows: int) -> None:
    height, width = frame.shape[:2]
    color = (0, 215, 255)
    for col in range(1, grid_cols):
        x = round(width * col / grid_cols)
        cv2.line(frame, (x, 0), (x, height), color, 1, cv2.LINE_AA)
    for row in range(1, grid_rows):
        y = round(height * row / grid_rows)
        cv2.line(frame, (0, y), (width, y), color, 1, cv2.LINE_AA)

    for row in range(grid_rows):
        for col in range(grid_cols):
            x = round(width * col / grid_cols) + 8
            y = round(height * row / grid_rows) + 24
            cv2.putText(
                frame,
                f"r{row}_c{col}",
                (x, y),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.55,
                color,
                1,
                cv2.LINE_AA,
            )


def draw_detections(frame, result, grid_cols: int, grid_rows: int) -> int:
    if result.boxes is None or len(result.boxes) == 0:
        return 0

    height, width = frame.shape[:2]
    xyxy_values = result.boxes.xyxy.cpu().tolist()
    confidence_values = result.boxes.conf.cpu().tolist()
    for xyxy, confidence in zip(xyxy_values, confidence_values):
        x1, y1, x2, y2 = (float(value) for value in xyxy)
        zone_id = zone_id_from_bottom_center(
            x1=x1,
            y2=y2,
            x2=x2,
            width=width,
            height=height,
            grid_cols=grid_cols,
            grid_rows=grid_rows,
        )
        left, top, right, bottom = map(round, (x1, y1, x2, y2))
        point_x = round((x1 + x2) / 2.0)
        point_y = round(y2)
        color = (40, 220, 40)
        cv2.rectangle(frame, (left, top), (right, bottom), color, 2)
        cv2.circle(frame, (point_x, point_y), 5, (0, 0, 255), -1)
        cv2.putText(
            frame,
            f"person {confidence:.2f} | {zone_id}",
            (left, max(24, top - 8)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.65,
            color,
            2,
            cv2.LINE_AA,
        )
    return len(xyxy_values)


def main() -> None:
    args = parse_args()
    validate_args(args)

    model = YOLO(str(args.model))
    cap = cv2.VideoCapture(str(args.video))
    if not cap.isOpened():
        raise RuntimeError(f"failed to open video: {args.video}")

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
    cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame_index)

    remaining_frame_count = frame_count - start_frame_index
    render_frame_count = remaining_frame_count
    if args.max_seconds > 0:
        render_frame_count = min(remaining_frame_count, max(1, round(fps * args.max_seconds)))

    args.output.parent.mkdir(parents=True, exist_ok=True)
    writer = cv2.VideoWriter(
        str(args.output),
        cv2.VideoWriter_fourcc(*"VP80"),
        fps,
        (width, height),
    )
    if not writer.isOpened():
        cap.release()
        raise RuntimeError(f"failed to open WebM writer: {args.output}")

    print(f"video={args.video}")
    print(f"start_sec={args.start_sec:.1f}, start_frame_index={start_frame_index}")
    print(f"frames_to_render={render_frame_count}, fps={fps:.2f}, size={width}x{height}")
    print(f"conf={args.conf:.2f}, device={args.device}, imgsz={args.imgsz}")
    print(f"output={args.output}")

    processed_frames = 0
    total_detection_observations = 0
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
            draw_grid(frame, grid_cols=args.grid_cols, grid_rows=args.grid_rows)
            detection_count = draw_detections(
                frame,
                result=result,
                grid_cols=args.grid_cols,
                grid_rows=args.grid_rows,
            )
            total_detection_observations += detection_count
            source_frame_index = start_frame_index + processed_frames
            timestamp_sec = source_frame_index / fps
            cv2.rectangle(frame, (0, height - 58), (width, height), (0, 0, 0), -1)
            cv2.putText(
                frame,
                (
                    f"frame={source_frame_index} time={timestamp_sec:.1f}s "
                    f"person detections={detection_count} conf={args.conf:.2f} "
                    "| visual QA, not unique people"
                ),
                (18, height - 18),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.8,
                (255, 255, 255),
                2,
                cv2.LINE_AA,
            )
            writer.write(frame)
            processed_frames += 1

            if processed_frames % max(1, round(fps * 10)) == 0:
                print(
                    f"processed_frames={processed_frames}/{render_frame_count}, "
                    f"detection_observations={total_detection_observations}"
                )
    finally:
        cap.release()
        writer.release()

    if processed_frames != render_frame_count:
        raise RuntimeError(
            f"preview ended early: expected={render_frame_count}, actual={processed_frames}"
        )
    print(f"processed_frames={processed_frames}")
    print(f"preview_detection_observations={total_detection_observations}")
    print(f"output={args.output}")


if __name__ == "__main__":
    main()
