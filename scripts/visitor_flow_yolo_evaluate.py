#!/usr/bin/env python3
"""Evaluate sampled person-only YOLO detections against AIHub bbox labels."""

from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

import cv2
from ultralytics import YOLO


# [Design Intent] L1-3은 방문객 수를 계산하는 단계가 아니라, 같은 프레임의
# YOLO bbox와 AIHub 정답 bbox를 비교해 탐지 모델의 오류를 정량화하는 단계다.


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Evaluate sampled YOLO person detections against AIHub labels."
    )
    parser.add_argument("--video", required=True, type=Path, help="Input mp4 path")
    parser.add_argument("--label", required=True, type=Path, help="AIHub label JSON")
    parser.add_argument("--model", required=True, type=Path, help="YOLO weight path")
    parser.add_argument("--device", default="cpu", help="Inference device: cpu, cuda, 0")
    parser.add_argument("--imgsz", default=960, type=int, help="YOLO inference image size")
    parser.add_argument(
        "--sample-every-sec",
        default=10.0,
        type=float,
        help="Frame sampling interval in seconds",
    )
    parser.add_argument(
        "--conf-thresholds",
        nargs="+",
        type=float,
        default=[0.25, 0.40, 0.50, 0.60, 0.70],
        help="Confidence thresholds to compare",
    )
    parser.add_argument(
        "--iou-threshold",
        default=0.50,
        type=float,
        help="Minimum IoU for a prediction/ground-truth match",
    )
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument(
        "--save-previews",
        action="store_true",
        help="Save selected-threshold GT/TP/FP/FN preview images",
    )
    return parser.parse_args()


def validate_args(args: argparse.Namespace) -> list[float]:
    for path, name in (
        (args.video, "video"),
        (args.label, "label"),
        (args.model, "model"),
    ):
        if not path.is_file():
            raise FileNotFoundError(f"{name} not found: {path}")

    if args.imgsz <= 0:
        raise ValueError("--imgsz must be greater than 0")
    if args.sample_every_sec <= 0:
        raise ValueError("--sample-every-sec must be greater than 0")
    if not 0.0 < args.iou_threshold <= 1.0:
        raise ValueError("--iou-threshold must be in (0.0, 1.0]")
    if not args.conf_thresholds:
        raise ValueError("--conf-thresholds requires at least one value")

    thresholds = sorted(set(args.conf_thresholds))
    if any(not 0.0 <= threshold <= 1.0 for threshold in thresholds):
        raise ValueError("all --conf-thresholds values must be between 0.0 and 1.0")
    return thresholds


