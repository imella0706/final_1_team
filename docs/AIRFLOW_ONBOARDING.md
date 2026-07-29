# BrandMate Airflow Onboarding

이 문서는 BrandMate의 `sns_trend` processed 데이터 검증 파이프라인을 Airflow로 운영하기 위한 기준입니다.

Airflow는 크롤러도 아니고 데이터 생성기도 아닙니다. 현재 MVP에서 Airflow의 역할은 데이터셋 담당자가 GCS에 올린 공식 processed 패키지를 read-only로 검증하고, API/DVC에서 사용 가능한 상태인지 판단하는 gate입니다.

## 1. Quick Start & 로그인 가이드

Airflow 인프라 초기화 시 `.env.airflow` 파일에 24자리 무작위 보안 비밀번호가 자동 생성됩니다.

```bash
# Airflow 관리자 로그인 정보 조회 (아이디/비밀번호 확인)
grep -E "AIRFLOW_ADMIN_USERNAME|AIRFLOW_ADMIN_PASSWORD" .env.airflow
```

- **기본 아이디 (Username):** `admin`
- **비밀번호 (Password):** 위 `grep` 명령으로 조회되는 `AIRFLOW_ADMIN_PASSWORD` 값 복사
- **Web UI 접속:** `http://<GCP_VM_외부_IP>:8080` (또는 SSH 터널링 시 `http://127.0.0.1:8080`)

## 2. 결론

```text
# [Design Intent] Airflow가 데이터를 만들지 않게 해서 curated 검수 책임과 processed 소비 책임을 분리한다.
dataset manager
  -> upload processed JSON/CSV to GCS
  -> Airflow validates processed package
  -> Airflow writes checksum and validation summary
  -> FastAPI loader smoke test
  -> DVC tracks processed package only
```

초기 MVP에서는 `curated -> processed` 자동화와 source별 crawler task를 Airflow에 넣지 않습니다.

## 2. 적용 범위

적용 대상:

- `data/processed/sns_trend/vN/cross_platform_signal_top_candidates/` 경로의 공식 processed 패키지 검증
- `cross_platform_signal_top_candidates.json`과 `cross_platform_signal_top_candidates.csv` 일관성 검증
- `schema_version`, `meme_id`, `curation_meta.status`, `trend_meta.status` 검증
- checksum report 생성
- FastAPI TrendCard loader smoke test
- DVC가 `landing`/`curated`가 아니라 `processed`만 추적하는지 확인
- Airflow 실행 결과를 `logs/data_pipeline/airflow/`에 저장

적용하지 않는 대상:

- Airflow가 밈 카드 내용을 자동 승인하는 기능
- Airflow가 curated에서 processed를 자동 생성하는 기능
- Airflow가 processed package를 GCS에 publish하는 기능
- 초기 MVP에서 YouTube, 고구마팜, 캐릿, 네이버 크롤러 실행
- Airflow metadata DB에 원본 JSON/CSV 본문 저장
- FastAPI, Frontend, ComfyUI, LLM API serving

## 3. 공식 입력

현재 v2 공식 processed 패키지:

```text
# [Design Intent] API가 읽는 공식 입력은 JSON 하나로 고정하고 CSV는 검수용 index로만 사용한다.
data/processed/sns_trend/v2/cross_platform_signal_top_candidates/
  cross_platform_signal_top_candidates.json
  cross_platform_signal_top_candidates.csv
```

GCS 기준 경로:

```text
gs://ssakda/projects/brandmate/data/processed/sns_trend/v2/cross_platform_signal_top_candidates/
```

주의:

- `landing`과 `curated`는 공식 pipeline input이 아닙니다.
- DVC 관리 대상도 우선 `processed`만 둡니다.
- `docs/`는 GCS data package 안에 올리지 않고 `docs/datasets/sns_trend/vN/`에만 둡니다.
- `v2`는 덮어쓰지 않습니다. 다음 공식 패키지는 `v3`, `v4`처럼 새 version으로 발행합니다.

