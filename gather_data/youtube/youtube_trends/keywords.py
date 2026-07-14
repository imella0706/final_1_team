from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date
from hashlib import sha256
from importlib.metadata import PackageNotFoundError, version
import json
import re
from typing import TYPE_CHECKING, Iterable, Protocol
import unicodedata

if TYPE_CHECKING:
    from .collector import VideoRecord


KEYWORD_SCHEMA_VERSION = 2
NORMALIZER_VERSION = "nfkc-casefold-v1"
ALIAS_VERSION = "none"
SNAPSHOT_FIELDS = [
    "schema_version",
    "snapshot_id",
    "date",
    "region",
    "canonical_keyword",
    "display_keyword",
    "video_count",
    "title_video_count",
    "tag_video_count",
    "occurrence_count",
    "channel_count",
    "sample_size",
    "tagged_video_count",
    "prevalence",
    "tokenizer_version",
    "normalizer_version",
    "alias_version",
    "stopword_version",
    "analysis_signature",
    "provenance",
]

DEFAULT_STOPWORDS = {
    "영상",
    "이",
    "가",
    "은",
    "는",
    "을",
    "를",
    "에",
    "의",
    "와",
    "과",
    "도",
    "으로",
    "with",
    "the",
    "and",
    "in",
    "on",
    "of",
    "to",
    "for",
    "from",
    "at",
    "by",
    "is",
    "are",
    "be",
    "or",
    "as",
    "it",
    "this",
    "that",
    "so",
    "good",
    "official",
    "video",
    "videos",
    "cover",
    "episode",
    "part",
    "full",
    "feat",
    "version",
}

class KeywordAnalysisError(RuntimeError):
    """Raised when a keyword snapshot cannot be produced."""


class Tokenizer(Protocol):
    name: str

    def tokenize(self, text: str) -> list[str]: ...


class RegexTokenizer:
    name = "regex-v2"

    def tokenize(self, text: str) -> list[str]:
        return _unicode_tokens(text)


def _unicode_tokens(text: str) -> list[str]:
    tokens: list[str] = []
    current: list[str] = []
    pending_joiner = ""

    def flush() -> None:
        nonlocal pending_joiner
        if current:
            tokens.append("".join(current))
            current.clear()
        pending_joiner = ""

    for character in text:
        category = unicodedata.category(character)
        if category.startswith(("L", "N")):
            if pending_joiner:
                current.append(pending_joiner)
                pending_joiner = ""
            current.append(character)
        elif category.startswith("M") and current and not pending_joiner:
            current.append(character)
        elif character in "-_" and current and not pending_joiner:
            pending_joiner = character
        elif character in "+#" and current and not pending_joiner:
            current.append(character)
        else:
            flush()
    flush()
    return tokens


class OktTokenizer:
    def __init__(self) -> None:
        try:
            from konlpy.tag import Okt

            self._okt = Okt()
        except Exception as exc:
            raise KeywordAnalysisError(
                "Okt tokenizer is unavailable. Install requirements-okt.txt and Java."
            ) from exc
        try:
            package_version = version("konlpy")
        except PackageNotFoundError:
            package_version = "unknown"
        self.name = f"okt-{package_version}"

    def tokenize(self, text: str) -> list[str]:
        try:
            return [str(token) for token in self._okt.nouns(text)]
        except Exception as exc:
            raise KeywordAnalysisError("Okt tokenizer failed") from exc


def create_tokenizer(name: str) -> Tokenizer:
    normalized = name.strip().lower()
    if normalized == "regex":
        return RegexTokenizer()
    if normalized == "okt":
        return OktTokenizer()
    raise KeywordAnalysisError("tokenizer must be either 'regex' or 'okt'")


def normalize_text(value: object) -> str:
    text = unicodedata.normalize("NFKC", str(value or ""))
    text = "".join(
        " " if unicodedata.category(character).startswith("C") else character
        for character in text
    )
    return re.sub(r"\s+", " ", text).strip()


def canonicalize_keyword(value: object) -> str:
    return normalize_text(value).casefold()


@dataclass(frozen=True)
class ExtractedToken:
    canonical: str
    display: str


def _extract_tokens(
    text: object,
    tokenizer: Tokenizer,
    stopwords: set[str],
) -> list[ExtractedToken]:
    normalized_text = normalize_text(text)
    extracted: list[ExtractedToken] = []
    for raw_token in tokenizer.tokenize(normalized_text):
        display = normalize_text(raw_token)
        canonical = canonicalize_keyword(display)
        if (
            not canonical
            or canonical in stopwords
            or (
                len(canonical) == 1
                and canonical.isascii()
                and not (display.isalpha() and display.isupper())
            )
        ):
            continue
        extracted.append(ExtractedToken(canonical=canonical, display=display))
    return extracted


