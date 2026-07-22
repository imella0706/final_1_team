#!/usr/bin/env python3
"""Archived L1-5 multi-clip YOLO evaluation wrapper.

Use scripts/visitor_flow_yolo_benchmark.py for active L2-3/L2-3b experiments.
This file is kept only to reproduce the earlier L1-5 batch evaluation artifact.
"""

from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


# [Design Intent] L1-5는 새 평가 로직을 만들지 않는다. L1-3 단일 clip 평가를
# 같은 설정으로 여러 clip에 반복 적용하고, clip별 편차와 전체 지표를 모은다.


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run L1-5 batch YOLO evaluation across matched C0241 clips."
    )
    parser.add_argument(
        "--sample-dir",
        required=True,
        type=Path,
        help="Directory containing videos/ and labels/ subdirectories.",
    )
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
        help="Save selected-threshold preview images for each clip.",
    )
    return parser.parse_args()


def validate_args(args: argparse.Namespace) -> list[float]:
    videos_dir = args.sample_dir / "videos"
    labels_dir = args.sample_dir / "labels"
    if not videos_dir.is_dir():
        raise FileNotFoundError(f"videos directory not found: {videos_dir}")
    if not labels_dir.is_dir():
        raise FileNotFoundError(f"labels directory not found: {labels_dir}")
    if not args.model.is_file():
        raise FileNotFoundError(f"model not found: {args.model}")
    if args.imgsz <= 0:
        raise ValueError("--imgsz must be greater than 0")
    if args.sample_every_sec <= 0:
        raise ValueError("--sample-every-sec must be greater than 0")
    if not 0.0 < args.iou_threshold <= 1.0:
        raise ValueError("--iou-threshold must be in (0.0, 1.0]")
    thresholds = sorted(set(args.conf_thresholds))
    if any(not 0.0 <= threshold <= 1.0 for threshold in thresholds):
        raise ValueError("all --conf-thresholds values must be between 0.0 and 1.0")
    return thresholds


def matched_pairs(sample_dir: Path) -> list[tuple[Path, Path]]:
    videos_by_stem = {path.stem: path for path in (sample_dir / "videos").glob("*.mp4")}
    labels_by_stem = {path.stem: path for path in (sample_dir / "labels").glob("*.json")}
    common_stems = sorted(videos_by_stem.keys() & labels_by_stem.keys())
    if not common_stems:
        raise FileNotFoundError(f"no matched mp4/json pairs under: {sample_dir}")

    missing_labels = sorted(videos_by_stem.keys() - labels_by_stem.keys())
    missing_videos = sorted(labels_by_stem.keys() - videos_by_stem.keys())
    if missing_labels or missing_videos:
        raise ValueError(
            "unmatched video/label stems: "
            f"missing_labels={missing_labels}, missing_videos={missing_videos}"
        )

    return [(videos_by_stem[stem], labels_by_stem[stem]) for stem in common_stems]


