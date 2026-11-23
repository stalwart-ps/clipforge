# Phase 5 handoff

Phase 5 adds word-level caption styling, preview, transcript corrections, and FFmpeg subtitle burn-in.

## Implemented

- Five caption presets: Hormozi Pop, Karaoke Highlight, Minimal Clean, Gaming Neon, and Boxed Pill.
- Caption customizer for system/local font selection, font size, text and highlight colors, outline color and width, shadow, vertical `MarginV`, words per line, ALL CAPS, animation, and profanity masking.
- Live HTML5 Canvas preview over the selected project's video. Slider and color changes are debounced; the word list is virtualized and isolated from style-control rerenders.
- Virtualized inline editor for each word and its start/end times. Edits persist in the transcript JSON in SQLite and regenerate the project's `.ass` file in the same request. Whisper is not rerun.
- ASS generation, file download, and captioned MP4 rendering through FFmpeg's `ass` filter. Renders use the existing NVENC-to-libx264 fallback.

## Key files

- `backend/app/captions/ass_generator.py` — preset resolution and word-timed ASS generation.
- `backend/app/captions/router.py` — font listing, ASS generation/download, transcript update, and caption render endpoints.
- `backend/app/captions/service.py` — project caption-file and style-config persistence.
- `backend/app/framing/ffmpeg_builder.py` — optional ASS filter integration in the render graph.
- `frontend/src/pages/CaptionStudio.tsx` — Caption Studio, Canvas preview, style controls, and virtualized transcript editor.
- `backend/app/projects/service.py` — saves word edits in SQLite and updates segment text from the edited words.

## API behavior

- `GET /api/captions/fonts` lists local font-file names.
- `POST /api/projects/{id}/captions/generate` creates `workspace_cache/projects/{id}/captions/captions.ass`.
- `GET /api/projects/{id}/captions/ass` downloads the generated subtitle file.
- `PUT /api/projects/{id}/captions/transcript` saves transcript edits and refreshes ASS using the submitted style.
- `POST /api/projects/{id}/captions/render` burns ASS captions into an MP4.
- The existing `PUT /api/projects/{id}/transcript` endpoint also refreshes ASS with the last saved style (or the default preset).

## Verification

- `npm run build` in `frontend/` passed.
- `python -m compileall -q app workers` and `git diff --check` passed.
- Backend runtime/API and FFmpeg render checks were not run because `pydantic` is not installed in the current Python environment.
