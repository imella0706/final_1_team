# BrandMate Airflow Onboarding

이 문서는 BrandMate의 트렌드/밈 문구 데이터 인입 파이프라인을 Airflow로 구축하기 위한 기준입니다.

Airflow는 크롤링 라이브러리도 아니고 전처리 엔진도 아닙니다. Airflow의 역할은 정해진 주기로 작업을
실행하고, task 의존성, 실패 재시도, backfill, 실행 로그를 통제하는 것입니다. 실제 크롤링은
`requests`, `BeautifulSoup`, `Selenium`, `Playwright`가 담당하고, MVP 전처리는 `pandas`가 담당합니다.

현재 실제 수집 코드는 `gather_data/` 아래에 있지만, Airflow 1차 MVP는 source별 데이터를 따로 관리하지
않습니다. 팀원이 여러 수집 채널을 취합하고 선별/정제한 뒤, 통합된 주간 밈 CSV 1개를 GCS landing에
업로드하는 구조를 기준으로 합니다.

| 영역 | 현재 역할 | Airflow 1차 적용 판단 |
| --- | --- | --- |
| 팀원 크롤링/정제 영역 | 여러 채널에서 후보 데이터를 수집하고 최신 트렌드 밈 CSV로 통합 | Airflow 밖에서 수행 |
| GCS landing | 팀원이 업로드하는 통합 주간 processed 후보 CSV | Airflow 자동 검수 대상 |
| Airflow | CSV 존재 여부, schema, 기본 품질 검증 | validation summary 저장 |
| 데이터셋 관리자 | 검증 결과 확인 후 공식 processed 데이터셋/DVC 등록 | Airflow 밖에서 수행 |

source별 crawler task 편입은 후순위입니다. 초기 MVP에서는 source별 Airflow DAG를 만들지 않습니다.

밈/트렌드는 시간이 지나면 데이터 가치가 떨어지므로 수동 실행이나 단발성 스크립트로 관리하면 운영 품질이
무너집니다. Airflow는 반복 수집, 산출물 검증, GCS 저장, 실패 추적을 자동화하기 위해 사용합니다.

## 1. 적용 범위

현재 BrandMate에서 Airflow를 적용할 대상은 데이터 인입 파이프라인입니다.

적용 대상:

```text
# [Design Intent] 초기에는 source별 수집이 아니라 통합 주간 CSV 자동 검수만 Airflow에 올린다.
- GCS landing의 통합 주간 밈 CSV 존재 여부 확인
- schema, row count, null 비율, 중복률, 날짜 범위, checksum 검증
- validation_summary.json, error.json 저장
```

적용하지 않는 대상:

```text
# [Design Intent] 사용자 요청을 처리하는 온라인 서비스와 오프라인 배치 오케스트레이션을 분리한다.
- FastAPI request serving
- Frontend serving
- ComfyUI image generation serving
- LLM API 실시간 호출 serving
- 사용자 세션 관리
- 모델 inference endpoint 운영
```

Airflow는 사용자 트래픽 처리를 위한 도구가 아닙니다. 동시 접속자 수가 아니라 데이터 수집 주기,
task 의존성, 실패 재처리, backfill 필요성으로 도입 여부를 판단합니다.

## 2. 현재 권장 아키텍처

현재 팀원이 크롤링, 선별, 기본 전처리를 수행해 주간 밈 CSV로 저장하므로, 첫 단계는 아래 구조가 맞습니다.

```text
# [Design Intent] DVC와 공식 데이터셋 등록은 분리하고, Airflow는 주간 CSV 자동 검수만 먼저 담당한다.
team crawler and curation
  -> weekly processed candidate CSV
  -> upload to GCS landing
  -> Airflow checks CSV exists
  -> Airflow validates schema and quality
  -> Airflow writes validation_summary.json
  -> dataset manager reviews and handles DVC registration
```

