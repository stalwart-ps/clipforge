You are a senior full-stack, media-engineering, and computer-vision software architect. Help me build **ClipForge Local**, a fast, lightweight, 100% local AI video clipping application that turns long-form videos and livestreams into short-form vertical/square/landscape clips using Ollama, Faster-Whisper/WhisperX, MediaPipe/YOLOv8, PySceneDetect, and FFmpeg.

---

### 1. Tech Stack & Runtime Requirements
- **Runtime:** Python 3.11+, FFmpeg/FFprobe on PATH, and a JS runtime for `yt-dlp` YouTube extraction (Deno 2.3+ recommended, or Node.js 22+ explicitly enabled via `js_runtimes`).
- **Backend:** FastAPI, Uvicorn, SQLite (`SQLAlchemy` / `aiosqlite`), Pydantic, WebSockets (real-time job progress and logs).
- **Frontend:** React + Vite + TypeScript + Tailwind CSS + HTML5 Canvas (interactive crop-region editor, platform safe-zone guides, and live caption preview).
- **Optional Native Desktop Window:** Support a `--desktop` launcher flag using `pywebview` (uses the OS native WebView — NEVER use Electron). In normal/production mode, FastAPI serves the compiled `frontend/dist` static bundle on a single port (`localhost:8000`) with zero Node.js server running in the background.
- **Core Media & AI Libraries:**
  - `yt-dlp[default]` (includes `yt-dlp-ejs` for YouTube signature solving) + optional `TwitchDownloaderCLI` integration for Twitch VOD chat replays.
  - `faster-whisper` (default, using `BatchedInferencePipeline`, `vad_filter=True`, `word_timestamps=True`, `hotwords`, and `initial_prompt`) + optional `whisperx` (forced alignment + speaker diarization).
  - Local **Ollama** HTTP API (`http://localhost:11434`).
  - `opencv-python`, `mediapipe` (Face Detection + Face Mesh lip-activity tracking), optional `ultralytics` (YOLOv8-Face), and `scenedetect` (PySceneDetect).
  - `librosa` / `numpy` for audio loudness/hype spike detection.
  - `FFmpeg` via subprocess (`filter_complex`, `libass` for `.ass` subtitles, `h264_nvenc` with automatic `libx264` fallback).

---

### 2. Strict Performance, Lightweight Footprint & VRAM Rules
The application must stay snappy (1–2s startup, low idle RAM) and run safely on hardware ranging from CPU-only laptops to 6GB–24GB GPUs:
1. **Lazy Imports Only:** NEVER import `torch`, `faster_whisper`, `whisperx`, `mediapipe`, `cv2`, `ultralytics`, `scenedetect`, or `librosa` at top-level startup in `main.py` or API routers. Import them strictly inside dedicated worker scripts only when a job executes.
2. **Subprocess Isolation & Sequential VRAM Execution:** Run every heavy stage (Download, Transcribe, Vision Tracking, FFmpeg Render) in an isolated worker subprocess (`subprocess.Popen` / `multiprocessing`). Never load Whisper, Ollama, and YOLO simultaneously:
   - Stage 1 (STT worker exits -> OS immediately reclaims 100% RAM/VRAM).
   - Stage 2 (Ollama API call -> send `"keep_alive": 0` on the final request to immediately flush model weights from VRAM).
   - Stage 3 (Vision Tracking & FFmpeg worker exits -> OS reclaims memory).
3. **Real Job Cancellation:** Track active worker/FFmpeg process PIDs so clicking "Cancel" terminates the entire process tree cleanly instead of leaving orphaned GPU/CPU jobs running.
4. **Stage Caching & Disk Cleaner:** Cache downloaded media, extracted WAV audio, engagement signals, scene cuts, and transcripts per project in SQLite + a project workspace folder. Re-running Ollama clip scoring or editing caption styles must skip downloading and transcription. Include a storage usage readout and a **"Clean Temp Files"** button in Settings.
5. **Instant Scrubbing & Light UI:** Serve local video files using HTTP Byte-Range Requests (`206 Partial Content`) for smooth HTML5 `<video>` scrubbing. Extract single on-demand JPEG frames via FFmpeg (`-ss ... -vframes 1`) for the Layout Canvas crop picker instead of streaming raw frames over WebSockets. Debounce UI slider updates and avoid polling loops.

