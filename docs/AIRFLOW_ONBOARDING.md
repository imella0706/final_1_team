# BrandMate Airflow Onboarding

이 문서는 BrandMate의 SNS 트렌드/밈 문구 데이터 인입 파이프라인을 Airflow로 구축하기 위한 기준입니다.

Airflow는 크롤링 라이브러리도 아니고 전처리 엔진도 아닙니다. Airflow의 역할은 정해진 주기로 작업을
실행하고, task 의존성, 실패 재시도, backfill, 실행 로그를 통제하는 것입니다. 실제 크롤링은
`requests`, `BeautifulSoup`, `Selenium`, `Playwright`가 담당하고, MVP 전처리는 `pandas`가 담당합니다.

BrandMate는 네이버, 구글, 인스타그램, 틱톡 등에서 최신 트렌드 밈 문구를 주기적으로 수집합니다.
밈/트렌드는 시간이 지나면 데이터 가치가 떨어지므로 수동 실행이나 단발성 스크립트로 관리하면 운영 품질이
무너집니다. Airflow는 이 반복 수집과 검증, GCS 저장, 실패 추적을 자동화하기 위해 사용합니다.

## 1. 적용 범위

현재 BrandMate에서 Airflow를 적용할 대상은 데이터 인입 파이프라인입니다.

적용 대상:

```text
# [Design Intent] 반복 실행, 실패 추적, 재처리가 필요한 배치성 데이터 작업만 Airflow에 올린다.
- SNS/검색 트렌드 크롤링 task 실행
- 크롤러가 만든 CSV 파일 감지
- raw CSV를 GCS raw prefix에 백업
- schema, row count, null 비율, 중복률, 날짜 범위, checksum 검증
- 검증된 CSV를 processed Parquet/CSV로 변환
- manifest, validation result, run summary, error bundle 저장
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

현재 팀원이 크롤링과 기본 전처리를 수행해 CSV로 저장하고 있으므로, 첫 단계는 아래 구조가 맞습니다.

```text
# [Design Intent] 기존 크롤러 구현을 억지로 뜯지 않고, CSV contract를 경계로 Airflow 인입 품질을 먼저 확보한다.
external crawler
  -> local/server landing CSV
  -> Airflow detect CSV
  -> validate CSV
  -> upload raw CSV to GCS
  -> transform to processed dataset
  -> upload processed artifact to GCS
  -> write manifest and run summary
```

크롤러까지 Airflow task로 넣는 구조는 2단계입니다.

```text
# [Design Intent] 수집 코드가 안정화된 뒤 source별 크롤링 실패를 Airflow task 단위로 격리한다.
Airflow DAG
  -> crawl_naver
  -> crawl_google
  -> crawl_instagram
  -> crawl_tiktok
  -> merge_raw_csv
  -> validate_csv
  -> upload_raw_to_gcs
  -> transform_to_processed
  -> upload_processed_to_gcs
  -> write_run_summary
```

처음부터 크롤러 전체를 Airflow에 넣지 않아도 됩니다. 먼저 CSV 형식과 저장 위치를 고정하고,
Airflow가 그 결과물을 안정적으로 검증하고 GCS에 올리게 만듭니다.

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

## 5. SNS Trend CSV Contract

Airflow에 연결하기 전에 팀원이 생성하는 CSV 형식을 고정해야 합니다. 이 계약 없이 Airflow를 붙이면
자동화된 쓰레기 수거장이 됩니다. 스케줄러가 성실하게 잘못된 데이터를 GCS에 쌓는 구조가 됩니다.

파일명 규칙:

```text
# [Design Intent] source, 수집일, 실행 단위를 파일명에 박아 재처리와 장애 추적을 단순하게 만든다.
{source}_trend_{YYYYMMDD}.csv
naver_trend_20260714.csv
google_trend_20260714.csv
instagram_trend_20260714.csv
tiktok_trend_20260714.csv
```

권장 landing directory:

```text
# [Design Intent] Airflow worker가 접근 가능한 서버 경로를 ingestion boundary로 삼는다.
/data/brandmate/incoming/sns_trend/dt=YYYY-MM-DD/{source}_trend_YYYYMMDD.csv
```

필수 컬럼:

| 컬럼 | 의미 | 예시 |
| --- | --- | --- |
| `id` | source 내부 식별자. 없으면 URL hash로 생성 | `naver_20260714_0001` |
| `source` | 데이터 출처 | `naver`, `google`, `instagram`, `tiktok` |
| `collected_at` | 크롤링 수집 시각 | `2026-07-14T07:00:00+09:00` |
| `published_at` | 원문 게시 시각. 없으면 null 허용 | `2026-07-13T22:10:00+09:00` |
| `keyword` | 수집 기준 키워드 또는 trend seed | `여름 밈` |
| `text` | 수집된 밈 문구/본문/캡션 | `요즘 이 밈 모르면 대화가 안 됨` |
| `url` | 원문 URL | `https://...` |
| `engagement_count` | 좋아요/댓글/조회수 합산 또는 source별 기준값 | `1234` |

