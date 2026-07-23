# GroundingDINO·SAM 2 기반 접시/음식 자동 주석과 CVAT 검수

## 목표

500장의 실제 음식 사진에 `plate_full`과 `food_visible` 인스턴스 마스크를 처음부터 손으로 그리지 않는다. GroundingDINO가 접시·음식 후보 상자를 찾고, 프로젝트의 SAM 2.1 Small이 상자 안의 초안 마스크를 만든다. 사용자는 CVAT에서 **틀린 경계, 누락, 클래스만 검수**한다.

`plate_full`은 음식에 가려진 가운데까지 포함한 접시 전체 외곽이고, `food_visible`은 화면에 실제로 보이는 음식만이다. 두 마스크의 겹침은 의도된 정상 동작이다.

## 생성물

자동 주석 실행 뒤 아래 파일이 생긴다.

- `data/training/plate_segmentation/auto_annotations/instances_draft.json`: CVAT에 올릴 COCO Instances 초안
- `data/training/plate_segmentation/auto_annotations/review_previews/`: 주황색 접시·초록색 음식 경계를 겹쳐 그린 빠른 검수용 이미지
- `data/training/plate_segmentation/auto_annotations/draft_summary.json`: 성공·검수 필요·실패 수
- `data/training/plate_segmentation/plate_annotation_manifest.csv`: 각 이미지의 자동 주석 상태

원본 `cvat_images`와 파일명은 바꾸지 않는다. CVAT에서 JSON의 `file_name`이 원본 업로드 파일명과 같아야 한다.

## 로컬 실행

프로젝트 루트에서 다음을 실행한다. `requirements-local.txt`에는 Transformers 기반 GroundingDINO 실행에 필요한 `transformers`, `torch`, `Pillow`과 COCO 처리를 위한 `pycocotools`가 들어 있다.

```powershell
pip install -r requirements-local.txt
python -m scripts.generate_plate_segmentation_drafts --overwrite
```

처음 실행하면 `IDEA-Research/grounding-dino-tiny`와 SAM 가중치를 내려받거나 로컬 캐시에서 읽는다. CUDA GPU가 있으면 자동 사용한다. GPU가 없다면 가능은 하지만 500장 작업은 매우 오래 걸리므로 권장하지 않는다.

원본 GroundingDINO 저장소를 직접 설치하거나 CUDA 확장을 컴파일할 필요는 없다. 이 프로젝트는 Transformers 어댑터를 사용해 로컬·Colab 의존성 충돌을 줄인다. 또한 기존 Ultralytics SAM 2.1 Small 어댑터를 그대로 사용하므로 별도의 Meta SAM 2 저장소 설치로 PyTorch를 교체하지 않는다.

## Google Colab 실행

1. 런타임 유형을 GPU로 바꾸고 `notebooks/08_colab_grounded_sam2_cvat_review.ipynb`를 연다.
2. 노트북 첫 셀에서 프로젝트 경로를 실제 Drive 경로로 확인한다.
3. 의존성 설치 셀을 한 번 실행하고 런타임을 다시 시작하지 않는다.
4. 작업 목록 셀을 먼저 실행한다. 이 셀은 `plate_annotation_manifest.csv`와 정확히 500장의 `cvat_images`를 확인한다. 이전에 53장처럼 불완전하게 만든 폴더가 남아 있다면, 먼저 백업한 뒤 셀의 `RESET_PLATE_WORKSPACE=True`를 명시적으로 설정한다.
5. 자동 주석 생성 셀을 실행한다. 모델의 첫 다운로드에는 시간이 걸리지만, 다음 실행에서는 Drive의 모델 캐시를 재사용한다.
6. 생성된 `instances_draft.json`과 `review_previews`를 Drive에서 내려받아 CVAT에 올린다.

Colab에서 실패한 이미지가 있더라도 전체 작업이 중단되지 않는다. `draft_summary.json`의 `failed`, `needs_manual_annotation` 수를 먼저 확인하고 해당 파일만 별도로 보정한다.

## CVAT 처음 사용하기

### 1. 프로젝트와 라벨 만들기

