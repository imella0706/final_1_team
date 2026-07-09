from dataclasses import dataclass

from app.modules.ad_copy.schemas import AdModel, ModelAvailability, ModelOption


@dataclass(frozen=True)
class ModelSpec:
    id: AdModel
    name: str
    size: str
    provider: str
    routed_model: str
    availability: ModelAvailability
    note: str
    recommended: bool = False
    supports_system_role: bool = True
    supports_structured_output: bool = True


MODEL_CATALOG = (
    ModelSpec(
        id=AdModel.QWEN_2_5_7B,
        name="Qwen 2.5 7B Instruct",
        size="7.6B",
        provider="huggingface",
        routed_model=AdModel.QWEN_2_5_7B.value,
        availability=ModelAvailability.HOSTED,
        note="Hugging Face Router 기반 한국어 광고 문구 비교 모델",
    ),
    ModelSpec(
        id=AdModel.LLAMA_3_1_8B,
        name="Llama 3.1 8B Instruct",
        size="8B",
        provider="huggingface",
        routed_model=AdModel.LLAMA_3_1_8B.value,
        availability=ModelAvailability.GATED,
        note="Hugging Face에서 Meta 라이선스와 접근 권한 동의 필요",
    ),
    ModelSpec(
        id=AdModel.NVIDIA_LLAMA_3_1_8B,
        name="NVIDIA · Llama 3.1 8B Instruct",
        size="8B",
        provider="nvidia",
        routed_model="meta/llama-3.1-8b-instruct",
        availability=ModelAvailability.HOSTED,
        note="NVIDIA NIM 무료 시험용 Endpoint · NVIDIA API 키 필요",
        supports_structured_output=False,
    ),
    ModelSpec(
        id=AdModel.GPT_4_1_MINI,
        name="GPT-4.1 Mini",
        size="OpenAI",
        provider="openai",
        routed_model=AdModel.GPT_4_1_MINI.value,
        availability=ModelAvailability.HOSTED,
        note="비용 효율적인 OpenAI 광고 문구 생성 기본 모델",
        recommended=True,
    ),
    ModelSpec(
        id=AdModel.GPT_5_4_NANO,
        name="GPT-5.4 Nano",
        size="OpenAI",
        provider="openai",
        routed_model=AdModel.GPT_5_4_NANO.value,
        availability=ModelAvailability.HOSTED,
        note="가벼운 OpenAI 문구 생성 모델",
    ),
    ModelSpec(
        id=AdModel.GPT_5_4_MINI,
        name="GPT-5.4 Mini",
        size="OpenAI",
        provider="openai",
        routed_model=AdModel.GPT_5_4_MINI.value,
        availability=ModelAvailability.HOSTED,
        note="품질과 비용을 균형 있게 쓰는 OpenAI 모델",
    ),
    ModelSpec(
        id=AdModel.GPT_5_4,
        name="GPT-5.4",
        size="OpenAI",
        provider="openai",
        routed_model=AdModel.GPT_5_4.value,
        availability=ModelAvailability.HOSTED,
        note="고품질 OpenAI 문구 생성 모델",
    ),
    ModelSpec(
        id=AdModel.GPT_5_5,
        name="GPT-5.5",
        size="OpenAI",
        provider="openai",
        routed_model=AdModel.GPT_5_5.value,
        availability=ModelAvailability.HOSTED,
        note="최상위 OpenAI 문구 생성 모델",
    ),
)


def list_model_options() -> list[ModelOption]:
    return [
        ModelOption(
            id=spec.id,
            name=spec.name,
            size=spec.size,
            provider=spec.provider,
            availability=spec.availability,
            note=spec.note,
            recommended=spec.recommended,
        )
        for spec in MODEL_CATALOG
    ]


def get_model_spec(model: AdModel) -> ModelSpec:
    for spec in MODEL_CATALOG:
        if spec.id == model:
            return spec
    raise ValueError(f"등록되지 않은 광고 문구 모델입니다: {model}")
