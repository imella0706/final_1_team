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
| 기존 5GB DB | 완료 |
| 다양성 기반 5GB v2 DB | 완료 |
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

### 기존 5GB DB

위치:

```text
data/final_db/5gb/
```

| 항목 | 값 |
|---|---:|
| 실제 이미지 용량 | 약 4.998GB |
| 이미지 수 | 952 |
| 고유 음식 수 | 88 |
| 임베딩 shape | 952 x 512 |

### 다양성 기반 5GB v2 DB

위치:

```text
data/final_db/5gb_v2_diverse/
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

## 주요 실행 순서

```cmd
python src\01_parse_metadata.py
python src\02_eda_report.py
python src\03_build_category_groups.py
python src\04_quality_filter.py
python src\05_remove_duplicates.py
python src\06_caption_tagging.py
python src\07_clip_embedding.py
python src\08_build_faiss.py
python src\09_make_final_db.py --versions 5gb
python src\10_prepare_diverse_candidates.py
python src\11_select_diverse_representatives.py
python src\12_build_diverse_embedding_subset.py
python src\13_build_diverse_faiss.py
python src\14_make_diverse_final_db.py --overwrite
python src\15_export_final_db_assets.py --db-names 5gb,5gb_v2_diverse
```

## 최종 DB 파일 구조

각 완성 DB 폴더는 다음 파일을 포함합니다.

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

`summary.json`은 해당 DB 하나의 생성 결과를 담습니다.

전체 DB 버전 목록과 요약은 아래 루트 파일에서 관리합니다.

```text
data/final_db/final_db_summary.json
```

`db_management_inventory.csv`는 사람이 전체 DB를 검수하고 관리하기 위한 CSV이고, `llm_prompt_payloads.json`은 LLM 프롬프트/RAG 입력으로 넘기기 쉬운 JSON payload입니다.

## DB Export 후처리

`src/15_export_final_db_assets.py`는 DB를 새로 생성하는 스크립트가 아니라, 이미 만들어진 DB 폴더를 읽어 관리용 파일과 LLM 전달용 파일을 추가하는 후처리 스크립트입니다.

완성 DB로 인식되는 조건은 DB 폴더 안에 다음 파일이 있는 것입니다.

```text
metadata.parquet
prompt_metadata.parquet
summary.json
```

새로운 DB를 만든 뒤 아래 명령을 실행하면:

```cmd
python src\15_export_final_db_assets.py --db-names 새로운_db
```

새로운 DB 폴더 안에 다음 파일이 추가됩니다.

```text
data/final_db/새로운_db/
├── db_management_inventory.csv
└── llm_prompt_payloads.json
```

그리고 루트 통합 summary에도 새 DB 정보가 반영됩니다.

```text
data/final_db/final_db_summary.json
```

여러 DB를 함께 갱신하려면 다음처럼 실행합니다.

```cmd
python src\15_export_final_db_assets.py --db-names 5gb,5gb_v2_diverse,새로운_db
```

`--db-names`를 생략하면 `data/final_db/` 아래의 완성 DB 폴더를 자동으로 찾아 export합니다.

## 검색 API

```cmd
python -m app.retrieval_api --db-dir data\final_db\5gb --host 127.0.0.1 --port 7860
```

확인:

```cmd
curl http://127.0.0.1:7860/health
curl http://127.0.0.1:7860/categories
```

## 주의사항

- `data/raw/`, `data/embeddings/`, `data/final_db/`, `data.zip`은 Git에 포함하지 않습니다.
- 현재 텍스트 검색은 CLIP text encoder를 직접 사용하는 구조가 아니라, 메타데이터 필터링과 이미지 임베딩 기반 대표 벡터 검색을 조합합니다.
- Bounding Box 기반 대표 이미지 선정은 `10_prepare_diverse_candidates.py`와 `5gb_v2_diverse` DB에서 반영되었습니다.
