# BrandMate AI 음성 광고 서비스

광고 문구를 자연스러운 한국어 음성으로 변환하는 BrandMate의 로컬 TTS
서비스입니다. `FunAudioLLM/Fun-CosyVoice3-0.5B-2512`를 WSL2의 NVIDIA
GPU에서 실행하며, BrandMate 웹에서 목소리와 속도를 선택해 음성을 생성하고
바로 재생하거나 파일로 내려받을 수 있습니다.

CosyVoice를 우선 사용하고 로컬 서비스가 준비되지 않았을 때는 설정에 따라
OpenAI Speech API로 폴백합니다.

## 주요 기능

- 로컬 GPU에서 실행되는 한국어 음성 광고 생성
- 허가된 기준 음성을 이용한 zero-shot voice cloning
- 남성·여성 및 감정별 5개 목소리 프리셋
- 시간, 가격, 수량, 할인율의 한국어 발음 정규화
- 긴 대본의 문장 단위 분할 생성 및 WAV 결합
- 대본과 연기 지시를 분리해 지시 문장 낭독 방지
- 말하기 속도 조절
- 동시 생성 1건 제한으로 VRAM 사용량 제어
- 웹 브라우저 재생 및 WAV/MP3 다운로드
- CosyVoice 장애 시 선택적 OpenAI TTS 폴백
- 225개 테스트 케이스 생성 및 품질 평가 자동화

## 기술 스택

| 영역 | 기술 |
| --- | --- |
| 로컬 TTS | Fun-CosyVoice3-0.5B-2512 |
| 음성 서비스 | Python 3.10, FastAPI, Uvicorn |
| 추론 환경 | WSL2 Ubuntu 22.04, CUDA, PyTorch |
| 백엔드 연동 | BrandMate FastAPI, HTTPX |
| 프론트엔드 | HTML, CSS, JavaScript, Web Audio |
| 발음 정확도 | GPT-4o Transcribe 기반 CER |
| 자연스러움 | NISQA-TTS v1 |
| 음량 | FFmpeg EBU R128 loudnorm |

## 서비스 구조

```mermaid
flowchart LR
    A["BrandMate 웹<br/>대본·목소리·속도"] --> B["FastAPI<br/>/api/v1/ad-content/audio/generate"]
    B --> C["CosyVoice 서비스<br/>127.0.0.1:50000"]
    C --> D["한국어 숫자·단위 정규화"]
    D --> E["긴 대본 문장 단위 분할"]
    E --> F["Cross-lingual 추론"]
    F --> G["WAV 결합"]
    G --> H["Base64 API 응답"]
    H --> I["브라우저 재생·다운로드"]
    C -. "실패 및 폴백 허용" .-> J["OpenAI Speech API"]
    J --> H
```

## 지원 목소리

| 내부 이름 | 웹 표시 | 기준 음성 |
| --- | --- | --- |
| `man_happy` | 남성 · 기쁨 | `voices/man_happy.wav` |
| `man_serious` | 남성 · 진지함 | `voices/man_serious.wav` |
| `woman_happy` | 여성 · 기쁨 | `voices/woman_happy.wav` |
| `woman_serious` | 여성 · 진지함 | `voices/woman_serious.wav` |
| `woman_whisper` | 여성 · 속삭임 | `voices/woman_whisper.wav` |

`man_whisper`와 `man_whisper2`는 쉰 목소리가 과장되는 문제가 있어 서비스와
웹 목록에서 제외했습니다. 기준 음성은 직접 녹음했거나 사용 허가를 받은
파일만 사용해야 합니다.

## 추론 방식

기본값은 `cross_lingual` 모드입니다.

- 사용자에게는 연기 지시 입력란을 노출하지 않습니다.
- 모델에는 내레이션 대본만 전달합니다.
- 기준 음성의 음색과 요청 속도는 유지합니다.
- `woman_whisper`는 속삭임을 보존하기 위한 내부 고정 지시를 사용합니다.
- 180자를 넘는 긴 대본은 문장 경계를 우선해 분할한 뒤 순서대로 결합합니다.

