# Dynamic Facecam Tracking Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an optional "Dynamic Facecam Tracking" toggle for `split_vertical` and `pip` layouts in ClipForge Local to follow repositioned streamer overlays without modifying `.venv` packages or causing RAM spikes.

**Architecture:** An isolated Python worker (`vision_worker.py`) executes `track_facecam` across the clip's `[start_sec, end_sec]` range sampled at 2 FPS using OpenCV `grab()`, MediaPipe FaceDetection with `model_selection=1`, and HSV histogram correlation filtering (>= 0.35) against streamer overlay borders. `ffmpeg_builder.py` builds animated nested `if(gte(t\,ts),px,prev)` crop expressions with pixel bounds clamping. Workspace SQLite configs, export pipelines, and `LayoutStudio.tsx` toggle this feature.

**Tech Stack:** Python 3.11, OpenCV (`cv2`), MediaPipe 0.10.21 (`mp.solutions.face_detection`), FFmpeg filter_complex, FastAPI, Pydantic v2, React 18, TypeScript, Tailwind CSS.

**Spec:** User prompt requirements and approved design doc from brainstorming.

## Global Constraints

- Do not modify or reinstall `.venv` packages (`mediapipe==0.10.21`, `opencv-python`).
- Avoid RAM spikes: downscale sampled frames to max width 640px, use `cap.grab()` to skip non-sampled frames, close MediaPipe with a context manager, release `cap` in `finally`, and run `gc.collect()` every 100 frames.
- Seek directly to `start_sec` via `cap.set(cv2.CAP_PROP_POS_MSEC, start_sec * 1000)` before the frame sampling loop so full-length videos are never scanned from 0:00.
- Reference HSV histogram is computed from the first sampled frame where a face is detected inside `facecam_box`, masking out the center face.
- Reject candidate faces below correlation `0.35`.
- Deadzone: only emit keyframes when `x` or `y` shifts by `> 0.05` persisting for 2 consecutive samples; cap output at max 25 keyframes per clip.
- Keep FFmpeg crop `w` and `h` strictly even (`& ~1`), and clamp `x` and `y` within `[0, src_w - w]` and `[0, src_h - h]`.
- Frontend and backend API field aliases must cleanly support `dynamicFacecamTracking` / `dynamic_facecam_tracking`.

## Review Focus

1. Video with no detected faces or candidate correlation < 0.35: holds initial static `facecam_box` without crashing or producing out-of-bounds crops.
2. Sudden 1-frame jitter/glitch: deadzone filter suppresses movement that does not persist for 2 consecutive samples.
3. Repositioned facecam overlay shifts near frame borders: crop pixel values clamp safely to `[0, src_w - w]` and `[0, src_h - h]`.
4. Over-quota movement: clips with continuous overlay changes clamp to 25 keyframes.
5. Export with toggle disabled: produces standard static crop filtergraph identical to existing behavior.

---

### Task 1: Backend Tracker in `backend/workers/vision_worker.py` and `backend/app/framing/auto_detect.py`

**Files:**
- Modify: `backend/workers/vision_worker.py`
- Modify: `backend/app/framing/auto_detect.py`
- Test: `tests/test_vision_tracker.py`

**Interfaces:**
- Consumes: CLI args `--track-facecam`, `--video-path`, `--track-start`, `--track-end`, `--facecam-box` (JSON string or coords).
- Produces: `track_facecam(video_path: str, start_sec: float, end_sec: float, facecam_box: dict) -> dict` returning `{"tracks": list[dict]}` where each item is `{"time": float, "x": float, "y": float}`.
- Produces in `auto_detect.py`: `async def track_facecam_overlay(video_path: str, start_sec: float, end_sec: float, facecam_box: dict) -> list[dict]`.

- [ ] **Step 1: Write unit tests for facecam tracker logic and deadzone filtering in `tests/test_vision_tracker.py`**
- [ ] **Step 2: Run test to verify it fails**
  Run: `& ".\.venv\Scripts\python.exe" -m pytest tests/test_vision_tracker.py -q`
- [ ] **Step 3: Implement `track_facecam` in `backend/workers/vision_worker.py` and helper in `auto_detect.py`**
  Implement direct seek `cap.set(cv2.CAP_PROP_POS_MSEC, start_sec * 1000)`, 2 FPS sampling with `cap.grab()`, max width 640px, context-managed MediaPipe FaceDetection (`model_selection=1`), first-detected-face HSV reference histogram with center face exclusion, candidate correlation scoring with threshold 0.35, stability deadzone (>0.05 shift for 2 consecutive samples), max 25 keyframes cap, and `gc.collect()` every 100 frames.
