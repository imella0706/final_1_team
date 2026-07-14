# BrandMate Dataset Submission Guide

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
| 실제 데이터셋 | X | O | O | 대용량 데이터는 Git에 올리지 않음 |
| 이미지/Parquet/Embedding/FAISS | X | O | O | 대용량 산출물은 GCS에 저장하고 DVC로 버전 추적 |
| DVC metadata 파일 | O | X | X | `.dvc`, `dvc.yaml`, `dvc.lock`은 Git에서 관리 |

짧게 정리하면 아래 정책입니다.

```text
스크립트는 Git only
데이터는 GCS/DVC
설명 문서는 Git + GCS
```

## 3. 데이터 단계

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

SNS 데이터 기준으로 보면 아래처럼 판단합니다.

```text
raw/sns/
= 처음 크롤링한 전체 원본 HTML, 이미지, 원문 JSON, 스크린샷

curated/sns/v1/
= 사람이 보고 "이건 밈/트렌드 데이터로 쓸 수 있다"고 고른 subset

processed/sns/v1/
= 모델/API가 바로 읽을 수 있게 만든 jsonl/parquet/csv
```

## 4. Manifest 공통 형식

`manifest.json`은 아래 공통 형식을 기본으로 사용합니다.

```json
{
  "dataset_name": "TODO",
  "version": "v1",
  "dataset_stage": "raw | curated | processed",
  "status": "baseline | stable | deprecated",
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

### 필드 설명

| 필드 | 의미 | 작성 예시 |
| --- | --- | --- |
| `dataset_name` | 데이터셋 이름입니다. 버전과 산출물 종류는 넣지 않습니다. | `sns_meme_trend`, `aihub_food_image_text` |
| `version` | 데이터셋 버전입니다. 같은 목적의 데이터셋이 바뀌면 `v2`, `v3`로 올립니다. | `v1` |
| `dataset_stage` | 데이터 단계입니다. 원본 전체면 `raw`, 선별본이면 `curated`, 모델이 바로 쓰는 가공본이면 `processed`입니다. | `curated` |
| `status` | 현재 버전의 운영 상태입니다. 첫 기준점은 `baseline`, 안정화된 버전은 `stable`, 더 이상 쓰지 않으면 `deprecated`입니다. | `baseline` |
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

### 작성 기준

- `manifest.json`은 자동화/검색/검증에 쓰는 컴퓨터용 기록이므로 영어 중심으로 작성합니다.
- `description.md`는 팀원이 읽는 설명 문서이므로 한국어 중심으로 작성합니다. 단, 모델명, 파일명, GCS path, 코드 경로는 원문 그대로 씁니다.
- AI가 추측해서 값을 채우는 것은 금지하고, AI가 확실히 알 수 없는 값은 `TODO`로 남깁니다. 
- `TODO` 항목은 데이터셋 담당자가 직접 확인해서 채웁니다.
- `none`은 해당 항목이 이 데이터셋에는 적용되지 않는다는 뜻입니다.
- `TODO`는 해당 항목이 필요하지만 아직 값을 모른다는 뜻입니다.
- `curated` 데이터셋이면 `processing` 쪽은 비워도 됩니다.
- `processed` 데이터셋이면 `input_dataset`, `artifact_name`, `preprocessing_steps`, `output_files`는 꼭 적어주세요.
- `limitations`에는 현재 데이터셋의 한계를 솔직하게 적어주세요.
- `next_version_plan`에는 다음 버전에서 보강할 점을 적어주세요.
- 공통 manifest 형식은 최소 필수 규격입니다. 데이터셋 특성상 추가로 기록해야 하는 정보가 있으면 `manifest.json`에 별도 section을 추가해주시기 바랍니다. 
  예: `retrieval`, `embedding`, `faiss_index`, `image_processing`, `text_processing`, `evaluation_policy`
- 추가 section을 만들 때는 왜 필요한지 `description.md`에도 같이 설명합니다.

## 5. Description 공통 형식

`description.md`는 사람이 읽는 설명 문서입니다. 아래 구조를 기본으로 사용합니다.

```md
# {dataset_name} {version} Description

## Summary
- 데이터셋을 한 문단으로 요약합니다.
- 이 데이터셋을 어디에 쓰는지 설명합니다.

## Dataset Stage
- raw / curated / processed 중 어느 단계인지 적습니다.
- 왜 그렇게 판단했는지 근거를 적습니다.

## Source
- 원본 제공처:
- 원본 데이터셋 이름:
- 원본 URL:
- 사용 split:
- raw 원본 GCS 업로드 여부:
- 원본 annotation/label 보존 여부:

## Curation
- 선별 개수:
- 목표 용량:
- 실제 용량:
- 선별 기준:
- 제외 기준:
- 카테고리 균형 여부:
- 원본 경로와 최종 경로 매핑 가능 여부:

## Processing
- 입력 데이터셋:
- 사용 목적:
- 전처리 단계:
- 생성 파일:
- 사용한 모델/도구:
- 모델/평가/검색/API에서 사용하는 방식:

## Dataset-Specific Fields
- 공통 manifest에 없는 데이터셋 전용 정보를 설명합니다.
- 예: retrieval, embedding, faiss_index, image_processing, text_processing, evaluation_policy

## Storage
- GCS path:
- local example path:
- DVC tracking 여부:

## Reproducibility
- 데이터셋 생성 스크립트 또는 노트북 경로:
- random seed:
- 같은 결과를 다시 만들 수 있는지:

## Limitations
- 현재 데이터셋의 한계를 적습니다.

## Next Version Plan
- 다음 버전에서 보강할 내용을 적습니다.
```

`description.md`의 목적은 사람에게 맥락을 전달하는 것입니다. `manifest.json`에 구조화된 값이 있더라도, 왜 그렇게 선별/전처리했는지와 현재 한계는 문장으로 설명합니다.

## 6. 공유 전 검수 항목

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

## 7. GCS 위치

최종 GCS 폴더 구조와 업로드 명령어는 [GCS_MLOPS_ONBOARDING.md](./GCS_MLOPS_ONBOARDING.md)를 따릅니다.

`manifest.storage.gcs_path`에는 아래 규칙에 맞는 경로를 적습니다.

```text
gs://ssakda/projects/brandmate/data/curated/{source}/v{version}/
gs://ssakda/projects/brandmate/data/processed/{source}/v{version}/{artifact_name}/
gs://ssakda/projects/brandmate/data/manifests/{dataset_name}_{version}.json
```

- 용량 정보는 폴더명에 넣지 않습니다. 용량은 manifest에 기록합니다.
- 데이터셋 이름과 processed 산출물 이름은 분리합니다. 예를 들어 AIHub 음식 이미지 및 정보소개 텍스트 데이터로 음식 설명용 데이터를 만들었다면 `dataset_name`은 `aihub_food_image_text`, `artifact_name`은 `food_description_data`로 기록합니다.
