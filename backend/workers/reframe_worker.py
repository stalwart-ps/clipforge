"""Phase 6 — Isolated Per-Frame Dynamic Reframer -> FFmpeg Pipe Worker.

2-Pass Shot-Locked + Sub-Pixel Smoothed Reframing:
- Pass 1: Fast Shot & Trajectory Analysis (Zero full-frame buffering).
  * 160x90 thumbnail HSV histogram correlation (< 0.65 = hard scene cut).
  * Dual-range MediaPipe face detection (models 0 and 1) on frame 0, cuts, and every 4th frame.
  * Consistent model 0 / high-confidence prioritization on IoU > 0.35 deduplication.
  * Early release of VideoCapture and MediaPipe detectors to drop RAM.
- Between Passes: Shot-Level Stabilization & Zero-Phase Smoothing.
  * Contiguous shot partitioning with spurious cut (< 6 frames) merging.
  * Dual layout voting (2_person, 1_person, 0_person) per shot.
  * Locked crop scale (w, h) per shot via median face size (zero zoom breathing).
  * 3-sample median filter for outlier rejection.
  * Tripod deadzone lock (< 0.06 spread -> 100% constant static camera).
  * Zero-phase Gaussian smoothing (radius=12) + max velocity clamp (<= 0.006/frame) for genuine motion.
  * Gaming mode step-locked holds with HSV webcam histogram correlation (>= 0.30).
- Pass 2: Sub-Pixel Rendering & FFmpeg Pipe.
  * cv2.warpAffine floating-point crop-and-scale matrix (eliminates 1px staircase shake).
  * Streaming BGR24 into FFmpeg stdin with audio concatenation, 20ms afade, loudnorm, watermark, and .ass captions.
  * NVENC (h264_nvenc) with automatic fallback to libx264.
  * Stderr background drain thread and continuous PROGRESS:<percent> (0-25% Pass 1, 25-100% Pass 2).
"""

from __future__ import annotations

import argparse
import collections
import functools
import gc
import json
import logging
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import threading

# Ensure backend root is on sys.path
backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

import cv2
import numpy as np

# Limit OpenCV threads so OpenCV, FFmpeg decode, and libass do not thrash CPU
cv2.setNumThreads(max(2, (os.cpu_count() or 4) - 2))

try:
    from backend.workers.face_engine import FaceEngine
except ImportError:
    from workers.face_engine import FaceEngine


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helper: IoU Deduplication
# ---------------------------------------------------------------------------
def compute_iou(box_a: dict, box_b: dict) -> float:
    """Compute Intersection over Union (IoU) for two normalized boxes {x, y, w, h}."""
    ax1, ay1 = float(box_a["x"]), float(box_a["y"])
    ax2, ay2 = ax1 + float(box_a["w"]), ay1 + float(box_a["h"])

    bx1, by1 = float(box_b["x"]), float(box_b["y"])
    bx2, by2 = bx1 + float(box_b["w"]), by1 + float(box_b["h"])

    ix1 = max(ax1, bx1)
    iy1 = max(ay1, by1)
    ix2 = min(ax2, bx2)
    iy2 = min(ay2, by2)

    inter_w = max(0.0, ix2 - ix1)
    inter_h = max(0.0, iy2 - iy1)
    inter_area = inter_w * inter_h

    area_a = float(box_a["w"]) * float(box_a["h"])
    area_b = float(box_b["w"]) * float(box_b["h"])
    union_area = area_a + area_b - inter_area
    if union_area <= 0.0:
        return 0.0
    return inter_area / union_area


def deduplicate_faces(candidates: list[dict], iou_threshold: float = 0.35) -> list[dict]:
    """Deduplicate face detections, consistently preferring model_selection=0 and higher confidence."""
    # Sort: model 0 preferred first, then highest score
    candidates.sort(key=lambda f: (1 if f.get("model", 1) == 0 else 0, f.get("score", 0.0)), reverse=True)
    kept: list[dict] = []
    for cand in candidates:
        if any(compute_iou(cand, k) > iou_threshold for k in kept):
            continue
        kept.append(cand)
    return kept


# ---------------------------------------------------------------------------
# Helper: Zero-Phase Gaussian Smoothing & Median Filtering
# ---------------------------------------------------------------------------
def median_filter_1d(arr: np.ndarray, size: int = 3) -> np.ndarray:
    """Apply a 3-sample median filter to remove single-frame MediaPipe outliers."""
    n = len(arr)
    if n < size:
        return np.copy(arr)
    p_prev = np.pad(arr, (1, 0), mode="edge")[:-1]
    p_next = np.pad(arr, (0, 1), mode="edge")[1:]
    stack = np.stack([p_prev, arr, p_next], axis=0)
    return np.median(stack, axis=0)


def zero_phase_gaussian_smooth(
    arr: np.ndarray,
    radius: int = 12,
    max_vel: float = 0.006,
) -> np.ndarray:
    """Zero-phase Gaussian moving average with edge reflection padding and max velocity clamp."""
    n = len(arr)
    if n <= 1:
        return np.copy(arr)

    r = min(radius, n - 1)
    if r < 1:
        return np.copy(arr)

    sigma = max(1.0, r / 2.0)
    x = np.arange(-r, r + 1)
    kernel = np.exp(-0.5 * (x / sigma) ** 2)
    kernel /= kernel.sum()

    padded = np.pad(arr, r, mode="reflect")
    smoothed = np.convolve(padded, kernel, mode="valid")

    # Velocity clamp (<= 0.006 of frame dimension per frame)
    clamped = np.empty_like(smoothed)
    clamped[0] = smoothed[0]
    for i in range(1, n):
        delta = smoothed[i] - clamped[i - 1]
        clamped[i] = clamped[i - 1] + np.clip(delta, -max_vel, max_vel)

    return clamped


# ---------------------------------------------------------------------------
# Helper: Sub-Pixel Floating-Point Rendering with cv2.warpAffine
# ---------------------------------------------------------------------------
def subpixel_render_pane(
    frame: np.ndarray,
    box: dict,
    target_w: int,
    target_h: int,
    fit_mode: str = "fill",
    head_bias: bool = True,
) -> np.ndarray:
    """Single floating-point cv2.warpAffine crop-and-scale matrix mapping directly to target dimensions.

    Eliminates all 1px staircase shake and integer rounding artifacts.
    """
    src_h, src_w = frame.shape[:2]
    target_w = max(2, int(target_w)) & ~1
    target_h = max(2, int(target_h)) & ~1
    target_ar = target_w / target_h

    src_x = float(box["x"]) * src_w
    src_y = float(box["y"]) * src_h
    src_bw = max(1.0, float(box["w"]) * src_w)
    src_bh = max(1.0, float(box["h"]) * src_h)

    if fit_mode == "fill":
        src_ar = src_bw / src_bh
        if src_ar > target_ar:
            # Crop sides horizontally
            cropped_w = src_bh * target_ar
            src_x += (src_bw - cropped_w) / 2.0
            src_bw = cropped_w
        else:
            # Crop vertically with upper head-bias
            cropped_h = src_bw / target_ar
            bias = 0.20 if head_bias else 0.50
            src_y += (src_bh - cropped_h) * bias
            src_bh = cropped_h

        scale_x = target_w / src_bw
        scale_y = target_h / src_bh
        m = np.array(
            [
                [scale_x, 0.0, -scale_x * src_x],
                [0.0, scale_y, -scale_y * src_y],
            ],
            dtype=np.float32,
        )
        return cv2.warpAffine(
            frame,
            m,
            (target_w, target_h),
            flags=cv2.INTER_LINEAR,
            borderMode=cv2.BORDER_REPLICATE,
        )
    else:
        # Fit mode: letterbox / pillarbox with black padding
        scale = min(target_w / src_bw, target_h / src_bh)
        dst_w = src_bw * scale
        dst_h = src_bh * scale
        dst_x0 = (target_w - dst_w) / 2.0
        dst_y0 = (target_h - dst_h) / 2.0

        m = np.array(
            [
                [scale, 0.0, dst_x0 - scale * src_x],
                [0.0, scale, dst_y0 - scale * src_y],
            ],
            dtype=np.float32,
        )
        return cv2.warpAffine(
            frame,
            m,
            (target_w, target_h),
            flags=cv2.INTER_LINEAR,
            borderMode=cv2.BORDER_CONSTANT,
            borderValue=(0, 0, 0),
        )


def fast_render_pane(
    frame: np.ndarray,
    box: dict,
    target_w: int,
    target_h: int,
    fit_mode: str = "fill",
    head_bias: bool = True,
) -> np.ndarray:
    """Fast integer crop-and-resize for stationary / tripod-locked panes.

    Uses integer slice + cv2.resize(..., interpolation=cv2.INTER_LINEAR),
    which is 5-10x faster than cv2.warpAffine on static crops.
    """
    src_h, src_w = frame.shape[:2]
    target_w = max(2, int(target_w)) & ~1
    target_h = max(2, int(target_h)) & ~1
    target_ar = target_w / target_h

    src_x = float(box["x"]) * src_w
    src_y = float(box["y"]) * src_h
    src_bw = max(1.0, float(box["w"]) * src_w)
    src_bh = max(1.0, float(box["h"]) * src_h)

    if fit_mode == "fill":
        src_ar = src_bw / src_bh
        if src_ar > target_ar:
            cropped_w = src_bh * target_ar
            src_x += (src_bw - cropped_w) / 2.0
            src_bw = cropped_w
        else:
            cropped_h = src_bw / target_ar
            bias = 0.20 if head_bias else 0.50
            src_y += (src_bh - cropped_h) * bias
            src_bh = cropped_h

        ix1 = max(0, min(src_w - 1, int(round(src_x))))
        iy1 = max(0, min(src_h - 1, int(round(src_y))))
        ix2 = max(ix1 + 2, min(src_w, int(round(src_x + src_bw))))
        iy2 = max(iy1 + 2, min(src_h, int(round(src_y + src_bh))))

        crop = frame[iy1:iy2, ix1:ix2]
        return cv2.resize(crop, (target_w, target_h), interpolation=cv2.INTER_LINEAR)
    else:
        scale = min(target_w / src_bw, target_h / src_bh)
        dst_w = max(2, int(round(src_bw * scale))) & ~1
        dst_h = max(2, int(round(src_bh * scale))) & ~1
        dst_x0 = (target_w - dst_w) // 2
        dst_y0 = (target_h - dst_h) // 2

        ix1 = max(0, min(src_w - 1, int(round(src_x))))
        iy1 = max(0, min(src_h - 1, int(round(src_y))))
        ix2 = max(ix1 + 2, min(src_w, int(round(src_x + src_bw))))
        iy2 = max(iy1 + 2, min(src_h, int(round(src_y + src_bh))))

        crop = frame[iy1:iy2, ix1:ix2]
        resized = cv2.resize(crop, (dst_w, dst_h), interpolation=cv2.INTER_LINEAR)
        canvas = np.zeros((target_h, target_w, 3), dtype=np.uint8)
        canvas[dst_y0:dst_y0 + dst_h, dst_x0:dst_x0 + dst_w] = resized
        return canvas


def render_pane(
    frame: np.ndarray,
    box: dict,
    target_w: int,
    target_h: int,
    fit_mode: str = "fill",
    head_bias: bool = True,
    is_static: bool = False,
) -> np.ndarray:
    """Render pane using fast slice + resize if static, or subpixel warpAffine if panning."""
    if is_static:
        return fast_render_pane(frame, box, target_w, target_h, fit_mode=fit_mode, head_bias=head_bias)
    return subpixel_render_pane(frame, box, target_w, target_h, fit_mode=fit_mode, head_bias=head_bias)


