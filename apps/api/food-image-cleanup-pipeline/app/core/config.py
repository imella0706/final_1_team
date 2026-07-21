from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field


class PathConfig(BaseModel):
    input_dir: Path = Path("data/input")
    mask_dir: Path = Path("data/masks")
    intermediate_dir: Path = Path("data/intermediate")
    output_dir: Path = Path("data/output")
    report_dir: Path = Path("data/reports")
    model_dir: Path = Path("models")
    log_dir: Path = Path("logs")


class ImageConfig(BaseModel):
    allowed_extensions: list[str] = [".jpg", ".jpeg", ".png", ".webp"]
    max_file_size_mb: int = Field(default=25, gt=0)
    max_long_side: int = Field(default=1536, gt=0)
    min_long_side: int = Field(default=768, gt=0)
    jpeg_quality: int = Field(default=95, ge=1, le=100)


class QualityConfig(BaseModel):
    blur_threshold: float = Field(default=80.0, ge=0)
    dark_mean_threshold: float = Field(default=55.0, ge=0, le=255)
    bright_mean_threshold: float = Field(default=210.0, ge=0, le=255)
    low_contrast_std_threshold: float = Field(default=28.0, ge=0)
    clipping_ratio_threshold: float = Field(default=0.08, ge=0, le=1)


class ValidationConfig(BaseModel):
    max_brightness_delta: float = Field(default=35.0, ge=0)
    max_contrast_delta: float = Field(default=35.0, ge=0)
    max_blur_score_drop_ratio: float = Field(default=0.20, ge=0, le=1)


class PipelineConfig(BaseModel):
    project: dict[str, Any] = {}
    paths: PathConfig = PathConfig()
    image: ImageConfig = ImageConfig()
    quality: QualityConfig = QualityConfig()
    models: dict[str, Any] = {}
    validation: ValidationConfig = ValidationConfig()


def _ensure_directories(config: PipelineConfig) -> None:
    for value in config.paths.model_dump().values():
        Path(value).mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=4)
def load_config(path: str = "configs/pipeline.yaml") -> PipelineConfig:
    config_path = Path(path)

    if not config_path.is_file():
        raise FileNotFoundError(f"설정 파일이 없습니다: {config_path.resolve()}")

    with config_path.open("r", encoding="utf-8") as fp:
        raw = yaml.safe_load(fp) or {}

    config = PipelineConfig.model_validate(raw)
    _ensure_directories(config)
    return config
