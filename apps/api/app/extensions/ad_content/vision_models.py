from dataclasses import dataclass

from app.core.config import settings
from app.extensions.ad_content.schemas import VisionModel, VisionModelOption


@dataclass(frozen=True)
class VisionModelSpec:
    id: VisionModel
    name: str
    provider: str
    availability: str
    note: str
    recommended: bool = False


VISION_MODEL_CATALOG = (
    VisionModelSpec(
        id=VisionModel.OPENAI_GPT_5_4_MINI,
        name="GPT-5.4 Mini Vision",
        provider="OpenAI",
        availability="hosted",
        note="기존 OpenAI 사진 분석 모델입니다.",
        recommended=True,
    ),
    VisionModelSpec(
        id=VisionModel.QWEN_2_5_VL_7B,
        name="Qwen2.5-VL-7B-Instruct",
        provider="Hugging Face",
        availability="hosted",
        note="사진 이해, OCR, 이미지 설명과 한국어 분석에 적합합니다.",
    ),
    VisionModelSpec(
        id=VisionModel.QWEN_3_VL_2B,
        name="Qwen3-VL-2B-Instruct",
        provider="Hugging Face",
        availability="hosted",
        note="가벼운 최신 Qwen Vision 모델로 빠른 이미지 분석에 적합합니다.",
    ),
    VisionModelSpec(
        id=VisionModel.QWEN_3_VL_4B,
        name="Qwen3-VL-4B-Instruct",
        provider="Hugging Face",
        availability="hosted",
        note="속도와 이미지 이해 성능의 균형을 둔 Qwen Vision 모델입니다.",
    ),
    VisionModelSpec(
        id=VisionModel.QWEN_3_VL_8B,
        name="Qwen3-VL-8B-Instruct",
        provider="Hugging Face",
        availability="provider_unavailable",
        note="연결 코드는 준비됐지만 현재 Hugging Face 공급자 상태가 error입니다.",
    ),
    VisionModelSpec(
        id=VisionModel.INTERNVL_3_2B,
        name="InternVL3-2B",
        provider="Custom endpoint",
        availability="configuration_required",
        note="OCR·문서 이해 모델입니다. OpenAI 호환 vLLM/LM Studio 주소가 필요합니다.",
    ),
    VisionModelSpec(
        id=VisionModel.INTERNVL_3_8B,
        name="InternVL3-8B",
        provider="Custom endpoint",
        availability="configuration_required",
        note="고성능 OCR·문서 이해 모델입니다. OpenAI 호환 vLLM 주소가 필요합니다.",
    ),
)


def list_vision_model_options() -> list[VisionModelOption]:
    has_openai = bool(settings.openai_api_key)
    has_hugging_face = bool(settings.llm_api_key)
    has_internvl = bool(settings.internvl_base_url)
    return [
        VisionModelOption(
            id=spec.id,
            name=spec.name,
            provider=spec.provider,
            availability=spec.availability,
            enabled=(
                has_openai
                if spec.id == VisionModel.OPENAI_GPT_5_4_MINI
                else has_internvl
                if spec.id in {VisionModel.INTERNVL_3_2B, VisionModel.INTERNVL_3_8B}
                else has_hugging_face and spec.availability == "hosted"
            ),
            recommended=spec.recommended,
            note=spec.note,
        )
        for spec in VISION_MODEL_CATALOG
    ]


def get_vision_model_spec(model: VisionModel) -> VisionModelSpec:
    for spec in VISION_MODEL_CATALOG:
        if spec.id == model:
            return spec
    raise ValueError(f"등록되지 않은 Vision 모델입니다: {model}")
