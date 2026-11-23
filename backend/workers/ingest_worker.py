"""
Isolated Ingestion Worker for URL Downloads & Engagement Mining
Executes yt-dlp, parses Heatmaps, Comment Timestamps, and Live Chat replays.
"""

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import yt_dlp

# Regex for timestamps in comments: e.g. "1:23", "01:23", "1:02:45"
TIMESTAMP_REGEX = re.compile(r"\b(?:(\d{1,2}):)?([0-5]?\d):([0-5]\d)\b")
HYPE_KEYWORDS = {"lmao", "lol", "insane", "best part", "clip", "clip this", "omg", "wtf", "crazy", "haha", "fire", "w"}


def parse_timestamp_sec(match: re.Match) -> float:
    hours = int(match.group(1)) if match.group(1) else 0
    minutes = int(match.group(2))
    seconds = int(match.group(3))
    return float(hours * 3600 + minutes * 60 + seconds)


def emit_progress(percent: float, stage: str, message: str = "", speed: str = "", eta: int = 0):
    payload = {
        "type": "progress",
        "percent": round(percent, 1),
        "stage": stage,
        "message": message,
        "speed": speed,
        "eta": eta,
    }
    print("PROGRESS:" + json.dumps(payload), flush=True)


def parse_heatmap(info_dict: dict) -> list[dict]:
    """Parse YouTube 'Most Replayed' heatmap data points."""
    raw_heatmap = info_dict.get("heatmap") or []
    points = []
    if not raw_heatmap:
        return points

    max_val = max((p.get("value", 0.0) for p in raw_heatmap), default=1.0)
    if max_val == 0:
        max_val = 1.0

    for item in raw_heatmap:
        start_time = float(item.get("start_time", 0.0))
        end_time = float(item.get("end_time", start_time + 1.0))
        mid_time = round((start_time + end_time) / 2.0, 2)
        val = float(item.get("value", 0.0))
        score = round((val / max_val) * 100.0, 1)

        points.append({
            "time_sec": mid_time,
            "score": score,
            "source": "heatmap",
            "label": "most_replayed",
        })

    return points


def parse_comment_timestamps(info_dict: dict) -> list[dict]:
    """Parse timestamps from comments weighted by likes and hype keywords."""
    comments = info_dict.get("comments") or []
    points = []
    if not comments:
        return points

    for c in comments:
        text = c.get("text", "")
        like_count = c.get("like_count", 0) or 0
        matches = list(TIMESTAMP_REGEX.finditer(text))
        if not matches:
            continue

        lower_text = text.lower()
        has_hype_word = any(kw in lower_text for kw in HYPE_KEYWORDS)
        # Weight based on likes and keywords
        weight = 1.0 + min(like_count / 10.0, 5.0) + (3.0 if has_hype_word else 0.0)

        for m in matches:
            t_sec = parse_timestamp_sec(m)
            points.append({
                "time_sec": t_sec,
                "score": min(100.0, round(weight * 15.0, 1)),
                "source": "comment",
                "label": text[:60],
            })

    # Deduplicate timestamps within 3 seconds of each other
    points.sort(key=lambda x: x["time_sec"])
    clustered = []
    for p in points:
        if clustered and abs(clustered[-1]["time_sec"] - p["time_sec"]) < 3.0:
            clustered[-1]["score"] = min(100.0, clustered[-1]["score"] + p["score"] * 0.4)
        else:
            clustered.append(p)

    return clustered


