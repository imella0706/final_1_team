from __future__ import annotations

import cv2
import numpy as np


def remove_color_spill(foreground_bgr: np.ndarray, alpha: np.ndarray, background_bgr: np.ndarray) -> np.ndarray:
    """Reduce original-background colour spill only in the semi-transparent edge band."""
    if foreground_bgr.shape != background_bgr.shape or foreground_bgr.shape[:2] != alpha.shape:
        raise ValueError("foreground, alpha and background sizes must match")
    binary = (alpha >= 250).astype(np.uint8) * 255
    edge = cv2.subtract(cv2.dilate(binary, np.ones((3, 3), np.uint8)), cv2.erode(binary, np.ones((3, 3), np.uint8)))
    edge_weight = (edge.astype(np.float32) / 255.0)[:, :, None] * (alpha[:, :, None].astype(np.float32) / 255.0)
    foreground = foreground_bgr.astype(np.float32)
    background = cv2.GaussianBlur(background_bgr, (0, 0), 3).astype(np.float32)
    neutralized = foreground * 0.88 + background * 0.12
    return np.clip(foreground * (1 - edge_weight) + neutralized * edge_weight, 0, 255).astype(np.uint8)
