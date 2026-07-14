from app.core.config import settings
from app.extensions.ad_content.main import app
from app.modules.model_runtime.llm.registry import (
    get_text_model_config,
    infer_provider,
    resolve_base_url,
    resolve_model_name,
)
from app.modules.model_runtime.schemas import (
    ImageGenerateResponse,
    ImageRuntimeProvider,
    LlmGenerateResponse,
    TextRuntimeProvider,
)
from tests.api_client import post


def test_openai_settings_resolve_model_alias(monkeypatch) -> None:
    monkeypatch.setattr(settings, "openai_base_url", "https://api.openai.com/v1")
    monkeypatch.setattr(settings, "openai_gpt_4_1_mini_model", "gpt-4.1-mini")

    config = get_text_model_config("gpt-4.1-mini")

    assert resolve_base_url(config) == "https://api.openai.com/v1"
    assert resolve_model_name(config) == "gpt-4.1-mini"
    assert infer_provider("https://api.openai.com/v1", config.provider) == (
        TextRuntimeProvider.OPENAI
    )


def test_nvidia_settings_resolve_model_alias(monkeypatch) -> None:
    monkeypatch.setattr(
        settings,
        "nvidia_base_url",
        "https://integrate.api.nvidia.com/v1",
    )
    monkeypatch.setattr(settings, "nvidia_llama_model", "meta/llama-3.1-8b-instruct")

    config = get_text_model_config("nvidia/meta/llama-3.1-8b-instruct")

    assert resolve_base_url(config) == "https://integrate.api.nvidia.com/v1"
    assert resolve_model_name(config) == "meta/llama-3.1-8b-instruct"
    assert infer_provider("https://integrate.api.nvidia.com/v1", config.provider) == (
        TextRuntimeProvider.NVIDIA
    )


def test_llm_generate_endpoint_delegates_to_service(monkeypatch) -> None:
    async def fake_generate_text(request):
        return LlmGenerateResponse(
            model=request.model,
            provider=TextRuntimeProvider.OPENAI,
            content="Generated ad copy",
            latency_ms=12,
        )

    monkeypatch.setattr(
        "app.modules.model_runtime.router.generate_text",
        fake_generate_text,
    )

    response = post(
        app,
        "/api/llm/generate",
        json={"model": "gpt-4.1-mini", "prompt": "Make an ad"},
    )

    assert response.status_code == 200
    assert response.json()["content"] == "Generated ad copy"


def test_image_generate_endpoint_delegates_to_service(monkeypatch) -> None:
    async def fake_generate_image(request):
        return ImageGenerateResponse(
            model=request.model,
            provider=ImageRuntimeProvider.DIFFUSERS,
            image_base64="aW1hZ2U=",
            media_type="image/png",
            latency_ms=34,
        )

    monkeypatch.setattr(
        "app.modules.model_runtime.router.generate_image",
        fake_generate_image,
    )

    response = post(
        app,
        "/api/image/generate",
        json={"model": "flux.1-schnell", "prompt": "A cafe ad image"},
    )

    assert response.status_code == 200
    assert response.json()["media_type"] == "image/png"
