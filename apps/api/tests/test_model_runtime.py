from fastapi.testclient import TestClient

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


def test_lm_studio_settings_resolve_model_alias(monkeypatch) -> None:
    monkeypatch.setattr(settings, "local_llm_base_url", "http://localhost:1234/v1")
    monkeypatch.setattr(settings, "local_llm_model", None)
    monkeypatch.setattr(settings, "mistral_base_url", None)
    monkeypatch.setattr(settings, "mistral_model", "lm-studio-mistral-id")

    config = get_text_model_config("mistral-7b-instruct-v0.3")

    assert resolve_base_url(config) == "http://localhost:1234/v1"
    assert resolve_model_name(config) == "lm-studio-mistral-id"
    assert infer_provider("http://localhost:1234/v1", config.provider) == (
        TextRuntimeProvider.LM_STUDIO
    )


def test_llm_generate_endpoint_delegates_to_service(monkeypatch) -> None:
    async def fake_generate_text(request):
        return LlmGenerateResponse(
            model=request.model,
            provider=TextRuntimeProvider.LM_STUDIO,
            content="Generated ad copy",
            latency_ms=12,
        )

    monkeypatch.setattr(
        "app.modules.model_runtime.router.generate_text",
        fake_generate_text,
    )

    response = TestClient(app).post(
        "/api/llm/generate",
        json={"model": "mistral-7b-instruct-v0.3", "prompt": "Make an ad"},
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

    response = TestClient(app).post(
        "/api/image/generate",
        json={"model": "flux.1-schnell", "prompt": "A cafe ad image"},
    )

    assert response.status_code == 200
    assert response.json()["media_type"] == "image/png"
