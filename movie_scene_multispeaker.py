"""
Movie Scene Mode — Cast Bank Architecture (standalone, does NOT modify app.py)

RUN in PowerShell:
  $cid = (docker-compose ps -q api).Trim()
  docker cp movie_scene_multispeaker.py "${cid}:/srv/media/movie_scene_multispeaker.py"
  
  # Run for 30 seconds:
  docker-compose exec api python /srv/media/movie_scene_multispeaker.py "Ryan disrespects Walter..." --duration 30
"""

import json
import os
import subprocess
import sys
import time
import uuid
import argparse
import urllib.request
from pathlib import Path

sys.path.append(os.getcwd())
from app import (
    OPENAI_API_KEY,
    KIE_API_KEY,
    generate_clip,
    extract_last_frame,
    _download,
    _upload_to_kie,
    _run_ffmpeg,
    _ask_openai_json,
)

CLIP_SECONDS = 5
RESOLUTION = "480p"
OUTPUT_DIR = Path("/srv/media/movie_scene_multispeaker")

def generate_flux_image(prompt: str) -> str:
    url_create = "https://api.kie.ai/api/v1/jobs/createTask"
    headers = {"Authorization": f"Bearer {KIE_API_KEY}", "Content-Type": "application/json"}
    payload = {
        "model": "flux1-kontext",
        "input": {"prompt": prompt, "aspect_ratio": "16:9"}
    }
    try:
        req = urllib.request.Request(url_create, data=json.dumps(payload).encode("utf-8"), headers=headers)
        with urllib.request.urlopen(req) as response:
            resp = json.loads(response.read().decode("utf-8"))
            task_id = resp["data"]["taskId"]
        
        while True:
            time.sleep(3)
            url_poll = f"https://api.kie.ai/api/v1/jobs/recordInfo?taskId={task_id}"
            req2 = urllib.request.Request(url_poll, headers=headers)
            with urllib.request.urlopen(req2) as response2:
                status_resp = json.loads(response2.read().decode("utf-8"))
                data = status_resp.get("data", {})
                state = data.get("state")
                
                if state == "success":
                    result = json.loads(data["resultJson"])
                    return result["resultUrls"][0]
                elif state in ["fail", "error"]:
                    print(f"    [Error] FLUX generation failed: {data.get('failMsg')}")
                    return ""
    except Exception as e:
        print(f"    [Error] FLUX Image generation request failed: {e}")
        return ""

def preflight():
    if not OPENAI_API_KEY: sys.exit("OPENAI_API_KEY is not set")
    if not KIE_API_KEY: sys.exit("KIE_API_KEY is not set")
    
    import shutil
    if OUTPUT_DIR.exists():
        shutil.rmtree(OUTPUT_DIR)
        
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / "clips").mkdir(exist_ok=True)
    (OUTPUT_DIR / "voices").mkdir(exist_ok=True)
    (OUTPUT_DIR / "norm").mkdir(exist_ok=True)

