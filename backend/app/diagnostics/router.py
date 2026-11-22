from fastapi import APIRouter, status
from app.diagnostics.schemas import SystemDiagnosticsResponse, YtDlpUpdateResponse
from app.diagnostics.service import DiagnosticsService

router = APIRouter(prefix="/api/diagnostics", tags=["diagnostics"])


@router.get("", response_model=SystemDiagnosticsResponse, status_code=status.HTTP_200_OK)
async def get_system_diagnostics() -> SystemDiagnosticsResponse:
    """Run all hardware and system diagnostics checks and return live telemetry."""
    return await DiagnosticsService.check_all()


@router.post("/update-ytdlp", response_model=YtDlpUpdateResponse, status_code=status.HTTP_200_OK)
async def update_ytdlp() -> YtDlpUpdateResponse:
    """Trigger a one-click upgrade of yt-dlp to the latest version."""
    return await DiagnosticsService.update_ytdlp()
