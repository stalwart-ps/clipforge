from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.db import get_db_session
from app.settings.schemas import CacheStatsResponse, CleanCacheResponse, SettingsRead, SettingsUpdate
from app.settings.service import SettingsService

router = APIRouter(prefix="/api", tags=["settings"])


@router.get("/settings", response_model=SettingsRead, status_code=status.HTTP_200_OK)
async def get_settings(session: AsyncSession = Depends(get_db_session)) -> SettingsRead:
    item = await SettingsService.get_or_create_settings(session)
    return SettingsRead.model_validate(item)


@router.put("/settings", response_model=SettingsRead, status_code=status.HTTP_200_OK)
async def update_settings(
    payload: SettingsUpdate, session: AsyncSession = Depends(get_db_session)
) -> SettingsRead:
    item = await SettingsService.update_settings(session, payload)
    return SettingsRead.model_validate(item)


@router.get("/cache/stats", response_model=CacheStatsResponse, status_code=status.HTTP_200_OK)
async def get_cache_stats() -> CacheStatsResponse:
    return SettingsService.get_cache_stats()


@router.post("/cache/clean", response_model=CleanCacheResponse, status_code=status.HTTP_200_OK)
async def clean_cache() -> CleanCacheResponse:
    return SettingsService.clean_cache()
