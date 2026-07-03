from fastapi import APIRouter

from app.modules.ad_copy.router import router as ad_copy_router

api_router = APIRouter()
api_router.include_router(ad_copy_router)
