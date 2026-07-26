# BrandMate Dataset Convention Onboarding
update: 2026.07.19

이 문서는 BrandMate 팀원이 데이터셋을 만들고 공유할 때 지켜야 하는 공통 규칙입니다.

핵심은 하나입니다. 데이터 파일만 공유하지 않습니다. 데이터셋을 GCS/DVC에 등록하거나 팀에 공유할 때는 데이터, 설명, 재현 정보를 같이 남깁니다.

## 1. 제출물

데이터셋을 공유할 때는 아래 4가지를 같이 준비합니다.

```text
1. 데이터 파일
2. manifest.json
3. description.md
4. 데이터셋을 다시 만들 수 있는 관련 코드 또는 노트북 경로
```

- `manifest.json`: GCS/DVC/자동화 스크립트가 읽기 좋은 컴퓨터용 기록입니다.
- `description.md`: 팀원이 데이터셋 목적, 선별 이유, 전처리 의도, 한계, 다음 버전 계획을 빠르게 이해하기 위한 설명 문서입니다.
- 관련 코드: Python script, shell script, Jupyter Notebook, Colab Notebook 링크 중 하나입니다.

## 2. 저장 위치 정책

| 항목 | Git | GCS | DVC | 기준 |
| --- | --- | --- | --- | --- |
| 코드 | O | X | X | 서비스/평가/전처리 코드는 Git에서 관리 |
| 데이터셋 생성 스크립트 경로 | O | X | X | 재현 코드는 Git에서 리뷰하고 버전관리 |
| `manifest.json` | O | O | X | Git은 리뷰/이력 관리, GCS는 데이터셋 패키지 설명용 |
| `description.md` | O | O | X | Git은 리뷰/이력 관리, GCS는 사람이 데이터셋을 바로 이해하기 위한 설명용 |
| 직접 수집한 landing/raw 데이터 | X | O | 필요 시 | SNS 크롤링처럼 팀이 직접 수집한 원본 입고 데이터는 GCS에 보관 |
| 공식 URL로 재확보 가능한 대용량 raw 데이터 | X | 링크로 대체 | X | AIHub 등 공식 제공처에서 다시 받을 수 있는 대용량 raw는 팀프로젝트 비용 문제로 GCS에 올리지 않고 출처 URL과 재현 방법을 기록 |
| curated 데이터 | X | O | 필요 시 | 공식 baseline 후보 풀로 고정할 때만 DVC 추적 |
| processed 데이터 | X | O | O | 모델/평가/검색/API가 바로 쓰는 공식 산출물은 DVC로 버전 추적 |
| 이미지/Parquet/Embedding/FAISS | X | O | O | 대용량 processed 산출물은 GCS에 저장하고 DVC로 버전 추적 |
| DVC metadata 파일 | O | X | X | `.dvc`, `dvc.yaml`, `dvc.lock`은 Git에서 관리 |

짧게 정리하면 아래 정책입니다.

```text
스크립트는 Git only
데이터는 GCS
공식 processed 산출물은 DVC
설명 문서는 Git + GCS
```

### DVC 추적 기준

> 이 문서는 데이터셋 담당자가 DVC 대상 여부를 판단하기 위한 정책만 설명합니다.
> 실제 DVC 명령어와 remote 운영 절차는 [GCS_MLOPS_ONBOARDING.md](./GCS_MLOPS_ONBOARDING.md)를 따릅니다.

DVC는 모든 중간 데이터를 무조건 등록하는 도구가 아닙니다.
Git commit과 실험/서비스에 사용한 데이터 버전을 연결해야 할 때 사용합니다.

| 데이터 종류 | DVC 기본 정책 | 이유 |
| --- | --- | --- |
| `landing` | 기본적으로 DVC 추적하지 않음 | 주기적으로 계속 들어오는 입고 데이터라 매 실행마다 DVC 버전을 만들면 관리 비용이 커짐 |
| `raw` | 필요 시에만 DVC 추적 | 외부 원본 전체를 장기 재현해야 하거나 원본 삭제 위험이 있을 때만 추적 |
| `curated` | 공식 baseline 후보 풀로 고정할 때만 DVC 추적 | 후보 풀 단계는 바뀔 수 있으므로 모든 임시본을 DVC로 잡지 않음 |
| `processed` | 공식 산출물은 DVC 추적 | 모델/평가/검색/API가 직접 소비하므로 코드 버전과 데이터 버전을 연결해야 함 |
| `eval` | 공식 평가셋이면 DVC 추적 | 평가 기준이 바뀌면 성능 비교가 깨지므로 버전 고정 필요 |

현재 프로젝트의 기본 운영 기준은 아래와 같습니다.

```text
직접 수집한 landing/raw = GCS 보관 중심
공식 URL로 재확보 가능한 대용량 raw = 링크와 재현 방법으로 대체 가능
curated = 공식 baseline으로 고정할 때만 DVC
processed = 실험/서비스에서 바로 쓰는 공식 산출물이면 DVC 필수
```

### 팀프로젝트 DVC 운영 범위

현재 팀프로젝트 기간과 운영 복잡도를 고려해 DVC 추적 대상은 공식 `processed` 산출물로 한정합니다.
`curated` 데이터는 GCS에 보관하고, `processed` manifest의 `processing.input_dataset`,
`curation.curated_inputs`, `reproducibility.generation_script_path`에 입력 경로와 생성 코드를 기록합니다.

