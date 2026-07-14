from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from app.modules.ad_copy.schemas import AdCopyRequest, AdCopyResponse


class ImageModel(StrEnum):
    OPENAI_GPT_IMAGE_1_MINI = "openai/gpt-image-1-mini"
    OPENAI_GPT_IMAGE_1 = "openai/gpt-image-1"
    OPENAI_GPT_IMAGE_2 = "openai/gpt-image-2"
    OPENAI_GPT_5_2_IMAGE_TOOL = "openai-responses/gpt-5.2-2025-12-11"
    OPENAI_GPT_5_5_IMAGE_TOOL = "openai-responses/gpt-5.5"
    FLUX_SCHNELL = "black-forest-labs/FLUX.1-schnell"
    SDXL_BASE = "stabilityai/stable-diffusion-xl-base-1.0"
    OPENJOURNEY = "prompthero/openjourney"


class ImageModelAvailability(StrEnum):
    HOSTED = "hosted"
    GATED = "gated"


class ImageModelOption(BaseModel):
    id: ImageModel
    name: str
    provider: str
    availability: ImageModelAvailability
    recommended: bool = False
    note: str


class AdImageRequest(BaseModel):
    model: ImageModel = ImageModel.OPENAI_GPT_IMAGE_1_MINI
    prompt: str = Field(min_length=1, max_length=4000)
    negative_prompt: str | None = Field(default=None, max_length=2000)
    reference_image_data_url: str | None = Field(default=None, max_length=4_000_000)
    width: int = Field(default=1024, ge=512, le=1536)
    height: int = Field(default=1280, ge=512, le=1536)
    guidance_scale: float = Field(default=3.5, ge=1, le=20)
    num_inference_steps: int = Field(default=28, ge=1, le=60)
    seed: int | None = Field(default=None, ge=0, le=2**32 - 1)


class AdImageResponse(BaseModel):
    model: str
    prompt: str
    image_base64: str
    media_type: str
    latency_ms: int


class BlogImageInput(BaseModel):
    id: str = Field(min_length=1, max_length=40)
    name: str = Field(default="", max_length=120)
    data_url: str = Field(min_length=1, max_length=4_000_000)


class AdContentRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    copy_request: AdCopyRequest = Field(alias="copy")
    image_model: ImageModel = ImageModel.OPENAI_GPT_IMAGE_1_MINI
    image_width: int = Field(default=1024, ge=512, le=1536)
    image_height: int = Field(default=1280, ge=512, le=1536)
    reference_image_data_url: str | None = Field(default=None, max_length=4_000_000)
    blog_images: list[BlogImageInput] = Field(default_factory=list, max_length=8)


class AdContentResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    input: dict[str, object] = Field(default_factory=dict)
    ad_copy: dict[str, list[str]] = Field(default_factory=dict)
    copy_result: AdCopyResponse = Field(alias="copy")
    marketing_strategy: dict[str, object] = Field(default_factory=dict)
    channel_recommendation: dict[str, object] = Field(default_factory=dict)
    visual_brief: dict[str, object] = Field(default_factory=dict)
    product_visualization: dict[str, object] = Field(default_factory=dict)
    image: AdImageResponse
    llm_prompt: dict[str, object] = Field(default_factory=dict)
    vision_prompt: dict[str, object] = Field(default_factory=dict)
    image_prompt: str
    negative_prompt: str = ""
    image_url: str = ""
    validation: dict[str, object] = Field(default_factory=dict)
    models: dict[str, str | None] = Field(default_factory=dict)
    artifacts: dict[str, str] = Field(default_factory=dict)
