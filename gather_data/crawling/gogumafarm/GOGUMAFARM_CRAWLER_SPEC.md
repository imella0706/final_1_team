# 고구마팜 `밈` 게시물 수집기 구현 명세

## 1. 문서 목적

이 문서는 다른 에이전트가 고구마팜의 `최신 밈과 트렌드` 카테고리 중 `밈` 태그가 붙은 공개 게시물만 수집하는 Python 프로그램을 구현할 수 있도록 요구사항을 고정한다.

이 단계에서는 크롤러 코드를 작성하지 않는다. 구현자는 이 문서를 기준으로 코드, 테스트, 실행 문서를 작성한다.

## 2. 확정된 요구사항

- 사용 목적: 내부 분석 및 개인 학습
- 대상 사이트: `https://gogumafarm.kr/`
- 대상 카테고리: `최신 밈과 트렌드`
- 대상 태그: `밈`
- 저장 형식: UTF-8 JSON
- 수집 방식: 공개 WordPress REST API 우선
- 저장 대상: 메타데이터, 태그, 제목 구조, 외부 출처 URL, 규칙 기반 자체 요약
- 저장 제외: 본문 전체, 본문 HTML, 본문 이미지 파일, 이미지 바이너리, 쿠키, 계정 정보
- 로그인, 인증 우회, 비공개 API 탐색, 브라우저 자동화는 사용하지 않는다.
- LLM 및 외부 요약 API를 사용하지 않는다.

## 3. 확인된 공개 API

2026-07-08 확인 기준:

| 항목 | 값 |
|---|---|
| WordPress API | `https://gogumafarm.kr/wp-json/wp/v2` |
| 카테고리 slug | `trends` |
| 카테고리 ID | `384` |
| 카테고리 이름 | `최신 밈과 트렌드` |
| 태그 이름 | `밈` |
| 태그 ID | `110` |
| 태그 slug | URL 인코딩된 `밈` (`%eb%b0%88`) |
| 카테고리 전체 게시물 | 228건 |
| 사이트 전체 `밈` 태그 게시물 | 93건 |
| 카테고리와 태그의 교집합 | 72건 |

건수는 변하는 값이므로 테스트의 고정 기대값으로 사용하지 않는다. ID도 영구 불변이라고 가정하지 말고 실행 시 아래 API로 이름과 slug를 검증한다.

```text
GET /wp-json/wp/v2/categories?slug=trends
GET /wp-json/wp/v2/tags/110
```

태그 ID 조회가 실패하거나 이름이 `밈`이 아니면 태그 목록 API에서 이름 또는 URL 디코딩된 slug가 `밈`인 항목을 다시 찾는다. 카테고리도 동일하게 검증해서, `slug=trends` 조회가 실패하거나 반환된 이름이 `최신 밈과 트렌드`가 아니면 카테고리 목록 API에서 이름이 `최신 밈과 트렌드`인 항목을 다시 찾는다. 이름이 일치하지 않는 고정 ID를 그대로 사용하면 안 된다.

## 4. 수집 범위

두 조건을 모두 만족하는 `publish` 상태의 게시물만 저장한다.

1. 카테고리 ID 목록에 `최신 밈과 트렌드` 카테고리 ID가 있다.
2. 태그 ID 목록에 `밈` 태그 ID가 있다.

권장 요청:

```text
GET /wp-json/wp/v2/posts
    ?categories=384
    &tags=110
    &status=publish
    &per_page=100
    &page=1
    &orderby=date
    &order=desc
    &_embed=1
```

실제 구현에서는 URL 인코딩과 query parameter 조립을 `requests`에 맡긴다. 문자열 연결로 URL을 직접 만들지 않는다.

응답 헤더 `X-WP-Total`과 `X-WP-TotalPages`를 읽어 전체 페이지를 순회한다. 현재 대상은 100건 이하이지만 한 페이지뿐이라고 가정하면 안 된다.

`_fields`로 응답을 줄일 경우 다음 항목을 포함한다. WordPress 임베딩이 유지되도록 `_links`와 `_embedded`도 포함해야 한다.

