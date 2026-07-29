# Careet 공개 메타데이터 크롤러

`CAREET_CRAWLER_SPEC.md`에 따라 캐릿의 **요즘 뜨는 밈** 시리즈에서 비로그인 상태로 공개된 메타데이터와 목차를 수집합니다. 로그인, 쿠키, 유료 장벽 우회, 본문 저장, 본문 이미지 다운로드는 구현하지 않습니다.

## 설치

Python 3.11 이상이 필요합니다.

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

## 실행

전체 공개 목록과 상세 페이지를 수집합니다. 요청 사이에는 기본 1.5초를 기다립니다.

```powershell
python careet_crawler.py
```

한 페이지만 확인하려면 다음과 같이 실행합니다.

```powershell
python careet_crawler.py --start-page 1 --end-page 1 --delay 1.5
```

주요 옵션:

- `--list-only`: 상세 페이지를 요청하지 않습니다.
- `--resume`: 당일 CSV 중 상세 수집에 성공한 콘텐츠를 재사용합니다.
- `--summary-mode rule|off`: 공개 미리보기 기반 설명 생성을 켜거나 끕니다.
- `--output-dir PATH`: 출력 루트를 변경합니다. 기본값은 `./data`입니다.
- `--week`, `--run-id`: 표준 landing run 경로를 사용하는 실행 식별자입니다.
- `--emit-curated-meme-card-candidates`: landing 결과에서 검수 전 curated 후보 JSON도 생성합니다.
- `--curated-version`: curated 데이터셋 버전입니다. 기본값은 `v3`입니다.
- `--download-thumbnails`: 대표 썸네일을 명시적으로 저장합니다.
- `--max-image-bytes INT`: 썸네일 최대 크기입니다. 기본값은 10 MiB입니다.

모든 옵션은 `python careet_crawler.py --help`에서 확인할 수 있습니다. `--delay`는 1.0초 미만으로 설정할 수 없습니다.

## 출력

- `data/raw/careet_articles_YYYYMMDD.csv`: 콘텐츠 단위 메타데이터
- `data/processed/careet_memes_YYYYMMDD.csv`: 목차에서 분리한 밈 단위 데이터
- `data/raw/thumbnails/{article_id}.{ext}`: `--download-thumbnails`를 지정한 경우의 대표 썸네일

CSV는 Excel 호환 `utf-8-sig`로 기록되며 임시 파일을 쓴 뒤 원자적으로 교체합니다. 상세 10건마다 체크포인트를 저장하고, `Ctrl+C` 중단 시에도 현재 결과를 저장합니다.

`rule` 요약기는 원문을 CSV나 로그에 남기지 않습니다. 충분한 공개 미리보기가 확인된 첫 목차 항목만 낮은 신뢰도의 보수적인 설명을 만들며, 나머지는 `insufficient_source`로 둡니다. LLM이나 외부 API는 사용하지 않습니다.

## 표준 landing/curated 실행

```bash
python careet_crawler.py \
  --week 2026-W31 \
  --run-id manual__careet_landing_2026W31 \
  --date 2026-07-27 \
  --end-page 1 \
  --emit-curated-meme-card-candidates \
  --curated-version v3
```

생성 경로:

```text
data/landing/sns_trend/week=2026-W31/raw/careet/run_id=<run_id>/
  careet_articles_20260727.csv
  careet_memes_20260727.csv
  careet_meme_terms_20260727.json
  careet_meme_term_suspects_20260727.csv
  crawler_run_summary.json

data/curated/sns_trend/v3/meme_card_candidates/careet/
  careet_meme_card_candidates_2026-W31.json
```

`meme_card_candidates`는 규칙으로 필터링한 검수 전 후보입니다. 사람이 검수한 뒤에만
`processed/cross_platform_signal_top_candidates`로 승격합니다.

## 테스트

테스트 fixture는 사이트 원문 전체가 아닌 선택자 검증에 필요한 최소 HTML만 포함합니다.

```powershell
python -m unittest discover -s tests -v
```

## 제한 및 준수 사항

- 사이트 구조가 바뀌어 첫 페이지의 카드나 페이지 수를 읽지 못하면 빈 성공 파일을 만들지 않고 실패합니다.
- 상세 페이지 하나의 오류는 해당 행에 기록하고 다음 콘텐츠를 계속 처리합니다.
- 대표 이미지는 기본적으로 URL만 기록합니다. 로컬 저장 전 사이트 운영자의 허락 또는 사용 권한을 확인해야 합니다.
- 이미지 옵션은 HTTPS, MIME, 파일 시그니처, 크기, 안전한 파일명과 SHA-256을 검증합니다.
- 실제 운영 전 `robots.txt`, 저작권 정책, 이용 조건의 최신 내용을 다시 확인하십시오.

## 파일 트리
• crawling/
  ├─ CAREET_CRAWLER_SPEC.md       # 원본 요구사항
  ├─ careet_crawler.py            # 크롤러 실행 코드
  ├─ requirements.txt             # Python 의존성
  ├─ README.md                    # 설치·실행 방법
  │
  ├─ data/                        # 전체 수집 결과
  │  ├─ raw/
  │  │  └─ careet_articles_20260708.csv   # 콘텐츠 136건
  │  └─ processed/
  │     └─ careet_memes_20260708.csv      # 밈 134건
  │
  ├─ data-smoke/                  # 목록 전용 검증 결과
  │  ├─ raw/
  │  │  └─ careet_articles_20260708.csv   # 콘텐츠 12건
  │  └─ processed/
  │     └─ careet_memes_20260708.csv      # 헤더만 존재
  │
  ├─ data-smoke-detail/           # 상세 페이지 포함 검증 결과
  │  ├─ raw/
  │  │  └─ careet_articles_20260708.csv   # 콘텐츠 12건
  │  └─ processed/
  │     └─ careet_memes_20260708.csv      # 밈 47건
  │
  └─ tests/
     ├─ test_careet_crawler.py    # 단위 테스트 18개
     └─ fixtures/
        ├─ list_page.html         # 목록 파싱 테스트 HTML
        ├─ detail_page.html       # 상세·목차 테스트 HTML
        └─ detail_no_toc.html     # 목차 없는 상세 HTML
