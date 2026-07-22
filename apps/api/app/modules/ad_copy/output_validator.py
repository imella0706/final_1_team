from dataclasses import dataclass, field
import re

from app.modules.ad_copy.schemas import (
    AdCopyContent,
    AdCopyRequest,
    ChannelRecommendation,
    FeatureVisualization,
    MarketingStrategy,
    MandatoryFeature,
    MandatoryProduct,
    ProductToShow,
    ValidationCheck,
    VisualBrief,
)
from app.modules.ad_copy.trend_context import TrendCard


@dataclass(frozen=True)
class CopyValidationResult:
    valid: bool
    warnings: list[str]
    # Machine-readable release-gate reasons. ``warnings`` remains the
    # user-facing/legacy contract; evaluation code should use these codes.
    failure_codes: list[str] = field(default_factory=list)


def _add_failure(
    warnings: list[str],
    failure_codes: list[str],
    code: str,
    warning: str,
) -> None:
    if warning not in warnings:
        warnings.append(warning)
    if code not in failure_codes:
        failure_codes.append(code)


def _normalize_hashtags(values: list[str]) -> list[str]:
    """Return one canonical hashtag per array item, preserving model wording."""

    normalized: list[str] = []
    for value in values:
        for token in re.split(r"[,\s]+", value.strip()):
            cleaned = "".join(
                character
                for character in token.lstrip("#")
                if character.isalnum() or character == "_"
            )
            if not cleaned:
                continue
            hashtag = f"#{cleaned}"
            if hashtag not in normalized:
                normalized.append(hashtag)
    return normalized[:10]


def _compose_instagram_publish_body(
    caption: str,
    publish_cta: str,
    publish_hashtags: list[str],
) -> str:
    caption_part = caption.strip()
    footer = "\n".join(
        part
        for part in (publish_cta.strip(), " ".join(publish_hashtags))
        if part
    )
    return "\n\n".join(part for part in (caption_part, footer) if part)


def normalize_copy_output(
    content: AdCopyContent,
    request: AdCopyRequest,
) -> AdCopyContent:
    """Normalize derived channel fields without inventing advertising facts.

    Instagram ``publish_body`` is a view of the three source fields, not a
    fourth piece of model-authored copy. Rebuilding it here prevents drift such
    as a missing CTA or a translated/mutated hashtag.
    """

    if request.channel.value != "instagram":
        return content

    recommendation = content.channel_recommendation
    caption = recommendation.caption.strip()
    publish_cta = recommendation.publish_cta.strip()
    source_hashtags = recommendation.publish_hashtags or content.hashtags
    publish_hashtags = _normalize_hashtags(source_hashtags)
    publish_body = _compose_instagram_publish_body(
        caption,
        publish_cta,
        publish_hashtags,
    )
    normalized_recommendation = recommendation.model_copy(
        update={
            "caption": caption,
            "publish_cta": publish_cta,
            "publish_hashtags": publish_hashtags,
            "publish_body": publish_body,
        }
    )
    return content.model_copy(
        update={
            "hashtags": publish_hashtags,
            "channel_recommendation": normalized_recommendation,
        }
    )


def build_repair_feedback(result: CopyValidationResult) -> str:
    """Render deterministic validation failures for one constrained retry."""

    if result.valid:
        return ""
    codes = ", ".join(result.failure_codes or ["production_validation_failed"])
    warning_rows = "\n".join(f"- {warning}" for warning in result.warnings)
    return f"실패 코드: {codes}\n수정 사유:\n{warning_rows}"


def _contains_any(text: str, terms: list[str]) -> list[str]:
    return [term for term in terms if term and term in text]


def _trend_markers(card: TrendCard) -> list[str]:
    return sorted(
        {marker.strip().casefold() for marker in card.copy_markers if marker.strip()},
        key=len,
        reverse=True,
    )


def _contains_trend_reference(text: str, card: TrendCard) -> bool:
    normalized = text.casefold()
    return any(marker in normalized for marker in _trend_markers(card))


def _first_sentence(text: str) -> str:
    for part in re.split(r"(?:\r?\n)+|(?<=[.!?。！？])\s+", text.strip()):
        if part.strip():
            return part.strip()
    return ""


def _opening_paragraphs(text: str, limit: int = 3) -> str:
    paragraphs = [
        part.strip()
        for part in re.split(r"(?:\r?\n){2,}", text.strip())
        if part.strip()
    ]
    return "\n".join(paragraphs[:limit])


