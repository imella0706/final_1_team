# 네이버 블로그 음식 사진 보정 파이프라인

## 1. 문서 목적

이 문서는 `final_1_team`의 광고 문구 생성 API에서 네이버 블로그 채널을 선택했을 때, 사용자가 업로드한 음식 사진을 어떻게 보정하는지 설명한다. 보정의 목표는 원본 음식과 용기의 형태를 유지하면서 기존 배경을 제거하고, 업종에 맞는 광고용 빈 배경을 생성해 자연스럽게 합성하는 것이다.

이 기능은 외부 프로젝트나 원격 API에 사진을 전달하지 않는다. 동일한 저장소에 포함된 `apps/api/food-image-cleanup-pipeline`을 로컬 subprocess로 실행한다.

## 2. 처리 경로

```text
웹 화면
  → POST /api/v1/ad-content/generate
  → app/extensions/ad_content/router.py
  → naver_image_enhancement.py
  → apps/api/food-image-cleanup-pipeline/scripts/run_background_replacement.py
  → BackgroundReplacementPipeline
  → 합성 JPG를 API image 응답으로 반환
```

네이버 블로그가 아닌 채널은 기존 광고 이미지 생성 경로를 유지한다. 네이버 블로그 채널에서는 `blog_images`의 첫 번째 이미지를 음식 사진으로 사용한다.

## 3. 업종별 배경 프롬프트

사용자 JSON의 `copy.business_type` 값을 [naver_background_prompts.py](../app/extensions/ad_content/naver_background_prompts.py)에서 정규화한다.

| 입력값 | 내부 업종 | 생성 배경 |
| --- | --- | --- |
| `카페`, `cafe` | `cafe` | 밝은 창가, 월넛 테이블, 모던 한국 카페 |
| `베이커리`, `bakery` | `bakery` | 카페형 프리미엄 베이커리 광고 배경 |
| `디저트`, `dessert` | `dessert` | 카페형 프리미엄 디저트 광고 배경 |
| `음식점`, `restaurant` | `restaurant` | 자연광, 내추럴 우드 테이블, 모던 한국 음식점 |
| `주점`, `pub` | `pub` | 짙은 목재, 앰버 조명, 저녁 분위기의 한국 주점 |

모든 프롬프트에는 음식, 접시, 컵, 사람, 손, 글자, 로고, 워터마크가 없는 빈 배경이라는 제약을 넣는다. 생성 모델이 원본 음식과 별개의 음식을 그리는 문제를 줄이기 위함이다.

## 4. 전체 이미지 보정 단계

```text
1. 입력 검사
2. YOLO11n 음식·용기 탐지
3. SAM 2.1 Tiny 구조 마스크 생성
4. BiRefNet HR 알파 매트 정제
5. Big-LaMa로 전경 밖 작은 이물질 제한 제거
6. RGBA 음식·용기 전경 추출
7. 업종별 빈 배경 프롬프트 선택
8. Sana 1.6B 또는 FLUX.1 Schnell 배경 생성
9. 원래 캔버스 기준 전경 배치
10. 접지 그림자 추가
11. 가장자리 색 번짐 제거와 제한적 색상 조화
12. OpenCLIP 의미 유사도 검증
13. 결과 JPG와 처리 보고서 저장
```

전경의 음식 픽셀을 생성 모델이 다시 그리도록 하지 않는 것이 핵심 원칙이다. 생성 모델은 배경만 만들고, 원본 음식·용기 전경은 알파 합성으로 올린다.

## 5. 사용 모델과 선택 이유

| 모델 | 역할 | 선택 이유 |
| --- | --- | --- |
| YOLO11n | 음식·용기·식기 후보 탐지 | 가볍고 빠르며 SAM에 필요한 사각형 프롬프트를 제공한다. COCO 클래스 한계로 탐지 실패 가능성이 있다. |
| SAM 2.1 Tiny | 음식·용기 구조 마스크 | 작은 모델로도 객체의 대략적인 외곽을 분리하며 후속 매팅의 기준을 제공한다. |
| BiRefNet HR | 연속 알파 매트 | 접시 곡선, 얇은 장식, 반투명 경계처럼 SAM 이진 마스크만으로 거친 부분을 자연스럽게 정제한다. |
| Big-LaMa | 전경 밖 이물질 제거 | 포크·나이프·스푼 같은 제거 대상이 전경 보호 마스크 밖에 있을 때만 제한적으로 복원한다. 음식 자체는 제거하지 않는다. |
| Sana 1.6B | 기본 빈 배경 생성 | 공개 모델로 접근성이 높고, 코랩·로컬 GPU에서 FLUX 대안으로 사용할 수 있다. |
| FLUX.1 Schnell | 선택 빈 배경 생성 | 적은 단계로 광고용 포토리얼 배경을 빠르게 만들 수 있다. 모델 접근 권한 또는 토큰이 필요할 수 있다. |
| OpenCLIP ViT-B-32 | 전경 의미 보존 검증 | 합성 뒤 음식·용기 마스크 영역이 원본과 의미상 지나치게 달라지지 않았는지 점검한다. |

## 6. API 실행 조건

기능은 모델 의존성과 GPU 사용량이 크므로 기본값에서는 비활성화한다. API의 `.env`에 아래 값을 설정하면 네이버 채널 요청에서 보정이 실행된다.

