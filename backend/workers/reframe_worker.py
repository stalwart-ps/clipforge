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
import gc
import json
import logging
from pathlib import Path
import shutil
import subprocess
import sys
import threading

# Ensure backend root is on sys.path
backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

import cv2
import mediapipe as mp
import numpy as np


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


def render_blurred_fill(
    frame: np.ndarray,
    target_w: int,
    target_h: int,
    fg_box: dict | None = None,
) -> np.ndarray:
    """Render a fast cinematic blurred background with foreground centered."""
    src_h, src_w = frame.shape[:2]
    target_w = max(2, int(target_w)) & ~1
    target_h = max(2, int(target_h)) & ~1

    small = cv2.resize(frame, (160, max(2, int(160 * src_h / src_w))), interpolation=cv2.INTER_AREA)
    small_blur = cv2.GaussianBlur(small, (21, 21), 0)
    bg = subpixel_render_pane(small_blur, {"x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0}, target_w, target_h, fit_mode="fill")

    box = fg_box or {"x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0}
    scale = min(target_w / (float(box["w"]) * src_w), target_h / (float(box["h"]) * src_h))
    dst_w = max(2, int(float(box["w"]) * src_w * scale)) & ~1
    dst_h = max(2, int(float(box["h"]) * src_h * scale)) & ~1
    off_x = (target_w - dst_w) // 2
    off_y = (target_h - dst_h) // 2

    fg_patch = subpixel_render_pane(frame, box, dst_w, dst_h, fit_mode="fill")
    bg[off_y:off_y + dst_h, off_x:off_x + dst_w] = fg_patch
    return bg


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
    watermark_config: dict | None,
    cwd: str | None,
) -> list[str]:
    """Assemble FFmpeg CLI invocation for piped raw BGR24 input and audio/subtitle muxing."""
    ffmpeg_bin = shutil.which("ffmpeg") or "ffmpeg"
    cmd = [ffmpeg_bin, "-hide_banner", "-y"]

    cmd += [
        "-f", "rawvideo",
        "-vcodec", "rawvideo",
        "-pix_fmt", "bgr24",
        "-s", f"{out_w}x{out_h}",
        "-r", f"{fps:.6f}",
        "-i", "pipe:0",
    ]

    if has_audio:
        for seg_start, seg_end in intervals:
            seg_dur = max(0.001, seg_end - seg_start)
            cmd += ["-ss", f"{seg_start:.6f}", "-t", f"{seg_dur:.6f}", "-i", video_path]

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
            if dur > 0.15:
                fade_out_st = max(0.0, dur - 0.02)
                fade_str = f",afade=t=in:st=0:d=0.020,afade=t=out:st={fade_out_st:.3f}:d=0.020"
            filter_parts.append(f"[{k + 1}:a:0]asetpts=PTS-STARTPTS{fade_str}[a{k}]")

        if len(intervals) > 1:
            concat_inputs = "".join(f"[a{k}]" for k in range(len(intervals)))
            filter_parts.append(f"{concat_inputs}concat=n={len(intervals)}:v=0:a=1[a_concat]")
            a_cur = "[a_concat]"
        else:
            filter_parts.append("[a0]anull[a_single]")
            a_cur = "[a_single]"

        if normalize:
            filter_parts.append(f"{a_cur}loudnorm=I=-14:TP=-1.5:LRA=11[aout]")
        else:
            filter_parts.append(f"{a_cur}anull[aout]")

    cmd += ["-filter_complex", ";".join(filter_parts)]

    total_duration = sum(max(0.001, e - s) for s, e in intervals)
    cmd += ["-t", f"{total_duration:.6f}"]

    cmd += ["-map", "[v_final]"]
    if encoder == "h264_nvenc":
        cmd += ["-c:v", "h264_nvenc", "-preset", "p4", "-rc:v", "vbr", "-cq:v", "19", "-b:v", "0", "-pix_fmt", "yuv420p"]
    else:
        cmd += ["-c:v", "libx264", "-crf", "18", "-preset", "fast", "-pix_fmt", "yuv420p"]

    if has_audio:
        cmd += ["-map", "[aout]", "-c:a", "aac", "-b:a", "192k", "-ar", "48000"]
    else:
        cmd += ["-an"]

    cmd += ["-fps_mode", "cfr", "-sn", "-movflags", "+faststart", output_path]
    return cmd


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
) -> tuple[int, list[bool], dict[int, list[dict]], dict[int, tuple[float, float] | None]]:
    """Iterate source video once to detect scene cuts and sampled face/webcam detections.

    Allocates 0-25% progress. Releases video capture and MediaPipe models before returning.
    """
    total_target_frames = sum(max(1, int(round((e - s) * fps))) for s, e in intervals)
    frame_cuts: list[bool] = []
    sampled_detections: dict[int, list[dict]] = {}
    sampled_webcam: dict[int, tuple[float, float] | None] = {}

    fb_initial = config.get("facecam_box") or {"x": 0.0, "y": 0.0, "w": 0.30, "h": 0.25}
    fb_w = float(fb_initial.get("w", 0.30))
    fb_h = float(fb_initial.get("h", 0.25))

    ref_hist: np.ndarray | None = None
    ref_offset_x = fb_w * 0.5
    ref_offset_y = fb_h * 0.35

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return 0, [], {}, {}

    mp_face = mp.solutions.face_detection
    global_frame_idx = 0
    last_reported_pct = -1

    try:
        with mp_face.FaceDetection(model_selection=0, min_detection_confidence=0.35) as det_close, \
             mp_face.FaceDetection(model_selection=1, min_detection_confidence=0.35) as det_wide:

            for seg_idx, (seg_start, seg_end) in enumerate(intervals):
                cap.set(cv2.CAP_PROP_POS_MSEC, max(0.0, seg_start) * 1000.0)
                seg_target_frames = max(1, int(round((seg_end - seg_start) * fps)))
                seg_emitted = 0
                prev_hist: np.ndarray | None = None

                while seg_emitted < seg_target_frames:
                    ret, frame = cap.read()
                    if not ret or frame is None:
                        break

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

                    # Sample frame 0, every scene cut, and every 4th frame (~7-8 FPS)
                    should_detect = (global_frame_idx == 0) or is_cut or (global_frame_idx % 4 == 0)

                    if should_detect:
                        scale = 480.0 / src_w if src_w > 480 else 1.0
                        small_bgr = cv2.resize(frame, (480, int(src_h * scale)), interpolation=cv2.INTER_AREA) if scale < 1.0 else frame
                        rgb_small = cv2.cvtColor(small_bgr, cv2.COLOR_BGR2RGB)

                        res0 = det_close.process(rgb_small)
                        res1 = det_wide.process(rgb_small)

                        candidates = []
                        for res, model_id in ((res0, 0), (res1, 1)):
                            if res and res.detections:
                                for det in res.detections:
                                    bb = det.location_data.relative_bounding_box
                                    lx = max(0.0, min(1.0, float(bb.xmin)))
                                    ly = max(0.0, min(1.0, float(bb.ymin)))
                                    bw = min(1.0 - lx, max(0.001, float(bb.width)))
                                    bh = min(1.0 - ly, max(0.001, float(bb.height)))
                                    candidates.append({
                                        "x": lx, "y": ly, "w": bw, "h": bh,
                                        "cx": lx + bw / 2.0, "cy": ly + bh / 2.0,
                                        "score": float(det.score[0]) if det.score else 0.0,
                                        "model": model_id,
                                    })

                        faces = deduplicate_faces(candidates, iou_threshold=0.35)
                        sampled_detections[global_frame_idx] = faces

                        # Gaming mode webcam histogram tracking on sampled frames
                        if config.get("framing_mode") == "gaming":
                            sw_h, sw_w = small_bgr.shape[:2]
                            hsv_small = cv2.cvtColor(small_bgr, cv2.COLOR_BGR2HSV)
                            if ref_hist is None and faces:
                                inside = [
                                    f for f in faces
                                    if fb_initial["x"] <= f["cx"] <= fb_initial["x"] + fb_w
                                    and fb_initial["y"] <= f["cy"] <= fb_initial["y"] + fb_h
                                ]
                                ref_face = max(inside, key=lambda f: f["w"] * f["h"]) if inside else faces[0]
                                ref_offset_x = ref_face["cx"] - float(fb_initial["x"])
                                ref_offset_y = ref_face["cy"] - float(fb_initial["y"])

                                px1 = max(0, min(sw_w - 1, int(float(fb_initial["x"]) * sw_w)))
                                py1 = max(0, min(sw_h - 1, int(float(fb_initial["y"]) * sw_h)))
                                px2 = max(px1 + 1, min(sw_w, int((float(fb_initial["x"]) + fb_w) * sw_w)))
                                py2 = max(py1 + 1, min(sw_h, int((float(fb_initial["y"]) + fb_h) * sw_h)))

                                roi = hsv_small[py1:py2, px1:px2]
                                mask = np.ones((py2 - py1, px2 - px1), dtype=np.uint8) * 255
                                f_px1 = max(0, min(px2 - px1, int((ref_face["x"] - float(fb_initial["x"])) * sw_w)))
                                f_py1 = max(0, min(py2 - py1, int((ref_face["y"] - float(fb_initial["y"])) * sw_h)))
                                f_px2 = max(0, min(px2 - px1, int((ref_face["x"] + ref_face["w"] - float(fb_initial["x"])) * sw_w)))
                                f_py2 = max(0, min(py2 - py1, int((ref_face["y"] + ref_face["h"] - float(fb_initial["y"])) * sw_h)))
                                mask[f_py1:f_py2, f_px1:f_px2] = 0

                                h_calc = cv2.calcHist([roi], [0, 1], mask, [30, 32], [0, 180, 0, 256])
                                cv2.normalize(h_calc, h_calc, alpha=0, beta=1, norm_type=cv2.NORM_MINMAX)
                                ref_hist = h_calc
                                sampled_webcam[global_frame_idx] = (float(fb_initial["x"]), float(fb_initial["y"]))
                            elif ref_hist is not None and faces:
                                best_match = None
                                best_sim = -1.0
                                for cand in faces:
                                    cand_x = max(0.0, min(1.0 - fb_w, cand["cx"] - ref_offset_x))
                                    cand_y = max(0.0, min(1.0 - fb_h, cand["cy"] - ref_offset_y))

                                    c_px1 = max(0, min(sw_w - 1, int(cand_x * sw_w)))
                                    c_py1 = max(0, min(sw_h - 1, int(cand_y * sw_h)))
                                    c_px2 = max(c_px1 + 1, min(sw_w, int((cand_x + fb_w) * sw_w)))
                                    c_py2 = max(c_py1 + 1, min(sw_h, int((cand_y + fb_h) * sw_h)))

                                    c_roi = hsv_small[c_py1:c_py2, c_px1:c_px2]
                                    c_mask = np.ones((c_py2 - c_py1, c_px2 - c_px1), dtype=np.uint8) * 255
                                    cf_px1 = max(0, min(c_px2 - c_px1, int((cand["x"] - cand_x) * sw_w)))
                                    cf_py1 = max(0, min(c_py2 - c_py1, int((cand["y"] - cand_y) * sw_h)))
                                    cf_px2 = max(0, min(c_px2 - c_px1, int((cand["x"] + cand["w"] - cand_x) * sw_w)))
                                    cf_py2 = max(0, min(c_py2 - c_py1, int((cand["y"] + cand["h"] - cand_y) * sw_h)))
                                    c_mask[cf_py1:cf_py2, cf_px1:cf_px2] = 0

                                    c_hist = cv2.calcHist([c_roi], [0, 1], c_mask, [30, 32], [0, 180, 0, 256])
                                    cv2.normalize(c_hist, c_hist, alpha=0, beta=1, norm_type=cv2.NORM_MINMAX)
                                    sim = cv2.compareHist(ref_hist, c_hist, cv2.HISTCMP_CORREL)
                                    if sim >= 0.30 and sim > best_sim:
                                        best_sim = sim
                                        best_match = (cand_x, cand_y)
                                sampled_webcam[global_frame_idx] = best_match
                            else:
                                sampled_webcam[global_frame_idx] = None

                    seg_emitted += 1
                    global_frame_idx += 1

                    pct = min(25, int(25.0 * global_frame_idx / max(1, total_target_frames)))
                    if pct != last_reported_pct:
                        print(f"PROGRESS:{pct}", flush=True)
                        last_reported_pct = pct

    finally:
        cap.release()
        gc.collect()

    return global_frame_idx, frame_cuts, sampled_detections, sampled_webcam


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
) -> list[dict]:
    """Build deterministic per-frame rendering plan with shot-level stabilization and zero-phase smoothing."""
    if total_frames <= 0:
        return []

    # 1. Partition into contiguous shots with spurious cut (< 6 frames) merging
    cut_indices = [0]
    for i in range(1, total_frames):
        if i < len(frame_cuts) and frame_cuts[i]:
            if i - cut_indices[-1] >= 6:
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
                        sorted_f = sorted(faces, key=lambda f: f["cx"])
                        left_samples.append((t, sorted_f[0]["cx"], sorted_f[0]["cy"], sorted_f[0]["h"]))
                        right_samples.append((t, sorted_f[-1]["cx"], sorted_f[-1]["cy"], sorted_f[-1]["h"]))
                    elif len(faces) == 1:
                        f = faces[0]
                        if f["cx"] < 0.5:
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
                if spread1 < 0.06:
                    final_cx1 = np.full(shot_len, float(np.median(med_cx1)))
                    final_cy1 = np.full(shot_len, float(np.median(med_cy1)))
                else:
                    final_cx1 = zero_phase_gaussian_smooth(med_cx1, radius=12, max_vel=0.006)
                    final_cy1 = zero_phase_gaussian_smooth(med_cy1, radius=12, max_vel=0.006)

                spread2 = max(np.ptp(med_cx2), np.ptp(med_cy2))
                if spread2 < 0.06:
                    final_cx2 = np.full(shot_len, float(np.median(med_cx2)))
                    final_cy2 = np.full(shot_len, float(np.median(med_cy2)))
                else:
                    final_cx2 = zero_phase_gaussian_smooth(med_cx2, radius=12, max_vel=0.006)
                    final_cy2 = zero_phase_gaussian_smooth(med_cy2, radius=12, max_vel=0.006)

                for k, f_idx in enumerate(range(shot_start, shot_end)):
                    y1 = np.clip(final_cy1[k] - 0.30 * lock_h1, 0.0, 1.0 - lock_h1)
                    x1 = np.clip(final_cx1[k] - 0.50 * lock_w1, 0.0, 1.0 - lock_w1)
                    y2 = np.clip(final_cy2[k] - 0.30 * lock_h2, 0.0, 1.0 - lock_h2)
                    x2 = np.clip(final_cx2[k] - 0.50 * lock_w2, 0.0, 1.0 - lock_w2)

                    plan[f_idx] = {
                        "layout_type": "2_person",
                        "box_p1": {"x": float(x1), "y": float(y1), "w": lock_w1, "h": lock_h1},
                        "box_p2": {"x": float(x2), "y": float(y2), "w": lock_w2, "h": lock_h2},
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
                if spread < 0.06:
                    final_cx = np.full(shot_len, float(np.median(med_cx)))
                    final_cy = np.full(shot_len, float(np.median(med_cy)))
                else:
                    final_cx = zero_phase_gaussian_smooth(med_cx, radius=12, max_vel=0.006)
                    final_cy = zero_phase_gaussian_smooth(med_cy, radius=12, max_vel=0.006)

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
        fb_w = float(fb_initial.get("w", 0.30))
        fb_h = float(fb_initial.get("h", 0.25))

        # Segment into step-locked holds
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

        # Generate per-frame positions with 6-frame smooth glide between holds
        per_frame_webcam: list[tuple[float, float]] = [(current_lock_x, current_lock_y)] * total_frames
        kf_idx = 0
        cur_x, cur_y = webcam_keyframes[0][1], webcam_keyframes[0][2]

        for f in range(total_frames):
            if kf_idx + 1 < len(webcam_keyframes):
                target_f, tgt_x, tgt_y = webcam_keyframes[kf_idx + 1]
                if f >= target_f:
                    cur_x, cur_y = tgt_x, tgt_y
                    kf_idx += 1
                elif f >= target_f - 6:
                    glide_alpha = (f - (target_f - 6)) / 6.0
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
) -> tuple[int, str]:
    """Execute Pass 2: sub-pixel affine rendering and raw BGR24 streaming into FFmpeg.

    Allocates 25-100% progress.
    """
    total_target_frames = sum(max(1, int(round((e - s) * fps))) for s, e in intervals)

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

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return 1, f"Could not reopen source video for Pass 2: {video_path}"

    global_frame_idx = 0
    last_reported_pct = -1

    try:
        for seg_idx, (seg_start, seg_end) in enumerate(intervals):
            cap.set(cv2.CAP_PROP_POS_MSEC, max(0.0, seg_start) * 1000.0)
            seg_target_frames = max(1, int(round((seg_end - seg_start) * fps)))
            seg_emitted = 0

            while seg_emitted < seg_target_frames:
                ret, frame = cap.read()
                if not ret or frame is None:
                    break

                step_plan = plan[min(global_frame_idx, len(plan) - 1)]
                l_type = step_plan.get("layout_type", "0_person")
                out_frame: np.ndarray | None = None

                if is_podcast_dual:
                    if l_type == "2_person":
                        b1 = step_plan["box_p1"]
                        b2 = step_plan["box_p2"]

                        if layout == "split_vertical":
                            top_h = max(2, min(out_h - 2, int(out_h * split_ratio / 100) & ~1))
                            bot_h = out_h - top_h
                            p1 = subpixel_render_pane(frame, b1, out_w, top_h, fit_mode=fit_mode)
                            p2 = subpixel_render_pane(frame, b2, out_w, bot_h, fit_mode=fit_mode)
                            out_frame = np.vstack([p1, p2])

                        elif layout == "split_inverted":
                            top_h = max(2, min(out_h - 2, int(out_h * split_ratio / 100) & ~1))
                            bot_h = out_h - top_h
                            p2 = subpixel_render_pane(frame, b2, out_w, top_h, fit_mode=fit_mode)
                            p1 = subpixel_render_pane(frame, b1, out_w, bot_h, fit_mode=fit_mode)
                            out_frame = np.vstack([p2, p1])

                        elif layout == "side_by_side_blur":
                            left_w = (out_w // 2) & ~1
                            right_w = out_w - left_w
                            pane_h = max(2, min(out_h, int(left_w * (16 / 9)) & ~1))
                            overlay_y = max(0, (out_h - pane_h) // 2)
                            p1 = subpixel_render_pane(frame, b1, left_w, pane_h, fit_mode=fit_mode)
                            p2 = subpixel_render_pane(frame, b2, right_w, pane_h, fit_mode=fit_mode)
                            dual_fg = np.hstack([p1, p2])
                            bg = render_blurred_fill(frame, out_w, out_h)
                            bg[overlay_y:overlay_y + pane_h, 0:out_w] = dual_fg
                            out_frame = bg

                        elif layout == "wide_plus_dual":
                            top_h = 690 if (out_w, out_h) == (1080, 1920) else max(2, int(out_h * 0.36) & ~1)
                            bot_h = out_h - top_h
                            left_w = (out_w // 2) & ~1
                            right_w = out_w - left_w
                            top_wide = subpixel_render_pane(frame, {"x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0}, out_w, top_h, fit_mode="fill")
                            p1 = subpixel_render_pane(frame, b1, left_w, bot_h, fit_mode=fit_mode)
                            p2 = subpixel_render_pane(frame, b2, right_w, bot_h, fit_mode=fit_mode)
                            bot_dual = np.hstack([p1, p2])
                            out_frame = np.vstack([top_wide, bot_dual])

                        else:  # podcast_active_speaker in dual shot
                            out_frame = subpixel_render_pane(frame, b1, out_w, out_h, fit_mode=fit_mode)

                    elif l_type == "1_person":
                        out_frame = subpixel_render_pane(frame, step_plan["box_p1"], out_w, out_h, fit_mode=fit_mode)

                    else:  # 0_person
                        out_frame = render_blurred_fill(frame, out_w, out_h)

                elif mode in ("gaming", "screen_presenter"):
                    wb = step_plan["webcam_box"]
                    gb = step_plan["gameplay_box"]

                    if layout == "pip":
                        fb_w = max(0.01, float(wb["w"]))
                        fb_h = max(0.01, float(wb["h"]))
                        pip_w = max(160, (out_w // 3) & ~1)
                        pip_h = max(90, int(pip_w * (fb_h / fb_w) * (src_h / src_w)) & ~1)
                        main_p = subpixel_render_pane(frame, gb, out_w, out_h, fit_mode=fit_mode)
                        pip_p = subpixel_render_pane(frame, wb, pip_w, pip_h, fit_mode="fill")
                        main_p[20:20 + pip_h, out_w - pip_w - 20:out_w - 20] = pip_p
                        out_frame = main_p

                    elif layout == "split_inverted":
                        top_h = max(2, min(out_h - 2, int(out_h * split_ratio / 100) & ~1))
                        bot_h = out_h - top_h
                        if mode == "screen_presenter":
                            top_p = subpixel_render_pane(frame, wb, out_w, top_h, fit_mode=fit_mode)
                            bot_p = subpixel_render_pane(frame, gb, out_w, bot_h, fit_mode=fit_mode)
                        else:
                            top_p = subpixel_render_pane(frame, gb, out_w, top_h, fit_mode=fit_mode)
                            bot_p = subpixel_render_pane(frame, wb, out_w, bot_h, fit_mode=fit_mode)
                        out_frame = np.vstack([top_p, bot_p])

                    else:  # split_vertical
                        top_h = max(2, min(out_h - 2, int(out_h * split_ratio / 100) & ~1))
                        bot_h = out_h - top_h
                        if mode == "screen_presenter":
                            top_p = subpixel_render_pane(frame, gb, out_w, top_h, fit_mode=fit_mode)
                            bot_p = subpixel_render_pane(frame, wb, out_w, bot_h, fit_mode=fit_mode)
                        else:
                            top_p = subpixel_render_pane(frame, wb, out_w, top_h, fit_mode=fit_mode)
                            bot_p = subpixel_render_pane(frame, gb, out_w, bot_h, fit_mode=fit_mode)
                        out_frame = np.vstack([top_p, bot_p])

                else:
                    # Single-Person Layouts (fullscreen_crop, punch_in_zoom)
                    if l_type == "1_person":
                        out_frame = subpixel_render_pane(frame, step_plan["box_p1"], out_w, out_h, fit_mode=fit_mode)
                    else:
                        out_frame = render_blurred_fill(frame, out_w, out_h)

                if out_frame is None or out_frame.shape[0] != out_h or out_frame.shape[1] != out_w:
                    out_frame = render_blurred_fill(frame, out_w, out_h)

                try:
                    assert proc.stdin
                    proc.stdin.write(out_frame.tobytes())
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
        cap.release()
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

    # Inspect source video metadata
    cap_info = cv2.VideoCapture(args.video_path)
    if not cap_info.isOpened():
        print(f"ERROR: Could not open video {args.video_path}", file=sys.stderr)
        sys.exit(1)
    fps = cap_info.get(cv2.CAP_PROP_FPS) or 30.0
    if fps <= 0.0 or fps > 120.0:
        fps = 30.0
    src_w = int(cap_info.get(cv2.CAP_PROP_FRAME_WIDTH)) or 1920
    src_h = int(cap_info.get(cv2.CAP_PROP_FRAME_HEIGHT)) or 1080
    cap_info.release()

    # Pass 1 — Fast Shot & Trajectory Analysis
    total_frames, frame_cuts, sampled_detections, sampled_webcam = run_pass_1(
        video_path=args.video_path,
        intervals=intervals,
        fps=fps,
        src_w=src_w,
        src_h=src_h,
        config=config_data,
    )

    # Between Passes: Shot-Level Stabilization & Zero-Phase Smoothing Plan
    plan = build_trajectory_plan(
        total_frames=total_frames,
        frame_cuts=frame_cuts,
        sampled_detections=sampled_detections,
        sampled_webcam=sampled_webcam,
        config=config_data,
        out_w=args.out_w,
        out_h=args.out_h,
        src_w=src_w,
        src_h=src_h,
        fps=fps,
        intervals=intervals,
    )

    # Pass 2 — Sub-Pixel Rendering & FFmpeg Pipe (with automatic NVENC -> libx264 fallback)
    initial_encoder = args.encoder or "h264_nvenc"
    encoders_to_try = [initial_encoder]
    if initial_encoder == "h264_nvenc":
        encoders_to_try.append("libx264")

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
            out_w=args.out_w,
            out_h=args.out_h,
            fps=fps,
            src_w=src_w,
            src_h=src_h,
            encoder=enc,
            normalize=args.normalize,
            has_audio=args.has_audio,
            ass_path=args.ass_path,
            watermark_path=args.watermark_path,
            cwd=args.cwd,
        )
        last_stderr = stderr
        if code == 0 and Path(args.output_path).is_file() and Path(args.output_path).stat().st_size > 0:
            success = True
            used_encoder = enc
            break

        Path(args.output_path).unlink(missing_ok=True)
        print(f"[REFRAME_WORKER WARNING] Encoder {enc} failed (code {code}). Stderr tail:\n{stderr[-1000:]}", flush=True, file=sys.stderr)

    if success:
        print(f"COMPLETE:{json.dumps({'encoder': used_encoder, 'output_path': args.output_path})}", flush=True)
        sys.exit(0)
    else:
        print(f"ERROR:{json.dumps({'error': 'All encoders failed', 'stderr': last_stderr[-2000:]})}", flush=True, file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