```text
id,date,date_gmt,modified,modified_gmt,slug,status,link,title,content,
excerpt,author,featured_media,categories,tags,_links,_embedded
```

## 5. API 우선 원칙

- HTML 카테고리 페이지를 기본 수집 경로로 사용하지 않는다.
- 게시물 ID, 작성자, taxonomy, 대표 이미지는 REST API 값을 사용한다.
- 공개 API가 일시적으로 실패하면 제한된 재시도 후 명확히 실패한다.
- API 장애 시 HTML 스크래핑으로 조용히 전환하지 않는다. 두 방식의 결과가 달라지는 것을 막기 위함이다.
- REST API의 `content.rendered`는 파싱 중 메모리에서만 사용하고 결과 JSON에 저장하지 않는다.

## 6. JSON 출력 구조

출력 파일 기본 경로:

```text
data/gogumafarm_memes_YYYYMMDD.json
```

JSON은 `ensure_ascii=False`, 들여쓰기 2칸, UTF-8로 저장한다. 최상위는 실행 메타데이터와 게시물 배열을 가진 객체로 만든다.

```json
{
  "schema_version": "1.0",
  "source": "gogumafarm",
  "source_url": "https://gogumafarm.kr/category/trends/",
  "category": {
    "id": 384,
    "name": "최신 밈과 트렌드",
    "slug": "trends"
  },
  "tag": {
    "id": 110,
    "name": "밈",
    "slug": "밈"
  },
  "collected_at": "2026-07-08T00:00:00+09:00",
  "api_reported_total": 72,
  "article_count": 72,
  "meme_item_count": 0,
  "articles": []
}
```

각 `articles` 항목은 다음 구조를 사용한다.

```json
{
  "post_id": 53907,
  "url": "https://gogumafarm.kr/.../",
  "slug": "...",
  "title": "게시물 제목",
  "status": "publish",
  "published_at": "2026-06-23T04:00:00Z",
  "published_local": "2026-06-23T13:00:00",
  "modified_at": "2026-06-23T08:09:13Z",
  "modified_local": "2026-06-23T17:09:13",
  "author": {
    "id": 99,
    "name": "작성자 이름"
  },
  "categories": [
    {"id": 384, "name": "최신 밈과 트렌드", "slug": "trends"}
  ],
  "tags": [
    {"id": 110, "name": "밈", "slug": "밈"}
  ],
  "excerpt": "공개 excerpt를 HTML 없이 정리한 텍스트",
  "featured_image": {
    "id": 53910,
    "url": "https://gogumafarm.kr/wp-content/uploads/...",
    "mime_type": "image/png",
    "alt_text": ""
  },
  "heading_structure": [
    {"level": 2, "text": "상위 제목", "order": 1},
    {"level": 3, "text": "하위 제목", "order": 2}
  ],
  "external_sources": [
    {
      "url": "https://example.com/source",
      "domain": "example.com",
      "anchor_text": "출처 이름",
      "type": "link"
    }
  ],
  "summary": "이 글은 제목과 주요 소제목을 기준으로 핵심 주제를 정리한 게시물이다.",
  "summary_method": "rule",
  "meme_extraction_status": "success",
  "meme_items": [
    {
      "meme_id": "53907_1",
      "name": "밈 이름",
      "position": 1,
      "heading_level": 2,
      "section_path": ["밈 이름"],
      "summary": "제목 구조에서 확인된 범위만 보수적으로 정리한 설명",
      "source_urls": ["https://example.com/source"],
      "extraction_source": "heading_structure",
      "extraction_status": "success"
    }
  ],
  "fetch_status": "success",
  "collected_at": "2026-07-08T00:00:00+09:00"
}
```

값을 얻지 못한 선택 필드는 타입별로 통일한다. 문자열은 `""`, 배열은 `[]`, 객체는 `null`을 사용한다. 예를 들어 대표 이미지가 없는 게시물(`featured_media=0`)의 `featured_image`는 `null`로 저장한다. 배열 필드는 항상 배열로 저장한다.

