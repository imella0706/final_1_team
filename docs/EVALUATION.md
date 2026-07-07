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

결과는 Git에 포함되지 않는 `outputs/evaluations`에 JSON과 Markdown 두 형식으로
생성됩니다. JSON에는 개별 요청·출력·오류가, Markdown에는 모델별 요약표가 기록됩니다.

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
- Vision Quality: 실제 이미지 생성 모델이 연결된 뒤 측정

측정할 수 없는 값은 보고서에서 `null`로 남깁니다.

## Vision 평가 확장

이미지 모델 연결 후 같은 평가 보고서에 다음 항목을 추가합니다.

1. CLIP Score
2. ImageReward
3. VLM-as-a-Judge
4. Human Preference
5. Aesthetic Score
6. Failure Rate
7. CLIP 또는 DINO 임베딩 기반 Diversity

사람 선호도는 모델명을 가린 블라인드 A/B 방식으로 기록하고, 자동 점수와 최종적으로
교차 검증합니다.

## 평가 데이터

초기 데이터는 `apps/api/evals/ad_copy_cases.json`에 있습니다. 업종·상황·타겟·톤과
금칙어 조합을 포함한 6개 스모크 케이스이며, 모델 선정 전에는 최소 30개 이상으로
확장합니다.