선택 컬럼:

| 컬럼 | 의미 |
| --- | --- |
| `author` | 작성자 또는 채널명 |
| `hashtags` | 해시태그 문자열 또는 JSON string |
| `category` | 음식, 카페, 계절, 이벤트 등 내부 분류 |
| `language` | `ko`, `en` 등 |
| `raw_payload_path` | 원본 HTML/JSON/screenshot을 별도 저장한 경우의 경로 |

CSV 기본 규칙:

```text
# [Design Intent] source별 크롤러 구현이 달라도 downstream validation과 전처리를 동일하게 만든다.
- encoding: utf-8
- delimiter: comma
- newline: LF
- duplicate key: source + id 또는 normalized url
- time zone: Asia/Seoul 기준 ISO-8601 권장
- 빈 문자열과 null 표기 방식은 pandas에서 일관되게 읽히도록 통일
```

## 6. 권장 DAG 구조

초기 MVP DAG는 외부 크롤러가 만든 CSV를 Airflow가 수집하는 방식으로 시작합니다.

```text
# [Design Intent] 이미 존재하는 크롤러 산출물에 품질 게이트와 저장 정책을 붙이는 최소 MVP DAG다.
brandmate_sns_trend_ingestion

wait_for_source_csv
  -> validate_source_csv
  -> upload_raw_csv_to_gcs
  -> merge_sources
  -> transform_to_processed
  -> validate_processed
  -> upload_processed_to_gcs
  -> write_manifest
  -> write_run_summary
```

크롤러까지 Airflow에서 실행하는 2단계 DAG는 아래 구조를 사용합니다.

```text
# [Design Intent] source별 크롤링 실패를 분리해 하나의 외부 사이트 장애가 전체 수집을 막지 않게 한다.
brandmate_sns_trend_crawling

crawl_naver
crawl_google
crawl_instagram
crawl_tiktok
  -> validate_source_csv
  -> upload_raw_csv_to_gcs
  -> merge_sources
  -> transform_to_processed
  -> validate_processed
  -> upload_processed_to_gcs
  -> write_manifest
  -> write_run_summary
```

Python DAG skeleton:

```python
# [Design Intent] DAG skeleton은 source별 task 격리, 단일 active run, 실패 재시도, 실행 timeout을 기본값으로 강제한다.
from __future__ import annotations

from datetime import timedelta

from airflow import DAG
from airflow.operators.python import PythonOperator
from pendulum import datetime


with DAG(
    dag_id="brandmate_sns_trend_ingestion",
    start_date=datetime(2026, 7, 14, tz="Asia/Seoul"),
    schedule="0 7 * * *",
    catchup=False,
    max_active_runs=1,
    default_args={
        "retries": 2,
        "retry_delay": timedelta(minutes=10),
        "execution_timeout": timedelta(minutes=30),
    },
    tags=["brandmate", "sns", "trend", "ingestion"],
) as dag:
    wait_for_source_csv = PythonOperator(
        task_id="wait_for_source_csv",
        python_callable=wait_for_source_csv_files,
    )

    validate_source_csv = PythonOperator(
        task_id="validate_source_csv",
        python_callable=validate_source_csv_files,
    )

    upload_raw_csv_to_gcs = PythonOperator(
        task_id="upload_raw_csv_to_gcs",
        python_callable=upload_raw_csv_files,
    )

    merge_sources = PythonOperator(
        task_id="merge_sources",
        python_callable=merge_source_csv_files,
    )

    transform_to_processed = PythonOperator(
        task_id="transform_to_processed",
        python_callable=transform_sns_trend_dataset,
    )

    validate_processed = PythonOperator(
        task_id="validate_processed",
        python_callable=validate_processed_dataset,
    )

    upload_processed_to_gcs = PythonOperator(
        task_id="upload_processed_to_gcs",
        python_callable=upload_processed_dataset,
    )

    write_manifest = PythonOperator(
        task_id="write_manifest",
        python_callable=write_dataset_manifest,
    )

    write_run_summary = PythonOperator(
        task_id="write_run_summary",
        python_callable=write_airflow_run_summary,
    )

    wait_for_source_csv >> validate_source_csv >> upload_raw_csv_to_gcs
    upload_raw_csv_to_gcs >> merge_sources >> transform_to_processed
    transform_to_processed >> validate_processed >> upload_processed_to_gcs
    upload_processed_to_gcs >> write_manifest >> write_run_summary
```

