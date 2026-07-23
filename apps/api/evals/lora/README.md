# Meme QLoRA 실험 준비 scaffold

이 디렉터리는 현재 수동 TrendCard(`gogumafarm:1bf390d89536004b`)를 사용하는
광고 문구 QLoRA의 **학습 경로와 데이터 계약을 검증하기 위한 준비물**입니다.
현재 seed 규모로 품질 우위나 일반화를 주장할 수는 없습니다.

## 포함 파일

- `train.seed.jsonl`: 서로 다른 상호·상품으로 작성한 학습 seed 12개
- `validation.seed.jsonl`: 학습 split과 상호·상품이 겹치지 않는 검증 seed 3개
- `../../scripts/train_meme_lora.py`: 검증 및 TRL/PEFT 4-bit QLoRA 학습 CLI
- `../../requirements-lora.txt`: API 기본 의존성과 분리한 선택적 학습 의존성

seed 행은 간결한 `request + gold` 형태입니다. 학습 CLI가 실행 시점에 다음을 수행합니다.

1. `AdCopyRequest`로 요청을 검증합니다.
2. 현재 수동 TrendCard와 실제 production prompt를 조립합니다.
3. `gold`를 현재 `AdCopyContent` 전체 JSON 계약으로 확장합니다.
4. production `validate_copy_output()`과 필수 표현·특징 검사를 통과시킵니다.
5. TRL conversational prompt-completion 형식으로 바꿉니다.

따라서 모델이 학습하는 assistant completion은 축약본이 아니라 현재 서비스가 요구하는
전체 광고 JSON입니다. `completion_only_loss=True`를 사용하므로 system/user prompt에는
loss를 주지 않고 assistant completion에만 loss를 계산합니다.

## 먼저 데이터만 검증

외부 패키지 설치나 GPU 없이 `apps/api`에서 실행할 수 있습니다.

```powershell
python -m scripts.train_meme_lora --validate-only --allow-unreviewed-seeds
```

검증 항목은 다음과 같습니다.

- JSONL/Pydantic 형식
- metadata와 실제 요청의 상호·상품 일치
- train/validation 간 example, source lineage, 상호, 상품 격리
- 기존 `evals/ad_copy_cases.json`, 현재 `meme_ad_copy_cases.json`,
  `few_shot_examples.json`과 상호·상품 중복 금지
- 현재 TrendCard 채널·권리·금지어 게이트
- 전체 `AdCopyContent` 스키마 및 production 출력 검증
- `required_terms`와 모든 입력 특징의 고객 노출 문구 포함

추가 비교 corpus를 만들면 같은 metadata 키(`business_name`, `product_names`,
`source_lineage_id`)를 넣고 아래처럼 비교 대상을 추가합니다.

```powershell
python -m scripts.train_meme_lora --validate-only --allow-unreviewed-seeds `
  --overlap-file evals/lora/additional.candidates.jsonl
```

문자열이 조금 다른 파생 예시는 exact-name 검사만으로 잡히지 않습니다. 실제 데이터셋을
늘리기 전에는 source post, campaign, template의 계보 ID를 먼저 부여하고, 증강 전에
split한 뒤 embedding 기반 near-duplicate 검사도 별도로 수행해야 합니다.

## seed 검수 상태

모든 현재 행은 다음 상태로 저장되어 있습니다.

```json
{
  "source_kind": "assistant_authored_scaffold",
  "review_status": "seed_needs_review",
  "rights_review_status": "seed_needs_review"
}
```

이는 의도적인 안전장치입니다. 실제 학습 전 카피 담당자와 데이터/권리 담당자가 각 행을
검토하고 두 status를 모두 `reviewed`로 변경해야 합니다. `--allow-unreviewed-seeds`는
adapter 연결만 확인하는 engineering smoke run에만 사용할 수 있으며 결과를 품질 평가에
사용하면 안 됩니다.
플래그를 빼면 현재 seed의 미검수 상태를 알리며 검증이 의도적으로 중단됩니다.

검수 시 확인할 내용:

- 입력에 없는 재료, 가격, 시간, 효능을 만들지 않았는가
- `니가 좋아`가 자연스럽고 각 고객 노출 문구에 과도하게 반복되지 않는가
- 대표 메뉴 뒤에 모든 메뉴를 쉼표로 나열하지 않았는가
- 모든 상품·특징·혜택이 요청과 정확히 일치하는가
- 상호·상품·원문 계보가 train, validation, test, few-shot 중 하나에만 속하는가
- 실제 사용자 문구나 개인정보가 포함되지 않았는가

## 선택적 학습 환경 설치

이 scaffold를 추가하면서 패키지를 설치하거나 학습을 실행하지 않았습니다. CUDA 학습
호스트에서만 다음을 수행합니다.

```powershell
cd apps/api
python -m pip install -e .
python -m pip install -r requirements-lora.txt
```

현재 스크립트는 Qwen base를 bitsandbytes 4-bit NF4와 double quantization으로 불러오고
LoRA adapter만 학습하는 QLoRA 방식입니다. `prepare_model_for_kbit_training()`과 gradient
checkpointing을 사용하며 optimizer는 `paged_adamw_8bit`입니다. `--compute-dtype auto`는
BF16을 지원하는 A100 같은 GPU에서는 BF16, 지원하지 않는 T4 같은 GPU에서는 FP16을
선택합니다. 필요하면 `--compute-dtype float16` 또는 `bfloat16`으로 명시할 수 있습니다.

production prompt와 전체 JSON completion이 길기 때문에 기본 sequence limit은 T4 smoke에
현실적인 4,096 token으로 낮췄습니다. 토큰화 후 limit을 넘는 행은 조용히 자르지 않고
학습을 중단합니다. 이 경우 측정된 최장 길이를 확인한 뒤 VRAM 여유가 있을 때만
`--max-length`를 올리세요. 4-bit여도 입력 길이와 activation에 따라 T4에서 OOM이 날 수
있습니다. CUDA가 없으면 모델 다운로드 전에 종료하며 CPU 학습 fallback은 제공하지 않습니다.

## 학습 실행

재현성을 위해 mutable `main` 대신 Hugging Face의 40자리 commit SHA가 필요합니다.
출력 폴더도 비어 있는 새 경로만 허용하며 기존 파일을 삭제하거나 덮어쓰지 않습니다.

```powershell
python -m scripts.train_meme_lora `
  --base-revision <QWEN_2_5_7B_COMMIT_SHA> `
  --output-dir ../../outputs/lora/qwen2.5-7b-meme/run-001 `
  --epochs 3 `
  --max-length 4096 `
  --compute-dtype auto `
  --seed 42
