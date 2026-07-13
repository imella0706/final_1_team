from __future__ import annotations

from dataclasses import dataclass
import json
import logging
from pathlib import Path
import re
from typing import Any, Iterable

import httplib2
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from .config import CollectionOptions, ConfigurationError
from .csv_io import DataFileError, atomic_write_csv, read_csv_rows


RAW_SCHEMA_VERSION = 2
VIDEO_CSV_FIELDS = [
    "video_id",
    "title",
    "channel_title",
    "category_id",
    "published_at",
    "view_count",
    "like_count",
    "comment_count",
    "tags",
    "url",
    "schema_version",
    "region_code",
    "collected_at",
    "tags_json",
]
LEGACY_VIDEO_FIELDS = VIDEO_CSV_FIELDS[:10]


class CollectionError(RuntimeError):
    """Raised when YouTube data cannot be collected safely."""


def _nonnegative_int(value: Any) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return 0
    return max(parsed, 0)


@dataclass(frozen=True)
class VideoRecord:
    video_id: str
    title: str
    channel_title: str
    category_id: str
    published_at: str
    view_count: int
    like_count: int
    comment_count: int
    tags: tuple[str, ...]
    url: str

    @classmethod
    def from_api_item(cls, item: dict[str, Any]) -> "VideoRecord | None":
        video_id = str(item.get("id") or "").strip()
        if not video_id:
            return None
        snippet = item.get("snippet") if isinstance(item.get("snippet"), dict) else {}
        statistics = (
            item.get("statistics") if isinstance(item.get("statistics"), dict) else {}
        )
        raw_tags = snippet.get("tags")
        tags = (
            tuple(str(tag).strip() for tag in raw_tags if str(tag).strip())
            if isinstance(raw_tags, list)
            else ()
        )
        return cls(
            video_id=video_id,
            title=str(snippet.get("title") or ""),
            channel_title=str(snippet.get("channelTitle") or ""),
            category_id=str(snippet.get("categoryId") or ""),
            published_at=str(snippet.get("publishedAt") or ""),
            view_count=_nonnegative_int(statistics.get("viewCount")),
            like_count=_nonnegative_int(statistics.get("likeCount")),
            comment_count=_nonnegative_int(statistics.get("commentCount")),
            tags=tags,
            url=f"https://www.youtube.com/watch?v={video_id}",
        )

    @classmethod
    def from_csv_row(cls, row: dict[str, str]) -> "VideoRecord":
        video_id = str(row.get("video_id") or "").strip()
        if not video_id:
            raise DataFileError("video_id must not be blank")
        tags_json = str(row.get("tags_json") or "").strip()
        if tags_json:
            try:
                parsed = json.loads(tags_json)
            except json.JSONDecodeError as exc:
                raise DataFileError(f"invalid tags_json for video {video_id}") from exc
            if not isinstance(parsed, list) or not all(
                isinstance(tag, str) for tag in parsed
            ):
                raise DataFileError(f"tags_json must be a string array for video {video_id}")
            tags = tuple(tag.strip() for tag in parsed if tag.strip())
        else:
            tags = tuple(
                tag.strip()
                for tag in str(row.get("tags") or "").split(",")
                if tag.strip()
            )
        return cls(
            video_id=video_id,
            title=str(row.get("title") or ""),
            channel_title=str(row.get("channel_title") or ""),
            category_id=str(row.get("category_id") or ""),
            published_at=str(row.get("published_at") or ""),
            view_count=_nonnegative_int(row.get("view_count")),
            like_count=_nonnegative_int(row.get("like_count")),
            comment_count=_nonnegative_int(row.get("comment_count")),
            tags=tags,
            url=str(row.get("url") or f"https://www.youtube.com/watch?v={video_id}"),
        )

    def to_csv_row(self, *, region_code: str, collected_at: str) -> dict[str, Any]:
        return {
            "video_id": self.video_id,
            "title": self.title,
            "channel_title": self.channel_title,
            "category_id": self.category_id,
            "published_at": self.published_at,
            "view_count": self.view_count,
            "like_count": self.like_count,
            "comment_count": self.comment_count,
            "tags": ",".join(self.tags),
            "url": self.url,
            "schema_version": RAW_SCHEMA_VERSION,
            "region_code": region_code,
            "collected_at": collected_at,
            "tags_json": json.dumps(self.tags, ensure_ascii=False),
        }


@dataclass(frozen=True)
class VideoSnapshot:
    videos: tuple[VideoRecord, ...]
    region_code: str = ""
    collected_at: str = ""
    schema_version: int = 1


