# BrandMate AI

소상공인 입력을 기반으로 광고 문구와 광고 이미지를 생성하는 FastAPI + 정적 프론트엔드 프로젝트입니다.

현재 작업 브랜치:

```text
feature/ai-copy-vision-model-integration
```

비교 기준 브랜치:

```text
feature/ad-copy-model-integration
```

사용자가 언급한 `feature/ai-copy-model-integration`은 원격 저장소에 없고, 실제 원격 브랜치명은 `feature/ad-copy-model-integration`입니다.

## 기준 브랜치와 달라진 점

`feature/ad-copy-model-integration`은 광고 문구 생성 LLM 중심 구조입니다. 현재 브랜치는 여기에 다음 기능을 추가했습니다.

- 브라우저에서 광고 문구 모델과 이미지 생성 모델을 함께 선택
- 광고 문구 생성 후 이미지 생성까지 이어지는 통합 API
- FLUX.1 Schnell, SDXL, Openjourney 이미지 모델 선택 구조
- Product Visualizer 독립 모듈
- Product Visual Database SQLite 캐시
- Wikimedia/Pexels/Unsplash reference image metadata 검색 구조
- Reference Analyzer를 통한 시각 특징 추출
- Prompt Normalizer와 negative prompt 강화
- 이미지 생성 결과에서 상품 대체, 가짜 글자, 로고, 간판을 줄이는 프롬프트 구조
- 모델 실행 방식별 README와 실패 원인 분석 문서

자세한 차이:

```text
apps/api/app/modules/model_runtime/docs/CHANGES_FROM_AD_COPY_MODEL_BRANCH.md
```

## 저장소 구조

```text
apps/
  api/                 FastAPI 백엔드
  web/                 메인 통합 테스트 페이지
  web-ad-content/      통합 브라우저 화면 원본/비교용 폴더
docs/                  기존 설계 문서
```

주요 신규 백엔드 모듈:

```text
apps/api/app/extensions/ad_content/
  image_service.py
  image_prompt.py
  prompt_normalizer.py
  product_visualizer.py
  reference_search.py
  reference_analyzer.py
  reference_store.py
  image_validator.py

apps/api/app/modules/model_runtime/
  llm/
  image/
  docs/
```

## 전체 파이프라인

```text
Browser
-> Input Validator
-> Marketing + Copy + Visual Brief LLM
-> Output Validator
-> Product Visualizer
-> Product Visual Database
-> Prompt Normalizer
-> Image Generation Model
-> Image Validator
-> Final Ad Content
```

## 빠른 실행

이미 가상환경과 `.env` 설정이 끝난 상태라면 저장소 루트에서 아래 파일만 실행하면 됩니다.

```cmd
start-brandmate.cmd
```

이 스크립트는 API 서버 `http://127.0.0.1:8000`과 웹 서버 `http://127.0.0.1:5500`을 함께 확인/실행하고, 브라우저를 자동으로 엽니다. 이미 실행 중인 서버가 있으면 중복으로 띄우지 않습니다.

### 1. 저장소 clone

```cmd
git clone https://github.com/imella0706/final_1_team.git
cd final_1_team
git checkout feature/ai-copy-vision-model-integration
```

### 2. Python 가상환경 생성

```cmd
cd apps\api
python -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
pip install -e ".[dev]"
copy .env.example .env
```

### 3. `.env` 설정

최소 설정:

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

Product Visual Database reference search는 선택 기능입니다.

```env
BRANDMATE_REFERENCE_SEARCH_ENABLED=false
BRANDMATE_REFERENCE_SOURCE=wikimedia
BRANDMATE_PRODUCT_VISUAL_DB_PATH=product_visual_profiles.sqlite3
```

`BRANDMATE_REFERENCE_SEARCH_ENABLED=true`로 바꾸면 Wikimedia Commons API를 사용합니다. Pexels/Unsplash는 해당 provider를 선택할 때만 API 키가 필요합니다.

### 4. API + 브라우저 한 번에 실행

```cmd
start-brandmate.cmd
```

브라우저 접속:

```text
http://127.0.0.1:5500
```

API 문서:

```text
http://127.0.0.1:8000/docs
```

### 5. API 서버만 따로 실행

```cmd
cd apps\api
.venv\Scripts\python.exe -m uvicorn app.extensions.ad_content.main:app --host 127.0.0.1 --port 8000
```

상태 확인:

```cmd
curl http://127.0.0.1:8000/health
```

API 문서:

```text
http://127.0.0.1:8000/docs
```

### 6. 브라우저만 따로 실행

새 CMD 창:

```cmd
cd apps\web
python -m http.server 5500
```

브라우저 접속:

```text
http://127.0.0.1:5500
```

## 사용 순서

1. 광고 문구 모델 선택
2. 이미지 생성 모델 선택
3. 업종, 상황, 타겟, 톤, 채널, 상호명, 상품명, 특징, 금지 표현 입력
4. `광고 콘텐츠 생성` 클릭
5. 광고 문구, CTA, 이미지, 모델 호출 payload 확인

## 테스트

```cmd
cd apps\api
.venv\Scripts\python.exe -m pytest
.venv\Scripts\python.exe -m ruff check app tests
```

프론트엔드 문법 확인:

```cmd
node --check ..\web\app.js
```

## 주요 문서

- API 실행 문서: [apps/api/README.md](apps/api/README.md)
- 브라우저 실행 문서: [apps/web/README.md](apps/web/README.md)
- 광고 콘텐츠 확장 모듈: [apps/api/app/extensions/ad_content/README.md](apps/api/app/extensions/ad_content/README.md)
- 광고 문구 모듈: [apps/api/app/modules/ad_copy/README.md](apps/api/app/modules/ad_copy/README.md)
- 모델 런타임 구조: [apps/api/app/modules/model_runtime/README.md](apps/api/app/modules/model_runtime/README.md)
- LLM 실행 방식: [apps/api/app/modules/model_runtime/llm/README.md](apps/api/app/modules/model_runtime/llm/README.md)
- 이미지 실행 방식: [apps/api/app/modules/model_runtime/image/README.md](apps/api/app/modules/model_runtime/image/README.md)
- 광고 콘텐츠 파이프라인: [apps/api/app/modules/model_runtime/docs/AD_CONTENT_PIPELINE_README.md](apps/api/app/modules/model_runtime/docs/AD_CONTENT_PIPELINE_README.md)
- 프롬프트 전략: [apps/api/app/modules/model_runtime/docs/PROMPT_STRATEGY.md](apps/api/app/modules/model_runtime/docs/PROMPT_STRATEGY.md)
- 기준 브랜치 대비 변경점: [apps/api/app/modules/model_runtime/docs/CHANGES_FROM_AD_COPY_MODEL_BRANCH.md](apps/api/app/modules/model_runtime/docs/CHANGES_FROM_AD_COPY_MODEL_BRANCH.md)
