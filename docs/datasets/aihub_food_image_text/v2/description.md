# aihub_food_image_text v2 Description

## Summary

`aihub_food_image_text` v2는 AIHub `비전영역 음식이미지 및 정보소개 텍스트 데이터`의 validation split에서 BrandMate 광고 생성/RAG/API 참고용으로 만든 processed retrieval artifact입니다.

현재 v2의 processed 산출물인 `food_description_data`는 음식 이미지, 메타데이터, 프롬프트용 경량 메타데이터, CLIP embedding, FAISS index, mapping 파일, 운영 검수용 CSV, LLM prompt payload JSON을 함께 묶은 retrieval 패키지입니다.

v2는 baseline `5gb` DB를 그대로 복제한 버전이 아니라, `01`~`08` 단계에서 생성된 base/v1 processed candidate pool과 embedding/FAISS 산출물을 바탕으로 `10`~`15` 단계의 diverse representative pipeline을 적용해 만든 `5gb_v2_diverse` 계열 artifact입니다. 따라서 v2 direct generation path에는 `09_make_final_db.py`를 포함하지 않습니다.

## Dataset Stage

- 판단 단계: `processed`
- 상태: `stable`
- 담당자: `Giwoo`
- 생성일: `2026-07-14`
- 판단 근거: 단순 이미지 subset이 아니라 `metadata.csv`, `metadata.parquet`, `prompt_metadata.csv`, `prompt_metadata.parquet`, `embeddings.npy`, `faiss.index`, `mapping.csv`, `db_management_inventory.csv`, `llm_prompt_payloads.json`을 포함하며 모델/API/RAG 파이프라인에서 바로 읽을 수 있는 구조이므로 processed 단계로 분류합니다.

## Source

- 원본 제공처: `AIHub`
- 원본 데이터셋 ID: `71564`
- 원본 데이터셋 이름: `비전영역 음식이미지 및 정보소개 텍스트 데이터`
- 원본 URL: `https://aihub.or.kr/aihubdata/data/view.do?dataSetSn=71564`
- 사용 split: `validation`
- raw 원본 전체 GCS 업로드 여부: `False`
- 원본 annotation/label 보존 여부: `False`
- 구축 기관 primary: `㈜네스`
- 구축 기관 participants: ㈜씨엔에이아이, ㈜어메이징푸드솔루션

## Existing Local Dataset Folder Analysis

검증에 사용한 기존 로컬 작업 경로는 다음입니다.

```text
C:\aihub-food-ad-rag\data\final_db\5gb_v2_diverse
```

이 경로는 개인 PC의 임시 작업/검증 경로이며, 공식 GCS 경로나 표준 processed 경로로 사용하지 않습니다. 온보딩 규칙에 따른 표준 processed artifact 경로는 다음입니다.

```text
data/processed/aihub_food_image_text/v2/food_description_data/
```

권장 GCS artifact root는 다음입니다.

```text
gs://ssakda/projects/brandmate/data/processed/aihub_food_image_text/v2/food_description_data/
```

artifact 내부 package docs 위치는 artifact root 기준 상대경로로 관리합니다.

```text
docs/manifest.json
docs/description.md
```

## Files

| 파일/폴더 | 확인된 개수/크기 | 역할 |
| --- | ---: | --- |
| `images/` | 1036 files | 최종 retrieval DB에 포함된 음식 reference 이미지 |
| `metadata.csv` | 1036 rows | 최종 DB 마스터 메타데이터 CSV |
| `metadata.parquet` | 1036 rows | 최종 DB 마스터 메타데이터 Parquet |
| `prompt_metadata.csv` | 1036 rows | LLM/RAG context용 경량 메타데이터 CSV |
| `prompt_metadata.parquet` | 1036 rows | LLM/RAG context용 경량 메타데이터 Parquet |
| `embeddings.npy` | shape `(1036, 512)` | 이미지 embedding 배열 |
| `faiss.index` | 1036 vectors | FAISS 검색 index |
| `mapping.csv` | 1036 rows | FAISS index 결과와 이미지/메타데이터 연결 테이블 |
| `summary.json` | 1 file | DB 생성 결과 요약 |
| `db_management_inventory.csv` | 1036 rows | 운영 검수 및 전체 데이터 관리용 inventory CSV |
| `llm_prompt_payloads.json` | 1036 records | LLM prompt context 전달용 JSON payload |

## Curation

- 선별 개수: 1036 images
- 목표 용량: `5.0` GB
- 실제 이미지 용량: `4.440799856558442` GB
- 실제 이미지 용량 bytes: `4768272538`
- 카테고리 균형 여부: `False`
- 원본 경로와 최종 경로 매핑 가능 여부: `True`
- 별도 curated artifact 존재 여부: `False`

선별 기준:

