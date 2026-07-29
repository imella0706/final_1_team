# BrandMate 음성 광고 개발 진행 상황

## 현재 상태

로컬 CosyVoice를 우선 사용해 광고 음성을 생성하고, 사용할 수 없을 때
OpenAI TTS로 폴백하는 파이프라인이 구현되어 있습니다. 웹에서는 내레이션 대본,
목소리, 말하기 속도를 선택하고 생성된 음성을 바로 재생하거나 WAV/MP3 파일로
다운로드할 수 있습니다.

기본 로컬 모델은 `FunAudioLLM/Fun-CosyVoice3-0.5B-2512`이며 WSL2 Ubuntu
22.04 환경에서 실행합니다.

## 생성 파이프라인

```mermaid
flowchart LR
    A["웹: 대본·목소리·속도"] --> B["FastAPI /ad-content/audio/generate"]
    B --> C["CosyVoice /v1/tts"]
    C --> D["한국어 숫자 발음 정규화"]
    D --> E["긴 대본 문장 단위 분할"]
    E --> F["cross-lingual 음성 생성"]
    F --> G["WAV 결합 및 응답"]
    G --> H["웹 재생·다운로드"]
    C -. "실패 및 폴백 허용" .-> I["OpenAI Speech API"]
    I --> H
```

## 완료된 작업

- CosyVoice 설치 및 실행 스크립트 추가
  - `services/cosyvoice/setup.sh`
  - `services/cosyvoice/start.sh`
- 로컬 음성 HTTP 서비스 추가
  - `GET /health`
  - `POST /v1/tts`
  - 포트 `50000`
  - 동시 생성 요청을 1개로 제한해 VRAM 사용량 제어
- BrandMate FastAPI에 음성 생성 API와 공급자 상태 확인 기능 연결
- CosyVoice 우선, OpenAI TTS 선택적 폴백 구현
- 웹 음성 광고 UI 구현
  - 내레이션 대본 편집
  - 목소리 선택
  - 말하기 속도 조절
  - 생성 상태 및 오류 표시
  - 브라우저 내 오디오 재생
  - 음성 파일 다운로드
- 한국어 숫자 발음 정규화
  - 예: `평일 오전 11시` → `평일 오전 열한 시`
  - 가격, 퍼센트, 시간 표현 처리
- 긴 대본을 문장 단위로 나누어 순서대로 생성한 뒤 결합
  - 대본 일부 누락 현상 완화
- cross-lingual 모드에서 지시 문장이 음성으로 읽히지 않도록 대본과 지시 분리
- 웹의 `연기 지시` 입력란 및 요청 payload 제거
  - 현재 기본 cross-lingual 모드에서는 사용자 지시가 적용되지 않기 때문
- 감정별 로컬 기준 음성 라벨 적용
- 불안정한 `남성 · 속삭임` 프리셋 제거
  - `man_whisper`와 `man_whisper2`는 UI에서 표시하지 않음
  - 해당 이름으로 로컬 서비스에 직접 요청해도 거부
  - WAV 파일 자체는 로컬 자료이므로 삭제하지 않음
- CosyVoice 반복 테스트 자동화 추가
  - 기존 CSV 기록 다음 번호부터 테스트 조합 자동 선택
  - 생성시간과 WAV 프레임 기반 실제 음성 길이 측정
  - 결과 WAV를 `../test voices/`에 저장
  - 결과를 `../voice test.csv`에 자동 추가
  - Excel 파일 잠금과 기존 WAV 덮어쓰기를 사전 차단
  - 2026-07-25 기준 1~225번 테스트 기록 완료
  - 자동화 구간 56~225번의 `voice_time`은 반올림한 정수 초로 기록
  - 자동화 WAV 170개 검증 완료, 총 약 96.81MB

## 현재 지원하는 로컬 목소리

| 내부 이름 | 웹 표시 |
| --- | --- |
| `man_happy` | 남성 · 기쁨 |
| `man_serious` | 남성 · 진지함 |
| `woman_happy` | 여성 · 기쁨 |
| `woman_serious` | 여성 · 진지함 |
| `woman_whisper` | 여성 · 속삭임 |

기준 음성 파일은 `services/cosyvoice/voices/<name>.wav`에 위치합니다. 

## 기본 실행 모드

기본값은 `COSYVOICE_INFERENCE_MODE=cross_lingual`입니다.

