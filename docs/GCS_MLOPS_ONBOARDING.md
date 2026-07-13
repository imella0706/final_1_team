# BrandMate GCS / DVC Onboarding

이 문서는 BrandMate 데이터셋, 모델 비교 실험, 웹서비스 생성 결과, 로그를 GCS에 정리하는 기준입니다.

데이터셋을 새로 만들거나 GCS에 업로드하기 전에는 데이터셋 제출 규격을 먼저 확인합니다.

- [BrandMate Dataset Submission Onboarding](./DATASET_SUBMISSION_ONBOARDING.md)

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
| `data/curated/aihub_food_image_text/v1/` | AIHub `비전영역 음식이미지 및 정보소개 텍스트 데이터` 원본에서 BrandMate에 쓸 샘플만 선별한 데이터 풀입니다. 학습/전처리/평가셋 후보를 뽑는 문제은행 역할입니다. |
| `data/curated/sns/v1/` | SNS source에서 수집 후 BrandMate 목적에 맞게 정제한 데이터 풀입니다. AIHub와 섞지 않고 source를 분리해 추적합니다. |
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

## 9. Manifest 작성

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

## 10. DVC 설정

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

## 11. VM으로 데이터 내려받기

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

## 12. 결과 업로드

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

## 13. 운영 규칙

- GCS 폴더명에는 `10gb` 같은 용량 정보를 넣지 않습니다. 용량은 manifest에 기록합니다.
- dataset이 다르면 `curated/{dataset_name}/v1` 또는 `processed/{dataset_name}/v1/{artifact_name}`처럼 반드시 분리합니다.
- `processed/merged/v1`은 schema와 merge rule이 합의된 통합 데이터셋만 둡니다.
- `processed/merged/v1`을 만들 때는 반드시 `data/manifests/processed_merged_v1.json`을 함께 작성합니다.
- 평가 결과와 웹서비스 생성 결과를 섞지 않습니다.
- DVC remote인 `gs://ssakda/dvc/brandmate/`는 직접 수정하지 않습니다.
- 로그에는 API key, 개인정보, 원본 민감 정보를 남기지 않습니다.
- 성공은 summary JSONL, 실패는 errors 폴더에 상세 로그를 남깁니다.