최상위 필드는 다음 관계를 항상 만족해야 한다. 위 최상위 예시는 지면상 `articles`를 비워 둔 것이며 실제 파일에서는 이 관계가 지켜져야 한다.

- `api_reported_total`: 마지막으로 검증한 `X-WP-Total` 값
- `article_count`: `articles` 배열 길이 (`fetch_status=parse_error` 게시물 포함)
- `meme_item_count`: 모든 게시물의 `meme_items` 길이 합계

## 7. 필드별 처리 규칙

### 7.1 텍스트 정리

- HTML entity를 디코딩한다.
- 태그를 제거하고 연속 공백과 줄바꿈을 한 칸으로 정규화한다.
- 제목과 소제목의 원래 순서를 보존한다.
- `excerpt`는 공개 API의 `excerpt.rendered`에서 텍스트만 추출하고 최대 500자로 제한한다.

### 7.2 시간

- `date_gmt`, `modified_gmt`를 UTC `Z` 형식으로 변환해 `published_at`, `modified_at`에 저장한다.
- 원본 `date`, `modified`도 `published_local`, `modified_local`로 보존한다.
- 수집 시각(`collected_at`)은 Asia/Seoul(+09:00) 기준으로, timezone이 포함된 ISO 8601로 저장한다.

### 7.3 작성자, taxonomy, 대표 이미지

- `_embedded.author`에서 작성자 이름을 가져온다.
- `_embedded["wp:term"]`을 taxonomy 기준으로 분리해 카테고리와 태그 이름을 얻는다.
- 카테고리와 태그 slug는 URL 디코딩한 값으로 저장한다.
- `_embedded["wp:featuredmedia"]`에서 대표 이미지 URL, MIME, 대체 텍스트를 얻는다.
- 대표 이미지 URL은 메타데이터로만 기록하고 파일을 다운로드하지 않는다.
- `featured_media`가 `0`이면 대표 이미지가 없는 것이므로 `featured_image`를 `null`로 저장한다.
- ID는 있지만 임베딩 값이 없으면 ID는 유지하고 나머지 값은 빈 문자열로 둔다. 누락 때문에 전체 실행을 실패시키지 않는다.

### 7.4 제목 구조

- `content.rendered` 안의 `h2`, `h3`, `h4`만 문서 순서대로 추출한다.
- 각 항목에 heading level과 전체 순번을 저장한다.
- 빈 제목, 공유 버튼, 반복되는 사이트 공통 문구는 제거한다.
- 모든 소제목을 독립적인 밈 이름으로 간주하지 않는다. 이 카테고리에는 여러 형식의 글이 섞여 있기 때문이다.

### 7.5 외부 출처 URL

- `content.rendered` 안의 `a[href]`와 `iframe[src]`에서 추출한다. 밈 출처가 YouTube 등 임베드로만 표기된 경우를 놓치지 않기 위한 것이며, iframe은 URL만 기록하고 임베드 콘텐츠를 요청하거나 다운로드하지 않는다.
- 각 항목의 `type`에 `a[href]`는 `link`, `iframe[src]`는 `embed`를 기록한다.
- `anchor_text`는 `link`면 링크 텍스트, `embed`면 iframe의 `title` 속성을 사용하고 없으면 빈 문자열로 둔다.
- `http`와 `https`만 허용한다.
- `gogumafarm.kr` 내부 링크, fragment, `mailto:`, `tel:`, `javascript:`는 제외한다.
- URL fragment는 제거하고 동일한 정규화 URL은 `type`과 무관하게 첫 번째 항목만 유지한다.
- 원래 등장 순서를 유지한다.
- hostname을 `domain`으로 함께 기록한다.

### 7.6 자체 요약

