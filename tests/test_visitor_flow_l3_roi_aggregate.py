from __future__ import annotations

import pandas as pd

from scripts.visitor_flow_l3_roi_aggregate import (
    apply_roi_to_events,
    build_roi_frames,
    build_roi_summary,
    point_in_polygon,
)


SQUARE = [(0.2, 0.2), (0.8, 0.2), (0.8, 0.8), (0.2, 0.8)]


def test_point_in_polygon_includes_boundary() -> None:
    assert point_in_polygon(0.5, 0.5, SQUARE)
    assert point_in_polygon(0.2, 0.5, SQUARE)
    assert point_in_polygon(0.8, 0.8, SQUARE)
    assert not point_in_polygon(0.1, 0.5, SQUARE)


def test_roi_aggregation_keeps_zero_detection_frames() -> None:
    events = pd.DataFrame(
        [
            {
                "analysis_id": "l2",
                "date_id": "2021-08-02",
                "video_id": "clip_C0241",
                "frame_index": 0,
                "timestamp_ms": 0,
                "time_bucket": "2021-08-02 09:00:00",
                "point_x_norm": 0.5,
                "point_y_norm": 0.5,
                "roi_id": "none",
                "is_in_front_of_shop": False,
            },
            {
                "analysis_id": "l2",
                "date_id": "2021-08-02",
                "video_id": "clip_C0241",
                "frame_index": 0,
                "timestamp_ms": 0,
                "time_bucket": "2021-08-02 09:00:00",
                "point_x_norm": 0.1,
                "point_y_norm": 0.5,
                "roi_id": "none",
                "is_in_front_of_shop": False,
            },
        ]
    )
    frames = pd.DataFrame(
        [
            {
                "analysis_id": "l2",
                "date_id": "2021-08-02",
                "video_id": "clip_C0241",
                "frame_index": 0,
                "timestamp_ms": 0,
                "time_bucket": "2021-08-02 09:00:00",
                "person_detection_count": 2,
            },
            {
                "analysis_id": "l2",
                "date_id": "2021-08-02",
                "video_id": "clip_C0241",
                "frame_index": 30,
                "timestamp_ms": 10000,
                "time_bucket": "2021-08-02 09:00:00",
                "person_detection_count": 0,
            },
        ]
    )

    roi_events = apply_roi_to_events(events, "l3", "storefront", SQUARE)
    roi_frames = build_roi_frames(frames, roi_events, "l3")
    summary = build_roi_summary(roi_frames, "l3", "storefront")

    assert roi_events["is_in_front_of_shop"].tolist() == [True, False]
    assert roi_frames["roi_observation_count"].tolist() == [1, 0]
    assert int(summary.iloc[0]["sampled_frame_count"]) == 2
    assert int(summary.iloc[0]["roi_observations"]) == 1
    assert summary.iloc[0]["mean_roi_observations_per_sampled_frame"] == 0.5
    assert summary.iloc[0]["roi_observation_share"] == 0.5