release candidate 패키징이나 크롤러 task 편입은 2단계 이후입니다.

```text
# [Design Intent] 자동 검수가 안정화된 뒤에만 데이터 패키징과 크롤러 실행을 Airflow로 확장한다.
future Airflow DAG
  -> check_weekly_csv_exists
  -> validate_csv_schema
  -> validate_csv_quality
  -> create_release_candidate
  -> write_manifest_draft
  -> optional crawler tasks after crawler hardening
```

처음부터 크롤러 전체를 Airflow에 넣지 않습니다. 먼저 주간 CSV 형식과 GCS landing 위치를 고정하고,
Airflow가 그 결과물을 안정적으로 검수하게 만듭니다.

## 3. Docker화 범위

Airflow만 Docker Compose로 구동합니다. 전체 서비스 Docker화는 이번 범위가 아닙니다.

Docker화 대상:

```text
# [Design Intent] Airflow 실행 상태와 스케줄링 컴포넌트만 컨테이너로 묶어 서비스 런타임과 분리한다.
- Airflow webserver
- Airflow scheduler
- Airflow metadata DB(Postgres)
```

Docker화하지 않는 대상:

```text
# [Design Intent] 데이터 배치 오케스트레이션과 사용자-facing 서비스 배포 범위를 섞지 않는다.
- FastAPI
- Frontend
- ComfyUI
- 모델 서버
```

Airflow metadata DB(Postgres)는 Airflow 내부 실행 상태를 저장하는 DB입니다. BrandMate 서비스 DB가 아닙니다.
CSV 원본, processed 데이터, validation 결과, 장애 상세 로그는 metadata DB에 넣지 않고 GCS에 저장합니다.

## 4. Airflow Metadata DB 정책

Airflow metadata DB에는 아래 값만 저장합니다.

- DAG run 상태
- task instance 상태
- retry 횟수
- schedule 정보
- 작은 XCom 값

XCom에는 작은 값만 저장합니다.

저장 가능:

```text
# [Design Intent] XCom은 데이터 전달 저장소가 아니라 task 간 작은 메타데이터 전달 용도로만 쓴다.
- gcs_raw_path
- gcs_processed_path
- row_count
- validation_status
- checksum
- run_id
```

저장 금지:

```text
# [Design Intent] Airflow metadata DB 비대화와 장애 복구 불가능한 상태 오염을 막는다.
- CSV 전체 내용
- pandas DataFrame
- 이미지 base64
- 긴 prompt 전문
- LLM raw response 전체
- validation result 전문
- error bundle 전문
```

Airflow metadata DB는 실행 상태 저장소입니다. 데이터 저장소가 아닙니다.

## 5. Weekly Meme CSV Contract

Airflow에 연결하기 전에 팀원이 생성하는 통합 주간 CSV 형식을 고정해야 합니다. 이 계약 없이
Airflow를 붙이면 자동화된 쓰레기 수거장이 됩니다. 스케줄러가 성실하게 잘못된 데이터를 GCS에 쌓는
구조가 됩니다.

파일명 규칙:

```text
# [Design Intent] 주차를 파일명에 박아 재처리와 장애 추적을 단순하게 만든다.
trend_meme_YYYY-Www.csv
trend_meme_2026-W29.csv
```

GCS landing path:

```text
# [Design Intent] 팀원이 올린 processed 후보 CSV를 공식 데이터셋 경로와 분리한다.
gs://ssakda/projects/brandmate/data/landing/processed/sns_meme_trend/week=YYYY-Www/trend_meme_YYYY-Www.csv
```

통합 CSV는 이미 선별/정제된 processed 후보입니다. Airflow는 변환보다 검증을 우선합니다.

필수 컬럼:

