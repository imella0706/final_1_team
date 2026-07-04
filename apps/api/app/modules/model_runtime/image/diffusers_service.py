import base64
from io import BytesIO
from time import perf_counter

from app.modules.model_runtime.image.registry import (
    get_image_model_config,
    resolve_image_model_name,
)
from app.modules.model_runtime.schemas import ImageGenerateRequest, ImageGenerateResponse


class ImageRuntimeError(RuntimeError):
    """Raised when an image runtime cannot complete a request."""


def _load_pipeline(model_name: str):
    try:
        import torch
        from diffusers import AutoPipelineForText2Image
    except ImportError as error:
        raise ImageRuntimeError(
            "Diffusers image generation requires optional packages. "
            "Install with: pip install diffusers transformers accelerate safetensors torch"
        ) from error

    dtype = torch.float16 if torch.cuda.is_available() else torch.float32
    pipe = AutoPipelineForText2Image.from_pretrained(model_name, torch_dtype=dtype)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    return pipe.to(device)


async def generate_image(request: ImageGenerateRequest) -> ImageGenerateResponse:
    started_at = perf_counter()
    try:
        config = get_image_model_config(request.model)
    except KeyError as error:
        raise ImageRuntimeError(str(error)) from error

    model_name = resolve_image_model_name(config)
    pipe = _load_pipeline(model_name)
    kwargs = {
        "prompt": request.prompt,
        "width": request.width,
        "height": request.height,
        "num_inference_steps": request.num_inference_steps,
        "guidance_scale": request.guidance_scale,
    }
    if request.negative_prompt:
        kwargs["negative_prompt"] = request.negative_prompt

    try:
        image = pipe(**kwargs).images[0]
    except Exception as error:
        raise ImageRuntimeError(f"{config.display_name} generation failed: {error}") from error

    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return ImageGenerateResponse(
        model=model_name,
        provider=config.provider,
        image_base64=base64.b64encode(buffer.getvalue()).decode("ascii"),
        media_type="image/png",
        latency_ms=round((perf_counter() - started_at) * 1000),
    )
