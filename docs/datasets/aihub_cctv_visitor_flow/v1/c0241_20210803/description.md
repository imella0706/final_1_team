# aihub_cctv_visitor_flow v1 c0241_20210803 Description

## Summary

`c0241_20210803`은 AIHub `유동 인구 분석을 위한 CCTV 영상 데이터`에서 visitor-flow MVP의 날짜 검증/비교를 위해 선별한 curated evaluation subset입니다.

이 subset은 전체 AIHub 원천 데이터셋이 아닙니다. Validation `ju-ja` 파일에서 TOM N TOMS COFFEE 매장 전면으로 확인한 `C0241` 카메라의 `2021-08-03` 영상 중 mp4/json stem이 1:1로 맞는 7개 쌍만 분리한 데이터입니다.

주 실험/대시보드 기준은 `c0241_20210802`입니다. `c0241_20210803`은 8월 2일에서 고른 YOLO confidence threshold와 모델 설정이 다른 날짜에서도 유지되는지 확인하고, L2-4에서 날짜 비교용으로 쓰기 위한 보조 검증셋입니다.

## Dataset Stage

- 판단 단계: `curated`
- 상태: `experimental`
- artifact role: `eval_subset`
- 담당자: `Sujin`
- 생성일: `2026-07-22`
- 판단 근거: 팀 규칙상 raw는 AIHub 489 전체 원천을 의미합니다. 이 폴더는 전체 raw가 아니라 Validation `ju-ja` source pool에서 `C0241`, `2021-08-03` 조건으로 다시 선별한 프로젝트 목적 subset이므로 curated 단계로 분류합니다.

## Source

- 원본 제공처: `AIHub`
- 원본 데이터셋 ID: `489`
- 원본 데이터셋 이름: `유동 인구 분석을 위한 CCTV 영상 데이터`
- 원본 URL: `https://aihub.or.kr/aihubdata/data/view.do?dataSetSn=489`
- AIHub downloader URL: `https://api.aihub.or.kr/api/aihubshell.do`
- raw scope: AIHub dataset 489 전체 원천 데이터셋
- selected source scope: `Validation ju-ja` 파일만 로컬 다운로드
- 다운로드 파일:
  - `VS3_ju-ja.zip`, key `65983`, 원천 영상
  - `VL3_ju-ja.zip`, key `65995`, 라벨링 데이터
- raw 원본 전체 GCS 업로드 여부: `False`
- annotation/label 보존 여부: `True`

## GCS Folder Structure Draft

지금 당장 GCS 업로드나 DVC 등록은 하지 않습니다. 다만 팀 공통 규칙에 맞춰 향후 업로드할 표준 경로를 미리 고정합니다.

```text
gs://ssakda/projects/brandmate/data/
  curated/
    aihub_cctv_visitor_flow/
      v1/
        ju_ja_validation_selected/
          videos/
            dawn_0_9/
            morning_9_12/
            afternoon_12_16/
            evening_16_20/
            night_20_24/
          labels/
            dawn_0_9/
            morning_9_12/
            afternoon_12_16/
            evening_16_20/
            night_20_24/

        c0241_20210802/
          videos/
            *.mp4
          labels/
            *.json

        c0241_20210803/
          videos/
            *.mp4
          labels/
            *.json
```

현재 문서의 공식 artifact root는 curated evaluation subset 기준으로 아래 경로를 우선 사용합니다.

```text
gs://ssakda/projects/brandmate/data/curated/aihub_cctv_visitor_flow/v1/c0241_20210803/
```

## Local Path Mapping

주의: `data/local/.../raw/`는 로컬 압축 해제 폴더 이름일 뿐, 팀 데이터 단계의 `raw`가 아닙니다. 팀 규칙상 raw는 AIHub 489 전체 원천 데이터셋을 의미합니다.

| 현재 로컬 경로 | 데이터 단계 판단 | 추천 GCS/표준 경로 | 파일 역할 |
| --- | --- | --- | --- |
| `data/curated/aihub_cctv_visitor_flow/v1/ju_ja_validation_selected/` | curated source pool | `gs://ssakda/projects/brandmate/data/curated/aihub_cctv_visitor_flow/v1/ju_ja_validation_selected/` | Validation ju-ja에서 재선별할 수 있는 source pool |
| `data/curated/aihub_cctv_visitor_flow/v1/c0241_20210803/videos/` | curated eval subset | `gs://ssakda/projects/brandmate/data/curated/aihub_cctv_visitor_flow/v1/c0241_20210803/videos/` | C0241 2021-08-03 mp4 7개 |
| `data/curated/aihub_cctv_visitor_flow/v1/c0241_20210803/labels/` | curated eval subset | `gs://ssakda/projects/brandmate/data/curated/aihub_cctv_visitor_flow/v1/c0241_20210803/labels/` | 같은 stem을 가진 AIHub person bbox 라벨 7개 |

## Files

Curated evaluation subset:

| 파일/폴더 | 확인된 개수/크기 | 역할 |
| --- | ---: | --- |
| `videos/*.mp4` | 7 files | C0241 카메라의 2021-08-03 영상 |
| `labels/*.json` | 7 files | 같은 stem을 가진 AIHub person bbox 라벨 |
| 전체 curated subset | 581,420,216 bytes / `555M` du | L2-3 threshold 검증 및 L2-4 날짜 비교용 입력 |

