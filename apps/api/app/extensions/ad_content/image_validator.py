import json
from dataclasses import dataclass

import httpx

from app.core.config import settings
from app.extensions.ad_content.schemas import AdImageResponse
from app.modules.ad_copy.schemas import AdCopyRequest


@dataclass(frozen=True)
class ImageValidationResult:
    valid: bool
    warnings: list[str]
    regeneration_prompt_suffix: str | None = None


def _secret_value(value) -> str | None:
    if value is None:
        return None
    if hasattr(value, "get_secret_value"):
        return value.get_secret_value() or None
    return str(value) or None


def _validation_prompt(copy_request: AdCopyRequest) -> str:
    return (
        "You are a strict ad image QA reviewer for Korean small-business ads.\n"
        "Inspect the generated image and return JSON only with this shape:\n"
        '{"valid": boolean, "warnings": string[], "regeneration_prompt_suffix": string | null}.\n'
        "Check whether the image visibly matches the requested business, products, and ad situation. "
        "Flag missing required products, distorted food, unreadable text, random people, brand logos, "
        "or visual elements that are unsupported by the input.\n\n"
        f"Business type: {copy_request.business_type.value}\n"
        f"Situation: {copy_request.situation.value}\n"
        f"Products that must be represented: {', '.join(copy_request.product_names)}\n"
        f"Features to preserve visually if possible: {', '.join(copy_request.features)}\n"
        f"Prohibited terms/expressions: {', '.join(copy_request.prohibited_terms)}"
    )


def _parse_validation(content: str) -> ImageValidationResult:
    cleaned = content.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.removeprefix("```json").removeprefix("```")
        cleaned = cleaned.removesuffix("```").strip()
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        return ImageValidationResult(
            valid=True,
            warnings=["OpenAI Vision validation returned non-JSON content."],
        )

    warnings = data.get("warnings", [])
    if not isinstance(warnings, list):
        warnings = [str(warnings)]
    suffix = data.get("regeneration_prompt_suffix")
    return ImageValidationResult(
        valid=bool(data.get("valid", True)),
        warnings=[str(warning) for warning in warnings],
        regeneration_prompt_suffix=suffix if isinstance(suffix, str) and suffix else None,
    )


async def validate_generated_image(
    image: AdImageResponse,
    copy_request: AdCopyRequest,
) -> ImageValidationResult:
    if not settings.image_validation_enabled:
        return ImageValidationResult(valid=True, warnings=[])

    api_key = _secret_value(settings.openai_api_key)
    if not api_key:
        return ImageValidationResult(
            valid=True,
            warnings=[
                "BRANDMATE_IMAGE_VALIDATION_ENABLED=true but BRANDMATE_OPENAI_API_KEY is missing; "
                "skipped GPT Vision validation."
            ],
        )

    model = settings.image_validator_model_name or settings.openai_vision_model
    endpoint = f"{settings.openai_base_url.rstrip('/')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": _validation_prompt(copy_request)},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{image.media_type};base64,{image.image_base64}"
                        },
                    },
                ],
            }
        ],
        "temperature": 0,
        "max_completion_tokens": 500,
        "response_format": {"type": "json_object"},
    }

    try:
        async with httpx.AsyncClient(timeout=settings.llm_timeout_seconds) as client:
            response = await client.post(endpoint, headers=headers, json=payload)
            response.raise_for_status()
            body = response.json()
            content = body["choices"][0]["message"]["content"]
    except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as error:
        return ImageValidationResult(
            valid=True,
            warnings=[f"OpenAI Vision validation skipped after provider error: {type(error).__name__}"],
        )

    return _parse_validation(content)
