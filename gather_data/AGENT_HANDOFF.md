# gather_data 폴더 agent 핸드오프

이 문서는 다른 agent가 `gather_data/` 전체를 이어받기 위한 기능 요약이다. 현재 폴더는 크게 `crawling`, `naver`, `youtube` 세 영역으로 나뉜다.

## 전체 구조

```text
gather_data/
├─ .gitignore
├─ crawling/
├─ naver/
└─ youtube/
```

## 공통 환경

- API 키는 repository의 canonical 환경 파일인 `apps/api/.env`에서 읽는다.
- 실제 `.env`는 출력하거나 커밋하지 않는다.
- 환경 변수 예시는 `apps/api/.env.gcp.example` 하나에서 관리한다.

필요한 환경 변수:

```text
YOUTUBE_API_KEY=
NAVER_CLIENT_ID=
NAVER_CLIENT_SECRET=
```

`gather_data/`는 크롤러 코드, 명세, 테스트, 의존성 파일만 Git으로 추적한다.
생성된 JSON/CSV/PNG와 source별 `data/`, `history/`, `reports/`는 추적하지
않으며, 공식 데이터셋은 repository root의 `data/` 계층에서 관리한다.

## 전체 목적

`gather_data/`는 최신 밈·트렌드 분석용 데이터를 여러 출처에서 모으는 작업 영역이다.

- `crawling/`: 캐릿, 고구마팜 등 콘텐츠 사이트에서 밈/트렌드 메타데이터 수집
- `naver/`: 네이버 검색 API와 데이터랩 API로 특정 키워드의 블로그·뉴스·검색량 흐름 수집
- `youtube/`: YouTube 인기 급상승 영상과 키워드 변화를 수집

이 데이터는 모델 fine-tuning용 원천 데이터라기보다, 이후 마케팅 agent가 광고를 생성할 때 RAG/프롬프트 컨텍스트로 사용할 트렌드 데이터베이스 후보로 보는 것이 맞다.

## `crawling/`

### 역할

콘텐츠 사이트에서 공개 메타데이터와 밈/트렌드 항목을 구조화해서 수집한다.

현재 하위 사이트:

```text
crawling/
├─ AGENT_HANDOFF.md
├─ careet/
└─ gogumafarm/
```

상세 내용은 [crawling/AGENT_HANDOFF.md](C:/Users/user/final_1_team/gather_data/crawling/AGENT_HANDOFF.md)를 먼저 읽는다.

### `crawling/careet/`

캐릿 `요즘 뜨는 밈` 시리즈에서 비로그인 공개 메타데이터와 목차 기반 밈 항목을 수집한다.

주요 파일:

```text
crawling/careet/
├─ CAREET_CRAWLER_SPEC.md
├─ careet_crawler.py
├─ README.md
├─ requirements.txt
├─ data/
├─ data-smoke/
├─ data-smoke-detail/
└─ tests/
```

대표 실행:

```powershell
cd gather_data\crawling\careet
python careet_crawler.py
python -m unittest discover -s tests -v
```

현재 확인된 최신 산출물:

- `data/raw/careet_articles_20260709.csv`: 136 rows
- `data/processed/careet_memes_20260709.csv`: 134 rows

현재 테스트 상태:

- `careet` 폴더 기준 19 tests passed.

### `crawling/gogumafarm/`

고구마팜 WordPress REST API에서 `최신 밈과 트렌드` 카테고리와 `밈` 태그의 교집합 게시물만 수집한다.

주요 파일:

```text
crawling/gogumafarm/
├─ GOGUMAFARM_CRAWLER_SPEC.md
├─ gogumafarm_crawler.py
├─ README.md
├─ requirements.txt
├─ data/
└─ tests/
```

대표 실행:

```powershell
cd gather_data\crawling\gogumafarm
python gogumafarm_crawler.py
python gogumafarm_crawler.py --dry-run
python -m unittest discover -s tests -v
```

현재 확인된 최신 산출물:

- `data/gogumafarm_memes_20260709.json`: `article_count=72`, `meme_item_count=95`
- `data/raw/gogumafarm_articles_20260709.csv`: 72 rows
- `data/processed/gogumafarm_meme_terms_20260709.csv`: 89 rows
- `data/final_processed/gogumafarm_meme_terms_20260709.json`: 84 items

현재 테스트 상태:

- `gogumafarm` 폴더 기준 13 tests passed.

### crawling 공통 주의사항

- 로그인, 쿠키, 인증 우회, 유료 장벽 우회 금지.
- 본문 전체, 본문 HTML, 이미지 바이너리 저장 금지.
- 실제 운영 전 각 사이트 robots 정책과 이용약관을 다시 확인한다.
- 테스트는 각 사이트 폴더에서 실행한다. `final_1_team` 루트에서 직접 실행하면 import 경로 문제로 실패할 수 있다.

