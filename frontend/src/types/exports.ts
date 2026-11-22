import { CaptionConfig, FramingConfig } from './project';

export interface ExportClipRequest {
  clipId: string;
  title: string;
  hookSummary: string;
  suggestedHashtags: string[];
  startSec: number;
  endSec: number;
}

export interface ExportSidecars {
  srt: boolean;
  ass: boolean;
  metadataJson: boolean;
  metadataTxt: boolean;
}

export interface ExportOptions {
  normalizeLoudness: boolean;
  removeSilence: boolean;
  silenceThresholdDb: number;
  silenceMinDurationSec: number;
  sidecars: ExportSidecars;
  captionConfig: CaptionConfig;
  framingConfig: FramingConfig;
}

export interface ExportJob {
  id: string;
  projectId: string;
  status: 'queued' | 'running' | 'completed' | 'cancelled' | 'error';
  progressPercent: number;
  currentClip: string | null;
  completedClips: number;
  totalClips: number;
  outputFiles: string[];
  error: string | null;
  createdAt: string;
  updatedAt: string;
}

