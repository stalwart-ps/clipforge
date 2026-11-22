from pydantic import Field
from app.core.schemas import APISchema


class IngestUrlRequest(APISchema):
    url: str = Field(..., min_length=5, description="YouTube, Twitch, or Kick URL")
    download_mode: str = Field(default="full", description="'full' (best video+audio) or 'fast_vod' (audio first)")
    fetch_chat_replay: bool = Field(default=True, description="Fetch live chat replay / comments if available")


class EngagementPoint(APISchema):
    time_sec: float
    score: float = Field(..., ge=0.0, le=100.0)
    source: str  # 'heatmap', 'comment', 'chat_velocity', 'audio_energy'
    label: str | None = None
    weight: float = 1.0


class EngagementSignals(APISchema):
    heatmap: list[EngagementPoint] = []
    comment_timestamps: list[EngagementPoint] = []
    chat_velocity: list[EngagementPoint] = []
    audio_energy: list[EngagementPoint] = []
    fused_peaks: list[EngagementPoint] = []


class WordTimestamp(APISchema):
    word: str
    start: float
    end: float
    confidence: float = 1.0


class TranscriptSegment(APISchema):
    id: int
    start: float
    end: float
    text: str
    words: list[WordTimestamp] = []


class TranscriptData(APISchema):
    language: str = "en"
    language_probability: float = 1.0
    duration: float = 0.0
    segments: list[TranscriptSegment] = []


class SceneCut(APISchema):
    start_sec: float
    end_sec: float


class CandidateClip(APISchema):
    id: str
    title: str
    hook_summary: str
    start_sec: float
    end_sec: float
    duration_sec: float
    viral_score: int = Field(..., ge=1, le=100)
    reason: str
    suggested_hashtags: list[str] = []
    detected_mood: str
    snapped_to_scene: bool = False


class TranscribeRequest(APISchema):
    whisper_model: str | None = None
    language: str | None = None
    translate: bool = False
    hotwords: str | None = None
    initial_prompt: str | None = None
    use_whisperx: bool = False


class DiscoverClipsRequest(APISchema):
    ollama_model: str | None = None
    min_duration_sec: int = Field(default=15, ge=5, le=120)
    max_duration_sec: int = Field(default=60, ge=10, le=300)
    max_clips: int = Field(default=5, ge=1, le=20)
    custom_prompt: str | None = None


class UpdateTranscriptRequest(APISchema):
    segments: list[TranscriptSegment]


class ProjectRead(APISchema):
    id: str
    title: str
    source_type: str
    source_url: str | None = None
    download_mode: str
    status: str
    progress_percent: float = 0.0
    current_stage: str
    video_path: str | None = None
    audio_path: str | None = None
    thumbnail_path: str | None = None
    duration_sec: float | None = None
    width: int | None = None
    height: int | None = None
    fps: float | None = None
    file_size_bytes: int | None = None
    engagement_signals: EngagementSignals | None = None
    has_transcript: bool = False
    has_scene_cuts: bool = False
    candidate_clips: list[CandidateClip] = []
    whisper_model_used: str | None = None
    ollama_model_used: str | None = None
    error_message: str | None = None
    active_pid: int | None = None
    created_at: str
    updated_at: str


class ProjectSummary(APISchema):
    id: str
    title: str
    source_type: str
    status: str
    progress_percent: float
    duration_sec: float | None = None
    has_transcript: bool = False
    clips_count: int = 0
    created_at: str


class CancelJobResponse(APISchema):
    success: bool
    message: str
    project_id: str
