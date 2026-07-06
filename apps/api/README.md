# 광고 문구 API

소상공인 입력을 선택한 LLM에 전달하고 광고 문구, CTA, 해시태그와 이미지 프롬프트를
구조화된 JSON으로 반환하는 FastAPI 애플리케이션입니다.

## 설치

```powershell
cd apps/api
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
Copy-Item .env.example .env
```

`.env`의 `BRANDMATE_LLM_API_KEY`에 Hugging Face 토큰을 입력합니다. 토큰에는
`Make calls to Inference Providers` 권한이 필요합니다.

```dotenv
BRANDMATE_LLM_BASE_URL=https://router.huggingface.co/v1
BRANDMATE_LLM_API_KEY=hf_...

# NVIDIA 모델을 선택할 때만 필요
BRANDMATE_NVIDIA_BASE_URL=https://integrate.api.nvidia.com/v1
BRANDMATE_NVIDIA_API_KEY=nvapi_...
```

## 실행

```powershell
uvicorn app.main:app --reload
```

- API 문서: `http://localhost:8000/docs`
- 상태 확인: `GET http://localhost:8000/health`
- 모델 목록: `GET http://localhost:8000/api/v1/ad-copies/models`
- 광고 생성: `POST http://localhost:8000/api/v1/ad-copies/generate`

## 모델 실행 방식

기본값은 Hugging Face의 OpenAI 호환 Router입니다. `BRANDMATE_LLM_BASE_URL`과
`BRANDMATE_LLM_API_KEY`를 바꾸면 vLLM 등 다른 OpenAI 호환 서버도 사용할 수 있습니다.

주의사항:

- Llama는 Hugging Face 계정에서 Meta 모델 접근 동의가 필요합니다.
- Qwen과 Llama는 HF Router가 Provider를 자동 선택합니다.
- `NVIDIA · Llama 3.1 8B`는 NVIDIA NIM 무료 시험용 Endpoint와 별도 키를 사용합니다.
- Mistral, Gemma, Phi, SOLAR는 모델 ID에 `:featherless-ai`를 자동으로 붙여
  기존 Hugging Face 토큰으로 Featherless AI에 라우팅합니다.
- Gemma는 Hugging Face에서 Google 사용 조건에 먼저 동의해야 합니다.
- SOLAR 10.7B Instruct v1.0은 CC BY-NC 4.0이므로 상업 서비스에 사용할 수 없습니다.
- 모델 또는 Provider가 JSON Schema를 거부하면 일반 JSON 출력 요청으로 한 번 재시도합니다.

전체 모델의 동일 입력 호출시간은 API 서버 실행 후 다음 명령으로 비교할 수 있습니다.

```powershell
python scripts/benchmark_models.py
```
