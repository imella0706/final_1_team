import asyncio
from collections.abc import AsyncIterator
from contextlib import suppress
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from sqlalchemy import text

from app.core.config import Settings, settings
from app.core.errors import register_exception_handlers
from app.core.observability import register_request_logging
from app.core.routing import register_router
from app.db.session import Database
from app.extensions.ad_content.router import router as ad_content_router
from app.modules.ad_copy.router import router as ad_copy_router
from app.modules.auth.dependencies import get_current_user
from app.modules.auth.outbox import AuthOutboxProcessor, SmtpAuthEmailSender
from app.modules.auth.rate_limit import InMemoryAuthRateLimiter, PostgresAuthRateLimiter
from app.modules.auth.router import router as auth_router
from app.modules.auth.security import AuthSecurity
from app.modules.model_runtime.router import router as model_runtime_router


def create_app(
    config: Settings | None = None,
    *,
    title: str | None = None,
    include_legacy_runtime_routes: bool = False,
) -> FastAPI:
    app_config = config or settings
    database = Database(app_config.database_url)
    auth_security = AuthSecurity(app_config)
    outbox_processor = None
    if app_config.auth_email_delivery_enabled:
        outbox_processor = AuthOutboxProcessor(
            database.session_factory,
            auth_security,
            SmtpAuthEmailSender(app_config),
            app_config,
        )

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        # [Design Intent] Database connections are process-scoped and released on
        # graceful shutdown; schema changes remain an explicit Alembic operation.
        outbox_task = (
            asyncio.create_task(outbox_processor.run(), name="auth-email-outbox")
            if outbox_processor
            else None
        )
        try:
            yield
        finally:
            if outbox_task:
                outbox_task.cancel()
                with suppress(asyncio.CancelledError):
                    await outbox_task
            await database.dispose()

    app = FastAPI(title=title or app_config.app_name, lifespan=lifespan)
    app.state.config = app_config
    app.state.database = database
    app.state.auth_security = auth_security
    app.state.auth_outbox_processor = outbox_processor
    app.state.auth_rate_limiter = (
        PostgresAuthRateLimiter(database.session_factory)
        if app_config.auth_rate_limit_backend == "postgres"
        else InMemoryAuthRateLimiter()
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=app_config.allowed_web_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
        expose_headers=["X-Request-ID"],
    )
    register_request_logging(app)
    register_exception_handlers(app)

    register_router(app, auth_router, prefix=app_config.api_prefix)

    # [Design Intent] Existing model endpoints incur compute cost and may expose
    # generated business data, so every route is authenticated at registration.
    protected = [Depends(get_current_user)]
    register_router(app, ad_copy_router, prefix=app_config.api_prefix, dependencies=protected)
    register_router(app, model_runtime_router, prefix=app_config.api_prefix, dependencies=protected)
    register_router(app, ad_content_router, prefix=app_config.api_prefix, dependencies=protected)
    if include_legacy_runtime_routes:
        register_router(app, model_runtime_router, prefix="/api", dependencies=protected)

    @app.get("/health", tags=["health"])
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/ready", tags=["health"])
    async def ready() -> dict[str, str]:
        try:
            async with database.engine.connect() as connection:
                await connection.execute(text("SELECT 1"))
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="database unavailable",
            ) from exc
        return {"status": "ready"}

    @app.get("/metrics", include_in_schema=False, response_class=PlainTextResponse)
    async def metrics() -> str:
        return app.state.auth_metrics.render_prometheus()

    return app


app = create_app()
