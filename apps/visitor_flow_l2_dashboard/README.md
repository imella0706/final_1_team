# Visitor Flow L2/L3 Dashboard

C0241 Aug 2 8 clips와 Aug 3 7 clips의 L2-4 집계, L3-1 수동 ROI 산출물, L3-2 개인정보 보호 미디어를 읽어 시간대별 frame-normalized 보행 관측량, 매장 전면 ROI 관측, 화면 기준 `6x4` 관측 분포를 보여주는 Streamlit POC입니다. 운영자 화면에서도 기본 시각자료는 마스킹 처리된 L3-2 JPG/WebM을 표시합니다.

이 화면은 YOLO를 다시 실행하지 않습니다. 입력은 L2-3a GPU prediction을 재사용해 만든 L2-4 artifact, 이를 CPU 후처리한 L3-1 ROI artifact, L3-2 privacy media, 오프라인 preview입니다.

```text
outputs/visitor_flow_mvp/c0241_20210802_20210803_l2_4/
├─ events.parquet
├─ frames.parquet
├─ summary.parquet
├─ analysis.json
├─ dashboard_summary.csv
└─ preview_videos/
   └─ *_yolo_conf_0p50.webm

outputs/visitor_flow_mvp/c0241_20210802_20210803_l3_1_roi/
├─ roi_config.json
├─ roi_events.parquet
├─ roi_frames.parquet
├─ roi_summary.parquet
├─ roi_dashboard_summary.csv
├─ roi_analysis.json
├─ previews/
│  └─ roi_overlay_preview.jpg
└─ preview_videos/
   └─ *_yolo_conf_0p50_roi_*.webm

outputs/visitor_flow_mvp/c0241_20210802_20210803_l3_2_privacy_media/
├─ images/
│  └─ roi_overlay_preview_masked.jpg
├─ media/
│  └─ roi_preview_masked.webm
└─ qa/
   └─ masking_qa_summary.json
```

## L2-4 artifact 생성

L2-4는 L2-3a의 최종 설정인 `YOLO11s / imgsz=960 / conf=0.50` prediction 결과를 재사용합니다. 따라서 아래 명령은 YOLO 재추론이 아니라 `prediction_candidates.csv`와 `frame_error_summary.csv`를 읽어 `frames.parquet`, `summary.parquet`, `dashboard_summary.csv`를 만드는 집계 단계입니다.

```bash
# [Design Intent] L2-3a GPU prediction을 재사용해 0명 frame 포함 프레임 정규화 지표를 만든다.
/home/imella0707/miniconda3/envs/ssakda/bin/python scripts/visitor_flow_l2_aggregate.py \
  --from-evaluation-dir outputs/visitor_flow_mvp/c0241_20210802_20210803_yolo_l2_3/configs/yolo11s_imgsz960/calibration_2021-08-02/clips \
  --from-evaluation-dir outputs/visitor_flow_mvp/c0241_20210802_20210803_yolo_l2_3/configs/yolo11s_imgsz960/validation_2021-08-03/clips \
  --conf 0.50 \
  --imgsz 960 \
  --sample-every-sec 10 \
  --grid-cols 6 \
  --grid-rows 4 \
  --expected-clip-count 15 \
  --analysis-id c0241_20210802_20210803_l2_4 \
  --output-dir outputs/visitor_flow_mvp/c0241_20210802_20210803_l2_4
```

## L3-1 수동 ROI artifact 생성

L3-1은 YOLO를 다시 실행하지 않습니다. L2-4의 bbox bottom-center 좌표에 C0241 수동 normalized polygon을 적용하고, 0명 frame을 포함한 ROI frame/time 집계와 overlay를 생성합니다.

ROI 좌표를 직접 다시 잡을 때는 기준 프레임 이미지에서 꼭짓점을 클릭해 `configs/visitor_flow/c0241_roi_config.json`을 갱신합니다.

```bash
# [Design Intent] 기준 프레임 위에서 관리자가 매장 전면 접근 ROI 꼭짓점을 직접 찍어 normalized polygon config를 저장한다.
/home/imella0707/miniconda3/envs/ssakda/bin/python scripts/visitor_flow_l3_roi_define.py \
  --image outputs/visitor_flow_mvp/c0241_20210802_20210803_l3_1_roi/previews/roi_overlay_preview.jpg \
  --output configs/visitor_flow/c0241_roi_config.json \
  --camera-id C0241 \
  --roi-id in_front_of_shop
```

