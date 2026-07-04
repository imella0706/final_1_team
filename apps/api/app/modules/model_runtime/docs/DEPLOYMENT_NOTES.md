# 실무 배포 관점 개선 방향

## 권장 아키텍처

```text
Browser
  -> FastAPI Backend
    -> LLM Gateway Service
      -> LM Studio / Ollama / vLLM / RunPod / HF Endpoint
    -> Image Generation Worker
      -> Diffusers GPU Worker / RunPod / Colab / HF Endpoint
```

## 모델 서버 운영

- 로컬 개발: LM Studio 또는 Ollama
- 단일 GPU 서버: vLLM 또는 TGI
- 이미지 생성: Diffusers worker 또는 managed endpoint
- 실서비스: GPU 서버를 API 서버와 분리

## 로컬 PC에서 모든 모델을 동시에 실행하기 어려운 이유

- 7B~10.7B LLM도 양자화하지 않으면 VRAM/RAM 요구량이 큽니다.
- 이미지 diffusion 모델은 LLM과 별도로 VRAM을 크게 사용합니다.
- 여러 모델을 동시에 로드하면 GPU memory fragmentation과 OOM이 발생할 수 있습니다.
- 노트북/일반 PC는 냉각, 전력, VRAM이 장시간 inference에 불리합니다.

## 핵심 개념

- GPU VRAM: 모델 weight와 inference activation이 올라가는 GPU 메모리입니다.
- RAM: 모델 로딩, tokenizer, CPU fallback, 이미지 후처리에 쓰입니다.
- 양자화: 모델 weight를 16bit보다 작은 형식으로 줄여 메모리 사용량을 낮추는 방식입니다.
- 모델 서버: 모델을 메모리에 올리고 HTTP/gRPC API를 제공하는 프로세스입니다.
- API endpoint: FastAPI가 호출하는 모델 서버 주소입니다. 예: `http://localhost:1234/v1`.

## 개선 방향

- 모델별 health check endpoint 추가
- provider별 timeout/retry/circuit breaker 추가
- 이미지 생성은 background job queue로 분리
- 생성 결과와 prompt/version 로그 저장
- 운영 환경에서는 secret manager로 API key 관리
- RunPod, Colab, Hugging Face Inference Endpoint로 원격 GPU 확장
