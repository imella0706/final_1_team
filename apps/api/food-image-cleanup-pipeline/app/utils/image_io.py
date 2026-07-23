from pathlib import Path
import cv2
import numpy as np
from PIL import Image, ImageOps
from app.core.config import ImageConfig

class ImageValidationError(ValueError):
    pass

def validate_image_path(image_path: str | Path, config: ImageConfig) -> Path:
    path = Path(image_path)
    if not path.exists():
        raise FileNotFoundError(f"이미지 파일이 없습니다: {path}")
    if not path.is_file():
        raise ImageValidationError(f"파일 경로가 아닙니다: {path}")
    if path.suffix.lower() not in set(config.allowed_extensions):
        raise ImageValidationError(f"지원하지 않는 확장자입니다: {path.suffix}")
    size_mb = path.stat().st_size / (1024 * 1024)
    if size_mb > config.max_file_size_mb:
        raise ImageValidationError(f"파일 크기 제한 초과: {size_mb:.2f}MB")
    return path

def load_image(image_path: str | Path, config: ImageConfig) -> np.ndarray:
    path = validate_image_path(image_path, config)
    try:
        with Image.open(path) as pil_image:
            pil_image = ImageOps.exif_transpose(pil_image).convert("RGB")
            rgb = np.asarray(pil_image)
    except Exception as exc:
        raise ImageValidationError(f"이미지를 읽을 수 없습니다: {path}") from exc
    return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)

def resize_for_processing(image: np.ndarray, max_long_side: int) -> np.ndarray:
    height, width = image.shape[:2]
    long_side = max(height, width)
    if long_side <= max_long_side:
        return image.copy()
    scale = max_long_side / long_side
    new_size = (max(1, round(width * scale)), max(1, round(height * scale)))
    return cv2.resize(image, new_size, interpolation=cv2.INTER_AREA)

def save_image(image: np.ndarray, output_path: str | Path, jpeg_quality: int = 95) -> Path:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    params = [cv2.IMWRITE_JPEG_QUALITY, jpeg_quality] if path.suffix.lower() in {".jpg", ".jpeg"} else []
    if not cv2.imwrite(str(path), image, params):
        raise IOError(f"이미지 저장 실패: {path}")
    return path
