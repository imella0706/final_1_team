import json

import httpx

from app.core.config import settings
from app.extensions.ad_content.product_visualizer import ProductVisual, ProductVisualization
from app.modules.ad_copy.schemas import AdCopyRequest, AdCopyResponse
from app.extensions.ad_content.schemas import BlogImageInput


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


def _parse_json_object(value: str) -> dict[str, object] | None:
    cleaned = value.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:].strip()
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start < 0 or end <= start:
            return None
        try:
            parsed = json.loads(cleaned[start : end + 1])
        except json.JSONDecodeError:
            return None
    return parsed if isinstance(parsed, dict) else None


def _format_blog_photo_notes(metadata: dict[str, object]) -> list[str]:
    notes: list[str] = []
    photos = metadata.get("photos")
    if isinstance(photos, list):
        for item in photos:
            if not isinstance(item, dict):
                continue
            photo_id = str(item.get("photo_id") or "사진").strip()
            photo_type = str(item.get("photo_type") or "기타").strip()
            main_subject = str(item.get("main_subject") or "").strip()
            quality = str(item.get("photo_quality") or "").strip()
            section = str(item.get("recommended_section") or "").strip()
            score = str(item.get("thumbnail_score") or "").strip()
            reason = str(item.get("thumbnail_reason") or "").strip()
            caption = str(item.get("recommended_caption") or "").strip()
            keywords = item.get("seo_keywords")
            keyword_text = ", ".join(str(keyword) for keyword in keywords if keyword) if isinstance(keywords, list) else ""
            notes.append(
                (
                    f"{photo_id}: type={photo_type}, subject={main_subject}, "
                    f"quality={quality}, section={section}, thumbnail_score={score}, "
                    f"thumbnail_reason={reason}, caption={caption}, seo_keywords={keyword_text}"
                ).strip()
            )
    thumbnail = metadata.get("recommended_thumbnail")
    order = metadata.get("recommended_order")
    reason = metadata.get("ordering_reason")
    if thumbnail:
        notes.append(f"대표사진 추천: {thumbnail}")
    if isinstance(order, list) and order:
        notes.append("추천 사진 순서: " + " -> ".join(str(item) for item in order))
    if reason:
        notes.append(f"사진 순서 추천 이유: {reason}")
    return notes


async def describe_blog_images(
    blog_images: list[BlogImageInput],
    copy_request: AdCopyRequest,
) -> tuple[list[str], dict[str, object]]:
    product_names = ", ".join(copy_request.product_names)
    prompt_text = (
        "업로드된 여러 사진을 네이버 블로그 글 작성용 자료로 분석해 주세요.\n"
        f"상호명: {copy_request.business_name}\n"
        f"상품명: {product_names}\n"
        f"블로그 글 목적: {copy_request.blog_purpose or 'None'}\n"
        f"강조할 내용: {', '.join(copy_request.blog_emphasis) or 'None'}\n"
        f"글 스타일: {copy_request.blog_style or 'None'}\n"
        f"SEO 키워드: {', '.join(copy_request.seo_keywords) or 'None'}\n"
        f"글 길이: {copy_request.blog_length or 'None'}\n\n"
        "반드시 JSON 객체 하나만 답하세요. Markdown, 설명, 코드블록은 쓰지 마세요.\n"
        "사진에 없는 정보는 만들지 말고, 보이는 정보만 블로그 작성용 메타데이터로 정리하세요.\n\n"
        "출력 형식:\n"
        "{\n"
        '  "photos": [\n'
        "    {\n"
        '      "photo_id": "사진 번호 또는 파일명",\n'
        '      "photo_type": "외관|실내|메뉴판|대표 메뉴|디저트|음료|기타",\n'
        '      "main_subject": "사진의 핵심 피사체",\n'
        '      "camera_angle": "정면|45도|상단|근접|원거리|기타",\n'
        '      "photo_quality": "초점/밝기/색감/구도에 대한 짧은 평가",\n'
        '      "recommended_section": "도입|매장 소개|대표 메뉴|추가 메뉴|음료|디저트|가격 안내|마무리",\n'
        '      "thumbnail_score": 1,\n'
        '      "thumbnail_reason": "제품 크기, 초점, 색감, 클릭 가능성, 식별성 기준으로 짧게 설명",\n'
        '      "recommended_caption": "블로그 본문에서 사진 아래에 붙일 짧은 설명",\n'
        '      "seo_keywords": ["사진에서 자연스럽게 연결되는 검색 키워드"]\n'
        "    }\n"
        "  ],\n"
        '  "recommended_thumbnail": "대표 사진 id",\n'
        '  "recommended_order": ["사진 id를 블로그 흐름에 맞게 정렬"],\n'
        '  "ordering_reason": "왜 이 순서가 자연스러운지 짧게 설명"\n'
        "}"
    )
    content: list[dict[str, object]] = [{"type": "text", "text": prompt_text}]
    redacted_content: list[dict[str, object]] = [{"type": "text", "text": prompt_text}]
    for image in blog_images[:8]:
        label = f"{image.id}: {image.name or 'uploaded image'}"
        content.append({"type": "text", "text": label})
        content.append({"type": "image_url", "image_url": {"url": image.data_url}})
        redacted_content.append({"type": "text", "text": label})
        redacted_content.append({"type": "image_url", "image_url": {"url": "[blog_image_data_url]"}})

    prompt_record: dict[str, object] = {
        "model": settings.image_validator_model_name or settings.openai_vision_model,
        "messages": [{"role": "user", "content": redacted_content}],
    }
    if not blog_images:
        return [], prompt_record

    api_key = _secret_value(settings.openai_api_key)
    if not api_key:
        return [], prompt_record

    try:
        async with httpx.AsyncClient(timeout=settings.llm_timeout_seconds) as client:
            response = await client.post(
                f"{settings.openai_base_url.rstrip('/')}/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": prompt_record["model"],
                    "messages": [{"role": "user", "content": content}],
                    "temperature": 0,
                    "max_completion_tokens": 1200,
                },
            )
            response.raise_for_status()
            body = response.json()
            result = body["choices"][0]["message"]["content"]
            if isinstance(result, str):
                parsed = _parse_json_object(result)
                if isinstance(parsed, dict):
                    notes = _format_blog_photo_notes(parsed)
                    prompt_record["structured_result"] = parsed
                    return notes[:10], prompt_record
                notes = [line.strip("- ").strip() for line in result.splitlines() if line.strip()]
                return notes[:10], prompt_record
    except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError):
        return [], prompt_record

    return [], prompt_record


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
