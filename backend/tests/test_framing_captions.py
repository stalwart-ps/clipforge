import unittest
from pathlib import Path

from app.captions.ass_generator import generate_ass
from app.captions.schemas import CaptionConfig
from app.framing.ffmpeg_builder import (
    _frac_to_px,
    _scale_to,
    build_filter_complex,
    build_ffmpeg_cmd,
)
from app.framing.schemas import FramingConfig, RegionBox
from app.projects.schemas import TranscriptData, TranscriptSegment, WordTimestamp


class FramingCaptionsTests(unittest.TestCase):
    def test_ass_generator_clip_relative_timing(self):
        transcript = TranscriptData(
            segments=[
                TranscriptSegment(
                    id=1,
                    start=100.0,
                    end=105.0,
                    text="Hello world clipforge test",
                    words=[
                        WordTimestamp(word="Hello", start=100.0, end=100.5),
                        WordTimestamp(word="world", start=100.6, end=101.2),
                        WordTimestamp(word="clipforge", start=101.3, end=102.0),
                        WordTimestamp(word="test", start=102.1, end=102.8),
                    ],
                )
            ]
        )
        config = CaptionConfig(preset="hormozi_pop", max_words_per_line=2)
        # Calling with start_sec=100.0 (the clip start)
        ass_text, event_count = generate_ass(
            transcript, config, 1080, 1920, start_sec=100.0, end_sec=105.0
        )
        self.assertGreater(event_count, 0)
        # Verify first dialogue starts at 0:00:00.00
        self.assertIn("Dialogue: 1,0:00:00.00,", ass_text)
        # Verify karaoke offset for the first word starts at 0cs (\kt0)
        self.assertIn(r"\kt0\kf50", ass_text)
        # Second word (start=100.6 -> offset 0.6s = 60cs)
        self.assertIn(r"\kt60\kf60", ass_text)

    def test_blurred_fill_foreground_overlay_on_top(self):
        config = FramingConfig(layout_template="blurred_fill", aspect_ratio="9:16")
        fc, w, h = build_filter_complex(config, 1920, 1080)
        self.assertEqual(w, 1080)
        self.assertEqual(h, 1920)
        self.assertIn("gblur=sigma=20", fc)
        self.assertIn("[bg_blur][fg_scaled]overlay=(W-w)/2:(H-h)/2[v_framed]", fc)
        # Ensure no opaque black pad in blurred_fill
        self.assertNotIn("color=black@0", fc)
        # Ensure final label is [v_final]
        self.assertIn("[v_final]", fc)

    def test_split_vertical_sharp_render_with_defaults(self):
        # Even with no boxes explicitly provided, split_vertical must not fall back to blurred_fill
        config = FramingConfig(
            layout_template="split_vertical",
            split_ratio=40,
            facecam_box=None,
            gameplay_box=None,
        )
        fc, w, h = build_filter_complex(config, 1920, 1080)
        self.assertIn("vstack=inputs=2[v_framed]", fc)
        self.assertNotIn("gblur", fc)
        self.assertIn("[v_final]", fc)

    def test_ass_filter_chained_directly_to_v_final(self):
        config = FramingConfig(layout_template="split_vertical")
        fc, w, h = build_filter_complex(config, 1920, 1080, ass_path="test_captions.ass")
        self.assertIn("[v_framed]ass='test_captions.ass'[v_final]", fc)

        cmd = build_ffmpeg_cmd(
            "in.mp4", "out.mp4", config, 1920, 1080, 0.0, 10.0, ass_path="test_captions.ass"
        )
        # Verify -map [v_final] is mapped
        self.assertIn("-map", cmd)
        map_idx = cmd.index("-map")
        self.assertEqual(cmd[map_idx + 1], "[v_final]")

    def test_frac_to_px_returns_even_dimensions(self):
        # Odd width and height from fraction
        box = RegionBox(x=0.0, y=0.0, w=639 / 1920, h=401 / 1080)
        x, y, w, h = _frac_to_px(box, 1920, 1080)
        self.assertEqual(w % 2, 0, f"w={w} should be even")
        self.assertEqual(h % 2, 0, f"h={h} should be even")
        self.assertGreaterEqual(w, 2)
        self.assertGreaterEqual(h, 2)

        # Near-zero dimensions clamp to >= 2 and even
        box_tiny = RegionBox(x=0.0, y=0.0, w=0.00001, h=0.00001)
        x, y, w, h = _frac_to_px(box_tiny, 1920, 1080)
        self.assertEqual(w % 2, 0)
        self.assertEqual(h % 2, 0)
        self.assertGreaterEqual(w, 2)
        self.assertGreaterEqual(h, 2)

        # Boundary box at odd source dimensions
        box_edge = RegionBox(x=0.999, y=0.999, w=0.1, h=0.1)
        x, y, w, h = _frac_to_px(box_edge, 1921, 1081)
        self.assertEqual(w % 2, 0)
        self.assertEqual(h % 2, 0)
        self.assertGreaterEqual(w, 2)
        self.assertGreaterEqual(h, 2)
        self.assertLessEqual(x + w, 1921)
        self.assertLessEqual(y + h, 1081)

    def test_scale_to_enforces_even_setsar_and_divisible_by_2(self):
        # Pass odd out_w and out_h: 1081 and 633
        result = _scale_to("in_lbl", "out_lbl", 1081, 633)
        expected_scale = "scale=1080:632:force_original_aspect_ratio=decrease:force_divisible_by=2"
        expected_pad = "pad=1080:632:(ow-iw)/2:(oh-ih)/2:color=black"
        self.assertTrue(result.startswith("[in_lbl]setsar=1:1,"))
        self.assertIn(expected_scale, result)
        self.assertIn(expected_pad, result)
        self.assertTrue(result.endswith("[out_lbl]"))
        setsar_idx = result.index("setsar=1:1")
        scale_idx = result.index("scale=")
        pad_idx = result.index("pad=")
        self.assertLess(setsar_idx, scale_idx)
        self.assertLess(scale_idx, pad_idx)

    def test_split_vertical_even_dimensions_and_sum(self):
        # 33% of 1920 produces odd height (633) if not rounded to even
        config = FramingConfig(
            layout_template="split_vertical",
            split_ratio=33,
            aspect_ratio="9:16",
            pane_fit_mode="fit",
        )
        fc, out_w, out_h = build_filter_complex(config, 1920, 1080)
        self.assertEqual(out_w % 2, 0)
        self.assertEqual(out_h % 2, 0)
        self.assertGreaterEqual(out_w, 2)
        self.assertGreaterEqual(out_h, 2)

        # top_h: int(1920 * 0.33) & ~1 = 632
        # bot_h: 1920 - 632 = 1288
        self.assertIn("scale=1080:632:force_original_aspect_ratio=decrease:force_divisible_by=2", fc)
        self.assertIn("pad=1080:632:(ow-iw)/2:(oh-ih)/2:color=black", fc)
        self.assertIn("scale=1080:1288:force_original_aspect_ratio=decrease:force_divisible_by=2", fc)
        self.assertIn("pad=1080:1288:(ow-iw)/2:(oh-ih)/2:color=black", fc)
        self.assertIn("setsar=1:1,scale=1080:632", fc)

    def test_split_vertical_all_split_ratios_and_modes(self):
        for mode in ("gaming", "screen_presenter", "reaction"):
            for ratio in (10, 15, 33, 35, 41, 50, 67, 75, 89, 90):
                config = FramingConfig(
                    framing_mode=mode,
                    layout_template="split_vertical",
                    split_ratio=ratio,
                    aspect_ratio="9:16",
                    pane_fit_mode="fit",
                )
                fc, out_w, out_h = build_filter_complex(config, 1920, 1080)
                self.assertEqual(out_w % 2, 0)
                self.assertEqual(out_h % 2, 0)
                self.assertGreaterEqual(out_w, 2)
                self.assertGreaterEqual(out_h, 2)

                # Extract top and bot heights from scale or pad expressions
                import re
                scale_matches = re.findall(rf"scale={out_w}:(\d+):", fc)
                self.assertEqual(len(scale_matches), 2, f"Expected 2 scale matches for mode={mode}, ratio={ratio}")
                top_h, bot_h = int(scale_matches[0]), int(scale_matches[1])
                self.assertEqual(top_h % 2, 0, f"top_h={top_h} must be even for ratio={ratio}")
                self.assertEqual(bot_h % 2, 0, f"bot_h={bot_h} must be even for ratio={ratio}")
                self.assertGreaterEqual(top_h, 2)
                self.assertGreaterEqual(bot_h, 2)
                self.assertEqual(top_h + bot_h, out_h, f"top_h + bot_h must equal out_h for ratio={ratio}")
                self.assertIn(f"setsar=1:1,scale={out_w}:{top_h}:force_original_aspect_ratio=decrease:force_divisible_by=2", fc)
                self.assertIn(f"setsar=1:1,scale={out_w}:{bot_h}:force_original_aspect_ratio=decrease:force_divisible_by=2", fc)


if __name__ == "__main__":
    unittest.main()