## 4. 검증 기준

`sns_trend` processed validation은 아래 조건을 통과해야 합니다.

- JSON payload가 parse 가능해야 함
- JSON payload에 `cards` list가 있어야 함
- `card_count == len(cards)`
- CSV row count가 JSON card count와 같아야 함
- 모든 카드의 `schema_version`이 동일해야 함
- 기본 기대값은 `schema_version=2.0`
- `meme_id`가 비어 있지 않고 unique해야 함
- 모든 카드의 `curation_meta.status=reviewed`
- 모든 카드의 `trend_meta.status=active`
- CSV의 `meme_id`, `source_family`, `schema_version`, `display_name`, `status`, `source_count`가 JSON과 일치해야 함
- FastAPI loader가 같은 payload를 읽을 수 있어야 함
- DVC가 `data/landing/sns_trend/` 또는 `data/curated/sns_trend/`를 추적하면 실패

warning으로 기록하는 항목:

- `is_mock=true` 카드 존재
- `trend_meta.collected_week` 혼합

현재 v2 baseline의 예상 warning:

```text
mock_cards: 20
mixed_collected_week:
  2026-W28: 1
  2026-W30: 19
```

## 5. 로컬 CLI

Airflow DAG를 만들기 전에 CLI로 검증 로직을 먼저 통과시킵니다.

```bash
# [Design Intent] DAG 밖에서 processed package 계약을 먼저 검증해 Airflow 디버깅 범위를 줄인다.
PYTHONPATH=airflow/include conda run -n ssakda python \
  airflow/include/sns_trend_processed_validation_cli.py \
  --api-loader-smoke \
  --dvc-check
```

성공 시 summary에는 최소 아래 값이 포함됩니다.

```text
status: passed
card_count: 20
csv.row_count: 20
schema_versions.2.0: 20
source_family_counts
collected_week_counts
checksums.json
checksums.csv
api_loader_smoke.status: passed
dvc.status
warnings
```

summary 파일로 저장하려면:

```bash
# [Design Intent] Airflow가 저장할 validation_summary.json과 같은 형태를 로컬에서도 확인한다.
PYTHONPATH=airflow/include conda run -n ssakda python \
  airflow/include/sns_trend_processed_validation_cli.py \
  --api-loader-smoke \
  --dvc-check \
  --summary-path airflow/mock_gcs/logs/data_pipeline/airflow/dag_id=sns_trend_processed_validation/run_id=local/validation_summary.json
```

## 6. 코드 구조

현재 Airflow 관련 파일:

```text
# [Design Intent] 검증 로직과 실행 진입점을 분리해 DAG, CLI, 테스트가 같은 코드를 재사용한다.
airflow/
  dags/
    sns_trend_processed_validation.py
  include/
    sns_trend/
      __init__.py
      storage.py
      validation.py
    sns_trend_processed_validation_cli.py
  tests/
    test_sns_trend_processed_validation_dag.py
    test_sns_trend_processed_validation.py
    test_sns_trend_storage.py
```

역할:

- `dags/sns_trend_processed_validation.py`: Airflow 수동 실행 DAG
- `sns_trend/storage.py`: GCS processed package sync와 validation summary upload adapter
- `sns_trend/validation.py`: 실제 processed package 검증 로직
- `sns_trend_processed_validation_cli.py`: CLI entrypoint
- `test_sns_trend_processed_validation.py`: JSON/CSV consistency와 DVC policy 테스트
- `test_sns_trend_processed_validation_dag.py`: DAG syntax와 Airflow DagBag import 테스트
- `test_sns_trend_storage.py`: GCS URI parsing, sync, summary upload adapter 테스트

삭제된 legacy POC:

- `airflow/dags/brandmate_weekly_meme_csv_validation.py`
- `airflow/include/brandmate_meme_validation.py`
- `airflow/include/run_meme_validation.py`
- `airflow/mock_gcs/data/landing/processed/sns_meme_trend/...`

