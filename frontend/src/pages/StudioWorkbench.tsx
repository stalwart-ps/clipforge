import React, { useEffect, useRef, useState, useCallback } from 'react';
import {
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  Download,
  Edit3,
  Film,
  Flame,
  Globe,
  Play,
  Save,
  Scissors,
  Sparkles,
  StopCircle,
  Upload,
  Video,
  Wand2,
  Zap,
} from 'lucide-react';
import { api } from '../api/client';
import {
  ProjectRead,
  ProjectSummary,
  TranscriptData,
  TranscriptSegment,
} from '../types/project';

function formatDuration(sec: number | null): string {
  if (!sec || isNaN(sec)) return '0:00';
  const h = Math.floor(sec / 3600);
  const m = Math.floor((sec % 3600) / 60);
  const s = Math.floor(sec % 60);
  if (h > 0) {
    return `${h}:${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
  }
  return `${m}:${s.toString().padStart(2, '0')}`;
}

export const StudioWorkbench: React.FC = () => {
  // Ingest mode: 'url' or 'local'
  const [ingestTab, setIngestTab] = useState<'url' | 'local'>('url');
  const [urlInput, setUrlInput] = useState('');
  const [downloadMode, setDownloadMode] = useState<'full' | 'fast_vod'>('full');
  const [fetchChatReplay, setFetchChatReplay] = useState(true);

  // Active / Selected project
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [activeProject, setActiveProject] = useState<ProjectRead | null>(null);

  // Ingestion status states
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [isCancelling, setIsCancelling] = useState(false);

  // Phase 3: Transcription State
  const [whisperModel, setWhisperModel] = useState('base');
  const [language, setLanguage] = useState('auto');
  const [translate, setTranslate] = useState(false);
  const [hotwords, setHotwords] = useState('');
  const [isTranscribing, setIsTranscribing] = useState(false);

  // Phase 3: Transcript Typo Editor State
  const [showTranscript, setShowTranscript] = useState(false);
  const [transcriptData, setTranscriptData] = useState<TranscriptData | null>(null);
  const [editingSegments, setEditingSegments] = useState<TranscriptSegment[]>([]);
  const [isSavingTranscript, setIsSavingTranscript] = useState(false);
  const [transcriptSaveNotice, setTranscriptSaveNotice] = useState(false);

  // Phase 3: Ollama Clip Discovery State
  const [ollamaModel, setOllamaModel] = useState('qwen2.5:7b');
  const [minDuration, setMinDuration] = useState(15);
  const [maxDuration, setMaxDuration] = useState(60);
  const [maxClips, setMaxClips] = useState(5);
  const [customPrompt, setCustomPrompt] = useState('');
  const [isDiscovering, setIsDiscovering] = useState(false);

  // Live WebSocket state
  const [liveProgress, setLiveProgress] = useState<{
    percent: number;
    stage: string;
    speed?: string;
    eta?: number;
  } | null>(null);

  const wsRef = useRef<WebSocket | null>(null);
  const videoRef = useRef<HTMLVideoElement | null>(null);

  // Load project list
  const loadProjects = useCallback(async () => {
    try {
      const list = await api.listProjects();
      setProjects(list);
      if (list.length > 0 && !activeProject) {
        const full = await api.getProject(list[0].id);
        setActiveProject(full);
      }
    } catch (err) {
      console.error('Failed to load projects list:', err);
    }
  }, [activeProject]);

  useEffect(() => {
    loadProjects();
  }, [loadProjects]);

  // Connect WebSocket when active project is in progress
  useEffect(() => {
    if (!activeProject) return;

    const isInProgress = [
      'pending',
      'downloading',
      'extracting_audio',
      'analyzing_engagement',
      'transcribing',
      'detecting_scenes',
      'scoring_clips',
    ].includes(activeProject.status);

    if (isInProgress) {
      const wsUrl = api.getProjectWebSocketUrl(activeProject.id);
      const ws = new WebSocket(wsUrl);
      wsRef.current = ws;

      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          if (data.type === 'progress') {
            setLiveProgress({
              percent: data.percent,
              stage: data.message || data.stage,
              speed: data.speed,
              eta: data.eta,
            });
          } else if (data.type === 'complete' || data.type === 'cancelled' || data.type === 'error') {
            api.getProject(activeProject.id).then((p) => {
              setActiveProject(p);
              setLiveProgress(null);
              setIsTranscribing(false);
              setIsDiscovering(false);
              loadProjects();
            });
          }
        } catch {
          // heartbeat
        }
      };

      return () => {
        ws.close();
      };
    }
  }, [activeProject?.id, activeProject?.status, loadProjects]);

  // Load transcript data when viewer is opened
  const handleToggleTranscript = async () => {
    if (!activeProject) return;
    if (!showTranscript && activeProject.hasTranscript) {
      try {
        const t = await api.getTranscript(activeProject.id);
        setTranscriptData(t);
        setEditingSegments(t.segments);
      } catch (err) {
        console.error('Failed to load transcript:', err);
      }
    }
    setShowTranscript(!showTranscript);
  };

  const handleSaveTranscript = async () => {
    if (!activeProject) return;
    setIsSavingTranscript(true);
    try {
      const updated = await api.updateTranscript(activeProject.id, editingSegments);
      setTranscriptData(updated);
      setTranscriptSaveNotice(true);
      setTimeout(() => setTranscriptSaveNotice(false), 3000);
    } catch (err) {
      console.error('Failed to save transcript:', err);
    } finally {
      setIsSavingTranscript(false);
    }
  };

  const handleRunTranscription = async () => {
    if (!activeProject) return;
    setIsTranscribing(true);
    try {
      const updated = await api.transcribeProject(activeProject.id, {
        whisperModel,
        language: language === 'auto' ? undefined : language,
        translate,
        hotwords: hotwords.trim() || undefined,
      });
      setActiveProject(updated);
    } catch (err: any) {
      console.error('Failed to start transcription:', err);
      setIsTranscribing(false);
    }
  };

  const handleRunOllamaDiscovery = async () => {
    if (!activeProject) return;
    setIsDiscovering(true);
    try {
      const updated = await api.discoverClips(activeProject.id, {
        ollamaModel,
        minDurationSec: minDuration,
        maxDurationSec: maxDuration,
        maxClips,
        customPrompt: customPrompt.trim() || undefined,
      });
      setActiveProject(updated);
    } catch (err: any) {
      console.error('Failed to start Ollama clip discovery:', err);
      setIsDiscovering(false);
    }
  };

  const handleUrlSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!urlInput.trim()) return;

    setIsSubmitting(true);
    setSubmitError(null);
    try {
      const created = await api.ingestUrl({
        url: urlInput.trim(),
        downloadMode,
        fetchChatReplay,
      });
      setActiveProject(created);
      setUrlInput('');
      loadProjects();
    } catch (err: any) {
      setSubmitError(err.message || 'Failed to start ingestion');
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleFileUpload = async (file: File) => {
    setIsSubmitting(true);
    setSubmitError(null);
    try {
      const created = await api.uploadLocalFile(file);
      setActiveProject(created);
      loadProjects();
    } catch (err: any) {
      setSubmitError(err.message || 'Failed to upload video');
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleCancelJob = async () => {
    if (!activeProject) return;
    setIsCancelling(true);
    try {
      await api.cancelProject(activeProject.id);
      const updated = await api.getProject(activeProject.id);
      setActiveProject(updated);
      setLiveProgress(null);
      setIsTranscribing(false);
      setIsDiscovering(false);
      loadProjects();
    } catch (err: any) {
      console.error('Failed to cancel job:', err);
    } finally {
      setIsCancelling(false);
    }
  };

  const handleSelectProject = async (id: string) => {
    try {
      const p = await api.getProject(id);
      setActiveProject(p);
      setLiveProgress(null);
      setShowTranscript(false);
    } catch (err) {
      console.error('Failed to switch project:', err);
    }
  };

  const handleJumpToTime = (timeSec: number) => {
    if (videoRef.current) {
      videoRef.current.currentTime = timeSec;
      videoRef.current.play().catch(() => {});
    }
  };

  const signals = activeProject?.engagementSignals;
  const duration = activeProject?.durationSec || 1.0;
  const clips = activeProject?.candidateClips || [];

  return (
    <div className="space-y-8 max-w-7xl mx-auto pb-16">
      {/* Title */}
      <div>
        <h1 className="text-2xl font-bold tracking-tight text-slate-100 flex items-center gap-2.5">
          <Film className="w-6 h-6 text-cyan-400" />
          <span>ClipForge Studio Workbench</span>
        </h1>
        <p className="text-sm text-slate-400 mt-1">
          Dual Ingestion (Phase 2) → Subprocess-Isolated Whisper STT & PySceneDetect → Ollama AI Clip Scoring (Phase 3).
        </p>
      </div>

      {/* Grid: Ingestion & Projects (Left) vs Player & Phase 3 Controls (Right) */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-8">
        {/* Left Column (5 cols): Ingestion & Projects */}
        <div className="lg:col-span-5 space-y-6">
          <div className="bg-surface border border-border rounded-xl p-5 space-y-4">
            <div className="flex items-center gap-2 border-b border-border-subtle pb-3">
              <button
                onClick={() => setIngestTab('url')}
                className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-all ${
                  ingestTab === 'url'
                    ? 'bg-cyan-500/20 text-cyan-400 border border-cyan-500/40'
                    : 'text-slate-400 hover:text-slate-200'
                }`}
              >
                <Globe className="w-3.5 h-3.5" />
                <span>Web Link (yt-dlp)</span>
              </button>

              <button
                onClick={() => setIngestTab('local')}
                className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-all ${
                  ingestTab === 'local'
                    ? 'bg-cyan-500/20 text-cyan-400 border border-cyan-500/40'
                    : 'text-slate-400 hover:text-slate-200'
                }`}
              >
                <Upload className="w-3.5 h-3.5" />
                <span>Local File Upload</span>
              </button>
            </div>

            {ingestTab === 'url' ? (
              <form onSubmit={handleUrlSubmit} className="space-y-4">
                <div>
                  <label className="block text-xs font-mono text-slate-300 mb-1">Video Stream URL</label>
                  <input
                    type="url"
                    value={urlInput}
                    onChange={(e) => setUrlInput(e.target.value)}
                    placeholder="https://www.youtube.com/watch?v=..."
                    className="w-full bg-surface-elevated border border-border rounded-lg px-3 py-2 text-xs font-mono text-slate-100 placeholder:text-slate-500 focus:outline-none focus:border-cyan-500"
                    required
                  />
                </div>

                <div>
                  <label className="block text-xs font-mono text-slate-300 mb-1.5">Download Mode</label>
                  <div className="grid grid-cols-2 gap-2">
                    <button
                      type="button"
                      onClick={() => setDownloadMode('full')}
                      className={`p-2 rounded-lg border text-left transition-all ${
                        downloadMode === 'full'
                          ? 'bg-cyan-950/40 border-cyan-500 text-slate-100'
                          : 'bg-surface-elevated border-border text-slate-400'
                      }`}
                    >
                      <div className="text-xs font-bold text-cyan-400 flex items-center gap-1">
                        <Download className="w-3 h-3" /> Full Download
                      </div>
                      <div className="text-[10px] text-slate-400 font-mono mt-0.5">Best video + audio</div>
                    </button>

                    <button
                      type="button"
                      onClick={() => setDownloadMode('fast_vod')}
                      className={`p-2 rounded-lg border text-left transition-all ${
                        downloadMode === 'fast_vod'
                          ? 'bg-cyan-950/40 border-cyan-500 text-slate-100'
                          : 'bg-surface-elevated border-border text-slate-400'
                      }`}
                    >
                      <div className="text-xs font-bold text-cyan-400 flex items-center gap-1">
                        <Zap className="w-3 h-3" /> Fast VOD Mode
                      </div>
                      <div className="text-[10px] text-slate-400 font-mono mt-0.5">Audio & signals first</div>
                    </button>
                  </div>
                </div>

                <div className="flex items-center gap-2 pt-1">
                  <input
                    type="checkbox"
                    id="chatReplayCheck"
                    checked={fetchChatReplay}
                    onChange={(e) => setFetchChatReplay(e.target.checked)}
                    className="rounded border-border bg-surface-elevated text-cyan-500"
                  />
                  <label htmlFor="chatReplayCheck" className="text-xs text-slate-300 font-mono cursor-pointer">
                    Extract chat replays & comment timestamps
                  </label>
                </div>

                {submitError && (
                  <div className="p-3 rounded-lg bg-rose-950/50 border border-rose-800 text-rose-300 text-xs font-mono">
                    {submitError}
                  </div>
                )}

                <button
                  type="submit"
                  disabled={isSubmitting || !urlInput.trim()}
                  className="w-full py-2.5 rounded-lg bg-cyan-500 hover:bg-cyan-400 text-black font-semibold text-xs transition-all active:scale-95 disabled:opacity-50"
                >
                  {isSubmitting ? 'Launching Worker...' : 'Start Video Ingestion'}
                </button>
              </form>
            ) : (
              <div className="space-y-4">
                <div
                  onDragOver={(e) => e.preventDefault()}
                  onDrop={(e) => {
                    e.preventDefault();
                    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
                      handleFileUpload(e.dataTransfer.files[0]);
                    }
                  }}
                  className="border-2 border-dashed border-border hover:border-cyan-500/80 rounded-xl p-8 text-center transition-all bg-surface-elevated cursor-pointer"
                  onClick={() => document.getElementById('localFileInput')?.click()}
                >
                  <input
                    id="localFileInput"
                    type="file"
                    accept=".mp4,.mov,.mkv,.webm"
                    className="hidden"
                    onChange={(e) => {
                      if (e.target.files && e.target.files[0]) {
                        handleFileUpload(e.target.files[0]);
                      }
                    }}
                  />
                  <Upload className="w-8 h-8 text-slate-400 mx-auto mb-2" />
                  <p className="text-xs font-semibold text-slate-200">Drag & drop video here</p>
                  <p className="text-[11px] text-slate-400 font-mono mt-1">.mp4, .mov, .mkv, .webm</p>
                </div>
              </div>
            )}
          </div>

          {/* Project List */}
          <div className="bg-surface border border-border rounded-xl p-5 space-y-3">
            <h3 className="text-xs font-mono uppercase tracking-wider text-slate-400 font-semibold">
              Recent Projects ({projects.length})
            </h3>
            <div className="space-y-1.5 max-h-56 overflow-y-auto">
              {projects.map((p) => (
                <div
                  key={p.id}
                  onClick={() => handleSelectProject(p.id)}
                  className={`p-2.5 rounded-lg border text-xs font-mono cursor-pointer transition-all flex items-center justify-between ${
                    activeProject?.id === p.id
                      ? 'bg-cyan-950/40 border-cyan-500/70 text-slate-100'
                      : 'bg-surface-elevated border-border-subtle hover:border-slate-600 text-slate-300'
                  }`}
                >
                  <div className="truncate pr-2">
                    <div className="font-semibold text-slate-100 truncate">{p.title}</div>
                    <div className="text-[10px] text-slate-400 flex items-center gap-2 mt-0.5">
                      <span className="uppercase">{p.sourceType}</span>
                      {p.durationSec ? <span>{formatDuration(p.durationSec)}</span> : null}
                      {p.hasTranscript ? <span className="text-emerald-400">✓ Transcribed</span> : null}
                    </div>
                  </div>
                  <span
                    className={`text-[10px] px-1.5 py-0.5 rounded-full flex-shrink-0 ${
                      p.status === 'ready'
                        ? 'bg-emerald-950 text-emerald-400 border border-emerald-800'
                        : 'bg-amber-950 text-amber-400 border border-amber-800 animate-pulse'
                    }`}
                  >
                    {p.status}
                  </span>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* Right Column (7 cols): Active Player & Phase 3 Workflows */}
        <div className="lg:col-span-7 space-y-6">
          {activeProject ? (
            <div className="bg-surface border border-border rounded-xl p-6 space-y-6">
              {/* Project Header */}
              <div className="flex items-start justify-between border-b border-border-subtle pb-4">
                <div>
                  <div className="flex items-center gap-2">
                    <span
                      className={`text-[10px] font-mono px-2 py-0.5 rounded-full uppercase ${
                        activeProject.status === 'ready'
                          ? 'bg-emerald-950 text-emerald-400 border border-emerald-800'
                          : 'bg-cyan-950 text-cyan-400 border border-cyan-800 animate-pulse'
                      }`}
                    >
                      {activeProject.status}
                    </span>
                    <span className="text-xs font-mono text-slate-400">{activeProject.id}</span>
                  </div>
                  <h2 className="text-lg font-bold text-slate-100 mt-1">{activeProject.title}</h2>
                </div>

                {['pending', 'downloading', 'extracting_audio', 'transcribing', 'scoring_clips'].includes(
                  activeProject.status
                ) && (
                  <button
                    onClick={handleCancelJob}
                    disabled={isCancelling}
                    className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-rose-950/60 hover:bg-rose-900 border border-rose-800 text-rose-300 text-xs font-mono transition-all"
                  >
                    <StopCircle className="w-3.5 h-3.5 text-rose-400" />
                    <span>{isCancelling ? 'Killing Tree...' : 'Cancel Job'}</span>
                  </button>
                )}
              </div>

              {/* Progress Bar */}
              {['pending', 'downloading', 'extracting_audio', 'transcribing', 'scoring_clips'].includes(
                activeProject.status
              ) && (
                <div className="p-4 rounded-xl bg-surface-elevated border border-cyan-900/60 space-y-2">
                  <div className="flex justify-between items-center text-xs font-mono">
                    <span className="text-cyan-400 font-semibold flex items-center gap-1.5">
                      <Zap className="w-3.5 h-3.5 animate-bounce" />
                      {liveProgress?.stage || activeProject.currentStage}
                    </span>
                    <span className="text-slate-200">
                      {liveProgress?.percent || activeProject.progressPercent}%
                    </span>
                  </div>
                  <div className="w-full h-2 bg-surface rounded-full overflow-hidden border border-border-subtle">
                    <div
                      className="h-full bg-gradient-to-r from-cyan-500 to-blue-500 transition-all duration-300 rounded-full"
                      style={{
                        width: `${Math.max(5, liveProgress?.percent || activeProject.progressPercent)}%`,
                      }}
                    />
                  </div>
                </div>
              )}

              {/* Video Player */}
              {activeProject.videoPath && (
                <div className="space-y-4">
                  <div className="relative rounded-xl overflow-hidden bg-black border border-border aspect-video flex items-center justify-center">
                    <video
                      ref={videoRef}
                      controls
                      preload="metadata"
                      src={api.getVideoStreamUrl(activeProject.id)}
                      className="w-full h-full object-contain"
                    />
                  </div>

                  {/* Engagement Signal Timeline */}
                  {signals && (
                    <div className="bg-surface-elevated border border-border rounded-xl p-4 space-y-2">
                      <div className="flex items-center justify-between text-xs font-mono">
                        <span className="font-bold text-slate-200 flex items-center gap-1.5">
                          <Flame className="w-4 h-4 text-amber-400" />
                          <span>Engagement Timeline (Heatmaps & Hype Spikes)</span>
                        </span>
                        <div className="flex items-center gap-3 text-[10px]">
                          <span className="text-cyan-400">■ Heatmap</span>
                          <span className="text-amber-400">● Comment</span>
                          <span className="text-pink-400">■ Loudness</span>
                        </div>
                      </div>

                      <div className="relative h-12 bg-surface rounded-lg border border-border-subtle overflow-hidden flex items-end px-1 cursor-pointer">
                        {signals.audioEnergy.map((pt, idx) => (
                          <div
                            key={`ae_${idx}`}
                            onClick={() => handleJumpToTime(pt.timeSec)}
                            title={`[${formatDuration(pt.timeSec)}] Loudness Spike: ${pt.score}%`}
                            className="absolute bottom-0 w-1 bg-pink-500/60 hover:bg-pink-400 rounded-t z-10"
                            style={{
                              left: `${(pt.timeSec / duration) * 100}%`,
                              height: `${Math.max(10, pt.score)}%`,
                            }}
                          />
                        ))}
                        {signals.heatmap.map((pt, idx) => (
                          <div
                            key={`hm_${idx}`}
                            onClick={() => handleJumpToTime(pt.timeSec)}
                            title={`[${formatDuration(pt.timeSec)}] Heatmap: ${pt.score}%`}
                            className="absolute bottom-0 w-1 bg-cyan-400/80 hover:bg-cyan-300 rounded-t z-20"
                            style={{
                              left: `${(pt.timeSec / duration) * 100}%`,
                              height: `${Math.max(10, pt.score)}%`,
                            }}
                          />
                        ))}
                        {signals.commentTimestamps.map((pt, idx) => (
                          <div
                            key={`cm_${idx}`}
                            onClick={() => handleJumpToTime(pt.timeSec)}
                            title={`[${formatDuration(pt.timeSec)}] "${pt.label}"`}
                            className="absolute top-1 w-2.5 h-2.5 rounded-full bg-amber-400 border border-black z-30"
                            style={{ left: `${(pt.timeSec / duration) * 100}%` }}
                          />
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              )}

              {/* ==================================================== */}
              {/* Phase 3: AI Transcription & Word-Level Typo Editor */}
              {/* ==================================================== */}
              <div className="bg-surface-elevated border border-border rounded-xl p-5 space-y-4">
                <div className="flex items-center justify-between">
                  <div>
                    <h3 className="text-sm font-bold text-slate-100 flex items-center gap-2">
                      <Scissors className="w-4 h-4 text-cyan-400" />
                      <span>Stage 1: faster-whisper Speech-to-Text</span>
                    </h3>
                    <p className="text-xs text-slate-400 font-mono mt-0.5">
                      Subprocess-isolated STT with Silero VAD & word-level timestamps.
                    </p>
                  </div>

                  {activeProject.hasTranscript && (
                    <span className="text-xs font-mono bg-emerald-950 text-emerald-400 border border-emerald-800 px-2 py-0.5 rounded-full flex items-center gap-1">
                      <CheckCircle2 className="w-3.5 h-3.5" /> Transcribed ({activeProject.whisperModelUsed || 'base'})
                    </span>
                  )}
                </div>

                {/* Transcription Settings Form */}
                <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                  <div>
                    <label className="block text-[11px] font-mono text-slate-400 mb-1">Whisper Model</label>
                    <select
                      value={whisperModel}
                      onChange={(e) => setWhisperModel(e.target.value)}
                      className="w-full bg-surface border border-border rounded px-2.5 py-1.5 text-xs font-mono text-slate-200"
                    >
                      <option value="tiny">tiny (Fastest, INT8)</option>
                      <option value="base">base (Light, Default)</option>
                      <option value="small">small (Balanced, CUDA)</option>
                      <option value="medium">medium (Accurate)</option>
                      <option value="large-v3-turbo">large-v3-turbo (Pro)</option>
                    </select>
                  </div>

                  <div>
                    <label className="block text-[11px] font-mono text-slate-400 mb-1">Language</label>
                    <select
                      value={language}
                      onChange={(e) => setLanguage(e.target.value)}
                      className="w-full bg-surface border border-border rounded px-2.5 py-1.5 text-xs font-mono text-slate-200"
                    >
                      <option value="auto">Auto-Detect</option>
                      <option value="en">English (en)</option>
                      <option value="es">Spanish (es)</option>
                      <option value="fr">French (fr)</option>
                      <option value="de">German (de)</option>
                      <option value="ja">Japanese (ja)</option>
                    </select>
                  </div>

                  <div>
                    <label className="block text-[11px] font-mono text-slate-400 mb-1">Hotwords / Names</label>
                    <input
                      type="text"
                      value={hotwords}
                      onChange={(e) => setHotwords(e.target.value)}
                      placeholder="Streamer, game slang..."
                      className="w-full bg-surface border border-border rounded px-2.5 py-1.5 text-xs font-mono text-slate-200"
                    />
                  </div>
                </div>

                <div className="flex items-center justify-between pt-1">
                  <div className="flex items-center gap-2">
                    <input
                      type="checkbox"
                      id="translateCheck"
                      checked={translate}
                      onChange={(e) => setTranslate(e.target.checked)}
                      className="rounded border-border bg-surface text-cyan-500"
                    />
                    <label htmlFor="translateCheck" className="text-xs text-slate-300 font-mono cursor-pointer">
                      Translate speech to English
                    </label>
                  </div>

                  <div className="flex items-center gap-2">
                    {activeProject.hasTranscript && (
                      <button
                        onClick={handleToggleTranscript}
                        className="px-3 py-1.5 rounded-lg bg-surface border border-border text-xs font-mono text-slate-300 hover:text-cyan-400 flex items-center gap-1.5 transition-all"
                      >
                        <Edit3 className="w-3.5 h-3.5" />
                        <span>{showTranscript ? 'Hide Transcript' : 'Edit Transcript'}</span>
                        {showTranscript ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
                      </button>
                    )}

                    <button
                      onClick={handleRunTranscription}
                      disabled={isTranscribing}
                      className="px-4 py-1.5 rounded-lg bg-cyan-500 hover:bg-cyan-400 text-black font-semibold text-xs font-mono transition-all disabled:opacity-50"
                    >
                      {isTranscribing ? 'Transcribing...' : activeProject.hasTranscript ? 'Re-Transcribe' : 'Run Transcription'}
                    </button>
                  </div>
                </div>

                {/* Inline Typo Editor Drawer */}
                {showTranscript && (
                  <div className="border-t border-border-subtle pt-4 space-y-3">
                    <div className="flex items-center justify-between">
                      <span className="text-xs font-mono font-semibold text-slate-300">
                        Word-Level Transcript ({editingSegments.length} Segments{transcriptData?.language ? ` • Lang: ${transcriptData.language.toUpperCase()}` : ''})
                      </span>
                      <div className="flex items-center gap-2">
                        {transcriptSaveNotice && (
                          <span className="text-xs text-emerald-400 font-mono">✓ Saved to SQLite</span>
                        )}
                        <button
                          onClick={handleSaveTranscript}
                          disabled={isSavingTranscript}
                          className="px-3 py-1 rounded bg-emerald-600 hover:bg-emerald-500 text-black font-bold text-xs font-mono flex items-center gap-1 transition-all"
                        >
                          <Save className="w-3.5 h-3.5" /> Save Edits
                        </button>
                      </div>
                    </div>

                    <div className="max-h-56 overflow-y-auto space-y-2 pr-1">
                      {editingSegments.map((seg, sIdx) => (
                        <div key={seg.id} className="p-2.5 rounded bg-surface border border-border-subtle text-xs font-mono space-y-1">
                          <div className="flex items-center justify-between text-[11px] text-slate-400">
                            <span
                              onClick={() => handleJumpToTime(seg.start)}
                              className="text-cyan-400 hover:underline cursor-pointer"
                            >
                              [{formatDuration(seg.start)} - {formatDuration(seg.end)}]
                            </span>
                            <span>Seg #{sIdx + 1}</span>
                          </div>
                          <input
                            type="text"
                            value={seg.text}
                            onChange={(e) => {
                              const newSegs = [...editingSegments];
                              newSegs[sIdx].text = e.target.value;
                              setEditingSegments(newSegs);
                            }}
                            className="w-full bg-surface-elevated border border-border-subtle rounded px-2 py-1 text-xs text-slate-200 focus:outline-none focus:border-cyan-500"
                          />
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>

              {/* ==================================================== */}
              {/* Phase 3: Ollama Clip Discovery Engine */}
              {/* ==================================================== */}
              <div className="bg-surface-elevated border border-border rounded-xl p-5 space-y-4">
                <div className="flex items-center justify-between">
                  <div>
                    <h3 className="text-sm font-bold text-slate-100 flex items-center gap-2">
                      <Wand2 className="w-4 h-4 text-violet-400" />
                      <span>Stage 2: Ollama Clip Discovery Engine</span>
                    </h3>
                    <p className="text-xs text-slate-400 font-mono mt-0.5">
                      Fuses transcript chunks with audience retention peaks & flushes VRAM via keep_alive: 0.
                    </p>
                  </div>
                  {activeProject.hasTranscript && (
                    <span className="text-[11px] text-cyan-400 font-mono bg-cyan-950/60 border border-cyan-800 px-2 py-0.5 rounded">
                      Stage Cache Active
                    </span>
                  )}
                </div>

                <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                  <div>
                    <label className="block text-[11px] font-mono text-slate-400 mb-1">Ollama Model</label>
                    <select
                      value={ollamaModel}
                      onChange={(e) => setOllamaModel(e.target.value)}
                      className="w-full bg-surface border border-border rounded px-2.5 py-1.5 text-xs font-mono text-slate-200"
                    >
                      <option value="qwen2.5:7b">qwen2.5:7b (Recommended)</option>
                      <option value="qwen2.5:3b">qwen2.5:3b (Lite)</option>
                      <option value="llama3.2:3b">llama3.2:3b</option>
                      <option value="llama3.1:8b">llama3.1:8b</option>
                    </select>
                  </div>

                  <div>
                    <label className="block text-[11px] font-mono text-slate-400 mb-1">
                      Clip Duration ({minDuration}s - {maxDuration}s)
                    </label>
                    <div className="flex items-center gap-2">
                      <input
                        type="range"
                        min="10"
                        max="30"
                        value={minDuration}
                        onChange={(e) => setMinDuration(Number(e.target.value))}
                        className="w-full accent-cyan-500"
                      />
                      <input
                        type="range"
                        min="30"
                        max="90"
                        value={maxDuration}
                        onChange={(e) => setMaxDuration(Number(e.target.value))}
                        className="w-full accent-cyan-500"
                      />
                    </div>
                  </div>

                  <div>
                    <label className="block text-[11px] font-mono text-slate-400 mb-1">Max Clips: {maxClips}</label>
                    <input
                      type="range"
                      min="1"
                      max="10"
                      value={maxClips}
                      onChange={(e) => setMaxClips(Number(e.target.value))}
                      className="w-full accent-cyan-500 mt-2"
                    />
                  </div>
                </div>

                <div>
                  <label className="block text-[11px] font-mono text-slate-400 mb-1">Custom Creator Prompt</label>
                  <input
                    type="text"
                    value={customPrompt}
                    onChange={(e) => setCustomPrompt(e.target.value)}
                    placeholder="e.g. Prioritize funny fails, high-energy screams, or key tutorial steps..."
                    className="w-full bg-surface border border-border rounded px-2.5 py-1.5 text-xs font-mono text-slate-200"
                  />
                </div>

                <div className="flex justify-end pt-1">
                  <button
                    onClick={handleRunOllamaDiscovery}
                    disabled={isDiscovering}
                    className="px-5 py-2 rounded-lg bg-gradient-to-r from-violet-600 to-cyan-500 hover:opacity-95 text-white font-bold text-xs font-mono transition-all active:scale-95 disabled:opacity-50 flex items-center gap-2"
                  >
                    <Sparkles className="w-4 h-4" />
                    <span>{isDiscovering ? 'Scoring with Ollama...' : 'Discover Viral Clips'}</span>
                  </button>
                </div>
              </div>

              {/* ==================================================== */}
              {/* Discovered Candidate Clips Showcase */}
              {/* ==================================================== */}
              {clips.length > 0 && (
                <div className="space-y-4 pt-2">
                  <h3 className="text-sm font-bold text-slate-100 flex items-center gap-2">
                    <Sparkles className="w-4 h-4 text-cyan-400" />
                    <span>Ranked Candidate Clips ({clips.length})</span>
                  </h3>

                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    {clips.map((clip, idx) => (
                      <div
                        key={clip.id}
                        className="p-4 rounded-xl bg-surface-elevated border border-border hover:border-cyan-500/60 transition-all space-y-2.5"
                      >
                        <div className="flex items-start justify-between">
                          <div className="flex items-center gap-2">
                            <span className="w-5 h-5 rounded-full bg-cyan-950 text-cyan-400 border border-cyan-800 text-[10px] font-mono font-bold flex items-center justify-center">
                              #{idx + 1}
                            </span>
                            <span className="text-xs font-mono bg-violet-950 text-violet-300 border border-violet-800 px-2 py-0.5 rounded-full capitalize">
                              {clip.detectedMood}
                            </span>
                            {clip.snappedToScene && (
                              <span className="text-[10px] font-mono bg-emerald-950 text-emerald-400 border border-emerald-800 px-1.5 py-0.5 rounded">
                                Cut-Snapped
                              </span>
                            )}
                          </div>

                          <div className="text-right">
                            <span className="text-xs font-mono font-bold text-emerald-400 bg-emerald-950/80 px-2 py-0.5 rounded border border-emerald-800">
                              {clip.viralScore} / 100
                            </span>
                          </div>
                        </div>

                        <div>
                          <h4 className="text-sm font-bold text-slate-100 leading-tight">{clip.title}</h4>
                          <p className="text-xs text-slate-300 font-mono mt-1">{clip.hookSummary}</p>
                        </div>

                        <div className="p-2 rounded bg-surface border border-border-subtle text-[11px] font-mono text-slate-400 space-y-1">
                          <div className="flex justify-between text-cyan-300">
                            <span>
                              [{formatDuration(clip.startSec)} - {formatDuration(clip.endSec)}]
                            </span>
                            <span>{clip.durationSec}s duration</span>
                          </div>
                          <div className="text-slate-400 line-clamp-2">{clip.reason}</div>
                        </div>

                        <div className="flex items-center justify-between pt-1">
                          <div className="flex flex-wrap gap-1 text-[10px] font-mono text-slate-400">
                            {clip.suggestedHashtags.slice(0, 3).map((t) => (
                              <span key={t} className="text-cyan-400">
                                {t}
                              </span>
                            ))}
                          </div>

                          <button
                            onClick={() => handleJumpToTime(clip.startSec)}
                            className="px-3 py-1 rounded bg-cyan-500/20 hover:bg-cyan-500/30 text-cyan-400 border border-cyan-500/40 text-xs font-mono flex items-center gap-1 transition-all"
                          >
                            <Play className="w-3 h-3" /> Preview
                          </button>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          ) : (
            <div className="bg-surface border border-border rounded-xl p-12 text-center space-y-3">
              <Video className="w-12 h-12 text-slate-400 mx-auto" />
              <h3 className="text-base font-semibold text-slate-200">No Video Ingested Yet</h3>
              <p className="text-xs text-slate-400 max-w-sm mx-auto font-mono">
                Select an existing project or ingest a new URL on the left to start AI transcription & Ollama clip discovery.
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
