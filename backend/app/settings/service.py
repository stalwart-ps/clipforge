import os
from pathlib import Path
import shutil
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.config import settings
from app.settings.models import AppSettings
from app.settings.schemas import CacheStatsResponse, CleanCacheResponse, SettingsUpdate

PRESET_DEFAULTS = {
    "lite": {
        "whisper_model": "base",
        "ollama_model": "qwen2.5:3b",
        "encoder": "libx264",
    },
    "balanced": {
        "whisper_model": "small",
        "ollama_model": "qwen2.5:7b",
        "encoder": "h264_nvenc",
    },
    "pro": {
        "whisper_model": "large-v3-turbo",
        "ollama_model": "qwen2.5:14b",
        "encoder": "h264_nvenc",
    },
}


class SettingsService:
    @staticmethod
    async def get_or_create_settings(session: AsyncSession) -> AppSettings:
        query = select(AppSettings).where(AppSettings.id == 1)
        result = await session.execute(query)
        item = result.scalar_one_or_none()

        if item is None:
            item = AppSettings(
                id=1,
                hardware_preset="balanced",
                whisper_model="small",
                ollama_model="qwen2.5:7b",
                encoder="h264_nvenc",
                js_runtime="auto",
                min_clip_duration_sec=15,
                max_clip_duration_sec=60,
            )
            session.add(item)
            await session.commit()
            await session.refresh(item)

        return item

    @classmethod
    async def update_settings(cls, session: AsyncSession, data: SettingsUpdate) -> AppSettings:
        item = await cls.get_or_create_settings(session)
        update_data = data.model_dump(exclude_unset=True)

        # If user changed hardware preset and didn't specify individual models, apply defaults
        if "hardware_preset" in update_data and update_data["hardware_preset"] in PRESET_DEFAULTS:
            preset = update_data["hardware_preset"]
            defaults = PRESET_DEFAULTS[preset]
            if "whisper_model" not in update_data:
                item.whisper_model = defaults["whisper_model"]
            if "ollama_model" not in update_data:
                item.ollama_model = defaults["ollama_model"]
            if "encoder" not in update_data:
                item.encoder = defaults["encoder"]

        for key, value in update_data.items():
            setattr(item, key, value)

        await session.commit()
        await session.refresh(item)
        return item

    @staticmethod
    def get_cache_stats() -> CacheStatsResponse:
        cache_path = settings.cache_dir
        total_bytes = 0
        file_count = 0

        if cache_path.exists():
            for root, _, files in os.walk(cache_path):
                for f in files:
                    file_path = Path(root) / f
                    try:
                        total_bytes += file_path.stat().st_size
                        file_count += 1
                    except OSError:
                        pass

        total_mb = round(total_bytes / (1024 * 1024), 2)
        return CacheStatsResponse(
            cache_dir=str(cache_path),
            total_bytes=total_bytes,
            total_mb=total_mb,
            file_count=file_count,
        )

    @staticmethod
    def clean_cache() -> CleanCacheResponse:
        temp_path = settings.temp_dir
        cache_path = settings.cache_dir
        reclaimed_bytes = 0
        files_deleted = 0

        # Clean all items inside temp_path
        if temp_path.exists():
            for item in temp_path.iterdir():
                try:
                    if item.is_file():
                        size = item.stat().st_size
                        item.unlink()
                        reclaimed_bytes += size
                        files_deleted += 1
                    elif item.is_dir():
                        dir_size = sum(f.stat().st_size for f in item.glob("**/*") if f.is_file())
                        shutil.rmtree(item)
                        reclaimed_bytes += dir_size
                        files_deleted += 1
                except OSError:
                    pass

        # Also clean any orphan .tmp, .part, .wav temporary files in cache_dir root
        if cache_path.exists():
            for item in cache_path.glob("*.tmp"):
                try:
                    reclaimed_bytes += item.stat().st_size
                    item.unlink()
                    files_deleted += 1
                except OSError:
                    pass

        temp_path.mkdir(parents=True, exist_ok=True)
        reclaimed_mb = round(reclaimed_bytes / (1024 * 1024), 2)

        return CleanCacheResponse(
            reclaimed_bytes=reclaimed_bytes,
            reclaimed_mb=reclaimed_mb,
            files_deleted=files_deleted,
            message=f"Cleaned {files_deleted} temporary files, reclaimed {reclaimed_mb} MB.",
        )
