from __future__ import annotations

import csv
import hashlib
import html
import json
import math
import re
import unicodedata
from dataclasses import replace
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Iterable

from .models import Scene, SearchResult, Storyboard, TrendCard


TOKEN_RE = re.compile(r"[0-9a-zA-Z가-힣]+")
GENERIC_QUERY_TERMS = {
    "광고",
    "기반",
    "만들기",
    "만들어",
    "밈",
    "사용",
    "숏폼",
    "영상",
    "위한",
    "이용",
    "제작",
    "트렌드",
    "활용",
}
SOURCE_PRIOR = {
    "gogumafarm": 0.85,
    "careet": 0.8,
    "youtube": 0.5,
    "naver": 0.35,
}
NOISE_TITLES = {
    "어디서시작됐나요",
    "어떻게쓸까",
    "이렇게사용하세요",
    "최신밈트렌드",
    "사용예시",
    "활용예시",
}


def _normalized(value: str) -> str:
    return unicodedata.normalize("NFKC", value or "").casefold().strip()


def _tokens(value: str, *, drop_generic: bool = False) -> set[str]:
    values = {
        token
        for token in TOKEN_RE.findall(_normalized(value))
        if len(token) >= 2 or token in {"ai", "3d"}
    }
    if drop_generic:
        values.difference_update(GENERIC_QUERY_TERMS)
    return values


def _canonical_title(value: str) -> str:
    return "".join(TOKEN_RE.findall(_normalized(value)))


def _latest(paths: Iterable[Path]) -> Path | None:
    candidates = list(paths)
    return max(candidates, key=lambda path: path.name) if candidates else None


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def _number(value: str | None) -> float:
    try:
        return float(str(value or "0").replace(",", ""))
    except ValueError:
        return 0.0


def _careet_cards(root: Path) -> list[TrendCard]:
    path = _latest(
        (root / "gather_data/crawling/careet/data/processed").glob(
            "careet_memes_*.csv"
        )
    )
    if path is None:
        return []

    cards: list[TrendCard] = []
    for row in _read_csv(path):
        title = (row.get("meme_name") or "").strip()
        status = (row.get("trend_status") or "unknown").strip()
        canonical = _canonical_title(title)
        if (
            not title
            or status not in {"current", "unknown"}
            or canonical in NOISE_TITLES
            or canonical.startswith("요즘뜨는해외숏폼밈")
        ):
            continue
        summary = (row.get("meme_summary") or "").strip()
        usage = (row.get("usage_example") or "").strip()
        cards.append(
            TrendCard(
                card_id=f"careet:{row.get('meme_id') or title}",
                title=title,
                source="careet",
                published_date=(row.get("published_date") or "").strip(),
                source_url=(row.get("source_url") or "").strip(),
                summary=summary,
                context=" | ".join(
                    value
                    for value in (
                        (row.get("parent_section") or "").strip(),
                        usage,
                    )
                    if value
                ),
                signal=1.0 if status == "current" else 0.5,
                metadata={
                    "input_file": str(path.relative_to(root)),
                    "trend_status": status,
                    "summary_confidence": row.get("summary_confidence") or "",
                },
            )
        )
    return cards


def _gogumafarm_cards(root: Path) -> list[TrendCard]:
    path = _latest(
        (root / "gather_data/crawling/gogumafarm/data/processed").glob(
            "gogumafarm_meme_terms_*.csv"
        )
    )
    if path is None:
        return []

    rows = _read_csv(path)
    parsed_dates = []
    for row in rows:
        try:
            parsed_dates.append(datetime.fromisoformat((row.get("published_date") or "")[:10]).date())
        except ValueError:
            continue
    cutoff = max(parsed_dates) - timedelta(days=180) if parsed_dates else None

    cards: list[TrendCard] = []
    for row in rows:
        title = (row.get("term") or "").strip()
        canonical = _canonical_title(title)
        published_text = (row.get("published_date") or "").strip()
        try:
            published = datetime.fromisoformat(published_text[:10]).date()
        except ValueError:
            published = None
        if (
            not title
            or canonical in NOISE_TITLES
            or canonical.startswith("요즘뜨는해외숏폼밈")
            or (cutoff is not None and published is not None and published < cutoff)
        ):
            continue
        relevance = _number(row.get("relevance_score"))
        stable_key = hashlib.sha256(
            f"{row.get('source_url') or ''}\0{_normalized(title)}".encode("utf-8")
        ).hexdigest()[:16]
        cards.append(
            TrendCard(
                card_id=f"gogumafarm:{stable_key}",
                title=title,
                source="gogumafarm",
                published_date=published_text,
                source_url=(row.get("source_url") or "").strip(),
                context=(row.get("tags") or "").replace("|", " "),
                signal=min(relevance / 3.0, 1.0),
                metadata={
                    "input_file": str(path.relative_to(root)),
                    "term_type": row.get("term_type") or "",
                    "relevance_score": relevance,
                },
            )
        )
    return cards


