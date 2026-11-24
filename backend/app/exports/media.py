"""Synchronized FFmpeg graph and subtitle timeline helpers for Phase 6 exports."""

from __future__ import annotations

import re
import shutil
from pathlib import Path


def map_time_to_output(time_sec: float, kept_intervals: list[tuple[float, float]]) -> float | None:
    """Map an original source timestamp into the concatenated output timeline."""
    elapsed = 0.0
    for start, end in kept_intervals:
        if (start - 0.04) <= time_sec <= (end + 0.04):
            clamped = min(max(time_sec, start), end)
            return round(elapsed + (clamped - start), 6)
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
    segments: list[tuple[float, float]] | None = None,
) -> str:
    """
    Build trimming and concatenation filtergraph before applying the framing filter graph.

    For multi-segment clips and single-segment clips, each segment has its own fast-seeked input stream [k:v] / [k:a].
    PTS is normalized, 20ms afade edges prevent audio clicks, and streams concat into [srcv] & [srca_raw].
    """
    multi_segments = [s for s in (segments or []) if s[1] > s[0]][:8]
    effective_segments = multi_segments if multi_segments else ([(start_sec, end_sec)] if end_sec > start_sec else [(0.0, 1.0)])
    all_kept = kept_intervals or effective_segments

    parts: list[str] = []
    video_labels: list[str] = []
    audio_labels: list[str] = []

    for k, (seg_start, seg_end) in enumerate(effective_segments):
        seg_dur = max(0.01, seg_end - seg_start)
        sub_intervals = [
            (max(seg_start, it[0]), min(seg_end, it[1]))
            for it in all_kept
            if it[1] > seg_start and it[0] < seg_end
        ]
        if not sub_intervals:
            sub_intervals = [(seg_start, seg_end)]

        is_full_segment = (
            len(sub_intervals) == 1
            and abs(sub_intervals[0][0] - seg_start) < 0.05
            and abs(sub_intervals[0][1] - seg_end) < 0.05
        )

        if is_full_segment:
            v_lbl = f"vseg{k}"
            parts.append(f"[{k}:v]setpts=PTS-STARTPTS[{v_lbl}]")
            video_labels.append(f"[{v_lbl}]")

            if has_audio:
                a_lbl = f"aseg{k}"
                fade_str = ""
                if seg_dur > 0.15:
                    fade_out_st = round(seg_dur - 0.02, 3)
                    fade_str = f",afade=t=in:st=0:d=0.020,afade=t=out:st={fade_out_st:.3f}:d=0.020"
                parts.append(f"[{k}:a:0]asetpts=PTS-STARTPTS{fade_str}[{a_lbl}]")
                audio_labels.append(f"[{a_lbl}]")
        else:
            for j, (sub_s, sub_e) in enumerate(sub_intervals):
                rel_s = max(0.0, sub_s - seg_start)
                rel_e = min(seg_dur, sub_e - seg_start)
                sub_dur = max(0.001, rel_e - rel_s)

                v_lbl = f"vseg{k}_{j}"
                parts.append(f"[{k}:v]trim=start={rel_s:.6f}:end={rel_e:.6f},setpts=PTS-STARTPTS[{v_lbl}]")
                video_labels.append(f"[{v_lbl}]")

                if has_audio:
                    a_lbl = f"aseg{k}_{j}"
                    fade_str = ""
                    if sub_dur > 0.15:
                        fade_out_st = round(sub_dur - 0.02, 3)
                        fade_str = f",afade=t=in:st=0:d=0.020,afade=t=out:st={fade_out_st:.3f}:d=0.020"
                    parts.append(
                        f"[{k}:a:0]atrim=start={rel_s:.6f}:end={rel_e:.6f},asetpts=PTS-STARTPTS{fade_str}[{a_lbl}]"
                    )
                    audio_labels.append(f"[{a_lbl}]")

    num_pieces = len(video_labels)
    if num_pieces == 1:
        parts.append(f"{video_labels[0]}null[srcv]")
        if has_audio:
            parts.append(f"{audio_labels[0]}anull[srca_raw]")
    else:
        parts.append(f"{''.join(video_labels)}concat=n={num_pieces}:v=1:a=0[srcv]")
        if has_audio:
            parts.append(f"{''.join(audio_labels)}concat=n={num_pieces}:v=0:a=1[srca_raw]")

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
    segments: list[tuple[float, float]] | None = None,
) -> list[str]:
    """Build a CFR export command with fast input seeking per segment and optional watermark stream."""
    multi_segments = [s for s in (segments or []) if s[1] > s[0]][:8]
    effective_segments = multi_segments if multi_segments else ([(start_sec, end_sec)] if end_sec > start_sec else [(0.0, 1.0)])
    all_kept = kept_intervals or effective_segments

    graph = build_export_filter_graph(
        framing_filter=framing_filter,
        start_sec=start_sec,
        end_sec=end_sec,
        kept_intervals=all_kept,
        normalize=normalize,
        has_audio=has_audio,
        segments=effective_segments,
    )
    ffmpeg = shutil.which("ffmpeg") or "ffmpeg"
    command = [ffmpeg, "-hide_banner", "-y"]

    # Fast Seeking: One input per segment with -ss <start> -t <duration> -i <source>
    for seg_start, seg_end in effective_segments:
        seg_dur = max(0.01, seg_end - seg_start)
        command += ["-ss", f"{seg_start:.6f}", "-t", f"{seg_dur:.6f}", "-i", input_path]

    # Watermark input is added AFTER all segment inputs (input index = len(effective_segments))
    if watermark_path and Path(watermark_path).is_file():
        command += ["-i", watermark_path]

    output_duration = sum(max(0.0, end - start) for start, end in all_kept)
    video_map = "[v_final]" if "[v_final]" in graph else "[vout]"
    command += ["-t", f"{output_duration:.6f}", "-filter_complex", graph, "-map", video_map]
    if has_audio:
        audio_map = "[aout]" if "[aout]" in graph else "0:a:0?"
        command += ["-map", audio_map, "-c:a", "aac", "-b:a", "192k", "-ar", "48000"]
    else:
        command += ["-an"]
    command += ["-fps_mode", "cfr", "-sn", "-movflags", "+faststart", "-progress", "pipe:1", "-nostats"]
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
            w_start = None
            w_end = None
            for k_start, k_end in kept_intervals:
                if word.end > k_start and word.start < k_end:
                    clamped_s = max(word.start, k_start)
                    clamped_e = min(word.end, k_end)
                    w_start = map_time_to_output(clamped_s, kept_intervals)
                    w_end = map_time_to_output(clamped_e, kept_intervals)
                    break

            if w_start is None or w_end is None or w_end <= w_start:
                continue
            words.append(WordTimestamp(word=word.word, start=w_start, end=w_end, confidence=word.confidence))

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
