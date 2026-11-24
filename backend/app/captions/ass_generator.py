"""ASS subtitle serialization for word-timestamped transcripts."""

from __future__ import annotations

import logging
import re
from typing import Any

from app.captions.schemas import CaptionConfig
from app.projects.schemas import TranscriptData, WordTimestamp

logger = logging.getLogger(__name__)

PRESETS: dict[str, dict[str, Any]] = {
    # Classic & Still presets (100% backwards-compatible)
    "hormozi_pop": {
        "font_name": "Arial Black",
        "font_size": 78,
        "primary_color": "#FFFFFF",
        "highlight_color": "#FFE600",
        "outline_color": "#000000",
        "outline_width": 6.0,
        "shadow_depth": 3.0,
        "shadow_blur": 0.0,
        "shadow_color": "#000000",
        "margin_v": 180,
        "position_y_percent": 80.0,
        "max_words_per_line": 3,
        "all_caps": True,
        "animation": "pop",
        "animation_style": "none",
        "secondary_font": "Georgia",
        "font_switch_mode": "none",
        "secondary_italic": True,
        "glow_enabled": False,
        "glow_color": "#00F5FF",
        "glow_intensity": 12,
        "letter_spacing": 0.0,
        "profanity_mask": False,
    },
    "karaoke_highlight": {
        "font_name": "Arial",
        "font_size": 62,
        "primary_color": "#FFFFFF",
        "highlight_color": "#52F59B",
        "outline_color": "#111111",
        "outline_width": 3.0,
        "shadow_depth": 1.0,
        "shadow_blur": 0.0,
        "shadow_color": "#000000",
        "margin_v": 140,
        "position_y_percent": 80.0,
        "max_words_per_line": 5,
        "all_caps": False,
        "animation": "highlight",
        "animation_style": "none",
        "secondary_font": "Georgia",
        "font_switch_mode": "none",
        "secondary_italic": True,
        "glow_enabled": False,
        "glow_color": "#00F5FF",
        "glow_intensity": 12,
        "letter_spacing": 0.0,
        "profanity_mask": False,
    },
    "minimal_clean": {
        "font_name": "Arial",
        "font_size": 54,
        "primary_color": "#FFFFFF",
        "highlight_color": "#FFFFFF",
        "outline_color": "#111111",
        "outline_width": 1.0,
        "shadow_depth": 2.0,
        "shadow_blur": 0.0,
        "shadow_color": "#000000",
        "margin_v": 110,
        "position_y_percent": 82.0,
        "max_words_per_line": 6,
        "all_caps": False,
        "animation": "none",
        "animation_style": "none",
        "secondary_font": "Georgia",
        "font_switch_mode": "none",
        "secondary_italic": True,
        "glow_enabled": False,
        "glow_color": "#00F5FF",
        "glow_intensity": 12,
        "letter_spacing": 0.0,
        "profanity_mask": False,
    },
    "gaming_neon": {
        "font_name": "Arial Black",
        "font_size": 66,
        "primary_color": "#E7FCFF",
        "highlight_color": "#00F5FF",
        "outline_color": "#E000FF",
        "outline_width": 5.0,
        "shadow_depth": 4.0,
        "shadow_blur": 0.0,
        "shadow_color": "#000000",
        "margin_v": 300,
        "position_y_percent": 75.0,
        "max_words_per_line": 4,
        "all_caps": True,
        "animation": "bounce",
        "animation_style": "none",
        "secondary_font": "Georgia",
        "font_switch_mode": "none",
        "secondary_italic": True,
        "glow_enabled": False,
        "glow_color": "#00F5FF",
        "glow_intensity": 12,
        "letter_spacing": 0.0,
        "profanity_mask": False,
    },
    "boxed_pill": {
        "font_name": "Arial",
        "font_size": 58,
        "primary_color": "#FFFFFF",
        "highlight_color": "#FFE875",
        "outline_color": "#171717",
        "outline_width": 2.0,
        "shadow_depth": 1.0,
        "shadow_blur": 0.0,
        "shadow_color": "#000000",
        "margin_v": 130,
        "position_y_percent": 80.0,
        "max_words_per_line": 4,
        "all_caps": False,
        "animation": "highlight",
        "animation_style": "none",
        "secondary_font": "Georgia",
        "font_switch_mode": "none",
        "secondary_italic": True,
        "glow_enabled": False,
        "glow_color": "#00F5FF",
        "glow_intensity": 12,
        "letter_spacing": 0.0,
        "profanity_mask": False,
    },
    # 7 New Stylized & Animated presets
    "editorial_mix": {
        "font_name": "Bahnschrift",
        "font_size": 68,
        "primary_color": "#FFFFFF",
        "highlight_color": "#FFD700",
        "outline_color": "#111111",
        "outline_width": 3.0,
        "shadow_depth": 2.0,
        "shadow_blur": 2.0,
        "shadow_color": "#000000",
        "margin_v": 180,
        "position_y_percent": 80.0,
        "max_words_per_line": 4,
        "all_caps": False,
        "animation": "pop",
        "animation_style": "pop_bounce",
        "secondary_font": "Georgia",
        "font_switch_mode": "active_word",
        "secondary_italic": True,
        "glow_enabled": False,
        "glow_color": "#FFD700",
        "glow_intensity": 12,
        "letter_spacing": 0.0,
        "profanity_mask": False,
    },
    "cyber_neon_glow": {
        "font_name": "Arial Black",
        "font_size": 68,
        "primary_color": "#FFFFFF",
        "highlight_color": "#00F5FF",
        "outline_color": "#00F5FF",
        "outline_width": 2.5,
        "shadow_depth": 0.0,
        "shadow_blur": 0.0,
        "shadow_color": "#000000",
        "margin_v": 240,
        "position_y_percent": 76.0,
        "max_words_per_line": 4,
        "all_caps": True,
        "animation": "highlight",
        "animation_style": "glow_pulse",
        "secondary_font": "Georgia",
        "font_switch_mode": "none",
        "secondary_italic": False,
        "glow_enabled": True,
        "glow_color": "#00F5FF",
        "glow_intensity": 14,
        "letter_spacing": 1.0,
        "profanity_mask": False,
    },
    "cinematic_blur": {
        "font_name": "Trebuchet MS",
        "font_size": 56,
        "primary_color": "#FFFFFF",
        "highlight_color": "#E2E8F0",
        "outline_color": "#0F172A",
        "outline_width": 1.5,
        "shadow_depth": 3.0,
        "shadow_blur": 4.0,
        "shadow_color": "#000000",
        "margin_v": 160,
        "position_y_percent": 82.0,
        "max_words_per_line": 5,
        "all_caps": False,
        "animation": "none",
        "animation_style": "blur_reveal",
        "secondary_font": "Georgia",
        "font_switch_mode": "none",
        "secondary_italic": False,
        "glow_enabled": False,
        "glow_color": "#00F5FF",
        "glow_intensity": 12,
        "letter_spacing": 2.5,
        "profanity_mask": False,
    },
    "kinetic_impact": {
        "font_name": "Impact",
        "font_size": 76,
        "primary_color": "#FFFFFF",
        "highlight_color": "#FFE600",
        "outline_color": "#000000",
        "outline_width": 5.0,
        "shadow_depth": 4.0,
        "shadow_blur": 0.0,
        "shadow_color": "#000000",
        "margin_v": 200,
        "position_y_percent": 78.0,
        "max_words_per_line": 3,
        "all_caps": True,
        "animation": "bounce",
        "animation_style": "kinetic_tilt",
        "secondary_font": "Georgia",
        "font_switch_mode": "none",
        "secondary_italic": False,
        "glow_enabled": False,
        "glow_color": "#00F5FF",
        "glow_intensity": 12,
        "letter_spacing": 0.5,
        "profanity_mask": False,
    },
    "slide_up_smooth": {
        "font_name": "Segoe UI",
        "font_size": 60,
        "primary_color": "#FFFFFF",
        "highlight_color": "#38BDF8",
        "outline_color": "#0B0F19",
        "outline_width": 2.0,
        "shadow_depth": 2.5,
        "shadow_blur": 2.5,
        "shadow_color": "#000000",
        "margin_v": 160,
        "position_y_percent": 80.0,
        "max_words_per_line": 4,
        "all_caps": False,
        "animation": "highlight",
        "animation_style": "slide_up",
        "secondary_font": "Georgia",
        "font_switch_mode": "none",
        "secondary_italic": False,
        "glow_enabled": False,
        "glow_color": "#38BDF8",
        "glow_intensity": 10,
        "letter_spacing": 0.5,
        "profanity_mask": False,
    },
    "highlighter_pill": {
        "font_name": "Segoe UI",
        "font_size": 58,
        "primary_color": "#FFFFFF",
        "highlight_color": "#FFE875",
        "outline_color": "#171717",
        "outline_width": 2.0,
        "shadow_depth": 1.5,
        "shadow_blur": 1.0,
        "shadow_color": "#000000",
        "margin_v": 140,
        "position_y_percent": 80.0,
        "max_words_per_line": 4,
        "all_caps": False,
        "animation": "highlight",
        "animation_style": "word_highlight",
        "secondary_font": "Georgia",
        "font_switch_mode": "none",
        "secondary_italic": False,
        "glow_enabled": False,
        "glow_color": "#FFE875",
        "glow_intensity": 10,
        "letter_spacing": 0.0,
        "profanity_mask": False,
    },
    "typewriter_tech": {
        "font_name": "Consolas",
        "font_size": 54,
        "primary_color": "#E6FFFA",
        "highlight_color": "#10B981",
        "outline_color": "#042F2E",
        "outline_width": 2.5,
        "shadow_depth": 3.0,
        "shadow_blur": 0.0,
        "shadow_color": "#022C22",
        "margin_v": 150,
        "position_y_percent": 82.0,
        "max_words_per_line": 5,
        "all_caps": False,
        "animation": "highlight",
        "animation_style": "typewriter",
        "secondary_font": "Consolas",
        "font_switch_mode": "none",
        "secondary_italic": False,
        "glow_enabled": False,
        "glow_color": "#10B981",
        "glow_intensity": 12,
        "letter_spacing": 1.2,
        "profanity_mask": False,
    },
}

