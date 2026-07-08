import json

import httpx

from app.core.config import settings
from app.extensions.ad_content.product_visualizer import ProductVisual, ProductVisualization
from app.modules.ad_copy.schemas import AdCopyRequest, AdCopyResponse


BUSINESS_TYPE_LABELS = {
    "cafe": "small independent cafe tabletop atmosphere, no signage",
    "bakery": "small independent bakery tabletop atmosphere, no signage",
    "dessert": "small independent dessert shop tabletop atmosphere, no signage",
    "restaurant": "small independent restaurant tabletop atmosphere, no signage",
    "pub": "small independent pub tabletop atmosphere, no signage",
}

CAMERA_LABELS = {
    "45_degree_close_up": "45-degree close-up product shot",
    "eye_level_close_up": "eye-level close-up product shot",
    "top_down_flat_lay": "top-down flat lay product shot",
    "macro_detail": "macro detail shot",
    "three_quarter_product_shot": "three-quarter product shot",
}

COMPOSITION_LABELS = {
    "centered_product_hero": "centered product hero composition",
    "two_product_set": "two-product set composition with all products visible together",
    "tray_set_composition": "tray set composition with all products arranged as one set",
    "rule_of_thirds": "rule-of-thirds product composition",
    "poster_with_empty_space": "vertical 4:5 poster composition with clear empty space",
}

LIGHTING_LABELS = {
    "soft_natural_window_light": "soft natural window light",
    "warm_morning_light": "warm morning light",
    "warm_afternoon_light": "warm afternoon light",
    "soft_studio_light": "soft studio light",
    "cozy_indoor_light": "cozy indoor light",
}

BACKGROUND_LABELS = {
    "minimal_korean_local_cafe": (
        "clean cafe table with a plain softly blurred interior background, "
        "no signs, no posters, no menu boards, no readable text"
    ),
    "wooden_cafe_table": (
        "clean wooden cafe table with a plain softly blurred background, "
        "no signs, no posters, no menu boards, no readable text"
    ),
    "clean_bakery_counter": (
        "clean bakery counter with a plain softly blurred background, "
        "no signs, no posters, no menu boards, no readable text"
    ),
    "warm_restaurant_table": (
        "warm restaurant table with a plain softly blurred background, "
        "no signs, no posters, no menu boards, no readable text"
    ),
    "cozy_pub_table": (
        "cozy pub table with a plain softly blurred background, "
        "no signs, no posters, no menu boards, no readable text"
    ),
}

PALETTE_LABELS = {
    "warm_beige_cream": "warm beige and cream tones",
    "soft_pink_peach": "soft pink and peach tones",
    "brown_cream_gold": "brown, cream, and gold tones",
    "fresh_fruit_tones": "fresh fruit color tones",
    "premium_neutral_tones": "premium neutral tones",
}

DEPTH_LABELS = {
    "shallow_depth_of_field": "shallow depth of field",
    "medium_depth_of_field": "medium depth of field",
    "sharp_product_soft_background": "sharp product focus with soft background blur",
}

EMPTY_SPACE_LABELS = {
    "top_20_percent": "empty space in the top 20 percent for later text overlay",
    "right_25_percent": "empty space on the right 25 percent for later text overlay",
    "left_25_percent": "empty space on the left 25 percent for later text overlay",
    "upper_right_corner": "empty space in the upper right corner for later text overlay",
    "poster_safe_margin": "poster-safe margin with clean negative space for later text overlay",
}


def _label(mapping: dict[str, str], value: str) -> str:
    return mapping.get(value, value.replace("_", " "))


def _secret_value(value) -> str | None:
    if value is None:
        return None
    if hasattr(value, "get_secret_value"):
        return value.get_secret_value() or None
    return str(value) or None


