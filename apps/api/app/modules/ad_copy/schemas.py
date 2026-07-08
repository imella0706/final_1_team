from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.modules.ad_copy.input_validator import (
    BUSINESS_TYPE_MAP,
    CHANNEL_MAP,
    SITUATION_MAP,
    TONE_MAP,
    normalize_ad_copy_input,
    normalize_age_groups,
    normalize_target_audiences,
)


class AdModel(StrEnum):
    OPENAI_GPT_5_5 = "openai/gpt-5.5"
    OPENAI_GPT_5_4 = "openai/gpt-5.4"
    OPENAI_GPT_5_4_MINI = "openai/gpt-5.4-mini"
    OPENAI_GPT_5_4_NANO = "openai/gpt-5.4-nano"
    OPENAI_GPT_4_1_MINI = "openai/gpt-4.1-mini"
    QWEN_2_5_7B = "Qwen/Qwen2.5-7B-Instruct"
    LLAMA_3_1_8B = "meta-llama/Llama-3.1-8B-Instruct"
    NVIDIA_LLAMA_3_1_8B = "nvidia/meta/llama-3.1-8b-instruct"
    MISTRAL_7B_V03 = "mistralai/Mistral-7B-Instruct-v0.3"
    GEMMA_2_9B = "google/gemma-2-9b-it"
    PHI_4_MINI = "microsoft/Phi-4-mini-instruct"
    SOLAR_10_7B = "upstage/SOLAR-10.7B-Instruct-v1.0"


class ModelAvailability(StrEnum):
    HOSTED = "hosted"
    GATED = "gated"
    LOCAL_ONLY = "local_only"
    RESEARCH_ONLY = "research_only"


class ModelOption(BaseModel):
    id: AdModel
    name: str
    size: str
    provider: str
    availability: ModelAvailability
    note: str
    recommended: bool = False


class BusinessType(StrEnum):
    CAFE = "cafe"
    BAKERY = "bakery"
    DESSERT = "dessert"
    RESTAURANT = "restaurant"
    PUB = "pub"


class AdSituation(StrEnum):
    NEW_MENU = "new_menu"
    DISCOUNT = "discount"
    EVENT = "event"
    DELIVERY = "delivery"
    TAKEOUT = "takeout"
    VISIT = "visit"


class TargetAudience(StrEnum):
    OFFICE_WORKERS = "office_workers"
    FAMILIES = "families"
    COUPLES = "couples"
    SOLO = "solo"


class AgeGroup(StrEnum):
    TEENS = "teens"
    TWENTIES = "twenties"
    THIRTIES = "thirties"
    FORTIES = "forties"
    FIFTIES_PLUS = "fifties_plus"


class AdChannel(StrEnum):
    INSTAGRAM = "instagram"
    NAVER_BLOG = "naver_blog"
    DELIVERY_APP = "delivery_app"
    STORE_POSTER = "store_poster"
    OTHER = "other"


class CopyTone(StrEnum):
    EMOTIONAL = "emotional"
    WITTY = "witty"
    FRIENDLY = "friendly"
    WARM = "warm"
    PLAYFUL = "playful"
    PROFESSIONAL = "professional"
    PREMIUM = "premium"


class AdCopyRequest(BaseModel):
    model: AdModel = AdModel.QWEN_2_5_7B
    business_name: str = Field(min_length=1, max_length=100)
    business_type: BusinessType
    situation: AdSituation
    age_groups: list[AgeGroup] = Field(default_factory=list, max_length=5)
    target_audiences: list[TargetAudience] = Field(default_factory=list, max_length=6)
    tone: CopyTone
    product_names: list[str] = Field(min_length=1, max_length=10)
    features: list[str] = Field(default_factory=list, max_length=10)
    channel: AdChannel
    promotion: str | None = Field(default=None, max_length=300)
    required_terms: list[str] = Field(default_factory=list, max_length=10)
    prohibited_terms: list[str] = Field(default_factory=list, max_length=20)

    @model_validator(mode="before")
    @classmethod
    def normalize_input_values(cls, data):
        if isinstance(data, dict):
            return normalize_ad_copy_input(data)
        return data

    @field_validator("business_type", mode="before")
    @classmethod
    def normalize_business_type(cls, value):
        return BUSINESS_TYPE_MAP.get(value, value) if isinstance(value, str) else value

    @field_validator("situation", mode="before")
    @classmethod
    def normalize_situation(cls, value):
        return SITUATION_MAP.get(value, value) if isinstance(value, str) else value

    @field_validator("target_audiences", mode="before")
    @classmethod
    def normalize_targets(cls, value):
        return normalize_target_audiences(value)

    @field_validator("age_groups", mode="before")
    @classmethod
    def normalize_ages(cls, value):
        return normalize_age_groups(value)

    @field_validator("tone", mode="before")
    @classmethod
    def normalize_tone(cls, value):
        return TONE_MAP.get(value, value) if isinstance(value, str) else value

    @field_validator("channel", mode="before")
    @classmethod
    def normalize_channel(cls, value):
        return CHANNEL_MAP.get(value, value) if isinstance(value, str) else value


