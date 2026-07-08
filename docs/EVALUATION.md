# 모델 평가 가이드

BrandMate의 광고 문구 모델과 추후 연결할 이미지 모델을 동일한 기준으로 비교하기 위한
평가 체계입니다. 예시 수치를 결과처럼 사용하지 않고 실제 호출에서 측정한 값만 보고서에
기록합니다.

## LLM 평가 실행

`apps/api`에서 실행합니다.

```powershell
.\.venv\Scripts\python -m scripts.evaluate_models --repeats 3 --concurrency 1
```

특정 모델과 일부 케이스만 빠르게 확인할 수도 있습니다.

```powershell
.\.venv\Scripts\python -m scripts.evaluate_models `
  --models nvidia/meta/llama-3.1-8b-instruct `
  --case-limit 1
```

동시 요청 50개 부하 테스트는 무료 Hosted API의 Rate Limit과 사용량을 먼저 확인한 뒤
실행합니다.

```powershell
.\.venv\Scripts\python -m scripts.evaluate_models `
  --models nvidia/meta/llama-3.1-8b-instruct `
  --repeats 10 `
  --concurrency 50
```

LLM 평가 결과는 Git에 포함되지 않는 `outputs/evaluations`에 JSON과 Markdown 두 형식으로
생성됩니다. JSON에는 개별 요청·출력·오류가, Markdown에는 모델별 요약표가 기록됩니다.

## Vision 평가 실행

이미지 모델 평가는 LLM 평가 runner에 섞지 않고 별도 runner로 실행합니다.

> 이 runner는 운영 요청 중 실행하는 코드가 아니라 모델 선택과 실험 재현을 위한
> 오프라인 평가 파이프라인입니다. 웹 UI 또는 FastAPI 수동 테스트를 해도
> `report.json`, `report.md`, 평가용 이미지 폴더는 자동 생성되지 않습니다.

```powershell
# [Design Intent] 기존 LLM 평가 케이스에서 image prompt를 생성한 뒤 이미지 생성 성공률과 latency를 측정한다.
.\.venv\Scripts\python -m scripts.evaluate_vision_models --repeats 3 --concurrency 1
```

WSL/Linux 터미널에서는 `apps/api`에서 아래처럼 실행합니다.

```bash
# [Design Intent] 로컬 FLUX/ComfyUI 평가 전에 가장 작은 조건으로 연결 상태를 검증한다.
conda activate ssakda
cd ~/personal/final_1_team/apps/api

python -m scripts.evaluate_vision_models \
  --case-limit 1 \
  --repeats 1 \
  --concurrency 1 \
  --image-models black-forest-labs/FLUX.1-schnell \
  --image-width 512 \
  --image-height 640 \
  --num-inference-steps 16 \
  --skip-clip
```

프로젝트 루트에서는 로컬 편의 wrapper를 사용할 수 있습니다. wrapper 기본값도 위와 같은
스모크 테스트 조건입니다. 이 기본 실행은 이미지 생성/저장 경로 확인을 우선하므로 CLIP Score를
건너뜁니다.

```bash
# [Design Intent] Ollama/ComfyUI 준비 상태를 확인한 뒤 가벼운 FLUX 평가를 한 번 실행한다.
./scripts/run_local_vision_eval.sh
```

CLIP Score까지 포함한 최종 평가가 필요하면 wrapper에서 `VISION_EVAL_SKIP_CLIP=0`을 지정합니다.

```bash
# [Design Intent] 이미지 저장까지 안정화된 뒤에만 CPU CLIP 평가를 추가한다.
VISION_EVAL_SKIP_CLIP=0 ./scripts/run_local_vision_eval.sh
```

평가 runner는 시작 전에 LLM endpoint와 이미지 provider를 사전 점검합니다.
CLIP Score를 켠 경우에만 CLIP 모델 로딩까지 사전 점검합니다.
하나라도 실패하면 run 폴더를 만들지 않고 종료합니다. 반쪽짜리 이미지 폴더나 실패 report가
쌓이는 것을 막기 위한 의도입니다.

로컬 ComfyUI FLUX만 빠르게 스모크 테스트할 때는 케이스 수를 제한합니다.

```powershell
# [Design Intent] 긴 이미지 생성 시간을 줄이고 runner 연결 상태만 먼저 확인한다.
.\.venv\Scripts\python -m scripts.evaluate_vision_models `
  --image-models black-forest-labs/FLUX.1-schnell `
  --case-limit 1 `
  --image-width 512 `
  --image-height 640 `
  --num-inference-steps 16 `
  --skip-clip
