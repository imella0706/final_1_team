from __future__ import annotations

import cv2
import numpy as np


def add_contact_shadow(background: np.ndarray, alpha: np.ndarray, config: dict) -> np.ndarray:
    """Place a soft shadow beneath the foreground before alpha compositing."""
    if not config.get("enabled", True) or not np.any(alpha):
        return background.copy()
    offset_y, offset_x = int(config.get("vertical_offset", 8)), int(config.get("horizontal_offset", 3))
    blur = max(1, int(config.get("blur_radius", 18)))
    if blur % 2 == 0:
        blur += 1
    opacity = float(np.clip(config.get("opacity", 0.22), 0.0, 1.0))
    shadow = np.zeros_like(alpha)
    matrix = np.float32([[1, 0, offset_x], [0, 1, offset_y]])
    shifted = cv2.warpAffine(alpha, matrix, (alpha.shape[1], alpha.shape[0]))
    shadow = cv2.GaussianBlur(shifted, (blur, blur), 0).astype(np.float32) / 255.0
    factor = 1.0 - shadow[:, :, None] * opacity
    return np.clip(background.astype(np.float32) * factor, 0, 255).astype(np.uint8)
