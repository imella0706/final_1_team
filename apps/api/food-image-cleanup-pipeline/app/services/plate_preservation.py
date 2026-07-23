from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np


@dataclass(frozen=True, slots=True)
class PlateAlphaValidation:
    """Quality gates for the original plate layer before it is composited."""

    alpha: np.ndarray
    metrics: dict[str, float | bool]


def _odd(value: int) -> int:
    value = max(1, int(value))
    return value if value % 2 else value + 1


def build_plate_preservation_alpha(
    plate_mask: np.ndarray,
    *,
    feather_kernel: int = 5,
) -> np.ndarray:
    """Create a plate alpha without letting a general matting model erase its rim.

    The plate is an original-pixel layer.  A very narrow Gaussian transition is
    allowed only outside its boundary; every interior pixel remains fully opaque.
    """
    if plate_mask.ndim != 2:
        raise ValueError("plate_mask must be a one-channel mask")

    binary = np.where(plate_mask >= 128, 255, 0).astype(np.uint8)
    if not np.any(binary):
        return binary

    kernel = _odd(feather_kernel)
    blurred = cv2.GaussianBlur(binary, (kernel, kernel), 0)
    # Do not use blurred alpha inside the plate: it is the cause of transparent
    # plate rims when the plate is later resized and composited.
    return np.where(binary > 0, 255, blurred).astype(np.uint8)


def validate_plate_preservation_alpha(
    plate_mask: np.ndarray,
    final_alpha: np.ndarray,
    *,
    minimum_coverage: float = 0.995,
    maximum_internal_gap_ratio: float = 0.002,
    validation_erosion_px: int = 2,
) -> PlateAlphaValidation:
    """Check that the final alpha still contains virtually all of the plate.

    The validation region is eroded slightly so intentional edge feathering is
    not mistaken for a missing plate rim.  Internal transparent islands still
    fail the gate and are saved in the report for diagnosis.
    """
    if plate_mask.shape != final_alpha.shape:
        raise ValueError("plate_mask and final_alpha must have the same size")

    plate = np.where(plate_mask >= 128, 255, 0).astype(np.uint8)
    if not np.any(plate):
        return PlateAlphaValidation(
            alpha=final_alpha.astype(np.uint8),
            metrics={
                "passed": False,
                "plate_pixels": 0.0,
                "opaque_coverage": 0.0,
                "internal_gap_ratio": 1.0,
            },
        )

    erosion = max(0, int(validation_erosion_px))
    if erosion:
        size = _odd(erosion * 2 + 1)
        region = cv2.erode(
            plate,
            cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (size, size)),
        )
        if not np.any(region):
            region = plate
    else:
        region = plate

    plate_pixels = int(np.count_nonzero(region))
    opaque = final_alpha >= 250
    covered = int(np.count_nonzero((region > 0) & opaque))
    coverage = covered / max(plate_pixels, 1)
    internal_gap_ratio = 1.0 - coverage
    passed = coverage >= float(minimum_coverage) and internal_gap_ratio <= float(
        maximum_internal_gap_ratio
    )
    return PlateAlphaValidation(
        alpha=final_alpha.astype(np.uint8),
        metrics={
            "passed": bool(passed),
            "plate_pixels": float(plate_pixels),
            "opaque_coverage": round(float(coverage), 6),
            "internal_gap_ratio": round(float(internal_gap_ratio), 6),
            "minimum_coverage": float(minimum_coverage),
            "maximum_internal_gap_ratio": float(maximum_internal_gap_ratio),
        },
    )
