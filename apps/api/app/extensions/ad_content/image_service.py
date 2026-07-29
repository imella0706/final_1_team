import base64
import binascii
import asyncio
import copy
import io
import json
import random
import time
from pathlib import Path
from time import perf_counter
from typing import Any
from urllib.parse import urlencode

import httpx
from huggingface_hub import InferenceClient

from app.core.config import settings
from app.extensions.ad_content.schemas import AdImageRequest, AdImageResponse, ImageModel


class ImageModelNotConfiguredError(RuntimeError):
    """Raised when image generation credentials are missing."""


class ImageModelProviderError(RuntimeError):
    """Raised when the image model provider rejects or fails a request."""


DATA_URL_BASE64_MARKER = ";base64,"
REFERENCE_IMAGE_EXTENSIONS = {
    "image/jpeg": "jpg",
    "image/jpg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
}
LOCAL_SDXL_MODELS = {ImageModel.SDXL_BASE, ImageModel.SDXL_TURBO}
LOCAL_COMFYUI_MODELS = {*LOCAL_SDXL_MODELS, ImageModel.FLUX_SCHNELL}


async def is_comfyui_available() -> bool:
    if settings.image_provider.lower() != "comfyui":
        return False

    try:
        async with httpx.AsyncClient(
            timeout=settings.comfyui_health_timeout_seconds
        ) as client:
            response = await client.get(_comfyui_url("/system_stats"))
        return response.status_code == 200
    except (httpx.HTTPError, ValueError):
        return False


def _secret_value(value) -> str | None:
    if value is None:
        return None
    if hasattr(value, "get_secret_value"):
        return value.get_secret_value() or None
    return str(value) or None


DEFAULT_COMFYUI_WORKFLOW_PATH = (
    Path(__file__).resolve().parent / "workflows" / "flux_schnell_gguf_api.json"
)
SDXL_TEXT_TO_IMAGE_WORKFLOW_PATH = (
    Path(__file__).resolve().parent / "workflows" / "sdxl_text_to_image_api.json"
)
SDXL_IMAGE_TO_IMAGE_WORKFLOW_PATH = (
    Path(__file__).resolve().parent / "workflows" / "sdxl_image_to_image_api.json"
)

PROMPT_NODE_ID = "5"
FLUX_GUIDANCE_NODE_ID = "6"
NEGATIVE_PROMPT_NODE_ID = "7"
LATENT_NODE_ID = "8"
SAMPLING_MODEL_NODE_ID = "2"
KSAMPLER_NODE_ID = "9"
SAVE_IMAGE_NODE_ID = "11"


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
    if request.seed is not None:
        payload["parameters"]["seed"] = request.seed
    if request.negative_prompt:
        payload["parameters"]["negative_prompt"] = request.negative_prompt
    return payload


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
    if not data_url.startswith("data:") or DATA_URL_BASE64_MARKER not in data_url:
        raise ImageModelProviderError("Reference image must be a base64 data URL.")

    header, encoded = data_url.split(",", 1)
    media_type = header.removeprefix("data:").split(";", 1)[0] or "image/png"
    extension = REFERENCE_IMAGE_EXTENSIONS.get(media_type, "png")

    try:
        image_bytes = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as error:
        raise ImageModelProviderError("Reference image data URL is not valid base64.") from error

    return image_bytes, media_type, f"reference.{extension}"


def _reference_guided_prompt(prompt: str) -> str:
    return (
        "Use the attached reference image as the primary visual source. "
        "Preserve the visible product identity, shape, color, material, arrangement, "
        "camera angle, and overall mood from the reference image whenever they match "
        "the requested products. Recompose it as a clean commercial advertising poster "
        "background with space for text overlay. Do not introduce unrelated main products.\n\n"
        f"{prompt}"
    )


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
            output_media_type = image_response.headers.get("content-type", "image/png").split(";")[
                0
            ]
            return image_response.content, output_media_type

    raise ImageModelProviderError(
        f"Image provider returned an unsupported response format: {str(body)[:500]}"
    )


def _workflow_template_path(request: AdImageRequest) -> Path:
    if settings.comfyui_workflow_path:
        return Path(settings.comfyui_workflow_path)
    if request.model in LOCAL_SDXL_MODELS:
        if request.reference_image_data_url:
            return SDXL_IMAGE_TO_IMAGE_WORKFLOW_PATH
        return SDXL_TEXT_TO_IMAGE_WORKFLOW_PATH
    return DEFAULT_COMFYUI_WORKFLOW_PATH


