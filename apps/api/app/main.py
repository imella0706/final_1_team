from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.routing import register_router
from app.extensions.ad_content.router import router as ad_content_router
from app.modules.ad_copy.router import router as ad_copy_router
from app.modules.model_runtime.router import router as model_runtime_router


def create_app() -> FastAPI:
    app = FastAPI(title=settings.app_name)
    app.add_middleware(
        CORSMiddleware,
<<<<<<< HEAD
        allow_origins=["*"],
=======
        allow_origins=[
            "http://34.55.162.157:5501",
            "http://localhost:5501",
            "http://127.0.0.1:5501",
            "http://localhost:5502",
            "http://127.0.0.1:5502",
        ],
>>>>>>> origin/dev
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    register_router(app, ad_copy_router, prefix=settings.api_prefix)
    register_router(app, model_runtime_router, prefix=settings.api_prefix)
    register_router(app, ad_content_router, prefix=settings.api_prefix)

    @app.get("/health", tags=["health"])
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
