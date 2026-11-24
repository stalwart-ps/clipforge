import React, { memo, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  Check,
  Download,
  Flame,
  Layers,
  Loader2,
  Palette,
  Play,
  RefreshCw,
  Save,
  Sparkles,
  Type,
  Wand2,
} from 'lucide-react';
import { api } from '../api/client';
import { useWorkspace } from '../context/WorkspaceContext';
import {
  AnimationStyle,
  CaptionConfig,
  CaptionPreset,
  FontSwitchMode,
  ProjectRead,
  ProjectSummary,
  TranscriptSegment,
  WordTimestamp,
} from '../types/project';

const PRESETS: Record<CaptionPreset, CaptionConfig> = {
  // Classic & Still Presets
  hormozi_pop: {
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
  },
  karaoke_highlight: {
    preset: 'karaoke_highlight',
    fontName: 'Arial',
    fontSize: 62,
    primaryColor: '#FFFFFF',
    highlightColor: '#52F59B',
    outlineColor: '#111111',
    outlineWidth: 3,
    shadowDepth: 1,
    shadowBlur: 0,
    shadowColor: '#000000',
    marginV: 140,
    positionYPercent: 80,
    maxWordsPerLine: 5,
    allCaps: false,
    animation: 'highlight',
    animationStyle: 'word_highlight',
    secondaryFont: 'Georgia',
    fontSwitchMode: 'none',
    secondaryItalic: true,
    glowEnabled: false,
    glowColor: '#00F5FF',
    glowIntensity: 12,
    letterSpacing: 0,
    profanityMask: false,
  },
  minimal_clean: {
    preset: 'minimal_clean',
    fontName: 'Arial',
    fontSize: 54,
    primaryColor: '#FFFFFF',
    highlightColor: '#FFFFFF',
    outlineColor: '#111111',
    outlineWidth: 1,
    shadowDepth: 2,
    shadowBlur: 0,
    shadowColor: '#000000',
    marginV: 110,
    positionYPercent: 82,
    maxWordsPerLine: 6,
    allCaps: false,
    animation: 'none',
    animationStyle: 'none',
    secondaryFont: 'Georgia',
    fontSwitchMode: 'none',
    secondaryItalic: true,
    glowEnabled: false,
    glowColor: '#00F5FF',
    glowIntensity: 12,
    letterSpacing: 0,
    profanityMask: false,
  },
  gaming_neon: {
    preset: 'gaming_neon',
    fontName: 'Arial Black',
    fontSize: 66,
    primaryColor: '#E7FCFF',
    highlightColor: '#00F5FF',
    outlineColor: '#E000FF',
    outlineWidth: 5,
    shadowDepth: 4,
    shadowBlur: 0,
    shadowColor: '#000000',
    marginV: 300,
    positionYPercent: 75,
    maxWordsPerLine: 4,
    allCaps: true,
    animation: 'bounce',
    animationStyle: 'glow_pulse',
    secondaryFont: 'Georgia',
    fontSwitchMode: 'none',
    secondaryItalic: true,
    glowEnabled: false,
    glowColor: '#00F5FF',
    glowIntensity: 12,
    letterSpacing: 0,
    profanityMask: false,
  },
  boxed_pill: {
    preset: 'boxed_pill',
    fontName: 'Arial',
    fontSize: 58,
    primaryColor: '#FFFFFF',
    highlightColor: '#FFE875',
    outlineColor: '#171717',
    outlineWidth: 2,
    shadowDepth: 1,
    shadowBlur: 0,
    shadowColor: '#000000',
    marginV: 130,
    positionYPercent: 80,
    maxWordsPerLine: 4,
    allCaps: false,
    animation: 'highlight',
    animationStyle: 'word_highlight',
    secondaryFont: 'Georgia',
    fontSwitchMode: 'none',
    secondaryItalic: true,
    glowEnabled: false,
    glowColor: '#00F5FF',
    glowIntensity: 12,
    letterSpacing: 0,
    profanityMask: false,
  },
  // 7 New Stylized & Animated Presets
  editorial_mix: {
    preset: 'editorial_mix',
    fontName: 'Bahnschrift',
    fontSize: 68,
    primaryColor: '#FFFFFF',
    highlightColor: '#FFD700',
    outlineColor: '#111111',
    outlineWidth: 3,
    shadowDepth: 2,
    shadowBlur: 2,
    shadowColor: '#000000',
    marginV: 180,
    positionYPercent: 80,
    maxWordsPerLine: 4,
    allCaps: false,
    animation: 'pop',
    animationStyle: 'pop_bounce',
    secondaryFont: 'Georgia',
    fontSwitchMode: 'active_word',
    secondaryItalic: true,
    glowEnabled: false,
    glowColor: '#FFD700',
    glowIntensity: 12,
    letterSpacing: 0,
    profanityMask: false,
  },
  cyber_neon_glow: {
    preset: 'cyber_neon_glow',
    fontName: 'Arial Black',
    fontSize: 68,
    primaryColor: '#FFFFFF',
    highlightColor: '#00F5FF',
    outlineColor: '#00F5FF',
    outlineWidth: 2.5,
    shadowDepth: 0,
    shadowBlur: 0,
    shadowColor: '#000000',
    marginV: 240,
    positionYPercent: 76,
    maxWordsPerLine: 4,
    allCaps: true,
    animation: 'highlight',
    animationStyle: 'glow_pulse',
    secondaryFont: 'Georgia',
    fontSwitchMode: 'none',
    secondaryItalic: false,
    glowEnabled: true,
    glowColor: '#00F5FF',
    glowIntensity: 14,
    letterSpacing: 1,
    profanityMask: false,
  },
  cinematic_blur: {
    preset: 'cinematic_blur',
    fontName: 'Trebuchet MS',
    fontSize: 56,
    primaryColor: '#FFFFFF',
    highlightColor: '#E2E8F0',
    outlineColor: '#0F172A',
    outlineWidth: 1.5,
    shadowDepth: 3,
    shadowBlur: 4,
    shadowColor: '#000000',
    marginV: 160,
    positionYPercent: 82,
    maxWordsPerLine: 5,
    allCaps: false,
    animation: 'none',
    animationStyle: 'blur_reveal',
    secondaryFont: 'Georgia',
    fontSwitchMode: 'none',
    secondaryItalic: false,
    glowEnabled: false,
    glowColor: '#00F5FF',
    glowIntensity: 12,
    letterSpacing: 2.5,
    profanityMask: false,
  },
  kinetic_impact: {
    preset: 'kinetic_impact',
    fontName: 'Impact',
    fontSize: 76,
    primaryColor: '#FFFFFF',
    highlightColor: '#FFE600',
    outlineColor: '#000000',
    outlineWidth: 5,
    shadowDepth: 4,
    shadowBlur: 0,
    shadowColor: '#000000',
    marginV: 200,
    positionYPercent: 78,
    maxWordsPerLine: 3,
    allCaps: true,
    animation: 'bounce',
    animationStyle: 'kinetic_tilt',
    secondaryFont: 'Georgia',
    fontSwitchMode: 'none',
    secondaryItalic: false,
    glowEnabled: false,
    glowColor: '#00F5FF',
    glowIntensity: 12,
    letterSpacing: 0.5,
    profanityMask: false,
  },
  slide_up_smooth: {
    preset: 'slide_up_smooth',
    fontName: 'Segoe UI',
    fontSize: 60,
    primaryColor: '#FFFFFF',
    highlightColor: '#38BDF8',
    outlineColor: '#0B0F19',
    outlineWidth: 2,
    shadowDepth: 2.5,
    shadowBlur: 2.5,
    shadowColor: '#000000',
    marginV: 160,
    positionYPercent: 80,
    maxWordsPerLine: 4,
    allCaps: false,
    animation: 'highlight',
    animationStyle: 'slide_up',
    secondaryFont: 'Georgia',
    fontSwitchMode: 'none',
    secondaryItalic: false,
    glowEnabled: false,
    glowColor: '#38BDF8',
    glowIntensity: 10,
    letterSpacing: 0.5,
    profanityMask: false,
  },
  highlighter_pill: {
    preset: 'highlighter_pill',
    fontName: 'Segoe UI',
    fontSize: 58,
    primaryColor: '#FFFFFF',
    highlightColor: '#FFE875',
    outlineColor: '#171717',
    outlineWidth: 2,
    shadowDepth: 1.5,
    shadowBlur: 1,
    shadowColor: '#000000',
    marginV: 140,
    positionYPercent: 80,
    maxWordsPerLine: 4,
    allCaps: false,
    animation: 'highlight',
    animationStyle: 'word_highlight',
    secondaryFont: 'Georgia',
    fontSwitchMode: 'none',
    secondaryItalic: false,
    glowEnabled: false,
    glowColor: '#FFE875',
    glowIntensity: 10,
    letterSpacing: 0,
    profanityMask: false,
  },
  typewriter_tech: {
    preset: 'typewriter_tech',
    fontName: 'Consolas',
    fontSize: 54,
    primaryColor: '#E6FFFA',
    highlightColor: '#10B981',
    outlineColor: '#042F2E',
    outlineWidth: 2.5,
    shadowDepth: 3,
    shadowBlur: 0,
    shadowColor: '#022C22',
    marginV: 150,
    positionYPercent: 82,
    maxWordsPerLine: 5,
    allCaps: false,
    animation: 'highlight',
    animationStyle: 'typewriter',
    secondaryFont: 'Consolas',
    fontSwitchMode: 'none',
    secondaryItalic: false,
    glowEnabled: false,
    glowColor: '#10B981',
    glowIntensity: 12,
    letterSpacing: 1.2,
    profanityMask: false,
  },
};

