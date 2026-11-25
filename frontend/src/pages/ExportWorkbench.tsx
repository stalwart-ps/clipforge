import React, { memo, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Activity, ArrowDown, ArrowUp, Check, ChevronDown, Clapperboard, Download, Film, Layers, Loader2, Play, Scissors, Square, X } from 'lucide-react';
import { api } from '../api/client';
import { useWorkspace } from '../context/WorkspaceContext';
import { ExportJob, ExportOptions } from '../types/exports';
import { CandidateClip, CaptionConfig, FramingConfig, FramingMode, LayoutTemplate, ProjectRead, ProjectSummary } from '../types/project';

type Bounds = { startSec: number; endSec: number };

const DEFAULT_CAPTIONS: CaptionConfig = {
  preset: 'hormozi_pop',
  fontName: 'Arial Black',
  fontSize: 78,
  primaryColor: '#FFFFFF',
  highlightColor: '#FFE600',
  outlineColor: '#000000',
  outlineWidth: 6,
  shadowDepth: 3,
  shadowBlur: 0,
  shadowColor: '#000000',
  marginV: 180,
  positionYPercent: 80,
  maxWordsPerLine: 3,
  allCaps: true,
  animation: 'pop',
  animationStyle: 'pop_bounce',
  secondaryFont: 'Georgia',
  fontSwitchMode: 'none',
  secondaryItalic: true,
  glowEnabled: false,
  glowColor: '#00F5FF',
  glowIntensity: 12,
  letterSpacing: 0,
  profanityMask: false,
};

const DEFAULT_FRAMING: FramingConfig = {
  framingMode: 'gaming',
  aspectRatio: '9:16',
  layoutTemplate: 'split_vertical',
  facecamBox: { x: 0.0, y: 0.0, w: 0.3, h: 0.25 },
  gameplayBox: { x: 0.0, y: 0.0, w: 1.0, h: 1.0 },
  splitRatio: 35,
  paneFitMode: 'fill',
  watermark: null,
};

const MODE_LAYOUT_OPTIONS: Record<FramingMode, Array<{ id: LayoutTemplate; label: string }>> = {
  podcast: [
    { id: 'split_vertical', label: '50/50 Stacked Split' },
    { id: 'podcast_active_speaker', label: 'Active Speaker Auto-Cut' },
    { id: 'side_by_side_blur', label: 'Side-by-Side Dual over Blur' },
    { id: 'wide_plus_dual', label: 'Wide Top + Dual Bottom' },
    { id: 'fullscreen_crop', label: 'Single Speaker Portrait' },
  ],
  gaming: [
    { id: 'split_vertical', label: 'Facecam Top / Game Bottom' },
    { id: 'split_inverted', label: 'Game Top / Facecam Bottom' },
    { id: 'pip', label: 'Gameplay + Facecam PiP' },
    { id: 'blurred_fill', label: 'Blurred Fill 9:16' },
    { id: 'fullscreen_crop', label: 'Fullscreen Crop' },
  ],
  talking_head: [
    { id: 'fullscreen_crop', label: 'Upper-Body Portrait (9:16)' },
    { id: 'punch_in_zoom', label: 'Punch-In Retention Zoom' },
    { id: 'blurred_fill', label: 'Blurred Fill' },
  ],
  screen_presenter: [
    { id: 'split_vertical', label: 'Screen Top / Presenter Bottom' },
    { id: 'split_inverted', label: 'Presenter Top / Screen Bottom' },
    { id: 'pip', label: 'Full Screen + Presenter PiP' },
    { id: 'blurred_fill', label: 'Blurred Fill' },
  ],
  reaction: [
    { id: 'split_vertical', label: 'Reactor Top / Video Bottom' },
    { id: 'split_inverted', label: 'Video Top / Reactor Bottom' },
    { id: 'pip', label: 'Video + Reactor PiP' },
    { id: 'side_by_side_blur', label: 'Side-by-Side Dual' },
  ],
};

function formatTime(value: number): string {
  const safe = Math.max(0, value);
  const minutes = Math.floor(safe / 60);
  return `${minutes}:${(safe % 60).toFixed(1).padStart(4, '0')}`;
}

interface WaveformTrimProps {
  duration: number;
  bounds: Bounds;
  energy: Array<{ timeSec: number; score: number }>;
  onCommit: (bounds: Bounds) => void;
}

