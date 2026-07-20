# v2 이미지·프롬프트 테스트 가이드

## 목적

이 테스트는 v2 음식 이미지 데이터를 이용해 기존 BrandMate 광고 생성 흐름을 제한된 수량으로 검증한다. 별도의 프롬프트를 만들거나 기존 프롬프트를 바꾸지 않는다.

모든 실행 환경(로컬, GCP GPU 서버, Google Colab)은 같은 v2 러너를 사용하며, 채널별로 기존 프로젝트의 `generate_content()` 분기를 그대로 호출한다.

```text
generate_content()
  ├─ Instagram: generate_ad_copy() -> visualize_products()
  │             -> normalize_image_prompt() -> generate_ad_image()
  └─ Naver Blog: describe_blog_images() -> generate_ad_copy()
                  -> uploaded image response
```

Naver Blog는 기존 API의 채널 규칙을 따른다. 광고 문구는 생성하지만, 입력 이미지를 블로그 이미지로 사용하므로 새 이미지를 생성하지 않는다. Instagram은 기존 상품 시각화·프롬프트 정규화·이미지 생성 단계를 실행한다.

## 입력 데이터와 프롬프트 보호

입력 루트는 `data/processed/aihub_food_image_text/v2`이다.

| 항목 | 위치 또는 기준 |
| --- | --- |
| 메타데이터 | `food_description_data/prompt_metadata.csv` |
| 이미지 | CSV의 `final_image_path`를 `food_description_data/`에 연결 |
| 데이터 ID | `final_image_id` |
| 고정 프롬프트 | `prompt_keywords` |
| 이미지·프롬프트 매칭 | 같은 CSV 행의 `final_image_id` |

러너는 `prompt_keywords` 원문을 `AdCopyRequest.features[0]`으로 전달하고 SHA-256을 검증한다. `strip`, `replace`, 번역, 요약, 재작성은 프롬프트 값에 적용하지 않는다. 기존 광고 카피·프롬프트·정규화 함수와 템플릿은 수정 대상이 아니다.

모델에 전달하는 이미지는 원본 파일과 별개의 메모리 복사본이다. v2 러너는 확장자와 실제 포맷이 다른 이미지(예: `.jpg` 확장자의 MPO)를 포함해 이미지 편집 API가 받을 수 있도록 첫 프레임을 단일 RGB JPEG로 변환하고, 긴 변을 최대 `1024px`로 제한한다. 이 과정은 원본 이미지 파일, CSV, 프롬프트를 쓰거나 수정하지 않는다. 변환된 데이터 URL은 기존 API 요청 스키마의 4,000,000자 제한보다 작은 3,800,000자 이하로 유지한다.

## 지원 범위

- 배치 크기: `10`, `50`, `100`만 허용하며, 실행 시 반드시 하나를 지정한다.
- 모델 선택: `--llm-model` 또는 `--all-llm-models`, `--image-model` 또는 `--all-image-models`를 각각 하나씩 반드시 지정한다. 기본 모델은 없다.
- 채널: `instagram`, `naver_blog`.
- 실패한 한 항목은 최대 2회 재시도한 뒤 실패로 기록하며, 다음 항목을 계속 처리한다.
- 입력 원본·프롬프트 파일은 읽기 전용이다.
- 출력 루트는 항상 `data/outputs/v2_model_results`이며, 테스트가 이 루트를 바꾸지 않는다.

## 실행 전 확인

Python 가상환경과 필요한 패키지가 정상이어야 한다.

```powershell
cd C:\dev\final_1_team\apps\api
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe -m pip install Pillow
.\.venv\Scripts\python.exe -m pytest tests\test_v2_image_prompt_pipeline.py -q
```

`Unable to create process ... Python312` 오류는 가상환경의 Python 실행 파일이 사라졌거나 경로가 바뀐 경우다. 현재 사용하는 Python 버전으로 가상환경을 다시 만든 뒤 위 설치 명령을 실행한다.

모델 제공자는 환경별로 준비해야 한다.

| 환경 | LLM | 이미지 |
| --- | --- | --- |
| 로컬 | LM Studio, Ollama, vLLM 또는 기존 OpenAI/NVIDIA API | FLUX 선택 시 ComfyUI, OpenAI 이미지 API |
| GCP GPU 서버 | vLLM 또는 기존 OpenAI/NVIDIA API | FLUX 선택 시 ComfyUI, OpenAI 이미지 API |
| Colab | 노트북의 로컬 vLLM 또는 기존 OpenAI/NVIDIA API | 노트북의 로컬 ComfyUI 또는 OpenAI 이미지 API |

로컬과 GCP는 기존 프로젝트 설정을 사용한다. OpenAI에는 `BRANDMATE_OPENAI_API_KEY`, NVIDIA LLM에는 `BRANDMATE_NVIDIA_API_KEY`를 설정한다. 이 키는 v2가 새로 해석하거나 저장하지 않고 기존 모델 런타임에 전달된다.

Colab은 GCP API URL이나 `.env` 파일을 요구하지 않는다. 다음 Colab Secret 이름을 지원하며 런타임 환경 변수로만 주입한다.

