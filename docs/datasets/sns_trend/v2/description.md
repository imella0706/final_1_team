# sns_trend v2 Description

## Summary

`sns_trend v2`는 2026-07-26에 `gather_data/processed/*.json`으로 추가된 `schema_version=2.0` 밈 카드 20개를 `landing`, `curated`, `processed` 단계로 다시 정리한 데이터셋입니다.
이번 버전의 공식 processed 산출물은 `cross_platform_signal_top_candidates`이며, API/RAG/프롬프트 조립에서 바로 읽을 수 있도록 merged JSON과 CSV index를 보존합니다.

## Dataset Stage

- 단계: processed
- 판단 근거: 원본 파일은 이미 `meaning`, `copy_structure`, `usage_rules`, `rights_risk`, `trend_meta`를 가진 구조화 밈 카드입니다. 단순 raw 크롤링 결과가 아닙니다. 따라서 입고 사본은 `landing`에 보존하고, 사람이 검수한 카드 풀은 `curated`, API/프롬프트가 바로 읽는 merged payload는 `processed`로 분리합니다.

## Files

- 주요 파일 목록:
  - `data/landing/sns_trend/week=2026-W30/raw/`
  - `data/curated/sns_trend/v2/meme_cards_reviewed/`
  - `data/processed/sns_trend/v2/cross_platform_signal_top_candidates/cross_platform_signal_top_candidates.json`
  - `data/processed/sns_trend/v2/cross_platform_signal_top_candidates/cross_platform_signal_top_candidates.csv`
- row/image 개수:
  - input JSON card count: 20
  - processed JSON card count: 20
  - image count: none
- 전체 용량:
  - landing: 152,167 bytes
  - curated: 152,167 bytes
  - processed package: 173,648 bytes
- 파일별 역할:
  - `landing/.../raw/<source_family>/`: 2026-07-26에 들어온 파일을 변경 없이 보존하는 입고 사본입니다.
  - `curated/.../meme_cards_reviewed/`: `curation_meta.status=reviewed`인 `schema_version=2.0` 밈 카드 후보 풀입니다.
  - `cross_platform_signal_top_candidates.json`: 전체 카드 20개를 하나의 payload로 묶은 JSON입니다.
  - `cross_platform_signal_top_candidates.csv`: 카드 ID, display name, source family, curation/trend status, source list를 빠르게 검수하기 위한 index입니다.
  - dataset docs: GCS 데이터 패키지 내부에는 두지 않고 `docs/datasets/sns_trend/v2/`에만 보관합니다.

## Source

- 원본 제공처: multiple sources
- 원본 데이터셋 이름: `sns_trend_meme_cards_week_2026-W30`
- 원본 URL:
  - Gogumafarm: `https://gogumafarm.kr/`
  - Careet: `https://contents.premium.naver.com/careets/insight`
  - Naver: 검색 및 데이터랩 공식 API 사용
  - Youtube : Data API v3로 KR mostPopular 스냅샷 → NFKC 정규화 및 중복 영상 제거 후 키워드 출현율 산출, 날짜별 스냅샷 비교로 급상승 키워드 탐지
- 사용 split: none
- 입고 기준일: 2026-07-26
- landing partition: `week=2026-W30`
- partition 판단 기준: v2 추가 입고분의 대표 `trend_meta.collected_week`가 `2026-W30`입니다. 단, 기존 후보에서 이어진 카드 1개는 내부 metadata가 `2026-W28`로 남아 있습니다.
- 시간대 기준: `Asia/Seoul`
- raw 원본 GCS 업로드 여부: 아니오
- 원본 annotation/label 보존 여부: none

## Curation

- 선별 기준: `gather_data/processed/*.json` 중 `schema_version=2.0`, `curation_meta.status=reviewed`, `trend_meta.status=active`인 카드 20개를 v2 후보 풀로 묶었습니다.
- 제외 기준: 이번 작업에서는 제외 파일이 없습니다.
- 카테고리 균형 여부: none
- 원본 경로와 최종 경로 매핑 가능 여부: 가능. `cross_platform_signal_top_candidates.csv`와 아래 mapping을 기준으로 추적합니다.

## Processing

- 입력 데이터셋: `data/curated/sns_trend/v2/meme_cards_reviewed/`
- artifact name: `cross_platform_signal_top_candidates`
- 사용 목적: api, prompt context generation, retrieval input
- 전처리 기준: curated 개별 JSON 카드를 서비스/프롬프트 계층에서 반복 파일 탐색 없이 읽을 수 있도록 merged JSON과 CSV index 형태로 패키징합니다.
- 전처리 단계:
  - reviewed v2 카드 20개를 curated 입력으로 사용
  - 전체 카드를 `cross_platform_signal_top_candidates.json`으로 병합
  - 검수용 `cross_platform_signal_top_candidates.csv` 생성
- 생성 파일:
  - `cross_platform_signal_top_candidates.json`
  - `cross_platform_signal_top_candidates.csv`
- 사용한 모델/도구: Python JSON/CSV packaging
- 모델/평가/검색/API에서 사용하는 방식: 광고 문구 생성과 밈 기반 프롬프트 조립 시 `meme_id`, `display_name`, `meaning`, `copy_structure`, `usage_rules`, `rights_risk`, `trend_meta`를 prompt context로 사용합니다.

## Folder and File Mapping

