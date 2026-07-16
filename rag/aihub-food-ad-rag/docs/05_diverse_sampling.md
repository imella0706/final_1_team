# Diverse Sampling Pipeline

## 목적

`src/10_prepare_diverse_candidates.py`는 기존 5GB DB의 한계를 보완하기 위해 추가된 후보 생성 스크립트다.

기존 5GB DB는 목표 용량에 맞춰 이미지를 선택했기 때문에 고유 음식 수가 88개에 그쳤다. 광고 생성용 Retrieval DB에서는 같은 음식의 유사 이미지가 많이 들어가는 것보다, 가능한 다양한 음식 종류와 대표적인 촬영 방향을 확보하는 것이 중요하다.

## 입력

```text
data/metadata/tagged_metadata.parquet
```

필수 컬럼:

```text
annotation_path
image_path
original_food_name
blur_score
actual_width
actual_height
```

## 출력

```text
data/metadata/diverse_sampling/diverse_candidate_metadata.parquet
data/metadata/diverse_sampling/diverse_candidate_preview.csv
data/metadata/diverse_sampling/diverse_candidate_summary.json
```

## 생성 Feature

| 컬럼 | 의미 |
|---|---|
| view_type | 정위/front, 측면/side, unknown |
| bbox_x, bbox_y, bbox_width, bbox_height | JSON annotation에서 추출한 Bounding Box |
| bbox_ratio | 이미지 전체 면적 대비 음식 영역 비율 |
| bbox_40_70_match | Bounding Box 비율이 40~70%인지 여부 |
| center_score | 음식 Bounding Box 중심이 이미지 중심에 가까운 정도 |
| resolution_pixels | 실제 이미지 픽셀 수 |
| blur_score_normalized | Blur Score 정규화 값 |
| resolution_score | 해상도 정규화 값 |
| bbox_range_score | 광고용 대표 이미지에 적합한 Bounding Box 비율 점수 |
| representative_score | 대표 이미지 선정을 위한 종합 점수 |

## 대표 이미지 점수

```text
representative_score =
  0.35 * bbox_range_score
+ 0.30 * center_score
+ 0.20 * blur_score_normalized
+ 0.15 * resolution_score
```

## v2 DB 샘플링 정책

```text
1. 음식 종류 다양성 최대화
2. 음식별 정위 1장 + 측면 1장 우선 선택
3. Bounding Box 비율 40~70% 우선
4. 중앙성 점수 우선
5. Blur Score 우선
6. 해상도 우선
```

## 전체 실행 단계

```cmd
python src\10_prepare_diverse_candidates.py
python src\11_select_diverse_representatives.py
python src\12_build_diverse_embedding_subset.py
python src\13_build_diverse_faiss.py
python src\14_make_diverse_final_db.py --overwrite
python src\15_export_final_db_assets.py --db-names 5gb,5gb_v2_diverse
```

| 단계 | 산출물 |
|---|---|
| 10 | `data/metadata/diverse_sampling/diverse_candidate_metadata.parquet` |
| 11 | `data/metadata/diverse_sampling/selected_representatives.parquet` |
| 12 | `data/embeddings/diverse_sampling/diverse_image_embeddings.npy` |
| 13 | `data/embeddings/diverse_sampling/diverse_faiss.index` |
| 14 | `data/final_db/5gb_v2_diverse/` |
| 15 | `db_management_inventory.csv`, `llm_prompt_payloads.json`, `final_db_summary.json` |

## 현재 v2 결과

위치:

```text
data/final_db/5gb_v2_diverse/
```

| 항목 | 값 |
|---|---:|
| 이미지 수 | 1,036 |
| 실제 이미지 용량 | 약 4.441GB |
| 고유 음식 수 | 541 |
| 정위 이미지 | 522 |
| 측면 이미지 | 514 |
| 정위/측면 모두 확보된 음식 | 495 |
| Bounding Box 40~70% 선택 비율 | 약 72.3% |
| 평균 Bounding Box 비율 | 약 0.431 |
| 평균 Center Score | 약 0.944 |
| 평균 Blur Score | 약 291.36 |

## 기존 5GB DB와 차이

| 항목 | 기존 5GB | v2 Diverse 5GB |
|---|---:|---:|
| 이미지 수 | 952 | 1,036 |
| 고유 음식 수 | 88 | 541 |
| 임베딩 차원 | 512 | 512 |
| 샘플링 기준 | 용량/카테고리 중심 | 음식 다양성/정위/측면/Bounding Box 중심 |

## 관리/LLM Export

최종 DB 생성 후 `15_export_final_db_assets.py`를 실행하면 다음 파일이 생성된다.

```text
data/final_db/5gb/db_management_inventory.csv
data/final_db/5gb/llm_prompt_payloads.json
data/final_db/5gb_v2_diverse/db_management_inventory.csv
data/final_db/5gb_v2_diverse/llm_prompt_payloads.json
data/final_db/final_db_summary.json
```

`db_management_inventory.csv`는 사람이 DB를 검수하기 위한 전체 관리 파일이고, `llm_prompt_payloads.json`은 LLM 프롬프트에 전달할 reference context 파일이다.

`15_export_final_db_assets.py`는 DB 생성기가 아니라 export 후처리 도구다. 이미 만들어진 DB 폴더 안에 `metadata.parquet`, `prompt_metadata.parquet`, `summary.json`이 있으면 완성 DB로 판단하고, 해당 DB 폴더에 관리용 CSV와 LLM용 JSON을 생성한다.

새 DB가 추가되었을 때의 흐름:

```text
새로운 DB 생성
  ↓
data/final_db/새로운_db/
  ├── metadata.parquet
  ├── prompt_metadata.parquet
  └── summary.json
  ↓
python src\15_export_final_db_assets.py --db-names 새로운_db
  ↓
data/final_db/새로운_db/
  ├── db_management_inventory.csv
  └── llm_prompt_payloads.json
  ↓
data/final_db/final_db_summary.json 갱신
```

여러 DB를 한 번에 갱신하려면 다음처럼 실행한다.

```cmd
python src\15_export_final_db_assets.py --db-names 5gb,5gb_v2_diverse,새로운_db
```

## 향후 평가

다음 단계에서는 Bounding Box 후보 구간별로 DB를 만들고 검색 성능을 비교한다.

추천 평가 지표:

```text
Hits@5
Recall@5
MRR
```

이 평가는 40~70% 구간이 실제 검색 성능에서도 가장 좋은지 확인하기 위한 근거가 된다.
