# ClipForge Phase 6 — Workspace State, Export Fidelity & AI Clip Discovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix three connected bug clusters — global workspace state resets on tab switch, layout/caption settings not wired end-to-end into FFmpeg export, and a hardcoded 10-clip cap with no AI-auto mode.

**Architecture:** Lift shared project/clip/layout/caption state into a React Context wrapping App, persist layoutConfig+captionConfig per project in backend SQLite via PATCH endpoints, fix the FFmpeg/ASS pipeline to never silently fall back to defaults, add logging of resolved config at export time, add an Auto clip-count mode that returns the full AI-ranked list, and add score-filter + quick-select UI.

**Tech Stack:** React 18 + TypeScript, FastAPI + SQLAlchemy async + SQLite, FFmpeg filter_complex, ASS subtitle format, Ollama HTTP API.

## Global Constraints

- Do NOT change `.venv` package versions or add new Python packages.
- Do NOT break any existing endpoint, export, caption, or framing behaviour.
- Do NOT rename existing Python models/schemas fields — only ADD new fields (optional with defaults).
- TypeScript must compile with zero errors (`pnpm run build`).
- Backend runs with `uvicorn` from `.venv`; no new pypi deps.
- All file paths relative to `D:\New folder\clipforge-phase-6\`.

## Review Focus

1. **Context re-render storms** — `WorkspaceContext` holds many fields; child components that consume only `activeProjectId` must not re-render when `captionConfig` changes. Use separate context slices or `useMemo`/`useCallback` guards.
2. **Backend PATCH race** — if the user changes layout rapidly, concurrent PATCHes could overwrite each other. The PATCH handler should use SQLAlchemy's row-level update and return 200 immediately; debounce on the frontend.
3. **Windows path escaping in ASS filter** — `D:\path` must become `D\:/path` in the FFmpeg `-filter_complex` `ass=` argument. The existing code in `ffmpeg_builder.py` does this; verify it's also done in `exports/service.py`'s inline call path and that captions are actually burned when `captionConfig` is set.
4. **Auto clip count with no transcript** — if Ollama returns 0 clips (network down), the AI-auto mode must still return an empty list gracefully, not crash the router.
5. **Score filter slider with 0 clips passing** — if the min-score slider is set so high that no clips pass, the Export button must be disabled with a helpful message, not silently queue an empty batch.

---

## Task 1 — WorkspaceContext: Shared Project & Clip State

**Files:**
- Create: `frontend/src/context/WorkspaceContext.tsx`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/pages/StudioWorkbench.tsx` (consume context for activeProjectId)
- Modify: `frontend/src/pages/LayoutStudio.tsx` (consume context for activeProjectId)
- Modify: `frontend/src/pages/CaptionStudio.tsx` (consume context for activeProjectId)
- Modify: `frontend/src/pages/ExportWorkbench.tsx` (consume context for activeProjectId)

**Interfaces:**
- Produces:
  ```ts
  interface WorkspaceState {
    activeProjectId: string;
    setActiveProjectId: (id: string) => void;
    selectedClipId: string;
    setSelectedClipId: (id: string) => void;
  }
  export const WorkspaceContext: React.Context<WorkspaceState>
  export const WorkspaceProvider: React.FC<{ children: React.ReactNode }>
  export function useWorkspace(): WorkspaceState
  ```

- [ ] **Step 1: Create `frontend/src/context/WorkspaceContext.tsx`**

  ```tsx
  import React, { createContext, useContext, useEffect, useState } from 'react';

  interface WorkspaceState {
    activeProjectId: string;
    setActiveProjectId: (id: string) => void;
    selectedClipId: string;
    setSelectedClipId: (id: string) => void;
  }

  const WorkspaceContext = createContext<WorkspaceState>({
    activeProjectId: '',
    setActiveProjectId: () => {},
    selectedClipId: '',
    setSelectedClipId: () => {},
  });

  const LS_KEY = 'cf_active_project_id';

  export const WorkspaceProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
    const [activeProjectId, setActiveProjectIdState] = useState<string>(
      () => localStorage.getItem(LS_KEY) ?? ''
    );
    const [selectedClipId, setSelectedClipId] = useState('');

    const setActiveProjectId = (id: string) => {
      setActiveProjectIdState(id);
      if (id) localStorage.setItem(LS_KEY, id);
      else localStorage.removeItem(LS_KEY);
    };

    return (
      <WorkspaceContext.Provider value={{ activeProjectId, setActiveProjectId, selectedClipId, setSelectedClipId }}>
        {children}
      </WorkspaceContext.Provider>
    );
  };

  export function useWorkspace(): WorkspaceState {
    return useContext(WorkspaceContext);
  }
  ```

