import asyncio
from datetime import datetime, timezone
import os
from pathlib import Path
import shutil
import subprocess
import sys
import httpx
from app.core.config import settings
from app.diagnostics.schemas import (
    FFmpegInfo,
    GPUInfo,
    OllamaInfo,
    OllamaModel,
    SystemDiagnosticsResponse,
    YtDlpInfo,
    YtDlpUpdateResponse,
)


def _run_cmd_sync(cmd: list[str], timeout: float = 3.0) -> tuple[int, str]:
    try:
        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
        )
        return proc.returncode, proc.stdout + ("\n" + proc.stderr if proc.stderr else "")
    except Exception as e:
        return -1, str(e)


class DiagnosticsService:
    @classmethod
    async def get_gpu_info(cls) -> GPUInfo:
        nvidia_smi = shutil.which("nvidia-smi")
        if not nvidia_smi:
            return GPUInfo(has_gpu=False, status="not_detected")

        try:
            cmd = [
                nvidia_smi,
                "--query-gpu=name,driver_version,memory.total,memory.used,memory.free,temperature.gpu,utilization.gpu",
                "--format=csv,noheader,nounits",
            ]
            rc, out = await asyncio.to_thread(_run_cmd_sync, cmd, 3.0)
            if rc != 0 or not out.strip():
                return GPUInfo(has_gpu=False, status="error")

            lines = out.strip().splitlines()
            line = lines[0]
            parts = [p.strip() for p in line.split(",")]

            # Query banner for CUDA version
            cuda_ver = None
            rc_banner, banner_out = await asyncio.to_thread(_run_cmd_sync, [nvidia_smi], 3.0)
            if rc_banner == 0:
                for text_line in banner_out.splitlines():
                    if "CUDA Version:" in text_line:
                        cuda_part = text_line.split("CUDA Version:")[1]
                        cuda_ver = cuda_part.split()[0].replace("|", "").strip()
                        break

            name = parts[0]
            driver = parts[1]
            total = int(float(parts[2])) if len(parts) > 2 and parts[2].replace(".", "").isdigit() else None
            used = int(float(parts[3])) if len(parts) > 3 and parts[3].replace(".", "").isdigit() else None
            free = int(float(parts[4])) if len(parts) > 4 and parts[4].replace(".", "").isdigit() else None
            temp = int(float(parts[5])) if len(parts) > 5 and parts[5].replace(".", "").isdigit() else None
            util = int(float(parts[6])) if len(parts) > 6 and parts[6].replace(".", "").isdigit() else None

            status = "optimal"
            if util is not None and util > 90:
                status = "high_usage"

            return GPUInfo(
                has_gpu=True,
                gpu_name=name,
                driver_version=driver,
                cuda_version=cuda_ver,
                vram_total_mb=total,
                vram_used_mb=used,
                vram_free_mb=free,
                temperature_c=temp,
                gpu_utilization_percent=util,
                status=status,
            )
        except Exception:
            return GPUInfo(has_gpu=False, status="error")

    @classmethod
    async def get_ffmpeg_info(cls) -> FFmpegInfo:
        ffmpeg_bin = shutil.which("ffmpeg")
        if not ffmpeg_bin:
            return FFmpegInfo(is_installed=False, status="missing")

        try:
            rc_ver, ver_out = await asyncio.to_thread(_run_cmd_sync, [ffmpeg_bin, "-version"], 3.0)
            if rc_ver != 0:
                return FFmpegInfo(is_installed=False, status="missing")

            lines = ver_out.splitlines()
            version_str = lines[0] if lines else "unknown"
            has_libass = "--enable-libass" in ver_out

            rc_enc, enc_out = await asyncio.to_thread(_run_cmd_sync, [ffmpeg_bin, "-encoders"], 3.0)
            has_libx264 = "libx264" in enc_out
            has_h264_nvenc = "h264_nvenc" in enc_out
            has_hevc_nvenc = "hevc_nvenc" in enc_out

            status = "ready" if has_h264_nvenc else ("ready_cpu_only" if has_libx264 else "missing")
            return FFmpegInfo(
                is_installed=True,
                version=version_str,
                has_libx264=has_libx264,
                has_h264_nvenc=has_h264_nvenc,
                has_hevc_nvenc=has_hevc_nvenc,
                has_libass=has_libass,
                status=status,
            )
        except Exception:
            return FFmpegInfo(is_installed=False, status="missing")

    @classmethod
    async def get_ollama_info(cls) -> OllamaInfo:
        url = settings.ollama_url.rstrip("/")
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                resp = await client.get(f"{url}/api/tags")
                if resp.status_code == 200:
                    data = resp.json()
                    models_raw = data.get("models", [])
                    models = []
                    for m in models_raw:
                        details = m.get("details", {})
                        param_size = details.get("parameter_size")
                        models.append(
                            OllamaModel(
                                name=m.get("name", "unknown"),
                                size_bytes=m.get("size"),
                                parameter_size=param_size,
                                modified_at=m.get("modified_at"),
                            )
                        )
                    status = "connected" if models else "empty"
                    return OllamaInfo(
                        is_reachable=True,
                        url=url,
                        models=models,
                        status=status,
                    )
                return OllamaInfo(is_reachable=False, url=url, models=[], status="disconnected")
        except Exception:
            return OllamaInfo(is_reachable=False, url=url, models=[], status="disconnected")

    @classmethod
    async def get_ytdlp_info(cls) -> YtDlpInfo:
        ytdlp_bin = shutil.which("yt-dlp")
        version = None
        is_installed = False

        if ytdlp_bin:
            rc, out = await asyncio.to_thread(_run_cmd_sync, [ytdlp_bin, "--version"], 3.0)
            if rc == 0:
                version = out.strip().splitlines()[0] if out.strip() else None
                is_installed = True

        if not is_installed:
            rc, out = await asyncio.to_thread(_run_cmd_sync, [sys.executable, "-m", "yt_dlp", "--version"], 3.0)
            if rc == 0:
                version = out.strip().splitlines()[0] if out.strip() else None
                is_installed = True

        # Check JS Runtimes (Deno preferred, Node supported)
        js_type = "none"
        js_ver = None
        has_js = False

        deno_bin = shutil.which("deno")
        if deno_bin:
            rc, out = await asyncio.to_thread(_run_cmd_sync, [deno_bin, "--version"], 3.0)
            if rc == 0 and out.strip():
                js_type = "deno"
                js_ver = out.strip().splitlines()[0]
                has_js = True

        if not has_js:
            node_bin = shutil.which("node")
            if not node_bin:
                local_pi_node = Path(os.environ.get("LOCALAPPDATA", "")) / "pi-node" / "current" / "node.exe"
                if local_pi_node.is_file():
                    node_bin = str(local_pi_node)

            if node_bin:
                rc, out = await asyncio.to_thread(_run_cmd_sync, [node_bin, "-v"], 3.0)
                if rc == 0 and out.strip():
                    js_type = "node"
                    js_ver = out.strip().splitlines()[0]
                    has_js = True

        status = "ready" if (is_installed and has_js) else ("warning_no_js" if is_installed else "missing")

        return YtDlpInfo(
            is_installed=is_installed,
            version=version,
            has_js_runtime=has_js,
            js_runtime_type=js_type,
            js_runtime_version=js_ver,
            status=status,
        )

    @classmethod
    async def check_all(cls) -> SystemDiagnosticsResponse:
        gpu_task = asyncio.create_task(cls.get_gpu_info())
        ffmpeg_task = asyncio.create_task(cls.get_ffmpeg_info())
        ollama_task = asyncio.create_task(cls.get_ollama_info())
        ytdlp_task = asyncio.create_task(cls.get_ytdlp_info())

        gpu, ffmpeg, ollama, ytdlp = await asyncio.gather(
            gpu_task, ffmpeg_task, ollama_task, ytdlp_task
        )

        recommended = "lite"
        if gpu.has_gpu and gpu.vram_total_mb:
            if gpu.vram_total_mb >= 11000:
                recommended = "pro"
            elif gpu.vram_total_mb >= 5000:
                recommended = "balanced"

        return SystemDiagnosticsResponse(
            gpu=gpu,
            ffmpeg=ffmpeg,
            ollama=ollama,
            ytdlp=ytdlp,
            recommended_preset=recommended,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

    @classmethod
    async def update_ytdlp(cls) -> YtDlpUpdateResponse:
        old_info = await cls.get_ytdlp_info()
        old_version = old_info.version

        try:
            cmd = [sys.executable, "-m", "pip", "install", "-U", "yt-dlp[default]"]
            rc, out = await asyncio.to_thread(_run_cmd_sync, cmd, 120.0)
            success = rc == 0

            new_info = await cls.get_ytdlp_info()
            return YtDlpUpdateResponse(
                success=success,
                old_version=old_version,
                new_version=new_info.version,
                output=out,
            )
        except Exception as e:
            return YtDlpUpdateResponse(
                success=False,
                old_version=old_version,
                new_version=old_version,
                output=str(e),
            )
