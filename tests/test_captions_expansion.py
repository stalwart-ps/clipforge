"""Tests for Phase 5 Caption Engine & Caption Studio Expansion.

Verifies:
- All 12 presets (5 classic + 7 new stylized/animated)
- Dual-layer neon glow (Layer 0 backing + Layer 1 foreground) with identical timings
- Explicit font resets without {\\r}
- Clamped \\an5\\pos and \\move coordinates
- Proper ASS BGR color conversion
- Font-switching modes (active_word, emphasis_words, alternate_lines)
- Backwards compatibility with older saved projects and workspace configs
"""

import pytest
from app.captions.ass_generator import PRESETS, _ass_bgr, _ass_style_color, generate_ass, resolve_config
from app.captions.schemas import CaptionConfig
from app.projects.schemas import TranscriptData, TranscriptSegment, WordTimestamp


def _sample_transcript() -> TranscriptData:
    return TranscriptData(
        text="Welcome to ClipForge Local caption studio engine test",
        language="en",
        segments=[
            TranscriptSegment(
                id=0,
                start=0.0,
                end=3.0,
                text="Welcome to ClipForge Local caption studio engine test",
                words=[
                    WordTimestamp(word="Welcome", start=0.0, end=0.4, score=0.99),
                    WordTimestamp(word="to", start=0.4, end=0.7, score=0.99),
                    WordTimestamp(word="ClipForge", start=0.7, end=1.2, score=0.99),
                    WordTimestamp(word="Local", start=1.2, end=1.6, score=0.99),
                    WordTimestamp(word="caption", start=1.6, end=2.0, score=0.99),
                    WordTimestamp(word="studio", start=2.0, end=2.4, score=0.99),
                    WordTimestamp(word="engine", start=2.4, end=2.7, score=0.99),
                    WordTimestamp(word="test", start=2.7, end=3.0, score=0.99),
                ],
            )
        ],
    )


def test_all_12_presets_exist():
    expected_presets = [
        "hormozi_pop",
        "karaoke_highlight",
        "minimal_clean",
        "gaming_neon",
        "boxed_pill",
        "editorial_mix",
        "cyber_neon_glow",
        "cinematic_blur",
        "kinetic_impact",
        "slide_up_smooth",
        "highlighter_pill",
        "typewriter_tech",
    ]
    for p in expected_presets:
        assert p in PRESETS, f"Preset {p} missing from PRESETS"
        cfg = CaptionConfig(preset=p)
        resolved = resolve_config(cfg)
        assert resolved.font_name is not None
        assert resolved.primary_color is not None


def test_bgr_color_conversion():
    # #00F5FF -> Red 00, Green F5, Blue FF -> &HFFF500&
    assert _ass_bgr("#00F5FF") == "&HFFF500&"
    # #FFE600 -> Red FF, Green E6, Blue 00 -> &H00E6FF&
    assert _ass_bgr("#FFE600") == "&H00E6FF&"
    # Style color format &HAABBGGRR
    assert _ass_style_color("#00F5FF", "00") == "&H00FFF500"


def test_editorial_mix_preset():
    cfg = CaptionConfig(preset="editorial_mix")
    ass_text, count = generate_ass(_sample_transcript(), cfg, width=1080, height=1920)
    assert count > 0
    assert "[Script Info]" in ass_text
    assert "PlayResX: 1080" in ass_text
    assert "PlayResY: 1920" in ass_text
    assert "Georgia" in ass_text
    assert "\\i1" in ass_text
    # Must NOT contain {\r}
    assert r"{\r}" not in ass_text


def test_cyber_neon_glow_layering():
    cfg = CaptionConfig(preset="cyber_neon_glow")
    ass_text, count = generate_ass(_sample_transcript(), cfg, width=1080, height=1920)
    assert count > 0

    lines = ass_text.splitlines()
    dialogue_l0 = [line for line in lines if line.startswith("Dialogue: 0,")]
    dialogue_l1 = [line for line in lines if line.startswith("Dialogue: 1,")]

    # Neon glow must emit Layer 0 backing
    assert len(dialogue_l0) > 0, "cyber_neon_glow must emit Layer 0 glow lines"
    assert len(dialogue_l0) == len(dialogue_l1), "Layer 0 and Layer 1 count must match exactly"

    # Layer 0 must have transparent body \1a&HFF& and glow border \3c & \blur
    first_l0 = dialogue_l0[0]
    assert r"\1a&HFF&" in first_l0
    assert r"\3c&HFFF500&" in first_l0
    assert r"\blur" in first_l0

    # Layer 0 and Layer 1 timing must match identically
    for l0, l1 in zip(dialogue_l0, dialogue_l1):
        parts_l0 = l0.split(",")
        parts_l1 = l1.split(",")
        # Start and End times: indices 1 and 2
        assert parts_l0[1] == parts_l1[1], f"Start time mismatch: {parts_l0[1]} vs {parts_l1[1]}"
        assert parts_l0[2] == parts_l1[2], f"End time mismatch: {parts_l0[2]} vs {parts_l1[2]}"

    # Must NOT contain {\r}
    assert r"{\r}" not in ass_text


