"""
Movie Scene Mode — Cast Bank Architecture (standalone, does NOT modify app.py)

Fully automated end-to-end execution:
Master Plan -> Clip 1 Script -> Clip 1 Video -> Clip 2 Script -> Clip 2 Video -> ... -> Final Master Video.
Use --interactive if you want manual review pauses between clips.

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
from typing import Optional

try:
    from langfuse import observe, get_client
except ImportError:
    def observe(*args, **kwargs):
        def decorator(f):
            return f
        return decorator
    def get_client():
        return None

# --- Reuse helpers from the main pipeline (read-only — nothing in app.py is changed) ---
sys.path.append(os.getcwd())
import app
app.KIE_MODEL = "bytedance/seedance-2-mini" # Override the model in memory for this run
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
CLIPS_PER_CHAPTER = 1  # 1 clip (5 seconds) per chapter: write script for clip, then generate video for clip, then next
WORDS_PER_SECOND = 2.5  # speaking pace every line is timed at
MIN_WORDS, MAX_WORDS = 6, 12  # per SPEECH clip, all speakers together
MAX_VOICE_REFS = 3  # kie.ai takes at most 3 reference audios per request
MAX_REF_IMAGES = 9  # kie.ai's limit for reference pictures per request (seedance-2-mini and -fast)
MAX_ON_SCREEN = 7  # characters visible (fully or partly) in one clip; 6-7 is for group and action scenes
PLACE_VIEWS = (2, 3)  # reference pictures per place: one wide master, the rest edited from it at other angles
MIN_STEP_SECONDS = 1.0  # shortest action step Seedance can visibly play; shorter moments get merged into a neighbour
VOICE_MIN_SECONDS, VOICE_MAX_SECONDS = 2.0, 4.9  # kie.ai rejects reference audio under 2 s; 3 x 4.9 s stays inside its 15 s total
SCRIPT_RETRIES = 2  # times OpenAI is asked to fix an outline or chapter that breaks the rules
VOICE_REUPLOAD_AFTER = 23 * 3600  # kie.ai deletes uploaded files after 24 h; older voice samples are uploaded again on --resume
AUDIO_RETRY_NOTE = "No background music, no singing, no humming: only the spoken dialogue and natural room sound."  # replaces "No background music." when a clip is retried after kie.ai's audio copyright filter
IN_FRAME = ["visible", "partly visible", "off screen", "has left"]
ON_SCREEN = ("visible", "partly visible")
POSTURES = ["standing", "walking", "sitting", "kneeling", "lying down", "crouching", "hovering", "floating"]

# ---------------------------------------------------------------------------
# Image Generation (FLUX)
# ---------------------------------------------------------------------------
@observe(name="generate_flux_image", as_type="span")
def generate_flux_image(prompt: str, input_image: str = "") -> str:
    """Text-to-image, or (with input_image) Kontext's edit mode, which keeps the input picture's content."""
    client = get_client()
    if client:
        try:
            client.update_current_span(metadata={"model": "flux1-kontext", "is_edit": bool(input_image)})
        except Exception:
            pass
    url_create = "https://api.kie.ai/api/v1/jobs/createTask"
    headers = {"Authorization": f"Bearer {KIE_API_KEY}", "Content-Type": "application/json"}
    payload = {
        "model": "flux1-kontext",
        "input": {
            "prompt": prompt,
            "aspect_ratio": "9:16",
            "nsfw_checker": False,
        }
    }
    if input_image:
        payload["input"]["input_image"] = input_image
    try:
        req = urllib.request.Request(url_create, data=json.dumps(payload).encode("utf-8"), headers=headers)
        with urllib.request.urlopen(req) as response:
            resp = json.loads(response.read().decode("utf-8"))
            task_id = resp["data"]["taskId"]
        if client:
            try:
                client.update_current_span(metadata={"task_id": task_id})
            except Exception:
                pass

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
                    url = result["resultUrls"][0]
                    if client:
                        try:
                            client.update_current_span(metadata={"state": "success", "result_url": url})
                        except Exception:
                            pass
                    return url
                elif state in ["fail", "error"]:
                    msg = data.get("failMsg")
                    print(f"    [Error] FLUX generation failed: {msg}")
                    if client:
                        try:
                            client.update_current_span(level="ERROR", status_message=str(msg))
                        except Exception:
                            pass
                    return ""
    except Exception as e:
        print(f"    [Error] FLUX Image generation request failed: {e}")
        if client:
            try:
                client.update_current_span(level="ERROR", status_message=str(e))
            except Exception:
                pass
        return ""

def _view_prompt(view: str) -> str:
    """Kontext edit prompt: the same empty place as the master picture, seen from another spot."""
    return (f"The same place as in the input picture, with exactly the same architecture, layout, furniture, materials, "
            f"colors and light, now seen {view}. Keep exactly the same pieces of furniture, the same number of each and in the same places: "
            f"add nothing, remove nothing. Empty, no people. Photorealistic, live-action movie still, NO CGI, NO 3D render.")

# ---------------------------------------------------------------------------
# Step 0 — preflight
# ---------------------------------------------------------------------------
def preflight(fresh: bool, interactive: bool = False):
    """A fresh video run starts from an empty output folder. --resume keeps it, and so does --script-only (it makes no files there)."""
    if not OPENAI_API_KEY: sys.exit("OPENAI_API_KEY is not set")
    if not KIE_API_KEY: sys.exit("KIE_API_KEY is not set")

    old_clips = sorted((OUTPUT_DIR / "clips").glob("clip_*.mp4")) if OUTPUT_DIR.exists() else []
    if fresh and OUTPUT_DIR.exists():
        if old_clips:
            if interactive:
                if input(f"\nThe output folder still has {len(old_clips)} paid clip(s) from an earlier run. A new run deletes them "
                         "(to continue that run instead, add --resume). Delete them and start fresh? [y/n]: ").strip().lower() != "y":
                    sys.exit("Nothing was deleted or generated.")
            else:
                print(f"\n[Auto] Clearing output folder containing {len(old_clips)} earlier clip(s) for a fresh run.")
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
                                "layout": {"type": "string", "description": "Fixed map of the place: every door, stair and window and the main furniture, each placed relative to the main entrance."},
                                "views": {"type": "array", "items": {"type": "string"}, "description": "2 or 3 camera viewpoints for the reference pictures; the first is the one image_prompt shows."},
                                "image_prompt": {"type": "string", "description": "Text-to-image prompt for a wide, empty view of the place from views[0]. NO PEOPLE."}
                            },
                            "required": ["id", "description", "layout", "views", "image_prompt"],
                            "additionalProperties": False,
                        },
                    },
                    "props": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "id": {"type": "string", "description": "snake_case id of ONE handled object, e.g. 'rose_vase'. Never clothing or shoes being worn."},
                                "description": {"type": "string", "description": "The prop's full fixed look, e.g. 'a clear glass vase filled with a large bouquet of red and white roses'."}
                            },
                            "required": ["id", "description"],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["characters", "style", "locations", "props"],
                "additionalProperties": False,
            },
            "beats": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "location_id": {"type": "string", "description": "The id of the listed location this clip happens in."},
                        "action": {"type": "string", "description": "The ONE main action or event of this clip, and who speaks."},
                        "speech": {"type": "boolean", "description": "true if someone speaks in this clip, false for a silent clip."}
                    },
                    "required": ["location_id", "action", "speech"],
                    "additionalProperties": False,
                },
                "description": "One beat per clip, in order."
            }
        },
        "required": ["scene_bible", "beats"],
        "additionalProperties": False,
    }

def _chapter_schema(location_ids: list[str], names: list[str], prop_ids: list[str]) -> dict:
    timed = lambda text_field: {
        "type": "object",
        "properties": {"start_est": {"type": "number"}, "end_est": {"type": "number"}, text_field: {"type": "string"}},
        "required": ["start_est", "end_est", text_field],
        "additionalProperties": False,
    }
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
                        "blocking": {
                            "type": "array",
                            "description": "The position diary: one entry for every character in this clip's place, on screen or not.",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "character": {"type": "string", "enum": names},
                                    "in_frame": {"type": "string", "enum": IN_FRAME},
                                    "position": {"type": "string", "description": "Where exactly they are at the START of the clip (0.0s), using the place's layout; for 'partly visible', which part the camera sees."},
                                    "posture": {"type": "string", "enum": POSTURES, "description": "Posture at the start of the clip (0.0s)."},
                                    "screen_profile": {"type": "string", "description": "2D screen-relative profile at START (0.0s), e.g. 'three_quarter_facing_screen_right', 'profile_facing_screen_left', 'frontal_facing_camera' ('none' if off-screen)."},
                                    "head_tilt": {"type": "string", "description": "Head tilt, roll, and vertical pitch at START (0.0s), e.g. 'tilted upward (chin raised, looking up at mid-air)', 'level at eye height', 'tilted downward (chin down, looking down at floor)', 'tilted slightly left' ('none' if off-screen)."},
                                    "eyeline": {"type": "string", "description": "Eye gaze direction at START (0.0s), e.g. 'looking across table at eye level toward screen-right', 'downward toward hands' ('none' if off-screen)."},
                                    "end_position": {"type": "string", "description": "Where exactly they are at the END of the clip (5.0s) (the same as position if they don't move); the next clip starts from here."},
                                    "end_posture": {"type": "string", "enum": POSTURES, "description": "Posture at the end of the clip (5.0s)."},
                                    "end_screen_profile": {"type": "string", "description": "2D screen-relative profile at END (5.0s), e.g. 'three_quarter_facing_screen_right' ('none' if off-screen)."},
                                    "end_head_tilt": {"type": "string", "description": "Head tilt, roll, and vertical pitch at END (5.0s), e.g. 'tilted upward (chin raised, looking up at mid-air)', 'level at eye height', 'tilted downward (chin down, looking down at floor)', 'tilted slightly left' ('none' if off-screen)."},
                                    "end_eyeline": {"type": "string", "description": "Eye gaze direction at END (5.0s), e.g. 'looking across table toward screen-right' ('none' if off-screen)."},
                                    "facing": {"type": "string", "description": "Which way they face / what they look at in 3D scene space."},
                                    "awareness": {"type": "string", "description": "What they have noticed so far that matters, e.g. 'has not noticed the door opening'."}
                                },
                                "required": [
                                    "character", "in_frame", "position", "posture",
                                    "screen_profile", "head_tilt", "eyeline",
                                    "end_position", "end_posture",
                                    "end_screen_profile", "end_head_tilt", "end_eyeline",
                                    "facing", "awareness"
                                ],
                                "additionalProperties": False,
                            },
                        },
                        "prop_state": {
                            "type": "array",
                            "description": "The prop diary: one entry for every prop that has appeared in the story so far, in frame or not.",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "prop_id": {"type": "string", "enum": prop_ids or ["(no props)"]},
                                    "holder": {"type": "string", "description": "The character holding or carrying it, or 'scene' if it rests somewhere."},
                                    "in_frame": {"type": "boolean", "description": "true only if the camera clearly sees it where the action happens; a distant or background prop is false."},
                                    "state": {"type": "string", "description": "Its condition and exactly where it is, e.g. 'intact, in his right hand behind his back'."}
                                },
                                "required": ["prop_id", "holder", "in_frame", "state"],
                                "additionalProperties": False
                            }
                        },
                        "action_steps": {"type": "array", "items": timed("action"), "description": "The clip's physical action in time order."},
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
                    "required": ["location_id", "shot", "blocking", "prop_state", "action_steps", "dialogue", "others"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["clips"],
        "additionalProperties": False,
    }

def _outline_prompt(topic: str, duration: int, total_clips: int) -> str:
    if total_clips <= 6:
        structure_directive = f"""   - DURATION-ADAPTIVE STRUCTURE (MICRO-DRAMA: {duration}s, {total_clips} CLIPS):
     This is a rapid, high-density single-scene drama. Do NOT waste clips on slow windups or generic walking.
     * Opening Beat (Beat 1): Immediate in medias res hook — jump straight into the inciting dilemma, statement, or dramatic disruption.
     * Escalation Beats (Beats 2 to {max(2, total_clips - 1)}): Rapid escalation — friction, moral pushback, revealing leverage/proof, tactical maneuver, or sudden magical/physical threat.
     * Final Beat (Beat {total_clips}): Decisive climax, irreversible commitment, punchline, or cliffhanger cutoff."""
    elif total_clips <= 18:
        p1_end = max(2, round(total_clips * 0.25))
        p2_end = max(p1_end + 2, round(total_clips * 0.75))
        structure_directive = f"""   - DURATION-ADAPTIVE STRUCTURE (MEDIUM DRAMA: {duration}s, {total_clips} CLIPS):
     Develop an escalating dramatic confrontation across a defined three-phase progression:
     * Phase 1 (Beats 1 to {p1_end}): Inciting Disruption — establish the core dilemma, immediate friction, or shock event.
     * Phase 2 (Beats {p1_end + 1} to {p2_end}): Deepening Stakes & Tactical Conflict — characters test tactics, reveal leverage/secrets, clash emotionally, or face rising obstacles. Every beat increases the pressure.
     * Phase 3 (Beats {p2_end + 1} to {total_clips}): The Breaking Point & Aftermath — the confrontation reaches its climax, an irreversible action or decision is taken, leading to the dramatic consequence or resolution."""
    else:
        seq_count = max(3, round(total_clips / 8))
        structure_directive = f"""   - DURATION-ADAPTIVE STRUCTURE (CINEMATIC MULTI-SEQUENCE FEATURE: {duration}s, {total_clips} CLIPS):
     This is an extended, feature-style cinematic film. Structure the {total_clips} clips into approximately {seq_count} distinct dramatic sequences (around 6-10 clips per sequence) across varied locations that build a complete feature narrative arc:
     * Progressive Narrative Arc:
       - Opening Sequence: Inciting incident, immediate disruption, and initial confrontation.
       - Rising Stakes & Movement: Characters must move, investigate, pursue, escape, or transition to new locations as stakes escalate (e.g. Discovery -> Flight & Pursuit -> Hidden Revelation -> Escalating Confrontation).
       - Climax & Resolution: The decisive physical/dramatic confrontation, resolution of the core conflict, and consequences.
     * Dynamic Location Progression: Do NOT trap characters in one room for the entire duration! Characters navigate progressive settings.
     * Sequence Transitions: Whenever transitioning to a major new setting, the first beat of that new place MUST be an exterior establishing shot to orient the audience before plunging into the interior drama."""

    return f"""You are planning an AI drama scene that is exactly {duration} seconds long: {total_clips} clips of {CLIP_SECONDS} seconds each.
