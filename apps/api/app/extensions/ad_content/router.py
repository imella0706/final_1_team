import asyncio

from fastapi import APIRouter, HTTPException, status

from app.core.config import settings
from app.extensions.ad_content.audio_service import (
    AudioModelNotConfiguredError,
    AudioModelProviderError,
    generate_ad_audio,
    list_audio_provider_statuses,
)
from app.extensions.ad_content.artifact_store import save_ad_content_artifacts
from app.extensions.ad_content.image_validator import validate_generated_image
from app.extensions.ad_content.image_service import (
    ImageModelNotConfiguredError,
    ImageModelProviderError,
    generate_ad_image,
)
from app.extensions.ad_content.image_prompt import describe_blog_images, describe_reference_image
from app.extensions.ad_content.naver_background_prompts import build_naver_background_prompt
from app.extensions.ad_content.naver_image_enhancement import (
    NaverImageEnhancementError,
    NaverImageEnhancementNotConfiguredError,
    enhance_naver_blog_image,
)
from app.extensions.ad_content.models import list_image_model_options
from app.extensions.ad_content.vision_models import list_vision_model_options
from app.extensions.ad_content.vision_service import (
    VisionModelNotConfiguredError,
    VisionModelProviderError,
)
from app.extensions.ad_content.product_visualizer import visualize_products
from app.extensions.ad_content.prompt_normalizer import (
    compact_regenerated_prompt,
    normalize_image_prompt,
)
from app.extensions.ad_content.schemas import (
    AdContentRequest,
    AdContentResponse,
    AdAudioRequest,
    AdAudioResponse,
    AdImageRequest,
    AdImageResponse,
    AudioProviderStatus,
    ImageModelOption,
    VisionModelOption,
)
from app.modules.ad_copy.service import (
    InvalidModelOutputError,
    ModelNotConfiguredError,
    ModelProviderError,
    generate_ad_copy,
)
from app.modules.ad_copy.trend_context import (
    TrendCardDataError,
    TrendCardNotFoundError,
    TrendCardNotUsableError,
)

router = APIRouter(prefix="/ad-content", tags=["ad-content"])

TRANSPARENT_PNG_BASE64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII="
)


def _extract_data_url_image(data_url: str | None) -> tuple[str, str]:
    if data_url and data_url.startswith("data:") and "," in data_url:
        header, encoded = data_url.split(",", 1)
        media_type = header.split(";", 1)[0].removeprefix("data:") or "image/png"
        return encoded, media_type
    return TRANSPARENT_PNG_BASE64, "image/png"


def _uploaded_blog_image_response(request: AdContentRequest) -> AdImageResponse:
    data_url = (
        request.blog_images[0].data_url
        if request.blog_images
        else request.reference_image_data_url
    )
    image_base64, media_type = _extract_data_url_image(data_url)
    return AdImageResponse(
        model="uploaded-blog-photo",
        prompt="Naver Blog channel uses uploaded photos directly. Image generation was skipped.",
        image_base64=image_base64,
        media_type=media_type,
        latency_ms=0,
    )


@router.get("/image-models", response_model=list[ImageModelOption])
async def image_models() -> list[ImageModelOption]:
    return list_image_model_options()


@router.post("/audio/generate", response_model=AdAudioResponse)
async def generate_audio(request: AdAudioRequest) -> AdAudioResponse:
    try:
        return await generate_ad_audio(request)
    except AudioModelNotConfiguredError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(error),
        ) from error
    except AudioModelProviderError as error:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(error),
        ) from error


@router.get("/audio/providers", response_model=list[AudioProviderStatus])
async def audio_providers() -> list[AudioProviderStatus]:
    return await list_audio_provider_statuses()