```

GPT-4o 같은 유료 Vision Judge는 기본 실행에 넣지 않고 선택적으로만 실행합니다.

```powershell
# [Design Intent] 자동 지표를 보완하는 2차 QA 점수만 필요할 때 유료 VLM Judge를 켠다.
$env:OPENAI_API_KEY="..."
.\.venv\Scripts\python -m scripts.evaluate_vision_models `
  --case-limit 1 `
  --vision-judge-model gpt-4o
```

현재 비전 runner는 별도 이미지 케이스 파일을 만들지 않고
`apps/api/evals/ad_copy_cases.json`를 그대로 사용합니다. 실행 흐름은
`LLM 광고 문구 생성 -> Product Visualizer -> Prompt Normalizer -> 이미지 생성 -> report 저장`
입니다. 따라서 이 보고서는 이미지 모델 단독 점수가 아니라 BrandMate의
copy-to-image 파이프라인 품질 점수입니다.
단, `--skip-clip`을 지정한 스모크 테스트에서는 CLIP Score를 계산하지 않고 이미지 생성/저장과
latency만 확인합니다.
이미지 생성 seed는 케이스 ID, 이미지 모델, 반복 번호를 기준으로 고정 생성해
`report.json`의 trial과 이미지 요청에 함께 기록합니다.
비전 평가 결과는 run 단위로 `outputs/evaluations/vision/{YYYYMMDD}/{HHMMSS}/`에 저장합니다.
각 run 폴더는 `report.json`, `report.md`, `images/{model_name}/` 구조를 가집니다.

`report.json`에서 시간 지표를 읽는 기준은 다음과 같습니다.

| 필드 | 의미 |
| --- | --- |
| `trials[].copy_latency_ms` | 광고 문구 생성에 걸린 시간 |
| `trials[].image_latency_ms` | 이미지 1장 생성에 걸린 시간 |
| `trials[].wall_latency_ms` | 카피 생성부터 이미지 저장, metric 계산 시도까지 포함한 전체 trial 시간 |
| `model_summaries[].serving_quality.mean_image_latency_ms` | 성공한 이미지 생성 요청들의 평균 이미지 생성 시간 |
| `model_summaries[].serving_quality.mean_latency_ms` | 성공한 trial들의 평균 End-to-End 시간 |

CLIP Score는 기본 지표에서 제외하고 선택 지표로만 유지합니다. 이미지 생성이 성공했다면
CLIP 계산 여부와 관계없이 Serving Quality의 성공률과 latency는 별도로 집계합니다.
CLIP Score까지 계산하려면 `apps/api`에서 GPU image dependency를 설치합니다.

```bash
# [Design Intent] 로컬과 GPU 서버를 같은 CUDA 12.1 PyTorch wheel 기준으로 고정한다.
pip install -r requirements-image-gpu-prod.txt --extra-index-url https://download.pytorch.org/whl/cu121
```
torch<2.6 환경에서는 .bin weight 로드가 보안 정책상 차단될 수 있어 safetensors weight를 사용합니다.

```bash
# [Design Intent] torch.load 기반 .bin 대신 safetensors weight로 공개 CLIP 모델을 로드한다.
python -c "from transformers import CLIPModel, CLIPProcessor; CLIPProcessor.from_pretrained('openai/clip-vit-base-patch32'); CLIPModel.from_pretrained('openai/clip-vit-base-patch32', use_safetensors=True); print('clip ok')"
```

평가용 CLIP은 선택 실행 시 기본적으로 CPU에서 실행합니다. 로컬 ComfyUI/FLUX가 GPU VRAM을 많이
사용하기 때문에, CLIP까지 GPU에 올리면 12GB급 GPU에서는 OOM으로 ComfyUI가 종료될 수
있습니다. 별도 평가 GPU가 있는 서버에서만 아래처럼 명시적으로 CUDA를 켭니다.

```bash
# [Design Intent] 기본은 FLUX 생성 안정성을 위해 CPU 평가이며, 별도 GPU가 있을 때만 CUDA를 사용한다.
BRANDMATE_VISION_METRIC_DEVICE=cuda python -m scripts.evaluate_vision_models --case-limit 1
```

이미지 생성용 prompt는 CLIP text encoder의 입력 한도보다 길 수 있습니다. 그래서 CLIP
Score는 전체 생성 prompt가 아니라 `clip_eval_prompt`를 별도로 만들어 계산합니다.
`clip_eval_prompt`는 상품명, 배경, 조명, 카메라, 광고 사진 스타일만 담은 짧은 평가용
문장입니다. 전체 생성 prompt는 재현성을 위해 `image_prompt`로 계속 저장합니다.

```text
Commercial food advertising photo showing handmade strawberry tiramisu and lunch set together on a clean cafe table, soft natural window light, 45-degree close-up product shot, realistic premium product photography, no readable text.
```

`truncation=True`는 긴 텍스트가 들어왔을 때 평가 runner가 죽지 않게 하는 마지막 안전장치입니다.
metric 계산 중 예외가 발생해도 이미지 생성 성공 여부와 저장 경로는 report에 남깁니다.

## 현재 자동 측정 지표

| 구분 | 지표 | 현재 계산 방법 |
| --- | --- | --- |
| Model Quality | JSON Compliance | 첫 응답이 Pydantic 스키마를 통과한 비율 |
| Model Quality | Context Adherence | 상품·필수어·금칙어 준수 규칙 기반 점수 |
| Model Quality | Tone & Manner | 톤별 표현 사전을 이용한 프록시 점수 |
| Model Quality | Hallucination Rate | 입력에 없는 예약·주문·효능·인증 등 주장 비율 |
| Model Quality | Toxicity | 유해 표현 사전 적발 비율 |
| Model Quality | Hashtag Compliance | `#` 시작 및 공백 없는 해시태그 비율 |
| Model Quality | Image Prompt Language | 영문 이미지 프롬프트 비율 |
| Model Quality | Diversity | 핵심 문구 간 토큰 Jaccard 거리 |
| Serving Quality | Task Success Rate | 전체 요청 중 최종 스키마 응답 성공 비율 |
| Serving Quality | Mean/P50/P95/P99 | 클라이언트에서 측정한 End-to-End 지연시간 |
| Serving Quality | Client Queue Wait | 평가 러너 Semaphore 진입 대기시간 |
| Serving Quality | Throughput | 모델별 평가 구간의 초당 완료 요청 수 |

