import asyncio
import json
from pathlib import Path
import shutil
import subprocess


def _run_sync(cmd: list[str], timeout: float = 30.0, combine_stderr: bool = True) -> tuple[int, str]:
    try:
        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
        out = proc.stdout or ""
        err = proc.stderr or ""
        if combine_stderr:
            return proc.returncode, out + ("\n" + err if err else "")
        return proc.returncode, out
    except Exception as e:
        return -1, str(e)


class FFmpegHelper:
    @staticmethod
    async def probe_media(file_path: Path) -> dict:
        ffprobe_bin = shutil.which("ffprobe") or "ffprobe"
        cmd = [
            ffprobe_bin,
            "-v",
            "quiet",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            str(file_path),
        ]
        rc, out = await asyncio.to_thread(_run_sync, cmd, 15.0, combine_stderr=False)
        if rc != 0:
            return {}

        try:
            data = json.loads(out)
            format_info = data.get("format", {})
            duration = float(format_info.get("duration", 0.0))
            size = int(format_info.get("size", 0))

            video_stream = None
            audio_stream = None
            for s in data.get("streams", []):
                if s.get("codec_type") == "video" and not video_stream:
                    video_stream = s
                elif s.get("codec_type") == "audio" and not audio_stream:
                    audio_stream = s

            width = int(video_stream.get("width", 0)) if video_stream else None
            height = int(video_stream.get("height", 0)) if video_stream else None

            # Calculate FPS
            fps = None
            if video_stream and "r_frame_rate" in video_stream:
                rate_parts = video_stream["r_frame_rate"].split("/")
                if len(rate_parts) == 2 and float(rate_parts[1]) > 0:
                    fps = round(float(rate_parts[0]) / float(rate_parts[1]), 2)

            return {
                "duration_sec": duration,
                "width": width,
                "height": height,
                "fps": fps,
                "file_size_bytes": size,
                "video_codec": video_stream.get("codec_name") if video_stream else None,
                "audio_codec": audio_stream.get("codec_name") if audio_stream else None,
            }
        except Exception:
            return {}

    @staticmethod
    async def extract_16k_mono_audio(input_video: Path, output_wav: Path) -> bool:
        """Extract 16kHz mono WAV for Whisper transcription & audio energy mining."""
        ffmpeg_bin = shutil.which("ffmpeg") or "ffmpeg"
        output_wav.parent.mkdir(parents=True, exist_ok=True)

        cmd = [
            ffmpeg_bin,
            "-y",
            "-i",
            str(input_video),
            "-vn",
            "-acodec",
            "pcm_s16le",
            "-ar",
            "16000",
            "-ac",
            "1",
            str(output_wav),
        ]
        rc, _ = await asyncio.to_thread(_run_sync, cmd, 300.0)
        return rc == 0 and output_wav.exists() and output_wav.stat().st_size > 0

    @staticmethod
    async def extract_thumbnail(input_video: Path, output_jpg: Path, time_sec: float = 1.0) -> bool:
        """Extract a single frame JPEG thumbnail using output seeking."""
        ffmpeg_bin = shutil.which("ffmpeg") or "ffmpeg"
        output_jpg.parent.mkdir(parents=True, exist_ok=True)

        cmd = [
            ffmpeg_bin,
            "-y",
            "-ss",
            str(time_sec),
            "-i",
            str(input_video),
            "-vframes",
            "1",
            "-q:v",
            "2",
            str(output_jpg),
        ]
        rc, _ = await asyncio.to_thread(_run_sync, cmd, 15.0)
        return rc == 0 and output_jpg.exists()
