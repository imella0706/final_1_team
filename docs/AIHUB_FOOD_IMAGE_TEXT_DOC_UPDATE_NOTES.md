# AIHub Food Image Text 문서 업데이트 기록

## 목적

이 문서는 `aihub_food_image_text v1` 데이터셋 등록 문서 중 아래 두 파일을 수정한 이유와 변경 내용을 기록하기 위한 문서입니다.

- `docs/datasets/aihub_food_image_text/v1/manifest.json`
- `docs/datasets/aihub_food_image_text/v1/description.md`

이번 수정의 기준은 `C:\aihub-food-ad-rag\data\final_db\5gb`에 생성된 **5GB baseline Retrieval DB**입니다.

중요하게, 이 문서는 `5gb_v2_diverse` 또는 이후 diverse sampling DB를 반영하지 않습니다. 현재 `v1` 등록 문서는 오직 `5gb` baseline DB만 설명합니다.

---

## 1. 전체 수정 방향

### 기존 상태

기존 문서는 `aihub_food_image_text v1` 데이터셋이 processed retrieval 패키지라는 점은 설명하고 있었지만, 다음 정보가 부족했습니다.

- 실제 생성된 `5gb` DB의 산출물 목록
- 운영 검수용 CSV 파일 설명
- LLM 프롬프트 전달용 JSON 파일 설명
- embedding/retrieval 세부 설정
- 재현 가능한 생성 스크립트 경로
- `manifest.json`과 `description.md` 사이의 설명 일관성

### 수정 방향

따라서 두 문서를 아래 원칙으로 보강했습니다.

1. `5gb` baseline DB 하나만 기준으로 설명한다.
2. 실제 산출물에 존재하는 파일을 문서에 반영한다.
3. 사람이 읽는 `description.md`와 기계가 읽는 `manifest.json`의 내용 수준을 맞춘다.
4. `TODO`로 남아 있던 일부 항목을 현재 프로젝트에서 확인 가능한 정보로 채운다.
5. 후속 DB인 `5gb_v2_diverse` 관련 내용은 의도적으로 제외한다.

---

## 2. `manifest.json` 변경 내용

### 2.1 `processing.preprocessing_steps` 수정

#### 변경 전

기존에는 처리 단계가 비교적 추상적으로 적혀 있었습니다.

```json
[
  "metadata normalization",
  "caption generation or caption assignment",
  "category mapping",
  "CLIP embedding generation",
  "FAISS index generation",
  "CSV and Parquet export"
]
```

#### 변경 후

현재 프로젝트의 실제 파이프라인을 더 잘 드러내도록 아래처럼 구체화했습니다.

```json
[
  "JSON metadata parsing and normalization",
  "business category and product group mapping",
  "image quality filtering",
  "duplicate removal",
  "caption and prompt keyword assignment",
  "CLIP image embedding generation",
  "FAISS index generation",
  "CSV and Parquet export",
  "LLM prompt payload JSON export"
]
```

#### 변경 이유

현재 `C:\aihub-food-ad-rag\src`의 파이프라인은 실제로 다음 흐름을 가집니다.

- `01_parse_metadata.py`
- `03_build_category_groups.py`
- `04_quality_filter.py`
- `05_remove_duplicates.py`
- `06_caption_tagging.py`
- `07_clip_embedding.py`
- `08_build_faiss.py`
- `09_make_final_db.py`
- `15_export_final_db_assets.py`

따라서 `manifest.json`의 처리 단계도 단순한 설명이 아니라 실제 실행 흐름을 추적할 수 있도록 보강했습니다.

단, `LLM prompt payload JSON export`는 엄밀히 말하면 DB 생성 전처리라기보다 후처리/export 단계입니다. 하지만 최종 artifact 구성에 포함되는 핵심 산출물이므로 현재 manifest에는 처리 산출 단계로 함께 기록했습니다.

---

### 2.2 `processing.output_files` 수정

#### 변경 내용

기존 output files에 아래 두 파일을 추가했습니다.

```json
"db_management_inventory.csv",
"llm_prompt_payloads.json"
```

#### 변경 이유

`15_export_final_db_assets.py` 실행 후 `5gb` DB 내부에 다음 파일들이 추가됩니다.

- `db_management_inventory.csv`
- `llm_prompt_payloads.json`

각 파일의 목적은 다음과 같습니다.

| 파일 | 목적 |
| --- | --- |
| `db_management_inventory.csv` | DB 운영, 검수, 누락 이미지 확인, 레코드 추적용 관리 CSV |
| `llm_prompt_payloads.json` | 광고 생성 LLM에 전달할 retrieval context payload JSON |

