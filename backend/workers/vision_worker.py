"""Phase 4 — Vision Worker subprocess for Auto-Detect Regions.

USAGE (called by auto_detect.py as an isolated subprocess):
  python vision_worker.py --video-path <path> --time-sec <float> --output-json <path>

Imports mediapipe and cv2 ONLY inside this module.
Never imported at FastAPI startup.

Outputs single line:  RESULT:{json}
"""
import numpy as np

import argparse
import json
import sys
from pathlib import Path


def _expand_gaming_facecam(face: dict, mode: str, tightness: str = "medium") -> dict:
    fx = float(face["x"])
    fy = float(face["y"])
    fw = float(face["w"])
    fh = float(face["h"])

    mult = 0.85 if tightness == "close" else (1.15 if tightness == "wide" else 1.0)
    w_mult = 2.8 * mult
    headroom_mult = 0.8 * mult
    torso_mult = 1.8 * mult

    new_w = min(0.35, max(0.20, fw * w_mult))
    new_h = min(0.32, max(0.18, fh * (1.0 + headroom_mult + torso_mult)))
    cx = fx + fw / 2.0
    cy = fy + fh / 2.0

    # Anchor towards nearest corner/edge
    if cx < 0.35:
        new_x = max(0.0, min(fx - 0.2 * new_w, 1.0 - new_w))
    elif cx > 0.65:
        new_x = max(0.0, min(1.0 - new_w, fx + fw + 0.2 * new_w - new_w))
    else:
        new_x = max(0.0, min(1.0 - new_w, cx - new_w / 2.0))

    if cy < 0.35:
        new_y = max(0.0, min(fy - headroom_mult * fh, 1.0 - new_h))
    elif cy > 0.65:
        new_y = max(0.0, min(1.0 - new_h, (fy + fh + torso_mult * fh) - new_h))
    else:
        new_y = max(0.0, min(1.0 - new_h, fy - headroom_mult * fh))

    return {
        "x": round(new_x, 4),
        "y": round(new_y, 4),
        "w": round(new_w, 4),
        "h": round(new_h, 4),
    }


def _frame_person_box(
    face: dict,
    pane_ar: float,
    src_ar: float,
    layout_template: str,
    tightness: str = "medium",
) -> dict:
    fx = float(face["x"])
    fy = float(face["y"])
    fw = float(face["w"])
    fh = float(face["h"])
    cx = fx + fw / 2.0
    cy = fy + fh / 2.0

    mult = 0.92 if tightness == "close" else (1.08 if tightness == "wide" else 1.0)

    if layout_template in ("split_vertical", "split_inverted"):
        # Split vertical / inverted (e.g. 50/50 on 9:16 -> pane_ar ~= 1.125):
        # Frame each person with a wider, upper-body box matching pane_ar
        # roughly w ~= 38%-46%, h ~= 58%-68% on 16:9 so Fill mode does NOT zoom in or clip heads
        h = max(0.58, min(0.68, 0.63 * mult))
        target_w = h * (pane_ar / src_ar) if src_ar > 0 else 0.42
        w = max(0.38, min(0.46, target_w))

        headroom = max(0.05, 0.75 * fh * mult)
        top = fy - headroom
        if top + h > 1.0:
            top = max(0.0, 1.0 - h)
        if top < 0.0:
            top = 0.0

        new_x = max(0.0, min(1.0 - w, cx - w / 2.0))
        new_y = top
    else:
        # podcast_active_speaker, fullscreen_crop, punch_in_zoom (9:16 portrait -> pane_ar ~= 0.5625)
        # and side_by_side_blur / wide_plus_dual bottom panes:
        # keep the portrait framing (w ~= 22%-28%, h ~= 62%-76%)
        h = max(0.62, min(0.76, 0.69 * mult))
        target_w = h * (pane_ar / src_ar) if src_ar > 0 else 0.25
        w = max(0.22, min(0.28, target_w))

        headroom = max(0.04, 0.65 * fh * mult)
        top = fy - headroom
        if top + h > 1.0:
            top = max(0.0, 1.0 - h)
        if top < 0.0:
            top = 0.0

        new_x = max(0.0, min(1.0 - w, cx - w / 2.0))
        new_y = top

    return {
        "x": round(new_x, 4),
        "y": round(new_y, 4),
        "w": round(w, 4),
        "h": round(h, 4),
    }


