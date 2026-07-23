# 음식 이미지 배경 교체 프로젝트 개요

## 1. 왜 만들었는가

네이버 채널용 광고 문구를 만들 때 업로드한 음식 사진이 원본 배경 그대로 노출되는 문제를 해결하기 위해 만들었다. 입력 음식의 형태와 원본 접시를 최대한 보존하면서, 업종과 촬영 각도에 맞는 빈 테이블 배경을 생성하고 자연스럽게 합성하는 것이 목적이다.

현재 기준 구현은 원본 접시를 보존하는 `preserve_original_plate` 모드다. 음식이나 접시를 생성 모델로 다시 그리지 않으므로 메뉴의 외형이 바뀌는 위험을 줄인다.

## 2. 무엇을 입력받는가

- JPG, JPEG, PNG, WEBP 형식의 음식 사진
- 선택 메타데이터 JSON
  - `business_type`: 카페, 베이커리, 디저트, 음식점, 주점 등 업종
  - `food_category`: 음식 분류 또는 메뉴 설명
  - `camera_angle`: 사용자가 지정하는 촬영 각도(`top`, `45` 등). 없으면 EfficientNet-B0가 예측한다.
- 선택 설정 파일: 기본값은 `configs/pipeline.yaml`

## 3. 무엇을 출력하는가

성공 시 다음을 출력한다.

- 최종 광고 이미지: `data/output/<이름>_background_replaced.jpg`
- 원본 접시·음식 전경 PNG: `data/intermediate/<이름>_foreground_rgba.png`
- 생성 배경과 후보 이미지: `data/intermediate/`
- 단계별 상태, 선택 후보, 품질·의미 검증 결과: `data/reports/<이름>_background_replacement_report.json`
- 디버그 마스크: `data/masks/` 및 `data/intermediate/`

검증을 통과하지 못하면 광고 이미지를 저장하지 않고, 실패 사유와 중간 산출물만 보고서에 남긴다.

## 4. 현재 전체 파이프라인

```text
입력·품질 검사
  → GroundingDINO 음식·접시 후보 탐지
  → 학습한 음식 전용 YOLO11n(best.pt) 탐지 보강
  → SAM 2.1 Small 음식·접시 구조 마스크
  → 접시 외곽 보존 마스크·음식 마스크 안정화
  → SAM 마스크 기반 RGBA 전경 생성
  → EfficientNet-B0 촬영 각도 판별 또는 JSON 각도 사용
  → 업종·각도별 빈 테이블 배경 프롬프트 생성
  → Sana 1.6B 또는 선택한 FLUX.1 Schnell 배경 후보 생성
  → 중앙 빈 공간·기하 조건·배경 내 음식 여부로 후보 선택
  → 접시 전경 축소·배치·약한 접지 그림자·제한적 색 조화
  → OpenCLIP·선명도·밝기·대비 검증
  → 최종 이미지 또는 실패 보고서 저장
```

### 전경 보존 원칙

1. 원본 접시와 음식 픽셀은 생성 모델에 전달하지 않는다.
2. 접시 외곽은 SAM 구조 마스크와 접시 보존 마스크로 유지한다.
3. 현재 기본 경로는 BiRefNet을 사용하지 않는다(`models.matting.enabled: false`). 알파는 안정화된 SAM 음식·접시 분할 마스크만 사용한다.
4. 접시 전체를 새로 생성하는 `generated_plate` 모드는 선택 실험 기능이며 기본값이 아니다.

## 5. 사용하는 모델과 이유

| 모델 | 현재 역할 | 선택 이유 |
| --- | --- | --- |
| GroundingDINO Tiny | 음식·접시 후보 상자 탐지 | 텍스트 조건을 이용해 일반 COCO 클래스보다 음식·접시 후보를 폭넓게 찾는다. 가중치는 `models/grounding-dino`에 캐시한다. |
| 학습한 YOLO11n (`models/best.pt`) | 음식 전용 탐지 보강 | AIHub 음식 사진으로 학습한 전용 모델을 기본 탐지기로 사용해 한식·빵·접시 조합 탐지를 보완한다. 기본 COCO YOLO11n은 선택 프로필이다. |
| SAM 2.1 Small | 음식·접시 구조 분할 | 탐지 상자를 세밀한 마스크로 확장하며, 현재 전경 알파의 기준이다. |
| EfficientNet-B0 (`models/efficientnet_best.pt`) | `top`·`45` 촬영 각도 판별 | 입력 시점에 맞는 배경 프롬프트·배치·그림자 모양을 선택한다. JSON `camera_angle`이 있으면 그 값을 우선한다. |
| Sana 1.6B | 기본 빈 배경 생성 | 별도 접근 토큰 없이 코랩 GPU에서 실행할 수 있는 기본 생성기다. |
| FLUX.1 Schnell | 선택 배경 생성기 | 설정에서 제공자를 변경하면 사용할 수 있는 대안이다. |
| OpenCLIP ViT-B-32 | 전경 의미 보존 검증 | 합성 전후 음식·접시 영역의 의미가 지나치게 달라졌는지 확인한다. |
| Big-LaMa | 선택적 이물질 제거 | 전경 보호 마스크 밖의 포크·나이프·작은 이물질을 제한적으로 제거한다. |

BiRefNet HR은 과거 경계 실험에 사용했지만 접시 외곽이 투명해지거나 일부가 끊기는 사례가 있어 현재 기본 경로에서 껐다. 관련 모델 파일을 별도로 내려받거나 실행할 필요가 없다.

