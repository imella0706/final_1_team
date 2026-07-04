from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from app.modules.ad_copy.schemas import AdCopyRequest, AdCopyResponse


class ImageModel(StrEnum):
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
    model: ImageModel = ImageModel.FLUX_SCHNELL
    prompt: str = Field(min_length=1, max_length=4000)
    negative_prompt: str | None = Field(default=None, max_length=2000)
    width: int = Field(default=1024, ge=512, le=1536)
    height: int = Field(default=1280, ge=512, le=1536)
    guidance_scale: float = Field(default=3.5, ge=1, le=20)
    num_inference_steps: int = Field(default=28, ge=1, le=60)


class AdImageResponse(BaseModel):
    model: str
    prompt: str
    image_base64: str
    media_type: str
    latency_ms: int


class AdContentRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    copy_request: AdCopyRequest = Field(alias="copy")
    image_model: ImageModel = ImageModel.FLUX_SCHNELL
    image_width: int = Field(default=1024, ge=512, le=1536)
    image_height: int = Field(default=1280, ge=512, le=1536)


class AdContentResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    input: dict[str, object] = Field(default_factory=dict)
    ad_copy: dict[str, list[str]] = Field(default_factory=dict)
    copy_result: AdCopyResponse = Field(alias="copy")
    marketing_strategy: dict[str, object] = Field(default_factory=dict)
    visual_brief: dict[str, object] = Field(default_factory=dict)
    product_visualization: dict[str, object] = Field(default_factory=dict)
    image: AdImageResponse
    image_prompt: str
    negative_prompt: str = ""
    image_url: str = ""
    validation: dict[str, object] = Field(default_factory=dict)
    models: dict[str, str | None] = Field(default_factory=dict)