조작 방법은 왼쪽 클릭으로 점 추가, 오른쪽 클릭으로 마지막 점 취소, `s`로 저장, `q` 또는 `Esc`로 종료입니다.

```bash
# [Design Intent] 카메라별 수동 polygon을 L2 bbox observation에 적용해 재현 가능한 ROI 산출물을 만든다.
/home/imella0707/miniconda3/envs/ssakda/bin/python scripts/visitor_flow_l3_roi_aggregate.py \
  --input-dir outputs/visitor_flow_mvp/c0241_20210802_20210803_l2_4 \
  --roi-config configs/visitor_flow/c0241_roi_config.json \
  --analysis-id c0241_20210802_20210803_l3_1_roi \
  --output-dir outputs/visitor_flow_mvp/c0241_20210802_20210803_l3_1_roi
```

현재 C0241 결과는 전체 bbox observation 478건 중 ROI 내부 230건이며, ROI 비중은 48.12%입니다. ROI 기준 피크는 2021-08-02 12:00, 프레임당 평균은 1.889입니다. 이 ROI는 탐앤탐스 전면 보행로와 계단 진입 동선을 포함한 매장 전면 접근 ROI입니다.

## 연속 YOLO/ROI 검증 영상 생성

피크 시간대인 Aug 2 12:51 clip에서 관측량이 많은 60~120초 검증 영상을 생성합니다. `--start-sec`는 원본 clip 안에서 렌더링을 시작할 초 단위 위치이고, `--max-seconds 60`은 60초만 preview로 저장한다는 뜻입니다.

```bash
# [Design Intent] L2-4 최종 설정과 같은 conf=0.50을 사용하되 모든 연속 frame에 bbox/grid를 그려 사람이 탐지 품질을 직접 감사한다.
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
  --output outputs/visitor_flow_mvp/c0241_20210802_20210803_l2_4/preview_videos/2021-08-02_12-51-00_mon_sunny_out_ju-ja_C0241_yolo_conf_0p50_start_60s.webm
```

이 preview는 정성적(qualitative) 시각 검증 artifact입니다. 모든 연속 frame을 추론하므로, 10초 간격으로 18장씩 sampling한 L2-4 집계 수치와 직접 합산하거나 비교하면 안 됩니다.

같은 clip에 C0241 수동 ROI를 표시한 운영자 검수용 영상을 만들 때는 `--roi-config`를 추가합니다. `--hide-grid`는 ROI 경계와 bbox 판정에 집중할 수 있도록 기존 `6x4` grid를 숨깁니다.

```bash
# [Design Intent] 수동 ROI가 연속 frame에서도 유지되고 bbox bottom-center 포함 판정이 의도대로 동작하는지 내부 운영자가 검수한다.
/home/imella0707/miniconda3/envs/ssakda/bin/python scripts/visitor_flow_l2_render_preview.py \
  --video data/curated/aihub_cctv_visitor_flow/v1/c0241_20210802/videos/2021-08-02_12-51-00_mon_sunny_out_ju-ja_C0241.mp4 \
  --model /home/imella0707/yolo11s.pt \
  --device 0 \
  --imgsz 960 \
  --conf 0.50 \
  --grid-cols 6 \
  --grid-rows 4 \
  --roi-config configs/visitor_flow/c0241_roi_config.json \
  --hide-grid \
  --start-sec 60 \
  --max-seconds 60 \
  --output outputs/visitor_flow_mvp/c0241_20210802_20210803_l3_1_roi/preview_videos/2021-08-02_12-51-00_mon_sunny_out_ju-ja_C0241_yolo_conf_0p50_roi_start_60s.webm
```

이 ROI WebM은 탐지·ROI 설정을 검수하기 위한 비마스킹 내부 debug artifact입니다. 대시보드 기본 화면에는 직접 재생하지 않고, 필요한 경우 접힌 내부 경로로만 확인합니다.

## L3-2 개인정보 보호 미디어 생성

운영자 화면과 고객 PDF 모두 기본 시각자료는 L3-2 마스킹 산출물을 사용합니다. AIHub 원본에 데이터셋 제공 단계의 비식별화가 있더라도, 우리 파이프라인 산출물 기준으로 한 번 더 person bbox 상단부 mosaic를 적용합니다.

