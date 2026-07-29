# Prompt Strategy

이 프로젝트는 소상공인 광고 콘텐츠 자동 생성을 위해 `프롬프트 4개 + 출력 JSON 구조`를 기준으로 설계합니다. 핵심은 모델이 한 번에 광고 문구와 이미지 프롬프트를 자유롭게 만들지 않게 하고, 전략, 카피, 비주얼 브리프, 이미지 프롬프트 정규화를 분리하는 것입니다.

## 최종 파이프라인

```text
브라우저 입력
  -> Marketing Strategy Prompt
  -> Copywriting Prompt
  -> Visual Brief Prompt
  -> Prompt Normalizer
  -> Image Generation Model
```

현재 백엔드는 API 호출 수를 늘리지 않기 위해 1~3단계 지시문을 `app/modules/ad_copy/prompt.py`의 단일 모델 요청 안에 넣고, 4단계 Prompt Normalizer는 `app/extensions/ad_content/image_prompt.py`에서 결정론적으로 실행합니다.

## 1. Marketing Strategy Prompt

역할: 한국 소상공인 광고 전략가

목표:

- 입력값을 분석해 명확한 마케팅 전략 생성
- 최종 광고 문구와 이미지 프롬프트는 작성하지 않음
- `features`의 모든 항목을 필수 판매 포인트로 유지
- `product_names`와 `features`를 요약, 삭제, 치환하지 않음
- 내부 라벨을 자연스러운 한국어로 변환

주요 출력:

- `business_summary`
- `mandatory_products`
- `mandatory_features`
- `core_message`
- `customer_emotion`
- `marketing_angle`
- `recommended_cta_direction`
- `avoid_points`

## 2. Copywriting Prompt

역할: 한국어 광고 카피라이터

목표:

- 실제 고객에게 보여줄 자연스러운 한국어 광고 문구 생성
- 모든 상품명을 최소 1회 이상 포함
- 모든 `feature_text`를 `body_copies`에 원문 그대로 최소 1회 포함
- 시간 정보 삭제 금지
- 금지어 사용 금지
- 깨진 한국어, 무의미한 표현, 임의 외국어 혼합 금지
- 해시태그는 `#`로 시작하고 한국어 중심으로 작성

주요 출력:

- `headlines`
- `body_copies`
- `ctas`
- `hashtags`
- `validation_check`

## 3. Visual Brief Prompt

역할: 광고 아트 디렉터

목표:

- 최종 이미지 프롬프트가 아닌 구조화된 비주얼 브리프 생성
- 모든 상품이 같은 장면 안에서 보이도록 지정
- 모든 feature를 이미지로 표현 가능한 단서로 변환
- 카메라, 구도, 조명, 배경, 색감, 심도, 여백은 정해진 enum 값만 사용
- 읽을 수 있는 글자, 로고, 간판, 메뉴판, 워터마크 제외

허용 enum:

```text
camera_angle:
- 45_degree_close_up
- eye_level_close_up
- top_down_flat_lay
- macro_detail
- three_quarter_product_shot

composition:
- centered_product_hero
- two_product_set
- tray_set_composition
- rule_of_thirds
- poster_with_empty_space

lighting:
- soft_natural_window_light
- warm_morning_light
- warm_afternoon_light
- soft_studio_light
- cozy_indoor_light

background:
- minimal_korean_local_cafe
- wooden_cafe_table
- clean_bakery_counter
- warm_restaurant_table
- cozy_pub_table

color_palette:
- warm_beige_cream
- soft_pink_peach
- brown_cream_gold
- fresh_fruit_tones
- premium_neutral_tones

depth_of_field:
- shallow_depth_of_field
- medium_depth_of_field
- sharp_product_soft_background

empty_space:
- top_20_percent
- right_25_percent
- left_25_percent
- upper_right_corner
- poster_safe_margin
```

주요 출력:

- `products_to_show`
- `feature_visualization`
- `camera_angle`
- `composition`
- `lighting`
- `background`
- `color_palette`
- `depth_of_field`
- `empty_space`
- `avoid`

## 4. Prompt Normalizer

역할: FLUX/SDXL/Openjourney용 이미지 프롬프트 정규화기

위치:

```text
app/extensions/ad_content/image_prompt.py
```

기능:

- 구조화된 `visual_brief`를 영어 이미지 프롬프트로 변환
- 모든 상품이 명확히 보이도록 서술
- `features`에서 나온 시각 단서를 사진 표현으로 변환
- FLUX가 이해하기 쉬운 상업 사진 표현으로 정리
- `negative_prompt`에 글자, 로고, 워터마크, 사람, 손, 왜곡, 저품질 요소를 분리

## 출력 JSON 구조

```json
{
  "marketing_strategy": {
    "business_summary": {
      "business_name": "",
      "business_type_korean": "",
      "situation_korean": "",
      "target_audiences_korean": [],
      "tone_korean": "",
      "channel_korean": ""
    },
    "mandatory_products": [
      {
        "product_name": "",
        "role": "primary"
      }
    ],
    "mandatory_features": [
      {
        "feature_text": "",
        "copy_usage_rule": "본문 문구에 원문 그대로 포함해야 함",
        "visual_usage_rule": "이미지에서 시각적으로 표현 가능한 형태로 변환해야 함"
      }
    ],
    "core_message": "",
    "customer_emotion": "",
    "marketing_angle": "",
    "recommended_cta_direction": "",
    "avoid_points": []
  },
  "headlines": [],
  "body_copies": [],
  "ctas": [],
  "validation_check": {
    "all_products_included": true,
    "all_features_included": true,
    "prohibited_terms_used": false,
    "visual_brief_uses_enum_only": true,
    "hashtags_removed": true,
    "language_quality": "natural Korean"
  },
  "visual_brief": {
    "products_to_show": [
      {
        "product_name": "",
        "visual_role": "main",
        "must_be_visible": true
      }
    ],
    "feature_visualization": [
      {
        "feature_text": "",
        "visual_translation": []
      }
    ],
    "camera_angle": "",
    "composition": "",
    "lighting": "",
    "background": "",
    "color_palette": [],
    "depth_of_field": "",
    "empty_space": "",
    "avoid": []
  },
  "safety_notes": []
}
```

## 코드 위치

```text
app/modules/ad_copy/prompt.py
app/modules/ad_copy/schemas.py
app/extensions/ad_content/image_prompt.py
app/extensions/ad_content/router.py
```

## 왜 이 구조를 쓰는가

소형 로컬 LLM은 자유 형식 프롬프트에서 상품명, 특징, 시간 정보 같은 필수 정보를 누락하기 쉽습니다. 그래서 `features`는 카피에서 원문 그대로 강제하고, 이미지는 해당 feature를 시각 단서로 바꾼 뒤 영어 사진 프롬프트로 정규화합니다. 이렇게 하면 문구 품질과 이미지 품질을 각각 추적하고 수정할 수 있습니다.
