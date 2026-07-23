# 접시 전체 보존용 YOLO11-seg 학습

## 목적

현재 음식 사진 보정 파이프라인은 GroundingDINO·음식 탐지 상자와 SAM 2.1 Small 마스크를 이용한다. 이 방식은 음식이 접시 중앙을 가리거나 무늬 접시의 경계가 약할 때 접시 일부를 배경으로 오인할 수 있다. 이 문서는 접시 전체 외곽을 보존하는 `plate_full`과 실제로 보이는 음식인 `food_visible`을 별도 인스턴스 분할 모델로 학습하는 방법을 설명한다.

`plate_full`에는 음식으로 가려진 접시 중앙과 접시 테두리까지 포함한다. `food_visible`은 실제로 보이는 음식만 포함한다. 두 마스크가 겹치는 것은 정상이다. 파이프라인은 두 마스크를 합쳐 원본 접시와 음식을 모두 보존하며, 현재 합성 알파는 안정화된 SAM 마스크만 사용한다.

## 사용하는 원본 데이터

기본 후보군은 다음 AIHub 정제 이미지셋이다.

`C:\dev\final_1_team\data\processed\aihub_food_image_text\v2\food_description_data`

이 경로의 `metadata.csv`는 이미지 존재 여부, 품질 통과 여부, 음식 이름, 촬영 시점, 중복 그룹 정보를 가진다. 준비 스크립트는 그중 `image_exists=true`, `quality_pass=true` 이미지를 대상으로 하고, 같은 음식·시점의 유사 이미지가 한쪽으로 몰리지 않도록 `food_view_key`를 섞어 500장을 기본 추출한다.

중요: 이 이미지셋에는 접시/음식 **마스크 라벨이 없다.** 기존 `yolo_food_detection/labels`의 사각형 라벨은 접시 분할 학습에 사용할 수 없다. 아래 절차로 새 마스크를 만든다.

## 클래스와 주석 규칙

| 클래스 | 번호 | 주석 범위 |
| --- | ---: | --- |
| `plate_full` | 0 | 음식에 가려진 중앙을 포함한 접시 외곽 전체. 접시 무늬와 테두리를 포함한다. 식탁보·테이블은 제외한다. |
| `food_visible` | 1 | 사진에서 실제로 보이는 음식만. 접시 테두리와 배경은 제외한다. |

접시가 없거나 외곽을 판단하기 어려운 사진은 억지로 라벨링하지 않는다. `plate_annotation_manifest.csv`의 `plate_full_status`를 `skipped`로 변경한다.

## 1. AIHub 후보 이미지와 작업 목록 만들기

프로젝트 루트에서 실행한다.

```powershell
python -m scripts.prepare_plate_annotation_manifest --sample-size 500
python -m scripts.assign_plate_segmentation_splits
```

생성 결과는 다음과 같다.

- `data/training/plate_segmentation/cvat_images/`: CVAT에 올릴 이미지
- `data/training/plate_segmentation/plate_annotation_manifest.csv`: 주석 상태와 split 목록
- `data/training/plate_segmentation/CVAT_ANNOTATION_GUIDE.md`: 작업자용 간단 규칙

두 번째 명령은 같은 `split_group`이 다른 split에 섞이지 않도록 70/15/15 비율로 `target_split`을 자동 배정한다. 주석 작업 중 접시가 없는 사진은 `plate_full_status=skipped`로 바꾼다.

기본은 하드링크로 이미지를 준비한다. 파일 시스템이 다르면 자동으로 복사된다. 원본을 항상 복사하려면 `--copy-images`를 붙인다.

## 2. 자동 초안 생성 후 CVAT에서 검수하기

먼저 GroundingDINO와 SAM 2.1 Small로 COCO Instances 초안을 만든다.

```powershell
python -m scripts.generate_plate_segmentation_drafts --overwrite
```

`auto_annotations/instances_draft.json`과 `review_previews/`가 생성된다. CVAT에는 `cvat_images`를 올린 뒤 `instances_draft.json`을 COCO Instances 형식으로 가져온다. 사용자는 다음만 검수한다.