- LLM이나 외부 API를 사용하지 않는다.
- 제목과 정리된 상위 소제목만 사용해 1~2문장의 보수적인 템플릿 요약을 만든다.
- 본문 문장을 그대로 복사하지 않는다.
- 근거가 제목밖에 없으면 제목 주제를 다루는 글이라는 수준으로만 작성한다.
- 최대 200자로 제한하고 `summary_method`는 `rule`로 기록한다.
- 요약 생성에 실패해도 게시물 수집은 성공으로 처리하고 요약만 빈 값으로 둔다.

### 7.7 개별 밈 항목 추출

게시물 단위 메타데이터만으로는 내부 밈 분석에 부족하므로, 신뢰할 수 있는 구조가 확인되는 게시물에서는 개별 밈을 `meme_items`로 분리한다.

- `meme_items`는 각 `article` 내부의 배열로 저장한다.
- `meme_id`는 `{post_id}_{position}` 형식으로 만든다. `position`은 게시물 안의 등장 순서이며 1부터 시작한다.
- `meme_id`는 실행 간 안정성을 보장하지 않는다. 게시물 수정으로 제목 순서가 바뀌면 같은 밈의 `meme_id`가 달라질 수 있으므로, 실행 간 추적에는 `post_id`와 정규화한 이름의 조합을 사용한다.

추출은 다음 용어 정의를 기준으로 한다.

- 설명용 제목: 공백과 문장부호를 제거해 정규화한 제목이 `어떤 밈인가요`, `유래`, `왜 유행하나요`, `어떻게 활용하나요`, `마케팅 활용`, `출처` 목록의 항목과 완전 일치하거나 해당 항목으로 시작하는 제목.
- 후보 제목: `h2`~`h4` 중 설명용 제목이 아니고 7.4에서 제거하는 사이트 공통 문구도 아닌 제목.
- 제목 구간: 후보 제목부터 같은 레벨 이상의 다음 제목 직전까지.
- 확정 조건: 제목 구간 안에 설명용 하위 제목이 1개 이상 있거나 외부 출처 URL이 1개 이상 있다.

`meme_extraction_status`는 다음 순서로 기계적으로 판정한다.

1. `content.rendered` HTML 파싱 실패 → `parse_error`
2. `h2`~`h4` 제목이 하나도 없음 → `unsupported_structure`
3. 후보 제목이 0개 → `no_items`
4. 확정 조건을 만족하는 후보가 0개 → `unsupported_structure`
5. 그 외 → `success`, 확정된 후보만 `meme_items`로 저장

- `meme_extraction_status`가 `success`가 아니면 `meme_items=[]`로 저장하고 항목을 추측하지 않는다.
- 한 게시물 안에서 같은 정규화 이름이 반복되면 첫 항목을 유지하고 중복을 기록한다.
- 항목별 `source_urls`에는 해당 제목 구간 안에서 발견한 외부 URL만 연결한다.
- 항목별 요약은 해당 구간의 제목 구조만 이용해 보수적으로 생성한다. 본문 문장을 복사하지 않는다.
- 원문 구간 텍스트는 파싱 중 메모리에서만 사용하고 JSON, 로그, 캐시에 저장하지 않는다.
- 최상위 `meme_item_count`는 모든 게시물의 `meme_items` 길이 합계와 같아야 한다.

## 8. 네트워크 정책

- Python 3.11 이상, `requests`, `beautifulsoup4` 사용을 권장한다.
- 고정되고 식별 가능한 User-Agent를 사용한다.
- 요청 사이 기본 1초 이상 대기한다.
- connect/read timeout을 각각 설정한다.
- HTTP 429와 5xx만 지수 백오프로 최대 3회 재시도한다.
- `Retry-After`가 있으면 이를 우선한다.
- 400, 401, 403, 404는 무한 재시도하지 않는다.
- 한 요청 실패가 전체 결과의 무결성을 깨뜨리면 불완전한 최종 파일을 성공 파일처럼 남기지 않는다.

## 9. 저장 안정성 및 갱신

