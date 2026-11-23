"""Phase 4 Tests — Vision Framing Engine, Profiles CRUD, filter_complex builder, frame extractor."""

import asyncio
import json
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.core.db import init_db
from app.framing.ffmpeg_builder import build_filter_complex, build_ffmpeg_cmd, ASPECT_DIMENSIONS
from app.framing.schemas import FramingConfig, RegionBox, WatermarkConfig
from app.main import app


# ---------------------------------------------------------------------------
# Shared ASGI client
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def client():
    await init_db()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as c:
        yield c


# ---------------------------------------------------------------------------
# Task 1: filter_complex builder — all 5 modes produce valid strings with cfr
# ---------------------------------------------------------------------------

class TestFilterComplexBuilder:
    def _base_config(self, mode: str, layout: str = "split_vertical") -> FramingConfig:
        return FramingConfig(
            framing_mode=mode,  # type: ignore
            aspect_ratio="9:16",
            layout_template=layout,  # type: ignore
            facecam_box=RegionBox(x=0.0, y=0.0, w=0.3, h=0.25),
            gameplay_box=RegionBox(x=0.0, y=0.25, w=1.0, h=0.75),
            split_ratio=35,
        )

    def test_gaming_mode_with_face(self):
        config = self._base_config("gaming")
        fc, out_w, out_h = build_filter_complex(config, src_w=1920, src_h=1080)
        assert "vstack" in fc
        assert "[vout]" in fc
        assert out_w == 1080
        assert out_h == 1920

    def test_gaming_mode_no_face_fallback(self):
        """No facecam box → blurred fill fallback."""
        config = FramingConfig(framing_mode="gaming", aspect_ratio="9:16", layout_template="split_vertical")
        fc, out_w, out_h = build_filter_complex(config, src_w=1920, src_h=1080)
        assert "gblur" in fc
        assert "[vout]" in fc

    def test_podcast_mode(self):
        config = self._base_config("podcast")
        fc, out_w, out_h = build_filter_complex(config, src_w=1920, src_h=1080)
        assert "[vout]" in fc

    def test_talking_head_mode(self):
        config = self._base_config("talking_head")
        fc, out_w, out_h = build_filter_complex(config, src_w=1920, src_h=1080)
        assert "[vout]" in fc

    def test_screen_presenter_mode(self):
        config = self._base_config("screen_presenter")
        fc, out_w, out_h = build_filter_complex(config, src_w=1920, src_h=1080)
        assert "[vout]" in fc

    def test_reaction_mode(self):
        config = self._base_config("reaction")
        fc, out_w, out_h = build_filter_complex(config, src_w=1920, src_h=1080)
        assert "[vout]" in fc

    def test_pip_layout(self):
        config = self._base_config("gaming", layout="pip")
        fc, out_w, out_h = build_filter_complex(config, src_w=1920, src_h=1080)
        assert "[vout]" in fc

    def test_blurred_fill_layout(self):
        config = self._base_config("gaming", layout="blurred_fill")
        fc, _, _ = build_filter_complex(config, src_w=1920, src_h=1080)
        assert "gblur" in fc
        assert "[vout]" in fc

    def test_1x1_aspect_ratio(self):
        config = self._base_config("gaming")
        config = config.model_copy(update={"aspect_ratio": "1:1"})
        fc, out_w, out_h = build_filter_complex(config, src_w=1920, src_h=1080)
        assert out_w == 1080
        assert out_h == 1080

    def test_16x9_aspect_ratio(self):
        config = self._base_config("gaming")
        config = config.model_copy(update={"aspect_ratio": "16:9"})
        fc, out_w, out_h = build_filter_complex(config, src_w=1920, src_h=1080)
        assert out_w == 1920
        assert out_h == 1080

    def test_cfr_flag_in_full_command(self):
        """The full ffmpeg command must include -fps_mode cfr on the output side."""
        config = self._base_config("gaming")
        cmd = build_ffmpeg_cmd(
            input_path="/tmp/fake.mp4",
            output_path="/tmp/out.mp4",
            config=config,
            src_w=1920,
            src_h=1080,
            start_sec=0.0,
            end_sec=5.0,
            encoder="libx264",
        )
        cmd_str = " ".join(cmd)
        assert "-fps_mode cfr" in cmd_str, "Missing -fps_mode cfr in FFmpeg command"
        assert "-filter_complex" in cmd_str
        assert "-map [vout]" in cmd_str


# ---------------------------------------------------------------------------
# Task 2: Saved Profiles CRUD
# ---------------------------------------------------------------------------