The user's story prompt is: {topic}

Return a JSON object with:
1. "scene_bible": The characters, locations, props and visual style. NO NARRATORS ALLOWED.
   - ENSEMBLE RULE: If the user's prompt specifies an exact number of characters to use, you MUST strictly follow that limit. If no number is specified, invent a reasonable cast size.
   - CASTING RULE: Unless the user's prompt explicitly asks for a specific ethnicity, default the cast to Western, European, or British demographics.
   - STATIC BIBLE RULE: The "look" and "voice" fields MUST describe ONLY permanent, unchanging physical traits (e.g., 'tall, blue eyes, black suit', 'deep baritone'). DO NOT describe chronological changes, emotional arcs, or story events (do NOT say 'starts happy but ends crying'). Emotional acting instructions belong ONLY in the individual clips.
   - REALISM RULE: Every "image_prompt" MUST explicitly include photography keywords to ensure extreme photorealism (e.g., "Photorealistic, 8k, live-action movie still, shot on 35mm lens, detailed skin texture, cinematic lighting, NO CGI, NO plastic look").
   - LOCATIONS: every place the story uses, listed once ("id" in snake_case, e.g. 'bedroom', 'house_exterior'). A room is ONE location however many camera angles it is filmed from: never make separate locations for different angles of the same room. "description": its fixed look in one or two sentences (architecture, furniture, materials, colors, light), true for the whole story. Places in the same building must match each other (same architecture, era, materials, floor plan, and which floor each room is on), and an exterior must show that same building (a townhouse on a street has no driveway).
   - LAYOUT: for every location, a fixed map that every clip set there will follow: each door, staircase and window and the main furniture, placed relative to the main entrance (e.g. 'The only door is in the near-left corner and opens inward; the bed stands against the far wall facing the door, about four metres from it; bedside tables on both sides; wardrobes along the right wall'). For a hallway, say where each door is and where it leads; for an exterior, where the front door, steps and path are. State how many of each thing there are ('the only sofa', 'two doors', 'a single desk'), so nothing gets duplicated. Include every feature the story will use in that place (a hiding spot, a back door, a gap in a hedge, a curtain someone stands behind, the car someone drives off in). Characters' positions and camera placements will be described with this map, so be concrete.
   - VIEWS: for every location, 2 or 3 camera viewpoints for its reference pictures, all showing the place empty: the first is a wide view that shows the layout (the one "image_prompt" shows), the others look from other key spots (e.g. 'from beside the bed looking back at the door', 'from the doorway looking in').
   - "image_prompt": a text-to-image prompt for the first view, showing the layout's key permanent features, and ALWAYS naming, clearly visible, every feature the story uses in that place (the video model can only use what the picture shows: if someone slips out through a gap or a back door, the gap or door must be in the picture), with photography keywords for extreme photorealism (e.g., "Photorealistic, live-action movie still, shot on Arri Alexa, 8k, detailed textures, NO CGI, NO 3D render"). NO PEOPLE, and none of the story's props.
   - PROPS: every object that a character carries, picks up, sets down, uses, changes or breaks in the story (e.g. a vase of flowers, divorce papers, a suitcase, a gun), with a snake_case "id" and a full fixed "description" of how it looks (e.g. 'a clear glass vase filled with a large bouquet of red and white roses'). Not furniture, and not what characters wear: clothes, shoes, jewellery and glasses belong in the character's "look" (a coat only becomes a prop if it is taken off and handed over or left somewhere). One prop is one object, never 'two pairs of...' or 'their bags'. An empty list if there are none.
2. "beats": exactly {total_clips} beats in order, one per {CLIP_SECONDS}-second clip. Each beat has "location_id", the id of the place where the clip happens (every place any beat uses must be in "locations", including stairs, corridors, cars and exteriors), "action", one sentence: what happens in this clip and who speaks, and "speech": true if anyone speaks in this clip. Keep every event from the user's story prompt, in its order, and the meaning of every line the user wrote for a character; add nothing that contradicts it.
{structure_directive}
   - THE LAW OF STATE CHANGES (MANDATORY ANTI-STAGNATION RULE):
     Every single 5-second beat MUST produce an explicit, observable STATE CHANGE that advances the scene. A beat can NEVER leave the characters in the same emotional, informational, or spatial status quo as the previous beat.
     Each beat must achieve at least ONE of:
     (1) Emotional Shift: A character's psychological state visibly changes (e.g., from calm denial to defensive rage; from amused disbelief to trembling dread; from shock to defiance).
     (2) Informational Turn: A secret is spoken, a lie is exposed, an ultimatum is delivered, or a new fact changes the balance of power.
     (3) Physical / Spatial Turn: The physical dynamic changes (e.g., closing distance to intimidate, drawing an object/weapon, slamming a door, an entity fully materializing, an abrupt entrance or flight).
   - STRICT RULE: NO EVENT STRETCHING (ANTI-DILUTION RULE):
     Never dilute a single physical action or event emergence across multiple beats (e.g., NEVER plan Beat 1: an anomaly begins, Beat 2: the anomaly grows, Beat 3: a visitor finally steps out).
     Any appearance, transformation, arrival, or physical action MUST complete its full emergence within ONE clip (using active kinetic action steps), so the subsequent clip immediately advances into dialogue, emotional reaction, or direct confrontation.
   - DIALOGUE DENSITY & RAPID MULTI-TURN EXCHANGES (HIGH PACING):
     In conversational, negotiation, or confrontation scenes, do NOT restrict dialogue to one solitary line per 5 seconds! Keep the scene lively with snappy two-way dialogue exchanges (e.g. Speaker A asks or accuses; Speaker B retorts or reacts within the same clip, or delivers a punchy hook answered in the next). In a dialogue-heavy sequence of 10 to 15 clips, aim for 15 to 22 total dialogue turns across speakers so the scene feels fast, punchy, and alive rather than dragging out with long pauses.
   - NO DEAD-AIR IN DISCUSSION SCENES:
     Once a conversation or dramatic encounter begins, EVERY consecutive beat must be a SPEECH beat ("speech": true). Never insert random silent filler clips in the middle of an ongoing dialogue exchange. Silent clips ("speech": false) belong ONLY to exterior establishing shots, stealth/sneaking, or brief moments of physical paralysis/shock.
   - FLOWING CONVERSATIONS ACROSS CUTS: A conversation flows like one continuous take sliced into {CLIP_SECONDS}-second pieces. When characters exchange rapid dialogue, clip N can feature a quick two-turn exchange or end on a burning question, with clip N+1 picking up immediately from the exact same positions with the response.
   - SPEECH: make a beat silent ("speech": false) only when the user's story says nobody speaks there, or when talking would make no sense: someone sneaking, hiding or frozen in shock, a character alone with nothing meaningful to say, an establishing shot. Otherwise characters talk.
   - LOCATION CHANGES: Whenever the story transitions to a completely new building or major location, the VERY FIRST beat for that new location MUST be an Establishing Shot ("speech": false, "action": "A highly dynamic cinematic exterior establishing shot of the building, showing active life like passing road traffic, pedestrians walking, or shifting weather to set the mood and tell the viewer where the next scene takes place. Nobody from the main cast is visible.").
   - PACING: give each part of the story the clips it needs. The set-up moves quickly; the parts with the most events (usually the confrontation and the climax) get the most clips, so no clip has to cram in several big actions. Every beat moves the story forward with a new action, line or reveal: never two beats of the same thing (no second clip of walking, no repeated kiss) and no padding. If the story has more events than clips, fold small moments into a neighbouring beat, never two big actions into one.
   - PRIVACY AND EAVESDROPPING: when characters talk about something another character must not hear, the story first shows that character going somewhere they plausibly can't hear: out of the room, far into another area, into the shower, behind a closed door. If that character secretly overhears, they come back or sneak close only after the talk has started, and the speakers must still have a reason to believe they are alone (they saw them leave, a door closed, water is running). Nobody says a secret with the person it's about a couple of metres away where they just watched them go.
   - MOVEMENT IS AN ACTION: one character leaving and another arriving are two separate actions; give them separate beats, or start the beat after the first has already happened (e.g. 'with Sam already gone, the manager walks in'). A walk across a room, street or building takes real time, so a beat never asks for a long walk plus a conversation."""

def _speakers_so_far(clips: list) -> set[str]:
    return {t["speaker"].lower() for c in clips for t in c["dialogue"]}

def _chapter_beats(beats: list, chap_idx: int) -> tuple[int, list]:
    """The first clip number (1-based) of this chapter and the beats it covers."""
    start = chap_idx * CLIPS_PER_CHAPTER
    return start + 1, beats[start:start + CLIPS_PER_CHAPTER]

def _beat_line(n: int, b: dict) -> str:
    return f"{n}. [{b['location_id']}] [{'SPEECH' if b.get('speech', True) else 'SILENT'}] {b['action']}"

def _state_so_far(prev_clips: list) -> str:
    """Every character's and prop's last known state: the continuity a new chapter must start from."""
    people, props = {}, {}
    for n, c in enumerate(prev_clips, 1):
        for b in c.get("blocking", []):
            people[b["character"]] = (n, c["location_id"], b)
        for p in c.get("prop_state", []):
            props[p["prop_id"]] = (n, c["location_id"], p)
    lines = []
    if prev_clips:
        last_clip = prev_clips[-1]
        lines.append(f"  - Camera setup at end of clip {len(prev_clips)}: {last_clip.get('shot', 'standard framing')}")
    for name, (n, loc, b) in people.items():
        where = f"{b.get('end_posture', b['posture'])}, {b.get('end_position', b['position'])}"
        end_prof = b.get("end_screen_profile", b.get("screen_profile", "frontal"))
        end_tilt = b.get("end_head_tilt", b.get("head_tilt", "upright neutral"))
        end_eye = b.get("end_eyeline", b.get("eyeline", "looking forward"))
        lines.append(
            f"  - {name} (at the end of clip {n}, in {loc}, {b['in_frame']}): {where}; "
            f"screen_profile: {end_prof}; head_tilt: {end_tilt}; eyeline: {end_eye}; facing {b['facing']}; {b['awareness']}"
        )
    for pid, (n, loc, p) in props.items():
        lines.append(f"  - prop {pid} (as of clip {n}): held by {p['holder']}; {p['state']}")
    return "\n".join(lines)

def _chapter_prompt(topic: str, chap_idx: int, total_chapters: int, beats: list, bible: dict, prev_clips: list) -> str:
    first, mine = _chapter_beats(beats, chap_idx)
    last = first + len(mine) - 1
    clip_range_str = f"clips {first} to {last}" if first != last else f"clip {first}"
    beat_range_str = f"beats {first} to {last}" if first != last else f"beat {first}"
    clip_count_str = f"{len(mine)} consecutive clips" if len(mine) > 1 else "1 clip"
    plan = "\n".join(_beat_line(n, b) for n, b in enumerate(beats, 1))
    locations = "\n".join(f"- {loc['id']}: {loc['description']} LAYOUT: {loc.get('layout', '')}" for loc in bible["locations"])
    props = "\n".join(f"- {p['id']}: {p['description']}" for p in bible.get("props", [])) or "- (none)"
    bridge = ""
    if prev_clips:
        window_size = 3
        recent = prev_clips[-window_size:]
        recent_start = len(prev_clips) - len(recent) + 1
        if len(prev_clips) > window_size:
            bridge = f"Previous scene context: Clips 1 to {recent_start - 1} have already played out according to the beat plan above.\n"
            bridge += f"Recent filmed clips (clips {recent_start} to {first - 1}) for direct physical & dialogue continuity:\n"
        else:
            bridge = "Everything filmed so far, in order. Continue straight on from the last clip, and never contradict or repeat any of it:\n"
        for n, c in enumerate(recent, recent_start):
            bridge += f"Clip {n} | {c['location_id']} | on screen: {', '.join(c.get('present_characters', [])) or 'nobody (establishing shot)'}\n"
            for s in c.get("action_steps", []):
                bridge += f"  [{s['start_est']}s to {s['end_est']}s] {s['action']}\n"
            for d in c.get("dialogue", []):
                bridge += f"  {d['speaker']} ({d['delivery']}): \"{d['line']}\"\n"
            bridge += f"  Acting and sound: {c.get('others', '')}\n"
        state = _state_so_far(prev_clips)
        if state:
            bridge += f"\nCURRENT STATE at the end of clip {first - 1} (carry every item forward exactly unless an action step in your clips changes it):\n{state}\n"
        bridge += f"\nStart clip {first} as a direct continuation of clip {first - 1}.\n"
    spoken = _speakers_so_far(prev_clips)
    not_yet = ", ".join(c["name"] for c in bible["characters"] if c["name"].lower() not in spoken) or "none"

    return f"""You are a world-class Hollywood cinematographer and screenwriter directing an AI-generated movie.
IMPORTANT: every clip is rendered on its own by a video model that sees ONLY that clip's text and reference pictures, with no memory of any other clip. Anything you do not state in the clip (who stands where, sitting or standing, what someone holds, who opens a door) the model will invent, and it will contradict the story. So every clip must be complete on its own.

The user's story prompt (the source of truth): {topic}
Scene Bible: {json.dumps(bible)}

The beat plan for the whole video, one beat per clip, each marked SPEECH or SILENT:
{plan}

