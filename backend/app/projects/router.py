import os
from pathlib import Path
from typing import Generator
from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Request,
    Response,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db_session
from app.core.ws_manager import ws_manager
from app.projects.schemas import (
    CancelJobResponse,
    CandidateClip,
    DiscoverClipsRequest,
    IngestUrlRequest,
    ProjectRead,
    ProjectSummary,
    TranscribeRequest,
    TranscriptData,
    UpdateTranscriptRequest,
)
from app.projects.service import ProjectService

router = APIRouter(prefix="/api/projects", tags=["projects"])


@router.post("/url", response_model=ProjectRead, status_code=status.HTTP_201_CREATED)
async def ingest_url(
    payload: IngestUrlRequest, session: AsyncSession = Depends(get_db_session)
) -> ProjectRead:
    """Ingest a YouTube, Twitch, or Kick URL using subprocess-isolated yt-dlp."""
    return await ProjectService.create_url_project(session, payload)


@router.post("/upload", response_model=ProjectRead, status_code=status.HTTP_201_CREATED)
async def upload_local_file(
    file: UploadFile = File(...), session: AsyncSession = Depends(get_db_session)
) -> ProjectRead:
    """Upload a local video file (.mp4, .mov, .mkv, .webm) and extract 16kHz audio."""
    if not file.filename:
        raise HTTPException(status_code=400, detail="Uploaded file missing filename")
    return await ProjectService.create_local_project(session, file)


@router.get("", response_model=list[ProjectSummary], status_code=status.HTTP_200_OK)
async def list_projects(session: AsyncSession = Depends(get_db_session)) -> list[ProjectSummary]:
    """List all recent projects."""
    return await ProjectService.list_projects(session)


@router.get("/{project_id}", response_model=ProjectRead, status_code=status.HTTP_200_OK)
async def get_project(
    project_id: str, session: AsyncSession = Depends(get_db_session)
) -> ProjectRead:
    """Get project details, media paths, and extracted engagement signals."""
    return await ProjectService.get_project(session, project_id)


@router.post("/{project_id}/cancel", response_model=CancelJobResponse, status_code=status.HTTP_200_OK)
async def cancel_project(
    project_id: str, session: AsyncSession = Depends(get_db_session)
) -> CancelJobResponse:
    """Cancel an active download, audio extraction, or signal analysis process tree."""
    await ProjectService.cancel_project(session, project_id)
    return CancelJobResponse(
        success=True,
        message=f"Project {project_id} process tree cleanly terminated",
        project_id=project_id,
    )


# ==========================================
# Phase 3: Transcription & Ollama Scoring
# ==========================================
@router.post("/{project_id}/transcribe", response_model=ProjectRead, status_code=status.HTTP_202_ACCEPTED)
async def transcribe_project(
    project_id: str,
    payload: TranscribeRequest = TranscribeRequest(),
    session: AsyncSession = Depends(get_db_session),
) -> ProjectRead:
    """Trigger isolated faster-whisper transcription with Silero VAD and word-level timestamps."""
    return await ProjectService.transcribe_project(session, project_id, payload)


@router.post("/{project_id}/detect-scenes", response_model=ProjectRead, status_code=status.HTTP_202_ACCEPTED)
async def detect_scenes_project(
    project_id: str,
    session: AsyncSession = Depends(get_db_session),
) -> ProjectRead:
    """Trigger PySceneDetect shot boundary detection for snap-to-cut framing."""
    return await ProjectService.detect_scenes_project(session, project_id)


@router.post("/{project_id}/discover-clips", response_model=ProjectRead, status_code=status.HTTP_202_ACCEPTED)
async def discover_clips_project(
    project_id: str,
    payload: DiscoverClipsRequest = DiscoverClipsRequest(),
    session: AsyncSession = Depends(get_db_session),
) -> ProjectRead:
    """
    Run Ollama clip discovery with overlapped windows fused with engagement peaks.
    Reuses cached transcript if available. Sends keep_alive: 0 on final call.
    """
    return await ProjectService.discover_clips_project(session, project_id, payload)


