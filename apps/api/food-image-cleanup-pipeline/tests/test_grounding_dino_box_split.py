from __future__ import annotations

import unittest

from app.services.grounding_dino import (
    GroundingDetection,
    split_plate_and_food_boxes,
)


class GroundingDINOBoxSplitTest(unittest.TestCase):
    def test_food_support_labels_are_forwarded_to_sam_food_boxes(self) -> None:
        detections = [
            GroundingDetection("plate", 0.91, (10, 20, 210, 220)),
            GroundingDetection("wooden skewer", 0.84, (80, 0, 105, 130)),
            GroundingDetection("chopstick", 0.76, (120, 5, 138, 145)),
            GroundingDetection("spoon", 0.88, (250, 10, 290, 220)),
        ]

        plate_boxes, food_boxes, _ = split_plate_and_food_boxes(detections)

        self.assertEqual(plate_boxes, [(10, 20, 210, 220)])
        self.assertIn((80, 0, 105, 130), food_boxes)
        self.assertIn((120, 5, 138, 145), food_boxes)
        self.assertNotIn((250, 10, 290, 220), food_boxes)


if __name__ == "__main__":
    unittest.main()
