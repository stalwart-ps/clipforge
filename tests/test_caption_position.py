import pytest
from app.captions.ass_generator import generate_ass
from app.captions.schemas import CaptionConfig
from app.projects.schemas import TranscriptData, TranscriptSegment, WordTimestamp
from app.framing.ffmpeg_builder import build_filter_complex
from app.framing.schemas import FramingConfig, RegionBox


def _dummy_transcript() -> TranscriptData:
    return TranscriptData(
        text="Hello world clipforge test",
        language="en",
        segments=[
            TranscriptSegment(
                id=0,
                start=0.0,
                end=2.0,
                text="Hello world clipforge test",
                words=[
                    WordTimestamp(word="Hello", start=0.0, end=0.5, score=0.99),
                    WordTimestamp(word="world", start=0.5, end=1.0, score=0.99),
                    WordTimestamp(word="clipforge", start=1.0, end=1.5, score=0.99),
                    WordTimestamp(word="test", start=1.5, end=2.0, score=0.99),
                ],
            )
        ],
    )


def test_caption_position_top_anchor():
    """Position < 35% should use Alignment 8 (Top-Center) with MarginV from top."""
    cfg = CaptionConfig(preset="hormozi_pop", position_y_percent=12.0)
    ass_text, count = generate_ass(_dummy_transcript(), cfg, width=1080, height=1920)
    assert count > 0
    # In ASS style line: Alignment, MarginL, MarginR, MarginV, Encoding
    # 12% of 1920 is ~230px MarginV with Alignment 8
    assert ",8,40,40,230,1" in ass_text


def test_caption_position_center_split_seam():
    """Position 50% (Split Seam) should use Alignment 2 (Bottom-Center) at 50% height."""
    cfg = CaptionConfig(preset="hormozi_pop", position_y_percent=50.0)
    ass_text, count = generate_ass(_dummy_transcript(), cfg, width=1080, height=1920)
    assert count > 0
    # 50% from top means 50% from bottom (960px MarginV) with Alignment 2
    assert ",2,40,40,960,1" in ass_text


def test_caption_position_lower_third_default():
    """Position 80% (Lower-Third) should use Alignment 2 with 384px MarginV."""
    cfg = CaptionConfig(preset="hormozi_pop", position_y_percent=80.0)
    ass_text, count = generate_ass(_dummy_transcript(), cfg, width=1080, height=1920)
    assert count > 0
    # 20% from bottom of 1920 is 384px MarginV with Alignment 2
    assert ",2,40,40,384,1" in ass_text


def test_caption_position_boxed_pill():
    """Boxed pill preset with top alignment generates matching vector pill coordinates."""
    cfg = CaptionConfig(preset="boxed_pill", position_y_percent=15.0)
    ass_text, count = generate_ass(_dummy_transcript(), cfg, width=1080, height=1920)
    assert count > 0
    assert ",8,40,40,288,1" in ass_text
    # Pill vector should start at top = margin_v (288)
    assert r"\p1}m " in ass_text
    assert " 288 " in ass_text


def test_burn_captions_strictly_honored_in_filter_complex():
    """When ass_path is None, ass= filter is NEVER attached."""
    config = FramingConfig(
        framing_mode="gaming",
        aspect_ratio="9:16",
        layout_template="split_vertical",
        facecam_box=RegionBox(x=0.0, y=0.0, w=0.3, h=0.25),
        gameplay_box=RegionBox(x=0.0, y=0.25, w=1.0, h=0.75),
    )
    fc_no_burn, _, _ = build_filter_complex(config, 1920, 1080, ass_path=None)
    assert "ass=" not in fc_no_burn
    assert "null[v_final]" in fc_no_burn or "null[vout]" in fc_no_burn

    # When ass_path is provided, ass= filter is attached
    fc_burn, _, _ = build_filter_complex(config, 1920, 1080, ass_path="test_captions.ass")
    assert "ass='test_captions.ass'[v_final]" in fc_burn or "ass='test_captions.ass'[vout]" in fc_burn