- [ ] **Step 4: Run test to verify it passes**
  Run: `& ".\.venv\Scripts\python.exe" -m pytest tests/test_vision_tracker.py -q`
- [ ] **Step 5: Commit changes**

---

### Task 2: Animated Crop Filtergraph in `backend/app/framing/ffmpeg_builder.py`

**Files:**
- Modify: `backend/app/framing/ffmpeg_builder.py`
- Test: `tests/test_dynamic_facecam_filter.py`

**Interfaces:**
- Consumes: `facecam_tracks: list[dict] | None` passed to `build_filter_complex(...)` and `build_ffmpeg_cmd(...)`.
- Produces: Animated `crop={w}:{h}:x='{x_expr}':y='{y_expr}'` with nested `if(gte(t\,{ts:.3f})\,{px}\,{prev})` expressions, even `w, h`, and coordinates clamped within `[0, src_w - w]` and `[0, src_h - h]`.

- [ ] **Step 1: Write unit tests for animated facecam crop in `tests/test_dynamic_facecam_filter.py`**
  Verify `split_vertical` and `pip` layouts produce dynamic crop expressions when `facecam_tracks` are present, with correct clamping and even dimensions.
- [ ] **Step 2: Run test to verify it fails**
  Run: `& ".\.venv\Scripts\python.exe" -m pytest tests/test_dynamic_facecam_filter.py -q`
- [ ] **Step 3: Update `build_filter_complex` in `backend/app/framing/ffmpeg_builder.py`**
  Add `facecam_tracks: list[dict] | None = None` argument. Build animated `x_expr` and `y_expr` for `split_vertical` (both standard and presenter) and `_pip_overlay` when `facecam_tracks` contains keyframes. Ensure coordinates are clamped and width/height remain even.
- [ ] **Step 4: Run test to verify it passes**
  Run: `& ".\.venv\Scripts\python.exe" -m pytest tests/test_dynamic_facecam_filter.py -q`
- [ ] **Step 5: Commit changes**

---

### Task 3: Schemas, Export Wiring & Frontend UI Toggle

**Files:**
- Modify: `backend/app/framing/schemas.py`
- Modify: `backend/app/exports/service.py`
- Modify: `frontend/src/types/project.ts`
- Modify: `frontend/src/pages/LayoutStudio.tsx`
- Modify: `frontend/src/pages/ExportWorkbench.tsx`

**Interfaces:**
- Consumes: `dynamicFacecamTracking` boolean from `LayoutStudio.tsx` persisted to `WorkspaceConfig.layout_config_json`.
- Produces: `FramingConfig.dynamic_facecam_tracking` (alias `dynamicFacecamTracking`) in Python and TypeScript.
- Integrates: When `dynamic_facecam_tracking` is true during export/preview, executes `track_facecam_overlay` in `service.py` and passes tracks into `build_filter_complex`.
- UI: Adds "Dynamic Facecam Tracking (Auto-Follow Overlay Moves)" toggle under Region Picker canvas.

- [ ] **Step 1: Add `dynamic_facecam_tracking` to `FramingConfig`, `ProfileCreate`, `ProfileUpdate`, `ProfileRead` in `backend/app/framing/schemas.py`**
- [ ] **Step 2: Wire tracking subprocess call into `backend/app/exports/service.py`**
  In `_run_batch` and `render_preview`, check `framing_config.dynamic_facecam_tracking`. If True, layout is `split_vertical` or `pip`, and `facecam_box` exists, run `track_facecam_overlay` and forward `facecam_tracks` to `build_filter_complex`. Also preserve and resolve `dynamicFacecamTracking` in `_resolve_framing_config`.
- [ ] **Step 3: Update frontend types in `frontend/src/types/project.ts`**
  Add `dynamicFacecamTracking?: boolean;` to `FramingConfig` and `SavedProfile`.
- [ ] **Step 4: Add UI Toggle in `frontend/src/pages/LayoutStudio.tsx` and wire in `ExportWorkbench.tsx`**
  Add toggle state, load from workspace config, autosave, and render modern toggle beneath Region Picker.
- [ ] **Step 5: Verify frontend build and Python syntax**
  Run `npm run build` in `frontend/` and python syntax check across modified files.
- [ ] **Step 6: Commit changes**
