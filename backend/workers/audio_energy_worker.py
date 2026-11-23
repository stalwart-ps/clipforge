"""
Audio Energy & Loudness Spike Extractor Worker
Runs in an ISOLATED subprocess to keep FastAPI startup 100% free of heavy audio libraries.
"""

import argparse
import json
from pathlib import Path
import sys
import wave
import numpy as np


def analyze_audio_energy(wav_path: Path, window_sec: float = 1.0, hop_sec: float = 0.5) -> list[dict]:
    with wave.open(str(wav_path), "rb") as wf:
        n_channels = wf.getnchannels()
        sampwidth = wf.getsampwidth()
        framerate = wf.getframerate()
        total_frames = wf.getnframes()

        if total_frames == 0 or framerate == 0:
            return []

        # Convert sample width to dtype and scale
        if sampwidth == 2:
            dtype = np.int16
            scale = 32768.0
        elif sampwidth == 4:
            dtype = np.int32
            scale = 2147483648.0
        else:
            dtype = np.uint8
            scale = 128.0

        window_size = int(window_sec * framerate)
        hop_size = int(hop_sec * framerate)

        energy_points = []
        rms_values = []

        # Stream audio in rolling blocks to keep peak memory < 2MB for any file duration
        buffer = np.empty(0, dtype=np.float32)
        sample_offset = 0
        read_block_frames = framerate * 10

        while sample_offset < total_frames or len(buffer) >= window_size:
            if len(buffer) < window_size and sample_offset < total_frames:
                to_read = min(read_block_frames, total_frames - sample_offset)
                raw_chunk = wf.readframes(to_read)
                sample_offset += to_read
                if not raw_chunk:
                    break
                chunk_audio = np.frombuffer(raw_chunk, dtype=dtype).astype(np.float32) / scale
                if n_channels > 1:
                    chunk_audio = chunk_audio.reshape(-1, n_channels).mean(axis=1)
                buffer = np.concatenate((buffer, chunk_audio)) if len(buffer) > 0 else chunk_audio

            if len(buffer) < window_size:
                break

            processed_in_buf = 0
            buf_start_sample = sample_offset - len(buffer)
            while processed_in_buf + window_size <= len(buffer):
                s_idx = buf_start_sample + processed_in_buf
                chunk = buffer[processed_in_buf : processed_in_buf + window_size]
                rms = float(np.sqrt(np.mean(chunk**2)))
                time_sec = round(s_idx / framerate, 2)
                rms_values.append(rms)
                energy_points.append({"time_sec": time_sec, "raw_rms": rms})
                processed_in_buf += hop_size

            buffer = buffer[processed_in_buf:]

    if not rms_values:
        return []

    max_rms = max(rms_values)
    if max_rms == 0:
        max_rms = 1.0

    # Percentiles for hype detection
    p75 = float(np.percentile(rms_values, 75))
    p90 = float(np.percentile(rms_values, 90))

    signals = []
    for item in energy_points:
        raw = item["raw_rms"]
        score = round((raw / max_rms) * 100.0, 1)
        label = None
        if raw >= p90:
            label = "loud_reaction"
        elif raw >= p75:
            label = "audio_peak"

        signals.append({
            "time_sec": item["time_sec"],
            "score": score,
            "source": "audio_energy",
            "label": label,
        })

    return signals


def main():
    parser = argparse.ArgumentParser(description="Extract Audio Loudness & Energy Spikes")
    parser.add_argument("--audio-path", type=str, required=True, help="Path to 16kHz mono WAV file")
    parser.add_argument("--output-json", type=str, required=True, help="Path to write JSON output")
    args = parser.parse_args()

    audio_path = Path(args.audio_path)
    output_path = Path(args.output_json)

    if not audio_path.exists():
        print(f"Error: audio file {audio_path} does not exist", file=sys.stderr)
        sys.exit(1)

    try:
        signals = analyze_audio_energy(audio_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(signals, f, indent=2)
        print(f"Successfully extracted {len(signals)} audio energy points.")
    except Exception as e:
        print(f"Error during audio energy extraction: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
