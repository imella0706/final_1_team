import json

import pytest
from pydantic import ValidationError

from app.core.config import settings
from app.modules.ad_copy.trend_context import (
    TrendCard,
    TrendCardNotFoundError,
    TrendCardNotUsableError,
    load_trend_cards,
    list_trend_cards,
    load_trend_card,
)


def test_load_trend_card_from_processed_v2_payload() -> None:
    card = load_trend_card("gogumafarm:1bf390d89536004b")

    assert isinstance(card, TrendCard)
    assert card.schema_version == "2.0"
    assert card.meme_id == "gogumafarm:1bf390d89536004b"
    assert card.display_name == "니가 좋아💖"
    assert card.modalities == ["audio", "text"]
    assert card.core_asset == "text"
    assert card.usable_assets == ["copy", "video_storyboard"]
    assert card.text_transferability.standalone_test == "pass"
    assert card.rights_risk.level == "low"
    assert card.text_patterns == [
        "{대표상품} 니가 좋아~\n{입력특징1}, 그래서 좋아~\n{입력특징2}, 그래서 좋아~",
        "{대표상품} 니가 좋아~ {입력특징1}, 그래서 좋아~ {입력특징2}, 그래서 좋아~",
    ]
    assert card.copy_markers == ["니가 좋아"]
    assert card.copy_structure is not None
    assert card.copy_structure.subject_source == "primary_product"
    assert card.copy_structure.subject_position == "before_marker"
    assert card.copy_structure.marker_occurrences == 1
    assert card.copy_structure.reason_source == "input_features"
    assert card.copy_structure.minimum_reason_count == 2
    assert card.copy_structure.reason_ending == "좋아"
    assert card.curation_meta.mode == "manual"
    assert card.curation_meta.status == "reviewed"
    assert card.trend_meta.collected_week == "2026-W28"
    assert card.is_mock is True


def test_load_trend_cards_from_processed_v2_payload() -> None:
    cards = load_trend_cards()

    assert len(cards) == 20
    assert {card.meme_id for card in cards} >= {
        "gogumafarm:1bf390d89536004b",
        "gogumafarm:d4e6309980c15a81",
        "manual:prison-comeback",
    }


def test_load_current_manually_curated_card_without_id() -> None:
    card = load_trend_card()

    assert card.meme_id == "gogumafarm:1bf390d89536004b"


def test_list_trend_cards_returns_reviewed_instagram_catalog() -> None:
    cards = list_trend_cards(require_channel="instagram")

    assert {card.meme_id for card in cards} >= {
        "gogumafarm:1bf390d89536004b",
        "gogumafarm:d4e6309980c15a81",
        "manual:prison-comeback",
    }


def test_load_trend_card_by_catalog_id() -> None:
    card = load_trend_card(
        "manual:prison-comeback",
        require_channel="instagram",
    )

    assert card.display_name == "감옥에서 누가 돌아왔게~"


def test_load_trend_card_rejects_mismatched_id() -> None:
    with pytest.raises(TrendCardNotFoundError, match="unknown_meme"):
        load_trend_card("unknown_meme")


def test_load_trend_card_rejects_unsupported_asset() -> None:
    with pytest.raises(TrendCardNotUsableError, match="image"):
        load_trend_card("gogumafarm:1bf390d89536004b", require_asset="image")


def _behavior_meme_card(**overrides: object) -> dict[str, object]:
    """copy 자산이 없는 행동 밈 카드 예시 (숏폼 전용)."""
    base: dict[str, object] = {
        "schema_version": "2.0",
        "meme_id": "test:dog_dance",
        "display_name": "코 맞고 강아지 춤",
        "meaning": "코를 맞은 뒤 강아지처럼 춤을 추는 숏폼 챌린지 밈.",
        "modalities": ["audio", "behavior"],
        "core_asset": "behavior",
        "usable_assets": ["video_storyboard"],
        "text_transferability": {"standalone_test": "fail", "evidence": []},
        "rights_risk": {"level": "medium", "notes": ""},
        "text_patterns": [],
        "copy_markers": [],
        "curation_meta": {"mode": "manual", "status": "reviewed"},
    }
    base.update(overrides)
    return base


def test_behavior_meme_without_text_patterns_is_valid() -> None:
    card = TrendCard.model_validate(_behavior_meme_card())

    assert card.supports("copy") is False
    assert card.supports("video_storyboard") is True


def test_copy_card_requires_text_patterns() -> None:
    with pytest.raises(ValidationError, match="text_patterns"):
        TrendCard.model_validate(
            _behavior_meme_card(
                modalities=["text"],
                core_asset="text",
                usable_assets=["copy"],
                text_transferability={"standalone_test": "pass", "evidence": []},
            )
        )


def test_copy_gate_rejects_failed_standalone_transfer(tmp_path) -> None:
    card = TrendCard.model_validate(
        _behavior_meme_card(
            modalities=["text"],
            core_asset="text",
            usable_assets=["copy"],
            text_patterns=["멍하니 좋아, {메뉴}"],
            copy_markers=["좋아"],
        )
    )
    path = tmp_path / "failed-standalone-card.json"
    path.write_text(json.dumps(card.model_dump(), ensure_ascii=False), encoding="utf-8")

    with pytest.raises(TrendCardNotUsableError, match="텍스트 단독 전이"):
        load_trend_card(card.meme_id, path=path, require_asset="copy")


def test_copy_card_requires_explicit_validation_marker() -> None:
    with pytest.raises(ValidationError, match="copy_markers"):
        TrendCard.model_validate(
            _behavior_meme_card(
                modalities=["text"],
                core_asset="text",
                usable_assets=["copy"],
                text_transferability={"standalone_test": "pass", "evidence": []},
                text_patterns=["멍하니 좋아, {메뉴}"],
            )
        )


def test_copy_structure_rejects_feature_reasons_without_ending() -> None:
    with pytest.raises(ValidationError, match="reason_ending"):
        TrendCard.model_validate(
            _behavior_meme_card(
                modalities=["text"],
                core_asset="text",
                usable_assets=["copy"],
                text_transferability={"standalone_test": "pass", "evidence": []},
                text_patterns=["{상품} {marker}"],
                copy_markers=["좋아"],
                copy_structure={
                    "subject_source": "primary_product",
                    "subject_position": "before_marker",
                    "marker_occurrences": 1,
                    "reason_source": "input_features",
                    "minimum_reason_count": 2,
                    "reason_ending": "",
                },
            )
        )


def test_core_asset_must_be_one_of_modalities() -> None:
    with pytest.raises(ValidationError, match="core_asset"):
        TrendCard.model_validate(
            _behavior_meme_card(core_asset="visual")
        )


def test_load_trend_card_rejects_incompatible_channel() -> None:
    with pytest.raises(TrendCardNotUsableError, match="naver_blog"):
        load_trend_card(require_channel="naver_blog")


def test_load_trend_card_rejects_conflicting_prohibited_term() -> None:
    with pytest.raises(TrendCardNotUsableError, match="금지 표현이 충돌"):
        load_trend_card(prohibited_terms=["좋아"])


def test_load_trend_card_uses_configured_payload_path(monkeypatch, tmp_path) -> None:
    source_card = load_trend_card()
    configured_path = tmp_path / "active-trendcard.json"
    configured_path.write_text(
        source_card.model_dump_json(indent=2),
        encoding="utf-8",
    )
    monkeypatch.setattr(settings, "trend_card_payload_path", configured_path)

    loaded = load_trend_card()

    assert loaded.meme_id == source_card.meme_id
