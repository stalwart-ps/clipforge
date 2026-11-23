from datetime import datetime, timezone
from sqlalchemy import DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column
from app.core.db import Base


class AppSettings(Base):
    __tablename__ = "app_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    hardware_preset: Mapped[str] = mapped_column(String, default="balanced")
    whisper_model: Mapped[str] = mapped_column(String, default="small")
    ollama_model: Mapped[str] = mapped_column(String, default="qwen2.5:7b")
    encoder: Mapped[str] = mapped_column(String, default="h264_nvenc")
    js_runtime: Mapped[str] = mapped_column(String, default="auto")

    # yt-dlp & cookies
    cookies_browser: Mapped[str | None] = mapped_column(String, nullable=True)
    cookies_file_path: Mapped[str | None] = mapped_column(String, nullable=True)
    po_token: Mapped[str | None] = mapped_column(String, nullable=True)

    # Defaults for clipping
    min_clip_duration_sec: Mapped[int] = mapped_column(Integer, default=15)
    max_clip_duration_sec: Mapped[int] = mapped_column(Integer, default=60)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