```bash
# [Design Intent] 운영자 화면과 고객 PDF에서 사용할 privacy-safe ROI 대표 이미지/영상을 outputs 후보 산출물로 만든다.
/home/imella0707/miniconda3/envs/ssakda/bin/python scripts/visitor_flow_l3_privacy_media.py \
  --video data/curated/aihub_cctv_visitor_flow/v1/c0241_20210802/videos/2021-08-02_12-51-00_mon_sunny_out_ju-ja_C0241.mp4 \
  --model /home/imella0707/yolo11s.pt \
  --roi-config configs/visitor_flow/c0241_roi_config.json \
  --output-dir outputs/visitor_flow_mvp/c0241_20210802_20210803_l3_2_privacy_media \
  --device 0 \
  --imgsz 960 \
  --conf 0.50 \
  --mask-conf 0.35 \
  --start-sec 60 \
  --max-seconds 60 \
  --mask-top-ratio 0.40 \
  --mask-padding-ratio 0.03 \
  --temporal-mask-frames 1 \
  --mosaic-block-size 12
```

`roi_preview_masked.webm`과 `roi_overlay_preview_masked.jpg`는 운영자 대시보드 기본 표시와 L3-3 고객 PDF 입력으로 사용합니다. L3-2는 용량과 재생 계약을 단순하게 유지하기 위해 WebM만 생성합니다. 비마스킹 `roi_overlay_preview.jpg`와 `*_roi_*.webm`은 내부 디버깅 경로로만 관리합니다.

## 실행

저장소 루트에서 실행합니다.

## 운영 정책

CCTV 상권분석은 기존 BrandMate 광고 생성 로직에 직접 섞지 않습니다. 현재 MVP에서 BrandMate 웹의 `상권분석` 메뉴는 고객에게 서비스 소개와 측정신청 화면을 제공하는 진입점으로만 둡니다. 분석 결과 화면은 고객에게 직접 공개하지 않고, 내부 운영자가 Streamlit에서 검수한 뒤 PDF 리포트 파일로 전달합니다.

Streamlit 대시보드는 내부 back-office 도구입니다. `고객 PDF 리포트` 탭은 고객이 접속하는 화면이 아니라 L3-3 `customer_report.html`/`customer_report.pdf`로 고정할 리포트 미리보기입니다. `운영 QA`와 `개발 artifact` 탭은 내부 전용이며 고객에게 공유하지 않습니다.

장기간 관측을 요구하는 고객이 늘어나고 분석 job, 파일 권한, 결제/프리미엄 entitlement가 안정화된 뒤에만 고객이 직접 로그인해 결과 현황을 보는 대시보드/포털을 별도 제품 단계로 검토합니다.

| 구분 | 현재 MVP 정책 |
|---|---|
| BrandMate 웹 | 상권분석 홍보와 측정신청 진입만 담당 |
| Streamlit | 내부 운영자 검수와 PDF 리포트 생성 보조 |
| 고객 제공물 | PDF 리포트 파일 |
| 금지 | Streamlit 주소를 고객에게 공유하거나 외부 IP에 공개 |
| 후속 | 장기 관측 고객이 많아진 뒤 고객 포털/로그인 대시보드 검토 |

### BrandMate 통합 실행 - 상권분석 담당자용

팀원 기본 실행에서는 Streamlit 상권분석 대시보드를 띄우지 않습니다. 상권분석 담당자 또는 관리자만 아래처럼 `START_DASHBOARD=true`를 명시해 BrandMate web, FastAPI, Postgres, Streamlit 대시보드를 함께 실행합니다.

```bash
# [Design Intent] 개발 중인 상권분석 Streamlit 화면은 담당자 확인 시에만 8503 포트로 함께 실행한다.
START_DASHBOARD=true bash scripts/manage_brandmate_services_gcp.sh restart
```

실행 후 접속 주소:

```text
BrandMate web: http://127.0.0.1:5501
Visitor-flow dashboard: http://127.0.0.1:8503
```

### 대시보드 단독 실행 - 개발/디버깅용

```bash
# [Design Intent] L2/L3 대시보드 실행에 필요한 Streamlit/Pandas/PyArrow 의존성을 설치한다.
/home/imella0707/miniconda3/envs/ssakda/bin/python -m pip install -r apps/visitor_flow_l2_dashboard/requirements.txt

# [Design Intent] L2-4, L3-1, L3-2 artifact를 읽어 전체 화면/ROI 프레임 정규화 지표와 마스킹된 ROI 미디어를 표시한다.
/home/imella0707/miniconda3/envs/ssakda/bin/python -m streamlit run apps/visitor_flow_l2_dashboard/app.py
```

브라우저가 자동으로 열리지 않으면 터미널에 표시되는 `http://localhost:8501` 또는 `http://localhost:8502` 주소로 접속합니다.

## 현재 화면에서 확인할 수 있는 것