RULES for the clips:
- "location_id": the place its beat is set in (in [brackets] in the beat plan), one of these locations, and the same id for every camera angle inside the same place (every clip there is rendered from fixed pictures of it, so the room always looks the same). Follow each place's LAYOUT exactly: doors, stairs and furniture are always where it puts them.
{locations}
- CINEMATIC CAMERA POLICY ([SAME SETUP] vs [ANGLE CUT]):
  CRITICAL: Every shot description MUST explicitly begin with either "[SAME SETUP]" or "[ANGLE CUT]".
  UNIFIED THREE-PHASE APPROACH:
  (1) ESTABLISHING PHASE — LOCKED MASTER SHOT ([SAME SETUP], first 1-2 clips of a new conversation or location):
      When a conversation begins or the scene moves to a new location, open with a locked wide or medium two-shot that establishes the geography: who is where, what the room looks like, and each character's screen position (frame-left vs frame-right).
      Re-state the exact same camera placement, lens, aim direction, and 2D frame composition across these opening clips.
      DO NOT arbitrarily aim at a different wall, door, or window from clip to clip (e.g. aiming North toward the bed in Clip 1, then aiming East toward the sash window in Clip 2 completely ruins character perspective and flips their orientation).
  (2) COVERAGE PHASE — MOTIVATED CUTS ([ANGLE CUT], from clip 2-3 onward in the same conversation):
      Once geography is established, use motivated angle cuts to add cinematic rhythm:
      - Over-the-Shoulder (OTS): camera behind one character's shoulder, focused on the other's face. Alternate whose shoulder for dialogue back-and-forth.
      - Close-Up / Extreme Close-Up: cut in tight on a face, trembling hands, clenched jaw, or a key prop during emotional peaks.
      - Profile Two-Shot: both characters in profile, facing each other, for balanced confrontations.
      - Power Dynamics: dominator shot from LOW angle, vulnerable character from HIGH angle.
      - Reveals: open on a close detail (a hand, a doorknob), then pull back or tilt to reveal the full scene.
      - Walking Scenes: low-angle tracking tight on boots and legs, OR rear tracking behind the shoulders.
      Every [ANGLE CUT] must be motivated by the drama (a reaction to absorb, a shift in power, a prop to emphasize). Never cut just for visual variety alone.
  (3) THE 180-DEGREE RULE & SCREEN DIRECTION (ALWAYS ENFORCED, BOTH PHASES):
      NEVER cross the axis of action. In any conversation or cut, each character MUST maintain their screen direction:
      The character on frame-left MUST still look toward screen-right in their close-up, and the character on frame-right MUST still look toward screen-left.
      Their eye-lines MUST match across cuts. Never flip character screen placement across consecutive clips unless an action step shows them physically walking across the room.
- ESTABLISHING SHOTS: only when the user's story asks for one, or the story jumps to a new place without showing anyone arrive. It shows an exterior location, nobody is visible and there is NO dialogue. Keep them rare.
- ONE MAIN MOMENT OR BEAT: each clip captures ONE natural cinematic beat that plays out comfortably in {CLIP_SECONDS} seconds. Never cram an entire scene's setup, revelation, and resolution into a single 5-second clip. But equally, never stretch a single action (an entrance, a reveal, a kiss) across multiple clips — complete it in one beat and move on (see ANTI-DILUTION above). For example, if someone arrives to deliver bad news: Clip 1 shows the arrival and the bombshell in one beat with a quick two-turn exchange ('Got a second? Only one of you can make the team.'); Clip 2 captures the stunned reaction and rapid pushback ('You can't be serious.'). Small supporting movement (breathing, glances, shifting posture) makes it feel alive.
- "shot": You are the Director of Photography. Write the exact camera setup for this 5-second clip as a single continuous physical sentence starting with "[SAME SETUP]" or "[ANGLE CUT]". You MUST include ALL FIVE of these elements:
  (1) CAMERA PLACEMENT: where is the camera physically positioned, using the place's layout? (e.g., "[SAME SETUP] Camera placed low on the pavement behind his ankles", "[SAME SETUP] From just inside the bedroom doorway looking North-East toward the bed", "[ANGLE CUT] Tight over her left shoulder facing Daniel")
  (2) CAMERA MOVEMENT: what does it physically do during the 5 seconds? (e.g., "tracks with him as he climbs", "slowly pushes in", "tilts up from his boots to his face", "locked static hold")
  (3) WHAT IT FOLLOWS: what specific body part, prop or detail does the camera stay tight on? (e.g., "stays tight on his polished boots and trouser hem", "locks on her eyes", "follows his trembling hand")
  (4) ENDING FRAME: where does the shot resolve at the end of 5 seconds? (e.g., "ending on a close-up of his face at the door", "resolving on an over-the-shoulder frame of the open bedroom")
  (5) LIGHTING + DEPTH OF FIELD: what is the key light source and how does it hit the subject? Does the background blur into bokeh? (e.g., "warm amber streetlamp from camera left rims his jaw; background window glow blooms into soft bokeh", "single harsh overhead bulb throws deep shadows under his eyes")
  The camera placement must agree with the blocking: if the camera is behind someone's shoulder facing the door, the blocking must put that person between the camera and the door.
  STORY-CRITICAL MOVEMENT ON CAMERA: when the story depends on where someone goes or where they come from (they hide, leave, slip away, sneak in, arrive, return), the camera must point that way and keep the start and end of the movement in frame, e.g. following her until she disappears through the back door, or holding on the doorway as he walks in. Never let the move that matters happen outside the frame.
  EXITS THAT LEAVE OTHERS ALONE: when someone leaves so that the others can be alone, the camera follows them until they are clearly gone (through the door, round the far corner, out of earshot) and the shot ends holding on the people left behind, alone, so the next clip plainly reads as a private moment.
  BAD EXAMPLE (never write this): "Wide shot, eye-level, slow push-in as he walks to the door."
  GOOD EXAMPLE (write like this): "[SAME SETUP] Camera placed at knee height on the pavement behind Daniel's black dress shoes, tracking forward as he climbs the stone steps, staying tight on his ankles and the brass key in his hand, tilting up his torso to resolve on a close-up of his face at the door; warm interior lamplight spills around the doorframe and the background street blurs into amber bokeh."
  SHOT SIZES: Extreme Wide, Wide, Medium-Wide (knees up), Medium (waist up), Medium Close-Up (chest up), Close-Up (face), Extreme Close-Up (eyes, mouth, hands, one object).
  - SCREEN PLACEMENT: the video model has NO memory of previous clips and cannot parse architectural text ('near-left corner'). In every shot with two or more visible characters, explicitly state where each person is IN THE FRAME using screen-relative language: 'frame left', 'frame right', 'foreground', 'background', 'centre frame' (e.g. 'ending with the Coach standing frame left and Oliver seated frame right'). Keep each character on the same side of the frame across consecutive conversation clips (the 180-degree rule).
