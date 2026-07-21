# EfficientNet-B0 촬영 각도 분류 학습

## 목적

현재 데이터셋에 존재하는 음식 이미지가 `top`, `45` 중 어느 촬영 각도인지 분류한다. 배경 교체 파이프라인은 이 결과를 이용해 원본 시점과 맞는 배경 프롬프트를 선택하게 된다.

## 입력과 라벨

원본 이미지와 확정 라벨은 다음 위치에 있다.

- 이미지: `data/training/EfficientNet-B0 angle/images/train`, `data/training/EfficientNet-B0 angle/images/val`
- 라벨 원장: `data/training/EfficientNet-B0 angle/labels/angle_label_review.csv`

`final_angle`은 반드시 다음 중 하나여야 한다.

- `top`: 음식·용기를 거의 수직 위에서 촬영한 탑뷰
- `45`: 위와 옆면이 함께 보이는 약 30~60도 사선 시점

현재 데이터에는 `side`, `low` 이미지가 없으므로 두 클래스는 학습 대상에서 제외했다. 학습 데이터 준비 스크립트는 빈 값·오타·존재하지 않는 파일을 거부하고, `top`, `45`가 각각 train/val에 최소 두 장 이상 없으면 중단한다.

## 데이터셋 구성

다음 명령은 CSV 라벨을 `torchvision.datasets.ImageFolder` 구조로 복사한다.

```text
data/training/efficientnet_b0_angle/dataset/
  train/top, train/45
  val/top,   val/45
  class_map.json
  dataset_summary.json
  manifest.csv
```

```powershell
python -m scripts.prepare_angle_classification_dataset
```

원본 이미지는 변경하지 않는다. 출력 폴더가 이미 비어 있지 않으면 덮어쓰지 않고 중단한다.

## 로컬 학습

프로젝트 루트에서 실행한다.

```powershell
python -m pip install -r requirements-angle-classifier-local.txt
python -m scripts.prepare_angle_classification_dataset
python -m scripts.train_efficientnet_b0_angle_classifier --epochs 50 --batch-size 32
python -m scripts.evaluate_efficientnet_b0_angle_classifier --weights runs/efficientnet_b0_angle/best.pt
```

CPU도 지원하지만 학습 시간이 길다. NVIDIA GPU가 있으면 자동으로 CUDA를 선택한다. `--device cpu` 또는 `--device cuda:0`으로 명시할 수 있다.

## Google Colab 학습

`notebooks/05_colab_efficientnet_b0_angle_training.ipynb`를 Drive의 프로젝트 위치에서 연다. 런타임 유형을 GPU로 바꾼 뒤 위에서부터 실행한다.

이 노트북은 `pip install torch`, `pip install torchvision`을 실행하지 않는다. Colab 기본 런타임의 호환된 PyTorch·torchvision 조합을 그대로 사용하므로, 기존 배경 생성 의존성과 충돌하지 않는다. 첫 셀에서 두 패키지와 CUDA를 확인하고 없을 때만 명확한 오류를 낸다.

## 산출물과 지표

학습 결과는 기본적으로 `runs/efficientnet_b0_angle/`에 저장된다.

- `best.pt`: 검증 균형 정확도가 가장 높았던 체크포인트
- `last.pt`: 마지막 에포크 체크포인트
- `training_report.json`: 에포크별 손실·정확도·균형 정확도·매크로 F1
- `training_history.csv`: 에포크별 수치를 스프레드시트에서 확인할 수 있는 CSV
- `training_curves.png`: 매 에포크 갱신되는 학습·검증 손실 및 평가 지표 그래프
- `best_confusion_matrix.png`: 최고 체크포인트의 혼동 행렬

독립 평가 명령은 `runs/efficientnet_b0_angle_evaluation/metrics.json`, `confusion_matrix.png`를 만든다. 주요 지표는 정확도, 균형 정확도, 매크로 F1, 클래스별 precision/recall/F1, 혼동 행렬이다. 클래스 데이터가 불균형할 수 있으므로 배포 판단에는 단순 정확도보다 균형 정확도와 클래스별 recall을 우선한다.

## 학습 품질을 위한 기본 정책

이 구성은 ImageNet 사전학습 EfficientNet-B0, 약한 증강, 클래스 가중치, label smoothing, AdamW, 학습률 감쇠, 조기 종료를 포함한 베이스라인이다. 50 epoch은 **최대치**이며, 검증 균형 정확도가 10 epoch 동안 개선되지 않으면 조기 종료한다.

초기 5 epoch은 분류기 헤드만 학습하고, 이후에는 더 작은 학습률로 백본까지 미세조정한다. `RandomResizedCrop` 범위를 `0.92~1.0`으로 제한해 촬영 각도 판정에 중요한 접시 테두리와 테이블 평면이 과도하게 잘리지 않도록 했다.

현재 `val`은 모델 선택과 조기 종료에 사용하므로 최종 성능의 독립 지표가 아니다. 서비스 적용 전에는 같은 음식의 연속 촬영본이 train/val에 나뉘지 않도록 촬영 세트 단위로 분할하고, 별도 test 세트와 실제 사용자 업로드 사진으로 최종 평가해야 한다.

## 학습 완료 가중치의 실제 사용 범위

평가를 통과해 `models/efficientnet_best.pt`로 배치한 가중치는 로컬 실행, Colab 실행, 네이버 채널 이미지 보정에서 공통으로 사용한다. 파이프라인은 JSON 수동 각도가 없을 때만 이 가중치로 `top` 또는 `45`를 판별한다.

판별 결과는 다음 세 가지를 함께 선택한다.

1. 업종별 빈 배경 프롬프트에 추가할 카메라 제약
2. 접시·음식 전경의 중앙 또는 하단 중앙 배치 정책
3. 탑뷰용 약한 원형 그림자 또는 45도용 일반 접지 그림자

모델의 목적은 음식 종류를 분류하거나 전경 마스크를 만드는 것이 아니다. 원본 사진과 생성 배경의 원근을 맞춰 합성 결과가 공중에 떠 보이는 문제를 줄이는 것이다. 후보 배경 생성·선택, 전경 55~70% 재배치, OpenCLIP·배경 음식·기하 검증의 상세 동작은 `CAMERA_ANGLE_PROMPT_SELECTION.md`를 참고한다.
