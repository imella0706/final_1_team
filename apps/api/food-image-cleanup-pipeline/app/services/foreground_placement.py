from __future__ import annotations

import cv2
import numpy as np


def fit_background(background: np.ndarray, target_shape: tuple[int, int]) -> np.ndarray:
    """Resize a generated background to the preserved foreground canvas."""
    height, width = target_shape
    if background.shape[:2] == (height, width):
        return background.copy()
    return cv2.resize(background, (width, height), interpolation=cv2.INTER_LANCZOS4)
