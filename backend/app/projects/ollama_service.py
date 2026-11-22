import asyncio
import json
import re
from typing import Any, List
import httpx

from app.core.config import settings
from app.projects.schemas import CandidateClip, EngagementSignals, TranscriptData, SceneCut


SYSTEM_PROMPT = """You are an elite short-form video producer (TikTok, YouTube Shorts, Instagram Reels).
Analyze the provided transcript segment and its audience engagement peaks (retention heatmap, comments, chat velocity, and audio hype screams).

Identify the most compelling, self-contained, high-retention short clips between {min_duration} and {max_duration} seconds.
{custom_instructions}

Return valid JSON with a "clips" array where each object has:
- "title": Punchy, click-worthy hook title (no clickbait lies, max 8 words).
- "hook_summary": First 3 seconds hook summary explaining why viewers won't swipe away.
- "start_sec": Float timestamp where the clip starts (must begin at a natural sentence start).
- "end_sec": Float timestamp where the clip ends (must resolve the thought/payoff).
- "viral_score": Integer 1-100 estimating virality and retention.
- "reason": Why this moment is high value (e.g. punchline, clutch gameplay, high emotion, key insight).
- "suggested_hashtags": Array of 3-5 relevant hashtags.
- "detected_mood": One of: "funny", "hype", "educational", "dramatic", "wholesome", "shocking".

JSON Schema:
{{
  "clips": [
    {{
      "title": "string",
      "hook_summary": "string",
      "start_sec": 0.0,
      "end_sec": 45.0,
      "viral_score": 90,
      "reason": "string",
      "suggested_hashtags": ["#tag1", "#tag2"],
      "detected_mood": "string"
    }}
  ]
}}
"""


