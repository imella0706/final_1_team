from __future__ import annotations

import unittest

import cv2
import numpy as np

from app.services.mask_quality import (
    assess_food_mask_quality,
    assess_plate_mask_quality,
)
from app.services.plate_edge_repair import repair_plate_edge
from app.services.plate_mask import PlateMaskService
from app.services.rim_observation import observe_container_rim


def _plate_config() -> dict[str, object]:
    return {
        "enabled": True,
        "minimum_area_ratio": 0.02,
        "maximum_aspect_ratio": 1.8,
        "minimum_ellipse_iou": 0.65,
        "maximum_ellipse_area_ratio": 1.35,
        "minimum_shape_confidence": 0.58,
        "contour_completion_enabled": True,
        "minimum_contour_solidity": 0.70,
        "minimum_rectangularity": 0.75,
        "maximum_contour_area_ratio": 1.25,
        "polygon_epsilon_ratio": 0.025,
        "maximum_polygon_vertices": 6,
        "edge_repair_kernel": 5,
    }


class PlateMaskGeneralizationTest(unittest.TestCase):
    def test_round_plate_uses_ellipse_completion(self) -> None:
        mask = np.zeros((320, 320), np.uint8)
        cv2.ellipse(mask, (160, 165), (105, 92), 8, 0, 360, 255, -1)
        cv2.rectangle(mask, (150, 65), (174, 91), 0, -1)

        result = PlateMaskService(_plate_config()).complete(mask)

        self.assertEqual(result.shape_type, "ellipse")
        self.assertTrue(result.used_ellipse_completion)
        self.assertGreater(np.count_nonzero(result.mask), np.count_nonzero(mask))

    def test_rectangular_tray_uses_measured_contour(self) -> None:
        mask = np.zeros((320, 320), np.uint8)
        cv2.rectangle(mask, (55, 85), (270, 245), 255, -1)
        cv2.rectangle(mask, (145, 80), (180, 105), 0, -1)

        result = PlateMaskService(_plate_config()).complete(mask)

        self.assertEqual(result.shape_type, "quadrilateral")
        self.assertFalse(result.used_ellipse_completion)
        self.assertTrue(result.used_contour_completion)
        self.assertLessEqual(
            float(result.metrics["completion_area_ratio"]),
            1.25,
        )

    def test_low_confidence_irregular_mask_keeps_source_component(self) -> None:
        mask = np.zeros((320, 320), np.uint8)
        points = np.array(
            [[40, 140], [130, 70], [160, 145], [255, 80], [280, 230], [95, 260]],
            np.int32,
        )
        cv2.fillPoly(mask, [points], 255)
        config = _plate_config()
        config["minimum_shape_confidence"] = 0.99

        result = PlateMaskService(config).complete(mask)

        self.assertTrue(result.metrics["fallback_to_source_mask"])
        self.assertEqual(
            np.count_nonzero(result.mask),
            np.count_nonzero(mask),
        )


class IndependentMaskQualityTest(unittest.TestCase):
    def test_food_and_plate_are_scored_independently(self) -> None:
        plate = np.zeros((320, 320), np.uint8)
        cv2.ellipse(plate, (160, 160), (110, 95), 0, 0, 360, 255, -1)
        food = np.zeros_like(plate)
        cv2.circle(food, (160, 160), 48, 255, -1)

        food_result = assess_food_mask_quality(food, plate_mask=plate)
        plate_result = assess_plate_mask_quality(
            plate,
            source_mask=plate,
            shape_type="ellipse",
            shape_confidence=0.9,
        )

        self.assertTrue(food_result.passed)
        self.assertTrue(plate_result.passed)
        self.assertIn("plate_overlap_ratio", food_result.metrics)
        self.assertIn("internal_hole_ratio", plate_result.metrics)

    def test_fragmented_food_does_not_make_plate_quality_fail(self) -> None:
        plate = np.zeros((320, 320), np.uint8)
        cv2.rectangle(plate, (45, 70), (275, 250), 255, -1)
        food = np.zeros_like(plate)
        for x in range(55, 265, 35):
            cv2.circle(food, (x, 155), 5, 255, -1)

        food_result = assess_food_mask_quality(
            food,
            plate_mask=plate,
            config={"minimum_largest_component_ratio": 0.50},
        )
        plate_result = assess_plate_mask_quality(
            plate,
            source_mask=plate,
            shape_type="quadrilateral",
            shape_confidence=0.9,
        )

        self.assertFalse(food_result.passed)
        self.assertTrue(plate_result.passed)


class AdaptiveRimObservationTest(unittest.TestCase):
    def test_non_green_rim_color_is_estimated_from_image(self) -> None:
        shape = (400, 400)
        image = np.full((*shape, 3), (170, 170, 170), np.uint8)
        plate = np.zeros(shape, np.uint8)
        cv2.ellipse(plate, (200, 205), (125, 110), 0, 0, 360, 255, -1)
        image[plate > 0] = (230, 232, 235)
        red_rim = np.zeros(shape, np.uint8)
        cv2.ellipse(red_rim, (200, 200), (125, 110), 0, 0, 360, 255, 7)
        image[red_rim > 0] = (35, 45, 190)
        food = np.zeros(shape, np.uint8)
        cv2.rectangle(food, (185, 86), (218, 122), 255, -1)
        image[food > 0] = (90, 130, 180)

        result = observe_container_rim(
            image,
            plate,
            food,
            shape_type="ellipse",
            config={
                "minimum_observed_pixels": 40,
                "minimum_confidence": 0.45,
                "expected_line_dilation": 25,
                "plate_guard_dilation": 12,
            },
        )

        self.assertTrue(result.metrics["used"])
        self.assertIsNotNone(result.color_bgr)
        assert result.color_bgr is not None
        self.assertGreater(int(result.color_bgr[2]), int(result.color_bgr[1]) + 80)

    def test_low_confidence_disables_synthetic_rim(self) -> None:
        shape = (320, 320)
        image = np.full((*shape, 3), 180, np.uint8)
        plate = np.zeros(shape, np.uint8)
        cv2.ellipse(plate, (160, 160), (105, 95), 0, 0, 360, 255, -1)
        food = np.zeros(shape, np.uint8)
        cv2.rectangle(food, (145, 55), (175, 92), 255, -1)
        config = {
            "enabled": True,
            "restore_rim_line": True,
            "rim_line_opacity": 0.0,
            "rim_line_bridge_occlusions": False,
            "rim_missing_detection_enabled": False,
            "rim_missing_surface_fill_enabled": False,
            "synthetic_rim_bridge_enabled": True,
            "synthetic_rim_bridge_mode": "observed_contour_gap",
            "synthetic_rim_bridge_dilate": True,
            "synthetic_rim_bridge_extra_width": 3,
            "plate_edge_alpha_extension_enabled": True,
            "adaptive_rim_observation": {
                "enabled": True,
                "minimum_confidence": 0.999,
                "minimum_observed_pixels": 40,
            },
        }

        result = repair_plate_edge(
            image,
            plate,
            food,
            config,
            shape_type="ellipse",
            plate_quality={"passed": True},
            food_quality={"passed": True},
        )

        self.assertEqual(result.metrics["synthetic_rim_bridge_pixels"], 0)
        self.assertEqual(result.metrics["alpha_extension_pixels"], 0)
        self.assertFalse(result.metrics["synthetic_rim_allowed"])


if __name__ == "__main__":
    unittest.main()
