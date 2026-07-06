# 로컬 LLM + ComfyUI FLUX 온보딩 가이드_20260707_04:10

이 문서는 Linux/WSL2 환경에서 BrandMate의 전체 로컬 생성 파이프라인을 실행하기 위한 팀 공용 가이드다.
고도화 작업 전, llm부터 이미지 생성까지 완성한 기본 파이프라인이다. 

```text
# [Design Intent] 각 모델을 별도 프로세스로 격리하고 HTTP API로 연결한다.
사용자 입력
-> FastAPI (BrandMate)
-> Ollama / Qwen 2.5 7B (광고 문구와 이미지 프롬프트 JSON 생성)
-> ComfyUI / FLUX.1 Schnell GGUF (이미지 생성)
-> FastAPI 응답
-> 브라우저
```

## 1. 먼저 알아야 할 핵심

- ComfyUI는 `final_1_team` 내부에 설치할 필요가 없다. `~/personal/ComfyUI`처럼 프로젝트와 분리하고 HTTP `8188` 포트로 연결한다.
- `ssakda`와 `comfyui` Conda 환경도 분리한다. 두 서비스의 PyTorch 및 라이브러리 의존성을 섞지 않는다.
- `flux1-schnell-Q4_K_S.gguf` 하나만 받아서는 실행되지 않는다. FLUX 본체, 텍스트 인코더 2개, VAE, GGUF custom node가 모두 필요하다.
- Linux에서는 Windows Portable이 아니라 [ComfyUI 공식 저장소](https://github.com/Comfy-Org/ComfyUI)를 clone하여 수동 설치한다.
- Python 3.11이 ComfyUI의 유일한 지원 버전은 아니다. 이 프로젝트에서 custom node 호환성을 포함해 검증한 기준 버전이 3.11이다.
- 모델 파일과 Hugging Face 토큰은 Git에 커밋하지 않는다.

## 2. 검증 환경

| 항목 | 검증값 |
|---|---|
| OS | Windows + WSL2 Linux |
| GPU | NVIDIA GeForce RTX 3060 12GB |
| RAM | 16GB |
| ComfyUI Python | 3.11 |
| ComfyUI 포트 | `127.0.0.1:8188` |
| Ollama 포트 | `127.0.0.1:11434` |
| FastAPI 포트 | `127.0.0.1:8000` |
| Frontend 포트 | `127.0.0.1:5501` |

16GB RAM과 12GB VRAM은 Qwen 7B와 FLUX를 동시에 상주시킬 여유가 부족하다. 로컬 테스트에서는 `--lowvram`과 순차 실행이 필요하며, 실제 운영에서는 LLM과 이미지 워커를 별도 GPU로 분리해야 한다.

## 3. 사전 점검

Windows PowerShell과 WSL 양쪽에서 GPU를 확인한다.

```powershell
# [Design Intent] Windows NVIDIA 드라이버가 GPU를 인식하는지 확인한다.
nvidia-smi
```

```bash
# [Design Intent] WSL GPU forwarding이 정상인지 확인한다.
nvidia-smi
```

WSL에서 `GPU access blocked by the operating system` 또는 `Found no NVIDIA driver`가 나오면 Python 패키지 문제가 아니다. NVIDIA 드라이버 업데이트 후 Windows 재부팅 또는 PowerShell에서 `wsl --shutdown`을 실행한 뒤 WSL을 다시 시작한다.

## 4. ComfyUI 설치

### 4.1 저장소와 Conda 환경

```bash
# [Design Intent] BrandMate 저장소와 독립된 이미지 추론 서비스로 설치한다.
cd ~/personal
git clone https://github.com/Comfy-Org/ComfyUI.git
cd ComfyUI
conda create -n comfyui python=3.11 -y
conda activate comfyui
python -m pip install --upgrade pip setuptools wheel
```

### 4.2 PyTorch와 ComfyUI 의존성

현재 팀에서 실제 이미지 생성까지 검증한 환경은 PyTorch `2.5.1+cu121`이다.

```bash
# [Design Intent] 팀에서 검증한 CUDA 12.1 PyTorch 환경을 재현한다.
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121
pip install -r requirements.txt
```

이 환경에서는 `cu130 or higher` 최적화 경고가 표시될 수 있지만 기본 추론은 동작한다. 신규 환경에서 최신 CUDA/PyTorch로 올릴 때는 ComfyUI와 ComfyUI-GGUF 호환성을 별도 검증해야 한다. 경고만 보고 기존 동작 환경을 즉시 업그레이드하지 않는다.

## 5. FLUX GGUF 필수 파일 설치

### 5.1 필요한 구성요소

| 역할 | 파일 | 설치 위치 |
|---|---|---|
| FLUX diffusion model | `flux1-schnell-Q4_K_S.gguf` | `ComfyUI/models/unet/` |
| CLIP encoder | `clip_l.safetensors` | `ComfyUI/models/clip/` |
| T5 encoder | `t5xxl_fp8_e4m3fn.safetensors` | `ComfyUI/models/clip/` |
| VAE | `ae.safetensors` | `ComfyUI/models/vae/` |
| GGUF loader | `ComfyUI-GGUF` | `ComfyUI/custom_nodes/` |

다운로드 출처:

- FLUX GGUF: [city96/FLUX.1-schnell-gguf](https://huggingface.co/city96/FLUX.1-schnell-gguf/tree/main)
- 텍스트 인코더: [comfyanonymous/flux_text_encoders](https://huggingface.co/comfyanonymous/flux_text_encoders/tree/main)
- VAE: [black-forest-labs/FLUX.1-schnell](https://huggingface.co/black-forest-labs/FLUX.1-schnell/tree/main)
- GGUF loader: [city96/ComfyUI-GGUF](https://github.com/city96/ComfyUI-GGUF)

### 5.2 디렉터리 생성

```bash
# [Design Intent] ComfyUI가 모델 종류별로 탐색하는 고정 디렉터리를 만든다.
mkdir -p ~/personal/ComfyUI/models/unet
mkdir -p ~/personal/ComfyUI/models/clip
mkdir -p ~/personal/ComfyUI/models/vae
```

### 5.3 Hugging Face CLI 준비

```bash
# [Design Intent] 대용량 모델을 인증 상태와 재시도 기능이 있는 공식 CLI로 받는다.
conda activate comfyui
pip install --upgrade huggingface_hub
hf auth login
```

브라우저 인증을 완료한다. Fine-grained token을 직접 만들 경우 다운로드 용도에는 다음 최소 권한만 사용한다.

- `Read access to contents of all public gated repos you can access`
- 개인 저장소도 다운로드해야 할 때만 personal namespace read 권한 추가
- Inference Provider 권한과 write 권한은 로컬 모델 다운로드에 필요 없다.

토큰 문자열을 `.env`, 문서, 채팅, Git에 남기지 않는다.

### 5.4 모델 다운로드

먼저 Black Forest Labs의 FLUX.1-schnell 페이지에서 라이선스에 동의하고 접근 승인을 받아야 한다. 승인 전에는 VAE 다운로드가 `401 Unauthorized` 또는 `Access denied`로 실패한다.

```bash
# [Design Intent] GGUF FLUX 본체를 workflow가 기대하는 정확한 이름으로 배치한다.
hf download city96/FLUX.1-schnell-gguf flux1-schnell-Q4_K_S.gguf \
  --local-dir ~/personal/ComfyUI/models/unet

# [Design Intent] FLUX의 dual text encoding에 필요한 CLIP-L과 T5XXL을 배치한다.
hf download comfyanonymous/flux_text_encoders clip_l.safetensors \
  --local-dir ~/personal/ComfyUI/models/clip
hf download comfyanonymous/flux_text_encoders t5xxl_fp8_e4m3fn.safetensors \
  --local-dir ~/personal/ComfyUI/models/clip

# [Design Intent] FLUX latent를 최종 이미지로 복원하는 VAE를 배치한다.
hf download black-forest-labs/FLUX.1-schnell ae.safetensors \
  --local-dir ~/personal/ComfyUI/models/vae
```

브라우저에서 같은 파일을 반복 다운로드하면 `.safetensors.1` 파일이 생긴다. ComfyUI가 사용하는 파일은 확장자가 정확한 원본 하나이며, `.1`은 수 GB의 디스크만 낭비한다. 크기와 체크섬을 비교한 뒤 중복 파일을 정리한다.

### 5.5 ComfyUI-GGUF 설치

```bash
# [Design Intent] 기본 ComfyUI에 없는 GGUF UNet loader 노드를 추가한다.
cd ~/personal/ComfyUI/custom_nodes
git clone https://github.com/city96/ComfyUI-GGUF.git
cd ~/personal/ComfyUI
pip install -r custom_nodes/ComfyUI-GGUF/requirements.txt
```

이미 clone되어 있다면 다시 clone하지 않는다.

### 5.6 파일 검증

```bash
# [Design Intent] 서버를 띄우기 전에 누락과 잘못된 모델 경로를 차단한다.
ls -lh ~/personal/ComfyUI/models/unet/flux1-schnell-Q4_K_S.gguf
ls -lh ~/personal/ComfyUI/models/clip/clip_l.safetensors
ls -lh ~/personal/ComfyUI/models/clip/t5xxl_fp8_e4m3fn.safetensors
ls -lh ~/personal/ComfyUI/models/vae/ae.safetensors
ls -ld ~/personal/ComfyUI/custom_nodes/ComfyUI-GGUF
```

`flux1-schnell-Q4_K_S.gguf`를 `models/` 루트에 두면 workflow에서 찾지 못한다. 반드시 `models/unet/`에 둔다.

## 6. ComfyUI 실행과 검증

```bash
# [Design Intent] 12GB VRAM에서 Ollama와 함께 테스트할 수 있도록 offloading을 활성화한다.
conda activate comfyui
cd ~/personal/ComfyUI
python main.py --listen 127.0.0.1 --port 8188 --lowvram
```

이 터미널은 종료하지 않는다. 새 터미널에서 확인한다.

```bash
# [Design Intent] ComfyUI 서버, GPU 인식, GGUF custom node 등록을 각각 확인한다.
curl http://127.0.0.1:8188/system_stats
curl http://127.0.0.1:8188/object_info/UnetLoaderGGUF
```

두 번째 응답에 `flux1-schnell-Q4_K_S.gguf`가 나오면 GGUF loader와 모델 탐색이 정상이다.

BrandMate는 ComfyUI GUI에서 workflow를 수동 실행하지 않는다. 다음 API workflow 템플릿을 읽어 프롬프트, 크기, step, guidance만 주입한 후 ComfyUI `/prompt` API를 호출한다.

```text
# [Design Intent] LLM이 workflow 구조나 모델 경로를 임의 변경하지 못하게 그래프를 코드 자산으로 고정한다.
apps/api/app/extensions/ad_content/workflows/flux_schnell_gguf_api.json
```

## 7. WSL Ollama와 Qwen 설치

Windows LM Studio의 `localhost:1234`는 WSL의 `localhost`와 동일한 프로세스가 아니다. 방화벽과 host binding 설정 없이 섞으면 연결 오류가 반복된다. 이 가이드는 FastAPI와 같은 WSL 안에 Ollama를 설치한다.

```bash
# [Design Intent] LLM 서버를 FastAPI와 동일한 Linux 네트워크 공간에 둔다.
curl -fsSL https://ollama.com/install.sh | sh
ollama pull qwen2.5:7b-instruct
```

공식 설치 스크립트는 [Ollama Linux 다운로드 페이지](https://ollama.com/download/linux)에서 확인한다.

```bash
# [Design Intent] OpenAI 호환 endpoint와 실제 model id를 검증한다.
curl http://127.0.0.1:11434/v1/models
```

응답 model id가 `qwen2.5:7b-instruct`인지 확인한다. API 요청의 논리 모델 ID는 `Qwen/Qwen2.5-7B-Instruct`지만 runtime registry가 `.env`의 실제 Ollama model id로 변환한다.

## 8. BrandMate API 설정

```bash
# [Design Intent] 백엔드 의존성을 이미지 모델 환경과 분리된 프로젝트 환경에 설치한다.
cd ~/personal/final_1_team/apps/api
conda activate ssakda
pip install -e ".[dev]"
```

`apps/api/.env`에 다음 값을 설정한다.

```env
# [Design Intent] 모든 모델 호출을 WSL 내부 로컬 서비스로 고정한다.
BRANDMATE_WEB_ORIGIN=http://127.0.0.1:5501
BRANDMATE_LLM_TIMEOUT_SECONDS=120

BRANDMATE_LOCAL_LLM_BASE_URL=http://127.0.0.1:11434/v1
BRANDMATE_LOCAL_LLM_API_KEY=
BRANDMATE_QWEN_BASE_URL=http://127.0.0.1:11434/v1
BRANDMATE_QWEN_MODEL=qwen2.5:7b-instruct
BRANDMATE_QWEN_API_KEY=

BRANDMATE_IMAGE_PROVIDER=comfyui
BRANDMATE_COMFYUI_BASE_URL=http://127.0.0.1:8188
BRANDMATE_COMFYUI_WORKFLOW_PATH=
BRANDMATE_COMFYUI_TIMEOUT_SECONDS=300
BRANDMATE_COMFYUI_POLL_INTERVAL_SECONDS=1
```

`BRANDMATE_COMFYUI_WORKFLOW_PATH`가 비어 있으면 저장소에 포함된 기본 workflow를 사용한다. `.env`를 수정한 뒤에는 FastAPI를 재시작해야 한다. 설정은 프로세스 시작 시 로드된다.

## 9. 서비스 실행 순서

항상 다음 순서로 실행한다.

1. Ollama 확인
2. ComfyUI 실행
3. FastAPI 실행
4. Frontend 실행

### 9.1 FastAPI

```bash
# [Design Intent] 광고 문구와 이미지 통합 router가 등록된 애플리케이션을 실행한다.
cd ~/personal/final_1_team/apps/api
conda activate ssakda
python -m uvicorn app.main:app --reload --port 8000
```

루트 `/`의 `404 Not Found`는 서버 실패가 아니다. 루트 endpoint를 만들지 않았기 때문이다.

```bash
# [Design Intent] API 자체와 로컬 이미지 모델 catalog를 확인한다.
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/api/v1/ad-content/image-models
```

API 문서는 `http://127.0.0.1:8000/docs`에서 확인한다.

### 9.2 Frontend

```bash
# [Design Intent] 정적 프론트엔드를 .env의 CORS origin과 동일한 주소로 제공한다.
cd ~/personal/final_1_team/apps/web-ad-content
python -m http.server 5501 --bind 127.0.0.1
```

브라우저에서 `http://127.0.0.1:5501`로 접속한다.

## 10. 전체 파이프라인 검증

먼저 세 서버를 독립적으로 검사한다.

```bash
# [Design Intent] 통합 요청 전에 어느 의존성이 죽어 있는지 즉시 구분한다.
curl http://127.0.0.1:11434/v1/models
curl http://127.0.0.1:8188/system_stats
curl http://127.0.0.1:8000/health
```

통합 요청을 실행한다.

```bash
# [Design Intent] 사용자 입력에서 Qwen JSON과 FLUX 이미지까지 이어지는 전체 경로를 검증한다.
curl -s -X POST http://127.0.0.1:8000/api/v1/ad-content/generate \
  -H "Content-Type: application/json" \
  -d '{
    "copy": {
      "model": "Qwen/Qwen2.5-7B-Instruct",
      "business_name": "달빛카페",
      "business_type": "cafe",
      "situation": "new_menu",
      "target_audiences": ["twenties"],
      "tone": "premium",
      "product_names": ["딸기 티라미수", "복숭아 에이드"],
      "features": ["부드러운 크림과 생딸기 조합", "햇살 좋은 창가에서 즐기는 시즌 음료"],
      "channel": "instagram",
      "promotion": null,
      "required_terms": ["딸기 티라미수", "복숭아 에이드"],
      "prohibited_terms": ["최고", "무조건"]
    },
    "image_model": "black-forest-labs/FLUX.1-schnell",
    "image_width": 1024,
    "image_height": 1280
  }' > /tmp/ad_content_full_response.json
```

Base64 전체를 터미널에 출력하지 말고 상태만 확인한다.

```bash
# [Design Intent] 대용량 이미지 문자열을 제외하고 성공 또는 오류 detail만 확인한다.
python -c "import json; d=json.load(open('/tmp/ad_content_full_response.json')); print(d.keys()); print(d.get('detail', 'SUCCESS'))"
```

성공하면 이미지를 디코딩한다.

```bash
# [Design Intent] API의 Base64 이미지 응답을 실제 PNG 파일로 복원한다.
python -c "import json,base64; d=json.load(open('/tmp/ad_content_full_response.json')); open('/tmp/ad_content_full.png','wb').write(base64.b64decode(d['image']['image_base64']))"
wslpath -w /tmp/ad_content_full.png
```

`/tmp/ad_content_full.png`는 실행 파일이 아니다. 경로를 Bash 명령처럼 입력하면 `Permission denied`가 정상이다. 출력된 Windows 경로를 파일 탐색기에서 열거나 `explorer.exe`로 연다.

## 11. 실제 발생한 문제와 해결 기록

| 증상 | 원인 | 해결 |
|---|---|---|
| Windows `nvidia-smi`는 성공하지만 WSL은 GPU access blocked | 드라이버 업데이트 후 WSL GPU forwarding 상태 불일치 | Windows 재부팅 또는 `wsl --shutdown` 후 재실행 |
| ComfyUI가 `Found no NVIDIA driver`로 종료 | WSL에서 CUDA device를 보지 못함 | WSL `nvidia-smi`부터 복구한 뒤 ComfyUI 재실행 |
| FLUX GGUF가 목록에 없음 | 파일을 `models/` 루트에 배치 | `models/unet/flux1-schnell-Q4_K_S.gguf`로 이동 |
| GGUF workflow node가 없음 | 기본 ComfyUI는 GGUF UNet loader를 제공하지 않음 | `ComfyUI-GGUF` clone 및 requirements 설치 |
| GGUF 파일만 있는데 생성 불가 | FLUX가 dual text encoder와 VAE를 별도 사용 | `clip_l`, `t5xxl`, `ae` 추가 설치 |
| VAE 다운로드 `401 Unauthorized` | FLUX.1-schnell gated repository 승인 또는 인증 누락 | 모델 페이지 약관 동의, 접근 승인, `hf auth login` |
| `huggingface-cli` deprecated | CLI 명령 변경 | `hf auth login`, `hf download` 사용 |
| T5 파일이 `.safetensors.1`로 중복 생성 | 같은 파일을 두 번 다운로드 | 체크섬 확인 후 중복 파일 정리 |
| `Port 8188 is already in use`와 DB lock | ComfyUI 프로세스를 이미 실행 중인데 다시 실행 | `lsof -i :8188`로 기존 PID 확인, 정상 서버 재사용 |
| `Port 8000 is already in use` | Uvicorn reload parent/worker가 이미 실행 중 | `lsof -i :8000` 확인 후 기존 서버를 종료하고 한 번만 실행 |
| 브라우저에서 generate URL 접속 시 `Method Not Allowed` | 생성 endpoint는 GET이 아닌 POST 전용 | Swagger 또는 `curl -X POST` 사용 |
| JSON 출력에서 알 수 없는 긴 문자열 | PNG가 Base64로 JSON에 포함됨 | JSON 전체 출력 금지, Base64를 PNG로 디코딩 |
| PNG 경로 입력 시 `Permission denied` | 이미지 파일을 프로그램처럼 실행하려 함 | `wslpath -w`로 경로 변환 후 이미지 뷰어로 열기 |
| LM Studio `localhost:1234` 연결 실패 | LM Studio는 Windows, FastAPI는 WSL에서 실행 | WSL Ollama로 통일하거나 Windows host binding/firewall 별도 설정 |
| UI는 API 연결됨인데 ComfyUI 연결 실패 | FastAPI는 살아 있지만 `8188` ComfyUI 프로세스가 종료됨 | `curl /system_stats` 확인 후 ComfyUI 재시작 |
| Qwen 이후 ComfyUI가 죽거나 매우 느림 | 16GB RAM/12GB VRAM에서 두 모델이 메모리 경쟁 | `--lowvram`, 순차 실행, Ollama unload 정책, 작업 큐 적용 |
| `Token indices ... 540 > 512` | LLM이 만든 이미지 prompt가 text encoder 한도를 초과 | 이미지 prompt 길이를 제한하고 핵심 시각 정보만 전달 |
| `cu130 or higher` 최적화 경고 | 검증 환경이 PyTorch CUDA 12.1 build | 기능 오류는 아님. 성능 업그레이드는 별도 branch에서 호환성 검증 |
| `/` 요청이 404 | FastAPI root endpoint 미정의 | `/health`, `/docs`, `/api/v1/...` 사용 |

## 12. 단일 GPU와 운영환경 기준

### L1: 로컬 POC

- Ollama, ComfyUI, FastAPI를 수동 실행한다.
- 한 번에 한 요청만 처리한다.
- Qwen 완료 후 FLUX를 순차 실행한다.
- `--lowvram`을 사용한다.

### L2: MVP

- 현재 동기식 장시간 HTTP 요청을 job 기반 비동기 API로 전환한다.
- API는 즉시 `job_id`를 반환하고 frontend는 polling 또는 WebSocket으로 상태를 받는다.
- GPU 작업 큐와 동시 실행 제한을 둔다.
- Qwen을 내린 뒤 FLUX를 실행해야 한다면 전체 GPU 작업을 직렬화한다. 요청 하나가 다른 요청의 모델을 임의로 unload하면 안 된다.
- 이미지 Base64를 API 응답에 계속 싣기보다 object storage URL을 반환한다.
- timeout, 실패 단계, LLM latency, image latency를 구조화 로그와 metric으로 남긴다.

### L3: 운영

```text
# [Design Intent] 모델 재로딩을 제거하고 각 GPU worker의 모델을 상주시킨다.
Stateless FastAPI
-> Job Queue
   -> LLM GPU Worker (Qwen 상시 로딩)
   -> Image GPU Worker (ComfyUI/FLUX 상시 로딩)
-> Object Storage
-> Result API / WebSocket
```

운영환경에서 요청마다 Qwen을 unload하는 방식은 모델 재로딩 latency와 GPU thrashing 때문에 확장되지 않는다. LLM과 이미지 워커를 별도 GPU로 분리하고 각각 모델을 상주시킨다. 큐 길이 제한, rate limit, backpressure, idempotency key, retry 정책, worker health check가 필요하다.

| Component | Cost shape | 병목 | MVP 대응 | 운영 대응 |
|---|---|---|---|---|
| Qwen inference | 요청당 수 초~수십 초 | GPU 점유와 모델 상주 메모리 | 단일 큐, 제한된 동시성 | 전용 GPU worker, batching |
| FLUX inference | 요청당 수십 초 이상 | GPU saturation과 긴 tail latency | ComfyUI queue, timeout | 이미지 worker 수평 확장 |
| 모델 swap | 수 GB disk/RAM/GPU 이동 | 요청마다 cold start | 단일 GPU에서는 감수 | 모델 상주, GPU 분리 |
| Base64 응답 | 이미지보다 약 33% 큼 | API memory와 network 증가 | 응답 크기 제한 | object storage URL |
| 외부/로컬 모델 호출 | network/process I/O | partial failure | timeout과 오류 단계 표시 | retry, circuit breaker, tracing |

## 13. 완료 체크리스트

- [ ] WSL `nvidia-smi`에서 GPU가 보인다.
- [ ] 네 개의 FLUX 필수 모델 파일이 정확한 폴더에 있다.
- [ ] `/object_info/UnetLoaderGGUF`에서 GGUF 모델이 보인다.
- [ ] Ollama `/v1/models`에서 `qwen2.5:7b-instruct`가 보인다.
- [ ] FastAPI `/health`가 `ok`를 반환한다.
- [ ] `/image-models`가 `Local ComfyUI` FLUX를 반환한다.
- [ ] 통합 API가 광고 문구, 이미지 프롬프트, PNG Base64를 반환한다.
- [ ] Frontend에서 최종 광고 문구와 이미지가 표시된다.
- [ ] `.env`, Hugging Face token, 모델 파일이 Git에 포함되지 않았다.