def _youtube_cards(root: Path) -> list[TrendCard]:
    path = _latest((root / "gather_data/youtube").glob("youtube_trending_KR_*.csv"))
    if path is None:
        return []

    cards: list[TrendCard] = []
    for row in _read_csv(path):
        title = (row.get("title") or "").strip()
        if not title:
            continue
        views = _number(row.get("view_count"))
        published_at = (row.get("published_at") or "").strip()
        cards.append(
            TrendCard(
                card_id=f"youtube:{row.get('video_id') or title}",
                title=title,
                source="youtube",
                published_date=published_at[:10],
                source_url=(row.get("url") or "").strip(),
                summary=(row.get("channel_title") or "").strip(),
                context=(row.get("tags") or "").replace(",", " "),
                signal=min(math.log1p(views) / 16.0, 1.0),
                metadata={
                    "input_file": str(path.relative_to(root)),
                    "view_count": int(views),
                    "like_count": int(_number(row.get("like_count"))),
                },
            )
        )
    return cards


def _naver_cards(root: Path) -> list[TrendCard]:
    path = root / "gather_data/naver/word_freq.csv"
    if not path.exists():
        return []

    cards: list[TrendCard] = []
    for index, row in enumerate(_read_csv(path)):
        title = (row.get("단어") or row.get("keyword") or "").strip()
        frequency = _number(row.get("빈도") or row.get("count"))
        if not title:
            continue
        cards.append(
            TrendCard(
                card_id=f"naver:{index}:{title}",
                title=title,
                source="naver",
                context="네이버 수집 문서의 연관 단어",
                signal=min(math.log1p(frequency) / 8.0, 1.0),
                metadata={
                    "input_file": str(path.relative_to(root)),
                    "frequency": int(frequency),
                },
            )
        )
    return cards


def load_trend_cards(repo_root: Path) -> list[TrendCard]:
    """Load the newest local snapshot from every supported source."""

    root = repo_root.resolve()
    cards = [
        *_careet_cards(root),
        *_gogumafarm_cards(root),
        *_youtube_cards(root),
        *_naver_cards(root),
    ]

    deduplicated: dict[str, TrendCard] = {}
    for card in cards:
        key = _canonical_title(card.title)
        if not key:
            continue
        existing = deduplicated.get(key)
        if existing is None:
            deduplicated[key] = card
            continue

        existing_rank = SOURCE_PRIOR.get(existing.source, 0.0) + existing.signal
        incoming_rank = SOURCE_PRIOR.get(card.source, 0.0) + card.signal
        primary, secondary = (
            (card, existing) if incoming_rank > existing_rank else (existing, card)
        )
        seen = set(primary.metadata.get("also_seen_in", []))
        seen.update((primary.source, secondary.source))
        metadata = dict(primary.metadata)
        metadata["also_seen_in"] = sorted(seen)
        deduplicated[key] = replace(primary, metadata=metadata)

    return sorted(
        deduplicated.values(),
        key=lambda card: (card.published_date, card.source, card.title),
        reverse=True,
    )


def _freshness(published_date: str) -> float:
    if not published_date:
        return 0.1
    try:
        published = datetime.fromisoformat(published_date[:10]).date()
    except ValueError:
        return 0.1
    days = max((date.today() - published).days, 0)
    return max(0.0, 1.0 - days / 180.0)


def search_trends(
    cards: Iterable[TrendCard], query: str, *, limit: int = 5
) -> list[SearchResult]:
    query_norm = _normalized(query)
    query_tokens = _tokens(query, drop_generic=True)
    scored: list[SearchResult] = []

    for card in cards:
        title_norm = _normalized(card.title)
        title_tokens = _tokens(card.title)
        all_tokens = _tokens(card.search_text)
        title_matches = query_tokens & title_tokens
        context_matches = (query_tokens & all_tokens) - title_matches

        score = SOURCE_PRIOR.get(card.source, 0.25)
        score += card.signal * 1.2
        score += _freshness(card.published_date) * 0.8
        score += len(title_matches) * 4.0
        score += len(context_matches) * 1.25
        reasons: list[str] = []

        canonical = _canonical_title(card.title)
        if canonical and len(canonical) >= 3 and canonical in _canonical_title(query_norm):
            score += 9.0
            reasons.append("제목 구문 일치")
        if title_matches:
            reasons.append("제목 키워드 일치")
        if context_matches:
            reasons.append("설명/태그 일치")
        if card.published_date:
            reasons.append("최신성 반영")
        if not reasons:
            reasons.append("소스 신뢰도와 신호값")

        matched_terms = tuple(sorted(title_matches | context_matches))
        scored.append(
            SearchResult(
                card=card,
                score=score,
                matched_terms=matched_terms,
                reasons=tuple(reasons),
            )
        )

    return sorted(
        scored,
        key=lambda result: (
            result.score,
            result.card.published_date,
            result.card.signal,
        ),
        reverse=True,
    )[: max(limit, 1)]


