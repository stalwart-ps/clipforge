import React, { memo, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Check, Download, Loader2, Play, RefreshCw, Save, Sparkles } from 'lucide-react';
import { api } from '../api/client';
import { useWorkspace } from '../context/WorkspaceContext';
import {
  CaptionAnimation,
  CaptionConfig,
  CaptionPreset,
  ProjectRead,
  ProjectSummary,
  TranscriptSegment,
  WordTimestamp,
} from '../types/project';

const PRESETS: Record<CaptionPreset, CaptionConfig> = {
  hormozi_pop: { preset: 'hormozi_pop', fontName: 'Arial Black', fontSize: 78, primaryColor: '#FFFFFF', highlightColor: '#FFE600', outlineColor: '#000000', outlineWidth: 6, shadowDepth: 3, marginV: 180, maxWordsPerLine: 3, allCaps: true, animation: 'pop', profanityMask: false },
  karaoke_highlight: { preset: 'karaoke_highlight', fontName: 'Arial', fontSize: 62, primaryColor: '#FFFFFF', highlightColor: '#52F59B', outlineColor: '#111111', outlineWidth: 3, shadowDepth: 1, marginV: 140, maxWordsPerLine: 5, allCaps: false, animation: 'highlight', profanityMask: false },
  minimal_clean: { preset: 'minimal_clean', fontName: 'Arial', fontSize: 54, primaryColor: '#FFFFFF', highlightColor: '#FFFFFF', outlineColor: '#111111', outlineWidth: 1, shadowDepth: 2, marginV: 110, maxWordsPerLine: 6, allCaps: false, animation: 'none', profanityMask: false },
  gaming_neon: { preset: 'gaming_neon', fontName: 'Arial Black', fontSize: 66, primaryColor: '#E7FCFF', highlightColor: '#00F5FF', outlineColor: '#E000FF', outlineWidth: 5, shadowDepth: 4, marginV: 300, maxWordsPerLine: 4, allCaps: true, animation: 'bounce', profanityMask: false },
  boxed_pill: { preset: 'boxed_pill', fontName: 'Arial', fontSize: 58, primaryColor: '#FFFFFF', highlightColor: '#FFE875', outlineColor: '#171717', outlineWidth: 2, shadowDepth: 1, marginV: 130, maxWordsPerLine: 4, allCaps: false, animation: 'highlight', profanityMask: false },
};

const PRESET_LABELS: Record<CaptionPreset, string> = {
  hormozi_pop: 'Hormozi Pop', karaoke_highlight: 'Karaoke Highlight', minimal_clean: 'Minimal Clean',
  gaming_neon: 'Gaming Neon', boxed_pill: 'Boxed Pill',
};

const PROFANITY = /\b(fuck(?:ing|ed|er|s)?|shit(?:ty|s)?|bitch(?:es)?|asshole|damn|bastard)\b/i;
const maskWord = (word: string) => word.replace(PROFANITY, (match) => `${match[0]}***`);

function useDebounced<T>(value: T, delay: number): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const timer = window.setTimeout(() => setDebounced(value), delay);
    return () => window.clearTimeout(timer);
  }, [value, delay]);
  return debounced;
}

interface PreviewProps {
  videoRef: React.MutableRefObject<HTMLVideoElement | null>;
  projectId: string | null;
  time: number;
  segments: TranscriptSegment[];
  config: CaptionConfig;
  playTimeRef: React.MutableRefObject<number>;
}

