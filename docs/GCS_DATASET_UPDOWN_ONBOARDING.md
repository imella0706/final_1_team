# BrandMate GCS Dataset Up/Down Onboarding

이 문서는 팀원이 이미 GCS에 올라간 데이터를 내려받거나, 담당 데이터셋을 GCS에 업로드할 때 사용하는 최소 명령만 정리합니다.
MLOps/인프라 담당자의 GCS prefix bootstrap, IAM, DVC remote 운영 기준은 [GCS_MLOPS_ONBOARDING.md](./GCS_MLOPS_ONBOARDING.md)를 봅니다.

## 1. 사전 확인

```bash
# [Design Intent] 현재 GCP 계정과 ssakda bucket 접근 권한을 먼저 확인한다.
gcloud auth list
gcloud config list
gcloud storage ls gs://ssakda
```

`scripts/setup_gcs_layout.sh`는 MLOps/인프라 담당자가 초기 GCS 폴더 구조를 세팅할 때 사용하는 bootstrap 스크립트입니다.
일반 팀원은 이 파일을 실행할 필요가 없습니다.

삭제 동기화는 사용하지 않습니다.

```text
--delete-unmatched-destination-objects 사용 금지
```

이 옵션은 로컬에 없는 GCS object를 삭제합니다. 기존 GCS 상태가 확실하지 않은 상태에서는 팀원이 올려둔 파일까지 지울 수 있습니다.

## 2. sns_trend v2

`sns_trend v2`는 `landing`, `curated`, `processed` 3개 stage를 함께 관리합니다.
GCS 데이터 패키지 내부에는 `docs/`를 만들지 않고, canonical 문서는 `docs/datasets/sns_trend/v2/`에만 둡니다.

### 다운로드

```bash
# [Design Intent] GCS readable path의 sns_trend 데이터를 로컬 표준 data/ 구조로 내려받는다.
cd /home/imella0707/personal/final_1_team

gcloud storage rsync \
  gs://ssakda/projects/brandmate/data/curated/sns_trend \
  data/curated/sns_trend \
  --recursive

gcloud storage rsync \
  gs://ssakda/projects/brandmate/data/landing/sns_trend \
  data/landing/sns_trend \
  --recursive

gcloud storage rsync \
  gs://ssakda/projects/brandmate/data/processed/sns_trend \
  data/processed/sns_trend \
  --recursive
```

### 업로드

먼저 dry-run으로 업로드될 파일을 확인합니다.

```bash
# [Design Intent] 공유 GCS prefix를 변경하기 전에 업로드 대상 차이를 먼저 확인한다.
cd /home/imella0707/personal/final_1_team

gcloud storage rsync \
  data/curated/sns_trend \
  gs://ssakda/projects/brandmate/data/curated/sns_trend \
  --recursive \
  --dry-run

gcloud storage rsync \
  data/landing/sns_trend \
  gs://ssakda/projects/brandmate/data/landing/sns_trend \
  --recursive \
  --dry-run

gcloud storage rsync \
  data/processed/sns_trend \
  gs://ssakda/projects/brandmate/data/processed/sns_trend \
  --recursive \
  --dry-run
```

dry-run 결과가 의도와 맞으면 `--dry-run`만 제거하고 실제 업로드합니다.

```bash
# [Design Intent] 로컬 표준 data/ 구조를 GCS readable path로 업로드한다.
cd /home/imella0707/personal/final_1_team

gcloud storage rsync \
  data/curated/sns_trend \
  gs://ssakda/projects/brandmate/data/curated/sns_trend \
  --recursive

gcloud storage rsync \
  data/landing/sns_trend \
  gs://ssakda/projects/brandmate/data/landing/sns_trend \
  --recursive

gcloud storage rsync \
  data/processed/sns_trend \
  gs://ssakda/projects/brandmate/data/processed/sns_trend \
  --recursive
```

업로드 후 확인합니다.

```bash
gcloud storage ls \
  gs://ssakda/projects/brandmate/data/processed/sns_trend/v2/cross_platform_signal_top_candidates/

gcloud storage ls \
  gs://ssakda/projects/brandmate/data/landing/sns_trend/week=2026-W30/raw/

gcloud storage ls \
  gs://ssakda/projects/brandmate/data/curated/sns_trend/v2/meme_cards_reviewed/
```

## 3. AIHub food image text

AIHub food image text는 공식 processed artifact만 다룹니다. 전체 AIHub raw 원본은 용량과 라이선스/비용 문제로 GCS에 올리지 않습니다.

### v2 다운로드

AIHub processed artifact는 이미지가 포함되어 크기가 큽니다. 다운로드 전 용량과 로컬 디스크를 확인합니다.

```bash
# [Design Intent] 대용량 이미지 artifact를 내려받기 전에 필요한 디스크 용량을 확인한다.
gcloud storage du -s \
  gs://ssakda/projects/brandmate/data/processed/aihub_food_image_text/v2/food_description_data

df -h .
```

```bash
# [Design Intent] GCS의 AIHub v2 processed artifact를 로컬 표준 processed 경로로 내려받는다.
cd /home/imella0707/personal/final_1_team

gcloud storage rsync \
  gs://ssakda/projects/brandmate/data/processed/aihub_food_image_text/v2/food_description_data \
  data/processed/aihub_food_image_text/v2/food_description_data \
  --recursive
```

### v1 업로드

```bash
# [Design Intent] AIHub food image text의 공식 processed artifact만 GCS readable path에 배치한다.
cd /home/imella0707/personal/final_1_team

gcloud storage rsync \
  data/processed/aihub_food_image_text/v1/food_description_data \
  gs://ssakda/projects/brandmate/data/processed/aihub_food_image_text/v1/food_description_data \
  --recursive \
  --dry-run
```

dry-run 결과가 의도와 맞으면 `--dry-run`만 제거합니다.

```bash
gcloud storage rsync \
  data/processed/aihub_food_image_text/v1/food_description_data \
  gs://ssakda/projects/brandmate/data/processed/aihub_food_image_text/v1/food_description_data \
  --recursive
```

업로드 후 확인합니다.

```bash
gcloud storage ls \
  gs://ssakda/projects/brandmate/data/processed/aihub_food_image_text/v1/food_description_data/
```

## 4. 제외

`food_101`은 현재 프로젝트 범위에서 제외했으므로 표준 GCS prefix와 업로드/다운로드 예시에 포함하지 않습니다.
