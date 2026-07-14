# BrandMate GCS / DVC Onboarding

이 문서는 BrandMate 데이터셋, 모델 비교 실험, 웹서비스 생성 결과, 로그를 GCS에 정리하는 기준입니다.

데이터셋을 새로 만들거나 GCS에 업로드하기 전에는 데이터셋 제출 규격을 먼저 확인합니다.

- [BrandMate Dataset Submission Onboarding](./DATASET_SUBMISSION_ONBOARDING.md)
- [BrandMate Airflow Onboarding](./AIRFLOW_ONBOARDING.md)

## 1. 설계 원칙

- `gs://ssakda`는 회사/ 공용 버킷입니다.
- BrandMate 부서 관련 파일은 `projects/brandmate/` 아래에 둡니다.
- DVC remote는 사람이 읽는 프로젝트 폴더와 분리해 `dvc/brandmate/`에 둡니다.
- AIHub 전체 100GB 원본은 비용 문제로 GCS에 올리지 않습니다.
- GCS에는 팀원이 선별한 dataset별 curated artifact와 processed/eval/output/log만 올립니다.
- VM은 GCS에서 필요한 subset만 내려받아 실행하는 GPU worker로 봅니다.

## 2. Google Cloud CLI 준비

GCS를 터미널에서 사용하려면 `gcloud` CLI가 필요합니다. Windows 사용자는 PowerShell이 아니라 WSL Ubuntu 터미널에서 아래 명령을 실행합니다.

```bash
# [Design Intent] WSL/Ubuntu 환경에서 Google Cloud CLI를 설치한다.
sudo apt-get update
sudo apt-get install -y apt-transport-https ca-certificates gnupg curl

curl -fsSL https://packages.cloud.google.com/apt/doc/apt-key.gpg \
  | sudo gpg --dearmor -o /usr/share/keyrings/cloud.google.gpg

echo "deb [signed-by=/usr/share/keyrings/cloud.google.gpg] https://packages.cloud.google.com/apt cloud-sdk main" \
  | sudo tee /etc/apt/sources.list.d/google-cloud-sdk.list

sudo apt-get update
sudo apt-get install -y google-cloud-cli
```

설치 확인:

```bash
gcloud --version
```

GCP 계정으로 로그인하고 프로젝트를 설정합니다.

```bash
# [Design Intent] 팀 프로젝트 GCP 계정과 프로젝트를 명확히 선택한다.
gcloud auth login
gcloud config set project sprint-ai-chunk5-01
```

현재 로그인 계정과 프로젝트를 확인합니다.

```bash
gcloud auth list
gcloud config list
```

버킷 접근 권한을 확인합니다.

```bash
# [Design Intent] 데이터 업로드 전에 ssakda 버킷 접근 권한을 검증한다.
gcloud storage ls gs://ssakda
```

이 명령이 실패하면 먼저 IAM 권한을 확인해야 합니다. 일반 팀원은 최소한 `저장소 개체 뷰어`와
`저장소 개체 생성자` 권한이 필요합니다.

## 3. 최종 GCS 구조

```text
gs://ssakda/
  projects/
    brandmate/
      data/
        landing/
          processed/
            sns_meme_trend/
              week=YYYY-Www/

        curated/
          aihub_food_image_text/
            v1/
          sns/
            v1/
          food_101/
            v1/

        processed/
          aihub_food_image_text/
            v1/
              food_description_data/
          sns/
            v1/
          food_101/
            v1/
          merged/
            v1/

        eval/
          smoke/
          comparison/
          final/
          source_split/
            aihub_food_image_text/
            sns/
            food_101/

        manifests/

      models/
        flux_schnell_gguf/
        sdxl/

      outputs/
        evaluations/
          vision/
        web_service_generated/

      logs/
        web_service/
          summary/
          errors/
        evaluations/
          summary/
          errors/

  dvc/
    brandmate/
```

## 4. 폴더 의미

