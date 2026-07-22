import asyncio
import json

import httpx
from pydantic import SecretStr

from app.main import app
from app.core.config import settings
from app.modules.ad_copy.models import get_model_spec
from app.modules.ad_copy.output_validator import build_fallback_copy, validate_copy_output
from app.modules.ad_copy.prompt import (
    PROMPT_VERSION,
    build_prompt,
    build_trend_card_prompt_block,
)
from app.modules.ad_copy.schemas import AdCopyRequest, AdModel, AgeGroup, TargetAudience
from app.modules.ad_copy.service import _parse_content, generate_ad_copy
from app.modules.ad_copy.trend_context import load_trend_card
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
    caption: str | None = None,
    publish_body: str | None = None,
) -> str:
    resolved_caption = caption if caption is not None else f"{headline}\n{body}"
    resolved_publish_body = (
        publish_body
        if publish_body is not None
        else f"{resolved_caption}\n{cta}"
    )
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
                "caption": resolved_caption,
                "publish_cta": cta,
                "publish_hashtags": ["#신메뉴", "#딸기티라미수"],
                "publish_title": headline,
                "publish_body": resolved_publish_body,
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

    assert PROMPT_VERSION == "channel-split-pipeline-v11-trendcard-v2"
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


def test_instagram_request_uses_server_active_card_without_client_id() -> None:
    request = AdCopyRequest.model_validate(sample_request())

    assert request.trend_card_id is None
    assert load_trend_card(request.trend_card_id).meme_id == (
        "gogumafarm:1bf390d89536004b"
    )


def test_trend_prompt_block_separates_generic_rules_from_card_data() -> None:
    request = AdCopyRequest.model_validate(sample_request())
    trend_card = load_trend_card(request.trend_card_id)

    block = build_trend_card_prompt_block(trend_card, channel=request.channel.value)

    assert "TrendCard 참고 정보" in block
    assert "text_patterns는 완성 문장이 아니라 창작 패턴입니다" in block
    assert "여러 상품을 하나의 플레이스홀더에 기계적으로 나열하지 마세요" in block
    assert '"display_name": "니가 좋아💖"' in block
    assert "고백 대상은 대표 메뉴 또는 상품 조합으로 바꾼다" in block
    assert "'니가 좋아' 뒤에 모든 메뉴명을 쉼표로 나열하는 단순 치환" in block
    assert "밈 반영 규칙" not in block
    assert "\\ub2c8" not in block


def test_trend_prompt_requires_trendcard_in_instagram_post_fields() -> None:
    request = AdCopyRequest.model_validate(sample_request())
    trend_card = load_trend_card(request.trend_card_id)

    prompt = build_prompt(request, trend_card)

    assert "channel_recommendation.caption의 첫 문장" in prompt
    assert "channel_recommendation.publish_body에도 그 caption" in prompt


def test_trend_validation_rejects_copy_without_selected_meme() -> None:
    request = AdCopyRequest.model_validate(sample_request())
    trend_card = load_trend_card(request.trend_card_id)
    content = _parse_content(valid_ad_copy_json())

    result = validate_copy_output(content, request, trend_card)

    assert result.valid is False
    assert any("첫 광고 문구에 반영되지 않았습니다" in warning for warning in result.warnings)


def test_trend_validation_rejects_instagram_post_without_meme() -> None:
    request = AdCopyRequest.model_validate(sample_request())
    trend_card = load_trend_card(request.trend_card_id)
    body = "수제 딸기 티라미수와 런치세트로 매일 손질한 생딸기, 직접 만든 딸기청을 만나보세요."
    content = _parse_content(
        valid_ad_copy_json(
            headline="딸기빛 오후엔 역시 니가 좋아, 수제 딸기 티라미수",
            caption=body,
            publish_body=f"{body}\n오늘 매장에서 만나보세요.",
        )
    )

    result = validate_copy_output(content, request, trend_card)

    assert result.valid is False
    assert not any("첫 광고 문구" in warning for warning in result.warnings)
    assert any("channel_recommendation.caption" in warning for warning in result.warnings)
    assert not any("Instagram caption 원문" in warning for warning in result.warnings)


def test_trend_validation_rejects_marker_only_in_cta() -> None:
    request = AdCopyRequest.model_validate(sample_request())
    trend_card = load_trend_card()
    content = _parse_content(
        valid_ad_copy_json(
            cta="니가 좋아, 수제 딸기 티라미수",
            caption="니가 좋아, 수제 딸기 티라미수\n오늘의 메뉴를 소개합니다.",
        )
    )

    result = validate_copy_output(content, request, trend_card)

    assert result.valid is False
    assert any("첫 광고 문구" in warning for warning in result.warnings)


