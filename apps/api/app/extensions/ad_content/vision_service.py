from dataclasses import dataclass
from typing import Any

import httpx

from app.core.config import settings
from app.extensions.ad_content.schemas import VisionModel
from app.extensions.ad_content.vision_models import get_vision_model_spec


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


def _secret_value(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "get_secret_value"):
        return value.get_secret_value() or None
    return str(value) or None


def resolve_vision_model(model: VisionModel) -> ResolvedVisionModel:
    spec = get_vision_model_spec(model)
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

    payload: dict[str, object] = {
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

    endpoint = f"{resolved.base_url.rstrip('/')}/chat/completions"
    try:
        async with httpx.AsyncClient(timeout=settings.llm_timeout_seconds) as client:
            response = await client.post(endpoint, headers=headers, json=payload)
            response.raise_for_status()
            body = response.json()
            result = body["choices"][0]["message"]["content"]
    except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as error:
        raise VisionModelProviderError(
            f"{model.value} Vision request failed: {type(error).__name__}: {error}"
        ) from error

    if not isinstance(result, str):
        raise VisionModelProviderError(
            f"{model.value} Vision response did not contain text content."
        )
    return result, resolved
