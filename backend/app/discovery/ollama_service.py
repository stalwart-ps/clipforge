import asyncio
import json
import re
from typing import Any, List
import httpx

from app.core.config import settings
from app.projects.schemas import CandidateClip, ClipSegment, EngagementSignals, TranscriptData, SceneCut


SYSTEM_PROMPT = """You are an elite short-form video producer (TikTok, YouTube Shorts, Instagram Reels).
Analyze the provided transcript segment and its audience engagement peaks (retention heatmap, comments, chat velocity, and audio hype screams).

{duration_instructions}
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

MULTI_SEGMENT_SYSTEM_PROMPT = """You are an elite short-form video producer (TikTok, YouTube Shorts, Instagram Reels).
Analyze the provided transcript segment and its audience engagement peaks (retention heatmap, comments, chat velocity, and audio hype screams).

{duration_instructions}
{custom_instructions}

{jump_cut_instructions}

Return valid JSON with a "clips" array where each object has:
- "title": Punchy, click-worthy hook title (no clickbait lies, max 8 words).
- "hook_summary": First 3 seconds hook summary explaining why viewers won't swipe away.
- "start_sec": Float timestamp where the clip starts (or start of first segment).
- "end_sec": Float timestamp where the clip ends (or end of last segment).
- "segments": Optional array of 2 to 4 segments [{{"start_sec": float, "end_sec": float, "label": "string"}}]. Omit or empty for continuous clips.
- "viral_score": Integer 1-100 estimating virality and retention.
- "reason": Why this moment is high value.
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
      "segments": [
        {{"start_sec": 0.0, "end_sec": 12.0, "label": "Setup"}},
        {{"start_sec": 24.0, "end_sec": 45.0, "label": "Payoff"}}
      ],
      "viral_score": 90,
      "reason": "string",
      "suggested_hashtags": ["#tag1", "#tag2"],
      "detected_mood": "string"
    }}
  ]
}}
"""

COMPILATION_SYSTEM_PROMPT = """You are an elite short-form video producer specializing in compilation and montage reels.
Review the following high-scoring candidate moments discovered across different parts of the video.

Propose up to 3 cross-video "Compilation / Story" clips stitching 2 to 5 thematically related moments from different parts of the video (e.g. funny fails montage, recurring joke, setup-and-payoff story arc).

Rules for each compilation clip:
- "segments": Array of 2 to 5 distinct non-overlapping segments [{{"start_sec": float, "end_sec": float, "label": "string"}}] selected from or refining the moments below.
- Each segment must have end_sec > start_sec + 2.0.
- Segments must be ordered chronologically without overlapping.
{compilation_duration_instructions}
- "viral_score": 1-100.

