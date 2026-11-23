from datetime import datetime, timezone
from sqlalchemy import DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from app.core.db import Base


class WorkspaceConfig(Base):
    __tablename__ = "workspace_config"

    project_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    layout_config_json: Mapped[str] = mapped_column(Text, default="{}")
    caption_config_json: Mapped[str] = mapped_column(Text, default="{}")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
