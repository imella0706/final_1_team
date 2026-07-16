# 캐릿 밈 데이터 크롤러 기획서

## 1. 문서 목적

이 문서는 캐릿(Careet)의 **요즘 뜨는 밈** 시리즈에서 공개된 메타데이터와 밈 이름을 수집하는 Python 크롤러의 구현 명세다.

구현 담당 에이전트는 이 문서만으로 크롤러를 작성하고, 실제 사이트 응답으로 선택자와 출력 결과를 검증해야 한다.

## 2. 목표

- 대상 시리즈의 모든 공개 콘텐츠 목록을 수집한다.
- 각 콘텐츠 상세 페이지에서 공개된 작성자, 시리즈, 목차 등을 수집한다.
- 목차를 개별 밈 단위로 정규화한다.
- 콘텐츠 단위 CSV와 밈 단위 CSV를 각각 생성한다.
- 재실행, 중단 복구, 중복 제거가 가능한 구조로 구현한다.
- 공개 미리보기에서 확인 가능한 밈에는 저작권을 침해하지 않는 짧은 자체 요약과 사용 상황을 생성한다.
- 대표 썸네일 저장은 권리와 이용 조건을 확인한 사용자가 명시적으로 켠 경우에만 지원한다.
- 로그인, 유료 장벽 우회, 본문 전체 또는 본문 삽입 이미지 복제는 구현하지 않는다.

## 3. 대상 사이트

| 구분 | URL |
|---|---|
| 시리즈 목록 | `https://www.careet.net/Content/Series/1` |
| 페이지네이션 | `https://www.careet.net/Content/Series/1?pageidx={page}` |
| 상세 페이지 | `https://www.careet.net/{article_id}` |
| robots.txt | `https://www.careet.net/robots.txt` |
| 저작권 정책 | `https://www.careet.net/Policy/Copyright` |

2026-07-08 확인 기준으로 목록은 서버 렌더링 HTML이며 페이지당 최대 12건, 총 12페이지·136건이다. 이 수치는 고정값으로 사용하지 말고 매 실행 시 HTML에서 다시 확인한다.

## 4. 접근 및 준수 원칙

### 허용 범위

- 공개 목록 페이지
- 비로그인 상태에서 제공되는 공개 상세 HTML
- 제목, URL, 날짜, 상태, 작성자, 시리즈, 목차 등 메타데이터
- 원본 페이지와 썸네일의 URL 문자열
- 공개 미리보기를 실행 중 메모리에서 분석해 새 문장으로 만든 짧은 설명
- 사용자가 명시적으로 활성화한 대표 썸네일의 연구용 로컬 사본

### 금지 범위

- 로그인 자동화 및 계정·쿠키 사용
- 멤버십 또는 페이월 우회
- 비공개 API 탐색이나 접근 제어 회피
- 본문 전체 또는 공개 미리보기 원문 문장의 저장·재배포
- 본문에 삽입된 이미지, GIF, 동영상 다운로드
- 이미지 다운로드 옵션을 사용자의 명시적 선택 없이 기본 활성화
- `/FileData`, `/MyPage`, `/User`, `/admtower` 접근

`robots.txt`상 `/Content/Series/1`과 숫자 상세 경로는 허용되지만 `/FileData` 등은 제한된다. 썸네일 URL이 별도 S3 호스트를 가리키더라도 저작권과 이용 조건은 별개다. 따라서 기본 동작은 **URL만 저장**이며, 로컬 저장은 `--download-thumbnails`를 명시한 경우에만 수행한다. 저장한 이미지는 내부 분석용으로만 취급하고 재배포하지 않는다. 실제 운영 전에는 사이트 운영자의 허락 또는 이용 권한을 별도로 확인하는 것이 권장된다.

요청 간 기본 대기 시간은 1.5초 이상으로 설정하고, 사용자가 CLI에서 더 긴 값으로 조정할 수 있게 한다.

## 5. 권장 기술 구성

