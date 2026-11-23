import os
from pathlib import Path
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Base workspace directory (repository root)
ROOT_DIR = Path(__file__).resolve().parent.parent.parent.parent
BACKEND_DIR = Path(__file__).resolve().parent.parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ROOT_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "ClipForge Local"
    app_version: str = "0.1.0"
    debug: bool = False

    host: str = "127.0.0.1"
    port: int = 8000

    # Paths
    root_dir: Path = ROOT_DIR
    backend_dir: Path = BACKEND_DIR
    database_url: str = f"sqlite+aiosqlite:///{ROOT_DIR / 'clipforge.db'}"
    cache_dir: Path = ROOT_DIR / "workspace_cache"
    temp_dir: Path = ROOT_DIR / "workspace_cache" / "temp"
    frontend_dist_dir: Path = ROOT_DIR / "frontend" / "dist"

    # Services
    ollama_url: str = "http://localhost:11434"
    cors_origins: list[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
        "http://app.local",
    ]


settings = Settings()

# Ensure critical workspace directories exist
settings.cache_dir.mkdir(parents=True, exist_ok=True)
settings.temp_dir.mkdir(parents=True, exist_ok=True)