실험용 `instruct` 모드도 남아 있지만 지시 문장의 일부를 읽거나 대본 일부가
누락되는 현상이 있어 기본 운영 모드로 사용하지 않습니다.

## 한국어 발음 정규화

CosyVoice에 전달하기 전에 숫자와 단위를 실제 한국어 발음 형태로 변환합니다.

| 입력 | 변환 예시 |
| --- | --- |
| `오전 11시` | `오전 열한 시` |
| `오후 2시부터 5시` | `오후 두 시부터 다섯 시` |
| `9,900원` | `구천구백 원` |
| `10%` | `십 퍼센트` |
| `1+1` | `원 플러스 원` |
| `커피 2잔` | `커피 두 잔` |

## 요구 사항

- Windows 10/11과 WSL2
- Ubuntu 22.04
- NVIDIA GPU와 최신 Windows NVIDIA 드라이버
- Python 3.10
- 약 15GB 이상의 여유 공간
- `git`, `git-lfs`, `g++`, `sox`

개발 및 검증 환경은 RTX 4060 Laptop GPU 8GB입니다. 모델은 동시 요청을
1개로 제한한 상태에서 로컬 추론이 가능합니다.

## 설치

WSL Ubuntu 22.04 터미널에서 저장소의 `services/cosyvoice`로 이동합니다.

```bash
sudo apt update
sudo apt install -y \
  git git-lfs build-essential sox libsox-dev \
  python3.10 python3.10-dev python3.10-venv

cd /mnt/c/path/to/final_1_team/services/cosyvoice
bash setup.sh
```

설치 스크립트는 다음 작업을 수행합니다.

1. `~/.local/share/brandmate-cosyvoice`에 전용 가상환경을 만듭니다.
2. 공식 CosyVoice 저장소와 submodule을 내려받습니다.
3. CosyVoice 및 서버 의존성을 설치합니다.
4. 추론에 불필요하고 CUDA 충돌을 일으킬 수 있는 DeepSpeed를 제거합니다.
5. `Fun-CosyVoice3-0.5B-2512` 가중치를 내려받습니다.
6. PyTorch, Whisper, PyWorld 및 CUDA 상태를 검사합니다.

다른 설치 위치를 사용하려면 두 스크립트에서 같은 환경변수를 설정합니다.

```bash
export BRANDMATE_COSYVOICE_HOME="$HOME/my-cosyvoice-runtime"
bash setup.sh
bash start.sh
```

## 실행

### 1. CosyVoice 서비스

WSL에서 실행합니다.

```bash
cd /mnt/c/path/to/final_1_team/services/cosyvoice
bash start.sh
```

정상 실행 주소:

```text
http://127.0.0.1:50000
```

Windows PowerShell에서 상태를 확인합니다.

```powershell
Invoke-RestMethod http://127.0.0.1:50000/health
```

`ready`가 `true`이고 `voices`에 5개 프리셋이 표시되면 정상입니다. 첫 요청은
모델을 GPU에 올리므로 이후 요청보다 오래 걸립니다.

### 2. BrandMate 전체 서비스

별도 WSL 터미널에서 저장소 루트로 이동합니다.

```bash
./scripts/manage_brandmate_services_gcp.sh restart
```

웹 접속:

```text
http://127.0.0.1:5501
```

Swagger:

```text
http://127.0.0.1:7660/docs
```

## BrandMate 환경변수

`apps/api/.env`에 다음 값을 설정합니다.

```env
BRANDMATE_VOICE_PROVIDER=cosyvoice
BRANDMATE_COSYVOICE_BASE_URL=http://127.0.0.1:50000
BRANDMATE_COSYVOICE_MODEL=Fun-CosyVoice3-0.5B-2512
BRANDMATE_COSYVOICE_TIMEOUT_SECONDS=180
BRANDMATE_COSYVOICE_HEALTH_TIMEOUT_SECONDS=2
BRANDMATE_COSYVOICE_FALLBACK_TO_OPENAI=true
```

