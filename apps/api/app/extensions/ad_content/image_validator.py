import json
from dataclasses import dataclass

from app.core.config import settings
from app.extensions.ad_content.schemas import AdImageResponse, VisionModel
from app.extensions.ad_content.vision_service import (
    VisionModelProviderError,
    request_vision_completion,
)
from app.modules.ad_copy.schemas import AdCopyRequest


@dataclass(frozen=True)
class ImageValidationResult:
    valid: bool
    warnings: list[str]
    regeneration_prompt_suffix: str | None = None


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
    vision_model: VisionModel,
) -> ImageValidationResult:
    if not settings.image_validation_enabled:
        return ImageValidationResult(valid=True, warnings=[])

    try:
        content, _ = await request_vision_completion(
            vision_model,
            [
                {"type": "text", "text": _validation_prompt(copy_request)},
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:{image.media_type};base64,{image.image_base64}"
                    },
                },
            ],
            max_tokens=500,
            json_mode=True,
        )
    except VisionModelProviderError as error:
        return ImageValidationResult(
            valid=True,
            warnings=[f"Vision validation skipped after provider error: {error}"],
        )

    return _parse_validation(content)