const CLASSIC_PRESETS: CaptionPreset[] = [
  'hormozi_pop',
  'karaoke_highlight',
  'minimal_clean',
  'gaming_neon',
  'boxed_pill',
];

const STYLIZED_PRESETS: CaptionPreset[] = [
  'editorial_mix',
  'cyber_neon_glow',
  'cinematic_blur',
  'kinetic_impact',
  'slide_up_smooth',
  'highlighter_pill',
  'typewriter_tech',
];

const PRESET_META: Record<
  CaptionPreset,
  { label: string; badge: string; desc: string; gradient: string }
> = {
  hormozi_pop: {
    label: 'Hormozi Pop',
    badge: 'POP BOLD',
    desc: 'Bold yellow pop with thick black outline',
    gradient: 'from-amber-500/20 to-yellow-500/10 border-amber-500/30',
  },
  karaoke_highlight: {
    label: 'Karaoke Highlight',
    badge: 'KARAOKE',
    desc: 'Emerald green sequential word fill',
    gradient: 'from-emerald-500/20 to-teal-500/10 border-emerald-500/30',
  },
  minimal_clean: {
    label: 'Minimal Clean',
    badge: 'CLEAN',
    desc: 'Crisp minimal white subtitle text',
    gradient: 'from-slate-500/20 to-slate-400/10 border-slate-500/30',
  },
  gaming_neon: {
    label: 'Gaming Neon',
    badge: 'ARCADE',
    desc: 'High-contrast magenta outline & cyan highlight',
    gradient: 'from-fuchsia-500/20 to-cyan-500/10 border-fuchsia-500/30',
  },
  boxed_pill: {
    label: 'Boxed Pill',
    badge: 'BOXED',
    desc: 'Translucent rounded background box',
    gradient: 'from-sky-500/20 to-blue-500/10 border-sky-500/30',
  },
  editorial_mix: {
    label: 'Editorial Mix',
    badge: 'EDITORIAL',
    desc: 'Sans base + Georgia italic gold emphasis words',
    gradient: 'from-amber-600/30 to-amber-900/20 border-amber-400/40',
  },
  cyber_neon_glow: {
    label: 'Cyber Neon Glow',
    badge: 'NEON GLOW',
    desc: 'True Layer 0 blurred cyan glow backing',
    gradient: 'from-cyan-500/30 to-blue-600/20 border-cyan-400/50',
  },
  cinematic_blur: {
    label: 'Cinematic Blur',
    badge: 'CINEMA',
    desc: 'Wide tracking & smooth blur-to-sharp reveal',
    gradient: 'from-indigo-500/25 to-purple-600/15 border-indigo-400/40',
  },
  kinetic_impact: {
    label: 'Kinetic Impact',
    badge: 'KINETIC',
    desc: 'Heavy tilted Impact font with snappy overshoot',
    gradient: 'from-red-600/25 to-yellow-600/15 border-red-500/40',
  },
  slide_up_smooth: {
    label: 'Slide Up Smooth',
    badge: 'SLIDE UP',
    desc: 'Soft shadow & upward fade glide',
    gradient: 'from-sky-500/25 to-teal-600/15 border-sky-400/40',
  },
  highlighter_pill: {
    label: 'Highlighter Pill',
    badge: 'PILL BOX',
    desc: 'Contrasting active word badge box highlight',
    gradient: 'from-lime-500/25 to-emerald-600/15 border-lime-400/40',
  },
  typewriter_tech: {
    label: 'Typewriter Tech',
    badge: 'CONSOLE',
    desc: 'Monospace terminal progressive word stream',
    gradient: 'from-emerald-600/30 to-teal-900/20 border-emerald-400/40',
  },
};

const POSITION_PRESETS = [
  { label: 'Top', val: 12 },
  { label: 'Upper-Mid', val: 28 },
  { label: 'Split Seam (Center)', val: 50 },
  { label: 'Lower-Third (Default)', val: 80 },
  { label: 'Bottom', val: 90 },
] as const;

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

