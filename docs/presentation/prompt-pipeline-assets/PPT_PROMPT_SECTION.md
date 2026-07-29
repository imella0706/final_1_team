# BrandMate 프롬프트 파이프라인 PPT 자료

## 한 문장 요약

BrandMate는 LLM이 광고 문구와 이미지 프롬프트를 한 번에 자유롭게 생성하지 않도록 **전략 → 카피 → Visual Brief → Prompt Normalizer → 이미지 생성 → Vision 검수**로 역할을 분리했습니다.

---

## 슬라이드 1. 프롬프트 설계 개요

### 제목

**구조화된 프롬프트로 광고 품질을 통제하다**

### 본문

- 소상공인이 입력한 상품·매장·타깃 정보를 구조화된 JSON으로 전달
- LLM은 광고 전략, 고객 노출 문구, 이미지 제작 지시를 분리해 반환
- 백엔드는 Visual Brief를 이미지 모델용 영어 프롬프트로 정규화
- Vision 모델이 결과 이미지를 검수하고 필요한 경우 한 번 재생성

### 발표 멘트

> 모델에게 “광고 하나 만들어줘”라고 요청하는 방식이 아니라, 각 단계의 역할과 출력 형식을 고정했습니다. 덕분에 GPT와 Hugging Face 모델을 교차 사용해도 같은 기준으로 결과를 비교할 수 있습니다.

### 사용할 이미지

- 배경 또는 우측 비주얼: `00-prompt-pipeline-hero.png`
- 제목은 이미지의 위쪽 여백에 PPT에서 직접 입력

---

## 슬라이드 2. 왜 프롬프트를 분리했는가

### 제목

**자유 형식 프롬프트의 문제를 구조화로 해결**

### 기존 문제

- 상품명, 가격, 운영시간 같은 필수 정보 누락
- 광고 문구와 내부 작업 지시가 섞여 고객에게 노출
- 이미지 모델이 원본 음식의 모양·재료·개수를 임의로 변경
- 모델마다 출력 형식이 달라 공정한 비교가 어려움
- 깨진 한글, 임의 로고, 워터마크, 추가 음식 생성

### 해결 방법

- 필수 정보는 JSON 필드와 검증 규칙으로 고정
- 고객용 카피와 이미지 제작용 Visual Brief를 분리
- Visual Brief의 구도·조명·배경은 Enum 값만 허용
- 이미지 프롬프트는 백엔드가 동일한 템플릿으로 생성
- Negative Prompt와 Vision QA로 생성 오류를 억제

### 발표 멘트

> 특히 로컬 소형 LLM은 긴 자유 형식 지시에서 필수 정보를 빠뜨리는 경우가 있었습니다. 그래서 모델의 창의성이 필요한 부분과 반드시 지켜야 하는 부분을 분리했습니다.

---

## 슬라이드 3. 전체 프롬프트 파이프라인

### 제목

**하나의 요청, 여섯 단계의 통제**

### 단계

1. **입력 JSON**: 가게명, 상품, 특징, 타깃, 채널, 모델
2. **Marketing Strategy**: 핵심 메시지와 고객 감정 정의
3. **Copywriting**: 제목, 본문, CTA, 해시태그 생성
4. **Visual Brief**: 상품, 구도, 조명, 배경, 여백 구조화
5. **Prompt Normalizer**: 영어 이미지 프롬프트와 Negative Prompt 생성
6. **Image Generation & Vision QA**: 이미지 생성, 검수, 필요 시 한 번 재생성

### 사용할 이미지

- 전체 슬라이드: `01-prompt-pipeline-overview.svg`

### 발표 멘트

> API 호출 수를 줄이기 위해 전략·카피·Visual Brief는 하나의 LLM 호출 안에서 생성합니다. 이미지 Prompt Normalizer는 모델 호출이 아니라 백엔드의 결정론적 코드로 실행합니다.

---

## 슬라이드 4. 입력과 출력 JSON

### 제목

**JSON을 모델 간 공통 계약으로 사용**

### 입력 JSON에서 관리하는 값

- 매장: `business_name`, `business_type`
- 상품: `product_names`, `features`, `product_price`
- 고객: `age_groups`, `target_audiences`, `interests`
- 채널: `instagram`, `naver_blog`
- 제약: `required_terms`, `prohibited_terms`
- 모델: `copy_model`, `vision_model`, `image_model`

### 출력 JSON에서 관리하는 값

- 전략: `marketing_strategy`
- 문구: `headlines`, `body_copies`, `ctas`, `hashtags`
- 이미지 설계: `visual_brief`
- 검증: `validation_check`, `safety_notes`
- 추적: `model`, `latency_ms`, `attempts`, `output_repaired`

### 사용할 이미지

- 전체 슬라이드: `02-json-contract.svg`
- 상세 코드가 필요하면 `sample-input.json`, `sample-llm-output.json` 사용

### 발표 멘트

> JSON은 단순 저장 형식이 아니라 모델 간 공통 인터페이스입니다. 어떤 LLM을 사용하더라도 같은 필드를 반환하게 해 모델 교체, 검증, 재시도, 성능 비교가 가능합니다.

---

