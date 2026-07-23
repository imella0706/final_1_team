from __future__ import annotations

from pathlib import Path
from typing import Literal, TypeAlias

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


TrendCopyStructure: TypeAlias = (
    CopyStructure | ContextDanceCopyStructure | ComebackRevealCopyStructure
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
        if self.core_asset not in self.modalities:
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
            if self.text_transferability.standalone_test != "pass":
                raise ValueError(
                    "usable_assets에 'copy'가 포함된 카드는 "
                    "text_transferability.standalone_test가 'pass'여야 합니다"
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
DEFAULT_TREND_CARD_PATH = REPO_ROOT / "gather_data" / "trendcard.json"


def resolve_trend_card_path(path: Path | None = None) -> Path:
    """명시 경로, 환경설정, 저장소 기본 경로 순서로 수동 카드 위치를 결정한다."""
    if path is not None:
        return path
    if settings.trend_card_path is not None:
        configured_path = settings.trend_card_path
        if configured_path.is_absolute():
            return configured_path
        return REPO_ROOT / configured_path
    return DEFAULT_TREND_CARD_PATH


def load_trend_card(
    meme_id: str | None = None,
    *,
    path: Path | None = None,
    require_asset: str | None = "copy",
    require_channel: str | None = None,
    prohibited_terms: list[str] | None = None,
) -> TrendCard:
    resolved_path = resolve_trend_card_path(path)
    try:
        raw_json = resolved_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise TrendCardDataError(
            "TrendCard 파일을 읽을 수 없습니다: "
            f"{resolved_path}. 배포 환경에서는 BRANDMATE_TREND_CARD_PATH를 설정하세요"
        ) from error

    try:
        card = TrendCard.model_validate_json(raw_json)
    except ValidationError as error:
        raise TrendCardDataError(
            f"TrendCard JSON 형식이 올바르지 않습니다: {resolved_path}"
        ) from error

    if meme_id is not None and card.meme_id != meme_id:
        raise TrendCardNotFoundError(f"TrendCard를 찾을 수 없습니다: {meme_id}")

    if require_asset is not None and not card.supports(require_asset):
        raise TrendCardNotUsableError(
            f"TrendCard '{meme_id}'는 '{require_asset}' 출력에 사용할 수 없습니다 "
            f"(usable_assets: {', '.join(card.usable_assets)})"
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
    return card