- [ ] **Step 2: Wrap the router in `App.tsx` with `<WorkspaceProvider>`**

  In `App.tsx`, import `WorkspaceProvider` and wrap the entire `<div className="min-h-screen ...">` return value:
  ```tsx
  return (
    <WorkspaceProvider>
      <div className="min-h-screen ...">
        ...
      </div>
    </WorkspaceProvider>
  );
  ```

- [ ] **Step 3: Wire `StudioWorkbench` to consume and set `activeProjectId` from context**

  - Import `useWorkspace` from `'../context/WorkspaceContext'`.
  - Replace the local `const [activeProject, setActiveProject] = useState<ProjectRead | null>(null)` with both local state AND context sync:
    - Keep local `activeProject` state (holds the full `ProjectRead` object).
    - After every `setActiveProject(p)`, call `setActiveProjectId(p.id)`.
    - On mount, if `activeProjectId` from context is non-empty and no `activeProject` is loaded yet, fetch it: `api.getProject(activeProjectId).then(setActiveProject)`.
  - In `loadProjects`: change `if (list.length > 0 && !activeProject)` to prefer `activeProjectId` from context first:
    ```ts
    const preferredId = activeProjectId || list[0]?.id;
    if (preferredId && !activeProject) {
      const full = await api.getProject(preferredId);
      setActiveProject(full);
      setActiveProjectId(full.id);
    }
    ```

- [ ] **Step 4: Wire `LayoutStudio`, `CaptionStudio`, `ExportWorkbench` to read `activeProjectId` from context**

  In each page component:
  - Import `useWorkspace`.
  - On mount `useEffect`, if `activeProjectId` from context is non-empty, pre-select that project (call `selectProject(activeProjectId)` / `setProjectId(activeProjectId)`) instead of defaulting to the first list item.
  - When user changes the project dropdown in a page, call `setActiveProjectId(newId)` from context as well.

- [ ] **Step 5: Verify TypeScript compiles with zero errors**

  Run: `cd "d:\New folder\clipforge-phase-6\frontend" && pnpm run build`
  Expected: exit code 0, zero TypeScript errors.

- [ ] **Step 6: Commit**

  ```bash
  git add frontend/src/context/WorkspaceContext.tsx frontend/src/App.tsx frontend/src/pages/StudioWorkbench.tsx frontend/src/pages/LayoutStudio.tsx frontend/src/pages/CaptionStudio.tsx frontend/src/pages/ExportWorkbench.tsx
  git commit -m "feat: lift activeProjectId into WorkspaceContext with localStorage persistence"
  ```

---

## Task 2 — Backend: Per-Project Layout & Caption Config Storage

**Files:**
- Create: `backend/app/workspace/models.py`
- Create: `backend/app/workspace/schemas.py`
- Create: `backend/app/workspace/router.py`
- Modify: `backend/app/main.py` (register router)
- Modify: `backend/app/core/db.py` (add table creation for workspace_config)

**Interfaces:**
- Produces:
  ```
  GET  /api/projects/{project_id}/workspace  → WorkspaceConfigRead
  PATCH /api/projects/{project_id}/workspace → WorkspaceConfigRead
  ```
  ```python
  class WorkspaceConfigRead(APISchema):
      project_id: str
      layout_config: dict  # serialized FramingConfig-compatible JSON
      caption_config: dict  # serialized CaptionConfig-compatible JSON
      updated_at: str
  ```

- [ ] **Step 1: Create `backend/app/workspace/models.py`**

  SQLAlchemy model for a `workspace_config` table, one row per project:
  ```python
  from sqlalchemy import Column, String, Text, DateTime
  from sqlalchemy.sql import func
  from app.core.db import Base

  class WorkspaceConfig(Base):
      __tablename__ = "workspace_config"
      project_id = Column(String, primary_key=True)
      layout_config_json = Column(Text, default="{}")
      caption_config_json = Column(Text, default="{}")
      updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
  ```