- "blocking" (THE POSITION DIARY, REQUIRED): one entry for EVERY character who is in this clip's place, whether the camera sees them or not:
  - "in_frame": "visible" (face and body in the shot), "partly visible" (only part of them, e.g. the hand that pushes the door open; say which part in "position"), "off screen" (in the place but outside the frame), or "has left" (only in the clip where they walk out; after that, leave them out).
  - "position" and "posture": exactly where they are and how at the START of the clip (0.0s), using the place's layout (e.g. 'at the far side of the room beside the bed, about four metres from the door', 'hovering in mid-air 1.5m above the floorboards, suspended at eye level with Elena'). Posture is standing, walking, sitting, kneeling, lying down, crouching, hovering, or floating.
  - AIRBORNE & FLOATING ENTITIES (CRITICAL):
    For drones, spirits, airborne creatures, floating lights, or any aerial entities, posture MUST be "hovering" or "floating" (never "standing" or "walking"). Explicitly specify their 3D vertical elevation in mid-air above the floorboards/ground in "position" and "end_position" (e.g. 'hovering mid-air 1.5m above the floorboards, completely airborne with feet suspended off the ground'). NEVER spawn an airborne entity on or from the floor/ground! If they materialize, they must emerge directly from their mid-air light/cloud in mid-air, NOT from the floorboards. Characters on the ground watching them must look UP or directly across at their mid-air elevation, never down at the floor!
    STRICT NO RE-TAKEOFF RULE (CONTINUITY ACROSS CUTS):
    Once any airborne entity, drone, creature, or floating object has completed its arrival, emergence, or ascent to its destination flight elevation in a previous clip (e.g. now hovering at eye level in mid-air):
    In all subsequent clips, NEVER re-describe them launching, taking off, rising upward, emerging, or flying up from their origin point, container, or the floor/ground again!
    They MUST start the clip ALREADY suspended and cruising/hovering in mid-air at their established elevation.
    Action steps must describe only their ongoing airborne flight, drift, or conversation gestures at their established elevation (e.g. 'already hovering at eye height, drifts forward 0.5m toward the headboard while speaking').
    Never re-focus the camera on the floor or origin container as a launchpad, as the video model will misinterpret that as a second takeoff eruption!
  - "screen_profile": 2D screen-relative profile at START (0.0s), e.g. 'three_quarter_facing_screen_right', 'profile_facing_screen_left', 'frontal_facing_camera' ('none' if off-screen).
  - "head_tilt": head tilt, roll, and vertical pitch at START (0.0s), e.g. 'tilted upward (chin raised, looking up at mid-air)', 'level at eye height', 'tilted downward (chin lowered, looking down at floor)', 'tilted slightly left' ('none' if off-screen).
  - "eyeline": gaze direction vector at START (0.0s), e.g. 'looking across table at eye level toward screen-right', 'upward toward floating entity in mid-air', 'downward toward hands' ('none' if off-screen).
  - "end_position" and "end_posture": where they are and how at the END of the clip (5.0s) (the same as the start if they don't move). The next clip starts from these.
  - "end_screen_profile", "end_head_tilt", "end_eyeline": profile, head tilt, and gaze at clip END (5.0s). The next clip starts from these. Always record vertical pitch: if looking up at clip end, record 'tilted upward (chin raised)'.
  - "facing": which way they face and what they look at in 3D scene space.
  - CLEAR POSITIONS: never describe a position in terms that contradict each other ('on the entrance side of the bench, directly in front of him' when he faces away from the entrance). 'In front of' and 'behind' are relative to where that person faces; when in doubt, use the layout's fixed things instead ('between the bench and the lockers').
  - "awareness": what they have noticed so far that matters (e.g. 'has not noticed the door opening', 'sees Daniel in the doorway').
  - THE GOLDEN CONTINUITY RULE (MANDATORY):
    Every character starts this clip (at 0.0s) EXACTLY where and how the previous clip ended them: its end_position, end_posture, end_screen_profile, end_head_tilt, and end_eyeline.
    NEVER snap, flip, or mirror a character's body orientation, head tilt, or screen facing across a cut!
    Preserve vertical pitch across cuts: if a character ended clip N looking UP at a hovering entity or light in mid-air, they MUST start clip N+1 at 0.0s with chin raised looking UP at that same elevation. NEVER let a character's gaze or head tilt snap downward to the floor across a cut!
  - SMOOTH MOTION TIMING (NO 0.0s SNAPS):
    If a character shifts their attention, turns to another speaker, or reacts to an object, they CANNOT start this clip already turned!
    They MUST start at 0.0s in their exact previous posture and head tilt. The head turn or shift in gaze MUST be written as an explicit timed action step in "action_steps" (e.g. [0.0s to 1.0s] Elena sits still with head tilted left, gazing toward screen-right; [1.0s to 2.5s] Elena smoothly rotates her head toward screen-left to look at the light; [2.5s to 5.0s] Elena watches the light intently).
    The "end_screen_profile", "end_head_tilt", and "end_eyeline" will then record the new orientation at 5.0s.
  - ANCHORS: describe positions against fixed things in the layout, and keep using the same words ('on the left end of the only bench', 'at the counter by the till'). When someone comes back to a place, the others are exactly where they were left, on the same spot of the same furniture, and it's said so; an empty spot someone left can be named ('the place beside him on the bench is empty').
  - OFF-SCREEN ACTORS: if someone outside the frame causes something the camera sees (opens a door, throws something in), make them "partly visible" and show it in the action steps. Otherwise the video model gives the action to whoever is on screen (a door opening with no visible hand looks as if the person inside opened it).
  - ON SCREEN: at most {MAX_ON_SCREEN} characters "visible" or "partly visible" in one clip. Five to seven are for group scenes and action scenes only.
- "action_steps" (REQUIRED, 1 to 4 steps): the clip's physical action in time order. Each has "start_est"/"end_est" in seconds inside this clip and one plain sentence of what visibly happens, naming who does it (e.g. [0.0 to 1.5] "Daniel's right hand pushes the bedroom door open from the hallway"; [1.5 to 5.0] "Emily and Mark keep kissing beside the bed, unaware"). Every change of position, posture, prop or awareness appears here.
  - LIVE REACTIONS: the video model renders each character independently — if you don't tell it what a bystander does, it freezes them like a mannequin. Every action step that has a visible bystander MUST describe what that bystander physically does at the same time (e.g. 'Ethan walks toward the door while Oliver's head turns, tracking him all the way until he disappears', NOT just 'Ethan walks toward the door' with Oliver's reaction left to "others"). Watching, flinching, turning, stepping back — if the camera sees it, the action step says it.
  - STRICT RULE: NO MANNEQUIN ACTING:
    Avoid passive, frozen states like 'staring blankly', 'remains rigidly upright', 'holds breath without moving', 'stares without blinking', 'watches motionless'.
    Human characters must exhibit dynamic bodily reactions: flinching, jolting, leaning in, clutching items or blankets, shielding eyes, gesturing, or trembling. Every 5-second clip must show an active progression in character emotion and physical posture (e.g. initial startle/recoil -> followed by leaning forward in wonder or clutching chest).
  - KINETIC PHYSICS FOR EFFECTS, LIGHTS & PHENOMENA:
    Magical lights, sparks, fire, smoke, energy swirls, and supernatural phenomena must NEVER be described as static or merely 'spinning in place'.
    Assign active spatial trajectories, velocity changes, and dynamic light-casting physics to all environmental and magical phenomena:
    (1) Trajectory & Velocity: specify active spatial motion across the room (e.g. 'the golden spark shudders violently, zips in an erratic arc across the room trailing brilliant stardust, swoops downward, then shoots up and pulses rapidly in mid-air').
    (2) Light-Casting & Moving Shadows: describe dynamic illumination (e.g. 'the pulsing flare casts flickering, rhythmic amber highlights across Elena’s face and throws moving shadows across the walls').
    (3) Physical Impact on Environment: describe how the phenomenon disturbs the surroundings (e.g. 'a resonant magical vibration billows the curtains and stirs loose hair').
  - REAL TIME: every step lasts at least {MIN_STEP_SECONDS:g} second (merge smaller moments into a neighbouring step), and movement takes realistic time: walking covers about 1 to 1.5 metres per second, running about 4, standing up or sitting down about 1 second, opening a door and stepping through about 1.5 seconds. Every step where someone walks or runs states the distance in digits, taken from the layout (e.g. 'walks the 5 metres from the bench to the gap'), so its time can be checked. If a movement doesn't fit, start the clip with the character already partway there, or end it before they arrive; never squeeze it, and never shorten or invent distances to make it fit: positions and distances always come from the layout.
  - ONLY WHAT THE CAMERA SEES: action steps describe only what is visible in this shot. Never mention an off-screen character or what they do off screen (the video model would draw them); their movement lives in the blocking only.
- "prop_state" (THE PROP DIARY, REQUIRED): one entry for every prop in the Scene Bible's "props" that has appeared in the story so far, in every clip from its first appearance to the end, even when it is not in the shot: "prop_id", "holder" (the character holding or carrying it, or 'scene' when it rests somewhere), "in_frame" (true only if the camera clearly sees it where the action happens; a prop far in the background or left in another part of the place is false, otherwise the video model draws it into the scene) and "state" (its condition and exactly where it is, e.g. 'intact, in his right hand behind his back', 'shattered across the floor beside the bed'). The system writes each prop's full fixed description into the video prompt for you. Props in the Scene Bible:
{props}
- "dialogue":
  - SPEECH OR SILENCE: a clip whose beat is SILENT has an EMPTY "dialogue" list. Never invent lines for a silent beat. A SPEECH clip has {MIN_WORDS} to {MAX_WORDS} words in total across all speakers. Ensure dialogue is substantial and uses natural, fluid phrasing (e.g., use "I'll get my bag back, wait for me" instead of just "I'll be a second").
  - STRICT RULE: NO NARRATORS. Only characters who are "visible" in the blocking can speak.
  - KNOWLEDGE: characters only say what they know at that moment. Nobody mentions, reacts to or answers something they have not noticed yet (see "awareness"). A character whose arrival must come as a surprise never calls out, greets anyone or announces themselves before the discovery.
  - PRIVACY: a secret is only spoken when the speakers have a reason to believe the person it's about can't hear (they saw them leave, a door closed, water is running, they are far away), and their "awareness" says why (e.g. 'believes Sam went out to the car park'). A character who secretly overhears is somewhere plausible for that, and the speakers don't know they are there.
  - SPEAKERS IN FRAME: whenever a character speaks, they must be in the frame (direct view, profile, three-quarter angle, or pacing/moving naturally in the shot). Natural cinematic movement—such as turning while talking, walking, or pacing the room—is encouraged. Never give dialogue to a character who is completely off-screen, out of frame, or seen strictly from behind with no head/body context; never during an over-the-shoulder shot from behind the speaker or the speaker's own POV; never during a close-up exclusively on hands, objects, or floor. When two characters speak in the same clip, frame both characters (two-shot, profile two-shot, medium shot). At most {MAX_VOICE_REFS} different speakers per clip.
  - HIGH-DENSITY DIALOGUE & TWO-SPEAKER EXCHANGES (CRITICAL FOR PACING):
    Do NOT let dialogue drag by restricting scenes to only one solitary line per 5 seconds! In dramatic conversations, arguments, and discovery scenes, actively write rapid, rhythmic two-speaker exchanges within the 5-second window:
    * Speaker A delivers a sharp 4-5 word line or question (e.g. from 0.2s to 2.3s, lasting 2.1s).
    * Speaker B delivers a sharp 4-5 word retort or counter-point (e.g. from 2.6s to 4.8s, lasting 2.2s).
    * Total words across both speakers must remain within {MIN_WORDS} to {MAX_WORDS} words (e.g. 5 words + 5 words = 10 words).
    This creates snappy verbal ping-pong that makes dialogue sequences feel fast, intense, and natural, providing 15 to 22 total lines across a 10 to 12 clip scene!
  - FLOWING DIALOGUE ACROSS CUTS: When a line needs deeper weight, a clip may feature a single punchy line or ultimatum that hangs, with the next clip starting immediately with the other character's spoken reply. Dialogue must never stall or leave long silent pauses in a conversation scene. A character who is alone may say short, meaningful lines to themselves only when the beat is SPEECH, never filler.
  - PLAIN, EVERYDAY SPEECH: characters talk like real people in a modern film, in simple, common words and short sentences that anyone understands the first time they hear them. No formal, poetic or old-fashioned phrasing, no fancy vocabulary, no jargon (not 'solicitor' or 'northbound' but 'lawyer' or 'the last train'), and no semicolons.
  - TIMING: "start_est" and "end_est" are seconds from the start of THIS clip (0 to {CLIP_SECONDS}), not of the whole video. Lines come in order and never overlap, with 0.2 to 0.5 s between speakers; the first line starts at 0.2 s or later and the last ends by {CLIP_SECONDS - 0.2:g} s. Each line's window is at least its word count divided by {WORDS_PER_SECOND:g} seconds long.
  - VOICE SAMPLES: The FIRST line a character speaks in the film is cut out of the clip and reused as that character's voice for the rest of the video, so it must be at least 5 words and 2 seconds long, spoken in a clear, fully voiced way (quiet or low is fine; never whispered, shouted, sobbed or breathless), and never a short reply.
  - "delivery": how THIS line is said: emotion, volume and pace (e.g., 'shaking with rage', 'cold, clipped and quiet'). Never describe the voice itself (tenor, baritone, accent): the system already sends each character's voice. The volume must match the story: if the story or beat says someone speaks quietly, whispers or shouts, the delivery says so (a secret is never at normal conversational volume). A character's very first line (their voice sample) may be quiet or low, but never whispered, shouted, sobbed or breathless.
  - STORY: keep the meaning of every line the user wrote for a character (quoted or described). Never write a line that contradicts the user's story or anything said or shown earlier (e.g. if a return is a surprise, nobody knew about it).
- "others": the visible acting and ambient sound in this clip. Write these things:
  (1) PHYSICAL ACTING & DYNAMIC PROGRESSION: what the face, eyes, mouth, hands, and body visibly do ('his chin trembles; he swallows hard; she flinches back against the pillows, clutching her blanket, then leans forward with parted lips'). Show active, multi-phase physical reactions instead of frozen expressions. SHOW EMOTIONS, NEVER NAME THEM — no inner states ('heartbreak', 'feels', 'realizes').
  (2) PROP INTERACTION (only if props are in the shot): how characters physically touch the props, consistent with the prop diary. If there are no props, skip this — do NOT invent props.
  (3) AMBIENT SOUND: 2 or 3 specific sound cues that Seedance should generate for the audio bed: Physical room tone, foley, and environmental sound cues ONLY (e.g. footsteps, ticking clocks, rain, distant traffic, fabric rustle, keys jingling, faint floorboard creak). Strictly NO musical instruments, score, melodies, humming, or synth drones. These make the clip feel real and alive.
- AI VIDEO LIMITATIONS (STRICT):
  - NO HAND-OFFS: AI cannot animate characters handing items to each other (e.g., handing cash, passing a phone). Instead, describe the item already in their hand, or being placed on a counter.
  - SPATIAL BLOCKING (SHOCK SCENES ONLY): when a character is meant to STOP and react the moment they open a door or enter a room (e.g., catching someone doing something), put them "standing frozen in the open doorway" in the blocking, never "enters the room and freezes". This prevents Seedance from making him walk deep into the room before stopping. For any normal walking scene, write the walking naturally.

=======================================================
CURRENT PRODUCTION CONTINUITY & ASSIGNMENT:
=======================================================
{bridge}

CALL SHEET FOR THIS ASSIGNMENT:
- Characters who have not spoken yet in the film so far: {not_yet}. (Remember: their first line becomes their voice sample).
- Directing {'CLIP ' + str(first) if first == last else 'CHAPTER ' + str(chap_idx + 1)} of {total_chapters}: write ONLY {clip_range_str} of the video, matching {beat_range_str} in the beat plan above. The other beats show what comes before and after; do not repeat earlier beats or jump ahead.
- You must generate EXACTLY {clip_count_str} of {CLIP_SECONDS} seconds each. This is a high-stakes, deeply dramatic movie.
Return strictly valid JSON matching the schema."""

def _supervisor_prompt(topic: str, bible: dict, beats: list, prev_clips: list, new_clips: list, first: int) -> str:
    plan = "\n".join(_beat_line(n, b) for n, b in enumerate(beats, 1))
    state = _state_so_far(prev_clips) or "  (nothing filmed yet)"
    recent = json.dumps(prev_clips[-3:], ensure_ascii=False)
    return f"""You are the script supervisor (continuity supervisor) on an AI-generated film. Each {CLIP_SECONDS}-second clip is rendered separately by a video model that sees ONLY that clip's own text and reference pictures, with no memory of other clips, so every contradiction or missing detail becomes a visible mistake.
The user's story: {topic}
Scene Bible (characters, locations with their fixed layouts, props): {json.dumps(bible, ensure_ascii=False)}
Beat plan (each clip marked SPEECH or SILENT):
{plan}
State at the end of the last clip already filmed:
{state}
The last clips already filmed (final, do not critique them): {recent}

NEW clips to check, clips {first} to {first + len(new_clips) - 1}: {json.dumps(new_clips, ensure_ascii=False)}

List the real problems in the NEW clips, most serious first, each as one short sentence starting with 'clip N:' and saying what to change. Check:
1. BEAT: does the clip do what its beat says?
2. BLOCKING & ORIENTATION CONTINUITY: every character starts where and how the previous clip ended them (its end_position, end_posture, end_screen_profile, and end_head_tilt), and their facing and awareness continue, unless an action step in this clip shows the change. No jump-cut orientation snapping: starting screen direction (facing left vs right) and head tilt at 0.0s must match the end of the previous clip. Vertical pitch continuity (chin raised looking up at mid-air vs level vs chin down) must be preserved across cuts. Airborne/hovering entities must remain suspended in mid-air and never spawn on or drop to the floor. Once an entity has completed its arrival or ascent in a previous clip, verify it is NOT re-described taking off or emerging from the floor/origin again, but starts already suspended and hovering at its established flight elevation. Any turn or shift of gaze must happen smoothly within an action step. The camera setup must follow the 180-degree rule across cuts. Nobody teleports, sits down or stands up off screen, or ends up somewhere the layout makes impossible. Someone who returns finds the others exactly where they were left, on the same spot of the same furniture.
3. TIMING: every action step lasts at least {MIN_STEP_SECONDS:g} second, and movement takes realistic time (walking about 1 to 1.5 metres per second). A long walk or an entrance squeezed into a second, or a walk plus a whole conversation in one clip, is a problem. Check each stated walking distance against the layout: an understated distance (5 metres called 2), or furniture moved closer so that a walk fits, is a problem.
   Action steps must describe only what the camera sees; a step that mentions an off-screen character is a problem.
4. STORY-CRITICAL MOVEMENT: when where someone goes or comes from matters to the story (hiding, leaving, arriving, returning), does the camera actually show it, start and end? A key exit that happens outside the frame is a problem. When someone leaves so that others can be alone, does the shot follow them until they are clearly gone and end on the people left behind?
4b. PRIVACY: is a secret only spoken when the speakers have a clear reason to believe the person it's about can't hear (saw them leave, door closed, far away), with that reason in their awareness? Someone hiding a couple of metres away, where the speakers just watched them go, is a problem.
5. KNOWLEDGE: nobody says, answers or reacts to something they have not noticed yet; nobody behaves as if they noticed someone before an action step shows it; a character whose arrival must be a surprise does not call out or announce themselves.
6. SPACE: doors, stairs and furniture are where the location's layout puts them; it is clear who opens each door (an off-screen person who does it is "partly visible" and named in the action steps); entrances, exits and distances make physical sense; no position is described in terms that contradict each other ('on the entrance side, directly in front of him' when he faces away from the entrance).
7. PROPS: every prop keeps its state and holder unless an action step changes them; a held prop stays in hand; broken things stay broken; a prop is marked in_frame only when the camera clearly sees it where the action happens.
8. CAMERA WORK & CLARITY FOR THE VIDEO MODEL: verify that conversation scenes open with a [SAME SETUP] locked master shot to establish geography (first 1-2 clips in a location), then use only motivated [ANGLE CUT]s (OTS, close-ups) — never random aim jumps to different walls. Verify the 180-degree rule is respected. Check that visible characters exhibit active physical reactions rather than freezing like mannequins or staring blankly for 5 seconds. Check that magical or environmental effects have dynamic spatial motion and lighting rather than hovering static. Could the model misread who does what (e.g. a door opening with no visible hand looks as if the person inside opened it)? Does the camera placement agree with the blocking? Is anyone doing two things at once, or is too much packed into {CLIP_SECONDS} seconds?
9. STORY: the lines and actions keep the user's story and never contradict an earlier clip, and each line's delivery matches how the story says it is spoken (said quietly or whispered in the story means a quiet delivery, never 'normal conversational volume').
BEFORE reporting anything, check it against the location's layout and the blocking (for example, a door that opens inward is pushed from outside and pulled from inside); if your note is wrong or unsure, drop it. Report only problems that would visibly show in the video or break the story, never style preferences or details the camera would not see. Return {{"problems": []}} if there are none."""

SUPERVISOR_SCHEMA = {
    "type": "object",
    "properties": {"problems": {"type": "array", "items": {"type": "string"}}},
    "required": ["problems"],
    "additionalProperties": False,
}

@observe(name="supervise_chapter", as_type="span")
def supervise_chapter(topic: str, bible: dict, beats: list, prev_clips: list, new_clips: list, first: int) -> list[str]:
    """A second OpenAI read of a chapter against the story state: the logic the code checks can't see."""
    print("  Script supervisor is checking continuity...", flush=True)
    answer = _ask_openai_json(_supervisor_prompt(topic, bible, beats, prev_clips, new_clips, first), "Check the new clips.",
                              "script_supervisor", SUPERVISOR_SCHEMA)
    problems = [f"script supervisor: {p}" for p in answer.get("problems", [])]
    client = get_client()
    if client and problems:
        try:
            client.create_event(name="supervisor_detected_issues", metadata={"problems": problems})
        except Exception:
            pass
    return problems



# ---------------------------------------------------------------------------
# Chapter check — the rules above that code can verify; OpenAI is asked to fix any it breaks
# ---------------------------------------------------------------------------
_WORD = re.compile(r"[\w'’]+")
_NOT_NORMAL_VOLUME = re.compile(r"\b(whisper|shout|scream|yell|murmur)(s|ed|ing)?\b|\bsob(s|bed|bing)?\b|\bbreathless\b|\bbarely audible\b", re.I)
_INNER_STATE = re.compile(r"\b(feels?|feeling|reali[sz](e|es|ing)|heartbreak|devastation|emotionally|imagining|hinting)\b", re.I)

WALK_SPEED, RUN_SPEED = 1.5, 4.0  # metres per second: the fastest a step may cover a stated distance
_MOVE = re.compile(r"\b(walk(s|ed|ing)?|run(s|ning)?|ran|sprint(s|ed|ing)?|dash(es|ed|ing)?|stride(s)?|strode|jog(s|ged|ging)?|hurr(y|ies|ied|ying)|rush(es|ed|ing)?)\b", re.I)
_RUN = re.compile(r"\b(run(s|ning)?|ran|sprint(s|ed|ing)?|dash(es|ed|ing)?|rush(es|ed|ing)?|hurr(y|ies|ied|ying)|jog(s|ged|ging)?)\b", re.I)
_DISTANCE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:-\s*)?(?:m|metres?|meters?)\b", re.I)

