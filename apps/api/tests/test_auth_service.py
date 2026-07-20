import asyncio
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from app.core.config import Settings
from app.core.errors import ApiError
from app.modules.auth.models import (
    ActionToken,
    AuthOutboxEvent,
    AuthSession,
    RefreshToken,
    User,
)
from app.modules.auth.repository import DuplicateEmailError
from app.modules.auth.schemas import LoginRequest, SignupRequest
from app.modules.auth.service import AuthService


class FakeAuthRepository:
    # [Design Intent] This fake implements the repository port in memory so the
    # service's business rules are tested without HTTP, PostgreSQL, or SQLAlchemy I/O.
    def __init__(self) -> None:
        self.users: dict[UUID, User] = {}
        self.refresh_tokens: dict[str, RefreshToken] = {}
        self.sessions: dict[UUID, AuthSession] = {}
        self.action_tokens: dict[str, ActionToken] = {}
        self.outbox_events: list[AuthOutboxEvent] = []
        self.commit_count = 0

    async def get_user_by_email(self, email_normalized: str) -> User | None:
        return next(
            (
                user
                for user in self.users.values()
                if user.email_normalized == email_normalized
            ),
            None,
        )

    async def get_user_by_id(self, user_id: UUID) -> User | None:
        return self.users.get(user_id)

    async def get_active_auth(
        self,
        user_id: UUID,
        session_id: UUID,
    ) -> tuple[User, AuthSession] | None:
        user = self.users.get(user_id)
        auth_session = self.sessions.get(session_id)
        if user is None or auth_session is None or auth_session.revoked_at is not None:
            return None
        return user, auth_session

    async def create_user(self, user: User) -> None:
        if await self.get_user_by_email(user.email_normalized):
            raise DuplicateEmailError
        now = datetime.now(UTC)
        user.id = uuid4()
        user.created_at = now
        user.updated_at = now
        self.users[user.id] = user

    async def get_refresh_for_update(self, token_hash: str) -> RefreshToken | None:
        return self.refresh_tokens.get(token_hash)

    def add_session(self, auth_session: AuthSession) -> None:
        self.sessions[auth_session.id] = auth_session

    async def get_session_for_update(self, session_id: UUID) -> AuthSession | None:
        return self.sessions.get(session_id)

    async def list_active_sessions(self, user_id: UUID) -> list[AuthSession]:
        return [
            item
            for item in self.sessions.values()
            if item.user_id == user_id and item.revoked_at is None
        ]

    async def revoke_session(
        self,
        user_id: UUID,
        session_id: UUID,
        revoked_at: datetime,
    ) -> bool:
        auth_session = self.sessions.get(session_id)
        if (
            auth_session is None
            or auth_session.user_id != user_id
            or auth_session.revoked_at is not None
        ):
            return False
        auth_session.revoked_at = revoked_at
        for token in self.refresh_tokens.values():
            if token.session_id == session_id and token.revoked_at is None:
                token.revoked_at = revoked_at
        return True

    async def revoke_all_sessions(self, user_id: UUID, revoked_at: datetime) -> None:
        for auth_session in self.sessions.values():
            if auth_session.user_id == user_id and auth_session.revoked_at is None:
                auth_session.revoked_at = revoked_at

    def add_refresh_token(self, token: RefreshToken) -> None:
        token.id = uuid4()
        self.refresh_tokens[token.token_hash] = token

    async def revoke_family(self, family_id: UUID, revoked_at: datetime) -> None:
        for token in self.refresh_tokens.values():
            if token.family_id == family_id and token.revoked_at is None:
                token.revoked_at = revoked_at

    async def revoke_all_for_user(self, user_id: UUID, revoked_at: datetime) -> None:
        for token in self.refresh_tokens.values():
            if token.user_id == user_id and token.revoked_at is None:
                token.revoked_at = revoked_at

    def add_action_token(self, token: ActionToken) -> None:
        self.action_tokens[token.token_hash] = token

    def add_outbox_event(self, event: AuthOutboxEvent) -> None:
        self.outbox_events.append(event)

    async def get_action_for_update(self, token_hash: str) -> ActionToken | None:
        return self.action_tokens.get(token_hash)

    async def invalidate_actions(
        self,
        user_id: UUID,
        purpose: str,
        invalidated_at: datetime,
    ) -> None:
        for token in self.action_tokens.values():
            if (
                token.user_id == user_id
                and token.purpose == purpose
                and token.used_at is None
                and token.invalidated_at is None
            ):
                token.invalidated_at = invalidated_at

    async def flush(self) -> None:
        return None

    async def commit(self) -> None:
        self.commit_count += 1


