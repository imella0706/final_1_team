import math
import re
from collections.abc import Iterable
from statistics import mean

from app.modules.ad_copy.schemas import AdCopyRequest, AdCopyResponse


UNSUPPORTED_CLAIM_TERMS = {
    "예약",
    "주문",
    "배송",
    "무료",
    "공짜",
    "1위",
    "유기농",
    "국내산",
    "건강",
    "효능",
    "치료",
    "완치",
    "보장",
    "인증",
    "수상",
}
TOXICITY_TERMS = {
    "혐오",
    "멍청",
    "바보",
    "죽어",
    "꺼져",
    "병신",
    "차별",
}
TONE_MARKERS = {
    "emotional": {"감성", "마음", "순간", "따뜻", "달콤", "여유", "설렘", "추억", "포근"},
    "friendly": {"함께", "만나", "즐겨", "해보세요", "들러", "반가"},
    "warm": {"따뜻", "포근", "정성", "편안", "다정"},
    "playful": {"톡톡", "짜잔", "두근", "재미", "반짝", "취향"},
    "professional": {"전문", "정확", "신뢰", "품질", "체계"},
    "premium": {"고급", "엄선", "특별", "품격", "섬세", "프리미엄"},
}


def percentile(values: Iterable[float], percentile_value: float) -> float | None:
    ordered = sorted(values)
    if not ordered:
        return None
    if len(ordered) == 1:
        return round(ordered[0], 2)

    position = (len(ordered) - 1) * percentile_value
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return round(ordered[lower], 2)
    weight = position - lower
    value = ordered[lower] * (1 - weight) + ordered[upper] * weight
    return round(value, 2)


def output_text(result: AdCopyResponse) -> str:
    return " ".join(
        [
            *result.headlines,
            *result.body_copies,
            *result.ctas,
            *result.hashtags,
            result.image_prompt,
        ]
    )


def context_adherence_score(
    request: AdCopyRequest,
    result: AdCopyResponse,
) -> float:
    text = output_text(result).lower()
    components: list[float] = []

    product_scores = []
    for product in request.product_names:
        tokens = [token for token in re.split(r"[\s,/]+", product.lower()) if token]
        if tokens:
            product_scores.append(sum(token in text for token in tokens) / len(tokens))
    if product_scores:
        components.append(mean(product_scores))

    if request.required_terms:
        components.append(
            sum(term.lower() in text for term in request.required_terms)
            / len(request.required_terms)
        )

    if request.prohibited_terms:
        components.append(
            1
            - (
                sum(term.lower() in text for term in request.prohibited_terms)
                / len(request.prohibited_terms)
            )
        )

    return round(mean(components) if components else 1.0, 4)


def hallucination_terms(
    request: AdCopyRequest,
    result: AdCopyResponse,
) -> list[str]:
    source = " ".join(
        [
            request.business_name,
            *request.product_names,
            *request.features,
            request.promotion or "",
        ]
    )
    generated = output_text(result)
    terms = set(UNSUPPORTED_CLAIM_TERMS)

    if request.situation.value in {"delivery", "takeout"} or request.channel.value == (
        "delivery_app"
    ):
        terms.discard("배송")
        terms.discard("주문")

    return sorted(term for term in terms if term in generated and term not in source)


def toxicity_terms(result: AdCopyResponse) -> list[str]:
    generated = output_text(result)
    return sorted(term for term in TOXICITY_TERMS if term in generated)


def tone_manner_proxy_score(
    request: AdCopyRequest,
    result: AdCopyResponse,
) -> float:
    generated = output_text(result)
    markers = TONE_MARKERS[request.tone.value]
    matches = sum(marker in generated for marker in markers)
    return round(min(1.0, matches / 2), 4)


def hashtag_compliance_rate(result: AdCopyResponse) -> float:
    if not result.hashtags:
        return 0.0
    valid = sum(
        hashtag.startswith("#") and not re.search(r"\s", hashtag)
        for hashtag in result.hashtags
    )
    return round(valid / len(result.hashtags), 4)


def is_english_image_prompt(result: AdCopyResponse) -> bool:
    letters = re.findall(r"[A-Za-z가-힣]", result.image_prompt)
    if not letters:
        return False
    english_letters = sum(character.isascii() for character in letters)
    return english_letters / len(letters) >= 0.8


def headline_diversity_score(result: AdCopyResponse) -> float:
    token_sets = [
        set(re.findall(r"[가-힣A-Za-z0-9]+", headline.lower()))
        for headline in result.headlines
    ]
    similarities: list[float] = []
    for index, left in enumerate(token_sets):
        for right in token_sets[index + 1 :]:
            union = left | right
            similarities.append(len(left & right) / len(union) if union else 1.0)
    return round(1 - mean(similarities), 4) if similarities else 0.0
