import asyncio
from pathlib import Path

import pytest

from app.modules.ad_copy.output_validator import (
    build_fallback_copy,
    validate_copy_output,
)
from app.modules.ad_copy.schemas import AdCopyContent, AdCopyRequest
from app.modules.ad_copy.service import InvalidModelOutputError, generate_ad_copy
from app.modules.ad_copy.trend_context import load_trend_card


REPO_ROOT = Path(__file__).resolve().parents[3]
TREND_CARD_FIXTURE = (
    REPO_ROOT
    / "data"
    / "curated"
    / "sns_trend"
    / "v2"
    / "meme_cards_reviewed"
    / "gogumafarm"
    / "gogumafarm_d4e6309980c15a81.json"
)


def _request(promotion: str) -> AdCopyRequest:
    return AdCopyRequest.model_validate(
        {
            "business_name": "모퉁이온도",
            "business_type": "cafe",
            "situation": "new_menu",
            "age_groups": ["twenties"],
            "target_audiences": ["college_students"],
            "tone": "playful",
            "product_names": ["청포도 요거트 스무디"],
            "features": ["청포도 과육 사용", "요거트 베이스"],
            "channel": "instagram",
            "promotion": promotion,
            "required_terms": ["청포도 과육"],
            "prohibited_terms": [],
        }
    )


def test_context_dance_fallback_rejects_internal_audience_summary() -> None:
    promotion = (
        "성별 타겟: 전체 / 직업군: 학생 / 타겟: 대학생 / "
        "제품가격: 6,500원 / 관심사: 디저트, 카페 / 지역: 서울 연남동 / "
        "상권: 대학가 / 세부 타겟: 신메뉴를 기다리는 20대 학생"
    )
    request = _request(promotion)
    card = load_trend_card(path=TREND_CARD_FIXTURE, require_channel="instagram")

    content = build_fallback_copy(request, ["test fallback"], card)
    recommendation = content.channel_recommendation

    assert content.headlines[0] == "새 메뉴가 생각나는 순간인데 파라파라나 춰야지~"
    assert "성별 타겟:" not in recommendation.caption
    assert "세부 타겟:" not in recommendation.caption
    assert len(recommendation.overlay_headline) <= 100
    assert len(recommendation.publish_title) <= 150
    assert validate_copy_output(content, request, card).valid is True


def test_context_dance_fallback_preserves_marker_with_long_campaign_context() -> None:
    promotion = ("여름 신메뉴 출시를 기다리는 고객을 위한 특별한 캠페인 상황 " * 6).strip()[:300]
    request = _request(promotion)
    card = load_trend_card(path=TREND_CARD_FIXTURE, require_channel="instagram")

    content = build_fallback_copy(request, ["test fallback"], card)
    recommendation = content.channel_recommendation

    assert content.headlines[0].endswith("인데 파라파라나 춰야지~")
    assert content.headlines[0].count("파라파라나 춰야지") == 1
    assert len(content.headlines[0]) <= 100
    assert len(recommendation.overlay_headline) <= 100
    assert len(recommendation.publish_title) <= 150
    assert validate_copy_output(content, request, card).valid is True


def test_context_dance_fallback_keeps_real_context_before_internal_metadata() -> None:
    promotion = "7월 신메뉴 공개 / 성별 타겟: 전체 / 타겟: 대학생 / 지역: 서울 마포구"
    request = _request(promotion)
    card = load_trend_card(path=TREND_CARD_FIXTURE, require_channel="instagram")

    content = build_fallback_copy(request, ["test fallback"], card)

    assert content.headlines[0] == "7월 신메뉴 공개인데 파라파라나 춰야지~"
    assert "성별 타겟:" not in content.channel_recommendation.caption
    assert validate_copy_output(content, request, card).valid is True


def test_generate_invalid_model_output_returns_safe_context_dance_fallback(
    monkeypatch,
) -> None:
    promotion = (
        "성별 타겟: 전체 / 직업군: 학생 / 타겟: 대학생 / "
        "제품가격: 6,500원 / 관심사: 디저트, 카페 / 지역: 서울 연남동 / "
        "상권: 대학가 / 세부 타겟: 신메뉴를 기다리는 20대 학생"
    )
    request = _request(promotion)
    card = load_trend_card(path=TREND_CARD_FIXTURE, require_channel="instagram")

    async def invalid_model_response(*args, **kwargs) -> str:
        del args, kwargs
        return '{"invalid":"model output"}'

    monkeypatch.setattr(
        "app.modules.ad_copy.service._call_model",
        invalid_model_response,
    )
    monkeypatch.setattr(
        "app.modules.ad_copy.service.load_trend_card",
        lambda *args, **kwargs: card,
    )

    result = asyncio.run(generate_ad_copy(request))

    assert result.attempts == 2
    assert result.output_repaired is True
    assert result.headlines[0] == "새 메뉴가 생각나는 순간인데 파라파라나 춰야지~"
    assert len(result.channel_recommendation.overlay_headline) <= 100
    assert "성별 타겟:" not in result.channel_recommendation.caption
    assert validate_copy_output(result, request, card).valid is True


def test_generate_wraps_fallback_schema_error(monkeypatch) -> None:
    request = _request("성별 타겟: 전체 / 타겟: 대학생")
    card = load_trend_card(path=TREND_CARD_FIXTURE, require_channel="instagram")

    async def invalid_model_response(*args, **kwargs) -> str:
        del args, kwargs
        return '{"invalid":"model output"}'

    def invalid_fallback(*args, **kwargs):
        del args, kwargs
        return AdCopyContent.model_validate({})

    monkeypatch.setattr(
        "app.modules.ad_copy.service._call_model",
        invalid_model_response,
    )
    monkeypatch.setattr(
        "app.modules.ad_copy.service.load_trend_card",
        lambda *args, **kwargs: card,
    )
    monkeypatch.setattr(
        "app.modules.ad_copy.service.build_fallback_copy",
        invalid_fallback,
    )

    with pytest.raises(
        InvalidModelOutputError,
        match="fallback 광고 문구가 출력 스키마를 충족하지 못했습니다",
    ):
        asyncio.run(generate_ad_copy(request))
