import asyncio
import json
from pathlib import Path
import shutil
import subprocess
import sys
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

# Ensure backend directory is in sys.path
backend_dir = Path(__file__).resolve().parent.parent / "backend"
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from app.core.config import settings
from app.core.db import Base, engine
from app.core.process_manager import ProcessManager
from app.main import app
from app.media.ffmpeg import FFmpegHelper


@pytest_asyncio.fixture(autouse=True)
async def init_test_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield


@pytest.fixture(scope="session")
def sample_test_video(tmp_path_factory):
    """Generate a tiny 1-second synthetic MP4 video with a sine wave audio track."""
    tmp_dir = tmp_path_factory.mktemp("media")
    video_path = tmp_dir / "sample_video.mp4"

    ffmpeg_bin = shutil.which("ffmpeg") or "ffmpeg"
    cmd = [
        ffmpeg_bin,
        "-y",
        "-f",
        "lavfi",
        "-i",
        "testsrc=duration=2:size=320x240:rate=30",
        "-f",
        "lavfi",
        "-i",
        "sine=frequency=1000:duration=2",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "64k",
        str(video_path),
    ]
    subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
    return video_path


@pytest.mark.asyncio
async def test_media_probing_and_audio_extraction(sample_test_video, tmp_path):
    # 1. Probe video metadata
    meta = await FFmpegHelper.probe_media(sample_test_video)
    assert meta["duration_sec"] >= 1.9
    assert meta["width"] == 320
    assert meta["height"] == 240
    assert meta["fps"] == 30.0

    # 2. Extract 16kHz mono audio
    wav_path = tmp_path / "extracted_16k.wav"
    extracted = await FFmpegHelper.extract_16k_mono_audio(sample_test_video, wav_path)
    assert extracted is True
    assert wav_path.exists()
    assert wav_path.stat().st_size > 0

    # 3. Test Audio Energy Worker subprocess
    worker_script = backend_dir / "workers" / "audio_energy_worker.py"
    signals_json = tmp_path / "audio_signals.json"

    proc = await asyncio.create_subprocess_exec(
        sys.executable,
        str(worker_script),
        "--audio-path",
        str(wav_path),
        "--output-json",
        str(signals_json),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    assert proc.returncode == 0
    assert signals_json.exists()

    with open(signals_json, "r") as f:
        signals = json.load(f)
    assert len(signals) > 0
    assert "time_sec" in signals[0]
    assert "score" in signals[0]
    assert signals[0]["source"] == "audio_energy"


@pytest.mark.asyncio
async def test_local_upload_and_stream(sample_test_video):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # 1. Upload sample video
        with open(sample_test_video, "rb") as f:
            files = {"file": ("sample.mp4", f, "video/mp4")}
            res = await client.post("/api/projects/upload", files=files)

        assert res.status_code == 201
        data = res.json()
        project_id = data["id"]
        assert data["sourceType"] == "local"
        assert data["downloadMode"] == "local"

        # Wait briefly for background audio extraction to complete
        await asyncio.sleep(2.0)

        # 2. Fetch project details
        proj_res = await client.get(f"/api/projects/{project_id}")
        assert proj_res.status_code == 200
        proj_data = proj_res.json()
        assert proj_data["status"] in ("extracting_audio", "ready")

        # 3. Test HTTP 206 Range Streaming
        # Request first 512 bytes
        headers = {"Range": "bytes=0-511"}
        stream_res = await client.get(f"/api/projects/{project_id}/stream", headers=headers)
        assert stream_res.status_code == 206
        assert "Content-Range" in stream_res.headers
        assert stream_res.headers["Content-Range"].startswith("bytes 0-511/")
        assert stream_res.headers["Accept-Ranges"] == "bytes"
        assert len(stream_res.content) == 512


@pytest.mark.asyncio
async def test_process_manager_cancellation():
    # Start a dummy long-running subprocess to verify tree termination
    proc = await asyncio.create_subprocess_exec(
        sys.executable,
        "-c",
        "import time; time.sleep(30)",
        stdout=asyncio.subprocess.PIPE,
    )
    test_id = "test_cancel_proj_123"
    await ProcessManager.register_process(test_id, proc.pid)

    # Cancel
    cancelled = await ProcessManager.cancel_project(test_id)
    assert cancelled is True

    # Check process is dead
    await asyncio.sleep(0.5)
    assert proc.returncode is not None or proc.poll() is not None