```

검수 전 연결 smoke만 수행하려면 위 명령에 `--allow-unreviewed-seeds`가 필요합니다.
완료되면 adapter, tokenizer 정보와 함께 다음 재현 정보를
`brandmate_training_manifest.json`에 기록합니다.

- base model과 immutable revision
- train/validation 경로와 SHA-256
- 누수 검사를 통과한 모든 비교 corpus 경로와 SHA-256
- 데이터 수, seed, LoRA rank/alpha/dropout/target modules
- 4-bit/NF4/double-quant 설정, bitsandbytes 버전, 실제 compute dtype
- epoch, learning rate, paged optimizer, gradient accumulation, GPU와 completion-only loss 사용 여부

## 동일 base로 서빙

공정 비교에서는 hosted Qwen과 로컬 QLoRA adapter를 비교하지 않습니다. 동일 revision,
tokenizer, chat template을 사용하는 한 vLLM 서버에서 base와 adapter를 함께 노출합니다.
QLoRA의 4-bit 설정은 **학습 시 base 로딩 방식**이며 adapter 자체가 4-bit 모델이 되는 것은
아닙니다. 예시는 Linux/WSL CUDA 환경 기준이며 vLLM 설치는 이 scaffold 범위 밖입니다.

```bash
vllm serve Qwen/Qwen2.5-7B-Instruct \
  --revision <QWEN_2_5_7B_COMMIT_SHA> \
  --enable-lora \
  --lora-modules brandmate-meme=../../outputs/lora/qwen2.5-7b-meme/run-001
```

`/v1/models`에서 base와 `brandmate-meme`가 모두 보이는지 확인한 뒤 같은 sampling,
max tokens, structured-output 조건으로 요청해야 합니다. production에서 runtime adapter
업로드 기능은 켜지 않습니다.

현재 Colab 생성 서버에서 쓰는 `Qwen2.5-7B-Instruct-AWQ`에 이 adapter를 바로 붙일 수 있다고
가정하면 안 됩니다. AWQ base 위 LoRA 지원 여부는 vLLM·CUDA·quantization 조합에 따라
달라질 수 있으며, 학습에 사용한 원본 base commit과 AWQ checkpoint의 계보도 확인해야
합니다. 가장 안전한 호환성 기준은 학습 manifest의 원본 `base_model`과 immutable
`base_revision`으로 base와 adapter를 먼저 함께 서빙하는 것입니다. AWQ를 사용하려면 별도
smoke에서 base/adapter 둘 다 로드되고 동일 요청에 응답하는지 검증한 후 평가하세요.

## 평가 시 최소 실험군

현재 `evaluate_models.py`는 모델 ID 비교용이라 이 LoRA 실험을 그대로 실행하지 못합니다.
별도 blind runner에서 최소한 다음 네 조건을 같은 case에 paired 실행해야 합니다.

1. 동일 base + 공통 task prompt
2. 동일 base + TrendCard
3. 동일 base + TrendCard + train split에서만 고른 few-shot
4. 동일 base + LoRA + 동일 TrendCard

LoRA-only 조건은 이미 학습한 밈의 암기 여부를 보는 진단군일 뿐입니다. unseen 밈
일반화를 비교할 때는 LoRA군에도 다른 군과 동일한 TrendCard를 제공해야 합니다.
재시도와 fallback이 차이를 가릴 수 있으므로 raw first attempt 품질과 production
end-to-end 성공률을 분리해 보고합니다.

## 데이터 규모 해석

12/3 seed는 다음만 확인할 수 있습니다.

- production prompt와 JSON completion을 TRL에 전달할 수 있는가
- adapter checkpoint를 만들고 동일 base 서버에서 활성화할 수 있는가
- 작은 데이터에 즉시 과적합하는지 탐지할 수 있는가

의사결정용 비교에는 이보다 훨씬 많은 사람 검수 데이터가 필요합니다. 최소 pilot도
대략 1,000~2,000 train pair, 100~200 validation pair, 300개 이상의 완전 held-out test
case와 여러 밈 cluster를 권장합니다. 한 장의 TrendCard만 학습한 결과로 다른 밈에 대한
일반화나 TrendCard/few-shot 대비 우위를 주장하지 않습니다.