위 파일들은 오래된 mock CSV 계약 기준이므로 공식 v2 processed pipeline에서는 사용하지 않습니다.

## 7. Airflow DAG 계획

다음 DAG 이름:

```text
sns_trend_processed_validation
```

Task graph:

```text
# [Design Intent] 공식 pipeline input인 processed package를 read-only로 검증하고 실패한 payload가 API/DVC gate를 통과하지 못하게 한다.
resolve_processed_package
  -> check_new_processed_release
  -> sync_processed_package_from_gcs
  -> validate_package
  -> write_validation_summary
  -> record_validated_version
```

manual trigger config:

```json
{
  "version": "v2",
  "processed_prefix": "data/processed/sns_trend/v2/cross_platform_signal_top_candidates/"
}
```

MVP에서는 schedule을 켜지 않습니다. 데이터셋 담당자가 새 processed package를 올린 뒤 수동 trigger합니다.

GCS에 업로드된 processed package를 검증할 때는 `source_gcs_prefix`를 넘깁니다. 이 경우 Airflow는 GCS object를 직접 스트리밍하지 않고, writable cache인 `/opt/airflow/gcs_data_cache`로 먼저 내려받은 뒤 기존 validator를 실행합니다.

로컬 Docker Airflow에서 GCS를 읽으려면 host의 ADC를 컨테이너에 read-only로 mount합니다. 처음 한 번 또는 `Reauthentication is needed`가 나오면 아래 명령으로 갱신합니다.

```bash
# [Design Intent] Airflow Python GCS client가 사용할 Application Default Credentials를 로컬에 준비한다.
gcloud auth application-default login
gcloud auth application-default print-access-token
```

```json
{
  "version": "v2",
  "source_gcs_prefix": "gs://ssakda/projects/brandmate/data/processed/sns_trend/v2/cross_platform_signal_top_candidates/",
  "write_gcs_summary": true,
  "force_revalidate": false,
  "same_version_policy": "skip"
}
```

`check_new_processed_release`는 latest discovery로 선택된 `vN`이 Airflow Variable에 저장된 마지막 성공 검증 version과 같은지 확인합니다. 기본 정책은 `skip`입니다. 새 release가 없으면 validator를 다시 돌리지 않고 downstream task가 skipped 됩니다.

같은 version을 의도적으로 다시 검증할 때는 manual trigger config에 아래 값을 넣습니다.

```json
{
  "force_revalidate": true
}
```

같은 version을 skip이 아니라 실패로 보고 싶으면 `same_version_policy`를 `fail`로 넘기거나 `.env.airflow`의 `BRANDMATE_SNS_TREND_SAME_VERSION_POLICY`를 `fail`로 바꿉니다. 현재 MVP 기본값은 알람 피로도를 줄이기 위해 `skip`입니다.

실패 알림은 기본 비활성화입니다. Discord webhook URL은 secret이므로 Git에 올리지 않습니다.

```bash
# [Design Intent] 로컬/VM에서 실패 알림을 켤 때만 private .env.airflow에 실제 webhook URL을 넣는다.
BRANDMATE_AIRFLOW_ALERTS_ENABLED=true
BRANDMATE_AIRFLOW_DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...
BRANDMATE_AIRFLOW_ALERT_TIMEOUT_SECONDS=5
```

알림 기준:

| 상태 | Discord 알림 |
| --- | --- |
| task `failed` | 전송 |
| same-version `skipped` | 전송 안 함 |
| local 개발에서 webhook 미설정 | 조용히 skip |

알림 payload에는 `dag_id`, `task_id`, `run_id`, `version`, `source_gcs_prefix`, `exception`, `log_url`을 포함합니다. Discord 전송 실패는 원래 Airflow task 실패를 덮어쓰지 않습니다.

같은 검증을 CLI로 실행할 때는 아래 스크립트를 사용합니다. 로컬과 VM smoke test에서 같은 진입점을 쓰기 위한 명령입니다.

