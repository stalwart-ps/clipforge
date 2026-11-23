"""Phase 4 — FFmpeg filter_complex builder for all 5 framing modes.

All renders enforce:
  -fps_mode cfr          → VFR-to-CFR sync protection (OBS / ShadowPlay recordings)
  h264_nvenc (attempt)   → automatic libx264 fallback on non-zero exit
  -pix_fmt yuv420p       → Safari / QuickTime compatibility
  -movflags +faststart   → web streaming moov atom placement
"""

from __future__ import annotations
import logging
import shutil
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

from app.framing.schemas import AspectRatio, FramingConfig, RegionBox


# Output dimensions per aspect ratio
ASPECT_DIMENSIONS: dict[str, tuple[int, int]] = {
    "9:16": (1080, 1920),
    "1:1": (1080, 1080),
    "16:9": (1920, 1080),
}


def _frac_to_px(box: RegionBox, src_w: int, src_h: int) -> tuple[int, int, int, int]:
    """Convert normalized 0–1 fractions to absolute pixel crop coordinates."""
    x = max(0, int(box.x * src_w))
    y = max(0, int(box.y * src_h))
    w = max(2, min(int(box.w * src_w), src_w - x) & ~1)
    h = max(2, min(int(box.h * src_h), src_h - y) & ~1)
    if x + w > src_w:
        x = max(0, src_w - w)
    if y + h > src_h:
        y = max(0, src_h - h)
    return x, y, w, h


def _safe_crop(box: RegionBox, src_w: int, src_h: int, label_in: str, label_out: str) -> str:
    """Produce a crop+scale filter segment."""
    x, y, w, h = _frac_to_px(box, src_w, src_h)
    return f"[{label_in}]crop={w}:{h}:{x}:{y}[{label_out}]"


def _dynamic_or_safe_crop(
    box: RegionBox,
    src_w: int,
    src_h: int,
    label_in: str,
    label_out: str,
    tracks: list[dict] | None = None,
) -> str:
    """Produce a static or animated crop filter segment keeping w and h strictly even."""
    x, y, w, h = _frac_to_px(box, src_w, src_h)
    w = max(2, min(w, src_w)) & ~1
    h = max(2, min(h, src_h)) & ~1
    if not tracks:
        return f"[{label_in}]crop={w}:{h}:{x}:{y}[{label_out}]"

    x_expr, y_expr = str(x), str(y)
    for row in tracks:
        ts = max(0.0, float(row.get("time", 0.0)))
        kx = float(row.get("x", box.x))
        ky = float(row.get("y", box.y))
        px = max(0, min(src_w - w, int(kx * src_w)))
        py = max(0, min(src_h - h, int(ky * src_h)))
        x_expr = f"if(gte(t\\,{ts:.3f})\\,{px}\\,{x_expr})"
        y_expr = f"if(gte(t\\,{ts:.3f})\\,{py}\\,{y_expr})"

    return f"[{label_in}]crop={w}:{h}:x='{x_expr}':y='{y_expr}'[{label_out}]"


def _scale_and_fit(
    label_in: str,
    label_out: str,
    target_w: int,
    target_h: int,
    fit_mode: str = "fill",
) -> str:
    """Scale and fit an input stream into exact target dimensions.

    In 'fill' mode:
      scale with force_original_aspect_ratio=increase, followed by center crop.
      Notice: per specification, omit :force_divisible_by=2 on the scale step
      so FFmpeg never rounds 1px below target crop dimensions (target_w and target_h
      are kept strictly even via & ~1).

    In 'fit' mode:
      scale with force_original_aspect_ratio=decrease:force_divisible_by=2, followed by pad.
    """
    target_w = max(2, int(target_w)) & ~1
    target_h = max(2, int(target_h)) & ~1
    if fit_mode == "fill":
        return (
            f"[{label_in}]setsar=1:1,"
            f"scale={target_w}:{target_h}:force_original_aspect_ratio=increase,"
            f"crop={target_w}:{target_h}[{label_out}]"
        )
    else:
        return (
            f"[{label_in}]setsar=1:1,"
            f"scale={target_w}:{target_h}:force_original_aspect_ratio=decrease:force_divisible_by=2,"
            f"pad={target_w}:{target_h}:(ow-iw)/2:(oh-ih)/2:color=black[{label_out}]"
        )


