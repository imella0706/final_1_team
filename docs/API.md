# 광고 문구 API 초안

모든 API 경로의 접두사는 `/api/v1`입니다.

## 광고 문구 생성

`POST /ad-copies/generate`

선택한 모델을 OpenAI 호환 LLM 엔드포인트로 호출합니다. API 키가 없으면 `503`,
Provider 접근·호출 또는 출력 검증에 실패하면 `502`를 반환합니다.

요청 예시:

```json
{
  "model": "Qwen/Qwen2.5-7B-Instruct",
  "business_name": "동네봄 카페",
  "business_type": "cafe",
  "situation": "new_menu",
  "target_audiences": ["twenties", "office_workers"],
  "tone": "emotional",
  "product_names": ["수제 딸기 티라미수", "런치세트"],
  "features": ["매일 손질한 생딸기", "직접 만든 딸기청"],
  "channel": "instagram",
  "promotion": "7월 한 달간 10% 할인",
  "required_terms": ["생딸기"],
  "prohibited_terms": ["무조건", "최고"]
}
```

응답 예시:

```json
{
  "headlines": ["오늘의 달콤한 쉼표, 생딸기 라테"],
  "body_copies": [
    "매일 손질한 생딸기와 직접 만든 딸기청으로 산뜻한 한 잔을 준비했어요."
  ],
  "ctas": ["퇴근길, 동네봄 카페에 들러보세요."],
  "hashtags": ["#생딸기라테", "#동네카페", "#카페추천"],
  "image_prompt": "Editorial food photography of handmade strawberry tiramisu...",
  "safety_notes": [],
  "model": "Qwen/Qwen2.5-7B-Instruct",
  "routed_model": "Qwen/Qwen2.5-7B-Instruct",
  "provider": "auto",
  "prompt_version": "ad-copy-v1",
  "latency_ms": 1840
}
```

실제 구현의 단일 계약은 `apps/api/app/modules/ad_copy/schemas.py`에서 관리합니다.
요청과 응답의 후보 개수와 문자열 길이 제한도 이 스키마에서 검증합니다.

## 선택 가능한 모델

`GET /ad-copies/models`

모델 ID와 크기, 호스팅 가능 여부, 접근·라이선스 주의사항을 반환합니다. 프론트엔드는
이 목록과 같은 모델 ID를 생성 요청의 `model` 필드에 전달합니다.

NVIDIA NIM의 Llama 3.1 8B를 선택할 때는 다음 모델 ID를 사용합니다.

```json
{
  "model": "nvidia/meta/llama-3.1-8b-instruct"
}
```

이 선택 ID는 내부적으로 NVIDIA의 `meta/llama-3.1-8b-instruct` 모델에 라우팅됩니다.
