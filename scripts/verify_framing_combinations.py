import subprocess
import sys
from pathlib import Path

# Add backend directory to sys.path
backend_dir = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(backend_dir))

from app.framing.ffmpeg_builder import build_filter_complex
from app.framing.schemas import FramingConfig, RegionBox

MODES = ["podcast", "gaming", "talking_head", "screen_presenter", "reaction"]

TEMPLATES_PER_MODE = {
    "podcast": ["split_vertical", "podcast_active_speaker", "side_by_side_blur", "wide_plus_dual", "fullscreen_crop"],
    "gaming": ["split_vertical", "split_inverted", "pip", "blurred_fill", "fullscreen_crop"],
    "talking_head": ["fullscreen_crop", "punch_in_zoom", "blurred_fill"],
    "screen_presenter": ["split_vertical", "split_inverted", "pip", "blurred_fill"],
    "reaction": ["split_vertical", "split_inverted", "pip", "side_by_side_blur"],
}

ALL_TEMPLATES = [
    "split_vertical",
    "split_inverted",
    "pip",
    "blurred_fill",
    "fullscreen_crop",
    "punch_in_zoom",
    "podcast_active_speaker",
    "side_by_side_blur",
    "wide_plus_dual",
]

ASPECTS = ["9:16", "1:1", "16:9"]

def verify_combinations():
    print("=" * 70)
    print("VERIFYING EVERY (framing_mode, layout_template) COMBINATION")
    print("=" * 70)

    total_tested = 0
    failures = []
    generated_fcs = {}

    for mode in MODES:
        templates = TEMPLATES_PER_MODE[mode]
        for tmpl in templates:
            total_tested += 1
            config = FramingConfig(
                framing_mode=mode,
                aspect_ratio="9:16",
                layout_template=tmpl,
                facecam_box=RegionBox(x=0.1, y=0.15, w=0.35, h=0.3),
                gameplay_box=RegionBox(x=0.0, y=0.0, w=1.0, h=1.0),
                split_ratio=50,
            )

            fc, out_w, out_h = build_filter_complex(config, src_w=1920, src_h=1080)

            # 1. Check even dimensions
            if out_w % 2 != 0 or out_h % 2 != 0:
                failures.append(f"({mode}, {tmpl}): Output dimensions ({out_w}x{out_h}) not even")
                continue

            # 2. Check single [0:v] consumption
            v0_count = fc.count("[0:v]")
            if v0_count != 1:
                failures.append(f"({mode}, {tmpl}): [0:v] consumed {v0_count} times instead of 1")
                continue

            # 3. Check distinctness across templates within the mode
            key = (mode, tmpl)
            generated_fcs[key] = fc

            # 4. Dry-run filtergraph in FFmpeg
            clean_fc = fc.split(";[v_framed]")[0] + ";[v_framed]null[v_final]"
            cmd = [
                "ffmpeg",
                "-f", "lavfi",
                "-i", "testsrc=size=1920x1080:rate=1",
                "-filter_complex", clean_fc,
                "-map", "[v_final]",
                "-frames:v", "1",
                "-f", "null",
                "-",
            ]
            res = subprocess.run(cmd, capture_output=True, text=True)
            if res.returncode != 0:
                failures.append(f"({mode}, {tmpl}): FFmpeg failed with code {res.returncode}:\n{res.stderr[-300:]}")
            else:
                print(f"✓ ({mode:16}, {tmpl:22}) -> out: {out_w}x{out_h}, valid FFmpeg filtergraph")

    # Check distinctness: each template in a mode should produce a distinct filtergraph
    for mode in MODES:
        templates = TEMPLATES_PER_MODE[mode]
        fcs = [generated_fcs[(mode, t)] for t in templates]
        if len(set(fcs)) != len(templates):
            failures.append(f"{mode}: Generated identical filtergraphs for different templates!")

    print("\n" + "=" * 70)
    print("TESTING CROSS-COMBINATIONS (ALL 5 MODES x ALL 9 TEMPLATES x 3 RATIOS)")
    print("=" * 70)

    for aspect in ASPECTS:
        for mode in MODES:
            for tmpl in ALL_TEMPLATES:
                total_tested += 1
                config = FramingConfig(
                    framing_mode=mode,
                    aspect_ratio=aspect,
                    layout_template=tmpl,
                    facecam_box=RegionBox(x=0.1, y=0.15, w=0.35, h=0.3),
                    gameplay_box=RegionBox(x=0.0, y=0.0, w=1.0, h=1.0),
                    split_ratio=50,
                )
                fc, out_w, out_h = build_filter_complex(config, src_w=1920, src_h=1080)
                if out_w % 2 != 0 or out_h % 2 != 0:
                    failures.append(f"({aspect}, {mode}, {tmpl}): Output dimensions ({out_w}x{out_h}) not even")
                if fc.count("[0:v]") != 1:
                    failures.append(f"({aspect}, {mode}, {tmpl}): [0:v] consumed {fc.count('[0:v]')} times")

    print(f"Tested {total_tested} total configurations.")
    print("=" * 70)
    print(f"Summary: {total_tested} tested, {len(failures)} failures")
    if failures:
        print("\nFAILURES:")
        for f in failures:
            print("  -", f)
        sys.exit(1)
    else:
        print("ALL COMBINATIONS PASSED PERFECTLY!")
        sys.exit(0)

if __name__ == "__main__":
    verify_combinations()