```text
Diverse representative sampling from the AIHub validation processed candidate pool: maximize unique food types, select one front and one side representative per food when available, prefer bbox ratio 0.40-0.70, high center score, high blur score, and high resolution.
```

Sampling policy:

- maximize_unique_food_types
- select_one_front_and_one_side_per_food
- prefer_bbox_ratio_0.40_to_0.70
- prefer_high_center_score
- prefer_high_blur_score
- prefer_high_resolution

품질/대표 이미지 선호 기준:

- prefer bbox ratio 0.40-0.70
- prefer high center score
- prefer high blur score
- prefer high resolution

검증 기준:

- image copy success validation
- path mapping validation

## Processing

- 입력 데이터셋: `AIHub validation selected processed candidate pool`
- artifact name: `food_description_data`
- 사용 목적: `retrieval`

처리 단계:

  - base/v1 metadata normalization
  - base/v1 category mapping
  - base/v1 image quality filtering
  - base/v1 duplicate removal
  - base/v1 caption generation or caption assignment
  - base/v1 CLIP embedding generation
  - base/v1 FAISS index generation
  - diverse representative candidate preparation
  - front and side view representative selection
  - diverse embedding subset build
  - diverse FAISS index generation
  - final DB materialization
  - CSV and Parquet export
  - DB management inventory CSV export
  - LLM prompt payload JSON export

생성 파일:

  - `images/`
  - `metadata.csv`
  - `metadata.parquet`
  - `prompt_metadata.csv`
  - `prompt_metadata.parquet`
  - `embeddings.npy`
  - `faiss.index`
  - `mapping.csv`
  - `summary.json`
  - `db_management_inventory.csv`
  - `llm_prompt_payloads.json`

중요한 구분:

```text
base/v1 processed candidate path: 01_parse_metadata.py through 08_build_faiss.py
v1 baseline DB path: 09_make_final_db.py creates data/final_db/5gb/
v2 diverse path: 10_prepare_diverse_candidates.py through 15_export_final_db_assets.py creates/exports data/final_db/5gb_v2_diverse/
```

## Dataset-Specific Fields

### Image Processing

| Field | Value |
| --- | ---: |
| image_count | 1036 |
| image_size_bytes | 4768272538 |
| image_size_gb | 4.440799856558442 |
| front_image_count | 522 |
| side_image_count | 514 |
| foods_with_front_and_side | 495 |
| foods_with_one_view | 46 |
| copy_failure_count | 0 |

- image directory: `images/`
- original image path column: `image_path`
- final image path column: `final_image_path`

### Representative Sampling

| Field | Value |
| --- | ---: |
| available_representative_count | 1036 |
| final_record_count | 1036 |
| unique_food_count | 541 |
| bbox_40_70_selected_count | 749 |
| bbox_40_70_selected_ratio | 0.722972972972973 |
| average_bbox_ratio | 0.43078611030950403 |
| average_center_score | 0.9436934336120392 |
| average_blur_score | 291.3626430546937 |

### Category Mapping

- business category column: `business_category`
- product group column: `product_group`
- mapping rule: Rule-based mapping inherited from the base/v1 processed candidate pipeline. Exact mapping implementation and version require dataset owner review.

Business category distribution:

| business_category | count |
| --- | ---: |
| restaurant | 590 |
| cafe | 171 |
| bakery | 102 |
| pub | 95 |
| dessert | 78 |

Product group distribution:

| product_group | count |
| --- | ---: |
| korean_food | 216 |
| delivery_food | 133 |
| bread | 72 |
| seafood_side | 57 |
| chicken | 57 |
| brunch | 55 |
| western_food | 51 |
| cake | 46 |
| japanese_food | 44 |
| tea | 41 |
| pizza | 40 |
| coffee | 38 |
| chinese_food | 26 |
| meat_grill | 23 |
| ade_juice | 22 |
| cookie_macaron | 20 |
| fried_side | 18 |
| pastry | 16 |
| smoothie | 15 |
| grilled_side | 13 |
| sandwich | 12 |
| korean_pub_food | 7 |
| ice_cream | 6 |
| shaved_ice | 6 |
| bagel | 2 |

### Embedding

- enabled: `True`
- model: `OpenCLIP ViT-B-32 / openai`
- file: `embeddings.npy`
- shape: `(1036, 512)`
- normalized: `True`

### Retrieval / FAISS

- enabled: `True`
- method: `embedding_search`
- index file: `faiss.index`
- mapping file: `mapping.csv`
- FAISS index type: `IndexFlatIP`
- similarity metric: `inner_product_on_l2_normalized_vectors`
- FAISS index total: `1036`
- mapping count: `1036`

`IndexFlatIP` is used with L2-normalized embeddings, so inner product on normalized vectors is used as the retrieval similarity metric.

### LLM Prompt Payload

