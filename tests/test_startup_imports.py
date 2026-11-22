import sys
from pathlib import Path
import pytest

# Ensure backend directory is in sys.path
backend_dir = Path(__file__).resolve().parent.parent / "backend"
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))


def test_zero_heavy_imports_at_startup():
    """
    CRITICAL SPEC RULE:
    Zero heavy AI/CV imports (torch, faster_whisper, whisperx, mediapipe, cv2,
    ultralytics, scenedetect, librosa) at FastAPI startup.
    """
    forbidden_modules = [
        "torch",
        "faster_whisper",
        "whisperx",
        "mediapipe",
        "cv2",
        "ultralytics",
        "scenedetect",
        "librosa",
    ]

    # Pre-check: None of them should be in sys.modules yet
    for mod in forbidden_modules:
        assert mod not in sys.modules, f"{mod} was already imported before test!"

    # Import the FastAPI application
    import app.main  # noqa: F401

    # Post-check: None of them should have been imported by app.main or its dependencies
    loaded_forbidden = [mod for mod in forbidden_modules if mod in sys.modules]
    assert (
        not loaded_forbidden
    ), f"Forbidden heavy modules loaded into sys.modules at startup: {loaded_forbidden}"
