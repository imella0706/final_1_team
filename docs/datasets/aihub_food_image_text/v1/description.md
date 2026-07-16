# aihub_food_image_text v1 Description

## Summary

`aihub_food_image_text`는 AIHub `비전영역 음식이미지 및 정보소개 텍스트 데이터`의 validation split에서 BrandMate 광고 생성/RAG에 사용할 음식 이미지와 텍스트 메타데이터를 선별하고, 검색 API와 광고 프롬프트 생성에서 바로 참조할 수 있도록 가공한 processed 데이터셋입니다.

현재 `v1`의 processed 산출물인 `food_description_data`는 `5gb` baseline DB 하나만을 기준으로 작성합니다. 이 패키지는 음식 이미지, 마스터 메타데이터, 프롬프트용 경량 메타데이터, CLIP image embedding, FAISS index, 검색 결과 매핑 파일, 운영 검수용 CSV, LLM 전달용 JSON payload를 함께 묶은 retrieval 패키지입니다.

## Dataset Stage

이 산출물은 `processed` 단계입니다.

단순히 이미지를 고른 데이터 풀이 아니라, 모델/API/RAG 파이프라인이 바로 읽을 수 있도록 아래 산출물을 포함합니다.

- `images/`
- `metadata.csv`, `metadata.parquet`
- `prompt_metadata.csv`, `prompt_metadata.parquet`
- `embeddings.npy`
- `faiss.index`
- `mapping.csv`
- `summary.json`
- `db_management_inventory.csv`
- `llm_prompt_payloads.json`

## Source

- 원본 제공처: AIHub
- 원본 데이터셋 ID: `71564`
- 원본 데이터셋 이름: `비전영역 음식이미지 및 정보소개 텍스트 데이터`
- 원본 URL: `https://aihub.or.kr/aihubdata/data/view.do?dataSetSn=71564`
- 사용 split: `validation`
- raw 원본 전체 GCS 업로드 여부: false
- 원본 annotation/label 보존 여부: false
- 구축 기관: `㈜네스`, `㈜씨엔에이아이`, `㈜어메이징푸드솔루션`

## Curation

- 선별 개수: 952 images
- 목표 용량: 5GB
- 실제 용량: 약 4.998GB
- 선별 기준: AIHub validation split에서 품질 필터링과 중복 제거를 거친 이미지 중 BrandMate reference/RAG에 사용할 약 5GB 규모의 baseline subset을 선별했습니다.
- 카테고리 균형 여부: false
- 품질 필터:
  - blur score filtering
  - low-resolution image filtering
  - image open/existence validation
  - pHash duplicate filtering
  - CLIP similarity duplicate filtering
- 원본 경로와 최종 경로 매핑 가능 여부: true

## Processing

- 입력 데이터셋: AIHub validation selected subset
- artifact name: `food_description_data`
- 사용 목적: retrieval, prompt context generation, API reference data
- 처리 내용:
  - JSON metadata parsing and normalization
  - business category and product group mapping
  - image quality filtering
  - duplicate removal
  - caption and prompt keyword assignment
  - CLIP image embedding generation
  - FAISS index generation
  - CSV and Parquet export
  - LLM prompt payload JSON export
- 생성 파일:
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

## Output Files

### `images/`

최종 retrieval DB에 실제로 포함된 음식 이미지 파일입니다. 검색 결과에서 `final_image_path`가 반환되면 프론트엔드, 노트북, API 응답 검증 과정에서 reference image로 사용할 수 있습니다.

### `metadata.csv`, `metadata.parquet`

최종 DB의 마스터 메타데이터입니다.

이미지 경로, 원본 음식명, 상품명, 업종 카테고리, 상품군, caption, prompt keyword, embedding index 등 분석과 검증에 필요한 전체 컬럼을 보관합니다.

### `prompt_metadata.csv`, `prompt_metadata.parquet`

광고 문구 생성이나 이미지 생성 프롬프트에 필요한 핵심 컬럼만 모은 경량 메타데이터입니다.

전체 메타데이터가 아니라 프롬프트 context 구성에 필요한 상품명, 카테고리, caption, prompt keyword, retrieval text, ad prompt hint 중심으로 사용합니다.

### `embeddings.npy`

최종 DB에 포함된 이미지의 CLIP embedding 배열입니다.

`5gb` 기준 embedding shape은 `(952, 512)`입니다. FAISS index를 재생성하거나 embedding 분포를 분석할 때 사용합니다.

### `faiss.index`

이미지 embedding 검색을 위한 FAISS index 파일입니다.

FAISS index type은 `IndexFlatIP`이며, normalized embedding에 대한 inner product similarity 검색을 기준으로 사용합니다.

### `mapping.csv`

FAISS index id, embedding index, 최종 이미지 경로, 원본 이미지 경로, 음식명, 카테고리 등을 연결하는 매핑 테이블입니다.

검색 결과를 실제 이미지와 메타데이터로 복원하는 데 필요합니다.

