# aihub_cctv_visitor_flow v1 Description

## Summary

`aihub_cctv_visitor_flow` v1은 AIHub `유동 인구 분석을 위한 CCTV 영상 데이터`에서 1차 visitor-flow MVP 테스트를 위해 선별한 curated sample입니다.

현재 v1은 전체 AIHub 원천 데이터셋이 아닙니다. TOM N TOMS COFFEE 매장 전면으로 확인한 `C0241` 카메라의 `2021-08-02` 영상 중 오전/오후/저녁/야간을 포함하는 8개 mp4/json 쌍만 선별한 기능 확인용 smoke sample입니다.

이 데이터셋의 목적은 실제 매장 방문자 수나 구매 전환을 증명하는 것이 아니라, 매장 앞 CCTV 영상/라벨에서 시간대별 사람 관측 밀도와 grid heatmap을 만들 수 있는지 검증하는 것입니다.

## Dataset Stage

- 판단 단계: `curated`
- 상태: `experimental`
- artifact role: `smoke_sample`
- 담당자: `Sujin`
- 생성일: `2026-07-19`
- 판단 근거: 팀 규칙상 raw는 AIHub 원천 전체를 의미합니다. 이번 v1은 AIHub 전체 raw가 아니라 Validation `ju-ja` 파일을 받은 뒤 다시 `C0241`, `2021-08-02`, TOM N TOMS COFFEE 매장 전면 장면만 선별한 subset이므로 curated 단계로 분류합니다.

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
- raw GCS 정책: 전체 AIHub 원천은 공식 URL/file key로 재확보 가능하므로 현재 GCS에 올리지 않습니다. `Validation ju-ja`처럼 일부만 받은 파일도 팀 규칙상 raw 공식 artifact로 포장하지 않고, 프로젝트 목적에 맞게 선별한 subset부터 curated로 문서화합니다.
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

  processed/
    aihub_cctv_visitor_flow/
      v1/
        c0241_20210802_label_smoke/
          analysis.json
          summary.csv
          bucket_summary.csv
          grid_heatmap.csv
```

현재 v1 문서의 공식 artifact root는 curated sample 기준으로 아래 경로를 우선 사용합니다.

```text
gs://ssakda/projects/brandmate/data/curated/aihub_cctv_visitor_flow/v1/c0241_20210802/
```

전체 Validation `ju-ja` selected source subset은 아래 curated artifact로 둡니다.

```text
gs://ssakda/projects/brandmate/data/curated/aihub_cctv_visitor_flow/v1/ju_ja_validation_selected/
```

label smoke test 산출물은 processed artifact로 분리합니다.

```text
gs://ssakda/projects/brandmate/data/processed/aihub_cctv_visitor_flow/v1/c0241_20210802_label_smoke/
```

## Local Path Mapping

주의: 아래 `data/local/.../raw/`는 로컬 압축 해제 폴더 이름일 뿐, 팀 데이터 단계의 `raw`가 아닙니다. 팀 규칙상 raw는 AIHub 489 전체 원천 데이터셋을 의미합니다.

| 현재 로컬 경로 | 데이터 단계 판단 | 추천 GCS/표준 경로 | 파일 역할 |
| --- | --- | --- | --- |
| `data/local/aihub_cctv_visitor_flow/ju_ja_validation/154.유동_인구_분석을_위한_CCTV_영상_데이터/01.데이터/2.Validation/원천데이터/VS3_ju-ja.zip` | selected source download | GCS 업로드 대상 아님. AIHub URL/file key로 재확보 | AIHub Validation ju-ja 원천 영상 zip |
| `data/local/aihub_cctv_visitor_flow/ju_ja_validation/154.유동_인구_분석을_위한_CCTV_영상_데이터/01.데이터/2.Validation/라벨링데이터_1107_add/VL3_ju-ja.zip` | selected source download | GCS 업로드 대상 아님. AIHub URL/file key로 재확보 | AIHub Validation ju-ja 라벨 zip |
| `data/local/aihub_cctv_visitor_flow/ju_ja_validation/raw/` | local extracted videos, not dataset raw | `data/curated/aihub_cctv_visitor_flow/v1/ju_ja_validation_selected/videos/` | 압축 해제된 Validation ju-ja 영상 132개를 curated source subset으로 복사 |
| `data/local/aihub_cctv_visitor_flow/ju_ja_validation/labels/` | local extracted labels, not dataset raw | `data/curated/aihub_cctv_visitor_flow/v1/ju_ja_validation_selected/labels/` | 압축 해제된 Validation ju-ja 라벨 132개를 curated source subset으로 복사 |
| `data/local/visitor_flow_mvp/samples/c0241_20210802/raw/` | curated MVP sample input | `data/curated/aihub_cctv_visitor_flow/v1/c0241_20210802/videos/` | 1차 MVP용 C0241 mp4 8개. 표준 경로에서는 `raw/` 대신 `videos/` 사용 |
| `data/local/visitor_flow_mvp/samples/c0241_20210802/labels/` | curated MVP sample input | `data/curated/aihub_cctv_visitor_flow/v1/c0241_20210802/labels/` | 1차 MVP용 C0241 json 8개 |
| `outputs/visitor_flow_mvp/c0241_20210802_label_smoke/` | processed | `gs://ssakda/projects/brandmate/data/processed/aihub_cctv_visitor_flow/v1/c0241_20210802_label_smoke/` | 라벨 기반 smoke test 산출물 |

