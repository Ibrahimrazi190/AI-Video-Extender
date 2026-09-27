"""
Movie Scene Mode — Manual Test MS-1 (standalone, does NOT modify app.py)

6 clips × 5 seconds, 480p, seedance-2-mini.
4 characters at a café table discussing a breakup.

RUN (pipe the script into the container — the file is on the host, not in the image):

  Full test (generates video, costs ~150 kie.ai credits):
    Get-Content movie_scene_test.py | docker-compose exec -T api python -

  Script preview only (calls OpenAI only, no kie.ai credits):
    Get-Content movie_scene_test.py | docker-compose exec -T api python - --script-only
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
    extract_audio,
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
NUM_CLIPS = 6
OUTPUT_DIR = Path("/srv/media/movie_scene_test")

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
# Step 1 — OpenAI script generation (movie scene schema)
# ---------------------------------------------------------------------------

MOVIE_SCENE_SCRIPT_SCHEMA = {
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
                    "speaker": {"type": "string"},
                    "line": {"type": "string"},
                    "delivery": {"type": "string"},
                    "others": {"type": "string"},
                },
                "required": ["shot", "speaker", "line", "delivery", "others"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["scene_bible", "clips"],
    "additionalProperties": False,
}


def _movie_scene_system_prompt(num_clips: int, clip_duration: int) -> str:
    target_words = round(clip_duration * 2.0)  # slightly conservative for multi-char
    max_words = round(clip_duration * 2.4)
    return f"""You write the shot-by-shot script for ONE scene of a short AI-generated drama. \
The scene has multiple characters talking to each other — nobody looks at or speaks to the camera. \
It is split into {num_clips} consecutive clips of {clip_duration} seconds each. The user gives you the topic.

Return a JSON object with two keys.

"scene_bible": an object with three keys:
  - "characters": a list of every character in the scene, each with:
      "name": their first name,
      "look": a concrete physical description (age, build, hair color and length, face, clothing) — specific enough to \
identify them in any shot,
      "voice": how their speaking voice sounds (pitch, tone, timbre, for example "warm, low male voice" or "clear, \
slightly sharp female voice").
  - "setting": the room, furniture, lighting and key props, in one or two sentences.
  - "style": the overall visual style (for example "realistic cinematic, shallow depth of field, warm muted tones").

"clips": a list of exactly {num_clips} objects, in order, each with:
  - "shot": the camera angle and who is visible, in one sentence. \
Use standard film shot types: wide, medium, close-up, over-the-shoulder, reaction. \
IMPORTANT: the FIRST clip MUST be a wide or medium-wide establishing shot that shows EVERY character's face \
clearly visible and unobstructed — this shot becomes the visual identity reference for the entire scene. \
Later clips can be any shot type. Vary the shot types across clips for a cinematic feel (alternate close-ups \
of different speakers with wider group shots and reaction shots).
  - "speaker": the name of the ONE character who speaks in this clip, or "none" if nobody speaks (a reaction shot \
or a silent beat). At most one person speaks per clip — the camera cuts handle the back-and-forth, not \
multiple speakers in a single take.
  - "line": what the speaker says out loud, or "" if speaker is "none". \
Natural spoken dialogue between friends — not narration, not to camera. \
Aim for about {target_words} words and never exceed {max_words}. \
Spoken words only: no stage directions, no emojis, and no double quotation marks inside the line.
  - "delivery": a short phrase (3–8 words) describing how the line is said and the speaker's body language, \
for example "leaning forward, quiet disbelief" or "reaches across the table, warm and steady". \
If speaker is "none", describe the visible characters' actions and expressions instead.
  - "others": what the non-speaking characters are doing in this clip, in one sentence. \
For example "the others listen in silence" or "Amir nods slowly". Leave empty ("") if only the speaker is visible.

Rules:
- The dialogue across all clips must form ONE coherent, emotionally building conversation with a beginning, \
middle and end. Each line responds to or follows from the previous one.
- At most ONE character speaks per clip. Multi-speaker dialogue happens through camera cuts, not within one clip.
- Do NOT have anyone speak to the camera or narrate. This is characters talking to each other.
- At least one clip should be a silent reaction shot where no one speaks.
- The first clip MUST be a wide shot with all characters' faces clearly visible — this is a hard requirement.