| 경로 | 의미 |
| --- | --- |
| `data/landing/processed/sns_meme_trend/week=YYYY-Www/` | 팀원이 업로드하는 주간 밈 CSV 입고 구역입니다. 이미 선별/정제된 processed 후보이지만, 공식 데이터셋으로 승인되기 전 단계입니다. Airflow는 이 prefix를 검수 대상으로만 사용합니다. |
| `data/curated/aihub_food_image_text/v1/` | AIHub `비전영역 음식이미지 및 정보소개 텍스트 데이터` 원본에서 BrandMate에 쓸 샘플만 선별한 데이터 풀입니다. 학습/전처리/평가셋 후보를 뽑는 문제은행 역할입니다. |
| `data/curated/sns/v1/` | SNS/트렌드 source에서 수집 후 BrandMate 목적에 맞게 정제한 데이터 풀입니다. 초기에는 source별 폴더를 나누기보다 통합 데이터셋 단위로 관리합니다. |
| `data/curated/food_101/v1/` | Food-101 기반 음식 이미지 데이터 풀입니다. 카페/음식점 광고 이미지 보강이나 음식 도메인 평가에 사용합니다. |
| `data/processed/{dataset_name}/v1/{artifact_name}/` | dataset별 curated 데이터를 모델/API/평가 파이프라인이 바로 쓸 수 있게 전처리한 산출물입니다. 예: `data/processed/aihub_food_image_text/v1/food_description_data/` |
| `data/processed/merged/v1/` | dataset별 processed 데이터를 동일 schema로 맞춘 뒤 하나의 학습/비교실험 경로로 합친 통합 데이터셋입니다. manifest 없이 임의로 합치지 않습니다. |
| `data/eval/smoke/` | 배포 직후 FastAPI, ComfyUI, model call이 살아있는지만 확인하는 최소 시험지입니다. 품질 평가용이 아니라 연결 확인용입니다. |
| `data/eval/comparison/` | FLUX vs SDXL 등 모델/프롬프트/전처리 비교와 최종 리포트에 쓰는 고정 시험지입니다. 바꾸면 이전 실험과 비교가 깨집니다. |
| `data/eval/final/` | comparison과 별도로 최종 발표용 평가셋을 잠그고 싶을 때만 쓰는 고정 시험지입니다. 현재는 비워둘 수 있습니다. |
| `data/eval/source_split/{dataset_name}/` | AIHub, SNS, Food-101 등 dataset별로 성능이 어디서 약한지 따로 보는 시험지입니다. 전체 평균에 숨은 약점을 찾는 용도입니다. |
| `data/manifests/` | 데이터셋 출처, 버전, 용량, 선별 기준, merge rule을 기록하는 장부입니다. 데이터만 올리고 manifest를 안 남기면 추적성이 깨집니다. |
| `models/flux_schnell_gguf/` | FLUX GGUF 모델의 manifest, ComfyUI workflow, 설정 파일을 두는 곳입니다. 모델 weight 자체를 무조건 여기에 올린다는 뜻은 아닙니다. |
| `models/sdxl/` | SDXL 비교실험용 manifest, workflow, 설정 파일을 두는 곳입니다. 새 모델을 추가하면 같은 방식으로 model folder를 추가합니다. |
| `outputs/evaluations/` | 내부 터미널 평가 runner가 만든 report, metric, 평가 중 생성 이미지를 저장합니다. 실험 산출물이며 웹서비스 사용자 결과와 섞지 않습니다. |
| `outputs/web_service_generated/` | 실제 웹서비스에서 사용자가 만든 최종 광고 결과입니다. 평가용 이미지가 아니라 서비스 산출물입니다. |
| `logs/web_service/` | FastAPI, frontend, ComfyUI 웹서비스 실행 요약과 장애 로그입니다. 성공은 summary, 실패는 errors에 남깁니다. |
| `logs/evaluations/` | 내부 터미널 평가 runner 실행 요약과 장애 로그입니다. 웹서비스 로그와 분리합니다. |
| `dvc/brandmate/` | DVC 전용 object store입니다. 사람이 직접 파일을 정리하거나 삭제하지 않습니다. |

## 5. IAM 권한 정책

관리자를 제외한 일반 팀원의 초기 권한은 업로드와 조회만 허용합니다. 공유 데이터셋과 DVC remote를 삭제하거나 덮어쓸 수 없어야 합니다.

개발 과정에서 삭제 권한이 없어서 작업이 과도하게 불편해지는 경우에는 팀 내 협의 후 특정 담당자나 특정 prefix에 한해 삭제 권한 부여를 검토합니다. 기본값은 삭제 불가입니다.

- 나머지 팀원
  - 스토리지 뷰어
    - GCS 버킷 구조와 설정을 콘솔에서 학습 목적으로 확인할 수 있게 부여합니다.
    - 실무 운영 환경이라면 최소권한 원칙에 따라 일반 팀원에게는 부여하지 않습니다.
  - 저장소 개체 뷰어
    - 데이터셋, 평가 결과, 로그 object를 조회/다운로드할 수 있습니다.
  - 저장소 개체 생성자
    - 새 object를 업로드할 수 있습니다.
    - 기존 object 삭제/덮어쓰기는 할 수 없습니다.

- 일반 팀원에게 부여하지 않는 역할
  - 스토리지 편집자
  - 스토리지 관리자
  - 저장소 개체 관리자
  - 프로젝트 편집자
  - 프로젝트 소유자

## 6. 로그 구조