def _get_schemas(total_clips):
    OUTLINE_SCHEMA = {
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
                                "image_prompt": {"type": "string", "description": "Highly detailed text-to-image prompt to generate this character's photo."}
                            },
                            "required": ["name", "look", "voice", "image_prompt"],
                            "additionalProperties": False,
                        },
                    },
                    "style": {"type": "string"},
                },
                "required": ["characters", "style"],
                "additionalProperties": False,
            },
        },
        "required": ["scene_bible"],
        "additionalProperties": False,
    }

    SCRIPT_SCHEMA = {
        "type": "object",
        "properties": {
            "clips": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "location_id": {"type": "string", "description": "Unique ID for this setting (e.g. 'office_lobby', 'restaurant')."},
                        "location_image_prompt": {"type": "string", "description": "Text-to-image prompt to generate the background room/environment. NO PEOPLE."},
                        "shot": {"type": "string", "description": "Camera angle and framing (e.g. 'Wide establishing shot', 'Over the shoulder')."},
                        "present_characters": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Names of characters physically visible in this specific clip (MAXIMUM 2)."
                        },
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
                    "required": ["location_id", "location_image_prompt", "shot", "present_characters", "dialogue", "others"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["clips"],
        "additionalProperties": False,
    }
    return OUTLINE_SCHEMA, SCRIPT_SCHEMA

def _outline_prompt(topic: str, duration: int) -> str:
    return f"""You are planning an AI drama scene that is exactly {duration} seconds long.
The user's story prompt is: {topic}

Return a JSON object with:
1. "scene_bible": The characters (name, look, voice), setting, and visual style. NO NARRATORS ALLOWED.
   - CASTING RULE: Unless the user's prompt explicitly asks for a specific ethnicity, default the cast to Western, European, or British demographics (names, appearances, and settings).
   - For each character, provide a highly detailed "image_prompt" that will be sent to FLUX to create their reference photo."""

def _script_prompt(topic: str, total_clips: int, bible: dict) -> str:
    return f"""You are a world-class Hollywood cinematographer and screenwriter directing a {total_clips * CLIP_SECONDS}-second scene.
Story Prompt: {topic}
Scene Bible: {json.dumps(bible)}

You must generate EXACTLY {total_clips} consecutive clips of {CLIP_SECONDS} seconds each. This is a high-stakes, deeply dramatic, emotional movie.

RULES for the clips:
- "location_id" and "location_image_prompt": Change scenes whenever the story naturally demands it. 
  - ESTABLISHING SHOTS: Whenever the story moves to a drastically new location (e.g., from an Office to a Hotel), the FIRST clip of that new location MUST be a cinematic exterior/environmental establishing shot (e.g., a drone shot of the hotel exterior at night). This clip must have an empty "present_characters" array and NO dialogue.
  - The image prompt MUST describe the mood, lighting (e.g., cinematic, moody, high-contrast), and atmosphere of the empty setting.
- "shot": Describe the camera angle, movement, and cinematic lighting in extreme detail! (e.g., 'Low-angle intense close-up with dramatic shadows', 'Handheld shaky tracking shot', 'Slow cinematic drone push-in').
- "present_characters": MAXIMUM TWO (2) CHARACTERS IN ANY GIVEN CLIP. Leave empty for establishing shots.
- "dialogue":
  - STRICT RULE: NO NARRATORS. Only characters physically in the scene can speak.
  - "delivery": Describe the exact, intense emotion (e.g., 'voice shaking with rage', 'cold, calculating whisper').
  - TARGET WORDS: {int(CLIP_SECONDS * 1.6)} to {int(CLIP_SECONDS * 2.4)} words per clip (if characters are speaking).
- "others": Describe the intense micro-expressions, body language, or environmental movement (e.g., 'wind blowing through trees', 'clenched fists').
Return strictly valid JSON matching the schema."""

def build_multi_prompt(clip: dict, bible: dict, cast_bank: dict[str, str], location_bank: dict[str, str], voice_bank: dict[str, str]) -> tuple[str, list[str], list[str]]:
    loc_url = location_bank.get(clip["location_id"], "")
    ref_image_urls = [loc_url] if loc_url else []
    
    speakers = clip["present_characters"][:2]
    char_tags = []
    for spkr in speakers:
        char_info = next((c for c in bible["characters"] if c["name"].lower() == spkr.lower()), None)
        if not char_info: continue
        if spkr in cast_bank and cast_bank[spkr]:
            ref_image_urls.append(cast_bank[spkr])
            img_idx = len(ref_image_urls)
            char_tags.append(f"{spkr} is @Image{img_idx} ({char_info['look']})")
        else:
            char_tags.append(f"{spkr} ({char_info['look']})")

    tag_str = ". ".join(char_tags)
    parts = []
    
    if speakers:
        if loc_url: parts.append(f"{clip['shot']}. The setting exactly matches @Image1. Characters: {tag_str}.")
        else: parts.append(f"{clip['shot']}. Setting: {clip['location_image_prompt']}. Characters: {tag_str}.")
    else:
        if loc_url: parts.append(f"{clip['shot']}. The setting exactly matches @Image1. Cinematic environmental shot, no people.")
        else: parts.append(f"{clip['shot']}. Setting: {clip['location_image_prompt']}. Cinematic environmental shot, no people.")

    ref_audio_urls = []
    if not clip["dialogue"]: 
        if speakers:
            parts.append("Nobody speaks. Intense silent acting and reaction shot.")
        else:
            parts.append("Nobody speaks. Atmospheric b-roll.")
    else:
        for turn in clip["dialogue"]:
            spkr = turn["speaker"]
            char = next((c for c in bible["characters"] if c["name"].lower() == spkr.lower()), None)
            if spkr in voice_bank:
                if voice_bank[spkr] not in ref_audio_urls: ref_audio_urls.append(voice_bank[spkr])
                parts.append(f"[{turn['start_est']}s to {turn['end_est']}s] {spkr} speaks in the voice of @Audio{ref_audio_urls.index(voice_bank[spkr]) + 1}, {turn['delivery']}: \"{turn['line']}\"")
            else:
                parts.append(f"[{turn['start_est']}s to {turn['end_est']}s] {spkr} speaks {char['voice'] if char else 'naturally'}, {turn['delivery']}: \"{turn['line']}\"")
        parts.append("Natural lip sync to the dialogue.")
    
    if clip["others"]: parts.append(clip["others"] + ".")
    parts.append("No background music.")
    return " ".join(parts), ref_image_urls, ref_audio_urls

def trim_windowed_voice(video_path: Path, speaker_name: str, start_est: float, end_est: float, turn_idx: int, dialogue_list: list) -> Path:
    import numpy as np
    voice_path = OUTPUT_DIR / "voices" / f"{speaker_name.lower()}_{uuid.uuid4().hex[:8]}.wav"
    prev_end = dialogue_list[turn_idx - 1]["end_est"] if turn_idx > 0 else 0.0
    next_start = dialogue_list[turn_idx + 1]["start_est"] if turn_idx < len(dialogue_list) - 1 else float(CLIP_SECONDS)
    search_start, search_end = max(prev_end, start_est - 1.0), min(next_start, end_est + 1.0)
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(video_path), "-vn", "-ac", "1", "-ar", "16000", "-f", "f32le", "-"], capture_output=True).stdout
    x = np.frombuffer(raw, dtype=np.float32)
    if len(x) < 1600: return None
    frame, sr = 320, 16000
    start_frame, end_frame = int(search_start * sr) // frame, int(search_end * sr) // frame
    if end_frame <= start_frame: return None
    slices = x[start_frame * frame : end_frame * frame].reshape(-1, frame)
    rms = np.sqrt((slices ** 2).mean(axis=1))
    level = 20 * np.log10(rms + 1e-9)
    spectrum = np.abs(np.fft.rfft(slices * np.hanning(frame), axis=1))[:, 3:] + 1e-9
    flatness = np.exp(np.log(spectrum).mean(axis=1)) / spectrum.mean(axis=1)
    loudest = level.max()
    if loudest < -45: return None
    voiced = np.flatnonzero((level > loudest - 20) & (flatness < 0.25))
    if len(voiced) == 0: return None
    margin_slices = 4
    local_start, local_end = max(0, voiced[0] - margin_slices), min(len(slices), voiced[-1] + margin_slices + 1)
    abs_start_sec, abs_end_sec = search_start + (local_start * frame / sr), search_start + (local_end * frame / sr)
    _run_ffmpeg("-i", str(video_path), "-vn", "-ss", f"{abs_start_sec:.4f}", "-to", f"{abs_end_sec:.4f}", "-c:a", "pcm_s16le", str(voice_path))
    return voice_path

