import React, { useState } from 'react';
import {
  AlertCircle,
  CheckCircle2,
  Cpu,
  Download,
  Film,
  HardDrive,
  Key,
  RefreshCw,
  Server,
  Sliders,
  Trash2,
  Zap,
} from 'lucide-react';
import { api } from '../api/client';
import { MetricCard } from '../components/MetricCard';
import { StatusIndicator } from '../components/StatusIndicator';
import {
  CacheStatsResponse,
  SettingsRead,
  SettingsUpdate,
  SystemDiagnosticsResponse,
  YtDlpUpdateResponse,
} from '../types/diagnostics';

interface DiagnosticsPageProps {
  diagnostics: SystemDiagnosticsResponse | null;
  settings: SettingsRead | null;
  cacheStats: CacheStatsResponse | null;
  onRefresh: () => void;
  onSettingsUpdated: (newSettings: SettingsRead) => void;
  onCacheCleaned: (stats: CacheStatsResponse) => void;
}

export const DiagnosticsPage: React.FC<DiagnosticsPageProps> = ({
  diagnostics,
  settings,
  cacheStats,
  onRefresh,
  onSettingsUpdated,
  onCacheCleaned,
}) => {
  // Local form state for settings
  const [cookiesBrowser, setCookiesBrowser] = useState(settings?.cookiesBrowser || '');
  const [cookiesFilePath, setCookiesFilePath] = useState(settings?.cookiesFilePath || '');
  const [poToken, setPoToken] = useState(settings?.poToken || '');
  const [whisperModel, setWhisperModel] = useState(settings?.whisperModel || 'small');
  const [ollamaModel, setOllamaModel] = useState(settings?.ollamaModel || 'qwen2.5:7b');
  const [encoder, setEncoder] = useState(settings?.encoder || 'h264_nvenc');
  const [jsRuntime, setJsRuntime] = useState(settings?.jsRuntime || 'auto');

  // Action states
  const [isUpdatingYtdlp, setIsUpdatingYtdlp] = useState(false);
  const [ytdlpUpdateResult, setYtdlpUpdateResult] = useState<YtDlpUpdateResponse | null>(null);
  const [isCleaningCache, setIsCleaningCache] = useState(false);
  const [cleanMessage, setCleanMessage] = useState<string | null>(null);
  const [isSavingSettings, setIsSavingSettings] = useState(false);
  const [saveSuccess, setSaveSuccess] = useState(false);

  // Sync state if settings prop changes
  React.useEffect(() => {
    if (settings) {
      setCookiesBrowser(settings.cookiesBrowser || '');
      setCookiesFilePath(settings.cookiesFilePath || '');
      setPoToken(settings.poToken || '');
      setWhisperModel(settings.whisperModel);
      setOllamaModel(settings.ollamaModel);
      setEncoder(settings.encoder);
      setJsRuntime(settings.jsRuntime);
    }
  }, [settings]);

  const handleApplyPreset = async (preset: 'lite' | 'balanced' | 'pro') => {
    try {
      const updated = await api.updateSettings({ hardwarePreset: preset });
      onSettingsUpdated(updated);
    } catch (err) {
      console.error('Failed to apply preset:', err);
    }
  };

  const handleSaveSettings = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsSavingSettings(true);
    setSaveSuccess(false);
    try {
      const payload: SettingsUpdate = {
        cookiesBrowser: cookiesBrowser || null,
        cookiesFilePath: cookiesFilePath || null,
        poToken: poToken || null,
        whisperModel,
        ollamaModel,
        encoder,
        jsRuntime,
      };
      const updated = await api.updateSettings(payload);
      onSettingsUpdated(updated);
      setSaveSuccess(true);
      setTimeout(() => setSaveSuccess(false), 3000);
    } catch (err) {
      console.error('Failed to save settings:', err);
    } finally {
      setIsSavingSettings(false);
    }
  };

  const handleUpdateYtDlp = async () => {
    setIsUpdatingYtdlp(true);
    setYtdlpUpdateResult(null);
    try {
      const res = await api.updateYtDlp();
      setYtdlpUpdateResult(res);
      onRefresh();
    } catch (err: any) {
      setYtdlpUpdateResult({
        success: false,
        oldVersion: diagnostics?.ytdlp.version || null,
        newVersion: null,
        output: err.message || 'Failed to update yt-dlp',
      });
    } finally {
      setIsUpdatingYtdlp(false);
    }
  };

  const handleCleanCache = async () => {
    setIsCleaningCache(true);
    setCleanMessage(null);
    try {
      const res = await api.cleanCache();
      setCleanMessage(res.message);
      const newStats = await api.getCacheStats();
      onCacheCleaned(newStats);
      setTimeout(() => setCleanMessage(null), 4000);
    } catch (err: any) {
      setCleanMessage('Failed to clean cache: ' + err.message);
    } finally {
      setIsCleaningCache(false);
    }
  };

  const gpu = diagnostics?.gpu;
  const ffmpeg = diagnostics?.ffmpeg;
  const ollama = diagnostics?.ollama;
  const ytdlp = diagnostics?.ytdlp;

  // Calculate VRAM percentages
  const vramTotal = gpu?.vramTotalMb || 0;
  const vramUsed = gpu?.vramUsedMb || 0;
  const vramPct = vramTotal > 0 ? Math.min(100, Math.round((vramUsed / vramTotal) * 100)) : 0;

  return (
    <div className="space-y-8 max-w-7xl mx-auto pb-16">
      {/* Page Title & Intro */}
      <div>
        <h1 className="text-2xl font-bold tracking-tight text-slate-100">System Diagnostics & Hardware Control</h1>
        <p className="text-sm text-slate-400 mt-1">
          Live verification of offline AI runtimes, GPU/NVENC acceleration, download extractors, and storage caches.
        </p>
      </div>

      {/* Grid: 4 Core Telemetry Cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        {/* 1. GPU & VRAM */}
        <MetricCard
          title="GPU Acceleration"
          subtitle={gpu?.gpuName || 'Discrete / Integrated GPU'}
          icon={<Cpu className="w-4 h-4" />}
          headerAction={<StatusIndicator status={gpu?.status || 'not_detected'} />}
        >
          {gpu?.hasGpu ? (
            <div className="space-y-3">
              <div>
                <div className="flex justify-between text-xs font-mono text-slate-300 mb-1">
                  <span>VRAM Allocation</span>
                  <span>
                    {gpu.vramUsedMb} / {gpu.vramTotalMb} MB ({vramPct}%)
                  </span>
                </div>
                <div className="w-full h-2 bg-surface-elevated rounded-full overflow-hidden border border-border-subtle">
                  <div
                    className={`h-full transition-all duration-500 rounded-full ${
                      vramPct > 85 ? 'bg-rose-500' : vramPct > 60 ? 'bg-amber-400' : 'bg-cyan-500'
                    }`}
                    style={{ width: `${vramPct}%` }}
                  />
                </div>
              </div>

              <div className="grid grid-cols-2 gap-2 text-xs font-mono pt-1 border-t border-border-subtle">
                <div>
                  <span className="text-slate-400">Driver:</span>{' '}
                  <span className="text-slate-200">{gpu.driverVersion || 'N/A'}</span>
                </div>
                <div>
                  <span className="text-slate-400">CUDA:</span>{' '}
                  <span className="text-slate-200">{gpu.cudaVersion || 'N/A'}</span>
                </div>
                <div>
                  <span className="text-slate-400">Temp:</span>{' '}
                  <span className="text-slate-200">{gpu.temperatureC ? `${gpu.temperatureC}°C` : 'N/A'}</span>
                </div>
                <div>
                  <span className="text-slate-400">Load:</span>{' '}
                  <span className="text-slate-200">{gpu.gpuUtilizationPercent !== null ? `${gpu.gpuUtilizationPercent}%` : 'N/A'}</span>
                </div>
              </div>
            </div>
          ) : (
            <div className="text-xs text-slate-400 font-mono py-2">
              No NVIDIA GPU detected. Application will safely run in CPU-only mode (INT8 quantization).
            </div>
          )}
        </MetricCard>

        {/* 2. FFmpeg & Hardware Encoders */}
        <MetricCard
          title="FFmpeg & Encoding"
          subtitle={ffmpeg?.version?.split(' ')[2] ? `v${ffmpeg.version.split(' ')[2]}` : 'Media Pipeline'}
          icon={<Film className="w-4 h-4" />}
          headerAction={<StatusIndicator status={ffmpeg?.status || 'missing'} />}
        >
          <div className="space-y-2.5 text-xs font-mono">
            <div className="flex items-center justify-between py-1 border-b border-border-subtle">
              <span className="text-slate-400">h264_nvenc (GPU)</span>
              <span className={ffmpeg?.hasH264Nvenc ? 'text-emerald-400 flex items-center gap-1' : 'text-slate-400'}>
                {ffmpeg?.hasH264Nvenc ? <CheckCircle2 className="w-3.5 h-3.5" /> : 'Unavailable'}
              </span>
            </div>
            <div className="flex items-center justify-between py-1 border-b border-border-subtle">
              <span className="text-slate-400">libx264 (CPU)</span>
              <span className={ffmpeg?.hasLibx264 ? 'text-emerald-400 flex items-center gap-1' : 'text-slate-400'}>
                {ffmpeg?.hasLibx264 ? <CheckCircle2 className="w-3.5 h-3.5" /> : 'Unavailable'}
              </span>
            </div>
            <div className="flex items-center justify-between py-1">
              <span className="text-slate-400">libass Subtitles</span>
              <span className={ffmpeg?.hasLibass ? 'text-emerald-400 flex items-center gap-1' : 'text-slate-400'}>
                {ffmpeg?.hasLibass ? <CheckCircle2 className="w-3.5 h-3.5" /> : 'Unavailable'}
              </span>
            </div>
          </div>
        </MetricCard>

        {/* 3. Ollama LLM Service */}
        <MetricCard
          title="Ollama Local LLM"
          subtitle={ollama?.isReachable ? `${ollama.models.length} Models Loaded` : 'Offline / Standby'}
          icon={<Server className="w-4 h-4" />}
          headerAction={<StatusIndicator status={ollama?.status || 'disconnected'} />}
        >
          {ollama?.isReachable ? (
            <div className="space-y-2 text-xs font-mono">
              <div className="text-slate-400 truncate">Endpoint: {ollama.url}</div>
              <div className="mt-2">
                <span className="text-slate-400 block mb-1">Installed Models:</span>
                <div className="max-h-20 overflow-y-auto space-y-1">
                  {ollama.models.length > 0 ? (
                    ollama.models.map((m) => (
                      <div
                        key={m.name}
                        className="flex items-center justify-between bg-surface-elevated px-2 py-0.5 rounded text-[11px]"
                      >
                        <span className="text-cyan-400 font-semibold">{m.name}</span>
                        <span className="text-slate-400">{m.parameterSize || 'Auto'}</span>
                      </div>
                    ))
                  ) : (
                    <div className="text-slate-400 italic">No models found in Ollama.</div>
                  )}
                </div>
              </div>
            </div>
          ) : (
            <div className="space-y-2 text-xs text-slate-400 font-mono">
              <p>Ollama server is not running on localhost:11434.</p>
              <div className="p-2 rounded bg-surface-elevated border border-border text-[11px] text-amber-400/90 flex items-start gap-1.5">
                <AlertCircle className="w-3.5 h-3.5 flex-shrink-0 mt-0.5" />
                <span>Run `ollama serve` in a terminal before starting clip scoring.</span>
              </div>
            </div>
          )}
        </MetricCard>

        {/* 4. yt-dlp & JS Runtime */}
        <MetricCard
          title="yt-dlp Extractor"
          subtitle={ytdlp?.version ? `v${ytdlp.version}` : 'Video Ingestion'}
          icon={<Download className="w-4 h-4" />}
          headerAction={<StatusIndicator status={ytdlp?.status || 'missing'} />}
        >
          <div className="space-y-2.5 text-xs font-mono">
            <div className="flex items-center justify-between py-1 border-b border-border-subtle">
              <span className="text-slate-400">JS Runtime</span>
              <span className={ytdlp?.hasJsRuntime ? 'text-emerald-400 font-semibold' : 'text-amber-400'}>
                {ytdlp?.hasJsRuntime ? `${ytdlp.jsRuntimeType?.toUpperCase()}` : 'None (May Bot-Block)'}
              </span>
            </div>

            <div className="flex items-center justify-between pt-1">
              <span className="text-slate-400 text-[11px]">YouTube Sig-Solver</span>
              <span className="text-slate-300 text-[11px]">{ytdlp?.hasJsRuntime ? 'Active' : 'Degraded'}</span>
            </div>

            <button
              onClick={handleUpdateYtDlp}
              disabled={isUpdatingYtdlp}
              className="w-full mt-2 flex items-center justify-center gap-1.5 py-1.5 rounded-lg bg-surface-elevated hover:bg-surface-hover text-cyan-400 border border-border text-xs font-medium transition-all disabled:opacity-50"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${isUpdatingYtdlp ? 'animate-spin' : ''}`} />
              <span>{isUpdatingYtdlp ? 'Updating yt-dlp...' : 'One-Click Update'}</span>
            </button>
          </div>
        </MetricCard>
      </div>

      {/* yt-dlp Update Result Modal / Banner */}
      {ytdlpUpdateResult && (
        <div
          className={`p-4 rounded-xl border text-xs font-mono space-y-1 ${
            ytdlpUpdateResult.success
              ? 'bg-emerald-950/40 border-emerald-800 text-emerald-200'
              : 'bg-rose-950/40 border-rose-800 text-rose-200'
          }`}
        >
          <div className="font-semibold flex items-center gap-2">
            {ytdlpUpdateResult.success ? (
              <CheckCircle2 className="w-4 h-4 text-emerald-400" />
            ) : (
              <AlertCircle className="w-4 h-4 text-rose-400" />
            )}
            <span>
              {ytdlpUpdateResult.success
                ? `yt-dlp updated successfully from ${ytdlpUpdateResult.oldVersion} to ${ytdlpUpdateResult.newVersion}`
                : 'yt-dlp update encountered an error'}
            </span>
          </div>
          <pre className="text-[11px] max-h-24 overflow-y-auto whitespace-pre-wrap opacity-80 pt-1">
            {ytdlpUpdateResult.output}
          </pre>
        </div>
      )}

      {/* Hardware Presets Section */}
      <div className="bg-surface border border-border rounded-xl p-6 space-y-4">
        <div>
          <h2 className="text-base font-bold text-slate-100 flex items-center gap-2">
            <Zap className="w-4 h-4 text-cyan-400" />
            <span>Hardware Execution Presets</span>
          </h2>
          <p className="text-xs text-slate-400 mt-0.5">
            Auto-configure transcription models, LLM parameters, and video encoders to fit your exact GPU VRAM budget.
          </p>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-4 pt-2">
          {/* Preset 1: Lite */}
          <div
            onClick={() => handleApplyPreset('lite')}
            className={`cursor-pointer rounded-xl p-4 border transition-all ${
              settings?.hardwarePreset === 'lite'
                ? 'bg-cyan-950/30 border-cyan-500 shadow-md shadow-cyan-950/50'
                : 'bg-surface-elevated border-border hover:border-slate-600'
            }`}
          >
            <div className="flex items-center justify-between mb-2">
              <span className="font-bold text-sm text-slate-100">Lite Preset</span>
              {diagnostics?.recommendedPreset === 'lite' && (
                <span className="text-[10px] bg-emerald-950 text-emerald-400 border border-emerald-800 px-2 py-0.5 rounded-full font-mono">
                  Recommended
                </span>
              )}
            </div>
            <p className="text-xs text-slate-400 mb-3">CPU-Only or 4GB VRAM Laptops</p>
            <ul className="text-xs font-mono space-y-1.5 text-slate-300">
              <li>• STT: faster-whisper (base, INT8)</li>
              <li>• LLM: qwen2.5:3b or llama3.2:3b</li>
              <li>• Encoder: libx264 (CPU veryfast)</li>
            </ul>
          </div>

          {/* Preset 2: Balanced */}
          <div
            onClick={() => handleApplyPreset('balanced')}
            className={`cursor-pointer rounded-xl p-4 border transition-all ${
              settings?.hardwarePreset === 'balanced'
                ? 'bg-cyan-950/30 border-cyan-500 shadow-md shadow-cyan-950/50'
                : 'bg-surface-elevated border-border hover:border-slate-600'
            }`}
          >
            <div className="flex items-center justify-between mb-2">
              <span className="font-bold text-sm text-slate-100">Balanced Preset</span>
              {diagnostics?.recommendedPreset === 'balanced' && (
                <span className="text-[10px] bg-emerald-950 text-emerald-400 border border-emerald-800 px-2 py-0.5 rounded-full font-mono">
                  Recommended
                </span>
              )}
            </div>
            <p className="text-xs text-slate-400 mb-3">6GB–8GB GPUs (e.g. RTX 3050/3060/4060)</p>
            <ul className="text-xs font-mono space-y-1.5 text-slate-300">
              <li>• STT: faster-whisper (small, INT8 CUDA)</li>
              <li>• LLM: qwen2.5:7b or llama3.1:8b</li>
              <li>• Encoder: h264_nvenc (Hardware)</li>
            </ul>
          </div>

          {/* Preset 3: Pro */}
          <div
            onClick={() => handleApplyPreset('pro')}
            className={`cursor-pointer rounded-xl p-4 border transition-all ${
              settings?.hardwarePreset === 'pro'
                ? 'bg-cyan-950/30 border-cyan-500 shadow-md shadow-cyan-950/50'
                : 'bg-surface-elevated border-border hover:border-slate-600'
            }`}
          >
            <div className="flex items-center justify-between mb-2">
              <span className="font-bold text-sm text-slate-100">Pro Preset</span>
              {diagnostics?.recommendedPreset === 'pro' && (
                <span className="text-[10px] bg-emerald-950 text-emerald-400 border border-emerald-800 px-2 py-0.5 rounded-full font-mono">
                  Recommended
                </span>
              )}
            </div>
            <p className="text-xs text-slate-400 mb-3">12GB+ VRAM Workstations</p>
            <ul className="text-xs font-mono space-y-1.5 text-slate-300">
              <li>• STT: large-v3-turbo (FP16 CUDA)</li>
              <li>• LLM: qwen2.5:14b or gemma3:12b</li>
              <li>• Encoder: h264_nvenc / hevc_nvenc</li>
            </ul>
          </div>
        </div>
      </div>

      {/* Two Column Section: Pipeline Config + Cache Management */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Left Column: Extraction & Cookies Settings (2 cols) */}
        <div className="lg:col-span-2 bg-surface border border-border rounded-xl p-6">
          <div className="flex items-center justify-between mb-4">
            <div>
              <h2 className="text-base font-bold text-slate-100 flex items-center gap-2">
                <Sliders className="w-4 h-4 text-cyan-400" />
                <span>Extraction & Model Overrides</span>
              </h2>
              <p className="text-xs text-slate-400 mt-0.5">
                Fine-tune cookies, PO-tokens, and individual engine models.
              </p>
            </div>
            {saveSuccess && (
              <span className="text-xs text-emerald-400 bg-emerald-950 px-2 py-1 rounded font-mono flex items-center gap-1">
                <CheckCircle2 className="w-3.5 h-3.5" /> Saved
              </span>
            )}
          </div>

          <form onSubmit={handleSaveSettings} className="space-y-4">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div>
                <label className="block text-xs font-mono text-slate-300 mb-1">Whisper STT Model</label>
                <select
                  value={whisperModel}
                  onChange={(e) => setWhisperModel(e.target.value)}
                  className="w-full bg-surface-elevated border border-border rounded-lg px-3 py-2 text-xs font-mono text-slate-200 focus:outline-none focus:border-cyan-500"
                >
                  <option value="tiny">tiny (Fastest, ~1GB VRAM)</option>
                  <option value="base">base (Light, ~1.5GB VRAM)</option>
                  <option value="small">small (Balanced, ~2.5GB VRAM)</option>
                  <option value="medium">medium (~5GB VRAM)</option>
                  <option value="large-v3-turbo">large-v3-turbo (Best, ~6GB VRAM)</option>
                </select>
              </div>

              <div>
                <label className="block text-xs font-mono text-slate-300 mb-1">Ollama Clip Model</label>
                <select
                  value={ollamaModel}
                  onChange={(e) => setOllamaModel(e.target.value)}
                  className="w-full bg-surface-elevated border border-border rounded-lg px-3 py-2 text-xs font-mono text-slate-200 focus:outline-none focus:border-cyan-500"
                >
                  {ollama?.models && ollama.models.length > 0 ? (
                    ollama.models.map((m) => (
                      <option key={m.name} value={m.name}>
                        {m.name} {m.parameterSize ? `(${m.parameterSize})` : ''}
                      </option>
                    ))
                  ) : (
                    <>
                      <option value="qwen2.5:7b">qwen2.5:7b (Recommended)</option>
                      <option value="qwen2.5:3b">qwen2.5:3b (Lite)</option>
                      <option value="llama3.2:3b">llama3.2:3b</option>
                      <option value="llama3.1:8b">llama3.1:8b</option>
                    </>
                  )}
                </select>
              </div>

              <div>
                <label className="block text-xs font-mono text-slate-300 mb-1">Video Encoder</label>
                <select
                  value={encoder}
                  onChange={(e) => setEncoder(e.target.value)}
                  className="w-full bg-surface-elevated border border-border rounded-lg px-3 py-2 text-xs font-mono text-slate-200 focus:outline-none focus:border-cyan-500"
                >
                  <option value="h264_nvenc">h264_nvenc (NVIDIA Hardware)</option>
                  <option value="libx264">libx264 (CPU / High Compatibility)</option>
                  <option value="hevc_nvenc">hevc_nvenc (H.265 Hardware)</option>
                </select>
              </div>

              <div>
                <label className="block text-xs font-mono text-slate-300 mb-1">JS Runtime Preference</label>
                <select
                  value={jsRuntime}
                  onChange={(e) => setJsRuntime(e.target.value)}
                  className="w-full bg-surface-elevated border border-border rounded-lg px-3 py-2 text-xs font-mono text-slate-200 focus:outline-none focus:border-cyan-500"
                >
                  <option value="auto">Auto-Detect (Deno preferred, else Node)</option>
                  <option value="deno">Force Deno</option>
                  <option value="node">Force Node.js</option>
                </select>
              </div>
            </div>

            <div className="pt-3 border-t border-border-subtle">
              <h3 className="text-xs font-semibold text-slate-200 mb-2 flex items-center gap-1.5">
                <Key className="w-3.5 h-3.5 text-cyan-400" />
                <span>YouTube Bot-Protection & Authentication</span>
              </h3>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div>
                  <label className="block text-xs font-mono text-slate-400 mb-1">Browser Cookies</label>
                  <select
                    value={cookiesBrowser}
                    onChange={(e) => setCookiesBrowser(e.target.value)}
                    className="w-full bg-surface-elevated border border-border rounded-lg px-3 py-2 text-xs font-mono text-slate-200 focus:outline-none focus:border-cyan-500"
                  >
                    <option value="">None (Public content only)</option>
                    <option value="chrome">Google Chrome</option>
                    <option value="edge">Microsoft Edge</option>
                    <option value="firefox">Mozilla Firefox</option>
                    <option value="brave">Brave Browser</option>
                  </select>
                </div>

                <div>
                  <label className="block text-xs font-mono text-slate-400 mb-1">PO-Token (Proof of Origin)</label>
                  <input
                    type="text"
                    value={poToken}
                    onChange={(e) => setPoToken(e.target.value)}
                    placeholder="Optional YouTube PO-Token"
                    className="w-full bg-surface-elevated border border-border rounded-lg px-3 py-2 text-xs font-mono text-slate-200 focus:outline-none focus:border-cyan-500"
                  />
                </div>
              </div>
            </div>

            <div className="flex justify-end pt-2">
              <button
                type="submit"
                disabled={isSavingSettings}
                className="px-5 py-2 rounded-lg bg-cyan-500 hover:bg-cyan-400 text-black font-semibold text-xs tracking-tight transition-all active:scale-95 disabled:opacity-50"
              >
                {isSavingSettings ? 'Saving...' : 'Save Configuration'}
              </button>
            </div>
          </form>
        </div>

        {/* Right Column: Cache & Storage Management */}
        <div className="bg-surface border border-border rounded-xl p-6 space-y-4">
          <div>
            <h2 className="text-base font-bold text-slate-100 flex items-center gap-2">
              <HardDrive className="w-4 h-4 text-cyan-400" />
              <span>Temp Cache Cleaner</span>
            </h2>
            <p className="text-xs text-slate-400 mt-0.5">
              Workspace storage usage for downloaded streams, audio stems, and intermediate crops.
            </p>
          </div>

          <div className="p-4 rounded-xl bg-surface-elevated border border-border space-y-3 font-mono">
            <div className="flex items-center justify-between text-xs">
              <span className="text-slate-400">Cache Directory</span>
              <span className="text-slate-200 truncate max-w-[160px]" title={cacheStats?.cacheDir}>
                workspace_cache
              </span>
            </div>

            <div className="flex items-center justify-between text-xs">
              <span className="text-slate-400">Total Size</span>
              <span className="text-cyan-400 font-bold text-sm">
                {cacheStats?.totalMb ? `${cacheStats.totalMb} MB` : '0.00 MB'}
              </span>
            </div>

            <div className="flex items-center justify-between text-xs">
              <span className="text-slate-400">Cached Files</span>
              <span className="text-slate-200">{cacheStats?.fileCount || 0}</span>
            </div>
          </div>

          {cleanMessage && (
            <div className="p-3 rounded-lg bg-cyan-950/40 border border-cyan-800 text-cyan-300 text-xs font-mono">
              {cleanMessage}
            </div>
          )}

          <button
            onClick={handleCleanCache}
            disabled={isCleaningCache}
            className="w-full flex items-center justify-center gap-2 py-2.5 rounded-lg bg-surface-elevated hover:bg-rose-950/40 border border-border hover:border-rose-700/60 text-slate-300 hover:text-rose-300 font-medium text-xs transition-all active:scale-95 disabled:opacity-50"
          >
            <Trash2 className="w-4 h-4 text-rose-400" />
            <span>{isCleaningCache ? 'Cleaning Temporary Cache...' : 'Clean Temp Files'}</span>
          </button>
        </div>
      </div>
    </div>
  );
};