def _trend_post_warnings(
    content: AdCopyContent,
    channel: str,
    card: TrendCard,
) -> list[str]:
    recommendation = content.channel_recommendation
    warnings: list[str] = []
    if channel == "instagram":
        if not _contains_trend_reference(_first_sentence(recommendation.caption), card):
            warnings.append(
                "선택한 TrendCard가 channel_recommendation.caption의 첫 문장에 "
                f"반영되지 않았습니다: {card.meme_id}"
            )
        caption = recommendation.caption.strip()
        if not caption or caption not in recommendation.publish_body:
            warnings.append(
                "channel_recommendation.publish_body에 Instagram caption 원문이 "
                f"포함되지 않았습니다: {card.meme_id}"
            )
        return warnings
    if channel == "naver_blog":
        if not _contains_trend_reference(
            _opening_paragraphs(recommendation.publish_body), card
        ):
            warnings.append(
                "선택한 TrendCard가 channel_recommendation.publish_body의 도입부에 "
                f"반영되지 않았습니다: {card.meme_id}"
            )
        return warnings

    title_or_opening = (
        f"{recommendation.publish_title} "
        f"{_first_sentence(recommendation.publish_body)}"
    )
    if not _contains_trend_reference(title_or_opening, card):
        warnings.append(
            "선택한 TrendCard가 channel_recommendation.publish_title 또는 "
            f"publish_body의 첫 문장에 반영되지 않았습니다: {card.meme_id}"
        )
    return warnings


def _has_mechanical_product_enumeration(
    content: AdCopyContent,
    request: AdCopyRequest,
    card: TrendCard,
) -> bool:
    recommendation = content.channel_recommendation
    customer_texts = [
        *content.headlines,
        *content.body_copies,
        recommendation.overlay_headline,
        recommendation.caption,
        recommendation.publish_title,
        recommendation.publish_body,
    ]
    for text in customer_texts:
        for sentence in re.split(r"(?:\r?\n)+|(?<=[.!?。！？])\s+", text):
            if not _contains_trend_reference(sentence, card):
                continue
            mentioned_products = [
                product for product in request.product_names if product in sentence
            ]
            if len(mentioned_products) >= 2 and sentence.count(",") >= 2:
                return True
    return False


def _customer_visible_fields(content: AdCopyContent) -> list[tuple[str, str]]:
    recommendation = content.channel_recommendation
    fields: list[tuple[str, str]] = []
    for name, values in (
        ("headlines", content.headlines),
        ("body_copies", content.body_copies),
        ("ctas", content.ctas),
        ("hashtags", content.hashtags),
    ):
        fields.extend(
            (f"{name}[{index}]", value)
            for index, value in enumerate(values)
            if value.strip()
        )
    for name in (
        "overlay_headline",
        "caption",
        "publish_cta",
        "publish_title",
        "publish_body",
        "blog_title",
    ):
        value = getattr(recommendation, name)
        if value.strip():
            fields.append((f"channel_recommendation.{name}", value))
    fields.extend(
        (f"channel_recommendation.publish_hashtags[{index}]", value)
        for index, value in enumerate(recommendation.publish_hashtags)
        if value.strip()
    )
    for section_index, section in enumerate(recommendation.blog_sections):
        for name in ("title", "body"):
            value = section.get(name)
            if isinstance(value, str) and value.strip():
                fields.append(
                    (
                        f"channel_recommendation.blog_sections[{section_index}].{name}",
                        value,
                    )
                )
    return fields


_FOREIGN_SCRIPT_RE = re.compile(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff]")
_HANGUL_RE = re.compile(r"[가-힣]")
_LATIN_RE = re.compile(r"[A-Za-z]{2,}")
_HASHTAG_RE = re.compile(r"^#[0-9A-Za-z가-힣_]+$")


def _non_korean_customer_fields(
    fields: list[tuple[str, str]],
    request: AdCopyRequest,
) -> list[str]:
    allowed_latin_literals = {
        "".join(character for character in value.casefold() if character.isalnum())
        for value in (
            request.business_name,
            *request.product_names,
            *request.required_terms,
        )
        if value.strip()
    }
    invalid: list[str] = []
    for name, text in fields:
        # Chinese/Japanese script is rejected even when a Korean fragment is
        # also present. Latin-only copy is rejected; short product/brand
        # fragments embedded in otherwise Korean copy remain allowed.
        normalized_text = "".join(
            character for character in text.casefold() if character.isalnum()
        )
        latin_only_without_input_match = (
            _LATIN_RE.search(text)
            and not _HANGUL_RE.search(text)
            and normalized_text not in allowed_latin_literals
        )
        if _FOREIGN_SCRIPT_RE.search(text) or latin_only_without_input_match:
            invalid.append(name)
    return invalid