```env
BRANDMATE_NAVER_IMAGE_ENHANCEMENT_ENABLED=true
BRANDMATE_NAVER_IMAGE_CLEANUP_ROOT=food-image-cleanup-pipeline
BRANDMATE_NAVER_IMAGE_CLEANUP_PYTHON=C:\경로\파이프라인전용가상환경\Scripts\python.exe
BRANDMATE_NAVER_IMAGE_CLEANUP_TIMEOUT_SECONDS=600
```

`BRANDMATE_NAVER_IMAGE_CLEANUP_PYTHON`은 API와 파이프라인이 서로 다른 가상환경을 사용할 때 필요하다. 해당 Python 환경에는 `food-image-cleanup-pipeline/requirements-local.txt`의 의존성과 각 모델 파일이 준비돼야 한다.

파이프라인은 `food-image-cleanup-pipeline/models/efficientnet_best.pt`의 EfficientNet-B0를 기본 촬영 각도 분류기로 사용한다. 업로드 음식 사진을 `top` 또는 `45`로 판단한 뒤, 업종별 배경 프롬프트에 해당 시점의 카메라 제약을 적용한다. 따라서 탑뷰 접시에는 수직 탑뷰 빈 테이블, 45도 음식 사진에는 사선 테이블 배경이 생성된다. 실행 보고서의 `step_7_camera_angle_classification`에서 모델 경로·라벨·확률을 확인할 수 있다.

## 7. 요청 및 결과 확인

요청에는 네이버 블로그 채널과 음식 사진을 포함한다.

```json
{
  "copy": {
    "channel": "naver_blog",
    "business_type": "카페"
  },
  "blog_images": [
    {
      "id": "food-1",
      "name": "dessert.jpg",
      "data_url": "data:image/jpeg;base64,..."
    }
  ]
}
```

정상 처리 시 응답의 다음 값을 확인한다.

```json
{
  "image": {
    "model": "food-image-cleanup-pipeline",
    "media_type": "image/jpeg"
  },
  "vision_prompt": {
    "image_generation": "background_replacement_completed",
    "background_template": "cafe"
  }
}
```

## 8. 실패 시 동작과 점검 순서

모델 미설치, GPU 부족, 생성 시간 초과, 모델 로딩 오류가 발생해도 광고 문구 생성 요청 전체를 실패시키지 않는다. 원본 업로드 사진을 반환하고 다음 상태 중 하나를 기록한다.

| 상태 | 의미 | 조치 |
| --- | --- | --- |
| `background_replacement_not_configured` | 기능이 비활성화됐거나 실행 Python·프로젝트를 찾지 못함 | `.env`와 Python 경로를 확인한다. |
| `background_replacement_failed_fallback` | 파이프라인 실행 또는 모델 추론 실패 | API 로그, 파이프라인 보고서, GPU·모델·의존성을 확인한다. |
| `background_replacement_completed` | 합성 결과를 정상 반환함 | 결과 이미지와 보고서의 검증 단계를 확인한다. |

현재 API 가상환경이 삭제된 시스템 Python 경로를 참조하는 경우에는 먼저 API 또는 파이프라인 가상환경을 재생성해야 한다. 정상 Python 경로를 `BRANDMATE_NAVER_IMAGE_CLEANUP_PYTHON`에 지정한 뒤 API를 재시작한다.

## 9. 각도 기반 후보 생성과 합성 품질 정책

네이버 채널의 이미지 보정은 업종별 기본 프롬프트를 그대로 생성기에 넘기지 않는다. 먼저 `food-image-cleanup-pipeline/models/efficientnet_best.pt`의 EfficientNet-B0로 사진을 `top` 또는 `45`로 판별한다. 호출 JSON에 `camera_angle_manual: true` 및 `camera_angle_label`이 있으면 이 수동 값이 우선한다.

| 각도 | 생성 배경 | 전경 배치 | 그림자 |
| --- | --- | --- | --- |
| `top` | 수직 탑뷰 빈 테이블 | 중앙, 너비 55~70% | 짧고 약한 원형 |
| `45` | 45도 테이블·실내 빈 배경 | 하단 중앙, 너비 55~70% | 일반 접지 그림자 |

Sana 또는 FLUX는 서로 다른 시드로 기본 3장, 설정에 따라 최대 4장의 배경 후보를 만든다. 후보 중 다음 기준의 점수가 가장 높은 한 장만 사용한다.

1. 음식이 놓일 중앙 영역이 충분히 비어 있는가
2. 원본 음식 사진의 색온도와 과도하게 다르지 않은가
3. YOLO가 생성 배경에서 음식을 검출하지 않았는가

원본 음식·접시 전경은 다시 생성하지 않고 9px feather 알파로 합성한다. 제한된 밝기 조화·가장자리 색 번짐 제거 후 OpenCLIP 전경 비교, 배경 음식 탐지, 기하 검증을 모두 수행한다. 음식이 포함된 배경 또는 잘못된 전경 크기·위치는 광고 JPG로 반환하지 않고 원본 이미지를 유지한다. 상세 후보 점수와 선택 결과는 파이프라인 보고서의 `step_8_background_generation`, `step_9_foreground_placement`, `step_14_background_geometry_validation`에서 확인할 수 있다.
