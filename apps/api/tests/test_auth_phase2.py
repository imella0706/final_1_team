import asyncio
from datetime import UTC, datetime

from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy import select

from app.core.config import Settings
from app.core.errors import ApiError
from app.db.base import Base
from app.main import create_app
from app.modules.auth.models import (
    ActionToken,
    AuthOutboxEvent,
    AuthRateLimitBucket,
    AuthSession,
    User,
)
from app.modules.auth.outbox import AuthOutboxProcessor
from app.modules.auth.rate_limit import PostgresAuthRateLimiter


def build_phase2_test_app():
    # [Design Intent] Public-MVP policy is enabled explicitly so these tests do
    # not confuse permissive local development with production authentication.
    config = Settings(
        _env_file=None,
        environment="test",
        web_origin="https://testserver",
        additional_web_origins="",
        database_url=(
            "postgresql+asyncpg://brandmate_test:brandmate-test-only@127.0.0.1:55433/"
            "brandmate_test"
        ),
        auth_secret_key=SecretStr("test-secret-key-with-at-least-32-bytes-long"),
        auth_email_verification_required=True,
        auth_refresh_cookie_name="__Host-brandmate_refresh",
        auth_refresh_cookie_secure=True,
        auth_signup_limit_per_5_minutes=100,
        auth_login_limit_per_5_minutes=100,
        auth_login_ip_limit_per_5_minutes=100,
        auth_refresh_limit_per_minute=100,
    )
    return create_app(config)


async def prepare_database(app) -> None:
    async with app.state.database.engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
        await connection.run_sync(Base.metadata.create_all)


async def signup(client: AsyncClient, email: str = "owner@example.com"):
    return await client.post(
        "/api/v1/auth/signup",
        json={
            "email": email,
            "display_name": "Owner",
            "password": "correct horse battery staple",
        },
    )


async def raw_action_token(app, purpose: str) -> str:
    async with app.state.database.session_factory() as session:
        action = (
            await session.execute(
                select(ActionToken)
                .where(ActionToken.purpose == purpose)
                .order_by(ActionToken.created_at.desc())
            )
        ).scalars().first()
        assert action is not None
        return app.state.auth_security.create_action_token(
            token_id=action.id,
            purpose=action.purpose,
        )


def test_email_verification_is_required_before_login() -> None:
    async def scenario() -> None:
        app = build_phase2_test_app()
        await prepare_database(app)
        transport = ASGITransport(app=app)
        async with AsyncClient(
            transport=transport,
            base_url="https://testserver",
            headers={"Origin": "https://testserver"},
        ) as client:
            created = await signup(client)
            assert created.status_code == 201
            assert created.json()["user"]["status"] == "pending_verification"

            blocked = await client.post(
                "/api/v1/auth/login",
                json={
                    "email": "owner@example.com",
                    "password": "correct horse battery staple",
                },
            )
            assert blocked.status_code == 403
            assert blocked.json()["error"]["code"] == "AUTH_EMAIL_NOT_VERIFIED"

            token = await raw_action_token(app, "verify_email")
            verified = await client.post(
                "/api/v1/auth/verify-email",
                json={"token": token},
            )
            assert verified.status_code == 200
            assert verified.json()["user"]["email_verified"] is True

            login = await client.post(
                "/api/v1/auth/login",
                json={
                    "email": "owner@example.com",
                    "password": "correct horse battery staple",
                    "device_name": "내 노트북",
                },
            )
            assert login.status_code == 200
            cookie = login.headers["set-cookie"].lower()
            assert "__host-brandmate_refresh=" in cookie
            assert "secure" in cookie
            assert "httponly" in cookie

            metrics = await client.get("/metrics")
            assert metrics.status_code == 200
            assert "brandmate_auth_requests_total" in metrics.text
            assert "AUTH_EMAIL_NOT_VERIFIED" in metrics.text
            assert "owner@example.com" not in metrics.text

        await app.state.database.dispose()

    asyncio.run(scenario())