def render_blurred_background(
    frame: np.ndarray,
    target_w: int,
    target_h: int,
) -> np.ndarray:
    """Render 1/8 downscaled and blurred background scaled to target canvas.

    Downscales source frame to 1/8 size (e.g. 135x240 for 1080x1920), applies a tiny (15, 15)
    GaussianBlur on that small image, and upscales to out_w x out_h—cutting Pass 2 CPU load dramatically.
    """
    src_h, src_w = frame.shape[:2]
    target_w = max(2, int(target_w)) & ~1
    target_h = max(2, int(target_h)) & ~1

    bg_w = max(16, (src_w // 8) & ~1)
    bg_h = max(16, (src_h // 8) & ~1)
    small = cv2.resize(frame, (bg_w, bg_h), interpolation=cv2.INTER_AREA)
    small_blur = cv2.GaussianBlur(small, (15, 15), 0)
    return subpixel_render_pane(small_blur, {"x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0}, target_w, target_h, fit_mode="fill", head_bias=False)


def render_blurred_fill(
    frame: np.ndarray,
    target_w: int,
    target_h: int,
    fg_box: dict | None = None,
) -> np.ndarray:
    """Render a fast cinematic blurred background with foreground centered."""
    bg = render_blurred_background(frame, target_w, target_h)
    src_h, src_w = frame.shape[:2]
    target_w = max(2, int(target_w)) & ~1
    target_h = max(2, int(target_h)) & ~1

    box = fg_box or {"x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0}
    scale = min(target_w / (float(box["w"]) * src_w), target_h / (float(box["h"]) * src_h))
    dst_w = max(2, int(float(box["w"]) * src_w * scale)) & ~1
    dst_h = max(2, int(float(box["h"]) * src_h * scale)) & ~1
    off_x = (target_w - dst_w) // 2
    off_y = (target_h - dst_h) // 2

    fg_patch = fast_render_pane(frame, box, dst_w, dst_h, fit_mode="fill", head_bias=False)
    bg[off_y:off_y + dst_h, off_x:off_x + dst_w] = fg_patch
    return bg


# ---------------------------------------------------------------------------
# Helpers: FFprobe Video Probe & Frame-Accurate FFmpeg CFR Segment Decoder
# ---------------------------------------------------------------------------
def probe_video(video_path: str) -> tuple[int, int, float]:
    """Probe source (src_w, src_h) and target constant fps once via ffprobe.

    Clamps to a clean standard CFR like 30.0 or min(60.0, round(src_fps, 3)).
    """
    ffprobe_bin = shutil.which("ffprobe") or "ffprobe"
    cmd = [
        ffprobe_bin,
        "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height,r_frame_rate,avg_frame_rate",
        "-of", "json",
        str(video_path),
    ]
    src_w, src_h, src_fps = 1920, 1080, 30.0
    probed = False
    try:
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
        data = json.loads(res.stdout)
        streams = data.get("streams", [])
        if streams:
            s = streams[0]
            src_w = int(s.get("width", 1920))
            src_h = int(s.get("height", 1080))
            fps_str = s.get("r_frame_rate") or s.get("avg_frame_rate") or "30/1"
            if "/" in fps_str:
                num, den = fps_str.split("/", 1)
                den_f = float(den)
                if den_f > 0:
                    src_fps = float(num) / den_f
            else:
                src_fps = float(fps_str)
            probed = True
    except Exception as e:
        logger.warning("ffprobe probe failed: %s, falling back to cv2.VideoCapture", e)

    if not probed:
        cap_info = cv2.VideoCapture(video_path)
        if cap_info.isOpened():
            src_w = int(cap_info.get(cv2.CAP_PROP_FRAME_WIDTH)) or 1920
            src_h = int(cap_info.get(cv2.CAP_PROP_FRAME_HEIGHT)) or 1080
            c_fps = cap_info.get(cv2.CAP_PROP_FPS) or 30.0
            if c_fps > 0:
                src_fps = c_fps
            cap_info.release()

    if src_fps <= 0.0 or src_fps > 120.0:
        target_fps = 30.0
    else:
        target_fps = min(60.0, round(src_fps, 3))
        if abs(target_fps - 30.0) < 0.05:
            target_fps = 30.0
        elif abs(target_fps - 60.0) < 0.05:
            target_fps = 60.0

    return src_w, src_h, target_fps


def fetch_frame_at_ts(video_path: str, ts: float, w: int, h: int) -> np.ndarray | None:
    """Read a single frame at timestamp ts using FFmpeg."""
    ffmpeg_bin = shutil.which("ffmpeg") or "ffmpeg"
    cmd = [
        ffmpeg_bin,
        "-hide_banner",
        "-loglevel", "error",
        "-ss", f"{max(0.0, ts):.6f}",
        "-i", str(video_path),
        "-frames:v", "1",
        "-s", f"{w}x{h}",
        "-f", "rawvideo",
        "-pix_fmt", "bgr24",
        "pipe:1",
    ]
    try:
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=5.0)
        expected_bytes = w * h * 3
        if len(res.stdout) >= expected_bytes:
            return np.frombuffer(res.stdout[:expected_bytes], dtype=np.uint8).reshape((h, w, 3))
    except Exception:
        pass
    try:
        cap = cv2.VideoCapture(video_path)
        if cap.isOpened():
            cap.set(cv2.CAP_PROP_POS_MSEC, max(0.0, ts) * 1000.0)
            ret, frame = cap.read()
            cap.release()
            if ret and frame is not None:
                return frame
    except Exception:
        pass
    return None


@functools.lru_cache(maxsize=16)
def can_use_cuda_decode(video_path: str) -> bool:
    """Fast 1-frame test to check if FFmpeg NVIDIA NVDEC (-hwaccel cuda) works on this video."""
    ffmpeg_bin = shutil.which("ffmpeg") or "ffmpeg"
    cmd = [
        ffmpeg_bin,
        "-hide_banner",
        "-loglevel", "error",
        "-hwaccel", "cuda",
        "-i", str(video_path),
        "-frames:v", "1",
        "-f", "null",
        "-",
    ]
    try:
        res = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=5.0,
        )
        return res.returncode == 0
    except Exception:
        return False


def decode_segment_frames(
    video_path: str,
    seg_start: float,
    seg_dur: float,
    target_fps: float,
    decode_w: int,
    decode_h: int,
    use_cuda: bool | None = None,
):
    """Decode exact expected_frames from video segment using FFmpeg CFR rawvideo pipe.

    Guarantees 100% frame-accurate A/V sync.
    If decoder ends early, repeats the last frame until expected_frames is emitted.
    If decoder outputs extra frames, stops cleanly at expected_frames and terminates cleanly.
    """
    ffmpeg_bin = shutil.which("ffmpeg") or "ffmpeg"
    expected_frames = max(1, int(round(seg_dur * target_fps)))
    frame_bytes = decode_w * decode_h * 3

    vf = f"fps={target_fps:.6f},scale={decode_w}:{decode_h}"

    if use_cuda is None:
        use_cuda = can_use_cuda_decode(video_path)

    hw_args = ["-hwaccel", "cuda"] if use_cuda else []

    cmd = [
        ffmpeg_bin,
        "-hide_banner",
        "-loglevel", "error",
        *hw_args,
        "-ss", f"{seg_start:.6f}",
        "-t", f"{seg_dur:.6f}",
        "-i", str(video_path),
        "-vf", vf,
        "-f", "rawvideo",
        "-pix_fmt", "bgr24",
        "pipe:1",
    ]

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        bufsize=frame_bytes * 4,
    )

    last_frame: np.ndarray | None = None
    frames_emitted = 0

    assert proc.stdout is not None
    try:
        while frames_emitted < expected_frames:
            raw = proc.stdout.read(frame_bytes)
            if len(raw) < frame_bytes:
                break
            frame = np.frombuffer(raw, dtype=np.uint8).reshape((decode_h, decode_w, 3))
            last_frame = frame
            frames_emitted += 1
            yield frame

        if frames_emitted < expected_frames:
            if last_frame is None:
                last_frame = np.zeros((decode_h, decode_w, 3), dtype=np.uint8)
            while frames_emitted < expected_frames:
                frames_emitted += 1
                yield last_frame.copy()

    finally:
        try:
            if proc.stdout:
                proc.stdout.close()
            if proc.stderr:
                proc.stderr.close()
        except Exception:
            pass
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()


# ---------------------------------------------------------------------------
# Helper: Sizing Calculation for Head-Safe Framing
# ---------------------------------------------------------------------------
def calculate_crop_scale(
    med_fh: float,
    pane_w: int,
    pane_h: int,
    src_w: int,
    src_h: int,
    coverage: float = 3.8,
) -> tuple[float, float]:
    """Calculate constant (w, h) matching pane aspect ratio proportional to median face height."""
    pane_ar = pane_w / max(1, pane_h)
    src_ar = src_w / max(1, src_h)

    target_h = max(0.40, min(0.96, med_fh * coverage))
    target_w = target_h * (pane_ar / src_ar)
    if target_w > 1.0:
        target_w = 1.0
        target_h = target_w / (pane_ar / src_ar)
    return round(target_w, 5), round(target_h, 5)


# ---------------------------------------------------------------------------
# Audio Stream & Loudnorm Helpers
# ---------------------------------------------------------------------------
def resolve_primary_audio_index(video_path: str) -> int:
    """Inspect all audio streams and return the 0-based relative audio stream index (0, 1, 2... for a:{idx}).

    - Prefers stream with disposition.default == 1 (if multiple have default, prefer tags.language starting with 'en', else first default).
    - Falls back to 0 if none is marked default or if ffprobe fails.
    """
    try:
        ffprobe_bin = shutil.which("ffprobe") or "ffprobe"
        cmd = [
            ffprobe_bin,
            "-hide_banner",
            "-v", "error",
            "-show_streams",
            "-select_streams", "a",
            "-print_format", "json",
            str(video_path),
        ]
        res = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=10,
        )
        if res.returncode != 0 or not res.stdout.strip():
            return 0
        data = json.loads(res.stdout)
        audio_streams = data.get("streams", [])
        if not audio_streams:
            return 0

        default_indices: list[int] = []
        for idx, stream in enumerate(audio_streams):
            if stream.get("codec_type") and stream.get("codec_type") != "audio":
                continue
            disp = stream.get("disposition") or {}
            val = disp.get("default")
            if val == 1 or val is True or str(val) == "1":
                default_indices.append(idx)

        if not default_indices:
            return 0

        if len(default_indices) == 1:
            return default_indices[0]

        for idx in default_indices:
            tags = audio_streams[idx].get("tags") or {}
            lang = str(tags.get("language") or "").strip().lower()
            if lang.startswith("en"):
                return idx

        return default_indices[0]
    except Exception:
        return 0


def measure_loudnorm(
    video_path: str,
    intervals: list[tuple[float, float]],
    audio_idx: int = 0,
) -> dict[str, str] | None:
    """Run a fast audio-only FFmpeg null pass to measure loudnorm stats.

    Returns dict with input_i, input_tp, input_lra, input_thresh, target_offset if all
    measured values are valid finite numbers, else None.
    """
    try:
        ffmpeg_bin = shutil.which("ffmpeg") or "ffmpeg"
        cmd = [ffmpeg_bin, "-hide_banner", "-y"]

        for seg_start, seg_end in intervals:
            seg_dur = max(0.001, seg_end - seg_start)
            cmd += [
                "-vn", "-sn", "-dn",
                "-ss", f"{seg_start:.6f}",
                "-t", f"{seg_dur + 1.0:.6f}",
                "-i", str(video_path),
            ]

        filter_parts: list[str] = []
        for k, (seg_start, seg_end) in enumerate(intervals):
            dur = max(0.001, seg_end - seg_start)
            fade_str = ""
            if dur > 0.20 and len(intervals) > 1:
                fades = []
                if k > 0:
                    fades.append("afade=t=in:st=0:d=0.010")
                fade_out_st = max(0.0, dur - 0.015)
                fades.append(f"afade=t=out:st={fade_out_st:.3f}:d=0.015")
                fade_str = "," + ",".join(fades)

            filter_parts.append(
                f"[{k}:a:{audio_idx}]atrim=start=0:duration={dur:.6f},"
                f"asetpts=PTS-STARTPTS,aresample=48000:async=1:first_pts=0{fade_str}[a{k}]"
            )

        if len(intervals) > 1:
            concat_inputs = "".join(f"[a{k}]" for k in range(len(intervals)))
            filter_parts.append(f"{concat_inputs}concat=n={len(intervals)}:v=0:a=1[srca_raw]")
            a_cur = "[srca_raw]"
        else:
            filter_parts.append("[a0]anull[srca_raw]")
            a_cur = "[srca_raw]"

        filter_parts.append(f"{a_cur}loudnorm=I=-14:TP=-1.5:LRA=11:print_format=json[aout]")
        cmd += ["-filter_complex", ";".join(filter_parts), "-map", "[aout]", "-f", "null", "-"]

        res = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=15,
        )
        if res.returncode != 0 and not res.stderr:
            return None

        stderr = res.stderr or ""
        last_open = stderr.rfind("{")
        last_close = stderr.rfind("}")
        if last_open == -1 or last_close == -1 or last_close <= last_open:
            return None

        parsed = json.loads(stderr[last_open : last_close + 1])
        required_keys = ("input_i", "input_tp", "input_lra", "input_thresh", "target_offset")
        if not all(k in parsed for k in required_keys):
            return None

        vals: dict[str, str] = {}
        for k in required_keys:
            raw_val = float(parsed[k])
            if not math.isfinite(raw_val):
                return None
            vals[k] = f"{raw_val:.2f}"
        return vals
    except Exception as exc:
        logger.warning("Loudnorm measurement failed or timed out: %s", exc)
        return None


# ---------------------------------------------------------------------------
# FFmpeg Command Builder
# ---------------------------------------------------------------------------
def build_ffmpeg_cmd(
    video_path: str,
    output_path: str,
    intervals: list[tuple[float, float]],
    out_w: int,
    out_h: int,
    fps: float,
    encoder: str,
    normalize: bool,
    has_audio: bool,
    ass_path: str | None,
    watermark_path: str | None,
    watermark_config: dict | None = None,
    cwd: str | None = None,
    audio_idx: int | None = None,
    measured_loudnorm: dict | None = None,
) -> list[str]:
    """Assemble FFmpeg CLI invocation for piped raw YUV420P input and audio/subtitle muxing."""
    ffmpeg_bin = shutil.which("ffmpeg") or "ffmpeg"
    cmd = [ffmpeg_bin, "-hide_banner", "-y"]

    out_w = max(2, int(out_w)) & ~1
    out_h = max(2, int(out_h)) & ~1

    cmd += [
        "-f", "rawvideo",
        "-vcodec", "rawvideo",
        "-pix_fmt", "yuv420p",
        "-s", f"{out_w}x{out_h}",
        "-r", f"{fps:.6f}",
        "-i", "pipe:0",
    ]

    if has_audio:
        if audio_idx is None:
            audio_idx = resolve_primary_audio_index(video_path)

        for seg_start, seg_end in intervals:
            seg_dur = max(0.001, seg_end - seg_start)
            cmd += [
                "-vn", "-sn", "-dn",
                "-ss", f"{seg_start:.6f}",
                "-t", f"{seg_dur + 1.0:.6f}",
                "-i", str(video_path),
            ]

    wm_idx = None
    if watermark_path and Path(watermark_path).is_file():
        wm_idx = 1 + len(intervals) if has_audio else 1
        cmd += ["-i", watermark_path]

    filter_parts: list[str] = []

    v_cur = "[0:v]"
    if wm_idx is not None:
        wm_cfg = watermark_config or {}
        wm_scale = max(0.01, min(1.0, float(wm_cfg.get("scale", 0.1))))
        wm_opacity = max(0.0, min(1.0, float(wm_cfg.get("opacity", 0.8))))
        corner = wm_cfg.get("corner", "bottom_right")
        margin = 20

        if corner == "top_left":
            wm_x, wm_y = f"{margin}", f"{margin}"
        elif corner == "top_right":
            wm_x, wm_y = f"main_w-overlay_w-{margin}", f"{margin}"
        elif corner == "bottom_left":
            wm_x, wm_y = f"{margin}", f"main_h-overlay_h-{margin}"
        else:
            wm_x, wm_y = f"main_w-overlay_w-{margin}", f"main_h-overlay_h-{margin}"

        filter_parts.append(
            f"[{wm_idx}:v]scale={out_w}*{wm_scale}:-1,format=argb,geq='p(X,Y)':a='{wm_opacity}*alpha(X,Y)'[wm];"
            f"{v_cur}[wm]overlay={wm_x}:{wm_y}[v_wm]"
        )
        v_cur = "[v_wm]"

    if ass_path:
        ass_file = Path(ass_path)
        if cwd and (Path(cwd) / ass_file.name).is_file():
            clean_ass = ass_file.name
        else:
            clean_ass = str(ass_path).replace("\\", "/")
            if ":" in clean_ass:
                clean_ass = clean_ass.replace(":", r"\:")
            clean_ass = clean_ass.replace("'", r"\'")

        fonts_dir = backend_dir / "assets" / "fonts"
        if fonts_dir.is_dir() and any(fonts_dir.glob("*.[to]tf")):
            clean_fonts = str(fonts_dir).replace("\\", "/")
            if ":" in clean_fonts:
                clean_fonts = clean_fonts.replace(":", r"\:")
            clean_fonts = clean_fonts.replace("'", r"\'")
            filter_parts.append(f"{v_cur}ass='{clean_ass}':fontsdir='{clean_fonts}'[v_final]")
        else:
            filter_parts.append(f"{v_cur}ass='{clean_ass}'[v_final]")
    else:
        filter_parts.append(f"{v_cur}null[v_final]")

    if has_audio:
        for k, (seg_start, seg_end) in enumerate(intervals):
            dur = max(0.001, seg_end - seg_start)
            fade_str = ""
            if dur > 0.20 and len(intervals) > 1:
                fades = []
                if k > 0:
                    fades.append("afade=t=in:st=0:d=0.010")
                fade_out_st = max(0.0, dur - 0.015)
                fades.append(f"afade=t=out:st={fade_out_st:.3f}:d=0.015")
                fade_str = "," + ",".join(fades)

            filter_parts.append(
                f"[{k + 1}:a:{audio_idx}]atrim=start=0:duration={dur:.6f},"
                f"asetpts=PTS-STARTPTS,aresample=48000:async=1:first_pts=0{fade_str}[a{k}]"
            )

        if len(intervals) > 1:
            concat_inputs = "".join(f"[a{k}]" for k in range(len(intervals)))
            filter_parts.append(f"{concat_inputs}concat=n={len(intervals)}:v=0:a=1[srca_raw]")
            a_cur = "[srca_raw]"
        else:
            filter_parts.append("[a0]anull[srca_raw]")
            a_cur = "[srca_raw]"

        if normalize:
            if measured_loudnorm is None:
                measured_loudnorm = measure_loudnorm(video_path, intervals, audio_idx)
            if measured_loudnorm and all(
                k in measured_loudnorm for k in ("input_i", "input_tp", "input_lra", "input_thresh", "target_offset")
            ):
                mi = measured_loudnorm["input_i"]
                mtp = measured_loudnorm["input_tp"]
                mlra = measured_loudnorm["input_lra"]
                mthresh = measured_loudnorm["input_thresh"]
                offset = measured_loudnorm["target_offset"]
                filter_parts.append(
                    f"{a_cur}loudnorm=I=-14:TP=-1.5:LRA=11:"
                    f"measured_I={mi}:measured_TP={mtp}:measured_LRA={mlra}:"
                    f"measured_thresh={mthresh}:offset={offset}:linear=true:print_format=summary,"
                    f"aresample=48000:async=1:first_pts=0[aout]"
                )
            else:
                filter_parts.append(f"{a_cur}alimiter=limit=0.95,aresample=48000:async=1:first_pts=0[aout]")
        else:
            filter_parts.append(f"{a_cur}aresample=48000:async=1:first_pts=0[aout]")

    cmd += ["-filter_complex", ";".join(filter_parts)]

    total_duration = sum(max(0.001, e - s) for s, e in intervals)
    cmd += ["-t", f"{total_duration:.6f}"]

    cmd += ["-map", "[v_final]"]
    if encoder == "h264_nvenc":
        cmd += ["-c:v", "h264_nvenc", "-preset", "p4", "-rc", "vbr", "-cq", "21", "-b:v", "0", "-pix_fmt", "yuv420p"]
    else:
        cmd += ["-c:v", "libx264", "-crf", "18", "-preset", "fast", "-pix_fmt", "yuv420p"]

    if has_audio:
        cmd += ["-map", "[aout]", "-c:a", "aac", "-b:a", "192k", "-ar", "48000"]
    else:
        cmd += ["-an"]

    cmd += ["-avoid_negative_ts", "make_zero", "-fps_mode", "cfr", "-sn", "-movflags", "+faststart", output_path]
    return cmd


build_ffmpeg_pipe_cmd = build_ffmpeg_cmd


# ---------------------------------------------------------------------------
# Helper: Room Fingerprint for 4-State Smart Overlay Lock (Step A)
# ---------------------------------------------------------------------------
def capture_room_fingerprint(
    video_path: str,
    facecam_box: dict,
    start_sec: float,
    reference_time_sec: float,
    src_w: int,
    src_h: int,
    face_engine: FaceEngine | None = None,
) -> dict:
    """Extract reference crop and construct outer-ring Room Fingerprint alongside ArcFace streamer embedding."""
    fx = float(facecam_box.get("x", 0.0))
    fy = float(facecam_box.get("y", 0.0))
    fw = float(facecam_box.get("w", 0.30))
    fh = float(facecam_box.get("h", 0.25))

    candidate_ts = [
        float(start_sec),
        float(reference_time_sec),
        float(start_sec) + 2.0,
        float(start_sec) + 10.0,
    ]
    seen_ts = set()
    valid_ts = []
    for ts in candidate_ts:
        c = max(0.0, round(ts, 3))
        if c not in seen_ts:
            seen_ts.add(c)
            valid_ts.append(c)

    chosen_frame: np.ndarray | None = None
    ref_face_h = 0.45 * fh
    ref_offset_x = 0.5 * fw
    ref_offset_y = 0.35 * fh
    streamer_embedding: np.ndarray | None = None

    for ts in valid_ts:
        frame = fetch_frame_at_ts(video_path, ts, src_w, src_h)
        if frame is None:
            continue

        if face_engine is not None:
            faces = face_engine.detect(frame, input_size=(640, 640), score_thresh=0.32)
            inside = [
                f for f in faces
                if fx <= f["cx"] <= fx + fw and fy <= f["cy"] <= fy + fh
            ]
            if inside:
                best_f = max(inside, key=lambda f: f["w"] * f["h"])
                ref_face_h = float(best_f["h"])
                ref_offset_x = float(best_f["cx"]) - fx
                ref_offset_y = float(best_f["cy"]) - fy
                streamer_embedding = face_engine.get_embedding(frame, best_f["kps"])
                chosen_frame = frame
                break

    # If no face found in candidate frames, fall back to reference_time_sec or start_sec
    if chosen_frame is None:
        frame = fetch_frame_at_ts(video_path, max(0.0, float(reference_time_sec)), src_w, src_h)
        if frame is None:
            frame = fetch_frame_at_ts(video_path, max(0.0, float(start_sec)), src_w, src_h)
        if frame is not None:
            chosen_frame = frame
            if face_engine is not None and streamer_embedding is None:
                faces = face_engine.detect(frame, input_size=(640, 640), score_thresh=0.32)
                inside = [f for f in faces if fx <= f["cx"] <= fx + fw and fy <= f["cy"] <= fy + fh]
                if inside:
                    best_f = max(inside, key=lambda f: f["w"] * f["h"])
                    ref_face_h = float(best_f["h"])
                    ref_offset_x = float(best_f["cx"]) - fx
                    ref_offset_y = float(best_f["cy"]) - fy
                    streamer_embedding = face_engine.get_embedding(frame, best_f["kps"])
        else:
            chosen_frame = np.zeros((src_h, src_w, 3), dtype=np.uint8)

    px1 = max(0, min(src_w - 1, int(fx * src_w)))
    py1 = max(0, min(src_h - 1, int(fy * src_h)))
    px2 = max(px1 + 4, min(src_w, int((fx + fw) * src_w)))
    py2 = max(py1 + 4, min(src_h, int((fy + fh) * src_h)))
    ref_crop = chosen_frame[py1:py2, px1:px2]

    tpl_w = 64
    crop_h, crop_w = ref_crop.shape[:2]
    aspect = max(0.1, crop_w / max(1, crop_h))
    tpl_h = max(16, int(round(tpl_w / aspect)))

    tpl_bgr = cv2.resize(ref_crop, (tpl_w, tpl_h), interpolation=cv2.INTER_AREA)

    # Inverted-U Static Mask: inner moving person (x: 20%..80%, y: 22%..95%)
    mask = np.ones((tpl_h, tpl_w), dtype=np.uint8) * 255
    mx1 = int(round(0.20 * tpl_w))
    mx2 = int(round(0.80 * tpl_w))
    my1 = int(round(0.22 * tpl_h))
    my2 = int(round(0.95 * tpl_h))
    mask[my1:my2, mx1:mx2] = 0

    tpl_hsv = cv2.cvtColor(tpl_bgr, cv2.COLOR_BGR2HSV)
    ref_hist = cv2.calcHist([tpl_hsv], [0, 1], mask, [30, 32], [0, 180, 0, 256])
    cv2.normalize(ref_hist, ref_hist, alpha=0, beta=1, norm_type=cv2.NORM_MINMAX)

    return {
        "tpl_bgr": tpl_bgr,
        "mask": mask,
        "ref_hist": ref_hist,
        "ref_face_h": ref_face_h,
        "ref_offset_x": ref_offset_x,
        "ref_offset_y": ref_offset_y,
        "streamer_embedding": streamer_embedding,
        "tpl_w": tpl_w,
        "tpl_h": tpl_h,
        "init_box": (fx, fy, fw, fh),
    }


# ---------------------------------------------------------------------------
# Pass 1 — Fast Shot & Trajectory Analysis
# ---------------------------------------------------------------------------
def run_pass_1(
    video_path: str,
    intervals: list[tuple[float, float]],
    fps: float,
    src_w: int,
    src_h: int,
    config: dict,
    use_cuda: bool | None = None,
) -> tuple[int, list[bool], dict[int, list[dict]], dict[int, tuple[float, float] | None], dict]:
    """Iterate source video once at analysis FPS (<= 15 FPS) to detect scene cuts and sampled face/webcam detections.

    Allocates 0-25% progress. Decodes each segment downscaled to 480px wide via FFmpeg CFR.
    """
    analysis_fps = min(float(fps), 15.0)
    total_target_frames = sum(max(1, int(round((e - s) * analysis_fps))) for s, e in intervals)
    frame_cuts: list[bool] = []
    sampled_detections: dict[int, list[dict]] = {}
    sampled_webcam: dict[int, tuple[float, float] | None] = {}
    sampled_gaming: dict[int, dict] = {}

    framing_mode = config.get("framing_mode", "gaming")
    gaming_tracking_mode = config.get("gaming_tracking_mode", "overlay_lock")
    ref_time_sec = float(config.get("reference_time_sec", 5.0))
    start_sec = intervals[0][0] if intervals else 0.0

    fb_initial = config.get("facecam_box") or {"x": 0.0, "y": 0.0, "w": 0.30, "h": 0.25}
    fb_w = float(fb_initial.get("w", 0.30))
    fb_h = float(fb_initial.get("h", 0.25))

    ref_hist: np.ndarray | None = None
    ref_offset_x = fb_w * 0.5
    ref_offset_y = fb_h * 0.35

    # Pass 1 analysis downscaled to 480px wide for speed (ensure even dimensions)
    p1_w = (480 if src_w > 480 else src_w) & ~1
    p1_h = (int(round(src_h * (p1_w / src_w))) & ~1)

    global_frame_idx = 0
    last_reported_pct = -1

    if use_cuda is None:
        use_cuda = can_use_cuda_decode(video_path)

    face_engine = FaceEngine(load_recognizer=True)

    try:
        # Step A — Capture Clean "Room Fingerprint" & Streamer Embedding Before Pass 1
        is_gaming = (framing_mode == "gaming")
        if is_gaming:
            room_fp = capture_room_fingerprint(
                video_path=video_path,
                facecam_box=fb_initial,
                start_sec=start_sec,
                reference_time_sec=ref_time_sec,
                src_w=src_w,
                src_h=src_h,
                face_engine=face_engine,
            )
            tpl_bgr = room_fp["tpl_bgr"]
            fp_mask = room_fp["mask"]
            ref_hist = room_fp["ref_hist"]
            ref_face_h = room_fp["ref_face_h"]
            ref_offset_x = room_fp.get("ref_offset_x", fb_w * 0.5)
            ref_offset_y = room_fp.get("ref_offset_y", fb_h * 0.35)
            streamer_embedding = room_fp.get("streamer_embedding")
            tpl_w = room_fp["tpl_w"]
            tpl_h = room_fp["tpl_h"]
            locked_box = room_fp["init_box"]
            sampled_gaming["_ref_face_h"] = ref_face_h
            sampled_gaming["_streamer_embedding"] = streamer_embedding

        host1_embedding: np.ndarray | None = None
        host2_embedding: np.ndarray | None = None

        for seg_idx, (seg_start, seg_end) in enumerate(intervals):
            seg_dur = max(0.001, seg_end - seg_start)
            prev_hist: np.ndarray | None = None
            seg_emitted = 0

            for frame in decode_segment_frames(video_path, seg_start, seg_dur, analysis_fps, p1_w, p1_h, use_cuda=use_cuda):
                # 160x90 thumbnail HSV histogram correlation (< 0.65 = hard scene cut)
                thumb = cv2.resize(frame, (160, 90), interpolation=cv2.INTER_AREA)
                hsv_thumb = cv2.cvtColor(thumb, cv2.COLOR_BGR2HSV)
                hist = cv2.calcHist([hsv_thumb], [0, 1], None, [30, 32], [0, 180, 0, 256])
                cv2.normalize(hist, hist, alpha=0, beta=1, norm_type=cv2.NORM_MINMAX)

                if prev_hist is None or seg_emitted == 0:
                    is_cut = True
                else:
                    corr = cv2.compareHist(prev_hist, hist, cv2.HISTCMP_CORREL)
                    is_cut = bool(corr < 0.65)
                prev_hist = hist
                frame_cuts.append(is_cut)

                # Sample frame 0, every scene cut, and every 2nd Pass 1 frame (~7.5 FPS)
                should_detect = (global_frame_idx == 0) or is_cut or (global_frame_idx % 2 == 0)

                if should_detect:
                    f_h, f_w = frame.shape[:2]
                    if is_gaming:
                        # Step B — Fast 4-State Pass 1 Analysis
                        is_overlay_lock = (gaming_tracking_mode == "overlay_lock")
                        state_1_matched = False

                        # 1. STATE 1 — Fast-Path Lock (overlay_lock only: <1ms room-border match, zero GPU inference)
                        if is_overlay_lock:
                            lx, ly, lw, lh = locked_box
                            cx1 = max(0, min(f_w - 1, int(lx * f_w)))
                            cy1 = max(0, min(f_h - 1, int(ly * f_h)))
                            cx2 = max(cx1 + 2, min(f_w, int((lx + lw) * f_w)))
                            cy2 = max(cy1 + 2, min(f_h, int((ly + lh) * f_h)))
                            crop = frame[cy1:cy2, cx1:cx2]
                            crop_resized = cv2.resize(crop, (tpl_w, tpl_h), interpolation=cv2.INTER_AREA)

                            tm_res = cv2.matchTemplate(crop_resized, tpl_bgr, cv2.TM_CCOEFF_NORMED, mask=fp_mask)
                            tm_corr = float(np.nan_to_num(tm_res[0, 0], nan=-1.0, posinf=-1.0, neginf=-1.0))

                            crop_hsv = cv2.cvtColor(crop_resized, cv2.COLOR_BGR2HSV)
                            crop_hist = cv2.calcHist([crop_hsv], [0, 1], fp_mask, [30, 32], [0, 180, 0, 256])
                            cv2.normalize(crop_hist, crop_hist, alpha=0, beta=1, norm_type=cv2.NORM_MINMAX)
                            hsv_corr = float(np.nan_to_num(cv2.compareHist(ref_hist, crop_hist, cv2.HISTCMP_CORREL), nan=-1.0, posinf=-1.0, neginf=-1.0))

                            score = 0.6 * tm_corr + 0.4 * hsv_corr
                            if score >= 0.58:
                                state_1_matched = True
                                sampled_gaming[global_frame_idx] = {
                                    "state": "overlay_locked",
                                    "box": (lx, ly, lw, lh),
                                    "face": None,
                                }
                                sampled_webcam[global_frame_idx] = (lx, ly)

                        if not state_1_matched:
                            # Run SCRFD + ArcFace on detected faces
                            faces = face_engine.detect(frame, input_size=(640, 640), score_thresh=0.32)
                            for f in faces:
                                f["embedding"] = face_engine.get_embedding(frame, f["kps"])
                                f["sim"] = FaceEngine.cosine_similarity(f["embedding"], streamer_embedding) if streamer_embedding is not None else 0.0

                            sampled_detections[global_frame_idx] = faces

                            # Room outer-ring HSV correlation on full frame
                            full_resized = cv2.resize(frame, (tpl_w, tpl_h), interpolation=cv2.INTER_AREA)
                            full_hsv = cv2.cvtColor(full_resized, cv2.COLOR_BGR2HSV)
                            full_hist = cv2.calcHist([full_hsv], [0, 1], fp_mask, [30, 32], [0, 180, 0, 256])
                            cv2.normalize(full_hist, full_hist, alpha=0, beta=1, norm_type=cv2.NORM_MINMAX)
                            full_hsv_corr = float(np.nan_to_num(cv2.compareHist(ref_hist, full_hist, cv2.HISTCMP_CORREL), nan=-1.0, posinf=-1.0, neginf=-1.0))
                            room_hsv_matches = (full_hsv_corr >= 0.50)

                            min_prom_h = max(0.14, ref_face_h * 1.6)

                            # 2. STATE 2 — Fullscreen Streamer Cam (No Duplicate Face)
                            prom_matches = [
                                f for f in faces
                                if ((f["sim"] >= 0.36) or (f["sim"] >= 0.28 and room_hsv_matches)) and (f["h"] >= min_prom_h)
                            ]

                            if prom_matches:
                                best_prom = max(prom_matches, key=lambda f: f["sim"])
                                sampled_gaming[global_frame_idx] = {
                                    "state": "fullscreen_cam",
                                    "box": locked_box,
                                    "face": best_prom,
                                }
                                sampled_webcam[global_frame_idx] = None
                            else:
                                # 3. STATE 3 — Moved / Green-Screen Overlay (Zero NPC Hijacking)
                                streamer_faces = [f for f in faces if f["sim"] >= 0.36]
                                if streamer_faces:
                                    sf = max(streamer_faces, key=lambda f: f["sim"])
                                    cand_x = max(0.0, min(1.0 - fb_w, sf["cx"] - ref_offset_x))
                                    cand_y = max(0.0, min(1.0 - fb_h, sf["cy"] - ref_offset_y))
                                    locked_box = (cand_x, cand_y, fb_w, fb_h)
                                    sampled_gaming[global_frame_idx] = {
                                        "state": "overlay_locked",
                                        "box": locked_box,
                                        "face": sf,
                                    }
                                    sampled_webcam[global_frame_idx] = (cand_x, cand_y)
                                elif streamer_embedding is None:
                                    # Fall back to Room Fingerprint search if streamer_embedding was unavailable
                                    frame_320 = cv2.resize(frame, (320, 180), interpolation=cv2.INTER_AREA)
                                    top_comb = -1.0
                                    top_box = None
                                    init_x = float(fb_initial.get("x", 0.0))
                                    init_y = float(fb_initial.get("y", 0.0))

                                    for s in (1.0, 0.85, 1.20):
                                        sw = max(16, min(316, int(round(fb_w * 320 * s))))
                                        sh = max(16, min(176, int(round(fb_h * 180 * s))))
                                        stpl = cv2.resize(tpl_bgr, (sw, sh), interpolation=cv2.INTER_AREA if sw < tpl_w else cv2.INTER_LINEAR)
                                        smask = cv2.resize(fp_mask, (sw, sh), interpolation=cv2.INTER_NEAREST)
                                        smask = (smask > 127).astype(np.uint8) * 255

                                        res_map = cv2.matchTemplate(frame_320, stpl, cv2.TM_CCOEFF_NORMED, mask=smask)
                                        res_map = np.nan_to_num(res_map, nan=-1.0, posinf=-1.0, neginf=-1.0)
                                        _, max_v, _, max_l = cv2.minMaxLoc(res_map)

                                        bx, by = max_l
                                        cand_crop = frame_320[by:by + sh, bx:bx + sw]
                                        cand_resized = cv2.resize(cand_crop, (tpl_w, tpl_h), interpolation=cv2.INTER_AREA)
                                        cand_hsv = cv2.cvtColor(cand_resized, cv2.COLOR_BGR2HSV)
                                        cand_hist = cv2.calcHist([cand_hsv], [0, 1], fp_mask, [30, 32], [0, 180, 0, 256])
                                        cv2.normalize(cand_hist, cand_hist, alpha=0, beta=1, norm_type=cv2.NORM_MINMAX)
                                        c_hsv_corr = float(np.nan_to_num(cv2.compareHist(ref_hist, cand_hist, cv2.HISTCMP_CORREL), nan=-1.0, posinf=-1.0, neginf=-1.0))

                                        comb = 0.6 * float(max_v) + 0.4 * c_hsv_corr
                                        if comb > top_comb:
                                            top_comb = comb
                                            top_box = (bx / 320.0, by / 180.0, sw / 320.0, sh / 180.0)

                                    if top_box is not None and top_comb >= 0.65:
                                        move_dist = ((top_box[0] - init_x) ** 2 + (top_box[1] - init_y) ** 2) ** 0.5
                                        if move_dist > 0.08:
                                            locked_box = top_box
                                        else:
                                            locked_box = (init_x, init_y, fb_w, fb_h)
                                        sampled_gaming[global_frame_idx] = {
                                            "state": "overlay_locked",
                                            "box": locked_box,
                                            "face": None,
                                        }
                                        sampled_webcam[global_frame_idx] = (locked_box[0], locked_box[1])
                                    else:
                                        # 4. STATE 4 — Cam Hidden / Pure Gameplay
                                        sampled_gaming[global_frame_idx] = {
                                            "state": "cam_hidden",
                                            "box": (init_x, init_y, fb_w, fb_h),
                                            "face": None,
                                        }
                                        sampled_webcam[global_frame_idx] = None
                                else:
                                    # In-game NPCs with cosine_sim < 0.36 strictly ignored -> State 4: Cam Hidden
                                    init_x = float(fb_initial.get("x", 0.0))
                                    init_y = float(fb_initial.get("y", 0.0))
                                    sampled_gaming[global_frame_idx] = {
                                        "state": "cam_hidden",
                                        "box": (init_x, init_y, fb_w, fb_h),
                                        "face": None,
                                    }
                                    sampled_webcam[global_frame_idx] = None
                    else:
                        # Podcast or other modes
                        faces = face_engine.detect(frame, input_size=(640, 640), score_thresh=0.32)
                        for f in faces:
                            f["embedding"] = face_engine.get_embedding(frame, f["kps"])

                        if framing_mode == "podcast":
                            # Host 1 and Host 2 identity lock
                            if (host1_embedding is None or host2_embedding is None) and faces:
                                gb_initial = config.get("gameplay_box") or {"x": 0.5, "y": 0.0, "w": 0.5, "h": 1.0}
                                fx, fy, fw, fh = float(fb_initial["x"]), float(fb_initial["y"]), float(fb_initial["w"]), float(fb_initial["h"])
                                gx, gy, gw, gh = float(gb_initial["x"]), float(gb_initial["y"]), float(gb_initial["w"]), float(gb_initial["h"])

                                f_in_1 = [f for f in faces if fx <= f["cx"] <= fx + fw and fy <= f["cy"] <= fy + fh]
                                f_in_2 = [f for f in faces if gx <= f["cx"] <= gx + gw and gy <= f["cy"] <= gy + gh]

                                if f_in_1 and f_in_2:
                                    if host1_embedding is None:
                                        host1_embedding = max(f_in_1, key=lambda f: f["w"] * f["h"])["embedding"]
                                    if host2_embedding is None:
                                        host2_embedding = max(f_in_2, key=lambda f: f["w"] * f["h"])["embedding"]
                                elif len(faces) >= 2 and (host1_embedding is None and host2_embedding is None):
                                    sorted_by_x = sorted(faces, key=lambda f: f["cx"])
                                    host1_embedding = sorted_by_x[0]["embedding"]
                                    host2_embedding = sorted_by_x[-1]["embedding"]

                            for f in faces:
                                f["sim_host1"] = FaceEngine.cosine_similarity(f["embedding"], host1_embedding) if host1_embedding is not None else -1.0
                                f["sim_host2"] = FaceEngine.cosine_similarity(f["embedding"], host2_embedding) if host2_embedding is not None else -1.0

                        sampled_detections[global_frame_idx] = faces

                seg_emitted += 1
                global_frame_idx += 1

                pct = min(25, int(25.0 * global_frame_idx / max(1, total_target_frames)))
                if pct != last_reported_pct:
                    print(f"PROGRESS:{pct}", flush=True)
                    last_reported_pct = pct

    finally:
        face_engine.close()
        del face_engine
        gc.collect()

    return global_frame_idx, frame_cuts, sampled_detections, sampled_webcam, sampled_gaming


# ---------------------------------------------------------------------------
# Trajectory Planning & Shot-Level Stabilization (Between Passes)
# ---------------------------------------------------------------------------
def build_trajectory_plan(
    total_frames: int,
    frame_cuts: list[bool],
    sampled_detections: dict[int, list[dict]],
    sampled_webcam: dict[int, tuple[float, float] | None],
    config: dict,
    out_w: int,
    out_h: int,
    src_w: int,
    src_h: int,
    fps: float,
    intervals: list[tuple[float, float]],
    sampled_gaming: dict | None = None,
) -> list[dict]:
    """Build deterministic per-frame rendering plan with shot-level stabilization and zero-phase smoothing."""
    if total_frames <= 0:
        return []

    fps_scale = max(0.1, fps / 60.0)
    min_cut_gap = max(2, int(round(6 * fps_scale)))
    smooth_radius = max(3, int(round(12 * fps_scale)))
    max_vel_frame = 0.006 / fps_scale
    debounce_frames = max(3, int(round(12 * fps_scale)))
    glide_len = max(2, int(round(6 * fps_scale)))

    # 1. Partition into contiguous shots with spurious cut merging
    cut_indices = [0]
    for i in range(1, total_frames):
        if i < len(frame_cuts) and frame_cuts[i]:
            if i - cut_indices[-1] >= min_cut_gap:
                cut_indices.append(i)

    shots: list[tuple[int, int]] = []
    for idx in range(len(cut_indices)):
        s_start = cut_indices[idx]
        s_end = cut_indices[idx + 1] if idx + 1 < len(cut_indices) else total_frames
        shots.append((s_start, s_end))

    layout = config.get("layout_template", "split_vertical")
    mode = config.get("framing_mode", "gaming")
    split_ratio = max(10, min(90, int(config.get("split_ratio", 50))))

    is_podcast_dual = (
        mode == "podcast"
        or layout in ("side_by_side_blur", "split_vertical", "split_inverted", "wide_plus_dual", "podcast_active_speaker")
    ) and mode not in ("gaming", "screen_presenter")

    fb_initial = config.get("facecam_box") or {"x": 0.0, "y": 0.0, "w": 0.30, "h": 0.25}
    gb_initial = config.get("gameplay_box") or {"x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0}

    plan: list[dict] = [{}] * total_frames

    # Determine pane dimensions for scale locking
    if layout in ("split_vertical", "split_inverted"):
        top_h = max(2, min(out_h - 2, int(out_h * split_ratio / 100) & ~1))
        bot_h = out_h - top_h
        pane1_dim = (out_w, top_h)
        pane2_dim = (out_w, bot_h)
    elif layout == "side_by_side_blur":
        left_w = (out_w // 2) & ~1
        right_w = out_w - left_w
        pane_h = max(2, min(out_h, int(left_w * (16 / 9)) & ~1))
        pane1_dim = (left_w, pane_h)
        pane2_dim = (right_w, pane_h)
    elif layout == "wide_plus_dual":
        top_h = 690 if (out_w, out_h) == (1080, 1920) else max(2, int(out_h * 0.36) & ~1)
        bot_h = out_h - top_h
        left_w = (out_w // 2) & ~1
        right_w = out_w - left_w
        pane1_dim = (left_w, bot_h)
        pane2_dim = (right_w, bot_h)
    else:
        pane1_dim = (out_w, out_h)
        pane2_dim = (out_w, out_h)

    # -----------------------------------------------------------------------
    # Non-Gaming Modes
    # -----------------------------------------------------------------------
    if mode != "gaming":
        for shot_start, shot_end in shots:
            shot_len = shot_end - shot_start
            shot_sampled_keys = [t for t in sorted(sampled_detections.keys()) if shot_start <= t < shot_end]
            if not shot_sampled_keys:
                shot_sampled_keys = [shot_start]

            # 1. Layout Vote in this shot
            votes = {"2_person": 0, "1_person": 0, "0_person": 0}
            for t in shot_sampled_keys:
                faces = sampled_detections.get(t, [])
                if len(faces) >= 2:
                    votes["2_person"] += 1
                elif len(faces) == 1:
                    votes["1_person"] += 1
                else:
                    votes["0_person"] += 1

            if is_podcast_dual:
                if votes["2_person"] > 0 and votes["2_person"] >= votes["1_person"] and votes["2_person"] >= votes["0_person"]:
                    shot_layout = "2_person"
                elif votes["1_person"] >= votes["2_person"] and votes["1_person"] >= votes["0_person"]:
                    shot_layout = "1_person"
                elif votes["0_person"] > votes["1_person"] and votes["0_person"] > votes["2_person"]:
                    shot_layout = "0_person"
                elif votes["2_person"] > 0:
                    shot_layout = "2_person"
                elif votes["1_person"] > 0:
                    shot_layout = "1_person"
                else:
                    shot_layout = "0_person"
            else:
                shot_layout = "1_person" if (votes["1_person"] > 0 or votes["2_person"] > 0) else "0_person"

            # 2. Dual Shot (2_person)
            if shot_layout == "2_person":
                left_samples: list[tuple[int, float, float, float]] = []
                right_samples: list[tuple[int, float, float, float]] = []

                for t in shot_sampled_keys:
                    faces = sampled_detections.get(t, [])
                    if len(faces) >= 2:
                        f_a, f_b = faces[0], faces[1]
                        sim_a1 = f_a.get("sim_host1", -1.0)
                        sim_a2 = f_a.get("sim_host2", -1.0)
                        sim_b1 = f_b.get("sim_host1", -1.0)
                        sim_b2 = f_b.get("sim_host2", -1.0)

                        if max(sim_a1, sim_a2, sim_b1, sim_b2) >= 0.32:
                            score_a1_b2 = sim_a1 + sim_b2
                            score_a2_b1 = sim_a2 + sim_b1
                            if score_a1_b2 >= score_a2_b1:
                                h1_face, h2_face = f_a, f_b
                            else:
                                h1_face, h2_face = f_b, f_a
                            left_samples.append((t, h1_face["cx"], h1_face["cy"], h1_face["h"]))
                            right_samples.append((t, h2_face["cx"], h2_face["cy"], h2_face["h"]))
                        else:
                            sorted_f = sorted(faces, key=lambda f: f["cx"])
                            left_samples.append((t, sorted_f[0]["cx"], sorted_f[0]["cy"], sorted_f[0]["h"]))
                            right_samples.append((t, sorted_f[-1]["cx"], sorted_f[-1]["cy"], sorted_f[-1]["h"]))
                    elif len(faces) == 1:
                        f = faces[0]
                        sim1 = f.get("sim_host1", -1.0)
                        sim2 = f.get("sim_host2", -1.0)
                        if sim1 >= 0.32 and sim1 > sim2:
                            left_samples.append((t, f["cx"], f["cy"], f["h"]))
                        elif sim2 >= 0.32 and sim2 > sim1:
                            right_samples.append((t, f["cx"], f["cy"], f["h"]))
                        elif f["cx"] < 0.5:
                            left_samples.append((t, f["cx"], f["cy"], f["h"]))
                        else:
                            right_samples.append((t, f["cx"], f["cy"], f["h"]))

                # Fallback if one person had zero detections in shot
                med_fh1 = float(np.median([s[3] for s in left_samples])) if left_samples else 0.20
                med_fh2 = float(np.median([s[3] for s in right_samples])) if right_samples else 0.20

                # Lock crop scale (w, h) strictly per shot (zero zoom breathing)
                lock_w1, lock_h1 = calculate_crop_scale(med_fh1, pane1_dim[0], pane1_dim[1], src_w, src_h)
                lock_w2, lock_h2 = calculate_crop_scale(med_fh2, pane2_dim[0], pane2_dim[1], src_w, src_h)

                # Linear interpolation of (cx, cy) to every frame in shot
                t_frames = np.arange(shot_start, shot_end)

                if left_samples:
                    xp1 = [s[0] for s in left_samples]
                    fp_cx1 = [s[1] for s in left_samples]
                    fp_cy1 = [s[2] for s in left_samples]
                    interp_cx1 = np.interp(t_frames, xp1, fp_cx1)
                    interp_cy1 = np.interp(t_frames, xp1, fp_cy1)
                else:
                    interp_cx1 = np.full(shot_len, 0.30)
                    interp_cy1 = np.full(shot_len, 0.40)

                if right_samples:
                    xp2 = [s[0] for s in right_samples]
                    fp_cx2 = [s[1] for s in right_samples]
                    fp_cy2 = [s[2] for s in right_samples]
                    interp_cx2 = np.interp(t_frames, xp2, fp_cx2)
                    interp_cy2 = np.interp(t_frames, xp2, fp_cy2)
                else:
                    interp_cx2 = np.full(shot_len, 0.70)
                    interp_cy2 = np.full(shot_len, 0.40)

                # 3-sample median filter
                med_cx1 = median_filter_1d(interp_cx1, size=3)
                med_cy1 = median_filter_1d(interp_cy1, size=3)
                med_cx2 = median_filter_1d(interp_cx2, size=3)
                med_cy2 = median_filter_1d(interp_cy2, size=3)

                # Tripod Deadzone Lock (< 0.06 spread) vs Silky Smooth Pan
                spread1 = max(np.ptp(med_cx1), np.ptp(med_cy1))
                is_static1 = bool(spread1 < 0.06)
                if is_static1:
                    final_cx1 = np.full(shot_len, float(np.median(med_cx1)))
                    final_cy1 = np.full(shot_len, float(np.median(med_cy1)))
                else:
                    final_cx1 = zero_phase_gaussian_smooth(med_cx1, radius=smooth_radius, max_vel=max_vel_frame)
                    final_cy1 = zero_phase_gaussian_smooth(med_cy1, radius=smooth_radius, max_vel=max_vel_frame)

                spread2 = max(np.ptp(med_cx2), np.ptp(med_cy2))
                is_static2 = bool(spread2 < 0.06)
                if is_static2:
                    final_cx2 = np.full(shot_len, float(np.median(med_cx2)))
                    final_cy2 = np.full(shot_len, float(np.median(med_cy2)))
                else:
                    final_cx2 = zero_phase_gaussian_smooth(med_cx2, radius=smooth_radius, max_vel=max_vel_frame)
                    final_cy2 = zero_phase_gaussian_smooth(med_cy2, radius=smooth_radius, max_vel=max_vel_frame)

                for k, f_idx in enumerate(range(shot_start, shot_end)):
                    y1 = np.clip(final_cy1[k] - 0.30 * lock_h1, 0.0, 1.0 - lock_h1)
                    x1 = np.clip(final_cx1[k] - 0.50 * lock_w1, 0.0, 1.0 - lock_w1)
                    y2 = np.clip(final_cy2[k] - 0.30 * lock_h2, 0.0, 1.0 - lock_h2)
                    x2 = np.clip(final_cx2[k] - 0.50 * lock_w2, 0.0, 1.0 - lock_w2)

                    plan[f_idx] = {
                        "layout_type": "2_person",
                        "box_p1": {"x": float(x1), "y": float(y1), "w": lock_w1, "h": lock_h1},
                        "box_p2": {"x": float(x2), "y": float(y2), "w": lock_w2, "h": lock_h2},
                        "is_static_p1": is_static1,
                        "is_static_p2": is_static2,
                        "is_cut": (f_idx == shot_start),
                    }

            # 3. Single Speaker (1_person)
            elif shot_layout == "1_person":
                primary_samples: list[tuple[int, float, float, float]] = []
                for t in shot_sampled_keys:
                    faces = sampled_detections.get(t, [])
                    if faces:
                        f = max(faces, key=lambda fc: fc["w"] * fc["h"])
                        primary_samples.append((t, f["cx"], f["cy"], f["h"]))

                med_fh = float(np.median([s[3] for s in primary_samples])) if primary_samples else 0.20
                lock_w, lock_h = calculate_crop_scale(med_fh, out_w, out_h, src_w, src_h)

                t_frames = np.arange(shot_start, shot_end)
                if primary_samples:
                    xp = [s[0] for s in primary_samples]
                    fp_cx = [s[1] for s in primary_samples]
                    fp_cy = [s[2] for s in primary_samples]
                    interp_cx = np.interp(t_frames, xp, fp_cx)
                    interp_cy = np.interp(t_frames, xp, fp_cy)
                else:
                    interp_cx = np.full(shot_len, 0.50)
                    interp_cy = np.full(shot_len, 0.40)

                med_cx = median_filter_1d(interp_cx, size=3)
                med_cy = median_filter_1d(interp_cy, size=3)

                spread = max(np.ptp(med_cx), np.ptp(med_cy))
                is_static = bool(spread < 0.06)
                if is_static:
                    final_cx = np.full(shot_len, float(np.median(med_cx)))
                    final_cy = np.full(shot_len, float(np.median(med_cy)))
                else:
                    final_cx = zero_phase_gaussian_smooth(med_cx, radius=smooth_radius, max_vel=max_vel_frame)
                    final_cy = zero_phase_gaussian_smooth(med_cy, radius=smooth_radius, max_vel=max_vel_frame)

                for k, f_idx in enumerate(range(shot_start, shot_end)):
                    cur_w, cur_h = lock_w, lock_h
                    if layout == "punch_in_zoom":
                        pos_sec = f_idx / fps
                        if (pos_sec % 12.0) >= 6.0:
                            cur_w = lock_w / 1.12
                            cur_h = lock_h / 1.12

                    y = np.clip(final_cy[k] - 0.30 * cur_h, 0.0, 1.0 - cur_h)
                    x = np.clip(final_cx[k] - 0.50 * cur_w, 0.0, 1.0 - cur_w)

                    plan[f_idx] = {
                        "layout_type": "1_person",
                        "box_p1": {"x": float(x), "y": float(y), "w": float(cur_w), "h": float(cur_h)},
                        "is_static": is_static,
                        "is_cut": (f_idx == shot_start),
                    }

            # 4. Zero Face (0_person) -> Blurred fill wide shot
            else:
                for f_idx in range(shot_start, shot_end):
                    plan[f_idx] = {
                        "layout_type": "0_person",
                        "box_p1": {"x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0},
                        "is_cut": (f_idx == shot_start),
                    }

    # -----------------------------------------------------------------------
    # Gaming Mode
    # -----------------------------------------------------------------------
    else:
        gaming_tracking_mode = config.get("gaming_tracking_mode", "overlay_lock")
        fb_w = float(fb_initial.get("w", 0.30))
        fb_h = float(fb_initial.get("h", 0.25))

        if gaming_tracking_mode in ("overlay_lock", "face_lock"):
            # Step C — Shot-Level State Debouncing & Step-Lock Stabilization
            sg = sampled_gaming or {}
            ref_face_h = float(sg.get("_ref_face_h", 0.45 * fb_h))

            sorted_sampled_times = sorted([k for k in sg.keys() if isinstance(k, int)])
            raw_states: list[str] = ["overlay_locked"] * total_frames
            raw_boxes: list[tuple[float, float, float, float]] = [
                (float(fb_initial.get("x", 0.0)), float(fb_initial.get("y", 0.0)), fb_w, fb_h)
            ] * total_frames
            raw_faces: list[dict | None] = [None] * total_frames

            if sorted_sampled_times:
                cur_st = sg[sorted_sampled_times[0]]["state"]
                cur_box = sg[sorted_sampled_times[0]]["box"]
                cur_face = sg[sorted_sampled_times[0]]["face"]
                s_idx = 0

                for f in range(total_frames):
                    while s_idx + 1 < len(sorted_sampled_times) and sorted_sampled_times[s_idx + 1] <= f:
                        s_idx += 1
                        cur_st = sg[sorted_sampled_times[s_idx]]["state"]
                        cur_box = sg[sorted_sampled_times[s_idx]]["box"]
                        cur_face = sg[sorted_sampled_times[s_idx]]["face"]

                    raw_states[f] = cur_st
                    raw_boxes[f] = cur_box
                    raw_faces[f] = cur_face

            # Debounce state changes lasting >= 12 frames (~0.4s)
            debounced_states = list(raw_states)
            if total_frames > 0:
                cur_state = raw_states[0]
                pending_state = None
                pending_count = 0

                for f in range(total_frames):
                    is_hard_cut = (f < len(frame_cuts) and frame_cuts[f])
                    if is_hard_cut:
                        cur_state = raw_states[f]
                        pending_state = None
                        pending_count = 0
                        debounced_states[f] = cur_state
                    else:
                        st = raw_states[f]
                        if st != cur_state:
                            if st == pending_state:
                                pending_count += 1
                                if pending_count >= debounce_frames:
                                    cur_state = pending_state
                                    backfill_start = max(0, f - (debounce_frames - 1))
                                    for bf in range(backfill_start, f + 1):
                                        debounced_states[bf] = cur_state
                                    pending_state = None
                                    pending_count = 0
                                else:
                                    debounced_states[f] = cur_state
                            else:
                                pending_state = st
                                pending_count = 1
                                debounced_states[f] = cur_state
                        else:
                            pending_state = None
                            pending_count = 0
                            debounced_states[f] = cur_state

            # Partition into segments at scene cuts and sustained state changes
            cut_points = [0]
            for f in range(1, total_frames):
                is_cut = (f < len(frame_cuts) and frame_cuts[f] and (f - cut_points[-1] >= min_cut_gap))
                is_state_change = (debounced_states[f] != debounced_states[f - 1])
                if is_cut or is_state_change:
                    cut_points.append(f)

            segments = []
            for idx in range(len(cut_points)):
                s_st = cut_points[idx]
                s_en = cut_points[idx + 1] if idx + 1 < len(cut_points) else total_frames
                segments.append((s_st, s_en))

            for seg_start, seg_end in segments:
                seg_len = seg_end - seg_start
                seg_state = debounced_states[seg_start]

                if seg_state == "overlay_locked":
                    # Lock (x, y, w, h) strictly to facecam_box dimensions (never expand or shift into HUD)
                    seg_b = [raw_boxes[f] for f in range(seg_start, seg_end) if raw_boxes[f] is not None]
                    init_x = float(fb_initial.get("x", 0.0))
                    init_y = float(fb_initial.get("y", 0.0))
                    if seg_b:
                        med_x = float(np.median([b[0] for b in seg_b]))
                        med_y = float(np.median([b[1] for b in seg_b]))
                    else:
                        med_x, med_y = init_x, init_y

                    move_dist = ((med_x - init_x) ** 2 + (med_y - init_y) ** 2) ** 0.5
                    if move_dist <= 0.08:
                        med_x, med_y = init_x, init_y
                    med_w, med_h = fb_w, fb_h

                    for f in range(seg_start, seg_end):
                        plan[f] = {
                            "layout_type": "gaming_overlay_locked",
                            "gaming_state": "overlay_locked",
                            "webcam_box": {"x": med_x, "y": med_y, "w": med_w, "h": med_h},
                            "gameplay_box": {"x": float(gb_initial["x"]), "y": float(gb_initial["y"]), "w": float(gb_initial["w"]), "h": float(gb_initial["h"])},
                            "is_static_webcam": True,
                            "is_static_gameplay": True,
                            "is_cut": (f == seg_start and (f < len(frame_cuts) and frame_cuts[f])),
                        }

                elif seg_state == "fullscreen_cam":
                    # Apply shot-level tripod lock + zero-phase Gaussian smooth pan and constant median (w, h)
                    primary_samples: list[tuple[int, float, float, float]] = []
                    for t in range(seg_start, seg_end):
                        fc = raw_faces[t]
                        if fc is not None:
                            primary_samples.append((t, fc["cx"], fc["cy"], fc["h"]))
                        elif t in sampled_detections and sampled_detections[t]:
                            fc = max(sampled_detections[t], key=lambda f: f["w"] * f["h"])
                            primary_samples.append((t, fc["cx"], fc["cy"], fc["h"]))

                    med_fh = float(np.median([s[3] for s in primary_samples])) if primary_samples else ref_face_h
                    lock_w, lock_h = calculate_crop_scale(med_fh, out_w, out_h, src_w, src_h)

                    t_frames = np.arange(seg_start, seg_end)
                    if primary_samples:
                        xp = [s[0] for s in primary_samples]
                        fp_cx = [s[1] for s in primary_samples]
                        fp_cy = [s[2] for s in primary_samples]
                        interp_cx = np.interp(t_frames, xp, fp_cx)
                        interp_cy = np.interp(t_frames, xp, fp_cy)
                    else:
                        interp_cx = np.full(seg_len, 0.50)
                        interp_cy = np.full(seg_len, 0.40)

                    med_cx = median_filter_1d(interp_cx, size=3)
                    med_cy = median_filter_1d(interp_cy, size=3)

                    spread = max(np.ptp(med_cx), np.ptp(med_cy))
                    is_static = bool(spread < 0.06)
                    if is_static:
                        final_cx = np.full(seg_len, float(np.median(med_cx)))
                        final_cy = np.full(seg_len, float(np.median(med_cy)))
                    else:
                        final_cx = zero_phase_gaussian_smooth(med_cx, radius=smooth_radius, max_vel=max_vel_frame)
                        final_cy = zero_phase_gaussian_smooth(med_cy, radius=smooth_radius, max_vel=max_vel_frame)

                    for k, f_idx in enumerate(range(seg_start, seg_end)):
                        y = np.clip(final_cy[k] - 0.30 * lock_h, 0.0, 1.0 - lock_h)
                        x = np.clip(final_cx[k] - 0.50 * lock_w, 0.0, 1.0 - lock_w)
                        plan[f_idx] = {
                            "layout_type": "gaming_fullscreen_cam",
                            "gaming_state": "fullscreen_cam",
                            "box_cam": {"x": float(x), "y": float(y), "w": float(lock_w), "h": float(lock_h)},
                            "gameplay_box": {"x": float(gb_initial["x"]), "y": float(gb_initial["y"]), "w": float(gb_initial["w"]), "h": float(gb_initial["h"])},
                            "is_static": is_static,
                            "is_static_gameplay": True,
                            "is_cut": (f_idx == seg_start and (f_idx < len(frame_cuts) and frame_cuts[f_idx])),
                        }

                else:  # cam_hidden
                    for f in range(seg_start, seg_end):
                        plan[f] = {
                            "layout_type": "gaming_cam_hidden",
                            "gaming_state": "cam_hidden",
                            "gameplay_box": {"x": float(gb_initial["x"]), "y": float(gb_initial["y"]), "w": float(gb_initial["w"]), "h": float(gb_initial["h"])},
                            "is_static_gameplay": True,
                            "is_cut": (f == seg_start and (f < len(frame_cuts) and frame_cuts[f])),
                        }

        else:
            # Segment into step-locked holds (face_lock mode)
            current_lock_x = float(fb_initial.get("x", 0.0))
            current_lock_y = float(fb_initial.get("y", 0.0))
            pending_pos: tuple[float, float] | None = None
            pending_count = 0

            # Build trajectory keyframes: (frame_idx, x, y)
            webcam_keyframes: list[tuple[int, float, float]] = [(0, current_lock_x, current_lock_y)]
            sorted_sampled_times = sorted(sampled_webcam.keys())

            for t in sorted_sampled_times:
                cand = sampled_webcam[t]
                if cand is None:
                    continue

                cx_cand, cy_cand = cand
                shift = max(abs(cx_cand - current_lock_x), abs(cy_cand - current_lock_y))

                if shift > 0.05:
                    if pending_pos is not None and max(abs(cx_cand - pending_pos[0]), abs(cy_cand - pending_pos[1])) < 0.03:
                        pending_count += 1
                    else:
                        pending_pos = (cx_cand, cy_cand)
                        pending_count = 1

                    if pending_count >= 3:
                        # Persisted for >= 3 samples (~0.4s) -> shift to new locked position
                        current_lock_x, current_lock_y = pending_pos
                        webcam_keyframes.append((t, current_lock_x, current_lock_y))
                        pending_pos = None
                        pending_count = 0
                else:
                    pending_pos = None
                    pending_count = 0

            # Generate per-frame positions with smooth glide between holds
            per_frame_webcam: list[tuple[float, float]] = [(current_lock_x, current_lock_y)] * total_frames
            kf_idx = 0
            cur_x, cur_y = webcam_keyframes[0][1], webcam_keyframes[0][2]

            for f in range(total_frames):
                if kf_idx + 1 < len(webcam_keyframes):
                    target_f, tgt_x, tgt_y = webcam_keyframes[kf_idx + 1]
                    if f >= target_f:
                        cur_x, cur_y = tgt_x, tgt_y
                        kf_idx += 1
                    elif f >= target_f - glide_len:
                        glide_alpha = (f - (target_f - glide_len)) / float(glide_len)
                        cur_x = (1.0 - glide_alpha) * webcam_keyframes[kf_idx][1] + glide_alpha * tgt_x
                        cur_y = (1.0 - glide_alpha) * webcam_keyframes[kf_idx][2] + glide_alpha * tgt_y

                per_frame_webcam[f] = (cur_x, cur_y)

            for f in range(total_frames):
                wx, wy = per_frame_webcam[f]
                plan[f] = {
                    "layout_type": "gaming",
                    "webcam_box": {"x": float(wx), "y": float(wy), "w": fb_w, "h": fb_h},
                    "gameplay_box": {"x": float(gb_initial["x"]), "y": float(gb_initial["y"]), "w": float(gb_initial["w"]), "h": float(gb_initial["h"])},
                    "is_cut": frame_cuts[f] if f < len(frame_cuts) else False,
                }

    return plan


def map_analysis_plan_to_target_fps(
    analysis_plan: list[dict],
    intervals: list[tuple[float, float]],
    analysis_fps: float,
    target_fps: float,
) -> list[dict]:
    """Upsample/map analysis plan onto Pass 2's exact full-rate frame count per segment.

    Uses nearest-index mapping per segment so Pass 2 renders full target FPS with frame-accurate
    cuts and zero A/V drift.
    """
    if not analysis_plan:
        return []

    full_plan: list[dict] = []
    an_offset = 0

    for seg_start, seg_end in intervals:
        seg_dur = max(0.001, seg_end - seg_start)
        m_seg = max(1, int(round(seg_dur * analysis_fps)))
        expected_frames = max(1, int(round(seg_dur * target_fps)))

        seg_analysis = analysis_plan[an_offset : an_offset + m_seg]
        an_offset += m_seg

        if not seg_analysis:
            fallback = analysis_plan[-1] if analysis_plan else {}
            full_plan.extend([dict(fallback)] * expected_frames)
            continue

        m_len = len(seg_analysis)
        last_m_idx = -1
        for n in range(expected_frames):
            if expected_frames <= 1 or m_len <= 1:
                m_idx = 0
            else:
                m_idx = min(m_len - 1, max(0, int(round(n * (m_len - 1) / (expected_frames - 1)))))

            step = dict(seg_analysis[m_idx])
            # Only mark cut on the first frame of the cut in Pass 2
            if n > 0 and m_idx == last_m_idx and step.get("is_cut"):
                step["is_cut"] = False
            last_m_idx = m_idx
            full_plan.append(step)

    return full_plan


# ---------------------------------------------------------------------------
# Pass 2 — Sub-Pixel Rendering & FFmpeg Pipe
# ---------------------------------------------------------------------------
def run_pass_2(
    video_path: str,
    output_path: str,
    intervals: list[tuple[float, float]],
    plan: list[dict],
    config: dict,
    out_w: int,
    out_h: int,
    fps: float,
    src_w: int,
    src_h: int,
    encoder: str,
    normalize: bool,
    has_audio: bool,
    ass_path: str | None,
    watermark_path: str | None,
    cwd: str | None,
    audio_idx: int | None = None,
    measured_loudnorm: dict | None = None,
    use_cuda: bool | None = None,
) -> tuple[int, str]:
    """Execute Pass 2: sub-pixel affine rendering and raw YUV420P streaming into FFmpeg.

    Allocates 25-100% progress.
    """
    out_w = max(2, int(out_w)) & ~1
    out_h = max(2, int(out_h)) & ~1
    total_target_frames = sum(max(1, int(round((e - s) * fps))) for s, e in intervals)

    if use_cuda is None:
        use_cuda = can_use_cuda_decode(video_path)

    ffmpeg_cmd = build_ffmpeg_cmd(
        video_path=video_path,
        output_path=output_path,
        intervals=intervals,
        out_w=out_w,
        out_h=out_h,
        fps=fps,
        encoder=encoder,
        normalize=normalize,
        has_audio=has_audio,
        ass_path=ass_path,
        watermark_path=watermark_path,
        watermark_config=config.get("watermark"),
        cwd=cwd,
        audio_idx=audio_idx,
        measured_loudnorm=measured_loudnorm,
    )

    logger.info("Spawning FFmpeg process: %s", " ".join(ffmpeg_cmd))
    proc = subprocess.Popen(
        ffmpeg_cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=str(cwd) if cwd else None,
    )

    stderr_lines: collections.deque[bytes] = collections.deque(maxlen=300)

    def drain_stderr():
        assert proc.stderr
        try:
            while line := proc.stderr.readline():
                stderr_lines.append(line)
        except Exception:
            pass

    stderr_thread = threading.Thread(target=drain_stderr, daemon=True)
    stderr_thread.start()

    layout = config.get("layout_template", "split_vertical")
    mode = config.get("framing_mode", "gaming")
    fit_mode = config.get("pane_fit_mode", "fill") or "fill"
    split_ratio = max(10, min(90, int(config.get("split_ratio", 50))))

    is_podcast_dual = (
        mode == "podcast"
        or layout in ("side_by_side_blur", "split_vertical", "split_inverted", "wide_plus_dual", "podcast_active_speaker")
    ) and mode not in ("gaming", "screen_presenter")

    # Pre-allocate single (out_h, out_w, 3) uint8 output canvas once before frame loop
    canvas = np.zeros((out_h, out_w, 3), dtype=np.uint8)

    global_frame_idx = 0
    last_reported_pct = -1

    try:
        for seg_idx, (seg_start, seg_end) in enumerate(intervals):
            seg_dur = max(0.001, seg_end - seg_start)
            seg_emitted = 0

            for frame in decode_segment_frames(video_path, seg_start, seg_dur, fps, src_w, src_h, use_cuda=use_cuda):
                step_plan = plan[min(global_frame_idx, len(plan) - 1)]
                l_type = step_plan.get("layout_type", "0_person")

                if is_podcast_dual:
                    if l_type == "2_person":
                        b1 = step_plan["box_p1"]
                        b2 = step_plan["box_p2"]

                        if layout == "split_vertical":
                            top_h = max(2, min(out_h - 2, int(out_h * split_ratio / 100) & ~1))
                            bot_h = out_h - top_h
                            p1 = render_pane(frame, b1, out_w, top_h, fit_mode=fit_mode, is_static=step_plan.get("is_static_p1", False))
                            p2 = render_pane(frame, b2, out_w, bot_h, fit_mode=fit_mode, is_static=step_plan.get("is_static_p2", False))
                            canvas[0:top_h, 0:out_w] = p1
                            canvas[top_h:out_h, 0:out_w] = p2

                        elif layout == "split_inverted":
                            top_h = max(2, min(out_h - 2, int(out_h * split_ratio / 100) & ~1))
                            bot_h = out_h - top_h
                            p2 = render_pane(frame, b2, out_w, top_h, fit_mode=fit_mode, is_static=step_plan.get("is_static_p2", False))
                            p1 = render_pane(frame, b1, out_w, bot_h, fit_mode=fit_mode, is_static=step_plan.get("is_static_p1", False))
                            canvas[0:top_h, 0:out_w] = p2
                            canvas[top_h:out_h, 0:out_w] = p1

                        elif layout == "side_by_side_blur":
                            left_w = (out_w // 2) & ~1
                            right_w = out_w - left_w
                            pane_h = max(2, min(out_h, int(left_w * (16 / 9)) & ~1))
                            overlay_y = max(0, (out_h - pane_h) // 2)
                            p1 = render_pane(frame, b1, left_w, pane_h, fit_mode=fit_mode, is_static=step_plan.get("is_static_p1", False))
                            p2 = render_pane(frame, b2, right_w, pane_h, fit_mode=fit_mode, is_static=step_plan.get("is_static_p2", False))
                            canvas[:] = render_blurred_background(frame, out_w, out_h)
                            canvas[overlay_y:overlay_y + pane_h, 0:left_w] = p1
                            canvas[overlay_y:overlay_y + pane_h, left_w:out_w] = p2

                        elif layout == "wide_plus_dual":
                            top_h = 690 if (out_w, out_h) == (1080, 1920) else max(2, int(out_h * 0.36) & ~1)
                            bot_h = out_h - top_h
                            left_w = (out_w // 2) & ~1
                            right_w = out_w - left_w
                            top_wide = fast_render_pane(frame, {"x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0}, out_w, top_h, fit_mode="fill")
                            p1 = render_pane(frame, b1, left_w, bot_h, fit_mode=fit_mode, is_static=step_plan.get("is_static_p1", False))
                            p2 = render_pane(frame, b2, right_w, bot_h, fit_mode=fit_mode, is_static=step_plan.get("is_static_p2", False))
                            canvas[0:top_h, 0:out_w] = top_wide
                            canvas[top_h:out_h, 0:left_w] = p1
                            canvas[top_h:out_h, left_w:out_w] = p2

                        else:  # podcast_active_speaker in dual shot
                            canvas[:] = render_pane(frame, b1, out_w, out_h, fit_mode=fit_mode, is_static=step_plan.get("is_static_p1", False))

                    elif l_type == "1_person":
                        canvas[:] = render_pane(frame, step_plan["box_p1"], out_w, out_h, fit_mode=fit_mode, is_static=step_plan.get("is_static", False))

                    else:  # 0_person
                        canvas[:] = render_blurred_fill(frame, out_w, out_h)

                elif mode in ("gaming", "screen_presenter"):
                    g_state = step_plan.get("gaming_state")
                    if mode == "gaming" and g_state == "fullscreen_cam":
                        is_static = step_plan.get("is_static", False)
                        canvas[:] = render_pane(frame, step_plan["box_cam"], out_w, out_h, fit_mode=fit_mode, head_bias=True, is_static=is_static)
                    elif mode == "gaming" and g_state == "cam_hidden":
                        gb = step_plan["gameplay_box"]
                        if layout == "fullscreen_crop":
                            canvas[:] = fast_render_pane(frame, gb, out_w, out_h, fit_mode=fit_mode, head_bias=False)
                        else:
                            canvas[:] = render_blurred_fill(frame, out_w, out_h, fg_box=gb)
                    else:
                        wb = step_plan["webcam_box"]
                        gb = step_plan["gameplay_box"]
                        is_stationary_wb = step_plan.get("is_static_webcam", g_state == "overlay_locked" or l_type == "gaming_overlay_locked")

                        if layout == "pip":
                            fb_w = max(0.01, float(wb["w"]))
                            fb_h = max(0.01, float(wb["h"]))
                            pip_w = max(160, (out_w // 3) & ~1)
                            pip_h = max(90, int(pip_w * (fb_h / fb_w) * (src_h / src_w)) & ~1)
                            main_p = fast_render_pane(frame, gb, out_w, out_h, fit_mode=fit_mode, head_bias=False)
                            pip_p = (
                                fast_render_pane(frame, wb, pip_w, pip_h, fit_mode="fill", head_bias=False)
                                if is_stationary_wb
                                else subpixel_render_pane(frame, wb, pip_w, pip_h, fit_mode="fill", head_bias=False)
                            )
                            canvas[:] = main_p
                            canvas[20:20 + pip_h, out_w - pip_w - 20:out_w - 20] = pip_p

                        elif layout == "split_inverted":
                            top_h = max(2, min(out_h - 2, int(out_h * split_ratio / 100) & ~1))
                            bot_h = out_h - top_h
                            if mode == "screen_presenter":
                                top_p = (
                                    fast_render_pane(frame, wb, out_w, top_h, fit_mode=fit_mode, head_bias=False)
                                    if is_stationary_wb
                                    else subpixel_render_pane(frame, wb, out_w, top_h, fit_mode=fit_mode, head_bias=False)
                                )
                                bot_p = fast_render_pane(frame, gb, out_w, bot_h, fit_mode=fit_mode, head_bias=False)
                            else:
                                top_p = fast_render_pane(frame, gb, out_w, top_h, fit_mode=fit_mode, head_bias=False)
                                bot_p = (
                                    fast_render_pane(frame, wb, out_w, bot_h, fit_mode=fit_mode, head_bias=False)
                                    if is_stationary_wb
                                    else subpixel_render_pane(frame, wb, out_w, bot_h, fit_mode=fit_mode, head_bias=False)
                                )
                            canvas[0:top_h, 0:out_w] = top_p
                            canvas[top_h:out_h, 0:out_w] = bot_p

                        elif layout == "fullscreen_crop":
                            canvas[:] = fast_render_pane(frame, gb, out_w, out_h, fit_mode=fit_mode, head_bias=False)

                        else:  # split_vertical
                            top_h = max(2, min(out_h - 2, int(out_h * split_ratio / 100) & ~1))
                            bot_h = out_h - top_h
                            if mode == "screen_presenter":
                                top_p = fast_render_pane(frame, gb, out_w, top_h, fit_mode=fit_mode, head_bias=False)
                                bot_p = (
                                    fast_render_pane(frame, wb, out_w, bot_h, fit_mode=fit_mode, head_bias=False)
                                    if is_stationary_wb
                                    else subpixel_render_pane(frame, wb, out_w, bot_h, fit_mode=fit_mode, head_bias=False)
                                )
                            else:
                                top_p = (
                                    fast_render_pane(frame, wb, out_w, top_h, fit_mode=fit_mode, head_bias=False)
                                    if is_stationary_wb
                                    else subpixel_render_pane(frame, wb, out_w, top_h, fit_mode=fit_mode, head_bias=False)
                                )
                                bot_p = fast_render_pane(frame, gb, out_w, bot_h, fit_mode=fit_mode, head_bias=False)
                            canvas[0:top_h, 0:out_w] = top_p
                            canvas[top_h:out_h, 0:out_w] = bot_p

                else:
                    # Single-Person Layouts (fullscreen_crop, punch_in_zoom)
                    if l_type == "1_person":
                        canvas[:] = render_pane(frame, step_plan["box_p1"], out_w, out_h, fit_mode=fit_mode, is_static=step_plan.get("is_static", False))
                    else:
                        canvas[:] = render_blurred_fill(frame, out_w, out_h)

                try:
                    assert proc.stdin
                    yuv_bytes = cv2.cvtColor(canvas, cv2.COLOR_BGR2YUV_I420).tobytes()
                    proc.stdin.write(yuv_bytes)
                except (BrokenPipeError, OSError):
                    logger.warning("FFmpeg pipe closed unexpectedly during Pass 2.")
                    break

                seg_emitted += 1
                global_frame_idx += 1

                if global_frame_idx % 100 == 0:
                    gc.collect()

                pct = min(99, 25 + int(74.0 * global_frame_idx / max(1, total_target_frames)))
                if pct != last_reported_pct:
                    print(f"PROGRESS:{pct}", flush=True)
                    last_reported_pct = pct

    finally:
        gc.collect()

    try:
        if proc.stdin:
            proc.stdin.close()
    except Exception:
        pass

    return_code = proc.wait()
    stderr_thread.join(timeout=3.0)
    stderr_text = b"".join(stderr_lines).decode("utf-8", errors="replace")

    if return_code == 0:
        print("PROGRESS:100", flush=True)

    return return_code, stderr_text


# ---------------------------------------------------------------------------
# CLI Entrypoint & 2-Pass Pipeline Execution
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Phase 6 — 2-Pass Shot-Locked Dynamic Reframer")
    parser.add_argument("--video-path", required=True)
    parser.add_argument("--output-path", required=True)
    parser.add_argument("--config-json", required=True)
    parser.add_argument("--intervals-json", required=True)
    parser.add_argument("--out-w", type=int, default=1080)
    parser.add_argument("--out-h", type=int, default=1920)
    parser.add_argument("--encoder", type=str, default="h264_nvenc")
    parser.add_argument("--normalize", action="store_true", default=False)
    parser.add_argument("--has-audio", action="store_true", default=False)
    parser.add_argument("--ass-path", type=str, default=None)
    parser.add_argument("--watermark-path", type=str, default=None)
    parser.add_argument("--cwd", type=str, default=None)
    args = parser.parse_args()

    # Limit OpenCV threads so OpenCV, FFmpeg decode, and libass do not thrash CPU
    cv2.setNumThreads(max(2, (os.cpu_count() or 4) - 2))

    config_raw = args.config_json
    if Path(config_raw).is_file():
        config_data = json.loads(Path(config_raw).read_text(encoding="utf-8"))
    else:
        config_data = json.loads(config_raw)

    intervals_raw = args.intervals_json
    if Path(intervals_raw).is_file():
        intervals_data = json.loads(Path(intervals_raw).read_text(encoding="utf-8"))
    else:
        intervals_data = json.loads(intervals_raw)

    intervals: list[tuple[float, float]] = []
    for item in intervals_data:
        if isinstance(item, (list, tuple)) and len(item) >= 2:
            intervals.append((float(item[0]), float(item[1])))
        elif isinstance(item, dict):
            s = float(item.get("start_sec", item.get("start", 0.0)))
            e = float(item.get("end_sec", item.get("end", 0.0)))
            intervals.append((s, e))

    if not intervals:
        intervals = [(0.0, 10.0)]

    out_w = max(2, int(args.out_w)) & ~1
    out_h = max(2, int(args.out_h)) & ~1

    # Inspect source video metadata via ffprobe
    src_w, src_h, fps = probe_video(args.video_path)

    # Test if NVIDIA NVDEC can be used for hardware decoding
    use_cuda = can_use_cuda_decode(args.video_path)
    if use_cuda:
        logger.info("[CLIPFORGE DECODER] NVIDIA NVDEC (-hwaccel cuda) enabled for Pass 1 & Pass 2 decode")
    else:
        logger.info("[CLIPFORGE DECODER] Software decode active (NVDEC unavailable or unsupported)")

    analysis_fps = min(fps, 15.0)

    # Pass 1 — Fast Shot & Trajectory Analysis (decoded at analysis_fps <= 15 FPS)
    total_analysis_frames, frame_cuts, sampled_detections, sampled_webcam, sampled_gaming = run_pass_1(
        video_path=args.video_path,
        intervals=intervals,
        fps=fps,
        src_w=src_w,
        src_h=src_h,
        config=config_data,
        use_cuda=use_cuda,
    )

    # Between Passes: Shot-Level Stabilization & Zero-Phase Smoothing Plan
    analysis_plan = build_trajectory_plan(
        total_frames=total_analysis_frames,
        frame_cuts=frame_cuts,
        sampled_detections=sampled_detections,
        sampled_webcam=sampled_webcam,
        config=config_data,
        out_w=out_w,
        out_h=out_h,
        src_w=src_w,
        src_h=src_h,
        fps=analysis_fps,
        intervals=intervals,
        sampled_gaming=sampled_gaming,
    )

    # Upsample/map analysis plan onto Pass 2's exact full-rate frame count per segment
    plan = map_analysis_plan_to_target_fps(
        analysis_plan=analysis_plan,
        intervals=intervals,
        analysis_fps=analysis_fps,
        target_fps=fps,
    )

    # Pass 2 — Sub-Pixel Rendering & FFmpeg Pipe (with automatic NVENC -> libx264 fallback)
    initial_encoder = args.encoder or "h264_nvenc"
    encoders_to_try = [initial_encoder]
    if initial_encoder == "h264_nvenc":
        encoders_to_try.append("libx264")

    audio_idx = resolve_primary_audio_index(args.video_path) if args.has_audio else 0
    measured_loudnorm = None
    if args.has_audio and args.normalize:
        measured_loudnorm = measure_loudnorm(args.video_path, intervals, audio_idx)

    success = False
    last_stderr = ""
    used_encoder = ""

    for enc in encoders_to_try:
        code, stderr = run_pass_2(
            video_path=args.video_path,
            output_path=args.output_path,
            intervals=intervals,
            plan=plan,
            config=config_data,
            out_w=out_w,
            out_h=out_h,
            fps=fps,
            src_w=src_w,
            src_h=src_h,
            encoder=enc,
            normalize=args.normalize,
            has_audio=args.has_audio,
            ass_path=args.ass_path,
            watermark_path=args.watermark_path,
            cwd=args.cwd,
            audio_idx=audio_idx,
            measured_loudnorm=measured_loudnorm,
            use_cuda=use_cuda,
        )
        last_stderr = stderr
        if code == 0 and Path(args.output_path).is_file() and Path(args.output_path).stat().st_size > 0:
            success = True
            used_encoder = enc
            if enc == "h264_nvenc":
                print("[CLIPFORGE ENCODER] Using h264_nvenc (NVIDIA GPU)", flush=True)
            else:
                print("[CLIPFORGE ENCODER] Using libx264 (CPU)", flush=True)
            break

        Path(args.output_path).unlink(missing_ok=True)
        if enc == "h264_nvenc":
            err_preview = stderr[-1000:].strip() if stderr else "(no stderr)"
            print(f"[CLIPFORGE ENCODER WARNING] h264_nvenc failed: {err_preview} — falling back to libx264", flush=True)
        else:
            print(f"[CLIPFORGE ENCODER WARNING] Encoder {enc} failed (code {code}). Stderr tail:\n{stderr[-1000:]}", flush=True, file=sys.stderr)

    if success:
        print(f"COMPLETE:{json.dumps({'encoder': used_encoder, 'output_path': args.output_path})}", flush=True)
        sys.exit(0)
    else:
        print(f"ERROR:{json.dumps({'error': 'All encoders failed', 'stderr': last_stderr[-2000:]})}", flush=True, file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
