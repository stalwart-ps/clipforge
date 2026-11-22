"""Phase 4 — Render Worker subprocess.

USAGE: Called via subprocess.run from the framing service.
Accepts JSON config on stdin and renders a clip.
Writes progress lines to stdout: PROGRESS:{json}
Writes COMPLETE:{json} on success.
Exits 0 on success, non-zero on failure.
"""

import argparse
import json
import sys
from pathlib import Path

# Heavy imports are inside main() — this module is never imported at startup


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, help="Input video path")
    parser.add_argument("--output", required=True, help="Output .mp4 path")
    parser.add_argument("--config-json", required=True, help="FramingConfig JSON string")
    parser.add_argument("--start-sec", type=float, default=0.0)
    parser.add_argument("--end-sec", type=float, default=60.0)
    parser.add_argument("--src-w", type=int, required=True)
    parser.add_argument("--src-h", type=int, required=True)
    args = parser.parse_args()

    try:
        import sys as _sys
        # Add backend to path so we can import app.framing
        backend_dir = Path(__file__).resolve().parent.parent
        if str(backend_dir) not in _sys.path:
            _sys.path.insert(0, str(backend_dir))

        from app.framing.schemas import FramingConfig
        from app.framing.ffmpeg_builder import try_render

        config = FramingConfig.model_validate_json(args.config_json)

        print(
            f"PROGRESS:{json.dumps({'type': 'progress', 'percent': 10, 'stage': 'rendering', 'message': 'Starting FFmpeg render...'})}",
            flush=True,
        )

        encoder_used, stderr = try_render(
            input_path=args.input,
            output_path=args.output,
            config=config,
            src_w=args.src_w,
            src_h=args.src_h,
            start_sec=args.start_sec,
            end_sec=args.end_sec,
        )

        out_size = Path(args.output).stat().st_size if Path(args.output).exists() else 0
        print(
            f"COMPLETE:{json.dumps({'output_path': args.output, 'encoder_used': encoder_used, 'file_size': out_size})}",
            flush=True,
        )
        sys.exit(0)

    except Exception as e:
        print(f"ERROR:{json.dumps({'error': str(e)})}", flush=True, file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
