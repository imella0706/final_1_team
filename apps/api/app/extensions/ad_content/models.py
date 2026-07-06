from dataclasses import dataclass

from app.extensions.ad_content.schemas import (
    ImageModel,
    ImageModelAvailability,
    ImageModelOption,
)


@dataclass(frozen=True)
class ImageModelSpec:
    id: ImageModel
    name: str
    provider: str
    availability: ImageModelAvailability
    note: str
    recommended: bool = False


IMAGE_MODEL_CATALOG = (
    ImageModelSpec(
        id=ImageModel.FLUX_SCHNELL,
        name="FLUX.1 Schnell",
        provider="Hugging Face Inference",
        availability=ImageModelAvailability.HOSTED,
        note="Fast prompt-following model for polished ad visual drafts.",
    ),
    ImageModelSpec(
        id=ImageModel.SDXL_BASE,
        name="Stable Diffusion XL Base 1.0",
        provider="Hugging Face Inference",
        availability=ImageModelAvailability.HOSTED,
        note="General-purpose image generation model with broad style coverage.",
    ),
    ImageModelSpec(
        id=ImageModel.OPENJOURNEY,
        name="Openjourney",
        provider="Hugging Face Inference",
        availability=ImageModelAvailability.HOSTED,
        note="Stylized promotional visuals and editorial poster concepts.",
    ),
)


def list_image_model_options() -> list[ImageModelOption]:
    return [
        ImageModelOption(
            id=spec.id,
            name=spec.name,
            provider=spec.provider,
            availability=spec.availability,
            recommended=spec.recommended,
            note=spec.note,
        )
        for spec in IMAGE_MODEL_CATALOG
    ]
