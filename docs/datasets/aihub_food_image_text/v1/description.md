# aihub_food_image_text v1 Description

## Summary

`aihub_food_image_text`는 AIHub `비전영역 음식이미지 및 정보소개 텍스트 데이터`의 validation split에서 만든 baseline processed retrieval dataset입니다.

이 데이터셋은 BrandMate의 검색/RAG/API 참고 데이터로 사용할 수 있도록 음식 이미지, 메타데이터, 프롬프트용 메타데이터, embedding, FAISS index, mapping 파일, 운영 검수용 CSV, LLM prompt payload JSON을 함께 묶은 패키지입니다.

현재 문서는 `manifest.json`에 확정된 값을 기준으로 작성하며, 데이터셋 담당자와 MLOps 담당자가 최종 검수해야 하는 항목은 마지막 검수 체크리스트에 별도로 정리합니다.

## Dataset Stage

- 판단 단계: `processed`
- 판단 근거: 이 데이터셋은 단순 선별 이미지 폴더가 아니라 `metadata.parquet`, `prompt_metadata.parquet`, `embeddings.npy`, `faiss.index`, `mapping.csv`, `llm_prompt_payloads.json`을 포함합니다.
- 온보딩 기준상 embedding 생성, FAISS index 생성, RAG/LLM 입력용 변환 결과는 모델/API/검색 파이프라인이 바로 소비하는 산출물이므로 `processed` 단계로 판단합니다.

## Source

- 원본 제공처: AIHub
- 원본 데이터셋 ID: `71564`
- 원본 데이터셋 이름: `비전영역 음식이미지 및 정보소개 텍스트 데이터`
- 원본 URL: `https://aihub.or.kr/aihubdata/data/view.do?dataSetSn=71564`
- 사용 split: `validation`
- raw 원본 전체 GCS 업로드 여부: false
- 원본 annotation/label 보존 여부: false
- 구축 기관: `㈜네스`, `㈜씨엔에이아이`, `㈜어메이징푸드솔루션`

## Existing Local Dataset Folder Analysis

분석한 기존 데이터셋 폴더는 다음입니다.

```text
data/processed/aihub_food_image_text/v1/food_description_data
```

확인된 파일 구조는 다음입니다.

```text
food_description_data/
├── images/
├── db_management_inventory.csv
├── embeddings.npy
├── faiss.index
├── llm_prompt_payloads.json
├── mapping.csv
├── metadata.csv
├── metadata.parquet
├── prompt_metadata.csv
├── prompt_metadata.parquet
└── summary.json
```

## Files

| 파일/폴더 | 확인된 개수/크기 | 역할 |
| --- | ---: | --- |
| `images/` | 952 files | 최종 retrieval DB에 포함된 음식 이미지 |
| `metadata.csv` | 952 rows / 17 columns | 최종 DB 마스터 메타데이터 CSV |
| `metadata.parquet` | 96,783 bytes | 최종 DB 마스터 메타데이터 Parquet |
| `prompt_metadata.csv` | 952 rows / 12 columns | LLM/RAG context용 경량 메타데이터 CSV |
| `prompt_metadata.parquet` | 90,357 bytes | LLM/RAG context용 경량 메타데이터 Parquet |
| `embeddings.npy` | 1,949,824 bytes | 이미지 embedding 배열, shape `(952, 512)` |
| `faiss.index` | 1,949,741 bytes | FAISS 검색 index |
| `mapping.csv` | 952 rows / 15 columns | FAISS index 결과와 이미지/메타데이터 연결 테이블 |
| `summary.json` | 1,143 bytes | DB 생성 결과 요약 |
| `db_management_inventory.csv` | 952 rows / 21 columns | 운영 검수/관리용 inventory CSV |
| `llm_prompt_payloads.json` | 952 records | LLM prompt context 전달용 JSON payload |

## Curation