| 컬럼 | 의미 | 예시 |
| --- | --- | --- |
| `id` | row 고유 id. 없으면 URL 또는 text hash로 생성해서 넣음 | `meme_2026w29_0001` |
| `collected_at` | 크롤링 수집 시각 | `2026-07-15T07:00:00+09:00` |
| `published_at` | 원문 게시 시각. 없으면 null 허용 | `2026-07-14T22:10:00+09:00` |
| `keyword` | 수집 기준 키워드 또는 trend seed | `카페`, `여름 밈` |
| `trend_term` | 밈/트렌드 핵심어 | `두바이 초콜릿`, `요아정` |
| `text` | 수집된 제목/요약/문구/캡션 | `요즘 이 밈 모르면 대화가 안 됨` |
| `url` | 원문 URL | `https://...` |
| `engagement_count` | 조회수/좋아요/댓글/검색량 등 가능한 지표. 없으면 null | `1234` |

선택 컬럼:

| 컬럼 | 의미 |
| --- | --- |
| `author` | 작성자 또는 채널명 |
| `source` | 원출처가 필요할 때만 남기는 참고 메타데이터 |
| `hashtags` | 해시태그 문자열 또는 JSON string |
| `category` | 음식, 카페, 계절, 이벤트 등 내부 분류 |
| `language` | `ko`, `en` 등 |
| `rank` | source 내부 랭킹 |
| `quality_score` | 내부 품질 점수. 초기에는 null 허용 |
| `raw_payload_path` | 원본 HTML/JSON/screenshot을 별도 저장한 경우의 경로 |

CSV 기본 규칙:

```text
# [Design Intent] 팀원이 만든 통합 CSV가 downstream validation과 데이터셋 등록 기준을 만족하게 한다.
- encoding: utf-8
- delimiter: comma
- newline: LF
- duplicate key: id 또는 normalized url
- time zone: Asia/Seoul 기준 ISO-8601 권장
- 빈 문자열과 null 표기 방식은 pandas에서 일관되게 읽히도록 통일
```

## 6. 초기 MVP DAG 구조

초기 MVP에서는 DVC, 공식 processed 데이터셋 등록, Parquet 변환, manifest draft 생성을 Airflow에 넣지
않습니다. 팀원이 GCS landing에 올린 주간 processed 후보 CSV를 Airflow가 자동 검수하고,
검증 결과만 `logs/data_pipeline/airflow/`에 남깁니다.

```text
# [Design Intent] Airflow와 DVC 책임을 분리하고, 초기에는 주간 CSV 자동 검수만 검증한다.
brandmate_weekly_meme_csv_validation

check_weekly_csv_exists
  -> validate_csv_schema
  -> validate_csv_quality
  -> write_validation_summary
```

입력 위치:

```text
gs://ssakda/projects/brandmate/data/landing/processed/sns_meme_trend/week=YYYY-Www/trend_meme_YYYY-Www.csv
```

출력 위치:

```text
gs://ssakda/projects/brandmate/logs/data_pipeline/airflow/
  dag_id=brandmate_weekly_meme_csv_validation/
    week=YYYY-Www/
      validation_summary.json
      error.json
```

Python DAG skeleton:

```python
# [Design Intent] DAG skeleton은 단일 주간 CSV 검수, 단일 active run, 실패 재시도, 실행 timeout을 기본값으로 강제한다.
from __future__ import annotations

from datetime import timedelta

from airflow import DAG
from airflow.operators.python import PythonOperator
from pendulum import datetime


with DAG(
    dag_id="brandmate_weekly_meme_csv_validation",
    start_date=datetime(2026, 7, 15, tz="Asia/Seoul"),
    schedule="0 7 * * 1",
    catchup=False,
    max_active_runs=1,
    default_args={
        "retries": 2,
        "retry_delay": timedelta(minutes=10),
        "execution_timeout": timedelta(minutes=30),
    },
    tags=["brandmate", "trend", "meme", "validation"],
) as dag:
    check_weekly_csv_exists = PythonOperator(
        task_id="check_weekly_csv_exists",
        python_callable=check_weekly_csv_exists_on_gcs,
    )

    validate_csv_schema = PythonOperator(
        task_id="validate_csv_schema",
        python_callable=validate_weekly_meme_csv_schema,
    )

    validate_csv_quality = PythonOperator(
        task_id="validate_csv_quality",
        python_callable=validate_weekly_meme_csv_quality,
    )

    write_validation_summary = PythonOperator(
        task_id="write_validation_summary",
        python_callable=write_weekly_validation_summary,
    )

    check_weekly_csv_exists >> validate_csv_schema >> validate_csv_quality >> write_validation_summary
```

