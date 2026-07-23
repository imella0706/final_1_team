# BrandMate API

FastAPI 기반 광고 콘텐츠 생성 API입니다. 광고 문구 모델과 이미지 생성 모델을
FastAPI 프로세스 안에 직접 로드하지 않고, 별도 모델 실행 계층을 API로 호출합니다.
현재 이미지 생성 운영 기준은 외부 유료 API가 아니라 GCP GPU VM의 ComfyUI를 직접
호출하는 방식입니다.

## 로컬 AI 전체 파이프라인 세팅

ComfyUI, FLUX GGUF, Ollama/Qwen, GCP GPU VM, API/eval 가상환경까지 포함한
전체 로컬 AI 파이프라인 설치 순서는 아래 문서를 기준으로 합니다.

```text
../../docs/LOCAL_AI_PIPELINE_ONBOARDING.md
```

이 README는 `apps/api` FastAPI 서버의 구조, endpoint, 기본 실행 방법만 다룹니다.
이미지 모델/ComfyUI/GPU 환경 세팅 내용을 중복해서 관리하지 않습니다.

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
copy .env.gcp.example .env
```

환경변수 예시는 로컬과 GCP 모두 `.env.gcp.example` 하나만 기준으로 사용하고,
실행 값은 git에 포함되지 않는 `.env`에 둡니다. 로컬 HTTP 개발 시에는 DB 주소,
origin, `ENVIRONMENT`, Refresh Cookie의 `Secure`/이름을 로컬 값으로 변경합니다.

```bash
cp .env.gcp.example .env
```

## `.env` 최소 설정

이미지 생성은 외부 유료 API가 아니라 GCP GPU VM의 ComfyUI를 기본으로 사용합니다.

```env
# [Design Intent] 이미지 생성은 자체 GPU VM의 ComfyUI를 기본 경로로 고정한다.
BRANDMATE_IMAGE_PROVIDER=comfyui
BRANDMATE_COMFYUI_BASE_URL=http://127.0.0.1:8188
BRANDMATE_COMFYUI_SDXL_CHECKPOINT=sd_xl_base_1.0.safetensors
BRANDMATE_COMFYUI_IMG2IMG_DENOISE=0.58
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
# [Design Intent] 현재 운영 기본 모델은 ComfyUI에서 실행하는 FLUX.1 Schnell이다.
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
.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 7660
```

상태 확인:

```cmd
curl http://127.0.0.1:7660/health
```

Swagger:

```text
http://127.0.0.1:7660/docs
```

## 회원가입과 JWT 인증

현재 인증 구조는 짧은 Access JWT와 서버에서 관리하는 회전형 Refresh Token을 함께 사용합니다.

- Access JWT: 브라우저 메모리에만 보관하고 API에는 `Authorization: Bearer`로 전달
- Refresh Token: HttpOnly Cookie에만 보관하고 DB에는 SHA-256 hash만 저장
- 비밀번호: Argon2id hash만 저장
- 기존 광고 생성 API: 인증 없이는 `401`
- 공개 가입: 이메일 인증 전에는 로그인 불가
- 비밀번호 재설정/변경: 성공 즉시 모든 Access/Refresh/기기 세션 무효화
- 기기 세션: Access JWT의 `sid`와 DB 세션을 비교해 특정 기기만 즉시 해제
- 인증 메일: DB Outbox에 먼저 기록한 뒤 SMTP worker가 제한적으로 재시도

로컬 DB와 migration 실행:

```bash
# [Design Intent] 애플리케이션 실행 전에 영속 DB와 스키마 버전을 먼저 확정한다.
docker compose -f docker-compose.api.yml up -d brandmate-postgres
cd apps/api
conda run -n ssakda alembic upgrade head
```

`.env`에는 저장소마다 다른 서명 키가 필요합니다.

```bash
# [Design Intent] 출력된 값은 .env/Secret Manager에만 넣고 Git에는 커밋하지 않는다.
openssl rand -hex 32
```

인증 Endpoint:

| Method | Path | 역할 |
| --- | --- | --- |
| `POST` | `/api/v1/auth/signup` | 회원가입 |
| `POST` | `/api/v1/auth/verify-email` | 이메일 일회용 토큰 확인 |
| `POST` | `/api/v1/auth/verify-email/resend` | 이메일 인증 링크 재발송 |
| `POST` | `/api/v1/auth/login` | Access JWT 발급 + Refresh Cookie 설정 |
| `POST` | `/api/v1/auth/refresh` | Refresh 회전 + 새 Access JWT 발급 |
| `POST` | `/api/v1/auth/logout` | 현재 로그인 family 폐기 |
| `POST` | `/api/v1/auth/logout-all` | 전체 Refresh 폐기 + 기존 Access 무효화 |
| `POST` | `/api/v1/auth/password-reset/request` | 비밀번호 재설정 메일 요청 |
| `POST` | `/api/v1/auth/password-reset/confirm` | 일회용 토큰으로 비밀번호 재설정 |
| `POST` | `/api/v1/auth/password/change` | 현재 비밀번호 확인 후 변경 |
| `GET` | `/api/v1/auth/sessions` | 로그인된 기기 목록 |
| `DELETE` | `/api/v1/auth/sessions/{id}` | 특정 기기 즉시 로그아웃 |
| `GET` | `/api/v1/auth/me` | 현재 사용자 조회 |

운영에서는 `.env.gcp.example`의 `AUTH_EMAIL_*`, `AUTH_SMTP_*` 값을 실제 발신 도메인과 SMTP 자격 증명으로 교체해야 합니다. `replace-me` 상태는 동작 확인용 예시일 뿐 배포 완료가 아닙니다. 코드 완료와 별개로 실제 HTTPS 도메인에서 메일 수신, `Secure`/`__Host-` Cookie, 브라우저 E2E를 통과하기 전에는 공개 회원 모집을 시작하지 않습니다.

인증 metric은 `GET /metrics`에서 Prometheus text 형식으로 노출합니다. 이메일, 사용자 ID, token, session ID는 label에 넣지 않습니다.

## 광고 콘텐츠 통합 요청 예시

```cmd
curl -X POST http://127.0.0.1:7660/api/v1/ad-content/generate ^
  -H "Authorization: Bearer %ACCESS_TOKEN%" ^
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

