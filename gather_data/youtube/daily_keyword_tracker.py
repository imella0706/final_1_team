# -*- coding: utf-8 -*-
"""
[매일 1회 실행] 인기 급상승 영상 수집 + 키워드 빈도를 날짜별로 저장

- youtube_trending_collector.py 와 youtube_trend_analysis.py의 로직을 합쳐서
  '오늘의 키워드 빈도표'를 history 폴더에 날짜별 파일로 쌓아둡니다.
- 이 파일이 여러 날짜만큼 쌓이면 compare_trends.py로 변화량을 비교할 수 있어요.

사전 준비:
1. pip install google-api-python-client pandas python-dotenv
   (더 정확한 분석을 원하면) pip install konlpy
2. 루트 .env 파일에 YOUTUBE_API_KEY 입력
3. 매일 1번씩 python daily_keyword_tracker.py 실행 (며칠 반복)
"""

from googleapiclient.discovery import build
from collections import Counter
from datetime import datetime
import pandas as pd
import re
import os
from dotenv import load_dotenv

# ===== 설정 =====
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, "..", ".env"))

API_KEY = os.getenv("YOUTUBE_API_KEY")
REGION_CODE = "KR"
TOTAL_VIDEOS = 100
HISTORY_DIR = os.path.join(BASE_DIR, "history")   # 날짜별 파일이 쌓이는 폴더

STOPWORDS = {"영상", "이", "가", "은", "는", "을", "를", "에", "의", "와", "과", "도", "으로", "with", "the", "and"}


def get_trending_videos():
    youtube = build("youtube", "v3", developerKey=API_KEY)
    videos = []
    next_page_token = None

    while len(videos) < TOTAL_VIDEOS:
        request = youtube.videos().list(
            part="snippet,statistics",
            chart="mostPopular",
            regionCode=REGION_CODE,
            maxResults=50,
            pageToken=next_page_token
        )
        response = request.execute()
        for item in response.get("items", []):
            snippet = item.get("snippet", {})
            videos.append({
                "title": snippet.get("title", ""),
                "tags": ",".join(snippet.get("tags", [])) if snippet.get("tags") else ""
            })
        next_page_token = response.get("nextPageToken")
        if not next_page_token:
            break

    return videos[:TOTAL_VIDEOS]


def extract_keywords(texts):
    try:
        from konlpy.tag import Okt
        okt = Okt()
        words = []
        for text in texts:
            words.extend([n for n in okt.nouns(str(text)) if len(n) > 1 and n not in STOPWORDS])
        return words
    except Exception:
        words = []
        for text in texts:
            tokens = re.findall(r"[가-힣a-zA-Z0-9]+", str(text))
            words.extend([t for t in tokens if len(t) > 1 and t not in STOPWORDS])
        return words


if __name__ == "__main__":
    if not API_KEY:
        raise SystemExit("YOUTUBE_API_KEY가 없습니다. 루트 .env 파일을 확인하세요.")

    os.makedirs(HISTORY_DIR, exist_ok=True)

    today = datetime.now().strftime("%Y-%m-%d")
    print(f"[{today}] {REGION_CODE} 인기 급상승 영상 수집 중...")

    videos = get_trending_videos()
    all_text = [v["title"] for v in videos] + [v["tags"] for v in videos]
    words = extract_keywords(all_text)

    freq_df = pd.DataFrame(Counter(words).most_common(), columns=["keyword", "count"])
    out_path = os.path.join(HISTORY_DIR, f"keywords_{today}.csv")
    freq_df.to_csv(out_path, index=False, encoding="utf-8-sig")

    print(f"완료! {len(freq_df)}개 키워드를 '{out_path}' 에 저장했습니다.")
    print("내일도 같은 방식으로 실행해서 며칠치 데이터를 쌓아주세요.")