def build_youtube_service(api_key: str, *, timeout: float) -> Any:
    if not api_key.strip():
        raise ConfigurationError("YOUTUBE_API_KEY must not be blank")
    for logger_name in ("googleapiclient", "httplib2", "google_auth_httplib2"):
        logging.getLogger(logger_name).setLevel(logging.WARNING)
    http = httplib2.Http(timeout=timeout)
    return build(
        "youtube",
        "v3",
        developerKey=api_key,
        http=http,
        cache_discovery=False,
    )


def _execute(request: Any, retries: int) -> dict[str, Any]:
    try:
        response = request.execute(num_retries=retries)
    except HttpError as exc:
        status = getattr(exc.resp, "status", "unknown")
        raise CollectionError(f"YouTube API request failed with HTTP {status}") from exc
    except (TimeoutError, OSError, httplib2.HttpLib2Error) as exc:
        raise CollectionError("YouTube API request failed due to a network error") from exc
    if not isinstance(response, dict):
        raise CollectionError("YouTube API returned an invalid response")
    return response


def fetch_trending_videos(
    service: Any,
    options: CollectionOptions,
) -> list[VideoRecord]:
    records: list[VideoRecord] = []
    seen_video_ids: set[str] = set()
    seen_page_tokens: set[str] = set()
    page_token: str | None = None

    while len(records) < options.total_videos:
        records_before_page = len(records)
        page_size = min(options.page_size, options.total_videos - len(records))
        request = service.videos().list(
            part="snippet,statistics",
            chart="mostPopular",
            regionCode=options.region_code,
            maxResults=page_size,
            pageToken=page_token,
        )
        response = _execute(request, options.retries)
        items = response.get("items", [])
        if not isinstance(items, list):
            raise CollectionError("YouTube API response field 'items' must be an array")
        for item in items:
            if not isinstance(item, dict):
                continue
            record = VideoRecord.from_api_item(item)
            if record is None or record.video_id in seen_video_ids:
                continue
            seen_video_ids.add(record.video_id)
            records.append(record)
            if len(records) >= options.total_videos:
                break

        if len(records) >= options.total_videos:
            break

        next_page_token = str(response.get("nextPageToken") or "").strip()
        if not next_page_token:
            break
        if len(records) == records_before_page:
            raise CollectionError("YouTube API page added no new videos")
        if next_page_token in seen_page_tokens:
            raise CollectionError("YouTube API repeated a page token")
        seen_page_tokens.add(next_page_token)
        page_token = next_page_token

    if not records:
        raise CollectionError("YouTube API returned no trending videos")
    return records


def write_video_csv(
    path: Path,
    videos: Iterable[VideoRecord],
    *,
    region_code: str,
    collected_at: str,
    overwrite: bool = True,
) -> None:
    rows = [
        video.to_csv_row(region_code=region_code, collected_at=collected_at)
        for video in videos
    ]
    if not rows:
        raise DataFileError("refusing to write an empty video snapshot")
    atomic_write_csv(path, VIDEO_CSV_FIELDS, rows, overwrite=overwrite)


def read_video_csv(path: Path) -> VideoSnapshot:
    fields, rows = read_csv_rows(path, required_fields=("video_id", "title", "tags"))
    if not rows:
        raise DataFileError(f"video snapshot is empty: {path}")
    v2_fields = {"schema_version", "region_code", "collected_at", "tags_json"}
    present_v2_fields = v2_fields.intersection(fields)
    if present_v2_fields and present_v2_fields != v2_fields:
        missing = ", ".join(sorted(v2_fields.difference(fields)))
        raise DataFileError(f"incomplete v2 video schema in {path}: {missing}")

    if present_v2_fields:
        schema_values = {str(row.get("schema_version") or "").strip() for row in rows}
        region_values = {
            str(row.get("region_code") or "").strip().upper() for row in rows
        }
        collected_values = {
            str(row.get("collected_at") or "").strip() for row in rows
        }
        if schema_values != {str(RAW_SCHEMA_VERSION)}:
            raise DataFileError(f"unsupported or mixed schema_version in {path}")
        if len(region_values) != 1 or not re.fullmatch(
            r"[A-Z]{2}", next(iter(region_values))
        ):
            raise DataFileError(f"mixed or invalid region_code in {path}")
        if len(collected_values) != 1 or not next(iter(collected_values)):
            raise DataFileError(f"mixed or blank collected_at in {path}")
        if any(not str(row.get("tags_json") or "").strip() for row in rows):
            raise DataFileError(f"tags_json must be present on every v2 row in {path}")
        schema_version = RAW_SCHEMA_VERSION
        region = next(iter(region_values))
        collected_at = next(iter(collected_values))
    else:
        schema_version = 1
        region = ""
        collected_at = ""

    videos = tuple(VideoRecord.from_csv_row(row) for row in rows)
    return VideoSnapshot(
        videos=videos,
        region_code=region,
        collected_at=collected_at,
        schema_version=schema_version,
    )