```bash
# [Design Intent] Airflow UI JSON 입력 실수를 줄이고 local/VM smoke test 절차를 같은 명령으로 고정한다.
./scripts/airflow/trigger_sns_trend_gcs_validation.sh
```

다른 GCS prefix나 버전을 검증할 때만 환경변수로 override합니다.

```bash
AIRFLOW_SNS_TREND_VERSION=v3 \
AIRFLOW_SNS_TREND_GCS_PREFIX=gs://ssakda/projects/brandmate/data/processed/sns_trend/v3/cross_platform_signal_top_candidates/ \
./scripts/airflow/trigger_sns_trend_gcs_validation.sh
```

Phase 3 latest discovery 경로를 검증할 때는 `source_gcs_prefix`를 직접 넘기면 안 됩니다. 같은 스크립트에서 `AIRFLOW_SNS_TREND_SELECTION_MODE=latest`를 주면 `source_gcs_prefix`와 `version`을 빼고 trigger해서, DAG가 `BRANDMATE_SNS_TREND_PROCESSED_GCS_ROOT` 아래에서 최신 `vN`을 직접 찾게 합니다.

```bash
# [Design Intent] source_gcs_prefix 없이 latest processed vN discovery 경로를 실제 Airflow DAG로 검증한다.
AIRFLOW_SNS_TREND_SELECTION_MODE=latest \
./scripts/airflow/trigger_sns_trend_gcs_validation.sh
```

기본값은 `force_revalidate=true`입니다. 이미 같은 version이 검증된 상태에서도 smoke test가 validator까지 지나가도록 하기 위한 설정입니다. same-version skip 정책 자체를 확인하고 싶을 때만 아래처럼 끕니다.

```bash
AIRFLOW_SNS_TREND_SELECTION_MODE=latest \
AIRFLOW_FORCE_REVALIDATE=false \
./scripts/airflow/trigger_sns_trend_gcs_validation.sh
```

`sync_processed_package_from_gcs`가 아래처럼 실패하면 GCS 인증 문제가 아니라 writable cache 권한 문제입니다.

```text
PermissionError: [Errno 13] Permission denied: '/opt/airflow/gcs_data_cache/...'
```

이 경우 직접 `chown`하지 말고 `./scripts/airflow/up.sh`를 다시 실행합니다. `up.sh`는 `airflow/gcs_data_cache`, `airflow/mock_gcs`, Airflow log mount를 현재 `AIRFLOW_UID` 기준으로 보정합니다.

로컬에서 GCS summary 업로드까지 아직 확인하지 않을 때는 아래처럼 끌 수 있습니다.

```json
{
  "version": "v2",
  "source_gcs_prefix": "gs://ssakda/projects/brandmate/data/processed/sns_trend/v2/cross_platform_signal_top_candidates/",
  "write_gcs_summary": false
}
```

### GCP VM smoke test

GCP VM에서 처음 실행할 때 Docker가 없으면 Airflow를 띄울 수 없습니다. VM을 운영 서버처럼 재현 가능하게 관리하기 위해 수동 `apt-get install` 대신 Docker setup 스크립트를 사용합니다.

```bash
# [Design Intent] VM에 Docker와 Docker Compose v2를 반복 가능한 방식으로 설치하고 Airflow smoke test 전제 조건을 맞춘다.
cd ~/final_1_team
./scripts/airflow/setup_gcp_vm_docker.sh
```

이 스크립트는 `sudo` 권한이 있는 계정에서만 실행할 수 있습니다. `sudo` 권한이 없으면 VM 관리자에게 먼저 권한을 요청합니다.

Ubuntu 이미지마다 Compose v2 패키지명이 다를 수 있습니다. 스크립트는 아래 순서로 설치를 시도합니다.

```text
docker-compose-plugin
-> docker-compose-v2
-> docker-compose
```

스크립트가 사용자를 `docker` group에 추가했다면 SSH/JupyterLab 세션을 끊고 다시 접속합니다. 바로 같은 터미널에서 이어가야 하면 임시로 아래를 실행합니다.

```bash
newgrp docker
```

