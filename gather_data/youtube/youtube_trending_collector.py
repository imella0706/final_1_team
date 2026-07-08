# -*- coding: utf-8 -*-
"""
유튜브 인기 급상승 영상 수집 스크립트
목적: SNS 트렌드 분석 과제 - 유튜브 파트

사전 준비:
1. pip install google-api-python-client python-dotenv
2. 루트 .env 파일에 YOUTUBE_API_KEY를 입력하세요.
3. python youtube_trending_collector.py 실행
"""

from googleapiclient.discovery import build
import csv
from datetime import datetime
import os
from dotenv import load_dotenv

# ===== 설정 =====
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, "..", ".env"))

API_KEY = os.getenv("YOUTUBE_API_KEY")
REGION_CODE = "KR"                    # 한국 기준 (다른 나라: US, JP 등)
MAX_RESULTS = 50                      # 한 번에 가져올 영상 수 (최대 50)
TOTAL_VIDEOS = 100                    # 총 수집할 영상 수 (50개씩 나눠서 가져옴)
OUTPUT_FILE = os.path.join(
    BASE_DIR,
    f"youtube_trending_{REGION_CODE}_{datetime.now().strftime('%Y%m%d')}.csv",
)


def get_trending_videos():
    youtube = build("youtube", "v3", developerKey=API_KEY)

    videos = []
    next_page_token = None

    while len(videos) < TOTAL_VIDEOS:
        request = youtube.videos().list(
            part="snippet,statistics,contentDetails",
            chart="mostPopular",
            regionCode=REGION_CODE,
            maxResults=MAX_RESULTS,
            pageToken=next_page_token
        )
        response = request.execute()

        for item in response.get("items", []):
            snippet = item.get("snippet", {})
            stats = item.get("statistics", {})

            videos.append({
                "video_id": item.get("id"),
                "title": snippet.get("title"),
                "channel_title": snippet.get("channelTitle"),
                "category_id": snippet.get("categoryId"),
                "published_at": snippet.get("publishedAt"),
                "view_count": stats.get("viewCount", 0),
                "like_count": stats.get("likeCount", 0),
                "comment_count": stats.get("commentCount", 0),
                "tags": ",".join(snippet.get("tags", [])) if snippet.get("tags") else "",
                "url": f"https://www.youtube.com/watch?v={item.get('id')}"
            })

        next_page_token = response.get("nextPageToken")
        if not next_page_token:
            break

    return videos[:TOTAL_VIDEOS]


def save_to_csv(videos, filename):
    if not videos:
        print("수집된 데이터가 없습니다.")
        return

    keys = videos[0].keys()
    with open(filename, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=keys)
        writer.writeheader()
        writer.writerows(videos)

    print(f"완료! {len(videos)}개 영상 데이터를 '{filename}' 파일로 저장했습니다.")


if __name__ == "__main__":
    if not API_KEY:
        raise SystemExit("YOUTUBE_API_KEY가 없습니다. 루트 .env 파일을 확인하세요.")

    print(f"[{REGION_CODE}] 인기 급상승 영상 수집을 시작합니다...")
    trending_videos = get_trending_videos()
    save_to_csv(trending_videos, OUTPUT_FILE)