---

### 3. Hardware Presets & Diagnostics (Settings Panel)
Include a live startup/settings diagnostic panel checking: GPU/CUDA availability & VRAM size, FFmpeg & `h264_nvenc` support, Ollama connection & available models, `yt-dlp` version + JS runtime detection (Deno/Node).
- **Hardware Presets (with full manual overrides per component):**
  - **Lite (CPU / 4GB VRAM):** `faster-whisper` (`tiny`/`base`, INT8 CPU) | MediaPipe Face Detection (CPU) | `qwen2.5:3b` or `llama3.2:3b` | `libx264` (`veryfast`).
  - **Balanced (6–8GB VRAM):** `faster-whisper` (`small`/`distil-large-v3.5`, INT8 CUDA) | MediaPipe Face Mesh (CPU) + OpenCV | `qwen2.5:7b` or `llama3.1:8b` | `h264_nvenc`.
  - **Pro (12GB+ VRAM):** `WhisperX` or `faster-whisper` (`large-v3-turbo`, FP16 CUDA) + Diarization | YOLOv8-Face + Active Speaker Detection | `qwen2.5:14b` / `gemma3:12b` | `h264_nvenc` / `hevc_nvenc`.
- **`yt-dlp` Maintenance Settings:**
  - Optional browser cookies (`cookiesfrombrowser` or cookies file path) and PO-token provider configuration to avoid YouTube bot-check blocks.
  - Selectable JS runtime (`deno` default, or `node` passed explicitly via `js_runtimes`).
  - One-click **"Update yt-dlp"** button inside Settings (`pip install -U "yt-dlp[default]"`).

---

### 4. End-to-End Pipeline & Feature Specifications

#### A. Dual Video Input & Engagement Mining
1. **Link Input (YouTube, Twitch, Kick, etc. via `yt-dlp`):**
   - **Full Download Mode:** Download best video + audio cleanly (always end `outtmpl` with `.%(ext)s`).
   - **Fast VOD Mode:** Download audio + metadata first to find top clips, then fetch only the approved high-res clip ranges (with padding) using `yt-dlp --download-sections`.
   - **Engagement Signal Extraction:**
     - **YouTube Heatmap:** Parse `info_dict.get("heatmap")` ("Most Replayed") retention peaks when available.
     - **Comments:** Scrape top comments (`getcomments: True`) and parse regex timestamps (`MM:SS` / `HH:MM:SS`) weighted by likes and hype keywords ("lmao", "insane", "best part", "clip this").
     - **Livestream Chat Replays:** Parse YouTube `live_chat` replay JSON for messages-per-second velocity spikes; include an optional hook for `TwitchDownloaderCLI` if the user configures its binary path for Twitch VOD chat.
2. **Local File Input:**
   - Drag-and-drop or file picker for `.mp4`, `.mkv`, `.mov`, `.webm`.
3. **Universal Audio Hype Detector (Both Link & Local):**
   - Extract RMS loudness and pitch/energy spikes via `librosa`/`numpy` to detect screams, laughter, and clutch reactions even when no comments or heatmaps exist.

