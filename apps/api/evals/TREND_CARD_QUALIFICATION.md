# TrendCard 카드 축 qualification

이 도구는 기존 `evaluate_meme_arms.py`와 다른 질문에 답합니다.

- 기존 arm 평가: 카드 한 장을 고정하고 prompt 전략을 비교합니다.
- 카드 qualification: production 전략을 `trendcard`로 고정하고 여러 카드가 같은 광고 입력에서 쓸 만한 결과를 만드는지 관찰합니다.

현재 manifest는 다음 세 원본을 읽습니다.

- `gather_data/trendcard.json`
- `gather_data/trendcard1.json`
- `gather_data/trendcard2.json`

## 안전 경계

qualification loader는 `TrendCard` 스키마를 직접 검증합니다. Production loader의 `curation_meta.status == "reviewed"` 조건을 우회해 서비스를 호출하는 것이 아니라, draft를 평가 대상으로 읽기 위한 별도 read-only 경로입니다.

- 카드 원본을 수정하지 않습니다.
- `curation_meta.status`를 변경하지 않습니다.
- `quality_status`는 항상 `evidence_only`입니다.
- 권리 위험이 `high`인 카드는 생성 대상에서 제외합니다.
- case 채널이 `suitable_channels`에 없거나 marker가 case의 금지어와 충돌하면 해당 카드/case만 skip합니다.
- 한 카드의 파일·스키마·채널 preflight가 실패해도 나머지 카드는 계속 검사합니다.

자동 점수는 `reviewed`나 production activation을 의미하지 않습니다. 사람 Judge calibration과 권리 검수, 승인 상태 변경은 별도 단계입니다.

## Dry-run

`apps/api`에서 실행합니다.

```powershell
python -m scripts.evaluate_trend_cards --dry-run --skip-judge
```

Dry-run은 외부 API를 호출하거나 결과 디렉터리를 만들지 않고 다음을 확인합니다.

- 세 카드의 스키마와 exact-byte SHA-256
- 카드별 channel/rights/marker-conflict preflight
- 기존 case의 `trend_card_id`가 trial마다 현재 카드 ID로 교체되는지
- `(case, card, repeat)` 작업 수와 최대 예상 호출 수
- 카드·case별 production prompt snapshot과 SHA-256
- 실행 endpoint와 Judge credential 준비 상태

기본 설정은 `8 cases x 3 cards x 3 repeats = 72 trials`입니다. Prompt snapshot은 repeat과 무관하므로 `8 x 3 = 24`개입니다.

## Evidence smoke

현재 case fixture가 `seed_needs_review`인 동안 실제 외부 호출은 한 case, 한 repeat만 허용합니다.

```powershell
python -m scripts.evaluate_trend_cards `
  --case-limit 1 `
  --repeats 1 `
  --allow-unreviewed-fixtures
```

전체 case가 사람·권리 검수를 마친 뒤 전체 실행을 할 수 있습니다. 기본 실행은 최대 요청 수가 안전 한도를 넘으므로 dry-run 결과를 확인한 뒤 `--allow-large-run`을 명시해야 합니다.

## 결과

기본 저장 위치는 API workspace 내부입니다.

```text
apps/api/outputs/evaluations/trend_cards/{YYYYMMDD-HHMMSS}/
├─ candidate_outputs/
│  └─ candidate-*.json
├─ report.json
└─ report.md
```

각 trial은 다음 연결 키를 포함합니다.

- `output_id`, `trial_id`, `card_id`: 사람 calibration label과 직접 연결할 ID
- `candidate_card_id`
- `trend_card_id`
- `card_sha256` / `card_artifact_sha256`: 카드 파일의 exact-byte SHA-256
- `customer_visible_output`: Judge와 사람이 평가하는 최종 고객 노출 필드 allow-list
- `output_sha256`: `customer_visible_output`을 key 정렬·공백 없는 canonical JSON으로 직렬화한 SHA-256
- `case_id`, `repeat`, `generation_seed`

카드 summary에는 generation 성공률, deterministic validator 통과율, marker 준수율, repair 의존도, 환각·유해 표현률, Judge 다섯 축과 종합 평균이 기록됩니다. 실패 trial도 카드의 expected trial 분모에 남기므로 실패를 제외해 카드 점수가 높아지지 않습니다.

Judge는 실제 production pipeline이 반환하는 최종 output을 봅니다. 초안과 repair 결과도 trial 진단에 별도로 보존합니다.

## 구현 파일

- `app/evaluation/trend_card_runner.py`: manifest schema, draft-safe parse, runtime card injection, preflight, paired seed/work 생성
- `scripts/evaluate_trend_cards.py`: dry-run, 실제 생성·validator·Judge, 카드별 집계와 artifact 출력
- `evals/trend_card_qualification.json`: 세 카드와 고정 전략 설정
- `tests/test_trend_card_qualification.py`: 카드 축 전용 회귀 테스트