- Python 3.11 이상
- `requests`
- `beautifulsoup4`
- 표준 라이브러리: `csv`, `json`, `logging`, `argparse`, `datetime`, `pathlib`, `time`, `re`
- JavaScript 렌더링 및 Selenium/Playwright는 사용하지 않는다.
- CSV 인코딩은 Excel 호환을 위해 `utf-8-sig`로 저장한다.

네트워크 요청에는 다음을 적용한다.

- 식별 가능한 고정 `User-Agent`
- 연결 및 읽기 타임아웃
- `requests.Session` 재사용
- HTTP 429 및 5xx에 한해서 지수 백오프 재시도
- 403, 404 등은 무한 재시도하지 않고 로그에 남긴다.
- 최대 재시도 횟수는 기본 3회로 제한한다.

## 6. 페이지 구조

사이트 개편 가능성이 있으므로 아래 선택자는 1차 선택자로 사용하고, 값 검증과 오류 로그를 반드시 추가한다.

### 6.1 목록 페이지

확인된 주요 구조:

```html
<section class="trend-list">
  <div class="trend-delivery__item">
    <a href="/1929">
      <div class="img-wrap"><img src="..." /></div>
      <strong class="title">...</strong>
      <span class="cate">유행중</span>
      <span class="date">2026.06.17</span>
    </a>
  </div>
</section>
```

```html
<div
  class="pagination"
  data-pagecount="12"
  data-pageparameter="pageidx"
  data-urlformat="/Content/Series/1?pageidx=__pageidx__">
</div>
```

선택자와 추출 규칙:

| 값 | 1차 선택자·규칙 |
|---|---|
| 카드 | `section.trend-list div.trend-delivery__item` |
| 상세 링크 | 카드 내부 `a[href]`, 경로가 `^/\d+$`인 경우만 허용 |
| `article_id` | 상세 링크의 숫자 경로 |
| 제목 | `strong.title`의 공백 정규화된 텍스트 |
| 썸네일 URL | `.img-wrap img[src]`의 `src`, `urljoin`으로 절대 URL화 |
| 상태 | `span.cate`, 없으면 빈 문자열 |
| 게시일 | `span.date`, 형식 `YYYY.MM.DD` |
| 총 페이지 | `.pagination[data-pagecount]` 속성 |

목록에서 카드 내부 북마크 버튼이나 관련 콘텐츠를 카드로 오인하지 않도록 상세 링크 패턴과 카드 컨테이너를 동시에 검증한다.

### 6.2 상세 페이지

확인된 주요 선택자:

| 값 | 1차 선택자·규칙 |
|---|---|
| 제목 | `h3.content-title` |
| 상태 | `.content-heading .cate-wrap .cate` |
| 게시일 | `.content-heading p.content-date` |
| 시리즈 이름 | `.content-heading .series-name` |
| 시리즈 링크 | `.content-heading a.series-name__wrap[href]` |
| 대표 이미지 URL | `.content-heading .con-right .img-wrap img[src]` 또는 `meta[property="og:image"]` |
| 작성자 | `.editor-info__wrap .editor-name` |
| 작성자 링크 | `.editor-info__wrap a[href^="/Content/Editor/"]` |
| 공개 글 영역 | `section.content-article article.article` |
| 페이월 표시 | `.careet-secret-cover__wrap`, `.careet-secret__con` 중 하나가 존재 |

목록과 상세 값이 다를 경우 상세 값을 우선하되 경고 로그를 남긴다. `article_id`, URL은 목록 값을 기준으로 유지한다.

### 6.3 목차 추출

목차는 상세 페이지의 공개 글 영역에 HTML 테이블 형태로 제공되는 사례가 확인되었다.

예시:

```text
목차
1. 백룸코어
2. 천연 위고비
3. 요즘 뜨는 해외 숏폼 밈 2
  ① Wow Okay
  ② Forgot Airpods trend
4. 자려고 누웠는데 양의지
```

추출 절차:

1. `article.article` 내부 테이블 중 텍스트에 `목차`가 포함된 첫 테이블을 찾는다.
2. `목차` 라벨을 제외한 셀의 줄바꿈 구조를 유지해 항목을 분리한다.
3. `1.`, `2.`, `①`, `②`, `가.` 등 흔한 번호 접두어를 제거한다.
4. 빈 항목과 `목차` 자체는 제거한다.
5. 원래 순서를 유지한다.
6. 원문 목차 구조가 없으면 빈 배열을 저장한다. 제목이나 본문에서 추측해 채우지 않는다.

상위 번호 아래 원형 번호 항목이 있으면 다음과 같이 계층을 보존한다.

```json
[
  {"position": 1, "name": "백룸코어", "parent_section": null},
  {"position": 2, "name": "천연 위고비", "parent_section": null},
  {"position": 3, "name": "요즘 뜨는 해외 숏폼 밈 2", "parent_section": null},
  {"position": 4, "name": "Wow Okay", "parent_section": "요즘 뜨는 해외 숏폼 밈 2"},
  {"position": 5, "name": "Forgot Airpods trend", "parent_section": "요즘 뜨는 해외 숏폼 밈 2"},
  {"position": 6, "name": "자려고 누웠는데 양의지", "parent_section": null}
]
```

목차의 상위 항목이 단순 묶음 제목인지 실제 밈인지 자동으로 완벽히 판단할 수 없다. 따라서 원본 항목을 삭제하지 않고 `parent_section`으로 관계만 기록한다.

### 6.4 밈 설명 생성

밈 이름만으로는 분석 가치가 낮으므로 가능한 경우 다음 두 값을 생성한다.

- `meme_summary`: 밈의 뜻이나 유래를 설명하는 1~2문장, 최대 200자
- `usage_example`: 해당 밈이 쓰이는 대표 상황을 설명하는 1문장, 최대 120자

설명 생성 원칙:

1. 비로그인 상태에서 실제로 노출된 공개 미리보기만 입력 자료로 사용한다.
2. 목차 다음에 공개된 첫 번째 소제목과 그 아래 텍스트를 대응되는 밈의 설명 근거로 사용한다.
3. 페이월 뒤 항목은 접근하거나 추측하지 않는다.
4. 원문 문장을 그대로 복사하지 않고 핵심 사실만 새 문장으로 바꾼다.
5. 출처에 없는 유래, 인물, 플랫폼, 사용법을 지어내지 않는다.
6. 근거가 부족하면 빈 문자열로 두고 `summary_status=insufficient_source`로 기록한다.
7. 요약에 성공하면 `summary_source=public_preview`, `summary_status=generated`로 기록한다.
8. 실패하면 `summary_status=failed`로 기록하고 다음 항목으로 진행한다.

공개 영역의 소제목은 `h3#mid__title` 또는 `article.article h2, h3`에서 찾는다. 해당 제목부터 다음 제목 또는 페이월 커버 전까지의 텍스트만 요약 입력으로 사용한다. 요약 입력 원문은 실행 중 메모리에서만 다루고 CSV, 로그, 캐시 파일에 저장하지 않는다.

설명 생성기는 크롤링·파싱 코드와 분리된 `SummaryGenerator` 인터페이스로 구현한다. 규칙 기반 요약으로 사실을 안전하게 재서술할 수 없는 경우 빈 값을 반환해야 한다. 선택적으로 LLM 구현체를 붙일 수 있지만 API 키를 코드에 저장해서는 안 되며, LLM 사용 여부와 모델은 README에 명시한다.

캐릿 공개 미리보기에는 보통 첫 번째 항목만 설명되어 있으므로 **모든 목차 항목에 설명이 생긴다고 가정하면 안 된다**. 전체 밈 설명이 필요하면 캐릿 크롤러와 분리된 후속 보강 단계에서 공식 SNS, 원본 영상 등 공개 출처를 추가 조사해야 한다.

### 6.5 대표 썸네일 저장

