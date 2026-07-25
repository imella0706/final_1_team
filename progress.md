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

## 검증

최근 관련 테스트 결과:

```text
23 passed
```

실행 명령:

```powershell
.\apps\api\.venv\Scripts\python.exe -m pytest `
  apps/api/tests/test_cosyvoice_service.py `
  apps/api/tests/test_ad_audio.py `
  apps/api/tests/test_web_auth_contract.py

node --check apps/web/app.js
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
