"""Re-export Ollama Clip Discovery Engine from app.discovery.ollama_service."""

from app.discovery.ollama_service import (
    CandidateClip,
    ClipSegment,
    EngagementSignals,
    TranscriptData,
    SceneCut,
    SYSTEM_PROMPT,
    MULTI_SEGMENT_SYSTEM_PROMPT,
    COMPILATION_SYSTEM_PROMPT,
    OllamaClipDiscoveryEngine,
)

__all__ = [
    "CandidateClip",
    "ClipSegment",
    "EngagementSignals",
    "TranscriptData",
    "SceneCut",
    "SYSTEM_PROMPT",
    "MULTI_SEGMENT_SYSTEM_PROMPT",
    "COMPILATION_SYSTEM_PROMPT",
    "OllamaClipDiscoveryEngine",
]