## Files

Curated source subset:

| 파일/폴더 | 확인된 개수/크기 | 역할 |
| --- | ---: | --- |
| `ju_ja_validation_selected/videos/**/*.mp4` | 132 files | Validation ju-ja selected source videos |
| `ju_ja_validation_selected/labels/**/*.json` | 132 files | Validation ju-ja selected source labels |
| 전체 source subset | 약 8.1 GB | C0241 외 다른 카메라/날짜 후보를 다시 선별하기 위한 curated source pool |

Curated sample:

| 파일/폴더 | 확인된 개수/크기 | 역할 |
| --- | ---: | --- |
| `videos/*.mp4` | 8 files | C0241 카메라의 2021-08-02 시간대별 원천 영상. 현재 로컬 폴더명은 `raw/`이지만 GCS 표준 경로에서는 `videos/`로 둡니다 |
| `labels/*.json` | 8 files | 같은 stem을 가진 AIHub person bbox 라벨 |
| 전체 curated sample | 약 639 MB | 1차 MVP 개발용 local sample |

Processed smoke test output:

| 파일 | 역할 |
| --- | --- |
| `analysis.json` | label smoke test 요약 결과 |
| `summary.csv` | clip 단위 person count, annotation row, store event 요약 |
| `bucket_summary.csv` | morning/afternoon/evening/night 시간대별 요약 |
| `grid_heatmap.csv` | bbox bottom-center 기반 grid cell count |

## Selected Clips

| time bucket | file stem |
| --- | --- |
| morning | `2021-08-02_09-21-00_mon_sunny_out_ju-ja_C0241` |
| morning | `2021-08-02_11-39-00_mon_sunny_out_ju-ja_C0241` |
| afternoon | `2021-08-02_12-51-00_mon_sunny_out_ju-ja_C0241` |
| evening | `2021-08-02_17-09-00_mon_sunny_out_ju-ja_C0241` |
| evening | `2021-08-02_17-51-00_mon_sunny_out_ju-ja_C0241` |
| evening | `2021-08-02_19-24-00_mon_sunny_out_ju-ja_C0241` |
| night | `2021-08-02_21-03-00_mon_sunny_out_ju-ja_C0241` |
| night | `2021-08-02_22-15-00_mon_sunny_out_ju-ja_C0241` |

## Curation

- 선별 개수: 8 mp4/json pairs
- 카메라 ID: `C0241`
- 날짜: `2021-08-02`
- 요일: `mon`
- 날씨: `sunny`
- 장소 맥락: TOM N TOMS COFFEE 매장 전면 골목 CCTV

선별 기준:

