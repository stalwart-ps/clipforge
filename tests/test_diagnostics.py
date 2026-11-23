from pathlib import Path
import sys
import pytest
from httpx import ASGITransport, AsyncClient

# Ensure backend directory is in sys.path
backend_dir = Path(__file__).resolve().parent.parent / "backend"
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from app.diagnostics.service import DiagnosticsService
from app.main import app


@pytest.mark.asyncio
async def test_diagnostics_service_methods():
    gpu = await DiagnosticsService.get_gpu_info()
    assert gpu.status in ["optimal", "high_usage", "not_detected", "error"]

    ffmpeg = await DiagnosticsService.get_ffmpeg_info()
    assert ffmpeg.status in ["ready", "ready_cpu_only", "missing"]

    ollama = await DiagnosticsService.get_ollama_info()
    assert ollama.status in ["connected", "disconnected", "empty"]

    ytdlp = await DiagnosticsService.get_ytdlp_info()
    assert ytdlp.status in ["ready", "warning_no_js", "missing"]

    all_diag = await DiagnosticsService.check_all()
    assert all_diag.recommended_preset in ["lite", "balanced", "pro"]
    assert all_diag.timestamp is not None


@pytest.mark.asyncio
async def test_diagnostics_api_endpoint():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/diagnostics")
        assert response.status_code == 200
        data = response.json()
        assert "gpu" in data
        assert "ffmpeg" in data
        assert "ollama" in data
        assert "ytdlp" in data
        assert "recommendedPreset" in data  # camelCase on wire
