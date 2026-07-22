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

`feature/ad-copy-model-integration`은 광고 문구 생성 LLM 중심 구조입니다. 현재 브랜치는 여기에 이미지 생성 통합 API와 관련 모듈을 추가했습니다.

현재 코드 기준으로 실제 요청 경로에서 동작하는 기능:

- 브라우저에서 광고 문구 모델과 이미지 생성 모델을 함께 선택
- 광고 문구 생성 후 이미지 생성까지 이어지는 통합 API
- FLUX.1 Schnell, SDXL, Openjourney 이미지 모델 선택 구조
- 광고 문구 LLM이 `marketing_strategy`, 광고 문구, `visual_brief`를 JSON으로 생성
- Product Visualizer fallback을 통한 상품별 기본 시각 JSON 생성
- Prompt Normalizer와 negative prompt 강화
- 이미지 생성 결과에서 상품 대체, 가짜 글자, 로고, 간판을 줄이는 프롬프트 구조
- 모델 실행 방식별 README와 실패 원인 분석 문서

구현 파일은 있지만 현재 런타임에서 완전히 활성화되지 않은 기능:

- Product Visual Database SQLite 캐시
- Wikimedia/Pexels/Unsplash reference image metadata 검색 구조
- Reference Analyzer를 통한 시각 특징 추출

위 기능들은 `product_visualizer.py` 안에 코드가 있지만, 현재 `ProductVisualizer.visualize()`가 먼저 fallback을 반환하므로 일반 `/api/v1/ad-content/generate` 요청에서는 실행되지 않습니다. 이 부분을 활성화하기 전까지는 README나 발표에서 "reference 기반 자동 상품 분석이 동작한다"고 말하면 안 됩니다.

자세한 차이:

```text
apps/api/app/modules/model_runtime/docs/CHANGES_FROM_AD_COPY_MODEL_BRANCH.md
```

## 저장소 구조

```text
apps/
  api/                 FastAPI 백엔드
  web/                 메인 통합 테스트 페이지
  web-legacy-ad-content/ 프롬프트/UI 고도화 전 베이스라인 비교용 폴더
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
-> Product Visualizer fallback
-> Prompt Normalizer
-> Image Generation Model
-> Image Validator (enabled일 때만)
-> Final Ad Content
```

Naver Blog 채널은 예외입니다. 업로드 사진이 있으면 블로그 사진 분석 메모를 만들고, 생성 이미지는 만들지 않고 업로드 이미지를 그대로 응답에 실어 보냅니다.

## 빠른 실행

현재 GCP/WSL 기준 표준 실행 경로는 `scripts/manage_brandmate_services_gcp.sh`입니다.
FastAPI, 정적 프론트엔드, Postgres, DB migration, ComfyUI를 같은 명령 체계에서 관리합니다. CCTV 상권분석 Streamlit은 아직 개발 중이므로 기본 실행에서는 제외합니다.

이 스크립트는 현재 GCP 세팅과 발표용 로컬 시연 기준입니다. 다만 팀원 로컬 환경에 FLUX/ComfyUI가 없어도 스크립트가 자동으로 감지해 ComfyUI만 건너뜁니다. 이 경우 인증, 서비스 선택, 광고 생성 화면 진입, FastAPI 연동은 확인할 수 있고, FLUX 이미지 생성만 사용할 수 없습니다. 상권분석 Streamlit은 개발 중이라 기본값으로 띄우지 않습니다.

```bash
# 서비스 시작
./scripts/manage_brandmate_services_gcp.sh

# 상태 확인
./scripts/manage_brandmate_services_gcp.sh status

# 로그 확인
./scripts/manage_brandmate_services_gcp.sh logs

# 서비스 종료
./scripts/manage_brandmate_services_gcp.sh stop

# 서비스 재시작
./scripts/manage_brandmate_services_gcp.sh restart
```

### 실행 모드

| 대상 | 명령어 | 실행 범위 |
| --- | --- | --- |
| 팀원 기본 실행 | `./scripts/manage_brandmate_services_gcp.sh restart` | Postgres, DB migration, FastAPI, web, ComfyUI 자동 감지. 상권분석 Streamlit은 제외 |
| 상권분석 담당 개발자 | `START_DASHBOARD=true ./scripts/manage_brandmate_services_gcp.sh restart` | 팀원 기본 실행 범위 + `apps/visitor_flow_l2_dashboard` Streamlit 대시보드 |

