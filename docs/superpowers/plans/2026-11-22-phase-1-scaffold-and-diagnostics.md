# Phase 1: Project Scaffold, Lazy Architecture & Hardware Diagnostics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the complete Phase 1 foundation for ClipForge Local, featuring a lazy-loading FastAPI backend, SQLite async database with settings and cache management, rich hardware/system diagnostics, a compiled React/Tailwind workstation UI shell with live telemetry, and an optional `--desktop` native window launcher via `pywebview`.

**Architecture:** 
The backend is structured into three clean layers (router -> service -> database) using FastAPI, Pydantic v2, and SQLAlchemy 2.0 with `aiosqlite`. Zero heavy AI/CV libraries are imported during startup. Diagnostics queries are run asynchronously via subprocesses and HTTP to check GPU/VRAM (`nvidia-smi`), FFmpeg/NVENC, Ollama (`http://localhost:11434`), `yt-dlp`, and JS runtimes (`deno`/`node`). The React + Vite + Tailwind frontend compiles to `frontend/dist` which FastAPI serves on a single port (`8000`), with an optional `--desktop` flag launching `pywebview`.

**Tech Stack:** 
- Python 3.11+, FastAPI, Uvicorn, SQLAlchemy 2.0, aiosqlite, pydantic-settings, httpx, pywebview, psutil
- React 18/19, TypeScript, Vite, Tailwind CSS, Lucide icons
- System CLIs: FFmpeg, nvidia-smi, yt-dlp, Ollama