## 7. GCS 저장 정책

`raw`, `processed`, `logs`를 같은 prefix에 섞지 않습니다.

SNS trend raw:

```text
# [Design Intent] 원본 CSV를 source와 수집일 기준으로 보존해 전처리 버그가 나도 재생성 가능하게 만든다.
gs://ssakda/projects/brandmate/data/raw/sns_trend/dt=YYYY-MM-DD/naver.csv
gs://ssakda/projects/brandmate/data/raw/sns_trend/dt=YYYY-MM-DD/google.csv
gs://ssakda/projects/brandmate/data/raw/sns_trend/dt=YYYY-MM-DD/instagram.csv
gs://ssakda/projects/brandmate/data/raw/sns_trend/dt=YYYY-MM-DD/tiktok.csv
```

SNS trend processed:

```text
# [Design Intent] 모델/API/평가 코드가 바로 읽을 수 있는 stable artifact만 processed에 둔다.
gs://ssakda/projects/brandmate/data/processed/sns_trend/v1/meme_phrase_dataset/
  data.parquet
  data.csv
  validation_summary.json
  docs/
    manifest.json
    description.md
```

Airflow logs:

```text
# [Design Intent] Airflow DB에는 상태만 남기고 상세 검증/장애 기록은 GCS에 남긴다.
gs://ssakda/projects/brandmate/logs/data_pipeline/airflow/
  dt=YYYY-MM-DD/
    dag_id=brandmate_sns_trend_ingestion/
      run_id={run_id}/
        run_summary.json
        validation_result.json
        error.json
        traceback.txt
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

## 8. CSV 검증 기준

CSV 인입 시 최소한 아래 검증은 통과해야 합니다.

| 검증 항목 | 목적 | 실패 처리 |
| --- | --- | --- |
| 필수 컬럼 존재 | schema drift 차단 | DAG 실패 |
| row count > 0 | 빈 파일 차단 | DAG 실패 |
| source 값 허용 목록 확인 | 잘못된 source명 차단 | DAG 실패 |
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
  "dataset": "sns_trend",
  "run_date": "2026-07-14",
  "status": "passed",
  "row_count": 1240,
  "source_counts": {
    "naver": 310,
    "google": 280,
    "instagram": 420,
    "tiktok": 230
  },
  "duplicate_url_rate": 0.031,
  "null_text_rate": 0.0,
  "checksum": "sha256:TODO"
}
```

## 9. pandas와 Spark 기준

현재 BrandMate SNS trend 수집은 `pandas`로 처리합니다. Spark는 지금 단계에서 넣지 않습니다.

| 상황 | 선택 |
| --- | --- |
| CSV 수 MB~수백 MB, 텍스트 정제, 중복 제거 | `pandas` |
| 매일 수 GB 이상, 대량 join, window aggregation | Spark 또는 Dataproc 검토 |
| 분석 쿼리와 dashboard 중심 | BigQuery 검토 |
| 실시간 검색/추천 serving | Elasticsearch, DB, API 설계 검토 |

Spark를 쓰지 않는 이유:

