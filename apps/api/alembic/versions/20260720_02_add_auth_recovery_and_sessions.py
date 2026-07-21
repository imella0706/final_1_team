"""Add email recovery tokens and revocable device sessions.

Revision ID: 20260720_02
Revises: 20260720_01
Create Date: 2026-07-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260720_02"
down_revision: str | None = "20260720_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # [Design Intent] Existing internal-alpha accounts remain verified during the
    # rollout; only accounts created under the new public policy start pending.
    op.add_column(
        "users",
        sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute("UPDATE users SET email_verified_at = now() WHERE status = 'active'")
    op.drop_constraint(op.f("ck_users_valid_status"), "users", type_="check")
    op.create_check_constraint(
        op.f("ck_users_valid_status"),
        "users",
        "status IN ('pending_verification', 'active', 'disabled', 'deleted')",
    )

    op.create_table(
        "auth_sessions",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("device_name", sa.String(length=80), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_auth_sessions_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_auth_sessions")),
    )
    op.create_index("ix_auth_sessions_user_id", "auth_sessions", ["user_id"])

    op.add_column(
        "refresh_tokens",
        sa.Column("session_id", sa.Uuid(), nullable=True),
    )
    op.create_foreign_key(
        op.f("fk_refresh_tokens_session_id_auth_sessions"),
        "refresh_tokens",
        "auth_sessions",
        ["session_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index("ix_refresh_tokens_session_id", "refresh_tokens", ["session_id"])
    # Legacy refresh tokens have no session root and must not survive this rollout.
    op.execute("UPDATE refresh_tokens SET revoked_at = now() WHERE revoked_at IS NULL")

    op.create_table(
        "auth_action_tokens",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("purpose", sa.String(length=32), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("invalidated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "purpose IN ('verify_email', 'reset_password')",
            name=op.f("ck_auth_action_tokens_valid_purpose"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_auth_action_tokens_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_auth_action_tokens")),
        sa.UniqueConstraint(
            "token_hash",
            name=op.f("uq_auth_action_tokens_token_hash"),
        ),
    )
    op.create_index(
        "ix_auth_action_tokens_user_purpose",
        "auth_action_tokens",
        ["user_id", "purpose"],
    )
    op.create_index(
        "ix_auth_action_tokens_expires_at",
        "auth_action_tokens",
        ["expires_at"],
    )

    op.create_table(
        "auth_outbox_events",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("action_token_id", sa.Uuid(), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.String(length=120), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "event_type IN ('auth.verify_email', 'auth.reset_password')",
            name=op.f("ck_auth_outbox_events_valid_event_type"),
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'processing', 'completed', 'dead')",
            name=op.f("ck_auth_outbox_events_valid_status"),
        ),
        sa.ForeignKeyConstraint(
            ["action_token_id"],
            ["auth_action_tokens.id"],
            name=op.f("fk_auth_outbox_events_action_token_id_auth_action_tokens"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_auth_outbox_events_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_auth_outbox_events")),
    )
    op.create_index(
        "ix_auth_outbox_events_status_next_attempt",
        "auth_outbox_events",
        ["status", "next_attempt_at"],
    )

    op.create_table(
        "auth_rate_limit_buckets",
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("scope", sa.String(length=48), nullable=False),
        sa.Column("window_started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("count", sa.BigInteger(), nullable=False),
        sa.PrimaryKeyConstraint("key", name=op.f("pk_auth_rate_limit_buckets")),
    )
    op.create_index(
        "ix_auth_rate_limit_buckets_expires_at",
        "auth_rate_limit_buckets",
        ["expires_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_auth_rate_limit_buckets_expires_at",
        table_name="auth_rate_limit_buckets",
    )
    op.drop_table("auth_rate_limit_buckets")
    op.drop_index(
        "ix_auth_outbox_events_status_next_attempt",
        table_name="auth_outbox_events",
    )
    op.drop_table("auth_outbox_events")
    op.drop_index("ix_auth_action_tokens_expires_at", table_name="auth_action_tokens")
    op.drop_index("ix_auth_action_tokens_user_purpose", table_name="auth_action_tokens")
    op.drop_table("auth_action_tokens")
    op.drop_index("ix_refresh_tokens_session_id", table_name="refresh_tokens")
    op.drop_constraint(
        op.f("fk_refresh_tokens_session_id_auth_sessions"),
        "refresh_tokens",
        type_="foreignkey",
    )
    op.drop_column("refresh_tokens", "session_id")
    op.drop_index("ix_auth_sessions_user_id", table_name="auth_sessions")
    op.drop_table("auth_sessions")
    op.drop_constraint(op.f("ck_users_valid_status"), "users", type_="check")
    op.execute("UPDATE users SET status = 'disabled' WHERE status = 'pending_verification'")
    op.create_check_constraint(
        op.f("ck_users_valid_status"),
        "users",
        "status IN ('active', 'disabled', 'deleted')",
    )
    op.drop_column("users", "email_verified_at")
