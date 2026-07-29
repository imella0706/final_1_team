#!/usr/bin/env python3
"""Select a manual visitor-flow ROI on a reference frame."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import cv2
import numpy as np


# [Design Intent] ROI selection is an operator tool, not part of batch
# aggregation. The saved normalized polygon is then consumed by
# visitor_flow_l3_roi_aggregate.py so ROI edits never require YOLO inference again.
REPO_ROOT = Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Click ROI polygon vertices on an image and save a config JSON."
    )
    parser.add_argument("--image", required=True, type=Path, help="Reference frame path.")
    parser.add_argument(
        "--output",
        default=Path("configs/visitor_flow/c0241_roi_config.json"),
        type=Path,
        help="Output ROI config JSON path.",
    )
    parser.add_argument("--camera-id", default="C0241")
    parser.add_argument("--roi-id", default="in_front_of_shop")
    parser.add_argument("--label", default="Storefront pedestrian lane")
    return parser.parse_args()


def resolve_repo_path(path: Path) -> Path:
    path = path.expanduser()
    if path.is_absolute():
        return path
    return REPO_ROOT / path


def draw_preview(image: np.ndarray, points: list[tuple[int, int]]) -> np.ndarray:
    preview = image.copy()
    for index, point in enumerate(points):
        cv2.circle(preview, point, 6, (0, 0, 255), -1)
        cv2.putText(
            preview,
            str(index + 1),
            (point[0] + 8, point[1] - 8),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            (0, 0, 255),
            2,
            cv2.LINE_AA,
        )
    if len(points) > 1:
        cv2.polylines(preview, [np.array(points, dtype=np.int32)], False, (0, 255, 255), 3)
    if len(points) > 2:
        overlay = preview.copy()
        cv2.fillPoly(overlay, [np.array(points, dtype=np.int32)], (0, 255, 255))
        preview = cv2.addWeighted(overlay, 0.18, preview, 0.82, 0)
        cv2.polylines(preview, [np.array(points, dtype=np.int32)], True, (0, 255, 255), 3)
    return preview


def build_config(
    *,
    camera_id: str,
    roi_id: str,
    label: str,
    points: list[tuple[int, int]],
    width: int,
    height: int,
) -> dict[str, Any]:
    polygon = [
        {"x": round(x / width, 6), "y": round(y / height, 6)} for x, y in points
    ]
    return {
        "schema_version": 1,
        "camera_id": camera_id,
        "primary_roi_id": roi_id,
        "label": label,
        "coordinate_space": "normalized_image",
        "position_point": "bbox_bottom_center",
        "definition_source": "manual_polygon",
        "boundary_inclusive": True,
        "polygon": polygon,
        "notes": [
            "Manual ROI selected from a fixed-camera reference frame.",
            "A detection is counted when its bbox bottom-center point is inside this polygon.",
            "Recalibrate this polygon if the camera position or crop changes.",
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
    window_name = "Visitor Flow ROI selector"

    def on_mouse(event: int, x: int, y: int, _flags: int, _param: object) -> None:
        if event == cv2.EVENT_LBUTTONDOWN:
            points.append((x, y))
        elif event == cv2.EVENT_RBUTTONDOWN and points:
            points.pop()
        cv2.imshow(window_name, draw_preview(image, points))

    cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)
    cv2.imshow(window_name, draw_preview(image, points))
    cv2.setMouseCallback(window_name, on_mouse)

    print("Left click: add point | Right click: undo | s: save | q/esc: quit")
    while True:
        key = cv2.waitKey(20) & 0xFF
        if key == ord("s"):
            if len(points) < 3:
                print("[error] Need at least 3 points before saving.")
                continue
            height, width = image.shape[:2]
            config = build_config(
                camera_id=args.camera_id,
                roi_id=args.roi_id,
                label=args.label,
                points=points,
                width=width,
                height=height,
            )
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(
                json.dumps(config, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            print(f"[ok] saved ROI config: {output_path}")
            break
        if key in {ord("q"), 27}:
            print("[skip] ROI config was not saved.")
            break

    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
