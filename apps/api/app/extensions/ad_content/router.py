from fastapi import APIRouter, HTTPException, status

from app.extensions.ad_content.image_service import (
    ImageModelNotConfiguredError,
    ImageModelProviderError,
    generate_ad_image,
)
from app.extensions.ad_content.models import list_image_model_options
from app.extensions.ad_content.schemas import (
    AdContentRequest,
    AdContentResponse,
    AdImageRequest,
    AdImageResponse,
    ImageModelOption,
)
from app.modules.ad_copy.service import (
    InvalidModelOutputError,
    ModelNotConfiguredError,
    ModelProviderError,
    generate_ad_copy,
)

router = APIRouter(prefix="/ad-content", tags=["ad-content"])


@router.get("/image-models", response_model=list[ImageModelOption])
async def image_models() -> list[ImageModelOption]:
    return list_image_model_options()


@router.post("/images/generate", response_model=AdImageResponse)
async def generate_image(request: AdImageRequest) -> AdImageResponse:
    try:
        return await generate_ad_image(request)
    except ImageModelNotConfiguredError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(error),
        ) from error
    except ImageModelProviderError as error:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(error),
        ) from error


@router.post("/generate", response_model=AdContentResponse)
async def generate_content(request: AdContentRequest) -> AdContentResponse:
    try:
        copy = await generate_ad_copy(request.copy_request)
        image_prompt = (
            f"{copy.image_prompt}\n\n"
            "Create a commercial advertising image without readable text. "
            "Use appetizing lighting, clear product focus, Korean local shop mood, "
            "premium social media poster composition, no logos, no watermarks."
        )
        image = await generate_ad_image(
            AdImageRequest(
                model=request.image_model,
                prompt=image_prompt,
                width=request.image_width,
                height=request.image_height,
            )
        )
    except ModelNotConfiguredError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(error),
        ) from error
    except ImageModelNotConfiguredError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(error),
        ) from error
    except (ModelProviderError, InvalidModelOutputError, ImageModelProviderError) as error:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(error),
        ) from error

    return AdContentResponse(copy_result=copy, image=image, image_prompt=image_prompt)