def _load_comfyui_workflow_template(request: AdImageRequest) -> dict[str, Any]:
    path = _workflow_template_path(request)
    try:
        with path.open("r", encoding="utf-8") as file:
            workflow = json.load(file)
    except OSError as error:
        raise ImageModelNotConfiguredError(
            f"ComfyUI workflow template not found: {path}"
        ) from error
    except json.JSONDecodeError as error:
        raise ImageModelNotConfiguredError(
            f"ComfyUI workflow template is invalid JSON: {path}"
        ) from error

    if not isinstance(workflow, dict):
        raise ImageModelNotConfiguredError("ComfyUI workflow template must be a JSON object.")
    return workflow


def _build_sdxl_workflow(
    request: AdImageRequest,
    reference_filename: str | None,
) -> dict[str, Any]:
    workflow = copy.deepcopy(_load_comfyui_workflow_template(request))
    try:
        checkpoint = (
            settings.comfyui_sdxl_turbo_checkpoint
            if request.model == ImageModel.SDXL_TURBO
            else settings.comfyui_sdxl_checkpoint
        )
        workflow["1"]["inputs"]["ckpt_name"] = checkpoint
        workflow["2"]["inputs"]["text"] = request.prompt
        workflow["3"]["inputs"]["text"] = request.negative_prompt or ""
        is_turbo = request.model == ImageModel.SDXL_TURBO
        workflow["7"]["inputs"]["steps"] = (
            min(request.num_inference_steps, 4)
            if is_turbo
            else request.num_inference_steps
        )
        workflow["7"]["inputs"]["cfg"] = (
            1.0 if is_turbo else max(request.guidance_scale, 5.0)
        )
        if is_turbo:
            workflow["7"]["inputs"]["sampler_name"] = "euler_ancestral"
            workflow["7"]["inputs"]["scheduler"] = "normal"
        workflow["7"]["inputs"]["seed"] = (
            request.seed if request.seed is not None else random.randint(0, 2**32 - 1)
        )
        workflow["9"]["inputs"]["filename_prefix"] = "brandmate_sdxl"
        if reference_filename:
            workflow["4"]["inputs"]["image"] = reference_filename
            workflow["5"]["inputs"]["width"] = request.width
            workflow["5"]["inputs"]["height"] = request.height
            workflow["7"]["inputs"]["denoise"] = settings.comfyui_img2img_denoise
        else:
            workflow["4"]["inputs"]["width"] = request.width
            workflow["4"]["inputs"]["height"] = request.height
            workflow["7"]["inputs"]["denoise"] = 1.0
    except KeyError as error:
        raise ImageModelNotConfiguredError(
            "SDXL ComfyUI workflow does not match the expected BrandMate node ids."
        ) from error
    return workflow


def _build_comfyui_workflow(
    request: AdImageRequest,
    reference_filename: str | None = None,
) -> dict[str, Any]:
    # [Design Intent]
    # The LLM only controls safe runtime fields. The ComfyUI graph, model names,
    # and node wiring stay fixed so a malformed LLM response cannot rewrite the pipeline.
    if request.model in LOCAL_SDXL_MODELS:
        return _build_sdxl_workflow(request, reference_filename)

    workflow = copy.deepcopy(_load_comfyui_workflow_template(request))

    try:
        workflow[PROMPT_NODE_ID]["inputs"]["text"] = request.prompt
        workflow[NEGATIVE_PROMPT_NODE_ID]["inputs"]["text"] = request.negative_prompt or ""
        workflow[LATENT_NODE_ID]["inputs"]["width"] = request.width
        workflow[LATENT_NODE_ID]["inputs"]["height"] = request.height
        workflow[SAMPLING_MODEL_NODE_ID]["inputs"]["width"] = request.width
        workflow[SAMPLING_MODEL_NODE_ID]["inputs"]["height"] = request.height
        workflow[KSAMPLER_NODE_ID]["inputs"]["steps"] = min(
            request.num_inference_steps,
            4,
        )
        workflow[FLUX_GUIDANCE_NODE_ID]["inputs"]["guidance"] = min(
            request.guidance_scale,
            3.5,
        )
        workflow[KSAMPLER_NODE_ID]["inputs"]["cfg"] = 1.0
        workflow[KSAMPLER_NODE_ID]["inputs"]["seed"] = (
            request.seed if request.seed is not None else random.randint(0, 2**32 - 1)
        )
        workflow[SAVE_IMAGE_NODE_ID]["inputs"]["filename_prefix"] = "brandmate_flux"
    except KeyError as error:
        raise ImageModelNotConfiguredError(
            "ComfyUI workflow template does not match the expected BrandMate node ids."
        ) from error

    return workflow