def run_single_clip(
    evaluator: Path,
    video: Path,
    label: Path,
    model: Path,
    device: str,
    imgsz: int,
    sample_every_sec: float,
    thresholds: list[float],
    iou_threshold: float,
    output_dir: Path,
    save_previews: bool,
) -> None:
    command = [
        sys.executable,
        str(evaluator),
        "--video",
        str(video),
        "--label",
        str(label),
        "--model",
        str(model),
        "--device",
        device,
        "--imgsz",
        str(imgsz),
        "--sample-every-sec",
        str(sample_every_sec),
        "--conf-thresholds",
        *[str(threshold) for threshold in thresholds],
        "--iou-threshold",
        str(iou_threshold),
        "--output-dir",
        str(output_dir),
    ]
    if save_previews:
        command.append("--save-previews")

    subprocess.run(command, check=True)


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as csv_file:
        return list(csv.DictReader(csv_file))


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise ValueError(f"cannot write empty CSV: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def selected_threshold(metrics_rows: list[dict[str, Any]]) -> dict[str, Any]:
    return max(
        metrics_rows,
        key=lambda row: (
            float(row["f1"]),
            float(row["recall"]),
            float(row["precision"]),
            -float(row["confidence_threshold"]),
        ),
    )


def aggregate_micro(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_threshold: dict[float, dict[str, Any]] = {}
    for row in rows:
        threshold = float(row["confidence_threshold"])
        bucket = by_threshold.setdefault(
            threshold,
            {
                "confidence_threshold": threshold,
                "iou_threshold": float(row["iou_threshold"]),
                "clip_count": 0,
                "sampled_frames": 0,
                "ground_truth_boxes": 0,
                "prediction_boxes": 0,
                "tp": 0,
                "fp": 0,
                "fn": 0,
            },
        )
        bucket["clip_count"] += 1
        bucket["sampled_frames"] += int(row["sampled_frames"])
        bucket["ground_truth_boxes"] += int(row["ground_truth_boxes"])
        bucket["prediction_boxes"] += int(row["prediction_boxes"])
        bucket["tp"] += int(row["tp"])
        bucket["fp"] += int(row["fp"])
        bucket["fn"] += int(row["fn"])

    aggregated = []
    for threshold in sorted(by_threshold):
        row = by_threshold[threshold]
        tp = int(row["tp"])
        fp = int(row["fp"])
        fn = int(row["fn"])
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else 0.0
        aggregated.append(
            {
                **row,
                "precision": round(precision, 6),
                "recall": round(recall, 6),
                "f1": round(f1, 6),
            }
        )
    return aggregated


def aggregate_clip_mean(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_threshold: dict[float, list[dict[str, Any]]] = {}
    for row in rows:
        by_threshold.setdefault(float(row["confidence_threshold"]), []).append(row)

    aggregated = []
    for threshold in sorted(by_threshold):
        threshold_rows = by_threshold[threshold]
        clip_count = len(threshold_rows)
        aggregated.append(
            {
                "confidence_threshold": threshold,
                "clip_count": clip_count,
                "mean_precision": round(
                    sum(float(row["precision"]) for row in threshold_rows) / clip_count,
                    6,
                ),
                "mean_recall": round(
                    sum(float(row["recall"]) for row in threshold_rows) / clip_count,
                    6,
                ),
                "mean_f1": round(
                    sum(float(row["f1"]) for row in threshold_rows) / clip_count,
                    6,
                ),
            }
        )
    return aggregated


def main() -> None:
    args = parse_args()
    thresholds = validate_args(args)
    pairs = matched_pairs(args.sample_dir)
    args.output_dir.mkdir(parents=True, exist_ok=True)

    evaluator = Path(__file__).parents[3] / "visitor_flow_yolo_evaluate.py"
    clip_rows: list[dict[str, Any]] = []

    for video, label in pairs:
        clip_output_dir = args.output_dir / "clips" / video.stem
        print(f"[L1-5] evaluating clip={video.stem}")
        run_single_clip(
            evaluator=evaluator,
            video=video,
            label=label,
            model=args.model,
            device=args.device,
            imgsz=args.imgsz,
            sample_every_sec=args.sample_every_sec,
            thresholds=thresholds,
            iou_threshold=args.iou_threshold,
            output_dir=clip_output_dir,
            save_previews=args.save_previews,
        )

        for row in read_csv_rows(clip_output_dir / "threshold_metrics.csv"):
            clip_rows.append({"video_id": video.stem, **row})

    write_csv(args.output_dir / "clip_threshold_metrics.csv", clip_rows)
    micro_rows = aggregate_micro(clip_rows)
    mean_rows = aggregate_clip_mean(clip_rows)
    write_csv(args.output_dir / "aggregate_micro_threshold_metrics.csv", micro_rows)
    write_csv(args.output_dir / "aggregate_clip_mean_threshold_metrics.csv", mean_rows)

    selected_micro = selected_threshold(micro_rows)
    selected_mean = selected_threshold(
        [
            {
                "confidence_threshold": row["confidence_threshold"],
                "precision": row["mean_precision"],
                "recall": row["mean_recall"],
                "f1": row["mean_f1"],
            }
            for row in mean_rows
        ]
    )
    summary = {
        "scope": "L1-5_multi_clip_yolo_vs_aihub_label_evaluation",
        "sample_dir": str(args.sample_dir),
        "clip_count": len(pairs),
        "clip_ids": [video.stem for video, _ in pairs],
        "model": str(args.model),
        "device": args.device,
        "imgsz": args.imgsz,
        "sample_every_sec": args.sample_every_sec,
        "confidence_thresholds": thresholds,
        "iou_threshold": args.iou_threshold,
        "selection_rule": "max_f1_then_recall_then_precision_then_lower_threshold",
        "selected_micro_threshold": selected_micro["confidence_threshold"],
        "selected_micro_metrics": selected_micro,
        "selected_clip_mean_threshold": selected_mean["confidence_threshold"],
        "selected_clip_mean_metrics": selected_mean,
        "limitations": [
            "This evaluates sampled-frame bbox detection, not unique visitors.",
            "Metrics are aggregated over matched C0241 clips from one day.",
            "Final threshold still requires preview audit and product-risk criteria.",
        ],
    }
    (args.output_dir / "batch_evaluation_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print("threshold,tp,fp,fn,precision,recall,f1")
    for row in micro_rows:
        print(
            f"{row['confidence_threshold']:.2f},{row['tp']},{row['fp']},"
            f"{row['fn']},{row['precision']:.3f},{row['recall']:.3f},"
            f"{row['f1']:.3f}"
        )
    print(
        "selected_micro_threshold="
        f"{float(selected_micro['confidence_threshold']):.2f}, "
        f"selected_micro_f1={float(selected_micro['f1']):.3f}"
    )
    print(f"output_dir={args.output_dir}")


if __name__ == "__main__":
    main()
