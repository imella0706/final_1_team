#!/usr/bin/env python3
"""Run the L2-3 three-config YOLO benchmark with a frozen validation threshold."""

from __future__ import annotations

import argparse
import csv
import json
import time
from pathlib import Path
from typing import Any

from ultralytics import YOLO

import visitor_flow_yolo_evaluate as evaluator


# [Design Intent] L2-3은 Aug 3 지표를 보고 threshold를 다시 고르는 데이터 누수를
# 막는다. 각 설정은 Aug 2 micro-F1로 threshold를 하나 선택하고, Aug 3에는 그 값만
# 평가한다. 모델은 설정당 한 번 로드해 반복 로딩 시간이 throughput을 오염시키지 않는다.


CONFIGS = {
    "yolo11n_imgsz640": {"model_arg": "yolo11n_model", "imgsz": 640},
    "yolo11s_imgsz640": {"model_arg": "yolo11s_model", "imgsz": 640},
    "yolo11s_imgsz960": {"model_arg": "yolo11s_model", "imgsz": 960},
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Compare YOLO11n/640, YOLO11s/640, and YOLO11s/960 using "
            "Aug 2 calibration and frozen-threshold Aug 3 validation."
        )
    )
    parser.add_argument("--calibration-dir", required=True, type=Path)
    parser.add_argument("--validation-dir", required=True, type=Path)
    parser.add_argument("--yolo11n-model", required=True, type=Path)
    parser.add_argument("--yolo11s-model", required=True, type=Path)
    parser.add_argument(
        "--device", default="cpu", help="Inference device: cpu, cuda, 0"
    )
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--camera-id", default="C0241")
    parser.add_argument("--calibration-date", default="2021-08-02")
    parser.add_argument("--validation-date", default="2021-08-03")
    parser.add_argument("--expected-calibration-clips", default=8, type=int)
    parser.add_argument("--expected-validation-clips", default=7, type=int)
    parser.add_argument("--sample-every-sec", default=10.0, type=float)
    parser.add_argument("--iou-threshold", default=0.50, type=float)
    parser.add_argument(
        "--conf-thresholds",
        nargs="+",
        type=float,
        default=[0.25, 0.40, 0.50, 0.60, 0.70],
    )
    parser.add_argument(
        "--configs",
        nargs="+",
        choices=tuple(CONFIGS),
        default=list(CONFIGS),
        help="Subset of benchmark configurations to execute.",
    )
    return parser.parse_args()


def validate_args(args: argparse.Namespace) -> list[float]:
    for sample_dir, name in (
        (args.calibration_dir, "calibration-dir"),
        (args.validation_dir, "validation-dir"),
    ):
        if not (sample_dir / "videos").is_dir():
            raise FileNotFoundError(
                f"{name} videos directory not found: {sample_dir / 'videos'}"
            )
        if not (sample_dir / "labels").is_dir():
            raise FileNotFoundError(
                f"{name} labels directory not found: {sample_dir / 'labels'}"
            )

    for model_path, name in (
        (args.yolo11n_model, "yolo11n-model"),
        (args.yolo11s_model, "yolo11s-model"),
    ):
        if not model_path.is_file():
            raise FileNotFoundError(f"{name} not found: {model_path}")

    if args.expected_calibration_clips <= 0 or args.expected_validation_clips <= 0:
        raise ValueError("expected clip counts must be greater than 0")
    if args.sample_every_sec <= 0:
        raise ValueError("--sample-every-sec must be greater than 0")
    if not 0.0 < args.iou_threshold <= 1.0:
        raise ValueError("--iou-threshold must be in (0.0, 1.0]")

    thresholds = sorted(set(args.conf_thresholds))
    if not thresholds or any(not 0.0 <= value <= 1.0 for value in thresholds):
        raise ValueError("all confidence thresholds must be between 0.0 and 1.0")
    return thresholds


