# Ad Content Extension

광고 문구 생성 결과를 이미지 생성 모델까지 연결하는 확장 모듈입니다.

## 역할

```text
AdContentRequest
-> generate_ad_copy
-> Product Visualizer fallback
-> Prompt Normalizer
-> Image Generation Model
-> optional Image Validator
-> AdContentResponse
```

주의: `product_visualizer.py`에는 LLM 기반 상품 시각 분석, Product Visual DB, reference analyzer 연동 코드가 있지만 현재 `visualize()`가 먼저 fallback을 반환합니다. 따라서 일반 통합 요청에서 실제로 쓰이는 것은 입력 상품명을 기반으로 만든 단순 ProductVisualization입니다.

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
- Product Visualizer fallback 호출
- 이미지 prompt/negative prompt 생성
- 이미지 모델 호출
- 옵션 기반 이미지 검증
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

Hugging Face 공식 클라이언트로 현재 지원되는 이미지 공급자를 자동 선택해 호출합니다.

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

사용자 상품명, 특징, visual brief를 바탕으로 상품별 시각 정보 JSON을 생성하는 모듈입니다. 현재 런타임에서는 즉시 fallback을 반환하므로 DB 캐시와 reference analyzer 경로는 실행되지 않습니다.

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

이미지 검증 hook입니다. `BRANDMATE_IMAGE_VALIDATION_ENABLED=true`이고 OpenAI-compatible vision API key가 있을 때 생성 이미지를 VLM으로 검사합니다. 기본값은 false라서 일반 실행에서는 검증을 건너뜁니다.

## 환경 변수

```env
# [Design Intent] 이미지 생성은 외부 유료 API가 아니라 자체 GPU VM의 ComfyUI를 기본 경로로 사용한다.
BRANDMATE_IMAGE_PROVIDER=comfyui
BRANDMATE_COMFYUI_BASE_URL=http://127.0.0.1:8188
BRANDMATE_IMAGE_PROMPT_TEMPLATE=generic

# 현재 통합 요청 경로에서는 product_visualizer.py 조기 fallback 때문에
# reference search가 실행되지 않는다. 활성화하려면 visualizer 로직 수정이 먼저 필요하다.
BRANDMATE_REFERENCE_SEARCH_ENABLED=false
BRANDMATE_REFERENCE_SOURCE=wikimedia
BRANDMATE_REFERENCE_MAX_RESULTS=3
BRANDMATE_PRODUCT_VISUAL_DB_PATH=product_visual_profiles.sqlite3
BRANDMATE_PEXELS_API_KEY=
BRANDMATE_UNSPLASH_ACCESS_KEY=

BRANDMATE_IMAGE_VALIDATION_ENABLED=false
BRANDMATE_IMAGE_VALIDATOR_MODEL_NAME=
```

기존 웹 테스트 방식은 그대로 사용할 수 있습니다. 이미지 생성은 FastAPI가 ComfyUI
HTTP API를 호출하는 방식입니다. 현재 기본 경로는 FLUX.1 Schnell GGUF workflow입니다.

```env
# [Design Intent] FastAPI와 ComfyUI가 같은 VM에서 실행되면 내부 localhost 주소를 사용한다.
BRANDMATE_IMAGE_PROVIDER=comfyui
BRANDMATE_COMFYUI_BASE_URL=http://127.0.0.1:8188
```

Hugging Face Router는 외부 유료 API 경로이므로 현재 운영 기본값에서 제외합니다.
임시 API 테스트가 필요할 때만 별도 `.env`에서 `BRANDMATE_IMAGE_PROVIDER=huggingface`로
바꿔 사용합니다.

```env
# [Design Intent] 외부 API 테스트는 운영 기본값이 아니라 임시 우회 경로로만 둔다.
BRANDMATE_IMAGE_PROVIDER=huggingface
# auto는 모델을 지원하는 현재 공급자를 Hugging Face Router가 선택합니다.
BRANDMATE_HF_IMAGE_PROVIDER=auto
BRANDMATE_HF_IMAGE_EDIT_MODEL=black-forest-labs/FLUX.1-Kontext-dev
BRANDMATE_LLM_API_KEY=...
```

참고 사진이 없는 Hugging Face 요청은 선택한 text-to-image 모델을 사용합니다. 참고 사진이
있으면 사진 원본 바이트를 `FLUX.1-Kontext-dev` image-to-image 요청에 직접 전달하며, 실제
사용된 편집 모델은 응답의 `image.model`과 artifact 메타데이터에 기록됩니다.

현재 비전 모델 평가코드는 터미널 생성 기준이며, 웹요청 중 자동으로 실행되지 않습니다. 평가지표, `report.json`, `report.md`, 평가용 이미지 저장은 터미널에서 `scriptsevaluate_vision_models`를 실행했을 때만 생성됩니다. 웹 UI에는 기존처럼 광고 문구 생성 시간과 이미지 생성 시간만 표시됩니다.

## 실행

```cmd
cd apps\api
.venv\Scripts\python.exe -m uvicorn app.extensions.ad_content.main:app --host 127.0.0.1 --port 8000
```
