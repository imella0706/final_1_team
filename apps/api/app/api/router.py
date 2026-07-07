from fastapi import APIRouter

from app.modules.ad_copy.router import router as ad_copy_router
from app.modules.model_runtime.router import router as model_runtime_router

api_router = APIRouter()
api_router.include_router(ad_copy_router)
api_router.include_router(model_runtime_router)
