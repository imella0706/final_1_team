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
    "openai/gpt-5.5": TextModelConfig(
        display_name="OpenAI GPT-5.5",
        provider=TextRuntimeProvider.OPENAI,
        default_model="gpt-5.5",
        base_url_setting="openai_base_url",
        model_setting="openai_gpt_5_5_model",
        api_key_setting="openai_api_key",
    ),
    "gpt-5.5": TextModelConfig(
        display_name="OpenAI GPT-5.5",
        provider=TextRuntimeProvider.OPENAI,
        default_model="gpt-5.5",
        base_url_setting="openai_base_url",
        model_setting="openai_gpt_5_5_model",
        api_key_setting="openai_api_key",
    ),
    "openai/gpt-5.4": TextModelConfig(
        display_name="OpenAI GPT-5.4",
        provider=TextRuntimeProvider.OPENAI,
        default_model="gpt-5.4",
        base_url_setting="openai_base_url",
        model_setting="openai_gpt_5_4_model",
        api_key_setting="openai_api_key",
    ),
    "gpt-5.4": TextModelConfig(
        display_name="OpenAI GPT-5.4",
        provider=TextRuntimeProvider.OPENAI,
        default_model="gpt-5.4",
        base_url_setting="openai_base_url",
        model_setting="openai_gpt_5_4_model",
        api_key_setting="openai_api_key",
    ),
    "openai/gpt-5.4-mini": TextModelConfig(
        display_name="OpenAI GPT-5.4 Mini",
        provider=TextRuntimeProvider.OPENAI,
        default_model="gpt-5.4-mini",
        base_url_setting="openai_base_url",
        model_setting="openai_gpt_5_4_mini_model",
        api_key_setting="openai_api_key",
    ),
    "gpt-5.4-mini": TextModelConfig(
        display_name="OpenAI GPT-5.4 Mini",
        provider=TextRuntimeProvider.OPENAI,
        default_model="gpt-5.4-mini",
        base_url_setting="openai_base_url",
        model_setting="openai_gpt_5_4_mini_model",
        api_key_setting="openai_api_key",
    ),
    "openai/gpt-5.4-nano": TextModelConfig(
        display_name="OpenAI GPT-5.4 Nano",
        provider=TextRuntimeProvider.OPENAI,
        default_model="gpt-5.4-nano",
        base_url_setting="openai_base_url",
        model_setting="openai_gpt_5_4_nano_model",
        api_key_setting="openai_api_key",
    ),
    "openai/gpt-4.1-mini": TextModelConfig(
        display_name="OpenAI GPT 4.1 Mini",
        provider=TextRuntimeProvider.OPENAI,
        default_model="gpt-4.1-mini",
        base_url_setting="openai_base_url",
        model_setting="openai_gpt_4_1_mini_model",
        api_key_setting="openai_api_key",
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
    "nvidia/meta/llama-3.1-8b-instruct": TextModelConfig(
        display_name="NVIDIA · Llama 3.1 8B Instruct",
        provider=TextRuntimeProvider.NVIDIA,
        default_model="meta/llama-3.1-8b-instruct",
        base_url_setting="nvidia_base_url",
        model_setting="nvidia_llama_model",
        api_key_setting="nvidia_api_key",
    ),
    "gpt-5.5": TextModelConfig(
        display_name="GPT-5.5",
        provider=TextRuntimeProvider.OPENAI,
        default_model="gpt-5.5",
        base_url_setting="openai_base_url",
        model_setting="openai_gpt_5_5_model",
        api_key_setting="openai_api_key",
    ),
    "gpt-5.4": TextModelConfig(
        display_name="GPT-5.4",
        provider=TextRuntimeProvider.OPENAI,
        default_model="gpt-5.4",
        base_url_setting="openai_base_url",
        model_setting="openai_gpt_5_4_model",
        api_key_setting="openai_api_key",
    ),
    "gpt-5.4-mini": TextModelConfig(
        display_name="GPT-5.4 Mini",
        provider=TextRuntimeProvider.OPENAI,
        default_model="gpt-5.4-mini",
        base_url_setting="openai_base_url",
        model_setting="openai_gpt_5_4_mini_model",
        api_key_setting="openai_api_key",
    ),
    "gpt-5.4-nano": TextModelConfig(
        display_name="GPT-5.4 Nano",
        provider=TextRuntimeProvider.OPENAI,
        default_model="gpt-5.4-nano",
        base_url_setting="openai_base_url",
        model_setting="openai_gpt_5_4_nano_model",
        api_key_setting="openai_api_key",
    ),
    "gpt-4.1-mini": TextModelConfig(
        display_name="GPT-4.1 Mini",
        provider=TextRuntimeProvider.OPENAI,
        default_model="gpt-4.1-mini",
        base_url_setting="openai_base_url",
        model_setting="openai_gpt_4_1_mini_model",
        api_key_setting="openai_api_key",
    ),
}


def get_text_model_config(model: str) -> TextModelConfig:
    key = model.strip()
    if key in MODEL_MAP:
        return MODEL_MAP[key]
    for config in MODEL_MAP.values():
        routed_base = config.default_model.removesuffix(":featherless-ai")
        if key in {config.display_name, config.default_model, routed_base}:
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
    if (
        local_base_url
        and config.provider not in {TextRuntimeProvider.OPENAI, TextRuntimeProvider.NVIDIA}
        and (_setting(config.model_setting) or settings.local_llm_model)
    ):
        return local_base_url
    if config.provider in {
        TextRuntimeProvider.LM_STUDIO,
        TextRuntimeProvider.OLLAMA,
        TextRuntimeProvider.VLLM,
    } and local_base_url:
        return local_base_url
    if config.provider == TextRuntimeProvider.OPENAI:
        return settings.openai_base_url
    if config.provider == TextRuntimeProvider.NVIDIA:
        return settings.nvidia_base_url
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
    if fallback in {TextRuntimeProvider.OPENAI, TextRuntimeProvider.NVIDIA}:
        return fallback
    if "router.huggingface.co" in normalized:
        return TextRuntimeProvider.HUGGING_FACE_ROUTER
    if "api.openai.com" in normalized:
        return TextRuntimeProvider.OPENAI
    if "integrate.api.nvidia.com" in normalized:
        return TextRuntimeProvider.NVIDIA
    if "localhost:1234" in normalized or "127.0.0.1:1234" in normalized:
        return TextRuntimeProvider.LM_STUDIO
    if "localhost:11434" in normalized or "127.0.0.1:11434" in normalized:
        return TextRuntimeProvider.OLLAMA
    if "/v1" in normalized:
        return TextRuntimeProvider.VLLM
    return fallback
