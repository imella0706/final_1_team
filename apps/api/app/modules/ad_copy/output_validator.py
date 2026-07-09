from dataclasses import dataclass

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


@dataclass(frozen=True)
class CopyValidationResult:
    valid: bool
    warnings: list[str]


def _contains_any(text: str, terms: list[str]) -> list[str]:
    return [term for term in terms if term and term in text]


def validate_copy_output(content: AdCopyContent, request: AdCopyRequest) -> CopyValidationResult:
    warnings: list[str] = []
    copy_text = " ".join(content.headlines + content.body_copies + content.ctas + content.hashtags)
    body_text = " ".join(content.body_copies)
    visual_text = str(content.visual_brief.model_dump())

    missing_products = [
        product for product in request.product_names if product not in copy_text
    ]
    if missing_products:
        warnings.append(f"광고 문구에 누락된 상품명: {', '.join(missing_products)}")

    missing_features = [feature for feature in request.features if feature not in body_text]
    if missing_features:
        warnings.append(f"본문 문구에 원문 그대로 누락된 특징: {', '.join(missing_features)}")

    prohibited_in_copy = _contains_any(copy_text, request.prohibited_terms)
    prohibited_in_visual = _contains_any(visual_text, request.prohibited_terms)
    if prohibited_in_copy or prohibited_in_visual:
        warnings.append(
            "금지 표현 포함: "
            + ", ".join(sorted(set(prohibited_in_copy + prohibited_in_visual)))
        )

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


def build_fallback_copy(request: AdCopyRequest, warnings: list[str]) -> AdCopyContent:
    products = ", ".join(request.product_names)
    features = " ".join(request.features)
    headline = remove_prohibited_terms(
        f"{request.business_name}의 새로운 소식", request.prohibited_terms
    )
    body = remove_prohibited_terms(
        f"{request.business_name}에서 {products}을(를) 만나보세요. {features}",
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
    channel_recommendations = {
        "instagram": ChannelRecommendation(
            format_name="인스타그램 피드",
            writing_direction="짧은 첫 문장, 본문, CTA, 해시태그 순서로 게시하세요.",
            image_direction="상품이 크게 보이는 4:5 피드 이미지로 사용하세요.",
            placement_tip="이미지 위에는 짧은 헤드라인만 올리고 자세한 설명은 캡션에 배치하세요.",
        ),
        "naver_blog": ChannelRecommendation(
            format_name="네이버 블로그 본문",
            writing_direction="작성된 문구를 블로그 도입부와 상품 설명 문단으로 나누어 사용하세요.",
            image_direction="대표 상품 사진을 도입부에, 상세 이미지를 본문 중간에 넣으세요.",
            placement_tip="글과 사진을 번갈아 배치하면 정보 탐색 흐름이 자연스럽습니다.",
        ),
        "delivery_app": ChannelRecommendation(
            format_name="배달앱 포스터",
            writing_direction="상품명, 가격/혜택, CTA가 바로 보이게 짧게 사용하세요.",
            image_direction="상품 중심의 전체 포스터 이미지로 사용하세요.",
            placement_tip="앱 카드에서는 이미지 아래에 핵심 혜택과 주문 CTA를 붙이세요.",
        ),
        "store_poster": ChannelRecommendation(
            format_name="매장 포스터",
            writing_direction="멀리서도 읽히는 한 줄 헤드라인과 짧은 CTA로 사용하세요.",
            image_direction="상품이 크게 보이는 세로형 포스터 이미지로 사용하세요.",
            placement_tip="상단에는 헤드라인, 중앙에는 상품, 하단에는 CTA를 배치하세요.",
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