- [ ] **Step 2: Create `backend/app/workspace/schemas.py`**

  ```python
  from app.core.schemas import APISchema

  class WorkspaceConfigRead(APISchema):
      project_id: str
      layout_config: dict = {}
      caption_config: dict = {}
      updated_at: str = ""

  class WorkspaceConfigPatch(APISchema):
      layout_config: dict | None = None
      caption_config: dict | None = None
  ```

- [ ] **Step 3: Create `backend/app/workspace/router.py`**

  ```python
  import json
  from datetime import datetime, timezone
  from fastapi import APIRouter, Depends
  from sqlalchemy.ext.asyncio import AsyncSession
  from sqlalchemy import select
  from app.core.db import get_db_session
  from app.workspace.models import WorkspaceConfig
  from app.workspace.schemas import WorkspaceConfigRead, WorkspaceConfigPatch

  router = APIRouter(prefix="/api/projects", tags=["workspace"])

  @router.get("/{project_id}/workspace", response_model=WorkspaceConfigRead)
  async def get_workspace(project_id: str, session: AsyncSession = Depends(get_db_session)):
      row = await session.get(WorkspaceConfig, project_id)
      if not row:
          return WorkspaceConfigRead(project_id=project_id)
      return WorkspaceConfigRead(
          project_id=row.project_id,
          layout_config=json.loads(row.layout_config_json or "{}"),
          caption_config=json.loads(row.caption_config_json or "{}"),
          updated_at=row.updated_at.isoformat() if row.updated_at else "",
      )

  @router.patch("/{project_id}/workspace", response_model=WorkspaceConfigRead)
  async def patch_workspace(project_id: str, payload: WorkspaceConfigPatch, session: AsyncSession = Depends(get_db_session)):
      row = await session.get(WorkspaceConfig, project_id)
      if not row:
          row = WorkspaceConfig(project_id=project_id)
          session.add(row)
      if payload.layout_config is not None:
          row.layout_config_json = json.dumps(payload.layout_config)
      if payload.caption_config is not None:
          row.caption_config_json = json.dumps(payload.caption_config)
      row.updated_at = datetime.now(timezone.utc)
      await session.commit()
      await session.refresh(row)
      return WorkspaceConfigRead(
          project_id=row.project_id,
          layout_config=json.loads(row.layout_config_json or "{}"),
          caption_config=json.loads(row.caption_config_json or "{}"),
          updated_at=row.updated_at.isoformat(),
      )
  ```

- [ ] **Step 4: Register the workspace table in `backend/app/core/db.py`**

  Import `WorkspaceConfig` model and ensure `Base.metadata.create_all` runs at startup (it already does via `async_engine`; just adding the import ensures the table is registered):
  ```python
  from app.workspace.models import WorkspaceConfig  # noqa: F401 — registers table
  ```

- [ ] **Step 5: Register router in `backend/app/main.py`**

  ```python
  from app.workspace.router import router as workspace_router
  app.include_router(workspace_router)
  ```

- [ ] **Step 6: Add API client methods in `frontend/src/api/client.ts`**

  ```ts
  async getWorkspaceConfig(projectId: string): Promise<{ layoutConfig: Record<string, unknown>; captionConfig: Record<string, unknown> }> {
    const res = await fetch(`${BASE_URL}/api/projects/${projectId}/workspace`);
    return handleResponse(res);
  },
  async patchWorkspaceConfig(projectId: string, payload: { layoutConfig?: Record<string, unknown>; captionConfig?: Record<string, unknown> }): Promise<void> {
    await fetch(`${BASE_URL}/api/projects/${projectId}/workspace`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
  },
  ```

- [ ] **Step 7: Wire `LayoutStudio` to load/save layoutConfig from backend on project select**

  - After `selectProject(id)` resolves, call `api.getWorkspaceConfig(id)` and if `layoutConfig` is non-empty, merge its fields into local state: `setFramingMode`, `setAspectRatio`, `setLayoutTemplate`, `setSplitRatio`, `setFacecamBox`, `setGameplayBox`, `setWatermarkOpacity`, `setWatermarkScale`, `setWatermarkCorner`.
  - After any of those setters is called by user interaction, debounce 800 ms then call `api.patchWorkspaceConfig(projectId, { layoutConfig: { framingMode, aspectRatio, layoutTemplate, splitRatio, facecamBox, gameplayBox, watermarkOpacity, watermarkScale, watermarkCorner, watermarkPath } })`.

