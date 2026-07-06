"""Print comparable ad-copy outputs from every configured model."""

import asyncio
import sys

from app.modules.ad_copy.models import MODEL_CATALOG
from app.modules.ad_copy.schemas import AdCopyRequest
from app.modules.ad_copy.service import generate_ad_copy


BASE_REQUEST = {
    "business_name": "오후의 조각",
    "business_type": "cafe",
    "situation": "new_menu",
    "target_audiences": ["twenties", "office_workers"],
    "tone": "emotional",
    "product_names": ["수제 딸기 티라미수", "런치세트"],
    "features": ["매일 직접 만든 디저트", "신선한 딸기 사용"],
    "channel": "instagram",
    "promotion": "7월 한정 10% 할인",
    "required_terms": ["생딸기"],
    "prohibited_terms": ["최고", "무조건", "인생 맛집"],
}


async def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    for spec in MODEL_CATALOG:
        print(f"\n## {spec.name} ({spec.provider})", flush=True)
        request = AdCopyRequest.model_validate({**BASE_REQUEST, "model": spec.id})
        try:
            result = await generate_ad_copy(request)
        except RuntimeError as error:
            print(f"- 실패: {error}", flush=True)
            continue

        print(f"- 호출시간: {result.latency_ms / 1000:.2f}초")
        print(f"- 핵심 문구: {' / '.join(result.headlines)}")
        print(f"- CTA: {' / '.join(result.ctas)}")
        print(f"- 해시태그: {' '.join(result.hashtags)}")
        print(f"- 이미지 프롬프트: {result.image_prompt}")
        if result.safety_notes:
            print(f"- 주의사항: {' / '.join(result.safety_notes)}")


if __name__ == "__main__":
    asyncio.run(main())
