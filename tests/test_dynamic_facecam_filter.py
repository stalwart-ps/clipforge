"""Unit tests for animated dynamic facecam crop in ffmpeg_builder.py."""

import pytest
from app.framing.ffmpeg_builder import build_filter_complex
from app.framing.schemas import FramingConfig, RegionBox


def _base_config(mode: str = "gaming", layout: str = "split_vertical") -> FramingConfig:
    return FramingConfig(
        framing_mode=mode,  # type: ignore
        aspect_ratio="9:16",
        layout_template=layout,  # type: ignore
        facecam_box=RegionBox(x=0.1, y=0.1, w=0.3, h=0.25),
        gameplay_box=RegionBox(x=0.0, y=0.0, w=1.0, h=1.0),
        split_ratio=35,
    )


def test_split_vertical_no_facecam_tracks_uses_static_crop():
    config = _base_config()
    fc, out_w, out_h = build_filter_complex(config, src_w=1920, src_h=1080, facecam_tracks=None)
    # in_a should be static crop
    assert "crop=" in fc
    assert "if(gte" not in fc


def test_split_vertical_with_facecam_tracks_uses_animated_crop():
    config = _base_config()
    tracks = [
        {"time": 2.0, "x": 0.6, "y": 0.1},
        {"time": 5.5, "x": 0.05, "y": 0.2},
    ]
    fc, out_w, out_h = build_filter_complex(config, src_w=1920, src_h=1080, facecam_tracks=tracks)
    # Check animated crop filter
    assert "gte(t\\,2.000)" in fc
    assert "gte(t\\,5.500)" in fc
    # Coordinates must be clamped within bounds
    # Facecam width = 0.3 * 1920 = 576. Max x = 1920 - 576 = 1344.
    # Track x=0.6 -> 0.6 * 1920 = 1152 <= 1344.
    assert "1152" in fc
    assert "[top][bot]vstack" in fc


def test_pip_with_facecam_tracks_uses_animated_crop():
    config = _base_config(layout="pip")
    tracks = [{"time": 1.5, "x": 0.5, "y": 0.0}]
    fc, out_w, out_h = build_filter_complex(config, src_w=1920, src_h=1080, facecam_tracks=tracks)
    assert "[in_b]crop=" in fc
    assert "gte(t\\,1.500)" in fc
    assert "overlay=" in fc


def test_screen_presenter_split_vertical_with_facecam_tracks():
    config = _base_config(mode="screen_presenter", layout="split_vertical")
    tracks = [{"time": 3.0, "x": 0.4, "y": 0.3}]
    fc, out_w, out_h = build_filter_complex(config, src_w=1920, src_h=1080, facecam_tracks=tracks)
    assert "gte(t\\,3.000)" in fc
    assert "[top][bot]vstack" in fc


def test_facecam_crop_coordinates_strictly_clamped_and_even():
    config = _base_config()
    # Out of bounds track coordinates (e.g. x=1.5, y=-0.5)
    tracks = [{"time": 1.0, "x": 1.5, "y": -0.5}]
    fc, out_w, out_h = build_filter_complex(config, src_w=1920, src_h=1080, facecam_tracks=tracks)
    # Width = 576, Height = 270.
    # Max x = 1920 - 576 = 1344, Min y = 0.
    assert "1344" in fc
    assert "*0" in fc
