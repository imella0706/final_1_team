# -*- coding: utf-8 -*-
"""
[3단계] 수집한 데이터로 트렌드 분석
--------------------------------------------------
사용법
1. KEYWORD를 1·2단계와 똑같이 입력
2. 터미널에서 실행:  python step3_analyze.py
결과
- trend_monthly.png    월별 블로그 글 수 추이
- trend_words.png      자주 등장하는 단어 TOP 20
- trend_search.png     네이버 검색량 추이 (데이터랩)
- word_freq.csv        단어 빈도표 (보고서용)
필요 라이브러리:  pip install pandas matplotlib kiwipiepy
"""
import platform
import os
from collections import Counter

import matplotlib.pyplot as plt
import pandas as pd

# ========== 여기만 수정하세요 ==========
KEYWORD = "카페"        # 1·2단계와 같은 키워드
# 빈도 분석에서 제외할 단어 (결과를 보고 자유롭게 추가하세요)
STOPWORDS = {"네이버", "블로그", "오늘", "정말", "생각", "때문", "그리고"}
# ======================================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def data_path(filename):
    return os.path.join(BASE_DIR, filename)

# ----- 한글 폰트 설정 (그래프 한글 깨짐 방지) -----
system = platform.system()
if system == "Windows":
    plt.rcParams["font.family"] = "Malgun Gothic"
elif system == "Darwin":                     # macOS
    plt.rcParams["font.family"] = "AppleGothic"
else:                                        # Linux
    plt.rcParams["font.family"] = "NanumGothic"
plt.rcParams["axes.unicode_minus"] = False

# ===== 1. 월별 글 수 추이 =====
df = pd.read_csv(data_path(f"naver_blog_{KEYWORD}.csv"), parse_dates=["date"])
print(f"블로그 데이터: 총 {len(df)}건, "
      f"기간 {df['date'].min().date()} ~ {df['date'].max().date()}")

monthly = df.groupby(df["date"].dt.to_period("M")).size()
plt.figure(figsize=(10, 4))
monthly.plot(kind="bar", color="#4C72B0")
plt.title(f"'{KEYWORD}' 월별 블로그 글 수 (최신 수집분 기준)")
plt.xlabel("월")
plt.ylabel("글 수")
plt.xticks(rotation=45)
plt.tight_layout()
plt.savefig(data_path("trend_monthly.png"), dpi=150)
plt.close()
print("저장 완료 → trend_monthly.png")

# ===== 2. 자주 등장하는 단어 TOP 20 =====
try:
    from kiwipiepy import Kiwi

    kiwi = Kiwi()
    texts = (df["title"].fillna("") + " " + df["description"].fillna(""))

    words = []
    for text in texts:
        for token in kiwi.tokenize(text):
            # 일반명사(NNG)·고유명사(NNP)만, 2글자 이상, 불용어 제외
            if (token.tag in ("NNG", "NNP")
                    and len(token.form) >= 2
                    and token.form not in STOPWORDS):
                words.append(token.form)

    top = Counter(words).most_common(20)
    freq_df = pd.DataFrame(top, columns=["단어", "빈도"])
    freq_df.to_csv(data_path("word_freq.csv"), index=False, encoding="utf-8-sig")

    plt.figure(figsize=(9, 6))
    plt.barh(freq_df["단어"][::-1], freq_df["빈도"][::-1], color="#55A868")
    plt.title(f"'{KEYWORD}' 관련 글에 자주 등장하는 단어 TOP 20")
    plt.xlabel("등장 횟수")
    plt.tight_layout()
    plt.savefig(data_path("trend_words.png"), dpi=150)
    plt.close()
    print("저장 완료 → trend_words.png, word_freq.csv")
except ImportError:
    print("kiwipiepy가 없어 단어 분석을 건너뜁니다. 설치: pip install kiwipiepy")

# ===== 3. 검색량 추이 (데이터랩) =====
try:
    dl = pd.read_csv(data_path(f"datalab_{KEYWORD}.csv"), parse_dates=["period"])
    plt.figure(figsize=(10, 4))
    plt.plot(dl["period"], dl["ratio"], color="#C44E52", linewidth=2)
    plt.title(f"'{KEYWORD}' 네이버 검색량 추이 (기간 내 최대=100 상대값)")
    plt.xlabel("기간")
    plt.ylabel("상대 검색량")
    plt.tight_layout()
    plt.savefig(data_path("trend_search.png"), dpi=150)
    plt.close()
    print("저장 완료 → trend_search.png")
except FileNotFoundError:
    print(f"datalab_{KEYWORD}.csv 가 없습니다. step2를 먼저 실행하세요.")

print("\n3단계 완료! 생성된 PNG 그래프와 CSV를 보고서에 활용하세요.")