성공 로그 전체를 GCS에 모두 올리면 비용과 노이즈가 커집니다. 대신 성공은 요약만, 
실패는 상세 로그를 저장합니다.

```text
logs/
  web_service/
    summary/
      YYYYMMDD.jsonl
    errors/
      YYYYMMDD/
        HHMMSS_request_id/
          error.json
          fastapi.log
          frontend.log
          comfyui.log

  evaluations/
    summary/
      YYYYMMDD.jsonl
    errors/
      YYYYMMDD/
        HHMMSS_run_id/
          error.json
          eval.log
          comfyui.log
```

웹서비스 성공 summary 예시:

```json
{"time":"2026-07-09T15:30:22+09:00","request_id":"req_8f3a2c","status":"success","copy_model":"gpt-5.4-nano","image_model":"flux_schnell_gguf","latency_ms":95510,"prompt_chars":3120}
```

웹서비스 실패 error 예시:

```json
{
  "time": "2026-07-09T15:42:01+09:00",
  "request_id": "req_91aa0e",
  "status": "failed",
  "stage": "comfyui_prompt",
  "error_type": "ConnectError",
  "error_message": "Could not connect to ComfyUI",
  "copy_model": "gpt-5.4-nano",
  "image_model": "flux_schnell_gguf",
  "prompt_chars": 3910
}
```

### 6.1 GCP VM 장애 진단 순서

웹 화면이 뜨지 않거나 생성 버튼 이후 파이프라인이 멈추면 먼저 어느 서버가 죽었는지 잘라야 합니다.
BrandMate GCP VM 구성은 보통 아래 3개 프로세스와 외부 LLM API 설정에 의존합니다.

| 구성요소 | 기본 포트 | 확인 명령 | 실패 시 의심 지점 |
| --- | --- | --- | --- |
| Frontend 정적 서버 | `5501` | `curl -I http://127.0.0.1:5501` | 프론트 서버 미실행, CORS origin 불일치 |
| FastAPI backend | `7660` | `curl http://127.0.0.1:7660/health` | API 서버 미실행, `.env` 설정 오류 |
| ComfyUI image server | `8188` | `curl http://127.0.0.1:8188/system_stats` | ComfyUI 미실행, GPU/CUDA 오류, 모델 파일 누락 |
| LLM API 설정 | 없음 | `.env`의 `BRANDMATE_LLM_API_KEY` 또는 `BRANDMATE_OPENAI_API_KEY` 확인 | API key 누락, provider/model 설정 오류, rate limit |

장애 확인은 사람이 `curl`을 하나씩 치는 방식이 기본이 아닙니다. 기본 진단은 서비스 관리 스크립트로
한 번에 확인합니다.

```bash
# [Design Intent] 프론트, API, ComfyUI 상태를 한 번에 확인해 감에 의존한 디버깅을 줄인다.
cd ~/personal/final_1_team
scripts/manage_brandmate_services.sh status
```

전체 서비스를 시작하거나 재시작할 때도 같은 스크립트를 사용합니다.

```bash
# [Design Intent] GCP VM에서 필요한 웹서비스 프로세스를 표준 스크립트로 기동한다.
cd ~/personal/final_1_team
scripts/manage_brandmate_services.sh
scripts/manage_brandmate_services.sh logs
```

`qa` 명령은 서비스 기동 후 비전 평가 wrapper까지 실행합니다. 단순 장애 확인용이 아니라
`run_local_vision_eval.sh`를 호출해 smoke 수준의 생성 평가까지 돌리는 명령입니다.

```bash
# [Design Intent] 서비스 준비 상태 확인 후 최소 비전 평가까지 실행한다.
cd ~/personal/final_1_team
scripts/manage_brandmate_services.sh qa
```

아래 `curl` 명령은 스크립트가 없는 환경이거나 특정 endpoint만 직접 확인해야 할 때의 fallback입니다.

```bash
# [Design Intent] 자동 진단 스크립트가 없을 때 웹서비스 파이프라인의 의존성 경계를 수동으로 분리한다.
curl -I http://127.0.0.1:5501
curl http://127.0.0.1:7660/health
curl http://127.0.0.1:8188/system_stats
```

FastAPI는 살아 있는데 생성 요청만 실패하면 통합 endpoint를 직접 호출합니다.

```bash
# [Design Intent] 프론트엔드를 배제하고 FastAPI -> LLM -> ComfyUI 경로만 검증한다.
curl -s -X POST http://127.0.0.1:7660/api/v1/ad-content/generate \
  -H "Content-Type: application/json" \
  -d '{
    "copy": {
      "model": "Qwen/Qwen2.5-7B-Instruct",
      "business_name": "달빛카페",
      "business_type": "cafe",
      "situation": "new_menu",
      "target_audiences": ["twenties"],
      "tone": "friendly",
      "product_names": ["딸기 라떼"],
      "features": ["제철 딸기 사용"],
      "channel": "instagram",
      "required_terms": [],
      "prohibited_terms": ["최고", "무조건"]
    },
    "image_model": "black-forest-labs/FLUX.1-schnell",
    "image_width": 1024,
    "image_height": 1280
  }'
```