| Colab Secret | 용도 |
| --- | --- |
| `OPENAI_API_KEY` 또는 `BRANDMATE_OPENAI_API_KEY` | OpenAI LLM 및 OpenAI 이미지 모델 |
| `NVIDIA_API_KEY` 또는 `BRANDMATE_NVIDIA_API_KEY` | NVIDIA Llama LLM |
| `HF_TOKEN` | Hugging Face Router 또는 로컬 vLLM/ComfyUI 모델 다운로드 |

어떤 Secret도 결과 JSON, 이벤트 로그, 노트북 출력 또는 저장소에 기록하지 않는다.

Colab 노트북은 기본 Python에 `pip install`을 실행하지 않는다. Colab Python 3.12에서는 `python -m venv`가 `ensurepip` 누락으로 실패할 수 있으므로, 노트북은 PyPA의 독립 실행형 `virtualenv.pyz`로 환경을 만든다. BrandMate 앱은 `/content/brandmate-app-v3`, Qwen vLLM은 `/content/vllm-cu128-v2`, ComfyUI는 `/content/comfyui-cu128-v2`에서 각각 격리해 실행한다. 따라서 Colab의 pandas·NumPy·numba·cudf·opentelemetry 의존성과 모델 서버 의존성이 섞이지 않는다. 이전 노트북을 실행한 적이 있으면 반드시 런타임을 새로 시작한 뒤 수정된 노트북의 첫 셀부터 실행한다.

## 로컬 또는 GCP 실행

먼저 모델 호출 없이 데이터와 매칭만 점검한다.

```powershell
.\.venv\Scripts\python.exe scripts\run_v2_image_prompt_pipeline.py `
  --input-dir "C:\dev\final_1_team\data\processed\aihub_food_image_text\v2" `
  --output-dir "C:\dev\final_1_team\data\outputs\v2_model_results" `
  --batch-size 10 `
  --llm-model "openai/gpt-4.1-mini" `
  --image-model "openai/gpt-image-1-mini" `
  --dry-run
```

두 채널을 실제 실행하는 예시다.

```powershell
.\.venv\Scripts\python.exe scripts\run_v2_image_prompt_pipeline.py `
  --input-dir "C:\dev\final_1_team\data\processed\aihub_food_image_text\v2" `
  --output-dir "C:\dev\final_1_team\data\outputs\v2_model_results" `
  --batch-size 10 `
  --channels instagram naver_blog `
  --llm-model "Qwen/Qwen2.5-7B-Instruct" `
  --image-model "black-forest-labs/FLUX.1-schnell"
```

Qwen을 선택한 경우 `http://localhost:1234/v1 (ConnectError)`는 프런트엔드나 FastAPI 서버를 열지 않아서 발생하는 오류가 아니다. `BRANDMATE_QWEN_BASE_URL` 또는 `BRANDMATE_LOCAL_LLM_BASE_URL`에 설정된 LM Studio/vLLM 등의 로컬 OpenAI 호환 서버가 실행되지 않았거나 주소가 잘못된 경우다. `http://localhost:1234/v1/models`가 응답하도록 만든 뒤, 실제 주소와 모델 이름을 `BRANDMATE_QWEN_BASE_URL`, `BRANDMATE_QWEN_MODEL`에 맞춘다. FLUX 실행에는 `BRANDMATE_IMAGE_PROVIDER=comfyui`와 실행 중인 ComfyUI가 추가로 필요하다.

OpenAI API 키로 테스트할 때는 키만 설정해서는 안 된다. v2 실행기는 기본 모델을 선택하지 않으므로, 광고 문구 모델과 이미지 모델을 반드시 명시해야 한다. OpenAI 광고 문구 모델을 선택하면 로컬 Qwen 서버가 아니라 OpenAI API를 호출한다. 이 명령은 프런트엔드와 FastAPI 서버를 열지 않아도 되며, 파이프라인이 OpenAI API를 직접 호출한다.

`apps/api/.env`에 아래 값을 한 번만 설정한다. API 키는 명령행, 결과 JSON, 이벤트 로그에 쓰지 않는다.

```env
BRANDMATE_OPENAI_API_KEY=새로_발급한_OpenAI_API_키
BRANDMATE_OPENAI_BASE_URL=https://api.openai.com/v1
```

```powershell
.\.venv\Scripts\python.exe scripts\run_v2_image_prompt_pipeline.py `
  --input-dir "C:\dev\final_1_team\data\processed\aihub_food_image_text\v2" `
  --output-dir "C:\dev\final_1_team\data\outputs\v2_model_results" `
  --batch-size 10 `
  --llm-model "openai/gpt-4.1-mini" `
  --image-model "openai/gpt-image-1-mini"