## 6.1 후속 확장 DAG 구조

초기 MVP가 안정화된 뒤에만 release candidate 패키징이나 crawler task 편입을 검토합니다.

```text
# [Design Intent] 자동 검수가 안정화된 뒤에만 후보 패키징과 크롤러 실행을 Airflow로 확장한다.
brandmate_trend_context_release_candidate

check_weekly_csv_exists
  -> validate_csv_schema
  -> validate_csv_quality
  -> create_release_candidate
  -> write_manifest_draft
  -> write_run_summary
```

크롤러를 DAG에 직접 넣는 것은 더 후순위입니다. 크롤러가 CLI 인자, timeout, 명확한 exit code, 테스트,
정책 검토를 갖춘 뒤에만 승격합니다.

## 7. GCS 저장 정책

`landing`, `processed`, `logs`, DVC remote를 같은 prefix에 섞지 않습니다.

초기 MVP 입력:

```text
# [Design Intent] 팀원이 올린 processed 후보 CSV는 공식 데이터셋과 분리된 landing prefix에 둔다.
gs://ssakda/projects/brandmate/data/landing/processed/sns_meme_trend/week=YYYY-Www/trend_meme_YYYY-Www.csv
```

초기 MVP 출력:

```text
# [Design Intent] 초기 Airflow는 데이터 파일을 복사/승격하지 않고 검증 결과만 남긴다.
gs://ssakda/projects/brandmate/logs/data_pipeline/airflow/
  dag_id=brandmate_weekly_meme_csv_validation/
    week=YYYY-Www/
      validation_summary.json
      error.json
```

공식 processed 데이터셋:

```text
# [Design Intent] 데이터셋 관리자가 검토 후 승인한 공식 데이터셋만 processed와 DVC로 추적한다.
gs://ssakda/projects/brandmate/data/processed/sns/v1/meme_phrase_dataset/
  data.csv
  data.parquet
  docs/
    manifest.json
    description.md
```

DVC remote:

```text
# [Design Intent] DVC 내부 object store는 사람이 직접 파일을 올리거나 정리하지 않는다.
gs://ssakda/dvc/brandmate/
```

웹서비스 장애 로그는 별도 prefix를 사용합니다.

