from __future__ import annotations

import unittest
from unittest.mock import patch

import cv2
import numpy as np

from app.services.food_support_recovery import recover_food_supports
from app.services.plate_edge_repair import repair_plate_edge


def _support_case() -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    shape = (360, 360)
    image = np.full((*shape, 3), (210, 210, 210), np.uint8)
    plate = np.zeros(shape, np.uint8)
    cv2.circle(plate, (180, 195), 110, 255, -1)
    image[plate > 0] = (235, 238, 240)

    rim = np.zeros(shape, np.uint8)
    cv2.circle(rim, (180, 195), 110, 255, 6)
    image[rim > 0] = (40, 95, 35)

    food = plate.copy()
    candidate = np.zeros(shape, np.uint8)
    cv2.line(candidate, (180, 150), (180, 38), 255, 7)
    cv2.line(image, (180, 150), (180, 38), (145, 185, 220), 7)

    # A detached utensil-shaped line must not qualify because it never crosses
    # from the plate interior to the exterior.
    cv2.line(candidate, (330, 75), (330, 240), 255, 9)
    cv2.line(image, (330, 75), (330, 240), (145, 185, 220), 9)
    return image, plate, food, candidate


class FoodSupportRecoveryTest(unittest.TestCase):
    def test_two_dimensional_hough_output_is_supported(self) -> None:
        image, plate, food, candidate = _support_case()
        hough_lines = np.array(
            [
                [180, 150, 180, 38],
                [181, 150, 181, 38],
                [179, 150, 179, 38],
                [182, 150, 182, 38],
            ],
            dtype=np.int32,
        )

        with patch(
            "app.services.food_support_recovery.cv2.HoughLinesP",
            return_value=hough_lines,
        ):
            result = recover_food_supports(
                image,
                plate,
                food,
                [candidate],
                {
                    "enabled": True,
                    "minimum_line_length_ratio": 0.04,
                    "maximum_line_length_ratio": 0.70,
                    "minimum_component_aspect_ratio": 1.0,
                    "minimum_component_candidate_overlap": 0.10,
                    "minimum_line_votes": 1,
                    "allow_geometry_only": False,
                    "grabcut_refinement_enabled": False,
                    "maximum_component_plate_area_ratio": 0.05,
                    "maximum_total_plate_area_ratio": 0.08,
                },
            )

        self.assertNotEqual(
            result.metrics.get("reason"),
            "invalid_hough_line_shape",
        )

    def test_crossing_skewer_is_recovered_but_detached_utensil_is_not(self) -> None:
        image, plate, food, candidate = _support_case()

        result = recover_food_supports(
            image,
            plate,
            food,
            [candidate],
            {
                "enabled": True,
                "minimum_line_length_ratio": 0.04,
                "maximum_line_length_ratio": 0.70,
                "hough_threshold": 12,
                "minimum_component_aspect_ratio": 1.0,
                "minimum_component_candidate_overlap": 0.10,
                "allow_geometry_only": False,
                "grabcut_refinement_enabled": False,
                "maximum_component_plate_area_ratio": 0.05,
                "maximum_total_plate_area_ratio": 0.08,
            },
        )

        self.assertTrue(result.metrics["applied"])
        self.assertGreater(np.count_nonzero(result.mask[35:90, 170:190]), 0)
        self.assertEqual(np.count_nonzero(result.mask[:, 320:340]), 0)

    def test_recovered_support_is_restored_after_rim_repair(self) -> None:
        source, plate, food, candidate = _support_case()
        support = recover_food_supports(
            source,
            plate,
            food,
            [candidate],
            {
                "enabled": True,
                "minimum_line_length_ratio": 0.04,
                "maximum_line_length_ratio": 0.70,
                "hough_threshold": 12,
                "minimum_component_aspect_ratio": 1.0,
                "minimum_component_candidate_overlap": 0.10,
                "allow_geometry_only": False,
                "grabcut_refinement_enabled": False,
                "maximum_component_plate_area_ratio": 0.05,
                "maximum_total_plate_area_ratio": 0.08,
            },
        ).mask
        cleaned = source.copy()
        cleaned[support > 0] = (20, 20, 20)

        result = repair_plate_edge(
            cleaned,
            plate,
            food,
            {
                "enabled": True,
                "ring_width": 20,
                "food_core_erosion": 15,
                "close_kernel": 3,
                "restore_rim_line": False,
                "plate_mask_rim_completion_enabled": False,
                "protected_detail_guard_width": 5,
                "protected_detail_feather_kernel": 1,
            },
            protected_detail_mask=support,
            source_image_bgr=source,
        )

        core = cv2.erode(support, np.ones((3, 3), np.uint8))
        self.assertGreater(np.count_nonzero(core), 0)
        self.assertTrue(np.array_equal(result.image[core > 0], source[core > 0]))
        self.assertEqual(
            result.metrics["protected_detail_pixels"],
            int(np.count_nonzero(support)),
        )


if __name__ == "__main__":
    unittest.main()
