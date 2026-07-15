# Model Runtime Integration

이 모듈은 모델을 FastAPI 프로세스 안에 직접 import해서 실행하지 않고, 모델 서버를 API로 호출하는 구조를 제공합니다.

## Endpoint

확장 실행 entrypoint인 `app.extensions.ad_content.main:app` 기준:

```text
POST /api/llm/generate
POST /api/image/generate
```

기존 API prefix 기준:

```text
POST /api/v1/llm/generate
POST /api/v1/image/generate
```

## 구조

```text
model_runtime/
  router.py                 FastAPI endpoint만 담당
  schemas.py                요청/응답 스키마
  llm/
    registry.py             MODEL_MAP과 환경 변수 매핑
    clients.py              LM Studio, Ollama, vLLM, HF Router client
    service.py              LLM 생성 orchestration
  image/
    registry.py             이미지 모델 매핑
    diffusers_service.py    Diffusers 기반 이미지 생성 service
  docs/
    FAILURE_ANALYSIS.md
    DEPLOYMENT_NOTES.md
    PROMPT_STRATEGY.md
    AD_CONTENT_PIPELINE_README.md
    CHANGES_FROM_AD_COPY_MODEL_BRANCH.md
```

## 설계 원칙

- router에는 모델 호출 로직을 넣지 않습니다.
- 텍스트 모델과 이미지 모델 endpoint를 분리합니다.
- 모델 이름은 코드 곳곳에 하드코딩하지 않고 registry의 `MODEL_MAP`에서 관리합니다.
- LM Studio, Ollama, vLLM은 모두 OpenAI-compatible `/v1/chat/completions` client를 공유합니다.
- Diffusers는 Python 프로세스에서 GPU/CPU 메모리를 크게 사용하므로 별도 service로 분리했습니다.

## 테스트

```bat
cd apps\api
.venv\Scripts\python.exe -m pytest tests\test_model_runtime.py
```
