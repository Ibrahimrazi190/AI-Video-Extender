"""
Hybrid Narrated Drama Mode — Standalone Engine
Implements HYBRID_NARRATED_DRAMA_PLAN.md:
  - First-Person POV Protagonist Voiceover (V.O.)
  - Live Spoken Dialogue Interactions (Lip-Sync)
  - Visceral Shock / Reaction Beats (Foley & Tension)
  - Rapid 20-to-25 Second Micro-Cycles (Alternating Rhythm)

Standalone execution — does NOT modify app.py or movie_scene_multispeaker.py.
Can be run via CLI or imported as a library.
"""

import argparse
import collections
import json
import math
import os
import re
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path

# --- Environment & App Imports ---
sys.path.append(os.getcwd())
import app
app.KIE_MODEL = "bytedance/seedance-2-mini"

from app import (
    OPENAI_API_KEY,
    KIE_API_KEY,
    OPENAI_MODEL,
    KieError,
    generate_clip,
    _clip_input,
    extract_last_frame,
    _download,
    _upload_to_kie,
    _run_ffmpeg,
    _ask_openai_json,
)

import movie_scene_multispeaker as movie

# ---------------------------------------------------------------------------
# Constants & Configuration
# ---------------------------------------------------------------------------
CLIP_SECONDS = 5
RESOLUTION = "480p"
OUTPUT_DIR = Path("/srv/media/hybrid_narrated_drama")
SCRIPTS_DIR = Path("/srv/media/hybrid_narrated_scripts")
CLIPS_PER_CHAPTER = 1
WORDS_PER_SECOND = 2.5
MIN_WORDS, MAX_WORDS = 6, 15
# Narration and dialogue are not symmetrical, and treating them as if they were is what flattened the first
# 5-minute run. Narration COMPRESSES - it skips time and covers what cannot be filmed - so it is rationed:
# two clips in a row is the working length, three is the ceiling and should feel exceptional. Dialogue PLAYS
# - it is the scene actually happening - so it is not chopped. The old rule capped dialogue at 3 clips in a
# row, which meant no confrontation could ever play out; the planner had to wedge voiceover in as spacer,
# and those spacer beats are the ones that narrated a phone call while it was still happening.
MAX_CONSECUTIVE_VO = 3
VO_RUN_WORTH_NOTING = 3          # allowed, but said out loud, because 15 seconds of narration is a lot
DIALOGUE_RUN_WORTH_NOTING = 10   # no hard cap: a scene takes the clips it takes
MAX_VOICE_REFS = 3
MAX_REF_IMAGES = 9
MAX_ON_SCREEN = 7
PLACE_VIEWS = (2, 3)
MIN_STEP_SECONDS = 1.0
SCRIPT_RETRIES = 2
CHAPTER_RETRIES = 3  # a clip script gets one more go than the outline: failing it halts a paid run mid-flight
CLIP_RETRIES = 2
FADE_SECONDS = 0.05
LEAD_IN_FADE = 0.08
AUDIO_RETRY_NOTE = "No background music, no singing, no humming: only the spoken dialogue and natural room sound."

IN_FRAME = ["visible", "partly visible", "off screen", "has left"]
ON_SCREEN = ("visible", "partly visible")
POSTURES = ["standing", "walking", "sitting", "kneeling", "lying down", "crouching", "hovering", "floating"]
FRAME_POSITIONS = [
    "frame left", "left of centre", "centre frame", "right of centre", "frame right",
    "foreground", "background", "off screen"
]
DELIVERY_MODES = ["voiceover", "dialogue", "shock_action"]

_WORD = re.compile(r"[\w'’]+")
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
    return False

LEFT_FRAME_POSITIONS = {"frame left", "left of centre"}
RIGHT_FRAME_POSITIONS = {"frame right", "right of centre"}

def _frame_positions_flip(pos_a: str | None, pos_b: str | None) -> bool:
    if not pos_a or not pos_b:
        return False
    a, b = pos_a.strip().lower(), pos_b.strip().lower()
    return (a in LEFT_FRAME_POSITIONS and b in RIGHT_FRAME_POSITIONS) or (a in RIGHT_FRAME_POSITIONS and b in LEFT_FRAME_POSITIONS)

_INNER_STATE = re.compile(
    r"\b(feels?|felt|realiz(es?|ed)|notic(es?|ed)|sens(es?|ed)|think(s?)|thought|wonders?|wondered|"
    r"understand(s?)|understood|decid(es?|ed)|recogniz(es?|ed)|know(s?)|knew|remembers?|remembered)\b",
    re.I,
)

# A "look" is what the camera sees in EVERY clip, so it may hold only permanent physical facts. A mood sent
# as appearance contradicts whatever the face is actually doing in that clip.
_MOOD_IN_LOOK = re.compile(
    r"\b(anxious|nervous|worried|tense|determined|confident|frightened|scared|terrified|angry|furious|"
    r"sad|happy|desperate|guarded|suspicious|weary|tired|exhausted|hopeful|bitter|uneasy|haunted)\b",
    re.I,
)

# The same rule as _MOOD_IN_LOOK, for the ear instead of the eye. "voice" is the instrument - its pitch,
# grain and accent - not how it is being played in a given scene. A bible that says "low, CONTROLLED alto"
# has written a performance note into a permanent field, and the clip writer then dutifully repeats it in
# every delivery: in the first 5-minute run, 39 of 56 spoken turns asked for restraint and only 2 asked for
# heat, which is why the whole film sounded flat. The model was never the problem - clips 39 and 40, the two
# that did ask for shouting, carry real anger.
# "low, controlled counterstrike without heat" - the clause that takes the emotion back out of a delivery.
# It is always a tail, so cutting it leaves a usable instruction behind.
_CANCELS_EMOTION = re.compile(
    r"[,;]?\s*\b(?:without|with no|never|lacking)\b[^,;]{0,30}?"
    r"\b(?:raised|volume|heat|shout\w*|anger|emotion|inflection|edge)\b[^,;]*",
    re.I,
)

_PERFORMANCE_IN_VOICE = re.compile(
    r"\b(controlled|restrained|measured|calm|quiet|hushed|flat|even|steady|unhurried|contained|"
    r"soft-spoken|monotone|emotionless|deadpan|detached)\b",
    re.I,
)

# Characters in the same uniform are told apart by hair and little else, so hair is compared by family
# rather than by wording: "dark brown" and "chestnut" are the same head of hair to a viewer.
_HAIR_COLORS = {
    "blonde": ("blond", "blonde", "platinum", "flaxen", "golden", "honey"),
    "red": ("red", "ginger", "auburn", "copper", "strawberry", "titian"),
    "brown": ("brown", "brunette", "chestnut", "mousy", "walnut", "sandy"),
    "black": ("black", "jet", "raven", "ebony"),
    "grey": ("grey", "gray", "white", "silver", "salt"),
}
_HAIR_STYLES = {
    "tied_back": ("ponytail", "tied back", "bun", "chignon", "pulled back", "topknot", "tied in"),
    "short": ("bob", "short", "crop", "pixie", "buzz", "shaved", "bald", "undercut"),
    "long_loose": ("long", "loose", "flowing", "shoulder length", "waist length", "worn down"),
    "braided": ("braid", "plait", "cornrow", "dreadlock", "locs", "twists"),
    "curly": ("curly", "curls", "afro", "coiled", "wavy", "ringlets"),
}


def _family(value: str | None, table: dict) -> str:
    """Which coarse family a free-text hair colour or style belongs to ("other" if none matches)."""
    v = _norm_desc(value)
    for fam, words in table.items():
        if any(w in v for w in words):
            return fam
    return "other"


# One template for every cast portrait: a clean, evenly lit, front-facing head-and-shoulders reference — the
# discipline the locations already get ("empty, no people"). An in-scene, half-shadowed character shot is a
# weak identity anchor, and the noir lighting baked into it fights the lighting of every clip it is used in.
_CAST_PORTRAIT = (
    "Photorealistic head-and-shoulders portrait photograph of a {casting}. "
    "Hair: {hair_color}, {hair_style}. Build: {build}. {distinguishing_feature}. Wearing {wardrobe}. "
    "Front-facing, looking straight into the lens, neutral relaxed expression, mouth closed. "
    "Even soft studio key light across the whole face, plain mid-grey seamless background, "
    "no props, no scenery, no text, nobody else in frame. "
    "Shot on an 85mm lens at f/2.8, 8k, natural detailed skin texture and pores, sharp focus on the eyes, "
    "live-action movie still, NO CGI, NO 3D render, NO illustration, NO plastic skin."
)

_APPEARANCE_FIELDS = ("casting", "hair_color", "hair_style", "build", "distinguishing_feature", "wardrobe")

# A location reference is a clean plate of the empty place. Anyone standing in it gets painted into every
# clip shot there - and a plate that shows the story's payoff shows it from the first clip onward.
_LOCATION_PLATE = (
    "{prompt}. The place is EMPTY: nobody in frame, no people at all, and none of the story's props. "
    "Photorealistic, live-action movie still, shot on Arri Alexa, 8k, detailed textures and materials, "
    "natural light falloff, NO CGI, NO 3D render, NO illustration."
)

_PERSON_IN_PLATE = re.compile(
    r"\b(man|woman|men|women|person|people|boy|girl|guy|lady|figure|silhouette|someone|somebody|"
    r"crowd|anyone|couple|pair of hands)\b", re.I,
)


def _compile_location_image_prompt(loc: dict) -> str:
    return _LOCATION_PLATE.format(prompt=(loc.get("image_prompt") or loc.get("description") or loc.get("id", "")).rstrip(". "))


def _compile_location_visuals(bible: dict) -> None:
    """Append the empty-plate and photorealism wording to every location's picture prompt, once."""
    for loc in bible.get("locations", []):
        if loc.get("image_prompt") and "The place is EMPTY" in loc["image_prompt"]:
            continue  # already compiled
        loc["image_prompt"] = _compile_location_image_prompt(loc)


def _clean_voices(bible: dict) -> list[str]:
    """Cut performance words out of each character's permanent `voice`, in place.

    "low, controlled alto" is a permanent field holding a note about how one line is played, and the clip
    writer then repeats it in every delivery for the rest of the film. Striking the word needs no judgement,
    so it is struck rather than re-asked: a retry is an OpenAI call, and a bad voice that survived the
    retries would fail the plan at the final whole-plan check, after all six planning calls were paid for.
    The validator in `_check_scene_bible` stays as a backstop for anything this cannot tidy."""
    notes = []
    for c in bible.get("characters", []):
        voice = (c.get("voice") or "").strip()
        if not voice or not _PERFORMANCE_IN_VOICE.search(voice):
            continue
        cleaned = _PERFORMANCE_IN_VOICE.sub("", voice)
        cleaned = re.sub(r"\s*,\s*,+", ", ", cleaned)
        cleaned = re.sub(r"\s{2,}", " ", cleaned).strip(" ,;")
        cleaned = re.sub(r"^(and|but|with)\s+", "", cleaned, flags=re.I)
        cleaned = re.sub(r"\s+(and|but|with)$", "", cleaned, flags=re.I).strip(" ,;")
        # If striking the word left nothing usable ("quiet and controlled" -> "and"), leave the original
        # alone and let the validator ask for a real one; a garbled voice is worse than a retry.
        _FILLER = {"and", "but", "with", "the", "that", "very", "quite", "rather"}
        if not any(len(w) >= 3 and w not in _FILLER for w in re.findall(r"[A-Za-z]+", cleaned.lower())):
            continue
        c["voice"] = cleaned
        notes.append(f"{c.get('name', '?')}: voice {voice!r} -> {cleaned!r}")
    return notes


def _compile_bible_visuals(bible: dict) -> None:
    """Everything the picture models are sent, derived from the bible in one place."""
    _compile_character_visuals(bible)
    _compile_location_visuals(bible)
    for note in _clean_voices(bible):
        print(f"  repaired {note}")


def _compile_look(appearance: dict) -> str:
    """The one-line description, used only for a character who has no reference picture."""
    hair = f"{appearance.get('hair_color', '')} hair, {appearance.get('hair_style', '')}".strip(" ,")
    parts = (appearance.get("casting", ""), hair, appearance.get("build", ""),
             appearance.get("distinguishing_feature", ""), appearance.get("wardrobe", ""))
    return ", ".join(p.rstrip(". ") for p in parts if p and p.strip())


def _compile_cast_image_prompt(appearance: dict) -> str:
    fields = {k: (appearance.get(k) or "").rstrip(". ") for k in _APPEARANCE_FIELDS}
    feature = fields["distinguishing_feature"]
    fields["distinguishing_feature"] = feature[:1].upper() + feature[1:]  # it opens its own sentence
    return _CAST_PORTRAIT.format(**fields)


def _compile_character_visuals(bible: dict) -> None:
    """Write every character's "look" and "image_prompt" from the one structured "appearance".

    Both used to be free-text fields OpenAI wrote separately, so the picture FLUX drew and the text sent
    beside it in every Seedance prompt described different people (a brown ponytail captioned "tidy
    dark-blonde bob"), and the model picked a different winner in each clip. Generating both from a single
    source means they cannot disagree."""
    for c in bible.get("characters", []):
        appearance = c.get("appearance")
        if not appearance:
            continue  # an older bible that already carries hand-written look/image_prompt
        c["look"] = _compile_look(appearance)
        c["image_prompt"] = _compile_cast_image_prompt(appearance)


# ---------------------------------------------------------------------------
# Schema Definitions
# ---------------------------------------------------------------------------
APPEARANCE_SCHEMA = {
    "type": "object",
    "description": "Permanent physical facts only - what the camera sees in EVERY clip. No moods, no emotions, no story events.",
    "properties": {
        "casting": {"type": "string", "description": "How the character reads on screen, in a few words: 'woman in her late twenties', 'man in his fifties'."},
        "hair_color": {"type": "string", "description": "One plain colour and nothing else: 'copper red', 'jet black', 'ash blonde'. Never leave this vague or absent."},
        "hair_style": {"type": "string", "description": "Length and how it is worn: 'short bob, worn loose', 'long, tied in a low ponytail'."},
        "build": {"type": "string", "description": "Height and build: 'tall and lean', 'short, broad-shouldered'."},
        "distinguishing_feature": {"type": "string", "description": "One permanent feature that separates this character from everyone else on screen: 'freckles and a scar through the left eyebrow', 'heavy black-framed glasses'."},
        "wardrobe": {"type": "string", "description": "The fixed clothing worn throughout: 'neat navy hotel uniform with a brass name tag'."}
    },
    "required": ["casting", "hair_color", "hair_style", "build", "distinguishing_feature", "wardrobe"],
    "additionalProperties": False
}

OUTLINE_SCHEMA = {
    "type": "object",
    "properties": {
        "scene_bible": {
            "type": "object",
            "properties": {
                "pov_protagonist": {
                    "type": "string",
                    "description": "The exact name of the single main character whose first-person POV narrates the story."
                },
                "characters": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "is_protagonist": {"type": "boolean"},
                            "role": {"type": "string"},
                            "appearance": APPEARANCE_SCHEMA,
                            "voice": {"type": "string", "description": "The INSTRUMENT only - pitch, grain, accent: 'smoky alto with a faint Irish lilt', 'gravelled baritone', 'bright soprano with a Boston edge'. Never how it is played: no 'controlled', 'quiet', 'measured', 'calm', 'flat'. How a line is delivered changes every clip and belongs to that clip's delivery."}
                        },
                        "required": ["name", "is_protagonist", "role", "appearance", "voice"],
                        "additionalProperties": False
                    }
                },
                "props": {
                    "type": "array",
                    "description": "Every object a character carries, picks up, sets down, uses, changes or breaks in the story. Not furniture, and not what characters wear. An empty list if there are none.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string", "description": "snake_case, e.g. 'laundry_cart', 'silver_case'."},
                            "description": {"type": "string", "description": "Its full fixed look, e.g. 'a wheeled canvas laundry cart stacked with folded white sheets'."}
                        },
                        "required": ["id", "description"],
                        "additionalProperties": False
                    }
                },
                "locations": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string"},
                            "description": {"type": "string"},
                            "layout": {
                                "type": "string",
                                "description": "Fixed spatial map of the place: entrances, doors, desks, furniture, windows."
                            },
                            "image_prompt": {"type": "string"},
                            "views": {"type": "array", "items": {"type": "string"}}
                        },
                        "required": ["id", "description", "layout", "image_prompt", "views"],
                        "additionalProperties": False
                    }
                }
            },
            "required": ["pov_protagonist", "characters", "props", "locations"],
            "additionalProperties": False
        },
        "beats": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "clip_number": {"type": "integer"},
                    "cycle_number": {"type": "integer"},
                    "delivery_mode": {
                        "type": "string",
                        "enum": ["voiceover", "dialogue", "shock_action"]
                    },
                    "location_id": {"type": "string"},
                    "present_characters": {"type": "array", "items": {"type": "string"}},
                    "speaker_or_actor": {
                        "type": "string",
                        "description": "ONE character name and nothing else - never two names, never a slash, never a prop or a place. Whose beat this is: for voiceover the pov_protagonist, for dialogue the character the beat belongs to (each line already carries its own speaker in audio_lines), for shock_action the pov_protagonist, or an empty string for an establishing shot with nobody on screen."
                    },
                    "summary": {"type": "string"},
                    "speech_budget": {"type": "integer"},
                    "audio_lines": {
                        "type": "array",
                        "description": "The EXACT words heard in this clip, in the order they are heard, decided here and nowhere else. voiceover: exactly ONE line, by the pov_protagonist. dialogue: ONE to THREE lines that together make a real exchange (a jab and its retort can share one clip). shock_action: an empty array.",
                        "items": {
                            "type": "object",
                            "properties": {
                                "speaker": {"type": "string", "description": "Who says this line. For a voiceover beat this is the pov_protagonist."},
                                "line": {"type": "string", "description": "The exact words spoken."}
                            },
                            "required": ["speaker", "line"],
                            "additionalProperties": False
                        }
                    },
                    "reveals": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Short key terms for facts the audience learns for the FIRST time in this beat: names, places, room numbers, objects (e.g. ['Room 404', '404', 'Julian Cross']). Empty if this beat reveals nothing new."
                    }
                },
                "required": [
                    "clip_number", "cycle_number", "delivery_mode", "location_id",
                    "present_characters", "speaker_or_actor", "summary", "speech_budget",
                    "audio_lines", "reveals"
                ],
                "additionalProperties": False
            }
        }
    },
    "required": ["scene_bible", "beats"],
    "additionalProperties": False
}

ACT_BREAKDOWN_SCHEMA = {
    "type": "object",
    "properties": {
        "scene_bible": OUTLINE_SCHEMA["properties"]["scene_bible"],
        "acts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "act_number": {"type": "integer"},
                    "title": {"type": "string"},
                    "primary_locations": {"type": "array", "items": {"type": "string"}},
                    "dramatic_question": {"type": "string"},
                    "start_clip": {"type": "integer"},
                    "end_clip": {"type": "integer"},
                    "summary": {"type": "string"},
                    "reveals": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Key terms the audience learns for the FIRST time in this act - names, places, room numbers, objects. Each term belongs to exactly ONE act: the act that discloses it. Earlier acts may not speak it."
                    }
                },
                "required": [
                    "act_number", "title", "primary_locations",
                    "dramatic_question", "start_clip", "end_clip", "summary", "reveals"
                ],
                "additionalProperties": False
            }
        }
    },
    "required": ["scene_bible", "acts"],
    "additionalProperties": False
}

ACT_BEATS_SCHEMA = {
    "type": "object",
    "properties": {
        "beats": OUTLINE_SCHEMA["properties"]["beats"]
    },
    "required": ["beats"],
    "additionalProperties": False
}