- [ ] **Step 8: Wire `CaptionStudio` to load/save captionConfig from backend on project select**

  - After `selectProject(id)` resolves, call `api.getWorkspaceConfig(id)` and if `captionConfig` is non-empty, call `setConfig(savedConfig as CaptionConfig)`.
  - Debounce 800 ms after `updateConfig` changes, then call `api.patchWorkspaceConfig(projectId, { captionConfig: config })`.

- [ ] **Step 9: Wire `ExportWorkbench` to load workspace config on project select**

  - After `projectId` changes and project loads, call `api.getWorkspaceConfig(projectId)`. Merge `layoutConfig` → `options.framingConfig` and `captionConfig` → `options.captionConfig`, but only fields that are non-empty/non-default to avoid overwriting the UI state with blanks.

- [ ] **Step 10: Verify backend starts and table is created**

  Run: `cd "d:\New folder\clipforge-phase-6" && .venv\Scripts\python.exe -c "import asyncio; from app.core.db import engine, Base; from app.workspace.models import WorkspaceConfig; asyncio.run(engine.run_sync(Base.metadata.create_all))"`  
  Expected: exits 0, no import errors.

- [ ] **Step 11: Verify TypeScript compiles**

  Run: `cd "d:\New folder\clipforge-phase-6\frontend" && pnpm run build`

- [ ] **Step 12: Commit**

  ```bash
  git add backend/app/workspace/ backend/app/main.py backend/app/core/db.py frontend/src/api/client.ts frontend/src/pages/LayoutStudio.tsx frontend/src/pages/CaptionStudio.tsx frontend/src/pages/ExportWorkbench.tsx
  git commit -m "feat: per-project layout+caption config persistence via SQLite workspace endpoint"
  ```

---

## Task 3 — Export Fidelity: Wire Layout, Caption & Trim Settings End-to-End

**Files:**
- Modify: `backend/app/exports/service.py`
- Modify: `backend/app/exports/media.py` (caption burn path)
- Modify: `backend/app/framing/ffmpeg_builder.py` (logging, verify caption wiring)
- Modify: `backend/app/captions/ass_generator.py` (logging)

**Interfaces:**
- Consumes: `BatchExportRequest` with `framing_config: FramingConfig`, `caption_config: CaptionConfig`, `clips: list[ExportClip]`
- Produces: FFmpeg log output + resolved config log to backend console; captions burned into output MP4 when transcript exists and `sidecars.ass` is requested or caption_config is non-default.

**Key bug:** The export pipeline in `service.py` calls `build_filter_complex(request.framing_config, ...)` correctly, BUT captions are only written as a sidecar `.ass` file — they are **never burned into the MP4**. The `.ass` filter is wired in `ffmpeg_builder.py`'s `build_filter_complex(ass_path=...)` parameter, but `service.py` never passes `ass_path` to `build_filter_complex`. Fix: generate the ASS file first, then pass its path.

Also: `ExportOptions` has `sidecars.ass` as a sidecar toggle, but captions should be BURNED into the video when the user has a caption config. Add a `burn_captions: bool` field to `ExportOptions`.

- [ ] **Step 1: Add `burn_captions` field to `ExportOptions` in `backend/app/exports/schemas.py`**

  ```python
  class ExportOptions(APISchema):
      ...
      burn_captions: bool = False   # NEW — burn ASS captions into output video
  ```

- [ ] **Step 2: Add `burnCaptions` to frontend `ExportOptions` type in `frontend/src/types/exports.ts`**

  ```ts
  export interface ExportOptions {
    ...
    burnCaptions: boolean;
  }
  ```

  Also update the default in `ExportWorkbench.tsx`: `burnCaptions: false`.

- [ ] **Step 3: Add a "Burn Captions into Video" toggle in `ExportWorkbench.tsx`**

  In the Audio polish section, after the sidecar checkboxes, add:
  ```tsx
  <label className="flex cursor-pointer items-center justify-between gap-4 rounded-lg bg-slate-900/70 px-3 py-2.5">
    <span>
      <span className="block text-sm text-slate-200">Burn captions into video</span>
      <span className="text-[11px] text-slate-500">Uses saved caption config (needs transcript)</span>
    </span>
    <input type="checkbox" checked={options.burnCaptions} onChange={() => setOptions(v => ({ ...v, burnCaptions: !v.burnCaptions }))} className="accent-cyan-400" />
  </label>
  ```