```

실행이 성공하면 채널과 모델 조합별 결과물은 `data/outputs/v2_model_results/batch_10/<채널>/models/<모델_조합>/`에 저장된다. 광고 문구 LLM 단계가 실패하면 이미지 생성 단계는 진행되지 않으므로 결과 이미지와 결과 경로가 비어 있는 상태로 기록된다.

## Colab 실행

노트북 파일은 `notebooks/colab_huggingface_v2_inference_test.ipynb`이다.

1. GPU 런타임을 새로 연다.
2. 프로젝트가 있는 Google Drive를 마운트하고 Colab Secret에 `HF_TOKEN`을 만든다.
3. 4절에서 기존 카탈로그의 LLM·이미지 모델 ID를 선택한다. OpenAI/NVIDIA 모델이면 해당 Secret을 추가한다.
4. 노트북 1~7절을 위에서 아래 순서로 실행한다. OpenAI/NVIDIA API 모델을 선택한 경우 불필요한 vLLM/ComfyUI 시작 단계는 자동으로 건너뛴다.
5. 8절에서 v2 입력 검증이 성공했는지 확인한다.
6. 9절을 실행하면 동일 v2 러너가 Instagram과 Naver Blog를 차례로 실행한다.
7. `BATCH_SIZE`를 `10`, `50`, `100` 중 하나로만 바꾼다.

실행할 때는 광고 문구 모델과 이미지 모델을 모두 선택해야 한다. 예를 들어 로컬 Qwen과 FLUX를 선택할 수 있으며, Colab은 Qwen AWQ 가중치를 vLLM 내부 구현으로 사용하더라도 프로젝트에 전달하는 모델 ID는 기존 카탈로그의 Qwen ID로 유지한다.

FLUX.1-schnell 접근 전에 Hugging Face 모델 페이지에서 사용 조건을 수락해야 한다. 기본 GGUF 모델은 약 6.8 GB이고 T5 텍스트 인코더는 약 4.9 GB이므로, 실제 실행에는 여유 GPU 메모리가 필요하다.

## 결과 저장과 해석

채널과 모델 조합은 서로 다른 경로에 저장된다.

```text
data/outputs/v2_model_results/
└─ batch_10/
   ├─ instagram/models/llm_Qwen_Qwen2.5-7B-Instruct__image_black-forest-labs_FLUX.1-schnell/
   │  ├─ results/<image_id>.json
   │  ├─ artifacts/instagram/<image_id>/
   │  ├─ logs/
   │  ├─ manifests/
   │  └─ state.json
   └─ naver_blog/models/llm_Qwen_Qwen2.5-7B-Instruct__image_black-forest-labs_FLUX.1-schnell/
      └─ 같은 구조
```

- `results/*.json`: 상태, 재시도 횟수, 프롬프트 해시, 모델, 광고 문구, 이미지 응답, 오류를 기록한다.
- `artifacts/<channel>/<image_id>/`: 광고 문구와 최종 이미지 등 채널 결과물이다.
- `logs/*.jsonl`: 시작, 재시도, 성공, 실패 이벤트다.
- `manifests/`: 전체 성공·실패·건너뜀 요약이다.
- `state.json`: `--resume`에서 성공 항목을 건너뛰기 위한 상태다.

`generate_content()`은 기존 서비스 계약에 따라 별도로 `outputs/ad-content/`에도 기존 API 아티팩트를 저장할 수 있다. 이는 테스트가 새 저장소를 만들거나 기존 출력 경로를 변경한 것이 아니라, 기존 API가 원래 하던 저장 동작이다.

## 오류 대응

| 오류 | 원인 | 조치 |
| --- | --- | --- |
| `ConnectError` | LLM 또는 ComfyUI 서버가 실행되지 않음 | 주소, 포트, 실행 상태를 확인 |
| 401/403 | HF 토큰 또는 gated 모델 접근 권한 부족 | `HF_TOKEN`과 모델 사용 조건 확인 |
| 429/5xx | 일시적 공급자 오류 | 로그의 재시도 후 다시 실행 |
| `invalid_image_file` | 확장자와 실제 포맷이 다르거나 이미지 편집 API가 원본 바이트를 거부함 | v2 러너가 생성하는 1024px RGB JPEG 모델 입력을 사용해 다시 실행하고, 계속되면 해당 원본 이미지의 손상 여부 확인 |
| `reference_image_data_url` 길이 초과 | 원본 이미지의 Base64 데이터 URL이 기존 API 스키마 제한을 초과함 | v2 러너의 1024px JPEG 메모리 변환이 적용된 최신 코드인지 확인 |
| CUDA OOM | LLM·FLUX 조합의 VRAM 부족 | 더 큰 GPU 사용, vLLM 메모리 비율 조정, 한 항목 테스트 후 재시도 |
| ComfyUI workflow 오류 | GGUF 노드 또는 정해진 모델 파일이 없음 | `ComfyUI-GGUF` 및 workflow가 요구하는 파일명 확인 |
| 이미지 검증 실패 | 원본 경로·확장자·바이트가 맞지 않음 | `logs/input_validation.json` 또는 검증 메시지 확인 |

프롬프트 보호 대상 파일과 함수는 이 테스트에서 수정하지 않는다: `app/modules/ad_copy/prompt.py`, `build_prompt()`, `build_prompt_messages()`, `normalize_image_prompt()` 및 그 템플릿·시스템 메시지·negative prompt 정의부.
