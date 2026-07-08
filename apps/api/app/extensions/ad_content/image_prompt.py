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


def _clip_product_names(
    request: AdCopyRequest,
    product_visualization: ProductVisualization | None,
) -> str:
    if product_visualization:
        names = [
            product.english_name.strip()
            for product in product_visualization.products
            if product.english_name.strip()
        ]
    else:
        names = [
            product_name.strip()
            for product_name in request.product_names
            if product_name.strip()
        ]

    if not names:
        return "the requested products"
    if len(names) == 1:
        return names[0]
    if len(names) == 2:
        return f"{names[0]} and {names[1]}"
    return f"{', '.join(names[:-1])}, and {names[-1]}"


def build_clip_eval_prompt(
    copy: AdCopyResponse,
    request: AdCopyRequest,
    product_visualization: ProductVisualization | None = None,
) -> str:
    brief = copy.visual_brief
    products = _clip_product_names(request, product_visualization)
    background = _label(BACKGROUND_LABELS, brief.background).split(",")[0]

    # [Design Intent] CLIP text encoder는 입력 길이가 짧다. 이미지 생성용 전체 prompt를
    # 그대로 평가에 넣으면 핵심 상품명이 잘리거나 token limit 오류가 난다. 그래서 CLIP에는
    # 케이스별 상품/구도/조명만 담은 짧은 평가 전용 prompt를 사용한다.
    return (
        "Commercial food advertising photo showing "
        f"{products} together on a {background}, "
        f"{_label(LIGHTING_LABELS, brief.lighting)}, "
        f"{_label(CAMERA_LABELS, brief.camera_angle)}, "
        "realistic premium product photography, no readable text."
    )


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

    image_prompt = f"""A photorealistic commercial advertising image for a Korean local business.

Prompt template:
{template}

Only the listed user-entered products may appear as the main subjects.
The image must clearly show every listed product together in one scene.
Do not replace the listed products with other food, drinks, objects, packages, or merchandise.
If a product name is not English, infer the product visually from the original product name and visual cues without inventing a different product.

Products:
{product_lines}

Required exact product identities:
{product_names}

Product identity lock:
The generated image must match the exact listed product identities. Do not create a generic substitute. Do not add any main product that is not in the list.

Business type:
- {business_type}

Feature visual cues:
{feature_lines}

Background:
{_label(BACKGROUND_LABELS, brief.background)}, softly blurred where appropriate. Use a plain wall, clean tabletop, or neutral interior only.

Composition:
{composition}, vertical 4:5 Instagram advertisement layout, product-centered styling.

Camera:
{_label(CAMERA_LABELS, brief.camera_angle)}, {_label(DEPTH_LABELS, brief.depth_of_field)}, professional commercial food photography lens look.

Lighting:
{_label(LIGHTING_LABELS, brief.lighting)}.

Style:
Professional commercial product advertising photography, realistic, clean, modern, emotional, cozy, high detail, premium but approachable local business mood. If the products are food or drinks, use appetizing food and beverage styling. If the products are objects, use clean product photography styling.

Color palette:
{palette}

Empty space:
{_label(EMPTY_SPACE_LABELS, brief.empty_space)}.

Advertising direction:
Focus on the products, not people. Leave negative space for later text overlay. Do not include readable text, fake text, gibberish letters, Korean Hangul, English letters, logos, menus, signs, signboards, wall posters, labels, brand marks, or watermarks. Keep the background free of any typography.

Quality:
High-resolution, premium commercial food photography, professional social media campaign image, realistic textures, appetizing styling.

Additional avoid list from art direction:
{avoid}
"""
    negative_prompt = (
        "readable text, Korean letters, English letters, logo, watermark, brand mark, "
        "menu board, store sign, signboard, wall poster, typography, fake text, "
        "gibberish text, pseudo letters, malformed Hangul, random people, hands, "
        "distorted food, melted dessert, messy table, duplicate objects, low quality, "
        "blurry, overexposed, underexposed, cartoon, anime, illustration, plastic texture, "
        "unnatural glass, deformed dessert, oversaturated colors, bad anatomy, artifacts, "
        f"cropped product, {unrelated_negative}"
    )
    return image_prompt, negative_prompt