def test_password_reset_is_single_use_and_revokes_existing_sessions() -> None:
    async def scenario() -> None:
        app = build_phase2_test_app()
        await prepare_database(app)
        transport = ASGITransport(app=app)
        headers = {"Origin": "https://testserver"}
        async with AsyncClient(
            transport=transport,
            base_url="https://testserver",
            headers=headers,
        ) as client:
            await signup(client)
            verify_token = await raw_action_token(app, "verify_email")
            await client.post("/api/v1/auth/verify-email", json={"token": verify_token})
            login = await client.post(
                "/api/v1/auth/login",
                json={
                    "email": "owner@example.com",
                    "password": "correct horse battery staple",
                },
            )
            old_access = login.json()["access_token"]

            unknown = await client.post(
                "/api/v1/auth/password-reset/request",
                json={"email": "missing@example.com"},
            )
            requested = await client.post(
                "/api/v1/auth/password-reset/request",
                json={"email": "owner@example.com"},
            )
            assert unknown.status_code == requested.status_code == 202
            assert unknown.json() == requested.json()

            reset_token = await raw_action_token(app, "reset_password")
            reset = await client.post(
                "/api/v1/auth/password-reset/confirm",
                json={
                    "token": reset_token,
                    "new_password": "new correct horse battery staple",
                },
            )
            assert reset.status_code == 204

            replay = await client.post(
                "/api/v1/auth/password-reset/confirm",
                json={
                    "token": reset_token,
                    "new_password": "another correct horse battery staple",
                },
            )
            assert replay.status_code == 400
            assert replay.json()["error"]["code"] == "AUTH_ACTION_TOKEN_INVALID"

            stale_access = await client.get(
                "/api/v1/auth/me",
                headers={"Authorization": f"Bearer {old_access}"},
            )
            assert stale_access.status_code == 401

            old_password = await client.post(
                "/api/v1/auth/login",
                json={"email": "owner@example.com", "password": "correct horse battery staple"},
            )
            new_password = await client.post(
                "/api/v1/auth/login",
                json={
                    "email": "owner@example.com",
                    "password": "new correct horse battery staple",
                },
            )
            assert old_password.status_code == 401
            assert new_password.status_code == 200

        await app.state.database.dispose()

    asyncio.run(scenario())


def test_one_device_can_be_revoked_without_logging_out_other_device() -> None:
    async def scenario() -> None:
        app = build_phase2_test_app()
        await prepare_database(app)
        transport = ASGITransport(app=app)
        headers = {"Origin": "https://testserver"}
        async with (
            AsyncClient(
                transport=transport,
                base_url="https://testserver",
                headers=headers,
            ) as safe_device,
            AsyncClient(
                transport=transport,
                base_url="https://testserver",
                headers=headers,
            ) as stolen_device,
        ):
            await signup(safe_device)
            verify_token = await raw_action_token(app, "verify_email")
            await safe_device.post("/api/v1/auth/verify-email", json={"token": verify_token})
            credentials = {
                "email": "owner@example.com",
                "password": "correct horse battery staple",
            }
            safe_login = await safe_device.post(
                "/api/v1/auth/login",
                json={**credentials, "device_name": "안전한 노트북"},
            )
            stolen_login = await stolen_device.post(
                "/api/v1/auth/login",
                json={**credentials, "device_name": "도난 노트북"},
            )
            safe_auth = {"Authorization": f"Bearer {safe_login.json()['access_token']}"}
            stolen_auth = {"Authorization": f"Bearer {stolen_login.json()['access_token']}"}

            sessions = await safe_device.get("/api/v1/auth/sessions", headers=safe_auth)
            assert sessions.status_code == 200
            by_name = {item["device_name"]: item for item in sessions.json()["sessions"]}
            assert set(by_name) == {"안전한 노트북", "도난 노트북"}

            revoked = await safe_device.delete(
                f"/api/v1/auth/sessions/{by_name['도난 노트북']['id']}",
                headers=safe_auth,
            )
            assert revoked.status_code == 204

            blocked_access = await stolen_device.get("/api/v1/auth/me", headers=stolen_auth)
            blocked_refresh = await stolen_device.post("/api/v1/auth/refresh")
            safe_access = await safe_device.get("/api/v1/auth/me", headers=safe_auth)
            assert blocked_access.status_code == 401
            assert blocked_refresh.status_code == 401
            assert safe_access.status_code == 200

            async with app.state.database.session_factory() as session:
                stored_sessions = (await session.execute(select(AuthSession))).scalars().all()
                assert sum(item.revoked_at is not None for item in stored_sessions) == 1

        await app.state.database.dispose()

    asyncio.run(scenario())


def test_password_change_requires_current_password_and_logs_out_every_device() -> None:
    async def scenario() -> None:
        app = build_phase2_test_app()
        await prepare_database(app)
        transport = ASGITransport(app=app)
        async with AsyncClient(
            transport=transport,
            base_url="https://testserver",
            headers={"Origin": "https://testserver"},
        ) as client:
            await signup(client)
            verify_token = await raw_action_token(app, "verify_email")
            await client.post("/api/v1/auth/verify-email", json={"token": verify_token})
            login = await client.post(
                "/api/v1/auth/login",
                json={
                    "email": "owner@example.com",
                    "password": "correct horse battery staple",
                },
            )
            authorization = {"Authorization": f"Bearer {login.json()['access_token']}"}

            rejected = await client.post(
                "/api/v1/auth/password/change",
                headers=authorization,
                json={
                    "current_password": "wrong password",
                    "new_password": "new correct horse battery staple",
                },
            )
            assert rejected.status_code == 401

            changed = await client.post(
                "/api/v1/auth/password/change",
                headers=authorization,
                json={
                    "current_password": "correct horse battery staple",
                    "new_password": "new correct horse battery staple",
                },
            )
            assert changed.status_code == 204
            stale = await client.get("/api/v1/auth/me", headers=authorization)
            assert stale.status_code == 401

        await app.state.database.dispose()

    asyncio.run(scenario())