def assemble_test_video(clip_paths: list[Path], output_filename: str) -> Path:
    if not clip_paths: return None
    final_path = OUTPUT_DIR / output_filename
    probe_out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=width,height,r_frame_rate", "-select_streams", "v:0", "-of", "json", str(clip_paths[0])], capture_output=True, text=True)
    info = json.loads(probe_out.stdout)["streams"][0]
    width, height, fps = info["width"], info["height"], info["r_frame_rate"]
    norm_dir = OUTPUT_DIR / "norm"
    norm_dir.mkdir(exist_ok=True)
    norm_paths = []
    for src in clip_paths:
        norm = norm_dir / f"norm_{src.name}.mkv"
        if not norm.exists():
            _run_ffmpeg("-i", str(src), "-filter_complex", f"[0:v]scale={width}:{height}:flags=lanczos,setsar=1,fps={fps},format=yuv420p[v];[0:a]aformat=sample_fmts=s16:sample_rates=48000:channel_layouts=stereo,afade=t=in:d=0.02,afade=t=out:st={CLIP_SECONDS - 0.1}:d=0.02[a]", "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-preset", "veryfast", "-crf", "16", "-c:a", "pcm_s16le", str(norm))
        norm_paths.append(norm)
    listing = OUTPUT_DIR / f"concat_{uuid.uuid4().hex[:6]}.txt"
    listing.write_text("".join(f"file '{p.as_posix()}'\n" for p in norm_paths), encoding="utf-8")
    part = OUTPUT_DIR / f"part_{output_filename}"
    _run_ffmpeg("-f", "concat", "-safe", "0", "-i", str(listing), "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(part))
    part.replace(final_path)
    return final_path

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("topic", nargs="*")
    parser.add_argument("--duration", type=int, default=15, help="Total requested video duration in seconds (must be multiple of 5)")
    parser.add_argument("--script-only", action="store_true")
    args = parser.parse_args()

    topic = " ".join(args.topic).strip()
    if os.path.isfile(topic):
        with open(topic, "r", encoding="utf-8") as f:
            topic = f.read()

    if not topic: topic = "A tense dramatic conversation where three friends confront a fourth about a betrayal."
    
    total_clips = max(1, args.duration // CLIP_SECONDS)
    preflight()
    OUTLINE_SCHEMA, SCRIPT_SCHEMA = _get_schemas(total_clips)

    print("\n=======================================================")
    print("[PHASE 1] Generating Cast Bible...")
    print("=======================================================")
    outline_data = _ask_openai_json(_outline_prompt(topic, args.duration), "Generate Outline", "movie_outline", OUTLINE_SCHEMA)
    bible = outline_data["scene_bible"]
    
    cast_bank: dict[str, str] = {}
    if not args.script_only:
        print("\n[PHASE 1.5] Generating Cast Images with FLUX...")
        for c in bible["characters"]:
            print(f"  Generating image for {c['name']}...", flush=True)
            img_url = generate_flux_image(c["image_prompt"])
            cast_bank[c['name']] = img_url
            if img_url: print(f"    Saved: {img_url}")

    print(f"\n=======================================================")
    print(f"[PHASE 2] Generating {total_clips}-Clip Script...")
    print("=======================================================")
    script_data = _ask_openai_json(_script_prompt(topic, total_clips, bible), "Generate Script", "movie_script", SCRIPT_SCHEMA)
    
    if args.script_only:
        print("\n=======================================================")
        print("🎬 DIRECTOR'S CUT: SCRIPT & PROMPT PREVIEW")
        print("=======================================================\n")
        
        print("🎭 CAST BANK (FLUX Image Prompts):")
        for c in bible["characters"]:
            print(f"  - {c['name']} (Voice: {c['voice']})")
            print(f"    Look: {c['look']}")
            print(f"    FLUX Prompt: {c['image_prompt']}\n")
            
        print("🌍 LOCATION SETS (FLUX Image Prompts):")
        seen_locs = set()
        for clip in script_data["clips"]:
            loc_id = clip["location_id"]
            if loc_id not in seen_locs:
                print(f"  - [{loc_id}]\n    FLUX Prompt: {clip['location_image_prompt']}\n")
                seen_locs.add(loc_id)
                
        print("🎥 SEEDANCE VIDEO CLIPS (Exact AI Prompts):")
        # Dummy banks just to show you how the prompt merges with the images
        dummy_cast = {c['name']: f"https://.../img_{c['name'].replace(' ', '_')}.jpg" for c in bible["characters"]}
        dummy_loc = {loc: f"https://.../bg_{loc}.jpg" for loc in seen_locs}
        
        for c_idx, clip_data in enumerate(script_data["clips"]):
            print(f"\n  ▶ CLIP {c_idx+1:02d} | Location: {clip_data['location_id']}")
            prompt_str, ref_imgs, _ = build_multi_prompt(clip_data, bible, dummy_cast, dummy_loc, {})
            print(f"    Shot Type: {clip_data['shot']}")
            if not clip_data["present_characters"]:
                print(f"    Cast on screen: NONE (Establishing Shot)")
            else:
                print(f"    Cast on screen: {', '.join(clip_data['present_characters'][:2])}")
            print(f"    SEEDANCE PROMPT:\n    > {prompt_str}")
        return

    all_clip_video_paths = []
    voice_bank: dict[str, str] = {}
    voice_local: dict[str, Path] = {}
    location_bank: dict[str, str] = {}
    
    for c_idx, clip_data in enumerate(script_data["clips"]):
        loc_id = clip_data["location_id"]
        if loc_id not in location_bank:
            print(f"\n  Generating new background image for location: {loc_id}...")
            bg_img_url = generate_flux_image(clip_data["location_image_prompt"])
            location_bank[loc_id] = bg_img_url
            if bg_img_url: print(f"    Saved: {bg_img_url}")
        
        print(f"\n  {'─'*40}\n  CLIP {c_idx+1}/{total_clips} (Location: {loc_id})", flush=True)
        prompt, ref_image_urls, ref_audio_urls = build_multi_prompt(clip_data, bible, cast_bank, location_bank, voice_bank)

        t0 = time.time()
        print(f"    generating on kie.ai...", flush=True)
        result = generate_clip(prompt=prompt, resolution=RESOLUTION, duration=CLIP_SECONDS, reference_image_urls=ref_image_urls if ref_image_urls else None, reference_audio_urls=ref_audio_urls if ref_audio_urls else None, generate_audio=True)
        print(f"    done in {time.time() - t0:.0f}s | credits: {result.get('credits_consumed', '?')}", flush=True)

        clip_path = OUTPUT_DIR / "clips" / f"clip_{c_idx+1:02d}.mp4"
        _download(result["video_url"], clip_path)
        all_clip_video_paths.append(clip_path)

        for t_idx, turn in enumerate(clip_data["dialogue"]):
            speaker = turn["speaker"]
            if speaker not in voice_local:
                print(f"    trimming {speaker}'s voice...", flush=True)
                v_path = trim_windowed_voice(clip_path, speaker, turn["start_est"], turn["end_est"], t_idx, clip_data["dialogue"])
                if v_path and v_path.exists():
                    voice_local[speaker] = v_path
                    uploaded_url = _upload_to_kie(v_path)
                    voice_bank[speaker] = uploaded_url

    print("\n=======================================================")
    print("ASSEMBLING FINAL MASTER VIDEO...")
    final = assemble_test_video(all_clip_video_paths, "master_final.mp4")
    print(f"\nTEST COMPLETE. Final video: {final}")
    print("Run these two lines in PowerShell to copy the master video out:")
    print("  $cid = (docker-compose ps -q api).Trim()")
    print("  docker cp \"${cid}:/srv/media/movie_scene_multispeaker/master_final.mp4\" ./movie_master_final.mp4")

if __name__ == "__main__":
    main()
