import argparse
import os
from pathlib import Path
import sys
import threading
import uvicorn

# Ensure backend directory is in sys.path
backend_dir = Path(__file__).resolve().parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))


def parse_args():
    parser = argparse.ArgumentParser(description="ClipForge Local Server & Desktop Launcher")
    parser.add_argument("--host", type=str, default="127.0.0.1", help="Host interface to bind (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8000, help="Port to listen on (default: 8000)")
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload for local backend development")
    parser.add_argument("--desktop", action="store_true", help="Launch native desktop window via pywebview")
    return parser.parse_args()


def main():
    args = parse_args()
    url = f"http://{args.host}:{args.port}"

    if args.desktop:
        from app.desktop.launcher import launch_desktop

        server_config = uvicorn.Config(
            "app.main:app",
            host=args.host,
            port=args.port,
            log_level="info",
        )
        server = uvicorn.Server(server_config)

        # Run Uvicorn in background thread
        server_thread = threading.Thread(target=server.run, daemon=True)
        server_thread.start()

        print(f"[*] Starting ClipForge Desktop Window pointing to {url}...")
        launch_desktop(url=url, title="ClipForge Local")
        server.should_exit = True
    else:
        print(f"[*] Starting ClipForge Local Server at {url}...")
        uvicorn.run(
            "app.main:app",
            host=args.host,
            port=args.port,
            reload=args.reload,
        )


if __name__ == "__main__":
    main()
