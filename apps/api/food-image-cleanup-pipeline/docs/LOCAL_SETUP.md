# 로컬 실행 안내

이 폴더는 네이버 블로그 음식 사진의 전경 보존·배경 생성·합성 전용 파이프라인이다. 운영 모드에서는 음식 탐지와 OpenCLIP 검증을 통과한 결과만 광고 합성 이미지로 저장한다.

## 기본 환경

```powershell
cd C:\dev\final_1_team\apps\api\food-image-cleanup-pipeline
python -m pip install -r requirements-local.txt
python -m scripts.download_models --models yolo sam2 big-lama openclip sana grounding-dino hq-sam
python -m scripts.run_background_replacement --input data/input/example.jpg --metadata data/input/example_metadata.json --enable-background-generator
```

로컬 전체 검증은 `notebooks/02_local_background_replacement.ipynb`를 사용한다. 노트북은 실행 보고서와 SAM 구조 마스크, 알파 마스크, RGBA 전경, 최종 또는 거부된 합성 이미지를 표시한다.

## 탐지 모델 선택

`configs/pipeline.yaml`의 `models.foreground_detector.active_profile`이 기본 탐지기를 결정한다.

| 값 | 가중치 | 용도 |
| --- | --- | --- |
| `food_specialized` | `models/best.pt` | 학습한 음식 전용 모델. 기본값이다. |
| `coco_yolo11n` | `models/yolo11n.pt` | COCO 사전학습 기본 YOLO11n. 비교 또는 대체 실행용이다. |

명령 한 번에만 전환하려면 `--detector-profile coco_yolo11n` 또는 `--detector-profile food_specialized`를 사용한다. 실행 보고서의 `step_2_yolo_detection.profile`에서 실제 선택된 프로필을 확인할 수 있다.

## 안전 종료 상태

- `food_detection_failed`: GroundingDINO와 YOLO11n이 모두 음식·용기를 찾지 못함. 광고 JPG를 저장하지 않는다.
- `semantic_validation_failed`: OpenCLIP 유사도 0.8 미만. 현재 코드는 재합성하지 않고 광고 JPG 저장을 거부한다.
- `completed`: 최종 합성 JPG를 저장했다.

중앙 사각형 대체는 `--diagnostic-center-fallback` 옵션을 준 연결 테스트에서만 허용한다. 운영 요청에는 사용하지 않는다.

## 디버그 산출물 확인

실행 보고서 `data/reports/<입력명>_background_replacement_report.json`의 `debug_artifacts`를 확인한다. 원본 SAM과 안정화 SAM 마스크를 먼저 비교한다. 안정화 마스크는 내부 투명 구멍과 작은 잡음을 제거한 합성용 마스크다. 이어서 접시 보존 마스크, SAM 기반 알파, RGBA 전경 미리보기, `semantic_*_reference`·`semantic_*_candidate` 전경 비교 이미지를 확인한다. OpenCLIP 검증에 실패한 경우에는 최종 합성 대신 거부된 합성 이미지가 기록된다.

최신 마스크·림 문제는 다음 순서로 확인한다.

1. `step_2c_mask_quality`: 음식과 접시 마스크를 각각 통과했는지 확인한다.
2. `step_2d_food_support_recovery`: `kept_components`, `recovered_pixels`, `applied`와 `*_food_support_mask.png`를 확인한다.
3. `step_5d_plate_edge_repair`: `adaptive_rim_observation`의 신뢰도와 브리지·알파 확장 픽셀을 확인한다.

HoughLinesP의 OpenCV 반환 배열은 코드에서 `(N, 4)`로 정규화하므로 Colab과 로컬의 `(N, 1, 4)`/`(N, 4)` 차이는 마스크 기준을 바꾸지 않는다.

## 결과 품질 점검

로컬 실행 후 보고서에서 다음 순서로 확인한다.

1. `step_7_camera_angle_classification`: EfficientNet-B0가 `top` 또는 `45`를 정상 분류했는지 확인한다. 필요하면 JSON 수동 지정값을 사용한다.
2. `step_8_background_generation`: 3~4개 후보 중 선택된 후보가 `food_detections: 0`인지와 중앙 여백·색온도 점수를 확인한다.
3. `step_9_foreground_placement`: preserve 모드의 유효 범위는 0.30~0.70이고 기본 목표는 탑뷰 `0.40`, 45도 `0.48`이다. 탑뷰는 `center`, 45도는 `center_lower`인지 확인한다.
4. `step_14_background_geometry_validation`: 배경 음식·기하 검증이 통과했는지 확인한다.

추가 종료 상태는 다음과 같다.

- `background_food_detected`: 선택된 생성 배경에서 음식이 검출되어 광고 결과를 저장하지 않았다.
- `geometry_validation_failed`: 전경 크기 또는 배치가 각도 정책을 벗어나 광고 결과를 저장하지 않았다.

`background_candidate_generation_failed`는 생성된 후보가 음식·식기·시점·테이블 평면 조건을 모두 만족하지 못한 상태다. 이 경우 시드를 바꿔 최대 횟수까지 재생성한 뒤에도 유효 후보가 없었음을 뜻하며, 프롬프트·생성 모델·GPU 환경을 점검해야 한다.
