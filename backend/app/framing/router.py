"""Phase 4 — Framing API Router.

Endpoints:
  GET  /api/profiles                     → list all saved profiles
  POST /api/profiles                     → create new profile
  GET  /api/profiles/{id}                → get profile
  PUT  /api/profiles/{id}                → update profile
  DEL  /api/profiles/{id}                → delete profile

  POST /api/projects/{id}/auto-detect-regions  → run vision_worker, return boxes
  POST /api/projects/{id}/render               → render clip with given config
"""

from __future__ import annotations
import asyncio
import json
import sys
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db import get_db_session
from app.framing.auto_detect import auto_detect_regions, track_active_speaker
from app.framing.schemas import (
    AutoDetectResult,
    FramingConfig,
    ProfileCreate,
    ProfileRead,
    ProfileUpdate,
    RegionBox,
    RenderRequest,
    RenderResponse,
)
from app.framing.service import ProfileService
from app.media.ffmpeg import FFmpegHelper
from app.projects.service import ProjectService

profiles_router = APIRouter(prefix="/api/profiles", tags=["profiles"])
framing_router = APIRouter(prefix="/api/projects", tags=["framing"])
assets_router = APIRouter(prefix="/api/framing", tags=["framing"])


@assets_router.post("/watermark")
async def upload_watermark(file: UploadFile = File(...)) -> dict[str, str]:
    """Store a local PNG watermark and return its path for render/profile configs."""
    if Path(file.filename or "").suffix.lower() != ".png":
        raise HTTPException(status_code=415, detail="Watermark must be a PNG image")
    data = await file.read(8 * 1024 * 1024 + 1)
    if len(data) > 8 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Watermark must be 8 MB or smaller")
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise HTTPException(status_code=415, detail="Uploaded file is not a valid PNG")
    folder = settings.cache_dir / "watermarks"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{__import__('uuid').uuid4().hex}.png"
    path.write_bytes(data)
    return {"path": str(path)}


# ---------------------------------------------------------------------------
# Saved Profiles CRUD
# ---------------------------------------------------------------------------

@profiles_router.get("", response_model=list[ProfileRead])
async def list_profiles(session: AsyncSession = Depends(get_db_session)) -> list[ProfileRead]:
    return await ProfileService.list_profiles(session)


@profiles_router.post("", response_model=ProfileRead, status_code=status.HTTP_201_CREATED)
async def create_profile(
    payload: ProfileCreate, session: AsyncSession = Depends(get_db_session)
) -> ProfileRead:
    return await ProfileService.create_profile(session, payload)


@profiles_router.get("/{profile_id}", response_model=ProfileRead)
async def get_profile(
    profile_id: str, session: AsyncSession = Depends(get_db_session)
) -> ProfileRead:
    return await ProfileService.get_profile(session, profile_id)


@profiles_router.put("/{profile_id}", response_model=ProfileRead)
async def update_profile(
    profile_id: str,
    payload: ProfileUpdate,
    session: AsyncSession = Depends(get_db_session),
) -> ProfileRead:
    return await ProfileService.update_profile(session, profile_id, payload)


@profiles_router.delete("/{profile_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_profile(
    profile_id: str, session: AsyncSession = Depends(get_db_session)
) -> None:
    await ProfileService.delete_profile(session, profile_id)


# ---------------------------------------------------------------------------
# On-demand single-frame JPEG extractor (for Canvas preview)
# ---------------------------------------------------------------------------

@framing_router.get("/{project_id}/frame")
async def get_project_frame(
    project_id: str,
    t: float = Query(default=1.0, ge=0.0, description="Seek time in seconds"),
    session: AsyncSession = Depends(get_db_session),
):
    """
    Extract a single JPEG frame at time `t` seconds using FFmpeg fast input-seek.
    Used by the Canvas Layout Studio for the draggable region picker preview.
    """
    project = await ProjectService.get_project(session, project_id)
    if not project.video_path or not Path(project.video_path).exists():
        raise HTTPException(status_code=404, detail="Video file not found")

    # Clamp seek time within video duration
    if project.duration_sec:
        t = max(0.0, min(t, project.duration_sec - 0.5))

    out_jpg = settings.temp_dir / f"{project_id}_frame_{int(t * 100)}.jpg"
    success = await FFmpegHelper.extract_thumbnail(Path(project.video_path), out_jpg, t)
    if not success:
        raise HTTPException(status_code=500, detail="Frame extraction failed")

    return FileResponse(str(out_jpg), media_type="image/jpeg")


