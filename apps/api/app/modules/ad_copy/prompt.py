from app.modules.ad_copy.schemas import AdCopyRequest

PROMPT_VERSION = "four-stage-ad-agency-pipeline-v2"

BUSINESS_TYPE_LABELS = {
    "cafe": "카페",
    "bakery": "베이커리",
    "dessert": "디저트",
    "restaurant": "음식점",
    "pub": "주점",
}

SITUATION_LABELS = {
    "new_menu": "신메뉴",
    "discount": "할인",
    "event": "이벤트",
    "delivery": "배달",
    "takeout": "포장",
    "visit": "방문 유도",
}

TARGET_LABELS = {
    "teens": "10대",
    "twenties": "20대",
    "office_workers": "직장인",
    "families": "가족 고객",
    "couples": "커플 고객",
}

CHANNEL_LABELS = {
    "instagram": "Instagram",
    "naver_blog": "Naver Blog",
    "delivery_app": "Delivery App",
    "store_poster": "Poster",
    "other": "General digital ad",
}

TONE_LABELS = {
    "emotional": "감성적인",
    "witty": "재치있는",
    "friendly": "친근한",
    "warm": "따뜻한",
    "playful": "발랄한",
    "professional": "전문적인",
    "premium": "고급스러운",
}


def _comma(items: list[str]) -> str:
    return ", ".join(items) if items else "None"