const CaptionPreview = memo(function CaptionPreview({ videoRef, projectId, time, segments, config, playTimeRef }: PreviewProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const words = useMemo(() => segments.flatMap((segment) => segment.words), [segments]);
  useEffect(() => {
    const video = videoRef.current;
    const canvas = canvasRef.current;
    const context = canvas?.getContext('2d');
    if (!canvas || !context) return;
    let frame = 0;
    let raf = 0;
    const draw = () => {
      const width = canvas.width;
      const height = canvas.height;
      const videoTime = video?.currentTime ?? playTimeRef.current;
      context.clearRect(0, 0, width, height);
      if (video && video.readyState >= 2 && video.videoWidth > 0) {
        const scale = Math.max(width / video.videoWidth, height / video.videoHeight);
        const drawW = video.videoWidth * scale;
        const drawH = video.videoHeight * scale;
        context.drawImage(video, (width - drawW) / 2, (height - drawH) / 2, drawW, drawH);
      } else {
        context.fillStyle = '#101722';
        context.fillRect(0, 0, width, height);
        context.fillStyle = '#7f8fa3';
        context.font = '16px sans-serif';
        context.textAlign = 'center';
        context.fillText('Select a transcribed video to preview captions', width / 2, height / 2);
      }
      let active = -1;
      for (let i = 0; i < words.length; i += 1) {
        if (videoTime >= words[i].start && videoTime <= words[i].end) { active = i; break; }
      }
      if (active >= 0) {
        const groupSize = Math.max(1, config.maxWordsPerLine);
        const first = Math.floor(active / groupSize) * groupSize;
        const group = words.slice(first, first + groupSize);
        const previewScale = height / 1920;
        const fontSize = Math.max(14, config.fontSize * previewScale);
        const elapsed = Math.max(0, videoTime - words[active].start);
        let scaleFactor = 1;
        if (config.animation === 'pop' || config.animation === 'bounce') {
          scaleFactor = 1 + 0.14 * Math.max(0, 1 - elapsed / 0.2);
        }
        context.save();
        context.translate(width / 2, height - (config.marginV / 1920) * height);
        context.scale(scaleFactor, scaleFactor);
        context.font = `${['hormozi_pop', 'gaming_neon'].includes(config.preset) ? '900' : '700'} ${fontSize}px "${config.fontName}", sans-serif`;
        context.textAlign = 'left';
        context.textBaseline = 'middle';
        context.lineJoin = 'round';
        const shown = group.map((word) => config.profanityMask ? maskWord(word.word) : word.word)
          .map((word) => config.allCaps ? word.toUpperCase() : word);
        const widths = shown.map((word) => context.measureText(`${word} `).width);
        const totalWidth = widths.reduce((sum, value) => sum + value, 0);
        if (config.preset === 'boxed_pill') {
          context.fillStyle = 'rgba(0,0,0,.58)';
          context.beginPath();
          context.roundRect(-totalWidth / 2 - 22, -fontSize * 0.78, totalWidth + 44, fontSize * 1.56, fontSize * 0.32);
          context.fill();
        }
        let x = -totalWidth / 2;
        group.forEach((_word, index) => {
          const text = shown[index];
          context.lineWidth = config.outlineWidth * previewScale * 2;
          context.strokeStyle = config.outlineColor;
          context.shadowColor = 'rgba(0,0,0,.85)';
          context.shadowBlur = config.shadowDepth * previewScale * 2;
          context.shadowOffsetY = config.shadowDepth * previewScale;
          context.strokeText(text, x, 0);
          context.fillStyle = first + index === active ? config.highlightColor : config.primaryColor;
          context.fillText(text, x, 0);
          x += widths[index];
        });
        context.restore();
      }
      frame += 1;
      if (frame < 2 || (video && !video.paused && !video.ended)) raf = requestAnimationFrame(draw);
    };
    raf = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(raf);
  }, [videoRef, projectId, time, words, config, playTimeRef]);
  return <canvas ref={canvasRef} width={720} height={1280} className="aspect-[9/16] w-full max-h-[72vh] rounded-xl border border-slate-700 bg-slate-950 object-contain" aria-label="Live caption preview" />;
});

interface WordInputProps {
  word: WordTimestamp;
  segmentIndex: number;
  wordIndex: number;
  onCommit: (segmentIndex: number, wordIndex: number, patch: Partial<WordTimestamp>) => void;
}

const WordInput = memo(function WordInput({ word, segmentIndex, wordIndex, onCommit }: WordInputProps) {
  const [draft, setDraft] = useState(word.word);
  const [start, setStart] = useState(word.start);
  const [end, setEnd] = useState(word.end);
  useEffect(() => { setDraft(word.word); setStart(word.start); setEnd(word.end); }, [word.word, word.start, word.end]);
  return (
    <div
      className="inline-flex flex-wrap items-center gap-1 rounded border border-slate-700 bg-slate-900 px-2 py-1.5 focus-within:border-cyan-500"
      onBlur={(event) => {
        if (event.currentTarget.contains(event.relatedTarget as Node | null)) return;
        const patch: Partial<WordTimestamp> = {};
        if (draft !== word.word) patch.word = draft;
        if (start !== word.start) patch.start = start;
        if (end !== word.end) patch.end = end;
        if (Object.keys(patch).length) onCommit(segmentIndex, wordIndex, patch);
      }}
    >
      <input
        value={draft}
        aria-label={`Edit word ${word.word} at ${word.start.toFixed(2)} seconds`}
        onChange={(event) => setDraft(event.target.value)}
        onKeyDown={(event) => { if (event.key === 'Enter') event.currentTarget.blur(); }}
        className="w-20 bg-transparent text-sm text-slate-100 outline-none"
      />
      <input type="number" min="0" step="0.01" value={start} onChange={(event) => setStart(Number(event.target.value))} aria-label="Word start time" className="w-[4.4rem] bg-transparent text-[10px] font-mono text-slate-400 outline-none" />
      <input type="number" min="0" step="0.01" value={end} onChange={(event) => setEnd(Number(event.target.value))} aria-label="Word end time" className="w-[4.4rem] bg-transparent text-[10px] font-mono text-slate-400 outline-none" />
    </div>
  );
});