GCS에 저장된 장애 로그는 날짜와 request id 기준으로 조회합니다.

```bash
# [Design Intent] 장애 발생 시 GCS에 남긴 summary와 상세 error bundle을 먼저 확인한다.
gcloud storage ls gs://ssakda/projects/brandmate/logs/web_service/summary/
gcloud storage cat gs://ssakda/projects/brandmate/logs/web_service/summary/YYYYMMDD.jsonl
gcloud storage ls gs://ssakda/projects/brandmate/logs/web_service/errors/YYYYMMDD/
gcloud storage cp \
  gs://ssakda/projects/brandmate/logs/web_service/errors/YYYYMMDD/HHMMSS_request_id/ \
  ./debug/web_service/YYYYMMDD/HHMMSS_request_id/ \
  --recursive
```

장애 단계는 `error.json`의 `stage`로 먼저 판단합니다.

| `stage` 예시 | 의미 | 다음 확인 |
| --- | --- | --- |
| `frontend_request` | 브라우저 또는 정적 서버 쪽 문제 | `5501`, CORS, API base URL |
| `copy_model` | 외부 LLM API 호출 실패 | `.env` API key, provider base URL, 모델명, rate limit |
| `comfyui_prompt` | ComfyUI prompt 제출 실패 | `8188/system_stats`, workflow, custom node |
| `comfyui_result` | prompt는 들어갔지만 이미지 결과 수신 실패 | ComfyUI queue, VRAM, timeout |
| `response_write` | 결과 저장 또는 응답 생성 실패 | output path 권한, 디스크/GCS 업로드 |

운영 원칙은 단순합니다. 장애 로그는 “나중에 보기 좋은 기록”이 아니라 “어느 프로세스가 죽었는지
5분 안에 자르는 도구”여야 합니다. 그래서 `error.json`에는 최소한 `request_id`, `stage`,
`error_type`, `error_message`, `latency_ms`, 사용 모델명, 입력 크기를 남깁니다.

### 6.2 운영 로그 구현 상태와 확장 순서

현재 구현된 로그는 `manage_brandmate_services.sh`가 각 프로세스의 stdout/stderr를 로컬 파일로
남기는 수준입니다.

```text
outputs/brandmate_services/
  fastapi.log
  frontend.log
  comfyui.log
```

이 로그는 FastAPI, frontend, ComfyUI 프로세스가 뜨지 않는 문제를 확인하기 위한 1차 진단 로그입니다.
예를 들어 포트 충돌, conda 환경 오류, ComfyUI 실행 오류, uvicorn 실행 오류를 확인할 때 사용합니다.

다만 이 로그만으로는 사용자 요청 단위의 장애 추적이 어렵습니다. 운영 수준의 장애 추적을 위해서는
추가로 아래 구조가 필요합니다.

- `request_id` 기반 structured JSON logging
- 요청 단계별 `stage` 기록
- `latency_ms`, `error_type`, `error_message` 기록
- 정상/실패 요청의 최소 summary log 저장
- 장애 발생 시 GCS `logs/web_service/errors/`에 error bundle 저장

BrandMate는 VM 디스크가 100GB 수준이므로 로컬에 로그를 장기 보관하지 않습니다. 평상시에는 얇은
summary log와 metric만 남기고, 장애가 발생했을 때만 상세 error bundle을 GCS에 저장합니다.

```text
gs://ssakda/projects/brandmate/logs/web_service/
  summary/
    dt=YYYY-MM-DD/
      summary.jsonl
  errors/
    dt=YYYY-MM-DD/
      {request_id}/
        error.json
        request_summary.json
        traceback.txt
```

`summary.jsonl`에는 모든 요청의 최소 메타데이터만 저장합니다.

```json
{"time":"2026-07-13T15:30:22+09:00","request_id":"req_1","status":"success","endpoint":"/api/v1/ad-content/generate","latency_ms":92340,"copy_model":"gpt-4.1-mini","image_model":"flux_schnell"}
{"time":"2026-07-13T15:35:10+09:00","request_id":"req_2","status":"failed","endpoint":"/api/v1/ad-content/generate","latency_ms":120000,"stage":"comfyui_result","error_type":"TimeoutError"}
```