class BusinessSummary(BaseModel):
    business_name: str = Field(min_length=1, max_length=100)
    business_type_korean: str = Field(min_length=1, max_length=100)
    situation_korean: str = Field(min_length=1, max_length=100)
    age_groups_korean: list[str] = Field(default_factory=list, max_length=5)
    target_audiences_korean: list[str] = Field(default_factory=list, max_length=6)
    tone_korean: str = Field(min_length=1, max_length=100)
    channel_korean: str = Field(min_length=1, max_length=100)


class MandatoryProduct(BaseModel):
    product_name: str = Field(min_length=1, max_length=100)
    role: Literal["primary", "secondary"]


class MandatoryFeature(BaseModel):
    feature_text: str = Field(min_length=1, max_length=300)
    copy_usage_rule: str = Field(min_length=1, max_length=200)
    visual_usage_rule: str = Field(min_length=1, max_length=200)


class MarketingStrategy(BaseModel):
    business_summary: BusinessSummary
    mandatory_products: list[MandatoryProduct] = Field(min_length=1, max_length=10)
    mandatory_features: list[MandatoryFeature] = Field(default_factory=list, max_length=10)
    core_message: str = Field(min_length=1, max_length=500)
    customer_emotion: str = Field(min_length=1, max_length=300)
    marketing_angle: str = Field(min_length=1, max_length=500)
    recommended_cta_direction: str = Field(min_length=1, max_length=300)
    avoid_points: list[str] = Field(default_factory=list, max_length=10)


class ValidationCheck(BaseModel):
    all_products_included: bool
    all_features_included: bool
    prohibited_terms_used: bool
    visual_brief_uses_enum_only: bool
    hashtags_removed: bool
    language_quality: str = Field(min_length=1, max_length=100)


class ProductToShow(BaseModel):
    product_name: str = Field(min_length=1, max_length=100)
    visual_role: Literal["main", "supporting"]
    must_be_visible: bool = True


class FeatureVisualization(BaseModel):
    feature_text: str = Field(min_length=1, max_length=300)
    visual_translation: list[str] = Field(default_factory=list, max_length=10)


class VisualBrief(BaseModel):
    products_to_show: list[ProductToShow] = Field(min_length=1, max_length=10)
    feature_visualization: list[FeatureVisualization] = Field(default_factory=list, max_length=10)
    camera_angle: Literal[
        "45_degree_close_up",
        "eye_level_close_up",
        "top_down_flat_lay",
        "macro_detail",
        "three_quarter_product_shot",
    ]
    composition: Literal[
        "centered_product_hero",
        "two_product_set",
        "tray_set_composition",
        "rule_of_thirds",
        "poster_with_empty_space",
    ]
    lighting: Literal[
        "soft_natural_window_light",
        "warm_morning_light",
        "warm_afternoon_light",
        "soft_studio_light",
        "cozy_indoor_light",
    ]
    background: Literal[
        "minimal_korean_local_cafe",
        "wooden_cafe_table",
        "clean_bakery_counter",
        "warm_restaurant_table",
        "cozy_pub_table",
    ]
    color_palette: list[
        Literal[
            "warm_beige_cream",
            "soft_pink_peach",
            "brown_cream_gold",
            "fresh_fruit_tones",
            "premium_neutral_tones",
        ]
    ] = Field(min_length=1, max_length=10)
    depth_of_field: Literal[
        "shallow_depth_of_field",
        "medium_depth_of_field",
        "sharp_product_soft_background",
    ]
    empty_space: Literal[
        "top_20_percent",
        "right_25_percent",
        "left_25_percent",
        "upper_right_corner",
        "poster_safe_margin",
    ]
    avoid: list[str] = Field(default_factory=list, max_length=10)


class AdCopyContent(BaseModel):
    marketing_strategy: MarketingStrategy
    headlines: list[str] = Field(min_length=1, max_length=5)
    body_copies: list[str] = Field(min_length=1, max_length=5)
    ctas: list[str] = Field(min_length=1, max_length=5)
    hashtags: list[str] = Field(default_factory=list, max_length=10)
    validation_check: ValidationCheck
    visual_brief: VisualBrief
    safety_notes: list[str] = Field(default_factory=list, max_length=10)


class AdCopyResponse(AdCopyContent):
    model: str
    routed_model: str = ""
    provider: str = ""
    prompt_version: str = ""
    latency_ms: int = 0
    attempts: int = 1
    output_repaired: bool = False