def _words(line: str) -> int:
    return len(_WORD.findall(line))

_IGNORE_DIRECTIONS = {"none", "off-screen", "off screen", "not visible", ""}

def _norm_desc(val: str | None) -> str:
    if not val:
        return ""
    return re.sub(r"[\s\-_]+", " ", str(val)).strip().lower()

def _profiles_conflict(prof_a: str | None, prof_b: str | None) -> bool:
    if not prof_a or not prof_b:
        return False
    a, b = _norm_desc(prof_a), _norm_desc(prof_b)
    if a in _IGNORE_DIRECTIONS or b in _IGNORE_DIRECTIONS:
        return False
    if a == b:
        return False
    left_a, left_b = ("left" in a), ("left" in b)
    right_a, right_b = ("right" in a), ("right" in b)
    if (left_a and right_b) or (right_a and left_b):
        return True
    if ("frontal" in a and "back" in b) or ("back" in a and "frontal" in b):
        return True
    return a != b

_TILT_UP = re.compile(r"\b(up|upward|upwards|raised)\b", re.I)
_TILT_DOWN = re.compile(r"\b(down|downward|downwards|lowered)\b", re.I)
_TILT_LEVEL = re.compile(r"\b(level|neutral|horizontal|upright)\b", re.I)
_TILT_LEFT = re.compile(r"\bleft\b", re.I)
_TILT_RIGHT = re.compile(r"\bright\b", re.I)

def _tilts_conflict(tilt_a: str | None, tilt_b: str | None) -> bool:
    if not tilt_a or not tilt_b:
        return False
    a, b = _norm_desc(tilt_a), _norm_desc(tilt_b)
    if a in _IGNORE_DIRECTIONS or b in _IGNORE_DIRECTIONS:
        return False
    if a == b:
        return False
    left_a, left_b = bool(_TILT_LEFT.search(a)), bool(_TILT_LEFT.search(b))
    right_a, right_b = bool(_TILT_RIGHT.search(a)), bool(_TILT_RIGHT.search(b))
    if (left_a and right_b) or (right_a and left_b):
        return True
    up_a, up_b = bool(_TILT_UP.search(a)), bool(_TILT_UP.search(b))
    down_a, down_b = bool(_TILT_DOWN.search(a)), bool(_TILT_DOWN.search(b))
    level_a = bool(_TILT_LEVEL.search(a)) and not (up_a or down_a or left_a or right_a)
    level_b = bool(_TILT_LEVEL.search(b)) and not (up_b or down_b or left_b or right_b)
    if (up_a and down_b) or (down_a and up_b):
        return True
    if (up_a and level_b) or (level_a and up_b):
        return True
    if (down_a and level_b) or (level_a and down_b):
        return True
    if ((left_a or right_a) and level_b) or (level_a and (left_b or right_b)):
        return True
    return False

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
    for loc in bible["locations"]:
        if "views" in loc and not PLACE_VIEWS[0] <= len(loc["views"]) <= PLACE_VIEWS[1]:
            problems.append(f"location '{loc['id']}' needs {PLACE_VIEWS[0]} or {PLACE_VIEWS[1]} views, not {len(loc['views'])}")
        if "layout" in loc and not loc["layout"].strip():
            problems.append(f"location '{loc['id']}' needs a layout (where its doors, stairs and furniture are)")
    prop_ids = [p["id"] for p in bible.get("props", [])]
    if len(set(prop_ids)) != len(prop_ids):
        problems.append("every prop needs its own unique id")
    prev_act = ""
    for n, b in enumerate(outline["beats"], 1):
        if b["location_id"] not in ids:
            problems.append(f"beat {n} happens in '{b['location_id']}', which is not in \"locations\": add that place to the locations (with its own description and image_prompt), or use the listed id of the place it means")
        act = b.get("action", "").strip()
        if _words(act) < 4:
            problems.append(f"beat {n}: action description is too brief ('{act}'); describe the specific physical action, dialogue turn, or state change (needs at least 4 words)")
        if prev_act and act.lower() == prev_act.lower():
            problems.append(f"beat {n}: action is an exact duplicate of beat {n-1} ('{act}'); every beat must produce a new state change or advance the narrative")
        prev_act = act
    return problems

def _normalize_clips(clips: list, bible: dict) -> None:
    """Spell every name as the bible does (the cast and voice banks are keyed by bible name) and derive
    present_characters (everyone visible or partly visible) from the blocking."""
    by_lower = {c["name"].lower(): c["name"] for c in bible["characters"]}
    for clip in clips:
        for b in clip.get("blocking", []):
            b["character"] = by_lower.get(b["character"].lower(), b["character"])
        for p in clip.get("prop_state", []):
            p["holder"] = by_lower.get(p["holder"].lower(), p["holder"])
        if "blocking" in clip:
            clip["present_characters"] = [b["character"] for b in clip["blocking"] if b["in_frame"] in ON_SCREEN]
        clip["present_characters"] = [by_lower.get(p.lower(), p) for p in clip.get("present_characters", [])]
        for t in clip["dialogue"]:
            t["speaker"] = by_lower.get(t["speaker"].lower(), t["speaker"])

def _check_chapter(clips: list, bible: dict, first_clip_number: int, chapter_beats: list, prev_clips: list) -> list[str]:
    names = {c["name"].lower() for c in bible["characters"]}
    prop_ids = {p["id"] for p in bible.get("props", [])}
    spoken = _speakers_so_far(prev_clips)
    problems = []
    if len(clips) != len(chapter_beats):
        problems.append(f"the chapter must have exactly {len(chapter_beats)} clips, one per beat, not {len(clips)}")
    for n, (clip, beat) in enumerate(zip(clips, chapter_beats), first_clip_number):
        if clip["location_id"] != beat["location_id"]:
            problems.append(f"clip {n} is set in '{clip['location_id']}', but its beat happens in '{beat['location_id']}'")
    history = list(prev_clips)
    for n, clip in enumerate(clips, first_clip_number):
        beat = chapter_beats[n - first_clip_number] if n - first_clip_number < len(chapter_beats) else {}
        present = {p.lower() for p in clip["present_characters"]}
        turns = clip["dialogue"]
        prev = history[-1] if history else None
        for p in clip["present_characters"]:
            if p.lower() not in names:
                problems.append(f"clip {n}: '{p}' is not a Scene Bible name (spell names exactly as in the bible)")
        if len(present) > MAX_ON_SCREEN:
            problems.append(f"clip {n}: {len(present)} characters on screen; the maximum is {MAX_ON_SCREEN}")
        texts = [("shot", clip["shot"]), ("others", clip["others"])] + [("action_steps", s["action"]) for s in clip.get("action_steps", [])]
        for field, text in texts:
            m = _INNER_STATE.search(text)
            if m:
                problems.append(f"clip {n}: \"{field}\" names an inner state ('{m.group(0)}'); describe what the face and body visibly do instead")
        shot_text = clip.get("shot", "")
        if prev and not re.search(r"\[(SAME SETUP|ANGLE CUT)\]", shot_text, re.I):
            problems.append(f"[SOFT] clip {n}: shot description should specify camera continuity tag [SAME SETUP] or [ANGLE CUT] at the start")
        if "blocking" in clip:  # scripts saved before the position diary existed have none
            listed = [b["character"].lower() for b in clip["blocking"]]
            if len(set(listed)) != len(listed):
                problems.append(f"clip {n}: a character is listed twice in the blocking")
            for b in clip.get("blocking", []):
                pos_text = f"{b.get('position', '')} {b.get('end_position', '')}".lower()
                post_val = b.get("posture", "")
                end_post_val = b.get("end_posture", post_val)
                if any(w in pos_text for w in ["hover", "float", "airborne", "mid-air", "mid air", "in the air", "aloft"]):
                    if post_val in ("standing", "walking") or end_post_val in ("standing", "walking"):
                        problems.append(
                            f"clip {n}: {b['character']} is described as airborne/hovering/floating, but posture is '{post_val}' (end_posture: '{end_post_val}'); "
                            f"use posture 'hovering' or 'floating' for airborne entities (never 'standing' or 'walking')."
                        )
                if post_val in ("hovering", "floating") or end_post_val in ("hovering", "floating"):
                    if "on the floor" in pos_text or "on the ground" in pos_text or "on the floorboards" in pos_text:
                        problems.append(
                            f"clip {n}: {b['character']} has posture '{post_val}' but position is on the floor/ground; "
                            f"airborne entities must remain suspended in mid-air at an explicit height above the floor."
                        )
            if prev and prev.get("blocking") and prev["location_id"] == clip["location_id"]:
                prev_by_name = {b["character"].lower(): b for b in prev["blocking"]}
                for b in prev["blocking"]:
                    if b["in_frame"] != "has left" and b["character"].lower() not in listed:
                        problems.append(f"clip {n}: {b['character']} was in {clip['location_id']} in the previous clip and hasn't left, so they must be in this clip's blocking (as 'off screen' if the camera doesn't see them)")
                for b in clip.get("blocking", []):
                    cname = b["character"].lower()
                    if cname in prev_by_name:
                        pb = prev_by_name[cname]
                        if pb.get("in_frame") in ON_SCREEN and b.get("in_frame") in ON_SCREEN:
                            # 1. Posture continuity at 0.0s
                            prev_end_posture = pb.get("end_posture", pb.get("posture"))
                            curr_start_posture = b.get("posture")
                            if prev_end_posture and curr_start_posture and prev_end_posture != curr_start_posture:
                                problems.append(
                                    f"clip {n}: {b['character']} starts with posture '{curr_start_posture}', but ended clip {n-1} with '{prev_end_posture}' "
                                    f"(start posture at 0.0s must match previous clip's ending posture; any posture change must occur within action_steps)"
                                )
                            # 2. Screen profile continuity at 0.0s
                            prev_end_prof = pb.get("end_screen_profile", pb.get("screen_profile"))
                            curr_prof = b.get("screen_profile")
                            if _profiles_conflict(prev_end_prof, curr_prof):
                                problems.append(
                                    f"clip {n}: {b['character']} starts with screen_profile '{curr_prof}', but ended clip {n-1} with '{prev_end_prof}'. "
                                    f"Starting pose at 0.0s must match previous clip's ending state. Any head/body rotation must occur smoothly within action_steps."
                                )
                            # 3. Head tilt continuity at 0.0s
                            prev_end_tilt = pb.get("end_head_tilt", pb.get("head_tilt"))
                            curr_tilt = b.get("head_tilt")
                            if _tilts_conflict(prev_end_tilt, curr_tilt):
                                problems.append(
                                    f"clip {n}: {b['character']} starts with head_tilt '{curr_tilt}', but ended clip {n-1} with '{prev_end_tilt}'. "
                                    f"Head tilt at 0.0s must match previous clip; write any head motion as a smooth timeline action step."
                                )
            steps = clip.get("action_steps", [])
            if not steps:
                problems.append(f"clip {n}: it needs 1 to 4 action steps")
            last_start = 0.0
            for s in steps:
                if not 0 <= s["start_est"] < s["end_est"] <= CLIP_SECONDS or s["start_est"] < last_start:
                    problems.append(f"clip {n}: action steps must be in time order, inside 0 to {CLIP_SECONDS} s")
                    break
                span = s["end_est"] - s["start_est"]
                if span < MIN_STEP_SECONDS - 0.05:
                    problems.append(f"clip {n}: the action step \"{s['action'][:60]}\" lasts {span:.1f} s; each step needs at least {MIN_STEP_SECONDS:g} s of real time (merge it into a neighbour, or start the clip with the movement partway done)")
                moving = _MOVE.search(s["action"])
                if moving:
                    dist = _DISTANCE.search(s["action"])
                    if not dist:
                        problems.append(f"clip {n}: the action step \"{s['action'][:60]}\" has someone {moving.group(0)} but doesn't say how far (e.g. 'walks the 5 metres to the door'), so its timing can't be checked")
                    else:
                        speed = RUN_SPEED if _RUN.search(s["action"]) else WALK_SPEED
                        needed = float(dist.group(1)) / speed
                        if span < needed - 0.1:
                            problems.append(f"clip {n}: \"{s['action'][:60]}\" covers {dist.group(1)} m in {span:.1f} s; that needs about {needed:.1f} s. Give it the time, or start or end the clip partway through the movement")
                off = [b["character"] for b in clip["blocking"] if b["in_frame"] in ("off screen", "has left")]
                named = [c for c in off if re.search(rf"\b{re.escape(c)}\b", s["action"], re.I)]
                if named:
                    problems.append(f"clip {n}: the action step \"{s['action'][:60]}\" mentions {', '.join(named)}, who is off screen; action steps describe only what the camera sees")
                last_start = s["start_est"]
            holders = names | {"scene"}
            carried = {p["prop_id"] for p in clip.get("prop_state", [])}
            for p in clip.get("prop_state", []):
                if p["prop_id"] not in prop_ids:
                    problems.append(f"clip {n}: prop '{p['prop_id']}' is not in the Scene Bible's props")
                if p["holder"].lower() not in holders:
                    problems.append(f"clip {n}: prop '{p['prop_id']}' is held by '{p['holder']}', which is neither a character nor 'scene'")
            if prev:
                for p in prev.get("prop_state", []):
                    if p["prop_id"] not in carried:
                        problems.append(f"clip {n}: prop '{p['prop_id']}' appeared earlier, so it must stay in the prop diary (with its current state)")
        if not present:
            if turns:
                problems.append(f"clip {n}: nobody is on screen (establishing shot), so it must have no dialogue")
            history.append(clip)
            continue
        if turns:
            total = sum(_words(t["line"]) for t in turns)
            if not MIN_WORDS <= total <= MAX_WORDS:
                problems.append(f"[SOFT] clip {n}: {total} words of dialogue; a SPEECH clip needs {MIN_WORDS} to {MAX_WORDS}")
        elif beat.get("speech", True):
            problems.append(f"[SOFT] clip {n}: its beat is SPEECH, so it needs {MIN_WORDS} to {MAX_WORDS} words of dialogue")
        if len({t["speaker"].lower() for t in turns}) > MAX_VOICE_REFS:
            problems.append(f"clip {n}: more than {MAX_VOICE_REFS} different speakers; the maximum is {MAX_VOICE_REFS}")
        visible = {b["character"].lower() for b in clip.get("blocking", []) if b["in_frame"] == "visible"} if "blocking" in clip else present
        prev_end = 0.0
        for t in turns:
            who, words, span = t["speaker"], _words(t["line"]), t["end_est"] - t["start_est"]
            if who.lower() not in visible:
                problems.append(f"clip {n}: {who} speaks but is not 'visible' in the blocking (a speaker's face must be on screen)")
            if ";" in t["line"]:
                problems.append(f"[SOFT] clip {n}: {who}'s line has a semicolon; people don't talk like that, split it into short plain sentences")
            if not 0 <= t["start_est"] < t["end_est"] <= CLIP_SECONDS:
                problems.append(f"clip {n}: {who}'s line is timed {t['start_est']} to {t['end_est']} s; times are seconds inside this {CLIP_SECONDS} s clip")
            elif t["start_est"] < prev_end:
                problems.append(f"clip {n}: {who}'s line starts before the previous line ends")
            elif words > span * WORDS_PER_SECOND + 0.5:
                problems.append(f"[SOFT] clip {n}: {who}'s line has {words} words in {span:.1f} s; it needs at least {words / WORDS_PER_SECOND:.1f} s")
            prev_end = max(prev_end, t["end_est"])
            if who.lower() not in spoken:
                spoken.add(who.lower())
                if words < 5 or span < VOICE_MIN_SECONDS or _NOT_NORMAL_VOLUME.search(t["delivery"]):
                    problems.append(f"clip {n}: this is {who}'s first line, which becomes their voice sample: it needs at least 5 words, at least {VOICE_MIN_SECONDS:g} s, clearly voiced (quiet is fine; not whispered, shouted, sobbed or breathless)")
        history.append(clip)
    return problems

