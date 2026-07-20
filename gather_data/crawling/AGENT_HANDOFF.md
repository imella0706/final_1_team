# Crawling 폴더 agent 핸드오프

이 문서는 다른 agent가 `gather_data/crawling` 하위 작업을 이어받기 위한 폴더별 기능 요약이다.

## 현재 최상위 구조

```text
gather_data/crawling/
├─ careet/
└─ gogumafarm/
```

`careet`과 `gogumafarm`은 서로 독립된 수집기다. 각 폴더 안에서 설치, 실행, 테스트를 수행해야 한다. 루트(`final_1_team`)에서 테스트를 직접 실행하면 Python import 경로 문제로 실패할 수 있다.

## 공통 원칙

- 목적은 최신 밈/트렌드 분석용 공개 데이터 수집이다.
- 로그인, 쿠키, 인증 우회, 비공개 API 탐색, 브라우저 자동화는 사용하지 않는다.
- 본문 전체, 본문 HTML, 이미지 바이너리, iframe 콘텐츠는 저장하지 않는다.
- 원문 문장을 길게 복제하지 않는다.
- 수집 결과는 이후 마케팅 agent에서 RAG/프롬프트 컨텍스트로 사용할 수 있는 구조화 데이터로 보는 것이 맞다.
- 운영 전에는 각 사이트의 robots 정책, 이용약관, 저작권 정책을 다시 확인해야 한다.

## `careet/`

### 역할

캐릿의 `요즘 뜨는 밈` 시리즈에서 비로그인 상태로 접근 가능한 공개 메타데이터와 목차 기반 밈 항목을 수집한다.

### 주요 파일

```text
careet/
├─ CAREET_CRAWLER_SPEC.md
├─ careet_crawler.py
├─ README.md
├─ requirements.txt
├─ data/
├─ data-smoke/
├─ data-smoke-detail/
└─ tests/
```

- `CAREET_CRAWLER_SPEC.md`: 캐릿 수집기의 요구사항 명세.
- `careet_crawler.py`: 실행 코드.
- `README.md`: 설치, 실행, 출력, 제한사항 설명.
- `requirements.txt`: Python 의존성.
- `tests/`: 실제 사이트를 호출하지 않는 단위 테스트와 fixture.
- `data/`: 전체 수집 결과.
- `data-smoke/`: 목록 중심 smoke 실행 결과.
- `data-smoke-detail/`: 상세 페이지 포함 smoke 실행 결과.

### 실행

`gather_data/crawling/careet`에서 실행한다.

```powershell
python careet_crawler.py
python careet_crawler.py --start-page 1 --end-page 1 --delay 1.5
python careet_crawler.py --list-only
python careet_crawler.py --resume
```

주요 옵션:

- `--start-page`, `--end-page`: 페이지 범위 제한.
- `--list-only`: 상세 페이지를 요청하지 않음.
- `--resume`: 기존 당일 CSV 중 상세 수집 성공분 재사용.
- `--summary-mode rule|off`: 규칙 기반 설명 생성 on/off.
- `--download-thumbnails`: 명시적으로 썸네일 저장. 기본은 저장하지 않음.
- `--emit-final-from-csv`: 기존 processed CSV에서 최종 밈 용어 JSON만 생성.
- `--audit-final-from-csv`: 기존 processed CSV에서 제외 의심 후보 CSV 생성.

### 산출물

대표 산출물:

```text
data/raw/careet_articles_YYYYMMDD.csv
data/processed/careet_memes_YYYYMMDD.csv
data/final_processed/careet_meme_terms_YYYYMMDD.json
data/final_processed/careet_meme_term_suspects_YYYYMMDD.csv
```

현재 확인된 최신 산출물 기준:

- `data/raw/careet_articles_20260709.csv`: 136 rows
- `data/processed/careet_memes_20260709.csv`: 134 rows

### 테스트

반드시 `careet` 폴더에서 실행한다.

```powershell
python -m unittest discover -s tests -v
```

현재 확인 결과: 19 tests passed.

### 주의사항

- 유료/로그인 영역 우회 금지.
- 본문 전체 저장 금지.
- 썸네일 다운로드는 기본 비활성화이며, 켤 경우 HTTPS, MIME, 파일 시그니처, 크기 제한을 검증한다.
- CSV는 Excel 호환을 위해 `utf-8-sig`를 사용한다.

## `gogumafarm/`

### 역할

고구마팜 WordPress REST API에서 `최신 밈과 트렌드` 카테고리와 `밈` 태그의 교집합 게시물만 수집한다.

수집 대상은 게시물 메타데이터, 제목 구조, 외부 출처 URL, 규칙 기반 요약, 신뢰 가능한 구조에서 추출한 `meme_items`다.

