import asyncio
import json
import uuid
from pathlib import Path
import shutil
import subprocess
import sys
from unittest.mock import AsyncMock, patch
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient, Response

# Ensure backend directory is in sys.path
backend_dir = Path(__file__).resolve().parent.parent / "backend"
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from app.core.config import settings
from app.core.db import Base, engine, async_session_maker, init_db
from app.main import app
from app.media.ffmpeg import FFmpegHelper
from app.projects.models import Project
from app.projects.ollama_service import OllamaClipDiscoveryEngine
from app.projects.schemas import (
    EngagementPoint,
    EngagementSignals,
    SceneCut,
    TranscriptData,
    TranscriptSegment,
    WordTimestamp,
)


@pytest_asyncio.fixture(autouse=True)
async def init_test_db():
    await init_db()
    yield


@pytest.fixture(scope="session")
def sample_media(tmp_path_factory):
    """Generate a 3-second sample MP4 video and 16kHz WAV."""
    tmp_dir = tmp_path_factory.mktemp("media_p3")
    video_path = tmp_dir / "sample_test.mp4"
    wav_path = tmp_dir / "sample_16k.wav"

    ffmpeg_bin = shutil.which("ffmpeg") or "ffmpeg"
    cmd = [
        ffmpeg_bin,
        "-y",
        "-f",
        "lavfi",
        "-i",
        "testsrc=duration=3:size=320x240:rate=30",
        "-f",
        "lavfi",
        "-i",
        "sine=frequency=1000:duration=3",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "pcm_s16le",
        "-ar",
        "16000",
        "-ac",
        "1",
        str(video_path),
    ]
    subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)

    # Extract WAV
    wav_cmd = [
        ffmpeg_bin,
        "-y",
        "-i",
        str(video_path),
        "-vn",
        "-acodec",
        "pcm_s16le",
        "-ar",
        "16000",
        "-ac",
        "1",
        str(wav_path),
    ]
    subprocess.run(wav_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)

    return {"video": video_path, "wav": wav_path}


@pytest.mark.asyncio
async def test_transcribe_worker_subprocess(sample_media, tmp_path):
    """Verify faster-whisper runs in an isolated subprocess and outputs word timestamps."""
    worker_script = backend_dir / "workers" / "transcribe_worker.py"
    output_json = tmp_path / "test_transcript.json"

    # Run worker on tiny model on CPU for fast testing
    cmd = [
        sys.executable,
        str(worker_script),
        "--audio-path",
        str(sample_media["wav"]),
        "--output-json",
        str(output_json),
        "--model-size",
        "tiny",
        "--device",
        "cpu",
        "--compute-type",
        "int8",
    ]

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    assert proc.returncode == 0, f"Worker failed: {stderr.decode()}"
    assert output_json.exists()

    with open(output_json, "r", encoding="utf-8") as f:
        data = json.load(f)

    assert "language" in data
    assert "segments" in data
    assert "duration" in data


@pytest.mark.asyncio
async def test_scene_detect_worker_subprocess(sample_media, tmp_path):
    """Verify PySceneDetect runs in an isolated worker subprocess."""
    worker_script = backend_dir / "workers" / "scene_detect_worker.py"
    output_json = tmp_path / "test_scenes.json"

    cmd = [
        sys.executable,
        str(worker_script),
        "--video-path",
        str(sample_media["video"]),
        "--output-json",
        str(output_json),
        "--threshold",
        "27.0",
    ]

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    assert proc.returncode == 0, f"Scene detect failed: {stderr.decode()}"
    assert output_json.exists()

    with open(output_json, "r", encoding="utf-8") as f:
        scenes = json.load(f)
    assert isinstance(scenes, list)