const WaveformTrim = memo(({ duration, bounds, energy, onCommit }: WaveformTrimProps) => {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const rangeRef = useRef<Bounds>(bounds);
  const dragRef = useRef<'start' | 'end' | null>(null);
  const drawRef = useRef<() => void>(() => undefined);
  const commitRef = useRef(onCommit);
  commitRef.current = onCommit;

  useEffect(() => {
    rangeRef.current = bounds;
    drawRef.current();
  }, [bounds.startSec, bounds.endSec]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const draw = () => {
      const box = canvas.getBoundingClientRect();
      const dpr = window.devicePixelRatio || 1;
      const width = Math.max(1, Math.round(box.width * dpr));
      const height = Math.max(1, Math.round(box.height * dpr));
      if (canvas.width !== width || canvas.height !== height) {
        canvas.width = width;
        canvas.height = height;
      }
      const context = canvas.getContext('2d');
      if (!context) return;
      context.setTransform(dpr, 0, 0, dpr, 0, 0);
      const w = box.width;
      const h = box.height;
      context.clearRect(0, 0, w, h);
      context.fillStyle = '#09141d';
      context.fillRect(0, 0, w, h);
      context.strokeStyle = 'rgba(148, 163, 184, .12)';
      context.lineWidth = 1;
      for (let line = 1; line < 8; line += 1) {
        const x = (w * line) / 8;
        context.beginPath(); context.moveTo(x, 0); context.lineTo(x, h); context.stroke();
      }
      const current = rangeRef.current;
      const startX = (current.startSec / duration) * w;
      const endX = (current.endSec / duration) * w;
      context.fillStyle = 'rgba(3, 8, 13, .68)';
      context.fillRect(0, 0, startX, h);
      context.fillRect(endX, 0, w - endX, h);
      context.strokeStyle = 'rgba(34, 211, 238, .88)';
      context.lineWidth = 1.2;
      context.beginPath();
      context.moveTo(0, h * .73); context.lineTo(w, h * .73); context.stroke();

      if (energy.length) {
        context.fillStyle = 'rgba(45, 212, 191, .78)';
        const step = Math.max(2, w / Math.max(energy.length, 1));
        for (const point of energy) {
          const x = (point.timeSec / duration) * w;
          const amplitude = Math.min(1, Math.max(.05, point.score / 100));
          const barH = amplitude * h * .56;
          context.fillRect(x, h * .73 - barH, Math.max(1.4, step * .62), barH);
        }
      } else {
        context.fillStyle = 'rgba(45, 212, 191, .24)';
        for (let x = 0; x < w; x += 8) {
          const barH = 5 + (Math.abs(Math.sin(x * .047) * Math.cos(x * .013)) * h * .22);
          context.fillRect(x, h * .73 - barH, 2, barH);
        }
      }

      context.fillStyle = '#22d3ee';
      for (const handleX of [startX, endX]) {
        context.fillRect(handleX - 5, 0, 10, h);
        context.beginPath();
        context.roundRect(handleX - 7, h * .33, 14, h * .34, 4);
        context.fill();
      }
    };
    drawRef.current = draw;
    draw();
    const resize = new ResizeObserver(draw);
    resize.observe(canvas);
    return () => resize.disconnect();
  }, [duration, energy]);

  const pointerTime = (event: React.PointerEvent<HTMLCanvasElement>) => {
    const rect = event.currentTarget.getBoundingClientRect();
    return Math.max(0, Math.min(duration, ((event.clientX - rect.left) / rect.width) * duration));
  };

  return (
    <div className="space-y-2">
      <canvas
        ref={canvasRef}
        className="w-full h-36 rounded-xl border border-slate-700/80 touch-none cursor-ew-resize"
        aria-label="Waveform timeline with draggable clip start and end handles"
        onPointerDown={(event) => {
          const time = pointerTime(event);
          const current = rangeRef.current;
          const active = Math.abs(time - current.startSec) <= Math.abs(time - current.endSec) ? 'start' : 'end';
          dragRef.current = active;
          event.currentTarget.setPointerCapture(event.pointerId);
          const updated = active === 'start'
            ? { startSec: Math.min(time, current.endSec - .2), endSec: current.endSec }
            : { startSec: current.startSec, endSec: Math.max(time, current.startSec + .2) };
          rangeRef.current = updated;
          drawRef.current();
        }}
        onPointerMove={(event) => {
          if (!dragRef.current) return;
          const time = pointerTime(event);
          const current = rangeRef.current;
          rangeRef.current = dragRef.current === 'start'
            ? { startSec: Math.min(time, current.endSec - .2), endSec: current.endSec }
            : { startSec: current.startSec, endSec: Math.max(time, current.startSec + .2) };
          drawRef.current();
        }}
        onPointerUp={() => {
          if (dragRef.current) commitRef.current(rangeRef.current);
          dragRef.current = null;
        }}
        onPointerCancel={() => { dragRef.current = null; }}
      />
      <div className="flex items-center justify-between text-xs font-mono text-slate-400">
        <span>IN <strong className="text-cyan-300">{formatTime(bounds.startSec)}</strong></span>
        <span className="text-slate-600">{energy.length ? 'AUDIO ENERGY' : 'TIMELINE GUIDE'}</span>
        <span>OUT <strong className="text-cyan-300">{formatTime(bounds.endSec)}</strong></span>
      </div>
    </div>
  );
});
WaveformTrim.displayName = 'WaveformTrim';

const ClipRow = memo(({ clip, selected, active, bounds, onSelect, onActivate }: {
  clip: CandidateClip; selected: boolean; active: boolean; bounds: Bounds;
  onSelect: () => void; onActivate: () => void;
}) => {
  const isMulti = Boolean(clip.segments && clip.segments.length >= 2);
  const timeDisplay = isMulti
    ? clip.segments!.map((s) => `${formatTime(s.startSec)}–${formatTime(s.endSec)}`).join(' + ')
    : `${formatTime(bounds.startSec)} – ${formatTime(bounds.endSec)}`;

  return (
    <div className={`group flex items-center gap-3 p-3 rounded-xl border transition-colors ${active ? 'bg-cyan-950/30 border-cyan-700/70' : 'bg-slate-900/55 border-slate-800 hover:border-slate-700'}`}>
      <input type="checkbox" checked={selected} onChange={onSelect} aria-label={`Select ${clip.title} for export`} className="accent-cyan-400 w-4 h-4 cursor-pointer" />
      <button onClick={onActivate} className="min-w-0 flex-1 text-left">
        <div className="flex items-center gap-2">
          <span className="block truncate text-sm font-medium text-slate-100">{clip.title}</span>
          {isMulti && (
            <span className="rounded bg-cyan-950 px-1.5 py-0.5 text-[10px] font-mono font-bold text-cyan-300 border border-cyan-800 flex-shrink-0">
              Multi-Cut ({clip.segments!.length} parts)
            </span>
          )}
        </div>
        <span className="mt-1 block truncate text-[11px] text-slate-500 font-mono">{timeDisplay} · score {clip.viralScore}</span>
      </button>
      <span className="rounded-md bg-slate-800 px-2 py-1 font-mono text-[10px] text-cyan-300">
        {Math.round(isMulti ? clip.durationSec : (bounds.endSec - bounds.startSec))}s
      </span>
    </div>
  );
});
ClipRow.displayName = 'ClipRow';