이미지 저장은 기술적으로 가능하지만 기본값은 비활성화한다. `--download-thumbnails`가 있을 때만 콘텐츠 대표 썸네일을 내려받는다.

저장 대상:

- 목록 카드 또는 상세 `og:image`의 대표 썸네일 1장
- 하나의 `article_id`당 최대 1개

저장 제외:

- `article.article` 본문에 삽입된 이미지와 GIF
- 페이월 전후의 콘텐츠 이미지
- 동영상, iframe, SNS 임베드 미디어

다운로드 절차:

1. 이미지 URL의 스킴이 `https`인지 확인한다.
2. 스트리밍 요청을 사용하며 요청 제한과 재시도 정책을 동일하게 적용한다.
3. 응답 `Content-Type`이 `image/jpeg`, `image/png`, `image/webp`, `image/gif` 중 하나인지 확인한다.
4. 최대 크기는 기본 10MB로 제한하고 초과 시 중단한다.
5. 파일명은 외부 URL을 사용하지 않고 `{article_id}.{검증된_확장자}`로 생성한다.
6. `.part` 임시 파일에 저장한 후 SHA-256을 계산하고 원자적으로 이동한다.
7. 이미 존재하며 해시가 같은 파일은 다시 저장하지 않는다.
8. HTML 응답이나 이미지 디코딩이 불가능한 파일은 삭제하고 실패로 기록한다.

썸네일은 특정 밈 하나가 아니라 **기사 전체의 대표 이미지**라는 점을 데이터 모델에 유지한다. 밈별 이미지로 복제하거나 연결하지 않는다.

## 7. 출력 데이터

실행 결과는 콘텐츠 원본 단위와 개별 밈 단위로 나눈다.

### 7.1 `careet_articles_YYYYMMDD.csv`

| 필드 | 타입 | 필수 | 설명 |
|---|---|---:|---|
| `source` | string | O | 고정값 `careet` |
| `series_id` | string | O | 고정값 `1` |
| `series_name` | string | O | 기본값 `요즘 뜨는 밈`, 상세값 우선 |
| `article_id` | string | O | 숫자 경로 ID |
| `url` | string | O | 정규화된 상세 URL |
| `title` | string | O | 콘텐츠 제목 |
| `published_date` | date | O | ISO `YYYY-MM-DD` |
| `trend_status_raw` | string |  | 사이트 원문 상태 |
| `trend_status` | string | O | 정규화 상태 |
| `thumbnail_url` | string |  | 원본 대표 썸네일 URL |
| `thumbnail_local_path` | string |  | 옵션으로 저장한 로컬 상대 경로 |
| `thumbnail_mime_type` | string |  | 검증된 MIME 타입 |
| `thumbnail_bytes` | integer |  | 저장한 파일 크기 |
| `thumbnail_sha256` | string |  | 저장한 파일의 SHA-256 |
| `thumbnail_download_status` | string | O | `disabled`, `success`, `skipped`, `failed` |
| `author` | string |  | 상세 작성자 |
| `author_id` | string |  | `/Content/Editor/{id}`의 ID |
| `toc_json` | JSON string | O | 목차 객체 배열, 없으면 `[]` |
| `meme_item_count` | integer | O | 목차에서 추출된 항목 수 |
| `is_paywalled` | boolean | O | `true` 또는 `false` |
| `list_page` | integer | O | 발견한 목록 페이지 |
| `list_position` | integer | O | 해당 페이지 내 순서, 1부터 시작 |
| `detail_fetch_status` | string | O | `success`, `http_error`, `parse_error` |
| `collected_at` | datetime | O | 타임존 포함 ISO 8601 |

상태 정규화 규칙:

| 원문 | 정규화 |
|---|---|
| `유행예감`, `유행 예감` | `emerging` |
| `유행중`, `유행 중` | `current` |
| `유행지남`, `유행 지남` | `expired` |
| 빈 값 또는 미등록 값 | `unknown` |

미등록 상태 문자열은 삭제하지 않고 `trend_status_raw`에 보존한다.

### 7.2 `careet_memes_YYYYMMDD.csv`

