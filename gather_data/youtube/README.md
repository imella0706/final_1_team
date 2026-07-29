# YouTube trend collector

한국 YouTube `mostPopular` 영상 스냅샷을 수집하고, 같은 스냅샷에서 키워드 출현율을 계산해 날짜별 변화를 비교한다.

## 구조

```text
youtube/
├─ youtube_trending_collector.py  # 원본 영상 스냅샷 수집
├─ daily_keyword_tracker.py       # 영상 스냅샷에서 키워드 통계 생성
├─ compare_trends.py              # 호환되는 두 키워드 스냅샷 비교
├─ youtube_trends/                # 재사용 가능한 수집·분석·파일 I/O 패키지
├─ tests/                         # 외부 API를 호출하지 않는 단위 테스트
├─ data/                          # 새 런타임 산출물
├─ reports/                       # 비교 CSV·PNG
├─ requirements.txt
└─ requirements-okt.txt           # 선택적 KoNLPy/Okt 의존성
```

기존 세 진입 스크립트의 파일명은 유지한다. 생성되는 CSV, `history/`, PNG,
`data/`, `reports/`는 Git에서 제외하고 공식 데이터셋은 repository root의
`data/landing|curated|processed` 계층에서 관리한다.

## 설치

Python 3.11 이상을 권장한다.

```powershell
cd gather_data\youtube
python -m pip install -r requirements.txt
```

Okt 형태소 분석기를 명시적으로 사용할 때만 다음 의존성을 설치한다. KoNLPy와 별도로 Java 실행 환경이 필요하다.

```powershell
python -m pip install -r requirements-okt.txt
```

API 키는 repository의 canonical 환경 파일인 `apps/api/.env`에서 읽는다.
환경 변수 목록은 `apps/api/.env.gcp.example`에서 관리한다.

```text
YOUTUBE_API_KEY=
```

선택 환경 변수:

```text
YOUTUBE_REGION_CODE=KR
YOUTUBE_TOTAL_VIDEOS=100
YOUTUBE_PAGE_SIZE=50
YOUTUBE_API_TIMEOUT=15
YOUTUBE_API_RETRIES=3
YOUTUBE_TOKENIZER=regex
YOUTUBE_TIMEZONE=Asia/Seoul
```

CLI 인자가 환경 변수보다 우선한다. API 키는 셸 기록에 남지 않도록 CLI 인자로 받지 않는다.

## 권장 실행 흐름

### 1. 원본 영상 스냅샷 수집

```powershell
python youtube_trending_collector.py
```

기본 출력:

```text
data/raw/youtube_trending_KR_YYYYMMDD.csv
```

재현 가능한 날짜와 별도 출력 위치를 지정할 수 있다.

```powershell
python youtube_trending_collector.py `
  --region KR `
  --limit 100 `
  --date 2026-07-10 `
  --output-dir data\raw `
  --fail-if-exists
```

### 2. 같은 원본에서 키워드 스냅샷 생성

수집 결과를 `--input-csv`로 재사용하는 방식을 권장한다. collector와 tracker가 서로 다른 시점에 API를 두 번 호출하는 문제를 피할 수 있다.
출력 CSV는 기존 채빈님 landing 파일과 동일하게 `keyword,count` 두 컬럼으로 고정한다.

```powershell
python daily_keyword_tracker.py `
  --input-csv data\raw\youtube_trending_KR_20260710.csv `
  --tokenizer regex `
  --fail-if-exists
```

`--input-csv`를 생략하면 tracker가 API를 직접 호출한다.
입력 파일명이 `youtube_trending_지역_YYYYMMDD.csv` 형식이 아니면 잘못된 날짜 귀속을 막기 위해 `--date`를 반드시 지정한다.

기본 출력:

```text
data/history/keywords_YYYY-MM-DD.csv
```

팀 공유 landing 산출물은 기존 채빈님 `youtube_keywords_YYYY-MM-DD.csv`와 같은 이름과 컬럼을 사용한다.

```bash
# [Design Intent] 기존 sns_trend landing의 keyword,count 계약에 맞춘 파일을 생성한다.
python daily_keyword_tracker.py \
  --input-csv data/landing/sns_trend/week=2026-W31/raw/youtube/run_id=<run_id>/youtube_trending_KR_2026-W31.csv \
  --date 2026-07-27 \
  --output-file data/landing/sns_trend/week=2026-W31/raw/youtube/run_id=<run_id>/youtube_keywords_2026-07-27.csv \
  --tokenizer regex \
  --fail-if-exists
```