export const ExportWorkbench: React.FC = () => {
  const { activeProjectId, setActiveProjectId } = useWorkspace();
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [project, setProject] = useState<ProjectRead | null>(null);
  const [projectId, setProjectId] = useState('');
  const [clips, setClips] = useState<CandidateClip[]>([]);
  const [minViralScore, setMinViralScore] = useState(0);
  const [activeClipId, setActiveClipId] = useState('');
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [boundsById, setBoundsById] = useState<Record<string, Bounds>>({});
  const [jobs, setJobs] = useState<ExportJob[]>([]);
  const [options, setOptions] = useState<ExportOptions>({
    normalizeLoudness: true, removeSilence: false, silenceThresholdDb: -35,
    silenceMinDurationSec: .6,
    sidecars: { srt: false, ass: false, metadataJson: true, metadataTxt: false },
    burnCaptions: false,
    captionConfig: DEFAULT_CAPTIONS, framingConfig: DEFAULT_FRAMING,
  });
  const [previewUrl, setPreviewUrl] = useState('');
  const [isPreviewing, setIsPreviewing] = useState(false);
  const [isQueueing, setIsQueueing] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [isMergeModalOpen, setIsMergeModalOpen] = useState(false);
  const [mergeOrder, setMergeOrder] = useState<string[]>([]);
  const [mergedTitle, setMergedTitle] = useState('');
  const videoRef = useRef<HTMLVideoElement>(null);
  const previewUrlRef = useRef('');

  useEffect(() => {
    api.listProjects().then((items) => {
      const ready = items.filter((item) => item.status === 'ready');
      setProjects(ready);
      const preferredId = ready.find((p) => p.id === activeProjectId)?.id || ready[0]?.id;
      if (preferredId) setProjectId(preferredId);
    }).catch((cause) => setError(cause.message || 'Could not load projects'));
  }, [activeProjectId]);

  useEffect(() => {
    if (!projectId) return;
    setActiveProjectId(projectId);
    let alive = true;
    Promise.all([
      api.getProject(projectId),
      api.getClips(projectId),
      api.getExportJobs(projectId),
      api.getWorkspaceConfig(projectId).catch(() => null),
    ])
      .then(([loadedProject, loadedClips, loadedJobs, wsConfig]) => {
        if (!alive) return;
        setProject(loadedProject);
        setClips(loadedClips);
        setJobs(loadedJobs);
        const first = loadedClips[0];
        setActiveClipId(first?.id || '');
        setSelectedIds(new Set(loadedClips.map((clip) => clip.id)));
        setBoundsById(Object.fromEntries(loadedClips.map((clip) => [clip.id, { startSec: clip.startSec, endSec: clip.endSec }])));
        if (wsConfig) {
          setOptions((prev) => {
            const next = { ...prev };
            if (wsConfig.layoutConfig && Object.keys(wsConfig.layoutConfig).length > 0) {
              const lc = wsConfig.layoutConfig as any;
              const fMode = lc.framingMode || lc.framing_mode;
              const aRatio = lc.aspectRatio || lc.aspect_ratio;
              const lTemplate = lc.layoutTemplate || lc.layout_template;
              const sRatio = typeof lc.splitRatio === 'number' ? lc.splitRatio : (typeof lc.split_ratio === 'number' ? lc.split_ratio : undefined);
              const fBox = lc.facecamBox || lc.facecam_box;
              const gBox = lc.gameplayBox || lc.gameplay_box;
              const pfm = lc.paneFitMode || lc.pane_fit_mode;
              const dft = typeof lc.dynamicFacecamTracking === 'boolean'
                ? lc.dynamicFacecamTracking
                : (typeof lc.dynamic_facecam_tracking === 'boolean' ? lc.dynamic_facecam_tracking : undefined);
              const gtm = lc.gamingTrackingMode || lc.gaming_tracking_mode;
              const rts = typeof lc.referenceTimeSec === 'number'
                ? lc.referenceTimeSec
                : (typeof lc.reference_time_sec === 'number' ? lc.reference_time_sec : undefined);

              next.framingConfig = {
                ...prev.framingConfig,
                ...(fMode ? { framingMode: fMode } : {}),
                ...(aRatio ? { aspectRatio: aRatio } : {}),
                ...(lTemplate ? { layoutTemplate: lTemplate } : {}),
                ...(sRatio !== undefined ? { splitRatio: sRatio } : {}),
                ...(pfm ? { paneFitMode: pfm } : {}),
                ...(fBox ? { facecamBox: fBox } : {}),
                ...(gBox ? { gameplayBox: gBox } : {}),
                ...(dft !== undefined ? { dynamicFacecamTracking: dft } : {}),
                ...(gtm ? { gamingTrackingMode: gtm } : {}),
                ...(rts !== undefined ? { referenceTimeSec: rts } : {}),
              };
            }
            if (wsConfig.captionConfig && Object.keys(wsConfig.captionConfig).length > 0) {
              next.captionConfig = { ...prev.captionConfig, ...(wsConfig.captionConfig as any) };
            }
            const ec = wsConfig.exportConfig || (wsConfig as any).export_config;
            if (ec && typeof ec.burnCaptions === 'boolean') {
              next.burnCaptions = ec.burnCaptions;
            } else if (wsConfig.captionConfig && typeof (wsConfig.captionConfig as any).burnCaptions === 'boolean') {
              next.burnCaptions = (wsConfig.captionConfig as any).burnCaptions;
            } else {
              const saved = localStorage.getItem(`clipforge_burn_captions_${projectId}`);
              if (saved !== null) {
                next.burnCaptions = saved === 'true';
              }
            }
            return next;
          });
        }
        setError('');
      }).catch((cause) => alive && setError(cause.message || 'Could not load project clips'));
    return () => { alive = false; };
  }, [projectId, setActiveProjectId]);

  // Persist burnCaptions to workspace config and localStorage
  const hasExportLoadedRef = useRef(false);
  useEffect(() => {
    if (!projectId) return;
    if (!hasExportLoadedRef.current) {
      hasExportLoadedRef.current = true;
      return;
    }
    localStorage.setItem(`clipforge_burn_captions_${projectId}`, String(options.burnCaptions));
    const timer = window.setTimeout(() => {
      api.patchWorkspaceConfig(projectId, {
        exportConfig: { burnCaptions: options.burnCaptions },
      }).catch(console.error);
    }, 600);
    return () => window.clearTimeout(timer);
  }, [projectId, options.burnCaptions]);

  useEffect(() => {
    if (!projectId) return;
    const socket = new WebSocket(api.getProjectWebSocketUrl(projectId));
    socket.onmessage = (event) => {
      try {
        const message = JSON.parse(event.data);
        if (message.type !== 'export_progress' || !message.job) return;
        const update = message.job as ExportJob;
        setJobs((current) => [update, ...current.filter((job) => job.id !== update.id)]);
      } catch { /* Ignore unrelated project messages. */ }
    };
    return () => socket.close();
  }, [projectId]);

  useEffect(() => () => {
    if (previewUrlRef.current) URL.revokeObjectURL(previewUrlRef.current);
  }, []);

  const activeClip = useMemo(() => clips.find((clip) => clip.id === activeClipId) || null, [clips, activeClipId]);
  const filteredClips = useMemo(() => clips.filter((clip) => clip.viralScore >= minViralScore), [clips, minViralScore]);
  const duration = project?.durationSec || 1;
  const activeBounds = activeClip ? (boundsById[activeClip.id] || { startSec: activeClip.startSec, endSec: activeClip.endSec }) : { startSec: 0, endSec: 1 };
  const audioEnergy = useMemo(() => (project?.engagementSignals?.audioEnergy || []).map((point) => ({ timeSec: point.timeSec, score: point.score })), [project?.engagementSignals?.audioEnergy]);
  const activeJobs = jobs.filter((job) => job.status === 'queued' || job.status === 'running');

  const updateBounds = useCallback((next: Bounds) => {
    if (!activeClip) return;
    setBoundsById((current) => ({ ...current, [activeClip.id]: next }));
  }, [activeClip]);

  const updateSidecar = (key: keyof ExportOptions['sidecars']) => setOptions((current) => ({
    ...current, sidecars: { ...current.sidecars, [key]: !current.sidecars[key] },
  }));

  const preview = async () => {
    if (!project || !activeClip) return;
    setError(''); setNotice(''); setIsPreviewing(true);
    try {
      const blob = await api.previewExport(project.id, activeBounds.startSec, activeBounds.endSec, options);
      const url = URL.createObjectURL(blob);
      if (previewUrlRef.current) URL.revokeObjectURL(previewUrlRef.current);
      previewUrlRef.current = url;
      setPreviewUrl(url);
      setNotice('5-second preview is ready.');
    } catch (cause: any) {
      setError(cause.message || 'Preview render failed');
    } finally { setIsPreviewing(false); }
  };

  const openMergeModal = () => {
    const sel = clips.filter((c) => selectedIds.has(c.id));
    if (sel.length < 2 || sel.length > 5) return;
    setMergeOrder(sel.map((c) => c.id));
    const defaultTitle = `${sel[0].title} + ${sel[1].title}${sel.length > 2 ? ` (+${sel.length - 2} more)` : ''} (Combined)`;
    setMergedTitle(defaultTitle);
    setIsMergeModalOpen(true);
  };

  const moveMergeItem = (idx: number, direction: 'up' | 'down') => {
    const targetIdx = direction === 'up' ? idx - 1 : idx + 1;
    if (targetIdx < 0 || targetIdx >= mergeOrder.length) return;
    const next = [...mergeOrder];
    const [removed] = next.splice(idx, 1);
    next.splice(targetIdx, 0, removed);
    setMergeOrder(next);
  };

  const confirmMerge = async () => {
    if (!project || mergeOrder.length < 2) return;
    const orderedClips = mergeOrder
      .map((id) => clips.find((c) => c.id === id))
      .filter((c): c is CandidateClip => Boolean(c));

    const combinedSegments = orderedClips.flatMap((c) => {
      if (c.segments && c.segments.length > 0) {
        return c.segments;
      }
      const b = boundsById[c.id] || { startSec: c.startSec, endSec: c.endSec };
      return [{ startSec: b.startSec, endSec: b.endSec, label: c.title }];
    });

    const totalDur = Math.round(combinedSegments.reduce((sum, s) => sum + Math.max(0, s.endSec - s.startSec), 0) * 100) / 100;
    const newId = `merged_${Date.now()}`;
    const newClip: CandidateClip = {
      id: newId,
      title: mergedTitle.trim() || `Merged Compilation (${orderedClips.length} parts)`,
      hookSummary: `Multi-cut compilation stitched from ${orderedClips.length} moments.`,
      startSec: combinedSegments[0]?.startSec || 0,
      endSec: combinedSegments[combinedSegments.length - 1]?.endSec || 0,
      durationSec: totalDur,
      viralScore: Math.round(orderedClips.reduce((max, c) => Math.max(max, c.viralScore), 75)),
      reason: `Manually combined from: ${orderedClips.map((c) => c.title).join(', ')}`,
      suggestedHashtags: Array.from(new Set(orderedClips.flatMap((c) => c.suggestedHashtags))).slice(0, 5),
      detectedMood: orderedClips[0]?.detectedMood || 'hype',
      snappedToScene: false,
      segments: combinedSegments,
    };

    const nextClips = [newClip, ...clips];
    setClips(nextClips);
    setActiveClipId(newClip.id);
    setSelectedIds(new Set([newClip.id]));
    setBoundsById((prev) => ({
      ...prev,
      [newClip.id]: { startSec: newClip.startSec, endSec: newClip.endSec },
    }));
    setIsMergeModalOpen(false);

    try {
      await api.updateClips(project.id, nextClips);
      setNotice(`Merged ${orderedClips.length} clips into "${newClip.title}".`);
    } catch (err: any) {
      setError(`Failed to save merged clip: ${err.message}`);
    }
  };

  const startBatch = async () => {
    if (!project) return;
    const selected = clips.filter((clip) => selectedIds.has(clip.id));
    if (!selected.length) { setError('Select at least one clip to export.'); return; }
    const exportClips = selected.map((clip) => ({
      clipId: clip.id, title: clip.title, hookSummary: clip.hookSummary,
      suggestedHashtags: clip.suggestedHashtags,
      segments: clip.segments || [],
      ...(boundsById[clip.id] || { startSec: clip.startSec, endSec: clip.endSec }),
    }));
    setIsQueueing(true); setError(''); setNotice('');
    try {
      const response = await api.startExportBatch(project.id, exportClips, options);
      setJobs((current) => [response.job, ...current.filter((job) => job.id !== response.job.id)]);
      setNotice(`Queued ${selected.length} clip${selected.length === 1 ? '' : 's'}.`);
    } catch (cause: any) { setError(cause.message || 'Could not queue exports'); }
    finally { setIsQueueing(false); }
  };

  const cancel = async (job: ExportJob) => {
    if (!project) return;
    try { await api.cancelExport(project.id, job.id); }
    catch (cause: any) { setError(cause.message || 'Could not cancel export'); }
  };

  const setFraming = (
    key: 'framingMode' | 'aspectRatio' | 'layoutTemplate' | 'paneFitMode',
    value: string
  ) => {
    setOptions((current) => {
      const nextConfig = { ...current.framingConfig, [key]: value };
      if (key === 'framingMode') {
        const mode = value as FramingMode;
        const validTemplates = MODE_LAYOUT_OPTIONS[mode];
        if (validTemplates && !validTemplates.some((t) => t.id === nextConfig.layoutTemplate)) {
          nextConfig.layoutTemplate = validTemplates[0].id;
        }
      }
      if (!nextConfig.facecamBox) {
        nextConfig.facecamBox = { x: 0.0, y: 0.0, w: 0.3, h: 0.25 };
      }
      if (!nextConfig.gameplayBox) {
        nextConfig.gameplayBox = { x: 0.0, y: 0.0, w: 1.0, h: 1.0 };
      }
      return { ...current, framingConfig: nextConfig as FramingConfig };
    });
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <div className="flex items-center gap-2 text-cyan-300 text-xs font-mono uppercase tracking-[.18em]"><Scissors className="h-4 w-4" /> Phase 6 · Clip Workbench</div>
          <h1 className="mt-2 text-3xl font-semibold tracking-tight text-white">Trim, polish, export.</h1>
          <p className="mt-1 max-w-2xl text-sm text-slate-400">Shape the clip, check a five-second render, then send one or more clips through the local export queue.</p>
        </div>
        <label className="grid gap-1 text-[11px] font-mono uppercase tracking-wider text-slate-500">
          Source project
          <span className="relative min-w-64">
            <select
              value={projectId}
              onChange={(event) => {
                setProjectId(event.target.value);
                setActiveProjectId(event.target.value);
              }}
              className="w-full appearance-none rounded-lg border border-slate-700 bg-slate-900 px-3 py-2.5 pr-9 text-sm font-sans text-slate-100 outline-none focus:border-cyan-500"
            >
              {projects.map((item) => <option key={item.id} value={item.id}>{item.title}</option>)}
            </select><ChevronDown className="pointer-events-none absolute right-3 top-3 h-4 w-4 text-slate-400" />
          </span>
        </label>
      </div>

      {project && (
        <div className="flex flex-wrap items-center gap-3 rounded-xl border border-cyan-900/50 bg-cyan-950/20 px-4 py-2.5 text-xs font-mono text-cyan-300">
          <span className="font-semibold text-cyan-400">▶ Export will render:</span>
          <span>Project: <strong className="text-white">{project.title}</strong></span>
          <span className="text-slate-500">·</span>
          <span>Layout: <strong className="text-white">{options.framingConfig.layoutTemplate.replace(/_/g, ' ')}</strong> ({options.framingConfig.aspectRatio} · {options.framingConfig.paneFitMode || 'fill'})</span>
          <span className="text-slate-500">·</span>
          <span>Captions: <strong className="text-white">{options.burnCaptions ? `${options.captionConfig.preset.replace(/_/g, ' ')}${options.captionConfig.glowEnabled ? ' (glow)' : ''}` : 'off'}</strong></span>
          <span className="text-slate-500">·</span>
          <span>Clips: <strong className="text-white">{selectedIds.size}</strong> selected</span>
        </div>
      )}

      {error && <div role="alert" className="rounded-lg border border-rose-800/80 bg-rose-950/40 px-4 py-3 text-sm text-rose-200">{error}</div>}
      {notice && <div role="status" className="rounded-lg border border-emerald-800/80 bg-emerald-950/30 px-4 py-3 text-sm text-emerald-200">{notice}</div>}

      {!projects.length ? (
        <div className="rounded-2xl border border-dashed border-slate-700 bg-slate-900/50 p-12 text-center">
          <Film className="mx-auto h-8 w-8 text-slate-500" />
          <h2 className="mt-3 text-lg font-medium text-slate-200">No ready projects yet</h2>
          <p className="mt-1 text-sm text-slate-500">Ingest a video and discover clips in Studio Workbench first.</p>
        </div>
      ) : (
        <>
          <div className="grid gap-5 xl:grid-cols-[minmax(0,1.5fr)_minmax(330px,.8fr)]">
            <section className="min-w-0 space-y-4 rounded-2xl border border-slate-800 bg-slate-950/75 p-5 shadow-xl shadow-black/10">
              <div className="flex items-center justify-between gap-3">
                <div><div className="text-[11px] font-mono uppercase tracking-wider text-slate-500">Clip timeline</div><h2 className="mt-1 text-lg font-medium text-white">{activeClip?.title || 'Select a clip'}</h2></div>
                <button onClick={() => setSelectedIds(new Set(selectedIds.size === filteredClips.length ? [] : filteredClips.map((clip) => clip.id)))} className="rounded-lg border border-slate-700 px-3 py-2 text-xs text-slate-300 hover:border-cyan-700 hover:text-cyan-200">{selectedIds.size === filteredClips.length ? 'Clear selection' : 'Select all'}</button>
              </div>
              {activeClip && <WaveformTrim duration={duration} bounds={activeBounds} energy={audioEnergy} onCommit={updateBounds} />}
              <div className="flex flex-wrap items-center justify-between gap-2 text-[11px] text-slate-500"><span>Drag either cyan handle to trim</span><span>Source {formatTime(duration)}</span></div>

              {/* Min Viral Score Filter & Quick-select controls */}
              <div className="space-y-2 pb-2 border-b border-slate-800">
                <div className="flex items-center justify-between">
                  <label className="text-[11px] font-mono uppercase tracking-wider text-slate-500">
                    Min Viral Score Filter: <span className="text-cyan-300 font-bold">{minViralScore}+</span>
                  </label>
                  <div className="flex gap-1.5">
                    <button
                      type="button"
                      onClick={() => setSelectedIds(new Set(filteredClips.map((c) => c.id)))}
                      className="px-2 py-1 rounded text-[10px] font-mono border border-slate-700 text-slate-300 hover:border-cyan-700"
                    >
                      Select Filtered ({filteredClips.length})
                    </button>
                    <button
                      type="button"
                      onClick={() => setSelectedIds(new Set(clips.filter((c) => c.viralScore >= 70).map((c) => c.id)))}
                      className="px-2 py-1 rounded text-[10px] font-mono border border-violet-800 text-violet-300 hover:border-violet-600"
                    >
                      AI Recommended (≥70)
                    </button>
                    <button
                      type="button"
                      onClick={() => setSelectedIds(new Set())}
                      className="px-2 py-1 rounded text-[10px] font-mono border border-slate-700 text-slate-400 hover:border-slate-500"
                    >
                      Clear
                    </button>
                    {selectedIds.size >= 2 && selectedIds.size <= 5 && (
                      <button
                        type="button"
                        onClick={openMergeModal}
                        className="px-2.5 py-1 rounded text-[10px] font-mono font-bold bg-cyan-600 hover:bg-cyan-500 text-white flex items-center gap-1 transition-all shadow-sm shadow-cyan-950"
                      >
                        <Layers className="h-3 w-3" />
                        Combine 2–5 Clips
                      </button>
                    )}
                  </div>
                </div>
                <input
                  type="range"
                  min={0}
                  max={100}
                  step={5}
                  value={minViralScore}
                  onChange={(e) => setMinViralScore(Number(e.target.value))}
                  className="w-full accent-violet-500"
                />
                {filteredClips.length === 0 && minViralScore > 0 && (
                  <p className="text-[11px] text-amber-400 font-mono">
                    No clips meet score ≥ {minViralScore}. Lower the filter or discover more clips.
                  </p>
                )}
              </div>

              <div className="max-h-[360px] space-y-2 overflow-y-auto pr-1">
                {filteredClips.map((clip) => <ClipRow key={clip.id} clip={clip} selected={selectedIds.has(clip.id)} active={activeClipId === clip.id} bounds={boundsById[clip.id] || { startSec: clip.startSec, endSec: clip.endSec }} onSelect={() => setSelectedIds((current) => { const next = new Set(current); next.has(clip.id) ? next.delete(clip.id) : next.add(clip.id); return next; })} onActivate={() => setActiveClipId(clip.id)} />)}
                {!clips.length && <p className="rounded-lg border border-dashed border-slate-800 p-5 text-center text-sm text-slate-500">No candidate clips were discovered for this video.</p>}
                {clips.length > 0 && filteredClips.length === 0 && <p className="rounded-lg border border-dashed border-slate-800 p-5 text-center text-sm text-slate-500">No clips match score ≥ {minViralScore}.</p>}
              </div>
            </section>

            <aside className="space-y-4">
              <section className="overflow-hidden rounded-2xl border border-slate-800 bg-slate-950/75 shadow-xl shadow-black/10">
                <div className="flex items-center justify-between border-b border-slate-800 px-4 py-3"><span className="flex items-center gap-2 text-sm font-medium text-slate-200"><Clapperboard className="h-4 w-4 text-cyan-300" />Quick framing preview</span><span className="rounded bg-slate-800 px-2 py-1 text-[10px] font-mono text-cyan-200">5 SEC</span></div>
                <video ref={videoRef} key={previewUrl || projectId} src={previewUrl || (project ? api.getVideoStreamUrl(project.id) : undefined)} controls playsInline className="aspect-video w-full bg-black object-contain" onLoadedMetadata={(event) => { if (!previewUrl && activeClip) event.currentTarget.currentTime = activeBounds.startSec; }} />
                <div className="grid grid-cols-2 gap-2 p-3">
                  <button onClick={preview} disabled={!activeClip || isPreviewing} className="flex items-center justify-center gap-2 rounded-lg bg-cyan-400 px-3 py-2.5 text-sm font-semibold text-slate-950 transition hover:bg-cyan-300 disabled:opacity-50">{isPreviewing ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4 fill-current" />}Render 5s Preview</button>
                  <button onClick={() => { if (videoRef.current) videoRef.current.currentTime = activeBounds.startSec; }} disabled={!activeClip} className="rounded-lg border border-slate-700 px-3 py-2 text-sm text-slate-300 hover:border-slate-500 disabled:opacity-50">Jump to In</button>
                </div>
              </section>

              <section className="space-y-4 rounded-2xl border border-slate-800 bg-slate-950/75 p-4">
                <div className="flex items-center gap-2 text-sm font-medium text-slate-200"><Activity className="h-4 w-4 text-teal-300" />Audio polish</div>
                <label className="flex cursor-pointer items-center justify-between gap-4 rounded-lg bg-slate-900/70 px-3 py-2.5"><span><span className="block text-sm text-slate-200">Loudness normalization</span><span className="text-[11px] text-slate-500">Target −14 LUFS · true peak −1.5 dB</span></span><input type="checkbox" checked={options.normalizeLoudness} onChange={() => setOptions((value) => ({ ...value, normalizeLoudness: !value.normalizeLoudness }))} className="accent-cyan-400" /></label>
                <div className="rounded-lg bg-slate-900/70 p-3">
                  <label className="flex cursor-pointer items-center justify-between gap-4"><span><span className="block text-sm text-slate-200">Remove dead air</span><span className="text-[11px] text-slate-500">Cuts matching video and audio spans</span></span><input type="checkbox" checked={options.removeSilence} onChange={() => setOptions((value) => ({ ...value, removeSilence: !value.removeSilence }))} className="accent-cyan-400" /></label>
                  {options.removeSilence && <div className="mt-3 grid grid-cols-2 gap-3"><label className="text-[10px] font-mono uppercase text-slate-500">Threshold dB<input type="number" min={-80} max={-10} value={options.silenceThresholdDb} onChange={(event) => setOptions((value) => ({ ...value, silenceThresholdDb: Number(event.target.value) }))} className="mt-1 w-full rounded-md border border-slate-700 bg-slate-950 px-2 py-1.5 text-sm text-slate-200" /></label><label className="text-[10px] font-mono uppercase text-slate-500">Min pause sec<input type="number" min={.1} max={10} step={.1} value={options.silenceMinDurationSec} onChange={(event) => setOptions((value) => ({ ...value, silenceMinDurationSec: Number(event.target.value) }))} className="mt-1 w-full rounded-md border border-slate-700 bg-slate-950 px-2 py-1.5 text-sm text-slate-200" /></label></div>}
                </div>
                <label className="flex cursor-pointer items-center justify-between gap-4 rounded-lg bg-slate-900/70 px-3 py-2.5">
                  <span>
                    <span className="block text-sm text-slate-200">Burn captions into video</span>
                    <span className="text-[11px] text-slate-500">Render styled captions onto video stream</span>
                  </span>
                  <input
                    type="checkbox"
                    checked={options.burnCaptions}
                    onChange={() => setOptions((value) => ({ ...value, burnCaptions: !value.burnCaptions }))}
                    className="accent-cyan-400"
                  />
                </label>
                <div className="grid grid-cols-2 gap-3">
                  <label className="text-[10px] font-mono uppercase text-slate-500">
                    Framing mode
                    <select
                      value={options.framingConfig.framingMode}
                      onChange={(event) => setFraming('framingMode', event.target.value)}
                      className="mt-1 w-full rounded-md border border-slate-700 bg-slate-900 px-2 py-2 text-xs text-slate-200"
                    >
                      <option value="gaming">Gaming</option>
                      <option value="podcast">Podcast</option>
                      <option value="talking_head">Talking head</option>
                      <option value="screen_presenter">Screen + presenter</option>
                      <option value="reaction">Reaction</option>
                    </select>
                  </label>
                  <label className="text-[10px] font-mono uppercase text-slate-500">
                    Canvas ratio
                    <select
                      value={options.framingConfig.aspectRatio}
                      onChange={(event) => setFraming('aspectRatio', event.target.value)}
                      className="mt-1 w-full rounded-md border border-slate-700 bg-slate-900 px-2 py-2 text-xs text-slate-200"
                    >
                      <option value="9:16">9:16 vertical</option>
                      <option value="1:1">1:1 square</option>
                      <option value="16:9">16:9 landscape</option>
                    </select>
                  </label>
                  <label className="col-span-2 text-[10px] font-mono uppercase text-slate-500">
                    Layout
                    <select
                      value={options.framingConfig.layoutTemplate}
                      onChange={(event) => setFraming('layoutTemplate', event.target.value)}
                      className="mt-1 w-full rounded-md border border-slate-700 bg-slate-900 px-2 py-2 text-xs text-slate-200"
                    >
                      {(MODE_LAYOUT_OPTIONS[options.framingConfig.framingMode] || []).map((t) => (
                        <option key={t.id} value={t.id}>{t.label}</option>
                      ))}
                    </select>
                  </label>
                  <label className="col-span-2 text-[10px] font-mono uppercase text-slate-500">
                    Pane Fit Mode
                    <select
                      value={options.framingConfig.paneFitMode || 'fill'}
                      onChange={(event) => setFraming('paneFitMode', event.target.value)}
                      className="mt-1 w-full rounded-md border border-slate-700 bg-slate-900 px-2 py-2 text-xs text-slate-200"
                    >
                      <option value="fill">Fill (Edge-to-edge, zero black bars)</option>
                      <option value="fit">Fit (Letterbox/pillarbox padding)</option>
                    </select>
                  </label>
                </div>
                <div className="space-y-2 border-t border-slate-800 pt-3">
                  <div className="text-[10px] font-mono uppercase tracking-wider text-slate-500">Optional files next to each MP4</div>
                  <div className="grid grid-cols-2 gap-2 text-xs text-slate-300">
                    {([['srt', '.srt subtitles'], ['ass', '.ass subtitles'], ['metadataJson', '.json metadata'], ['metadataTxt', '.txt metadata']] as const).map(([key, label]) => <label key={key} className="flex cursor-pointer items-center gap-2"><input type="checkbox" disabled={(key === 'srt' || key === 'ass') && !project?.hasTranscript} checked={options.sidecars[key]} onChange={() => updateSidecar(key)} className="accent-cyan-400" />{label}</label>)}
                  </div>
                  {!project?.hasTranscript && <p className="text-[10px] text-amber-300/80">Subtitle sidecars need a saved transcript.</p>}
                </div>
                <button onClick={startBatch} disabled={!selectedIds.size || isQueueing || activeJobs.length > 0} className="flex w-full items-center justify-center gap-2 rounded-lg bg-gradient-to-r from-teal-300 to-cyan-400 px-4 py-3 text-sm font-bold text-slate-950 transition hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-45"><Download className="h-4 w-4" />{isQueueing ? 'Queueing…' : `Export ${selectedIds.size} selected clip${selectedIds.size === 1 ? '' : 's'}`}</button>
                <p className="text-center text-[10px] text-slate-600">CFR video · NVENC with automatic CPU fallback · outputs stay local</p>
              </section>
            </aside>
          </div>

          <section className="rounded-2xl border border-slate-800 bg-slate-950/75 p-5">
            <div className="mb-4 flex items-center justify-between"><div><h2 className="text-lg font-medium text-white">Export queue</h2><p className="text-xs text-slate-500">Updates live over the project WebSocket</p></div><span className="rounded-full border border-slate-700 px-2.5 py-1 text-[10px] font-mono text-slate-400">{jobs.length} JOBS</span></div>
            <div className="space-y-3">
              {jobs.map((job) => <div key={job.id} className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
                <div className="flex flex-wrap items-center justify-between gap-3"><div className="flex items-center gap-2"><span className={`h-2 w-2 rounded-full ${job.status === 'running' ? 'animate-pulse bg-cyan-400' : job.status === 'completed' ? 'bg-emerald-400' : job.status === 'error' ? 'bg-rose-400' : job.status === 'cancelled' ? 'bg-slate-500' : 'bg-amber-300'}`} /><span className="text-sm font-medium capitalize text-slate-200">{job.status}</span><span className="text-xs text-slate-500">{job.completedClips}/{job.totalClips} clips</span>{job.currentClip && <span className="text-xs text-cyan-300">· {job.currentClip}</span>}</div>
                  <div className="flex items-center gap-2">{job.status === 'queued' || job.status === 'running' ? <button onClick={() => cancel(job)} className="flex items-center gap-1 rounded-md border border-rose-900/80 px-2.5 py-1.5 text-xs text-rose-300 hover:bg-rose-950/50"><X className="h-3.5 w-3.5" />Cancel batch</button> : job.status === 'completed' ? <span className="flex items-center gap-1 text-xs text-emerald-300"><Check className="h-3.5 w-3.5" />Ready</span> : null}</div>
                </div>
                <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-slate-800"><div className="h-full rounded-full bg-gradient-to-r from-teal-300 to-cyan-400 transition-[width] duration-300" style={{ width: `${job.progressPercent}%` }} /></div>
                {job.error && <p className="mt-2 text-xs text-rose-300">{job.error}</p>}
                {job.outputFiles.length > 0 && <div className="mt-3 flex flex-wrap gap-2">{job.outputFiles.map((path) => { const name = path.split(/[\\/]/).pop() || path; return <a key={path} href={api.getExportFileUrl(job.projectId, job.id, name)} className="rounded-md border border-slate-700 px-2.5 py-1.5 text-[11px] text-cyan-200 hover:border-cyan-700 hover:bg-cyan-950/30">{name}</a>; })}</div>}
              </div>)}
              {!jobs.length && <div className="flex items-center gap-3 rounded-xl border border-dashed border-slate-800 p-5 text-sm text-slate-500"><Square className="h-4 w-4" />Nothing in the queue yet. Select clips and start an export.</div>}
            </div>
          </section>
        </>
      )}

      {isMergeModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 p-4 backdrop-blur-sm">
          <div className="w-full max-w-lg rounded-2xl border border-cyan-800 bg-slate-900 p-6 shadow-2xl space-y-4">
            <div className="flex items-center justify-between border-b border-slate-800 pb-3">
              <div className="flex items-center gap-2">
                <Layers className="h-5 w-5 text-cyan-400" />
                <h3 className="text-base font-semibold text-white">Combine 2–5 Clips</h3>
              </div>
              <button
                onClick={() => setIsMergeModalOpen(false)}
                className="text-slate-400 hover:text-white p-1 rounded hover:bg-slate-800"
              >
                <X className="h-4 w-4" />
              </button>
            </div>

            <p className="text-xs text-slate-400">
              Arrange 2–5 selected moments in playback order. The combined clip will stitch all segments with seamless PTS and audio fade.
            </p>

            <div>
              <label className="block text-[11px] font-mono uppercase text-slate-400 mb-1">Compilation Title</label>
              <input
                type="text"
                value={mergedTitle}
                onChange={(e) => setMergedTitle(e.target.value)}
                className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-xs text-slate-100 font-medium"
              />
            </div>

            <div className="space-y-2 max-h-56 overflow-y-auto pr-1">
              {mergeOrder.map((id, idx) => {
                const c = clips.find((item) => item.id === id);
                if (!c) return null;
                const b = boundsById[c.id] || { startSec: c.startSec, endSec: c.endSec };
                return (
                  <div
                    key={id}
                    className="flex items-center justify-between gap-3 p-2.5 rounded-lg border border-slate-800 bg-slate-950/70"
                  >
                    <div className="flex items-center gap-2.5 min-w-0 flex-1">
                      <span className="w-5 h-5 rounded bg-cyan-950 text-cyan-300 border border-cyan-800 text-[10px] font-mono font-bold flex items-center justify-center flex-shrink-0">
                        {idx + 1}
                      </span>
                      <div className="min-w-0">
                        <span className="block truncate text-xs font-medium text-slate-200">{c.title}</span>
                        <span className="block text-[10px] text-slate-500 font-mono">
                          {formatTime(b.startSec)}–{formatTime(b.endSec)} ({Math.round(b.endSec - b.startSec)}s)
                        </span>
                      </div>
                    </div>

                    <div className="flex items-center gap-1">
                      <button
                        type="button"
                        disabled={idx === 0}
                        onClick={() => moveMergeItem(idx, 'up')}
                        className="p-1 rounded bg-slate-800 hover:bg-slate-700 disabled:opacity-30 text-slate-300"
                        title="Move Up"
                      >
                        <ArrowUp className="h-3.5 w-3.5" />
                      </button>
                      <button
                        type="button"
                        disabled={idx === mergeOrder.length - 1}
                        onClick={() => moveMergeItem(idx, 'down')}
                        className="p-1 rounded bg-slate-800 hover:bg-slate-700 disabled:opacity-30 text-slate-300"
                        title="Move Down"
                      >
                        <ArrowDown className="h-3.5 w-3.5" />
                      </button>
                    </div>
                  </div>
                );
              })}
            </div>

            <div className="flex items-center justify-between border-t border-slate-800 pt-3">
              <span className="text-xs font-mono text-cyan-300">
                {mergeOrder.length} parts selected
              </span>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={() => setIsMergeModalOpen(false)}
                  className="rounded-lg border border-slate-700 px-3 py-1.5 text-xs text-slate-300 hover:bg-slate-800"
                >
                  Cancel
                </button>
                <button
                  type="button"
                  onClick={confirmMerge}
                  className="rounded-lg bg-cyan-500 hover:bg-cyan-400 px-4 py-1.5 text-xs font-bold text-slate-950"
                >
                  Combine into 1 Clip
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