JSON Schema:
{{
  "compilations": [
    {{
      "title": "Punchy Compilation Title",
      "hook_summary": "Opening hook explaining the compilation theme",
      "segments": [
        {{"start_sec": 15.0, "end_sec": 30.0, "label": "Part 1"}},
        {{"start_sec": 120.0, "end_sec": 140.0, "label": "Part 2"}}
      ],
      "viral_score": 92,
      "reason": "Why these moments work together",
      "suggested_hashtags": ["#compilation", "#viral"],
      "detected_mood": "funny"
    }}
  ]
}}
"""


class OllamaClipDiscoveryEngine:
    @staticmethod
    def _strip_think_tags(text: str) -> str:
        """Strip any <think>...</think> reasoning traces from raw LLM responses before JSON parsing."""
        if not text:
            return ""
        # Strip completed <think>...</think> tags (case-insensitive, dotall for newlines)
        cleaned = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL | re.IGNORECASE)
        # Also strip unclosed <think> tag if the response was cut off mid-thought
        cleaned = re.sub(r"<think>.*$", "", cleaned, flags=re.DOTALL | re.IGNORECASE)
        return cleaned.strip()

    @classmethod
    def _parse_llm_json(cls, raw_response: str) -> dict:
        """Clean think tags and robustly parse JSON from raw Ollama response."""
        cleaned = cls._strip_think_tags(raw_response)
        if not cleaned:
            return {}
        try:
            return json.loads(cleaned)
        except Exception:
            # Fallback 1: Extract between outermost curly braces
            match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
            if match:
                try:
                    return json.loads(match.group(0))
                except Exception:
                    pass
            # Fallback 2: Extract from markdown code fence
            code_block_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", cleaned, flags=re.DOTALL)
            if code_block_match:
                try:
                    return json.loads(code_block_match.group(1))
                except Exception:
                    pass
        return {}

    @classmethod
    async def _post_generate(cls, client: httpx.AsyncClient, url: str, payload: dict) -> dict | None:
        """Send /api/generate request to Ollama, retrying without 'think' if rejected by older Ollama."""
        resp = await client.post(url, json=payload)
        if resp.status_code != 200 and "think" in payload:
            fallback_payload = dict(payload)
            del fallback_payload["think"]
            resp = await client.post(url, json=fallback_payload)
        if resp.status_code == 200:
            return resp.json()
        return None

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
        max_clips: int | None = None,
        custom_instructions: str = "",
        allow_multi_segment: bool = False,
        auto_duration: bool = True,
    ) -> tuple[list[CandidateClip], str | None]:
        url = f"{settings.ollama_url.rstrip('/')}/api/generate"
        total_duration = transcript.duration or (transcript.segments[-1].end if transcript.segments else 60.0)

        windows = cls._create_overlapping_windows(total_duration, window_sec=300.0, overlap_sec=60.0)
        all_candidate_clips: list[dict] = []

        custom_prompt_note = f"Special Creator Request: {custom_instructions}" if custom_instructions else ""

        if auto_duration:
            duration_instructions = (
                "Choose the natural story-complete length for each clip based on its meaning "
                "(complete hook → setup → punchline/takeaway; never cut mid-sentence and never pad dead air just to hit an arbitrary duration).\n"
                "- Aim for high-retention Shorts/Reels pacing: punchy moments can be 10–25s, standard highlights 25–60s, "
                "and strong complete stories/explanations can run 60–120s if every second holds attention (valid safety bounds: 6.0s to 150.0s)."
            )
            jump_cut_instructions = (
                "Optionally, you may create Jump-Cut clips by including a \"segments\" array containing 2 to 4 non-overlapping segments "
                "(each segment 5 to 45 seconds, combined natural story-complete duration up to 180 seconds) when cutting out middle filler/dead moments improves hook-to-payoff flow."
            )
        else:
            duration_instructions = (
                f"Identify the most compelling, self-contained, high-retention short clips strictly between {min_duration} and {max_duration} seconds."
            )
            jump_cut_instructions = (
                f"Optionally, you may create Jump-Cut clips by including a \"segments\" array containing 2 to 4 non-overlapping segments "
                f"(each segment 5 to 30 seconds, total combined duration strictly between {min_duration} and {max_duration} seconds) "
                "when cutting out middle filler/dead moments improves hook-to-payoff flow."
            )

        if allow_multi_segment:
            system_prompt_rendered = MULTI_SEGMENT_SYSTEM_PROMPT.format(
                duration_instructions=duration_instructions,
                custom_instructions=custom_prompt_note,
                jump_cut_instructions=jump_cut_instructions,
            )
        else:
            system_prompt_rendered = SYSTEM_PROMPT.format(
                duration_instructions=duration_instructions,
                custom_instructions=custom_prompt_note,
            )

        model_lower = (model_name or "").lower()
        is_reasoning_model = "qwen3" in model_lower or "r1" in model_lower

        try:
            # -------------------------------------------------------------
            # PASS 1: Window-based Candidate Discovery (with optional jump-cuts)
            # -------------------------------------------------------------
            for idx, (win_start, win_end) in enumerate(windows):
                is_final_window = (idx == len(windows) - 1)
                # Keep model in VRAM if Pass 2 (Compilation) will run; otherwise flush on final window
                keep_alive = "5m" if (allow_multi_segment or not is_final_window) else 0

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
                    # Live chat velocity
                    for pt in engagement.chat_velocity:
                        if win_start <= pt.time_sec <= win_end and pt.score >= 50.0:
                            signals_summary.append(f"- Live Chat Flood Spike at {pt.time_sec}s (Score: {pt.score}/100)")

                engagement_block = "\n".join(signals_summary) if signals_summary else "No external audience retention spikes in this section; evaluate transcript dialogue quality."

                prompt = f"""{system_prompt_rendered}

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
                if is_reasoning_model:
                    payload["think"] = False

                try:
                    async with httpx.AsyncClient(timeout=180.0) as client:
                        data = await cls._post_generate(client, url, payload)
                        if data:
                            response_text = data.get("response", "{}")
                            parsed = cls._parse_llm_json(response_text)
                            clips = parsed.get("clips", [])
                            for c in clips:
                                all_candidate_clips.append(c)
                except Exception as e:
                    print(f"Ollama request error for window {win_start}-{win_end}: {e}")

            # -------------------------------------------------------------
            # PASS 2: 2-Pass Cross-Video Compilations (when allow_multi_segment)
            # -------------------------------------------------------------
            if allow_multi_segment and len(all_candidate_clips) >= 2:
                try:
                    moments_lines = []
                    for i, c in enumerate(all_candidate_clips[:15]):
                        t = c.get("title", f"Moment {i + 1}")
                        s = float(c.get("start_sec", 0.0))
                        e = float(c.get("end_sec", s + 30.0))
                        hook = c.get("hook_summary", "")
                        mood = c.get("detected_mood", "")
                        moments_lines.append(f"- Moment #{i + 1}: \"{t}\" ({s:.1f}s - {e:.1f}s, mood: {mood}) - Hook: {hook}")

                    if auto_duration:
                        compilation_duration_instructions = (
                            "- Combined total duration: choose the natural story-complete length for each compilation based on its meaning "
                            "(complete hook → setup → punchline/takeaway; never cut mid-sentence and never pad dead air just to hit an arbitrary duration).\n"
                            "- Aim for high-retention Shorts/Reels pacing: punchy montages can be 10–25s, standard highlights 25–60s, "
                            "and strong complete story arcs can run 60–120s (up to 180.0s for multi-segment compilations) if every second holds attention."
                        )
                    else:
                        compilation_duration_instructions = (
                            f"- Combined total duration must strictly be between {min_duration} and {max_duration} seconds."
                        )

                    pass2_system = COMPILATION_SYSTEM_PROMPT.format(
                        compilation_duration_instructions=compilation_duration_instructions
                    )

                    pass2_prompt = f"""{pass2_system}

Candidate moments discovered across the video:
{chr(10).join(moments_lines)}
"""

                    pass2_payload = {
                        "model": model_name,
                        "prompt": pass2_prompt,
                        "format": "json",
                        "stream": False,
                        "options": {
                            "temperature": 0.4,
                        },
                        "keep_alive": 0,  # Flush model from VRAM on this final call
                    }
                    if is_reasoning_model:
                        pass2_payload["think"] = False

                    async with httpx.AsyncClient(timeout=180.0) as client:
                        data = await cls._post_generate(client, url, pass2_payload)
                        if data:
                            response_text = data.get("response", "{}")
                            parsed = cls._parse_llm_json(response_text)
                            compilations = parsed.get("compilations", [])
                            for comp in compilations[:3]:
                                if comp.get("segments") and len(comp.get("segments")) >= 2:
                                    all_candidate_clips.append(comp)
                except Exception as e:
                    print(f"Ollama Pass 2 Compilation request error: {e}")

        finally:
            try:
                # Guaranteed cleanup: explicitly flush model weights from VRAM to keep GPU memory free
                async with httpx.AsyncClient(timeout=10.0) as client:
                    await client.post(url, json={"model": model_name, "keep_alive": 0})
            except Exception:
                pass

        # -------------------------------------------------------------
        # Post-Processing: Snap boundaries and validate multi-segment clips
        # -------------------------------------------------------------
        processed_clips: list[CandidateClip] = []
        all_words = []
        for s in transcript.segments:
            for w in s.words:
                all_words.append(w)

        scene_cut_times = [sc.start_sec for sc in (scene_cuts or [])]

        for idx, raw_clip in enumerate(all_candidate_clips):
            try:
                raw_segments = raw_clip.get("segments")
                validated_segments: list[ClipSegment] = []

                if isinstance(raw_segments, list) and len(raw_segments) >= 2:
                    parsed_segs: list[tuple[float, float, str | None]] = []
                    for seg in raw_segments:
                        if not isinstance(seg, dict):
                            continue
                        s_start = float(seg.get("start_sec", 0.0))
                        s_end = float(seg.get("end_sec", 0.0))
                        if s_end > s_start + 2.0 and 0.0 <= s_start < total_duration and s_end <= total_duration + 1.0:
                            parsed_segs.append((s_start, s_end, seg.get("label")))

                    parsed_segs.sort(key=lambda x: x[0])

                    # Verify no overlaps
                    has_overlap = False
                    for i in range(len(parsed_segs) - 1):
                        if parsed_segs[i][1] > parsed_segs[i + 1][0]:
                            has_overlap = True
                            break

                    if not has_overlap and 2 <= len(parsed_segs) <= 8:
                        for s_start, s_end, s_label in parsed_segs:
                            # Snap segment to closest word boundaries if words available
                            if all_words:
                                closest_s = min(all_words, key=lambda w: abs(w.start - s_start))
                                if abs(closest_s.start - s_start) <= 2.0:
                                    s_start = closest_s.start
                                closest_e = min(all_words, key=lambda w: abs(w.end - s_end))
                                if abs(closest_e.end - s_end) <= 2.0 and closest_e.end > s_start + 1.8:
                                    s_end = closest_e.end

                            validated_segments.append(
                                ClipSegment(
                                    start_sec=round(s_start, 2),
                                    end_sec=round(s_end, 2),
                                    label=str(s_label) if s_label else None,
                                )
                            )

                if validated_segments:
                    start = validated_segments[0].start_sec
                    end = validated_segments[-1].end_sec
                    dur = round(sum(s.end_sec - s.start_sec for s in validated_segments), 2)
                    snapped_scene = False
                    # Check combined duration fits bounds
                    if auto_duration:
                        if dur < 6.0 or dur > 180.0:
                            continue
                    else:
                        if dur < min_duration or dur > max_duration:
                            continue
                else:
                    # Single continuous clip
                    start = float(raw_clip.get("start_sec", 0.0))
                    end = float(raw_clip.get("end_sec", start + 30.0))

                    # 1. Snap to nearest word start and end
                    if all_words:
                        closest_start = min(all_words, key=lambda w: abs(w.start - start))
                        if abs(closest_start.start - start) <= 2.5:
                            start = closest_start.start

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
                    if auto_duration:
                        if dur < 6.0 or dur > 150.0:
                            continue
                    else:
                        if dur < min_duration or dur > max_duration:
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
                        segments=validated_segments,
                    )
                )
            except Exception:
                continue

        # Sort by viral_score descending and deduplicate overlapping clips
        processed_clips.sort(key=lambda c: c.viral_score, reverse=True)
        deduped: list[CandidateClip] = []

        for clip in processed_clips:
            is_dup = False
            for existing in deduped:
                overlap_start = max(clip.start_sec, existing.start_sec)
                overlap_end = min(clip.end_sec, existing.end_sec)
                if overlap_end > overlap_start:
                    overlap_dur = overlap_end - overlap_start
                    if overlap_dur / min(max(1.0, clip.duration_sec), max(1.0, existing.duration_sec)) > 0.6:
                        if not clip.segments and not existing.segments:
                            is_dup = True
                            break
                        elif clip.segments and existing.segments:
                            if len(clip.segments) == len(existing.segments) and abs(clip.duration_sec - existing.duration_sec) < 3.0:
                                is_dup = True
                                break
            if not is_dup:
                deduped.append(clip)
            if max_clips is not None and len(deduped) >= max_clips:
                break

        total_found = len(processed_clips)
        strong = [c for c in deduped if c.viral_score >= 70]
        multi_count = sum(1 for c in deduped if len(c.segments) >= 2)
        multi_msg = f" (including {multi_count} multi-cut clips)" if multi_count > 0 else ""
        if max_clips is None:
            recommendation_summary = f"AI recommends {len(strong)} strong clips (score ≥ 70) out of {total_found} found{multi_msg}"
        else:
            recommendation_summary = f"AI evaluated {total_found} candidate clips: {len(strong)} strong (score ≥ 70), capped at {len(deduped)}{multi_msg}"

        return deduped, recommendation_summary
