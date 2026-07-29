# Ad Copy Module

광고 문구, 마케팅 전략, visual brief를 생성하는 모듈입니다.

## 기준 브랜치 대비 변경점

`feature/ad-copy-model-integration`에서는 광고 문구 생성이 중심이었습니다. 현재 브랜치에서는 이미지 생성 파이프라인과 연결하기 위해 다음 구조가 추가되었습니다.

- Marketing Strategy
- Copywriting
- Visual Brief
- Output Validator
- Product Visualizer 연결을 위한 schema 확장
- 해시태그 제거

## 파일별 설명

```text
prompt.py
```

광고 문구 LLM에 전달하는 prompt를 생성합니다. 출력은 JSON만 허용합니다.

출력 주요 키:

```text
marketing_strategy
headlines
body_copies
ctas
validation_check
visual_brief
safety_notes
```

```text
schemas.py
```

광고 문구 request/response schema입니다.

중요 구조:

```text
MarketingStrategy
VisualBrief
ProductToShow
FeatureVisualization
ValidationCheck
AdCopyContent
AdCopyResponse
```

```text
input_validator.py
```

브라우저 입력값을 내부 enum으로 정규화합니다.

예:

```text
카페 -> cafe
신메뉴 -> new_menu
20대 -> twenties
감성적 -> emotional
인스타그램 -> instagram
```

```text
output_validator.py
```

LLM 출력 검증과 fallback 생성을 담당합니다.

검증 항목:

- 모든 상품명이 광고 문구나 CTA에 포함됐는지
- 모든 특징이 본문 문구에 포함됐는지
- 금지어가 포함됐는지
- visual brief에 모든 상품이 포함됐는지

```text
service.py
```

선택된 LLM 모델을 호출합니다. Hugging Face Router, LM Studio, vLLM, Ollama 같은 OpenAI-compatible endpoint로 확장할 수 있습니다.

## 수동 TrendCard

광고에 사용할 TrendCard의 공식 원본은 저장소 루트의
`data/processed/sns_trend/v2/cross_platform_signal_top_candidates/cross_platform_signal_top_candidates.json`
입니다. 이 payload는 사람이 작성·검수한 v2 카드들을 공식 processed 데이터셋 구조로
패키징한 산출물입니다.

- `curation_meta.status`가 `reviewed`인 카드만 광고에 사용합니다.
- `copy_markers`는 결과 검증 전용이며 LLM 프롬프트에는 전달하지 않습니다.
- Instagram 요청은 payload의 첫 번째 usable 카드를 active default로 선택합니다.
- 명시적인 `trend_card_id`가 전달되면 payload 안에서 해당 `meme_id`를 찾아 사용합니다.
- 배포 환경에서는 `BRANDMATE_TREND_CARD_PAYLOAD_PATH`로 JSON 위치를 지정할 수 있습니다.

## 실행 테스트

```cmd
cd apps\api
.venv\Scripts\python.exe -m pytest tests\test_ad_copy.py
```
