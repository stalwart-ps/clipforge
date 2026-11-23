from pydantic import Field
from app.core.schemas import APISchema


class SettingsRead(APISchema):
    id: int = 1
    hardware_preset: str
    whisper_model: str
    ollama_model: str
    encoder: str
    js_runtime: str
    cookies_browser: str | None = None
    cookies_file_path: str | None = None
    po_token: str | None = None
    min_clip_duration_sec: int = 15
    max_clip_duration_sec: int = 60


class SettingsUpdate(APISchema):
    hardware_preset: str | None = None
    whisper_model: str | None = None
    ollama_model: str | None = None
    encoder: str | None = None
    js_runtime: str | None = None
    cookies_browser: str | None = None
    cookies_file_path: str | None = None
    po_token: str | None = None
    min_clip_duration_sec: int | None = Field(default=None, ge=5, le=120)
    max_clip_duration_sec: int | None = Field(default=None, ge=10, le=300)


class CacheStatsResponse(APISchema):
    cache_dir: str
    total_bytes: int
    total_mb: float
    file_count: int


class CleanCacheResponse(APISchema):
    reclaimed_bytes: int
    reclaimed_mb: float
    files_deleted: int
    message: str