- 임시 파일에 쓴 뒤 원자적으로 최종 JSON 파일로 교체한다.
- 게시물 ID를 고유 키로 사용해 중복을 제거한다.
- 최종 정렬은 `published_at` 내림차순, 같은 시각이면 `post_id` 내림차순으로 한다.
- API가 보고한 총건수(`X-WP-Total`)와 목록 수집 단계에서 필터 검증을 통과한 고유 게시물 수가 다르면 실패 또는 강한 경고로 처리한다. 이 검증은 목록 수집 단계 기준이다. 이후 파싱 단계의 `parse_error`와 필수 필드 누락 제외는 이 검증에 포함하지 않고 종료 통계와 경고로 보고한다.
- 이후 증분 갱신 시 기존 `post_id`와 `modified_at`을 비교해 신규 또는 수정 게시물만 다시 파싱할 수 있게 구조를 분리한다.
- 증분 갱신을 구현하더라도 매 실행 시 목록 메타데이터는 전체 1~수 페이지를 확인한다. 현재 규모에서는 최대 100건 단위 조회 비용이 작다.
- 10개 게시물 처리마다 허용된 출력 필드만 담은 체크포인트를 원자적으로 갱신한다. 체크포인트에도 본문과 본문 HTML을 저장하지 않는다.
- 정상 종료 후 체크포인트를 삭제한다. 중단 시에는 체크포인트를 보존한다.

### 9.1 재개 파일 선택과 병합

- `--resume`은 출력 디렉터리의 체크포인트를 먼저 찾고, 없으면 파일명의 날짜(`YYYYMMDD`)가 가장 최신인 `gogumafarm_memes_*.json`을 읽는다. 파일명에서 날짜를 파싱할 수 없는 파일은 무시한다.
- `--resume-from PATH`가 지정되면 자동 선택 대신 해당 파일을 사용한다. `--resume-from`은 `--resume`을 암시한다.
- 재개 파일의 `schema_version`, `source`, 카테고리 이름 또는 slug, 태그 이름이 현재 명세와 일치하지 않으면 재사용하지 않고 실패한다.
- API 목록은 재개 실행에서도 전체를 다시 조회한다.
- 기존 `post_id`의 `modified_at`이 API 값과 같으면 제목 구조, 외부 출처, 요약, `meme_items`를 재사용한다.
- 신규 게시물이나 `modified_at`이 변경된 게시물은 다시 파싱한다.
- 더 이상 API 교집합에 없는 기존 게시물은 새 결과에서 제거하되 제거 건수를 종료 통계에 남긴다.
- 재개 파일은 위 규칙에 따라 항상 1개만 선택하며 여러 재개 파일을 병합하지 않는다.

## 10. 개인정보 및 저작권 경계

- 공개 API에서 제공하더라도 `content.rendered` 전체를 JSON, 로그, fixture에 저장하지 않는다.
- 본문 이미지, GIF, 동영상, iframe을 다운로드하지 않는다.
- 원문 단락이나 긴 문장을 요약이라는 이름으로 복제하지 않는다.
- 작성자 이름은 공개 게시물 메타데이터 범위에서만 저장한다.
- 이메일, 전화번호 등 본문에서 발견된 개인정보는 별도 필드로 추출하지 않는다.
- 로그에는 본문, excerpt 전체, 쿠키, 응답 전체를 출력하지 않는다.
- 2026-07-09 확인 기준 robots.txt는 모든 경로를 허용한다(`User-agent: *`, `Allow: /`). robots 정책과 이용약관이 바뀌면 운영 전에 다시 검토한다.

## 11. 오류 상태

게시물별 `fetch_status`는 다음 중 하나를 사용한다.

- `success`: 필수 메타데이터와 구조화 결과 생성 완료
- `partial`: 게시물은 저장했지만 임베딩 등 선택 정보 일부 누락
- `parse_error`: 필수 필드는 확보했지만 본문 구조 추출(제목 구조, 외부 출처, 밈 항목)에 실패. 게시물은 `articles`에 저장하되 구조 필드는 빈 값으로 두고 `meme_extraction_status=parse_error`로 기록한다.

