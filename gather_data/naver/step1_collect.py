# -*- coding: utf-8 -*-
"""
[1단계] 네이버 검색 API로 블로그·뉴스 글 수집
--------------------------------------------------
사용법
1. apps/api/.env 파일에 NAVER_CLIENT_ID, NAVER_CLIENT_SECRET 입력
2. 아래 KEYWORD를 원하는 검색어로 수정
3. 터미널에서 실행:  python step1_collect.py
결과
- naver_blog_키워드.csv  (블로그 글 최대 1,000건)
- naver_news_키워드.csv  (뉴스 기사 최대 1,000건)
필요 라이브러리:  pip install requests pandas python-dotenv
"""
import html
import argparse
import os
import re
import time
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
KEYWORD = "카페"          # 분석할 키워드로 변경
DEFAULT_SOURCES = ("blog", "news")
# ============================================

HEADERS = {
    "X-Naver-Client-Id": CLIENT_ID,
    "X-Naver-Client-Secret": CLIENT_SECRET,
}


def clean_text(text):
    """제목/요약에 섞인 HTML 태그(<b> 등)와 특수문자(&quot; 등)를 제거"""
    text = re.sub(r"<[^>]+>", "", str(text))
    text = html.unescape(text)
    return text.strip()


def collect(source, *, keyword=KEYWORD, limit=1000):
    """source: 'blog' 또는 'news'. 최신순으로 최대 1,000건 수집"""
    if source not in DEFAULT_SOURCES:
        raise ValueError(f"unsupported source: {source}")
    limit = max(1, min(int(limit), 1000))
    url = f"https://openapi.naver.com/v1/search/{source}.json"
    all_items = []
    # start는 1~1000까지만 허용 → 100건씩 10번 = 최대 1,000건
    for start in range(1, limit + 1, 100):
        display = min(100, limit - len(all_items))
        params = {"query": keyword, "display": display, "start": start, "sort": "date"}
        res = requests.get(url, headers=HEADERS, params=params)
        if res.status_code != 200:
            print(f"[{source}] 오류 {res.status_code}: {res.text}")
            break
        items = res.json().get("items", [])
        if not items:          # 더 이상 결과가 없으면 종료
            break
        all_items.extend(items)
        all_items = all_items[:limit]
        print(f"[{source}] {len(all_items)}건 수집 중...")
        if len(all_items) >= limit:
            break
        time.sleep(0.2)        # 과도한 호출 방지
    return all_items


def to_dataframe(items, source):
    """수집 결과를 표로 정리: 태그 제거 + 날짜 변환 + 중복 제거"""
    df = pd.DataFrame(items)
    if df.empty:
        return df
    df["title"] = df["title"].apply(clean_text)
    df["description"] = df["description"].apply(clean_text)
    if source == "blog":       # 블로그는 postdate(예: 20260615)
        df["date"] = pd.to_datetime(df["postdate"].astype(str),
                                    format="%Y%m%d", errors="coerce")
    else:                      # 뉴스는 pubDate(예: Mon, 15 Jun 2026 07:50:00 +0900)
        df["date"] = (pd.to_datetime(df["pubDate"], errors="coerce", utc=True)
                        .dt.tz_convert("Asia/Seoul").dt.tz_localize(None))
    df = df.drop_duplicates(subset="link")   # 같은 글 중복 제거
    return df


def parse_args():
    parser = argparse.ArgumentParser(
        description="Collect Naver blog/news search results."
    )
    parser.add_argument("--keyword", default=KEYWORD)
    parser.add_argument("--limit", type=int, default=1000)
    parser.add_argument(
        "--sources",
        default="blog,news",
        help="Comma-separated sources: blog,news",
    )
    parser.add_argument("--output-dir", default=BASE_DIR)
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    if not CLIENT_ID or not CLIENT_SECRET:
        raise SystemExit(
            "NAVER_CLIENT_ID 또는 NAVER_CLIENT_SECRET이 없습니다. "
            "apps/api/.env 파일을 확인하세요."
        )

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    sources = tuple(source.strip() for source in args.sources.split(",") if source.strip())
    for source in sources:
        items = collect(source, keyword=args.keyword, limit=args.limit)
        df = to_dataframe(items, source)
        filename = output_dir / f"naver_{source}_{args.keyword}.csv"
        df.to_csv(filename, index=False, encoding="utf-8-sig")
        print(f"[{source}] 총 {len(df)}건 저장 완료 → {filename}\n")

    print("1단계 완료! 다음은 python step2_datalab.py 를 실행하세요.")
