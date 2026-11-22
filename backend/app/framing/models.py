"""Phase 4 — Framing SQLAlchemy model for Saved Channel/Streamer Profiles."""

from datetime import datetime, timezone
from sqlalchemy import DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from app.core.db import Base


class SavedProfile(Base):
    __tablename__ = "saved_profiles"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(255))  # e.g. "My Gaming Channel"
    framing_mode: Mapped[str] = mapped_column(String(32), default="gaming")
    # 'gaming' | 'podcast' | 'talking_head' | 'screen_presenter' | 'reaction'

    aspect_ratio: Mapped[str] = mapped_column(String(16), default="9:16")
    # '9:16' | '1:1' | '16:9'

    layout_template: Mapped[str] = mapped_column(String(32), default="split_vertical")
    # 'split_vertical' | 'fullscreen_crop' | 'blurred_fill' | 'pip'

    # Crop region boxes (x, y, w, h as 0.0–1.0 fractions of source dimensions)
    facecam_box_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    # {"x": 0.0, "y": 0.0, "w": 0.3, "h": 0.3}

    gameplay_box_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    # {"x": 0.0, "y": 0.3, "w": 1.0, "h": 0.7}

    # Watermark config
    watermark_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    watermark_corner: Mapped[str] = mapped_column(String(16), default="bottom_right")
    # 'top_left' | 'top_right' | 'bottom_left' | 'bottom_right'
    watermark_scale: Mapped[float] = mapped_column(Float, default=0.1)  # fraction of output width
    watermark_opacity: Mapped[float] = mapped_column(Float, default=0.8)

    # Caption / Ollama prompt override for this channel profile
    ollama_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    caption_style: Mapped[str] = mapped_column(String(32), default="hormozi_pop")

    # Split ratio for split_vertical layout (percent for top pane, e.g. 35 = 35% top)
    split_ratio: Mapped[int] = mapped_column(Integer, default=35)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
