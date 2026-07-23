# 음식 데이터로 YOLO11n 음식 위치 탐지 모델 학습

## 목적

COCO 사전학습 YOLO11n은 빵·한식·접시 조합을 일관되게 음식으로 인식하지 못할 수 있다. 이 문서는 프로젝트 음식 이미지 1,036장으로 `food` 위치를 탐지하는 별도 YOLO11n 모델을 만드는 절차다.

이 모델의 역할은 음식 종류 분류가 아니라, 배경 교체 파이프라인의 SAM 2.1에 전달할 음식 사각형을 찾는 것이다.

## 데이터와 라벨

원본은 프로젝트의 v2 음식 데이터 폴더다. 다른 위치에 두었다면 데이터셋 변환 시 `--source-root`로 해당 경로를 지정한다.

이미지는 `images/`에 있고, 같은 폴더의 `metadata.csv`에는 각 이미지에 대한 `bbox_x`, `bbox_y`, `bbox_width`, `bbox_height`, `bbox_found`가 있다. 변환 스크립트는 이 좌표를 YOLO 형식의 정규화된 `food` 단일 클래스 라벨로 바꾼다.

현재 메타데이터에는 접시·컵·그릇을 독립 객체로 구분하는 상자가 없으므로, 이 학습으로는 `container` 클래스를 만들 수 없다. 용기 분리가 필요하면 별도 주석을 추가해 2클래스 데이터셋을 다시 만들어야 한다.

## 1단계: 의존성 설치

로컬 GPU 환경에서는 프로젝트 루트에서 다음을 실행한다.

```powershell
python -m pip install -r requirements-local.txt
```

코랩에서는 `requirements-colab.txt`를 설치한다. 학습은 CUDA GPU를 권장한다. CPU에서도 실행되지만 1,036장 기준으로 실용적인 시간이 아닐 수 있다.

재현 가능한 실행 흐름은 다음 노트북에 준비되어 있다.

- 로컬: `notebooks/04_local_yolo11n_food_training.ipynb`
- Google Colab: `notebooks/03_colab_yolo11n_food_training.ipynb`

코랩은 Windows의 `C:\dev\...` 경로를 직접 사용할 수 없다. 프로젝트와 데이터 원본 폴더를 각각 Google Drive의 `MyDrive/final_1_team/...` 경로에 동기화한 뒤, 코랩 노트북 첫 셀의 `DRIVE_ROOT`만 실제 Drive 위치에 맞춘다.

## 2단계: YOLO 데이터셋 생성

```powershell
cd C:\dev\final_1_team\apps\api\food-image-cleanup-pipeline
python -m scripts.prepare_yolo_food_dataset
```

생성 위치는 `data/training/yolo_food_detection`이다. 같은 음식의 정면·측면 사진이 학습과 검증에 함께 들어가지 않도록 음식명 단위로 85:15 분할한다. 기본적으로 저장 공간을 아끼기 위해 원본 이미지의 하드링크를 만들며, 원본과 출력 위치가 다른 드라이브라면 `--copy-images`를 추가한다.

검증 전에는 다음 파일을 확인한다.

`data/training/yolo_food_detection/dataset_audit.txt`

여기서 유효 Bounding Box 수가 1,036장에 가깝고, 제외 사유가 없는지 확인한다.

## 3단계: 학습

```powershell
python -m scripts.train_yolo11n_food_detector --epochs 100 --imgsz 960 --device 0
```

`yolo11n.pt`가 없으면 Ultralytics가 사전학습 가중치를 내려받는다. 결과의 최적 모델은 다음처럼 생성된다.

`runs/yolo_food_detector/yolo11n_food_v1/weights/best.pt`

## 4단계: 검증과 운영 반영

학습 로그의 `mAP50-95`, `mAP50`, 검증 이미지 예측 결과를 함께 확인한다. 특히 네이버 채널에서 쓰는 탑뷰·정면 음식 사진을 별도 점검한다. 단일 숫자가 좋아도 접시를 포함하지 못하거나 음식 일부만 잡으면 배경 합성 품질이 떨어진다.

검증을 통과한 모델은 `models/best.pt`에 두며, 파이프라인은 기본으로 이 파일을 사용한다. `configs/pipeline.yaml`의 `models.foreground_detector.active_profile` 값을 `food_specialized`로 두면 된다. COCO 기본 모델과 비교하려면 값을 `coco_yolo11n`으로 바꾸거나 실행 시 `--detector-profile coco_yolo11n`을 지정한다.

정량 평가는 다음 명령으로 별도 실행할 수 있다.

```powershell
python -m scripts.evaluate_yolo11n_food_detector `
  --weights runs/yolo_food_detector/yolo11n_food_v1/weights/best.pt
```

평가 결과는 `runs/yolo_food_detector_evaluation/yolo11n_food_v1/metrics.json`에 저장된다. 포함 지표는 정밀도(Precision), 재현율(Recall), `mAP50`, `mAP75`, `mAP50_95`다. 숫자 평가와 함께 Ultralytics가 만드는 검증 예측 이미지와 혼동 행렬도 확인한다.

## 한계

- 이 데이터는 음식 전체의 단일 상자만 학습한다. 음식 종류 분류나 접시·컵 독립 탐지는 하지 않는다.
- 원본 메타데이터 상자가 음식과 접시를 함께 감싼 범위인지 표본 검수가 필요하다.
- 배경 제거 정확도는 탐지 상자 외에도 SAM·BiRefNet 품질에 좌우된다.

## 배경 후보 검증에서의 사용

학습된 `models/best.pt`는 입력 음식·접시의 위치를 찾는 기본 탐지기다. 같은 탐지기는 생성된 빈 배경 후보에도 적용되어 음식이 새로 생성됐는지 점검한다. 후보 배경에서 `food`가 검출되면 해당 후보는 선택 점수에서 크게 불리하며, 선택된 배경에서 음식이 검출된 경우 최종 광고 JPG를 저장하지 않는다.

이 검증은 음식 분할을 대신하지 않는다. 입력 전경은 YOLO 상자를 SAM 2.1 Tiny에 전달해 분할하고, 배경 후보 검증은 음식 없는 광고 배경이라는 조건을 확인하는 별도 안전장치다.
