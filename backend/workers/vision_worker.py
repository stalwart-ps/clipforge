"""Phase 4 — Vision Worker subprocess for Auto-Detect Regions.

USAGE (called by auto_detect.py as an isolated subprocess):
  python vision_worker.py --video-path <path> --time-sec <float> --output-json <path>

Imports mediapipe and cv2 ONLY inside this module.
Never imported at FastAPI startup.

Outputs single line:  RESULT:{json}
"""

import argparse
import json
import sys
from pathlib import Path


def detect_regions(video_path: str, time_sec: float = 1.0) -> dict:
    """
    Open a single frame at time_sec and detect faces using MediaPipe Face Detection.

    Returns:
        {
            "face_count": int,
            "face_confidence": float,
            "faces": [{"x": f, "y": f, "w": f, "h": f, "confidence": f}],
            "facecam_box": {"x": f, "y": f, "w": f, "h": f} | None,
            "gameplay_box": {"x": f, "y": f, "w": f, "h": f} | None,
            "mode_suggestion": str,
        }
    """
    import cv2  # noqa: F401
    import mediapipe as mp  # noqa: F401

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return {
            "face_count": 0,
            "face_confidence": 0.0,
            "faces": [],
            "facecam_box": None,
            "gameplay_box": None,
            "mode_suggestion": "gaming",
            "message": "Could not open video file",
        }

    # Seek to the requested time
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total_frames = cap.get(cv2.CAP_PROP_FRAME_COUNT)
    frame_idx = min(int(time_sec * fps), max(0, int(total_frames) - 1))
    cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)

    ret, frame = cap.read()
    cap.release()

    if not ret or frame is None:
        return {
            "face_count": 0,
            "face_confidence": 0.0,
            "faces": [],
            "facecam_box": None,
            "gameplay_box": None,
            "mode_suggestion": "gaming",
            "message": "Failed to read frame",
        }

    h_px, w_px = frame.shape[:2]
    rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

    # MediaPipe Face Detection
    mp_face = mp.solutions.face_detection
    faces_data = []

    with mp_face.FaceDetection(
        model_selection=1,  # 1 = full range model (better for far faces)
        min_detection_confidence=0.4,
    ) as detector:
        results = detector.process(rgb_frame)
        if results.detections:
            for det in results.detections:
                bbox = det.location_data.relative_bounding_box
                faces_data.append(
                    {
                        "x": max(0.0, float(bbox.xmin)),
                        "y": max(0.0, float(bbox.ymin)),
                        "w": min(1.0, float(bbox.width)),
                        "h": min(1.0, float(bbox.height)),
                        "confidence": float(det.score[0]) if det.score else 0.0,
                    }
                )

    face_count = len(faces_data)
    avg_confidence = sum(f["confidence"] for f in faces_data) / face_count if face_count else 0.0

    # -------------------------------------------------------------------------
    # Heuristic: Identify the "facecam" box (small face, usually in a corner)
    # vs a "presenter" face that fills much of the frame.
    # In gaming streams the facecam overlay typically occupies <25% of frame area.
    # -------------------------------------------------------------------------
    facecam_box = None
    gameplay_box = None
    mode_suggestion = "gaming"

    if face_count == 0:
        # No face → fullscreen gameplay / no-face fallback
        gameplay_box = {"x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0}
        mode_suggestion = "gaming"
    elif face_count == 1:
        f = faces_data[0]
        face_area = f["w"] * f["h"]
        if face_area < 0.20:
            # Small corner overlay → gaming mode: facecam + rest is gameplay
            facecam_box = {"x": f["x"], "y": f["y"], "w": f["w"], "h": f["h"]}
            # Gameplay = whole frame; user can manually crop
            gameplay_box = {"x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0}
            mode_suggestion = "gaming"
        elif face_area < 0.60:
            # Medium-sized face → talking head mode
            # Pad the box by 20% to include shoulders
            pad_x = min(0.1, f["x"])
            pad_y = min(0.05, f["y"])
            facecam_box = {
                "x": max(0.0, f["x"] - pad_x),
                "y": max(0.0, f["y"] - pad_y),
                "w": min(1.0 - f["x"] + pad_x, f["w"] + 2 * pad_x),
                "h": min(1.0 - f["y"] + pad_y, f["h"] * 1.5),
            }
            mode_suggestion = "talking_head"
        else:
            # Large face filling most of frame → podcast mode
            facecam_box = {"x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0}
            mode_suggestion = "podcast"
    elif face_count == 2:
        # Two faces → podcast mode (sorted left-to-right)
        faces_sorted = sorted(faces_data, key=lambda f: f["x"])
        # facecam = left face
        facecam_box = {k: faces_sorted[0][k] for k in ("x", "y", "w", "h")}
        gameplay_box = {k: faces_sorted[1][k] for k in ("x", "y", "w", "h")}
        mode_suggestion = "podcast"
    else:
        # 3+ faces (panel / group) → podcast with largest face as facecam
        biggest = max(faces_data, key=lambda f: f["w"] * f["h"])
        facecam_box = {k: biggest[k] for k in ("x", "y", "w", "h")}
        mode_suggestion = "podcast"

    return {
        "face_count": face_count,
        "face_confidence": round(avg_confidence, 3),
        "faces": faces_data,
        "facecam_box": facecam_box,
        "gameplay_box": gameplay_box,
        "mode_suggestion": mode_suggestion,
        "message": f"Detected {face_count} face(s) with avg confidence {avg_confidence:.2f}",
    }


def main():
    parser = argparse.ArgumentParser(description="Phase 4 Vision Worker — Auto-Detect Regions")
    parser.add_argument("--video-path", required=True)
    parser.add_argument("--time-sec", type=float, default=5.0)
    parser.add_argument("--output-json", required=False, default=None)
    args = parser.parse_args()

    try:
        result = detect_regions(args.video_path, args.time_sec)
    except Exception as e:
        result = {
            "face_count": 0,
            "face_confidence": 0.0,
            "faces": [],
            "facecam_box": None,
            "gameplay_box": None,
            "mode_suggestion": "gaming",
            "message": f"Vision worker error: {e}",
        }

    output = json.dumps(result)

    if args.output_json:
        Path(args.output_json).write_text(output, encoding="utf-8")

    # Always print to stdout for subprocess communication
    print(f"RESULT:{output}", flush=True)
    sys.exit(0)


if __name__ == "__main__":
    main()
