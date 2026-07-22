from dataclasses import dataclass
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


def validate_copy_output(
    content: AdCopyContent,
    request: AdCopyRequest,
    trend_card: TrendCard | None = None,
) -> CopyValidationResult:
    warnings: list[str] = []
    channel_text = str(content.channel_recommendation.model_dump())
    all_primary_copy_text = " ".join(content.headlines + content.body_copies + content.ctas)
    visible_primary_copy_text = " ".join(content.headlines[:1] + content.body_copies[:1])
    copy_text = f"{all_primary_copy_text} {' '.join(content.hashtags)} {channel_text}"
    is_blog = request.channel.value == "naver_blog"
    visual_text = "" if is_blog else str(content.visual_brief.model_dump())

    missing_products = [
        product for product in request.product_names if product not in copy_text
    ]
    if missing_products:
        warnings.append(f"광고 문구에 누락된 상품명: {', '.join(missing_products)}")

    prohibited_in_copy = _contains_any(copy_text, request.prohibited_terms)
    prohibited_in_visual = [] if is_blog else _contains_any(visual_text, request.prohibited_terms)
    if prohibited_in_copy or prohibited_in_visual:
        warnings.append(
            "금지 표현 포함: "
            + ", ".join(sorted(set(prohibited_in_copy + prohibited_in_visual)))
        )

    if trend_card:
        if not _contains_trend_reference(visible_primary_copy_text, trend_card):
            warnings.append(
                "선택한 TrendCard가 화면에 표시되는 첫 광고 문구에 반영되지 않았습니다: "
                f"{trend_card.meme_id}"
            )
        warnings.extend(
            _trend_post_warnings(content, request.channel.value, trend_card)
        )
        if _has_mechanical_product_enumeration(content, request, trend_card):
            warnings.append(
                "TrendCard 응용 표현에 여러 상품명을 쉼표로 단순 나열했습니다: "
                f"{trend_card.meme_id}"
            )

    if not is_blog:
        visual_products = {item.product_name for item in content.visual_brief.products_to_show}
        missing_visual_products = [
            product for product in request.product_names if product not in visual_products
        ]
        if missing_visual_products:
            warnings.append(
                f"visual_brief.products_to_show에 누락된 상품명: {', '.join(missing_visual_products)}"
            )

    return CopyValidationResult(valid=not warnings, warnings=warnings)


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
    opening = f"{request.business_name}의 {product}를 소개합니다."
    if sales_features:
        opening = f"{sales_features[0]}으로 기억될 {request.business_name}의 {product}를 소개합니다."

    lines = [
        opening,
        "",
        f"{product}이(가) 필요한 순간에 자연스럽게 어울리는 메뉴입니다.",
    ]
    if trend_headline:
        lines.insert(0, trend_headline)
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
    cta = remove_prohibited_terms(
        f"{request.business_name}에서 확인해보세요.", request.prohibited_terms
    )
    hashtags = [
        f"#{remove_prohibited_terms(product, request.prohibited_terms).replace(' ', '')}"
        for product in request.product_names[:3]
    ]
    hashtags.append(f"#{request.business_type.value}")
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
