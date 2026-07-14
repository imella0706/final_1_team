from enum import StrEnum

from pydantic import BaseModel, Field


class TextRuntimeProvider(StrEnum):
    HUGGING_FACE_ROUTER = "huggingface_router"
    OPENAI = "openai"
    NVIDIA = "nvidia"
    LM_STUDIO = "lm_studio"
    OLLAMA = "ollama"
    VLLM = "vllm"


class ImageRuntimeProvider(StrEnum):
    DIFFUSERS = "diffusers"
    OPENAI = "openai"


class LlmGenerateRequest(BaseModel):
    model: str = Field(min_length=1)
    prompt: str = Field(min_length=1, max_length=8000)
    system_prompt: str | None = Field(default=None, max_length=2000)
    temperature: float = Field(default=0.7, ge=0, le=2)
    max_tokens: int = Field(default=800, ge=1, le=4096)


class LlmGenerateResponse(BaseModel):
    model: str
    provider: TextRuntimeProvider
    content: str
    latency_ms: int


class ImageGenerateRequest(BaseModel):
    model: str = Field(min_length=1)
    prompt: str = Field(min_length=1, max_length=2000)
    negative_prompt: str | None = Field(default=None, max_length=1000)
    width: int = Field(default=1024, ge=256, le=1536)
    height: int = Field(default=1024, ge=256, le=1536)
    num_inference_steps: int = Field(default=28, ge=1, le=80)
    guidance_scale: float = Field(default=7.0, ge=0, le=20)


class ImageGenerateResponse(BaseModel):
    model: str
    provider: ImageRuntimeProvider
    image_base64: str
    media_type: str
    latency_ms: int
