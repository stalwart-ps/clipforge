"""Phase 6 preview and cancellable batch export API."""

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db_session
from app.exports.schemas import (
    BatchExportRequest,
    ExportCancelResponse,
    ExportJobCreated,
    ExportJobRead,
    PreviewRequest,
)
from app.exports.service import cancel_job, create_job, get_job, get_jobs, render_preview
from app.core.config import settings
from app.media.ffmpeg import FFmpegHelper
from app.projects.service import ProjectService

router = APIRouter(prefix="/api/projects", tags=["exports"])


def _validate_bounds(start: float, end: float, duration: float | None) -> None:
    if end <= start:
        raise HTTPException(status_code=422, detail="Clip end must be after its start")
    if duration is not None and (start >= duration or end > duration + 0.001):
        raise HTTPException(status_code=422, detail="Clip bounds must fit inside the source video")


@router.get("/{project_id}/exports/jobs", response_model=list[ExportJobRead])
async def list_export_jobs(project_id: str, session: AsyncSession = Depends(get_db_session)):
    await ProjectService.get_project(session, project_id)
    return await get_jobs(project_id)


@router.post(
    "/{project_id}/exports/batch",
    response_model=ExportJobCreated,
    status_code=status.HTTP_202_ACCEPTED,
)
async def start_batch_export(
    project_id: str,
    payload: BatchExportRequest,
    session: AsyncSession = Depends(get_db_session),
) -> ExportJobCreated:
    project = await ProjectService.get_project(session, project_id)
    if not project.video_path or not Path(project.video_path).is_file():
        raise HTTPException(status_code=404, detail="Project video file not found")
    for clip in payload.clips:
        _validate_bounds(clip.start_sec, clip.end_sec, project.duration_sec)
    wants_subtitles = payload.burn_captions or payload.sidecars.srt or payload.sidecars.ass
    transcript = None
    if wants_subtitles:
        if not project.has_transcript:
            raise HTTPException(status_code=409, detail="Subtitle burning or sidecars require a saved transcript")
        transcript = await ProjectService.get_transcript(session, project_id)
    media_info = await FFmpegHelper.probe_media(Path(project.video_path))
    has_audio = bool(media_info.get("audio_codec"))
    if payload.remove_silence and not has_audio:
        raise HTTPException(status_code=422, detail="Dead-air trimming requires an audio stream")
    job = await create_job(
        project_id, project.video_path, payload.clips, payload,
        project.width or media_info.get("width") or 1920,
        project.height or media_info.get("height") or 1080,
        project.duration_sec or media_info.get("duration_sec"), transcript,
        has_audio=has_audio,
    )
    return ExportJobCreated(job=job)


@router.post("/{project_id}/exports/preview")
async def preview_export(
    project_id: str,
    payload: PreviewRequest,
    session: AsyncSession = Depends(get_db_session),
) -> FileResponse:
    project = await ProjectService.get_project(session, project_id)
    if not project.video_path or not Path(project.video_path).is_file():
        raise HTTPException(status_code=404, detail="Project video file not found")
    _validate_bounds(payload.start_sec, payload.end_sec, project.duration_sec)
    media_info = await FFmpegHelper.probe_media(Path(project.video_path))
    if payload.remove_silence and not media_info.get("audio_codec"):
        raise HTTPException(status_code=422, detail="Dead-air trimming requires an audio stream")
    transcript = None
    if payload.burn_captions and project.has_transcript:
        transcript = await ProjectService.get_transcript(session, project_id)
    try:
        output = await render_preview(
            project_id, project.video_path, payload,
            project.width or media_info.get("width") or 1920,
            project.height or media_info.get("height") or 1080,
            project.duration_sec or media_info.get("duration_sec"),
            transcript=transcript,
            has_audio=bool(media_info.get("audio_codec")),
        )
    except RuntimeError as error:
        raise HTTPException(status_code=500, detail=str(error)) from error
    return FileResponse(output, media_type="video/mp4", filename="clipforge_preview.mp4")


@router.post(
    "/{project_id}/exports/jobs/{job_id}/cancel",
    response_model=ExportCancelResponse,
)
async def stop_export(
    project_id: str,
    job_id: str,
    session: AsyncSession = Depends(get_db_session),
) -> ExportCancelResponse:
    await ProjectService.get_project(session, project_id)
    job = await get_job(job_id)
    if not job or job.project_id != project_id:
        raise HTTPException(status_code=404, detail="Export job not found")
    cancelled = await cancel_job(job_id)
    return ExportCancelResponse(
        success=cancelled,
        message="Export cancelled and FFmpeg process reaped" if cancelled else "Export job is already complete",
    )


@router.get("/{project_id}/exports/jobs/{job_id}/files/{file_name}")
async def download_export_file(
    project_id: str,
    job_id: str,
    file_name: str,
    session: AsyncSession = Depends(get_db_session),
) -> FileResponse:
    await ProjectService.get_project(session, project_id)
    job = await get_job(job_id)
    if not job or job.project_id != project_id:
        raise HTTPException(status_code=404, detail="Export job not found")
    root = (settings.cache_dir / "projects" / project_id / "renders" / "exports" / job_id).resolve()
    path = (root / Path(file_name).name).resolve()
    if path.parent != root or not path.is_file() or path.suffix.lower() not in {".mp4", ".srt", ".ass", ".json", ".txt"}:
        raise HTTPException(status_code=404, detail="Export file not found")
    media_type = "video/mp4" if path.suffix.lower() == ".mp4" else "text/plain; charset=utf-8"
    return FileResponse(path, media_type=media_type, filename=path.name)
