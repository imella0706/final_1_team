# BrandMate Ad Content Studio

광고 문구 모델과 이미지 생성 모델을 브라우저에서 선택하고 최종 광고 콘텐츠를 생성하는 정적 프론트엔드입니다.

기존 `apps/web`을 수정하지 않고 별도 폴더로 추가했습니다.

## 호출 API

```text
GET  http://localhost:8000/api/v1/ad-copies/models
GET  http://localhost:8000/api/v1/ad-content/image-models
POST http://localhost:8000/api/v1/ad-content/generate
```

API 서버는 반드시 아래 app으로 실행해야 합니다.

```text
app.extensions.ad_content.main:app
```

## 실행 전 준비

저장소 루트에서 API 환경을 준비합니다.

```cmd
cd apps\api
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
copy .env.example .env
```

`.env`에 사용할 LLM/API 키 또는 LM Studio 정보를 설정합니다.

## API 서버 실행

저장소 루트 기준:

```cmd
cd apps\api
.venv\Scripts\python.exe -m uvicorn app.extensions.ad_content.main:app --host 127.0.0.1 --port 8000
```

상태 확인:

```cmd
curl http://127.0.0.1:8000/health
```

## 프론트엔드 실행

새 CMD 창에서 저장소 루트 기준:

```cmd
cd apps\web-ad-content
python -m http.server 5501
```

브라우저 접속:

```text
http://127.0.0.1:5501
```

## 사용 순서

1. 광고 문구 모델 선택
2. 이미지 생성 모델 선택
3. 업종, 상황, 타깃, 톤, 채널, 상호명, 상품명, 특징, 금지 표현 입력
4. `광고 콘텐츠 생성` 클릭
5. 결과 영역에서 광고 문구, CTA, 이미지 확인
6. payload preview에서 `product_visualization`, `image_prompt`, `negative_prompt` 확인

## LM Studio 사용

Mistral/Gemma/Phi/SOLAR를 로컬에서 실행하려면 LM Studio Local Server가 필요합니다.

1. LM Studio 실행
2. 모델 다운로드 및 로드
3. Local Server 켜기
4. 모델 ID 확인

```cmd
curl http://localhost:1234/v1/models
```

`.env` 예시:

```env
BRANDMATE_LOCAL_LLM_BASE_URL=http://localhost:1234/v1
BRANDMATE_LOCAL_LLM_API_KEY=
BRANDMATE_MISTRAL_MODEL=lm_studio_mistral_model_id
BRANDMATE_GEMMA_MODEL=lm_studio_gemma_model_id
BRANDMATE_PHI_MODEL=lm_studio_phi_model_id
BRANDMATE_SOLAR_MODEL=lm_studio_solar_model_id
```

## Product Visual Database

선택 기능입니다. 기본값은 꺼져 있습니다.

```env
BRANDMATE_REFERENCE_SEARCH_ENABLED=false
BRANDMATE_REFERENCE_SOURCE=wikimedia
BRANDMATE_PRODUCT_VISUAL_DB_PATH=product_visual_profiles.sqlite3
```

`true`로 켜면 Wikimedia Commons reference metadata를 검색하고, 이미지 자체가 아닌 시각 특징 JSON만 SQLite에 저장합니다.

## 자주 나는 오류

`API 연결 실패`

```text
8000번 FastAPI 서버가 꺼져 있거나 app.extensions.ad_content.main:app이 아닌 app으로 실행된 상태입니다.
```

`모델 서버에 연결할 수 없습니다`

```text
LM Studio Local Server가 꺼져 있거나 BRANDMATE_LOCAL_LLM_BASE_URL 주소가 다릅니다.
```

`모델이 약속된 JSON 형식을 지키지 않았습니다`

```text
LLM 응답이 JSON schema를 지키지 않은 상태입니다. 현재 코드는 재시도 후 fallback copy를 사용합니다.
```
