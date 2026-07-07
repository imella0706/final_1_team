# Ad Content Extension

광고 문구 생성 결과를 이미지 생성 모델까지 연결하는 확장 모듈입니다.

## 역할

```text
AdContentRequest
-> generate_ad_copy
-> Product Visualizer
-> Prompt Normalizer
-> Image Generation Model
-> AdContentResponse
```

기존 광고 문구 API를 유지하면서 `/api/v1/ad-content/generate` endpoint를 제공합니다.

## 파일별 설명

```text
main.py
```

확장 FastAPI app entrypoint입니다. 브라우저 통합 화면은 이 app을 실행합니다.

```text
router.py
```

광고 콘텐츠 통합 endpoint를 정의합니다.

- 광고 문구 생성
- Product Visualizer 호출
- 이미지 prompt/negative prompt 생성
- 이미지 모델 호출
- 최종 응답 조립

```text
schemas.py
```

광고 콘텐츠 요청/응답 schema입니다. 기존 request schema를 유지하면서 응답에 `product_visualization`, `image_prompt`, `negative_prompt`, `validation`, `models`를 포함합니다.

```text
models.py
```

브라우저에서 선택할 수 있는 이미지 생성 모델 목록입니다.

```text
image_service.py
```

Hugging Face Inference Router 스타일의 이미지 생성 API를 호출합니다.

```text
image_prompt.py
```

최종 이미지 프롬프트와 negative prompt를 생성합니다. Product Visualizer 결과의 `english_name`, `visual_description`, `serving_style`, `must_show`, `must_not_replace_with`를 사용합니다.

```text
prompt_normalizer.py
```

Product Visualizer 출력과 visual brief를 image prompt builder에 연결합니다.

```text
product_visualizer.py
```

사용자 상품명, 특징, visual brief를 바탕으로 상품별 시각 정보 JSON을 생성합니다. Product Visual Database가 켜져 있으면 DB 캐시와 reference analyzer를 먼저 사용합니다.

```text
reference_search.py
```

Wikimedia Commons, Pexels, Unsplash 같은 공식/라이선스 명확한 source에서 reference image metadata를 검색합니다. 이미지 파일은 저장하지 않습니다.

```text
reference_analyzer.py
```

검색된 reference metadata를 LLM에 전달하여 일반 시각 특징만 추출합니다.

```text
reference_store.py
```

SQLite 기반 Product Visual DB입니다. 이미지 파일이 아니라 시각 특징 JSON과 source metadata만 저장합니다.

```text
image_validator.py
```

이미지 검증 hook입니다. 현재는 옵션 구조이며, 추후 CLIP 같은 이미지-텍스트 유사도 모델을 연결할 수 있습니다.

## 환경 변수

```env
BRANDMATE_IMAGE_BASE_URL=https://router.huggingface.co/hf-inference
BRANDMATE_IMAGE_PROVIDER=huggingface
BRANDMATE_IMAGE_PROMPT_TEMPLATE=generic

BRANDMATE_REFERENCE_SEARCH_ENABLED=false
BRANDMATE_REFERENCE_SOURCE=wikimedia
BRANDMATE_REFERENCE_MAX_RESULTS=3
BRANDMATE_PRODUCT_VISUAL_DB_PATH=product_visual_profiles.sqlite3
BRANDMATE_PEXELS_API_KEY=
BRANDMATE_UNSPLASH_ACCESS_KEY=

BRANDMATE_IMAGE_VALIDATION_ENABLED=false
BRANDMATE_IMAGE_VALIDATOR_MODEL_NAME=
```

기존 웹 테스트 방식은 그대로 사용할 수 있습니다. Hugging Face API로 이미지를 생성하려면
`BRANDMATE_IMAGE_PROVIDER`를 비우거나 `huggingface`로 설정합니다.

```env
# [Design Intent] 기존 API 키 기반 이미지 생성 경로를 기본값으로 유지한다.
BRANDMATE_IMAGE_PROVIDER=huggingface
BRANDMATE_IMAGE_BASE_URL=https://router.huggingface.co/hf-inference
BRANDMATE_LLM_API_KEY=...
```

로컬 FLUX를 테스트할 때만 `BRANDMATE_IMAGE_PROVIDER=comfyui`로 바꾸고 ComfyUI를
실행합니다. 현재 로컬 ComfyUI 경로는 FLUX.1 Schnell만 지원하며 다른 모델을 추가할 예정입니다.

```env
# 로컬 ComfyUI 서버가 떠 있을 때만 FLUX workflow를 사용
BRANDMATE_IMAGE_PROVIDER=comfyui
BRANDMATE_COMFYUI_BASE_URL=http://127.0.0.1:8188
```

현재 비전 모델 평가코드는 터미널 생성 기준이며, 웹요청 중 자동으로 실행되지 않습니다. 평가지표, `report.json`, `report.md`, 평가용 이미지 저장은 터미널에서 `scriptsevaluate_vision_models`를 실행했을 때만 생성됩니다. 웹 UI에는 기존처럼 광고 문구 생성 시간과 이미지 생성 시간만 표시됩니다.

## 실행

```cmd
cd apps\api
.venv\Scripts\python.exe -m uvicorn app.extensions.ad_content.main:app --host 127.0.0.1 --port 8000
```