이 판단을 한 이유는 아래와 같습니다.

- 프로젝트 기간이 2026-07-30까지로 제한되어 있어 `curated`까지 DVC로 고정하면 등록/검수/충돌 해결 비용이 커집니다.
- `landing`과 `curated`는 수집과 정리 과정에서 자주 바뀌므로 모든 중간본을 DVC로 추적하면 pointer가 과도하게 늘어납니다.
- 팀원이 DVC에 익숙하지 않은 상태에서 raw/curated/processed를 모두 추적하면 운영 실수가 생기기 쉽습니다.
- 실험과 서비스 재현성에 직접 영향을 주는 것은 최종적으로 모델/API/RAG가 소비하는 `processed` 산출물입니다.
- 따라서 현재 단계에서는 `processed`를 우선 고정하고, `curated` 계보는 GCS 경로와 manifest/description 문서로 추적합니다.

이 구조의 한계도 명확히 기록합니다.

- 현재 구조에서는 `processed` 산출물이 어떤 `curated` 경로에서 생성되었는지는 추적할 수 있습니다.
- 하지만 `curated` 데이터 자체의 DVC hash까지 고정하지는 않습니다.
- 따라서 완전한 DVC lineage, 즉 `curated` hash → `processed` hash 연결은 다음 운영 고도화 범위로 둡니다.

추후 운영 고도화 시에는 아래 구조로 확장합니다.

```text
curated DVC 추적
→ processed DVC 추적
→ dvc.yaml / dvc.lock으로 curated → processed lineage 고정
```

## 3. 역할과 등록 흐름

데이터셋 등록은 MLOps/인프라 담당자가 전부 대신 처리하는 구조로 운영하지 않습니다.
MLOps 담당자는 구조와 규칙을 만들고, 데이터셋 담당자는 자기 데이터를 그 규칙에 맞춰 등록합니다.
다만 현재 팀프로젝트 범위에서는 DVC 등록과 DVC remote 업로드는 MLOps/인프라 담당자가 관리합니다.

| 역할 | 책임 |
| --- | --- |
| MLOps/인프라 담당자 | GCS 폴더 구조 설계, raw/curated/processed 기준 정의, manifest/description 템플릿 제공, DVC 등록 방식 정의, Airflow 기준 설계, 예시 데이터셋 등록 |
| 데이터셋 담당자 | 본인 데이터 단계 판단, 데이터 파일 정리, manifest/description 작성, 생성 코드 또는 노트북 경로 제출, 원본 출처/선별 기준/한계 직접 검수 |
| MLOps/인프라 담당자 | PR 또는 등록 결과 리뷰, 폴더 구조/manifest/DVC pointer가 규칙에 맞는지 확인 |

권장 등록 흐름은 아래와 같습니다.

```text
1. 데이터셋 담당자가 v1/v2 등 버전별 폴더 구조 초안을 만든다.
2. 데이터셋 담당자가 raw / curated / processed 단계를 판단한다.
3. 데이터셋 담당자가 manifest.json, description.md, 생성 코드 경로를 준비한다.
4. MLOps/인프라 담당자가 폴더 구조, 데이터 단계, metadata 필드를 1차 검수한다.
5. 검수 후 데이터셋 담당자가 승인된 구조대로 GCS에 업로드한다.
6. MLOps/인프라 담당자가 공식 processed 산출물을 DVC로 등록한다.
7. MLOps/인프라 담당자가 .dvc pointer, manifest, description을 최종 PR 리뷰한다.
```

초기 운영에서는 MLOps/인프라 담당자가 예시 데이터셋 1~2개를 같이 등록해 기준을 잡습니다.
이후 팀원의 데이터셋 관리 숙련도가 충분하고 충돌 위험이 낮아졌을 때는 데이터셋 담당자도 DVC 등록을 수행할 수 있습니다.
그 전까지는 DVC 등록, `dvc push`, DVC remote 권한/복구는 MLOps/인프라 담당자가 관리합니다.

### 초기 DVC 중앙 관리 원칙

현재 팀프로젝트 초기 단계에서는 DVC 등록과 `dvc push`를 MLOps/인프라 담당자가 중앙에서 관리합니다.

DVC는 단순 데이터 업로드 도구가 아니라 Git commit과 데이터 hash를 연결하는 버전관리 절차입니다.
데이터셋 구조, `manifest.json`, `description.md`가 아직 자주 바뀌는 단계에서 각 데이터셋 담당자가 직접
`dvc add`와 `dvc push`를 수행하면 아래 문제가 생길 수 있습니다.

- `.dvc` pointer 충돌
- GCS readable path와 DVC remote의 데이터 불일치
- Git에 실제 데이터 파일을 잘못 추가하는 실수
- metadata 수정 후 DVC pointer를 갱신하지 않아 Git commit과 데이터 버전이 어긋나는 문제
- 여러 사람이 같은 processed artifact를 수정하면서 어떤 데이터 버전이 공식인지 불명확해지는 문제

따라서 초기에는 데이터셋 담당자가 폴더 구조 초안, metadata 작성, 생성 코드 경로 정리, GCS 업로드까지 수행하고, MLOps/인프라 담당자가 최종 검수 후 DVC 등록과 `.dvc` pointer 갱신을 처리합니다.

