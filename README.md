# BrandMate AI

광고 제작이 어려운 소상공인이 매장과 상품 정보를 입력하면 바로 활용할 수 있는
한국어 광고 문구를 제안하는 서비스입니다.

현재 MVP의 한 가지 목표는 **좋은 광고 문구 생성**입니다. 광고 이미지와 영상은
문구 생성 품질을 검증한 뒤, 생성된 문구를 입력으로 사용하는 후속 단계에서 다룹니다.

## MVP 결과물

- 핵심 광고 문구와 보조 문구
- 행동을 유도하는 CTA
- 채널에 맞는 해시태그
- 과장·위험 표현 검토 결과
- 이후 광고 이미지 제작에 활용할 수 있는 구조화된 JSON

## 저장소 구조

```text
apps/
  api/                 광고 문구 생성 API와 도메인 로직
  web/                 광고 문구→이미지 흐름을 보는 정적 테스트 페이지
docs/
  API.md               요청·응답 계약
  ARCHITECTURE.md      현재 애플리케이션 구조
  IMPLEMENTATION_PLAN.md
  MODEL_STRATEGY.md    모델 후보와 평가 기준
```

기능이 실제로 필요해질 때 폴더를 추가합니다. 이미지 생성, 문서 생성, 별도 워커,
큐와 배포 인프라용 빈 디렉터리는 미리 만들지 않습니다.

## 개발 순서

1. 광고 문구 요청·응답 계약 확정
2. 업종별 프롬프트 템플릿 작성
3. Qwen 계열 모델로 첫 생성 흐름 연결
4. 한국어 자연스러움, 매력도, 안전성, 형식 준수율 평가
5. 테스트 페이지에서 카피→이미지 전달 계약 검증
6. 사용자 피드백을 모은 뒤 실제 이미지 모델과 학습 여부 검토

자세한 범위는 [구현 계획](docs/IMPLEMENTATION_PLAN.md)을 참고하세요.

## 로컬 실행

API는 [API 실행 안내](apps/api/README.md)에 따라 Hugging Face 토큰을 설정하고
`uvicorn app.main:app --reload`로 실행합니다. 별도 터미널에서:

```powershell
cd apps/web
python -m http.server 5500
```

`http://localhost:5500`에서 모델을 선택해 같은 광고 입력의 결과를 비교할 수 있습니다.

```cmd
vision model 연결
API 서버 실행
cd /d C:\final_1_team\apps\api
uvicorn app.extensions.ad_content.main:app --host 127.0.0.1 --port 8000

새 CMD 창을 하나 더 열고 프론트엔드 실행
cd /d C:\final_1_team\apps\web-ad-content
python.exe -m http.server 5501