def parse_live_chat_velocity(info_dict: dict, chat_json_path: Path | None = None) -> list[dict]:
    """Parse live chat replay for messages-per-second spikes."""
    messages = []
    if chat_json_path and chat_json_path.exists():
        try:
            with open(chat_json_path, "r", encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        item = json.loads(line)
                        offset = item.get("replayChatItemAction", {}).get("videoOffsetTimeMsec")
                        if offset:
                            messages.append(float(offset) / 1000.0)
        except Exception:
            pass

    if not messages:
        return []

    messages.sort()
    max_time = int(messages[-1]) if messages else 0
    bucket_sec = 5
    buckets = {}

    for t in messages:
        b = int(t // bucket_sec) * bucket_sec
        buckets[b] = buckets.get(b, 0) + 1

    if not buckets:
        return []

    max_count = max(buckets.values())
    if max_count == 0:
        max_count = 1

    signals = []
    for b_time, count in sorted(buckets.items()):
        score = round((count / max_count) * 100.0, 1)
        if score >= 50.0:  # Only capture significant velocity spikes
            signals.append({
                "time_sec": float(b_time),
                "score": score,
                "source": "chat_velocity",
                "label": f"chat_spike ({count} msgs/5s)",
            })

    return signals


def main():
    parser = argparse.ArgumentParser(description="yt-dlp Ingestion & Signal Extraction")
    parser.add_argument("--url", type=str, required=True)
    parser.add_argument("--project-id", type=str, required=True)
    parser.add_argument("--download-mode", type=str, default="full", choices=["full", "fast_vod"])
    parser.add_argument("--output-dir", type=str, required=True)
    parser.add_argument("--cookies-browser", type=str, default=None)
    parser.add_argument("--cookies-file", type=str, default=None)
    parser.add_argument("--po-token", type=str, default=None)
    parser.add_argument("--js-runtime", type=str, default=None)
    parser.add_argument("--twitch-chat-cli", type=str, default=None)
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    outtmpl = str(output_dir / f"{args.project_id}.%(ext)s")

    emit_progress(5.0, "extracting_metadata", "Extracting video info and engagement signals...")

    def progress_hook(d):
        if d["status"] == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            downloaded = d.get("downloaded_bytes", 0)
            percent = (downloaded / total * 80.0) if total > 0 else 20.0
            speed_str = d.get("_speed_str", "N/A")
            eta_val = d.get("eta", 0) or 0
            emit_progress(10.0 + percent, "downloading", f"Downloading media: {d.get('_percent_str', '')}", speed_str, eta_val)
        elif d["status"] == "finished":
            emit_progress(90.0, "processing", "Download complete, processing audio...")

    ydl_opts = {
        "outtmpl": outtmpl,
        "progress_hooks": [progress_hook],
        "quiet": True,
        "no_warnings": True,
        "getcomments": True,
    }

    if args.download_mode == "fast_vod":
        ydl_opts["format"] = "bestaudio/best"
    else:
        ydl_opts["format"] = "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best"

    if args.cookies_browser:
        ydl_opts["cookiesfrombrowser"] = (args.cookies_browser,)
    elif args.cookies_file and Path(args.cookies_file).exists():
        ydl_opts["cookiefile"] = args.cookies_file

    if args.po_token:
        ydl_opts["extractor_args"] = {"youtube": {"po_token": [args.po_token]}}

    if args.js_runtime and args.js_runtime != "auto":
        ydl_opts["js_runtimes"] = [args.js_runtime]

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(args.url, download=True)

        downloaded_file = Path(ydl.prepare_filename(info))
        if not downloaded_file.exists():
            # In case extension was merged to .mp4 or .mkv
            potential_files = list(output_dir.glob(f"{args.project_id}.*"))
            if potential_files:
                downloaded_file = potential_files[0]

        emit_progress(92.0, "extracting_audio", "Extracting 16kHz audio track...")

        # Extract 16kHz mono WAV for Whisper & energy mining
        audio_file = output_dir / f"{args.project_id}_16k.wav"
        ffmpeg_bin = shutil.which("ffmpeg") or "ffmpeg"
        subprocess.run(
            [ffmpeg_bin, "-y", "-i", str(downloaded_file), "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1", str(audio_file)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )

        emit_progress(95.0, "analyzing_engagement", "Analyzing retention heatmap & comments...")

        # Parse signals
        heatmap_points = parse_heatmap(info)
        comment_points = parse_comment_timestamps(info)
        chat_points = parse_live_chat_velocity(info)

        # Run audio energy analysis directly in worker
        from audio_energy_worker import analyze_audio_energy
        audio_points = analyze_audio_energy(audio_file)

        signals_data = {
            "heatmap": heatmap_points,
            "comment_timestamps": comment_points,
            "chat_velocity": chat_points,
            "audio_energy": audio_points,
        }

        signals_file = output_dir / f"{args.project_id}_signals.json"
        with open(signals_file, "w", encoding="utf-8") as f:
            json.dump(signals_data, f, indent=2)

        emit_progress(100.0, "ready", "Ingestion and signal mining complete!")

        # Output final result JSON for parent service
        result = {
            "title": info.get("title", "YouTube Video"),
            "video_path": str(downloaded_file),
            "audio_path": str(audio_file),
            "duration_sec": float(info.get("duration", 0.0)),
            "width": info.get("width"),
            "height": info.get("height"),
            "fps": info.get("fps"),
            "signals": signals_data,
        }
        print("COMPLETE:" + json.dumps(result), flush=True)

    except Exception as e:
        print("ERROR:" + str(e), file=sys.stderr, flush=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
