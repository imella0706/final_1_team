import asyncio

from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy import select

from app.core.config import Settings
from app.db.base import Base
from app.main import create_app
from app.modules.auth.models import RefreshToken, User


def build_test_app():
    config = Settings(
        _env_file=None,
        environment="test",
        web_origin="http://testserver",
        additional_web_origins="",
        database_url=(
            "postgresql+asyncpg://brandmate_test:brandmate-test-only@127.0.0.1:55433/"
            "brandmate_test"
        ),
        auth_secret_key=SecretStr("test-secret-key-with-at-least-32-bytes-long"),
        auth_signup_limit_per_5_minutes=100,
        auth_login_limit_per_5_minutes=100,
        auth_refresh_limit_per_minute=100,
    )
    return create_app(config)


async def prepare_database(app) -> None:
    async with app.state.database.engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
        await connection.run_sync(Base.metadata.create_all)


def test_signup_login_refresh_reuse_detection_and_protected_routes() -> None:
    async def scenario() -> None:
        app = build_test_app()
        await prepare_database(app)
        transport = ASGITransport(app=app)
        async with AsyncClient(
            transport=transport,
            base_url="http://testserver",
            headers={"Origin": "http://testserver"},
        ) as client:
            protected = await client.get("/api/v1/ad-copies/models")
            assert protected.status_code == 401
            assert protected.json()["error"]["code"] == "AUTH_REQUIRED"

            payload = {
                "email": "Owner@Example.com",
                "display_name": "Owner",
                "password": "correct horse battery staple",
            }
            signup = await client.post("/api/v1/auth/signup", json=payload)
            assert signup.status_code == 201
            assert signup.json()["user"]["email"] == "owner@example.com"
            assert "password" not in signup.text

            duplicate = await client.post("/api/v1/auth/signup", json=payload)
            assert duplicate.status_code == 409
            assert duplicate.json()["error"]["code"] == "AUTH_EMAIL_ALREADY_EXISTS"

            invalid = await client.post(
                "/api/v1/auth/login",
                json={"email": payload["email"], "password": "wrong"},
            )
            assert invalid.status_code == 401
            assert invalid.json()["error"]["code"] == "AUTH_INVALID_CREDENTIALS"

            login = await client.post(
                "/api/v1/auth/login",
                json={"email": payload["email"], "password": payload["password"]},
            )
            assert login.status_code == 200
            assert login.json()["token_type"] == "bearer"
            assert login.headers["cache-control"] == "no-store"
            assert "httponly" in login.headers["set-cookie"].lower()
            assert "samesite=lax" in login.headers["set-cookie"].lower()
            old_refresh = client.cookies.get("brandmate_refresh")
            access_token = login.json()["access_token"]

            async with app.state.database.session_factory() as session:
                user = (await session.execute(select(User))).scalar_one()
                stored_refresh = (
                    await session.execute(select(RefreshToken))
                ).scalar_one()
                assert user.password_hash.startswith("$argon2id$")
                assert payload["password"] not in user.password_hash
                assert stored_refresh.token_hash != old_refresh
                assert len(stored_refresh.token_hash) == 64

            current_user = await client.get(
                "/api/v1/auth/me",
                headers={"Authorization": f"Bearer {access_token}"},
            )
            assert current_user.status_code == 200
            assert current_user.json()["display_name"] == "Owner"

            tampered_token = f"{access_token[:-1]}{'A' if access_token[-1] != 'A' else 'B'}"
            tampered = await client.get(
                "/api/v1/auth/me",
                headers={"Authorization": f"Bearer {tampered_token}"},
            )
            assert tampered.status_code == 401
            assert tampered.json()["error"]["code"] == "AUTH_TOKEN_INVALID"

            allowed = await client.get(
                "/api/v1/ad-copies/models",
                headers={"Authorization": f"Bearer {access_token}"},
            )
            assert allowed.status_code == 200

            refreshed = await client.post("/api/v1/auth/refresh")
            assert refreshed.status_code == 200
            assert refreshed.headers["cache-control"] == "no-store"
            new_refresh = client.cookies.get("brandmate_refresh")
            assert new_refresh != old_refresh

            async with AsyncClient(
                transport=transport,
                base_url="http://testserver",
                headers={
                    "Origin": "http://testserver",
                    "Cookie": f"brandmate_refresh={old_refresh}",
                },
            ) as attacker:
                reused = await attacker.post("/api/v1/auth/refresh")
            assert reused.status_code == 401
            assert reused.json()["error"]["code"] == "AUTH_REFRESH_REUSED"

            revoked_family = await client.post("/api/v1/auth/refresh")
            assert revoked_family.status_code == 401
            assert revoked_family.json()["error"]["code"] == "AUTH_REFRESH_EXPIRED"

        await app.state.database.dispose()

    asyncio.run(scenario())


