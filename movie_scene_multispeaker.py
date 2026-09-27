"""
Movie Scene Mode — Multi-Speaker Test (standalone, does NOT modify app.py)

Tests up to 3 speakers in a single 10-second clip, sequential dialogue.
Demonstrates per-speaker timestamping and windowed voice extraction.

RUN (pipe the script into the container):
  Script preview only:
    Get-Content movie_scene_multispeaker.py | docker-compose exec -T api python - --script-only
  Full test (~120 credits for 3x10s clips):
    Get-Content movie_scene_multispeaker.py | docker-compose exec -T api python -
"""

import json
import os
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

# --- Reuse helpers from the main pipeline (read-only — nothing in app.py is changed) ---
from app import (
    OPENAI_API_KEY,
    OPENAI_MODEL,
    KIE_API_KEY,
    generate_clip,
    extract_last_frame,
    _download,
    _upload_to_kie,
    _run_ffmpeg,
    _ask_openai_json,
)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
CLIP_SECONDS = 5
RESOLUTION = "480p"
NUM_CLIPS = 3
OUTPUT_DIR = Path("/srv/media/movie_scene_multispeaker")

# ---------------------------------------------------------------------------
# Step 0 — preflight
# ---------------------------------------------------------------------------
def preflight():
    if not OPENAI_API_KEY:
        sys.exit("OPENAI_API_KEY is not set — set it in .env and rebuild")
    if not KIE_API_KEY:
        sys.exit("KIE_API_KEY is not set — set it in .env and rebuild")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / "clips").mkdir(exist_ok=True)
    (OUTPUT_DIR / "voices").mkdir(exist_ok=True)
    print("preflight ok", flush=True)

# ---------------------------------------------------------------------------
# Step 1 — OpenAI script generation (Multi-Speaker Schema)
# ---------------------------------------------------------------------------
MULTI_SCENE_SCRIPT_SCHEMA = {
    "type": "object",
    "properties": {
        "scene_bible": {
            "type": "object",
            "properties": {
                "characters": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "look": {"type": "string"},
                            "voice": {"type": "string"},
                        },
                        "required": ["name", "look", "voice"],
                        "additionalProperties": False,
                    },
                },
                "setting": {"type": "string"},
                "style": {"type": "string"},
            },
            "required": ["characters", "setting", "style"],
            "additionalProperties": False,
        },
        "clips": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "shot": {"type": "string"},
                    "dialogue": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "speaker": {"type": "string"},
                                "line": {"type": "string"},
                                "delivery": {"type": "string"},
                                "start_est": {"type": "number"},
                                "end_est": {"type": "number"}
                            },
                            "required": ["speaker", "line", "delivery", "start_est", "end_est"],
                            "additionalProperties": False
                        }
                    },
                    "others": {"type": "string"},
                },
                "required": ["shot", "dialogue", "others"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["scene_bible", "clips"],
    "additionalProperties": False,
}

def _multi_scene_system_prompt(num_clips: int, clip_duration: int) -> str:
    return f"""You write the shot-by-shot script for ONE scene of a short AI-generated drama.
The scene has multiple characters talking to each other sequentially.
It is split into {num_clips} consecutive clips of {clip_duration} seconds each.

Return a JSON object with two keys.

"scene_bible":
  - "characters": list of every character (name, look, voice).
  - "setting": the room, furniture, lighting.
  - "style": overall visual style.

"clips": exactly {num_clips} objects, each with:
  - "shot": the camera angle (e.g., Wide shot of the group, Over-the-shoulder).
    IMPORTANT: The FIRST clip MUST be a wide shot showing ALL characters' faces clearly.
  - "dialogue": a list of who speaks in this clip.
    RULES for dialogue:
    - Since the clip is only {clip_duration} seconds long, 1 or 2 speakers per clip is normal.
    - You can have UP TO 3 speakers sequentially in a single clip, but never more than 3.
    - People must speak SEQUENTIALLY. No overlapping speech.
    - Give a "start_est" and "end_est" (in seconds, 0.0 to {clip_duration}.0) for exactly when they speak.
    - Leave at least 0.5s of silence between speakers so they don't overlap.
    - TARGET WORDS: The total word count of ALL lines in this clip combined should be between {int(clip_duration * 1.6)} to {int(clip_duration * 2.4)} words (e.g., 8 to 12 words for a 5-second clip).
    - NO HARD CUTS: Sentences must be complete. The final speaker's line must finish naturally before the clip ends (e.g., "end_est" should be at least 0.2s before {clip_duration}.0). Never leave a character mid-sentence or mid-word at the end of a clip.
    - Example: [ {{"speaker": "Daniel", "line": "...", "start_est": 0.5, "end_est": 2.5}},
                 {{"speaker": "Priya", "line": "...", "start_est": 3.0, "end_est": 4.8}} ]
    - If nobody speaks (reaction shot), provide an empty array [].
  - "others": what non-speakers are doing.

Return strictly valid JSON matching the schema, and nothing else."""

