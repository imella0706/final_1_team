from dataclasses import asdict, dataclass
from app.core.config import ValidationConfig
from app.services.quality import QualityMetrics

@dataclass(slots=True)
class ValidationResult:
    passed: bool
    reasons: list[str]
    brightness_delta: float
    contrast_delta: float
    blur_score_drop_ratio: float
    def to_dict(self) -> dict:
        return asdict(self)

def validate_result(before: QualityMetrics, after: QualityMetrics, config: ValidationConfig) -> ValidationResult:
    reasons = []
    brightness_delta = abs(after.brightness_mean - before.brightness_mean)
    contrast_delta = abs(after.contrast_std - before.contrast_std)
    blur_drop = 0.0 if before.blur_score <= 1e-6 else max(0.0, (before.blur_score - after.blur_score) / before.blur_score)
    if brightness_delta > config.max_brightness_delta:
        reasons.append(f"밝기 변화량 초과: {brightness_delta:.2f}")
    if contrast_delta > config.max_contrast_delta:
        reasons.append(f"대비 변화량 초과: {contrast_delta:.2f}")
    if blur_drop > config.max_blur_score_drop_ratio:
        reasons.append(f"선명도 저하 비율 초과: {blur_drop:.3f}")
    return ValidationResult(not reasons, reasons, round(brightness_delta, 4), round(contrast_delta, 4), round(blur_drop, 6))
