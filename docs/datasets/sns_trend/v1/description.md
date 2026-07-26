# sns_trend v1 Description

## Summary

`sns_trend`는 YouTube, Gogumafarm, Careet, Naver에서 수집한 SNS/콘텐츠 트렌드 후보 데이터를 기반으로 만든 데이터셋입니다.
현재 `v1`의 processed 산출물인 `cross_platform_signal_top_candidates`는 4개 플랫폼 후보를 병합한 뒤 플랫폼별 신호를 `signal` score로 정량화하고, 상위 점수 후보만 남겨 프롬프트/RAG 파이프라인에서 바로 참고할 수 있도록 만든 결과입니다.

## Dataset Stage

- 단계: processed
- 판단 근거: `platform_cleaned`와 `keyword_terms`는 프로젝트에 쓸 후보 데이터를 정리한 curated 데이터입니다. 반면 `cross_platform_signal_top_candidates`는 4개 플랫폼 후보를 merge하고, source별 신호를 `signal` score로 맞춘 뒤 상위 점수 후보만 남긴 processed 산출물입니다. query, score, rank, matched_terms, reasons, card metadata가 포함되어 있어 실제 프롬프트/RAG 파이프라인에서 바로 소비할 수 있는 구조입니다.

## Files

- 주요 파일 목록:
  - `data/landing/sns_trend/week=2026-W28/raw/`
  - `data/curated/sns_trend/v1/platform_cleaned/`
  - `data/curated/sns_trend/v1/keyword_terms/`
  - `data/processed/sns_trend/v1/cross_platform_signal_top_candidates/cross_platform_signal_top_candidates.json`
  - `data/processed/sns_trend/v1/cross_platform_signal_top_candidates/cross_platform_signal_top_candidates.csv`
- row/image 개수:
  - processed result: 5 results / 5 CSV rows
  - raw CSV rows: 5,728 rows
  - curated 1차 CSV rows: 2,732 rows
  - curated 2차 JSON terms: 332 terms
  - curated 2차 CSV suspect rows: 9 rows
  - image count: none
- 전체 용량: 약 1.4 MB (표준 `data/landing`, `data/curated`, `data/processed` 구조 기준)
- 파일별 역할:
  - `data/landing/sns_trend/week=2026-W28/raw/`: 플랫폼별 최초 수집 CSV입니다.
  - `data/curated/sns_trend/v1/platform_cleaned/`: null, 중복, 불필요 컬럼 제거 등 플랫폼별 1차 정리본입니다.
  - `data/curated/sns_trend/v1/keyword_terms/`: 후보 키워드/밈 표현을 JSON/CSV로 정리한 파일입니다.
  - `cross_platform_signal_top_candidates.json`: 4개 플랫폼 후보를 merge한 뒤 `signal` score 기준으로 상위 후보만 남긴 nested JSON 결과입니다.
  - `cross_platform_signal_top_candidates.csv`: Airflow 검증과 사람이 확인하기 쉬운 flat table 형태로 펼친 파일입니다.

## Source

- 원본 제공처: YouTube, Gogumafarm, Careet, Naver
- 원본 데이터셋 이름: SNS/content trend crawl
- 원본 URL: multiple
- 사용 split: none
- 수집 기간: 2026-07-07 ~ 2026-07-09
- landing partition: `week=2026-W28`
- 시간대 기준: `Asia/Seoul`
- raw 원본 GCS 업로드 여부: TODO
- 원본 annotation/label 보존 여부: none

## Curation

- 플랫폼: youtube, gogumafarm, careet, naver
- 1차 정리본: `data/curated/sns_trend/v1/platform_cleaned/`
- 후보 키워드 목록: `data/curated/sns_trend/v1/keyword_terms/`
- 선별 기준:
  - `curated-1차 가공`: 링크, position, null, 중복 데이터 등 분석에 불필요한 값을 제거한 플랫폼별 정리본입니다.
  - `curated-2차가공`: Giwoo님의 기존 밈 데이터 정리 방식에 맞춰 `백룸코어`, `천연 위고비`처럼 키워드 중심으로 정리하고, 숫자 등 불필요한 값을 제거한 후보 용어 목록입니다.
- 제외 기준: null, 중복 데이터, 불필요 컬럼, 키워드 후보로 쓰기 어려운 숫자성 값 등을 제거했습니다.
- 카테고리 균형 여부: none
- 이모지 처리: 이모지 자체가 밈 표현일 수 있어 일괄 제거하지 않았습니다.
- 사람 검수 개입: processed ranking 단계에는 사람 검수가 개입하지 않았습니다.
- 원본 경로와 최종 경로 매핑 가능 여부: 가능. 아래 `Folder and File Mapping` 표를 기준으로 추적합니다.

## Processing

