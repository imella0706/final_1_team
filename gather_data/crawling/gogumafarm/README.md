# Gogumafarm public metadata crawler

`GOGUMAFARM_CRAWLER_SPEC.md` 기준으로 고구마팜 WordPress REST API에서 `최신 밈과 트렌드` 카테고리와 `밈` 태그의 교집합 게시물만 수집합니다.

본문 전체, 본문 HTML, 쿠키, 이미지 파일, 이미지 바이너리, iframe 콘텐츠는 저장하지 않습니다. 결과에는 공개 메타데이터, 제목 구조, 외부 출처 URL, 규칙 기반 요약만 포함됩니다.

## Install

Python 3.11 이상을 권장합니다.

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

## Run

실제 수집:

```powershell
python gogumafarm_crawler.py
```

사전 점검만 수행하고 파일을 만들지 않는 스모크 테스트:

```powershell
python gogumafarm_crawler.py --dry-run
```

이미 생성된 `gogumafarm_memes_YYYYMMDD.json`에서 팀원 형식 CSV만 다시 만들기:

```powershell
python gogumafarm_crawler.py --emit-from-json data\gogumafarm_memes_YYYYMMDD.json
```

주요 옵션:

- `--output-dir PATH`: 출력 디렉터리. 기본값은 `./data`
- `--delay FLOAT`: 요청 간 대기 시간. 기본값은 `1.0`, 최소값도 `1.0`
- `--timeout FLOAT`: connect/read timeout 기준값. 기본값은 `15.0`
- `--retries INT`: 429와 5xx 재시도 횟수. 기본값은 `3`
- `--resume`: 체크포인트 또는 최신 결과 파일에서 수정되지 않은 게시물 구조를 재사용
- `--resume-from PATH`: 지정한 JSON 파일에서 재개. `--resume`을 암시
- `--emit-from-json PATH`: 기존 JSON에서 `raw`, `processed`, `final_processed` 산출물만 생성
- `--dry-run`: taxonomy와 첫 게시물 페이지의 헤더/필터만 검증
- `--log-level DEBUG|INFO|WARNING|ERROR`

## Output

기본 출력:

```text
data/gogumafarm_memes_YYYYMMDD.json
data/raw/gogumafarm_articles_YYYYMMDD.csv
data/processed/gogumafarm_meme_terms_YYYYMMDD.csv
data/final_processed/gogumafarm_meme_terms_YYYYMMDD.json
```

최상위 JSON에는 실행 메타데이터와 `articles` 배열이 들어갑니다. 각 게시물에는 `post_id`, `url`, `title`, `author`, `categories`, `tags`, `excerpt`, `featured_image`, `heading_structure`, `external_sources`, `summary`, `meme_items` 등이 포함됩니다.

`processed/gogumafarm_meme_terms_YYYYMMDD.csv`는 팀원 산출물과 같은 컬럼을 사용합니다.

```text
term_id,article_id,term,term_type,source_field,position,published_date,tags,relevance_score,source_url,collected_at
```

`content`, `content_html`, 본문 전체, 이미지 바이너리는 저장하지 않습니다. 수집 중단 시에는 같은 출력 디렉터리에 `.gogumafarm_checkpoint.json`이 남을 수 있고, 정상 종료 시 삭제됩니다.

## Tests

단위 테스트는 실제 사이트를 호출하지 않는 합성 fixture만 사용합니다.

```powershell
python -m unittest discover -s tests -v
```

## Notes

- 공개 WordPress API만 사용하며 HTML 페이지 스크래핑이나 브라우저 자동화로 전환하지 않습니다.
- API의 `X-WP-Total`, `X-WP-TotalPages`가 실행 중 바뀌면 처음부터 한 번 재수집하고, 재수집에서도 바뀌면 실패합니다.
- `--dry-run`은 결과 JSON과 체크포인트를 만들지 않습니다.
- 운영 전에는 사이트 robots 정책과 이용약관의 최신 상태를 다시 확인해야 합니다.
