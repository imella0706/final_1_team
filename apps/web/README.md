# BrandMate 메인 통합 테스트 페이지

소상공인 입력부터 광고 문구 생성, 참고 이미지 업로드, 이미지 모델 선택, 최종 광고 이미지 생성까지
한 화면에서 확인하는 메인 정적 테스트 페이지입니다.

## 확인할 수 있는 것

- 업종, 상황, 타겟, 톤, 가게명, 상품, 금칙어 입력
- Qwen, Llama, Mistral, Gemma, Phi, SOLAR 중 광고 문구 모델 선택
- FLUX.1 Schnell, SDXL, Openjourney 등 이미지 생성 모델 선택
- 참고 이미지 업로드, 미리보기, 제품만 추출 옵션
- 광고 문구 모델의 문구·CTA·해시태그 결과
- 이미지 모델에 넘기는 프롬프트와 negative prompt
- 두 모델 사이에 전달되는 전체 JSON
- 생성된 광고 이미지와 저장된 artifact 경로

## 실행

저장소 루트에서 한 번에 실행할 수 있습니다.

```cmd
start-brandmate.cmd
```

이 스크립트는 API와 정적 웹 서버를 함께 확인/실행하고 브라우저를 엽니다.

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
app.js        광고 문구 + 이미지 생성 파이프라인 호출
```

API 주소를 바꿀 때는 `app.js` 상단의 `API_BASE_URL`을 수정합니다.