## `naver/`

### 역할

네이버 검색 API와 네이버 데이터랩 API를 사용해 특정 키워드의 온라인 언급량과 검색량 흐름을 수집·분석한다.

현재 스크립트는 `KEYWORD = "카페"`로 고정되어 있다. 다른 키워드를 분석하려면 `step1_collect.py`, `step2_datalab.py`, `step3_analyze.py`의 `KEYWORD` 값을 같은 값으로 맞춰야 한다.

### 주요 파일

```text
naver/
├─ step1_collect.py
├─ step2_datalab.py
├─ step3_analyze.py
├─ naver_blog_카페.csv
├─ naver_news_카페.csv
├─ datalab_카페.csv
├─ word_freq.csv
├─ trend_monthly.png
├─ trend_words.png
└─ trend_search.png
```

### 단계별 기능

#### `step1_collect.py`

네이버 검색 API로 블로그와 뉴스 문서를 최신순으로 수집한다.

- 사용 API: `https://openapi.naver.com/v1/search/{blog|news}.json`
- 필요 키: `NAVER_CLIENT_ID`, `NAVER_CLIENT_SECRET`
- 현재 키워드: `카페`
- 수집량: source별 최대 1,000건
- 출력:
  - `naver_blog_카페.csv`
  - `naver_news_카페.csv`

현재 산출물:

- `naver_blog_카페.csv`: 946 rows
- `naver_news_카페.csv`: 999 rows

#### `step2_datalab.py`

네이버 데이터랩 API로 키워드 검색량 추이를 수집한다.

- 사용 API: `https://openapi.naver.com/v1/datalab/search`
- 필요 키: `NAVER_CLIENT_ID`, `NAVER_CLIENT_SECRET`
- 현재 키워드: `카페`
- 현재 기간: `2024-07-01` ~ `2026-06-30`
- 현재 단위: `week`
- 출력:
  - `datalab_카페.csv`

현재 산출물:

- `datalab_카페.csv`: 105 rows
- 컬럼: `period`, `ratio`

#### `step3_analyze.py`

`step1`, `step2` 결과를 사용해 시각화와 단어 빈도표를 만든다.

- 입력:
  - `naver_blog_카페.csv`
  - `datalab_카페.csv`
- 선택 의존성:
  - `kiwipiepy`: 설치되어 있으면 명사 기반 단어 분석 수행
- 출력:
  - `trend_monthly.png`: 월별 블로그 글 수
  - `trend_words.png`: 자주 등장하는 단어 TOP 20
  - `trend_search.png`: 네이버 데이터랩 검색량 추이
  - `word_freq.csv`: 단어 빈도표

현재 산출물:

- `word_freq.csv`: 20 rows
- `trend_monthly.png`
- `trend_words.png`
- `trend_search.png`

### 실행 순서

`gather_data/naver`에서 실행한다.

```powershell
python step1_collect.py
python step2_datalab.py
python step3_analyze.py
```

### naver 주의사항

- 현재 스크립트는 argparse가 없고 상단 상수 수정 방식이다.
- `KEYWORD`를 세 스크립트에서 동일하게 맞춰야 산출물이 이어진다.
- 네이버 API 키가 없으면 `step1`, `step2`는 실행되지 않는다.
- API 응답 오류 시 일부 source에서 중단될 수 있다.
- 현재 별도 단위 테스트는 없다.

## `youtube/`

### 역할

YouTube Data API v3의 한국 `mostPopular` 영상 스냅샷을 수집하고, 같은 스냅샷에서 영상 단위 키워드 출현율을 계산해 날짜별 변화를 비교한다.

이 영역은 2026-07-10 리팩터링 후 다음 두 데이터 세대를 명시적으로 구분한다.

- legacy v1: 기존 `keyword,count` 발생 횟수 데이터. 읽기 전용 호환 대상.
- v2: Unicode 정규화와 고유 영상 단위 집계를 사용하는 새 데이터.

기존 루트 CSV, `history/`, 비교 CSV·PNG는 legacy 샘플로 그대로 둔다. 새 런타임 산출물은 Git에 섞이지 않도록 `data/`, `reports/` 아래에 생성하고 `youtube/.gitignore`에서 제외한다.

### 주요 파일

