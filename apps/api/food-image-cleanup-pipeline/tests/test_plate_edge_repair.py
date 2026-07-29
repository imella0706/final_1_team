from __future__ import annotations

import unittest

import cv2
import numpy as np

from app.services.plate_edge_repair import repair_plate_edge


def _synthetic_case() -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    shape = (512, 512)
    image = np.full((*shape, 3), (210, 210, 210), dtype=np.uint8)

    physical_plate = np.zeros(shape, dtype=np.uint8)
    cv2.ellipse(physical_plate, (256, 250), (165, 165), 0, 0, 360, 255, -1)
    image[physical_plate > 0] = (225, 235, 238)

    physical_rim = np.zeros(shape, dtype=np.uint8)
    cv2.ellipse(physical_rim, (256, 250), (165, 165), 0, 0, 360, 255, 7)
    image[physical_rim > 0] = (45, 105, 35)

    # The segmentation ellipse is intentionally lower than the real colored rim.
    plate_mask = np.zeros(shape, dtype=np.uint8)
    cv2.ellipse(plate_mask, (256, 266), (170, 175), 0, 0, 360, 255, -1)

    # A skewer-like occluder removes a short section of the real top rim.
    food_mask = np.zeros(shape, dtype=np.uint8)
    cv2.rectangle(food_mask, (235, 72), (277, 116), 255, -1)
    image[food_mask > 0] = (150, 190, 220)
    return image, plate_mask, food_mask, physical_rim


def _config() -> dict[str, object]:
    return {
        "enabled": True,
        "ring_width": 28,
        "food_core_erosion": 17,
        "close_kernel": 5,
        "max_component_area": 24000,
        "inpaint_radius": 7.0,
        "method": "telea",
        "restore_rim_line": True,
        "rim_line_width": 5,
        "restore_inner_rim_line": True,
        "inner_rim_line_width": 5,
        "inner_rim_line_inset": 22,
        "color_aligned_rim_enabled": True,
        "color_aligned_rim_line_width": 5,
        "color_aligned_rim_inset_min": 4,
        "color_aligned_rim_inset_max": 42,
        "color_aligned_rim_inset_step": 2,
        "color_aligned_rim_top_ratio": 0.36,
        "color_aligned_rim_allow_food_overlap": False,
        "color_aligned_rim_min_overlap_pixels": 16,
        "rim_line_opacity": 0.0,
        "rim_line_bridge_occlusions": True,
        "rim_missing_detection_enabled": True,
        "rim_missing_surface_fill_enabled": False,
        "rim_missing_core_blend_enabled": False,
        "synthetic_rim_bridge_enabled": True,
        "synthetic_rim_bridge_mode": "observed_contour_gap",
        "synthetic_rim_bridge_top_ratio": 0.30,
        "synthetic_rim_bridge_dilation": 55,
        "synthetic_rim_bridge_connect_full_top": False,
        "synthetic_rim_bridge_gap_observed_dilation": 7,
        "synthetic_rim_bridge_gap_anchor_close_kernel": 5,
        "synthetic_rim_bridge_gap_min_width": 3,
        "synthetic_rim_bridge_gap_max_width": 96,
        "synthetic_rim_bridge_gap_endpoint_margin": 4,
        "synthetic_rim_bridge_plate_outside_tolerance": 9,
        "synthetic_rim_bridge_dilate": True,
        "synthetic_rim_bridge_extra_width": 3,
        "synthetic_rim_bridge_allow_food_overlap": True,
        "synthetic_rim_bridge_opacity": 0.98,
        "synthetic_rim_bridge_feather_kernel": 3,
        "synthetic_rim_band_enabled": False,
        "synthetic_rim_color_min_samples": 24,
        "synthetic_rim_color_saturation_min": 45,
        "synthetic_rim_color_value_min": 30,
        "synthetic_rim_color_value_max": 210,
        "synthetic_rim_color_hue_window": 14,
        "synthetic_rim_color_hue_min": 35,
        "synthetic_rim_color_hue_max": 95,
        "observed_rim_fit_enabled": True,
        "observed_rim_fit_line_width": 5,
        "observed_rim_fit_boundary_width": 42,
        "observed_rim_fit_plate_dilation": 9,
        "observed_rim_fit_min_component_area": 8,
        "observed_rim_fit_min_pixels": 128,
        "observed_rim_fit_observed_dilation": 7,
        "observed_rim_fit_min_overlap_ratio": 0.55,
        "observed_rim_fit_max_aspect_ratio": 1.35,
        "observed_rim_fit_min_area_ratio": 0.55,
        "observed_rim_fit_max_area_ratio": 1.05,
        "observed_rim_fit_max_center_shift_ratio": 0.08,
        "plate_edge_alpha_extension_enabled": True,
        "plate_mask_rim_completion_enabled": False,
        "rim_line_bridge_occlusions": False,
        "rim_missing_detection_enabled": False,
    }


class PlateEdgeRepairTest(unittest.TestCase):
    def test_observed_rim_gap_is_bridged_without_full_outer_arc(self) -> None:
        image, plate_mask, food_mask, physical_rim = _synthetic_case()
        result = repair_plate_edge(image, plate_mask, food_mask, _config())

        self.assertTrue(result.metrics["adaptive_rim_observation"]["used"])
        self.assertEqual(
            result.metrics["adaptive_rim_observation"]["representative_color_bgr"],
            [45, 105, 35],
        )
        self.assertGreaterEqual(result.metrics["bracketed_rim_gap"]["gap_count"], 1)
        self.assertGreater(result.metrics["synthetic_rim_bridge_pixels"], 0)
        self.assertIsNotNone(result.alpha_extension_mask)
        assert result.alpha_extension_mask is not None
        self.assertGreater(np.count_nonzero(result.alpha_extension_mask), 0)

        physical_rim_guard = cv2.dilate(
            physical_rim,
            cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9)),
        )
        extension_outside_real_rim = np.count_nonzero(
            (result.alpha_extension_mask > 0) & (physical_rim_guard == 0)
        )
        self.assertEqual(extension_outside_real_rim, 0)

        gap_region = np.zeros_like(physical_rim)
        gap_region[78:112, 230:282] = 255
        before_green = cv2.inRange(image, (20, 70, 15), (90, 150, 80))
        after_green = cv2.inRange(result.image, (20, 70, 15), (90, 150, 80))
        self.assertGreater(
            np.count_nonzero(cv2.bitwise_and(after_green, gap_region)),
            np.count_nonzero(cv2.bitwise_and(before_green, gap_region)),
        )


if __name__ == "__main__":
    unittest.main()