- enabled: `True`
- file: `llm_prompt_payloads.json`
- record count: `1036`
- top-level type: `list`
- top-level keys: `database_name`, `reference`, `prompt_context`

## Output Schema

### `metadata.csv`

```text
final_image_id, final_db_row_index, diverse_embedding_id, diverse_embedding_key, representative_id, annotation_path, image_path, json_valid, parse_error, json_file_name, json_stem, source_file_name, original_major_category, original_middle_category, original_sub_category, original_food_name, product_name, food_code, view_group_code, cooking_style_code, situation_code, location_code, image_width, image_height, image_weight, serving_weight, nutrition_g, nutrition_energy, nutrition_cal, nutrition_sugar, ... (109 columns total)
```

### `prompt_metadata.csv`

```text
final_image_id, final_db_row_index, final_image_path, original_food_name, product_name, food_code, business_category, product_group, view_type, caption, prompt_keywords, caption_lighting, caption_composition, caption_camera_angle, ad_use_case, visual_style_hint, bbox_ratio, bbox_40_70_match, center_score, blur_score, resolution_score, representative_score
```

### `mapping.csv`

```text
final_image_id, final_db_row_index, final_image_path, final_image_file_name, faiss_index_id, diverse_embedding_id, diverse_embedding_key, embedding_id, embedding_array_index, representative_id, source_row_index, image_path, relative_image_path, original_food_name, product_name, food_code, business_category, product_group, view_type, bbox_ratio, bbox_40_70_match, center_score, blur_score, resolution_score, quality_score, representative_score, caption, prompt_keywords, embedding_match_method, annotation_path, ... (105 columns total)
```

### `db_management_inventory.csv`

```text
database_name, final_image_id, faiss_index_id, final_image_path, final_image_file_name, image_path, original_food_name, product_name, food_code, business_category, product_group, view_type, bbox_ratio, bbox_40_70_match, center_score, blur_score, actual_width, actual_height, representative_score, caption, prompt_keywords, caption_lighting, caption_composition, caption_camera_angle, ad_use_case, visual_style_hint, final_db_row_index, diverse_embedding_id, diverse_embedding_key, representative_id, ... (111 columns total)
```

### `llm_prompt_payloads.json`

```text
database_name, reference, prompt_context
```

## Statistics

- image file count: `1036`
- record count: `1036`
- embedding shape: `(1036, 512)`
- actual image size: `4.440799856558442` GB
- unique food name count: `541`

## Recommended GCS Folder Structure Draft

`manifest.json` 기준 GCS 경로에는 아래 표준 processed artifact 구조를 사용합니다.

```text
gs://ssakda/projects/brandmate/data/processed/aihub_food_image_text/v2/food_description_data/
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

| 기존 로컬/표준 경로 | 추천 GCS/표준 경로 | 파일 역할 |
| --- | --- | --- |
| `data/processed/aihub_food_image_text/v2/food_description_data/images/` | `gs://ssakda/projects/brandmate/data/processed/aihub_food_image_text/v2/food_description_data/images/` | 최종 음식 reference 이미지 |
| `data/processed/aihub_food_image_text/v2/food_description_data/metadata.csv` | `gs://ssakda/projects/brandmate/data/processed/aihub_food_image_text/v2/food_description_data/metadata.csv` | 최종 DB 마스터 메타데이터 CSV |
| `data/processed/aihub_food_image_text/v2/food_description_data/metadata.parquet` | `gs://ssakda/projects/brandmate/data/processed/aihub_food_image_text/v2/food_description_data/metadata.parquet` | 최종 DB 마스터 메타데이터 Parquet |
| `data/processed/aihub_food_image_text/v2/food_description_data/prompt_metadata.csv` | `gs://ssakda/projects/brandmate/data/processed/aihub_food_image_text/v2/food_description_data/prompt_metadata.csv` | LLM/RAG 프롬프트용 경량 메타데이터 CSV |
| `data/processed/aihub_food_image_text/v2/food_description_data/prompt_metadata.parquet` | `gs://ssakda/projects/brandmate/data/processed/aihub_food_image_text/v2/food_description_data/prompt_metadata.parquet` | LLM/RAG 프롬프트용 경량 메타데이터 Parquet |
| `data/processed/aihub_food_image_text/v2/food_description_data/embeddings.npy` | `gs://ssakda/projects/brandmate/data/processed/aihub_food_image_text/v2/food_description_data/embeddings.npy` | CLIP 이미지 embedding 배열 |
| `data/processed/aihub_food_image_text/v2/food_description_data/faiss.index` | `gs://ssakda/projects/brandmate/data/processed/aihub_food_image_text/v2/food_description_data/faiss.index` | FAISS 검색 index |
| `data/processed/aihub_food_image_text/v2/food_description_data/mapping.csv` | `gs://ssakda/projects/brandmate/data/processed/aihub_food_image_text/v2/food_description_data/mapping.csv` | FAISS 검색 결과와 이미지/메타데이터 연결 테이블 |
| `data/processed/aihub_food_image_text/v2/food_description_data/summary.json` | `gs://ssakda/projects/brandmate/data/processed/aihub_food_image_text/v2/food_description_data/summary.json` | DB 생성 결과 요약 |
| `data/processed/aihub_food_image_text/v2/food_description_data/db_management_inventory.csv` | `gs://ssakda/projects/brandmate/data/processed/aihub_food_image_text/v2/food_description_data/db_management_inventory.csv` | 운영 검수 및 전체 데이터 관리용 inventory CSV |
| `data/processed/aihub_food_image_text/v2/food_description_data/llm_prompt_payloads.json` | `gs://ssakda/projects/brandmate/data/processed/aihub_food_image_text/v2/food_description_data/llm_prompt_payloads.json` | LLM prompt context 전달용 JSON payload |
| `docs/datasets/aihub_food_image_text/v2/manifest.json` | `gs://ssakda/projects/brandmate/data/processed/aihub_food_image_text/v2/food_description_data/docs/manifest.json` | artifact package manifest 사본 |
| `docs/datasets/aihub_food_image_text/v2/description.md` | `gs://ssakda/projects/brandmate/data/processed/aihub_food_image_text/v2/food_description_data/docs/description.md` | artifact package description 사본 |