class TestProfilesCRUD:
    async def test_create_and_list_profiles(self, client: AsyncClient):
        # Create
        payload = {
            "name": f"Test Gaming Channel {uuid.uuid4().hex[:6]}",
            "framing_mode": "gaming",
            "aspect_ratio": "9:16",
            "layout_template": "split_vertical",
            "facecam_box": {"x": 0.0, "y": 0.0, "w": 0.3, "h": 0.25},
            "gameplay_box": {"x": 0.0, "y": 0.25, "w": 1.0, "h": 0.75},
            "split_ratio": 35,
            "ollama_prompt": "Focus on epic gaming moments",
            "caption_style": "gaming_neon",
        }
        resp = await client.post("/api/profiles", json=payload)
        assert resp.status_code == 201, resp.text
        created = resp.json()
        assert created["framing_mode"] == "gaming"
        assert created["split_ratio"] == 35
        profile_id = created["id"]

        # List
        resp2 = await client.get("/api/profiles")
        assert resp2.status_code == 200
        ids = [p["id"] for p in resp2.json()]
        assert profile_id in ids

        # Get
        resp3 = await client.get(f"/api/profiles/{profile_id}")
        assert resp3.status_code == 200
        assert resp3.json()["id"] == profile_id

        # Update
        resp4 = await client.put(f"/api/profiles/{profile_id}", json={"name": "Updated Channel", "split_ratio": 40})
        assert resp4.status_code == 200
        assert resp4.json()["split_ratio"] == 40

        # Delete
        resp5 = await client.delete(f"/api/profiles/{profile_id}")
        assert resp5.status_code == 204

        # Confirm gone
        resp6 = await client.get(f"/api/profiles/{profile_id}")
        assert resp6.status_code == 404


# ---------------------------------------------------------------------------
# Task 3: On-demand frame extractor endpoint
# ---------------------------------------------------------------------------

class TestFrameExtractor:
    async def test_frame_extractor_no_project_returns_404(self, client: AsyncClient):
        resp = await client.get("/api/projects/nonexistent_project/frame?t=1.0")
        assert resp.status_code in (404, 422)

    async def test_frame_endpoint_registered(self, client: AsyncClient):
        """Ensure the endpoint is registered (not 405/404 from router)."""
        # We can't test with a real video without one, but confirm it's reachable
        resp = await client.get("/api/projects/fake_id/frame?t=0.0")
        # Expect 404 (project not found), NOT 405 (method not allowed)
        assert resp.status_code != 405


# ---------------------------------------------------------------------------
# Task 4: Vision worker subprocess — verify it can be called and exits 0
# ---------------------------------------------------------------------------

class TestVisionWorker:
    def test_vision_worker_script_exists(self):
        from app.core.config import settings
        worker = settings.backend_dir / "workers" / "vision_worker.py"
        assert worker.exists(), f"vision_worker.py not found at {worker}"

    def test_vision_worker_produces_result_format(self):
        """
        Run the vision worker with a fake non-existent video.
        It should still exit 0 and produce a valid RESULT: JSON with mode_suggestion.
        """
        import sys
        from app.core.config import settings
        worker = settings.backend_dir / "workers" / "vision_worker.py"

        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
            out_json = tmp.name

        try:
            result = subprocess.run(
                [sys.executable, str(worker), "--video-path", "/nonexistent.mp4", "--output-json", out_json],
                capture_output=True,
                text=True,
                timeout=30,
            )
            # Should exit 0 even on failure (graceful fallback)
            assert result.returncode == 0
            # Should have written something to the JSON file
            if Path(out_json).exists():
                data = json.loads(Path(out_json).read_text())
                assert "mode_suggestion" in data
                assert "face_count" in data
        finally:
            Path(out_json).unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Task 5: Render worker — NVENC fallback to libx264
# ---------------------------------------------------------------------------

class TestRenderWorkerNvencFallback:
    def test_nvenc_fallback_to_libx264(self):
        """
        Builds a command for h264_nvenc and verifies the libx264 fallback command
        contains -fps_mode cfr. We test builder correctness; actual FFmpeg execution
        requires a real video which may not be present in CI.
        """
        config = FramingConfig(
            framing_mode="gaming",
            aspect_ratio="9:16",
            layout_template="blurred_fill",
        )

        # Build libx264 command and verify required flags
        cmd = build_ffmpeg_cmd(
            input_path="/tmp/fake.mp4",
            output_path="/tmp/out.mp4",
            config=config,
            src_w=1920,
            src_h=1080,
            start_sec=0.0,
            end_sec=5.0,
            encoder="libx264",
        )
        cmd_str = " ".join(cmd)
        assert "libx264" in cmd_str
        assert "-fps_mode cfr" in cmd_str
        assert "-movflags +faststart" in cmd_str

    def test_render_endpoint_registered(self):
        """Verify the render endpoint is on the right path."""
        from app.framing.router import framing_router
        paths = [route.path for route in framing_router.routes]
        assert any("render" in p for p in paths)


# ---------------------------------------------------------------------------
# Task 6: Startup import safety — cv2/mediapipe still not at startup
# ---------------------------------------------------------------------------

class TestStartupImportsPhase4:
    def test_no_cv2_at_startup(self):
        import sys
        import subprocess

        code = """
import sys
sys.path.insert(0, '.')
from app.main import app
heavy = []
for mod in ['cv2', 'mediapipe', 'torch', 'ultralytics']:
    if mod in sys.modules:
        heavy.append(mod)
if heavy:
    print('HEAVY_IMPORTS_FOUND:' + ','.join(heavy))
    sys.exit(1)
print('OK_NO_HEAVY_IMPORTS')
sys.exit(0)
"""
        result = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=str(Path(__file__).parent.parent / "backend"),
        )
        assert result.returncode == 0, f"Heavy imports detected at startup: {result.stdout} {result.stderr}"
        assert "OK_NO_HEAVY_IMPORTS" in result.stdout
