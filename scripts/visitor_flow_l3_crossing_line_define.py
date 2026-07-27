#!/usr/bin/env python3
"""Select a manual visitor-flow line-crossing reference line."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import cv2
import numpy as np


# [Design Intent] L3-5 line definition is an operator calibration tool. It
# stores a normalized two-point line so later crossing aggregation can use the
# same config across 1080p frames without rerunning manual calibration.
REPO_ROOT = Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Click two points on an image and save a line-crossing config JSON."
    )
    parser.add_argument("--image", required=True, type=Path, help="Reference frame path.")
    parser.add_argument(
        "--output",
        default=Path("configs/visitor_flow/c0241_crossing_config.json"),
        type=Path,
        help="Output line-crossing config JSON path.",
    )
    parser.add_argument("--camera-id", default="C0241")
    parser.add_argument("--line-id", default="walkway_up_down_flow")
    parser.add_argument("--label", default="Walkway up/down pedestrian flow")
    parser.add_argument(
        "--negative-to-positive-label",
        default="screen_downward_event",
        help=(
            "Direction label when a track moves from the negative side to the "
            "positive side of the directed line. For a left-to-right horizontal "
            "line, this is screen top-to-bottom."
        ),
    )
    parser.add_argument(
        "--positive-to-negative-label",
        default="screen_upward_event",
        help=(
            "Direction label when a track moves from the positive side to the "
            "negative side of the directed line. For a left-to-right horizontal "
            "line, this is screen bottom-to-top."
        ),
    )
    return parser.parse_args()


def resolve_repo_path(path: Path) -> Path:
    path = path.expanduser()
    if path.is_absolute():
        return path
    return REPO_ROOT / path


def draw_preview(image: np.ndarray, points: list[tuple[int, int]]) -> np.ndarray:
    preview = image.copy()
    for index, point in enumerate(points):
        cv2.circle(preview, point, 7, (0, 0, 255), -1)
        cv2.putText(
            preview,
            "start" if index == 0 else "end",
            (point[0] + 10, point[1] - 10),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            (0, 0, 255),
            2,
            cv2.LINE_AA,
        )
    if len(points) == 2:
        cv2.line(preview, points[0], points[1], (0, 0, 255), 5, cv2.LINE_AA)
        midpoint = (
            int((points[0][0] + points[1][0]) / 2),
            int((points[0][1] + points[1][1]) / 2),
        )
        cv2.putText(
            preview,
            "L3-5 crossing line",
            (midpoint[0] + 12, midpoint[1] - 12),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.75,
            (0, 0, 255),
            2,
            cv2.LINE_AA,
        )
    return preview


def build_config(
    *,
    camera_id: str,
    line_id: str,
    label: str,
    points: list[tuple[int, int]],
    width: int,
    height: int,
    negative_to_positive_label: str,
    positive_to_negative_label: str,
) -> dict[str, Any]:
    line = [{"x": round(x / width, 6), "y": round(y / height, 6)} for x, y in points]
    return {
        "schema_version": 1,
        "camera_id": camera_id,
        "primary_line_id": line_id,
        "label": label,
        "coordinate_space": "normalized_image",
        "position_point": "bbox_bottom_center",
        "definition_source": "manual_line",
        "line": line,
        "direction_labels": {
            "negative_to_positive": negative_to_positive_label,
            "positive_to_negative": positive_to_negative_label,
        },
        "notes": [
            "Manual crossing line selected from a fixed-camera reference frame.",
            "For C0241 walkway flow, click the left endpoint first and the right endpoint second.",
            "A crossing event is based on track bbox bottom-center movement across this line.",
            "This is a movement event signal, not a unique visitor count or store entry count.",
            "Recalibrate this line if the camera position or crop changes.",
        ],
    }


def main() -> None:
    args = parse_args()
    image_path = resolve_repo_path(args.image)
    output_path = resolve_repo_path(args.output)

    image = cv2.imread(str(image_path))
    if image is None:
        raise FileNotFoundError(f"failed to read reference image: {image_path}")

    points: list[tuple[int, int]] = []
    window_name = "Visitor Flow L3-5 crossing line selector"

    def on_mouse(event: int, x: int, y: int, _flags: int, _param: object) -> None:
        if event == cv2.EVENT_LBUTTONDOWN:
            if len(points) >= 2:
                points.clear()
            points.append((x, y))
        elif event == cv2.EVENT_RBUTTONDOWN and points:
            points.pop()
        cv2.imshow(window_name, draw_preview(image, points))

    cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)
    cv2.imshow(window_name, draw_preview(image, points))
    cv2.setMouseCallback(window_name, on_mouse)

    print(
        "Left click: start/end point | Right click: undo | "
        "s: save | q/esc: quit"
    )
    print("[tip] For the red horizontal walkway line, click left endpoint first.")
    while True:
        key = cv2.waitKey(20) & 0xFF
        if key == ord("s"):
            if len(points) != 2:
                print("[error] Need exactly 2 points before saving.")
                continue
            height, width = image.shape[:2]
            config = build_config(
                camera_id=args.camera_id,
                line_id=args.line_id,
                label=args.label,
                points=points,
                width=width,
                height=height,
                negative_to_positive_label=args.negative_to_positive_label,
                positive_to_negative_label=args.positive_to_negative_label,
            )
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(
                json.dumps(config, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            print(f"[ok] saved crossing line config: {output_path}")
            break
        if key in {ord("q"), 27}:
            print("[skip] crossing line config was not saved.")
            break

    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
