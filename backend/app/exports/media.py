"""Synchronized FFmpeg graph and subtitle timeline helpers for Phase 6 exports."""

from __future__ import annotations

import re
import shutil
from pathlib import Path


def map_time_to_output(time_sec: float, kept_intervals: list[tuple[float, float]]) -> float | None:
    """Map an original source timestamp into the concatenated output timeline."""
    elapsed = 0.0
    for start, end in kept_intervals:
        if start <= time_sec <= end:
            return round(elapsed + min(time_sec - start, end - start), 6)
        elapsed += max(0.0, end - start)
    return None


def calculate_keep_intervals(
    start_sec: float,
    end_sec: float,
    silence_intervals: list[tuple[float, float]],
    padding_sec: float = 0.08,
) -> list[tuple[float, float]]:
    """Remove detected pauses while retaining a small breath around each pause."""
    clipped = sorted(
        (max(start_sec, start - padding_sec), min(end_sec, end + padding_sec))
        for start, end in silence_intervals
        if end > start_sec and start < end_sec
    )
    merged: list[tuple[float, float]] = []
    for start, end in clipped:
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    kept: list[tuple[float, float]] = []
    cursor = start_sec
    for silence_start, silence_end in merged:
        if silence_start - cursor > 0.04:
            kept.append((cursor, silence_start))
        cursor = max(cursor, silence_end)
    if end_sec - cursor > 0.04:
        kept.append((cursor, end_sec))
    return kept or [(start_sec, end_sec)]


def parse_silencedetect(stderr: str, offset_sec: float = 0.0) -> list[tuple[float, float]]:
    """Parse FFmpeg silencedetect stderr into absolute source-time intervals."""
    starts = re.finditer(r"silence_start:\s*(-?\d+(?:\.\d+)?)", stderr)
    ends = list(re.finditer(r"silence_end:\s*(-?\d+(?:\.\d+)?)", stderr))
    intervals: list[tuple[float, float]] = []
    end_index = 0
    for match in starts:
        start = float(match.group(1))
        while end_index < len(ends) and float(ends[end_index].group(1)) < start:
            end_index += 1
        if end_index < len(ends):
            end = float(ends[end_index].group(1))
            end_index += 1
        else:
            duration_match = re.search(r"silence_duration:\s*(\d+(?:\.\d+)?)", stderr[match.end():])
            end = start + float(duration_match.group(1)) if duration_match else start
        if end > start:
            intervals.append((offset_sec + start, offset_sec + end))
    return intervals


def build_export_filter_graph(
    framing_filter: str,
    start_sec: float,
    end_sec: float,
    kept_intervals: list[tuple[float, float]],
    normalize: bool,
    has_audio: bool = True,
) -> str:
    """Trim and concat matching video/audio intervals before the Phase 4 framing graph."""
    intervals = kept_intervals or [(start_sec, end_sec)]
    parts: list[str] = []
    video_labels: list[str] = []
    audio_labels: list[str] = []
    for index, (start, end) in enumerate(intervals):
        video_label = f"vseg{index}"
        parts.append(
            f"[0:v]trim=start={start:.6f}:end={end:.6f},setpts=PTS-STARTPTS[{video_label}]"
        )
        video_labels.append(f"[{video_label}]")
        if has_audio:
            audio_label = f"aseg{index}"
            parts.append(
                f"[0:a]atrim=start={start:.6f}:end={end:.6f},asetpts=PTS-STARTPTS[{audio_label}]"
            )
            audio_labels.append(f"[{audio_label}]")

    if len(intervals) == 1:
        parts.append(f"{video_labels[0]}null[srcv]")
        if has_audio:
            parts.append(f"{audio_labels[0]}anull[srca_raw]")
    else:
        parts.append(f"{''.join(video_labels)}concat=n={len(intervals)}:v=1:a=0[srcv]")
        if has_audio:
            parts.append(f"{''.join(audio_labels)}concat=n={len(intervals)}:v=0:a=1[srca_raw]")

    parts.append(framing_filter.replace("[0:v]", "[srcv]"))
    if has_audio:
        audio_filter = "[srca_raw]loudnorm=I=-14:TP=-1.5:LRA=11[aout]" if normalize else "[srca_raw]anull[aout]"
        parts.append(audio_filter)
    return ";".join(parts)


def build_export_command(
    input_path: str,
    output_path: str,
    framing_filter: str,
    src_w: int,
    src_h: int,
    start_sec: float,
    end_sec: float,
    encoder: str,
    kept_intervals: list[tuple[float, float]],
    normalize: bool,
    has_audio: bool = True,
    watermark_path: str | None = None,
) -> list[str]:
    """Build a CFR export command with optional matching audio and watermark streams."""
    graph = build_export_filter_graph(
        framing_filter, start_sec, end_sec, kept_intervals, normalize, has_audio
    )
    ffmpeg = shutil.which("ffmpeg") or "ffmpeg"
    command = [ffmpeg, "-hide_banner", "-y", "-i", input_path]
    if watermark_path and Path(watermark_path).is_file():
        command += ["-i", watermark_path]
    output_duration = sum(max(0.0, end - start) for start, end in (kept_intervals or [(start_sec, end_sec)]))
    command += ["-t", f"{output_duration:.6f}", "-filter_complex", graph, "-map", "[vout]"]
    if has_audio:
        command += ["-map", "[aout]", "-c:a", "aac", "-b:a", "192k"]
    else:
        command += ["-an"]
    command += ["-fps_mode", "cfr", "-movflags", "+faststart", "-progress", "pipe:1", "-nostats"]
    if encoder == "h264_nvenc":
        command += ["-c:v", "h264_nvenc", "-preset", "p4", "-rc:v", "vbr", "-cq:v", "19", "-b:v", "0", "-pix_fmt", "yuv420p"]
    else:
        command += ["-c:v", "libx264", "-crf", "18", "-preset", "fast", "-pix_fmt", "yuv420p"]
    command.append(output_path)
    return command


def map_transcript(transcript, kept_intervals: list[tuple[float, float]]):
    """Return a transcript with word and segment times translated to export time."""
    from app.projects.schemas import TranscriptData, TranscriptSegment, WordTimestamp

    segments = []
    for segment in transcript.segments:
        words = []
        for word in segment.words:
            start = map_time_to_output(word.start, kept_intervals)
            end = map_time_to_output(word.end, kept_intervals)
            if start is None or end is None or end <= start:
                continue
            words.append(WordTimestamp(word=word.word, start=start, end=end, confidence=word.confidence))
        if words:
            segments.append(TranscriptSegment(
                id=segment.id, start=words[0].start, end=words[-1].end,
                text=" ".join(word.word for word in words), words=words,
            ))
    duration = sum(end - start for start, end in kept_intervals)
    return TranscriptData(
        language=transcript.language,
        language_probability=transcript.language_probability,
        duration=duration,
        segments=segments,
    )