def test_disabled_user_cannot_login_or_refresh() -> None:
    async def scenario() -> None:
        app = build_phase2_test_app()
        await prepare_database(app)
        transport = ASGITransport(app=app)
        async with AsyncClient(
            transport=transport,
            base_url="https://testserver",
            headers={"Origin": "https://testserver"},
        ) as client:
            await signup(client)
            verify_token = await raw_action_token(app, "verify_email")
            await client.post("/api/v1/auth/verify-email", json={"token": verify_token})
            login = await client.post(
                "/api/v1/auth/login",
                json={
                    "email": "owner@example.com",
                    "password": "correct horse battery staple",
                },
            )
            assert login.status_code == 200

            async with app.state.database.session_factory() as session:
                user = (await session.execute(select(User))).scalar_one()
                user.status = "disabled"
                await session.commit()

            rejected_login = await client.post(
                "/api/v1/auth/login",
                json={
                    "email": "owner@example.com",
                    "password": "correct horse battery staple",
                },
            )
            rejected_refresh = await client.post("/api/v1/auth/refresh")
            assert rejected_login.status_code == 401
            assert rejected_refresh.status_code == 401

        await app.state.database.dispose()

    asyncio.run(scenario())


def test_email_outbox_retries_without_rolling_back_signup() -> None:
    class FailingSender:
        async def send(self, **_message) -> None:
            raise TimeoutError("provider timeout")

    class RecordingSender:
        def __init__(self) -> None:
            self.messages: list[dict[str, str]] = []

        async def send(self, **message) -> None:
            self.messages.append(message)

    async def scenario() -> None:
        app = build_phase2_test_app()
        await prepare_database(app)
        transport = ASGITransport(app=app)
        async with AsyncClient(
            transport=transport,
            base_url="https://testserver",
            headers={"Origin": "https://testserver"},
        ) as client:
            created = await signup(client)
            assert created.status_code == 201

        processor = AuthOutboxProcessor(
            app.state.database.session_factory,
            app.state.auth_security,
            FailingSender(),
            app.state.config,
        )
        assert await processor.process_one() is True

        async with app.state.database.session_factory() as session:
            user = (await session.execute(select(User))).scalar_one()
            event = (await session.execute(select(AuthOutboxEvent))).scalar_one()
            assert user.status == "pending_verification"
            assert event.status == "pending"
            assert event.attempt_count == 1
            assert event.last_error == "TimeoutError"
            event.next_attempt_at = datetime.now(UTC)
            await session.commit()

        sender = RecordingSender()
        processor.sender = sender
        assert await processor.process_one() is True
        assert len(sender.messages) == 1
        assert "#verify_token=" in sender.messages[0]["action_url"]
        assert "?verify_token=" not in sender.messages[0]["action_url"]

        async with app.state.database.session_factory() as session:
            event = (await session.execute(select(AuthOutboxEvent))).scalar_one()
            action = (await session.execute(select(ActionToken))).scalar_one()
            assert event.status == "completed"
            raw_token = app.state.auth_security.create_action_token(
                token_id=action.id,
                purpose=action.purpose,
            )
            # [Design Intent] The delivery event is durable, but a database dump
            # still contains only the action-token digest rather than the raw link.
            assert raw_token not in repr(event.__dict__)

        await app.state.database.dispose()

    asyncio.run(scenario())


def test_postgres_rate_limit_is_atomic_across_concurrent_workers() -> None:
    async def scenario() -> None:
        app = build_phase2_test_app()
        await prepare_database(app)
        first_worker = PostgresAuthRateLimiter(app.state.database.session_factory)
        second_worker = PostgresAuthRateLimiter(app.state.database.session_factory)

        results = await asyncio.gather(
            first_worker.check(scope="login", identity="203.0.113.10", limit=1, window=60),
            second_worker.check(scope="login", identity="203.0.113.10", limit=1, window=60),
            return_exceptions=True,
        )
        failures = [result for result in results if isinstance(result, ApiError)]
        assert len(failures) == 1
        assert failures[0].code == "AUTH_RATE_LIMITED"

        async with app.state.database.session_factory() as session:
            bucket = (await session.execute(select(AuthRateLimitBucket))).scalar_one()
            assert bucket.count == 2

        await app.state.database.dispose()

    asyncio.run(scenario())
