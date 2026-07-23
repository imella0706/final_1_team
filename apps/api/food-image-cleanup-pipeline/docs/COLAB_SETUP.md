# 코랩 실행 안내

`notebooks/01_colab_background_replacement.ipynb`를 GPU 런타임에서 위에서 아래 순서로 실행한다. 노트북은 전역 패키지를 바꾸지 않고 `/content/food-image-cleanup-packages`에 파이프라인 의존성만 설치한다.

기본 코랩 검증은 GroundingDINO Tiny, 학습한 음식 전용 YOLO11n, SAM 2.1 Small, Big-LaMa, EfficientNet-B0, Sana 1.6B, OpenCLIP을 사용한다. GroundingDINO 가중치는 `models/grounding-dino`에 캐시해 다음 실행에서 재사용한다. BiRefNet HR은 현재 기본 파이프라인에서 사용하지 않는다. 기본 배경 생성기는 접근 토큰이 필요 없는 `sana-1.6b`이며, FLUX.1 Schnell은 선택적으로 사용할 수 있다.

## 학습한 음식 탐지 모델 사용

배경 교체 테스트의 기본 탐지기는 학습한 음식 전용 YOLO11n 가중치 `models/best.pt`다. `scripts/download_models.py`는 공용 기본 모델만 내려받으므로, 이 학습 가중치는 Google Drive의 프로젝트 폴더 `models/best.pt`에 직접 둬야 한다.

`notebooks/01_colab_background_replacement.ipynb`는 실행 전 파일 존재를 확인하고, 결과 보고서의 `step_2_yolo_detection`에서 다음을 검증한다.

```json
{
  "model": "models/best.pt",
  "profile": "food_specialized"
}
```

기본 COCO 모델과 비교하려면 노트북의 `DETECTOR_PROFILE` 값을 `coco_yolo11n`으로 바꾼다. 이 경우 `models/yolo11n.pt`와 COCO 클래스 목록을 사용한다.

## 운영과 동일한 안전 정책

- YOLO11n이 음식·용기를 찾지 못하면 중앙 사각형으로 광고 이미지를 만들지 않는다.
- OpenCLIP 유사도 0.8 미만이면 SAM 기반 알파와 접시 보존 마스크로 재합성하며, 계속 실패하면 광고 JPG를 저장하지 않는다.
- 재시도도 실패하면 최종 광고 JPG를 저장하지 않고 실패 보고서와 디버그 산출물만 남긴다.

노트북 마지막 셀에서 실행 보고서의 `debug_artifacts`를 통해 원본·안정화 SAM 구조 마스크, 접시 보존 마스크, SAM 기반 알파 마스크, RGBA 전경, OpenCLIP 전경 비교 이미지, 최종 또는 거부된 합성 이미지를 확인한다.

## 각도 분류와 후보 선택 확인

노트북은 `models/efficientnet_best.pt`가 있는지 확인하고, 실행 보고서의 `step_7_camera_angle_classification`에서 `top` 또는 `45` 분류 결과·확률을 표시한다. JSON에 수동 각도를 지정하려면 아래처럼 작성한다.

```json
{
  "camera_angle_manual": true,
  "camera_angle_label": "top"
}
```

`step_8_background_generation`에는 기본 3개 후보의 시드·중앙 여백 점수·색온도 점수·배경 음식 탐지 결과·선택 후보 번호가 기록된다. 후보 파일은 `data/intermediate/*_generated_background_candidate_*.jpg`에 저장된다. 마지막으로 `step_9_foreground_placement`의 전경 너비 비율이 0.55~0.70인지, `step_14_background_geometry_validation`이 통과했는지 확인한다.
