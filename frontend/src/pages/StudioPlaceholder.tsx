import React from 'react';
import { CheckCircle2, Clapperboard, Eye, MessageSquare, Sparkles, Wand2 } from 'lucide-react';

export const StudioPlaceholder: React.FC = () => {
  const phases = [
    {
      num: 'Phase 1',
      title: 'Scaffold, Lazy Architecture & Diagnostics',
      desc: 'FastAPI single-port server, SQLite async database, live GPU/VRAM telemetry, hardware presets, yt-dlp updater, and cache cleaner.',
      status: 'Ready & Verified',
      active: true,
      icon: <CheckCircle2 className="w-5 h-5 text-emerald-400" />,
    },
    {
      num: 'Phase 2',
      title: 'Ingestion, Engagement Mining & Range Streaming',
      desc: 'YouTube / Twitch / Kick download modes, comment timestamp parser, live chat velocity spikes, audio hype detector, and HTTP 206 video streaming.',
      status: 'Next Milestone',
      active: false,
      icon: <Clapperboard className="w-5 h-5 text-cyan-400" />,
    },
    {
      num: 'Phase 3',
      title: 'Transcription & Ollama Clip Scoring',
      desc: 'Subprocess-isolated faster-whisper, PySceneDetect cut boundaries, word-level timestamps, and Ollama structured JSON clip scoring with VRAM keep_alive: 0.',
      status: 'Planned',
      active: false,
      icon: <Wand2 className="w-5 h-5 text-violet-400" />,
    },
    {
      num: 'Phase 4',
      title: 'Vision Framing & Layout Studio',
      desc: 'HTML5 Canvas drag-and-drop crop picker, Gaming Mode (Facecam vs Gameplay), Podcast Active Speaker Tracking (MediaPipe), and Safe-Zone overlays.',
      status: 'Planned',
      active: false,
      icon: <Eye className="w-5 h-5 text-amber-400" />,
    },
    {
      num: 'Phase 5',
      title: 'Customizable Auto-Captions Engine',
      desc: '5 presets (Hormozi, Karaoke, Minimal, Neon, Boxed Pill), .ass subtitle generation, word-level typo editor, and profanity masking.',
      status: 'Planned',
      active: false,
      icon: <MessageSquare className="w-5 h-5 text-blue-400" />,
    },
    {
      num: 'Phase 6',
      title: 'Clip Workbench & Batch Export',
      desc: 'Waveform trimming, 5s preview render, -14 LUFS loudnorm, dead-air silence trimmer, and batch CFR rendering queue with sidecar exports.',
      status: 'Planned',
      active: false,
      icon: <Sparkles className="w-5 h-5 text-pink-400" />,
    },
  ];

  return (
    <div className="max-w-5xl mx-auto space-y-8 pb-16">
      <div>
        <h1 className="text-2xl font-bold tracking-tight text-slate-100 flex items-center gap-2.5">
          <Clapperboard className="w-6 h-6 text-cyan-400" />
          <span>ClipForge Studio Workbench</span>
        </h1>
        <p className="text-sm text-slate-400 mt-1">
          Full offline AI video pipeline architecture roadmap. Phase 1 provides the foundational runtime, hardware diagnostics, and static shell.
        </p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {phases.map((p) => (
          <div
            key={p.num}
            className={`p-5 rounded-xl border transition-all ${
              p.active
                ? 'bg-cyan-950/20 border-cyan-500/60 shadow-lg shadow-cyan-950/30'
                : 'bg-surface border-border hover:border-slate-700'
            }`}
          >
            <div className="flex items-center justify-between mb-3">
              <div className="flex items-center gap-2.5">
                <div className="p-2 rounded-lg bg-surface-elevated border border-border-subtle">{p.icon}</div>
                <div>
                  <span className="text-xs font-mono font-bold text-cyan-400 block">{p.num}</span>
                  <h3 className="text-sm font-semibold text-slate-100">{p.title}</h3>
                </div>
              </div>
              <span
                className={`text-[11px] font-mono px-2 py-0.5 rounded-full ${
                  p.active
                    ? 'bg-emerald-950 text-emerald-400 border border-emerald-800'
                    : 'bg-surface-elevated text-slate-400 border border-border-subtle'
                }`}
              >
                {p.status}
              </span>
            </div>
            <p className="text-xs text-slate-400 leading-relaxed font-mono">{p.desc}</p>
          </div>
        ))}
      </div>
    </div>
  );
};