def _narrated_chapter_schema(location_ids: list[str], character_names: list[str],
                             prop_ids: list[str] | None = None) -> dict:
    """Builds a dynamic JSON schema strictly constraining locations, characters and props."""
    loc_prop = (
        {"type": "string", "enum": location_ids, "description": "The exact Scene Bible location this clip is set in."}
        if location_ids else {"type": "string", "description": "The Scene Bible location this clip is set in."}
    )
    char_items = (
        {"type": "string", "enum": character_names}
        if character_names else {"type": "string"}
    )
    char_prop = (
        {"type": "string", "enum": character_names}
        if character_names else {"type": "string"}
    )
    return {
        "type": "object",
        "properties": {
            "clips": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "clip_number": {"type": "integer"},
                        "delivery_mode": {
                            "type": "string",
                            "enum": ["voiceover", "dialogue", "shock_action"]
                        },
                        "location_id": loc_prop,
                        "shot": {
                            "type": "string",
                            "description": "Camera framing and angle prefixed with [SAME SETUP] or [ANGLE CUT]."
                        },
                        "present_characters": {
                            "type": "array",
                            "items": char_items,
                            "description": "Characters physically visible on screen."
                        },
                        "speech": {
                            "type": "array",
                            "description": "Everything heard in this clip, in time order, one entry per spoken line. voiceover: exactly one entry. dialogue: one to three entries, by up to three different speakers. shock_action: an empty array. Every line is the Master Plan's, copied word for word.",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "speaker": char_prop,
                                    "line": {"type": "string", "description": "The Master Plan's words for this turn, copied exactly."},
                                    "delivery": {"type": "string", "description": "How this turn is delivered, matching the heat of THIS moment. The full range is available and the film needs all of it: 'roared, furious, voice breaking', 'shouted over the rain', 'spat out through clenched teeth', 'laughing, delighted and cruel', 'pleading, close to tears', 'sharp accusation', 'cold, resolute warning', 'barely a whisper'. Never write a delivery that cancels its own emotion ('fury without raised volume')."},
                                    "start_est": {"type": "number", "description": "When this turn starts, in seconds inside the clip (0.0 to 5.0). The first turn starts at 0.4s or later so the picture settles first."},
                                    "end_est": {"type": "number", "description": "When this turn ends, in seconds inside the clip (at most 4.8). Turns must not overlap: each one starts after the previous one ends."}
                                },
                                "required": ["speaker", "line", "delivery", "start_est", "end_est"],
                                "additionalProperties": False
                            }
                        },
                        "environment": {
                            "type": "string",
                            "description": "What the PLACE itself does during this clip: weather, light, machinery, doors, a ringing bell, a lift, a flickering monitor, rain on glass. Never people - nobody is described here. An empty string if the place is simply still.",
                        },
                        "prop_state": {
                            "type": "array",
                            "description": "Only the props this clip actually needs: every prop IN SHOT, plus any prop whose holder or state CHANGED here. Leave out anything off camera and unchanged - the system carries those forward for you, so listing them again is wasted.",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "prop_id": {"type": "string", "enum": (prop_ids or ["(no props)"])},
                                    "holder": {"type": "string", "description": "The character holding or carrying it, or 'scene' when it rests somewhere."},
                                    "in_frame": {"type": "boolean", "description": "true only if the camera clearly sees it where the action happens; a prop elsewhere in the room or far in the background is false, or the video model draws it into the shot."},
                                    "state": {"type": "string", "description": "Its condition and exactly where it is, e.g. 'stacked with clean linens, parked at the desk corner'."}
                                },
                                "required": ["prop_id", "holder", "in_frame", "state"],
                                "additionalProperties": False
                            }
                        },
                        "action_steps": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "start_time": {"type": "number"},
                                    "character": char_prop,
                                    "action": {"type": "string"}
                                },
                                "required": ["start_time", "character", "action"],
                                "additionalProperties": False
                            }
                        },
                        "blocking": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "character": char_prop,
                                    "position": {"type": "string", "description": "Where they are at 0.0s, the instant of the cut."},
                                    "posture": {"type": "string", "enum": POSTURES, "description": "Their posture at 0.0s."},
                                    "screen_profile": {"type": "string", "description": "Which way they face the camera at 0.0s."},
                                    "frame_position": {
                                        "type": "string",
                                        "enum": FRAME_POSITIONS,
                                        "description": "Where they appear horizontally on the 2D screen at 0.0s ('off screen' if in_frame is 'off screen' or 'has left')."
                                    },
                                    "eyeline": {"type": "string", "description": "Where they are looking at 0.0s."},
                                    "end_position": {"type": "string", "description": "Where they are when this clip ENDS, after the action steps have played out. Same as position if they do not move."},
                                    "end_posture": {"type": "string", "enum": POSTURES, "description": "Their posture when this clip ENDS. The NEXT clip must open on this."},
                                    "end_screen_profile": {"type": "string", "description": "Which way they face when this clip ENDS. The next clip must open on this."},
                                    "end_frame_position": {
                                        "type": "string",
                                        "enum": FRAME_POSITIONS,
                                        "description": "Where in the FRAME they are when this clip ENDS. Same as frame_position unless an action step walks them across the shot. The next clip must open on this.",
                                    },
                                    "end_eyeline": {"type": "string", "description": "Where they are looking when this clip ENDS."},
                                    "awareness": {"type": "string", "description": "What this character has noticed SO FAR that matters, and what they have not: 'has not noticed the lift doors open', 'saw the monitor flash ROOM 404', 'believes she is alone in the lobby'."},
                                    "in_frame": {"type": "string", "enum": IN_FRAME}
                                },
                                "required": ["character", "position", "posture", "screen_profile", "frame_position", "eyeline",
                                             "end_position", "end_posture", "end_screen_profile", "end_frame_position",
                                             "end_eyeline", "awareness", "in_frame"],
                                "additionalProperties": False
                            }
                        }
                    },
                    "required": [
                        "clip_number", "delivery_mode", "location_id", "shot",
                        "present_characters", "speech", "environment", "prop_state", "action_steps", "blocking"
                    ],
                    "additionalProperties": False
                }
            }
        },
        "required": ["clips"],
        "additionalProperties": False
    }

CHAPTER_SCHEMA = _narrated_chapter_schema([], [])

SUPERVISOR_SCHEMA = {
    "type": "object",
    "properties": {
        "problems": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Short sentences describing genuine continuity violations to fix, or empty if none."
        }
    },
    "required": ["problems"],
    "additionalProperties": False,
}


# ---------------------------------------------------------------------------
# Prompt Directives & Validation
# ---------------------------------------------------------------------------
def _narrated_outline_prompt(topic: str, duration: int, total_clips: int) -> tuple[str, str]:
    """Builds prompt for the Master Plan, enforcing rapid 20-to-25s micro-cycles and location continuity."""
    system_prompt = f"""You are a master showrunner and director for viral dramatic mini-series (ReelShort / DramaBox style).
You are directing a {duration}-second narrative divided into exactly {total_clips} continuous 5-second video clips.

CORE ARCHITECTURE: HYBRID NARRATED DRAMA (FIRST-PERSON POV + LIVE DIALOGUE):
1. SINGLE POV PROTAGONIST:
   - Identify the single main lead character whose life/journey we follow.
   - In scene_bible, set is_protagonist: true for this character, and set pov_protagonist to their name.
   - All voiceover (V.O.) in the entire series is strictly narrated in FIRST-PERSON ("I", "my", "we") in their voice!

2. SCENES PLAY, BRIDGES SKIP (CRITICAL):
   Do NOT clump all voiceovers at the start or all dialogues at the end, and do NOT chop the story into equal pieces. There are two kinds of stretch, and the difference is what makes a drama watchable:
     * A SCENE (delivery_mode='dialogue'): a moment PLAYED OUT in real time, people in a room doing things to each other. This is where the drama is, and it needs room - a real confrontation runs many clips in a row and must NOT be broken up. Let it build: proposition, objection, leverage, counter, ultimatum, decision.
     * A BRIDGE (delivery_mode='voiceover'): time SKIPPED, or consequences landing. 1 to 2 clips of the protagonist's narration over strong visuals, 3 at the absolute most, and then we are somewhere new with everything changed. "I closed every port he owned" is a bridge - two clips. A bridge NEVER narrates a scene that is still playing in front of the camera; it moves us past what we do not need to watch.
     * Phase 3: THE WORDLESS BEAT (0 or 1 clip, delivery_mode='shock_action'):
       Used ONLY when the story genuinely gives you one. Two kinds:
         (a) THE SHOCKWAVE - the protagonist's own visceral reaction to something that just physically happened (a frozen stare, a gasped recoil, a dropped glass). Other characters in the shot may react too, but the camera stays with the protagonist.
         (b) THE ESTABLISHING SHOT - nobody on screen at all: the building from the street, a lift door sliding open, rain running down a window, an empty corridor. It tells the viewer where the next scene happens, exactly as a normal film or drama does. For these, present_characters MUST be empty and speaker_or_actor MUST be empty.
       NEVER invent a jolt to fill this slot. If nothing physically happens at this point in the story, SKIP Phase 3 and carry straight on with dialogue or voiceover. A manufactured shock is worse than no shock: it stops the scene dead and steals the moment from whoever it is really about.
   Alternate between the two as the STORY demands, never on a timer. Follow the story first; the rhythm serves it, never the other way round.

3. LOCATION CONTINUITY & CONFINEMENT (CRITICAL):
   - Confinement within an act, progression between acts.
   - A dramatic sequence must anchor in 1 to 2 core locations (e.g. the main reception desk, the office) across consecutive beats. Do NOT jump between random unestablished rooms or hallways every 5 seconds.
   - Across a full narrative, the story must progress between distinct locations as dramatic acts unfold (for 30+ clips, establish 4 to 8 distinct locations).
   - Every single beat's location_id MUST match one of the exact ids defined in scene_bible.locations.
   - A room is ONE location however many angles it is filmed from: never make separate locations for different angles of the same room. Places in the same building must match each other in architecture, era and materials.
   - "description": its fixed look in one or two sentences (architecture, furniture, materials, colours, light), true for the WHOLE story.
   - "layout": a fixed map every clip set there follows - each door, window, staircase and the main furniture, placed relative to the main entrance, stating how many of each there are ('the only door', 'two lifts'), and including every feature the story uses there (a counter someone hides behind, a lift, a back corridor).
   - "views": 2 or 3 camera VIEWPOINTS for the reference pictures, ALL showing the place EMPTY - 'from the entrance looking at the desk', 'from behind the desk looking out'. A viewpoint is a place to stand, NOT a shot from the story: never 'Clara POV', never an insert of a story object.
   - "image_prompt": a text-to-image prompt for a wide view from the FIRST viewpoint, naming every permanent feature the story uses there (the video model can only use what the picture shows). It must contain NO PEOPLE and NONE of the story's props or payoffs: a reference plate showing a character standing in the doorway puts them in every clip filmed there, and one showing the story's final reveal shows it from the very first clip. The system adds the photorealism and empty-room wording for you.

4. CASTING THE SCREEN (CRITICAL):
   - CASTING RULE: unless the premise asks for a specific ethnicity, default the cast to Western, European or British demographics.
   - STATIC BIBLE RULE: "appearance" and "voice" hold ONLY permanent, unchanging physical facts ('tall and lean', 'jet black hair', 'smoky alto with a faint Irish lilt'). NEVER put a mood, an emotion or a story event there ('anxious', 'determined', 'starts hopeful') - those belong to a clip's delivery and action.
   - "voice" IS THE INSTRUMENT, NOT THE PERFORMANCE (CRITICAL): give its pitch, grain and accent only. NEVER 'controlled', 'quiet', 'measured', 'calm', 'flat' or 'restrained' - those describe how someone is speaking in one moment, and written here they make EVERY line in the film inherit them. A character whose voice is 'low, controlled alto' will never be allowed to shout.
   - VISUAL SEPARATION RULE: each character's reference portrait is generated automatically from "appearance", and these clips are watched on a phone in dark, dim rooms. Every character MUST be identifiable at a glance:
     * No two characters may share a hair colour. If the story dresses them in the same uniform, their hair colour AND hair style must BOTH differ.
     * Every character needs a real "distinguishing_feature" - something visible on the face or head. Never 'none'.
   - Fill every "appearance" field precisely. It is the only description of that character the camera will ever get.
   - PROPS: list in "props" every object a character carries, picks up, sets down, uses, changes or breaks in the story (a laundry cart, a silver case, a phone receiver, a knife), each with a snake_case "id" and a full fixed "description" of how it looks. NOT furniture that simply stands in the room, and NOT what characters wear - clothes, glasses and jewellery belong to "appearance". One prop is one object, never 'their bags'. An empty list if the story has none.

5. THE SPOKEN WORD IS DECIDED HERE (CRITICAL):
   - You are the ONLY writer who sees the whole story, so YOU write every line, in "audio_lines": the exact words the audience hears in that clip, in order. The clip director downstream writes only what is SEEN, and will be forced to speak your lines verbatim.
   - A DIALOGUE beat may hold ONE, TWO or THREE lines, by up to {MAX_VOICE_REFS} different speakers. Use more than one whenever the exchange is quick - a jab and its retort belong in the SAME clip, not split across a cut. Use one line when it is meant to hang.
   - A VOICEOVER beat holds exactly ONE line, by the pov_protagonist. A shock_action beat holds an EMPTY array.
   - VOICE SAMPLES: the FIRST line a character speaks in the whole video is cut out of that clip and reused as their voice everywhere after, so make it a clear, fully voiced line of at least {VOICE_SAMPLE_MIN_WORDS} words - never their short one- or two-word reply. Introduce a character's voice on a beat where they carry the line, then let them trade quick fire afterwards.
   - The clip is only {CLIP_SECONDS} seconds long, so "speech_budget" - the TOTAL words across every line in the beat - must be {MIN_WORDS} to {MAX_WORDS}. Three speakers in one clip means roughly four words each: "Where is she?" / "Gone." / "You are lying." Short, hard lines land; long ones get cut off.
   - PLAIN, SPEAKABLE WORDS (CRITICAL): everybody - the narrator included - talks like a person in a modern film. Short, common words anyone understands the first time they hear them. NO poetry, no metaphor stacking, no literary inversion, no semicolons, no archaic or ornate phrasing, no abstract nouns doing the work of a verb.
     * BAD (do not write like this): "Three years I kept him breathing; tonight, he offered ink." / "My clearance turned green while his power learned rain." / "mercy recognizes old footsteps"
     * GOOD (write like this): "Three years I kept him alive. Tonight he hands me a pen." / "My ship cleared while his city drowned." / "He has begged in front of me before."
   - The narration is her thinking, not her writing. It says the thing the picture cannot - what she wants, what it costs, what she will not say out loud - in the plainest words that will carry it.
   - REVEAL ORDER (CRITICAL): a line may only use what the audience already knows. List in "reveals" the key terms each beat discloses for the FIRST time - names, places, room numbers, objects. NEVER let an earlier beat's lines speak a term that a later beat reveals: the protagonist cannot name Room 404 in clip 2 if a co-worker reveals it in clip 3.

6. ABSOLUTE RULES:
   - NEVER have more than 3 consecutive voiceover clips, and 2 is the working length: past that the viewer is listening to someone think instead of watching something happen.
   - Consecutive dialogue clips are NOT capped. A scene takes the clips it takes; never break one up just to insert narration.
   - For shock_action clips, speech_budget must be 0 and audio_lines must be an empty array.
   - For voiceover and dialogue clips, speech_budget must be {MIN_WORDS} to {MAX_WORDS} words.
   - This is a FIRST-PERSON story, so when a shock_action beat has ANY people in it, the camera stays with the pov_protagonist: they must be among its present_characters and be its speaker_or_actor. Everyone else present may still react in the clip - they simply are not who the shot is about. A shock_action beat with NOBODY on screen (an establishing or atmospheric shot) has empty present_characters and an empty speaker_or_actor.
"""
    user_prompt = f"Story Premise:\n{topic}\n\nGenerate the complete Master Plan for {total_clips} clips ({duration}s total)."
    return system_prompt, user_prompt


_WORD_TO_NUM = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "eleven": 11, "twelve": 12,
}
_ACT_COUNT_RE = re.compile(
    r"\b(?:(\d+)|(one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve))\s*-?\s*acts?\b",
    re.I
)


def _detect_premise_act_count(topic: str) -> int | None:
    """Detects if the user explicitly requested a specific act count in the topic/premise."""
    m = _ACT_COUNT_RE.search(topic or "")
    if not m:
        return None
    val = int(m.group(1)) if m.group(1) else _WORD_TO_NUM.get(m.group(2).lower())
    if val is not None and 2 <= val <= 12:
        return val
    return None


