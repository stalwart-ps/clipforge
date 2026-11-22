export interface GPUInfo {
  hasGpu: boolean;
  gpuName: string | null;
  driverVersion: string | null;
  cudaVersion: string | null;
  vramTotalMb: number | null;
  vramUsedMb: number | null;
  vramFreeMb: number | null;
  temperatureC: number | null;
  gpuUtilizationPercent: number | null;
  status: 'optimal' | 'high_usage' | 'not_detected' | 'error';
}

export interface FFmpegInfo {
  isInstalled: boolean;
  version: string | null;
  hasLibx264: boolean;
  hasH264Nvenc: boolean;
  hasHevcNvenc: boolean;
  hasLibass: boolean;
  status: 'ready' | 'ready_cpu_only' | 'missing';
}

export interface OllamaModel {
  name: string;
  sizeBytes: number | null;
  parameterSize: string | null;
  modifiedAt: string | null;
}

export interface OllamaInfo {
  isReachable: boolean;
  url: string;
  models: OllamaModel[];
  status: 'connected' | 'disconnected' | 'empty';
}

export interface YtDlpInfo {
  isInstalled: boolean;
  version: string | null;
  hasJsRuntime: boolean;
  jsRuntimeType: 'deno' | 'node' | 'none' | null;
  jsRuntimeVersion: string | null;
  status: 'ready' | 'warning_no_js' | 'missing';
}

export interface SystemDiagnosticsResponse {
  gpu: GPUInfo;
  ffmpeg: FFmpegInfo;
  ollama: OllamaInfo;
  ytdlp: YtDlpInfo;
  recommendedPreset: 'lite' | 'balanced' | 'pro';
  timestamp: string;
}

export interface SettingsRead {
  id: number;
  hardwarePreset: 'lite' | 'balanced' | 'pro' | 'custom';
  whisperModel: string;
  ollamaModel: string;
  encoder: string;
  jsRuntime: string;
  cookiesBrowser: string | null;
  cookiesFilePath: string | null;
  poToken: string | null;
  minClipDurationSec: number;
  maxClipDurationSec: number;
}

export interface SettingsUpdate {
  hardwarePreset?: 'lite' | 'balanced' | 'pro' | 'custom';
  whisperModel?: string;
  ollamaModel?: string;
  encoder?: string;
  jsRuntime?: string;
  cookiesBrowser?: string | null;
  cookiesFilePath?: string | null;
  poToken?: string | null;
  minClipDurationSec?: number;
  maxClipDurationSec?: number;
}

export interface CacheStatsResponse {
  cacheDir: string;
  totalBytes: number;
  totalMb: number;
  fileCount: number;
}

export interface CleanCacheResponse {
  reclaimedBytes: number;
  reclaimedMb: number;
  filesDeleted: number;
  message: string;
}

export interface YtDlpUpdateResponse {
  success: boolean;
  oldVersion: string | null;
  newVersion: string | null;
  output: string;
}
