from pathlib import Path

import pytest

from app.evaluation.meme_schemas import (
    MemeJudgeComebackRevealCopyStructure,
    MemeJudgeContextDanceCopyStructure,
)
from app.evaluation.text_judge import build_meme_judge_input, build_meme_judge_messages
from app.modules.ad_copy.output_validator import (
    _trend_structure_failures,
    build_fallback_copy,
    validate_copy_output,
)
from app.modules.ad_copy.prompt import build_trend_card_prompt_block
from app.modules.ad_copy.schemas import AdCopyRequest
from app.modules.ad_copy.trend_context import (
    ComebackRevealCopyStructure,
    ContextDanceCopyStructure,
    CopyStructure,
    load_trend_card,
)


REPO_ROOT = Path(__file__).resolve().parents[3]
TREND_CARD_V2_ROOT = (
    REPO_ROOT
    / "data"
    / "curated"
    / "sns_trend"
    / "v2"
    / "meme_cards_reviewed"
)
TREND_CARD_FIXTURES = {
    "feature_reason": TREND_CARD_V2_ROOT / "gogumafarm" / "gogumafarm_1bf390d89536004b.json",
    "context_dance": TREND_CARD_V2_ROOT / "gogumafarm" / "gogumafarm_d4e6309980c15a81.json",
    "comeback_reveal": TREND_CARD_V2_ROOT / "manual" / "manual_prison-comeback.json",
}


def _request() -> AdCopyRequest:
    return AdCopyRequest.model_validate(
        {
            "business_name": "동네봄 카페",
            "business_type": "cafe",
            "situation": "new_menu",
            "age_groups": ["twenties"],
            "target_audiences": ["college_students"],
            "tone": "playful",
            "product_names": ["수제 딸기 티라미수"],
            "features": ["매일 손질한 생딸기", "직접 만든 딸기청"],
            "channel": "instagram",
            "promotion": "재입고",
            "required_terms": ["생딸기"],
            "prohibited_terms": ["최고"],
        }
    )


@pytest.mark.parametrize(
    ("variant", "structure_type", "required_modality", "asset_note"),
    [
        ("feature_reason", CopyStructure, "text", "copy"),
        ("context_dance", ContextDanceCopyStructure, "video", "audio"),
        ("comeback_reveal", ComebackRevealCopyStructure, "image", "image"),
    ],
)
def test_all_trend_card_shapes_load_without_losing_media_fields(
    variant: str,
    structure_type: type,
    required_modality: str,
    asset_note: str,
) -> None:
    card = load_trend_card(
        path=TREND_CARD_FIXTURES[variant],
        require_asset="copy",
        require_channel="instagram",
    )

    assert isinstance(card.copy_structure, structure_type)
    assert required_modality in card.modalities
    assert asset_note in card.asset_notes


def test_context_dance_validator_checks_context_core_marker_and_optional_call() -> None:
    request = _request()
    card = load_trend_card(path=TREND_CARD_FIXTURES["context_dance"])

    valid = (
        "재입고를 기다리는 중인데 파라파라나 춰야지~\n"
        "대학생~ 오이데~"
    )
    invalid = "오이데~ 파라파라나 춰야지~ 파라파라나 춰야겠다~"

    assert _trend_structure_failures(
        valid, request, card, scope="test"
    ) == []
    codes = {
        code
        for code, _ in _trend_structure_failures(
            invalid, request, card, scope="test"
        )
    }
    assert "trend_marker_count_invalid_in_test" in codes
    assert "trend_context_count_insufficient_in_test" in codes
    assert "trend_optional_call_not_after_marker_in_test" in codes


def test_comeback_validator_checks_setup_reveal_and_grounded_support() -> None:
    request = _request()
    card = load_trend_card(path=TREND_CARD_FIXTURES["comeback_reveal"])

    valid = (
        "품절에서~ 누가 돌아왔게~?\n"
        "그래, 수제 딸기 티라미수 돌아왔다~\n"
        "매일 손질한 생딸기, 갖추고 돌아왔다~"
    )
    missing_reveal = (
        "품절에서~ 누가 돌아왔게~?\n"
        "매일 손질한 생딸기, 갖추고 돌아왔다~"
    )
    missing_support = (
        "품절에서~ 누가 돌아왔게~?\n"
        "그래, 수제 딸기 티라미수 돌아왔다~"
    )

    assert _trend_structure_failures(
        valid, request, card, scope="test"
    ) == []
    reveal_codes = {
        code
        for code, _ in _trend_structure_failures(
            missing_reveal, request, card, scope="test"
        )
    }
    support_codes = {
        code
        for code, _ in _trend_structure_failures(
            missing_support, request, card, scope="test"
        )
    }
    assert "trend_reveal_missing_after_marker_in_test" in reveal_codes
    assert "trend_support_count_insufficient_in_test" in support_codes
    assert "trend_support_not_grounded_in_test" in support_codes


@pytest.mark.parametrize(
    ("variant", "judge_structure_type", "rubric_term"),
    [
        (
            "context_dance",
            MemeJudgeContextDanceCopyStructure,
            "optional_call_marker",
        ),
        (
            "comeback_reveal",
            MemeJudgeComebackRevealCopyStructure,
            "support_source",
        ),
    ],
)
def test_new_structures_survive_prompt_judge_and_fallback_validation(
    variant: str,
    judge_structure_type: type,
    rubric_term: str,
) -> None:
    request = _request()
    card = load_trend_card(path=TREND_CARD_FIXTURES[variant])
    content = build_fallback_copy(request, [], card)

    assert validate_copy_output(content, request, card).valid is True
    prompt = build_trend_card_prompt_block(card, channel="instagram")
    assert rubric_term in prompt

    judge_input = build_meme_judge_input(request, card, content)
    assert isinstance(judge_input.trend_context.copy_structure, judge_structure_type)
    serialized = judge_input.model_dump(mode="json")
    assert rubric_term in serialized["trend_context"]["copy_structure"]
    judge_prompt = "\n".join(
        message["content"] for message in build_meme_judge_messages(judge_input)
    )
    assert "context_source/context_position/marker_variants" in judge_prompt
    assert "setup_source/marker_template/reveal_source/support_source" in judge_prompt
