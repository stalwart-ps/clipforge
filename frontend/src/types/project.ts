export interface EngagementPoint {
  timeSec: number;
  score: number;
  source: 'heatmap' | 'comment' | 'chat_velocity' | 'audio_energy';
  label: string | null;
  weight?: number;
}

export interface EngagementSignals {
  heatmap: EngagementPoint[];
  commentTimestamps: EngagementPoint[];
  chatVelocity: EngagementPoint[];
  audioEnergy: EngagementPoint[];
  fusedPeaks?: EngagementPoint[];
}

export interface WordTimestamp {
  word: string;
  start: number;
  end: number;
  confidence: number;
}

export interface TranscriptSegment {
  id: number;
  start: number;
  end: number;
  text: string;
  words: WordTimestamp[];
}

export interface TranscriptData {
  language: string;
  languageProbability: number;
  duration: number;
  segments: TranscriptSegment[];
}

export interface CandidateClip {
  id: string;
  title: string;
  hookSummary: string;
  startSec: number;
  endSec: number;
  durationSec: number;
  viralScore: number;
  reason: string;
  suggestedHashtags: string[];
  detectedMood: string;
  snappedToScene: boolean;
}

export interface TranscribeRequest {
  whisperModel?: string;
  language?: string;
  translate?: boolean;
  hotwords?: string;
  initialPrompt?: string;
  useWhisperx?: boolean;
}

export interface DiscoverClipsRequest {
  ollamaModel?: string;
  minDurationSec?: number;
  maxDurationSec?: number;
  maxClips?: number;
  customPrompt?: string;
}

export interface ProjectRead {
  id: string;
  title: string;
  sourceType: 'url' | 'local';
  sourceUrl: string | null;
  downloadMode: 'full' | 'fast_vod' | 'local';
  status:
    | 'pending'
    | 'downloading'
    | 'extracting_audio'
    | 'analyzing_engagement'
    | 'transcribing'
    | 'detecting_scenes'
    | 'scoring_clips'
    | 'ready'
    | 'error'
    | 'cancelled';
  progressPercent: number;
  currentStage: string;
  videoPath: string | null;
  audioPath: string | null;
  thumbnailPath: string | null;
  durationSec: number | null;
  width: number | null;
  height: number | null;
  fps: number | null;
  fileSizeBytes: number | null;
  engagementSignals: EngagementSignals | null;
  hasTranscript: boolean;
  hasSceneCuts: boolean;
  candidateClips: CandidateClip[];
  whisperModelUsed: string | null;
  ollamaModelUsed: string | null;
  errorMessage: string | null;
  activePid: number | null;
  createdAt: string;
  updatedAt: string;
}

export interface ProjectSummary {
  id: string;
  title: string;
  sourceType: string;
  status: string;
  progressPercent: number;
  durationSec: number | null;
  hasTranscript: boolean;
  clipsCount: number;
  createdAt: string;
}

export interface IngestUrlRequest {
  url: string;
  downloadMode: 'full' | 'fast_vod';
  fetchChatReplay?: boolean;
}

// ============================================================
// Phase 4 — Framing & Profiles
// ============================================================

export interface RegionBox {
  x: number; // 0.0–1.0 fraction of source width
  y: number; // 0.0–1.0 fraction of source height
  w: number;
  h: number;
}

export type FramingMode = 'gaming' | 'podcast' | 'talking_head' | 'screen_presenter' | 'reaction';
export type AspectRatio = '9:16' | '1:1' | '16:9';
export type LayoutTemplate = 'split_vertical' | 'fullscreen_crop' | 'blurred_fill' | 'pip';

export interface WatermarkConfig {
  path: string | null;
  corner: 'top_left' | 'top_right' | 'bottom_left' | 'bottom_right';
  scale: number;   // 0.01–1.0 fraction of output width
  opacity: number; // 0.0–1.0
}

export interface FramingConfig {
  framingMode: FramingMode;
  aspectRatio: AspectRatio;
  layoutTemplate: LayoutTemplate;
  facecamBox: RegionBox | null;
  gameplayBox: RegionBox | null;
  splitRatio: number; // 10–90 (top pane %)
  watermark: WatermarkConfig | null;
  faceDetected?: boolean | null;
}

export interface SavedProfile {
  id: string;
  name: string;
  framingMode: FramingMode;
  aspectRatio: AspectRatio;
  layoutTemplate: LayoutTemplate;
  facecamBox: RegionBox | null;
  gameplayBox: RegionBox | null;
  splitRatio: number;
  watermark: WatermarkConfig | null;
  ollamaPrompt: string | null;
  captionStyle: string;
  createdAt: string;
  updatedAt: string;
}

export interface AutoDetectResult {
  facecamBox: RegionBox | null;
  gameplayBox: RegionBox | null;
  faceCount: number;
  faceConfidence: number;
  modeSuggestion: FramingMode;
  message: string;
}

export interface RenderRequest {
  clipId?: string;
  startSec: number;
  endSec: number;
  framingConfig: FramingConfig;
  profileId?: string;
  outputFilename?: string;
}

export interface RenderResponse {
  projectId: string;
  outputPath: string;
  outputFilename: string;
  durationSec: number;
  framingMode: string;
  encoderUsed: string;
  message: string;
}