# ---------------------------------------------------------------------------
# Auto-Detect Regions (MediaPipe vision subprocess)
# ---------------------------------------------------------------------------

@framing_router.post("/{project_id}/auto-detect-regions", response_model=AutoDetectResult)
async def auto_detect_project_regions(
    project_id: str,
    t: float = Query(default=5.0, ge=0.0, description="Frame time for detection"),
    framing_mode: str = Query(default="gaming", description="Framing mode for smart person expansion"),
    tightness: str = Query(default="medium", description="Framing tightness: close, medium, wide"),
    session: AsyncSession = Depends(get_db_session),
) -> AutoDetectResult:
    """
    Run MediaPipe Face Detection on a single frame to auto-populate
    FacecamBox and GameplayBox, and suggest a framing mode.
    """
    project = await ProjectService.get_project(session, project_id)
    if not project.video_path or not Path(project.video_path).exists():
        raise HTTPException(status_code=404, detail="Video file not found")

    if project.duration_sec:
        t = max(0.0, min(t, project.duration_sec - 0.5))

    result = await auto_detect_regions(
        project.video_path,
        time_sec=t,
        framing_mode=framing_mode,
        tightness=tightness,
    )
    return result


# ---------------------------------------------------------------------------
# Render Clip with FramingConfig
# ---------------------------------------------------------------------------

@framing_router.post("/{project_id}/render", response_model=RenderResponse)
async def render_project_clip(
    project_id: str,
    payload: RenderRequest,
    session: AsyncSession = Depends(get_db_session),
) -> RenderResponse:
    """
    Render a clip segment using the given FramingConfig.
    h264_nvenc is attempted first; libx264 is the automatic fallback.
    Always enforces -fps_mode cfr for VFR-to-CFR sync protection.
    """
    project = await ProjectService.get_project(session, project_id)
    if not project.video_path or not Path(project.video_path).exists():
        raise HTTPException(status_code=404, detail="Video file not found")

    # Resolve clip bounds
    start_sec = payload.start_sec
    end_sec = payload.end_sec

    if payload.clip_id and project.candidate_clips:
        clip = next((c for c in project.candidate_clips if c.id == payload.clip_id), None)
        if clip:
            start_sec = clip.start_sec
            end_sec = clip.end_sec

    if end_sec <= start_sec:
        raise HTTPException(status_code=400, detail="end_sec must be > start_sec")
    if project.duration_sec:
        end_sec = min(end_sec, project.duration_sec)

    # Resolve framing config (from saved profile or inline payload)
    framing_config: FramingConfig = payload.framing_config
    if payload.profile_id:
        framing_config = await ProfileService.profile_to_framing_config(session, payload.profile_id)

    speaker_tracks = None
    if framing_config.framing_mode in ("podcast", "talking_head"):
        try:
            speaker_tracks = await track_active_speaker(project.video_path, start_sec, end_sec)
        except Exception:
            # The worker is optional at install time; static manual framing remains usable.
            speaker_tracks = None

    # Determine source dimensions
    src_w = project.width or 1920
    src_h = project.height or 1080

    # Build output path
    output_dir = settings.cache_dir / "projects" / project_id / "renders"
    output_dir.mkdir(parents=True, exist_ok=True)

    out_name = payload.output_filename or f"clip_{int(start_sec)}_{int(end_sec)}_{framing_config.aspect_ratio.replace(':', 'x')}.mp4"
    output_path = str(output_dir / out_name)

    # Run render in thread (blocking subprocess)
    try:
        encoder_used, _stderr = await asyncio.to_thread(
            _do_render,
            project.video_path,
            output_path,
            framing_config,
            src_w,
            src_h,
            start_sec,
            end_sec,
            speaker_tracks,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Render failed: {e}")

    return RenderResponse(
        project_id=project_id,
        output_path=output_path,
        output_filename=out_name,
        duration_sec=end_sec - start_sec,
        framing_mode=framing_config.framing_mode,
        encoder_used=encoder_used,
        message=f"Rendered {end_sec - start_sec:.1f}s clip using {encoder_used}",
    )


def _do_render(
    video_path: str,
    output_path: str,
    config: FramingConfig,
    src_w: int,
    src_h: int,
    start_sec: float,
    end_sec: float,
    speaker_tracks: list[dict] | None = None,
) -> tuple[str, str]:
    from app.framing.ffmpeg_builder import try_render
    return try_render(video_path, output_path, config, src_w, src_h, start_sec, end_sec,
                      speaker_tracks=speaker_tracks)