| 필드 | 타입 | 필수 | 설명 |
|---|---|---:|---|
| `meme_id` | string | O | `{article_id}_{position}` |
| `article_id` | string | O | 원본 콘텐츠 ID |
| `meme_name` | string | O | 목차에서 번호를 제거한 이름 |
| `parent_section` | string |  | 상위 목차 이름 |
| `position` | integer | O | 콘텐츠 내 순서 |
| `published_date` | date | O | 원본 콘텐츠 게시일 |
| `trend_status` | string | O | 원본 콘텐츠 정규화 상태 |
| `extraction_source` | string | O | 현재는 고정값 `toc` |
| `meme_summary` | string |  | 공개 근거로 재서술한 1~2문장 설명 |
| `usage_example` | string |  | 대표 사용 상황 1문장 |
| `summary_source` | string |  | 성공 시 `public_preview` |
| `summary_status` | string | O | `generated`, `insufficient_source`, `failed`, `disabled` |
| `summary_confidence` | string | O | `high`, `medium`, `low`, `unknown` |
| `source_url` | string | O | 캐릿 상세 URL |
| `collected_at` | datetime | O | 타임존 포함 ISO 8601 |

`aliases`, `platform_hint`, `meme_type` 등 근거가 없는 속성은 크롤러가 추측하지 않는다. 설명도 공개 근거가 부족하면 빈 값으로 둔다.

## 8. 파일 및 코드 구조

최소 산출물:

```text
crawling/
├─ CAREET_CRAWLER_SPEC.md
├─ careet_crawler.py
├─ requirements.txt
├─ README.md
├─ data/
│  ├─ raw/
│  │  ├─ careet_articles_YYYYMMDD.csv
│  │  └─ thumbnails/              # 옵션 사용 시에만 생성
│  │     └─ {article_id}.{ext}
│  └─ processed/
│     └─ careet_memes_YYYYMMDD.csv
└─ tests/
   ├─ fixtures/
   └─ test_careet_crawler.py
```

HTML fixture에는 실제 본문을 장기간 복제하지 말고 파서 테스트에 필요한 최소 구조만 직접 작성한다.

## 9. CLI 요구사항

기본 실행:

```powershell
python careet_crawler.py
```

지원 옵션:

```text
--start-page INTEGER    시작 페이지, 기본 1
--end-page INTEGER      종료 페이지, 미지정 시 HTML의 data-pagecount 사용
--delay FLOAT           요청 사이 대기 초, 기본 1.5, 최소 1.0
--timeout FLOAT         요청 타임아웃 초, 기본 15
--retries INTEGER       429·5xx 최대 재시도, 기본 3
--output-dir PATH       출력 루트, 기본 ./data
--list-only             상세 요청 없이 articles 목록 필드만 생성
--resume                기존 당일 articles 파일을 읽어 성공한 상세 요청 생략
--summary-mode MODE     rule 또는 off, 기본 rule
--download-thumbnails   대표 썸네일 저장, 기본 비활성화
--max-image-bytes INT   이미지당 최대 크기, 기본 10485760
--log-level LEVEL       DEBUG, INFO, WARNING, ERROR
```

`--list-only`에서는 상세 전용 필드를 빈 값으로 두고 `detail_fetch_status=list_only`로 기록한다. `toc_json=[]`, `meme_item_count=0`으로 저장한다.

`--summary-mode=off`에서는 모든 설명 필드를 비우고 `summary_status=disabled`, `summary_confidence=unknown`으로 기록한다. 기본 `rule` 모드는 공개 미리보기에 명시된 정보만 규칙 기반으로 짧게 재서술한다.

`--download-thumbnails`가 없으면 이미지 요청을 하지 않고 `thumbnail_download_status=disabled`로 기록한다.

`--end-page`가 실제 총 페이지보다 크면 총 페이지까지만 실행하고 경고를 남긴다.

## 10. 실행 흐름