def _scale_to(label_in: str, label_out: str, out_w: int, out_h: int, fit_mode: str = "fit") -> str:
    return _scale_and_fit(label_in, label_out, out_w, out_h, fit_mode=fit_mode)


def _blurred_fill(out_w: int, out_h: int, fg_box: RegionBox | None = None, src_w: int = 1920, src_h: int = 1080) -> str:
    """Produce a Gaussian-blurred background padded to output size + sharp centred foreground overlay."""
    out_w = max(2, int(out_w)) & ~1
    out_h = max(2, int(out_h)) & ~1
    if fg_box and (fg_box.x > 0.001 or fg_box.y > 0.001 or fg_box.w < 0.999 or fg_box.h < 0.999):
        fx, fy, fw, fh = _frac_to_px(fg_box, src_w, src_h)
        fg_expr = f"[in_b]crop={fw}:{fh}:{fx}:{fy},scale={out_w}:{out_h}:force_original_aspect_ratio=decrease:force_divisible_by=2,setsar=1:1,setpts=PTS-STARTPTS[fg_scaled]"
    else:
        fg_expr = f"[in_b]scale={out_w}:{out_h}:force_original_aspect_ratio=decrease:force_divisible_by=2,setsar=1:1,setpts=PTS-STARTPTS[fg_scaled]"

    fc = (
        "[0:v]split=2[in_a][in_b];"
        f"[in_a]scale={out_w}:{out_h}:force_original_aspect_ratio=increase,"
        f"crop={out_w}:{out_h},gblur=sigma=20,setsar=1:1,setpts=PTS-STARTPTS[bg_blur];"
        f"{fg_expr};"
        f"[bg_blur][fg_scaled]overlay=(W-w)/2:(H-h)/2[v_framed]"
    )
    return fc