```text
# [Design Intent] 데이터 파이프라인 장애와 사용자 요청 처리 장애를 분리해 원인 분석 경계를 명확히 한다.
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

## 8. 산출물 검증 기준

CSV/JSON 인입 시 최소한 아래 검증은 통과해야 합니다.

| 검증 항목 | 목적 | 실패 처리 |
| --- | --- | --- |
| 필수 컬럼 존재 | schema drift 차단 | DAG 실패 |
| row count > 0 | 빈 파일 차단 | DAG 실패 |
| 선택 `source` 값 확인 | source 컬럼이 있을 때만 허용 목록 또는 자유값 정책 확인 | summary 기록 또는 실패 |
| 날짜 범위 | 오래된 밈/미래 날짜 데이터 차단 | DAG 실패 또는 quarantine |
| primary key 중복률 | 중복 수집 감지 | 임계치 초과 시 실패 |
| URL 중복률 | source 간 중복 콘텐츠 감지 | summary 기록, 과도하면 실패 |
| null 비율 | feature 품질 저하 감지 | 임계치 초과 시 실패 |
| text 길이 | 빈 문구/비정상 장문 차단 | quarantine 또는 실패 |
| engagement_count 타입 | ranking feature 품질 보장 | 변환 실패 시 null 처리 후 summary 기록 |
| checksum | 같은 파일 재업로드/변조 추적 | manifest 또는 validation result에 기록 |

권장 validation result:

```jsonc
// [Design Intent] validation result는 사람이 읽는 로그이면서 자동 검증 리포트로도 재사용 가능해야 한다.
{
  "dataset": "sns_meme_trend",
  "period_type": "weekly",
  "period": "2026-W29",
  "status": "passed",
  "row_count": 325,
  "input_path": "gs://ssakda/projects/brandmate/data/landing/processed/sns_meme_trend/week=2026-W29/trend_meme_2026-W29.csv",
  "duplicate_url_rate": 0.031,
  "null_text_rate": 0.0,
  "checksum": "sha256:TODO"
}
```

## 9. pandas와 Spark 기준

현재 BrandMate trend context 수집은 `pandas`로 처리합니다. Spark는 지금 단계에서 넣지 않습니다.

| 상황 | 선택 |
| --- | --- |
| CSV 수 MB~수백 MB, 텍스트 정제, 중복 제거 | `pandas` |
| 매일 수 GB 이상, 대량 join, window aggregation | Spark 또는 Dataproc 검토 |
| 분석 쿼리와 dashboard 중심 | BigQuery 검토 |
| 실시간 검색/추천 serving | Elasticsearch, DB, API 설계 검토 |

Spark를 쓰지 않는 이유:

```text
# [Design Intent] 현재 병목이 아닌 분산 처리 인프라를 먼저 넣지 않고, 운영 복잡도를 데이터 규모에 맞춘다.
- 현재 `gather_data` 산출물은 MVP 기준으로 pandas 처리량 안에 들어온다.
- Airflow 도입 목적은 분산 연산이 아니라 스케줄링, 재시도, 검증, 로그 추적이다.
- Spark는 job packaging, cluster/runtime, dependency 관리 비용이 있다.
- 데이터 크기와 변환 복잡도가 실제로 커진 뒤 승격한다.
```

## 10. 인증과 보안

서비스 계정 JSON key를 DAG 코드 안에서 생성하거나 임시 파일로 흘리는 방식은 피합니다.

권장:

```text
# [Design Intent] credential을 DAG 코드와 분리해 key 유출과 환경별 설정 꼬임을 줄인다.
- Airflow Connection에 Google Cloud connection 등록
- VM 또는 Airflow container에 Application Default Credentials 설정
- GCS 접근 권한은 최소권한 원칙으로 부여
- raw/processed/logs prefix별 권한 범위를 분리할 수 있으면 분리
```

금지:

```text
# [Design Intent] credential을 코드/로그/XCom에 남기지 않는다.
- service account JSON을 Git에 커밋
- DAG 내부에서 key 파일 문자열 생성
- XCom에 credential 저장
- Airflow log에 credential path나 secret value 출력
```

## 11. 실패 처리 기준

트렌드 크롤링은 자주 깨집니다. 사이트 구조 변경, API quota, rate limit, 네트워크 지연이 정상적으로 발생합니다.
따라서 실패 처리를 설계에 포함해야 합니다.

| 실패 지점 | 처리 |
| --- | --- |
| 특정 source 산출물 미생성 | 해당 source 실패로 기록, 필수 source면 DAG 실패 |
| 일부 row validation 실패 | quarantine 파일로 분리하고 summary 기록 |
| 필수 컬럼 누락 | DAG 실패 |
| 전체 row count 0 | DAG 실패 |
| GCS 업로드 실패 | retry 후 실패 시 error bundle 저장 |
| validation summary 저장 실패 | retry 후 실패 시 Airflow task 로그 확인 |

에러 저장 형식:

```jsonc
// [Design Intent] 장애 재현에 필요한 최소 실행 맥락을 error bundle에 남긴다.
{
  "time": "2026-07-20T07:15:22+09:00",
  "dag_id": "brandmate_weekly_meme_csv_validation",
  "task_id": "validate_csv_schema",
  "run_id": "scheduled__2026-07-20T07:00:00+09:00",
  "status": "failed",
  "period": "2026-W29",
  "error_type": "SchemaValidationError",
  "error_message": "missing required column: trend_term",
  "input_path": "gs://ssakda/projects/brandmate/data/landing/processed/sns_meme_trend/week=2026-W29/trend_meme_2026-W29.csv"
}
```

## 12. 초기 POC 순서

초기 Airflow POC는 실제 크롤러 전체를 바로 붙이지 않습니다. 먼저 mock CSV로
GCS landing 감지와 CSV validation, validation summary 저장만 검증합니다.

로컬 mock POC 구성:

```text
# [Design Intent] GCS 인증 문제와 Airflow DAG 동작 검증을 분리하기 위해 mock GCS 경로를 먼저 사용한다.
docker-compose.airflow.yml
airflow/
  dags/
    brandmate_weekly_meme_csv_validation.py
  include/
    brandmate_meme_validation.py
    run_meme_validation.py
  mock_gcs/
    data/landing/processed/sns_meme_trend/week=2026-W29/trend_meme_2026-W29.csv
