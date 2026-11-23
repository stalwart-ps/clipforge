from typing import Literal

from pydantic import Field

from app.core.schemas import APISchema
from app.projects.schemas import TranscriptSegment


CaptionPreset = Literal[
    "hormozi_pop", "karaoke_highlight", "minimal_clean", "gaming_neon", "boxed_pill"
]
CaptionAnimation = Literal["none", "pop", "highlight", "bounce"]


class CaptionConfig(APISchema):
    preset: CaptionPreset = "hormozi_pop"
    font_name: str | None = Field(None, min_length=1, max_length=100)
    font_size: int | None = Field(None, ge=12, le=180)
    primary_color: str | None = Field(None, pattern=r"^#[0-9A-Fa-f]{6}$")
    highlight_color: str | None = Field(None, pattern=r"^#[0-9A-Fa-f]{6}$")
    outline_color: str | None = Field(None, pattern=r"^#[0-9A-Fa-f]{6}$")
    outline_width: float | None = Field(None, ge=0.0, le=16.0)
    shadow_depth: float | None = Field(None, ge=0.0, le=12.0)
    margin_v: int | None = Field(None, ge=0, le=2000)
    position_y_percent: float | None = Field(None, ge=0.0, le=100.0)
    max_words_per_line: int | None = Field(None, ge=1, le=6)
    all_caps: bool | None = None
    animation: CaptionAnimation | None = None
    profanity_mask: bool | None = None


class CaptionGenerateRequest(APISchema):
    config: CaptionConfig = Field(default_factory=CaptionConfig)


class CaptionRenderRequest(APISchema):
    start_sec: float = Field(0.0, ge=0.0)
    end_sec: float | None = Field(None, gt=0.0)
    config: CaptionConfig = Field(default_factory=CaptionConfig)


class CaptionGenerateResponse(APISchema):
    ass_path: str
    event_count: int


class CaptionRenderResponse(APISchema):
    output_path: str
    encoder_used: str
    event_count: int


class CaptionTranscriptUpdateRequest(APISchema):
    segments: list[TranscriptSegment]
    config: CaptionConfig = Field(default_factory=CaptionConfig)

