"""Phase 4 — FFmpeg filter_complex builder for all 5 framing modes.

All renders enforce:
  -fps_mode cfr          → VFR-to-CFR sync protection (OBS / ShadowPlay recordings)
  h264_nvenc (attempt)   → automatic libx264 fallback on non-zero exit
  -pix_fmt yuv420p       → Safari / QuickTime compatibility
  -movflags +faststart   → web streaming moov atom placement
"""

from __future__ import annotations
import shutil
import subprocess
from pathlib import Path

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
    w = max(1, min(int(box.w * src_w), src_w - x))
    h = max(1, min(int(box.h * src_h), src_h - y))
    return x, y, w, h


def _safe_crop(box: RegionBox, src_w: int, src_h: int, label_in: str, label_out: str) -> str:
    """Produce a crop+scale filter segment."""
    x, y, w, h = _frac_to_px(box, src_w, src_h)
    return f"[{label_in}]crop={w}:{h}:{x}:{y}[{label_out}]"


def _scale_to(label_in: str, label_out: str, out_w: int, out_h: int) -> str:
    return (
        f"[{label_in}]scale={out_w}:{out_h}:force_original_aspect_ratio=decrease,"
        f"pad={out_w}:{out_h}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1:1[{label_out}]"
    )


def _blurred_fill(out_w: int, out_h: int) -> str:
    """Produce a Gaussian-blurred background padded to output size + sharp centred foreground overlay."""
    # [0:v] → blurred bg   [0:v] → sharp fg
    fc = (
        f"[0:v]scale={out_w}:{out_h}:force_original_aspect_ratio=increase,"
        f"crop={out_w}:{out_h},gblur=sigma=20[bg];"
        f"[0:v]scale={out_w}:{out_h}:force_original_aspect_ratio=decrease,"
        f"pad={out_w}:{out_h}:(ow-iw)/2:(oh-ih)/2:color=black@0,setsar=1:1[fg];"
        f"[bg][fg]overlay=(W-w)/2:(H-h)/2[vout]"
    )
    return fc