- 선별 개수: 952 images
- 목표 용량: `target_size_gb = 5.0`
- 실제 이미지 용량: 약 4.998GB
- 실제 이미지 용량 bytes: 5,366,508,606
- 카테고리 균형 여부: false
- 원본 경로와 최종 경로 매핑 가능 여부: true
- 선별 기준: Selected from AIHub validation split until approximately 5GB after quality filtering.

확인된 품질 필터 또는 처리 기준은 다음입니다.

- blur score filtering
- low-resolution image filtering
- pHash duplicate filtering
- CLIP similarity duplicate filtering

이미지 존재 여부와 열기 가능 여부는 `image existence/open validation`으로 별도 validation check에 기록합니다.

## Processing

- 입력 데이터셋: AIHub validation selected subset
- artifact name: `food_description_data`
- 사용 목적: retrieval, prompt context generation, API reference data
- 처리 내용:
  - metadata normalization
  - category mapping
  - image quality filtering
  - duplicate removal
  - caption generation or caption assignment
  - CLIP embedding generation
  - FAISS index generation
  - CSV and Parquet export
- 후처리/export 내용:
  - DB management inventory CSV export
  - LLM prompt payload JSON export

## Dataset-Specific Fields

### Image Processing

- image count: 952
- image directory: `images/`
- image size: 약 4.998GB
- source image path column: `image_path`
- final image path column: `final_image_path`

### Category Mapping

- business category column: `business_category`
- product group column: `product_group`
- mapping rule: Rule-based mapping using `configs/category_map.yaml` and `src/03_build_category_groups.py`. Keyword rules are built from `service_category_schema.business_categories.*.product_groups.*.keywords`, sorted by keyword length in descending order, and matched against the combined `product_name`, `original_food_name`, and `food_code` text. The script then applies food-name based manual override and fallback-reduction rules, and remaining unmapped rows fall back to `restaurant` / `delivery_food` according to `unmapped_policy`.

Business category distribution:

| category | count |
| --- | ---: |
| restaurant | 276 |
| dessert | 175 |
| bakery | 174 |
| cafe | 165 |
| pub | 162 |

Product group distribution:

| product_group | count |
| --- | ---: |
| chicken | 272 |
| cake | 175 |
| bread | 164 |
| fried_side | 127 |
| brunch | 124 |
| ade_juice | 40 |
| grilled_side | 35 |
| bagel | 9 |
| japanese_food | 2 |
| delivery_food | 1 |
| pizza | 1 |
| tea | 1 |
| pastry | 1 |

### Embedding

- enabled: true
- file: `embeddings.npy`
- shape: `(952, 512)`
- model: `OpenCLIP ViT-B-32 pretrained=openai`
- normalized: true

### Retrieval / FAISS

- enabled: true
- method: embedding search
- index file: `faiss.index`
- mapping file: `mapping.csv`
- FAISS index type: `IndexFlatIP`
- similarity metric: `inner_product_on_normalized_embeddings`

### LLM Prompt Payload

- enabled: true
- file: `llm_prompt_payloads.json`
- record count: 952
- top-level type: list
- observed top-level keys:
  - `database_name`
  - `reference`
  - `prompt_context`

## Output Schema

### `metadata.csv`

```text
final_image_id, embedding_id, source_row_index, image_path, original_food_name, product_name, food_code, business_category, product_group, caption, prompt_keywords, text_for_embedding, embedding_array_index, final_image_size_bytes, final_image_exists, final_image_file_name, final_image_path
```

### `prompt_metadata.csv`

```text
final_image_id, final_image_path, business_category, product_group, product_name, original_food_name, food_code, caption, prompt_keywords, text_for_embedding, retrieval_text, ad_prompt_hint
```

### `mapping.csv`

```text
faiss_index_id, final_image_id, embedding_id, embedding_array_index, final_image_path, final_image_file_name, image_path, original_food_name, product_name, food_code, business_category, product_group, caption, prompt_keywords, text_for_embedding
```

### `db_management_inventory.csv`

