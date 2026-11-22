"""
Isolated Scene Detection Worker using PySceneDetect.
Detects camera transitions and hard cuts to allow snap-to-scene boundaries.
Runs in a separate subprocess that exits cleanly.
"""

import argparse
import json
from pathlib import Path
import sys


def emit_progress(percent: float, message: str = ""):
    payload = {
        "type": "progress",
        "percent": round(percent, 1),
        "stage": "detecting_scenes",
        "message": message,
    }
    print("PROGRESS:" + json.dumps(payload), flush=True)


def main():
    parser = argparse.ArgumentParser(description="PySceneDetect Scene Boundary Worker")
    parser.add_argument("--video-path", type=str, required=True)
    parser.add_argument("--output-json", type=str, required=True)
    parser.add_argument("--threshold", type=float, default=27.0)
    args = parser.parse_args()

    video_path = Path(args.video_path)
    output_path = Path(args.output_json)

    if not video_path.exists():
        print(f"ERROR: Video file not found: {video_path}", file=sys.stderr, flush=True)
        sys.exit(1)

    emit_progress(10.0, "Scanning video for scene cuts...")

    try:
        from scenedetect import open_video, SceneManager, ContentDetector

        video = open_video(str(video_path))
        scene_manager = SceneManager()
        scene_manager.add_detector(ContentDetector(threshold=args.threshold))

        emit_progress(30.0, "Detecting cut transitions...")
        scene_manager.detect_scenes(video)

        scene_list = scene_manager.get_scene_list()
        scenes = []

        for start_time, end_time in scene_list:
            scenes.append({
                "start_sec": round(start_time.get_seconds(), 2),
                "end_sec": round(end_time.get_seconds(), 2),
            })

        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(scenes, f, indent=2)

        emit_progress(100.0, f"Detected {len(scenes)} scene cuts!")
        print("COMPLETE:" + json.dumps({"scene_count": len(scenes)}), flush=True)

    except Exception as e:
        print(f"ERROR: {str(e)}", file=sys.stderr, flush=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
