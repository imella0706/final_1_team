from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from app.core.config import settings

Modality = Literal[
    "text",
    "audio",
    "visual",
    "image",
    "video",
    "behavior",
    "format",
    "copy",
]
UsableAsset = Literal["copy", "image", "video_storyboard"]
AssetNoteKey = Literal[
    "copy",
    "image",
    "video_storyboard",
    "audio",
    "video",
    "text",
    "visual",
    "behavior",
    "format",
]


class TrendCardNotFoundError(ValueError):
    """Raised when the requested trend card ID does not match the local card."""


class TrendCardNotUsableError(ValueError):
    """Raised when the trend card does not support the requested output asset."""


class TrendCardDataError(RuntimeError):
    """Raised when the local trend-card artifact cannot be loaded or validated."""


class TextTransferability(BaseModel):
    """밈 핵심 표현이 원본 영상 없이 텍스트만으로 성립하는지에 대한 판정과 근거."""

    model_config = ConfigDict(extra="forbid")

    standalone_test: Literal["pass", "fail"]
    evidence: list[str] = Field(default_factory=list, max_length=10)


class RightsRisk(BaseModel):
    """가사·상표·인물 어록 등 텍스트 인용 시 권리 위험 수준."""

    model_config = ConfigDict(extra="forbid")

    level: Literal["low", "medium", "high"]
    notes: str = Field(default="", max_length=500)