def test_trend_validation_requires_marker_in_instagram_caption_opening() -> None:
    request = AdCopyRequest.model_validate(sample_request())
    trend_card = load_trend_card()
    body = "수제 딸기 티라미수와 런치세트를 소개합니다."
    caption = f"{body}\n니가 좋아, 수제 딸기 티라미수"
    content = _parse_content(
        valid_ad_copy_json(
            headline="니가 좋아, 수제 딸기 티라미수",
            caption=caption,
        )
    )

    result = validate_copy_output(content, request, trend_card)

    assert result.valid is False
    assert any("caption의 첫 문장" in warning for warning in result.warnings)


def test_trend_validation_requires_caption_text_in_publish_body() -> None:
    request = AdCopyRequest.model_validate(sample_request())
    trend_card = load_trend_card()
    caption = "니가 좋아, 수제 딸기 티라미수\n오늘의 메뉴를 소개합니다."
    content = _parse_content(
        valid_ad_copy_json(
            headline="니가 좋아, 수제 딸기 티라미수",
            caption=caption,
            publish_body="니가 좋아, 수제 딸기 티라미수\n서로 다른 게시물 본문입니다.",
        )
    )

    result = validate_copy_output(content, request, trend_card)

    assert result.valid is False
    assert any("Instagram caption 원문" in warning for warning in result.warnings)


def test_trend_validation_accepts_instagram_copy_and_post_with_meme() -> None:
    request = AdCopyRequest.model_validate(sample_request())
    trend_card = load_trend_card(request.trend_card_id)
    content = _parse_content(
        valid_ad_copy_json(headline="딸기빛 오후엔 역시 니가 좋아, 수제 딸기 티라미수")
    )

    result = validate_copy_output(content, request, trend_card)

    assert result.valid is True
    assert result.warnings == []


def test_fallback_copy_uses_selected_trend_card() -> None:
    request = AdCopyRequest.model_validate(sample_request())
    trend_card = load_trend_card(request.trend_card_id)

    content = build_fallback_copy(request, ["test fallback"], trend_card)

    assert "니가 좋아" in content.headlines[0]
    assert ", ".join(request.product_names) not in content.headlines[0]
    assert request.product_names[0] in content.headlines[0]
    assert "니가 좋아" in content.channel_recommendation.caption
    assert "니가 좋아" in content.channel_recommendation.publish_body
    assert validate_copy_output(content, request, trend_card).valid is True


def test_trend_validation_rejects_comma_separated_product_list() -> None:
    request = AdCopyRequest.model_validate(sample_request())
    trend_card = load_trend_card()
    listed_headline = "니가 좋아, 수제 딸기 티라미수, 런치세트"
    content = _parse_content(valid_ad_copy_json(headline=listed_headline))

    result = validate_copy_output(content, request, trend_card)

    assert result.valid is False
    assert any("쉼표로 단순 나열" in warning for warning in result.warnings)


def test_naver_blog_post_and_fallback_use_selected_trend_card() -> None:
    request_data = sample_request()
    request_data["channel"] = "naver_blog"
    request_data["trend_card_id"] = "gogumafarm:1bf390d89536004b"
    request = AdCopyRequest.model_validate(request_data)
    trend_card = load_trend_card(request.trend_card_id)
    content = _parse_content(
        valid_ad_copy_json(
            headline="딸기빛 오후엔 역시 니가 좋아, 수제 딸기 티라미수",
            publish_body="수제 딸기 티라미수와 런치세트를 소개합니다.",
        )
    )

    invalid_result = validate_copy_output(content, request, trend_card)

    assert invalid_result.valid is False
    assert any("channel_recommendation.publish_body" in warning for warning in invalid_result.warnings)

    content.channel_recommendation.publish_body = (
        "수제 딸기 티라미수와 런치세트가 생각나는 오후에도 "
        "결국 니가 좋아."
    )
    valid_result = validate_copy_output(content, request, trend_card)
    fallback = build_fallback_copy(request, ["test fallback"], trend_card)

    assert valid_result.valid is True
    assert "니가 좋아" in fallback.channel_recommendation.publish_body
    assert "니가 좋아" not in fallback.channel_recommendation.publish_title