def _pip_overlay(gameplay_box: RegionBox | None, facecam_box: RegionBox | None,
                 src_w: int, src_h: int, out_w: int, out_h: int) -> str:
    """Picture-in-Picture: gameplay fullscreen + facecam corner pip."""
    # Main content fills output; facecam overlaid at top-right 25% width
    pip_w = out_w // 4
    pip_h = int(pip_w * (facecam_box.h / facecam_box.w)) if facecam_box and facecam_box.w else out_h // 4
    pip_w = max(pip_w, 160)
    pip_h = max(pip_h, 90)
    margin = 20

    if gameplay_box:
        gx, gy, gw, gh = _frac_to_px(gameplay_box, src_w, src_h)
        fc = f"[0:v]crop={gw}:{gh}:{gx}:{gy},scale={out_w}:{out_h}:force_original_aspect_ratio=decrease,pad={out_w}:{out_h}:(ow-iw)/2:(oh-ih)/2:black,setsar=1:1[main];"
    else:
        fc = f"[0:v]scale={out_w}:{out_h}:force_original_aspect_ratio=decrease,pad={out_w}:{out_h}:(ow-iw)/2:(oh-ih)/2:black,setsar=1:1[main];"

    if facecam_box:
        fx, fy, fw, fh = _frac_to_px(facecam_box, src_w, src_h)
        pip_x = out_w - pip_w - margin
        pip_y = margin
        fc += (
            f"[0:v]crop={fw}:{fh}:{fx}:{fy},scale={pip_w}:{pip_h},setsar=1:1[pip];"
            f"[main][pip]overlay={pip_x}:{pip_y}[vout]"
        )
    else:
        fc += "[main]copy[vout]"

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

    The output stream is always named [vout].
    Audio stream [0:a] is passed through unchanged via -map [vout] -map 0:a.
    """
    out_w, out_h = ASPECT_DIMENSIONS.get(config.aspect_ratio, (1080, 1920))
    mode = config.framing_mode
    layout = config.layout_template
    fc = ""

    # -----------------------------------------------------------------------
    # 1. FULLSCREEN / BLURRED FILL (single-region modes)
    # -----------------------------------------------------------------------
    if layout == "blurred_fill":
        fc = _blurred_fill(out_w, out_h)

    elif layout == "fullscreen_crop":
        # Crop the gameplay/main box and fill output
        box = config.gameplay_box or config.facecam_box
        if box:
            x, y, w, h = _frac_to_px(box, src_w, src_h)
            fc = (
                f"[0:v]crop={w}:{h}:{x}:{y},"
                f"scale={out_w}:{out_h}:force_original_aspect_ratio=decrease,"
                f"pad={out_w}:{out_h}:(ow-iw)/2:(oh-ih)/2:black,setsar=1:1[vout]"
            )
        else:
            fc = _blurred_fill(out_w, out_h)

    # -----------------------------------------------------------------------
    # 2. PICTURE-IN-PICTURE
    # -----------------------------------------------------------------------
    elif layout == "pip":
        fc = _pip_overlay(config.gameplay_box, config.facecam_box, src_w, src_h, out_w, out_h)

    # -----------------------------------------------------------------------
    # 3. SPLIT VERTICAL — top (facecam/face) / bottom (gameplay/content)
    # -----------------------------------------------------------------------
    else:  # 'split_vertical' or fallback
        split = max(10, min(90, config.split_ratio))
        top_h = int(out_h * split / 100)
        bot_h = out_h - top_h

        if mode == "gaming":
            # Top = facecam, Bottom = gameplay
            # If no face detected, fall back to blurred fill for the whole frame
            if config.facecam_box and config.gameplay_box and config.face_detected is not False:
                facecam_parts = _safe_crop(config.facecam_box, src_w, src_h, "0:v", "face_raw")
                fc_top = _scale_to("face_raw", "top", out_w, top_h)
                gameplay_parts = _safe_crop(config.gameplay_box, src_w, src_h, "0:v", "game_raw")
                fc_bot = _scale_to("game_raw", "bot", out_w, bot_h)
                fc = (
                    f"{facecam_parts};"
                    f"{fc_top};"
                    f"{gameplay_parts};"
                    f"{fc_bot};"
                    f"[top][bot]vstack=inputs=2[vout]"
                )
            else:
                # No-face fallback: fullscreen gameplay blurred fill
                fc = _blurred_fill(out_w, out_h)

        elif mode == "reaction":
            # Left = reactor (facecam), Right = content — but we do it vertically for 9:16
            if config.facecam_box and config.gameplay_box:
                fc_face = _safe_crop(config.facecam_box, src_w, src_h, "0:v", "react_raw")
                fc_top = _scale_to("react_raw", "top", out_w, top_h)
                fc_content = _safe_crop(config.gameplay_box, src_w, src_h, "0:v", "content_raw")
                fc_bot = _scale_to("content_raw", "bot", out_w, bot_h)
                fc = (
                    f"{fc_face};"
                    f"{fc_top};"
                    f"{fc_content};"
                    f"{fc_bot};"
                    f"[top][bot]vstack=inputs=2[vout]"
                )
            else:
                fc = _blurred_fill(out_w, out_h)

        elif mode in ("podcast", "talking_head") and speaker_tracks:
            tracked_boxes = [row for row in speaker_tracks if row.get("box")]
            if tracked_boxes:
                first = tracked_boxes[0]["box"]
                crop_w = max(2, min(src_w, int(first["w"] * src_w * 1.55))) & ~1
                crop_h = max(2, min(src_h, int(first["h"] * src_h * 1.75))) & ~1
                default_x = (src_w - crop_w) // 2
                default_y = (src_h - crop_h) // 2
                # Fixed crop size avoids zoom pumping. Cut events return to center,
                # while active speaker boxes update its position over time.
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
                    f"pad={out_w}:{out_h}:(ow-iw)/2:(oh-ih)/2:black,setsar=1:1[vout]"
                )
            else:
                fc = _blurred_fill(out_w, out_h)

        elif mode in ("podcast", "talking_head"):
            # Single tracked face region centred; blurred background behind
            box = config.facecam_box or config.gameplay_box
            if box:
                x, y, w, h = _frac_to_px(box, src_w, src_h)
                fc = (
                    # Blurred background
                    f"[0:v]scale={out_w}:{out_h}:force_original_aspect_ratio=increase,"
                    f"crop={out_w}:{out_h},gblur=sigma=25[bg];"
                    # Sharp face crop scaled to fit
                    f"[0:v]crop={w}:{h}:{x}:{y},"
                    f"scale={out_w}:{out_h}:force_original_aspect_ratio=decrease,"
                    f"pad={out_w}:{out_h}:(ow-iw)/2:(oh-ih)/2:color=black@0,setsar=1:1[fg];"
                    f"[bg][fg]overlay=(W-w)/2:(H-h)/2[vout]"
                )
            else:
                fc = _blurred_fill(out_w, out_h)

        elif mode == "screen_presenter":
            # Bottom = presenter (facecam) small, Top = screen (gameplay)
            if config.facecam_box and config.gameplay_box and config.face_detected is not False:
                fc_screen = _safe_crop(config.gameplay_box, src_w, src_h, "0:v", "screen_raw")
                fc_top = _scale_to("screen_raw", "top", out_w, top_h)
                fc_pres = _safe_crop(config.facecam_box, src_w, src_h, "0:v", "pres_raw")
                fc_bot = _scale_to("pres_raw", "bot", out_w, bot_h)
                fc = (
                    f"{fc_screen};"
                    f"{fc_top};"
                    f"{fc_pres};"
                    f"{fc_bot};"
                    f"[top][bot]vstack=inputs=2[vout]"
                )
            else:
                fc = _blurred_fill(out_w, out_h)

        else:
            fc = _blurred_fill(out_w, out_h)

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

        # Replace [vout] with [pre_wm] and add watermark overlay
        fc = fc.replace("[vout]", "[pre_wm]")
        fc += (
            f";[1:v]scale={out_w}*{wm_scale}:-1,"
            f"format=argb,geq='p(X,Y)':a='{wm_opacity}*alpha(X,Y)'[wm];"
            f"[pre_wm][wm]overlay={wm_x}:{wm_y}[vout]"
        )

    if ass_path and Path(ass_path).is_file():
        # FFmpeg filter paths require escaping Windows drive colons and separators.
        escaped_ass = str(Path(ass_path).resolve()).replace("\\", "/").replace(":", r"\:").replace("'", r"\'")
        fc = fc.replace("[vout]", "[pre_ass]")
        fc += f";[pre_ass]ass='{escaped_ass}'[vout]"

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
        "-map", "[vout]",
        "-map", "0:a?",
        "-fps_mode", "cfr",        # ← VFR-to-CFR sync protection (output side)
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
    for encoder in ("h264_nvenc", "libx264"):
        cmd = build_ffmpeg_cmd(
            input_path, output_path, config, src_w, src_h, start_sec, end_sec, encoder,
            speaker_tracks=speaker_tracks, ass_path=ass_path,
        )
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
        )
        if result.returncode == 0:
            return encoder, result.stderr.decode("utf-8", errors="ignore")
        # Any NVENC failure (driver, device busy, unsupported preset, or codec
        # setup) gets a CPU retry so the configured render still completes.

    # If libx264 also failed raise
    raise RuntimeError(f"FFmpeg render failed with both h264_nvenc and libx264")
