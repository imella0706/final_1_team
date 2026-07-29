from app.evaluation.metrics import (
    context_adherence_score,
    hallucination_terms,
    hashtag_compliance_rate,
    headline_diversity_score,
    is_english_image_prompt,
    percentile,
    toxicity_terms,
)
from app.modules.ad_copy.schemas import AdCopyRequest, AdCopyResponse


def request_fixture() -> AdCopyRequest:
    return AdCopyRequest.model_validate(
        {
            "model": "Qwen/Qwen2.5-7B-Instruct",
            "business_name": "오후의 조각",
            "business_type": "cafe",
            "situation": "new_menu",
            "target_audiences": ["twenties"],
            "tone": "emotional",
            "product_names": ["수제 딸기 티라미수"],
            "features": ["생딸기 사용"],
            "channel": "instagram",
            "required_terms": ["생딸기"],
            "prohibited_terms": ["최고"],
        }
    )


def response_fixture() -> AdCopyResponse:
    return AdCopyResponse.model_validate(
        {
            "marketing_strategy": {
                "business_summary": {
                    "business_name": "오후의 조각",
                    "business_type_korean": "카페",
                    "situation_korean": "신메뉴",
                    "age_groups_korean": ["20대"],
                    "target_audiences_korean": [],
                    "tone_korean": "감성적인",
                    "channel_korean": "Instagram",
                },
                "mandatory_products": [
                    {"product_name": "수제 딸기 티라미수", "role": "primary"}
                ],
                "mandatory_features": [
                    {
                        "feature_text": "생딸기 사용",
                        "copy_usage_rule": "본문 문구에 자연스럽게 포함해야 함",
                        "visual_usage_rule": "이미지에서 생딸기 토핑으로 표현해야 함",
                    }
                ],
                "core_message": "생딸기 티라미수 신메뉴 소개",
                "customer_emotion": "달콤한 기대감",
                "marketing_angle": "신메뉴 경험",
                "recommended_cta_direction": "방문 유도",
                "avoid_points": [],
            },
            "headlines": ["생딸기 티라미수의 달콤한 순간", "오늘의 디저트 한 조각"],
            "body_copies": ["수제 딸기 티라미수를 만나보세요."],
            "ctas": ["지금 매장에 들러보세요."],
            "hashtags": ["#생딸기", "#수제티라미수"],
            "image_prompt": "Editorial photography of handmade strawberry tiramisu",
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
                    }
                ],
                "feature_visualization": [
                    {
                        "feature_text": "생딸기 사용",
                        "visual_translation": ["fresh strawberry topping"],
                    }
                ],
                "camera_angle": "45_degree_close_up",
                "composition": "centered_product_hero",
                "lighting": "soft_natural_window_light",
                "background": "minimal_korean_local_cafe",
                "color_palette": ["warm_beige_cream"],
                "depth_of_field": "shallow_depth_of_field",
                "empty_space": "top_20_percent",
                "avoid": ["readable_text"],
            },
            "safety_notes": [],
            "model": "Qwen/Qwen2.5-7B-Instruct",
            "routed_model": "Qwen/Qwen2.5-7B-Instruct",
            "provider": "auto",
            "prompt_version": "ad-copy-v1",
            "latency_ms": 1000,
        }
    )


def test_percentile_interpolates_latency_distribution() -> None:
    assert percentile([100, 200, 300, 400], 0.5) == 250
    assert percentile([100, 200, 300, 400], 0.95) == 385
    assert percentile([], 0.95) is None


def test_quality_metrics_detect_contract_and_context() -> None:
    request = request_fixture()
    response = response_fixture()

    assert context_adherence_score(request, response) == 1.0
    assert hashtag_compliance_rate(response) == 1.0
    assert is_english_image_prompt(response) is True
    assert headline_diversity_score(response) > 0
    assert hallucination_terms(request, response) == []
    assert toxicity_terms(response) == []


def test_hallucination_and_hashtag_violations_are_detected() -> None:
    request = request_fixture()
    response = response_fixture().model_copy(
        update={
            "ctas": ["온라인으로 예약하고 주문하세요."],
            "body_copies": ["건강에 좋은 디저트입니다."],
            "hashtags": ["생딸기", "#공백 태그"],
            "image_prompt": "생딸기 티라미수 광고 이미지",
        }
    )

    assert hallucination_terms(request, response) == ["건강", "예약", "주문"]
    assert hashtag_compliance_rate(response) == 0.0
    assert is_english_image_prompt(response) is False
