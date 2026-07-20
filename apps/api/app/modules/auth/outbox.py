import asyncio
import logging
import secrets
import smtplib
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage
from typing import Protocol
from urllib.parse import quote
from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.modules.auth.models import ActionToken, AuthOutboxEvent, User
from app.modules.auth.security import AuthSecurity

logger = logging.getLogger("brandmate.auth.outbox")


class AuthEmailSenderPort(Protocol):
    async def send(
        self,
        *,
        event_type: str,
        recipient: str,
        display_name: str,
        action_url: str,
    ) -> None: ...


class SmtpAuthEmailSender:
    def __init__(self, config: Settings) -> None:
        self.config = config

    async def send(
        self,
        *,
        event_type: str,
        recipient: str,
        display_name: str,
        action_url: str,
    ) -> None:
        await asyncio.to_thread(
            self._send_sync,
            event_type=event_type,
            recipient=recipient,
            display_name=display_name,
            action_url=action_url,
        )

    def _send_sync(
        self,
        *,
        event_type: str,
        recipient: str,
        display_name: str,
        action_url: str,
    ) -> None:
        subject, instruction = {
            "auth.verify_email": (
                "[BrandMate] 이메일 주소를 인증해 주세요",
                "아래 링크에서 이메일 인증을 완료해 주세요.",
            ),
            "auth.reset_password": (
                "[BrandMate] 비밀번호를 재설정해 주세요",
                "본인이 요청했다면 아래 링크에서 비밀번호를 재설정해 주세요.",
            ),
        }[event_type]
        message = EmailMessage()
        message["Subject"] = subject
        message["From"] = self.config.auth_smtp_from_email
        message["To"] = recipient
        message.set_content(
            f"{display_name}님,\n\n{instruction}\n\n{action_url}\n\n"
            "직접 요청하지 않았다면 이 메일을 무시해 주세요."
        )

        # [Design Intent] SMTP runs outside the event loop with a hard timeout.
        # Raw action URLs are delivered only to the recipient and never logged.
        with smtplib.SMTP(
            self.config.auth_smtp_host,
            self.config.auth_smtp_port,
            timeout=self.config.auth_email_timeout_seconds,
        ) as client:
            client.ehlo()
            if self.config.auth_smtp_starttls:
                client.starttls()
                client.ehlo()
            if self.config.auth_smtp_username:
                password = (
                    self.config.auth_smtp_password.get_secret_value()
                    if self.config.auth_smtp_password
                    else ""
                )
                client.login(self.config.auth_smtp_username, password)
            client.send_message(message)


class AuthOutboxProcessor:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        security: AuthSecurity,
        sender: AuthEmailSenderPort,
        config: Settings,
    ) -> None:
        self.session_factory = session_factory
        self.security = security
        self.sender = sender
        self.config = config

    async def process_one(self) -> bool:
        event_id = await self._claim_one()
        if event_id is None:
            return False

        delivery = await self._build_delivery(event_id)
        if delivery is None:
            await self._mark_completed(event_id)
            return True

        try:
            await self.sender.send(**delivery)
        except Exception as exc:
            # [Design Intent] Store only the exception class. Provider messages can
            # contain credentials, recipients, or action URLs.
            await self._mark_failed(event_id, type(exc).__name__)
        else:
            await self._mark_completed(event_id)
        return True

    async def run(self) -> None:
        while True:
            try:
                processed = await self.process_one()
                if not processed:
                    await asyncio.sleep(self.config.auth_outbox_poll_seconds)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("auth outbox iteration failed")
                await asyncio.sleep(self.config.auth_outbox_poll_seconds)

    async def _claim_one(self) -> UUID | None:
        now = datetime.now(UTC)
        stale_before = now - timedelta(minutes=5)
        async with self.session_factory() as session, session.begin():
            event = (
                await session.execute(
                    select(AuthOutboxEvent)
                    .where(
                        or_(
                            and_(
                                AuthOutboxEvent.status == "pending",
                                AuthOutboxEvent.next_attempt_at <= now,
                            ),
                            and_(
                                AuthOutboxEvent.status == "processing",
                                AuthOutboxEvent.locked_at < stale_before,
                            ),
                        )
                    )
                    .order_by(AuthOutboxEvent.next_attempt_at, AuthOutboxEvent.created_at)
                    .with_for_update(skip_locked=True)
                    .limit(1)
                )
            ).scalar_one_or_none()
            if event is None:
                return None
            event.status = "processing"
            event.locked_at = now
            event.attempt_count += 1
            return event.id

    async def _build_delivery(self, event_id: UUID) -> dict[str, str] | None:
        async with self.session_factory() as session:
            result = await session.execute(
                select(AuthOutboxEvent, ActionToken, User)
                .join(ActionToken, ActionToken.id == AuthOutboxEvent.action_token_id)
                .join(User, User.id == AuthOutboxEvent.user_id)
                .where(AuthOutboxEvent.id == event_id)
            )
            row = result.one_or_none()
            if row is None:
                return None
            event, action, user = row
            now = datetime.now(UTC)
            expires_at = (
                action.expires_at.replace(tzinfo=UTC)
                if action.expires_at.tzinfo is None
                else action.expires_at.astimezone(UTC)
            )
            if (
                action.used_at is not None
                or action.invalidated_at is not None
                or expires_at <= now
                or user.status in {"disabled", "deleted"}
            ):
                return None

            raw_token = self.security.create_action_token(
                token_id=action.id,
                purpose=action.purpose,
            )
            query_name = "verify_token" if action.purpose == "verify_email" else "reset_token"
            action_url = (
                f"{self.config.auth_public_web_url.rstrip('/')}/"
                f"#{query_name}={quote(raw_token, safe='')}"
            )
            return {
                "event_type": event.event_type,
                "recipient": user.email_normalized,
                "display_name": user.display_name,
                "action_url": action_url,
            }

    async def _mark_completed(self, event_id: UUID) -> None:
        async with self.session_factory() as session, session.begin():
            event = await session.get(AuthOutboxEvent, event_id, with_for_update=True)
            if event is not None:
                event.status = "completed"
                event.processed_at = datetime.now(UTC)
                event.locked_at = None
                event.last_error = None

    async def _mark_failed(self, event_id: UUID, error_name: str) -> None:
        now = datetime.now(UTC)
        async with self.session_factory() as session, session.begin():
            event = await session.get(AuthOutboxEvent, event_id, with_for_update=True)
            if event is None:
                return
            event.last_error = error_name[:120]
            event.locked_at = None
            if event.attempt_count >= self.config.auth_outbox_max_attempts:
                event.status = "dead"
                event.processed_at = now
                return
            jitter_ms = secrets.randbelow(1001)
            backoff_seconds = min(300, 5 * (2 ** (event.attempt_count - 1)))
            event.status = "pending"
            event.next_attempt_at = now + timedelta(
                seconds=backoff_seconds,
                milliseconds=jitter_ms,
            )
