"""
Phase 4 Test Render Script — 5-Second Split-Screen Sample Clip

Usage:
    .venv\\Scripts\\python.exe scripts/test_render_phase4.py
    .venv\\Scripts\\python.exe scripts/test_render_phase4.py --video path/to/video.mp4
    .venv\\Scripts\\python.exe scripts/test_render_phase4.py --mode podcast --aspect 1:1

Renders a 5-second split-screen clip using the Gaming framing mode (or any mode you specify),
with the libx264 encoder (guaranteed to work without NVENC), and prints the output file path.
"""

import argparse
import sys
from pathlib import Path

# Add backend to path
backend_dir = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(backend_dir))


def main():
    parser = argparse.ArgumentParser(description="Phase 4 — 5-Second Test Render")
    parser.add_argument("--video", default=None, help="Path to input video (auto-detected from DB if omitted)")
    parser.add_argument(
        "--mode",
        default="gaming",
        choices=["gaming", "podcast", "talking_head", "screen_presenter", "reaction"],
        help="Framing mode (default: gaming)",
    )
    parser.add_argument(
        "--aspect",
        default="9:16",
        choices=["9:16", "1:1", "16:9"],
        help="Output aspect ratio (default: 9:16)",
    )
    parser.add_argument("--start", type=float, default=5.0, help="Start time in seconds (default: 5)")
    parser.add_argument("--layout", default="split_vertical",
                        choices=["split_vertical", "fullscreen_crop", "blurred_fill", "pip"],
                        help="Layout template (default: split_vertical)")
    args = parser.parse_args()

    video_path = args.video

    # Auto-detect first project video from DB if not provided
    if not video_path:
        import asyncio
        import aiosqlite
        from app.core.config import settings

        async def get_first_video():
            db_path = str(settings.root_dir / "clipforge.db")
            async with aiosqlite.connect(db_path) as db:
                async with db.execute(
                    "SELECT video_path, width, height FROM projects WHERE video_path IS NOT NULL LIMIT 1"
                ) as cursor:
                    row = await cursor.fetchone()
                    return row

        row = asyncio.run(get_first_video())
        if row:
            video_path, src_w, src_h = row
            src_w = src_w or 1920
            src_h = src_h or 1080
            print(f"[Auto-detected] Using video: {video_path}")
        else:
            print("No projects found in DB. Run phase 2 ingestion first, or pass --video <path>")
            sys.exit(1)
    else:
        # Probe dimensions
        import shutil, json, subprocess
        ffprobe_bin = shutil.which("ffprobe") or "ffprobe"
        result = subprocess.run(
            [ffprobe_bin, "-v", "quiet", "-print_format", "json", "-show_streams", video_path],
            capture_output=True, text=True,
        )
        src_w, src_h = 1920, 1080
        if result.returncode == 0:
            try:
                data = json.loads(result.stdout)
                for s in data.get("streams", []):
                    if s.get("codec_type") == "video":
                        src_w = s.get("width", 1920)
                        src_h = s.get("height", 1080)
                        break
            except Exception:
                pass
        print(f"[Probed] Source: {src_w}x{src_h}")

    if not Path(video_path).exists():
        print(f"Video file not found: {video_path}")
        sys.exit(1)

    # Build framing config
    from app.framing.schemas import FramingConfig, RegionBox
    from app.framing.ffmpeg_builder import try_render

    # For Gaming split-screen: facecam = top-left 25%, gameplay = full frame
    facecam_box = RegionBox(x=0.0, y=0.0, w=0.3, h=0.25) if args.mode in ("gaming", "reaction") else None
    gameplay_box = RegionBox(x=0.0, y=0.0, w=1.0, h=1.0) if args.mode != "talking_head" else None

    config = FramingConfig(
        framing_mode=args.mode,  # type: ignore
        aspect_ratio=args.aspect,  # type: ignore
        layout_template=args.layout,  # type: ignore
        facecam_box=facecam_box,
        gameplay_box=gameplay_box,
        split_ratio=35,
    )

    start_sec = args.start
    end_sec = start_sec + 5.0  # Always 5 seconds

    output_path = str(Path(video_path).parent / f"test_render_{args.mode}_{args.aspect.replace(':', 'x')}_5s.mp4")

    print(f"\n{'='*60}")
    print(f"Phase 4 Test Render")
    print(f"{'='*60}")
    print(f"Mode        : {args.mode}")
    print(f"Aspect Ratio: {args.aspect}")
    print(f"Layout      : {args.layout}")
    print(f"Time range  : {start_sec:.1f}s — {end_sec:.1f}s (5 seconds)")
    print(f"Source dims : {src_w}x{src_h}")
    print(f"Output      : {output_path}")
    print(f"{'='*60}\n")

    try:
        encoder_used, stderr = try_render(
            input_path=video_path,
            output_path=output_path,
            config=config,
            src_w=int(src_w),
            src_h=int(src_h),
            start_sec=start_sec,
            end_sec=end_sec,
            timeout=120.0,
        )
        file_size = Path(output_path).stat().st_size / (1024 * 1024)
        print(f"[SUCCESS] Rendered with encoder : {encoder_used}")
        print(f"[SUCCESS] Output file size       : {file_size:.2f} MB")
        print(f"[SUCCESS] Output path            : {output_path}")
        print(f"\nOpen the file to visually verify framing and split ratio.")
    except Exception as e:
        print(f"[ERROR] Render failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