_CONDITIONAL_CLAIMS = (
    "예약",
    "주문",
    "배송",
    "배달",
    "할인",
    "무료",
    "공짜",
    "증정",
    "한정",
    "이벤트",
    "1위",
    "최고",
    "유일",
    "베스트",
    "수밖에",
    "유기농",
    "국내산",
    "건강",
    "저칼로리",
    "다이어트",
    "면역",
    "혈당",
    "무설탕",
    "비건",
    "영양",
    "효능",
    "치료",
    "완치",
    "보장",
    "인증",
    "수상",
    "수제",
    "직접 만든",
    "당일",
    "신선",
)


def _unsupported_claims(
    customer_text: str,
    request: AdCopyRequest,
) -> list[str]:
    evidence = " ".join(
        part
        for part in (
            request.business_name,
            *request.product_names,
            *request.features,
            request.promotion or "",
            *request.required_terms,
            request.product_price or "",
            request.additional_request or "",
            request.operating_info or "",
        )
        if part
    )
    allowed_by_context: set[str] = set()
    if request.situation.value in {"delivery", "takeout"} or (
        request.channel.value == "delivery_app"
    ):
        allowed_by_context.update({"주문", "배송", "배달"})
    if request.situation.value == "discount":
        allowed_by_context.add("할인")
    if request.situation.value == "event":
        allowed_by_context.add("이벤트")
    return [
        term
        for term in _CONDITIONAL_CLAIMS
        if term in customer_text and term not in evidence and term not in allowed_by_context
    ]


