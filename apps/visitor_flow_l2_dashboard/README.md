# Visitor Flow L2 Dashboard

C0241 8개 CCTV clip의 L2-1 집계 산출물을 읽어 시간대별 보행 관측량과 화면 grid heatmap을 보여주는 Streamlit POC입니다. YOLO bbox 검증 영상도 재생할 수 있습니다.

이 화면은 YOLO를 다시 실행하지 않습니다. 입력은 이미 생성된 L2-1 artifact와 오프라인으로 생성한 preview video입니다.

```text
outputs/visitor_flow_mvp/c0241_20210802_l2_1/
├─ events.parquet
├─ summary.parquet
├─ analysis.json
├─ dashboard_summary.csv
└─ preview_videos/
   └─ *_yolo_conf_0p50.webm
```

## 연속 YOLO 검증 영상 생성

먼저 peak 시간대인 12:51 clip에서 관측량이 많은 60~120초 검증 영상을 생성합니다. `--start-sec`는 원본 clip 안에서 렌더링을 시작할 초 단위 위치이고, `--max-seconds 60`은 60초만 preview로 저장한다는 뜻입니다.

```bash
# [Design Intent] L2-1과 같은 conf=0.50을 사용하되 모든 연속 frame에 bbox/grid를 그려 사람이 탐지 품질을 직접 감사한다.
/home/imella0707/miniconda3/envs/ssakda/bin/python scripts/visitor_flow_l2_render_preview.py \
  --video data/curated/aihub_cctv_visitor_flow/v1/c0241_20210802/videos/2021-08-02_12-51-00_mon_sunny_out_ju-ja_C0241.mp4 \
  --model /home/imella0707/yolo11s.pt \
  --device 0 \
  --imgsz 960 \
  --conf 0.50 \
  --grid-cols 6 \
  --grid-rows 4 \
  --start-sec 60 \
  --max-seconds 60 \
  --output outputs/visitor_flow_mvp/c0241_20210802_l2_1/preview_videos/2021-08-02_12-51-00_mon_sunny_out_ju-ja_C0241_yolo_conf_0p50_start_60s.webm
```

이 preview는 정성적(qualitative) 시각 검증 artifact입니다. 모든 연속 frame을 추론하므로, 10초 간격으로 18장씩 sampling한 L2-1 집계 수치와 직접 합산하거나 비교하면 안 됩니다.

## 실행

저장소 루트에서 실행합니다.

```bash
# [Design Intent] L2-2 대시보드 실행에 필요한 Streamlit/Pandas/PyArrow 의존성을 설치한다.
/home/imella0707/miniconda3/envs/ssakda/bin/python -m pip install -r apps/visitor_flow_l2_dashboard/requirements.txt

# [Design Intent] L2-1 artifact를 읽어 시간대 chart와 grid heatmap을 표시한다.
/home/imella0707/miniconda3/envs/ssakda/bin/python -m streamlit run apps/visitor_flow_l2_dashboard/app.py
```

브라우저가 자동으로 열리지 않으면 터미널에 표시되는 `http://localhost:8501` 또는 `http://localhost:8502` 주소로 접속합니다.

## 현재 화면에서 확인할 수 있는 것

- 가장 붐빈 시간대
- 시간대별 보행 관측량
- 가장 많이 보인 화면 구역
- 시간대별 전체 보행 관측량
- 실제 영상에서 노란 `6x4` grid 기준 확인
- 전체 시간대 또는 선택 시간대의 화면 구역별 밀집도
- 마케팅 후보 해석
- 검증용 YOLO bbox/grid 영상
- 개발/검증용 `analysis.json`, `summary.parquet`, `events.parquet` 원본 확인

## 해석 제한

- 표시 값은 보행 관측량입니다.
- 같은 사람이 여러 sampled frame에 나오면 여러 건으로 집계됩니다.
- tracking을 하지 않았으므로 순방문자 수가 아닙니다.
- 화면 grid는 실제 지면 좌표가 아니라 CCTV 화면상의 상대 구역입니다.
- 히트맵 색상은 관측량의 상대 강도입니다. 연노랑은 적음, 주황은 중간, 진한 빨강은 많음을 뜻합니다.
- 시간대 목록은 임의 선택값이 아니라 AIHub C0241 폴더에 있는 영상 시작 시각을 1시간 단위로 묶은 결과입니다.
- marketing signal은 dashboard validation용 rule-based hypothesis이며 매출 상승 검증 결과가 아닙니다.
- preview 영상의 bbox는 tracking ID가 아닙니다.
- 노란 매장 전면 ROI와 `In front of shop` 카운트는 L2-3에서 별도로 구현합니다.
