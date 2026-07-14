from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import logging
import os
from pathlib import Path
import re
import sys
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dotenv import load_dotenv


YOUTUBE_DIR = Path(__file__).resolve().parent.parent
GATHER_DATA_DIR = YOUTUBE_DIR.parent
ENV_FILE = GATHER_DATA_DIR / ".env"
RAW_DATA_DIR = YOUTUBE_DIR / "data" / "raw"
HISTORY_V2_DIR = YOUTUBE_DIR / "data" / "history"
REPORT_DIR = YOUTUBE_DIR / "reports"

DEFAULT_REGION_CODE = "KR"
DEFAULT_TOTAL_VIDEOS = 100
DEFAULT_PAGE_SIZE = 50
DEFAULT_TIMEOUT = 15.0
DEFAULT_RETRIES = 3
DEFAULT_TOP_N = 20
DEFAULT_MIN_SUPPORT = 2


class ConfigurationError(ValueError):
    """Raised when runtime configuration is invalid."""


def load_environment(env_file: Path = ENV_FILE) -> None:
    load_dotenv(env_file, override=False)


def configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level),
        format="%(levelname)s %(message)s",
    )
    # Google discovery DEBUG records contain the full URL, including the API key.
    for logger_name in ("googleapiclient", "httplib2", "google_auth_httplib2"):
        logging.getLogger(logger_name).setLevel(logging.WARNING)


def configure_console() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors="backslashreplace")


def env_text(name: str, default: str) -> str:
    value = os.getenv(name)
    return value.strip() if value and value.strip() else default


def env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigurationError(f"{name} must be an integer") from exc


def env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise ConfigurationError(f"{name} must be a number") from exc


def require_api_key() -> str:
    api_key = os.getenv("YOUTUBE_API_KEY", "").strip()
    if not api_key:
        raise ConfigurationError(
            "YOUTUBE_API_KEY is missing. Set it in gather_data/.env."
        )
    return api_key


def parse_run_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ConfigurationError("date must use YYYY-MM-DD format") from exc


def current_run_date() -> date:
    timezone_name = env_text("YOUTUBE_TIMEZONE", "Asia/Seoul")
    try:
        timezone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise ConfigurationError(f"unknown YOUTUBE_TIMEZONE: {timezone_name}") from exc
    from datetime import datetime

    return datetime.now(timezone).date()


@dataclass(frozen=True)
class CollectionOptions:
    region_code: str = DEFAULT_REGION_CODE
    total_videos: int = DEFAULT_TOTAL_VIDEOS
    page_size: int = DEFAULT_PAGE_SIZE
    timeout: float = DEFAULT_TIMEOUT
    retries: int = DEFAULT_RETRIES

    def __post_init__(self) -> None:
        region = self.region_code.strip().upper()
        object.__setattr__(self, "region_code", region)
        if not re.fullmatch(r"[A-Z]{2}", region):
            raise ConfigurationError("region code must be two ASCII letters")
        if not 1 <= self.total_videos <= 500:
            raise ConfigurationError("total videos must be between 1 and 500")
        if not 1 <= self.page_size <= 50:
            raise ConfigurationError("page size must be between 1 and 50")
        if not 0 < self.timeout <= 300:
            raise ConfigurationError("timeout must be greater than 0 and at most 300")
        if not 0 <= self.retries <= 10:
            raise ConfigurationError("retries must be between 0 and 10")


def collection_options_from_env(**overrides: object) -> CollectionOptions:
    values: dict[str, object] = {
        "region_code": overrides.get("region_code")
        if overrides.get("region_code") is not None
        else env_text("YOUTUBE_REGION_CODE", DEFAULT_REGION_CODE),
        "total_videos": overrides.get("total_videos")
        if overrides.get("total_videos") is not None
        else env_int("YOUTUBE_TOTAL_VIDEOS", DEFAULT_TOTAL_VIDEOS),
        "page_size": overrides.get("page_size")
        if overrides.get("page_size") is not None
        else env_int("YOUTUBE_PAGE_SIZE", DEFAULT_PAGE_SIZE),
        "timeout": overrides.get("timeout")
        if overrides.get("timeout") is not None
        else env_float("YOUTUBE_API_TIMEOUT", DEFAULT_TIMEOUT),
        "retries": overrides.get("retries")
        if overrides.get("retries") is not None
        else env_int("YOUTUBE_API_RETRIES", DEFAULT_RETRIES),
    }
    return CollectionOptions(**values)
