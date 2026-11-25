import asyncio
from collections import deque
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import sys
import uuid
from fastapi import UploadFile
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db import async_session_maker
from app.core.errors import NotFoundError, ValidationError
from app.core.process_manager import ProcessManager
from app.core.ws_manager import ws_manager
from app.media.ffmpeg import FFmpegHelper
from app.projects.models import Project
from app.projects.ollama_service import OllamaClipDiscoveryEngine
from app.projects.schemas import (
    CandidateClip,
    DiscoverClipsRequest,
    EngagementPoint,
    EngagementSignals,
    IngestUrlRequest,
    ProjectRead,
    ProjectSummary,
    SceneCut,
    TranscribeRequest,
    TranscriptData,
    TranscriptSegment,
    UpdateTranscriptRequest,
)
from app.settings.service import SettingsService


class ProjectService:
    @staticmethod
    def _generate_project_id() -> str:
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        rand = uuid.uuid4().hex[:6]
        return f"proj_{ts}_{rand}"

    @classmethod
    async def create_url_project(
        cls, session: AsyncSession, payload: IngestUrlRequest
    ) -> ProjectRead:
        project_id = cls._generate_project_id()
        proj_dir = settings.cache_dir / "projects" / project_id
        proj_dir.mkdir(parents=True, exist_ok=True)

        app_settings = await SettingsService.get_or_create_settings(session)

        project = Project(
            id=project_id,
            title="Processing Video...",
            source_type="url",
            source_url=payload.url,
            download_mode=payload.download_mode,
            status="downloading",
            progress_percent=5.0,
            current_stage="Initializing yt-dlp downloader...",
        )
        session.add(project)
        await session.commit()
        await session.refresh(project)

        # Launch worker in background task
        asyncio.create_task(
            cls._run_url_ingest_worker(
                project_id=project_id,
                url=payload.url,
                download_mode=payload.download_mode,
                output_dir=proj_dir,
                cookies_browser=app_settings.cookies_browser,
                cookies_file=app_settings.cookies_file_path,
                po_token=app_settings.po_token,
                js_runtime=app_settings.js_runtime,
            )
        )

        return cls._to_read_schema(project)

    @classmethod
    async def _run_url_ingest_worker(
        cls,
        project_id: str,
        url: str,
        download_mode: str,
        output_dir: Path,
        cookies_browser: str | None,
        cookies_file: str | None,
        po_token: str | None,
        js_runtime: str | None,
    ):
        worker_script = settings.backend_dir / "workers" / "ingest_worker.py"
        cmd = [
            sys.executable,
            str(worker_script),
            "--url",
            url,
            "--project-id",
            project_id,
            "--download-mode",
            download_mode,
            "--output-dir",
            str(output_dir),
        ]

        if cookies_browser:
            cmd.extend(["--cookies-browser", cookies_browser])
        if cookies_file:
            cmd.extend(["--cookies-file", cookies_file])
        if po_token:
            cmd.extend(["--po-token", po_token])
        if js_runtime:
            cmd.extend(["--js-runtime", js_runtime])

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(settings.backend_dir / "workers"),
            )

            await ProcessManager.register_process(project_id, proc.pid)

            # Update DB with active PID
            async with async_session_maker() as session:
                q = select(Project).where(Project.id == project_id)
                res = await session.execute(q)
                p = res.scalar_one_or_none()
                if p:
                    p.active_pid = proc.pid
                    await session.commit()

            complete_data = None
            stderr_tail: deque[bytes] = deque(maxlen=200)

            async def drain_stderr():
                if proc.stderr:
                    while line := await proc.stderr.readline():
                        stderr_tail.append(line)

            stderr_task = asyncio.create_task(drain_stderr())

            # Stream stdout lines
            while True:
                line = await proc.stdout.readline()
                if not line:
                    break
                text = line.decode("utf-8", errors="ignore").strip()
                if text.startswith("PROGRESS:"):
                    try:
                        prog = json.loads(text[9:])
                        await ws_manager.broadcast(project_id, prog)

                        async with async_session_maker() as session:
                            q = select(Project).where(Project.id == project_id)
                            res = await session.execute(q)
                            p = res.scalar_one_or_none()
                            if p and p.status not in ("cancelled", "error"):
                                p.progress_percent = prog.get("percent", p.progress_percent)
                                p.current_stage = prog.get("message", p.current_stage)
                                await session.commit()
                    except Exception:
                        pass
                elif text.startswith("COMPLETE:"):
                    try:
                        complete_data = json.loads(text[9:])
                    except Exception:
                        pass

            await proc.wait()
            if not stderr_task.done():
                await stderr_task
            stderr_out = b"".join(stderr_tail)

            await ProcessManager.unregister_process(project_id)

            async with async_session_maker() as session:
                q = select(Project).where(Project.id == project_id)
                res = await session.execute(q)
                p = res.scalar_one_or_none()
                if not p or p.status == "cancelled":
                    return

                if proc.returncode == 0 and complete_data:
                    p.status = "ready"
                    p.progress_percent = 100.0
                    p.current_stage = "Ingestion Complete"
                    p.title = complete_data.get("title", p.title)
                    p.video_path = complete_data.get("video_path")
                    p.audio_path = complete_data.get("audio_path")
                    p.duration_sec = complete_data.get("duration_sec")
                    p.width = complete_data.get("width")
                    p.height = complete_data.get("height")
                    p.fps = complete_data.get("fps")
                    p.active_pid = None

                    if p.video_path and Path(p.video_path).exists():
                        thumb_file = output_dir / f"{project_id}_thumb.jpg"
                        if await FFmpegHelper.extract_thumbnail(Path(p.video_path), thumb_file, 1.0):
                            p.thumbnail_path = str(thumb_file)

                    if "signals" in complete_data:
                        p.engagement_signals_json = json.dumps(complete_data["signals"])

                    await session.commit()
                    await ws_manager.broadcast(
                        project_id,
                        {"type": "complete", "message": "Video ingestion and mining complete!"},
                    )
                else:
                    err_msg = stderr_out.decode("utf-8", errors="ignore") or "Worker terminated with non-zero exit code"
                    p.status = "error"
                    p.error_message = err_msg
                    p.active_pid = None
                    await session.commit()
                    await ws_manager.broadcast(
                        project_id,
                        {"type": "error", "error": err_msg},
                    )

        except Exception as e:
            await ProcessManager.unregister_process(project_id)
            async with async_session_maker() as session:
                q = select(Project).where(Project.id == project_id)
                res = await session.execute(q)
                p = res.scalar_one_or_none()
                if p and p.status != "cancelled":
                    p.status = "error"
                    p.error_message = str(e)
                    p.active_pid = None
                    await session.commit()
            await ws_manager.broadcast(project_id, {"type": "error", "error": str(e)})

    @classmethod
    async def create_local_project(
        cls, session: AsyncSession, file: UploadFile
    ) -> ProjectRead:
        project_id = cls._generate_project_id()
        proj_dir = settings.cache_dir / "projects" / project_id
        proj_dir.mkdir(parents=True, exist_ok=True)

        orig_filename = file.filename or "video.mp4"
        ext = Path(orig_filename).suffix.lower() or ".mp4"
        saved_video_path = proj_dir / f"{project_id}{ext}"

        with open(saved_video_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        file_size = saved_video_path.stat().st_size

        project = Project(
            id=project_id,
            title=Path(orig_filename).stem,
            source_type="local",
            source_url=None,
            download_mode="local",
            status="extracting_audio",
            progress_percent=20.0,
            current_stage="Probing video format and extracting audio...",
            video_path=str(saved_video_path),
            file_size_bytes=file_size,
        )
        session.add(project)
        await session.commit()
        await session.refresh(project)

        asyncio.create_task(
            cls._process_local_media(project_id, saved_video_path, proj_dir)
        )

        return cls._to_read_schema(project)

    @classmethod
    async def _process_local_media(cls, project_id: str, video_path: Path, output_dir: Path):
        try:
            meta = await FFmpegHelper.probe_media(video_path)
            duration = meta.get("duration_sec")
            width = meta.get("width")
            height = meta.get("height")
            fps = meta.get("fps")

            await ws_manager.broadcast(
                project_id,
                {"type": "progress", "percent": 40.0, "stage": "extracting_audio", "message": "Extracting 16kHz audio track..."},
            )

            audio_path = output_dir / f"{project_id}_16k.wav"
            extracted = await FFmpegHelper.extract_16k_mono_audio(video_path, audio_path)
            if not extracted:
                raise RuntimeError("Failed to extract audio stream via FFmpeg")

            thumb_path = output_dir / f"{project_id}_thumb.jpg"
            await FFmpegHelper.extract_thumbnail(video_path, thumb_path, min(2.0, (duration or 1.0) / 2.0))

            await ws_manager.broadcast(
                project_id,
                {"type": "progress", "percent": 75.0, "stage": "analyzing_engagement", "message": "Analyzing audio energy and hype spikes..."},
            )

            worker_script = settings.backend_dir / "workers" / "audio_energy_worker.py"
            signals_json_path = output_dir / f"{project_id}_signals.json"

            cmd = [
                sys.executable,
                str(worker_script),
                "--audio-path",
                str(audio_path),
                "--output-json",
                str(signals_json_path),
            ]

            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await ProcessManager.register_process(project_id, proc.pid)
            await proc.wait()
            await ProcessManager.unregister_process(project_id)

            audio_signals = []
            if signals_json_path.exists():
                with open(signals_json_path, "r", encoding="utf-8") as f:
                    audio_signals = json.load(f)

            signals_payload = {
                "heatmap": [],
                "comment_timestamps": [],
                "chat_velocity": [],
                "audio_energy": audio_signals,
            }

            async with async_session_maker() as session:
                q = select(Project).where(Project.id == project_id)
                res = await session.execute(q)
                p = res.scalar_one_or_none()
                if p and p.status != "cancelled":
                    p.status = "ready"
                    p.progress_percent = 100.0
                    p.current_stage = "Ready for Clipping"
                    p.duration_sec = duration
                    p.width = width
                    p.height = height
                    p.fps = fps
                    p.audio_path = str(audio_path)
                    p.thumbnail_path = str(thumb_path) if thumb_path.exists() else None
                    p.engagement_signals_json = json.dumps(signals_payload)
                    await session.commit()

            await ws_manager.broadcast(
                project_id,
                {"type": "complete", "message": "Local video ingestion and audio analysis complete!"},
            )

        except Exception as e:
            await ProcessManager.unregister_process(project_id)
            async with async_session_maker() as session:
                q = select(Project).where(Project.id == project_id)
                res = await session.execute(q)
                p = res.scalar_one_or_none()
                if p and p.status != "cancelled":
                    p.status = "error"
                    p.error_message = str(e)
                    await session.commit()
            await ws_manager.broadcast(project_id, {"type": "error", "error": str(e)})

    # ==========================================
    # Phase 3: Transcription Subprocess Worker
    # ==========================================
    @classmethod
    async def transcribe_project(
        cls, session: AsyncSession, project_id: str, payload: TranscribeRequest
    ) -> ProjectRead:
        q = select(Project).where(Project.id == project_id)
        res = await session.execute(q)
        project = res.scalar_one_or_none()
        if not project:
            raise NotFoundError(f"Project {project_id} not found")

        # Determine audio path (extract from video if missing)
        proj_dir = settings.cache_dir / "projects" / project_id
        audio_path = Path(project.audio_path) if project.audio_path else proj_dir / f"{project_id}_16k.wav"

        if not audio_path.exists():
            if not project.video_path or not Path(project.video_path).exists():
                raise ValidationError("Cannot transcribe: no media file found")
            await FFmpegHelper.extract_16k_mono_audio(Path(project.video_path), audio_path)
            project.audio_path = str(audio_path)

        app_settings = await SettingsService.get_or_create_settings(session)
        whisper_model = payload.whisper_model or app_settings.whisper_model or "base"

        project.status = "transcribing"
        project.progress_percent = 5.0
        project.current_stage = f"Starting Whisper ({whisper_model})..."
        project.whisper_model_used = whisper_model
        await session.commit()
        await session.refresh(project)

        asyncio.create_task(
            cls._run_transcribe_worker(
                project_id=project_id,
                audio_path=audio_path,
                proj_dir=proj_dir,
                whisper_model=whisper_model,
                language=payload.language,
                translate=payload.translate,
                hotwords=payload.hotwords,
                initial_prompt=payload.initial_prompt,
                use_whisperx=payload.use_whisperx,
            )
        )

        return cls._to_read_schema(project)

    @classmethod
    async def _run_transcribe_worker(
        cls,
        project_id: str,
        audio_path: Path,
        proj_dir: Path,
        whisper_model: str,
        language: str | None,
        translate: bool,
        hotwords: str | None,
        initial_prompt: str | None,
        use_whisperx: bool,
    ):
        worker_script = settings.backend_dir / "workers" / "transcribe_worker.py"
        output_json = proj_dir / f"{project_id}_transcript.json"

        cmd = [
            sys.executable,
            str(worker_script),
            "--audio-path",
            str(audio_path),
            "--output-json",
            str(output_json),
            "--model-size",
            whisper_model,
        ]

        if language:
            cmd.extend(["--language", language])
        if translate:
            cmd.append("--translate")
        if hotwords:
            cmd.extend(["--hotwords", hotwords])
        if initial_prompt:
            cmd.extend(["--initial-prompt", initial_prompt])
        if use_whisperx:
            cmd.append("--use-whisperx")

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(settings.backend_dir / "workers"),
            )
            await ProcessManager.register_process(project_id, proc.pid)

            stderr_tail: deque[bytes] = deque(maxlen=200)

            async def drain_stderr():
                if proc.stderr:
                    while line := await proc.stderr.readline():
                        stderr_tail.append(line)

            stderr_task = asyncio.create_task(drain_stderr())

            while True:
                line = await proc.stdout.readline()
                if not line:
                    break
                text = line.decode("utf-8", errors="ignore").strip()
                if text.startswith("PROGRESS:"):
                    try:
                        prog = json.loads(text[9:])
                        await ws_manager.broadcast(project_id, prog)
                        async with async_session_maker() as session:
                            q = select(Project).where(Project.id == project_id)
                            res = await session.execute(q)
                            p = res.scalar_one_or_none()
                            if p and p.status not in ("cancelled", "error"):
                                p.progress_percent = prog.get("percent", p.progress_percent)
                                p.current_stage = prog.get("message", p.current_stage)
                                await session.commit()
                    except Exception:
                        pass

            await proc.wait()
            if not stderr_task.done():
                await stderr_task
            stderr_out = b"".join(stderr_tail)
            await ProcessManager.unregister_process(project_id)

            async with async_session_maker() as session:
                q = select(Project).where(Project.id == project_id)
                res = await session.execute(q)
                p = res.scalar_one_or_none()
                if not p or p.status == "cancelled":
                    return

                if proc.returncode == 0 and output_json.exists():
                    with open(output_json, "r", encoding="utf-8") as f:
                        transcript_raw = f.read()

                    p.transcript_json = transcript_raw
                    p.status = "ready"
                    p.progress_percent = 100.0
                    p.current_stage = "Transcription Complete"
                    p.active_pid = None
                    await session.commit()

                    await ws_manager.broadcast(
                        project_id,
                        {"type": "complete", "message": "Transcription complete and saved!"},
                    )
                else:
                    err = stderr_out.decode("utf-8", errors="ignore") or "Whisper worker failed"
                    p.status = "error"
                    p.error_message = err
                    p.active_pid = None
                    await session.commit()
                    await ws_manager.broadcast(project_id, {"type": "error", "error": err})

        except Exception as e:
            await ProcessManager.unregister_process(project_id)
            async with async_session_maker() as session:
                q = select(Project).where(Project.id == project_id)
                res = await session.execute(q)
                p = res.scalar_one_or_none()
                if p and p.status != "cancelled":
                    p.status = "error"
                    p.error_message = str(e)
                    await session.commit()
            await ws_manager.broadcast(project_id, {"type": "error", "error": str(e)})

    # ==========================================
    # Phase 3: PySceneDetect Worker
    # ==========================================
    @classmethod
    async def detect_scenes_project(cls, session: AsyncSession, project_id: str) -> ProjectRead:
        q = select(Project).where(Project.id == project_id)
        res = await session.execute(q)
        project = res.scalar_one_or_none()
        if not project:
            raise NotFoundError(f"Project {project_id} not found")

        if not project.video_path or not Path(project.video_path).exists():
            raise ValidationError("No video file found for scene detection")

        proj_dir = settings.cache_dir / "projects" / project_id
        video_path = Path(project.video_path)

        project.status = "detecting_scenes"
        project.progress_percent = 10.0
        project.current_stage = "Detecting shot boundaries..."
        await session.commit()
        await session.refresh(project)

        asyncio.create_task(
            cls._run_scene_detect_worker(project_id, video_path, proj_dir)
        )
        return cls._to_read_schema(project)

    @classmethod
    async def _run_scene_detect_worker(cls, project_id: str, video_path: Path, proj_dir: Path):
        worker_script = settings.backend_dir / "workers" / "scene_detect_worker.py"
        output_json = proj_dir / f"{project_id}_scenes.json"

        cmd = [
            sys.executable,
            str(worker_script),
            "--video-path",
            str(video_path),
            "--output-json",
            str(output_json),
        ]

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await ProcessManager.register_process(project_id, proc.pid)

            stderr_tail: deque[bytes] = deque(maxlen=200)

            async def drain_stderr():
                if proc.stderr:
                    while line := await proc.stderr.readline():
                        stderr_tail.append(line)

            stderr_task = asyncio.create_task(drain_stderr())

            while True:
                line = await proc.stdout.readline()
                if not line:
                    break
                text = line.decode("utf-8", errors="ignore").strip()
                if text.startswith("PROGRESS:"):
                    try:
                        prog = json.loads(text[9:])
                        await ws_manager.broadcast(project_id, prog)
                    except Exception:
                        pass

            await proc.wait()
            if not stderr_task.done():
                await stderr_task
            await ProcessManager.unregister_process(project_id)

            async with async_session_maker() as session:
                q = select(Project).where(Project.id == project_id)
                res = await session.execute(q)
                p = res.scalar_one_or_none()
                if not p or p.status == "cancelled":
                    return

                if proc.returncode == 0 and output_json.exists():
                    with open(output_json, "r", encoding="utf-8") as f:
                        scenes_raw = f.read()

                    p.scene_cuts_json = scenes_raw
                    p.status = "ready"
                    p.current_stage = "Scene Detection Complete"
                    await session.commit()
                    await ws_manager.broadcast(
                        project_id,
                        {"type": "complete", "message": "Scene detection complete!"},
                    )

        except Exception as e:
            await ProcessManager.unregister_process(project_id)
            print(f"Error in scene detect worker: {e}")

    # ==========================================
    # Phase 3: Ollama Clip Discovery Engine
    # ==========================================
    @classmethod
    async def discover_clips_project(
        cls, session: AsyncSession, project_id: str, payload: DiscoverClipsRequest
    ) -> ProjectRead:
        q = select(Project).where(Project.id == project_id)
        res = await session.execute(q)
        project = res.scalar_one_or_none()
        if not project:
            raise NotFoundError(f"Project {project_id} not found")

        app_settings = await SettingsService.get_or_create_settings(session)
        ollama_model = payload.ollama_model or app_settings.ollama_model or "qwen2.5:7b"

        proj_dir = settings.cache_dir / "projects" / project_id

        # STAGE CACHING CHECK:
        # If transcript is missing, execute transcription first
        if not project.transcript_json:
            await cls.transcribe_project(session, project_id, TranscribeRequest())
            # Poll or await transcription
            for _ in range(300):
                await asyncio.sleep(1.0)
                await session.refresh(project)
                if project.transcript_json:
                    break
                if project.status == "error":
                    raise ValidationError(f"Transcription failed: {project.error_message}")

        # Check scene cuts
        if not project.scene_cuts_json and project.video_path:
            await cls.detect_scenes_project(session, project_id)
            for _ in range(60):
                await asyncio.sleep(0.5)
                await session.refresh(project)
                if project.scene_cuts_json:
                    break

        project.status = "scoring_clips"
        project.progress_percent = 10.0
        project.current_stage = f"Evaluating clips with Ollama ({ollama_model})..."
        project.ollama_model_used = ollama_model
        await session.commit()
        await session.refresh(project)

        target_max_clips = None if payload.clip_count_mode == "auto" else payload.max_clips

        asyncio.create_task(
            cls._run_discover_clips(
                project_id=project_id,
                ollama_model=ollama_model,
                min_duration=payload.min_duration_sec,
                max_duration=payload.max_duration_sec,
                max_clips=target_max_clips,
                custom_instructions=payload.custom_prompt or "",
                allow_multi_segment=payload.allow_multi_segment,
                auto_duration=payload.auto_duration,
            )
        )

        return cls._to_read_schema(project)

    @classmethod
    async def _run_discover_clips(
        cls,
        project_id: str,
        ollama_model: str,
        min_duration: int,
        max_duration: int,
        max_clips: int | None,
        custom_instructions: str,
        allow_multi_segment: bool = False,
        auto_duration: bool = True,
    ):
        try:
            async with async_session_maker() as session:
                q = select(Project).where(Project.id == project_id)
                res = await session.execute(q)
                p = res.scalar_one_or_none()
                if not p:
                    return

                # Parse cached transcript
                transcript_dict = json.loads(p.transcript_json or "{}")
                transcript_data = TranscriptData(
                    language=transcript_dict.get("language", "en"),
                    duration=transcript_dict.get("duration", p.duration_sec or 60.0),
                    segments=[
                        TranscriptSegment(**s) for s in transcript_dict.get("segments", [])
                    ],
                )

                # Parse engagement signals
                engagement = None
                if p.engagement_signals_json:
                    raw_sig = json.loads(p.engagement_signals_json)
                    engagement = EngagementSignals(
                        heatmap=[EngagementPoint(**pt) for pt in raw_sig.get("heatmap", [])],
                        comment_timestamps=[EngagementPoint(**pt) for pt in raw_sig.get("comment_timestamps", [])],
                        chat_velocity=[EngagementPoint(**pt) for pt in raw_sig.get("chat_velocity", [])],
                        audio_energy=[EngagementPoint(**pt) for pt in raw_sig.get("audio_energy", [])],
                    )

                # Parse scene cuts
                scene_cuts = []
                if p.scene_cuts_json:
                    raw_scenes = json.loads(p.scene_cuts_json)
                    scene_cuts = [SceneCut(**sc) for sc in raw_scenes]

            await ws_manager.broadcast(
                project_id,
                {"type": "progress", "percent": 40.0, "stage": "scoring_clips", "message": "Fusing retention peaks and querying Ollama..."},
            )

            # Discover clips with Ollama
            clips, recommendation = await OllamaClipDiscoveryEngine.discover_clips(
                transcript=transcript_data,
                engagement=engagement,
                scene_cuts=scene_cuts,
                model_name=ollama_model,
                min_duration=min_duration,
                max_duration=max_duration,
                max_clips=max_clips,
                custom_instructions=custom_instructions,
                allow_multi_segment=allow_multi_segment,
                auto_duration=auto_duration,
            )

            async with async_session_maker() as session:
                q = select(Project).where(Project.id == project_id)
                res = await session.execute(q)
                p = res.scalar_one_or_none()
                if p and p.status != "cancelled":
                    p.candidate_clips_json = json.dumps([c.model_dump() for c in clips])
                    p.ai_clip_recommendation = recommendation
                    p.status = "ready"
                    p.progress_percent = 100.0
                    p.current_stage = f"Discovered {len(clips)} candidate clips!"
                    await session.commit()

            await ws_manager.broadcast(
                project_id,
                {
                    "type": "complete",
                    "message": f"Discovered {len(clips)} clips with Ollama!",
                    "recommendation": recommendation,
                },
            )

        except Exception as e:
            async with async_session_maker() as session:
                q = select(Project).where(Project.id == project_id)
                res = await session.execute(q)
                p = res.scalar_one_or_none()
                if p and p.status != "cancelled":
                    p.status = "error"
                    p.error_message = str(e)
                    await session.commit()
            await ws_manager.broadcast(project_id, {"type": "error", "error": str(e)})

    # ==========================================
    # Transcript & Clips Retrieval & Typo Editor
    # ==========================================
    @classmethod
    async def get_transcript(cls, session: AsyncSession, project_id: str) -> TranscriptData:
        q = select(Project).where(Project.id == project_id)
        res = await session.execute(q)
        project = res.scalar_one_or_none()
        if not project or not project.transcript_json:
            raise NotFoundError(f"No transcript found for project {project_id}")

        data = json.loads(project.transcript_json)
        return TranscriptData(
            language=data.get("language", "en"),
            language_probability=data.get("language_probability", 1.0),
            duration=data.get("duration", 0.0),
            segments=[TranscriptSegment(**s) for s in data.get("segments", [])],
        )

    @classmethod
    async def update_transcript(
        cls, session: AsyncSession, project_id: str, payload: UpdateTranscriptRequest
    ) -> TranscriptData:
        q = select(Project).where(Project.id == project_id)
        res = await session.execute(q)
        project = res.scalar_one_or_none()
        if not project:
            raise NotFoundError(f"Project {project_id} not found")

        current = json.loads(project.transcript_json or "{}")
        current["segments"] = [
            {
                **segment.model_dump(),
                "text": " ".join(word.word for word in segment.words) if segment.words else segment.text,
            }
            for segment in payload.segments
        ]

        project.transcript_json = json.dumps(current)
        await session.commit()

        return TranscriptData(
            language=current.get("language", "en"),
            language_probability=current.get("language_probability", 1.0),
            duration=current.get("duration", 0.0),
            segments=[TranscriptSegment(**segment) for segment in current["segments"]],
        )

    @classmethod
    async def get_clips(cls, session: AsyncSession, project_id: str) -> list[CandidateClip]:
        q = select(Project).where(Project.id == project_id)
        res = await session.execute(q)
        project = res.scalar_one_or_none()
        if not project or not project.candidate_clips_json:
            return []

        data = json.loads(project.candidate_clips_json)
        return [CandidateClip(**c) for c in data]

    @classmethod
    async def update_clips(cls, session: AsyncSession, project_id: str, clips: list[CandidateClip]) -> list[CandidateClip]:
        q = select(Project).where(Project.id == project_id)
        res = await session.execute(q)
        project = res.scalar_one_or_none()
        if not project:
            raise NotFoundError(f"Project {project_id} not found")

        project.candidate_clips_json = json.dumps([c.model_dump() for c in clips])
        await session.commit()
        await session.refresh(project)
        return clips

    @classmethod
    async def cancel_project(cls, session: AsyncSession, project_id: str) -> bool:
        await ProcessManager.cancel_project(project_id)

        q = select(Project).where(Project.id == project_id)
        res = await session.execute(q)
        project = res.scalar_one_or_none()
        if not project:
            raise NotFoundError(f"Project {project_id} not found")

        project.status = "cancelled"
        project.current_stage = "Job cancelled by user"
        project.active_pid = None
        await session.commit()

        await ws_manager.broadcast(
            project_id,
            {"type": "cancelled", "message": "Job successfully cancelled"},
        )
        return True

    @classmethod
    async def get_project(cls, session: AsyncSession, project_id: str) -> ProjectRead:
        q = select(Project).where(Project.id == project_id)
        res = await session.execute(q)
        project = res.scalar_one_or_none()
        if not project:
            raise NotFoundError(f"Project {project_id} not found")

        return cls._to_read_schema(project)

    @classmethod
    async def list_projects(cls, session: AsyncSession) -> list[ProjectSummary]:
        q = select(Project).order_by(Project.created_at.desc())
        res = await session.execute(q)
        items = res.scalars().all()

        summaries = []
        for p in items:
            clips_count = 0
            if p.candidate_clips_json:
                try:
                    clips_count = len(json.loads(p.candidate_clips_json))
                except Exception:
                    pass

            is_missing = bool(p.video_path and not Path(p.video_path).is_file())

            summaries.append(
                ProjectSummary(
                    id=p.id,
                    title=p.title,
                    source_type=p.source_type,
                    status=p.status,
                    progress_percent=p.progress_percent,
                    duration_sec=p.duration_sec,
                    has_transcript=bool(p.transcript_json),
                    clips_count=clips_count,
                    created_at=p.created_at.isoformat(),
                    file_missing=is_missing,
                )
            )
        return summaries

    @classmethod
    async def delete_project(cls, session: AsyncSession, project_id: str) -> dict:
        """
        Harden DELETE /api/projects/{project_id}:
        - Cancel any running background job/process for project_id first (ignore errors if none active)
        - Delete all child/related SQLite rows referencing project_id before deleting the Project row
          so SQLite NEVER fails with a foreign-key constraint error.
        - Delete project cache directory (settings.cache_dir / "projects" / project_id) using
          shutil.rmtree(..., ignore_errors=True) — succeeding cleanly even if folder or video_path
          was already manually deleted from disk.
        - Return {"deleted": True, "project_id": project_id}.
        """
        # 1. Cancel running background process & active export jobs
        try:
            await ProcessManager.cancel_project(project_id)
        except Exception:
            pass

        try:
            from app.exports.service import get_jobs, cancel_job
            jobs = await get_jobs(project_id)
            for j in jobs:
                if j.status in ("queued", "running"):
                    await cancel_job(j.id)
        except Exception:
            pass

        # 2. Delete child / related SQLite rows
        try:
            from app.workspace.models import WorkspaceConfig
            await session.execute(delete(WorkspaceConfig).where(WorkspaceConfig.project_id == project_id))
        except Exception:
            pass

        # 3. Delete Project row
        await session.execute(delete(Project).where(Project.id == project_id))
        await session.commit()

        # 4. Clean up cache directory cleanly
        proj_dir = settings.cache_dir / "projects" / project_id
        shutil.rmtree(proj_dir, ignore_errors=True)

        # 5. Broadcast to WS
        try:
            await ws_manager.broadcast(project_id, {"type": "deleted", "project_id": project_id})
        except Exception:
            pass

        return {"deleted": True, "project_id": project_id}

    @classmethod
    async def cleanup_projects(
        cls,
        session: AsyncSession,
        remove_missing: bool = True,
        remove_cancelled: bool = True,
    ) -> dict:
        """
        Finds all projects where video_path is missing on disk (when remove_missing=True)
        OR status in ("cancelled", "failed", "error") (when remove_cancelled=True),
        cascade-deletes them from SQLite, removes leftover workspace_cache/projects/<id>
        folders, and returns {"removed_count": N, "removed_ids": [...]}.
        """
        q = select(Project)
        res = await session.execute(q)
        projects = res.scalars().all()

        target_ids: list[str] = []
        for p in projects:
            should_remove = False
            if remove_missing:
                if p.video_path and not Path(p.video_path).is_file():
                    should_remove = True
                elif not p.video_path and p.status in ("ready", "error", "cancelled", "failed"):
                    should_remove = True

            if remove_cancelled:
                if (p.status or "").lower() in ("cancelled", "failed", "error"):
                    should_remove = True

            if should_remove:
                target_ids.append(p.id)

        for pid in target_ids:
            try:
                await ProcessManager.cancel_project(pid)
            except Exception:
                pass

            try:
                from app.exports.service import get_jobs, cancel_job
                jobs = await get_jobs(pid)
                for j in jobs:
                    if j.status in ("queued", "running"):
                        await cancel_job(j.id)
            except Exception:
                pass

            try:
                from app.workspace.models import WorkspaceConfig
                await session.execute(delete(WorkspaceConfig).where(WorkspaceConfig.project_id == pid))
            except Exception:
                pass

            await session.execute(delete(Project).where(Project.id == pid))

            proj_dir = settings.cache_dir / "projects" / pid
            shutil.rmtree(proj_dir, ignore_errors=True)

        await session.commit()

        return {
            "removed_count": len(target_ids),
            "removed_ids": target_ids,
        }

    @staticmethod
    def _to_read_schema(p: Project) -> ProjectRead:
        signals = None
        if p.engagement_signals_json:
            try:
                raw_sig = json.loads(p.engagement_signals_json)
                signals = EngagementSignals(
                    heatmap=[EngagementPoint(**pt) for pt in raw_sig.get("heatmap", [])],
                    comment_timestamps=[EngagementPoint(**pt) for pt in raw_sig.get("comment_timestamps", [])],
                    chat_velocity=[EngagementPoint(**pt) for pt in raw_sig.get("chat_velocity", [])],
                    audio_energy=[EngagementPoint(**pt) for pt in raw_sig.get("audio_energy", [])],
                )
            except Exception:
                signals = None

        candidate_clips = []
        if p.candidate_clips_json:
            try:
                raw_clips = json.loads(p.candidate_clips_json)
                candidate_clips = [CandidateClip(**c) for c in raw_clips]
            except Exception:
                candidate_clips = []

        is_missing = bool(p.video_path and not Path(p.video_path).is_file())

        return ProjectRead(
            id=p.id,
            title=p.title,
            source_type=p.source_type,
            source_url=p.source_url,
            download_mode=p.download_mode,
            status=p.status,
            progress_percent=p.progress_percent,
            current_stage=p.current_stage,
            video_path=p.video_path,
            audio_path=p.audio_path,
            thumbnail_path=p.thumbnail_path,
            duration_sec=p.duration_sec,
            width=p.width,
            height=p.height,
            fps=p.fps,
            file_size_bytes=p.file_size_bytes,
            engagement_signals=signals,
            has_transcript=bool(p.transcript_json),
            has_scene_cuts=bool(p.scene_cuts_json),
            candidate_clips=candidate_clips,
            whisper_model_used=p.whisper_model_used,
            ollama_model_used=p.ollama_model_used,
            ai_clip_recommendation=p.ai_clip_recommendation,
            error_message=p.error_message,
            active_pid=p.active_pid,
            file_missing=is_missing,
            created_at=p.created_at.isoformat(),
            updated_at=p.updated_at.isoformat(),
        )
