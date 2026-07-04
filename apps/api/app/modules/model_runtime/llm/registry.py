from dataclasses import dataclass
from typing import Any

from app.core.config import settings
from app.modules.model_runtime.schemas import TextRuntimeProvider


@dataclass(frozen=True)
class TextModelConfig:
    display_name: str
    provider: TextRuntimeProvider
    default_model: str
    base_url_setting: str
    model_setting: str
    api_key_setting: str


MODEL_MAP: dict[str, TextModelConfig] = {
    "mistral-7b-instruct-v0.3": TextModelConfig(
        display_name="Mistral 7B Instruct v0.3",
        provider=TextRuntimeProvider.LM_STUDIO,
        default_model="mistralai/Mistral-7B-Instruct-v0.3",
        base_url_setting="mistral_base_url",
        model_setting="mistral_model",
        api_key_setting="mistral_api_key",
    ),
    "gemma-2-9b-instruct": TextModelConfig(
        display_name="Gemma 2 9B Instruct",
        provider=TextRuntimeProvider.LM_STUDIO,
        default_model="google/gemma-2-9b-it",
        base_url_setting="gemma_base_url",
        model_setting="gemma_model",
        api_key_setting="gemma_api_key",
    ),
    "phi-4-mini-instruct": TextModelConfig(
        display_name="Phi 4 Mini Instruct",
        provider=TextRuntimeProvider.LM_STUDIO,
        default_model="microsoft/Phi-4-mini-instruct",
        base_url_setting="phi_base_url",
        model_setting="phi_model",
        api_key_setting="phi_api_key",
    ),
    "solar-10.7b-instruct": TextModelConfig(
        display_name="SOLAR 10.7B Instruct",
        provider=TextRuntimeProvider.LM_STUDIO,
        default_model="upstage/SOLAR-10.7B-Instruct-v1.0",
        base_url_setting="solar_base_url",
        model_setting="solar_model",
        api_key_setting="solar_api_key",
    ),
    "qwen-2.5-7b-instruct": TextModelConfig(
        display_name="Qwen 2.5 7B Instruct",
        provider=TextRuntimeProvider.HUGGING_FACE_ROUTER,
        default_model="Qwen/Qwen2.5-7B-Instruct",
        base_url_setting="qwen_base_url",
        model_setting="qwen_model",
        api_key_setting="qwen_api_key",
    ),
    "llama-3.1-8b-instruct": TextModelConfig(
        display_name="Llama 3.1 8B Instruct",
        provider=TextRuntimeProvider.HUGGING_FACE_ROUTER,
        default_model="meta-llama/Llama-3.1-8B-Instruct",
        base_url_setting="llama_base_url",
        model_setting="llama_model",
        api_key_setting="llama_api_key",
    ),
}


def get_text_model_config(model: str) -> TextModelConfig:
    key = model.strip()
    if key in MODEL_MAP:
        return MODEL_MAP[key]
    for config in MODEL_MAP.values():
        if key in {config.display_name, config.default_model}:
            return config
    raise KeyError(f"Unknown text model: {model}")


def _setting(name: str) -> Any:
    return getattr(settings, name, None)


def _secret_value(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "get_secret_value"):
        return value.get_secret_value() or None
    return str(value) or None


def resolve_base_url(config: TextModelConfig) -> str:
    model_base_url = _setting(config.base_url_setting)
    if model_base_url:
        return model_base_url
    local_base_url = settings.local_llm_base_url
    if config.provider in {
        TextRuntimeProvider.LM_STUDIO,
        TextRuntimeProvider.OLLAMA,
        TextRuntimeProvider.VLLM,
    } and local_base_url:
        return local_base_url
    return settings.llm_base_url


def resolve_model_name(config: TextModelConfig) -> str:
    return (
        _setting(config.model_setting)
        or settings.local_llm_model
        or config.default_model
    )


def resolve_api_key(config: TextModelConfig) -> str | None:
    return (
        _secret_value(_setting(config.api_key_setting))
        or _secret_value(settings.local_llm_api_key)
        or (settings.llm_api_key.get_secret_value() if settings.llm_api_key else None)
    )


def infer_provider(base_url: str, fallback: TextRuntimeProvider) -> TextRuntimeProvider:
    normalized = base_url.lower()
    if "router.huggingface.co" in normalized:
        return TextRuntimeProvider.HUGGING_FACE_ROUTER
    if "localhost:1234" in normalized or "127.0.0.1:1234" in normalized:
        return TextRuntimeProvider.LM_STUDIO
    if "localhost:11434" in normalized or "127.0.0.1:11434" in normalized:
        return TextRuntimeProvider.OLLAMA
    if "/v1" in normalized:
        return TextRuntimeProvider.VLLM
    return fallback
