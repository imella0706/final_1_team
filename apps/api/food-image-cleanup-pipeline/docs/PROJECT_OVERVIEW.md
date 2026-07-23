# 음식 이미지 배경 교체 프로젝트 개요

## 1. 왜 만들었는가

네이버 블로그용 음식 사진은 원본 배경, 부스러기, 식기, 조명 상태 때문에 광고 이미지로 바로 쓰기 어려울 수 있다. 이 프로젝트는 음식과 음식을 담은 용기는 원본 픽셀로 보존하고, 불필요한 배경을 제거한 뒤 업종과 음식 분위기에 맞는 새 배경을 생성·합성하기 위해 만들었다.

가장 중요한 원칙은 생성 모델이 음식 자체를 다시 그리지 않도록 하는 것이다. 음식의 모양, 색, 소스, 접시 무늬가 바뀌면 실제 메뉴와 광고 이미지가 달라질 수 있기 때문이다.

## 2. 무엇을 입력받는가

필수 입력은 다음 두 가지다.

- 음식 사진: JPG, JPEG, PNG, WEBP 형식의 원본 사진
- 배경 메타데이터 JSON: 업종, 음식 범주, 배치 위치, 광원 방향, 필요하면 고정 배경 프롬프트

예시 JSON:

```json
{
  "business_type": "cafe",
  "food_category": "dessert",
  "foreground_position": "center_lower",
  "light_direction": "left",
  "background_prompt": "Photorealistic premium modern Korean cafe interior, empty table surface, no food, no plate, no people, no text"
}
```

네이버 연동에서는 업로드 이미지와 사용자 JSON의 업종값을 받아 `pub`, `restaurant`, `cafe` 계열의 배경 프롬프트를 선택한다.

## 3. 무엇을 출력하는가

다음 파일을 생성한다.

- 최종 이미지: `data/output/<입력명>_background_replaced.jpg`
- 투명 전경 이미지: `data/intermediate/<입력명>_foreground.png`
- 알파 매트: `data/masks/<입력명>_foreground_alpha.png`
- 생성 배경: `data/intermediate/<입력명>_generated_background.jpg`
- 실행 보고서: `data/reports/<입력명>_background_replacement_report.json`

최종 이미지는 새 배경 위에 원본 음식·용기 전경을 합성하고 그림자와 경계 보정을 적용한 결과다.

## 4. 전체 파이프라인은 어떻게 되는가

```text
입력 음식 사진
  → 음식·용기 후보 탐지
  → SAM 구조 마스크
  → BiRefNet 알파 매트
  → 음식 보호 영역 생성
  → 전경 주변 이물질만 LaMa로 제거
  → 원본 음식·용기 RGBA 추출
  → 업종별 FLUX 빈 배경 생성
  → 원래 위치·크기에 맞춘 전경 배치
  → 접지 그림자 생성
  → 경계 색 번짐·밝기 조화
  → 알파 합성
  → OpenCLIP 전경 보존 검증
```

FLUX는 음식이 없는 배경만 만들고, 음식·용기 전경은 원본 이미지에서 가져온다.

## 5. 각 모델은 왜 사용했는가

| 모델 | 역할 | 선택 이유 |
|---|---|---|
| YOLO11n | 음식·용기·포크·나이프·스푼 탐지 | 가볍고 빠르며 SAM에 사각형 프롬프트를 제공할 수 있다. |
| 음식 특화 YOLO11n | 음식 전체 위치 탐지 | 프로젝트 음식 이미지와 Bounding Box로 학습해 COCO에 없는 한식·빵·디저트의 탐지 실패를 줄인다. |
| SAM 2.1 Tiny | 음식·용기 구조 마스크 | 전경 범위를 구조적으로 분리한다. |
| BiRefNet HR | 연속 알파 매트 | 접시 곡선, 유리, 얇은 장식물 등 경계를 더 자연스럽게 만든다. |
| Big-LaMa | 전경 주변 이물질 제거 | 음식 경계 근처의 부스러기·식기·작은 소품을 제한적으로 제거한다. |
| FLUX.1 Schnell | 빈 광고 배경 생성 | 빠른 단계 수로 업종별 음식 광고 배경 후보를 생성한다. |
| OpenCLIP ViT-B-32 | 전경 의미 보존 검증 | 배경이 아니라 음식·용기 영역이 원본과 지나치게 달라지지 않았는지 확인한다. |