재접속 또는 `newgrp docker` 후 확인합니다.

```bash
groups
docker --version
docker compose version
docker ps
```

그 다음 Airflow를 띄우고 GCS processed validation을 실행합니다.

```bash
cd ~/final_1_team
./scripts/airflow/up.sh
./scripts/airflow/trigger_sns_trend_gcs_validation.sh
```

VM에서는 로컬 ADC 대신 VM service account 권한으로 GCS에 접근하는 것이 기준입니다. service account에 processed prefix read/list와 logs prefix write 권한이 없으면 `sync_processed_package_from_gcs` 또는 `write_validation_summary`에서 실패합니다.

### YouTube landing collection DAG

Phase 4의 첫 DAG는 `sns_trend_youtube_landing_collection`입니다. 아직 GCS 업로드나
processed 승격을 하지 않습니다. 역할은 YouTube 원본 영상 목록을 landing run 폴더에
저장하고, 같은 raw CSV에서 `keyword,count` 파일을 만든 뒤
`curated/meme_card_candidates/youtube` 후보 JSON까지 생성하는 것입니다.

Airflow 컨테이너에서 실행하려면 private `.env.airflow`에 YouTube API key를 넣어야
합니다.

```bash
# [Design Intent] YouTube API key는 secret이므로 tracked example이 아니라 private env에만 둔다.
YOUTUBE_API_KEY=...
```

수동 실행 config 예시는 아래와 같습니다.

```json
{
  "week": "2026-W31",
  "run_date": "2026-07-27",
  "run_id": "manual__youtube_phase4_smoke",
  "limit": 5,
  "emit_curated_meme_card_candidates": true
}
```

생성되는 로컬 landing 산출물:

```text
data/landing/sns_trend/week=2026-W31/raw/youtube/run_id=manual__youtube_phase4_smoke/
  youtube_trending_KR_2026-W31.csv
  youtube_keywords_2026-07-27.csv
  crawler_run_summary.json

data/curated/sns_trend/v3/meme_card_candidates/youtube/
  youtube_meme_card_candidates_2026-W31.json
```

task 의미:

| Task | 역할 |
| --- | --- |
| `resolve_youtube_landing_context` | 이번 run의 `week`, `run_date`, `run_id`, landing 경로 결정 |
| `collect_youtube_trending_raw` | `youtube_trending_collector.py` 실행 후 raw video CSV와 `crawler_run_summary.json` 생성 |
| `build_youtube_keyword_snapshot` | raw CSV를 입력으로 `daily_keyword_tracker.py` 실행 후 `keyword,count` CSV와 curated 후보 JSON 생성 |
| `verify_youtube_landing_contract` | raw CSV, keyword CSV, summary, curated 후보 JSON 존재 여부와 schema 확인 |

`BRANDMATE_SNS_TREND_YOUTUBE_LANDING_SCHEDULE`은 기본값이 비어 있으므로 manual trigger
전용입니다. 매주 자동 실행은 YouTube/고구마팜/캐릿/네이버 CLI 계약을 모두 확인한 뒤
별도 단계에서 켭니다.

### Gogumafarm landing collection DAG

`sns_trend_gogumafarm_landing_collection`은 고구마팜 크롤러를 Airflow에서 실행해
landing 원본과 curated 후보 파일을 생성합니다. 아직 사람이 검수한 processed 패키지를
만들지는 않습니다.

수동 실행 config 예시는 아래와 같습니다.

```json
{
  "week": "2026-W31",
  "run_date": "2026-07-27",
  "run_id": "manual__gogumafarm_phase4_smoke",
  "emit_curated_meme_card_candidates": true
}
```

생성되는 로컬 산출물:

```text
data/landing/sns_trend/week=2026-W31/raw/gogumafarm/run_id=manual__gogumafarm_phase4_smoke/
  gogumafarm_memes_20260727.json
  gogumafarm_articles_20260727.csv
  gogumafarm_meme_terms_20260727.csv
  gogumafarm_meme_terms_20260727.json
  crawler_run_summary.json

data/curated/sns_trend/v3/meme_card_candidates/gogumafarm/
  gogumafarm_meme_card_candidates_2026-W31.json
```