- 입력 데이터셋: `sns_trend` curated `platform_cleaned`, `keyword_terms`
- artifact name: `cross_platform_signal_top_candidates`
- 사용 목적: retrieval, prompt context generation, trend candidate ranking
- 전처리 기준: YouTube, Gogumafarm, Careet, Naver 후보를 하나로 merge하고, 플랫폼마다 다른 신호를 `signal` score 지표로 정량화한 뒤 상위 점수 후보만 남깁니다.
- 전처리 단계:
  - YouTube, Gogumafarm, Careet, Naver 후보를 하나의 후보 풀로 merge
  - 플랫폼별 signal 값을 계산해 서로 다른 source의 후보를 비교 가능한 점수로 정량화
  - 현재 demo query 기준으로 후보 검색
  - 제목, 설명, 태그, metadata에서 query term 매칭
  - signal score와 최신성 기준을 반영해 후보 점수화
  - signal score 기준으로 후보를 정렬한 뒤 상위 점수 후보만 보존
  - nested JSON과 Airflow 검증용 flat CSV로 export
- 생성 파일:
  - `cross_platform_signal_top_candidates.json`
  - `cross_platform_signal_top_candidates.csv`
- 사용한 모델/도구: Python demo pipeline (`demo/trend_ad/pipeline.py`)
- 모델/평가/검색/API에서 사용하는 방식: 광고 문구 생성과 밈 기반 프롬프트 조립 시 query 관련 trend candidate를 검색/랭킹 근거로 사용합니다.

## Dataset-Specific Fields

- `cross_platform_signal_top_candidates`: 여러 플랫폼 후보를 merge한 뒤 signal score 기반으로 상위 후보만 남긴 result 구조입니다.
- `signal`: 플랫폼별로 다른 raw 지표를 후보 ranking에 사용할 수 있도록 정량화한 score입니다.
- `human_reviewed`: processed ranking 단계에서는 `false`입니다.
- `top_candidate_policy`: 현재 export는 signal score 기준 상위 후보만 남긴 결과입니다.
- `input_platforms`: query ranking 전에 후보로 넣은 플랫폼 전체입니다.
- `result_platforms`: top result의 대표 source로 실제 등장한 플랫폼입니다.
- `metadata.also_seen_in`: 특정 밈/키워드가 다른 플랫폼에서도 관측되었음을 나타내는 보조 metadata입니다.

## Folder and File Mapping

`sns_trend v1`은 기존 임시 폴더인 `outputs/Chaebin/`에 있던 파일을 아래 GCS/표준 위치로 재배치하는 구조입니다.

| 기존 위치 | 추천 GCS/표준 위치 | 의미 |
| --- | --- | --- |
| `outputs/Chaebin/raw-첫 수집/` | `gs://ssakda/projects/brandmate/data/landing/sns_trend/week=2026-W28/raw/` | 크롤링해서 처음 들어온 입고 데이터 |
| `outputs/Chaebin/curated-1차 가공/` | `gs://ssakda/projects/brandmate/data/curated/sns_trend/v1/platform_cleaned/` | null, 중복, 불필요 컬럼 제거 등 플랫폼별 1차 정리본 |
| `outputs/Chaebin/curated-2차가공/` | `gs://ssakda/projects/brandmate/data/curated/sns_trend/v1/keyword_terms/` | 후보 키워드/밈 표현만 뽑은 목록 |
| `outputs/Chaebin/4_merged.json` | `gs://ssakda/projects/brandmate/data/processed/sns_trend/v1/cross_platform_signal_top_candidates/cross_platform_signal_top_candidates.json` | 4개 플랫폼 후보를 merge한 뒤 signal score 기준으로 상위 후보만 남긴 nested JSON 결과 |
| `outputs/Chaebin/query_ranked_candidates.csv` | `gs://ssakda/projects/brandmate/data/processed/sns_trend/v1/cross_platform_signal_top_candidates/cross_platform_signal_top_candidates.csv` | `cross_platform_signal_top_candidates.json`을 Airflow 검증이 쉽도록 flat CSV로 펼친 파일 |

## Recommended GCS Folder Structure

```text
gs://ssakda/projects/brandmate/data/
  landing/
    sns_trend/
      week=2026-W28/
        raw/
          youtube/
            youtube_keywords_2026-07-07.csv
            youtube_keywords_2026-07-08.csv
          gogumafarm/
            gogumafarm_articles_20260709.csv
          careet/
            careet_articles_20260708.csv
            careet_articles_20260709.csv
          naver/
            naver_blog_cafe.csv
            naver_datalab_cafe.csv
            naver_news_cafe.csv

  curated/
    sns_trend/
      v1/
        platform_cleaned/
          youtube/
            youtube_keyword_trend_comparison.csv
          gogumafarm/
            gogumafarm_meme_terms_20260709.csv
          careet/
            careet_memes_20260708.csv
            careet_memes_20260709.csv
          naver/
            naver_word_freq.csv

        keyword_terms/
          careet/
            careet_meme_terms_20260708.json
            careet_meme_terms_20260709.json
            careet_meme_term_suspects_20260708.csv
          gogumafarm/
            gogumafarm_meme_terms_20260709.json

  processed/
    sns_trend/
      v1/
        cross_platform_signal_top_candidates/
          cross_platform_signal_top_candidates.json
          cross_platform_signal_top_candidates.csv
          docs/
            manifest.json
            description.md
```

