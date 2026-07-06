from dataclasses import dataclass

from app.modules.ad_copy.schemas import AdModel, ModelAvailability, ModelOption


@dataclass(frozen=True)
class ModelSpec:
    id: AdModel
    name: str
    size: str
    availability: ModelAvailability
    note: str
    recommended: bool = False


MODEL_CATALOG = (
    ModelSpec(
        id=AdModel.QWEN_2_5_7B,
        name="Qwen 2.5 7B Instruct",
        size="7.6B",
        availability=ModelAvailability.HOSTED,
        note="한국어 광고 문구의 기본 비교 모델",
        recommended=True,
    ),
    ModelSpec(
        id=AdModel.LLAMA_3_1_8B,
        name="Llama 3.1 8B Instruct",
        size="8B",
        availability=ModelAvailability.GATED,
        note="Hugging Face에서 Meta 라이선스와 접근 권한 동의 필요",
    ),
    ModelSpec(
        id=AdModel.MISTRAL_7B_V03,
        name="Mistral 7B Instruct v0.3",
        size="7B",
        availability=ModelAvailability.LOCAL_ONLY,
        note="현재 HF 호스팅 Provider가 없어 로컬 vLLM 등의 엔드포인트 필요",
    ),
    ModelSpec(
        id=AdModel.GEMMA_2_9B,
        name="Gemma 2 9B Instruct",
        size="9B",
        availability=ModelAvailability.LOCAL_ONLY,
        note="현재 기본 HF Router 미지원 · Gemma 사용 조건 동의 후 별도 서버 필요",
    ),
    ModelSpec(
        id=AdModel.PHI_4_MINI,
        name="Phi 4 Mini Instruct",
        size="4B",
        availability=ModelAvailability.LOCAL_ONLY,
        note="현재 기본 HF Router 미지원 · 로컬 또는 별도 Endpoint 필요",
    ),
    ModelSpec(
        id=AdModel.SOLAR_10_7B,
        name="SOLAR 10.7B Instruct",
        size="10.7B",
        availability=ModelAvailability.RESEARCH_ONLY,
        note="현재 기본 HF Router 미지원 · CC BY-NC 4.0 연구·비교 전용",
    ),
)


def list_model_options() -> list[ModelOption]:
    return [
        ModelOption(
            id=spec.id,
            name=spec.name,
            size=spec.size,
            availability=spec.availability,
            note=spec.note,
            recommended=spec.recommended,
        )
        for spec in MODEL_CATALOG
    ]