interface TranscriptEditorProps {
  segments: TranscriptSegment[];
  onCommit: WordInputProps['onCommit'];
  saving: boolean;
  saved: boolean;
}

const CaptionTranscriptEditor = memo(function CaptionTranscriptEditor({ segments, onCommit, saving, saved }: TranscriptEditorProps) {
  const [scrollTop, setScrollTop] = useState(0);
  const flat = useMemo(() => segments.flatMap((segment, segmentIndex) => segment.words.map((word, wordIndex) => ({ word, segmentIndex, wordIndex }))), [segments]);
  const itemHeight = 52;
  const visibleCount = 30;
  const start = Math.max(0, Math.floor(scrollTop / itemHeight) - 3);
  const visible = flat.slice(start, start + visibleCount);
  return (
    <section className="rounded-xl border border-slate-800 bg-slate-900/60">
      <div className="flex items-center justify-between border-b border-slate-800 px-4 py-3">
        <div>
          <h2 className="text-sm font-semibold text-slate-100">Word transcript</h2>
          <p className="mt-1 text-xs text-slate-400">Edit a word, then leave the field to save it and refresh the .ass file.</p>
        </div>
        <span className="inline-flex items-center gap-1 text-xs text-slate-400" aria-live="polite">
          {saving ? <><Loader2 className="h-3.5 w-3.5 animate-spin" /> Saving</> : saved ? <><Check className="h-3.5 w-3.5 text-emerald-400" /> Saved</> : 'Autosave on'}
        </span>
      </div>
      {flat.length === 0 ? <p className="p-4 text-sm text-slate-400">This transcript has no word timestamps.</p> : (
        <div className="h-[420px] overflow-auto p-3" onScroll={(event) => setScrollTop(event.currentTarget.scrollTop)}>
          <div style={{ height: start * itemHeight }} />
          <div className="space-y-2">
            {visible.map(({ word, segmentIndex, wordIndex }) => (
              <div key={`${segmentIndex}-${wordIndex}`} className="flex flex-wrap items-center gap-2">
                <span className="w-14 shrink-0 text-[10px] font-mono text-slate-500">#{segmentIndex + 1}</span>
                <WordInput word={word} segmentIndex={segmentIndex} wordIndex={wordIndex} onCommit={onCommit} />
              </div>
            ))}
          </div>
          <div style={{ height: Math.max(0, (flat.length - start - visible.length) * itemHeight) }} />
        </div>
      )}
    </section>
  );
});