def generate_multi_script(topic: str) -> dict:
    print("calling OpenAI for the multi-speaker script...", flush=True)
    prompt = _multi_scene_system_prompt(NUM_CLIPS, CLIP_SECONDS)
    script = _ask_openai_json(prompt, f"Topic: {topic}", "movie_multi_script", MULTI_SCENE_SCRIPT_SCHEMA)
    return script

# ---------------------------------------------------------------------------
# Step 2 — Prompt Builder with Timing Brackets
# ---------------------------------------------------------------------------
def build_multi_prompt(
    clip: dict,
    bible: dict,
    is_first: bool,
    voice_bank: dict[str, str],
    has_image_ref: bool,
) -> tuple[str, list[str]]:
    """Builds the prompt and returns the prompt string AND the ordered list of audio URLs to send."""
    chars_text = "; ".join(f"{c['name']} ({c['look']})" for c in bible["characters"])
    setting = bible["setting"].rstrip(".")
    style = bible["style"].rstrip(".")

    parts = []
    
    # Shot description
    if is_first:
        parts.append(f"{clip['shot']}. Characters: {chars_text}. {setting}. {style}. All characters' faces clearly visible and unobstructed.")
    else:
        if has_image_ref:
            parts.append(f"{clip['shot']}. Same characters and setting as @Image1. {style}.")
        else:
            parts.append(f"{clip['shot']}. {chars_text}. {setting}. {style}.")

    # Dialogue handling
    ref_audio_urls = []
    
    if not clip["dialogue"]:
        parts.append("Nobody speaks. Reaction shot.")
    else:
        for turn in clip["dialogue"]:
            spkr = turn["speaker"]
            char = next((c for c in bible["characters"] if c["name"].lower() == spkr.lower()), None)
            char_look = f" ({char['look']})" if char else ""
            
            # Check if this speaker is banked
            if spkr in voice_bank:
                # Add to the URL list if not already in it for this clip
                if voice_bank[spkr] not in ref_audio_urls:
                    ref_audio_urls.append(voice_bank[spkr])
                
                # The tag number corresponds to the 1-based index in the upload list
                audio_tag_idx = ref_audio_urls.index(voice_bank[spkr]) + 1
                voice_str = f"in the voice of @Audio{audio_tag_idx}"
            else:
                voice_str = char["voice"] if char else "a natural voice"
            
            # Format: [1.0s to 3.5s] Daniel (look...) speaks in the voice of @Audio1, delivery: "Line"
            timing = f"[{turn['start_est']}s to {turn['end_est']}s]"
            parts.append(f"{timing} {spkr}{char_look} speaks {voice_str}, {turn['delivery']}: \"{turn['line']}\"")

        parts.append("Natural lip sync to the dialogue.")

    if clip["others"]:
        parts.append(clip["others"] + ".")

    parts.append("No background music, no score.")
    
    # Cap to 3 audio references (Seedance Mini limit)
    if len(ref_audio_urls) > 3:
        print("  WARNING: Exceeded 3 audio references for one clip. Capping to first 3.", flush=True)
        ref_audio_urls = ref_audio_urls[:3]

    return " ".join(parts), ref_audio_urls