필수 필드는 `post_id`, `url`, `title`, `status`, 게시일이다. 필수 필드가 하나라도 없는 항목은 `articles`에 저장하지 않는다. 제외 건수는 강한 경고와 종료 통계로 남기고 9장의 총건수 검증에는 포함하지 않는다.

### 11.1 API 응답 검증

- 성공 응답의 `Content-Type`이 JSON인지 확인한다.
- 게시물 목록 응답이 JSON 배열인지 확인하고 WordPress 오류 객체를 목록으로 오인하지 않는다.
- `X-WP-Total`, `X-WP-TotalPages`가 존재하며 0 이상의 정수인지 확인한다.
- 마지막 페이지 전인데 빈 배열이 반환되면 페이지네이션 변경 또는 서버 오류로 보고 실패한다.
- 각 게시물의 `status=publish`, 대상 카테고리 ID 포함, `밈` 태그 ID 포함 여부를 다시 검사한다.
- 필터 밖 게시물이 반환되면 저장하지 않고 강한 경고와 건수를 남긴다.
- 첫 페이지와 마지막 페이지 사이에 `X-WP-Total`이 달라지면 게시물 변경 가능성을 기록하고 처음부터 한 번만 다시 수집한다.
- 재수집에서도 총건수가 변하거나 고유 게시물 수가 API 총건수와 다르면 최종 파일을 성공 결과로 교체하지 않는다.
- JSON 디코딩 오류나 필수 응답 구조 누락 시 응답 본문 전체를 로그에 남기지 않는다.

## 12. CLI 요구사항

구현 프로그램은 최소한 다음 옵션을 제공한다.

```text
--output-dir PATH       기본 ./data
--delay FLOAT           요청 간 대기, 기본 1.0초, 최소 1.0초
--timeout FLOAT         connect/read timeout 기준값, 기본 15초
--retries INT           재시도 횟수, 기본 3
--resume
--resume-from PATH
--dry-run
--log-level DEBUG|INFO|WARNING|ERROR
```

`--dry-run`은 taxonomy ID, API 응답 헤더, 대상 건수, 첫 페이지의 필터 일치 여부만 검증하고 JSON과 체크포인트를 저장하지 않는다.

기본 실행 예시:

```powershell
python gogumafarm_crawler.py
```

## 13. 파일 및 코드 구조

구현 결과는 다음 구조를 기본으로 한다.

```text
gogumafarm/
├─ GOGUMAFARM_CRAWLER_SPEC.md
├─ gogumafarm_crawler.py
├─ README.md
├─ requirements.txt
├─ data/
│  └─ gogumafarm_memes_YYYYMMDD.json
└─ tests/
   ├─ test_gogumafarm_crawler.py
   └─ fixtures/
      ├─ taxonomy.json
      ├─ posts_page.json
      └─ rendered_content.html
```

네트워크 클라이언트, API 파싱, 본문 구조 추출, 밈 항목 추출, 요약, JSON 저장을 각각 함수나 클래스로 분리한다. HTTP 요청 함수 안에서 파일을 저장하거나 요약을 생성하지 않는다.

## 14. 실행 흐름 및 종료 통계

구현은 다음 순서를 따른다.

1. CLI 인자와 출력 경로를 검증한다.
2. 공개 category/tag API로 대상 taxonomy ID와 이름을 확인한다.
3. 첫 게시물 페이지에서 총건수와 총페이지를 읽는다.
4. 모든 페이지를 순회하고 필터를 재검증한다.
5. `post_id` 기준 중복을 제거하고 총건수 일치를 확인한다.
6. 재개 파일이 있으면 스키마를 검증하고 수정되지 않은 결과를 재사용한다.
7. 신규·수정 게시물의 제목 구조와 외부 출처를 추출한다.
8. 신뢰 가능한 게시물에서만 개별 `meme_items`를 추출한다.
9. 게시물 및 밈 항목 요약을 생성한다.
10. 체크포인트를 갱신하고 최종 정렬·검증 후 JSON을 원자적으로 저장한다.

정상 종료 시 최소한 다음 통계를 로그로 한 번 출력한다.

