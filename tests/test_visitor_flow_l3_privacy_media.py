from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from scripts.visitor_flow_l3_privacy_media import (
    current_and_recent_boxes,
    filter_detections_by_conf,
    mask_person_bbox_tops,
    validate_output_dir,
)


def gradient_frame(height: int = 24, width: int = 24) -> np.ndarray:
    values = np.arange(height * width * 3, dtype=np.uint16).reshape(height, width, 3)
    return (values % 251).astype(np.uint8)


def test_mask_person_bbox_tops_changes_only_upper_bbox_region() -> None:
    frame = gradient_frame()
    original = frame.copy()

    regions = mask_person_bbox_tops(
        frame,
        boxes=[(4.0, 4.0, 20.0, 20.0)],
        top_ratio=0.5,
        block_size=4,
    )

    assert regions == [(4, 4, 20, 12)]
    assert not np.array_equal(frame[4:12, 4:20], original[4:12, 4:20])
    assert np.array_equal(frame[12:20, 4:20], original[12:20, 4:20])
    assert np.array_equal(frame[:4], original[:4])
    assert np.array_equal(frame[:, :4], original[:, :4])


def test_mask_person_bbox_tops_clips_box_to_frame() -> None:
    frame = gradient_frame(height=12, width=12)

    regions = mask_person_bbox_tops(
        frame,
        boxes=[(-5.0, -4.0, 8.0, 10.0), (20.0, 20.0, 30.0, 30.0)],
        top_ratio=0.4,
        block_size=3,
    )

    assert regions == [(0, 0, 8, 4)]


def test_mask_person_bbox_tops_can_expand_bbox_region() -> None:
    frame = gradient_frame(height=20, width=20)

    regions = mask_person_bbox_tops(
        frame,
        boxes=[(5.0, 5.0, 15.0, 15.0)],
        top_ratio=0.5,
        block_size=4,
        padding_ratio=0.2,
    )

    assert regions == [(3, 3, 17, 10)]


def test_filter_detections_by_conf_keeps_display_threshold_separate() -> None:
    detections = [
        (0.0, 0.0, 10.0, 10.0, 0.24),
        (0.0, 0.0, 10.0, 10.0, 0.50),
        (0.0, 0.0, 10.0, 10.0, 0.81),
    ]

    filtered = filter_detections_by_conf(detections, 0.50)

    assert [detection[4] for detection in filtered] == [0.50, 0.81]


def test_current_and_recent_boxes_reuses_previous_masks() -> None:
    previous_boxes = [
        [(1.0, 1.0, 5.0, 5.0)],
        [(6.0, 6.0, 9.0, 9.0)],
    ]

    boxes = current_and_recent_boxes(
        current_boxes=[(10.0, 10.0, 12.0, 12.0)],
        previous_boxes=previous_boxes,
    )

    assert boxes == [
        (1.0, 1.0, 5.0, 5.0),
        (6.0, 6.0, 9.0, 9.0),
        (10.0, 10.0, 12.0, 12.0),
    ]


def test_validate_output_dir_rejects_processed_dataset_path() -> None:
    with pytest.raises(ValueError, match="must be under outputs"):
        validate_output_dir(Path("/tmp/data/processed/privacy_media"))
