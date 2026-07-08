import base64
import binascii
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


def _secret_value(value) -> str | None:
    if value is None:
        return None
    if hasattr(value, "get_secret_value"):
        return value.get_secret_value() or None
    return str(value) or None


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


def _is_openai_image_model(model: str) -> bool:
    return model.startswith("openai/")


def _is_openai_responses_image_model(model: str) -> bool:
    return model.startswith("openai-responses/")


def _openai_model_name(model: str) -> str:
    return model.removeprefix("openai/")


def _openai_responses_model_name(model: str) -> str:
    return model.removeprefix("openai-responses/")


def _openai_size(width: int, height: int) -> str:
    if width == height:
        return "1024x1024"
    if height > width:
        return "1024x1536"
    return "1536x1024"


def _decode_reference_image(data_url: str) -> tuple[bytes, str, str]:
    if not data_url.startswith("data:") or ";base64," not in data_url:
        raise ImageModelProviderError("Reference image must be a base64 data URL.")

    header, encoded = data_url.split(",", 1)
    media_type = header.removeprefix("data:").split(";", 1)[0] or "image/png"
    extension = {
        "image/jpeg": "jpg",
        "image/jpg": "jpg",
        "image/png": "png",
        "image/webp": "webp",
    }.get(media_type, "png")

    try:
        image_bytes = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as error:
        raise ImageModelProviderError("Reference image data URL is not valid base64.") from error

    return image_bytes, media_type, f"reference.{extension}"


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
    if _is_openai_responses_image_model(request.model.value):
        return await _generate_openai_responses_image(request)

    if _is_openai_image_model(request.model.value):
        return await _generate_openai_image(request)

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


async def _generate_openai_image(request: AdImageRequest) -> AdImageResponse:
    api_key = _secret_value(settings.openai_api_key)
    if not api_key:
        raise ImageModelNotConfiguredError(
            "BRANDMATE_OPENAI_API_KEY is required for OpenAI image generation."
        )

    if request.reference_image_data_url:
        return await _generate_openai_image_edit(request)

    started_at = perf_counter()
    endpoint = f"{settings.openai_base_url.rstrip('/')}/images/generations"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": _openai_model_name(request.model.value),
        "prompt": request.prompt,
        "size": _openai_size(request.width, request.height),
        "n": 1,
    }

    try:
        async with httpx.AsyncClient(timeout=settings.llm_timeout_seconds) as client:
            response = await client.post(endpoint, headers=headers, json=payload)
            response.raise_for_status()
        image_bytes, media_type = await _extract_image(response)
    except httpx.HTTPStatusError as error:
        detail = _provider_detail(error.response)
        raise ImageModelProviderError(
            f"{request.model.value} image generation failed: {detail}"
        ) from error
    except httpx.HTTPError as error:
        raise ImageModelProviderError(
            "Could not connect to the OpenAI image provider. "
            f"Root error: {type(error).__name__}"
        ) from error

    return AdImageResponse(
        model=payload["model"],
        prompt=request.prompt,
        image_base64=base64.b64encode(image_bytes).decode("ascii"),
        media_type=media_type,
        latency_ms=round((perf_counter() - started_at) * 1000),
    )


async def _generate_openai_image_edit(request: AdImageRequest) -> AdImageResponse:
    api_key = _secret_value(settings.openai_api_key)
    if not api_key:
        raise ImageModelNotConfiguredError(
            "BRANDMATE_OPENAI_API_KEY is required for OpenAI image editing."
        )
    if not request.reference_image_data_url:
        raise ImageModelProviderError("Reference image is required for image editing.")

    image_bytes, media_type, filename = _decode_reference_image(
        request.reference_image_data_url
    )
    started_at = perf_counter()
    endpoint = f"{settings.openai_base_url.rstrip('/')}/images/edits"
    headers = {"Authorization": f"Bearer {api_key}"}
    data = {
        "model": _openai_model_name(request.model.value),
        "prompt": request.prompt,
        "size": _openai_size(request.width, request.height),
        "n": "1",
    }
    files = {"image": (filename, image_bytes, media_type)}

    try:
        async with httpx.AsyncClient(timeout=settings.llm_timeout_seconds) as client:
            response = await client.post(
                endpoint,
                headers=headers,
                data=data,
                files=files,
            )
            response.raise_for_status()
        image_bytes, output_media_type = await _extract_image(response)
    except httpx.HTTPStatusError as error:
        detail = _provider_detail(error.response)
        raise ImageModelProviderError(
            f"{request.model.value} image editing failed: {detail}"
        ) from error
    except httpx.HTTPError as error:
        raise ImageModelProviderError(
            "Could not connect to the OpenAI image editing provider. "
            f"Root error: {type(error).__name__}"
        ) from error

    return AdImageResponse(
        model=data["model"],
        prompt=request.prompt,
        image_base64=base64.b64encode(image_bytes).decode("ascii"),
        media_type=output_media_type,
        latency_ms=round((perf_counter() - started_at) * 1000),
    )


async def _generate_openai_responses_image(request: AdImageRequest) -> AdImageResponse:
    api_key = _secret_value(settings.openai_api_key)
    if not api_key:
        raise ImageModelNotConfiguredError(
            "BRANDMATE_OPENAI_API_KEY is required for OpenAI Responses image generation."
        )

    started_at = perf_counter()
    model_name = _openai_responses_model_name(request.model.value)
    endpoint = f"{settings.openai_base_url.rstrip('/')}/responses"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    response_input: str | list[dict[str, Any]]
    if request.reference_image_data_url:
        response_input = [
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": request.prompt},
                    {
                        "type": "input_image",
                        "image_url": request.reference_image_data_url,
                    },
                ],
            }
        ]
    else:
        response_input = request.prompt
    payload = {
        "model": model_name,
        "input": response_input,
        "tools": [{"type": "image_generation"}],
    }

    try:
        async with httpx.AsyncClient(timeout=settings.llm_timeout_seconds) as client:
            response = await client.post(endpoint, headers=headers, json=payload)
            response.raise_for_status()
        image_bytes = _extract_openai_responses_image(response.json())
    except httpx.HTTPStatusError as error:
        detail = _provider_detail(error.response)
        raise ImageModelProviderError(
            f"{request.model.value} image generation failed: {detail}"
        ) from error
    except httpx.HTTPError as error:
        raise ImageModelProviderError(
            "Could not connect to the OpenAI Responses image provider. "
            f"Root error: {type(error).__name__}"
        ) from error

    return AdImageResponse(
        model=model_name,
        prompt=request.prompt,
        image_base64=base64.b64encode(image_bytes).decode("ascii"),
        media_type="image/png",
        latency_ms=round((perf_counter() - started_at) * 1000),
    )


def _extract_openai_responses_image(body: dict[str, Any]) -> bytes:
    output = body.get("output")
    if not isinstance(output, list):
        raise ImageModelProviderError(
            f"OpenAI Responses returned an unsupported response format: {str(body)[:500]}"
        )

    for item in output:
        if not isinstance(item, dict):
            continue
        if item.get("type") != "image_generation_call":
            continue
        result = item.get("result")
        if isinstance(result, str):
            return base64.b64decode(result)

    output_types = [
        item.get("type")
        for item in output
        if isinstance(item, dict) and isinstance(item.get("type"), str)
    ]
    raise ImageModelProviderError(
        "OpenAI Responses did not return an image_generation_call result. "
        f"Output types: {output_types}"
    )
