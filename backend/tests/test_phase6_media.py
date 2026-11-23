import unittest

from app.exports.media import (
    build_export_filter_graph,
    build_export_command,
    calculate_keep_intervals,
    map_time_to_output,
    parse_silencedetect,
)


class Phase6MediaTests(unittest.TestCase):
    def test_caption_times_follow_kept_video_audio_intervals(self):
        kept = [(10.0, 12.0), (14.0, 16.0)]
        self.assertEqual(map_time_to_output(14.5, kept), 2.5)
        self.assertIsNone(map_time_to_output(13.0, kept))

    def test_silence_graph_trims_audio_and_video_together_and_normalizes(self):
        graph = build_export_filter_graph(
            "[0:v]scale=1080:1920[vout]", 10.0, 16.0,
            [(10.0, 12.0), (14.0, 16.0)], normalize=True,
        )
        self.assertIn("[0:v]trim=start=10.000000:end=12.000000", graph)
        self.assertIn("[0:a]atrim=start=10.000000:end=12.000000", graph)
        self.assertIn("concat=n=2:v=1:a=0[srcv]", graph)
        self.assertIn("concat=n=2:v=0:a=1[srca_raw]", graph)
        self.assertIn("loudnorm=I=-14:TP=-1.5:LRA=11", graph)

    def test_command_enforces_cfr_and_preview_is_five_seconds(self):
        command = build_export_command(
            "input.mp4", "preview.mp4", "[0:v]scale=1080:1920[vout]",
            1920, 1080, 12.0, 17.0, "h264_nvenc", [], normalize=False,
        )
        self.assertIn("-fps_mode", command)
        self.assertEqual(command[command.index("-fps_mode") + 1], "cfr")
        self.assertIn("-t", command)
        self.assertEqual(float(command[command.index("-t") + 1]), 5.0)

    def test_detected_silence_is_offset_and_removed_with_matching_keep_spans(self):
        silences = parse_silencedetect(
            "[silencedetect] silence_start: 1.000\n[silencedetect] silence_end: 2.000",
            offset_sec=10.0,
        )
        self.assertEqual(silences, [(11.0, 12.0)])
        kept = calculate_keep_intervals(10.0, 13.0, silences, padding_sec=0.0)
        self.assertEqual(kept, [(10.0, 11.0), (12.0, 13.0)])


if __name__ == "__main__":
    unittest.main()
