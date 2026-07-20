# Visitor Flow Streamlit POC

C0241 17:09 단일 영상의 L1-3 YOLO 평가 결과를 보여주는 독립형 대시보드입니다.

이 화면은 실제 방문객 수나 시간대별 상권 분석 결과가 아닙니다. sampled-frame bbox 탐지 성능과 오류 preview를 팀원에게 시연하기 위한 L1 POC입니다.

## 임시 운영 안내

이 Streamlit 앱은 visitor-flow 결과를 기존 BrandMate 웹 코드와 바로 결합하지 않고 빠르게 검증하기 위해 만든 임시 대시보드입니다. 최종 사용자용 독립 서비스가 아니며, 현재는 모델 평가 결과와 시각화 구성을 확인하는 용도로만 운영합니다.

향후 visitor-flow 결과 조회 API를 FastAPI에 추가하고 화면을 `apps/web`에 통합하면 이 앱은 운영 대상에서 제외합니다. 통합 화면의 기능이 이 POC와 동일한 수준으로 검증된 뒤 `apps/visitor_flow_poc`를 제거하거나 legacy 코드로 이동합니다.

- 현재 역할: YOLO 평가 결과의 내부 검증 및 팀 시연
- 임시 UI: Streamlit
- 최종 UI: `apps/web`
- 최종 데이터 제공 방식: 브라우저의 로컬 파일 직접 접근이 아닌 FastAPI 응답
- 종료 조건: `apps/web` 통합 화면에서 지표, 프레임 오류, bbox preview 확인 완료

## 실행

저장소 루트에서 실행합니다.

```bash
# [Design Intent] 대시보드 전용 고정 의존성을 설치합니다.
python -m pip install -r apps/visitor_flow_poc/requirements.txt

# [Design Intent] 기본 L1-3 결과 폴더를 읽어 로컬 Streamlit 화면을 엽니다.
python -m streamlit run apps/visitor_flow_poc/app.py
```

기본 입력은 아래 로컬 산출물입니다.

```text
outputs/visitor_flow_mvp/c0241_20210802_yolo_l1_3/
```

다른 결과 폴더를 확인하려면 화면 왼쪽의 `L1-3 결과 폴더`를 변경합니다.

## 현재 화면에서 확인할 수 있는 것

- threshold별 Precision, Recall, F1
- 선택 threshold의 TP, FP, FN
- 프레임별 AIHub reference bbox와 YOLO bbox 차이
- 선택 threshold의 GT/TP/FP/FN preview

실제 방문객 수, 중복 제거, 하루 시간대별 피크, 구역 heatmap, 마케팅 최종 추천은 후속 L1-5/L2 범위입니다.