1. 첫 목록 페이지를 요청한다.
2. `data-pagecount`에서 총 페이지를 읽는다.
3. 요청된 페이지 범위를 결정한다.
4. 각 목록 페이지에서 카드 메타데이터를 수집한다.
5. `article_id` 기준으로 중복을 제거한다.
6. `--list-only`가 아니면 상세 페이지를 순차 요청한다.
7. 상세 메타데이터, 목차, 페이월 여부를 추출한다.
8. 공개 미리보기 근거가 있는 목차 항목의 설명과 사용 상황을 생성한다.
9. `--download-thumbnails`가 있으면 검증된 대표 썸네일만 저장한다.
10. 콘텐츠 레코드를 `article_id` 오름차순이 아니라 **게시일 내림차순, 목록 발견 순서**로 정렬한다.
11. 목차 배열을 밈 레코드로 펼친다.
12. 임시 파일에 먼저 기록한 뒤 최종 CSV로 원자적 교체한다.
13. 성공·실패·목차 없음·설명 없음·이미지 저장·중복 건수를 요약 출력한다.

중단 시 데이터 유실을 줄이기 위해 페이지 또는 상세 N건 단위 체크포인트를 둘 수 있다. 임시 파일은 최종 파일과 같은 디렉터리에 둔다.

## 11. 오류 처리

- 목록 카드에 `article_id`, 제목, 날짜 중 하나가 없으면 해당 카드를 건너뛰고 경고한다.
- 날짜 파싱 실패 시 원문과 URL을 로그에 남기고 카드는 건너뛴다.
- 상세 요청 실패 시 목록 정보는 articles CSV에 유지한다.
- 상세 파싱 실패는 `detail_fetch_status=parse_error`로 기록한다.
- 상세 404는 `detail_fetch_status=http_error`로 기록하고 다음 글로 진행한다.
- 목차가 없는 것은 정상 상태로 취급하며 오류로 세지 않는다.
- 설명 근거가 없으면 오류로 처리하지 않고 `summary_status=insufficient_source`로 기록한다.
- 이미지 검증이나 저장 실패는 CSV 수집을 중단하지 않고 `thumbnail_download_status=failed`로 기록한다.
- 실패한 이미지의 `.part` 파일은 안전하게 삭제한다.
- 한 페이지의 카드가 0건인데 다음 페이지가 남아 있으면 사이트 구조 변경 가능성이 있으므로 실행을 실패 처리한다.
- 첫 페이지에서 페이지네이션 또는 카드 선택자가 모두 실패하면 빈 CSV를 성공 결과로 만들지 말고 비정상 종료한다.

로그에 본문 HTML 전체나 인증 정보가 출력되지 않게 한다.

## 12. 중복 및 재실행 정책

- 콘텐츠 기본키: `article_id`
- 밈 기본키: `meme_id`
- 같은 `article_id`가 여러 페이지에서 발견되면 첫 발견 순서를 유지하고 최신 파싱 값으로 병합한다.
- `--resume` 실행 시 `detail_fetch_status=success`인 기존 글은 다시 요청하지 않는다.
- 제목, 상태, 날짜처럼 바뀔 수 있는 목록 필드는 재실행 시 최신값으로 갱신한다.
- 출력 파일 내 기본키 중복은 허용하지 않는다.
- 같은 `article_id`의 썸네일 파일은 하나만 유지하고 해시가 같으면 다시 내려받지 않는다.

## 13. 테스트 요구사항

최소 단위 테스트:

1. 목록 카드에서 ID, 제목, 날짜, 상태, 이미지 URL 추출
2. 상태가 없는 카드의 `unknown` 처리
3. `data-pagecount` 파싱
4. 날짜를 `YYYY-MM-DD`로 변환
5. 상세 작성자와 작성자 ID 추출
6. 페이월 표시 탐지
7. 단순 번호 목차 파싱
8. 원형 번호가 포함된 계층 목차 파싱
9. 목차가 없는 상세 페이지 처리
10. 중복 `article_id` 제거
11. 429·5xx 재시도와 404 비재시도
12. CSV의 `utf-8-sig` 저장과 한글 재로딩
13. 공개 미리보기의 첫 목차 항목에 설명 생성
14. 설명 근거가 부족한 항목의 `insufficient_source` 처리
15. 요약 입력 원문이 CSV와 로그에 남지 않음
16. 이미지 옵션 기본 비활성화
17. 이미지 MIME 타입·최대 크기·안전한 파일명 검증
18. 이미지 저장 성공 시 경로, 크기, SHA-256 기록