```text
youtube/
├─ README.md
├─ requirements.txt
├─ requirements-okt.txt
├─ youtube_trending_collector.py
├─ daily_keyword_tracker.py
├─ compare_trends.py
├─ youtube_trends/
│  ├─ config.py
│  ├─ collector.py
│  ├─ csv_io.py
│  ├─ keywords.py
│  └─ trends.py
├─ tests/
├─ data/                         # 새 실행 시 생성, Git 제외
│  ├─ raw/
│  └─ history/
├─ reports/                      # 새 실행 시 생성, Git 제외
├─ youtube_trending_KR_20260707.csv
├─ youtube_trending_KR_20260708.csv
├─ keyword_trend_comparison.csv
├─ keyword_trend_comparison.png
└─ history/
   ├─ keywords_2026-07-07.csv
   └─ keywords_2026-07-08.csv
```

세 기존 스크립트는 CLI 진입점이고, 재사용 가능한 수집·분석·파일 I/O는 `youtube_trends/` 패키지에 있다. import 시 API 호출이나 파일 생성은 하지 않는다.

#### `youtube_trending_collector.py`

YouTube `videos.list(chart="mostPopular")` 결과를 페이지 단위로 수집해 raw v2 CSV를 만든다.

- 필요 키: `YOUTUBE_API_KEY`
- 기본 지역/수량: `KR`, 100개
- 기본 출력: `data/raw/youtube_trending_KR_YYYYMMDD.csv`
- timeout, 재시도, 페이지 크기, 반복 page token, 중복 video ID, 빈 응답을 처리한다.
- CSV는 `utf-8-sig`와 원자적 교체를 사용한다.
- 기존 10개 컬럼을 앞부분에 유지하고 `schema_version`, `region_code`, `collected_at`, `tags_json`을 추가한다.
- 정확한 태그 배열은 `tags_json`이며, comma 문자열 `tags`는 legacy 호환용이다.
- `--fail-if-exists`는 API 호출 전에 기존 출력 존재 여부를 검사한다.
- Google client DEBUG logger는 API 키가 포함된 URL을 출력할 수 있으므로 항상 WARNING 이상으로 고정한다.

#### `daily_keyword_tracker.py`

raw 영상 CSV 또는 live API 응답에서 `keyword,count` 키워드 스냅샷을 만든다.

- 권장 입력: `--input-csv data/raw/youtube_trending_*.csv`. collector 결과를 재사용해 서로 다른 시점의 API 중복 호출을 피한다.
- 기본 출력: `data/history/keywords_YYYY-MM-DD.csv`
- sns_trend landing 공유용도 기존 채빈님 `youtube_keywords_YYYY-MM-DD.csv`
  형식과 동일하게 `keyword,count` 두 컬럼으로 출력한다.
- 내부 집계는 v2 snapshot 기준으로 수행하고, 외부 CSV에는 `display_keyword` -> `keyword`,
  `occurrence_count` -> `count`만 남긴다.
- 기본 tokenizer: 환경 간 재현성이 있는 `regex`.
- 선택 tokenizer: `okt`. 선택했는데 KoNLPy/Java가 없으면 regex로 조용히 fallback하지 않고 실패한다.
- 정규화: NFKC, casefold, 불용어 처리. `T1`, `t1`, `Ｔ１`은 canonical `t1`으로 합친다.
- 중복 `video_id`를 제거하고 한 키워드는 영상 하나당 `video_count`에 최대 1회 반영한다.
- `occurrence_count`는 반복 태그 진단용이며 순위 기준이 아니다.
- 주요 메타데이터: `sample_size`, `prevalence`, `channel_count`, tokenizer/normalizer/alias/stopword 버전, `analysis_signature`.
- 입력 CSV와 출력 CSV가 같은 경로면 원본 보호를 위해 실패한다.
- `--input-csv`와 `--limit`을 함께 쓰면 입력 순서 기준 앞 N개 영상만 분석한다.

#### `compare_trends.py`

호환되는 두 키워드 스냅샷을 비교해 CSV와 차트를 만든다.

- 기본 입력: `data/history/`에서 최신 스냅샷과 호환되는 직전 스냅샷.
- 기본 출력: `reports/keyword_trend_comparison.csv`, `reports/keyword_trend_comparison.png`.
- v1끼리는 `legacy_raw_count`, v2끼리는 `prevalence_v2`로 비교한다.
- v1/v2 혼합, 다른 region, 다른 `analysis_signature` 조합은 비교하지 않는다.
- 최신 스냅샷에 호환되는 이전 파일이 없으면 오래된 legacy 쌍으로 물러나지 않고 실패한다.
- v2 기본 변화량은 `delta_pp = new_prevalence - old_prevalence`의 퍼센트포인트다.
- 현재 지지 영상이 기본 2개 미만이면 `low_support`로 표시한다.
- 비교 CSV에는 canonical keyword, 기간, region, 양쪽 sample size와 분석 버전을 함께 저장한다.
- 입력 경로와 출력 경로 충돌을 거부한다.
- CSV와 PNG를 모두 임시 파일로 만든 뒤 함께 반영하며 실패 시 기존 보고서 쌍을 복원한다.