## 슬라이드 5. Visual Brief와 Enum

### 제목

**LLM은 이미지 문장이 아니라 Visual Brief를 작성**

### Visual Brief 핵심 필드

| 필드 | 역할 | 예시 |
|---|---|---|
| `products_to_show` | 화면에 반드시 보여야 할 상품 | 크림빵, main, visible |
| `feature_visualization` | 상품 특징을 시각 단서로 변환 | 아침 제작 → 갓 만든 느낌 |
| `camera_angle` | 카메라 시점 | `45_degree_close_up` |
| `composition` | 상품 배치 | `centered_product_hero` |
| `lighting` | 조명 | `soft_natural_window_light` |
| `background` | 매장 맥락 | `minimal_korean_local_cafe` |
| `empty_space` | 포스터 문구 여백 | `poster_safe_margin` |
| `avoid` | 제외 요소 | text, logo, people |

### Enum을 사용한 이유

- 모델마다 다른 표현을 하나의 기준으로 통일
- 허용하지 않은 구도와 배경을 줄임
- 동일 조건으로 GPT Image, SDXL, FLUX 비교 가능
- 백엔드에서 안정적으로 영어 이미지 프롬프트로 매핑

### 사용할 이미지

- 전체 슬라이드: `03-prompt-normalizer.svg`

---

## 슬라이드 6. 이미지 프롬프트 정규화

### 제목

**백엔드가 동일한 이미지 프롬프트를 생성**

### Positive Prompt 구성

1. `Task`: 광고 이미지 생성인지 원본 사진 보정인지 선언
2. `Products`: 표시할 상품과 특징
3. `Product Identity Lock`: 상품 교체 방지
4. `Composition / Camera / Lighting / Background`
5. `Poster Text Plan`: 글자 삽입용 여백만 확보
6. `Priority`: 어떤 조건을 가장 먼저 지킬지 순서 지정

### Negative Prompt 구성

```text
No readable text. No logo. No watermark.
No people. No hands. No extra food.
No product substitution. No gibberish text.
No malformed Hangul.
```

### 원본 사진이 있을 때 추가되는 규칙

- 음식의 모양, 개수, 재료, 토핑, 접시, 배치, 카메라 각도 유지
- 음식 자체를 재생성하지 않고 조명·노출·색온도만 보정
- 원본에 없는 음식이나 소품을 추가하지 않음

### 발표 멘트

> LLM별로 이미지 프롬프트 문장력이 달라 생기는 변수를 줄이기 위해, 최종 이미지 프롬프트는 백엔드가 동일한 규칙으로 생성합니다.

---

## 슬라이드 7. Vision 검수와 재생성

### 제목

**생성 후에도 JSON으로 품질을 검사**

### Vision QA 출력

```json
{
  "valid": false,
  "warnings": ["원본 음식의 형태가 변경됨"],
  "regeneration_prompt_suffix": "Preserve the original food shape exactly."
}
```

### 동작

- `valid=true`: 최종 결과 저장
- `valid=false`: 경고와 수정 지시를 이미지 프롬프트에 추가
- 최대 한 번 재생성하여 무한 반복 방지
- 결과 JSON에 경고, 재생성 횟수, 사용 모델, 소요 시간 저장

### 사용할 이미지

- 왼쪽: `04-reference-photo-before.jpg`
- 가운데: `05-reference-photo-early-result.png`
- 오른쪽 설명: “원본 음식이 다른 형태로 바뀐 초기 결과 → Identity Lock 강화”

### 주의

이 비교 이미지는 “좋은 최종 결과”가 아니라 **프롬프트 개선이 필요했던 실제 사례**로 사용합니다.

---

## 슬라이드 8. 결과 예시와 핵심 효과

### 제목

**같은 구조로 여러 모델을 교차 평가**

### 사용할 이미지

- 우측: `06-generated-ad-example.jpg`

### 좌측 핵심 효과

- **일관성**: 모델이 달라도 동일한 JSON과 프롬프트 계약 사용
- **재현성**: 입력, 프롬프트, 모델, 소요 시간, 결과물을 함께 저장
- **안전성**: 금지어, 깨진 한글, 임의 상품 추가를 검증
- **확장성**: Instagram, Naver Blog, 이미지 광고, 음성 광고로 확장
- **평가 가능성**: LLM·Vision·이미지 모델의 영향을 단계별로 비교

### 마무리 문장

> 프롬프트를 문장이 아니라 파이프라인으로 설계해, 소상공인 광고 생성의 품질과 재현성을 함께 확보했습니다.

---

## 파일 사용 안내

- SVG는 PowerPoint에 드래그하면 선명한 벡터 이미지로 삽입됩니다.
- PNG/JPG는 16:9 슬라이드에서 자르기 기능을 사용해 배치합니다.
- JSON 예시는 발표용으로 핵심 필드만 축약한 버전입니다.
- 실제 구현 근거:
  - `apps/api/app/modules/ad_copy/prompt.py`
- `apps/api/app/modules/ad_copy/schemas.py`
- `apps/api/app/extensions/ad_content/image_prompt.py`
- `apps/api/app/extensions/ad_content/image_validator.py`