def test_unknown_trend_card_returns_validation_error_before_model_call() -> None:
    request = sample_request()
    request["trend_card_id"] = "unknown_meme"

    response = post(app, "/api/v1/ad-copies/generate", json=request)

    assert response.status_code == 422
    assert response.json() == {"detail": "TrendCard를 찾을 수 없습니다: unknown_meme"}


def test_trend_card_conflicting_prohibited_term_returns_422() -> None:
    request = sample_request()
    request["prohibited_terms"] = ["좋아"]

    response = post(app, "/api/v1/ad-copies/generate", json=request)

    assert response.status_code == 422
    assert "필수 표현과 금지 표현이 충돌" in response.json()["detail"]


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
    assert len(models) == 6
    models_by_id = {model["id"]: model for model in models}
    assert models[0]["id"] == "Qwen/Qwen2.5-7B-Instruct"
    assert models[0]["provider"] == "huggingface"
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
                            "message": {
                                "content": valid_ad_copy_json(
                                    headline="OpenAI 문구, 오늘도 니가 좋아"
                                )
                            }
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
                                "content": valid_ad_copy_json(
                                    headline="딸기빛 오후엔 역시 니가 좋아, 수제 딸기 티라미수"
                                )
                            }
                        }
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
    assert response.json()["trend_card_id"] == "gogumafarm:1bf390d89536004b"
    assert response.json()["headlines"] == ["딸기빛 오후엔 역시 니가 좋아, 수제 딸기 티라미수"]
    assert captured_payloads[0]["model"] == "gpt-5.4-mini-test"
    assert captured_payloads[0]["max_completion_tokens"] == 2000
    assert "max_tokens" not in captured_payloads[0]
    assert captured_payloads[0]["response_format"]["type"] == "json_schema"
    assert "니가 좋아💖" in captured_payloads[0]["messages"][1]["content"]


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
            valid_ad_copy_json(headline="수정 문구, 오늘도 니가 좋아"),
        ]
    )
    captured_invalid_content: list[str | None] = []

    async def fake_call_model(request, *, trend_card=None, invalid_content=None):
        del request
        assert trend_card is not None
        assert trend_card.meme_id == "gogumafarm:1bf390d89536004b"
        captured_invalid_content.append(invalid_content)
        return next(responses)

    monkeypatch.setattr(
        "app.modules.ad_copy.service._call_model",
        fake_call_model,
    )

    result = asyncio.run(generate_ad_copy(AdCopyRequest.model_validate(sample_request())))

    assert result.headlines == ["수정 문구, 오늘도 니가 좋아"]
    assert result.attempts == 2
    assert result.output_repaired is True
    assert captured_invalid_content == [
        None,
        '{"headlines":["첫 문구"],"body_copies":["첫 본문"]}',
    ]


def test_generate_retries_when_instagram_post_misses_trend(monkeypatch) -> None:
    body = "수제 딸기 티라미수와 런치세트로 매일 손질한 생딸기, 직접 만든 딸기청을 만나보세요."
    responses = iter(
        [
            valid_ad_copy_json(
                headline="딸기빛 오후엔 역시 니가 좋아, 수제 딸기 티라미수",
                caption=body,
                publish_body=f"{body}\n오늘 매장에서 만나보세요.",
            ),
            valid_ad_copy_json(
                headline="딸기빛 오후엔 역시 니가 좋아, 수제 딸기 티라미수",
            ),
        ]
    )

    async def fake_call_model(request, *, trend_card=None, invalid_content=None):
        del request, invalid_content
        assert trend_card is not None
        return next(responses)

    monkeypatch.setattr(
        "app.modules.ad_copy.service._call_model",
        fake_call_model,
    )

    result = asyncio.run(generate_ad_copy(AdCopyRequest.model_validate(sample_request())))

    assert result.attempts == 2
    assert result.output_repaired is True
    assert "니가 좋아" in result.channel_recommendation.caption
    assert "니가 좋아" in result.channel_recommendation.publish_body


def test_generate_returns_only_revalidated_trend_fallback(monkeypatch) -> None:
    async def fake_call_model(request, *, trend_card=None, invalid_content=None):
        del request, invalid_content
        assert trend_card is not None
        return '{"invalid":"model output"}'

    monkeypatch.setattr(
        "app.modules.ad_copy.service._call_model",
        fake_call_model,
    )

    request = AdCopyRequest.model_validate(sample_request())
    result = asyncio.run(generate_ad_copy(request))
    trend_card = load_trend_card()

    assert result.attempts == 3
    assert result.output_repaired is True
    assert ", ".join(request.product_names) not in result.headlines[0]
    assert validate_copy_output(result, request, trend_card).valid is True