검수 전 후보 JSON까지 만들 때는 `--emit-curated-meme-card-candidates`를 명시한다.

```bash
# [Design Intent] landing keyword,count 결과를 검수 전 후보 JSON으로 승격하되,
# 공식 processed 입력으로는 자동 승격하지 않는다.
python daily_keyword_tracker.py \
  --input-csv data/landing/sns_trend/week=2026-W31/raw/youtube/run_id=<run_id>/youtube_trending_KR_2026-W31.csv \
  --date 2026-07-27 \
  --output-file data/landing/sns_trend/week=2026-W31/raw/youtube/run_id=<run_id>/youtube_keywords_2026-07-27.csv \
  --tokenizer regex \
  --week 2026-W31 \
  --run-id <run_id> \
  --emit-curated-meme-card-candidates
```

curated 출력:

```text
data/curated/sns_trend/v3/meme_card_candidates/youtube/
  youtube_meme_card_candidates_2026-W31.json
```

`regex`가 기본 tokenizer이며 모든 팀 환경에서 동일하게 동작한다. `okt`를 선택했는데 KoNLPy 또는 Java가 없으면 조용히 다른 알고리즘으로 전환하지 않고 실패한다.

### 3. 트렌드 비교

```powershell
python compare_trends.py
```

기본적으로 `data/history/`에서 가장 최신 스냅샷과 동일한 schema, region, tokenizer, normalizer, alias, stopword 버전을 가진 직전 스냅샷을 선택한다. 최신 스냅샷과 호환되는 이전 파일이 없으면 과거 legacy 결과로 물러나지 않고 실패한다.

```powershell
python compare_trends.py `
  --old data\history\keywords_2026-07-09.csv `
  --new data\history\keywords_2026-07-10.csv `
  --min-support 2 `
  --top-n 20
```

기본 출력:

```text
reports/keyword_trend_comparison.csv
reports/keyword_trend_comparison.png
```

차트가 필요하지 않은 배치나 테스트에서는 `--no-plot`을 사용한다.

기존 legacy 결과를 명시적으로 다시 비교하려면 다음처럼 기존 `history/`를 지정한다.

```powershell
python compare_trends.py --history-dir history --no-plot
```

## v2 데이터 의미

현재 `daily_keyword_tracker.py`의 외부 산출물은 `keyword,count`로 고정한다.
내부 집계는 아래 v2 기준으로 수행한 뒤 `display_keyword`와 `occurrence_count`만 출력한다.

1. Unicode NFKC 정규화
2. 영문 casefold
3. tokenizer 적용
4. 정규화된 불용어 제거
5. 중복 `video_id` 제거
6. 한 키워드는 영상 하나당 `video_count`에 최대 한 번 반영

예를 들어 `T1`, `t1`, `Ｔ１`은 canonical keyword `t1`으로 합쳐진다. `T1`과 `티원`처럼 의미 해석이 필요한 별칭은 자동으로 합치지 않는다.

주요 키워드 컬럼:

- `video_count`: 키워드가 한 번 이상 등장한 고유 영상 수
- `occurrence_count`: 제목·태그에서 발견된 전체 횟수. 진단용이며 순위 기준이 아니다.
- `sample_size`: 중복 제거 후 전체 영상 수
- `prevalence`: `video_count / sample_size`
- `title_video_count`, `tag_video_count`: 출처별 고유 영상 수
- `channel_count`: 키워드를 사용한 고유 채널 수
- `tokenizer_version`, `normalizer_version`: 재현성을 위한 처리 버전
- `stopword_version`, `analysis_signature`: 비교 호환성을 검증하는 분석 설정 식별자

v2 비교는 `prevalence` 변화의 퍼센트포인트인 `delta_pp`를 우선한다. 최신 지지 영상 수가 `--min-support`보다 작으면 `low_support`로 분류한다.

## Legacy 호환 정책

- 기존 `keyword,count` CSV는 수정하지 않고 유지한다.
- 새 landing 공유용 `keyword,count` 파일도 내부 v2 snapshot에서 `display_keyword`를 `keyword`,
  `occurrence_count`를 `count`로 축소해 생성한다.
- v1끼리는 `legacy_raw_count` 방식으로 비교한다.
- v2끼리는 `prevalence_v2` 방식으로 비교한다.
- v1과 v2는 표본과 집계 의미가 달라 혼합 비교를 거부한다.
- 분석 signature가 다른 v2 파일도 비교를 거부한다.
- 새 raw CSV는 기존 10개 컬럼을 앞부분에 유지하면서 `schema_version`, `region_code`, `collected_at`, `tags_json`을 추가한다.
- `tags_json`이 정확한 태그 배열이며, 기존 comma 문자열 `tags`는 사람 확인과 하위 호환 용도다.