def test_concurrent_signup_and_refresh_keep_database_consistent() -> None:
    async def scenario() -> None:
        app = build_test_app()
        await prepare_database(app)
        transport = ASGITransport(app=app)
        shared_headers = {"Origin": "http://testserver"}
        signup_payload = {
            "email": "concurrent@example.com",
            "display_name": "Concurrent Owner",
            "password": "correct horse battery staple",
        }

        async with (
            AsyncClient(
                transport=transport,
                base_url="http://testserver",
                headers=shared_headers,
            ) as first,
            AsyncClient(
                transport=transport,
                base_url="http://testserver",
                headers=shared_headers,
            ) as second,
        ):
            signup_results = await asyncio.gather(
                first.post("/api/v1/auth/signup", json=signup_payload),
                second.post("/api/v1/auth/signup", json=signup_payload),
            )
            assert sorted(response.status_code for response in signup_results) == [201, 409]

            await first.post(
                "/api/v1/auth/login",
                json={
                    "email": signup_payload["email"],
                    "password": signup_payload["password"],
                },
            )
            raw_refresh = first.cookies.get("brandmate_refresh")
            refresh_headers = {
                **shared_headers,
                "Cookie": f"brandmate_refresh={raw_refresh}",
            }
            async with (
                AsyncClient(
                    transport=transport,
                    base_url="http://testserver",
                    headers=refresh_headers,
                ) as refresh_one,
                AsyncClient(
                    transport=transport,
                    base_url="http://testserver",
                    headers=refresh_headers,
                ) as refresh_two,
            ):
                refresh_results = await asyncio.gather(
                    refresh_one.post("/api/v1/auth/refresh"),
                    refresh_two.post("/api/v1/auth/refresh"),
                )

            assert sorted(response.status_code for response in refresh_results) == [200, 401]
            rejected = next(response for response in refresh_results if response.status_code == 401)
            assert rejected.json()["error"]["code"] == "AUTH_REFRESH_REUSED"

            async with app.state.database.session_factory() as session:
                users = (await session.execute(select(User))).scalars().all()
                assert len(users) == 1

        await app.state.database.dispose()

    asyncio.run(scenario())


def test_logout_all_revokes_access_and_refresh_tokens() -> None:
    async def scenario() -> None:
        app = build_test_app()
        await prepare_database(app)
        transport = ASGITransport(app=app)
        async with AsyncClient(
            transport=transport,
            base_url="http://testserver",
            headers={"Origin": "http://testserver"},
        ) as client:
            await client.post(
                "/api/v1/auth/signup",
                json={
                    "email": "owner@example.com",
                    "display_name": "Owner",
                    "password": "correct horse battery staple",
                },
            )
            await client.post(
                "/api/v1/auth/login",
                json={
                    "email": "owner@example.com",
                    "password": "correct horse battery staple",
                },
            )
            old_refresh = client.cookies.get("brandmate_refresh")
            second_login = await client.post(
                "/api/v1/auth/login",
                json={
                    "email": "owner@example.com",
                    "password": "correct horse battery staple",
                },
            )
            access_token = second_login.json()["access_token"]
            authorization = {"Authorization": f"Bearer {access_token}"}

            async with AsyncClient(
                transport=transport,
                base_url="http://testserver",
                headers={
                    "Origin": "http://testserver",
                    "Cookie": f"brandmate_refresh={old_refresh}",
                },
            ) as stale_browser:
                stale_refresh = await stale_browser.post("/api/v1/auth/refresh")
            assert stale_refresh.status_code == 401
            assert stale_refresh.json()["error"]["code"] == "AUTH_REFRESH_EXPIRED"

            logout_all = await client.post("/api/v1/auth/logout-all", headers=authorization)
            assert logout_all.status_code == 204

            revoked_access = await client.get("/api/v1/auth/me", headers=authorization)
            assert revoked_access.status_code == 401
            assert revoked_access.json()["error"]["code"] == "AUTH_TOKEN_REVOKED"

            revoked_refresh = await client.post("/api/v1/auth/refresh")
            assert revoked_refresh.status_code == 401

        await app.state.database.dispose()

    asyncio.run(scenario())


