# 코랩 실행 안내

`notebooks/01_colab_background_replacement.ipynb`를 GPU 런타임에서 위에서 아래 순서로 실행한다. 노트북은 전역 패키지를 바꾸지 않고 `/content/food-image-cleanup-packages`에 파이프라인 의존성만 설치한다.

기본 코랩 검증은 GroundingDINO Tiny, 학습한 음식 전용 YOLO11n, SAM 2.1 Small, HQ-SAM, Big-LaMa, EfficientNet-B0, Sana 1.6B, OpenCLIP을 사용한다. GroundingDINO와 HQ-SAM은 각각 `models/grounding-dino`, `models/hq-sam`에 저장해 다음 실행에서 재사용한다. 노트북의 다운로드 셀은 호환성을 위해 BiRefNet도 내려받지만, 현재 CLI는 매팅을 강제로 비활성화하므로 추론에는 사용하지 않는다. 기본 배경 생성기는 `sana-1.6b`이며 FLUX.1 Schnell은 선택 대안이다.

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
- OpenCLIP 유사도 0.8 미만이면 현재 코드는 재합성하지 않고 광고 JPG를 저장하지 않는다.
- 검증 실패 시 실패 보고서와 디버그 산출물만 남긴다.

노트북 마지막 셀에서 실행 보고서의 `debug_artifacts`를 통해 원본·안정화 SAM 구조 마스크, 접시 보존 마스크, SAM 기반 알파 마스크, RGBA 전경, OpenCLIP 전경 비교 이미지, 최종 또는 거부된 합성 이미지를 확인한다.

최신 코드에서는 `food_support_mask`도 저장한다. `step_2c_mask_quality`, `step_2d_food_support_recovery`, `step_5d_plate_edge_repair`를 함께 확인해야 음식·접시 품질, 꼬치형 지지 구조 채택, 적응형 림 관찰과 브리지 적용 여부를 구분할 수 있다. 음식 지지 구조를 최상단 RGB 레이어로 다시 합성하는 단계는 취소됐으므로 `step_5e_food_support_layer`는 현재 보고서에 존재하지 않는다.

OpenCV 빌드에 따라 HoughLinesP가 `(N, 1, 4)` 또는 `(N, 4)` 배열을 반환할 수 있다. 현재 코드는 이를 `(N, 4)`로 정규화하므로 과거의 `numpy.int32 object is not iterable` 오류를 피하며, 이 호환 처리는 검출 임계값이나 모델 출력을 바꾸지 않는다.

## 노트북의 모드 덮어쓰기

`configs/pipeline.yaml`의 기본 모드는 `preserve_original_plate`이지만, 현재 `01_colab_background_replacement.ipynb` 위젯 기본값은 `generated_plate`다. 노트북은 선택값을 메타데이터의 `composition_mode`로 전달하므로 YAML보다 위젯 선택이 우선한다. 또한 generated 모드 테스트에서는 `require_food_visible_mask: false`를 전달해 SAM 음식 마스크 fallback을 허용한다. 운영과 같은 엄격한 조건을 검증하려면 위젯에서 preserve 모드를 선택하거나 메타데이터의 해당 값을 직접 확인해야 한다.

## 각도 분류와 후보 선택 확인

노트북은 `models/efficientnet_best.pt`가 있는지 확인하고, 실행 보고서의 `step_7_camera_angle_classification`에서 `top` 또는 `45` 분류 결과·확률을 표시한다. JSON에 수동 각도를 지정하려면 아래처럼 작성한다.

```json
{
  "camera_angle_manual": true,
  "camera_angle_label": "top"
}
```

`step_8_background_generation`에는 기본 3개 후보의 시드·중앙 여백 점수·색온도 점수·배경 음식 탐지 결과·선택 후보 번호가 기록된다. 후보 파일은 `data/intermediate/*_generated_background_candidate_*.jpg`에 저장된다. 마지막으로 `step_9_foreground_placement`의 기본 목표가 탑뷰 `0.40`, 45도 `0.48`인지 확인한다. preserve 모드의 허용 범위는 0.30~0.70이며, `step_14_background_geometry_validation`도 통과해야 한다.
