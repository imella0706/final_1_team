# [Design Intent] YOLO 탐지 결과를 직접 눈으로 검증하기 위한 L1 preview CLI다.
# 아직 집계, Parquet, Streamlit, 마케팅 추천은 넣지 않는다.

import argparse
from pathlib import Path

import cv2
from ultralytics import YOLO


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--video", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--conf", required=True, type=float)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--imgsz", default=960, type=int)
    parser.add_argument("--save-output", default="")
    parser.add_argument("--no-window", action="store_true")
    return parser.parse_args()


def main():
    args = parse_args()

    video_path = Path(args.video)
    model_path = Path(args.model)

    if not video_path.exists():
        raise FileNotFoundError(f"video not found: {video_path}")
    if not model_path.exists():
        raise FileNotFoundError(f"model not found: {model_path}")

    model = YOLO(str(model_path))
    cap = cv2.VideoCapture(str(video_path))

    if not cap.isOpened():
        raise RuntimeError(f"failed to open video: {video_path}")

    fps = cap.get(cv2.CAP_PROP_FPS) or 1
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    duration_sec = frame_count / fps

    print(f"video={video_path}")
    print(f"fps={fps:.2f}, frames={frame_count}, size={width}x{height}, duration={duration_sec:.1f}s")
    print(f"model={model_path}, conf={args.conf}, device={args.device}, imgsz={args.imgsz}")

    writer = None
    if args.save_output:
        output_path = Path(args.save_output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        writer = cv2.VideoWriter(str(output_path), fourcc, fps, (width, height))
        print(f"save_output={output_path}")

    frame_index = 0
    wait_ms = max(1, int(1000 / fps))

    while True:
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

        person_count = 0 if result.boxes is None else len(result.boxes)
        timestamp_sec = frame_index / fps

        annotated = result.plot()
        cv2.putText(
            annotated,
            f"frame={frame_index} time={timestamp_sec:.1f}s persons={person_count} conf={args.conf}",
            (20, 40),
            cv2.FONT_HERSHEY_SIMPLEX,
            1.0,
            (0, 255, 255),
            2,
        )

        if frame_index % int(max(1, fps * 5)) == 0:
            print(f"frame={frame_index}, time={timestamp_sec:.1f}s, persons={person_count}")

        if writer is not None:
            writer.write(annotated)

        if not args.no_window:
            cv2.imshow("Visitor Flow YOLO Preview", annotated)
            key = cv2.waitKey(wait_ms) & 0xFF
            if key == ord("q"):
                break

        frame_index += 1

    cap.release()
    if writer is not None:
        writer.release()
    if not args.no_window:
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()