```text
# [Design Intent] 현재 병목이 아닌 분산 처리 인프라를 먼저 넣지 않고, 운영 복잡도를 데이터 규모에 맞춘다.
- SNS 밈 문구 CSV는 MVP 기준으로 pandas 처리량 안에 들어온다.
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

SNS 크롤링은 자주 깨집니다. 사이트 구조 변경, rate limit, 로그인 요구, 네트워크 지연이 정상적으로 발생합니다.
따라서 실패 처리를 설계에 포함해야 합니다.

| 실패 지점 | 처리 |
| --- | --- |
| 특정 source CSV 미생성 | 해당 source 실패로 기록, 필수 source면 DAG 실패 |
| 일부 row validation 실패 | quarantine CSV로 분리하고 summary 기록 |
| 필수 컬럼 누락 | DAG 실패 |
| 전체 row count 0 | DAG 실패 |
| GCS 업로드 실패 | retry 후 실패 시 error bundle 저장 |
| processed 변환 실패 | raw 경로를 summary에 남기고 DAG 실패 |

에러 저장 형식:

```jsonc
// [Design Intent] 장애 재현에 필요한 최소 실행 맥락을 error bundle에 남긴다.
{
  "time": "2026-07-14T07:15:22+09:00",
  "dag_id": "brandmate_sns_trend_ingestion",
  "task_id": "validate_source_csv",
  "run_id": "manual__2026-07-14T07:00:00+09:00",
  "status": "failed",
  "source": "instagram",
  "error_type": "SchemaValidationError",
  "error_message": "missing required column: text",
  "raw_path": "/data/brandmate/incoming/sns_trend/dt=2026-07-14/instagram_trend_20260714.csv"
}
```

## 12. 초기 POC 순서

초기 Airflow POC는 실제 SNS 크롤러 전체를 바로 붙이지 않습니다. 먼저 mock CSV로
Airflow -> validation -> raw upload -> processed 변환 -> GCS upload 흐름을 검증합니다.

POC 순서:

```text
# [Design Intent] 크롤러 품질 문제와 Airflow/GCS 연결 문제를 분리해 디버깅 범위를 줄인다.
1. mock SNS CSV 생성
2. local landing directory에 저장
3. Airflow DAG 수동 실행
4. CSV validation 통과 확인
5. raw CSV GCS 업로드 확인
6. processed Parquet/CSV 생성 확인
7. run_summary.json, validation_result.json 저장 확인
8. 실패 CSV로 DAG 실패와 error.json 저장 확인
9. 실제 crawler 산출 CSV로 교체
10. source별 crawler task를 Airflow 내부로 옮길지 판단
```

예시 mock CSV:

```text
# [Design Intent] mock CSV는 실제 SNS crawler 산출물과 같은 schema로 만들어 DAG 연결만 먼저 검증한다.
id,source,collected_at,published_at,keyword,text,url,engagement_count
instagram_001,instagram,2026-07-14T07:00:00+09:00,2026-07-13T23:10:00+09:00,여름 밈,"요즘 이거 모르면 대화가 안 됨",https://example.com/1,1200
tiktok_001,tiktok,2026-07-14T07:00:00+09:00,2026-07-13T21:30:00+09:00,카페 트렌드,"얼죽아 다음은 얼죽빙",https://example.com/2,3400
naver_001,naver,2026-07-14T07:00:00+09:00,,신메뉴 홍보,"두바이 초콜릿 다음 유행 찾는 중",https://example.com/3,80
```

## 13. 완료 기준

- Airflow webserver에 접속할 수 있습니다.
- Airflow scheduler가 DAG를 감지합니다.
- `brandmate_sns_trend_ingestion` DAG를 수동 실행할 수 있습니다.
- mock SNS CSV ingestion이 성공합니다.
- 실패 mock CSV에서 DAG가 실패하고 `error.json`이 GCS에 저장됩니다.
- source별 raw CSV가 GCS raw prefix에 저장됩니다.
- processed `meme_phrase_dataset` 산출물이 GCS processed prefix에 저장됩니다.
- validation summary가 GCS `logs/data_pipeline/airflow/`에 저장됩니다.
- Airflow XCom에 CSV 본문이나 DataFrame이 저장되지 않습니다.
- Spark 없이 pandas 기반 변환이 동작합니다.

## 14. 후순위 작업

Airflow 인입 파이프라인이 먼저입니다. Prometheus/Grafana는 그 다음 단계에서 metric 관찰용으로 추가합니다.

우선순위:

1. Airflow 기반 SNS trend CSV 인입 파이프라인
2. source별 crawler task Airflow 편입
3. FastAPI request_id 기반 structured logging
4. GCS error bundle 저장
5. Prometheus/Grafana metric dashboard
6. Cloud Logging ERROR/WARNING 제한 연동
7. 데이터 규모 증가 시 BigQuery 또는 Spark/Dataproc 검토
