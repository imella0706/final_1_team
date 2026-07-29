# Channel Output Formatting Changes

## 목적

Instagram 이미지 다운로드와 Naver Blog 원고 복사 흐름에서 실제 사용자가 바로 활용하기 어려운 부분을 개선했다.

- Instagram: 긴 게시 제목을 이미지에 그대로 올려 다운로드할 때 뒤 문구가 잘리는 문제를 줄였다.
- Naver Blog: 테스트 UI의 작은 글자를 직접 복사하지 않고, 네이버 블로그 편집기에 붙여넣기 좋은 전용 원고를 별도로 생성하고 복사하게 했다.

## 변경 파일

### `apps/web/app.js`

#### `splitLongCanvasToken(context, token, maxWidth)`

공백이 없는 긴 한국어/상품명 문자열도 캔버스 너비를 넘지 않도록 문자 단위로 나누는 함수다.

기존 `wrapCanvasText`는 공백 기준으로만 줄을 나눴기 때문에 긴 상품명이나 제목이 한 단어처럼 들어오면 줄바꿈이 제대로 되지 않았다.

#### `wrapCanvasText(context, text, maxWidth)`

긴 단어를 먼저 `splitLongCanvasToken`으로 분해한 뒤 줄을 계산하도록 수정했다.

의도는 한국어 제목, 메뉴명, 브랜드명처럼 공백이 적은 텍스트도 다운로드 이미지 안에서 자연스럽게 줄바꿈되게 하는 것이다.

#### `splitPosterTitle(title)`

긴 제목을 포스터용 짧은 `headline`과 보조 설명용 `subtitle`로 분리한다.

예를 들어 `연남동 카페 '오후의 조각' 신메뉴 – 수제 딸기 티라미수와 피치에이드`처럼 긴 제목은 앞부분을 overlay headline으로, 뒤 상품 설명을 subtitle로 나눈다.

의도는 이미지 위에 들어가는 글자를 "전체 게시 제목"이 아니라 "시각적으로 읽히는 짧은 문구"로 바꾸는 것이다.

#### `fitCanvasText(context, text, maxWidth, options)`

캔버스에 들어갈 텍스트의 글자 크기를 자동으로 줄이면서 지정한 최대 줄 수 안에 맞춘다.

기존에는 고정 글자 크기와 `slice(0, 3)` 방식 때문에 제목 뒤쪽이 사라질 수 있었다. 변경 후에는 headline과 subtitle 각각 최대 줄 수, 최소/최대 폰트 크기, 줄간격을 따로 적용한다.

#### `buildMergedPosterBlob()`

다운로드/클립보드 복사용 최종 포스터 이미지를 합성하는 함수다.

변경 사항:

- `#poster-headline`뿐 아니라 `#poster-subtitle`도 함께 읽는다.
- 하단 그라데이션 영역을 조금 넓혀 subtitle까지 읽히게 했다.
- headline은 최대 2줄, subtitle은 최대 2줄로 맞춘다.
- 고정 폰트 크기 대신 `fitCanvasText`로 이미지 크기에 맞춰 자동 조절한다.

의도는 긴 제목이 잘리지 않고, 이미지 위 텍스트가 제목/부제 구조로 안정적으로 보이게 하는 것이다.

#### `buildNaverBlogPasteText(input, recommendation, copy, publishHashtags)`

네이버 블로그 전용 복붙 원고를 만드는 새 함수다.

입력 채널이 `naver_blog`일 때만 동작하며 다음 요소를 하나의 텍스트로 조립한다.

- 블로그 제목
- 대표 사진 삽입 위치와 추천 이유
- `blog_sections` 기반 섹션별 제목, 사진 삽입 위치, 본문
- 사진 순서 추천
- 해시태그

의도는 사용자가 결과 UI의 작은 텍스트를 드래그해서 복사하지 않게 하고, 네이버 블로그 편집기에 바로 붙여넣을 수 있는 원고를 별도로 제공하는 것이다.

#### `copyNaverBlogPasteText()`

`latestNaverBlogPasteText`에 저장된 네이버 블로그 원고를 클립보드에 복사한다.

브라우저가 `navigator.clipboard.writeText`를 지원하지 않거나 아직 생성된 원고가 없으면 사용자에게 오류를 보여준다.