## 6. 실제로 어떻게 실행하는가

로컬 실행:

```powershell
cd C:\dev\final_1_team\apps\api\food-image-cleanup-pipeline
python -m pip install -r requirements-local.txt
python -m scripts.download_models --all
python -m scripts.run_background_replacement --input data/input/example.jpg --metadata data/input/example_metadata.json --enable-matting --enable-background-generator
```

음식 전용 탐지기는 기본으로 `models/best.pt`를 사용한다. 이번 실행에만 기본 COCO YOLO11n을 선택하려면 아래처럼 실행한다.

```powershell
python -m scripts.run_background_replacement --input data/input/example.jpg --metadata data/input/example_metadata.json --detector-profile coco_yolo11n
```

항상 기본 COCO 모델을 사용하려면 `configs/pipeline.yaml`의 `models.foreground_detector.active_profile` 값을 `coco_yolo11n`으로 변경한다. 음식 전용 모델로 되돌릴 때는 `food_specialized`를 사용한다.

코랩 실행은 `notebooks/01_colab_background_replacement.ipynb`를 GPU 런타임에서 위에서 아래로 실행한다. 자세한 내용은 `LOCAL_SETUP.md`, `COLAB_SETUP.md`를 참고한다.

음식 특화 YOLO11n 학습은 로컬 `notebooks/04_local_yolo11n_food_training.ipynb` 또는 코랩 `notebooks/03_colab_yolo11n_food_training.ipynb`에서 실행한다. 두 노트북은 음식 메타데이터의 Bounding Box를 YOLO 라벨로 변환하고, 학습 뒤 `Precision`, `Recall`, `mAP50`, `mAP75`, `mAP50_95` 평가 보고서를 저장한다. 자세한 절차는 `YOLO11N_FOOD_TRAINING.md`에 정리되어 있다.

## 7. 현재 어디까지 완성되었는가

- 네이버 블로그 업로드 이미지에서 내부 파이프라인을 호출하는 연동 어댑터를 추가했다.
- 업종별 배경 프롬프트 선택을 구현했다.
- 음식·용기 분리, 알파 매트, 배경 생성, 그림자, 합성, 전경 OpenCLIP 검증 코드를 구현했다.
- 로컬·코랩 요구사항 파일과 코랩 검증 노트북을 정리했다.
- 음식 데이터 1,036장의 메타데이터 Bounding Box를 검증해 학습 878장·검증 158장의 `food` 단일 클래스 YOLO 데이터셋을 생성했다.
- 로컬·코랩 YOLO11n 학습 노트북과 정량 평가 스크립트를 추가했다.
- 코드 문법과 YAML 설정 로딩은 확인했다.

## 8. 어떤 문제가 남아 있는가

- 실제 코랩 GPU에서 음식 특화 YOLO11n 100 epoch 학습과 평가를 끝까지 실행한 실측 지표는 아직 필요하다.
- YOLO11n의 기본 COCO 클래스에는 많은 한식과 복합 음식이 없어 음식 탐지가 실패할 수 있다.
- FLUX.1 Schnell과 BiRefNet은 GPU 메모리와 다운로드 시간이 많이 필요하다.
- Big-LaMa, BiRefNet, FLUX를 한 실행에 함께 올리면 코랩 GPU 메모리 부족이 발생할 수 있다.
- IC-Light 직접 추론은 음식 디테일 변경 위험 때문에 아직 연결하지 않았다.

## 9. 앞으로 무엇을 개선해야 하는가

