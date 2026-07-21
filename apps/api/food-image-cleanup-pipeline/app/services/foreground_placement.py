from __future__ import annotations

import cv2
import numpy as np


def place_foreground(
    foreground_bgr: np.ndarray,
    alpha: np.ndarray,
    *,
    placement: str,
    width_ratio: float,
) -> tuple[np.ndarray, np.ndarray, dict[str, float | int | str]]:
    """Resize the detected dish to a controlled canvas share and place it safely."""
    if foreground_bgr.shape[:2] != alpha.shape:
        raise ValueError("foreground and alpha must have matching dimensions")
    ys, xs = np.where(alpha > 0)
    if len(xs) == 0:
        raise ValueError("foreground alpha is empty")
    height, width = alpha.shape
    x1, x2, y1, y2 = xs.min(), xs.max() + 1, ys.min(), ys.max() + 1
    crop = foreground_bgr[y1:y2, x1:x2]
    crop_alpha = alpha[y1:y2, x1:x2]
    requested_width = int(round(width * float(np.clip(width_ratio, 0.55, 0.70))))
    scale = min(requested_width / max(crop.shape[1], 1), (height * 0.78) / max(crop.shape[0], 1))
    target_width = max(1, int(round(crop.shape[1] * scale)))
    target_height = max(1, int(round(crop.shape[0] * scale)))
    resized = cv2.resize(crop, (target_width, target_height), interpolation=cv2.INTER_LANCZOS4)
    resized_alpha = cv2.resize(crop_alpha, (target_width, target_height), interpolation=cv2.INTER_LANCZOS4)
    x = max(0, min(width - target_width, (width - target_width) // 2))
    if placement == "center":
        y = max(0, min(height - target_height, (height - target_height) // 2))
    else:
        y = max(0, min(height - target_height, int(height * 0.59 - target_height / 2)))
    canvas = np.zeros_like(foreground_bgr)
    canvas_alpha = np.zeros_like(alpha)
    canvas[y : y + target_height, x : x + target_width] = resized
    canvas_alpha[y : y + target_height, x : x + target_width] = resized_alpha
    return canvas, canvas_alpha, {
        "placement": placement,
        "width_ratio": round(target_width / width, 6),
        "scale": round(scale, 6),
        "x": x,
        "y": y,
        "width": target_width,
        "height": target_height,
    }


def fit_background(background: np.ndarray, target_shape: tuple[int, int]) -> np.ndarray:
    """Resize a generated background to the preserved foreground canvas."""
    height, width = target_shape
    if background.shape[:2] == (height, width):
        return background.copy()
    return cv2.resize(background, (width, height), interpolation=cv2.INTER_LANCZOS4)
