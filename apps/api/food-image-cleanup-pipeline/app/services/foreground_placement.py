from __future__ import annotations

import cv2
import numpy as np


def place_foreground(
    foreground_bgr: np.ndarray,
    alpha: np.ndarray,
    *,
    placement: str,
    width_ratio: float,
    safe_padding_px: int = 24,
    canvas_margin_px: int = 32,
    alpha_crop_threshold: int = 1,
    anchor_center: tuple[float, float] | None = None,
    minimum_width_ratio: float = 0.30,
) -> tuple[np.ndarray, np.ndarray, dict[str, float | int | str]]:
    """Resize a dish while preserving a transparent safety border around its rim."""
    if foreground_bgr.shape[:2] != alpha.shape:
        raise ValueError("foreground and alpha must have matching dimensions")
    ys, xs = np.where(alpha >= max(1, int(alpha_crop_threshold)))
    if len(xs) == 0:
        raise ValueError("foreground alpha is empty")
    height, width = alpha.shape
    x1, x2, y1, y2 = xs.min(), xs.max() + 1, ys.min(), ys.max() + 1
    padding = max(0, int(safe_padding_px))
    crop_x1, crop_x2 = max(0, x1 - padding), min(width, x2 + padding)
    crop_y1, crop_y2 = max(0, y1 - padding), min(height, y2 + padding)
    crop = foreground_bgr[crop_y1:crop_y2, crop_x1:crop_x2]
    crop_alpha = alpha[crop_y1:crop_y2, crop_x1:crop_x2]
    requested_object_width = int(
        round(width * float(np.clip(width_ratio, minimum_width_ratio, 0.70)))
    )
    margin = max(0, int(canvas_margin_px))
    scale = min(
        requested_object_width / max(x2 - x1, 1),
        (width - margin * 2) / max(crop.shape[1], 1),
        (height - margin * 2) / max(crop.shape[0], 1),
    )
    target_width = max(1, int(round(crop.shape[1] * scale)))
    target_height = max(1, int(round(crop.shape[0] * scale)))
    resized = cv2.resize(crop, (target_width, target_height), interpolation=cv2.INTER_LANCZOS4)
    resized_alpha = cv2.resize(crop_alpha, (target_width, target_height), interpolation=cv2.INTER_LANCZOS4)
    object_x_offset = int(round((x1 - crop_x1) * scale))
    object_y_offset = int(round((y1 - crop_y1) * scale))
    object_width = max(1, int(round((x2 - x1) * scale)))
    object_height = max(1, int(round((y2 - y1) * scale)))
    if anchor_center is not None:
        anchor_x, anchor_y = anchor_center
        x = int(round(width * anchor_x - object_x_offset - object_width * 0.5))
        y = int(round(height * anchor_y - object_y_offset - object_height * 0.5))
    else:
        x = int(round(width * 0.5 - object_x_offset - object_width * 0.5))
        if placement == "center":
            y = int(round(height * 0.5 - object_y_offset - object_height * 0.5))
        else:
            y = int(round(height * 0.59 - object_y_offset - object_height * 0.5))
    x = max(margin, min(width - margin - target_width, x))
    y = max(margin, min(height - margin - target_height, y))
    canvas = np.zeros_like(foreground_bgr)
    canvas_alpha = np.zeros_like(alpha)
    canvas[y : y + target_height, x : x + target_width] = resized
    canvas_alpha[y : y + target_height, x : x + target_width] = resized_alpha
    return canvas, canvas_alpha, {
        "placement": placement,
        "width_ratio": round(object_width / width, 6),
        "scale": round(scale, 6),
        "x": x,
        "y": y,
        "width": target_width,
        "height": target_height,
        "object_width": object_width,
        "object_height": object_height,
        "safe_padding_px": padding,
        "canvas_margin_px": margin,
        "anchor_x": round(float(anchor_center[0]), 6) if anchor_center else 0.5,
        "anchor_y": round(float(anchor_center[1]), 6) if anchor_center else (
            0.5 if placement == "center" else 0.59
        ),
    }


def fit_background(background: np.ndarray, target_shape: tuple[int, int]) -> np.ndarray:
    """Resize a generated background to the preserved foreground canvas."""
    height, width = target_shape
    if background.shape[:2] == (height, width):
        return background.copy()
    return cv2.resize(background, (width, height), interpolation=cv2.INTER_LANCZOS4)