Return strictly valid JSON matching the schema, and nothing else."""


def generate_movie_script(topic: str) -> dict:
    print("calling OpenAI for the movie scene script...", flush=True)
    prompt = _movie_scene_system_prompt(NUM_CLIPS, CLIP_SECONDS)
    script = _ask_openai_json(prompt, f"Topic: {topic}", "movie_scene_script", MOVIE_SCENE_SCRIPT_SCHEMA)
    clips = script["clips"]
    if len(clips) != NUM_CLIPS:
        raise ValueError(f"expected {NUM_CLIPS} clips, got {len(clips)}")
    if not script["scene_bible"]["characters"]:
        raise ValueError("no characters in scene_bible")
    return script


# ---------------------------------------------------------------------------
# Step 2 — build the Seedance prompt for each clip
# ---------------------------------------------------------------------------

def _characters_text(characters: list[dict]) -> str:
    """One-line per character: 'Name (look)' for embedding in prompts."""
    return "; ".join(f"{c['name']} ({c['look']})" for c in characters)


def _character_by_name(characters: list[dict], name: str) -> dict | None:
    for c in characters:
        if c["name"].lower() == name.lower():
            return c
    return None


def build_movie_prompt(
    clip: dict,
    bible: dict,
    is_first: bool,
    voice_bank: dict[str, str],
    has_image_ref: bool,
) -> str:
    """Build the Seedance prompt for one Movie Scene clip.

    References (@Image1, @Audio1) are only mentioned when they are actually sent.
    """
    chars_text = _characters_text(bible["characters"])
    setting = bible["setting"].rstrip(".")
    style = bible["style"].rstrip(".")

    shot = clip["shot"].rstrip(".")
    speaker_name = clip["speaker"]
    line = clip["line"]
    delivery = clip["delivery"].rstrip(".")
    others = clip["others"]

    parts: list[str] = []

    # Shot description
    if is_first:
        # First clip: full identity description, no references
        parts.append(
            f"{shot}. Characters at the table: {chars_text}. "
            f"{setting}. {style}. All characters' faces clearly visible and unobstructed."
        )
    else:
        # Later clips: reference the image anchor
        if has_image_ref:
            parts.append(
                f"{shot}. Same characters and setting as @Image1. {style}."
            )
        else:
            parts.append(f"{shot}. {chars_text}. {setting}. {style}.")

    # Speaker and dialogue
    if speaker_name.lower() != "none" and line:
        char = _character_by_name(bible["characters"], speaker_name)
        char_look = f" ({char['look']})" if char else ""

        # Voice description: use @Audio tag if banked, otherwise text
        audio_tag_index = None
        if speaker_name in voice_bank:
            # The audio reference is sent — which @Audio tag is it?
            # It's always @Audio1 since we send at most one audio ref per clip
            audio_tag_index = 1

        if audio_tag_index:
            parts.append(
                f"{speaker_name}{char_look} speaks in the voice of @Audio{audio_tag_index}, "
                f"{delivery}: \"{line}\""
            )
        else:
            voice_desc = char["voice"] if char else "a natural voice"
            parts.append(
                f"{speaker_name}{char_look} speaks in {voice_desc}, "
                f"{delivery}: \"{line}\""
            )

        parts.append("Natural lip sync to the dialogue.")
    else:
        # Reaction / silent beat
        parts.append(f"{delivery}.")

    # Others
    if others:
        parts.append(others + ".")

    # Anti-music
    parts.append("No background music, no score.")

    return " ".join(parts)


# ---------------------------------------------------------------------------
# Step 3 — per-speaker voice trimming (from one clip's audio)
# ---------------------------------------------------------------------------

def trim_speaker_voice(video_path: Path, speaker_name: str) -> Path:
    """Extract the full audio from a clip, find the speech region using energy detection,
    trim to just the speech, and save it locally. Returns the local WAV path.

    This is a simplified version of the energy/silence detector approach described
    in MOVIE_SCENE.md §5.1 — good enough for a manual test where each clip has
    at most one speaker.
    """
    import numpy as np

    voice_path = OUTPUT_DIR / "voices" / f"{speaker_name.lower()}_{uuid.uuid4().hex[:8]}.wav"

    # Extract full audio as mono 16kHz float32
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(video_path), "-vn", "-ac", "1", "-ar", "16000", "-f", "f32le", "-"],
        capture_output=True,
    ).stdout
    x = np.frombuffer(raw, dtype=np.float32)
    if len(x) < 1600:  # less than 0.1s
        print(f"  WARNING: no audio found for {speaker_name}, skipping voice trim", flush=True)
        return None

    sr = 16000
    frame = 320  # 20 ms
    n = len(x) // frame
    slices = x[:n * frame].reshape(n, frame)
    rms = np.sqrt((slices ** 2).mean(axis=1))
    level = 20 * np.log10(rms + 1e-9)

    # Spectral flatness to distinguish voice from breath/noise
    spectrum = np.abs(np.fft.rfft(slices * np.hanning(frame), axis=1))[:, 3:] + 1e-9
    flatness = np.exp(np.log(spectrum).mean(axis=1)) / spectrum.mean(axis=1)

    loudest = level.max()
    if loudest < -45:
        print(f"  WARNING: audio too quiet for {speaker_name}, skipping voice trim", flush=True)
        return None

    # Find voiced slices: loud enough and tonal (not breathy/noisy)
    voiced = np.flatnonzero((level > loudest - 20) & (flatness < 0.25))
    if len(voiced) == 0:
        print(f"  WARNING: no voiced segments found for {speaker_name}", flush=True)
        return None

    # Find the region from first voiced slice to last voiced slice, with a small margin
    margin_slices = 3  # ~60 ms margin
    start_slice = max(0, voiced[0] - margin_slices)
    end_slice = min(n, voiced[-1] + margin_slices + 1)
    start_sec = start_slice * frame / sr
    end_sec = end_slice * frame / sr

    print(f"  voice detected {start_sec:.2f}s – {end_sec:.2f}s ({end_sec - start_sec:.2f}s)", flush=True)

    # Trim the audio from the original video (at full quality, not from the float32 stream)
    _run_ffmpeg(
        "-i", str(video_path),
        "-vn", "-ss", f"{start_sec:.4f}", "-to", f"{end_sec:.4f}",
        "-c:a", "pcm_s16le", str(voice_path),
    )

    return voice_path


# ---------------------------------------------------------------------------
# Step 4 — assemble the final video from all clips
# ---------------------------------------------------------------------------

def assemble_test_video(clip_paths: list[Path]) -> Path:
    """Simple concat of all clip videos into one final MP4, scaled to a common size."""
    final_path = OUTPUT_DIR / "final.mp4"
    print(f"\nassembling {len(clip_paths)} clips into final video...", flush=True)

    # Probe the first clip for the target size
    probe_out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "stream=width,height,r_frame_rate",
         "-select_streams", "v:0", "-of", "json", str(clip_paths[0])],
        capture_output=True, text=True,
    )
    info = json.loads(probe_out.stdout)["streams"][0]
    width, height = info["width"], info["height"]
    fps = info["r_frame_rate"]

    # Prepare each clip: scale to common size, constant fps, audio trimmed to picture length
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
            f"afade=t=in:d=0.02,afade=t=out:st=4.9:d=0.02[a]",
            "-map", "[v]", "-map", "[a]",
            "-c:v", "libx264", "-preset", "medium", "-crf", "16", "-c:a", "pcm_s16le",
            str(norm),
        )
        norm_paths.append(norm)
        print(f"  normalized clip {i + 1}/{len(clip_paths)}", flush=True)

    # Concat
    listing = OUTPUT_DIR / "concat.txt"
    listing.write_text("".join(f"file '{p.as_posix()}'\n" for p in norm_paths), encoding="utf-8")

    part = OUTPUT_DIR / "final.part.mp4"
    _run_ffmpeg(
        "-f", "concat", "-safe", "0", "-i", str(listing),
        "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart",
        str(part),
    )
    part.replace(final_path)
    print(f"final video: {final_path}", flush=True)
    return final_path


# ---------------------------------------------------------------------------
# Main — run the full test
# ---------------------------------------------------------------------------

def main():
    # Parse args: everything that isn't a flag is the topic
    args = sys.argv[1:]  # argv[0] is '-' when piped
    script_only = "--script-only" in args
    topic_parts = [a for a in args if not a.startswith("--")]
    topic = " ".join(topic_parts).strip()

    if not topic:
        print("Usage:", flush=True)
        print('  Get-Content movie_scene_test.py | docker-compose exec -T api python - "YOUR TOPIC" --script-only', flush=True)
        print('  Get-Content movie_scene_test.py | docker-compose exec -T api python - "YOUR TOPIC"', flush=True)
        print("", flush=True)
        print("Example:", flush=True)
        print('  Get-Content movie_scene_test.py | docker-compose exec -T api python - "A woman tells her three friends about her husbands toxic behavior at a cafe" --script-only', flush=True)
        sys.exit(1)

    preflight()

    # ── 1. Generate the script ─────────────────────────────────────────────
    print(f"\nTopic: {topic}", flush=True)
    script = generate_movie_script(topic)
    bible = script["scene_bible"]
    clips = script["clips"]

    # Save the script for inspection
    script_path = OUTPUT_DIR / "script.json"
    script_path.write_text(json.dumps(script, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nscript saved to {script_path}", flush=True)

    # Print the script
    print(f"\n{'='*60}", flush=True)
    print("SCENE BIBLE", flush=True)
    print(f"{'='*60}", flush=True)
    print(f"  Setting: {bible['setting']}", flush=True)
    print(f"  Style:   {bible['style']}", flush=True)
    for c in bible["characters"]:
        print(f"  {c['name']:8s}  look: {c['look']}", flush=True)
        print(f"           voice: {c['voice']}", flush=True)

    for i, clip in enumerate(clips):
        print(f"\n--- Clip {i+1} ---", flush=True)
        print(f"  Shot:     {clip['shot']}", flush=True)
        print(f"  Speaker:  {clip['speaker']}", flush=True)
        print(f"  Line:     \"{clip['line']}\"", flush=True)
        print(f"  Delivery: {clip['delivery']}", flush=True)
        print(f"  Others:   {clip['others']}", flush=True)
    print(f"\n{'='*60}\n", flush=True)

    # Also preview what the prompts would look like
    print("PROMPT PREVIEW (what would be sent to Seedance):", flush=True)
    for i, clip_data in enumerate(clips):
        fake_bank = {}  # no voices banked yet in preview
        prompt = build_movie_prompt(clip_data, bible, is_first=(i == 0), voice_bank=fake_bank, has_image_ref=(i > 0))
        print(f"\n  Clip {i+1}: {prompt[:300]}{'...' if len(prompt) > 300 else ''}", flush=True)

    if script_only:
        print(f"\n{'='*60}", flush=True)
        print("SCRIPT-ONLY MODE — no kie.ai calls made, no credits spent.", flush=True)
        print("Run without --script-only to generate the actual videos.", flush=True)
        print(f"{'='*60}", flush=True)
        return

    # ── 2. Generate clips one by one ───────────────────────────────────────
    voice_bank: dict[str, str] = {}      # speaker_name -> uploaded kie.ai URL
    voice_local: dict[str, Path] = {}    # speaker_name -> local WAV path
    image_ref_url: str | None = None     # clip 1's last frame, uploaded to kie.ai
    clip_video_paths: list[Path] = []    # local paths for the final assembly

    for i, clip_data in enumerate(clips):
        clip_num = i + 1
        is_first = (i == 0)
        speaker = clip_data["speaker"]
        has_speaker = speaker.lower() != "none" and clip_data["line"]

        print(f"\n{'─'*60}", flush=True)
        print(f"CLIP {clip_num}/{NUM_CLIPS}", flush=True)
        print(f"  Shot:    {clip_data['shot']}", flush=True)
        print(f"  Speaker: {speaker} {'(banked ✓)' if speaker in voice_bank else '(text only)' if has_speaker else '(silent)'}", flush=True)
        print(f"  Line:    \"{clip_data['line']}\"", flush=True)

        # Build references
        ref_image_urls = None
        ref_audio_urls = None

        if not is_first and image_ref_url:
            ref_image_urls = [image_ref_url]

        if has_speaker and speaker in voice_bank:
            ref_audio_urls = [voice_bank[speaker]]

        # Build the prompt
        prompt = build_movie_prompt(
            clip_data, bible, is_first,
            voice_bank=voice_bank,
            has_image_ref=(ref_image_urls is not None),
        )
        print(f"\n  PROMPT:\n  {prompt[:200]}{'...' if len(prompt) > 200 else ''}", flush=True)

        # Log what references are being sent
        ref_summary = []
        if ref_image_urls:
            ref_summary.append("image: clip 1's last frame")
        if ref_audio_urls:
            ref_summary.append(f"audio: {speaker}'s banked voice")
        print(f"  REFS: {', '.join(ref_summary) or 'none'}", flush=True)

        # Generate the clip
        t0 = time.time()
        print(f"  generating on kie.ai...", flush=True)
        result = generate_clip(
            prompt=prompt,
            resolution=RESOLUTION,
            duration=CLIP_SECONDS,
            reference_image_urls=ref_image_urls,
            reference_audio_urls=ref_audio_urls,
            generate_audio=True,
        )
        elapsed = time.time() - t0
        print(f"  done in {elapsed:.0f}s | credits: {result.get('credits_consumed', '?')}", flush=True)
        print(f"  video: {result['video_url']}", flush=True)

        # Download the clip
        clip_path = OUTPUT_DIR / "clips" / f"clip{clip_num}.mp4"
        _download(result["video_url"], clip_path)
        clip_video_paths.append(clip_path)
        print(f"  saved to {clip_path}", flush=True)

        # ── Post-generation: extract references for later clips ───────────
        if is_first:
            # Extract last frame as the group identity anchor
            print(f"  extracting last frame (group identity anchor)...", flush=True)
            image_ref_url = extract_last_frame(result["video_url"])
            # Also save locally for inspection
            _run_ffmpeg(
                "-sseof", "-0.1", "-i", str(clip_path),
                "-frames:v", "1", "-q:v", "2",
                str(OUTPUT_DIR / "clip1_lastframe.png"),
            )
            print(f"  last frame uploaded: {image_ref_url}", flush=True)

        # Trim the speaker's voice and add to the voice bank
        if has_speaker and speaker not in voice_local:
            print(f"  trimming {speaker}'s voice for the voice bank...", flush=True)
            voice_path = trim_speaker_voice(clip_path, speaker)
            if voice_path and voice_path.exists():
                voice_local[speaker] = voice_path
                # Upload to kie.ai so it can be used as a reference
                uploaded_url = _upload_to_kie(voice_path)
                voice_bank[speaker] = uploaded_url
                print(f"  {speaker}'s voice banked: {uploaded_url}", flush=True)
            else:
                print(f"  WARNING: could not bank {speaker}'s voice", flush=True)
        elif has_speaker and speaker in voice_local:
            print(f"  {speaker}'s voice already banked, skipping trim", flush=True)

    # ── 3. Summary ─────────────────────────────────────────────────────────
    print(f"\n{'='*60}", flush=True)
    print("GENERATION COMPLETE", flush=True)
    print(f"{'='*60}", flush=True)
    print(f"  Clips generated: {len(clip_video_paths)}", flush=True)
    print(f"  Voice bank: {list(voice_bank.keys())}", flush=True)
    print(f"  Image ref:  {'yes' if image_ref_url else 'no'}", flush=True)

    for i, path in enumerate(clip_video_paths):
        speaker = clips[i]["speaker"]
        refs_used = []
        if i > 0 and image_ref_url:
            refs_used.append("image")
        if speaker in voice_bank and clips[i]["line"]:
            # Check if this clip actually used the banked voice
            # (voice is banked AFTER the clip where the speaker first speaks)
            first_speech_clip = next(
                (j for j, c in enumerate(clips[:i]) if c["speaker"].lower() == speaker.lower() and c["line"]),
                None,
            )
            if first_speech_clip is not None:
                refs_used.append(f"audio ({speaker})")
        print(f"  clip {i+1}: {path.name}  | speaker: {speaker:8s} | refs: {', '.join(refs_used) or 'none'}", flush=True)

    # ── 4. Assemble final video ────────────────────────────────────────────
    final = assemble_test_video(clip_video_paths)

    print(f"\n{'='*60}", flush=True)
    print("TEST MS-1 COMPLETE", flush=True)
    print(f"{'='*60}", flush=True)
    print(f"  Final video: {final}", flush=True)
    print(f"  Script:      {OUTPUT_DIR / 'script.json'}", flush=True)
    print(f"  Last frame:  {OUTPUT_DIR / 'clip1_lastframe.png'}", flush=True)
    print(f"  Voice bank:  {OUTPUT_DIR / 'voices'}/", flush=True)
    print(f"\n  Copy the final video out:", flush=True)
    print(f"    docker cp $(docker-compose ps -q api):{final} ./movie_scene_final.mp4", flush=True)
    print(f"\n  WHAT TO CHECK:", flush=True)
    print(f"  1. Do close-up characters look like the same people from the wide shot?", flush=True)
    print(f"  2. Does Sara's voice in her second clip sound like her first?", flush=True)
    print(f"  3. Are the text-only voices (Amir, Priya, Layla) distinct from each other?", flush=True)
    print(f"  4. Does the reaction shot have no dialogue or lip movement?", flush=True)
    print(f"  5. Does the café setting stay consistent across shots?", flush=True)
    print(f"  6. Does it feel like a real scene when watched straight through?", flush=True)


if __name__ == "__main__":
    main()