def test_stolen_device_is_blocked_immediately_after_logout_all() -> None:
    async def scenario() -> None:
        app = build_test_app()
        await prepare_database(app)
        transport = ASGITransport(app=app)
        origin_headers = {"Origin": "http://testserver"}
        credentials = {
            "email": "stolen-device@example.com",
            "password": "correct horse battery staple",
        }

        # [Design Intent] Model the real incident: two independent browser cookie
        # jars exist, and the safe device terminates every session after theft.
        async with (
            AsyncClient(
                transport=transport,
                base_url="http://testserver",
                headers=origin_headers,
            ) as stolen_device,
            AsyncClient(
                transport=transport,
                base_url="http://testserver",
                headers=origin_headers,
            ) as safe_device,
        ):
            signup = await safe_device.post(
                "/api/v1/auth/signup",
                json={
                    **credentials,
                    "display_name": "Device Owner",
                },
            )
            assert signup.status_code == 201

            stolen_login = await stolen_device.post(
                "/api/v1/auth/login",
                json=credentials,
            )
            safe_login = await safe_device.post(
                "/api/v1/auth/login",
                json=credentials,
            )
            assert stolen_login.status_code == 200
            assert safe_login.status_code == 200

            stolen_authorization = {
                "Authorization": f"Bearer {stolen_login.json()['access_token']}"
            }
            safe_authorization = {
                "Authorization": f"Bearer {safe_login.json()['access_token']}"
            }
            before_revocation = await stolen_device.get(
                "/api/v1/auth/me",
                headers=stolen_authorization,
            )
            assert before_revocation.status_code == 200

            logout_all = await safe_device.post(
                "/api/v1/auth/logout-all",
                headers=safe_authorization,
            )
            assert logout_all.status_code == 204

            stolen_access = await stolen_device.get(
                "/api/v1/auth/me",
                headers=stolen_authorization,
            )
            assert stolen_access.status_code == 401
            assert stolen_access.json()["error"]["code"] == "AUTH_TOKEN_REVOKED"

            stolen_refresh = await stolen_device.post("/api/v1/auth/refresh")
            assert stolen_refresh.status_code == 401
            assert stolen_refresh.json()["error"]["code"] == "AUTH_REFRESH_EXPIRED"

            async with app.state.database.session_factory() as session:
                refresh_tokens = (
                    await session.execute(select(RefreshToken))
                ).scalars().all()
                assert len(refresh_tokens) == 2
                assert all(token.revoked_at is not None for token in refresh_tokens)

        await app.state.database.dispose()

    asyncio.run(scenario())


def test_rejects_cross_site_cookie_requests_and_redacts_invalid_password() -> None:
    async def scenario() -> None:
        app = build_test_app()
        await prepare_database(app)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            forbidden = await client.post(
                "/api/v1/auth/login",
                headers={"Origin": "https://attacker.example"},
                json={"email": "owner@example.com", "password": "secret-password"},
            )
            assert forbidden.status_code == 403
            assert forbidden.json()["error"]["code"] == "AUTH_ORIGIN_FORBIDDEN"

            invalid_password = "do-not-echo-this"
            validation = await client.post(
                "/api/v1/auth/signup",
                headers={"Origin": "http://testserver"},
                json={
                    "email": "owner@example.com",
                    "display_name": "Owner",
                    "password": invalid_password * 20,
                },
            )
            assert validation.status_code == 422
            assert invalid_password not in validation.text
            assert validation.json()["error"]["code"] == "REQUEST_VALIDATION_FAILED"

        await app.state.database.dispose()

    asyncio.run(scenario())