def read_label(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def video_metadata(path: Path) -> dict[str, Any]:
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise RuntimeError(f"failed to open video: {path}")

    metadata = {
        "fps": float(cap.get(cv2.CAP_PROP_FPS)),
        "frame_count": int(cap.get(cv2.CAP_PROP_FRAME_COUNT)),
        "width": int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
        "height": int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
    }
    cap.release()
    return metadata


def validate_label_video(
    video_path: Path, label_data: dict[str, Any], metadata: dict[str, Any]
) -> None:
    # [Design Intent] 라벨과 mp4가 다른 영상이면 지표는 전부 무의미해지므로,
    # 파일명과 핵심 메타데이터가 일치하지 않으면 즉시 중단한다.
    label_video = label_data["video"]
    label_width, label_height = label_video["resolution"][:2]
    mismatches = []

    if label_video["file_name"] != video_path.name:
        mismatches.append(
            f"file_name label={label_video['file_name']} video={video_path.name}"
        )
    if int(label_video["total_frame"]) != metadata["frame_count"]:
        mismatches.append(
            "frame_count "
            f"label={label_video['total_frame']} video={metadata['frame_count']}"
        )
    if abs(float(label_video["fps"]) - metadata["fps"]) > 1e-6:
        mismatches.append(f"fps label={label_video['fps']} video={metadata['fps']}")
    if (int(label_width), int(label_height)) != (
        metadata["width"],
        metadata["height"],
    ):
        mismatches.append(
            "resolution "
            f"label={label_width}x{label_height} "
            f"video={metadata['width']}x{metadata['height']}"
        )

    if mismatches:
        raise ValueError("label/video mismatch: " + "; ".join(mismatches))


def labels_by_frame(label_data: dict[str, Any]) -> dict[int, list[dict[str, Any]]]:
    grouped: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for annotation in label_data.get("annotations", []):
        bbox = annotation.get("bbox")
        if not isinstance(bbox, list) or len(bbox) != 4:
            raise ValueError(f"invalid annotation bbox: {annotation}")
        grouped[int(annotation["frame"])].append(
            {
                "gt_id": str(annotation["id"]),
                "bbox": tuple(float(value) for value in bbox),
            }
        )
    return grouped


def collect_predictions(
    video_path: Path,
    model_path: Path,
    device: str,
    imgsz: int,
    confidence_floor: float,
    frame_indices: list[int],
    fps: float,
    labels: dict[int, list[dict[str, Any]]],
) -> dict[int, list[dict[str, Any]]]:
    # [Design Intent] 가장 낮은 confidence에서 YOLO를 한 번만 실행한 뒤,
    # 저장된 confidence를 필터링해 여러 threshold를 동일 조건에서 비교한다.
    model = YOLO(str(model_path))
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"failed to open video: {video_path}")

    predictions: dict[int, list[dict[str, Any]]] = defaultdict(list)
    try:
        for frame_index in frame_indices:
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
            ok, frame = cap.read()
            if not ok:
                raise RuntimeError(f"failed to read frame: {frame_index}")

            result = model.predict(
                frame,
                classes=[0],
                conf=confidence_floor,
                device=device,
                imgsz=imgsz,
                verbose=False,
            )[0]

            if result.boxes is not None:
                xyxy_values = result.boxes.xyxy.cpu().tolist()
                confidence_values = result.boxes.conf.cpu().tolist()
                for prediction_index, (bbox, confidence) in enumerate(
                    zip(xyxy_values, confidence_values)
                ):
                    predictions[frame_index].append(
                        {
                            "prediction_index": prediction_index,
                            "bbox": tuple(float(value) for value in bbox),
                            "confidence": float(confidence),
                        }
                    )

            print(
                f"frame={frame_index}, time={frame_index / fps:.1f}s, "
                f"gt={len(labels.get(frame_index, []))}, "
                f"pred_candidates={len(predictions[frame_index])}"
            )
    finally:
        cap.release()

    return predictions


def bbox_iou(
    left: tuple[float, float, float, float],
    right: tuple[float, float, float, float],
) -> float:
    left_x1, left_y1, left_x2, left_y2 = left
    right_x1, right_y1, right_x2, right_y2 = right

    intersection_x1 = max(left_x1, right_x1)
    intersection_y1 = max(left_y1, right_y1)
    intersection_x2 = min(left_x2, right_x2)
    intersection_y2 = min(left_y2, right_y2)
    intersection_width = max(0.0, intersection_x2 - intersection_x1)
    intersection_height = max(0.0, intersection_y2 - intersection_y1)
    intersection_area = intersection_width * intersection_height

    left_area = max(0.0, left_x2 - left_x1) * max(0.0, left_y2 - left_y1)
    right_area = max(0.0, right_x2 - right_x1) * max(0.0, right_y2 - right_y1)
    union_area = left_area + right_area - intersection_area
    return intersection_area / union_area if union_area > 0.0 else 0.0


def match_boxes(
    ground_truths: list[dict[str, Any]],
    predictions: list[dict[str, Any]],
    iou_threshold: float,
) -> tuple[list[dict[str, Any]], list[int], list[int]]:
    # [Design Intent] 하나의 예측 bbox가 여러 정답을 중복 정답 처리하지 않도록
    # IoU가 큰 쌍부터 greedy 1:1 매칭한다.
    candidates = []
    for gt_index, ground_truth in enumerate(ground_truths):
        for prediction_index, prediction in enumerate(predictions):
            iou = bbox_iou(ground_truth["bbox"], prediction["bbox"])
            if iou >= iou_threshold:
                candidates.append((iou, gt_index, prediction_index))

    candidates.sort(reverse=True)
    matched_gt_indices: set[int] = set()
    matched_prediction_indices: set[int] = set()
    matches = []

    for iou, gt_index, prediction_index in candidates:
        if gt_index in matched_gt_indices:
            continue
        if prediction_index in matched_prediction_indices:
            continue
        matched_gt_indices.add(gt_index)
        matched_prediction_indices.add(prediction_index)
        matches.append(
            {
                "gt_index": gt_index,
                "prediction_index": prediction_index,
                "iou": iou,
            }
        )

    unmatched_gt_indices = [
        index for index in range(len(ground_truths)) if index not in matched_gt_indices
    ]
    unmatched_prediction_indices = [
        index
        for index in range(len(predictions))
        if index not in matched_prediction_indices
    ]
    return matches, unmatched_gt_indices, unmatched_prediction_indices


