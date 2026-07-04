from dataclasses import dataclass

from app.core.config import settings
from app.modules.model_runtime.schemas import ImageRuntimeProvider


@dataclass(frozen=True)
class ImageModelConfig:
    display_name: str
    provider: ImageRuntimeProvider
    default_model: str
    model_setting: str


IMAGE_MODEL_MAP: dict[str, ImageModelConfig] = {
    "flux.1-schnell": ImageModelConfig(
        display_name="FLUX.1 Schnell",
        provider=ImageRuntimeProvider.DIFFUSERS,
        default_model="black-forest-labs/FLUX.1-schnell",
        model_setting="flux_model",
    ),
    "sdxl-base-1.0": ImageModelConfig(
        display_name="Stable Diffusion XL Base 1.0",
        provider=ImageRuntimeProvider.DIFFUSERS,
        default_model="stabilityai/stable-diffusion-xl-base-1.0",
        model_setting="sdxl_model",
    ),
    "openjourney": ImageModelConfig(
        display_name="Openjourney",
        provider=ImageRuntimeProvider.DIFFUSERS,
        default_model="prompthero/openjourney",
        model_setting="openjourney_model",
    ),
}


def get_image_model_config(model: str) -> ImageModelConfig:
    key = model.strip()
    if key in IMAGE_MODEL_MAP:
        return IMAGE_MODEL_MAP[key]
    for config in IMAGE_MODEL_MAP.values():
        if key in {config.display_name, config.default_model}:
            return config
    raise KeyError(f"Unknown image model: {model}")


def resolve_image_model_name(config: ImageModelConfig) -> str:
    return getattr(settings, config.model_setting, None) or config.default_model
