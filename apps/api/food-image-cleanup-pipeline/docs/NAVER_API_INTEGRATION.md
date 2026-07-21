# 네이버 블로그 이미지 보정 API 연동

## 목적

`final_1_team`의 네이버 블로그 채널은 사용자가 올린 음식 사진을 광고 문구와 함께 반환한다. 이 연동은 사진을 다른 외부 프로젝트로 전달하지 않고, 같은 저장소의 `apps/api/food-image-cleanup-pipeline`을 실행해 음식·용기 전경은 유지하고 광고용 빈 배경만 생성·합성한다.

## 처리 흐름

```text
네이버 블로그 선택 + 음식 사진 업로드
→ API가 업로드 사진을 파이프라인 작업 파일로 저장
→ YOLO/SAM 2.1/BiRefNet으로 음식·용기 전경 분리
→ 업종별 빈 배경 프롬프트로 Sana 또는 FLUX 배경 생성
→ 그림자·색상 조화·의미 검증
→ 합성 JPG를 네이버 광고 문구 응답의 image로 반환
```

모델 준비 전이거나 처리 중 오류가 나면 광고 문구 API 전체를 실패시키지 않고 원본 사진을 반환한다. 이때 응답의 `vision_prompt.image_generation`과 `vision_prompt.image_enhancement_reason`에서 원인을 확인한다.

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

파이프라인 전용 환경은 `food-image-cleanup-pipeline/requirements-local.txt`를 설치하고, `scripts/download_models.py`로 필요한 모델을 받는다. GPU와 모델 파일이 준비되지 않은 상태에서 활성화하면 API는 원본 사진을 반환하며 상태를 `background_replacement_failed_fallback`으로 기록한다.

## 확인 방법

1. API 서버를 재시작한다.
2. 네이버 블로그 채널과 음식 사진 한 장으로 `/api/v1/ad-content/generate`를 호출한다.
3. 응답의 `vision_prompt.image_generation`이 `background_replacement_completed`인지 확인한다.
4. `image.media_type`이 `image/jpeg`, `image.model`이 `food-image-cleanup-pipeline`인지 확인한다.

