"""Unit tests for Dynamic Facecam Tracking in vision_worker and auto_detect."""

import pytest
from workers.vision_worker import filter_deadzone_keyframes


def test_deadzone_filters_single_frame_jitter():
    """A shift > 0.05 that only lasts for 1 sample must be rejected."""
    initial = {"x": 0.1, "y": 0.1}
    # Samples: 0: initial, 1: jitter to (0.5, 0.5), 2: returns to initial
    samples = [
        {"time": 0.0, "x": 0.1, "y": 0.1},
        {"time": 0.5, "x": 0.5, "y": 0.5},
        {"time": 1.0, "x": 0.1, "y": 0.1},
        {"time": 1.5, "x": 0.1, "y": 0.1},
    ]
    keyframes = filter_deadzone_keyframes(samples, initial, deadzone=0.05, min_consecutive=2, max_keyframes=25)
    assert len(keyframes) == 0


def test_deadzone_emits_persistent_shift():
    """A shift > 0.05 persisting for >= 2 samples must emit a keyframe."""
    initial = {"x": 0.1, "y": 0.1}
    samples = [
        {"time": 0.0, "x": 0.1, "y": 0.1},
        {"time": 0.5, "x": 0.6, "y": 0.1},
        {"time": 1.0, "x": 0.61, "y": 0.1},  # 2nd sample at new position
        {"time": 1.5, "x": 0.6, "y": 0.1},
    ]
    keyframes = filter_deadzone_keyframes(samples, initial, deadzone=0.05, min_consecutive=2, max_keyframes=25)
    assert len(keyframes) == 1
    assert keyframes[0]["time"] == 0.5
    assert abs(keyframes[0]["x"] - 0.6) < 0.02


def test_deadzone_ignores_sub_threshold_movement():
    """A shift <= 0.05 must be ignored as camera noise/drift."""
    initial = {"x": 0.1, "y": 0.1}
    samples = [
        {"time": 0.0, "x": 0.1, "y": 0.1},
        {"time": 0.5, "x": 0.13, "y": 0.12},  # shift 0.03
        {"time": 1.0, "x": 0.14, "y": 0.11},  # shift 0.04
        {"time": 1.5, "x": 0.12, "y": 0.12},
    ]
    keyframes = filter_deadzone_keyframes(samples, initial, deadzone=0.05, min_consecutive=2, max_keyframes=25)
    assert len(keyframes) == 0


def test_keyframes_capped_at_max():
    """Max keyframes constraint (25) is strictly respected."""
    initial = {"x": 0.0, "y": 0.0}
    samples = []
    t = 0.0
    for i in range(40):
        # alternate positions every 2 samples
        x_val = 0.5 if (i // 2) % 2 == 1 else 0.0
        samples.append({"time": t, "x": x_val, "y": 0.0})
        t += 0.5

    keyframes = filter_deadzone_keyframes(samples, initial, deadzone=0.05, min_consecutive=2, max_keyframes=25)
    assert len(keyframes) <= 25


def test_track_facecam_missing_video():
    """Missing or invalid video returns empty tracks dictionary without crashing."""
    from workers.vision_worker import track_facecam
    res = track_facecam("non_existent_video.mp4", 0.0, 5.0, {"x": 0.1, "y": 0.1, "w": 0.3, "h": 0.25})
    assert res == {"tracks": []}