이 정책은 데이터셋 담당자의 작업을 제한하려는 목적이 아니라, 데이터 구조가 안정화되기 전까지
데이터 버전 충돌과 복구 비용을 줄이기 위한 운영 기준입니다.

데이터셋 구조가 안정화되고 팀원이 DVC 운영 흐름에 익숙해진 뒤에는 데이터셋 담당자도 DVC 등록을 수행할 수 있도록 전환할 예정입니다. 

## 4. 데이터 단계

| 단계 | 의미 | 예시 |
| --- | --- | --- |
| `raw` | 외부에서 받은 원본 전체 | AIHub 원본 전체, SNS 전체 크롤링 원본 |
| `curated` | raw에서 프로젝트 목적에 맞는 데이터만 선별한 단계 | SNS 크롤링 결과 중 사람이 검수해 밈/트렌드 데이터만 고른 subset |
| `processed` | curated를 모델/평가/검색/API 파이프라인이 바로 읽을 수 있게 구조화하거나 변환한 단계 | JSONL/Parquet 변환, 필드명 통일, 텍스트 정제, OCR, resize, crop, metadata 정리. 검색/RAG용이면 embedding 생성, FAISS index 생성 포함 |

짧게 정리하면 아래 기준입니다.

```text
가져온 것 = raw
쓸 것만 고른 것 = curated
모델/파이프라인이 바로 사용할 수 있도록 바꾼 것 = processed
```

중요한 기준은 "처리를 했는가"가 아니라 "어디에서 소비되는 데이터인가"입니다.

팀 컨벤션상 null 제거, 중복 제거, 불필요 컬럼 제거, source별 정리, 후보 keyword 추출처럼
프로젝트에 쓸 후보 데이터를 고르고 정리하는 작업은 curated 단계로 봅니다.

기술적으로는 전처리라고 볼 수 있어도, 실제 모델/API/RAG 파이프라인이 바로 소비하는 최종 산출물이 아니면 우리 팀에서는 curated로 분류합니다.

반면 score/ranking 계산, query 결과 구조화, embedding 생성, FAISS index 생성,
RAG/LLM 입력용 변환처럼 프로젝트 파이프라인에서 바로 소비할 수 있는 산출물은 processed 단계로 봅니다.

SNS 데이터 기준으로 보면 아래처럼 판단합니다.

```text
raw/sns/
= 처음 크롤링한 전체 원본 HTML, 이미지, 원문 JSON, 스크린샷

curated/sns/v1/
= 사람이 보거나 규칙으로 걸러 "이건 밈/트렌드 데이터로 쓸 수 있다"고 정리한 subset
= null/중복/불필요 컬럼 제거, source별 정리, 후보 keyword 추출 데이터

processed/sns/v1/
= 모델/API/RAG/LLM이 바로 읽을 수 있게 만든 jsonl/parquet/csv
= signal scored ranking, query ranked candidates, embedding, FAISS index, prompt input dataset
```

## 5. Manifest 공통 형식

`manifest.json`은 아래 공통 형식을 기본으로 사용합니다.

```json
{
  "dataset_name": "TODO",
  "version": "v1",
  "dataset_stage": "raw | curated | processed",
  "status": "experimental | baseline | stable | deprecated",
  "artifact_role": "optional: source_pool | smoke_sample | mvp_sample | train_dataset | eval_subset | retrieval_index | api_payload",
  "owner": "TODO",
  "created_at": "YYYY-MM-DD",
  "source": {
    "provider": "TODO",
    "source_name": "TODO",
    "source_url": "TODO",
    "source_split": "TODO",
    "raw_uploaded_to_gcs": false,
    "annotation_preserved": "TODO"
  },
  "curation": {
    "selected_count": "TODO",
    "target_size_gb": "TODO",
    "actual_size_gb": "TODO",
    "selection_policy": "TODO",
    "category_balanced": "TODO",
    "quality_filters": [],
    "path_mapping_available": "TODO"
  },
  "processing": {
    "input_dataset": "TODO",
    "artifact_name": "TODO",
    "target_use": "training | evaluation | generation | api | retrieval | analysis",
    "preprocessing_steps": [],
    "output_files": []
  },
  "storage": {
    "gcs_path": "TODO",
    "local_example_path": "TODO",
    "dvc_tracked": false
  },
  "reproducibility": {
    "generation_script_available": "TODO",
    "generation_script_path": "TODO",
    "random_seed": "none | TODO | integer",
    "can_rebuild": "TODO"
  },
  "limitations": [],
  "next_version_plan": "TODO"
}
```

### Manifest 작성 예시

아래 예시는 SNS 트렌드 데이터셋 기준 예시입니다.
다른 데이터셋은 그대로 복사하지 말고, 공통 형식은 유지하되 본인 데이터셋에 필요한 항목을 추가해서 작성해주세요.
AI가 모르는 값은 추측하지 말고 `TODO`로 남겨주세요.