인증 통합 테스트는 운영 DB와 분리된 PostgreSQL을 사용합니다.

```bash
# [Design Intent] 테스트가 개발 사용자 데이터를 삭제하지 않도록 tmpfs DB를 별도로 띄운다.
docker compose -f docker-compose.api.yml --profile test up -d brandmate-test-postgres
cd apps/api
conda run -n ssakda pytest -q
```

## 관련 문서

### 전체 실행/온보딩

- 로컬 AI 전체 파이프라인 설치: `../../docs/LOCAL_AI_PIPELINE_ONBOARDING.md`
- 평가 실행 및 리포트 해석: `../../docs/EVALUATION.md`

### API 기능 문서

- 광고 콘텐츠 확장 모듈: `app/extensions/ad_content/README.md`
- 광고 문구 모듈: `app/modules/ad_copy/README.md`
- 모델 런타임 구조: `app/modules/model_runtime/README.md`

### 모델 실행 방식

- LLM 실행 방식: `app/modules/model_runtime/llm/README.md`
- 이미지 런타임 구조: `app/modules/model_runtime/image/README.md`

### 설계/운영 참고

- 광고 콘텐츠 파이프라인: `app/modules/model_runtime/docs/AD_CONTENT_PIPELINE_README.md`
- 프롬프트 전략: `app/modules/model_runtime/docs/PROMPT_STRATEGY.md`
- 실패 원인 분석: `app/modules/model_runtime/docs/FAILURE_ANALYSIS.md`
- 배포 개선 방향: `app/modules/model_runtime/docs/DEPLOYMENT_NOTES.md`
