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

## Folder and File Mapping

`sns_trend v1`은 기존 임시 폴더인 `data/Chaebin/`에 있던 파일을 아래 GCS/표준 위치로 재배치하는 구조입니다.

| 기존 위치 | GCS/표준 위치 | 의미 |
| --- | --- | --- |
| `data/Chaebin/raw-첫 수집/` | `data/landing/sns_trend/week=2026-W28/raw/` | 크롤링해서 처음 들어온 입고 데이터 |
| `data/Chaebin/curated-1차 가공/` | `data/curated/sns_trend/v1/platform_cleaned/` | null, 중복, 불필요 컬럼 제거 등 플랫폼별 1차 정리본 |
| `data/Chaebin/curated-2차가공/` | `data/curated/sns_trend/v1/keyword_terms/` | 후보 키워드/밈 표현만 뽑은 목록 |
| `data/Chaebin/4_merged.json` | `data/processed/sns_trend/v1/query_ranked_candidates/query_ranked_candidates.json` | 특정 query 기준으로 후보를 점수화/정렬한 nested JSON 결과 |
| `data/Chaebin/query_ranked_candidates.csv` | `data/processed/sns_trend/v1/query_ranked_candidates/query_ranked_candidates.csv` | `query_ranked_candidates.json`을 Airflow 검증이 쉽도록 flat CSV로 펼친 파일 |

표준 GCS 구조는 아래와 같습니다.

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
        query_ranked_candidates/
          query_ranked_candidates.json
          query_ranked_candidates.csv
        docs/
          manifest.json
          description.md
```

데이터셋 패키지로 정식 등록할 때는 processed artifact 내부에 아래 문서 사본을 추가합니다.
안녕하세요 1조 여러분.
데이터 버전관리를 위해 팀 공통으로 지켜야 할 데이터셋 공유 규칙을 전달드립니다.

데이터셋 공유 시 아래 4가지를 같이 준비해주세요.

1. 데이터 파일
2. manifest.json
3. description.md
4. 데이터셋을 다시 만들 수 있는 관련 코드 또는 노트북 경로

자세한 내용은 아래 문서를 참고해주세요.

Git 문서: docs/DATASET_SUBMISSION_GUIDE.md

manifest.json과 description.md는 직접 처음부터 작성하지 않아도 됩니다.

AI에게 docs/DATASET_SUBMISSION_GUIDE.md 파일과 본인 데이터셋 정보를 같이 넣고,

“이 기준에 맞춰 manifest.json과 description.md 초안을 만들어줘. 모르는 값은 TODO로 남겨줘.”

“그리고 final_1_team/docs/GCS_MLOPS_ONBOARDING.md 참고해서 gcs구조도 추천해주라. 내 데이터셋은 어떻게 정리하면 될까.” 

라고 요청하면 됩니다.

단, AI가 만든 결과는 초안입니다.
TODO로 남은 항목은 데이터셋 담당자가 직접 확인해서 채워 넣어야 합니다.
AI가 모르는 값을 추측해서 채우는 것은 금지합니다.

DATASET_SUBMISSION_GUIDE.md에는 공통 manifest.json 형식이 정리되어 있습니다.

공통 필드만 채우고 끝내지 말고, 본인이 담당하는 데이터셋 특징에 맞는 전용 필드도 manifest.json에 추가해주세요.

예:

- SNS 트렌드 데이터셋: platform, crawl_period, text_cleaning, pii_policy, trend_category
- AIHub 이미지 데이터셋: image_processing, category_mapping, retrieval, embedding, faiss_index
- 평가 데이터셋: evaluation_policy, sampling_rule, fixed_seed, metric_target

description.md에는 아래 항목을 포함해주세요.

특히 ★ 표시된 항목은 파일 목록만 보고는 정확히 알 수 없으므로, 최종 공유 전 데이터셋 담당자가 직접 확인해주세요.

1. 데이터셋 목적
2. 파일 목록
3. row/image 개수
4. 용량
5. ★ 원본 출처
6. 데이터 단계(raw / curated / processed)
7. ★ 선별 기준
8. ★ 전처리 기준
9. ★ 생성 스크립트 또는 노트북 경로
10. ★ 현재 한계
11. ★ 다음 버전 계획

큰 데이터 파일은 Git에 올리지 말고 GCS/DVC로 관리합니다.

Git에는 아래 항목만 올립니다.

- manifest.json
- description.md
- 관련 코드 또는 노트북 경로
- DVC pointer 파일(.dvc, dvc.yaml, dvc.lock)

실제 데이터 파일은 GCS/DVC로 관리합니다.

작업하시다가 궁금한 부분이 있다면 저에게 DM 부탁드립니다.
감사합니다.
```text
data/processed/sns_trend/v1/query_ranked_candidates/docs/
  manifest.json
  description.md
```

GCS에 올리는 파일명은 쉘, Airflow, GCS CLI에서 안정적으로 다루기 위해 영어/숫자/underscore 중심으로 정리합니다.
로컬 원본 파일명이 한글을 포함한 경우, GCS 표준 위치에서는 아래처럼 바꿉니다.

| 로컬 원본 파일명 | GCS 표준 파일명 |
| --- | --- |
| `naver_blog_카페.csv` | `naver_blog_cafe.csv` |
| `naver_datalab_카페.csv` | `naver_datalab_cafe.csv` |
| `naver_news_카페.csv` | `naver_news_cafe.csv` |

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
- input platforms: youtube, gogumafarm, careet, naver
- result platforms: gogumafarm, naver, youtube

`query_ranked_candidates.json`은 query와 ranked result를 보존하는 원본 구조입니다.
`query_ranked_candidates.csv`는 Airflow에서 필수 컬럼, score, rank, source, URL 누락 여부 등을 검증하기 쉽게 펼친 flat table입니다.

`input_platforms`는 query ranking 전에 후보로 넣은 플랫폼 전체입니다.
`result_platforms`는 top 결과의 대표 `source`로 실제 등장한 플랫폼입니다.
원본 JSON의 `metadata.also_seen_in`은 특정 밈/키워드가 다른 플랫폼에서도 함께 관측되었음을 나타내는 보조 metadata입니다.
예를 들어 어떤 결과의 대표 `source`가 `gogumafarm`이어도, `metadata.also_seen_in`에 `careet`이 있으면 같은 밈/키워드가 Careet에서도 관측되었다는 뜻입니다.
따라서 Careet은 이번 top result의 대표 source로는 나오지 않았지만, 일부 후보의 `also_seen_in` metadata에는 포함되어 있습니다.

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