def validate_copy_output(
    content: AdCopyContent,
    request: AdCopyRequest,
    trend_card: TrendCard | None = None,
) -> CopyValidationResult:
    warnings: list[str] = []
    failure_codes: list[str] = []
    visible_primary_copy_text = " ".join(content.headlines[:1] + content.body_copies[:1])
    visible_fields = _customer_visible_fields(content)
    customer_text = " ".join(value for _, value in visible_fields)
    is_blog = request.channel.value == "naver_blog"
    visual_text = "" if is_blog else str(content.visual_brief.model_dump())

    missing_products = [
        product for product in request.product_names if product not in customer_text
    ]
    if missing_products:
        _add_failure(
            warnings,
            failure_codes,
            "product_name_missing_in_customer_copy",
            f"광고 문구에 누락된 상품명: {', '.join(missing_products)}",
        )

    missing_required_terms = [
        term for term in request.required_terms if term and term not in customer_text
    ]
    if missing_required_terms:
        _add_failure(
            warnings,
            failure_codes,
            "required_terms_missing",
            "고객 노출 문구에 누락된 필수 표현: "
            + ", ".join(missing_required_terms),
        )

    prohibited_in_copy = _contains_any(customer_text, request.prohibited_terms)
    prohibited_in_visual = [] if is_blog else _contains_any(visual_text, request.prohibited_terms)
    if prohibited_in_copy or prohibited_in_visual:
        _add_failure(
            warnings,
            failure_codes,
            "prohibited_term_used",
            "금지 표현 포함: "
            + ", ".join(sorted(set(prohibited_in_copy + prohibited_in_visual))),
        )

    non_korean_fields = _non_korean_customer_fields(visible_fields, request)
    if non_korean_fields:
        _add_failure(
            warnings,
            failure_codes,
            "non_korean_customer_copy",
            "자연스러운 한국어가 아닌 고객 노출 필드: "
            + ", ".join(non_korean_fields),
        )

    unsupported_claims = _unsupported_claims(customer_text, request)
    if unsupported_claims:
        _add_failure(
            warnings,
            failure_codes,
            "unsupported_claim_detected",
            "입력으로 뒷받침되지 않는 표현 감지: "
            + ", ".join(unsupported_claims),
        )

    hashtag_values = [
        *content.hashtags,
        *content.channel_recommendation.publish_hashtags,
    ]
    invalid_hashtags = [
        hashtag for hashtag in hashtag_values if not _HASHTAG_RE.fullmatch(hashtag)
    ]
    if invalid_hashtags:
        _add_failure(
            warnings,
            failure_codes,
            "hashtag_format_noncompliant",
            "해시태그 형식 오류: " + ", ".join(dict.fromkeys(invalid_hashtags)),
        )

    if trend_card:
        if not _contains_trend_reference(visible_primary_copy_text, trend_card):
            _add_failure(
                warnings,
                failure_codes,
                "trend_marker_missing_in_primary_copy",
                "선택한 TrendCard가 화면에 표시되는 첫 광고 문구에 반영되지 않았습니다: "
                f"{trend_card.meme_id}",
            )
        for warning in _trend_post_warnings(
            content, request.channel.value, trend_card
        ):
            code = (
                "trend_marker_missing_in_caption_opening"
                if "caption의 첫 문장" in warning
                else "instagram_caption_missing_from_publish_body"
                if "Instagram caption 원문" in warning
                else "trend_marker_missing_in_channel_post"
            )
            _add_failure(warnings, failure_codes, code, warning)
        if _has_mechanical_product_enumeration(content, request, trend_card):
            _add_failure(
                warnings,
                failure_codes,
                "trend_mechanical_product_enumeration",
                "TrendCard 응용 표현에 여러 상품명을 쉼표로 단순 나열했습니다: "
                f"{trend_card.meme_id}",
            )

    if not is_blog:
        visual_products = {item.product_name for item in content.visual_brief.products_to_show}
        missing_visual_products = [
            product for product in request.product_names if product not in visual_products
        ]
        if missing_visual_products:
            _add_failure(
                warnings,
                failure_codes,
                "product_name_not_preserved_in_visual_brief",
                "visual_brief.products_to_show에 누락된 상품명: "
                + ", ".join(missing_visual_products),
            )

    if request.channel.value == "instagram":
        recommendation = content.channel_recommendation
        missing_caption_products = [
            product
            for product in request.product_names
            if product not in recommendation.caption
        ]
        if missing_caption_products:
            _add_failure(
                warnings,
                failure_codes,
                "instagram_caption_product_name_missing",
                "Instagram caption에 누락된 상품명: "
                + ", ".join(missing_caption_products),
            )
        missing_caption_required_terms = [
            term
            for term in request.required_terms
            if term and term not in recommendation.caption
        ]
        if missing_caption_required_terms:
            _add_failure(
                warnings,
                failure_codes,
                "instagram_caption_required_terms_missing",
                "Instagram caption에 누락된 필수 표현: "
                + ", ".join(missing_caption_required_terms),
            )
        if not recommendation.caption.strip():
            _add_failure(
                warnings,
                failure_codes,
                "instagram_caption_missing",
                "Instagram caption이 비어 있습니다.",
            )
        if not recommendation.publish_cta.strip():
            _add_failure(
                warnings,
                failure_codes,
                "instagram_publish_cta_missing",
                "Instagram publish_cta가 비어 있습니다.",
            )
        if not recommendation.publish_hashtags:
            _add_failure(
                warnings,
                failure_codes,
                "instagram_publish_hashtags_missing",
                "Instagram publish_hashtags가 비어 있습니다.",
            )
        expected_body = _compose_instagram_publish_body(
            recommendation.caption,
            recommendation.publish_cta,
            recommendation.publish_hashtags,
        )
        if recommendation.publish_body != expected_body:
            _add_failure(
                warnings,
                failure_codes,
                "instagram_publish_body_not_normalized",
                "Instagram publish_body가 caption + publish_cta + "
                "publish_hashtags의 정규 조합과 일치하지 않습니다.",
            )

    return CopyValidationResult(
        valid=not warnings,
        warnings=warnings,
        failure_codes=failure_codes,
    )


def remove_prohibited_terms(text: str, prohibited_terms: list[str]) -> str:
    cleaned = text
    for term in prohibited_terms:
        if term:
            cleaned = cleaned.replace(term, "")
    return " ".join(cleaned.split())


def _feature_value(features: list[str], label: str) -> str:
    prefix = f"{label}:"
    for feature in features:
        if feature.startswith(prefix):
            return feature.removeprefix(prefix).strip()
    return ""


def _sales_features(features: list[str]) -> list[str]:
    internal_prefixes = (
        "성별 타겟:",
        "직업군:",
        "타겟:",
        "제품가격:",
        "관심사:",
        "지역:",
        "상권:",
        "세부 타겟:",
    )
    return [
        feature.strip()
        for feature in features
        if feature.strip() and not feature.startswith(internal_prefixes)
    ]


def _clean_hashtag(value: str) -> str:
    cleaned = "".join(ch for ch in value if ch.isalnum() or ch in ("_",))
    return f"#{cleaned}" if cleaned else ""


