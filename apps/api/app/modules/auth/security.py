import asyncio
import base64
import hashlib
import hmac
import logging
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from uuid import UUID, uuid4

import jwt
from pwdlib import PasswordHash

from app.core.config import Settings
from app.core.errors import ApiError

logger = logging.getLogger("brandmate.auth")


class AuthSecurityPort(Protocol):
    # [Design Intent] AuthService depends on cryptographic capabilities, allowing
    # fast deterministic unit tests while the real adapter is tested separately.
    async def hash_password(self, password: str) -> str: ...

    async def verify_password(
        self,
        password: str,
        stored_hash: str | None,
    ) -> tuple[bool, str | None]: ...

    def create_access_token(
        self,
        *,
        user_id: UUID,
        session_id: UUID,
        token_version: int,
    ) -> str: ...

    def create_refresh_token(self) -> str: ...

    def hash_refresh_token(self, token: str) -> str: ...

    def create_action_token(self, *, token_id: UUID, purpose: str) -> str: ...

    def hash_action_token(self, token: str) -> str: ...


class AuthSecurity:
    def __init__(self, config: Settings) -> None:
        # [Design Intent] Argon2id is adaptive and memory-hard. Hashing runs in a
        # worker thread so its deliberate CPU cost does not block FastAPI's loop.
        self.password_hash = PasswordHash.recommended()
        self._dummy_password_hash = self.password_hash.hash(secrets.token_urlsafe(32))
        configured_secret = (
            config.auth_secret_key.get_secret_value() if config.auth_secret_key else None
        )
        if configured_secret:
            self._jwt_secret = configured_secret
        else:
            self._jwt_secret = secrets.token_urlsafe(48)
            logger.warning(
                "BRANDMATE_AUTH_SECRET_KEY is missing; generated an ephemeral local key. "
                "Tokens will be invalid after restart."
            )
        self.config = config

    async def hash_password(self, password: str) -> str:
        return await asyncio.to_thread(self.password_hash.hash, password)

    async def verify_password(
        self,
        password: str,
        stored_hash: str | None,
    ) -> tuple[bool, str | None]:
        candidate_hash = stored_hash or self._dummy_password_hash
        valid, updated_hash = await asyncio.to_thread(
            self.password_hash.verify_and_update,
            password,
            candidate_hash,
        )
        return bool(valid and stored_hash), updated_hash if stored_hash else None

    def create_access_token(
        self,
        *,
        user_id: UUID,
        session_id: UUID,
        token_version: int,
    ) -> str:
        now = datetime.now(UTC)
        expires_at = now + timedelta(minutes=self.config.auth_access_token_minutes)
        payload = {
            "iss": self.config.auth_jwt_issuer,
            "aud": self.config.auth_jwt_audience,
            "sub": str(user_id),
            "sid": str(session_id),
            "exp": expires_at,
            "iat": now,
            "jti": str(uuid4()),
            "typ": "access",
            "ver": token_version,
        }
        return jwt.encode(
            payload,
            self._jwt_secret,
            algorithm=self.config.auth_jwt_algorithm,
        )

    def decode_access_token(self, token: str) -> dict[str, Any]:
        try:
            claims = jwt.decode(
                token,
                self._jwt_secret,
                algorithms=[self.config.auth_jwt_algorithm],
                audience=self.config.auth_jwt_audience,
                issuer=self.config.auth_jwt_issuer,
                options={
                    "require": [
                        "iss",
                        "aud",
                        "sub",
                        "sid",
                        "exp",
                        "iat",
                        "jti",
                        "typ",
                        "ver",
                    ]
                },
                leeway=5,
            )
            if claims.get("typ") != "access":
                raise jwt.InvalidTokenError("unexpected token type")
            UUID(str(claims["sub"]))
            UUID(str(claims["sid"]))
            UUID(str(claims["jti"]))
            if not isinstance(claims.get("ver"), int):
                raise jwt.InvalidTokenError("invalid token version")
            return claims
        except jwt.ExpiredSignatureError as exc:
            raise ApiError(401, "AUTH_TOKEN_EXPIRED", "인증이 만료되었습니다.") from exc
        except (jwt.InvalidTokenError, ValueError, TypeError) as exc:
            raise ApiError(401, "AUTH_TOKEN_INVALID", "유효하지 않은 인증입니다.") from exc

    @staticmethod
    def create_refresh_token() -> str:
        return secrets.token_urlsafe(48)

    @staticmethod
    def hash_refresh_token(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    def create_action_token(self, *, token_id: UUID, purpose: str) -> str:
        # [Design Intent] The UUID is a public selector and the HMAC is the secret
        # proof. Workers can reconstruct a link without persisting the raw token.
        message = f"brandmate-auth-action:{purpose}:{token_id}".encode()
        signature = hmac.new(
            self._jwt_secret.encode(),
            message,
            hashlib.sha256,
        ).digest()
        encoded = base64.urlsafe_b64encode(signature).rstrip(b"=").decode()
        return f"{token_id}.{encoded}"

    @staticmethod
    def hash_action_token(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()
