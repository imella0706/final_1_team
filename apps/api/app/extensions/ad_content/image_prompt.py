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

CHANNEL_IMAGE_DIRECTIONS = {
    "instagram": {
        "format": "Instagram feed image, vertical 4:5",
        "placement": "hero product in the center, clean margin for one short overlay headline",
        "intent": "scroll-stopping product photo for a social feed",
    },
    "naver_blog": {
        "format": "Naver blog editorial product photo, vertical 4:5",
        "placement": "natural representative photo that can sit at the top of a blog post or between paragraphs",
        "intent": "informative blog image that supports written product storytelling",
    },
    "delivery_app": {
        "format": "delivery app promotional poster, vertical 4:5",
        "placement": "full poster-style layout with a large product hero and clean blank zones for price, benefit, and order CTA",
        "intent": "app banner/poster image focused on immediate ordering",
    },
    "store_poster": {
        "format": "in-store promotional poster, vertical 4:5",
        "placement": "large product hero with poster-safe top and bottom margins",
        "intent": "clear poster image visible at a glance",
    },
    "other": {
        "format": "digital product ad image, vertical 4:5",
        "placement": "large product hero with clean negative space",
        "intent": "general product promotion image",
    },
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
) -> tuple[str | None, dict[str, object]]:
    prompt_text = build_reference_image_prompt(copy_request)
    prompt_record: dict[str, object] = {
        "model": settings.image_validator_model_name or settings.openai_vision_model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt_text},
                    {
                        "type": "image_url",
                        "image_url": {"url": "[reference_image_data_url]"},
                    },
                ],
            }
        ],
    }
    if not reference_image_data_url:
        return None, prompt_record

    api_key = _secret_value(settings.openai_api_key)
    if not api_key:
        return None, prompt_record

    payload = {
        "model": prompt_record["model"],
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt_text},
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
                return content.strip(), prompt_record
    except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError):
        return None, prompt_record

    return None, prompt_record


def build_reference_image_prompt(copy_request: AdCopyRequest) -> str:
    product_names = ", ".join(copy_request.product_names)
    channel = _channel_direction(copy_request.channel.value)
    return (
        "업로드된 참고 이미지를 이미지 생성 모델에 전달할 짧은 시각 지시로 정리해 주세요.\n"
        f"사용자 입력 상품명: {product_names}\n"
        f"사용할 채널/방향: {channel['format']} / {channel['placement']}\n\n"
        "아래 3가지만 한국어로 짧게 답하세요.\n"
        "1. 유지할 제품 식별 요소\n"
        "2. 유지할 배치/구도 방향\n"
        "3. 제거하거나 단순화할 배경 요소\n\n"
        "사진에 없는 제품, 특징, 문구는 만들지 마세요."
    )


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
    must_show = _bullet_lines(product.must_show)
    must_not = _bullet_lines(product.must_not_replace_with)
    block = [
        f"- {product.original_name}",
        f"  English: {product.english_name}",
    ]
    if must_show:
        block.extend(["", "  Must show:", must_show])
    if must_not:
        block.extend(["", "  Do not:", must_not])
    return "\n".join(block)


def _bullet_lines(items: list[str]) -> str:
    cleaned = [item.strip() for item in items if item and item.strip()]
    return "\n".join(f"  - {item}" for item in dict.fromkeys(cleaned[:6]))


def _describe_products(
    copy: AdCopyResponse,
    request: AdCopyRequest,
    product_visualization: ProductVisualization | None,
) -> str:
    if product_visualization:
        return "\n".join(
            _describe_visualized_product(product) for product in product_visualization.products
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
        lines.append(
            "\n".join(
                [
                    f"- {product.product_name}",
                    f"  English: {product.product_name}",
                    "",
                    "  Must show:",
                    f"  - {product.product_name}",
                    f"  - {role}",
                    "",
                    "  Do not:",
                    "  - Substitute with a different product",
                ]
            )
        )
    return "\n".join(lines)


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


def _reference_context_block(reference_image_context: str | None) -> str:
    if not reference_image_context:
        return "- No reference image analysis available."

    return f"""Reference image analysis:
{reference_image_context}
"""


def _channel_direction(channel: str) -> dict[str, str]:
    return CHANNEL_IMAGE_DIRECTIONS.get(channel, CHANNEL_IMAGE_DIRECTIONS["other"])


def build_ad_image_prompt(
    copy: AdCopyResponse,
    request: AdCopyRequest,
    product_visualization: ProductVisualization | None = None,
    reference_image_context: str | None = None,
) -> tuple[str, str]:
    brief = copy.visual_brief
    business_type = BUSINESS_TYPE_LABELS.get(
        request.business_type.value, request.business_type.value
    )
    palette = ", ".join(_label(PALETTE_LABELS, color) for color in brief.color_palette)
    product_lines = _describe_products(copy, request, product_visualization)
    composition = _label(COMPOSITION_LABELS, brief.composition)
    template = settings.image_prompt_template or "generic"
    product_names = ", ".join(request.product_names)
    negative_prompt = _build_negative_prompt()
    reference_context = _reference_context_block(reference_image_context)
    channel = _channel_direction(request.channel.value)

    image_prompt = f"""Task:
Create one realistic commercial product ad image for a Korean small business.

Template:
{template}

Reference Image:
{reference_context}

Products:
{product_lines}

Product Identity Lock:
{product_names}

Composition:
- {channel["format"]}
- {channel["intent"]}
- {channel["placement"]}
- {composition}
- {_label(EMPTY_SPACE_LABELS, brief.empty_space)}

Camera:
- {_label(CAMERA_LABELS, brief.camera_angle)}
- {_label(DEPTH_LABELS, brief.depth_of_field)}

Lighting:
- {_label(LIGHTING_LABELS, brief.lighting)}

Background:
- business context: {business_type}
- {_label(BACKGROUND_LABELS, brief.background)}

Style:
- realistic product photography
- clean SNS ad image
- {palette}

Negative prompt:
{negative_prompt}

Priority:
1. Preserve the uploaded reference product identity when it matches Product Identity Lock.
2. Do not add birthday candles, party props, text, or new toppings unless they are clearly visible in the reference image.
3. Treat marketing features as copy strategy, not image objects.
4. Use only the product listed in Product Identity Lock as the main product.
"""
    return image_prompt, negative_prompt


def _build_negative_prompt() -> str:
    return (
        "No readable text. No logo. No watermark. No menu board. "
        "No people. No hands. No extra food. No product substitution. "
        "No birthday candles unless visible in the reference image. "
        "No party props unless visible in the reference image."
    )