이 파일들은 단순 부가 파일이 아니라 BrandMate 서비스 연결 시 직접 활용될 수 있는 산출물이므로 `output_files`에 반영했습니다.

---

### 2.3 `food_description_data.caption_method` 수정

#### 변경 전

```json
"caption_method": "TODO"
```

#### 변경 후

```json
"caption_method": "caption and prompt keyword fields produced by the caption tagging stage; exact runtime model/version is not encoded in this v1 manifest."
```

#### 변경 이유

현재 DB에는 `caption`, `prompt_keywords`가 포함되어 있습니다. 따라서 caption 관련 필드가 존재한다는 사실은 기록하되, 정확한 caption 모델 버전이 manifest에 고정되어 있지는 않기 때문에 모델명을 단정하지 않았습니다.

---

### 2.4 `food_description_data.category_mapping_rule` 수정

#### 변경 전

```json
"category_mapping_rule": "TODO"
```

#### 변경 후

```json
"category_mapping_rule": "rule/keyword based mapping into business_category and product_group for BrandMate ad retrieval use cases."
```

#### 변경 이유

현재 DB는 원본 AIHub 카테고리를 그대로 쓰는 것이 아니라 BrandMate 광고 검색에 맞게 아래 필드를 사용합니다.

- `business_category`
- `product_group`

따라서 rule/keyword 기반 매핑을 사용했다는 점을 manifest에 명시했습니다.

---

### 2.5 `food_description_data.embedding` 수정

#### 변경 전

```json
{
  "enabled": true,
  "model": "TODO",
  "shape": [952, 512],
  "normalized": "TODO"
}
```

#### 변경 후

```json
{
  "enabled": true,
  "model": "OpenCLIP ViT-B-32 (512-dimensional image embeddings)",
  "shape": [952, 512],
  "normalized": true
}
```

#### 변경 이유

현재 `5gb` DB의 embedding shape은 `(952, 512)`이고, 프로젝트 설정에서 OpenCLIP `ViT-B-32` 계열 embedding을 사용하도록 설계되어 있습니다. FAISS 검색에서는 normalized embedding 기반 inner product를 사용하므로 `normalized`를 `true`로 기록했습니다.

---

### 2.6 `food_description_data.retrieval` 수정

#### 변경 전

```json
{
  "enabled": true,
  "method": "embedding_search",
  "index_file": "faiss.index",
  "faiss_index_type": "TODO",
  "similarity_metric": "TODO"
}
```

#### 변경 후

```json
{
  "enabled": true,
  "method": "embedding_search",
  "index_file": "faiss.index",
  "faiss_index_type": "IndexFlatIP",
  "similarity_metric": "inner_product_on_normalized_embeddings"
}
```

#### 변경 이유

현재 검색 DB는 `faiss.index`를 사용하고, FAISS index type은 `IndexFlatIP` 기준으로 문서화했습니다. normalized embedding을 전제로 inner product similarity를 사용한다고 기록했습니다.

---

### 2.7 `schema.columns` 추가

#### 변경 내용

아래 두 산출물의 schema 정보를 추가했습니다.

- `db_management_inventory.csv`
- `llm_prompt_payloads.json`

#### 변경 이유

두 파일은 운영 및 LLM 연결에 직접 사용됩니다. 따라서 파일이 존재한다는 설명만으로는 부족하고, 어떤 필드를 포함하는지 manifest에서 추적 가능해야 합니다.

---

### 2.8 `storage.local_source_project_path` 추가

#### 추가 내용

```json
"local_source_project_path": "C:\\aihub-food-ad-rag\\data\\final_db\\5gb"
```

#### 변경 이유

dev 프로젝트에 등록되는 데이터셋 문서는 실제 생성 프로젝트인 `C:\aihub-food-ad-rag`와 연결됩니다. 이 필드는 현재 manifest가 어떤 로컬 산출물을 기준으로 작성되었는지 추적하기 위해 추가했습니다.

---

### 2.9 `reproducibility` 수정

#### 변경 전

```json
{
  "generation_script_available": "TODO",
  "generation_script_path": "TODO",
  "random_seed": "TODO",
  "can_rebuild": "TODO"
}
```

#### 변경 후

```json
{
  "generation_script_available": true,
  "generation_script_path": [
    "C:\\aihub-food-ad-rag\\src\\01_parse_metadata.py",
    "C:\\aihub-food-ad-rag\\src\\02_eda_report.py",
    "C:\\aihub-food-ad-rag\\src\\03_build_category_groups.py",
    "C:\\aihub-food-ad-rag\\src\\04_quality_filter.py",
    "C:\\aihub-food-ad-rag\\src\\05_remove_duplicates.py",
    "C:\\aihub-food-ad-rag\\src\\06_caption_tagging.py",
    "C:\\aihub-food-ad-rag\\src\\07_clip_embedding.py",
    "C:\\aihub-food-ad-rag\\src\\08_build_faiss.py",
    "C:\\aihub-food-ad-rag\\src\\09_make_final_db.py",
    "C:\\aihub-food-ad-rag\\src\\15_export_final_db_assets.py"
  ],
  "random_seed": "none",
  "can_rebuild": "partial"
}
```

