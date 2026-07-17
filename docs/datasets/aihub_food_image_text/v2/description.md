# aihub_food_image_text v2 Description

## Summary

`aihub_food_image_text` v2는 '비전영역 음식이미지 및 정보소개 텍스트 데이터'의 AIHub 검증 분할에서 파생된 처리된 검색 아티팩트입니다.

이 패키지는 BrandMate RAG/API 참조용으로 설계되었습니다. 여기에는 음식 이미지, 마스터 메타데이터, 프롬프트 지향 메타데이터, CLIP 임베딩, FAISS 인덱스, 매핑 파일, 운영 인벤토리 CSV 및 LLM 프롬프트 페이로드 JSON이 포함되어 있습니다.

v2 아티팩트는 '5gb_v2_diverse' 데이터베이스를 설명합니다. 최종 기준 '5gb' DB의 직접적인 연속은 아닙니다. 대신, 스크립트 '01'~'08'에서 생성된 베이스/v1 처리 후보 풀과 임베딩/FAISS 아티팩트를 사용한 후, 스크립트 '10'~'15'를 통해 다양한 대표 DB를 재구성합니다.

## Dataset Stage

- Dataset stage: `processed`
- Status: `stable`
- Owner: `Giwoo`
- Created at: `2026-07-14`

This artifact is classified as `processed` because it is not only a selected image folder. It includes normalized metadata, prompt metadata, embeddings, a FAISS index, mapping files, and JSON/CSV exports that can be consumed directly by model/API/RAG pipelines.

## Source

- Provider: `AIHub`
- Source dataset ID: `71564`
- Source dataset name: `비전영역 음식이미지 및 정보소개 텍스트 데이터`
- Source URL: `https://aihub.or.kr/aihubdata/data/view.do?dataSetSn=71564`
- Source split: `validation`
- Raw uploaded to GCS: `False`
- Original annotation preserved in this artifact: `False`
- Builder primary: `㈜네스`
- Builder participants: ㈜씨엔에이아이, ㈜어메이징푸드솔루션

## Existing Local Dataset Folder Analysis

Local source artifact used for validation:

```text
C:\aihub-food-ad-rag\data\final_db\5gb_v2_diverse
```

This is a local working path and should not be treated as the official storage path. The standard processed artifact path is:

```text
data/processed/aihub_food_image_text/v2/food_description_data/
```

Recommended GCS artifact root:

```text
gs://ssakda/projects/brandmate/data/processed/aihub_food_image_text/v2/food_description_data/
```

Package docs are stored relative to the artifact root:

```text
docs/manifest.json
docs/description.md
```

## Files

The artifact contains the following output files according to the manifest:

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

### File Roles

| File or folder | Role |
| --- | --- |
| `images/` | Food reference images included in the final retrieval DB. |
| `metadata.csv` / `metadata.parquet` | Master metadata for final DB records. |
| `prompt_metadata.csv` / `prompt_metadata.parquet` | Lightweight prompt/RAG context metadata. |
| `embeddings.npy` | CLIP image embedding array. |
| `faiss.index` | FAISS vector index for image embedding retrieval. |
| `mapping.csv` | Mapping between FAISS ids, image paths, food names, and metadata fields. |
| `summary.json` | Per-DB generation summary. |
| `db_management_inventory.csv` | Human-readable operational inventory for DB inspection. |
| `llm_prompt_payloads.json` | JSON payloads for LLM prompt/RAG context generation. |

## Curation

- Selected count: `1036` images
- Target size: `5.0` GB
- Actual image size: `4.440799856558442` GB
- Actual image size bytes: `4768272538`
- Category balanced: `False`
- Path mapping available: `True`
- Separate curated artifact exists: `False`

Selection policy:

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

Quality preference rules:

- prefer bbox ratio 0.40-0.70
- prefer high center score
- prefer high blur score
- prefer high resolution

Validation checks:

- image copy success validation
- path mapping validation

## Processing

- Input dataset: `AIHub validation selected processed candidate pool`
- Artifact name: `food_description_data`
- Target use: `retrieval`

Processing steps:

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

Important distinction:

```text
v1/base path: 01_parse_metadata.py through 08_build_faiss.py
v1 baseline DB path: 09_make_final_db.py creates data/final_db/5gb/
v2 diverse path: 10_prepare_diverse_candidates.py through 15_export_final_db_assets.py creates/exports data/final_db/5gb_v2_diverse/
```

## Image Processing

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

- Image directory: `images/`
- Original image path column: `image_path`
- Final image path column: `final_image_path`

## Representative Sampling

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

## Category Mapping

- Business category column: `business_category`
- Product group column: `product_group`
- Mapping rule: Rule-based mapping inherited from the base/v1 processed candidate pipeline. Exact mapping implementation and version require dataset owner review.

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

## Embedding

- Enabled: `True`
- Model: `OpenCLIP ViT-B-32 / openai`
- File: `embeddings.npy`
- Shape: `(1036, 512)`
- Normalized: `True`

## Retrieval / FAISS

- Enabled: `True`
- Method: `embedding_search`
- Index file: `faiss.index`
- Mapping file: `mapping.csv`
- FAISS index type: `IndexFlatIP`
- Similarity metric: `inner_product_on_l2_normalized_vectors`
- FAISS index total: `1036`
- Mapping count: `1036`

`IndexFlatIP` is used with L2-normalized embeddings, so inner product on normalized vectors is used as the retrieval similarity metric.

## LLM Prompt Payload

- Enabled: `True`
- File: `llm_prompt_payloads.json`
- Record count: `1036`
- Top-level type: `list`
- Top-level keys: ['database_name', 'reference', 'prompt_context']

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

- Image file count: `1036`
- Record count: `1036`
- Embedding shape: `(1036, 512)`
- Unique food name count: `541`

## Storage

- GCS path: `gs://ssakda/projects/brandmate/data/processed/aihub_food_image_text/v2/food_description_data/`
- Local example path: `data/processed/aihub_food_image_text/v2/food_description_data/`
- Recommended standard path: `data/processed/aihub_food_image_text/v2/food_description_data/`
- Package docs manifest path: `docs/manifest.json`
- Package docs description path: `docs/description.md`
- DVC tracked: `TODO`

No central `data/manifests/` copy is declared in this document.

## Reproducibility

- Generation script available: `True`
- Random seed: `42`
- Seed setup path: `C:\aihub-food-ad-rag\src\utils\reproducibility.py`
- Can rebuild: `True`

Generation script path:

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

The v2 direct generation path excludes `09_make_final_db.py`. Script `09_make_final_db.py` is used for the baseline `5gb` DB, while v2 uses outputs from `01`~`08` and then runs `10`~`15`.

## Limitations

- Category distribution was not intentionally balanced for BrandMate target domains.
- Restaurant remains the largest business category in the observed v2 distribution.
- Original AIHub annotation files were not preserved in this artifact.
- Exact embedding model, normalization policy, similarity metric, and rebuild determinism require dataset owner review.

## Next Version Plan

Evaluate retrieval quality metrics such as Hits@5, Recall@5, and MRR for candidate bbox ratio policies, then promote the best representative sampling policy to the next stable dataset version.

## Dataset Owner Review Checklist

- Confirm whether `storage.dvc_tracked` should remain `TODO` or be updated after a `.dvc` pointer is created.
- Confirm whether the mapping rule text is sufficiently precise for team handoff.
- Confirm limitations and next version plan before final dataset registration.