OpenAI 폴백을 사용할 때만 개인 또는 팀 API 키와 모델을 설정합니다.

```env
BRANDMATE_OPENAI_API_KEY=
BRANDMATE_OPENAI_TTS_MODEL=gpt-4o-mini-tts
BRANDMATE_OPENAI_TTS_FALLBACK_MODELS=tts-1-hd,tts-1
BRANDMATE_OPENAI_TTS_VOICE=coral
BRANDMATE_OPENAI_TTS_FORMAT=mp3
```

API 키는 Git에 커밋하지 않습니다. 폴백이 필요하지 않으면 다음과 같이
비활성화할 수 있습니다.

```env
BRANDMATE_COSYVOICE_FALLBACK_TO_OPENAI=false
```

## GCP GPU VM 실행

GCP에서는 BrandMate API와 CosyVoice를 같은 Ubuntu GPU VM에 배치하고,
CosyVoice의 `50000` 포트는 VM 내부 통신에만 사용합니다. 팀 검증 환경은
Ubuntu Linux, G2 계열 VM, NVIDIA L4 1장입니다.

### 1. VM과 GPU 확인

SSH로 VM에 접속한 뒤 GPU와 디스크를 먼저 확인합니다.

```bash
nvidia-smi
df -h
```

`nvidia-smi`에 `NVIDIA L4`, Driver Version과 CUDA Version이 표시되면
드라이버가 준비된 상태입니다. CosyVoice 설치만을 위해 CUDA Toolkit을 별도로
설치할 필요는 없습니다.

권장 초기 구성:

| 항목 | 권장값 |
| --- | --- |
| OS | Ubuntu 22.04 |
| 머신 | G2 계열 |
| GPU | NVIDIA L4 1장 |
| VRAM | 24GB |
| 디스크 여유 공간 | 최소 15GB |
| 음성 생성 동시성 | 1 |

### 2. 저장소 및 CosyVoice 설치

```bash
sudo apt update
sudo apt install -y \
  git git-lfs build-essential sox libsox-dev \
  python3.10 python3.10-dev python3.10-venv

mkdir -p ~/personal
cd ~/personal
git clone https://github.com/imella0706/final_1_team.git
cd final_1_team
git checkout feature/voice-ad-youngseong

bash services/cosyvoice/setup.sh
```

이미 clone한 VM에서는 새로 clone하지 않고 현재 브랜치를 갱신한 뒤
`setup.sh`를 다시 실행합니다. 기존 전용 가상환경과 모델 다운로드는 가능한
범위에서 재사용됩니다.

### 3. GCP API 환경 설정

BrandMate API 환경과 CosyVoice 환경은 분리합니다. API는 팀 표준 Conda 환경
`ssakda`, CosyVoice는 `~/.local/share/brandmate-cosyvoice/venv`를 사용합니다.

```bash
cd ~/personal/final_1_team

conda create -n ssakda python=3.12 -y
cd apps/api
conda run -n ssakda python -m pip install -U pip setuptools wheel
conda run -n ssakda python -m pip install -e ".[dev]"
cd ../..

cp apps/api/.env.gcp.example apps/api/.env
```

GCP VM에 Docker와 Compose가 없다면 팀 제공 설치 스크립트를 실행합니다.

```bash
./scripts/airflow/setup_gcp_vm_docker.sh
docker compose version
```

스크립트가 현재 사용자를 Docker 그룹에 추가했다면 SSH 연결을 종료했다가
다시 접속한 후 다음 단계를 진행합니다.

`apps/api/.env`의 DB, 인증, LLM 및 이미지 설정 자리표시자를 실제 GCP 값으로
교체하고 음성 공급자를 다음처럼 설정합니다.

```env
BRANDMATE_VOICE_PROVIDER=cosyvoice
BRANDMATE_COSYVOICE_BASE_URL=http://127.0.0.1:50000
BRANDMATE_COSYVOICE_MODEL=Fun-CosyVoice3-0.5B-2512
BRANDMATE_COSYVOICE_TIMEOUT_SECONDS=180
BRANDMATE_COSYVOICE_HEALTH_TIMEOUT_SECONDS=2
BRANDMATE_COSYVOICE_FALLBACK_TO_OPENAI=false
```

