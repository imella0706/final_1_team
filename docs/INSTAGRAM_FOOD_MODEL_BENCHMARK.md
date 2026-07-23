# 음식 사진 Instagram 모델 성능 테스트

`apps/api/scripts/run_instagram_food_benchmark.py`는 음식 사진 10장에 동일한
Instagram 광고 조건을 적용하고 LLM, Vision, 이미지 생성 모델을 비교한다.

## 기본 테스트 사진

메타데이터와 사진이 모두 존재하는 다음 10장을 사용한다.

| 음식 | 업종 | 상품군 |
| --- | --- | --- |
| 마늘빵 | bakery | bread |
| 감자토스트 | bakery | sandwich |
| BLT샌드위치 | cafe | brunch |
| 단호박샐러드 | cafe | brunch |
| 어묵튀김 | pub | fried_side |
| 마라살꼬치 | pub | grilled_side |
| 깐풍치킨(뼈) | restaurant | chicken |
| 가리비초밥 | restaurant | japanese_food |
| 단호박피자 | restaurant | pizza |
| 날치알크림파스타 | restaurant | western_food |

사진별 상품명, 업종, 설명, 키워드와 시각 스타일은
`data/images/prompt_metadata*.csv`에서 읽는다. 원본 파일은 변경하지 않는다.
확장자가 JPG이지만 실제 형식이 PNG인 파일도 모델 호출용 메모리 복사본만
RGB JPEG, 최대 1024×1024, 데이터 URL 3,800,000자 이하로 변환한다.

## 테스트 방식

기본 `one-factor` 방식은 첫 번째 모델 조합을 기준으로 LLM, Vision, 이미지
모델을 한 종류씩 바꾼다. 모델군별 영향을 더 적은 호출로 분리해서 비교하기
위한 방식이며 사진 10장 기준 140회가 계획된다.

`full` 방식은 선택한 세 모델군의 Cartesian product를 실행한다. 기본 모델
전체를 사용하면 10 × 8 LLM × 5 Vision × 3 이미지 = 1,200회이므로 API 비용과
로컬 실행 시간을 확인한 뒤 제한적으로 실행해야 한다.

로컬 FLUX.1 Schnell은 참조 사진을 받지 않는 text-to-image 모델이므로 기본
목록에서 제외했다. 해당 모델의 실패·호환성까지 확인하려면 `--image-model`
옵션으로 명시할 수 있다.

## 실행

아래 명령은 모델을 호출하지 않고 10장 매니페스트와 실행 계획만 만든다.

```powershell
cd apps/api
.\.venv\Scripts\python -m scripts.run_instagram_food_benchmark
```

작은 교차 테스트부터 실제 실행하려면 모델을 명시하고 횟수를 제한한다.

```powershell
.\.venv\Scripts\python -m scripts.run_instagram_food_benchmark `
  --llm-model local/qwen2.5:7b `
  --llm-model openai/gpt-5.4-mini `
  --vision-model local/qwen3-vl:4b `
  --vision-model openai/gpt-5.4-mini `
  --image-model stabilityai/stable-diffusion-xl-base-1.0 `
  --image-model openai/gpt-image-1-mini `
  --matrix-mode full `
  --max-runs 20 `
  --concurrency 1 `
  --save-text-overlay `
  --execute
```

`--save-text-overlay`를 지정하면 원본 생성 이미지와 함께 GPT/LLM이 만든
`overlay_headline`과 음식명이 합성된 `generated-with-copy.png`를 저장한다.
완료된 기존 실행에 문구 이미지만 추가하려면 모델을 다시 호출하지 않고 다음처럼
실행한다.

```powershell
.\.venv\Scripts\python -m scripts.run_instagram_food_benchmark `
  --render-overlays-from-run ..\..\outputs\instagram-food-benchmark\<실행시각>
```

API 키는 명령행에서 받지 않고 기존 `apps/api/.env` 설정을 사용한다. 로컬
모델을 선택할 때는 Ollama와 ComfyUI가 실행 중이어야 한다.

## 결과

실행 결과는 `outputs/instagram-food-benchmark/<실행시각>/`에 저장된다.

- `plan.json`: 실행할 사진·모델 조합
- `trials.jsonl`: 성공과 실패를 즉시 한 줄씩 기록한 로그
- `trials/<trial-id>/generated.*`: 생성 이미지
- `trials/<trial-id>/generated-with-copy.png`: Instagram 문구가 합성된 이미지
- `trials/<trial-id>/source-original-<이미지명>`: 모델 입력에 사용한 원본 사진의 정확한 복사본
- `text-overlay-manifest.json`: 합성 문구와 원본·결과 이미지 대응표
- `source-image-manifest.json`: 원본 사진과 저장 복사본의 경로·SHA-256 대응표
- `trials/<trial-id>/result.json`: 광고 문구, 프롬프트, 검증 결과
- `report.json`: 모델군별 파이프라인 성공률, 순수 모델 문구 성공률, fallback
  문구 사용률, 평균 재시도, 지연시간, 문구 준수도 집계
- `manual-review.csv`: 사람이 1~5점으로 음식 동일성, 사진 유사도, 한국어
  문구 품질, Instagram 적합성, 시각 품질을 평가하는 양식

자동 지표만으로 광고 품질을 확정하지 않는다. 최종 비교에서는 같은 사진의
결과를 나란히 보고 `manual-review.csv`를 작성하는 것이 필요하다.

## Hugging Face 실행 시 데이터 정제

작은 오픈모델이 잘못된 데이터셋 설명을 광고 사실로 사용하는 것을 막기 위해
`caption`, 음식 코드, 영문 스타일 라벨은 매니페스트의 감사 정보로만 보존하고
모델 입력에서는 제외한다. 실제 시각 정보는 업로드 사진을 받은 Vision 분석을
기준으로 한다. Hugging Face LLM에는 strict JSON Schema 대신 호환성이 높은
JSON-object 모드와 temperature 0.2를 사용하며, 반환값은 동일한 Pydantic
스키마로 다시 검증한다.

HF 전용 10장 실행 예시는 다음과 같다.

```powershell
.\.venv\Scripts\python -m scripts.run_instagram_food_benchmark `
  --llm-model Qwen/Qwen2.5-7B-Instruct `
  --vision-model Qwen/Qwen2.5-VL-7B-Instruct `
  --image-model black-forest-labs/FLUX.1-schnell `
  --image-provider-override huggingface `
  --matrix-mode full `
  --save-text-overlay `
  --concurrency 1 `
  --execute
```

참고 사진이 있으면 HF 이미지 생성 단계는 설정된 이미지 편집 모델
`black-forest-labs/FLUX.1-Kontext-dev`로 라우팅된다. 따라서 결과 JSON의
`image_model_actual`을 기준으로 실제 호출 모델을 확인해야 한다.
