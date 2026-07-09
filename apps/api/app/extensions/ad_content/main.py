from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.core.config import settings
from app.extensions.ad_content.router import router as ad_content_router
from app.modules.model_runtime.router import router as model_runtime_router


def create_app() -> FastAPI:
    app = FastAPI(title=f"{settings.app_name} Ad Content Extension")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(api_router, prefix=settings.api_prefix)
    app.include_router(ad_content_router, prefix=settings.api_prefix)
    app.include_router(model_runtime_router, prefix="/api")

    @app.get("/health", tags=["health"])
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
