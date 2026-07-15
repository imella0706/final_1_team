# Design

## 설계 목표

AI Hub 음식 이미지 데이터를 단순 보관용 데이터가 아니라 광고 생성 AI가 검색하고 참조할 수 있는 Food Retrieval DB로 재구성한다.

## 핵심 설계 원칙

### 1. 원본 데이터 보존

`data/raw/`의 원본 이미지와 JSON은 수정하지 않는다. 모든 처리 결과는 `data/metadata/`, `data/embeddings/`, `data/final_db/` 아래에 별도로 저장한다.

### 2. 단계별 중간 산출물 저장

각 단계는 독립 실행 가능하도록 설계한다.

```text
parquet: 중간 메타데이터
csv: 사람이 확인하기 쉬운 리포트
json: 단계별 요약
npy: 임베딩 배열
faiss.index: 검색 인덱스
```

### 3. 광고 서비스용 카테고리 매핑

AI Hub 원본 음식명은 광고 서비스에서 바로 쓰기 어렵기 때문에 다음 구조로 변환한다.

```text
business_category
  -> product_group
      -> product_name
```

현재 `business_category`는 다음 5개를 사용한다.

```text
restaurant
cafe
bakery
dessert
pub
```

### 4. 품질 기반 정제

이미지 품질은 다음 항목으로 판단한다.

- 이미지 파일 존재 여부
- 이미지 열기 가능 여부
- 최소 해상도
- Blur Score
- Quality Score

### 5. 중복 제거

pHash를 사용해 동일하거나 매우 유사한 이미지를 제거한다. 이 단계는 검색 결과의 반복 노출을 줄이고 DB 다양성을 높이는 역할을 한다.

### 6. Caption Tagging

BLIP 기반 캡션과 시각 태그를 생성한다.

생성 컬럼:

```text
caption
caption_status
prompt_keywords
caption_lighting
caption_composition
caption_camera_angle
ad_use_case
visual_style_hint
```

### 7. 임베딩과 검색

OpenCLIP `ViT-B-32/openai` 모델을 사용하여 이미지 임베딩을 생성하고, FAISS `IndexFlatIP`로 검색 인덱스를 만든다.

### 8. 다양성 기반 대표 이미지 정책

새로 추가된 10~14단계 스크립트는 기존 DB의 한계를 보완하기 위한 다양성 기반 DB 생성 파이프라인이다.

정책:

```text
1. 음식 종류 다양성 최대화
2. 음식별 정위 1장 + 측면 1장 우선 선택
3. Bounding Box 비율 40~70% 우선
4. 중앙성 점수 우선
5. Blur Score 우선
6. 해상도 우선
```

이 정책은 `data/final_db/5gb_v2_diverse/` DB에 반영되어 있다.

다양성 기반 파이프라인:

| 단계 | 파일 | 역할 |
|---|---|---|
| 10 | `10_prepare_diverse_candidates.py` | 후보 이미지 Feature 생성 |
| 11 | `11_select_diverse_representatives.py` | 음식별 정위/측면 대표 이미지 선택 |
| 12 | `12_build_diverse_embedding_subset.py` | 대표 이미지 임베딩 subset 생성 |
| 13 | `13_build_diverse_faiss.py` | diverse FAISS 인덱스 생성 |
| 14 | `14_make_diverse_final_db.py` | `5gb_v2_diverse` DB 패키징 |
| 15 | `15_export_final_db_assets.py` | 관리용 CSV, LLM JSON, 통합 summary 생성 |

### 9. 최종 관리/LLM Export

`src/15_export_final_db_assets.py`는 완성된 DB 폴더를 읽어 다음 파일을 생성한다.

```text
db_management_inventory.csv
llm_prompt_payloads.json
```

`db_management_inventory.csv`는 사람이 DB 전체를 검수하고 관리하기 위한 파일이고, `llm_prompt_payloads.json`은 LLM 프롬프트 또는 RAG context로 넘기기 위한 JSON 파일이다.

전체 DB 버전 요약은 루트 파일에서 관리한다.

```text
data/final_db/final_db_summary.json
```

## 현재 한계

- 10GB/20GB는 완성 DB가 아니라 구조만 준비되어 있다.
- 기존 5GB DB는 고유 음식 수가 88개로, 음식 다양성이 낮다.
- 현재 검색 API는 CLIP text encoder 기반 검색이 아니다.
- Bounding Box 비율별 Recall@5, Hits@5, MRR 비교 실험은 아직 별도 평가 단계로 남아 있다.

## 개선 방향

- `5gb_v2_diverse`를 기준 DB로 삼아 검색 품질 평가
- Bounding Box 후보 구간별 성능 비교
- CLIP text embedding 검색 추가
- 광고 입력 스키마와 Retrieval DB를 연결하는 end-to-end RAG 파이프라인 구성
