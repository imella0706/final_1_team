from __future__ import annotations

import pandas as pd

from apps.visitor_flow_l2_dashboard.app import (
    build_customer_report_facts,
    customer_time_chart,
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
