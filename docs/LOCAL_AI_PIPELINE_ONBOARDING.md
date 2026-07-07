# 로컬 LLM + ComfyUI FLUX 온보딩 가이드_20260707_04:10

이 문서는 GCP/Linux 환경에서 BrandMate의 전체 로컬 생성 파이프라인을 실행하기 위한 팀 공용 가이드다.
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

### 2.1 GCP 팀 공용 VM 기준

| 항목 | 검증값 |
|---|---|
| OS | Ubuntu Linux GCP VM |
| GCP 머신 | G2 계열 |
| GPU | NVIDIA L4 1장 |
| VRAM | 약 24GB |
| RAM | 16GB |
| NVIDIA driver | `nvidia-smi` 기준 확인 |
| API/eval Python | 3.12 |
| ComfyUI Python | 3.11 |
| ComfyUI 포트 | `127.0.0.1:8188` |
| Ollama 포트 | `127.0.0.1:11434` |
| FastAPI 포트 | `127.0.0.1:8000` |
| Frontend 포트 | `127.0.0.1:5501` |

### 2.2 로컬 참고 환경

| 항목 | 검증값 |
|---|---|
| OS | Windows + WSL2 Linux |
| GPU | NVIDIA GeForce RTX 3060 |
| VRAM | 12GB |
| RAM | 16GB |
| API/eval Conda | `ssakda`, Python 3.12.13 |
| ComfyUI Conda | `comfyui`, Python 3.11.15 |

GCP L4는 VRAM이 약 24GB라 로컬 12GB GPU보다 이미지 생성에는 유리하다. 다만
GCP 제공 VM의 시스템 RAM 16GB와 vCPU 4개는 여전히 빡빡하므로, FLUX 단일 모델
smoke test는 `batch_size=1`, `concurrency=1`부터 시작한다. 로컬 12GB GPU에서는
`--lowvram`과 순차 실행이 필요하다.

## 3. GCP/Linux 설치 순서 요약

이 섹션은 팀원이 GCP GPU VM에서 최소 실험 환경을 빠르게 재현하기 위한 순서다.
자세한 설명은 뒤의 각 섹션을 따른다.

1. GCP GPU와 NVIDIA driver 확인

   ```bash
   # [Design Intent] GCP VM이 NVIDIA L4와 driver를 정상 인식하는지 먼저 확인한다.
   nvidia-smi
   ```

   `NVIDIA L4`, `Driver Version`, `CUDA Version`이 보이면 GPU/driver 설치는 끝난 상태다.
   이 단계에서 CUDA toolkit을 별도로 설치하지 않는다.

2. BrandMate API/eval 가상환경 생성

   여기서 API는 FastAPI 백엔드 서버를 의미하고, eval은 터미널에서 실행하는
   모델 평가 runner를 의미한다. 둘 다 BrandMate 앱 코드(`apps/api/app`)를 사용하므로
   같은 가상환경 `ssakda` 환경에서 실행한다.

   API/eval 환경은 ComfyUI 환경과 분리한다. `requirements`는 Python 버전을 자동으로
   맞추지 않으므로, 팀 기준 Python으로 Conda 환경을 직접 만든다. Conda는 Python
   버전과 가상환경 생성을 담당하고, 프로젝트 의존성 설치는 해당 환경 안의
   `python -m pip`로 수행한다.

   ```bash
   # [Design Intent] API/eval 환경은 ComfyUI와 분리하고 Python 3.12로 고정한다.
   cd ~/personal/final_1_team/apps/api
   conda create -n ssakda python=3.12 -y
   conda activate ssakda
   python --version
   python -m pip install -U pip setuptools wheel
   python -m pip install -r requirements-image-gpu-prod.txt --extra-index-url https://download.pytorch.org/whl/cu121
   ```

   GCP VM에 Conda가 없으면 Miniconda/Anaconda를 먼저 설치한다. OS 기본 Python에
   직접 설치하지 않는다.

   설치 후 GPU PyTorch 동작을 확인한다.

   ```bash
   # [Design Intent] Python이 NVIDIA L4를 실제로 사용할 수 있는지 확인한다.
   python -c "import torch; print(torch.__version__); print(torch.version.cuda); print(torch.cuda.is_available()); print(torch.cuda.get_device_name(0))"
   ```

   기대값은 `torch==2.5.1+cu121`, `torch.version.cuda == 12.1`,
   `torch.cuda.is_available() == True`, `NVIDIA L4`다.

