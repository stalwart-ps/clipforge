"""ASS subtitle serialization for word-timestamped transcripts."""

from __future__ import annotations

import logging
import re

from app.captions.schemas import CaptionConfig
from app.projects.schemas import TranscriptData, WordTimestamp

logger = logging.getLogger(__name__)


PRESETS: dict[str, dict] = {
    "hormozi_pop": {"font_name": "Arial Black", "font_size": 78, "primary_color": "#FFFFFF", "highlight_color": "#FFE600", "outline_color": "#000000", "outline_width": 6, "shadow_depth": 3, "margin_v": 180, "position_y_percent": 80.0, "max_words_per_line": 3, "all_caps": True, "animation": "pop"},
    "karaoke_highlight": {"font_name": "Arial", "font_size": 62, "primary_color": "#FFFFFF", "highlight_color": "#52F59B", "outline_color": "#111111", "outline_width": 3, "shadow_depth": 1, "margin_v": 140, "position_y_percent": 80.0, "max_words_per_line": 5, "all_caps": False, "animation": "highlight"},
    "minimal_clean": {"font_name": "Arial", "font_size": 54, "primary_color": "#FFFFFF", "highlight_color": "#FFFFFF", "outline_color": "#111111", "outline_width": 1, "shadow_depth": 2, "margin_v": 110, "position_y_percent": 82.0, "max_words_per_line": 6, "all_caps": False, "animation": "none"},
    "gaming_neon": {"font_name": "Arial Black", "font_size": 66, "primary_color": "#E7FCFF", "highlight_color": "#00F5FF", "outline_color": "#E000FF", "outline_width": 5, "shadow_depth": 4, "margin_v": 300, "position_y_percent": 75.0, "max_words_per_line": 4, "all_caps": True, "animation": "bounce"},
    "boxed_pill": {"font_name": "Arial", "font_size": 58, "primary_color": "#FFFFFF", "highlight_color": "#FFE875", "outline_color": "#171717", "outline_width": 2, "shadow_depth": 1, "margin_v": 130, "position_y_percent": 80.0, "max_words_per_line": 4, "all_caps": False, "animation": "highlight"},
}

_PROFANITY = re.compile(r"\b(fuck(?:ing|ed|er|s)?|shit(?:ty|s)?|bitch(?:es)?|asshole|damn|bastard)\b", re.I)


def resolve_config(config: CaptionConfig) -> CaptionConfig:
    """Use preset defaults while preserving every supplied customizer value."""
    defaults = PRESETS[config.preset]
    values = {**defaults, **config.model_dump(exclude={"preset"}, exclude_none=True), "preset": config.preset}
    values["font_name"] = re.sub(r"[,\r\n]", "", values["font_name"]) or "Arial"
    return CaptionConfig(**values)


def _ass_color(hex_color: str) -> str:
    red, green, blue = (hex_color[i:i + 2] for i in (1, 3, 5))
    return f"&H00{blue}{green}{red}".upper()


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
        yield words[offset:offset + size]


def _animation_tag(animation: str) -> str:
    if animation == "pop":
        return r"{\t(0,90,\fscx118\fscy118)\t(90,180,\fscx100\fscy100)}"
    if animation == "bounce":
        return r"{\t(0,90,\fscy125)\t(90,210,\fscy100)}"
    return ""


def _pill_event(start: str, end: str, text: str, config: CaptionConfig, width: int, height: int,
                alignment: int = 2, margin_v: int = 180) -> str:
    """ASS vector background with rounded corners, sized to the caption line."""
    measured = max(config.font_size, min(width - 80, round(len(text) * config.font_size * 0.56)))
    box_w = measured + 48
    box_h = round(config.font_size * 1.55)
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
    return f"Dialogue: 0,{start},{end},Default,,0,0,0,,{{\\an7\\pos(0,0)\\bord0\\shad0\\1c&H000000&\\1a&H66&\\p1}}{path}{{\\p0}}"


def generate_ass(transcript: TranscriptData, config: CaptionConfig, width: int, height: int,
                 start_sec: float = 0.0, end_sec: float | None = None) -> tuple[str, int]:
    """Return complete ASS document and emitted dialogue count."""
    config = resolve_config(config)

    # Determine vertical position percent and dynamic Alignment + MarginV
    if config.position_y_percent is not None:
        pos_y = float(config.position_y_percent)
    elif config.margin_v is not None and config.margin_v > 0:
        pos_y = max(5.0, min(95.0, round(100.0 * (1.0 - config.margin_v / float(height or 1920)), 1)))
    else:
        pos_y = 80.0

    if pos_y < 35.0:
        alignment = 8  # Top-center alignment
        effective_margin_v = max(10, round((pos_y / 100.0) * height))
    else:
        alignment = 2  # Bottom-center alignment
        effective_margin_v = max(10, round(((100.0 - pos_y) / 100.0) * height))

    border_style = 1
    bold = -1 if config.preset in ("hormozi_pop", "gaming_neon") else 0
    back_color = "&H66000000" if config.preset == "boxed_pill" else "&H00000000"
    style = (
        # ASS karaoke fills the active syllable with PrimaryColour; upcoming
        # syllables remain SecondaryColour until their timing begins.
        f"Style: Default,{config.font_name},{config.font_size},{_ass_color(config.highlight_color)},"
        f"{_ass_color(config.primary_color)},{_ass_color(config.outline_color)},{back_color},"
        f"{bold},0,0,0,100,100,0,0,{border_style},{config.outline_width:g},{config.shadow_depth:g},"
        f"{alignment},40,40,{effective_margin_v},1"
    )
    header = [
        "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {width}", f"PlayResY: {height}",
        "WrapStyle: 2", "ScaledBorderAndShadow: yes", "", "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding", style, "", "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    events = 0
    for segment in transcript.segments:
        words = [word for word in segment.words if word.end > start_sec and (end_sec is None or word.start < end_sec)]
        for group in _chunks(words, config.max_words_per_line):
            if not group:
                continue

            # Convert every word's timestamps to clip-relative time starting at 0:00:00.00
            group_rel = []
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

            tags = _animation_tag(config.animation)
            tagged_words = []
            for word, w_start, w_end in group_rel:
                value = _safe_text(word.word, config)
                if config.animation == "none":
                    tagged_words.append(value)
                else:
                    duration_cs = max(1, round((w_end - w_start) * 100))
                    offset_cs = max(0, round((w_start - line_start) * 100))
                    tagged_words.append(f"{{\\kt{offset_cs}\\kf{duration_cs}}}{value}")

            text = tags + (f"{{\\1c{_ass_color(config.primary_color)}}}" if config.animation == "none" else "") + " ".join(tagged_words)
            start, end = _ass_time(line_start), _ass_time(line_end)
            if config.preset == "boxed_pill":
                plain_text = " ".join(_safe_text(word.word, config) for word in group)
                header.append(_pill_event(start, end, plain_text, config, width, height, alignment, effective_margin_v))
            events += 1
            header.append(f"Dialogue: 1,{start},{end},Default,,0,0,0,,{text}")
    logger.debug("generate_ass rendered %d events (preset=%s, font=%s, size=%d, align=%d, margin_v=%d)", events, config.preset, config.font_name, config.font_size, alignment, effective_margin_v)
    return "\n".join(header) + "\n", events

