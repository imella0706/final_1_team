import asyncio

import httpx
from pydantic import SecretStr
import pytest

from app.core.config import settings
from app.extensions.ad_content.main import app
from app.extensions.ad_content.schemas import AdImageRequest, AdImageResponse, VisionModel
from app.extensions.ad_content.image_prompt import build_ad_image_prompt
from app.extensions.ad_content.image_service import _build_comfyui_workflow, generate_ad_image
from app.extensions.ad_content.product_visualizer import ProductVisualization
from app.extensions.ad_content.reference_search import search_reference_images
from app.extensions.ad_content.reference_store import ProductVisualProfileStore
from app.extensions.ad_content.vision_service import request_vision_completion
from app.modules.ad_copy.schemas import AdCopyRequest
from app.modules.ad_copy.schemas import AdCopyResponse
from tests.api_client import get, post


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
        "vision_model": "openai/gpt-5.4-mini",
        "image_model": "black-forest-labs/FLUX.1-schnell",
        "image_width": 1024,
        "image_height": 1280,
        "reference_image_data_url": "data:image/png;base64,aW1hZ2U=",
    }


def test_generate_content_rejects_unknown_nested_trend_card() -> None:
    request = sample_content_request()
    request["copy"]["trend_card_id"] = "unknown_meme"

    response = post(app, "/api/v1/ad-content/generate", json=request)

    assert response.status_code == 422
    assert response.json() == {"detail": "TrendCard를 찾을 수 없습니다: unknown_meme"}


def test_image_model_catalog_is_exposed(monkeypatch) -> None:
    monkeypatch.setattr(settings, "image_provider", "comfyui")

    response = get(app, "/api/v1/ad-content/image-models")

    assert response.status_code == 200
    models = response.json()
    models_by_id = {model["id"]: model for model in models}
    assert models[0]["id"] == "stabilityai/stable-diffusion-xl-base-1.0"
    assert models[0]["provider"] == "Local ComfyUI"
    assert models[0]["recommended"] is True
    assert models_by_id["openai/gpt-image-1-mini"]["provider"] == "OpenAI"
    assert models_by_id["openai/gpt-image-1-mini"]["recommended"] is False
    assert models_by_id["openai-responses/gpt-5.5"]["provider"] == "OpenAI Responses API"
    assert models_by_id["stabilityai/stable-diffusion-xl-base-1.0"]["provider"] == (
        "Local ComfyUI"
    )
    assert models_by_id["stabilityai/sdxl-turbo"]["provider"] == "Local ComfyUI"
    assert models_by_id["black-forest-labs/FLUX.1-schnell"]["provider"] == (
        "Local ComfyUI"
    )


def test_local_sdxl_reference_workflow_uses_uploaded_image(monkeypatch) -> None:
    monkeypatch.setattr(settings, "comfyui_workflow_path", None)
    monkeypatch.setattr(settings, "comfyui_sdxl_checkpoint", "local-sdxl.safetensors")
    monkeypatch.setattr(settings, "comfyui_img2img_denoise", 0.42)

    workflow = _build_comfyui_workflow(
        AdImageRequest(
            model="stabilityai/stable-diffusion-xl-base-1.0",
            prompt="Preserve the cream bread and create an ad image.",
            negative_prompt="wrong product",
            reference_image_data_url="data:image/png;base64,aW1hZ2U=",
            width=1024,
            height=1280,
            seed=7,
        ),
        "brandmate/reference.png",
    )

    assert workflow["1"]["inputs"]["ckpt_name"] == "local-sdxl.safetensors"
    assert workflow["2"]["inputs"]["text"].startswith("Preserve the cream bread")
    assert workflow["3"]["inputs"]["text"] == "wrong product"
    assert workflow["4"]["inputs"]["image"] == "brandmate/reference.png"
    assert workflow["5"]["inputs"]["width"] == 1024
    assert workflow["5"]["inputs"]["height"] == 1280
    assert workflow["7"]["inputs"]["denoise"] == 0.42
    assert workflow["7"]["inputs"]["seed"] == 7


def test_local_sdxl_text_workflow_uses_requested_size(monkeypatch) -> None:
    monkeypatch.setattr(settings, "comfyui_workflow_path", None)

    workflow = _build_comfyui_workflow(
        AdImageRequest(
            model="stabilityai/stable-diffusion-xl-base-1.0",
            prompt="Create a cafe poster.",
            width=768,
            height=1024,
        )
    )

    assert workflow["4"]["class_type"] == "EmptyLatentImage"
    assert workflow["4"]["inputs"]["width"] == 768
    assert workflow["4"]["inputs"]["height"] == 1024
    assert workflow["7"]["inputs"]["denoise"] == 1.0


