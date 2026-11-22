"""Phase 4 — Auto-detect regions: launches vision_worker.py as isolated subprocess."""

from __future__ import annotations
import asyncio
import json
import sys
from pathlib import Path

from app.core.config import settings
from app.framing.schemas import AutoDetectResult, RegionBox


async def auto_detect_regions(
    video_path: str,
    time_sec: float = 5.0,
) -> AutoDetectResult:
    """
    Runs the vision_worker subprocess and returns an AutoDetectResult.

    If mediapipe/cv2 are not installed, returns a sensible default
    (whole-frame boxes, gaming mode) rather than crashing.
    """
    worker_script = settings.backend_dir / "workers" / "vision_worker.py"
    output_json = settings.temp_dir / f"vision_{abs(hash(video_path))}.json"

    cmd = [
        sys.executable,
        str(worker_script),
        "--video-path", video_path,
        "--time-sec", str(time_sec),
        "--output-json", str(output_json),
    ]

    try:
        result = await asyncio.to_thread(
            _run_vision_subprocess, cmd, timeout=60.0
        )
    except Exception as e:
        # Vision deps not installed or other error → return whole-frame defaults
        return AutoDetectResult(
            facecam_box=None,
            gameplay_box=RegionBox(x=0.0, y=0.0, w=1.0, h=1.0),
            face_count=0,
            face_confidence=0.0,
            mode_suggestion="gaming",
            message=f"Auto-detect unavailable: {e}. Install opencv-python and mediapipe.",
        )

    # Parse result from subprocess
    result_data: dict = {}
    if output_json.exists():
        try:
            result_data = json.loads(output_json.read_text(encoding="utf-8"))
        except Exception:
            pass
        finally:
            output_json.unlink(missing_ok=True)

    if not result_data:
        return AutoDetectResult(
            gameplay_box=RegionBox(x=0.0, y=0.0, w=1.0, h=1.0),
            mode_suggestion="gaming",
            message="Vision worker returned no data",
        )

    facecam_box: RegionBox | None = None
    gameplay_box: RegionBox | None = None

    if result_data.get("facecam_box"):
        try:
            facecam_box = RegionBox(**result_data["facecam_box"])
        except Exception:
            pass

    if result_data.get("gameplay_box"):
        try:
            gameplay_box = RegionBox(**result_data["gameplay_box"])
        except Exception:
            pass

    return AutoDetectResult(
        facecam_box=facecam_box,
        gameplay_box=gameplay_box,
        face_count=result_data.get("face_count", 0),
        face_confidence=result_data.get("face_confidence", 0.0),
        mode_suggestion=result_data.get("mode_suggestion", "gaming"),  # type: ignore[arg-type]
        message=result_data.get("message", ""),
    )


def _run_vision_subprocess(cmd: list[str], timeout: float) -> int:
    import subprocess

    proc = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
    )
    return proc.returncode


async def track_active_speaker(video_path: str, start_sec: float, end_sec: float) -> list[dict]:
    """Run cut-aware MediaPipe Face Mesh tracking in its isolated worker."""
    worker_script = settings.backend_dir / "workers" / "vision_worker.py"
    output_json = settings.temp_dir / f"speaker_{abs(hash((video_path, start_sec, end_sec)))}.json"
    cmd = [sys.executable, str(worker_script), "--video-path", video_path,
           "--track-start", str(start_sec), "--track-end", str(end_sec),
           "--output-json", str(output_json)]
    try:
        await asyncio.to_thread(_run_vision_subprocess, cmd, max(120.0, (end_sec - start_sec) * 3))
        payload = json.loads(output_json.read_text(encoding="utf-8"))
        return payload.get("tracks", [])
    finally:
        output_json.unlink(missing_ok=True)
