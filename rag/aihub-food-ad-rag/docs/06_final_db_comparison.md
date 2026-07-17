# Final DB Comparison

## 목적

이 문서는 기존 `5gb` DB와 새로 만든 `5gb_v2_diverse` DB의 차이를 정리한다. 두 DB는 모두 광고 생성용 Food Retrieval DB지만, 샘플링 기준과 활용 목적이 다르다.

```text
기존 5gb DB
  -> 용량 목표와 카테고리 비율 중심으로 생성한 기본 Retrieval DB

5gb_v2_diverse DB
  -> 음식 종류 다양성, 정위/측면 대표성, Bounding Box 품질을 반영한 개선 DB
```

## 요약 비교

| 항목 | 기존 5gb DB | 5gb_v2_diverse DB |
|---|---:|---:|
| 위치 | `data/final_db/5gb/` | `data/final_db/5gb_v2_diverse/` |
| 실제 이미지 용량 | 약 4.998GB | 약 4.441GB |
| 이미지 수 | 952 | 1,036 |
| 고유 음식 수 | 88 | 541 |
| 임베딩 shape | 952 x 512 | 1,036 x 512 |
| 샘플링 기준 | 용량/카테고리 중심 | 음식 다양성/정위/측면/BBox 중심 |
| 정위 이미지 수 | 별도 관리 없음 | 522 |
| 측면 이미지 수 | 별도 관리 없음 | 514 |
| 정위/측면 모두 확보된 음식 | 별도 관리 없음 | 495 |
| BBox 40~70% 선택 비율 | 별도 관리 없음 | 약 72.3% |

## 기존 5gb DB

### 생성 목적

기존 `5gb` DB는 전체 파이프라인이 정상적으로 작동하는지 검증하고, 검색 API와 Prompt RAG에서 바로 사용할 수 있는 첫 번째 완성 DB를 만드는 것이 목적이었다.

### 생성 방식

`src/09_make_final_db.py`가 다음 입력을 사용해 생성한다.

```text
data/embeddings/embedding_metadata.parquet
data/embeddings/image_embeddings.npy
```

주요 기준:

```text
1. 목표 용량 5GB에 맞춰 이미지 선택
2. business_category 비율 반영
3. product_group, original_food_name 기준 정렬 및 샘플링
4. 선택 이미지로 metadata, prompt_metadata, embeddings, faiss.index 생성
```

### 장점

- 파이프라인 전체 검증에 적합하다.
- 검색 API에서 바로 사용할 수 있다.
- `summary.json`, `metadata.parquet`, `prompt_metadata.parquet`, `faiss.index` 구조가 안정적으로 갖춰져 있다.
- DB 패키징과 API 로딩 검증용 기준 DB로 적합하다.

### 한계

- 고유 음식 수가 88개로 낮다.
- 특정 product_group 또는 음식 종류가 과대표집될 수 있다.
- 정위/측면 촬영 방향을 명시적으로 보장하지 않는다.
- Bounding Box 비율, 중앙성, 대표 이미지 점수를 고려하지 않는다.

## 5gb_v2_diverse DB

### 생성 목적

`5gb_v2_diverse` DB는 기존 DB의 음식 다양성 부족 문제를 해결하기 위해 만들었다. 광고 생성용 Retrieval DB에서는 동일 음식의 유사 이미지가 반복되는 것보다, 다양한 음식 종류와 대표적인 촬영 방향을 확보하는 것이 중요하다.

### 생성 방식

다음 단계로 생성한다.

```cmd
python src\10_prepare_diverse_candidates.py
python src\11_select_diverse_representatives.py
python src\12_build_diverse_embedding_subset.py
python src\13_build_diverse_faiss.py
python src\14_make_diverse_final_db.py --overwrite
python src\15_export_final_db_assets.py --db-names 5gb,5gb_v2_diverse
```

### 단계별 역할