def extract_keyword_occurrences(
    texts: Iterable[object],
    *,
    tokenizer_name: str = "regex",
    stopwords: Iterable[str] = DEFAULT_STOPWORDS,
) -> list[str]:
    tokenizer = create_tokenizer(tokenizer_name)
    normalized_stopwords = {canonicalize_keyword(word) for word in stopwords}
    return [
        token.canonical
        for text in texts
        for token in _extract_tokens(text, tokenizer, normalized_stopwords)
    ]


def _display_form(forms: Counter[str], canonical: str) -> str:
    if not forms:
        return canonical
    return sorted(forms, key=lambda value: (-forms[value], value.casefold(), value))[0]


def _snapshot_id(videos: Iterable[VideoRecord]) -> str:
    payload = [
        {
            "video_id": video.video_id,
            "title": video.title,
            "channel_title": video.channel_title,
            "tags": list(video.tags),
        }
        for video in sorted(videos, key=lambda item: item.video_id)
    ]
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256(encoded).hexdigest()[:16]


def _stopword_version(stopwords: set[str]) -> str:
    encoded = "\n".join(sorted(stopwords)).encode("utf-8")
    return f"sha256:{sha256(encoded).hexdigest()[:12]}"


def build_keyword_snapshot(
    videos: Iterable[VideoRecord],
    *,
    snapshot_date: date,
    region: str,
    tokenizer_name: str = "regex",
    stopwords: Iterable[str] = DEFAULT_STOPWORDS,
    provenance: str = "live_api",
) -> list[dict[str, object]]:
    unique_videos: dict[str, VideoRecord] = {}
    for video in videos:
        if video.video_id and video.video_id not in unique_videos:
            unique_videos[video.video_id] = video
    if not unique_videos:
        raise KeywordAnalysisError("cannot analyze an empty video snapshot")

    tokenizer = create_tokenizer(tokenizer_name)
    normalized_stopwords = {canonicalize_keyword(word) for word in stopwords}
    stopword_version = _stopword_version(normalized_stopwords)
    analysis_signature = "|".join(
        (
            tokenizer.name,
            NORMALIZER_VERSION,
            ALIAS_VERSION,
            stopword_version,
        )
    )
    video_counts: Counter[str] = Counter()
    title_video_counts: Counter[str] = Counter()
    tag_video_counts: Counter[str] = Counter()
    occurrence_counts: Counter[str] = Counter()
    display_forms: dict[str, Counter[str]] = defaultdict(Counter)
    channels: dict[str, set[str]] = defaultdict(set)
    tagged_video_count = 0

    for video in unique_videos.values():
        title_tokens = _extract_tokens(video.title, tokenizer, normalized_stopwords)
        tag_tokens = [
            token
            for tag in video.tags
            for token in _extract_tokens(tag, tokenizer, normalized_stopwords)
        ]
        if video.tags:
            tagged_video_count += 1

        title_keys = {token.canonical for token in title_tokens}
        tag_keys = {token.canonical for token in tag_tokens}
        all_tokens = title_tokens + tag_tokens
        all_keys = title_keys | tag_keys

        occurrence_counts.update(token.canonical for token in all_tokens)
        title_video_counts.update(title_keys)
        tag_video_counts.update(tag_keys)
        video_counts.update(all_keys)
        for canonical, display in {
            (token.canonical, token.display) for token in all_tokens
        }:
            display_forms[canonical][display] += 1
        for canonical in all_keys:
            if video.channel_title:
                channels[canonical].add(video.channel_title)

    if not video_counts:
        raise KeywordAnalysisError("no keywords remained after tokenization")

    sample_size = len(unique_videos)
    snapshot_id = _snapshot_id(unique_videos.values())
    rows: list[dict[str, object]] = []
    for canonical, count in video_counts.items():
        rows.append(
            {
                "schema_version": KEYWORD_SCHEMA_VERSION,
                "snapshot_id": snapshot_id,
                "date": snapshot_date.isoformat(),
                "region": region.upper(),
                "canonical_keyword": canonical,
                "display_keyword": _display_form(display_forms[canonical], canonical),
                "video_count": count,
                "title_video_count": title_video_counts[canonical],
                "tag_video_count": tag_video_counts[canonical],
                "occurrence_count": occurrence_counts[canonical],
                "channel_count": len(channels[canonical]),
                "sample_size": sample_size,
                "tagged_video_count": tagged_video_count,
                "prevalence": f"{count / sample_size:.8f}",
                "tokenizer_version": tokenizer.name,
                "normalizer_version": NORMALIZER_VERSION,
                "alias_version": ALIAS_VERSION,
                "stopword_version": stopword_version,
                "analysis_signature": analysis_signature,
                "provenance": provenance,
            }
        )
    rows.sort(
        key=lambda row: (
            -int(row["video_count"]),
            str(row["canonical_keyword"]),
        )
    )
    return rows
