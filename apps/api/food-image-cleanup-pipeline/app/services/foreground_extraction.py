from __future__ import annotations

import cv2
import numpy as np


def foreground_mask(food_mask: np.ndarray | None, container_mask: np.ndarray | None) -> np.ndarray:
    """Combine food and its serving container into one protected foreground."""
    if food_mask is None and container_mask is None:
        raise ValueError("at least one foreground mask is required")
    if food_mask is None:
        return container_mask.copy()
    if container_mask is None:
        return food_mask.copy()
    if food_mask.shape != container_mask.shape:
        raise ValueError("food_mask and container_mask must have the same size")
    return np.maximum(food_mask, container_mask)


def extract_rgba(image: np.ndarray, alpha: np.ndarray) -> np.ndarray:
    """Return a BGRA foreground while preserving the original food pixels."""
    if image.shape[:2] != alpha.shape:
        raise ValueError("alpha matte must match the image size")
    if image.ndim != 3 or image.shape[2] != 3:
        raise ValueError("image must be a three-channel BGR image")
    return np.dstack((image, alpha.astype(np.uint8)))


def alpha_composite(foreground_bgra: np.ndarray, background_bgr: np.ndarray) -> np.ndarray:
    """Composite an original-pixel foreground on a generated BGR background."""
    if foreground_bgra.shape[:2] != background_bgr.shape[:2]:
        raise ValueError("foreground and background must have the same size")
    alpha = foreground_bgra[:, :, 3:4].astype(np.float32) / 255.0
    return np.clip(
        foreground_bgra[:, :, :3].astype(np.float32) * alpha
        + background_bgr.astype(np.float32) * (1.0 - alpha),
        0,
        255,
    ).astype(np.uint8)
