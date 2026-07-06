import json
from time import perf_counter
from typing import Any

import httpx
from pydantic import ValidationError

from app.core.config import settings
from app.modules.ad_copy.models import get_model_spec
from app.modules.ad_copy.prompt import PROMPT_VERSION, build_prompt
from app.modules.ad_copy.schemas import AdCopyContent, AdCopyRequest, AdCopyResponse


class ModelNotConfiguredError(RuntimeError):
    """Raised when an LLM endpoint or API key has not been configured."""


class ModelProviderError(RuntimeError):
    """Raised when the configured model provider rejects or fails a request."""


class InvalidModelOutputError(RuntimeError):
    """Raised when a model response does not satisfy the advertising-copy schema."""


def _request_payload(
    request: AdCopyRequest,
    *,
    structured: bool,
    invalid_content: str | None = None,
) -> dict[str, Any]:
    model_spec = get_model_spec(request.model)
    system_prompt = (
        "당신은 한국 소상공인을 위한 광고 카피라이터입니다. "
        "입력에 없는 사실을 만들지 말고 JSON 객체만 출력하세요."
    )
    user_prompt = build_prompt(request)
    if invalid_content is not None:
        user_prompt += f"""

[형식 수정 요청]
직전 응답은 필수 키가 빠졌거나 JSON 형식이 잘못되었습니다.
아래 직전 응답의 내용을 보존하면서 반드시 모든 필수 키를 채운 JSON 객체로 다시 작성하세요.
필수 키: headlines, body_copies, ctas, hashtags, image_prompt, safety_notes
각 목록 필드는 JSON 배열이어야 하며, safety_notes가 없으면 빈 배열([])을 사용하세요.
설명이나 마크다운 코드 블록을 덧붙이지 마세요.

직전 응답:
{invalid_content[:6000]}
"""
    messages = (
        [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        if model_spec.supports_system_role
        else [{"role": "user", "content": f"{system_prompt}\n\n{user_prompt}"}]
    )
    payload: dict[str, Any] = {
        "model": model_spec.routed_model,
        "messages": messages,
        "temperature": 0.2 if invalid_content is not None else 0.75,
        "max_tokens": 1200,
    }
    if structured:
        payload["response_format"] = {
            "type": "json_schema",
            "json_schema": {
                "name": "AdCopyContent",
                "schema": AdCopyContent.model_json_schema(),
                "strict": True,
            },
        }
    return payload


def _extract_content(response: httpx.Response) -> str:
    try:
        body = response.json()
        return body["choices"][0]["message"]["content"]
    except (json.JSONDecodeError, KeyError, IndexError, TypeError) as error:
        raise InvalidModelOutputError("모델 응답에서 문구 내용을 찾을 수 없습니다.") from error


def _parse_content(content: str) -> AdCopyContent:
    cleaned = content.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.removeprefix("```json").removeprefix("```")
        cleaned = cleaned.removesuffix("```").strip()

    try:
        data, _ = json.JSONDecoder().raw_decode(cleaned)
        for field in ("headlines", "body_copies", "ctas", "hashtags", "safety_notes"):
            if isinstance(data.get(field), str):
                data[field] = [data[field]]
        return AdCopyContent.model_validate(data)
    except (json.JSONDecodeError, ValidationError, AttributeError) as error:
        raise InvalidModelOutputError(
            "모델이 약속된 JSON 형식을 지키지 않았습니다. 같은 입력으로 다시 시도해주세요."
        ) from error


async def _call_model(
    request: AdCopyRequest,
    *,
    invalid_content: str | None = None,
) -> str:
    model_spec = get_model_spec(request.model)
    if model_spec.provider == "nvidia":
        base_url = settings.nvidia_base_url
        api_key = settings.nvidia_api_key
        api_key_name = "BRANDMATE_NVIDIA_API_KEY"
    else:
        base_url = settings.llm_base_url
        api_key = settings.llm_api_key
        api_key_name = "BRANDMATE_LLM_API_KEY"

    if api_key is None or not api_key.get_secret_value().strip():
        raise ModelNotConfiguredError(
            f"{api_key_name}가 없습니다. API 서버의 .env를 설정해주세요."
        )

    endpoint = f"{base_url.rstrip('/')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key.get_secret_value()}",
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=settings.llm_timeout_seconds) as client:
            response = await client.post(
                endpoint,
                headers=headers,
                json=_request_payload(
                    request,
                    structured=model_spec.supports_structured_output,
                    invalid_content=invalid_content,
                ),
            )

            if model_spec.supports_structured_output and response.status_code in {
                400,
                422,
            }:
                response = await client.post(
                    endpoint,
                    headers=headers,
                    json=_request_payload(
                        request,
                        structured=False,
                        invalid_content=invalid_content,
                    ),
                )

            response.raise_for_status()
    except httpx.HTTPStatusError as error:
        detail = error.response.text[:500]
        raise ModelProviderError(
            f"{request.model.value} 호출이 거절되었습니다: {detail}"
        ) from error
    except httpx.HTTPError as error:
        raise ModelProviderError(
            f"모델 서버에 연결할 수 없습니다: {type(error).__name__}"
        ) from error

    return _extract_content(response)


def _add_prohibited_term_warnings(
    content: AdCopyContent,
    prohibited_terms: list[str],
) -> AdCopyContent:
    generated_text = " ".join(
        content.headlines + content.body_copies + content.ctas + content.hashtags
    )
    found_terms = [term for term in prohibited_terms if term in generated_text]
    if not found_terms:
        return content

    return content.model_copy(
        update={
            "safety_notes": [
                *content.safety_notes,
                f"생성 결과에 기피 표현이 포함되었습니다: {', '.join(found_terms)}",
            ]
        }
    )


async def generate_ad_copy(request: AdCopyRequest) -> AdCopyResponse:
    started_at = perf_counter()
    model_spec = get_model_spec(request.model)
    raw_content = await _call_model(request)
    attempts = 1
    output_repaired = False
    try:
        content = _parse_content(raw_content)
    except InvalidModelOutputError:
        attempts = 2
        output_repaired = True
        repaired_content = await _call_model(request, invalid_content=raw_content)
        content = _parse_content(repaired_content)
    content = _add_prohibited_term_warnings(content, request.prohibited_terms)
    latency_ms = round((perf_counter() - started_at) * 1000)

    return AdCopyResponse(
        **content.model_dump(),
        model=request.model.value,
        routed_model=model_spec.routed_model,
        provider=model_spec.provider,
        prompt_version=PROMPT_VERSION,
        latency_ms=latency_ms,
        attempts=attempts,
        output_repaired=output_repaired,
    )