def matched_pairs_for_date(
    sample_dir: Path,
    date: str,
    camera_id: str,
    expected_count: int,
) -> list[tuple[Path, Path]]:
    videos = {
        path.stem: path
        for path in (sample_dir / "videos").rglob("*.mp4")
        if path.stem.startswith(f"{date}_") and path.stem.endswith(f"_{camera_id}")
    }
    labels = {
        path.stem: path
        for path in (sample_dir / "labels").rglob("*.json")
        if path.stem.startswith(f"{date}_") and path.stem.endswith(f"_{camera_id}")
    }
    missing_labels = sorted(videos.keys() - labels.keys())
    missing_videos = sorted(labels.keys() - videos.keys())
    if missing_labels or missing_videos:
        raise ValueError(
            f"unmatched {date} {camera_id} pairs: "
            f"missing_labels={missing_labels}, missing_videos={missing_videos}"
        )

    stems = sorted(videos.keys() & labels.keys())
    if len(stems) != expected_count:
        raise ValueError(
            f"expected {expected_count} matched clips for {date} {camera_id}, "
            f"found {len(stems)}"
        )
    return [(videos[stem], labels[stem]) for stem in stems]


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
        precision = evaluator.safe_divide(tp, tp + fp)
        recall = evaluator.safe_divide(tp, tp + fn)
        f1 = evaluator.safe_divide(2 * tp, 2 * tp + fp + fn)
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