## 6. 네이버 채널과의 연결

`C:\dev\final_1_team`의 네이버 채널에서 이미지 보정이 요청되면 음식 이미지 보정 모듈이 이 파이프라인을 실행한다. JSON의 업종 값은 배경 프롬프트 선택에 사용된다.

- `카페`, `베이커리`, `디저트` → 밝은 카페형 배경
- `음식점` → 식당형 배경
- `주점` → 어두운 목재·따뜻한 조명 중심의 펍형 배경

파이프라인의 결과 상태가 `completed`일 때만 생성한 광고 이미지를 사용한다. 탐지 실패, 전경 보존 실패, OpenCLIP 실패 상태는 원본을 임의로 대체하지 않고 보고서로 반환한다.

## 7. 실행 방법

### 로컬

프로젝트 루트에서 의존성을 설치한다.

```powershell
pip install -r requirements-local.txt
python -m scripts.download_models --models yolo sam2 big-lama openclip sana grounding-dino
```

실행 예시는 다음과 같다.

```powershell
python -m scripts.run_background_replacement `
  --input data/input/example.jpg `
  --metadata data/input/example_metadata.json `
  --enable-background-generator
```

학습한 음식 전용 탐지기를 기본으로 사용한다. 기본 COCO YOLO11n으로 비교하려면 `--detector-profile coco_yolo11n`을 사용한다.

### Google Colab

`notebooks/01_colab_background_replacement.ipynb`를 사용한다. 노트북은 프로젝트를 Google Drive에서 열고, 의존성 설치·가중치 캐시·입력 생성·파이프라인 실행·결과 저장을 순서대로 수행한다. GroundingDINO 가중치는 프로젝트의 `models/grounding-dino`에 저장돼 런타임 재실행 때 다시 내려받지 않는다.

실험 기준 환경은 Google Colab GPU L4였다. 코랩 실행 절차와 문제 해결은 `docs/COLAB_SETUP.md`를 따른다.

## 8. 현재 완성 상태

- 네이버 채널 이미지 보정 경로 연결 완료
- GroundingDINO + 학습한 음식 전용 YOLO11n + SAM 2.1 Small 전경 분리 완료
- EfficientNet-B0 기반 `top`·`45` 각도 자동 판별 및 프롬프트 선택 완료
- 업종별 배경 프롬프트, 다중 후보 생성·선택, 접지 그림자, 제한적 색 조화 완료
- 원본 접시 보존 모드와 접시 마스크 디버그 산출물 저장 완료
- OpenCLIP·배경 음식 검출·기하·기본 품질 검증 완료
- YOLO11-seg 기반 `plate_full` / `food_visible` 전용 접시 분할 모델은 데이터 자동 초안·CVAT 검수·학습 흐름을 마련했고, 최종 학습 가중치 연결은 진행 중이다.

### 최근 검증 예시

Google Colab L4 환경에서 BiRefNet을 끈 상태로 수행한 최근 예시에서는 다음이 확인됐다.

- GroundingDINO 음식 후보 7개, 접시 후보 1개 탐지
- 음식 전용 YOLO11n 후보 1개 탐지
- EfficientNet-B0가 `top`을 약 0.965 신뢰도로 판별
- 배경 후보를 4회 생성해 유효 후보 3개 중 최적 후보 선택
- OpenCLIP 유사도 약 0.986으로 기준 0.8 통과
- 밝기·대비·선명도 품질 검증 통과

이 값은 한 장의 검증 사례이며 전체 데이터셋의 일반 성능 지표는 아니다.

## 9. 남아 있는 문제와 다음 개선

- 원형 접시에는 기하 보정이 효과적이지만, 사각 접시·유리 그릇·접시가 거의 보이지 않는 경우에는 오검출 가능성이 남아 있다.
- 생성 배경은 음식·접시·컵을 금지해도 일부 소품이 생길 수 있다. 후보 선택 단계에서 더 강한 객체 검출과 재생성 정책이 필요하다.
- 조명 방향은 현재 프롬프트와 단순 그림자에 의존한다. 배경과 전경의 물리적 조명 차이를 더 줄이려면 별도 조명 조화 모델을 검증해야 한다.
- 장기적으로 `plate_full`, `food_visible` 두 클래스를 가진 YOLO11-seg 모델을 학습·평가해 기하 보정을 보조 또는 대체해야 한다.
- 다양한 업종·촬영 각도·접시 재질에 대해 성공률, 전경 보존율, 사용자 선호도 평가셋을 구축해야 한다.

## 10. 관련 문서

- `docs/NAVER_IMAGE_ENHANCEMENT_DEVELOPMENT_HISTORY.md`: 네이버 채널 이미지 보정 기능을 처음 설계한 시점부터 현재까지의 의사결정·실험 이력
- `docs/ARCHITECTURE.md`: 코드 기준 세부 구조
- `configs/pipeline.yaml`: 현재 적용되는 모델·가중치·배경 생성·검증 설정
- `docs/COLAB_SETUP.md`: 코랩 실행과 가중치 캐시
- `docs/LOCAL_SETUP.md`: 로컬 실행
- `docs/PLATE_SEGMENTATION_TRAINING.md`: 접시 전용 YOLO11-seg 데이터·CVAT 검수·학습 절차
