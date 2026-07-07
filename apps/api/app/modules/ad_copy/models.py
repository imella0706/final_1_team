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
        provider="auto",
        routed_model=AdModel.QWEN_2_5_7B.value,
        availability=ModelAvailability.HOSTED,
        note="한국어 광고 문구의 기본 비교 모델",
        recommended=True,
    ),
    ModelSpec(
        id=AdModel.LLAMA_3_1_8B,
        name="Llama 3.1 8B Instruct",
        size="8B",
        provider="auto",
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
        note="NVIDIA NIM 무료 시험용 Endpoint · 별도 NVIDIA API 키 필요",
        supports_structured_output=False,
    ),
    ModelSpec(
        id=AdModel.MISTRAL_7B_V03,
        name="Mistral 7B Instruct v0.3",
        size="7B",
        provider="featherless-ai",
        routed_model="mistral-community/Mistral-7B-Instruct-v0.3:featherless-ai",
        availability=ModelAvailability.HOSTED,
        note="Featherless AI의 채팅 호환 커뮤니티 변환본으로 라우팅 · 콜드 스타트 시 일시적 503 가능",
        supports_system_role=False,
    ),
    ModelSpec(
        id=AdModel.GEMMA_2_9B,
        name="Gemma 2 9B Instruct",
        size="9B",
        provider="featherless-ai",
        routed_model=f"{AdModel.GEMMA_2_9B.value}:featherless-ai",
        availability=ModelAvailability.GATED,
        note="Featherless AI 라우팅 · Google Gemma 사용 조건 동의 필요",
    ),
    ModelSpec(
        id=AdModel.PHI_4_MINI,
        name="Phi 4 Mini Instruct",
        size="4B",
        provider="featherless-ai",
        routed_model=f"{AdModel.PHI_4_MINI.value}:featherless-ai",
        availability=ModelAvailability.HOSTED,
        note="HF 토큰으로 Featherless AI에 명시적으로 라우팅",
    ),
    ModelSpec(
        id=AdModel.SOLAR_10_7B,
        name="SOLAR 10.7B Instruct",
        size="10.7B",
        provider="featherless-ai",
        routed_model=f"{AdModel.SOLAR_10_7B.value}:featherless-ai",
        availability=ModelAvailability.RESEARCH_ONLY,
        note="Featherless AI 라우팅 · CC BY-NC 4.0 연구·비교 전용",
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
