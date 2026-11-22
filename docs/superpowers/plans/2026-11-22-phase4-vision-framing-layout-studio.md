# Phase 4 — Vision Framing Engine, Interactive Layout Studio & Saved Profiles

> **For agentic workers:** REQUIRED SUB-SKILL: executing-plans

**Goal:** Build all five framing modes (Gaming/Podcast/Talking Head/Screen+Presenter/Reaction), the HTML5 Canvas crop-region editor with safe-zone overlays and watermark controls, the FFmpeg filter_complex builder with cfr + nvenc/x264 fallback, the Saved Profiles CRUD API, and a 5-second test render script.

**Architecture:** New `backend/app/framing/` module handles Profiles CRUD, Auto-Detect (vision_worker subprocess), and filter_complex building. A new `backend/workers/vision_worker.py` runs MediaPipe + OpenCV in isolation. The Canvas Layout Studio is a new React component in `frontend/src/pages/LayoutStudio.tsx` that talks to these new API endpoints and renders on an `<canvas>` with draggable boxes.

**Tech Stack:** Python (FastAPI, OpenCV, MediaPipe in subprocess), FFmpeg filter_complex (h264_nvenc / libx264 fallback, -fps_mode cfr), React 18 + HTML5 Canvas, Tailwind CSS.

**Spec:** d:/clipping/my app/SPEC.md (Section 4.D, 4.E, 4.G)

## Global Constraints

- Zero heavy imports (cv2, mediapipe, ultralytics) at FastAPI startup — only inside subprocess workers.
- FFmpeg must always use `-fps_mode cfr` on output; h264_nvenc attempted first, fallback to libx264 on non-zero exit code.
- All vision heavy work in isolated `backend/workers/vision_worker.py` subprocess that exits completely before next stage.
- SQLite migration via PRAGMA check in init_db() — no Alembic.
- React+TS must compile with `tsc` strict (no unused imports, no implicit any).
- Single-port FastAPI at :8000 serving frontend/dist.

## Review Focus

- VFR input (OBS recordings): `-fps_mode cfr` must appear on the OUTPUT side, not input side.
- MediaPipe Face Mesh deadband: without it, every small lip movement triggers a camera pan.
- Scene-cut reset: smoothing state must zero out exactly on detected cut boundaries.
- NVENC fallback: when h264_nvenc is not available FFmpeg returns non-zero; must catch and retry with libx264.
- Canvas DnD on mobile/touch: mousedown/mousemove/mouseup only; not needed here (desktop app).

---

## Task 1: Backend — Framing Schemas & SQLite Model

**Files:**
- Create: `backend/app/framing/__init__.py`
- Create: `backend/app/framing/models.py`
- Create: `backend/app/framing/schemas.py`
- Modify: `backend/app/core/db.py` (add migration for `saved_profiles` table + Phase 4 columns on `projects`)
- Modify: `backend/app/projects/models.py` (add framing_config_json, render_path columns)

**Interfaces:**
- Produces: `SavedProfile` SQLAlchemy model, `FramingConfig` Pydantic schema (layout, regions, aspect_ratio, watermark, framing_mode), `ProfileRead/Create` schemas.

## Task 2: Backend — Saved Profiles CRUD Router

**Files:**
- Create: `backend/app/framing/router.py`
- Create: `backend/app/framing/service.py`
- Modify: `backend/app/main.py` (include framing router)

**Interfaces:**
- Consumes: Task 1 schemas
- Produces: REST endpoints `GET /api/profiles`, `POST /api/profiles`, `GET /api/profiles/{id}`, `PUT /api/profiles/{id}`, `DELETE /api/profiles/{id}`

## Task 3: Backend — On-Demand Frame JPEG Extractor

**Files:**
- Modify: `backend/app/media/ffmpeg.py` (add `extract_frame_jpeg(video_path, time_sec, output_jpg)`)
- Modify: `backend/app/projects/router.py` (add `GET /api/projects/{id}/frame?t=<seconds>`)

**Interfaces:**
- Produces: `GET /api/projects/{id}/frame?t=10.5` → JPEG response (uses input-seeking `-ss` before `-i` for speed, single frame only)

## Task 4: Backend — Vision Worker (Auto-Detect Regions)

**Files:**
- Create: `backend/workers/vision_worker.py`
- Create: `backend/app/framing/auto_detect.py`
- Modify: `backend/app/framing/router.py` (add `POST /api/projects/{id}/auto-detect-regions`)

**Interfaces:**
- Produces: `AutoDetectResult { facecam_box: Box | None, gameplay_box: Box | None, face_confidence: float, mode_suggestion: str }`
- Worker prints `RESULT:{json}` to stdout on exit

## Task 5: Backend — FFmpeg filter_complex Builder & Render Worker

**Files:**
- Create: `backend/app/framing/ffmpeg_builder.py`
- Create: `backend/workers/render_worker.py`
- Modify: `backend/app/framing/router.py` (add `POST /api/projects/{id}/render`)
- Modify: `backend/app/framing/schemas.py` (add RenderRequest schema)

**Interfaces:**
- `build_filter_complex(config: FramingConfig, src_w, src_h, out_w, out_h) -> str`
- `render_clip(project_id, clip, config, output_path) -> None` (subprocess with NVENC fallback)

## Task 6: Backend — Tests (Phase 4)

**Files:**
- Create: `tests/test_phase4_framing.py`

Tests:
- `test_profile_crud` — POST create, GET list, PUT update, DELETE
- `test_frame_jpeg_extractor` — GET /api/projects/{id}/frame?t=1 returns JPEG bytes
- `test_filter_complex_builder` — all 5 modes produce valid filter strings with cfr flag
- `test_render_worker_nvenc_fallback` — if nvenc unavailable, libx264 output exists
- `test_startup_imports_no_cv2` — ensure cv2/mediapipe not imported at startup

## Task 7: Frontend — Types & API Client Extensions

**Files:**
- Modify: `frontend/src/types/project.ts` (add FramingConfig, SavedProfile, RegionBox types)
- Modify: `frontend/src/api/client.ts` (add profiles CRUD methods, getFrameUrl, autoDetectRegions, renderClip)

## Task 8: Frontend — Canvas Layout Studio Page

**Files:**
- Create: `frontend/src/pages/LayoutStudio.tsx`
- Modify: `frontend/src/App.tsx` (add route/tab for Layout Studio)

Canvas must support:
- Draggable + resizable FacecamBox (magenta) and GameplayBox (cyan) over a live JPEG preview
- Aspect ratio selector (9:16 / 1:1 / 16:9)
- Mode selector (Gaming / Podcast / Talking Head / Screen+Presenter / Reaction)
- Safe-zone overlay toggle (YouTube Shorts / Reels / TikTok)
- Brand Watermark: file upload, corner, scale, opacity
- Auto-Detect Regions button
- Saved Profiles panel (1-click load, Save as Profile)

## Task 9: Verification Script — 5-Second Sample Split-Screen Render

**Files:**
- Create: `scripts/test_render_phase4.py`

Renders a 5s split-screen clip from the first project in the DB using Gaming mode with libx264 fallback, prints output path.