## Selected Clips

| time bucket | file stem |
| --- | --- |
| morning | `2021-08-03_09-12-00_tue_sunny_out_ju-ja_C0241` |
| morning | `2021-08-03_09-39-00_tue_sunny_out_ju-ja_C0241` |
| morning | `2021-08-03_09-51-00_tue_sunny_out_ju-ja_C0241` |
| afternoon | `2021-08-03_13-54-00_tue_sunny_out_ju-ja_C0241` |
| evening | `2021-08-03_17-27-00_tue_sunny_out_ju-ja_C0241` |
| night | `2021-08-03_21-39-00_tue_sunny_out_ju-ja_C0241` |
| night | `2021-08-03_21-51-00_tue_sunny_out_ju-ja_C0241` |

## Curation

- 선별 개수: 7 mp4/json pairs
- 카메라 ID: `C0241`
- 날짜: `2021-08-03`
- 요일: `tue`
- 날씨: `sunny`
- 장소 맥락: TOM N TOMS COFFEE 매장 전면 골목 CCTV

선별 기준:

- 같은 카메라 ID를 사용해 장소 변수를 고정합니다.
- 8월 2일과 다른 날짜를 사용해 threshold 및 모델 설정의 날짜 이동성을 확인합니다.
- mp4와 json stem이 1:1로 매칭되는 파일만 사용합니다.
- 차량/성별/연령 분석이 아니라 person bbox 기반 보행자 관측 밀도만 사용합니다.

한계:

- 8월 3일은 7개 clip이며, 8월 2일의 8개 clip과 개수가 같지 않습니다.
- 시간대가 완전히 균형 잡힌 검증셋은 아닙니다. L2-3b balanced subset에서는 날짜별 6개 clip만 골라 시간대 조건을 맞춥니다.
- 이 subset만으로 `C0241` 전체 날짜 일반화나 실제 매장 방문자 수를 주장하면 안 됩니다.

## Processing

이 subset은 단독 label smoke test용이 아니라 L2 YOLO 설정 검증과 대시보드 날짜 비교 입력으로 사용합니다.

관련 스크립트:

```text
scripts/visitor_flow_yolo_config_compare.py
scripts/visitor_flow_l2_aggregate.py
scripts/visitor_flow_yolo_evaluate.py
```

주요 사용처:

| 단계 | 역할 |
| --- | --- |
| L2-3a | 8월 2일에서 선택한 설정/threshold를 8월 3일에 고정 적용해 성능 유지 여부 확인 |
| L2-3b | 날짜별 6개 clip balanced subset으로 AP/mAP 보조 지표까지 포함해 설정 재검증 |
| L2-4 | Aug 2 중심 dashboard에서 Aug 3를 비교 날짜로 사용 |

## Rebuild From Source

`ju_ja_validation_selected` source pool에서 다시 만들 때는 `C0241`, `2021-08-03`, mp4/json stem 매칭 조건을 지켜야 합니다.

```bash
# [Design Intent] Keep the reusable source pool intact and materialize only the fixed Aug 3 C0241 evaluation subset into the flat curated layout.
mkdir -p data/curated/aihub_cctv_visitor_flow/v1/c0241_20210803/videos
mkdir -p data/curated/aihub_cctv_visitor_flow/v1/c0241_20210803/labels
find data/curated/aihub_cctv_visitor_flow/v1/ju_ja_validation_selected/videos -type f -name '2021-08-03_*_C0241.mp4' -exec cp -t data/curated/aihub_cctv_visitor_flow/v1/c0241_20210803/videos {} +
find data/curated/aihub_cctv_visitor_flow/v1/ju_ja_validation_selected/labels -type f -name '2021-08-03_*_C0241.json' -exec cp -t data/curated/aihub_cctv_visitor_flow/v1/c0241_20210803/labels {} +
```

검증 조건:

```text
video_count = 7
label_count = 7
matched_stem_count = 7
all stems start with 2021-08-03_
all stems end with _C0241
```

## Allowed and Forbidden Claims

Allowed:

- 같은 카메라/매장 맥락의 날짜 비교
- 8월 2일에서 선택한 YOLO confidence threshold의 8월 3일 고정 적용 결과
- 시간대별 사람 관측 밀도
- frame-level person observation metrics

Forbidden:

- 실제 TOM N TOMS 방문자 수
- 구매 전환율
- 매출 예측
- 고객 신원 식별
- 성별/연령 기반 타겟팅
- `C0241` 전체 날짜 또는 다른 매장으로의 일반화

## Storage and DVC

- Git에 실제 mp4/json 데이터 파일은 올리지 않습니다.
- 현재 curated 데이터는 로컬 `data/curated/.../c0241_20210803/`에 있습니다.
- GCS 업로드는 아직 하지 않았습니다.
- DVC 등록은 아직 하지 않았습니다.
- 현재 팀프로젝트 기준에서는 공식 processed 산출물이 안정화된 뒤 DVC 등록 여부를 판단합니다.

## Reproducibility

재현 조건:

- AIHub dataset key `489` 접근 권한
- AIHub file key `65983`, `65995`
- AIHub downloader `aihubshell`
- 압축 해제된 Validation `ju-ja` 원천/라벨 또는 curated source pool `ju_ja_validation_selected`
- `C0241`, `2021-08-03` 조건의 mp4/json stem 매칭

