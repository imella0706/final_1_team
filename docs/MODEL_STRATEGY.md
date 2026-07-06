# 광고 문구 모델 전략

## 연결 방식

API는 OpenAI 호환 `/chat/completions` 규격으로 모델을 호출합니다. 기본 서버는
Hugging Face Inference Providers Router이며 환경변수로 로컬 vLLM 서버를 사용할 수
있습니다. 모델 출력은 JSON Schema로 요청하고 Pydantic으로 다시 검증합니다.

## 비교 모델

| 모델 | 현재 연결 방식 | 용도·주의사항 |
| --- | --- | --- |
| Qwen 2.5 7B Instruct | HF Provider, 실측 성공 | 한국어 광고 문구 기본 모델 |
| Llama 3.1 8B Instruct | HF Provider, 실측 성공 | Meta 접근 동의 필요 |
| Mistral 7B Instruct v0.3 | 로컬 서버 | 현재 HF 호스팅 Provider 없음 |
| Gemma 2 9B Instruct | 로컬/별도 Endpoint | 현재 기본 HF Router 미지원 |
| Phi 4 Mini Instruct | 로컬/별도 Endpoint | 현재 기본 HF Router 미지원 |
| SOLAR 10.7B Instruct | 로컬/별도 Endpoint, 연구 전용 | Router 미지원, CC BY-NC 4.0 |

테스트 페이지에서는 같은 입력과 프롬프트 계약으로 모델을 바꿔 결과를 비교합니다.
Provider, 접근권한 또는 라이선스 차이를 모델 품질 차이와 혼동하지 않도록 실행 실패도
그대로 기록합니다.

## 평가 항목

- 한국어 자연스러움
- 광고 문구 매력도
- 과장·기만 표현 여부
- CTA 품질
- 해시태그 품질
- 요청한 말투와 필수 표현 준수
- JSON 형식 준수율
- 생성 시간과 요청당 비용

## 학습 원칙

초기에는 모델을 별도로 학습하지 않습니다. 업종별 프롬프트와 few-shot 예시로 먼저
비교하고, 사용자가 선택하거나 수정한 결과가 충분히 쌓였을 때 LoRA 또는 SFT 필요성을
다시 판단합니다.
