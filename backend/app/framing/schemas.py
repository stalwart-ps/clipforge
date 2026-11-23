"""Phase 4 — Pydantic schemas for framing configs, region boxes, and saved profiles."""

from __future__ import annotations
from typing import Literal
from pydantic import Field
from app.core.schemas import APISchema


# ---------------------------------------------------------------------------
# Region Box — normalized 0.0–1.0 fractions of the *source* video dimensions
# ---------------------------------------------------------------------------
class RegionBox(APISchema):
    x: float = Field(0.0, ge=0.0, le=1.0, description="Left edge fraction")
    y: float = Field(0.0, ge=0.0, le=1.0, description="Top edge fraction")
    w: float = Field(1.0, gt=0.0, le=1.0, description="Width fraction")
    h: float = Field(1.0, gt=0.0, le=1.0, description="Height fraction")


# ---------------------------------------------------------------------------
# Watermark Config
# ---------------------------------------------------------------------------
class WatermarkConfig(APISchema):
    path: str | None = None          # Absolute path to PNG on server
    corner: Literal["top_left", "top_right", "bottom_left", "bottom_right"] = "bottom_right"
    scale: float = Field(0.1, gt=0.0, le=1.0)   # Fraction of output width
    opacity: float = Field(0.8, gt=0.0, le=1.0)


# ---------------------------------------------------------------------------
# Full Framing Configuration
# ---------------------------------------------------------------------------
FramingMode = Literal["gaming", "podcast", "talking_head", "screen_presenter", "reaction"]
AspectRatio = Literal["9:16", "1:1", "16:9"]
LayoutTemplate = Literal["split_vertical", "fullscreen_crop", "blurred_fill", "pip"]


class FramingConfig(APISchema):
    framing_mode: FramingMode = "gaming"
    aspect_ratio: AspectRatio = "9:16"
    layout_template: LayoutTemplate = "split_vertical"

    # Crop boxes (normalized 0–1)
    facecam_box: RegionBox | None = None
    gameplay_box: RegionBox | None = None

    # Split ratio for split_vertical (top pane %, e.g. 35 → 35/65 split)
    split_ratio: int = Field(35, ge=10, le=90)

    # Watermark
    watermark: WatermarkConfig | None = None
    # `None` means let Gaming Mode use its full-frame no-face fallback.
    face_detected: bool | None = None


# ---------------------------------------------------------------------------
# Saved Profile CRUD
# ---------------------------------------------------------------------------
class ProfileCreate(APISchema):
    name: str = Field(..., min_length=1, max_length=255)
    framing_mode: FramingMode = "gaming"
    aspect_ratio: AspectRatio = "9:16"
    layout_template: LayoutTemplate = "split_vertical"
    facecam_box: RegionBox | None = None
    gameplay_box: RegionBox | None = None
    split_ratio: int = Field(35, ge=10, le=90)
    watermark: WatermarkConfig | None = None
    ollama_prompt: str | None = None
    caption_style: str = "hormozi_pop"


class ProfileUpdate(APISchema):
    name: str | None = None
    framing_mode: FramingMode | None = None
    aspect_ratio: AspectRatio | None = None
    layout_template: LayoutTemplate | None = None
    facecam_box: RegionBox | None = None
    gameplay_box: RegionBox | None = None
    split_ratio: int | None = None
    watermark: WatermarkConfig | None = None
    ollama_prompt: str | None = None
    caption_style: str | None = None


class ProfileRead(APISchema):
    id: str
    name: str
    framing_mode: str
    aspect_ratio: str
    layout_template: str
    facecam_box: RegionBox | None = None
    gameplay_box: RegionBox | None = None
    split_ratio: int
    watermark: WatermarkConfig | None = None
    ollama_prompt: str | None = None
    caption_style: str
    created_at: str
    updated_at: str


# ---------------------------------------------------------------------------
# Auto-Detect Regions API response
# ---------------------------------------------------------------------------
class AutoDetectResult(APISchema):
    facecam_box: RegionBox | None = None
    gameplay_box: RegionBox | None = None
    face_count: int = 0
    face_confidence: float = 0.0
    # Suggested mode based on detected regions
    mode_suggestion: FramingMode = "gaming"
    message: str = ""


# ---------------------------------------------------------------------------
# Render Request/Response
# ---------------------------------------------------------------------------
class RenderRequest(APISchema):
    clip_id: str | None = None          # CandidateClip id; if None, render full video
    start_sec: float = Field(0.0, ge=0.0)
    end_sec: float = Field(60.0, ge=1.0)
    framing_config: FramingConfig = Field(default_factory=FramingConfig)
    profile_id: str | None = None       # Load saved profile (overrides framing_config if set)
    output_filename: str | None = None  # Optional custom output name


class RenderResponse(APISchema):
    project_id: str
    output_path: str
    output_filename: str
    duration_sec: float
    framing_mode: str
    encoder_used: str   # 'h264_nvenc' or 'libx264'
    message: str = "Render queued"