- [ ] **Step 4: Wire caption burning in `backend/app/exports/service.py`**

  In `_run_batch`, after generating the temp output path and before calling `build_filter_complex`, add:
  ```python
  # Generate ASS file if burning captions is requested and transcript is available
  ass_file_path: str | None = None
  if request.burn_captions and clip_transcript and request.caption_config:
      ass_content, _ = generate_ass(clip_transcript, request.caption_config, out_w, out_h)
      ass_tmp = output_dir / f"{out_stem}.ass_tmp"
      ass_tmp.write_text(ass_content, encoding="utf-8-sig")
      ass_file_path = str(ass_tmp)
  ```

  Then pass `ass_file_path` to `build_filter_complex`:
  ```python
  framing, out_w, out_h = build_filter_complex(
      request.framing_config, src_w, src_h, ass_path=ass_file_path,
  )
  ```

  Note: `build_filter_complex` needs to be computed AFTER `out_w`/`out_h` are known for ASS generation. Restructure so `build_filter_complex` is called first (without ass_path) to get `out_w`/`out_h`, then generate ASS, then call again with `ass_path`:
  ```python
  # First pass: get output dimensions
  _, out_w, out_h = build_filter_complex(request.framing_config, src_w, src_h)
  # Generate ASS with correct dimensions
  ass_file_path = None
  if request.burn_captions and clip_transcript and request.caption_config:
      ass_content, _ = generate_ass(clip_transcript, request.caption_config, out_w, out_h)
      ass_tmp = output_dir / f"{out_stem}_captions.ass"
      ass_tmp.write_text(ass_content, encoding="utf-8-sig")
      ass_file_path = str(ass_tmp)
  # Second pass: build full filter with captions
  framing, out_w, out_h = build_filter_complex(request.framing_config, src_w, src_h, ass_path=ass_file_path)
  ```

- [ ] **Step 5: Add startup logging to `_run_batch` in `service.py`**

  At the top of the `for index, clip in enumerate(clips):` loop, before building the command, log:
  ```python
  import logging
  logger = logging.getLogger(__name__)
  
  # At top of _run_batch, before the for loop:
  logger.info(
      "=== EXPORT JOB START === job_id=%s project_id=%s clips=%d\n"
      "  framing_config: %s\n"
      "  caption_config: %s\n"
      "  burn_captions: %s",
      job_id, job.project_id, len(clips),
      request.framing_config.model_dump(),
      request.caption_config.model_dump(),
      request.burn_captions,
  )
  ```

  Also log the full FFmpeg command before each `_run_process` call:
  ```python
  logger.info("FFmpeg command: %s", " ".join(command))
  ```

- [ ] **Step 6: Add logging to `build_filter_complex` in `ffmpeg_builder.py`**

  ```python
  import logging
  logger = logging.getLogger(__name__)
  # At end of build_filter_complex, before return:
  logger.debug("filter_complex resolved (layout=%s mode=%s aspect=%s ass=%s): %s",
               layout, mode, config.aspect_ratio, ass_path, fc[:300])
  ```

- [ ] **Step 7: Verify Windows path escaping for ASS filter**

  In `ffmpeg_builder.py` line ~276:
  ```python
  escaped_ass = str(Path(ass_path).resolve()).replace("\\", "/").replace(":", r"\:").replace("'", r"\'")
  ```
  Confirm this produces `D\:/path/to/file.ass` (not `D:/path/to/file.ass` which FFmpeg rejects on Windows). The existing code does `.replace("\\", "/").replace(":", r"\:")` which is correct order.

