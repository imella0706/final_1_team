from fastapi import APIRouter, HTTPException, status

from app.modules.ad_copy.models import list_model_options
from app.modules.ad_copy.schemas import AdCopyRequest, AdCopyResponse, ModelOption
from app.modules.ad_copy.service import (
    InvalidModelOutputError,
    ModelNotConfiguredError,
    ModelProviderError,
    generate_ad_copy,
)

router = APIRouter(prefix="/ad-copies", tags=["ad-copies"])


@router.get("/models", response_model=list[ModelOption])
async def models() -> list[ModelOption]:
    return list_model_options()


@router.post("/generate", response_model=AdCopyResponse)
async def generate(request: AdCopyRequest) -> AdCopyResponse:
    try:
        return await generate_ad_copy(request)
    except ModelNotConfiguredError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(error),
        ) from error
    except (ModelProviderError, InvalidModelOutputError) as error:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(error),
        ) from error