### 팀원 로컬 확인

팀원 PC에 FLUX/ComfyUI가 없어도 같은 명령을 사용합니다. ComfyUI가 설치되어 있으면 실행하고, 없으면 자동으로 skip합니다. 상권분석 Streamlit은 개발 중이므로 팀원 로컬에서는 기본적으로 실행하지 않습니다.

```bash
# [Design Intent] GCP/로컬 모두 같은 진입점을 사용한다. ComfyUI는 환경에 따라 자동 감지하고, 개발 중인 Streamlit은 기본 비활성화한다.
./scripts/manage_brandmate_services_gcp.sh restart
```

접속:

```text
http://127.0.0.1:5501
```

주의:

- ComfyUI가 없는 환경에서는 FLUX 이미지 생성만 사용할 수 없습니다.
- 상권분석 Streamlit은 개발 중이므로 기본 실행에서는 뜨지 않습니다.
- 상권분석 대시보드를 상권분석 담당 개발자가 직접 확인할 때만 `START_DASHBOARD=true ./scripts/manage_brandmate_services_gcp.sh restart`로 실행합니다.
- 전체 광고 이미지 생성은 GCP/시연 머신에서 `./scripts/manage_brandmate_services_gcp.sh restart`로 확인합니다.

### 팀원에게 공유할 로그인 방식

GCP 서버가 떠 있는 경우 팀원은 로컬에 FLUX를 설치하지 않고 GCP의 BrandMate web URL로 접속해서 로그인합니다. GCP 외부 IP 또는 도메인은 보안상 README에 고정하지 말고 팀 채널에 별도로 공유합니다.

```text
http://<GCP_EXTERNAL_IP_OR_DOMAIN>:5501
```

현재 테스트 계정:

```text
id: admin@admin.com
pw: brandmateadmin
```

이 계정은 로컬/시연용 테스트 계정입니다. 공개 배포 계정이나 운영 계정으로 쓰면 안 됩니다.

아래 스크립트는 협의 전까지 유지하는 legacy 경로입니다. 현재 표준 실행 경로가 아닙니다.

- `scripts/start-brandmate.ps1`: Windows legacy launcher입니다. 팀 협의 후 `scripts/legacy/`로 이동하거나 삭제합니다.
- `scripts/run_local_vision_eval.sh`: Ollama 기반 로컬 평가 전용 legacy wrapper입니다. 팀 협의 후 `scripts/legacy/`로 이동하거나 삭제합니다.

Windows에서 기존 방식으로 실행해야 하는 경우에만 아래 파일을 사용합니다.

```cmd
start-brandmate.cmd
```

이 legacy 스크립트는 API 서버와 웹 서버를 함께 확인/실행하고, 브라우저를 자동으로 엽니다.

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
copy .env.gcp.example .env
```

환경변수 예시는 로컬과 GCP 모두 `apps/api/.env.gcp.example`만 기준으로 사용하고,
실행 값은 git에 포함되지 않는 `apps/api/.env`에 둡니다. 로컬에서는 DB 주소, origin,
`ENVIRONMENT`, Refresh Cookie의 `Secure`/이름을 로컬 HTTP 환경에 맞게 변경해야 합니다.

```bash
cp apps/api/.env.gcp.example apps/api/.env
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

Product Visual Database reference search는 코드상 선택 기능으로 준비되어 있지만, 현재 통합 API 요청 경로에서는 Product Visualizer 조기 fallback 때문에 실제로 사용되지 않습니다. 이 기능을 쓰려면 `product_visualizer.py`의 fallback 우회 로직을 먼저 수정해야 합니다.

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
http://127.0.0.1:7660/docs
```

### 5. API 서버만 따로 실행

```cmd
cd apps\api
.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 7660
```

상태 확인:

```cmd
curl http://127.0.0.1:7660/health
```

API 문서:

```text
http://127.0.0.1:7660/docs
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

- 인증 백엔드 구현 범위: [docs/Backend.md](docs/Backend.md)
- 로컬 Qwen + ComfyUI FLUX 온보딩: [docs/LOCAL_AI_PIPELINE_ONBOARDING.md](docs/LOCAL_AI_PIPELINE_ONBOARDING.md)
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