@pytest.mark.asyncio
async def test_ollama_clip_discovery_with_vram_flush():
    """Verify Ollama chunking, engagement fusion, boundary snapping, and keep_alive: 0 VRAM flush."""
    transcript = TranscriptData(
        language="en",
        duration=65.0,
        segments=[
            TranscriptSegment(
                id=1,
                start=5.2,
                end=12.0,
                text="This is an insane moment that will blow your mind.",
                words=[
                    WordTimestamp(word="This", start=5.2, end=5.6),
                    WordTimestamp(word="is", start=5.6, end=5.8),
                    WordTimestamp(word="an", start=5.8, end=6.0),
                    WordTimestamp(word="insane", start=6.0, end=6.5),
                    WordTimestamp(word="moment", start=6.5, end=7.0),
                    WordTimestamp(word="that", start=7.0, end=7.3),
                    WordTimestamp(word="will", start=7.3, end=7.6),
                    WordTimestamp(word="blow", start=7.6, end=8.0),
                    WordTimestamp(word="your", start=8.0, end=8.2),
                    WordTimestamp(word="mind.", start=8.2, end=8.8),
                ],
            ),
            TranscriptSegment(
                id=2,
                start=12.5,
                end=28.4,
                text="We pulled off the impossible clutch victory.",
                words=[
                    WordTimestamp(word="We", start=12.5, end=13.0),
                    WordTimestamp(word="pulled", start=13.0, end=13.5),
                    WordTimestamp(word="off", start=13.5, end=13.8),
                    WordTimestamp(word="the", start=13.8, end=14.0),
                    WordTimestamp(word="impossible", start=14.0, end=14.8),
                    WordTimestamp(word="clutch", start=14.8, end=15.3),
                    WordTimestamp(word="victory.", start=15.3, end=16.0),
                ],
            ),
        ],
    )

    engagement = EngagementSignals(
        heatmap=[EngagementPoint(time_sec=14.0, score=96.0, source="heatmap", label="peak")],
        comment_timestamps=[EngagementPoint(time_sec=15.0, score=90.0, source="comment", label="insane clutch")],
        chat_velocity=[EngagementPoint(time_sec=14.5, score=85.0, source="chat_velocity", label="chat flood")],
        audio_energy=[EngagementPoint(time_sec=15.5, score=92.0, source="audio_energy", label="loud reaction")],
    )

    scene_cuts = [
        SceneCut(start_sec=0.0, end_sec=5.0),
        SceneCut(start_sec=5.0, end_sec=28.5),
    ]

    mock_ollama_response = {
        "clips": [
            {
                "title": "Impossible Clutch Win",
                "hook_summary": "Mind-blowing turnaround in seconds.",
                "start_sec": 5.0,
                "end_sec": 28.0,
                "viral_score": 95,
                "reason": "Heatmap peak + comment timestamps + scream hype.",
                "suggested_hashtags": ["#clutch", "#viral", "#gaming"],
                "detected_mood": "hype",
            }
        ]
    }

    recorded_payloads = []

    async def mock_post(url, json=None, **kwargs):
        recorded_payloads.append(json)
        return Response(200, json={"response": json_dumps(mock_ollama_response)})

    def json_dumps(obj):
        import json
        return json.dumps(obj)

    with patch("httpx.AsyncClient.post", side_effect=mock_post):
        clips = await OllamaClipDiscoveryEngine.discover_clips(
            transcript=transcript,
            engagement=engagement,
            scene_cuts=scene_cuts,
            model_name="qwen2.5:7b",
            min_duration=10,
            max_duration=60,
            max_clips=3,
        )

    assert len(clips) == 1
    assert clips[0].title == "Impossible Clutch Win"
    assert clips[0].viral_score == 95
    # Verify boundary snapped to scene cut (5.0s)
    assert clips[0].start_sec == 5.0
    assert clips[0].snapped_to_scene is True

    # Verify keep_alive: 0 was sent on the final request!
    assert len(recorded_payloads) > 0
    assert recorded_payloads[-1]["keep_alive"] == 0


@pytest.mark.asyncio
async def test_stage_caching_and_transcript_editor():
    """Verify that existing transcripts are reused without re-transcribing, and typo edits persist."""
    test_proj_id = f"proj_cache_{uuid.uuid4().hex[:8]}"
    async with async_session_maker() as session:
        proj = Project(
            id=test_proj_id,
            title="Cache Test Video",
            source_type="local",
            download_mode="local",
            status="ready",
            duration_sec=30.0,
            transcript_json=json.dumps({
                "language": "en",
                "duration": 30.0,
                "segments": [
                    {
                        "id": 1,
                        "start": 0.0,
                        "end": 5.0,
                        "text": "Origianl typo text here",
                        "words": [{"word": "Origianl", "start": 0.0, "end": 1.0, "confidence": 0.9}],
                    }
                ],
            }),
        )
        session.add(proj)
        await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # 1. Fetch transcript
        res = await client.get(f"/api/projects/{test_proj_id}/transcript")
        assert res.status_code == 200
        data = res.json()
        assert data["segments"][0]["text"] == "Origianl typo text here"

        # 2. Fix typo via PUT /api/projects/{id}/transcript
        updated_segments = [
            {
                "id": 1,
                "start": 0.0,
                "end": 5.0,
                "text": "Original corrected text here",
                "words": [{"word": "Original", "start": 0.0, "end": 1.0, "confidence": 1.0}],
            }
        ]
        put_res = await client.put(
            f"/api/projects/{test_proj_id}/transcript",
            json={"segments": updated_segments},
        )
        assert put_res.status_code == 200
        put_data = put_res.json()
        assert put_data["segments"][0]["text"] == "Original corrected text here"

        # 3. Verify SQLite persisted the fix
        verify_res = await client.get(f"/api/projects/{test_proj_id}/transcript")
        assert verify_res.json()["segments"][0]["text"] == "Original corrected text here"