task 의미:

| Task | 역할 |
| --- | --- |
| `resolve_gogumafarm_landing_context` | 이번 run의 `week`, `run_date`, `run_id`, landing/curated 경로 결정 |
| `collect_gogumafarm_landing` | `gogumafarm_crawler.py` 실행 후 landing 파일과 curated 후보 JSON 생성 |
| `verify_gogumafarm_landing_contract` | raw JSON, article CSV, term CSV/JSON, summary, curated 후보 파일 존재와 기본 계약 확인 |

`BRANDMATE_SNS_TREND_GOGUMAFARM_LANDING_SCHEDULE`은 기본값이 비어 있으므로 manual trigger
전용입니다. `BRANDMATE_SNS_TREND_GOGUMAFARM_CURATED_VERSION` 기본값은 `v3`입니다.

### Careet landing collection DAG

`sns_trend_careet_landing_collection`은 캐릿 크롤러를 Airflow에서 실행해 landing 원본
파일과 검수 전 curated 후보를 생성하고 산출물 계약을 확인합니다. 공식 processed
패키지는 만들지 않습니다.

수동 실행 config 예시는 아래와 같습니다.

```json
{
  "week": "2026-W31",
  "run_date": "2026-07-27",
  "run_id": "manual__careet_phase4_smoke",
  "end_page": 1,
  "curated_version": "v3",
  "emit_curated_meme_card_candidates": true
}
```

생성되는 로컬 산출물:

```text
data/landing/sns_trend/week=2026-W31/raw/careet/run_id=manual__careet_phase4_smoke/
  careet_articles_20260727.csv
  careet_memes_20260727.csv
  careet_meme_terms_20260727.json
  careet_meme_term_suspects_20260727.csv
  crawler_run_summary.json

data/curated/sns_trend/v3/meme_card_candidates/careet/
  careet_meme_card_candidates_2026-W31.json
```

task 의미:

| Task | 역할 |
| --- | --- |
| `resolve_careet_landing_context` | 이번 run의 `week`, `run_date`, `run_id`, landing/curated 경로 결정 |
| `collect_careet_landing` | `careet_crawler.py` 실행 후 landing CSV/JSON, summary, curated 후보 생성 |
| `verify_careet_landing_contract` | landing row count와 curated 후보의 stage, source, lineage, term count 계약 확인 |

`BRANDMATE_SNS_TREND_CAREET_LANDING_SCHEDULE`은 기본값이 비어 있으므로 manual trigger
전용입니다. `BRANDMATE_SNS_TREND_CAREET_CURATED_VERSION` 기본값은 `v3`입니다.
캐릿은 현재 공개 페이지 기반 수집이라 별도 API key가 필요 없습니다.

## 8. Airflow Metadata DB 정책

Airflow metadata DB에는 실행 상태만 저장합니다.

저장 가능:

- DAG run 상태
- task instance 상태
- retry 횟수
- 작은 XCom 값
- path
- card count
- checksum
- validation status

저장 금지:

- JSON payload 전체
- CSV 본문 전체
- pandas DataFrame
- 긴 prompt 전문
- LLM response 전문
- 이미지 base64
- secret

## 9. Docker Compose

현재 Airflow는 custom image와 Docker Compose로 구동합니다.

```text
# [Design Intent] Airflow 실행 상태와 스케줄링 컴포넌트만 컨테이너로 묶고 서비스 런타임과 분리한다.
Dockerfile.airflow
requirements.airflow.txt
docker-compose.airflow.yml
  airflow-postgres
  airflow-init
  airflow-webserver
  airflow-scheduler
```

custom image `brandmate-airflow:2.10.5-python3.11`은
`apache/airflow:2.10.5-python3.11`을 base로 사용합니다. 로컬 `ssakda`
conda env의 Python `3.12`와 다르므로 Airflow 안에서 실행될 코드는 Python
3.11에서도 동작해야 합니다.