export const CaptionStudio: React.FC = () => {
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [project, setProject] = useState<ProjectRead | null>(null);
  const [segments, setSegments] = useState<TranscriptSegment[]>([]);
  const segmentsRef = useRef<TranscriptSegment[]>([]);
  const [config, setConfig] = useState<CaptionConfig>(PRESETS.hormozi_pop);
  const debouncedConfig = useDebounced(config, 120);
  const [fonts, setFonts] = useState<string[]>(['Arial', 'Arial Black']);
  const [videoTime, setVideoTime] = useState(0);
  const [videoReady, setVideoReady] = useState(false);
  const playTimeRef = useRef(0);
  const videoRef = useRef<HTMLVideoElement>(null);
  const saveQueue = useRef<Promise<unknown>>(Promise.resolve());
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [busy, setBusy] = useState(false);
  const [rendering, setRendering] = useState(false);
  const [notice, setNotice] = useState('');
  const { activeProjectId, setActiveProjectId } = useWorkspace();
  const [error, setError] = useState('');
  const configRef = useRef(config);
  const projectIdRef = useRef<string | null>(null);
  configRef.current = config;
  projectIdRef.current = project?.id ?? null;

  const selectProject = useCallback(async (id: string) => {
    setError('');
    setNotice('');
    setProject(null);
    setActiveProjectId(id);
    try {
      const [selected, transcript, wsConfig] = await Promise.all([
        api.getProject(id),
        api.getTranscript(id),
        api.getWorkspaceConfig(id).catch(() => ({ layoutConfig: {}, captionConfig: {} })),
      ]);
      setProject(selected);
      setSegments(transcript.segments);
      segmentsRef.current = transcript.segments;
      setVideoTime(0);
      setVideoReady(false);
      playTimeRef.current = 0;
      if (videoRef.current) { videoRef.current.pause(); videoRef.current.load(); }
      if (wsConfig && wsConfig.captionConfig && Object.keys(wsConfig.captionConfig).length > 0) {
        setConfig(wsConfig.captionConfig as CaptionConfig);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Select a project with a transcript');
    }
  }, [setActiveProjectId]);

  useEffect(() => {
    Promise.all([api.listProjects(), api.getCaptionFonts().catch(() => ['Arial', 'Arial Black'])]).then(([items, availableFonts]) => {
      setProjects(items);
      setFonts(availableFonts.length ? availableFonts : ['Arial', 'Arial Black']);
      const preferredId = activeProjectId || items[0]?.id;
      if (preferredId) {
        selectProject(preferredId);
      }
    }).catch((err: unknown) => setError(err instanceof Error ? err.message : 'Could not load caption studio data'));
  }, []);

  // Debounced autosave captionConfig to backend
  const hasLoadedRef = useRef(false);
  useEffect(() => {
    if (!project?.id) return;
    if (!hasLoadedRef.current) {
      hasLoadedRef.current = true;
      return;
    }
    const timer = window.setTimeout(() => {
      api.patchWorkspaceConfig(project.id, {
        captionConfig: config as unknown as Record<string, unknown>,
      }).catch(console.error);
    }, 800);
    return () => window.clearTimeout(timer);
  }, [project?.id, config]);

  const commitWord = useCallback((segmentIndex: number, wordIndex: number, patch: Partial<WordTimestamp>) => {
    const projectId = projectIdRef.current;
    if (!projectId) return;
    const next = segmentsRef.current.map((segment, index) => index !== segmentIndex ? segment : {
      ...segment,
      words: segment.words.map((word, indexWord) => indexWord === wordIndex ? { ...word, ...patch } : word),
    });
    segmentsRef.current = next;
    setSegments(next);
    setSaving(true);
    setSaved(false);
    const currentConfig = configRef.current;
    saveQueue.current = saveQueue.current.catch(() => undefined).then(() => api.updateCaptionTranscript(projectId, next, currentConfig));
    saveQueue.current.then(() => { setSaving(false); setSaved(true); setNotice('Transcript and .ass captions saved'); })
      .catch((err: unknown) => { setSaving(false); setError(err instanceof Error ? err.message : 'Could not save transcript'); });
  }, []);

  const updateConfig = <K extends keyof CaptionConfig>(key: K, value: CaptionConfig[K]) => {
    setConfig((current) => ({ ...current, [key]: value }));
  };

  const generateAss = async () => {
    if (!project) return;
    setBusy(true);
    setError('');
    try {
      const result = await api.generateCaptions(project.id, config);
      setNotice(`Generated ${result.eventCount} timed caption lines`);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Caption generation failed');
    } finally { setBusy(false); }
  };

  const renderCaptions = async () => {
    if (!project) return;
    setRendering(true);
    setError('');
    try {
      const result = await api.renderCaptionedVideo(project.id, config);
      setNotice(`Captioned video rendered with ${result.encoderUsed}: ${result.outputPath}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Caption render failed');
    } finally { setRendering(false); }
  };

  const setPreset = (preset: CaptionPreset) => setConfig({ ...PRESETS[preset], profanityMask: config.profanityMask });
  const patchSlider = <K extends 'fontSize' | 'outlineWidth' | 'shadowDepth' | 'marginV' | 'maxWordsPerLine',>(key: K, min: number, max: number) =>
    (event: React.ChangeEvent<HTMLInputElement>) => updateConfig(key, Math.max(min, Math.min(max, Number(event.target.value))) as CaptionConfig[K]);

  const togglePlayback = () => {
    if (!videoRef.current) return;
    if (videoRef.current.paused) void videoRef.current.play(); else videoRef.current.pause();
  };
  const handleTimeUpdate = () => {
    if (!videoRef.current) return;
    playTimeRef.current = videoRef.current.currentTime;
    setVideoTime(videoRef.current.currentTime);
  };

  return (
    <div className="mx-auto max-w-[1500px] space-y-6 pb-12 text-slate-100">
      <header className="flex flex-wrap items-end justify-between gap-4 border-b border-slate-800 pb-5">
        <div>
          <p className="text-xs font-mono text-cyan-400">PHASE 5 / CAPTIONS</p>
          <h1 className="mt-1 text-2xl font-semibold tracking-tight">Caption Studio</h1>
          <p className="mt-1 text-sm text-slate-400">Style, preview, and correct word-level captions without rerunning transcription.</p>
        </div>
        <label className="min-w-64 text-xs text-slate-400">Project
          <select value={project?.id ?? ''} onChange={(event) => event.target.value && void selectProject(event.target.value)} className="mt-1 block w-full rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-white">
            <option value="">Choose a transcribed project</option>
            {projects.filter((item) => item.hasTranscript).map((item) => <option value={item.id} key={item.id}>{item.title}</option>)}
          </select>
        </label>
      </header>

      {error && <div role="alert" className="rounded-lg border border-rose-900 bg-rose-950/50 px-4 py-3 text-sm text-rose-200">{error}</div>}
      {notice && <div role="status" className="rounded-lg border border-emerald-900 bg-emerald-950/40 px-4 py-3 text-sm text-emerald-200">{notice}</div>}

      <div className="grid gap-6 xl:grid-cols-[minmax(300px,0.8fr)_minmax(480px,1.2fr)]">
        <section className="space-y-3">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-semibold">Live preview</h2>
            <span className="font-mono text-xs text-slate-400">{videoTime.toFixed(2)}s</span>
          </div>
          <div className="mx-auto max-w-[360px]">
            <CaptionPreview videoRef={videoRef} projectId={videoReady ? project?.id ?? null : null} time={videoTime} segments={segments} config={debouncedConfig} playTimeRef={playTimeRef} />
          </div>
          {project && <video ref={videoRef} src={api.getVideoStreamUrl(project.id)} className="sr-only" preload="metadata" onLoadedData={() => setVideoReady(true)} onTimeUpdate={handleTimeUpdate} />}
          <div className="flex items-center gap-3">
            <button type="button" onClick={togglePlayback} disabled={!project} className="inline-flex items-center gap-2 rounded-md bg-cyan-600 px-3 py-2 text-xs font-semibold text-white disabled:opacity-50"><Play className="h-4 w-4" /> Play</button>
            <input type="range" min={0} max={project?.durationSec ?? 0} step={0.05} value={Math.min(videoTime, project?.durationSec ?? 0)} onChange={(event) => { const value = Number(event.target.value); playTimeRef.current = value; setVideoTime(value); if (videoRef.current) videoRef.current.currentTime = value; }} className="min-w-0 flex-1 accent-cyan-500" aria-label="Preview position" />
          </div>
          <div className="flex flex-wrap gap-2">
            <button type="button" onClick={() => void generateAss()} disabled={!project || busy} className="inline-flex items-center gap-2 rounded-md bg-violet-600 px-3 py-2 text-xs font-semibold disabled:opacity-50">{busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />} Generate .ass</button>
            {project && <a href={api.getCaptionsUrl(project.id)} download className="inline-flex items-center gap-2 rounded-md border border-slate-700 px-3 py-2 text-xs text-slate-200"><Download className="h-4 w-4" /> Download .ass</a>}
            <button type="button" onClick={() => void renderCaptions()} disabled={!project || rendering} className="inline-flex items-center gap-2 rounded-md border border-cyan-800 px-3 py-2 text-xs text-cyan-200 disabled:opacity-50">{rendering ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />} Burn captions into MP4</button>
          </div>
        </section>

        <section className="space-y-4 rounded-xl border border-slate-800 bg-slate-900/50 p-4 sm:p-5">
          <div className="flex items-start justify-between gap-3">
            <div><h2 className="text-sm font-semibold">Caption style</h2><p className="mt-1 text-xs text-slate-400">Controls update the preview after a short pause.</p></div>
            <button type="button" onClick={() => setConfig(PRESETS[config.preset])} className="inline-flex items-center gap-1 text-xs text-slate-400 hover:text-white"><RefreshCw className="h-3.5 w-3.5" /> Reset preset</button>
          </div>
          <label className="block text-xs text-slate-400">Preset
            <select value={config.preset} onChange={(event) => setPreset(event.target.value as CaptionPreset)} className="mt-1 block w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-white">
              {(Object.keys(PRESETS) as CaptionPreset[]).map((key) => <option value={key} key={key}>{PRESET_LABELS[key]}</option>)}
            </select>
          </label>
          <div className="grid grid-cols-2 gap-3">
            <label className="text-xs text-slate-400">Font family
              <select value={config.fontName} onChange={(event) => updateConfig('fontName', event.target.value)} className="mt-1 block w-full rounded-md border border-slate-700 bg-slate-950 px-2 py-2 text-sm text-white">{fonts.map((font) => <option key={font}>{font}</option>)}</select>
            </label>
            <label className="text-xs text-slate-400">Font size <span className="text-cyan-300">{config.fontSize}px</span>
              <input type="range" min={24} max={120} value={config.fontSize} onChange={patchSlider('fontSize', 24, 120)} className="mt-3 block w-full accent-cyan-500" />
            </label>
            <label className="flex items-center gap-2 text-xs text-slate-300">Text color <input type="color" value={config.primaryColor} onChange={(event) => updateConfig('primaryColor', event.target.value)} className="h-8 w-10 rounded border border-slate-700 bg-transparent" /></label>
            <label className="flex items-center gap-2 text-xs text-slate-300">Active word <input type="color" value={config.highlightColor} onChange={(event) => updateConfig('highlightColor', event.target.value)} className="h-8 w-10 rounded border border-slate-700 bg-transparent" /></label>
            <label className="flex items-center gap-2 text-xs text-slate-300">Outline color <input type="color" value={config.outlineColor} onChange={(event) => updateConfig('outlineColor', event.target.value)} className="h-8 w-10 rounded border border-slate-700 bg-transparent" /></label>
            <label className="text-xs text-slate-400">Outline width <span className="text-cyan-300">{config.outlineWidth}</span>
              <input type="range" min={0} max={12} step={0.5} value={config.outlineWidth} onChange={patchSlider('outlineWidth', 0, 12)} className="mt-3 block w-full accent-cyan-500" />
            </label>
            <label className="text-xs text-slate-400">Shadow depth <span className="text-cyan-300">{config.shadowDepth}</span>
              <input type="range" min={0} max={10} step={0.5} value={config.shadowDepth} onChange={patchSlider('shadowDepth', 0, 10)} className="mt-3 block w-full accent-cyan-500" />
            </label>
            <label className="text-xs text-slate-400">Vertical position · MarginV <span className="text-cyan-300">{config.marginV}</span>
              <input type="range" min={30} max={600} step={5} value={config.marginV} onChange={patchSlider('marginV', 30, 600)} className="mt-3 block w-full accent-cyan-500" />
            </label>
            <label className="text-xs text-slate-400">Words per line · {config.maxWordsPerLine}
              <input type="range" min={1} max={6} value={config.maxWordsPerLine} onChange={patchSlider('maxWordsPerLine', 1, 6)} className="mt-3 block w-full accent-cyan-500" />
            </label>
            <label className="text-xs text-slate-400">Animation
              <select value={config.animation} onChange={(event) => updateConfig('animation', event.target.value as CaptionAnimation)} className="mt-1 block w-full rounded-md border border-slate-700 bg-slate-950 px-2 py-2 text-sm text-white">
                <option value="none">None</option><option value="pop">Pop</option><option value="highlight">Highlight</option><option value="bounce">Bounce</option>
              </select>
            </label>
            <div className="flex flex-col justify-center gap-3 text-xs text-slate-300">
              <label className="flex items-center gap-2"><input type="checkbox" checked={config.allCaps} onChange={(event) => updateConfig('allCaps', event.target.checked)} className="accent-cyan-500" /> ALL CAPS</label>
              <label className="flex items-center gap-2"><input type="checkbox" checked={config.profanityMask} onChange={(event) => updateConfig('profanityMask', event.target.checked)} className="accent-cyan-500" /> Mask profanity</label>
            </div>
          </div>
        </section>
      </div>

      <CaptionTranscriptEditor segments={segments} onCommit={commitWord} saving={saving} saved={saved} />
    </div>
  );
};

export default CaptionStudio;