def _render_trend_pattern(
    card: TrendCard | None,
    request: AdCopyRequest,
) -> str:
    if card is None:
        return ""
    primary_product = (
        request.product_names[0] if request.product_names else request.business_name
    )
    situation = {
        "new_menu": "새 메뉴가 생각나는 순간",
        "discount": "알뜰하게 즐기고 싶은 순간",
        "event": "특별한 소식이 생각나는 순간",
        "delivery": "집에서 메뉴가 생각나는 순간",
        "takeout": "가볍게 챙겨 가고 싶은 순간",
        "visit": "카페에 들르고 싶은 순간",
    }.get(request.situation.value, "메뉴가 생각나는 순간")
    pattern = card.text_patterns[0] if card.text_patterns else card.display_name
    replacements = {
        "{메뉴}": primary_product,
        "{상품}": primary_product,
        "{상황}": situation,
        "{방문을 유도할 대상}": request.business_name,
    }
    rendered = pattern
    for placeholder, value in replacements.items():
        rendered = rendered.replace(placeholder, value)
    return re.sub(r"\{[^{}]+\}", primary_product, rendered).strip()


def _build_instagram_package(
    request: AdCopyRequest,
    products: str,
    prohibited_terms: list[str],
    trend_card: TrendCard | None = None,
) -> tuple[str, str, str, list[str]]:
    product = request.product_names[0] if request.product_names else products
    product_phrase = products or product
    sales_features = _sales_features(request.features)
    price = request.product_price or _feature_value(request.features, "제품가격")
    region = request.region or _feature_value(request.features, "지역")
    interests = request.interests or [
        item.strip()
        for item in _feature_value(request.features, "관심사").split(",")
        if item.strip()
    ]

    trend_headline = _render_trend_pattern(trend_card, request)
    overlay_headline = remove_prohibited_terms(
        trend_headline or "오늘은 달콤하게, 특별하게", prohibited_terms
    )
    opening = f"{request.business_name}의 {product_phrase}를 소개합니다."
    if sales_features:
        opening = (
            f"{sales_features[0]}으로 기억될 {request.business_name}의 "
            f"{product_phrase}를 소개합니다."
        )

    relationship_subject = (
        "이 메뉴 조합이"
        if len(request.product_names) > 1
        else f"{product}이(가)"
    )

    lines = [
        opening,
        "",
        f"{relationship_subject} 필요한 순간에 자연스럽게 어울립니다.",
    ]
    if trend_headline:
        lines.insert(0, trend_headline)
    missing_required_terms = [
        term
        for term in request.required_terms
        if term and term not in "\n".join(lines)
    ]
    if missing_required_terms:
        lines.append(
            f"{', '.join(missing_required_terms)}의 매력도 함께 만나보세요."
        )
    if price:
        lines.extend(["", f"{price}에 즐기는 달콤한 선택."])
    if region:
        lines.extend(["", f"📍{region}"])

    caption = remove_prohibited_terms("\n".join(lines), prohibited_terms)
    publish_cta = remove_prohibited_terms("매장에서 만나보세요.", prohibited_terms)
    hashtags = [
        _clean_hashtag(region.replace("서울 ", "").replace(" ", "") + "카페") if region else "",
        _clean_hashtag(product),
        "#디저트맛집",
    ]
    for interest in interests:
        hashtags.append(_clean_hashtag(interest))
    hashtags = [tag for tag in dict.fromkeys(hashtags) if tag][:6]
    return overlay_headline, caption, publish_cta, hashtags