async def describe_reference_image(
    reference_image_data_url: str | None,
    copy_request: AdCopyRequest,
) -> str | None:
    if not reference_image_data_url:
        return None

    api_key = _secret_value(settings.openai_api_key)
    if not api_key:
        return None

    prompt = (
        "이 참고 이미지를 보고, 광고 이미지 생성에 바로 반영할 수 있도록 핵심 시각 요소를 한국어로 짧게 요약해 주세요. "
        "제품의 형태, 재질, 색상, 구도, 강조할 포인트, 배경 느낌을 중심으로 2~3문장으로 적어 주세요."
    )
    payload = {
        "model": settings.image_validator_model_name or settings.openai_vision_model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": reference_image_data_url}},
                ],
            }
        ],
        "temperature": 0,
        "max_completion_tokens": 400,
    }

    try:
        async with httpx.AsyncClient(timeout=settings.llm_timeout_seconds) as client:
            response = await client.post(
                f"{settings.openai_base_url.rstrip('/')}/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            response.raise_for_status()
            body = response.json()
            content = body["choices"][0]["message"]["content"]
            if isinstance(content, str):
                return content.strip()
    except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError):
        return None

    return None


def _product_visual_cues(product_name: str, copy: AdCopyResponse) -> list[str]:
    cues: list[str] = []
    for feature in copy.visual_brief.feature_visualization:
        if product_name in feature.feature_text:
            cues.extend(feature.visual_translation)
    if not cues:
        for feature in copy.visual_brief.feature_visualization:
            cues.extend(feature.visual_translation[:2])
    return list(dict.fromkeys(cue for cue in cues if cue))


def _product_identity_description(product_name: str, copy: AdCopyResponse) -> str:
    cues = _product_visual_cues(product_name, copy)
    identity_rules = [
        "interpret the product name literally",
        "preserve the exact user-entered product identity",
        "show the correct shape, material, texture, color, package, garnish, or serving style implied by the product name",
        "do not substitute it with a visually similar but different product",
    ]
    details = ", ".join([*identity_rules, *cues])
    return f"{product_name} ({details})"


def _describe_visualized_product(product: ProductVisual) -> str:
    visual_description = ", ".join(product.visual_description)
    serving_style = ", ".join(product.serving_style)
    must_show = ", ".join(product.must_show)
    return (
        f"- {product.original_name}: {product.english_name}, category: {product.category}, "
        f"visual details: {visual_description}, serving style: {serving_style}, "
        f"must show: {must_show}"
    )


def _describe_products(
    copy: AdCopyResponse,
    request: AdCopyRequest,
    product_visualization: ProductVisualization | None,
) -> str:
    if product_visualization:
        return "\n".join(
            _describe_visualized_product(product)
            for product in product_visualization.products
        )

    products = copy.visual_brief.products_to_show
    if not products:
        products = [
            type(
                "FallbackProduct",
                (),
                {
                    "product_name": product_name,
                    "visual_role": "main" if index == 0 else "supporting",
                    "must_be_visible": True,
                },
            )()
            for index, product_name in enumerate(request.product_names)
        ]

    lines = []
    for product in products:
        role = "main product" if product.visual_role == "main" else "supporting product"
        description = _product_identity_description(product.product_name, copy)
        lines.append(
            f"- {description}: {role}, clearly visible in the same scene"
        )
    return "\n".join(lines)


def _describe_features(copy: AdCopyResponse) -> str:
    lines = []
    for item in copy.visual_brief.feature_visualization:
        cues = ", ".join(item.visual_translation) if item.visual_translation else "clear visual cue"
        lines.append(f"- {item.feature_text}: {cues}")
    return "\n".join(lines) if lines else "- No extra feature visualization required"


def _unlisted_product_negative(
    product_visualization: ProductVisualization | None,
) -> str:
    must_not_replace = []
    if product_visualization:
        must_not_replace = [
            item
            for product in product_visualization.products
            for item in product.must_not_replace_with
        ]
    product_specific = ", ".join(dict.fromkeys(must_not_replace))
    return (
        "unlisted product, wrong product, substituted product, unrelated food, "
        "unrelated drink, unrelated object, extra food item, extra beverage, "
        "extra merchandise item, visually similar but incorrect product"
        + (f", {product_specific}" if product_specific else "")
    )


