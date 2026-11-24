"""Process-aware sequential batch export queue."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import shutil
import sys
import uuid
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

from app.captions.ass_generator import generate_ass
from app.core.config import settings
from app.core.process_manager import ProcessManager
from app.core.ws_manager import ws_manager
from app.exports.media import (
    build_export_command,
    calculate_keep_intervals,
    map_transcript,
    parse_silencedetect,
)
from app.exports.schemas import BatchExportRequest, ExportClip, ExportJobRead, PreviewRequest
from app.framing.auto_detect import track_facecam_overlay
from app.framing.ffmpeg_builder import build_filter_complex
from app.framing.schemas import FramingConfig, RegionBox, WatermarkConfig
from app.projects.schemas import TranscriptData


_JOBS: dict[str, ExportJobRead] = {}
_TASKS: dict[str, asyncio.Task] = {}
_CANCEL_REQUESTED: set[str] = set()
_LOCK = asyncio.Lock()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_name(value: str) -> str:
    cleaned = re.sub(r"[^\w.-]+", "_", value, flags=re.UNICODE).strip("._")
    return (cleaned or "clip")[:80]


def _snapshot(job_id: str) -> ExportJobRead:
    return ExportJobRead.model_validate(_JOBS[job_id].model_dump())


async def _publish(job_id: str) -> None:
    job = _JOBS[job_id]
    job.updated_at = _now()
    await ws_manager.broadcast(job.project_id, {"type": "export_progress", "job": job.model_dump(by_alias=True)})


async def _cancelled(job_id: str) -> bool:
    return job_id in _CANCEL_REQUESTED


async def _run_process(
    job_id: str,
    command: list[str],
    duration_sec: float,
    on_progress=None,
    cwd: str | Path | None = None,
) -> tuple[int, str]:
    """Run one FFmpeg process, drain both pipes, and always wait/reap after termination."""
    process = await asyncio.create_subprocess_exec(
        *command,
        cwd=str(cwd or settings.backend_dir),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    await ProcessManager.register_process(job_id, process.pid)
    if await _cancelled(job_id):
        await ProcessManager.cancel_project(job_id)

    stderr_tail: deque[bytes] = deque(maxlen=300)

    async def drain_stderr() -> None:
        assert process.stderr
        while line := await process.stderr.readline():
            stderr_tail.append(line)

    stderr_task = asyncio.create_task(drain_stderr())
    last_percent = -1
    try:
        assert process.stdout
        async for raw_line in process.stdout:
            if not raw_line.startswith(b"out_time_ms=") or not on_progress:
                continue
            try:
                current = int(raw_line.split(b"=", 1)[1]) / 1_000_000
                percent = min(99, int(100 * current / max(0.1, duration_sec)))
                if percent != last_percent:
                    last_percent = percent
                    await on_progress(percent)
            except (ValueError, ZeroDivisionError):
                pass
        return_code = await process.wait()
        await stderr_task
        return return_code, b"".join(stderr_tail).decode("utf-8", errors="replace")
    finally:
        if process.returncode is None:
            await ProcessManager.cancel_project(job_id)
            await process.wait()
        if not stderr_task.done():
            stderr_task.cancel()
            await asyncio.gather(stderr_task, return_exceptions=True)
        await ProcessManager.unregister_process(job_id)


async def _run_worker_process(
    job_id: str,
    command: list[str],
    on_progress=None,
    cwd: str | Path | None = None,
) -> tuple[int, str]:
    """Run a worker subprocess, drain stdout for PROGRESS:<percent>, drain stderr, and reap."""
    process = await asyncio.create_subprocess_exec(
        *command,
        cwd=str(cwd or settings.backend_dir),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    await ProcessManager.register_process(job_id, process.pid)
    if await _cancelled(job_id):
        await ProcessManager.cancel_project(job_id)

    stderr_tail: deque[bytes] = deque(maxlen=300)

    async def drain_stderr() -> None:
        assert process.stderr
        while line := await process.stderr.readline():
            stderr_tail.append(line)

    stderr_task = asyncio.create_task(drain_stderr())
    last_percent = -1
    try:
        assert process.stdout
        async for raw_line in process.stdout:
            text = raw_line.decode("utf-8", errors="replace").strip()
            if text.startswith("PROGRESS:") and on_progress:
                try:
                    percent = int(text.split(":", 1)[1].strip())
                    if percent != last_percent:
                        last_percent = percent
                        await on_progress(percent)
                except ValueError:
                    pass
        return_code = await process.wait()
        await stderr_task
        return return_code, b"".join(stderr_tail).decode("utf-8", errors="replace")
    finally:
        if process.returncode is None:
            await ProcessManager.cancel_project(job_id)
            await process.wait()
        if not stderr_task.done():
            stderr_task.cancel()
            await asyncio.gather(stderr_task, return_exceptions=True)
        await ProcessManager.unregister_process(job_id)


async def _silences(
    job_id: str, video_path: str, start_sec: float, end_sec: float,
    threshold_db: float, min_duration_sec: float,
) -> list[tuple[float, float]]:
    ffmpeg = shutil.which("ffmpeg") or "ffmpeg"
    command = [
        ffmpeg, "-hide_banner", "-ss", str(start_sec), "-t", str(end_sec - start_sec),
        "-i", video_path, "-vn", "-af",
        f"silencedetect=noise={threshold_db:g}dB:d={min_duration_sec:g}",
        "-f", "null", "-",
    ]
    code, stderr = await _run_process(job_id, command, end_sec - start_sec)
    if await _cancelled(job_id):
        return []
    if code:
        raise RuntimeError(f"FFmpeg silence detection failed: {stderr[-1200:]}")
    return parse_silencedetect(stderr, offset_sec=start_sec)


async def create_job(
    project_id: str,
    video_path: str,
    clips: list[ExportClip],
    request: BatchExportRequest,
    src_w: int,
    src_h: int,
    duration_sec: float | None,
    transcript: TranscriptData | None,
    has_audio: bool = True,
) -> ExportJobRead:
    job_id = uuid.uuid4().hex
    job = ExportJobRead(
        id=job_id, project_id=project_id, status="queued", progress_percent=0,
        total_clips=len(clips), created_at=_now(), updated_at=_now(),
    )
    async with _LOCK:
        _JOBS[job_id] = job
        _TASKS[job_id] = asyncio.create_task(
            _run_batch(job_id, video_path, clips, request, src_w, src_h, duration_sec, transcript, has_audio)
        )
    await _publish(job_id)
    return _snapshot(job_id)


async def _resolve_framing_config(project_id: str, config: FramingConfig) -> FramingConfig:
    """Verify and enrich FramingConfig with saved workspace layoutConfig if fields are default."""
    try:
        from app.core.db import AsyncSessionLocal
        from app.workspace.models import WorkspaceConfig
        from sqlalchemy import select

        async with AsyncSessionLocal() as session:
            res = await session.execute(
                select(WorkspaceConfig).where(WorkspaceConfig.project_id == project_id)
            )
            ws = res.scalar_one_or_none()
            if ws and ws.layout_config_json:
                data = json.loads(ws.layout_config_json)
                if isinstance(data, dict) and data:
                    updates = {}
                    l_template = data.get("layoutTemplate") or data.get("layout_template")
                    f_mode = data.get("framingMode") or data.get("framing_mode")
                    a_ratio = data.get("aspectRatio") or data.get("aspect_ratio")
                    s_ratio = data.get("splitRatio") if "splitRatio" in data else data.get("split_ratio")
                    f_box = data.get("facecamBox") or data.get("facecam_box")
                    g_box = data.get("gameplayBox") or data.get("gameplay_box")

                    if config.facecam_box is None and f_box:
                        updates["facecam_box"] = RegionBox.model_validate(f_box) if isinstance(f_box, dict) else f_box
                    if config.gameplay_box is None and g_box:
                        updates["gameplay_box"] = RegionBox.model_validate(g_box) if isinstance(g_box, dict) else g_box

                    if l_template and config.layout_template == "split_vertical" and l_template != "split_vertical":
                        updates["layout_template"] = l_template
                    if f_mode and config.framing_mode == "gaming" and f_mode != "gaming":
                        updates["framing_mode"] = f_mode
                    if a_ratio and config.aspect_ratio == "9:16" and a_ratio != "9:16":
                        updates["aspect_ratio"] = a_ratio
                    if isinstance(s_ratio, (int, float)) and config.split_ratio == 35 and int(s_ratio) != 35:
                        updates["split_ratio"] = int(s_ratio)

                    dynamic_facecam = data.get("dynamicFacecamTracking") if "dynamicFacecamTracking" in data else data.get("dynamic_facecam_tracking")
                    if dynamic_facecam is not None:
                        updates["dynamic_facecam_tracking"] = bool(dynamic_facecam)

                    wm_path = data.get("watermarkPath")
                    if wm_path and not (config.watermark and config.watermark.path):
                        updates["watermark"] = WatermarkConfig(
                            path=wm_path,
                            opacity=float(data.get("watermarkOpacity", 0.8)),
                            scale=float(data.get("watermarkScale", 0.1)),
                            corner=data.get("watermarkCorner", "bottom_right"),
                        )

                    p_fit = data.get("paneFitMode") or data.get("pane_fit_mode")
                    if p_fit and p_fit in ("fill", "fit"):
                        updates["pane_fit_mode"] = p_fit

                    if updates:
                        config = config.model_copy(update=updates)
    except Exception as e:
        logger.warning("Could not check workspace layout_config for project %s: %s", project_id, e)

    print(
        f"[CLIPFORGE FRAMING CONFIG] Project: {project_id} | Template: {config.layout_template} | "
        f"Mode: {config.framing_mode} | Split: {config.split_ratio} | Facecam: {config.facecam_box} | "
        f"Gameplay: {config.gameplay_box}",
        flush=True,
    )
    return config


async def _resolve_caption_config(project_id: str, config: CaptionConfig) -> CaptionConfig:
    """Enrich CaptionConfig with saved workspace captionConfig if present."""
    try:
        from app.core.db import AsyncSessionLocal
        from app.workspace.models import WorkspaceConfig
        from sqlalchemy import select

        async with AsyncSessionLocal() as session:
            res = await session.execute(
                select(WorkspaceConfig).where(WorkspaceConfig.project_id == project_id)
            )
            ws = res.scalar_one_or_none()
            if ws and ws.caption_config_json:
                data = json.loads(ws.caption_config_json)
                if isinstance(data, dict) and data:
                    updates = {}
                    field_map = {
                        "preset": ("preset", str),
                        "fontName": ("font_name", str),
                        "font_name": ("font_name", str),
                        "fontSize": ("font_size", int),
                        "font_size": ("font_size", int),
                        "primaryColor": ("primary_color", str),
                        "primary_color": ("primary_color", str),
                        "highlightColor": ("highlight_color", str),
                        "highlight_color": ("highlight_color", str),
                        "outlineColor": ("outline_color", str),
                        "outline_color": ("outline_color", str),
                        "outlineWidth": ("outline_width", float),
                        "outline_width": ("outline_width", float),
                        "shadowDepth": ("shadow_depth", float),
                        "shadow_depth": ("shadow_depth", float),
                        "shadowBlur": ("shadow_blur", float),
                        "shadow_blur": ("shadow_blur", float),
                        "shadowColor": ("shadow_color", str),
                        "shadow_color": ("shadow_color", str),
                        "marginV": ("margin_v", int),
                        "margin_v": ("margin_v", int),
                        "positionYPercent": ("position_y_percent", float),
                        "position_y_percent": ("position_y_percent", float),
                        "maxWordsPerLine": ("max_words_per_line", int),
                        "max_words_per_line": ("max_words_per_line", int),
                        "allCaps": ("all_caps", bool),
                        "all_caps": ("all_caps", bool),
                        "animation": ("animation", str),
                        "profanityMask": ("profanity_mask", bool),
                        "profanity_mask": ("profanity_mask", bool),
                        "secondaryFont": ("secondary_font", str),
                        "secondary_font": ("secondary_font", str),
                        "fontSwitchMode": ("font_switch_mode", str),
                        "font_switch_mode": ("font_switch_mode", str),
                        "secondaryItalic": ("secondary_italic", bool),
                        "secondary_italic": ("secondary_italic", bool),
                        "glowEnabled": ("glow_enabled", bool),
                        "glow_enabled": ("glow_enabled", bool),
                        "glowColor": ("glow_color", str),
                        "glow_color": ("glow_color", str),
                        "glowIntensity": ("glow_intensity", int),
                        "glow_intensity": ("glow_intensity", int),
                        "animationStyle": ("animation_style", str),
                        "animation_style": ("animation_style", str),
                        "letterSpacing": ("letter_spacing", float),
                        "letter_spacing": ("letter_spacing", float),
                    }
                    for k, (attr, typ) in field_map.items():
                        if k in data and data[k] is not None:
                            try:
                                val = data[k]
                                if typ is bool:
                                    updates[attr] = val if isinstance(val, bool) else str(val).lower() in ("true", "1")
                                else:
                                    updates[attr] = typ(val)
                            except (ValueError, TypeError):
                                pass
                    if updates:
                        config = config.model_copy(update=updates)
    except Exception as e:
        logger.warning("Could not check workspace caption_config for project %s: %s", project_id, e)
    return config


async def _run_batch(
    job_id: str,
    video_path: str,
    clips: list[ExportClip],
    request: BatchExportRequest,
    src_w: int,
    src_h: int,
    duration_sec: float | None,
    transcript: TranscriptData | None,
    has_audio: bool,
) -> None:
    job = _JOBS[job_id]
    output_dir = settings.cache_dir / "projects" / job.project_id / "renders" / "exports" / job_id
    output_dir.mkdir(parents=True, exist_ok=True)
    try:
        job.status = "running"
        await _publish(job_id)

        request.framing_config = await _resolve_framing_config(job.project_id, request.framing_config)
        request.caption_config = await _resolve_caption_config(job.project_id, request.caption_config)

        logger.info(
            "=== EXPORT JOB START === job_id=%s project_id=%s clips=%d\n"
            "  framing_config: %s\n"
            "  caption_config: %s\n"
            "  burn_captions: %s",
            job_id, job.project_id, len(clips),
            request.framing_config.model_dump(),
            request.caption_config.model_dump(),
            request.burn_captions,
        )

        for index, clip in enumerate(clips):
            if await _cancelled(job_id):
                break

            # Multi-segment support: consume clip.segments or fall back to single range
            if clip.segments and len(clip.segments) > 0:
                base_segments = [
                    (max(0.0, s.start_sec), min(s.end_sec, duration_sec) if duration_sec else s.end_sec)
                    for s in clip.segments
                    if s.end_sec > s.start_sec
                ][:8]
            else:
                s_start = max(0.0, clip.start_sec)
                s_end = min(clip.end_sec, duration_sec) if duration_sec else clip.end_sec
                base_segments = [(s_start, s_end)] if s_end > s_start else []

            if not base_segments:
                raise ValueError(f"Clip {clip.title!r} has invalid bounds or segments")

            start = base_segments[0][0]
            end = base_segments[-1][1]
            job.current_clip = clip.title
            await _publish(job_id)

            if request.remove_silence:
                all_kept = []
                for seg_start, seg_end in base_segments:
                    silences = await _silences(
                        job_id, video_path, seg_start, seg_end,
                        request.silence_threshold_db, request.silence_min_duration_sec,
                    )
                    all_kept.extend(calculate_keep_intervals(seg_start, seg_end, silences))
                kept = all_kept[:20] if all_kept else base_segments
            else:
                kept = base_segments

            if await _cancelled(job_id):
                break

            clip_transcript = map_transcript(transcript, kept) if transcript else None
            out_stem = _safe_name(f"{clip.title}_{index + 1}")
            final_path = output_dir / f"{out_stem}.mp4"
            temp_path = output_dir / f"{out_stem}.partial.mp4"

            # 1. Determine base canvas dimensions
            _, out_w, out_h = build_filter_complex(request.framing_config, src_w, src_h)

            # 2. Burn captions into video stream if enabled and transcript exists
            ass_burn_filename = None
            ass_file_path = None
            if request.burn_captions:
                if not clip_transcript:
                    raise RuntimeError("Burn captions requested but no transcript is available for this clip")
                ass_content, _ = generate_ass(clip_transcript, request.caption_config, out_w, out_h)
                ass_file = output_dir / f"{out_stem}_burn.ass"
                ass_file.write_text(ass_content, encoding="utf-8-sig")
                if not ass_file.is_file() or ass_file.stat().st_size == 0:
                    raise RuntimeError(f"Generated ASS subtitle file {ass_file} is empty or missing")
                ass_burn_filename = ass_file.name
                ass_file_path = ass_file

            # 3. Dynamic Facecam / Multi-Person Tracking or Pure-FFmpeg Export
            layout = request.framing_config.layout_template
            mode = request.framing_config.framing_mode
            watermark = request.framing_config.watermark
            encoder_used = ""

            if request.framing_config.dynamic_facecam_tracking and layout != "blurred_fill":
                worker_script = Path(__file__).resolve().parent.parent.parent / "workers" / "reframe_worker.py"
                worker_cmd = [
                    sys.executable,
                    str(worker_script),
                    "--video-path", str(video_path),
                    "--output-path", str(temp_path),
                    "--config-json", request.framing_config.model_dump_json(),
                    "--intervals-json", json.dumps(kept),
                    "--out-w", str(out_w),
                    "--out-h", str(out_h),
                    "--encoder", "h264_nvenc",
                    "--cwd", str(output_dir),
                ]
                if request.normalize_loudness:
                    worker_cmd.append("--normalize")
                if has_audio:
                    worker_cmd.append("--has-audio")
                if ass_burn_filename:
                    worker_cmd.extend(["--ass-path", str(ass_burn_filename)])
                if watermark and watermark.path and Path(watermark.path).is_file():
                    worker_cmd.extend(["--watermark-path", str(watermark.path)])

                cmd_str = " ".join(worker_cmd)
                print(f"\n[CLIPFORGE DYNAMIC REFRAME WORKER COMMAND]\n{cmd_str}\n", flush=True)
                logger.info("Executing Dynamic Reframe Worker for clip %s: %s", clip.title, cmd_str)

                async def report_worker(percent: int) -> None:
                    job.progress_percent = round(100 * (index + percent / 100) / len(clips), 1)
                    await _publish(job_id)

                code, stderr = await _run_worker_process(job_id, worker_cmd, report_worker, cwd=output_dir)
                if await _cancelled(job_id):
                    temp_path.unlink(missing_ok=True)
                    break
                if code == 0 and temp_path.is_file() and temp_path.stat().st_size > 0:
                    encoder_used = "h264_nvenc"
                    temp_path.replace(final_path)
                else:
                    temp_path.unlink(missing_ok=True)
                    err_preview = stderr[-2000:] if stderr else "(no stderr)"
                    print(f"[DYNAMIC REFRAME FATAL ERROR] Worker failed for clip '{clip.title}'. Stderr:\n{err_preview}", flush=True)
                    raise RuntimeError(f"Dynamic reframe worker failed: {err_preview}")
            else:
                facecam_tracks = None
                gameplay_tracks = None
                is_supported_layout = layout in (
                    "split_vertical", "split_inverted", "pip", "side_by_side_blur",
                    "wide_plus_dual", "fullscreen_crop", "punch_in_zoom", "podcast_active_speaker"
                )
                is_two_person = (
                    mode == "podcast"
                    or layout in ("podcast_active_speaker", "side_by_side_blur", "wide_plus_dual")
                )

                framing, out_w, out_h = build_filter_complex(
                    request.framing_config, src_w, src_h,
                    ass_path=ass_burn_filename,
                    facecam_tracks=facecam_tracks,
                    gameplay_tracks=gameplay_tracks,
                    watermark_input_index=len(base_segments),
                )
                progress_duration = sum(right - left for left, right in kept)

                async def report(percent: int) -> None:
                    job.progress_percent = round(100 * (index + percent / 100) / len(clips), 1)
                    await _publish(job_id)

                for encoder in ("h264_nvenc", "libx264"):
                    command = build_export_command(
                        video_path, str(temp_path), framing, out_w, out_h, start, end,
                        encoder, kept, request.normalize_loudness,
                        has_audio=has_audio,
                        watermark_path=watermark.path if watermark else None,
                        segments=base_segments,
                    )

                    # Export Debug Logging on every export
                    first_15_ass = ""
                    if ass_file_path and ass_file_path.is_file():
                        lines = ass_file_path.read_text(encoding="utf-8-sig", errors="replace").splitlines()[:15]
                        first_15_ass = "\n".join(f"    {ln}" for ln in lines)
                    else:
                        first_15_ass = "    (no captions burned)"

                    cmd_str = " ".join(command)
                    print(f"\n[CLIPFORGE EXPORT FFMPEG COMMAND]\n{cmd_str}\n", flush=True)
                    debug_log = (
                        f"\n{'='*75}\n"
                        f"[CLIPFORGE EXPORT DEBUG]\n"
                        f"  Job ID:           {job_id}\n"
                        f"  Clip:             {clip.title} (idx={index + 1}, {start:.2f}s - {end:.2f}s)\n"
                        f"  Layout Template:  {request.framing_config.layout_template}\n"
                        f"  Framing Mode:     {request.framing_config.framing_mode}\n"
                        f"  Aspect Ratio:     {request.framing_config.aspect_ratio}\n"
                        f"  Split Ratio:      {request.framing_config.split_ratio}\n"
                        f"  Facecam Box:      {request.framing_config.facecam_box}\n"
                        f"  Gameplay Box:     {request.framing_config.gameplay_box}\n"
                        f"  Burn Captions:    {request.burn_captions}\n"
                        f"  Caption Preset:   {request.caption_config.preset if request.caption_config else 'none'}\n"
                        f"  ASS File Preview (First 15 lines):\n{first_15_ass}\n"
                        f"  Encoder Attempt:  {encoder}\n"
                        f"  Working Dir (cwd): {output_dir}\n"
                        f"  FFmpeg Command:\n    {cmd_str}\n"
                        f"{'='*75}"
                    )
                    print(debug_log, flush=True)
                    logger.info(debug_log)

                    code, stderr = await _run_process(job_id, command, progress_duration, report, cwd=output_dir)
                    if await _cancelled(job_id):
                        break
                    if code == 0 and temp_path.is_file() and temp_path.stat().st_size > 0:
                        encoder_used = encoder
                        break
                    temp_path.unlink(missing_ok=True)
                    err_preview = stderr[-1500:] if stderr else "(no stderr)"
                    print(f"[FFMPEG WARNING] Encoder {encoder} failed (code {code}):\n{err_preview}", flush=True)
                    logger.warning("FFmpeg encoder %s failed (code %d):\n%s", encoder, code, err_preview)
                    if encoder == "libx264":
                        print(f"[FFMPEG FATAL ERROR] All encoders failed for clip '{clip.title}'. Stderr:\n{stderr[-2000:]}", flush=True)
                        raise RuntimeError(f"FFmpeg export failed with NVENC and libx264: {stderr[-2000:]}")
                if await _cancelled(job_id):
                    temp_path.unlink(missing_ok=True)
                    break
                if not encoder_used:
                    raise RuntimeError("FFmpeg export did not produce an output file")
                temp_path.replace(final_path)

            if ass_file_path and ass_file_path.is_file():
                ass_file_path.unlink(missing_ok=True)

            sidecars = request.sidecars
            if sidecars.srt or sidecars.ass:
                subtitles_dir = output_dir / "subtitles"
                subtitles_dir.mkdir(parents=True, exist_ok=True)
                if clip_transcript and sidecars.srt:
                    srt = _make_srt(clip_transcript)
                    (subtitles_dir / f"{out_stem}.srt").write_text(srt, encoding="utf-8")
                if clip_transcript and sidecars.ass:
                    ass, _ = generate_ass(clip_transcript, request.caption_config, out_w, out_h)
                    (subtitles_dir / f"{out_stem}.ass").write_text(ass, encoding="utf-8-sig")
            metadata = {
                "project_id": job.project_id, "clip_id": clip.clip_id,
                "title": clip.title, "hook_summary": clip.hook_summary,
                "suggested_hashtags": clip.suggested_hashtags,
                "source_start_sec": start, "source_end_sec": end,
                "segments": [{"start_sec": s[0], "end_sec": s[1]} for s in base_segments],
                "duration_sec": sum(right - left for left, right in kept),
                "removed_silence_sec": max(0.0, sum(s[1] - s[0] for s in base_segments) - sum(right - left for left, right in kept)),
                "encoder": encoder_used, "fps_mode": "cfr",
                "loudness_normalized": request.normalize_loudness,
                "sidecar_timeline": "mapped to exported CFR video timeline",
            }
            if sidecars.metadata_json:
                final_path.with_suffix(".json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
            if sidecars.metadata_txt:
                tags = " ".join(clip.suggested_hashtags)
                final_path.with_suffix(".txt").write_text(
                    f"{clip.title}\n\n{clip.hook_summary}\n\n{tags}\n", encoding="utf-8"
                )
            emitted = [str(final_path)]
            if clip_transcript is not None and sidecars.srt and srt_file.is_file():
                emitted.append(str(srt_file))
            if clip_transcript is not None and sidecars.ass and ass_file_out.is_file():
                emitted.append(str(ass_file_out))
            if sidecars.metadata_json:
                emitted.append(str(final_path.with_suffix(".json")))
            if sidecars.metadata_txt:
                emitted.append(str(final_path.with_suffix(".txt")))
            job.output_files.extend(emitted)
            job.completed_clips += 1
            job.progress_percent = round(job.completed_clips * 100 / len(clips), 1)
            await _publish(job_id)

        if await _cancelled(job_id):
            for partial in output_dir.glob("*.partial.mp4"):
                partial.unlink(missing_ok=True)
            job.status = "cancelled"
        else:
            job.status = "completed"
            job.progress_percent = 100
    except Exception as error:
        job.status = "error"
        job.error = str(error)
        logger.error("Export job %s failed: %s", job_id, error, exc_info=True)
        print(f"\n[CLIPFORGE EXPORT FATAL ERROR] Job {job_id}: {error}\n", flush=True)
        for partial in output_dir.glob("*.partial.mp4"):
            partial.unlink(missing_ok=True)
    finally:
        job.current_clip = None
        _CANCEL_REQUESTED.discard(job_id)
        await _publish(job_id)


async def get_jobs(project_id: str) -> list[ExportJobRead]:
    return [_snapshot(job_id) for job_id, job in reversed(list(_JOBS.items())) if job.project_id == project_id]


async def get_job(job_id: str) -> ExportJobRead | None:
    return _snapshot(job_id) if job_id in _JOBS else None


async def cancel_job(job_id: str) -> bool:
    job = _JOBS.get(job_id)
    if not job or job.status in ("completed", "cancelled", "error"):
        return False
    _CANCEL_REQUESTED.add(job_id)
    job.status = "cancelled"
    await _publish(job_id)
    await ProcessManager.cancel_project(job_id)
    task = _TASKS.get(job_id)
    if task and task is not asyncio.current_task():
        await asyncio.gather(task, return_exceptions=True)
    return True


async def shutdown_export_jobs() -> None:
    job_ids = [job_id for job_id, job in _JOBS.items() if job.status in ("queued", "running")]
    for job_id in job_ids:
        await cancel_job(job_id)
    tasks = [_TASKS[job_id] for job_id in job_ids if job_id in _TASKS]
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)


async def render_preview(
    project_id: str,
    video_path: str,
    request: PreviewRequest,
    src_w: int,
    src_h: int,
    duration_sec: float | None,
    transcript: TranscriptData | None = None,
    has_audio: bool = True,
) -> Path:
    start = request.start_sec
    end = min(request.end_sec, start + 5.0, duration_sec) if duration_sec else min(request.end_sec, start + 5.0)
    if end <= start:
        raise ValueError("Preview start must be before the end of the source video")
    preview_id = f"preview_{uuid.uuid4().hex}"
    if request.remove_silence:
        silences = await _silences(
            preview_id, video_path, start, end,
            request.silence_threshold_db, request.silence_min_duration_sec,
        )
        kept = calculate_keep_intervals(start, end, silences)
    else:
        kept = [(start, end)]

    output_dir = settings.cache_dir / "projects" / project_id / "renders" / "previews"
    output_dir.mkdir(parents=True, exist_ok=True)

    request.framing_config = await _resolve_framing_config(project_id, request.framing_config)
    request.caption_config = await _resolve_caption_config(project_id, request.caption_config)

    _, out_w, out_h = build_filter_complex(request.framing_config, src_w, src_h)

    ass_burn_filename = None
    ass_file_path = None
    clip_transcript = map_transcript(transcript, kept) if transcript else None
    if request.burn_captions and clip_transcript and request.caption_config:
        ass_content, _ = generate_ass(clip_transcript, request.caption_config, out_w, out_h)
        ass_file = output_dir / f"{preview_id}_burn.ass"
        ass_file.write_text(ass_content, encoding="utf-8-sig")
        if ass_file.is_file() and ass_file.stat().st_size > 0:
            ass_burn_filename = ass_file.name
            ass_file_path = ass_file

    facecam_tracks = None
    layout = request.framing_config.layout_template
    mode = request.framing_config.framing_mode
    watermark = request.framing_config.watermark
    output = output_dir / f"preview_{uuid.uuid4().hex}.mp4"
    temp = output.with_name(output.stem + ".partial.mp4")

    if request.framing_config.dynamic_facecam_tracking and layout != "blurred_fill":
        worker_script = Path(__file__).resolve().parent.parent.parent / "workers" / "reframe_worker.py"
        worker_cmd = [
            sys.executable,
            str(worker_script),
            "--video-path", str(video_path),
            "--output-path", str(temp),
            "--config-json", request.framing_config.model_dump_json(),
            "--intervals-json", json.dumps(kept),
            "--out-w", str(out_w),
            "--out-h", str(out_h),
            "--encoder", "h264_nvenc",
            "--cwd", str(output_dir),
        ]
        if request.normalize_loudness:
            worker_cmd.append("--normalize")
        if has_audio:
            worker_cmd.append("--has-audio")
        if ass_burn_filename:
            worker_cmd.extend(["--ass-path", str(ass_burn_filename)])
        if watermark and watermark.path and Path(watermark.path).is_file():
            worker_cmd.extend(["--watermark-path", str(watermark.path)])

        cmd_str = " ".join(worker_cmd)
        print(f"\n[CLIPFORGE DYNAMIC REFRAME PREVIEW COMMAND]\n{cmd_str}\n", flush=True)
        logger.info("Executing Dynamic Reframe Worker for preview: %s", cmd_str)

        try:
            code, stderr = await _run_worker_process(preview_id, worker_cmd, cwd=output_dir)
            if code == 0 and temp.is_file() and temp.stat().st_size > 0:
                temp.replace(output)
                return output
            temp.unlink(missing_ok=True)
            err_preview = stderr[-2000:] if stderr else "(no stderr)"
            print(f"[DYNAMIC REFRAME PREVIEW FATAL ERROR] Preview failed:\n{err_preview}", flush=True)
            raise RuntimeError(f"Dynamic reframe preview failed: {err_preview}")
        finally:
            await ProcessManager.cancel_project(preview_id)
            temp.unlink(missing_ok=True)
            if ass_file_path and ass_file_path.is_file():
                ass_file_path.unlink(missing_ok=True)
    else:
        facecam_tracks = None
        gameplay_tracks = None
        framing, out_w, out_h = build_filter_complex(
            request.framing_config, src_w, src_h,
            ass_path=ass_burn_filename,
            facecam_tracks=facecam_tracks,
            gameplay_tracks=gameplay_tracks,
            watermark_input_index=1,
        )
        try:
            error_text = ""
            for encoder in ("h264_nvenc", "libx264"):
                command = build_export_command(
                    video_path, str(temp), framing, out_w, out_h, start, end,
                    encoder, kept, request.normalize_loudness,
                    has_audio=has_audio,
                    watermark_path=watermark.path if watermark else None,
                    segments=[(start, end)],
                )

                first_15_ass = ""
                if ass_file_path and ass_file_path.is_file():
                    lines = ass_file_path.read_text(encoding="utf-8-sig", errors="replace").splitlines()[:15]
                    first_15_ass = "\n".join(f"    {ln}" for ln in lines)
                else:
                    first_15_ass = "    (no captions burned)"

                cmd_str = " ".join(command)
                print(f"\n[CLIPFORGE PREVIEW FFMPEG COMMAND]\n{cmd_str}\n", flush=True)
                debug_log = (
                    f"\n{'='*75}\n"
                    f"[CLIPFORGE PREVIEW DEBUG]\n"
                    f"  Preview ID:       {preview_id}\n"
                    f"  Bounds:           {start:.2f}s - {end:.2f}s\n"
                    f"  Layout Template:  {request.framing_config.layout_template}\n"
                    f"  Framing Mode:     {request.framing_config.framing_mode}\n"
                    f"  Aspect Ratio:     {request.framing_config.aspect_ratio}\n"
                    f"  Split Ratio:      {request.framing_config.split_ratio}\n"
                    f"  Facecam Box:      {request.framing_config.facecam_box}\n"
                    f"  Gameplay Box:     {request.framing_config.gameplay_box}\n"
                    f"  Burn Captions:    {request.burn_captions}\n"
                    f"  Caption Preset:   {request.caption_config.preset if request.caption_config else 'none'}\n"
                    f"  ASS File Preview (First 15 lines):\n{first_15_ass}\n"
                    f"  Working Dir (cwd): {output_dir}\n"
                    f"  FFmpeg Command:\n    {cmd_str}\n"
                    f"{'='*75}"
                )
                print(debug_log, flush=True)
                logger.info(debug_log)

                code, error_text = await _run_process(preview_id, command, sum(b - a for a, b in kept), cwd=output_dir)
                if code == 0 and temp.is_file() and temp.stat().st_size:
                    temp.replace(output)
                    return output
                temp.unlink(missing_ok=True)
                err_preview = error_text[-1500:] if error_text else "(no stderr)"
                print(f"[FFMPEG PREVIEW WARNING] Encoder {encoder} failed (code {code}):\n{err_preview}", flush=True)
                logger.warning("FFmpeg preview encoder %s failed (code %d):\n%s", encoder, code, err_preview)
            print(f"[FFMPEG PREVIEW FATAL ERROR] Preview render failed:\n{error_text[-2000:]}", flush=True)
            raise RuntimeError(f"FFmpeg preview failed with NVENC and libx264: {error_text[-2000:]}")
        finally:
            await ProcessManager.cancel_project(preview_id)
            temp.unlink(missing_ok=True)
            if ass_file_path:
                ass_file_path.unlink(missing_ok=True)


def _timestamp(seconds: float) -> str:
    millis = max(0, round(seconds * 1000))
    hours, millis = divmod(millis, 3_600_000)
    minutes, millis = divmod(millis, 60_000)
    whole_seconds, millis = divmod(millis, 1000)
    return f"{hours:02}:{minutes:02}:{whole_seconds:02},{millis:03}"


def _make_srt(transcript: TranscriptData, words_per_cue: int = 7) -> str:
    cues: list[str] = []
    cue_index = 1
    for segment in transcript.segments:
        words = segment.words
        for offset in range(0, len(words), words_per_cue):
            group = words[offset:offset + words_per_cue]
            if not group:
                continue
            cues.extend([
                str(cue_index),
                f"{_timestamp(group[0].start)} --> {_timestamp(group[-1].end)}",
                " ".join(word.word for word in group), "",
            ])
            cue_index += 1
    return "\n".join(cues)
