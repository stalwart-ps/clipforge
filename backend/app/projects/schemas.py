from pydantic import Field, model_validator
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


class ClipSegment(APISchema):
    start_sec: float
    end_sec: float
    label: str | None = None


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
    segments: list[ClipSegment] = []

    @model_validator(mode="after")
    def compute_duration_and_bounds(self) -> "CandidateClip":
        if self.segments:
            self.duration_sec = round(sum(max(0.0, s.end_sec - s.start_sec) for s in self.segments), 2)
            if not self.start_sec or self.start_sec > self.segments[0].start_sec:
                self.start_sec = self.segments[0].start_sec
            if not self.end_sec or self.end_sec < self.segments[-1].end_sec:
                self.end_sec = self.segments[-1].end_sec
        elif not self.duration_sec and self.end_sec > self.start_sec:
            self.duration_sec = round(self.end_sec - self.start_sec, 2)
        return self

    @property
    def effective_segments(self) -> list[tuple[float, float]]:
        if self.segments:
            return [(s.start_sec, s.end_sec) for s in self.segments]
        return [(self.start_sec, self.end_sec)]


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
    clip_count_mode: str = Field(default="manual", pattern="^(auto|manual)$")
    max_clips: int = Field(default=5, ge=1, le=100)
    custom_prompt: str | None = None
    allow_multi_segment: bool = False
    auto_duration: bool = True


class UpdateClipsRequest(APISchema):
    clips: list[CandidateClip] = []


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
    ai_clip_recommendation: str | None = None
    error_message: str | None = None
    active_pid: int | None = None
    file_missing: bool = False
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
    file_missing: bool = False


class CancelJobResponse(APISchema):
    success: bool
    message: str
    project_id: str


class DeleteProjectResponse(APISchema):
    deleted: bool = True
    project_id: str


class ProjectCleanupRequest(APISchema):
    remove_missing: bool = True
    remove_cancelled: bool = True


class ProjectCleanupResponse(APISchema):
    removed_count: int
    removed_ids: list[str] = []