def test_cinematic_blur_preset():
    cfg = CaptionConfig(preset="cinematic_blur")
    ass_text, count = generate_ass(_sample_transcript(), cfg, width=1080, height=1920)
    assert count > 0
    assert r"\fsp" in ass_text or "Spacing" in ass_text
    assert r"\blur12" in ass_text
    assert r"\an5" in ass_text
    assert r"{\r}" not in ass_text


def test_kinetic_impact_preset():
    cfg = CaptionConfig(preset="kinetic_impact")
    ass_text, count = generate_ass(_sample_transcript(), cfg, width=1080, height=1920)
    assert count > 0
    assert "Impact" in ass_text
    assert r"\frz" in ass_text
    assert r"\fscx" in ass_text
    assert r"{\r}" not in ass_text


def test_slide_up_smooth_preset():
    cfg = CaptionConfig(preset="slide_up_smooth")
    ass_text, count = generate_ass(_sample_transcript(), cfg, width=1080, height=1920)
    assert count > 0
    assert r"\move(" in ass_text
    assert r"\fad(" in ass_text
    assert r"\an5" in ass_text
    assert r"{\r}" not in ass_text


def test_typewriter_tech_preset():
    cfg = CaptionConfig(preset="typewriter_tech")
    ass_text, count = generate_ass(_sample_transcript(), cfg, width=1080, height=1920)
    assert count > 0
    assert "Consolas" in ass_text
    assert r"\alpha&HFF&" in ass_text
    assert r"{\r}" not in ass_text


def test_highlighter_pill_preset():
    cfg = CaptionConfig(preset="highlighter_pill")
    ass_text, count = generate_ass(_sample_transcript(), cfg, width=1080, height=1920)
    assert count > 0
    assert r"\an5" in ass_text
    assert r"{\r}" not in ass_text


def test_font_switch_modes():
    # 1. active_word mode
    cfg_act = CaptionConfig(
        preset="minimal_clean",
        font_switch_mode="active_word",
        secondary_font="Georgia",
        secondary_italic=True,
    )
    ass_act, _ = generate_ass(_sample_transcript(), cfg_act, 1080, 1920)
    assert "Georgia" in ass_act
    assert r"\i1" in ass_act
    assert r"{\r}" not in ass_act

    # 2. alternate_lines mode
    cfg_alt = CaptionConfig(
        preset="minimal_clean",
        font_switch_mode="alternate_lines",
        secondary_font="Times New Roman",
        secondary_italic=False,
    )
    ass_alt, _ = generate_ass(_sample_transcript(), cfg_alt, 1080, 1920)
    assert "Times New Roman" in ass_alt
    assert r"{\r}" not in ass_alt


def test_clamped_coordinates_at_extremes():
    # Extreme top (0%) should clamp to safe bounds (~8% of 1920 = 154)
    cfg_top = CaptionConfig(preset="editorial_mix", position_y_percent=0.0)
    ass_top, _ = generate_ass(_sample_transcript(), cfg_top, 1080, 1920)
    assert r"\pos(540,154)" in ass_top

    # Extreme bottom (100%) should clamp to safe bounds (~92% of 1920 = 1766)
    cfg_bot = CaptionConfig(preset="editorial_mix", position_y_percent=100.0)
    ass_bot, _ = generate_ass(_sample_transcript(), cfg_bot, 1080, 1920)
    assert r"\pos(540,1766)" in ass_bot


def test_backwards_compatibility_saved_dict():
    # Simulates loading an older saved project JSON that has only older fields
    old_data = {
        "preset": "hormozi_pop",
        "font_name": "Arial Black",
        "font_size": 78,
        "primary_color": "#FFFFFF",
        "highlight_color": "#FFE600",
        "outline_color": "#000000",
        "outline_width": 6.0,
        "shadow_depth": 3.0,
        "margin_v": 180,
    }
    cfg = CaptionConfig.model_validate(old_data)
    assert cfg.preset == "hormozi_pop"
    assert cfg.glow_enabled is None
    resolved = resolve_config(cfg)
    assert resolved.glow_enabled is False
    assert resolved.secondary_font == "Georgia"
    assert resolved.font_switch_mode == "none"
