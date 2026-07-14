import json
from time import perf_counter
from typing import Any

import httpx
from pydantic import ValidationError

from app.core.config import settings
from app.modules.ad_copy.models import get_model_spec
from app.modules.ad_copy.output_validator import build_fallback_copy, validate_copy_output
from app.modules.ad_copy.prompt import PROMPT_VERSION, build_prompt
from app.modules.ad_copy.schemas import AdCopyContent, AdCopyRequest, AdCopyResponse
from app.modules.model_runtime.llm.registry import (
    get_text_model_config,
    infer_provider,
    resolve_api_key,
    resolve_base_url,
    resolve_model_name,
)
from app.modules.model_runtime.schemas import TextRuntimeProvider


class ModelNotConfiguredError(RuntimeError):
    """Raised when an LLM endpoint or API key has not been configured."""


class ModelProviderError(RuntimeError):
    """Raised when the configured model provider rejects or fails a request."""


class InvalidModelOutputError(RuntimeError):
    """Raised when a model response does not satisfy the advertising-copy schema."""


def _required_key_name(provider: TextRuntimeProvider) -> str:
    if provider == TextRuntimeProvider.OPENAI:
        return "BRANDMATE_OPENAI_API_KEY"
    if provider == TextRuntimeProvider.NVIDIA:
        return "BRANDMATE_NVIDIA_API_KEY"
    return "BRANDMATE_LLM_API_KEY"


def _request_payload(
    request: AdCopyRequest,
    *,
    provider: TextRuntimeProvider,
    provider_model_name: str,
    structured: bool,
<<<<<<< HEAD
    supports_system_role: bool = True,
    use_max_completion_tokens: bool = False,
    invalid_content: str | None = None,
) -> dict[str, Any]:
    messages = build_prompt_messages(
        request,
        supports_system_role=supports_system_role,
        invalid_content=invalid_content,
    )

    payload: dict[str, Any] = {
        "model": provider_model_name,
        "messages": messages,
        "temperature": 0.75,
    }
    token_limit_name = "max_completion_tokens" if use_max_completion_tokens else "max_tokens"
    payload[token_limit_name] = 4000 if request.channel.value == "naver_blog" else 2000
    if structured and request.channel.value != "naver_blog":
=======
    invalid_content: str | None = None,
) -> dict[str, Any]:
    user_content = build_prompt(request)
    if invalid_content is not None:
        user_content += f"""

[Design Intent] 직전 응답이 JSON 스키마 또는 비즈니스 검증을 통과하지 못했다.
아래 직전 응답의 의미는 유지하되, 현재 시스템이 요구하는 JSON 객체 형식으로만 다시 작성하라.
설명, 마크다운 코드 블록, 추가 문장은 출력하지 마라.

직전 응답:
{invalid_content[:6000]}
"""

    payload: dict[str, Any] = {
        "model": provider_model_name,
        "messages": [
            {
                "role": "system",
                "content": (
                    "당신은 한국 소상공인을 위한 광고 카피라이터입니다. "
                    "입력에 없는 사실을 만들지 말고 JSON 객체만 출력하세요."
                ),
            },
            {"role": "user", "content": user_content},
        ],
        "temperature": 0.2 if invalid_content is not None else 0.75,
    }
    token_limit_key = (
        "max_completion_tokens"
        if provider == TextRuntimeProvider.OPENAI
        and provider_model_name.startswith("gpt-5")
        else "max_tokens"
    )
    payload[token_limit_key] = 2000
    if structured:
>>>>>>> origin/dev
        payload["response_format"] = {
            "type": "json_schema",
            "json_schema": {
                "name": "AdCopyContent",
                "schema": AdCopyContent.model_json_schema(),
                "strict": True,
            },
        }
    return payload


def build_prompt_messages(
    request: AdCopyRequest,
    *,
    supports_system_role: bool = True,
    invalid_content: str | None = None,
) -> list[dict[str, str]]:
    system_prompt = (
        "당신은 한국 소상공인을 위한 광고 카피라이터입니다. "
        "입력에 없는 사실을 만들지 말고, 요청한 JSON 객체만 출력하세요."
    )
    user_prompt = build_prompt(request)
    if invalid_content:
        user_prompt = (
            f"{user_prompt}\n\n"
            "이전 응답은 JSON 스키마 또는 내부 검증에 실패했습니다. "
            "아래 이전 응답을 참고해 같은 요구사항을 만족하는 올바른 JSON 객체만 다시 출력하세요.\n"
            f"이전 응답:\n{invalid_content}"
        )

    if supports_system_role:
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
    else:
        messages = [{"role": "user", "content": f"{system_prompt}\n\n{user_prompt}"}]

    return messages


def _extract_content(response: httpx.Response) -> str:
    try:
        body = response.json()
        return body["choices"][0]["message"]["content"]
    except (json.JSONDecodeError, KeyError, IndexError, TypeError) as error:
        raise InvalidModelOutputError(
            "모델 응답에서 광고 문구 내용을 찾을 수 없습니다."
        ) from error