class OllamaClipDiscoveryEngine:
    @staticmethod
    def _create_overlapping_windows(total_duration: float, window_sec: float = 240.0, overlap_sec: float = 60.0) -> list[tuple[float, float]]:
        if total_duration <= window_sec:
            return [(0.0, total_duration)]

        windows = []
        step = window_sec - overlap_sec
        curr = 0.0
        while curr < total_duration:
            end = min(total_duration, curr + window_sec)
            windows.append((curr, end))
            if end >= total_duration:
                break
            curr += step
        return windows

    @classmethod
    async def discover_clips(
        cls,
        transcript: TranscriptData,
        engagement: EngagementSignals | None,
        scene_cuts: list[SceneCut] | None,
        model_name: str = "qwen2.5:7b",
        min_duration: int = 15,
        max_duration: int = 60,
        max_clips: int = 5,
        custom_instructions: str = "",
    ) -> list[CandidateClip]:
        url = f"{settings.ollama_url.rstrip('/')}/api/generate"
        total_duration = transcript.duration or (transcript.segments[-1].end if transcript.segments else 60.0)

        windows = cls._create_overlapping_windows(total_duration, window_sec=300.0, overlap_sec=60.0)
        all_candidate_clips: list[dict] = []

        custom_prompt_note = f"Special Creator Request: {custom_instructions}" if custom_instructions else ""

        for idx, (win_start, win_end) in enumerate(windows):
            is_final_request = (idx == len(windows) - 1)
            # On final request, send keep_alive: 0 to flush model weights from VRAM immediately!
            keep_alive = 0 if is_final_request else "5m"

            # 1. Filter transcript segments in this window
            win_segments = [
                s for s in transcript.segments
                if (s.start <= win_end and s.end >= win_start)
            ]
            if not win_segments:
                continue

            transcript_text = "\n".join([
                f"[{round(s.start, 1)}s - {round(s.end, 1)}s]: {s.text}"
                for s in win_segments
            ])

            # 2. Filter engagement points in this window
            signals_summary = []
            if engagement:
                # Top heatmap peaks
                for pt in engagement.heatmap:
                    if win_start <= pt.time_sec <= win_end and pt.score >= 50.0:
                        signals_summary.append(f"- YouTube Retention Peak at {pt.time_sec}s (Score: {pt.score}/100)")
                # Top comments
                for pt in engagement.comment_timestamps:
                    if win_start <= pt.time_sec <= win_end and pt.score >= 40.0:
                        signals_summary.append(f"- Top Comment at {pt.time_sec}s: \"{pt.label}\" (Score: {pt.score}/100)")
                # Audio hype spikes
                for pt in engagement.audio_energy:
                    if win_start <= pt.time_sec <= win_end and pt.score >= 60.0:
                        signals_summary.append(f"- Audio Loudness/Reaction Spike at {pt.time_sec}s (Score: {pt.score}/100)")
                # Chat velocity
                for pt in engagement.chat_velocity:
                    if win_start <= pt.time_sec <= win_end and pt.score >= 50.0:
                        signals_summary.append(f"- Live Chat Flood Spike at {pt.time_sec}s (Score: {pt.score}/100)")

            engagement_block = "\n".join(signals_summary) if signals_summary else "No external audience retention spikes in this section; evaluate transcript dialogue quality."

            prompt = f"""{SYSTEM_PROMPT.format(min_duration=min_duration, max_duration=max_duration, custom_instructions=custom_prompt_note)}

Transcript Window ({round(win_start, 1)}s to {round(win_end, 1)}s):
{transcript_text}

Audience Engagement Signals:
{engagement_block}
"""

            payload = {
                "model": model_name,
                "prompt": prompt,
                "format": "json",
                "stream": False,
                "options": {
                    "temperature": 0.4,
                },
                "keep_alive": keep_alive,
            }

            try:
                async with httpx.AsyncClient(timeout=180.0) as client:
                    resp = await client.post(url, json=payload)
                    if resp.status_code == 200:
                        data = resp.json()
                        response_text = data.get("response", "{}")
                        parsed = json.loads(response_text)
                        clips = parsed.get("clips", [])
                        for c in clips:
                            all_candidate_clips.append(c)
            except Exception as e:
                # If Ollama is offline or model fails, continue
                print(f"Ollama request error for window {win_start}-{win_end}: {e}")

        # Post-Processing: Snap boundaries to word endpoints and scene cuts
        processed_clips: list[CandidateClip] = []
        all_words = []
        for s in transcript.segments:
            for w in s.words:
                all_words.append(w)

        scene_cut_times = [sc.start_sec for sc in (scene_cuts or [])]

        for idx, raw_clip in enumerate(all_candidate_clips):
            try:
                start = float(raw_clip.get("start_sec", 0.0))
                end = float(raw_clip.get("end_sec", start + 30.0))

                # 1. Snap to nearest word start and end
                if all_words:
                    # Find closest word start
                    closest_start = min(all_words, key=lambda w: abs(w.start - start))
                    if abs(closest_start.start - start) <= 2.5:
                        start = closest_start.start

                    # Find closest word end
                    closest_end = min(all_words, key=lambda w: abs(w.end - end))
                    if abs(closest_end.end - end) <= 2.5:
                        end = closest_end.end

                # 2. Snap to nearest PySceneDetect scene cut
                snapped_scene = False
                for sc_time in scene_cut_times:
                    if abs(sc_time - start) <= 1.2:
                        start = sc_time
                        snapped_scene = True
                    if abs(sc_time - end) <= 1.2:
                        end = sc_time
                        snapped_scene = True

                dur = round(end - start, 2)
                if dur < (min_duration - 2) or dur > (max_duration + 10):
                    continue

                processed_clips.append(
                    CandidateClip(
                        id=f"clip_{idx + 1}",
                        title=raw_clip.get("title", f"Clip #{idx + 1}"),
                        hook_summary=raw_clip.get("hook_summary", ""),
                        start_sec=round(start, 2),
                        end_sec=round(end, 2),
                        duration_sec=dur,
                        viral_score=int(raw_clip.get("viral_score", 70)),
                        reason=raw_clip.get("reason", "Interesting dialogue moment"),
                        suggested_hashtags=raw_clip.get("suggested_hashtags", ["#viral"]),
                        detected_mood=raw_clip.get("detected_mood", "hype"),
                        snapped_to_scene=snapped_scene,
                    )
                )
            except Exception:
                continue

        # Sort by viral_score descending and deduplicate overlapping clips
        processed_clips.sort(key=lambda c: c.viral_score, reverse=True)
        deduped: list[CandidateClip] = []

        for clip in processed_clips:
            # Check if overlaps > 70% with any already selected clip
            is_dup = False
            for existing in deduped:
                overlap_start = max(clip.start_sec, existing.start_sec)
                overlap_end = min(clip.end_sec, existing.end_sec)
                if overlap_end > overlap_start:
                    overlap_dur = overlap_end - overlap_start
                    if overlap_dur / min(clip.duration_sec, existing.duration_sec) > 0.6:
                        is_dup = True
                        break
            if not is_dup:
                deduped.append(clip)
            if len(deduped) >= max_clips:
                break

        return deduped
