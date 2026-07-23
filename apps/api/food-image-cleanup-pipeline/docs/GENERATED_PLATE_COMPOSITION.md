# 생성 접시 기반 음식 합성(선택 실험 모드)

> 현재 기본 모드는 `preserve_original_plate`다. 즉 원본 접시와 음식을 함께 보존한다. `generated_plate`는 `food_visible` 분할 마스크 품질이 확인된 경우에만 켤 수 있는 선택 실험 모드다.

## 목적

기존 방식은 원본 사진의 음식·접시·식탁보를 한 전경으로 유지했다. 이 방식에서는 원본 접시 외곽이 조금만 잘려도 합성 결과가 부자연스러워지고, 원본 식탁보가 함께 남는다.

선택한 `generated_plate` 모드는 원본에서 **음식만** 추출하고, 배경 생성 모델이 만든 빈 접시 위에 음식만 올린다. 따라서 원본 접시, 식탁보, 음식 아래의 작은 물건은 최종 광고 이미지에 포함되지 않는다. 다만 기본 모드는 원본 접시 외곽을 보존하는 `preserve_original_plate`이므로, 접시 무늬와 실제 메뉴 사진의 일관성을 우선한다.

## 처리 흐름

1. 음식 탐지와 SAM으로 음식 구조 마스크를 만든다.
2. 음식 전용 마스크를 안정화하고 SAM 기반 알파만 사용한다. 현재 BiRefNet은 실행하지 않는다.
3. 배경 프롬프트에 중앙의 빈 흰색 원형 접시와 접시 테두리 보존 조건을 넣는다.
4. 여러 배경 후보를 만들고, 중앙 접시 후보를 찾는다.
5. 중앙 접시가 없거나 점수가 낮은 후보, 음식·그릇·컵 등이 중앙 배치 영역에 있는 후보는 버린다.
6. 선택된 접시의 중심을 기준으로 음식 전경을 배치한다. 음식의 짧은 변은 접시 짧은 변의 56%를 기본값으로 사용한다.
7. 음식에만 접지 그림자, 색상 조화, 경계 보정을 적용하고 의미·품질 검증을 수행한다.

원본 접시를 새로 생성하지 않는 것이 핵심이다. 생성 모델이 배경과 함께 만든 접시는 조명·원근·그림자가 이미 일치하므로, 원본 접시 외곽이 끊기는 문제를 구조적으로 피할 수 있다.

## 설정

`configs/pipeline.yaml`의 설정은 다음과 같다.

```yaml
models:
  generated_plate_composition:
    enabled: true
    mode: preserve_original_plate # 선택 실험 모드는 generated_plate
    require_food_visible_mask: true
    minimum_plate_score: 0.45
    food_width_ratio_of_plate: 0.56
    minimum_food_width_ratio: 0.12
    maximum_food_width_ratio: 0.42
```

- `generated_plate`: 음식만 추출해 생성된 빈 접시 위에 배치하는 선택 실험 모드다. 기본 모드는 `preserve_original_plate`다.
- `preserve_original_plate`: 이전 호환 모드다. 원본 접시를 유지해야 하는 예외 상황에서만 사용한다.
- `minimum_plate_score`: 중앙성·크기·원형성을 바탕으로 계산한 접시 후보의 최소 점수다. 후보 품질이 낮다면 `0.55`까지 올릴 수 있다.
- `food_width_ratio_of_plate`: 음식 전경 크기다. 음식이 접시를 과하게 덮으면 `0.45~0.52`로 낮춘다.

## 프롬프트 규칙

생성 접시 모드에서는 프롬프트에 다음 조건이 자동으로 추가된다.

```text
one empty round white ceramic dinner plate centered on the table,
fully visible with a clean intact rim, large enough to hold one dish
```

사용자 프롬프트에 `no plate`가 있더라도 생성 접시 모드에서는 이 문구를 제거한다. `no food`는 유지하므로 생성 배경의 접시는 비어 있어야 한다.

## 확인 방법

실행 후 보고서의 `step_8_background_generation.candidates`에서 각 후보의 `generated_plate` 값을 확인한다. `found=true`, `score >= minimum_plate_score`인 후보만 최종 선택 대상이 된다.

최종 결과가 어색하면 다음 순서로 점검한다.

1. `*_generated_background_candidate_*.jpg`에서 중앙 접시가 완전하고 비어 있는지 확인한다.
2. 보고서의 선택 후보 `generated_plate.width_ratio`, `height_ratio`가 너무 작지 않은지 확인한다.
3. 음식이 크면 `food_width_ratio_of_plate`를 낮춘다.
4. 접시가 포함된 원본을 유지해야 하는 특수 사례만 `preserve_original_plate`로 전환한다.

로컬 실행과 코랩 노트북은 모두 같은 `configs/pipeline.yaml`을 읽으므로, 별도의 노트북 설정 변경 없이 이 모드가 적용된다.