def _parse_content(content: str) -> AdCopyContent:
    cleaned = content.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.removeprefix("```json").removeprefix("```")
        cleaned = cleaned.removesuffix("```").strip()

    try:
        data, _ = json.JSONDecoder().raw_decode(cleaned)
        data.pop("image_prompt", None)
        validation_check = data.get("validation_check")
        if isinstance(validation_check, dict):
            if "all_features_included_verbatim" in validation_check:
                validation_check["all_features_included"] = validation_check.pop(
                    "all_features_included_verbatim"
                )
            validation_check.setdefault("visual_brief_uses_enum_only", True)
            validation_check.setdefault("hashtags_removed", True)
        for field in ("headlines", "body_copies", "ctas", "hashtags", "safety_notes"):
            if isinstance(data.get(field), str):
                data[field] = [data[field]]
        channel_recommendation = data.get("channel_recommendation")
        if isinstance(channel_recommendation, dict) and isinstance(
            channel_recommendation.get("publish_hashtags"),
            str,
        ):
            channel_recommendation["publish_hashtags"] = [
                item.strip()
                for item in channel_recommendation["publish_hashtags"].replace(",", " ").split()
                if item.strip()
            ]
        return AdCopyContent.model_validate(data)
    except (json.JSONDecodeError, ValidationError, AttributeError) as error:
        raise InvalidModelOutputError(
            "모델이 약속한 JSON 형식을 지키지 않았습니다. 같은 입력으로 다시 시도해주세요."
        ) from error


async def _call_model(
    request: AdCopyRequest,
    *,
    invalid_content: str | None = None,
) -> str:
<<<<<<< HEAD
=======
    model_spec = get_model_spec(request.model)
>>>>>>> origin/dev
    try:
        config = get_text_model_config(request.model.value)
    except KeyError as error:
        raise ModelNotConfiguredError(str(error)) from error

    model_spec = get_model_spec(request.model)
    base_url = resolve_base_url(config)
    provider_model_name = resolve_model_name(config)
    api_key = resolve_api_key(config)
    provider = infer_provider(base_url, config.provider)

    if provider in {
        TextRuntimeProvider.HUGGING_FACE_ROUTER,
        TextRuntimeProvider.OPENAI,
        TextRuntimeProvider.NVIDIA,
    } and not api_key:
<<<<<<< HEAD
        key_name = _required_key_name(provider)
        raise ModelNotConfiguredError(
            f"{key_name} is missing. Add it to apps/api/.env before calling {request.model.value}."
=======
        raise ModelNotConfiguredError(
            f"{config.api_key_setting}가 없습니다. API 서버의 .env를 설정해주세요."
>>>>>>> origin/dev
        )

    endpoint = f"{base_url.rstrip('/')}/chat/completions"
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    try:
        async with httpx.AsyncClient(timeout=settings.llm_timeout_seconds) as client:
            response = await client.post(
                endpoint,
                headers=headers,
                json=_request_payload(
                    request,
                    provider=provider,
                    provider_model_name=provider_model_name,
                    structured=model_spec.supports_structured_output,
<<<<<<< HEAD
                    supports_system_role=model_spec.supports_system_role,
                    use_max_completion_tokens=provider == TextRuntimeProvider.OPENAI,
=======
>>>>>>> origin/dev
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
                        provider=provider,
                        provider_model_name=provider_model_name,
                        structured=False,
<<<<<<< HEAD
                        supports_system_role=model_spec.supports_system_role,
                        use_max_completion_tokens=provider == TextRuntimeProvider.OPENAI,
=======
>>>>>>> origin/dev
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
            f"모델 서버에 연결할 수 없습니다: {base_url} ({type(error).__name__})"
        ) from error

    return _extract_content(response)


def _add_prohibited_term_warnings(
    content: AdCopyContent,
    prohibited_terms: list[str],
) -> AdCopyContent:
    generated_text = " ".join(content.headlines + content.body_copies + content.ctas)
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
    warnings: list[str] = []
    content: AdCopyContent | None = None
    last_error: Exception | None = None
    invalid_content: str | None = None
    attempts = 0
    output_repaired = False
<<<<<<< HEAD
    model_spec = get_model_spec(request.model)
    llm_prompt = {
        "prompt_version": PROMPT_VERSION,
        "model": request.model.value,
        "messages": build_prompt_messages(
            request,
            supports_system_role=model_spec.supports_system_role,
        ),
    }

    for attempt in range(3):
        attempts = attempt + 1
        raw_content: str | None = None
=======

    for attempt in range(3):
        attempts = attempt + 1
>>>>>>> origin/dev
        try:
            raw_content = await _call_model(request, invalid_content=invalid_content)
            candidate = _parse_content(raw_content)
            validation = validate_copy_output(candidate, request)
            if validation.valid:
                content = candidate
                output_repaired = attempt > 0
                break
            warnings = validation.warnings
            last_error = InvalidModelOutputError("; ".join(validation.warnings))
            invalid_content = raw_content
<<<<<<< HEAD
        except InvalidModelOutputError as error:
            last_error = error
            warnings = [str(error)]
            if raw_content:
                invalid_content = raw_content
=======
            output_repaired = True
        except InvalidModelOutputError as error:
            last_error = error
            warnings = [str(error)]
            invalid_content = raw_content if "raw_content" in locals() else None
            output_repaired = True
>>>>>>> origin/dev

        if attempt == 2:
            content = build_fallback_copy(request, warnings)
            output_repaired = True

    if content is None:
        raise InvalidModelOutputError(str(last_error)) from last_error

    content = _add_prohibited_term_warnings(content, request.prohibited_terms)
    latency_ms = round((perf_counter() - started_at) * 1000)

    return AdCopyResponse(
        **content.model_dump(),
        model=request.model.value,
        routed_model=model_spec.routed_model,
        provider=model_spec.provider,
        prompt_version=PROMPT_VERSION,
        llm_prompt=llm_prompt,
        latency_ms=latency_ms,
        attempts=attempts,
        output_repaired=output_repaired,
    )