| 기존 위치 | GCS/표준 위치 | 의미 |
| --- | --- | --- |
| `gather_data/processed/*.json` | `data/landing/sns_trend/week=2026-W30/raw/<source_family>/` | 2026-07-26에 들어온 v2 카드 파일을 변경 없이 보존한 입고 사본 |
| `gather_data/processed/*.json` | `data/curated/sns_trend/v2/meme_cards_reviewed/<source_family>/` | `schema_version=2.0`, `curation_meta.status=reviewed`, `trend_meta.status=active` 조건을 통과한 reviewed 카드 후보 풀 |
| `gather_data/processed/*.json` | `data/processed/sns_trend/v2/cross_platform_signal_top_candidates/cross_platform_signal_top_candidates.json` | 개별 JSON 20개를 하나의 공식 API/RAG/프롬프트 입력 payload로 병합한 JSON |
| `gather_data/processed/*.json` | `data/processed/sns_trend/v2/cross_platform_signal_top_candidates/cross_platform_signal_top_candidates.csv` | merged JSON과 같은 20개 카드의 사람이 검수하기 쉬운 CSV index |
| `gather_data/processed/*.json` | `gs://ssakda/projects/brandmate/data/landing/sns_trend/week=2026-W30/raw/<source_family>/` | GCS landing 업로드 위치 |
| `gather_data/processed/*.json` | `gs://ssakda/projects/brandmate/data/curated/sns_trend/v2/meme_cards_reviewed/<source_family>/` | GCS curated 업로드 위치 |
| `gather_data/processed/*.json` | `gs://ssakda/projects/brandmate/data/processed/sns_trend/v2/cross_platform_signal_top_candidates/` | GCS processed 업로드 위치 |

## Recommended GCS Folder Structure

```text
gs://ssakda/projects/brandmate/data/
  landing/
    sns_trend/
      week=2026-W30/
        raw/
          gogumafarm/
          incross/
          manual/

  curated/
    sns_trend/
      v2/
        meme_cards_reviewed/
          gogumafarm/
          incross/
          manual/

  processed/
    sns_trend/
      v2/
        cross_platform_signal_top_candidates/
          cross_platform_signal_top_candidates.json
          cross_platform_signal_top_candidates.csv
```

## Quality Notes

- 전체 JSON 파일: 20
- `schema_version=2.0`: 20
- `curation_meta.status=reviewed`: 20
- `trend_meta.status=active`: 20
- source family:
  - `gogumafarm`: 2
  - `incross`: 1
  - `manual`: 17
- `trend_meta.collected_week`:
  - `2026-W30`: 19
  - `2026-W28`: 1

여기서 `trend_meta.collected_week=2026-W28`인 카드가 1개 있습니다. 이번 v2 입고분의 대표 주차는 `2026-W30`이므로 landing partition은 `week=2026-W30`으로 유지합니다. 다만 카드 내부 주차가 섞여 있다는 사실은 수정하지 않고 metadata에 노출합니다.

## Storage

- GCS 업로드 예정 경로: `gs://ssakda/projects/brandmate/data/processed/sns_trend/v2/cross_platform_signal_top_candidates/`
- landing GCS 경로: `gs://ssakda/projects/brandmate/data/landing/sns_trend/week=2026-W30/raw/`
- curated GCS 경로: `gs://ssakda/projects/brandmate/data/curated/sns_trend/v2/meme_cards_reviewed/`
- local example path: `data/processed/sns_trend/v2/cross_platform_signal_top_candidates/`
- 기존 로컬 입력 경로: `gather_data/processed/`
- canonical manifest: `docs/datasets/sns_trend/v2/manifest.json`
- canonical description: `docs/datasets/sns_trend/v2/description.md`
- GCS 데이터 패키지 내부 docs 업로드 여부: 아니오
- `gather_data/` 하위 크롤링 runtime 산출물은 Git/GCS 공식 업로드 대상이 아닙니다. v2 공식 데이터셋은 `gather_data/processed/*.json`에서 온 20개 카드를 `data/landing`, `data/curated`, `data/processed`로 재분류한 결과만 기준으로 합니다.

## Reproducibility

- 데이터셋 생성 스크립트 또는 노트북 경로: TODO
- random seed: 없음
- 같은 결과를 다시 만들 수 있는지: 부분 가능. 현재 파일 패키징은 재현 가능하지만, 각 밈 카드의 원본 수집/작성 과정은 별도 스크립트 또는 노트북 경로가 필요합니다. 공식 데이터셋에 포함되지 않은 중간 CSV, PNG, smoke output이 필요하면 크롤러 코드를 다시 실행하거나 원본 작업자(박채빈님)에게 별도로 요청해야 합니다.

## Limitations

- 원본 파일은 reviewed mock card입니다. 플랫폼 raw crawl 전체가 아닙니다.
- 내부 `trend_meta.collected_week`가 20개 중 1개에서 `2026-W28`로 남아 있어, v2 패키지는 `week=2026-W30` 입고분이지만 일부 카드 metadata는 이전 주차를 가리킵니다.
- 원본 URL 증거와 생성 스크립트 경로가 아직 완전히 연결되어 있지 않습니다.
- 현재 processed 산출물은 prompt/API payload입니다. embedding index나 scored ranking artifact는 아닙니다.
- DVC 추적은 아직 켜지지 않았습니다. 공식 DVC 등록은 MLOps/인프라 플로우에서 처리해야 합니다.

## Next Version Plan

- 카드별 원본 URL/evidence를 `source_url` 또는 별도 evidence field로 보강합니다.
- mock card와 verified production card를 분리합니다.
- 실제 retrieval에 사용할 경우 embedding/FAISS 또는 query-ranked artifact를 별도 processed 산출물로 추가합니다.
- `trend_meta.collected_week`와 landing partition 기준을 자동 검증합니다.
