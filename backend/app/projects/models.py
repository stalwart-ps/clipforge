from datetime import datetime, timezone
from sqlalchemy import DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from app.core.db import Base


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    title: Mapped[str] = mapped_column(String(255), default="Untitled Video")
    source_type: Mapped[str] = mapped_column(String(32))  # 'url' or 'local'
    source_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    download_mode: Mapped[str] = mapped_column(String(32), default="full")  # 'full', 'fast_vod', 'local'

    status: Mapped[str] = mapped_column(String(32), default="pending")
    # 'pending', 'downloading', 'extracting_audio', 'analyzing_engagement', 'ready', 'error', 'cancelled'
    progress_percent: Mapped[float] = mapped_column(Float, default=0.0)
    current_stage: Mapped[str] = mapped_column(String(255), default="Initialized")

    # Media paths (relative to workspace or absolute)
    video_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    audio_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)  # 16kHz mono WAV
    thumbnail_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)

    # Video properties
    duration_sec: Mapped[float | None] = mapped_column(Float, nullable=True)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fps: Mapped[float | None] = mapped_column(Float, nullable=True)
    file_size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Engagement Signals (Heatmap, Comment Timestamps, Live Chat, Audio Energy)
    engagement_signals_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Phase 3 Caching: Transcripts, Scene Cuts, and Ranked Candidate Clips
    transcript_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    scene_cuts_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    candidate_clips_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    whisper_model_used: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ollama_model_used: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ai_clip_recommendation: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Process tracking for cancellation
    active_pid: Mapped[int | None] = mapped_column(Integer, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
