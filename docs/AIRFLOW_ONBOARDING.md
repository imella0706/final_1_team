# BrandMate Airflow Onboarding

이 문서는 BrandMate의 `sns_trend` processed 데이터 검증 파이프라인을 Airflow로 운영하기 위한 기준입니다.

Airflow는 크롤러도 아니고 데이터 생성기도 아닙니다. 현재 MVP에서 Airflow의 역할은 데이터셋 담당자가 GCS에 올린 공식 processed 패키지를 read-only로 검증하고, API/DVC에서 사용 가능한 상태인지 판단하는 gate입니다.

## 1. 현재 결론

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
      validation.py
    sns_trend_processed_validation_cli.py
  tests/
    test_sns_trend_processed_validation_dag.py
    test_sns_trend_processed_validation.py
```

역할:

- `dags/sns_trend_processed_validation.py`: Airflow 수동 실행 DAG
- `sns_trend/validation.py`: 실제 processed package 검증 로직
- `sns_trend_processed_validation_cli.py`: CLI entrypoint
- `test_sns_trend_processed_validation.py`: JSON/CSV consistency와 DVC policy 테스트
- `test_sns_trend_processed_validation_dag.py`: DAG syntax와 Airflow DagBag import 테스트

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
  -> validate_package
  -> write_validation_summary
```

manual trigger config:

```json
{
  "version": "v2",
  "processed_prefix": "data/processed/sns_trend/v2/cross_platform_signal_top_candidates/"
}
```

MVP에서는 schedule을 켜지 않습니다. 데이터셋 담당자가 새 processed package를 올린 뒤 수동 trigger합니다.

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

현재 Airflow는 Docker Compose로만 구동합니다.

```text
# [Design Intent] Airflow 실행 상태와 스케줄링 컴포넌트만 컨테이너로 묶고 서비스 런타임과 분리한다.
docker-compose.airflow.yml
  airflow-postgres
  airflow-init
  airflow-webserver
  airflow-scheduler
```

현재 이미지는 `apache/airflow:2.10.5-python3.11`입니다. 로컬 `ssakda` conda env의 Python `3.12`와 다릅니다. Airflow 안에서 실행될 코드는 Python 3.11 기준으로도 동작해야 합니다.

현재 compose는 POC 성격이 남아 있습니다.

- `user: "0:0"`은 로컬 POC 임시값
- Fernet key가 비어 있음
- admin credential이 compose에 하드코딩
- `./data`와 `./apps/api`를 read-only로 마운트해 processed package와 FastAPI loader smoke test를 확인함
- Airflow 컨테이너 시작 시 동적 pip install은 하지 않음
- DB port 노출 정책은 운영 전 점검 필요

L2 MVP 전환 시 고쳐야 합니다.

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

1. `sns_trend_processed_validation` DAG 추가
2. validation summary를 mock logs prefix에 저장
3. Airflow DagBag import test 추가
4. GCS adapter/ADC 연결
5. `.env.airflow.example`과 non-root compose 정리
6. 새 processed version 수동 run 절차 문서화
7. 알림 연결
8. YouTube/고구마팜 crawler ingestion 검토
9. 캐릿/네이버 crawler ingestion 검토

크롤러 ingestion은 후속 단계입니다. 지금 MVP의 성공 기준은 processed package validation gate가 안정적으로 동작하는 것입니다.