- API 보고 대상 건수와 최종 게시물 건수
- 수집 성공, 부분 성공, 파싱 실패 건수와 필수 필드 누락으로 제외한 건수
- 신규, 수정, 재사용, 제거 게시물 건수
- 밈 항목 수와 `success`, `no_items`, `unsupported_structure`, `parse_error` 게시물 수
- 중복 게시물과 중복 밈 이름 제거 건수
- 고유 외부 출처 URL 수

로그에는 진행률을 `처리 건수/전체 건수` 형식으로 표시하되 본문, excerpt 전체, 응답 JSON 전체를 출력하지 않는다.

## 15. 테스트 요구사항

실제 사이트를 호출하지 않는 단위 테스트를 작성한다.

- 카테고리와 태그 확인
- 카테고리와 태그 교집합 필터
- `X-WP-TotalPages` 기반 페이지 순회
- HTML entity 및 공백 정리
- `h2`~`h4` 제목 구조와 순서
- 설명용 소제목 제외와 근거 기반 `meme_items` 추출
- 상태 판정 순서: 제목이 없거나 근거 없는 후보만 있으면 `unsupported_structure`, 후보 자체가 없으면 `no_items`
- 밈 이름과 `meme_id` 중복 방지
- 내부 링크 제외, 외부 URL 중복 제거, `iframe[src]` 임베드 수집과 `type` 구분
- 작성자, taxonomy, 대표 이미지 임베딩 누락 처리
- 규칙 기반 요약이 본문 문장을 복사하지 않는지 확인
- 게시물 ID 중복 제거
- UTF-8 한글 JSON 왕복
- 원자적 저장
- 체크포인트 저장, 재개 파일 선택, 수정되지 않은 게시물 재사용
- 잘못된 schema 또는 다른 category/tag 재개 파일 거부
- 429와 5xx 재시도, 404 미재시도
- JSON이 아닌 응답, WordPress 오류 객체, 잘못된 페이지 헤더 거부
- 수집 도중 총건수 변경 시 1회 재수집 후 실패 처리
- 최종 JSON에 `content`, `content_html`, 이미지 바이너리 필드가 없는지 확인

fixture에는 실제 게시물 본문을 복사하지 않는다. 필요한 구조만 담은 짧은 합성 JSON과 HTML을 사용한다.

단위 테스트와 별도로 다음 실제 API 스모크 테스트 절차를 README에 기록한다.

```powershell
python gogumafarm_crawler.py --dry-run
```

스모크 테스트는 JSON 파일을 만들지 않아야 하며, category/tag 검증 성공 여부, API 대상 건수, 페이지 수만 출력해야 한다. 실제 건수 자체는 고정하지 않는다.

## 16. 완료 조건

다음을 모두 만족해야 구현 완료로 본다.

1. 공개 WordPress API만 사용한다.
2. `최신 밈과 트렌드`와 `밈` 태그의 교집합만 수집한다.
3. 모든 결과에 `밈` 태그와 대상 카테고리가 포함되어 있다.
4. 페이지 수와 게시물 수를 응답 헤더에서 동적으로 처리한다.
5. 출력은 유효한 UTF-8 JSON이며 스키마가 일관된다.
6. 본문 전체와 이미지 파일이 저장되지 않는다.
7. 제목 구조, 외부 출처, 규칙 기반 요약이 저장된다.
8. 신뢰 가능한 구조에서만 개별 `meme_items`가 생성되고 불확실한 구조는 명시적으로 표시된다.
9. `--resume`과 `--resume-from`의 선택·검증·병합 규칙이 동작한다.
10. API 응답 형식, 필터, 총건수 변경을 검증한다.
11. 네트워크 오류와 중단 시 손상된 최종 파일을 만들지 않는다.
12. 단위 테스트가 실제 네트워크 없이 통과한다.
13. `--dry-run` 스모크 테스트가 결과 파일 없이 성공한다.
14. README에 설치, 실행, 출력, 제한사항을 기록한다.