상세 request payload, 긴 prompt, 이미지 base64, LLM raw response 전체는 summary log에 남기지 않습니다.
이 값들은 비용, 개인정보, 용량 문제를 만들 수 있으므로 장애 발생 시 필요한 범위에서만 error bundle에
제한적으로 저장합니다.

### 6.3 Observability 적용 우선순위

Cloud Logging은 관리형 로그 수집/검색에는 좋지만 비용이 발생할 수 있습니다. Prometheus와 Grafana는
오픈소스지만 직접 운영해야 하고, 기본 역할은 로그 저장이 아니라 metric 수집과 대시보드입니다.

BrandMate에서는 아래 순서로 구현합니다.

1. Airflow 기반 주기 데이터 인입 파이프라인을 먼저 구축합니다.
2. FastAPI에 `request_id` 기반 structured logging을 추가합니다.
3. 장애 발생 시 GCS error bundle 저장을 추가합니다.
4. Prometheus/Grafana는 latency, error rate, GPU 사용률, ComfyUI queue 같은 metric 관찰용으로 추가합니다.
5. Cloud Logging 연동은 비용과 필요성을 보고 ERROR/WARNING 중심으로 제한 적용합니다.

Prometheus/Grafana를 도입하더라도 GCS를 Prometheus의 기본 저장소로 사용하지 않습니다. Prometheus는
로컬 TSDB에 짧은 retention을 두고 metric을 저장합니다. GCS는 장애 상세 로그, 평가 결과, error bundle 같은
장기 보관 산출물에 사용합니다.

```text
Prometheus/Grafana:
  request_count, error_rate, latency_p95, GPU memory, ComfyUI queue length

GCS:
  summary.jsonl, error bundle, evaluation report, generated outputs
```

## 7. GCS 구조 생성 순서
GCS 콘솔에서 마우스로 폴더를 만들어도 동작은 합니다. 
★★하지만 팀 온보딩과 재현성을 위해 `gcloud storage` 명령어를 표준으로 사용합니다.

먼저 인증과 버킷 접근을 확인합니다.

```bash
# [Design Intent] 현재 GCP 계정과 프로젝트가 올바른지 확인한다.
gcloud auth list
gcloud config list
gcloud storage ls gs://ssakda
```

GCS 구조는 스크립트로 생성합니다. 기본 실행은 dry-run입니다. 
실제 버킷에 쓰려면 `--apply`를 붙입니다.

```bash
# [Design Intent] 공유 버킷을 바꾸기 전에 생성될 prefix를 먼저 검토한다.
cd ~/final_1_team
./scripts/setup_gcs_layout.sh
```

```bash
# [Design Intent] 검토한 GCS prefix를 .keep object로 생성한다.
cd ~/final_1_team
./scripts/setup_gcs_layout.sh --apply
```

생성 결과를 확인합니다.

```bash
# [Design Intent] BrandMate 프로젝트 prefix가 의도대로 생성됐는지 확인한다.
gcloud storage ls --recursive gs://ssakda/projects/brandmate/
gcloud storage ls gs://ssakda/dvc/brandmate/
```

## 8. 데이터 등록 기준

업로드 대상별 역할을 먼저 구분합니다. 이 기준을 어기면 Git, GCS, DVC가 같은 일을 중복해서 하게 되고 나중에 팀원이 복구 절차를 이해하지 못합니다.

| 항목 | Git | GCS readable path | DVC remote | 기준 |
| --- | --- | --- | --- | --- |
| 실제 데이터 파일 | X | O | O | 이미지, CSV, Parquet, embedding, FAISS index 같은 대용량 산출물입니다. Git에 올리지 않습니다. |
| DVC pointer 파일 | O | X | X | `data/.../{artifact_name}.dvc` 파일입니다. Git commit과 DVC object를 연결합니다. |
| DVC 내부 object | X | X | O | `gs://ssakda/dvc/brandmate/` 아래에 DVC가 해시 기반으로 저장합니다. 사람이 직접 수정하지 않습니다. |
| canonical manifest/description | O | O | X | Git의 `docs/datasets/`가 공식 원본입니다. GCS `data/manifests/`에는 중앙 조회용 복사본을 둡니다. DVC 추적 대상은 아닙니다. |
| package docs | DVC pointer로만 추적 | O | O | artifact 내부 `docs/manifest.json`, `docs/description.md`입니다. 데이터 패키지 일부라 GCS readable path와 DVC remote에 같이 들어갑니다. |
| 생성 스크립트/노트북 | O | X | X | 재현 코드는 Git에서 리뷰하고 버전관리합니다. |

짧게 정리하면 아래 정책입니다.

```text
Git = 코드, 공식 문서, DVC pointer
GCS readable path = 사람이 직접 찾아볼 데이터 패키지
DVC remote = Git commit에 연결되는 데이터 버전 저장소
```