def _comfyui_url(path: str) -> str:
    return f"{settings.comfyui_base_url.rstrip('/')}/{path.lstrip('/')}"


def _find_saved_image(history: dict[str, Any], prompt_id: str) -> dict[str, str]:
    prompt_history = history.get(prompt_id)
    if not isinstance(prompt_history, dict):
        raise ImageModelProviderError(f"ComfyUI history did not contain prompt_id={prompt_id}.")

    status = prompt_history.get("status")
    if isinstance(status, dict) and status.get("status_str") == "error":
        messages = status.get("messages")
        if isinstance(messages, list):
            for message in reversed(messages):
                if not isinstance(message, list) or len(message) < 2:
                    continue
                detail = message[1]
                if message[0] == "execution_error" and isinstance(detail, dict):
                    error_message = detail.get("exception_message")
                    if isinstance(error_message, str) and error_message.strip():
                        raise ImageModelProviderError(
                            f"ComfyUI workflow failed: {error_message.strip()}"
                        )
        raise ImageModelProviderError("ComfyUI workflow failed without an error message.")

    outputs = prompt_history.get("outputs")
    if not isinstance(outputs, dict):
        raise ImageModelProviderError("ComfyUI history response did not contain outputs.")

    for output in outputs.values():
        if not isinstance(output, dict):
            continue
        images = output.get("images")
        if isinstance(images, list) and images:
            image = images[0]
            if isinstance(image, dict):
                filename = image.get("filename")
                subfolder = image.get("subfolder", "")
                image_type = image.get("type", "output")
                if isinstance(filename, str):
                    return {
                        "filename": filename,
                        "subfolder": subfolder if isinstance(subfolder, str) else "",
                        "type": image_type if isinstance(image_type, str) else "output",
                    }

    raise ImageModelProviderError("ComfyUI completed but no saved image was found.")


async def _download_comfyui_image(client: httpx.AsyncClient, image: dict[str, str]) -> bytes:
    query = urlencode(image)
    response = await client.get(_comfyui_url(f"/view?{query}"))
    response.raise_for_status()
    return response.content


async def _upload_comfyui_reference(
    client: httpx.AsyncClient,
    data_url: str,
) -> str:
    image_bytes, media_type, filename = _decode_reference_image(data_url)
    response = await client.post(
        _comfyui_url("/upload/image"),
        files={"image": (filename, image_bytes, media_type)},
        data={"type": "input", "overwrite": "true"},
    )
    response.raise_for_status()
    body = response.json()
    name = body.get("name")
    subfolder = body.get("subfolder") or ""
    if not isinstance(name, str) or not name:
        raise ImageModelProviderError("ComfyUI image upload did not return a filename.")
    return f"{subfolder}/{name}" if subfolder else name


