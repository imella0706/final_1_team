from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from app.core.config import Settings
from app.core.errors import ApiError
from app.modules.auth.models import (
    ActionToken,
    AuthOutboxEvent,
    AuthSession,
    RefreshToken,
    User,
)
from app.modules.auth.repository import AuthRepositoryPort, DuplicateEmailError
from app.modules.auth.schemas import LoginRequest, SessionPublic, SignupRequest, UserPublic
from app.modules.auth.security import AuthSecurityPort


@dataclass(slots=True)
class IssuedTokens:
    access_token: str
    refresh_token: str
    expires_in: int
    user: User
    refresh_record: RefreshToken


def normalize_email(email: str) -> str:
    return email.strip().casefold()


def to_public_user(user: User) -> UserPublic:
    return UserPublic(
        id=user.id,
        email=user.email_normalized,
        display_name=user.display_name,
        status=user.status,
        email_verified=user.email_verified_at is not None,
        created_at=user.created_at,
    )


def as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


class AuthService:
    def __init__(
        self,
        repository: AuthRepositoryPort,
        security: AuthSecurityPort,
        config: Settings,
    ) -> None:
        self.repository = repository
        self.security = security
        self.config = config

    async def signup(self, request: SignupRequest) -> User:
        email = normalize_email(str(request.email))
        if await self.repository.get_user_by_email(email):
            raise ApiError(409, "AUTH_EMAIL_ALREADY_EXISTS", "이미 가입된 이메일입니다.")

        now = datetime.now(UTC)
        requires_verification = self.config.auth_email_verification_required
        user = User(
            email_normalized=email,
            display_name=request.display_name,
            password_hash=await self.security.hash_password(request.password.get_secret_value()),
            status="pending_verification" if requires_verification else "active",
            token_version=0,
            email_verified_at=None if requires_verification else now,
        )
        try:
            await self.repository.create_user(user)
        except DuplicateEmailError as exc:
            raise ApiError(
                409,
                "AUTH_EMAIL_ALREADY_EXISTS",
                "이미 가입된 이메일입니다.",
            ) from exc
        if requires_verification:
            await self._replace_action_token(
                user,
                purpose="verify_email",
                expires_at=now + timedelta(hours=self.config.auth_email_verification_hours),
            )
        await self.repository.commit()
        return user

    async def login(
        self,
        request: LoginRequest,
        *,
        existing_refresh_token: str | None = None,
    ) -> IssuedTokens:
        email = normalize_email(str(request.email))
        user = await self.repository.get_user_by_email(email)
        valid, updated_hash = await self.security.verify_password(
            request.password.get_secret_value(),
            user.password_hash if user else None,
        )
        if not valid or user is None or user.status != "active":
            # [Design Intent] Missing accounts and wrong passwords share the same
            # response and both execute Argon2, reducing account enumeration signal.
            if valid and user is not None and user.status == "pending_verification":
                raise ApiError(
                    403,
                    "AUTH_EMAIL_NOT_VERIFIED",
                    "이메일 인증을 완료해 주세요.",
                )
            raise ApiError(
                401,
                "AUTH_INVALID_CREDENTIALS",
                "이메일 또는 비밀번호가 올바르지 않습니다.",
            )

        if updated_hash:
            user.password_hash = updated_hash
        if existing_refresh_token:
            existing = await self.repository.get_refresh_for_update(
                self.security.hash_refresh_token(existing_refresh_token)
            )
            if existing is not None:
                now = datetime.now(UTC)
                await self.repository.revoke_family(existing.family_id, now)
                if existing.session_id:
                    await self.repository.revoke_session(user.id, existing.session_id, now)

        now = datetime.now(UTC)
        auth_session = AuthSession(
            id=uuid4(),
            user_id=user.id,
            device_name=request.device_name,
            created_at=now,
            last_seen_at=now,
        )
        self.repository.add_session(auth_session)
        issued = self._issue_tokens(user, session_id=auth_session.id)
        await self.repository.commit()
        return issued

    async def refresh(self, raw_token: str | None) -> IssuedTokens:
        if not raw_token:
            raise ApiError(401, "AUTH_REFRESH_REQUIRED", "로그인이 필요합니다.")

        now = datetime.now(UTC)
        stored = await self.repository.get_refresh_for_update(
            self.security.hash_refresh_token(raw_token)
        )
        if stored is None:
            raise ApiError(401, "AUTH_REFRESH_INVALID", "세션을 갱신할 수 없습니다.")

        if stored.used_at is not None:
            await self.repository.revoke_family(stored.family_id, now)
            await self.repository.commit()
            raise ApiError(
                401,
                "AUTH_REFRESH_REUSED",
                "세션 이상이 감지되어 다시 로그인해야 합니다.",
            )

        if stored.revoked_at is not None or as_utc(stored.expires_at) <= now:
            raise ApiError(401, "AUTH_REFRESH_EXPIRED", "세션이 만료되었습니다.")

        if stored.session_id is None:
            await self.repository.revoke_family(stored.family_id, now)
            await self.repository.commit()
            raise ApiError(401, "AUTH_REFRESH_EXPIRED", "세션이 만료되었습니다.")

        auth_session = await self.repository.get_session_for_update(stored.session_id)
        if auth_session is None or auth_session.revoked_at is not None:
            await self.repository.revoke_family(stored.family_id, now)
            await self.repository.commit()
            raise ApiError(401, "AUTH_REFRESH_EXPIRED", "세션이 만료되었습니다.")

        user = await self.repository.get_user_by_id(stored.user_id)
        if user is None or user.status != "active":
            await self.repository.revoke_family(stored.family_id, now)
            await self.repository.commit()
            raise ApiError(401, "AUTH_ACCOUNT_UNAVAILABLE", "로그인이 필요합니다.")

        stored.used_at = now
        auth_session.last_seen_at = now
        issued = self._issue_tokens(
            user,
            session_id=auth_session.id,
            family_id=stored.family_id,
        )
        await self.repository.flush()
        stored.replaced_by_id = issued.refresh_record.id
        await self.repository.commit()
        return issued

    async def logout(self, raw_token: str | None) -> None:
        if not raw_token:
            return
        stored = await self.repository.get_refresh_for_update(
            self.security.hash_refresh_token(raw_token)
        )
        if stored is not None:
            now = datetime.now(UTC)
            await self.repository.revoke_family(stored.family_id, now)
            if stored.session_id:
                await self.repository.revoke_session(stored.user_id, stored.session_id, now)
            await self.repository.commit()

    async def logout_all(self, user: User) -> None:
        now = datetime.now(UTC)
        user.token_version += 1
        await self.repository.revoke_all_for_user(user.id, now)
        await self.repository.revoke_all_sessions(user.id, now)
        await self.repository.commit()

    async def list_sessions(self, user: User, current_session_id: UUID) -> list[SessionPublic]:
        sessions = await self.repository.list_active_sessions(user.id)
        return [
            SessionPublic(
                id=item.id,
                device_name=item.device_name,
                created_at=item.created_at,
                last_seen_at=item.last_seen_at,
                current=item.id == current_session_id,
            )
            for item in sessions
        ]

    async def revoke_session(self, user: User, session_id: UUID) -> None:
        revoked = await self.repository.revoke_session(user.id, session_id, datetime.now(UTC))
        if not revoked:
            raise ApiError(404, "AUTH_SESSION_NOT_FOUND", "로그인 기기를 찾을 수 없습니다.")
        await self.repository.commit()

    async def resend_verification(self, email: str) -> None:
        user = await self.repository.get_user_by_email(normalize_email(email))
        if user is not None and user.status == "pending_verification":
            now = datetime.now(UTC)
            await self._replace_action_token(
                user,
                purpose="verify_email",
                expires_at=now + timedelta(hours=self.config.auth_email_verification_hours),
            )
            await self.repository.commit()

    async def verify_email(self, raw_token: str) -> User:
        token, user = await self._consume_action_token(raw_token, purpose="verify_email")
        now = datetime.now(UTC)
        token.used_at = now
        user.email_verified_at = now
        if user.status == "pending_verification":
            user.status = "active"
        await self.repository.invalidate_actions(user.id, "verify_email", now)
        await self.repository.commit()
        return user

    async def request_password_reset(self, email: str) -> None:
        user = await self.repository.get_user_by_email(normalize_email(email))
        if user is not None and user.status == "active":
            now = datetime.now(UTC)
            await self._replace_action_token(
                user,
                purpose="reset_password",
                expires_at=now + timedelta(minutes=self.config.auth_password_reset_minutes),
            )
            await self.repository.commit()

    async def reset_password(self, raw_token: str, new_password: str) -> None:
        token, user = await self._consume_action_token(raw_token, purpose="reset_password")
        now = datetime.now(UTC)
        token.used_at = now
        user.password_hash = await self.security.hash_password(new_password)
        user.token_version += 1
        await self.repository.invalidate_actions(user.id, "reset_password", now)
        await self.repository.revoke_all_for_user(user.id, now)
        await self.repository.revoke_all_sessions(user.id, now)
        await self.repository.commit()

    async def change_password(
        self,
        user: User,
        *,
        current_password: str,
        new_password: str,
    ) -> None:
        valid, _ = await self.security.verify_password(current_password, user.password_hash)
        if not valid:
            raise ApiError(
                401,
                "AUTH_CURRENT_PASSWORD_INVALID",
                "현재 비밀번호가 올바르지 않습니다.",
            )
        if current_password == new_password:
            raise ApiError(
                400,
                "AUTH_PASSWORD_UNCHANGED",
                "새 비밀번호는 현재 비밀번호와 달라야 합니다.",
            )
        now = datetime.now(UTC)
        user.password_hash = await self.security.hash_password(new_password)
        user.token_version += 1
        await self.repository.invalidate_actions(user.id, "reset_password", now)
        await self.repository.revoke_all_for_user(user.id, now)
        await self.repository.revoke_all_sessions(user.id, now)
        await self.repository.commit()

    async def _replace_action_token(
        self,
        user: User,
        *,
        purpose: str,
        expires_at: datetime,
    ) -> ActionToken:
        now = datetime.now(UTC)
        await self.repository.invalidate_actions(user.id, purpose, now)
        token_id = uuid4()
        raw_token = self.security.create_action_token(token_id=token_id, purpose=purpose)
        action = ActionToken(
            id=token_id,
            user_id=user.id,
            purpose=purpose,
            token_hash=self.security.hash_action_token(raw_token),
            expires_at=expires_at,
            created_at=now,
        )
        self.repository.add_action_token(action)
        self.repository.add_outbox_event(
            AuthOutboxEvent(
                id=uuid4(),
                user_id=user.id,
                action_token_id=action.id,
                event_type=f"auth.{purpose}",
                status="pending",
                attempt_count=0,
                next_attempt_at=now,
                created_at=now,
            )
        )
        return action

    async def _consume_action_token(
        self,
        raw_token: str,
        *,
        purpose: str,
    ) -> tuple[ActionToken, User]:
        now = datetime.now(UTC)
        stored = await self.repository.get_action_for_update(
            self.security.hash_action_token(raw_token)
        )
        if (
            stored is None
            or stored.purpose != purpose
            or stored.used_at is not None
            or stored.invalidated_at is not None
            or as_utc(stored.expires_at) <= now
        ):
            raise ApiError(
                400,
                "AUTH_ACTION_TOKEN_INVALID",
                "링크가 유효하지 않거나 만료되었습니다.",
            )
        user = await self.repository.get_user_by_id(stored.user_id)
        if user is None or user.status in {"disabled", "deleted"}:
            raise ApiError(
                400,
                "AUTH_ACTION_TOKEN_INVALID",
                "링크가 유효하지 않거나 만료되었습니다.",
            )
        return stored, user

    def _issue_tokens(
        self,
        user: User,
        *,
        session_id: UUID,
        family_id: UUID | None = None,
    ) -> IssuedTokens:
        now = datetime.now(UTC)
        raw_refresh = self.security.create_refresh_token()
        refresh = RefreshToken(
            user_id=user.id,
            session_id=session_id,
            token_hash=self.security.hash_refresh_token(raw_refresh),
            family_id=family_id or uuid4(),
            expires_at=now + timedelta(days=self.config.auth_refresh_token_days),
            created_at=now,
        )
        self.repository.add_refresh_token(refresh)
        return IssuedTokens(
            access_token=self.security.create_access_token(
                user_id=user.id,
                session_id=session_id,
                token_version=user.token_version,
            ),
            refresh_token=raw_refresh,
            expires_in=self.config.auth_access_token_minutes * 60,
            user=user,
            refresh_record=refresh,
        )
