import pytest
from app.framing.schemas import FramingConfig, RegionBox
from app.framing.ffmpeg_builder import build_filter_complex
from workers.vision_worker import _expand_face_box

ALL_MODE_TEMPLATES = [
    # Podcast
    ("podcast", "split_vertical"),
    ("podcast", "podcast_active_speaker"),
    ("podcast", "side_by_side_blur"),
    ("podcast", "wide_plus_dual"),
    ("podcast", "fullscreen_crop"),
    # Gaming
    ("gaming", "split_vertical"),
    ("gaming", "split_inverted"),
    ("gaming", "pip"),
    ("gaming", "blurred_fill"),
    ("gaming", "fullscreen_crop"),
    # Talking Head
    ("talking_head", "fullscreen_crop"),
    ("talking_head", "punch_in_zoom"),
    ("talking_head", "blurred_fill"),
    # Screen Presenter
    ("screen_presenter", "split_vertical"),
    ("screen_presenter", "split_inverted"),
    ("screen_presenter", "pip"),
    ("screen_presenter", "blurred_fill"),
    # Reaction
    ("reaction", "split_vertical"),
    ("reaction", "split_inverted"),
    ("reaction", "pip"),
    ("reaction", "side_by_side_blur"),
]


@pytest.mark.parametrize("mode,template", ALL_MODE_TEMPLATES)
@pytest.mark.parametrize("pane_fit_mode", ["fill", "fit"])
def test_all_templates_filter_complex(mode: str, template: str, pane_fit_mode: str):
    cfg = FramingConfig(
        framing_mode=mode,
        layout_template=template,
        pane_fit_mode=pane_fit_mode,
        facecam_box=RegionBox(x=0.1, y=0.1, w=0.3, h=0.25),
        gameplay_box=RegionBox(x=0.0, y=0.0, w=1.0, h=1.0),
        split_ratio=50,
    )
    fc, out_w, out_h = build_filter_complex(cfg, src_w=1920, src_h=1080)
    assert "[v_final]" in fc
    assert out_w % 2 == 0
    assert out_h % 2 == 0
    assert "[0:v]" in fc
    # Verify single [0:v] consumption in graph
    assert fc.count("[0:v]") == 1, f"[0:v] consumed multiple times in {mode}/{template}/{pane_fit_mode}: {fc}"


def test_podcast_active_speaker_with_tracks():
    cfg = FramingConfig(
        framing_mode="podcast",
        layout_template="podcast_active_speaker",
        pane_fit_mode="fill",
        facecam_box=RegionBox(x=0.1, y=0.2, w=0.3, h=0.4),
        gameplay_box=RegionBox(x=0.6, y=0.2, w=0.3, h=0.4),
    )
    # Speaker tracks switching to person 2 at t=4.0
    tracks = [
        {"time": 0.0, "active_id": 0, "box": {"x": 0.1, "y": 0.2, "w": 0.3, "h": 0.4}},
        {"time": 4.0, "active_id": 1, "box": {"x": 0.6, "y": 0.2, "w": 0.3, "h": 0.4}},
        {"time": 8.0, "active_id": 0, "box": {"x": 0.1, "y": 0.2, "w": 0.3, "h": 0.4}},
    ]
    fc, _, _ = build_filter_complex(cfg, 1920, 1080, speaker_tracks=tracks)
    assert "between(t" in fc
    assert "overlay=0:0:enable=" in fc
    assert "[p1_full][p2_full]" in fc


def test_punch_in_zoom_constant_branches():
    cfg = FramingConfig(
        framing_mode="talking_head",
        layout_template="punch_in_zoom",
        pane_fit_mode="fill",
        facecam_box=RegionBox(x=0.2, y=0.2, w=0.4, h=0.4),
    )
    fc, _, _ = build_filter_complex(cfg, 1920, 1080)
    assert "[in_norm][in_zoom]" in fc
    assert "[norm][zoomed]overlay=0:0:enable='gte(mod(t\\,6)\\,3)'" in fc


def test_fill_vs_fit_scaling():
    cfg_fill = FramingConfig(
        framing_mode="gaming",
        layout_template="split_vertical",
        pane_fit_mode="fill",
        facecam_box=RegionBox(x=0.1, y=0.1, w=0.3, h=0.25),
        gameplay_box=RegionBox(x=0.0, y=0.0, w=1.0, h=1.0),
    )
    fc_fill, _, _ = build_filter_complex(cfg_fill, 1920, 1080)
    # In fill mode: force_original_aspect_ratio=increase, followed by crop, NO force_divisible_by=2 on scale
    assert "force_original_aspect_ratio=increase,crop=" in fc_fill
    assert "force_original_aspect_ratio=increase:force_divisible_by=2" not in fc_fill

    cfg_fit = FramingConfig(
        framing_mode="gaming",
        layout_template="split_vertical",
        pane_fit_mode="fit",
        facecam_box=RegionBox(x=0.1, y=0.1, w=0.3, h=0.25),
        gameplay_box=RegionBox(x=0.0, y=0.0, w=1.0, h=1.0),
    )
    fc_fit, _, _ = build_filter_complex(cfg_fit, 1920, 1080)
    # In fit mode: force_original_aspect_ratio=decrease:force_divisible_by=2, followed by pad
    assert "force_original_aspect_ratio=decrease:force_divisible_by=2,pad=" in fc_fit


def test_smart_face_expansion():
    # Tight face (MediaPipe ~6% x ~10%)
    face = {"x": 0.47, "y": 0.20, "w": 0.06, "h": 0.10}

    # Podcast medium
    pod_med = _expand_face_box(face, "podcast", "medium")
    assert pod_med["w"] > face["w"] * 2.5
    assert pod_med["h"] > face["h"] * 4.0
    assert pod_med["y"] < face["y"]  # headroom
    assert 0.0 <= pod_med["x"] <= 1.0
    assert 0.0 <= pod_med["y"] <= 1.0
    assert pod_med["x"] + pod_med["w"] <= 1.0
    assert pod_med["y"] + pod_med["h"] <= 1.0

    # Tightness variations
    pod_close = _expand_face_box(face, "podcast", "close")
    pod_wide = _expand_face_box(face, "podcast", "wide")
    assert pod_close["w"] < pod_med["w"] < pod_wide["w"]
    assert pod_close["h"] < pod_med["h"] < pod_wide["h"]

    # Gaming corner expansion
    corner_face = {"x": 0.85, "y": 0.10, "w": 0.08, "h": 0.12}
    game_box = _expand_face_box(corner_face, "gaming", "medium")
    assert game_box["w"] > corner_face["w"] * 2.0
    assert 0.0 <= game_box["x"] <= 1.0
    assert 0.0 <= game_box["y"] <= 1.0
