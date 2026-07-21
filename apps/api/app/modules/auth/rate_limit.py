import asyncio
import hashlib
import time
from collections import defaultdict, deque
from datetime import UTC, datetime, timedelta
from typing import Protocol

from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.errors import ApiError
from app.modules.auth.models import AuthRateLimitBucket


class AuthRateLimiterPort(Protocol):
    async def check(self, *, scope: str, identity: str, limit: int, window: int) -> None: ...


class InMemoryAuthRateLimiter:
    _MAX_IDENTITIES = 20_000

    def __init__(self) -> None:
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._lock = asyncio.Lock()

    async def check(self, *, scope: str, identity: str, limit: int, window: int) -> None:
        # [Design Intent] This is an L2 single-instance guard against obvious brute
        # force. Redis must replace it before horizontal API scaling.
        digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()
        key = f"{scope}:{digest}"
        now = time.monotonic()
        cutoff = now - window
        async with self._lock:
            if len(self._events) >= self._MAX_IDENTITIES:
                stale_keys = [
                    event_key
                    for event_key, timestamps in self._events.items()
                    if not timestamps or timestamps[-1] <= cutoff
                ]
                for stale_key in stale_keys:
                    self._events.pop(stale_key, None)
                if len(self._events) >= self._MAX_IDENTITIES and key not in self._events:
                    raise ApiError(
                        503,
                        "AUTH_RATE_LIMIT_UNAVAILABLE",
                        "인증 요청을 잠시 처리할 수 없습니다.",
                        headers={"Retry-After": "60"},
                    )
            events = self._events[key]
            while events and events[0] <= cutoff:
                events.popleft()
            if len(events) >= limit:
                retry_after = max(1, int(events[0] + window - now))
                raise ApiError(
                    429,
                    "AUTH_RATE_LIMITED",
                    "요청이 너무 많습니다. 잠시 후 다시 시도해 주세요.",
                    headers={"Retry-After": str(retry_after)},
                )
            events.append(now)


class PostgresAuthRateLimiter:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def check(self, *, scope: str, identity: str, limit: int, window: int) -> None:
        now = datetime.now(UTC)
        started_epoch = int(now.timestamp()) // window * window
        window_started_at = datetime.fromtimestamp(started_epoch, tz=UTC)
        expires_at = window_started_at + timedelta(seconds=window)
        identity_digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()
        key = hashlib.sha256(
            f"{scope}:{identity_digest}:{started_epoch}".encode("utf-8")
        ).hexdigest()

        # [Design Intent] PostgreSQL UPSERT makes the counter atomic across API
        # workers and instances without adding Redis to the MVP infrastructure.
        statement = (
            insert(AuthRateLimitBucket)
            .values(
                key=key,
                scope=scope,
                window_started_at=window_started_at,
                expires_at=expires_at,
                count=1,
            )
            .on_conflict_do_update(
                index_elements=[AuthRateLimitBucket.key],
                set_={"count": AuthRateLimitBucket.count + 1},
            )
            .returning(AuthRateLimitBucket.count)
        )
        async with self._session_factory() as session:
            count = (await session.execute(statement)).scalar_one()
            # Bound table growth with cheap probabilistic cleanup. Correctness does
            # not depend on cleanup because every key includes its fixed window.
            if int(key[:4], 16) % 100 == 0:
                await session.execute(
                    delete(AuthRateLimitBucket).where(AuthRateLimitBucket.expires_at < now)
                )
            await session.commit()

        if count > limit:
            retry_after = max(1, int((expires_at - now).total_seconds()))
            raise ApiError(
                429,
                "AUTH_RATE_LIMITED",
                "요청이 너무 많습니다. 잠시 후 다시 시도해 주세요.",
                headers={"Retry-After": str(retry_after)},
            )