const CaptionPreview = memo(function CaptionPreview({
  videoRef,
  projectId,
  time,
  segments,
  config,
  playTimeRef,
}: PreviewProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const words = useMemo(() => segments.flatMap((segment) => segment.words), [segments]);

  useEffect(() => {
    const video = videoRef.current;
    const canvas = canvasRef.current;
    const context = canvas?.getContext('2d');
    if (!canvas || !context) return;
    let frame = 0;
    let raf = 0;

    const isEmphasisWord = (text: string) => {
      const clean = text.replace(/[^\w]/g, '');
      return /\d/.test(clean) || clean.length >= 6 || (clean.length >= 3 && clean === clean.toUpperCase());
    };

    const draw = () => {
      const width = canvas.width;
      const height = canvas.height;
      const videoTime = video?.currentTime ?? playTimeRef.current;
      context.clearRect(0, 0, width, height);

      // 1. Draw video or fallback background
      if (video && video.readyState >= 2 && video.videoWidth > 0) {
        const scale = Math.max(width / video.videoWidth, height / video.videoHeight);
        const drawW = video.videoWidth * scale;
        const drawH = video.videoHeight * scale;
        context.drawImage(video, (width - drawW) / 2, (height - drawH) / 2, drawW, drawH);
      } else {
        context.fillStyle = '#0a0f18';
        context.fillRect(0, 0, width, height);
        context.fillStyle = '#64748b';
        context.font = '15px sans-serif';
        context.textAlign = 'center';
        context.fillText('Select a transcribed video to preview captions', width / 2, height / 2);
      }

      // Visual split seam guides
      context.save();
      context.setLineDash([4, 4]);
      context.strokeStyle = 'rgba(255, 255, 255, 0.12)';
      context.lineWidth = 1;
      context.beginPath();
      context.moveTo(0, height * 0.35);
      context.lineTo(width, height * 0.35);
      context.moveTo(0, height * 0.50);
      context.lineTo(width, height * 0.50);
      context.stroke();
      context.fillStyle = 'rgba(255, 255, 255, 0.3)';
      context.font = '10px monospace';
      context.textAlign = 'right';
      context.fillText('Split 35%', width - 8, height * 0.35 - 4);
      context.fillText('Center 50%', width - 8, height * 0.50 - 4);
      context.restore();

      // Find active word
      let active = -1;
      for (let i = 0; i < words.length; i += 1) {
        if (videoTime >= words[i].start && videoTime <= words[i].end) {
          active = i;
          break;
        }
      }

      if (active >= 0) {
        const groupSize = Math.max(1, config.maxWordsPerLine || 4);
        const first = Math.floor(active / groupSize) * groupSize;
        const group = words.slice(first, first + groupSize);
        const activeIdxInGroup = active - first;
        const previewScale = height / 1920;
        const baseFontSize = Math.max(14, (config.fontSize || 60) * previewScale);
        const elapsed = Math.max(0, videoTime - words[active].start);

        // Position math
        const posY =
          typeof config.positionYPercent === 'number'
            ? config.positionYPercent
            : Math.max(5, Math.min(95, 100 - ((config.marginV || 180) / 1920) * 100));
        const clampedYPercent = Math.max(8, Math.min(92, posY));
        const centerY = (clampedYPercent / 100) * height;

        // Animation dynamics
        let animOffsetY = 0;
        let animOpacity = 1.0;
        let animScale = 1.0;
        let animTiltAngle = 0;

        const animStyle = config.animationStyle || 'none';

        if (animStyle === 'slide_up') {
          const slideProgress = Math.min(1, elapsed / 0.15);
          animOffsetY = (1 - slideProgress) * 26 * previewScale;
          animOpacity = Math.min(1, elapsed / 0.12);
        } else if (animStyle === 'pop_bounce') {
          const popProgress = Math.min(1, elapsed / 0.17);
          animScale = popProgress < 0.5 ? 1 + (popProgress / 0.5) * 0.16 : 1 + (1 - (popProgress - 0.5) / 0.5) * 0.16;
        } else if (animStyle === 'kinetic_tilt') {
          const chunkIdx = Math.floor(first / groupSize);
          animTiltAngle = (chunkIdx % 2 === 0 ? -2.5 : 2.5) * (Math.PI / 180);
          const bounceProgress = Math.min(1, elapsed / 0.16);
          animScale = bounceProgress < 0.5 ? 0.95 + (bounceProgress / 0.5) * 0.18 : 1 + (1 - (bounceProgress - 0.5) / 0.5) * 0.14;
        } else if (animStyle === 'glow_pulse') {
          const pulseT = Math.min(1, elapsed / 0.20);
          animScale = 1 + (pulseT < 0.5 ? (pulseT / 0.5) * 0.10 : (1 - (pulseT - 0.5) / 0.5) * 0.10);
        } else if (config.animation === 'pop' || config.animation === 'bounce') {
          animScale = 1 + 0.14 * Math.max(0, 1 - elapsed / 0.2);
        }

        context.save();
        context.globalAlpha = animOpacity;
        context.translate(width / 2, centerY + animOffsetY);
        if (animTiltAngle !== 0) {
          context.rotate(animTiltAngle);
        }

        // Prepare words
        const shown = group.map((w) => {
          let str = config.profanityMask ? maskWord(w.word) : w.word;
          return config.allCaps ? str.toUpperCase() : str;
        });

        // Compute styling per word
        const isAlternateLine = config.fontSwitchMode === 'alternate_lines' && Math.floor(first / groupSize) % 2 === 1;
        const primaryFont = config.fontName || 'Arial';
        const secFont = config.secondaryFont || 'Georgia';
        const isBold = ['hormozi_pop', 'gaming_neon', 'cyber_neon_glow', 'kinetic_impact'].includes(config.preset);
        const fontWeight = isBold ? '900' : '700';

        // Measure text with fonts
        const wordFonts: string[] = [];
        const isWordItalic: boolean[] = [];
        const isWordHighlighted: boolean[] = [];

        shown.forEach((wordText, i) => {
          const isAct = i === activeIdxInGroup;
          const isEmph = config.fontSwitchMode === 'emphasis_words' && isEmphasisWord(wordText);
          const useSecFont = isAlternateLine || (isAct && config.fontSwitchMode === 'active_word') || isEmph;
          const fontFam = useSecFont ? secFont : primaryFont;
          const italic = (useSecFont && config.secondaryItalic) || false;
          wordFonts.push(`${italic ? 'italic ' : ''}${fontWeight} ${baseFontSize}px "${fontFam}", sans-serif`);
          isWordItalic.push(italic);
          isWordHighlighted.push(isAct);
        });

        // Measure widths
        const widths: number[] = [];
        shown.forEach((wordText, i) => {
          context.font = wordFonts[i];
          const w = context.measureText(`${wordText} `).width;
          widths.push(w);
        });
        const totalWidth = widths.reduce((sum, w) => sum + w, 0);

        // Boxed Pill or Highlighter Pill background
        if (config.preset === 'boxed_pill' || config.preset === 'highlighter_pill') {
          context.save();
          context.fillStyle = config.preset === 'highlighter_pill' ? 'rgba(15, 23, 42, 0.75)' : 'rgba(0, 0, 0, 0.6)';
          context.beginPath();
          context.roundRect(
            -totalWidth / 2 - 20,
            -baseFontSize * 0.8,
            totalWidth + 40,
            baseFontSize * 1.6,
            baseFontSize * 0.35
          );
          context.fill();
          if (config.preset === 'highlighter_pill') {
            context.strokeStyle = 'rgba(255, 232, 117, 0.4)';
            context.lineWidth = 1.5;
            context.stroke();
          }
          context.restore();
        }

        // DRAW LAYER 0: Neon Glow Backing (if enabled)
        if (config.glowEnabled) {
          context.save();
          let glowX = -totalWidth / 2;
          const glowColor = config.glowColor || '#00F5FF';
          const glowIntensity = (config.glowIntensity || 12) * previewScale;

          group.forEach((_, index) => {
            if (animStyle === 'typewriter' && index > activeIdxInGroup) return;

            const text = shown[index];
            const isAct = index === activeIdxInGroup;
            context.font = wordFonts[index];
            context.textAlign = 'left';
            context.textBaseline = 'middle';
            context.lineJoin = 'round';

            context.save();
            if (isAct && animScale !== 1) {
              const wordW = widths[index];
              context.translate(glowX + wordW / 2, 0);
              context.scale(animScale, animScale);
              context.translate(-(glowX + wordW / 2), 0);
            }

            // Glow blur
            context.shadowColor = glowColor;
            context.shadowBlur = glowIntensity * 2.5;
            context.strokeStyle = glowColor;
            context.lineWidth = glowIntensity * 1.5;
            context.strokeText(text, glowX, 0);
            context.restore();

            glowX += widths[index];
          });
          context.restore();
        }

        // DRAW LAYER 1: Foreground Crisp Text & Outline
        let x = -totalWidth / 2;
        group.forEach((_, index) => {
          if (animStyle === 'typewriter' && index > activeIdxInGroup) return;

          const text = shown[index];
          const isAct = index === activeIdxInGroup;
          context.font = wordFonts[index];
          context.textAlign = 'left';
          context.textBaseline = 'middle';
          context.lineJoin = 'round';

          context.save();
          if (isAct && animScale !== 1) {
            const wordW = widths[index];
            context.translate(x + wordW / 2, 0);
            context.scale(animScale, animScale);
            context.translate(-(x + wordW / 2), 0);
          }

          // Active word highlight box for highlighter_pill preset
          if (config.preset === 'highlighter_pill' && isAct) {
            context.fillStyle = config.highlightColor || '#FFE875';
            context.beginPath();
            context.roundRect(x - 4, -baseFontSize * 0.65, widths[index] - 4, baseFontSize * 1.3, 6);
            context.fill();
          }

          // Stroke & Shadow
          context.lineWidth = (config.outlineWidth ?? 2) * previewScale * 2;
          context.strokeStyle = isAct && config.preset === 'highlighter_pill' ? '#0F172A' : config.outlineColor || '#000000';
          context.shadowColor = config.shadowColor || 'rgba(0,0,0,.85)';
          const shadowBlur = (config.shadowBlur || 0) * previewScale * 2;
          context.shadowBlur = shadowBlur + (config.shadowDepth || 2) * previewScale * 1.5;
          context.shadowOffsetY = (config.shadowDepth || 2) * previewScale;
          context.shadowOffsetX = config.preset === 'kinetic_impact' ? (config.shadowDepth || 4) * previewScale : 0;
          context.strokeText(text, x, 0);

          // Fill text
          if (config.preset === 'highlighter_pill' && isAct) {
            context.fillStyle = '#0F172A'; // Contrasting text inside active pill
          } else {
            context.fillStyle = isAct ? config.highlightColor : config.primaryColor;
          }
          context.fillText(text, x, 0);
          context.restore();

          x += widths[index];
        });

        context.restore();
      }

      frame += 1;
      if (frame < 2 || (video && !video.paused && !video.ended)) {
        raf = requestAnimationFrame(draw);
      }
    };

    raf = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(raf);
  }, [videoRef, projectId, time, words, config, playTimeRef]);

  return (
    <canvas
      ref={canvasRef}
      width={720}
      height={1280}
      className="aspect-[9/16] w-full max-h-[72vh] rounded-xl border border-slate-700 bg-slate-950 object-contain shadow-2xl"
      aria-label="Live caption preview"
    />
  );
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

  useEffect(() => {
    setDraft(word.word);
    setStart(word.start);
    setEnd(word.end);
  }, [word.word, word.start, word.end]);

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
        onKeyDown={(event) => {
          if (event.key === 'Enter') event.currentTarget.blur();
        }}
        className="w-20 bg-transparent text-sm text-slate-100 outline-none"
      />
      <input
        type="number"
        min="0"
        step="0.01"
        value={start}
        onChange={(event) => setStart(Number(event.target.value))}
        aria-label="Word start time"
        className="w-[4.4rem] bg-transparent text-[10px] font-mono text-slate-400 outline-none"
      />
      <input
        type="number"
        min="0"
        step="0.01"
        value={end}
        onChange={(event) => setEnd(Number(event.target.value))}
        aria-label="Word end time"
        className="w-[4.4rem] bg-transparent text-[10px] font-mono text-slate-400 outline-none"
      />
    </div>
  );
});