Manifest/description은 두 종류로 나눕니다.

```text
canonical docs:
  Git에서 리뷰하는 공식 문서입니다.
  docs/datasets/{dataset_name}_{version}_manifest.json
  docs/datasets/{dataset_name}_{version}_description.md

package docs:
  GCS/DVC 데이터 패키지 안에 같이 들어가는 사본입니다.
  data/{stage}/{dataset_name}/{version}/{artifact_name}/docs/manifest.json
  data/{stage}/{dataset_name}/{version}/{artifact_name}/docs/description.md
```

팀원이 본인 로컬에서 새 데이터셋을 등록할 때는 아래 순서대로 진행합니다. 실제 업로드 명령은 GCS 인증, manifest 작성, DVC 설정이 끝난 뒤 실행합니다.

1. 데이터셋 폴더를 `data/{stage}/{dataset_name}/v1/{artifact_name}/` 구조로 맞춥니다.
2. Git 공식 문서인 `docs/datasets/{dataset_name}_v1_manifest.json`, `docs/datasets/{dataset_name}_v1_description.md`를 작성합니다.
3. 데이터 패키지 내부에 `docs/manifest.json`, `docs/description.md` 사본을 넣습니다.
4. DVC가 처음이면 `dvc init`, `dvc remote add`를 먼저 설정합니다.
5. GCS readable path에 실제 데이터 패키지를 `gcloud storage rsync`로 업로드합니다.
6. `dvc add data/{stage}/{dataset_name}/v1/{artifact_name}`로 데이터 패키지를 추적합니다.
7. `dvc push`로 DVC remote인 `gs://ssakda/dvc/brandmate/`에 데이터 버전을 업로드합니다.
8. Git에는 `.dvc`, `.dvcignore`, `.gitignore`, `.dvc` pointer, 공식 manifest/description, 생성 스크립트만 추가합니다.
9. `git status --short`에서 실제 대용량 데이터 파일이 Git에 잡히지 않는지 확인합니다.

`{stage}`에는 `curated`, `processed`, `eval` 중 하나를 넣습니다. `processed` 데이터셋은
`{dataset_name}/v1/{artifact_name}` 구조를 사용합니다. 새로운 dataset이나 artifact가 필요하면
임의로 폴더를 만들지 말고 먼저 팀 내에서 이름을 합의합니다.

## 9. 주기 데이터 인입과 Airflow 연동 기준

Airflow 세부 구축 계획은 [AIRFLOW_ONBOARDING.md](./AIRFLOW_ONBOARDING.md)를 따릅니다.

Airflow는 사용자 트래픽 처리를 위한 도구가 아닙니다. 동시 접속자 수가 아니라 데이터 수집 주기, task 의존성,
실패 재처리 필요성으로 도입 여부를 판단합니다. 단순한 1회성 데이터셋이면 `cron` 또는 수동 배치로도 충분하지만,
BrandMate의 초기 Airflow MVP는 팀원이 업로드한 주간 processed 후보 CSV를 자동 검수하는 구조로 시작합니다.
DVC 등록과 공식 processed 데이터셋 승격은 기존 데이터셋 관리 절차를 따르며, Airflow가 직접 `dvc add`,
`dvc push`, `git commit`을 실행하지 않습니다.

GCS 관점의 핵심 원칙은 아래와 같습니다.

- 팀원이 올리는 주간 processed 후보 CSV는 `data/landing/processed/sns_meme_trend/week=YYYY-Www/`에 둡니다.
- Airflow 초기 MVP는 landing CSV의 존재 여부, schema, 기본 품질만 검증합니다.
- validation 결과와 Airflow error bundle은 `logs/data_pipeline/airflow/`에 저장합니다.
- 공식 데이터셋으로 승인된 산출물만 `data/processed/{dataset_name}/v1/{artifact_name}/`에 저장하고 DVC로 추적합니다.
- Airflow metadata DB에는 task 상태와 run metadata만 남기고, CSV 원본이나 validation result 전문은 저장하지 않습니다.
- `landing`, `processed`, DVC remote를 같은 prefix에 섞지 않습니다.

| Layer | 역할 | BrandMate 기준 |
| --- | --- | --- |
| Input Storage | 주간 processed 후보 CSV landing | `data/landing/processed/sns_meme_trend/week=YYYY-Www/` |
| Validation | 파일 존재, schema, 품질 검증 | Airflow가 validation task 실행 |
| Validation Output | 검증 요약과 실패 로그 | `logs/data_pipeline/airflow/dag_id=.../week=YYYY-Www/` |
| Official Dataset | 승인된 processed artifact 저장 | `data/processed/{dataset_name}/v1/{artifact_name}/` |
| Consumption | DS 분석, 학습, 평가 | GCS processed prefix 또는 DVC pull |