| 단계 | 파일 | 역할 |
|---|---|---|
| 10 | `10_prepare_diverse_candidates.py` | Bounding Box, 중앙성, view_type, representative_score 계산 |
| 11 | `11_select_diverse_representatives.py` | 음식별 정위/측면 대표 이미지 선택 |
| 12 | `12_build_diverse_embedding_subset.py` | 선택 이미지에 해당하는 CLIP 임베딩 subset 생성 |
| 13 | `13_build_diverse_faiss.py` | diverse subset 전용 FAISS 인덱스 생성 |
| 14 | `14_make_diverse_final_db.py` | 최종 `5gb_v2_diverse` DB 패키징 |
| 15 | `15_export_final_db_assets.py` | 관리 CSV, LLM JSON, 루트 final_db_summary 생성 |

### 대표 이미지 선정 기준

```text
1. 음식 종류 다양성 최대화
2. 음식별 정위 1장 + 측면 1장 우선
3. Bounding Box 비율 40~70% 우선
4. 중앙성 점수 우선
5. Blur Score 우선
6. 해상도 우선
```

대표 이미지 점수:

```text
representative_score =
  0.35 * bbox_range_score
+ 0.30 * center_score
+ 0.20 * blur_score_normalized
+ 0.15 * resolution_score
```

### 장점

- 고유 음식 수가 88개에서 541개로 증가했다.
- 정위/측면 이미지를 균형 있게 확보했다.
- 음식별 대표 이미지가 더 명확하다.
- Bounding Box 비율과 중앙성을 고려해 광고 reference image로 쓰기 좋은 이미지가 많다.
- 검색 결과에서 동일 음식 반복이 줄어들 가능성이 높다.

### 한계

- 실제 Retrieval 성능 평가는 아직 추가로 필요하다.
- Bounding Box 40~70%가 최적인지는 Hits@5, Recall@5, MRR로 비교해야 한다.
- 이미지 다양성이 증가했지만, 일부 카테고리 분포는 여전히 원본 데이터 분포 영향을 받는다.
- CLIP text encoder 기반 텍스트-이미지 검색은 아직 별도 개선 과제다.

## 파일 구조 비교

두 DB 모두 최종적으로 같은 운영 구조를 갖는다.

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

전체 DB 통합 요약은 루트에서 관리한다.

```text
data/final_db/final_db_summary.json
```

## 관리 CSV와 LLM JSON

`src/15_export_final_db_assets.py`를 실행하면 각 DB 폴더에 다음 파일이 생성된다.

```text
db_management_inventory.csv
llm_prompt_payloads.json
```

### db_management_inventory.csv

사람이 DB를 검수하기 위한 파일이다.

주요 용도:

```text
1. 이미지별 음식명 확인
2. business_category / product_group 확인
3. view_type, bbox_ratio, center_score 확인
4. caption, prompt_keywords 검수
5. DB별 데이터 편향 확인
```

### llm_prompt_payloads.json

LLM 프롬프트 또는 RAG context에 바로 전달하기 위한 JSON 파일이다.

주요 용도:

```text
1. 광고 프롬프트 생성 reference context
2. 이미지 생성 프롬프트 보강
3. 유사 메뉴 검색 결과를 LLM 입력으로 변환
4. 서비스 API 응답 payload 설계 참고
```

## 어떤 DB를 기준으로 써야 하는가?

### 빠른 API 검증

```text
data/final_db/5gb/
```

기존 DB는 API 로딩, 검색 응답, 파일 구조 검증에 적합하다.

### 광고 생성용 Reference DB

```text
data/final_db/5gb_v2_diverse/
```

v2 DB는 음식 다양성과 대표 이미지 품질이 더 좋아 광고 생성용 reference DB로 더 적합하다.

## 보고서 작성 시 핵심 결론

보고서에는 다음처럼 정리할 수 있다.

```text
기존 5GB DB는 전체 파이프라인 검증과 검색 API 구축을 위한 기준 DB로 활용하였다.
이후 동일 음식 반복과 낮은 음식 다양성 문제를 개선하기 위해 다양성 기반 샘플링 정책을 추가하였다.
그 결과 5gb_v2_diverse DB는 고유 음식 수를 88개에서 541개로 확대했고,
정위/측면 대표 이미지를 균형 있게 확보하여 광고 생성용 Reference DB로서 활용성이 개선되었다.
```


### Reproducibility

The v2 generation path uses `src/utils/reproducibility.py` with seed `42`. The direct v2 generation path is `01`~`08` plus `10`~`15`; `09_make_final_db.py` is for the baseline `5gb` DB.