def _ask_checked(what: str, prompt: str, request: str, name: str, schema: dict, check) -> tuple[dict, list[str]]:
    """Ask OpenAI, check the answer, and ask it to fix what's wrong (up to SCRIPT_RETRIES times).
    Returns the answer and whatever problems are still left.
    Problems prefixed with [SOFT] are warnings only (e.g. word count) and do not trigger retries."""
    SOFT = "[SOFT] "
    client = get_client()
    for attempt in range(SCRIPT_RETRIES + 1):
        data = _ask_openai_json(prompt, request, name, schema)
        problems = check(data)
        soft = [p for p in problems if p.startswith(SOFT)]
        hard = [p for p in problems if not p.startswith(SOFT)]
        if soft:
            print(f"  {what} check: {len(soft)} soft warning(s) (will not retry):")
            for p in soft:
                print(f"    ⚡ {p[len(SOFT):]}")
        if not hard:
            break
        if client:
            try:
                client.create_event(
                    name=f"{what}_validation_retry",
                    metadata={"attempt": attempt + 1, "hard_problems": hard, "soft_warnings": soft}
                )
            except Exception:
                pass
        if attempt < SCRIPT_RETRIES:
            print(f"  {what} check: {len(hard)} problem(s), asking OpenAI to fix them (retry {attempt + 1}/{SCRIPT_RETRIES}):")
            for p in hard:
                print(f"    - {p}")
            request = (
                "Here is your previous answer:\n" + json.dumps(data) + "\n\nIt breaks these rules:\n- " + "\n- ".join(hard)
                + "\n\nCRITICAL INSTRUCTION: DO NOT hallucinate a completely new story. You must remain 100% faithful to the Master Plan Beat and the previous clip's ending state. ONLY change the specific details (like posture, props, or word count) necessary to fix the broken rules. Do not rewrite the core action steps unless explicitly required to fix a teleportation or logic error. Return the fixed JSON keeping everything else identical."
            )
    # Strip [SOFT] prefix for the final report
    all_remaining = hard + [p[len(SOFT):] for p in soft]
    if hard:
        print(f"\n  ⚠ {what} still breaks {len(hard)} rule(s) after {SCRIPT_RETRIES} retries:")
        for p in hard:
            print(f"    - {p}")
    return data, all_remaining

@observe(name="write_outline")
def write_outline(topic: str, duration: int, total_clips: int) -> tuple[dict, list[str]]:
    return _ask_checked("Outline", _outline_prompt(topic, duration, total_clips), "Generate Outline", "movie_outline",
                        _outline_schema(), lambda d: _check_outline(d, total_clips))


def _continuation_outline_prompt(
    original_topic: str,
    continuation_prompt: str,
    bible: dict,
    prev_clips: list,
    additional_clips: int,
) -> str:
    start_clip_idx = len(prev_clips) + 1
    end_clip_idx = len(prev_clips) + additional_clips
    state = _state_so_far(prev_clips)
    recent_summary = ""
    if prev_clips:
        last_clip = prev_clips[-1]
        recent_summary = f"The previous video ended at clip {len(prev_clips)} in location '{last_clip.get('location_id', '')}'.\n"
        if last_clip.get("action_steps"):
            recent_summary += "Last clip action: " + "; ".join(a.get("action", "") for a in last_clip.get("action_steps", [])) + "\n"
        if last_clip.get("dialogue"):
            recent_summary += "Last clip dialogue: " + "; ".join(f'{d.get("speaker")}: "{d.get("line")}"' for d in last_clip.get("dialogue", [])) + "\n"

    return f"""You are continuing an ongoing AI drama scene.
Original Scene Premise: {original_topic}

Existing Scene Bible:
{json.dumps(bible, indent=2, ensure_ascii=False)}

Where the previous film left off:
{recent_summary}
{state}

User's continuation prompt for the next part of the story:
{continuation_prompt}

Plan exactly {additional_clips} NEW clips of {CLIP_SECONDS} seconds each (clips {start_clip_idx} to {end_clip_idx}).

Return a JSON object with:
1. "scene_bible": The updated scene bible.
   - Keep ALL existing characters, locations, props, and style intact. Do NOT rename or remove any existing character or location.
   - If the continuation introduces any NEW characters, add them to "characters" with their full permanent look, voice, and photorealistic "image_prompt" (Arri Alexa, 35mm lens, 8k, natural skin texture, NO CGI, NO 3D render).
   - If the continuation visits any NEW location or set, add it to "locations" with its fixed description, layout map, views, and photorealistic "image_prompt" (NO PEOPLE).
   - If any new handled props are introduced, add them to "props".
2. "beats": Exactly {additional_clips} beats in order, one per clip, for clips {start_clip_idx} to {end_clip_idx}.
   - Beat {start_clip_idx} must connect seamlessly with the ending state of clip {len(prev_clips)}.
   - If transitioning to a new building or major location, the very first beat in that new place MUST be an Establishing Shot (speech: false).
   - Each beat has "location_id" (must exist in locations), "action", and "speech" (true/false).
   - THE LAW OF STATE CHANGES: Every single 5-second beat must produce an explicit observable state change (emotional shift, informational turn, or physical/spatial change). Never repeat the same action or leave characters in a stagnant state across consecutive beats.
   - NO EVENT STRETCHING: Complete any physical emergence or action within one clip rather than diluting it across multiple beats.
   - DIALOGUE DENSITY & RAPID MULTI-TURN EXCHANGES (HIGH PACING):
     In conversational, negotiation, or confrontation scenes, do NOT restrict dialogue to one solitary line per 5 seconds! Keep the scene lively with snappy two-way dialogue exchanges (e.g. Speaker A asks or accuses; Speaker B retorts or reacts within the same clip, or delivers a punchy hook answered in the next). In a dialogue-heavy sequence, aim for high dialogue density so the scene feels fast, punchy, and alive rather than dragging out with long pauses.
   - NO DEAD-AIR IN DISCUSSION SCENES:
     Once a conversation or dramatic encounter begins, EVERY consecutive beat must be a SPEECH beat ("speech": true). Never insert random silent filler clips in the middle of an ongoing dialogue exchange. Silent clips ("speech": false) belong ONLY to exterior establishing shots, stealth/sneaking, or brief moments of physical paralysis/shock.
"""


def _check_continuation_outline(outline: dict, additional_clips: int) -> list[str]:
    bible = outline.get("scene_bible", {})
    problems = []
    if len(outline.get("beats", [])) != additional_clips:
        problems.append(f"'beats' must have exactly {additional_clips} entries, not {len(outline.get('beats', []))}")
    ids = [loc["id"] for loc in bible.get("locations", [])]
    prev_act = ""
    for n, b in enumerate(outline.get("beats", []), 1):
        if b.get("location_id") not in ids:
            problems.append(f"continuation beat {n} uses '{b.get('location_id')}' which is not in locations")
        act = b.get("action", "").strip()
        if _words(act) < 4:
            problems.append(f"continuation beat {n}: action description is too brief ('{act}'); describe the specific physical action, dialogue turn, or state change")
        if prev_act and act.lower() == prev_act.lower():
            problems.append(f"continuation beat {n}: action is an exact duplicate of beat {n-1} ('{act}'); every beat must produce a new state change")
        prev_act = act
    return problems


@observe(name="write_continuation_outline")
def write_continuation_outline(
    original_topic: str,
    continuation_prompt: str,
    bible: dict,
    prev_clips: list,
    additional_clips: int,
) -> tuple[dict, list[str]]:
    prompt = _continuation_outline_prompt(original_topic, continuation_prompt, bible, prev_clips, additional_clips)
    return _ask_checked(
        "Continuation Outline",
        prompt,
        "Generate Continuation Outline",
        "movie_continuation_outline",
        _outline_schema(),
        lambda d: _check_continuation_outline(d, additional_clips),
    )


@observe(name="write_chapter")
def write_chapter(topic: str, chap_idx: int, total_chapters: int, beats: list, bible: dict, prev_clips: list, supervise: bool = False) -> tuple[dict, list[str]]:
    first, mine = _chapter_beats(beats, chap_idx)
    schema = _chapter_schema([loc["id"] for loc in bible["locations"]], [c["name"] for c in bible["characters"]],
                             [p["id"] for p in bible.get("props", [])])

    def check(data: dict) -> list[str]:
        _normalize_clips(data["clips"], bible)
        problems = _check_chapter(data["clips"], bible, first, mine, prev_clips)
        if not problems and supervise:
            return supervise_chapter(topic, bible, beats, prev_clips, data["clips"], first)
        return problems

    return _ask_checked(
        f"Chapter {chap_idx + 1}", _chapter_prompt(topic, chap_idx, total_chapters, beats, bible, prev_clips), "Generate Script",
        f"movie_chapter_{chap_idx + 1}", schema, check,
    )

def save_script(path: Path, topic: str, bible: dict, beats: list, chapters: list) -> None:
    """Everything the video steps need, so --from-script can render exactly this script without asking OpenAI again."""
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {"version": 2, "topic": topic, "scene_bible": bible, "beats": beats, "chapters": chapters}
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

def _report(what: str, problems: list[str]) -> None:
    if problems:
        print(f"\n  ⚠ {what} breaks {len(problems)} rule(s):")
        for p in problems:
            print(f"    - {p}")

_VOICE_WORDS = re.compile(r"\b(tenor|baritone|bass|alto|soprano|mezzo|contralto|accent(ed)?|voice)\b", re.I)

def _delivery_only(delivery: str, voice: str) -> str:
    """Drop the parts of a line's delivery that re-describe the voice itself ('clear youthful tenor, ...'):
    the character's voice is already sent, and saying it twice only muddles the prompt."""
    parts = [p.strip() for p in delivery.split(",") if p.strip()]
    kept = []
    for i, p in enumerate(parts):
        if _VOICE_WORDS.search(p) or p.lower() in voice.lower():
            continue
        # "low, careful, and clipped" minus "low" must not become "careful, and clipped" when the list is cut short
        kept.append(re.sub(r"^(and|but)\s+", "", p, flags=re.I) if (i == len(parts) - 1 and len(kept) <= 1) else p)
    return ", ".join(kept) if kept else delivery

def _join(items: list[str]) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]

