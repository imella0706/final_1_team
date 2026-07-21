from dataclasses import asdict, dataclass
import cv2
import numpy as np
from app.core.config import QualityConfig

@dataclass(slots=True)
class QualityMetrics:
    width: int
    height: int
    brightness_mean: float
    contrast_std: float
    blur_score: float
    shadow_clipping_ratio: float
    highlight_clipping_ratio: float
    is_blurry: bool
    is_dark: bool
    is_bright: bool
    is_low_contrast: bool
    has_clipping: bool
    def to_dict(self) -> dict:
        return asdict(self)

def analyze_quality(
    image: np.ndarray, config: QualityConfig, mask: np.ndarray | None = None
) -> QualityMetrics:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    if mask is not None:
        if mask.shape != gray.shape:
            raise ValueError("mask must match image dimensions")
        selector = mask > 0
        if not np.any(selector):
            raise ValueError("quality mask is empty")
    else:
        selector = np.ones(gray.shape, dtype=bool)
    pixels = gray[selector]
    laplacian = cv2.Laplacian(gray, cv2.CV_64F)[selector]
    brightness = float(pixels.mean())
    contrast = float(pixels.std())
    blur = float(laplacian.var())
    shadow = float(np.mean(pixels <= 5))
    highlight = float(np.mean(pixels >= 250))
    h, w = gray.shape
    return QualityMetrics(
        width=w, height=h,
        brightness_mean=round(brightness, 4),
        contrast_std=round(contrast, 4),
        blur_score=round(blur, 4),
        shadow_clipping_ratio=round(shadow, 6),
        highlight_clipping_ratio=round(highlight, 6),
        is_blurry=blur < config.blur_threshold,
        is_dark=brightness < config.dark_mean_threshold,
        is_bright=brightness > config.bright_mean_threshold,
        is_low_contrast=contrast < config.low_contrast_std_threshold,
        has_clipping=(shadow + highlight) > config.clipping_ratio_threshold,
    )
