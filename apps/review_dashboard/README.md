# BrandMate SNS TrendCard Review Dashboard (Streamlit MVP)

BrandMate SNS 트렌드 카드 수집 및 Scoring 결과를 사람이 검수(`accept / reject / hold`)하고, 승인된 결과를 `review_decisions` 아티팩트로 저장하며 Airflow Processed Release DAG를 이벤트 기반으로 트리거하는 Streamlit 대시보드 애플리케이션입니다.

## 주요 기능

1. **자동 주차 및 Run Discovery**:
   - `data/curated/sns_trend/v3/review_queue/` 하위의 `week=YYYY-Www` 및 Airflow/CLI `run_id` 자동 탐색.
2. **2단계 필터링 (2-Tier Review View)**:
   - **⚡ Top 20 Default Review**: 1위~20위 상위 추천 카드 3분 빠른 검수 뷰. (공식 processed v2 baseline 규격과 1:1 대응)
   - **🔍 Top 100 Search & Filter**: 소스별 필터(`YouTube`, `Gogumafarm`, `Careet`, `Naver`), 키워드 검색, 순위 슬라이더를 갖춘 Top 100 컷오프 탐색 뷰.
3. **Decisions Persistence & P5-5 Validator 연동**:
   - 검수 저장 시 `gather_data/review_queue/decisions.py`의 `validate_review_decisions`를 통해 Naver-only accept 금지 및 ID 무결성 자동 검증.
   - `data/curated/sns_trend/v3/review_decisions/week=YYYY-Www/` 아래 `sns_trend_review_decisions.json` 및 `sns_trend_review_decisions.csv` 원자적(Atomic) 단방향 저장.
4. **Airflow REST API Release Trigger**:
   - 대시보드 하단의 "Release to Processed" 버튼 클릭 시 Airflow REST API (`POST /api/v1/dags/sns_trend_processed_release/dagRuns`) 호출.

## 실행 방법

`ssakda` conda 가상환경에서 아래 명령으로 실행합니다.

```bash
# 로컬 개발 및 인터랙티브 실행
PYTHONPATH=gather_data conda run -n ssakda streamlit run apps/review_dashboard/sns_trend_review_app.py

# Headless 검증 모드
PYTHONPATH=gather_data conda run -n ssakda streamlit run apps/review_dashboard/sns_trend_review_app.py --server.headless true
```
