# Image Runtime

이미지 모델은 텍스트 LLM과 실행 방식이 다릅니다. LLM은 OpenAI-compatible HTTP 서버로 호출하기 쉽지만, 이미지 모델은 대형 diffusion pipeline, scheduler, VAE, GPU VRAM을 직접 다루는 경우가 많습니다.

## 지원 대상

| 모델 | 실행 방식 | 기본 모델 ID |
| --- | --- | --- |
| FLUX.1 Schnell | Diffusers | `black-forest-labs/FLUX.1-schnell` |
| Stable Diffusion XL Base 1.0 | Diffusers | `stabilityai/stable-diffusion-xl-base-1.0` |
| Openjourney | Diffusers | `prompthero/openjourney` |

## 설치

```bat
cd apps\api
pip install -e ".[image]"
```

GPU 환경에서는 PyTorch CUDA 빌드가 별도로 필요할 수 있습니다.

## 요청 예시

```bat
curl -X POST http://127.0.0.1:8000/api/image/generate ^
  -H "Content-Type: application/json" ^
  -d "{\"model\":\"sdxl-base-1.0\",\"prompt\":\"A premium cafe poster for strawberry tiramisu\",\"width\":1024,\"height\":1024}"
```

## 주의

- 로컬 PC에서 이미지 모델과 여러 LLM을 동시에 실행하면 VRAM/RAM이 부족해질 수 있습니다.
- Diffusers는 모델을 Python 프로세스 안으로 로드하므로 FastAPI worker와 분리하거나 별도 worker로 운영하는 편이 안전합니다.
- FLUX 계열은 큰 VRAM을 요구할 수 있어 RunPod, Colab, 별도 GPU 서버 사용을 권장합니다.