def build_multi_prompt(
    clip: dict,
    bible: dict,
    cast_bank: dict[str, str],
    location_bank: dict[str, list[str]],
    voice_bank: dict[str, str],
    prev_clip: dict | None = None,
) -> tuple[str, list[str], list[str]]:
    """The clip's Seedance prompt and references. Everything the clip needs is stated here, because Seedance sees nothing else:
    the place (pictures and layout), who is where (blocking), what props are in the shot and their state, the timed action,
    the dialogue and the acting."""
    loc = next((l for l in bible["locations"] if l["id"] == clip["location_id"]), None)
    on_screen = clip["present_characters"][:MAX_ON_SCREEN]
    faces = [n for n in on_screen if cast_bank.get(n)]
    # Picture budget (kie.ai takes 9): every face first, then as many views of the place as fit (at least 1, at most 3).
    place_urls = [u for u in location_bank.get(clip["location_id"], []) if u]
    place_urls = place_urls[:max(1, min(PLACE_VIEWS[1], MAX_REF_IMAGES - len(faces)))]
    ref_image_urls = list(place_urls)

    char_tags = []
    for name in on_screen:
        char_info = next((c for c in bible["characters"] if c["name"].lower() == name.lower()), None)
        if not char_info: continue
        if cast_bank.get(name) and len(ref_image_urls) < MAX_REF_IMAGES:
            ref_image_urls.append(cast_bank[name])
            char_tags.append(f"{name} is @Image{len(ref_image_urls)} ({char_info['look']})")
        else:
            char_tags.append(f"{name} ({char_info['look']})")

    shot = clip["shot"].rstrip(". ")
    others = clip["others"].rstrip(". ") if clip["others"] else ""
    if place_urls:
        tags = _join([f"@Image{i}" for i in range(1, len(place_urls) + 1)])
        same = " (the same place from different angles)" if len(place_urls) > 1 else ""
        setting_note = f"The location is the place shown in {tags}{same}: keep its layout, architecture, furniture, materials, colors and light exactly the same, but film it from the camera angle described here"
    else:
        setting_note = f"Location: {loc['description'].rstrip('. ') if loc else clip['location_id']}"

    parts = [f"Five-second {shot}, {setting_note}."]
    parts.append(f"Characters: {'. '.join(char_tags)}." if on_screen else "Cinematic environmental shot, no people.")

    blocking = [b for b in clip.get("blocking", []) if b["in_frame"] in ON_SCREEN]

    # Pillar 4: Temporal Continuity Anchor
    anchor_items = []
    airborne_characters = []
    for b in blocking:
        cname = b["character"]
        prof = b.get("screen_profile", "").strip()
        tilt = b.get("head_tilt", "").strip()
        eye = b.get("eyeline", "").strip()
        post = b.get("posture", "").strip()
        if post in ("hovering", "floating"):
            airborne_characters.append(cname)
            c_parts = [f"{cname}: {post} in mid-air (airborne)"]
        else:
            c_parts = [f"{cname}: {post}"]
        if prof and prof.lower() not in _IGNORE_DIRECTIONS:
            c_parts.append(prof.replace("_", " "))
        if tilt and tilt.lower() not in _IGNORE_DIRECTIONS:
            c_parts.append(f"head {tilt}")
        if eye and eye.lower() not in _IGNORE_DIRECTIONS:
            c_parts.append(f"eyeline {eye}")
        anchor_items.append(", ".join(c_parts))

    if anchor_items:
        if prev_clip and prev_clip.get("location_id") == clip.get("location_id"):
            parts.append(
                f"CONTINUITY ANCHOR: At 0.0s cut, character body posture, head tilt, and screen direction strictly match the preceding shot: "
                f"[{'; '.join(anchor_items)}]. "
                f"STRICT RULE: No sudden snapping, jump-cut warping, or mirroring of face or body direction across the cut. "
                f"Any change in gaze, head orientation, or posture must occur as a smooth, continuous physical movement during the action timeline."
            )
        else:
            parts.append(
                f"STARTING POSE ANCHOR: At 0.0s, character body posture, head tilt, and screen direction are strictly anchored: "
                f"[{'; '.join(anchor_items)}]. "
                f"Any change in gaze, head angle, or posture must be executed as a smooth, continuous physical movement during the action timeline."
            )

    if airborne_characters:
        parts.append(
            f"AIRBORNE DIRECTIVE: {_join(airborne_characters)} is/are completely airborne in mid-air (hovering/floating), "
            f"suspended above the floorboards with feet off the ground; do NOT ground their feet, stand them on the floor, or spawn them from the floorboards. "
            f"Their elevation must remain strictly suspended in mid-air. "
            f"If already airborne in the scene, they are ALREADY hovering in mid-air at second 0.0; do NOT render another takeoff, eruption, or launch from the ground."
        )

    def _at(posture: str, position: str) -> str:
        # OpenAI often repeats the posture inside the text ("standing frozen in..."); don't say it twice.
        position = position.rstrip(". ")
        return position if position.lower().startswith(posture) else f"{posture}, {position}"
    def _where(b: dict) -> str:
        facing = b["facing"].rstrip(". ")
        # Say "facing" only when OpenAI's text doesn't already ('faces the door', 'starts facing the lockers, then...').
        facing = facing if re.search(r"\b(fac(e|es|ing)|look(s|ing)?|turn(s|ing)?|watch(es|ing)?)\b", facing, re.I) else f"facing {facing}"
        start = _at(b["posture"], b["position"])
        end_pos, end_posture = b.get("end_position", b["position"]), b.get("end_posture", b["posture"])
        profile = b.get("screen_profile", "").strip()
        tilt = b.get("head_tilt", "").strip()
        eye = b.get("eyeline", "").strip()
        details = []
        if profile and profile.lower() not in _IGNORE_DIRECTIONS:
            details.append(profile.replace("_", " "))
        if tilt and tilt.lower() not in _IGNORE_DIRECTIONS:
            details.append(f"head {tilt}")
        if eye and eye.lower() not in _IGNORE_DIRECTIONS:
            details.append(f"eyeline {eye}")
        head_str = f" ({', '.join(details)})" if details else ""

        if end_pos.rstrip(". ") == b["position"].rstrip(". ") and end_posture == b["posture"]:
            return f"{start}{head_str}; {facing}"
        return f"starts {start}{head_str}; ends {_at(end_posture, end_pos)}; {facing}"
    if blocking:
        parts.append("Blocking: " + " ".join(
            f"{b['character']} ({b['in_frame']}): {_where(b)}; {b['awareness'].rstrip('. ')}." for b in blocking))
    props = {p["id"]: p["description"] for p in bible.get("props", [])}
    def _plain(text: str) -> str:
        # Prop ids like 'work_bag' sometimes leak into the prose; Seedance should read plain words.
        for pid in props:
            text = re.sub(rf"\b{re.escape(pid)}\b", pid.replace("_", " "), text)
        return text
    shown = [p for p in clip.get("prop_state", []) if p["in_frame"]]
    if shown:
        parts.append("Props in the shot: " + " ".join(
            f"{props.get(p['prop_id'], p['prop_id']).rstrip('. ')} ({'held by ' + p['holder'] if p['holder'] != 'scene' else 'resting in the scene'}; {p['state'].rstrip('. ')})."
            for p in shown))
    if clip.get("action_steps"):
        parts.append("Action: " + " ".join(f"[{s['start_est']}s to {s['end_est']}s] {_plain(s['action']).rstrip('. ')}." for s in clip["action_steps"]))

    ref_audio_urls = []
    if not clip["dialogue"]:
        parts.append("Nobody speaks.")
    else:
        for turn in clip["dialogue"]:
            spkr = turn["speaker"]
            char = next((c for c in bible["characters"] if c["name"].lower() == spkr.lower()), None)
            voice_url = voice_bank.get(spkr)
            if voice_url and voice_url not in ref_audio_urls and len(ref_audio_urls) < MAX_VOICE_REFS:
                ref_audio_urls.append(voice_url)
            delivery = _delivery_only(turn["delivery"], char["voice"] if char else "")
            if voice_url in ref_audio_urls:
                parts.append(f"[{turn['start_est']}s to {turn['end_est']}s] {spkr} speaks in the voice of @Audio{ref_audio_urls.index(voice_url) + 1}, {delivery}: \"{turn['line']}\"")
            else:
                parts.append(f"[{turn['start_est']}s to {turn['end_est']}s] {spkr} speaks {char['voice'].rstrip('. ') if char else 'naturally'}, {delivery}: \"{turn['line']}\"")
        speakers = list(dict.fromkeys(t["speaker"] for t in clip["dialogue"]))
        parts.append(f"{_join(speakers)} {'is' if len(speakers) == 1 else 'are'} in the frame while speaking; natural dialogue delivery and lip movement matching their line, whether seen in direct view, profile, or dynamic cinematic motion; everyone else keeps their mouth closed.")
    if others:
        parts.append(_plain(others) + ".")
    parts.append("Fluid cinematic physical motion throughout: render active character bodily reactions, natural momentum, and dynamic responsive lighting; characters must not freeze or remain static.")
    parts.append("No background music.")
    return " ".join(parts), ref_image_urls, ref_audio_urls

def trim_windowed_voice(video_path: Path, speaker_name: str, start_est: float, end_est: float, turn_idx: int, dialogue_list: list, out_dir: Optional[Path] = None) -> Path:
    import numpy as np
    safe_name = speaker_name.lower().replace(" ", "_")
    voices_dir = out_dir or ((video_path.parent.parent / "voices") if video_path.parent.name == "clips" else (OUTPUT_DIR / "voices"))
    voices_dir.mkdir(parents=True, exist_ok=True)
    voice_path = voices_dir / f"{safe_name}_{uuid.uuid4().hex[:8]}.wav"
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
    voice_path.parent.mkdir(parents=True, exist_ok=True)
    _run_ffmpeg("-i", str(video_path), "-vn", "-ss", f"{abs_start_sec:.4f}", "-to", f"{abs_end_sec:.4f}", "-c:a", "pcm_s16le", str(voice_path))
    return voice_path

def assemble_test_video(clip_paths: list[Path], output_filename: str) -> Path:
    if not clip_paths: return None
    final_path = OUTPUT_DIR / output_filename
    probes = [app._probe(p) for p in clip_paths]
    width, height, fps = probes[0]["width"], probes[0]["height"], probes[0]["fps"]
    norm_parts = []
    for i, p in enumerate(clip_paths):
        trim = (i > 0)
        norm_file = app._normalized(p, width, height, fps, trim_lead_in=trim)
        norm_parts.append(norm_file)
    listing = OUTPUT_DIR / f"concat_{uuid.uuid4().hex[:6]}.txt"
    listing.write_text("".join(f"file '{p.as_posix()}'\n" for p in norm_parts), encoding="utf-8")
    part = OUTPUT_DIR / f"part_{output_filename}"
    app._run_ffmpeg(
        "-f", "concat", "-safe", "0", "-i", str(listing),
        "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(part),
    )
    part.replace(final_path)
    return final_path