```json
{
  "dataset_name": "sns_trend",
  "version": "v1",
  "dataset_stage": "processed",
  "status": "baseline",
  "owner": "Chaebin",
  "created_at": "2026-07-16",
  "source": {
    "provider": "manual_crawl",
    "source_name": "sns_trend_week_2026-W28",
    "source_url": "multiple_sources",
    "source_split": "none",
    "raw_uploaded_to_gcs": true,
    "annotation_preserved": "none",
    "platforms": ["youtube", "gogumafarm", "careet", "naver"],
    "crawl_period": {
      "timezone": "Asia/Seoul",
      "start_date": "2026-07-07",
      "end_date": "2026-07-09",
      "week": "2026-W28"
    }
  },
  "curation": {
    "selected_count": "TODO",
    "target_size_gb": "none",
    "actual_size_gb": "TODO",
    "selection_policy": "null/중복/불필요 컬럼 제거 후 플랫폼별 후보 데이터 정리",
    "category_balanced": "none",
    "quality_filters": ["null 제거", "중복 제거", "불필요 컬럼 제거"],
    "path_mapping_available": true
  },
  "processing": {
    "input_dataset": "sns_trend_curated_v1",
    "artifact_name": "cross_platform_signal_top_candidates",
    "target_use": "retrieval",
    "preprocessing_steps": [
      "platform별 후보 통합",
      "platform별 signal score 정량화",
      "query 기준 후보 검색",
      "상위 점수 후보 구조화",
      "JSON 결과를 CSV로 flatten"
    ],
    "output_files": [
      "cross_platform_signal_top_candidates.json",
      "cross_platform_signal_top_candidates.csv"
    ],
    "input_platforms": ["youtube", "gogumafarm", "careet", "naver"],
    "result_platforms": ["gogumafarm", "naver", "youtube"]
  },
  "storage": {
    "gcs_path": "gs://ssakda/projects/brandmate/data/processed/sns_trend/v1/cross_platform_signal_top_candidates/",
    "local_example_path": "data/processed/sns_trend/v1/cross_platform_signal_top_candidates/",
    "dvc_tracked": false
  },
  "reproducibility": {
    "generation_script_available": true,
    "generation_script_path": "demo/trend_ad/pipeline.py",
    "random_seed": "none",
    "can_rebuild": "partial"
  },
  "limitations": [
    "현재 export는 특정 demo query 기준 상위 후보 결과이며 전체 global ranking 데이터셋은 아닙니다.",
    "curated 데이터는 현재 DVC로 추적하지 않고 GCS 경로와 metadata로 계보를 관리합니다."
  ],
  "next_version_plan": "주기적 크롤링 자동화, cross-platform signal scoring 확장, score 기준 top-N 보존 정책 정의"
}
```

### 필드 설명

| 필드 | 의미 | 작성 예시 |
| --- | --- | --- |
| `dataset_name` | 데이터셋 이름입니다. 버전과 산출물 종류는 넣지 않습니다. | `sns_trend`, `aihub_food_image_text` |
| `version` | 데이터셋 release 번호입니다. 새 데이터가 들어왔거나, 선별 기준/생성 코드/출력 구조/사용 목적이 달라져 기존 버전과 구분해야 하면 `v2`, `v3`로 올립니다. 단, 매일/매주 자동으로 누적되는 운영 데이터는 version을 매번 올리기보다 `date`, `week`, `month` 같은 partition으로 관리할 수 있습니다. | `v1` |
| `dataset_stage` | 데이터 단계입니다. 원본 전체면 `raw`, 선별본이면 `curated`, 모델이 바로 쓰는 가공본이면 `processed`입니다. | `curated` |
| `status` | 현재 버전의 운영 상태입니다. 기능 확인/탐색용은 `experimental`, 첫 공식 기준점은 `baseline`, 안정화된 버전은 `stable`, 더 이상 쓰지 않으면 `deprecated`입니다. | `baseline` |
| `artifact_role` | 선택 필드입니다. 같은 `dataset_name/version/stage` 아래에 여러 artifact가 있을 때 이 artifact의 역할을 구분합니다. | `source_pool`, `smoke_sample`, `mvp_sample`, `train_dataset`, `eval_subset`, `retrieval_index`, `api_payload` |
| `owner` | 데이터셋 생성/관리 담당자입니다. | `giwoo`, `chaebin` |
| `created_at` | 데이터셋 생성일입니다. | `2026-07-13` |
| `source.provider` | 원본 제공처입니다. | `AIHub`, `Instagram`, `Kaggle`, `manual_crawl` |
| `source.source_name` | 원본 데이터셋 또는 수집 작업 이름입니다. | `비전영역 음식이미지 및 정보소개 텍스트 데이터`, `sns_meme_crawl_202607` |
| `source.source_url` | 원본 URL입니다. 없으면 `TODO`로 둡니다. | `https://aihub.or.kr/...` |
| `source.source_split` | 원본에서 사용한 split입니다. 해당 없으면 `none` 또는 `TODO`입니다. | `train`, `validation`, `none` |
| `source.raw_uploaded_to_gcs` | raw 원본 전체를 GCS에 올렸는지 여부입니다. | `false` |
| `source.annotation_preserved` | 원본 annotation/label 파일을 보존했는지 여부입니다. | `true`, `false`, `TODO` |
| `curation.selected_count` | 선별한 데이터 개수입니다. 이미지면 장수, row 데이터면 row 수입니다. | `952` |
| `curation.target_size_gb` | 목표 용량입니다. 목표가 없으면 `TODO`입니다. | `5.0` |
| `curation.actual_size_gb` | 실제 데이터 용량입니다. | `4.99` |
| `curation.selection_policy` | 어떤 기준으로 골랐는지 적습니다. | `5GB까지 랜덤 선별 후 품질 필터 적용` |
| `curation.category_balanced` | 카테고리 균형을 맞췄는지 여부입니다. | `true`, `false`, `TODO` |
| `curation.quality_filters` | 제외/필터링 기준입니다. | `["blur 제거", "중복 제거"]` |
| `curation.path_mapping_available` | 원본 경로와 최종 파일 경로를 연결할 수 있는지 여부입니다. | `true` |
| `processing.input_dataset` | processed 데이터셋이면 입력으로 사용한 curated/raw 데이터셋 이름입니다. | `aihub_food_image_text_curated_v1` |
| `processing.artifact_name` | processed 단계에서 만들어진 산출물 이름입니다. 같은 데이터셋에서 여러 산출물이 생길 수 있으므로 dataset 이름과 분리합니다. | `food_description_data`, `train_dataset`, `eval_subset` |
| `processing.target_use` | 데이터셋 사용 목적입니다. | `training`, `evaluation`, `generation`, `api`, `retrieval`, `analysis` |
| `processing.preprocessing_steps` | 수행한 전처리 단계입니다. | `["resize", "OCR", "parquet 변환"]` |
| `processing.output_files` | 생성된 주요 파일 목록입니다. | `["metadata.csv", "images/", "summary.json"]` |
| `storage.gcs_path` | GCS에 업로드될 위치입니다. | `gs://ssakda/projects/brandmate/data/processed/sns/v1/` |
| `storage.local_example_path` | 로컬 예시 경로입니다. | `~/final_1_team/data/sns_meme_v1` |
| `storage.dvc_tracked` | DVC로 추적하는지 여부입니다. | `false` |
| `reproducibility.generation_script_available` | 재생성 스크립트가 있는지 여부입니다. | `true`, `false` |
| `reproducibility.generation_script_path` | 재생성 스크립트나 노트북 경로입니다. | `scripts/build_sns_dataset.py`, `Colab URL` |
| `reproducibility.random_seed` | 랜덤 샘플링/랜덤 분할을 썼다면 seed입니다. 랜덤 과정이 없으면 `none`, 썼지만 값을 모르면 `TODO`입니다. | `42`, `none`, `TODO` |
| `reproducibility.can_rebuild` | 같은 결과를 다시 만들 수 있는지 여부입니다. | `true`, `false`, `partial` |
| `limitations` | 현재 데이터셋의 한계입니다. 숨기지 말고 적습니다. | `["카페 메뉴 데이터 부족"]` |
| `next_version_plan` | 다음 버전에서 보강할 내용입니다. | `카페/베이커리 메뉴 추가 수집` |

