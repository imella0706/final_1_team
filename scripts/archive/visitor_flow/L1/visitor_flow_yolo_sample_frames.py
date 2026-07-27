# [Design Intent] L1-2에서 영상을 일정 간격으로 샘플링하고,
# person-only YOLO 탐지 결과를 후속 집계가 가능한 CSV로 저장한다.
# 이 스크립트는 실제 방문객 수, tracking, 마케팅 추천을 계산하지 않는다.

import argparse
import csv
from pathlib import Path

import cv2
from ultralytics import YOLO


CSV_FIELDS = [
    "video_id",
    "frame_index",
    "timestamp_sec",
    "bbox_index",
    "bbox_x1",
    "bbox_y1",
    "bbox_x2",
    "bbox_y2",
    "confidence",
    "point_x_norm",
    "point_y_norm",
    "person_detection_observations",
    "detections_in_frame",
]


def parse_args():
    # [Design Intent] 모델과 threshold를 CLI 인자로 받아 동일 영상에서 설정을
    # 바꿔가며 재실험할 수 있게 한다.
    parser = argparse.ArgumentParser(
        description="Sample video frames and save person-only YOLO detections to CSV."
    )
    parser.add_argument("--video", required=True, help="Input mp4 path")
    parser.add_argument("--model", required=True, help="YOLO model weight path")
    parser.add_argument("--conf", required=True, type=float, help="Confidence threshold")
    parser.add_argument("--device", default="cpu", help="Inference device: cpu, cuda, 0")
    parser.add_argument("--imgsz", default=960, type=int, help="YOLO inference image size")
    parser.add_argument(
        "--sample-every-sec",
        default=10.0,
        type=float,
        help="Frame sampling interval in seconds",
    )
    parser.add_argument("--output-csv", required=True, help="Output CSV path")
    parser.add_argument(
        "--save-preview-dir",
        default="",
        help="Optional directory for annotated sampled-frame images",
    )
    return parser.parse_args()


def validate_args(args):
    video_path = Path(args.video)
    model_path = Path(args.model)

    if not video_path.is_file():
        raise FileNotFoundError(f"video not found: {video_path}")
    if not model_path.is_file():
        raise FileNotFoundError(f"model not found: {model_path}")
    if not 0.0 <= args.conf <= 1.0:
        raise ValueError("--conf must be between 0.0 and 1.0")
    if args.imgsz <= 0:
        raise ValueError("--imgsz must be greater than 0")
    if args.sample_every_sec <= 0:
        raise ValueError("--sample-every-sec must be greater than 0")

    return video_path, model_path


def empty_detection_row(video_id, frame_index, timestamp_sec):
    # [Design Intent] 탐지 결과가 0인 프레임도 CSV에서 사라지지 않게 남긴다.
    # 이 행의 person_detection_observations=0은 "사람이 없었다"가 아니라
    # "현재 모델 설정에서 사람 bbox가 관측되지 않았다"는 뜻이다.
    return {
        "video_id": video_id,
        "frame_index": frame_index,
        "timestamp_sec": round(timestamp_sec, 3),
        "bbox_index": "",
        "bbox_x1": "",
        "bbox_y1": "",
        "bbox_x2": "",
        "bbox_y2": "",
        "confidence": "",
        "point_x_norm": "",
        "point_y_norm": "",
        "person_detection_observations": 0,
        "detections_in_frame": 0,
    }


def detection_rows(result, video_id, frame_index, timestamp_sec, width, height):
    if result.boxes is None or len(result.boxes) == 0:
        return [empty_detection_row(video_id, frame_index, timestamp_sec)]

    xyxy_values = result.boxes.xyxy.cpu().tolist()
    confidence_values = result.boxes.conf.cpu().tolist()
    detections_in_frame = len(xyxy_values)
    rows = []

    for bbox_index, (xyxy, confidence) in enumerate(
        zip(xyxy_values, confidence_values)
    ):
        x1, y1, x2, y2 = xyxy

        # [Design Intent] bbox bottom-center를 사람의 바닥 접점 proxy로 사용한다.
        # 0~1 정규화 좌표라서 해상도가 다른 영상에도 같은 grid 규칙을 적용할 수 있다.
        point_x_norm = ((x1 + x2) / 2.0) / width
        point_y_norm = y2 / height

        rows.append(
            {
                "video_id": video_id,
                "frame_index": frame_index,
                "timestamp_sec": round(timestamp_sec, 3),
                "bbox_index": bbox_index,
                "bbox_x1": round(x1, 2),
                "bbox_y1": round(y1, 2),
                "bbox_x2": round(x2, 2),
                "bbox_y2": round(y2, 2),
                "confidence": round(confidence, 6),
                "point_x_norm": round(point_x_norm, 6),
                "point_y_norm": round(point_y_norm, 6),
                "person_detection_observations": 1,
                "detections_in_frame": detections_in_frame,
            }
        )

    return rows


