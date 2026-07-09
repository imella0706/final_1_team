from app.modules.ad_copy.schemas import AdCopyRequest

PROMPT_VERSION = "four-stage-ad-agency-pipeline-v5-channel-layout"

BUSINESS_TYPE_LABELS = {
    "cafe": "카페",
    "bakery": "베이커리",
    "dessert": "디저트",
    "restaurant": "음식점",
    "pub": "주점",
}

SITUATION_LABELS = {
    "new_menu": "신메뉴",
    "discount": "세트메뉴 할인",
    "event": "이벤트",
    "delivery": "배달",
    "takeout": "포장",
    "visit": "방문 유도",
}

AGE_GROUP_LABELS = {
    "teens": "10대",
    "twenties": "20대",
    "thirties": "30대",
    "forties": "40대",
    "fifties_plus": "50대 이상",
}

TARGET_LABELS = {
    "office_workers": "직장인",
    "students": "학생",
    "middle_school_students": "중학생",
    "high_school_students": "고등학생",
    "college_students": "대학생",
    "families": "가족 고객",
    "couples": "커플 고객",
    "solo": "혼자 방문하는 고객",
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

GENDER_LABELS = {
    "all": "전체",
    "female": "여성",
    "male": "남성",
}

OCCUPATION_GROUP_LABELS = {
    "none": "None",
    "office_worker": "직장인",
    "student": "학생",
    "self_employed": "자영업자",
    "freelancer": "프리랜서",
    "professional": "전문직",
    "homemaker": "주부",
    "job_seeker": "취업준비생",
    "other": "기타",
}


def _comma(items: list[str]) -> str:
    return ", ".join(items) if items else "None"


def _label(labels: dict[str, str], value: str | None) -> str:
    if not value:
        return "None"
    return labels.get(value, value)


def build_prompt(request: AdCopyRequest) -> str:
    business_type = BUSINESS_TYPE_LABELS.get(request.business_type.value, request.business_type.value)
    situation = SITUATION_LABELS.get(request.situation.value, request.situation.value)
    age_groups = _comma(
        [AGE_GROUP_LABELS.get(age.value, age.value) for age in request.age_groups]
    )
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
    gender = _label(GENDER_LABELS, request.gender)
    occupation_group = _label(OCCUPATION_GROUP_LABELS, request.occupation_group)
    product_price = request.product_price or "None"
    interests = _comma(request.interests)
    region = request.region or "None"
    trade_area = request.trade_area or "None"
    audience_detail = request.audience_detail or "None"

    return f"""당신은 한국 소상공인을 위한 AI 광고 제작팀입니다.

아래 순서로 네 가지 역할을 수행하세요.
1. 시니어 마케팅 전략가
2. 시니어 한국어 광고 카피라이터
3. 채널별 게시 형식 설계자
4. 이미지 모델 전달용 비주얼 브리프 정리자

전략을 먼저 세운 뒤, 그 전략을 바탕으로 광고 문구와 구조화된 visual_brief를 작성하세요.
이 응답에서는 최종 이미지 프롬프트를 작성하지 마세요. 최종 이미지 프롬프트는 백엔드가 visual_brief를 이용해 별도로 정규화합니다.
광고 문구와 visual_brief에서 같은 단어와 같은 설명을 반복하지 마세요. 광고 문구는 고객에게 보이는 글에 집중하고, visual_brief는 이미지 모델에 필요한 상품명, 시각 단서, 배치 방향만 담으세요.
반드시 유효한 JSON 객체 하나만 반환하세요. Markdown, 설명, 코드블록은 절대 포함하지 마세요.
JSON의 키 이름과 enum 값은 아래 스키마에 있는 영어 값을 정확히 그대로 사용하세요.
광고 문구, 마케팅 전략 내용, 고객에게 보이는 문장은 자연스러운 한국어로 작성하세요.

--------------------------------------------------
입력 정보
--------------------------------------------------
업종: {business_type}
상황: {situation}
나이대: {age_groups}
타깃 유형: {targets}
성별 타겟: {gender}
직업군: {occupation_group}
관심사: {interests}
지역: {region}
상권: {trade_area}
세부 타겟 메모: {audience_detail}
톤앤매너: {tone}
마케팅 채널: {channel}
상호명: {request.business_name}
상품명: {products}
제품가격: {product_price}
특징/판매 포인트: {features}
프로모션: {promotion}
반드시 포함할 표현: {required_terms}
사용하면 안 되는 표현: {prohibited_terms}

--------------------------------------------------
STEP 1. 마케팅 전략
--------------------------------------------------
당신은 한국 소상공인 광고를 전문으로 하는 시니어 마케팅 전략가입니다.

입력 정보를 분석해 명확한 마케팅 전략을 만드세요.
이 단계에서는 최종 광고 문구를 쓰지 마세요.
이 단계에서는 이미지 프롬프트를 쓰지 마세요.

가장 중요한 규칙:
"features"의 모든 항목은 필수 판매 포인트입니다.
요약하거나 삭제하거나 다른 말로 바꾸지 마세요.
성별, 직업군, 타깃 유형, 관심사, 지역, 상권, 세부 타겟 메모는 핵심 타겟 세분화 정보입니다.
타깃 유형에 학생/중학생/고등학생/대학생이 포함되면 예산감각, 방문 가능 시간대, 친구 동반 여부, 말투의 가벼움을 다르게 해석하세요.
직업군이 직장인/자영업자/프리랜서/전문직/주부/취업준비생이면 생활 리듬, 구매 동기, 방문 맥락, 가격 민감도를 다르게 반영하세요.

규칙:
1. 모든 product_names는 사용자가 입력한 원문 그대로 유지하세요.
2. 모든 features는 사용자가 입력한 원문 그대로 유지하세요.
3. 내부 라벨은 자연스러운 한국어 의미로 해석하세요.
4. prohibited_terms는 절대 사용하지 마세요.
5. 핵심 가치는 mandatory_products와 mandatory_features를 통해 상품과 특징으로 분리하세요.
6. 창의성, 다큐멘터리, 오디세이, 스케이핑처럼 추상적이거나 광고 맥락에 맞지 않는 단어를 만들지 마세요.

--------------------------------------------------
STEP 2. 광고 문구 작성
--------------------------------------------------
당신은 시니어 한국어 광고 카피라이터입니다.

한국 소상공인이 실제 고객에게 사용할 수 있는 광고 문구를 작성하세요.
고객이 자연스럽게 읽을 수 있는 한국어 문장으로 작성하세요.

반드시 지켜야 할 규칙:
1. 모든 product_name은 광고 문구 어딘가에 최소 1회 이상 포함하세요.
2. 모든 feature_text는 body_copies 안에 원문 그대로 최소 1회 이상 포함하세요.
3. 필수 특징을 의역하지 마세요.
4. 기간, 시간, 할인율 같은 정보가 있으면 삭제하지 마세요.
5. prohibited_terms는 사용하지 마세요.
6. 어색하거나 깨진 한국어를 만들지 마세요.
7. 의미 없는 표현을 만들지 마세요.
8. 불필요한 영어, 일본어, 임의의 외국어를 섞지 마세요.
9. hashtags 필드에 광고 채널에 맞는 한국어 해시태그를 3~6개 작성하세요.
10. 해시태그는 #으로 시작하고 공백 없이 작성하세요.
11. 해시태그에도 prohibited_terms를 사용하지 마세요.

채널별 작성 방향:
- Instagram: 인스타 피드 캡션처럼 첫 문장은 짧게, 이어서 상품 매력과 방문/주문 유도를 자연스럽게 작성
- Naver Blog: 블로그 본문처럼 정보성, 스토리텔링, 방문 맥락이 보이도록 문단형 문구 작성
- Delivery App: 배달앱 상품 카드/배너처럼 상품명, 가격/혜택, 주문 유도가 빠르게 보이는 직접적인 문구 작성
- Store Poster: 짧고 눈에 잘 띄는 문구

--------------------------------------------------
STEP 3. 채널별 게시 형식 추천
--------------------------------------------------
당신은 채널별 광고 콘텐츠 편집자입니다.

channel_recommendation을 작성하세요.
고객에게 보여줄 글과 이미지를 어떤 형식으로 배치하면 좋은지 추천합니다.

채널별 추천 방향:
- Instagram: 인스타 피드 게시물 형식. 첫 화면에는 생성 이미지와 짧은 헤드라인을 두고, 캡션에는 본문/CTA/해시태그 순서로 배치하도록 추천하세요.
- Naver Blog: 블로그 글 작성 형식. LLM이 작성한 글을 본문으로 쓰고, 사진은 도입부 대표 이미지와 상품 설명 중간 이미지로 넣으면 좋다고 추천하세요.
- Delivery App: 배달앱 포스터/배너 형식. 상품 이미지 전체를 포스터처럼 쓰고, 앱 화면에서는 헤드라인, 가격/혜택, CTA가 바로 보이도록 추천하세요.
- Store Poster: 매장 포스터 형식. 멀리서도 보이는 한 줄 헤드라인과 큰 상품 이미지를 추천하세요.

--------------------------------------------------
STEP 4. 비주얼 브리프
--------------------------------------------------
당신은 전문 광고 대행사의 상업 광고 아트 디렉터입니다.

구조화된 visual_brief를 작성하세요.
최종 이미지 프롬프트를 쓰지 마세요.
광고 문구를 다시 쓰지 마세요.
visual_brief는 이미지 모델에 넘길 최소 정보입니다. 상품명, 참고 이미지에서 유지할 요소, 상품 배치 방향, 사진/포스터 형식만 남기고 마케팅 문장을 반복하지 마세요.

반드시 지켜야 할 규칙:
1. 모든 상품은 이미지에 시각적으로 등장해야 합니다.
2. 상품이 여러 개라면 모든 상품이 하나의 장면 안에 함께 보여야 합니다.
3. 모든 feature는 이미지에서 표현 가능한 시각 단서로 바꾸세요.
4. 아래 허용된 enum 값만 사용하세요.
5. 임의의 카메라 용어를 만들지 마세요.
6. 임의의 조명 용어를 만들지 마세요.
7. 비주얼 지시문에 무작위 한국어 문구를 넣지 마세요.
8. 읽을 수 있는 글자, 로고, 간판, 메뉴판, 워터마크를 포함하지 마세요.

허용된 enum 값:

camera_angle:
- "45_degree_close_up": 45도 근접 제품 사진
- "eye_level_close_up": 눈높이 근접 제품 사진
- "top_down_flat_lay": 위에서 내려다본 플랫레이
- "macro_detail": 세부 질감이 보이는 매크로 디테일
- "three_quarter_product_shot": 3/4 각도의 제품 사진

composition:
- "centered_product_hero": 제품을 중앙에 둔 주인공 구도
- "two_product_set": 두 상품이 함께 보이는 세트 구도
- "tray_set_composition": 트레이 위에 정리된 세트 구도
- "rule_of_thirds": 삼분할 구도
- "poster_with_empty_space": 텍스트 삽입 여백이 있는 포스터형 구도

lighting:
- "soft_natural_window_light": 부드러운 자연 창가 조명
- "warm_morning_light": 따뜻한 아침 조명
- "warm_afternoon_light": 따뜻한 오후 조명
- "soft_studio_light": 부드러운 스튜디오 조명
- "cozy_indoor_light": 아늑한 실내 조명

background:
- "minimal_korean_local_cafe": 미니멀한 한국 동네 카페 분위기
- "wooden_cafe_table": 깨끗한 나무 카페 테이블
- "clean_bakery_counter": 깔끔한 베이커리 카운터
- "warm_restaurant_table": 따뜻한 음식점 테이블
- "cozy_pub_table": 아늑한 주점 테이블

color_palette:
- "warm_beige_cream": 따뜻한 베이지와 크림 톤
- "soft_pink_peach": 부드러운 핑크와 피치 톤
- "brown_cream_gold": 브라운, 크림, 골드 톤
- "fresh_fruit_tones": 신선한 과일 컬러 톤
- "premium_neutral_tones": 고급스러운 뉴트럴 톤

depth_of_field:
- "shallow_depth_of_field": 얕은 심도
- "medium_depth_of_field": 중간 심도
- "sharp_product_soft_background": 제품은 선명하고 배경은 부드러운 흐림

empty_space:
- "top_20_percent": 상단 20% 여백
- "right_25_percent": 오른쪽 25% 여백
- "left_25_percent": 왼쪽 25% 여백
- "upper_right_corner": 오른쪽 상단 여백
- "poster_safe_margin": 포스터용 안전 여백

--------------------------------------------------
STEP 5. 프롬프트 정규화 준비
--------------------------------------------------
당신은 FLUX 이미지 생성을 위한 프롬프트 정규화 준비자입니다.

이 역할의 최종 처리는 응답 이후 백엔드에서 수행됩니다.
백엔드가 visual_brief를 깔끔한 이미지 프롬프트로 변환할 수 있도록 구조화해 주세요.
brief 안에는 읽을 수 있는 글자, 로고, 간판, 메뉴판, 워터마크를 넣지 마세요.

--------------------------------------------------
출력 JSON 스키마
--------------------------------------------------
아래 키를 가진 JSON 객체 하나만 반환하세요.
키 이름은 반드시 영어 그대로 유지하세요.
배열은 비워 두지 말고, 입력에 맞는 실제 내용을 채우세요.

{{
  "marketing_strategy": {{
    "business_summary": {{
      "business_name": "{request.business_name}",
      "business_type_korean": "{business_type}",
      "situation_korean": "{situation}",
      "age_groups_korean": [],
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
  "hashtags": [],
  "channel_recommendation": {{
    "format_name": "",
    "writing_direction": "",
    "image_direction": "",
    "placement_tip": ""
  }},
  "validation_check": {{
    "all_products_included": true,
    "all_features_included": true,
    "prohibited_terms_used": false,
    "visual_brief_uses_enum_only": true,
    "hashtags_removed": false,
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
