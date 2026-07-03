from fastapi.testclient import TestClient

from app.extensions.ad_content.main import app
from app.extensions.ad_content.schemas import AdImageResponse
from app.extensions.ad_content.image_service import _image_endpoint
from app.modules.ad_copy.schemas import AdCopyResponse


def sample_content_request() -> dict[str, object]:
    return {
        "copy": {
            "model": "Qwen/Qwen2.5-7B-Instruct",
            "business_name": "Sample Cafe",
            "business_type": "cafe",
            "situation": "new_menu",
            "target_audiences": ["twenties", "office_workers"],
            "tone": "emotional",
            "product_names": ["strawberry tiramisu", "peach ade"],
            "features": ["fresh dessert every morning"],
            "channel": "instagram",
            "promotion": None,
            "required_terms": [],
            "prohibited_terms": ["best"],
        },
        "image_model": "black-forest-labs/FLUX.1-schnell",
        "image_width": 1024,
        "image_height": 1280,
    }


def test_image_model_catalog_is_exposed() -> None:
    response = TestClient(app).get("/api/v1/ad-content/image-models")

    assert response.status_code == 200
    models = response.json()
    assert models[0]["id"] == "black-forest-labs/FLUX.1-schnell"
    assert models[0]["recommended"] is False
    assert len(models) == 3


def test_image_endpoint_uses_hugging_face_router_by_default(monkeypatch) -> None:
    monkeypatch.delenv("BRANDMATE_IMAGE_BASE_URL", raising=False)

    assert (
        _image_endpoint("black-forest-labs/FLUX.1-schnell")
        == "https://router.huggingface.co/hf-inference/models/black-forest-labs/FLUX.1-schnell"
    )


def test_generate_content_orchestrates_copy_and_image_models(monkeypatch) -> None:
    captured_image_request = {}

    async def fake_generate_ad_copy(request):
        return AdCopyResponse(
            headlines=["Fresh dessert, ready for your afternoon"],
            body_copies=["Meet handmade strawberry tiramisu with peach ade today."],
            ctas=["Visit Sample Cafe today"],
            hashtags=["#samplecafe", "#dessert"],
            image_prompt="Editorial photo of strawberry tiramisu and peach ade",
            safety_notes=[],
            model=request.model.value,
            prompt_version="test",
            latency_ms=123,
        )

    async def fake_generate_ad_image(request):
        captured_image_request["model"] = request.model.value
        captured_image_request["prompt"] = request.prompt
        captured_image_request["width"] = request.width
        captured_image_request["height"] = request.height
        return AdImageResponse(
            model=request.model.value,
            prompt=request.prompt,
            image_base64="aW1hZ2U=",
            media_type="image/png",
            latency_ms=456,
        )

    monkeypatch.setattr(
        "app.extensions.ad_content.router.generate_ad_copy",
        fake_generate_ad_copy,
    )
    monkeypatch.setattr(
        "app.extensions.ad_content.router.generate_ad_image",
        fake_generate_ad_image,
    )

    response = TestClient(app).post("/api/v1/ad-content/generate", json=sample_content_request())

    assert response.status_code == 200
    body = response.json()
    assert body["copy"]["latency_ms"] == 123
    assert body["image"]["latency_ms"] == 456
    assert captured_image_request["model"] == "black-forest-labs/FLUX.1-schnell"
    assert captured_image_request["width"] == 1024
    assert captured_image_request["height"] == 1280
    assert "no watermarks" in captured_image_request["prompt"]
