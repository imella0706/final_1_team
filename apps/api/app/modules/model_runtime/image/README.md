# Image Runtime

이미지 모델은 텍스트 LLM과 실행 방식이 다릅니다. 현재 팀 기준은 외부 유료 이미지
API가 아니라 GCP GPU VM에서 ComfyUI를 직접 띄우고, FastAPI가 ComfyUI HTTP API를
호출하는 방식입니다.

전체 설치 순서는 이 문서가 아니라 팀 공용 온보딩 문서를 기준으로 합니다.

```text
../../../../../../docs/LOCAL_AI_PIPELINE_ONBOARDING.md
```

이 문서는 이미지 런타임의 역할과 코드 관점의 실행 방식을 설명합니다.

## 지원 대상

| 모델 | 실행 방식 | 기본 모델 ID |
| --- | --- | --- |
| FLUX.1 Schnell | GCP GPU VM의 Local ComfyUI | `black-forest-labs/FLUX.1-schnell` |
| Stable Diffusion XL Base 1.0 | 추후 GCP GPU VM에서 직접 실행 검토 | `stabilityai/stable-diffusion-xl-base-1.0` |
| Openjourney | 추후 GCP GPU VM에서 직접 실행 검토 | `prompthero/openjourney` |

Hugging Face Router는 외부 유료 API 경로이므로 현재 운영 기준에서 제외합니다.
Diffusers는 ComfyUI 없이 Python worker에서 모델을 직접 로드할 때 검토할 후보입니다.
현재 기본 운영 경로는 `FastAPI -> ComfyUI -> FLUX.1 Schnell GGUF`입니다.

## 설치 기준

이미지 생성/CLIP 평가용 GPU 서버 패키지는 `apps/api/requirements-image-gpu-prod.txt`
기준으로 설치합니다.

```bash
cd apps/api
python -m pip install -r requirements-image-gpu-prod.txt --extra-index-url https://download.pytorch.org/whl/cu121
```

ComfyUI, FLUX GGUF 모델 파일, text encoder, VAE, custom node 설치는
`LOCAL_AI_PIPELINE_ONBOARDING.md`를 따릅니다. 이 문서에 설치 절차를 중복 작성하지
않습니다.

## 요청 예시

```bat
curl -X POST http://127.0.0.1:8000/api/image/generate ^
  -H "Content-Type: application/json" ^
  -d "{\"model\":\"sdxl-base-1.0\",\"prompt\":\"A premium cafe poster for strawberry tiramisu\",\"width\":1024,\"height\":1024}"
```

## 주의

- 로컬 PC에서 이미지 모델과 여러 LLM을 동시에 실행하면 VRAM/RAM이 부족해질 수 있습니다.
- 현재 FLUX 경로는 FastAPI가 ComfyUI HTTP API를 호출하는 구조입니다.
- ComfyUI와 API/eval은 서로 다른 가상환경으로 분리합니다.
- Diffusers를 직접 사용하는 실험은 FastAPI worker와 분리하거나 별도 worker로 운영하는 편이 안전합니다.