### Status 값 기준

`status`는 데이터 단계나 artifact 역할이 아니라 운영 상태를 뜻합니다. 아래 4개 값만 사용합니다.

| status | 의미 | 예시 |
| --- | --- | --- |
| `experimental` | 기능 확인/탐색용. 공식 비교 기준 아님 | `c0241_20210802` 8개 smoke sample |
| `baseline` | 팀이 첫 공식 기준점으로 삼는 데이터 | `ju_ja_validation_selected` 후보 풀 또는 첫 processed 분석 결과 |
| `stable` | 반복 실험/서비스/API에서 계속 쓰기로 고정한 버전 | 최종 dashboard/RAG/API 입력 데이터 |
| `deprecated` | 더 이상 사용하지 않는 데이터 | 구조 변경 전 v1, 잘못된 샘플 |

### 작성 기준

- `manifest.json`은 자동화/검색/검증에 쓰는 컴퓨터용 기록이므로 영어 중심으로 작성합니다.
- `description.md`는 팀원이 읽는 설명 문서이므로 한국어 중심으로 작성합니다. 단, 모델명, 파일명, GCS path, 코드 경로는 원문 그대로 씁니다.
- AI가 추측해서 값을 채우는 것은 금지하고, AI가 확실히 알 수 없는 값은 `TODO`로 남깁니다. 
- `TODO` 항목은 데이터셋 담당자가 직접 확인해서 채웁니다.
- `none`은 해당 항목이 이 데이터셋에는 적용되지 않는다는 뜻입니다.
- `TODO`는 해당 항목이 필요하지만 아직 값을 모른다는 뜻입니다.
- `curated` 데이터셋이면 `processing` 쪽은 비워도 됩니다.
- `processed` 데이터셋이면 `input_dataset`, `artifact_name`, `preprocessing_steps`, `output_files`는 꼭 적어주세요.
- 같은 dataset/version 아래에 후보 풀, MVP sample, 평가 subset처럼 여러 목적의 artifact를 함께 둘 때는 `artifact_role`을 추가합니다.
- `limitations`에는 현재 데이터셋의 한계를 솔직하게 적어주세요.
- `next_version_plan`에는 다음 버전에서 보강할 점을 적어주세요.
- 공통 manifest 형식은 최소 필수 규격입니다. 데이터셋 특성상 추가로 기록해야 하는 정보가 있으면 `manifest.json`에 별도 section을 추가해주시기 바랍니다. 
  예: `retrieval`, `embedding`, `faiss_index`, `image_processing`, `text_processing`, `evaluation_policy`
- 추가 section을 만들 때는 왜 필요한지 `description.md`에도 같이 설명합니다.

### AI 초안 생성 프롬프트

AI로 `manifest.json`과 `description.md` 초안을 만들 때는
[DATASET_METADATA_DRAFT_PROMPT.md](./DATASET_METADATA_DRAFT_PROMPT.md)를 사용합니다.