@router.get("/{project_id}/transcript", response_model=TranscriptData, status_code=status.HTTP_200_OK)
async def get_project_transcript(
    project_id: str,
    session: AsyncSession = Depends(get_db_session),
) -> TranscriptData:
    """Get the full word-level transcript for inline editing."""
    return await ProjectService.get_transcript(session, project_id)


@router.put("/{project_id}/transcript", response_model=TranscriptData, status_code=status.HTTP_200_OK)
async def update_project_transcript(
    project_id: str,
    payload: UpdateTranscriptRequest,
    session: AsyncSession = Depends(get_db_session),
) -> TranscriptData:
    """Save user typo edits into SQLite without re-transcribing."""
    return await ProjectService.update_transcript(session, project_id, payload)


@router.get("/{project_id}/clips", response_model=list[CandidateClip], status_code=status.HTTP_200_OK)
async def get_project_clips(
    project_id: str,
    session: AsyncSession = Depends(get_db_session),
) -> list[CandidateClip]:
    """Retrieve ranked candidate clips discovered for this project."""
    return await ProjectService.get_clips(session, project_id)


@router.get("/{project_id}/thumbnail")
async def get_project_thumbnail(
    project_id: str, session: AsyncSession = Depends(get_db_session)
):
    """Serve single-frame preview thumbnail."""
    project = await ProjectService.get_project(session, project_id)
    if not project.thumbnail_path or not Path(project.thumbnail_path).exists():
        raise HTTPException(status_code=404, detail="Thumbnail not available yet")
    return FileResponse(project.thumbnail_path, media_type="image/jpeg")


def _iter_file_range(file_path: Path, start: int, length: int, chunk_size: int = 1024 * 1024) -> Generator[bytes, None, None]:
    with open(file_path, "rb") as f:
        f.seek(start)
        bytes_left = length
        while bytes_left > 0:
            read_size = min(chunk_size, bytes_left)
            chunk = f.read(read_size)
            if not chunk:
                break
            bytes_left -= len(chunk)
            yield chunk


@router.get("/{project_id}/stream")
async def stream_video(
    project_id: str, request: Request, session: AsyncSession = Depends(get_db_session)
):
    """
    HTTP 206 Partial Content / Byte-Range Video Streaming.
    Enables smooth instant scrubbing in HTML5 <video> players.
    """
    project = await ProjectService.get_project(session, project_id)
    if not project.video_path or not Path(project.video_path).exists():
        raise HTTPException(status_code=404, detail="Video file not found or not yet downloaded")

    file_path = Path(project.video_path)
    file_size = file_path.stat().st_size
    range_header = request.headers.get("range")

    media_type = "video/mp4"
    if file_path.suffix.lower() == ".webm":
        media_type = "video/webm"
    elif file_path.suffix.lower() == ".mkv":
        media_type = "video/x-matroska"

    if not range_header:
        # Full content response
        return FileResponse(file_path, media_type=media_type)

    # Parse Range: bytes=start-end
    try:
        range_str = range_header.replace("bytes=", "").strip()
        parts = range_str.split("-")
        start = int(parts[0]) if parts[0] else 0
        end = int(parts[1]) if len(parts) > 1 and parts[1] else file_size - 1

        if start >= file_size or end >= file_size or start > end:
            return Response(
                status_code=status.HTTP_416_REQUESTED_RANGE_NOT_SATISFIABLE,
                headers={"Content-Range": f"bytes */{file_size}"},
            )

        content_length = (end - start) + 1
        headers = {
            "Content-Range": f"bytes {start}-{end}/{file_size}",
            "Accept-Ranges": "bytes",
            "Content-Length": str(content_length),
            "Content-Type": media_type,
        }

        return StreamingResponse(
            _iter_file_range(file_path, start, content_length),
            status_code=status.HTTP_206_PARTIAL_CONTENT,
            headers=headers,
        )
    except Exception:
        return FileResponse(file_path, media_type=media_type)


@router.websocket("/ws/{project_id}")
async def project_websocket(websocket: WebSocket, project_id: str):
    """Real-time WebSocket progress stream for download, audio extraction, and signal analysis."""
    await ws_manager.connect(project_id, websocket)
    try:
        while True:
            # Keep socket alive and respond to client pings
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        await ws_manager.disconnect(project_id, websocket)
    except Exception:
        await ws_manager.disconnect(project_id, websocket)
