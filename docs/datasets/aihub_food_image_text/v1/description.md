# aihub_food_image_text v1 Description

## Summary

`aihub_food_image_text`는 AIHub `비전영역 음식이미지 및 정보소개 텍스트 데이터`의 validation split에서 BrandMate에 사용할 음식 이미지/텍스트 후보를 선별하고, 검색과 광고 프롬프트 생성에 바로 쓸 수 있도록 가공한 데이터셋입니다.

현재 `v1`의 processed 산출물인 `food_description_data`는 음식 이미지, 메타데이터, 프롬프트용 경량 메타데이터, CLIP embedding, FAISS index를 함께 묶은 retrieval 패키지입니다.

## Dataset Stage

이 산출물은 `processed` 단계입니다.

단순히 이미지를 고른 데이터 풀이 아니라, 모델/API/RAG 파이프라인이 바로 읽을 수 있도록 아래 산출물을 포함합니다.

- `metadata.csv`, `metadata.parquet`
- `prompt_metadata.csv`, `prompt_metadata.parquet`
- `embeddings.npy`
- `faiss.index`
- `mapping.csv`
- `summary.json`
- `images/`

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
- 선별 기준: AIHub validation split에서 약 5GB 목표로 BrandMate reference/RAG에 사용할 이미지 subset을 선별했습니다.
- 카테고리 균형 여부: false
- 품질 필터:
  - blur score filtering
  - low-resolution image filtering
  - pHash duplicate filtering
  - CLIP similarity duplicate filtering
- 원본 경로와 최종 경로 매핑 가능 여부: true

## Processing

- 입력 데이터셋: AIHub validation selected subset
- artifact name: `food_description_data`
- 사용 목적: retrieval, prompt context generation, API reference data
- 처리 내용:
  - metadata normalization
  - caption generation 또는 caption assignment
  - category mapping
  - CLIP embedding generation
  - FAISS index generation
  - CSV and Parquet export
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

## Output Files

### `images/`

최종 retrieval DB에 실제로 포함된 음식 이미지 파일입니다.

검색 결과에서 `final_image_path`가 반환되면, 프론트엔드나 노트북은 이 폴더의 이미지를 열어 reference image로 사용할 수 있습니다.

### `metadata.csv`, `metadata.parquet`

최종 DB의 마스터 메타데이터입니다.

이미지 경로, 원본 음식명, 상품명, 업종 카테고리, 상품군, caption, prompt keyword, embedding index 등 분석과 검증에 필요한 전체 컬럼을 보관합니다.

### `prompt_metadata.csv`, `prompt_metadata.parquet`

광고 문구 생성이나 이미지 생성 프롬프트에 필요한 핵심 컬럼만 모은 경량 메타데이터입니다.

전체 메타데이터가 아니라 프롬프트 context 구성에 필요한 상품명, 카테고리, caption, prompt keyword, retrieval text, ad prompt hint 중심으로 사용합니다.

### `embeddings.npy`

최종 DB에 포함된 이미지의 CLIP embedding 배열입니다.

FAISS index를 재생성하거나 embedding 분포를 분석할 때 사용합니다.

### `faiss.index`

이미지 embedding 검색을 위한 FAISS index 파일입니다.

API나 노트북에서 유사 음식 이미지를 검색할 때 사용합니다.

### `mapping.csv`

FAISS index id, embedding index, 최종 이미지 경로, 원본 이미지 경로, 음식명, 카테고리 등을 연결하는 매핑 테이블입니다.

검색 결과를 실제 이미지와 메타데이터로 복원하는 데 필요합니다.

### `summary.json`

데이터 생성 결과 요약 파일입니다.

이미지 수, record 수, 카테고리 분포 등 빠르게 확인해야 하는 요약 정보를 둡니다.

## Statistics

- image file count: 952
- record count: 952
- embedding shape: `(952, 512)`
- business category count:
  - restaurant: 276
  - dessert: 175
  - bakery: 174
  - cafe: 165
  - pub: 162
- unique food name count: 88

## Storage

- GCS path: `gs://ssakda/projects/brandmate/data/processed/aihub_food_image_text/v1/food_description_data/`
- local example path: `data/processed/aihub_food_image_text/v1/food_description_data/`
- canonical manifest: `docs/datasets/aihub_food_image_text/v1/manifest.json`
- canonical description: `docs/datasets/aihub_food_image_text/v1/description.md`
- package docs:
  - `data/processed/aihub_food_image_text/v1/food_description_data/docs/manifest.json`
  - `data/processed/aihub_food_image_text/v1/food_description_data/docs/description.md`
- DVC tracking 여부: true

## Reproducibility

- 데이터셋 생성 스크립트 또는 노트북 경로: TODO
- random seed: TODO
- 같은 결과를 다시 만들 수 있는지: TODO

## Limitations

- BrandMate target domain 기준으로 카테고리 균형을 의도적으로 맞춘 데이터셋은 아닙니다.
- cafe, bakery, dessert, beverage, brunch 시나리오는 추가 보강이 필요할 수 있습니다.
- 약 5GB 목표 크기와 일정 제약 안에서 생성된 baseline 데이터셋입니다.
- 원본 AIHub annotation 파일은 이 artifact 안에 보존하지 않았습니다.

## Next Version Plan

다음 버전에서는 cafe, bakery, dessert, beverage, brunch 커버리지를 강화하고, 생성 스크립트와 seed 정보를 보강해 재현 가능성을 높입니다.
