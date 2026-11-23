import pytest
import json
from app.projects.schemas import CandidateClip, ClipSegment, DiscoverClipsRequest, UpdateClipsRequest
from app.exports.schemas import ExportClip
from app.exports.media import (
    build_export_command,
    build_export_filter_graph,
    map_time_to_output,
    map_transcript,
    calculate_keep_intervals,
)
from app.framing.schemas import FramingConfig, WatermarkConfig
from app.framing.ffmpeg_builder import build_filter_complex
from app.projects.schemas import TranscriptData, TranscriptSegment, WordTimestamp


def test_candidate_clip_backwards_compatible():
    # Clip with no segments (older saved project)
    raw = {
        "id": "clip_1",
        "title": "Solo Clip",
        "hook_summary": "Great hook",
        "start_sec": 10.0,
        "end_sec": 40.0,
        "duration_sec": 30.0,
        "viral_score": 85,
        "reason": "Good punchline",
        "suggested_hashtags": ["#viral"],
        "detected_mood": "funny",
        "snapped_to_scene": False,
    }
    clip = CandidateClip(**raw)
    assert clip.segments == []
    assert clip.duration_sec == 30.0
    assert clip.effective_segments == [(10.0, 40.0)]


def test_candidate_clip_multi_segment():
    segments = [
        {"start_sec": 10.0, "end_sec": 20.0, "label": "Hook"},
        {"start_sec": 40.0, "end_sec": 55.0, "label": "Payoff"},
    ]
    clip = CandidateClip(
        id="clip_multi",
        title="Jump Cut Clip",
        hook_summary="Hook to payoff",
        start_sec=10.0,
        end_sec=55.0,
        duration_sec=0.0,  # Should be computed from segments
        viral_score=90,
        reason="No filler",
        suggested_hashtags=["#shorts"],
        detected_mood="hype",
        snapped_to_scene=False,
        segments=[ClipSegment(**s) for s in segments],
    )
    # Duration must be the sum of all segments (10 + 15 = 25s)
    assert clip.duration_sec == 25.0
    assert len(clip.segments) == 2
    assert clip.effective_segments == [(10.0, 20.0), (40.0, 55.0)]


def test_export_clip_multi_segment():
    export_clip = ExportClip(
        clip_id="exp_1",
        title="Export Jump Cut",
        start_sec=5.0,
        end_sec=50.0,
        segments=[
            ClipSegment(start_sec=5.0, end_sec=15.0),
            ClipSegment(start_sec=35.0, end_sec=50.0),
        ],
    )
    assert len(export_clip.segments) == 2
    assert export_clip.effective_segments == [(5.0, 15.0), (35.0, 50.0)]
    assert export_clip.duration_sec == 25.0


def test_discover_clips_request_toggle():
    req_default = DiscoverClipsRequest()
    assert req_default.allow_multi_segment is False

    req_custom = DiscoverClipsRequest(allow_multi_segment=True)
    assert req_custom.allow_multi_segment is True


def test_fast_seeking_ffmpeg_command():
    segments = [(12.0, 25.0), (45.0, 60.0)]
    framing = "[0:v]null[vout]"
    cmd = build_export_command(
        input_path="video.mp4",
        output_path="out.mp4",
        framing_filter=framing,
        src_w=1920,
        src_h=1080,
        start_sec=12.0,
        end_sec=60.0,
        encoder="libx264",
        kept_intervals=segments,
        normalize=True,
        has_audio=True,
        segments=segments,
    )
    cmd_str = " ".join(cmd)
    # Must use fast seeking -ss <start> -t <duration> -i video.mp4 for each segment
    assert "-ss 12.000000 -t 13.000000 -i video.mp4" in cmd_str
    assert "-ss 45.000000 -t 15.000000 -i video.mp4" in cmd_str
    # Must not use -copyts or slow seeking
    assert "-copyts" not in cmd_str