## 실패와 덮어쓰기

- 성공 종료 코드는 `0`, API·파일·분석 실패는 `1`, 설정 오류는 `2`다.
- API가 0건을 반환하면 빈 정상 파일을 만들지 않고 실패한다.
- API 재시도 횟수와 timeout을 설정할 수 있다.
- CSV와 PNG는 임시 파일에 완전히 쓴 뒤 교체한다. 비교 보고서는 두 파일 생성을 모두 마친 후 함께 반영하고 실패 시 기존 쌍을 복원한다.
- 기존 동작 호환을 위해 기본은 같은 이름의 파일을 교체한다. 보호가 필요하면 `--fail-if-exists`를 사용한다.
- 오류 메시지에는 API 키나 전체 요청 URL을 출력하지 않는다.

## Airflow landing 실행 계약

Airflow 또는 동일한 배치 실행기는 `--week`와 `--run-id`를 함께 전달한다.

```bash
# [Design Intent] 주차와 run_id를 경로에 포함해 재실행 결과가 기존 raw를 덮어쓰지 않게 한다.
python youtube_trending_collector.py \
  --week 2026-W31 \
  --run-id manual__youtube_2026w31
```

`--output-dir`를 생략하면 아래 표준 위치에 저장한다.

```text
data/landing/sns_trend/week=2026-W31/raw/youtube/run_id=manual__youtube_2026w31/
  youtube_trending_KR_2026-W31.csv
  youtube_keywords_YYYY-MM-DD.csv
  crawler_run_summary.json
  error.json  # 실패 시에만 생성

data/curated/sns_trend/v3/meme_card_candidates/youtube/
  youtube_meme_card_candidates_2026-W31.json
```

파일 역할:

| 파일 | 역할 | 예시 컬럼 |
| --- | --- | --- |
| `youtube_trending_KR_2026-W31.csv` | YouTube에서 가져온 원본 영상 목록 | `video_id`, `title`, `tags`, `view_count`, `url` |
| `youtube_keywords_YYYY-MM-DD.csv` | 원본 영상 목록에서 키워드만 뽑아 count로 집계한 결과 | `keyword`, `count` |
| `youtube_meme_card_candidates_2026-W31.json` | 사람이 검수하기 전 YouTube 밈 카드 후보 | `terms`, `term_scores`, `review_status=pending` |
| `crawler_run_summary.json` | 이번 수집 실행 로그 | 수집 개수, 실행 시간, 저장 경로 |
| `error.json` | 실패 시 원인 추적용 로그 | `status`, `exit_code`, `error_type`, `message` |

`youtube_keywords_YYYY-MM-DD.csv`는 `youtube_trending_KR_YYYY-Www.csv`를 입력으로
`daily_keyword_tracker.py`가 생성한다. `youtube_meme_card_candidates_YYYY-Www.json`도
같은 keyword snapshot에서 생성하며, 아직 사람이 검수하지 않은 `pending` 후보라서
processed payload로 자동 승격하지 않는다.

- `--week`는 `Asia/Seoul` 기준 ISO week를 `YYYY-Www` 형식으로 전달한다.
- `--week`와 `--run-id` 중 하나만 전달하면 설정 오류(`exit 2`)다.
- 성공 시 raw CSV와 `crawler_run_summary.json`을 기록한다.
- 수집 또는 파일 저장 실패 시 `error.json`을 기록하고 non-zero로 종료한다.
- API key와 전체 요청 URL은 artifact에 기록하지 않는다.
- 기존 사용자는 두 인자 없이 기존 raw 출력 방식을 계속 사용할 수 있다.

## 테스트

외부 YouTube API를 호출하지 않는다.

```powershell
cd gather_data\youtube
python -m unittest discover -s tests -v
python -m compileall -q .
```

테스트는 pagination, 중복 영상, 반복 page token, 빈 응답, CSV 원자 저장, 태그 round-trip, Unicode/case 정규화, 영상 단위 집계, legacy/v2 비교 거부, CLI 설정 우선순위와 종료 코드를 검증한다.

Linux에서 한글 차트를 만들려면 Noto Sans CJK KR 또는 NanumGothic 같은 한글 폰트를 설치하고 필요 시 `--font-family`로 지정한다.

실제 사이트/API 호환성은 별도 smoke 실행으로 확인해야 한다. smoke 실행 전 API 할당량과 출력 파일명을 확인한다.
