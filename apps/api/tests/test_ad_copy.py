import asyncio
import json

import httpx
from pydantic import SecretStr

from app.main import app
from app.core.config import settings
from app.modules.ad_copy.models import get_model_spec
from app.modules.ad_copy.prompt import PROMPT_VERSION, build_prompt
from app.modules.ad_copy.schemas import AdCopyRequest, AdModel, AgeGroup, TargetAudience
from app.modules.ad_copy.service import _parse_content, _request_payload, generate_ad_copy
from app.modules.model_runtime.schemas import TextRuntimeProvider
from tests.api_client import get, post


def sample_request() -> dict[str, object]:
    return {
        "model": "Qwen/Qwen2.5-7B-Instruct",
        "business_name": "동네봄 카페",
        "business_type": "cafe",
        "situation": "new_menu",
        "age_groups": ["twenties"],
        "target_audiences": ["office_workers"],
        "tone": "emotional",
        "product_names": ["수제 딸기 티라미수", "런치세트"],
        "features": ["매일 손질한 생딸기", "직접 만든 딸기청"],
        "channel": "instagram",
        "promotion": "7월 한 달간 10% 할인",
        "required_terms": ["생딸기"],
        "prohibited_terms": ["무조건", "최고"],
    }


def valid_ad_copy_json(
    *,
    headline: str = "딸기빛 오후를 한 조각",
    body: str = "수제 딸기 티라미수와 런치세트로 매일 손질한 생딸기, 직접 만든 딸기청을 만나보세요.",
    cta: str = "오늘 매장에서 만나보세요.",
) -> str:
    return json.dumps(
        {
            "marketing_strategy": {
                "business_summary": {
                    "business_name": "동네봄 카페",
                    "business_type_korean": "카페",
                    "situation_korean": "신메뉴",
                    "age_groups_korean": ["20대"],
                    "target_audiences_korean": ["직장인"],
                    "tone_korean": "감성적인",
                    "channel_korean": "Instagram",
                },
                "mandatory_products": [
                    {"product_name": "수제 딸기 티라미수", "role": "primary"},
                    {"product_name": "런치세트", "role": "secondary"},
                ],
                "mandatory_features": [
                    {
                        "feature_text": "매일 손질한 생딸기",
                        "copy_usage_rule": "본문 문구에 자연스럽게 포함해야 함",
                        "visual_usage_rule": "이미지에서 생딸기 토핑으로 표현해야 함",
                    }
                ],
                "core_message": "딸기 티라미수로 즐기는 달콤한 오후",
                "customer_emotion": "기분 좋은 휴식",
                "marketing_angle": "신메뉴 경험",
                "recommended_cta_direction": "방문 유도",
                "avoid_points": ["과장 표현"],
            },
            "headlines": [headline],
            "body_copies": [body],
            "ctas": [cta],
            "hashtags": ["#신메뉴", "#딸기티라미수"],
            "channel_recommendation": {
                "format_name": "Instagram feed caption",
                "writing_direction": "짧은 첫 문장과 방문 유도 중심",
                "image_direction": "두 상품이 함께 보이는 제품 사진",
                "placement_tip": "이미지와 캡션을 함께 게시",
                "overlay_headline": headline,
                "caption": body,
                "publish_cta": cta,
                "publish_hashtags": ["#신메뉴", "#딸기티라미수"],
                "publish_title": headline,
                "publish_body": f"{body}\n{cta}",
                "promotion_template": "상단 헤드라인 / 중앙 상품 / 하단 CTA",
                "image_insert_guide": "피드 이미지 첫 장에 대표 상품을 배치",
            },
            "validation_check": {
                "all_products_included": True,
                "all_features_included": True,
                "prohibited_terms_used": False,
                "visual_brief_uses_enum_only": True,
                "hashtags_removed": True,
                "language_quality": "natural Korean",
            },
            "visual_brief": {
                "products_to_show": [
                    {
                        "product_name": "수제 딸기 티라미수",
                        "visual_role": "main",
                        "must_be_visible": True,
                    },
                    {
                        "product_name": "런치세트",
                        "visual_role": "supporting",
                        "must_be_visible": True,
                    },
                ],
                "feature_visualization": [
                    {
                        "feature_text": "매일 손질한 생딸기",
                        "visual_translation": ["fresh strawberry pieces"],
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
            "safety_notes": [],
        },
        ensure_ascii=False,
    )


def test_build_prompt_uses_business_facts_and_safety_terms() -> None:
    prompt = build_prompt(AdCopyRequest.model_validate(sample_request()))

    assert PROMPT_VERSION == "channel-split-pipeline-v7"
    assert "동네봄 카페" in prompt
    assert "수제 딸기 티라미수, 런치세트" in prompt
    assert "매일 손질한 생딸기" in prompt
    assert "STEP 1. 마케팅 전략" in prompt
    assert "STEP 2. 광고 문구 작성" in prompt
    assert "STEP 3. 채널별 게시 형식 추천" in prompt
    assert "STEP 4. 비주얼 브리프" in prompt
    assert "20대" in prompt
    assert '"products_to_show"' in prompt


def test_build_prompt_separates_age_groups_and_targets() -> None:
    request = sample_request()
    request["age_groups"] = ["twenties"]
    request["target_audiences"] = ["office_workers", "solo"]

    prompt = build_prompt(AdCopyRequest.model_validate(request))

    assert "나이대: 20대" in prompt
    assert "타깃 유형: 직장인, 혼자 방문하는 고객" in prompt


def test_legacy_target_age_values_are_moved_to_age_groups() -> None:
    legacy_request = sample_request()
    legacy_request.pop("age_groups")
    legacy_request["target_audiences"] = ["twenties", "office_workers"]

    request = AdCopyRequest.model_validate(legacy_request)

    assert request.age_groups == [AgeGroup.TWENTIES]
    assert request.target_audiences == [TargetAudience.OFFICE_WORKERS]


def test_model_catalog_contains_all_comparison_models() -> None:
    response = get(app, "/api/v1/ad-copies/models")

    assert response.status_code == 200
    models = response.json()
    assert len(models) == 9
    models_by_id = {model["id"]: model for model in models}
    assert models[0]["id"] == "local/qwen2.5:1.5b"
    assert models[0]["provider"] == "ollama"
    assert models_by_id["local/qwen2.5:7b"]["recommended"] is True
    assert models_by_id["local/mistral:7b"]["provider"] == "ollama"
    assert models_by_id["meta-llama/Llama-3.1-8B-Instruct"]["availability"] == "gated"
    assert models_by_id["nvidia/meta/llama-3.1-8b-instruct"]["provider"] == "nvidia"
    assert models_by_id["openai/gpt-5.4"]["provider"] == "openai"
    assert "openai/gpt-4.1-mini" not in models_by_id
    assert "openai/gpt-5.5" not in models_by_id
    assert "google/gemma-2-9b-it" not in models_by_id
    assert (
        get_model_spec(AdModel.NVIDIA_LLAMA_3_1_8B).supports_structured_output
        is False
    )


def test_generate_returns_clear_error_without_api_key(monkeypatch) -> None:
    monkeypatch.setattr(settings, "openai_api_key", None)
    monkeypatch.setattr(settings, "local_llm_api_key", None)
    monkeypatch.setattr(settings, "llm_api_key", None)
    request = sample_request()
    request["model"] = "gpt-5.4-mini"
    response = post(app, "/api/v1/ad-copies/generate", json=request)

    assert response.status_code == 503
    assert response.json() == {
        "detail": "openai_api_key가 없습니다. API 서버의 .env를 설정해주세요."
    }


def test_openai_model_uses_its_own_endpoint_and_api_key(monkeypatch) -> None:
    captured_requests: list[dict[str, object]] = []

    class FakeAsyncClient:
        def __init__(self, **kwargs) -> None:
            del kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args) -> None:
            del args

        async def post(self, url, *, headers, json):
            captured_requests.append(
                {"url": url, "authorization": headers["Authorization"], "json": json}
            )
            return httpx.Response(
                200,
                request=httpx.Request("POST", url),
                json={
                    "choices": [
                        {
                            "message": {"content": valid_ad_copy_json(headline="OpenAI 문구")}
                        }
                    ]
                },
            )

    monkeypatch.setattr(settings, "openai_api_key", SecretStr("openai-test-token"))
    monkeypatch.setattr(settings, "openai_base_url", "https://openai.example/v1")
    monkeypatch.setattr(settings, "openai_gpt_5_4_mini_model", "gpt-5.4-mini-test")
    monkeypatch.setattr(
        "app.modules.ad_copy.service.httpx.AsyncClient",
        FakeAsyncClient,
    )
    request = sample_request()
    request["model"] = "gpt-5.4-mini"

    response = post(app, "/api/v1/ad-copies/generate", json=request)

    assert response.status_code == 200
    assert response.json()["provider"] == "openai"
    assert response.json()["routed_model"] == "gpt-5.4-mini"
    assert captured_requests[0]["url"] == (
        "https://openai.example/v1/chat/completions"
    )
    assert captured_requests[0]["authorization"] == "Bearer openai-test-token"
    assert captured_requests[0]["json"]["model"] == "gpt-5.4-mini-test"
    assert captured_requests[0]["json"]["max_completion_tokens"] == 2000
    assert "max_tokens" not in captured_requests[0]["json"]
    assert captured_requests[0]["json"]["response_format"]["type"] == "json_schema"


def test_hugging_face_payload_uses_compact_json_mode_and_low_temperature() -> None:
    request = AdCopyRequest.model_validate(sample_request())

    payload = _request_payload(
        request,
        provider=TextRuntimeProvider.HUGGING_FACE_ROUTER,
        provider_model_name="Qwen/Qwen2.5-7B-Instruct",
        structured=True,
    )

    assert payload["temperature"] == 0.2
    assert payload["response_format"] == {"type": "json_object"}
    assert "json_schema" not in payload["response_format"]


def test_local_ollama_model_uses_native_json_output(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeAsyncClient:
        def __init__(self, **kwargs) -> None:
            del kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args) -> None:
            del args

        async def post(self, url, *, headers, json):
            captured.update({"url": url, "headers": headers, "json": json})
            return httpx.Response(
                200,
                request=httpx.Request("POST", url),
                json={"message": {"content": valid_ad_copy_json()}},
            )

    monkeypatch.setattr(settings, "local_llm_base_url", "http://127.0.0.1:11434/v1")
    monkeypatch.setattr(
        "app.modules.ad_copy.service.httpx.AsyncClient",
        FakeAsyncClient,
    )
    request = sample_request()
    request["model"] = "local/qwen2.5:1.5b"

    response = post(app, "/api/v1/ad-copies/generate", json=request)

    assert response.status_code == 200
    assert response.json()["provider"] == "ollama"
    assert captured["url"] == "http://127.0.0.1:11434/api/chat"
    assert captured["json"]["model"] == "qwen2.5:1.5b"
    assert captured["json"]["stream"] is False
    assert captured["json"]["format"] == "json"
    assert captured["json"]["options"]["num_predict"] == 2000


def test_generate_uses_selected_model_and_returns_structured_copy(monkeypatch) -> None:
    captured_payloads: list[dict[str, object]] = []

    class FakeAsyncClient:
        def __init__(self, **kwargs) -> None:
            del kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args) -> None:
            del args

        async def post(self, url, *, headers, json):
            del headers
            captured_payloads.append(json)
            return httpx.Response(
                200,
                request=httpx.Request("POST", url),
                json={
                    "choices": [
                        {"message": {"content": valid_ad_copy_json()}}
                    ]
                },
            )

    monkeypatch.setattr(settings, "openai_api_key", SecretStr("test-token"))
    monkeypatch.setattr(settings, "openai_base_url", "https://api.openai.test/v1")
    monkeypatch.setattr(settings, "openai_gpt_5_4_mini_model", "gpt-5.4-mini-test")
    monkeypatch.setattr(
        "app.modules.ad_copy.service.httpx.AsyncClient",
        FakeAsyncClient,
    )

    request = sample_request()
    request["model"] = "gpt-5.4-mini"
    response = post(app, "/api/v1/ad-copies/generate", json=request)

    assert response.status_code == 200
    assert response.json()["model"] == "gpt-5.4-mini"
    assert response.json()["provider"] == "openai"
    assert response.json()["routed_model"] == "gpt-5.4-mini"
    assert response.json()["headlines"] == ["딸기빛 오후를 한 조각"]
    assert captured_payloads[0]["model"] == "gpt-5.4-mini-test"
    assert captured_payloads[0]["max_completion_tokens"] == 2000
    assert "max_tokens" not in captured_payloads[0]
    assert captured_payloads[0]["response_format"]["type"] == "json_schema"


def test_parse_content_normalizes_single_string_to_list() -> None:
    content = _parse_content(
        '{"headlines":"새로운 한 조각",'
        '"marketing_strategy":{'
        '"business_summary":{'
        '"business_name":"동네봄 카페",'
        '"business_type_korean":"카페",'
        '"situation_korean":"신메뉴",'
        '"target_audiences_korean":["20대"],'
        '"tone_korean":"감성적인",'
        '"channel_korean":"Instagram"},'
        '"mandatory_products":[{"product_name":"디저트","role":"primary"}],'
        '"mandatory_features":[],'
        '"core_message":"신메뉴 소개",'
        '"customer_emotion":"기대감",'
        '"marketing_angle":"첫 경험",'
        '"recommended_cta_direction":"방문 유도",'
        '"avoid_points":["과장"]},'
        '"body_copies":["오늘 만나보세요."],'
        '"ctas":"지금 방문해보세요.",'
        '"validation_check":{'
        '"all_products_included":true,'
        '"all_features_included":true,'
        '"prohibited_terms_used":false,'
        '"visual_brief_uses_enum_only":true,'
        '"hashtags_removed":true,'
        '"language_quality":"natural Korean"},'
        '"visual_brief":{'
        '"products_to_show":[{"product_name":"디저트","visual_role":"main","must_be_visible":true}],'
        '"feature_visualization":[],'
        '"camera_angle":"45_degree_close_up",'
        '"composition":"centered_product_hero",'
        '"lighting":"soft_natural_window_light",'
        '"background":"minimal_korean_local_cafe",'
        '"color_palette":["warm_beige_cream"],'
        '"depth_of_field":"shallow_depth_of_field",'
        '"empty_space":"top_20_percent",'
        '"avoid":["글자"]},'
        '"safety_notes":"과장 표현이 없는지 확인해주세요."}'
    )

    assert content.headlines == ["새로운 한 조각"]
    assert content.ctas == ["지금 방문해보세요."]
    assert content.safety_notes == ["과장 표현이 없는지 확인해주세요."]


def test_parse_content_ignores_explanation_after_json() -> None:
    content = _parse_content(
        '{"headlines":["새로운 한 조각"],'
        '"marketing_strategy":{'
        '"business_summary":{'
        '"business_name":"동네봄 카페",'
        '"business_type_korean":"카페",'
        '"situation_korean":"신메뉴",'
        '"target_audiences_korean":["20대"],'
        '"tone_korean":"감성적인",'
        '"channel_korean":"Instagram"},'
        '"mandatory_products":[{"product_name":"디저트","role":"primary"}],'
        '"mandatory_features":[],'
        '"core_message":"신메뉴 소개",'
        '"customer_emotion":"기대감",'
        '"marketing_angle":"첫 경험",'
        '"recommended_cta_direction":"방문 유도",'
        '"avoid_points":["과장"]},'
        '"body_copies":["오늘 만나보세요."],'
        '"ctas":["지금 방문해보세요."],'
        '"validation_check":{'
        '"all_products_included":true,'
        '"all_features_included":true,'
        '"prohibited_terms_used":false,'
        '"visual_brief_uses_enum_only":true,'
        '"hashtags_removed":true,'
        '"language_quality":"natural Korean"},'
        '"visual_brief":{'
        '"products_to_show":[{"product_name":"디저트","visual_role":"main","must_be_visible":true}],'
        '"feature_visualization":[],'
        '"camera_angle":"45_degree_close_up",'
        '"composition":"centered_product_hero",'
        '"lighting":"soft_natural_window_light",'
        '"background":"minimal_korean_local_cafe",'
        '"color_palette":["warm_beige_cream"],'
        '"depth_of_field":"shallow_depth_of_field",'
        '"empty_space":"top_20_percent",'
        '"avoid":["글자"]},'
        '"safety_notes":[]}\n'
        "위 JSON은 요청한 광고 문구입니다."
    )

    assert content.headlines == ["새로운 한 조각"]


def test_generate_retries_once_when_required_json_key_is_missing(monkeypatch) -> None:
    responses = iter(
        [
            '{"headlines":["첫 문구"],"body_copies":["첫 본문"]}',
            valid_ad_copy_json(headline="수정 문구"),
        ]
    )
    captured_invalid_content: list[str | None] = []

    async def fake_call_model(request, *, invalid_content=None):
        del request
        captured_invalid_content.append(invalid_content)
        return next(responses)

    monkeypatch.setattr(
        "app.modules.ad_copy.service._call_model",
        fake_call_model,
    )

    result = asyncio.run(generate_ad_copy(AdCopyRequest.model_validate(sample_request())))

    assert result.headlines == ["수정 문구"]
    assert result.attempts == 2
    assert result.output_repaired is True
    assert captured_invalid_content == [
        None,
        '{"headlines":["첫 문구"],"body_copies":["첫 본문"]}',
    ]