**Spec:** [SPEC.md](file:///d:/clipping/my%20app/SPEC.md)

---

## Global Constraints

- Python runtime: Python 3.11+ compatibility.
- Zero heavy imports at startup: `torch`, `faster_whisper`, `whisperx`, `mediapipe`, `cv2`, `ultralytics`, `scenedetect`, `librosa` must NEVER be imported in `app/` during startup or API initialization.
- Single-port production serving: FastAPI serves `frontend/dist` statically on port `8000` when built.
- Desktop mode: `--desktop` flag runs `pywebview` with native OS webview (no Electron).
- Settings & Diagnostics completeness: GPU/VRAM live metrics, FFmpeg/NVENC detection, Ollama API query, `yt-dlp` + JS runtime checks, Hardware presets (Lite, Balanced, Pro, Custom), Cookies/PO-token settings, one-click `yt-dlp` updater, and Temp Cache Cleaner.

## Review Focus

1. **Lazy imports verification:** Ensure neither `main.py` nor any router/service imports heavy AI/CV packages into `sys.modules`.
2. **Missing external tools resilience:** If `nvidia-smi`, `ollama`, or `ffmpeg` is missing or fails, diagnostics must return structured status objects (`not_detected` / `disconnected` / `error`) without crashing the API.
3. **Single-port SPA fallback:** When accessing client-side routes (or reloading), FastAPI static file handler must fallback gracefully to `index.html`.
4. **Cache Cleaner safety:** Cleaner must only wipe designated temporary cache subdirectories (e.g. `workspace_cache/temp/`), never user files or source code.
5. **Desktop window shutdown:** Closing the `pywebview` window must cleanly terminate the background Uvicorn server.

---

## Proposed Folder Structure

```
d:\clipping\my app\
├── backend/
│   ├── requirements.txt
│   ├── run.py                          # Unified launcher (FastAPI server + optional --desktop)
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py                     # App factory, lifespan, CORS, static dist mount
│   │   ├── core/
│   │   │   ├── __init__.py
│   │   │   ├── config.py               # Pydantic BaseSettings
│   │   │   ├── db.py                   # Async engine, sessionmaker, Base, init_db
│   │   │   ├── errors.py               # Domain exceptions & Problem Details handlers
│   │   │   └── schemas.py              # APISchema base (camelCase)
│   │   ├── diagnostics/
│   │   │   ├── __init__.py
│   │   │   ├── schemas.py              # GPU, FFmpeg, Ollama, YtDlp schemas
│   │   │   ├── service.py              # Async checks for system binaries & APIs
│   │   │   └── router.py               # GET /api/diagnostics, POST /api/diagnostics/update-ytdlp
│   │   ├── settings/
│   │   │   ├── __init__.py
│   │   │   ├── models.py               # AppSettings ORM model
│   │   │   ├── schemas.py              # SettingsRead, SettingsUpdate, CacheStats
│   │   │   ├── service.py              # Settings CRUD, preset configs, cache cleaner
│   │   │   └── router.py               # GET/PUT /api/settings, GET/POST /api/cache
│   │   └── desktop/
│   │       ├── __init__.py
│   │       └── launcher.py             # pywebview desktop window runner
├── frontend/
│   ├── package.json
│   ├── vite.config.ts
│   ├── tsconfig.json
│   ├── tsconfig.node.json
│   ├── index.html
│   ├── tailwind.config.js
│   ├── postcss.config.js
│   └── src/
│       ├── main.tsx
│       ├── App.tsx
│       ├── index.css
│       ├── api/
│       │   └── client.ts               # Typed API client
│       ├── types/
│       │   └── diagnostics.ts          # TypeScript interfaces matching backend
│       ├── components/
│       │   ├── Layout.tsx              # Workstation app frame & navigation
│       │   ├── Header.tsx              # Top bar with hardware badge & quick stats
│       │   ├── MetricCard.tsx          # Telemetry display cards
│       │   └── StatusIndicator.tsx     # Health pills
│       └── pages/
│           ├── DiagnosticsPage.tsx     # Full diagnostics, presets & settings
│           └── StudioPlaceholder.tsx   # Phase 2 preview
└── tests/
    ├── test_startup_imports.py         # Confirms zero heavy imports at startup
    ├── test_diagnostics.py             # Diagnostics endpoint validation
    └── test_settings.py                # Settings and Cache endpoints validation
```

---

## Tasks

### Task 1: Backend Foundation, Core Config, Database & Lazy Startup
- **Files:**
  - Create: `backend/requirements.txt`
  - Create: `backend/app/core/config.py`
  - Create: `backend/app/core/db.py`
  - Create: `backend/app/core/errors.py`
  - Create: `backend/app/core/schemas.py`
  - Create: `backend/app/main.py`
  - Create: `tests/test_startup_imports.py`
- [ ] Create `requirements.txt` with FastAPI, Uvicorn, SQLAlchemy, aiosqlite, pydantic-settings, httpx, pywebview, psutil.
- [ ] Build `config.py` using `pydantic-settings` to manage host, port, cache directories, and defaults.
- [ ] Build `db.py` with SQLAlchemy async sessionmaker and database initialization on lifespan startup.
- [ ] Build `schemas.py` with `APISchema` providing automatic `camelCase` serialization.
- [ ] Build `main.py` with lifespan context, domain error handlers, and router placeholders.
- [ ] Write `tests/test_startup_imports.py` verifying that initializing `app` does not load `torch`, `faster_whisper`, `mediapipe`, `cv2`, `librosa`, or `ultralytics`.

### Task 2: Diagnostics & System Telemetry Service
- **Files:**
  - Create: `backend/app/diagnostics/schemas.py`
  - Create: `backend/app/diagnostics/service.py`
  - Create: `backend/app/diagnostics/router.py`
  - Create: `tests/test_diagnostics.py`
- [ ] Define schemas for GPU telemetry (name, VRAM total/free/used, driver, CUDA, utilization), FFmpeg (version, libx264, h264_nvenc, hevc_nvenc), Ollama (reachable, models list, active status), and yt-dlp (version, JS runtime detected: Deno/Node).
- [ ] Implement `DiagnosticsService.check_all()` running concurrent async subprocesses/HTTP requests.
- [ ] Implement `DiagnosticsService.update_ytdlp()` running `pip install -U "yt-dlp[default]"`.
- [ ] Build router endpoints: `GET /api/diagnostics` and `POST /api/diagnostics/update-ytdlp`.
- [ ] Write `tests/test_diagnostics.py` to assert correct responses and non-crashing fallbacks when tools are missing.

### Task 3: Settings Model, Hardware Presets & Cache Cleaner Service
- **Files:**
  - Create: `backend/app/settings/models.py`
  - Create: `backend/app/settings/schemas.py`
  - Create: `backend/app/settings/service.py`
  - Create: `backend/app/settings/router.py`
  - Create: `tests/test_settings.py`
- [ ] Create `AppSettings` database model in `models.py` for hardware preset, whisper model, ollama model, JS runtime preference, cookies browser/path, and PO-token.
- [ ] Define schemas in `schemas.py` for read/update operations and cache statistics.
- [ ] Implement `SettingsService` for fetching/updating settings, applying preset presets (Lite, Balanced, Pro, Custom), and cache calculation/cleaning in `workspace_cache/`.
- [ ] Create endpoints: `GET /api/settings`, `PUT /api/settings`, `GET /api/cache/stats`, and `POST /api/cache/clean`.
- [ ] Write `tests/test_settings.py` verifying preset changes and cache calculation/cleaning.

### Task 4: Frontend Workstation Shell, Diagnostics & Settings UI
- **Files:**
  - Create: `frontend/package.json`
  - Create: `frontend/vite.config.ts`
  - Create: `frontend/tsconfig.json`
  - Create: `frontend/tsconfig.node.json`
  - Create: `frontend/index.html`
  - Create: `frontend/tailwind.config.js`
  - Create: `frontend/postcss.config.js`
  - Create: `frontend/src/index.css`
  - Create: `frontend/src/types/diagnostics.ts`
  - Create: `frontend/src/api/client.ts`
  - Create: `frontend/src/components/Layout.tsx`
  - Create: `frontend/src/components/Header.tsx`
  - Create: `frontend/src/components/MetricCard.tsx`
  - Create: `frontend/src/components/StatusIndicator.tsx`
  - Create: `frontend/src/pages/DiagnosticsPage.tsx`
  - Create: `frontend/src/pages/StudioPlaceholder.tsx`
  - Create: `frontend/src/App.tsx`
  - Create: `frontend/src/main.tsx`
- [ ] Scaffold Vite + React + TypeScript + Tailwind setup.
- [ ] Implement typed API client (`client.ts`) communicating with `/api` endpoints.
- [ ] Build modern dark workstation theme (`Layout.tsx`, `Header.tsx`, `MetricCard.tsx`).
- [ ] Build `DiagnosticsPage.tsx` with:
  - Live GPU/VRAM cards (VRAM bar, temperature, driver)
  - FFmpeg & NVENC capability badges
  - Ollama connectivity indicator & model tags dropdown
  - `yt-dlp` version with one-click "Update yt-dlp" button + JS runtime detection indicator (Deno/Node)
  - Hardware Preset selector (Lite, Balanced, Pro, Custom) with automated recommendations
  - Cookies and PO-token configuration inputs
  - Temp Cache Cleaner card displaying cached MB and "Clean Cache" action button
- [ ] Build frontend bundle with `npm run build` producing `frontend/dist`.

### Task 5: Static Single-Port Serving, Desktop Window (`pywebview`) & CLI Launcher
- **Files:**
  - Create: `backend/app/desktop/launcher.py`
  - Create: `backend/run.py`
  - Modify: `backend/app/main.py`
- [ ] Update `main.py` to serve static files from `frontend/dist` with SPA fallback to `index.html`.
- [ ] Implement `launcher.py` with `pywebview` opening `http://127.0.0.1:8000` with native OS window.
- [ ] Build `run.py` supporting flags: `--port`, `--host`, `--reload`, and `--desktop`.
- [ ] Verify execution end-to-end: running `python backend/run.py` serves backend + frontend on `http://127.0.0.1:8000`.

### Task 6: Verification & Hand-off Instructions
- [ ] Run test suite (`pytest`) to verify all diagnostics, settings, and zero-lazy-import tests pass.
- [ ] Verify FastAPI single-port serving serves the built React app.
- [ ] Document exact installation and run commands for the user.
