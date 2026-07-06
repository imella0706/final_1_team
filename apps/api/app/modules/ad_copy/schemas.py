from enum import StrEnum

from pydantic import BaseModel, Field


class AdModel(StrEnum):
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
    TEENS = "teens"
    TWENTIES = "twenties"
    OFFICE_WORKERS = "office_workers"
    FAMILIES = "families"
    COUPLES = "couples"


class AdChannel(StrEnum):
    INSTAGRAM = "instagram"
    NAVER_BLOG = "naver_blog"
    DELIVERY_APP = "delivery_app"
    STORE_POSTER = "store_poster"
    OTHER = "other"


class CopyTone(StrEnum):
    EMOTIONAL = "emotional"
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
    target_audiences: list[TargetAudience] = Field(min_length=1, max_length=5)
    tone: CopyTone
    product_names: list[str] = Field(min_length=1, max_length=10)
    features: list[str] = Field(default_factory=list, max_length=10)
    channel: AdChannel
    promotion: str | None = Field(default=None, max_length=300)
    required_terms: list[str] = Field(default_factory=list, max_length=10)
    prohibited_terms: list[str] = Field(default_factory=list, max_length=20)


class AdCopyContent(BaseModel):
    headlines: list[str] = Field(min_length=1, max_length=5)
    body_copies: list[str] = Field(min_length=1, max_length=5)
    ctas: list[str] = Field(min_length=1, max_length=5)
    hashtags: list[str] = Field(min_length=1, max_length=15)
    image_prompt: str = Field(min_length=1, max_length=2000)
    safety_notes: list[str] = Field(default_factory=list, max_length=10)


class AdCopyResponse(AdCopyContent):
    model: str
    routed_model: str
    provider: str
    prompt_version: str
    latency_ms: int