def build_ad_image_prompt(
    copy: AdCopyResponse,
    request: AdCopyRequest,
    product_visualization: ProductVisualization | None = None,
    reference_image_context: str | None = None,
) -> tuple[str, str]:
    brief = copy.visual_brief
    business_type = BUSINESS_TYPE_LABELS.get(request.business_type.value, request.business_type.value)
    palette = ", ".join(_label(PALETTE_LABELS, color) for color in brief.color_palette)
    avoid = ", ".join(brief.avoid) if brief.avoid else "none"
    product_lines = _describe_products(copy, request, product_visualization)
    feature_lines = _describe_features(copy)
    composition = _label(COMPOSITION_LABELS, brief.composition)
    template = settings.image_prompt_template or "generic"
    product_names = ", ".join(request.product_names)
    unrelated_negative = _unlisted_product_negative(product_visualization)

    reference_context_block = ""
    if reference_image_context:
        reference_context_block = f"""

참고 이미지 분석:
{reference_image_context}

이미지 생성 지침:
- 참고 이미지의 핵심 디테일만 반영하고, 제품의 핵심 포인트만 강조하세요.
- 불필요한 배경이나 잡음을 줄이고, 강조할 요소만 선명하게 남기세요.
- 제품의 형태와 색상은 정확하게 유지하고, 나머지 요소는 단순하게 처리하세요.
"""

    image_prompt = f"""전문 상업용 광고 이미지로, 한국 소규모 매장을 위한 실제 사진 같은 이미지로 생성해 주세요.

프롬프트 템플릿:
{template}

다음 제품만 메인 주제로 사용하세요.
모든 제품이 하나의 장면에 함께 보이도록 구성하세요.
제품을 다른 음식, 음료, 물건, 포장지, 상품으로 바꾸지 마세요.
제품명이 한국어이더라도, 이름에 맞는 형태와 재질을 시각적으로 자연스럽게 반영하세요.

제품:
{product_lines}

필수 제품 정체성:
{product_names}

제품 정체성 잠금:
사용자 입력한 제품 정보와 정확히 일치해야 합니다. 일반적인 대체품을 만들지 마세요. 목록에 없는 메인 제품을 추가하지 마세요.

업종:
- {business_type}

강조할 시각 포인트:
{feature_lines}

배경:
{_label(BACKGROUND_LABELS, brief.background)}. 필요하면 부드럽게 흐리게 처리하세요. 평범한 벽, 깨끗한 테이블, 중립적인 실내 공간만 사용하세요.

구도:
{composition}, 세로 4:5 인스타그램 광고 레이아웃, 제품이 중심이 되도록 구성하세요.

카메라:
{_label(CAMERA_LABELS, brief.camera_angle)}, {_label(DEPTH_LABELS, brief.depth_of_field)}, 전문 상업용 식음료 촬영 느낌의 렌즈를 사용하세요.

조명:
{_label(LIGHTING_LABELS, brief.lighting)}.

스타일:
전문 상업용 제품 광고 사진, 현실적이고 깔끔하며 현대적이고 따뜻하고 세밀한 디테일, 프리미엄하지만 친근한 지역 상점 분위기. 음식이나 음료라면 식욕을 자극하는 식음료 스타일로, 물건이라면 깔끔한 제품 사진 스타일로 표현하세요.

색상 팔레트:
{palette}

여백:
{_label(EMPTY_SPACE_LABELS, brief.empty_space)}.

광고 방향:
제품 자체를 중심으로 보여 주세요. 나중에 텍스트를 올릴 수 있도록 여백을 남기세요. 읽을 수 있는 텍스트, 가짜 텍스트, 한국어, 영어, 로고, 메뉴판, 간판, 포스터, 라벨, 브랜드 마크, 워터마크는 넣지 마세요. 배경에는 타이포그래피를 남기지 마세요.

품질:
고해상도, 프리미엄 상업용 식음료 사진, 전문적인 SNS 캠페인 이미지, 현실적인 질감, 식욕을 자극하는 스타일.

추가 회피 요소:
{avoid}{reference_context_block}
"""
    negative_prompt = (
        "읽을 수 있는 텍스트, 한국어 글자, 영어 글자, 로고, 워터마크, 브랜드 마크, "
        "메뉴판, 가게 간판, 안내판, 벽 포스터, 타이포그래피, 가짜 텍스트, "
        "의미 없는 문자열, 비정상적인 한글, 무작위 사람, 손, "
        "왜곡된 음식, 녹아버린 디저트, 지저분한 테이블, 중복된 객체, 낮은 품질, "
        "흐림, 과노출, 부족한 노출, 만화, 애니메이션, 일러스트, 플라스틱 느낌, "
        "비현실적인 유리, 변형된 디저트, 과도한 채도, 잘못된 해부학, 아티팩트, "
        f"잘린 제품, {unrelated_negative}"
    )
    return image_prompt, negative_prompt