- 웹에서는 사용자 연기 지시를 받거나 전송하지 않습니다.
- 선택한 기준 음성의 음색과 말하기 속도는 적용됩니다.
- `woman_whisper`만 속삭임 보존을 위해 내부 고정 지시를 사용합니다.
- 실험용 `instruct` 모드는 남겨 두었지만 지시 일부를 읽는 문제가 있어 기본으로
  사용하지 않습니다.

## 실행 및 확인

### CosyVoice

WSL Ubuntu 22.04에서:

```bash
cd /mnt/c/Users/ASUS/Downloads/finalproject12/final_1_team/services/cosyvoice
bash start.sh
```

Windows PowerShell에서 상태 확인:

```powershell
Invoke-RestMethod http://127.0.0.1:50000/health
```

`ready: true`이고 `voices`에 지원하는 5개 목소리가 표시되면 정상입니다. 최초
음성 생성은 모델을 GPU에 로드하므로 이후 요청보다 오래 걸립니다.

### BrandMate 전체 서비스

팀의 현재 서비스 관리 방식은 루트 `README.md`와
`scripts/manage_brandmate_services_gcp.sh`를 기준으로 합니다. 웹 접속 주소는
`http://127.0.0.1:5501/`입니다.

## GPT-4o Transcribe CER 자동 평가

`scripts/evaluate_voice_cer.py`는 225개 테스트 WAV를 `gpt-4o-transcribe`로
전사하고 기존 `voice test.csv`에 CER 결과를 추가합니다. 개인 API 키는 Git에서
제외되는 `apps/api/.env.voice-eval`의 `OPENAI_API_KEY`에서만 읽습니다.

```powershell
# 파일 매핑과 미완료 범위만 확인
.\apps\api\.venv\Scripts\python.exe .\scripts\evaluate_voice_cer.py --dry-run --all

# 1건 스모크 테스트
.\apps\api\.venv\Scripts\python.exe .\scripts\evaluate_voice_cer.py --count 1

# 남은 항목 전부 처리
.\apps\api\.venv\Scripts\python.exe .\scripts\evaluate_voice_cer.py --all
```

- 완료된 `cer` 행은 다음 실행에서 자동으로 건너뜁니다.
- API 응답은 `test voices/.asr-cache`에 WAV 해시와 함께 저장되어 재과금을
  방지합니다.
- 최초 실행 시 `voice test.before-cer.csv` 백업을 만듭니다.
- 원본 사람 평가 컬럼은 보존하고 ASR 전사, 정규화 문자열, 편집 거리, CER,
  토큰 사용량과 지연시간 컬럼을 추가합니다.
- 숫자, 시간, 가격, 할인율은 CosyVoice와 같은 한국어 읽기 형태로 정규화한 뒤
  공백과 문장부호를 제외하고 CER를 계산합니다.

2026-07-27 기준 225개 평가를 완료했습니다.

- Macro 평균 CER: `0.61%`
- 전체 문자 기준 Micro CER: `0.31%`
- CER `0%`: 207개
- CER `5% 이하`: 218개
- 최대 CER: `26.67%`
- API 토큰 기준 예상 비용: 약 `$0.17`

CER는 ASR 결과에 의존합니다. 특히 193~195번처럼 사람이 `ten%`로 들은 발음을
ASR이 문맥상 `10%`로 전사하면 CER가 `0%`로 나올 수 있습니다. 숫자·가격·할인율
같은 중요 문구는 CER만으로 통과시키지 않고 사람 평가를 함께 사용해야 합니다.

## NISQA-TTS 전용 환경

NISQA는 CosyVoice와 분리된 WSL Ubuntu 22.04 환경에 설치했습니다.

| 항목 | 값 |
| --- | --- |
| 설치 루트 | `/home/spai0930/.local/share/brandmate-nisqa` |
| 가상환경 | `/home/spai0930/.local/share/brandmate-nisqa/venv` |
| 공식 소스 | `/home/spai0930/.local/share/brandmate-nisqa/NISQA` |
| 공식 소스 커밋 | `fe84f0f252abec382b24367d5b22498a7ce34dbb` |
| 가중치 | `weights/nisqa_tts.tar` |
| Python | `3.10` |
| PyTorch | `2.5.1+cpu` |

공식 환경의 Python 3.9, PyTorch 1.10, CUDA 10.2 고정값은 RTX 4060 세대 및 현재
CosyVoice 환경과 맞지 않아 사용하지 않았습니다. NISQA-TTS 모델은 작으므로
CPU 전용 PyTorch로 격리해 CUDA 충돌을 피했습니다.