```

Airflow 없이 검증 로직만 먼저 확인:

```bash
# [Design Intent] DAG를 올리기 전에 검증 로직과 mock CSV 계약부터 확인한다.
python airflow/include/run_meme_validation.py \
  --base-dir airflow/mock_gcs \
  --week 2026-W29
```

Airflow 실행:

```bash
# [Design Intent] Airflow webserver, scheduler, metadata DB만 Docker Compose로 구동한다.
chmod -R g+w airflow/mock_gcs
docker compose -f docker-compose.airflow.yml up airflow-init
docker compose -f docker-compose.airflow.yml up -d airflow-webserver airflow-scheduler
```

현재 `docker-compose.airflow.yml`은 로컬 POC 권한 문제를 줄이기 위해 Airflow 컨테이너를 `user: "0:0"`으로
실행합니다. 운영 배포 설정이 아닙니다. GCP/운영 환경에서는 전용 Airflow 이미지, 명시적인 UID/GID,
로그 볼륨 권한 설정, Secret/Connection 관리를 별도로 잡아야 합니다.

접속 정보:

```text
# [Design Intent] MVP에서는 로컬 Admin 계정으로 DAG 실행 여부만 확인한다.
URL: http://localhost:8080
username: admin
password: admin
```

수동 실행 시 `Trigger DAG w/ config`에 아래 값을 넣으면 mock week를 고정해서 실행할 수 있습니다.

```json
{
  "week": "2026-W29"
}
```

검증 결과는 아래 mock GCS log 경로에 저장됩니다.

```text
# [Design Intent] validation summary는 Airflow metadata DB가 아니라 데이터 파이프라인 로그 경로에 저장한다.
airflow/mock_gcs/logs/data_pipeline/airflow/
  dag_id=brandmate_weekly_meme_csv_validation/
    week=2026-W29/
      validation_summary.json
      error.json
