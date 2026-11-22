"""Process-aware sequential batch export queue."""

from __future__ import annotations

import asyncio
import json
import re
import shutil
import uuid
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

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
from app.framing.ffmpeg_builder import build_filter_complex
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
) -> tuple[int, str]:
    """Run one FFmpeg process, drain both pipes, and always wait/reap after termination."""
    process = await asyncio.create_subprocess_exec(
        *command,
        cwd=str(settings.backend_dir),
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
        for index, clip in enumerate(clips):
            if await _cancelled(job_id):
                break
            start = max(0.0, clip.start_sec)
            end = min(clip.end_sec, duration_sec) if duration_sec else clip.end_sec
            if end <= start:
                raise ValueError(f"Clip {clip.title!r} has invalid bounds")
            job.current_clip = clip.title
            await _publish(job_id)

            if request.remove_silence:
                silences = await _silences(
                    job_id, video_path, start, end,
                    request.silence_threshold_db, request.silence_min_duration_sec,
                )
                kept = calculate_keep_intervals(start, end, silences)
            else:
                kept = [(start, end)]
            if await _cancelled(job_id):
                break

            clip_transcript = map_transcript(transcript, kept) if transcript else None
            out_stem = _safe_name(f"{clip.title}_{index + 1}")
            final_path = output_dir / f"{out_stem}.mp4"
            temp_path = output_dir / f"{out_stem}.partial.mp4"
            framing, out_w, out_h = build_filter_complex(
                request.framing_config, src_w, src_h,
            )
            watermark = request.framing_config.watermark
            progress_duration = sum(right - left for left, right in kept)

            async def report(percent: int) -> None:
                job.progress_percent = round(100 * (index + percent / 100) / len(clips), 1)
                await _publish(job_id)

            encoder_used = ""
            for encoder in ("h264_nvenc", "libx264"):
                command = build_export_command(
                    video_path, str(temp_path), framing, out_w, out_h, start, end,
                    encoder, kept, request.normalize_loudness,
                    has_audio=has_audio,
                    watermark_path=watermark.path if watermark else None,
                )
                code, stderr = await _run_process(job_id, command, progress_duration, report)
                if await _cancelled(job_id):
                    break
                if code == 0 and temp_path.is_file() and temp_path.stat().st_size > 0:
                    encoder_used = encoder
                    break
                temp_path.unlink(missing_ok=True)
                if encoder == "libx264":
                    raise RuntimeError(f"FFmpeg export failed with NVENC and libx264: {stderr[-1800:]}")
            if await _cancelled(job_id):
                temp_path.unlink(missing_ok=True)
                break
            if not encoder_used:
                raise RuntimeError("FFmpeg export did not produce an output file")
            temp_path.replace(final_path)

            sidecars = request.sidecars
            if clip_transcript and sidecars.srt:
                srt = _make_srt(clip_transcript)
                final_path.with_suffix(".srt").write_text(srt, encoding="utf-8")
            if clip_transcript and sidecars.ass:
                ass, _ = generate_ass(clip_transcript, request.caption_config, out_w, out_h)
                final_path.with_suffix(".ass").write_text(ass, encoding="utf-8-sig")
            metadata = {
                "project_id": job.project_id, "clip_id": clip.clip_id,
                "title": clip.title, "hook_summary": clip.hook_summary,
                "suggested_hashtags": clip.suggested_hashtags,
                "source_start_sec": start, "source_end_sec": end,
                "duration_sec": sum(right - left for left, right in kept),
                "removed_silence_sec": max(0.0, end - start - sum(right - left for left, right in kept)),
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
            emitted = [str(final_path)] + [
                str(final_path.with_suffix(ext)) for enabled, ext in (
                    (clip_transcript is not None and sidecars.srt, ".srt"),
                    (clip_transcript is not None and sidecars.ass, ".ass"),
                    (sidecars.metadata_json, ".json"),
                    (sidecars.metadata_txt, ".txt"),
                ) if enabled
            ]
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
    framing, out_w, out_h = build_filter_complex(request.framing_config, src_w, src_h)
    watermark = request.framing_config.watermark
    output_dir = settings.cache_dir / "projects" / project_id / "renders" / "previews"
    output_dir.mkdir(parents=True, exist_ok=True)
    output = output_dir / f"preview_{uuid.uuid4().hex}.mp4"
    temp = output.with_name(output.stem + ".partial.mp4")
    try:
        error_text = ""
        for encoder in ("h264_nvenc", "libx264"):
            command = build_export_command(
                video_path, str(temp), framing, out_w, out_h, start, end,
                encoder, kept, request.normalize_loudness,
                has_audio=has_audio,
                watermark_path=watermark.path if watermark else None,
            )
            code, error_text = await _run_process(preview_id, command, sum(b - a for a, b in kept))
            if code == 0 and temp.is_file() and temp.stat().st_size:
                temp.replace(output)
                return output
            temp.unlink(missing_ok=True)
        raise RuntimeError(f"FFmpeg preview failed with NVENC and libx264: {error_text[-1400:]}")
    finally:
        await ProcessManager.cancel_project(preview_id)
        temp.unlink(missing_ok=True)


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
