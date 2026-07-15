# Project Report Summary

## 1. 요구사항 분석

목표는 AI Hub 음식 이미지 데이터를 광고 콘텐츠 생성 AI가 참조할 수 있는 Food Retrieval DB로 변환하는 것이다. 사용자는 상품명, 업종, 광고 상황을 입력하고, 시스템은 유사 음식 이미지와 메타데이터를 검색하여 광고 문구 및 이미지 생성 프롬프트의 참고 자료로 제공한다.

## 2. 데이터셋 분석

사용 데이터는 AI Hub `비전영역, 음식이미지 및 정보소개 텍스트 데이터`의 Validation 원천데이터와 라벨링데이터다.

주요 수치:

| 항목 | 값 |
|---|---:|
| JSON | 11,582 |
| 이미지 | 11,582 |
| 고유 음식명 | 643 |
| Food Code | 69 |
| 원본 이미지 용량 | 약 43.74GB |

## 3. 시스템 아키텍처

```text
Raw Image + JSON
 -> Metadata Parsing
 -> EDA
 -> Category Mapping
 -> Quality Filtering
 -> Duplicate Removal
 -> Caption Tagging
 -> CLIP Embedding
 -> FAISS Index
 -> Final DB
 -> Retrieval API / Prompt RAG
```

## 4. DB 설계

완성 DB는 다음 파일을 포함한다.

```text
images/
metadata.parquet
prompt_metadata.parquet
embeddings.npy
faiss.index
mapping.csv
summary.json
final_db_summary.json
```

`metadata.parquet`은 전체 검색 메타데이터, `prompt_metadata.parquet`은 광고 프롬프트 생성용 경량 메타데이터, `embeddings.npy`와 `faiss.index`는 유사 이미지 검색에 사용된다.

## 5. 데이터 전처리 파이프라인

품질 필터링 결과 11,582장 중 7,733장이 통과했고, pHash 기반 중복 제거 후 7,351장이 남았다. 이 7,351장에 대해 BLIP 캡션과 CLIP 임베딩을 생성했다.

## 6. 임베딩 및 검색 시스템 설계

OpenCLIP `ViT-B-32/openai` 모델로 이미지 임베딩을 생성하고 FAISS `IndexFlatIP`로 검색한다. 현재 API는 텍스트를 직접 CLIP text embedding으로 변환하지 않고, 메타데이터 필터링과 후보 이미지 평균 임베딩을 결합해 검색한다.

## 7. 최종 DB 생성 과정

기존 DB는 `src/09_make_final_db.py`로 생성한다. 다양성 기반 DB는 10~14단계로 생성한다.

| 단계 | 파일 | 역할 |
|---|---|---|
| 10 | `10_prepare_diverse_candidates.py` | Bounding Box, 중앙성, view_type 후보 Feature 생성 |
| 11 | `11_select_diverse_representatives.py` | 음식별 정위/측면 대표 이미지 선택 |
| 12 | `12_build_diverse_embedding_subset.py` | 대표 이미지 임베딩 subset 생성 |
| 13 | `13_build_diverse_faiss.py` | diverse FAISS 인덱스 생성 |
| 14 | `14_make_diverse_final_db.py` | `5gb_v2_diverse` DB 생성 |
| 15 | `15_export_final_db_assets.py` | 관리 CSV, LLM JSON, 통합 summary 생성 |

전체 DB 목록과 요약은 아래 파일에서 관리한다.

```text
data/final_db/final_db_summary.json
```

## 8. 실험 및 결과

### 기존 5GB DB

| 항목 | 값 |
|---|---:|
| 이미지 수 | 952 |
| 실제 용량 | 약 4.998GB |
| 고유 음식 수 | 88 |

### 다양성 기반 5GB v2 DB

| 항목 | 값 |
|---|---:|
| 이미지 수 | 1,036 |
| 실제 용량 | 약 4.441GB |
| 고유 음식 수 | 541 |
| 정위 이미지 | 522 |
| 측면 이미지 | 514 |
| 정위/측면 모두 확보된 음식 | 495 |

## 9. 최종 산출물 구조

```text
data/final_db/5gb/
data/final_db/5gb_v2_diverse/
```

10GB/20GB는 구조만 준비되어 있으며, 현재 완성 DB로 보지는 않는다.

각 완성 DB에는 다음 추가 관리 파일이 포함된다.

```text
db_management_inventory.csv
llm_prompt_payloads.json
```

## 10. 서비스 활용 방안

Retrieval DB는 광고 생성 시스템에서 Reference DB 역할을 한다.

```text
사용자 입력
 -> 상품명/업종 기반 검색
 -> 유사 음식 이미지 및 메타데이터 반환
 -> 광고 문구 프롬프트 구성
 -> 이미지 생성 프롬프트 구성
```

## 11. 한계점 및 개선 방향

- 기존 5GB DB는 음식 다양성이 낮다.
- v2 DB는 다양성을 개선했지만 검색 성능 평가는 추가로 필요하다.
- Bounding Box 비율별 Hits@5, Recall@5, MRR 평가가 필요하다.
- CLIP text encoder 기반 검색을 추가하면 텍스트-이미지 검색 품질을 더 명확히 평가할 수 있다.
