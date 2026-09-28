"""
Movie Scene Mode — Cast Bank Architecture (standalone, does NOT modify app.py)

RUN in PowerShell:
  $cid = (docker-compose ps -q api).Trim()
  docker cp movie_scene_multispeaker.py "${cid}:/srv/media/movie_scene_multispeaker.py"
  docker-compose exec api python /srv/media/movie_scene_multispeaker.py "Your plot here" --duration 120
"""

import json
import os
import re
import subprocess
import sys
import time
import uuid
import argparse
import urllib.request
import shutil
from pathlib import Path

# --- Reuse helpers from the main pipeline (read-only — nothing in app.py is changed) ---
sys.path.append(os.getcwd())
import app
app.KIE_MODEL = "bytedance/seedance-2-fast" # Override the model in memory for this run
from app import (
    OPENAI_API_KEY,
    KIE_API_KEY,
    KieError,
    generate_clip,
    _clip_input,
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
OUTPUT_DIR = Path("/srv/media/movie_scene_multispeaker")
SCRIPTS_DIR = Path("/srv/media/movie_scene_scripts")  # saved scripts; outside OUTPUT_DIR, which every run wipes
CLIPS_PER_CHAPTER = 6  # 30 seconds per batch
WORDS_PER_SECOND = 2.5  # speaking pace every line is timed at
MIN_WORDS, MAX_WORDS = int(CLIP_SECONDS * 1.6), int(CLIP_SECONDS * WORDS_PER_SECOND)  # per clip, all speakers together
MAX_VOICE_REFS = 3  # kie.ai takes at most 3 reference audios per request
VOICE_MIN_SECONDS, VOICE_MAX_SECONDS = 2.0, 4.9  # kie.ai rejects reference audio under 2 s; 3 x 4.9 s stays inside its 15 s total
SCRIPT_RETRIES = 2  # times OpenAI is asked to fix an outline or chapter that breaks the rules
VOICE_REUPLOAD_AFTER = 23 * 3600  # kie.ai deletes uploaded files after 24 h; older voice samples are uploaded again on --resume
AUDIO_RETRY_NOTE = "No background music, no singing, no humming: only the spoken dialogue and natural room sound."  # replaces "No background music." when a clip is retried after kie.ai's audio copyright filter

# ---------------------------------------------------------------------------
# Image Generation (FLUX)
# ---------------------------------------------------------------------------
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

# ---------------------------------------------------------------------------
# Step 0 — preflight
# ---------------------------------------------------------------------------
def preflight(fresh: bool):
    """A fresh video run starts from an empty output folder. --resume keeps it, and so does --script-only (it makes no files there)."""
    if not OPENAI_API_KEY: sys.exit("OPENAI_API_KEY is not set")
    if not KIE_API_KEY: sys.exit("KIE_API_KEY is not set")

    old_clips = sorted((OUTPUT_DIR / "clips").glob("clip_*.mp4")) if OUTPUT_DIR.exists() else []
    if fresh and OUTPUT_DIR.exists():
        if old_clips and input(f"\nThe output folder still has {len(old_clips)} paid clip(s) from an earlier run. A new run deletes them "
                               "(to continue that run instead, add --resume). Delete them and start fresh? [y/n]: ").strip().lower() != "y":
            sys.exit("Nothing was deleted or generated.")
        shutil.rmtree(OUTPUT_DIR)
    if not fresh and (OUTPUT_DIR / "norm").exists():
        shutil.rmtree(OUTPUT_DIR / "norm")  # joining cache, keyed by clip file name; rebuilt so a remade clip is never joined from a stale copy

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / "clips").mkdir(exist_ok=True)
    (OUTPUT_DIR / "voices").mkdir(exist_ok=True)
    (OUTPUT_DIR / "norm").mkdir(exist_ok=True)
    (OUTPUT_DIR / "requests").mkdir(exist_ok=True)  # exactly what each clip sent to kie.ai and got back

# ---------------------------------------------------------------------------
# Step 1 — OpenAI script generation (Schemas & Prompts)
# ---------------------------------------------------------------------------
def _outline_schema() -> dict:
    return {
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
                    "locations": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "id": {"type": "string", "description": "snake_case id of one physical place, e.g. 'bedroom'. One id per room, whatever the camera angle."},
                                "description": {"type": "string", "description": "The place's fixed look in one or two sentences."},
                                "image_prompt": {"type": "string", "description": "Text-to-image prompt for a wide, empty view of the place. NO PEOPLE."}
                            },
                            "required": ["id", "description", "image_prompt"],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["characters", "style", "locations"],
                "additionalProperties": False,
            },
            "beats": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "location_id": {"type": "string", "description": "The id of the listed location this clip happens in."},
                        "action": {"type": "string", "description": "The ONE main action or event of this clip, and who speaks."}
                    },
                    "required": ["location_id", "action"],
                    "additionalProperties": False,
                },
                "description": "One beat per clip, in order."
            }
        },
        "required": ["scene_bible", "beats"],
        "additionalProperties": False,
    }

