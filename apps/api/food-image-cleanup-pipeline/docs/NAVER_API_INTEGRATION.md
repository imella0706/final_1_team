# 네이버 블로그 이미지 보정 API 연동

## 목적

`final_1_team`의 네이버 블로그 채널은 사용자가 올린 음식 사진을 광고 문구와 함께 반환한다. 이 연동은 사진을 다른 외부 프로젝트로 전달하지 않고, 같은 저장소의 `apps/api/food-image-cleanup-pipeline`을 실행해 음식·용기 전경은 유지하고 광고용 빈 배경만 생성·합성한다.

## 처리 흐름

```text
네이버 블로그 선택 + 음식 사진 업로드
→ API가 업로드 사진을 파이프라인 작업 파일로 저장
→ GroundingDINO·학습한 YOLO11n으로 음식·접시 후보 탐지
→ SAM 2.1 Small 기본 마스크와 HQ-SAM patch_missing 경계 보완
→ 접시 보존 마스크와 SAM 알파로 원본 접시 외곽 보존
→ 안전 제거·분리 전경 정리·용기 블러·접시 림 복원
→ 업종별 빈 배경 프롬프트로 Sana 또는 FLUX 배경 생성
→ 그림자·색상 조화·OpenCLIP 차단 검증
→ 합성 JPG를 네이버 광고 문구 응답의 image로 반환
```

모델 준비 전이거나 처리 중 오류가 나면 광고 문구 API 전체를 실패시키지 않고 원본 사진을 반환한다. 이때 응답의 `vision_prompt.image_generation`과 `vision_prompt.image_enhancement_reason`에서 원인을 확인한다.

자동 실행 조건은 채널 값이 `naver_blog`이고 `blog_images`에 사진이 한 장 이상 있으며 아래 환경 변수 스위치가 `true`인 경우다. 현재 API는 여러 사진 중 첫 번째 사진만 이미지 보정 파이프라인에 전달한다. 사진이 없으면 파이프라인을 실행하지 않고 업로드 이미지 응답 경로를 사용한다.

음식 탐지 실패 또는 OpenCLIP 검증 실패 시에도 동일하게 원본 사진을 반환한다. 파이프라인은 광고 합성 JPG를 저장하지 않고 `food_detection_failed` 또는 `semantic_validation_failed` 보고서와 디버그 산출물만 남긴다.

## 음식 탐지 모델

네이버 채널에서 이미지 보정이 활성화되면 같은 파이프라인 설정을 사용한다. 먼저 GroundingDINO가 `plate`, `dish`, `bowl`, `food`, `meal` 등의 프롬프트로 후보 상자를 제시하고, 기본 탐지 프로필 `food_specialized`의 학습한 음식 전용 YOLO11n 가중치 `food-image-cleanup-pipeline/models/best.pt`가 음식 위치를 보완한다. 실행 보고서의 `step_2_yolo_detection.model`과 `step_2_yolo_detection.profile`이 각각 `models/best.pt`, `food_specialized`인지 확인하면 실제 적용 여부를 알 수 있다.

비교 또는 장애 진단을 위해서만 `configs/pipeline.yaml`의 `models.foreground_detector.active_profile`을 `coco_yolo11n`으로 바꿔 기본 COCO YOLO11n을 선택할 수 있다. 운영 기본값은 학습 모델을 사용하는 `food_specialized`다.

## 업종별 배경 프롬프트

| 입력 JSON 업종 | 내부 업종 | 배경 템플릿 |
| --- | --- | --- |
| `카페`, `cafe` | `cafe` | 프리미엄 모던 한국 카페, 밝은 창가와 월넛 테이블 |
| `베이커리`, `bakery` | `bakery` | 카페형 프리미엄 베이커리 광고 배경 |
| `디저트`, `dessert` | `dessert` | 카페형 프리미엄 디저트 광고 배경 |
| `음식점`, `restaurant` | `restaurant` | 자연광과 내추럴 우드 테이블의 한국 음식점 |
| `주점`, `pub` | `pub` | 어두운 목재와 앰버 조명의 한국 주점 |

각 템플릿에는 `no food`, `no plate`, `no people`, `no text`, `no logo`, `no watermark` 조건이 들어간다. 배경 생성 모델이 음식이나 접시를 새로 그려 원본 음식과 충돌하는 것을 줄이기 위한 조건이다.

## 서버 설정

`apps/api/.env`에 다음을 설정한다. 기본값은 안전을 위해 비활성화되어 있다.

```env
BRANDMATE_NAVER_IMAGE_ENHANCEMENT_ENABLED=true
BRANDMATE_NAVER_IMAGE_CLEANUP_ROOT=food-image-cleanup-pipeline
BRANDMATE_NAVER_IMAGE_CLEANUP_PYTHON=C:\경로\파이프라인전용가상환경\Scripts\python.exe
BRANDMATE_NAVER_IMAGE_CLEANUP_TIMEOUT_SECONDS=600
```

`BRANDMATE_NAVER_IMAGE_CLEANUP_PYTHON`은 API와 파이프라인을 서로 다른 가상환경에서 실행할 때 설정한다. API Python에 파이프라인의 모든 의존성을 설치했다면 비워 둘 수 있다.

환경 변수를 바꾼 뒤에는 API 프로세스를 재시작해야 한다. `BRANDMATE_NAVER_IMAGE_ENHANCEMENT_ENABLED=false`이거나 변수가 없으면 기본값이 `false`이므로 파이프라인은 실행되지 않고 원본 이미지 fallback이 사용된다.

파이프라인 전용 환경은 `food-image-cleanup-pipeline/requirements-local.txt`를 설치하고, `scripts/download_models.py`로 필요한 모델을 받는다. GPU와 모델 파일이 준비되지 않은 상태에서 활성화하면 API는 원본 사진을 반환하며 상태를 `background_replacement_failed_fallback`으로 기록한다.

## 확인 방법

1. API 서버를 재시작한다.
2. 네이버 블로그 채널과 음식 사진 한 장으로 `/api/v1/ad-content/generate`를 호출한다.
3. 응답의 `vision_prompt.image_generation`이 `background_replacement_completed`인지 확인한다.
4. `image.media_type`이 `image/jpeg`, `image.model`이 `food-image-cleanup-pipeline`인지 확인한다.

## 각도 기반 후보 배경 선택

네이버 채널은 업종별 기본 프롬프트를 `background_prompt_base`로 전달한다. 파이프라인은 업로드 사진의 EfficientNet-B0 분류 결과 또는 JSON 수동 각도를 바탕으로 해당 프롬프트에 `top` 또는 `45` 카메라 제약을 추가한다. 그러므로 네이버 API가 임의의 눈높이 배경을 고정해서 사용하는 구조가 아니다.

생성기는 음식·접시·컵이 없는 배경 후보를 기본 3장 생성한다. 중앙 여백, 색온도, YOLO 음식 미검출 여부로 후보를 고르고, 원본 음식·접시는 캔버스 너비의 55~70%로 재배치해 합성한다. 탑뷰는 중앙·약한 원형 그림자, 45도는 하단 중앙·일반 접지 그림자를 사용한다.

API 응답에서 이미지가 원본으로 돌아오면 파이프라인 보고서에서 다음 상태를 우선 확인한다.

- `background_food_detected`: 생성 배경에 음식이 남아 있음
- `geometry_validation_failed`: 각도·위치·전경 크기 정책 실패
- `semantic_validation_failed`: OpenCLIP 전경 의미 보존 실패
