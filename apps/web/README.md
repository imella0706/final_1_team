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

이 연결은 로컬 개발/발표용입니다. 기본 서비스 실행 명령으로 Streamlit 대시보드가 8503 포트로 자동 함께 시작됩니다.

## 실행

저장소 루트에서 한 번에 실행할 수 있습니다. 현재 GCP/WSL 기준 표준 실행 스크립트는 `scripts/manage_brandmate_services_gcp.sh`입니다.

```bash
cd /home/imella0707/personal/final_1_team
./scripts/manage_brandmate_services_gcp.sh restart
```

이 스크립트는 Postgres, DB migration, FastAPI, 정적 웹 서버, ComfyUI, Streamlit 상권분석 대시보드를 함께 확인/실행합니다.

팀원 로컬에 FLUX/ComfyUI가 없어도 같은 명령을 사용합니다. ComfyUI가 설치되어 있으면 실행하고, 없으면 자동으로 건너뜁니다.

```bash
# [Design Intent] GCP/로컬 모두 같은 진입점을 사용하며, Postgres/FastAPI/Web/ComfyUI/Streamlit을 원스톱으로 관리한다.
./scripts/manage_brandmate_services_gcp.sh restart
```

주의:

- ComfyUI가 없는 환경에서는 FLUX 이미지 생성만 동작하지 않습니다.
- 상권분석 Streamlit 대시보드는 8503 포트로 자동 실행되며, Web 메인(5501 포트)의 상권분석 카드에서 바로 진입할 수 있습니다.
- 로그인, 서비스 선택, 광고 생성 화면 진입, FastAPI 기본 연동은 확인할 수 있습니다.
- GCP 시연 환경에서는 전체 스크립트를 기본 옵션으로 실행하고, 팀원은 GCP web URL로 접속합니다.

개별로 실행하려면 먼저 `apps/api`에서 API를 `http://127.0.0.1:7660`으로 실행합니다. 그다음 별도
터미널에서 테스트 페이지를 실행합니다.

기존 화면만 확인할 때는 `index.html`을 직접 열 수 있습니다. PWA 설치와 오프라인 화면을
확인하려면 이 폴더에서 정적 서버를 실행합니다.

```bash
cd apps/web
python -m http.server 5501
```

브라우저에서 `http://localhost:5501`으로 접속합니다.

## 파일

```text
index.html             화면 구조와 입력·결과 영역, PWA 메타데이터 연결
styles.css             통합 테스트 페이지 레이아웃
app.js                 기존 기능과 서비스 워커 등록
manifest.webmanifest   설치 이름, 실행 방식, 테마와 아이콘 설정
sw.js                  정적 화면 파일의 오프라인 캐시와 업데이트 처리
icons/                 홈 화면 및 마스커블 앱 아이콘
```

API 주소를 바꿀 때는 `app.js` 상단의 `API_BASE_URL`을 수정합니다.

## PWA 설치와 캐시 범위

로컬에서는 `http://localhost:5501`, 외부 배포에서는 HTTPS 주소로 접속한 뒤 브라우저의
`앱 설치` 또는 `홈 화면에 추가` 메뉴를 사용합니다. 설치 후에도 같은 FastAPI 서버를 사용하므로
로그인과 광고 생성에는 네트워크 연결이 필요합니다.

외부 배포에서는 웹 화면뿐 아니라 FastAPI도 HTTPS로 제공해야 합니다. 가능하면 같은 도메인의
`/api/v1` 경로로 연결하고, 별도 도메인을 사용한다면 해당 HTTPS 주소와 CORS 설정을 함께 맞춥니다.

Windows 로컬 PC에서 웹 `127.0.0.1:5501`과 API `127.0.0.1:7660`을 이미 실행 중이라면
저장소 루트에서 다음 명령으로 발표용 임시 HTTPS 주소를 만들 수 있습니다.

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\manage_brandmate_tunnel.ps1 start
```

이 구성은 Caddy가 `/api/*`만 API로 전달하고 나머지는 웹으로 전달하므로 외부에서도 같은
origin을 사용합니다. Cloudflare 계정이나 소유 도메인은 필요하지 않으며, 발표 후에는 `stop`
명령으로 터널을 종료합니다. 터널을 다시 시작하면 임시 주소와 설치된 PWA의 origin이 바뀝니다.

현재 GCP 표준 경로에서는 저장소 루트에서 다음과 같이 동일 도메인 HTTPS 프록시를 실행합니다.

```bash
BRANDMATE_DOMAIN=app.example.com ./scripts/manage_brandmate_services_gcp.sh restart-demo-public
```

실행 전에 DNS가 GCP VM을 가리키고 외부 80/443 포트가 허용되어 있어야 합니다.
발표용 명령은 FastAPI의 공개 origin을 같은 `https://app.example.com` 주소로 자동 설정하고
이메일 인증과 SMTP 전송을 비활성화합니다. 공개 운영 배포에서는 `restart-public`을 사용하고
`BRANDMATE_WEB_ORIGIN`과 `BRANDMATE_AUTH_PUBLIC_WEB_URL`을 직접 운영 설정에 반영합니다.

서비스 워커는 `index.html`, `styles.css`, `app.js`, 매니페스트와 앱 아이콘만 캐시합니다.
API, 인증, 업로드 이미지와 광고 생성 결과는 캐시하거나 가로채지 않습니다. 화면 파일은
온라인일 때 서버를 먼저 확인하고, 연결할 수 없을 때만 저장된 파일을 사용합니다.

정적 화면 파일 구성이 바뀌면 `sw.js`의 `CACHE_NAME`을 새 값으로 올리고,
`APP_SHELL_PATHS`의 버전 쿼리도 `index.html`과 맞춥니다.