GCP에서 OpenAI 폴백까지 사용할 때만
`BRANDMATE_COSYVOICE_FALLBACK_TO_OPENAI=true`로 변경하고 Secret Manager
또는 Git에 포함되지 않는 `.env`에 API 키를 설정합니다.

HTTP 기반 내부 시연에서는 production용 Secure Cookie 설정을 그대로 사용할 수
없습니다. 로컬 Docker PostgreSQL과 GCP 외부 IP를 사용하는 제한된 팀 시연이라면
다음 값을 실제 주소에 맞게 설정합니다.

```env
BRANDMATE_ENVIRONMENT=development
BRANDMATE_DATABASE_URL=postgresql+asyncpg://brandmate:brandmate-local-only@127.0.0.1:5433/brandmate
BRANDMATE_WEB_ORIGIN=http://<GCP_EXTERNAL_IP_OR_DOMAIN>:5501
BRANDMATE_AUTH_PUBLIC_WEB_URL=http://<GCP_EXTERNAL_IP_OR_DOMAIN>:5501
BRANDMATE_AUTH_REFRESH_COOKIE_NAME=brandmate_refresh
BRANDMATE_AUTH_REFRESH_COOKIE_SECURE=false
```

이 HTTP 설정은 IP allowlist가 적용된 내부 시연 전용입니다. 공개 운영에서는
`BRANDMATE_ENVIRONMENT=production`, HTTPS 도메인, `Secure` 및 `__Host-`
Cookie, 실제 SMTP와 관리형 DB를 사용해야 합니다. 고정 외부 IP와 secret은
README나 코드에 기록하지 않습니다.

### 4. CosyVoice 백그라운드 실행

SSH 연결이 끊어져도 서비스를 유지하려면 저장소 루트에서 다음과 같이
실행합니다.

```bash
cd ~/personal/final_1_team
mkdir -p outputs/brandmate_services/pids

nohup setsid bash services/cosyvoice/start.sh \
  > outputs/brandmate_services/cosyvoice.log 2>&1 &

echo $! > outputs/brandmate_services/pids/cosyvoice.pid
```

로그와 상태를 확인합니다.

```bash
tail -f outputs/brandmate_services/cosyvoice.log
```

다른 SSH 터미널:

```bash
curl http://127.0.0.1:50000/health
nvidia-smi
```

`ready: true`이면서 `model_loaded: false`일 수 있습니다. 이는 모델 파일과
기준 음성은 준비됐지만 아직 첫 생성 요청이 없어 GPU에 모델을 올리지 않은
정상 상태입니다.

### 5. BrandMate 실행

Docker, Conda 환경과 `apps/api/.env` 설정을 완료한 뒤 실행합니다.

음성 광고만 검증하고 GPU 메모리를 CosyVoice에 집중하려면 ComfyUI를
비활성화합니다.

```bash
cd ~/personal/final_1_team
START_COMFYUI=false ./scripts/manage_brandmate_services_gcp.sh restart
```

이미지 광고까지 함께 검증할 때:

```bash
./scripts/manage_brandmate_services_gcp.sh restart
```

서비스 상태:

```bash
./scripts/manage_brandmate_services_gcp.sh status
curl http://127.0.0.1:50000/health
curl http://127.0.0.1:7660/health
curl http://127.0.0.1:7660/api/v1/ad-content/audio/providers
curl -I http://127.0.0.1:5501
```

L4 한 장에서 FLUX/ComfyUI와 CosyVoice를 동시에 실행하면 두 모델이 GPU
메모리를 함께 사용합니다. CUDA OOM이 발생하면 `START_COMFYUI=false`로 음성
서비스를 먼저 검증하거나 이미지와 음성 작업을 순차 실행합니다.

### 6. 외부 접속

권장 방식은 공개 방화벽 규칙을 추가하지 않고 SSH 터널을 사용하는 것입니다.
로컬 PC에서 다음 명령을 실행합니다.

