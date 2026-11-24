import React, {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react';
import {
  BookmarkPlus,
  CheckCircle2,
  Cpu,
  Download,
  Eye,
  EyeOff,
  Layers,
  Loader2,
  Maximize2,
  Minimize2,
  ScanSearch,
  Trash2,
  Video,
  Wand2,
  X,
} from 'lucide-react';
import { api } from '../api/client';
import { useWorkspace } from '../context/WorkspaceContext';
import {
  AspectRatio,
  AutoDetectResult,
  FramingConfig,
  FramingMode,
  LayoutTemplate,
  PaneFitMode,
  ProjectRead,
  ProjectSummary,
  RegionBox,
  RenderResponse,
  SavedProfile,
} from '../types/project';

// ─── Output canvas dimensions ────────────────────────────────────────────────
const ASPECT_DIMS: Record<AspectRatio, [number, number]> = {
  '9:16': [1080, 1920],
  '1:1': [1080, 1080],
  '16:9': [1920, 1080],
};

export interface ModeTemplateOption {
  key: LayoutTemplate;
  label: string;
  desc: string;
}

export interface ModeMeta {
  key: FramingMode;
  icon: string;
  label: string;
  r1Name: string;
  r2Name: string;
  r1Icon: string;
  r2Icon: string;
  defaultSplit: number;
  defaultTemplate: LayoutTemplate;
  templates: ModeTemplateOption[];
  hideR2ByDefault?: boolean;
}

export const MODE_METAS: Record<FramingMode, ModeMeta> = {
  podcast: {
    key: 'podcast',
    icon: '🎙️',
    label: 'Podcast',
    r1Name: 'Person 1',
    r2Name: 'Person 2',
    r1Icon: '🎙️',
    r2Icon: '🎙️',
    defaultSplit: 50,
    defaultTemplate: 'split_vertical',
    templates: [
      { key: 'split_vertical', label: '50/50 Stacked Split', desc: 'Person 1 top, Person 2 bottom' },
      { key: 'podcast_active_speaker', label: 'Active Speaker 9:16', desc: 'Fullscreen auto-cutting between hosts' },
      { key: 'side_by_side_blur', label: 'Side-by-Side Dual', desc: 'Dual portrait panes over blurred fill' },
      { key: 'wide_plus_dual', label: 'Wide + Dual Split', desc: 'Overview wide top shot + hosts side-by-side bottom' },
      { key: 'fullscreen_crop', label: 'Single Speaker Portrait', desc: 'Focused 9:16 portrait crop of main speaker' },
    ],
  },
  gaming: {
    key: 'gaming',
    icon: '🎮',
    label: 'Gaming',
    r1Name: 'Facecam',
    r2Name: 'Gameplay',
    r1Icon: '📷',
    r2Icon: '🎮',
    defaultSplit: 35,
    defaultTemplate: 'split_vertical',
    templates: [
      { key: 'split_vertical', label: 'Facecam Top / Game Bottom', desc: 'Standard streamer stacked vertical split' },
      { key: 'split_inverted', label: 'Game Top / Facecam Bottom', desc: 'Gameplay on top, facecam on bottom' },
      { key: 'pip', label: 'Picture-in-Picture', desc: 'Fullscreen gameplay with corner webcam' },
      { key: 'blurred_fill', label: 'Blurred Fill', desc: 'Centered gameplay over blurred pillarbox' },
      { key: 'fullscreen_crop', label: 'Fullscreen Crop', desc: 'Fill entire frame from gameplay region' },
    ],
  },
  talking_head: {
    key: 'talking_head',
    icon: '🗣️',
    label: 'Talking Head',
    r1Name: 'Speaker',
    r2Name: 'Region 2 (Dual Layout)',
    r1Icon: '🗣️',
    r2Icon: '👥',
    defaultSplit: 50,
    defaultTemplate: 'fullscreen_crop',
    hideR2ByDefault: true,
    templates: [
      { key: 'fullscreen_crop', label: '9:16 Upper-Body Portrait', desc: 'Centered upper-body portrait framing' },
      { key: 'punch_in_zoom', label: 'Punch-In Zoom Cuts', desc: 'Subtle rhythmic 100%→110% zoom cuts every 6s' },
      { key: 'blurred_fill', label: 'Blurred Fill', desc: 'Portrait crop over dynamic blurred background' },
    ],
  },
  screen_presenter: {
    key: 'screen_presenter',
    icon: '🖥️',
    label: 'Screen Presenter',
    r1Name: 'Presenter',
    r2Name: 'Screen / Slides',
    r1Icon: '🧑‍🏫',
    r2Icon: '🖥️',
    defaultSplit: 60,
    defaultTemplate: 'split_vertical',
    templates: [
      { key: 'split_vertical', label: 'Screen Top / Presenter Bottom', desc: 'Slides on top (60%), presenter webcam bottom' },
      { key: 'split_inverted', label: 'Presenter Top / Screen Bottom', desc: 'Presenter webcam top, slides on bottom' },
      { key: 'pip', label: 'Screen + Presenter PiP', desc: 'Fullscreen slides with presenter corner PiP' },
      { key: 'blurred_fill', label: 'Blurred Fill', desc: 'Pillarboxed presentation over blurred backdrop' },
    ],
  },
  reaction: {
    key: 'reaction',
    icon: '😂',
    label: 'Reaction',
    r1Name: 'Reactor',
    r2Name: 'Original Video',
    r1Icon: '😂',
    r2Icon: '🎬',
    defaultSplit: 40,
    defaultTemplate: 'split_vertical',
    templates: [
      { key: 'split_vertical', label: 'Reactor Top / Video Bottom', desc: 'Reactor webcam top (40%), original video bottom' },
      { key: 'split_inverted', label: 'Video Top / Reactor Bottom', desc: 'Original video top (60%), reactor on bottom' },
      { key: 'pip', label: 'Video + Reactor PiP', desc: 'Original video full frame with reactor PiP overlay' },
      { key: 'side_by_side_blur', label: 'Side-by-Side Dual', desc: 'Reactor left and video right side-by-side' },
    ],
  },
};

// Safe-zone overlays (normalized fractions of output canvas)
const SAFE_ZONES: Record<string, { label: string; zones: Array<{ x: number; y: number; w: number; h: number; color: string; label: string }> }> = {
  shorts: {
    label: 'YouTube Shorts',
    zones: [
      { x: 0.0, y: 0.75, w: 1.0, h: 0.25, color: 'rgba(255,80,80,0.18)', label: 'Shorts UI' },
      { x: 0.75, y: 0.0, w: 0.25, h: 1.0, color: 'rgba(255,160,0,0.12)', label: 'Actions' },
    ],
  },
  reels: {
    label: 'Instagram Reels',
    zones: [
      { x: 0.0, y: 0.78, w: 1.0, h: 0.22, color: 'rgba(255,80,180,0.18)', label: 'Reels UI' },
      { x: 0.0, y: 0.0, w: 1.0, h: 0.08, color: 'rgba(255,80,180,0.12)', label: 'Top bar' },
    ],
  },
  tiktok: {
    label: 'TikTok',
    zones: [
      { x: 0.0, y: 0.80, w: 1.0, h: 0.20, color: 'rgba(0,220,220,0.18)', label: 'TikTok UI' },
      { x: 0.75, y: 0.0, w: 0.25, h: 1.0, color: 'rgba(0,220,220,0.12)', label: 'Actions' },
    ],
  },
};

type SafeZoneKey = keyof typeof SAFE_ZONES | null;

type DragAction = 'move' | 'resize-tl' | 'resize-tr' | 'resize-bl' | 'resize-br';

interface DragState {
  boxKey: 'facecam' | 'gameplay' | null;
  action: DragAction | null;
  startMouseX: number;
  startMouseY: number;
  startBox: RegionBox;
}

function emptyBox(): RegionBox {
  return { x: 0.0, y: 0.0, w: 0.5, h: 0.5 };
}

function clampBox(box: RegionBox): RegionBox {
  const x = Math.max(0, Math.min(0.98, box.x));
  const y = Math.max(0, Math.min(0.98, box.y));
  const w = Math.max(0.02, Math.min(1.0 - x, box.w));
  const h = Math.max(0.02, Math.min(1.0 - y, box.h));
  return { x, y, w, h };
}

// Convert normalized box to canvas pixel coords
function boxToPx(box: RegionBox, canvasW: number, canvasH: number) {
  return {
    x: box.x * canvasW,
    y: box.y * canvasH,
    w: box.w * canvasW,
    h: box.h * canvasH,
  };
}

export const LayoutStudio: React.FC = () => {
  const { activeProjectId, setActiveProjectId } = useWorkspace();

  // ── Project selector ──────────────────────────────────────────────────────
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [activeProject, setActiveProject] = useState<ProjectRead | null>(null);
  const [loadingProject, setLoadingProject] = useState(false);

  // ── Frame preview ─────────────────────────────────────────────────────────
  const [frameSec, setFrameSec] = useState(5.0);
  const [frameUrl, setFrameUrl] = useState<string | null>(null);
  const [imgLoaded, setImgLoaded] = useState(false);
  const imgRef = useRef<HTMLImageElement | null>(null);

  // ── Framing config state ──────────────────────────────────────────────────
  const [framingMode, setFramingMode] = useState<FramingMode>('gaming');
  const [aspectRatio, setAspectRatio] = useState<AspectRatio>('9:16');
  const [layoutTemplate, setLayoutTemplate] = useState<LayoutTemplate>('split_vertical');
  const [splitRatio, setSplitRatio] = useState(35);
  const [facecamBox, setFacecamBox] = useState<RegionBox | null>({
    x: 0.0, y: 0.0, w: 0.3, h: 0.25,
  });
  const [gameplayBox, setGameplayBox] = useState<RegionBox | null>({
    x: 0.0, y: 0.0, w: 1.0, h: 1.0,
  });
  const [faceDetected, setFaceDetected] = useState<boolean | null>(null);
  const [dynamicFacecamTracking, setDynamicFacecamTracking] = useState<boolean>(false);
  const [paneFitMode, setPaneFitMode] = useState<PaneFitMode>('fill');
  const [tightness, setTightness] = useState<'close' | 'medium' | 'wide'>('medium');
  const [punchInZoomed, setPunchInZoomed] = useState<boolean>(true);
  const [activeSpeakerHost, setActiveSpeakerHost] = useState<'p1' | 'p2'>('p1');
  const currentMeta = useMemo(() => MODE_METAS[framingMode] || MODE_METAS.gaming, [framingMode]);

  // ── Safe-zone overlay ─────────────────────────────────────────────────────
  const [safeZoneKey, setSafeZoneKey] = useState<SafeZoneKey>(null);

  // ── Watermark ─────────────────────────────────────────────────────────────
  const [watermarkOpacity, setWatermarkOpacity] = useState(0.8);
  const [watermarkScale, setWatermarkScale] = useState(0.1);
  const [watermarkPath, setWatermarkPath] = useState<string | null>(null);
  const [watermarkPreview, setWatermarkPreview] = useState<string | null>(null);
  const [watermarkCorner, setWatermarkCorner] = useState<'top_left' | 'top_right' | 'bottom_left' | 'bottom_right'>('bottom_right');

  // ── Fullscreen modal state ────────────────────────────────────────────────
  const [isFullscreenOpen, setIsFullscreenOpen] = useState(false);

  useEffect(() => () => {
    if (watermarkPreview) URL.revokeObjectURL(watermarkPreview);
  }, [watermarkPreview]);

  // ── Auto-detect ───────────────────────────────────────────────────────────
  const [isDetecting, setIsDetecting] = useState(false);
  const [detectResult, setDetectResult] = useState<AutoDetectResult | null>(null);

  // ── Profiles ──────────────────────────────────────────────────────────────
  const [profiles, setProfiles] = useState<SavedProfile[]>([]);
  const [profileName, setProfileName] = useState('');
  const [savingProfile, setSavingProfile] = useState(false);
  const [profileSaved, setProfileSaved] = useState(false);

  // ── Render ────────────────────────────────────────────────────────────────
  const [renderResult, setRenderResult] = useState<RenderResponse | null>(null);
  const [isRendering, setIsRendering] = useState(false);
  const [renderError, setRenderError] = useState<string | null>(null);
  const [renderStartSec, setRenderStartSec] = useState(0.0);
  const [renderEndSec, setRenderEndSec] = useState(60.0);

  // ── Canvas DnD ────────────────────────────────────────────────────────────
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const fullscreenCanvasRef = useRef<HTMLCanvasElement>(null);
  const outputCanvasRef = useRef<HTMLCanvasElement>(null);

  const dragRef = useRef<DragState>({
    boxKey: null,
    action: null,
    startMouseX: 0,
    startMouseY: 0,
    startBox: emptyBox(),
  });

  const selectProject = useCallback(async (id: string) => {
    setLoadingProject(true);
    try {
      setActiveProjectId(id);
      const [p, wsConfig] = await Promise.all([
        api.getProject(id),
        api.getWorkspaceConfig(id).catch(() => ({ layoutConfig: {}, captionConfig: {} })),
      ]);
      setActiveProject(p);
      setFrameSec(5.0);
      setRenderEndSec(Math.min(60.0, p.durationSec ?? 60.0));
      setFrameUrl(api.getFrameUrl(id, 5.0) + `&_=${Date.now()}`);
      setImgLoaded(false);

      if (wsConfig && wsConfig.layoutConfig && Object.keys(wsConfig.layoutConfig).length > 0) {
        const lc = wsConfig.layoutConfig as Record<string, unknown>;
        if (lc.framingMode) setFramingMode(lc.framingMode as FramingMode);
        if (lc.aspectRatio) setAspectRatio(lc.aspectRatio as AspectRatio);
        if (lc.layoutTemplate) setLayoutTemplate(lc.layoutTemplate as LayoutTemplate);
        if (typeof lc.splitRatio === 'number') setSplitRatio(lc.splitRatio);
        if (lc.facecamBox) setFacecamBox(lc.facecamBox as RegionBox);
        if (lc.gameplayBox) setGameplayBox(lc.gameplayBox as RegionBox);
        if (typeof lc.watermarkOpacity === 'number') setWatermarkOpacity(lc.watermarkOpacity);
        if (typeof lc.watermarkScale === 'number') setWatermarkScale(lc.watermarkScale);
        if (lc.watermarkCorner) setWatermarkCorner(lc.watermarkCorner as any);
        if (typeof lc.watermarkPath === 'string' || lc.watermarkPath === null) setWatermarkPath(lc.watermarkPath as string | null);
        if (typeof lc.dynamicFacecamTracking === 'boolean') setDynamicFacecamTracking(lc.dynamicFacecamTracking);
        else if (typeof lc.dynamic_facecam_tracking === 'boolean') setDynamicFacecamTracking(lc.dynamic_facecam_tracking);
        if (lc.paneFitMode) setPaneFitMode(lc.paneFitMode as PaneFitMode);
        else if (lc.pane_fit_mode) setPaneFitMode(lc.pane_fit_mode as PaneFitMode);
      }
    } finally {
      setLoadingProject(false);
    }
  }, [setActiveProjectId]);

  // Load projects list
  useEffect(() => {
    api.listProjects().then((list) => {
      setProjects(list);
      const preferredId = activeProjectId || list[0]?.id;
      if (preferredId) {
        selectProject(preferredId);
      }
    }).catch(console.error);
    api.listProfiles().then(setProfiles).catch(console.error);
  }, []);

  // Debounced autosave layoutConfig to backend
  const hasLoadedRef = useRef(false);
  useEffect(() => {
    if (!activeProject?.id) return;
    if (!hasLoadedRef.current) {
      hasLoadedRef.current = true;
      return;
    }
    const timer = window.setTimeout(() => {
      api.patchWorkspaceConfig(activeProject.id, {
        layoutConfig: {
          framingMode,
          aspectRatio,
          layoutTemplate,
          splitRatio,
          paneFitMode,
          facecamBox,
          gameplayBox,
          watermarkOpacity,
          watermarkScale,
          watermarkCorner,
          watermarkPath,
          dynamicFacecamTracking,
        },
      }).catch(console.error);
    }, 800);
    return () => window.clearTimeout(timer);
  }, [
    activeProject?.id,
    framingMode,
    aspectRatio,
    layoutTemplate,
    splitRatio,
    paneFitMode,
    facecamBox,
    gameplayBox,
    watermarkOpacity,
    watermarkScale,
    watermarkCorner,
    watermarkPath,
    dynamicFacecamTracking,
  ]);

  // Seek to new frame time
  const seekFrame = useCallback((t: number) => {
    if (!activeProject) return;
    const clamped = Math.max(0, Math.min(t, (activeProject.durationSec ?? 300) - 0.5));
    setFrameSec(clamped);
    setFrameUrl(api.getFrameUrl(activeProject.id, clamped) + `&_=${Date.now()}`);
    setImgLoaded(false);
  }, [activeProject]);

  // Close fullscreen modal on Escape key
  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && isFullscreenOpen) {
        setIsFullscreenOpen(false);
      }
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [isFullscreenOpen]);

  // ── Canvas drawing & dimension math ──────────────────────────────────────
  const [outW, outH] = ASPECT_DIMS[aspectRatio];

  // Natural aspect ratio of the source video (width / height)
  const naturalAspect = (imgRef.current && imgRef.current.naturalWidth && imgRef.current.naturalHeight)
    ? (imgRef.current.naturalWidth / imgRef.current.naturalHeight)
    : (activeProject?.width && activeProject?.height)
    ? (activeProject.width / activeProject.height)
    : (16 / 9);

  // Wide 16:9 canvas dimensions (860px wide on desktop for pixel accuracy)
  const REGIONS_CANVAS_W = 860;
  const regionsCanvasH = Math.max(180, Math.round(REGIONS_CANVAS_W / naturalAspect));

  // Fullscreen modal canvas dimensions
  const FULLSCREEN_CANVAS_W = 1280;
  const fullscreenCanvasH = Math.max(240, Math.round(FULLSCREEN_CANVAS_W / naturalAspect));

  // Output preview canvas: strictly preserve selected target aspect ratio
  const targetAspect = outW / outH;
  const OUTPUT_MAX_H = Math.max(300, regionsCanvasH);
  let outPreviewH = OUTPUT_MAX_H;
  let outPreviewW = Math.round(OUTPUT_MAX_H * targetAspect);
  if (outPreviewW > 360) {
    outPreviewW = 360;
    outPreviewH = Math.round(outPreviewW / targetAspect);
  }

  // Draw region boxes with prominent 4-corner handles
  const renderBoxesOnCanvas = useCallback((
    canvas: HTMLCanvasElement,
    _isLarge = false,
  ) => {
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    ctx.clearRect(0, 0, canvas.width, canvas.height);

    if (imgRef.current && imgLoaded) {
      ctx.drawImage(imgRef.current, 0, 0, canvas.width, canvas.height);
    } else {
      ctx.fillStyle = '#090d16';
      ctx.fillRect(0, 0, canvas.width, canvas.height);
      ctx.fillStyle = '#475569';
      ctx.font = '14px monospace';
      ctx.textAlign = 'center';
      ctx.fillText(activeProject ? 'Loading video frame…' : 'Select a project to begin', canvas.width / 2, canvas.height / 2);
    }

    const W = canvas.width;
    const H = canvas.height;

    const drawBox = (box: RegionBox, color: string, label: string) => {
      const { x, y, w, h } = boxToPx(box, W, H);
      ctx.strokeStyle = color;
      ctx.lineWidth = 2.5;
      ctx.setLineDash([]);
      ctx.strokeRect(x, y, w, h);
      ctx.fillStyle = color.replace('1)', '0.14)');
      ctx.fillRect(x, y, w, h);

      // Label pill with dark contrast background
      ctx.fillStyle = 'rgba(0, 0, 0, 0.75)';
      ctx.fillRect(x + 2, y + 2, Math.min(120, w - 4), 18);
      ctx.fillStyle = color;
      ctx.font = 'bold 11px monospace';
      ctx.textAlign = 'left';
      ctx.fillText(label, x + 6, y + 15);

      // Visible corner drag handles (all 4 corners)
      const HANDLE_SIZE = 10;
      const half = HANDLE_SIZE / 2;
      const corners = [
        { cx: x, cy: y },
        { cx: x + w, cy: y },
        { cx: x, cy: y + h },
        { cx: x + w, cy: y + h },
      ];
      corners.forEach(({ cx, cy }) => {
        ctx.fillStyle = '#ffffff';
        ctx.fillRect(cx - half, cy - half, HANDLE_SIZE, HANDLE_SIZE);
        ctx.strokeStyle = color;
        ctx.lineWidth = 2;
        ctx.strokeRect(cx - half, cy - half, HANDLE_SIZE, HANDLE_SIZE);
      });
    };

    const meta = MODE_METAS[framingMode] || MODE_METAS.gaming;
    const isDual = layoutTemplate === 'split_vertical' || layoutTemplate === 'split_inverted' || layoutTemplate === 'side_by_side_blur' || layoutTemplate === 'wide_plus_dual';
    const showR2 = !meta.hideR2ByDefault || isDual;

    if (gameplayBox && showR2) drawBox(gameplayBox, 'rgba(0,210,255,1)', meta.r2Name);
    if (facecamBox) drawBox(facecamBox, 'rgba(255,100,220,1)', meta.r1Name);
  }, [imgLoaded, facecamBox, gameplayBox, activeProject, framingMode, layoutTemplate]);

  const drawCanvas = useCallback(() => {
    if (canvasRef.current) {
      renderBoxesOnCanvas(canvasRef.current, false);
    }
  }, [renderBoxesOnCanvas]);

  const drawFullscreenCanvas = useCallback(() => {
    if (fullscreenCanvasRef.current && isFullscreenOpen) {
      renderBoxesOnCanvas(fullscreenCanvasRef.current, true);
    }
  }, [renderBoxesOnCanvas, isFullscreenOpen]);

  useEffect(() => {
    drawCanvas();
  }, [drawCanvas]);

  useEffect(() => {
    drawFullscreenCanvas();
  }, [drawFullscreenCanvas]);

  const drawOutputPreview = useCallback(() => {
    const canvas = outputCanvasRef.current;
    const image = imgRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    const W = canvas.width;
    const H = canvas.height;
    ctx.fillStyle = '#070b12';
    ctx.fillRect(0, 0, W, H);
    if (!image || !imgLoaded || !image.naturalWidth) {
      ctx.fillStyle = '#64748b';
      ctx.font = '12px monospace';
      ctx.textAlign = 'center';
      ctx.fillText('Output preview', W / 2, H / 2);
      return;
    }

    const drawRegion = (box: RegionBox | null, dx: number, dy: number, dw: number, dh: number) => {
      if (!box) return;
      const sx = box.x * image.naturalWidth;
      const sy = box.y * image.naturalHeight;
      const sw = Math.max(1, box.w * image.naturalWidth);
      const sh = Math.max(1, box.h * image.naturalHeight);

      if (paneFitMode === 'fill') {
        // object-cover: scale to cover dw:dh without black bars
        const scale = Math.max(dw / sw, dh / sh);
        const rw = sw * scale;
        const rh = sh * scale;
        // Head-Safe Vertical Fill Bias: whenever rh > dh (vertical crop), bias crop toward upper area (y = (dh - rh) * 0.2)
        const xOffset = (dw - rw) / 2;
        const yOffset = rh > dh ? (dh - rh) * 0.2 : (dh - rh) / 2;
        ctx.save();
        ctx.beginPath();
        ctx.rect(dx, dy, dw, dh);
        ctx.clip();
        ctx.drawImage(image, sx, sy, sw, sh, dx + xOffset, dy + yOffset, rw, rh);
        ctx.restore();
      } else {
        // object-contain: scale to fit inside dw:dh, padded with black
        const scale = Math.min(dw / sw, dh / sh);
        const rw = sw * scale;
        const rh = sh * scale;
        ctx.fillStyle = '#000000';
        ctx.fillRect(dx, dy, dw, dh);
        ctx.drawImage(image, sx, sy, sw, sh, dx + (dw - rw) / 2, dy + (dh - rh) / 2, rw, rh);
      }
    };

    if (layoutTemplate === 'split_vertical') {
      const topPaneH = Math.round(H * (splitRatio / 100));
      const botPaneH = H - topPaneH;
      const topBox = framingMode === 'screen_presenter'
        ? (gameplayBox ?? { x: 0, y: 0, w: 1, h: 0.65 })
        : (facecamBox ?? { x: 0, y: 0, w: 0.3, h: 0.25 });
      const botBox = framingMode === 'screen_presenter'
        ? (facecamBox ?? { x: 0, y: 0, w: 0.3, h: 0.25 })
        : (gameplayBox ?? { x: 0, y: 0, w: 1, h: 1.0 });

      drawRegion(topBox, 0, 0, W, topPaneH);
      drawRegion(botBox, 0, topPaneH, W, botPaneH);

      // Split ratio divider line on Output canvas
      ctx.setLineDash([5, 4]);
      ctx.strokeStyle = 'rgba(255,255,255,0.7)';
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      ctx.moveTo(0, topPaneH);
      ctx.lineTo(W, topPaneH);
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.fillStyle = 'rgba(0,0,0,0.65)';
      ctx.fillRect(4, topPaneH - 14, 82, 13);
      ctx.fillStyle = 'rgba(255,255,255,0.95)';
      ctx.font = '10px monospace';
      ctx.textAlign = 'left';
      ctx.fillText(`${splitRatio}% / ${100 - splitRatio}%`, 8, topPaneH - 4);
    } else if (layoutTemplate === 'split_inverted') {
      const topPaneH = Math.round(H * (splitRatio / 100));
      const botPaneH = H - topPaneH;
      const topBox = framingMode === 'screen_presenter'
        ? (facecamBox ?? { x: 0, y: 0, w: 0.3, h: 0.25 })
        : (gameplayBox ?? { x: 0, y: 0, w: 1, h: 1.0 });
      const botBox = framingMode === 'screen_presenter'
        ? (gameplayBox ?? { x: 0, y: 0, w: 1, h: 0.65 })
        : (facecamBox ?? { x: 0, y: 0, w: 0.3, h: 0.25 });

      drawRegion(topBox, 0, 0, W, topPaneH);
      drawRegion(botBox, 0, topPaneH, W, botPaneH);

      ctx.setLineDash([5, 4]);
      ctx.strokeStyle = 'rgba(255,255,255,0.7)';
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      ctx.moveTo(0, topPaneH);
      ctx.lineTo(W, topPaneH);
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.fillStyle = 'rgba(0,0,0,0.65)';
      ctx.fillRect(4, topPaneH - 14, 82, 13);
      ctx.fillStyle = 'rgba(255,255,255,0.95)';
      ctx.font = '10px monospace';
      ctx.textAlign = 'left';
      ctx.fillText(`${splitRatio}% / ${100 - splitRatio}%`, 8, topPaneH - 4);
    } else if (layoutTemplate === 'pip') {
      const mainBox = gameplayBox ?? { x: 0, y: 0, w: 1, h: 1 };
      const pipBox = facecamBox ?? { x: 0, y: 0, w: 0.3, h: 0.25 };
      drawRegion(mainBox, 0, 0, W, H);

      const pipW = Math.round(W * 0.33);
      const boxAspect = (pipBox.w * image.naturalWidth) / Math.max(1, pipBox.h * image.naturalHeight);
      const pipH = Math.round(pipW / (boxAspect || 1.333));
      const pipX = W - pipW - 12;
      const pipY = 12;

      ctx.save();
      ctx.shadowColor = 'rgba(0,0,0,0.6)';
      ctx.shadowBlur = 8;
      ctx.fillStyle = 'rgba(0,0,0,0.5)';
      ctx.beginPath();
      if (typeof ctx.roundRect === 'function') {
        ctx.roundRect(pipX, pipY, pipW, pipH, 8);
      } else {
        ctx.rect(pipX, pipY, pipW, pipH);
      }
      ctx.fill();
      ctx.restore();

      ctx.save();
      ctx.beginPath();
      if (typeof ctx.roundRect === 'function') {
        ctx.roundRect(pipX, pipY, pipW, pipH, 8);
      } else {
        ctx.rect(pipX, pipY, pipW, pipH);
      }
      ctx.clip();
      drawRegion(pipBox, pipX, pipY, pipW, pipH);
      ctx.restore();

      ctx.save();
      ctx.strokeStyle = 'rgba(255,255,255,0.85)';
      ctx.lineWidth = 2;
      ctx.beginPath();
      if (typeof ctx.roundRect === 'function') {
        ctx.roundRect(pipX, pipY, pipW, pipH, 8);
      } else {
        ctx.rect(pipX, pipY, pipW, pipH);
      }
      ctx.stroke();
      ctx.restore();
    } else if (layoutTemplate === 'blurred_fill') {
      // Full-canvas blurred source video background (filter: blur(16px))
      ctx.save();
      ctx.filter = 'blur(16px)';
      const bgScale = Math.max(W / image.naturalWidth, H / image.naturalHeight);
      const bgW = image.naturalWidth * bgScale;
      const bgH = image.naturalHeight * bgScale;
      ctx.drawImage(image, (W - bgW) / 2, (H - bgH) / 2, bgW, bgH);
      ctx.restore();

      // Sharp centered foreground (in Gaming/Screen/Reaction use gameplay_box / full 16:9 frame; in Talking Head/Podcast use facecam_box / full frame)
      const fgBox = (framingMode === 'talking_head' || framingMode === 'podcast')
        ? (facecamBox ?? { x: 0, y: 0, w: 1, h: 1 })
        : (gameplayBox ?? { x: 0, y: 0, w: 1, h: 1 });

      const sx = fgBox.x * image.naturalWidth;
      const sy = fgBox.y * image.naturalHeight;
      const sw = Math.max(1, fgBox.w * image.naturalWidth);
      const sh = Math.max(1, fgBox.h * image.naturalHeight);
      const fgScale = Math.min(W / sw, H / sh);
      const rw = sw * fgScale;
      const rh = sh * fgScale;
      ctx.drawImage(image, sx, sy, sw, sh, (W - rw) / 2, (H - rh) / 2, rw, rh);
    } else if (layoutTemplate === 'fullscreen_crop') {
      // gameplay_box for Gaming/Screen, facecam_box for Talking Head/Podcast/Reaction
      const cropBox = (framingMode === 'talking_head' || framingMode === 'podcast' || framingMode === 'reaction')
        ? (facecamBox ?? gameplayBox ?? { x: 0, y: 0, w: 1, h: 1 })
        : (gameplayBox ?? facecamBox ?? { x: 0, y: 0, w: 1, h: 1 });
      drawRegion(cropBox, 0, 0, W, H);
    } else if (layoutTemplate === 'punch_in_zoom') {
      const spk = facecamBox ?? gameplayBox ?? { x: 0, y: 0, w: 1, h: 1 };
      if (punchInZoomed) {
        // Distinct 112% punch-in framing centered on speaker
        const zw = spk.w / 1.12;
        const zh = spk.h / 1.12;
        const zx = Math.max(0, Math.min(1 - zw, spk.x + (spk.w - zw) / 2));
        const zy = Math.max(0, Math.min(1 - zh, spk.y + (spk.h - zh) / 2));
        drawRegion({ x: zx, y: zy, w: zw, h: zh }, 0, 0, W, H);
      } else {
        drawRegion(spk, 0, 0, W, H);
      }

      ctx.fillStyle = 'rgba(0,0,0,0.75)';
      ctx.fillRect(8, 8, 230, 24);
      ctx.strokeStyle = punchInZoomed ? '#a855f7' : 'rgba(255,255,255,0.3)';
      ctx.lineWidth = 1;
      ctx.strokeRect(8, 8, 230, 24);
      ctx.fillStyle = punchInZoomed ? '#c084fc' : '#94a3b8';
      ctx.font = 'bold 10px monospace';
      ctx.textAlign = 'left';
      ctx.fillText(
        `⚡ Auto Punch-In (${punchInZoomed ? '112% Zoom' : '100% Base'})`,
        14,
        24
      );
    } else if (layoutTemplate === 'podcast_active_speaker') {
      const spk = (activeSpeakerHost === 'p2' && gameplayBox)
        ? gameplayBox
        : (facecamBox ?? { x: 0.1, y: 0.15, w: 0.38, h: 0.65 });
      drawRegion(spk, 0, 0, W, H);

      ctx.fillStyle = 'rgba(0,0,0,0.75)';
      ctx.fillRect(8, 8, 230, 24);
      ctx.strokeStyle = '#38bdf8';
      ctx.lineWidth = 1;
      ctx.strokeRect(8, 8, 230, 24);
      ctx.fillStyle = '#38bdf8';
      ctx.font = 'bold 10px monospace';
      ctx.textAlign = 'left';
      ctx.fillText(
        `🎙️ Active Speaker (${activeSpeakerHost === 'p1' ? 'Person 1' : 'Person 2'})`,
        14,
        24
      );
    } else if (layoutTemplate === 'side_by_side_blur') {
      ctx.save();
      ctx.filter = 'blur(16px)';
      const bgScale = Math.max(W / image.naturalWidth, H / image.naturalHeight);
      const bgW = image.naturalWidth * bgScale;
      const bgH = image.naturalHeight * bgScale;
      ctx.drawImage(image, (W - bgW) / 2, (H - bgH) / 2, bgW, bgH);
      ctx.restore();

      const leftW = Math.round(W / 2);
      const rightW = W - leftW;
      const paneH = Math.min(H, Math.round(leftW * (16 / 9)));
      const paneY = Math.round((H - paneH) / 2);

      const p1 = facecamBox ?? { x: 0, y: 0, w: 0.5, h: 1 };
      const p2 = gameplayBox ?? { x: 0.5, y: 0, w: 0.5, h: 1 };
      drawRegion(p1, 0, paneY, leftW, paneH);
      drawRegion(p2, leftW, paneY, rightW, paneH);

      // Border divider
      ctx.strokeStyle = 'rgba(255,255,255,0.4)';
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(leftW, paneY);
      ctx.lineTo(leftW, paneY + paneH);
      ctx.stroke();
    } else if (layoutTemplate === 'wide_plus_dual') {
      // 9:16 (1080x1920) geometry: Top ~36% (690px), Bottom ~64% (1230px)
      const topH = Math.round(H * (690 / 1920));
      const botH = H - topH;
      const leftW = Math.round(W / 2);
      const rightW = W - leftW;

      // Top pane: full uncropped 16:9 wide source frame (scaled cleanly to W wide, filled/clean-cropped symmetrically)
      const sw = image.naturalWidth;
      const sh = image.naturalHeight;
      const topScale = Math.max(W / sw, topH / sh);
      const rw = sw * topScale;
      const rh = sh * topScale;
      ctx.save();
      ctx.beginPath();
      ctx.rect(0, 0, W, topH);
      ctx.clip();
      ctx.drawImage(image, 0, 0, sw, sh, (W - rw) / 2, (topH - rh) / 2, rw, rh);
      ctx.restore();

      // Bottom pane: two equal side-by-side portrait panes (Person 1 left, Person 2 right)
      const p1 = facecamBox ?? { x: 0.0, y: 0.0, w: 0.5, h: 1.0 };
      const p2 = gameplayBox ?? { x: 0.5, y: 0.0, w: 0.5, h: 1.0 };
      drawRegion(p1, 0, topH, leftW, botH);
      drawRegion(p2, leftW, topH, rightW, botH);

      // Dividers
      ctx.strokeStyle = 'rgba(255,255,255,0.5)';
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      ctx.moveTo(0, topH); ctx.lineTo(W, topH);
      ctx.moveTo(leftW, topH); ctx.lineTo(leftW, H);
      ctx.stroke();

      // Top pane label
      ctx.fillStyle = 'rgba(0,0,0,0.6)';
      ctx.fillRect(6, 6, 120, 16);
      ctx.fillStyle = 'rgba(255,255,255,0.9)';
      ctx.font = '9px monospace';
      ctx.textAlign = 'left';
      ctx.fillText('Overview Wide (16:9)', 10, 18);
    } else {
      // Fullscreen crop fallback
      const cropBox = (framingMode === 'talking_head' || framingMode === 'podcast' || framingMode === 'reaction')
        ? (facecamBox ?? gameplayBox ?? { x: 0, y: 0, w: 1, h: 1 })
        : (gameplayBox ?? facecamBox ?? { x: 0, y: 0, w: 1, h: 1 });
      drawRegion(cropBox, 0, 0, W, H);
    }

    // Platform safe-zone overlay on target output
    if (safeZoneKey && SAFE_ZONES[safeZoneKey]) {
      for (const zone of SAFE_ZONES[safeZoneKey].zones) {
        ctx.fillStyle = zone.color;
        ctx.fillRect(zone.x * W, zone.y * H, zone.w * W, zone.h * H);
        ctx.strokeStyle = zone.color.replace('0.18', '0.55').replace('0.12', '0.45');
        ctx.setLineDash([4, 3]);
        ctx.strokeRect(zone.x * W, zone.y * H, zone.w * W, zone.h * H);
        ctx.setLineDash([]);
        ctx.fillStyle = 'rgba(255,255,255,0.85)';
        ctx.font = '9px monospace';
        ctx.textAlign = 'left';
        ctx.fillText(zone.label, zone.x * W + 4, zone.y * H + 11);
      }
    }

    if (watermarkPreview) {
      const logo = new Image();
      logo.onload = () => {
        const logoW = W * watermarkScale;
        const logoH = (logoW * logo.height) / logo.width;
        const x = watermarkCorner.endsWith('right') ? W - logoW - 8 : 8;
        const y = watermarkCorner.startsWith('bottom') ? H - logoH - 8 : 8;
        ctx.globalAlpha = watermarkOpacity;
        ctx.drawImage(logo, x, y, logoW, logoH);
        ctx.globalAlpha = 1;
      };
      logo.src = watermarkPreview;
    }
  }, [
    imgLoaded,
    aspectRatio,
    framingMode,
    layoutTemplate,
    paneFitMode,
    facecamBox,
    gameplayBox,
    splitRatio,
    safeZoneKey,
    watermarkPreview,
    watermarkScale,
    watermarkOpacity,
    watermarkCorner,
    punchInZoomed,
    activeSpeakerHost,
  ]);

  useEffect(() => {
    drawOutputPreview();
  }, [drawOutputPreview]);

  // ── Hit-testing for 4 corner handles and box move ─────────────────────────
  const hitTest = useCallback(
    (cx: number, cy: number, W: number, H: number): { boxKey: 'facecam' | 'gameplay'; action: DragAction } | null => {
      const HANDLE_HIT = 14;
      const meta = MODE_METAS[framingMode] || MODE_METAS.gaming;
      const isDual = layoutTemplate === 'split_vertical' || layoutTemplate === 'split_inverted' || layoutTemplate === 'side_by_side_blur' || layoutTemplate === 'wide_plus_dual';
      const showR2 = !meta.hideR2ByDefault || isDual;

      const candidates: Array<['facecam' | 'gameplay', RegionBox | null]> = [
        ['facecam', facecamBox],
      ];
      if (showR2) {
        candidates.push(['gameplay', gameplayBox]);
      }

      for (const [key, box] of candidates) {
        if (!box) continue;
        const { x, y, w, h } = boxToPx(box, W, H);

        // Check 4 corners with hit priority
        if (Math.abs(cx - (x + w)) <= HANDLE_HIT && Math.abs(cy - (y + h)) <= HANDLE_HIT) {
          return { boxKey: key, action: 'resize-br' };
        }
        if (Math.abs(cx - x) <= HANDLE_HIT && Math.abs(cy - (y + h)) <= HANDLE_HIT) {
          return { boxKey: key, action: 'resize-bl' };
        }
        if (Math.abs(cx - (x + w)) <= HANDLE_HIT && Math.abs(cy - y) <= HANDLE_HIT) {
          return { boxKey: key, action: 'resize-tr' };
        }
        if (Math.abs(cx - x) <= HANDLE_HIT && Math.abs(cy - y) <= HANDLE_HIT) {
          return { boxKey: key, action: 'resize-tl' };
        }

        // Inside box: move
        if (cx >= x && cy >= y && cx <= x + w && cy <= y + h) {
          return { boxKey: key, action: 'move' };
        }
      }
      return null;
    },
    [facecamBox, gameplayBox, framingMode, layoutTemplate]
  );

  const handlePointerDown = useCallback((
    e: React.MouseEvent<HTMLCanvasElement>,
    canvas: HTMLCanvasElement | null,
  ) => {
    if (!canvas) return;
    const rect = canvas.getBoundingClientRect();
    const mx = (e.clientX - rect.left) * canvas.width / rect.width;
    const my = (e.clientY - rect.top) * canvas.height / rect.height;
    const hit = hitTest(mx, my, canvas.width, canvas.height);
    if (!hit) return;
    const box = hit.boxKey === 'facecam' ? facecamBox : gameplayBox;
    if (!box) return;
    dragRef.current = {
      boxKey: hit.boxKey,
      action: hit.action,
      startMouseX: mx,
      startMouseY: my,
      startBox: { ...box },
    };
  }, [hitTest, facecamBox, gameplayBox]);

  const handlePointerMove = useCallback((
    e: React.MouseEvent<HTMLCanvasElement>,
    canvas: HTMLCanvasElement | null,
  ) => {
    if (!canvas) return;
    const rect = canvas.getBoundingClientRect();
    const mx = (e.clientX - rect.left) * canvas.width / rect.width;
    const my = (e.clientY - rect.top) * canvas.height / rect.height;

    const { boxKey, action, startMouseX, startMouseY, startBox } = dragRef.current;
    if (!boxKey || !action) {
      // Dynamic cursor update
      const hit = hitTest(mx, my, canvas.width, canvas.height);
      if (!hit) {
        canvas.style.cursor = 'crosshair';
      } else if (hit.action === 'move') {
        canvas.style.cursor = 'move';
      } else if (hit.action === 'resize-tl' || hit.action === 'resize-br') {
        canvas.style.cursor = 'nwse-resize';
      } else if (hit.action === 'resize-tr' || hit.action === 'resize-bl') {
        canvas.style.cursor = 'nesw-resize';
      }
      return;
    }

    const dx = (mx - startMouseX) / canvas.width;
    const dy = (my - startMouseY) / canvas.height;

    let newBox: RegionBox;
    switch (action) {
      case 'move':
        newBox = clampBox({ ...startBox, x: startBox.x + dx, y: startBox.y + dy });
        break;
      case 'resize-br':
        newBox = clampBox({ ...startBox, w: startBox.w + dx, h: startBox.h + dy });
        break;
      case 'resize-bl':
        newBox = clampBox({ ...startBox, x: startBox.x + dx, w: startBox.w - dx, h: startBox.h + dy });
        break;
      case 'resize-tr':
        newBox = clampBox({ ...startBox, y: startBox.y + dy, w: startBox.w + dx, h: startBox.h - dy });
        break;
      case 'resize-tl':
        newBox = clampBox({ ...startBox, x: startBox.x + dx, y: startBox.y + dy, w: startBox.w - dx, h: startBox.h - dy });
        break;
      default:
        newBox = startBox;
    }

    if (boxKey === 'facecam') {
      setFacecamBox(newBox);
      setFaceDetected(true);
    } else {
      setGameplayBox(newBox);
    }
  }, [hitTest]);

  const handlePointerUp = useCallback(() => {
    dragRef.current = { boxKey: null, action: null, startMouseX: 0, startMouseY: 0, startBox: emptyBox() };
  }, []);

  // ── Auto-Detect Regions ───────────────────────────────────────────────────
  const handleAutoDetect = async () => {
    if (!activeProject) return;
    setIsDetecting(true);
    setDetectResult(null);
    try {
      const result = await api.autoDetectRegions(
        activeProject.id,
        frameSec,
        framingMode,
        tightness,
        layoutTemplate,
        aspectRatio,
        splitRatio
      );
      setDetectResult(result);
      if (result.facecamBox) setFacecamBox(result.facecamBox);
      else if (result.faceCount === 0) setFacecamBox(null);
      if (result.gameplayBox) setGameplayBox(result.gameplayBox);
      setFaceDetected(result.faceCount > 0);
      if (result.modeSuggestion) {
        setFramingMode(result.modeSuggestion);
        const meta = MODE_METAS[result.modeSuggestion];
        if (meta && !meta.templates.some((t) => t.key === layoutTemplate)) {
          setLayoutTemplate(meta.defaultTemplate);
          setSplitRatio(meta.defaultSplit);
        }
      }
    } catch (err) {
      console.error('Auto-detect failed:', err);
    } finally {
      setIsDetecting(false);
    }
  };

  const handleFramingModeClick = (newMode: FramingMode) => {
    setFramingMode(newMode);
    const meta = MODE_METAS[newMode];
    if (meta) {
      if (!meta.templates.some((t) => t.key === layoutTemplate)) {
        setLayoutTemplate(meta.defaultTemplate);
      }
      setSplitRatio(meta.defaultSplit);
    }
  };

  // ── Save Profile ──────────────────────────────────────────────────────────
  const handleSaveProfile = async () => {
    if (!profileName.trim()) return;
    setSavingProfile(true);
    try {
      const created = await api.createProfile({
        name: profileName.trim(),
        framingMode,
        aspectRatio,
        layoutTemplate,
        facecamBox,
        gameplayBox,
        splitRatio,
        paneFitMode,
        watermark: watermarkPath ? { path: watermarkPath, corner: watermarkCorner, scale: watermarkScale, opacity: watermarkOpacity } : null,
        ollamaPrompt: null,
        captionStyle: 'hormozi_pop',
        dynamicFacecamTracking,
      } as Parameters<typeof api.createProfile>[0]);
      setProfiles((prev) => [created, ...prev]);
      setProfileName('');
      setProfileSaved(true);
      setTimeout(() => setProfileSaved(false), 2500);
    } finally {
      setSavingProfile(false);
    }
  };

  const handleLoadProfile = (profile: SavedProfile) => {
    setFramingMode(profile.framingMode);
    setAspectRatio(profile.aspectRatio);
    setLayoutTemplate(profile.layoutTemplate);
    setSplitRatio(profile.splitRatio);
    if (profile.paneFitMode) {
      setPaneFitMode(profile.paneFitMode);
    }
    if (profile.facecamBox) setFacecamBox(profile.facecamBox);
    else setFacecamBox(null);
    setFaceDetected(profile.facecamBox ? true : null);
    setWatermarkPath(profile.watermark?.path ?? null);
    setWatermarkCorner(profile.watermark?.corner ?? 'bottom_right');
    setWatermarkScale(profile.watermark?.scale ?? 0.1);
    setWatermarkOpacity(profile.watermark?.opacity ?? 0.8);
    if (typeof profile.dynamicFacecamTracking === 'boolean') {
      setDynamicFacecamTracking(profile.dynamicFacecamTracking);
    }
  };

  const handleDeleteProfile = async (id: string) => {
    await api.deleteProfile(id);
    setProfiles((prev) => prev.filter((p) => p.id !== id));
  };

  // ── Render Clip ───────────────────────────────────────────────────────────
  const handleRender = async () => {
    if (!activeProject) return;
    setIsRendering(true);
    setRenderError(null);
    setRenderResult(null);

    const config: FramingConfig = {
      framingMode,
      aspectRatio,
      layoutTemplate,
      facecamBox,
      gameplayBox,
      splitRatio,
      paneFitMode,
      watermark: watermarkPath ? { path: watermarkPath, corner: watermarkCorner, scale: watermarkScale, opacity: watermarkOpacity } : null,
      faceDetected,
      dynamicFacecamTracking,
    };

    try {
      const result = await api.renderClip(activeProject.id, {
        startSec: renderStartSec,
        endSec: renderEndSec,
        framingConfig: config as unknown as FramingConfig,
      });
      setRenderResult(result);
    } catch (err: unknown) {
      setRenderError(err instanceof Error ? err.message : 'Render failed');
    } finally {
      setIsRendering(false);
    }
  };

  return (
    <div className="min-h-screen bg-background text-slate-100 flex flex-col">
      {/* ── Top Header ── */}
      <div className="border-b border-border px-6 py-3 flex flex-wrap items-center justify-between gap-4 bg-surface/30">
        <div className="flex items-center gap-3">
          <Layers className="w-5 h-5 text-cyan-400" />
          <div>
            <h1 className="text-sm font-bold font-mono text-cyan-400 tracking-wide">Layout Studio</h1>
            <span className="text-[10px] text-slate-500 font-mono">Phase 4 — Wide Framing Engine & Region Picker</span>
          </div>
        </div>

        {/* Project Selector & Scrub in Header */}
        <div className="flex items-center gap-4 flex-wrap">
          <div className="flex items-center gap-2">
            <label className="text-[11px] font-mono text-slate-400">Project:</label>
            <select
              className="bg-surface border border-border rounded px-2.5 py-1 text-xs font-mono text-slate-200 min-w-[200px]"
              value={activeProject?.id ?? ''}
              onChange={(e) => e.target.value && selectProject(e.target.value)}
            >
              <option value="">— select project —</option>
              {projects.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.title} ({p.status})
                </option>
              ))}
            </select>
            {loadingProject && <Loader2 className="w-3.5 h-3.5 animate-spin text-cyan-400" />}
          </div>

          {activeProject && (
            <div className="flex items-center gap-2 bg-surface/60 border border-border rounded-lg px-3 py-1">
              <span className="text-[11px] font-mono text-slate-400">Frame:</span>
              <input
                type="range"
                min={0}
                max={activeProject.durationSec ?? 300}
                step={0.5}
                value={frameSec}
                onChange={(e) => seekFrame(Number(e.target.value))}
                className="w-32 accent-cyan-500 cursor-pointer"
              />
              <span className="text-[11px] font-mono text-cyan-400 font-semibold w-12 text-right">{frameSec.toFixed(1)}s</span>
              {frameUrl && (
                <img
                  ref={imgRef}
                  src={frameUrl}
                  alt=""
                  className="hidden"
                  onLoad={() => setImgLoaded(true)}
                  onError={() => setImgLoaded(false)}
                />
              )}
            </div>
          )}
        </div>
      </div>

      {/* ── Main Workspace Scrollable Container ── */}
      <div className="flex-1 overflow-y-auto p-6 space-y-6">

        {/* ═══════════════════════════════════════════════════════════════════
            TOP STAGE: WIDE 70/30 DUAL-CANVAS WORKSPACE
        ═══════════════════════════════════════════════════════════════════ */}
        <div className="grid grid-cols-1 xl:grid-cols-12 gap-6 items-start">

          {/* 1. Large Wide Regions Source Canvas (Main Stage, 700–900px wide on desktop) */}
          <div className="xl:col-span-8 rounded-2xl border border-border bg-surface/50 p-4 space-y-3 shadow-xl">
            <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border pb-3">
              <div className="flex items-center gap-2.5">
                <span className="text-sm font-mono font-bold text-slate-100">Regions (Source Video)</span>
                <span className="text-[11px] font-mono px-2 py-0.5 rounded bg-slate-800 text-slate-400 border border-slate-700">
                  {naturalAspect >= 1.7 && naturalAspect <= 1.8 ? '16:9 Landscape' : `Ratio: ${naturalAspect.toFixed(2)}`}
                </span>
                {activeProject?.width && activeProject?.height && (
                  <span className="text-[11px] font-mono text-slate-500">
                    ({activeProject.width}×{activeProject.height})
                  </span>
                )}
              </div>

              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={() => {
                    if (framingMode === 'podcast') {
                      setFacecamBox({ x: 0.1, y: 0.1, w: 0.35, h: 0.45 });
                    } else {
                      setFacecamBox({ x: 0.1, y: 0.1, w: 0.35, h: 0.45 });
                    }
                    setFaceDetected(true);
                  }}
                  className="px-2 py-1 text-[11px] font-mono rounded border border-fuchsia-700 text-fuchsia-400 hover:bg-fuchsia-950/70 transition-all"
                >
                  Reset {currentMeta.r1Name}
                </button>
                {!(framingMode === 'talking_head' && (layoutTemplate === 'fullscreen_crop' || layoutTemplate === 'punch_in_zoom')) && (
                  <button
                    type="button"
                    onClick={() => {
                      if (framingMode === 'podcast') {
                        setGameplayBox({ x: 0.55, y: 0.1, w: 0.35, h: 0.45 });
                      } else {
                        setGameplayBox({ x: 0.0, y: 0.0, w: 1.0, h: 1.0 });
                      }
                    }}
                    className="px-2 py-1 text-[11px] font-mono rounded border border-cyan-700 text-cyan-400 hover:bg-cyan-950/70 transition-all"
                  >
                    Reset {currentMeta.r2Name}
                  </button>
                )}
                <button
                  type="button"
                  onClick={() => { setFacecamBox(null); setGameplayBox(null); }}
                  className="px-2 py-1 text-[11px] font-mono rounded border border-slate-600 text-slate-400 hover:bg-slate-800 transition-all"
                >
                  Clear
                </button>
                <div className="flex items-center gap-1 pl-1 border-l border-slate-800">
                  <span className="text-[10px] font-mono text-slate-400">Tightness:</span>
                  <select
                    value={tightness}
                    onChange={(e) => setTightness(e.target.value as 'close' | 'medium' | 'wide')}
                    className="bg-surface border border-violet-700/80 rounded px-1.5 py-1 text-[11px] font-mono text-violet-300 focus:outline-none"
                    title="Person Framing Tightness for Auto-Detect"
                  >
                    <option value="close">Close-Up</option>
                    <option value="medium">Medium</option>
                    <option value="wide">Wide</option>
                  </select>
                </div>
                <button
                  type="button"
                  onClick={handleAutoDetect}
                  disabled={!activeProject || isDetecting}
                  className="px-3 py-1 rounded bg-violet-600 hover:bg-violet-500 text-white text-[11px] font-mono font-semibold transition-all disabled:opacity-50 flex items-center gap-1.5 shadow"
                >
                  {isDetecting ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <ScanSearch className="w-3.5 h-3.5" />}
                  Auto-Detect
                </button>
                {/* Expand Fullscreen modal button */}
                <button
                  type="button"
                  onClick={() => setIsFullscreenOpen(true)}
                  className="px-2.5 py-1 text-[11px] font-mono font-semibold rounded border border-cyan-500 bg-cyan-950/80 text-cyan-300 hover:bg-cyan-900 transition-all flex items-center gap-1.5 shadow-md shadow-cyan-950"
                  title="Expand to Fullscreen Modal for pixel-accurate dragging & resizing"
                >
                  <Maximize2 className="w-3.5 h-3.5 text-cyan-400" />
                  Expand Fullscreen
                </button>
              </div>
            </div>

            {/* Canvas Container */}
            <div className="relative flex justify-center items-center bg-slate-950 rounded-xl border border-slate-800 overflow-hidden shadow-2xl">
              <canvas
                ref={canvasRef}
                width={REGIONS_CANVAS_W}
                height={regionsCanvasH}
                className="w-full max-w-[860px] h-auto select-none touch-none block"
                onMouseDown={(e) => handlePointerDown(e, canvasRef.current)}
                onMouseMove={(e) => handlePointerMove(e, canvasRef.current)}
                onMouseUp={handlePointerUp}
                onMouseLeave={handlePointerUp}
              />
            </div>

            {/* Region Canvas Bottom Status Bar */}
            <div className="flex flex-wrap items-center justify-between gap-3 pt-1 text-[11px] font-mono text-slate-400">
              <div className="flex items-center gap-3">
                <span className="flex items-center gap-1.5 text-fuchsia-400">
                  <span className="w-2 h-2 rounded-full bg-fuchsia-400 inline-block" />
                  {currentMeta.r1Icon} {currentMeta.r1Name}: {facecamBox ? `x:${(facecamBox.x * 100).toFixed(0)}% y:${(facecamBox.y * 100).toFixed(0)}% w:${(facecamBox.w * 100).toFixed(0)}% h:${(facecamBox.h * 100).toFixed(0)}%` : 'none'}
                </span>
                {!(framingMode === 'talking_head' && (layoutTemplate === 'fullscreen_crop' || layoutTemplate === 'punch_in_zoom')) && (
                  <span className="flex items-center gap-1.5 text-cyan-400">
                    <span className="w-2 h-2 rounded-full bg-cyan-400 inline-block" />
                    {currentMeta.r2Icon} {currentMeta.r2Name}: {gameplayBox ? `x:${(gameplayBox.x * 100).toFixed(0)}% y:${(gameplayBox.y * 100).toFixed(0)}% w:${(gameplayBox.w * 100).toFixed(0)}% h:${(gameplayBox.h * 100).toFixed(0)}%` : 'none'}
                  </span>
                )}
              </div>
              <span className="text-slate-500">Drag box to move · Drag any of 4 corner handles to resize</span>
            </div>

            {detectResult && (
              <div className="p-2.5 rounded-lg bg-violet-950/70 border border-violet-800 text-[11px] font-mono flex items-center justify-between">
                <span className="text-violet-300 font-semibold">{detectResult.message}</span>
                <span className="text-slate-400">
                  Faces: {detectResult.faceCount} · Confidence: {(detectResult.faceConfidence * 100).toFixed(0)}% · 
                  Suggested: <strong className="text-cyan-400">{detectResult.modeSuggestion}</strong>
                </span>
              </div>
            )}

            {/* Dynamic Facecam Tracking Toggle */}
            <div className="pt-2 border-t border-border-subtle flex items-center justify-between gap-3">
              <div className="space-y-0.5">
                <span className="text-xs font-mono font-medium text-slate-200 block">
                  Dynamic Subject Tracking (Auto-Follow Faces & Overlays)
                </span>
                <span className="text-[10px] font-mono text-slate-500 block">
                  Tracks faces and camera/overlay shifts across Split, PiP, Side-by-Side, Wide+Dual, Fullscreen, and Active Speaker layouts
                </span>
              </div>
              <button
                type="button"
                role="switch"
                aria-checked={dynamicFacecamTracking}
                onClick={() => setDynamicFacecamTracking(!dynamicFacecamTracking)}
                className={`relative inline-flex h-5 w-9 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 ease-in-out focus:outline-none ${
                  dynamicFacecamTracking ? 'bg-cyan-500' : 'bg-slate-700'
                }`}
              >
                <span
                  className={`pointer-events-none inline-block h-4 w-4 transform rounded-full bg-white shadow-lg ring-0 transition duration-200 ease-in-out ${
                    dynamicFacecamTracking ? 'translate-x-4' : 'translate-x-0'
                  }`}
                />
              </button>
            </div>
          </div>

          {/* 2. Output Preview Panel (Beside regions canvas, 30% width) */}
          <div className="xl:col-span-4 rounded-2xl border border-border bg-surface/50 p-4 space-y-3 shadow-xl flex flex-col justify-between">
            <div className="space-y-3">
              <div className="flex items-center justify-between border-b border-border pb-3">
                <div>
                  <span className="text-sm font-mono font-bold text-slate-100 block">Output Preview</span>
                  <span className="text-[10px] font-mono text-cyan-400">{aspectRatio} ({layoutTemplate.replace(/_/g, ' ')})</span>
                </div>
                <div className="flex items-center gap-2">
                  {layoutTemplate === 'punch_in_zoom' && (
                    <button
                      type="button"
                      onClick={() => setPunchInZoomed((z) => !z)}
                      className={`px-2 py-0.5 text-[10px] font-mono rounded border transition-all ${
                        punchInZoomed
                          ? 'border-purple-500 text-purple-300 bg-purple-950 font-bold'
                          : 'border-border text-slate-400 hover:text-slate-200'
                      }`}
                      title="Toggle preview between 100% and 112% punch-in zoom cut"
                    >
                      {punchInZoomed ? 'Auto Punch-In: 112%' : 'Auto Punch-In: 100%'}
                    </button>
                  )}
                  {layoutTemplate === 'podcast_active_speaker' && (
                    <button
                      type="button"
                      onClick={() => setActiveSpeakerHost((h) => (h === 'p1' ? 'p2' : 'p1'))}
                      className="px-2 py-0.5 text-[10px] font-mono rounded border border-sky-500 text-sky-300 bg-sky-950 font-bold hover:bg-sky-900 transition-all"
                      title="Toggle preview between Person 1 and Person 2 active speaker cuts"
                    >
                      Active Speaker: {activeSpeakerHost === 'p1' ? 'Person 1' : 'Person 2'}
                    </button>
                  )}
                  {/* Pane Fit Mode Toggle */}
                  <div className="flex items-center rounded border border-border p-0.5 bg-surface">
                    <button
                      type="button"
                      onClick={() => setPaneFitMode('fill')}
                      className={`px-2 py-0.5 text-[10px] font-mono rounded transition-all ${
                        paneFitMode === 'fill'
                          ? 'bg-cyan-500 text-slate-950 font-bold'
                          : 'text-slate-400 hover:text-slate-200'
                      }`}
                      title="Fill Pane: Zero black bars, scaled edge-to-edge"
                    >
                      Fill
                    </button>
                    <button
                      type="button"
                      onClick={() => setPaneFitMode('fit')}
                      className={`px-2 py-0.5 text-[10px] font-mono rounded transition-all ${
                        paneFitMode === 'fit'
                          ? 'bg-cyan-500 text-slate-950 font-bold'
                          : 'text-slate-400 hover:text-slate-200'
                      }`}
                      title="Fit Pane: Black bar letterbox/pillarbox padding"
                    >
                      Fit
                    </button>
                  </div>
                  <div className="flex items-center gap-1">
                    {(['9:16', '1:1', '16:9'] as AspectRatio[]).map((ar) => (
                      <button
                        key={ar}
                        type="button"
                        onClick={() => setAspectRatio(ar)}
                        className={`px-2 py-0.5 text-[10px] font-mono rounded border transition-all ${
                          aspectRatio === ar
                            ? 'border-cyan-500 text-cyan-400 bg-cyan-950 font-bold'
                            : 'border-border text-slate-400 hover:border-slate-500'
                        }`}
                      >
                        {ar}
                      </button>
                    ))}
                  </div>
                </div>
              </div>

              {/* Centered Preview Canvas */}
              <div className="flex justify-center items-center bg-slate-950/90 rounded-xl p-3 border border-border min-h-[340px]">
                <canvas
                  ref={outputCanvasRef}
                  width={outPreviewW}
                  height={outPreviewH}
                  className="rounded-lg border border-border shadow-2xl max-h-[460px] object-contain"
                />
              </div>
            </div>

            {/* Safe-zone overlay selector */}
            <div className="space-y-2 pt-2 border-t border-border-subtle">
              <label className="text-[11px] font-mono text-slate-400 flex items-center gap-1.5">
                {safeZoneKey ? <Eye className="w-3.5 h-3.5 text-yellow-400" /> : <EyeOff className="w-3.5 h-3.5 text-slate-500" />}
                Platform Safe-Zone Guides
              </label>
              <div className="flex gap-2">
                {(['shorts', 'reels', 'tiktok'] as SafeZoneKey[]).map((k) => (
                  <button
                    key={k}
                    type="button"
                    onClick={() => setSafeZoneKey(safeZoneKey === k ? null : k)}
                    className={`flex-1 px-2 py-1 text-[10px] font-mono rounded border transition-all ${
                      safeZoneKey === k
                        ? 'border-yellow-500 text-yellow-400 bg-yellow-950 font-semibold'
                        : 'border-border text-slate-400 hover:border-slate-500 bg-surface'
                    }`}
                  >
                    {k === 'shorts' ? '▶ Shorts' : k === 'reels' ? '📸 Reels' : '🎵 TikTok'}
                  </button>
                ))}
              </div>
            </div>
          </div>
        </div>

        {/* ═══════════════════════════════════════════════════════════════════
            BOTTOM SECTION: FRAMING MODE, TEMPLATE, WATERMARK, RENDER, PROFILES
        ═══════════════════════════════════════════════════════════════════ */}
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-6">

          {/* Column 1: Framing Mode & Layout Template */}
          <div className="rounded-2xl border border-border bg-surface/50 p-5 space-y-5 shadow-lg">
            {/* Framing Mode */}
            <section className="space-y-3">
              <h2 className="text-xs font-mono font-semibold text-slate-300 uppercase tracking-widest">
                Framing Mode
              </h2>
              <div className="grid grid-cols-5 gap-2">
                {(
                  [
                    { key: 'gaming', icon: '🎮', label: 'Gaming' },
                    { key: 'podcast', icon: '🎙️', label: 'Podcast' },
                    { key: 'talking_head', icon: '🗣️', label: 'Talking' },
                    { key: 'screen_presenter', icon: '🖥️', label: 'Screen' },
                    { key: 'reaction', icon: '😂', label: 'Reaction' },
                  ] as Array<{ key: FramingMode; icon: string; label: string }>
                ).map(({ key, icon, label }) => (
                  <button
                    key={key}
                    type="button"
                    onClick={() => handleFramingModeClick(key)}
                    className={`flex flex-col items-center gap-1 p-2 rounded-xl border text-[10px] font-mono transition-all ${
                      framingMode === key
                        ? 'border-cyan-500 text-cyan-400 bg-cyan-950 font-bold'
                        : 'border-border text-slate-400 hover:border-slate-500 bg-surface'
                    }`}
                  >
                    <span className="text-base">{icon}</span>
                    <span>{label}</span>
                  </button>
                ))}
              </div>

              <div className="text-[11px] font-mono text-slate-400 bg-slate-950/60 border border-border-subtle rounded-lg p-2.5 leading-relaxed">
                {framingMode === 'gaming' && '🎮 Gaming: Face detected → Split (Facecam top / Gameplay bottom). No face → Blurred fill fullscreen.'}
                {framingMode === 'podcast' && '🎙️ Podcast: Active-speaker tracking with deadband + exponential smoothing. Auto-resets on scene cuts.'}
                {framingMode === 'talking_head' && '🗣️ Talking Head: Face-centred 9:16 tracking with optional auto punch-in zoom on high-energy moments.'}
                {framingMode === 'screen_presenter' && '🖥️ Screen+Presenter: Screen on top, presenter webcam bottom with blurred pillarbox fill.'}
                {framingMode === 'reaction' && '😂 Reaction: Reactor webcam top / primary content bottom vertical split.'}
              </div>
            </section>

            {/* Layout Template */}
            <section className="space-y-3 border-t border-border-subtle pt-4">
              <div className="flex items-center justify-between">
                <h2 className="text-xs font-mono font-semibold text-slate-300 uppercase tracking-widest">Layout Template</h2>
                <span className="text-[10px] font-mono text-cyan-400 capitalize">{framingMode.replace(/_/g, ' ')} Mode</span>
              </div>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                {currentMeta.templates.map(({ key: tKey, label, desc }: ModeTemplateOption) => (
                  <button
                    key={tKey}
                    type="button"
                    onClick={() => setLayoutTemplate(tKey)}
                    title={desc}
                    className={`p-2 rounded-lg border text-left transition-all ${
                      layoutTemplate === tKey
                        ? 'border-emerald-500 text-emerald-400 bg-emerald-950/80 font-semibold shadow'
                        : 'border-border text-slate-400 hover:border-slate-500 bg-surface'
                    }`}
                  >
                    <div className="text-[11px] font-mono leading-tight">{label}</div>
                    <div className="text-[9px] font-mono text-slate-500 mt-0.5 truncate">{desc}</div>
                  </button>
                ))}
              </div>

              {(layoutTemplate === 'split_vertical' || layoutTemplate === 'split_inverted' || layoutTemplate === 'wide_plus_dual') && (
                <div className="space-y-1.5 pt-1">
                  <div className="flex items-center justify-between text-[11px] font-mono text-slate-400">
                    <span>Split Ratio (Top pane %)</span>
                    <span className="text-cyan-400 font-bold">{splitRatio}% / {100 - splitRatio}%</span>
                  </div>
                  <input
                    type="range"
                    min={10} max={90} value={splitRatio}
                    onChange={(e) => setSplitRatio(Number(e.target.value))}
                    className="w-full accent-cyan-500 cursor-pointer"
                  />
                  <div className="flex justify-between text-[10px] font-mono text-slate-500">
                    <span>35/65 (Gaming)</span>
                    <span>40/60 (Reaction)</span>
                    <span>50/50 (Podcast)</span>
                    <span>60/40 (Screen)</span>
                  </div>
                </div>
              )}
            </section>
          </div>

          {/* Column 2: Brand Watermark & Saved Channel Profiles */}
          <div className="rounded-2xl border border-border bg-surface/50 p-5 space-y-5 shadow-lg">
            {/* Watermark Controls */}
            <section className="space-y-3">
              <h2 className="text-xs font-mono font-semibold text-slate-300 uppercase tracking-widest">Brand Watermark</h2>
              <div className="space-y-3">
                <div>
                  <label className="text-[11px] font-mono text-slate-400 mb-1 block">Transparent PNG logo</label>
                  <input
                    type="file"
                    accept="image/png,.png"
                    onChange={async (event) => {
                      const file = event.target.files?.[0];
                      if (!file) return;
                      try {
                        const uploaded = await api.uploadWatermark(file);
                        setWatermarkPath(uploaded.path);
                        setWatermarkPreview((previous) => {
                          if (previous) URL.revokeObjectURL(previous);
                          return URL.createObjectURL(file);
                        });
                      } catch (error) {
                        setRenderError(error instanceof Error ? error.message : 'Watermark upload failed');
                      }
                    }}
                    className="block w-full text-[11px] text-slate-300 file:mr-3 file:rounded file:border-0 file:bg-slate-700 file:px-2.5 file:py-1 file:text-slate-100"
                  />
                  {watermarkPreview && <img src={watermarkPreview} alt="Watermark preview" className="mt-2 h-10 max-w-32 object-contain" />}
                  {watermarkPath && (
                    <button
                      type="button"
                      onClick={() => {
                        setWatermarkPath(null);
                        setWatermarkPreview((previous) => {
                          if (previous) URL.revokeObjectURL(previous);
                          return null;
                        });
                      }}
                      className="mt-1 text-[10px] text-rose-300 hover:underline"
                    >
                      Remove watermark
                    </button>
                  )}
                </div>

                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="text-[11px] font-mono text-slate-400 mb-1 block">Corner Position</label>
                    <select
                      value={watermarkCorner}
                      onChange={(e) => setWatermarkCorner(e.target.value as typeof watermarkCorner)}
                      className="w-full bg-surface border border-border rounded px-2 py-1.5 text-xs font-mono text-slate-200"
                    >
                      <option value="top_left">Top Left</option>
                      <option value="top_right">Top Right</option>
                      <option value="bottom_left">Bottom Left</option>
                      <option value="bottom_right">Bottom Right</option>
                    </select>
                  </div>
                  <div>
                    <label className="text-[11px] font-mono text-slate-400 mb-1 block">Scale ({(watermarkScale * 100).toFixed(0)}%)</label>
                    <input type="range" min={3} max={30} value={watermarkScale * 100}
                      onChange={(e) => setWatermarkScale(Number(e.target.value) / 100)}
                      className="w-full accent-cyan-500 mt-2" />
                  </div>
                </div>

                <div>
                  <label className="text-[11px] font-mono text-slate-400 mb-1 block">Opacity ({(watermarkOpacity * 100).toFixed(0)}%)</label>
                  <input type="range" min={10} max={100} value={watermarkOpacity * 100}
                    onChange={(e) => setWatermarkOpacity(Number(e.target.value) / 100)}
                    className="w-full accent-cyan-500" />
                </div>
              </div>
            </section>

            {/* Saved Channel Profiles */}
            <section className="space-y-3 border-t border-border-subtle pt-4">
              <h2 className="text-xs font-mono font-semibold text-slate-300 uppercase tracking-widest flex items-center gap-2">
                <BookmarkPlus className="w-4 h-4 text-yellow-400" /> Saved Channel Profiles
              </h2>

              <div className="flex gap-2">
                <input
                  type="text"
                  placeholder="Profile name (e.g. My Gaming Channel)"
                  value={profileName}
                  onChange={(e) => setProfileName(e.target.value)}
                  className="flex-1 bg-surface border border-border rounded px-2.5 py-1.5 text-xs font-mono text-slate-200 placeholder-slate-500"
                />
                <button
                  type="button"
                  onClick={handleSaveProfile}
                  disabled={!profileName.trim() || savingProfile}
                  className="px-3 py-1.5 rounded-lg bg-yellow-600 hover:bg-yellow-500 text-black font-bold text-xs font-mono flex items-center gap-1.5 transition-all disabled:opacity-50"
                >
                  {savingProfile ? <Loader2 className="w-3 h-3 animate-spin" /> : <Wand2 className="w-3 h-3" />}
                  Save
                </button>
              </div>

              {profileSaved && (
                <div className="text-xs font-mono text-emerald-400 flex items-center gap-1.5">
                  <CheckCircle2 className="w-3.5 h-3.5" /> Profile saved!
                </div>
              )}

              {profiles.length > 0 && (
                <div className="space-y-2 max-h-36 overflow-y-auto pr-1">
                  {profiles.map((profile) => (
                    <div
                      key={profile.id}
                      className="flex items-center justify-between p-2 rounded-lg bg-surface border border-border-subtle hover:border-border transition-all"
                    >
                      <div className="space-y-0.5 truncate mr-2">
                        <div className="text-xs font-mono font-semibold text-slate-200 truncate">{profile.name}</div>
                        <div className="text-[10px] font-mono text-slate-500">
                          {profile.framingMode} · {profile.aspectRatio} · {profile.splitRatio}% split
                        </div>
                      </div>
                      <div className="flex items-center gap-1.5 flex-shrink-0">
                        <button
                          type="button"
                          onClick={() => handleLoadProfile(profile)}
                          className="px-2 py-0.5 text-[10px] font-mono rounded border border-cyan-700 text-cyan-400 hover:bg-cyan-950 transition-all flex items-center gap-1"
                        >
                          <Video className="w-3 h-3" /> Load
                        </button>
                        <button
                          type="button"
                          onClick={() => handleDeleteProfile(profile.id)}
                          className="p-1 rounded border border-red-900 text-red-500 hover:bg-red-950 transition-all"
                        >
                          <Trash2 className="w-3 h-3" />
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </section>
          </div>

          {/* Column 3: Render Controls */}
          <div className="rounded-2xl border border-border bg-surface/50 p-5 space-y-4 shadow-lg flex flex-col justify-between">
            <div className="space-y-4">
              <h2 className="text-xs font-mono font-semibold text-slate-300 uppercase tracking-widest flex items-center gap-2">
                <Cpu className="w-4 h-4 text-orange-400" /> Quick Render Test
              </h2>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="text-[11px] font-mono text-slate-400 mb-1 block">Start (sec)</label>
                  <input type="number" value={renderStartSec} min={0} step={0.5}
                    onChange={(e) => setRenderStartSec(Number(e.target.value))}
                    className="w-full bg-background border border-border rounded px-2 py-1.5 text-xs font-mono text-slate-200" />
                </div>
                <div>
                  <label className="text-[11px] font-mono text-slate-400 mb-1 block">End (sec)</label>
                  <input type="number" value={renderEndSec} min={1} step={0.5}
                    onChange={(e) => setRenderEndSec(Number(e.target.value))}
                    className="w-full bg-background border border-border rounded px-2 py-1.5 text-xs font-mono text-slate-200" />
                </div>
              </div>

              <div className="text-[11px] font-mono text-slate-400 bg-slate-950/60 p-2.5 rounded-lg border border-border-subtle space-y-1">
                <div>Codec: NVENC (auto-fallback to libx264)</div>
                <div>Format: CFR · faststart · AAC 128k</div>
              </div>
            </div>

            <div className="space-y-3">
              <button
                type="button"
                onClick={handleRender}
                disabled={!activeProject || isRendering}
                className="w-full flex items-center justify-center gap-2 px-4 py-2.5 rounded-xl bg-gradient-to-r from-orange-600 to-amber-600 hover:opacity-95 text-white text-xs font-mono font-bold transition-all disabled:opacity-50 shadow-md"
              >
                {isRendering ? <Loader2 className="w-4 h-4 animate-spin" /> : <Download className="w-4 h-4" />}
                {isRendering ? 'Rendering clip…' : `Render ${Math.max(1, Math.round(renderEndSec - renderStartSec))}s Clip`}
              </button>

              {renderError && (
                <div className="p-2.5 rounded-lg bg-red-950/80 border border-red-800 text-xs font-mono text-red-300">
                  {renderError}
                </div>
              )}

              {renderResult && (
                <div className="p-2.5 rounded-lg bg-emerald-950/80 border border-emerald-800 text-[11px] font-mono space-y-0.5">
                  <div className="text-emerald-400 font-semibold flex items-center gap-1.5">
                    <CheckCircle2 className="w-3.5 h-3.5" /> Render Complete!
                  </div>
                  <div className="text-slate-400">Encoder: <span className="text-cyan-400">{renderResult.encoderUsed}</span></div>
                  <div className="text-slate-400">File: <span className="text-slate-200 break-all">{renderResult.outputFilename}</span></div>
                </div>
              )}
            </div>
          </div>
        </div>
      </div>

      {/* ═══════════════════════════════════════════════════════════════════
          EXPAND FULLSCREEN MODAL (Pixel-Accurate Precision Canvas)
      ═══════════════════════════════════════════════════════════════════ */}
      {isFullscreenOpen && (
        <div className="fixed inset-0 z-50 flex flex-col bg-slate-950/95 backdrop-blur-md p-6 overflow-hidden animate-in fade-in duration-200">
          {/* Modal Header */}
          <div className="flex items-center justify-between border-b border-slate-800 pb-4 mb-4">
            <div className="flex items-center gap-3">
              <Maximize2 className="w-5 h-5 text-cyan-400" />
              <div>
                <h2 className="text-base font-mono font-bold text-slate-100">
                  Pixel-Accurate Region Editor (Fullscreen Mode)
                </h2>
                <p className="text-xs font-mono text-slate-400">
                  Source: {activeProject?.width ?? 1920}×{activeProject?.height ?? 1080} · Drag any corner handle for micro-precise box fitting
                </p>
              </div>
            </div>

            <div className="flex items-center gap-3">
              <button
                type="button"
                onClick={() => {
                  setFacecamBox({ x: 0.1, y: 0.1, w: 0.35, h: 0.45 });
                  setFaceDetected(true);
                }}
                className="px-2.5 py-1 text-xs font-mono rounded border border-fuchsia-700 text-fuchsia-400 hover:bg-fuchsia-950 transition-all"
              >
                Reset {currentMeta.r1Name}
              </button>
              {!(framingMode === 'talking_head' && (layoutTemplate === 'fullscreen_crop' || layoutTemplate === 'punch_in_zoom')) && (
                <button
                  type="button"
                  onClick={() => {
                    if (framingMode === 'podcast') {
                      setGameplayBox({ x: 0.55, y: 0.1, w: 0.35, h: 0.45 });
                    } else {
                      setGameplayBox({ x: 0.0, y: 0.0, w: 1.0, h: 1.0 });
                    }
                  }}
                  className="px-2.5 py-1 text-xs font-mono rounded border border-cyan-700 text-cyan-400 hover:bg-cyan-950 transition-all"
                >
                  Reset {currentMeta.r2Name}
                </button>
              )}
              <button
                type="button"
                onClick={() => { setFacecamBox(null); setGameplayBox(null); }}
                className="px-2.5 py-1 text-xs font-mono rounded border border-slate-700 text-slate-400 hover:bg-slate-800 transition-all"
              >
                Clear
              </button>
              <button
                type="button"
                onClick={() => setIsFullscreenOpen(false)}
                className="px-3 py-1.5 text-xs font-mono rounded-lg bg-cyan-600 hover:bg-cyan-500 text-slate-950 font-bold flex items-center gap-1.5 transition-all"
              >
                <Minimize2 className="w-4 h-4" />
                Done
              </button>
              <button
                type="button"
                onClick={() => setIsFullscreenOpen(false)}
                className="p-1.5 rounded-lg border border-slate-700 text-slate-400 hover:text-white hover:bg-slate-800 transition-all"
                title="Close (Esc)"
              >
                <X className="w-5 h-5" />
              </button>
            </div>
          </div>

          {/* Modal Huge Canvas Stage */}
          <div className="flex-1 flex items-center justify-center overflow-hidden bg-slate-900/60 rounded-2xl border border-slate-800 p-4">
            <canvas
              ref={fullscreenCanvasRef}
              width={FULLSCREEN_CANVAS_W}
              height={fullscreenCanvasH}
              className="max-w-full max-h-[75vh] w-auto h-auto rounded-xl border border-slate-700 shadow-2xl select-none touch-none block"
              onMouseDown={(e) => handlePointerDown(e, fullscreenCanvasRef.current)}
              onMouseMove={(e) => handlePointerMove(e, fullscreenCanvasRef.current)}
              onMouseUp={handlePointerUp}
              onMouseLeave={handlePointerUp}
            />
          </div>

          {/* Modal Footer with Live Coords */}
          <div className="flex items-center justify-between border-t border-slate-800 pt-3 mt-4 text-xs font-mono">
            <div className="flex items-center gap-6">
              <span className="text-fuchsia-400 font-semibold">
                {currentMeta.r1Icon} {currentMeta.r1Name}: {facecamBox ? `X: ${(facecamBox.x * 100).toFixed(1)}% | Y: ${(facecamBox.y * 100).toFixed(1)}% | W: ${(facecamBox.w * 100).toFixed(1)}% | H: ${(facecamBox.h * 100).toFixed(1)}%` : 'none'}
              </span>
              {!(framingMode === 'talking_head' && (layoutTemplate === 'fullscreen_crop' || layoutTemplate === 'punch_in_zoom')) && (
                <span className="text-cyan-400 font-semibold">
                  {currentMeta.r2Icon} {currentMeta.r2Name}: {gameplayBox ? `X: ${(gameplayBox.x * 100).toFixed(1)}% | Y: ${(gameplayBox.y * 100).toFixed(1)}% | W: ${(gameplayBox.w * 100).toFixed(1)}% | H: ${(gameplayBox.h * 100).toFixed(1)}%` : 'none'}
                </span>
              )}
            </div>
            <span className="text-slate-500">Press ESC or click Done to return</span>
          </div>
        </div>
      )}
    </div>
  );
};

export default LayoutStudio;