def safe_divide(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def evaluate_threshold(
    threshold: float,
    frame_indices: list[int],
    labels: dict[int, list[dict[str, Any]]],
    prediction_candidates: dict[int, list[dict[str, Any]]],
    iou_threshold: float,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    total_tp = 0
    total_fp = 0
    total_fn = 0
    frame_rows = []
    detail_rows = []

    for frame_index in frame_indices:
        ground_truths = labels.get(frame_index, [])
        predictions = [
            prediction
            for prediction in prediction_candidates.get(frame_index, [])
            if prediction["confidence"] >= threshold
        ]
        matches, unmatched_gt_indices, unmatched_prediction_indices = match_boxes(
            ground_truths=ground_truths,
            predictions=predictions,
            iou_threshold=iou_threshold,
        )

        tp = len(matches)
        fp = len(unmatched_prediction_indices)
        fn = len(unmatched_gt_indices)
        total_tp += tp
        total_fp += fp
        total_fn += fn
        frame_rows.append(
            {
                "confidence_threshold": threshold,
                "frame_index": frame_index,
                "gt_count": len(ground_truths),
                "prediction_count": len(predictions),
                "tp": tp,
                "fp": fp,
                "fn": fn,
            }
        )

        for match in matches:
            ground_truth = ground_truths[match["gt_index"]]
            prediction = predictions[match["prediction_index"]]
            detail_rows.append(
                detail_row(
                    threshold=threshold,
                    frame_index=frame_index,
                    result="tp",
                    ground_truth=ground_truth,
                    prediction=prediction,
                    iou=match["iou"],
                )
            )
        for gt_index in unmatched_gt_indices:
            detail_rows.append(
                detail_row(
                    threshold=threshold,
                    frame_index=frame_index,
                    result="fn",
                    ground_truth=ground_truths[gt_index],
                    prediction=None,
                    iou=None,
                )
            )
        for prediction_index in unmatched_prediction_indices:
            detail_rows.append(
                detail_row(
                    threshold=threshold,
                    frame_index=frame_index,
                    result="fp",
                    ground_truth=None,
                    prediction=predictions[prediction_index],
                    iou=None,
                )
            )

    precision = safe_divide(total_tp, total_tp + total_fp)
    recall = safe_divide(total_tp, total_tp + total_fn)
    f1 = safe_divide(2 * total_tp, 2 * total_tp + total_fp + total_fn)
    metrics = {
        "confidence_threshold": threshold,
        "iou_threshold": iou_threshold,
        "sampled_frames": len(frame_indices),
        "ground_truth_boxes": total_tp + total_fn,
        "prediction_boxes": total_tp + total_fp,
        "tp": total_tp,
        "fp": total_fp,
        "fn": total_fn,
        "precision": round(precision, 6),
        "recall": round(recall, 6),
        "f1": round(f1, 6),
    }
    return metrics, frame_rows, detail_rows


def detail_row(
    threshold: float,
    frame_index: int,
    result: str,
    ground_truth: dict[str, Any] | None,
    prediction: dict[str, Any] | None,
    iou: float | None,
) -> dict[str, Any]:
    gt_bbox = ground_truth["bbox"] if ground_truth else ("", "", "", "")
    prediction_bbox = (
        prediction["bbox"] if prediction else ("", "", "", "")
    )
    return {
        "confidence_threshold": threshold,
        "frame_index": frame_index,
        "result": result,
        "gt_id": ground_truth["gt_id"] if ground_truth else "",
        "prediction_confidence": (
            round(prediction["confidence"], 6) if prediction else ""
        ),
        "iou": round(iou, 6) if iou is not None else "",
        "gt_x1": gt_bbox[0],
        "gt_y1": gt_bbox[1],
        "gt_x2": gt_bbox[2],
        "gt_y2": gt_bbox[3],
        "pred_x1": prediction_bbox[0],
        "pred_y1": prediction_bbox[1],
        "pred_x2": prediction_bbox[2],
        "pred_y2": prediction_bbox[3],
    }


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise ValueError(f"cannot write empty CSV: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def write_prediction_candidates(
    path: Path,
    video_id: str,
    fps: float,
    frame_indices: list[int],
    prediction_candidates: dict[int, list[dict[str, Any]]],
) -> None:
    rows = []
    for frame_index in frame_indices:
        for prediction in prediction_candidates.get(frame_index, []):
            x1, y1, x2, y2 = prediction["bbox"]
            rows.append(
                {
                    "video_id": video_id,
                    "frame_index": frame_index,
                    "timestamp_sec": round(frame_index / fps, 3),
                    "prediction_index": prediction["prediction_index"],
                    "bbox_x1": round(x1, 2),
                    "bbox_y1": round(y1, 2),
                    "bbox_x2": round(x2, 2),
                    "bbox_y2": round(y2, 2),
                    "confidence": round(prediction["confidence"], 6),
                }
            )

    # 탐지 후보가 하나도 없는 비정상/극단 조건에서도 CSV header는 남긴다.
    fieldnames = [
        "video_id",
        "frame_index",
        "timestamp_sec",
        "prediction_index",
        "bbox_x1",
        "bbox_y1",
        "bbox_x2",
        "bbox_y2",
        "confidence",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def draw_box(
    image: Any,
    bbox: tuple[float, float, float, float],
    color: tuple[int, int, int],
    label: str,
) -> None:
    x1, y1, x2, y2 = (int(round(value)) for value in bbox)
    cv2.rectangle(image, (x1, y1), (x2, y2), color, 2)
    cv2.putText(
        image,
        label,
        (x1, max(20, y1 - 8)),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.55,
        color,
        2,
    )


def save_selected_previews(
    video_path: Path,
    preview_dir: Path,
    frame_indices: list[int],
    labels: dict[int, list[dict[str, Any]]],
    prediction_candidates: dict[int, list[dict[str, Any]]],
    selected_threshold: float,
    iou_threshold: float,
    fps: float,
) -> None:
    # [Design Intent] 숫자만 보고 끝내지 않고 GT/TP/FP/FN을 색으로 겹쳐서,
    # 라벨 오류나 프레임 정렬 오류도 사람이 직접 확인할 수 있게 한다.
    preview_dir.mkdir(parents=True, exist_ok=True)
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"failed to reopen video: {video_path}")

    try:
        for frame_index in frame_indices:
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
            ok, frame = cap.read()
            if not ok:
                raise RuntimeError(f"failed to read preview frame: {frame_index}")

            ground_truths = labels.get(frame_index, [])
            predictions = [
                prediction
                for prediction in prediction_candidates.get(frame_index, [])
                if prediction["confidence"] >= selected_threshold
            ]
            matches, unmatched_gt_indices, unmatched_prediction_indices = match_boxes(
                ground_truths=ground_truths,
                predictions=predictions,
                iou_threshold=iou_threshold,
            )

            matched_gt_indices = {match["gt_index"] for match in matches}
            for gt_index, ground_truth in enumerate(ground_truths):
                if gt_index in matched_gt_indices:
                    draw_box(frame, ground_truth["bbox"], (0, 200, 0), "GT matched")
                else:
                    draw_box(frame, ground_truth["bbox"], (0, 165, 255), "FN GT")

            for match in matches:
                prediction = predictions[match["prediction_index"]]
                draw_box(
                    frame,
                    prediction["bbox"],
                    (255, 0, 0),
                    f"TP {prediction['confidence']:.2f} IoU {match['iou']:.2f}",
                )
            for prediction_index in unmatched_prediction_indices:
                prediction = predictions[prediction_index]
                draw_box(
                    frame,
                    prediction["bbox"],
                    (0, 0, 255),
                    f"FP {prediction['confidence']:.2f}",
                )

            header = (
                f"frame={frame_index} time={frame_index / fps:.1f}s "
                f"conf={selected_threshold:.2f} GT={len(ground_truths)} "
                f"TP={len(matches)} FP={len(unmatched_prediction_indices)} "
                f"FN={len(unmatched_gt_indices)}"
            )
            cv2.putText(
                frame,
                header,
                (20, 40),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.8,
                (0, 255, 255),
                2,
            )
            output_path = preview_dir / f"frame_{frame_index:06d}.jpg"
            if not cv2.imwrite(str(output_path), frame):
                raise RuntimeError(f"failed to save preview: {output_path}")
    finally:
        cap.release()


def main() -> None:
    args = parse_args()
    thresholds = validate_args(args)
    label_data = read_label(args.label)
    metadata = video_metadata(args.video)
    validate_label_video(args.video, label_data, metadata)
    labels = labels_by_frame(label_data)

    sample_step_frames = max(1, round(metadata["fps"] * args.sample_every_sec))
    frame_indices = list(range(0, metadata["frame_count"], sample_step_frames))
    confidence_floor = min(thresholds)
    args.output_dir.mkdir(parents=True, exist_ok=True)

    print(f"video={args.video}")
    print(f"label={args.label}")
    print(f"model={args.model}")
    print(
        f"fps={metadata['fps']:.2f}, frames={metadata['frame_count']}, "
        f"size={metadata['width']}x{metadata['height']}"
    )
    print(
        f"sample_every_sec={args.sample_every_sec}, sampled_frames={len(frame_indices)}, "
        f"conf_thresholds={thresholds}, iou_threshold={args.iou_threshold}"
    )

    prediction_candidates = collect_predictions(
        video_path=args.video,
        model_path=args.model,
        device=args.device,
        imgsz=args.imgsz,
        confidence_floor=confidence_floor,
        frame_indices=frame_indices,
        fps=metadata["fps"],
        labels=labels,
    )

    metrics_rows = []
    frame_rows = []
    detail_rows = []
    for threshold in thresholds:
        metrics, threshold_frame_rows, threshold_detail_rows = evaluate_threshold(
            threshold=threshold,
            frame_indices=frame_indices,
            labels=labels,
            prediction_candidates=prediction_candidates,
            iou_threshold=args.iou_threshold,
        )
        metrics_rows.append(metrics)
        frame_rows.extend(threshold_frame_rows)
        detail_rows.extend(threshold_detail_rows)

    # [Design Intent] 현재 POC의 균형 기준은 max F1이다. 동률이면 Recall,
    # Precision, 더 낮은 threshold 순으로 선택해 놓침을 우선 줄인다.
    selected = max(
        metrics_rows,
        key=lambda row: (
            row["f1"],
            row["recall"],
            row["precision"],
            -row["confidence_threshold"],
        ),
    )

    write_csv(args.output_dir / "threshold_metrics.csv", metrics_rows)
    write_csv(args.output_dir / "frame_error_summary.csv", frame_rows)
    write_csv(args.output_dir / "bbox_match_details.csv", detail_rows)
    write_prediction_candidates(
        path=args.output_dir / "prediction_candidates.csv",
        video_id=args.video.stem,
        fps=metadata["fps"],
        frame_indices=frame_indices,
        prediction_candidates=prediction_candidates,
    )

    summary = {
        "scope": "L1-3_yolo_vs_aihub_label_evaluation",
        "video": str(args.video),
        "label": str(args.label),
        "model": str(args.model),
        "device": args.device,
        "imgsz": args.imgsz,
        "sample_every_sec": args.sample_every_sec,
        "sampled_frames": len(frame_indices),
        "confidence_thresholds": thresholds,
        "iou_threshold": args.iou_threshold,
        "selection_rule": "max_f1_then_recall_then_precision_then_lower_threshold",
        "selected_threshold": selected["confidence_threshold"],
        "selected_metrics": selected,
        "threshold_metrics": metrics_rows,
        "limitations": [
            "This evaluates sampled-frame bbox detection, not unique visitors.",
            "Results cover one C0241 clip and do not prove generalization.",
            "AIHub label quality and frame alignment must also be visually checked.",
            "A reference-label FP can be a visible person missing from the label or a valid detection below the IoU match threshold.",
        ],
    }
    (args.output_dir / "evaluation_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    if args.save_previews:
        save_selected_previews(
            video_path=args.video,
            preview_dir=args.output_dir / "previews_selected_threshold",
            frame_indices=frame_indices,
            labels=labels,
            prediction_candidates=prediction_candidates,
            selected_threshold=selected["confidence_threshold"],
            iou_threshold=args.iou_threshold,
            fps=metadata["fps"],
        )

    print("threshold,tp,fp,fn,precision,recall,f1")
    for row in metrics_rows:
        print(
            f"{row['confidence_threshold']:.2f},{row['tp']},{row['fp']},"
            f"{row['fn']},{row['precision']:.3f},{row['recall']:.3f},"
            f"{row['f1']:.3f}"
        )
    print(
        f"selected_threshold={selected['confidence_threshold']:.2f}, "
        f"selected_f1={selected['f1']:.3f}"
    )
    print(f"output_dir={args.output_dir}")


if __name__ == "__main__":
    main()
