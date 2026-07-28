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

`sns_trend` landing 표준 경로에 저장:

```powershell
python gogumafarm_crawler.py `
  --week 2026-W31 `
  --run-id manual__gogumafarm_phase4_smoke_20260727 `
  --date 2026-07-27
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
- `--date YYYY-MM-DD`: 산출물 파일명 기준일. 미지정 시 Asia/Seoul 현재 날짜 사용
- `--week YYYY-Www`: `sns_trend` landing week partition. `--run-id`와 함께 사용
- `--run-id ID`: Airflow 또는 수동 실행 ID. `--week`와 함께 사용
- `--delay FLOAT`: 요청 간 대기 시간. 기본값은 `1.0`, 최소값도 `1.0`
- `--timeout FLOAT`: connect/read timeout 기준값. 기본값은 `15.0`
- `--retries INT`: 429와 5xx 재시도 횟수. 기본값은 `3`
- `--resume`: 체크포인트 또는 최신 결과 파일에서 수정되지 않은 게시물 구조를 재사용
- `--resume-from PATH`: 지정한 JSON 파일에서 재개. `--resume`을 암시
- `--emit-from-json PATH`: 기존 JSON에서 `raw`, `processed`, `final_processed` 산출물만 생성
- `--emit-curated-meme-card-candidates`: landing 실행에서 rule-filtered curated meme card candidate JSON도 생성
- `--curated-version vN`: curated dataset version. 기본값은 `v3`
- `--curated-root PATH`: curated root. 기본값은 `data/curated/sns_trend`
- `--dry-run`: taxonomy와 첫 게시물 페이지의 헤더/필터만 검증
- `--fail-if-exists`: 기존 산출물이 있으면 덮어쓰지 않고 실패
- `--log-level DEBUG|INFO|WARNING|ERROR`

## Output

기본 legacy 출력:

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

기존 `processed/`, `final_processed/`는 이 크롤러 내부 단계명입니다. 프로젝트 표준
`data/processed/sns_trend/vN/...`의 공식 processed와 같은 의미가 아닙니다.
v3부터는 크롤러 내부 단계명을 GCS stage 이름으로 그대로 가져오지 않고 아래 의미로
해석합니다.

| 크롤러 내부 산출물 | GCS/프로젝트 표준 의미 | 설명 |
| --- | --- | --- |
| `raw` | `landing/raw` | 크롤링 원본 게시글 메타데이터 |
| `processed` | landing run 내부 후보 CSV | heading에서 자동 추출한 term 후보 |
| `final_processed` | `curated/meme_card_candidates` | 자동 필터링까지 끝난 후보 JSON. 아직 검수 완료 아님 |
| 사람 검수 후 생성 | `processed/cross_platform_signal_top_candidates` | 공식 API/RAG/프롬프트 입력 패키지 |

최종 운영 흐름은 아래 기준을 따릅니다.

```text
landing/raw
  -> curated/meme_card_candidates
  -> 사람이 검수
  -> processed/cross_platform_signal_top_candidates
```

따라서 `curated/meme_card_candidates`는 자동 생성 후보이고, 검수 완료본은 별도
`meme_cards_reviewed` 폴더를 만들지 않고 바로 공식 processed 패키지로 승격합니다.

`sns_trend` landing mode에서는 내부 단계 폴더명을 만들지 않고 run 폴더에 flat하게 저장합니다.

```text
data/landing/sns_trend/week=2026-W31/raw/gogumafarm/run_id=<run_id>/
  gogumafarm_memes_YYYYMMDD.json
  gogumafarm_articles_YYYYMMDD.csv
  gogumafarm_meme_terms_YYYYMMDD.csv
  gogumafarm_meme_terms_YYYYMMDD.json
  crawler_run_summary.json
  error.json  # 실패 시에만 생성
```

| 파일 | 역할 |
| --- | --- |
| `gogumafarm_memes_YYYYMMDD.json` | 크롤러가 만든 전체 구조화 JSON |
| `gogumafarm_articles_YYYYMMDD.csv` | 게시글 단위 메타데이터 CSV |
| `gogumafarm_meme_terms_YYYYMMDD.csv` | 게시글 heading에서 추출한 밈 후보 term CSV |
| `gogumafarm_meme_terms_YYYYMMDD.json` | 중복/불량 표현을 줄인 후보 term JSON |
| `crawler_run_summary.json` | 이번 수집 실행 결과와 산출물 경로 |
| `error.json` | 실패 시 원인 추적용 artifact |

`--emit-curated-meme-card-candidates`를 같이 쓰면 landing 후보 term을 기반으로 아래
curated 후보 문서를 생성합니다. 이 파일은 자동 규칙 기반 후보이므로 사람 검수
완료가 아닙니다. 그래서 `review_status=pending`으로 저장됩니다. `terms`는 이모지를
제거한 canonical 검색/중복제거 값이고, `display_terms`는 카드 display name 검수에
참고할 이모지 포함 원문 표현입니다.

```text
data/curated/sns_trend/v3/meme_card_candidates/gogumafarm/
  gogumafarm_meme_card_candidates_2026-W31.json
```

사람이 이 후보를 검수한 뒤에는 아래 공식 processed 패키지에 병합합니다.

```text
data/processed/sns_trend/v3/cross_platform_signal_top_candidates/
  cross_platform_signal_top_candidates.json
  cross_platform_signal_top_candidates.csv
```

landing 경로에는 dataset version을 붙이지 않습니다. landing은 크롤링 입고 기준이므로
`week=<ISO week>`와 `run_id=<run_id>`로 추적합니다. version은 curated/processed
산출물부터 붙입니다. 대신 curated 후보 JSON 내부에 아래 lineage 필드를 남겨서 어떤
landing run에서 생성됐는지 추적합니다.

```json
{
  "version": "v3",
  "stage": "curated",
  "artifact_name": "meme_card_candidates",
  "collected_week": "2026-W31",
  "source_landing_run_id": "manual__gogumafarm_landing_2026W31_20260727T183402KST"
}
```

반대로 landing의 `crawler_run_summary.json`에는 생성된 curated 후보 파일 경로를
`outputs.curated_meme_card_candidates`로 남깁니다. 즉 양쪽에서 서로 추적할 수
있습니다.

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
