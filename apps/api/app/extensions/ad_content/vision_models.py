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


LOCAL_OLLAMA_VISION_MODELS = {
    VisionModel.LOCAL_QWEN_2_5_VL_7B,
    VisionModel.LOCAL_QWEN_3_VL_2B,
    VisionModel.LOCAL_QWEN_3_VL_4B,
    VisionModel.LOCAL_QWEN_3_VL_8B,
}

INTERNVL_MODELS = {
    VisionModel.INTERNVL_3_2B,
    VisionModel.INTERNVL_3_8B,
}


VISION_MODEL_CATALOG = (
    VisionModelSpec(
        id=VisionModel.LOCAL_QWEN_3_VL_4B,
        name="Qwen3-VL 4B (Local)",
        provider="Local / Ollama",
        availability="local",
        note="이미지 이해와 속도의 균형이 좋은 로컬 Vision 모델입니다.",
        recommended=True,
    ),
    VisionModelSpec(
        id=VisionModel.LOCAL_QWEN_2_5_VL_7B,
        name="Qwen2.5-VL 7B (Local)",
        provider="Local / Ollama",
        availability="local",
        note="사진 이해, OCR, 한국어 이미지 설명에 적합한 로컬 모델입니다.",
    ),
    VisionModelSpec(
        id=VisionModel.LOCAL_QWEN_3_VL_2B,
        name="Qwen3-VL 2B (Local)",
        provider="Local / Ollama",
        availability="local",
        note="가볍고 빠른 로컬 Vision 비교 모델입니다.",
    ),
    VisionModelSpec(
        id=VisionModel.LOCAL_QWEN_3_VL_8B,
        name="Qwen3-VL 8B (Local)",
        provider="Local / Ollama",
        availability="local",
        note="더 높은 이미지 추론 성능을 비교하기 위한 로컬 모델입니다. 8GB GPU에서는 느릴 수 있습니다.",
    ),
    VisionModelSpec(
        id=VisionModel.OPENAI_GPT_5_4_MINI,
        name="GPT-5.4 Mini Vision",
        provider="GPT / OpenAI",
        availability="hosted",
        note="OpenAI API를 사용하는 사진 분석 모델입니다.",
    ),
    VisionModelSpec(
        id=VisionModel.QWEN_2_5_VL_7B,
        name="Qwen2.5-VL-7B-Instruct",
        provider="Hugging Face",
        availability="hosted",
        note="Hugging Face Router를 사용하는 Qwen Vision 모델입니다.",
    ),
    VisionModelSpec(
        id=VisionModel.QWEN_3_VL_2B,
        name="Qwen3-VL-2B-Instruct",
        provider="Hugging Face",
        availability="hosted",
        note="Hugging Face Router를 사용하는 경량 Qwen Vision 모델입니다.",
    ),
    VisionModelSpec(
        id=VisionModel.QWEN_3_VL_4B,
        name="Qwen3-VL-4B-Instruct",
        provider="Hugging Face",
        availability="hosted",
        note="Hugging Face Router를 사용하는 Qwen Vision 모델입니다.",
    ),
    VisionModelSpec(
        id=VisionModel.QWEN_3_VL_8B,
        name="Qwen3-VL-8B-Instruct",
        provider="Hugging Face",
        availability="provider_unavailable",
        note="연결 코드는 준비되어 있지만 현재 Hugging Face 공급자 상태에서는 사용할 수 없습니다.",
    ),
    VisionModelSpec(
        id=VisionModel.INTERNVL_3_2B,
        name="InternVL3-2B (Local server)",
        provider="Local / LMDeploy",
        availability="configuration_required",
        note="공식 LMDeploy OpenAI 호환 서버 주소를 설정하면 이미지와 함께 요청합니다.",
    ),
    VisionModelSpec(
        id=VisionModel.INTERNVL_3_8B,
        name="InternVL3-8B (Local server)",
        provider="Local / LMDeploy",
        availability="configuration_required",
        note="공식 LMDeploy OpenAI 호환 서버 주소가 필요하며 8GB GPU 단독 실행은 권장하지 않습니다.",
    ),
)


def list_vision_model_options() -> list[VisionModelOption]:
    has_openai = bool(settings.openai_api_key)
    has_hugging_face = bool(settings.llm_api_key)
    has_local_ollama = bool(settings.local_llm_base_url)
    has_internvl = bool(settings.internvl_base_url)
    return [
        VisionModelOption(
            id=spec.id,
            name=spec.name,
            provider=spec.provider,
            availability=spec.availability,
            enabled=(
                has_local_ollama
                if spec.id in LOCAL_OLLAMA_VISION_MODELS
                else has_openai
                if spec.id == VisionModel.OPENAI_GPT_5_4_MINI
                else has_internvl
                if spec.id in INTERNVL_MODELS
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
