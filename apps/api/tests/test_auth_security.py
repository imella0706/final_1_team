from datetime import UTC, datetime, timedelta
from uuid import uuid4

import jwt
import pytest
from pydantic import SecretStr

from app.core.config import Settings
from app.core.errors import ApiError
from app.modules.auth.security import AuthSecurity

SECRET = "test-secret-key-with-at-least-32-bytes-long"


def build_security() -> AuthSecurity:
    return AuthSecurity(
        Settings(
            _env_file=None,
            environment="test",
            auth_secret_key=SecretStr(SECRET),
        )
    )


def valid_claims() -> dict:
    now = datetime.now(UTC)
    return {
        "iss": "brandmate-api",
        "aud": "brandmate-web",
        "sub": str(uuid4()),
        "sid": str(uuid4()),
        "exp": now + timedelta(minutes=5),
        "iat": now,
        "jti": str(uuid4()),
        "typ": "access",
        "ver": 0,
    }


@pytest.mark.parametrize(
    ("claim", "value"),
    [
        ("iss", "attacker-api"),
        ("aud", "other-client"),
        ("typ", "refresh"),
    ],
)
def test_access_token_rejects_each_wrong_security_claim(claim: str, value: str) -> None:
    # [Design Intent] Each trust-boundary claim fails in isolation so a future
    # decoder refactor cannot silently disable issuer, audience, or type checks.
    claims = valid_claims()
    claims[claim] = value
    token = jwt.encode(claims, SECRET, algorithm="HS256")

    with pytest.raises(ApiError) as rejected:
        build_security().decode_access_token(token)

    assert rejected.value.code == "AUTH_TOKEN_INVALID"


def test_access_token_rejects_expired_token() -> None:
    claims = valid_claims()
    claims["iat"] = datetime.now(UTC) - timedelta(minutes=10)
    claims["exp"] = datetime.now(UTC) - timedelta(minutes=1)
    token = jwt.encode(claims, SECRET, algorithm="HS256")

    with pytest.raises(ApiError) as rejected:
        build_security().decode_access_token(token)

    assert rejected.value.code == "AUTH_TOKEN_EXPIRED"


def test_access_token_requires_session_id() -> None:
    claims = valid_claims()
    del claims["sid"]
    token = jwt.encode(claims, SECRET, algorithm="HS256")

    with pytest.raises(ApiError) as rejected:
        build_security().decode_access_token(token)

    assert rejected.value.code == "AUTH_TOKEN_INVALID"