def run_clip(
    video: Path,
    label: Path,
    model: YOLO,
    model_path: Path,
    config_id: str,
    imgsz: int,
    device: str,
    sample_every_sec: float,
    thresholds: list[float],
    inference_confidence_floor: float,
    iou_threshold: float,
    data_role: str,
    frozen_threshold: float | None,
    output_dir: Path,
) -> dict[str, Any]:
    clip_started = time.perf_counter()
    label_data = evaluator.read_label(label)
    metadata = evaluator.video_metadata(video)
    evaluator.validate_label_video(video, label_data, metadata)
    labels = evaluator.labels_by_frame(label_data)
    sample_step_frames = max(1, round(metadata["fps"] * sample_every_sec))
    frame_indices = list(range(0, metadata["frame_count"], sample_step_frames))

    prediction_candidates, prediction_timing = evaluator.collect_predictions(
        video_path=video,
        model_path=model_path,
        device=device,
        imgsz=imgsz,
        confidence_floor=inference_confidence_floor,
        frame_indices=frame_indices,
        fps=metadata["fps"],
        labels=labels,
        model=model,
    )

    metrics_rows: list[dict[str, Any]] = []
    frame_rows: list[dict[str, Any]] = []
    detail_rows: list[dict[str, Any]] = []
    for threshold in thresholds:
        metrics, threshold_frames, threshold_details = evaluator.evaluate_threshold(
            threshold=threshold,
            frame_indices=frame_indices,
            labels=labels,
            prediction_candidates=prediction_candidates,
            iou_threshold=iou_threshold,
        )
        metrics_rows.append(metrics)
        frame_rows.extend(threshold_frames)
        detail_rows.extend(threshold_details)

    if frozen_threshold is not None and (
        len(metrics_rows) != 1
        or float(metrics_rows[0]["confidence_threshold"]) != frozen_threshold
    ):
        raise AssertionError(
            "validation must evaluate exactly the frozen calibration threshold"
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    evaluator.write_csv(output_dir / "threshold_metrics.csv", metrics_rows)
    evaluator.write_csv(output_dir / "frame_error_summary.csv", frame_rows)
    evaluator.write_csv(output_dir / "bbox_match_details.csv", detail_rows)
    evaluator.write_prediction_candidates(
        path=output_dir / "prediction_candidates.csv",
        video_id=video.stem,
        fps=metadata["fps"],
        frame_indices=frame_indices,
        prediction_candidates=prediction_candidates,
    )

    summary = {
        "scope": "L2-3_config_date_clip_evaluation",
        "data_role": data_role,
        "config_id": config_id,
        "video": str(video),
        "label": str(label),
        "model": str(model_path),
        "device": device,
        "imgsz": imgsz,
        "sample_every_sec": sample_every_sec,
        "sampled_frames": len(frame_indices),
        "confidence_thresholds": thresholds,
        "inference_confidence_floor": inference_confidence_floor,
        "frozen_calibration_threshold": frozen_threshold,
        "iou_threshold": iou_threshold,
        "threshold_policy": (
            "calibration_candidate_scan"
            if frozen_threshold is None
            else "frozen_from_calibration_no_reselection"
        ),
        "threshold_metrics": metrics_rows,
        "timing": {
            **prediction_timing,
            "evaluation_wall_time_sec": round(time.perf_counter() - clip_started, 6),
        },
    }
    (output_dir / "evaluation_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return summary


def summarize_timing(clip_summaries: list[dict[str, Any]]) -> dict[str, Any]:
    sampled_frames = sum(int(summary["sampled_frames"]) for summary in clip_summaries)
    pipeline_sec = sum(
        float(summary["timing"]["prediction_pipeline_wall_time_sec"])
        for summary in clip_summaries
    )
    inference_sec = sum(
        float(summary["timing"]["ultralytics_inference_time_sec"])
        for summary in clip_summaries
    )
    evaluation_sec = sum(
        float(summary["timing"]["evaluation_wall_time_sec"])
        for summary in clip_summaries
    )
    return {
        "sampled_frames": sampled_frames,
        "prediction_pipeline_wall_time_sec": round(pipeline_sec, 6),
        "evaluation_wall_time_sec": round(evaluation_sec, 6),
        "ultralytics_inference_time_sec": round(inference_sec, 6),
        "prediction_pipeline_fps": round(
            sampled_frames / pipeline_sec if pipeline_sec > 0.0 else 0.0, 6
        ),
        "inference_fps": round(
            sampled_frames / inference_sec if inference_sec > 0.0 else 0.0, 6
        ),
    }


def run_date(
    pairs: list[tuple[Path, Path]],
    date: str,
    data_role: str,
    model: YOLO,
    model_path: Path,
    config_id: str,
    imgsz: int,
    device: str,
    sample_every_sec: float,
    thresholds: list[float],
    inference_confidence_floor: float,
    iou_threshold: float,
    frozen_threshold: float | None,
    output_dir: Path,
) -> dict[str, Any]:
    date_started = time.perf_counter()
    clip_summaries = []
    clip_rows = []
    for clip_index, (video, label) in enumerate(pairs, start=1):
        print(
            f"[L2-3] config={config_id} role={data_role} "
            f"clip={clip_index}/{len(pairs)} video={video.stem}",
            flush=True,
        )
        summary = run_clip(
            video=video,
            label=label,
            model=model,
            model_path=model_path,
            config_id=config_id,
            imgsz=imgsz,
            device=device,
            sample_every_sec=sample_every_sec,
            thresholds=thresholds,
            inference_confidence_floor=inference_confidence_floor,
            iou_threshold=iou_threshold,
            data_role=data_role,
            frozen_threshold=frozen_threshold,
            output_dir=output_dir / "clips" / video.stem,
        )
        clip_summaries.append(summary)
        for row in summary["threshold_metrics"]:
            clip_rows.append({"video_id": video.stem, **row})

    micro_rows = aggregate_micro(clip_rows)
    mean_rows = aggregate_clip_mean(clip_rows)
    write_csv(output_dir / "clip_threshold_metrics.csv", clip_rows)
    write_csv(output_dir / "aggregate_micro_threshold_metrics.csv", micro_rows)
    write_csv(output_dir / "aggregate_clip_mean_threshold_metrics.csv", mean_rows)
    operating_metrics = selected_threshold(micro_rows)
    if (
        frozen_threshold is not None
        and float(operating_metrics["confidence_threshold"]) != frozen_threshold
    ):
        raise AssertionError(
            "validation aggregate changed the frozen calibration threshold"
        )

    summary = {
        "scope": "L2-3_config_date_evaluation",
        "date": date,
        "data_role": data_role,
        "config_id": config_id,
        "clip_count": len(pairs),
        "clip_ids": [video.stem for video, _ in pairs],
        "model": str(model_path),
        "device": device,
        "imgsz": imgsz,
        "sample_every_sec": sample_every_sec,
        "confidence_thresholds": thresholds,
        "inference_confidence_floor": inference_confidence_floor,
        "frozen_calibration_threshold": frozen_threshold,
        "iou_threshold": iou_threshold,
        "threshold_policy": (
            "max_micro_f1_then_recall_then_precision_then_lower_threshold"
            if frozen_threshold is None
            else "frozen_from_calibration_no_reselection"
        ),
        "operating_threshold": operating_metrics["confidence_threshold"],
        "operating_metrics": operating_metrics,
        "timing": {
            **summarize_timing(clip_summaries),
            "date_run_wall_time_sec": round(time.perf_counter() - date_started, 6),
        },
    }
    (output_dir / "date_evaluation_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return summary


def benchmark_row(
    config_id: str,
    model_path: Path,
    imgsz: int,
    device: str,
    model_load_sec: float,
    calibration: dict[str, Any],
    validation: dict[str, Any],
) -> dict[str, Any]:
    calibration_metrics = calibration["operating_metrics"]
    validation_metrics = validation["operating_metrics"]
    return {
        "config_id": config_id,
        "model": model_path.name,
        "imgsz": imgsz,
        "device": device,
        "selected_threshold": calibration["operating_threshold"],
        "calibration_clip_count": calibration["clip_count"],
        "calibration_sampled_frames": calibration["timing"]["sampled_frames"],
        "calibration_precision": calibration_metrics["precision"],
        "calibration_recall": calibration_metrics["recall"],
        "calibration_f1": calibration_metrics["f1"],
        "validation_clip_count": validation["clip_count"],
        "validation_sampled_frames": validation["timing"]["sampled_frames"],
        "validation_precision": validation_metrics["precision"],
        "validation_recall": validation_metrics["recall"],
        "validation_f1": validation_metrics["f1"],
        "model_load_wall_time_sec": round(model_load_sec, 6),
        "calibration_prediction_wall_time_sec": calibration["timing"][
            "prediction_pipeline_wall_time_sec"
        ],
        "validation_prediction_wall_time_sec": validation["timing"][
            "prediction_pipeline_wall_time_sec"
        ],
        "calibration_evaluation_wall_time_sec": calibration["timing"][
            "evaluation_wall_time_sec"
        ],
        "validation_evaluation_wall_time_sec": validation["timing"][
            "evaluation_wall_time_sec"
        ],
        "validation_inference_fps": validation["timing"]["inference_fps"],
        "validation_prediction_pipeline_fps": validation["timing"][
            "prediction_pipeline_fps"
        ],
    }


def main() -> None:
    args = parse_args()
    thresholds = validate_args(args)
    calibration_pairs = matched_pairs_for_date(
        sample_dir=args.calibration_dir,
        date=args.calibration_date,
        camera_id=args.camera_id,
        expected_count=args.expected_calibration_clips,
    )
    validation_pairs = matched_pairs_for_date(
        sample_dir=args.validation_dir,
        date=args.validation_date,
        camera_id=args.camera_id,
        expected_count=args.expected_validation_clips,
    )
    args.output_dir.mkdir(parents=True, exist_ok=True)

    benchmark_rows = []
    config_summaries = []
    inference_confidence_floor = min(thresholds)
    for config_id in args.configs:
        config = CONFIGS[config_id]
        model_path = getattr(args, config["model_arg"])
        imgsz = int(config["imgsz"])
        print(f"[L2-3] loading config={config_id} model={model_path}", flush=True)
        model_load_started = time.perf_counter()
        model = YOLO(str(model_path))
        model_load_sec = time.perf_counter() - model_load_started
        config_output_dir = args.output_dir / "configs" / config_id

        calibration = run_date(
            pairs=calibration_pairs,
            date=args.calibration_date,
            data_role="calibration",
            model=model,
            model_path=model_path,
            config_id=config_id,
            imgsz=imgsz,
            device=args.device,
            sample_every_sec=args.sample_every_sec,
            thresholds=thresholds,
            inference_confidence_floor=inference_confidence_floor,
            iou_threshold=args.iou_threshold,
            frozen_threshold=None,
            output_dir=config_output_dir / f"calibration_{args.calibration_date}",
        )
        frozen_threshold = float(calibration["operating_threshold"])
        validation = run_date(
            pairs=validation_pairs,
            date=args.validation_date,
            data_role="fixed_validation",
            model=model,
            model_path=model_path,
            config_id=config_id,
            imgsz=imgsz,
            device=args.device,
            sample_every_sec=args.sample_every_sec,
            thresholds=[frozen_threshold],
            inference_confidence_floor=inference_confidence_floor,
            iou_threshold=args.iou_threshold,
            frozen_threshold=frozen_threshold,
            output_dir=config_output_dir / f"validation_{args.validation_date}",
        )

        row = benchmark_row(
            config_id=config_id,
            model_path=model_path,
            imgsz=imgsz,
            device=args.device,
            model_load_sec=model_load_sec,
            calibration=calibration,
            validation=validation,
        )
        benchmark_rows.append(row)
        config_summaries.append(
            {
                "config_id": config_id,
                "model": str(model_path),
                "imgsz": imgsz,
                "model_load_wall_time_sec": round(model_load_sec, 6),
                "calibration": calibration,
                "fixed_validation": validation,
            }
        )

    ranked_rows = sorted(
        benchmark_rows,
        key=lambda row: (
            float(row["validation_f1"]),
            float(row["validation_recall"]),
            float(row["validation_precision"]),
            float(row["validation_inference_fps"]),
        ),
        reverse=True,
    )
    rank_by_config = {row["config_id"]: rank for rank, row in enumerate(ranked_rows, 1)}
    final_rows = [
        {"validation_rank": rank_by_config[row["config_id"]], **row}
        for row in benchmark_rows
    ]
    write_csv(args.output_dir / "model_benchmark.csv", final_rows)

    selected = ranked_rows[0]
    benchmark_summary = {
        "scope": "L2-3_three_config_frozen_threshold_benchmark",
        "calibration_date": args.calibration_date,
        "validation_date": args.validation_date,
        "camera_id": args.camera_id,
        "device": args.device,
        "sample_every_sec": args.sample_every_sec,
        "iou_threshold": args.iou_threshold,
        "calibration_threshold_candidates": thresholds,
        "inference_confidence_floor": inference_confidence_floor,
        "threshold_policy": (
            "Select per-config max micro-F1 on calibration; evaluate only that frozen "
            "threshold on validation."
        ),
        "config_selection_rule": (
            "max validation F1, then recall, precision, and inference FPS"
        ),
        "selected_config_id": selected["config_id"],
        "selected_config": selected,
        "benchmark_rows": final_rows,
        "config_summaries": config_summaries,
        "limitations": [
            "This is sampled-frame bbox detection evaluation, not unique visitor counting.",
            "The benchmark covers one fixed camera and two adjacent dates only.",
            "Timing is hardware- and software-environment-specific.",
            "Aug 3 selects the final model configuration, so another date is still needed for an unbiased final holdout estimate.",
        ],
    }
    (args.output_dir / "model_benchmark.json").write_text(
        json.dumps(benchmark_summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print("validation_rank,config_id,threshold,precision,recall,f1,inference_fps")
    for row in sorted(final_rows, key=lambda item: item["validation_rank"]):
        print(
            f"{row['validation_rank']},{row['config_id']},"
            f"{float(row['selected_threshold']):.2f},"
            f"{float(row['validation_precision']):.3f},"
            f"{float(row['validation_recall']):.3f},"
            f"{float(row['validation_f1']):.3f},"
            f"{float(row['validation_inference_fps']):.2f}"
        )
    print(f"selected_config_id={selected['config_id']}")
    print(f"output_dir={args.output_dir}")


if __name__ == "__main__":
    main()
