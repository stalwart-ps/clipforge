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


def _scale_to(label_in: str, label_out: str, out_w: int, out_h: int) -> str:
    out_w = max(2, int(out_w)) & ~1
    out_h = max(2, int(out_h)) & ~1
    return (
        f"[{label_in}]setsar=1:1,"
        f"scale={out_w}:{out_h}:force_original_aspect_ratio=decrease:force_divisible_by=2,"
        f"pad={out_w}:{out_h}:(ow-iw)/2:(oh-ih)/2:color=black[{label_out}]"
    )


def _blurred_fill(out_w: int, out_h: int, fg_box: RegionBox | None = None, src_w: int = 1920, src_h: int = 1080) -> str:
    """Produce a Gaussian-blurred background padded to output size + sharp centred foreground overlay."""
    # [0:v]split=2[in_a][in_b]
    # [in_a] → blurred bg (scaled to cover and cropped to out_w:out_h)
    # [in_b] → sharp fg (scaled to fit within out_w:out_h with aspect ratio preserved)
    # [bg_blur][fg_scaled]overlay=(W-w)/2:(H-h)/2[v_framed]
    if fg_box and (fg_box.x > 0.001 or fg_box.y > 0.001 or fg_box.w < 0.999 or fg_box.h < 0.999):
        fx, fy, fw, fh = _frac_to_px(fg_box, src_w, src_h)
        fg_expr = f"[in_b]crop={fw}:{fh}:{fx}:{fy},scale={out_w}:{out_h}:force_original_aspect_ratio=decrease,setsar=1:1,setpts=PTS-STARTPTS[fg_scaled]"
    else:
        fg_expr = f"[in_b]scale={out_w}:{out_h}:force_original_aspect_ratio=decrease,setsar=1:1,setpts=PTS-STARTPTS[fg_scaled]"

    fc = (
        "[0:v]split=2[in_a][in_b];"
        f"[in_a]scale={out_w}:{out_h}:force_original_aspect_ratio=increase,"
        f"crop={out_w}:{out_h},gblur=sigma=20,setsar=1:1,setpts=PTS-STARTPTS[bg_blur];"
        f"{fg_expr};"
        f"[bg_blur][fg_scaled]overlay=(W-w)/2:(H-h)/2[v_framed]"
    )
    return fc