GCS에 올리는 파일명은 shell, Airflow, GCS CLI에서 안정적으로 다루기 위해 영어/숫자/underscore 중심으로 정리합니다.
로컬 원본 파일명이 한글을 포함한 경우, GCS 표준 위치에서는 아래처럼 바꿉니다.

| 로컬 원본 파일명 | GCS 표준 파일명 |
| --- | --- |
| `naver_blog_카페.csv` | `naver_blog_cafe.csv` |
| `naver_datalab_카페.csv` | `naver_datalab_cafe.csv` |
| `naver_news_카페.csv` | `naver_news_cafe.csv` |

## Cross Platform Signal Ranked Candidates

- query: `니가 좋아 밈을 활용한 여름 카페 신메뉴 숏폼 광고`
- selected_card_id: `gogumafarm:1bf390d89536004b`
- result count: 5
- input platforms: youtube, gogumafarm, careet, naver
- result platforms: gogumafarm, naver, youtube

`cross_platform_signal_top_candidates.json`은 query와 ranked result를 보존하는 원본 구조입니다.
`cross_platform_signal_top_candidates.csv`는 Airflow에서 필수 컬럼, score, rank, source, URL 누락 여부 등을 검증하기 쉽게 펼친 flat table입니다.

현재 파일은 demo query 기준으로 export된 5개 결과입니다.
다만 산출물의 핵심은 단순 query 결과가 아니라 4개 플랫폼 후보를 merge하고 `signal` score로 우선순위를 매긴 뒤 상위 점수 후보만 남긴 구조입니다.
데이터 양이 커지는 다음 버전에서는 score 기준 top-N 보존 개수를 명시적으로 고정해야 합니다.

`input_platforms`는 query ranking 전에 후보로 넣은 플랫폼 전체입니다.
`result_platforms`는 top 결과의 대표 `source`로 실제 등장한 플랫폼입니다.
원본 JSON의 `metadata.also_seen_in`은 특정 밈/키워드가 다른 플랫폼에서도 함께 관측되었음을 나타내는 보조 metadata입니다.
예를 들어 어떤 결과의 대표 `source`가 `gogumafarm`이어도, `metadata.also_seen_in`에 `careet`이 있으면 같은 밈/키워드가 Careet에서도 관측되었다는 뜻입니다.
따라서 Careet은 이번 top result의 대표 source로는 나오지 않았지만, 일부 후보의 `also_seen_in` metadata에는 포함되어 있습니다.

## Storage

- GCS 업로드 예정 경로: `gs://ssakda/projects/brandmate/data/processed/sns_trend/v1/cross_platform_signal_top_candidates/`
- local example path: `data/processed/sns_trend/v1/cross_platform_signal_top_candidates/`
- 기존 로컬 입력 경로: `outputs/Chaebin/`
- canonical manifest: `docs/datasets/sns_trend/v1/manifest.json`
- canonical description: `docs/datasets/sns_trend/v1/description.md`
- package docs:
  - `data/processed/sns_trend/v1/cross_platform_signal_top_candidates/docs/manifest.json`
  - `data/processed/sns_trend/v1/cross_platform_signal_top_candidates/docs/description.md`
- `gather_data/` 하위 크롤링 runtime 산출물은 Git/GCS 공식 업로드 대상이 아닙니다. 공식 데이터셋에 포함되지 않은 중간 CSV, PNG, smoke output이 필요하면 크롤러 코드를 다시 실행하거나 원본 작업자(박채빈님)에게 별도로 요청해야 합니다.

## Reproducibility

- 데이터셋 생성 스크립트 또는 노트북 경로: `demo/trend_ad/pipeline.py`
- score 계산 코드 위치: `demo/trend_ad/pipeline.py`
- random seed: none
- 같은 결과를 다시 만들 수 있는지: 부분 가능. 공식 processed export는 `demo/trend_ad/pipeline.py` 기준으로 추적하지만, `gather_data/` 하위 runtime 산출물 전체를 Git에 보존하지 않으므로 동일 중간 산출물이 필요하면 크롤러 재실행 또는 원본 작업자 확인이 필요합니다.

## Limitations

- 현재 export 파일은 하나의 demo query에 대한 top candidates입니다. 전체 트렌드 global ranking 데이터셋은 아닙니다.
- signal score 기준 상위 후보만 포함되어 있습니다.
- processed ranking 단계에 인간 검수는 개입하지 않았습니다.
- Instagram 데이터는 정책 또는 접근 제한으로 포함되지 않았습니다.
- source별로 metadata 밀도가 다르며, 일부 source URL 또는 published_date가 비어 있을 수 있습니다.

## Next Version Plan

- 주간 수집 스키마를 안정화합니다.
- `platform_cleaned`, `keyword_terms`, `cross_platform_signal_top_candidates` 생성 코드를 명확히 연결합니다.
- 전체 후보 global ranking 산출물을 만들고, 데이터 양이 커질 경우 score 기준 top-N 보존 개수를 명확히 정합니다.
- Airflow 검증 기준에 맞춰 CSV 필수 컬럼, score 타입, rank 중복 여부, source 허용 목록을 고정합니다.
