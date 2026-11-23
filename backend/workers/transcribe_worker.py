"""
Isolated Transcription Worker using faster-whisper.
Runs in a separate process that terminates completely upon completion
to free 100% of GPU/CPU VRAM before Ollama or vision models run.
"""

import argparse
import json
from pathlib import Path
import shutil
import sys


def emit_progress(percent: float, message: str = ""):
    payload = {
        "type": "progress",
        "percent": round(percent, 1),
        "stage": "transcribing",
        "message": message,
    }
    print("PROGRESS:" + json.dumps(payload), flush=True)


def check_cuda_available() -> bool:
    try:
        import ctranslate2
        return "cuda" in ctranslate2.get_supported_devices()
    except Exception:
        return False


def main():
    parser = argparse.ArgumentParser(description="faster-whisper Transcription Worker")
    parser.add_argument("--audio-path", type=str, required=True)
    parser.add_argument("--output-json", type=str, required=True)
    parser.add_argument("--model-size", type=str, default="base")
    parser.add_argument("--device", type=str, default="auto", choices=["auto", "cuda", "cpu"])
    parser.add_argument("--compute-type", type=str, default="auto")
    parser.add_argument("--language", type=str, default=None)
    parser.add_argument("--translate", action="store_true", default=False)
    parser.add_argument("--hotwords", type=str, default=None)
    parser.add_argument("--initial-prompt", type=str, default=None)
    parser.add_argument("--use-whisperx", action="store_true", default=False)
    parser.add_argument("--batch-size", type=int, default=4, help="Batch size for BatchedInferencePipeline (safe for 6GB VRAM)")
    args = parser.parse_args()

    audio_path = Path(args.audio_path)
    output_path = Path(args.output_json)

    if not audio_path.exists():
        print(f"ERROR: Audio file not found: {audio_path}", file=sys.stderr, flush=True)
        sys.exit(1)

    emit_progress(5.0, f"Loading Whisper model ({args.model_size})...")

    # Determine device and compute type
    device = args.device
    if device == "auto":
        device = "cuda" if check_cuda_available() else "cpu"

    compute_type = args.compute_type
    if compute_type == "auto":
        compute_type = "float16" if device == "cuda" else "int8"

    try:
        from faster_whisper import WhisperModel, BatchedInferencePipeline

        # Load base model
        model = WhisperModel(
            args.model_size,
            device=device,
            compute_type=compute_type,
            download_root=str(Path.home() / ".cache" / "whisper"),
        )

        # Wrap in batched inference pipeline for high speed
        batched_model = BatchedInferencePipeline(model=model)

        emit_progress(20.0, "Transcribing with Silero VAD and word-level timestamps...")

        transcribe_kwargs = {
            "batch_size": args.batch_size,
            "word_timestamps": True,
            "vad_filter": True,
            "vad_parameters": dict(min_silence_duration_ms=500),
            "task": "translate" if args.translate else "transcribe",
        }

        if args.language and args.language != "auto":
            transcribe_kwargs["language"] = args.language

        if args.hotwords:
            transcribe_kwargs["hotwords"] = args.hotwords

        if args.initial_prompt:
            transcribe_kwargs["initial_prompt"] = args.initial_prompt

        segments_iter, info = batched_model.transcribe(str(audio_path), **transcribe_kwargs)

        duration = info.duration or 1.0
        segments = []

        for idx, seg in enumerate(segments_iter):
            word_list = []
            if seg.words:
                for w in seg.words:
                    word_list.append({
                        "word": w.word.strip(),
                        "start": round(w.start, 2),
                        "end": round(w.end, 2),
                        "confidence": round(w.probability, 2),
                    })

            segments.append({
                "id": idx,
                "start": round(seg.start, 2),
                "end": round(seg.end, 2),
                "text": seg.text.strip(),
                "words": word_list,
            })

            # Calculate progress based on timestamp
            pct = min(95.0, 20.0 + (seg.end / duration) * 75.0)
            emit_progress(pct, f"Transcribed {round(seg.end, 1)}s / {round(duration, 1)}s")

        result_data = {
            "language": info.language,
            "language_probability": round(info.language_probability, 2),
            "duration": round(duration, 2),
            "segments": segments,
        }

        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(result_data, f, indent=2)

        emit_progress(100.0, "Transcription complete!")
        print("COMPLETE:" + json.dumps({"segments_count": len(segments), "language": info.language}), flush=True)

    except Exception as e:
        print(f"ERROR: {str(e)}", file=sys.stderr, flush=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
