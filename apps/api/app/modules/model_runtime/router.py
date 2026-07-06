from fastapi import APIRouter, HTTPException, status

from app.modules.model_runtime.image.diffusers_service import (
    ImageRuntimeError,
    generate_image,
)
from app.modules.model_runtime.llm.clients import LlmRuntimeError
from app.modules.model_runtime.llm.service import generate_text
from app.modules.model_runtime.schemas import (
    ImageGenerateRequest,
    ImageGenerateResponse,
    LlmGenerateRequest,
    LlmGenerateResponse,
)

router = APIRouter(tags=["model-runtime"])


@router.post("/llm/generate", response_model=LlmGenerateResponse)
async def llm_generate(request: LlmGenerateRequest) -> LlmGenerateResponse:
    try:
        return await generate_text(request)
    except LlmRuntimeError as error:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(error),
        ) from error


@router.post("/image/generate", response_model=ImageGenerateResponse)
async def image_generate(request: ImageGenerateRequest) -> ImageGenerateResponse:
    try:
        return await generate_image(request)
    except ImageRuntimeError as error:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(error),
        ) from error
