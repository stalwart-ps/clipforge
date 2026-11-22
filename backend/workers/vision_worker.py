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
                left = max(0.0, min(1.0, float(bbox.xmin)))
                top = max(0.0, min(1.0, float(bbox.ymin)))
                faces_data.append(
                    {
                        "x": left,
                        "y": top,
                        "w": min(1.0 - left, max(0.001, float(bbox.width))),
                        "h": min(1.0 - top, max(0.001, float(bbox.height))),
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


def detect_active_speaker_tracks(video_path: str, start_sec: float, end_sec: float) -> dict:
    """Sample Face Mesh mouth motion, select speakers, and smooth focus per cut.

    Heavy vision dependencies are intentionally confined to this worker process.
    PySceneDetect cut boundaries reset both mouth history and camera smoothing.
    """
    import cv2
    import mediapipe as mp
    from scenedetect import ContentDetector, FrameTimecode, SceneManager, open_video

    video = open_video(video_path)
    scene_manager = SceneManager()
    scene_manager.add_detector(ContentDetector(threshold=27.0, min_scene_len=1))
    video.seek(FrameTimecode(start_sec, video.frame_rate))
    scene_manager.detect_scenes(
        video,
        duration=FrameTimecode(max(0.0, end_sec - start_sec), video.frame_rate),
    )
    scenes = scene_manager.get_scene_list()
    cuts = [float(scene[0].get_seconds()) for scene in scenes if start_sec < float(scene[0].get_seconds()) < end_sec]

    cap = cv2.VideoCapture(video_path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    step = max(1, round(fps / 5.0))
    cap.set(cv2.CAP_PROP_POS_MSEC, start_sec * 1000.0)
    sample_sec = step / fps
    rows: list[dict] = []
    histories: dict[int, list[tuple[float, float]]] = {}
    cut_index = 0
    last_cut = start_sec
    pending_cut = False
    frame_idx = max(0, round(start_sec * fps))
    mesh = mp.solutions.face_mesh.FaceMesh(
        static_image_mode=True, max_num_faces=4, refine_landmarks=True,
        min_detection_confidence=0.45,
    )
    try:
        while frame_idx / fps < end_sec:
            ok, frame = cap.read()
            if not ok:
                break
            t = frame_idx / fps
            if cut_index < len(cuts) and t >= cuts[cut_index]:
                last_cut = cuts[cut_index]
                cut_index += 1
                histories.clear()
                pending_cut = True
            if (frame_idx - round(start_sec * fps)) % step:
                frame_idx += 1
                continue
            h, w = frame.shape[:2]
            result = mesh.process(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
            faces = []
            if result.multi_face_landmarks:
                for face_id, landmarks in enumerate(result.multi_face_landmarks):
                    xs = [point.x for point in landmarks.landmark]
                    ys = [point.y for point in landmarks.landmark]
                    # Face Mesh lip landmarks: upper/lower center and mouth corners.
                    lm = landmarks.landmark
                    mouth_open = abs(lm[13].y - lm[14].y) / max(0.01, abs(lm[78].x - lm[308].x))
                    box = {"x": max(0.0, min(xs)), "y": max(0.0, min(ys)),
                           "w": max(0.01, min(1.0, max(xs) - min(xs))),
                           "h": max(0.01, min(1.0, max(ys) - min(ys)))}
                    history = histories.setdefault(face_id, [])
                    history.append((t, mouth_open))
                    history[:] = [entry for entry in history if t - entry[0] <= 1.2]
                    values = [entry[1] for entry in history]
                    variance = (sum((value - sum(values) / len(values)) ** 2 for value in values) / len(values)) if len(values) > 1 else 0.0
                    faces.append({"id": face_id, "box": box, "activity": variance})
            active = max(faces, key=lambda face: face["activity"], default=None)
            rows.append({"time": t - start_sec, "cut": pending_cut,
                         "faces": faces, "active_id": active["id"] if active else None,
                         "box": active["box"] if active else None})
            pending_cut = False
            frame_idx += 1
    finally:
        mesh.close()
        cap.release()

    # Deadband avoids following weak mouth noise. Exponential smoothing is restarted at cuts.
    smoothed = None
    focus = []
    active_id = None
    alpha, deadband = 0.32, 0.0015
    for row in rows:
        box = row["box"]
        if row["cut"]:
            smoothed = None
            active_id = None
        candidate = next((f for f in row["faces"] if f["id"] == row["active_id"]), None)
        if not candidate or candidate["activity"] < deadband:
            box = smoothed
        else:
            if smoothed is None or active_id != candidate["id"]:
                smoothed = dict(box)
            else:
                smoothed = {key: (1 - alpha) * smoothed[key] + alpha * box[key] for key in box}
            active_id = candidate["id"]
            box = smoothed
        focus.append({"time": row["time"], "box": box, "cut": row["cut"]})
    return {"tracks": focus, "cuts": [cut - start_sec for cut in cuts]}


def main():
    parser = argparse.ArgumentParser(description="Phase 4 Vision Worker — Auto-Detect Regions")
    parser.add_argument("--video-path", required=True)
    parser.add_argument("--time-sec", type=float, default=5.0)
    parser.add_argument("--output-json", required=False, default=None)
    parser.add_argument("--track-start", type=float, default=None)
    parser.add_argument("--track-end", type=float, default=None)
    args = parser.parse_args()

    try:
        result = (detect_active_speaker_tracks(args.video_path, args.track_start, args.track_end)
                  if args.track_start is not None and args.track_end is not None
                  else detect_regions(args.video_path, args.time_sec))
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
