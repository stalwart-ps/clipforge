"""API models for Phase 6 export requests and queue state."""

from typing import Literal

from pydantic import Field

from app.core.schemas import APISchema
from app.captions.schemas import CaptionConfig
from app.framing.schemas import FramingConfig


class ExportClip(APISchema):
    clip_id: str | None = None
    title: str = Field(default="Clip", min_length=1, max_length=255)
    hook_summary: str = ""
    suggested_hashtags: list[str] = []
    start_sec: float = Field(..., ge=0)
    end_sec: float = Field(..., gt=0)


class ExportSidecars(APISchema):
    srt: bool = False
    ass: bool = False
    metadata_json: bool = False
    metadata_txt: bool = False


class ExportOptions(APISchema):
    normalize_loudness: bool = False
    remove_silence: bool = False
    silence_threshold_db: float = Field(default=-35.0, ge=-80.0, le=-10.0)
    silence_min_duration_sec: float = Field(default=0.6, ge=0.1, le=10.0)
    sidecars: ExportSidecars = Field(default_factory=ExportSidecars)
    caption_config: CaptionConfig = Field(default_factory=CaptionConfig)
    framing_config: FramingConfig = Field(default_factory=FramingConfig)


class BatchExportRequest(ExportOptions):
    clips: list[ExportClip] = Field(..., min_length=1, max_length=100)


class PreviewRequest(ExportOptions):
    start_sec: float = Field(..., ge=0)
    end_sec: float = Field(..., gt=0)


class ExportJobRead(APISchema):
    id: str
    project_id: str
    status: Literal["queued", "running", "completed", "cancelled", "error"]
    progress_percent: float = 0.0
    current_clip: str | None = None
    completed_clips: int = 0
    total_clips: int = 0
    output_files: list[str] = []
    error: str | None = None
    created_at: str
    updated_at: str


class ExportJobCreated(APISchema):
    job: ExportJobRead


class ExportCancelResponse(APISchema):
    success: bool
    message: str