```bash
gcloud compute ssh <VM_NAME> --zone <ZONE> -- \
  -L 5501:127.0.0.1:5501 \
  -L 7660:127.0.0.1:7660
```

로컬 브라우저에서 접속합니다.

```text
http://127.0.0.1:5501
```

팀 시연을 위해 외부 IP로 직접 접속해야 한다면 GCP 방화벽은 다음처럼
제한합니다.

| 포트 | 용도 | 공개 정책 |
| --- | --- | --- |
| `5501` | BrandMate 웹 | 팀원 공인 IP `/32`만 허용 |
| `7660` | FastAPI | 팀원 공인 IP `/32`만 허용 |
| `50000` | CosyVoice 내부 API | 외부 공개 금지 |
| `8188` | ComfyUI | 기본 비공개, 필요할 때만 IP 제한 |

프론트엔드는 접속한 호스트의 `7660` 포트로 API를 호출하므로, 외부 IP 방식은
`5501`과 `7660` 모두 허용해야 합니다. `0.0.0.0/0` 전체 공개는 사용하지
않습니다.

### 7. 로그, 재시작 및 종료

```bash
# CosyVoice 로그
tail -f outputs/brandmate_services/cosyvoice.log

# BrandMate 로그
./scripts/manage_brandmate_services_gcp.sh logs

# CosyVoice 종료
kill "$(cat outputs/brandmate_services/pids/cosyvoice.pid)"
rm -f outputs/brandmate_services/pids/cosyvoice.pid

# BrandMate 종료
./scripts/manage_brandmate_services_gcp.sh stop
```

CosyVoice 코드나 기준 음성을 갱신한 뒤에는 기존 프로세스를 종료하고
`nohup` 명령으로 다시 실행합니다. API의 `.env`를 변경한 경우에도 BrandMate
서비스를 재시작해야 합니다.

## API

### CosyVoice 로컬 API

```text
GET  /health
POST /v1/tts
```

PowerShell 요청 예시:

```powershell
$body = @{
  input = "오늘 커피는 딸기 라떼로 달콤하게."
  voice = "woman_happy"
  speed = 1.0
} | ConvertTo-Json

Invoke-WebRequest http://127.0.0.1:50000/v1/tts `
  -Method Post `
  -ContentType "application/json" `
  -Body $body `
  -OutFile sample.wav
```

응답은 `audio/wav`이며 다음 헤더를 포함합니다.

- `X-BrandMate-Model`
- `X-BrandMate-Voice`
- `X-BrandMate-Inference-Mode`
- `X-Generation-Latency-Ms`

### BrandMate 통합 API

```text
GET  /api/v1/ad-content/audio/providers
POST /api/v1/ad-content/audio/generate
```

요청 본문:

```json
{
  "input": "봄날커피의 딸기 크림 라떼를 만나보세요.",
  "voice": "woman_happy",
  "speed": 1.0
}
```

통합 API는 공급자, 실제 사용 모델, 폴백 여부, media type, Base64 음성과
생성 시간을 반환합니다.

## 테스트 데이터 자동 생성

`scripts/run_cosyvoice_test.py`는 목소리, 대본 길이 및 특수 표현 조합을
계획된 순서대로 생성합니다.

```powershell
# 다음 테스트 확인
.\apps\api\.venv\Scripts\python.exe .\scripts\run_cosyvoice_test.py --dry-run

# 다음 1건 생성
.\apps\api\.venv\Scripts\python.exe .\scripts\run_cosyvoice_test.py

# 남은 테스트 모두 생성
.\apps\api\.venv\Scripts\python.exe .\scripts\run_cosyvoice_test.py --all
```

기본 데이터 배치:

```text
finalproject12/
  voice test.csv
  test voices/
  final_1_team/
```

CSV를 Excel에서 열어 두면 저장할 수 없으므로 실행 전에 닫아야 합니다.
스크립트는 기존 번호 다음부터 재개하고, 생성 시간과 실제 WAV 길이를 기록하며,
기존 파일을 덮어쓰지 않습니다.