- [ ] **Step 8: Add "Active Export Summary" badge to `ExportWorkbench.tsx`**

  Below the page header, before the main grid, add:
  ```tsx
  {project && (
    <div className="flex items-center gap-3 rounded-xl border border-cyan-900/50 bg-cyan-950/20 px-4 py-2.5 text-xs font-mono text-cyan-300">
      <span className="font-semibold text-cyan-400">▶ Export will render:</span>
      <span>Project: <strong>{project.title}</strong></span>
      <span className="text-slate-500">·</span>
      <span>Layout: <strong>{options.framingConfig.layoutTemplate.replace('_', ' ')}</strong> ({options.framingConfig.aspectRatio})</span>
      <span className="text-slate-500">·</span>
      <span>Captions: <strong>{options.burnCaptions ? options.captionConfig.preset.replace('_', ' ') : 'off'}</strong></span>
      <span className="text-slate-500">·</span>
      <span>Clips: <strong>{selectedIds.size}</strong> selected</span>
    </div>
  )}
  ```

- [ ] **Step 9: Verify TypeScript compiles**

  Run: `cd "d:\New folder\clipforge-phase-6\frontend" && pnpm run build`
  Expected: exit code 0.

- [ ] **Step 10: Commit**

  ```bash
  git add backend/app/exports/service.py backend/app/exports/schemas.py backend/app/framing/ffmpeg_builder.py backend/app/captions/ass_generator.py frontend/src/pages/ExportWorkbench.tsx frontend/src/types/exports.ts
  git commit -m "fix: wire caption burning end-to-end, add export logging, add Active Export Summary badge"
  ```

---

## Task 4 — Auto (AI Recommended) Clip Count + Remove 10-Clip Cap

**Files:**
- Modify: `backend/app/projects/schemas.py` (DiscoverClipsRequest: raise cap to 100, add `clip_count_mode`)
- Modify: `backend/app/projects/ollama_service.py` (honour max_clips=None for auto mode, return ai_recommendation_summary)
- Modify: `backend/app/projects/service.py` (pass through new fields)
- Modify: `frontend/src/types/project.ts` (DiscoverClipsRequest + CandidateClip)
- Modify: `frontend/src/pages/StudioWorkbench.tsx` (Clip Count Mode UI)
- Modify: `frontend/src/pages/ExportWorkbench.tsx` (score filter slider + quick-select)

**Interfaces:**
- Consumes (modified `DiscoverClipsRequest`):
  ```python
  class DiscoverClipsRequest(APISchema):
      ollama_model: str | None = None
      min_duration_sec: int = Field(default=15, ge=5, le=120)
      max_duration_sec: int = Field(default=60, ge=10, le=300)
      clip_count_mode: str = Field(default="manual", pattern="^(auto|manual)$")
      max_clips: int = Field(default=5, ge=1, le=100)   # Only used when clip_count_mode == "manual"
      custom_prompt: str | None = None
  ```
- Produces (modified `ProjectRead.candidate_clips`): same `CandidateClip` list, sorted by viral_score desc.
- Produces (new field on `ProjectRead`): `ai_clip_recommendation: str | None` — e.g. `"AI recommends 24 strong clips (score >= 70) out of 38 found"`.

- [ ] **Step 1: Modify `DiscoverClipsRequest` in `backend/app/projects/schemas.py`**

  - Change `max_clips: int = Field(default=5, ge=1, le=20)` → `max_clips: int = Field(default=5, ge=1, le=100)`
  - Add `clip_count_mode: str = Field(default="manual", pattern="^(auto|manual)$")`

- [ ] **Step 2: Add `ai_clip_recommendation` to `ProjectRead` in `backend/app/projects/schemas.py`**

  ```python
  ai_clip_recommendation: str | None = None
  ```

- [ ] **Step 3: Modify `OllamaClipDiscoveryEngine.discover_clips` in `ollama_service.py`**

  - Change signature: `max_clips: int = 5` → `max_clips: int | None = None` (None = auto, no cap).
  - In the deduplication loop: replace `if len(deduped) >= max_clips: break` with:
    ```python
    if max_clips is not None and len(deduped) >= max_clips:
        break
    ```
  - Return a tuple `(deduped_clips, recommendation_summary)` where:
    ```python
    total_found = len(processed_clips)
    strong = [c for c in deduped if c.viral_score >= 70]
    if max_clips is None:
        recommendation_summary = f"AI recommends {len(strong)} strong clips (score ≥ 70) out of {total_found} found"
    else:
        recommendation_summary = None
    return deduped, recommendation_summary
    ```
  - Update the method signature's return type to `tuple[list[CandidateClip], str | None]`.