#### 변경 이유

온보딩 문서에서는 데이터셋을 다시 만들 수 있는 코드 또는 노트북 경로를 요구합니다. 현재 프로젝트에는 단계별 생성 스크립트가 존재하므로 `generation_script_available`을 `true`로 바꾸고, 관련 스크립트 경로를 명시했습니다.

`can_rebuild`는 `true`가 아니라 `partial`로 기록했습니다. 이유는 동일한 구조는 재생성 가능하지만 caption 생성 환경, 모델 버전, 로컬 파일 순서 등에 따라 완전히 동일한 row order나 caption 결과까지 보장하기 어렵기 때문입니다.

---

### 2.10 `limitations` 수정

#### 변경 내용

`v1` manifest가 현재 `5gb` baseline DB만 설명한다는 제한을 추가했습니다.

#### 변경 이유

같은 프로젝트 안에 다른 DB 산출물이 있더라도, 이 dataset registration 문서는 현재 `5gb` baseline DB만 대상으로 합니다. 이를 명시해 향후 다른 DB와 혼동하지 않도록 했습니다.

---

## 3. `description.md` 변경 내용

### 3.1 Summary 수정

#### 변경 내용

`description.md`의 Summary를 단순 retrieval 패키지 설명에서 아래 내용까지 포함하도록 확장했습니다.

- `5gb` baseline DB만 기준으로 작성한다는 점
- 운영 검수용 CSV 포함
- LLM 전달용 JSON payload 포함
- 검색 결과 매핑 파일 포함

#### 변경 이유

`manifest.json`에는 추가 산출물이 반영되어 있는데, 사람이 읽는 설명 문서에 해당 파일 설명이 없으면 실제 데이터셋을 이해하기 어렵습니다. 따라서 Summary 단계에서부터 `5gb` DB의 실제 구성 목적을 명확히 했습니다.

---

### 3.2 Dataset Stage 수정

#### 변경 내용

기존 산출물 목록에 아래 파일을 추가했습니다.

- `db_management_inventory.csv`
- `llm_prompt_payloads.json`

#### 변경 이유

두 파일은 `15_export_final_db_assets.py`를 통해 생성되는 후처리 산출물입니다. 운영 검수와 LLM prompt context 전달에 직접 쓰이므로 processed artifact의 구성 파일로 문서화했습니다.

---

### 3.3 Processing 수정

#### 변경 내용

처리 내용을 아래처럼 실제 파이프라인 중심으로 구체화했습니다.

- JSON metadata parsing and normalization
- business category and product group mapping
- image quality filtering
- duplicate removal
- caption and prompt keyword assignment
- CLIP image embedding generation
- FAISS index generation
- CSV and Parquet export
- LLM prompt payload JSON export

#### 변경 이유

`manifest.json`의 `preprocessing_steps`와 사람이 읽는 `description.md`의 처리 설명이 일치해야 합니다. 또한 이 데이터셋이 단순 이미지 모음이 아니라 API/RAG에서 바로 쓰는 processed artifact라는 점을 더 잘 설명하기 위해 수정했습니다.

---

### 3.4 Output Files 섹션 보강

#### 추가된 파일 설명

아래 두 파일 설명을 새로 추가했습니다.

##### `db_management_inventory.csv`

DB 운영과 검수에 사용할 수 있도록 최종 이미지, 원본 이미지, 음식명, 카테고리, 상품군, caption, prompt keyword, embedding id, 파일 존재 여부 등을 행 단위로 정리한 관리용 CSV입니다.

##### `llm_prompt_payloads.json`

광고 생성 LLM으로 전달하기 쉬운 형태로 `prompt_metadata`를 JSON payload 배열로 변환한 파일입니다. 상품명, 음식명, 카테고리, caption, prompt keyword, retrieval text, ad prompt hint, reference image path를 포함합니다.

#### 변경 이유

이 두 파일은 dev 프로젝트에서 광고 생성 기능과 연결될 때 직접 사용할 수 있는 파일입니다. 따라서 description에도 각 파일의 역할과 활용 목적을 명확히 기록했습니다.

---

### 3.5 Dataset-Specific Fields 섹션 추가

#### 추가 내용

아래 정보를 새로 정리했습니다.

- caption method
- category mapping rule
- embedding model
- embedding shape
- embedding normalization
- retrieval method
- FAISS index type
- similarity metric
- main category fields
- prompt fields
- path mapping fields