Feast는 지금 단계에서 필수로 넣지 않습니다. 온라인 feature serving이 필요한 단계가 아니면 인프라만 무거워집니다.
현재는 GCS의 Parquet dataset을 offline feature store처럼 쓰고, 필요해지는 시점에 Feast 또는 BigQuery 기반
feature store로 승격하는 게 맞습니다.

## 10. Manifest 작성

Manifest와 description 작성 기준은 [DATASET_SUBMISSION_ONBOARDING.md](./DATASET_SUBMISSION_ONBOARDING.md)를 따릅니다.

현재 AIHub 음식 이미지/텍스트 5GB processed artifact 기준 파일은 아래와 같습니다.

```text
docs/datasets/aihub_food_image_text_v1_manifest.json
docs/datasets/aihub_food_image_text_v1_description.md
```

GCS에는 manifest를 `data/manifests/`에 올리고, 사람이 GCS 콘솔에서 바로 이해할 수 있도록
artifact prefix의 `docs/` 아래에도 `manifest.json`, `description.md` 복사본을 둡니다.

```text
Git canonical:
docs/datasets/aihub_food_image_text_v1_manifest.json
docs/datasets/aihub_food_image_text_v1_description.md

GCS package copy:
gs://ssakda/projects/brandmate/data/processed/aihub_food_image_text/v1/food_description_data/docs/manifest.json
gs://ssakda/projects/brandmate/data/processed/aihub_food_image_text/v1/food_description_data/docs/description.md
```

Manifest 업로드:

```bash
# [Design Intent] 데이터셋 manifest를 GCS의 중앙 manifest 경로에 저장한다.
gcloud storage cp \
  docs/datasets/aihub_food_image_text_v1_manifest.json \
  gs://ssakda/projects/brandmate/data/manifests/aihub_food_image_text_v1.json
```

Description 업로드:

```bash
# [Design Intent] GCS artifact prefix 안에서도 사람이 데이터셋 설명을 바로 확인할 수 있게 한다.
gcloud storage cp \
  docs/datasets/aihub_food_image_text_v1_description.md \
  gs://ssakda/projects/brandmate/data/processed/aihub_food_image_text/v1/food_description_data/docs/description.md
```

Artifact package 내부 `docs/manifest.json`도 함께 맞춥니다.

```bash
# [Design Intent] 데이터 패키지 내부에서도 manifest와 description을 같은 이름으로 제공한다.
gcloud storage cp \
  docs/datasets/aihub_food_image_text_v1_manifest.json \
  gs://ssakda/projects/brandmate/data/processed/aihub_food_image_text/v1/food_description_data/docs/manifest.json
```

로컬 데이터 패키지 안에도 같은 구조를 유지합니다.

```text
data/processed/aihub_food_image_text/v1/food_description_data/docs/
  manifest.json
  description.md
```

## 11. DVC 설정

DVC는 Git commit과 데이터 버전을 연결하기 위한 포인터입니다. `gs://ssakda/dvc/brandmate/`는 DVC 내부 object store이므로 사람이 직접 파일을 정리하지 않습니다.

```bash
# [Design Intent] Git commit과 데이터 버전을 강하게 결합하기 위해 DVC remote를 GCS로 둔다.
cd ~/personal/final_1_team
dvc init
dvc config core.site_cache_dir .dvc/site-cache
dvc remote add -d gcsremote gs://ssakda/dvc/brandmate
git add .dvc .dvcignore
git commit -m "Initialize DVC for BrandMate"
```

WSL 또는 제한된 실행 환경에서 DVC가 `/var/tmp/dvc`에 쓰려고 하며 실패할 수 있습니다. 이 경우 `core.site_cache_dir`를 프로젝트 내부 `.dvc/site-cache`로 고정합니다.

DVC의 GCS backend는 `gcloud storage` 로그인과 별개로 Application Default Credentials를 사용합니다. `dvc push`에서 `Your default credentials were not found`가 나오면 아래 명령으로 ADC를 한 번 설정합니다.

```bash
# [Design Intent] DVC/GCSFS가 GCS bucket에 인증된 사용자로 접근할 수 있게 한다.
gcloud auth application-default login --no-launch-browser
```

GCS readable path에 사람이 직접 확인할 수 있는 데이터 패키지를 먼저 올립니다. 이 경로는 DVC remote와 다릅니다.

```bash
# [Design Intent] GCS 콘솔이나 VM에서 사람이 직접 찾을 수 있는 경로에도 데이터 패키지를 배치한다.
cd ~/personal/final_1_team

gcloud storage rsync \
  data/processed/aihub_food_image_text/v1/food_description_data \
  gs://ssakda/projects/brandmate/data/processed/aihub_food_image_text/v1/food_description_data \
  --recursive
```