```text
database_name, final_image_id, faiss_index_id, final_image_path, final_image_file_name, image_path, original_food_name, product_name, food_code, business_category, product_group, caption, prompt_keywords, text_for_embedding, retrieval_text, ad_prompt_hint, embedding_id, source_row_index, embedding_array_index, final_image_size_bytes, final_image_exists
```

### `llm_prompt_payloads.json`

확인된 구조:

```text
list[record]
record keys: database_name, reference, prompt_context
```

## Statistics

- image file count: 952
- record count: 952
- embedding shape: `(952, 512)`
- actual image size: 약 4.998GB
- unique food name count: 88

## Recommended GCS Folder Structure Draft

`manifest.json` 기준 GCS 경로는 아래 표준 processed artifact 경로를 사용합니다.

표준 구조 초안은 다음과 같습니다.

```text
gs://ssakda/projects/brandmate/data/processed/aihub_food_image_text/v1/food_description_data/
├── images/
├── metadata.csv
├── metadata.parquet
├── prompt_metadata.csv
├── prompt_metadata.parquet
├── embeddings.npy
├── faiss.index
├── mapping.csv
├── summary.json
├── db_management_inventory.csv
├── llm_prompt_payloads.json
└── docs/
    ├── manifest.json
    └── description.md
```

## Local Path to Recommended Standard Path Mapping

| 기존 로컬 경로 | 추천 GCS/표준 경로 | 파일 역할 |
| --- | --- | --- |
| `data/processed/aihub_food_image_text/v1/food_description_data/images\` | `gs://ssakda/projects/brandmate/data/processed/aihub_food_image_text/v1/food_description_data/images/` | 최종 음식 이미지 |
| `data/processed/aihub_food_image_text/v1/food_description_data/metadata.csv` | `gs://ssakda/projects/brandmate/data/processed/aihub_food_image_text/v1/food_description_data/metadata.csv` | 마스터 메타데이터 CSV |
| `data/processed/aihub_food_image_text/v1/food_description_data/metadata.parquet` | `gs://ssakda/projects/brandmate/data/processed/aihub_food_image_text/v1/food_description_data/metadata.parquet` | 마스터 메타데이터 Parquet |
| `data/processed/aihub_food_image_text/v1/food_description_data/prompt_metadata.csv` | `gs://ssakda/projects/brandmate/data/processed/aihub_food_image_text/v1/food_description_data/prompt_metadata.csv` | 프롬프트용 메타데이터 CSV |
| `data/processed/aihub_food_image_text/v1/food_description_data/prompt_metadata.parquet` | `gs://ssakda/projects/brandmate/data/processed/aihub_food_image_text/v1/food_description_data/prompt_metadata.parquet` | 프롬프트용 메타데이터 Parquet |
| `data/processed/aihub_food_image_text/v1/food_description_data/embeddings.npy` | `gs://ssakda/projects/brandmate/data/processed/aihub_food_image_text/v1/food_description_data/embeddings.npy` | 이미지 embedding 배열 |
| `data/processed/aihub_food_image_text/v1/food_description_data/faiss.index` | `gs://ssakda/projects/brandmate/data/processed/aihub_food_image_text/v1/food_description_data/faiss.index` | FAISS 검색 index |
| `data/processed/aihub_food_image_text/v1/food_description_data/mapping.csv` | `gs://ssakda/projects/brandmate/data/processed/aihub_food_image_text/v1/food_description_data/mapping.csv` | 검색 결과 매핑 테이블 |
| `data/processed/aihub_food_image_text/v1/food_description_data/summary.json` | `gs://ssakda/projects/brandmate/data/processed/aihub_food_image_text/v1/food_description_data/summary.json` | 생성 결과 요약 |
| `data/processed/aihub_food_image_text/v1/food_description_data/db_management_inventory.csv` | `gs://ssakda/projects/brandmate/data/processed/aihub_food_image_text/v1/food_description_data/db_management_inventory.csv` | 운영 검수용 inventory |
| `data/processed/aihub_food_image_text/v1/food_description_data/llm_prompt_payloads.json` | `gs://ssakda/projects/brandmate/data/processed/aihub_food_image_text/v1/food_description_data/llm_prompt_payloads.json` | LLM prompt payload |
| `docs/datasets/aihub_food_image_text/v1/manifest.json` | `gs://ssakda/projects/brandmate/data/processed/aihub_food_image_text/v1/food_description_data/docs/manifest.json` | 데이터셋 manifest |
| `docs/datasets/aihub_food_image_text/v1/description.md` | `gs://ssakda/projects/brandmate/data/processed/aihub_food_image_text/v1/food_description_data/docs/description.md` | 데이터셋 설명 문서 |

