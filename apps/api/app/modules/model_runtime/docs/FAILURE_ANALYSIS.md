# 모델 구현 실패 원인 분석

## 1. Hugging Face Router에 모든 모델이 있는 것은 아님

Qwen 2.5 7B Instruct와 Llama 3.1 8B Instruct는 Hugging Face Router의 `/v1/models`에서 확인되지만, Mistral 7B Instruct v0.3, Gemma 2 9B Instruct, Phi 4 Mini Instruct, SOLAR 10.7B Instruct는 현재 Router 목록에 없었습니다.

따라서 브라우저에서 모델명을 선택해도 Router가 실제 provider를 찾지 못하면 400 계열 오류가 발생합니다.

## 2. `.env` 값이 실제 코드까지 전달되지 않던 문제

이전 구현은 일부 모델별 설정을 `os.getenv()`로 읽었습니다. CMD에서 uvicorn을 실행하면 `.env`는 Pydantic Settings가 읽지만 OS 환경변수로 자동 주입되지는 않습니다. 그래서 `.env`에 값을 넣어도 service 계층에서 `None`으로 보일 수 있었습니다.

현재 구현은 필요한 값을 `Settings` 필드로 등록하고 `settings`를 통해 읽습니다.

## 3. 모델을 FastAPI 코드 안에서 직접 import하면 안 되는 이유

LLM과 diffusion 모델은 수 GB에서 수십 GB의 VRAM/RAM을 사용합니다. FastAPI worker 안에서 직접 로드하면 다음 문제가 생깁니다.

- 서버 시작 시간이 길어짐
- 요청 처리 worker가 모델 메모리에 묶임
- 여러 모델 동시 로드 시 VRAM 부족
- 배포/스케일링/장애 격리가 어려움
- API 서버 재시작과 모델 재로드가 강하게 결합됨

실무에서는 모델 서버를 별도 프로세스나 별도 GPU 인스턴스로 띄우고, 백엔드는 HTTP API로 호출하는 방식을 선호합니다.

## 4. vLLM을 Windows에서 바로 실행하기 어려운 이유

vLLM은 고성능 CUDA runtime, Linux 중심 의존성, GPU memory manager, attention kernel에 강하게 의존합니다. Windows 네이티브 환경에서는 설치/커널/드라이버 호환성이 까다롭고, 일반적으로 WSL2 또는 Linux GPU 서버에서 운영하는 편이 안정적입니다.

## 5. LM Studio가 현재 환경에서 현실적인 이유

LM Studio는 Windows GUI에서 모델 다운로드, 양자화 모델 로드, OpenAI-compatible API 서버 실행을 한 번에 제공합니다. 이미 사용자가 Mistral/Gemma/Phi/SOLAR 모델을 다운로드해 둔 상태이므로, FastAPI는 `http://localhost:1234/v1/chat/completions`만 호출하면 됩니다.

## 6. 텍스트 모델과 이미지 모델 실행 방식 차이

텍스트 모델은 token streaming과 chat completions API 표준이 널리 쓰입니다. 이미지 모델은 diffusion pipeline, scheduler, latent, VAE, image postprocess가 필요하고, 모델별 VRAM 요구량이 커서 Diffusers 같은 별도 service 계층이 필요합니다.