### 주요 파일

```text
gogumafarm/
├─ GOGUMAFARM_CRAWLER_SPEC.md
├─ gogumafarm_crawler.py
├─ README.md
├─ requirements.txt
├─ data/
└─ tests/
```

- `GOGUMAFARM_CRAWLER_SPEC.md`: 고구마팜 수집기 요구사항 명세.
- `gogumafarm_crawler.py`: 실행 코드.
- `README.md`: 설치, 실행, 출력, 제한사항 설명.
- `requirements.txt`: Python 의존성.
- `tests/`: 실제 사이트를 호출하지 않는 단위 테스트와 합성 fixture.
- `data/`: JSON, raw CSV, processed CSV, final processed JSON 산출물.

### 수집 기준

확인된 기준값:

- WordPress API: `https://gogumafarm.kr/wp-json/wp/v2`
- category slug: `trends`
- category ID: `384`
- category name: `최신 밈과 트렌드`
- tag ID: `110`
- tag name: `밈`

단, ID와 건수는 고정값으로 가정하지 말고 실행 시 API로 검증해야 한다.

### 실행

`gather_data/crawling/gogumafarm`에서 실행한다.

```powershell
python gogumafarm_crawler.py
python gogumafarm_crawler.py --dry-run
python gogumafarm_crawler.py --resume
python gogumafarm_crawler.py --emit-from-json data\gogumafarm_memes_YYYYMMDD.json
```

주요 옵션:

- `--output-dir PATH`: 출력 디렉터리. 기본 `./data`.
- `--delay FLOAT`: 요청 간 대기. 기본 1.0초, 최소 1.0초.
- `--timeout FLOAT`: timeout 기준값. 기본 15초.
- `--retries INT`: 429/5xx 재시도 횟수. 기본 3.
- `--resume`: 체크포인트 또는 최신 결과 파일에서 수정되지 않은 게시물 재사용.
- `--resume-from PATH`: 지정 JSON에서 재개.
- `--emit-from-json PATH`: 기존 JSON에서 팀원 형식 CSV/최종 JSON만 재생성.
- `--dry-run`: taxonomy와 첫 게시물 페이지만 검증하고 파일 저장하지 않음.

### 산출물

대표 산출물:

```text
data/gogumafarm_memes_YYYYMMDD.json
data/raw/gogumafarm_articles_YYYYMMDD.csv
data/processed/gogumafarm_meme_terms_YYYYMMDD.csv
data/final_processed/gogumafarm_meme_terms_YYYYMMDD.json
```

현재 확인된 최신 산출물 기준:

- `data/gogumafarm_memes_20260709.json`: `article_count=72`, `meme_item_count=95`
- `data/raw/gogumafarm_articles_20260709.csv`: 72 rows
- `data/processed/gogumafarm_meme_terms_20260709.csv`: 89 rows
- `data/final_processed/gogumafarm_meme_terms_20260709.json`: 84 items

### 테스트

반드시 `gogumafarm` 폴더에서 실행한다.

```powershell
python -m unittest discover -s tests -v
```

현재 확인 결과: 13 tests passed.

### 주의사항

- 공개 WordPress REST API만 사용한다.
- HTML 페이지 scraping으로 조용히 fallback하지 않는다.
- `content.rendered`는 메모리 파싱에만 사용하고 결과 JSON, 로그, fixture에 저장하지 않는다.
- `meme_items`는 신뢰 가능한 heading 구조가 있을 때만 생성한다.
- 불확실한 구조는 `unsupported_structure`, `no_items`, `parse_error` 등 상태로 남긴다.
- `--dry-run`은 결과 JSON과 체크포인트를 만들면 안 된다.

## agent 작업 시 우선순위

1. 먼저 대상 폴더의 `README.md`를 읽는다.
2. 그 다음 해당 `*_CRAWLER_SPEC.md`를 읽고, 코드와 명세가 어긋나는지 확인한다.
3. 실행은 각 사이트 폴더 안에서 수행한다.
4. 네트워크가 필요한 실제 수집 전에 단위 테스트를 먼저 실행한다.
5. 실제 수집은 사이트 정책 재확인 후 수행한다.
6. 새로운 사이트를 추가할 때는 기존처럼 `gather_data/crawling/{site_name}/` 하위에 독립 폴더를 만든다.

## Git 상태 참고

현재 `careet/`와 `gogumafarm/`는 폴더 단위로 정리되어 있으나, 기존 루트 파일 이동 때문에 Git에는 삭제/신규 파일로 보일 수 있다. 리뷰 시에는 단순 삭제가 아니라 `gather_data/crawling/` 루트에 있던 Careet 관련 파일들이 `careet/` 하위로 이동된 것인지 확인해야 한다.
