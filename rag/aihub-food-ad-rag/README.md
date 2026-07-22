# AIHub Food Advertisement Retrieval DB

AI Hub 음식 이미지 데이터를 광고 콘텐츠 생성 AI에서 참조할 수 있는 검색형 데이터베이스(Retrieval DB)로 변환하는 프로젝트입니다.

이 프로젝트는 광고 문구나 이미지를 직접 생성하는 모델이 아니라, 생성 모델이 참고할 수 있는 음식 이미지, 음식명, 업종, 상품군, 캡션, 프롬프트 키워드, CLIP 임베딩, FAISS 검색 인덱스를 구축합니다.

## 현재 완료 상태

| 항목 | 상태 |
|---|---|
| 원본 데이터 파싱 | 완료 |
| EDA 리포트 | 완료 |
| 업종/상품군 매핑 | 완료 |
| 이미지 품질 필터링 | 완료 |
| pHash 기반 중복 제거 | 완료 |
| BLIP 기반 캡션/태그 생성 | 완료 |
| CLIP 이미지 임베딩 생성 | 완료 |
| FAISS 인덱스 생성 | 완료 |
| 기존 processed\aihub_food_image_text\v1\food_description_data DB | 완료 |
| 다양성 기반 processed\aihub_food_image_text\v2\food_description_data | 완료 |
| 최종 DB 관리 CSV/LLM JSON Export | 완료 |
| 10GB/20GB DB | 구조만 준비됨, 완성 DB 아님 |

## 핵심 데이터 요약

| 항목 | 값 |
|---|---:|
| JSON 파일 수 | 11,582 |
| 이미지 파일 수 | 11,582 |
| 유효 JSON 수 | 11,582 |
| 누락 이미지 수 | 0 |
| 음식 종류 | 643 |
| Food Code 수 | 69 |
| 원본 이미지 용량 | 약 43.74GB |
| 평균 이미지 크기 | 약 3.87MB |
| 평균 해상도 | 약 3002 x 2955 |

## 처리 결과

| 단계 | 결과 |
|---|---:|
| 품질 통과 이미지 | 7,733 |
| 품질 제외 이미지 | 3,849 |
| 중복 제거 후 이미지 | 7,351 |
| 캡션 생성 성공 | 7,351 |
| CLIP 임베딩 생성 | 7,351 x 512 |
| FAISS 인덱스 총 벡터 | 7,351 |

## 최종 DB

### 기존 processed\aihub_food_image_text\v1\food_description_data DB

위치:

```text
data/final_db/processed\aihub_food_image_text\v1\food_description_data/
```

| 항목 | 값 |
|---|---:|
| 실제 이미지 용량 | 약 4.998GB |
| 이미지 수 | 952 |
| 고유 음식 수 | 88 |
| 임베딩 shape | 952 x 512 |

### 다양성 기반 processed\aihub_food_image_text\v2\food_description_data

위치:

```text
data/final_db/processed\aihub_food_image_text\v2\food_description_data/
```

샘플링 정책:

```text
1. 음식 종류 다양성 최대화
2. 음식별 정위 1장 + 측면 1장 우선 선택
3. Bounding Box 비율 40~70% 우선
4. 중앙성 점수 우선
5. Blur Score 우선
6. 해상도 우선
```

| 항목 | 값 |
|---|---:|
| 실제 이미지 용량 | 약 4.441GB |
| 이미지 수 | 1,036 |
| 고유 음식 수 | 541 |
| 정위 이미지 | 522 |
| 측면 이미지 | 514 |
| 정위/측면 모두 확보된 음식 | 495 |
| Bounding Box 40~70% 선택 비율 | 약 72.3% |
| 임베딩 shape | 1,036 x 512 |

## Execution Flow

The shared base/v1 processed candidate pool is created by steps `01`~`08`.

```cmd
python src\01_parse_metadata.py
python src\02_eda_report.py
python src\03_build_category_groups.py
python src\04_quality_filter.py
python src\05_remove_duplicates.py
python src\06_caption_tagging.py
python src\07_clip_embedding.py
python src\08_build_faiss.py
```

The baseline `processed\aihub_food_image_text\v1\food_description_data` DB is created by `09_make_final_db.py`.

```cmd
python src\09_make_final_db.py --versions processed\aihub_food_image_text\v1\food_description_data
```

The diverse `processed\aihub_food_image_text\v2\food_description_data` DB does not directly reuse the final baseline `processed\aihub_food_image_text\v1\food_description_data` DB. It uses the base/v1 processed candidate pool and embedding/FAISS artifacts from `01`~`08`, then rebuilds the DB through steps `10`~`15`.

```cmd
python src\10_prepare_diverse_candidates.py
python src\11_select_diverse_representatives.py
python src\12_build_diverse_embedding_subset.py
python src\13_build_diverse_faiss.py
python src\14_make_diverse_final_db.py --overwrite
python src\15_export_final_db_assets.py --db-names processed\aihub_food_image_text\v1\food_description_data,processed\aihub_food_image_text\v2\food_description_data
```

## Reproducibility

The v2 generation path scripts `01`~`08` and `10`~`15` call `src/utils/reproducibility.py`.

```text
DEFAULT_RANDOM_SEED = 42
```

The seed utility sets Python `random`, NumPy, PyTorch, CUDA seeds and deterministic options on a best-effort basis.

## Final DB File Structure

Each completed DB folder contains:

```text
images/
metadata.parquet
prompt_metadata.parquet
embeddings.npy
faiss.index
mapping.csv
summary.json
db_management_inventory.csv
llm_prompt_payloads.json
```

`summary.json` describes one DB folder. The root summary across DB versions is managed at:

```text
data/final_db/final_db_summary.json
```

## DB Export Post-processing

`src/15_export_final_db_assets.py` adds operational/export artifacts to each completed DB folder.

| File | Purpose |
|---|---|
| `db_management_inventory.csv` | Human-readable DB inspection and management CSV |
| `llm_prompt_payloads.json` | JSON payload for LLM prompt or RAG context |
| `final_db_summary.json` | Integrated summary for DB versions under `data/final_db/` |

## Search API

```cmd
python app\retrieval_api.py
```

Basic checks:

```cmd
curl http://127.0.0.1:7860/health
curl http://127.0.0.1:7860/categories
```

The current API does not directly use the CLIP text encoder. It combines metadata filtering with representative vector search based on image embeddings.

## Notes

- Do not commit `data/raw/`, `data/embeddings/`, `data/final_db/`, or `data.zip`.
- `processed\aihub_food_image_text\v2\food_description_data` does not directly reuse the final baseline `processed\aihub_food_image_text\v1\food_description_data` DB; it uses outputs from `01`~`08`.
- `09_make_final_db.py` is for the baseline `processed\aihub_food_image_text\v1\food_description_data` DB and is not part of the direct v2 generation path.
- Bounding Box representative selection is implemented in `10_prepare_diverse_candidates.py` and reflected in `processed\aihub_food_image_text\v2\food_description_data`.