1. 새 YOLO11n 모델을 코랩 GPU에서 학습하고, 검증 지표와 실제 네이버 업로드 사진 결과를 확인한 뒤에만 운영 탐지기 우선순위에 연결한다.
2. 실제 네이버 업로드 사진으로 전경 분리·배경 생성·합성 품질을 평가하는 테스트셋을 만든다.
3. 모델을 단계별로 메모리에서 해제하거나 CPU 오프로딩해 코랩 메모리 사용량을 줄인다.
4. 여러 FLUX 시드 후보를 생성하고 OpenCLIP·사람 평가로 가장 자연스러운 배경을 선택한다.
5. IC-Light V1을 연결할 경우 결과 전체를 쓰지 않고 저주파 조명 성분만 원본 전경에 반영한다.
6. 네이버 API 응답에 단계별 상태, 실패 원인, 결과 보고서 경로를 함께 기록한다.

## 10. 현재 운영 안전 정책

### 음식 특화 탐지

탐지는 설정된 YOLO11n 프로필 하나만 사용한다. 기본값은 `models/best.pt` 음식 전용 모델이며, 필요하면 COCO 기본 `models/yolo11n.pt` 프로필을 선택할 수 있다. 음식·용기 후보를 찾지 못하면 `food_detection_failed` 상태를 보고서에 저장하고 광고 이미지는 생성하지 않는다. 중앙 사각형 대체는 `--diagnostic-center-fallback` 연결 테스트 전용이다.

### 매팅과 의미 검증

SAM 구조 마스크는 합성 전에 닫힘 연산, 작은 연결 요소 제거, 내부 구멍 채우기로 안정화한다. BiRefNet은 이 안정화 마스크를 미세 보정할 때만 사용한다. BiRefNet 알파와 안정화 SAM 마스크의 IoU, 면적 비율, 연결 요소 수를 검사해 기준을 넘지 못하면 안정화 SAM 마스크로 즉시 되돌린다. OpenCLIP은 마스크 바깥을 중립색으로 제거한 전경 비교 이미지로 유사도를 계산한다. 유사도가 0.8 미만이면 SAM 마스크로 재합성하고, 재검증도 실패하면 `semantic_validation_failed` 상태로 종료한다. 이 경우 최종 광고 JPG는 저장하지 않는다.

### 디버그 산출물

실행 보고서의 `debug_artifacts`에는 원본·안정화 SAM 구조 마스크, BiRefNet/SAM 알파 마스크, RGBA 전경 미리보기, OpenCLIP 전경 비교 이미지, 최종 합성 또는 거부된 합성 이미지 경로가 들어간다. 선명도·밝기·대비 검증은 생성 배경이 아닌 안정화된 전경 영역만 대상으로 계산한다.

## 최신 합성 품질 정책

촬영 각도는 JSON의 수동 지정값 또는 EfficientNet-B0 분류 결과로 결정한다. 이 결과는 단순 메타데이터가 아니라 배경 프롬프트의 카메라 구도, 전경 위치, 그림자 파라미터를 함께 결정한다.

| 항목 | `top` | `45` |
| --- | --- | --- |
| 생성 배경 | 수직 탑뷰 빈 테이블 | 45도 테이블·실내 빈 배경 |
| 전경 위치 | 중앙 | 하단 중앙 |
| 전경 너비 | 캔버스의 55~70% | 캔버스의 55~70% |
| 그림자 | 짧고 약한 원형 그림자 | 일반 접지 그림자 |

배경은 고정 시드 하나로 한 장만 만들지 않는다. 기본 3장, 설정 시 최대 4장을 생성하고 다음 점수를 합산해 후보를 고른다.

1. 음식이 놓일 중앙 영역의 여백
2. 원본과 생성 배경의 색온도 유사성
3. 생성 배경에서 음식이 검출되지 않았는지 여부

선택된 배경은 원본 음식 픽셀을 다시 생성하지 않고, 9px feather 알파와 제한된 색 조화로 합성한다. OpenCLIP 전경 비교, 배경 음식 탐지, 전경 크기·배치 기하 검증 중 하나라도 실패하면 광고용 결과 파일을 저장하지 않는다.
