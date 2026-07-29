from __future__ import annotations

import json

import pandas as pd

from apps.visitor_flow_l2_dashboard.app import (
    build_customer_report_facts,
    customer_time_chart,
    load_crossing_results,
    load_tracking_qa,
    validate_crossing_dir,
    validate_tracking_qa_dir,
)


# [Design Intent] 고객 보고서 문구가 바뀌어도 피크, 분석 시간, 직접 비교 시간대의
# 결정론적 fact 계약은 L2/L3 집계값과 동일하게 유지한다.
def test_build_customer_report_facts_uses_validated_aggregates() -> None:
    analysis = {
        "clip_count": 3,
        "sampled_frames": 54,
        "sample_every_sec": 10.0,
        "clip_summaries": [
            {"frame_count": 540, "fps": 3.0},
            {"frame_count": 540, "fps": 3.0},
            {"frame_count": 540, "fps": 3.0},
        ],
        "date_summary": [
            {
                "date_id": "2021-08-02",
                "mean_persons_per_sampled_frame": 1.5,
            },
            {
                "date_id": "2021-08-03",
                "mean_persons_per_sampled_frame": 1.25,
            },
        ],
    }
    dashboard_summary = pd.DataFrame(
        [
            {
                "date_id": "2021-08-02",
                "time_bucket": "2021-08-02 09:00:00",
                "mean_persons_per_sampled_frame": 1.0,
            },
            {
                "date_id": "2021-08-02",
                "time_bucket": "2021-08-02 12:00:00",
                "mean_persons_per_sampled_frame": 3.0,
            },
            {
                "date_id": "2021-08-03",
                "time_bucket": "2021-08-03 09:00:00",
                "mean_persons_per_sampled_frame": 2.0,
            },
        ]
    )
    roi_analysis = {
        "camera_id": "C0241",
        "roi_observation_share": 0.48,
        "peak_date_id": "2021-08-02",
        "peak_time_bucket": "2021-08-02 12:00:00",
        "peak_mean_roi_observations_per_sampled_frame": 1.8,
    }

    facts = build_customer_report_facts(
        analysis,
        dashboard_summary,
        roi_analysis,
    )

    assert facts["analysis_minutes"] == 9
    assert facts["peak_date_id"] == "2021-08-02"
    assert facts["peak_hour"] == "12:00"
    assert facts["peak_scene_average"] == 3.0
    assert facts["peak_to_date_average"] == 2.0
    assert facts["storefront_share"] == 0.48
    assert facts["comparable_hours"] == ["09:00"]


def test_customer_time_chart_uses_customer_facing_date_and_hour_labels() -> None:
    summary = pd.DataFrame(
        [
            {
                "date_id": "2021-08-02",
                "time_bucket": "2021-08-02 09:00:00",
                "mean_persons_per_sampled_frame": 1.0,
            },
            {
                "date_id": "2021-08-03",
                "time_bucket": "2021-08-03 09:00:00",
                "mean_persons_per_sampled_frame": 2.0,
            },
        ]
    )

    chart = customer_time_chart(summary, "mean_persons_per_sampled_frame")

    assert chart.index.tolist() == ["09시"]
    assert chart.columns.tolist() == ["08월 02일", "08월 03일"]
    assert chart.loc["09시", "08월 03일"] == 2.0


def test_validate_and_load_tracking_qa_artifacts(tmp_path) -> None:
    qa_dir = tmp_path / "tracking_qa"
    summary_path = qa_dir / "qa" / "tracking_qa_summary.json"
    events_path = qa_dir / "tracks" / "track_events.csv"
    video_path = qa_dir / "media" / "tracking_id_qa.webm"
    summary_path.parent.mkdir(parents=True)
    events_path.parent.mkdir(parents=True)
    video_path.parent.mkdir(parents=True)
    summary_path.write_text(
        json.dumps(
            {
                "stage": "L3-4_tracking_id_qa",
                "results": {"processed_frames": 180},
            }
        ),
        encoding="utf-8",
    )
    events_path.write_text("track_id,source_frame_index\n1,180\n", encoding="utf-8")
    video_path.write_bytes(b"webm")

    missing = validate_tracking_qa_dir(qa_dir)
    summary, loaded_video_path, loaded_events_path = load_tracking_qa(qa_dir)

    assert missing == []
    assert summary["stage"] == "L3-4_tracking_id_qa"
    assert loaded_video_path == video_path
    assert loaded_events_path == events_path


def test_validate_and_load_crossing_artifacts(tmp_path) -> None:
    crossing_dir = tmp_path / "line_crossing"
    summary_path = crossing_dir / "qa" / "crossing_summary.json"
    events_path = crossing_dir / "crossings" / "crossing_events.csv"
    video_path = crossing_dir / "media" / "line_crossing_qa.webm"
    summary_path.parent.mkdir(parents=True)
    events_path.parent.mkdir(parents=True)
    video_path.parent.mkdir(parents=True)
    summary_path.write_text(
        json.dumps(
            {
                "stage": "L3-5_line_crossing_direction_events",
                "results": {"total_crossing_events": 14},
            }
        ),
        encoding="utf-8",
    )
    events_path.write_text("track_id,event_direction\n1,screen_downward_event\n", encoding="utf-8")
    video_path.write_bytes(b"webm")

    missing = validate_crossing_dir(crossing_dir)
    summary, loaded_video_path, loaded_events_path = load_crossing_results(crossing_dir)

    assert missing == []
    assert summary["stage"] == "L3-5_line_crossing_direction_events"
    assert loaded_video_path == video_path
    assert loaded_events_path == events_path