AI 결과는 초안입니다. `TODO` 항목과 원본 출처, 선별 기준, 전처리 기준, 현재 한계, 다음 버전 계획은 데이터셋 담당자가 직접 검수합니다.

## 6. Description 공통 형식

- `description.md`는 사람이 읽는 설명 문서입니다. 아래 구조를 기본으로 사용합니다.
- 실제 description.md 작성 시 `TODO` 항목을 본인 데이터셋 정보로 채워주세요.
- 아래 공통 형식은 실제 description.md에 복사해서 사용할 수 있는 기본 구조입니다.
- DVC 추적 상태는 데이터셋 담당자 작성 항목이 아닙니다. MLOps/인프라 담당자가 최종 등록 후 `manifest.json`의 `storage.dvc_tracked`에서 관리합니다.

```md
# {dataset_name} {version} Description

## Summary
(데이터셋이 무엇인지 설명하고, 어디에 활용되는지 적습니다. 한 문장으로 끝내도 되고, 필요한 경우 여러 문장으로 설명해도 됩니다.)

- 데이터셋 개요: TODO
- 활용 방식: TODO

## Dataset Stage
- 단계: (raw / curated / processed 중 하나를 작성합니다.)
- 판단 근거: (해당 단계를 선택한 이유를 작성합니다.)

## Files
- 주요 파일 목록: (주요 파일 또는 디렉터리 이름을 작성합니다.)
- row/image 개수: (row 수 또는 이미지 장수를 작성합니다.)
- 전체 용량: (데이터셋 전체 용량을 작성합니다.)
- 파일별 역할: (각 주요 파일이 어떤 용도인지 작성합니다.)

## Source
- 원본 제공처: (원본 제공처를 작성합니다.)
- 원본 데이터셋 이름: (원본 데이터셋 또는 수집 작업 이름을 작성합니다.)
- 원본 URL: (원본 URL을 작성합니다. 없으면 `없음` 또는 `TODO`로 표시합니다.)
- 사용 split: (사용한 split을 작성합니다. 해당 없으면 `없음`으로 표시합니다.)
- raw 원본 GCS 업로드 여부: (업로드했다면 `예`, 아니면 `아니오`를 작성합니다.)
- 원본 annotation/label 보존 여부: (보존 여부를 작성합니다.)

## Curation
- 선별 기준: (데이터를 선택한 기준을 작성합니다.)
- 제외 기준: (제외하거나 필터링한 기준을 작성합니다.)
- 카테고리 균형 여부: (균형 적용 여부와 방식을 작성합니다.)
- 원본 경로와 최종 경로 매핑 가능 여부: (매핑 가능 여부와 매핑 파일 위치를 작성합니다.)

## Processing
- 입력 데이터셋: (입력 raw 또는 curated 데이터셋 경로/이름을 작성합니다.)
- 사용 목적: (training / evaluation / generation / api / retrieval / analysis 중 사용 목적을 작성합니다.)
- 전처리 기준: (전처리의 목적과 적용 기준을 작성합니다.)
- 전처리 단계: (실행한 전처리 단계를 순서대로 작성합니다.)
- 생성 파일: (생성한 주요 파일을 작성합니다.)
- 사용한 모델/도구: (사용 모델, 라이브러리, 서비스 또는 도구를 작성합니다.)
- 모델/평가/검색/API에서 사용하는 방식: (실제 소비 파이프라인과 사용 방식을 작성합니다.)

## Dataset-Specific Fields
(공통 manifest에 없는 데이터셋 전용 정보를 설명합니다. 예: retrieval, embedding, faiss_index, image_processing, text_processing, evaluation_policy)

## Storage
- GCS 업로드 예정 경로: (승인 후 업로드할 GCS 경로를 작성합니다. 아직 경로가 정해지지 않았다면 추측하지 말고 `TODO`로 남깁니다.)
- local example path: (로컬 예시 경로를 작성합니다.)

## Reproducibility
- 데이터셋 생성 스크립트 또는 노트북 경로: (재생성 코드 또는 노트북 경로를 작성합니다.)
- random seed: (사용한 seed를 작성합니다. 랜덤 과정이 없으면 `없음`으로 표시합니다.)
- 같은 결과를 다시 만들 수 있는지: (가능 / 부분 가능 / 불가능과 그 이유를 작성합니다.)

## Limitations
(현재 데이터셋의 한계를 작성합니다.)

## Next Version Plan
(다음 버전에서 보강할 내용을 작성합니다.)
```

### Description 작성 예시

아래는 SNS 트렌드 processed 데이터셋의 작성 예시입니다. 실제 description.md에는 예시 값을 그대로 복사하지 말고, 본인 데이터셋의 확인된 값으로 작성해주세요.

```md
## Summary

- 데이터셋 개요: YouTube, 고구마팜, 캐릿, 네이버에서 수집한 SNS/콘텐츠 트렌드 후보 데이터입니다.
- 활용 방식: 광고 문구 생성과 밈 기반 프롬프트 조립을 위한 트렌드 후보 검색/랭킹에 활용합니다.

## Dataset Stage
- 단계: processed
- 판단 근거: 여러 플랫폼 후보를 merge하고 signal score 기준으로 상위 후보 결과를 구조화했기 때문에 실제 프롬프트/RAG 파이프라인에서 바로 사용할 수 있는 processed 산출물입니다.

## Files
- 주요 파일 목록:
  - cross_platform_signal_top_candidates.json
  - cross_platform_signal_top_candidates.csv
- row/image 개수: 5 rows
- 전체 용량: TODO
- 파일별 역할:
  - cross_platform_signal_top_candidates.json: 여러 플랫폼 후보를 merge한 뒤 signal score 기준 상위 후보, query, selected_card_id를 포함한 원본 구조화 결과입니다.
  - cross_platform_signal_top_candidates.csv: Airflow 검증과 사람이 확인하기 쉽도록 JSON을 flat table 형태로 펼친 파일입니다.
```

