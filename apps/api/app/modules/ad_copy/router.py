from fastapi import APIRouter, HTTPException, status

from app.modules.ad_copy.models import list_model_options
from app.modules.ad_copy.schemas import (
    AdCopyRequest,
    AdCopyResponse,
    ModelOption,
    TrendCardOption,
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
    list_trend_cards,
)

router = APIRouter(prefix="/ad-copies", tags=["ad-copies"])


@router.get("/models", response_model=list[ModelOption])
async def models() -> list[ModelOption]:
    return list_model_options()


@router.get("/trend-cards", response_model=list[TrendCardOption])
async def trend_cards(channel: str | None = None) -> list[TrendCardOption]:
    return [
        TrendCardOption(
            meme_id=card.meme_id,
            display_name=card.display_name,
            meaning=card.meaning,
            copy_markers=card.copy_markers,
            suitable_channels=card.suitable_channels,
            suitable_tones=card.suitable_tones,
            usage_rules=card.usage_rules,
            prohibited_usage=card.prohibited_usage,
            rights_risk_level=card.rights_risk.level,
            rights_risk_notes=card.rights_risk.notes,
            is_mock=card.is_mock,
        )
        for card in list_trend_cards(require_channel=channel)
    ]


@router.post("/generate", response_model=AdCopyResponse)
async def generate(request: AdCopyRequest) -> AdCopyResponse:
    try:
        return await generate_ad_copy(request)
    except (TrendCardNotFoundError, TrendCardNotUsableError) as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(error),
        ) from error
    except TrendCardDataError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(error),
        ) from error
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
