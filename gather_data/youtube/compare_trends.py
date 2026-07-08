# -*- coding: utf-8 -*-
"""
[비교 분석] history 폴더에 쌓인 날짜별 키워드 데이터를 비교해서
'급상승 키워드' (증가폭이 큰 키워드)를 뽑아냅니다.

daily_keyword_tracker.py 를 며칠간 실행해서 history 폴더에
keywords_YYYY-MM-DD.csv 파일이 2개 이상 쌓여있어야 합니다.

사전 준비:
1. pip install pandas matplotlib
2. python compare_trends.py 실행
   (기본적으로 가장 오래된 날짜 vs 가장 최근 날짜를 비교합니다)
"""

import pandas as pd
import matplotlib.pyplot as plt
import glob
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
HISTORY_DIR = os.path.join(BASE_DIR, "history")
TOP_N = 20

plt.rcParams["font.family"] = "Malgun Gothic"   # Windows
# plt.rcParams["font.family"] = "AppleGothic"   # Mac
plt.rcParams["axes.unicode_minus"] = False


def load_history():
    files = sorted(glob.glob(os.path.join(HISTORY_DIR, "keywords_*.csv")))
    if len(files) < 2:
        raise SystemExit(
            f"비교하려면 최소 2개 날짜의 데이터가 필요합니다. "
            f"현재 {len(files)}개 있습니다. daily_keyword_tracker.py를 며칠 더 실행해주세요."
        )
    return files


def compare(old_file, new_file):
    old_date = os.path.basename(old_file).replace("keywords_", "").replace(".csv", "")
    new_date = os.path.basename(new_file).replace("keywords_", "").replace(".csv", "")

    old_df = pd.read_csv(old_file, encoding="utf-8-sig").set_index("keyword")["count"]
    new_df = pd.read_csv(new_file, encoding="utf-8-sig").set_index("keyword")["count"]

    merged = pd.DataFrame({"old_count": old_df, "new_count": new_df}).fillna(0)
    merged["change"] = merged["new_count"] - merged["old_count"]
    merged = merged.sort_values("change", ascending=False)

    print(f"\n===== {old_date} → {new_date} 급상승 키워드 TOP {TOP_N} =====")
    print(merged.head(TOP_N))

    comparison_csv = os.path.join(BASE_DIR, "keyword_trend_comparison.csv")
    merged.to_csv(comparison_csv, encoding="utf-8-sig")
    print("\n저장됨: keyword_trend_comparison.csv (전체 비교 결과)")

    top = merged.head(TOP_N)
    plt.figure(figsize=(10, 6))
    plt.barh(top.index[::-1], top["change"][::-1], color="orange")
    plt.title(f"급상승 키워드 TOP {TOP_N} ({old_date} → {new_date})")
    plt.xlabel("증가량 (등장 횟수 변화)")
    plt.tight_layout()
    comparison_png = os.path.join(BASE_DIR, "keyword_trend_comparison.png")
    plt.savefig(comparison_png)
    print("저장됨: keyword_trend_comparison.png")


if __name__ == "__main__":
    files = load_history()
    compare(files[0], files[-1])   # 가장 오래된 날짜 vs 가장 최근 날짜