## Storage

- GCS path: `gs://ssakda/projects/brandmate/data/processed/aihub_food_image_text/v2/food_description_data/`
- local example path: `data/processed/aihub_food_image_text/v2/food_description_data/`
- recommended standard path: `data/processed/aihub_food_image_text/v2/food_description_data/`
- package docs manifest path: `docs/manifest.json`
- package docs description path: `docs/description.md`
- DVC tracking 여부: `TODO`

중앙 `data/manifests/` 사본은 이 문서에서 선언하지 않습니다. package docs는 artifact 내부 `docs/manifest.json`, `docs/description.md` 위치를 기준으로 관리합니다.

## Reproducibility

- generation script available: `True`
- random seed: `42`
- seed setup path: `C:\aihub-food-ad-rag\src\utils\reproducibility.py`
- can rebuild: `True`

생성 스크립트 경로:

- `C:\aihub-food-ad-rag\src\01_parse_metadata.py`
- `C:\aihub-food-ad-rag\src\02_eda_report.py`
- `C:\aihub-food-ad-rag\src\03_build_category_groups.py`
- `C:\aihub-food-ad-rag\src\04_quality_filter.py`
- `C:\aihub-food-ad-rag\src\05_remove_duplicates.py`
- `C:\aihub-food-ad-rag\src\06_caption_tagging.py`
- `C:\aihub-food-ad-rag\src\07_clip_embedding.py`
- `C:\aihub-food-ad-rag\src\08_build_faiss.py`
- `C:\aihub-food-ad-rag\src\10_prepare_diverse_candidates.py`
- `C:\aihub-food-ad-rag\src\11_select_diverse_representatives.py`
- `C:\aihub-food-ad-rag\src\12_build_diverse_embedding_subset.py`
- `C:\aihub-food-ad-rag\src\13_build_diverse_faiss.py`
- `C:\aihub-food-ad-rag\src\14_make_diverse_final_db.py`
- `C:\aihub-food-ad-rag\src\15_export_final_db_assets.py`

v2 direct generation path에서는 `09_make_final_db.py`를 제외합니다. `09_make_final_db.py`는 baseline `5gb` DB 생성용이며, v2는 `01`~`08`의 base processed candidate 산출물을 기반으로 `10`~`15` 단계를 실행합니다.

## Limitations

- Category distribution was not intentionally balanced for BrandMate target domains.
- Restaurant remains the largest business category in the observed v2 distribution.
- Original AIHub annotation files were not preserved in this artifact.
- Exact embedding model, normalization policy, similarity metric, and rebuild determinism require dataset owner review.

## Next Version Plan

Evaluate retrieval quality metrics such as Hits@5, Recall@5, and MRR for candidate bbox ratio policies, then promote the best representative sampling policy to the next stable dataset version.

## Dataset Owner Review Checklist

- `storage.dvc_tracked`를 `.dvc` pointer 생성 이후 확정해야 합니다.
- `category_mapping.mapping_rule`이 팀 handoff에 충분한 수준인지 데이터셋 담당자가 최종 검수해야 합니다.
- `limitations`와 `next_version_plan`은 최종 등록 전 데이터셋 담당자가 직접 검수해야 합니다.
- 실제 GCS 업로드 후 artifact 내부 `docs/manifest.json`, `docs/description.md` 사본이 이 canonical 문서와 일치하는지 확인해야 합니다.
