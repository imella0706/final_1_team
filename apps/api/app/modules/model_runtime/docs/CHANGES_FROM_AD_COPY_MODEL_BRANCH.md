# Changes From `feature/ad-copy-model-integration`

이 문서는 원격 기준 브랜치 `feature/ad-copy-model-integration`과 현재 브랜치 `feature/ai-copy-vision-model-integration`의 차이를 정리합니다.

사용자가 언급한 `feature/ai-copy-model-integration` 브랜치는 원격 저장소에 없으며, 실제 비교 가능한 광고 문구 모델 통합 브랜치는 `feature/ad-copy-model-integration`입니다.

## 기준 브랜치의 범위

`feature/ad-copy-model-integration`은 광고 문구 생성 LLM 통합이 중심입니다.

주요 기능:

- 광고 문구 모델 목록
- 광고 문구 생성 API
- LLM 모델 선택
- 기본 광고 문구 JSON 생성

## 현재 브랜치에서 추가된 기능

### 1. 광고 콘텐츠 통합 API

추가 파일:

```text
apps/api/app/extensions/ad_content/
```

추가 endpoint:

```text
GET  /api/v1/ad-content/image-models
POST /api/v1/ad-content/generate
```

역할:

- 광고 문구 생성
- Product Visualizer fallback 실행
- 이미지 prompt 생성
- 이미지 모델 호출
- 최종 광고 콘텐츠 반환

### 2. 브라우저 통합 화면

추가 폴더:

```text
apps/web-legacy-ad-content/
```

역할:

- 광고 문구 모델 선택
- 이미지 생성 모델 선택
- 광고 정보 입력
- 광고 문구와 이미지 결과 표시

### 3. 이미지 생성 모델 구조

추가/수정 파일:

```text
apps/api/app/extensions/ad_content/image_service.py
apps/api/app/extensions/ad_content/models.py
apps/api/app/extensions/ad_content/schemas.py
apps/api/app/modules/model_runtime/image/
```

지원 모델:

```text
FLUX.1 Schnell
Stable Diffusion XL Base 1.0
Openjourney
```

### 4. Product Visualizer

추가 파일:

```text
apps/api/app/extensions/ad_content/product_visualizer.py
```

역할:

- 현재 요청 경로에서는 fallback으로 상품명을 기본 시각 정보 JSON으로 변환
- 사용자가 입력한 상품이 다른 상품으로 대체되는 문제 완화
- 음식, 음료, 물건, 패키지, 소품 등 다양한 상품에 대응

현재 제한:

- `ProductVisualizer.visualize()`가 즉시 fallback을 반환하므로 LLM 기반 상품 시각 분석은 실행되지 않습니다.

### 5. Product Visual Database

추가 파일:

```text
apps/api/app/extensions/ad_content/reference_store.py
apps/api/app/extensions/ad_content/reference_search.py
apps/api/app/extensions/ad_content/reference_analyzer.py
```

역할:

- 공식/라이선스 명확한 reference source에서 image metadata 검색
- Vision/LLM 분석으로 시각 특징만 추출
- 이미지 파일이 아니라 visual JSON과 source metadata만 SQLite에 저장

기본값:

```env
BRANDMATE_REFERENCE_SEARCH_ENABLED=false
BRANDMATE_REFERENCE_SOURCE=wikimedia
```

현재 제한:

- 위 DB/search/analyzer 코드는 존재하지만 Product Visualizer 조기 fallback 때문에 일반 `/api/v1/ad-content/generate` 요청에서는 실행되지 않습니다.

### 6. Prompt Normalizer

추가 파일:

```text
apps/api/app/extensions/ad_content/prompt_normalizer.py
apps/api/app/extensions/ad_content/image_prompt.py
```

역할:

- Product Visualizer 출력과 visual brief를 최종 image prompt로 변환
- negative prompt 생성
- 가짜 글자, 로고, 메뉴판, 간판, 상품 대체를 줄이는 지시 추가

### 7. 입력/출력 검증 강화

추가 파일:

```text
apps/api/app/modules/ad_copy/input_validator.py
apps/api/app/modules/ad_copy/output_validator.py
```

역할:

- 한국어 입력값을 내부 enum으로 정규화
- 상품명/특징/금지어 검증
- LLM 출력 실패 시 fallback copy 생성

### 8. 모델 런타임 구조

추가 폴더:

```text
apps/api/app/modules/model_runtime/
```

역할:

- LLM runtime
- Image runtime
- LM Studio, vLLM, Ollama, Diffusers 확장 구조

## 주요 수정 파일

```text
README.md
apps/api/README.md
apps/api/.env.example
apps/api/app/core/config.py
apps/api/app/api/router.py
apps/api/app/modules/ad_copy/prompt.py
apps/api/app/modules/ad_copy/schemas.py
apps/api/app/modules/ad_copy/service.py
apps/api/pyproject.toml
```

## 테스트 추가

```text
apps/api/tests/test_ad_content_extension.py
apps/api/tests/test_model_runtime.py
```

현재 검증 명령:

```cmd
cd apps\api
.venv\Scripts\python.exe -m pytest
.venv\Scripts\python.exe -m ruff check app tests
node --check ..\web-legacy-ad-content\app.js
```
