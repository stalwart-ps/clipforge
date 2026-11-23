"""Phase 5 caption generation, font discovery, download, and render endpoints."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.captions.schemas import (
    CaptionGenerateRequest,
    CaptionGenerateResponse,
    CaptionRenderRequest,
    CaptionRenderResponse,
    CaptionTranscriptUpdateRequest,
)
from app.captions.service import caption_dir, write_project_ass
from app.core.config import settings
from app.core.db import get_db_session
from app.framing.schemas import FramingConfig
from app.projects.service import ProjectService
from app.projects.schemas import TranscriptData, UpdateTranscriptRequest

router = APIRouter(prefix="/api", tags=["captions"])


def _system_fonts() -> list[str]:
    candidates = [
        Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts",
        Path.home() / ".fonts", Path.home() / ".local/share/fonts",
        Path("/usr/share/fonts"), Path("/System/Library/Fonts"), Path("/Library/Fonts"),
    ]
    names: set[str] = {"Arial", "Arial Black", "DejaVu Sans"}
    for folder in candidates:
        if folder.is_dir():
            for pattern in ("*.ttf", "*.otf", "*.ttc"):
                names.update(path.stem.replace("_", " ") for path in folder.rglob(pattern))
    return sorted(names, key=str.casefold)


@router.get("/captions/fonts", response_model=list[str])
async def list_caption_fonts() -> list[str]:
    return await asyncio.to_thread(_system_fonts)


@router.post("/projects/{project_id}/captions/generate", response_model=CaptionGenerateResponse)
async def generate_project_captions(
    project_id: str,
    payload: CaptionGenerateRequest,
    session: AsyncSession = Depends(get_db_session),
) -> CaptionGenerateResponse:
    transcript = await ProjectService.get_transcript(session, project_id)
    path, count = write_project_ass(project_id, transcript, payload.config)
    return CaptionGenerateResponse(ass_path=str(path), event_count=count)


@router.put("/projects/{project_id}/captions/transcript", response_model=TranscriptData)
async def update_caption_transcript(
    project_id: str,
    payload: CaptionTranscriptUpdateRequest,
    session: AsyncSession = Depends(get_db_session),
):
    """Persist inline word edits and refresh the generated ASS from the same request."""
    updated = await ProjectService.update_transcript(
        session, project_id, UpdateTranscriptRequest(segments=payload.segments)
    )
    write_project_ass(project_id, updated, payload.config)
    return updated


@router.get("/projects/{project_id}/captions/ass")
async def download_project_captions(
    project_id: str, session: AsyncSession = Depends(get_db_session)
) -> FileResponse:
    await ProjectService.get_project(session, project_id)
    path = caption_dir(project_id) / "captions.ass"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Caption file has not been generated yet")
    return FileResponse(path, media_type="text/plain; charset=utf-8", filename=f"{project_id}_captions.ass")


@router.post("/projects/{project_id}/captions/render", response_model=CaptionRenderResponse)
async def render_captioned_video(
    project_id: str,
    payload: CaptionRenderRequest,
    session: AsyncSession = Depends(get_db_session),
) -> CaptionRenderResponse:
    project = await ProjectService.get_project(session, project_id)
    if not project.video_path or not Path(project.video_path).is_file():
        raise HTTPException(status_code=404, detail="Project video file not found")
    if not project.has_transcript:
        raise HTTPException(status_code=409, detail="Transcribe the video before generating captions")
    end_sec = min(payload.end_sec or project.duration_sec or 0.0, project.duration_sec or payload.end_sec or 0.0)
    if end_sec <= payload.start_sec:
        raise HTTPException(status_code=422, detail="Caption render range must have positive duration")
    transcript = await ProjectService.get_transcript(session, project_id)
    ass_path, count = write_project_ass(
        project_id, transcript, payload.config, payload.start_sec, end_sec,
    )
    output_dir = settings.cache_dir / "projects" / project_id / "renders"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"captions_{int(payload.start_sec)}_{int(end_sec)}.mp4"
    framing = FramingConfig(layout_template="blurred_fill", aspect_ratio="9:16")

    def render() -> tuple[str, str]:
        from app.framing.ffmpeg_builder import try_render
        return try_render(
            project.video_path, str(output_path), framing, project.width or 1920, project.height or 1080,
            payload.start_sec, end_sec, ass_path=str(ass_path),
        )

    try:
        encoder, _ = await asyncio.to_thread(render)
    except Exception as error:
        raise HTTPException(status_code=500, detail=f"Caption render failed: {error}") from error
    return CaptionRenderResponse(output_path=str(output_path), encoder_used=encoder, event_count=count)

