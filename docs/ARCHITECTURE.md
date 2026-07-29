# 아키텍처

이 문서는 현재 코드 기준의 런타임 구조를 설명합니다. README나 예전 계획 문서보다 이 파일을 우선 기준으로 봅니다.

## 현재 실행 흐름

통합 광고 콘텐츠 endpoint는 하나의 FastAPI 요청 안에서 광고 문구 생성부터 이미지 생성까지 순차 실행합니다.

```text
Browser
  -> POST /api/v1/ad-content/generate
  -> AdContentRequest validation
  -> generate_ad_copy()
     -> LLM call
     -> Pydantic schema validation
     -> output retry or fallback copy
  -> ProductVisualizer.visualize()
     -> current runtime: fallback ProductVisualization
  -> describe_reference_image()
     -> OpenAI-compatible vision model only when reference image and API key exist
  -> normalize_image_prompt()
     -> image prompt
     -> negative prompt
  -> generate_ad_image()
     -> ComfyUI, OpenAI image API, OpenAI Responses image tool, or Hugging Face image endpoint
  -> validate_generated_image()
     -> skipped unless BRANDMATE_IMAGE_VALIDATION_ENABLED=true
  -> save_ad_content_artifacts()
     -> local outputs/ad-content artifact write
  -> AdContentResponse
```

Naver Blog 채널은 별도 흐름입니다.

```text
Browser
  -> POST /api/v1/ad-content/generate
  -> optional describe_blog_images()
  -> generate_ad_copy()
  -> image generation skipped
  -> uploaded blog photo returned as image payload
```

## 코드 경계

```text
apps/api/app/modules/ad_copy/
  router.py             광고 문구 API
  schemas.py            광고 문구 입력/출력 계약
  prompt.py             광고 문구, 채널 추천, visual_brief 생성 프롬프트
  service.py            LLM 호출, 재시도, fallback 처리
  input_validator.py    한국어/legacy 입력값 정규화
  output_validator.py   상품명, 금지어, visual_brief 검증과 fallback copy

apps/api/app/extensions/ad_content/
  router.py             광고 문구 + 이미지 통합 endpoint
  schemas.py            통합 요청/응답 계약
  product_visualizer.py 상품별 ProductVisualization 생성
  image_prompt.py       최종 image prompt와 negative prompt 조립
  prompt_normalizer.py  prompt 길이 제한과 정규화
  image_service.py      이미지 모델 provider 호출
  image_validator.py    옵션 기반 VLM 이미지 검증
  artifact_store.py     로컬 산출물 저장
```

## 현재 구현 상태

- 실제 이미지 생성 API 호출은 구현되어 있습니다. 더 이상 "이미지 결과 모의 실행" 상태가 아닙니다.
- 광고 문구 LLM은 `marketing_strategy`, 광고 문구, `channel_recommendation`, `visual_brief`를 구조화 JSON으로 반환해야 합니다.
- 최종 이미지 프롬프트는 LLM이 직접 쓰는 것이 아니라 `image_prompt.py`가 `visual_brief`, 상품 정보, reference image context를 조립해서 만듭니다.
- `ProductVisualizer`는 호출되지만 현재 코드에서는 즉시 fallback을 반환합니다. 그래서 LLM 기반 상품 시각 분석, Product Visual DB 조회, reference search, reference analyzer는 일반 통합 요청에서 실행되지 않습니다.
- 이미지 검증은 `BRANDMATE_IMAGE_VALIDATION_ENABLED=false`가 기본값입니다. 기본 실행에서는 이미지 검증이 통과 처리됩니다.
- 생성 결과는 local filesystem의 `outputs/ad-content` 아래에 저장됩니다.

## 현재 한계

- 장시간 이미지 생성을 하나의 HTTP 요청 안에서 처리합니다. job queue, polling endpoint, worker 분리는 아직 없습니다.
- 로컬 파일 저장은 단일 VM 데모에는 충분하지만 수평 확장 구조에는 맞지 않습니다. 운영에서는 object storage URL을 반환해야 합니다.
- Product Visual DB와 Reference Analyzer는 코드만 존재하고 현재 요청 경로에서는 우회됩니다.
- 사용자 평가, 블라인드 A/B 선호도 저장, human feedback loop는 아직 API로 구현되어 있지 않습니다.
- request_id 기반 structured logging, stage별 error bundle, Prometheus/Grafana metric은 문서화된 계획 수준입니다.

## L2 MVP 판단

현재 구조는 "실제 이미지 생성이 붙은 동기식 MVP"입니다. 발표나 팀 공유에서는 아래처럼 말해야 합니다.

```text
구현됨:
- 광고 문구 생성
- visual_brief 구조화
- image prompt 정규화
- 이미지 모델 호출
- 옵션 기반 이미지 검증 hook
- 로컬 artifact 저장

미완성:
- Product Visualizer의 LLM/reference 분석 경로 활성화
- job queue와 GPU 작업 동시성 제어
- object storage 기반 결과 저장
- 사용자 평가 수집 API
- 운영 관측성
```