_PROFANITY = re.compile(
    r"\b(fuck(?:ing|ed|er|s)?|shit(?:ty|s)?|bitch(?:es)?|asshole|damn|bastard)\b",
    re.I,
)


def resolve_config(config: CaptionConfig) -> CaptionConfig:
    """Use preset defaults while preserving every supplied customizer value."""
    preset_key = config.preset if config.preset in PRESETS else "hormozi_pop"
    defaults = PRESETS[preset_key]
    user_values = config.model_dump(exclude={"preset"}, exclude_none=True)
    values = {**defaults, **user_values, "preset": preset_key}
    values["font_name"] = re.sub(r"[,\r\n]", "", str(values.get("font_name") or "Arial")) or "Arial"
    values["secondary_font"] = (
        re.sub(r"[,\r\n]", "", str(values.get("secondary_font") or "Georgia")) or "Georgia"
    )
    return CaptionConfig(**values)


def _ass_bgr(hex_color: str | None) -> str:
    """Convert hex color (#RRGGBB) to .ass BGR format (&HBBGGRR&)."""
    if not hex_color:
        return "&HFFFFFF&"
    hex_color = hex_color.lstrip("#")
    if len(hex_color) == 6:
        r, g, b = hex_color[0:2], hex_color[2:4], hex_color[4:6]
        return f"&H{b}{g}{r}&".upper()
    return "&HFFFFFF&"