class FakeAuthSecurity:
    # [Design Intent] Argon2/JWT correctness belongs to security and API
    # integration tests; this fake keeps service unit tests fast and deterministic.
    def __init__(self) -> None:
        self.refresh_sequence = 0

    async def hash_password(self, password: str) -> str:
        return f"hashed::{password}"

    async def verify_password(
        self,
        password: str,
        stored_hash: str | None,
    ) -> tuple[bool, str | None]:
        return stored_hash == f"hashed::{password}", None

    @staticmethod
    def create_access_token(
        *,
        user_id: UUID,
        session_id: UUID,
        token_version: int,
    ) -> str:
        return f"access::{user_id}::{session_id}::{token_version}"

    def create_refresh_token(self) -> str:
        self.refresh_sequence += 1
        return f"refresh::{self.refresh_sequence}"

    @staticmethod
    def hash_refresh_token(token: str) -> str:
        return f"digest::{token}"

    @staticmethod
    def create_action_token(*, token_id: UUID, purpose: str) -> str:
        return f"action::{purpose}::{token_id}"

    @staticmethod
    def hash_action_token(token: str) -> str:
        return f"action-digest::{token}"


def build_service() -> tuple[AuthService, FakeAuthRepository, FakeAuthSecurity]:
    config = Settings(
        _env_file=None,
        environment="test",
    )
    repository = FakeAuthRepository()
    security = FakeAuthSecurity()
    return AuthService(repository, security, config), repository, security


def test_signup_service_normalizes_and_delegates_hashing_without_database() -> None:
    async def scenario() -> None:
        service, repository, _security = build_service()
        password = "correct horse battery staple"

        user = await service.signup(
            SignupRequest(
                email="  Owner@Example.COM ",
                display_name="Owner",
                password=password,
            )
        )

        assert user.email_normalized == "owner@example.com"
        assert user.password_hash == f"hashed::{password}"
        assert repository.users[user.id] is user

    asyncio.run(scenario())


def test_auth_service_maps_duplicate_and_issues_login_tokens() -> None:
    async def scenario() -> None:
        service, repository, _security = build_service()
        signup = SignupRequest(
            email="owner@example.com",
            display_name="Owner",
            password="correct horse battery staple",
        )
        user = await service.signup(signup)

        with pytest.raises(ApiError) as duplicate:
            await service.signup(signup)
        assert duplicate.value.status_code == 409
        assert duplicate.value.code == "AUTH_EMAIL_ALREADY_EXISTS"

        issued = await service.login(
            LoginRequest(email=signup.email, password=signup.password)
        )
        assert issued.access_token.startswith(f"access::{user.id}::")
        assert issued.access_token.endswith("::0")
        assert issued.refresh_record.token_hash in repository.refresh_tokens
        assert repository.commit_count == 2

    asyncio.run(scenario())


def test_production_settings_reject_http_web_origin() -> None:
    # [Design Intent] A production config that would make Secure cookies unusable
    # must fail at startup instead of producing a broken login after deployment.
    with pytest.raises(ValueError, match="web origins must use HTTPS"):
        Settings(
            _env_file=None,
            environment="production",
            web_origin="http://brandmate.example.com",
            additional_web_origins="",
            database_url="postgresql+asyncpg://user:password@db:5432/brandmate",
            auth_secret_key="production-secret-with-at-least-32-bytes",
            auth_refresh_cookie_name="__Host-brandmate_refresh",
            auth_refresh_cookie_secure=True,
            auth_email_verification_required=True,
            auth_email_delivery_enabled=True,
            auth_smtp_host="smtp.example.com",
            auth_smtp_from_email="no-reply@example.com",
            auth_public_web_url="https://brandmate.example.com",
            auth_rate_limit_backend="postgres",
        )