Tone과 Hallucination 자동 점수는 초기 프록시입니다. 운영 모델 선정 전에는 블라인드
사람 평가 또는 별도의 Judge 모델 점수와 교차 검증해야 합니다.

## 아직 측정하지 않는 지표

- `TPOT`: 현재 비스트리밍 Hosted API에는 토큰별 도착 시각이 없어 정확히 계산할 수 없음
- Provider Queue Waiting Time: 외부 Provider 내부 대기열 정보가 공개되지 않음
- GPU Utilization / VRAM Peak: 자체 vLLM 또는 NVIDIA NIM 서버에서 NVML로 측정
- Vision Quality 자동 점수: CLIP/Aesthetic/Diversity는 선택 지표로 분리

측정할 수 없는 값은 보고서에서 `null`로 남깁니다.

`TPOT`은 token output time이므로 LLM 생성 지표입니다. 이미지 생성 모델에는 그대로
적용하지 않고, 필요하면 `time_per_image` 또는 diffusion step 단위 시간이 노출되는
런타임에서 `time_per_step`을 별도 지표로 둡니다.

## Vision 평가 확장

이미지 모델 연결 후 같은 평가 보고서에 Vision Model Quality와 Serving Quality를
추가합니다. 현재 기본 목표는 로컬 FLUX/ComfyUI 환경에서 안정적으로 반복 가능한 지표를
먼저 남기는 것입니다. 무거운 모델 의존성, 유료 API, 수동 집계가 필요한 지표는 선택 검증으로
분리합니다.

### 현재 기본 지표

