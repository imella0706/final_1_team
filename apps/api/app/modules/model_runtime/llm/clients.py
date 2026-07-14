import json
from typing import Any

import httpx

from app.core.config import settings
from app.modules.model_runtime.llm.registry import TextModelConfig
from app.modules.model_runtime.schemas import TextRuntimeProvider


class LlmRuntimeError(RuntimeError):
    """Raised when a text model runtime cannot complete a request."""


class OpenAICompatibleClient:
    provider: TextRuntimeProvider

    def __init__(self, provider: TextRuntimeProvider) -> None:
        self.provider = provider

    async def generate(
        self,
        *,
        config: TextModelConfig,
        base_url: str,
        model_name: str,
        api_key: str | None,
        messages: list[dict[str, str]],
        temperature: float,
        max_tokens: int,
    ) -> str:
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        payload: dict[str, Any] = {
            "model": model_name,
            "messages": messages,
            "temperature": temperature,
        }
<<<<<<< HEAD
        token_limit_name = (
            "max_completion_tokens"
            if self.provider == TextRuntimeProvider.OPENAI
            else "max_tokens"
        )
        payload[token_limit_name] = max_tokens
=======
        token_limit_key = (
            "max_completion_tokens"
            if self.provider == TextRuntimeProvider.OPENAI
            and model_name.startswith("gpt-5")
            else "max_tokens"
        )
        payload[token_limit_key] = max_tokens
>>>>>>> origin/dev
        endpoint = f"{base_url.rstrip('/')}/chat/completions"

        try:
            async with httpx.AsyncClient(timeout=settings.llm_timeout_seconds) as client:
                response = await client.post(endpoint, headers=headers, json=payload)
                response.raise_for_status()
        except httpx.HTTPStatusError as error:
            detail = error.response.text[:500]
            raise LlmRuntimeError(
                f"{config.display_name} provider call failed: {detail}"
            ) from error
        except httpx.HTTPError as error:
            raise LlmRuntimeError(
                f"Could not connect to {config.display_name} at {base_url}: "
                f"{type(error).__name__}"
            ) from error

        try:
            body = response.json()
            return body["choices"][0]["message"]["content"]
        except (json.JSONDecodeError, KeyError, IndexError, TypeError) as error:
            raise LlmRuntimeError(
                f"{config.display_name} returned an unsupported response format."
            ) from error


class LMStudioClient(OpenAICompatibleClient):
    def __init__(self) -> None:
        super().__init__(TextRuntimeProvider.LM_STUDIO)


class OllamaClient(OpenAICompatibleClient):
    def __init__(self) -> None:
        super().__init__(TextRuntimeProvider.OLLAMA)


class VllmClient(OpenAICompatibleClient):
    def __init__(self) -> None:
        super().__init__(TextRuntimeProvider.VLLM)


class HuggingFaceRouterClient(OpenAICompatibleClient):
    def __init__(self) -> None:
        super().__init__(TextRuntimeProvider.HUGGING_FACE_ROUTER)


class OpenAIClient(OpenAICompatibleClient):
    def __init__(self) -> None:
        super().__init__(TextRuntimeProvider.OPENAI)


class NvidiaClient(OpenAICompatibleClient):
    def __init__(self) -> None:
        super().__init__(TextRuntimeProvider.NVIDIA)
