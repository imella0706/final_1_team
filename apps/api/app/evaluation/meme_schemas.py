"""Schemas used by the text-only meme advertising judge."""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator


Score = Annotated[int, Field(ge=1, le=5)]
NonEmptyText = Annotated[str, Field(min_length=1, max_length=300)]


class MemeJudgeRequestFacts(BaseModel):
    """User-supplied facts that the judge may use as evidence."""

    model_config = ConfigDict(extra="forbid")

    business_name: str
    business_type: str
    situation: str
    age_groups: list[str]
    target_audiences: list[str]
    tone: str
    product_names: list[str]
    features: list[str]
    channel: str
    promotion: str | None
    required_terms: list[str]
    prohibited_terms: list[str]
    gender: str | None
    occupation_group: str | None
    product_price: str | None
    interests: list[str]
    region: str | None
    trade_area: str | None
    audience_detail: str | None
    blog_purpose: str | None
    blog_emphasis: list[str]
    blog_style: str | None
    seo_keywords: list[str]
    blog_length: str | None
    additional_request: str | None
    operating_info: str | None
    blog_photo_notes: list[str]


class MemeJudgeTrendContext(BaseModel):
    """The allow-listed TrendCard fields visible to the judge."""

    model_config = ConfigDict(extra="forbid")

    meaning: str
    text_patterns: list[str]
    usage_rules: list[str]
    prohibited_usage: list[str]
    copy_markers: list[str]


class MemeJudgeVisibleResult(BaseModel):
    """Only copy that can be shown to an advertisement customer or reader."""

    model_config = ConfigDict(extra="forbid")

    headlines: list[str]
    body_copies: list[str]
    ctas: list[str]
    hashtags: list[str]
    overlay_headline: str
    caption: str
    publish_cta: str
    publish_hashtags: list[str]
    publish_title: str
    publish_body: str
    blog_title: str
    blog_section_texts: list[str]


class MemeJudgeInput(BaseModel):
    """Complete, deliberately allow-listed input sent to the judge."""

    model_config = ConfigDict(extra="forbid")

    request_facts: MemeJudgeRequestFacts
    trend_context: MemeJudgeTrendContext
    operational_requirements: list[NonEmptyText] = Field(min_length=1, max_length=20)
    customer_visible_result: MemeJudgeVisibleResult


class MemeJudgeResult(BaseModel):
    """Validated judge scores with a deterministic overall score."""

    model_config = ConfigDict(extra="forbid")

    naturalness: Score
    pattern_fidelity: Score
    product_relevance: Score
    factuality: Score
    channel_readiness: Score
    hard_failures: list[NonEmptyText] = Field(max_length=10)
    reason: str = Field(min_length=1, max_length=1000)

    @field_validator("hard_failures", mode="before")
    @classmethod
    def normalize_hard_failures(cls, values: object) -> object:
        if isinstance(values, list):
            return [value.strip() if isinstance(value, str) else value for value in values]
        return values

    @field_validator("reason", mode="before")
    @classmethod
    def normalize_reason(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @computed_field(return_type=float)
    @property
    def overall_score(self) -> float:
        scores = (
            self.naturalness,
            self.pattern_fidelity,
            self.product_relevance,
            self.factuality,
            self.channel_readiness,
        )
        return round(sum(scores) / len(scores), 2)