async def _generate_ad_image_comfyui(request: AdImageRequest) -> AdImageResponse:
    if request.model not in LOCAL_COMFYUI_MODELS:
        raise ImageModelNotConfiguredError(
            "Local ComfyUI generation supports FLUX.1 Schnell and SDXL Base 1.0."
        )
    if request.model == ImageModel.FLUX_SCHNELL and request.reference_image_data_url:
        raise ImageModelNotConfiguredError(
            "Local FLUX.1 Schnell is text-to-image only. Select Local SDXL to use an "
            "uploaded reference photo."
        )

    started_at = perf_counter()
    timeout = settings.comfyui_timeout_seconds
    deadline = time.monotonic() + timeout

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            reference_filename = None
            if request.reference_image_data_url:
                reference_filename = await _upload_comfyui_reference(
                    client,
                    request.reference_image_data_url,
                )
            workflow = _build_comfyui_workflow(request, reference_filename)
            prompt_response = await client.post(
                _comfyui_url("/prompt"),
                json={"prompt": workflow},
            )
            prompt_response.raise_for_status()
            prompt_id = prompt_response.json()["prompt_id"]

            while time.monotonic() < deadline:
                history_response = await client.get(_comfyui_url(f"/history/{prompt_id}"))
                history_response.raise_for_status()
                history = history_response.json()
                if history:
                    image = _find_saved_image(history, prompt_id)
                    image_bytes = await _download_comfyui_image(client, image)
                    return AdImageResponse(
                        model=request.model.value,
                        prompt=request.prompt,
                        image_base64=base64.b64encode(image_bytes).decode("ascii"),
                        media_type="image/png",
                        latency_ms=round((perf_counter() - started_at) * 1000),
                    )
                await _sleep(settings.comfyui_poll_interval_seconds)
    except KeyError as error:
        raise ImageModelProviderError("ComfyUI /prompt response did not include prompt_id.") from error
    except httpx.HTTPStatusError as error:
        detail = _provider_detail(error.response)
        raise ImageModelProviderError(f"ComfyUI image generation failed: {detail}") from error
    except httpx.HTTPError as error:
        raise ImageModelProviderError(
            f"Could not connect to ComfyUI at {settings.comfyui_base_url}. "
            "Check that ComfyUI is running and reachable."
        ) from error

    raise ImageModelProviderError(f"ComfyUI image generation timed out after {timeout} seconds.")


async def _sleep(seconds: float) -> None:
    await asyncio.sleep(seconds)


def _generate_hugging_face_image(
    request: AdImageRequest,
    api_key: str,
) -> tuple[bytes, str]:
    client = InferenceClient(
        provider=settings.hf_image_provider,
        api_key=api_key,
        timeout=settings.llm_timeout_seconds,
    )
    if request.reference_image_data_url:
        reference_bytes, _, _ = _decode_reference_image(request.reference_image_data_url)
        model = settings.hf_image_edit_model
        image = client.image_to_image(
            reference_bytes,
            prompt=_reference_guided_prompt(request.prompt),
            negative_prompt=request.negative_prompt,
            num_inference_steps=request.num_inference_steps,
            guidance_scale=request.guidance_scale,
            model=model,
            target_size={"width": request.width, "height": request.height},
        )
    else:
        model = request.model.value
        image = client.text_to_image(
            request.prompt,
            negative_prompt=request.negative_prompt,
            height=request.height,
            width=request.width,
            num_inference_steps=request.num_inference_steps,
            guidance_scale=request.guidance_scale,
            model=model,
            seed=request.seed,
        )
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue(), model


async def generate_ad_image(request: AdImageRequest) -> AdImageResponse:
    if (
        settings.image_provider.lower() == "comfyui"
        and request.model in LOCAL_COMFYUI_MODELS
    ):
        return await _generate_ad_image_comfyui(request)

    if _is_openai_responses_image_model(request.model.value):
        return await _generate_openai_responses_image(request)

    if _is_openai_image_model(request.model.value):
        return await _generate_openai_image(request)

    if settings.llm_api_key is None:
        raise ImageModelNotConfiguredError(
            "BRANDMATE_LLM_API_KEY is required for Hugging Face image generation."
        )

    started_at = perf_counter()
    try:
        image_bytes, routed_model = await asyncio.to_thread(
            _generate_hugging_face_image,
            request,
            settings.llm_api_key.get_secret_value(),
        )
    except Exception as error:
        raise ImageModelProviderError(
            f"{request.model.value} image generation failed via Hugging Face "
            f"provider {settings.hf_image_provider}: {error}"
        ) from error

    return AdImageResponse(
        model=routed_model,
        prompt=request.prompt,
        image_base64=base64.b64encode(image_bytes).decode("ascii"),
        media_type="image/png",
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
            f"Could not connect to the OpenAI image provider. Root error: {type(error).__name__}"
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

    image_bytes, media_type, filename = _decode_reference_image(request.reference_image_data_url)
    started_at = perf_counter()
    endpoint = f"{settings.openai_base_url.rstrip('/')}/images/edits"
    headers = {"Authorization": f"Bearer {api_key}"}
    data = {
        "model": _openai_model_name(request.model.value),
        "prompt": _reference_guided_prompt(request.prompt),
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
                    {"type": "input_text", "text": _reference_guided_prompt(request.prompt)},
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