def _write_record(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")

def render_clip(n: int, prompt: str, image_urls: list[str], audio_urls: list[str], interactive: bool = False):
    """Generate clip n on kie.ai, recording every request and reply in requests/clip_NN.json.
    A clip kie.ai refuses is retried once by itself (after the audio copyright filter, with stricter no-music wording);
    in interactive mode, you choose: retry, skip the clip, or quit (everything made so far is kept for --resume).
    In automated mode (default), it retries up to 2 times, then safely halts to preserve credits.
    Returns kie.ai's reply, "skip" or "quit"."""
    record_path = OUTPUT_DIR / "requests" / f"clip_{n:02d}.json"
    old = json.loads(record_path.read_text(encoding="utf-8")) if record_path.exists() else {}
    record = {"attempts": old.get("attempts", [])}
    if "sent_to_kie" in old and "kie_reply" not in old and "attempts" not in old:  # written before failures were recorded
        record["attempts"].append({"sent_to_kie": old["sent_to_kie"], "error": "failed in an earlier run (no reply recorded)"})
    auto_retried = False
    retries_left = 2
    while True:
        # The exact request body generate_clip() sends (same helper), saved before sending and again with kie.ai's reply.
        record["sent_to_kie"] = {"model": app.KIE_MODEL, "input": _clip_input(prompt, RESOLUTION, CLIP_SECONDS, True, None, audio_urls or None, image_urls or None)}
        _write_record(record_path, record)
        t0 = time.time()
        print(f"    generating on kie.ai... (request saved: {record_path})", flush=True)
        try:
            result = generate_clip(prompt=prompt, resolution=RESOLUTION, duration=CLIP_SECONDS, reference_image_urls=image_urls or None, reference_audio_urls=audio_urls or None, generate_audio=True)
        except TimeoutError as te:
            record["attempts"].append({"sent_to_kie": record["sent_to_kie"], "error": str(te)})
            _write_record(record_path, record)
            print(f"    ✗ clip {n} timed out waiting for kie.ai after 15 minutes: {te}", flush=True)
            print("    [Halt] Stopped without re-triggering to prevent double billing. Resume job when ready.", flush=True)
            return "quit"
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
            if not interactive:
                if retries_left > 0:
                    retries_left -= 1
                    print(f"    [Auto] Retrying clip {n} ({retries_left} retries left)...", flush=True)
                    time.sleep(5)
                    continue
                print(f"    ✗ [Auto] Clip {n} failed after retries. Stopping execution to preserve credits.", flush=True)
                return "quit"
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

def _place_urls(entry: dict) -> list[str]:
    """A place's picture links from images.json (runs made before place views existed have one picture)."""
    return [v["url"] for v in entry["views"]] if "views" in entry else [entry["url"]]

def main():
    global CLIPS_PER_CHAPTER  # --chapter-clips can change it for this run
    parser = argparse.ArgumentParser()
    parser.add_argument("topic", nargs="*")
    parser.add_argument("--duration", type=int, default=15, help="Total requested video duration in seconds")
    parser.add_argument("--script-only", action="store_true")
    parser.add_argument("--from-script", help="Use a saved script (JSON) instead of asking OpenAI for a new one; its length replaces --duration")
    parser.add_argument("--resume", action="store_true", help="With --from-script: continue an interrupted run, keeping its clips, pictures and voice samples")
    parser.add_argument("--chapter-clips", type=int, default=CLIPS_PER_CHAPTER, help=f"Clips OpenAI writes per chapter (default {CLIPS_PER_CHAPTER}: script-then-generate each clip)")
    parser.add_argument("--interactive", action="store_true", help="Pause for manual review and prompt confirmation between clips (default is automated)")
    parser.add_argument("-y", "--yes", action="store_true", help="Automatically proceed (default behavior)")
    parser.add_argument("--supervise", action="store_true", help="Enable secondary AI script supervisor call (costs extra OpenAI tokens; default off)")
    args = parser.parse_args()
    CLIPS_PER_CHAPTER = max(1, args.chapter_clips)
    if args.resume and not args.from_script:
        sys.exit("--resume continues an interrupted run: use it with --from-script (the same saved script).")

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
    saved_chapters = []
    if saved:
        # Regroup the saved clips into this version's chapter size (older scripts used 6-clip chapters);
        # an incomplete last chapter is written again by OpenAI.
        flat = [c for chap in saved["chapters"] for c in chap]
        saved_chapters = [flat[i:i + CLIPS_PER_CHAPTER] for i in range(0, len(flat), CLIPS_PER_CHAPTER)]
        if saved_chapters and len(saved_chapters[-1]) < len(_chapter_beats(saved["beats"], len(saved_chapters) - 1)[1]):
            saved_chapters.pop()
    # Save every script this run writes (or completes), so it can be rendered again exactly with --from-script.
    script_path = None if len(saved_chapters) >= chapters_count else SCRIPTS_DIR / f"script_{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:4]}.json"

    if args.resume and not (OUTPUT_DIR / "requests" / "images.json").exists():
        sys.exit(f"Nothing to resume: {OUTPUT_DIR} has no run with pictures in it. Nothing was generated.")
    preflight(fresh=not args.script_only and not args.resume, interactive=args.interactive)

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
        print("\n🏠 LOCATIONS (fixed pictures and layout; every camera angle in that place uses them):")
        for loc in bible["locations"]:
            print(f"  - {loc['id']}: {loc['description']}")
            if loc.get("layout"): print(f"    Layout: {loc['layout']}")
            for i, view in enumerate(loc.get("views", []), 1):
                print(f"    View {i}: {view}{'  (master picture)' if i == 1 else '  (edited from the master)'}")
            print(f"    FLUX Prompt: {loc['image_prompt']}")
        if bible.get("props"):
            print("\n🧰 PROPS (fixed descriptions, written into every clip that shows them):")
            for p in bible["props"]:
                print(f"  - {p['id']}: {p['description']}")
    print("\n📋 BEAT PLAN (one beat per clip):")
    for n, b in enumerate(beats, 1):
        print(f"  {n:02d}. [{b['location_id']}] {'' if b.get('speech', True) else '(silent) '}{b['action']}")
    if problems and not args.script_only:
        if args.interactive:
            if input("\nContinue with this plan anyway? [y/n]: ").strip().lower() != "y":
                print("Stopped before anything was generated.")
                return
        else:
            print("\n  [Auto] Outline check reported minor issues, proceeding with beat plan...")

    cast_bank: dict[str, str] = {}
    location_bank: dict[str, list[str]] = {}
    voice_bank: dict[str, str] = {}
    voice_local: dict[str, Path] = {}
    if args.resume:
        # Same pictures and voice samples as the interrupted run, so faces, rooms and voices match the clips already made.
        images = json.loads((OUTPUT_DIR / "requests" / "images.json").read_text(encoding="utf-8"))
        cast_bank = {name: v["url"] for name, v in images["cast"].items()}
        location_bank = {lid: _place_urls(v) for lid, v in images["locations"].items()}
        mismatched = [c["name"] for c in bible["characters"] if images["cast"].get(c["name"], {}).get("prompt") != c["image_prompt"]]
        mismatched += [l["id"] for l in bible["locations"] if images["locations"].get(l["id"], {}).get("prompt") != l["image_prompt"]]
        if mismatched:
            sys.exit(f"The saved script's picture prompts for {', '.join(mismatched)} differ from the interrupted run's pictures, "
                     "so --resume would not match. Use the same saved script, or start a fresh run. Nothing was generated.")
        print(f"\n[RESUME] Reusing the interrupted run's {len(cast_bank)} cast and {sum(len(u) for u in location_bank.values())} place pictures.")
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
        images = {"cast": {}, "locations": {}}
        for c in bible["characters"]:
            print(f"  Generating image for {c['name']}...", flush=True)
            cast_bank[c["name"]] = generate_flux_image(c["image_prompt"])
            images["cast"][c["name"]] = {"prompt": c["image_prompt"], "url": cast_bank[c["name"]]}
            if cast_bank[c["name"]]: print(f"    Saved: {cast_bank[c['name']]}")
        for loc in bible["locations"]:
            views = loc.get("views") or ["wide view"]
            print(f"  Generating the master picture of {loc['id']} ({views[0]})...", flush=True)
            master = generate_flux_image(loc["image_prompt"])
            entry = {"prompt": loc["image_prompt"], "url": master, "views": [{"view": views[0], "prompt": loc["image_prompt"], "url": master}]}
            if master:
                print(f"    Saved: {master}")
                # The other angles are edits of the master (Kontext keeps its content), so they show the same room, not a new one.
                for view in views[1:PLACE_VIEWS[1]]:
                    print(f"  Generating {loc['id']} {view}...", flush=True)
                    url = generate_flux_image(_view_prompt(view), input_image=master)
                    if url:
                        entry["views"].append({"view": view, "prompt": _view_prompt(view), "url": url})
                        print(f"    Saved: {url}")
            images["locations"][loc["id"]] = entry
            location_bank[loc["id"]] = [v["url"] for v in entry["views"] if v["url"]]
        (OUTPUT_DIR / "requests" / "images.json").write_text(json.dumps(images, indent=2, ensure_ascii=False), encoding="utf-8")
        missing = [name for name, url in cast_bank.items() if not url] + [lid for lid, urls in location_bank.items() if not urls]
        if missing:
            print(f"\n  ⚠ No image for: {', '.join(missing)}. They would be drawn from text alone and change look from clip to clip.")
            if args.interactive:
                if input("Continue anyway? [y/n]: ").strip().lower() != "y":
                    print("Stopped before any video was generated.")
                    return
            else:
                print("  [Auto] Proceeding with video generation...")

    all_clip_video_paths = []
    resume_cmd = f"docker-compose exec api python /srv/media/movie_scene_multispeaker.py --from-script {args.from_script or script_path} --resume"

    all_clips_json = []
    chapters_json = list(saved_chapters)

    if args.script_only and len(saved_chapters) < chapters_count and saved_chapters:
        print(f"  Fast-forwarding {len(saved_chapters)} already-saved clips to resume at Clip {len(saved_chapters) + 1}...\n")

    for chap_idx in range(chapters_count):
        chap_num = chap_idx + 1
        unit_label = f"CLIP {chap_num}/{total_clips}" if CLIPS_PER_CHAPTER == 1 else f"CHAPTER {chap_num}/{chapters_count}"

        if chap_idx < len(saved_chapters):
            script_data = {"clips": saved_chapters[chap_idx]}
            _normalize_clips(script_data["clips"], bible)
            # Fast-forward past already-saved chapters when generating remaining scripts
            if args.script_only and len(saved_chapters) < chapters_count:
                all_clips_json.extend(script_data["clips"])
                continue
            first, mine = _chapter_beats(beats, chap_idx)
            problems = _check_chapter(script_data["clips"], bible, first, mine, all_clips_json)
            _report(f"Saved {unit_label.lower()}", problems)
            all_clips_json.extend(script_data["clips"])
        else:
            print(f"\n=======================================================")
            print(f"[{unit_label}] Generating AI Script...")
            print("=======================================================")
            script_data, problems = write_chapter(topic, chap_idx, chapters_count, beats, bible, all_clips_json, supervise=getattr(args, "supervise", False))
            chapters_json.append(script_data["clips"])
            if script_path:
                save_script(script_path, topic, bible, beats, chapters_json)
            all_clips_json.extend(script_data["clips"])
        if problems and not args.script_only:
            all_exist = True
            for c_idx_rel in range(CLIPS_PER_CHAPTER):
                g_idx = (chap_idx * CLIPS_PER_CHAPTER) + c_idx_rel + 1
                if not (OUTPUT_DIR / "clips" / f"clip_{g_idx:02d}.mp4").exists():
                    all_exist = False
                    break
            if args.resume and all_exist:
                pass
            elif args.interactive:
                if input(f"\nGenerate {unit_label.lower()} anyway? [y/n]: ").strip().lower() != "y":
                    print(f"Stopping before {unit_label.lower()}; nothing was generated for it.")
                    break
            else:
                print(f"  [Auto] Proceeding to generate video for {unit_label}...")

        if args.script_only:
            print("\n🎬 DIRECTOR'S CUT: SCRIPT & PROMPT PREVIEW")
            print("   (The real run sends this same text, except that the place, each character and each already-sampled voice")
            print("    point at their pictures or voice sample: @Image1+ for the place's views, then the cast, @Audio1+ for voices.)")
            print(f"\n🎥 SEEDANCE VIDEO CLIPS ({unit_label}):")
            for c_idx, clip_data in enumerate(script_data["clips"]):
                print(f"\n  ▶ CLIP {(chap_idx * CLIPS_PER_CHAPTER) + c_idx + 1:02d} | Location: {clip_data['location_id']}")
                print(f"    Shot Type: {clip_data['shot']}")
                prev_preview = script_data["clips"][c_idx - 1] if c_idx > 0 else (all_clips_json[-1] if all_clips_json else None)
                prompt_str, _, _ = build_multi_prompt(clip_data, bible, {}, {}, {}, prev_clip=prev_preview)
                print(f"    SEEDANCE PROMPT:\n    > {prompt_str}")

            if chap_num < chapters_count:
                if args.interactive:
                    ans = input("\n[Press Enter to generate next Chapter, or 'q' to stop and review]: ").strip().lower()
                    if ans == "q":
                        print(f"\n✓ Script generation paused at {unit_label}. Saved to:\n  {script_path}\n")
                        break
            continue

        # --- Video Generation Phase ---
        batch_video_paths = []
        all_reused = True
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
            
            all_reused = False
            print(f"\n  {'─'*40}\n  CLIP {global_idx}/{total_clips} (Location: {loc_id})", flush=True)

            active_script = script_path if (script_path and Path(script_path).exists()) else (Path(args.from_script) if (args.from_script and Path(args.from_script).exists()) else None)
            while True:
                prev_clip_script = all_clips_json[-1] if all_clips_json else None
                prompt, ref_image_urls, ref_audio_urls = build_multi_prompt(clip_data, bible, cast_bank, location_bank, voice_bank, prev_clip=prev_clip_script)
                print(f"\n  🎬 COMPILED SEEDANCE PROMPT (Clip {global_idx}/{total_clips}):\n  > {prompt}\n", flush=True)
                if args.interactive:
                    ans = input(f"  Generate Clip {global_idx} on kie.ai? [y = generate, r = reload from script json, q = quit]: ").strip().lower()
                    if ans == "y":
                        break
                    elif ans == "r":
                        target_file = active_script if (active_script and active_script.exists()) else (Path(args.from_script) if (args.from_script and Path(args.from_script).exists()) else None)
                        if target_file and target_file.exists():
                            print(f"  Reloading clip {global_idx} from {target_file}...")
                            raw_data = json.loads(target_file.read_text(encoding="utf-8"))
                            chaps = raw_data.get("chapters", [])
                            if chap_idx < len(chaps) and c_idx_rel < len(chaps[chap_idx]):
                                clip_data = chaps[chap_idx][c_idx_rel]
                                script_data["clips"][c_idx_rel] = clip_data
                                print("  ✓ Reloaded successfully! Updated prompt preview below:")
                            else:
                                print(f"  Could not find chapter {chap_idx} clip {c_idx_rel} in {target_file}")
                        else:
                            print(f"  Script file not found: {target_file}")
                    elif ans == "q":
                        print(f"\nStopped before clip {global_idx}. Everything made so far is kept.")
                        print(f"To continue later:\n  {resume_cmd}")
                        return
                    else:
                        print("  Please enter 'y' to generate, 'r' to reload after editing script JSON, or 'q' to quit.")
                else:
                    break

            result = render_clip(global_idx, prompt, ref_image_urls, ref_audio_urls, interactive=args.interactive)
            if result == "skip":
                print(f"    clip {global_idx} skipped; it's left out of the video (a later --resume makes it again)", flush=True)
                continue
            if result == "quit":
                print(f"\nStopped. Everything made so far is kept in {OUTPUT_DIR}. To continue from clip {global_idx}:\n  {resume_cmd}")
                return

            _download(result["video_url"], clip_path)
            batch_video_paths.append(clip_path)
            all_clip_video_paths.append(clip_path)

            # Voice samples first (saved to voices.json), so stopping at the pause below never loses them for --resume.
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

            # Per-clip completion status
            print(f"\n  ✅ Clip {global_idx}/{total_clips} done! Video saved to container.", flush=True)
            if global_idx < total_clips:
                if args.interactive:
                    print(f"     Copy it out to preview: docker cp \"${{cid}}:/srv/media/movie_scene_multispeaker/clips/clip_{global_idx:02d}.mp4\" .\\clip_{global_idx:02d}.mp4")
                    if input(f"  Continue to Clip {global_idx + 1}? [y/n]: ").strip().lower() != "y":
                        print(f"\nStopped after clip {global_idx}. Everything made so far is kept.")
                        print(f"To continue later:\n  {resume_cmd}")
                        return
                else:
                    print(f"  [Auto] Continuing to Clip {global_idx + 1}...", flush=True)

        # Assemble batch review only when grouping multiple clips per chapter
        if CLIPS_PER_CHAPTER > 1:
            chap_review_filename = f"chapter_{chap_num}_review.mp4"
            assemble_test_video(batch_video_paths, chap_review_filename)

            if chap_num < chapters_count and not all_reused:
                print(f"\n=======================================================")
                print(f"CHAPTER {chap_num} COMPLETE!", flush=True)
                if args.interactive:
                    print(f"Review video: docker cp \"${{cid}}:/srv/media/movie_scene_multispeaker/{chap_review_filename}\" .\\{chap_review_filename}")
                    ans = input(f"\nContinue generating the next {CLIPS_PER_CHAPTER * CLIP_SECONDS} seconds? [y/n]: ").strip().lower()
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
    try:
        main()
    finally:
        client = get_client()
        if client:
            try:
                client.flush()
            except Exception:
                pass