L2 로컬 실행 기준:

- webserver, scheduler, init은 `${AIRFLOW_UID}:0`으로 실행하며 UID 0을 사용하지 않음
- `.env.airflow`은 Git ignore 대상이며 Fernet key, webserver secret, admin password를 보관
- `.env.airflow.example`에는 변수 계약만 기록
- `up.sh` 최초 실행 시 `.env.airflow`와 무작위 secret을 자동 생성
- `./data`, `./apps/api`, DAG, include 코드는 read-only mount
- `./airflow/gcs_data_cache`, `./airflow/mock_gcs`, Airflow log mount는 `up.sh`가 `${AIRFLOW_UID}:0` 소유로 보정
- Postgres host port는 노출하지 않음
- 컨테이너 시작 시 동적 pip install을 하지 않고 image build 단계에서 dependency를 고정
- Airflow system/UI timezone은 UTC 유지

표준 실행 명령:

```bash
# [Design Intent] 팀원이 compose 세부 명령과 init 순서를 외우지 않게 lifecycle을 단일 진입점으로 고정한다.
./scripts/airflow/up.sh
./scripts/airflow/status.sh
./scripts/airflow/logs.sh airflow-scheduler
./scripts/airflow/logs.sh airflow-webserver --follow
./scripts/airflow/down.sh
```

`down.sh`는 container와 Airflow compose network만 내리고 metadata DB와 log
volume은 보존합니다. 실행 이력을 지우는 `docker compose down -v`는 초기화를
명시적으로 결정한 경우가 아니면 사용하지 않습니다.

로그인 계정과 port는 로컬 `.env.airflow`에서 확인합니다. 해당 파일의
password, Fernet key, webserver secret은 문서, commit, terminal output에
붙여 넣지 않습니다.

프로젝트 root에서 다른 Compose 서비스도 실행 중이면 Airflow 실행 시
`orphan containers` 또는 `network resource is still in use` warning이 보일 수
있습니다. 현재 `final_1_team` Compose project를 공유해서 생기는 warning이며,
Airflow 장애가 아닙니다. 다른 backend DB까지 제거할 수 있으므로
`--remove-orphans`로 무작정 정리하지 않습니다.

## 10. 테스트

로컬 검증:

```bash
# [Design Intent] Airflow DAG 등록 전에 재사용 검증 로직을 ssakda 환경에서 검증한다.
PYTHONPATH=airflow/include conda run -n ssakda python -m pytest \
  airflow/tests/test_sns_trend_processed_validation.py \
  airflow/tests/test_sns_trend_processed_validation_dag.py
```

정적 검사:

```bash
# [Design Intent] Airflow 컨테이너에 올리기 전에 Python 3.11 호환 가능한 표준 코드 품질을 확인한다.
PYTHONPATH=airflow/include conda run -n ssakda python -m ruff check \
  airflow/dags/sns_trend_processed_validation.py \
  airflow/include/sns_trend/validation.py \
  airflow/include/sns_trend_processed_validation_cli.py \
  airflow/tests/test_sns_trend_processed_validation.py \
  airflow/tests/test_sns_trend_processed_validation_dag.py
```

컴파일 확인:

```bash
# [Design Intent] import-time syntax error를 DAG import 전에 잡는다.
conda run -n ssakda python -m compileall -q \
  airflow/dags/sns_trend_processed_validation.py \
  airflow/include/sns_trend \
  airflow/include/sns_trend_processed_validation_cli.py
```

## 11. 후순위 작업

우선순위:

1. GCS adapter/ADC 연결
2. 새 processed version 수동 run 절차 문서화
3. 알림 연결
4. metadata DB backup/runbook 정리
5. YouTube/고구마팜 crawler ingestion 검토
6. 캐릿/네이버 crawler ingestion 검토

크롤러 ingestion은 후속 단계입니다. 지금 MVP의 성공 기준은 processed package validation gate가 안정적으로 동작하는 것입니다.