def _ass_style_color(hex_color: str | None, alpha_hex: str = "00") -> str:
    """Convert hex color to ASS Style &HAABBGGRR format."""
    if not hex_color:
        return f"&H{alpha_hex}FFFFFF"
    hex_color = hex_color.lstrip("#")
    if len(hex_color) == 6:
        r, g, b = hex_color[0:2], hex_color[2:4], hex_color[4:6]
        return f"&H{alpha_hex}{b}{g}{r}".upper()
    return f"&H{alpha_hex}FFFFFF"


def _ass_time(seconds: float) -> str:
    centiseconds = max(0, round(seconds * 100))
    hours, remainder = divmod(centiseconds, 360000)
    minutes, remainder = divmod(remainder, 6000)
    whole_seconds, centiseconds = divmod(remainder, 100)
    return f"{hours}:{minutes:02d}:{whole_seconds:02d}.{centiseconds:02d}"


def _safe_text(word: str, config: CaptionConfig) -> str:
    value = _PROFANITY.sub(lambda match: match.group(0)[0] + "***", word) if config.profanity_mask else word
    if config.all_caps:
        value = value.upper()
    return value.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}").replace("\n", "\\N")


def _chunks(words: list[WordTimestamp], size: int):
    for offset in range(0, len(words), size):
        yield words[offset : offset + size]


