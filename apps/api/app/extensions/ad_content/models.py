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
        id=ImageModel.OPENAI_GPT_IMAGE_1,
        name="OpenAI gpt-image-1",
        provider="OpenAI",
        availability=ImageModelAvailability.HOSTED,
        note="OpenAI 이미지 생성 모델. BRANDMATE_OPENAI_API_KEY가 필요합니다.",
        recommended=True,
    ),
    ImageModelSpec(
        id=ImageModel.OPENAI_GPT_5_2_IMAGE_TOOL,
        name="GPT-5.2 + image_generation tool",
        provider="OpenAI Responses API",
        availability=ImageModelAvailability.HOSTED,
        note=(
            "GPT-5.2가 Responses API의 image_generation 도구를 호출하는 방식입니다. "
            "이미지 생성 권한/RPM은 별도로 필요합니다."
        ),
    ),
    ImageModelSpec(
        id=ImageModel.OPENAI_GPT_5_5_IMAGE_TOOL,
        name="GPT-5.5 + image_generation tool",
        provider="OpenAI Responses API",
        availability=ImageModelAvailability.HOSTED,
        note=(
            "GPT-5.5가 Responses API의 image_generation 도구를 호출하는 방식입니다. "
            "이미지 생성 권한/RPM은 별도로 필요합니다."
        ),
    ),
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