def _expand_face_box(face: dict, mode: str, tightness: str = "medium") -> dict:
    if mode in ("gaming", "screen_presenter"):
        return _expand_gaming_facecam(face, mode, tightness)
    return _frame_person_box(face, 1.125, 16.0 / 9.0, "split_vertical", tightness)


def detect_regions(
    video_path: str,
    time_sec: float = 1.0,
    framing_mode: str = "gaming",
    tightness: str = "medium",
    layout_template: str = "split_vertical",
    aspect_ratio: str = "9:16",
    split_ratio: int = 50,
) -> dict:
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
    if not Path(video_path).exists():
        return {
            "face_count": 0,
            "face_confidence": 0.0,
            "faces": [],
            "facecam_box": None,
            "gameplay_box": {"x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0},
            "mode_suggestion": framing_mode or "gaming",
            "message": "Video file does not exist",
        }

    import cv2  # noqa: F401

    def _read_frame(t: float) -> tuple[np.ndarray | None, float, float]:
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            return None, 30.0, 0.0
        fps_val = cap.get(cv2.CAP_PROP_FPS) or 30.0
        total_f = cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0.0
        dur = total_f / max(1.0, fps_val)
        idx = min(int(round(t * fps_val)), max(0, int(total_f) - 1)) if total_f > 0 else int(round(t * fps_val))
        cap.set(cv2.CAP_PROP_POS_FRAMES, max(0, idx))
        r, f = cap.read()
        cap.release()
        return (f if r and f is not None else None), fps_val, dur

    frame, fps, duration = _read_frame(time_sec)
    if frame is None:
        return {
            "face_count": 0,
            "face_confidence": 0.0,
            "faces": [],
            "facecam_box": None,
            "gameplay_box": None,
            "mode_suggestion": "gaming",
            "message": "Failed to read frame",
        }

    faces_data: list[dict] = []

    model_dir = Path(__file__).resolve().parents[1] / "models" / "face"
    det_model_path = model_dir / "det_10g.onnx"

    if det_model_path.exists():
        try:
            from backend.workers.face_engine import FaceEngine
        except ImportError:
            from workers.face_engine import FaceEngine

        def _is_corner_face(f: dict) -> bool:
            cx = float(f.get("cx", f["x"] + f["w"] / 2.0))
            cy = float(f.get("cy", f["y"] + f["h"] / 2.0))
            if (cx <= 0.40 or cx >= 0.60) and (cy <= 0.45 or cy >= 0.55):
                return True
            if cx <= 0.35 or cx >= 0.65 or cy <= 0.30 or cy >= 0.70:
                return True
            return False

        def _run_quadrant_pass(engine: FaceEngine, img_bgr: np.ndarray) -> list[dict]:
            img_h, img_w = img_bgr.shape[:2]
            qw = int(round(img_w * 0.55))
            qh = int(round(img_h * 0.55))
            quads = [
                (0, 0, qw, qh),
                (img_w - qw, 0, qw, qh),
                (0, img_h - qh, qw, qh),
                (img_w - qw, img_h - qh, qw, qh),
            ]
            q_faces: list[dict] = []
            for ox, oy, bw, bh in quads:
                crop = img_bgr[oy:oy + bh, ox:ox + bw]
                dets = engine.detect(crop, input_size=(640, 640), score_thresh=0.28, nms_thresh=0.40)
                for d in dets:
                    nx = (ox + d["x"] * bw) / img_w
                    ny = (oy + d["y"] * bh) / img_h
                    nw = (d["w"] * bw) / img_w
                    nh = (d["h"] * bh) / img_h
                    kps_px = [[float(ox + kp[0]), float(oy + kp[1])] for kp in d.get("kps", [])]
                    q_faces.append({
                        "x": round(max(0.0, min(1.0, nx)), 4),
                        "y": round(max(0.0, min(1.0, ny)), 4),
                        "w": round(max(0.001, min(1.0 - nx, nw)), 4),
                        "h": round(max(0.001, min(1.0 - ny, nh)), 4),
                        "cx": round(nx + nw / 2.0, 4),
                        "cy": round(ny + nh / 2.0, 4),
                        "confidence": d["confidence"],
                        "score": d["score"],
                        "kps": kps_px,
                    })
            return q_faces

        def _dedup_faces(flist: list[dict], iou_thresh: float = 0.35) -> list[dict]:
            if not flist:
                return []
            flist_sorted = sorted(flist, key=lambda f: f["confidence"], reverse=True)
            kept = []
            for f in flist_sorted:
                ovr = False
                for k in kept:
                    x1 = max(f["x"], k["x"])
                    y1 = max(f["y"], k["y"])
                    x2 = min(f["x"] + f["w"], k["x"] + k["w"])
                    y2 = min(f["y"] + f["h"], k["y"] + k["h"])
                    inter = max(0.0, x2 - x1) * max(0.0, y2 - y1)
                    union = (f["w"] * f["h"]) + (k["w"] * k["h"]) - inter
                    if union > 0 and (inter / union) > iou_thresh:
                        ovr = True
                        break
                if not ovr:
                    kept.append(f)
            return kept

        with FaceEngine(load_recognizer=False) as engine:
            # 1. Full frame at input_size=(960, 960) with score_thresh=0.30
            raw_dets = engine.detect(frame, input_size=(960, 960), score_thresh=0.30)
            faces_data = _dedup_faces(raw_dets)

            # 2. If 0 faces (or gaming mode with no corner face), run 4-quadrant corner pass
            need_quad = (len(faces_data) == 0) or (framing_mode == "gaming" and not any(_is_corner_face(f) for f in faces_data))
            if need_quad:
                q_dets = _run_quadrant_pass(engine, frame)
                if q_dets:
                    combined = _dedup_faces(q_dets + faces_data)
                    if framing_mode == "gaming":
                        corner_f = [f for f in combined if _is_corner_face(f)]
                        faces_data = corner_f if corner_f else combined
                    else:
                        faces_data = combined

            # 3. If still 0, probe nearby timestamps: +2s, -2s, +5s, +10s
            if len(faces_data) == 0 or (framing_mode == "gaming" and not any(_is_corner_face(f) for f in faces_data)):
                probe_offsets = [2.0, -2.0, 5.0, 10.0]
                for off in probe_offsets:
                    probe_t = time_sec + off
                    if probe_t < 0.0 or (duration > 0.0 and probe_t > duration):
                        continue
                    p_frame, _, _ = _read_frame(probe_t)
                    if p_frame is None:
                        continue
                    p_dets = engine.detect(p_frame, input_size=(960, 960), score_thresh=0.30)
                    if len(p_dets) == 0 or (framing_mode == "gaming" and not any(_is_corner_face(f) for f in p_dets)):
                        p_quad = _run_quadrant_pass(engine, p_frame)
                        if p_quad:
                            p_dets = _dedup_faces(p_quad + p_dets)

                    if p_dets:
                        if framing_mode == "gaming":
                            c_faces = [f for f in p_dets if _is_corner_face(f)]
                            if c_faces:
                                faces_data = c_faces
                                break
                            elif len(faces_data) == 0:
                                faces_data = p_dets
                                break
                        else:
                            faces_data = p_dets
                            break
    else:
        # Fallback gracefully to MediaPipe ONLY if det_10g.onnx is missing
        import mediapipe as mp  # noqa: F401
        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        mp_face = mp.solutions.face_detection
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

    src_h, src_w = frame.shape[:2]
    src_ar = src_w / max(1, src_h)

    # Output dimensions per aspect ratio
    canvas_dims = {
        "9:16": (1080, 1920),
        "1:1": (1080, 1080),
        "16:9": (1920, 1080),
    }
    canvas_w, canvas_h = canvas_dims.get(aspect_ratio, (1080, 1920))

    # Compute target pane aspect ratio (pane_ar = pane_w / pane_h)
    if layout_template in ("split_vertical", "split_inverted"):
        pane_w = canvas_w
        ratio = max(10, min(90, split_ratio))
        pane_h = max(2, int(canvas_h * (ratio / 100)))
        pane_ar = pane_w / max(1, pane_h)
    elif layout_template in ("podcast_active_speaker", "fullscreen_crop", "punch_in_zoom"):
        pane_ar = canvas_w / max(1, canvas_h)
    elif layout_template == "side_by_side_blur":
        left_w = (canvas_w // 2) & ~1
        pane_h = max(2, min(canvas_h, int(left_w * (16 / 9)) & ~1))
        pane_ar = left_w / max(1, pane_h)
    elif layout_template == "wide_plus_dual":
        top_h = 690 if (canvas_w, canvas_h) == (1080, 1920) else max(2, int(canvas_h * 0.36) & ~1)
        bot_h = canvas_h - top_h
        pane_w = (canvas_w // 2) & ~1
        pane_ar = pane_w / max(1, bot_h)
    else:
        pane_ar = canvas_w / max(1, canvas_h)

    # -------------------------------------------------------------------------
    # Mode-aware Smart Person / Torso Expansion
    # -------------------------------------------------------------------------
    facecam_box = None
    gameplay_box = None
    mode_suggestion = framing_mode

    if face_count == 0:
        # No face → fullscreen gameplay / no-face fallback
        gameplay_box = {"x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0}
        mode_suggestion = framing_mode or "gaming"
    elif framing_mode == "podcast":
        mode_suggestion = "podcast"
        if face_count >= 2:
            # Sort left-to-right by horizontal position
            faces_sorted = sorted(faces_data, key=lambda f: f["x"])
            f1, f2 = faces_sorted[0], faces_sorted[1]
            b1 = _frame_person_box(f1, pane_ar, src_ar, layout_template, tightness)
            b2 = _frame_person_box(f2, pane_ar, src_ar, layout_template, tightness)

            # Prevent heavy horizontal overlap and respect midpoint separation
            f1_cx = f1["x"] + f1["w"] / 2.0
            f2_cx = f2["x"] + f2["w"] / 2.0
            mid_x = (f1_cx + f2_cx) / 2.0

            if b1["x"] + b1["w"] > mid_x:
                shift = (b1["x"] + b1["w"]) - mid_x
                b1["x"] = max(0.0, round(b1["x"] - shift, 4))
                if b1["x"] + b1["w"] > mid_x:
                    b1["w"] = max(0.12, round(mid_x - b1["x"], 4))

            if b2["x"] < mid_x:
                shift = mid_x - b2["x"]
                b2["x"] = min(round(1.0 - b2["w"], 4), round(b2["x"] + shift, 4))
                if b2["x"] < mid_x:
                    b2["x"] = round(mid_x, 4)
                    b2["w"] = max(0.12, min(round(1.0 - b2["x"], 4), b2["w"]))

            facecam_box = b1  # Person 1
            gameplay_box = b2  # Person 2
        else:
            facecam_box = _frame_person_box(faces_data[0], pane_ar, src_ar, layout_template, tightness)
            gameplay_box = {"x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0}
    elif framing_mode == "talking_head":
        mode_suggestion = "talking_head"
        f = max(faces_data, key=lambda f: f["w"] * f["h"])
        facecam_box = _frame_person_box(f, pane_ar, src_ar, layout_template, tightness)
        gameplay_box = {"x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0}
    elif framing_mode == "reaction":
        mode_suggestion = "reaction"
        f = max(faces_data, key=lambda f: f["w"] * f["h"])
        if layout_template == "pip":
            facecam_box = _expand_gaming_facecam(f, "reaction", tightness)
        else:
            facecam_box = _frame_person_box(f, pane_ar, src_ar, layout_template, tightness)
        gameplay_box = {"x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0}
    elif framing_mode in ("gaming", "screen_presenter"):
        mode_suggestion = framing_mode
        # Expand detected face into realistic webcam/presenter crop
        # In gaming/presenter, do NOT assign a second face as gameplay.
        f = max(faces_data, key=lambda f: f["confidence"])
        facecam_box = _expand_gaming_facecam(f, framing_mode, tightness)
        gameplay_box = {"x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0}
    else:
        # Generic fallback
        f = faces_data[0]
        facecam_box = _frame_person_box(f, pane_ar, src_ar, layout_template, tightness)
        gameplay_box = {"x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0}
        mode_suggestion = "gaming" if face_count <= 1 else "podcast"

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
        static_image_mode=False, max_num_faces=4, refine_landmarks=False,
        min_detection_confidence=0.45, min_tracking_confidence=0.45,
    )
    try:
        while frame_idx / fps < end_sec:
            # Skip unneeded frames with grab() instead of decoding full uncompressed frames to RAM
            if (frame_idx - round(start_sec * fps)) % step:
                if not cap.grab():
                    break
                frame_idx += 1
                continue

            ok, frame = cap.read()
            if not ok or frame is None:
                break
            t = frame_idx / fps
            if cut_index < len(cuts) and t >= cuts[cut_index]:
                last_cut = cuts[cut_index]
                cut_index += 1
                histories.clear()
                pending_cut = True

            h, w = frame.shape[:2]
            # Downsample large 1080p/4K frames to max dimension 640 for lightweight inference (< 2MB buffer)
            max_dim = max(h, w)
            if max_dim > 640:
                scale = 640.0 / max_dim
                small_frame = cv2.resize(frame, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
                rgb = cv2.cvtColor(small_frame, cv2.COLOR_BGR2RGB)
            else:
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

            result = mesh.process(rgb)
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


def filter_deadzone_keyframes(
    samples: list[dict],
    initial_box: dict,
    deadzone: float = 0.05,
    min_consecutive: int = 2,
    max_keyframes: int = 25,
) -> list[dict]:
    """Filter raw position samples using a stability deadzone.

    Only emits a new keyframe {"time": t_rel, "x": x, "y": y} if x or y shifted
    by more than `deadzone` from the last emitted position and persists for at least
    `min_consecutive` consecutive samples. Capped to `max_keyframes`.
    """
    keyframes: list[dict] = []
    last_emitted_x = float(initial_box.get("x", 0.0))
    last_emitted_y = float(initial_box.get("y", 0.0))

    pending_pos: tuple[float, float] | None = None
    pending_time: float = 0.0
    consecutive_count = 0

    for sample in samples:
        if len(keyframes) >= max_keyframes:
            break

        sx = float(sample["x"])
        sy = float(sample["y"])
        st = float(sample["time"])

        shift_x = abs(sx - last_emitted_x)
        shift_y = abs(sy - last_emitted_y)

        if shift_x > deadzone or shift_y > deadzone:
            if pending_pos is not None:
                if abs(sx - pending_pos[0]) <= deadzone and abs(sy - pending_pos[1]) <= deadzone:
                    consecutive_count += 1
                else:
                    pending_pos = (sx, sy)
                    pending_time = st
                    consecutive_count = 1
            else:
                pending_pos = (sx, sy)
                pending_time = st
                consecutive_count = 1

            if consecutive_count >= min_consecutive:
                keyframes.append({
                    "time": round(pending_time, 3),
                    "x": round(pending_pos[0], 4),
                    "y": round(pending_pos[1], 4),
                })
                last_emitted_x, last_emitted_y = pending_pos[0], pending_pos[1]
                pending_pos = None
                consecutive_count = 0
        else:
            pending_pos = None
            consecutive_count = 0

    return keyframes


def _select_keyframes(samples: list[dict], max_keyframes: int = 45) -> list[dict]:
    """Select up to max_keyframes, guaranteeing inclusion of endpoints and camera cuts."""
    if len(samples) <= max_keyframes:
        return samples

    keep_indices: set[int] = {0, len(samples) - 1}
    for idx, s in enumerate(samples):
        if s.get("cut"):
            keep_indices.add(idx)

    if len(keep_indices) >= max_keyframes:
        return [samples[i] for i in sorted(keep_indices)]

    remaining_quota = max_keyframes - len(keep_indices)
    step = len(samples) / float(remaining_quota + 1)
    for k in range(1, remaining_quota + 1):
        idx = min(len(samples) - 1, int(round(k * step)))
        keep_indices.add(idx)

    return [samples[i] for i in sorted(keep_indices)]


def track_facecam(
    video_path: str,
    start_sec: float,
    end_sec: float,
    facecam_box: dict,
    framing_mode: str = "gaming",
) -> dict:
    """Track facecam overlay within [start_sec, end_sec] at 4 FPS with mode-aware matching and EMA smoothing."""
    import cv2
    import gc
    import mediapipe as mp
    import numpy as np

    fb_x = float(facecam_box.get("x", 0.0))
    fb_y = float(facecam_box.get("y", 0.0))
    fb_w = float(facecam_box.get("w", 0.3))
    fb_h = float(facecam_box.get("h", 0.25))

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return {"tracks": []}

    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    step = max(1, round(fps / 4.0))  # 4 FPS sampling rate

    # Direct seek to start_sec via POS_MSEC
    cap.set(cv2.CAP_PROP_POS_MSEC, max(0.0, start_sec) * 1000.0)
    start_frame_idx = max(0, round(start_sec * fps))
    frame_idx = start_frame_idx

    ref_hist = None
    ref_offset_x = fb_w * 0.5
    ref_offset_y = fb_h * 0.28 if fb_h > 0.35 else fb_h * 0.42
    ref_locked = False
    last_x = fb_x
    last_y = fb_y
    last_cx = fb_x + fb_w / 2.0
    last_cy = fb_y + fb_h / 2.0

    raw_samples: list[dict] = []
    processed_frames = 0

    mp_face = mp.solutions.face_detection
    try:
        with mp_face.FaceDetection(
            model_selection=1,  # Full-range model for far/small faces
            min_detection_confidence=0.25,
        ) as detector:
            while True:
                # Skip non-sampled frames using grab() to avoid decoding to RAM
                if (frame_idx - start_frame_idx) % step != 0:
                    if not cap.grab():
                        break
                    frame_idx += 1
                    continue

                ok, frame = cap.read()
                if not ok or frame is None:
                    break

                pos_ms = cap.get(cv2.CAP_PROP_POS_MSEC)
                actual_ts = (pos_ms / 1000.0) if pos_ms > 0 else (frame_idx / fps)
                if actual_ts >= end_sec:
                    break

                if pos_ms > 0:
                    t_rel = max(0.0, round(pos_ms / 1000.0 - start_sec, 3))
                else:
                    t_rel = max(0.0, round(frame_idx / fps - start_sec, 3))

                h, w = frame.shape[:2]
                if w > 640:
                    scale = 640.0 / w
                    small_frame = cv2.resize(frame, (640, int(h * scale)), interpolation=cv2.INTER_AREA)
                else:
                    small_frame = frame

                sw_h, sw_w = small_frame.shape[:2]
                rgb = cv2.cvtColor(small_frame, cv2.COLOR_BGR2RGB)

                result = detector.process(rgb)
                detected_faces = []
                if result and result.detections:
                    for det in result.detections:
                        bb = det.location_data.relative_bounding_box
                        lx = max(0.0, min(1.0, float(bb.xmin)))
                        ly = max(0.0, min(1.0, float(bb.ymin)))
                        bw = min(1.0 - lx, max(0.001, float(bb.width)))
                        bh = min(1.0 - ly, max(0.001, float(bb.height)))
                        detected_faces.append({
                            "x": lx, "y": ly, "w": bw, "h": bh,
                            "cx": lx + bw / 2.0, "cy": ly + bh / 2.0,
                            "score": float(det.score[0]) if det.score else 0.0,
                        })

                if framing_mode == "gaming":
                    hsv = cv2.cvtColor(small_frame, cv2.COLOR_BGR2HSV)
                    # Build reference histogram on first frame where face is detected inside facecam_box
                    if ref_hist is None:
                        faces_inside = [
                            f for f in detected_faces
                            if fb_x <= f["cx"] <= fb_x + fb_w and fb_y <= f["cy"] <= fb_y + fb_h
                        ]
                        if faces_inside:
                            ref_face = max(faces_inside, key=lambda f: f["w"] * f["h"])
                            ref_offset_x = ref_face["cx"] - fb_x
                            ref_offset_y = ref_face["cy"] - fb_y
                            ref_locked = True

                            px1 = max(0, min(sw_w - 1, int(fb_x * sw_w)))
                            py1 = max(0, min(sw_h - 1, int(fb_y * sw_h)))
                            px2 = max(px1 + 1, min(sw_w, int((fb_x + fb_w) * sw_w)))
                            py2 = max(py1 + 1, min(sw_h, int((fb_y + fb_h) * sw_h)))

                            roi_hsv = hsv[py1:py2, px1:px2]
                            mask = np.ones((py2 - py1, px2 - px1), dtype=np.uint8) * 255

                            # Exclude center face region from reference histogram
                            f_px1 = max(0, min(px2 - px1, int((ref_face["x"] - fb_x) * sw_w)))
                            f_py1 = max(0, min(py2 - py1, int((ref_face["y"] - fb_y) * sw_h)))
                            f_px2 = max(0, min(px2 - px1, int((ref_face["x"] + ref_face["w"] - fb_x) * sw_w)))
                            f_py2 = max(0, min(py2 - py1, int((ref_face["y"] + ref_face["h"] - fb_y) * sw_h)))
                            mask[f_py1:f_py2, f_px1:f_px2] = 0

                            hist = cv2.calcHist([roi_hsv], [0, 1], mask, [30, 32], [0, 180, 0, 256])
                            cv2.normalize(hist, hist, alpha=0, beta=1, norm_type=cv2.NORM_MINMAX)
                            ref_hist = hist
                        target_x, target_y = fb_x, fb_y
                    else:
                        # Match candidate faces against reference HSV histogram (correlation >= 0.30)
                        best_match = None
                        best_score = -1.0

                        for cand in detected_faces:
                            cand_x = max(0.0, min(1.0 - fb_w, cand["cx"] - ref_offset_x))
                            cand_y = max(0.0, min(1.0 - fb_h, cand["cy"] - ref_offset_y))

                            c_px1 = max(0, min(sw_w - 1, int(cand_x * sw_w)))
                            c_py1 = max(0, min(sw_h - 1, int(cand_y * sw_h)))
                            c_px2 = max(c_px1 + 1, min(sw_w, int((cand_x + fb_w) * sw_w)))
                            c_py2 = max(c_py1 + 1, min(sw_h, int((cand_y + fb_h) * sw_h)))

                            c_roi_hsv = hsv[c_py1:c_py2, c_px1:c_px2]
                            c_mask = np.ones((c_py2 - c_py1, c_px2 - c_px1), dtype=np.uint8) * 255

                            cf_px1 = max(0, min(c_px2 - c_px1, int((cand["x"] - cand_x) * sw_w)))
                            cf_py1 = max(0, min(c_py2 - c_py1, int((cand["y"] - cand_y) * sw_h)))
                            cf_px2 = max(0, min(c_px2 - c_px1, int((cand["x"] + cand["w"] - cand_x) * sw_w)))
                            cf_py2 = max(0, min(c_py2 - c_py1, int((cand["y"] + cand["h"] - cand_y) * sw_h)))
                            c_mask[cf_py1:cf_py2, cf_px1:cf_px2] = 0

                            c_hist = cv2.calcHist([c_roi_hsv], [0, 1], c_mask, [30, 32], [0, 180, 0, 256])
                            cv2.normalize(c_hist, c_hist, alpha=0, beta=1, norm_type=cv2.NORM_MINMAX)
                            sim = cv2.compareHist(ref_hist, c_hist, cv2.HISTCMP_CORREL)

                            if sim >= 0.30 and sim > best_score:
                                best_score = sim
                                best_match = (cand_x, cand_y)

                        if best_match is not None:
                            target_x, target_y = best_match
                        else:
                            target_x, target_y = last_x, last_y
                else:
                    # Podcast / Talking Head / Reaction / Screen-Presenter:
                    # Spatial proximity / left-vs-right matching without gaming HSV rejection
                    if not ref_locked:
                        faces_inside = [
                            f for f in detected_faces
                            if fb_x <= f["cx"] <= fb_x + fb_w and fb_y <= f["cy"] <= fb_y + fb_h
                        ]
                        if faces_inside:
                            ref_face = max(faces_inside, key=lambda f: f["w"] * f["h"])
                            ref_offset_x = ref_face["cx"] - fb_x
                            ref_offset_y = ref_face["cy"] - fb_y
                            ref_locked = True

                    if not detected_faces:
                        target_x, target_y = last_x, last_y
                    elif len(detected_faces) == 1:
                        f = detected_faces[0]
                        target_x = max(0.0, min(1.0 - fb_w, f["cx"] - ref_offset_x))
                        target_y = max(0.0, min(1.0 - fb_h, f["cy"] - ref_offset_y))
                    else:
                        init_cx = fb_x + fb_w / 2.0
                        if init_cx < 0.45:
                            same_side = [f for f in detected_faces if f["cx"] <= 0.55]
                            pool = same_side if same_side else detected_faces
                        elif init_cx > 0.55:
                            same_side = [f for f in detected_faces if f["cx"] >= 0.45]
                            pool = same_side if same_side else detected_faces
                        else:
                            pool = detected_faces

                        best_face = min(pool, key=lambda f: (f["cx"] - last_cx)**2 + (f["cy"] - last_cy)**2)
                        target_x = max(0.0, min(1.0 - fb_w, best_face["cx"] - ref_offset_x))
                        target_y = max(0.0, min(1.0 - fb_h, best_face["cy"] - ref_offset_y))

                shift_x = abs(target_x - last_x)
                shift_y = abs(target_y - last_y)

                if shift_x > 0.18 or shift_y > 0.18:
                    # Camera cut: snap immediately without lag
                    curr_x = target_x
                    curr_y = target_y
                    is_cut = True
                else:
                    # Smooth normal motion with EMA (alpha = 0.35)
                    alpha = 0.35
                    curr_x = (1.0 - alpha) * last_x + alpha * target_x
                    curr_y = (1.0 - alpha) * last_y + alpha * target_y
                    is_cut = False

                last_x = curr_x
                last_y = curr_y
                last_cx = curr_x + fb_w / 2.0
                last_cy = curr_y + fb_h / 2.0

                raw_samples.append({
                    "time": t_rel,
                    "x": round(curr_x, 4),
                    "y": round(curr_y, 4),
                    "cut": is_cut,
                })

                processed_frames += 1
                if processed_frames % 100 == 0:
                    gc.collect()

                frame_idx += 1
    finally:
        cap.release()
        gc.collect()

    keyframes = _select_keyframes(raw_samples, max_keyframes=45)
    return {"tracks": keyframes}


def main():
    parser = argparse.ArgumentParser(description="Phase 4 Vision Worker — Auto-Detect Regions")
    parser.add_argument("--video-path", required=True)
    parser.add_argument("--time-sec", type=float, default=5.0)
    parser.add_argument("--output-json", required=False, default=None)
    parser.add_argument("--track-start", type=float, default=None)
    parser.add_argument("--track-end", type=float, default=None)
    parser.add_argument("--track-facecam", action="store_true", default=False)
    parser.add_argument("--facecam-box", type=str, default=None)
    parser.add_argument("--framing-mode", type=str, default="gaming")
    parser.add_argument("--tightness", type=str, default="medium")
    parser.add_argument("--layout-template", type=str, default="split_vertical")
    parser.add_argument("--aspect-ratio", type=str, default="9:16")
    parser.add_argument("--split-ratio", type=int, default=50)
    args = parser.parse_args()

    try:
        if args.track_facecam and args.track_start is not None and args.track_end is not None:
            fb = json.loads(args.facecam_box) if args.facecam_box else {"x": 0.0, "y": 0.0, "w": 0.3, "h": 0.25}
            result = track_facecam(
                args.video_path,
                args.track_start,
                args.track_end,
                fb,
                framing_mode=args.framing_mode,
            )
        elif args.track_start is not None and args.track_end is not None:
            result = detect_active_speaker_tracks(args.video_path, args.track_start, args.track_end)
        else:
            result = detect_regions(
                args.video_path,
                args.time_sec,
                framing_mode=args.framing_mode,
                tightness=args.tightness,
                layout_template=args.layout_template,
                aspect_ratio=args.aspect_ratio,
                split_ratio=args.split_ratio,
            )
    except Exception as e:
        result = {
            "face_count": 0,
            "face_confidence": 0.0,
            "faces": [],
            "facecam_box": None,
            "gameplay_box": None,
            "mode_suggestion": "gaming",
            "tracks": [],
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