## Storage

- GCS 업로드 예정 경로: `gs://ssakda/projects/brandmate/data/processed/aihub_food_image_text/v1/food_description_data/`
- local example path: `data/processed/aihub_food_image_text/v1/food_description_data/`
- recommended standard path: `data/processed/aihub_food_image_text/v1/food_description_data/`
- DVC tracking 여부: true

DVC tracking 상태는 `manifest.json` 기준 `true`입니다.

## Reproducibility

확인된 생성 관련 스크립트 경로는 다음입니다.

- `C:\aihub-food-ad-rag\src\01_parse_metadata.py`
- `C:\aihub-food-ad-rag\src\02_eda_report.py`
- `C:\aihub-food-ad-rag\src\03_build_category_groups.py`
- `C:\aihub-food-ad-rag\src\04_quality_filter.py`
- `C:\aihub-food-ad-rag\src\05_remove_duplicates.py`
- `C:\aihub-food-ad-rag\src\06_caption_tagging.py`
- `C:\aihub-food-ad-rag\src\07_clip_embedding.py`
- `C:\aihub-food-ad-rag\src\08_build_faiss.py`
- `C:\aihub-food-ad-rag\src\09_make_final_db.py`
- `C:\aihub-food-ad-rag\src\15_export_final_db_assets.py`

- random seed: 42
- 같은 결과를 다시 만들 수 있는지: `partial`

## Limitations

- Category distribution was not intentionally balanced for BrandMate target domains.
- Cafe and bakery scenarios may require more cake, dessert, bakery, beverage, and brunch images.
- Dataset was created under time constraints using approximately 5GB target size.
- Original AIHub annotation files were not preserved in this artifact.

## Next Version Plan

Use the verified diverse follow-up artifact as the next-version direction: maximize unique food types, select one front and one side representative per food when available, prefer bbox ratio 0.40-0.70, high center score, high blur score, and high resolution; observed follow-up summary has 1036 records, 541 unique foods, 522 front images, 514 side images, 495 foods with both views, and 749 records (72.30%) in the bbox 0.40-0.70 range.

## Dataset Owner Review Checklist

- `curation.selection_policy`는 `manifest.json` 기준 값으로 반영했으며, 담당자 최종 검수를 권장합니다.
- `category_mapping.mapping_rule`은 `manifest.json` 기준 값으로 반영했으며, 담당자 최종 검수를 권장합니다.
- `embedding.model`은 `manifest.json` 기준 값으로 반영했습니다.
- `embedding.normalized`는 `manifest.json` 기준 값으로 반영했습니다.
- `retrieval.faiss_index_type`은 `manifest.json` 기준 값으로 반영했습니다.
- `retrieval.similarity_metric`은 `manifest.json` 기준 값으로 반영했습니다.
- `storage.gcs_path`는 `manifest.json` 기준 값으로 반영했습니다.
- `storage.dvc_tracked`는 `manifest.json` 기준 값으로 반영했습니다.
- `reproducibility.random_seed`는 `manifest.json` 기준 값으로 반영했습니다.
- `reproducibility.can_rebuild`는 `manifest.json` 기준 값으로 반영했습니다.
- `limitations`는 `manifest.json` 기준 값으로 반영했으며, 담당자 최종 검수를 권장합니다.
- `next_version_plan`은 `manifest.json` 기준 값으로 반영했으며, 담당자 최종 검수를 권장합니다.


