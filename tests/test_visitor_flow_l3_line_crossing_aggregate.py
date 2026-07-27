from __future__ import annotations

import pandas as pd

from scripts.visitor_flow_l3_line_crossing_aggregate import (
    CrossingLine,
    Point,
    detect_crossing_events,
    line_pixels,
    side_of_line,
    signed_distance_to_line,
)


CONFIG = {
    "schema_version": 1,
    "camera_id": "C0241",
    "primary_line_id": "walkway_up_down_flow",
    "label": "Walkway up/down pedestrian flow",
    "coordinate_space": "normalized_image",
    "position_point": "bbox_bottom_center",
    "definition_source": "manual_line",
    "line": [{"x": 0.25, "y": 0.5}, {"x": 0.75, "y": 0.5}],
    "direction_labels": {
        "negative_to_positive": "screen_downward_event",
        "positive_to_negative": "screen_upward_event",
    },
}


def track_row(
    *,
    track_id: int,
    frame: int,
    x: float,
    y: float,
    confidence: float = 0.8,
    is_in_roi: bool = True,
) -> dict[str, object]:
    return {
        "source_frame_index": 180 + frame,
        "clip_frame_index": frame,
        "timestamp_sec": 60.0 + frame / 3.0,
        "track_id": track_id,
        "confidence": confidence,
        "bottom_center_x": x,
        "bottom_center_y": y,
        "is_in_roi": is_in_roi,
    }


def test_directed_horizontal_line_maps_above_to_negative_side() -> None:
    line = CrossingLine(start=Point(100, 500), end=Point(900, 500))

    assert signed_distance_to_line(Point(500, 400), line) < 0
    assert signed_distance_to_line(Point(500, 600), line) > 0
    assert side_of_line(Point(500, 501), line, margin_px=3) == 0


def test_detects_upward_and_downward_crossing_events() -> None:
    line = line_pixels(CONFIG, width=1000, height=1000)
    events = pd.DataFrame(
        [
            track_row(track_id=1, frame=0, x=500, y=420),
            track_row(track_id=1, frame=2, x=500, y=580),
            track_row(track_id=2, frame=0, x=600, y=590),
            track_row(track_id=2, frame=3, x=600, y=410),
        ]
    )

    crossing_rows = detect_crossing_events(
        events,
        line,
        CONFIG,
        width=1000,
        height=1000,
        line_margin_px=3,
        min_event_gap_frames=0,
    )

    assert [row["event_label"] for row in crossing_rows] == [
        "screen_downward_event",
        "screen_upward_event",
    ]
    assert crossing_rows[0]["intersection_x"] == 500.0
    assert crossing_rows[0]["intersection_y"] == 500.0


def test_ignores_crossing_outside_finite_line_segment() -> None:
    line = line_pixels(CONFIG, width=1000, height=1000)
    events = pd.DataFrame(
        [
            track_row(track_id=1, frame=0, x=100, y=420),
            track_row(track_id=1, frame=2, x=100, y=580),
        ]
    )

    crossing_rows = detect_crossing_events(
        events,
        line,
        CONFIG,
        width=1000,
        height=1000,
        line_margin_px=3,
        min_event_gap_frames=0,
    )

    assert crossing_rows == []


def test_min_event_gap_suppresses_line_jitter_duplicates() -> None:
    line = line_pixels(CONFIG, width=1000, height=1000)
    events = pd.DataFrame(
        [
            track_row(track_id=1, frame=0, x=500, y=420),
            track_row(track_id=1, frame=2, x=500, y=580),
            track_row(track_id=1, frame=3, x=500, y=420),
            track_row(track_id=1, frame=4, x=500, y=580),
        ]
    )

    crossing_rows = detect_crossing_events(
        events,
        line,
        CONFIG,
        width=1000,
        height=1000,
        line_margin_px=3,
        min_event_gap_frames=6,
    )

    assert len(crossing_rows) == 1
    assert crossing_rows[0]["event_label"] == "screen_downward_event"