- [ ] **Step 4: Update `ProjectService.discover_clips_project` in `backend/app/projects/service.py`**

  - Pass `max_clips=None` when `payload.clip_count_mode == "auto"`, else `payload.max_clips`.
  - Store the returned `recommendation_summary` into the Project model's `ai_clip_recommendation` column (add this column to the SQLAlchemy model `backend/app/projects/models.py` with `Column(String, nullable=True)`).
  - Return the updated `ProjectRead` including the new field.

- [ ] **Step 5: Update frontend types in `frontend/src/types/project.ts`**

  - In `DiscoverClipsRequest`: add `clipCountMode?: 'auto' | 'manual'`.
  - In `ProjectRead`: add `aiClipRecommendation: string | null`.

- [ ] **Step 6: Update `StudioWorkbench.tsx` Clip Discovery UI**

  Replace the existing `maxClips` number input row with a **Clip Count Mode** toggle + conditional input:
  ```tsx
  {/* Clip Count Mode */}
  <div>
    <label className="block text-[11px] font-mono text-slate-400 mb-1">Clip Count Mode</label>
    <div className="flex gap-2 mb-2">
      <button
        onClick={() => setClipCountMode('auto')}
        className={`flex-1 px-2 py-1.5 rounded-lg border text-xs font-mono transition-all ${
          clipCountMode === 'auto'
            ? 'border-violet-500 text-violet-300 bg-violet-950'
            : 'border-border text-slate-400 hover:border-slate-500'
        }`}
      >
        🤖 Auto (AI Recommended)
      </button>
      <button
        onClick={() => setClipCountMode('manual')}
        className={`flex-1 px-2 py-1.5 rounded-lg border text-xs font-mono transition-all ${
          clipCountMode === 'manual'
            ? 'border-cyan-500 text-cyan-300 bg-cyan-950'
            : 'border-border text-slate-400 hover:border-slate-500'
        }`}
      >
        🔢 Manual Limit
      </button>
    </div>
    {clipCountMode === 'manual' && (
      <div>
        <label className="block text-[11px] font-mono text-slate-400 mb-1">Max Clips (1–100)</label>
        <input
          type="number" min={1} max={100} value={maxClips}
          onChange={(e) => setMaxClips(Math.max(1, Math.min(100, Number(e.target.value))))}
          className="w-full bg-surface border border-border rounded px-2.5 py-1.5 text-xs font-mono text-slate-200"
        />
      </div>
    )}
  </div>
  ```

  Add state: `const [clipCountMode, setClipCountMode] = useState<'auto' | 'manual'>('manual');`

  Update `handleRunOllamaDiscovery` to pass `clipCountMode` and conditionally `maxClips`:
  ```ts
  const updated = await api.discoverClips(activeProject.id, {
    ollamaModel,
    minDurationSec: minDuration,
    maxDurationSec: maxDuration,
    clipCountMode,
    ...(clipCountMode === 'manual' ? { maxClips } : {}),
    customPrompt: customPrompt.trim() || undefined,
  });
  ```

  After discovery, if `updated.aiClipRecommendation`, show it as a notice banner:
  ```tsx
  {activeProject.aiClipRecommendation && (
    <div className="p-2.5 rounded-lg bg-violet-950/50 border border-violet-700 text-xs text-violet-200 font-mono">
      🤖 {activeProject.aiClipRecommendation}
    </div>
  )}
  ```