```

로컬 POC 검증 완료 상태:

```text
# [Design Intent] Airflow 도입 범위를 mock CSV 자동 검수로 제한하고, GCS/DVC 연동 전 실행 가능성을 먼저 증명한다.
DAG: brandmate_weekly_meme_csv_validation
Input: airflow/mock_gcs/data/landing/processed/sns_meme_trend/week=2026-W29/trend_meme_2026-W29.csv
Output: airflow/mock_gcs/logs/data_pipeline/airflow/dag_id=brandmate_weekly_meme_csv_validation/week=2026-W29/validation_summary.json
```

확인된 항목:

```text
# [Design Intent] POC에서 통과한 범위와 아직 남은 범위를 분리해 다음 작업 판단을 단순하게 만든다.
- Python validation script: passed
- Docker Compose config: passed
- Airflow metadata DB init: passed
- Airflow DAG import: passed
- Airflow manual DAG run: success
- Airflow webserver: healthy
- Airflow scheduler: running
```

로컬 Airflow 종료:

```bash
# [Design Intent] Airflow POC 컨테이너가 다른 로컬 서비스 포트나 Docker 리소스를 계속 잡고 있지 않게 한다.
docker compose -f docker-compose.airflow.yml down
```

POC 순서:

```text
# [Design Intent] 크롤러 품질 문제와 Airflow/GCS 연결 문제를 분리해 디버깅 범위를 줄인다.
1. mock weekly meme CSV 생성
2. GCS landing prefix에 업로드
3. Airflow DAG 수동 실행
4. `check_weekly_csv_exists` 통과 확인
5. `validate_csv_schema` 통과 확인
6. `validate_csv_quality` 통과 확인
7. `validation_summary.json` 저장 확인
8. 실패 mock CSV로 DAG 실패와 `error.json` 저장 확인
9. 실제 팀원 주간 CSV로 교체
10. 데이터셋 관리자가 기존 DVC 절차로 공식 processed 데이터셋 등록
```

예시 mock CSV:

```text
# [Design Intent] mock CSV는 팀원이 업로드할 주간 processed 후보 CSV와 같은 형태로 만든다.
id,collected_at,published_at,keyword,trend_term,text,url,engagement_count,source
meme_2026w29_0001,2026-07-15T07:00:00+09:00,2026-07-14T23:10:00+09:00,밈,두바이 초콜릿,"두바이 초콜릿 이후 디저트 밈 확산",https://example.com/1,1200,careet
meme_2026w29_0002,2026-07-15T07:00:00+09:00,2026-07-14T21:30:00+09:00,카페 트렌드,요아정,"요아정 소비 맥락을 활용한 카페 신메뉴 콘텐츠",https://example.com/2,3400,gogumafarm
meme_2026w29_0003,2026-07-15T07:00:00+09:00,,카페,신메뉴 홍보,"여름 카페 신메뉴 리뷰 글 증가",https://example.com/3,80,naver_blog
```

## 13. 완료 기준

- Airflow webserver에 접속할 수 있습니다.
- Airflow scheduler가 DAG를 감지합니다.
- `brandmate_weekly_meme_csv_validation` DAG를 수동 실행할 수 있습니다.
- mock weekly meme CSV validation이 성공합니다.
- 실패 mock CSV에서 DAG가 실패하고 `error.json`이 GCS에 저장됩니다.
- validation summary가 GCS `logs/data_pipeline/airflow/`에 저장됩니다.
- Airflow XCom에 CSV 본문이나 DataFrame이 저장되지 않습니다.
- DVC 등록은 Airflow가 아니라 데이터셋 관리자가 기존 절차로 수행합니다.

## 14. 후순위 작업

Airflow 인입 파이프라인이 먼저입니다. Prometheus/Grafana는 그 다음 단계에서 metric 관찰용으로 추가합니다.

우선순위:

1. GCS landing 기반 weekly meme CSV 자동 검수
2. validation summary 기반 데이터셋 관리자 검토 프로세스 정리
3. release candidate 패키징 자동화 검토
4. 통합 CSV 생성 스크립트 안정화 후 Airflow 편입 검토
5. source별 crawler task Airflow 편입은 필요성이 생길 때 별도 검토
6. FastAPI request_id 기반 structured logging
7. GCS error bundle 저장
8. Prometheus/Grafana metric dashboard
9. Cloud Logging ERROR/WARNING 제한 연동
10. 데이터 규모 증가 시 BigQuery 또는 Spark/Dataproc 검토
