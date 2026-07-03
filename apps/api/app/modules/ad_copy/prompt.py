from app.modules.ad_copy.schemas import AdCopyRequest

PROMPT_VERSION = "ad-copy-v1"


def build_prompt(request: AdCopyRequest) -> str:
    """Build the first Korean advertising-copy prompt."""
    products = ", ".join(request.product_names)
    features = "\n".join(f"- {feature}" for feature in request.features) or "- 별도 입력 없음"
    targets = ", ".join(target.value for target in request.target_audiences)
    required_terms = ", ".join(request.required_terms) or "없음"
    prohibited_terms = ", ".join(request.prohibited_terms) or "없음"
    promotion = request.promotion or "없음"

    return f"""당신은 한국 소상공인을 돕는 광고 카피라이터입니다.
입력에 없는 가격, 효능, 수치, 수상 경력을 지어내지 마세요.
과장되거나 기만적인 표현을 피하고 지정된 JSON 형식으로만 답하세요.

[매장과 상품]
상호명: {request.business_name}
업종: {request.business_type.value}
상황: {request.situation.value}
상품/서비스: {products}
핵심 특징:
{features}
목표 고객: {targets}
게시 채널: {request.channel.value}
말투: {request.tone.value}
프로모션: {promotion}
필수 표현: {required_terms}
금지 표현: {prohibited_terms}

[출력]
- 서로 다른 핵심 문구 3개
- 서로 다른 본문 문구 3개
- CTA 3개
- 해시태그 5~10개
- 광고 문구와 상품을 반영한 이미지 생성용 영문 프롬프트 1개
- 과장 또는 위험 표현 주의사항

다음 키만 가진 JSON 객체를 출력하세요:
headlines, body_copies, ctas, hashtags, image_prompt, safety_notes
"""
