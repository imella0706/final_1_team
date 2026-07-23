"""GroundingDINO 상자와 SAM 2 마스크로 CVAT 검수용 COCO 초안을 만든다."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from app.services.grounding_dino import GroundingDINODetector, split_plate_and_food_boxes
from app.services.segmentation import SAM2Segmenter, SegmenterRuntimeError


CLASS_IDS = {"plate_full": 1, "food_visible": 2}


def parse_args() -> argparse.Namespace:
    root = Path(__file__).resolve().parents[1] / "data/training/plate_segmentation"
    parser = argparse.ArgumentParser(description="GroundingDINO + SAM 2로 CVAT 검수용 COCO 초안을 만듭니다.")
    parser.add_argument("--images-dir", type=Path, default=root / "cvat_images")
    parser.add_argument("--manifest", type=Path, default=root / "plate_annotation_manifest.csv")
    parser.add_argument("--output-dir", type=Path, default=root / "auto_annotations")
    parser.add_argument("--grounding-model-id", default="IDEA-Research/grounding-dino-tiny")
    parser.add_argument("--sam-weights", default="models/sam2.1_t.pt")
    parser.add_argument("--device", default="auto")
    parser.add_argument("--box-threshold", type=float, default=0.28)
    parser.add_argument("--text-threshold", type=float, default=0.22)
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def mask_to_annotation(mask: np.ndarray, image_id: int, category_id: int, annotation_id: int) -> dict[str, Any] | None:
    binary = (mask > 0).astype(np.uint8)
    contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    polygons: list[list[float]] = []
    for contour in contours:
        if cv2.contourArea(contour) < 64:
            continue
        points = contour.reshape(-1, 2)
        if len(points) < 3:
            continue
        polygons.append(points.astype(float).reshape(-1).tolist())
    if not polygons:
        return None
    x, y, width, height = cv2.boundingRect(binary)
    return {
        "id": annotation_id,
        "image_id": image_id,
        "category_id": category_id,
        "segmentation": polygons,
        "area": float(np.count_nonzero(binary)),
        "bbox": [float(x), float(y), float(width), float(height)],
        "iscrowd": 0,
    }


def overlay(image: np.ndarray, plate_mask: np.ndarray, food_mask: np.ndarray) -> np.ndarray:
    result = image.copy()
    for mask, color in ((plate_mask, (255, 120, 0)), (food_mask, (0, 220, 0))):
        if np.any(mask):
            tint = np.full_like(result, color)
            selector = mask > 0
            result[selector] = cv2.addWeighted(result[selector], 0.55, tint[selector], 0.45, 0)
            contours, _ = cv2.findContours((mask > 0).astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            cv2.drawContours(result, contours, -1, color, 2)
    return result


def update_manifest(path: Path, states: dict[str, dict[str, Any]]) -> None:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
        fields = list(rows[0]) if rows else []
    additions = ["auto_annotation_status", "auto_plate_boxes", "auto_food_boxes", "auto_annotation_note"]
    for field in additions:
        if field not in fields:
            fields.append(field)
    for row in rows:
        state = states.get(row["image_file_name"])
        if state is None:
            continue
        row.update(state)
        if state["auto_annotation_status"] == "needs_review":
            row["plate_full_status"] = "needs_review"
            row["food_visible_status"] = "needs_review"
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    args = parse_args()
    if not args.manifest.is_file():
        raise SystemExit(
            "작업 목록이 없습니다. 먼저 다음 명령으로 이미지 500장과 "
            f"plate_annotation_manifest.csv를 만드세요:\n"
            "python -m scripts.prepare_plate_annotation_manifest --sample-size 500\n"
            f"현재 기대 경로: {args.manifest}"
        )
    if not args.images_dir.is_dir():
        raise SystemExit(f"CVAT 입력 이미지 폴더가 없습니다: {args.images_dir}")
    if args.output_dir.exists() and any(args.output_dir.iterdir()) and not args.overwrite:
        raise SystemExit(f"기존 초안을 보존합니다. 새 폴더를 쓰거나 --overwrite를 사용하세요: {args.output_dir}")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    preview_dir = args.output_dir / "review_previews"
    preview_dir.mkdir(exist_ok=True)
    detector = GroundingDINODetector(
        {
            "model_id": args.grounding_model_id,
            "device": args.device,
            "box_threshold": args.box_threshold,
            "text_threshold": args.text_threshold,
            "prompts": ["plate", "dish", "bowl", "food"],
        }
    )
    segmenter = SAM2Segmenter({"enabled": True, "weights": args.sam_weights, "device": args.device})
    images: list[dict[str, Any]] = []
    annotations: list[dict[str, Any]] = []
    states: dict[str, dict[str, Any]] = {}
    annotation_id = 1
    for image_id, path in enumerate(sorted(args.images_dir.glob("*")), start=1):
        if path.suffix.lower() not in {".jpg", ".jpeg", ".png", ".webp"}:
            continue
        image = cv2.imread(str(path), cv2.IMREAD_COLOR)
        if image is None:
            states[path.name] = {"auto_annotation_status": "failed", "auto_annotation_note": "이미지 읽기 실패"}
            continue
        height, width = image.shape[:2]
        images.append({"id": image_id, "file_name": path.name, "width": width, "height": height})
        try:
            detections = detector.detect(image)
            plate_boxes, food_boxes, _ = split_plate_and_food_boxes(detections)
            plate_mask = segmenter.segment(image, plate_boxes).mask
            food_mask = segmenter.segment(image, food_boxes).mask
        except (RuntimeError, SegmenterRuntimeError) as exc:
            states[path.name] = {
                "auto_annotation_status": "failed",
                "auto_plate_boxes": "0",
                "auto_food_boxes": "0",
                "auto_annotation_note": str(exc),
            }
            continue
        plate_annotation = mask_to_annotation(plate_mask, image_id, CLASS_IDS["plate_full"], annotation_id)
        if plate_annotation is not None:
            annotations.append(plate_annotation)
            annotation_id += 1
        food_annotation = mask_to_annotation(food_mask, image_id, CLASS_IDS["food_visible"], annotation_id)
        if food_annotation is not None:
            annotations.append(food_annotation)
            annotation_id += 1
        state = "needs_review" if plate_annotation and food_annotation else "needs_manual_annotation"
        states[path.name] = {
            "auto_annotation_status": state,
            "auto_plate_boxes": str(len(plate_boxes)),
            "auto_food_boxes": str(len(food_boxes)),
            "auto_annotation_note": "GroundingDINO + SAM2 초안. CVAT에서 경계와 클래스 검수 필요.",
        }
        cv2.imwrite(str(preview_dir / f"{path.stem}_draft.jpg"), overlay(image, plate_mask, food_mask))
    payload = {
        "info": {"description": "GroundingDINO + SAM2 접시/음식 자동 주석 초안", "version": "0.1"},
        "licenses": [],
        "categories": [
            {"id": 1, "name": "plate_full", "supercategory": "serving_container"},
            {"id": 2, "name": "food_visible", "supercategory": "food"},
        ],
        "images": images,
        "annotations": annotations,
    }
    output_json = args.output_dir / "instances_draft.json"
    output_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    update_manifest(args.manifest, states)
    summary = {
        "images": len(images),
        "annotations": len(annotations),
        "needs_review": sum(state.get("auto_annotation_status") == "needs_review" for state in states.values()),
        "needs_manual_annotation": sum(state.get("auto_annotation_status") == "needs_manual_annotation" for state in states.values()),
        "failed": sum(state.get("auto_annotation_status") == "failed" for state in states.values()),
        "coco_json": str(output_json),
        "preview_dir": str(preview_dir),
    }
    (args.output_dir / "draft_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
