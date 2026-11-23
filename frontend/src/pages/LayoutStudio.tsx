import React, {
  useCallback,
  useEffect,
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
  ScanSearch,
  Trash2,
  Video,
  Wand2,
} from 'lucide-react';
import { api } from '../api/client';
import { useWorkspace } from '../context/WorkspaceContext';
import {
  AspectRatio,
  AutoDetectResult,
  FramingConfig,
  FramingMode,
  LayoutTemplate,
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

interface DragState {
  boxKey: 'facecam' | 'gameplay' | null;
  action: 'move' | 'resize-br' | null;
  startMouseX: number;
  startMouseY: number;
  startBox: RegionBox;
}

function emptyBox(): RegionBox {
  return { x: 0.0, y: 0.0, w: 0.5, h: 0.5 };
}

function clampBox(box: RegionBox): RegionBox {
  const x = Math.max(0, Math.min(0.99, box.x));
  const y = Math.max(0, Math.min(0.99, box.y));
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

  // ── Safe-zone overlay ─────────────────────────────────────────────────────
  const [safeZoneKey, setSafeZoneKey] = useState<SafeZoneKey>(null);

  // ── Watermark ─────────────────────────────────────────────────────────────
  const [watermarkOpacity, setWatermarkOpacity] = useState(0.8);
  const [watermarkScale, setWatermarkScale] = useState(0.1);
  const [watermarkPath, setWatermarkPath] = useState<string | null>(null);
  const [watermarkPreview, setWatermarkPreview] = useState<string | null>(null);
  const [watermarkCorner, setWatermarkCorner] = useState<'top_left' | 'top_right' | 'bottom_left' | 'bottom_right'>('bottom_right');

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
          facecamBox,
          gameplayBox,
          watermarkOpacity,
          watermarkScale,
          watermarkCorner,
          watermarkPath,
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
    facecamBox,
    gameplayBox,
    watermarkOpacity,
    watermarkScale,
    watermarkCorner,
    watermarkPath,
  ]);

  // Seek to new frame time
  const seekFrame = useCallback((t: number) => {
    if (!activeProject) return;
    const clamped = Math.max(0, Math.min(t, (activeProject.durationSec ?? 300) - 0.5));
    setFrameSec(clamped);
    setFrameUrl(api.getFrameUrl(activeProject.id, clamped) + `&_=${Date.now()}`);
    setImgLoaded(false);
  }, [activeProject]);

  // ── Canvas drawing & dimension math ──────────────────────────────────────
  const [outW, outH] = ASPECT_DIMS[aspectRatio];

  // Natural aspect ratio of the source video (width / height)
  const naturalAspect = (imgRef.current && imgRef.current.naturalWidth && imgRef.current.naturalHeight)
    ? (imgRef.current.naturalWidth / imgRef.current.naturalHeight)
    : (activeProject?.width && activeProject?.height)
    ? (activeProject.width / activeProject.height)
    : (16 / 9);

  // Regions source canvas: always preserve natural aspect ratio
  const REGIONS_CANVAS_W = 440;
  const regionsCanvasH = Math.max(120, Math.round(REGIONS_CANVAS_W / naturalAspect));

  // Output preview canvas: strictly preserve selected target aspect ratio
  const targetAspect = outW / outH;
  const OUTPUT_MAX_H = 340;
  const OUTPUT_MAX_W = 340;
  let outPreviewW = OUTPUT_MAX_W;
  let outPreviewH = Math.round(OUTPUT_MAX_W / targetAspect);
  if (outPreviewH > OUTPUT_MAX_H) {
    outPreviewH = OUTPUT_MAX_H;
    outPreviewW = Math.round(OUTPUT_MAX_H * targetAspect);
  }

  const drawCanvas = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    ctx.clearRect(0, 0, canvas.width, canvas.height);

    // Draw frame image preserving natural aspect ratio across the source canvas
    if (imgRef.current && imgLoaded) {
      ctx.drawImage(imgRef.current, 0, 0, canvas.width, canvas.height);
    } else {
      ctx.fillStyle = '#0f172a';
      ctx.fillRect(0, 0, canvas.width, canvas.height);
      ctx.fillStyle = '#334155';
      ctx.font = '13px monospace';
      ctx.textAlign = 'center';
      ctx.fillText(activeProject ? 'Loading frame preview…' : 'Select a project', canvas.width / 2, canvas.height / 2);
    }

    const W = canvas.width;
    const H = canvas.height;

    // Draw region boxes
    const drawBox = (box: RegionBox, color: string, label: string) => {
      const { x, y, w, h } = boxToPx(box, W, H);
      ctx.strokeStyle = color;
      ctx.lineWidth = 2;
      ctx.setLineDash([]);
      ctx.strokeRect(x, y, w, h);
      ctx.fillStyle = color.replace('1)', '0.12)');
      ctx.fillRect(x, y, w, h);

      // Label pill
      ctx.fillStyle = color;
      ctx.font = 'bold 10px monospace';
      ctx.textAlign = 'left';
      ctx.fillText(label, x + 4, y + 13);

      // Resize handle (bottom-right corner)
      ctx.fillStyle = color;
      ctx.fillRect(x + w - 10, y + h - 10, 10, 10);
    };

    if (gameplayBox) drawBox(gameplayBox, 'rgba(0,210,255,1)', '🎮 Gameplay');
    if (facecamBox) drawBox(facecamBox, 'rgba(255,100,220,1)', '📷 Facecam');
  }, [imgLoaded, facecamBox, gameplayBox, activeProject]);

  useEffect(() => {
    drawCanvas();
  }, [drawCanvas]);

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
      const sw = box.w * image.naturalWidth;
      const sh = box.h * image.naturalHeight;
      const scale = Math.min(dw / sw, dh / sh);
      const rw = sw * scale;
      const rh = sh * scale;
      ctx.drawImage(image, sx, sy, sw, sh, dx + (dw - rw) / 2, dy + (dh - rh) / 2, rw, rh);
    };

    if (layoutTemplate === 'split_vertical') {
      const topPaneH = H * (splitRatio / 100);
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
      ctx.strokeStyle = 'rgba(255,255,255,0.6)';
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      ctx.moveTo(0, topPaneH);
      ctx.lineTo(W, topPaneH);
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.fillStyle = 'rgba(0,0,0,0.6)';
      ctx.fillRect(4, topPaneH - 14, 80, 13);
      ctx.fillStyle = 'rgba(255,255,255,0.9)';
      ctx.font = '10px monospace';
      ctx.textAlign = 'left';
      ctx.fillText(`${splitRatio}% / ${100 - splitRatio}%`, 8, topPaneH - 4);
    } else if (layoutTemplate === 'pip') {
      const mainBox = gameplayBox ?? { x: 0, y: 0, w: 1, h: 1 };
      const pipBox = facecamBox ?? { x: 0, y: 0, w: 0.3, h: 0.25 };
      drawRegion(mainBox, 0, 0, W, H);

      const pipW = Math.round(W * 0.32);
      const pipH = Math.round(pipW * (pipBox.h / pipBox.w));
      const pipX = W - pipW - 10;
      const pipY = 10;
      ctx.fillStyle = 'rgba(0,0,0,0.4)';
      ctx.fillRect(pipX - 2, pipY - 2, pipW + 4, pipH + 4);
      drawRegion(pipBox, pipX, pipY, pipW, pipH);
      ctx.strokeStyle = 'rgba(255,100,220,0.9)';
      ctx.lineWidth = 1.5;
      ctx.strokeRect(pipX, pipY, pipW, pipH);
    } else if (layoutTemplate === 'blurred_fill') {
      // Blurred background fills/covers the canvas
      ctx.save();
      ctx.filter = 'blur(16px)';
      const bgScale = Math.max(W / image.naturalWidth, H / image.naturalHeight);
      const bgW = image.naturalWidth * bgScale;
      const bgH = image.naturalHeight * bgScale;
      ctx.drawImage(image, (W - bgW) / 2, (H - bgH) / 2, bgW, bgH);
      ctx.restore();

      // Sharp foreground overlaid ON TOP
      const fgBox = gameplayBox ?? facecamBox ?? { x: 0, y: 0, w: 1, h: 1 };
      drawRegion(fgBox, 0, 0, W, H);
    } else {
      // Fullscreen crop
      const cropBox = (framingMode === 'talking_head' || framingMode === 'podcast')
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
        ctx.fillStyle = 'rgba(255,255,255,0.7)';
        ctx.font = '9px monospace';
        ctx.textAlign = 'left';
        ctx.fillText(zone.label, zone.x * W + 4, zone.y * H + 11);
      }
    }

    if (watermarkPreview) {
      const logo = new Image();
      logo.onload = () => {
        const logoW = W * watermarkScale;
        const logoH = logoW * logo.height / logo.width;
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
    facecamBox,
    gameplayBox,
    splitRatio,
    safeZoneKey,
    watermarkPreview,
    watermarkScale,
    watermarkOpacity,
    watermarkCorner,
  ]);

  useEffect(() => {
    drawOutputPreview();
  }, [drawOutputPreview]);

  // ── Canvas mouse DnD accurately mapped to source coordinates ──────────────
  const hitTest = useCallback(
    (cx: number, cy: number, W: number, H: number): { boxKey: 'facecam' | 'gameplay'; action: 'move' | 'resize-br' } | null => {
      const HANDLE = 14;

      for (const [key, box] of [
        ['facecam', facecamBox] as const,
        ['gameplay', gameplayBox] as const,
      ]) {
        if (!box) continue;
        const { x, y, w, h } = boxToPx(box, W, H);
        if (cx >= x + w - HANDLE && cy >= y + h - HANDLE && cx <= x + w + 4 && cy <= y + h + 4) {
          return { boxKey: key, action: 'resize-br' };
        }
        if (cx >= x && cy >= y && cx <= x + w && cy <= y + h) {
          return { boxKey: key, action: 'move' };
        }
      }
      return null;
    },
    [facecamBox, gameplayBox]
  );

  const onMouseDown = useCallback(
    (e: React.MouseEvent<HTMLCanvasElement>) => {
      const canvas = canvasRef.current;
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
    },
    [hitTest, facecamBox, gameplayBox]
  );

  const onMouseMove = useCallback(
    (e: React.MouseEvent<HTMLCanvasElement>) => {
      const { boxKey, action, startMouseX, startMouseY, startBox } = dragRef.current;
      if (!boxKey || !action) return;

      const canvas = canvasRef.current;
      if (!canvas) return;
      const rect = canvas.getBoundingClientRect();
      const mx = (e.clientX - rect.left) * canvas.width / rect.width;
      const my = (e.clientY - rect.top) * canvas.height / rect.height;

      // Accurately normalize dx and dy to source canvas coordinate system [0.0, 1.0]
      const dx = (mx - startMouseX) / canvas.width;
      const dy = (my - startMouseY) / canvas.height;

      let newBox: RegionBox;
      if (action === 'move') {
        newBox = clampBox({ ...startBox, x: startBox.x + dx, y: startBox.y + dy });
      } else {
        newBox = clampBox({ ...startBox, w: startBox.w + dx, h: startBox.h + dy });
      }

      if (boxKey === 'facecam') {
        setFacecamBox(newBox);
        setFaceDetected(true);
      } else {
        setGameplayBox(newBox);
      }
    },
    []
  );

  const onMouseUp = useCallback(() => {
    dragRef.current = { boxKey: null, action: null, startMouseX: 0, startMouseY: 0, startBox: emptyBox() };
  }, []);

  // ── Auto-Detect Regions ───────────────────────────────────────────────────
  const handleAutoDetect = async () => {
    if (!activeProject) return;
    setIsDetecting(true);
    setDetectResult(null);
    try {
      const result = await api.autoDetectRegions(activeProject.id, frameSec);
      setDetectResult(result);
      if (result.facecamBox) setFacecamBox(result.facecamBox);
      else if (result.faceCount === 0) setFacecamBox(null);
      if (result.gameplayBox) setGameplayBox(result.gameplayBox);
      setFaceDetected(result.faceCount > 0);
      if (result.modeSuggestion) setFramingMode(result.modeSuggestion);
    } catch (err) {
      console.error('Auto-detect failed:', err);
    } finally {
      setIsDetecting(false);
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
        watermark: watermarkPath ? { path: watermarkPath, corner: watermarkCorner, scale: watermarkScale, opacity: watermarkOpacity } : null,
        ollamaPrompt: null,
        captionStyle: 'hormozi_pop',
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
    if (profile.facecamBox) setFacecamBox(profile.facecamBox);
    else setFacecamBox(null);
    setFaceDetected(profile.facecamBox ? true : null);
    setWatermarkPath(profile.watermark?.path ?? null);
    setWatermarkCorner(profile.watermark?.corner ?? 'bottom_right');
    setWatermarkScale(profile.watermark?.scale ?? 0.1);
    setWatermarkOpacity(profile.watermark?.opacity ?? 0.8);
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
      watermark: watermarkPath ? { path: watermarkPath, corner: watermarkCorner, scale: watermarkScale, opacity: watermarkOpacity } : null,
      faceDetected,
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
      {/* ── Header ── */}
      <div className="border-b border-border px-6 py-3 flex items-center gap-3">
        <Layers className="w-5 h-5 text-cyan-400" />
        <h1 className="text-sm font-bold font-mono text-cyan-400 tracking-wide">Layout Studio</h1>
        <span className="text-xs text-slate-500 font-mono">Phase 4 — Framing Engine</span>
      </div>

      <div className="flex flex-1 overflow-hidden">
        {/* ═══════════════════════════════════════════════════════════════════
            LEFT PANEL — Project selector + Canvas crop editor
        ═══════════════════════════════════════════════════════════════════ */}
        <div className="w-[480px] flex-shrink-0 border-r border-border flex flex-col overflow-y-auto">
          {/* Project Selector */}
          <div className="p-4 border-b border-border-subtle space-y-2">
            <label className="block text-[11px] font-mono text-slate-400">Active Project</label>
            <select
              className="w-full bg-surface border border-border rounded px-2 py-1.5 text-xs font-mono text-slate-200"
              value={activeProject?.id ?? ''}
              onChange={(e) => e.target.value && selectProject(e.target.value)}
            >
              <option value="">— select a project —</option>
              {projects.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.title} ({p.status})
                </option>
              ))}
            </select>
            {loadingProject && (
              <div className="flex items-center gap-1.5 text-xs text-cyan-400 font-mono">
                <Loader2 className="w-3.5 h-3.5 animate-spin" /> Loading…
              </div>
            )}
          </div>

          {/* Frame Seek */}
          {activeProject && (
            <div className="p-4 border-b border-border-subtle space-y-2">
              <div className="flex items-center justify-between">
                <label className="text-[11px] font-mono text-slate-400">Preview Frame (seek)</label>
                <span className="text-[11px] font-mono text-cyan-400">{frameSec.toFixed(1)}s</span>
              </div>
              <input
                type="range"
                min={0}
                max={activeProject.durationSec ?? 300}
                step={0.5}
                value={frameSec}
                onChange={(e) => seekFrame(Number(e.target.value))}
                className="w-full accent-cyan-500"
              />
              {/* Hidden img for canvas drawing */}
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

          {/* 1. Regions Source Canvas (Always natural aspect ratio) */}
          <div className="p-4 border-b border-border-subtle space-y-3">
            <div className="flex items-center justify-between">
              <div>
                <span className="text-xs font-mono font-semibold text-slate-200 block">Regions (Source Video)</span>
                <span className="text-[10px] font-mono text-slate-500">
                  Natural aspect: {naturalAspect >= 1.7 && naturalAspect <= 1.8 ? '16:9 Landscape' : naturalAspect.toFixed(2)}
                </span>
              </div>
              <div className="flex gap-1.5">
                <button
                  onClick={() => { setFacecamBox({ x: 0.0, y: 0.0, w: 0.3, h: 0.25 }); setFaceDetected(true); }}
                  className="px-2 py-0.5 text-[10px] font-mono rounded border border-fuchsia-700 text-fuchsia-400 hover:bg-fuchsia-950 transition-all"
                >
                  Reset Face
                </button>
                <button
                  onClick={() => setGameplayBox({ x: 0.0, y: 0.0, w: 1.0, h: 1.0 })}
                  className="px-2 py-0.5 text-[10px] font-mono rounded border border-cyan-700 text-cyan-400 hover:bg-cyan-950 transition-all"
                >
                  Reset Game
                </button>
                <button
                  onClick={() => { setFacecamBox(null); setGameplayBox(null); }}
                  className="px-2 py-0.5 text-[10px] font-mono rounded border border-slate-600 text-slate-400 hover:bg-slate-800 transition-all"
                >
                  Clear
                </button>
              </div>
            </div>

            <canvas
              ref={canvasRef}
              width={REGIONS_CANVAS_W}
              height={regionsCanvasH}
              className="rounded-lg border border-border w-full cursor-crosshair select-none touch-none bg-slate-950 block shadow-inner"
              onMouseDown={onMouseDown}
              onMouseMove={onMouseMove}
              onMouseUp={onMouseUp}
              onMouseLeave={onMouseUp}
            />

            <div className="flex items-center justify-between text-[10px] text-slate-500 font-mono">
              <span>Drag boxes to move. Drag corners to resize.</span>
              <span>0.0–1.0 normalized coords</span>
            </div>

            {/* Auto-Detect */}
            <button
              onClick={handleAutoDetect}
              disabled={!activeProject || isDetecting}
              className="w-full flex items-center justify-center gap-2 px-3 py-2 rounded-lg bg-violet-600 hover:bg-violet-500 text-white text-xs font-mono font-semibold transition-all disabled:opacity-50"
            >
              {isDetecting ? (
                <Loader2 className="w-3.5 h-3.5 animate-spin" />
              ) : (
                <ScanSearch className="w-3.5 h-3.5" />
              )}
              Auto-Detect Regions (MediaPipe)
            </button>

            {detectResult && (
              <div className="p-2.5 rounded-lg bg-violet-950 border border-violet-800 text-[11px] font-mono space-y-0.5">
                <div className="text-violet-300 font-semibold">{detectResult.message}</div>
                <div className="text-slate-400">
                  Faces: {detectResult.faceCount} · Confidence: {(detectResult.faceConfidence * 100).toFixed(0)}% · 
                  Suggested Mode: <span className="text-cyan-400">{detectResult.modeSuggestion}</span>
                </div>
              </div>
            )}
          </div>

          {/* 2. Output Preview Panel (Strict target aspect ratio) */}
          <div className="p-4 space-y-3">
            <div className="flex items-center justify-between">
              <div>
                <span className="text-xs font-mono font-semibold text-slate-200 block">Output Preview</span>
                <span className="text-[10px] font-mono text-cyan-400">Target: {aspectRatio} ({layoutTemplate.replace('_', ' ')})</span>
              </div>
              <div className="flex items-center gap-1.5">
                {/* Aspect ratio toggle */}
                {(['9:16', '1:1', '16:9'] as AspectRatio[]).map((ar) => (
                  <button
                    key={ar}
                    onClick={() => setAspectRatio(ar)}
                    className={`px-2 py-0.5 text-[10px] font-mono rounded border transition-all ${
                      aspectRatio === ar
                        ? 'border-cyan-500 text-cyan-400 bg-cyan-950'
                        : 'border-border text-slate-400 hover:border-slate-500'
                    }`}
                  >
                    {ar}
                  </button>
                ))}
              </div>
            </div>

            <div className="flex justify-center items-center bg-slate-950/80 rounded-xl p-3 border border-border min-h-[220px]">
              <canvas
                ref={outputCanvasRef}
                width={outPreviewW}
                height={outPreviewH}
                className="rounded-lg border border-border shadow-lg"
              />
            </div>

            {/* Safe-zone overlay selector */}
            <div className="space-y-1.5">
              <label className="text-[11px] font-mono text-slate-400 flex items-center gap-1.5">
                {safeZoneKey ? <Eye className="w-3 h-3" /> : <EyeOff className="w-3 h-3" />}
                Platform Safe-Zone Overlay
              </label>
              <div className="flex gap-2">
                {(['shorts', 'reels', 'tiktok'] as SafeZoneKey[]).map((k) => (
                  <button
                    key={k}
                    onClick={() => setSafeZoneKey(safeZoneKey === k ? null : k)}
                    className={`flex-1 px-2 py-1 text-[10px] font-mono rounded border transition-all ${
                      safeZoneKey === k
                        ? 'border-yellow-500 text-yellow-400 bg-yellow-950'
                        : 'border-border text-slate-400 hover:border-slate-500'
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
            RIGHT PANEL — Mode/Layout config, Watermark, Profiles, Render
        ═══════════════════════════════════════════════════════════════════ */}
        <div className="flex-1 overflow-y-auto p-6 space-y-6">
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
                  { key: 'talking_head', icon: '🗣️', label: 'Talking Head' },
                  { key: 'screen_presenter', icon: '🖥️', label: 'Screen+Pres.' },
                  { key: 'reaction', icon: '😂', label: 'Reaction' },
                ] as Array<{ key: FramingMode; icon: string; label: string }>
              ).map(({ key, icon, label }) => (
                <button
                  key={key}
                  onClick={() => setFramingMode(key)}
                  className={`flex flex-col items-center gap-1 p-2.5 rounded-xl border text-[11px] font-mono transition-all ${
                    framingMode === key
                      ? 'border-cyan-500 text-cyan-400 bg-cyan-950'
                      : 'border-border text-slate-400 hover:border-slate-500 bg-surface'
                  }`}
                >
                  <span className="text-lg">{icon}</span>
                  <span>{label}</span>
                </button>
              ))}
            </div>

            {/* Mode descriptions */}
            <div className="text-[11px] font-mono text-slate-500 bg-surface border border-border-subtle rounded-lg p-2.5">
              {framingMode === 'gaming' && '🎮 Gaming: Face detected → Split (Facecam top / Gameplay bottom). No face → Blurred fill fullscreen.'}
              {framingMode === 'podcast' && '🎙️ Podcast: MediaPipe active-speaker tracking with deadband + exponential smoothing. Auto-resets on scene cuts.'}
              {framingMode === 'talking_head' && '🗣️ Talking Head: Face-centred 9:16 tracking with optional auto punch-in zoom on high-energy moments.'}
              {framingMode === 'screen_presenter' && '🖥️ Screen+Presenter: Screen/slide on top, presenter webcam bottom. Blurred pillarbox fill.'}
              {framingMode === 'reaction' && '😂 Reaction: Reactor webcam top / primary content bottom vertical split.'}
            </div>
          </section>

          {/* Layout Template */}
          <section className="space-y-2">
            <h2 className="text-xs font-mono font-semibold text-slate-300 uppercase tracking-widest">Layout Template</h2>
            <div className="grid grid-cols-4 gap-2">
              {(
                [
                  { key: 'split_vertical', label: 'Split Vertical' },
                  { key: 'fullscreen_crop', label: 'Fullscreen Crop' },
                  { key: 'blurred_fill', label: 'Blurred Fill' },
                  { key: 'pip', label: 'Picture-in-Picture' },
                ] as Array<{ key: LayoutTemplate; label: string }>
              ).map(({ key, label }) => (
                <button
                  key={key}
                  onClick={() => setLayoutTemplate(key)}
                  className={`p-2 rounded-lg border text-[11px] font-mono text-center transition-all ${
                    layoutTemplate === key
                      ? 'border-emerald-500 text-emerald-400 bg-emerald-950'
                      : 'border-border text-slate-400 hover:border-slate-500 bg-surface'
                  }`}
                >
                  {label}
                </button>
              ))}
            </div>

            {layoutTemplate === 'split_vertical' && (
              <div className="space-y-1">
                <div className="flex items-center justify-between text-[11px] font-mono text-slate-400">
                  <span>Split Ratio (Top pane %)</span>
                  <span className="text-cyan-400">{splitRatio}% / {100 - splitRatio}%</span>
                </div>
                <input
                  type="range"
                  min={10} max={90} value={splitRatio}
                  onChange={(e) => setSplitRatio(Number(e.target.value))}
                  className="w-full accent-cyan-500"
                />
                <div className="flex justify-between text-[10px] font-mono text-slate-500">
                  <span>35/65 (Gaming default)</span>
                  <span>40/60</span>
                  <span>50/50</span>
                </div>
              </div>
            )}
          </section>

          {/* Watermark Controls */}
          <section className="space-y-2">
            <h2 className="text-xs font-mono font-semibold text-slate-300 uppercase tracking-widest">Brand Watermark</h2>
            <div className="grid grid-cols-2 gap-3">
              <div className="col-span-2">
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
                  className="block w-full text-[11px] text-slate-300 file:mr-3 file:rounded file:border-0 file:bg-slate-700 file:px-3 file:py-1.5 file:text-slate-100"
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
                    className="mt-1 text-[10px] text-rose-300"
                  >
                    Remove watermark
                  </button>
                )}
              </div>
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
                  <option value="bottom_right">Bottom Right (default)</option>
                </select>
              </div>
              <div>
                <label className="text-[11px] font-mono text-slate-400 mb-1 block">Scale ({(watermarkScale * 100).toFixed(0)}%)</label>
                <input type="range" min={3} max={30} value={watermarkScale * 100}
                  onChange={(e) => setWatermarkScale(Number(e.target.value) / 100)}
                  className="w-full accent-cyan-500 mt-1.5" />
              </div>
              <div className="col-span-2">
                <label className="text-[11px] font-mono text-slate-400 mb-1 block">Opacity ({(watermarkOpacity * 100).toFixed(0)}%)</label>
                <input type="range" min={10} max={100} value={watermarkOpacity * 100}
                  onChange={(e) => setWatermarkOpacity(Number(e.target.value) / 100)}
                  className="w-full accent-cyan-500" />
              </div>
            </div>
            <p className="text-[10px] font-mono text-slate-500">Logo and placement are included in saved profiles and renders.</p>
          </section>

          {/* Render Controls */}
          <section className="space-y-3 p-4 rounded-xl border border-border bg-surface">
            <h2 className="text-xs font-mono font-semibold text-slate-300 uppercase tracking-widest flex items-center gap-2">
              <Cpu className="w-4 h-4 text-orange-400" /> Render Clip
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
            <div className="text-[11px] font-mono text-slate-500 space-y-0.5">
              <div>Encoder: h264_nvenc → auto-fallback libx264</div>
              <div>Output: -fps_mode cfr · -movflags +faststart · AAC 128k</div>
            </div>
            <button
              onClick={handleRender}
              disabled={!activeProject || isRendering}
              className="w-full flex items-center justify-center gap-2 px-4 py-2 rounded-lg bg-orange-600 hover:bg-orange-500 text-white text-xs font-mono font-semibold transition-all disabled:opacity-50"
            >
              {isRendering ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Download className="w-3.5 h-3.5" />}
              {isRendering ? 'Rendering…' : `Render ${renderEndSec - renderStartSec}s Clip`}
            </button>

            {renderError && (
              <div className="p-2.5 rounded-lg bg-red-950 border border-red-800 text-xs font-mono text-red-300">
                {renderError}
              </div>
            )}

            {renderResult && (
              <div className="p-2.5 rounded-lg bg-emerald-950 border border-emerald-800 text-[11px] font-mono space-y-0.5">
                <div className="text-emerald-400 font-semibold flex items-center gap-1.5">
                  <CheckCircle2 className="w-3.5 h-3.5" /> Render Complete!
                </div>
                <div className="text-slate-400">Encoder: <span className="text-cyan-400">{renderResult.encoderUsed}</span></div>
                <div className="text-slate-400">File: <span className="text-slate-200 break-all">{renderResult.outputFilename}</span></div>
              </div>
            )}
          </section>

          {/* Saved Profiles */}
          <section className="space-y-3">
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

            {profiles.length === 0 ? (
              <p className="text-xs font-mono text-slate-500 italic">No saved profiles yet.</p>
            ) : (
              <div className="space-y-2">
                {profiles.map((profile) => (
                  <div
                    key={profile.id}
                    className="flex items-center justify-between p-3 rounded-lg bg-surface border border-border-subtle hover:border-border transition-all"
                  >
                    <div className="space-y-0.5">
                      <div className="text-xs font-mono font-semibold text-slate-200">{profile.name}</div>
                      <div className="text-[11px] font-mono text-slate-500">
                        {profile.framingMode} · {profile.aspectRatio} · {profile.layoutTemplate} · {profile.splitRatio}% split
                      </div>
                    </div>
                    <div className="flex items-center gap-2">
                      <button
                        onClick={() => handleLoadProfile(profile)}
                        className="px-2.5 py-1 text-[10px] font-mono rounded border border-cyan-700 text-cyan-400 hover:bg-cyan-950 transition-all flex items-center gap-1"
                      >
                        <Video className="w-3 h-3" /> Load
                      </button>
                      <button
                        onClick={() => handleDeleteProfile(profile.id)}
                        className="p-1.5 rounded border border-red-900 text-red-500 hover:bg-red-950 transition-all"
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
      </div>
    </div>
  );
};

export default LayoutStudio;