def build_storyboard(
    *,
    brief: str,
    product: str,
    audience: str,
    cta: str,
    trend: TrendCard,
) -> Storyboard:
    trend_context = trend.summary or trend.context or "짧고 반복 가능한 밈 포맷"
    scenes = (
        Scene(
            start=0.0,
            end=2.2,
            role="hook",
            on_screen_text=f"{trend.title}\n이 타이밍에?",
            visual_direction="강한 대비의 세로 화면에 밈 이름을 먼저 노출한다.",
            motion="텍스트가 아래에서 빠르게 진입하고 2회 짧게 펄스한다.",
        ),
        Scene(
            start=2.2,
            end=4.6,
            role="trend_evidence",
            on_screen_text=f"지금 포착한 트렌드\n{trend.title}",
            visual_direction=f"출처 {trend.source}와 트렌드 카드를 편집 화면처럼 보여준다.",
            motion="카드가 좌측에서 슬라이드되고 핵심 단어에 밑줄이 그어진다.",
        ),
        Scene(
            start=4.6,
            end=7.8,
            role="product_payoff",
            on_screen_text=f"{product}\n피드에 꽂히는 한 장면",
            visual_direction=f"{audience} 타깃이 즉시 알아볼 수 있는 제품 실루엣과 사용 장면을 배치한다.",
            motion="제품이 92%에서 100%로 확대되고 포인트 컬러가 회전한다.",
        ),
        Scene(
            start=7.8,
            end=10.0,
            role="cta",
            on_screen_text=f"{cta}\n{product}",
            visual_direction="브랜드 영역과 CTA를 생성 영상 위에 후합성할 수 있게 비워 둔다.",
            motion="CTA가 짧게 상승하고 마지막 0.8초 동안 정지한다.",
        ),
    )

    scene_lines = "\n".join(
        f"- {scene.start:.1f}-{scene.end:.1f}s [{scene.role}] "
        f"{scene.visual_direction} Motion: {scene.motion} "
        f"On-screen text: {scene.on_screen_text!r}"
        for scene in scenes
    )
    generation_prompt = f"""Create a 10-second vertical 9:16 Korean short-form ad.

Product: {product}
Audience: {audience}
Creative brief: {brief}
Trend inspiration: {trend.title}
Trend context: {trend_context}

Use the trend only as an abstract timing, rhythm, and communication pattern. Do not reproduce the source creator, footage, music, logo, or a recognizably identical composition.

Storyboard:
{scene_lines}

Visual direction: crisp commercial lighting, clear product silhouette, fast editorial pacing, four distinct beats, safe center composition for mobile UI overlays. Keep product appearance consistent across shots. Leave final typography, brand logo, price, and CTA for deterministic post-production."""

    return Storyboard(
        brief=brief,
        product=product,
        audience=audience,
        cta=cta,
        trend=trend,
        duration_seconds=10.0,
        aspect_ratio="9:16",
        scenes=scenes,
        generation_prompt=generation_prompt,
        negative_prompt=(
            "illegible text, mutated product, duplicate objects, extra fingers, "
            "third-party logos, watermarks, copied creator likeness, abrupt identity changes"
        ),
        rights_note=(
            "The source URL is discovery evidence only. Use owned or explicitly licensed "
            "media for model conditioning and commercial publication."
        ),
    )