interface TranscriptEditorProps {
  segments: TranscriptSegment[];
  onCommit: WordInputProps['onCommit'];
  saving: boolean;
  saved: boolean;
}

const CaptionTranscriptEditor = memo(function CaptionTranscriptEditor({
  segments,
  onCommit,
  saving,
  saved,
}: TranscriptEditorProps) {
  const [scrollTop, setScrollTop] = useState(0);
  const flat = useMemo(
    () =>
      segments.flatMap((segment, segmentIndex) =>
        segment.words.map((word, wordIndex) => ({ word, segmentIndex, wordIndex }))
      ),
    [segments]
  );
  const itemHeight = 52;
  const visibleCount = 30;
  const start = Math.max(0, Math.floor(scrollTop / itemHeight) - 3);
  const visible = flat.slice(start, start + visibleCount);

  return (
    <section className="rounded-xl border border-slate-800 bg-slate-900/60">
      <div className="flex items-center justify-between border-b border-slate-800 px-4 py-3">
        <div>
          <h2 className="text-sm font-semibold text-slate-100">Word transcript</h2>
          <p className="mt-1 text-xs text-slate-400">
            Edit a word, then leave the field to save it and refresh the .ass file.
          </p>
        </div>
        <span className="inline-flex items-center gap-1 text-xs text-slate-400" aria-live="polite">
          {saving ? (
            <>
              <Loader2 className="h-3.5 w-3.5 animate-spin" /> Saving
            </>
          ) : saved ? (
            <>
              <Check className="h-3.5 w-3.5 text-emerald-400" /> Saved
            </>
          ) : (
            'Autosave on'
          )}
        </span>
      </div>
      {flat.length === 0 ? (
        <p className="p-4 text-sm text-slate-400">This transcript has no word timestamps.</p>
      ) : (
        <div
          className="h-[420px] overflow-auto p-3"
          onScroll={(event) => setScrollTop(event.currentTarget.scrollTop)}
        >
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
  const [fonts, setFonts] = useState<string[]>([
    'Arial',
    'Arial Black',
    'Bahnschrift',
    'Consolas',
    'Georgia',
    'Impact',
    'Segoe UI',
    'Times New Roman',
    'Trebuchet MS',
    'Verdana',
  ]);
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

  const selectProject = useCallback(
    async (id: string) => {
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
        if (videoRef.current) {
          videoRef.current.pause();
          videoRef.current.load();
        }
        if (wsConfig && wsConfig.captionConfig && Object.keys(wsConfig.captionConfig).length > 0) {
          setConfig((current) => ({
            ...current,
            ...(wsConfig.captionConfig as CaptionConfig),
          }));
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Select a project with a transcript');
      }
    },
    [setActiveProjectId]
  );

  useEffect(() => {
    Promise.all([
      api.listProjects(),
      api.getCaptionFonts().catch(() => [
        'Arial',
        'Arial Black',
        'Bahnschrift',
        'Consolas',
        'Georgia',
        'Impact',
        'Segoe UI',
        'Times New Roman',
        'Trebuchet MS',
        'Verdana',
      ]),
    ])
      .then(([items, availableFonts]) => {
        setProjects(items);
        if (availableFonts.length) {
          const combined = Array.from(
            new Set([
              ...availableFonts,
              'Arial',
              'Arial Black',
              'Bahnschrift',
              'Consolas',
              'Georgia',
              'Impact',
              'Segoe UI',
              'Times New Roman',
              'Trebuchet MS',
              'Verdana',
            ])
          ).sort();
          setFonts(combined);
        }
        const preferredId = activeProjectId || items[0]?.id;
        if (preferredId) {
          selectProject(preferredId);
        }
      })
      .catch((err: unknown) =>
        setError(err instanceof Error ? err.message : 'Could not load caption studio data')
      );
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
      api
        .patchWorkspaceConfig(project.id, {
          captionConfig: config as unknown as Record<string, unknown>,
        })
        .catch(console.error);
    }, 800);
    return () => window.clearTimeout(timer);
  }, [project?.id, config]);

  const commitWord = useCallback(
    (segmentIndex: number, wordIndex: number, patch: Partial<WordTimestamp>) => {
      const projectId = projectIdRef.current;
      if (!projectId) return;
      const next = segmentsRef.current.map((segment, index) =>
        index !== segmentIndex
          ? segment
          : {
              ...segment,
              words: segment.words.map((word, indexWord) =>
                indexWord === wordIndex ? { ...word, ...patch } : word
              ),
            }
      );
      segmentsRef.current = next;
      setSegments(next);
      setSaving(true);
      setSaved(false);
      const currentConfig = configRef.current;
      saveQueue.current = saveQueue.current
        .catch(() => undefined)
        .then(() => api.updateCaptionTranscript(projectId, next, currentConfig));
      saveQueue.current
        .then(() => {
          setSaving(false);
          setSaved(true);
          setNotice('Transcript and .ass captions saved');
        })
        .catch((err: unknown) => {
          setSaving(false);
          setError(err instanceof Error ? err.message : 'Could not save transcript');
        });
    },
    []
  );

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
    } finally {
      setBusy(false);
    }
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
    } finally {
      setRendering(false);
    }
  };

  const currentPosY =
    typeof config.positionYPercent === 'number'
      ? config.positionYPercent
      : Math.max(5, Math.min(95, Math.round(100 - ((config.marginV || 180) / 1920) * 100)));

  const handlePositionChange = (val: number) => {
    const clampedVal = Math.max(5, Math.min(95, val));
    const marginV =
      clampedVal < 35
        ? Math.max(10, Math.round((clampedVal / 100) * 1920))
        : Math.max(10, Math.round(((100 - clampedVal) / 100) * 1920));

    setConfig((current) => ({
      ...current,
      positionYPercent: clampedVal,
      marginV,
    }));
  };

  const setPreset = (preset: CaptionPreset) => {
    const p = PRESETS[preset] || PRESETS.hormozi_pop;
    setConfig({
      ...p,
      positionYPercent: config.positionYPercent ?? p.positionYPercent ?? 80,
      profanityMask: config.profanityMask,
    });
  };

  const patchSlider =
    <
      K extends
        | 'fontSize'
        | 'outlineWidth'
        | 'shadowDepth'
        | 'shadowBlur'
        | 'glowIntensity'
        | 'letterSpacing'
        | 'marginV'
        | 'maxWordsPerLine',
    >(
      key: K,
      min: number,
      max: number
    ) =>
    (event: React.ChangeEvent<HTMLInputElement>) =>
      updateConfig(key, Math.max(min, Math.min(max, Number(event.target.value))) as CaptionConfig[K]);

  const togglePlayback = () => {
    if (!videoRef.current) return;
    if (videoRef.current.paused) void videoRef.current.play();
    else videoRef.current.pause();
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
          <p className="mt-1 text-sm text-slate-400">
            Style, animate, and preview high-engagement word captions with mixed fonts, neon glow, and precise timing.
          </p>
        </div>
        <label className="min-w-64 text-xs text-slate-400">
          Project
          <select
            value={project?.id ?? ''}
            onChange={(event) => event.target.value && void selectProject(event.target.value)}
            className="mt-1 block w-full rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-white focus:border-cyan-500 outline-none"
          >
            <option value="">Choose a transcribed project</option>
            {projects
              .filter((item) => item.hasTranscript)
              .map((item) => (
                <option value={item.id} key={item.id}>
                  {item.title}
                </option>
              ))}
          </select>
        </label>
      </header>

      {error && (
        <div role="alert" className="rounded-lg border border-rose-900 bg-rose-950/50 px-4 py-3 text-sm text-rose-200">
          {error}
        </div>
      )}
      {notice && (
        <div
          role="status"
          className="rounded-lg border border-emerald-900 bg-emerald-950/40 px-4 py-3 text-sm text-emerald-200"
        >
          {notice}
        </div>
      )}

      <div className="grid gap-6 xl:grid-cols-[minmax(320px,0.85fr)_minmax(500px,1.15fr)]">
        {/* Left column: Live Preview & Player Controls */}
        <section className="space-y-3">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-semibold flex items-center gap-1.5">
              <Sparkles className="h-4 w-4 text-cyan-400" /> Live Preview
            </h2>
            <span className="font-mono text-xs text-slate-400">{videoTime.toFixed(2)}s</span>
          </div>

          <div className="mx-auto max-w-[360px]">
            <CaptionPreview
              videoRef={videoRef}
              projectId={videoReady ? project?.id ?? null : null}
              time={videoTime}
              segments={segments}
              config={debouncedConfig}
              playTimeRef={playTimeRef}
            />
          </div>

          {project && (
            <video
              ref={videoRef}
              src={api.getVideoStreamUrl(project.id)}
              className="sr-only"
              preload="metadata"
              onLoadedData={() => setVideoReady(true)}
              onTimeUpdate={handleTimeUpdate}
            />
          )}

          <div className="flex items-center gap-3">
            <button
              type="button"
              onClick={togglePlayback}
              disabled={!project}
              className="inline-flex items-center gap-2 rounded-md bg-cyan-600 px-3 py-2 text-xs font-semibold text-white hover:bg-cyan-500 disabled:opacity-50"
            >
              <Play className="h-4 w-4" /> Play
            </button>
            <input
              type="range"
              min={0}
              max={project?.durationSec ?? 0}
              step={0.05}
              value={Math.min(videoTime, project?.durationSec ?? 0)}
              onChange={(event) => {
                const value = Number(event.target.value);
                playTimeRef.current = value;
                setVideoTime(value);
                if (videoRef.current) videoRef.current.currentTime = value;
              }}
              className="min-w-0 flex-1 accent-cyan-500"
              aria-label="Preview position"
            />
          </div>

          <div className="flex flex-wrap gap-2 pt-1">
            <button
              type="button"
              onClick={() => void generateAss()}
              disabled={!project || busy}
              className="inline-flex items-center gap-2 rounded-md bg-violet-600 px-3 py-2 text-xs font-semibold text-white hover:bg-violet-500 disabled:opacity-50 shadow-sm"
            >
              {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Wand2 className="h-4 w-4" />} Generate .ass
            </button>
            {project && (
              <a
                href={api.getCaptionsUrl(project.id)}
                download
                className="inline-flex items-center gap-2 rounded-md border border-slate-700 bg-slate-800/80 px-3 py-2 text-xs text-slate-200 hover:bg-slate-700"
              >
                <Download className="h-4 w-4" /> Download .ass
              </a>
            )}
            <button
              type="button"
              onClick={() => void renderCaptions()}
              disabled={!project || rendering}
              className="inline-flex items-center gap-2 rounded-md border border-cyan-700 bg-cyan-950/60 px-3 py-2 text-xs text-cyan-200 hover:bg-cyan-900/60 disabled:opacity-50"
            >
              {rendering ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />} Burn captions into MP4
            </button>
          </div>
        </section>

        {/* Right column: Preset Selector & Mix-and-Match Customizer */}
        <section className="space-y-5 rounded-xl border border-slate-800 bg-slate-900/50 p-4 sm:p-5">
          <div className="flex items-start justify-between gap-3">
            <div>
              <h2 className="text-sm font-semibold text-slate-100 flex items-center gap-2">
                <Palette className="h-4 w-4 text-cyan-400" /> Caption Presets & Styles
              </h2>
              <p className="mt-0.5 text-xs text-slate-400">
                Choose a base template or customize any animation, font-switching, or glow effect below.
              </p>
            </div>
            <button
              type="button"
              onClick={() => setPreset(config.preset)}
              className="inline-flex items-center gap-1 text-xs text-slate-400 hover:text-white"
            >
              <RefreshCw className="h-3.5 w-3.5" /> Reset preset
            </button>
          </div>

          {/* PRESETS ORGANIZED INTO TWO GROUPS */}
          <div className="space-y-4">
            {/* 1. Stylized & Animated Templates */}
            <div>
              <span className="text-[11px] font-mono uppercase tracking-wider text-cyan-400 font-semibold flex items-center gap-1.5 mb-2">
                <Flame className="h-3.5 w-3.5 text-cyan-400" /> Stylized & Animated Templates (New)
              </span>
              <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
                {STYLIZED_PRESETS.map((presetKey) => {
                  const meta = PRESET_META[presetKey];
                  const isSelected = config.preset === presetKey;
                  return (
                    <button
                      key={presetKey}
                      type="button"
                      onClick={() => setPreset(presetKey)}
                      className={`relative flex flex-col justify-between p-2.5 rounded-lg border text-left transition-all ${
                        isSelected
                          ? 'border-cyan-400 bg-cyan-950/80 shadow-md ring-1 ring-cyan-400/50'
                          : 'border-slate-800 bg-slate-900/70 hover:border-slate-700 hover:bg-slate-800/60'
                      }`}
                    >
                      <div className="flex items-center justify-between gap-1 mb-1">
                        <span className="text-xs font-semibold text-white leading-tight">{meta.label}</span>
                        <span className="text-[9px] font-mono font-bold px-1.5 py-0.5 rounded bg-cyan-900/60 text-cyan-300 border border-cyan-700/60 shrink-0">
                          {meta.badge}
                        </span>
                      </div>
                      <p className="text-[10px] text-slate-400 leading-snug line-clamp-2">{meta.desc}</p>
                    </button>
                  );
                })}
              </div>
            </div>

            {/* 2. Classic & Still Templates */}
            <div>
              <span className="text-[11px] font-mono uppercase tracking-wider text-slate-400 font-semibold flex items-center gap-1.5 mb-2">
                <Layers className="h-3.5 w-3.5 text-slate-400" /> Classic & Still Templates
              </span>
              <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
                {CLASSIC_PRESETS.map((presetKey) => {
                  const meta = PRESET_META[presetKey];
                  const isSelected = config.preset === presetKey;
                  return (
                    <button
                      key={presetKey}
                      type="button"
                      onClick={() => setPreset(presetKey)}
                      className={`relative flex flex-col justify-between p-2 rounded-lg border text-left transition-all ${
                        isSelected
                          ? 'border-cyan-400 bg-cyan-950/80 shadow-md ring-1 ring-cyan-400/50'
                          : 'border-slate-800 bg-slate-900/50 hover:border-slate-700 hover:bg-slate-800/40'
                      }`}
                    >
                      <div className="flex items-center justify-between gap-1 mb-1">
                        <span className="text-xs font-semibold text-slate-200">{meta.label}</span>
                        <span className="text-[9px] font-mono px-1 rounded bg-slate-800 text-slate-400 border border-slate-700">
                          {meta.badge}
                        </span>
                      </div>
                      <p className="text-[10px] text-slate-400 leading-snug line-clamp-1">{meta.desc}</p>
                    </button>
                  );
                })}
              </div>
            </div>
          </div>

          {/* DEDICATED CONTROLS SECTION */}
          <div className="space-y-4 pt-2 border-t border-slate-800/80">
            {/* 1. Animation Style Selector */}
            <div className="rounded-xl bg-slate-950/70 p-3.5 border border-slate-800 space-y-2">
              <div className="flex items-center justify-between">
                <label className="text-xs font-semibold text-slate-200 flex items-center gap-1.5">
                  <Wand2 className="h-3.5 w-3.5 text-cyan-400" /> Animation Style
                </label>
                <span className="text-[11px] font-mono text-cyan-400">
                  {config.animationStyle || 'none'}
                </span>
              </div>
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-1.5">
                {(
                  [
                    { id: 'none', label: 'None (Still)' },
                    { id: 'pop_bounce', label: 'Pop Bounce' },
                    { id: 'slide_up', label: 'Slide Up' },
                    { id: 'blur_reveal', label: 'Blur Reveal' },
                    { id: 'word_highlight', label: 'Word Highlight' },
                    { id: 'typewriter', label: 'Typewriter' },
                    { id: 'kinetic_tilt', label: 'Kinetic Tilt' },
                    { id: 'glow_pulse', label: 'Glow Pulse' },
                  ] as const
                ).map((item) => {
                  const isSelected = (config.animationStyle || 'none') === item.id;
                  return (
                    <button
                      key={item.id}
                      type="button"
                      onClick={() => updateConfig('animationStyle', item.id as AnimationStyle)}
                      className={`px-2 py-1.5 rounded-md border text-xs font-medium text-center transition-all ${
                        isSelected
                          ? 'border-cyan-500 bg-cyan-950 text-cyan-300 font-semibold shadow-sm'
                          : 'border-slate-800 bg-slate-900/60 text-slate-300 hover:border-slate-700'
                      }`}
                    >
                      {item.label}
                    </button>
                  );
                })}
              </div>
            </div>

            {/* 2. Font Switching & Mixed Fonts */}
            <div className="rounded-xl bg-slate-950/70 p-3.5 border border-slate-800 space-y-3">
              <div className="flex items-center justify-between">
                <span className="text-xs font-semibold text-slate-200 flex items-center gap-1.5">
                  <Type className="h-3.5 w-3.5 text-cyan-400" /> Font Switching & Mixed Typography
                </span>
                <span className="text-[10px] font-mono text-slate-400">
                  Mode: {config.fontSwitchMode || 'none'}
                </span>
              </div>
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                <label className="text-xs text-slate-400">
                  Primary Font
                  <select
                    value={config.fontName}
                    onChange={(event) => updateConfig('fontName', event.target.value)}
                    className="mt-1 block w-full rounded-md border border-slate-700 bg-slate-900 px-2 py-1.5 text-xs text-white outline-none focus:border-cyan-500"
                  >
                    {fonts.map((f) => (
                      <option key={`p-${f}`} value={f}>
                        {f}
                      </option>
                    ))}
                  </select>
                </label>

                <label className="text-xs text-slate-400">
                  Secondary (Accent) Font
                  <select
                    value={config.secondaryFont || 'Georgia'}
                    onChange={(event) => updateConfig('secondaryFont', event.target.value)}
                    className="mt-1 block w-full rounded-md border border-slate-700 bg-slate-900 px-2 py-1.5 text-xs text-white outline-none focus:border-cyan-500"
                  >
                    {fonts.map((f) => (
                      <option key={`s-${f}`} value={f}>
                        {f}
                      </option>
                    ))}
                  </select>
                </label>

                <label className="text-xs text-slate-400">
                  Font Switch Mode
                  <select
                    value={config.fontSwitchMode || 'none'}
                    onChange={(event) => updateConfig('fontSwitchMode', event.target.value as FontSwitchMode)}
                    className="mt-1 block w-full rounded-md border border-slate-700 bg-slate-900 px-2 py-1.5 text-xs text-white outline-none focus:border-cyan-500"
                  >
                    <option value="none">Off (Single Font)</option>
                    <option value="active_word">Active Word</option>
                    <option value="emphasis_words">Emphasis Words (6+ chars/digits)</option>
                    <option value="alternate_lines">Alternate Lines</option>
                  </select>
                </label>
              </div>

              <div className="flex flex-wrap items-center justify-between gap-3 pt-1">
                <label className="flex items-center gap-2 text-xs text-slate-300 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={config.secondaryItalic ?? true}
                    onChange={(e) => updateConfig('secondaryItalic', e.target.checked)}
                    className="accent-cyan-500 rounded"
                  />
                  <span>Italicize accent/secondary font words</span>
                </label>
                <div className="flex items-center gap-3">
                  <span className="text-xs text-slate-400">Letter Spacing: {config.letterSpacing || 0}px</span>
                  <input
                    type="range"
                    min={0}
                    max={6}
                    step={0.5}
                    value={config.letterSpacing || 0}
                    onChange={patchSlider('letterSpacing', 0, 6)}
                    className="w-24 accent-cyan-500"
                  />
                </div>
              </div>
            </div>

            {/* 3. Glow & Shadow Controls */}
            <div className="rounded-xl bg-slate-950/70 p-3.5 border border-slate-800 space-y-3">
              <div className="flex items-center justify-between">
                <span className="text-xs font-semibold text-slate-200 flex items-center gap-1.5">
                  <Sparkles className="h-3.5 w-3.5 text-cyan-400" /> Neon Glow & Shadow Depth
                </span>
                <label className="flex items-center gap-2 text-xs font-medium text-cyan-300 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={config.glowEnabled || false}
                    onChange={(e) => updateConfig('glowEnabled', e.target.checked)}
                    className="accent-cyan-500 rounded"
                  />
                  <span>Enable Layer 0 Glow Backing</span>
                </label>
              </div>

              {config.glowEnabled && (
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 p-2.5 rounded-lg bg-cyan-950/30 border border-cyan-900/40">
                  <label className="flex items-center justify-between text-xs text-slate-300">
                    <span>Glow Color</span>
                    <input
                      type="color"
                      value={config.glowColor || '#00F5FF'}
                      onChange={(e) => updateConfig('glowColor', e.target.value)}
                      className="h-7 w-12 rounded border border-slate-700 bg-transparent cursor-pointer"
                    />
                  </label>
                  <label className="text-xs text-slate-300 space-y-1 block">
                    <div className="flex justify-between">
                      <span>Glow Intensity / Radius</span>
                      <span className="text-cyan-400 font-mono">{config.glowIntensity || 12}px</span>
                    </div>
                    <input
                      type="range"
                      min={4}
                      max={30}
                      step={1}
                      value={config.glowIntensity || 12}
                      onChange={patchSlider('glowIntensity', 4, 30)}
                      className="w-full accent-cyan-500"
                    />
                  </label>
                </div>
              )}

              <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 pt-1">
                <label className="text-xs text-slate-400 space-y-1 block">
                  <div className="flex justify-between">
                    <span>Shadow Depth</span>
                    <span className="text-cyan-400 font-mono">{config.shadowDepth}</span>
                  </div>
                  <input
                    type="range"
                    min={0}
                    max={8}
                    step={0.5}
                    value={config.shadowDepth}
                    onChange={patchSlider('shadowDepth', 0, 8)}
                    className="w-full accent-cyan-500"
                  />
                </label>

                <label className="text-xs text-slate-400 space-y-1 block">
                  <div className="flex justify-between">
                    <span>Shadow Blur</span>
                    <span className="text-cyan-400 font-mono">{config.shadowBlur || 0}</span>
                  </div>
                  <input
                    type="range"
                    min={0}
                    max={12}
                    step={0.5}
                    value={config.shadowBlur || 0}
                    onChange={patchSlider('shadowBlur', 0, 12)}
                    className="w-full accent-cyan-500"
                  />
                </label>

                <label className="flex items-center justify-between text-xs text-slate-300">
                  <span>Shadow Color</span>
                  <input
                    type="color"
                    value={config.shadowColor || '#000000'}
                    onChange={(e) => updateConfig('shadowColor', e.target.value)}
                    className="h-7 w-12 rounded border border-slate-700 bg-transparent cursor-pointer"
                  />
                </label>
              </div>
            </div>

            {/* 4. Vertical Position Controls */}
            <div className="rounded-xl bg-slate-950/70 p-3.5 border border-slate-800 space-y-2.5">
              <div className="flex items-center justify-between">
                <div>
                  <span className="text-xs font-mono font-semibold text-slate-200 block">Vertical Position</span>
                  <span className="text-[10px] font-mono text-slate-500">
                    {currentPosY < 35 ? 'Top Anchor (Alignment 8)' : 'Bottom Anchor (Alignment 2)'} · MarginV:{' '}
                    {config.marginV}px
                  </span>
                </div>
                <span className="text-xs font-mono font-bold text-cyan-400 bg-cyan-950/80 px-2 py-0.5 rounded border border-cyan-800">
                  {currentPosY}% from top
                </span>
              </div>

              <div className="grid grid-cols-5 gap-1.5">
                {POSITION_PRESETS.map((p) => {
                  const isSelected = Math.abs(currentPosY - p.val) <= 2;
                  return (
                    <button
                      key={p.label}
                      type="button"
                      onClick={() => handlePositionChange(p.val)}
                      className={`px-1 py-1.5 rounded-lg border text-[10px] font-mono text-center transition-all ${
                        isSelected
                          ? 'border-cyan-500 text-cyan-300 bg-cyan-950/90 font-bold shadow-sm'
                          : 'border-slate-800 text-slate-400 hover:border-slate-700 bg-slate-900/60'
                      }`}
                    >
                      {p.label}
                    </button>
                  );
                })}
              </div>

              <div className="pt-1">
                <input
                  type="range"
                  min={5}
                  max={95}
                  step={1}
                  value={currentPosY}
                  onChange={(e) => handlePositionChange(Number(e.target.value))}
                  className="w-full accent-cyan-500 cursor-pointer"
                />
                <div className="flex justify-between text-[10px] font-mono text-slate-500 pt-1">
                  <span>5% (Top)</span>
                  <span>28% (Upper-Mid)</span>
                  <span>50% (Split Seam)</span>
                  <span>80% (Lower-Third)</span>
                  <span>95% (Bottom)</span>
                </div>
              </div>
            </div>

            {/* 5. Typography Size, Colors, Outlines, Words Per Line */}
            <div className="grid grid-cols-2 sm:grid-cols-3 gap-3 pt-2">
              <label className="text-xs text-slate-400">
                Font size <span className="text-cyan-300">{config.fontSize}px</span>
                <input
                  type="range"
                  min={24}
                  max={120}
                  value={config.fontSize}
                  onChange={patchSlider('fontSize', 24, 120)}
                  className="mt-2 block w-full accent-cyan-500"
                />
              </label>

              <label className="text-xs text-slate-400">
                Words per line · {config.maxWordsPerLine}
                <input
                  type="range"
                  min={1}
                  max={8}
                  value={config.maxWordsPerLine}
                  onChange={patchSlider('maxWordsPerLine', 1, 8)}
                  className="mt-2 block w-full accent-cyan-500"
                />
              </label>

              <label className="text-xs text-slate-400">
                Outline width <span className="text-cyan-300">{config.outlineWidth}</span>
                <input
                  type="range"
                  min={0}
                  max={12}
                  step={0.5}
                  value={config.outlineWidth}
                  onChange={patchSlider('outlineWidth', 0, 12)}
                  className="mt-2 block w-full accent-cyan-500"
                />
              </label>

              <label className="flex items-center justify-between text-xs text-slate-300">
                <span>Text color</span>
                <input
                  type="color"
                  value={config.primaryColor}
                  onChange={(event) => updateConfig('primaryColor', event.target.value)}
                  className="h-8 w-10 rounded border border-slate-700 bg-transparent cursor-pointer"
                />
              </label>

              <label className="flex items-center justify-between text-xs text-slate-300">
                <span>Active word</span>
                <input
                  type="color"
                  value={config.highlightColor}
                  onChange={(event) => updateConfig('highlightColor', event.target.value)}
                  className="h-8 w-10 rounded border border-slate-700 bg-transparent cursor-pointer"
                />
              </label>

              <label className="flex items-center justify-between text-xs text-slate-300">
                <span>Outline color</span>
                <input
                  type="color"
                  value={config.outlineColor}
                  onChange={(event) => updateConfig('outlineColor', event.target.value)}
                  className="h-8 w-10 rounded border border-slate-700 bg-transparent cursor-pointer"
                />
              </label>
            </div>

            <div className="flex flex-wrap items-center gap-6 pt-2 text-xs text-slate-300">
              <label className="flex items-center gap-2 cursor-pointer">
                <input
                  type="checkbox"
                  checked={config.allCaps}
                  onChange={(event) => updateConfig('allCaps', event.target.checked)}
                  className="accent-cyan-500 rounded"
                />
                <span>ALL CAPS</span>
              </label>

              <label className="flex items-center gap-2 cursor-pointer">
                <input
                  type="checkbox"
                  checked={config.profanityMask}
                  onChange={(event) => updateConfig('profanityMask', event.target.checked)}
                  className="accent-cyan-500 rounded"
                />
                <span>Mask profanity</span>
              </label>
            </div>
          </div>
        </section>
      </div>

      <CaptionTranscriptEditor segments={segments} onCommit={commitWord} saving={saving} saved={saved} />
    </div>
  );
};

export default CaptionStudio;