### 현재 보존 중인 legacy 산출물

- `youtube_trending_KR_20260707.csv`: 100 rows
- `youtube_trending_KR_20260708.csv`: 100 rows
- `history/keywords_2026-07-07.csv`: 1,652 rows
- `history/keywords_2026-07-08.csv`: 1,682 rows
- `keyword_trend_comparison.csv`: 2,355 rows
- `keyword_trend_comparison.png`

legacy history는 표본 크기와 영상별 출현 정보를 복원할 수 없으므로 v2 prevalence 데이터로 변환하지 않는다. 필요하면 `python compare_trends.py --history-dir history --no-plot`으로 v1끼리만 다시 비교한다.

### 실행 순서

`gather_data/youtube`에서 실행한다.

```powershell
python youtube_trending_collector.py
python daily_keyword_tracker.py --input-csv data\raw\youtube_trending_KR_YYYYMMDD.csv
python compare_trends.py
```

v2 비교에는 같은 분석 signature로 만든 날짜별 파일이 최소 2개 필요하다. 모든 CLI 옵션과 schema는 `youtube/README.md`를 먼저 확인한다.

### 설정과 테스트

- 필수 의존성: `requirements.txt`.
- 선택 Okt 의존성: `requirements-okt.txt`와 Java.
- API 키는 CLI 인자로 받지 않고 `apps/api/.env`의 `YOUTUBE_API_KEY`를 사용한다.
- CLI > 환경 변수 > 기본값 순서로 설정한다. 잘못된 미사용 환경 변수는 명시적 CLI 값을 막지 않는다.
- 날짜 기본 timezone은 `Asia/Seoul`이며 `YOUTUBE_TIMEZONE`으로 바꿀 수 있다.
- 성공 exit code `0`, API/파일/분석 실패 `1`, 설정 오류 `2`.
- 현재 오프라인 단위 테스트: 41 tests passed.

```powershell
cd gather_data\youtube
python -m unittest discover -s tests -v
python -m compileall -q .
```

테스트는 실제 YouTube API를 호출하지 않는다. pagination, API 키 로그 비노출, raw metadata 일관성, 태그 round-trip, Unicode 정규화, 영상 단위 집계, 분석 signature 호환, 입력/출력 충돌, 보고서 rollback과 PNG 생성을 검증한다.

### 남은 한계

- 실제 API smoke test와 스케줄러/CI 자동 실행은 아직 없다.
- `T1`과 `티원` 같은 의미 기반 alias, 다단어 개체명, 조회수 가중치, 7일 복합 점수는 아직 구현하지 않았다.
- 기본 regex tokenizer는 범용 Unicode 문자와 `i-dle`, `C++` 같은 내부 구두점을 보존하지만 언어별 형태소 의미 분석은 하지 않는다.
- Linux 차트에는 Noto Sans CJK KR 또는 NanumGothic 등 한글 폰트를 별도로 설치해야 할 수 있다.
- 새 v2 실행 결과는 아직 저장소에 생성하지 않았다. 기존 legacy 파일은 수정하지 않았다.

## 다른 agent가 작업할 때 권장 순서

1. `gather_data/AGENT_HANDOFF.md`를 먼저 읽는다.
2. `crawling` 작업이면 `gather_data/crawling/AGENT_HANDOFF.md`와 해당 사이트의 README/명세를 읽는다.
3. API 키가 필요한 작업이면 `apps/api/.env.gcp.example`의 키 이름만 확인하고, 실제 `.env` 값은 출력하지 않는다.
4. 기존 산출물을 덮어쓸 수 있는 스크립트는 실행 전에 목적과 출력 파일명을 확인한다.
5. 새 수집 소스를 추가할 때는 기존 구조처럼 독립 폴더와 README/명세/테스트를 함께 둔다.
6. 광고 생성 agent와 연결할 때는 원본 전체를 모델에 넣기보다, 각 출처의 결과를 트렌드 카드 형태로 정규화한 뒤 검색/RAG 컨텍스트로 사용하는 방향을 우선한다.

## 현재 Git 상태 참고

`crawling/` 쪽은 기존 루트 파일을 `careet/` 하위로 정리한 이력이 있어 Git에서는 삭제와 신규 파일이 동시에 보일 수 있다. 리뷰 시 단순 삭제가 아니라 이동/재구성인지 확인해야 한다.
