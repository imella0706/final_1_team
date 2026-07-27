from __future__ import annotations

from typing import Any

import cv2
import numpy as np


def _odd_kernel(value: Any, default: int) -> int:
    kernel = max(1, int(value or default))
    return kernel + 1 if kernel % 2 == 0 else kernel


def apply_container_blur(
    image_bgr: np.ndarray,
    container_mask: np.ndarray,
    food_protection_mask: np.ndarray,
    config: dict[str, Any],
) -> tuple[np.ndarray, dict[str, Any], np.ndarray]:
    """Blur only the visible serving container while keeping food pixels sharp."""
    if image_bgr.ndim != 3 or image_bgr.shape[2] != 3:
        raise ValueError("image_bgr must be a three-channel BGR image")
    if image_bgr.shape[:2] != container_mask.shape:
        raise ValueError("container_mask must match image size")
    if image_bgr.shape[:2] != food_protection_mask.shape:
        raise ValueError("food_protection_mask must match image size")

    if not bool(config.get("enabled", False)):
        return image_bgr, {"status": "disabled"}, np.zeros_like(container_mask, dtype=np.uint8)

    protect_kernel = _odd_kernel(config.get("food_protection_dilation", 11), 11)
    feather_kernel = _odd_kernel(config.get("mask_feather_kernel", 9), 9)
    blur_kernel = _odd_kernel(config.get("blur_kernel", 9), 9)
    sigma = float(config.get("sigma", 0.0))
    opacity = float(np.clip(config.get("opacity", 1.0), 0.0, 1.0))

    protected_food = cv2.dilate(
        np.where(food_protection_mask > 0, 255, 0).astype(np.uint8),
        cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (protect_kernel, protect_kernel)),
    )
    target = cv2.bitwise_and(
        np.where(container_mask > 0, 255, 0).astype(np.uint8),
        cv2.bitwise_not(protected_food),
    )
    target_pixels = int(np.count_nonzero(target))
    if target_pixels == 0 or opacity <= 0.0:
        return image_bgr, {
            "status": "skipped",
            "reason": "empty_container_region" if target_pixels == 0 else "zero_opacity",
            "target_pixels": target_pixels,
        }, target

    blurred = cv2.GaussianBlur(image_bgr, (blur_kernel, blur_kernel), sigma)
    blend_mask = cv2.GaussianBlur(target, (feather_kernel, feather_kernel), 0).astype(np.float32)
    blend_mask = (blend_mask / 255.0 * opacity)[:, :, None]
    output = np.clip(
        image_bgr.astype(np.float32) * (1.0 - blend_mask)
        + blurred.astype(np.float32) * blend_mask,
        0,
        255,
    ).astype(np.uint8)
    return output, {
        "status": "completed",
        "target_pixels": target_pixels,
        "blur_kernel": blur_kernel,
        "sigma": sigma,
        "opacity": opacity,
        "mask_feather_kernel": feather_kernel,
        "food_protection_dilation": protect_kernel,
    }, target