def save_annotated_preview(
    result,
    preview_dir,
    frame_index,
    timestamp_sec,
    detections_in_frame,
    conf,
):
    annotated = result.plot()
    cv2.putText(
        annotated,
        (
            f"frame={frame_index} time={timestamp_sec:.1f}s "
            f"persons={detections_in_frame} conf={conf}"
        ),
        (20, 40),
        cv2.FONT_HERSHEY_SIMPLEX,
        1.0,
        (0, 255, 255),
        2,
    )
    preview_path = preview_dir / (
        f"frame_{frame_index:06d}_time_{timestamp_sec:07.1f}s.jpg"
    )
    if not cv2.imwrite(str(preview_path), annotated):
        raise RuntimeError(f"failed to save preview image: {preview_path}")


def main():
    args = parse_args()
    video_path, model_path = validate_args(args)
    output_csv = Path(args.output_csv)
    preview_dir = Path(args.save_preview_dir) if args.save_preview_dir else None

    output_csv.parent.mkdir(parents=True, exist_ok=True)
    if preview_dir is not None:
        preview_dir.mkdir(parents=True, exist_ok=True)

    model = YOLO(str(model_path))
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"failed to open video: {video_path}")

    fps = cap.get(cv2.CAP_PROP_FPS)
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    if fps <= 0:
        cap.release()
        raise RuntimeError(f"invalid video fps: {fps}")
    if frame_count <= 0 or width <= 0 or height <= 0:
        cap.release()
        raise RuntimeError(
            f"invalid video metadata: frames={frame_count}, size={width}x{height}"
        )

    # [Design Intent] 초 단위 샘플 간격을 영상 fps 기준 frame 간격으로 변환한다.
    sample_step_frames = max(1, round(fps * args.sample_every_sec))
    duration_sec = frame_count / fps

    print(f"video={video_path}")
    print(
        f"fps={fps:.2f}, frames={frame_count}, "
        f"size={width}x{height}, duration={duration_sec:.1f}s"
    )
    print(
        f"model={model_path}, conf={args.conf}, device={args.device}, "
        f"imgsz={args.imgsz}"
    )
    print(
        f"sample_every_sec={args.sample_every_sec}, "
        f"sample_step_frames={sample_step_frames}"
    )

    sampled_frame_count = 0
    detection_observation_count = 0
    csv_row_count = 0

    try:
        with output_csv.open("w", encoding="utf-8", newline="") as csv_file:
            writer = csv.DictWriter(csv_file, fieldnames=CSV_FIELDS)
            writer.writeheader()

            for frame_index in range(0, frame_count, sample_step_frames):
                cap.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
                ok, frame = cap.read()
                if not ok:
                    print(f"warning: failed to read frame={frame_index}; skipped")
                    continue

                timestamp_sec = frame_index / fps
                result = model.predict(
                    frame,
                    classes=[0],
                    conf=args.conf,
                    device=args.device,
                    imgsz=args.imgsz,
                    verbose=False,
                )[0]

                rows = detection_rows(
                    result=result,
                    video_id=video_path.stem,
                    frame_index=frame_index,
                    timestamp_sec=timestamp_sec,
                    width=width,
                    height=height,
                )
                writer.writerows(rows)

                detections_in_frame = sum(
                    int(row["person_detection_observations"]) for row in rows
                )
                sampled_frame_count += 1
                detection_observation_count += detections_in_frame
                csv_row_count += len(rows)

                print(
                    f"frame={frame_index}, time={timestamp_sec:.1f}s, "
                    f"person_detection_observations={detections_in_frame}"
                )

                if preview_dir is not None:
                    save_annotated_preview(
                        result=result,
                        preview_dir=preview_dir,
                        frame_index=frame_index,
                        timestamp_sec=timestamp_sec,
                        detections_in_frame=detections_in_frame,
                        conf=args.conf,
                    )
    finally:
        cap.release()

    print(f"sampled_frames={sampled_frame_count}")
    print(f"person_detection_observations={detection_observation_count}")
    print(f"csv_rows={csv_row_count}")
    print(f"output_csv={output_csv}")
    if preview_dir is not None:
        print(f"preview_dir={preview_dir}")


if __name__ == "__main__":
    main()