- [ ] **Step 7: Add score filter slider + quick-select buttons to `ExportWorkbench.tsx`**

  Add state: `const [minViralScore, setMinViralScore] = useState(0);`

  Derive filtered clips: `const filteredClips = clips.filter(c => c.viralScore >= minViralScore);`

  Above the clip list, add:
  ```tsx
  <div className="space-y-2 pb-2 border-b border-slate-800">
    <div className="flex items-center justify-between">
      <label className="text-[11px] font-mono uppercase tracking-wider text-slate-500">
        Min Viral Score Filter: <span className="text-cyan-300">{minViralScore}+</span>
      </label>
      <div className="flex gap-1.5">
        <button onClick={() => setSelectedIds(new Set(filteredClips.map(c => c.id)))}
          className="px-2 py-1 rounded text-[10px] font-mono border border-slate-700 text-slate-300 hover:border-cyan-700">
          Select Filtered
        </button>
        <button onClick={() => setSelectedIds(new Set(clips.filter(c => c.viralScore >= 70).map(c => c.id)))}
          className="px-2 py-1 rounded text-[10px] font-mono border border-violet-800 text-violet-300 hover:border-violet-600">
          AI Recommended (≥70)
        </button>
        <button onClick={() => setSelectedIds(new Set())}
          className="px-2 py-1 rounded text-[10px] font-mono border border-slate-700 text-slate-400 hover:border-slate-500">
          Clear
        </button>
      </div>
    </div>
    <input type="range" min={0} max={100} step={5} value={minViralScore}
      onChange={e => setMinViralScore(Number(e.target.value))}
      className="w-full accent-violet-500" />
    {filteredClips.length === 0 && minViralScore > 0 && (
      <p className="text-[11px] text-amber-400 font-mono">
        No clips meet score ≥ {minViralScore}. Lower the filter or run discovery again.
      </p>
    )}
  </div>
  ```

  Replace `clips.map(...)` in the clip list with `filteredClips.map(...)`.

  Update the Export button to also check `filteredClips.length`:
  ```tsx
  disabled={!selectedIds.size || isQueueing || activeJobs.length > 0}
  ```
  (unchanged, since `selectedIds` already tracks what's checked.)

- [ ] **Step 8: Update `DiscoverClipsRequest` type in `frontend/src/types/project.ts`**

  ```ts
  export interface DiscoverClipsRequest {
    ollamaModel?: string;
    minDurationSec?: number;
    maxDurationSec?: number;
    clipCountMode?: 'auto' | 'manual';
    maxClips?: number;
    customPrompt?: string;
  }
  ```

- [ ] **Step 9: Verify TypeScript compiles with zero errors**

  Run: `cd "d:\New folder\clipforge-phase-6\frontend" && pnpm run build`
  Expected: exit code 0.

- [ ] **Step 10: Commit**

  ```bash
  git add backend/app/projects/schemas.py backend/app/projects/ollama_service.py backend/app/projects/service.py backend/app/projects/models.py frontend/src/types/project.ts frontend/src/pages/StudioWorkbench.tsx frontend/src/pages/ExportWorkbench.tsx
  git commit -m "feat: auto AI clip count mode, remove 10-clip cap, add score filter + quick-select UI"
  ```

---

## Task 5 — Final Verification

- [ ] **Step 1: Full TypeScript build**

  Run: `cd "d:\New folder\clipforge-phase-6\frontend" && pnpm run build`
  Expected: exit code 0, zero errors.

- [ ] **Step 2: Backend import smoke test**

  Run: `cd "d:\New folder\clipforge-phase-6" && .venv\Scripts\python.exe -c "from app.main import app; print('OK')"`
  Expected: prints `OK`.

- [ ] **Step 3: List all modified files**

  Run: `git diff --name-only HEAD~5..HEAD`
  Expected list (verify all 20+ modified/created files are present):
  - `frontend/src/context/WorkspaceContext.tsx` (new)
  - `frontend/src/App.tsx`
  - `frontend/src/pages/StudioWorkbench.tsx`
  - `frontend/src/pages/LayoutStudio.tsx`
  - `frontend/src/pages/CaptionStudio.tsx`
  - `frontend/src/pages/ExportWorkbench.tsx`
  - `frontend/src/api/client.ts`
  - `frontend/src/types/project.ts`
  - `frontend/src/types/exports.ts`
  - `backend/app/workspace/models.py` (new)
  - `backend/app/workspace/schemas.py` (new)
  - `backend/app/workspace/router.py` (new)
  - `backend/app/workspace/__init__.py` (new, empty)
  - `backend/app/main.py`
  - `backend/app/core/db.py`
  - `backend/app/exports/schemas.py`
  - `backend/app/exports/service.py`
  - `backend/app/framing/ffmpeg_builder.py`
  - `backend/app/captions/ass_generator.py`
  - `backend/app/projects/schemas.py`
  - `backend/app/projects/ollama_service.py`
  - `backend/app/projects/service.py`
  - `backend/app/projects/models.py`

- [ ] **Step 4: Commit final verification**

  ```bash
  git commit --allow-empty -m "chore: verified zero-error build for workspace state + export fidelity + AI clips"
  ```