위 공통 형식은 공유 전 검수해야 하는 핵심 항목을 모두 포함합니다.

| 검수 항목 | description.md 위치 |
| --- | --- |
| 데이터셋 목적 | `Summary` |
| 파일 목록 | `Files` |
| row/image 개수 | `Files` |
| 용량 | `Files` |
| 원본 출처 | `Source` |
| 데이터 단계 | `Dataset Stage` |
| 선별 기준 | `Curation` |
| 전처리 기준 | `Processing` |
| 생성 스크립트 또는 노트북 경로 | `Reproducibility` |
| 현재 한계 | `Limitations` |
| 다음 버전 계획 | `Next Version Plan` |

`description.md`의 목적은 사람에게 맥락을 전달하는 것입니다. `manifest.json`에 구조화된 값이 있더라도, 왜 그렇게 선별/전처리했는지와 현재 한계는 문장으로 설명합니다.

## 7. 공유 전 검수 항목

데이터셋 공유 전 아래 항목은 담당자가 최종 확인합니다.

| 항목 | 검수 이유 |
| --- | --- |
| 데이터셋 목적 | 사용처가 불명확하면 GCS 위치와 평가 기준이 흔들림 |
| 파일 목록 | 누락 파일이나 불필요한 파일 확인 |
| row/image 개수 | manifest 수치와 실제 데이터 불일치 방지 |
| 용량 | GCS 비용과 VM 디스크 사용량 판단 |
| 원본 출처 | 라이선스, 재현성, 데이터 계보 확인 |
| 데이터 단계 | raw / curated / processed 위치 결정 |
| 선별 기준 | 데이터 편향과 품질 기준 추적 |
| 전처리 기준 | 모델 성능 변화 원인 추적 |
| 생성 스크립트 또는 노트북 경로 | 재생성 가능성 확인 |
| 현재 한계 | 모델/서비스 결과 해석 시 오해 방지 |
| 다음 버전 계획 | v2 개선 방향 명확화 |

특히 원본 출처, 선별 기준, 전처리 기준, 현재 한계, 다음 버전 계획은 AI가 파일 목록만 보고 정확히 알 수 없습니다.

## 8. GCS 위치

데이터셋 담당자가 새 데이터셋 폴더 구조를 잡을 때는 이 섹션을 기준으로 합니다.
즉, 팀원이 `raw`, `curated`, `processed` 중 어디에 둘지 판단하고 `manifest.storage.gcs_path`를 작성할 때는
이 문서를 먼저 봅니다.

MLOps/인프라 담당자용 전체 bucket 구조, DVC remote, 권한, 업로드/복구 절차는
[GCS_MLOPS_ONBOARDING.md](./GCS_MLOPS_ONBOARDING.md)를 따릅니다.

| 상황 | 먼저 볼 문서 |
| --- | --- |
| 데이터셋 담당자가 자기 데이터의 폴더 구조 초안을 만들 때 | `GCS_DATASET_CONVENTION_ONBOARDING.md` |
| `raw / curated / processed` 단계를 판단할 때 | `GCS_DATASET_CONVENTION_ONBOARDING.md` |
| `manifest.json`, `description.md`를 작성할 때 | `GCS_DATASET_CONVENTION_ONBOARDING.md` |
| 실제 GCS bucket 전체 구조, 권한, DVC remote를 관리할 때 | `GCS_MLOPS_ONBOARDING.md` |
| `dvc add`, `dvc push`, DVC pointer 갱신 기준을 확인할 때 | `GCS_MLOPS_ONBOARDING.md` |

`manifest.storage.gcs_path`에는 아래 규칙에 맞는 경로를 적습니다.

```text
gs://ssakda/projects/brandmate/data/curated/{dataset_name}/v{version}/{artifact_name}/
gs://ssakda/projects/brandmate/data/processed/{dataset_name}/v{version}/{artifact_name}/
```

- 용량 정보는 폴더명에 넣지 않습니다. 용량은 manifest에 기록합니다.
- 데이터셋 이름과 processed 산출물 이름은 분리합니다. 예를 들어 AIHub 음식 이미지 및 정보소개 텍스트 데이터로 음식 설명용 데이터를 만들었다면 `dataset_name`은 `aihub_food_image_text`, processed 산출물 이름인 `artifact_name`은 `food_description_data`로 기록합니다.
- GCS에는 데이터 파일만 업로드합니다. `manifest.json`, `description.md` 사본은 GCS에 두지 않습니다.

### Metadata 관리 원칙

완벽한 데이터 계보 관리만 놓고 보면 GCS artifact 안에 metadata 사본을 함께 두는 방식이 더 엄밀합니다.
하지만 현재 팀은 초기 스타트업/팀프로젝트 단계이고, 이미 Git과 GCS 양쪽에 docs가 있어 팀원이 혼동한 사례가 있었습니다.
따라서 현재 운영 기준에서는 팀원의 혼동을 줄이는 것을 우선합니다.

