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
            "headlines": ["생딸기 티라미수의 달콤한 순간", "오늘의 디저트 한 조각"],
            "body_copies": ["수제 딸기 티라미수를 만나보세요."],
            "ctas": ["지금 매장에 들러보세요."],
            "hashtags": ["#생딸기", "#수제티라미수"],
            "image_prompt": "Editorial photography of handmade strawberry tiramisu",
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