def _pip_overlay(
    gameplay_box: RegionBox | None,
    facecam_box: RegionBox | None,
    src_w: int,
    src_h: int,
    out_w: int,
    out_h: int,
    facecam_tracks: list[dict] | None = None,
    fit_mode: str = "fill",
) -> str:
    """Picture-in-Picture: gameplay fullscreen + facecam corner pip."""
    out_w = max(2, int(out_w)) & ~1
    out_h = max(2, int(out_h)) & ~1
    g_box = gameplay_box or RegionBox(x=0.0, y=0.0, w=1.0, h=1.0)
    f_box = facecam_box or RegionBox(x=0.0, y=0.0, w=0.3, h=0.25)

    pip_w = max(160, (out_w // 3) & ~1)
    pip_h = max(90, int(pip_w * (f_box.h / f_box.w)) & ~1 if f_box.w else (out_h // 4) & ~1)
    margin = 20

    gx, gy, gw, gh = _frac_to_px(g_box, src_w, src_h)
    pip_x = max(0, out_w - pip_w - margin)
    pip_y = margin

    fc_main_crop = f"[in_a]crop={gw}:{gh}:{gx}:{gy}[main_raw]"
    fc_main_fit = _scale_and_fit("main_raw", "main", out_w, out_h, fit_mode=fit_mode)

    fc_pip_crop = _dynamic_or_safe_crop(f_box, src_w, src_h, "in_b", "pip_raw", tracks=facecam_tracks)
    fc_pip_fit = _scale_and_fit("pip_raw", "pip", pip_w, pip_h, fit_mode="fill")

    fc = (
        "[0:v]split=2[in_a][in_b];"
        f"{fc_main_crop};"
        f"{fc_main_fit};"
        f"{fc_pip_crop};"
        f"{fc_pip_fit};"
        f"[main][pip]overlay={pip_x}:{pip_y}[v_framed]"
    )
    return fc


def build_filter_complex(
    config: FramingConfig,
    src_w: int,
    src_h: int,
    speaker_tracks: list[dict] | None = None,
    ass_path: str | None = None,
    facecam_tracks: list[dict] | None = None,
    watermark_input_index: int = 1,
) -> tuple[str, int, int]:
    """
    Build the -filter_complex string for the given FramingConfig.

    Returns:
        (filter_complex_str, out_w, out_h)

    The framed video label is [v_framed], chained into [v_final] (with optional ass filter).
    Audio stream [0:a] is passed through unchanged via -map [v_final] -map 0:a.
    """
    out_w, out_h = ASPECT_DIMENSIONS.get(config.aspect_ratio, (1080, 1920))
    out_w = max(2, int(out_w)) & ~1
    out_h = max(2, int(out_h)) & ~1
    mode = config.framing_mode
    layout = config.layout_template
    fit_mode = getattr(config, "pane_fit_mode", "fill") or "fill"
    fc = ""

    # Fallback boxes ensuring sharp rendering even if boxes weren't populated
    face_box = config.facecam_box or RegionBox(x=0.0, y=0.0, w=0.3, h=0.25)
    game_box = config.gameplay_box or RegionBox(x=0.0, y=0.0, w=1.0, h=1.0)

    # -----------------------------------------------------------------------
    # 1. BLURRED FILL
    # -----------------------------------------------------------------------
    if layout == "blurred_fill":
        fc = _blurred_fill(out_w, out_h, config.gameplay_box or config.facecam_box, src_w, src_h)

    # -----------------------------------------------------------------------
    # 2. FULLSCREEN CROP
    # -----------------------------------------------------------------------
    elif layout == "fullscreen_crop":
        box = (
            (config.facecam_box or config.gameplay_box or RegionBox(x=0.0, y=0.0, w=1.0, h=1.0))
            if mode in ("podcast", "talking_head")
            else (config.gameplay_box or config.facecam_box or RegionBox(x=0.0, y=0.0, w=1.0, h=1.0))
        )
        x, y, w, h = _frac_to_px(box, src_w, src_h)
        fc_crop = f"[0:v]crop={w}:{h}:{x}:{y}[raw]"
        fc_fit = _scale_and_fit("raw", "v_framed", out_w, out_h, fit_mode=fit_mode)
        fc = f"{fc_crop};{fc_fit}"

    # -----------------------------------------------------------------------
    # 3. PICTURE-IN-PICTURE (PIP)
    # -----------------------------------------------------------------------
    elif layout == "pip":
        fc = _pip_overlay(
            config.gameplay_box,
            config.facecam_box,
            src_w,
            src_h,
            out_w,
            out_h,
            facecam_tracks=facecam_tracks,
            fit_mode=fit_mode,
        )

    # -----------------------------------------------------------------------
    # 4. PUNCH-IN ZOOM (Talking Head)
    # -----------------------------------------------------------------------
    elif layout == "punch_in_zoom":
        box = config.facecam_box or config.gameplay_box or RegionBox(x=0.0, y=0.0, w=1.0, h=1.0)
        fx, fy, fw, fh = _frac_to_px(box, src_w, src_h)
        zw = max(2, int(fw / 1.10)) & ~1
        zh = max(2, int(fh / 1.10)) & ~1
        zx = max(0, min(src_w - zw, fx + (fw - zw) // 2))
        zy = max(0, min(src_h - zh, fy + (fh - zh) // 2))

        fc = (
            "[0:v]split=2[in_norm][in_zoom];"
            f"[in_norm]crop={fw}:{fh}:{fx}:{fy}[norm_raw];"
            + _scale_and_fit("norm_raw", "norm", out_w, out_h, fit_mode=fit_mode)
            + ";"
            f"[in_zoom]crop={zw}:{zh}:{zx}:{zy}[zoom_raw];"
            + _scale_and_fit("zoom_raw", "zoomed", out_w, out_h, fit_mode=fit_mode)
            + ";"
            "[norm][zoomed]overlay=0:0:enable='gte(mod(t\\,6)\\,3)'[v_framed]"
        )

    # -----------------------------------------------------------------------
    # 5. PODCAST ACTIVE SPEAKER (Fullscreen 9:16 Auto-Cutting)
    # -----------------------------------------------------------------------
    elif layout == "podcast_active_speaker":
        p1_box = config.facecam_box or RegionBox(x=0.1, y=0.15, w=0.38, h=0.65)
        p2_box = config.gameplay_box or RegionBox(x=0.52, y=0.15, w=0.38, h=0.65)
        p1_x, p1_y, p1_w, p1_h = _frac_to_px(p1_box, src_w, src_h)
        p2_x, p2_y, p2_w, p2_h = _frac_to_px(p2_box, src_w, src_h)

        p2_enable = ""
        if speaker_tracks:
            p2_intervals: list[tuple[float, float]] = []
            current_start: float | None = None
            p2_cx = p2_box.x + p2_box.w / 2.0
            p1_cx = p1_box.x + p1_box.w / 2.0

            for row in speaker_tracks:
                t = float(row.get("time", 0.0))
                b = row.get("box")
                is_p2 = False
                if row.get("active_id") == 1:
                    is_p2 = True
                elif b:
                    bcx = float(b.get("x", 0.0)) + float(b.get("w", 0.0)) / 2.0
                    if abs(bcx - p2_cx) < abs(bcx - p1_cx):
                        is_p2 = True

                if is_p2:
                    if current_start is None:
                        current_start = t
                else:
                    if current_start is not None:
                        if t > current_start + 0.3:
                            p2_intervals.append((current_start, t))
                        current_start = None
            if current_start is not None:
                p2_intervals.append((current_start, current_start + 10.0))

            if p2_intervals:
                p2_enable = "+".join(f"between(t\\,{s:.3f}\\,{e:.3f})" for s, e in p2_intervals[:25])

        if not p2_enable:
            # Clean fallback when speaker tracks are empty or no transitions
            p2_enable = "gte(mod(t\\,12)\\,6)"

        fc = (
            "[0:v]split=2[in_p1][in_p2];"
            f"[in_p1]crop={p1_w}:{p1_h}:{p1_x}:{p1_y}[p1_raw];"
            + _scale_and_fit("p1_raw", "p1_full", out_w, out_h, fit_mode=fit_mode)
            + ";"
            f"[in_p2]crop={p2_w}:{p2_h}:{p2_x}:{p2_y}[p2_raw];"
            + _scale_and_fit("p2_raw", "p2_full", out_w, out_h, fit_mode=fit_mode)
            + ";"
            f"[p1_full][p2_full]overlay=0:0:enable='{p2_enable}'[v_framed]"
        )

    # -----------------------------------------------------------------------
    # 6. SIDE-BY-SIDE BLUR (Dual Portrait Panes over Blurred Background)
    # -----------------------------------------------------------------------
    elif layout == "side_by_side_blur":
        left_w = (out_w // 2) & ~1
        right_w = out_w - left_w
        pane_h = max(2, min(out_h, int(left_w * (16 / 9)) & ~1))
        overlay_y = max(0, (out_h - pane_h) // 2) & ~1

        p1_box = config.facecam_box or RegionBox(x=0.0, y=0.0, w=0.5, h=1.0)
        p2_box = config.gameplay_box or RegionBox(x=0.5, y=0.0, w=0.5, h=1.0)
        p1_x, p1_y, p1_w, p1_h = _frac_to_px(p1_box, src_w, src_h)
        p2_x, p2_y, p2_w, p2_h = _frac_to_px(p2_box, src_w, src_h)

        fc = (
            "[0:v]split=3[in_bg][in_p1][in_p2];"
            f"[in_bg]scale={out_w}:{out_h}:force_original_aspect_ratio=increase,"
            f"crop={out_w}:{out_h},gblur=sigma=20,setsar=1:1,setpts=PTS-STARTPTS[bg_blur];"
            f"[in_p1]crop={p1_w}:{p1_h}:{p1_x}:{p1_y}[p1_raw];"
            + _scale_and_fit("p1_raw", "p1_pane", left_w, pane_h, fit_mode=fit_mode)
            + ";"
            f"[in_p2]crop={p2_w}:{p2_h}:{p2_x}:{p2_y}[p2_raw];"
            + _scale_and_fit("p2_raw", "p2_pane", right_w, pane_h, fit_mode=fit_mode)
            + ";"
            "[p1_pane][p2_pane]hstack=inputs=2[dual_fg];"
            f"[bg_blur][dual_fg]overlay=0:{overlay_y}[v_framed]"
        )

    # -----------------------------------------------------------------------
    # 7. WIDE PLUS DUAL (Wide Top + Dual Bottom Side-by-Side)
    # -----------------------------------------------------------------------
    elif layout == "wide_plus_dual":
        top_h = max(2, int(out_h * 0.40) & ~1)
        bot_h = out_h - top_h
        left_w = (out_w // 2) & ~1
        right_w = out_w - left_w

        wide_box = config.gameplay_box or RegionBox(x=0.0, y=0.0, w=1.0, h=1.0)
        p1_box = config.facecam_box or RegionBox(x=0.0, y=0.0, w=0.5, h=1.0)
        p2_box = config.gameplay_box or RegionBox(x=0.5, y=0.0, w=0.5, h=1.0)

        wx, wy, ww, wh = _frac_to_px(wide_box, src_w, src_h)
        p1_x, p1_y, p1_w, p1_h = _frac_to_px(p1_box, src_w, src_h)
        p2_x, p2_y, p2_w, p2_h = _frac_to_px(p2_box, src_w, src_h)

        fc = (
            "[0:v]split=3[in_wide][in_p1][in_p2];"
            f"[in_wide]crop={ww}:{wh}:{wx}:{wy}[wide_raw];"
            + _scale_and_fit("wide_raw", "wide_top", out_w, top_h, fit_mode=fit_mode)
            + ";"
            f"[in_p1]crop={p1_w}:{p1_h}:{p1_x}:{p1_y}[p1_raw];"
            + _scale_and_fit("p1_raw", "p1_pane", left_w, bot_h, fit_mode=fit_mode)
            + ";"
            f"[in_p2]crop={p2_w}:{p2_h}:{p2_x}:{p2_y}[p2_raw];"
            + _scale_and_fit("p2_raw", "p2_pane", right_w, bot_h, fit_mode=fit_mode)
            + ";"
            "[p1_pane][p2_pane]hstack=inputs=2[bot_dual];"
            "[wide_top][bot_dual]vstack=inputs=2[v_framed]"
        )

    # -----------------------------------------------------------------------
    # 8. SPLIT INVERTED (Game / Screen / Video Top, Face / Presenter Bottom)
    # -----------------------------------------------------------------------
    elif layout == "split_inverted":
        split = max(10, min(90, config.split_ratio))
        top_h = max(2, min(out_h - 2, int(out_h * split / 100) & ~1))
        bot_h = out_h - top_h

        if mode == "screen_presenter":
            # Presenter Top, Screen Bottom
            fc_top_crop = _dynamic_or_safe_crop(face_box, src_w, src_h, "in_a", "top_raw", tracks=facecam_tracks)
            fc_top_fit = _scale_and_fit("top_raw", "top", out_w, top_h, fit_mode=fit_mode)
            fc_bot_crop = _safe_crop(game_box, src_w, src_h, "in_b", "bot_raw")
            fc_bot_fit = _scale_and_fit("bot_raw", "bot", out_w, bot_h, fit_mode=fit_mode)
        else:
            # Region 2 (Gameplay / Video) Top, Region 1 (Face / Reactor) Bottom
            fc_top_crop = _safe_crop(game_box, src_w, src_h, "in_a", "top_raw")
            fc_top_fit = _scale_and_fit("top_raw", "top", out_w, top_h, fit_mode=fit_mode)
            fc_bot_crop = _dynamic_or_safe_crop(face_box, src_w, src_h, "in_b", "bot_raw", tracks=facecam_tracks)
            fc_bot_fit = _scale_and_fit("bot_raw", "bot", out_w, bot_h, fit_mode=fit_mode)

        fc = (
            "[0:v]split=2[in_a][in_b];"
            f"{fc_top_crop};"
            f"{fc_top_fit};"
            f"{fc_bot_crop};"
            f"{fc_bot_fit};"
            "[top][bot]vstack=inputs=2[v_framed]"
        )

    # -----------------------------------------------------------------------
    # 9. SPLIT VERTICAL (Standard Stacked Vertical Split)
    # -----------------------------------------------------------------------
    else:
        split = max(10, min(90, config.split_ratio))
        top_h = max(2, min(out_h - 2, int(out_h * split / 100) & ~1))
        bot_h = out_h - top_h

        if mode == "screen_presenter":
            # Screen Top, Presenter Bottom
            fc_top_crop = _safe_crop(game_box, src_w, src_h, "in_a", "top_raw")
            fc_top_fit = _scale_and_fit("top_raw", "top", out_w, top_h, fit_mode=fit_mode)
            fc_bot_crop = _dynamic_or_safe_crop(face_box, src_w, src_h, "in_b", "bot_raw", tracks=facecam_tracks)
            fc_bot_fit = _scale_and_fit("bot_raw", "bot", out_w, bot_h, fit_mode=fit_mode)
        else:
            # Region 1 (Facecam / Person 1 / Reactor) Top, Region 2 (Gameplay / Person 2 / Video) Bottom
            fc_top_crop = _dynamic_or_safe_crop(face_box, src_w, src_h, "in_a", "top_raw", tracks=facecam_tracks)
            fc_top_fit = _scale_and_fit("top_raw", "top", out_w, top_h, fit_mode=fit_mode)
            fc_bot_crop = _safe_crop(game_box, src_w, src_h, "in_b", "bot_raw")
            fc_bot_fit = _scale_and_fit("bot_raw", "bot", out_w, bot_h, fit_mode=fit_mode)

        fc = (
            "[0:v]split=2[in_a][in_b];"
            f"{fc_top_crop};"
            f"{fc_top_fit};"
            f"{fc_bot_crop};"
            f"{fc_bot_fit};"
            "[top][bot]vstack=inputs=2[v_framed]"
        )

    # -----------------------------------------------------------------------
    # 4. Watermark overlay (appended if configured)
    # -----------------------------------------------------------------------
    if config.watermark and config.watermark.path and Path(config.watermark.path).exists():
        wm_path = config.watermark.path
        wm_scale = max(0.01, min(1.0, config.watermark.scale))
        wm_opacity = max(0.0, min(1.0, config.watermark.opacity))
        corner = config.watermark.corner
        margin = 20

        if corner == "top_left":
            wm_x, wm_y = margin, margin
        elif corner == "top_right":
            wm_x, wm_y = f"main_w-overlay_w-{margin}", margin
        elif corner == "bottom_left":
            wm_x, wm_y = margin, f"main_h-overlay_h-{margin}"
        else:  # bottom_right
            wm_x, wm_y = f"main_w-overlay_w-{margin}", f"main_h-overlay_h-{margin}"

        fc = fc.replace("[v_framed]", "[v_pre_wm]")
        fc += (
            f";[{watermark_input_index}:v]scale={out_w}*{wm_scale}:-1,"
            f"format=argb,geq='p(X,Y)':a='{wm_opacity}*alpha(X,Y)'[wm];"
            f"[v_pre_wm][wm]overlay={wm_x}:{wm_y}[v_framed]"
        )

    # -----------------------------------------------------------------------
    # 5. ASS Subtitle Chaining onto [v_framed]
    # -----------------------------------------------------------------------
    if ass_path:
        clean_ass = str(ass_path).replace("\\", "/")
        if ":" in clean_ass:
            clean_ass = clean_ass.replace(":", r"\:")
        clean_ass = clean_ass.replace("'", r"\'")
        fc += f";[v_framed]ass='{clean_ass}'[v_final]"
    else:
        fc += ";[v_framed]null[v_final]"

    logger.debug(
        "build_filter_complex resolved (mode=%s, aspect=%s, ass_path=%s): %s",
        config.framing_mode, config.aspect_ratio, ass_path, fc[:300],
    )
    return fc, out_w, out_h


def _get_base_encode_args(out_w: int, out_h: int, encoder: str) -> list[str]:
    """Return encoder-specific output arguments."""
    if encoder == "h264_nvenc":
        return [
            "-c:v", "h264_nvenc",
            "-preset", "p4",           # balanced NVENC preset
            "-rc:v", "vbr",
            "-cq:v", "19",
            "-b:v", "0",
            "-pix_fmt", "yuv420p",
        ]
    else:
        return [
            "-c:v", "libx264",
            "-crf", "18",
            "-preset", "fast",
            "-pix_fmt", "yuv420p",
        ]


def build_ffmpeg_cmd(
    input_path: str,
    output_path: str,
    config: FramingConfig,
    src_w: int,
    src_h: int,
    start_sec: float,
    end_sec: float,
    encoder: str = "h264_nvenc",
    watermark_path: str | None = None,
    speaker_tracks: list[dict] | None = None,
    ass_path: str | None = None,
    facecam_tracks: list[dict] | None = None,
    watermark_input_index: int = 1,
) -> list[str]:
    """
    Assemble a complete FFmpeg command for rendering a clip.

    Key invariants:
      - Input seeking (-ss before -i) for fast seek to start_sec
      - -t specifies clip duration
      - -fps_mode cfr on OUTPUT side enforces CFR (VFR-to-CFR sync protection)
      - [vout] from filter_complex is mapped to output
      - Audio copied from input 0:a
      - -movflags +faststart
    """
    # Merge watermark path into config if provided at call time
    if watermark_path and not (config.watermark and config.watermark.path):
        from app.framing.schemas import WatermarkConfig  # noqa
        config = config.model_copy(update={"watermark": WatermarkConfig(path=watermark_path)})

    has_watermark = bool(config.watermark and config.watermark.path and Path(config.watermark.path).exists())
    fc_str, out_w, out_h = build_filter_complex(
        config, src_w, src_h, speaker_tracks=speaker_tracks, ass_path=ass_path, facecam_tracks=facecam_tracks,
        watermark_input_index=watermark_input_index,
    )

    ffmpeg_bin = shutil.which("ffmpeg") or "ffmpeg"
    duration = end_sec - start_sec

    video_map = "[v_final]" if "[v_final]" in fc_str else "[vout]"
    cmd = [
        ffmpeg_bin,
        "-y",
        "-ss", str(start_sec),   # input-seek (fast keyframe seek)
        "-i", input_path,
    ]

    if has_watermark:
        cmd += ["-i", config.watermark.path]  # type: ignore[union-attr]

    cmd += [
        "-t", str(duration),
        "-filter_complex", fc_str,
        "-map", video_map,
        "-map", "0:a?",
        "-fps_mode", "cfr",        # ← VFR-to-CFR sync protection (output side)
        "-sn",
        "-c:a", "aac",
        "-b:a", "128k",
        "-movflags", "+faststart",
    ]

    cmd += _get_base_encode_args(out_w, out_h, encoder)
    cmd.append(output_path)

    return cmd


def try_render(
    input_path: str,
    output_path: str,
    config: FramingConfig,
    src_w: int,
    src_h: int,
    start_sec: float,
    end_sec: float,
    timeout: float = 1800.0,
    speaker_tracks: list[dict] | None = None,
    ass_path: str | None = None,
    facecam_tracks: list[dict] | None = None,
) -> tuple[str, str]:
    """
    Try h264_nvenc first; on failure re-run with libx264.

    Returns:
        (encoder_used, stderr_output)
    """
    run_cwd = None
    cmd_ass_path = ass_path
    if ass_path and Path(ass_path).is_file():
        ass_p = Path(ass_path)
        run_cwd = str(ass_p.parent)
        cmd_ass_path = ass_p.name

    result = None
    for encoder in ("h264_nvenc", "libx264"):
        cmd = build_ffmpeg_cmd(
            input_path, output_path, config, src_w, src_h, start_sec, end_sec, encoder,
            speaker_tracks=speaker_tracks, ass_path=cmd_ass_path, facecam_tracks=facecam_tracks,
        )
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            cwd=run_cwd,
        )
        if result.returncode == 0:
            return encoder, result.stderr.decode("utf-8", errors="ignore")

    err_msg = result.stderr.decode("utf-8", errors="ignore")[-1200:] if result else "unknown error"
    raise RuntimeError(f"FFmpeg render failed with both h264_nvenc and libx264: {err_msg}")
