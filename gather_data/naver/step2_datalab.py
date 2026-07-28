# -*- coding: utf-8 -*-
"""
[2단계] 네이버 데이터랩 API로 검색량 추이 수집
--------------------------------------------------
사용법
1. apps/api/.env 파일에 NAVER_CLIENT_ID, NAVER_CLIENT_SECRET 입력
2. KEYWORD를 1단계와 똑같이 입력
3. 조회 기간(START_DATE, END_DATE)을 원하는 대로 수정
4. 터미널에서 실행:  python step2_datalab.py
결과
- datalab_키워드.csv  (기간별 상대 검색량. 기간 내 최대값=100 기준 비율)
필요 라이브러리:  pip install requests pandas python-dotenv
"""
import argparse
import json
import os
import sys
from pathlib import Path

import pandas as pd
import requests
from dotenv import load_dotenv

# ========== 설정 ==========
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ENV_FILE = os.path.abspath(os.path.join(BASE_DIR, "..", "..", "apps", "api", ".env"))
load_dotenv(ENV_FILE)

CLIENT_ID = os.getenv("NAVER_CLIENT_ID")
CLIENT_SECRET = os.getenv("NAVER_CLIENT_SECRET")
KEYWORD = "카페"        # 1단계와 같은 키워드
START_DATE = "2024-07-01"       # 조회 시작일 (2016-01-01 이후만 가능)
END_DATE = "2026-06-30"         # 조회 종료일
TIME_UNIT = "week"              # "date"(일별) / "week"(주별) / "month"(월별)
# ======================================


def parse_args():
    parser = argparse.ArgumentParser(
        description="Collect Naver Data Lab search trend data."
    )
    parser.add_argument("--keyword", default=KEYWORD)
    parser.add_argument("--start-date", default=START_DATE)
    parser.add_argument("--end-date", default=END_DATE)
    parser.add_argument("--time-unit", default=TIME_UNIT, choices=("date", "week", "month"))
    parser.add_argument("--output-dir", default=BASE_DIR)
    return parser.parse_args()


def collect_datalab_search_trend(*, keyword, start_date, end_date, time_unit):
    url = "https://openapi.naver.com/v1/datalab/search"
    headers = {
        "X-Naver-Client-Id": CLIENT_ID,
        "X-Naver-Client-Secret": CLIENT_SECRET,
        "Content-Type": "application/json",
    }
    body = {
        "startDate": start_date,
        "endDate": end_date,
        "timeUnit": time_unit,
        # 키워드를 여러 개 비교하고 싶으면 keywordGroups에 그룹을 추가하세요 (최대 5개)
        # 예: {"groupName": "비건", "keywords": ["비건", "비건식품"]}
        "keywordGroups": [
            {"groupName": keyword, "keywords": [keyword]},
        ],
    }

    res = requests.post(url, headers=headers, data=json.dumps(body))
    if res.status_code != 200:
        print(f"오류 {res.status_code}: {res.text}")
        sys.exit()
    return res.json()["results"][0]["data"]


if __name__ == "__main__":
    args = parse_args()
    if not CLIENT_ID or not CLIENT_SECRET:
        raise SystemExit(
            "NAVER_CLIENT_ID 또는 NAVER_CLIENT_SECRET이 없습니다. "
            "apps/api/.env 파일을 확인하세요."
        )

    data = collect_datalab_search_trend(
        keyword=args.keyword,
        start_date=args.start_date,
        end_date=args.end_date,
        time_unit=args.time_unit,
    )
    df = pd.DataFrame(data)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    filename = output_dir / f"datalab_{args.keyword}.csv"
    df.to_csv(filename, index=False, encoding="utf-8-sig")

    print(f"{len(df)}개 구간 저장 완료 → {filename}")
    print(df.head())
    print("\n2단계 완료! 다음은 python step3_analyze.py 를 실행하세요.")
