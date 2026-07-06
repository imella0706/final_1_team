# Ad Content Pipeline README

이 문서는 소상공인 광고 콘텐츠 생성 서비스에 적용된 실무형 생성 AI 파이프라인을 설명합니다.

## 적용된 흐름

```text
Browser
  -> Input Validator Python
  -> Marketing + Copy + Visual 생성 LLM 1회 호출
  -> Output Validator Python
  -> Prompt Normalizer Python
  -> Image Generation Model
  -> Image Validator Python
  -> 최종 결과 반환
```

기존 endpoint 이름과 주요 request 필드는 유지했습니다.

```text
POST /api/v1/ad-content/generate
POST /api/v1/ad-copies/generate
```

## 코드 위치

```text
app/modules/ad_copy/input_validator.py
app/modules/ad_copy/prompt.py
app/modules/ad_copy/output_validator.py
app/extensions/ad_content/product_visualizer.py
app/modules/ad_copy/service.py
app/extensions/ad_content/prompt_normalizer.py
app/extensions/ad_content/image_prompt.py
app/extensions/ad_content/image_validator.py
app/extensions/ad_content/router.py
```

## 1. Input Validator

위치:

```text
app/modules/ad_copy/input_validator.py
```

역할:

- 한국어 선택값을 내부 enum 값으로 변환
- 상품명, 특징, 필수 표현, 금지 표현 리스트 정리
- 빈 문자열 제거
- 기존 request schema 필드명 유지

예시:

```text
카페 -> cafe
신메뉴 -> new_menu
20대 -> twenties
직장인 -> office_workers
감성적 -> emotional
재치있는 -> witty
인스타그램 -> instagram
```

`AdCopyRequest`의 Pydantic validator에서 이 모듈을 호출하므로, 브라우저가 한국어 선택값을 보내도 내부 enum으로 정규화됩니다.

## 2. LLM Prompt

위치:

```text
app/modules/ad_copy/prompt.py
```

광고 문구 생성 모델은 특정 모델로 고정하지 않습니다. 선택된 모델은 기존 model registry와 환경 변수 설정을 통해 OpenAI-compatible API, Hugging Face Router, LM Studio, vLLM, Ollama 등으로 바꿀 수 있습니다.

LLM은 한 번의 호출로 아래 세 가지를 생성합니다.

- `marketing_strategy`
- `headlines`, `body_copies`, `ctas`
- `visual_brief`

해시태그는 생성하지 않으며, 출력 JSON에도 `hashtags` 필드를 포함하지 않습니다.

## 3. Output Validator

위치:

```text
app/modules/ad_copy/output_validator.py
```

검증 규칙:

- 모든 `product_names`가 headline, body copy, CTA 중 최소 한 곳에 포함되어야 함
- 모든 `features`가 `body_copies` 안에 원문 그대로 포함되어야 함
- `prohibited_terms`가 광고 문구나 visual brief에 포함되면 실패
- `visual_brief.products_to_show`에 모든 상품명이 포함되어야 함
- LLM이 `hashtags`를 반환하면 parsing 단계에서 제거

검증 실패 시:

1. 같은 광고 문구 생성 모델에 최대 2회 재시도
2. 2회 재시도 후에도 실패하면 Python fallback copy 생성

Fallback copy는 입력값 기반으로 생성하며, 특정 상품명이나 테스트 문구를 코드에 하드코딩하지 않습니다.

## 4. Product Visualizer

위치:

```text
app/extensions/ad_content/product_visualizer.py
```

역할:

- 이미지 생성 모델이 상품명을 잘못 해석하지 않도록 상품명을 시각 정보 JSON으로 변환
- 사용자가 선택한 광고 문구 LLM을 그대로 사용해 자동 생성
- 선택적으로 공식/라이선스가 명확한 reference image source를 조회하고, 이미지 자체가 아니라 추출된 시각 특징만 DB에 저장
- 특정 상품명 사전에 의존하지 않고 입력 상품명, 특징, visual brief를 바탕으로 추론
- 실패 시 입력값 기반 fallback을 생성해 파이프라인을 계속 진행

입력:

```text
Business Type
Product Names
Features
Visual Brief
```

출력:

```json
{
  "products": [
    {
      "original_name": "",
      "english_name": "",
      "category": "",
      "visual_description": [],
      "serving_style": [],
      "must_show": [],
      "must_not_replace_with": []
    }
  ]
}
```

중요 규칙:

- `original_name`은 사용자가 입력한 상품명 그대로 유지
- `english_name`은 자연스러운 영어 설명으로 생성
- `visual_description`은 맛, 감정, 분위기가 아니라 보이는 특징만 작성
- `serving_style`은 이미지에서 상품이 놓이는 방식을 작성
- `must_show`는 반드시 보여야 할 시각 요소를 작성
- `must_not_replace_with`는 비슷하게 생겼지만 대체되면 안 되는 상품을 작성

### Product Visual Database

기본값은 꺼져 있습니다.

```env
BRANDMATE_REFERENCE_SEARCH_ENABLED=false
BRANDMATE_REFERENCE_SOURCE=wikimedia
BRANDMATE_REFERENCE_MAX_RESULTS=3
BRANDMATE_PRODUCT_VISUAL_DB_PATH=product_visual_profiles.sqlite3
BRANDMATE_PEXELS_API_KEY=
BRANDMATE_UNSPLASH_ACCESS_KEY=
```

동작 방식:

```text
Product Visualizer
  -> SQLite DB 조회
  -> 캐시가 있으면 ProductVisualization으로 사용
  -> 캐시가 없으면 공식/라이선스 명확한 reference source 검색
  -> Reference Analyzer가 시각 특징만 추출
  -> 이미지 파일은 저장하지 않고 visual JSON과 source metadata만 SQLite에 저장
  -> Prompt Normalizer가 저장된 visual JSON을 사용
```

저장 테이블:

```text
product_visual_profiles
- normalized_name
- original_name
- category
- english_name
- visual_description_json
- serving_style_json
- must_show_json
- must_not_replace_with_json
- reference_query
- reference_sources_json
- created_at
- updated_at
```

중요 원칙:

- 웹 이미지 파일 자체를 DB에 저장하지 않습니다.
- `image_url`, `page_url`, `license`, `source`, `attribution` 같은 출처 메타데이터만 저장합니다.
- 최종 prompt에는 특정 이미지를 복제하라는 지시가 아니라 일반 시각 특징만 반영합니다.
- 기본 reference source는 Wikimedia Commons입니다. Pexels/Unsplash는 API 키가 있을 때 사용할 수 있습니다.

## 5. Prompt Normalizer

위치:

```text
app/extensions/ad_content/prompt_normalizer.py
app/extensions/ad_content/image_prompt.py
```

역할:

- `visual_brief` enum 값과 Product Visualizer 출력을 영어 사진/광고 표현으로 변환
- Product Visualizer의 `english_name`, `visual_description`, `serving_style`, `must_show`를 사용
- 모든 상품이 이미지에 포함되도록 명시
- 상품이 중심 피사체가 되도록 명시
- 사람이 중심이 되지 않게 명시
- 읽을 수 있는 글자, 로고, 워터마크, 메뉴판, 간판을 금지
- `negative_prompt` 생성

### 상품 불일치와 가짜 글자 방지

이미지 모델은 사용자가 입력한 상품명을 그대로 받으면 상품 정체성을 잘못 해석할 수 있습니다. 이 경우 입력한 상품 대신 비슷해 보이는 다른 음식, 음료, 물건, 패키지가 생성될 수 있습니다.

이를 줄이기 위해 normalizer는 다음을 수행합니다.

- 입력된 상품명 원문을 `Required exact product identities`로 고정
- Product Visualizer의 상품별 시각 설명을 최종 prompt에 연결
- 음식, 음료, 물건, 패키지, 소품 등 어떤 상품이 들어와도 입력 상품만 주요 피사체로 등장하도록 명시
- Product Visualizer의 `must_not_replace_with`와 입력 목록에 없는 대체 상품, 관련 없는 음식, 관련 없는 음료, 관련 없는 물건을 negative prompt에 추가
- `Korean local cafe background`처럼 글자 생성을 유도할 수 있는 배경 표현을 피하고, `plain softly blurred interior`, `no signs`, `no posters`, `no menu boards`로 정규화
- `fake text`, `gibberish text`, `malformed Hangul`, `signboard`, `wall poster`를 negative prompt에 추가

템플릿은 환경 변수로 교체할 수 있습니다.

```env
BRANDMATE_IMAGE_PROMPT_TEMPLATE=generic
```

지원 방향:

```text
generic
flux
sdxl
stable_diffusion
dalle_compatible
```

현재 구현은 기본값 `generic`을 사용하고, template 이름을 최종 image prompt에 포함해 추후 모델별 템플릿 분기로 확장할 수 있게 했습니다.

## 6. Image Validator

위치:

```text
app/extensions/ad_content/image_validator.py
```

초기 버전은 옵션 hook입니다.

```env
BRANDMATE_IMAGE_VALIDATION_ENABLED=false
BRANDMATE_IMAGE_VALIDATOR_MODEL_NAME=
BRANDMATE_IMAGE_VALIDATION_THRESHOLD=0.24
```

`BRANDMATE_IMAGE_VALIDATION_ENABLED=true`일 때 CLIP 같은 이미지-텍스트 유사도 모델을 연결할 수 있는 위치를 제공합니다. 현재는 특정 CLIP 모델을 코드에 고정하지 않고 설정값으로 확장하도록 분리했습니다.

## 최종 응답 구조

기존 프론트엔드 호환을 위해 `copy`와 `image`는 유지합니다. 동시에 실무형 파이프라인 확인용 필드를 추가했습니다.

```json
{
  "input": {},
  "ad_copy": {
    "headlines": [],
    "body_copies": [],
    "ctas": []
  },
  "copy": {},
  "marketing_strategy": {},
  "visual_brief": {},
  "image": {},
  "image_prompt": "",
  "negative_prompt": "",
  "image_url": "",
  "validation": {
    "input_valid": true,
    "copy_valid": true,
    "image_valid": true,
    "regeneration_count": 0,
    "warnings": []
  },
  "models": {
    "copy_model": "",
    "image_model": "",
    "image_provider": "",
    "image_prompt_template": "",
    "image_validator_model": ""
  }
}
```

## 중요 원칙

- 특정 LLM 모델명을 prompt나 pipeline 코드에 고정하지 않습니다.
- 특정 이미지 생성 모델명을 normalizer 코드에 고정하지 않습니다.
- 사용자가 입력한 상품명과 특징은 삭제하지 않습니다.
- 금지 표현은 광고 문구, visual brief, image prompt, negative prompt에 포함되지 않도록 검증합니다.
- 해시태그는 생성하지 않습니다.
- visual brief는 enum 기반 구조를 유지합니다.
