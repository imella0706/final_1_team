# 구현 계획

## 제품 목표

광고 문구 작성 경험이 없는 소상공인이 몇 가지 정보만 입력해도 게시 가능한 광고 초안을
얻도록 돕습니다. 현재 코드는 광고 문구 생성에서 실제 이미지 생성 호출까지 이어지는
동기식 MVP입니다. 더 이상 이미지 생성 모의 실행만 하는 상태가 아닙니다.

## 첫 사용자 흐름

```text
매장/상품 정보 입력
  → 광고 목적과 게시 채널 선택
  → 광고 문구 생성
  → 문구·CTA·해시태그·visual_brief 확인
  → image prompt / negative prompt 생성
  → 실제 이미지 생성 결과 확인
```

## 입력

- 상호명과 업종
- 상품 또는 서비스명
- 핵심 특징과 고객에게 줄 혜택
- 목표 고객
- 광고 상황: 신메뉴, 할인, 이벤트, 배달, 포장, 방문 유도
- 비교할 광고 문구 모델
- 게시 채널: Instagram, Naver Blog, 배달앱 등
- 원하는 말투
- 할인·기간 같은 프로모션 정보(선택)
- 반드시 포함하거나 피해야 할 표현(선택)

## 출력

- 핵심 문구 후보 3개
- 본문 문구 후보 3개
- CTA 후보
- 해시태그
- 이미지 모델로 전달할 image prompt / negative prompt
- 생성 이미지 base64 payload
- 로컬 artifact 경로
- 과장 또는 위험 표현에 대한 주의사항

응답은 이후 광고 이미지 제작에서도 재사용할 수 있도록 JSON으로 구조화합니다.

## 현재 구현 상태

구현됨:

- 광고 문구 LLM 호출
- `marketing_strategy`, `channel_recommendation`, `visual_brief` 구조화
- LLM 출력 Pydantic 검증, 재시도, fallback copy
- 통합 endpoint `/api/v1/ad-content/generate`
- 이미지 모델 선택과 실제 이미지 생성 호출
- Prompt Normalizer와 negative prompt 생성
- 옵션 기반 VLM 이미지 검증 hook
- 생성 결과 local artifact 저장

구현됐지만 현재 통합 요청에서 활성화되지 않음:

- Product Visual DB 조회
- Wikimedia/Pexels/Unsplash reference metadata 검색
- Reference Analyzer 기반 상품 시각 특징 추출

위 세 기능은 코드 파일이 있지만 `ProductVisualizer.visualize()`가 즉시 fallback을 반환하므로
현재 일반 요청 경로에서는 실행되지 않습니다.

아직 미구현:

- job queue, polling endpoint, worker 분리
- GPU 작업 동시성 제한
- object storage 기반 이미지 저장과 URL 반환
- 사용자 평가/선호도 저장 API
- request_id 기반 structured logging과 운영 metric

## 구현 단계

### 1단계 — 계약과 프롬프트

- Pydantic 요청·응답 스키마 작성
- 음식점, 카페, 베이커리 등 업종별 프롬프트 템플릿 작성
- JSON 출력 검증과 실패 시 재시도 규칙 작성
- 금칙어와 과장 표현에 대한 기본 안전 규칙 작성

### 2단계 — 모델 연결 (구현됨)

- Qwen, Llama, Mistral, Gemma, Phi, SOLAR 선택 계약
- Hugging Face Router 또는 로컬 vLLM용 OpenAI 호환 호출
- 타임아웃, Provider 오류와 JSON 검증 오류 응답
- 생성 결과에 모델, 프롬프트 버전과 처리 시간 기록

### 2.5단계 — 이미지 생성 통합 (부분 구현됨)

- 통합 API에서 광고 문구 생성 후 이미지 생성 모델 호출
- ComfyUI, OpenAI image API, OpenAI Responses image tool, Hugging Face image endpoint 지원 구조
- 생성 결과 base64 응답과 local artifact 저장
- Naver Blog 채널은 생성 이미지를 만들지 않고 업로드 이미지를 활용
- Product Visualizer는 현재 fallback만 사용하므로 reference 기반 시각 분석 활성화 필요

### 3단계 — 품질 평가

- JSON 최초 준수율과 최종 태스크 성공률
- 문맥·필수어·금칙어 준수
- 한국어 톤앤매너와 광고 문구 자연스러움
- 입력에 없는 주장과 유해 표현 비율
- CTA, 해시태그, 영문 이미지 프롬프트 품질
- Mean, P50, P95, P99 지연시간과 처리량
- 이미지 생성 연결 후 CLIP Score, Aesthetic Score, Failure Rate, Diversity Score 평가지표 자동화
- 이미지 최종 후보 검증용 GPT-4o Vision Judge, Human Preference, ImageReward

동일 입력으로 모델을 바꿔 실행하며 Qwen을 한국어 기준 모델로 비교합니다. 접근권한,
Provider 지원과 라이선스 차이는 품질 점수와 별도로 기록합니다.
자동 평가 결과는 JSON과 Markdown 보고서로 저장하며, 주관적 품질은 사람 평가 또는
Judge 모델과 교차 검증합니다. 구체적인 계산 방식은 `docs/EVALUATION.md`에서 관리합니다.

### 4단계 — 테스트 페이지

- 한 화면 안에서 입력과 실제 광고 문구 결과를 확인
- Qwen, Hugging Face/NVIDIA Llama, Mistral, Gemma, Phi, SOLAR 선택
- 광고 문구 모델과 이미지 모델의 처리 상태 표시
- 두 모델 사이에 전달되는 JSON 표시
- 어려운 마케팅 용어 대신 예시와 쉬운 설명 제공

### 5단계 — 실제 사용자 화면

- 결과 복사와 모델별 비교 이력 지원
- 사용자가 채택하거나 수정한 결과를 품질 개선 데이터로 축적

## 지금 하지 않는 것

- 영상 모델 호출
- OCR과 사업계획서 생성
- 모델 파인튜닝 또는 LoRA
- Redis 큐와 별도 워커
- 복잡한 계정·조직·권한 시스템
- 사용처가 정해지지 않은 공용 패키지 분리

초기에는 프롬프트와 few-shot 예시로 품질을 확인합니다. 실제 사용자 데이터가 충분히
쌓이기 전에는 별도 학습을 진행하지 않습니다.

정적 프론트엔드와 통합 API는 실제 이미지 생성 결과를 표시할 수 있습니다. 다만 현재 구조는
장시간 HTTP 요청 기반이므로 운영형 서비스로 보려면 job queue와 object storage 전환이 먼저 필요합니다.
