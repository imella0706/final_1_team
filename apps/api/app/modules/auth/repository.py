from datetime import datetime
from typing import Protocol
from uuid import UUID

from sqlalchemy import Select, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.models import (
    ActionToken,
    AuthOutboxEvent,
    AuthSession,
    RefreshToken,
    User,
)


class DuplicateEmailError(Exception):
    """Raised when the database rejects a duplicate normalized email."""


class AuthRepositoryPort(Protocol):
    # [Design Intent] The service depends on this small persistence contract, not
    # AsyncSession. Tests can replace PostgreSQL with a deterministic fake.
    async def get_user_by_email(self, email_normalized: str) -> User | None: ...

    async def get_user_by_id(self, user_id: UUID) -> User | None: ...

    async def get_active_auth(
        self,
        user_id: UUID,
        session_id: UUID,
    ) -> tuple[User, AuthSession] | None: ...

    async def create_user(self, user: User) -> None: ...

    def add_session(self, auth_session: AuthSession) -> None: ...

    async def get_session_for_update(self, session_id: UUID) -> AuthSession | None: ...

    async def list_active_sessions(self, user_id: UUID) -> list[AuthSession]: ...

    async def revoke_session(
        self,
        user_id: UUID,
        session_id: UUID,
        revoked_at: datetime,
    ) -> bool: ...

    async def revoke_all_sessions(self, user_id: UUID, revoked_at: datetime) -> None: ...

    async def get_refresh_for_update(self, token_hash: str) -> RefreshToken | None: ...

    def add_refresh_token(self, token: RefreshToken) -> None: ...

    async def revoke_family(self, family_id: UUID, revoked_at: datetime) -> None: ...

    async def revoke_all_for_user(self, user_id: UUID, revoked_at: datetime) -> None: ...

    def add_action_token(self, token: ActionToken) -> None: ...

    def add_outbox_event(self, event: AuthOutboxEvent) -> None: ...

    async def get_action_for_update(self, token_hash: str) -> ActionToken | None: ...

    async def invalidate_actions(
        self,
        user_id: UUID,
        purpose: str,
        invalidated_at: datetime,
    ) -> None: ...

    async def flush(self) -> None: ...

    async def commit(self) -> None: ...


class SqlAlchemyAuthRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_user_by_email(self, email_normalized: str) -> User | None:
        result = await self._session.execute(
            select(User).where(User.email_normalized == email_normalized)
        )
        return result.scalar_one_or_none()

    async def get_user_by_id(self, user_id: UUID) -> User | None:
        return await self._session.get(User, user_id)

    async def get_active_auth(
        self,
        user_id: UUID,
        session_id: UUID,
    ) -> tuple[User, AuthSession] | None:
        # [Design Intent] User status, token version inputs, and session revocation
        # are loaded in one indexed query on every protected request.
        result = await self._session.execute(
            select(User, AuthSession)
            .join(AuthSession, AuthSession.user_id == User.id)
            .where(
                User.id == user_id,
                AuthSession.id == session_id,
            )
        )
        row = result.one_or_none()
        return (row[0], row[1]) if row else None

    async def create_user(self, user: User) -> None:
        # [Design Intent] The repository translates a database race into a
        # persistence-neutral error. The service never imports SQLAlchemy.
        self._session.add(user)
        try:
            await self._session.flush()
        except IntegrityError as exc:
            await self._session.rollback()
            raise DuplicateEmailError from exc
        await self._session.refresh(user)

    def add_session(self, auth_session: AuthSession) -> None:
        self._session.add(auth_session)

    async def get_session_for_update(self, session_id: UUID) -> AuthSession | None:
        result = await self._session.execute(
            select(AuthSession)
            .where(AuthSession.id == session_id)
            .with_for_update()
        )
        return result.scalar_one_or_none()

    async def list_active_sessions(self, user_id: UUID) -> list[AuthSession]:
        result = await self._session.execute(
            select(AuthSession)
            .where(
                AuthSession.user_id == user_id,
                AuthSession.revoked_at.is_(None),
            )
            .order_by(AuthSession.last_seen_at.desc())
        )
        return list(result.scalars())

    async def revoke_session(
        self,
        user_id: UUID,
        session_id: UUID,
        revoked_at: datetime,
    ) -> bool:
        result = await self._session.execute(
            update(AuthSession)
            .where(
                AuthSession.user_id == user_id,
                AuthSession.id == session_id,
                AuthSession.revoked_at.is_(None),
            )
            .values(revoked_at=revoked_at)
        )
        await self._session.execute(
            update(RefreshToken)
            .where(
                RefreshToken.user_id == user_id,
                RefreshToken.session_id == session_id,
                RefreshToken.revoked_at.is_(None),
            )
            .values(revoked_at=revoked_at)
        )
        return bool(result.rowcount)

    async def revoke_all_sessions(self, user_id: UUID, revoked_at: datetime) -> None:
        await self._session.execute(
            update(AuthSession)
            .where(
                AuthSession.user_id == user_id,
                AuthSession.revoked_at.is_(None),
            )
            .values(revoked_at=revoked_at)
        )

    async def get_refresh_for_update(self, token_hash: str) -> RefreshToken | None:
        statement: Select[tuple[RefreshToken]] = (
            select(RefreshToken)
            .where(RefreshToken.token_hash == token_hash)
            .with_for_update()
        )
        result = await self._session.execute(statement)
        return result.scalar_one_or_none()

    def add_refresh_token(self, token: RefreshToken) -> None:
        self._session.add(token)

    async def revoke_family(self, family_id: UUID, revoked_at: datetime) -> None:
        await self._session.execute(
            update(RefreshToken)
            .where(
                RefreshToken.family_id == family_id,
                RefreshToken.revoked_at.is_(None),
            )
            .values(revoked_at=revoked_at)
        )

    async def revoke_all_for_user(self, user_id: UUID, revoked_at: datetime) -> None:
        await self._session.execute(
            update(RefreshToken)
            .where(
                RefreshToken.user_id == user_id,
                RefreshToken.revoked_at.is_(None),
            )
            .values(revoked_at=revoked_at)
        )

    def add_action_token(self, token: ActionToken) -> None:
        self._session.add(token)

    def add_outbox_event(self, event: AuthOutboxEvent) -> None:
        self._session.add(event)

    async def get_action_for_update(self, token_hash: str) -> ActionToken | None:
        result = await self._session.execute(
            select(ActionToken)
            .where(ActionToken.token_hash == token_hash)
            .with_for_update()
        )
        return result.scalar_one_or_none()

    async def invalidate_actions(
        self,
        user_id: UUID,
        purpose: str,
        invalidated_at: datetime,
    ) -> None:
        await self._session.execute(
            update(ActionToken)
            .where(
                ActionToken.user_id == user_id,
                ActionToken.purpose == purpose,
                ActionToken.used_at.is_(None),
                ActionToken.invalidated_at.is_(None),
            )
            .values(invalidated_at=invalidated_at)
        )

    async def flush(self) -> None:
        await self._session.flush()

    async def commit(self) -> None:
        await self._session.commit()