# ---------------------------------------------------------------------------
# Step 3 — Windowed Voice Trimming
# ---------------------------------------------------------------------------
def trim_windowed_voice(video_path: Path, speaker_name: str, start_est: float, end_est: float, clip_idx: int, turn_idx: int, dialogue_list: list) -> Path:
    """Extracts a speaker's voice by searching ONLY within a bounded window to prevent overlapping with others."""
    import numpy as np

    voice_path = OUTPUT_DIR / "voices" / f"{speaker_name.lower()}_c{clip_idx}_t{turn_idx}.wav"

    # Define tight search boundaries based on neighbors
    # E.g., if speaker 1 ends at 3.0, and speaker 2 starts at 3.5, search start for speaker 2 is max(3.0, 3.5 - 1.0) = 3.0
    prev_end = dialogue_list[turn_idx - 1]["end_est"] if turn_idx > 0 else 0.0
    next_start = dialogue_list[turn_idx + 1]["start_est"] if turn_idx < len(dialogue_list) - 1 else float(CLIP_SECONDS)
    
    search_start = max(prev_end, start_est - 1.0)
    search_end = min(next_start, end_est + 1.0)
    
    print(f"  [{speaker_name}] estimated: {start_est}s - {end_est}s | bounded search: {search_start}s - {search_end}s", flush=True)

    # Extract full audio to f32le
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(video_path), "-vn", "-ac", "1", "-ar", "16000", "-f", "f32le", "-"],
        capture_output=True,
    ).stdout
    x = np.frombuffer(raw, dtype=np.float32)
    if len(x) < 1600:
        return None

    frame = 320 # 20ms
    sr = 16000
    
    # Isolate the search window slices
    start_frame = int(search_start * sr) // frame
    end_frame = int(search_end * sr) // frame
    
    if end_frame <= start_frame:
        return None
        
    slices = x[start_frame * frame : end_frame * frame].reshape(-1, frame)
    
    rms = np.sqrt((slices ** 2).mean(axis=1))
    level = 20 * np.log10(rms + 1e-9)
    
    spectrum = np.abs(np.fft.rfft(slices * np.hanning(frame), axis=1))[:, 3:] + 1e-9
    flatness = np.exp(np.log(spectrum).mean(axis=1)) / spectrum.mean(axis=1)

    loudest = level.max()
    if loudest < -45:
        return None

    # Voiced: loud and tonal
    voiced = np.flatnonzero((level > loudest - 20) & (flatness < 0.25))
    if len(voiced) == 0:
        return None

    margin_slices = 4 # 80ms
    local_start = max(0, voiced[0] - margin_slices)
    local_end = min(len(slices), voiced[-1] + margin_slices + 1)
    
    abs_start_sec = search_start + (local_start * frame / sr)
    abs_end_sec = search_start + (local_end * frame / sr)
    
    print(f"  [{speaker_name}] actual voice found: {abs_start_sec:.2f}s - {abs_end_sec:.2f}s", flush=True)

    _run_ffmpeg(
        "-i", str(video_path),
        "-vn", "-ss", f"{abs_start_sec:.4f}", "-to", f"{abs_end_sec:.4f}",
        "-c:a", "pcm_s16le", str(voice_path),
    )

    return voice_path