def _build_blog_package(
    request: AdCopyRequest,
    products: str,
    body: str,
    cta: str,
    hashtags: list[str],
    trend_card: TrendCard | None = None,
) -> dict[str, object]:
    photo_notes = request.blog_photo_notes or []
    photo_order = [_photo_label(note, index + 1) for index, note in enumerate(photo_notes)]
    products_list = request.product_names
    product_text = _join_korean_products(products_list)
    region = request.region or _feature_value(request.features, "지역")
    region_label = region.split()[-1] if region else ""
    feature_sentence = " ".join(
        feature
        for feature in _sales_features(request.features)
        if not any(keyword in feature for keyword in ("운영", "시간", "런치"))
    )
    situation = request.situation.value
    title_suffix, opening, visit_guidance = _blog_situation_copy(
        situation, request.business_name, product_text
    )
    trend_opening = _render_trend_pattern(trend_card, request)
    intro = "\n".join(part for part in [trend_opening, opening] if part)
    title = f"{region_label + ' ' if region_label else ''}카페 {request.business_name}, {title_suffix}"
    menu_photo_marker = f"[{photo_order[0]} - {product_text}]" if photo_order else ""
    space_photo_marker = (
        f"[{photo_order[1]} - 매장 내부 또는 전경]" if len(photo_order) > 1 else ""
    )
    price_details = [
        f"{product} {_product_price(product, request.product_price)}".strip()
        for product in products_list
        if _product_price(product, request.product_price)
    ]
    menu_body = f"{product_text}는 {request.business_name}에서 준비한 메뉴입니다."
    if price_details:
        menu_body += f" 가격은 {', '.join(price_details)}입니다."
    menu_body += " 방문하신 날의 여유로운 시간과 함께 자연스럽게 즐겨 보세요."

    sections = [
        {
            "title": "인사말",
            "photo": photo_order[0] if photo_order else "",
            "body": intro,
        },
        {
            "title": f"{product_text}를 소개합니다",
            "photo": photo_order[0] if photo_order else "",
            "body": menu_body,
        },
        {
            "title": "편안하게 머물다 가실 수 있는 공간",
            "photo": photo_order[1] if len(photo_order) > 1 else "",
            "body": " ".join(
                part
                for part in [
                    f"{request.business_name}은 편안하게 머물며 메뉴를 즐길 수 있는 공간입니다.",
                    feature_sentence,
                    visit_guidance,
                ]
                if part
            ),
        },
    ]

    store_info = ["📍 매장 안내"]
    if region:
        store_info.append(f"위치 : {region}")
    if price_details:
        store_info.append(f"추천 메뉴 : {', '.join(price_details)}")
    else:
        store_info.append(f"추천 메뉴 : {product_text}")
    if request.operating_info:
        store_info.append(f"운영 안내 : {request.operating_info}")

    publish_body = "\n\n".join(
        part
        for part in [
            title,
            f"안녕하세요.\n{request.business_name}입니다.",
            trend_opening,
            opening,
            menu_photo_marker,
            sections[1]["title"],
            sections[1]["body"],
            sections[2]["title"],
            space_photo_marker,
            sections[2]["body"],
            "감사합니다.",
            "\n".join(store_info),
            " ".join(hashtags),
        ]
        if part
    )
    return {
        "blog_title": title,
        "thumbnail_photo": photo_order[0] if photo_order else "",
        "thumbnail_reason": "",
        "photo_order": photo_order,
        "blog_sections": sections,
        "publish_body": publish_body,
        "promotion_template": "",
        "image_insert_guide": "사진이 있는 경우 메뉴 또는 매장 소개 문단 다음에 배치하세요.",
    }


def _join_korean_products(products: list[str]) -> str:
    if len(products) <= 1:
        return products[0] if products else "대표 메뉴"
    return f"{', '.join(products[:-1])}와 {products[-1]}"


def _product_price(product: str, product_price: str | None) -> str:
    if not product_price:
        return ""
    match = re.search(rf"{re.escape(product)}\s*[:：-]?\s*(\d[\d,]*원)", product_price)
    return match.group(1) if match else ""


def _photo_label(note: str, fallback_index: int) -> str:
    match = re.search(r"사진\s*\d+", note)
    return match.group(0).replace("  ", " ") if match else f"사진 {fallback_index}"


def _blog_situation_copy(
    situation: str, business_name: str, products: str
) -> tuple[str, str, str]:
    copies = {
        "new_menu": (
            f"새롭게 준비한 {products}를 소개합니다",
            f"오늘은 {business_name}에서 새롭게 준비한 {products}를 소개해 드립니다.",
            "새로운 메뉴가 궁금하셨다면 매장에서 직접 만나보세요.",
        ),
        "discount": (
            f"{products} 세트 메뉴 할인 소식을 전합니다",
            f"오늘은 {business_name}의 {products} 세트 메뉴 할인 소식을 안내해 드립니다.",
            "할인 적용 메뉴와 기간은 방문 전 매장 안내를 확인해 주세요.",
        ),
        "event": (
            f"{products}와 함께하는 이벤트를 안내합니다",
            f"오늘은 {business_name}에서 준비한 {products} 관련 이벤트 소식을 전해 드립니다.",
            "이벤트 참여 방법과 기간은 매장 안내에 맞춰 확인해 주세요.",
        ),
        "delivery": (
            f"집에서도 즐길 수 있는 {products}를 소개합니다",
            f"오늘은 {business_name}의 {products}를 배달로 즐기는 방법을 소개해 드립니다.",
            "편안한 자리에서 메뉴를 즐기고 싶을 때 배달 주문을 확인해 보세요.",
        ),
        "takeout": (
            f"가볍게 포장해 즐기기 좋은 {products}를 소개합니다",
            f"오늘은 {business_name}의 {products}를 포장으로 즐기는 방법을 소개해 드립니다.",
            "바쁜 하루 중에도 포장으로 편하게 메뉴를 만나보세요.",
        ),
        "visit": (
            f"매장에서 즐기기 좋은 {products}를 소개합니다",
            f"오늘은 {business_name}에서 직접 즐기기 좋은 {products}를 소개해 드립니다.",
            "여유로운 시간이 필요할 때 매장에 들러 메뉴를 만나보세요.",
        ),
    }
    return copies.get(situation, copies["visit"])


