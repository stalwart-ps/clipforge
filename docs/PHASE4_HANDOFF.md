# Phase 4 handoff

Phase 4 adds the vision framing engine, Layout Studio, saved profiles, and FFmpeg framing renders.

## Implemented

- Five framing modes: Gaming (including the no-face fullscreen fallback), Podcast, Talking Head, Screen + Presenter, and Reaction.
- Podcast and Talking Head renders run MediaPipe Face Mesh tracking in the isolated vision worker. Mouth-motion activity selects the speaker; deadband and exponential smoothing reduce jitter, and PySceneDetect cuts reset the crop to center.
- FFmpeg filter graph generation supports the framing layouts, watermark compositing, constant frame rate output (`-fps_mode cfr`), and `h264_nvenc` with `libx264` retry.
- Layout Studio is reachable from the app navigation. It has a Canvas region editor and output preview, draggable/resizable Facecam and Gameplay boxes, Auto-Detect Regions, Shorts/Reels/TikTok safe-zone overlays, and PNG watermark upload and controls.
- Saved Channel Profiles can be created, loaded, and deleted through the existing Profiles API. Profiles include layout, region, split, and watermark settings.
- On-demand project frame extraction returns a single JPEG for the Canvas preview.

## Key files

- `backend/app/framing/` — framing schemas, API routes, saved profile service, and FFmpeg filter builder.
- `backend/workers/vision_worker.py` — isolated MediaPipe region and speaker tracking worker.
- `frontend/src/pages/LayoutStudio.tsx` — interactive Canvas editor and preview.
- `scripts/test_render_phase4.py` — renders a 5-second split-screen sample from a supplied video or the first video in the project database.

## Verification

- `npm run build` in `frontend/` passed.
- `python -m compileall -q app workers` and `git diff --check` passed.
- The Python runtime smoke check could not run because `pydantic` is not installed in the current environment. A sample render was not run because no input video was supplied.

To visually check framing, run `python scripts/test_render_phase4.py --video <path-to-video.mp4>` from the repository root (or use the project virtual environment's Python executable).
