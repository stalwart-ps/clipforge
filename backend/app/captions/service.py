"""Project-local caption files and current style persistence."""

import json
from pathlib import Path

from app.captions.ass_generator import generate_ass, resolve_config
from app.captions.schemas import CaptionConfig
from app.core.config import settings
from app.projects.schemas import TranscriptData


def caption_dir(project_id: str) -> Path:
    return settings.cache_dir / "projects" / project_id / "captions"


def write_project_ass(project_id: str, transcript: TranscriptData, config: CaptionConfig,
                      start_sec: float = 0.0,
                      end_sec: float | None = None) -> tuple[Path, int]:
    folder = caption_dir(project_id)
    folder.mkdir(parents=True, exist_ok=True)
    config = resolve_config(config)
    # Captioned renders currently use the Phase 4 9:16 target canvas.
    text, events = generate_ass(transcript, config, 1080, 1920, start_sec, end_sec)
    ass_path = folder / "captions.ass"
    ass_path.write_text(text, encoding="utf-8-sig")
    (folder / "config.json").write_text(config.model_dump_json(indent=2), encoding="utf-8")
    return ass_path, events


def saved_config(project_id: str) -> CaptionConfig:
    path = caption_dir(project_id) / "config.json"
    if not path.exists():
        return CaptionConfig()
    try:
        return CaptionConfig.model_validate(json.loads(path.read_text(encoding="utf-8")))
    except (ValueError, OSError):
        return CaptionConfig()

