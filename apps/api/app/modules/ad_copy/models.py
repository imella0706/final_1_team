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
        id=AdModel.OPENAI_GPT_5_5,
        name="OpenAI GPT-5.5",
        size="frontier",
        provider="openai",
        routed_model="gpt-5.5",
        availability=ModelAvailability.HOSTED,
        note="최신 플래그십 GPT 모델. 광고 기획/카피 품질 비교용 기본 추천",
        recommended=True,
    ),
    ModelSpec(
        id=AdModel.OPENAI_GPT_5_4,
        name="OpenAI GPT-5.4",
        size="frontier",
        provider="openai",
        routed_model="gpt-5.4",
        availability=ModelAvailability.HOSTED,
        note="품질은 높게 유지하면서 GPT-5.5보다 비용을 낮춘 비교 후보",
    ),
    ModelSpec(
        id=AdModel.OPENAI_GPT_5_4_MINI,
        name="OpenAI GPT-5.4 Mini",
        size="mini",
        provider="openai",
        routed_model="gpt-5.4-mini",
        availability=ModelAvailability.HOSTED,
        note="속도/비용 테스트용 GPT 모델. 실서비스 후보 비교에 적합",
    ),
    ModelSpec(
        id=AdModel.OPENAI_GPT_5_4_NANO,
        name="OpenAI GPT-5.4 Nano",
        size="nano",
        provider="openai",
        routed_model="gpt-5.4-nano",
        availability=ModelAvailability.HOSTED,
        note="가장 저렴하고 빠른 GPT 테스트 후보. 간단 문구 생성 비교용",
    ),
    ModelSpec(
        id=AdModel.QWEN_2_5_7B,
        name="Qwen 2.5 7B Instruct",
        size="7.6B",
        provider="huggingface",
        routed_model=AdModel.QWEN_2_5_7B.value,
        availability=ModelAvailability.HOSTED,
<<<<<<< HEAD
        note="한국어 광고 문구의 기본 비교 모델",
    ),
    ModelSpec(
        id=AdModel.OPENAI_GPT_4_1_MINI,
        name="OpenAI GPT 4.1 Mini",
        size="mini",
        provider="openai",
        routed_model="gpt-4.1-mini",
        availability=ModelAvailability.HOSTED,
        note="이전 세대 GPT 테스트 기준선. 새 GPT 모델과 비교할 때 사용",
=======
        note="Hugging Face Router 기반 한국어 광고 문구 비교 모델",
>>>>>>> origin/dev
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
