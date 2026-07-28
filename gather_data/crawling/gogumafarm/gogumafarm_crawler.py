"""Gogumafarm public WordPress metadata crawler.

Only the public WordPress REST API is requested. Full article bodies, rendered
HTML, cookies, image binaries, and embedded media are never persisted.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import logging
import os
import re
import time
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence
from urllib.parse import unquote, urljoin, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup, Tag


BASE_URL = "https://gogumafarm.kr"
API_BASE = f"{BASE_URL}/wp-json/wp/v2"
SOURCE_URL = f"{BASE_URL}/category/trends/"
SCHEMA_VERSION = "1.0"
CRAWLER_RUN_SUMMARY_FILENAME = "crawler_run_summary.json"
CRAWLER_ERROR_FILENAME = "error.json"

CATEGORY_NAME = "최신 밈과 트렌드"
CATEGORY_SLUG = "trends"
TAG_NAME = "밈"
TAG_ID_HINT = 110

USER_AGENT = "GogumafarmPublicMetadataCrawler/1.0 (research; no-login; contact: local-user)"
RETRYABLE_STATUS = {429, 500, 502, 503, 504}
KST = timezone(timedelta(hours=9))
CHECKPOINT_NAME = ".gogumafarm_checkpoint.json"
REPO_ROOT = Path(__file__).resolve().parents[3]
LANDING_DATA_ROOT = REPO_ROOT / "data" / "landing" / "sns_trend"
CURATED_DATA_ROOT = REPO_ROOT / "data" / "curated" / "sns_trend"
DEFAULT_CURATED_VERSION = "v3"

POST_FIELDS = ",".join(
    [
        "id",
        "date",
        "date_gmt",
        "modified",
        "modified_gmt",
        "slug",
        "status",
        "link",
        "title",
        "content",
        "excerpt",
        "author",
        "featured_media",
        "categories",
        "tags",
        "_links",
        "_embedded",
    ]
)

COMMON_HEADINGS = {
    "",
    "공유하기",
    "관련 글",
    "관련글",
    "추천 글",
    "추천글",
    "이전 글",
    "이전글",
    "다음 글",
    "다음글",
}
EXPLANATORY_HEADINGS = [
    "어떤 밈인가요",
    "유래",
    "왜 유행하나요",
    "어떻게 활용하나요",
    "마케팅 활용",
    "출처",
]
PARSER_VERSION = "2026-07-09.api_terms.1"

MEME_SIGNAL_TERMS = {
    "밈",
    "유행",
    "트렌드",
    "바이럴",
    "SNS",
    "릴스",
    "챌린지",
    "숏폼",
    "틱톡",
    "인스타그램",
    "X(트위터)",
    "크리에이터",
}
TERM_REJECT_PATTERNS = {
    "궁금하다면",
    "확인해 보세요",
    "살펴보세요",
    "모아봤",
    "브랜드",
    "마케터",
    "아티클",
    "활용법",
    "활용해",
    "소개할게요",
    "정리했어요",
    "놓치지 마세요",
    "외부 필진",
    "고구마팜",
    "뉴스레터",
    "구독",
    "문의하기",
    "클릭",
    "확인하기",
    "보러가기",
    "알려드림",
    "추천",
    "리포트",
    "광고",
    "이벤트",
    "캠페인",
    "전략",
    "사례",
    "인사이트",
}
EXACT_REJECT_TERMS = {
    "최신",
    "최신 밈",
    "인기 릴스",
    "틱톡",
    "챌린지",
    "유튜브 쇼츠",
}
GENERIC_TERM_PATTERNS = {
    "어떤 밈인가요",
    "어떤 콘텐츠인가요",
    "어떻게 활용할 수 있나요",
    "이렇게 활용해 보세요",
    "브랜드 인사이트",
    "함께 보면 더 알찬 아티클",
    "이런 아티클도 있어요",
    "한 입 더",
    "사용 예시",
    "에디터의 첨언",
    "출처 확인이 무엇보다 중요",
    "브랜드 활용 팁",
    "활용 방법",
    "최신 밈",
    "SNS 최신 숏폼",
}

ARTICLE_CSV_FIELDS = [
    "source",
    "category_name",
    "article_id",
    "url",
    "title",
    "published_date",
    "tags",
    "thumbnail_url",
    "is_meme_related",
    "meme_signal_terms",
    "heading_count",
    "detail_fetch_status",
    "list_page",
    "list_position",
    "content_hash",
    "parser_version",
    "collected_at",
]
TERM_CSV_FIELDS = [
    "term_id",
    "article_id",
    "term",
    "term_type",
    "source_field",
    "position",
    "published_date",
    "tags",
    "relevance_score",
    "source_url",
    "collected_at",
]

LOG = logging.getLogger("gogumafarm_crawler")


class CrawlerError(RuntimeError):
    """Fatal crawl or parse failure."""


class CountChangedError(CrawlerError):
    """Raised when WordPress pagination totals change mid-run."""


class HTTPStatusError(RuntimeError):
    def __init__(self, url: str, status_code: int):
        super().__init__(f"HTTP {status_code}: {url}")
        self.url = url
        self.status_code = status_code


@dataclass(frozen=True)
class KeywordArtifacts:
    term_rows: list[dict[str, Any]]
    final_terms: list[str]
    display_terms: list[str]


@dataclass(frozen=True)
class Taxonomy:
    id: int
    name: str
    slug: str


@dataclass
class HeadingEntry:
    level: int
    text: str
    order: int
    tag: Tag
    tag_index: int


@dataclass
class ExtractionResult:
    status: str
    items: list[dict[str, Any]] = field(default_factory=list)
    duplicate_names: int = 0


@dataclass
class RunStats:
    api_total: int = 0
    excluded_missing_required: int = 0
    filtered_out: int = 0
    duplicate_posts: int = 0
    duplicate_meme_names: int = 0
    new_posts: int = 0
    modified_posts: int = 0
    reused_posts: int = 0
    removed_posts: int = 0


def clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def html_to_text(value: Any) -> str:
    if value in (None, ""):
        return ""
    return clean_text(BeautifulSoup(str(value), "html.parser").get_text(" ", strip=True))


def trim_text(value: str, limit: int) -> str:
    value = clean_text(value)
    return value if len(value) <= limit else value[:limit].rstrip()


def now_kst() -> str:
    return datetime.now(KST).isoformat(timespec="seconds")


def now_utc_z() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def current_run_date() -> date:
    return datetime.now(KST).date()


def parse_run_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise CrawlerError("--date must use YYYY-MM-DD format") from exc


def parse_iso_week(value: str) -> str:
    normalized = value.strip().upper()
    match = re.fullmatch(r"(\d{4})-W(\d{2})", normalized)
    if match is None:
        raise CrawlerError("--week must use YYYY-Www format")
    year, week = (int(part) for part in match.groups())
    try:
        date.fromisocalendar(year, week, 1)
    except ValueError as exc:
        raise CrawlerError(f"invalid ISO week: {normalized}") from exc
    return normalized


def parse_dataset_version(value: str) -> str:
    normalized = value.strip().lower()
    if not re.fullmatch(r"v[1-9][0-9]*", normalized):
        raise CrawlerError("dataset version must use vN format, for example v3")
    return normalized


def parse_run_id(value: str) -> str:
    normalized = value.strip()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:+@=-]{0,254}", normalized):
        raise CrawlerError("--run-id must be 1-255 path-safe ASCII characters")
    return normalized


def landing_run_directory(
    *,
    week: str,
    run_id: str,
    root: Path = LANDING_DATA_ROOT,
) -> Path:
    # [Design Intent] Isolate each crawler execution so reruns never overwrite
    # another Airflow/manual run inside the shared landing partition.
    return root / f"week={week}" / "raw" / "gogumafarm" / f"run_id={run_id}"


def curated_meme_card_candidates_path(
    *,
    version: str,
    week: str,
    root: Path = CURATED_DATA_ROOT,
) -> Path:
    return root / version / "meme_card_candidates" / "gogumafarm" / f"gogumafarm_meme_card_candidates_{week}.json"


def utc_z(value: Any) -> str:
    value = clean_text(value)
    if not value:
        return ""
    normalized = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return value if value.endswith("Z") else f"{value}Z"
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds") + "Z"


def decode_slug(value: Any) -> str:
    return unquote(clean_text(value))


def _normalize_key(value: str) -> str:
    return re.sub(r"[\W_]+", "", clean_text(value), flags=re.UNICODE).lower()


def is_common_heading(value: str) -> bool:
    return clean_text(value) in COMMON_HEADINGS


def is_explanatory_heading(value: str) -> bool:
    key = _normalize_key(value)
    return any(key == _normalize_key(item) or key.startswith(_normalize_key(item)) for item in EXPLANATORY_HEADINGS)


class PoliteSession:
    """Rate-limited requests session with bounded retries."""

    def __init__(self, delay: float = 1.0, timeout: float = 15.0, retries: int = 3):
        self.delay = delay
        self.timeout = timeout
        self.retries = retries
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": USER_AGENT,
                "Accept": "application/json",
                "Accept-Language": "ko-KR,ko;q=0.9",
            }
        )
        self._last_request_at: float | None = None

    def close(self) -> None:
        self.session.close()

    def _wait(self) -> None:
        if self._last_request_at is None:
            return
        remaining = self.delay - (time.monotonic() - self._last_request_at)
        if remaining > 0:
            time.sleep(remaining)

    def get(self, url: str, *, params: dict[str, Any] | None = None) -> requests.Response:
        attempts = self.retries + 1
        for attempt in range(attempts):
            self._wait()
            try:
                response = self.session.get(url, params=params, timeout=(self.timeout, self.timeout))
                self._last_request_at = time.monotonic()
            except requests.RequestException:
                self._last_request_at = time.monotonic()
                if attempt + 1 >= attempts:
                    raise
                wait = float(2**attempt)
                LOG.warning("network error; retrying in %.1fs (%d/%d)", wait, attempt + 1, self.retries)
                time.sleep(wait)
                continue

            if response.status_code not in RETRYABLE_STATUS:
                if not response.ok:
                    response.close()
                    raise HTTPStatusError(response.url, response.status_code)
                return response

            status = response.status_code
            retry_after = response.headers.get("Retry-After", "")
            response.close()
            if attempt + 1 >= attempts:
                raise HTTPStatusError(url, status)
            try:
                wait = max(float(retry_after), float(2**attempt))
            except ValueError:
                wait = float(2**attempt)
            LOG.warning("HTTP %d; retrying in %.1fs (%d/%d)", status, wait, attempt + 1, self.retries)
            time.sleep(wait)
        raise AssertionError("unreachable")

    def get_json(self, endpoint: str, *, params: dict[str, Any] | None = None) -> tuple[Any, dict[str, str]]:
        url = endpoint if endpoint.startswith("http") else f"{API_BASE}/{endpoint.lstrip('/')}"
        response = self.get(url, params=params)
        try:
            content_type = response.headers.get("Content-Type", "").split(";", 1)[0].lower()
            if content_type not in {"application/json", "application/ld+json"}:
                raise CrawlerError(f"non-JSON response from {response.url}: {content_type!r}")
            try:
                return response.json(), dict(response.headers)
            except ValueError as exc:
                raise CrawlerError(f"invalid JSON response from {response.url}") from exc
        finally:
            response.close()


def _validate_wp_array(data: Any, context: str) -> list[dict[str, Any]]:
    if isinstance(data, dict):
        code = clean_text(data.get("code", "unknown"))
        raise CrawlerError(f"WordPress error object returned for {context}: {code}")
    if not isinstance(data, list):
        raise CrawlerError(f"{context} response must be a JSON array")
    return [item for item in data if isinstance(item, dict)]


def _validate_wp_object(data: Any, context: str) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise CrawlerError(f"{context} response must be a JSON object")
    if "code" in data and "message" in data:
        raise CrawlerError(f"WordPress error object returned for {context}: {clean_text(data.get('code'))}")
    return data


def _taxonomy_from_item(item: dict[str, Any]) -> Taxonomy:
    return Taxonomy(id=int(item["id"]), name=html_to_text(item.get("name", "")), slug=decode_slug(item.get("slug", "")))


def resolve_category(client: Any) -> Taxonomy:
    data, _ = client.get_json("categories", params={"slug": CATEGORY_SLUG, "per_page": 100})
    matches = _validate_wp_array(data, "category slug lookup")
    for item in matches:
        category = _taxonomy_from_item(item)
        if category.slug == CATEGORY_SLUG and category.name == CATEGORY_NAME:
            return category

    data, _ = client.get_json("categories", params={"search": CATEGORY_NAME, "per_page": 100})
    for item in _validate_wp_array(data, "category search"):
        category = _taxonomy_from_item(item)
        if category.name == CATEGORY_NAME:
            return category
    raise CrawlerError(f"target category not found: {CATEGORY_NAME}")


def resolve_tag(client: Any) -> Taxonomy:
    try:
        data, _ = client.get_json(f"tags/{TAG_ID_HINT}")
        item = _validate_wp_object(data, "tag id lookup")
        tag = _taxonomy_from_item(item)
        if tag.name == TAG_NAME:
            return tag
    except (HTTPStatusError, CrawlerError, KeyError, ValueError):
        LOG.info("tag id lookup failed or mismatched; falling back to tag search")

    data, _ = client.get_json("tags", params={"search": TAG_NAME, "per_page": 100})
    for item in _validate_wp_array(data, "tag search"):
        tag = _taxonomy_from_item(item)
        if tag.name == TAG_NAME or tag.slug == TAG_NAME:
            return tag
    raise CrawlerError(f"target tag not found: {TAG_NAME}")


def parse_page_headers(headers: dict[str, Any]) -> tuple[int, int]:
    try:
        total = int(headers["X-WP-Total"])
        pages = int(headers["X-WP-TotalPages"])
    except (KeyError, TypeError, ValueError) as exc:
        raise CrawlerError("missing or invalid WordPress pagination headers") from exc
    if total < 0 or pages < 0:
        raise CrawlerError("WordPress pagination headers must be non-negative")
    return total, pages


def fetch_posts_page(client: Any, category: Taxonomy, tag: Taxonomy, page: int) -> tuple[list[dict[str, Any]], int, int]:
    data, headers = client.get_json(
        "posts",
        params={
            "categories": category.id,
            "tags": tag.id,
            "status": "publish",
            "per_page": 100,
            "page": page,
            "orderby": "date",
            "order": "desc",
            "_embed": 1,
            "_fields": POST_FIELDS,
        },
    )
    rows = _validate_wp_array(data, f"posts page {page}")
    total, total_pages = parse_page_headers(headers)
    return rows, total, total_pages


def _post_matches_filter(post: dict[str, Any], category: Taxonomy, tag: Taxonomy) -> bool:
    try:
        category_ids = {int(value) for value in post.get("categories", [])}
        tag_ids = {int(value) for value in post.get("tags", [])}
    except (TypeError, ValueError):
        return False
    return post.get("status") == "publish" and category.id in category_ids and tag.id in tag_ids


def _collect_posts_once(client: Any, category: Taxonomy, tag: Taxonomy, stats: RunStats) -> tuple[list[dict[str, Any]], int]:
    first_page, first_total, first_total_pages = fetch_posts_page(client, category, tag, 1)
    posts_by_id: dict[int, dict[str, Any]] = {}
    invalid_count = 0
    duplicate_count = 0

    def add_page(rows: list[dict[str, Any]], page: int) -> None:
        nonlocal invalid_count, duplicate_count
        if page < first_total_pages and not rows:
            raise CrawlerError(f"posts page {page} returned empty before the last page")
        for post in rows:
            if not _post_matches_filter(post, category, tag):
                invalid_count += 1
                continue
            try:
                post_id = int(post["id"])
            except (KeyError, TypeError, ValueError):
                invalid_count += 1
                continue
            if post_id in posts_by_id:
                duplicate_count += 1
                continue
            posts_by_id[post_id] = post

    add_page(first_page, 1)
    for page in range(2, first_total_pages + 1):
        rows, total, total_pages = fetch_posts_page(client, category, tag, page)
        if total != first_total or total_pages != first_total_pages:
            raise CountChangedError("WordPress post total changed during pagination")
        add_page(rows, page)

    stats.filtered_out += invalid_count
    stats.duplicate_posts += duplicate_count
    if len(posts_by_id) != first_total:
        raise CrawlerError(f"API reported {first_total} posts, but collected {len(posts_by_id)} unique matching posts")
    posts = sorted(posts_by_id.values(), key=lambda item: (clean_text(item.get("date_gmt")), int(item.get("id", 0))), reverse=True)
    return posts, first_total


def collect_posts(client: Any, category: Taxonomy, tag: Taxonomy, stats: RunStats) -> tuple[list[dict[str, Any]], int]:
    for attempt in range(2):
        before_filtered = stats.filtered_out
        before_duplicates = stats.duplicate_posts
        try:
            return _collect_posts_once(client, category, tag, stats)
        except CountChangedError:
            stats.filtered_out = before_filtered
            stats.duplicate_posts = before_duplicates
            if attempt == 0:
                LOG.warning("WordPress total changed during pagination; restarting once")
                continue
            raise CrawlerError("WordPress total changed again during pagination")
    raise AssertionError("unreachable")


def dry_run(client: Any, category: Taxonomy, tag: Taxonomy) -> None:
    rows, total, total_pages = fetch_posts_page(client, category, tag, 1)
    mismatches = sum(1 for post in rows if not _post_matches_filter(post, category, tag))
    if mismatches:
        raise CrawlerError(f"first page contains {mismatches} posts outside target filters")
    LOG.info(
        "dry-run ok: category=%s(%s) tag=%s(%s) api_total=%d pages=%d first_page_items=%d",
        category.name,
        category.id,
        tag.name,
        tag.id,
        total,
        total_pages,
        len(rows),
    )


def _embedded_terms(post: dict[str, Any]) -> list[dict[str, Any]]:
    embedded = post.get("_embedded") or {}
    groups = embedded.get("wp:term") or []
    terms: list[dict[str, Any]] = []
    if isinstance(groups, list):
        for group in groups:
            if isinstance(group, list):
                terms.extend(item for item in group if isinstance(item, dict))
    return terms


def _taxonomy_values(post: dict[str, Any], field: str, taxonomy_name: str, known: Taxonomy) -> list[dict[str, Any]]:
    ids = []
    for value in post.get(field, []) or []:
        try:
            ids.append(int(value))
        except (TypeError, ValueError):
            continue
    terms_by_id: dict[int, dict[str, Any]] = {}
    for term in _embedded_terms(post):
        if clean_text(term.get("taxonomy")) != taxonomy_name:
            continue
        try:
            term_id = int(term["id"])
        except (KeyError, TypeError, ValueError):
            continue
        terms_by_id[term_id] = term

    values: list[dict[str, Any]] = []
    for term_id in ids:
        term = terms_by_id.get(term_id)
        if term:
            values.append({"id": term_id, "name": html_to_text(term.get("name", "")), "slug": decode_slug(term.get("slug", ""))})
        elif term_id == known.id:
            values.append({"id": known.id, "name": known.name, "slug": known.slug})
        else:
            values.append({"id": term_id, "name": "", "slug": ""})
    return values


def _author(post: dict[str, Any]) -> dict[str, Any]:
    author_id = int(post.get("author") or 0)
    embedded = post.get("_embedded") or {}
    authors = embedded.get("author") or []
    author_name = ""
    if authors and isinstance(authors[0], dict):
        author_id = int(authors[0].get("id") or author_id)
        author_name = html_to_text(authors[0].get("name", ""))
    return {"id": author_id, "name": author_name}


def _featured_image(post: dict[str, Any]) -> dict[str, Any] | None:
    try:
        media_id = int(post.get("featured_media") or 0)
    except (TypeError, ValueError):
        media_id = 0
    if media_id == 0:
        return None

    embedded = post.get("_embedded") or {}
    media = embedded.get("wp:featuredmedia") or []
    if media and isinstance(media[0], dict):
        item = media[0]
        return {
            "id": int(item.get("id") or media_id),
            "url": clean_text(item.get("source_url", "")),
            "mime_type": clean_text(item.get("mime_type", "")),
            "alt_text": html_to_text(item.get("alt_text", "")),
        }
    return {"id": media_id, "url": "", "mime_type": "", "alt_text": ""}


def _soup_from_content(content: Any) -> BeautifulSoup:
    if not isinstance(content, str):
        raise ValueError("content.rendered must be a string")
    return BeautifulSoup(content, "html.parser")


def _all_tags_with_positions(soup: BeautifulSoup) -> tuple[list[Tag], dict[int, int]]:
    tags = [tag for tag in soup.find_all(True)]
    return tags, {id(tag): index for index, tag in enumerate(tags)}


def _heading_entries(soup: BeautifulSoup) -> tuple[list[HeadingEntry], list[Tag], dict[int, int]]:
    tags, positions = _all_tags_with_positions(soup)
    entries: list[HeadingEntry] = []
    for heading in soup.find_all(["h2", "h3", "h4"]):
        text = clean_text(heading.get_text(" ", strip=True))
        if is_common_heading(text):
            continue
        entries.append(
            HeadingEntry(
                level=int(str(heading.name)[1]),
                text=text,
                order=len(entries) + 1,
                tag=heading,
                tag_index=positions.get(id(heading), -1),
            )
        )
    return entries, tags, positions


def extract_heading_structure(soup: BeautifulSoup) -> list[dict[str, Any]]:
    entries, _, _ = _heading_entries(soup)
    return [{"level": item.level, "text": item.text, "order": item.order} for item in entries]


def _normalize_external_url(raw_url: Any) -> tuple[str, str] | None:
    raw = clean_text(raw_url)
    if not raw:
        return None
    absolute = urljoin(BASE_URL, raw)
    parsed = urlparse(absolute)
    scheme = parsed.scheme.lower()
    if scheme not in {"http", "https"}:
        return None
    host = (parsed.hostname or "").lower()
    if not host or host == "gogumafarm.kr" or host.endswith(".gogumafarm.kr"):
        return None
    normalized = urlunparse(parsed._replace(fragment=""))
    return normalized, host


def _sources_from_tags(tags: Iterable[Tag]) -> list[dict[str, Any]]:
    sources: list[dict[str, Any]] = []
    seen: set[str] = set()
    for tag in tags:
        if tag.name == "a":
            raw_url = tag.get("href")
            source_type = "link"
            anchor_text = clean_text(tag.get_text(" ", strip=True))
        elif tag.name == "iframe":
            raw_url = tag.get("src")
            source_type = "embed"
            anchor_text = clean_text(tag.get("title", ""))
        else:
            continue
        normalized = _normalize_external_url(raw_url)
        if normalized is None:
            continue
        url, domain = normalized
        if url in seen:
            continue
        seen.add(url)
        sources.append({"url": url, "domain": domain, "anchor_text": anchor_text, "type": source_type})
    return sources


def extract_external_sources(soup: BeautifulSoup) -> list[dict[str, Any]]:
    return _sources_from_tags(tag for tag in soup.find_all(["a", "iframe"]))


def _section_end_index(entries: list[HeadingEntry], start: int) -> int:
    current = entries[start]
    for item in entries[start + 1 :]:
        if item.level <= current.level:
            return item.tag_index
    return 10**12


def _section_path(entries: list[HeadingEntry], index: int) -> list[str]:
    current = entries[index]
    parents: list[HeadingEntry] = []
    for item in reversed(entries[:index]):
        if item.level < current.level and all(item.level < parent.level for parent in parents):
            parents.append(item)
    return [item.text for item in reversed(parents)] + [current.text]


def _child_heading_texts(entries: list[HeadingEntry], start: int, end_index: int) -> list[str]:
    current = entries[start]
    result: list[str] = []
    for item in entries[start + 1 :]:
        if item.tag_index >= end_index:
            break
        if item.level > current.level:
            result.append(item.text)
    return result


def article_summary(title: str, heading_structure: list[dict[str, Any]]) -> str:
    topics = [
        clean_text(item.get("text", ""))
        for item in heading_structure
        if not is_explanatory_heading(clean_text(item.get("text", "")))
    ][:3]
    if topics:
        summary = f"{title}은 {', '.join(topics)} 등을 중심으로 최신 밈과 트렌드를 정리한 게시물이다."
    else:
        summary = f"{title} 주제를 다루는 최신 밈과 트렌드 게시물이다."
    return trim_text(summary, 200)


def meme_summary(name: str, child_headings: list[str]) -> str:
    useful = [item for item in child_headings if is_explanatory_heading(item)][:3]
    if useful:
        summary = f"{name}은 {', '.join(useful)} 같은 제목 구조에서 별도 설명이 확인된 밈 항목이다."
    else:
        summary = f"{name}은 게시물 제목 구조에서 별도 항목으로 확인된 밈이다."
    return trim_text(summary, 200)


def extract_meme_items(soup: BeautifulSoup, post_id: int) -> ExtractionResult:
    entries, tags, _ = _heading_entries(soup)
    if not entries:
        return ExtractionResult(status="unsupported_structure")

    candidate_indexes = [
        index
        for index, item in enumerate(entries)
        if item.text and not is_common_heading(item.text) and not is_explanatory_heading(item.text)
    ]
    if not candidate_indexes:
        return ExtractionResult(status="no_items")

    seen_names: set[str] = set()
    items: list[dict[str, Any]] = []
    duplicate_names = 0
    for index in candidate_indexes:
        heading = entries[index]
        name_key = _normalize_key(heading.text)
        if not name_key:
            continue
        if name_key in seen_names:
            duplicate_names += 1
            continue
        end_index = _section_end_index(entries, index)
        section_tags = [
            tag
            for tag_index, tag in enumerate(tags)
            if heading.tag_index < tag_index < end_index and tag.name in {"a", "iframe"}
        ]
        section_sources = _sources_from_tags(section_tags)
        child_headings = _child_heading_texts(entries, index, end_index)
        has_explanatory_child = any(is_explanatory_heading(text) for text in child_headings)
        if not has_explanatory_child and not section_sources:
            continue
        seen_names.add(name_key)
        position = len(items) + 1
        items.append(
            {
                "meme_id": f"{post_id}_{position}",
                "name": heading.text,
                "position": position,
                "heading_level": heading.level,
                "section_path": _section_path(entries, index),
                "summary": meme_summary(heading.text, child_headings),
                "source_urls": [source["url"] for source in section_sources],
                "extraction_source": "heading_structure",
                "extraction_status": "success",
            }
        )
    if not items:
        return ExtractionResult(status="unsupported_structure", duplicate_names=duplicate_names)
    return ExtractionResult(status="success", items=items, duplicate_names=duplicate_names)


def _required_base_article(post: dict[str, Any]) -> dict[str, Any] | None:
    try:
        post_id = int(post["id"])
    except (KeyError, TypeError, ValueError):
        return None
    title = html_to_text((post.get("title") or {}).get("rendered", ""))
    url = clean_text(post.get("link", ""))
    status = clean_text(post.get("status", ""))
    published_at = utc_z(post.get("date_gmt", ""))
    if not post_id or not title or not url or status != "publish" or not published_at:
        return None
    return {
        "post_id": post_id,
        "url": url,
        "slug": decode_slug(post.get("slug", "")),
        "title": title,
        "status": status,
        "published_at": published_at,
        "published_local": clean_text(post.get("date", "")),
        "modified_at": utc_z(post.get("modified_gmt", "")),
        "modified_local": clean_text(post.get("modified", "")),
    }


def article_from_post(
    post: dict[str, Any],
    category: Taxonomy,
    tag: Taxonomy,
    collected_at: str,
    *,
    reuse: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    base = _required_base_article(post)
    if base is None:
        return None

    article = {
        **base,
        "author": _author(post),
        "categories": _taxonomy_values(post, "categories", "category", category),
        "tags": _taxonomy_values(post, "tags", "post_tag", tag),
        "excerpt": trim_text(html_to_text((post.get("excerpt") or {}).get("rendered", "")), 500),
        "featured_image": _featured_image(post),
        "heading_structure": [],
        "external_sources": [],
        "summary": "",
        "summary_method": "rule",
        "meme_extraction_status": "parse_error",
        "meme_items": [],
        "fetch_status": "parse_error",
        "collected_at": collected_at,
    }

    if reuse:
        list_fields = {"heading_structure", "external_sources", "meme_items"}
        for key in ("heading_structure", "external_sources", "summary", "summary_method", "meme_extraction_status", "meme_items"):
            article[key] = reuse.get(key, [] if key in list_fields else "")
        article["fetch_status"] = reuse.get("fetch_status", "success")
        return article

    try:
        soup = _soup_from_content((post.get("content") or {}).get("rendered", ""))
        headings = extract_heading_structure(soup)
        sources = extract_external_sources(soup)
        extraction = extract_meme_items(soup, int(article["post_id"]))
        article.update(
            {
                "heading_structure": headings,
                "external_sources": sources,
                "summary": article_summary(article["title"], headings),
                "meme_extraction_status": extraction.status,
                "meme_items": extraction.items,
                "fetch_status": "success",
            }
        )
        if not article["author"]["name"] or (article["featured_image"] is not None and not article["featured_image"]["url"]):
            article["fetch_status"] = "partial"
        article["_duplicate_meme_names"] = extraction.duplicate_names
    except Exception as exc:
        LOG.warning("content parse failed: post_id=%s error=%s", article["post_id"], exc)
        article["meme_extraction_status"] = "parse_error"
        article["fetch_status"] = "parse_error"
    return article


def _sort_articles(articles: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(articles, key=lambda item: (clean_text(item.get("published_at")), int(item.get("post_id", 0))), reverse=True)


def make_document(
    articles: list[dict[str, Any]],
    category: Taxonomy,
    tag: Taxonomy,
    collected_at: str,
    api_total: int,
) -> dict[str, Any]:
    clean_articles: list[dict[str, Any]] = []
    for article in _sort_articles(articles):
        clean_article = {key: value for key, value in article.items() if not key.startswith("_")}
        clean_articles.append(clean_article)
    return {
        "schema_version": SCHEMA_VERSION,
        "source": "gogumafarm",
        "source_url": SOURCE_URL,
        "category": {"id": category.id, "name": category.name, "slug": category.slug},
        "tag": {"id": tag.id, "name": tag.name, "slug": tag.slug},
        "collected_at": collected_at,
        "api_reported_total": api_total,
        "article_count": len(clean_articles),
        "meme_item_count": sum(len(article.get("meme_items", [])) for article in clean_articles),
        "articles": clean_articles,
    }


def _stable_article_id(article: dict[str, Any]) -> str:
    path = urlparse(clean_text(article.get("url", ""))).path.strip("/")
    if path:
        return path.split("/", 1)[0][:80]
    slug = clean_text(article.get("slug", ""))
    if slug:
        return slug[:80]
    return str(article.get("post_id", ""))


def _published_date(article: dict[str, Any]) -> str:
    for key in ("published_local", "published_at"):
        value = clean_text(article.get(key, ""))
        if value:
            return value[:10]
    return ""


def _tag_text(article: dict[str, Any]) -> str:
    values: list[str] = []
    for tag in article.get("tags", []) or []:
        if isinstance(tag, dict):
            name = clean_text(tag.get("name", ""))
            if name:
                values.append(name)
    return "|".join(values)


def _meme_signal_text(title: str, tags: str) -> str:
    haystack = f"{title} {tags}".lower()
    return "|".join(term for term in sorted(MEME_SIGNAL_TERMS) if term.lower() in haystack)


def _article_is_meme_related(title: str, tags: str) -> bool:
    return "밈" in f"{title} {tags}"


def _article_content_hash(article: dict[str, Any]) -> str:
    payload = json.dumps(
        {
            "title": article.get("title", ""),
            "headings": article.get("heading_structure", []),
            "sources": article.get("external_sources", []),
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest() if payload else ""


def _clean_term(value: str) -> str:
    value = clean_text(value)
    value = re.sub(r"^[\d①②③④⑤⑥⑦⑧⑨⑩]+(?:\ufe0f?\u20e3)?\s*[.)\]]?\s*", "", value)
    value = re.sub(r"\s*\[[^\]]+\]\s*$", "", value)
    while value and unicodedata.category(value[0]) in {"Cf", "Mn"}:
        value = value[1:].lstrip()
    while value and unicodedata.category(value[-1]) in {"Cf", "Mn"}:
        value = value[:-1].rstrip()
    return clean_text(value.strip("~!?.·-–—:：|"))


def _remove_emoji(value: str) -> str:
    kept: list[str] = []
    for char in value:
        if unicodedata.category(char) in {"So", "Sk", "Cf", "Mn"}:
            continue
        kept.append(char)
    return clean_text("".join(kept))


def _term_key(value: str) -> str:
    return re.sub(r"[^0-9A-Za-z가-힣]+", "", _clean_term(value)).lower()


def _is_reasonable_term_length(term: str) -> bool:
    compact = re.sub(r"\s+", "", term)
    return 2 <= len(compact) <= 60


def _is_final_meme_term(term: str) -> bool:
    normalized = _term_key(term)
    if not normalized or not _is_reasonable_term_length(term):
        return False
    if normalized in {_term_key(value) for value in EXACT_REJECT_TERMS}:
        return False
    if any(_term_key(value) in normalized for value in GENERIC_TERM_PATTERNS):
        return False
    if is_common_heading(term) or is_explanatory_heading(term):
        return False
    lowered = term.lower()
    return not any(pattern.lower() in lowered for pattern in TERM_REJECT_PATTERNS)


def _term_type(term: str) -> str:
    if any(char in term for char in ("~", "?", "!", "ㅋ")) or len(term) >= 10:
        return "phrase"
    if re.search(r"[A-Za-z]", term):
        return "mixed"
    return "keyword"


def article_csv_rows(document: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for index, article in enumerate(document.get("articles", []), start=1):
        if not isinstance(article, dict):
            continue
        tags = _tag_text(article)
        title = clean_text(article.get("title", ""))
        featured = article.get("featured_image") or {}
        rows.append(
            {
                "source": "gogumafarm",
                "category_name": (document.get("category") or {}).get("name", CATEGORY_NAME),
                "article_id": _stable_article_id(article),
                "url": clean_text(article.get("url", "")),
                "title": title,
                "published_date": _published_date(article),
                "tags": tags,
                "thumbnail_url": clean_text(featured.get("url", "")) if isinstance(featured, dict) else "",
                "is_meme_related": _article_is_meme_related(title, tags),
                "meme_signal_terms": _meme_signal_text(title, tags),
                "heading_count": len(article.get("heading_structure", []) or []),
                "detail_fetch_status": article.get("fetch_status", ""),
                "list_page": ((index - 1) // 100) + 1,
                "list_position": ((index - 1) % 100) + 1,
                "content_hash": _article_content_hash(article),
                "parser_version": PARSER_VERSION,
                "collected_at": article.get("collected_at") or document.get("collected_at", ""),
            }
        )
    return rows


def term_csv_rows(document: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for article in document.get("articles", []):
        if not isinstance(article, dict):
            continue
        article_id = _stable_article_id(article)
        tags = _tag_text(article)
        title = clean_text(article.get("title", ""))
        tag_bonus = 1 if {"밈", "바이럴", "SNS"}.intersection(set(tags.split("|"))) else 0
        title_bonus = 1 if "밈" in title else 0
        seen: set[str] = set()
        position = 0
        for heading in article.get("heading_structure", []) or []:
            if not isinstance(heading, dict):
                continue
            term = _clean_term(clean_text(heading.get("text", "")))
            key = re.sub(r"\s+", "", term).lower()
            if not key or key in seen or not _is_final_meme_term(term):
                continue
            seen.add(key)
            position += 1
            level = heading.get("level", "")
            rows.append(
                {
                    "term_id": f"{article_id}_{position}",
                    "article_id": article_id,
                    "term": term,
                    "term_type": _term_type(term),
                    "source_field": f"h{level}" if level else "",
                    "position": position,
                    "published_date": _published_date(article),
                    "tags": tags,
                    "relevance_score": 1 + tag_bonus + title_bonus,
                    "source_url": clean_text(article.get("url", "")),
                    "collected_at": article.get("collected_at") or document.get("collected_at", ""),
                }
            )
    return rows


def final_meme_term_pairs(rows: Iterable[dict[str, Any]]) -> tuple[list[str], list[str]]:
    terms: list[str] = []
    display_terms: list[str] = []
    seen: set[str] = set()
    for row in rows:
        display_term = _clean_term(str(row.get("term", "")))
        term = _remove_emoji(display_term)
        if not _is_final_meme_term(term):
            continue
        key = re.sub(r"\s+", "", term).lower()
        if key and key not in seen:
            terms.append(term)
            display_terms.append(display_term)
            seen.add(key)
    return terms, display_terms


def final_meme_terms(rows: Iterable[dict[str, Any]]) -> list[str]:
    terms, _display_terms = final_meme_term_pairs(rows)
    return terms


def build_keyword_artifacts(document: dict[str, Any]) -> KeywordArtifacts:
    term_rows = term_csv_rows(document)
    final_terms, display_terms = final_meme_term_pairs(term_rows)
    return KeywordArtifacts(
        term_rows=term_rows,
        final_terms=final_terms,
        display_terms=display_terms,
    )


def atomic_write_csv(path: Path, fields: list[str], rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            values = {field: row.get(field, "") for field in fields}
            for field, value in values.items():
                if isinstance(value, bool):
                    values[field] = str(value).lower()
            writer.writerow(values)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def atomic_write_json(path: Path, document: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(document, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def emit_team_style_outputs(output_dir: Path, document: dict[str, Any], stamp: str) -> tuple[Path, Path, Path]:
    article_path = output_dir / "raw" / f"gogumafarm_articles_{stamp}.csv"
    term_path = output_dir / "processed" / f"gogumafarm_meme_terms_{stamp}.csv"
    final_path = output_dir / "final_processed" / f"gogumafarm_meme_terms_{stamp}.json"
    article_rows = article_csv_rows(document)
    keyword_artifacts = build_keyword_artifacts(document)
    atomic_write_csv(article_path, ARTICLE_CSV_FIELDS, article_rows)
    atomic_write_csv(term_path, TERM_CSV_FIELDS, keyword_artifacts.term_rows)
    atomic_write_json(final_path, keyword_artifacts.final_terms)
    return article_path, term_path, final_path


def emit_landing_outputs(output_dir: Path, document: dict[str, Any], stamp: str) -> tuple[Path, Path, Path]:
    article_path = output_dir / f"gogumafarm_articles_{stamp}.csv"
    term_path = output_dir / f"gogumafarm_meme_terms_{stamp}.csv"
    final_path = output_dir / f"gogumafarm_meme_terms_{stamp}.json"
    article_rows = article_csv_rows(document)
    keyword_artifacts = build_keyword_artifacts(document)
    atomic_write_csv(article_path, ARTICLE_CSV_FIELDS, article_rows)
    atomic_write_csv(term_path, TERM_CSV_FIELDS, keyword_artifacts.term_rows)
    atomic_write_json(final_path, keyword_artifacts.final_terms)
    return article_path, term_path, final_path


def build_curated_meme_card_candidates_document(
    document: dict[str, Any],
    *,
    version: str,
    week: str,
    run_id: str,
) -> dict[str, Any]:
    keyword_artifacts = build_keyword_artifacts(document)
    return {
        "schema_version": "1.0",
        "dataset_name": "sns_trend",
        "version": version,
        "stage": "curated",
        "artifact_name": "meme_card_candidates",
        "source_family": "gogumafarm",
        "curation_status": "rule_filtered",
        "review_status": "pending",
        "collected_week": week,
        "source_landing_run_id": run_id,
        "generated_at": now_utc_z(),
        "source_article_count": document.get("article_count", 0),
        "source_meme_item_count": document.get("meme_item_count", 0),
        "term_count": len(keyword_artifacts.final_terms),
        "terms": keyword_artifacts.final_terms,
        "display_terms": keyword_artifacts.display_terms,
    }


def write_curated_meme_card_candidates(
    *,
    document: dict[str, Any],
    version: str,
    week: str,
    run_id: str,
    root: Path = CURATED_DATA_ROOT,
    fail_if_exists: bool = False,
) -> Path:
    output_path = curated_meme_card_candidates_path(version=version, week=week, root=root)
    if fail_if_exists:
        _ensure_outputs_do_not_exist([output_path])
    payload = build_curated_meme_card_candidates_document(
        document,
        version=version,
        week=week,
        run_id=run_id,
    )
    atomic_write_json(output_path, payload)
    return output_path


def _landing_context(args: argparse.Namespace) -> tuple[str, str] | None:
    week = getattr(args, "week", None)
    run_id = getattr(args, "run_id", None)
    if week is None and run_id is None:
        return None
    if week is None or run_id is None:
        raise CrawlerError("--week and --run-id must be provided together")
    return parse_iso_week(week), parse_run_id(run_id)


def _resolve_output_dir(args: argparse.Namespace, landing: tuple[str, str] | None) -> Path:
    if args.output_dir is not None:
        return Path(args.output_dir)
    if landing is None:
        return Path("data")
    week, run_id = landing
    return landing_run_directory(week=week, run_id=run_id)


def _resolve_stamp(args: argparse.Namespace, fallback_path: Path | None = None) -> str:
    if args.run_date:
        return parse_run_date(args.run_date).strftime("%Y%m%d")
    if fallback_path is not None:
        fallback_stamp = _date_from_output_name(fallback_path)
        if fallback_stamp:
            return fallback_stamp
    return current_run_date().strftime("%Y%m%d")


def _ensure_outputs_do_not_exist(paths: Iterable[Path]) -> None:
    existing = [str(path) for path in paths if path.exists()]
    if existing:
        raise CrawlerError(f"output already exists: {existing[0]}")


def write_landing_summary(
    *,
    output_dir: Path,
    document: dict[str, Any],
    week: str,
    run_id: str,
    started_at: str,
    outputs: dict[str, Path],
    mode: str,
) -> Path:
    summary_path = output_dir / CRAWLER_RUN_SUMMARY_FILENAME
    summary = {
        "schema_version": "1.0",
        "source": "gogumafarm",
        "status": "success",
        "mode": mode,
        "week": week,
        "run_id": run_id,
        "started_at": started_at,
        "ended_at": now_utc_z(),
        "article_count": document.get("article_count", 0),
        "meme_item_count": document.get("meme_item_count", 0),
        "outputs": {name: str(path) for name, path in outputs.items()},
    }
    atomic_write_json(summary_path, summary)
    return summary_path


def write_landing_error(
    *,
    output_dir: Path,
    week: str,
    run_id: str,
    started_at: str,
    exit_code: int,
    error: Exception,
) -> Path:
    error_path = output_dir / CRAWLER_ERROR_FILENAME
    payload = {
        "schema_version": "1.0",
        "source": "gogumafarm",
        "status": "failed",
        "week": week,
        "run_id": run_id,
        "started_at": started_at,
        "ended_at": now_utc_z(),
        "exit_code": exit_code,
        "error_type": type(error).__name__,
        "message": str(error),
    }
    atomic_write_json(error_path, payload)
    return error_path


def clear_landing_error(output_dir: Path) -> None:
    (output_dir / CRAWLER_ERROR_FILENAME).unlink(missing_ok=True)


def load_document(path: Path) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as handle:
            document = json.load(handle)
    except OSError as exc:
        raise CrawlerError(f"cannot read JSON file: {path}") from exc
    except json.JSONDecodeError as exc:
        raise CrawlerError(f"invalid JSON file: {path}") from exc
    if not isinstance(document, dict) or document.get("source") != "gogumafarm":
        raise CrawlerError("JSON file is not a gogumafarm crawler document")
    return document


def _date_from_output_name(path: Path) -> str:
    match = re.search(r"gogumafarm_memes_(\d{8})\.json$", path.name)
    return match.group(1) if match else ""


def choose_resume_file(output_dir: Path, resume: bool, resume_from: Path | None) -> Path | None:
    if resume_from is not None:
        return resume_from
    if not resume:
        return None
    checkpoint = output_dir / CHECKPOINT_NAME
    if checkpoint.exists():
        return checkpoint
    candidates = [path for path in output_dir.glob("gogumafarm_memes_*.json") if _date_from_output_name(path)]
    return max(candidates, key=_date_from_output_name) if candidates else None


def load_resume_articles(path: Path, category: Taxonomy, tag: Taxonomy) -> dict[str, dict[str, Any]]:
    try:
        with path.open("r", encoding="utf-8") as handle:
            document = json.load(handle)
    except OSError as exc:
        raise CrawlerError(f"cannot read resume file: {path}") from exc
    except json.JSONDecodeError as exc:
        raise CrawlerError(f"resume file is not valid JSON: {path}") from exc

    if document.get("schema_version") != SCHEMA_VERSION or document.get("source") != "gogumafarm":
        raise CrawlerError("resume file schema/source does not match")
    category_doc = document.get("category") or {}
    tag_doc = document.get("tag") or {}
    if category_doc.get("name") != category.name and category_doc.get("slug") != category.slug:
        raise CrawlerError("resume file category does not match")
    if tag_doc.get("name") != tag.name:
        raise CrawlerError("resume file tag does not match")
    articles = document.get("articles")
    if not isinstance(articles, list):
        raise CrawlerError("resume file articles must be an array")
    result: dict[str, dict[str, Any]] = {}
    for article in articles:
        if isinstance(article, dict) and article.get("post_id") is not None:
            result[str(article["post_id"])] = article
    return result


def validate_final_document(document: dict[str, Any]) -> None:
    if document["article_count"] != len(document["articles"]):
        raise CrawlerError("article_count mismatch")
    if document["meme_item_count"] != sum(len(article.get("meme_items", [])) for article in document["articles"]):
        raise CrawlerError("meme_item_count mismatch")
    forbidden = {"content", "content_html", "rendered_content", "image_binary", "body", "html"}
    for article in document["articles"]:
        found = forbidden.intersection(article.keys())
        if found:
            raise CrawlerError(f"forbidden persisted article fields: {sorted(found)}")


def crawl(args: argparse.Namespace, client: Any | None = None) -> Path | None:
    owns_client = client is None
    client = client or PoliteSession(args.delay, args.timeout, args.retries)
    started_at = now_utc_z()
    landing = _landing_context(args)
    output_dir = _resolve_output_dir(args, landing)
    stats = RunStats()
    try:
        category = resolve_category(client)
        tag = resolve_tag(client)
        if args.dry_run:
            dry_run(client, category, tag)
            return None

        output_dir.mkdir(parents=True, exist_ok=True)
        collected_at = now_kst()
        posts, api_total = collect_posts(client, category, tag, stats)
        stats.api_total = api_total

        resume_file = choose_resume_file(output_dir, args.resume or args.resume_from is not None, args.resume_from)
        previous_articles = load_resume_articles(resume_file, category, tag) if resume_file else {}
        current_ids = {str(post.get("id")) for post in posts}
        stats.removed_posts = len(set(previous_articles) - current_ids)

        articles: list[dict[str, Any]] = []
        checkpoint = output_dir / CHECKPOINT_NAME
        for index, post in enumerate(posts, start=1):
            post_id = str(post.get("id", ""))
            previous = previous_articles.get(post_id)
            modified_at = utc_z(post.get("modified_gmt", ""))
            reuse = previous if previous and previous.get("modified_at") == modified_at else None
            if reuse:
                stats.reused_posts += 1
            elif previous:
                stats.modified_posts += 1
            else:
                stats.new_posts += 1

            article = article_from_post(post, category, tag, collected_at, reuse=reuse)
            if article is None:
                stats.excluded_missing_required += 1
                continue
            stats.duplicate_meme_names += int(article.pop("_duplicate_meme_names", 0))
            articles.append(article)

            if index % 10 == 0:
                checkpoint_doc = make_document(articles, category, tag, collected_at, api_total)
                atomic_write_json(checkpoint, checkpoint_doc)
                LOG.info("progress: %d/%d posts processed", index, len(posts))

        document = make_document(articles, category, tag, collected_at, api_total)
        validate_final_document(document)
        stamp = _resolve_stamp(args)
        output_path = output_dir / f"gogumafarm_memes_{stamp}.json"
        if args.fail_if_exists:
            landing_output_paths = [
                output_path,
                output_dir / f"gogumafarm_articles_{stamp}.csv",
                output_dir / f"gogumafarm_meme_terms_{stamp}.csv",
                output_dir / f"gogumafarm_meme_terms_{stamp}.json",
                output_dir / CRAWLER_RUN_SUMMARY_FILENAME,
            ]
            if landing is not None and args.emit_curated_meme_card_candidates:
                week, _run_id = landing
                landing_output_paths.append(
                    curated_meme_card_candidates_path(
                        version=args.curated_version,
                        week=week,
                        root=args.curated_root,
                    )
                )
            legacy_output_paths = [
                output_path,
                output_dir / "raw" / f"gogumafarm_articles_{stamp}.csv",
                output_dir / "processed" / f"gogumafarm_meme_terms_{stamp}.csv",
                output_dir / "final_processed" / f"gogumafarm_meme_terms_{stamp}.json",
            ]
            _ensure_outputs_do_not_exist(landing_output_paths if landing else legacy_output_paths)
        atomic_write_json(output_path, document)
        if landing is None:
            article_csv_path, term_csv_path, final_terms_path = emit_team_style_outputs(output_dir, document, stamp)
        else:
            article_csv_path, term_csv_path, final_terms_path = emit_landing_outputs(output_dir, document, stamp)
            week, run_id = landing
            outputs = {
                "raw_json": output_path,
                "article_csv": article_csv_path,
                "term_csv": term_csv_path,
                "term_json": final_terms_path,
            }
            if args.emit_curated_meme_card_candidates:
                curated_path = write_curated_meme_card_candidates(
                    document=document,
                    version=args.curated_version,
                    week=week,
                    run_id=run_id,
                    root=args.curated_root,
                    fail_if_exists=False,
                )
                outputs["curated_meme_card_candidates"] = curated_path
            clear_landing_error(output_dir)
            write_landing_summary(
                output_dir=output_dir,
                document=document,
                week=week,
                run_id=run_id,
                started_at=started_at,
                outputs=outputs,
                mode="crawl",
            )
        checkpoint.unlink(missing_ok=True)

        statuses = [article.get("meme_extraction_status", "") for article in articles]
        unique_sources = {
            source["url"]
            for article in articles
            for source in article.get("external_sources", [])
            if isinstance(source, dict) and source.get("url")
        }
        LOG.info(
            "done: api_total=%d articles=%d success=%d partial=%d parse_error=%d excluded_required=%d",
            api_total,
            len(articles),
            sum(article.get("fetch_status") == "success" for article in articles),
            sum(article.get("fetch_status") == "partial" for article in articles),
            sum(article.get("fetch_status") == "parse_error" for article in articles),
            stats.excluded_missing_required,
        )
        LOG.info(
            "changes: new=%d modified=%d reused=%d removed=%d duplicate_posts=%d duplicate_meme_names=%d filtered_out=%d",
            stats.new_posts,
            stats.modified_posts,
            stats.reused_posts,
            stats.removed_posts,
            stats.duplicate_posts,
            stats.duplicate_meme_names,
            stats.filtered_out,
        )
        LOG.info(
            "meme_items=%d statuses success=%d no_items=%d unsupported_structure=%d parse_error=%d unique_external_sources=%d",
            document["meme_item_count"],
            statuses.count("success"),
            statuses.count("no_items"),
            statuses.count("unsupported_structure"),
            statuses.count("parse_error"),
            len(unique_sources),
        )
        if landing is None:
            LOG.info("team-style outputs: raw=%s processed=%s final=%s", article_csv_path, term_csv_path, final_terms_path)
        else:
            LOG.info(
                "landing outputs: json=%s articles=%s terms=%s final_terms=%s",
                output_path,
                article_csv_path,
                term_csv_path,
                final_terms_path,
            )
        return output_path
    except (CrawlerError, HTTPStatusError, requests.RequestException) as exc:
        if landing is not None:
            week, run_id = landing
            try:
                write_landing_error(
                    output_dir=output_dir,
                    week=week,
                    run_id=run_id,
                    started_at=started_at,
                    exit_code=1,
                    error=exc,
                )
            except OSError as artifact_error:
                LOG.error("failed to write landing error artifact: %s", artifact_error)
        raise
    except KeyboardInterrupt:
        LOG.warning("interrupted; preserving checkpoint if one was written")
        raise
    finally:
        if owns_client:
            client.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="고구마팜 공개 WordPress API 기반 밈 게시물 메타데이터 수집기")
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--date", dest="run_date", help="output date in YYYY-MM-DD format")
    parser.add_argument("--week", help="landing partition in Asia/Seoul ISO week format (YYYY-Www)")
    parser.add_argument("--run-id", help="Airflow or local run identifier used to isolate landing artifacts")
    parser.add_argument("--delay", type=float, default=1.0, help="request interval in seconds; minimum 1.0")
    parser.add_argument("--timeout", type=float, default=15.0)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--resume-from", type=Path)
    parser.add_argument("--emit-from-json", type=Path, help="existing gogumafarm_memes_YYYYMMDD.json에서 CSV/term JSON만 생성")
    parser.add_argument(
        "--emit-curated-meme-card-candidates",
        dest="emit_curated_meme_card_candidates",
        action="store_true",
        help="also write rule-filtered curated meme_card_candidates JSON for landing runs",
    )
    parser.add_argument("--curated-version", default=DEFAULT_CURATED_VERSION, help="curated dataset version, for example v3")
    parser.add_argument("--curated-root", type=Path, default=CURATED_DATA_ROOT)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--fail-if-exists", action="store_true", help="do not replace an existing output file")
    parser.add_argument("--log-level", choices=("DEBUG", "INFO", "WARNING", "ERROR"), default="INFO")
    return parser


def validate_args(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    if args.delay < 1.0:
        parser.error("--delay must be at least 1.0")
    if args.timeout <= 0:
        parser.error("--timeout must be greater than 0")
    if args.retries < 0:
        parser.error("--retries must be at least 0")
    if args.resume_from is not None and not args.resume_from.exists():
        parser.error("--resume-from file does not exist")
    if args.emit_from_json is not None and not args.emit_from_json.exists():
        parser.error("--emit-from-json file does not exist")
    try:
        landing = _landing_context(args)
        args.curated_version = parse_dataset_version(args.curated_version)
        if args.emit_curated_meme_card_candidates and landing is None:
            parser.error("--emit-curated-meme-card-candidates requires --week and --run-id")
        if args.run_date:
            parse_run_date(args.run_date)
    except CrawlerError as exc:
        parser.error(str(exc))


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    validate_args(parser, args)
    logging.basicConfig(level=getattr(logging, args.log_level), format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    started_at = now_utc_z()
    try:
        if args.emit_from_json is not None:
            document = load_document(args.emit_from_json)
            landing = _landing_context(args)
            output_dir = _resolve_output_dir(args, landing)
            output_dir.mkdir(parents=True, exist_ok=True)
            stamp = _resolve_stamp(args, fallback_path=args.emit_from_json)
            if landing is None:
                article_path, term_path, final_path = emit_team_style_outputs(output_dir, document, stamp)
                LOG.info("team-style outputs: raw=%s processed=%s final=%s", article_path, term_path, final_path)
            else:
                article_path, term_path, final_path = emit_landing_outputs(output_dir, document, stamp)
                week, run_id = landing
                outputs = {
                    "source_json": args.emit_from_json,
                    "article_csv": article_path,
                    "term_csv": term_path,
                    "term_json": final_path,
                }
                if args.emit_curated_meme_card_candidates:
                    curated_path = write_curated_meme_card_candidates(
                        document=document,
                        version=args.curated_version,
                        week=week,
                        run_id=run_id,
                        root=args.curated_root,
                        fail_if_exists=args.fail_if_exists,
                    )
                    outputs["curated_meme_card_candidates"] = curated_path
                clear_landing_error(output_dir)
                write_landing_summary(
                    output_dir=output_dir,
                    document=document,
                    week=week,
                    run_id=run_id,
                    started_at=started_at,
                    outputs=outputs,
                    mode="emit_from_json",
                )
                LOG.info("landing outputs: articles=%s terms=%s final_terms=%s", article_path, term_path, final_path)
            return 0
        crawl(args)
    except CrawlerError as exc:
        LOG.error("crawl failed: %s", exc)
        return 1
    except HTTPStatusError as exc:
        LOG.error("HTTP request failed: %s", exc)
        return 1
    except requests.RequestException as exc:
        LOG.error("network request failed: %s", exc)
        return 1
    except KeyboardInterrupt:
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