```bash
source ~/.local/share/brandmate-nisqa/venv/bin/activate
cd ~/.local/share/brandmate-nisqa/NISQA
mkdir -p ~/.local/share/brandmate-nisqa/results

python run_predict.py \
  --mode predict_file \
  --pretrained_model weights/nisqa_tts.tar \
  --deg "/mnt/c/Users/ASUS/Downloads/finalproject12/test voices/T001_man_happy_short1.wav" \
  --output_dir ~/.local/share/brandmate-nisqa/results
```

스모크 테스트에서 `T001_man_happy_short1.wav`의 `mos_pred`는 `3.8472`,
모델 표시는 `NISQA_TTS_v1`로 정상 출력됐습니다. 공식 스크립트는 출력 폴더를
자동 생성하지 않으므로 실행 전에 `mkdir -p`가 필요합니다. 신뢰한 공식
가중치를 `torch.load`하는 과정에서 출력되는 `weights_only=False`
`FutureWarning`은 추론 실패가 아닙니다.

## NISQA-TTS 자동 평가

225개 WAV의 NISQA-TTS 자연스러움 평가를 완료하고 `voice test.csv`에 다음
컬럼을 추가했습니다.

- `nisqa_tts_naturalness`
- `nisqa_model`
- `nisqa_source_commit`
- `nisqa_evaluated_at`

```bash
~/.local/share/brandmate-nisqa/venv/bin/python \
  /mnt/c/Users/ASUS/Downloads/finalproject12/final_1_team/scripts/evaluate_voice_nisqa.py \
  --all --batch-size 10 --max-segments 10000
```

- 평가 완료: `225/225`
- 평균: `3.7643`
- 중앙값: `3.7569`
- 표준편차: `0.5680`
- 최소: `2.3234` (43번, `woman_whisper_short3`)
- 최대: `4.7853` (173번, `woman_happy_price`)
- 모델: `NISQA_TTS_v1`
- 공식 소스 커밋: `fe84f0f252abec382b24367d5b22498a7ce34dbb`
- 전체 결과: `~/.local/share/brandmate-nisqa/runs/voice-test-20260727-111718-953711/NISQA_results.csv`
- 원본 백업: `C:\Users\ASUS\Downloads\finalproject12\voice test.before-nisqa.csv`

공식 기본값인 `ms_max_segments=6000`은 일부 매우 긴 음성에서 부족하므로
자동화 래퍼의 기본값을 `10000`으로 설정했습니다. 가중치와 공식 소스는
수정하지 않았습니다.

기존 사람 평가 및 CER 25개 컬럼은 백업본과 대조해 모든 값이 동일함을
확인했습니다. NISQA와 사람의 `total` 점수 사이 피어슨 상관계수는
`-0.043`, `sound_quality`와는 `0.055`였습니다. 이 데이터에서는 NISQA를
사람 평가의 대체값으로 보지 않고 자연스러움에 관한 독립적인 참고 지표로
사용해야 합니다.

## LUFS-I 및 True Peak 자동 측정

FFmpeg `loudnorm` 필터로 225개 WAV의 통합 음량과 True Peak 측정을
완료했습니다. 원본 파일은 정규화하거나 수정하지 않았습니다. 웹에서 모노
음성이 양쪽 채널로 재생되는 상황을 반영하기 위해 `dual_mono=true`를
사용했습니다.

CSV에 추가한 지표 및 메타데이터 컬럼:

- `lufs_integrated`
- `true_peak_dbtp`
- `lufs_tool`
- `lufs_measured_at`

Windows 또는 WSL에 FFmpeg가 없으면 프로젝트 API 가상환경에 번들 FFmpeg를
설치할 수 있습니다.

```powershell
.\apps\api\.venv\Scripts\python.exe -m pip install imageio-ffmpeg

# 파일 매핑과 미완료 범위 확인
.\apps\api\.venv\Scripts\python.exe .\scripts\evaluate_voice_lufs.py `
  --dry-run --all

# 남은 항목 전부 측정
.\apps\api\.venv\Scripts\python.exe .\scripts\evaluate_voice_lufs.py `
  --all --workers 4
```

2026-07-27 기준 전체 측정 결과:

- 평가 완료: `225/225`
- LUFS-I 평균: `-16.14`
- LUFS-I 중앙값: `-14.53`
- LUFS-I 범위: `-27.20 ~ -9.19`
- LUFS-I 표준편차: `4.45`
- True Peak 범위: `-12.67 ~ +0.31 dBTP`
- True Peak `0 dBTP` 초과: 53개
- True Peak `-1.5 dBTP` 초과: 114개
- `-17 ~ -15 LUFS-I` 범위: 48개
- 원본 백업: `C:\Users\ASUS\Downloads\finalproject12\voice test.before-lufs.csv`

