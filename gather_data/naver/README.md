# Naver SNS Trend Collector

Naver collector는 `sns_trend` 데이터셋의 landing 입력을 만든다.

## Legacy Scripts

기존 스크립트는 아래 API를 직접 호출한다.

| File | Role | Output |
| --- | --- | --- |
| `step1_collect.py` | Naver Search Blog/News 수집 | `naver_blog_<keyword>.csv`, `naver_news_<keyword>.csv` |
| `step2_datalab.py` | DataLab Search Trend 수집 | `datalab_<keyword>.csv` |
| `step3_analyze.py` | 기존 로컬 분석 스크립트 | 로컬 분석 결과 |

## Standard Landing CLI

Airflow에는 `naver_landing_collector.py`를 태운다.

```bash
python gather_data/naver/naver_landing_collector.py \
  --keyword 카페 \
  --week 2026-W31 \
  --run-id manual__naver_landing_2026W31_20260727T220700KST \
  --date 2026-07-27 \
  --limit 5 \
  --sources blog,news \
  --include-datalab \
  --datalab-start-date 2026-07-01 \
  --datalab-end-date 2026-07-27 \
  --datalab-time-unit week \
  --emit-curated-meme-card-candidates \
  --fail-if-exists
```

## Output Contract

Landing output:

```text
data/landing/sns_trend/week=YYYY-Www/raw/naver/run_id=<run_id>/
  naver_blog_<keyword>_YYYYMMDD.csv
  naver_news_<keyword>_YYYYMMDD.csv
  datalab_<keyword>_YYYYMMDD.csv
  naver_word_freq_YYYYMMDD.csv
  crawler_run_summary.json
  error.json
```

Curated candidate output:

```text
data/curated/sns_trend/v3/meme_card_candidates/naver/
  naver_meme_card_candidates_YYYY-Www.json
```

`naver_word_freq_YYYYMMDD.csv`는 채빈님 YouTube keyword 파일과 같은
`keyword,count` 컬럼 계약을 따른다.

## Notes

- `run_id=` 폴더는 Airflow 재실행과 장애 추적용이다.
- `crawler_run_summary.json`은 수집 실행 로그다. processed 입력이 아니다.
- Naver `meme_card_candidates`는 `usage_policy=reference_only`로 생성한다.
- Naver Search/DataLab 결과는 트렌드 모니터링 참고용이다.
- 사람이 검수하고 다른 플랫폼 근거가 있을 때만 `processed/cross_platform_signal_top_candidates`로 승격한다.
