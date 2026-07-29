# Food Image Cleanup Pipeline

네이버 블로그 채널에 업로드된 음식 사진에서 원본 음식과 접시를 최대한 보존하고, 불필요한 주변 물체를 제거한 뒤 업종·분위기·촬영 각도에 맞는 광고 배경을 생성해 합성하는 파이프라인이다.

## 현재 기본 동작

- 기본 합성 모드는 `preserve_original_plate`다.
- GroundingDINO가 음식·접시 후보를 먼저 찾고 음식 전용 YOLO11n이 놓친 쪽만 보완한다.
- SAM 2.1 Small이 기본 마스크를 만들고 HQ-SAM은 `patch_missing` 방식으로 작은 결손만 보완한다.
- `PlateMaskService`가 용기 윤곽을 `ellipse`, `quadrilateral`, `irregular`로 판정한다. 형태 신뢰도가 낮으면 임의의 접시 윤곽을 만들지 않고 원본 연결 영역을 유지한다.
- 음식과 접시 마스크는 별도의 품질 기준으로 검사한다. `generated_plate`는 음식 전용 마스크가 기준을 통과하지 못하면 중단한다.
- preserve 모드에서는 음식과 연결된 가는 꼬치 후보를 GroundingDINO·Canny·Hough 선분과 SAM 증거로 검사해 `food_support_mask`로 보호한다.
- `plate_mask`에서 만든 `plate_alpha`를 최종 알파에 다시 합쳐 접시 내부 구멍을 방지한다.
- 수저·컵·그릇 후보는 보호 영역을 제외한 `safe_removal_mask`에서만 Big-LaMA로 제거한다.
- 접시나 음식과 분리된 전경 컴포넌트는 후처리로 알파에서 제거한다.
- preserve 모드에서는 용기 블러와 접시 림 복원을 적용한다. 림 복원은 원본 RGB의 실제 림 색·윤곽 신뢰도가 기준을 통과할 때만 합성 브리지를 허용한다.
- EfficientNet-B0가 `top` 또는 `45`를 판별하고 SANA 1.6B가 기본 배경 후보를 만든다.
- OpenCLIP·배경 객체·기하·화질 검증을 통과한 결과만 JPG로 저장한다.

자세한 최신 실행 순서는 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)를 참고한다.

## 네이버 채널 자동 실행과 ON/OFF

광고 콘텐츠 API에서 다음 조건을 모두 만족하면 파이프라인이 자동 실행된다.

1. 채널 값이 `naver_blog`다.
2. `blog_images`에 업로드 사진이 한 장 이상 있다.
3. API의 `.env`에서 이미지 보정 스위치가 켜져 있다.
4. 파이프라인 전용 Python과 필요한 모델이 준비되어 있다.

현재 API는 업로드된 여러 사진 중 첫 번째 사진만 보정한다. 기능이 꺼져 있거나 모델 실행이 실패하면 광고 문구 요청 전체를 실패시키지 않고 업로드 원본 이미지로 fallback한다.

`apps/api/.env`에서 설정한다.

```dotenv
BRANDMATE_NAVER_IMAGE_ENHANCEMENT_ENABLED=true
BRANDMATE_NAVER_IMAGE_CLEANUP_ROOT=food-image-cleanup-pipeline
BRANDMATE_NAVER_IMAGE_CLEANUP_PYTHON=C:\path\to\pipeline\.venv\Scripts\python.exe
BRANDMATE_NAVER_IMAGE_CLEANUP_TIMEOUT_SECONDS=600
```

| 설정 | 역할 |
| --- | --- |
| `BRANDMATE_NAVER_IMAGE_ENHANCEMENT_ENABLED` | 전체 네이버 이미지 보정 기능 ON/OFF. 기본값은 `false`다. |
| `BRANDMATE_NAVER_IMAGE_CLEANUP_ROOT` | `apps/api` 기준 파이프라인 경로 또는 절대 경로다. |
| `BRANDMATE_NAVER_IMAGE_CLEANUP_PYTHON` | 파이프라인 의존성과 모델 런타임이 설치된 Python이다. 비우면 API의 Python을 사용한다. |
| `BRANDMATE_NAVER_IMAGE_CLEANUP_TIMEOUT_SECONDS` | 한 장 처리 제한 시간이다. 기본값은 600초다. |