class TrendMeta(BaseModel):
    """트렌드 수명 주기와 수집 출처. 라우팅/운영용 메타데이터로 LLM에는 전달하지 않는다."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["rising", "active", "fading", "unknown"] = "unknown"
    collected_week: str | None = None
    sources: list[str] = Field(default_factory=list, max_length=20)


class CurationMeta(BaseModel):
    """사람이 직접 작성하고 검수하는 활성 TrendCard의 관리 상태."""

    model_config = ConfigDict(extra="forbid")

    mode: Literal["manual"] = "manual"
    status: Literal["draft", "reviewed"] = "draft"
    notes: str = Field(default="", max_length=500)


class CopyStructure(BaseModel):
    """Data-driven constraints for one application of a text pattern.

    The fields describe *how* a card's copy should be assembled without
    teaching the validator about any particular meme phrase.
    """

    model_config = ConfigDict(extra="forbid")

    subject_source: Literal["primary_product", "any_product", "business_name"]
    subject_position: Literal["before_marker", "unrestricted"] = "unrestricted"
    marker_occurrences: int = Field(default=1, ge=1, le=5)
    reason_source: Literal["input_features", "none"] = "none"
    minimum_reason_count: int = Field(default=0, ge=0, le=5)
    reason_ending: str = Field(default="", max_length=30)

    @model_validator(mode="after")
    def validate_reason_contract(self) -> "CopyStructure":
        if self.reason_source == "input_features":
            if self.minimum_reason_count < 1:
                raise ValueError(
                    "input_features reason_source에는 minimum_reason_count가 필요합니다"
                )
            if not self.reason_ending.strip():
                raise ValueError(
                    "input_features reason_source에는 reason_ending이 필요합니다"
                )
        elif self.minimum_reason_count or self.reason_ending.strip():
            raise ValueError(
                "reason_source가 none이면 reason count와 ending을 지정할 수 없습니다"
            )
        return self


class ContextDanceCopyStructure(BaseModel):
    """상황을 먼저 제시하고 핵심 marker와 선택 호출을 잇는 구조."""

    model_config = ConfigDict(extra="forbid")

    context_source: Literal["campaign_context_or_input_situation"]
    context_position: Literal["before_marker"]
    marker_occurrences: int = Field(default=1, ge=1, le=5)
    marker_variants: list[str] = Field(min_length=1, max_length=10)
    minimum_context_count: int = Field(default=1, ge=1, le=5)
    optional_call_source: Literal["target_audience_or_desired_object"]
    optional_call_position: Literal["after_marker"]
    optional_call_marker: str = Field(min_length=1, max_length=30)


class ComebackRevealCopyStructure(BaseModel):
    """복귀 맥락, 질문 marker, 상품 공개와 특징 근거를 잇는 구조."""

    model_config = ConfigDict(extra="forbid")

    setup_source: Literal["comeback_context"]
    setup_position: Literal["before_marker"]
    marker_template: str = Field(min_length=1, max_length=100)
    marker_occurrences: int = Field(default=1, ge=1, le=5)
    reveal_source: Literal["primary_product"]
    reveal_position: Literal["after_marker"]
    support_source: Literal["input_features"]
    minimum_support_count: int = Field(default=1, ge=1, le=5)
    support_relation: Literal["returned_with"]
    reason_ending: str = Field(min_length=1, max_length=30)


class TemplateRevealCopyStructure(BaseModel):
    """Template marker, reveal, and support contract for broader v2 meme cards."""

    model_config = ConfigDict(extra="forbid")

    setup_source: str = Field(min_length=1, max_length=80)
    setup_position: str = Field(min_length=1, max_length=80)
    marker_template: str = Field(min_length=1, max_length=160)
    marker_occurrences: int = Field(default=1, ge=1, le=5)
    reveal_source: str = Field(min_length=1, max_length=80)
    reveal_position: str = Field(min_length=1, max_length=80)
    support_source: str = Field(min_length=1, max_length=80)
    minimum_support_count: int = Field(default=1, ge=1, le=5)
    support_relation: str = Field(min_length=1, max_length=100)
    reason_ending: str = Field(min_length=1, max_length=40)


TrendCopyStructure: TypeAlias = (
    CopyStructure
    | ContextDanceCopyStructure
    | ComebackRevealCopyStructure
    | TemplateRevealCopyStructure
)


class TrendCard(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["2.0"]
    meme_id: str = Field(
        min_length=1,
        max_length=100,
        pattern=r"^[A-Za-z0-9:_-]+$",
    )
    display_name: str = Field(min_length=1, max_length=200)
    meaning: str = Field(min_length=1, max_length=500)

    # 분류/라우팅 필드: 밈의 정체성이 어떤 모달리티에 있고 어떤 산출물에 쓸 수 있는지.
    modalities: list[Modality] = Field(min_length=1, max_length=5)
    core_asset: Modality
    usable_assets: list[UsableAsset] = Field(min_length=1, max_length=3)
    asset_notes: dict[AssetNoteKey, str] = Field(default_factory=dict)
    text_transferability: TextTransferability
    rights_risk: RightsRisk

    # 생성용 필드: LLM 프롬프트에 선별 주입된다.
    text_patterns: list[str] = Field(default_factory=list, max_length=10)
    copy_markers: list[str] = Field(default_factory=list, max_length=10)
    copy_structure: TrendCopyStructure | None = None
    suitable_channels: list[str] = Field(default_factory=list, max_length=10)
    suitable_tones: list[str] = Field(default_factory=list, max_length=10)
    target_audiences: list[str] = Field(default_factory=list, max_length=20)
    usage_rules: list[str] = Field(default_factory=list, max_length=20)
    prohibited_usage: list[str] = Field(default_factory=list, max_length=20)

    curation_meta: CurationMeta
    trend_meta: TrendMeta = Field(default_factory=TrendMeta)
    is_mock: bool = False

    @model_validator(mode="after")
    def validate_copy_gate(self) -> "TrendCard":
        """copy 자산 게이트: 문구에 쓰려면 독립 텍스트 패턴이 반드시 있어야 한다."""
        if self.core_asset != "copy" and self.core_asset not in self.modalities:
            raise ValueError("core_asset은 modalities에 포함되어야 합니다")
        if "copy" in self.usable_assets:
            if "text" not in self.modalities:
                raise ValueError(
                    "usable_assets에 'copy'가 포함된 카드는 modalities에 "
                    "'text'가 필요합니다"
                )
            if not self.text_patterns:
                raise ValueError(
                    "usable_assets에 'copy'가 포함된 카드는 text_patterns가 "
                    "최소 1개 필요합니다"
                )
            if not self.copy_markers:
                raise ValueError(
                    "usable_assets에 'copy'가 포함된 카드는 copy_markers가 "
                    "최소 1개 필요합니다"
                )
        return self

    def supports(self, asset: str) -> bool:
        return asset in self.usable_assets


REPO_ROOT = Path(__file__).resolve().parents[5]

V3_TREND_CARD_PAYLOAD_PATH = (
    REPO_ROOT
    / "data"
    / "processed"
    / "sns_trend"
    / "v3"
    / "cross_platform_signal_top_candidates"
    / "cross_platform_signal_top_candidates.json"
)

V3_TREND_CARD_PAYLOAD_PATH = (
    REPO_ROOT
    / "data"
    / "processed"
    / "sns_trend"
    / "v3"
    / "cross_platform_signal_top_candidates"
    / "cross_platform_signal_top_candidates.json"
)

DEFAULT_TREND_CARD_PAYLOAD_PATH = (
    REPO_ROOT
    / "data"
    / "processed"
    / "sns_trend"
    / "v2"
    / "cross_platform_signal_top_candidates"
    / "cross_platform_signal_top_candidates.json"
)


def _repo_relative_path(path: Path) -> Path:
    if path.is_absolute():
        return path
    return REPO_ROOT / path


def resolve_trend_card_payload_path(path: Path | None = None) -> Path:
    """명시 경로, 환경설정, 공식 v2 processed 경로 순서로 카드 artifact를 결정한다."""
    if path is not None:
        return path
    if settings.trend_card_payload_path is not None:
        return _repo_relative_path(settings.trend_card_payload_path)
    return DEFAULT_TREND_CARD_PAYLOAD_PATH


def _read_json_artifact(path: Path) -> Any:
    try:
        if path.suffix == ".jsonl":
            return [
                json.loads(line)
                for line in path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise TrendCardDataError(
            "TrendCard artifact를 읽을 수 없습니다: "
            f"{path}. 배포 환경에서는 BRANDMATE_TREND_CARD_PAYLOAD_PATH를 설정하고 "
            "DVC/GCS 동기화 여부를 확인하세요"
        ) from error


def _strip_packaging_fields(raw_card: dict[str, Any]) -> dict[str, Any]:
    allowed_fields = set(TrendCard.model_fields)
    return {
        key: value
        for key, value in raw_card.items()
        if key in allowed_fields
    }


def _validate_raw_card(raw_card: Any, *, path: Path, index: int | None = None) -> TrendCard:
    if not isinstance(raw_card, dict):
        location = f"{path}[{index}]" if index is not None else str(path)
        raise TrendCardDataError(f"TrendCard 항목은 JSON object여야 합니다: {location}")
    try:
        return TrendCard.model_validate(_strip_packaging_fields(raw_card))
    except ValidationError as error:
        location = f"{path}[{index}]" if index is not None else str(path)
        raise TrendCardDataError(f"TrendCard JSON 형식이 올바르지 않습니다: {location}") from error


def _raw_cards_from_artifact(path: Path) -> list[Any]:
    if path.is_dir():
        default_payload = path / "cross_platform_signal_top_candidates.json"
        if default_payload.exists():
            return _raw_cards_from_artifact(default_payload)

        cards: list[Any] = []
        for item in sorted(path.glob("**/*.json")):
            if item.name in {"manifest.json", "description.json"}:
                continue
            cards.append(_read_json_artifact(item))
        return cards

    payload = _read_json_artifact(path)
    if isinstance(payload, dict) and isinstance(payload.get("cards"), list):
        return list(payload["cards"])
    if isinstance(payload, list):
        return payload
    return [payload]


@lru_cache(maxsize=16)
def _load_trend_cards_cached(path_value: str) -> tuple[TrendCard, ...]:
    path = Path(path_value)
    cards = [
        _validate_raw_card(raw_card, path=path, index=index)
        for index, raw_card in enumerate(_raw_cards_from_artifact(path))
    ]
    if not cards:
        raise TrendCardDataError(f"TrendCard artifact가 비어 있습니다: {path}")

    meme_ids = [card.meme_id for card in cards]
    duplicate_ids = sorted({meme_id for meme_id in meme_ids if meme_ids.count(meme_id) > 1})
    if duplicate_ids:
        raise TrendCardDataError(
            "TrendCard artifact에 중복 meme_id가 있습니다: "
            f"{', '.join(duplicate_ids)}"
        )
    return tuple(cards)


def load_trend_cards(*, path: Path | None = None) -> list[TrendCard]:
    """공식 v2 processed payload 또는 명시적으로 전달한 테스트 artifact를 로드한다."""
    resolved_path = resolve_trend_card_payload_path(path).resolve()
    return list(_load_trend_cards_cached(str(resolved_path)))


def _validate_card_gate(
    card: TrendCard,
    *,
    requested_meme_id: str | None,
    require_asset: str | None,
    require_channel: str | None,
    prohibited_terms: list[str] | None,
) -> None:
    card_label = requested_meme_id or card.meme_id
    if require_asset is not None and not card.supports(require_asset):
        raise TrendCardNotUsableError(
            f"TrendCard '{card_label}'는 '{require_asset}' 출력에 사용할 수 없습니다 "
            f"(usable_assets: {', '.join(card.usable_assets)})"
        )
    if require_asset == "copy" and card.text_transferability.standalone_test != "pass":
        raise TrendCardNotUsableError(
            f"TrendCard '{card.meme_id}'는 텍스트 단독 전이가 실패해 copy 출력에 사용할 수 없습니다 "
            f"(standalone_test: {card.text_transferability.standalone_test})"
        )
    if card.curation_meta.status != "reviewed":
        raise TrendCardNotUsableError(
            f"TrendCard '{card.meme_id}'는 수동 검수가 완료되지 않았습니다 "
            f"(curation status: {card.curation_meta.status})"
        )
    if card.rights_risk.level == "high":
        raise TrendCardNotUsableError(
            f"TrendCard '{card.meme_id}'는 권리 위험이 높아 광고 생성에 사용할 수 없습니다"
        )
    if (
        require_channel is not None
        and card.suitable_channels
        and require_channel not in card.suitable_channels
    ):
        raise TrendCardNotUsableError(
            f"TrendCard '{card.meme_id}'는 '{require_channel}' 채널에 적합하지 않습니다 "
            f"(suitable_channels: {', '.join(card.suitable_channels)})"
        )

    normalized_prohibited_terms = [
        term.strip().casefold() for term in (prohibited_terms or []) if term.strip()
    ]
    conflicting_terms = sorted(
        {
            term
            for term in normalized_prohibited_terms
            if any(term in marker.casefold() for marker in card.copy_markers)
        }
    )
    if require_asset == "copy" and conflicting_terms:
        raise TrendCardNotUsableError(
            f"TrendCard '{card.meme_id}'의 필수 표현과 금지 표현이 충돌합니다: "
            f"{', '.join(conflicting_terms)}"
        )


def load_trend_card(
    meme_id: str | None = None,
    *,
    path: Path | None = None,
    require_asset: str | None = "copy",
    require_channel: str | None = None,
    prohibited_terms: list[str] | None = None,
) -> TrendCard:
    cards = load_trend_cards(path=path)
    if meme_id is not None:
        matched = [card for card in cards if card.meme_id == meme_id]
        if not matched:
            raise TrendCardNotFoundError(f"TrendCard를 찾을 수 없습니다: {meme_id}")
        card = matched[0]
        _validate_card_gate(
            card,
            requested_meme_id=meme_id,
            require_asset=require_asset,
            require_channel=require_channel,
            prohibited_terms=prohibited_terms,
        )
        return card

    if cards:
        first_card = cards[0]
        _validate_card_gate(
            first_card,
            requested_meme_id=None,
            require_asset=require_asset,
            require_channel=require_channel,
            prohibited_terms=prohibited_terms,
        )
        return first_card
    else:
        raise TrendCardNotFoundError(f"TrendCard를 찾을 수 없습니다: {meme_id}")
