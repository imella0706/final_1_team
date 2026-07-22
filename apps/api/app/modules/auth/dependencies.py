from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import ApiError
from app.modules.auth.models import AuthSession, User
from app.modules.auth.repository import SqlAlchemyAuthRepository
from app.modules.auth.security import AuthSecurity
from app.modules.auth.service import AuthService

bearer_scheme = HTTPBearer(auto_error=False)


@dataclass(slots=True)
class AuthContext:
    user: User
    session: AuthSession


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    async for session in request.app.state.database.session():
        yield session


def get_config(request: Request) -> Settings:
    return request.app.state.config


def get_security(request: Request) -> AuthSecurity:
    return request.app.state.auth_security


def get_auth_service(
    session: Annotated[AsyncSession, Depends(get_session)],
    security: Annotated[AuthSecurity, Depends(get_security)],
    config: Annotated[Settings, Depends(get_config)],
) -> AuthService:
    return AuthService(SqlAlchemyAuthRepository(session), security, config)


async def get_current_auth(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    session: Annotated[AsyncSession, Depends(get_session)],
    security: Annotated[AuthSecurity, Depends(get_security)],
) -> AuthContext:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise ApiError(
            401,
            "AUTH_REQUIRED",
            "로그인이 필요합니다.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    claims = security.decode_access_token(credentials.credentials)
    current = await SqlAlchemyAuthRepository(session).get_active_auth(
        UUID(claims["sub"]),
        UUID(claims["sid"]),
    )
    if current is None:
        raise ApiError(401, "AUTH_SESSION_REVOKED", "로그인 세션이 종료되었습니다.")
    user, auth_session = current
    if user.status != "active":
        raise ApiError(401, "AUTH_ACCOUNT_UNAVAILABLE", "로그인이 필요합니다.")
    if user.token_version != claims["ver"]:
        raise ApiError(401, "AUTH_TOKEN_REVOKED", "인증이 취소되었습니다.")
    if auth_session.revoked_at is not None:
        raise ApiError(401, "AUTH_SESSION_REVOKED", "로그인 세션이 종료되었습니다.")
    return AuthContext(user=user, session=auth_session)


async def get_current_user(
    context: Annotated[AuthContext, Depends(get_current_auth)],
) -> User:
    return context.user