# ---------------------------------------------------------------------------
# Step 4 — Assembly
# ---------------------------------------------------------------------------
def assemble_test_video(clip_paths: list[Path]) -> Path:
    final_path = OUTPUT_DIR / "final.mp4"
    
    probe_out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "stream=width,height,r_frame_rate",
         "-select_streams", "v:0", "-of", "json", str(clip_paths[0])],
        capture_output=True, text=True,
    )
    info = json.loads(probe_out.stdout)["streams"][0]
    width, height = info["width"], info["height"]
    fps = info["r_frame_rate"]

    norm_dir = OUTPUT_DIR / "norm"
    norm_dir.mkdir(exist_ok=True)
    norm_paths: list[Path] = []

    for i, src in enumerate(clip_paths):
        norm = norm_dir / f"clip{i + 1}_norm.mkv"
        _run_ffmpeg(
            "-i", str(src),
            "-filter_complex",
            f"[0:v]scale={width}:{height}:flags=lanczos,setsar=1,fps={fps},format=yuv420p[v];"
            f"[0:a]aformat=sample_fmts=s16:sample_rates=48000:channel_layouts=stereo,"
            f"afade=t=in:d=0.02,afade=t=out:st={CLIP_SECONDS - 0.1}:d=0.02[a]",
            "-map", "[v]", "-map", "[a]",
            "-c:v", "libx264", "-preset", "medium", "-crf", "16", "-c:a", "pcm_s16le",
            str(norm),
        )
        norm_paths.append(norm)

    listing = OUTPUT_DIR / "concat.txt"
    listing.write_text("".join(f"file '{p.as_posix()}'\n" for p in norm_paths), encoding="utf-8")

    part = OUTPUT_DIR / "final.part.mp4"
    _run_ffmpeg(
        "-f", "concat", "-safe", "0", "-i", str(listing),
        "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart",
        str(part),
    )
    part.replace(final_path)
    return final_path

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    args = sys.argv[1:]
    script_only = "--script-only" in args
    topic_parts = [a for a in args if not a.startswith("--")]
    topic = " ".join(topic_parts).strip()

    if not topic:
        topic = "Daniel, Priya, and Sara have a tense argument over coffee. Daniel says it has to stop. Priya agrees with him and asks Sara. Sara agrees with both of them."

    preflight()

    print(f"\nTopic: {topic}", flush=True)
    script = generate_multi_script(topic)
    bible = script["scene_bible"]
    clips = script["clips"]

    script_path = OUTPUT_DIR / "script.json"
    script_path.write_text(json.dumps(script, indent=2, ensure_ascii=False), encoding="utf-8")
    
    print("\nPROMPT PREVIEW (what would be sent to Seedance):", flush=True)
    for i, clip_data in enumerate(clips):
        prompt, _ = build_multi_prompt(clip_data, bible, is_first=(i == 0), voice_bank={}, has_image_ref=(i > 0))
        print(f"\n  Clip {i+1}:\n  {prompt}", flush=True)

    if script_only:
        print("\nSCRIPT-ONLY MODE — no kie.ai calls made. Remove --script-only to run.")
        return

    voice_bank: dict[str, str] = {}
    voice_local: dict[str, Path] = {}
    image_ref_url: str | None = None
    clip_video_paths: list[Path] = []

    for i, clip_data in enumerate(clips):
        clip_num = i + 1
        is_first = (i == 0)
        
        print(f"\n{'─'*60}\nCLIP {clip_num}/{NUM_CLIPS}", flush=True)
        
        prompt, ref_audio_urls = build_multi_prompt(
            clip_data, bible, is_first,
            voice_bank=voice_bank,
            has_image_ref=(image_ref_url is not None),
        )
        
        ref_image_urls = [image_ref_url] if image_ref_url and not is_first else None

        print(f"  PROMPT:\n  {prompt[:150]}...", flush=True)
        print(f"  AUDIO REFS: {len(ref_audio_urls)} sent", flush=True)

        t0 = time.time()
        print(f"  generating on kie.ai...", flush=True)
        result = generate_clip(
            prompt=prompt,
            resolution=RESOLUTION,
            duration=CLIP_SECONDS,
            reference_image_urls=ref_image_urls,
            reference_audio_urls=ref_audio_urls if ref_audio_urls else None,
            generate_audio=True,
        )
        elapsed = time.time() - t0
        print(f"  done in {elapsed:.0f}s | credits: {result.get('credits_consumed', '?')}", flush=True)

        clip_path = OUTPUT_DIR / "clips" / f"clip{clip_num}.mp4"
        _download(result["video_url"], clip_path)
        clip_video_paths.append(clip_path)

        if is_first:
            image_ref_url = extract_last_frame(result["video_url"])
            print(f"  image anchor extracted: {image_ref_url}", flush=True)

        # Trimming all speakers in this clip using windowed approach
        for t_idx, turn in enumerate(clip_data["dialogue"]):
            speaker = turn["speaker"]
            if speaker not in voice_local:
                print(f"  trimming {speaker}'s voice...", flush=True)
                voice_path = trim_windowed_voice(
                    clip_path, speaker, 
                    turn["start_est"], turn["end_est"], 
                    clip_num, t_idx, clip_data["dialogue"]
                )
                if voice_path and voice_path.exists():
                    voice_local[speaker] = voice_path
                    uploaded_url = _upload_to_kie(voice_path)
                    voice_bank[speaker] = uploaded_url
                    print(f"  {speaker} banked: {uploaded_url}", flush=True)
                else:
                    print(f"  WARNING: failed to isolate {speaker}", flush=True)

    final = assemble_test_video(clip_video_paths)
    print(f"\nTEST COMPLETE. Final video: {final}")
    print("Run these two lines in PowerShell to copy the video out:")
    print("  $cid = (docker-compose ps -q api).Trim()")
    print(f"  docker cp \"${{cid}}:{final}\" ./movie_multi_final.mp4")

if __name__ == "__main__":
    main()