#### `renderResult(input, result)`

모델 결과를 화면에 렌더링할 때 다음 처리를 추가했다.

- `splitPosterTitle`로 포스터 headline/subtitle을 분리해 `#poster-headline`, `#poster-subtitle`에 반영한다.
- `buildNaverBlogPasteText`로 네이버 블로그 복붙 원고를 생성한다.
- 생성된 원고가 있을 때만 `#naver-blog-copy-preview`, `#naver-blog-copy-label`, `#copy-naver-blog-button`을 표시한다.

### `apps/web/index.html`

#### 포스터 subtitle 영역

`figcaption.poster-copy` 안에 다음 요소를 추가했다.

```html
<small id="poster-subtitle"></small>
```

의도는 이미지 위의 긴 제목을 한 덩어리로 보여주지 않고, 짧은 headline과 subtitle로 분리해 표시하는 것이다.

#### 네이버 블로그 복붙 원고 영역

`publish-package` 안에 다음 요소를 추가했다.

```html
<span id="naver-blog-copy-label" hidden>네이버 블로그 복붙 원고</span>
<pre class="naver-blog-copy-preview" id="naver-blog-copy-preview" hidden></pre>
<button class="text-button naver-blog-copy-button" id="copy-naver-blog-button" type="button" hidden>
  네이버 블로그 원고 복사
</button>
```

의도는 테스트 페이지의 결과 표시 영역과 실제 네이버 블로그에 붙여넣을 원고를 분리하는 것이다.

### `apps/web/styles.css`

#### `.poster-copy small`

포스터 subtitle 전용 스타일을 추가했다.

- headline보다 작은 크기
- 높은 대비
- 자연스러운 줄간격
- 긴 한국어 문구 대응을 위한 `word-break`, `overflow-wrap`

#### `.publish-package .naver-blog-copy-preview`

네이버 블로그 복붙 원고 미리보기 스타일을 추가했다.

기존 결과 텍스트는 11px로 작게 표시되어, 사용자가 직접 복사하면 사용성이 떨어졌다. 새 미리보기는 14px, 넓은 줄간격, 별도 배경과 스크롤 영역을 적용했다.

#### `.naver-blog-copy-button`

네이버 블로그 원고 복사 버튼 스타일을 추가했다.

의도는 사용자가 복사해야 할 대상이 "일반 결과 텍스트"가 아니라 "네이버 블로그 원고"라는 점을 명확히 보여주는 것이다.

### `apps/api/app/modules/ad_copy/prompt.py`

#### `build_naver_blog_prompt(request)`

네이버 블로그 채널 프롬프트에 다음 요구를 추가했다.

- `publish_body`는 네이버 블로그 편집기에 그대로 붙여넣을 수 있는 완성 원고로 작성한다.
- UI 라벨, JSON 키 이름, 개발용 설명을 본문에 넣지 않는다.
- 제목, 대표 사진 삽입 위치, 도입부, 사진별 본문 문단, 방문/주문 안내, 마무리, 해시태그 흐름을 빈 줄과 함께 구성한다.
- 문단은 모바일에서 읽기 좋게 1~3문장 단위로 짧게 나눈다.
- 사진 위치는 `[사진 삽입: 사진 2 - 대표 메뉴]`처럼 사용자가 바로 이해할 수 있게 표시한다.

의도는 프론트엔드에서 후처리하기 전에 모델 출력 자체가 네이버 블로그에 적합한 원고 구조를 갖도록 하는 것이다.

## 기대 효과

- Instagram 다운로드 이미지에서 긴 제목의 뒷부분이 사라지는 문제가 줄어든다.
- 이미지 위 텍스트가 headline/subtitle 구조로 정리되어 가독성이 좋아진다.
- Naver Blog 결과는 테스트 UI 표시용 텍스트와 실제 복사용 원고가 분리된다.
- 사용자는 블로그 원고를 복사한 뒤 글자 크기와 문단 구조를 다시 크게 손보는 시간을 줄일 수 있다.
- 모델 프롬프트와 프론트엔드 출력 조립이 같은 방향을 바라보므로 결과 일관성이 좋아진다.