1. `plate_full` 폴리곤이 음식에 가린 중앙을 포함해 접시 테두리 전체를 감싸는지 확인한다.
2. `food_visible`에는 실제 음식만 남기고 접시·식탁보·테이블은 제외한다.
3. 접시가 없거나 외곽을 판단할 수 없는 이미지는 제외 대상으로 기록한다.
4. 검수 결과를 COCO Instances 1.0 형식으로 `data/training/plate_segmentation/annotations/instances_reviewed.json`에 내보낸다.
5. 아래 명령으로 두 클래스가 모두 있는 이미지의 상태를 자동으로 완료 처리한다.

```powershell
python -m scripts.mark_plate_annotation_reviewed `
  --coco-json data/training/plate_segmentation/annotations/instances_reviewed.json
```

CVAT을 처음 사용하는 경우의 클릭 순서, 검수 기준, 실패 이미지 처리 방식은 `GROUNDED_SAM2_CVAT_REVIEW.md`를 따른다. 같은 `split_group`은 반드시 같은 split에 둔다.

100장은 탑뷰·45도·무늬 접시·흰 접시·유리 그릇·식탁보·나무 테이블·음식이 접시를 크게 가린 경우를 의도적으로 포함해 별도 검수 집합으로 유지한다.

## 3. COCO 주석을 YOLO 분할 데이터로 변환하기

```powershell
python -m scripts.prepare_plate_segmentation_dataset `
  --coco-json data/training/plate_segmentation/annotations/instances_reviewed.json `
  --images-dir data/training/plate_segmentation/cvat_images
```

결과 `data/training/plate_segmentation/yolo_plate_segmentation/dataset.yaml`을 학습 입력으로 사용한다. `dataset_audit.json`에서 split별 수와 제외 사유를 확인한다. 모든 split에 `plate_full` 주석이 하나 이상 있어야 한다.

## 4. 로컬 학습과 평가

```powershell
python -m scripts.train_yolo11n_plate_segmenter --epochs 100 --imgsz 1024
python -m scripts.evaluate_yolo11n_plate_segmenter `
  --weights runs/plate_segmenter/yolo11n_plate_seg_v1/weights/best.pt
```

학습은 `yolo11n-seg.pt`를 시작 가중치로 사용한다. 평가 JSON에는 박스 및 세그멘테이션 mAP50/mAP50-95가 저장된다. 운영 도입의 최소 목표는 `plate_full` 검수셋에서 접시 외곽 누락이 없는지 육안 확인하고, 전체 세그멘테이션 mAP50 0.80 이상을 확인하는 것이다.

## 5. Google Colab에서 학습하기

Colab에는 Windows 경로가 존재하지 않는다. AIHub 원본과 프로젝트를 Google Drive의 동일한 `final_1_team` 구조로 올리거나 마운트해야 한다.

```python
from google.colab import drive
drive.mount('/content/drive')

%cd /content/drive/MyDrive/final_1_team/apps/api/food-image-cleanup-pipeline
!pip install --prefer-binary --upgrade-strategy only-if-needed -r requirements-colab.txt
```

`notebooks/08_colab_grounded_sam2_cvat_review.ipynb`는 후보 추출 여부 확인, GroundingDINO + SAM 2 자동 초안 생성, CVAT 검수본 반영, 변환, 학습, 평가를 순서대로 실행한다. `06_colab_plate_segmentation_training.ipynb`는 이미 검수 COCO가 준비된 경우에만 사용하는 간단 학습 노트북이다.

## 6. 광고 이미지 파이프라인에 연결하기

학습 후 가중치를 아래 경로에 복사한다.

`models/yolo11n_plate_seg.pt`

그 다음 `configs/pipeline.yaml`을 수정한다.

```yaml
models:
  plate_segmenter:
    enabled: true
    weights: models/yolo11n_plate_seg.pt
```

모델이 활성화되면 파이프라인은 `plate_full`을 접시 외곽의 우선 마스크로 사용하고, 기하학적 접시 보완은 가장자리 작은 빈틈만 보완한다. 가중치가 없거나 추론이 실패하면 기존 SAM + 기하학 보완 경로로 안전하게 되돌아가므로 네이버 채널 이미지 보정 요청이 모델 파일 부재 때문에 중단되지 않는다.