def test_local_sdxl_turbo_workflow_uses_fast_settings(monkeypatch) -> None:
    monkeypatch.setattr(settings, "comfyui_workflow_path", None)
    monkeypatch.setattr(
        settings,
        "comfyui_sdxl_turbo_checkpoint",
        "local-sdxl-turbo.safetensors",
    )

    workflow = _build_comfyui_workflow(
        AdImageRequest(
            model="stabilityai/sdxl-turbo",
            prompt="Create a fast cafe poster.",
            num_inference_steps=12,
            guidance_scale=7.5,
        )
    )

    assert workflow["1"]["inputs"]["ckpt_name"] == "local-sdxl-turbo.safetensors"
    assert workflow["7"]["inputs"]["steps"] == 4
    assert workflow["7"]["inputs"]["cfg"] == 1.0
    assert workflow["7"]["inputs"]["sampler_name"] == "euler_ancestral"
    assert workflow["7"]["inputs"]["scheduler"] == "normal"


def test_hugging_face_image_generation_uses_provider_routing(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeImage:
        def save(self, buffer, *, format):
            captured["format"] = format
            buffer.write(b"image")

    class FakeInferenceClient:
        def __init__(self, **kwargs):
            captured["client"] = kwargs

        def text_to_image(self, prompt, **kwargs):
            captured["prompt"] = prompt
            captured["request"] = kwargs
            return FakeImage()

    monkeypatch.setattr(settings, "image_provider", "huggingface")
    monkeypatch.setattr(settings, "hf_image_provider", "auto")
    monkeypatch.setattr(settings, "llm_api_key", SecretStr("hf-test-token"))
    monkeypatch.setattr(
        "app.extensions.ad_content.image_service.InferenceClient",
        FakeInferenceClient,
    )

    response = asyncio.run(
        generate_ad_image(
            AdImageRequest(
                model="black-forest-labs/FLUX.1-schnell",
                prompt="Make a cafe poster background",
            )
        )
    )

    assert captured["client"]["provider"] == "auto"
    assert captured["client"]["api_key"] == "hf-test-token"
    assert captured["request"]["model"] == "black-forest-labs/FLUX.1-schnell"
    assert captured["format"] == "PNG"
    assert response.image_base64 == "aW1hZ2U="


def test_vision_model_catalog_separates_providers(monkeypatch) -> None:
    monkeypatch.setattr(settings, "openai_api_key", SecretStr("openai-test-token"))
    monkeypatch.setattr(settings, "llm_api_key", SecretStr("hf-test-token"))
    monkeypatch.setattr(settings, "local_llm_base_url", "http://127.0.0.1:11434/v1")
    monkeypatch.setattr(settings, "internvl_base_url", None)

    response = get(app, "/api/v1/ad-content/vision-models")

    assert response.status_code == 200
    models = {model["id"]: model for model in response.json()}
    assert models["openai/gpt-5.4-mini"]["provider"] == "GPT / OpenAI"
    assert models["local/qwen2.5vl:7b"]["provider"] == "Local / Ollama"
    assert models["local/qwen3-vl:2b"]["enabled"] is True
    assert models["local/qwen3-vl:4b"]["recommended"] is True
    assert models["local/qwen3-vl:8b"]["enabled"] is True
    assert models["Qwen/Qwen2.5-VL-7B-Instruct"]["enabled"] is True
    assert models["Qwen/Qwen3-VL-2B-Instruct"]["enabled"] is True
    assert models["Qwen/Qwen3-VL-4B-Instruct"]["enabled"] is True
    assert models["Qwen/Qwen3-VL-8B-Instruct"]["enabled"] is False
    assert models["OpenGVLab/InternVL3-2B"]["enabled"] is False
    assert models["OpenGVLab/InternVL3-8B"]["availability"] == "configuration_required"


def test_local_ollama_vision_request_sends_base64_image(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeAsyncClient:
        def __init__(self, **kwargs):
            del kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            del args

        async def post(self, url, *, headers, json):
            captured["url"] = url
            captured["headers"] = headers
            captured["json"] = json
            return httpx.Response(
                200,
                request=httpx.Request("POST", url),
                json={"message": {"content": '{"summary":"strawberry cake"}'}},
            )

    monkeypatch.setattr(settings, "local_llm_base_url", "http://127.0.0.1:11434/v1")
    monkeypatch.setattr(settings, "local_llm_api_key", None)
    monkeypatch.setattr(
        settings,
        "local_qwen_3_vl_4b_model",
        "qwen3-vl:4b-instruct",
    )
    monkeypatch.setattr(
        "app.extensions.ad_content.vision_service.httpx.AsyncClient",
        FakeAsyncClient,
    )

    content, resolved = asyncio.run(
        request_vision_completion(
            VisionModel.LOCAL_QWEN_3_VL_4B,
            [
                {"type": "text", "text": "Describe this photo."},
                {
                    "type": "image_url",
                    "image_url": {"url": "data:image/png;base64,aW1hZ2U="},
                },
            ],
            max_tokens=300,
            json_mode=True,
        )
    )

    payload = captured["json"]
    assert content == '{"summary":"strawberry cake"}'
    assert resolved.provider == "Local / Ollama"
    assert captured["url"] == "http://127.0.0.1:11434/api/chat"
    assert payload["model"] == "qwen3-vl:4b-instruct"
    assert payload["messages"][0]["content"] == "Describe this photo."
    assert payload["messages"][0]["images"] == ["aW1hZ2U="]
    assert payload["options"]["num_predict"] == 300
    assert payload["think"] is False
    assert payload["keep_alive"] == 0
    assert payload["format"] == "json"


def test_hugging_face_vision_request_sends_image_url(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeAsyncClient:
        def __init__(self, **kwargs):
            del kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            del args

        async def post(self, url, *, headers, json):
            captured["url"] = url
            captured["headers"] = headers
            captured["json"] = json
            return httpx.Response(
                200,
                request=httpx.Request("POST", url),
                json={"choices": [{"message": {"content": "사진 분석 결과"}}]},
            )

    monkeypatch.setattr(settings, "llm_base_url", "https://router.huggingface.co/v1")
    monkeypatch.setattr(settings, "llm_api_key", SecretStr("hf-test-token"))
    monkeypatch.setattr(
        "app.extensions.ad_content.vision_service.httpx.AsyncClient",
        FakeAsyncClient,
    )

    content, resolved = asyncio.run(
        request_vision_completion(
            VisionModel.QWEN_2_5_VL_7B,
            [
                {"type": "text", "text": "사진을 설명하세요."},
                {
                    "type": "image_url",
                    "image_url": {"url": "data:image/png;base64,aW1hZ2U="},
                },
            ],
            max_tokens=400,
        )
    )

    assert content == "사진 분석 결과"
    assert resolved.provider == "Hugging Face"
    assert captured["url"] == "https://router.huggingface.co/v1/chat/completions"
    assert captured["json"]["model"] == "Qwen/Qwen2.5-VL-7B-Instruct"
    assert captured["json"]["messages"][0]["content"][1]["type"] == "image_url"
    assert captured["json"]["max_tokens"] == 400

def test_hugging_face_reference_image_uses_image_to_image(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeImage:
        def save(self, buffer, *, format):
            captured["format"] = format
            buffer.write(b"edited-image")

    class FakeInferenceClient:
        def __init__(self, **kwargs):
            captured["client"] = kwargs

        def image_to_image(self, image, prompt, **kwargs):
            captured["image"] = image
            captured["prompt"] = prompt
            captured["request"] = kwargs
            return FakeImage()

    monkeypatch.setattr(settings, "image_provider", "huggingface")
    monkeypatch.setattr(settings, "hf_image_provider", "auto")
    monkeypatch.setattr(
        settings,
        "hf_image_edit_model",
        "black-forest-labs/FLUX.1-Kontext-dev",
    )
    monkeypatch.setattr(settings, "llm_api_key", SecretStr("hf-test-token"))
    monkeypatch.setattr(
        "app.extensions.ad_content.image_service.InferenceClient",
        FakeInferenceClient,
    )

    response = asyncio.run(
        generate_ad_image(
            AdImageRequest(
                model="black-forest-labs/FLUX.1-schnell",
                prompt="Make a cafe poster background",
                reference_image_data_url="data:image/png;base64,aW1hZ2U=",
            )
        )
    )

    assert captured["image"] == b"image"
    assert "attached reference image as the primary visual source" in captured["prompt"]
    assert captured["request"]["model"] == "black-forest-labs/FLUX.1-Kontext-dev"
    assert captured["request"]["target_size"] == {"width": 1024, "height": 1280}
    assert response.model == "black-forest-labs/FLUX.1-Kontext-dev"
    assert response.image_base64 == "ZWRpdGVkLWltYWdl"


def test_openai_image_generation_sends_reference_image_as_edit(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeAsyncClient:
        def __init__(self, **kwargs) -> None:
            del kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args) -> None:
            del args

        async def post(self, url, *, headers, data=None, files=None, json=None):
            captured["url"] = url
            captured["headers"] = headers
            captured["data"] = data
            captured["files"] = files
            captured["json"] = json
            return httpx.Response(
                200,
                request=httpx.Request("POST", url),
                json={"data": [{"b64_json": "aW1hZ2U="}]},
            )

    monkeypatch.setattr(settings, "openai_api_key", SecretStr("openai-test-token"))
    monkeypatch.setattr(settings, "image_provider", "huggingface")
    monkeypatch.setattr(
        "app.extensions.ad_content.image_service.httpx.AsyncClient",
        FakeAsyncClient,
    )

    response = asyncio.run(
        generate_ad_image(
            AdImageRequest(
                model="openai/gpt-image-1-mini",
                prompt="Make a cafe poster background",
                reference_image_data_url="data:image/png;base64,aW1hZ2U=",
            )
        )
    )

    assert response.image_base64 == "aW1hZ2U="
    assert captured["url"].endswith("/images/edits")
    assert captured["data"]["model"] == "gpt-image-1-mini"
    assert "attached reference image as the primary visual source" in captured["data"]["prompt"]
    assert "Make a cafe poster background" in captured["data"]["prompt"]
    assert captured["json"] is None
    assert captured["files"]["image"][0] == "reference.png"


def test_comfyui_provider_still_allows_openai_image_models(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeAsyncClient:
        def __init__(self, **kwargs) -> None:
            del kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args) -> None:
            del args

        async def post(self, url, *, headers, data=None, files=None, json=None):
            captured["url"] = url
            captured["headers"] = headers
            captured["data"] = data
            captured["files"] = files
            captured["json"] = json
            return httpx.Response(
                200,
                request=httpx.Request("POST", url),
                json={"data": [{"b64_json": "aW1hZ2U="}]},
            )

    monkeypatch.setattr(settings, "image_provider", "comfyui")
    monkeypatch.setattr(settings, "openai_api_key", SecretStr("openai-test-token"))
    monkeypatch.setattr(
        "app.extensions.ad_content.image_service.httpx.AsyncClient",
        FakeAsyncClient,
    )

    response = asyncio.run(
        generate_ad_image(
            AdImageRequest(
                model="openai/gpt-image-1-mini",
                prompt="Make a cafe poster background",
            )
        )
    )

    assert response.image_base64 == "aW1hZ2U="
    assert captured["url"].endswith("/images/generations")
    assert captured["json"]["model"] == "gpt-image-1-mini"


@pytest.mark.parametrize(
    ("use_vision_analysis", "expected_analysis_calls"),
    [(True, 1), (False, 0)],
)
def test_generate_content_orchestrates_copy_and_image_models(
    monkeypatch,
    use_vision_analysis: bool,
    expected_analysis_calls: int,
) -> None:
    captured_image_request = {}
    analysis_calls = 0

    async def fake_generate_ad_copy(request):
        return AdCopyResponse(
            marketing_strategy={
                "business_summary": {
                    "business_name": "Sample Cafe",
                    "business_type_korean": "카페",
                    "situation_korean": "신메뉴",
                    "target_audiences_korean": ["20대", "직장인"],
                    "tone_korean": "감성적인",
                    "channel_korean": "Instagram",
                },
                "mandatory_products": [
                    {"product_name": "strawberry tiramisu", "role": "primary"},
                    {"product_name": "peach ade", "role": "secondary"},
                ],
                "mandatory_features": [
                    {
                        "feature_text": "fresh dessert every morning",
                        "copy_usage_rule": "본문 문구에 원문 그대로 포함해야 함",
                        "visual_usage_rule": "이미지에서 시각적으로 표현 가능한 형태로 변환해야 함",
                    }
                ],
                "core_message": "Fresh dessert for a relaxed afternoon",
                "customer_emotion": "cozy appetite",
                "marketing_angle": "new menu experience",
                "recommended_cta_direction": "visit today",
                "avoid_points": ["overclaim"],
            },
            headlines=["Fresh dessert, ready for your afternoon"],
            body_copies=[
                "Meet handmade strawberry tiramisu with peach ade today. "
                "fresh dessert every morning"
            ],
            ctas=["Visit Sample Cafe today"],
            validation_check={
                "all_products_included": True,
                "all_features_included": True,
                "prohibited_terms_used": False,
                "visual_brief_uses_enum_only": True,
                "hashtags_removed": True,
                "language_quality": "natural Korean",
            },
            visual_brief={
                "products_to_show": [
                    {
                        "product_name": "strawberry tiramisu",
                        "visual_role": "main",
                        "must_be_visible": True,
                    },
                    {
                        "product_name": "peach ade",
                        "visual_role": "supporting",
                        "must_be_visible": True,
                    },
                ],
                "feature_visualization": [
                    {
                        "feature_text": "fresh dessert every morning",
                        "visual_translation": ["fresh cream layers", "morning cafe setting"],
                    }
                ],
                "camera_angle": "45_degree_close_up",
                "composition": "two_product_set",
                "lighting": "soft_natural_window_light",
                "background": "minimal_korean_local_cafe",
                "color_palette": ["warm_beige_cream", "soft_pink_peach"],
                "depth_of_field": "shallow_depth_of_field",
                "empty_space": "top_20_percent",
                "avoid": ["readable_text", "random_people"],
            },
            safety_notes=[],
            model=request.model.value,
            prompt_version="test",
            latency_ms=123,
        )

    async def fake_generate_ad_image(request):
        captured_image_request["model"] = request.model.value
        captured_image_request["prompt"] = request.prompt
        captured_image_request["negative_prompt"] = request.negative_prompt
        captured_image_request["reference_image_data_url"] = request.reference_image_data_url
        captured_image_request["width"] = request.width
        captured_image_request["height"] = request.height
        return AdImageResponse(
            model=request.model.value,
            prompt=request.prompt,
            image_base64="aW1hZ2U=",
            media_type="image/png",
            latency_ms=456,
        )

    async def fake_describe_reference_image(reference_image_data_url, copy_request, vision_model):
        nonlocal analysis_calls
        analysis_calls += 1
        del reference_image_data_url, copy_request, vision_model
        return "참고 이미지: 딸기 디저트와 음료가 함께 보이는 사진", {
            "reference_image_prompt": "mocked",
        }

    async def fake_visualize_products(request, copy):
        del request, copy
        return ProductVisualization(
            products=[
                {
                    "original_name": "strawberry tiramisu",
                    "english_name": "strawberry tiramisu",
                    "category": "Dessert",
                    "visual_description": ["visible cream layers", "fresh strawberry topping"],
                    "serving_style": ["served on ceramic dessert plate"],
                    "must_show": ["cream layers", "strawberry topping"],
                    "must_not_replace_with": ["chocolate cake"],
                },
                {
                    "original_name": "peach ade",
                    "english_name": "peach ade",
                    "category": "Ade",
                    "visual_description": ["clear glass", "ice cubes", "peach slices"],
                    "serving_style": ["served in transparent glass"],
                    "must_show": ["peach slices", "ice cubes"],
                    "must_not_replace_with": ["latte"],
                },
            ]
        )

    monkeypatch.setattr(
        "app.extensions.ad_content.router.generate_ad_copy",
        fake_generate_ad_copy,
    )
    monkeypatch.setattr(
        "app.extensions.ad_content.router.generate_ad_image",
        fake_generate_ad_image,
    )
    monkeypatch.setattr(
        "app.extensions.ad_content.router.visualize_products",
        fake_visualize_products,
    )
    monkeypatch.setattr(
        "app.extensions.ad_content.router.describe_reference_image",
        fake_describe_reference_image,
    )

    request_body = sample_content_request()
    request_body["use_vision_analysis"] = use_vision_analysis
    response = post(app, "/api/v1/ad-content/generate", json=request_body)

    assert response.status_code == 200
    body = response.json()
    assert body["copy"]["latency_ms"] == 123
    assert body["copy"]["hashtags"] == []
    assert body["ad_copy"]["ctas"] == ["Visit Sample Cafe today"]
    assert body["product_visualization"]["products"][0]["category"] == "Dessert"
    assert body["validation"]["input_valid"] is True
    assert body["image"]["latency_ms"] == 456
    assert analysis_calls == expected_analysis_calls
    assert body["models"]["vision_analysis"] == (
        "enabled" if use_vision_analysis else "disabled"
    )
    assert body["vision_prompt"]["analysis_enabled"] is use_vision_analysis
    assert captured_image_request["model"] == "black-forest-labs/FLUX.1-schnell"
    assert captured_image_request["reference_image_data_url"] == "data:image/png;base64,aW1hZ2U="
    assert captured_image_request["width"] == 1024
    assert captured_image_request["height"] == 1280
    assert "commercial product ad image" in captured_image_request["prompt"]
    assert "strawberry tiramisu" in captured_image_request["prompt"]
    assert (
        "참고 이미지: 딸기 디저트와 음료가 함께 보이는 사진"
        in captured_image_request["prompt"]
    ) is use_vision_analysis
    assert (
        "Peach ade" in captured_image_request["prompt"]
        or "peach ade" in captured_image_request["prompt"]
    )
    assert "No readable text" in captured_image_request["negative_prompt"]


def test_image_prompt_uses_korean_and_reference_image_context() -> None:
    request = AdCopyRequest.model_validate(
        {
            "model": "Qwen/Qwen2.5-7B-Instruct",
            "business_name": "오후의 조각",
            "business_type": "cafe",
            "situation": "new_menu",
            "target_audiences": ["twenties"],
            "tone": "emotional",
            "product_names": ["수제 딸기 티라미수"],
            "features": ["매일 아침 직접 만드는 디저트"],
            "channel": "instagram",
            "promotion": None,
            "required_terms": [],
            "prohibited_terms": [],
        }
    )
    copy = AdCopyResponse(
        marketing_strategy={
            "business_summary": {
                "business_name": "오후의 조각",
                "business_type_korean": "카페",
                "situation_korean": "신메뉴",
                "target_audiences_korean": ["20대"],
                "tone_korean": "감성적인",
                "channel_korean": "Instagram",
            },
            "mandatory_products": [{"product_name": "수제 딸기 티라미수", "role": "primary"}],
            "mandatory_features": [],
            "core_message": "신메뉴를 강조하는 광고",
            "customer_emotion": "따뜻한 기대",
            "marketing_angle": "신메뉴 경험",
            "recommended_cta_direction": "방문 유도",
            "avoid_points": [],
        },
        headlines=["신메뉴가 출시됐어요"],
        body_copies=["수제 딸기 티라미수로 특별한 하루를 시작해보세요."],
        ctas=["지금 방문해보세요"],
        validation_check={
            "all_products_included": True,
            "all_features_included": True,
            "prohibited_terms_used": False,
            "visual_brief_uses_enum_only": True,
            "hashtags_removed": True,
            "language_quality": "natural Korean",
        },
        visual_brief={
            "products_to_show": [
                {
                    "product_name": "수제 딸기 티라미수",
                    "visual_role": "main",
                    "must_be_visible": True,
                }
            ],
            "feature_visualization": [],
            "camera_angle": "45_degree_close_up",
            "composition": "centered_product_hero",
            "lighting": "soft_natural_window_light",
            "background": "minimal_korean_local_cafe",
            "color_palette": ["warm_beige_cream"],
            "depth_of_field": "shallow_depth_of_field",
            "empty_space": "top_20_percent",
            "avoid": [],
        },
        safety_notes=[],
        model="gpt-4.1-mini",
        prompt_version="test",
        latency_ms=111,
    )

    prompt, negative_prompt = build_ad_image_prompt(
        copy,
        request,
        None,
        reference_image_context="참고 이미지: 딸기 크림층이 선명하게 보이는 디저트",
    )

    assert "commercial product ad image" in prompt
    assert "Reference image analysis" in prompt
    assert "Product Identity Lock" in prompt
    assert "딸기 크림층" in prompt
    assert "photorealistic" not in prompt.lower()
    assert "No readable text" in negative_prompt


def test_image_prompt_locks_user_products_and_blocks_fake_text() -> None:
    request = AdCopyRequest.model_validate(
        {
            "model": "Qwen/Qwen2.5-7B-Instruct",
            "business_name": "오후의 조각",
            "business_type": "cafe",
            "situation": "new_menu",
            "target_audiences": ["twenties"],
            "tone": "emotional",
            "product_names": ["수제 딸기 티라미수", "피치에이드"],
            "features": ["매일 아침 직접 만드는 디저트"],
            "channel": "instagram",
            "promotion": None,
            "required_terms": [],
            "prohibited_terms": [],
        }
    )
    copy = AdCopyResponse(
        marketing_strategy={
            "business_summary": {
                "business_name": "오후의 조각",
                "business_type_korean": "카페",
                "situation_korean": "신메뉴",
                "target_audiences_korean": ["20대"],
                "tone_korean": "감성적인",
                "channel_korean": "Instagram",
            },
            "mandatory_products": [
                {"product_name": "수제 딸기 티라미수", "role": "primary"},
                {"product_name": "피치에이드", "role": "secondary"},
            ],
            "mandatory_features": [],
            "core_message": "디저트와 음료를 함께 보여주는 광고",
            "customer_emotion": "따뜻한 휴식",
            "marketing_angle": "신메뉴 경험",
            "recommended_cta_direction": "방문 유도",
            "avoid_points": [],
        },
        headlines=["수제 딸기 티라미수와 피치에이드"],
        body_copies=["수제 딸기 티라미수와 피치에이드를 만나보세요."],
        ctas=["오늘 확인해보세요."],
        validation_check={
            "all_products_included": True,
            "all_features_included": True,
            "prohibited_terms_used": False,
            "visual_brief_uses_enum_only": True,
            "hashtags_removed": True,
            "language_quality": "natural Korean",
        },
        visual_brief={
            "products_to_show": [
                {
                    "product_name": "수제 딸기 티라미수",
                    "visual_role": "main",
                    "must_be_visible": True,
                },
                {
                    "product_name": "피치에이드",
                    "visual_role": "supporting",
                    "must_be_visible": True,
                },
            ],
            "feature_visualization": [],
            "camera_angle": "45_degree_close_up",
            "composition": "two_product_set",
            "lighting": "warm_afternoon_light",
            "background": "minimal_korean_local_cafe",
            "color_palette": ["soft_pink_peach", "warm_beige_cream"],
            "depth_of_field": "shallow_depth_of_field",
            "empty_space": "top_20_percent",
            "avoid": ["readable_text", "store_sign"],
        },
        safety_notes=[],
        model=request.model.value,
        prompt_version="test",
        latency_ms=1,
    )

    visualization = ProductVisualization(
        products=[
            {
                "original_name": "수제 딸기 티라미수",
                "english_name": "handmade strawberry tiramisu",
                "category": "Dessert",
                "visual_description": ["visible cream layers", "fresh strawberry slices"],
                "serving_style": ["served on a ceramic dessert plate"],
                "must_show": ["cream layers", "fresh strawberry slices"],
                "must_not_replace_with": ["chocolate cake", "cheesecake"],
            },
            {
                "original_name": "피치에이드",
                "english_name": "peach ade",
                "category": "Ade",
                "visual_description": ["clear glass", "ice cubes", "peach slices"],
                "serving_style": ["served in transparent glass"],
                "must_show": ["peach slices", "ice cubes"],
                "must_not_replace_with": ["latte", "milk tea"],
            },
        ]
    )

    prompt, negative_prompt = build_ad_image_prompt(copy, request, visualization)

    assert "수제 딸기 티라미수" in prompt
    assert "handmade strawberry tiramisu" in prompt
    assert "피치에이드" in prompt
    assert "visible cream layers" in prompt
    assert "Product Identity Lock" in prompt
    assert "realistic product photography" in prompt
    assert "no signs, no posters, no menu boards, no readable text" in prompt
    assert "unlisted product" in negative_prompt
    assert "chocolate cake" in negative_prompt
    assert "unrelated object" in negative_prompt
    assert "gibberish text" in negative_prompt
    assert "malformed Hangul" in negative_prompt


def test_image_prompt_handles_non_food_small_business_product() -> None:
    request = AdCopyRequest.model_validate(
        {
            "model": "Qwen/Qwen2.5-7B-Instruct",
            "business_name": "하루공방",
            "business_type": "dessert",
            "situation": "event",
            "target_audiences": ["couples"],
            "tone": "premium",
            "product_names": ["핸드메이드 세라믹 머그컵", "미니 꽃다발"],
            "features": ["손으로 빚은 유광 세라믹 질감", "선물 포장 가능"],
            "channel": "instagram",
            "promotion": None,
            "required_terms": [],
            "prohibited_terms": [],
        }
    )
    copy = AdCopyResponse(
        marketing_strategy={
            "business_summary": {
                "business_name": "하루공방",
                "business_type_korean": "소품샵",
                "situation_korean": "이벤트",
                "target_audiences_korean": ["커플 고객"],
                "tone_korean": "고급스러운",
                "channel_korean": "Instagram",
            },
            "mandatory_products": [
                {"product_name": "핸드메이드 세라믹 머그컵", "role": "primary"},
                {"product_name": "미니 꽃다발", "role": "secondary"},
            ],
            "mandatory_features": [],
            "core_message": "선물용 소품 광고",
            "customer_emotion": "따뜻함",
            "marketing_angle": "선물 제안",
            "recommended_cta_direction": "방문 유도",
            "avoid_points": [],
        },
        headlines=["핸드메이드 세라믹 머그컵과 미니 꽃다발"],
        body_copies=["핸드메이드 세라믹 머그컵과 미니 꽃다발을 만나보세요."],
        ctas=["매장에서 확인해보세요."],
        validation_check={
            "all_products_included": True,
            "all_features_included": True,
            "prohibited_terms_used": False,
            "visual_brief_uses_enum_only": True,
            "hashtags_removed": True,
            "language_quality": "natural Korean",
        },
        visual_brief={
            "products_to_show": [
                {
                    "product_name": "핸드메이드 세라믹 머그컵",
                    "visual_role": "main",
                    "must_be_visible": True,
                },
                {
                    "product_name": "미니 꽃다발",
                    "visual_role": "supporting",
                    "must_be_visible": True,
                },
            ],
            "feature_visualization": [
                {
                    "feature_text": "손으로 빚은 유광 세라믹 질감",
                    "visual_translation": ["glossy ceramic texture", "handmade surface"],
                },
                {
                    "feature_text": "선물 포장 가능",
                    "visual_translation": ["gift-ready styling", "neat wrapping ribbon"],
                },
            ],
            "camera_angle": "three_quarter_product_shot",
            "composition": "two_product_set",
            "lighting": "soft_studio_light",
            "background": "wooden_cafe_table",
            "color_palette": ["premium_neutral_tones"],
            "depth_of_field": "sharp_product_soft_background",
            "empty_space": "poster_safe_margin",
            "avoid": ["readable_text", "logo"],
        },
        safety_notes=[],
        model=request.model.value,
        prompt_version="test",
        latency_ms=1,
    )

    visualization = ProductVisualization(
        products=[
            {
                "original_name": "핸드메이드 세라믹 머그컵",
                "english_name": "handmade ceramic mug",
                "category": "Object",
                "visual_description": ["glossy ceramic texture", "handmade surface"],
                "serving_style": ["displayed upright on a clean tabletop"],
                "must_show": ["mug handle", "glossy ceramic texture"],
                "must_not_replace_with": ["paper cup", "glass tumbler"],
            },
            {
                "original_name": "미니 꽃다발",
                "english_name": "mini flower bouquet",
                "category": "Gift",
                "visual_description": ["small wrapped flowers", "neat ribbon"],
                "serving_style": ["placed next to the main product"],
                "must_show": ["flower stems", "wrapping paper"],
                "must_not_replace_with": ["potted plant"],
            },
        ]
    )

    prompt, negative_prompt = build_ad_image_prompt(copy, request, visualization)

    assert "핸드메이드 세라믹 머그컵" in prompt
    assert "handmade ceramic mug" in prompt
    assert "미니 꽃다발" in prompt
    assert "glossy ceramic texture" in prompt
    assert "realistic product photography" in prompt
    assert "premium neutral tones" in prompt
    assert "unrelated food" in negative_prompt
    assert "unrelated object" in negative_prompt
    assert "paper cup" in negative_prompt


def test_product_visual_profile_store_round_trips_without_image_bytes(tmp_path) -> None:
    store = ProductVisualProfileStore(str(tmp_path / "product_visual.sqlite3"))
    visualization = ProductVisualization(
        products=[
            {
                "original_name": "수제 딸기 티라미수",
                "english_name": "handmade strawberry tiramisu",
                "category": "Dessert",
                "visual_description": ["cream layers", "fresh strawberries"],
                "serving_style": ["served on ceramic plate"],
                "must_show": ["cream layers"],
                "must_not_replace_with": ["chocolate cake"],
            }
        ]
    )

    store.upsert_visualization(
        visualization,
        reference_query="수제 딸기 티라미수 cafe product photo",
        reference_sources=[
            {
                "source": "wikimedia",
                "page_url": "https://commons.wikimedia.org/example",
                "image_url": "https://upload.wikimedia.org/example.jpg",
                "license": "CC BY-SA",
            }
        ],
    )

    cached = store.get("수제 딸기 티라미수")

    assert cached is not None
    assert cached.english_name == "handmade strawberry tiramisu"
    assert cached.visual_description == ["cream layers", "fresh strawberries"]


@pytest.mark.anyio
async def test_reference_search_is_disabled_by_default(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.extensions.ad_content.reference_search.settings.reference_search_enabled",
        False,
    )

    query, results = await search_reference_images("수제 딸기 티라미수", "cafe")

    assert query == ""
    assert results == []