3. FLUX.1 Schnell GGUF 양자화 모델 다운로드

   FLUX GGUF 모델은 아래 Hugging Face 저장소에서 받는다.
   - 정확한 확인을 위해 notion 링크에서도 확인한다.  
    https://app.notion.com/p/VISION-395e900739a380db9e37dce7277686ec

   - [city96/FLUX.1-schnell-gguf](https://huggingface.co/city96/FLUX.1-schnell-gguf/tree/main)

   단, ★★GGUF 본체 하나만으로는 실행되지 않는다. 아래 파일들이 모두 필요하다.

   | 역할 | 파일 | 설치 위치 |
   |---|---|---|
   | FLUX diffusion model | `flux1-schnell-Q4_K_S.gguf` | `~/personal/ComfyUI/models/unet/` |
   | CLIP encoder | `clip_l.safetensors` | `~/personal/ComfyUI/models/clip/` |
   | T5 encoder | `t5xxl_fp8_e4m3fn.safetensors` | `~/personal/ComfyUI/models/clip/` |
   | VAE | `ae.safetensors` | `~/personal/ComfyUI/models/vae/` |
   | GGUF loader | `ComfyUI-GGUF` | `~/personal/ComfyUI/custom_nodes/` |

4. Linux ComfyUI 설치

   - Linux에서는 Windows portable 패키지를 쓰지 않는다. ComfyUI 공식 저장소를 clone하고,
   ComfyUI 전용 Conda 환경을 Python 3.11로 만든다. 
   
   - ★기존 `ssakda`/API 가상환경과 섞지 않는다.

   ```bash
   # [Design Intent] ComfyUI는 API/eval 환경과 분리된 이미지 추론 서비스로 설치한다.
   cd ~/personal
   git clone https://github.com/Comfy-Org/ComfyUI.git
   cd ComfyUI
   conda create -n comfyui python=3.11 -y
   conda activate comfyui
   python -m pip install --upgrade pip setuptools wheel
   pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121
   pip install -r requirements.txt
   ```

5. ComfyUI-GGUF custom node 설치

   ```bash
   # [Design Intent] GGUF UNet loader 노드를 ComfyUI에 추가한다.
   cd ~/personal/ComfyUI/custom_nodes
   git clone https://github.com/city96/ComfyUI-GGUF.git
   cd ~/personal/ComfyUI
   pip install -r custom_nodes/ComfyUI-GGUF/requirements.txt
   ```

6. ComfyUI 실행

   ```bash
   # [Design Intent] GCP/로컬 단일 GPU에서 ComfyUI를 API 서버로 실행한다.
   conda activate comfyui
   cd ~/personal/ComfyUI
   python main.py --listen 127.0.0.1 --port 8188 --lowvram
   ```

   새 터미널에서 확인한다.

   ```bash
   curl http://127.0.0.1:8188/system_stats
   curl http://127.0.0.1:8188/object_info/UnetLoaderGGUF
   ```

7. BrandMate API/eval 실행

   `.env`에서 ComfyUI endpoint를 맞춘다. `127.0.0.1`은 "내 PC"가 아니라
   **현재 프로세스가 실행 중인 같은 머신**을 의미한다. 따라서 GCP VM 안에서
   ComfyUI와 BrandMate API/eval을 같은 VM에 같이 띄우면 `127.0.0.1:8188`이 맞다.
   이 VM 내부 통신에는 GCP 방화벽에서 `8188` 포트를 열 필요가 없다.

   ```env
   # [Design Intent] ComfyUI와 API/eval이 같은 GCP VM 안에서 실행될 때 사용한다.
   BRANDMATE_IMAGE_PROVIDER=comfyui
   BRANDMATE_COMFYUI_BASE_URL=http://127.0.0.1:8188
   ```

   외부 팀원이 브라우저에서 `http://우리 외부 ip:8188`처럼 GCP 외부 IP로
   ComfyUI UI를 직접 확인해야 한다면 설정이 달라진다. ComfyUI를 외부 접속 가능한
   주소로 listen해야 하고, GCP 방화벽에서 `tcp:8188`을 열어야 한다. 단,
   source range는 팀원들의 공인 IP `/32`만 등록한다. `0.0.0.0/0` 전체 공개는
   금지한다. ComfyUI는 기본적으로 외부 서비스용 인증/권한 제어가 강하지 않다.
   전체 공개하면 모르는 사용자가 UI에 접근해 GPU 작업을 계속 넣을 수 있고,
   GCP GPU 비용이 발생하거나 모델 파일/워크플로우가 노출되어 피해를 입을 수 있다. 

   ```bash
   # [Design Intent] 팀원 공인 IP allowlist가 걸린 GCP 방화벽 뒤에서만 외부 UI 접근을 허용한다.
   conda activate comfyui
   cd ~/personal/ComfyUI

   # 먼저 기본 실행
   python main.py --listen 0.0.0.0 --port 8188
   ```

   - OOM 나거나 VRAM 부족하면:
   ```bash
   python main.py --listen 0.0.0.0 --port 8188 --lowvram
   ```

   팀원 공인 IP는 각자 아래 명령으로 확인한다.

   ```bash
   curl ifconfig.me
   ```

   GCP 방화벽 규칙은 다음 기준으로 만든다.

   ```text
   target: 해당 GCP VM
   port: tcp:8188
   source ranges:
   - 팀원1_공인IP/32
   - 팀원2_공인IP/32
   - 팀원3_공인IP/32
   ```

   ComfyUI와 API/eval이 서로 다른 VM/컨테이너에 있으면 `127.0.0.1`을 쓰면 안 된다.
   그때는 같은 VPC 내부 통신이면 내부 IP를 사용한다.

   ```env
   # [Design Intent] API/eval은 VM A, ComfyUI는 VM B에서 실행될 때 내부망 주소를 사용한다.
   BRANDMATE_COMFYUI_BASE_URL=http://내부ip:8188
   ```

   외부 IP로 ComfyUI를 직접 열어둔 경우에도 source IP allowlist 없이 공개하면 안 된다.
   ComfyUI에는 인증/권한 제어가 약하므로 실험이 끝나면 `8188` 방화벽 규칙을 닫는다.
   SSH 접근 권한이 있는 사람은 외부 포트 공개 대신 SSH 터널을 사용할 수 있다.

   평가 runner는 API/eval 가상환경에서 실행한다.

   ```bash
   # [Design Intent] FLUX 단일 모델 기준으로 전체 연결과 report 생성을 smoke test한다.
   cd ~/personal/final_1_team/apps/api
   conda activate ssakda
   python scripts/evaluate_vision_models.py \
     --output-dir ~/personal/final_1_team/outputs/evaluations \
     --case-limit 1 \
     --repeats 1 \
     --concurrency 1 \
     --image-models black-forest-labs/FLUX.1-schnell
   ```

## 4. 사전 점검

GCP/Linux VM 안에서 GPU, 디스크, Conda 설치 상태를 먼저 확인한다.

```bash
# [Design Intent] GCP VM이 NVIDIA L4와 driver를 정상 인식하는지 확인한다.
nvidia-smi
```

```bash
# [Design Intent] 모델 파일과 Python 패키지를 설치할 디스크 여유 공간을 확인한다.
df -h
```

```bash
# [Design Intent] API/eval과 ComfyUI를 분리할 Conda 환경 관리자가 있는지 확인한다.
conda --version
```

`nvidia-smi`에서 `NVIDIA L4`, `Driver Version`, `CUDA Version`이 보이면 GPU와
driver는 준비된 상태다. 이 경우 CUDA toolkit을 별도로 설치하지 않는다.
`conda`가 없으면 Miniconda/Anaconda를 먼저 설치한다.

## 5. ComfyUI 설치

### 5.1 저장소와 Conda 환경

```bash
# [Design Intent] BrandMate 저장소와 독립된 이미지 추론 서비스로 설치한다.
cd ~/personal
git clone https://github.com/Comfy-Org/ComfyUI.git
cd ComfyUI
conda create -n comfyui python=3.11 -y
conda activate comfyui
python -m pip install --upgrade pip setuptools wheel
```

### 5.2 PyTorch와 ComfyUI 의존성

현재 팀에서 실제 이미지 생성까지 검증한 환경은 PyTorch `2.5.1+cu121`이다.

```bash
# [Design Intent] 팀에서 검증한 CUDA 12.1 PyTorch 환경을 재현한다.
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121
pip install -r requirements.txt
```

이 환경에서는 `cu130 or higher` 최적화 경고가 표시될 수 있지만 기본 추론은 동작한다. 신규 환경에서 최신 CUDA/PyTorch로 올릴 때는 ComfyUI와 ComfyUI-GGUF 호환성을 별도 검증해야 한다. 경고만 보고 기존 동작 환경을 즉시 업그레이드하지 않는다.

## 6. FLUX GGUF 필수 파일 설치

### 6.1 필요한 구성요소

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

### 6.2 디렉터리 생성

```bash
# [Design Intent] ComfyUI가 모델 종류별로 탐색하는 고정 디렉터리를 만든다.
mkdir -p ~/personal/ComfyUI/models/unet
mkdir -p ~/personal/ComfyUI/models/clip
mkdir -p ~/personal/ComfyUI/models/vae
```

### 6.3 Hugging Face CLI 준비

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

### 6.4 모델 다운로드

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

### 6.5 ComfyUI-GGUF 설치

```bash
# [Design Intent] 기본 ComfyUI에 없는 GGUF UNet loader 노드를 추가한다.
cd ~/personal/ComfyUI/custom_nodes
git clone https://github.com/city96/ComfyUI-GGUF.git
cd ~/personal/ComfyUI
pip install -r custom_nodes/ComfyUI-GGUF/requirements.txt
```

이미 clone되어 있다면 다시 clone하지 않는다.

### 6.6 파일 검증

```bash
# [Design Intent] 서버를 띄우기 전에 누락과 잘못된 모델 경로를 차단한다.
ls -lh ~/personal/ComfyUI/models/unet/flux1-schnell-Q4_K_S.gguf
ls -lh ~/personal/ComfyUI/models/clip/clip_l.safetensors
ls -lh ~/personal/ComfyUI/models/clip/t5xxl_fp8_e4m3fn.safetensors
ls -lh ~/personal/ComfyUI/models/vae/ae.safetensors
ls -ld ~/personal/ComfyUI/custom_nodes/ComfyUI-GGUF
```

`flux1-schnell-Q4_K_S.gguf`를 `models/` 루트에 두면 workflow에서 찾지 못한다. 반드시 `models/unet/`에 둔다.

## 7. ComfyUI 실행과 검증

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

## 8. Linux Ollama와 Qwen 설치

이 가이드는 FastAPI와 같은 Linux VM 안에 Ollama를 설치해 Qwen 2.5 7B
Instruct를 로컬 OpenAI 호환 endpoint로 사용한다. 같은 VM 안에서 실행하면
FastAPI가 `http://127.0.0.1:11434/v1`로 Ollama를 호출할 수 있다.

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

## 9. BrandMate API 설정

```bash
# [Design Intent] 백엔드 의존성을 이미지 모델 환경과 분리된 프로젝트 환경에 설치한다.
cd ~/personal/final_1_team/apps/api
conda activate ssakda
python -m pip install -e ".[dev]"
```

`apps/api/.env`에 다음 값을 설정한다.

```env
# [Design Intent] 모든 모델 호출을 같은 Linux VM 내부 로컬 서비스로 고정한다.
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

## 10. 서비스 실행 순서

항상 다음 순서로 실행한다.

1. Ollama 확인
2. ComfyUI 실행
3. FastAPI 실행
4. Frontend 실행

### 10.1 FastAPI

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

### 10.2 Frontend

```bash
# [Design Intent] 정적 프론트엔드를 .env의 CORS origin과 동일한 주소로 제공한다.
cd ~/personal/final_1_team/apps/web-ad-content
python -m http.server 5501 --bind 127.0.0.1
```

브라우저에서 `http://127.0.0.1:5501`로 접속한다.

## 11. 전체 파이프라인 검증

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

`/tmp/ad_content_full.png`는 실행 파일이 아니다. 경로를 Bash 명령처럼 입력하면
`Permission denied`가 정상이다. GCP/Linux에서는 `scp` 또는 브라우저/API 응답으로
파일을 내려받아 확인한다. WSL 로컬 테스트에서는 `wslpath -w`로 변환한 Windows 경로를
파일 탐색기에서 열거나 `explorer.exe`로 연다.

## 12. 실제 발생한 문제와 해결 기록

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

## 13. 단일 GPU와 운영환경 기준

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

## 14. 완료 체크리스트

- [ ] Linux VM에서 `nvidia-smi`로 GPU가 보인다.
- [ ] 네 개의 FLUX 필수 모델 파일이 정확한 폴더에 있다.
- [ ] `/object_info/UnetLoaderGGUF`에서 GGUF 모델이 보인다.
- [ ] Ollama `/v1/models`에서 `qwen2.5:7b-instruct`가 보인다.
- [ ] FastAPI `/health`가 `ok`를 반환한다.
- [ ] `/image-models`가 `Local ComfyUI` FLUX를 반환한다.
- [ ] 통합 API가 광고 문구, 이미지 프롬프트, PNG Base64를 반환한다.
- [ ] Frontend에서 최종 광고 문구와 이미지가 표시된다.
- [ ] `.env`, Hugging Face token, 모델 파일이 Git에 포함되지 않았다.
