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

def analyze_quality(image: np.ndarray, config: QualityConfig) -> QualityMetrics:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    brightness = float(gray.mean())
    contrast = float(gray.std())
    blur = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    shadow = float(np.mean(gray <= 5))
    highlight = float(np.mean(gray >= 250))
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