def _calc_pos_y(config: CaptionConfig, height: int) -> float:
    if config.position_y_percent is not None:
        return float(config.position_y_percent)
    if config.margin_v is not None and config.margin_v > 0:
        return max(5.0, min(95.0, round(100.0 * (1.0 - config.margin_v / float(height or 1920)), 1)))
    return 80.0


def _is_emphasis(word: str) -> bool:
    clean = re.sub(r"[^\w]", "", word)
    if not clean:
        return False
    if any(char.isdigit() for char in clean):
        return True
    if len(clean) >= 6:
        return True
    if len(clean) >= 3 and clean.isupper():
        return True
    return False


def _pill_event(
    start: str,
    end: str,
    text: str,
    config: CaptionConfig,
    width: int,
    height: int,
    alignment: int = 2,
    margin_v: int = 180,
) -> str:
    """ASS vector background with rounded corners, sized to the caption line."""
    font_size = config.font_size or 58
    measured = max(font_size, min(width - 80, round(len(text) * font_size * 0.56)))
    box_w = measured + 48
    box_h = round(font_size * 1.55)
    radius = min(22, box_h // 3)
    left = (width - box_w) // 2
    if alignment == 8:
        top = margin_v
    else:
        top = height - margin_v - box_h
    right, bottom = left + box_w, top + box_h
    path = (
        f"m {left + radius} {top} l {right - radius} {top} "
        f"b {right - radius // 2} {top} {right} {top + radius // 2} {right} {top + radius} "
        f"l {right} {bottom - radius} "
        f"b {right} {bottom - radius // 2} {right - radius // 2} {bottom} {right - radius} {bottom} "
        f"l {left + radius} {bottom} "
        f"b {left + radius // 2} {bottom} {left} {bottom - radius // 2} {left} {bottom - radius} "
        f"l {left} {top + radius} "
        f"b {left} {top + radius // 2} {left + radius // 2} {top} {left + radius} {top} z"
    )
    return (
        f"Dialogue: 0,{start},{end},Default,,0,0,0,,"
        f"{{\\an7\\pos(0,0)\\bord0\\shad0\\1c&H000000&\\1a&H66&\\p1}}{path}{{\\p0}}"
    )


def generate_ass(
    transcript: TranscriptData,
    config: CaptionConfig,
    width: int,
    height: int,
    start_sec: float = 0.0,
    end_sec: float | None = None,
) -> tuple[str, int]:
    """Return complete ASS document and emitted dialogue count."""
    config = resolve_config(config)

    pos_y = _calc_pos_y(config, height)
    if pos_y < 35.0:
        alignment = 8  # Top-center alignment
        effective_margin_v = max(10, round((pos_y / 100.0) * height))
    else:
        alignment = 2  # Bottom-center alignment
        effective_margin_v = max(10, round(((100.0 - pos_y) / 100.0) * height))

    # Center coordinates for \\an5 positioning and motion transforms
    cx = width // 2
    raw_cy = round((pos_y / 100.0) * height)
    cy = max(round(height * 0.08), min(round(height * 0.92), raw_cy))

    # Determine whether dynamic positioning / animated mode is active
    is_animated_or_custom = (
        config.animation_style in (
            "pop_bounce",
            "slide_up",
            "blur_reveal",
            "word_highlight",
            "typewriter",
            "kinetic_tilt",
            "glow_pulse",
        )
        or config.font_switch_mode in ("active_word", "emphasis_words", "alternate_lines")
        or bool(config.glow_enabled)
        or (config.letter_spacing is not None and config.letter_spacing > 0)
        or config.preset in (
            "editorial_mix",
            "cyber_neon_glow",
            "cinematic_blur",
            "kinetic_impact",
            "slide_up_smooth",
            "highlighter_pill",
            "typewriter_tech",
        )
    )

    border_style = 1
    bold = -1 if config.preset in ("hormozi_pop", "gaming_neon", "cyber_neon_glow", "kinetic_impact") else 0
    back_color = "&H66000000" if config.preset in ("boxed_pill", "highlighter_pill") else _ass_style_color(config.shadow_color, "00")
    outline_color_ass = _ass_style_color(config.outline_color)
    primary_color_ass = _ass_style_color(config.primary_color)
    highlight_color_ass = _ass_style_color(config.highlight_color)
    spacing_val = config.letter_spacing or 0.0

    style = (
        f"Style: Default,{config.font_name},{config.font_size},{highlight_color_ass},"
        f"{primary_color_ass},{outline_color_ass},{back_color},"
        f"{bold},0,0,0,100,100,{spacing_val:g},0,{border_style},{config.outline_width or 2:g},{config.shadow_depth or 0:g},"
        f"{alignment},40,40,{effective_margin_v},1"
    )

    header = [
        "[Script Info]",
        "ScriptType: v4.00+",
        f"PlayResX: {width}",
        f"PlayResY: {height}",
        "WrapStyle: 2",
        "ScaledBorderAndShadow: yes",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding",
        style,
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]

    events = 0
    pri_bgr = _ass_bgr(config.primary_color)
    hl_bgr = _ass_bgr(config.highlight_color)
    out_bgr = _ass_bgr(config.outline_color)
    glow_bgr = _ass_bgr(config.glow_color)
    shad_bgr = _ass_bgr(config.shadow_color)
    pri_font = config.font_name or "Arial"
    sec_font = config.secondary_font or "Georgia"
    sec_italic = bool(config.secondary_italic)
    glow_radius = max(2, min(50, config.glow_intensity or 12))
    anim_style = config.animation_style or "none"
    switch_mode = config.font_switch_mode or "none"

    chunk_idx = 0
    for segment in transcript.segments:
        words = [w for w in segment.words if w.end > start_sec and (end_sec is None or w.start < end_sec)]
        for group in _chunks(words, config.max_words_per_line or 4):
            if not group:
                continue

            group_rel: list[tuple[WordTimestamp, float, float]] = []
            for word in group:
                w_start = max(0.0, word.start - start_sec)
                w_end = max(w_start + 0.01, word.end - start_sec)
                if end_sec is not None:
                    w_end = min(w_end, end_sec - start_sec)
                group_rel.append((word, w_start, w_end))

            line_start = group_rel[0][1]
            line_end = max(line_start + 0.01, group_rel[-1][2])
            if end_sec is not None:
                line_end = min(line_end, end_sec - start_sec)

            # --- Branch 1: Legacy behavior for untouched classic presets without new overrides ---
            if not is_animated_or_custom:
                tagged_words = []
                for word, w_start, w_end in group_rel:
                    value = _safe_text(word.word, config)
                    if config.animation == "none":
                        tagged_words.append(value)
                    else:
                        duration_cs = max(1, round((w_end - w_start) * 100))
                        offset_cs = max(0, round((w_start - line_start) * 100))
                        tagged_words.append(f"{{\\kt{offset_cs}\\kf{duration_cs}}}{value}")

                anim_tags = ""
                if config.animation == "pop":
                    anim_tags = r"{\t(0,90,\fscx118\fscy118)\t(90,180,\fscx100\fscy100)}"
                elif config.animation == "bounce":
                    anim_tags = r"{\t(0,90,\fscy125)\t(90,210,\fscy100)}"

                text = (
                    anim_tags
                    + (f"{{\\1c{pri_bgr}}}" if config.animation == "none" else "")
                    + " ".join(tagged_words)
                )
                start_str, end_str = _ass_time(line_start), _ass_time(line_end)
                if config.preset == "boxed_pill":
                    plain_text = " ".join(_safe_text(w.word, config) for w in group)
                    header.append(
                        _pill_event(
                            start_str,
                            end_str,
                            plain_text,
                            config,
                            width,
                            height,
                            alignment,
                            effective_margin_v,
                        )
                    )
                events += 1
                header.append(f"Dialogue: 1,{start_str},{end_str},Default,,0,0,0,,{text}")
                chunk_idx += 1
                continue

            # --- Branch 2: Stylized & Animated presets, Font-Switching, Glow, Shadow & Motion ---
            # Determine line-level font for alternate_lines mode
            if switch_mode == "alternate_lines" and (chunk_idx % 2 == 1):
                base_font = sec_font
                base_italic = sec_italic
            else:
                base_font = pri_font
                base_italic = False

            # Determine emphasis words in this line (up to 2)
            emphasis_indices: set[int] = set()
            if switch_mode == "emphasis_words":
                for idx_w, (w_obj, _, _) in enumerate(group_rel):
                    if _is_emphasis(w_obj.word):
                        emphasis_indices.add(idx_w)
                        if len(emphasis_indices) >= 2:
                            break

            # Line-level motion and positioning prefix tags
            # Rule 2: Use \an5 whenever emitting \pos(cx, cy) or \move(...) with clamped cy
            if anim_style == "slide_up":
                motion_tags = f"\\an5\\move({cx},{cy + 26},{cx},{cy},0,150)\\fad(120,60)"
            elif anim_style == "blur_reveal":
                motion_tags = f"\\an5\\pos({cx},{cy})\\blur12\\alpha&HFF&\\t(0,180,0.5,\\blur0\\alpha&H00&)"
            elif anim_style == "kinetic_tilt":
                tilt_angle = -2.5 if (chunk_idx % 2 == 0) else 2.5
                motion_tags = f"\\an5\\pos({cx},{cy})\\frz{tilt_angle:g}"
            else:
                motion_tags = f"\\an5\\pos({cx},{cy})"

            # Letter spacing tag
            if config.letter_spacing and config.letter_spacing > 0:
                motion_tags += f"\\fsp{config.letter_spacing:g}"

            # Shadow override if shadow_blur or shadow_depth or shadow_color specified
            shadow_tags = ""
            if config.shadow_depth is not None and config.shadow_depth > 0:
                shadow_tags += f"\\shad{config.shadow_depth:g}\\4c{shad_bgr}"
            if config.shadow_blur is not None and config.shadow_blur > 0:
                shadow_tags += f"\\blur{config.shadow_blur:g}"

            # Word-by-word timing slices when word-level interaction or animation is active
            needs_word_slices = (
                switch_mode in ("active_word", "emphasis_words")
                or anim_style in ("pop_bounce", "word_highlight", "typewriter", "kinetic_tilt", "glow_pulse")
                or config.animation in ("pop", "highlight", "bounce")
            )

            # Reset strings without {\r}:
            # Rule 1: Reset explicitly only {\fn<primary>\i0\c<primary_bgr>\fscx100\fscy100} on L1,
            # and {\fn<primary>\i0\fscx100\fscy100} on L0.
            reset_l1 = f"{{\\fn{base_font}\\i{1 if base_italic else 0}\\c{pri_bgr}\\fscx100\\fscy100}}"
            reset_l0 = f"{{\\fn{base_font}\\i{1 if base_italic else 0}\\fscx100\\fscy100}}"

            if config.preset == "boxed_pill":
                plain_text = " ".join(_safe_text(w.word, config) for w in group)
                pill_start, pill_end = _ass_time(line_start), _ass_time(line_end)
                header.append(
                    _pill_event(
                        pill_start,
                        pill_end,
                        plain_text,
                        config,
                        width,
                        height,
                        alignment,
                        effective_margin_v,
                    )
                )

            if needs_word_slices:
                for active_i in range(len(group_rel)):
                    active_word_item, act_start, act_end = group_rel[active_i]
                    # Snap end to the start of next word in group to prevent micro-blinks
                    if active_i < len(group_rel) - 1:
                        next_start = group_rel[active_i + 1][1]
                        if next_start > act_start:
                            slice_end = min(line_end, next_start)
                        else:
                            slice_end = act_end
                    else:
                        slice_end = line_end

                    if slice_end <= act_start:
                        slice_end = act_start + 0.08

                    slice_start_str = _ass_time(act_start)
                    slice_end_str = _ass_time(slice_end)

                    # Build word list for Layer 1 (foreground) and Layer 0 (glow)
                    l1_tokens: list[str] = []
                    l0_tokens: list[str] = []

                    for w_idx, (w_item, _, _) in enumerate(group_rel):
                        word_str = _safe_text(w_item.word, config)

                        # Typewriter tech: hide words that haven't appeared yet
                        if anim_style == "typewriter" and w_idx > active_i:
                            l1_tokens.append(f"{{\\alpha&HFF&}}{word_str}{{\\alpha&H00&}}")
                            l0_tokens.append(f"{{\\alpha&HFF&}}{word_str}{{\\alpha&H00&}}")
                            continue

                        is_active = (w_idx == active_i)
                        is_emph = (w_idx in emphasis_indices)

                        # Determine font and italic
                        if is_active and switch_mode == "active_word":
                            cur_font = sec_font
                            cur_italic = sec_italic
                        elif is_emph:
                            cur_font = sec_font
                            cur_italic = sec_italic
                        else:
                            cur_font = base_font
                            cur_italic = base_italic

                        # Determine active animation scale tag
                        scale_tag = ""
                        scale_reset = ""
                        if is_active:
                            if anim_style == "pop_bounce":
                                scale_tag = r"\t(0,85,\fscx116\fscy116)\t(85,170,\fscx100\fscy100)"
                            elif anim_style == "kinetic_tilt":
                                scale_tag = r"\fscx80\fscy80\t(0,85,0.6,\fscx114\fscy114)\t(85,165,\fscx100\fscy100)"
                            elif config.animation == "pop":
                                scale_tag = r"\t(0,90,\fscx118\fscy118)\t(90,180,\fscx100\fscy100)"
                            elif config.animation == "bounce":
                                scale_tag = r"\t(0,90,\fscy125)\t(90,210,\fscy100)"
                        elif is_emph:
                            scale_tag = r"\fscx108\fscy108"
                            scale_reset = r"\fscx100\fscy100"

                        # Layer 1 styling: color + font + scale
                        color_tag = f"\\c{hl_bgr}" if is_active else f"\\c{pri_bgr}"
                        font_tag = f"\\fn{cur_font}\\i{1 if cur_italic else 0}"
                        l1_word = f"{{{color_tag}{font_tag}{scale_tag}}}{word_str}{reset_l1}"
                        l1_tokens.append(l1_word)

                        # Layer 0 styling (glow): mirror fn, i, scale WITHOUT overriding \1a&HFF& or \3c
                        l0_glow_pulse = ""
                        if is_active and anim_style == "glow_pulse":
                            l0_glow_pulse = f"\\t(0,90,\\bord{glow_radius + 4}\\blur{glow_radius + 4})\\t(90,180,\\bord{glow_radius}\\blur{glow_radius})"
                        l0_word = f"{{{font_tag}{scale_tag}{l0_glow_pulse}}}{word_str}{reset_l0}"
                        l0_tokens.append(l0_word)

                    text_l1 = " ".join(l1_tokens)
                    text_l0 = " ".join(l0_tokens)

                    # When glow is enabled: emit Layer 0 first, then Layer 1 with 100% identical timing
                    if config.glow_enabled:
                        l0_prefix = (
                            f"{{{motion_tags}\\1a&HFF&\\3c{glow_bgr}\\bord{glow_radius}\\blur{glow_radius}"
                            f"\\fn{base_font}\\i{1 if base_italic else 0}}}"
                        )
                        events += 1
                        header.append(
                            f"Dialogue: 0,{slice_start_str},{slice_end_str},Default,,0,0,0,,{l0_prefix}{text_l0}"
                        )

                    # Foreground Layer 1
                    l1_prefix = (
                        f"{{{motion_tags}{shadow_tags}\\1a&H00&\\1c{pri_bgr}\\3c{out_bgr}"
                        f"\\bord{config.outline_width or 2:g}\\fn{base_font}\\i{1 if base_italic else 0}}}"
                    )
                    events += 1
                    header.append(
                        f"Dialogue: 1,{slice_start_str},{slice_end_str},Default,,0,0,0,,{l1_prefix}{text_l1}"
                    )

            else:
                # Single chunk event for still or whole-line animations (e.g. cinematic_blur, slide_up without word-switch)
                start_str, end_str = _ass_time(line_start), _ass_time(line_end)
                l1_tokens = []
                l0_tokens = []
                for idx_w, (w_item, _, _) in enumerate(group_rel):
                    word_str = _safe_text(w_item.word, config)
                    is_emph = idx_w in emphasis_indices
                    cur_font = sec_font if is_emph else base_font
                    cur_italic = sec_italic if is_emph else base_italic
                    scale_tag = r"\fscx108\fscy108" if is_emph else ""
                    font_tag = f"\\fn{cur_font}\\i{1 if cur_italic else 0}"

                    l1_tokens.append(f"{{{font_tag}{scale_tag}\\c{pri_bgr}}}{word_str}{reset_l1}")
                    l0_tokens.append(f"{{{font_tag}{scale_tag}}}{word_str}{reset_l0}")

                text_l1 = " ".join(l1_tokens)
                text_l0 = " ".join(l0_tokens)

                if config.glow_enabled:
                    l0_prefix = (
                        f"{{{motion_tags}\\1a&HFF&\\3c{glow_bgr}\\bord{glow_radius}\\blur{glow_radius}"
                        f"\\fn{base_font}\\i{1 if base_italic else 0}}}"
                    )
                    events += 1
                    header.append(
                        f"Dialogue: 0,{start_str},{end_str},Default,,0,0,0,,{l0_prefix}{text_l0}"
                    )

                l1_prefix = (
                    f"{{{motion_tags}{shadow_tags}\\1a&H00&\\1c{pri_bgr}\\3c{out_bgr}"
                    f"\\bord{config.outline_width or 2:g}\\fn{base_font}\\i{1 if base_italic else 0}}}"
                )
                events += 1
                header.append(
                    f"Dialogue: 1,{start_str},{end_str},Default,,0,0,0,,{l1_prefix}{text_l1}"
                )

            chunk_idx += 1

    logger.debug(
        "generate_ass rendered %d events (preset=%s, font=%s, sec_font=%s, glow=%s, anim=%s)",
        events,
        config.preset,
        config.font_name,
        config.secondary_font,
        config.glow_enabled,
        config.animation_style,
    )
    return "\n".join(header) + "\n", events
