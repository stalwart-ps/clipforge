# Phase 6 handoff — in progress

## Goal

Implement only `SPEC.md` Phase 6 on the Phase 5 branch: waveform trim handles, 5-second preview, optional -14 LUFS normalization, configurable dead-air removal, and cancellable batch exports with optional `.srt`, `.ass`, `.json`, and `.txt` sidecars.

## Existing code and decisions

- Branch confirmed: `prateek-phase-5`.
- Projects store candidate clip bounds and word timestamps in SQLite. Phase 5 provides `generate_ass` and a project caption file service.
- Phase 4 provides a framing filter builder with CFR output and NVENC-to-libx264 fallback, but its synchronous render route does not track/cancel the FFmpeg process.
- Export queue will run sequentially per batch in-process. FFmpeg is spawned asynchronously and registered under a unique job ID with `ProcessManager`; cancellation terminates the process tree, awaits process exit, marks the job cancelled, and prevents later clips from starting.
- Silence removal will use `silencedetect`, then trim and concatenate matching source-time intervals for video and audio in a shared filter graph. Transcript cue times will be mapped through these same kept intervals. All preview/export video uses `-fps_mode cfr`.
- React workbench will draw the available engagement audio-energy points to Canvas (and show a neutral waveform when absent), use trim handles, load the clip video preview, receive progress through project WebSocket, and avoid polling.

## Files expected

- Create `backend/app/exports/{__init__.py,schemas.py,media.py,service.py,router.py}`.
- Modify `backend/app/main.py` to mount API routes and shut down active jobs cleanly.
- Create `frontend/src/pages/ExportWorkbench.tsx`; modify API types/client, `App.tsx`, and `Header.tsx`.
- Add focused backend tests for synchronized silence graph construction, sidecar timeline mapping, CFR, and 5-second preview command.

## Checklist

- [x] Backend schemas, FFmpeg helpers, queue/routes, sidecars.
- [x] Frontend canvas trim/editor, preview, queue, and cancellation controls.
- [x] Run requested builds/checks and record startup time + idle RAM or exact runtime blocker against SPEC Section 2.

## Progress

- 2026-11-22: Recon confirmed Phase 5 branch and actual source files; prior branch mismatch resolved by user steering. No implementation work started yet.
- 2026-11-22: Added `backend/tests/test_phase6_media.py` for caption remapping through kept intervals, synchronized trim/concat graph construction, loudnorm, CFR, and exact five-second preview duration. Confirmed expected red failure: `app.exports` module does not exist (`PYTHONPATH=backend python -m unittest discover -s backend/tests -p test_phase6_media.py -v`).
- 2026-11-22: Implemented tested media helpers, silence detection/interval mapping, ASS/SRT generation from saved word timestamps, metadata sidecars, asynchronous sequential batch worker, job-specific ProcessManager cancellation with task/process reap, preview/batch/status/cancel/download routes, API registration, and shutdown cleanup. Focused backend tests now pass (3/3); Python compileall and `git diff --check` pass.
- 2026-11-22: Implemented Canvas waveform trim handles, candidate selection, export controls, five-second preview playback, WebSocket queue progress/cancel, and local output downloads. `npm run build` passed before the final small layout-template selector was added; user then directed to stop further testing, so that last UI edit was not rebuilt.
- 2026-11-22: Temporary runtime-only FastAPI/SQLite dependencies were installed outside the repository for Section 2 measurement. Uvicorn served `/api/settings` in 1.62s; idle Uvicorn process-tree RSS was 94.5 MB after settling; the verification server process tree was stopped. This is within the SPEC 1–2s startup target and remains lightweight compared with loading AI workers.
- 2026-11-22: A local synthetic FFmpeg end-to-end attempt was stopped at the user's direction. The bundled temporary FFmpeg executable could run directly, but invoking it from the API worker returned Windows `WinError 5: Access is denied`; therefore no actual media render or mid-render cancellation was verified in this environment. The tested pure helper checks (3/3), Python syntax compile, and `git diff --check` had passed before this attempt. The system PATH still does not provide FFmpeg.
- Final code status: Phase 6 implementation is present. Remaining verification limitation: run a real preview/export and mid-batch cancellation on a machine where FFmpeg is executable by the backend.
