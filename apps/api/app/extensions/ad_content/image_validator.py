from dataclasses import dataclass

from app.core.config import settings
from app.extensions.ad_content.schemas import AdImageResponse
from app.modules.ad_copy.schemas import AdCopyRequest


@dataclass(frozen=True)
class ImageValidationResult:
    valid: bool
    warnings: list[str]
    regeneration_prompt_suffix: str | None = None


async def validate_generated_image(
    image: AdImageResponse,
    copy_request: AdCopyRequest,
) -> ImageValidationResult:
    del image
    if not settings.image_validation_enabled:
        return ImageValidationResult(valid=True, warnings=[])

    if not settings.image_validator_model_name:
        return ImageValidationResult(
            valid=True,
            warnings=[
                "BRANDMATE_IMAGE_VALIDATION_ENABLED=true이지만 "
                "BRANDMATE_IMAGE_VALIDATOR_MODEL_NAME이 없어 이미지 검증을 건너뜁니다."
            ],
        )

    return ImageValidationResult(
        valid=True,
        warnings=[
            "이미지 검증 hook이 활성화되었습니다. 실제 CLIP 유사도 검증 모델 연결은 "
            f"{settings.image_validator_model_name} 기준으로 확장하세요.",
            f"검증 대상 상품: {', '.join(copy_request.product_names)}",
        ],
    )
