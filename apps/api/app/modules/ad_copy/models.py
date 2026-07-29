from dataclasses import dataclass
from typing import Any

from app.core.config import settings
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
        id=AdModel.LOCAL_QWEN_2_5_1_5B,
        name="Qwen2.5 1.5B · Local",
        size="1.5B Q4",
        provider="ollama",
        routed_model="qwen2.5:1.5b",
        availability=ModelAvailability.LOCAL_ONLY,
        note="경량 로컬 기준 모델. Ollama와 RTX 3060에서 실행합니다.",
        supports_structured_output=True,
    ),
    ModelSpec(
        id=AdModel.LOCAL_QWEN_2_5_7B,
        name="Qwen2.5 7B · Local",
        size="7B Q4",
        provider="ollama",
        routed_model="qwen2.5:7b",
        availability=ModelAvailability.LOCAL_ONLY,
        note="한국어 광고 문구 품질 비교용 로컬 7B 모델입니다.",
        supports_structured_output=True,
    ),
    ModelSpec(
        id=AdModel.LOCAL_MISTRAL_7B,
        name="Mistral 7B v0.3 · Local",
        size="7B Q4",
        provider="ollama",
        routed_model="mistral:7b",
        availability=ModelAvailability.LOCAL_ONLY,
        note="Qwen과 비교할 범용 로컬 7B 모델입니다.",
        supports_structured_output=True,
    ),
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
        id=AdModel.OPENAI_GPT_5_4_NANO,
        name="OpenAI GPT-5.4 Nano",
        size="nano",
        provider="openai",
        routed_model=AdModel.GPT_5_4_NANO.value,
        availability=ModelAvailability.HOSTED,
        note="가장 저렴하고 빠른 GPT 테스트 후보. 간단 문구 생성 비교용",
    ),
    ModelSpec(
        id=AdModel.OPENAI_GPT_5_4_MINI,
        name="OpenAI GPT-5.4 Mini",
        size="mini",
        provider="openai",
        routed_model=AdModel.GPT_5_4_MINI.value,
        availability=ModelAvailability.HOSTED,
        note="속도/비용 테스트용 GPT 모델. 실서비스 후보 비교에 적합",
    ),
    ModelSpec(
        id=AdModel.OPENAI_GPT_5_4,
        name="OpenAI GPT-5.4",
        size="frontier",
        provider="openai",
        routed_model=AdModel.GPT_5_4.value,
        availability=ModelAvailability.HOSTED,
        note="품질은 높게 유지하면서 GPT-5.5보다 비용을 낮춘 비교 후보",
    ),
)

LOCAL_MODEL_IDS = frozenset(
    {
        AdModel.LOCAL_QWEN_2_5_1_5B,
        AdModel.LOCAL_QWEN_2_5_7B,
        AdModel.LOCAL_MISTRAL_7B,
    }
)
OPENAI_MODEL_IDS = frozenset(
    {
        AdModel.OPENAI_GPT_5_4_NANO,
        AdModel.OPENAI_GPT_5_4_MINI,
        AdModel.OPENAI_GPT_5_4,
    }
)
HUGGING_FACE_MODEL_KEY_SETTINGS = {
    AdModel.QWEN_2_5_7B: "qwen_api_key",
    AdModel.LLAMA_3_1_8B: "llama_api_key",
}
MODEL_RECOMMENDATION_PRIORITY = (
    AdModel.OPENAI_GPT_5_4_MINI,
    AdModel.OPENAI_GPT_5_4_NANO,
    AdModel.OPENAI_GPT_5_4,
    AdModel.QWEN_2_5_7B,
    AdModel.LLAMA_3_1_8B,
    AdModel.NVIDIA_LLAMA_3_1_8B,
    AdModel.LOCAL_QWEN_2_5_7B,
    AdModel.LOCAL_QWEN_2_5_1_5B,
    AdModel.LOCAL_MISTRAL_7B,
)


def _has_secret(value: Any) -> bool:
    if value is None:
        return False
    if hasattr(value, "get_secret_value"):
        value = value.get_secret_value()
    return bool(str(value).strip())


def _model_is_enabled(spec: ModelSpec) -> bool:
    if spec.id in LOCAL_MODEL_IDS:
        return bool(settings.local_llm_base_url)
    if spec.id in OPENAI_MODEL_IDS:
        return bool(settings.openai_base_url) and _has_secret(settings.openai_api_key)
    if spec.id in HUGGING_FACE_MODEL_KEY_SETTINGS:
        provider_key = getattr(
            settings,
            HUGGING_FACE_MODEL_KEY_SETTINGS[spec.id],
            None,
        )
        return bool(settings.llm_base_url) and (
            _has_secret(provider_key) or _has_secret(settings.llm_api_key)
        )
    if spec.id == AdModel.NVIDIA_LLAMA_3_1_8B:
        return bool(settings.nvidia_base_url) and _has_secret(settings.nvidia_api_key)
    return False


def list_model_options() -> list[ModelOption]:
    enabled_by_id = {spec.id: _model_is_enabled(spec) for spec in MODEL_CATALOG}
    recommended_id = next(
        (
            model_id
            for model_id in MODEL_RECOMMENDATION_PRIORITY
            if enabled_by_id.get(model_id, False)
        ),
        None,
    )
    return [
        ModelOption(
            id=spec.id,
            name=spec.name,
            size=spec.size,
            provider=spec.provider,
            availability=spec.availability,
            note=spec.note,
            enabled=enabled_by_id[spec.id],
            recommended=spec.id == recommended_id,
        )
        for spec in MODEL_CATALOG
    ]


def get_model_spec(model: AdModel) -> ModelSpec:
    for spec in MODEL_CATALOG:
        if spec.id == model:
            return spec
    routed_value = model.value.removeprefix("openai/")
    for spec in MODEL_CATALOG:
        if spec.routed_model == routed_value:
            return spec
    raise ValueError(f"등록되지 않은 광고 문구 모델입니다: {model}")
