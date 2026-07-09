# BrandMate API

FastAPI 기반 광고 콘텐츠 생성 API입니다. 광고 문구 모델과 이미지 생성 모델을 FastAPI 프로세스 안에 직접 로드하지 않고, OpenAI-compatible endpoint, Hugging Face Router, LM Studio, Diffusers service 등 외부 모델 실행 계층을 API로 호출합니다.

## 주요 Endpoint

```text
GET  /health

GET  /api/v1/ad-copies/models
POST /api/v1/ad-copies/generate

GET  /api/v1/ad-content/image-models
POST /api/v1/ad-content/generate

POST /api/llm/generate
POST /api/image/generate
```

## 설치

저장소 루트에서:

```cmd
cd apps\api
python -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
pip install -e ".[dev]"
copy .env.example .env
```

## `.env` 최소 설정

Hugging Face Router를 사용할 경우:

```env
BRANDMATE_LLM_BASE_URL=https://router.huggingface.co/v1
BRANDMATE_LLM_API_KEY=hf_your_token_here
BRANDMATE_IMAGE_BASE_URL=https://router.huggingface.co/hf-inference
```

LM Studio를 사용할 경우:

```env
BRANDMATE_LOCAL_LLM_BASE_URL=http://localhost:1234/v1
BRANDMATE_LOCAL_LLM_API_KEY=

BRANDMATE_MISTRAL_MODEL=lm_studio_mistral_model_id
BRANDMATE_GEMMA_MODEL=lm_studio_gemma_model_id
BRANDMATE_PHI_MODEL=lm_studio_phi_model_id
BRANDMATE_SOLAR_MODEL=lm_studio_solar_model_id
```

LM Studio 모델 ID 확인:

```cmd
curl http://localhost:1234/v1/models
```

이미지 모델 설정:

```env
BRANDMATE_FLUX_MODEL=black-forest-labs/FLUX.1-schnell
BRANDMATE_SDXL_MODEL=stabilityai/stable-diffusion-xl-base-1.0
BRANDMATE_OPENJOURNEY_MODEL=prompthero/openjourney
```

Product Visual Database는 선택 기능입니다.

```env
BRANDMATE_REFERENCE_SEARCH_ENABLED=false
BRANDMATE_REFERENCE_SOURCE=wikimedia
BRANDMATE_REFERENCE_MAX_RESULTS=3
BRANDMATE_PRODUCT_VISUAL_DB_PATH=product_visual_profiles.sqlite3
BRANDMATE_PEXELS_API_KEY=
BRANDMATE_UNSPLASH_ACCESS_KEY=
```

`BRANDMATE_REFERENCE_SEARCH_ENABLED=true`이면 기본값 `wikimedia`를 사용합니다. Pexels/Unsplash를 선택할 때만 각각 API 키가 필요합니다.

## 서버 실행

프론트까지 한 번에 실행하려면 저장소 루트에서:

```cmd
start-brandmate.cmd
```

API만 따로 실행하려면:

```cmd
cd apps\api
.venv\Scripts\python.exe -m uvicorn app.extensions.ad_content.main:app --host 127.0.0.1 --port 8000
```

상태 확인:

```cmd
curl http://127.0.0.1:8000/health
```

Swagger:

```text
http://127.0.0.1:8000/docs
```

## 광고 콘텐츠 통합 요청 예시

```cmd
curl -X POST http://127.0.0.1:8000/api/v1/ad-content/generate ^
  -H "Content-Type: application/json" ^
  -d "{\"copy\":{\"model\":\"Qwen/Qwen2.5-7B-Instruct\",\"business_name\":\"오후의 조각\",\"business_type\":\"cafe\",\"situation\":\"new_menu\",\"target_audiences\":[\"twenties\"],\"tone\":\"friendly\",\"product_names\":[\"수제 딸기 티라미수\",\"피치에이드\"],\"features\":[\"매일 아침 직접 만드는 디저트\",\"평일 오전 11시부터 오후 2시까지 런치 세트 운영\"],\"channel\":\"instagram\",\"promotion\":null,\"required_terms\":[],\"prohibited_terms\":[\"최고\",\"무조건\"]},\"image_model\":\"black-forest-labs/FLUX.1-schnell\",\"image_width\":1024,\"image_height\":1280}"
```

응답에는 다음 정보가 포함됩니다.

```text
copy
ad_copy
marketing_strategy
visual_brief
product_visualization
image_prompt
negative_prompt
image
validation
models
```

## 광고 콘텐츠 파이프라인

```text
Input Validator
-> Marketing + Copy + Visual Brief LLM
-> Output Validator
-> Product Visualizer
-> Product Visual Database
-> Prompt Normalizer
-> Image Generation Model
-> Image Validator
```

## 모듈 설명

```text
app/modules/ad_copy/
  prompt.py              광고 문구/전략/비주얼 브리프 LLM prompt
  input_validator.py     한국어 입력값 정규화
  output_validator.py    LLM 출력 검증, 재시도, fallback
  service.py             LLM 호출 service

app/extensions/ad_content/
  router.py              광고 문구 + 이미지 생성 통합 endpoint
  image_service.py       이미지 모델 호출
  image_prompt.py        최종 image prompt 및 negative prompt 생성
  prompt_normalizer.py   Product Visualizer 출력과 visual brief 연결
  product_visualizer.py  상품명 -> 시각 정보 JSON 변환
  reference_search.py    Wikimedia/Pexels/Unsplash reference metadata 검색
  reference_analyzer.py  reference metadata -> 시각 특징 추출
  reference_store.py     SQLite Product Visual DB
  image_validator.py     이미지 검증 hook
```

## 기준 브랜치와의 차이

기준 브랜치:

```text
origin/feature/ad-copy-model-integration
```

현재 브랜치에는 광고 문구 생성 기능 외에 이미지 생성 모델 통합, Product Visualizer, Product Visual DB, 브라우저 통합 화면, 모델 런타임 문서가 추가되었습니다.

상세 문서:

```text
app/modules/model_runtime/docs/CHANGES_FROM_AD_COPY_MODEL_BRANCH.md
```

## 테스트

```cmd
cd apps\api
.venv\Scripts\python.exe -m pytest
.venv\Scripts\python.exe -m ruff check app tests
```

## 관련 README

- 광고 콘텐츠 확장 모듈: `app/extensions/ad_content/README.md`
- 광고 문구 모듈: `app/modules/ad_copy/README.md`
- 모델 런타임 구조: `app/modules/model_runtime/README.md`
- LLM 실행 방식: `app/modules/model_runtime/llm/README.md`
- 이미지 실행 방식: `app/modules/model_runtime/image/README.md`
- 광고 콘텐츠 파이프라인: `app/modules/model_runtime/docs/AD_CONTENT_PIPELINE_README.md`
- 프롬프트 전략: `app/modules/model_runtime/docs/PROMPT_STRATEGY.md`
- 실패 원인 분석: `app/modules/model_runtime/docs/FAILURE_ANALYSIS.md`
- 배포 개선 방향: `app/modules/model_runtime/docs/DEPLOYMENT_NOTES.md`
