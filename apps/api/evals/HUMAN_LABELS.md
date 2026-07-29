# Human calibration labels

`human_labels.template.json` 또는 `human_labels.template.csv`를 복사한 뒤 빈 행을 실제
평가 값으로 채웁니다. 템플릿의 빈 값은 의도적으로 loader 검증을 통과하지 않으므로 완료된
라벨로 오인할 수 없습니다.

- 다섯 점수(`naturalness`, `pattern_fidelity`, `product_relevance`, `factuality`,
  `channel_readiness`)는 각각 1~5의 정수입니다.
- `acceptable`은 `yes` 또는 `no`만 사용합니다.
- `output_sha256`과 `card_sha256`은 평가한 출력과 카드 원본의 소문자 SHA-256입니다.
- 같은 출력을 두 명이 독립 평가할 때는 행을 복제하고 `rater_id`만 평가자별로 다르게
  지정합니다. 다른 output/trial/card/case ID와 두 SHA-256은 동일하게 유지합니다.
- `comment`는 선택 사항이며 빈 값으로 둘 수 있습니다.
- `rubric_version`은 현재 `meme-human-rubric-v1`입니다. 루브릭을 바꾸면 기존 라벨과
  섞지 않습니다.

JSON과 CSV는 같은 loader로 검증합니다.

```python
from pathlib import Path

from app.evaluation.human_labels import load_human_evaluation_labels

label_set = load_human_evaluation_labels(Path("evals/human_labels.json"))
for label in label_set.labels:
    print(label.output_id, label.rater_id, label.acceptable)
```

필수 ID·해시·점수가 비어 있거나, 점수가 범위를 벗어나거나, 같은 평가자가 같은 출력을
중복 평가하거나, 동일 output/card ID에 서로 다른 SHA-256이 연결되면
`HumanLabelDataError`가 발생합니다.