`.env` 변경 후에는 API 서버를 재시작해야 한다.

### 파이프라인 내부 기능 ON/OFF

모델과 후처리 단계는 [configs/pipeline.yaml](configs/pipeline.yaml)의 `enabled` 값으로 제어한다.

```yaml
models:
  hq_sam:
    enabled: true
  plate_segmenter:
    enabled: false
  food_support_recovery:
    enabled: true
    preserve_mode_only: true
    allow_geometry_only: false
  plate_mask:
    enabled: true
  inpainter:
    enabled: true
  preserved_container_blur:
    enabled: true
  foreground_cleanup:
    enabled: true
  plate_edge_repair:
    enabled: true
  background_generator:
    enabled: true
  semantic_validator:
    enabled: true
```

`preserved_container_blur`와 `plate_edge_repair`는 `preserve_original_plate`에서만 실행된다. `plate_segmenter`는 현재 기본값이 꺼져 있다. `generated_plate`에서 `require_food_visible_mask: true`를 유지하려면 활성화된 접시 분할 모델이 유효한 `food_visible` 마스크를 만들어야 한다.

현재 후보 가중치는 `models/yolo_seg_best.pt`에 있지만 YAML의 기본 가중치 경로는 `models/yolo11n_plate_seg.pt`다. 접시 분할 모델을 켜려면 성능 검증 후 `weights`를 실제 파일 경로로 바꾸고 `enabled: true`로 설정해야 한다.

`food_support_recovery`는 얇은 선을 모두 복구하지 않는다. 접시 경계를 통과하고 음식과 연결되며 SAM/HQ-SAM 후보 증거가 있는 구조만 채택한다. `plate_edge_repair.adaptive_rim_observation.enabled: true`와 `quality_gate_enabled: true`는 실제 림 관찰 신뢰도가 낮을 때 합성 림과 알파 확장을 차단한다.

## 설치

파이프라인 루트에서 실행한다.

```powershell
python -m pip install -r requirements-local.txt
python -m scripts.download_models --models yolo sam2 big-lama openclip sana grounding-dino hq-sam
```

직접 학습한 다음 가중치는 다운로드 스크립트가 만들지 않으므로 별도로 준비해야 한다.

- 음식 전용 탐지기: `models/best.pt`
- 촬영 각도 분류기: `models/efficientnet_best.pt`
- 선택적 접시 분할 모델: 설정의 `models.plate_segmenter.weights`

## 로컬 CLI 실행

```powershell
python -m scripts.run_background_replacement `
  --input data/input/example.jpg `
  --metadata data/input/example_metadata.json `
  --enable-background-generator