## 품질 평가

225개 광고 음성을 사람 평가와 세 가지 객관적 지표로 분석했습니다.

| 지표 | 의미 | 방향 |
| --- | --- | --- |
| 사람 평가 `total` | 발음, 억양, 음질, 안정성 종합 | 높을수록 좋음 |
| CER | 원본 대본과 ASR 전사의 문자 오류율 | 낮을수록 좋음 |
| NISQA-TTS | 사람의 자연스러움 MOS를 예측한 1~5점 | 높을수록 좋음 |
| LUFS-I | 광고 전체의 체감 음량 | 목표 범위의 일관성이 중요 |
| True Peak | 재생 과정의 최대 피크 | 0 dBTP 초과 주의 |

### 평가 결과

| 항목 | 결과 |
| --- | ---: |
| 전체 테스트 | 225개 |
| 사람 평가 평균 | 19.49 / 20 |
| 사람 평가 `total ≥ 18` | 217개 |
| Macro CER 평균 | 0.61% |
| Micro CER | 0.31% |
| CER 0% | 207개 |
| NISQA-TTS 평균 | 3.7643 / 5 |
| NISQA-TTS 범위 | 2.3234~4.7853 |
| LUFS-I 평균 | -16.14 |
| LUFS-I 범위 | -27.20~-9.19 |
| True Peak 범위 | -12.67~+0.31 dBTP |
| True Peak 0 dBTP 초과 | 53개 |

주요 해석:

- NISQA-TTS와 사람의 종합 점수 간 상관은 거의 없었으므로 NISQA를 단독 합격
  기준으로 사용하지 않습니다.
- CER는 ASR이 잘못된 숫자 발음을 문맥에 맞게 보정할 수 있어 숫자, 가격,
  시간과 할인율은 사람이 다시 듣습니다.
- `woman_serious`의 평균 음량은 `-24.35 LUFS-I`로 다른 프리셋보다 작아
  출력 음량 정규화가 필요합니다.
- 53개 파일이 0 dBTP를 초과해 후처리 limiter 도입이 후속 과제로 남아 있습니다.

### CER

개인 OpenAI API 키를 Git에서 제외되는
`apps/api/.env.voice-eval`에 설정합니다.

```env
OPENAI_API_KEY=
```

```powershell
.\apps\api\.venv\Scripts\python.exe .\scripts\evaluate_voice_cer.py `
  --dry-run --all

.\apps\api\.venv\Scripts\python.exe .\scripts\evaluate_voice_cer.py --all
```

전사 결과는 `test voices/.asr-cache`에 저장되어 재실행 시 중복 API 호출과
과금을 방지합니다.

### NISQA-TTS

CosyVoice와 분리한 CPU 가상환경에서 `nisqa_tts.tar`만 사용합니다.

```bash
~/.local/share/brandmate-nisqa/venv/bin/python \
  /mnt/c/path/to/final_1_team/scripts/evaluate_voice_nisqa.py \
  --all --batch-size 10 --max-segments 10000
```

긴 광고를 처리하기 위해 공식 기본 구간 상한 6000 대신 10000을 사용합니다.
가중치와 공식 NISQA 소스는 수정하지 않습니다.

### LUFS-I 및 True Peak

FFmpeg가 없으면 API 가상환경에 번들 실행 파일을 설치합니다.

```powershell
.\apps\api\.venv\Scripts\python.exe -m pip install imageio-ffmpeg

.\apps\api\.venv\Scripts\python.exe .\scripts\evaluate_voice_lufs.py `
  --all --workers 4
```

원본 WAV는 수정하지 않고 측정 결과만 CSV에 추가합니다. 모노 음성이 웹에서
양쪽 채널로 재생되는 상황을 반영해 `dual_mono=true`를 사용합니다.

## 검증

```powershell
.\apps\api\.venv\Scripts\python.exe -m pytest `
  apps/api/tests/test_cosyvoice_service.py `
  apps/api/tests/test_ad_audio.py `
  apps/api/tests/test_web_auth_contract.py `
  apps/api/tests/test_voice_test_automation.py `
  apps/api/tests/test_voice_cer_evaluation.py `
  apps/api/tests/test_voice_nisqa_evaluation.py `
  apps/api/tests/test_voice_lufs_evaluation.py