### `summary.json`

`5gb` DB 생성 결과 요약 파일입니다.

이미지 수, record 수, embedding shape, 카테고리 분포 등 빠르게 확인해야 하는 요약 정보를 둡니다.

### `db_management_inventory.csv`

DB 운영과 검수에 사용할 수 있도록 최종 이미지, 원본 이미지, 음식명, 카테고리, 상품군, caption, prompt keyword, embedding id, 파일 존재 여부 등을 행 단위로 정리한 관리용 CSV입니다.

이 파일은 데이터셋 검수, 누락 이미지 확인, 카테고리 분포 확인, 운영 중 레코드 추적에 사용합니다.

### `llm_prompt_payloads.json`

광고 생성 LLM으로 전달하기 쉬운 형태로 `prompt_metadata`를 JSON payload 배열로 변환한 파일입니다.

상품명, 음식명, 카테고리, caption, prompt keyword, retrieval text, ad prompt hint, reference image path를 포함하며, BrandMate 광고 프롬프트 생성 단계에서 검색 결과 context로 사용할 수 있습니다.

## Dataset-Specific Fields

- caption method: caption tagging stage에서 생성 또는 할당된 `caption`, `prompt_keywords`를 사용합니다. 정확한 런타임 모델/버전은 이 `v1` manifest에 고정하지 않았습니다.
- category mapping rule: BrandMate 광고 검색 목적에 맞춰 rule/keyword 기반으로 `business_category`, `product_group`을 매핑했습니다.
- embedding model: OpenCLIP `ViT-B-32` 계열 image embedding
- embedding shape: `(952, 512)`
- embedding normalization: true
- retrieval method: embedding search
- FAISS index type: `IndexFlatIP`
- similarity metric: normalized embedding 기준 inner product
- main category fields: `business_category`, `product_group`
- prompt fields: `caption`, `prompt_keywords`, `retrieval_text`, `ad_prompt_hint`
- path mapping fields: `image_path`, `final_image_path`, `final_image_file_name`

## Statistics

- image file count: 952
- record count: 952
- embedding shape: `(952, 512)`
- actual image size: 약 4.998GB
- business category count:
  - restaurant: 276
  - dessert: 175
  - bakery: 174
  - cafe: 165
  - pub: 162
- product group count:
  - chicken: 272
  - cake: 175
  - bread: 164
  - fried_side: 127
  - brunch: 124
  - ade_juice: 40
  - grilled_side: 35
  - bagel: 9
  - japanese_food: 2
  - delivery_food: 1
  - pizza: 1
  - tea: 1
  - pastry: 1
- unique food name count: 88

## Storage

- GCS path: `gs://ssakda/projects/brandmate/data/processed/aihub_food_image_text/v1/food_description_data/`
- manifest GCS path: `gs://ssakda/projects/brandmate/data/manifests/aihub_food_image_text_v1.json`
- local example path: `data/processed/aihub_food_image_text/v1/food_description_data/`
- local source project path: `C:\aihub-food-ad-rag\data\final_db\5gb`
- canonical manifest: `docs/datasets/aihub_food_image_text/v1/manifest.json`
- canonical description: `docs/datasets/aihub_food_image_text/v1/description.md`
- package docs:
  - `data/processed/aihub_food_image_text/v1/food_description_data/docs/manifest.json`
  - `data/processed/aihub_food_image_text/v1/food_description_data/docs/description.md`
- DVC tracking 여부: true

## Reproducibility

- 데이터셋 생성 스크립트 경로:
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
- random seed: none
- 같은 결과를 다시 만들 수 있는지: partial

동일한 입력 데이터와 동일한 로컬 경로가 유지되면 같은 구조의 DB를 다시 만들 수 있습니다. 다만 caption 생성 모델 버전, GPU/CPU 실행 환경, 원본 파일 배치 상태에 따라 caption 또는 선별 순서가 일부 달라질 수 있으므로 `partial`로 기록합니다.

## Limitations

- BrandMate target domain 기준으로 카테고리 균형을 의도적으로 맞춘 데이터셋은 아닙니다.
- cafe, bakery, dessert, beverage, brunch 시나리오는 추가 보강이 필요할 수 있습니다.
- 약 5GB 목표 크기와 일정 제약 안에서 생성된 baseline 데이터셋입니다.
- 원본 AIHub annotation 파일은 이 artifact 안에 보존하지 않았습니다.
- 음식 종류 다양성보다 5GB 용량 목표와 기본 품질 필터 통과 여부를 우선한 baseline DB입니다.

## Next Version Plan

다음 버전에서는 cafe, bakery, dessert, beverage, brunch 커버리지를 강화하고, 음식 종류 다양성, 촬영 방향, bounding box 대표성, 검색 평가 지표를 반영한 별도 버전을 검토합니다. 단, 이 `v1` 문서는 현재 `5gb` baseline DB만을 기준으로 합니다.

