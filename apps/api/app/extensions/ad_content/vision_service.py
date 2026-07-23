from dataclasses import dataclass
from typing import Any

import httpx

from app.core.config import settings
from app.extensions.ad_content.schemas import VisionModel
from app.extensions.ad_content.vision_models import (
    LOCAL_OLLAMA_VISION_MODELS,
    get_vision_model_spec,
)


class VisionModelNotConfiguredError(RuntimeError):
    """Raised when a selected Vision model has no usable endpoint or credential."""


class VisionModelProviderError(RuntimeError):
    """Raised when a Vision provider rejects or fails a request."""


@dataclass(frozen=True)
class ResolvedVisionModel:
    id: VisionModel
    routed_model: str
    provider: str
    base_url: str
    api_key: str | None


LOCAL_OLLAMA_MODEL_SETTINGS = {
    VisionModel.LOCAL_QWEN_2_5_VL_7B: "local_qwen_2_5_vl_7b_model",
    VisionModel.LOCAL_QWEN_3_VL_2B: "local_qwen_3_vl_2b_model",
    VisionModel.LOCAL_QWEN_3_VL_4B: "local_qwen_3_vl_4b_model",
    VisionModel.LOCAL_QWEN_3_VL_8B: "local_qwen_3_vl_8b_model",
}


def _secret_value(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "get_secret_value"):
        return value.get_secret_value() or None
    return str(value) or None


def resolve_vision_model(model: VisionModel) -> ResolvedVisionModel:
    spec = get_vision_model_spec(model)
    if model in LOCAL_OLLAMA_VISION_MODELS:
        if not settings.local_llm_base_url:
            raise VisionModelNotConfiguredError(
                f"{model.value} requires BRANDMATE_LOCAL_LLM_BASE_URL."
            )
        model_setting = LOCAL_OLLAMA_MODEL_SETTINGS[model]
        return ResolvedVisionModel(
            id=model,
            routed_model=getattr(settings, model_setting),
            provider=spec.provider,
            base_url=settings.local_llm_base_url,
            api_key=_secret_value(settings.local_llm_api_key),
        )

    if model == VisionModel.OPENAI_GPT_5_4_MINI:
        api_key = _secret_value(settings.openai_api_key)
        if not api_key:
            raise VisionModelNotConfiguredError(
                "BRANDMATE_OPENAI_API_KEY is required for GPT Vision."
            )
        return ResolvedVisionModel(
            id=model,
            routed_model=settings.image_validator_model_name
            or settings.openai_vision_model
            or "gpt-5.4-mini",
            provider=spec.provider,
            base_url=settings.openai_base_url,
            api_key=api_key,
        )

    if model in {VisionModel.INTERNVL_3_2B, VisionModel.INTERNVL_3_8B}:
        if not settings.internvl_base_url:
            raise VisionModelNotConfiguredError(
                f"{model.value} requires BRANDMATE_INTERNVL_BASE_URL."
            )
        return ResolvedVisionModel(
            id=model,
            routed_model=model.value,
            provider=spec.provider,
            base_url=settings.internvl_base_url,
            api_key=_secret_value(settings.internvl_api_key),
        )

    api_key = _secret_value(settings.llm_api_key)
    if not api_key:
        raise VisionModelNotConfiguredError(
            f"BRANDMATE_LLM_API_KEY is required for {model.value}."
        )
    return ResolvedVisionModel(
        id=model,
        routed_model=model.value,
        provider=spec.provider,
        base_url=settings.llm_base_url,
        api_key=api_key,
    )


def _ollama_endpoint(base_url: str) -> str:
    normalized = base_url.rstrip("/")
    if normalized.endswith("/v1"):
        normalized = normalized[:-3]
    return f"{normalized}/api/chat"


def _ollama_message(content: list[dict[str, object]]) -> dict[str, object]:
    text_parts: list[str] = []
    images: list[str] = []
    for part in content:
        if part.get("type") == "text" and isinstance(part.get("text"), str):
            text_parts.append(str(part["text"]))
            continue
        if part.get("type") != "image_url":
            continue
        image_url = part.get("image_url")
        if not isinstance(image_url, dict) or not isinstance(image_url.get("url"), str):
            continue
        url = str(image_url["url"])
        if not url.startswith("data:") or ";base64," not in url:
            raise ValueError("Ollama Vision requires a base64 data URL image.")
        images.append(url.split(";base64,", 1)[1])

    message: dict[str, object] = {
        "role": "user",
        "content": "\n\n".join(text_parts),
    }
    if images:
        message["images"] = images
    return message


async def request_vision_completion(
    model: VisionModel,
    content: list[dict[str, object]],
    *,
    max_tokens: int,
    json_mode: bool = False,
) -> tuple[str, ResolvedVisionModel]:
    resolved = resolve_vision_model(model)
    headers = {"Content-Type": "application/json"}
    if resolved.api_key:
        headers["Authorization"] = f"Bearer {resolved.api_key}"

    try:
        if model in LOCAL_OLLAMA_VISION_MODELS:
            payload: dict[str, object] = {
                "model": resolved.routed_model,
                "messages": [_ollama_message(content)],
                "stream": False,
                "think": False,
                "keep_alive": 0,
                "options": {"temperature": 0, "num_predict": max_tokens},
            }
            if json_mode:
                payload["format"] = "json"
            endpoint = _ollama_endpoint(resolved.base_url)
        else:
            payload = {
                "model": resolved.routed_model,
                "messages": [{"role": "user", "content": content}],
                "temperature": 0,
            }
            if model == VisionModel.OPENAI_GPT_5_4_MINI:
                payload["max_completion_tokens"] = max_tokens
                if json_mode:
                    payload["response_format"] = {"type": "json_object"}
            else:
                payload["max_tokens"] = max_tokens
                if json_mode:
                    payload["response_format"] = {"type": "json_object"}
            endpoint = f"{resolved.base_url.rstrip('/')}/chat/completions"

        async with httpx.AsyncClient(timeout=settings.llm_timeout_seconds) as client:
            response = await client.post(endpoint, headers=headers, json=payload)
            if (
                response.status_code in {400, 422}
                and model not in LOCAL_OLLAMA_VISION_MODELS
                and model != VisionModel.OPENAI_GPT_5_4_MINI
                and "response_format" in payload
            ):
                payload.pop("response_format", None)
                response = await client.post(endpoint, headers=headers, json=payload)
            response.raise_for_status()
            body = response.json()
            result = (
                body["message"]["content"]
                if model in LOCAL_OLLAMA_VISION_MODELS
                else body["choices"][0]["message"]["content"]
            )
    except httpx.HTTPStatusError as error:
        detail = error.response.text.strip()
        raise VisionModelProviderError(
            f"{model.value} Vision request failed: HTTP {error.response.status_code}: "
            f"{detail}"
        ) from error
    except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as error:
        raise VisionModelProviderError(
            f"{model.value} Vision request failed: {type(error).__name__}: {error}"
        ) from error

    if not isinstance(result, str):
        raise VisionModelProviderError(
            f"{model.value} Vision response did not contain text content."
        )
    return result, resolved
