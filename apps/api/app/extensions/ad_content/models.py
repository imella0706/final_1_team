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
        provider="Hugging Face Router",
        availability=ImageModelAvailability.HOSTED,
        note=(
            "사진이 없으면 FLUX.1 Schnell로 생성하고, 참고 사진이 있으면 "
            "FLUX.1 Kontext image-to-image로 원본 상품을 반영합니다."
        ),
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
        provider="Hugging Face Router",
        availability=ImageModelAvailability.HOSTED,
        note="General-purpose image generation model with broad style coverage.",
    ),
    ImageModelSpec(
        id=ImageModel.OPENJOURNEY,
        name="Openjourney",
        provider="Hugging Face Router",
        availability=ImageModelAvailability.HOSTED,
        note="Stylized promotional visuals and editorial poster concepts.",
    ),
)

COMFYUI_IMAGE_MODEL_CATALOG = (
    ImageModelSpec(
        id=ImageModel.SDXL_BASE,
        name="SDXL Base 1.0 · Local img2img",
        provider="Local ComfyUI",
        availability=ImageModelAvailability.HOSTED,
        note=(
            "로컬 GPU에서 실행합니다. 사진이 있으면 img2img, 없으면 text-to-image를 "
            "사용합니다."
        ),
        recommended=True,
    ),
    ImageModelSpec(
        id=ImageModel.SDXL_TURBO,
        name="SDXL Turbo · Local",
        provider="Local ComfyUI",
        availability=ImageModelAvailability.HOSTED,
        note="1~4 step 고속 로컬 모델입니다. Base 모델과 속도·품질을 비교합니다.",
    ),
    ImageModelSpec(
        id=ImageModel.FLUX_SCHNELL,
        name="FLUX.1 Schnell Q4 · Local",
        provider="Local ComfyUI",
        availability=ImageModelAvailability.HOSTED,
        note="GGUF Q4 양자화 FLUX 모델입니다. 로컬 text-to-image 비교용입니다.",
    ),
)


def _has_secret(value: object | None) -> bool:
    if value is None:
        return False
    if hasattr(value, "get_secret_value"):
        value = value.get_secret_value()
    return bool(str(value).strip())


def _model_is_enabled(spec: ImageModelSpec, *, comfyui_available: bool) -> bool:
    if spec.provider == "Local ComfyUI":
        return comfyui_available
    if spec.provider in {"OpenAI", "OpenAI Responses API"}:
        return _has_secret(settings.openai_api_key)
    if spec.provider == "Hugging Face Router":
        return _has_secret(settings.llm_api_key)
    return False


def list_image_model_options(
    *,
    comfyui_available: bool | None = None,
) -> list[ImageModelOption]:
    comfyui_configured = settings.image_provider.lower() == "comfyui"
    if comfyui_configured:
        catalog = (
            *COMFYUI_IMAGE_MODEL_CATALOG,
            *[
                spec
                for spec in IMAGE_MODEL_CATALOG
                if spec.id
                not in {
                    ImageModel.FLUX_SCHNELL,
                    ImageModel.SDXL_BASE,
                    ImageModel.SDXL_TURBO,
                }
            ],
        )
    else:
        catalog = IMAGE_MODEL_CATALOG

    if comfyui_available is None:
        comfyui_available = comfyui_configured
    model_states = [
        (spec, _model_is_enabled(spec, comfyui_available=comfyui_available))
        for spec in catalog
    ]

    recommended_id: ImageModel | None = None
    if comfyui_configured and comfyui_available:
        recommended_id = next(
            (
                spec.id
                for spec, enabled in model_states
                if enabled and spec.provider == "Local ComfyUI" and spec.recommended
            ),
            None,
        )
    if recommended_id is None:
        recommended_id = next(
            (
                spec.id
                for spec, enabled in model_states
                if enabled and spec.id == ImageModel.OPENAI_GPT_IMAGE_1_MINI
            ),
            None,
        )
    if recommended_id is None:
        recommended_id = next(
            (spec.id for spec, enabled in model_states if enabled),
            None,
        )

    return [
        ImageModelOption(
            id=spec.id,
            name=spec.name,
            provider=spec.provider,
            availability=spec.availability,
            enabled=enabled,
            recommended=enabled and spec.id == recommended_id,
            note=spec.note,
        )
        for spec, enabled in model_states
    ]
