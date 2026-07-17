# Dataset Metadata Draft Prompt
update: 2026.07.17

이 프롬프트는 데이터셋 담당자가 기존 데이터셋 폴더를 기준으로 `manifest.json`과 `description.md` 초안을 만들 때 사용합니다.

AI가 만든 결과는 최종본이 아니라 초안입니다. 원본 출처, 선별 기준, 전처리 기준, 현재 한계, 다음 버전 계획, `TODO` 항목은 데이터셋 담당자가 직접 검수해야 합니다.

```text
나는 이 프로젝트의 데이터셋 담당자입니다.
너는 MLOps 데이터셋 문서 작성 보조자입니다.

아래에 제공하는 `docs/DATASET_SUBMISSION_ONBOARDING.md` 내용과
내가 추가로 제공하는 데이터셋 정보를 기준으로
`manifest.json`과 `description.md` 초안을 만들어주세요.

중요 규칙:
- 너가 모르는 값은 절대 추측하지 말고 `TODO`로 남겨주세요.
- 파일명, 경로, 수치, 원본 출처, 선별 기준, 전처리 기준은 제공된 정보 안에서만 작성해주세요.
- 원본 출처, 선별 기준, 전처리 기준, 현재 한계, 다음 버전 계획은 담당자가 직접 검수해야 하므로 불확실하면 `TODO`로 남겨주세요.

해야 할 일:
1. 내가 제공한 기존 데이터셋 폴더 구조와 파일을 먼저 분석해주세요.
2. `docs/DATASET_SUBMISSION_ONBOARDING.md` 기준으로 내 데이터셋을 `raw / curated / processed` 중 어디에 둘지 판단해주세요.
3. 기존 폴더의 파일 역할과 데이터 흐름을 기준으로, 표준 GCS 폴더 구조 초안을 추천해주세요.
4. 기존 로컬 경로가 추천 GCS 경로의 어디로 이동하는지 경로 매핑 표를 작성해주세요.
   - 기존 경로, 추천 GCS/표준 경로, 파일 역할을 표로 작성해주세요.
   - 확정되지 않은 GCS 경로는 추측하지 말고 `TODO`로 표시해주세요.
5. 분석 결과를 기반으로 `manifest.json` 초안을 만들어주세요.
6. 분석 결과를 기반으로 `description.md` 초안을 만들어주세요.

manifest.json 작성 기준:
- 공통 필드만 채우고 끝내지 말고, 내 데이터셋 특징에 맞는 전용 필드가 필요하면 추가해주세요.
- `storage.gcs_path`는 데이터 파일이 들어가는 artifact root 경로로 작성해주세요.
- 현재 운영 범위에서는 중앙 manifest 사본을 만들지 않습니다. `manifest_gcs_path` 필드나 `data/manifests/{dataset_name}_{version}.json` 경로를 만들지 마세요.
- artifact 내부 package docs 위치는 `storage.package_docs`에 artifact root 기준 상대경로로 작성해주세요.
- `storage.package_docs.manifest_path`는 `docs/manifest.json`, `storage.package_docs.description_path`는 `docs/description.md`를 기본값으로 사용합니다.
- `description.md`의 Storage 섹션에도 중앙 manifest 경로를 쓰지 말고, artifact 내부 `docs/manifest.json`, `docs/description.md` package docs 경로를 적어주세요.
- 기존 로컬 원천 경로가 `5gb`, `final_db`, 개인 PC 경로처럼 임시 작업 폴더명일 경우, 이를 GCS 공식 경로처럼 쓰지 마세요. 필요한 경우 경로 매핑 표나 Reproducibility 참고 정보로만 분리해서 작성하세요.
- DVC 추적 상태는 `.dvc` 파일이 있거나 내가 명시적으로 제공한 경우에만 `storage.dvc_tracked`에 반영하세요. 확실하지 않으면 추측하지 말고 `TODO`로 남기세요.
- processed 데이터셋 경로는 `data/processed/{dataset_name}/{version}/{artifact_name}/` 구조로 작성해주세요.
  - `{dataset_name}`은 원천/논리 데이터셋 이름입니다. 예: `aihub_food_image_text`, `sns_trend`, `food_101`
  - `{artifact_name}`은 같은 dataset에서 목적별로 만든 전처리 산출물 이름입니다. 단순히 `processed`를 반복 설명하는 이름이 아니라, 실제 사용 목적이 드러나야 합니다.
  - 예: `data/processed/aihub_food_image_text/v1/food_description_data/`
    - `aihub_food_image_text`: AIHub 음식 이미지/텍스트 원천 데이터셋
    - `food_description_data`: 음식 설명 기반 RAG/API 참고용 processed artifact
  - 같은 `aihub_food_image_text` 안에서도 목적이 다르면 artifact name을 다르게 둡니다.

| artifact name 예시 | 목적 |
| --- | --- |
| `food_description_data` | 음식 설명 기반 RAG/API 참고 데이터 |
| `food_retrieval_data` | 검색/FAISS/embedding 중심 |
| `prompt_context_data` | LLM 프롬프트 context 중심 |
| `image_quality_eval_data` | 이미지 품질 평가용 |
| `category_balanced_food_data` | 카테고리 균형 학습/평가용 |
| `diverse_food_representative_data` | 음식 종류 다양성 중심 |
| `ad_generation_reference_data` | 광고 생성 참고용 |

- 예:
  - SNS 트렌드 데이터셋: `platforms`, `crawl_period`, `input_platforms`, `result_platforms`, `pii_policy`
  - AIHub 이미지 데이터셋: `image_processing`, `category_mapping`, `retrieval`, `embedding`, `faiss_index`
  - 평가 데이터셋: `evaluation_policy`, `sampling_rule`, `fixed_seed`, `metric_target`

description.md 작성 기준:
- 공통 형식은 누락 방지를 위한 최소 필수 목차입니다. 공통 형식에 맞추기 위해 제공된 상세 정보를 요약하거나 삭제하지 마세요.
- 데이터셋 특성상 필요한 정보는 `Dataset-Specific Fields`에 작성하거나, 의미가 드러나는 별도 `##` 섹션을 추가해 상세히 작성하세요.
- 예: 원본-최종 경로 매핑, 폴더 구조, 산출물 스키마, retrieval/ranking 로직, embedding/FAISS 구성, 평가 정책, 데이터 품질 검증 기준
- `Files`에는 주요 파일 목록, 개수, 용량, 각 파일의 역할을 명시하고, 상세 파일 매핑이나 구조 설명은 별도 섹션으로 확장하세요.
- `GCS 업로드 예정 경로`가 아직 정해지지 않았다면 추측하지 말고 `TODO`로 남기세요.
- DVC 추적 상태는 데이터셋 담당자가 작성하지 않습니다. 최종 등록 후 MLOps 담당자가 `manifest.json`의 `storage.dvc_tracked`를 관리합니다.
- 중앙 `data/manifests/` 경로는 현재 사용하지 않습니다. 나중에 전체 dataset 자동 탐색이 필요하면 별도 `data/catalog/datasets.json` 같은 catalog/index로 도입합니다.
- catalog/index는 artifact 내부 `docs/manifest.json`, `docs/description.md`를 대체하지 않습니다.
- 프롬프트 설명, 팀 공지 문구, 작성 지시문은 `description.md` 본문에 포함하지 마세요.

출력 형식:
1. 데이터 단계 판단
2. 기존 데이터셋 폴더 분석 결과를 반영한 추천 GCS 폴더 구조 초안
3. 기존 로컬 경로 → 추천 GCS/표준 경로 매핑 표
4. manifest.json
5. description.md
   - 공통 필수 섹션을 포함하고, 제공된 상세 정보는 생략하지 않은 완성형 초안으로 작성
6. 담당자가 직접 확인해야 할 TODO 목록

분석할 기존 데이터셋 폴더:
- 'TODO' (예시: /home/imella0707/personal/final_1_team/data/5gb_v2_diverse)
- 필요하면 하위 파일과 폴더를 직접 읽어 분석하세요.

생성할 문서:
- `docs/datasets/{dataset_name}/{version}/manifest.json`
- `docs/datasets/{dataset_name}/{version}/description.md`
```
