from __future__ import annotations

from pathlib import Path

import pytest

from scripts.visitor_flow_l3_tracking_qa import (
    TrackDetection,
    build_track_summary,
    event_row,
    extract_tracked_detections,
    stable_track_color,
    validate_output_dir,
)


class TensorLike:
    def __init__(self, values: list[object]) -> None:
        self.values = values

    def cpu(self) -> "TensorLike":
        return self

    def tolist(self) -> list[object]:
        return self.values


class FakeBoxes:
    def __init__(
        self,
        xyxy: list[list[float]],
        conf: list[float],
        ids: list[int] | None,
    ) -> None:
        self.xyxy = TensorLike(xyxy)
        self.conf = TensorLike(conf)
        self.id = None if ids is None else TensorLike(ids)

    def __len__(self) -> int:
        return len(self.conf.values)


class FakeResult:
    def __init__(self, boxes: FakeBoxes | None) -> None:
        self.boxes = boxes


def test_extract_tracked_detections_reads_ultralytics_track_ids() -> None:
    result = FakeResult(
        FakeBoxes(
            xyxy=[[1.0, 2.0, 11.0, 22.0], [5.0, 6.0, 15.0, 26.0]],
            conf=[0.81, 0.64],
            ids=[3, 7],
        )
    )

    detections = extract_tracked_detections(result)

    assert detections == [
        TrackDetection(track_id=3, confidence=0.81, x1=1.0, y1=2.0, x2=11.0, y2=22.0),
        TrackDetection(track_id=7, confidence=0.64, x1=5.0, y1=6.0, x2=15.0, y2=26.0),
    ]


def test_extract_tracked_detections_allows_missing_track_ids() -> None:
    result = FakeResult(
        FakeBoxes(
            xyxy=[[1.0, 2.0, 11.0, 22.0]],
            conf=[0.81],
            ids=None,
        )
    )

    detections = extract_tracked_detections(result)

    assert detections[0].track_id is None
    assert detections[0].bottom_center() == (6.0, 22.0)


def test_build_track_summary_records_fragmentation_candidates() -> None:
    detections = [
        TrackDetection(track_id=1, confidence=0.9, x1=0, y1=0, x2=10, y2=10),
        TrackDetection(track_id=1, confidence=0.8, x1=1, y1=0, x2=11, y2=10),
        TrackDetection(track_id=1, confidence=0.7, x1=8, y1=0, x2=18, y2=10),
        TrackDetection(track_id=2, confidence=0.6, x1=0, y1=0, x2=10, y2=10),
        TrackDetection(track_id=None, confidence=0.5, x1=0, y1=0, x2=10, y2=10),
    ]
    rows = [
        event_row(detections[0], 100, 0, 33.3, True),
        event_row(detections[1], 101, 1, 33.6, True),
        event_row(detections[2], 108, 8, 36.0, False),
        event_row(detections[3], 103, 3, 34.3, False),
        event_row(detections[4], 104, 4, 34.6, False),
    ]

    summary = build_track_summary(rows=rows, processed_frames=10, max_gap_frames=3)

    assert summary["unique_clip_track_ids"] == 2
    assert summary["track_observations"] == 4
    assert summary["unassigned_observations"] == 1
    assert summary["tracks_with_single_observation"] == 1
    assert summary["fragmentation_gap_count"] == 1
    assert summary["max_active_tracks_per_frame"] == 1
    track_one = summary["track_summaries"][0]
    assert track_one["track_id"] == 1
    assert track_one["span_frames"] == 9
    assert track_one["fragmentation_gap_count"] == 1
    assert track_one["max_gap_frames"] == 6


def test_stable_track_color_is_deterministic() -> None:
    assert stable_track_color(5) == stable_track_color(5)
    assert stable_track_color(None) == (170, 170, 170)


def test_validate_output_dir_rejects_non_outputs_path() -> None:
    with pytest.raises(ValueError, match="must be under outputs"):
        validate_output_dir(Path("/tmp/visitor_flow_l3_tracking"))