.\apps\api\.venv\Scripts\python.exe -m ruff check `
  scripts/evaluate_voice_cer.py `
  scripts/evaluate_voice_nisqa.py `
  scripts/evaluate_voice_lufs.py `
  scripts/run_nisqa_predict.py

node --check apps/web/app.js
```

최근 병합 후 음성 관련 테스트는 `51 passed`입니다.

## 문제 해결

### `invalid option name: pipefail`

`start.sh`를 `sh`가 아니라 Bash로 실행합니다.

```bash
bash start.sh
```

### 포트 50000이 이미 사용 중

```bash
ss -ltnp | grep :50000
```

기존 CosyVoice 프로세스를 확인한 뒤 중복 실행을 중지합니다.

### `pkg_resources`가 없어 Whisper 설치 실패

최신 `setup.sh`는 `setuptools<81`과 비격리 빌드를 사용합니다. 기존 환경을
그대로 둔 채 다시 실행할 수 있습니다.

```bash
bash setup.sh
```

### `pyworld` 빌드 중 `g++`를 찾지 못함

```bash
sudo apt update
sudo apt install -y build-essential python3.10-dev
bash setup.sh
```

### `CUDA_HOME does not exist`

DeepSpeed는 학습용 선택 의존성이며 이 서비스의 단일 GPU 추론에는 필요하지
않습니다.

```bash
VENV="$HOME/.local/share/brandmate-cosyvoice/venv"
"$VENV/bin/pip" uninstall -y deepspeed
bash start.sh
```

### 환경 검증

```bash
VENV="$HOME/.local/share/brandmate-cosyvoice/venv"
"$VENV/bin/pip" check
"$VENV/bin/python" -c \
  'import torch; print("CUDA available:", torch.cuda.is_available())'
```

## 알려진 제한 사항

- 모델 최초 로딩과 첫 생성은 시간이 오래 걸릴 수 있습니다.
- 동시 생성 요청은 1개씩 처리하므로 요청이 많으면 대기 시간이 늘어납니다.
- 기준 음성의 녹음 품질과 발화 방식이 결과에 큰 영향을 줍니다.
- Cross-lingual 모드는 자유로운 연기 지시를 지원하지 않습니다.
- 완전한 속삭임 기준음은 숨소리와 쉰 소리를 과장할 수 있습니다.
- CER, NISQA와 LUFS는 사람의 광고 적합성 평가를 대체하지 않습니다.

## 주요 파일

```text
services/cosyvoice/
  setup.sh                 WSL 설치 및 모델 다운로드
  start.sh                 로컬 음성 서비스 실행
  server.py                정규화, 분할, 추론 및 HTTP API
  requirements-server.txt  FastAPI 서버 의존성
  voices/                  허가된 기준 음성

apps/api/app/extensions/ad_content/
  audio_service.py         CosyVoice 호출 및 OpenAI 폴백
  router.py                통합 음성 API
  schemas.py               요청 및 응답 스키마

scripts/
  run_cosyvoice_test.py    225개 음성 생성 자동화
  evaluate_voice_cer.py    CER 자동 평가
  evaluate_voice_nisqa.py  NISQA-TTS 자동 평가
  evaluate_voice_lufs.py   LUFS-I 및 True Peak 자동 측정
  run_nisqa_predict.py     긴 음성을 지원하는 NISQA 실행 래퍼
```

## 데이터 및 음성 사용 주의

- 기준 음성은 소유권 또는 명시적인 사용 권한이 확인된 파일만 사용합니다.
- AI 생성 음성임을 사용자 화면에 표시합니다.
- API 키, 개인 음성 및 평가용 캐시는 공개 저장소에 올리지 않습니다.
- CosyVoice, NISQA 및 각 모델 가중치는 해당 프로젝트의 라이선스를 따릅니다.