def build_fallback_copy(
    request: AdCopyRequest,
    warnings: list[str],
    trend_card: TrendCard | None = None,
) -> AdCopyContent:
    products = _join_korean_products(request.product_names)
    sales_features = _sales_features(request.features)
    feature_sentence = " ".join(sales_features)
    trend_headline = _render_trend_pattern(trend_card, request)
    headline = remove_prohibited_terms(
        trend_headline or f"{request.business_name}의 새로운 소식",
        request.prohibited_terms,
    )
    body = remove_prohibited_terms(
        f"{request.business_name}에서 {products}을(를) 만나보세요. {feature_sentence}",
        request.prohibited_terms,
    )
    missing_required_terms = [
        term for term in request.required_terms if term and term not in body
    ]
    if missing_required_terms:
        body = f"{body} {', '.join(missing_required_terms)}"
    cta = remove_prohibited_terms(
        f"{request.business_name}에서 확인해보세요.", request.prohibited_terms
    )
    hashtags = [
        f"#{remove_prohibited_terms(product, request.prohibited_terms).replace(' ', '')}"
        for product in request.product_names[:3]
    ]
    business_type_hashtag = {
        "cafe": "카페",
        "bakery": "베이커리",
        "dessert": "디저트",
        "restaurant": "음식점",
        "pub": "주점",
    }.get(request.business_type.value, "동네가게")
    hashtags.append(f"#{business_type_hashtag}")
    product_items = [
        MandatoryProduct(product_name=product, role="primary" if index == 0 else "secondary")
        for index, product in enumerate(request.product_names)
    ]
    feature_items = [
        MandatoryFeature(
            feature_text=feature,
            copy_usage_rule="must appear in body copy",
            visual_usage_rule="must be converted into visual cue when possible",
        )
        for feature in request.features
    ]
    visual_products = [
        ProductToShow(
            product_name=product,
            visual_role="main" if index == 0 else "supporting",
            must_be_visible=True,
        )
        for index, product in enumerate(request.product_names)
    ]
    feature_visualization = [
        FeatureVisualization(feature_text=feature, visual_translation=[feature])
        for feature in request.features
    ]
    overlay_headline, caption, instagram_cta, instagram_hashtags = _build_instagram_package(
        request,
        products,
        request.prohibited_terms,
        trend_card,
    )
    blog_package = _build_blog_package(
        request,
        products,
        body,
        cta,
        hashtags,
        trend_card,
    )
    channel_recommendations = {
        "instagram": ChannelRecommendation(
            format_name="인스타그램 피드",
            writing_direction="짧은 첫 문장, 본문, CTA, 해시태그 순서로 게시하세요.",
            image_direction="상품이 크게 보이는 4:5 피드 이미지로 사용하세요.",
            placement_tip="이미지 위에는 짧은 헤드라인만 올리고 자세한 설명은 캡션에 배치하세요.",
            overlay_headline=overlay_headline,
            caption=caption,
            publish_cta=instagram_cta,
            publish_hashtags=instagram_hashtags,
            publish_title=overlay_headline,
            publish_body=f"{caption}\n\n{instagram_cta}\n{' '.join(instagram_hashtags)}",
            promotion_template="이미지: 생성된 4:5 상품 사진\n제목: overlay_headline\n캡션: caption\n마무리: publish_cta\n해시태그: publish_hashtags",
            image_insert_guide="생성 이미지는 피드 본문 첫 장에 넣고, 자세한 설명은 캡션에 배치하세요.",
        ),
        "naver_blog": ChannelRecommendation(
            format_name="네이버 블로그 본문",
            writing_direction="작성된 문구를 블로그 도입부와 상품 설명 문단으로 나누어 사용하세요.",
            image_direction="대표 상품 사진을 도입부에, 상세 이미지를 본문 중간에 넣으세요.",
            placement_tip="글과 사진을 번갈아 배치하면 정보 탐색 흐름이 자연스럽습니다.",
            publish_title=str(blog_package["blog_title"]),
            publish_body=str(blog_package["publish_body"]),
            promotion_template=str(blog_package["promotion_template"]),
            image_insert_guide=str(blog_package["image_insert_guide"]),
            blog_title=str(blog_package["blog_title"]),
            thumbnail_photo=str(blog_package["thumbnail_photo"]),
            thumbnail_reason=str(blog_package["thumbnail_reason"]),
            photo_order=blog_package["photo_order"],  # type: ignore[arg-type]
            blog_sections=blog_package["blog_sections"],  # type: ignore[arg-type]
        ),
        "delivery_app": ChannelRecommendation(
            format_name="배달앱 포스터",
            writing_direction="상품명, 가격/혜택, CTA가 바로 보이게 짧게 사용하세요.",
            image_direction="상품 중심의 전체 포스터 이미지로 사용하세요.",
            placement_tip="앱 카드에서는 이미지 아래에 핵심 혜택과 주문 CTA를 붙이세요.",
            publish_title=headline,
            publish_body=f"{body}\n{cta}",
            promotion_template="포스터 헤드라인\n상품명/가격 또는 혜택\n짧은 설명\n주문 CTA",
            image_insert_guide="생성 이미지는 앱 상품 카드의 대표 이미지 또는 배너 이미지로 사용하세요.",
        ),
        "store_poster": ChannelRecommendation(
            format_name="매장 포스터",
            writing_direction="멀리서도 읽히는 한 줄 헤드라인과 짧은 CTA로 사용하세요.",
            image_direction="상품이 크게 보이는 세로형 포스터 이미지로 사용하세요.",
            placement_tip="상단에는 헤드라인, 중앙에는 상품, 하단에는 CTA를 배치하세요.",
            publish_title=headline,
            publish_body=f"{body}\n{cta}",
            promotion_template="상단: 헤드라인\n중앙: 큰 상품 이미지\n하단: 가격/혜택과 CTA",
            image_insert_guide="생성 이미지를 포스터 중앙에 크게 두고, 문구는 상단과 하단에 짧게 배치하세요.",
        ),
    }

    return AdCopyContent(
        marketing_strategy=MarketingStrategy(
            business_summary={
                "business_name": request.business_name,
                "business_type_korean": request.business_type.value,
                "situation_korean": request.situation.value,
                "age_groups_korean": [age.value for age in request.age_groups],
                "target_audiences_korean": [target.value for target in request.target_audiences],
                "tone_korean": request.tone.value,
                "channel_korean": request.channel.value,
            },
            mandatory_products=product_items,
            mandatory_features=feature_items,
            core_message=f"{products}의 핵심 특징을 정확히 알리는 광고",
            customer_emotion="신뢰감",
            marketing_angle="입력된 상품과 특징 중심",
            recommended_cta_direction="매장 확인 유도",
            avoid_points=request.prohibited_terms,
        ),
        headlines=[headline],
        body_copies=[body],
        ctas=[cta],
        hashtags=hashtags,
        channel_recommendation=channel_recommendations.get(
            request.channel.value,
            ChannelRecommendation(
                format_name="디지털 광고",
                writing_direction="본문과 CTA를 함께 사용하세요.",
                image_direction="상품 중심 이미지로 사용하세요.",
                placement_tip="글과 이미지를 같은 메시지로 맞춰 배치하세요.",
                publish_title=headline,
                publish_body=f"{body}\n\n{cta}",
                promotion_template="제목\n이미지\n본문\nCTA",
                image_insert_guide="생성 이미지를 게시물 상단에 넣고 본문과 CTA를 이어서 배치하세요.",
            ),
        ),
        validation_check=ValidationCheck(
            all_products_included=True,
            all_features_included=True,
            prohibited_terms_used=False,
            visual_brief_uses_enum_only=True,
            hashtags_removed=False,
            language_quality="fallback Korean",
        ),
        visual_brief=VisualBrief(
            products_to_show=visual_products,
            feature_visualization=feature_visualization,
            camera_angle="45_degree_close_up",
            composition="two_product_set"
            if len(request.product_names) > 1
            else "centered_product_hero",
            lighting="soft_natural_window_light",
            background="minimal_korean_local_cafe",
            color_palette=["premium_neutral_tones"],
            depth_of_field="shallow_depth_of_field",
            empty_space="poster_safe_margin",
            avoid=[
                "readable_text",
                "logo",
                "watermark",
                "menu_board",
                "store_sign",
                "random_people",
                "distorted_food",
                "messy_table",
            ],
        ),
        safety_notes=[*warnings, "LLM 출력 검증 실패로 fallback copy를 사용했습니다."],
    )
