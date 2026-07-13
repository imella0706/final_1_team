"""Careet public metadata crawler.

Only public list/detail pages are requested.  Article body text is never persisted.
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
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Protocol
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup, Tag


BASE_URL = "https://www.careet.net"
SERIES_ID = "1"
SERIES_NAME = "요즘 뜨는 밈"
LIST_URL = f"{BASE_URL}/Content/Series/{SERIES_ID}"
USER_AGENT = "CareetPublicMetadataCrawler/1.0 (research; no-login; contact: local-user)"
RETRYABLE_STATUS = {429, 500, 502, 503, 504}

ARTICLE_FIELDS = [
    "source", "series_id", "series_name", "article_id", "url", "title",
    "published_date", "trend_status_raw", "trend_status", "thumbnail_url",
    "thumbnail_local_path", "thumbnail_mime_type", "thumbnail_bytes",
    "thumbnail_sha256", "thumbnail_download_status", "author", "author_id",
    "toc_json", "meme_item_count", "is_paywalled", "list_page",
    "list_position", "detail_fetch_status", "collected_at",
]
MEME_FIELDS = [
    "meme_id", "article_id", "meme_name", "parent_section", "position",
    "published_date", "trend_status", "extraction_source", "meme_summary",
    "usage_example", "summary_source", "summary_status",
    "summary_confidence", "source_url", "collected_at",
]
FINAL_REJECT_TERMS = {
    "",
    "목차",
    "사용 예시",
    "브랜드 활용 팁",
    "함께 보면 더 알찬 아티클",
    "이런 아티클도 있어요",
}
COUNTED_BUCKET_PATTERN = re.compile(r"\s+\d+$")
SUSPECT_TERM_FIELDS = ["article_id", "meme_id", "meme_name", "parent_section", "position", "reason"]

LOG = logging.getLogger("careet_crawler")


class CrawlerError(RuntimeError):
    """Fatal crawl or parse failure."""


class HTTPStatusError(RuntimeError):
    def __init__(self, url: str, status_code: int):
        super().__init__(f"HTTP {status_code}: {url}")
        self.url = url
        self.status_code = status_code


def clean_text(value: str | None) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def parse_date(value: str) -> str:
    value = clean_text(value)
    for fmt in ("%Y.%m.%d", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt).date().isoformat()
        except ValueError:
            pass
    raise ValueError(f"지원하지 않는 날짜 형식: {value!r}")


def normalize_status(value: str) -> str:
    compact = re.sub(r"\s+", "", clean_text(value))
    return {
        "유행예감": "emerging",
        "유행중": "current",
        "유행지남": "expired",
    }.get(compact, "unknown")


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


class PoliteSession:
    """A rate-limited session with bounded exponential-backoff retries."""

    def __init__(self, delay: float = 1.5, timeout: float = 15.0, retries: int = 3):
        self.delay = delay
        self.timeout = timeout
        self.retries = retries
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT, "Accept-Language": "ko-KR,ko;q=0.9"})
        self._last_request_at: float | None = None

    def close(self) -> None:
        self.session.close()

    def _wait(self) -> None:
        if self._last_request_at is None:
            return
        remaining = self.delay - (time.monotonic() - self._last_request_at)
        if remaining > 0:
            time.sleep(remaining)

    def get(self, url: str, *, stream: bool = False) -> requests.Response:
        attempts = self.retries + 1
        for attempt in range(attempts):
            self._wait()
            try:
                response = self.session.get(url, timeout=(self.timeout, self.timeout), stream=stream)
                self._last_request_at = time.monotonic()
            except requests.RequestException:
                self._last_request_at = time.monotonic()
                if attempt + 1 >= attempts:
                    raise
                wait = 2 ** attempt
                LOG.warning("네트워크 오류; %.1f초 후 재시도 (%d/%d): %s", wait, attempt + 1, self.retries, url)
                time.sleep(wait)
                continue

            if response.status_code not in RETRYABLE_STATUS:
                if not response.ok:
                    response.close()
                    raise HTTPStatusError(url, response.status_code)
                return response

            response.close()
            if attempt + 1 >= attempts:
                raise HTTPStatusError(url, response.status_code)
            retry_after = response.headers.get("Retry-After", "")
            try:
                wait = max(float(retry_after), float(2 ** attempt))
            except ValueError:
                wait = float(2 ** attempt)
            LOG.warning("HTTP %d; %.1f초 후 재시도 (%d/%d): %s", response.status_code, wait, attempt + 1, self.retries, url)
            time.sleep(wait)
        raise AssertionError("unreachable")


def _soup(html: str | bytes) -> BeautifulSoup:
    return BeautifulSoup(html, "html.parser")


def parse_list_page(html: str | bytes, page: int, base_url: str = BASE_URL) -> tuple[list[dict[str, Any]], int | None]:
    soup = _soup(html)
    pagination = soup.select_one(".pagination[data-pagecount]")
    total_pages: int | None = None
    if pagination:
        raw_count = pagination.get("data-pagecount", "")
        try:
            total_pages = int(str(raw_count))
            if total_pages < 1:
                raise ValueError
        except ValueError:
            LOG.warning("잘못된 data-pagecount: %r", raw_count)

    result: list[dict[str, Any]] = []
    cards = soup.select("section.trend-list div.trend-delivery__item")
    for position, card in enumerate(cards, start=1):
        link: Tag | None = None
        article_id = ""
        for candidate in card.select("a[href]"):
            path = urlparse(str(candidate.get("href", ""))).path
            match = re.fullmatch(r"/(\d+)/?", path)
            if match:
                link, article_id = candidate, match.group(1)
                break
        title_node = card.select_one("strong.title")
        date_node = card.select_one("span.date")
        title = clean_text(title_node.get_text(" ", strip=True) if title_node else "")
        raw_date = clean_text(date_node.get_text(" ", strip=True) if date_node else "")
        if not link or not article_id or not title or not raw_date:
            LOG.warning("필수 값이 없는 목록 카드 건너뜀: page=%d position=%d", page, position)
            continue
        try:
            published_date = parse_date(raw_date)
        except ValueError:
            LOG.warning("날짜를 해석할 수 없는 목록 카드 건너뜀: page=%d position=%d value=%r", page, position, raw_date)
            continue
        status_node = card.select_one("span.cate")
        status_raw = clean_text(status_node.get_text(" ", strip=True) if status_node else "")
        image = card.select_one(".img-wrap img[src]")
        thumbnail_url = urljoin(base_url, str(image.get("src", ""))) if image else ""
        result.append({
            "source": "careet",
            "series_id": SERIES_ID,
            "series_name": SERIES_NAME,
            "article_id": article_id,
            "url": urljoin(base_url, f"/{article_id}"),
            "title": title,
            "published_date": published_date,
            "trend_status_raw": status_raw,
            "trend_status": normalize_status(status_raw),
            "thumbnail_url": thumbnail_url,
            "thumbnail_local_path": "",
            "thumbnail_mime_type": "",
            "thumbnail_bytes": "",
            "thumbnail_sha256": "",
            "thumbnail_download_status": "disabled",
            "author": "",
            "author_id": "",
            "toc_json": "[]",
            "meme_item_count": 0,
            "is_paywalled": False,
            "list_page": page,
            "list_position": position,
            "detail_fetch_status": "list_only",
            "collected_at": now_iso(),
        })
    return result, total_pages


_TOP_PREFIX = re.compile(r"^\s*(?P<marker>\d{1,3}\s*[.)．]|[가-힣]\s*[.)])\s*(?P<name>.*)$")
_CIRCLE_PREFIX = re.compile(r"^\s*(?P<marker>[①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳])\s*(?P<name>.*)$")


def _toc_lines(table: Tag) -> list[str]:
    lines: list[str] = []
    for cell in table.select("th, td"):
        for raw in cell.get_text("\n", strip=True).splitlines():
            value = clean_text(raw)
            if value:
                lines.append(value)
    return lines or [clean_text(v) for v in table.get_text("\n").splitlines() if clean_text(v)]


def extract_toc(article: Tag | BeautifulSoup | None) -> list[dict[str, Any]]:
    if article is None:
        return []
    table = next((item for item in article.select("table") if "목차" in clean_text(item.get_text(" "))), None)
    if table is None:
        return []

    parsed: list[tuple[str, str]] = []
    pending_kind: str | None = None
    for line in _toc_lines(table):
        if line == "목차":
            continue
        line = re.sub(r"^목차\s*", "", line).strip()
        if not line:
            continue
        circle = _CIRCLE_PREFIX.match(line)
        top = _TOP_PREFIX.match(line)
        if circle or top:
            match = circle or top
            assert match is not None
            name = clean_text(match.group("name"))
            kind = "child" if circle else "top"
            if not name:
                pending_kind = kind
                continue
            parsed.append((kind, name))
            pending_kind = None
            continue
        # Some tables put the numeric marker and its text in separate cells.
        if pending_kind:
            parsed.append((pending_kind, line))
            pending_kind = None
        else:
            parsed.append(("top", line))

    items: list[dict[str, Any]] = []
    current_parent: str | None = None
    for kind, name in parsed:
        if not name or name == "목차":
            continue
        parent = current_parent if kind == "child" else None
        if kind == "top":
            current_parent = name
        items.append({"position": len(items) + 1, "name": name, "parent_section": parent})
    return items


def _node_text(node: Tag | None) -> str:
    return clean_text(node.get_text(" ", strip=True) if node else "")


@dataclass
class DetailData:
    values: dict[str, Any]
    toc: list[dict[str, Any]]
    preview_text: str


def _extract_preview(article: Tag | None, first_meme_name: str) -> str:
    """Return ephemeral preview evidence for only the first TOC item."""
    if article is None or not first_meme_name:
        return ""
    headings = article.select("h2, h3")
    if not headings:
        return ""
    normalized_name = re.sub(r"\s+", "", first_meme_name).lower()
    chosen: Tag | None = None
    for heading in headings:
        heading_text = _node_text(heading)
        normalized_heading = re.sub(r"\s+", "", re.sub(r"^\d+\s*[.)]\s*", "", heading_text)).lower()
        if normalized_name in normalized_heading or normalized_heading in normalized_name:
            chosen = heading
            break
    if chosen is None:
        chosen = article.select_one("h3#mid__title")
    if chosen is None:
        return ""

    chunks: list[str] = []
    for sibling in chosen.next_siblings:
        if isinstance(sibling, Tag):
            classes = set(sibling.get("class", []))
            if sibling.name in {"h2", "h3"} or classes.intersection({"careet-secret-cover__wrap", "careet-secret__con"}):
                break
            for secret in sibling.select(".careet-secret-cover__wrap, .careet-secret__con"):
                secret.decompose()
            text = _node_text(sibling)
            if text:
                chunks.append(text)
        if sum(map(len, chunks)) >= 1200:
            break
    return clean_text(" ".join(chunks))[:1200]


def parse_detail_page(html: str | bytes) -> DetailData:
    soup = _soup(html)
    title = _node_text(soup.select_one("h3.content-title"))
    if not title:
        raise ValueError("상세 제목 선택자에서 값을 찾지 못함")
    raw_status = _node_text(soup.select_one(".content-heading .cate-wrap .cate"))
    raw_date = _node_text(soup.select_one(".content-heading p.content-date"))
    published_date = parse_date(raw_date) if raw_date else ""
    series_name = _node_text(soup.select_one(".content-heading .series-name"))
    author = _node_text(soup.select_one(".editor-info__wrap .editor-name"))
    author_link = soup.select_one('.editor-info__wrap a[href^="/Content/Editor/"]')
    author_id = ""
    if author_link:
        match = re.search(r"/Content/Editor/([^/?#]+)", str(author_link.get("href", "")))
        author_id = match.group(1) if match else ""
    image = soup.select_one(".content-heading .con-right .img-wrap img[src]")
    image_url = str(image.get("src", "")) if image else ""
    if not image_url:
        og_image = soup.select_one('meta[property="og:image"][content]')
        image_url = str(og_image.get("content", "")) if og_image else ""
    image_url = urljoin(BASE_URL, image_url) if image_url else ""
    article = soup.select_one("section.content-article article.article")
    toc = extract_toc(article)
    preview = _extract_preview(article, str(toc[0]["name"]) if toc else "")
    values = {
        "title": title,
        "trend_status_raw": raw_status,
        "trend_status": normalize_status(raw_status) if raw_status else "",
        "published_date": published_date,
        "series_name": series_name,
        "thumbnail_url": image_url,
        "author": author,
        "author_id": author_id,
        "is_paywalled": bool(soup.select_one(".careet-secret-cover__wrap, .careet-secret__con")),
    }
    return DetailData(values=values, toc=toc, preview_text=preview)


@dataclass
class SummaryResult:
    summary: str = ""
    usage: str = ""
    source: str = ""
    status: str = "insufficient_source"
    confidence: str = "unknown"


class SummaryGenerator(Protocol):
    def generate(self, meme_name: str, evidence: str) -> SummaryResult: ...


class RuleBasedSummaryGenerator:
    """Deliberately conservative generator that never stores source sentences."""

    def generate(self, meme_name: str, evidence: str) -> SummaryResult:
        evidence = clean_text(evidence)
        # A short fragment is too weak to support even a conservative description.
        if len(evidence) < 40 or len(clean_text(meme_name)) < 2:
            return SummaryResult()
        summary = f"‘{clean_text(meme_name)}’은 공개 미리보기에서 의미와 쓰임이 소개된 밈이다."
        usage = "공개 미리보기에서 설명한 맥락과 같은 상황을 나타낼 때 사용한다."
        return SummaryResult(summary[:200], usage[:120], "public_preview", "generated", "low")


class DisabledSummaryGenerator:
    def generate(self, meme_name: str, evidence: str) -> SummaryResult:
        return SummaryResult(status="disabled", confidence="unknown")


def make_meme_rows(article: dict[str, Any], toc: list[dict[str, Any]], generator: SummaryGenerator, preview: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in toc:
        evidence = preview if int(item["position"]) == 1 else ""
        try:
            generated = generator.generate(str(item["name"]), evidence)
        except Exception:
            LOG.exception("요약 생성 실패: article_id=%s position=%s", article["article_id"], item["position"])
            generated = SummaryResult(status="failed")
        rows.append({
            "meme_id": f'{article["article_id"]}_{item["position"]}',
            "article_id": article["article_id"],
            "meme_name": item["name"],
            "parent_section": item.get("parent_section") or "",
            "position": item["position"],
            "published_date": article["published_date"],
            "trend_status": article["trend_status"],
            "extraction_source": "toc",
            "meme_summary": generated.summary,
            "usage_example": generated.usage,
            "summary_source": generated.source,
            "summary_status": generated.status,
            "summary_confidence": generated.confidence,
            "source_url": article["url"],
            "collected_at": article["collected_at"],
        })
    return rows


def _actual_image_type(data: bytes) -> tuple[str, str] | None:
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg", "jpg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png", "png"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif", "gif"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp", "webp"
    return None


def download_thumbnail(client: PoliteSession, article: dict[str, Any], root: Path, max_bytes: int) -> None:
    url = str(article.get("thumbnail_url", ""))
    if urlparse(url).scheme.lower() != "https":
        article["thumbnail_download_status"] = "skipped"
        LOG.warning("HTTPS가 아닌 썸네일 건너뜀: article_id=%s", article["article_id"])
        return
    part_dir = root / "raw" / "thumbnails"
    part_dir.mkdir(parents=True, exist_ok=True)
    part = part_dir / f'{article["article_id"]}.part'
    response: requests.Response | None = None
    try:
        response = client.get(url, stream=True)
        declared = response.headers.get("Content-Length", "")
        if declared and int(declared) > max_bytes:
            raise ValueError("Content-Length가 제한을 초과함")
        content_type = response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
        allowed = {"image/jpeg", "image/png", "image/webp", "image/gif"}
        if content_type not in allowed:
            raise ValueError(f"허용되지 않은 Content-Type: {content_type!r}")
        digest = hashlib.sha256()
        total = 0
        head = bytearray()
        with part.open("wb") as output:
            for chunk in response.iter_content(64 * 1024):
                if not chunk:
                    continue
                total += len(chunk)
                if total > max_bytes:
                    raise ValueError("이미지 크기 제한을 초과함")
                if len(head) < 16:
                    head.extend(chunk[: 16 - len(head)])
                digest.update(chunk)
                output.write(chunk)
        detected = _actual_image_type(bytes(head))
        if not detected or detected[0] != content_type:
            raise ValueError("응답 MIME과 파일 시그니처가 일치하지 않음")
        mime, extension = detected
        target = part_dir / f'{article["article_id"]}.{extension}'
        sha256 = digest.hexdigest()
        if target.exists() and hashlib.sha256(target.read_bytes()).hexdigest() == sha256:
            part.unlink(missing_ok=True)
        else:
            os.replace(part, target)
        article.update({
            "thumbnail_local_path": target.relative_to(root).as_posix(),
            "thumbnail_mime_type": mime,
            "thumbnail_bytes": total,
            "thumbnail_sha256": sha256,
            "thumbnail_download_status": "success",
        })
    except Exception as exc:
        part.unlink(missing_ok=True)
        article["thumbnail_download_status"] = "failed"
        LOG.warning("썸네일 저장 실패: article_id=%s error=%s", article["article_id"], exc)
    finally:
        if response is not None:
            response.close()


def read_csv_by_key(path: Path, key: str) -> dict[str, dict[str, str]]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return {row[key]: row for row in csv.DictReader(handle) if row.get(key)}


def atomic_write_csv(path: Path, fields: list[str], rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            values: dict[str, Any] = {}
            for field in fields:
                value = row.get(field, "")
                values[field] = str(value).lower() if isinstance(value, bool) else value
            writer.writerow(values)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def _final_term_key(value: str) -> str:
    return re.sub(r"[^0-9A-Za-z가-힣]+", "", clean_text(value)).lower()


def _looks_like_counted_bucket(value: str) -> bool:
    value = clean_text(value)
    return bool(COUNTED_BUCKET_PATTERN.search(value))


def suspect_non_term_rows(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = list(rows)
    parent_keys = {_final_term_key(str(row.get("parent_section", ""))) for row in rows if row.get("parent_section")}
    suspects: list[dict[str, Any]] = []
    for row in rows:
        term = clean_text(str(row.get("meme_name", "")))
        key = _final_term_key(term)
        reasons: list[str] = []
        if key and key in parent_keys:
            reasons.append("used_as_parent_section")
        if _looks_like_counted_bucket(term):
            reasons.append("ends_with_standalone_count")
        if key.isdigit():
            reasons.append("number_only")
        if reasons:
            suspects.append({**row, "reason": "|".join(reasons)})
    return suspects


def final_meme_terms(rows: Iterable[dict[str, Any]]) -> list[str]:
    rows = list(rows)
    terms: list[str] = []
    seen: set[str] = set()
    reject_keys = {_final_term_key(value) for value in FINAL_REJECT_TERMS}
    parent_keys = {_final_term_key(str(row.get("parent_section", ""))) for row in rows if row.get("parent_section")}
    for row in rows:
        term = clean_text(str(row.get("meme_name", "")))
        key = _final_term_key(term)
        if len(key) < 2 or key.isdigit() or key in reject_keys or key in parent_keys or key in seen or _looks_like_counted_bucket(term):
            continue
        terms.append(term)
        seen.add(key)
    return terms


def atomic_write_json(path: Path, values: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(values, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def _date_from_meme_csv(path: Path) -> str:
    match = re.search(r"careet_memes_(\d{8})\.csv$", path.name)
    return match.group(1) if match else ""


def emit_final_terms(output_root: Path, meme_rows: Iterable[dict[str, Any]], stamp: str) -> Path:
    final_path = output_root / "final_processed" / f"careet_meme_terms_{stamp}.json"
    atomic_write_json(final_path, final_meme_terms(meme_rows))
    return final_path


def emit_suspect_terms(output_root: Path, meme_rows: Iterable[dict[str, Any]], stamp: str) -> Path:
    suspect_path = output_root / "final_processed" / f"careet_meme_term_suspects_{stamp}.csv"
    atomic_write_csv(suspect_path, SUSPECT_TERM_FIELDS, suspect_non_term_rows(meme_rows))
    return suspect_path


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _sort_articles(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    def key(row: dict[str, Any]) -> tuple[int, int, int]:
        try:
            ordinal = datetime.strptime(str(row["published_date"]), "%Y-%m-%d").date().toordinal()
        except ValueError:
            ordinal = 0
        return (-ordinal, int(row["list_page"]), int(row["list_position"]))
    return sorted(rows, key=key)


def _warn_changed(article: dict[str, Any], detail: dict[str, Any], field: str) -> None:
    if detail.get(field) and article.get(field) and detail[field] != article[field]:
        LOG.warning("목록/상세 값 불일치; 상세 우선: article_id=%s field=%s", article["article_id"], field)


def _apply_detail(article: dict[str, Any], detail: DetailData) -> None:
    for field in ("title", "published_date", "trend_status_raw", "series_name", "thumbnail_url"):
        _warn_changed(article, detail.values, field)
    for field, value in detail.values.items():
        if value not in (None, ""):
            article[field] = value
    article["toc_json"] = json.dumps(detail.toc, ensure_ascii=False, separators=(",", ":"))
    article["meme_item_count"] = len(detail.toc)
    article["detail_fetch_status"] = "success"
    article["collected_at"] = now_iso()


def crawl(args: argparse.Namespace, client: PoliteSession | None = None) -> tuple[Path, Path, list[dict[str, Any]], list[dict[str, Any]]]:
    owns_client = client is None
    client = client or PoliteSession(args.delay, args.timeout, args.retries)
    output_root = Path(args.output_dir)
    stamp = datetime.now().astimezone().strftime("%Y%m%d")
    article_path = output_root / "raw" / f"careet_articles_{stamp}.csv"
    meme_path = output_root / "processed" / f"careet_memes_{stamp}.csv"
    final_path = output_root / "final_processed" / f"careet_meme_terms_{stamp}.json"
    previous_articles = read_csv_by_key(article_path, "article_id") if args.resume else {}
    previous_memes = read_csv_by_key(meme_path, "meme_id") if args.resume else {}
    generator: SummaryGenerator = DisabledSummaryGenerator() if args.summary_mode == "off" else RuleBasedSummaryGenerator()

    articles_by_id: dict[str, dict[str, Any]] = {}
    meme_rows: list[dict[str, Any]] = []
    try:
        first_response = client.get(LIST_URL)
        first_rows, total_pages = parse_list_page(first_response.content, 1)
        first_response.close()
        if not first_rows or total_pages is None:
            raise CrawlerError("첫 목록 페이지의 카드 또는 페이지 수 선택자 파싱 실패")
        requested_end = args.end_page if args.end_page is not None else total_pages
        if requested_end > total_pages:
            LOG.warning("end-page=%d가 총 페이지=%d보다 커 총 페이지까지만 수집", requested_end, total_pages)
        end_page = min(requested_end, total_pages)
        if args.start_page > end_page:
            raise CrawlerError(f"시작 페이지({args.start_page})가 종료 페이지({end_page})보다 큼")

        page_rows = first_rows if args.start_page == 1 else []
        for page in range(args.start_page, end_page + 1):
            if page != 1:
                response = client.get(f"{LIST_URL}?pageidx={page}")
                page_rows, _ = parse_list_page(response.content, page)
                response.close()
            if not page_rows:
                raise CrawlerError(f"목록 페이지 {page}에서 유효한 카드를 찾지 못함")
            for row in page_rows:
                article_id = str(row["article_id"])
                if article_id in articles_by_id:
                    # Keep first discovery order, refresh changeable list metadata.
                    old = articles_by_id[article_id]
                    for field in ("title", "published_date", "trend_status_raw", "trend_status", "thumbnail_url"):
                        old[field] = row[field]
                    LOG.info("중복 article_id 병합: %s", article_id)
                else:
                    articles_by_id[article_id] = row

        for index, article in enumerate(articles_by_id.values(), start=1):
            article_id = str(article["article_id"])
            prior = previous_articles.get(article_id)
            if args.resume and prior and prior.get("detail_fetch_status") == "success" and not args.list_only:
                refreshed = {**prior}
                for field in ("title", "published_date", "trend_status_raw", "trend_status", "thumbnail_url", "list_page", "list_position"):
                    refreshed[field] = article[field]
                if not args.download_thumbnails:
                    refreshed.update({
                        "thumbnail_local_path": "", "thumbnail_mime_type": "",
                        "thumbnail_bytes": "", "thumbnail_sha256": "",
                        "thumbnail_download_status": "disabled",
                    })
                articles_by_id[article_id] = refreshed
                prior_meme_rows = [row for row in previous_memes.values() if row.get("article_id") == article_id]
                if args.summary_mode == "off":
                    for row in prior_meme_rows:
                        row.update({
                            "meme_summary": "", "usage_example": "", "summary_source": "",
                            "summary_status": "disabled", "summary_confidence": "unknown",
                        })
                meme_rows.extend(prior_meme_rows)
                if args.download_thumbnails:
                    if refreshed.get("thumbnail_url"):
                        download_thumbnail(client, refreshed, output_root, args.max_image_bytes)
                    else:
                        refreshed["thumbnail_download_status"] = "skipped"
                LOG.info("완료된 상세 건너뜀(--resume): article_id=%s", article_id)
                continue
            if args.list_only:
                continue
            try:
                response = client.get(str(article["url"]))
            except (HTTPStatusError, requests.RequestException) as exc:
                article["detail_fetch_status"] = "http_error"
                article["collected_at"] = now_iso()
                LOG.warning("상세 요청 실패: article_id=%s error=%s", article_id, exc)
                continue
            try:
                detail = parse_detail_page(response.content)
                _apply_detail(article, detail)
                meme_rows.extend(make_meme_rows(article, detail.toc, generator, detail.preview_text))
            except Exception as exc:
                article["detail_fetch_status"] = "parse_error"
                article["collected_at"] = now_iso()
                LOG.warning("상세 파싱 실패: article_id=%s error=%s", article_id, exc)
            finally:
                response.close()
            if args.download_thumbnails:
                if article["detail_fetch_status"] == "success" and article.get("thumbnail_url"):
                    download_thumbnail(client, article, output_root, args.max_image_bytes)
                else:
                    article["thumbnail_download_status"] = "skipped"
            if index % 10 == 0:
                atomic_write_csv(article_path, ARTICLE_FIELDS, _sort_articles(articles_by_id.values()))
                atomic_write_csv(meme_path, MEME_FIELDS, meme_rows)
                atomic_write_json(final_path, final_meme_terms(meme_rows))
                emit_suspect_terms(output_root, meme_rows, stamp)
    except KeyboardInterrupt:
        LOG.warning("중단 신호 수신; 현재까지의 결과를 체크포인트로 저장")
        atomic_write_csv(article_path, ARTICLE_FIELDS, _sort_articles(articles_by_id.values()))
        atomic_write_csv(meme_path, MEME_FIELDS, meme_rows)
        atomic_write_json(final_path, final_meme_terms(meme_rows))
        emit_suspect_terms(output_root, meme_rows, stamp)
        raise
    finally:
        if owns_client:
            client.close()

    articles = _sort_articles(articles_by_id.values())
    article_order = {str(article["article_id"]): index for index, article in enumerate(articles)}
    meme_rows.sort(key=lambda row: (article_order.get(str(row["article_id"]), len(article_order)), int(row["position"])))
    atomic_write_csv(article_path, ARTICLE_FIELDS, articles)
    atomic_write_csv(meme_path, MEME_FIELDS, meme_rows)
    emit_final_terms(output_root, meme_rows, stamp)
    emit_suspect_terms(output_root, meme_rows, stamp)
    LOG.info(
        "완료: articles=%d success=%d failed=%d no_toc=%d memes=%d summaries=%d images=%d",
        len(articles),
        sum(row["detail_fetch_status"] == "success" for row in articles),
        sum(row["detail_fetch_status"] in {"http_error", "parse_error"} for row in articles),
        sum(row["detail_fetch_status"] == "success" and int(row["meme_item_count"]) == 0 for row in articles),
        len(meme_rows),
        sum(row["summary_status"] == "generated" for row in meme_rows),
        sum(row["thumbnail_download_status"] == "success" for row in articles),
    )
    return article_path, meme_path, articles, meme_rows


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="캐릿 '요즘 뜨는 밈' 공개 메타데이터 수집기")
    parser.add_argument("--start-page", type=int, default=1)
    parser.add_argument("--end-page", type=int)
    parser.add_argument("--delay", type=float, default=1.5, help="요청 사이 대기(초), 최소 1.0")
    parser.add_argument("--timeout", type=float, default=15.0)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--output-dir", type=Path, default=Path("data"))
    parser.add_argument("--list-only", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--emit-final-from-csv", type=Path, help="existing processed/careet_memes_YYYYMMDD.csv에서 final_processed JSON만 생성")
    parser.add_argument("--audit-final-from-csv", type=Path, help="existing processed/careet_memes_YYYYMMDD.csv에서 제외 의심 후보 CSV만 생성")
    parser.add_argument("--summary-mode", choices=("rule", "off"), default="rule")
    parser.add_argument("--download-thumbnails", action="store_true")
    parser.add_argument("--max-image-bytes", type=int, default=10_485_760)
    parser.add_argument("--log-level", choices=("DEBUG", "INFO", "WARNING", "ERROR"), default="INFO")
    return parser


def validate_args(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    if args.start_page < 1:
        parser.error("--start-page는 1 이상이어야 합니다")
    if args.end_page is not None and args.end_page < 1:
        parser.error("--end-page는 1 이상이어야 합니다")
    if args.delay < 1.0:
        parser.error("--delay는 사이트 부하 방지를 위해 1.0 이상이어야 합니다")
    if args.timeout <= 0:
        parser.error("--timeout은 0보다 커야 합니다")
    if args.retries < 0:
        parser.error("--retries는 0 이상이어야 합니다")
    if args.max_image_bytes <= 0:
        parser.error("--max-image-bytes는 0보다 커야 합니다")

    if args.emit_final_from_csv is not None and not args.emit_final_from_csv.exists():
        parser.error("--emit-final-from-csv file does not exist")
    if args.audit_final_from_csv is not None and not args.audit_final_from_csv.exists():
        parser.error("--audit-final-from-csv file does not exist")


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    validate_args(parser, args)
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    try:
        if args.emit_final_from_csv is not None:
            rows = read_csv_rows(args.emit_final_from_csv)
            stamp = _date_from_meme_csv(args.emit_final_from_csv) or datetime.now().astimezone().strftime("%Y%m%d")
            final_path = emit_final_terms(Path(args.output_dir), rows, stamp)
            LOG.info("final terms output: %s", final_path)
            return 0
        if args.audit_final_from_csv is not None:
            rows = read_csv_rows(args.audit_final_from_csv)
            stamp = _date_from_meme_csv(args.audit_final_from_csv) or datetime.now().astimezone().strftime("%Y%m%d")
            suspect_path = emit_suspect_terms(Path(args.output_dir), rows, stamp)
            LOG.info("suspect terms output: %s", suspect_path)
            return 0
        crawl(args)
    except CrawlerError as exc:
        LOG.error("수집 중단: %s", exc)
        return 1
    except KeyboardInterrupt:
        return 130
    except (requests.RequestException, HTTPStatusError) as exc:
        LOG.error("네트워크 요청 실패: %s", exc)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
