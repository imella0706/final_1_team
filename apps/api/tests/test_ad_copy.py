import httpx
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.main import app
from app.core.config import settings
from app.modules.ad_copy.prompt import PROMPT_VERSION, build_prompt
from app.modules.ad_copy.schemas import AdCopyRequest
from app.modules.ad_copy.service import _parse_content


def sample_request() -> dict[str, object]:
    return {
        "model": "Qwen/Qwen2.5-7B-Instruct",
        "business_name": "동네봄 카페",
        "business_type": "cafe",
        "situation": "new_menu",
        "target_audiences": ["twenties", "office_workers"],
        "tone": "emotional",
        "product_names": ["수제 딸기 티라미수", "런치세트"],
        "features": ["매일 손질한 생딸기", "직접 만든 딸기청"],
        "channel": "instagram",
        "promotion": "7월 한 달간 10% 할인",
        "required_terms": ["생딸기"],
        "prohibited_terms": ["무조건", "최고"],
    }


def test_build_prompt_uses_business_facts_and_safety_terms() -> None:
    prompt = build_prompt(AdCopyRequest.model_validate(sample_request()))

    assert PROMPT_VERSION == "four-stage-ad-agency-pipeline-v2"
    assert "동네봄 카페" in prompt
    assert "수제 딸기 티라미수, 런치세트" in prompt
    assert "매일 손질한 생딸기" in prompt
    assert "STEP 1. MARKETING STRATEGY" in prompt
    assert "STEP 2. COPYWRITING" in prompt
    assert "STEP 3. VISUAL BRIEF" in prompt
    assert "STEP 4. PROMPT NORMALIZER" in prompt
    assert "20대" in prompt
    assert '"products_to_show"' in prompt


def test_model_catalog_contains_all_comparison_models() -> None:
    response = TestClient(app).get("/api/v1/ad-copies/models")

    assert response.status_code == 200
    models = response.json()
    assert len(models) == 6
    assert models[0]["id"] == "Qwen/Qwen2.5-7B-Instruct"
    assert models[0]["recommended"] is True
    assert models[2]["availability"] == "local_only"
    assert models[3]["availability"] == "local_only"
    assert models[4]["availability"] == "local_only"
    assert models[5]["availability"] == "research_only"


def test_generate_returns_clear_error_without_api_key(monkeypatch) -> None:
    monkeypatch.setattr(settings, "llm_api_key", None)
    response = TestClient(app).post("/api/v1/ad-copies/generate", json=sample_request())

    assert response.status_code == 503
    assert response.json() == {
        "detail": "BRANDMATE_LLM_API_KEY가 없습니다. API 서버의 .env를 설정해주세요."
    }


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
                        {
                            "message": {
                                "content": (
                                        '{"marketing_strategy":{'
                                        '"business_summary":{'
                                        '"business_name":"동네봄 카페",'
                                        '"business_type_korean":"카페",'
                                        '"situation_korean":"신메뉴",'
                                        '"target_audiences_korean":["20대","직장인"],'
                                        '"tone_korean":"감성적인",'
                                        '"channel_korean":"Instagram"},'
                                        '"mandatory_products":['
                                        '{"product_name":"수제 딸기 티라미수","role":"primary"},'
                                        '{"product_name":"런치세트","role":"secondary"}],'
                                        '"mandatory_features":['
                                        '{"feature_text":"매일 손질한 생딸기",'
                                        '"copy_usage_rule":"본문 문구에 원문 그대로 포함해야 함",'
                                        '"visual_usage_rule":"이미지에서 시각적으로 표현 가능한 형태로 변환해야 함"}],'
                                        '"core_message":"딸기 티라미수로 즐기는 달콤한 오후",'
                                        '"customer_emotion":"기분 좋은 휴식",'
                                        '"marketing_angle":"신메뉴 경험",'
                                        '"recommended_cta_direction":"방문 유도",'
                                        '"avoid_points":["과장 표현"]},'
                                        '"headlines":["딸기빛 오후를 한 조각"],'
                                        '"body_copies":["수제 딸기 티라미수와 런치세트로 매일 손질한 생딸기, 직접 만든 딸기청을 만나보세요."],'
                                        '"ctas":["오늘 매장에서 만나보세요."],'
                                        '"validation_check":{'
                                        '"all_products_included":true,'
                                        '"all_features_included":true,'
                                        '"prohibited_terms_used":false,'
                                        '"visual_brief_uses_enum_only":true,'
                                        '"hashtags_removed":true,'
                                        '"language_quality":"natural Korean"},'
                                        '"visual_brief":{'
                                        '"products_to_show":['
                                        '{"product_name":"수제 딸기 티라미수","visual_role":"main","must_be_visible":true},'
                                        '{"product_name":"런치세트","visual_role":"supporting","must_be_visible":true}],'
                                        '"feature_visualization":['
                                        '{"feature_text":"매일 손질한 생딸기","visual_translation":["fresh strawberry pieces"]},'
                                        '{"feature_text":"직접 만든 딸기청","visual_translation":["homemade strawberry syrup"]}],'
                                        '"camera_angle":"45_degree_close_up",'
                                        '"composition":"two_product_set",'
                                        '"lighting":"soft_natural_window_light",'
                                        '"background":"minimal_korean_local_cafe",'
                                        '"color_palette":["warm_beige_cream","soft_pink_peach"],'
                                        '"depth_of_field":"shallow_depth_of_field",'
                                        '"empty_space":"top_20_percent",'
                                        '"avoid":["readable_text","random_people"]},'
                                        '"safety_notes":[]}'
                                )
                            }
                        }
                    ]
                },
            )

    monkeypatch.setattr(settings, "llm_api_key", SecretStr("test-token"))
    monkeypatch.setattr(settings, "local_llm_base_url", "http://localhost:1234/v1")
    monkeypatch.setattr(settings, "phi_model", "lm-studio-phi-id")
    monkeypatch.setattr(
        "app.modules.ad_copy.service.httpx.AsyncClient",
        FakeAsyncClient,
    )

    request = sample_request()
    request["model"] = "microsoft/Phi-4-mini-instruct"
    response = TestClient(app).post("/api/v1/ad-copies/generate", json=request)

    assert response.status_code == 200
    assert response.json()["model"] == "microsoft/Phi-4-mini-instruct"
    assert response.json()["headlines"] == ["딸기빛 오후를 한 조각"]
    assert captured_payloads[0]["model"] == "lm-studio-phi-id"
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