```

메타데이터 예시:

```json
{
  "business_type": "cafe",
  "desired_mood": "cozy and warm",
  "composition_mode": "preserve_original_plate",
  "camera_angle_manual": false
}
```

주요 옵션:

```text
--business-type
--desired-mood
--composition-mode preserve_original_plate|generated_plate
--detector-profile food_specialized|coco_yolo11n
--allow-sam-food-mask-for-generated-plate
--enable-hq-sam
--hq-sam-model-id
--hq-sam-selection-mode
--diagnostic-center-fallback
```

`--diagnostic-center-fallback`은 탐지 연결 진단용이며 운영 결과 생성에는 사용하지 않는다. 현재 CLI의 `--enable-matting`은 호환성을 위해 남아 있지만 코드가 BiRefNet을 강제로 비활성화한다.

## 합성 모드

### `preserve_original_plate`

원본 음식과 원본 접시를 함께 보존하는 기본 모드다. `plate_alpha`를 최종 단계에 다시 합쳐 접시 내부 구멍을 막고, 용기 블러와 접시 림 복원을 적용한다.

### `generated_plate`

원본 접시를 제외하고 음식만 생성 배경의 빈 접시 위에 배치하는 실험 모드다. 기본 정책에서는 학습된 `food_visible` 마스크가 없으면 결과를 거부한다. CLI의 `--allow-sam-food-mask-for-generated-plate`는 테스트 편의를 위한 완화 옵션이다.

## 출력과 보고서

| 종류 | 기본 경로 |
| --- | --- |
| 최종 광고 이미지 | `data/output/<입력명>_background_replaced.jpg` |
| RGBA 전경 | `data/intermediate/<입력명>_foreground_rgba.png` |
| 마스크 | `data/masks/` |
| 실행 보고서 | `data/reports/<입력명>_background_replacement_report.json` |
| Colab 실험 보관본 | `data/experiments/background_replacement/<실행시각>/` |

성공 여부는 보고서 최상위 `status`로 확인한다. `completed`일 때만 `output_path`가 생성된다. 주요 실패 상태는 `food_detection_failed`, `food_visible_segmentation_required`, `plate_preservation_failed`, `background_candidate_generation_failed`, `semantic_validation_failed`, `geometry_validation_failed`다.

최근 마스크·림 일반화 작업은 다음 항목으로 확인한다.

- `step_2c_mask_quality`: 음식과 접시 마스크의 독립 품질 결과
- `step_2d_food_support_recovery`: 음식 연결 지지 구조의 채택 수와 복구 픽셀
- `step_5d_plate_edge_repair`: 적응형 림 관찰 신뢰도, 실제 림 보존과 합성 브리지 적용 여부
- `data/masks/<입력명>_food_support_mask.png`: 실제로 보호된 얇은 지지 구조

음식 지지 구조를 모든 후처리 뒤 최상단 RGB 레이어로 다시 그리는 실험은 취소되었다. 현재 코드에는 `step_5e_food_support_layer`가 없으며, `step_2d_food_support_recovery`의 보수적인 마스크 보호만 남아 있다.

네이버 API 응답에서는 다음도 확인한다.

- 성공: `vision_prompt.image_generation == "background_replacement_completed"`
- 기능 미설정: `background_replacement_not_configured`
- 실행 실패 후 원본 반환: `background_replacement_failed_fallback`
- 성공 모델명: `image.model == "food-image-cleanup-pipeline"`

## Colab

[notebooks/01_colab_background_replacement.ipynb](notebooks/01_colab_background_replacement.ipynb)를 위에서 아래로 실행한다. 현재 노트북 위젯 기본값은 `generated_plate`이며 메타데이터가 YAML 기본 모드를 덮어쓴다. 운영 기본과 같은 결과를 확인하려면 위젯에서 `preserve_original_plate`를 선택한다.

## 문서 안내

- [프로젝트 개요](docs/PROJECT_OVERVIEW.md)
- [최신 구조와 실행 흐름](docs/ARCHITECTURE.md)
- [네이버 API 연결](docs/NAVER_API_INTEGRATION.md)
- [로컬 실행](docs/LOCAL_SETUP.md)
- [Colab 실행](docs/COLAB_SETUP.md)
- [generated_plate 모드](docs/GENERATED_PLATE_COMPOSITION.md)
- [접시 분할 학습](docs/PLATE_SEGMENTATION_TRAINING.md)
- [카메라 각도 선택](docs/CAMERA_ANGLE_PROMPT_SELECTION.md)

`image_cleanup_model_data_pipeline_0935.md`와 `image_cleanup_problem_solving_history_0935.md`는 파일명과 문서 머리말에 적힌 시점까지의 설계·문제 해결 기록이다. 최신 운영 상태는 이 README, `ARCHITECTURE.md`, `configs/pipeline.yaml`, 실제 실행 보고서를 우선한다.