| 지표 | 계산 방식과 도구 | 모델 선정 기준과 비즈니스 임팩트 |
| --- | --- | --- |
| Image Generation Success Rate | 이미지 생성 요청 중 base64 payload가 정상 디코딩되고 파일로 저장된 비율 | 모델이 실제로 결과물을 안정적으로 생성하는지 판단합니다. |
| Failure Rate | Python exception handling으로 API 실패, timeout, 빈 이미지, 깨진 base64, corrupt image 건수를 집계하고 `실패 수 / 전체 요청 수 * 100`으로 계산 | 생성 실패율이 높으면 사용자는 같은 요청을 반복해야 합니다. 품질 이전에 서비스 신뢰도를 무너뜨리는 운영 안정성 지표입니다. |
| Image Latency | 이미지 생성 요청 시작부터 이미지 payload 수신까지 걸린 시간 | FLUX/SDXL 등 후보 모델의 실제 생성 속도를 비교합니다. |
| Pipeline Latency | 광고 문구 생성, Product Visualizer, 이미지 생성, 저장, metric 계산 시도를 포함한 trial 전체 시간 | 사용자가 체감할 end-to-end 비용과 평가 runner 처리량을 판단합니다. |
| Saved Image Path | run별 `images/{model_name}/` 아래 생성 이미지를 저장 | 자동 점수만으로 판단하기 어려운 광고 이미지 품질을 팀원이 직접 비교할 수 있습니다. |

### 선택 지표

| 지표 | 계산 방식과 도구 | 현재 결정 |
| --- | --- | --- |
| CLIP Score | OpenAI CLIP 계열 모델로 `clip_eval_prompt`와 생성 이미지 임베딩의 cosine similarity를 계산 | 토큰 제한, 모델 로딩 비용, 로컬 GPU/CPU 부담 때문에 기본 지표에서 제외합니다. 최종 보고서용 또는 별도 평가 환경에서만 `VISION_EVAL_SKIP_CLIP=0`으로 선택 실행합니다. |
| Aesthetic Score | LAION Aesthetic Predictor 또는 CLIP 기반 Aesthetic Predictor로 이미지를 1~10점 스케일로 평가 | 계산 함수는 있으나 predictor weight와 runner 연결이 필요합니다. 현재 report에는 포함하지 않습니다. |
| Diversity Score | 동일 프롬프트로 N장 생성 후 CLIP 또는 DINO 이미지 임베딩을 추출하고 pairwise cosine similarity의 `1 - 평균 유사도`를 계산 | 동일 prompt 반복 생성과 이미지 임베딩 계산이 필요합니다. 현재 비전 runner에는 미구현입니다. |
| GPT-4o Vision Judge | 생성 이미지와 프롬프트를 GPT-4o Vision API에 전달하고 광고 목적 부합성, 브랜드 적합성, 오브젝트 정확성, 시각적 오류를 1~5점으로 채점 | 유료 API라 기본 회귀 테스트가 아니라 후보 모델 최종 검증에만 사용합니다. |
| Human Preference | 모델명을 가린 블라인드 A/B 테스트를 CSV 또는 JSON으로 수동 입력받아 선호도 승률을 집계 | 사람의 감성 판단이 최종 Ground Truth입니다. 발표와 보고서에서 가장 설득력이 높지만 자동화 지표는 아닙니다. |
| ImageReward | 사람 선호 데이터로 학습된 ImageReward 모델로 이미지 품질과 텍스트 부합성을 점수화 | 설치와 모델 의존성이 무겁기 때문에 2차 이후 후보입니다. |

Vision 지표도 모델별 단일 샘플 점수만 보고하지 않습니다. 동일 평가 세트에서 모델별
반복 생성 결과를 집계하고, 핵심 지표는 평균과 표준편차를 함께 기록합니다. 현재 비교 표에는
이미지 생성 성공률, Failure Rate, Image Latency, Pipeline Latency, 저장 이미지 경로를
우선 포함합니다.

사람 선호도는 모델명을 가린 블라인드 A/B 방식으로 기록하고, 자동 점수와 최종적으로
교차 검증합니다. 예시 수치는 보고서 템플릿에 넣지 않고 실제 실행 결과만 기록합니다.

## 평가 데이터

초기 데이터는 `apps/api/evals/ad_copy_cases.json`에 있습니다. 업종·상황·타겟·톤과
금칙어 조합을 포함한 6개 스모크 케이스이며, 모델 선정 전에는 최소 30개 이상으로
확장합니다.