def _normalize_act_spans(acts: list[dict], total_clips: int) -> list[dict]:
    """Ensures act spans strictly cover clips 1..total_clips continuously without gaps or overlaps."""
    if not acts:
        n = 4 if total_clips >= 60 else max(2, round(total_clips / 15))
        clip_per_act = total_clips // n
        res = []
        cur = 1
        for i in range(1, n + 1):
            end = cur + clip_per_act - 1 if i < n else total_clips
            res.append({
                "act_number": i,
                "title": f"Act {i}",
                "primary_locations": [],
                "dramatic_question": "",
                "start_clip": cur,
                "end_clip": end,
                "summary": "",
                "reveals": []
            })
            cur = end + 1
        return res

    normalized = []
    n_acts = len(acts)
    cur_start = 1

    for idx, act in enumerate(acts):
        a = dict(act)
        a["act_number"] = idx + 1
        a["start_clip"] = cur_start

        if idx == n_acts - 1:
            a["end_clip"] = total_clips
        else:
            raw_end = a.get("end_clip")
            try:
                raw_end = int(raw_end)
            except (TypeError, ValueError):
                raw_end = cur_start + (total_clips // n_acts) - 1

            min_end = cur_start
            max_end = total_clips - (n_acts - 1 - idx)
            a["end_clip"] = max(min_end, min(raw_end, max_end))

        cur_start = a["end_clip"] + 1
        normalized.append(a)

    return normalized


def _plan_act_batches(acts: list[dict]) -> list[dict]:
    """Plans generation batches from acts, splitting acts > 20 clips and merging acts < 6 clips."""
    initial_chunks = []
    for a in acts:
        start = a["start_clip"]
        end = a["end_clip"]
        span = end - start + 1
        if span > 20:
            num_splits = math.ceil(span / 20)
            chunk_size = math.ceil(span / num_splits)
            cur = start
            base_title = a.get("title") or f"Act {a.get('act_number', '')}"
            for s in range(num_splits):
                s_end = min(cur + chunk_size - 1, end) if s < num_splits - 1 else end
                initial_chunks.append({
                    "act_numbers": [a["act_number"]],
                    "start_clip": cur,
                    "end_clip": s_end,
                    "clip_count": s_end - cur + 1,
                    "title": f"{base_title} (Part {s+1}/{num_splits})",
                    "primary_locations": a.get("primary_locations", []),
                    "dramatic_question": a.get("dramatic_question", ""),
                    "summary": a.get("summary", ""),
                })
                cur = s_end + 1
        else:
            initial_chunks.append({
                "act_numbers": [a["act_number"]],
                "start_clip": start,
                "end_clip": end,
                "clip_count": span,
                "title": a.get("title", f"Act {a['act_number']}"),
                "primary_locations": a.get("primary_locations", []),
                "dramatic_question": a.get("dramatic_question", ""),
                "summary": a.get("summary", ""),
            })

    batches = []
    for c in initial_chunks:
        if batches and (batches[-1]["clip_count"] < 6 or c["clip_count"] < 6):
            if batches[-1]["clip_count"] + c["clip_count"] <= 20:
                prev = batches[-1]
                prev["end_clip"] = c["end_clip"]
                prev["clip_count"] += c["clip_count"]
                prev["act_numbers"].extend(c["act_numbers"])
                prev["title"] = f"{prev['title']} & {c['title']}"
                prev["primary_locations"] = list(dict.fromkeys(prev["primary_locations"] + c["primary_locations"]))
                prev["dramatic_question"] = f"{prev['dramatic_question']} / {c['dramatic_question']}".strip(" /")
                prev["summary"] = f"{prev['summary']} {c['summary']}".strip()
                continue
        batches.append(dict(c))

    for i, b in enumerate(batches, 1):
        b["batch_index"] = i

    return batches


def _narrated_act_breakdown_prompt(topic: str, duration: int, total_clips: int,
                                   act_count: int | None = None) -> tuple[str, str]:
    """Builds prompt for Act Breakdown Call 1: Scene Bible + Acts Structure."""
    default_acts = act_count if act_count else (4 if total_clips >= 60 else max(2, round(total_clips / 15)))
    act_instruction = (
        f"Divide the {duration}s story ({total_clips} clips) into exactly {act_count} narrative acts as requested in the premise."
        if act_count else
        f"Divide the {duration}s story ({total_clips} clips) into about {default_acts} narrative acts. "
        f"Size each one by what it has to do, NOT by dividing {total_clips} evenly - unequal acts are expected and correct."
    )

    system_prompt = f"""You are a master showrunner and director for viral dramatic mini-series (ReelShort / DramaBox style).
You are architecting the Scene Bible and multi-act structure for a {duration}-second narrative divided into exactly {total_clips} continuous 5-second video clips.

CORE ARCHITECTURE: HYBRID NARRATED DRAMA (ACT BREAKDOWN & SCENE BIBLE)

1. SINGLE POV PROTAGONIST:
   - Identify the single main lead character whose life/journey we follow.
   - In scene_bible, set is_protagonist: true for this character, and set pov_protagonist to their name.
   - All voiceover (V.O.) in the entire series is strictly narrated in FIRST-PERSON ("I", "my", "we") in their voice!

2. CASTING THE SCREEN & STATIC BIBLE:
   - CASTING RULE: unless the premise asks for a specific ethnicity, default the cast to Western, European or British demographics.
   - STATIC BIBLE RULE: "appearance" and "voice" hold ONLY permanent, unchanging physical facts ('tall and lean', 'jet black hair', 'smoky alto with a faint Irish lilt'). NEVER put a mood, an emotion or a story event there ('anxious', 'determined', 'starts hopeful') - those belong to a clip's delivery and action.
   - "voice" IS THE INSTRUMENT, NOT THE PERFORMANCE (CRITICAL): give its pitch, grain and accent only. NEVER 'controlled', 'quiet', 'measured', 'calm', 'flat' or 'restrained' - those describe how someone is speaking in one moment, and written here they make EVERY line in the film inherit them. A character whose voice is 'low, controlled alto' will never be allowed to shout.
   - VISUAL SEPARATION RULE: each character's reference portrait is generated automatically from "appearance", and these clips are watched on a phone in dark, dim rooms. Every character MUST be identifiable at a glance:
     * No two characters may share a hair colour. If the story dresses them in the same uniform, their hair colour AND hair style must BOTH differ.
     * Every character needs a real "distinguishing_feature" - something visible on the face or head. Never 'none'.
   - Fill every "appearance" field precisely. It is the only description of that character the camera will ever get.
   - PROPS: list in "props" every object a character carries, picks up, sets down, uses, changes or breaks in the story (a laundry cart, a silver case, a phone receiver, a knife), each with a snake_case "id" and a full fixed "description" of how it looks. NOT furniture that simply stands in the room, and NOT what characters wear.

3. DRAMATISE, DO NOT REPORT (CRITICAL):
   - An act's main turns must HAPPEN IN FRONT OF THE CAMERA, physically, between people in the same room. Things the audience is only told about did not happen to them.
   - Never build an act around events the camera cannot see: money moving, accounts freezing, orders being carried out elsewhere, numbers changing on a monitor. If the story needs those, they are a BRIDGE of 1 to 2 voiceover clips, and then we cut to the scene where someone has to face the person who did it.
   - Phone calls, texts and screens are fine as BEATS - a call lands, she reads it, she reacts - but never as the spine of a stretch of clips. One character alone in a room holding a receiver is not a scene, however good the lines are; the person on the other end has to be in the room before it becomes one.
   - Ask of every act: who is physically present, and what do they DO to each other? If the answer is "one person, and she listens", restructure it.

4. LOCATION CONTINUITY & PROGRESSION ACROSS ACTS:
   - Confinement within a SCENE, progression between scenes.
   - Each act anchors in 1 to 2 core locations during its dramatic sequence. Do NOT jump between random unestablished rooms every 5 seconds.
   - The story MUST progress to new locations between acts! For a {total_clips}-clip production ({duration}s), establish 4 to 8 distinct locations total across the entire story (e.g. Grand Lobby, Executive Office, Archives, Private Sedan, Rooftop Terrace).
   - "description": fixed look in 1-2 sentences true for the whole story.
   - "layout": fixed map relative to the entrance, doors, windows, key features.
   - "views": 2 or 3 camera VIEWPOINTS showing the place EMPTY.
   - "image_prompt": wide text-to-image prompt showing the EMPTY place with NO PEOPLE and NO PROPS.

5. MULTI-ACT STRUCTURE:
   - {act_instruction}
   - LENGTH FOLLOWS CONTENT (CRITICAL): acts are NOT equal lengths. Decide what each act has to do, then give it the clips that takes. An act that is one long confrontation may need 18 clips; an act that exists to move the story from one place to the next may need 4. Equal-length acts are a sign the story has not been thought about - the last production came out 12/12/12/12/12 and the middle acts were padded out with people saying nothing new.
   - WHAT A STRETCH OF CLIPS IS FOR - there are two kinds, and mixing them up is what makes a drama drag:
     * A SCENE is a moment PLAYED OUT in real time: two people in a room, the thing actually happening in front of the camera. Scenes are where drama lives, and they need room - a real confrontation runs 10 or more clips and must not be chopped up.
     * A BRIDGE is time SKIPPED or consequences landing: it is carried by 1 to 2 voiceover clips over strong visuals, never more than 3, and it exists so the next scene can start later, elsewhere, or with everything changed. "I closed every port he owned" is a bridge - two clips. Do NOT expand a bridge into a scene: 12 clips of someone alone in a room reacting to things happening off-screen is unwatchable.
   - LOCATIONS MOVE WITHIN AN ACT, not just between acts. An act may open in a car, arrive at a building and finish in a room upstairs. Listing one location per act is what produced five separate 60-second rooms.
   - For each act in "acts", specify:
     * "act_number": integer 1, 2, ...
     * "title": short dramatic title (e.g. 'Act 1: The Inciting Disruption')
     * "primary_locations": array of location ids from scene_bible.locations where this act takes place
     * "dramatic_question": the central tension or question driving this act
     * "start_clip": integer start clip (Act 1 starts at 1)
     * "end_clip": integer end clip (Act {default_acts} ends at {total_clips})
     * "summary": concise summary of narrative progression, major clash, and ending revelation or cliffhanger.
     * "reveals": the key terms the audience learns for the FIRST time in this act - names, places, room numbers, objects.
   - Act spans must cover clips 1 to {total_clips} continuously without gaps.

6. WHO LEARNS WHAT, AND WHEN (CRITICAL):
   - Each act's beats are written in a separate later pass that cannot see the acts after it. The "reveals" lists are how that pass knows what it is not allowed to say yet, so they have to be right here.
   - A term belongs to exactly ONE act: the act that first discloses it. Never repeat a term in a later act's "reveals".
   - Nothing may be spoken before the act that reveals it. If Act 3 is where a character learns the room number, no line in Acts 1 or 2 may say that number - not even the narrator's.
"""
    user_prompt = f"Story Premise:\n{topic}\n\nGenerate the complete Scene Bible and Act Breakdown for {total_clips} clips ({duration}s total)."
    return system_prompt, user_prompt


def _narrated_act_beats_prompt(topic: str, batch: dict, all_acts: list[dict], bible: dict,
                               prior_beats: list[dict], total_clips: int) -> tuple[str, str]:
    """Builds prompt for Act Beats Call 2..N: writing beats for one act/batch."""
    start_clip = batch["start_clip"]
    end_clip = batch["end_clip"]
    clip_count = batch["clip_count"]

    system_prompt = f"""You are a master showrunner and director for viral dramatic mini-series (ReelShort / DramaBox style).
You are writing the beats for Clips {start_clip} to {end_clip} (exactly {clip_count} continuous 5-second video clips) within a {total_clips}-clip production.

CORE ARCHITECTURE: HYBRID NARRATED DRAMA (BEAT SCRIPTING):
1. SINGLE POV PROTAGONIST:
   - POV Protagonist: '{bible.get("pov_protagonist", "protagonist")}'.
   - All voiceover (delivery_mode='voiceover') is strictly in FIRST-PERSON ("I", "my", "we") spoken by '{bible.get("pov_protagonist")}'!

2. SCENES PLAY, BRIDGES SKIP (CRITICAL):
     * A SCENE (delivery_mode='dialogue'): the moment PLAYED OUT in real time, people in a room doing things to each other. It runs as many clips in a row as it needs and must NOT be chopped up to make room for narration. Let it build: proposition, objection, leverage, counter, ultimatum, decision.
     * A BRIDGE (delivery_mode='voiceover'): time SKIPPED or consequences landing - 1 to 2 clips, 3 at the very most, then we are somewhere new with everything changed. A bridge NEVER narrates a scene that is still playing in front of the camera.
     * DRAMATISE, DO NOT REPORT: the turns of this act happen physically, between people in the same room. Things that cannot be filmed - accounts freezing, orders carried out elsewhere, numbers on a monitor - are a BRIDGE of 1 to 2 clips, never a stretch of beats. A character alone holding a telephone is not a scene.
     * Phase 3: THE WORDLESS BEAT (0 or 1 clip, delivery_mode='shock_action'):
       Used ONLY when the story genuinely gives you one:
         (a) THE SHOCKWAVE - protagonist's own visceral reaction (frozen stare, gasped recoil, dropped item).
         (b) THE ESTABLISHING SHOT - nobody on screen: building exterior, lift door, empty corridor.
       Skip Phase 3 if no real physical shock occurs.

3. LOCATION CONTINUITY & CONFINEMENT:
   - Anchor in this act's primary locations: {batch.get('primary_locations', [])}.
   - Every beat's location_id MUST match one of the exact ids defined in scene_bible.locations.

4. THE SPOKEN WORD DECIDED HERE:
   - You write the exact spoken words in "audio_lines".
   - A DIALOGUE beat holds 1 to {MAX_VOICE_REFS} lines between characters in scene_bible.
   - A VOICEOVER beat holds exactly ONE line by '{bible.get("pov_protagonist")}'.
   - A SHOCK_ACTION beat has audio_lines = [] and speech_budget = 0.
   - For dialogue/voiceover, "speech_budget" is the total words across all lines in that beat: {MIN_WORDS} to {MAX_WORDS} words.
   - VOICE SAMPLES: The first line a character ever speaks in the whole series must be at least {VOICE_SAMPLE_MIN_WORDS} words.
   - PLAIN, SPEAKABLE WORDS (CRITICAL): everybody - the narrator included - talks like a person in a modern film. Short, common words anyone understands the first time they hear them. NO poetry, no metaphor stacking, no literary inversion, no semicolons, no archaic or ornate phrasing, no abstract nouns doing the work of a verb.
     * BAD (do not write like this): "Three years I kept him breathing; tonight, he offered ink." / "My clearance turned green while his power learned rain." / "mercy recognizes old footsteps"
     * GOOD (write like this): "Three years I kept him alive. Tonight he hands me a pen." / "My ship cleared while his city drowned." / "He has begged in front of me before."
   - The narration is the protagonist THINKING, not writing. It says what the picture cannot - what she wants, what it cost, what she will not say aloud - in the plainest words that carry it.

5. REVEAL ORDER & SECRET LEDGER (CRITICAL):
   - A line may only mention what the audience already knows.
   - List in "reveals" any new terms disclosed for the FIRST time in that beat.
   - NEVER mention a secret fact/term before the clip that reveals it!

6. ABSOLUTE RULES:
   - NEVER have more than 3 consecutive voiceover clips, and 2 is the working length: past that the viewer is listening to someone think instead of watching something happen.
   - Consecutive dialogue clips are NOT capped. A scene takes the clips it takes; never break one up just to insert narration.
   - Output clip_number starting at {start_clip} and ending at {end_clip}. Exactly {clip_count} beats.
"""

    bible_summary = {
        "pov_protagonist": bible.get("pov_protagonist"),
        "characters": [
            {"name": c["name"], "role": c["role"], "voice": c.get("voice", "")}
            for c in bible.get("characters", [])
        ],
        "locations": [
            {"id": l["id"], "description": l["description"], "layout": l.get("layout", "")}
            for l in bible.get("locations", [])
        ],
        "props": bible.get("props", [])
    }

    roadmap_items = []
    for a in all_acts:
        is_cur = any(num in batch.get("act_numbers", []) for num in [a.get("act_number")])
        tag = "  <-- CURRENT ASSIGNMENT" if is_cur else ""
        roadmap_items.append(
            f"Act {a['act_number']}: '{a['title']}' (Clips {a['start_clip']}-{a['end_clip']}){tag}\n"
            f"  Locations: {', '.join(a.get('primary_locations', []))}\n"
            f"  Dramatic Question: {a.get('dramatic_question', '')}\n"
            f"  Summary: {a.get('summary', '')}"
        )
    roadmap_text = "\n".join(roadmap_items)

    reserved = _terms_reserved_for_later_acts(all_acts, batch)
    reserved_text = ""
    if reserved:
        reserved_text = (
            "\n\nRESERVED FOR LATER ACTS (CRITICAL): a later act is the one that discloses each of these, so no "
            "line you write here may say any of them - not in dialogue, not in the narrator's voice:\n  "
            + ", ".join(f"'{t}'" for t in reserved)
            + "\nThe audience does not know them yet. Write around them."
        )

    prior_text = ""
    if prior_beats:
        known_terms = sorted(_terms_known_by(prior_beats, len(prior_beats) - 1))
        recent = prior_beats[-4:]
        last_beat = prior_beats[-1]
        prior_text = f"""
PREVIOUS FILMED BEATS:
Total clips already filmed: {len(prior_beats)} (Clips 1 to {len(prior_beats)}).
Terms already revealed to audience: {known_terms if known_terms else 'None yet'}.

Most recent beats filmed:
{json.dumps(recent, indent=2)}

CONTINUITY HAND-OFF FROM CLIP {last_beat['clip_number']}:
- Immediately preceding clip delivery_mode: '{last_beat.get('delivery_mode')}'
- Preceding location_id: '{last_beat.get('location_id')}'
- Characters present: {last_beat.get('present_characters', [])}
Ensure smooth narrative flow and character positioning from Clip {last_beat['clip_number']} into Clip {start_clip}!
"""

    user_prompt = f"""Story Premise:
{topic}

Scene Bible:
{json.dumps(bible_summary, indent=2)}

Full Story Act Roadmap:
{roadmap_text}
{prior_text}
CURRENT TASK:
Generate exactly {clip_count} beats for Clips {start_clip} to {end_clip}.
Act(s): {batch.get('act_numbers')} - '{batch.get('title')}'
Primary Locations: {batch.get('primary_locations')}
Dramatic Question: {batch.get('dramatic_question')}
Act Goal / Summary: {batch.get('summary')}

Return JSON with "beats" containing exactly {clip_count} items with clip_number from {start_clip} to {end_clip}.
"""
    system_prompt += reserved_text
    return system_prompt, user_prompt


def _beat_lines(beat: dict) -> list[dict]:
    """The turns a beat plans, as [{"speaker", "line"}]. Reads the older single `audio_line` shape too, so a
    job planned before multi-speaker clips can still be resumed."""
    lines = beat.get("audio_lines")
    if lines is not None:
        return [t for t in lines if (t.get("line") or "").strip()]
    line = (beat.get("audio_line") or "").strip()
    return [{"speaker": (beat.get("speaker_or_actor") or "").strip(), "line": line}] if line else []


def _clip_turns(clip: dict) -> list[dict]:
    """A clip's spoken turns, reading the older single `audio_text`/`speaker` shape too."""
    turns = clip.get("speech")
    if turns is not None:
        return [t for t in turns if (t.get("line") or "").strip()]
    text = (clip.get("audio_text") or "").strip()
    if not text:
        return []
    return [{"speaker": (clip.get("speaker") or "").strip(), "line": text,
             "delivery": clip.get("delivery", ""), "start_est": clip.get("start_est", 0.5),
             "end_est": clip.get("end_est", 4.5)}]


def _spoken_words(turns: list[dict]) -> int:
    return sum(len(_WORD.findall(t.get("line") or "")) for t in turns)


VOICE_SAMPLE_MIN_WORDS = 5    # a banked voice is cut from a real line, so the first one has to be usable
VOICE_SAMPLE_MIN_SECONDS = 1.5


def _is_good_voice_sample(turn: dict) -> bool:
    """Is this turn long enough to cut a usable voice reference out of?"""
    words = len(_WORD.findall(turn.get("line") or ""))
    try:
        span = float(turn.get("end_est", 0) or 0) - float(turn.get("start_est", 0) or 0)
    except (TypeError, ValueError):
        span = 0.0
    return words >= VOICE_SAMPLE_MIN_WORDS and span >= VOICE_SAMPLE_MIN_SECONDS


def _better_sample_later(speaker: str, beats: list[dict] | None, after_index: int) -> bool:
    """Does this speaker get a longer line further on? If so, wait for it rather than banking a scrap."""
    for b in (beats or [])[after_index + 1:]:
        for t in _beat_lines(b):
            if (t.get("speaker") or "").strip().lower() == speaker.strip().lower():
                if len(_WORD.findall(t.get("line") or "")) >= VOICE_SAMPLE_MIN_WORDS:
                    return True
    return False


def should_bank_voice(turn: dict, speaker: str, beats: list[dict] | None, clip_index: int) -> bool:
    """A voice banked from "Gone." is the voice that character keeps for the rest of the video, so a scrap of
    a line is only used when nothing better is coming."""
    if _is_good_voice_sample(turn):
        return True
    return not _better_sample_later(speaker, beats, clip_index)


def _hard_problems(problems: list[str]) -> list[str]:
    """The problems that must stop a job: anything not marked [SOFT]. A soft problem is cosmetic (a line a
    word or two long, slightly rushed pacing) and is worth logging, never worth spending credits to avoid."""
    return [p for p in problems or [] if not p.startswith("[SOFT] ")]


def _soft_problems(problems: list[str]) -> list[str]:
    return [p[len("[SOFT] "):] for p in problems or [] if p.startswith("[SOFT] ")]


def _terms_known_by(beats: list[dict], upto: int) -> set[str]:
    """The key terms the audience has heard by the end of beat `upto` (0-based, inclusive)."""
    known = set()
    for b in beats[: upto + 1]:
        for t in (b.get("reveals") or []):
            if t and t.strip():
                known.add(t.strip().lower())
    return known


def _terms_reserved_for_later_acts(all_acts: list[dict], batch: dict) -> list[str]:
    """Terms a later act will disclose, which this batch's lines must not speak yet.

    The per-batch beat check can only see beats already written, so a leak into a later act is invisible to
    it. The act breakdown knows the whole shape of the story, so it is asked up front which act discloses
    what, and that answer is what makes the leak catchable while a retry is still cheap and local."""
    mine = [a for a in batch.get("act_numbers", []) if isinstance(a, int)]
    highest = max(mine) if mine else 0
    reserved: set[str] = set()
    already: set[str] = set()
    for act in all_acts or []:
        number = act.get("act_number")
        terms = {(t or "").strip().lower() for t in (act.get("reveals") or []) if (t or "").strip()}
        if isinstance(number, int) and number > highest:
            reserved |= terms
        else:
            already |= terms
    return sorted(reserved - already)


def _leaking_beats(beats: list[dict]) -> list[tuple[int, str]]:
    """(index, term) for every beat whose line speaks something the story only reveals later."""
    found: list[tuple[int, str]] = []
    for i, beat in enumerate(beats):
        line = " ".join(t.get("line", "") for t in _beat_lines(beat)).strip()
        if not line:
            continue
        for term in _terms_still_secret(beats, i):
            if _mentions(line, term):
                found.append((i, term))
    return found


def _terms_still_secret(beats: list[dict], upto: int) -> set[str]:
    """Terms a later beat discloses that the audience has NOT heard yet by beat `upto`."""
    known = _terms_known_by(beats, upto)
    secret = set()
    for b in beats[upto + 1:]:
        for t in (b.get("reveals") or []):
            t = (t or "").strip().lower()
            if t and t not in known:
                secret.add(t)
    return secret


def _mentions(text: str, term: str) -> bool:
    return bool(re.search(rf"(?<!\w){re.escape(term)}(?!\w)", text or "", re.I))


def _check_scene_bible(bible: dict) -> list[str]:
    """Validates scene_bible consistency: protagonist, character appearance distinctness, location viewpoints/plates."""
    problems = []
    protagonist = bible.get("pov_protagonist", "").strip()
    char_names = [c["name"].lower() for c in bible.get("characters", [])]
    if not protagonist or protagonist.lower() not in char_names:
        problems.append(f"pov_protagonist '{protagonist}' is not defined in characters list.")

    valid_loc_ids = {loc["id"] for loc in bible.get("locations", [])}
    if not valid_loc_ids:
        problems.append("scene_bible must define at least one location.")

    seen_hair: list[tuple[str, str, str]] = []
    small_cast = len(bible.get("characters", [])) <= 5
    for c in bible.get("characters", []):
        cname = c.get("name", "?")
        appearance = c.get("appearance") or {}
        for field in _APPEARANCE_FIELDS:
            value = (appearance.get(field) or "").strip()
            if not value or _norm_desc(value) in {"none", "n a", "na", "unspecified", "unknown"}:
                problems.append(f"{cname}: appearance.{field} is empty; every character needs a concrete, permanent {field.replace('_', ' ')}.")
                continue
            m = _MOOD_IN_LOOK.search(value)
            if m:
                problems.append(f"{cname}: appearance.{field} says '{m.group(0)}', which is a mood, not a permanent physical fact. Describe only what the camera sees in every clip.")
        voice = (c.get("voice") or "").strip()
        vm = _PERFORMANCE_IN_VOICE.search(voice)
        if vm:
            problems.append(
                f"{cname}: voice says '{vm.group(0)}', which is how a line is PERFORMED, not what the voice IS. "
                f"A permanent performance note makes every delivery in the film inherit it. Describe only pitch, "
                f"grain and accent ('smoky alto with a faint Irish lilt', 'gravelled baritone')."
            )
        color_fam = _family(appearance.get("hair_color"), _HAIR_COLORS)
        style_fam = _family(appearance.get("hair_style"), _HAIR_STYLES)
        for other, other_color, other_style in seen_hair:
            if color_fam == other_color and style_fam == other_style:
                problems.append(f"{cname} and {other} have the same hair colour AND the same hair style; change one of the two so they can be told apart.")
            elif small_cast and color_fam == other_color:
                problems.append(f"{cname} and {other} both have {color_fam} hair. In a cast this small every character needs a different hair colour, or they cannot be told apart on a dim phone screen.")
        seen_hair.append((cname, color_fam, style_fam))

    char_name_words = {w for c in bible.get("characters", []) for w in _norm_desc(c.get("name")).split() if len(w) > 2}
    for loc in bible.get("locations", []):
        plate = loc.get("image_prompt") or ""
        if "The place is EMPTY" in plate:
            continue  # already compiled; its wording is ours, not the model's
        m = _PERSON_IN_PLATE.search(plate)
        if m:
            problems.append(f"location '{loc.get('id')}': its image_prompt describes a person ('{m.group(0)}'). A location picture is the EMPTY place - anyone in it is painted into every clip filmed there.")
        named = [w for w in char_name_words if re.search(rf"\b{re.escape(w)}\b", plate, re.I)]
        if named:
            problems.append(f"location '{loc.get('id')}': its image_prompt names the character '{named[0]}'. Describe only the empty place.")
        views = loc.get("views") or []
        if not (2 <= len(views) <= 3):
            problems.append(f"location '{loc.get('id')}': give 2 or 3 viewpoints, not {len(views)}.")
        for v in views:
            vm = _PERSON_IN_PLATE.search(v or "")
            v_named = [w for w in char_name_words if re.search(rf"\b{re.escape(w)}\b", v or "", re.I)]
            if vm or v_named:
                problems.append(f"location '{loc.get('id')}': viewpoint '{v}' names a person. A viewpoint is a place to stand in the empty room, not a shot from the story.")

    return problems


def _repair_beats(beats: list[dict], bible: dict) -> list[str]:
    """Settle what the code can settle about a batch of beats, before they are validated.

    `speaker_or_actor` predates per-turn speakers in `audio_lines`, so the model keeps trying to make it do
    a job it no longer has - naming two characters at once ("Lorenzo / Elena"), or naming the object a
    wordless beat is about ("platinum_ring"). Every act of the first 60-clip plan spent a retry on this and
    nothing else. The right value is derivable, so it is derived."""
    fixed: list[str] = []
    protagonist = (bible.get("pov_protagonist") or "").strip()
    cast = {c["name"].lower(): c["name"] for c in bible.get("characters", [])}
    for b in beats:
        written = (b.get("speaker_or_actor") or "").strip()
        mode = b.get("delivery_mode")
        turns = _beat_lines(b)
        on_screen = [p for p in b.get("present_characters", []) if p and p.strip()]
        if mode == "voiceover":
            correct = protagonist
        elif mode == "dialogue":
            first = (turns[0].get("speaker") or "").strip() if turns else ""
            # the beat belongs to whoever speaks first, unless that name is not in the cast
            correct = cast.get(first.lower()) or cast.get(written.lower()) or protagonist
        else:
            # a reaction is the protagonist's; an establishing shot with nobody in it has no actor at all
            correct = protagonist if on_screen else ""
        if written != correct:
            b["speaker_or_actor"] = correct
            fixed.append(f"clip {b.get('clip_number', '?')}: speaker_or_actor {written or '(empty)'!r} -> {correct or '(empty)'!r}")
    return fixed


def _check_beats(beats: list[dict], bible: dict, prior_beats: list[dict] | None = None) -> list[str]:
    """Validates beat sequence rules: micro-cycle alternating rhythm, speakers, audio lines, word count, reveals."""
    problems = []
    protagonist = bible.get("pov_protagonist", "").strip()
    char_names = [c["name"].lower() for c in bible.get("characters", [])]
    valid_loc_ids = {loc["id"] for loc in bible.get("locations", [])}

    consecutive_vo = 0
    consecutive_dial = 0
    if prior_beats:
        for pb in reversed(prior_beats):
            mode = pb.get("delivery_mode")
            if mode == "voiceover" and consecutive_dial == 0:
                consecutive_vo += 1
            elif mode == "dialogue" and consecutive_vo == 0:
                consecutive_dial += 1
            else:
                break

    offset = len(prior_beats) if prior_beats else 0
    all_sequence = (prior_beats or []) + beats

    for idx, b in enumerate(beats):
        i = offset + idx + 1
        loc_id = b.get("location_id")
        if loc_id not in valid_loc_ids:
            problems.append(f"Beat {i} uses location '{loc_id}', which is not in scene_bible locations ({list(valid_loc_ids)}).")

        spk = (b.get("speaker_or_actor") or "").strip()
        if spk.upper().endswith("(V.O.)"):
            spk = spk[:-6].strip()
            b["speaker_or_actor"] = spk
        elif spk.upper().endswith("(VO)"):
            spk = spk[:-4].strip()
            b["speaker_or_actor"] = spk

        turns = _beat_lines(b)
        line = " ".join(t.get("line", "") for t in turns).strip()
        line_words = _spoken_words(turns)
        mode = b.get("delivery_mode")
        if mode in ("voiceover", "dialogue"):
            if not turns:
                problems.append(f"Clip {i}: audio_lines is empty; write the exact words heard in this clip.")
            elif mode == "voiceover" and len(turns) > 1:
                problems.append(f"Clip {i}: a voiceover beat is one narrator, so it takes exactly one line, not {len(turns)}.")
            elif mode == "dialogue" and len(turns) > MAX_VOICE_REFS:
                problems.append(f"Clip {i}: {len(turns)} lines in one {CLIP_SECONDS}-second clip; at most {MAX_VOICE_REFS} fit.")
            else:
                speakers = {(t.get("speaker") or "").strip().lower() for t in turns}
                unknown = [s for s in speakers if s and s not in char_names]
                if unknown:
                    problems.append(f"Clip {i}: '{unknown[0]}' speaks here but is not in the scene_bible characters list.")
                elif len(speakers) > MAX_VOICE_REFS:
                    problems.append(f"Clip {i}: {len(speakers)} different speakers; at most {MAX_VOICE_REFS} can share a clip.")
                elif not (MIN_WORDS <= line_words <= MAX_WORDS):
                    problems.append(f"[SOFT] Clip {i}: {line_words} words across {len(turns)} line(s); {MIN_WORDS} to {MAX_WORDS} in total fits the clip best.")
                elif line_words != b.get("speech_budget"):
                    b["speech_budget"] = line_words
        if mode == "voiceover":
            consecutive_vo += 1
            consecutive_dial = 0
            if consecutive_vo > MAX_CONSECUTIVE_VO:
                problems.append(
                    f"Clip {i}: {consecutive_vo} voiceover clips in a row. {MAX_CONSECUTIVE_VO} is the absolute "
                    f"ceiling - past that the viewer is listening to {consecutive_vo * CLIP_SECONDS} seconds of "
                    f"someone thinking. Narration SKIPS time and covers what cannot be filmed; the moment itself "
                    f"has to be played, so cut into the scene."
                )
            elif consecutive_vo == VO_RUN_WORTH_NOTING:
                problems.append(
                    f"[SOFT] Clip {i}: three voiceover clips in a row ({VO_RUN_WORTH_NOTING * CLIP_SECONDS}s of "
                    f"narration). Two is the working length; three is for when the story genuinely needs it."
                )
            # The clip validator enforces the same rule, so catching it here means a cheap plan retry
            # instead of a clip fighting it mid-run: a first-person voiceover over a scene with people in
            # it has to include the narrator, even if they are only a voice on a line. A beat with nobody
            # on screen is exempt - narration over an establishing shot is normal.
            vo_present = [p for p in b.get("present_characters", []) if p and p.strip()]
            if vo_present and protagonist and protagonist.lower() not in {p.lower() for p in vo_present}:
                problems.append(
                    f"Clip {i}: '{protagonist}' narrates this beat but is not among its present_characters. "
                    f"Add them (they can be off screen, a voice on a line), or give the beat nobody on screen."
                )
            vo_speaker = (turns[0].get("speaker") or spk).strip() if turns else spk
            if vo_speaker.lower() != protagonist.lower():
                problems.append(f"Clip {i}: voiceover must be narrated by pov_protagonist '{protagonist}', not '{vo_speaker}'.")
        elif mode == "dialogue":
            consecutive_dial += 1
            consecutive_vo = 0
            # No hard cap. A confrontation is supposed to run: capping it at 3 is what forced voiceover in as
            # spacer, and those spacer beats narrated scenes that were still playing.
            if consecutive_dial == DIALOGUE_RUN_WORTH_NOTING + 1:
                problems.append(
                    f"[SOFT] Clip {i}: {consecutive_dial} dialogue clips unbroken "
                    f"({consecutive_dial * CLIP_SECONDS}s). Fine if the scene is still turning; if it has started "
                    f"repeating itself, the scene is over and the story should move."
                )
            if spk and spk.lower() not in char_names:
                problems.append(f"Clip {i}: dialogue speaker '{spk}' is not in scene_bible characters list.")
        elif mode == "shock_action":
            consecutive_vo = 0
            consecutive_dial = 0
            if b.get("speech_budget", 0) != 0:
                problems.append(f"Clip {i}: shock_action must have speech_budget = 0.")
            if turns:
                problems.append(f"Clip {i}: shock_action is wordless; audio_lines must be empty, not '{line}'.")
            present = [p for p in b.get("present_characters", []) if p and p.strip()]
            if present:
                if protagonist and protagonist.lower() not in {p.lower() for p in present}:
                    problems.append(f"Clip {i}: a wordless beat with people in it must include the POV protagonist '{protagonist}' - we watch from inside their head. For an establishing shot of a place, leave present_characters empty instead.")
                elif spk and protagonist and spk.lower() != protagonist.lower():
                    problems.append(f"Clip {i}: the reaction belongs to '{protagonist}', not '{spk}'. '{spk}' can still react inside the clip; they are just not who the shot is about.")
            elif spk:
                problems.append(f"Clip {i}: this is an establishing shot with nobody on screen, so speaker_or_actor must be empty, not '{spk}'.")

    # Reveal secrets check
    for idx, b in enumerate(beats):
        abs_idx = offset + idx
        line = " ".join(t.get("line", "") for t in _beat_lines(b)).strip()
        if not line:
            continue
        for term in _terms_still_secret(all_sequence, abs_idx):
            if _mentions(line, term):
                reveal_at = next((j + 1 for j, fb in enumerate(all_sequence) if term in {(t or "").strip().lower() for t in (fb.get("reveals") or [])}), "?")
                problems.append(f"Clip {abs_idx + 1}: a line says '{term}', which the audience does not learn until clip {reveal_at}. Rewrite it using only what is already known.")

    return problems


def _check_narrated_outline(data: dict, total_clips: int) -> list[str]:
    """Validates that the outline strictly follows the rapid micro-cycle rhythm and location consistency."""
    problems = []
    bible = data.get("scene_bible", {})
    beats = data.get("beats", [])

    if len(beats) != total_clips:
        problems.append(f"Outline produced {len(beats)} beats; exactly {total_clips} required.")

    problems.extend(_check_scene_bible(bible))
    problems.extend(_check_beats(beats, bible))

    # Location variety check (§9: Confinement within an act, progression between acts)
    if total_clips >= 30:
        used_locs = {b.get("location_id") for b in beats if b.get("location_id")}
        if len(used_locs) < 3:
            problems.append(
                f"[SOFT] Location variety: Only {len(used_locs)} distinct locations used across {total_clips} clips. "
                f"A production of this length should progress across 4-8 locations (at least 3)."
            )
        loc_counts = collections.Counter(b.get("location_id") for b in beats if b.get("location_id"))
        if loc_counts:
            top_loc, top_cnt = loc_counts.most_common(1)[0]
            if top_cnt > total_clips * 0.70:
                pct = int(top_cnt * 100 / total_clips)
                problems.append(
                    f"[SOFT] Location variety: Location '{top_loc}' covers {top_cnt}/{total_clips} clips ({pct}%). "
                    f"Consider progressing to new locations between acts."
                )

    return problems


def _check_act_breakdown(data: dict, total_clips: int) -> list[str]:
    """Validates Scene Bible and Act breakdown structure."""
    problems = []
    bible = data.get("scene_bible", {})
    acts = data.get("acts", [])

    problems.extend(_check_scene_bible(bible))

    if not acts:
        problems.append("Act breakdown returned no acts.")
        return problems

    valid_loc_ids = {loc["id"] for loc in bible.get("locations", [])}
    if total_clips >= 30:
        if len(valid_loc_ids) < 3:
            problems.append(
                f"[SOFT] Location variety: scene_bible defines only {len(valid_loc_ids)} locations for {total_clips} clips. "
                f"A 5-minute production should establish 4 to 8 locations across acts."
            )
        all_act_locs = {loc for a in acts for loc in a.get("primary_locations", []) if loc}
        if len(all_act_locs) < 3:
            problems.append(
                f"[SOFT] Location variety: acts collectively use only {len(all_act_locs)} distinct locations. "
                f"Aim for progression across 4 to 8 locations across acts."
            )

    for idx, a in enumerate(acts, 1):
        for loc in a.get("primary_locations", []):
            if loc not in valid_loc_ids:
                problems.append(f"Act {idx} references location '{loc}' not in scene_bible locations ({list(valid_loc_ids)}).")
        st = a.get("start_clip")
        en = a.get("end_clip")
        if st is None or en is None:
            problems.append(f"Act {idx} is missing start_clip or end_clip.")
        elif st > en:
            problems.append(f"Act {idx} has start_clip ({st}) > end_clip ({en}).")

    return problems


def _check_act_beats(beats: list[dict], bible: dict, start_clip: int, end_clip: int,
                     prior_beats: list[dict] | None = None,
                     reserved_terms: list[str] | None = None) -> list[str]:
    """Validates beats generated for a single act/batch against the bible, the prior beats, and the terms
    later acts are keeping back."""
    problems = []
    expected_count = end_clip - start_clip + 1
    if len(beats) != expected_count:
        problems.append(f"Act produced {len(beats)} beats; exactly {expected_count} required for clips {start_clip} to {end_clip}.")

    # Auto-normalize clip numbers if shifted
    for idx, b in enumerate(beats):
        if b.get("clip_number") != start_clip + idx:
            b["clip_number"] = start_clip + idx

    problems.extend(_check_beats(beats, bible, prior_beats=prior_beats))

    # A leak forward into an act that has not been written yet is invisible to the ledger, which only knows
    # the beats that exist. The act breakdown's own reveal lists are what close that gap.
    for idx, b in enumerate(beats):
        line = " ".join(t.get("line", "") for t in _beat_lines(b)).strip()
        if not line:
            continue
        for term in reserved_terms or []:
            if _mentions(line, term):
                problems.append(
                    f"Clip {start_clip + idx}: a line says '{term}', which a LATER act is the one to reveal. "
                    f"Write this line using only what the audience knows by now."
                )
    return problems


def _write_single_shot_outline(topic: str, duration: int, total_clips: int) -> tuple[dict, list[str]]:
    """Generates the Master Plan in a single shot for shorter videos (< 30 clips)."""
    sys_p, usr_p = _narrated_outline_prompt(topic, duration, total_clips)
    for attempt in range(SCRIPT_RETRIES + 1):
        data = _ask_openai_json(sys_p, usr_p, "narrated_outline", OUTLINE_SCHEMA)
        _compile_bible_visuals(data.get("scene_bible", {}))
        for note in _repair_beats(data.get("beats", []), data.get("scene_bible", {})):
            print(f"  repaired {note}")
        problems = _check_narrated_outline(data, total_clips)
        hard = _hard_problems(problems)
        if not hard:
            return data, problems
        if attempt < SCRIPT_RETRIES:
            print(f"  Outline check: {len(hard)} problem(s), asking OpenAI to fix (retry {attempt+1}/{SCRIPT_RETRIES}):")
            for p in hard:
                print(f"    - {p}")
            usr_p = (
                f"Story Premise:\n{topic}\n\nHere is your previous response:\n"
                + json.dumps(data)
                + "\n\nIt broke these rules:\n- "
                + "\n- ".join(hard)
                + "\n\nCRITICAL INSTRUCTION: DO NOT hallucinate a completely new story. You must remain 100% faithful to the Story Premise, characters, and established events above. ONLY adjust the specific fields necessary to satisfy the rules and return valid JSON adhering strictly to the alternating micro-cycle rhythm."
            )
    return data, problems


def _write_act_based_outline(topic: str, duration: int, total_clips: int) -> tuple[dict, list[str]]:
    """Generates the Master Plan in acts for long videos (>= 30 clips).
    Call 1: Scene Bible + Act Outline.
    Call 2..N: Beats for each act/batch, seeing prior beats and roadmap."""
    act_count = _detect_premise_act_count(topic)
    sys_p, usr_p = _narrated_act_breakdown_prompt(topic, duration, total_clips, act_count=act_count)

    breakdown_data = {}
    for attempt in range(SCRIPT_RETRIES + 1):
        breakdown_data = _ask_openai_json(sys_p, usr_p, "narrated_act_breakdown", ACT_BREAKDOWN_SCHEMA)
        _compile_bible_visuals(breakdown_data.get("scene_bible", {}))
        breakdown_problems = _check_act_breakdown(breakdown_data, total_clips)
        hard = _hard_problems(breakdown_problems)
        if not hard:
            break
        if attempt < SCRIPT_RETRIES:
            print(f"  Act breakdown check: {len(hard)} problem(s), asking OpenAI to fix (retry {attempt+1}/{SCRIPT_RETRIES}):")
            for p in hard:
                print(f"    - {p}")
            usr_p = (
                f"Story Premise:\n{topic}\n\nHere is your previous response:\n"
                + json.dumps(breakdown_data)
                + "\n\nIt broke these rules:\n- "
                + "\n- ".join(hard)
                + "\n\nCRITICAL INSTRUCTION: DO NOT hallucinate a completely new story. ONLY adjust the specific fields necessary to satisfy the rules and return valid JSON adhering strictly to the schema."
            )

    bible = breakdown_data.get("scene_bible", {})
    raw_acts = breakdown_data.get("acts", [])
    acts = _normalize_act_spans(raw_acts, total_clips)
    breakdown_data["acts"] = acts
    batches = _plan_act_batches(acts)

    all_beats: list[dict] = []
    for batch in batches:
        start_clip = batch["start_clip"]
        end_clip = batch["end_clip"]
        batch_sys, batch_usr = _narrated_act_beats_prompt(topic, batch, acts, bible, all_beats, total_clips)
        batch_beats: list[dict] = []
        for attempt in range(SCRIPT_RETRIES + 1):
            beats_resp = _ask_openai_json(batch_sys, batch_usr, f"narrated_act_beats_{batch['batch_index']}", ACT_BEATS_SCHEMA)
            batch_beats = beats_resp.get("beats", [])
            for note in _repair_beats(batch_beats, bible):
                print(f"  repaired {note}")
            problems = _check_act_beats(batch_beats, bible, start_clip, end_clip, prior_beats=all_beats,
                                        reserved_terms=_terms_reserved_for_later_acts(acts, batch))
            hard = _hard_problems(problems)
            if not hard:
                break
            if attempt < SCRIPT_RETRIES:
                print(f"  Act {batch['batch_index']} check: {len(hard)} problem(s), asking OpenAI to fix (retry {attempt+1}/{SCRIPT_RETRIES}):")
                for p in hard:
                    print(f"    - {p}")
                batch_usr = (
                    batch_usr
                    + f"\n\nHere is your previous response:\n{json.dumps(beats_resp)}\n\n"
                    + "It broke these rules:\n- "
                    + "\n- ".join(hard)
                    + f"\n\nCRITICAL INSTRUCTION: Return valid JSON with 'beats' containing exactly {batch['clip_count']} items strictly addressing the above problems."
                )
        all_beats.extend(batch_beats)

    # Backstop. The per-batch check catches a leak against what the acts declared; this catches one against
    # what the beats actually wrote, which only becomes visible once every act exists. Rewriting the single
    # batch that owns the offending beat costs one call, where failing here would discard every planning call
    # and the whole plan with it.
    leaks = _leaking_beats(all_beats)
    if leaks:
        beat_index, term = leaks[0]
        owner = next((b for b in batches if b["start_clip"] <= beat_index + 1 <= b["end_clip"]), None)
        if owner is not None:
            print(f"  Reveal leak at clip {beat_index + 1} ('{term}'); rewriting {owner['title']} only.")
            head = all_beats[: owner["start_clip"] - 1]
            tail = all_beats[owner["end_clip"]:]
            leak_notes = "\n- ".join(
                f"clip {i + 1} says '{t}', which the story only reveals later" for i, t in leaks
                if owner["start_clip"] <= i + 1 <= owner["end_clip"]
            )
            batch_sys, batch_usr = _narrated_act_beats_prompt(topic, owner, acts, bible, head, total_clips)
            batch_usr += (
                "\n\nYour previous beats for these clips leaked the story:\n- " + leak_notes
                + "\n\nCRITICAL INSTRUCTION: keep the same beats, locations and rhythm; only rewrite the offending "
                  "lines so they use nothing the audience has not been told yet. Return valid JSON."
            )
            retry = _ask_openai_json(batch_sys, batch_usr, f"narrated_act_beats_{owner['batch_index']}_releak",
                                     ACT_BEATS_SCHEMA)
            fixed_beats = retry.get("beats", [])
            if len(fixed_beats) == owner["clip_count"]:
                for offset, b in enumerate(fixed_beats):
                    b["clip_number"] = owner["start_clip"] + offset
                all_beats = head + fixed_beats + tail

    full_data = {
        "scene_bible": bible,
        "acts": acts,
        "beats": all_beats
    }
    full_problems = _check_narrated_outline(full_data, total_clips)
    return full_data, full_problems


def write_narrated_outline(topic: str, duration: int, total_clips: int) -> tuple[dict, list[str]]:
    """Generates the Master Plan. Automatically switches to act-based generation for >= 30 clips."""
    if total_clips < 30:
        return _write_single_shot_outline(topic, duration, total_clips)
    return _write_act_based_outline(topic, duration, total_clips)


def write_narrated_continuation_outline(topic: str, continuation_prompt: str, bible: dict,
                                        prev_beats: list[dict], additional_clips: int) -> tuple[dict, list[str]]:
    """Generates additional beats extending an existing narrated drama plan."""
    start_clip = len(prev_beats) + 1
    end_clip = len(prev_beats) + additional_clips
    batch = {
        "batch_index": 1,
        "act_numbers": ["Continuation"],
        "start_clip": start_clip,
        "end_clip": end_clip,
        "clip_count": additional_clips,
        "title": "Story Continuation",
        "primary_locations": [l["id"] for l in bible.get("locations", [])],
        "dramatic_question": continuation_prompt,
        "summary": continuation_prompt,
    }
    all_acts = [{
        "act_number": "Continuation",
        "title": "Continuation",
        "primary_locations": [l["id"] for l in bible.get("locations", [])],
        "dramatic_question": continuation_prompt,
        "start_clip": start_clip,
        "end_clip": end_clip,
        "summary": continuation_prompt
    }]
    sys_p, usr_p = _narrated_act_beats_prompt(topic, batch, all_acts, bible, prev_beats, start_clip + additional_clips - 1)
    new_beats: list[dict] = []
    problems: list[str] = []
    for attempt in range(SCRIPT_RETRIES + 1):
        resp = _ask_openai_json(sys_p, usr_p, "narrated_continuation_beats", ACT_BEATS_SCHEMA)
        new_beats = resp.get("beats", [])
        problems = _check_act_beats(new_beats, bible, start_clip, end_clip, prior_beats=prev_beats)
        hard = _hard_problems(problems)
        if not hard:
            break
    return {"scene_bible": bible, "beats": new_beats}, problems


# ---------------------------------------------------------------------------
# Chapter / Clip Scripting
# ---------------------------------------------------------------------------
def _normalize_narrated_clip(clip: dict, bible: dict) -> None:
    """Spell every character name as the Scene Bible does and derive present_characters from blocking."""
    by_lower = {c["name"].lower(): c["name"] for c in bible.get("characters", [])}
    clip["speech"] = _clip_turns(clip)  # settles the older single-line shape into turns
    for t in clip["speech"]:
        if t.get("speaker"):
            t["speaker"] = by_lower.get(t["speaker"].lower(), t["speaker"])
    for s in clip.get("action_steps", []):
        if "character" in s and s["character"]:
            s["character"] = by_lower.get(s["character"].lower(), s["character"])
    for b in clip.get("blocking", []):
        if "character" in b and b["character"]:
            b["character"] = by_lower.get(b["character"].lower(), b["character"])
        if b.get("in_frame") in ("off screen", "has left"):
            b["frame_position"] = "off screen"
        elif not b.get("frame_position") or b.get("frame_position") not in FRAME_POSITIONS or b.get("frame_position") == "off screen":
            b["frame_position"] = "centre frame"
    for p in clip.get("prop_state", []):
        holder = (p.get("holder") or "").strip()
        if holder and holder.lower() != "scene":
            p["holder"] = by_lower.get(holder.lower(), holder)
    if "blocking" in clip:
        clip["present_characters"] = [
            b["character"] for b in clip["blocking"] if b.get("in_frame") in ON_SCREEN
        ]
    clip["present_characters"] = [
        by_lower.get(p.lower(), p) for p in clip.get("present_characters", [])
    ]


def _awareness_line(clip: dict) -> str:
    """Who had noticed what by the end of a clip, for the next clip's continuity history."""
    return "; ".join(
        f"{b.get('character')}: {(b.get('awareness') or '').rstrip('. ')}"
        for b in clip.get("blocking", []) if (b.get("awareness") or "").strip()
    )


def _props_line(clip: dict) -> str:
    """A clip's prop diary as one readable line, for the continuity history."""
    return "; ".join(
        f"{p.get('prop_id')} ({'held by ' + p['holder'] if p.get('holder') and p['holder'] != 'scene' else 'in the scene'}"
        f"{', in shot' if p.get('in_frame') else ', not in shot'}): {(p.get('state') or '').rstrip('. ')}"
        for p in clip.get("prop_state", [])
    )


def _narrated_chapter_prompt(
    topic: str,
    clip_index: int,
    total_clips: int,
    beat: dict,
    bible: dict,
    prev_clips: list[dict],
    beats: list[dict] | None = None
) -> tuple[str, str]:
    """Builds prompt for writing an individual 5-second narrated drama clip."""
    protagonist = bible["pov_protagonist"]
    mode = beat["delivery_mode"]
    target_loc_id = beat["location_id"]

    target_loc = next((l for l in bible.get("locations", []) if l["id"] == target_loc_id), None)
    loc_desc = target_loc.get("description", "") if target_loc else target_loc_id
    loc_layout = target_loc.get("layout", "established layout") if target_loc else "established layout"

    available_locations = "\n".join(
        f"- '{loc['id']}': {loc['description']} | Layout: {loc.get('layout', 'established layout')}"
        for loc in bible.get("locations", [])
    )

    props = bible.get("props", [])
    props_block = ("   Props in the Scene Bible:\n" + "\n".join(f"     - {p['id']}: {p['description']}" for p in props)) if props else "   The Scene Bible lists no props, so prop_state is an empty array."

    characters_summary = "\n".join(
        f"- {c['name']} ({'POV Protagonist' if c['name'].lower() == protagonist.lower() else c.get('role', 'Supporting')}): {c.get('look', '')}"
        for c in bible.get("characters", [])
    )

    # The line itself was written by the Master Plan, which is the only writer that sees the whole story and
    # can therefore place a revelation in the right clip. Here it is quoted and locked.
    beat_turns = _beat_lines(beat)
    if beat_turns:
        quoted = "\n".join(f'    {i + 1}. {t.get("speaker", "")}: "{t.get("line", "")}"' for i, t in enumerate(beat_turns))
        line_rule = (
            f'- "speech" MUST hold exactly these {len(beat_turns)} turn(s), in this order, each line copied word for word '
            f'- nothing added, removed, reworded or merged, and no extra turns:\n{quoted}\n'
            f'- Give each turn its own "delivery" and its own start_est/end_est window. The windows must not overlap: '
            f'each turn begins after the one before it ends, the first starts at 0.4s or later, and the last ends by 4.8s.'
        )
    else:
        line_rule = f"- 'speech' is the line or lines heard in this clip ({MIN_WORDS} to {MAX_WORDS} words in total)."

    mode_instructions = ""
    if mode == "voiceover":
        mode_instructions = f"""THIS IS A FIRST-PERSON VOICEOVER BEAT:
- The single speech turn MUST be spoken by '{protagonist}'.
{line_rule}
- Its window should start between 0.5 and 0.8 seconds and end between 4.0 and 4.6 seconds.
- Its delivery is the emotional vocal tone of their thoughts, and inner thought is NOT automatically quiet: it can seethe, break, accuse, or land flat with exhaustion (e.g. 'shaking with suppressed rage', 'bitter, half a laugh in it', 'raw and close to tears', 'urgent, breathless', 'cold, resolute dread', 'barely a whisper'). Pick the one this moment actually calls for.
- MOUTH CLOSED DIRECTIVE (CRITICAL): In action_steps, {protagonist} and all visible characters MUST keep their mouths completely closed with natural resting facial expressions. Describe solely physical, visible acting (e.g. staring at the telephone receiver, tightening grip on desk, glancing toward doorway). ZERO talking or mouth-moving actions!"""
    elif mode == "dialogue":
        mode_instructions = f"""THIS IS A LIVE SPOKEN DIALOGUE BEAT:
- Each turn's speaker is a character speaking live on-camera, or over a phone/intercom from elsewhere.
{line_rule}
- When two or three characters speak in one clip, FRAME THEM ALL: a two-shot, a profile two-shot, or a medium shot that holds everyone who speaks. Never give a line to someone the camera cannot see, unless they are a remote voice on a telephone or intercom.
- A single-turn clip should start between 0.5 and 0.9 seconds and end between 4.0 and 4.6 seconds. Two or three turns share the same {CLIP_SECONDS} seconds between them, back to back, with a beat of air between each.
- Each turn's delivery is that speaker's emotional tone at THIS moment, and people in a drama shout, snarl, laugh and beg as well as murmur (e.g. 'roared, furious', 'shouted across the room', 'spat through clenched teeth', 'laughing, delighted and cruel', 'pleading, voice cracking', 'sharp accusation', 'guarded, suspicious murmur', 'barely a whisper').
- A REPLY REACTS (CRITICAL): when a turn answers the one before it in the same clip, its delivery must carry what that line just did to them - stung, amused, winded, hardening, goaded into hitting back. A jab met with a blank, even tone plays as a robot answering a person. If the previous turn mocked them, this one either shows the hurt or returns the mockery harder; it never simply states words.
- EMOTIONAL RANGE (CRITICAL): never write a delivery that cancels its own emotion - 'fury without raised volume', 'anger held under perfect calm', 'defiance without a raised note' are instructions to sound flat, and a whole film of them is unwatchable. If a character is furious, they SOUND furious. The previous clips' deliveries are listed in the history below: if the last two were restrained, this one breaks the pattern unless the beat genuinely calls for another quiet moment.
- Lip synchronization is active for on-screen speakers. Action steps describe natural head movements, gestures, and expressive acting while speaking."""
    else:  # shock_action
        mode_instructions = """THIS IS A WORDLESS BEAT (no speech of any kind):
- "speech" MUST be an empty array: nobody speaks at all.
- IF THE BEAT HAS CHARACTERS IN IT, this is a reaction shot: describe visceral physical reactions in action_steps - a stunned freeze, a gasped recoil, an object slipping from a hand, a sudden sharp camera push. Everyone present may react; the camera stays on the POV protagonist. Zero dialogue, zero lip movement.
- IF THE BEAT HAS NO CHARACTERS (present_characters is empty), this is an ESTABLISHING or ATMOSPHERIC shot of the place itself - the building from the street, a lift door sliding open, rain on a window, an empty corridor. Leave "blocking" and "action_steps" as EMPTY arrays, put the framing and light in "shot", and put everything that MOVES in "environment". Nobody appears."""

    # This block is the same bytes for every clip of a job, so nothing clip-specific is allowed in front of
    # it. OpenAI discounts the longest common PREFIX of a request automatically, above 1024 tokens; while
    # this text opened with "Clip N of M" and this clip's own quoted lines, the common prefix across a
    # 43-clip run measured 6 tokens and all ~3,400 tokens of rules below were billed at full rate 43 times
    # over. Everything that changes from clip to clip lives in the user message instead, which is why rule 1
    # is delivered there. The rules keep their original numbers so the run logs and PROGRESS.md still match.
    system_prompt = f"""You are directing one {CLIP_SECONDS}-second clip of a fast-paced Hybrid Narrated Drama.
POV Protagonist: {protagonist}.

ABSOLUTE SPATIAL & CONTINUITY RULES:
1. MANDATORY LOCATION ANCHOR (CRITICAL): given with the clip you are directing, below. The clip MUST be set in the location it names, and you may never invent a location or move to an unlisted one.

2. CONTINUITY ACROSS CUTS:
   Blocking describes TWO moments: where each character is at 0.0s (position, posture, screen_profile, eyeline) and where the action leaves them at the end of the clip (end_position, end_posture, end_screen_profile, end_eyeline).
   If this clip continues in the same location as the previous clip, each character's 0.0s pose MUST match the pose the PREVIOUS clip ENDED them in - not the pose it started them in. They are free to move during this clip; every change between the two must be shown happening in action_steps. A character who stands still all clip simply has the same values at both ends.

3. REMOTE TELEPHONE / INTERCOM / COMMUNICATOR CALLS (CRITICAL):
   If a character is speaking over a telephone, mobile phone, intercom, or radio from outside this room:
   - The remote caller is NOT physically present in this room.
   - In blocking, that remote speaker MUST be set to in_frame: "off screen" (position: "remote caller on phone line").
   - NEVER place the remote caller physically standing inside the room with the person answering the phone!
   - The person holding the receiver/phone is visible, reacting physically to what they hear.

4. NO UNCREDITED CHARACTERS:
   All characters in present_characters, blocking, action_steps, and speaker MUST be selected strictly from the Scene Bible:
{characters_summary}
   Do NOT hallucinate or introduce new uncredited characters, bosses, or passersby.

5. CINEMATIC CAMERA POLICY ([SAME SETUP] vs [ANGLE CUT]):
   CRITICAL: Every shot description MUST explicitly begin with either "[SAME SETUP]" or "[ANGLE CUT]".
   UNIFIED APPROACH:
   (1) ESTABLISHING PHASE — LOCKED MASTER SHOT ([SAME SETUP], opening clips of a conversation or location):
       When a conversation begins or the scene moves to a new location, open with a locked wide or medium two-shot establishing the geography: who is where, what the room looks like, and each character's screen position (frame-left vs frame-right).
       Re-state the exact same camera placement, lens, aim direction, and 2D frame composition across consecutive [SAME SETUP] clips.
       DO NOT arbitrarily aim at a different wall, door, or window from clip to clip, which flips character perspective.
   (2) COVERAGE PHASE — MOTIVATED CUTS ([ANGLE CUT], from clip 2-3 onward in the same conversation):
       Once geography is established, use motivated angle cuts to add cinematic rhythm:
       - Over-the-Shoulder (OTS): camera behind one character's shoulder, focused on the other's face. Alternate whose shoulder for dialogue back-and-forth.
       - Close-Up / Extreme Close-Up: cut in tight on a face, trembling hands, clenched jaw, or a key prop during emotional peaks.
       - Profile Two-Shot: both characters in profile, facing each other, for balanced confrontations.
       - Power Dynamics: dominator shot from LOW angle, vulnerable character from HIGH angle.
       - Reveals: open on a close detail (a hand, a doorknob), then pull back or tilt to reveal the full scene.
       Every [ANGLE CUT] must be motivated by the drama (a reaction to absorb, a shift in power, a prop to emphasize). Never cut just for visual variety alone.
   (3) THE 180-DEGREE RULE & SCREEN DIRECTION (ALWAYS ENFORCED, BOTH PHASES):
       NEVER cross the axis of action. In any conversation or cut, each character MUST maintain their screen direction:
       The character on frame-left MUST still look toward screen-right in their close-up, and the character on frame-right MUST still look toward screen-left.
       Never flip character screen placement across consecutive clips in the same scene unless an action step shows them physically walking across the room.
   (4) ONE MAIN MOMENT PER CLIP:
       Each clip captures ONE natural cinematic beat that plays out comfortably in 5 seconds. Never cram an entire scene's setup, revelation, and resolution into a single 5-second clip. Complete one beat cleanly and move on.
   (5) "shot" FORMAT (REQUIRED):
       Write the exact camera setup for this 5-second clip as a single continuous physical sentence starting with "[SAME SETUP]" or "[ANGLE CUT]". You MUST include these elements:
       - CAMERA PLACEMENT: where is the camera physically positioned, using the place's layout? (e.g. "[SAME SETUP] Camera placed at waist height two metres from the reception desk facing Clara Vance", "[ANGLE CUT] Tight over his left shoulder facing Clara")
       - CAMERA MOVEMENT: what does it physically do during the 5 seconds? (e.g. "slowly pushes in", "tracks with her as she turns", "tilts up from the desk to her face", "locked static hold")
       - WHAT IT FOLLOWS: what specific body part, prop or detail does the camera stay tight on? (e.g. "locks on her eyes", "follows her trembling hand", "stays tight on his jawline")
       - ENDING FRAME: where does the shot resolve at the end of 5 seconds? (e.g. "ending on a tight close-up of her face", "resolving on an over-the-shoulder frame of the open doorway")
       - DEPTH OF FIELD: how does focus fall off? (e.g. "shallow depth of field with background lobby blurring into soft bokeh", "deep focus keeping both actors crisp")
       NOTE: Lighting and room atmosphere belong in "environment", NOT in "shot". Do not put lighting descriptions in "shot".
       The camera placement must agree with the blocking: if the camera is behind someone's shoulder facing the door, the blocking must put that person between the camera and the door.
       - STORY-CRITICAL MOVEMENT ON CAMERA: when the story depends on where someone goes or where they come from (they hide, leave, slip away, sneak in, arrive, return), the camera must point that way and keep the start and end of the movement in frame. Never let the move that matters happen outside the frame.
       - EXITS THAT LEAVE OTHERS ALONE: when someone leaves so that others can be alone, the camera follows them until they are clearly gone (through the door, out of earshot) and the shot ends holding on the people left behind, alone, so the next clip plainly reads as a private moment.
       BAD EXAMPLE: "Wide shot, eye-level, slow push-in as he walks to the door."
       GOOD EXAMPLE: "[SAME SETUP] Camera placed at waist height two metres from the reception desk facing Clara Vance, slowly pushing in as she speaks, locking on her eyes and the brass bell on the counter, resolving on a tight medium close-up of her face; shallow depth of field leaves the background elevator bank in soft bokeh."
       SHOT SIZES: Extreme Wide, Wide, Medium-Wide (knees up), Medium (waist up), Medium Close-Up (chest up), Close-Up (face), Extreme Close-Up (eyes, mouth, hands, one object).
       SCREEN PLACEMENT: In "blocking", set "frame_position" for every character: 'frame left', 'left of centre', 'centre frame', 'right of centre', 'frame right', 'foreground', 'background', or 'off screen'.

6. WHAT EACH CHARACTER KNOWS ("awareness", REQUIRED per character):
   What that character has noticed so far that matters, and what they have NOT. It carries forward from the previous clip and only changes when an action step in THIS clip shows them noticing something.
   - KNOWLEDGE: nobody speaks about, answers or reacts to something they have not noticed. A character who was off screen or had left did not hear what was said while they were away.
   - FIRST-PERSON POV: the voiceover is {protagonist}'s own thought, in the moment. It may only draw on what {protagonist} has seen, heard or could reasonably guess by now. Never let the narration know something {protagonist} has not yet witnessed - that turns their inner voice into an all-seeing narrator and breaks the first person.

7. WHAT THE PLACE IS DOING ("environment", REQUIRED):
   One short sentence of what the location itself does during this clip, with NO people in it: the storm flaring at the windows, a lift door sliding open, the brass bell still trembling, the monitor flashing, rain crawling down the glass. This is where every non-human movement lives, because action_steps always belong to a character. For a wordless establishing shot with nobody on screen, this field carries the whole motion of the clip. Leave it an empty string only when the place is genuinely still.

8. THE PROP DIARY ("prop_state", REQUIRED):
   List ONLY two kinds of prop, and nothing else:
     (a) every prop the camera SEES in this clip, and
     (b) every prop whose holder or state CHANGED in this clip, even if it is off camera.
   A prop that is off camera and unchanged is simply left out - the system carries it forward on its own, so repeating it here wastes the clip's words. Most clips will list only one or two props.
   Give each one "holder" (the character carrying it, or 'scene' when it rests somewhere), "in_frame" (true ONLY if the camera clearly sees it where the action happens - a prop elsewhere in the room is false, or the video model draws it into the shot) and "state" (its condition and exactly where it is). A prop never teleports, never changes hands off screen, and never repairs itself. The system writes each prop's fixed description into the video prompt for you.
{props_block}
9. PHYSICAL VISIBLE ACTING ONLY:
   Describe visible physical movements, gestures, and facial expressions in action_steps. Never describe unfilmable inner thoughts (no 'wonders', 'realizes', 'feels').

10. YOU DO NOT KNOW THE FUTURE (CRITICAL):
   You are shown only the beats that have already been filmed and the one beat you are writing now. Nothing later exists yet. Never name, hint at or foreshadow a person, place, room number, object or event that has not already appeared in the clips above - not in action_steps, not in the shot, not anywhere.

11. THE BEAT'S CAST IS THE CLIP'S CAST (CRITICAL):
   Every character the beat lists in present_characters MUST appear in this clip's blocking. A character may be in_frame 'off screen' (a voice on a telephone, someone just out of shot), but may NEVER be dropped from the clip, and their actions may NEVER be reassigned to somebody else. Silently removing a character rewrites who the story is about.

Story Premise:
{topic}
"""

    history_summary = ""
    if prev_clips:
        recent = prev_clips[-3:]
        recent_start = len(prev_clips) - len(recent) + 1
        history_lines = []
        for idx, c in enumerate(recent, recent_start):
            c_num = c.get("clip_number", idx)
            c_mode = c.get("delivery_mode", "dialogue")
            c_loc = c.get("location_id", "")
            c_shot = c.get("shot", "")
            c_chars = ", ".join(c.get("present_characters", [])) or "nobody visible"
            c_turns = _clip_turns(c)
            speech_line = " ".join(
                f'{(t.get("speaker") or "").strip()} ({(t.get("delivery") or "").strip()}): "{t.get("line", "")}"'
                for t in c_turns
            ) if c_turns else "[WORDLESS BEAT]"
            steps_line = "; ".join(f"{s.get('character')}: {s.get('action')}" for s in c.get("action_steps", []))

            blocking_state = []
            for b in c.get("blocking", []):
                if b.get("in_frame") in ON_SCREEN:
                    blocking_state.append(f"{b.get('character')}: {b.get('posture')} at {b.get('position')} ({b.get('screen_profile')})")
            block_str = "; ".join(blocking_state) or "none on screen"

            history_lines.append(
                f"Clip {c_num} | Location: '{c_loc}' | Mode: {c_mode.upper()} | Shot: {c_shot}\n"
                f"  Visible on screen: {c_chars}\n"
                f"  Actions: {steps_line}\n"
                f"  Spoken/Internal Voice: {speech_line}\n"
                f"  Ending Pose/Blocking: {block_str}\n"
                f"  What the place was doing: {c.get('environment') or 'still'}\n"
                f"  What each character knew by the end: {_awareness_line(c) or 'nothing noted'}\n"
                f"  Props at the end of the clip: {_props_line(c) or 'none yet'}"
            )
        history_summary = "\nPREVIOUS FILMED CLIPS (Direct Narrative & Spoken Continuity):\n" + "\n\n".join(history_lines) + f"\n\nStart Clip {clip_index + 1} as a direct continuous beat responding to Clip {clip_index}."

    # Only the story so far, never what is coming. Handing the whole plan to the clip writer is what let a
    # clip-2 voiceover name Room 404 a clip before the story revealed it.
    roadmap = ""
    if beats:
        so_far = beats[: clip_index + 1]
        roadmap = "\nThe story SO FAR (everything that exists; nothing beyond this has happened yet):\n" + "\n".join(
            f"{i+1}. [{b.get('location_id')}] [{b.get('delivery_mode', '').upper()}] {b.get('speaker_or_actor')}: {b.get('summary')}"
            for i, b in enumerate(so_far)
        )

    # Everything that differs from clip to clip, so that the system message above stays a cacheable prefix.
    user_prompt = f"""You are directing Clip {clip_index + 1} of {total_clips}.
Delivery Mode for this clip: {mode.upper()}.

{mode_instructions}

1. MANDATORY LOCATION ANCHOR (CRITICAL):
   Clip {clip_index + 1} MUST be set in location '{target_loc_id}'.
   Description: {loc_desc}
   Layout: {loc_layout}
   Do NOT invent new locations or transition to unlisted hallways, archives, or rooms!
{roadmap}

Target Beat for Clip {clip_index + 1}:
{json.dumps(beat, indent=2)}
{history_summary}

Write the detailed screenplay script for Clip {clip_index + 1}. Ensure location_id is '{target_loc_id}'."""

    return system_prompt, user_prompt


def _norm_line(text: str) -> str:
    """A spoken line reduced to its words, for comparing what was written with what was planned."""
    return " ".join(_WORD.findall(text or "")).lower()


def _check_narrated_chapter(
    data: dict,
    beat: dict,
    bible: dict,
    prev_clip: dict | None,
    clip_index: int = 0,
    beats: list[dict] | None = None
) -> list[str]:
    """Validates the clip screenplay for mouth closure, dialogue limits, location locking, and spatial continuity."""
    problems = []
    clips = data.get("clips", [])
    if not clips:
        return ["no clips returned in chapter data."]
    clip = clips[0]

    protagonist = bible.get("pov_protagonist", "").strip()
    mode = beat.get("delivery_mode", "dialogue")
    target_loc = beat.get("location_id")
    bible_chars = {c["name"].lower(): c["name"] for c in bible.get("characters", [])}
    bible_locs = {loc["id"] for loc in bible.get("locations", [])}

    # 1. Mode check
    if clip.get("delivery_mode") != mode:
        problems.append(f"clip mode is '{clip.get('delivery_mode')}', but beat requires '{mode}'.")

    # 2. Location lock check
    loc_id = clip.get("location_id", "")
    if loc_id != target_loc:
        problems.append(f"clip {clip_index + 1} is set in location '{loc_id}', but beat {clip_index + 1} requires '{target_loc}'.")
    if loc_id not in bible_locs:
        problems.append(f"clip {clip_index + 1}: location '{loc_id}' is not in Scene Bible locations ({list(bible_locs)}).")

    # 2b. A delivery that cancels its own emotion ("fury without raised volume") is an instruction to
    #     sound flat, and a scene of them is why the first 5-minute run had no heat in it anywhere.
    for t in _clip_turns(clip):
        d = (t.get("delivery") or "")
        if _CANCELS_EMOTION.search(d):
            problems.append(
                f"[SOFT] clip {clip_index + 1}: delivery '{d}' cancels its own emotion. "
                f"If the moment is hot, let it sound hot; if it is quiet, say so plainly."
            )

    # 3. Character verification (No hallucinated names)
    for p in clip.get("present_characters", []):
        if p.lower() not in bible_chars:
            problems.append(f"clip {clip_index + 1}: on-screen character '{p}' is not in Scene Bible characters.")

    for b in clip.get("blocking", []):
        cname = b.get("character", "")
        if cname.lower() not in bible_chars:
            problems.append(f"clip {clip_index + 1}: blocking character '{cname}' is not in Scene Bible characters.")
        if b.get("posture") and b.get("posture") not in POSTURES:
            problems.append(f"clip {clip_index + 1}: posture '{b.get('posture')}' must be one of {POSTURES}.")
        if b.get("in_frame") and b.get("in_frame") not in IN_FRAME:
            problems.append(f"clip {clip_index + 1}: in_frame '{b.get('in_frame')}' must be one of {IN_FRAME}.")
        fp = b.get("frame_position")
        if not fp or fp not in FRAME_POSITIONS:
            problems.append(f"clip {clip_index + 1}: frame_position '{fp}' must be one of {FRAME_POSITIONS}.")
        elif b.get("in_frame") in ("off screen", "has left") and fp != "off screen":
            problems.append(f"clip {clip_index + 1}: {cname} is in_frame '{b.get('in_frame')}', so frame_position must be 'off screen' (got '{fp}').")
        elif b.get("in_frame") in ON_SCREEN and fp == "off screen":
            problems.append(f"clip {clip_index + 1}: {cname} is in_frame '{b.get('in_frame')}', so frame_position cannot be 'off screen'.")

    for s in clip.get("action_steps", []):
        cname = s.get("character", "")
        if cname.lower() not in bible_chars:
            problems.append(f"clip {clip_index + 1}: action step character '{cname}' is not in Scene Bible characters.")

    # 4. Audio & Speaker rules
    turns = _clip_turns(clip)
    audio_text = " ".join(t.get("line", "") for t in turns).strip()
    words = _spoken_words(turns)
    for t in turns:
        tspk = (t.get("speaker") or "").strip()
        if tspk and tspk.lower() not in bible_chars:
            problems.append(f"clip {clip_index + 1}: '{tspk}' speaks here but is not in the Scene Bible characters.")

    if mode == "voiceover":
        if len(turns) != 1:
            problems.append(f"clip {clip_index + 1}: a voiceover clip has exactly one narrated line, not {len(turns)}.")
        vo_spk = (turns[0].get("speaker") or "").strip() if turns else ""
        if vo_spk.lower() != protagonist.lower():
            problems.append(f"clip {clip_index + 1}: voiceover speaker must be POV protagonist '{protagonist}', not '{vo_spk}'.")
        if not (MIN_WORDS <= words <= MAX_WORDS):
            problems.append(f"[SOFT] clip {clip_index + 1}: voiceover has {words} words; optimal is {MIN_WORDS} to {MAX_WORDS}.")
        # Verify mouth closed
        for s in clip.get("action_steps", []):
            act = s.get("action", "").lower()
            if any(w in act for w in ["speak", "says", "shouts", "whispers aloud", "talks", "mouth moves"]):
                problems.append(f"clip {clip_index + 1}: voiceover clip cannot have speaking mouth actions in '{act}'. Keep mouth closed!")
    elif mode == "dialogue":
        if not turns:
            problems.append(f"clip {clip_index + 1}: dialogue clip must have at least one spoken turn.")
        if len(turns) > MAX_VOICE_REFS:
            problems.append(f"clip {clip_index + 1}: {len(turns)} turns in one clip; at most {MAX_VOICE_REFS} fit in {CLIP_SECONDS} seconds.")
        if len({(t.get("speaker") or "").strip().lower() for t in turns}) > MAX_VOICE_REFS:
            problems.append(f"clip {clip_index + 1}: more than {MAX_VOICE_REFS} different speakers; kie.ai takes at most {MAX_VOICE_REFS} voices per clip.")
        if not (MIN_WORDS <= words <= MAX_WORDS):
            problems.append(f"[SOFT] clip {clip_index + 1}: {words} words across {len(turns)} turn(s); optimal is {MIN_WORDS} to {MAX_WORDS} in total.")
    elif mode == "shock_action":
        if turns:
            problems.append(f"clip {clip_index + 1}: shock_action clip must have no speech at all (found {len(turns)} turn(s)).")

    # Turns share one 5-second clip, so they have to queue rather than collide.
    prev_end = 0.0
    for n, t in enumerate(turns, 1):
        try:
            t_start, t_end = float(t.get("start_est", 0) or 0), float(t.get("end_est", 0) or 0)
        except (TypeError, ValueError):
            problems.append(f"clip {clip_index + 1}: turn {n} has a non-numeric time window.")
            continue
        if t_end <= t_start:
            problems.append(f"clip {clip_index + 1}: turn {n} ends at {t_end:.1f}s, at or before it starts ({t_start:.1f}s).")
        elif t_start < prev_end:
            problems.append(f"clip {clip_index + 1}: turn {n} starts at {t_start:.1f}s, before turn {n - 1} finishes at {prev_end:.1f}s. Turns must not overlap.")
        elif t_end > CLIP_SECONDS:
            problems.append(f"clip {clip_index + 1}: turn {n} runs to {t_end:.1f}s, past the end of a {CLIP_SECONDS}-second clip.")
        prev_end = max(prev_end, t_end)

    # 4b. The Master Plan owns the words: the clip may not reword, replace or improve the line it was given.
    beat_turns = _beat_lines(beat)
    if beat_turns and mode in ("voiceover", "dialogue"):
        if len(turns) != len(beat_turns):
            problems.append(
                f"clip {clip_index + 1}: the Master Plan gives this clip {len(beat_turns)} line(s), but you wrote {len(turns)}. "
                f"Use its lines exactly, in order, without merging or splitting them."
            )
        else:
            for n, (written, planned) in enumerate(zip(turns, beat_turns), 1):
                if _norm_line(written.get("line", "")) != _norm_line(planned.get("line", "")):
                    problems.append(
                        f"clip {clip_index + 1}, turn {n}: the line was changed. It must be the Master Plan's words: "
                        f"\"{planned.get('line', '')}\" (you wrote: \"{written.get('line', '')}\")."
                    )
                p_spk, w_spk = (planned.get("speaker") or "").strip(), (written.get("speaker") or "").strip()
                if p_spk and w_spk.lower() != p_spk.lower():
                    problems.append(f"clip {clip_index + 1}, turn {n}: the Master Plan gives this line to '{p_spk}', not '{w_spk}'.")

    # 4c. Nobody the beat cast may be dropped, and their actions may not be handed to someone else.
    clip_cast = {b.get("character", "").strip().lower() for b in clip.get("blocking", []) if b.get("character")}
    for name in beat.get("present_characters", []):
        if name and name.strip().lower() not in clip_cast:
            problems.append(
                f"clip {clip_index + 1}: the beat has '{name}' in this clip, but they are missing from blocking. "
                f"Include them (in_frame 'off screen' if they are not on camera); never drop them or give their actions to someone else."
            )
    actor = (beat.get("speaker_or_actor") or "").strip()
    if actor and actor.lower() not in clip_cast:
        problems.append(f"clip {clip_index + 1}: the beat's actor '{actor}' does not appear in this clip's blocking.")

    # 4d. A line may not speak a fact the audience has not been told yet.
    if beats:
        for term in _terms_still_secret(beats, clip_index):
            if _mentions(audio_text, term):
                problems.append(
                    f"clip {clip_index + 1}: a spoken line says '{term}', which the story has not revealed yet. "
                    f"Use only what the clips so far have established."
                )

    # 4d-bis. The voiceover is the protagonist's own thought, so it cannot narrate a scene they are not in.
    # A clip with nobody on screen is exempt: narration over an establishing shot is normal.
    if mode == "voiceover":
        blocked = [b.get("character", "").strip() for b in clip.get("blocking", []) if b.get("character")]
        if blocked and protagonist and protagonist.lower() not in {c.lower() for c in blocked}:
            problems.append(
                f"clip {clip_index + 1}: this is {protagonist}'s first-person voiceover, but they are not in the clip at all. "
                f"Either put them in the scene, or make it a shot with nobody on screen."
            )

    # 4e. The place does things; people do not belong in that description.
    env = (clip.get("environment") or "").strip()
    if env:
        m = _PERSON_IN_PLATE.search(env)
        if m:
            problems.append(f"clip {clip_index + 1}: \"environment\" describes a person ('{m.group(0)}'). It is what the PLACE does; people belong in blocking and action_steps.")
        for cname in bible_chars.values():
            if re.search(rf"\b{re.escape(cname.split()[0])}\b", env, re.I):
                problems.append(f"clip {clip_index + 1}: \"environment\" names '{cname}'. Describe only what the place itself does.")
                break

    # 4f. The prop diary: every prop is real, held by somebody real, and never quietly disappears.
    bible_props = {p["id"] for p in bible.get("props", [])}
    diary = clip.get("prop_state", []) or []
    seen_props = set()
    for p in diary:
        pid = p.get("prop_id", "")
        if pid not in bible_props:
            problems.append(f"clip {clip_index + 1}: prop '{pid}' is not in the Scene Bible props.")
        seen_props.add(pid)
        holder = (p.get("holder") or "").strip()
        if holder and holder.lower() != "scene" and holder.lower() not in bible_chars:
            problems.append(f"clip {clip_index + 1}: prop '{pid}' is held by '{holder}', who is not in the Scene Bible. Use a character's name, or 'scene' when it rests somewhere.")
    # A prop the clip leaves out is off camera and unchanged, which is now the expected way to say so:
    # _repair_narrated_clip carries it forward with in_frame False before this check ever runs, so the
    # stored diary stays complete while the model only has to write what the clip actually uses.
    #
    # The exception is a prop the ACTION touches. Since omission now means "unchanged", a prop that moves
    # here but goes unlisted is frozen at its old holder and state by the carry-forward - and that wrong
    # state then follows it for the rest of the story and into the video prompt. Matching is deliberately
    # conservative (the whole name, or a distinctive long word from it) because a false positive costs a
    # retry, while the fix for one is harmless: listing a prop the action names is never wrong.
    action_text = " ".join(st.get("action", "") for st in clip.get("action_steps", [])).lower()
    if action_text:
        # A single word only stands for a prop if nothing else answers to it. "radio" looks like
        # car_radio_mic, but the harbour terminal has a radio console in its layout, so an action step
        # saying "at the radio console" is describing furniture. Words that name scenery, or that belong to
        # more than one prop, are dropped and only the prop's whole name is matched.
        scenery = " ".join(f"{l.get('description', '')} {l.get('layout', '')}"
                           for l in bible.get("locations", [])).lower()
        for pid in sorted(bible_props - seen_props):
            phrases = {pid.replace("_", " ")}
            longest = max(pid.split("_"), key=len, default="")
            shared = sum(1 for other in bible_props if longest in other.split("_"))
            if (len(longest) >= 5 and shared == 1
                    and not re.search(rf"\b{re.escape(longest)}\b", scenery)):
                phrases.add(longest)
            if any(re.search(rf"\b{re.escape(p)}\b", action_text) for p in phrases):
                problems.append(
                    f"clip {clip_index + 1}: an action step handles '{pid}', but it is not in this clip's "
                    f"prop_state. Anything the action moves or uses must be listed here with its new holder "
                    f"and state, or it stays frozen where the last clip left it."
                )

    # 5. Speech timing validation (SOFT)
    if mode in ("voiceover", "dialogue"):
        start_est = float(clip.get("start_est", 0.5) or 0.5)
        end_est = float(clip.get("end_est", 4.5) or 4.5)
        if not (0.0 <= start_est < end_est <= CLIP_SECONDS):
            problems.append(f"[SOFT] clip {clip_index + 1}: speech timing ({start_est:.1f}s to {end_est:.1f}s) should be inside 0.0s to {CLIP_SECONDS}s.")
        span = max(0.1, end_est - start_est)
        if words > span * 3.2 + 0.5:
            problems.append(f"[SOFT] clip {clip_index + 1}: {words} words in {span:.1f}s may sound rushed; comfortable pacing is {words / 2.5:.1f}s.")

    # 6. Remote phone call blocking check
    beat_text = (beat.get("summary", "") + " " + " ".join(s.get("action", "") for s in clip.get("action_steps", []))).lower()
    is_phone_scene = any(w in beat_text for w in ["phone", "telephone", "intercom", "call from", "rings from", "receiver"])
    if is_phone_scene:
        for tspk in {(t.get("speaker") or "").strip() for t in turns}:
            if not tspk or tspk.lower() == protagonist.lower():
                continue
            for b in clip.get("blocking", []):
                if b.get("character", "").lower() == tspk.lower():
                    pos = b.get("position", "").lower()
                    if b.get("in_frame") in ON_SCREEN and any(w in pos for w in ["remote", "other line", "other end", "outside the room", "calling from outside"]):
                        problems.append(f"clip {clip_index + 1}: {tspk} is calling remotely on telephone/intercom; they must be in_frame: 'off screen', not visible in {loc_id}.")

    # 7. Blocking continuity with previous clip (if in same location)
    if prev_clip and prev_clip.get("location_id") == clip.get("location_id"):
        prev_blocking = {b["character"].lower(): b for b in prev_clip.get("blocking", [])}
        for b in clip.get("blocking", []):
            cname = b.get("character", "").lower()
            if cname in prev_blocking:
                pb = prev_blocking[cname]
                if pb.get("in_frame") in ON_SCREEN and b.get("in_frame") in ON_SCREEN:
                    # The previous clip's END, not its start: a character who sat down during clip N must be
                    # sitting when clip N+1 opens. Comparing start against start would instead force every
                    # clip in a location to open in the same pose, freezing the scene.
                    prev_post = pb.get("end_posture") or pb.get("posture")
                    curr_post = b.get("posture")
                    if prev_post and curr_post and prev_post != curr_post:
                        problems.append(f"clip {clip_index + 1}: {b['character']} opens with posture '{curr_post}', but the previous clip left them '{prev_post}'. The 0.0s pose must continue from where the last clip ENDED; show any change inside this clip's action_steps.")
                    prev_prof = pb.get("end_screen_profile") or pb.get("screen_profile")
                    curr_prof = b.get("screen_profile")
                    if _profiles_conflict(prev_prof, curr_prof):
                        problems.append(f"[SOFT] clip {clip_index + 1}: {b['character']} opens facing '{curr_prof}', but the previous clip left them facing '{prev_prof}'. No orientation snapping across the cut; turn inside the clip instead.")
                    # The previous clip's END, as with posture: a character who crossed the frame during
                    # clip N must open clip N+1 on the side they finished on. Comparing against its start
                    # would both flag that legitimate move and miss the flip it is meant to catch.
                    prev_fp = pb.get("end_frame_position") or pb.get("frame_position")
                    curr_fp = b.get("frame_position")
                    if _frame_positions_flip(prev_fp, curr_fp):
                        problems.append(
                            f"[SOFT] clip {clip_index + 1}: {b['character']} opens at '{curr_fp}', but was '{prev_fp}' in the previous clip (180-degree rule / screen direction flip across the cut). "
                            f"Maintain screen side unless an action step visibly moves them across."
                        )

    # 7b. Dynamic range. Two restrained clips back to back is normal; it is only worth noting because the
    #     first run managed five in a row, 25 seconds in which nobody raised their voice even once.
    if prev_clip:
        def _all_restrained(c):
            turns_ = _clip_turns(c)
            return bool(turns_) and all(_PERFORMANCE_IN_VOICE.search(t.get("delivery") or "") for t in turns_)
        if _all_restrained(clip) and _all_restrained(prev_clip):
            problems.append(
                f"[SOFT] clip {clip_index + 1}: this clip and the one before it are both delivered entirely "
                f"under restraint. Let the temperature move unless the scene genuinely calls for another quiet beat."
            )

    # 8. Inner states check in descriptions
    texts = [("shot", clip.get("shot", ""))] + [("action_steps", s.get("action", "")) for s in clip.get("action_steps", [])]
    for field, text in texts:
        m = _INNER_STATE.search(text)
        if m:
            problems.append(f"clip {clip_index + 1}: '{field}' names an inner state ('{m.group(0)}'); describe what the face and body visibly do instead.")

    # 9. Camera continuity tag check ([SAME SETUP] / [ANGLE CUT])
    shot_text = (clip.get("shot") or "").strip()
    if prev_clip and not re.search(r"\[(SAME SETUP|ANGLE CUT)\]", shot_text, re.I):
        problems.append(
            f"[SOFT] clip {clip_index + 1}: shot description should specify camera continuity tag [SAME SETUP] or [ANGLE CUT] at the start."
        )

    return problems


def _turn_windows_valid(turns: list[dict]) -> bool:
    """Are the speech windows ordered, non-overlapping and inside the clip?"""
    prev_end = 0.0
    for t in turns:
        try:
            start, end = float(t.get("start_est", -1)), float(t.get("end_est", -1))
        except (TypeError, ValueError):
            return False
        if not (0.0 <= start < end <= CLIP_SECONDS) or start < prev_end:
            return False
        prev_end = end
    return True


def _respace_turns(turns: list[dict]) -> None:
    """Give the turns clean, ordered windows inside the clip, each sized by its word count.

    Who speaks and in what order is the model's decision; only the clock is ours."""
    if not turns:
        return
    words = [max(1, len(_WORD.findall(t.get("line") or ""))) for t in turns]
    total = sum(words)
    first, last = 0.4, CLIP_SECONDS - 0.2
    gap = 0.2 if len(turns) > 1 else 0.0
    span = (last - first) - gap * (len(turns) - 1)
    cursor = first
    for turn, count in zip(turns, words):
        length = span * count / total
        turn["start_est"] = round(cursor, 2)
        turn["end_est"] = round(cursor + length, 2)
        cursor += length + gap


def _repair_narrated_clip(clip: dict, beat: dict, bible: dict, prev_clip: dict | None = None,
                          attempt: int = 0, final: bool = False) -> list[str]:
    """Fix what the code can fix by itself, in place, BEFORE validation - so it costs no retry.

    A retry is an OpenAI call, and three in a row stop the job. Over 60 clips even a 2% per-clip failure
    rate halts the run about 70% of the time, so anything that can be settled deterministically is settled
    here rather than re-asked. Returns what was changed, for the log.

    Repairs widen as attempts are spent: timing and prop carry-forward from the start, the Master Plan's
    wording once the model has had one chance at it, and a missing cast member placed off screen only on
    the last attempt, where the alternative is failing the clip."""
    fixed: list[str] = []

    # 1. Timing. The model chose the speakers and the order; bad arithmetic is not worth a retry.
    turns = _clip_turns(clip)
    if turns and not _turn_windows_valid(turns):
        _respace_turns(turns)
        clip["speech"] = turns
        fixed.append(f"re-spaced {len(turns)} speech window(s) so they fit the clip without overlapping")

    # 1b. A delivery that cancels its own emotion is an instruction to sound robotic, and the model obeys
    #     it: the first 5-minute run asked for "low, controlled counterstrike WITHOUT HEAT" and got exactly
    #     that, in the same clip where "bright, needling amusement" gave the other character real personality.
    #     The cancelling clause is always a tail on an otherwise usable delivery, so it is cut rather than
    #     re-asked - a retry is an OpenAI call, and this needs no judgement.
    for t in _clip_turns(clip):
        d = (t.get("delivery") or "").strip()
        trimmed = _CANCELS_EMOTION.sub("", d).strip(" ,;")
        if trimmed and trimmed != d:
            t["delivery"] = trimmed
            fixed.append(f"delivery {d!r} -> {trimmed!r} (it cancelled its own emotion)")
    if any("cancelled its own emotion" in f for f in fixed):
        clip["speech"] = _clip_turns(clip)

    # 2a. One prop, one entry. A real run produced a clip with 563 prop entries - the same ledger case 554
    #     times - because the model fell into a repetition loop that nothing stopped. That single clip cost
    #     36,408 tokens. Keeping the first entry per prop is deterministic and costs no retry.
    diary = clip.get("prop_state") or []
    if diary:
        unique, seen = [], set()
        for prop in diary:
            pid = prop.get("prop_id")
            if pid in seen:
                continue
            seen.add(pid)
            unique.append(prop)
        if len(unique) != len(diary):
            clip["prop_state"] = unique
            fixed.append(f"dropped {len(diary) - len(unique)} repeated prop entries, keeping one per prop")

    # 2b. A prop that appeared earlier and goes unmentioned here is off camera and unchanged - the clip is
    #     asked to list only what it sees or moves, so filling the rest back in is the normal path, not a
    #     rescue. It keeps the stored diary complete without paying to regenerate it every clip.
    if prev_clip:
        present = {p.get("prop_id") for p in clip.get("prop_state") or []}
        carried = []
        for prop in prev_clip.get("prop_state") or []:
            pid = prop.get("prop_id")
            if pid and pid not in present:
                clip.setdefault("prop_state", []).append({
                    "prop_id": pid,
                    "holder": prop.get("holder") or "scene",
                    "in_frame": False,
                    "state": (prop.get("state") or "").strip() or "unchanged since the previous clip",
                })
                carried.append(pid)
        if carried:
            fixed.append(f"carried {', '.join(carried)} forward in the prop diary, out of frame")

    # 3. After one retry the model has had its chance to write the plan's words. Take them.
    planned = _beat_lines(beat)
    if planned and attempt > 0 and clip.get("delivery_mode") in ("voiceover", "dialogue"):
        written = _clip_turns(clip)
        drifted = len(written) != len(planned) or any(
            _norm_line(w.get("line", "")) != _norm_line(p.get("line", ""))
            for w, p in zip(written, planned)
        )
        if drifted:
            clip["speech"] = [{
                "speaker": (p.get("speaker") or "").strip(),
                "line": p.get("line", ""),
                "delivery": (written[i].get("delivery") if i < len(written) else "") or "natural conversational tone",
                "start_est": 0.0,
                "end_est": 0.0,
            } for i, p in enumerate(planned)]
            _respace_turns(clip["speech"])
            fixed.append("replaced the spoken lines with the Master Plan's wording")

    # 4. Last resort: a character the beat requires is better off screen than missing.
    if final:
        blocked = {(b.get("character") or "").strip().lower() for b in clip.get("blocking") or []}
        added = []
        for name in beat.get("present_characters") or []:
            if name and name.strip().lower() not in blocked:
                clip.setdefault("blocking", []).append({
                    "character": name,
                    "position": "elsewhere in the location, out of shot",
                    "posture": "standing",
                    "screen_profile": "not visible",
                    "eyeline": "away from camera",
                    "end_position": "elsewhere in the location, out of shot",
                    "end_posture": "standing",
                    "end_screen_profile": "not visible",
                    "end_frame_position": "off screen",
                    "end_eyeline": "away from camera",
                    "awareness": "unchanged from the previous clip",
                    "frame_position": "off screen",
                    "in_frame": "off screen",
                })
                added.append(name)
        if added:
            fixed.append(f"placed {', '.join(added)} off screen, as the beat requires them in this clip")

    # 5. frame_position default / off_screen normalization
    for b in clip.get("blocking") or []:
        in_frame = b.get("in_frame")
        fp = b.get("frame_position")
        if in_frame in ("off screen", "has left"):
            if fp != "off screen":
                b["frame_position"] = "off screen"
                fixed.append(f"set frame_position of off-screen character '{b.get('character')}' to 'off screen'")
        elif not fp or fp not in FRAME_POSITIONS or fp == "off screen":
            b["frame_position"] = "centre frame"
            fixed.append(f"defaulted frame_position of '{b.get('character')}' to 'centre frame'")

    # 6. shot tag prefix: if missing [SAME SETUP] or [ANGLE CUT], prepend motivated tag
    shot_text = (clip.get("shot") or "").strip()
    if shot_text and prev_clip and not re.search(r"\[(SAME SETUP|ANGLE CUT)\]", shot_text, re.I):
        same_loc = bool(prev_clip.get("location_id") == clip.get("location_id"))
        c_num = clip.get("clip_number", 1)
        tag = "[SAME SETUP]" if (same_loc and c_num % 3 != 0) else "[ANGLE CUT]"
        clip["shot"] = f"{tag} {shot_text}"
        fixed.append(f"prepended {tag} camera continuity tag to shot")

    return fixed


def _narrated_supervisor_prompt(
    topic: str,
    bible: dict,
    beat: dict,
    prev_clips: list[dict],
    clip: dict
) -> tuple[str, str]:
    """Generates system and user prompts for Script Supervisor in hybrid narrated drama.
    Context is strictly scoped: current clip, up to 2 previous clips, bible, and current beat."""
    protagonist = bible.get("pov_protagonist", "protagonist")
    clip_num = clip.get("clip_number", beat.get("clip_number", "?"))
    recent_clips = prev_clips[-2:] if prev_clips else []

    system_prompt = f"""You are the script supervisor (continuity supervisor) on an AI-generated hybrid narrated drama.
Each 5-second clip is rendered separately by a video model that sees ONLY that clip's own text and reference pictures, with no memory of other clips, so every contradiction or missing detail becomes a visible mistake.

The story is told from the FIRST-PERSON perspective of the protagonist: {protagonist}.

Analyze the newly written clip screenplay against the scene bible, the target beat, and the previous filmed clips.
Critique these 7 critical areas:
1. BEAT FIDELITY: Does the clip faithfully accomplish what its assigned beat dictates?
2. BLOCKING & POSITION CONTINUITY:
   - Does each character at 0.0s start where and in the posture/facing/profile that the PREVIOUS clip ENDED them in?
   - Any physical move or posture shift must be explicitly performed in action_steps.
   - Does camera placement agree with the blocking? Does the shot adhere to the 180-degree rule across cuts?
3. KNOWLEDGE & AWARENESS:
   - Does anyone speak about, answer, or react to something their 'awareness' says they have not noticed?
   - A character who was off-screen or absent does not know what was said while they were away.
4. FIRST-PERSON POV:
   - The voiceover is {protagonist}'s own internal thoughts in the moment.
   - It may ONLY draw upon what {protagonist} has seen, heard, or could reasonably guess by now.
   - The voiceover must NEVER exhibit omniscience or narrate events/places {protagonist} has not witnessed.
5. PROPS HONESTY & CONTINUITY:
   - Does every prop maintain its holder and state unless an action step changes it?
   - Is 'in_frame' honest (marked true ONLY if the camera clearly sees it where the action happens)?
   - Props must not teleport or quietly disappear.
6. SPACE & LAYOUT ADHERENCE:
   - Do character positions and movements agree with the location's fixed layout (doors, counters, furniture)?
   - Entrances, exits, and walking distances must make physical sense. Nobody teleports.
7. PACKING & PACING:
   - Is too much crammed into a single 5-second clip?
   - Do dialogue lines and physical actions have sufficient time to play out naturally?

BEFORE reporting anything:
- Check it against the location's layout and blocking.
- Report ONLY genuine, visible continuity errors or narrative contradictions that would break the film.
- Do NOT report stylistic preferences, minor phrasing choices, or camera details not visible to the audience.
- Return short, concrete sentences describing each problem and how to fix it.
- If there are no genuine continuity problems, return {{"problems": []}}."""

    user_prompt = f"""Story Premise:
{topic}

Scene Bible (Characters, Locations, Props):
{json.dumps(bible, indent=2, ensure_ascii=False)}

Target Beat for Clip {clip_num}:
{json.dumps(beat, indent=2, ensure_ascii=False)}

Previous Filmed Clips (Last up to 2 clips):
{json.dumps(recent_clips, indent=2, ensure_ascii=False) if recent_clips else "None (this is the first clip)."}

NEW Written Clip to Supervise (Clip {clip_num}):
{json.dumps(clip, indent=2, ensure_ascii=False)}

Check the NEW written clip for continuity and fidelity. Return JSON adhering to the schema."""

    return system_prompt, user_prompt


def supervise_narrated_chapter(
    topic: str,
    bible: dict,
    beat: dict,
    prev_clips: list[dict],
    clip: dict
) -> list[str]:
    """A secondary OpenAI critique of a clip screenplay against story continuity."""
    c_num = clip.get("clip_number", beat.get("clip_number", "?"))
    print(f"  Script supervisor is checking continuity for clip {c_num}...", flush=True)
    sys_p, usr_p = _narrated_supervisor_prompt(topic, bible, beat, prev_clips, clip)
    answer = _ask_openai_json(sys_p, usr_p, "narrated_supervisor", SUPERVISOR_SCHEMA, model=app.OPENAI_CLIP_MODEL)
    problems = [f"script supervisor: {p}" for p in answer.get("problems", []) if p and str(p).strip()]
    return problems


def write_narrated_chapter(
    topic: str,
    clip_index: int,
    total_clips: int,
    beats: list[dict],
    bible: dict,
    prev_clips: list[dict],
    supervise: bool = False
) -> tuple[dict, list[str]]:
    """Writes an individual clip script with validation."""
    beat = beats[clip_index]
    sys_p, usr_p = _narrated_chapter_prompt(topic, clip_index, total_clips, beat, bible, prev_clips, beats=beats)
    # A retry adds to this rather than replacing it: the beat, the roadmap and the clip history are what the
    # model needs in order to fix anything, and keeping the message's head unchanged keeps the cached prefix.
    base_usr = usr_p
    prev_clip = prev_clips[-1] if prev_clips else None

    # Dynamic schema locking locations and characters from scene_bible
    location_ids = [loc["id"] for loc in bible.get("locations", [])]
    character_names = [c["name"] for c in bible.get("characters", [])]
    prop_ids = [p["id"] for p in bible.get("props", [])]
    schema = _narrated_chapter_schema(location_ids, character_names, prop_ids)

    supervisor_retried = False

    for attempt in range(CHAPTER_RETRIES + 1):
        data = _ask_openai_json(sys_p, usr_p, "narrated_chapter", schema, model=app.OPENAI_CLIP_MODEL)
        clip = data["clips"][0]
        _normalize_narrated_clip(clip, bible)  # settle names and the turn shape before repairing
        last_attempt = attempt == CHAPTER_RETRIES
        changes = _repair_narrated_clip(clip, beat, bible, prev_clip, attempt=attempt, final=last_attempt)
        if changes:
            _normalize_narrated_clip(clip, bible)  # a repair may have changed the cast
            for c in changes:
                print(f"  Clip {clip_index+1} repaired: {c}")
        problems = _check_narrated_chapter(data, beat, bible, prev_clip, clip_index=clip_index, beats=beats)
        problems += [f"[SOFT] clip {clip_index+1}: auto-repaired - {c}" for c in changes]
        hard = _hard_problems(problems)

        # Gating: supervisor runs ONLY after code checks pass (not hard)!
        if not hard:
            if supervise:
                if not supervisor_retried and not last_attempt:
                    sup_problems = supervise_narrated_chapter(topic, bible, beat, prev_clips, clip)
                    if sup_problems:
                        supervisor_retried = True
                        print(f"  Clip {clip_index+1} supervisor note(s), retrying (1 rewrite allowed):")
                        for sp in sup_problems:
                            print(f"    - {sp}")
                        usr_p = (
                            base_usr
                            + "\n\nHere is the clip you wrote:\n" + json.dumps(clip, indent=2, ensure_ascii=False)
                            + "\n\nThe script supervisor raised these continuity notes:\n- " + "\n- ".join(sup_problems)
                            + "\n\nCRITICAL INSTRUCTION: You must strictly maintain visual, location, and character continuity. "
                            f"Clip {clip_index+1} MUST stay in location '{beat['location_id']}'. "
                            "Fix the specific continuity violations while keeping the narrative consistent. Return valid JSON."
                        )
                        continue
                else:
                    # Either rewrite already happened, or this is last_attempt: check supervisor and downgrade any notes to [SOFT]
                    sup_problems = supervise_narrated_chapter(topic, bible, beat, prev_clips, clip)
                    if sup_problems:
                        print(f"  Clip {clip_index+1} supervisor note(s) downgraded to [SOFT]:")
                        for sp in sup_problems:
                            print(f"    - {sp}")
                        problems += [f"[SOFT] {sp}" for sp in sup_problems]
            return data, problems

        if not last_attempt:
            print(f"  Clip {clip_index+1} check: {len(hard)} issue(s), retrying ({attempt+1}/{CHAPTER_RETRIES}):")
            for h in hard:
                print(f"    - {h}")
            usr_p = (
                base_usr
                + "\n\nHere is your previous answer:\n" + json.dumps(clip, indent=2, ensure_ascii=False)
                + "\n\nIt broke these rules:\n- " + "\n- ".join(hard)
                + "\n\nCRITICAL INSTRUCTION: You must strictly maintain visual, location, and character continuity. "
                f"Clip {clip_index+1} MUST stay in location '{beat['location_id']}'. "
                "Fix the specific continuity violations while keeping the narrative consistent. Return valid JSON."
            )
    # Retries are spent. The lines were already replaced with the Master Plan's by repair 3, and the beat's
    # cast placed off screen by repair 4, so whatever is left here is a real problem for the caller to judge.
    return data, problems


# ---------------------------------------------------------------------------
# Prompt Builder for Seedance (Kie.ai)
# ---------------------------------------------------------------------------
def build_narrated_prompt(
    clip: dict,
    bible: dict,
    cast_bank: dict[str, str],
    location_bank: dict[str, list[str]],
    voice_bank: dict[str, str],
    prev_clip: dict | None = None
) -> tuple[str, list[str], list[str]]:
    """Compiles Seedance prompt and references tailored to delivery_mode."""
    mode = clip.get("delivery_mode", "dialogue")
    protagonist = bible["pov_protagonist"]
    loc_id = clip["location_id"]
    loc = next((l for l in bible["locations"] if l["id"] == loc_id), None)

    on_screen = clip["present_characters"][:MAX_ON_SCREEN]
    faces = [n for n in on_screen if cast_bank.get(n)]
    place_urls = location_bank.get(loc_id, [])[:max(1, min(PLACE_VIEWS[1], MAX_REF_IMAGES - len(faces)))]

    ref_images = list(place_urls)
    char_tags = []
    for name in on_screen:
        cinfo = next((c for c in bible["characters"] if c["name"].lower() == name.lower()), None)
        # "look" is derived from "appearance" by _compile_character_visuals(); a bible that skipped that
        # step (an older job, or a character added by a continuation) must still render.
        look = (cinfo.get("look") or (_compile_look(cinfo["appearance"]) if cinfo and cinfo.get("appearance") else "")) if cinfo else ""
        if cast_bank.get(name) and len(ref_images) < MAX_REF_IMAGES:
            ref_images.append(cast_bank[name])
            # The picture IS the description. Repeating the written look beside it hands the model a second,
            # competing account of the same face, and it picks a different winner in every clip - which is
            # how one character's hair changed colour from clip to clip.
            char_tags.append(f"{name} is @Image{len(ref_images)}")
        else:
            char_tags.append(f"{name} ({look})")

    shot = clip["shot"].rstrip(". ")
    setting_note = f"Location: {loc['description']}" if loc else f"Location: {loc_id}"
    if place_urls:
        tags = ", ".join([f"@Image{i+1}" for i in range(len(place_urls))])
        setting_note = f"Location matches {tags}: maintain architectural layout, palette, and lighting"

    parts = [f"Five-second {shot}, {setting_note}."]
    parts.append(f"Characters: {'. '.join(char_tags)}." if on_screen else "Cinematic environmental shot.")
    if any("@Image" in t for t in char_tags):
        parts.append("Each named character's face, hair colour, hairstyle and clothing match their reference image exactly: do not restyle, recolour or re-cast anyone.")

    environment = (clip.get("environment") or "").strip()
    if environment:
        parts.append(f"The place itself: {environment.rstrip('. ')}.")

    # Props the camera can actually see, with the bible's fixed description of each
    prop_desc = {p["id"]: p["description"] for p in bible.get("props", [])}
    shown_props = [p for p in clip.get("prop_state", []) or [] if p.get("in_frame")]
    if shown_props:
        parts.append("Props in the shot: " + " ".join(
            f"{prop_desc.get(p['prop_id'], p['prop_id'].replace('_', ' ')).rstrip('. ')} "
            f"({'held by ' + p['holder'] if (p.get('holder') or 'scene') != 'scene' else 'resting in the scene'}; "
            f"{(p.get('state') or '').rstrip('. ')})."
            for p in shown_props))

    # Action summary
    def _plain(text: str) -> str:
        # Prop ids like 'laundry_cart' sometimes leak into the prose; Seedance should read plain words.
        for pid in prop_desc:
            text = re.sub(rf"\b{re.escape(pid)}\b", pid.replace("_", " "), text)
        return text

    action_descs = [f"{s['character']}: {_plain(s['action'])}" for s in clip.get("action_steps", [])]
    if action_descs:
        parts.append(f"Actions: {'; '.join(action_descs)}.")

    # Audio references & directives
    ref_audios: list[str] = []
    turns = _clip_turns(clip)

    def _voice_tag(name: str) -> str:
        """Attach this speaker's banked voice and return '@AudioN', or '' the first time we hear them.

        kie.ai takes at most MAX_VOICE_REFS reference audios per request, and the same speaker reuses the
        same tag rather than a second slot."""
        url = voice_bank.get(name)
        if not url:
            return ""
        if url not in ref_audios:
            if len(ref_audios) >= MAX_VOICE_REFS:
                return ""
            ref_audios.append(url)
        return f"@Audio{ref_audios.index(url) + 1}"

    def _window(turn: dict, index: int, total: int) -> tuple[float, float]:
        """This turn's slot inside the clip, falling back to an even share when the script gave none."""
        share = (CLIP_SECONDS - 0.8) / max(1, total)
        default_start = 0.4 + index * share
        start = max(0.4, float(turn.get("start_est", default_start) or default_start))
        end = min(CLIP_SECONDS - 0.2, float(turn.get("end_est", start + share) or (start + share)))
        if end <= start:
            end = min(CLIP_SECONDS - 0.2, start + share)
        return start, end

    def _spoken(turn: dict) -> tuple[str, str, str, str]:
        """(speaker, delivery, line, written voice). The voice matters only until one has been banked: on the
        clip where a character first speaks there is no @Audio to point at, so the bible's description is the
        only thing shaping the voice Seedance invents - and that invented voice is then banked and reused for
        the rest of the video. Leaving it out is what makes a narrator sound flat for all sixty clips."""
        name = (turn.get("speaker") or "").strip()
        char = next((c for c in bible.get("characters", []) if c["name"].lower() == name.lower()), None)
        delivery = (turn.get("delivery") or "").strip() or "natural conversational tone"
        voice = (char.get("voice") or "").strip() if char else ""
        return name, movie._delivery_only(delivery, voice), (turn.get("line") or ""), voice

    if mode == "voiceover" and turns:
        start_est, end_est = _window(turns[0], 0, 1)
        _name, delivery, line, written_voice = _spoken(turns[0])
        tag = _voice_tag(protagonist)
        if tag:
            in_voice = f" in {tag}'s voice"
        else:  # nothing banked yet: describe the voice, or this first take sets a flat one for the whole film
            in_voice = f" in {written_voice.rstrip('. ')}" if written_voice else ""
        parts.append(
            f"VOICEOVER DIRECTIVE (CRITICAL): [{start_est:.1f}s to {end_est:.1f}s] An off-screen internal monologue narrates this scene{in_voice}, {delivery}: \"{line}\". "
            f"The characters on screen DO NOT speak or move their mouths. Keep lips closed with natural resting facial expression. "
            f"Characters engage solely in physical cinematic acting. No on-screen lip movement."
        )
    elif mode == "dialogue" and turns:
        on_screen_now = {b.get("character", "").lower() for b in clip.get("blocking", []) if b.get("in_frame") in ON_SCREEN}
        lines = []
        for i, turn in enumerate(turns):
            start_est, end_est = _window(turn, i, len(turns))
            name, delivery, line, written_voice = _spoken(turn)
            tag = _voice_tag(name)
            spoken_as = (f" matching {tag}" if tag
                         else (f", speaking in {written_voice.rstrip('. ')}" if written_voice else ""))
            if name.lower() in on_screen_now:
                lines.append(f"[{start_est:.1f}s to {end_est:.1f}s] {name} speaks aloud on camera with synchronized lip movement{spoken_as}, {delivery}: \"{line}\".")
            else:
                remote_as = (f" in {tag}'s voice" if tag
                             else (f", in {written_voice.rstrip('. ')}" if written_voice else ""))
                lines.append(f"[{start_est:.1f}s to {end_est:.1f}s] {name}'s voice comes from the telephone receiver/off-screen{remote_as}, {delivery}: \"{line}\".")
        parts.append("DIALOGUE DIRECTIVE: " + " ".join(lines))
        if len(turns) > 1:
            speaking = [n for n in dict.fromkeys((t.get("speaker") or "").strip() for t in turns) if n]
            parts.append(
                f"The lines run back to back in one continuous take, in that order, with a natural beat between them - "
                f"never at the same time and never repeated. Only the speaker of each line moves their lips during it; "
                f"everyone else listens with their mouth closed. Hold {movie._join(speaking)} in frame together."
            )
    else:  # shock_action
        parts.append(
            "REACTION DIRECTIVE: Cinematic non-verbal shot. The ONLY audio is diegetic sound that belongs to this place - room tone, footsteps, a door, rain, a telephone, a caught breath. "
            "No dialogue, no voices, no humming, no lip movement, and absolutely no musical score, sting, drone or soundtrack of any kind."
        )

    parts.append("Fluid cinematic physical motion throughout: render active character bodily reactions, natural momentum, and dynamic responsive lighting; characters must not freeze or remain static.")
    parts.append("No background music.")

    # Continuity anchor
    blocking = [b for b in clip.get("blocking", []) if b["in_frame"] in ON_SCREEN]
    if blocking:
        def _arc(b: dict) -> str:
            start_prof = b.get("screen_profile", "front")
            start = f"{b['posture']}, screen {start_prof}"
            end_post, end_prof = b.get("end_posture") or b["posture"], b.get("end_screen_profile") or start_prof
            start_fp = b.get("frame_position") or ""
            end_fp = b.get("end_frame_position") or start_fp
            # The opening frame position is already listed below; the arc only carries the move.
            if (end_post, _norm_desc(end_prof), end_fp) == (b["posture"], _norm_desc(start_prof), start_fp):
                return f"{b['character']}: {start}, held throughout"
            moved = f", ends {end_post}, screen {end_prof}"
            if end_fp and end_fp != start_fp:
                moved += f", crossing to {end_fp}"
            return f"{b['character']}: starts {start}{moved}"
        parts.append(
            f"CONTINUITY ANCHOR: at the 0.0s cut and through the clip, [{'; '.join(_arc(b) for b in blocking)}]. "
            f"No sudden jumping or mirroring; any change happens on screen, not across the cut."
        )
        frame_pos = "; ".join(f"{b['character']} {b.get('frame_position', 'centre frame')}" for b in blocking)
        if frame_pos:
            parts.append(f"Frame positions: [{frame_pos}].")
        knows = "; ".join(f"{b['character']} {(b.get('awareness') or '').rstrip('. ')}"
                          for b in blocking if (b.get("awareness") or "").strip())
        if knows:
            parts.append(f"What each one has noticed: {knows}. Nobody reacts to anything they have not noticed.")

    prompt = " ".join(parts)
    return prompt, ref_images, ref_audios


# ---------------------------------------------------------------------------
# Clip Render & Voice Banking
# ---------------------------------------------------------------------------
def trim_windowed_voice(video_path: Path, speaker_name: str, start_est: float, end_est: float,
                        turn_idx: int, dialogue_list: list, out_dir: Path | None = None) -> Path | None:
    """Extracts a high-quality voice reference sample for speaker_name using NumPy RMS energy detection.
    Writes to the job's own voices/ directory with a sanitized, space-free filename."""
    import numpy as np
    safe_name = re.sub(r"[^\w\-]+", "_", speaker_name.strip().lower()).strip("_")
    voices_dir = (out_dir or video_path.parent.parent) / "voices"
    voice_path = voices_dir / f"{safe_name}_{uuid.uuid4().hex[:8]}.wav"

    prev_end = float(dialogue_list[turn_idx - 1].get("end_est", 0.0) or 0.0) if turn_idx > 0 else 0.0
    next_start = float(dialogue_list[turn_idx + 1].get("start_est", CLIP_SECONDS) or CLIP_SECONDS) if turn_idx < len(dialogue_list) - 1 else float(CLIP_SECONDS)
    search_start, search_end = max(prev_end, start_est - 1.0), min(next_start, end_est + 1.0)

    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(video_path), "-vn", "-ac", "1", "-ar", "16000", "-f", "f32le", "-"],
        capture_output=True
    ).stdout
    x = np.frombuffer(raw, dtype=np.float32)
    if len(x) < 1600:
        return None
    frame, sr = 320, 16000
    start_frame = int(search_start * sr) // frame
    end_frame = min(int(search_end * sr) // frame, len(x) // frame)
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
    voiced = np.flatnonzero((level > loudest - 20) & (flatness < 0.25))
    if len(voiced) == 0:
        return None
    margin_slices = 4
    local_start = max(0, voiced[0] - margin_slices)
    local_end = min(len(slices), voiced[-1] + margin_slices + 1)
    abs_start_sec = search_start + (local_start * frame / sr)
    abs_end_sec = search_start + (local_end * frame / sr)
    if abs_end_sec - abs_start_sec < 2.0:
        return None  # kie.ai rejects audio < 2s; next line gets tried
    abs_end_sec = min(abs_end_sec, abs_start_sec + 4.9)

    voices_dir.mkdir(parents=True, exist_ok=True)
    _run_ffmpeg("-y", "-i", str(video_path), "-vn", "-ss", f"{abs_start_sec:.4f}", "-to", f"{abs_end_sec:.4f}", "-c:a", "pcm_s16le", str(voice_path))
    return voice_path


def render_narrated_clip(n: int, prompt: str, image_urls: list[str], audio_urls: list[str], interactive: bool = False,
                         out_dir: Path | None = None):
    """Executes Kie.ai generation with request logging and error retry ladder.

    - Catch KieError audio copyright filter triggers and retry once with AUDIO_RETRY_NOTE.
    - Catch TimeoutError (15-min polling limit) and halt without auto-retrying to prevent double billing.
    - Catch transient KieError / network exceptions and auto-retry up to CLIP_RETRIES times with backoff.
    - Logs every attempt, request input, and reply into requests/clip_NN.json per job."""
    record_path = (out_dir or OUTPUT_DIR) / "requests" / f"clip_{n:02d}.json"
    record_path.parent.mkdir(parents=True, exist_ok=True)
    old = json.loads(record_path.read_text(encoding="utf-8")) if record_path.exists() else {}
    record = {"attempts": old.get("attempts", [])}
    auto_retried_copyright = False
    retries_left = CLIP_RETRIES

    while True:
        record["sent_to_kie"] = {
            "model": app.KIE_MODEL,
            "input": _clip_input(prompt, RESOLUTION, CLIP_SECONDS, True, None, audio_urls or None, image_urls or None)
        }
        record_path.write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")
        t0 = time.time()
        print(f"    rendering clip {n} on kie.ai...", flush=True)
        try:
            result = generate_clip(
                prompt=prompt,
                resolution=RESOLUTION,
                duration=CLIP_SECONDS,
                reference_image_urls=image_urls or None,
                reference_audio_urls=audio_urls or None,
                generate_audio=True
            )
            print(f"    ✓ clip {n} done in {time.time() - t0:.0f}s (credits: {result.get('credits_consumed', '?')})", flush=True)
            record["kie_reply"] = result
            record_path.write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")
            return result
        except TimeoutError as e:
            record["attempts"].append({"sent_to_kie": record["sent_to_kie"], "error": f"TimeoutError: {e}"})
            record_path.write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")
            print(f"    ✗ clip {n} timed out waiting for kie.ai after 15 minutes: {e}", flush=True)
            print("    [Halt] Stopped without re-triggering to prevent double billing. Resume job when ready.", flush=True)
            return "quit"
        except Exception as e:
            record["attempts"].append({"sent_to_kie": record["sent_to_kie"], "error": str(e)})
            record_path.write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")
            print(f"    ✗ clip {n} failed: {e}", flush=True)

            # 1. Copyright filter fallback (retry once with AUDIO_RETRY_NOTE)
            if isinstance(e, KieError) and not auto_retried_copyright and "copyright" in str(e).lower():
                auto_retried_copyright = True
                if prompt.endswith("No background music."):
                    prompt = prompt[:-len("No background music.")] + AUDIO_RETRY_NOTE
                elif "No background music." in prompt:
                    prompt = prompt.replace("No background music.", AUDIO_RETRY_NOTE)
                else:
                    prompt = prompt + " " + AUDIO_RETRY_NOTE
                print("    retrying once with stricter no-music wording (copyright filter fallback)...", flush=True)
                continue

            # 2. Automated vs interactive handling for other failures
            if not interactive:
                if retries_left > 0:
                    retries_left -= 1
                    print(f"    [Auto] Retrying clip {n} in 5s ({retries_left} retries left)...", flush=True)
                    time.sleep(5)
                    continue
                print(f"    ✗ [Auto] Clip {n} failed after retries. Stopping execution to preserve credits.", flush=True)
                return "quit"

            ans = ""
            while ans not in ("r", "s", "q"):
                ans = input(f"    Clip {n}: [r] retry  [s] skip  [q] quit (progress kept for resume): ").strip().lower()
            if ans == "r":
                continue
            return "skip" if ans == "s" else "quit"


def bank_voice(clip_path: Path, speaker: str, voice_bank: dict, start_est: float = 0.5, end_est: float = 4.5,
               turn_index: int = 0, turns: list[dict] | None = None, out_dir: Path | None = None) -> None:
    """Extracts a high-quality voice sample from a rendered clip using NumPy RMS energy detection.

    `turns` is the clip's full turn list, so the energy search for one speaker stays inside their own window
    and cannot wander into the line before or after it. Filenames are space-sanitized and stored in the job's voices/ folder."""
    if speaker.lower() in {k.lower() for k in voice_bank}:
        return
    window = turns or [{"start_est": start_est, "end_est": end_est}]
    try:
        # Use intelligent RMS energy waveform voice trimming
        wav_path = trim_windowed_voice(
            clip_path, speaker, start_est, end_est, turn_index, window, out_dir=out_dir
        )
        if not wav_path or not wav_path.exists():
            # Fallback to precise ffmpeg window if waveform energy detector didn't find clear burst
            safe_name = re.sub(r"[^\w\-]+", "_", speaker.strip().lower()).strip("_")
            voices_dir = (out_dir or clip_path.parent.parent) / "voices"
            voices_dir.mkdir(parents=True, exist_ok=True)
            wav_path = voices_dir / f"{safe_name}_{uuid.uuid4().hex[:8]}.wav"
            _run_ffmpeg(
                "-y", "-i", str(clip_path),
                "-ss", f"{start_est:.2f}", "-to", f"{end_est:.2f}",
                "-vn", "-ar", "44100", "-ac", "2", str(wav_path)
            )
        url = _upload_to_kie(wav_path)
        voice_bank[speaker] = url
        print(f"    ★ banked voice for {speaker}: {url}", flush=True)
    except Exception as e:
        print(f"    ⚠ voice banking failed for {speaker}: {e}", flush=True)


# ---------------------------------------------------------------------------
# Final Assembly
# ---------------------------------------------------------------------------
def assemble_narrated_video(run_dir: Path, total_clips: int) -> Path:
    """Concatenates all completed clips into a final master video, normalizing geometry
    and trimming lead-in dead air on clips after the first (i > 0)."""
    clips_dir = run_dir / "clips"
    clip_files = sorted(clips_dir.glob("clip_*.mp4"))
    if not clip_files:
        raise RuntimeError("No clips found to assemble.")

    probes = [app._probe(p) for p in clip_files]
    width, height, fps = probes[0]["width"], probes[0]["height"], probes[0]["fps"]
    norm_parts = []
    for i, p in enumerate(clip_files):
        trim = (i > 0)
        norm_file = app._normalized(p, width, height, fps, trim_lead_in=trim)
        norm_parts.append(norm_file)

    concat_list = run_dir / "concat.txt"
    concat_list.write_text("".join(f"file '{p.as_posix()}'\n" for p in norm_parts), encoding="utf-8")
    part = run_dir / "part_final_hybrid_drama.mp4"
    out_path = run_dir / "final_hybrid_drama.mp4"

    app._run_ffmpeg(
        "-f", "concat", "-safe", "0", "-i", str(concat_list),
        "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(part),
    )
    part.replace(out_path)
    print(f"\n==========================================")
    print(f"🎬 FINAL HYBRID DRAMA ASSEMBLED:")
    print(f"   {out_path}")
    print(f"==========================================\n")
    return out_path


# ---------------------------------------------------------------------------
# Standalone CLI / Execution Flow
# ---------------------------------------------------------------------------
def run_hybrid_drama(topic: str, duration: int = 75, interactive: bool = False, script_only: bool = False, supervise: bool = False):
    """Full end-to-end execution of Hybrid Narrated Drama."""
    total_clips = duration // CLIP_SECONDS
    print(f"\n--- HYBRID NARRATED DRAMA: {duration}s ({total_clips} clips) ---")
    print(f"Topic: {topic[:80]}...\n")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / "clips").mkdir(parents=True, exist_ok=True)

    # 1. Master Plan
    print("Step 1: Generating Master Plan with Rapid Micro-Cycles...")
    outline, problems = write_narrated_outline(topic, duration, total_clips)
    hard = _hard_problems(problems)
    if hard:
        print("\n  Master Plan still breaks these rules after retries. Nothing was generated:")
        for p in hard:
            print(f"    - {p}")
        sys.exit("Fix the premise (or rerun) - no credits were spent.")
    for p in _soft_problems(problems):
        print(f"  note: {p}")
    bible = outline["scene_bible"]
    beats = outline["beats"]
    protagonist = bible["pov_protagonist"]
    print(f"  ✓ Master Plan ready: Protagonist = '{protagonist}', {len(beats)} beats.")

    plan_file = OUTPUT_DIR / "master_plan.json"
    plan_file.write_text(json.dumps(outline, indent=2, ensure_ascii=False), encoding="utf-8")

    if script_only:
        print(f"Plan saved to {plan_file}. --script-only set, exiting.")
        return

    # 2. FLUX Reference Images
    print("\nStep 2: Generating Cast & Location reference images via FLUX...")
    cast_bank = {}
    _compile_bible_visuals(bible)
    for c in bible["characters"]:
        url = movie.generate_flux_image(c["image_prompt"])
        cast_bank[c["name"]] = url
        print(f"  ✓ FLUX cast image for {c['name']}")

    location_bank = {}
    for loc in bible["locations"]:
        master = movie.generate_flux_image(loc["image_prompt"])
        views = [master]
        for view_desc in loc.get("views", [])[1:3]:
            angle = movie.generate_flux_image(movie._view_prompt(view_desc), input_image=master)
            views.append(angle)
        location_bank[loc["id"]] = views
        print(f"  ✓ FLUX location images for {loc['id']} ({len(views)} views)")

    # 3. Interleaved Generation Loop
    print("\nStep 3: Interleaved Scripting & Video Generation...")
    voice_bank = {}
    prev_clips = []

    for i in range(total_clips):
        beat = beats[i]
        mode = beat["delivery_mode"]
        print(f"\n--- Clip {i+1}/{total_clips} [{mode.upper()}] (Cycle {beat.get('cycle_number', '?')}) ---")

        # Scripting
        ch_data, clip_problems = write_narrated_chapter(topic, i, total_clips, beats, bible, prev_clips, supervise=supervise)
        clip_hard = _hard_problems(clip_problems)
        if clip_hard:
            print(f"\n  Clip {i+1}'s script still breaks these rules after retries. Stopping before it is rendered:")
            for p in clip_hard:
                print(f"    - {p}")
            sys.exit(f"Clips 1 to {i} are kept; clip {i+1} was not rendered, so it cost nothing.")
        clip_script = ch_data["clips"][0]

        # Prompt Compilation
        prev_script = prev_clips[-1] if prev_clips else None
        prompt, img_urls, aud_urls = build_narrated_prompt(
            clip_script, bible, cast_bank, location_bank, voice_bank, prev_clip=prev_script
        )

        # Video Render
        res = render_narrated_clip(i + 1, prompt, img_urls, aud_urls, interactive=interactive)
        if res == "quit":
            print(f"Halting execution at clip {i+1}.")
            return

        video_url = res["video_url"]
        clip_file = OUTPUT_DIR / "clips" / f"clip_{i+1:02d}.mp4"
        _download(video_url, clip_file)

        # Bank voice if new speaker or protagonist
        clip_turns = _clip_turns(clip_script)
        for t_idx, turn in enumerate(clip_turns):
            spk = (turn.get("speaker") or "").strip()
            if not spk or not should_bank_voice(turn, spk, beats, i):
                continue
            s_est = float(turn.get("start_est", 0.5) or 0.5)
            e_est = float(turn.get("end_est", 4.5) or 4.5)
            bank_voice(clip_file, spk, voice_bank, start_est=s_est, end_est=e_est,
                       turn_index=t_idx, turns=clip_turns)

        prev_clips.append(clip_script)

    # 4. Assemble
    assemble_narrated_video(OUTPUT_DIR, total_clips)


def main():
    parser = argparse.ArgumentParser(description="Hybrid Narrated Drama Standalone Pipeline")
    parser.add_argument("topic", nargs="*", help="Story prompt or premise")
    parser.add_argument("--duration", type=int, default=75, help="Duration in seconds (multiple of 5)")
    parser.add_argument("--interactive", action="store_true", help="Prompt before each clip")
    parser.add_argument("--script-only", action="store_true", help="Generate only the master plan JSON")
    parser.add_argument("--supervise", action="store_true", help="Enable script supervisor AI continuity check (default off)")
    args = parser.parse_args()

    topic = " ".join(args.topic).strip() if args.topic else "A young wedding planner in Italy discovers the groom is the con artist who robbed her mother's locket."
    run_hybrid_drama(topic, duration=args.duration, interactive=args.interactive, script_only=args.script_only, supervise=args.supervise)



if __name__ == "__main__":
    main()