목소리별 평균 LUFS-I는 `man/happy -13.73`, `man/serious -13.22`,
`woman/happy -13.57`, `woman/serious -24.35`, `woman/whisper -15.85`로
나왔습니다. 특히 여성 진지함은 다른 목소리보다 약 9~11 LU 작아 재생 음량의
일관성 문제가 큽니다. True Peak가 0 dBTP를 넘은 파일은 재생 또는 인코딩
과정에서 피크 왜곡이 발생할 가능성이 있으므로 후처리 정규화가 필요합니다.

CSV는 `voice test.before-lufs.csv`와 대조해 기존 사람 평가, CER, NISQA
29개 컬럼의 모든 값이 동일함을 확인했습니다.

## 검증

최근 관련 테스트 결과:

```text
23 passed
CER/NISQA 자동 평가: 15 passed
LUFS 자동 측정: 7 passed
```

실행 명령:

```powershell
.\apps\api\.venv\Scripts\python.exe -m pytest `
  apps/api/tests/test_cosyvoice_service.py `
  apps/api/tests/test_ad_audio.py `
  apps/api/tests/test_web_auth_contract.py

node --check apps/web/app.js

.\apps\api\.venv\Scripts\python.exe -m pytest `
  apps/api/tests/test_voice_cer_evaluation.py `
  apps/api/tests/test_voice_nisqa_evaluation.py

.\apps\api\.venv\Scripts\python.exe -m ruff check `
  scripts/evaluate_voice_cer.py `
  scripts/evaluate_voice_nisqa.py `
  scripts/evaluate_voice_lufs.py `
  scripts/run_nisqa_predict.py `
  apps/api/tests/test_voice_cer_evaluation.py `
  apps/api/tests/test_voice_nisqa_evaluation.py `
  apps/api/tests/test_voice_lufs_evaluation.py
```

실제 웹 화면에서도 다음을 확인했습니다.

- 연기 지시 입력란이 표시되지 않음
- 남성 속삭임이 목소리 목록에 표시되지 않음
- 지원하는 로컬 목소리 5개가 표시됨

## 알려진 제약과 주의사항

- 첫 모델 로딩에 시간이 걸릴 수 있습니다.
- 포트 `50000`을 이미 다른 CosyVoice 프로세스가 사용 중이면
  `address already in use` 오류가 발생합니다.
- `bash start.sh`는 Bash에서 실행해야 합니다. `sh start.sh`로 실행하면
  `invalid option name: pipefail` 오류가 발생할 수 있습니다.
- 음성 기준 파일은 깨끗하고 배경음·잔향이 적은 모노 WAV가 가장 안정적입니다.
- 실제 완전한 속삭임 기준음은 CosyVoice에서 숨소리와 쉰 소리를 과장할 수 있습니다.
- OpenAI 폴백을 사용하려면 유효한 API 키와 계정에서 접근 가능한 TTS 모델이
  필요합니다.
- 현재 작업 트리의 `scripts/manage_brandmate_services_gcp.sh` 수정은 이 음성
  작업과 무관한 기존 팀원 변경이므로 되돌리거나 함께 커밋하지 않습니다.

## 주요 파일

- `apps/web/index.html`: 음성 광고 화면
- `apps/web/app.js`: 목소리 목록, 생성 요청, 재생 및 다운로드
- `apps/api/app/extensions/ad_content/audio_service.py`: CosyVoice/OpenAI 호출
- `apps/api/app/extensions/ad_content/schemas.py`: 음성 API 요청·응답 모델
- `services/cosyvoice/server.py`: 로컬 CosyVoice 서비스
- `services/cosyvoice/setup.sh`: WSL 설치
- `services/cosyvoice/start.sh`: 로컬 서비스 실행
- `services/cosyvoice/README.md`: 상세 설치 및 문제 해결
- `scripts/evaluate_voice_cer.py`: GPT-4o Transcribe 기반 CER 자동 평가
- `scripts/evaluate_voice_nisqa.py`: NISQA-TTS 배치 및 CSV 병합
- `scripts/evaluate_voice_lufs.py`: FFmpeg 기반 LUFS-I 및 True Peak 자동 측정
- `scripts/run_nisqa_predict.py`: 긴 음성을 지원하는 공식 NISQA 실행 래퍼
