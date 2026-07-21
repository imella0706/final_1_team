# aihub_cctv_visitor_flow v1 / ju_ja_validation_selected

## Summary

`ju_ja_validation_selected`는 AIHub `유동 인구 분석을 위한 CCTV 영상 데이터` 중 Validation `ju-ja` 파일만 내려받아 표준 curated 구조로 정리한 source pool입니다.

이 artifact는 C0241 전용 MVP sample이 아닙니다. `C0063`, `C0065`, `C0071`, `C0133`, `C0241` 카메라가 섞여 있는 후보 풀입니다. 1차 MVP에서 실제 분석 대상으로 쓰는 `C0241 + 2021-08-02` 8쌍은 별도 artifact인 `c0241_20210802`에 있습니다.

## Dataset Stage

- 판단 단계: `curated`
- 상태: `baseline`
- artifact role: `source_pool`
- 담당자: `Sujin`
- 생성일: `2026-07-19`
- 판단 근거: 팀 규칙상 raw는 AIHub dataset 489 전체 원천 데이터셋입니다. 이 artifact는 전체 AIHub raw가 아니라 Validation `ju-ja` 파일만 선택해 받은 뒤 프로젝트 표준 구조로 정리한 후보 풀이므로 curated로 분류합니다.

## Source

- 원본 제공처: `AIHub`
- 원본 데이터셋 ID: `489`
- 원본 데이터셋 이름: `유동 인구 분석을 위한 CCTV 영상 데이터`
- 원본 URL: `https://aihub.or.kr/aihubdata/data/view.do?dataSetSn=489`
- AIHub downloader URL: `https://api.aihub.or.kr/api/aihubshell.do`
- selected source scope: `Validation ju-ja`
- 다운로드 파일:
  - `VS3_ju-ja.zip`, key `65983`, Validation ju-ja 원천 영상
  - `VL3_ju-ja.zip`, key `65995`, Validation ju-ja 라벨링 데이터

## Files

| 파일/폴더 | 확인된 개수/크기 | 역할 |
| --- | ---: | --- |
| `videos/**/*.mp4` | 132 files | Validation ju-ja 후보 영상 |
| `labels/**/*.json` | 132 files | 같은 stem을 가진 AIHub 라벨 |
| 전체 artifact | 약 8.1 GB | C0241 외 다른 카메라/날짜를 재선별하기 위한 curated source pool |

## Camera Distribution

| camera_id | mp4 | json | 역할 |
| --- | ---: | ---: | --- |
| `C0063` | 9 | 9 | 후보 카메라 |
| `C0065` | 9 | 9 | 후보 카메라 |
| `C0071` | 38 | 38 | 후보 카메라 |
| `C0133` | 13 | 13 | 후보 카메라 |
| `C0241` | 63 | 63 | TOM N TOMS COFFEE 전면으로 확인한 MVP 후보 카메라 |

## Time Bucket Distribution

| standard folder | original AIHub bucket | mp4 | json |
| --- | --- | ---: | ---: |
| `dawn_0_9` | `새벽(0~9)` | 21 | 21 |
| `morning_9_12` | `오전(9~12)` | 31 | 31 |
| `afternoon_12_16` | `오후(12~16)` | 24 | 24 |
| `evening_16_20` | `저녁(16~20)` | 31 | 31 |
| `night_20_24` | `야간(20~24)` | 25 | 25 |

## Date Distribution

| date | mp4 count |
| --- | ---: |
| `2021-08-02` | 38 |
| `2021-08-03` | 22 |
| `2021-08-04` | 19 |
| `2021-08-05` | 16 |
| `2021-08-06` | 7 |
| `2021-08-07` | 13 |
| `2021-08-08` | 2 |
| `2021-08-09` | 6 |
| `2021-08-10` | 9 |

## Standard Layout

```text
data/curated/aihub_cctv_visitor_flow/v1/ju_ja_validation_selected/
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
```

## Relationship to MVP Sample

`ju_ja_validation_selected`는 후보 풀입니다. 이 안에서 아래 조건으로 다시 선별한 8쌍이 1차 MVP sample입니다.

- camera_id: `C0241`
- date: `2021-08-02`
- pair count: 8 mp4/json pairs
- output artifact: `data/curated/aihub_cctv_visitor_flow/v1/c0241_20210802/`

## Reproducibility

### AIHub downloader 준비

`aihubshell`은 로컬 다운로드 도구입니다. Git/curated/GCS artifact에 포함하지 않습니다.

```bash
# [Design Intent] Keep the AIHub downloader as a local-only acquisition tool, not as a versioned dataset artifact.
mkdir -p data/local/aihub_tools
curl -L -o data/local/aihub_tools/aihubshell https://api.aihub.or.kr/api/aihubshell.do
chmod +x data/local/aihub_tools/aihubshell
```

### Validation ju-ja 다운로드

```bash
# [Design Intent] Reacquire only the selected AIHub Validation ju-ja source files needed to rebuild this curated source pool.
mkdir -p data/local/aihub_cctv_visitor_flow/ju_ja_validation
cd data/local/aihub_cctv_visitor_flow/ju_ja_validation
../../aihub_tools/aihubshell \
  -mode d \
  -datasetkey 489 \
  -filekey 65983,65995 \
  -aihubapikey "$AIHUB_API_KEY"
```

실제 API key는 문서나 Git에 쓰지 않습니다.

## Allowed and Forbidden Claims

Allowed:

- Validation ju-ja 후보 풀의 카메라/날짜/시간대 분포
- mp4/json pair 매칭 여부
- 특정 MVP sample을 고르기 위한 후보 pool

Forbidden:

- 전체 AIHub dataset 489를 대표한다는 주장
- 특정 매장 방문자 수
- 구매 전환율
- 고객 신원 식별
- 성별/연령 기반 타겟팅

## Notes

- 이 artifact의 폴더명에는 `raw`를 사용하지 않습니다.
- 로컬 압축 해제 과정에서 사용한 임시 폴더명이 있더라도, 표준 curated artifact에서는 `videos/`, `labels/`만 사용합니다.
- 표준 curated artifact의 하위 폴더명은 shell/GCS/code 호환성을 위해 ASCII snake case만 사용합니다.