@router.get("/vision-models", response_model=list[VisionModelOption])
async def vision_models() -> list[VisionModelOption]:
    return list_vision_model_options()


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
        copy_request = request.copy_request
        is_naver_blog = copy_request.channel.value == "naver_blog"
        blog_photo_notes: list[str] = []
        blog_vision_prompt: dict[str, object] = {}
        if is_naver_blog and request.blog_images and request.use_vision_analysis:
            blog_photo_notes, blog_vision_prompt = await describe_blog_images(
                request.blog_images,
                copy_request,
                request.vision_model,
            )
            copy_request = copy_request.model_copy(
                update={"blog_photo_notes": blog_photo_notes}
            )
        elif is_naver_blog and request.blog_images:
            blog_vision_prompt = {
                "analysis_enabled": False,
                "model": request.vision_model.value,
                "image_count": len(request.blog_images),
            }

        copy = await generate_ad_copy(copy_request)

        if is_naver_blog:
            background_prompt = build_naver_background_prompt(copy_request.business_type)
            vision_prompt = {
                "blog_images_prompt": blog_vision_prompt,
                "blog_photo_notes": blog_photo_notes,
                "image_generation": "background_replacement_pending",
                "product_visualization": "original_food_container_preservation_required",
                "background_prompt": background_prompt.prompt,
                "background_template": background_prompt.template,
                "background_business_type": background_prompt.business_type,
            }
            image_prompt = ""
            negative_prompt = ""
            try:
                image = (
                    await asyncio.to_thread(
                        enhance_naver_blog_image, copy_request, request.blog_images[0]
                    )
                    if request.blog_images
                    else _uploaded_blog_image_response(request)
                )
                if request.blog_images:
                    # 파이프라인이 EfficientNet-B0 각도 분류 결과를 반영해 실제 사용한 프롬프트다.
                    vision_prompt["background_prompt"] = image.prompt
                vision_prompt["image_generation"] = "background_replacement_completed"
            except NaverImageEnhancementNotConfiguredError as error:
                image = _uploaded_blog_image_response(request)
                vision_prompt["image_generation"] = "background_replacement_not_configured"
                vision_prompt["image_enhancement_reason"] = str(error)
            except NaverImageEnhancementError as error:
                # 모델·GPU·검증 오류가 있어도 광고 문구 생성 API 자체는 실패시키지 않는다.
                # 원본을 반환하고 응답 메타데이터로 운영자가 원인을 확인할 수 있게 한다.
                image = _uploaded_blog_image_response(request)
                vision_prompt["image_generation"] = "background_replacement_failed_fallback"
                vision_prompt["image_enhancement_reason"] = str(error)
            visual_brief_payload: dict[str, object] = {}
            product_visualization_payload: dict[str, object] = {}
            image_valid = True
            image_warnings: list[str] = []
            regeneration_count = 0
        else:
            product_visualization = await visualize_products(copy_request, copy)
            if request.use_vision_analysis:
                reference_image_context, vision_prompt = await describe_reference_image(
                    request.reference_image_data_url,
                    copy_request,
                    request.vision_model,
                )
                vision_prompt["analysis_enabled"] = True
            else:
                reference_image_context = None
                vision_prompt = {
                    "analysis_enabled": False,
                    "model": request.vision_model.value,
                    "reference_image_provided": bool(request.reference_image_data_url),
                }
            image_prompt, negative_prompt = normalize_image_prompt(
                copy,
                copy_request,
                product_visualization,
                reference_image_context,
            )
            image = await generate_ad_image(
                AdImageRequest(
                    model=request.image_model,
                    prompt=image_prompt,
                    negative_prompt=negative_prompt,
                    reference_image_data_url=request.reference_image_data_url,
                    width=request.image_width,
                    height=request.image_height,
                )
            )
            image_validation = await validate_generated_image(
                image,
                copy_request,
                request.vision_model,
            )
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
                        reference_image_data_url=request.reference_image_data_url,
                        width=request.image_width,
                        height=request.image_height,
                    )
                )
                image_validation = await validate_generated_image(
                    image,
                    copy_request,
                    request.vision_model,
                )
            image_valid = image_validation.valid
            image_warnings = image_validation.warnings
            visual_brief_payload = copy.visual_brief.model_dump(mode="json")
            product_visualization_payload = product_visualization.model_dump(mode="json")
    except (TrendCardNotFoundError, TrendCardNotUsableError) as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(error),
        ) from error
    except (TrendCardDataError, ModelNotConfiguredError) as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(error),
        ) from error
    except ImageModelNotConfiguredError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(error),
        ) from error
    except VisionModelNotConfiguredError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(error),
        ) from error
    except (
        ModelProviderError,
        InvalidModelOutputError,
        ImageModelProviderError,
        VisionModelProviderError,
    ) as error:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(error),
        ) from error

    response = AdContentResponse(
        input=copy_request.model_dump(mode="json"),
        ad_copy={
            "headlines": copy.headlines,
            "body_copies": copy.body_copies,
            "ctas": copy.ctas,
            "hashtags": copy.hashtags,
        },
        copy_result=copy,
        marketing_strategy=copy.marketing_strategy.model_dump(mode="json"),
        channel_recommendation=copy.channel_recommendation.model_dump(mode="json"),
        visual_brief=visual_brief_payload,
        product_visualization=product_visualization_payload,
        image=image,
        llm_prompt=copy.llm_prompt,
        vision_prompt=vision_prompt,
        image_prompt=image_prompt,
        negative_prompt=negative_prompt,
        image_url="",
        validation={
            "input_valid": True,
            "copy_valid": not copy.safety_notes,
            "image_valid": image_valid,
            "regeneration_count": regeneration_count,
            "warnings": copy.safety_notes + image_warnings,
        },
        models={
            "copy_model": copy.model,
            "vision_model": request.vision_model.value,
            "vision_analysis": "enabled" if request.use_vision_analysis else "disabled",
            "image_model": image.model,
            "image_provider": settings.image_provider,
            "image_prompt_template": settings.image_prompt_template,
            "image_validator_model": settings.image_validator_model_name,
        },
    )
    response.artifacts = save_ad_content_artifacts(response)
    return response