#### B. Local Transcription Module
- Extract 16kHz mono WAV via FFmpeg.
- Support `faster-whisper` (`BatchedInferencePipeline` with Silero VAD enabled) and optional `WhisperX`.
- Expose **Language Selector** (Auto or specific language), **Multilingual code-switching toggle**, **Translate to English toggle**, and a **Custom Vocabulary / Terms box** (passed to Whisper's `hotwords` / `initial_prompt` for accurate streamer names, game terminology, and mixed-language slang).
- Save **word-level timestamps** (`[{word, start, end, confidence}]`) to SQLite so users can edit transcript typos later without re-transcribing.

#### C. Ollama Clip Discovery Engine
- Dynamically query `GET http://localhost:11434/api/tags` for installed models.
- Chunk long transcripts with overlapping windows (respecting configurable context length) and fuse each chunk with normalized engagement spikes (heatmap peaks, comment timestamps, chat velocity spikes, audio energy peaks).
- Enforce structured JSON output returning ranked candidate clips:
  `{ title, hook_summary, start_sec, end_sec, viral_score (1-100), reason, suggested_hashtags, detected_mood }`.
- Snap clip boundaries cleanly to sentence/word endpoints and detected scene-cut boundaries (`PySceneDetect`).
- User controls: target duration range (e.g., 15–60s), max clip count, and custom instructions (e.g., "prioritize funny fails" or "focus on key explanations").

#### D. Scene Cut Detection & Smart Clipping Modes
Run lightweight `PySceneDetect` on candidate clip ranges so camera transitions snap cleanly on hard cuts instead of awkwardly panning across them. Implement a modular `FramingEngine` with these modes:
1. **Gaming Mode (Auto Facecam Aware):**
   - Scans sample frames for a persistent face/webcam overlay (typically in corners/borders).
   - **Face Detected:** Applies the chosen layout (e.g., Split Vertical: Facecam on top, Gameplay on bottom).
   - **No Face Detected:** Automatically switches to Fullscreen Gameplay mode (center-crop, blurred-pillarbox fill, or smooth motion-tracked crop).
2. **Podcast / Multi-Speaker Mode (Active Speaker Detection):**
   - Detects all faces and uses MediaPipe Face Mesh (lip-opening / Mouth Aspect Ratio variance synced with audio speech segments) to track the active speaker.
   - Applies deadband + exponential smoothing to prevent jittery camera shake, resets instantly on scene cuts, and supports automatic 2-person vertical split-screen when both subjects speak rapidly or simultaneously.
3. **Talking Head / Single Creator Mode:**
   - Smooth face-centered 9:16 tracking with optional auto punch-in zoom (e.g., 1.12x) on high-energy moments.
4. **Screen + Presenter / Tutorial Mode:**
   - Keeps main screen/slide area legible (blurred fill or active-region pan) with presenter webcam as a top split or rounded Picture-in-Picture (PiP).
5. **Reaction Mode:**
   - Splits frame cleanly between reactor webcam and primary content region.

#### E. Interactive Layout Studio (Manual + AI Auto) & Profiles
- **Aspect Ratios:** `9:16` (1080x1920), `1:1` (1080x1080), `16:9` (1920x1080).
- **Layout Templates:**
  - `Split Vertical` (Top = Region A / Facecam, Bottom = Region B / Gameplay, with draggable split ratio e.g., 35/65, 40/60, 50/50).
  - `Fullscreen Dynamic Crop` (single tracked region).
  - `Blurred Background Fill` (16:9 centered over Gaussian-blurred background).
  - `Picture-in-Picture (PiP)` (main content full + corner overlay box).
- **Interactive Canvas Region Picker:**
  - Scrubbable single-frame video preview where the user can draw, drag, and resize color-coded boxes (`Streamer/Facecam Box` and `Gameplay/Content Box`).
  - **"Auto-Detect Regions"** button runs the vision detector to auto-populate boxes for manual fine-tuning.
  - **Live Side-by-Side Output Preview** with a toggleable translucent **Platform Safe-Zone Overlay** (YouTube Shorts / Reels / TikTok right-side icons & bottom description zones) so captions and HUD elements never get covered.
  - **Brand Watermark Slot:** Optional transparent PNG logo upload with corner position, scale, and opacity controls.
- **Saved Channel / Streamer Profiles:** 1-click **"Save as Profile"** storing crop coordinates, layout template/ratio, caption style, watermark, and custom Ollama prompt for instant reuse on future videos from the same creator.

#### F. Customizable Auto-Captions Engine
- Generate `.ass` (Advanced SubStation Alpha) subtitle files from word-level timestamps and burn via FFmpeg `ass=` filter.
- **5 Built-In Style Presets:**
  1. *Hormozi Pop* (bold uppercase, active word scales up & turns yellow/green, thick black outline).
  2. *Karaoke Highlight* (smooth active-word color highlight).
  3. *Minimal Clean* (sleek sans-serif, subtle drop shadow).
  4. *Gaming Neon* (high-contrast cyan/magenta glow positioned safely above gameplay HUD).
  5. *Boxed Pill* (semi-transparent rounded background behind active text).
- **Full Customizer Controls:** Font picker (scans system/local fonts), font size, primary & active-word highlight colors, outline color & thickness, shadow depth, vertical position slider (`MarginV`), max words per line (1–6), ALL CAPS toggle, animation style (None / Pop / Highlight / Bounce).
- **Inline Transcript Typo Editor:** Click any word in a clip's transcript to fix typos or timing before burning captions.
- **Profanity Masking Toggle:** Optional auto-censoring of profanity in generated captions (e.g., `f***`).

#### G. Clip Workbench, Audio Polish & Export Engine
- **Trimming & Quick Preview:** Waveform timeline handles to adjust clip start/end points, plus a **"Render 5s Preview"** button to inspect framing and caption styling before full export.
- **VFR-to-CFR Sync Protection:** Always enforce constant frame rate output during FFmpeg render (`-fps_mode cfr`) so OBS, ShadowPlay, and mobile Variable Frame Rate recordings never cause caption/audio drift.
- **Audio Loudness Normalization:** Optional FFmpeg `loudnorm` filter targeting `-14 LUFS` (standard for Shorts/Reels/TikTok).
- **Optional Silence / Dead-Air Trimmer:** Automatically jump-cut silent pauses exceeding a configurable threshold (e.g., 0.6s).
- **Batch Export & Metadata Pack:** Render single clips or batch-export all approved clips with live progress bars. Optionally save clean `.srt`/`.ass` subtitle files and `.txt`/`.json` metadata sidecars (title, hook, hashtags) alongside each rendered `.mp4`.

---

### 5. Phased Implementation Plan (Execute Strictly One Phase at a Time)
Do NOT dump the entire codebase at once. Build, verify, and test each milestone before moving to the next:

- **Phase 1 — Project Scaffold, Lazy Architecture & Hardware Diagnostics:**
  Create the folder structure, FastAPI backend (with static `frontend/dist` serving + optional `--desktop` `pywebview` launcher), SQLite schema, React+Tailwind frontend shell, Hardware/Settings page (GPU/VRAM, FFmpeg/NVENC, Ollama, `yt-dlp` + JS runtime diagnostics, presets, cookies/PO-token config, one-click `yt-dlp` updater, and Temp Cache Cleaner).
- **Phase 2 — Ingestion, Engagement Mining & HTTP Range Streaming:**
  Implement subprocess-isolated URL (`yt-dlp` Full & Fast VOD modes, heatmap, comment timestamps, YouTube live chat spikes, optional Twitch chat hook) and Local File ingestion, Audio Energy spike extractor, WebSocket progress/cancellation system, stage caching, and HTTP `206` Range video streaming.
- **Phase 3 — Transcription & Ollama Clip Scoring:**
  Implement subprocess-isolated `faster-whisper` (`BatchedInferencePipeline` + Silero VAD + `hotwords`/language options + optional `WhisperX`), word-level SQLite storage, `PySceneDetect` boundary detection, and Ollama structured clip discovery with engagement-signal fusion and `keep_alive: 0` VRAM unloading.
- **Phase 4 — Vision Framing Engine, Interactive Layout Studio & Saved Profiles:**
  Build the HTML5 Canvas drag-and-drop crop picker (using FFmpeg single-frame JPEGs), "Auto-Detect Regions" API, Platform Safe-Zone overlay, Brand Watermark controls, Saved Profiles CRUD, Gaming Mode (face vs. no-face), Podcast Mode (MediaPipe active speaker tracking with cut-aware smoothing), Talking Head/Screen/Reaction modes, and the FFmpeg `filter_complex` builder (with `-fps_mode cfr`).
- **Phase 5 — Auto-Captions Engine, Live Preview & Transcript Editor:**
  Build the `.ass` word-level generator with all 5 presets, full style customizer, live canvas caption preview, profanity masking toggle, and inline word-level transcript editor.
- **Phase 6 — Clip Workbench, Audio Polish & Batch Export Queue:**
  Build waveform trim handles, 5-second quick preview render, `-14 LUFS` loudnorm toggle, Dead-Air silence trimmer, and the cancellable batch export queue with `.srt`/`.ass`/metadata sidecar exports.

Begin now by confirming the exact folder tree and implementing **Phase 1** completely, including `requirements.txt`, `package.json`, and clear run commands.