def test_watermark_dynamic_input_index(tmp_path):
    logo = tmp_path / "logo.png"
    logo.write_bytes(b"dummy")
    config = FramingConfig(
        aspect_ratio="9:16",
        layout_template="blurred_fill",
        framing_mode="gaming",
        watermark=WatermarkConfig(path=str(logo), opacity=0.8, scale=0.1, corner="bottom_right"),
    )
    # When there are 3 segments, watermark input index must be 3
    fc, _, _ = build_filter_complex(config, 1920, 1080, watermark_input_index=3)
    # The watermark stream must reference [3:v]
    assert "[3:v]scale=" in fc
    assert "[1:v]" not in fc

    # When single segment, watermark index is 1
    fc1, _, _ = build_filter_complex(config, 1920, 1080, watermark_input_index=1)
    assert "[1:v]scale=" in fc1


def test_afade_audio_edges_and_concat():
    segments = [(10.0, 20.0), (30.0, 45.0)]
    framing = "[0:v]null[vout]"
    graph = build_export_filter_graph(
        framing_filter=framing,
        start_sec=10.0,
        end_sec=45.0,
        kept_intervals=segments,
        normalize=True,
        has_audio=True,
        segments=segments,
    )
    # Seg 0 dur = 10s -> afade out st = 9.980s
    assert "afade=t=in:st=0:d=0.020,afade=t=out:st=9.980:d=0.020" in graph
    # Seg 1 dur = 15s -> afade out st = 14.980s
    assert "afade=t=in:st=0:d=0.020,afade=t=out:st=14.980:d=0.020" in graph
    # Check concatenation into [srcv] and [srca_raw]
    assert "concat=n=2:v=1:a=0[srcv]" in graph
    assert "concat=n=2:v=0:a=1[srca_raw]" in graph
    assert "loudnorm" in graph


def test_transcript_mapping_multi_segment():
    kept_intervals = [(10.0, 20.0), (50.0, 60.0)]
    # Word in segment 1: 12.0s -> output 2.0s
    assert map_time_to_output(12.0, kept_intervals) == 2.0
    # Word in gap: 30.0s -> None
    assert map_time_to_output(30.0, kept_intervals) is None
    # Word in segment 2: 53.0s -> output 10.0s + 3.0s = 13.0s
    assert map_time_to_output(53.0, kept_intervals) == 13.0

    raw_transcript = TranscriptData(
        language="en",
        duration=100.0,
        segments=[
            TranscriptSegment(
                id=1,
                start=10.5,
                end=15.0,
                text="Part one hook",
                words=[
                    WordTimestamp(word="Part", start=10.5, end=11.0),
                    WordTimestamp(word="one", start=11.2, end=12.0),
                    WordTimestamp(word="hook", start=12.1, end=13.0),
                ],
            ),
            TranscriptSegment(
                id=2,
                start=30.0,
                end=35.0,
                text="Skipped middle filler",
                words=[
                    WordTimestamp(word="Skipped", start=30.0, end=32.0),
                ],
            ),
            TranscriptSegment(
                id=3,
                start=51.0,
                end=55.0,
                text="Part two payoff",
                words=[
                    WordTimestamp(word="Part", start=51.0, end=52.0),
                    WordTimestamp(word="two", start=52.2, end=53.0),
                    WordTimestamp(word="payoff", start=53.5, end=54.5),
                ],
            ),
        ],
    )

    mapped = map_transcript(raw_transcript, kept_intervals)
    assert len(mapped.segments) == 2  # Middle segment skipped
    assert mapped.duration == 20.0
    # First segment words
    assert mapped.segments[0].words[0].start == pytest.approx(0.5, 0.01)
    assert mapped.segments[0].words[0].end == pytest.approx(1.0, 0.01)
    # Second segment words (offset by first segment duration 10.0s)
    assert mapped.segments[1].words[0].start == pytest.approx(11.0, 0.01)
    assert mapped.segments[1].words[0].end == pytest.approx(12.0, 0.01)