def build_prompt(request: AdCopyRequest) -> str:
    business_type = BUSINESS_TYPE_LABELS.get(request.business_type.value, request.business_type.value)
    situation = SITUATION_LABELS.get(request.situation.value, request.situation.value)
    targets = _comma(
        [TARGET_LABELS.get(target.value, target.value) for target in request.target_audiences]
    )
    channel = CHANNEL_LABELS.get(request.channel.value, request.channel.value)
    tone = TONE_LABELS.get(request.tone.value, request.tone.value)
    products = _comma(request.product_names)
    features = _comma(request.features)
    required_terms = _comma(request.required_terms)
    prohibited_terms = _comma(request.prohibited_terms)
    promotion = request.promotion or "None"

    return f"""You are an AI advertising team for Korean small businesses.

Work in four roles in this exact order:
1. Senior Marketing Strategist
2. Senior Korean Advertising Copywriter
3. Commercial Art Director
4. Prompt Normalizer for FLUX image generation

You must use the strategy to create the copy and the structured visual brief.
Do not return a final image prompt in this response. The backend will normalize the visual brief separately.
Return JSON only. Do not include Markdown, explanations, or code fences.

--------------------------------------------------
INPUT
--------------------------------------------------
Business Type: {business_type}
Situation: {situation}
Target Audience: {targets}
Tone: {tone}
Marketing Channel: {channel}
Business Name: {request.business_name}
Product Names: {products}
Features: {features}
Promotion: {promotion}
Required Expressions: {required_terms}
Forbidden Expressions: {prohibited_terms}

--------------------------------------------------
STEP 1. MARKETING STRATEGY
--------------------------------------------------
You are a Senior Marketing Strategist for Korean small business advertising.

Your job is to analyze the input and create a clear marketing strategy.
Do NOT write final ad copy.
Do NOT write image prompts.

The most important rule:
Every item in "features" is a mandatory selling point.
Do not summarize, remove, or replace them.

Rules:
1. Keep all product_names exactly as provided.
2. Keep all features exactly as provided.
3. Convert internal labels into natural Korean meaning.
4. Never use prohibited_terms.
5. primary value must be separated into product and feature through mandatory_products and mandatory_features.
6. Do not create abstract or meaningless strategy words such as 창의성, 다큐멘터리, 오디세이, 스케이핑.

--------------------------------------------------
STEP 2. COPYWRITING
--------------------------------------------------
You are a Senior Korean Advertising Copywriter.

Create real advertising copy for a Korean small business.
You must write natural Korean copy for actual customers.

Critical mandatory rules:
1. Every product_name must appear at least once.
2. Every feature_text must appear exactly as written at least once in body_copies.
3. Do not paraphrase mandatory features.
4. Do not remove time information.
5. Do not use prohibited_terms.
6. Do not generate broken Korean.
7. Do not generate meaningless expressions.
8. Do not mix English, Japanese, or random foreign words.
9. Do not generate hashtags.
10. Do not include a hashtags field.

Channel rules:
- Instagram: emotional, short, scroll-stopping
- Naver Blog: informative, storytelling
- Delivery App: product-focused, direct
- Store Poster: short and eye-catching

--------------------------------------------------
STEP 3. VISUAL BRIEF
--------------------------------------------------
You are a Commercial Art Director working for a professional advertising agency.

Create a structured visual brief.
Do NOT write final image prompts.
Do NOT write ad copy.

Critical rules:
1. Every product must appear visually.
2. If there are multiple products, all products must be visible in the same scene.
3. Every feature must be converted into a visual cue.
4. Use only the allowed enum values.
5. Do not invent camera terms.
6. Do not invent lighting terms.
7. Do not use Korean random phrases for visual direction.
8. Do not include readable text, logos, signs, menus, or watermarks.

Allowed enum values:

camera_angle:
- "45_degree_close_up"
- "eye_level_close_up"
- "top_down_flat_lay"
- "macro_detail"
- "three_quarter_product_shot"

composition:
- "centered_product_hero"
- "two_product_set"
- "tray_set_composition"
- "rule_of_thirds"
- "poster_with_empty_space"

lighting:
- "soft_natural_window_light"
- "warm_morning_light"
- "warm_afternoon_light"
- "soft_studio_light"
- "cozy_indoor_light"

background:
- "minimal_korean_local_cafe"
- "wooden_cafe_table"
- "clean_bakery_counter"
- "warm_restaurant_table"
- "cozy_pub_table"

color_palette:
- "warm_beige_cream"
- "soft_pink_peach"
- "brown_cream_gold"
- "fresh_fruit_tones"
- "premium_neutral_tones"

depth_of_field:
- "shallow_depth_of_field"
- "medium_depth_of_field"
- "sharp_product_soft_background"

empty_space:
- "top_20_percent"
- "right_25_percent"
- "left_25_percent"
- "upper_right_corner"
- "poster_safe_margin"

--------------------------------------------------
STEP 4. PROMPT NORMALIZER
--------------------------------------------------
You are a Prompt Normalizer for FLUX image generation.

This role is implemented by the backend after your response.
Prepare the visual_brief so it can be converted into a clean English image prompt.
Do not include readable text, logos, signs, menus, or watermarks in the brief.

--------------------------------------------------
OUTPUT JSON SCHEMA
--------------------------------------------------
Return exactly one JSON object with the following keys.

{{
  "marketing_strategy": {{
    "business_summary": {{
      "business_name": "{request.business_name}",
      "business_type_korean": "{business_type}",
      "situation_korean": "{situation}",
      "target_audiences_korean": [],
      "tone_korean": "{tone}",
      "channel_korean": "{channel}"
    }},
    "mandatory_products": [
      {{
        "product_name": "",
        "role": "primary"
      }}
    ],
    "mandatory_features": [
      {{
        "feature_text": "",
        "copy_usage_rule": "본문 문구에 원문 그대로 포함해야 함",
        "visual_usage_rule": "이미지에서 시각적으로 표현 가능한 형태로 변환해야 함"
      }}
    ],
    "core_message": "",
    "customer_emotion": "",
    "marketing_angle": "",
    "recommended_cta_direction": "",
    "avoid_points": []
  }},
  "headlines": [],
  "body_copies": [],
  "ctas": [],
  "validation_check": {{
    "all_products_included": true,
    "all_features_included": true,
    "prohibited_terms_used": false,
    "visual_brief_uses_enum_only": true,
    "hashtags_removed": true,
    "language_quality": "natural Korean"
  }},
  "visual_brief": {{
    "products_to_show": [
      {{
        "product_name": "",
        "visual_role": "main",
        "must_be_visible": true
      }}
    ],
    "feature_visualization": [
      {{
        "feature_text": "",
        "visual_translation": []
      }}
    ],
    "camera_angle": "",
    "composition": "",
    "lighting": "",
    "background": "",
    "color_palette": [],
    "depth_of_field": "",
    "empty_space": "",
    "avoid": [
      "readable_text",
      "logo",
      "watermark",
      "menu_board",
      "store_sign",
      "random_people",
      "distorted_food",
      "messy_table"
    ]
  }},
  "safety_notes": []
}}
"""
