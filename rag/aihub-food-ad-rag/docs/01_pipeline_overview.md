# Pipeline Overview

## 목적

70GB AI Hub 음식 이미지 원본 데이터를 광고 프롬프트 생성을 지원하는 Retrieval DB로 변환합니다.

## 전체 단계

1. 메타데이터 파싱
2. EDA 리포트 생성
3. 서비스 카테고리 매핑
4. 이미지 품질 필터링
5. 중복 제거
6. 캡션/조명/구도 태깅
7. CLIP 임베딩 생성
8. FAISS 인덱스 생성
9. 5GB / 10GB / 20GB 최종 DB 생성

## 카테고리 매핑 단계

```text
AI Hub 원본 카테고리
↓
business_category
↓
product_group
↓
product_name
```

## Input

프로젝트는 AI Hub 원본 데이터를 입력으로 사용합니다.

```text
data/
└── raw/
    ├── images/
    └── annotations/
```

| Directory | Description |
| --------- | ----------- |
| `data/raw/images` | AI Hub 원본 이미지 |
| `data/raw/annotations` | AI Hub 원본 JSON Annotation |

---

## Output

전처리 및 벡터화 과정을 거쳐 최종 RAG 데이터베이스를 생성합니다.

```text
data/
└── final_db/
    ├── 5gb/
    ├── 10gb/
    └── 20gb/
```

| Version | Purpose |
| ------- | ------- |
| `5GB` | 빠른 프로토타입 및 개발 |
| `10GB` | 검증 및 발표 |
| `20GB` | 서비스 테스트 및 최종 데이터베이스 |

---

## Key Artifacts

파이프라인 수행 과정에서 다음과 같은 핵심 산출물이 생성됩니다.

```text
raw_metadata.parquet
category_enriched_metadata.parquet
quality_filtered_metadata.parquet
deduplicated_metadata.parquet
tagged_metadata.parquet
embeddings.npy
faiss.index
summary.json
```

| Artifact | Description |
| -------- | ----------- |
| `raw_metadata.parquet` | 원본 JSON을 Parquet 형식으로 변환한 메타데이터 |
| `category_enriched_metadata.parquet` | 서비스 카테고리가 추가된 메타데이터 |
| `quality_filtered_metadata.parquet` | 품질 기준을 통과한 데이터 |
| `deduplicated_metadata.parquet` | 중복 제거가 완료된 데이터 |
| `tagged_metadata.parquet` | 캡션 및 이미지 태그가 추가된 데이터 |
| `embeddings.npy` | OpenCLIP 이미지 임베딩 벡터 |
| `faiss.index` | FAISS 벡터 검색 인덱스 |
| `summary.json` | 데이터셋 통계 및 생성 결과 요약 |
---

## Reproducibility

The v2 generation path scripts `01`~`08` and `10`~`15` call `src/utils/reproducibility.py` and use seed `42`.
