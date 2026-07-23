from __future__ import annotations

import cv2
import numpy as np


def harmonize_foreground(foreground_bgr: np.ndarray, alpha: np.ndarray, background_bgr: np.ndarray, config: dict) -> np.ndarray:
    """Apply bounded low-frequency brightness and colour adaptation to the original foreground."""
    if not config.get("enabled", True) or not np.any(alpha):
        return foreground_bgr.copy()
    mask = alpha > 200
    background_pixels = background_bgr[~mask]
    foreground_pixels = foreground_bgr[mask]
    if not len(background_pixels) or not len(foreground_pixels):
        return foreground_bgr.copy()
    bg_lab = cv2.cvtColor(background_bgr, cv2.COLOR_BGR2LAB)
    fg_lab = cv2.cvtColor(foreground_bgr, cv2.COLOR_BGR2LAB)
    max_delta = float(config.get("max_brightness_delta", 12.0))
    delta_l = float(np.clip(bg_lab[:, :, 0][~mask].mean() - fg_lab[:, :, 0][mask].mean(), -max_delta, max_delta))
    result = fg_lab.astype(np.float32)
    result[:, :, 0] = np.clip(result[:, :, 0] + delta_l, 0, 255)
    return cv2.cvtColor(result.astype(np.uint8), cv2.COLOR_LAB2BGR)
