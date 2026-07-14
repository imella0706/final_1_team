from dataclasses import dataclass

from app.core.config import settings
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
        id=ImageModel.OPENAI_GPT_IMAGE_1_MINI,
        name="OpenAI gpt-image-1-mini",
        provider="OpenAI",
        availability=ImageModelAvailability.HOSTED,
        note=(
            "현재 프로젝트 API 키로 호출 성공을 확인한 OpenAI 이미지 생성 모델입니다. "
            "저비용/일반 이미지 생성용으로 우선 사용합니다."
        ),
        recommended=True,
    ),
    ImageModelSpec(
        id=ImageModel.OPENAI_GPT_IMAGE_1,
        name="OpenAI gpt-image-1",
        provider="OpenAI",
        availability=ImageModelAvailability.HOSTED,
        note="OpenAI 이미지 생성 모델입니다. 계정/프로젝트 권한과 RPM 제한을 확인해야 합니다.",
    ),
    ImageModelSpec(
        id=ImageModel.OPENAI_GPT_IMAGE_2,
        name="OpenAI gpt-image-2",
        provider="OpenAI",
        availability=ImageModelAvailability.HOSTED,
        note=(
            "고성능 OpenAI 이미지 생성 모델입니다. 현재 테스트한 키에서는 RPM Limit 0으로 호출이 막혔습니다."
        ),
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

COMFYUI_IMAGE_MODEL_CATALOG = (
    ImageModelSpec(
        id=ImageModel.FLUX_SCHNELL,
        name="FLUX.1 Schnell GGUF",
        provider="Local ComfyUI",
        availability=ImageModelAvailability.GATED,
        note="Local Flux Schnell pipeline served by ComfyUI with the GGUF loader.",
        recommended=True,
    ),
)


def list_image_model_options() -> list[ImageModelOption]:
    catalog = (
        COMFYUI_IMAGE_MODEL_CATALOG
        if settings.image_provider.lower() == "comfyui"
        else IMAGE_MODEL_CATALOG
    )
    return [
        ImageModelOption(
            id=spec.id,
            name=spec.name,
            provider=spec.provider,
            availability=spec.availability,
            recommended=spec.recommended,
            note=spec.note,
        )
        for spec in catalog
    ]