- 같은 카메라 ID를 사용해 장소 변수를 고정합니다.
- 같은 날짜를 사용해 요일/날씨 변수를 고정합니다.
- 오전/오후/저녁/야간을 포함해 시간대별 비교가 가능하게 합니다.
- mp4와 json stem이 1:1로 매칭되는 파일만 사용합니다.
- 차량/성별/연령 분석이 아니라 person bbox 기반 보행자 관측 밀도만 사용합니다.

## Processing

현재 실행한 smoke test는 YOLO 추론이 아니라 AIHub 라벨 기반 집계입니다.

실행 스크립트:

```text
scripts/archive/visitor_flow/L0/visitor_flow_label_smoke_test.py
```

입력:

```text
data/local/visitor_flow_mvp/samples/c0241_20210802/
```

출력:

```text
outputs/visitor_flow_mvp/c0241_20210802_label_smoke/
```

처리 단계:

- json label 파일 로드
- 파일명에서 date/time/day/weather/camera_id 파싱
- `video.total_person`, unique person id, annotation row count 집계
- bbox bottom-center를 3x3 grid cell로 변환
- morning/afternoon/evening/night bucket summary 생성
- `analysis.json`, `summary.csv`, `bucket_summary.csv`, `grid_heatmap.csv` 저장

## Smoke Test Result

라벨 기반 1차 테스트 결과:

| time_bucket | clip_count | total_person | avg_total_person_per_clip | max_persons_per_frame | store_event_count |
| --- | ---: | ---: | ---: | ---: | ---: |
| morning | 2 | 38 | 19.000 | 6 | 10 |
| afternoon | 1 | 33 | 33.000 | 9 | 6 |
| evening | 3 | 53 | 17.667 | 7 | 4 |
| night | 2 | 38 | 19.000 | 8 | 8 |

주의: 오후 bucket은 clip이 1개뿐입니다. 따라서 `afternoon`이 가장 높다는 결과는 strong claim이 아니라 smoke-test sample 기준 관측 결과로만 사용합니다.

## Allowed and Forbidden Claims

Allowed:

- 시간대별 사람 관측 밀도
- grid heatmap 기반 보행 구역 분포
- TOM N TOMS 전면 보행 흐름 smoke test
- 운영/프로모션 타이밍 힌트

Forbidden:

- 실제 TOM N TOMS 방문자 수
- 구매 전환율
- 매출 예측
- 고객 신원 식별
- 성별/연령 기반 타겟팅
- CCTV 기반 개인 추적

## Storage and DVC

- Git에 실제 mp4/json 데이터 파일은 올리지 않습니다.
- 현재 `data/local/...` 경로는 로컬 실험용입니다.
- GCS 업로드는 아직 하지 않았습니다.
- DVC 등록은 아직 하지 않았습니다.
- 현재 팀프로젝트 기준에서는 공식 processed 산출물이 안정화된 뒤 DVC 등록 여부를 판단합니다.

## Reproducibility

재현 조건:

- AIHub dataset key `489` 접근 권한
- AIHub file key `65983`, `65995`
- AIHub downloader `aihubshell`
- 압축 해제된 Validation `ju-ja` 원천/라벨
- `scripts/archive/visitor_flow/L0/visitor_flow_label_smoke_test.py`

### 1. AIHub downloader 준비

`aihubshell`은 데이터가 아니라 로컬 다운로드 도구입니다. Git/curated/GCS에 넣지 않습니다.

```bash
# [Design Intent] Keep the AIHub downloader as a local-only acquisition tool, not as a versioned dataset artifact.
mkdir -p data/local/aihub_tools
curl -L -o data/local/aihub_tools/aihubshell https://api.aihub.or.kr/api/aihubshell.do
chmod +x data/local/aihub_tools/aihubshell
```

### 2. AIHub Validation ju-ja 파일 다운로드

사용한 file key:

| 파일 | file key | 역할 |
| --- | ---: | --- |
| `VS3_ju-ja.zip` | `65983` | Validation ju-ja 원천 영상 |
| `VL3_ju-ja.zip` | `65995` | Validation ju-ja 라벨링 데이터 |

다운로드 명령:

```bash
# [Design Intent] Reacquire only the selected AIHub Validation ju-ja source files needed to rebuild this curated MVP dataset.
mkdir -p data/local/aihub_cctv_visitor_flow/ju_ja_validation
cd data/local/aihub_cctv_visitor_flow/ju_ja_validation
../../aihub_tools/aihubshell \
  -mode d \
  -datasetkey 489 \
  -filekey 65983,65995 \
  -aihubapikey "$AIHUB_API_KEY"
```

주의: 실제 API key를 문서나 Git에 쓰지 않습니다. 로컬 shell 환경변수 `AIHUB_API_KEY`로 주입합니다.

### 3. 압축 해제

다운로드한 zip은 중간 로컬 작업 폴더에 따로 풀지 않습니다. 현재 사용하는 표준 curated artifact의 `videos/`, `labels/` 경로에 바로 압축 해제합니다.

```bash
# [Design Intent] Extract the selected AIHub source files directly into the standard curated layout without maintaining obsolete local working copies.
mkdir -p data/curated/aihub_cctv_visitor_flow/v1/ju_ja_validation_selected/videos
mkdir -p data/curated/aihub_cctv_visitor_flow/v1/ju_ja_validation_selected/labels

python -m zipfile -e \
  "data/local/aihub_cctv_visitor_flow/ju_ja_validation/154.유동_인구_분석을_위한_CCTV_영상_데이터/01.데이터/2.Validation/원천데이터/VS3_ju-ja.zip" \
  data/curated/aihub_cctv_visitor_flow/v1/ju_ja_validation_selected/videos

python -m zipfile -e \
  "data/local/aihub_cctv_visitor_flow/ju_ja_validation/154.유동_인구_분석을_위한_CCTV_영상_데이터/01.데이터/2.Validation/라벨링데이터_1107_add/VL3_ju-ja.zip" \
  data/curated/aihub_cctv_visitor_flow/v1/ju_ja_validation_selected/labels
```

### 4. 표준 curated 경로

압축 해제한 selected source와 여기서 선별한 C0241 sample은 아래 표준 curated 경로를 현재 v1의 기준으로 사용합니다.

```text
data/curated/aihub_cctv_visitor_flow/v1/
  ju_ja_validation_selected/
    videos/
    labels/

  c0241_20210802/
    videos/
    labels/
```

재실행 예시:

```bash
# [Design Intent] Rebuild the current label-based smoke-test outputs from the selected C0241 MVP sample.
python scripts/archive/visitor_flow/L0/visitor_flow_label_smoke_test.py \
  --sample-dir data/curated/aihub_cctv_visitor_flow/v1/c0241_20210802 \
  --output-dir outputs/visitor_flow_mvp/c0241_20210802_label_smoke
```

## Limitations

- 현재 결과는 AIHub 라벨 기반 smoke test입니다. YOLO 모델 추론 결과가 아닙니다.
- 오후 시간대 sample이 1개뿐이라 시간대별 결론을 강하게 주장하면 안 됩니다.
- 실제 매장 입장 여부는 event label의 `store_in/store_out`으로도 제한적으로만 참고해야 합니다.
- 구매 전환, 매출, 재방문, 고객 성별/연령 타겟팅은 1차 MVP 범위가 아닙니다.
- 전체 AIHub raw는 공식 URL과 file key로 재확보 가능하므로 현재는 GCS 업로드하지 않습니다.
- 일부만 받은 `Validation ju-ja` zip도 raw 공식 artifact로 등록하지 않습니다. 프로젝트 목적에 맞게 선별한 `C0241 + 2021-08-02` subset부터 curated artifact로 관리합니다.

## Next Version Plan

- v2: 같은 C0241 카메라에서 여러 날짜를 추가해 평일/주말 또는 요일별 차이를 비교합니다.
- v2: YOLO person detection 결과를 생성하고 AIHub label count와 sanity check합니다.
- v3: 상가정보/주변 업종 데이터를 붙여 CCTV 피크를 상권 맥락으로 해석합니다.
- v4: BrandMate 광고 카피 생성에 `visitor_flow_context`를 연결합니다.

## TODO

- GCS bucket/prefix 최종 확정
- curated sample 실제 byte size 기록
- YOLO 기반 processed output 생성 후 manifest 갱신
- DVC 추적 여부 결정