def _pip_overlay(gameplay_box: RegionBox | None, facecam_box: RegionBox | None,
                 src_w: int, src_h: int, out_w: int, out_h: int) -> str:
    """Picture-in-Picture: gameplay fullscreen + facecam corner pip."""
    g_box = gameplay_box or RegionBox(x=0.0, y=0.0, w=1.0, h=1.0)
    f_box = facecam_box or RegionBox(x=0.0, y=0.0, w=0.3, h=0.25)

    pip_w = max(160, out_w // 4)
    pip_h = max(90, int(pip_w * (f_box.h / f_box.w)) if f_box.w else out_h // 4)
    margin = 20

    gx, gy, gw, gh = _frac_to_px(g_box, src_w, src_h)
    fx, fy, fw, fh = _frac_to_px(f_box, src_w, src_h)

    pip_x = out_w - pip_w - margin
    pip_y = margin

    fc = (
        "[0:v]split=2[in_a][in_b];"
        f"[in_a]crop={gw}:{gh}:{gx}:{gy},scale={out_w}:{out_h}:force_original_aspect_ratio=decrease,pad={out_w}:{out_h}:(ow-iw)/2:(oh-ih)/2:black,setsar=1:1,setpts=PTS-STARTPTS[main];"
        f"[in_b]crop={fw}:{fh}:{fx}:{fy},scale={pip_w}:{pip_h},setsar=1:1,setpts=PTS-STARTPTS[pip];"
        f"[main][pip]overlay={pip_x}:{pip_y}[v_framed]"
    )
    return fc


def build_filter_complex(
    config: FramingConfig,
    src_w: int,
    src_h: int,
    speaker_tracks: list[dict] | None = None,
    ass_path: str | None = None,
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
    fc = ""

    # Fallback boxes ensuring sharp rendering even if boxes weren't populated
    face_box = config.facecam_box or RegionBox(x=0.0, y=0.0, w=0.3, h=0.25)
    game_box = config.gameplay_box or RegionBox(x=0.0, y=0.0, w=1.0, h=1.0)

    # -----------------------------------------------------------------------
    # 1. FULLSCREEN / BLURRED FILL
    # -----------------------------------------------------------------------
    if layout == "blurred_fill":
        fc = _blurred_fill(out_w, out_h, config.gameplay_box or config.facecam_box, src_w, src_h)

    elif layout == "fullscreen_crop":
        # Crop the gameplay/main box and fill output
        box = config.gameplay_box or config.facecam_box or RegionBox(x=0.0, y=0.0, w=1.0, h=1.0)
        x, y, w, h = _frac_to_px(box, src_w, src_h)
        fc = (
            f"[0:v]crop={w}:{h}:{x}:{y},"
            f"scale={out_w}:{out_h}:force_original_aspect_ratio=decrease,"
            f"pad={out_w}:{out_h}:(ow-iw)/2:(oh-ih)/2:black,setsar=1:1[v_framed]"
        )

    # -----------------------------------------------------------------------
    # 2. PICTURE-IN-PICTURE
    # -----------------------------------------------------------------------
    elif layout == "pip":
        fc = _pip_overlay(config.gameplay_box, config.facecam_box, src_w, src_h, out_w, out_h)

    # -----------------------------------------------------------------------
    # 3. SPLIT VERTICAL — top / bottom vertical split
    # -----------------------------------------------------------------------
    else:  # 'split_vertical' or fallback
        out_w = max(2, int(out_w)) & ~1
        out_h = max(4, int(out_h)) & ~1
        split = max(10, min(90, config.split_ratio))
        top_h = max(2, min(out_h - 2, int(out_h * split / 100) & ~1))
        bot_h = out_h - top_h

        if mode == "screen_presenter":
            # Screen/content top, presenter bottom
            fc_screen = _safe_crop(game_box, src_w, src_h, "in_a", "screen_raw")
            fc_top = _scale_to("screen_raw", "top", out_w, top_h)
            fc_pres = _safe_crop(face_box, src_w, src_h, "in_b", "pres_raw")
            fc_bot = _scale_to("pres_raw", "bot", out_w, bot_h)
            fc = (
                "[0:v]split=2[in_a][in_b];"
                f"{fc_screen};"
                f"{fc_top};"
                f"{fc_pres};"
                f"{fc_bot};"
                f"[top][bot]vstack=inputs=2[v_framed]"
            )

        elif mode in ("podcast", "talking_head") and speaker_tracks:
            tracked_boxes = [row for row in speaker_tracks if row.get("box")]
            if tracked_boxes:
                first = tracked_boxes[0]["box"]
                crop_w = max(2, min(src_w, int(first["w"] * src_w * 1.55))) & ~1
                crop_h = max(2, min(src_h, int(first["h"] * src_h * 1.75))) & ~1
                default_x = (src_w - crop_w) // 2
                default_y = (src_h - crop_h) // 2
                x_expr, y_expr = str(default_x), str(default_y)
                for row in speaker_tracks:
                    box = row.get("box")
                    if not box and not row.get("cut"):
                        continue
                    x = default_x if not box else max(0, min(src_w - crop_w, int(box["x"] * src_w + box["w"] * src_w / 2 - crop_w / 2)))
                    y = default_y if not box else max(0, min(src_h - crop_h, int(box["y"] * src_h + box["h"] * src_h / 2 - crop_h / 2)))
                    timestamp = max(0.0, float(row["time"]))
                    x_expr = f"if(gte(t\\,{timestamp:.3f})\\,{x}\\,{x_expr})"
                    y_expr = f"if(gte(t\\,{timestamp:.3f})\\,{y}\\,{y_expr})"
                fc = (
                    f"[0:v]crop={crop_w}:{crop_h}:x='{x_expr}':y='{y_expr}',"
                    f"scale={out_w}:{out_h}:force_original_aspect_ratio=decrease,"
                    f"pad={out_w}:{out_h}:(ow-iw)/2:(oh-ih)/2:black,setsar=1:1[v_framed]"
                )
            else:
                fc = _blurred_fill(out_w, out_h, game_box, src_w, src_h)

        elif mode in ("podcast", "talking_head"):
            # Single tracked face region centred; blurred background behind
            x, y, w, h = _frac_to_px(face_box, src_w, src_h)
            fc = (
                "[0:v]split=2[in_a][in_b];"
                f"[in_a]scale={out_w}:{out_h}:force_original_aspect_ratio=increase,"
                f"crop={out_w}:{out_h},gblur=sigma=25,setsar=1:1,setpts=PTS-STARTPTS[bg_blur];"
                f"[in_b]crop={w}:{h}:{x}:{y},"
                f"scale={out_w}:{out_h}:force_original_aspect_ratio=decrease,setsar=1:1,setpts=PTS-STARTPTS[fg_scaled];"
                f"[bg_blur][fg_scaled]overlay=(W-w)/2:(H-h)/2[v_framed]"
            )

        else:
            # gaming, reaction, or standard split vertical: Facecam top, Gameplay bottom
            facecam_parts = _safe_crop(face_box, src_w, src_h, "in_a", "face_raw")
            fc_top = _scale_to("face_raw", "top", out_w, top_h)
            gameplay_parts = _safe_crop(game_box, src_w, src_h, "in_b", "game_raw")
            fc_bot = _scale_to("game_raw", "bot", out_w, bot_h)
            fc = (
                "[0:v]split=2[in_a][in_b];"
                f"{facecam_parts};"
                f"{fc_top};"
                f"{gameplay_parts};"
                f"{fc_bot};"
                f"[top][bot]vstack=inputs=2[v_framed]"
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
            f";[1:v]scale={out_w}*{wm_scale}:-1,"
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
    fc_str, out_w, out_h = build_filter_complex(config, src_w, src_h, speaker_tracks, ass_path)

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
            speaker_tracks=speaker_tracks, ass_path=cmd_ass_path,
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
