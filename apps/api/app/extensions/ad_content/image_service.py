import base64
import os
from time import perf_counter
from typing import Any

import httpx

from app.core.config import settings
from app.extensions.ad_content.schemas import AdImageRequest, AdImageResponse


class ImageModelNotConfiguredError(RuntimeError):
    """Raised when image generation credentials are missing."""


class ImageModelProviderError(RuntimeError):
    """Raised when the image model provider rejects or fails a request."""


DEFAULT_IMAGE_BASE_URL = "https://router.huggingface.co/hf-inference"


def _build_payload(request: AdImageRequest) -> dict:
    payload = {
        "inputs": request.prompt,
        "parameters": {
            "width": request.width,
            "height": request.height,
            "guidance_scale": request.guidance_scale,
            "num_inference_steps": request.num_inference_steps,
        },
        "options": {"wait_for_model": True},
    }
    if request.negative_prompt:
        payload["parameters"]["negative_prompt"] = request.negative_prompt
    return payload


def _image_endpoint(model: str) -> str:
    base_url = os.getenv("BRANDMATE_IMAGE_BASE_URL", DEFAULT_IMAGE_BASE_URL)
    return f"{base_url.rstrip('/')}/models/{model}"


def _provider_detail(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return response.text[:500]

    if isinstance(body, dict):
        for key in ("error", "detail", "message"):
            value = body.get(key)
            if isinstance(value, str):
                return value[:500]
    return str(body)[:500]


async def _extract_image(response: httpx.Response) -> tuple[bytes, str]:
    media_type = response.headers.get("content-type", "image/png").split(";")[0]
    if media_type.startswith("image/"):
        return response.content, media_type

    try:
        body: Any = response.json()
    except ValueError as error:
        raise ImageModelProviderError(
            f"Image provider returned non-image content: {response.text[:500]}"
        ) from error

    if isinstance(body, dict):
        data = body.get("data")
        if isinstance(data, list) and data and isinstance(data[0], dict):
            b64_json = data[0].get("b64_json")
            if isinstance(b64_json, str):
                return base64.b64decode(b64_json), "image/jpeg"

        output = body.get("output")
        if isinstance(output, list) and output and isinstance(output[0], str):
            async with httpx.AsyncClient(timeout=settings.llm_timeout_seconds) as client:
                image_response = await client.get(output[0])
                image_response.raise_for_status()
            output_media_type = image_response.headers.get("content-type", "image/png").split(";")[0]
            return image_response.content, output_media_type

    raise ImageModelProviderError(
        f"Image provider returned an unsupported response format: {str(body)[:500]}"
    )


async def generate_ad_image(request: AdImageRequest) -> AdImageResponse:
    if settings.llm_api_key is None:
        raise ImageModelNotConfiguredError(
            "BRANDMATE_LLM_API_KEY is required for Hugging Face image generation."
        )

    started_at = perf_counter()
    endpoint = _image_endpoint(request.model.value)
    headers = {
        "Authorization": f"Bearer {settings.llm_api_key.get_secret_value()}",
        "Accept": "image/png",
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=settings.llm_timeout_seconds) as client:
            response = await client.post(endpoint, headers=headers, json=_build_payload(request))
            response.raise_for_status()
        image_bytes, media_type = await _extract_image(response)
    except httpx.HTTPStatusError as error:
        detail = _provider_detail(error.response)
        raise ImageModelProviderError(
            f"{request.model.value} image generation failed: {detail}"
        ) from error
    except httpx.HTTPError as error:
        raise ImageModelProviderError(
            "Could not connect to the image model provider. "
            "Check internet access and BRANDMATE_IMAGE_BASE_URL "
            f"({DEFAULT_IMAGE_BASE_URL}). Root error: {type(error).__name__}"
        ) from error

    return AdImageResponse(
        model=request.model.value,
        prompt=request.prompt,
        image_base64=base64.b64encode(image_bytes).decode("ascii"),
        media_type=media_type,
        latency_ms=round((perf_counter() - started_at) * 1000),
    )