def _chapter_schema(location_ids: list[str]) -> dict:
    return {
        "type": "object",
        "properties": {
            "clips": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "location_id": {"type": "string", "enum": location_ids, "description": "The Scene Bible location this clip is set in."},
                        "shot": {"type": "string", "description": "Camera angle and framing (e.g. 'Wide establishing shot', 'Over the shoulder')."},
                        "present_characters": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Names of characters physically visible in this specific clip (MAXIMUM 7)."
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
                    "required": ["location_id", "shot", "present_characters", "dialogue", "others"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["clips"],
        "additionalProperties": False,
    }

def _outline_prompt(topic: str, duration: int, total_clips: int) -> str:
    return f"""You are planning an AI drama scene that is exactly {duration} seconds long: {total_clips} clips of {CLIP_SECONDS} seconds each.
The user's story prompt is: {topic}

Return a JSON object with:
1. "scene_bible": The characters, locations, and visual style. NO NARRATORS ALLOWED.
   - ENSEMBLE RULE: If the user's prompt specifies an exact number of characters to use, you MUST strictly follow that limit. If no number is specified, invent a reasonable cast size.
   - CASTING RULE: Unless the user's prompt explicitly asks for a specific ethnicity, default the cast to Western, European, or British demographics.
   - STATIC BIBLE RULE: The "look" and "voice" fields MUST describe ONLY permanent, unchanging physical traits (e.g., 'tall, blue eyes, black suit', 'deep baritone'). DO NOT describe chronological changes, emotional arcs, or story events (do NOT say 'starts happy but ends crying'). Emotional acting instructions belong ONLY in the individual clips.
   - REALISM RULE: Every "image_prompt" MUST explicitly include photography keywords to ensure extreme photorealism (e.g., "Photorealistic, 8k, live-action movie still, shot on 35mm lens, detailed skin texture, cinematic lighting, NO CGI, NO plastic look").
   - LOCATIONS: every place the story uses, listed once ("id" in snake_case, e.g. 'bedroom', 'house_exterior'). A room is ONE location however many camera angles it is filmed from: never make separate locations for different angles of the same room. "description": its fixed look in one or two sentences (architecture, furniture, materials, colors, light), true for the whole story. "image_prompt": a text-to-image prompt for a wide, empty view of that place showing its key permanent features, with photography keywords for extreme photorealism (e.g., "Photorealistic, live-action movie still, shot on Arri Alexa, 8k, detailed textures, NO CGI, NO 3D render"). NO PEOPLE, and none of the story's props that get carried, moved or broken. Places in the same building must match each other (same architecture, era, materials, floor plan, and which floor each room is on), and an exterior must show that same building (a townhouse on a street has no driveway).
2. "beats": exactly {total_clips} beats in order, one per {CLIP_SECONDS}-second clip. Each beat has "location_id", the id of the place where the clip happens (every place any beat uses must be in "locations", including stairs, corridors, cars and exteriors), and "action", one sentence: the ONE main action or event of that clip, and who speaks. Keep every event from the user's story prompt, in its order, and the meaning of every line the user wrote for a character; add nothing that contradicts it.
   - PACING: give each part of the story the clips it needs. The set-up moves quickly; the parts with the most events (usually the confrontation and the climax) get the most clips, so no clip has to cram in several big actions. Every beat moves the story forward with a new action, line or reveal: never two beats of the same thing (no second clip of walking, no repeated kiss) and no padding. If the story has more events than clips, fold small moments into a neighbouring beat, never two big actions into one."""

def _speakers_so_far(clips: list) -> set[str]:
    return {t["speaker"].lower() for c in clips for t in c["dialogue"]}

def _chapter_beats(beats: list, chap_idx: int) -> tuple[int, list]:
    """The first clip number (1-based) of this chapter and the beats it covers."""
    start = chap_idx * CLIPS_PER_CHAPTER
    return start + 1, beats[start:start + CLIPS_PER_CHAPTER]

def _chapter_prompt(topic: str, chap_idx: int, total_chapters: int, beats: list, bible: dict, prev_clips: list) -> str:
    first, mine = _chapter_beats(beats, chap_idx)
    last = first + len(mine) - 1
    plan = "\n".join(f"{n}. [{b['location_id']}] {b['action']}" for n, b in enumerate(beats, 1))
    locations = "\n".join(f"- {loc['id']}: {loc['description']}" for loc in bible["locations"])
    bridge = ""
    if prev_clips:
        # The whole script so far, not just the last clips, so later chapters can't contradict or repeat earlier ones.
        bridge = "Everything filmed so far, in order. Continue straight on from the last clip, and never contradict or repeat any of it:\n"
        for n, c in enumerate(prev_clips, 1):
            bridge += f"Clip {n} | {c['location_id']} | on screen: {', '.join(c['present_characters']) or 'nobody (establishing shot)'}\n"
            for d in c['dialogue']:
                bridge += f"  {d['speaker']} ({d['delivery']}): \"{d['line']}\"\n"
            bridge += f"  Action: {c['others']}\n"
        bridge += f"\nStart clip {first} as a direct continuation of clip {first - 1}.\n"
    spoken = _speakers_so_far(prev_clips)
    not_yet = ", ".join(c["name"] for c in bible["characters"] if c["name"].lower() not in spoken) or "none"

    return f"""You are a world-class Hollywood cinematographer and screenwriter directing CHAPTER {chap_idx + 1} of {total_chapters}: clips {first} to {last} of the video.
The user's story prompt (the source of truth): {topic}
Scene Bible: {json.dumps(bible)}
The beat plan for the whole video, one beat per clip. Write ONLY clips {first} to {last}, one clip per beat, in order; the other beats show what comes before and after, so do not repeat earlier beats or jump ahead:
{plan}

{bridge}

You must generate EXACTLY {len(mine)} consecutive clips of {CLIP_SECONDS} seconds each. This is a high-stakes, deeply dramatic movie.

RULES for the clips:
- "location_id": the place its beat is set in (in [brackets] in the beat plan), one of these locations, and the same id for every camera angle inside the same place (every clip there is rendered from one fixed picture of it, so the room always looks the same):
{locations}
- CAMERA WORK: film it like a high-budget movie. Change the camera angle on every cut, never the same framing twice in a row, and choose each angle for what the moment needs: a wide or medium shot to set up a place or show movement, two-shots and over-the-shoulders for conversations, close-ups for key lines and reactions, low or high angles for power, tracking shots to follow someone. Keep screen direction consistent (the 180-degree rule: in a conversation each character stays on the same side of the frame across cuts). One clear camera move per clip (e.g., a slow push-in, a pan, a dolly), not several.
- ESTABLISHING SHOTS: only when the user's story asks for one, or the story jumps to a new place without showing anyone arrive. It shows an exterior location, has an empty "present_characters" array and NO dialogue. Keep them rare.
- ONE MAIN ACTION: each clip shows the one main action or event of its beat, something that plays out naturally in {CLIP_SECONDS} seconds (e.g., she slaps the papers onto his chest; he smashes the vase). Small supporting movement (breathing, glances, a gesture) is fine, but never pack several events into one clip. The dialogue plays during that action. Each clip starts where the previous one ended and adds something new, so it never drags.
- "shot": Describe the camera angle, movement, and cinematic lighting in extreme detail! (e.g., 'Low-angle intense close-up with dramatic shadows', 'Handheld shaky tracking shot'). Only what the camera sees: no symbolism or mood commentary (not 'making the home look small and hollow').
- "present_characters": exactly the characters visible in this framing, MAXIMUM SEVEN (7). A character whose point of view the camera takes is NOT visible. Spell names exactly as in the Scene Bible. Leave empty for establishing shots.
- "dialogue":
  - STRICT RULE: NO NARRATORS. Only characters in "present_characters" can speak.
  - FACES ON SCREEN: whenever a character speaks, their face must be clearly visible in the shot. Never give a line to someone seen from behind, out of focus, out of frame or off screen; never during an over-the-shoulder shot from behind the speaker or the speaker's own POV; never during a close-up of hands, objects or a body part. When two characters speak in the same clip, frame both faces (two-shot, profile two-shot, medium shot).
  - CONVERSATIONS, NOT MONOLOGUES: when two or more characters are on screen, a clip usually has a back-and-forth: a main line, then a short reply, reaction or interruption of 2 to 4 words from another visible character (e.g. 'Not now.', 'You're lying.', 'Please, just go.'), so no clip ends on a line left hanging. A character who is alone may say short, meaningful lines to themselves about what is happening, but never filler (no talking to objects, no describing their own actions).
  - PLAIN, EVERYDAY SPEECH: characters talk like real people in a modern film, in simple, common words and short sentences that anyone understands the first time they hear them. No formal, poetic or old-fashioned phrasing, no fancy vocabulary, no jargon (not 'solicitor' or 'northbound' but 'lawyer' or 'the last train'), and no semicolons.
  - NO LONG SILENCES: every clip with characters on screen has dialogue, {MIN_WORDS} to {MAX_WORDS} words in total across all speakers (about {WORDS_PER_SECOND:g} words per second). Only establishing shots are silent.
  - TIMING: "start_est" and "end_est" are seconds from the start of THIS clip (0 to {CLIP_SECONDS}), not of the whole video. Lines come in order and never overlap, with 0.2 to 0.5 s between speakers; the first line starts at 0.2 s or later and the last ends by {CLIP_SECONDS - 0.2:g} s. Each line's window is at least its word count divided by {WORDS_PER_SECOND:g} seconds long.
  - VOICE SAMPLES: characters who have not spoken yet: {not_yet}. The FIRST line each of them speaks is cut out of the clip and reused as that character's voice for the rest of the video, so it must be at least 5 words and 2 seconds long, spoken at normal conversational volume (not whispered, shouted, sobbed or breathless), and never a short reply.
  - "delivery": how the voice sounds: tone, volume, pace and emotion as heard (e.g., 'voice shaking with rage', 'cold, clipped and quiet').
  - STORY: keep the meaning of every line the user wrote for a character (quoted or described). Never write a line that contradicts the user's story or anything said or shown earlier (e.g. if a return is a surprise, nobody knew about it).
- "others": the visible acting and movement in this clip. SHOW EMOTIONS, NEVER NAME THEM: write what the face, eyes, mouth, hands, body and breathing do ('his chin trembles and his eyes fill with tears; he swallows hard'), never inner states or interpretation ('heartbreak overtakes him', 'he feels betrayed', 'imagining the reunion').
- CONTINUITY: people and props stay where the previous clip left them. Someone holding an object keeps holding it until a clip shows them put it down or drop it; broken things stay broken; nobody notices the same thing twice; the layout of the house stays the same.
Return strictly valid JSON matching the schema."""


# ---------------------------------------------------------------------------
# Chapter check — the rules above that code can verify; OpenAI is asked to fix any it breaks
# ---------------------------------------------------------------------------
_WORD = re.compile(r"[\w'’]+")
_NOT_NORMAL_VOLUME = re.compile(r"\b(whisper|shout|scream|yell|murmur)(s|ed|ing)?\b|\bsob(s|bed|bing)?\b|\bbreathless\b|\bbarely audible\b", re.I)
_INNER_STATE = re.compile(r"\b(feels?|feeling|reali[sz](e|es|ing)|heartbreak|devastation|emotionally|imagining|hinting)\b", re.I)

def _words(line: str) -> int:
    return len(_WORD.findall(line))

def _check_outline(outline: dict, total_clips: int) -> list[str]:
    bible, problems = outline["scene_bible"], []
    if len(outline["beats"]) != total_clips:
        problems.append(f"\"beats\" must have exactly {total_clips} entries (one per clip), not {len(outline['beats'])}")
    names = [c["name"].lower() for c in bible["characters"]]
    if not names or len(set(names)) != len(names):
        problems.append("the characters must have unique names")
    ids = [loc["id"] for loc in bible["locations"]]
    if not ids or len(set(ids)) != len(ids):
        problems.append("every location needs its own unique id, one per physical place")
    for n, b in enumerate(outline["beats"], 1):
        if b["location_id"] not in ids:
            problems.append(f"beat {n} happens in '{b['location_id']}', which is not in \"locations\": add that place to the locations (with its own description and image_prompt), or use the listed id of the place it means")
    return problems

def _check_chapter(clips: list, bible: dict, first_clip_number: int, beat_locations: list[str], spoken_before: set[str]) -> list[str]:
    names = {c["name"].lower() for c in bible["characters"]}
    spoken = set(spoken_before)
    problems = []
    if len(clips) != len(beat_locations):
        problems.append(f"the chapter must have exactly {len(beat_locations)} clips, one per beat, not {len(clips)}")
    for n, (clip, place) in enumerate(zip(clips, beat_locations), first_clip_number):
        if clip["location_id"] != place:
            problems.append(f"clip {n} is set in '{clip['location_id']}', but its beat happens in '{place}'")
    for n, clip in enumerate(clips, first_clip_number):
        present = {p.lower() for p in clip["present_characters"]}
        turns = clip["dialogue"]
        for p in clip["present_characters"]:
            if p.lower() not in names:
                problems.append(f"clip {n}: '{p}' is not a Scene Bible name (spell names exactly as in the bible)")
        if len(present) > 7:
            problems.append(f"clip {n}: {len(present)} characters on screen; the maximum is 7")
        for field in ("shot", "others"):
            m = _INNER_STATE.search(clip[field])
            if m:
                problems.append(f"clip {n}: \"{field}\" names an inner state ('{m.group(0)}'); describe what the face and body visibly do instead")
        if not present:
            if turns:
                problems.append(f"clip {n}: nobody is on screen (establishing shot), so it must have no dialogue")
            continue
        total = sum(_words(t["line"]) for t in turns)
        if not MIN_WORDS <= total <= MAX_WORDS:
            problems.append(f"clip {n}: {total} words of dialogue; every clip with characters on screen needs {MIN_WORDS} to {MAX_WORDS}")
        if len({t["speaker"].lower() for t in turns}) > MAX_VOICE_REFS:
            problems.append(f"clip {n}: more than {MAX_VOICE_REFS} different speakers; the maximum is {MAX_VOICE_REFS}")
        prev_end = 0.0
        for t in turns:
            who, words, span = t["speaker"], _words(t["line"]), t["end_est"] - t["start_est"]
            if who.lower() not in present:
                problems.append(f"clip {n}: {who} speaks but is not in present_characters (a speaker's face must be on screen)")
            if ";" in t["line"]:
                problems.append(f"clip {n}: {who}'s line has a semicolon; people don't talk like that, split it into short plain sentences")
            if not 0 <= t["start_est"] < t["end_est"] <= CLIP_SECONDS:
                problems.append(f"clip {n}: {who}'s line is timed {t['start_est']} to {t['end_est']} s; times are seconds inside this {CLIP_SECONDS} s clip")
            elif t["start_est"] < prev_end:
                problems.append(f"clip {n}: {who}'s line starts before the previous line ends")
            elif words > span * WORDS_PER_SECOND + 0.5:
                problems.append(f"clip {n}: {who}'s line has {words} words in {span:.1f} s; it needs at least {words / WORDS_PER_SECOND:.1f} s")
            prev_end = max(prev_end, t["end_est"])
            if who.lower() not in spoken:
                spoken.add(who.lower())
                if words < 5 or span < VOICE_MIN_SECONDS or _NOT_NORMAL_VOLUME.search(t["delivery"]):
                    problems.append(f"clip {n}: this is {who}'s first line, which becomes their voice sample: it needs at least 5 words, at least {VOICE_MIN_SECONDS:g} s, at normal volume (not whispered, shouted, sobbed or breathless)")
    return problems

def _canonical_names(clips: list, bible: dict) -> None:
    """Spell every name as the bible does, so the cast and voice banks (keyed by bible name) always match."""
    by_lower = {c["name"].lower(): c["name"] for c in bible["characters"]}
    for clip in clips:
        clip["present_characters"] = [by_lower.get(p.lower(), p) for p in clip["present_characters"]]
        for t in clip["dialogue"]:
            t["speaker"] = by_lower.get(t["speaker"].lower(), t["speaker"])

def _ask_checked(what: str, prompt: str, request: str, name: str, schema: dict, check) -> tuple[dict, list[str]]:
    """Ask OpenAI, check the answer, and ask it to fix what's wrong (up to SCRIPT_RETRIES times).
    Returns the answer and whatever problems are still left."""
    for attempt in range(SCRIPT_RETRIES + 1):
        data = _ask_openai_json(prompt, request, name, schema)
        problems = check(data)
        if not problems:
            break
        if attempt < SCRIPT_RETRIES:
            print(f"  {what} check: {len(problems)} rule problem(s), asking OpenAI to fix them (retry {attempt + 1}/{SCRIPT_RETRIES})...", flush=True)
            request = (
                "Here is your previous answer:\n" + json.dumps(data) + "\n\nIt breaks these rules:\n- " + "\n- ".join(problems)
                + "\n\nReturn the whole answer again with every one of these fixed, keeping everything else."
            )
    if problems:
        print(f"\n  ⚠ {what} still breaks {len(problems)} rule(s) after {SCRIPT_RETRIES} retries:")
        for p in problems:
            print(f"    - {p}")
    return data, problems

def write_outline(topic: str, duration: int, total_clips: int) -> tuple[dict, list[str]]:
    return _ask_checked("Outline", _outline_prompt(topic, duration, total_clips), "Generate Outline", "movie_outline",
                        _outline_schema(), lambda d: _check_outline(d, total_clips))

def write_chapter(topic: str, chap_idx: int, total_chapters: int, beats: list, bible: dict, prev_clips: list) -> tuple[dict, list[str]]:
    first, mine = _chapter_beats(beats, chap_idx)
    schema = _chapter_schema([loc["id"] for loc in bible["locations"]])
    data, problems = _ask_checked(
        f"Chapter {chap_idx + 1}", _chapter_prompt(topic, chap_idx, total_chapters, beats, bible, prev_clips), "Generate Script",
        f"movie_chapter_{chap_idx + 1}", schema,
        lambda d: _check_chapter(d["clips"], bible, first, [b["location_id"] for b in mine], _speakers_so_far(prev_clips)),
    )
    _canonical_names(data["clips"], bible)
    return data, problems

def save_script(path: Path, topic: str, bible: dict, beats: list, chapters: list) -> None:
    """Everything the video steps need, so --from-script can render exactly this script without asking OpenAI again."""
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {"version": 1, "topic": topic, "scene_bible": bible, "beats": beats, "chapters": chapters}
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

def _report(what: str, problems: list[str]) -> None:
    if problems:
        print(f"\n  ⚠ {what} breaks {len(problems)} rule(s):")
        for p in problems:
            print(f"    - {p}")

def build_multi_prompt(clip: dict, bible: dict, cast_bank: dict[str, str], location_bank: dict[str, str], voice_bank: dict[str, str]) -> tuple[str, list[str], list[str]]:
    loc_url = location_bank.get(clip["location_id"], "")
    ref_image_urls = [loc_url] if loc_url else []
    
    speakers = clip["present_characters"][:7]
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

    # One fixed picture per place: Seedance keeps the place's look from it but films it from this clip's own camera angle.
    loc = next((l for l in bible["locations"] if l["id"] == clip["location_id"]), None)
    shot = clip["shot"].rstrip(". ")
    if loc_url: setting = f"{shot}. The location is the place shown in @Image1: keep its architecture, furniture, materials, colors and light exactly the same, but film it from the camera angle described here, not the angle of the picture."
    else: setting = f"{shot}. Location: {loc['description'].rstrip('. ') if loc else clip['location_id']}."
    if speakers: parts.append(f"{setting} Characters: {tag_str}.")
    else: parts.append(f"{setting} Cinematic environmental shot, no people.")

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
            voice_url = voice_bank.get(spkr)
            if voice_url and voice_url not in ref_audio_urls and len(ref_audio_urls) < MAX_VOICE_REFS:
                ref_audio_urls.append(voice_url)
            if voice_url in ref_audio_urls:
                parts.append(f"[{turn['start_est']}s to {turn['end_est']}s] {spkr} speaks in the voice of @Audio{ref_audio_urls.index(voice_url) + 1}, {turn['delivery']}: \"{turn['line']}\"")
            else:
                parts.append(f"[{turn['start_est']}s to {turn['end_est']}s] {spkr} speaks {char['voice'] if char else 'naturally'}, {turn['delivery']}: \"{turn['line']}\"")
        faces = list(dict.fromkeys(t["speaker"] for t in clip["dialogue"]))
        who = faces[0] if len(faces) == 1 else ", ".join(faces[:-1]) + " and " + faces[-1]
        parts.append(f"{who} {'is' if len(faces) == 1 else 'are'} clearly visible on camera, face and lips in view, while speaking. Natural lip sync: each person's lips move only during their own line; everyone else keeps their mouth closed.")
    
    if clip["others"]: parts.append(clip["others"].rstrip(". ") + ".")
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
    start_frame, end_frame = int(search_start * sr) // frame, min(int(search_end * sr) // frame, len(x) // frame)
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
    if abs_end_sec - abs_start_sec < VOICE_MIN_SECONDS:
        return None  # kie.ai rejects it as a reference; the speaker's next line gets tried instead
    abs_end_sec = min(abs_end_sec, abs_start_sec + VOICE_MAX_SECONDS)
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

def _write_record(path: Path, record: dict) -> None:
    path.write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")

def render_clip(n: int, prompt: str, image_urls: list[str], audio_urls: list[str]):
    """Generate clip n on kie.ai, recording every request and reply in requests/clip_NN.json.
    A clip kie.ai refuses is retried once by itself (after the audio copyright filter, with stricter no-music wording);
    after that you choose: retry, skip the clip, or quit (everything made so far is kept for --resume).
    Returns kie.ai's reply, "skip" or "quit"."""
    record_path = OUTPUT_DIR / "requests" / f"clip_{n:02d}.json"
    old = json.loads(record_path.read_text(encoding="utf-8")) if record_path.exists() else {}
    record = {"attempts": old.get("attempts", [])}
    if "sent_to_kie" in old and "kie_reply" not in old and "attempts" not in old:  # written before failures were recorded
        record["attempts"].append({"sent_to_kie": old["sent_to_kie"], "error": "failed in an earlier run (no reply recorded)"})
    auto_retried = False
    while True:
        # The exact request body generate_clip() sends (same helper), saved before sending and again with kie.ai's reply.
        record["sent_to_kie"] = {"model": app.KIE_MODEL, "input": _clip_input(prompt, RESOLUTION, CLIP_SECONDS, True, None, audio_urls or None, image_urls or None)}
        _write_record(record_path, record)
        t0 = time.time()
        print(f"    generating on kie.ai... (request saved: {record_path})", flush=True)
        try:
            result = generate_clip(prompt=prompt, resolution=RESOLUTION, duration=CLIP_SECONDS, reference_image_urls=image_urls or None, reference_audio_urls=audio_urls or None, generate_audio=True)
        except Exception as e:
            record["attempts"].append({"sent_to_kie": record["sent_to_kie"], "error": str(e)})
            _write_record(record_path, record)
            print(f"    ✗ clip {n} failed: {e}", flush=True)
            if isinstance(e, KieError) and not auto_retried:  # kie.ai refused or failed the task; timeouts and network errors go straight to you
                auto_retried = True
                if "copyright" in str(e).lower() and prompt.endswith("No background music."):
                    prompt = prompt[:-len("No background music.")] + AUDIO_RETRY_NOTE
                    print("    retrying once with stricter no-music wording...", flush=True)
                else:
                    print("    retrying once...", flush=True)
                continue
            ans = ""
            while ans not in ("r", "s", "q"):
                ans = input(f"    Clip {n}: [r] retry  [s] skip it  [q] quit (everything made so far is kept for --resume): ").strip().lower()
            if ans == "r":
                continue
            return "skip" if ans == "s" else "quit"
        print(f"    done in {time.time() - t0:.0f}s | credits: {result.get('credits_consumed', '?')}", flush=True)
        record["kie_reply"] = result
        _write_record(record_path, record)
        return result

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("topic", nargs="*")
    parser.add_argument("--duration", type=int, default=15, help="Total requested video duration in seconds")
    parser.add_argument("--script-only", action="store_true")
    parser.add_argument("--from-script", help="Use a saved script (JSON) instead of asking OpenAI for a new one; its length replaces --duration")
    parser.add_argument("--resume", action="store_true", help="With --from-script: continue an interrupted run, keeping its clips, pictures and voice samples")
    args = parser.parse_args()
    if args.resume and (not args.from_script or args.script_only):
        sys.exit("--resume continues an interrupted video run: use it with --from-script (the same saved script) and without --script-only.")

    saved = None
    if args.from_script:
        if not os.path.isfile(args.from_script):
            sys.exit(f"Saved script not found in the container: {args.from_script}\nCopy it in first (docker cp), then run this again. Nothing was generated.")
        with open(args.from_script, "r", encoding="utf-8") as f:
            saved = json.load(f)
        topic = saved["topic"]
    else:
        topic = " ".join(args.topic).strip()
        if os.path.isfile(topic):
            with open(topic, "r", encoding="utf-8") as f:
                topic = f.read().strip()
        elif topic.endswith(".txt"):
            sys.exit(f"Story file not found in the container: {topic}\nCopy it in first (docker cp), then run this again. Nothing was sent to OpenAI.")

    if not topic: topic = "A tense dramatic conversation where three friends confront a fourth about a betrayal."
    print(f"\nStory: {topic[:150]}{'...' if len(topic) > 150 else ''}")

    total_clips = len(saved["beats"]) if saved else max(1, args.duration // CLIP_SECONDS)
    chapters_count = max(1, (total_clips + CLIPS_PER_CHAPTER - 1) // CLIPS_PER_CHAPTER)
    saved_chapters = saved["chapters"] if saved else []
    # Save every script this run writes (or completes), so it can be rendered again exactly with --from-script.
    script_path = None if len(saved_chapters) >= chapters_count else SCRIPTS_DIR / f"script_{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:4]}.json"

    if args.resume and not (OUTPUT_DIR / "requests" / "images.json").exists():
        sys.exit(f"Nothing to resume: {OUTPUT_DIR} has no run with pictures in it. Nothing was generated.")
    preflight(fresh=not args.script_only and not args.resume)

    print("\n=======================================================")
    print(f"[MASTER PLAN] Planning {total_clips} clips ({chapters_count} chapters)...")
    print("=======================================================")
    if saved:
        print(f"  Using the saved script {args.from_script}: its {len(saved_chapters)} chapter(s) are not rewritten by OpenAI.")
        outline_data = {"scene_bible": saved["scene_bible"], "beats": saved["beats"]}
        problems = _check_outline(outline_data, total_clips)
        _report("The saved plan", problems)
    else:
        outline_data, problems = write_outline(topic, args.duration, total_clips)
    bible = outline_data["scene_bible"]
    beats = outline_data["beats"]
    if script_path:
        save_script(script_path, topic, bible, beats, saved_chapters)
        print(f"  Script is being saved to {script_path}")

    if args.script_only:
        print("\n🎭 CAST BANK (FLUX Image Prompts):")
        for c in bible["characters"]:
            print(f"  - {c['name']} (Voice: {c['voice']})")
            print(f"    FLUX Prompt: {c['image_prompt']}")
        print("\n🏠 LOCATIONS (one fixed picture each, every camera angle in that place uses it):")
        for loc in bible["locations"]:
            print(f"  - {loc['id']}: {loc['description']}")
            print(f"    FLUX Prompt: {loc['image_prompt']}")
    print("\n📋 BEAT PLAN (one beat per clip):")
    for n, b in enumerate(beats, 1):
        print(f"  {n:02d}. [{b['location_id']}] {b['action']}")
    if problems and not args.script_only and input("\nContinue with this plan anyway? [y/n]: ").strip().lower() != "y":
        print("Stopped before anything was generated.")
        return

    cast_bank: dict[str, str] = {}
    location_bank: dict[str, str] = {}
    voice_bank: dict[str, str] = {}
    voice_local: dict[str, Path] = {}
    if args.resume:
        # Same pictures and voice samples as the interrupted run, so faces, rooms and voices match the clips already made.
        images = json.loads((OUTPUT_DIR / "requests" / "images.json").read_text(encoding="utf-8"))
        cast_bank = {name: v["url"] for name, v in images["cast"].items()}
        location_bank = {lid: v["url"] for lid, v in images["locations"].items()}
        mismatched = [c["name"] for c in bible["characters"] if images["cast"].get(c["name"], {}).get("prompt") != c["image_prompt"]]
        mismatched += [l["id"] for l in bible["locations"] if images["locations"].get(l["id"], {}).get("prompt") != l["image_prompt"]]
        if mismatched:
            sys.exit(f"The saved script's picture prompts for {', '.join(mismatched)} differ from the interrupted run's pictures, "
                     "so --resume would not match. Use the same saved script, or start a fresh run. Nothing was generated.")
        print(f"\n[RESUME] Reusing the interrupted run's {len(cast_bank)} cast and {len(location_bank)} place pictures.")
        voices_path = OUTPUT_DIR / "requests" / "voices.json"
        voices = json.loads(voices_path.read_text(encoding="utf-8")) if voices_path.exists() else {}
        for speaker, v in voices.items():
            wav = OUTPUT_DIR / "voices" / v["file"]
            voice_local[speaker] = wav
            if time.time() - v.get("uploaded_at", wav.stat().st_mtime) > VOICE_REUPLOAD_AFTER:
                v["url"], v["uploaded_at"] = _upload_to_kie(wav), time.time()  # kie.ai deletes uploads after 24 h
                print(f"  {speaker}'s voice sample was older than 23 h: uploaded again (same audio).")
            voice_bank[speaker] = v["url"]
            print(f"  Reusing {speaker}'s voice sample (from clip {v['from_clip']}: \"{v['line']}\").")
        voices_path.write_text(json.dumps(voices, indent=2, ensure_ascii=False), encoding="utf-8")
    elif not args.script_only:
        print("\n[PHASE 1.5] Generating cast and location images with FLUX...")
        for c in bible["characters"]:
            print(f"  Generating image for {c['name']}...", flush=True)
            cast_bank[c["name"]] = generate_flux_image(c["image_prompt"])
            if cast_bank[c["name"]]: print(f"    Saved: {cast_bank[c['name']]}")
        for loc in bible["locations"]:
            print(f"  Generating image for location {loc['id']}...", flush=True)
            location_bank[loc["id"]] = generate_flux_image(loc["image_prompt"])
            if location_bank[loc["id"]]: print(f"    Saved: {location_bank[loc['id']]}")
        images = {"cast": {c["name"]: {"prompt": c["image_prompt"], "url": cast_bank[c["name"]]} for c in bible["characters"]},
                  "locations": {l["id"]: {"prompt": l["image_prompt"], "url": location_bank[l["id"]]} for l in bible["locations"]}}
        (OUTPUT_DIR / "requests" / "images.json").write_text(json.dumps(images, indent=2, ensure_ascii=False), encoding="utf-8")
        missing = [name for name, url in (*cast_bank.items(), *location_bank.items()) if not url]
        if missing:
            print(f"\n  ⚠ No image for: {', '.join(missing)}. They would be drawn from text alone and change look from clip to clip.")
            if input("Continue anyway? [y/n]: ").strip().lower() != "y":
                print("Stopped before any video was generated.")
                return

    all_clip_video_paths = []
    resume_cmd = f"docker-compose exec api python /srv/media/movie_scene_multispeaker.py --from-script {args.from_script or script_path} --resume"

    all_clips_json = []
    chapters_json = list(saved_chapters)

    for chap_idx in range(chapters_count):
        chap_num = chap_idx + 1
        print(f"\n=======================================================")
        print(f"[CHAPTER {chap_num}/{chapters_count}] {'Saved script' if chap_idx < len(saved_chapters) else 'Generating AI Script...'}")
        print("=======================================================")

        if chap_idx < len(saved_chapters):
            script_data = {"clips": saved_chapters[chap_idx]}
            first, mine = _chapter_beats(beats, chap_idx)
            problems = _check_chapter(script_data["clips"], bible, first, [b["location_id"] for b in mine], _speakers_so_far(all_clips_json))
            _report(f"Saved chapter {chap_num}", problems)
        else:
            script_data, problems = write_chapter(topic, chap_idx, chapters_count, beats, bible, all_clips_json)
            chapters_json.append(script_data["clips"])
            save_script(script_path, topic, bible, beats, chapters_json)
        if problems and not args.script_only:
            if input(f"\nGenerate chapter {chap_num} anyway? [y/n]: ").strip().lower() != "y":
                print(f"Stopping before chapter {chap_num}; nothing was generated for it.")
                break
        all_clips_json.extend(script_data["clips"])
        
        if args.script_only:
            print("\n🎬 DIRECTOR'S CUT: SCRIPT & PROMPT PREVIEW")
            print("   (The real run sends this same text, except that the location, each character and each already-sampled voice")
            print("    point at their picture or voice sample: @Image1 for the place, @Image2+ for the cast, @Audio1+ for voices.)")
            print(f"\n🎥 SEEDANCE VIDEO CLIPS (Chapter {chap_num}):")
            for c_idx, clip_data in enumerate(script_data["clips"]):
                print(f"\n  ▶ CLIP {(chap_idx * CLIPS_PER_CHAPTER) + c_idx + 1:02d} | Location: {clip_data['location_id']}")
                print(f"    Shot Type: {clip_data['shot']}")
                prompt_str, _, _ = build_multi_prompt(clip_data, bible, {}, {}, {})
                print(f"    SEEDANCE PROMPT:\n    > {prompt_str}")
            
            if chap_num < chapters_count:
                input("\nPress Enter to generate script for next Chapter...")
            continue

        # --- Video Generation Phase ---
        batch_video_paths = []
        for c_idx_rel, clip_data in enumerate(script_data["clips"]):
            global_idx = (chap_idx * CLIPS_PER_CHAPTER) + c_idx_rel + 1
            if global_idx > total_clips: break # Safety cap
            
            loc_id = clip_data["location_id"]
            clip_path = OUTPUT_DIR / "clips" / f"clip_{global_idx:02d}.mp4"
            if args.resume and clip_path.exists():
                # Made and paid for before the interruption; its voice samples (if any) are already loaded from voices.json.
                print(f"\n  {'─'*40}\n  CLIP {global_idx}/{total_clips} (Location: {loc_id}): already made, reusing it", flush=True)
                batch_video_paths.append(clip_path)
                all_clip_video_paths.append(clip_path)
                continue
            print(f"\n  {'─'*40}\n  CLIP {global_idx}/{total_clips} (Location: {loc_id})", flush=True)
            prompt, ref_image_urls, ref_audio_urls = build_multi_prompt(clip_data, bible, cast_bank, location_bank, voice_bank)
            result = render_clip(global_idx, prompt, ref_image_urls, ref_audio_urls)
            if result == "skip":
                print(f"    clip {global_idx} skipped; it's left out of the video (a later --resume makes it again)", flush=True)
                continue
            if result == "quit":
                print(f"\nStopped. Everything made so far is kept in {OUTPUT_DIR}. To continue from clip {global_idx}:\n  {resume_cmd}")
                return

            _download(result["video_url"], clip_path)
            batch_video_paths.append(clip_path)
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
                        voices_path = OUTPUT_DIR / "requests" / "voices.json"
                        voices = json.loads(voices_path.read_text(encoding="utf-8")) if voices_path.exists() else {}
                        voices[speaker] = {"from_clip": global_idx, "line": turn["line"], "file": v_path.name, "url": uploaded_url, "uploaded_at": time.time()}
                        voices_path.write_text(json.dumps(voices, indent=2, ensure_ascii=False), encoding="utf-8")
                    else:
                        print(f"    no usable {VOICE_MIN_SECONDS:g}+ s voice sample in this line; trying {speaker}'s next line", flush=True)
        
        # Assemble batch review
        chap_review_filename = f"chapter_{chap_num}_review.mp4"
        assemble_test_video(batch_video_paths, chap_review_filename)
        
        if chap_num < chapters_count:
            print(f"\n=======================================================")
            print(f"CHAPTER {chap_num} COMPLETE!")
            print(f"Review video: docker cp \"${{cid}}:/srv/media/movie_scene_multispeaker/{chap_review_filename}\" .\\{chap_review_filename}")
            ans = input("\nContinue generating the next 30 seconds? [y/n]: ").strip().lower()
            if ans != 'y':
                print("Stopping generation early as requested.")
                print(f"The clips are kept. To continue later from clip {(chap_idx + 1) * CLIPS_PER_CHAPTER + 1}:\n  {resume_cmd}")
                break

    if not args.script_only and not all_clip_video_paths:
        print("\nNothing was generated.")
    elif not args.script_only:
        print("\n=======================================================")
        print("ASSEMBLING FINAL MASTER VIDEO...")
        final = assemble_test_video(all_clip_video_paths, "master_final.mp4")
        print(f"\nTEST COMPLETE. Final video: {final}")
        print("Run these two lines in PowerShell to copy the master video out:")
        print("  $cid = (docker-compose ps -q api).Trim()")
        print("  docker cp \"${cid}:/srv/media/movie_scene_multispeaker/master_final.mp4\" ./movie_master_final.mp4")

    if script_path:
        print("\n=======================================================")
        print(f"SCRIPT SAVED: {script_path}")
        print("To make the video from exactly this script (no new OpenAI script):")
        print(f"  docker-compose exec api python /srv/media/movie_scene_multispeaker.py --from-script {script_path}")
        print("To keep a copy on your PC:")
        print(f"  $cid = (docker-compose ps -q api).Trim(); docker cp \"${{cid}}:{script_path}\" .\\{script_path.name}")

if __name__ == "__main__":
    main()
