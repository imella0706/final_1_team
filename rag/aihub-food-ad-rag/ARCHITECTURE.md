# Architecture

## 목적

이 프로젝트는 AI Hub 음식 이미지 데이터를 광고 콘텐츠 생성 AI가 참조할 수 있는 Retrieval DB로 변환한다. 최종 산출물은 이미지 파일, 메타데이터, 프롬프트용 메타데이터, CLIP 임베딩, FAISS 인덱스를 포함한다.

## 전체 흐름

```text
AI Hub Validation Dataset
  -> 01_parse_metadata.py
  -> 02_eda_report.py
  -> 03_build_category_groups.py
  -> 04_quality_filter.py
  -> 05_remove_duplicates.py
  -> 06_caption_tagging.py
  -> 07_clip_embedding.py
  -> 08_build_faiss.py
  -> 09_make_final_db.py
  -> 10_prepare_diverse_candidates.py
  -> 11_select_diverse_representatives.py
  -> 12_build_diverse_embedding_subset.py
  -> 13_build_diverse_faiss.py
  -> 14_make_diverse_final_db.py
  -> 15_export_final_db_assets.py
  -> final_db
```

## Layer 구성

### Data Ingestion Layer

입력:

```text
data/raw/images/
data/raw/annotations/
```

역할:

- JSON 어노테이션 파싱
- 이미지 파일 매칭
- 음식명, 음식 코드, 영양정보, 이미지 크기 추출
- `raw_metadata.parquet` 생성

### Data Processing Layer

역할:

- EDA 리포트 생성
- 업종/상품군 매핑
- 이미지 품질 필터링
- pHash 기반 중복 제거
- BLIP 기반 캡션 및 시각 태그 생성

주요 산출물:

```text
data/metadata/raw_metadata.parquet
data/metadata/category_enriched_metadata.parquet
data/metadata/quality_filtered_metadata.parquet
data/metadata/deduplicated_metadata.parquet
data/metadata/tagged_metadata.parquet
```

### Embedding & Indexing Layer

역할:

- OpenCLIP 이미지 임베딩 생성
- FAISS IndexFlatIP 인덱스 생성
- 임베딩과 메타데이터 연결

주요 산출물:

```text
data/embeddings/image_embeddings.npy
data/embeddings/embedding_metadata.parquet
data/embeddings/faiss.index
data/embeddings/faiss_mapping.csv
```


### Reproducibility Layer

`src/utils/reproducibility.py` is the shared seed utility called by the v2 generation path scripts `01`~`08` and `10`~`15`.

```text
DEFAULT_RANDOM_SEED = 42
```

It sets Python `random`, NumPy, PyTorch, CUDA seeds and deterministic options on a best-effort basis. The v2 `can_rebuild=true` statement assumes this seed setup plus the same input data, intermediate artifacts, dependency versions, and local path layout.

### Final DB Layer

역할:

- 검색 API에서 바로 사용할 DB 패키지 생성
- DB 버전별 이미지, 메타데이터, 임베딩, FAISS 인덱스 저장
- DB별 `summary.json` 저장
- 전체 DB 루트에 `final_db_summary.json` 저장
- 관리용 CSV와 LLM 전달용 JSON 생성

현재 완성 DB:

```text
data/final_db/processed\aihub_food_image_text\v1\food_description_data/
data/final_db/processed\aihub_food_image_text\v2\food_description_data/
```

설계만 준비된 폴더:

```text
data/final_db/10gb/
data/final_db/20gb/
```

### Application Layer

```text
app/retrieval_api.py
app/prompt_rag.py
```

역할:

- DB 로드
- 카테고리 조회
- 유사 이미지 검색
- 검색 결과를 광고 프롬프트용 reference context로 변환

## 현재 검색 구조

현재 API는 CLIP text encoder를 직접 쓰는 텍스트-이미지 검색이 아니다. 입력 텍스트는 메타데이터 필터링에 사용되고, 필터링된 후보 이미지들의 평균 임베딩을 대표 query vector로 사용한다.

향후 개선 방향은 CLIP text embedding 또는 BM25 + Vector Hybrid Search를 추가하는 것이다.

## Diverse DB 생성 단계

다양성 기반 DB는 10~14단계로 생성된다.

| 단계 | 파일 | 역할 |
|---|---|---|
| 10 | `10_prepare_diverse_candidates.py` | Bounding Box, 중앙성, view_type, representative_score 생성 |
| 11 | `11_select_diverse_representatives.py` | 음식별 정위/측면 대표 이미지 선택 |
| 12 | `12_build_diverse_embedding_subset.py` | 선택 대표 이미지에 해당하는 임베딩 subset 생성 |
| 13 | `13_build_diverse_faiss.py` | diverse subset 전용 FAISS 인덱스 생성 |
| 14 | `14_make_diverse_final_db.py` | `processed\aihub_food_image_text\v2\food_description_data` 최종 DB 패키징 |
| 15 | `15_export_final_db_assets.py` | 관리용 CSV, LLM JSON, 루트 master summary 생성 |

## DB 요약 파일 정책

각 DB 폴더에는 개별 요약 파일을 둔다.

```text
summary.json
```

전체 DB 버전 목록과 생성 요약은 루트 파일에서 관리한다.

```text
data/final_db/final_db_summary.json
```

`src/15_export_final_db_assets.py`는 `processed\aihub_food_image_text\v1\food_description_data`, `processed\aihub_food_image_text\v2\food_description_data` 등 완성 DB 폴더를 읽어 루트 `final_db_summary.json`을 갱신한다.
