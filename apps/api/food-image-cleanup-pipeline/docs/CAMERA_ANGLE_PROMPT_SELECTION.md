# EfficientNet-B0 촬영 각도 기반 배경 프롬프트 선택

## 적용 모델

기본 촬영 각도 분류기는 `models/efficientnet_best.pt`다. 학습된 EfficientNet-B0는 입력 음식 사진을 `top` 또는 `45`로 분류한다. 설정은 `configs/pipeline.yaml`의 `models.camera_angle_classifier`에 있으며, 로컬 실행·Colab 실행·네이버 이미지 보정이 모두 같은 설정과 가중치를 사용한다.

실행 보고서에는 다음 단계가 추가된다.

```json
"step_7_camera_angle_classification": {
  "status": "completed",
  "label": "top",
  "confidence": 0.93,
  "probabilities": {"45": 0.07, "top": 0.93},
  "model": "models/efficientnet_best.pt"
}
```

`confidence`가 설정값보다 낮으면 `low_confidence` 상태를 남긴다. 기본 정책은 최고 확률 클래스를 계속 사용하며, 원하면 YAML의 `fallback_on_low_confidence: true`로 변경해 `fallback_angle`을 사용하게 할 수 있다.

## 프롬프트 선택과 자연스러운 합성

| 분류 결과 | 생성 배경의 카메라 제약 | 빈 배치 영역 | 합성 정책 |
|---|---|---|---|
| `top` | 카메라가 테이블 수직 위 90도에 위치한 탑뷰. 벽·창·의자·수평선이 없는 테이블 표면 | 중앙 | 짧고 균일한 접지 그림자(세로 2px, 가로 0px)를 사용한다. 접시와 배경의 원근이 맞아 큰 접시도 자연스럽게 유지된다. |
| `45` | 카메라가 테이블을 향해 약 45도 아래로 내려다보는 사선 시점 | 중앙 하단 | 기본 접지 그림자와 얕은 심도의 실내 배경을 사용한다. 테이블 앞쪽과 뒤쪽 실내 흐림이 원본 음식·용기 시점과 맞는다. |

합성 품질의 핵심은 음식 픽셀을 다시 생성하지 않는 것이다. 파이프라인은 원본 음식·용기 RGBA 전경을 그대로 보존하고, 각도에 맞는 **음식 없는 배경만** 생성한다. 이후 제한된 색 조화·가장자리 색 번짐 제거·접지 그림자를 적용하고 OpenCLIP으로 전경 의미 보존을 확인한다.

탑뷰 원본에 눈높이 카페 배경을 합성하면 접시가 공중에 떠 보이는 문제가 생긴다. 이 기능은 그 기하학적 불일치를 막는 데 목적이 있다. 다만 입력 사진의 마스크가 접시 바깥 배경까지 포함하면 각도 분류가 맞아도 결과가 부자연스러울 수 있으므로, 보고서의 SAM·알파·RGBA 디버그 산출물을 함께 확인해야 한다.

## 네이버 채널 연결

네이버 채널에서 업로드 이미지를 보정할 때 API는 업종별 기본 프롬프트를 `background_prompt_base`로 전달한다. 파이프라인이 EfficientNet-B0 분류 결과를 바탕으로 이 프롬프트에서 눈높이 표현을 제거하고 `top` 또는 `45` 카메라 제약을 덧붙인다. 따라서 API 응답의 `vision_prompt.background_prompt`는 단순 업종 템플릿이 아니라 실제로 선택된 각도 프롬프트다.

## 테스트 확인

`notebooks/01_colab_background_replacement.ipynb`와 `notebooks/02_local_background_replacement.ipynb`는 실행 보고서에서 다음을 확인한다.

- 모델 경로가 `models/efficientnet_best.pt`인지
- 예측 라벨이 `top` 또는 `45`인지
- 보고서의 `step_7_camera_angle_classification` 상태·확률·사유

가중치가 없거나 PyTorch 추론 환경이 없으면 파이프라인은 `fallback_angle`으로 프롬프트를 만들고 보고서에 `unavailable` 상태와 원인을 기록한다.
# 각도 기반 배경 후보 선택과 자연스러운 합성

입력 JSON의 `camera_angle_manual: true`와 `camera_angle_label: top | 45`가 있으면 그 값을 사용한다. 그렇지 않으면 `models/efficientnet_best.pt`의 EfficientNet-B0가 `top` 또는 `45`를 분류한다.

- `top`: 수직 탑뷰 빈 테이블 배경, 중앙 배치, 짧고 약한 원형 접지 그림자를 사용한다.
- `45`: 45도 테이블·실내 배경, 하단 중앙 배치, 일반 접지 그림자를 사용한다.

배경 생성기는 서로 다른 시드로 기본 3장(설정으로 3~4장)을 만든다. 각 후보는 중앙 배치 영역의 여백, 원본과의 색온도 차이, 음식 탐지 결과로 점수를 얻고 가장 높은 후보만 합성에 사용한다. 후보 이미지와 선택 점수는 보고서의 `step_8_background_generation` 및 `data/intermediate/*_generated_background_candidate_*.jpg`에 남는다.

전경은 원본 픽셀을 그대로 보존하되, 접시·음식 알파의 실제 외곽을 기준으로 재배치한다. preserve 모드의 기본 목표는 탑뷰 `0.40`, 45도 `0.48`이며 허용 범위는 0.30~0.70이다. 알파 외곽에는 `safe_padding_px: 28`을 유지하고, 제한된 밝기 조화와 가장자리 색 번짐 제거를 수행한다. 마지막으로 OpenCLIP 전경 비교, 생성 배경 음식 탐지, 각도·배치·크기 기하 검증을 통과해야 결과 이미지를 저장한다.

## 탑뷰 후보의 강제 통과 조건

`top` 입력은 카페 실내·벽·창문·의자 배경을 생성 프롬프트에서 제외하고, 프레임 전체를 채우는 단일 탁자 표면만 요청한다. 후보 점수는 유효성 검사를 통과한 후보끼리만 비교한다.

- 음식 특화 YOLO와 COCO YOLO가 음식·접시·컵·식기 중 하나를 검출하면 후보를 즉시 폐기한다.
- 탑뷰 후보에서 강한 수평 경계가 검출되면 벽·테이블 경계 또는 수평선으로 판단해 폐기한다.
- 기본 3개의 유효 후보를 얻을 때까지 다른 시드로 최대 12회 생성한다.
- 유효 후보가 하나도 없으면 `background_candidate_generation_failed`로 종료하며, 부자연스러운 합성 JPG를 저장하지 않는다.

탑뷰 합성의 그림자는 이동된 실루엣 전체가 아니라 접시 외곽 4px을 확장해 만든 얇은 고리형 접지 그림자다. blur 9px, opacity 0.10을 사용해 접시가 테이블 표면에 닿아 보이도록 한다.
