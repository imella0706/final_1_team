from fastapi import APIRouter, HTTPException, status

from app.core.config import settings
from app.extensions.ad_content.image_validator import validate_generated_image
from app.extensions.ad_content.image_service import (
    ImageModelNotConfiguredError,
    ImageModelProviderError,
    generate_ad_image,
)
from app.extensions.ad_content.models import list_image_model_options
from app.extensions.ad_content.product_visualizer import visualize_products
from app.extensions.ad_content.prompt_normalizer import (
    compact_regenerated_prompt,
    normalize_image_prompt,
)
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
        product_visualization = await visualize_products(request.copy_request, copy)
        image_prompt, negative_prompt = normalize_image_prompt(
            copy,
            request.copy_request,
            product_visualization,
        )
        image = await generate_ad_image(
            AdImageRequest(
                model=request.image_model,
                prompt=image_prompt,
                negative_prompt=negative_prompt,
                width=request.image_width,
                height=request.image_height,
            )
        )
        image_validation = await validate_generated_image(image, request.copy_request)
        regeneration_count = 0
        if not image_validation.valid and image_validation.regeneration_prompt_suffix:
            regeneration_count = 1
            image_prompt = compact_regenerated_prompt(
                f"{image_prompt}\n\n{image_validation.regeneration_prompt_suffix}"
            )
            image = await generate_ad_image(
                AdImageRequest(
                    model=request.image_model,
                    prompt=image_prompt,
                    negative_prompt=negative_prompt,
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

    return AdContentResponse(
        input=request.copy_request.model_dump(mode="json"),
        ad_copy={
            "headlines": copy.headlines,
            "body_copies": copy.body_copies,
            "ctas": copy.ctas,
        },
        copy_result=copy,
        marketing_strategy=copy.marketing_strategy.model_dump(mode="json"),
        visual_brief=copy.visual_brief.model_dump(mode="json"),
        product_visualization=product_visualization.model_dump(mode="json"),
        image=image,
        image_prompt=image_prompt,
        negative_prompt=negative_prompt,
        image_url="",
        validation={
            "input_valid": True,
            "copy_valid": not copy.safety_notes,
            "image_valid": image_validation.valid,
            "regeneration_count": regeneration_count,
            "warnings": copy.safety_notes + image_validation.warnings,
        },
        models={
            "copy_model": copy.model,
            "image_model": image.model,
            "image_provider": settings.image_provider,
            "image_prompt_template": settings.image_prompt_template,
            "image_validator_model": settings.image_validator_model_name,
        },
    )