- `manifest.json`, `description.md`는 Git의 `docs/datasets/...` 아래에서만 관리합니다.
- GCS에는 데이터 파일만 업로드합니다.
- GCS에 metadata 사본을 두지 않습니다. Git/GCS 양쪽 문서 불일치와 팀원 혼동을 막기 위해서입니다.
- `status` 변경은 Git manifest만 수정합니다.
- DVC는 공식 `processed` 산출물만 추적합니다.
- catalog/index는 현재 도입하지 않습니다. 데이터셋 수가 늘어 Git metadata만으로 탐색이 어려워질 때 별도 정책으로 도입합니다.

팀원이 GCS에 직접 업로드하거나 내려받아야 할 때는 아래 명령을 사용합니다.

```bash
# [Design Intent] 로컬 데이터 패키지를 사람이 확인 가능한 GCS 경로에 업로드한다.
gcloud storage rsync --recursive \
  data/{stage}/{dataset_name}/v1/{artifact_name} \
  gs://ssakda/projects/brandmate/data/{stage}/{dataset_name}/v1/{artifact_name}

# [Design Intent] GCS에 등록된 데이터 패키지를 로컬로 내려받는다.
gcloud storage rsync --recursive \
  gs://ssakda/projects/brandmate/data/{stage}/{dataset_name}/v1/{artifact_name} \
  data/{stage}/{dataset_name}/v1/{artifact_name}
```

### 주간 수집 데이터 partition 기준

트렌드 데이터처럼 주기적으로 수집되는 데이터는 `landing` 영역에 주차 단위로 저장합니다.

```text
gs://ssakda/projects/brandmate/data/landing/sns_trend/week=YYYY-Www/
```

주차는 ISO week 기준을 사용하며, 서비스 기준 시간대는 `Asia/Seoul`입니다.

```text
week=2026-W28
= Asia/Seoul 기준 2026년 ISO 28주차
= 2026-07-06 월요일 00:00 ~ 2026-07-12 일요일 23:59:59 KST
```

Airflow 실행 환경은 UTC일 수 있지만, 데이터 partition은 한국 서비스 기준에 맞춰
`Asia/Seoul` 기준으로 계산합니다.

### Version과 수집 partition 구분

`version`은 팀이 구분해서 관리하는 데이터셋 release 번호입니다.
새 데이터가 들어왔거나, 선별 기준/생성 코드/출력 구조/사용 목적이 달라져 기존 버전과 구분해야 하면 `v2`, `v3`로 올릴 수 있습니다.

다만 매일/매주 자동으로 누적되는 운영 데이터는 version을 매번 올리면 관리가 지저분해집니다.
이 경우에는 같은 version 아래에 `date`, `week`, `month` 같은 partition을 둡니다.

예를 들어 `sns_trend`를 매주 같은 방식으로 크롤링한다면 아래처럼 같은 `v1`에 주차 partition을 둘 수 있습니다.

```text
data/processed/sns_trend/v1/week=2026-W28/cross_platform_signal_top_candidates/
data/processed/sns_trend/v1/week=2026-W29/cross_platform_signal_top_candidates/
data/processed/sns_trend/v1/week=2026-W30/cross_platform_signal_top_candidates/
```

반대로 팀이 새 release로 구분하는 편이 더 명확하면 version을 올립니다.
특히 수동 선별 데이터, 고정 benchmark, 발표/서비스 기준 데이터처럼 자주 바뀌지 않는 데이터는 `v1`, `v2` 방식이 단순합니다.

| 상황 | 추천 관리 방식 | 이유 |
| --- | --- | --- |
| AIHub food image/text처럼 자주 바뀌지 않는 고정 데이터셋 | `v1`, `v2` release 관리 | 팀원이 버전 단위로 이해하기 쉬움 |
| 매주 크롤링되는 `sns_trend` | `week=YYYY-Www` partition 또는 필요 시 새 version | 반복 수집이라 매주 version을 올리면 version 의미가 흐려질 수 있음 |
| 실제 운영형 CCTV/visitor_flow 일별 집계 | `date=YYYY-MM-DD` partition | 매일 쌓이는 운영 데이터라 일자 기준 조회가 중요 |
| 선별 기준/생성 코드/출력 구조/사용 목적이 크게 바뀜 | 새 version | 기존 결과와 비교/재현 기준이 달라짐 |

### CCTV/visitor_flow partition 기준

중요한 예외: CCTV도 매일 찍히는 운영 데이터가 되면 주기적 데이터셋입니다.
현재 `aihub_cctv_visitor_flow`가 낮은 변경 빈도로 분류되는 이유는 AIHub에서 받은 고정 샘플을 쓰기 때문입니다.
실제 매장 CCTV 입력으로 전환하면 아래처럼 시간 partition을 둡니다.

```text
data/processed/visitor_flow/v1/store_id={store_id}/date=YYYY-MM-DD/
data/processed/visitor_flow/v1/store_id={store_id}/week=YYYY-Www/
```

일 단위 운영/인력 배치 분석이 목적이면 `date=YYYY-MM-DD`를 우선 사용합니다.
주간 리포트나 트렌드 비교가 목적이면 `week=YYYY-Www` 집계 artifact를 별도로 만듭니다.
