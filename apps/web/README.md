# BrandMate 메인 통합 테스트 페이지

로그인 이후 광고 생성과 상권 분석 POC를 선택하는 메인 정적 테스트 페이지입니다.
광고 생성은 기존 BrandMate 화면에서 진행하고, 상권 분석은 개발 중인 Streamlit 대시보드를 새 탭으로 엽니다.
상권 분석 POC가 안정화되고 광고 생성 기능 통합이 완료되면 Streamlit을 제거하고 BrandMate 정적 웹 화면, 즉 현재 `index.html`/`app.js` 기반 바닐라 JS 화면으로 통합할 예정입니다.

## 확인할 수 있는 것

- 업종, 상황, 타겟, 톤, 가게명, 상품, 금칙어 입력
- Qwen, Llama, Mistral, Gemma, Phi, SOLAR 중 광고 문구 모델 선택
- FLUX.1 Schnell, SDXL, Openjourney 등 이미지 생성 모델 선택
- 참고 이미지 업로드, 미리보기, 제품만 추출 옵션
- 광고 문구 모델의 문구·CTA·해시태그 결과
- 이미지 모델에 넘기는 프롬프트와 negative prompt
- 두 모델 사이에 전달되는 전체 JSON
- 생성된 광고 이미지와 저장된 artifact 경로
- 상권 분석 POC 진입 카드

## 상권 분석 POC 연결

상권 분석 카드는 `http://127.0.0.1:8503`을 새 탭으로 엽니다.

```bash
# [Design Intent] 상권 분석은 아직 FastAPI 정식 API 계약이 없으므로 로컬 Streamlit POC로 임시 연결한다.
/home/imella0707/miniconda3/envs/ssakda/bin/python -m streamlit run apps/visitor_flow_l2_dashboard/app.py --server.port 8503
```

이 연결은 로컬 개발/발표용입니다. 상권분석 Streamlit은 아직 개발 중이므로 팀원 기본 실행에서는 띄우지 않습니다. 상권분석 담당 개발자가 직접 확인할 때만 `START_DASHBOARD=true`로 실행합니다.

## 실행

저장소 루트에서 한 번에 실행할 수 있습니다. 현재 GCP/WSL 기준 표준 실행 스크립트는 `scripts/manage_brandmate_services_gcp.sh`입니다.

```bash
cd /home/imella0707/personal/final_1_team
./scripts/manage_brandmate_services_gcp.sh restart
```

이 스크립트는 Postgres, DB migration, FastAPI, 정적 웹 서버, ComfyUI를 함께 확인/실행합니다. 상권분석 Streamlit은 아직 개발 중이므로 기본 실행에서는 제외합니다.

팀원 로컬에 FLUX/ComfyUI가 없어도 같은 명령을 사용합니다. ComfyUI가 설치되어 있으면 실행하고, 없으면 자동으로 건너뜁니다.

```bash
# [Design Intent] GCP/로컬 모두 같은 진입점을 사용한다. ComfyUI는 자동 감지하고, 개발 중인 Streamlit은 기본 비활성화한다.
./scripts/manage_brandmate_services_gcp.sh restart
```

주의:

- ComfyUI가 없는 환경에서는 FLUX 이미지 생성만 동작하지 않습니다.
- 상권분석 Streamlit은 개발 중이므로 기본 실행에서는 뜨지 않습니다.
- 상권분석 담당 개발자가 대시보드를 직접 확인할 때만 `START_DASHBOARD=true ./scripts/manage_brandmate_services_gcp.sh restart`로 실행합니다.
- 로그인, 서비스 선택, 광고 생성 화면 진입, FastAPI 기본 연동은 확인할 수 있습니다.
- GCP 시연 환경에서는 전체 스크립트를 기본 옵션으로 실행하고, 팀원은 GCP web URL로 접속합니다.

개별로 실행하려면 먼저 `apps/api`에서 API를 `http://127.0.0.1:7660`으로 실행합니다. 그다음 별도
터미널에서 테스트 페이지를 실행합니다.

`index.html`을 직접 열거나 이 폴더에서 정적 서버를 실행합니다.

```bash
cd apps/web
python -m http.server 5501
```

브라우저에서 `http://localhost:5501`으로 접속합니다.

## 파일

```text
index.html    화면 구조와 입력·결과 영역
styles.css    통합 테스트 페이지 레이아웃
app.js        서비스 선택 화면과 광고 문구 + 이미지 생성 파이프라인 호출
```

API 주소를 바꿀 때는 `app.js` 상단의 `API_BASE_URL`을 수정합니다.