실사이트 스모크 테스트:

```powershell
python careet_crawler.py --start-page 1 --end-page 1 --delay 1.5
```

스모크 테스트에서는 다음을 확인한다.

- articles가 1건 이상 생성됨
- `article_id`, 제목, 날짜, URL이 비어 있지 않음
- 상세 URL이 `https://www.careet.net/{숫자}` 형식임
- 한글이 깨지지 않음
- 기본 실행에서는 이미지 파일이 다운로드되지 않음
- 본문 텍스트가 CSV에 포함되지 않음

이미지 옵션 스모크 테스트는 별도로 실행한다.

```powershell
python careet_crawler.py --start-page 1 --end-page 1 --delay 1.5 --download-thumbnails
```

이 테스트는 사용자가 이미지 저장 권한과 이용 조건을 확인한 환경에서만 수행한다. 성공 시 대표 썸네일만 저장되고 본문 이미지가 없어야 한다.

## 14. 완료 조건

아래 조건을 모두 만족해야 구현 완료로 본다.

- [ ] 전체 페이지 수를 HTML에서 동적으로 탐지한다.
- [ ] 목록과 상세 파서가 함수 또는 클래스로 분리되어 있다.
- [ ] articles 및 memes CSV를 지정된 스키마로 생성한다.
- [ ] 목차가 없는 글과 상세 요청 실패가 전체 실행을 중단시키지 않는다.
- [ ] 기본 요청 간격이 1.5초 이상이다.
- [ ] 로그인·페이월 우회 코드가 없다.
- [ ] 공개 근거가 있는 밈에는 짧은 설명과 사용 상황이 생성된다.
- [ ] 근거가 부족한 설명은 추측하지 않고 상태값과 함께 비워 둔다.
- [ ] 요약 입력에 사용한 공개 원문을 CSV나 로그에 저장하지 않는다.
- [ ] 본문 삽입 이미지는 어떤 옵션에서도 저장하지 않는다.
- [ ] 대표 썸네일 저장은 명시적 옵션으로만 동작한다.
- [ ] 이미지 MIME 타입, 용량, 파일명, 해시를 검증한다.
- [ ] 재시도에 상한과 백오프가 있다.
- [ ] `--resume`과 중복 제거가 동작한다.
- [ ] 단위 테스트와 1페이지 스모크 테스트가 통과한다.
- [ ] README에 설치, 실행, 출력 경로, 제한사항이 설명되어 있다.

## 15. 구현 시 주의사항

- 목록의 `유행중` 상태는 정량적인 조회수 지표가 아니라 캐릿 편집 기준이다.
- 사이트에는 공개 조회수, 좋아요 수, 댓글 수가 없으므로 임의로 만들지 않는다.
- 하나의 상위 목차가 여러 하위 밈을 묶을 수 있으므로 평면 문자열 분할만으로 처리하지 않는다.
- 공개 미리보기는 보통 첫 목차 항목까지만 제공되므로 설명의 누락은 정상적인 데이터 제약이다.
- 대표 썸네일은 기사 단위 자료이며 개별 밈의 직접 이미지라고 해석하지 않는다.
- 사이트의 공통 `og:description`은 글별 설명이 아니므로 저장하지 않는다.
- 2026-07-08 당시 확인한 선택자에 의존하되 구조 변경을 감지할 수 있도록 필수 필드 검증을 둔다.
- 현재 유튜브·네이버 데이터가 CSV 기반이므로 최종 결과도 CSV를 기본으로 한다.
