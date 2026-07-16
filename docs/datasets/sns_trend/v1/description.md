# sns_trend v1 Description

## Summary

`sns_trend`는 YouTube, Gogumafarm, Careet, Naver에서 수집한 SNS/콘텐츠 트렌드 후보 데이터를 기반으로 만든 데이터셋입니다.
현재 `v1`의 processed 산출물인 `query_ranked_candidates`는 특정 광고 query에 대해 플랫폼별 후보를 검색하고, score/ranking을 계산해 프롬프트/RAG 파이프라인에서 바로 참고할 수 있도록 만든 결과입니다.

## Dataset Stage

이 산출물은 `processed` 단계입니다.

`platform_cleaned`와 `keyword_terms`는 프로젝트에 쓸 후보 데이터를 정리한 curated 데이터입니다.
반면 `query_ranked_candidates`는 query, score, rank, matched_terms, reasons, card metadata가 포함되어 있어 실제 프롬프트/RAG 파이프라인에서 바로 소비할 수 있는 구조입니다.

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
- 선별 기준: null, 중복, 불필요 컬럼을 제거하고 플랫폼별 후보 키워드와 밈 표현을 정리했습니다.
- 이모지 처리: 이모지 자체가 밈 표현일 수 있어 일괄 제거하지 않았습니다.
- 사람 검수 개입: TODO

## Processing

- 입력 데이터셋: `sns_trend` curated `platform_cleaned`, `keyword_terms`
- artifact name: `query_ranked_candidates`
- 사용 목적: retrieval, prompt context generation, trend candidate ranking
- 처리 내용:
  - YouTube, Gogumafarm, Careet, Naver 후보를 query 기준으로 검색
  - 제목, 설명, 태그, metadata에서 query term 매칭
  - signal score와 최신성 기준을 반영해 후보 점수화
  - 상위 후보를 ranking 형태로 정렬
  - nested JSON과 Airflow 검증용 flat CSV로 export
- 생성 파일:
  - `query_ranked_candidates.json`
  - `query_ranked_candidates.csv`

## Query Ranked Candidates

- query: `니가 좋아 밈을 활용한 여름 카페 신메뉴 숏폼 광고`
- selected_card_id: `gogumafarm:1bf390d89536004b`
- result count: 5
- result sources: gogumafarm, naver, youtube

`query_ranked_candidates.json`은 query와 ranked result를 보존하는 원본 구조입니다.
`query_ranked_candidates.csv`는 Airflow에서 필수 컬럼, score, rank, source, URL 누락 여부 등을 검증하기 쉽게 펼친 flat table입니다.

## Storage

- GCS path: `gs://ssakda/projects/brandmate/data/processed/sns_trend/v1/query_ranked_candidates/`
- local example path: `data/processed/sns_trend/v1/query_ranked_candidates/`
- canonical manifest: `docs/datasets/sns_trend/v1/manifest.json`
- canonical description: `docs/datasets/sns_trend/v1/description.md`
- package docs:
  - `data/processed/sns_trend/v1/query_ranked_candidates/docs/manifest.json`
  - `data/processed/sns_trend/v1/query_ranked_candidates/docs/description.md`
- DVC tracking 여부: false

## Reproducibility

- 데이터셋 생성 스크립트 또는 노트북 경로: TODO
- score 계산 코드 위치: TODO
- random seed: none
- 같은 결과를 다시 만들 수 있는지: TODO

## Limitations

- 현재 산출물은 하나의 demo query에 대한 ranked candidates입니다. 전체 트렌드 global ranking 데이터셋은 아닙니다.
- query에 대한 상위 후보만 포함되어 있습니다.
- Instagram 데이터는 정책 또는 접근 제한으로 포함되지 않았습니다.
- source별로 metadata 밀도가 다르며, 일부 source URL 또는 published_date가 비어 있을 수 있습니다.

## Next Version Plan

- 주간 수집 스키마를 안정화합니다.
- `platform_cleaned`, `keyword_terms`, `query_ranked_candidates` 생성 코드를 명확히 연결합니다.
- query 기반 결과와 별도로 전체 후보 global ranking 산출물을 만들지 검토합니다.
- Airflow 검증 기준에 맞춰 CSV 필수 컬럼, score 타입, rank 중복 여부, source 허용 목록을 고정합니다.