#### 변경 이유

온보딩 문서에서는 공통 manifest에 없는 데이터셋 고유 정보를 별도 section으로 설명할 수 있다고 안내합니다. 이 데이터셋은 retrieval/embedding/FAISS를 포함하는 processed artifact이므로, 검색 시스템 관련 필드를 사람이 읽는 문서에도 명확히 추가했습니다.

---

### 3.6 Statistics 보강

#### 변경 내용

기존 통계에 product group count와 actual image size를 더 명확히 정리했습니다.

#### 변경 이유

데이터셋을 사용할 사람이 `5gb` baseline DB의 카테고리 편향과 구성 규모를 빠르게 판단할 수 있도록 하기 위함입니다.

---

### 3.7 Storage 수정

#### 변경 내용

아래 항목을 추가했습니다.

```text
local source project path: C:\aihub-food-ad-rag\data\final_db\5gb
```

#### 변경 이유

현재 dev 프로젝트 문서는 `C:\aihub-food-ad-rag` 프로젝트에서 생성한 산출물을 등록하는 목적입니다. 따라서 원본 산출물 위치를 명시해 추적 가능성을 높였습니다.

---

### 3.8 Reproducibility 수정

#### 변경 내용

`TODO`로 되어 있던 재현성 항목을 실제 생성 스크립트 경로 중심으로 보강했습니다.

#### 변경 이유

온보딩 문서에서는 데이터셋을 다시 만들 수 있는 코드나 노트북 경로를 요구합니다. 따라서 `C:\aihub-food-ad-rag\src`의 단계별 스크립트를 문서에 기록했습니다.

---

### 3.9 Limitations 수정

#### 변경 내용

기존 한계점에 아래 관점을 추가했습니다.

- 음식 종류 다양성보다 5GB 용량 목표와 기본 품질 필터 통과 여부를 우선한 baseline DB이다.
- 이 `v1` 문서는 현재 `5gb` baseline DB만 기준으로 한다.

#### 변경 이유

현재 DB는 검색/RAG baseline으로는 사용 가능하지만, 카테고리 균형이나 음식 종류 다양성을 최적화한 버전은 아닙니다. 이 한계를 명시해 서비스 적용 시 오해를 줄이기 위해 수정했습니다.

---

## 4. 왜 `5gb`만 반영했는가

현재 `aihub_food_image_text v1` 등록 문서는 `food_description_data`의 baseline artifact를 등록하기 위한 문서입니다.

따라서 이 문서에는 다음을 반영하지 않습니다.

- `5gb_v2_diverse`
- diverse sampling pipeline
- front/side representative sampling
- bbox ratio 기반 대표 이미지 선정
- 후속 실험 DB 통계

이 정보는 별도 데이터셋 버전 또는 별도 문서에서 다루는 것이 맞습니다. 현재 `v1` 문서는 `5gb` baseline DB만 설명합니다.

---

## 5. 주의할 점

### `image open/existence validation`에 대한 해석

`image_open_ok`, `image_exists` 같은 컬럼이 현재 프로젝트 메타데이터에 존재하기 때문에 이미지 존재 여부와 열기 가능 여부를 검증한 흔적이 있습니다.

다만 이것은 엄밀히 말하면 `quality_filter`라기보다 validation check에 가깝습니다. 따라서 문서에서 이 항목을 품질 필터에 포함할지, 별도 validation 항목으로 분리할지는 팀 컨벤션에 따라 조정할 수 있습니다.

### `LLM prompt payload JSON export`에 대한 해석

`llm_prompt_payloads.json`은 DB 생성의 핵심 전처리라기보다는 `15_export_final_db_assets.py`에서 수행하는 후처리/export 산출물입니다.

하지만 최종 artifact 안에 포함되고 BrandMate LLM 프롬프트 연결에 직접 쓰일 수 있으므로 현재 문서에서는 processed artifact의 생성 단계 중 하나로 설명했습니다.

---

## 6. 최종 정리

이번 수정은 데이터 자체를 변경한 작업이 아니라, 이미 생성된 `5gb` baseline DB를 dev 프로젝트의 데이터셋 등록 규칙에 맞게 설명하기 위한 문서 정비 작업입니다.

핵심 변경 목적은 다음과 같습니다.

1. `manifest.json`의 TODO를 줄이고 실제 산출물 기준으로 보강한다.
2. `description.md`를 사람이 이해하기 쉬운 수준으로 확장한다.
3. 두 문서가 서로 같은 파일 목록, 처리 단계, 활용 목적을 설명하도록 맞춘다.
4. `5gb` baseline DB만 기준으로 문서를 유지한다.
