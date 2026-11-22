import {
  CacheStatsResponse,
  CleanCacheResponse,
  SettingsRead,
  SettingsUpdate,
  SystemDiagnosticsResponse,
  YtDlpUpdateResponse,
} from '../types/diagnostics';
import {
  AutoDetectResult,
  DiscoverClipsRequest,
  FramingConfig,
  IngestUrlRequest,
  ProjectRead,
  ProjectSummary,
  RenderRequest,
  RenderResponse,
  SavedProfile,
  TranscribeRequest,
  TranscriptData,
  TranscriptSegment,
  CandidateClip,
} from '../types/project';

const BASE_URL = '';

async function handleResponse<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const errorBody = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(errorBody.detail || `Request failed with status ${res.status}`);
  }
  return res.json();
}

export const api = {
  // Diagnostics & Settings
  async getDiagnostics(): Promise<SystemDiagnosticsResponse> {
    const res = await fetch(`${BASE_URL}/api/diagnostics`);
    return handleResponse<SystemDiagnosticsResponse>(res);
  },

  async updateYtDlp(): Promise<YtDlpUpdateResponse> {
    const res = await fetch(`${BASE_URL}/api/diagnostics/update-ytdlp`, {
      method: 'POST',
    });
    return handleResponse<YtDlpUpdateResponse>(res);
  },

  async getSettings(): Promise<SettingsRead> {
    const res = await fetch(`${BASE_URL}/api/settings`);
    return handleResponse<SettingsRead>(res);
  },

  async updateSettings(payload: SettingsUpdate): Promise<SettingsRead> {
    const res = await fetch(`${BASE_URL}/api/settings`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    return handleResponse<SettingsRead>(res);
  },

  async getCacheStats(): Promise<CacheStatsResponse> {
    const res = await fetch(`${BASE_URL}/api/cache/stats`);
    return handleResponse<CacheStatsResponse>(res);
  },

  async cleanCache(): Promise<CleanCacheResponse> {
    const res = await fetch(`${BASE_URL}/api/cache/clean`, {
      method: 'POST',
    });
    return handleResponse<CleanCacheResponse>(res);
  },

  // Phase 2: Ingestion & Projects
  async ingestUrl(payload: IngestUrlRequest): Promise<ProjectRead> {
    const res = await fetch(`${BASE_URL}/api/projects/url`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    return handleResponse<ProjectRead>(res);
  },

  async uploadLocalFile(file: File): Promise<ProjectRead> {
    const formData = new FormData();
    formData.append('file', file);
    const res = await fetch(`${BASE_URL}/api/projects/upload`, {
      method: 'POST',
      body: formData,
    });
    return handleResponse<ProjectRead>(res);
  },

  async listProjects(): Promise<ProjectSummary[]> {
    const res = await fetch(`${BASE_URL}/api/projects`);
    return handleResponse<ProjectSummary[]>(res);
  },

  async getProject(projectId: string): Promise<ProjectRead> {
    const res = await fetch(`${BASE_URL}/api/projects/${projectId}`);
    return handleResponse<ProjectRead>(res);
  },

  async cancelProject(projectId: string): Promise<{ success: boolean; message: string }> {
    const res = await fetch(`${BASE_URL}/api/projects/${projectId}/cancel`, {
      method: 'POST',
    });
    return handleResponse<{ success: boolean; message: string }>(res);
  },

  // Phase 3: Transcription & Ollama Scoring
  async transcribeProject(projectId: string, payload: TranscribeRequest = {}): Promise<ProjectRead> {
    const res = await fetch(`${BASE_URL}/api/projects/${projectId}/transcribe`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    return handleResponse<ProjectRead>(res);
  },

  async detectScenes(projectId: string): Promise<ProjectRead> {
    const res = await fetch(`${BASE_URL}/api/projects/${projectId}/detect-scenes`, {
      method: 'POST',
    });
    return handleResponse<ProjectRead>(res);
  },

  async discoverClips(projectId: string, payload: DiscoverClipsRequest = {}): Promise<ProjectRead> {
    const res = await fetch(`${BASE_URL}/api/projects/${projectId}/discover-clips`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    return handleResponse<ProjectRead>(res);
  },

  async getTranscript(projectId: string): Promise<TranscriptData> {
    const res = await fetch(`${BASE_URL}/api/projects/${projectId}/transcript`);
    return handleResponse<TranscriptData>(res);
  },

  async updateTranscript(projectId: string, segments: TranscriptSegment[]): Promise<TranscriptData> {
    const res = await fetch(`${BASE_URL}/api/projects/${projectId}/transcript`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ segments }),
    });
    return handleResponse<TranscriptData>(res);
  },

  async getClips(projectId: string): Promise<CandidateClip[]> {
    const res = await fetch(`${BASE_URL}/api/projects/${projectId}/clips`);
    return handleResponse<CandidateClip[]>(res);
  },

  getVideoStreamUrl(projectId: string): string {
    return `${BASE_URL}/api/projects/${projectId}/stream`;
  },

  getProjectWebSocketUrl(projectId: string): string {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const host = window.location.host || '127.0.0.1:8000';
    return `${protocol}//${host}/api/projects/ws/${projectId}`;
  },

  // Phase 4: Framing & Layout Studio
  getFrameUrl(projectId: string, timeSec: number): string {
    return `${BASE_URL}/api/projects/${projectId}/frame?t=${timeSec}`;
  },

  async autoDetectRegions(projectId: string, timeSec: number = 5.0): Promise<AutoDetectResult> {
    const res = await fetch(
      `${BASE_URL}/api/projects/${projectId}/auto-detect-regions?t=${timeSec}`,
      { method: 'POST' }
    );
    return handleResponse<AutoDetectResult>(res);
  },

  async renderClip(projectId: string, payload: RenderRequest): Promise<RenderResponse> {
    const res = await fetch(`${BASE_URL}/api/projects/${projectId}/render`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    return handleResponse<RenderResponse>(res);
  },

  // Phase 4: Saved Profiles CRUD
  async listProfiles(): Promise<SavedProfile[]> {
    const res = await fetch(`${BASE_URL}/api/profiles`);
    return handleResponse<SavedProfile[]>(res);
  },

  async createProfile(payload: Partial<SavedProfile> & { name: string }): Promise<SavedProfile> {
    const res = await fetch(`${BASE_URL}/api/profiles`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    return handleResponse<SavedProfile>(res);
  },

  async updateProfile(profileId: string, payload: Partial<SavedProfile>): Promise<SavedProfile> {
    const res = await fetch(`${BASE_URL}/api/profiles/${profileId}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    return handleResponse<SavedProfile>(res);
  },

  async deleteProfile(profileId: string): Promise<void> {
    await fetch(`${BASE_URL}/api/profiles/${profileId}`, { method: 'DELETE' });
  },
};
