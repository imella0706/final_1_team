import json
from time import perf_counter
from typing import Any

import httpx
from pydantic import ValidationError

from app.core.config import settings
from app.modules.ad_copy.prompt import PROMPT_VERSION, build_prompt
from app.modules.ad_copy.schemas import AdCopyContent, AdCopyRequest, AdCopyResponse


class ModelNotConfiguredError(RuntimeError):
    """Raised when an LLM endpoint or API key has not been configured."""


class ModelProviderError(RuntimeError):
    """Raised when the configured model provider rejects or fails a request."""


class InvalidModelOutputError(RuntimeError):
    """Raised when a model response does not satisfy the advertising-copy schema."""


def _request_payload(request: AdCopyRequest, *, structured: bool) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": request.model.value,
        "messages": [
            {
                "role": "system",
                "content": (
                    "당신은 한국 소상공인을 위한 광고 카피라이터입니다. "
                    "입력에 없는 사실을 만들지 말고 JSON 객체만 출력하세요."
                ),
            },
            {"role": "user", "content": build_prompt(request)},
        ],
        "temperature": 0.75,
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


async def _call_model(request: AdCopyRequest) -> str:
    if settings.llm_api_key is None:
        raise ModelNotConfiguredError(
            "BRANDMATE_LLM_API_KEY가 없습니다. API 서버의 .env를 설정해주세요."
        )

    endpoint = f"{settings.llm_base_url.rstrip('/')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {settings.llm_api_key.get_secret_value()}",
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=settings.llm_timeout_seconds) as client:
            response = await client.post(
                endpoint,
                headers=headers,
                json=_request_payload(request, structured=True),
            )

            if response.status_code in {400, 422}:
                response = await client.post(
                    endpoint,
                    headers=headers,
                    json=_request_payload(request, structured=False),
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
    raw_content = await _call_model(request)
    content = _parse_content(raw_content)
    content = _add_prohibited_term_warnings(content, request.prohibited_terms)
    latency_ms = round((perf_counter() - started_at) * 1000)

    return AdCopyResponse(
        **content.model_dump(),
        model=request.model.value,
        prompt_version=PROMPT_VERSION,
        latency_ms=latency_ms,
    )