그 다음 같은 데이터 패키지를 DVC로 추적합니다.

```bash
# [Design Intent] Git에는 실제 데이터가 아니라 DVC pointer만 저장한다.
dvc add data/processed/aihub_food_image_text/v1/food_description_data
dvc push
git add data/processed/aihub_food_image_text/v1/food_description_data.dvc .gitignore .dvc .dvcignore
git add docs/datasets/aihub_food_image_text_v1_manifest.json
git add docs/datasets/aihub_food_image_text_v1_description.md
git commit -m "Track AIHub food image text v1 processed artifact"
```

업로드 후 확인합니다.

```bash
# [Design Intent] readable GCS path와 DVC 상태가 모두 정상인지 검증한다.
gcloud storage du -s \
  gs://ssakda/projects/brandmate/data/processed/aihub_food_image_text/v1/food_description_data

gcloud storage ls \
  gs://ssakda/projects/brandmate/data/processed/aihub_food_image_text/v1/food_description_data/docs/

dvc status
```

팀원이 받을 때:

```bash
git pull
dvc pull
```

## 12. VM으로 데이터 내려받기

GPU VM 디스크는 100GB 이하이므로 전체 데이터를 계속 로컬에 쌓지 않습니다. 필요한 dataset과 artifact만 내려받습니다.

```bash
# [Design Intent] VM에는 실행에 필요한 AIHub food image text processed artifact만 캐시한다.
mkdir -p ~/data/brandmate/processed/aihub_food_image_text/v1/food_description_data
gcloud storage rsync \
  gs://ssakda/projects/brandmate/data/processed/aihub_food_image_text/v1/food_description_data \
  ~/data/brandmate/processed/aihub_food_image_text/v1/food_description_data \
  --recursive
```

```bash
# [Design Intent] 평가 smoke set만 내려받아 배포 직후 빠르게 검증한다.
mkdir -p ~/data/brandmate/eval/smoke
gcloud storage rsync \
  gs://ssakda/projects/brandmate/data/eval/smoke \
  ~/data/brandmate/eval/smoke \
  --recursive
```

용량 확인:

```bash
du -sh ~/data/brandmate
df -h
```

## 13. 결과 업로드

평가 결과는 로컬 구조를 그대로 GCS에 올립니다.

비전 모델 평가는 현재 CLIP Score, Aesthetic Score, Diversity 같은 무거운 자동 품질 지표를
기본 산출물로 보지 않습니다. 로컬 12GB VRAM 환경에서는 이미지 생성 모델과 평가용 vision
encoder가 같은 자원을 두고 경쟁해 OOM과 latency 증가를 만들기 쉽습니다. 기본 업로드 대상은
`report.json`, `report.md`, 모델별 생성 이미지, Image Generation Success Rate, Failure Rate,
Image Latency, Pipeline Latency, Throughput, Client Queue Wait입니다. CLIP/Aesthetic/Diversity는
24GB 이상 GPU 또는 별도 offline batch 평가에서 생성한 경우에만 선택 산출물로 함께 올립니다.

```bash
# [Design Intent] 로컬 평가 run 구조를 GCS에서도 동일하게 유지한다.
gcloud storage rsync \
  ~/final_1_team/outputs/evaluations \
  gs://ssakda/projects/brandmate/outputs/evaluations \
  --recursive
```

웹서비스 최종 생성 결과는 `outputs/web_service_generated/`에 request 단위로 저장합니다.

```text
gs://ssakda/projects/brandmate/outputs/web_service_generated/YYYYMMDD/request_id/
  final_image.png
  payload.json
  response.json
  metadata.json
```

## 14. 운영 규칙

- GCS 폴더명에는 `10gb` 같은 용량 정보를 넣지 않습니다. 용량은 manifest에 기록합니다.
- dataset이 다르면 `curated/{dataset_name}/v1` 또는 `processed/{dataset_name}/v1/{artifact_name}`처럼 반드시 분리합니다.
- `processed/merged/v1`은 schema와 merge rule이 합의된 통합 데이터셋만 둡니다.
- `processed/merged/v1`을 만들 때는 반드시 `data/manifests/processed_merged_v1.json`을 함께 작성합니다.
- 평가 결과와 웹서비스 생성 결과를 섞지 않습니다.
- DVC remote인 `gs://ssakda/dvc/brandmate/`는 직접 수정하지 않습니다.
- 로그에는 API key, 개인정보, 원본 민감 정보를 남기지 않습니다.
- 성공은 summary JSONL, 실패는 errors 폴더에 상세 로그를 남깁니다.