def write_text_artifacts(
    output_dir: Path,
    *,
    results: list[SearchResult],
    storyboard: Storyboard,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    retrieval = {
        "query": storyboard.brief,
        "selected_card_id": storyboard.trend.card_id,
        "results": [result.to_dict() for result in results],
    }
    (output_dir / "retrieval.json").write_text(
        json.dumps(retrieval, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (output_dir / "storyboard.json").write_text(
        json.dumps(storyboard.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (output_dir / "prompt.txt").write_text(
        storyboard.generation_prompt + "\n\nNegative prompt:\n" + storyboard.negative_prompt,
        encoding="utf-8",
    )


def write_html_report(
    output_dir: Path,
    *,
    results: list[SearchResult],
    storyboard: Storyboard,
    has_video: bool,
    has_gif: bool,
) -> Path:
    rows = "\n".join(
        "<tr>"
        f"<td>{index}</td>"
        f"<td><strong>{html.escape(result.card.title)}</strong></td>"
        f"<td>{html.escape(result.card.source)}</td>"
        f"<td>{result.score:.2f}</td>"
        f"<td>{html.escape(', '.join(result.matched_terms) or '-')}</td>"
        "</tr>"
        for index, result in enumerate(results, start=1)
    )
    if has_gif:
        media = '<img class="gif" src="preview.gif" alt="Animatic preview">'
        if has_video:
            media += '<a class="media-link" href="animatic.mp4">MP4 열기</a>'
    else:
        media = (
            '<video controls playsinline src="animatic.mp4"></video>' if has_video else ""
        )
    source_link = (
        f'<a href="{html.escape(storyboard.trend.source_url)}">원문 후보 열기</a>'
        if storyboard.trend.source_url
        else "원문 링크 없음"
    )
    page = f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Trend to Ad Demo</title>
  <style>
    :root {{ color-scheme: light; font-family: "Malgun Gothic", "Noto Sans KR", sans-serif; }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; background: #f3f4f6; color: #171717; }}
    header {{ background: #171717; color: white; padding: 18px 28px; border-bottom: 4px solid #ffd84d; }}
    header h1 {{ margin: 0; font-size: 22px; letter-spacing: 0; }}
    header p {{ margin: 6px 0 0; color: #c8c8c8; font-size: 14px; }}
    main {{ max-width: 1180px; margin: 0 auto; padding: 28px; }}
    .summary {{ display: grid; grid-template-columns: minmax(280px, 400px) 1fr; gap: 28px; align-items: start; }}
    .media {{ background: #0f0f0f; padding: 16px; border-radius: 6px; min-height: 520px; display: grid; place-items: center; }}
    video, .gif {{ width: min(100%, 330px); max-height: 70vh; object-fit: contain; }}
    .media-link {{ display: block; color: white; padding: 8px 0 0; font-size: 14px; }}
    section {{ padding: 24px 0; border-bottom: 1px solid #d6d8dc; }}
    h2 {{ margin: 0 0 14px; font-size: 17px; letter-spacing: 0; }}
    .facts {{ display: grid; grid-template-columns: 120px 1fr; gap: 10px 16px; margin: 0; }}
    .facts dt {{ color: #686b70; }} .facts dd {{ margin: 0; font-weight: 600; }}
    pre {{ white-space: pre-wrap; overflow-wrap: anywhere; background: #fff; border-left: 4px solid #6557d9; padding: 18px; margin: 0; font: 13px/1.55 Consolas, monospace; }}
    table {{ width: 100%; border-collapse: collapse; background: white; font-size: 14px; }}
    th, td {{ text-align: left; padding: 11px 12px; border-bottom: 1px solid #e3e4e7; }}
    th {{ background: #e8eaee; color: #4e5156; }}
    a {{ color: #4f46c8; }}
    @media (max-width: 760px) {{ .summary {{ grid-template-columns: 1fr; }} main {{ padding: 18px; }} }}
  </style>
</head>
<body>
  <header><h1>Trend → Ad Prototype</h1><p>로컬 CSV 검색 결과와 광고 애니매틱</p></header>
  <main>
    <div class="summary">
      <div class="media">{media}</div>
      <div>
        <section>
          <h2>선택 결과</h2>
          <dl class="facts">
            <dt>제품</dt><dd>{html.escape(storyboard.product)}</dd>
            <dt>타깃</dt><dd>{html.escape(storyboard.audience)}</dd>
            <dt>밈 후보</dt><dd>{html.escape(storyboard.trend.title)}</dd>
            <dt>출처</dt><dd>{html.escape(storyboard.trend.source)} · {source_link}</dd>
            <dt>형식</dt><dd>{storyboard.duration_seconds:.0f}초 · {storyboard.aspect_ratio}</dd>
          </dl>
        </section>
        <section><h2>입력 브리프</h2><p>{html.escape(storyboard.brief)}</p></section>
        <section><h2>권리 메모</h2><p>{html.escape(storyboard.rights_note)}</p></section>
      </div>
    </div>
    <section><h2>검색 후보</h2><table><thead><tr><th>#</th><th>후보</th><th>출처</th><th>점수</th><th>일치어</th></tr></thead><tbody>{rows}</tbody></table></section>
    <section><h2>영상 모델 입력 프롬프트</h2><pre>{html.escape(storyboard.generation_prompt)}</pre></section>
  </main>
</body>
</html>
"""
    report = output_dir / "report.html"
    report.write_text(page, encoding="utf-8")
    return report
