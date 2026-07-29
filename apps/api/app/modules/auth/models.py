from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class User(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending_verification', 'active', 'disabled', 'deleted')",
            name="valid_status",
        ),
    )

    # [Design Intent] The normalized email has a database UNIQUE constraint;
    # application-side duplicate checks alone are race-prone.
    email_normalized: Mapped[str] = mapped_column(String(320), nullable=False, unique=True)
    display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(512), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    token_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AuthSession(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "auth_sessions"

    # [Design Intent] A server-side session root gives every login a revocable
    # identity. Access JWTs remain short-lived but a stolen device can be cut off
    # immediately without logging every other device out.
    user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    device_name: Mapped[str] = mapped_column(String(80), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RefreshToken(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "refresh_tokens"

    # [Design Intent] Only a SHA-256 digest is persisted. Possession of a database
    # backup therefore does not directly grant a usable browser refresh token.
    user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    session_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("auth_sessions.id", ondelete="CASCADE"),
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    family_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, default=uuid4)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    replaced_by_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("refresh_tokens.id", ondelete="SET NULL"),
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


Index("ix_refresh_tokens_user_id", RefreshToken.user_id)
Index("ix_refresh_tokens_session_id", RefreshToken.session_id)
Index("ix_refresh_tokens_family_id", RefreshToken.family_id)
Index("ix_refresh_tokens_expires_at", RefreshToken.expires_at)
Index("ix_auth_sessions_user_id", AuthSession.user_id)


class ActionToken(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "auth_action_tokens"
    __table_args__ = (
        CheckConstraint(
            "purpose IN ('verify_email', 'reset_password')",
            name="valid_purpose",
        ),
    )

    # [Design Intent] Only a digest is stored. The token delivered to the user is
    # purpose-bound and one-time, so a database read does not expose usable links.
    user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    purpose: Mapped[str] = mapped_column(String(32), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    invalidated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


Index("ix_auth_action_tokens_user_purpose", ActionToken.user_id, ActionToken.purpose)
Index("ix_auth_action_tokens_expires_at", ActionToken.expires_at)


class AuthOutboxEvent(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "auth_outbox_events"
    __table_args__ = (
        CheckConstraint(
            "event_type IN ('auth.verify_email', 'auth.reset_password')",
            name="valid_event_type",
        ),
        CheckConstraint(
            "status IN ('pending', 'processing', 'completed', 'dead')",
            name="valid_status",
        ),
    )

    # [Design Intent] The durable event references a purpose-bound action token;
    # it never stores a raw verification or password-reset token.
    user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    action_token_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("auth_action_tokens.id", ondelete="CASCADE"),
        nullable=False,
    )
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


Index(
    "ix_auth_outbox_events_status_next_attempt",
    AuthOutboxEvent.status,
    AuthOutboxEvent.next_attempt_at,
)


class AuthRateLimitBucket(Base):
    __tablename__ = "auth_rate_limit_buckets"

    # [Design Intent] The key contains only SHA-256 output; raw IP addresses and
    # normalized emails never become durable rate-limit records.
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    scope: Mapped[str] = mapped_column(String(48), nullable=False)
    window_started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    count: Mapped[int] = mapped_column(BigInteger, nullable=False)


Index("ix_auth_rate_limit_buckets_expires_at", AuthRateLimitBucket.expires_at)