1. CVAT에 로그인한 뒤 **Projects**에서 새 프로젝트를 만든다.
2. 라벨을 두 개 추가한다.
   - `plate_full`: 접시 전체 외곽. 음식으로 가린 접시 안쪽도 포함한다.
   - `food_visible`: 사진에서 실제로 보이는 음식만 포함한다.
3. 라벨은 인스턴스 단위로 사용한다. 속성은 처음에는 추가하지 않아도 된다.

### 2. 이미지와 자동 초안 올리기

1. 프로젝트 안에서 새 Task를 만들고 `data/training/plate_segmentation/cvat_images`의 이미지 500장을 업로드한다.
2. Task가 열리면 **Actions / Upload annotations** 메뉴를 찾아 형식으로 `COCO 1.0` 또는 화면에 표시되는 동등한 COCO Instances 형식을 고른다.
3. `auto_annotations/instances_draft.json`을 올린다.
4. 이미지가 표시되면 한 장에서 주황색·초록색 객체가 보이는지 먼저 확인한다. 보이지 않으면 파일명 불일치 또는 COCO 형식 선택 오류를 먼저 해결한다.

CVAT 화면의 메뉴 이름은 서비스 버전에 따라 조금 다를 수 있지만, 핵심은 **이미지를 먼저 올리고, 같은 Task에 COCO 인스턴스 주석을 가져오는 것**이다.

### 3. 검수 규칙

한 장마다 새로 그리는 대신, 이미 만들어진 폴리곤을 다음 기준으로 고친다.

- 접시 외곽이 끊겼으면 `plate_full` 폴리곤의 바깥 테두리만 연결한다. 음식에 가린 접시 중앙은 포함한다.
- 식탁보·테이블·그림자는 `plate_full`에서 제외한다.
- 빵·반찬 등 보이는 음식만 `food_visible`에 남긴다. 접시 무늬·테두리는 넣지 않는다.
- 접시가 없거나 외곽을 판단할 수 없으면 억지로 학습 라벨을 만들지 말고 해당 이미지를 제외 대상으로 기록한다.

`review_previews`를 옆에 열어두면 자동 결과가 불안정한 이미지를 먼저 고를 수 있다. 특히 `needs_manual_annotation`과 `failed` 이미지만 추가 작업하면 되므로 500장을 처음부터 전부 그릴 필요가 없다.

### 4. 검수본 내보내기와 학습 준비

1. 검수가 끝난 Task에서 **Export annotations**를 선택하고 COCO Instances 형식으로 내보낸다.
2. 결과 JSON을 `data/training/plate_segmentation/annotations/instances_reviewed.json`으로 저장한다.
3. 아래 명령으로 두 클래스가 모두 있는 이미지의 상태를 자동으로 `completed` 처리한다.

```powershell
python -m scripts.mark_plate_annotation_reviewed `
  --coco-json data/training/plate_segmentation/annotations/instances_reviewed.json
```

4. 이어서 YOLO 분할 형식으로 변환하고 학습한다.

```powershell
python -m scripts.prepare_plate_segmentation_dataset `
  --coco-json data/training/plate_segmentation/annotations/instances_reviewed.json
python -m scripts.train_yolo11n_plate_segmenter --epochs 100 --imgsz 1024
python -m scripts.evaluate_yolo11n_plate_segmenter `
  --weights runs/plate_segmenter/yolo11n_plate_seg_v1/weights/best.pt
```

## 운영 파이프라인 적용

평가가 끝난 `best.pt`를 `models/yolo11n_plate_seg.pt`에 두고 `configs/pipeline.yaml`의 `models.plate_segmenter.enabled`를 `true`로 바꾼다. 이 모델은 `plate_full`과 `food_visible`을 따로 예측하고 둘을 합친 보호 마스크를 배경 교체 전경으로 사용한다. 그래서 음식이 접시 중앙을 가려도 접시 외곽을 보존하는 것이 목표다.

## 조명·색감 조화 정책

운영 파이프라인은 현재 원본 전경을 보존하기 위해 제한된 밝기·대비·채도 조화만 적용한다. Harmonizer 저장소는 연구 참고용으로는 유용하지만 비상업용 라이선스이므로, 네이버 광고 결과물에 외부 가중치를 그대로 적용하지 않는다. 상업 사용 권한을 별도로 확보하기 전에는 현재의 제한 조화 방식을 유지한다.