화면은 고객 직접 접속용 SaaS가 아니라 내부 운영자 도구입니다. BrandMate 웹의 상권분석 메뉴는 고객에게 홍보/측정신청 화면을 보여주고, 실제 분석 결과는 운영자가 이 Streamlit 화면에서 검수한 뒤 PDF 파일로 전달하는 구조를 기준으로 합니다.

| 탭 | 용도 | 고객 제공 여부 |
|---|---|---|
| 고객 PDF 리포트 | L3-3 `customer_report.html`/`customer_report.pdf`로 고정할 리포트 미리보기 | PDF 산출물로 제공 |
| 운영 QA | ROI, 마스킹 영상, 탐지 품질, grid 해석 검수 | 내부 전용 |
| 개발 artifact | `analysis.json`, parquet sample 등 원본 산출물 확인 | 내부 전용 |

- 가장 붐빈 시간대
- 매장 전면 ROI 내부 sampled observation과 전체 관측 대비 비중
- ROI 내부 관측의 시간대별 프레임당 평균/p95/max
- 마스킹 처리된 수동 ROI 대표 이미지
- 마스킹 처리된 운영자용 ROI 연속 검증 영상
- 시간대별 프레임당 평균 보행 관측량
- 시간대별 p95/max 보행 관측량
- Aug 2/Aug 3 날짜 비교
- 화면 기준 최다 관측 구역
- 시간대별 전체 보행 관측량
- 실제 영상에서 노란 `6x4` grid 기준 확인
- 전체 시간대 또는 선택 시간대의 화면 구역별 관측 분포
- 시간대 기반 마케팅 후보 해석
- 검증용 YOLO bbox/grid 영상
- 수동 ROI polygon이 연속 frame에 표시된 비마스킹 내부 debug artifact 경로
- 개발/검증용 `analysis.json`, `frames.parquet`, `summary.parquet`, `events.parquet` 원본 확인

## 해석 제한

- 표시 값은 보행 관측량입니다.
- 같은 사람이 여러 sampled frame에 나오면 여러 건으로 집계됩니다.
- tracking을 하지 않았으므로 순방문자 수가 아닙니다.
- 화면 grid는 실제 지면 좌표가 아니라 CCTV 화면상의 상대 구역입니다.
- 화면 grid는 원근 보정 전의 image-space grid입니다. 같은 보행로도 카메라에서 멀면 좁게 압축되고 가까우면 넓게 펼쳐져 보일 수 있습니다.
- 시간대별 주지표는 0명 frame을 포함한 `mean_persons_per_sampled_frame`입니다. 관측 합계만으로 피크를 판단하지 않습니다.
- Aug 2와 Aug 3의 직접 날짜 비교는 두 날짜가 모두 가진 시간대만 기준으로 봅니다. 현재 겹치는 시간대는 `09:00`, `17:00`, `21:00`이며, 나머지 시간대는 해당 날짜 표본 안의 피크 후보로만 해석합니다.
- 히트맵 색상은 관측량의 상대 강도입니다. 연노랑은 적음, 주황은 중간, 진한 빨강은 많음을 뜻합니다.
- 진한 빨강 구역은 실제 면적당 인구 밀도나 입간판 설치 최적 위치가 아닙니다. 해당 화면 칸에서 사람이 탐지된 횟수가 상대적으로 많다는 뜻입니다.
- 시간대 목록은 임의 선택값이 아니라 입력 clip의 시작 시각을 1시간 단위로 묶은 결과입니다.
- marketing signal은 dashboard validation용 rule-based hypothesis이며 매출 상승 검증 결과가 아닙니다.
- preview 영상의 bbox는 tracking ID가 아닙니다.
- 노란 매장 전면 ROI는 카메라별 수동 설정이며 자동 탐지 결과가 아닙니다.
- ROI 내부 관측량은 bbox bottom-center가 polygon 안에 들어온 sampled observation입니다. 통행량, 선 통과 이벤트, 고유 방문자 수가 아닙니다.
- 카메라 위치나 crop이 바뀌면 해당 카메라의 ROI polygon을 다시 설정해야 합니다.
- 운영자 대시보드 기본 화면에는 L3-2 마스킹 이미지와 WebM만 표시합니다.
- 비마스킹 ROI 검증 영상은 내부 debug artifact이며 기본 화면에서 직접 재생하지 않습니다.
- ROI overlay 정지 이미지는 얼굴 마스킹 후 고객 PDF의 `분석화면 예시`로 포함할 수 있습니다.
