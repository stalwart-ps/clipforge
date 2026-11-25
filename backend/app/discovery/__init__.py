"""Discovery Engine & Schema definitions for AI Clip Discovery."""

from app.projects.schemas import (
    CandidateClip,
    ClipSegment,
    DiscoverClipsRequest,
)
from app.discovery.ollama_service import (
    OllamaClipDiscoveryEngine,
    SYSTEM_PROMPT,
    MULTI_SEGMENT_SYSTEM_PROMPT,
    COMPILATION_SYSTEM_PROMPT,
)

__all__ = [
    "CandidateClip",
    "ClipSegment",
    "DiscoverClipsRequest",
    "OllamaClipDiscoveryEngine",
    "SYSTEM_PROMPT",
    "MULTI_SEGMENT_SYSTEM_PROMPT",
    "COMPILATION_SYSTEM_PROMPT",
]
