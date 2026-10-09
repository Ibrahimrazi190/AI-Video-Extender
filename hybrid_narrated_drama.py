"""
Hybrid Narrated Drama Mode — Standalone Engine
Implements HYBRID_NARRATED_DRAMA_PLAN.md:
  - First-Person POV Protagonist Voiceover (V.O.)
  - Live Spoken Dialogue Interactions (Lip-Sync)
  - Visceral Shock / Reaction Beats (Foley & Tension)
  - Scenes that play out and bridges that skip time (no fixed rhythm), with the story DELIVERED through the spoken script

Standalone execution — does NOT modify app.py or movie_scene_multispeaker.py.
Can be run via CLI or imported as a library.
"""

import argparse
import collections
import copy
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
    OpenAIOutputCut,
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
# 13 words is the most a 5-second clip carries before the voice starts DROPPING words (measured on the first clips of the Mike/Hannah
# plan: 14 words in a 3.8 s window were all spoken, 16 words in 3.7 s lost one; a faster line in a two-speaker clip, 5 words/s, is no safer).
MIN_WORDS, MAX_WORDS = 6, 13
MAX_TURN_WORDS_PER_SECOND = 3.8     # a line spoken faster than this has its window re-spaced by word count
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

# --- Supporting cast: people who are on screen for a scene or two (a parent at a family dinner, a waiter) ---------------------
# Only characters in the scene bible get a portrait, a stable face and a reference-image slot, and the clip writer may name only
# them. Anyone else on screen is painted by the video model as a stranger who changes from clip to clip. So a person who has a part
# in a shot is CAST, as a lighter "supporting" entry: the same fixed look and portrait, but no weight of story attached.
SUPPORTING_ROLE = "supporting"      # the `role` of such an entry
MAX_SUPPORTING = 4                  # in one film: more faces make a shot harder to keep consistent
SUPPORTING_MAX_LINES = 2            # spoken lines a supporting character has in the WHOLE film (often none)
CAST_GAP_CHECK = True               # the plan report asks the cheap model who is shown on screen without being cast
CAST_GAP_REASONING = "high"
CAST_GAP_MAX_OUTPUT = 16000
MAX_CAST_NAME_CHARS = 40


def _is_supporting(character: dict) -> bool:
    return (character.get("role") or "").strip().lower() == SUPPORTING_ROLE


_SUPPORTING_CAST_RULE = (
    '   - SUPPORTING CHARACTERS (CRITICAL): anyone who has a part in a shot (acts, reacts, mouths a word, is looked at, or is addressed '
    'while visible: a parent at a family dinner, a waiter who takes an order, a colleague who interrupts) MUST be in "characters". '
    'Only cast members get a portrait, so anyone else is painted by the video model as a stranger who looks different in every clip. '
    f'Give such a person a name and set their "role" to exactly "{SUPPORTING_ROLE}". A supporting character has the same fixed "appearance" '
    'and a short "voice" as everyone else, but ONE short plain phrase each for "motivation", "relationships" and "speech_style"; appears '
    f'in one stretch of the story; speaks {SUPPORTING_MAX_LINES} lines or fewer in the whole film (often none); and is listed in '
    f'present_characters of every beat they are visible in. At most {MAX_SUPPORTING} supporting characters. People who are only talked '
    'about stay off screen, and blurred passers-by who do nothing are not characters.'
)

_ON_SCREEN_RULE = (
    '   - ON-SCREEN RULE: "present_characters" lists everyone who is visible with a part in the beat, and every one of them is in the '
    'scene bible. Never write a beat that puts someone on screen who is not in the cast; if the story needs them seen, they are a '
    f'supporting character. A supporting character speaks at most {SUPPORTING_MAX_LINES} lines in the whole film.'
)
PLACE_VIEWS = (2, 3)
MIN_STEP_SECONDS = 1.0
SCRIPT_RETRIES = 2
CHAPTER_RETRIES = 3  # a clip script gets one more go than the outline: failing it halts a paid run mid-flight
CLIP_RETRIES = 2
# Ceilings on a single OpenAI reply, reasoning included, so a model stuck repeating itself costs a bounded
# amount: clip 43 of the first 5-minute run wrote the same prop entry 563 times and used 36,408 tokens. A
# normal clip is about 3k and a normal act of beats about 5k, so these are several times a real answer and
# only ever bite on a runaway. A reply that hits one is a failed attempt and is retried, never used.
CLIP_MAX_OUTPUT = 16000
PLAN_MAX_OUTPUT = 32000
SUPERVISOR_MAX_OUTPUT = 8000
MAX_ACTION_STEPS = 16  # the busiest real clip used 10; the schema only stops a list that will not end
# How many of the most recent clips in the history carry their END state (final poses, what each character
# knew, what the place was doing, the prop diary). Only the latest clip's end state is the one the next clip
# has to open on: it already includes everything the older ones said, so repeating theirs was a third of the
# prompt for nothing. The older clips still show their shot, actions and speech. 3 restores the old behaviour.
HISTORY_END_STATE_CLIPS = 1
# How many of the most recent beats the "story so far" list shows one by one. The list used to hold EVERY earlier beat, so
# it grew by ~40 tokens a clip (about 2.4k at clip 60, about 14k at clip 350, and the whole run's total grows with the
# square of the clip count) while saying nothing the clip writer needs: who knows what, where each prop is, the cast and
# the last three clips are carried by their own lists. Earlier stretches shrink to one line per finished act (taken from
# the plan) or to a count. 0 restores the full list.
STORY_SO_FAR_WINDOW = 10
STORY_SO_FAR_ACTS = 3   # how many of the most recent finished acts get a one-line summary (0 = all of them)
# Send the video model the action steps as a timeline ("0-2s: ... 2-5s: ...") instead of one untimed list.
# Every step already carries a start_time, which used to be thrown away at the last moment, so the video model
# had to guess WHEN someone walks in, turns or leaves. False restores the old untimed "Actions:" sentence.
TIMED_ACTIONS = True
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

# --- Story delivery -----------------------------------------------------------------------------------------
# The first 5-minute run planned good events and did not tell the audience the story: what the protagonist
# wanted was never said, jargon ("Rossi", "manifests", "the ports") was never explained, and the central secret
# was stated once, by the villain, at clip 34 of 43. A story is DELIVERED when a viewer who hears only the
# spoken script can retell it. These are the facts that script must carry, and where.
BEAT_FUNCTIONS = ["hook", "clash", "stakes", "decision", "reversal", "reveal", "complication", "bonding", "wound",
                  "promise", "collision", "cost", "aftermath", "escalation", "bridge", "cliffhanger", "resolution"]
FACT_KINDS = ["state_now", "plant_question", "pay_later"]
FACT_ROLES = ["want", "obstacle", "plan", "stakes", "backstory", "secret", "relationship", "ending", "setup"]
STORY_DELIVERY = True            # False: the planners are not told about delivery and no delivery check runs (the schema
                                 # fields stay, are harmless, and may come back empty)
BLIND_READ = True                # one cheap call per plan: a reader who only HEARS the script retells the story
BLIND_READ_MAX_OUTPUT = 2500
PLAN_REPAIR_BUDGET_TOKENS = 60000  # all retries and rewrites of one plan together; then what is wrong is shown, not re-asked
# By what share of the runtime the audience must know each kind of thing. Derived from one example script
# (want by clip 2-4 of 12, the lie at clip 5, the wound at clip 9); a starting point to calibrate, not a law.
NARRATION_SHARE_BAND = (0.25, 0.35)   # the protagonist's voiceover as a share of all spoken words (told to the planner, checked in the report)
DELIVERY_TIMETABLE = {"want": 0.10, "obstacle": 0.25, "plan": 0.40, "stakes": 0.75, "ending": 1.00}

# --- Limits that follow the length of the plan -----------------------------------------------------------------------
# Every number below used to be a constant tuned on a 60-clip (5-minute) story. At 300 clips they quietly became wrong:
# the prompt asked for "30 to 16" facts (the lower bound outgrew a hard cap of 16), "4 to 8 locations" and "4 acts" for
# a 25-minute story, a 60k-token repair budget was spent by the third batch of fifteen, and the reply ceiling did not
# grow with the act breakdown. Each is now a function of the clip count that returns EXACTLY the old value at 60 clips,
# so a 5-minute plan is unchanged. They are limits on how a plan may GROW, never targets to fill.
MAX_REVEALS_PER_BEAT = 8   # terms one 5-second beat can disclose for the first time; no real beat comes near it
MAX_SEQUENCES_PER_ACT = 12  # stretches (scenes and bridges) in one act; an act is at most ~20 clips, so this only stops a loop
SEQUENCE_KINDS = ("scene", "bridge")


def _fact_range(total_clips: int) -> tuple[int, int]:
    """(low, high): how many must-understand facts the delivery map holds. (6, 10) at 60 clips."""
    low = max(4, round(total_clips / 10))
    return low, max(low + 2, round(total_clips / 6))


def _default_act_count(total_clips: int) -> int:
    """About one act per 15 clips; never fewer than 4 from 60 clips up (as before), 2 below that."""
    return max(4, round(total_clips / 15)) if total_clips >= 60 else max(2, round(total_clips / 15))


def _act_range(total_clips: int) -> tuple[int, int]:
    """(low, high): how many acts the planner is told to choose between when the premise names no count. A range, not a
    number, so it can pick what the story's turns need instead of anchoring on one figure (the first plan came out
    12/12/12/12/12). (2, 4) for a 3-minute story, (3, 7) at 60 clips, (17, 33) at 300. The one-act-per-15-clips figure
    (`_default_act_count`) is now only the fallback split, used when the model returns no acts at all."""
    low = max(2, round(total_clips / 18))
    return low, max(low + 2, round(total_clips / 9))


def _location_target(total_clips: int) -> tuple[int, int]:
    """(low, high): how many distinct places a story of this length should use. (4, 8) up to 60 clips."""
    extra = max(0, total_clips - 60)
    return 4 + extra // 30, 8 + extra // 15


def _short_places(total_clips: int) -> tuple[int, int]:
    """(low, high): how many distinct places a SHORT plan (one call, no acts) should use: one for each scene, never the whole
    story in one room. (2, 3) for a minute (12 clips), (2, 4) for 90 seconds, (2, 6) just under the act-based threshold."""
    return (2 if total_clips >= 8 else 1), max(3, round(total_clips / 5))


def _repair_budget_for(total_clips: int) -> int:
    """Tokens that all retries and rewrites of one plan may spend together: 60,000 up to 60 clips, then 1,000 a clip."""
    return max(PLAN_REPAIR_BUDGET_TOKENS, 1000 * total_clips)


def _plan_ceiling(units: int, per_unit: int, base: int) -> int:
    """Reply ceiling for one planning call, reasoning included: never below PLAN_MAX_OUTPUT, and growing with what the call
    has to write (`units` clips or acts at `per_unit` tokens each, on top of `base`). A normal reply is a fraction of it,
    so only a runaway ever reaches it. 32,000 for a 12-clip batch and for the 60-clip act breakdown, as before."""
    return max(PLAN_MAX_OUTPUT, base + per_unit * units)


def _plan_caps(total_clips: int) -> dict:
    """The largest each list of the plan may be. These only stop a model stuck repeating itself (clip 43 wrote one prop 563
    times); they sit well above anything a real story of this length needs."""
    _, hi_places = _location_target(total_clips)
    _, hi_facts = _fact_range(total_clips)
    return {
        "facts": max(16, hi_facts),
        "jargon": max(10, round(total_clips / 8)),
        "characters": max(12, total_clips // 10),
        "props": max(20, total_clips // 4),
        "locations": hi_places + 4,
        "acts": max(8, total_clips // 5),
    }


def _cap_plan_schema(schema: dict, total_clips: int, beats: int | None = None, cast: int | None = None) -> dict:
    """A copy of a planning schema with every open-ended list given a ceiling for a plan of `total_clips` (`beats` is the
    exact number of beats this call writes, `cast` the size of the cast it can use). The module's own schemas are left
    alone. Strict mode accepts maxItems."""
    s, caps = copy.deepcopy(schema), _plan_caps(total_clips)
    props = s["properties"]
    if "scene_bible" in props:
        bible = props["scene_bible"]["properties"]
        bible["characters"]["maxItems"] = caps["characters"]
        bible["props"]["maxItems"] = caps["props"]
        bible["locations"]["maxItems"] = caps["locations"]
        bible["locations"]["items"]["properties"]["views"]["maxItems"] = 3
    if "delivery" in props:
        d = props["delivery"]["properties"]
        d["facts"]["maxItems"] = caps["facts"]
        d["jargon"]["maxItems"] = caps["jargon"]
    if "acts" in props:
        props["acts"]["maxItems"] = caps["acts"]
        a = props["acts"]["items"]["properties"]
        a["primary_locations"]["maxItems"] = 6
        a["reveals"]["maxItems"] = 15
        if "sequences" in a:
            a["sequences"]["maxItems"] = MAX_SEQUENCES_PER_ACT
    if "sequences" in props:   # a short plan's one list for the whole story
        props["sequences"]["maxItems"] = MAX_SEQUENCES_PER_ACT
    if "beats" in props:
        if beats:
            props["beats"]["maxItems"] = beats
        b = props["beats"]["items"]["properties"]
        b["audio_lines"]["maxItems"] = MAX_VOICE_REFS
        b["reveals"]["maxItems"] = MAX_REVEALS_PER_BEAT
        b["present_characters"]["maxItems"] = cast or caps["characters"]
    return s

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
    "Spacious and open, shot with a wide-angle lens: generous floor space and depth, room for three people to stand apart and for a camera to stand several metres back. "
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

DELIVERY_SCHEMA = {
    "type": "object",
    "description": "What the audience must understand, and where the spoken script says it. A viewer who only HEARS the film must be able to retell the story from this.",
    "properties": {
        "story_in_five": {
            "type": "array", "minItems": 5, "maxItems": 5, "items": {"type": "string"},
            "description": "Exactly five plain sentences a viewer should be able to say after watching: (1) who the protagonist is and what they want; (2) what stands in the way; (3) what they do about it; (4) what it costs or what is at stake; (5) where it stands at the end, or the open question the episode ends on."
        },
        "facts": {
            "type": "array", "maxItems": 16,
            "description": "The must-understand facts, each assigned to ONE clip and ONE speaker.",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string", "description": "f1, f2, f3 ..."},
                    "role": {"type": "string", "enum": FACT_ROLES, "description": "What this fact is for in the story."},
                    "kind": {"type": "string", "enum": FACT_KINDS, "description": "state_now: said plainly now. plant_question: the audience is told a secret EXISTS (in plain words, without naming its content) and the answer comes later. pay_later: the answer, said plainly at its planned clip."},
                    "text": {"type": "string", "description": "The fact in one plain sentence."},
                    "line": {"type": "string", "description": "A plain draft of the spoken line (about 6-15 words) in which the owner says this fact inside the clash, in their own speech style. The beat writer may improve it but must keep its meaning and key terms. For plant_question it hints that a secret EXISTS without naming it."},
                    "key_terms": {"type": "array", "minItems": 2, "maxItems": 5, "items": {"type": "string"}, "description": "The distinctive words the spoken line must contain to carry the fact (lower case, single words, e.g. 'three', 'years', 'prison'). For plant_question these must NOT include any reserved reveal term."},
                    "owner": {"type": "string", "description": "The exact character name who says it."},
                    "channel": {"type": "string", "enum": ["dialogue", "narration"]},
                    "deliver_at": {"type": "integer", "description": "The clip number where it is said."},
                    "deadline": {"type": "integer", "description": "The latest clip number by which the audience must have it."},
                    "repeat_at": {"type": "integer", "description": "A later clip number where it is said again in different words, or 0 for none."}
                },
                "required": ["id", "role", "kind", "text", "line", "key_terms", "owner", "channel", "deliver_at", "deadline", "repeat_at"],
                "additionalProperties": False
            }
        },
        "jargon": {
            "type": "array", "maxItems": 10,
            "description": "Words the audience will not know (a family name used as a code word, a legal term, a place, an institution) and the plain phrase that explains each the first time it is spoken.",
            "items": {
                "type": "object",
                "properties": {
                    "term": {"type": "string"},
                    "plain_gloss": {"type": "string", "description": "A short plain phrase, e.g. 'forged papers that said the cargo was clean'."}
                },
                "required": ["term", "plain_gloss"],
                "additionalProperties": False
            }
        }
    },
    "required": ["story_in_five", "facts", "jargon"],
    "additionalProperties": False
}

# The shape of a story, as an ordered list of stretches that together cover every clip exactly once. Every act of a long plan
# has one; a short plan (one call, no acts) has one for the whole thing.
SEQUENCES_SCHEMA = {
    "type": "array", "minItems": 1,
    "description": "The shape of the story (or of this act): an ORDERED list of stretches that together cover every clip exactly once. A scene plays one moment out in real time; a bridge skips time.",
    "items": {
        "type": "object",
        "properties": {
            "kind": {"type": "string", "enum": ["scene", "bridge"],
                     "description": "scene: a moment PLAYED OUT between people in a room, as many clips as it needs. bridge: time SKIPPED or consequences landing, 1 to 2 clips of the protagonist's narration over strong visuals, never more than 3."},
            "clip_count": {"type": "integer", "description": "How many clips this stretch takes. YOU decide. The counts add up to the length of the act (or, for a short plan, of the whole story)."},
            "location_id": {"type": "string", "description": "Where it happens: an id from scene_bible.locations. Stretches may use different places."},
            "purpose": {"type": "string", "description": "One line: what this stretch is for and what is different after it."}
        },
        "required": ["kind", "clip_count", "location_id", "purpose"],
        "additionalProperties": False
    }
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
                            "motivation": {"type": "string", "description": "What this character wants in this story and why, in one plain sentence they could say aloud ('I want to take back everything he built on my work')."},
                            "relationships": {"type": "string", "description": "Who they are to each of the other main characters, in one plain sentence ('his fixer for three years; Marco's secret handler')."},
                            "speech_style": {"type": "string", "description": "HOW they talk (clipped, teasing, formal, hesitant...) with two short sample phrases in that voice. It is the manner of speaking; it never replaces saying plainly WHAT matters."},
                            "voice": {"type": "string", "description": "The INSTRUMENT only - pitch, grain, accent: 'smoky alto with a faint Irish lilt', 'gravelled baritone', 'bright soprano with a Boston edge'. Never how it is played: no 'controlled', 'quiet', 'measured', 'calm', 'flat'. How a line is delivered changes every clip and belongs to that clip's delivery."}
                        },
                        "required": ["name", "is_protagonist", "role", "appearance", "voice", "motivation", "relationships", "speech_style"],
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
        "delivery": DELIVERY_SCHEMA,
        "sequences": SEQUENCES_SCHEMA,
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
                    },
                    "function": {
                        "type": "string",
                        "enum": BEAT_FUNCTIONS,
                        "description": "The job this beat does in the story. Adjacent beats must not keep doing the same job in the same place without a new turn."
                    },
                    "turn": {
                        "type": "string",
                        "description": "ONE sentence: what is different after this beat (a fact learned, a power shift, a new obstacle, a relationship change). A beat that changes nothing does not belong."
                    },
                    "delivers": {
                        "type": "array",
                        "maxItems": 3,
                        "items": {"type": "string"},
                        "description": "Ids (f1, f2 ...) of the must-understand facts whose key terms this beat's spoken lines say or repeat. Empty if none."
                    }
                },
                "required": [
                    "clip_number", "cycle_number", "delivery_mode", "location_id",
                    "present_characters", "speaker_or_actor", "summary", "speech_budget",
                    "audio_lines", "reveals", "function", "turn", "delivers"
                ],
                "additionalProperties": False
            }
        }
    },
    "required": ["scene_bible", "delivery", "sequences", "beats"],
    "additionalProperties": False
}

ACT_BREAKDOWN_SCHEMA = {
    "type": "object",
    "properties": {
        "scene_bible": OUTLINE_SCHEMA["properties"]["scene_bible"],
        "delivery": DELIVERY_SCHEMA,
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
                    },
                    "sequences": SEQUENCES_SCHEMA
                },
                "required": [
                    "act_number", "title", "primary_locations",
                    "dramatic_question", "start_clip", "end_clip", "summary", "reveals", "sequences"
                ],
                "additionalProperties": False
            }
        }
    },
    "required": ["scene_bible", "delivery", "acts"],
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
    # Length limits the schema itself enforces, so a runaway list is cut off by the decoder instead of being
    # paid for. Each is a bound no valid clip can exceed: the diary lists a prop at most once, blocking has one
    # entry per character, and a clip holds at most MAX_VOICE_REFS turns. Left off when the bible gives no
    # props or cast, since there is then nothing to bound by.
    prop_cap = {"maxItems": len(prop_ids)} if prop_ids else {}
    cast_cap = {"maxItems": len(character_names)} if character_names else {}
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
                            "maxItems": MAX_VOICE_REFS,
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
                            **prop_cap,
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
                            "maxItems": MAX_ACTION_STEPS,
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
                            **cast_cap,
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
# A runtime is EPISODE ONE of a longer story, not a whole film squeezed to fit. The first 5-minute run asked for
# a complete arc in 60 clips, so a ~20-minute plot was compressed: 502 spoken words in all, 41% of them
# narration, and a viewer who "didn't get a single thing" in the middle act. False restores the old prompts.
EPISODE_ONE = True


CONCLUDE_AT_SECONDS = 1800   # a plan this long (30 minutes) tells a WHOLE story and ends it; shorter ones are episode one


def _episode_one_rule(duration: int, total_clips: int, acts: bool = False, final: bool = True) -> str:
    """The shared 'play it out' rule for every planning prompt. Under CONCLUDE_AT_SECONDS the runtime is episode one and ends
    on a cliffhanger; from CONCLUDE_AT_SECONDS up it is a whole story with an earned ending. `acts` adds the line only the
    act breakdown needs: what the LAST act's fields must say. `final` is False for a batch of beats that is NOT the last one:
    the ending instruction (cliffhanger or resolution) then binds the last batch only, so a scene in the middle may still
    reach its own outcome."""
    if not EPISODE_ONE:
        return ""
    if duration >= CONCLUDE_AT_SECONDS:
        last_act = ("\n   - The LAST act resolves the central dramatic question, and its \"summary\" names what it pays off.") if acts else ""
        thread_line = ("Keep the premise's cast, world, tone, events and ending. Every open thread (a question, a secret, a promise) is paid off by the end. The ending is earned and clear: the central conflict is resolved and the audience is told how everyone stands."
                       if final else
                       "Every open thread is paid off by the end of the story, in its last batch. In this batch do not close the central conflict early; scenes inside it may reach their own outcomes.")
        return f"""
THIS RUNTIME TELLS THE WHOLE STORY (CRITICAL):
   - These {total_clips} clips ({duration}s) are long enough for a complete story with a beginning, a middle and an ending.
   - Play every turn that matters in real time, with the clips it takes: never summarise, skip or rush an event that matters. (A bridge of one or two voiceover clips may skip time between scenes; it may not replace a scene that matters.)
   - {thread_line}{last_act}"""
    last_act = ("\n   - The LAST act's \"dramatic_question\" must still be OPEN at its end, and its \"summary\" must name "
                "the cliffhanger it ends on.") if acts else ""
    ending_line = ("The episode ENDS ON A CLIFFHANGER: a reveal, a threat arriving, an arrival or a choice that is still open. Each act still answers its OWN smaller question, so the episode feels satisfying and not unfinished; only the ONE central question of the story stays open. Do NOT close that central conflict, and do not end on a resolution, a goodbye or a moral."
                   if final else
                   "The episode ends on a cliffhanger, in its LAST batch. In this batch do not close the central conflict early; each scene and each act inside it may reach its own turn and outcome.")
    return f"""
EPISODE ONE, NOT A WHOLE FILM (CRITICAL):
   - These {total_clips} clips ({duration}s) are the OPENING MOVEMENT of a longer story - one episode of a ReelShort / DramaBox series. They are NOT a complete film squeezed into {duration} seconds.
   - Tell only as much of the story as will genuinely PLAY in real time in the clips available: each turn staged between people in the room, with the clips it takes. Never summarise, skip, rush or narrate through an event that matters just to reach an ending inside the runtime. (A bridge of one or two voiceover clips may skip time between scenes; it may not replace a scene that matters.)
   - If the premise holds more events than the runtime can play properly, play the earlier ones in full and stop where the clips run out, at the strongest unresolved turn. Whatever is left belongs to the next episode.
   - WHAT THE PREMISE DECIDES AND WHAT THE RUNTIME DECIDES: keep the premise's cast, world, tone, events and their order. Its act count, and the clips it gives each act, are guides: let every act take the clips it needs. If the premise gives the story a closing (a last scene that settles everything), do NOT film that closing: this plan stops at the strongest unresolved turn before it, and the premise's closing belongs to the next episode. Use the clips to let the earlier events play out in full instead.
   - {ending_line}{last_act}"""


def _cliffhanger_final_rule(duration: int = 0) -> str:
    """Extra instruction for the batch of beats that ends the plan: a cliffhanger for an episode, a resolution for a whole story."""
    if not EPISODE_ONE:
        return ""
    if duration >= CONCLUDE_AT_SECONDS:
        return """
THESE BEATS END THE STORY (CRITICAL):
   - Resolve the central conflict and pay off every open thread, plainly and where the audience can hear it: someone says what was decided, what it cost and where everyone stands.
   - Finish on a clear final image, and let the last voiceover line answer the first one. No new threat and no cliffhanger."""
    return """
THESE BEATS END THE EPISODE (CRITICAL):
   - The last two beats leave the story OPEN: a reveal that changes everything, a threat arriving, a decision not yet made, or a door opening onto the next problem. The smaller questions of this episode are already answered; only the central one stays open. Do NOT resolve the central conflict and do NOT give anyone a closing line, farewell or moral.
   - The final beat is the cliffhanger itself - usually a wordless shock_action or one sharp line - never a summary. The viewer must want the next episode."""


_OLD_PLAIN_RULE = '   - PLAIN, SPEAKABLE WORDS (CRITICAL): everybody - the narrator included - talks like a person in a modern film. Short, common words anyone understands the first time they hear them. NO poetry, no metaphor stacking, no literary inversion, no semicolons, no archaic or ornate phrasing, no abstract nouns doing the work of a verb.\n     * BAD (do not write like this): "Three years I kept him breathing; tonight, he offered ink." / "My clearance turned green while his power learned rain." / "mercy recognizes old footsteps"\n     * GOOD (write like this): "Three years I kept him alive. Tonight he hands me a pen." / "My ship cleared while his city drowned." / "He has begged in front of me before."'


_DELIVERY_NOTES = {
    "quick_outline": " That quick-fire style is for a clash that carries no new fact: a beat that must DELIVER a fact (see STORY DELIVERY) uses one or two lines, never three.",
    "plant_outline": " The EXISTENCE of a hidden secret may be planted earlier as a plain question or hint, without any reserved term (see STORY DELIVERY); that is encouraged.",
    "quick_beats": " A beat that must DELIVER a fact (see FACTS below) uses one or two lines, never three quick-fire ones.",
    "plant_beats": "\n   - The EXISTENCE of a hidden secret may be planted earlier as a plain question or hint, without any reserved term (see FACTS below); that is encouraged.",
}


def _delivery_note(key: str) -> str:
    """Sentences in the older rules that point at the delivery section. They exist only while that section does, so no
    prompt ever refers to an instruction that is not in it."""
    return _DELIVERY_NOTES[key] if STORY_DELIVERY else ""


# --- Plain language: EVERY spoken line, not only the key facts ----------------------------------------------------
# The first run's lines were poetic and unclear ("Tonight he offers me a pen", "He waited for tears. I gave him the
# silence he feared", "You just threw away the thing holding back the dark"). The older rule asked for plain words but its
# own GOOD examples were figurative ("Tonight he hands me a pen", "My ship cleared while his city drowned"), the premise
# asked for lines "sharper than mine", and nothing checked a line. The rule now has literal examples, and a cheap review
# (`plain_pass_plan`) rewrites any line that a viewer with basic English would not understand at first hearing.
PLAIN_LANGUAGE = True   # False restores the older rule, with its own examples
PLAIN_PASS = True       # one cheap review call per PLAIN_PASS_CHUNK beats; False skips it
PLAIN_PASS_CHUNK = 15
PLAIN_PASS_MAX_OUTPUT = 3500

_PLAIN_RULE = """   - PLAIN LANGUAGE TEST (CRITICAL - EVERY spoken line, narration included): a viewer with basic English, who cannot see the picture, must understand the line the FIRST time they hear it.
     * LITERAL, never figurative: no metaphor, simile, idiom or poetic image. Say the plain thing. 'Kept him breathing', 'the dark', 'the silence he feared', 'his city drowned' and 'he offered ink' are all banned.
     * Short, common words; one or two short sentences; no abstract nouns doing a verb's work; no semicolons.
     * Say WHO and WHAT: 'he' must be clear from the line before. When a character does something that means something (returns a ring, signs, hands something over, walks out), a line says what it means: 'Take your ring back. We are done.'
     * When it matters, say what a character FEELS or WANTS in plain words.
     * If the premise gives a sample line, keep its MEANING and write it in plain words: plain beats poetic, even when the premise asks for sharper lines.
     * BAD -> GOOD: 'Tonight he hands me a pen.' -> 'Tonight he is firing me.' / 'He waited for tears. I gave him the silence he feared.' -> 'He wanted me to beg. I did not.' / 'You just threw away the thing holding back the dark.' -> 'Without me, you will lose everything.' / 'I learned quiet from his mistakes.' -> 'I stay calm because I have watched him lose control.' / 'Her smile could not outrun the ledger.' -> 'She smiles, but she knows the money is gone.'"""


def _plain_language_rule() -> str:
    return _PLAIN_RULE if PLAIN_LANGUAGE else _OLD_PLAIN_RULE


PLAIN_PASS_SCHEMA = {
    "type": "object",
    "properties": {
        "lines": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "clip_number": {"type": "integer"},
                    "line_index": {"type": "integer"},
                    "verdict": {"type": "string", "enum": ["plain", "rewrite"]},
                    "plain_line": {"type": "string", "description": "The rewritten line when the verdict is 'rewrite'; an empty string when it is 'plain'."}
                },
                "required": ["clip_number", "line_index", "verdict", "plain_line"],
                "additionalProperties": False
            }
        }
    },
    "required": ["lines"],
    "additionalProperties": False
}


def _plain_pass_prompt(chunk: list[dict], first_clip: int, prev_beat: dict | None, bible: dict,
                       delivery: dict | None) -> tuple[str, str]:
    styles = "; ".join(f"{c['name']}: {c.get('speech_style')}" for c in bible.get("characters", []) if c.get("speech_style"))
    system = (
        "You check the spoken lines of a short drama for PLAIN LANGUAGE. A line is plain when a viewer with basic English, who "
        "cannot see the picture, understands it the first time they hear it. REWRITE a line if it uses a metaphor, simile, "
        "idiom or poetic image, if it is unclear who or what it refers to, or if it hides a plain fact behind a clever phrase. "
        "ALSO rewrite the closest line when the beat shows a meaningful act (returning a ring, signing, handing something over, "
        "walking out) and no line says what it means.\n"
        "When you rewrite: keep the speaker, the meaning, the attitude (a cold character stays cold, a proud one proud) and the "
        "story information; use short, common words; add no new facts and no new names; do not make it much longer than the "
        "original. Most lines are already fine: mark those 'plain' and leave plain_line empty. Return one entry for EVERY line."
    )
    parts = []
    for n, beat in enumerate(chunk):
        clip = first_clip + n
        turns = _beat_lines(beat)
        if not turns:
            continue
        parts.append(f"Clip {clip} ({beat.get('delivery_mode')}) at {beat.get('location_id')}: {beat.get('summary')}")
        parts += [f"  line {i}: {t.get('speaker')}: \"{t.get('line')}\"" for i, t in enumerate(turns)]
        for f in (delivery or {}).get("facts") or []:
            if int(f.get("deliver_at") or 0) == clip and f.get("key_terms"):
                parts.append(f"  (this clip must still say, in its lines: {', '.join(f['key_terms'])})")
    user = "\n".join([
        f"Speech styles: {styles}" if styles else "",
        f"The line just before the first clip: {_last_line(prev_beat)}",
        "",
        *parts,
    ])
    return system, user


def _apply_plain_rewrite(beat: dict, line_index: int, new_line: str, facts_here: list[dict], reserved: set[str]) -> dict | None:
    """Put a rewritten line into a beat if it honours the beat; returns the before/after record or None."""
    turns = beat.get("audio_lines")
    if not turns or not (0 <= line_index < len(turns)):
        return None
    old = (turns[line_index].get("line") or "").strip()
    new = " ".join((new_line or "").split())
    if not new or new == old or ";" in new:
        return None
    old_words, new_words = len(_WORD.findall(old)), len(_WORD.findall(new))
    total_old = _spoken_words(turns)
    total_new = total_old - old_words + new_words
    if new_words < 2 or total_new > max(total_old, MAX_WORDS):
        return None
    before_text, after_text = _beat_text(beat), None
    after_text = before_text.replace(old, new, 1)
    for f in facts_here:   # a fact the beat said must still be said
        if _terms_covered(f.get("key_terms") or [], before_text) and not _terms_covered(f.get("key_terms") or [], after_text):
            return None
    if any(_mentions(new, term) for term in reserved):
        return None
    turns[line_index]["line"] = new
    beat["speech_budget"] = total_new
    return {"speaker": turns[line_index].get("speaker"), "before": old, "after": new}


def plain_pass_beats(beats: list[dict], bible: dict, delivery: dict | None = None, start_clip: int = 1,
                     prior_beats: list[dict] | None = None, reserved_for=None) -> dict:
    """Review EVERY spoken line for plain language and rewrite the ones that are not. One cheap call per
    PLAIN_PASS_CHUNK beats, no retries; a rewrite that does not honour its beat (speaker kept, word budget, a fact's key terms,
    reveal order) is thrown away. Never raises. Returns a log of what was changed."""
    log = {"checked": 0, "rewritten": 0, "rewrites": [], "calls": 0, "failed_calls": 0}
    if not (PLAIN_PASS and PLAIN_LANGUAGE):
        return log
    for lo in range(0, len(beats), PLAIN_PASS_CHUNK):
        chunk = beats[lo: lo + PLAIN_PASS_CHUNK]
        first_clip = start_clip + lo
        if not any(_beat_lines(b) for b in chunk):
            continue
        prev_beat = beats[lo - 1] if lo else (prior_beats[-1] if prior_beats else None)
        system, user = _plain_pass_prompt(chunk, first_clip, prev_beat, bible, delivery)
        log["calls"] += 1
        try:
            answer = _ask_openai_json(system, user, "narrated_plain_pass", PLAIN_PASS_SCHEMA,
                                      model=app.OPENAI_CLIP_MODEL, max_completion_tokens=PLAIN_PASS_MAX_OUTPUT)
        except Exception as e:  # a review must never break a plan
            log["failed_calls"] += 1
            print(f"  plain-language review failed for clips {first_clip}-{first_clip + len(chunk) - 1}: {e}", flush=True)
            continue
        log["checked"] += sum(len(_beat_lines(b)) for b in chunk)
        for entry in (answer or {}).get("lines") or []:
            if entry.get("verdict") != "rewrite":
                continue
            clip = int(entry.get("clip_number") or 0)
            if not (first_clip <= clip < first_clip + len(chunk)):
                continue
            beat = chunk[clip - first_clip]
            facts_here = [f for f in (delivery or {}).get("facts") or [] if int(f.get("deliver_at") or 0) == clip]
            reserved = set(reserved_for(clip) if reserved_for else ()) | _terms_still_secret((prior_beats or []) + beats, len(prior_beats or []) + lo + (clip - first_clip))
            done = _apply_plain_rewrite(beat, int(entry.get("line_index") or 0), entry.get("plain_line") or "", facts_here, reserved)
            if done:
                log["rewritten"] += 1
                log["rewrites"].append({"clip": clip, **done})
    return log


def plain_pass_plan(plan: dict) -> dict:
    """The plain-language review for a whole plan (changes its beats in place) and a note of what changed, kept on the plan
    as `plain_pass` for the report."""
    acts = plan.get("acts") or []

    def reserved_for(clip: int) -> set[str]:
        out: set[str] = set()
        for a in acts:
            if int(a.get("start_clip") or 0) > clip:
                out |= {(t or "").strip().lower() for t in (a.get("reveals") or []) if (t or "").strip()}
        return out

    try:
        log = plain_pass_beats(plan.get("beats") or [], plan.get("scene_bible") or {}, plan.get("delivery"), 1,
                               reserved_for=reserved_for)
    except Exception as e:  # never break a plan
        log = {"checked": 0, "rewritten": 0, "rewrites": [], "calls": 0, "failed_calls": 1, "error": str(e)}
    plan["plain_pass"] = log
    return log


def _delivery_plan_rule(duration: int, total_clips: int) -> str:
    """The planning-stage instruction: decide what the audience must understand and where it is SAID."""
    if not STORY_DELIVERY:
        return ""

    def by(share: float) -> int:
        return max(1, round(total_clips * share))

    low, high = _fact_range(total_clips)
    return f"""
STORY DELIVERY (CRITICAL): a viewer who only HEARS this film - no pictures, no premise - must be able to retell it.
   - "delivery.story_in_five": five plain sentences the viewer should be able to say afterwards: who the protagonist is and what they want; what stands in the way; what they do about it; what it costs or what is at stake; where it stands at the end, or the open question the episode ends on.
   - "delivery.facts": {low} to {high} must-understand facts. Each is said in ONE clip by ONE character, in plain words, inside a clash (demanded, refused, accused, confessed - never announced to nobody). Give each a role, a kind, "key_terms" (the distinctive words the spoken line must contain), a "line" (a plain draft of that spoken line, about 6-15 words, in the owner's own speech style), an owner, a channel (dialogue, or narration when only the protagonist's own thoughts can carry it), deliver_at, deadline, and repeat_at (the same fact again in different words much later; 0 for none).
       * kind state_now: said plainly at that clip. kind plant_question: the audience is told a secret EXISTS ("He still doesn't know what I paid to keep him free") without being told what it is; its answer is a SEPARATE pay_later fact at the clip where the story reveals it. kind pay_later: the answer, said plainly.
       * Never put a term from an act's "reveals" in a plant_question's key_terms: a reveal stays hidden until its act.
       * Deadlines for {total_clips} clips: the protagonist's WANT by clip {by(0.10)}; what stands in their way by clip {by(0.25)}; what they are doing about it by clip {by(0.40)}; the stakes restated in new words by clip {by(0.75)}; the ending state (or the open question the episode ends on) at the last clip that has spoken words, by clip {total_clips} at the latest (if the final beat is wordless, say it in the one before).
   - "delivery.jargon": every word the audience will not know (a family name used as a code word, a legal or trade term, an institution, a place) with a short plain gloss. It is explained in the same or the previous line the first time it is spoken.
   - Every character in the scene bible also has a "motivation" (what they want, in one plain sentence they could say aloud), "relationships" and a "speech_style". The protagonist's motivation must come back as a spoken line (the 'want' fact); a character's speech_style is HOW they talk, never a reason to be oblique about WHAT matters.
   - The protagonist's narration is the cheapest channel for early backstory and for the plan: a few plain words that state it, never a description of what the picture shows."""


_DELIVERY_WRITING_RULES = f"""
WRITING THE LINES SO THE STORY IS UNDERSTOOD (CRITICAL):
   1. Exposition through conflict: facts are demanded, refused, accused, confessed - never announced to nobody.
   2. The protagonist SAYS what they want and what it costs them, plainly, early.
   3. Name the stakes aloud whenever they change.
   4. The first time a listed jargon term is spoken, explain it in the same or the previous line, in plain words.
   5. A comeback must also carry information (an answer plus a new fact). A line that only sounds sharp is rewritten.
   6. One new fact per line, two at most per clip. A beat that delivers a fact uses ONE or TWO lines, never three quick-fire ones.
   7. Plant the question, delay the answer: say THAT a secret exists, never WHAT it is, before its planned clip.
   8. Say the key facts twice, in different words, far apart.
   9. Subtext comes after text: an oblique line is fine once the fact it relies on has been said.
   10. Narration states motive, fear, decision and backstory in plain words; it never describes what the picture shows.
   11. NARRATION SHARE: the protagonist's voiceover is about {int(NARRATION_SHARE_BAND[0] * 100)} to {int(NARRATION_SHARE_BAND[1] * 100)}% of all the spoken words; the rest is live dialogue. A premise that asks for a narration-led story gets the top of this range, not more. Every narration line states motive, fear, decision or backstory.
   A quiet or stoic character is a matter of HOW a line is delivered, never of what it says.
   For every beat also give "function" (the job it does in the story), "turn" (ONE sentence: what is different after it - a fact learned, a power shift, a new obstacle) and "delivers" (the ids of the facts its lines say). A beat that changes nothing does not belong."""


def _facts_block(delivery: dict | None, start_clip: int, end_clip: int) -> str:
    """The facts a batch of beats must deliver, plus what the audience already knows and what is still open."""
    if not STORY_DELIVERY or not delivery or not delivery.get("facts"):
        return ""
    facts = delivery["facts"]
    due, again, known, open_q = [], [], [], []
    for f in facts:
        at, rep = int(f.get("deliver_at") or 0), int(f.get("repeat_at") or 0)
        if start_clip <= at <= end_clip:
            due.append(f)
        elif at < start_clip and f.get("kind") != "plant_question":
            known.append(f)
        if at < start_clip and f.get("kind") == "plant_question":
            open_q.append(f)
        if start_clip <= rep <= end_clip:
            again.append(f)

    def line(f: dict, clip: int, repeat: bool) -> str:
        terms = ", ".join(f"'{t}'" for t in f.get("key_terms", []))
        how = "say it AGAIN, in different words," if repeat else "must say, plainly,"
        draft = f" Draft line you may use or improve (keep its meaning and key terms): \"{f.get('line')}\"" if f.get("line") else ""
        return (f"- {f.get('id')} [{f.get('kind')}, {f.get('role')}] clip {clip}: {f.get('owner')} ({f.get('channel')}) {how} "
                f"in a line that contains {terms}: \"{f.get('text')}\".{draft}")

    out = ["FACTS THIS BATCH MUST DELIVER (the beat at each clip below must be a voiceover or dialogue beat, never a wordless one; its audio_lines must say each fact and its \"delivers\" must list its id):"]
    out += [line(f, int(f["deliver_at"]), False) for f in due]
    out += [line(f, int(f["repeat_at"]), True) for f in again]
    if not due and not again:
        out.append("- none in this batch; keep the story moving and do not re-explain what the audience already knows.")
    else:
        out.append("BEFORE YOU ANSWER, check each fact above: the beat at its clip has a spoken line, by its owner, that contains its "
                   "key terms, and that beat has only one or two lines so there is room to say it plainly.")
    if known:
        out.append("THE AUDIENCE ALREADY KNOWS: " + " | ".join(str(f.get("text")) for f in known[-8:]))
    if open_q:
        out.append("QUESTIONS THE AUDIENCE HAS BEEN GIVEN (still open; do not answer them early): "
                   + " | ".join(str(f.get("text")) for f in open_q))
    jargon = delivery.get("jargon") or []
    if jargon:
        out.append("JARGON TO EXPLAIN ON FIRST USE: " + "; ".join(f"'{j.get('term')}' = {j.get('plain_gloss')}" for j in jargon))
    return "\n".join(out)


def _narrated_outline_prompt(topic: str, duration: int, total_clips: int) -> tuple[str, str]:
    """Builds the single-call Master Plan prompt (short videos): scenes play, bridges skip, a place is kept, and the
    story is DELIVERED in the spoken script."""
    places_lo, places_hi = _short_places(total_clips)
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
   - THE SHAPE COMES FIRST (CRITICAL): before the beats, write "sequences": an ORDERED list of stretches that together cover all {total_clips} clips exactly once. Each has a "kind" ("scene" or "bridge"), a "clip_count" (YOU decide: a scene takes as many clips as the moment needs, a bridge takes 1 or 2 and never more than {MAX_BRIDGE_CLIPS}; the counts add up to {total_clips}), a "location_id" (an id from scene_bible.locations; different stretches may be in different places) and a one-line "purpose" (what it is for and what is different after it). Then write the beats so that every beat follows its stretch: the stretch's place, and live dialogue for a scene, narration over strong visuals for a bridge.
   - EVERY EVENT PLAYS (CRITICAL): each event of the story must have a scene of its own (or be the turn a bridge lands on). An event that has no stretch to play it will be squeezed into one line of narration, and then the story is REPORTED instead of SHOWN. If the premise holds more events than {total_clips} clips can play, play the earlier ones in full and leave the rest.

3. LOCATION CONTINUITY & CONFINEMENT (CRITICAL):
   - Confinement within a scene, progression between scenes.
   - A scene must anchor in 1 to 2 core locations (e.g. the main reception desk, the office) across consecutive beats. Do NOT jump between random unestablished rooms or hallways every 5 seconds.
   - A story this short ({total_clips} clips) uses {places_lo} to {places_hi} distinct places: a place for each scene, not the whole story in one room. The story MOVES when its scene changes.
   - Every single beat's location_id MUST match one of the exact ids defined in scene_bible.locations.
   - A room is ONE location however many angles it is filmed from: never make separate locations for different angles of the same room. Places in the same building must match each other in architecture, era and materials.
   - SPACE FOR THE CAMERA (CRITICAL): every place must be roomy enough for three people to stand and walk and for a camera to stand several metres back, because the shots need real angles (over the shoulder, wide, tracking). Describe a corridor as a wide landing or hall (about 3 to 4 metres across, 8 or more metres long, doors well apart), a room as a large room, a staircase as a broad one. Never write narrow, cramped, tiny, tight or claustrophobic about a place; if the premise names a small place, keep it but give it room.
   - "description": its fixed look in one or two sentences (architecture, furniture, materials, colours, light), true for the WHOLE story.
   - "layout": a fixed map every clip set there follows - each door, window, staircase and the main furniture, placed relative to the main entrance, stating how many of each there are ('the only door', 'two lifts'), and including every feature the story uses there (a counter someone hides behind, a lift, a back corridor).
   - "views": 2 or 3 camera VIEWPOINTS for the reference pictures, ALL showing the place EMPTY - 'from the entrance looking at the desk', 'from behind the desk looking out'. Where two people will talk, make two of the views LOOK OPPOSITE WAYS along the line between them, so a reverse angle has a picture to match. A viewpoint is a place to stand, NOT a shot from the story: never 'Clara POV', never an insert of a story object.
   - "image_prompt": a text-to-image prompt for a wide view from the FIRST viewpoint, naming every permanent feature the story uses there (the video model can only use what the picture shows). It must contain NO PEOPLE and NONE of the story's props or payoffs: a reference plate showing a character standing in the doorway puts them in every clip filmed there, and one showing the story's final reveal shows it from the very first clip. The system adds the photorealism and empty-room wording for you.

4. CASTING THE SCREEN (CRITICAL):
   - CASTING RULE: unless the premise asks for a specific ethnicity, default the cast to Western, European or British demographics.
   - STATIC BIBLE RULE: "appearance" and "voice" hold ONLY permanent, unchanging physical facts ('tall and lean', 'jet black hair', 'smoky alto with a faint Irish lilt'). NEVER put a mood, an emotion or a story event there ('anxious', 'determined', 'starts hopeful') - those belong to a clip's delivery and action.
   - "voice" IS THE INSTRUMENT, NOT THE PERFORMANCE (CRITICAL): give its pitch, grain and accent only. NEVER 'controlled', 'quiet', 'measured', 'calm', 'flat' or 'restrained' - those describe how someone is speaking in one moment, and written here they make EVERY line in the film inherit them. A character whose voice is 'low, controlled alto' will never be allowed to shout.
   - VISUAL SEPARATION RULE: each character's reference portrait is generated automatically from "appearance", and these clips are watched on a phone in dark, dim rooms. Every character MUST be identifiable at a glance:
     * No two MAIN characters may share a hair colour. If the story dresses them in the same uniform, their hair colour AND hair style must BOTH differ. A supporting character must differ from every other character in hair colour OR hair style.
     * Every character needs a real "distinguishing_feature" - something visible on the face or head. Never 'none'.
{_SUPPORTING_CAST_RULE}
   - Fill every "appearance" field precisely. It is the only description of that character the camera will ever get.
   - PROPS: list in "props" every object a character carries, picks up, sets down, uses, changes or breaks in the story (a laundry cart, a silver case, a phone receiver, a knife), each with a snake_case "id" and a full fixed "description" of how it looks. NOT furniture that simply stands in the room, and NOT what characters wear - clothes, glasses and jewellery belong to "appearance". One prop is one object, never 'their bags'. An empty list if the story has none.

5. THE SPOKEN WORD IS DECIDED HERE (CRITICAL):
   - You are the ONLY writer who sees the whole story, so YOU write every line, in "audio_lines": the exact words the audience hears in that clip, in order. The clip director downstream writes only what is SEEN, and will be forced to speak your lines verbatim.
   - A DIALOGUE beat may hold ONE, TWO or THREE lines, by up to {MAX_VOICE_REFS} different speakers. Use more than one whenever the exchange is quick - a jab and its retort belong in the SAME clip, not split across a cut. Use one line when it is meant to hang.
   - A VOICEOVER beat holds exactly ONE line, by the pov_protagonist. A shock_action beat holds an EMPTY array.
   - VOICE SAMPLES: the FIRST line a character speaks in the whole video is cut out of that clip and reused as their voice everywhere after, so make it a clear, fully voiced line of at least {VOICE_SAMPLE_MIN_WORDS} words - never their short one- or two-word reply. Introduce a character's voice on a beat where they carry the line, then let them trade quick fire afterwards.
   - The clip is only {CLIP_SECONDS} seconds long, so "speech_budget" - the TOTAL words across every line in the beat - must be {MIN_WORDS} to {MAX_WORDS}. Three speakers in one clip means roughly four words each: "Where is she?" / "Gone." / "You are lying." Short, hard lines land; long ones get cut off.{_delivery_note("quick_outline")}
{_plain_language_rule()}
   - The narration is her thinking, not her writing. It says what the picture cannot - what she wants, what it costs her, what she has decided, what she is hiding from the others - in the plainest words that will carry it. It states; it never describes what the picture already shows.
   - REVEAL ORDER (CRITICAL): a line may only use facts the audience already knows. List in "reveals" the key terms each beat discloses for the FIRST time - names, places, room numbers, objects. NEVER let an earlier beat's lines speak a term that a later beat reveals: the protagonist cannot name Room 404 in clip 2 if a co-worker reveals it in clip 3.{_delivery_note("plant_outline")}

6. ABSOLUTE RULES:
   - NEVER have more than 3 consecutive voiceover clips, and 2 is the working length: past that the viewer is listening to someone think instead of watching something happen.
   - Consecutive dialogue clips are NOT capped. A scene takes the clips it takes; never break one up just to insert narration.
   - For shock_action clips, speech_budget must be 0 and audio_lines must be an empty array.
   - For voiceover and dialogue clips, speech_budget must be {MIN_WORDS} to {MAX_WORDS} words.
{_ON_SCREEN_RULE}
   - This is a FIRST-PERSON story, so when a shock_action beat has ANY people in it, the camera stays with the pov_protagonist: they must be among its present_characters and be its speaker_or_actor. Everyone else present may still react in the clip - they simply are not who the shot is about. A shock_action beat with NOBODY on screen (an establishing or atmospheric shot) has empty present_characters and an empty speaker_or_actor.
{_episode_one_rule(duration, total_clips)}
{_cliffhanger_final_rule(duration)}
{_delivery_plan_rule(duration, total_clips)}
{_DELIVERY_WRITING_RULES if STORY_DELIVERY else ""}
"""
    user_prompt = (f"Story Premise:\n{topic}\n\nGenerate the Master Plan for these {total_clips} clips ({duration}s total)"
                   + (" - episode one, ending on a cliffhanger." if EPISODE_ONE and duration < CONCLUDE_AT_SECONDS else "."))
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
        n = _default_act_count(total_clips)
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
        if span > BATCH_MAX_CLIPS:
            num_splits = math.ceil(span / BATCH_MAX_CLIPS)
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
        if batches and (batches[-1]["clip_count"] < BATCH_MIN_CLIPS or c["clip_count"] < BATCH_MIN_CLIPS):
            if batches[-1]["clip_count"] + c["clip_count"] <= BATCH_MAX_CLIPS:
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


# --- Sequences: the shape of an act, decided in the plan and then checked ---------------------------------------------------
# "A scene plays, a bridge skips time" used to be prose in the prompts. Nothing recorded which stretch was which, so nothing
# could check it, and a model's default is uniform blocks (the first plan came out 12/12/12/12/12, one room each, with a
# montage inflated into twelve clips). Each act now lists its sequences: scene or bridge, how many clips, where, and what it
# is for. The planner decides all of it; code only checks that the lengths add up, the places exist and a bridge stays short.
MAX_BRIDGE_CLIPS = MAX_CONSECUTIVE_VO


def _single_acts(data: dict, total_clips: int) -> list[dict]:
    """A short plan has no acts, but its sequences cover the whole story exactly as an act's cover the act. Wrapping them in one
    act that spans every clip lets the layout, repair, check, report notes and dashboard work for it unchanged. The list of
    sequences is shared, not copied, so a repair made through this wrapper is a repair of the plan."""
    return [{"act_number": 1, "title": "The episode", "primary_locations": [], "dramatic_question": "", "start_clip": 1,
             "end_clip": total_clips, "summary": "The whole story.", "reveals": [],
             "sequences": data.get("sequences") if isinstance(data.get("sequences"), list) else []}]


def _fold_sequences_into_acts(data: dict, total_clips: int) -> None:
    """The finished short plan keeps its shape the way a long plan does, in `acts`, which is what the job, the plan file, the
    report and the dashboard read. (While the plan is being written it stays a top-level `sequences`, the shape of the schema.)"""
    if "sequences" in data:
        data["acts"] = _single_acts(data, total_clips)
        data.pop("sequences", None)


def _sequence_layout(acts: list[dict] | None, total_clips: int | None = None) -> list[dict]:
    """Every sequence of every act with the absolute clips it covers:
    [{"act_number", "kind", "location_id", "purpose", "start", "end"}], in story order. `total_clips` first settles the
    act spans (raw model output); acts that are already normalised need not pass it. Acts without sequences give nothing."""
    spans = _normalize_act_spans(acts, total_clips) if (acts and total_clips) else (acts or [])
    rows: list[dict] = []
    for a in spans:
        try:
            cursor, act_end = int(a.get("start_clip") or 0), int(a.get("end_clip") or 0)
        except (TypeError, ValueError):
            continue
        for s in a.get("sequences") or []:
            try:
                n = int(s.get("clip_count"))
            except (TypeError, ValueError):
                continue
            if n < 1 or cursor < 1 or cursor > act_end:
                continue
            end = min(cursor + n - 1, act_end)
            rows.append({"act_number": a.get("act_number"), "kind": s.get("kind"), "location_id": s.get("location_id"),
                         "purpose": (s.get("purpose") or "").strip(), "start": cursor, "end": end})
            cursor = end + 1
    return rows


def _repair_sequences(acts: list[dict] | None, total_clips: int, bible: dict | None = None) -> list[str]:
    """Settle what the code can settle about each act's sequences before they are validated (a retry is an OpenAI call).
    A missing list becomes one scene; a small miscount (the lengths add up to a few clips more or fewer than the act) is
    taken up by the longest scene, which is the stretch that can best spare or use a clip. A bigger miscount is left for the
    check to report, because that is the planner not knowing what its own act contains. Edits `acts` in place; returns notes."""
    notes: list[str] = []
    if not acts:
        return notes
    spans = _normalize_act_spans(acts, total_clips)
    places = [l.get("id") for l in (bible or {}).get("locations", []) if l.get("id")]
    for a, span in zip(acts, spans):
        n = span["end_clip"] - span["start_clip"] + 1
        num = a.get("act_number", "?")
        seqs = a.get("sequences")
        if not isinstance(seqs, list) or not seqs:
            where = next((p for p in (a.get("primary_locations") or []) if p in places), None) or (places[0] if places else "")
            a["sequences"] = [{"kind": "scene", "clip_count": n, "location_id": where,
                               "purpose": ((a.get("summary") or a.get("title") or "")[:200])}]
            notes.append(f"act {num}: no sequences were given, so the whole act is one scene")
            continue
        for s in seqs:
            kind = str(s.get("kind") or "").strip().lower()
            s["kind"] = kind if kind in SEQUENCE_KINDS else ("bridge" if "bridge" in kind else "scene")
            try:
                s["clip_count"] = int(s.get("clip_count"))
            except (TypeError, ValueError):
                pass
        if not all(isinstance(s.get("clip_count"), int) and s["clip_count"] >= 1 for s in seqs):
            continue   # the check reports it
        diff = n - sum(s["clip_count"] for s in seqs)
        if diff and abs(diff) <= max(3, n // 4):
            scenes = [s for s in seqs if s["kind"] == "scene"]
            target = max(scenes, key=lambda s: s["clip_count"]) if scenes else seqs[-1]
            new = target["clip_count"] + diff
            if new >= 1 and (target["kind"] == "scene" or new <= MAX_BRIDGE_CLIPS):
                target["clip_count"] = new
                notes.append(f"act {num}: its sequences added up to {n - diff} clips but the act has {n}; the {target['kind']} "
                             f"in '{target.get('location_id')}' now takes {new}")
    return notes


def _sanitize_sequence_places(acts: list[dict] | None, bible: dict) -> list[str]:
    """Last resort once the retries are spent: a sequence set in a place the bible does not have gets the act's own first
    listed place (or the first place of the bible), so the beat writer is never told to film somewhere that does not exist."""
    notes: list[str] = []
    places = [l.get("id") for l in bible.get("locations", []) if l.get("id")]
    for a in acts or []:
        for s in a.get("sequences") or []:
            if places and s.get("location_id") not in places:
                new = next((p for p in (a.get("primary_locations") or []) if p in places), places[0])
                notes.append(f"act {a.get('act_number', '?')}: a sequence was set in '{s.get('location_id')}', which is not in the bible; it now uses '{new}'")
                s["location_id"] = new
    return notes


def _check_sequences(acts: list[dict], bible: dict, total_clips: int) -> list[str]:
    """Hard: a clip count that is not a whole number of at least 1, a place the bible does not have, a bridge longer than
    MAX_BRIDGE_CLIPS, lengths that do not add up to the act. Soft: an act made of one kind of stretch or one place, and acts
    that are all the same length (the 12/12/12/12/12 symptom)."""
    problems: list[str] = []
    places = {l["id"] for l in bible.get("locations", [])}
    lengths: list[int] = []
    for a, span in zip(acts, _normalize_act_spans(acts, total_clips)):
        n = span["end_clip"] - span["start_clip"] + 1
        lengths.append(n)
        num = a.get("act_number", "?")
        seqs = a.get("sequences") or []
        if not seqs:
            problems.append(f"[SOFT] Act {num} lists no sequences, so nothing says which of its {n} clips are scenes and which are bridges.")
            continue
        sound = True
        for i, s in enumerate(seqs, 1):
            cc = s.get("clip_count")
            if not isinstance(cc, int) or isinstance(cc, bool) or cc < 1:
                problems.append(f"Act {num} sequence {i}: clip_count must be a whole number of at least 1, not {cc!r}.")
                sound = False
                continue
            if s.get("kind") not in SEQUENCE_KINDS:
                problems.append(f"Act {num} sequence {i}: kind must be 'scene' or 'bridge', not {s.get('kind')!r}.")
            if s.get("location_id") not in places:
                problems.append(f"Act {num} sequence {i}: location '{s.get('location_id')}' is not in scene_bible locations ({sorted(places)}).")
            if s.get("kind") == "bridge" and cc > MAX_BRIDGE_CLIPS:
                problems.append(f"Act {num} sequence {i}: a bridge skips time in 1 to {MAX_BRIDGE_CLIPS} clips, not {cc}. "
                                f"Make it a scene that plays out, or shorten it.")
        total = sum(s["clip_count"] for s in seqs if isinstance(s.get("clip_count"), int))
        if sound and total != n:
            problems.append(f"Act {num}: its sequences add up to {total} clips but the act has {n} (clips {span['start_clip']}-{span['end_clip']}). "
                            f"Give every clip of the act to exactly one sequence.")
        if n >= BATCH_MIN_CLIPS and len(seqs) >= 2:   # one long scene in one room is a legitimate act; only a split act can be uniform
            if len({s.get("kind") for s in seqs}) == 1:
                problems.append(f"[SOFT] Act {num} is {n} clips of nothing but {seqs[0].get('kind')}s. A drama alternates: scenes that play out and bridges that skip time.")
            if len({s.get("location_id") for s in seqs}) == 1:
                problems.append(f"[SOFT] Act {num} stays in '{seqs[0].get('location_id')}' for all {n} clips; unless one long scene is the point, let it move.")
    if len(lengths) >= 3 and len(set(lengths)) == 1:
        problems.append(f"[SOFT] Every act is {lengths[0]} clips long. Acts are sized by what they have to do, so identical lengths usually mean the story was cut into equal pieces.")
    return problems


def _structure_block(all_acts: list[dict] | None, start_clip: int, end_clip: int) -> tuple[str, list[str]]:
    """What the beat writer is told about the stretches that fall in its batch: (text, the places those stretches use).
    ("", []) for acts that have no sequences (a continuation, or a plan from before sequences)."""
    rows = [r for r in _sequence_layout(all_acts) if r["end"] >= start_clip and r["start"] <= end_clip]
    if not rows:
        return "", []
    lines, places = [], []
    for r in rows:
        where = f"Clips {r['start']}-{r['end']}" if r["end"] > r["start"] else f"Clip {r['start']}"
        part = "" if (r["start"] >= start_clip and r["end"] <= end_clip) else \
            f" (this batch writes clips {max(r['start'], start_clip)}-{min(r['end'], end_clip)} of it)"
        if r["kind"] == "bridge":
            how = ("Skip time: the protagonist's narration (voiceover beats) over strong visuals, then land somewhere new with "
                   "everything changed. Do not stage a scene here.")
        else:
            how = ("Play it out in real time between the people in the room, beat by beat. Do not cut away to narration, do not "
                   "summarise it, and do not wrap it up early: it has these clips.")
        lines.append(f"- {where}{part}: a {str(r['kind']).upper()} in '{r['location_id']}'. Purpose: {r['purpose'] or '-'}. {how}")
        if r["location_id"] and r["location_id"] not in places:
            places.append(r["location_id"])
    return ("STRUCTURE OF THESE CLIPS (decided in the plan; follow it - every beat's location_id is the place named for its stretch):\n"
            + "\n".join(lines)), places


def _sequence_beat_notes(beats: list[dict] | None, acts: list[dict] | None) -> list[str]:
    """Soft notes where the finished beats do not follow the planned stretches: a scene filmed in another place or told
    mostly by narration, a bridge that stages live dialogue. One note per stretch, so the review stays readable."""
    notes: list[str] = []
    for r in _sequence_layout(acts):
        clips = [(n, beats[n - 1]) for n in range(r["start"], min(r["end"], len(beats or [])) + 1)]
        if not clips:
            continue
        span = f"Clips {r['start']}-{r['end']}"
        wrong_place = [n for n, b in clips if r["location_id"] and b.get("location_id") != r["location_id"]]
        if wrong_place:
            notes.append(f"[SOFT] {span} are planned as a {r['kind']} in '{r['location_id']}', but clip(s) {', '.join(map(str, wrong_place[:5]))} "
                         f"{'are' if len(wrong_place) > 1 else 'is'} set elsewhere.")
        if r["kind"] == "bridge":
            talk = [n for n, b in clips if b.get("delivery_mode") == "dialogue"]
            if talk:
                notes.append(f"[SOFT] {span} are planned as a bridge (time skipped), but clip(s) {', '.join(map(str, talk[:5]))} stage live dialogue.")
        elif len(clips) >= 3:
            told = [n for n, b in clips if b.get("delivery_mode") == "voiceover"]
            if len(told) * 2 > len(clips):
                notes.append(f"[SOFT] {span} are planned as a scene that plays out, but {len(told)} of its {len(clips)} clips are narration.")
    return notes


def _narrated_act_breakdown_prompt(topic: str, duration: int, total_clips: int,
                                   act_count: int | None = None) -> tuple[str, str]:
    """Builds prompt for Act Breakdown Call 1: Scene Bible + Acts Structure."""
    acts_lo, acts_hi = _act_range(total_clips)
    places_lo, places_hi = _location_target(total_clips)
    act_instruction = (
        f"Divide the {duration}s story ({total_clips} clips) into exactly {act_count} narrative acts as requested in the premise."
        if act_count else
        f"Divide the {duration}s story ({total_clips} clips) into {acts_lo} to {acts_hi} narrative acts: as many as the story needs to turn, and no more. "
        f"Each act ends on a real turn. Size each one by what it has to do, NOT by dividing {total_clips} evenly - unequal acts are expected and correct."
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
     * No two MAIN characters may share a hair colour. If the story dresses them in the same uniform, their hair colour AND hair style must BOTH differ. A supporting character must differ from every other character in hair colour OR hair style.
     * Every character needs a real "distinguishing_feature" - something visible on the face or head. Never 'none'.
{_SUPPORTING_CAST_RULE}
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
   - The story MUST progress to new locations between acts! For a {total_clips}-clip production ({duration}s), establish {places_lo} to {places_hi} distinct locations total across the entire story (e.g. Grand Lobby, Executive Office, Archives, Private Sedan, Rooftop Terrace).
   - SPACE FOR THE CAMERA (CRITICAL): every place must be roomy enough for three people to stand and walk and for a camera to stand several metres back, because the shots need real angles (over the shoulder, wide, tracking). Describe a corridor as a wide landing or hall (about 3 to 4 metres across, 8 or more metres long, doors well apart), a room as a large room, a staircase as a broad one. Never write narrow, cramped, tiny, tight or claustrophobic about a place; if the premise names a small place, keep it but give it room.
   - "description": fixed look in 1-2 sentences true for the whole story.
   - "layout": fixed map relative to the entrance, doors, windows, key features.
   - "views": 2 or 3 camera VIEWPOINTS showing the place EMPTY. Where two people will talk, make two of the views LOOK OPPOSITE WAYS along the line between them, so a reverse angle has a picture to match.
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
     * "end_clip": integer end clip (the LAST act ends at {total_clips})
     * "summary": concise summary of narrative progression, major clash, and ending revelation or cliffhanger.
     * "reveals": the key terms the audience learns for the FIRST time in this act - names, places, room numbers, objects.
     * "sequences": the SHAPE of the act, an ORDERED list of stretches that together cover every clip of the act exactly once. Each has:
         - "kind": "scene" or "bridge" (as defined above).
         - "clip_count": how many clips it takes. YOU decide: a scene takes as many as the moment needs, a bridge takes 1 or 2 and never more than {MAX_BRIDGE_CLIPS}. The counts of one act's sequences must add up to that act's length (end_clip - start_clip + 1).
         - "location_id": where it happens, an id from scene_bible.locations. The sequences of one act may use different places.
         - "purpose": one line: what this stretch is for and what is different after it.
   - Act spans must cover clips 1 to {total_clips} continuously without gaps.
   - EVERY EVENT PLAYS (CRITICAL): each event that an act's "summary" names must have a scene of its own (or be the turn a bridge lands on). An event that is only mentioned in the summary, with no sequence to play it, will be squeezed into one line of narration: that is how a story ends up REPORTED instead of SHOWN. If an act holds more events than clips, move the surplus to the next act (or, in an episode, leave it for the next one) rather than packing it in.

6. WHO LEARNS WHAT, AND WHEN (CRITICAL):
   - Each act's beats are written in a separate later pass that cannot see the acts after it. The "reveals" lists are how that pass knows what it is not allowed to say yet, so they have to be right here.
   - A term belongs to exactly ONE act: the act that first discloses it. Never repeat a term in a later act's "reveals".
   - Nothing may be spoken before the act that reveals it. If Act 3 is where a character learns the room number, no line in Acts 1 or 2 may say that number - not even the narrator's.
{_episode_one_rule(duration, total_clips, acts=True)}
{_delivery_plan_rule(duration, total_clips)}
"""
    user_prompt = (f"Story Premise:\n{topic}\n\nGenerate the Scene Bible and Act Breakdown for these {total_clips} clips ({duration}s total)"
                   + (" - episode one, ending on a cliffhanger." if EPISODE_ONE and duration < CONCLUDE_AT_SECONDS else "."))
    return system_prompt, user_prompt


def _narrated_act_beats_prompt(topic: str, batch: dict, all_acts: list[dict], bible: dict,
                               prior_beats: list[dict], total_clips: int,
                               delivery: dict | None = None) -> tuple[str, str]:
    """Builds prompt for Act Beats Call 2..N: writing beats for one act/batch. `delivery` (the plan's must-understand
    facts) tells this batch which facts its spoken lines have to carry."""
    start_clip = batch["start_clip"]
    end_clip = batch["end_clip"]
    clip_count = batch["clip_count"]
    facts_block = _facts_block(delivery, start_clip, end_clip)
    # Only the batch that holds the last clip of the episode is told to end on a cliffhanger; a continuation is
    # one too, since it is the last batch of what exists so far.
    final_rule = _cliffhanger_final_rule(total_clips * CLIP_SECONDS) if end_clip >= total_clips else ""

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
   - A DIALOGUE beat holds 1 to {MAX_VOICE_REFS} lines between characters in scene_bible.{_delivery_note("quick_beats")}
   - A VOICEOVER beat holds exactly ONE line by '{bible.get("pov_protagonist")}'.
   - A SHOCK_ACTION beat has audio_lines = [] and speech_budget = 0.
   - For dialogue/voiceover, "speech_budget" is the total words across all lines in that beat: {MIN_WORDS} to {MAX_WORDS} words.
   - VOICE SAMPLES: The first line a character ever speaks in the whole series must be at least {VOICE_SAMPLE_MIN_WORDS} words.
{_plain_language_rule()}
   - The narration is the protagonist THINKING, not writing. It says what the picture cannot - what she wants, what it cost, what she has decided, what she is hiding from the others - in the plainest words that carry it. It states; it never describes what the picture already shows.

5. REVEAL ORDER & SECRET LEDGER (CRITICAL):
   - A line may only mention facts the audience already knows.
   - List in "reveals" any new terms disclosed for the FIRST time in that beat.
   - NEVER mention a secret fact/term before the clip that reveals it!{_delivery_note("plant_beats")}

6. ABSOLUTE RULES:
   - NEVER have more than 3 consecutive voiceover clips, and 2 is the working length: past that the viewer is listening to someone think instead of watching something happen.
   - Consecutive dialogue clips are NOT capped. A scene takes the clips it takes; never break one up just to insert narration.
{_ON_SCREEN_RULE}
   - Output clip_number starting at {start_clip} and ending at {end_clip}. Exactly {clip_count} beats.
{_episode_one_rule(total_clips * CLIP_SECONDS, total_clips, final=end_clip >= total_clips)}
{final_rule}
{_DELIVERY_WRITING_RULES if STORY_DELIVERY else ""}
"""

    bible_summary = {
        "pov_protagonist": bible.get("pov_protagonist"),
        "characters": [
            {"name": c["name"], "role": c["role"], "voice": c.get("voice", ""),
             **{k: c[k] for k in ("motivation", "relationships", "speech_style") if c.get(k)}}
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

    structure_text, structure_places = _structure_block(all_acts, start_clip, end_clip)
    shown_places = list(batch.get("primary_locations") or []) + [p for p in structure_places if p not in (batch.get("primary_locations") or [])]

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
Primary Locations: {shown_places}
Dramatic Question: {batch.get('dramatic_question')}
Act Goal / Summary: {batch.get('summary')}
{structure_text}

{facts_block}

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


# A plan that breaks a rule used to be thrown away whole, and with it every planning call that had been paid for (about
# $1-2 on the story model). But the plan already stops at plan_ready for a person to read before anything is rendered, and
# most of its hard rules are about how the film LOOKS or SOUNDS, which that person can judge better than a regex. These
# are the ones that can go to the review gate. Everything else stays blocking, because the clip stage re-checks it and
# would stop the job in the middle of a paid run: a location or speaker that is not in the bible, a voiceover with two
# lines, a dialogue beat with four, a wordless beat that has words, a line that leaks a reveal, a beat with no words,
# a wrong number of beats.
_REVIEWABLE_PLAN_PROBLEMS = (
    "voiceover clips in a row",                                  # rhythm
    "a wordless beat with people in it must include the POV",    # whose reaction the shot is about
    "the reaction belongs to",
    "this is an establishing shot with nobody on screen",
    "hair colour",                                               # two characters who look alike on a dim phone screen
    "which is a mood, not a permanent physical fact",            # appearance wording
    "is empty; every character needs a concrete, permanent",
    "which is how a line is PERFORMED",                          # voice wording
    "its image_prompt describes a person",                       # location picture wording
    "its image_prompt names the character",
    "give 2 or 3 viewpoints",
    "A viewpoint is a place to stand",
    " sequence ",                                                # the planned shape of an act or story (beats are what render)
    "its sequences add up to",
    "a bridge skips time in",
    "before the voice starts dropping words",                   # a line over the word limit: fix it in Revise plan
)


def split_plan_problems(hard: list[str]) -> tuple[list[str], list[str]]:
    """(blocking, reviewable): the hard problems that must stop a plan, and the ones to show at the review gate instead."""
    blocking, reviewable = [], []
    for p in hard or []:
        (reviewable if any(frag in p for frag in _REVIEWABLE_PLAN_PROBLEMS) else blocking).append(p)
    return blocking, reviewable


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


# ---------------------------------------------------------------------------
# Story delivery: checks (no model, no cost), the blind reader and the plan report
# ---------------------------------------------------------------------------
_STOP = frozenset(
    "a an the and or but of to in on at for with from by is are was were be been it its this that these those "
    "i you he she we they my your his her our their me him them as so if not no do does did".split()
)


def _stem(word: str) -> str:
    w = word.lower().strip("'’")
    for suffix in ("ing", "ed", "es", "s"):
        if w.endswith(suffix) and len(w) - len(suffix) >= 3:
            return w[: -len(suffix)]
    return w


def _stems(text: str) -> set[str]:
    return {_stem(w) for w in _WORD.findall(text or "") if w.lower() not in _STOP}


def _terms_covered(terms: list[str], text: str, share: float = 0.5) -> bool:
    """Does `text` say enough of a fact's distinctive words (at least `share` of them, never fewer than one)?"""
    wanted = {s for t in terms or [] for s in _stems(str(t))}
    if not wanted:
        return True
    return len(wanted & _stems(text)) >= max(1, math.ceil(len(wanted) * share))


def _beat_text(beat: dict) -> str:
    return " ".join((t.get("line") or "") for t in _beat_lines(beat))


def _soften(problems: list[str]) -> list[str]:
    return [p if p.startswith("[SOFT] ") else "[SOFT] " + p for p in problems]


def _is_delivery_problem(problem: str) -> bool:
    p = problem.removeprefix("[SOFT] ")
    return p.startswith(("delivery.", "fact ")) or "the plan says this clip must state fact" in p


def _soften_delivery(problems: list[str]) -> list[str]:
    """Once the retries (or the repair budget) are spent, a delivery problem that is still there is REPORTED to the
    user at the plan gate; it must not turn a finished plan into a rejected one. Structural problems stay hard."""
    return [("[SOFT] " + p if _is_delivery_problem(p) and not p.startswith("[SOFT] ") else p) for p in problems]


class _RepairBudget:
    """The tokens that every retry and rewrite of ONE plan may spend together. When it is used up the planner stops
    asking and the remaining problems are shown instead, so a plan can never loop on its own flags."""

    def __init__(self, limit: int | None = None):
        self.limit = PLAN_REPAIR_BUDGET_TOKENS if limit is None else limit
        self.spent = 0

    @property
    def exhausted(self) -> bool:
        return self.spent >= self.limit

    def charge_last_call(self) -> None:
        log = getattr(app, "USAGE_LOG", None) or []
        if log:
            self.spent += int(log[-1].get("input", 0) or 0) + int(log[-1].get("output", 0) or 0)


def _repair_delivery(delivery: dict | None, bible: dict, total_clips: int) -> list[str]:
    """Settle what the code can settle about the delivery map before it is validated (a retry is an OpenAI call):
    ids, the spelling of owners, a narration fact owned by someone other than the narrator, clip numbers out of range,
    a deadline before its own clip, a repeat before its own clip, stray key terms."""
    notes: list[str] = []
    if not delivery:
        return notes
    cast = {c["name"].lower(): c["name"] for c in bible.get("characters", [])}
    protagonist = (bible.get("pov_protagonist") or "").strip()
    seen: set[str] = set()
    for n, f in enumerate(delivery.get("facts") or [], 1):
        fid = (f.get("id") or "").strip() or f"f{n}"
        if fid in seen:
            fid = f"f{n}"
        f["id"] = fid
        seen.add(fid)
        owner = (f.get("owner") or "").strip()
        canon = cast.get(owner.lower())
        if canon is None and owner:
            first = owner.lower().split()[0]
            canon = next((v for k, v in cast.items() if k.split()[0] == first), None)
        if canon and canon != owner:
            f["owner"] = canon
            notes.append(f"fact {fid}: owner {owner!r} -> {canon!r}")
        if f.get("channel") == "narration" and protagonist and f.get("owner") != protagonist:
            notes.append(f"fact {fid}: narration is the protagonist's own voice, so the owner {f.get('owner')!r} -> {protagonist!r}")
            f["owner"] = protagonist
        try:
            at = int(f.get("deliver_at") or 0)
        except (TypeError, ValueError):
            at = 0
        if at and not 1 <= at <= total_clips:
            notes.append(f"fact {fid}: clip {at} -> {min(max(at, 1), total_clips)}")
            at = min(max(at, 1), total_clips)
        f["deliver_at"] = at
        try:
            deadline = int(f.get("deadline") or 0)
        except (TypeError, ValueError):
            deadline = 0
        if at and deadline < at:
            notes.append(f"fact {fid}: deadline {deadline} -> {at} (it cannot be before the clip that says it)")
            deadline = at
        f["deadline"] = min(deadline, total_clips) if deadline else at
        try:
            rep = int(f.get("repeat_at") or 0)
        except (TypeError, ValueError):
            rep = 0
        f["repeat_at"] = rep if at < rep <= total_clips else 0
        f["key_terms"] = [str(t).strip().lower() for t in f.get("key_terms") or [] if str(t).strip()]
    return notes


def _check_delivery_plan(delivery: dict | None, bible: dict, acts: list[dict] | None, total_clips: int,
                         beats: list[dict] | None = None) -> list[str]:
    """Is the delivery map itself sound? Hard: the five sentences, a want, real owners, real clip numbers, and no
    plant_question that names a term the story reveals later (the map would contradict the reveal ledger).
    Soft: the timetable and the plant/pay pairing."""
    if not STORY_DELIVERY:
        return []
    if not delivery:
        return ["[SOFT] The plan has no delivery map (story_in_five, facts, jargon)."]
    problems: list[str] = []
    five = [s for s in (delivery.get("story_in_five") or []) if str(s).strip()]
    if len(five) != 5:
        problems.append(f"delivery.story_in_five must hold exactly five plain sentences, not {len(five)}.")
    facts = delivery.get("facts") or []
    if len(facts) < 4:
        problems.append(f"delivery.facts lists {len(facts)} fact(s); at least 4 must-understand facts are needed.")
    cast = {c["name"].lower() for c in bible.get("characters", [])}
    reserved: set[str] = set()
    for a in acts or []:
        reserved |= {(t or "").strip().lower() for t in (a.get("reveals") or []) if (t or "").strip()}
    for b in beats or []:
        reserved |= {(t or "").strip().lower() for t in (b.get("reveals") or []) if (t or "").strip()}
    for f in facts:
        fid = f.get("id", "?")
        if (f.get("owner") or "").strip().lower() not in cast:
            problems.append(f"fact {fid}: owner '{f.get('owner')}' is not a character in the scene bible.")
        at = f.get("deliver_at") or 0
        if not (isinstance(at, int) and 1 <= at <= total_clips):
            problems.append(f"fact {fid}: deliver_at {at} is not a clip number between 1 and {total_clips}.")
        if f.get("kind") == "plant_question":
            blob = " ".join(f.get("key_terms") or []) + " " + (f.get("text") or "")
            for term in sorted(reserved):
                if _mentions(blob, term):
                    problems.append(
                        f"fact {fid} plants a question but its key terms or text use '{term}', which the story reveals "
                        f"later. Plant THAT a secret exists, in plain words, without naming it."
                    )
                    break
    # Any fact (not only a planted question): its words, its draft line and its key terms may not contain a term that a LATER
    # act (or a later beat) reveals, or the writer is told to say it and forbidden to say it at the same time.
    later_by_clip: list[tuple[int, str]] = []
    for a in acts or []:
        later_by_clip += [(int(a.get("start_clip") or 0), (x or "").strip()) for x in (a.get("reveals") or []) if (x or "").strip()]
    for i, b in enumerate(beats or [], 1):
        later_by_clip += [(i, (x or "").strip()) for x in (b.get("reveals") or []) if (x or "").strip()]
    for f in facts:
        at = f.get("deliver_at") or 0
        if not isinstance(at, int):
            continue
        blob = " ".join(f.get("key_terms") or []) + " " + (f.get("text") or "") + " " + (f.get("line") or "")
        clash = next((term for clip, term in later_by_clip if clip > at and _mentions(blob, term)), None)
        if clash and f.get("kind") != "plant_question":   # a planted question was already reported above
            problems.append(
                f"fact {f.get('id', '?')} (clip {at}) says or requires '{clash}', which the story only reveals later. Say the fact "
                f"without that word, or move the fact to the clip where it is revealed."
            )
    if facts and not any(f.get("role") == "want" for f in facts):
        problems.append("delivery.facts has no fact with role 'want': the audience must be told what the protagonist wants.")
    for role, share in DELIVERY_TIMETABLE.items():
        if role == "ending":
            continue
        at_roles = [f.get("deliver_at") or 0 for f in facts if f.get("role") == role and f.get("deliver_at")]
        limit = max(1, round(total_clips * share))
        if at_roles and min(at_roles) > limit:
            problems.append(f"[SOFT] the first '{role}' fact is said at clip {min(at_roles)}; by clip {limit} the audience should know it.")
        elif not at_roles and role != "want":
            problems.append(f"[SOFT] no fact has role '{role}'.")
    if any(f.get("kind") == "plant_question" for f in facts) and not any(f.get("kind") == "pay_later" for f in facts):
        problems.append("[SOFT] a question is planted but no fact pays it off.")
    return problems


def _jargon_problems(beats: list[dict], jargon: list[dict], first_clip: int, prior_beats: list[dict] | None) -> list[str]:
    """Every listed term is explained in the same or the previous line the first time it is spoken (soft)."""
    problems: list[str] = []
    sequence = (prior_beats or []) + beats
    offset = len(prior_beats or [])
    for j in jargon or []:
        term = (j.get("term") or "").strip()
        if not term:
            continue
        for idx, b in enumerate(sequence):
            if not _mentions(_beat_text(b), term):
                continue
            if idx >= offset:  # first spoken use is in THIS batch
                near = _beat_text(b) + " " + (_beat_text(sequence[idx - 1]) if idx else "")
                if not _terms_covered([j.get("plain_gloss") or ""], near, 0.5) and (j.get("plain_gloss") or "").strip():
                    problems.append(f"[SOFT] clip {first_clip + idx - offset}: '{term}' is spoken without being explained "
                                    f"(plain gloss: {j.get('plain_gloss')}).")
            break
    return problems


def _check_delivery_beats(beats: list[dict], delivery: dict | None, start_clip: int = 1,
                          prior_beats: list[dict] | None = None) -> list[str]:
    """Do the beats' spoken lines carry the facts the plan assigned to them? Only a fact whose key terms are missing
    from its assigned clip is HARD; ownership, the "delivers" list, jargon, repeats and repetition are soft. A plan with
    no delivery map (an older job) is skipped."""
    if not STORY_DELIVERY or not delivery or not delivery.get("facts"):
        return []
    problems: list[str] = []
    end_clip = start_clip + len(beats) - 1
    for f in delivery["facts"]:
        fid, at = f.get("id", "?"), int(f.get("deliver_at") or 0)
        terms = f.get("key_terms") or []
        if start_clip <= at <= end_clip:
            beat = beats[at - start_clip]
            text = _beat_text(beat)
            if not _terms_covered(terms, text):
                problems.append(
                    f"Clip {at}: the plan says this clip must state fact {fid} - \"{f.get('text')}\" - in a spoken line "
                    f"that contains {', '.join(repr(t) for t in terms)}, said by {f.get('owner')}; the lines do not carry it. "
                    f"Rewrite the lines so {f.get('owner')} says it plainly (inside the conflict)."
                )
            else:
                speakers = {(t.get("speaker") or "").strip().lower() for t in _beat_lines(beat)}
                if (f.get("owner") or "").strip().lower() not in speakers:
                    problems.append(f"[SOFT] Clip {at}: fact {fid} belongs to {f.get('owner')}, who does not speak in that beat.")
                if f.get("channel") == "narration" and beat.get("delivery_mode") != "voiceover":
                    problems.append(f"[SOFT] Clip {at}: fact {fid} is meant as narration but the beat is '{beat.get('delivery_mode')}'.")
                if "delivers" in beat and fid not in (beat.get("delivers") or []):
                    problems.append(f"[SOFT] Clip {at}: the beat does not list {fid} in \"delivers\".")
        rep = int(f.get("repeat_at") or 0)
        if start_clip <= rep <= end_clip and not _terms_covered(terms, _beat_text(beats[rep - start_clip])):
            problems.append(f"[SOFT] Clip {rep}: fact {fid} should be said again here, in different words.")
    problems += _jargon_problems(beats, delivery.get("jargon") or [], start_clip, prior_beats)
    # function and turn: a beat that changes nothing, and runs that tread water (soft; only when the plan has them)
    for idx, b in enumerate(beats):
        if "turn" in b and not (b.get("turn") or "").strip():
            problems.append(f"[SOFT] Clip {start_clip + idx}: the beat has no turn (what is different after it).")
        prev = beats[idx - 1] if idx else (prior_beats[-1] if prior_beats else None)
        if prev and b.get("turn") and prev.get("turn") and b.get("function") and b.get("function") == prev.get("function") \
                and b.get("location_id") == prev.get("location_id"):
            a_, b_ = _stems(prev["turn"]), _stems(b["turn"])
            if a_ and b_ and len(a_ & b_) / len(a_ | b_) >= 0.6:
                problems.append(f"[SOFT] Clips {start_clip + idx - 1}-{start_clip + idx}: the same job in the same place with "
                                f"almost the same turn; the story is treading water here.")
    return problems


FACT_REPAIR_SCHEMA = {
    "type": "object",
    "properties": {
        "audio_lines": {
            "type": "array", "minItems": 1, "maxItems": 2,
            "items": {
                "type": "object",
                "properties": {"speaker": {"type": "string"}, "line": {"type": "string"}},
                "required": ["speaker", "line"],
                "additionalProperties": False
            }
        }
    },
    "required": ["audio_lines"],
    "additionalProperties": False
}
FACT_REPAIR_MAX_OUTPUT = 1200


def _last_line(beat: dict | None) -> str:
    turns = _beat_lines(beat) if beat else []
    return f"{turns[-1].get('speaker')}: \"{turns[-1].get('line')}\"" if turns else "(none)"


def _first_line(beat: dict | None) -> str:
    turns = _beat_lines(beat) if beat else []
    return f"{turns[0].get('speaker')}: \"{turns[0].get('line')}\"" if turns else "(none)"


def _fact_repair_prompt(beat: dict, prev_beat: dict | None, next_beat: dict | None, fact: dict, bible: dict,
                        reserved: set[str]) -> tuple[str, str]:
    protagonist = (bible.get("pov_protagonist") or "").strip()
    cast = [c["name"] for c in bible.get("characters", [])]
    voiceover = beat.get("delivery_mode") == "voiceover"
    shape = (f"This is a VOICEOVER beat: exactly ONE line, spoken by {protagonist} as their own first-person thought."
             if voiceover else
             "This is a DIALOGUE beat: ONE or TWO lines (never three), spoken by characters in the beat.")
    styles = "; ".join(f"{c['name']}: {c.get('speech_style')}" for c in bible.get("characters", []) if c.get("speech_style"))
    system = (
        "You rewrite the spoken lines of ONE beat of a short drama so that a specific fact is said plainly and the beat still "
        "works. Keep the beat's situation, who is in it and how each character talks. The new lines must follow naturally "
        "from the line before and lead into the line after. Use short, common words, no metaphor stacking. Say the fact "
        "INSIDE the clash (demanded, refused, accused, confessed), never announced to nobody. Return only the new audio_lines."
    )
    user = "\n".join([
        f"Beat {beat.get('clip_number')} ({beat.get('delivery_mode')}) at {beat.get('location_id')}: {beat.get('summary')}",
        f"Characters in the beat: {', '.join(beat.get('present_characters') or []) or 'nobody'}. Everyone who may speak: {', '.join(cast)}.",
        f"Speech styles: {styles}" if styles else "",
        f"The line before: {_last_line(prev_beat)}",
        f"The line after: {_first_line(next_beat)}",
        "Its current lines: " + (" / ".join(f"{t.get('speaker')}: \"{t.get('line')}\"" for t in _beat_lines(beat)) or "(none)"),
        "",
        f"THE FACT THAT MUST BE SAID (by {fact.get('owner')}, {fact.get('channel')}): {fact.get('text')}",
        f"Key terms the spoken line must contain: {', '.join(fact.get('key_terms') or [])}",
        f"Draft line you may use or improve: \"{fact.get('line')}\"" if fact.get("line") else "",
        "",
        shape,
        f"Total words across the lines: {MIN_WORDS} to {MAX_WORDS}.",
        ("Never say, hint at or name any of these (the story reveals them later): " + ", ".join(sorted(reserved))) if reserved else "",
    ])
    return system, user


def _valid_fact_repair(lines: list[dict], beat: dict, fact: dict, bible: dict, reserved: set[str]) -> list[dict] | None:
    """The rewritten lines, normalised, or None if they do not honour the beat (the original lines are then kept)."""
    cast = {c["name"].lower(): c["name"] for c in bible.get("characters", [])}
    protagonist = (bible.get("pov_protagonist") or "").strip()
    out = []
    for t in lines or []:
        who = cast.get((t.get("speaker") or "").strip().lower())
        text = (t.get("line") or "").strip()
        if not who or not text:
            return None
        out.append({"speaker": who, "line": text})
    voiceover = beat.get("delivery_mode") == "voiceover"
    if not out or (voiceover and (len(out) != 1 or out[0]["speaker"] != protagonist)) or len(out) > 2:
        return None
    words = sum(len(_WORD.findall(t["line"])) for t in out)
    if not (3 <= words <= MAX_WORDS):
        return None
    joined = " ".join(t["line"] for t in out)
    if not _terms_covered(fact.get("key_terms") or [], joined):
        return None
    if any(_mentions(joined, term) for term in reserved):
        return None
    if fact.get("channel") == "dialogue" and (fact.get("owner") or "").lower() not in {t["speaker"].lower() for t in out}:
        return None
    return out


def _repair_missing_facts(beats: list[dict], bible: dict, delivery: dict | None, start_clip: int = 1,
                          budget: "_RepairBudget | None" = None, reserved_terms: list[str] | None = None,
                          prior_beats: list[dict] | None = None) -> list[str]:
    """A fact the plan put in a clip but the lines do not say is NOT a reason to re-ask a whole act on the story model
    (about 11,000 tokens each time). One small call on the cheap model rewrites just that beat's lines, with the line
    before and after it, the fact, its draft line and its key terms. It is tried once per fact; if the answer is not
    valid, or the repair budget is spent, the beat is left as written and the gap is reported. Returns notes for the log."""
    if not STORY_DELIVERY or not delivery or not delivery.get("facts"):
        return []
    notes: list[str] = []
    end_clip = start_clip + len(beats) - 1
    offset = len(prior_beats or [])
    for f in delivery["facts"]:
        at = int(f.get("deliver_at") or 0)
        if not (start_clip <= at <= end_clip):
            continue
        idx = at - start_clip
        beat = beats[idx]
        if _terms_covered(f.get("key_terms") or [], _beat_text(beat)):
            continue
        if beat.get("delivery_mode") == "shock_action":
            notes.append(f"[SOFT] fact {f.get('id')} is planned for clip {at}, which is a wordless beat; the plan needs to move it.")
            continue
        if budget is not None and budget.exhausted:
            notes.append(f"[SOFT] fact {f.get('id')} (clip {at}) was left as written: the repair budget is spent.")
            continue
        prev_beat = beats[idx - 1] if idx else (prior_beats[-1] if prior_beats else None)
        next_beat = beats[idx + 1] if idx + 1 < len(beats) else None
        reserved = set(reserved_terms or []) | _terms_still_secret((prior_beats or []) + beats, offset + idx)
        system, user = _fact_repair_prompt(beat, prev_beat, next_beat, f, bible, reserved)
        try:
            answer = _ask_openai_json(system, user, "narrated_fact_repair", FACT_REPAIR_SCHEMA,
                                      model=app.OPENAI_CLIP_MODEL, max_completion_tokens=FACT_REPAIR_MAX_OUTPUT)
        except Exception as e:  # a repair must never break a plan
            answer = None
            print(f"  fact {f.get('id')} repair call failed: {e}", flush=True)
        if budget is not None:
            budget.charge_last_call()
        lines = _valid_fact_repair((answer or {}).get("audio_lines") or [], beat, f, bible, reserved)
        if lines is None:
            notes.append(f"[SOFT] fact {f.get('id')} is not said in clip {at} and the rewrite did not work; it is left as written.")
            continue
        beat["audio_lines"] = lines
        beat["speech_budget"] = sum(len(_WORD.findall(t["line"])) for t in lines)
        beat["speaker_or_actor"] = (bible.get("pov_protagonist") or "") if beat.get("delivery_mode") == "voiceover" else lines[0]["speaker"]
        if "delivers" in beat and f.get("id") not in (beat.get("delivers") or []):
            beat["delivers"] = list(beat.get("delivers") or []) + [f.get("id")]
        notes.append(f"repaired fact {f.get('id')} at clip {at} with one small call: " + " / ".join(t["line"] for t in lines))
    return notes


def delivery_transcript(beats: list[dict]) -> str:
    """Every spoken line, in order, with its speaker and nothing else: what a viewer who only HEARS the film gets.
    The protagonist's voiceover is marked, since a listener would hear it as an inner voice."""
    out = []
    for i, b in enumerate(beats, 1):
        turns = _beat_lines(b)
        if not turns:
            continue
        inner = b.get("delivery_mode") == "voiceover"
        for t in turns:
            who = (t.get("speaker") or "").strip() or "?"
            out.append(f"Clip {b.get('clip_number', i)} | {who}{' (inner voice, narration)' if inner else ''}: {t.get('line', '')}")
    return "\n".join(out)


BLIND_READ_SCHEMA = {
    "type": "object",
    "properties": {
        "five_sentences": {"type": "array", "minItems": 5, "maxItems": 5, "items": {"type": "string"}},
        "protagonist_and_want": {"type": "string"},
        "obstacle": {"type": "string"},
        "secret_or_lie": {"type": "string"},
        "relationship_change": {"type": "string"},
        "stakes": {"type": "string"},
        "ending_or_open_question": {"type": "string"}
    },
    "required": ["five_sentences", "protagonist_and_want", "obstacle", "secret_or_lie", "relationship_change",
                 "stakes", "ending_or_open_question"],
    "additionalProperties": False
}

_BLIND_FIELDS = ("protagonist_and_want", "obstacle", "secret_or_lie", "relationship_change", "stakes",
                 "ending_or_open_question")


def _blind_read_prompt(transcript: str) -> tuple[str, str]:
    system = (
        "You are a viewer who has only HEARD a short drama. You saw no pictures and read no description or premise. "
        "Below is every line that was spoken, in order, with the speaker's name; a speaker marked (inner voice, narration) is "
        "the protagonist's own thoughts spoken over the picture.\n"
        "Answer ONLY from what is said. If something is not stated in the lines, write exactly 'not stated' for it. "
        "Never guess, never fill a gap with what would be likely, and never use outside knowledge.\n"
        "Return: five plain sentences that retell the story (who the protagonist is and what they want; what stands in the "
        "way; what they do about it; what it costs or what is at stake; where it stands at the end or what is left open), "
        "then short answers to six questions."
    )
    return system, f"The spoken lines:\n{transcript}"


def blind_read(beats: list[dict]) -> dict:
    """One cheap call: a reader who only hears the spoken script retells the story. The reader is deliberately LESS
    informed than the writer; if it understands, a viewer will."""
    system, user = _blind_read_prompt(delivery_transcript(beats))
    return _ask_openai_json(system, user, "narrated_blind_read", BLIND_READ_SCHEMA,
                            model=app.OPENAI_CLIP_MODEL, max_completion_tokens=BLIND_READ_MAX_OUTPUT)


def check_blind_answers(answers: dict, delivery: dict | None) -> dict:
    """Which intended facts did the blind reader actually recover? Code only: a fact is understood when the reader's
    words contain at least half of its distinctive terms."""
    reader = " ".join([*(answers.get("five_sentences") or []), *(str(answers.get(k) or "") for k in _BLIND_FIELDS)])
    not_stated = [k for k in _BLIND_FIELDS if str(answers.get(k) or "").strip().lower().startswith("not stated")]
    statuses = []
    for f in (delivery or {}).get("facts") or []:
        statuses.append({"id": f.get("id"), "role": f.get("role"), "kind": f.get("kind"), "text": f.get("text"),
                         "understood": _terms_covered(f.get("key_terms") or [], reader)})
    understood = sum(1 for s in statuses if s["understood"])
    problems = [f"[SOFT] The blind reader did not learn fact {s['id']} ({s['role']}): {s['text']}" for s in statuses if not s["understood"]]
    problems += [f"[SOFT] The blind reader says '{k}' is not stated in the spoken script." for k in not_stated]
    return {"facts": statuses, "understood": understood, "total": len(statuses),
            "understood_share": round(understood / len(statuses), 2) if statuses else None,
            "not_stated": not_stated, "problems": problems}


LONG_STAY_CLIPS = 15   # a stretch in one place longer than this (15 clips = 75 s) is noted in the plan report (soft)


def _location_stays(beats: list[dict]) -> list[dict]:
    """The plan as consecutive stretches in one place: [{"location", "from", "to", "clips"}]."""
    stays: list[dict] = []
    for i, b in enumerate(beats, 1):
        loc = b.get("location_id") or "?"
        clip = b.get("clip_number") or i
        if stays and stays[-1]["location"] == loc:
            stays[-1]["to"] = clip
            stays[-1]["clips"] += 1
        else:
            stays.append({"location": loc, "from": clip, "to": clip, "clips": 1})
    return stays


def plan_delivery_report(plan: dict, run_blind: bool | None = None) -> dict:
    """What the Director shows before anything is rendered: the free checks, the spoken-script stats, the dialogue-only
    page, and (one cheap call) what a blind reader understood. Never raises: a report must not break a plan."""
    delivery = plan.get("delivery") or {}
    beats = plan.get("beats") or []
    bible = plan.get("scene_bible") or {}
    words = narration = lines = 0
    for b in beats:
        for t in _beat_lines(b):
            n = len(_WORD.findall(t.get("line") or ""))
            words += n
            lines += 1
            if b.get("delivery_mode") == "voiceover":
                narration += n
    share = round(narration / words, 2) if words else 0.0
    minutes = len(beats) * CLIP_SECONDS / 60 if beats else 0
    problems: list[str] = []
    try:
        problems += _soften(_check_delivery_plan(delivery, bible, plan.get("acts"), len(beats), beats))
        problems += _soften(_check_delivery_beats(beats, delivery, 1))
    except Exception as e:  # a report must never break a plan
        problems.append(f"[SOFT] delivery checks could not run: {e}")
    try:
        problems += _sequence_beat_notes(beats, plan.get("acts"))
    except Exception as e:  # a report must never break a plan
        problems.append(f"[SOFT] the sequence check could not run: {e}")
    lo, hi = NARRATION_SHARE_BAND
    if words and not (lo <= share <= hi):
        problems.append(f"[SOFT] narration is {int(share * 100)}% of the spoken words (target {int(lo * 100)}-{int(hi * 100)}%).")
    # Places: how many are used, and the longest stay in one. A soft note only: a long scene that keeps turning is fine,
    # a long stretch where nothing changes is not, and this cannot tell which; it says where to look.
    stays = _location_stays(beats)
    defined = [l.get("id") for l in bible.get("locations", []) if l.get("id")]
    used = list(dict.fromkeys(s["location"] for s in stays))
    longest = max(stays, key=lambda s: s["clips"]) if stays else None
    for s in stays:
        if s["clips"] > LONG_STAY_CLIPS:
            problems.append(
                f"[SOFT] Clips {s['from']}-{s['to']} stay in '{s['location']}' for {s['clips'] * CLIP_SECONDS} s. Fine if the scene "
                f"keeps turning; if nothing new happens, move the story or add a second place."
            )
    location_lines = [
        f"Locations: {len(used)} used of {len(defined)} defined" if defined else f"Locations: {len(used)} used",
        (f"Longest stay in one place: {longest['clips']} clips ({longest['clips'] * CLIP_SECONDS} s) in {longest['location']}"
         if longest else "Longest stay in one place: -"),
    ]
    report = {
        "story_in_five": delivery.get("story_in_five") or [],
        "facts": delivery.get("facts") or [],
        "stats": {"spoken_lines": lines, "spoken_words": words, "narration_share": share,
                  "words_per_minute": round(words / minutes) if minutes else 0,
                  "wordless_clips": sum(1 for b in beats if not _beat_lines(b)), "clips": len(beats),
                  "locations_used": len(used), "locations_defined": len(defined),
                  "longest_stay_clips": longest["clips"] if longest else 0,
                  "longest_stay_location": longest["location"] if longest else None},
        "location_lines": location_lines,
        "stays": stays,
        "plain_pass": plan.get("plain_pass"),
        "problems": problems,
        "dialogue_only": delivery_transcript(beats),
        "blind": None,
    }
    if run_blind is None:
        run_blind = BLIND_READ and STORY_DELIVERY and bool(delivery.get("facts"))
    if run_blind and beats:
        try:
            result = check_blind_answers(blind_read(beats), delivery)
            report["blind"] = result
            report["problems"] += result["problems"]
        except Exception as e:
            report["blind_error"] = f"{type(e).__name__}: {e}"
    if run_blind and beats and CAST_GAP_CHECK and bible.get("characters"):
        try:
            gaps = find_cast_gaps(beats, bible)
            report["cast_gaps"] = gaps
            if gaps:
                who = "; ".join(f"{g['label']} (clips {_clip_ranges(g['clips'])})" for g in gaps)
                report["problems"].append(
                    f"[REVIEW] Cast: the plan puts people on screen who are not in the cast: {who}. They get no portrait, so they will be left out of "
                    f"the shots or look different in every clip. Under 'Revise the plan' press 'Check the cast' to add them.")
        except Exception as e:  # a report must never break a plan
            report["cast_gap_error"] = f"{type(e).__name__}: {e}"
    return report


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

    seen_hair: list[tuple[str, str, str, bool]] = []
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
        this_supporting = _is_supporting(c)
        for other, other_color, other_style, other_supporting in seen_hair:
            if color_fam == other_color and style_fam == other_style:
                problems.append(f"{cname} and {other} have the same hair colour AND the same hair style; change one of the two so they can be told apart.")
            elif small_cast and color_fam == other_color and not (this_supporting or other_supporting):
                problems.append(f"{cname} and {other} both have {color_fam} hair. In a cast this small every character needs a different hair colour, or they cannot be told apart on a dim phone screen.")
        seen_hair.append((cname, color_fam, style_fam, this_supporting))

    n_supporting = sum(1 for c in bible.get("characters", []) if _is_supporting(c))
    if n_supporting > MAX_SUPPORTING:
        problems.append(f"[SOFT] {n_supporting} supporting characters; at most {MAX_SUPPORTING} fit in one film, because every extra face makes a shot harder to keep consistent.")
    _cramped = re.compile(r"\b(narrow|cramped|tiny|tight|claustrophobic|confined|squeezed)\b", re.I)
    for loc in bible.get("locations", []):
        m = _cramped.search(" ".join(str(loc.get(k) or "") for k in ("description", "layout")) + " " + str(loc.get("image_prompt") or "").split("The place is EMPTY")[0])
        if m:
            problems.append(f"[SOFT] location '{loc.get('id')}' is described as '{m.group(0)}'. Every place needs room for three people and a camera several metres back: describe it as wide and spacious (a corridor is a wide landing or hall).")
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
            # The narrator's own thought over a scene with people in it needs the narrator in that scene: a voice on a
            # line, off screen, is enough. The planner was told so and still forgets; adding the name costs no retry, and
            # the clip stage then writes them in off screen.
            if on_screen and protagonist and protagonist.lower() not in {p.lower() for p in on_screen}:
                b["present_characters"] = list(b.get("present_characters") or []) + [protagonist]
                fixed.append(f"clip {b.get('clip_number', '?')}: added the narrator {protagonist!r} to present_characters (off screen is fine)")
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
    """Validates beat sequence rules: voiceover run length, speakers, audio lines, word count, reveals."""
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
                elif line_words > MAX_WORDS:
                    problems.append(f"Clip {i}: the lines total {line_words} words, but at most {MAX_WORDS} fit in {CLIP_SECONDS} seconds before the voice starts dropping words. Shorten them to {MAX_WORDS} words or fewer, keeping the meaning and the key words.")
                elif line_words < MIN_WORDS:
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

    supporting = {c["name"].lower(): c["name"] for c in bible.get("characters", []) if _is_supporting(c)}
    if supporting:
        spoken: dict[str, int] = {}
        for b in all_sequence:
            for t in _beat_lines(b):
                who = (t.get("speaker") or "").strip().lower()
                if who in supporting:
                    spoken[who] = spoken.get(who, 0) + 1
        for who, n in spoken.items():
            if n > SUPPORTING_MAX_LINES:
                problems.append(f"[SOFT] {supporting[who]} is a supporting character and speaks {n} lines; supporting characters speak at most {SUPPORTING_MAX_LINES}. Give the extra lines to a main character.")

    return problems


def _check_narrated_outline(data: dict, total_clips: int, hard_delivery: bool = False) -> list[str]:
    """Validates the whole plan: beat rules, scene bible, location variety, and (when present) story delivery.

    `hard_delivery` makes an UNSOUND DELIVERY MAP (no 'want' fact, fewer than four facts, owners that do not exist...) a hard
    problem; the single-call plan passes True because a retry is the only way to repair the map. A fact missing from its
    clip is never hard here: it is repaired afterwards with one small call (`_repair_missing_facts`), so it must not cost
    a retry of the whole plan, and for the act-based plan the final check only reports (failing at this point would throw
    away every planning call that was paid for)."""
    problems = []
    bible = data.get("scene_bible", {})
    beats = data.get("beats", [])

    if len(beats) != total_clips:
        problems.append(f"Outline produced {len(beats)} beats; exactly {total_clips} required.")

    problems.extend(_check_scene_bible(bible))
    problems.extend(_check_beats(beats, bible))
    if STORY_DELIVERY and data.get("delivery"):
        map_problems = _check_delivery_plan(data["delivery"], bible, data.get("acts"), total_clips, beats)
        problems.extend(map_problems if hard_delivery else _soften(map_problems))
        problems.extend(_soften_delivery(_check_delivery_beats(beats, data["delivery"], 1)))

    # A short plan commits to its shape too (a plan with none, an older one, is simply not checked for it).
    if total_clips < 30 and data.get("sequences") is not None:
        problems.extend(_check_sequences(_single_acts(data, total_clips), bible, total_clips))
        if total_clips >= 8 and len({b.get("location_id") for b in beats if b.get("location_id")}) < 2:
            problems.append(f"[SOFT] Location variety: the whole {total_clips}-clip story stays in one place. "
                            f"A story this short should use {_short_places(total_clips)[0]} to {_short_places(total_clips)[1]}: a place for each scene.")

    # Location variety check (§9: Confinement within an act, progression between acts)
    if total_clips >= 30:
        used_locs = {b.get("location_id") for b in beats if b.get("location_id")}
        if len(used_locs) < 3:
            problems.append(
                f"[SOFT] Location variety: Only {len(used_locs)} distinct locations used across {total_clips} clips. "
                f"A production of this length should progress across {_location_target(total_clips)[0]}-{_location_target(total_clips)[1]} locations (at least 3)."
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
                f"A production of {total_clips} clips should establish {_location_target(total_clips)[0]} to {_location_target(total_clips)[1]} locations across acts."
            )
        all_act_locs = {loc for a in acts for loc in a.get("primary_locations", []) if loc}
        if len(all_act_locs) < 3:
            problems.append(
                f"[SOFT] Location variety: acts collectively use only {len(all_act_locs)} distinct locations. "
                f"Aim for progression across {_location_target(total_clips)[0]} to {_location_target(total_clips)[1]} locations across acts."
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

    problems.extend(_check_sequences(acts, bible, total_clips))
    problems.extend(_check_delivery_plan(data.get("delivery"), bible, acts, total_clips))
    return problems


def _check_act_beats(beats: list[dict], bible: dict, start_clip: int, end_clip: int,
                     prior_beats: list[dict] | None = None,
                     reserved_terms: list[str] | None = None,
                     delivery: dict | None = None, soft_delivery: bool = False) -> list[str]:
    """Validates beats generated for a single act/batch against the bible, the prior beats, the terms later acts are
    keeping back, and the facts the plan assigned to these clips (`delivery`)."""
    problems = []
    expected_count = end_clip - start_clip + 1
    if len(beats) != expected_count:
        problems.append(f"Act produced {len(beats)} beats; exactly {expected_count} required for clips {start_clip} to {end_clip}.")

    # Auto-normalize clip numbers if shifted
    for idx, b in enumerate(beats):
        if b.get("clip_number") != start_clip + idx:
            b["clip_number"] = start_clip + idx

    problems.extend(_check_beats(beats, bible, prior_beats=prior_beats))
    delivery_problems = _check_delivery_beats(beats, delivery, start_clip, prior_beats)
    # With soft_delivery the planner does NOT re-ask the whole act for a missing fact: _repair_missing_facts fixes it
    # afterwards with one small call per fact.
    problems.extend(_soften_delivery(delivery_problems) if soft_delivery else delivery_problems)

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


# --- Retries run on the cheap model, and cannot change what was fine ----------------------------------------------
# The FIRST write of a plan stays on the story model: it invents the story and every spoken line. A RETRY repairs
# problems that are named, so it runs on the cheap model (`OPENAI_CLIP_MODEL`), and its answer is MERGED in code: only
# the clips or the parts of the plan a broken rule names are taken from it, everything else is kept exactly as the
# story model wrote it. (A re-run after a cut-off reply is the first write again, not a repair, so it stays on the
# story model.)
RETRY_ON_CLIP_MODEL = True
BATCH_MAX_CLIPS = 20   # an act longer than this is split; small acts are merged only while the total stays within it
BATCH_MIN_CLIPS = 6    # an act shorter than this is merged into the previous batch (when the total fits)
_CLIP_NUMBER = re.compile(r"\b(?:clip|beat)s?\s+(\d+)\b", re.I)


def _retry_model(attempt: int) -> str | None:
    """The model for this attempt: None (the story model) for the first write, the cheap model for every retry."""
    return app.OPENAI_CLIP_MODEL if (attempt and RETRY_ON_CLIP_MODEL) else None


def _flagged_clips(problems: list[str]) -> set[int] | None:
    """The clip numbers that a list of hard problems names, or None when the whole answer is needed (a problem that
    names no clip, or a wrong NUMBER of beats)."""
    flagged: set[int] = set()
    for p in problems:
        if "beats; exactly" in p:
            return None
        numbers = _CLIP_NUMBER.findall(p)
        if not numbers:
            return None
        flagged |= {int(n) for n in numbers}
    return flagged


def _merge_beats(old: list[dict], new: list[dict], flagged: set[int] | None, start_clip: int = 1) -> list[dict]:
    """The retry's beat for each flagged clip, the earlier beat for every other clip."""
    if flagged is None or len(old) != len(new):
        return new
    return [new[i] if (start_clip + i) in flagged else old[i] for i in range(len(old))]


def _merge_breakdown(old: dict, new: dict, hard: list[str], total_clips: int) -> dict:
    """Take from a retried act breakdown only the part a broken rule names (the bible, the delivery map or the acts)."""
    bible = old.get("scene_bible", {})
    in_bible = set(_hard_problems(_check_scene_bible(bible)))
    in_map = set(_hard_problems(_check_delivery_plan(old.get("delivery"), bible, old.get("acts"), total_clips)))
    out = dict(old)
    if any(p in in_bible for p in hard) and "scene_bible" in new:
        out["scene_bible"] = new["scene_bible"]
    if any(p in in_map and p not in in_bible for p in hard) and "delivery" in new:
        out["delivery"] = new["delivery"]
    if any(p not in in_bible and p not in in_map for p in hard) and "acts" in new:
        out["acts"] = new["acts"]
    return out


def _merge_outline(old: dict, new: dict, hard: list[str], total_clips: int) -> dict:
    """The same for the single-call plan: the bible, the delivery map, and (clip by clip) the beats."""
    bible = old.get("scene_bible", {})
    in_bible = set(_hard_problems(_check_scene_bible(bible)))
    in_map = set(_hard_problems(_check_delivery_plan(old.get("delivery"), bible, old.get("acts"), total_clips, old.get("beats"))))
    in_seq = set(_hard_problems(_check_sequences(_single_acts(old, total_clips), bible, total_clips))) if old.get("sequences") is not None else set()
    out = dict(old)
    if any(p in in_bible for p in hard) and "scene_bible" in new:
        out["scene_bible"] = new["scene_bible"]
    if any(p in in_map and p not in in_bible for p in hard) and "delivery" in new:
        out["delivery"] = new["delivery"]
    if any(p in in_seq and p not in in_bible and p not in in_map for p in hard) and "sequences" in new:
        out["sequences"] = new["sequences"]
    rest = [p for p in hard if p not in in_bible and p not in in_map and p not in in_seq]
    if rest:
        out["beats"] = _merge_beats(old.get("beats", []), new.get("beats", []), _flagged_clips(rest), 1)
    return out


def _scope_note(flagged: set[int] | None) -> str:
    if not flagged:
        return ""
    return ("\nONLY clips " + ", ".join(str(n) for n in sorted(flagged)) + " may change: return every other beat EXACTLY as it "
            "was in your previous response, word for word.")


def _ask_planner(sys_p: str, usr_p: str, name: str, schema: dict, model: str | None = None, ceiling: int | None = None) -> dict:
    """A planning call with a ceiling on its reply (`ceiling`, from `_plan_ceiling`, grows with what the call writes;
    PLAN_MAX_OUTPUT when not given). `model=None` is the story model (the first write of a plan); the retry paths pass the
    cheap model (see `_retry_model`).

    A reply that hits the ceiling is a runaway, not a long answer, and is asked for once more before the plan
    is given up on: the repeat is cheaper than abandoning the planning calls already paid for."""
    for attempt in (1, 2):
        try:
            return _ask_openai_json(sys_p, usr_p, name, schema, model=model, max_completion_tokens=ceiling or PLAN_MAX_OUTPUT)
        except OpenAIOutputCut as e:
            if attempt == 2:
                raise
            print(f"  {e}; asking once more.", flush=True)


def _write_single_shot_outline(topic: str, duration: int, total_clips: int) -> tuple[dict, list[str]]:
    """Generates the Master Plan in a single shot for shorter videos (< 30 clips)."""
    sys_p, usr_p = _narrated_outline_prompt(topic, duration, total_clips)
    budget = _RepairBudget(_repair_budget_for(total_clips))
    schema = _cap_plan_schema(OUTLINE_SCHEMA, total_clips, beats=total_clips)
    ceiling = _plan_ceiling(total_clips, 1200, 24000)

    def finish(data: dict, problems: list[str]) -> tuple[dict, list[str]]:
        """A fact the lines do not say is repaired with one small call each (never by re-asking the whole plan), then the
        plan is judged again. Whatever is still wrong about delivery is reported, not fatal."""
        notes = _repair_missing_facts(data.get("beats", []), data.get("scene_bible", {}), data.get("delivery"), 1, budget=budget)
        for note in notes:
            print(f"  {note}")
        if notes:
            problems = _check_narrated_outline(data, total_clips)
        _fold_sequences_into_acts(data, total_clips)
        return data, _soften_delivery(problems)

    prev, prev_hard = None, []
    for attempt in range(SCRIPT_RETRIES + 1):
        data = _ask_planner(sys_p, usr_p, "narrated_outline", schema, model=_retry_model(attempt), ceiling=ceiling)
        if attempt:
            budget.charge_last_call()
            if prev is not None:
                data = _merge_outline(prev, data, prev_hard, total_clips)  # only what a broken rule named may change
        _compile_bible_visuals(data.get("scene_bible", {}))
        for note in _repair_beats(data.get("beats", []), data.get("scene_bible", {})):
            print(f"  repaired {note}")
        for note in _repair_delivery(data.get("delivery"), data.get("scene_bible", {}), total_clips):
            print(f"  repaired {note}")
        wrapped = _single_acts(data, total_clips)
        for note in _repair_sequences(wrapped, total_clips, data.get("scene_bible")):
            print(f"  repaired {note}")
        data["sequences"] = wrapped[0]["sequences"]
        problems = _check_narrated_outline(data, total_clips, hard_delivery=True)
        hard = _hard_problems(problems)
        if not hard:
            return finish(data, problems)
        if budget.exhausted:
            print(f"  Repair budget ({budget.limit:,} tokens) used up; the remaining problems are shown, not re-asked.")
            return finish(data, problems)
        if attempt < SCRIPT_RETRIES:
            print(f"  Outline check: {len(hard)} problem(s), asking OpenAI to fix (retry {attempt+1}/{SCRIPT_RETRIES}):")
            for p in hard:
                print(f"    - {p}")
            prev, prev_hard = data, hard
            usr_p = (
                f"Story Premise:\n{topic}\n\nHere is your previous response:\n"
                + json.dumps(data)
                + "\n\nIt broke these rules:\n- "
                + "\n- ".join(hard)
                + "\n\nCRITICAL INSTRUCTION: DO NOT hallucinate a completely new story. You must remain 100% faithful to the Story Premise, characters, and established events above. ONLY adjust the specific fields necessary to satisfy the rules above and keep everything else exactly as it was; return valid JSON adhering strictly to the schema."
                + _scope_note(_flagged_clips(hard))
            )
    return finish(data, problems)


def _write_act_based_outline(topic: str, duration: int, total_clips: int) -> tuple[dict, list[str]]:
    """Generates the Master Plan in acts for long videos (>= 30 clips).
    Call 1: Scene Bible + Act Outline.
    Call 2..N: Beats for each act/batch, seeing prior beats and roadmap."""
    act_count = _detect_premise_act_count(topic)
    sys_p, usr_p = _narrated_act_breakdown_prompt(topic, duration, total_clips, act_count=act_count)

    budget = _RepairBudget(_repair_budget_for(total_clips))  # every retry and rewrite of this plan draws on one budget
    breakdown_schema = _cap_plan_schema(ACT_BREAKDOWN_SCHEMA, total_clips)
    breakdown_ceiling = _plan_ceiling(total_clips, 120, 24000)
    breakdown_data = {}
    prev_breakdown, prev_hard_b = None, []
    for attempt in range(SCRIPT_RETRIES + 1):
        breakdown_data = _ask_planner(sys_p, usr_p, "narrated_act_breakdown", breakdown_schema, model=_retry_model(attempt),
                                      ceiling=breakdown_ceiling)
        if attempt:
            budget.charge_last_call()
            if prev_breakdown is not None:  # only the part a broken rule named (bible, delivery map or acts) may change
                breakdown_data = _merge_breakdown(prev_breakdown, breakdown_data, prev_hard_b, total_clips)
        _compile_bible_visuals(breakdown_data.get("scene_bible", {}))
        for note in _repair_delivery(breakdown_data.get("delivery"), breakdown_data.get("scene_bible", {}), total_clips):
            print(f"  repaired {note}")
        for note in _repair_sequences(breakdown_data.get("acts"), total_clips, breakdown_data.get("scene_bible")):
            print(f"  repaired {note}")
        breakdown_problems = _check_act_breakdown(breakdown_data, total_clips)
        hard = _hard_problems(breakdown_problems)
        if not hard:
            break
        if budget.exhausted:
            print(f"  Repair budget ({budget.limit:,} tokens) used up; the act breakdown is used as it is.")
            break
        if attempt < SCRIPT_RETRIES:
            print(f"  Act breakdown check: {len(hard)} problem(s), asking OpenAI to fix (retry {attempt+1}/{SCRIPT_RETRIES}):")
            for p in hard:
                print(f"    - {p}")
            prev_breakdown, prev_hard_b = breakdown_data, hard
            usr_p = (
                f"Story Premise:\n{topic}\n\nHere is your previous response:\n"
                + json.dumps(breakdown_data)
                + "\n\nIt broke these rules:\n- "
                + "\n- ".join(hard)
                + "\n\nCRITICAL INSTRUCTION: DO NOT hallucinate a completely new story. ONLY adjust the specific fields necessary to satisfy the rules and keep everything else exactly as it was; return valid JSON adhering strictly to the schema."
            )

    bible = breakdown_data.get("scene_bible", {})
    raw_acts = breakdown_data.get("acts", [])
    acts = _normalize_act_spans(raw_acts, total_clips)
    for note in _repair_sequences(acts, total_clips, bible) + _sanitize_sequence_places(acts, bible):
        print(f"  repaired {note}")
    breakdown_data["acts"] = acts
    batches = _plan_act_batches(acts)
    delivery = breakdown_data.get("delivery") if STORY_DELIVERY else None

    all_beats: list[dict] = []
    for batch in batches:
        start_clip = batch["start_clip"]
        end_clip = batch["end_clip"]
        batch_sys, batch_usr = _narrated_act_beats_prompt(topic, batch, acts, bible, all_beats, total_clips, delivery=delivery)
        batch_beats: list[dict] = []
        prev_beats_b, prev_hard_beats = None, []
        batch_schema = _cap_plan_schema(ACT_BEATS_SCHEMA, total_clips, beats=batch["clip_count"], cast=len(bible.get("characters", [])) or None)
        batch_ceiling = _plan_ceiling(batch["clip_count"], 1200, 16000)
        for attempt in range(SCRIPT_RETRIES + 1):
            beats_resp = _ask_planner(batch_sys, batch_usr, f"narrated_act_beats_{batch['batch_index']}", batch_schema,
                                      model=_retry_model(attempt), ceiling=batch_ceiling)
            if attempt:
                budget.charge_last_call()
            batch_beats = beats_resp.get("beats", [])
            if attempt and prev_beats_b is not None:
                # The retry runs on the cheap model: take only the clips a broken rule named, keep the rest exactly.
                batch_beats = _merge_beats(prev_beats_b, batch_beats, _flagged_clips(prev_hard_beats), start_clip)
            for note in _repair_beats(batch_beats, bible):
                print(f"  repaired {note}")
            problems = _check_act_beats(batch_beats, bible, start_clip, end_clip, prior_beats=all_beats,
                                        reserved_terms=_terms_reserved_for_later_acts(acts, batch), delivery=delivery,
                                        soft_delivery=True)
            hard = _hard_problems(problems)
            if not hard:
                break
            if budget.exhausted:
                print(f"  Repair budget ({budget.limit:,} tokens) used up; Act {batch['batch_index']} is kept as written "
                      f"and its remaining problems are reported.")
                break
            if attempt < SCRIPT_RETRIES:
                print(f"  Act {batch['batch_index']} check: {len(hard)} problem(s), asking OpenAI to fix (retry {attempt+1}/{SCRIPT_RETRIES}):")
                for p in hard:
                    print(f"    - {p}")
                prev_beats_b, prev_hard_beats = batch_beats, hard
                batch_usr = (
                    batch_usr
                    + f"\n\nHere is your previous response:\n{json.dumps({'beats': batch_beats})}\n\n"
                    + "It broke these rules:\n- "
                    + "\n- ".join(hard)
                    + f"\n\nCRITICAL INSTRUCTION: Return valid JSON with 'beats' containing exactly {batch['clip_count']} items strictly addressing the above problems."
                    + _scope_note(_flagged_clips(hard))
                )
        # A fact the lines still do not say is fixed here with one small call each, not by re-asking this whole act.
        for note in _repair_missing_facts(batch_beats, bible, delivery, start_clip, budget=budget,
                                          reserved_terms=_terms_reserved_for_later_acts(acts, batch), prior_beats=all_beats):
            print(f"  {note}")
        all_beats.extend(batch_beats)

    # Backstop. The per-batch check catches a leak against what the acts declared; this catches one against
    # what the beats actually wrote, which only becomes visible once every act exists. Rewriting the single
    # batch that owns the offending beat costs one call, where failing here would discard every planning call
    # and the whole plan with it.
    leaks = _leaking_beats(all_beats)
    if leaks and budget.exhausted:
        print("  Repair budget used up; the reveal leak is reported, not rewritten.")
    if leaks and not budget.exhausted:
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
            batch_sys, batch_usr = _narrated_act_beats_prompt(topic, owner, acts, bible, head, total_clips, delivery=delivery)
            batch_usr += (
                "\n\nYour previous beats for these clips leaked the story:\n- " + leak_notes
                + "\n\nCRITICAL INSTRUCTION: keep the same beats, locations and rhythm; only rewrite the offending "
                  "lines so they use nothing the audience has not been told yet, and keep every fact above that this "
                  "batch must deliver. Return valid JSON."
            )
            retry = _ask_planner(batch_sys, batch_usr, f"narrated_act_beats_{owner['batch_index']}_releak",
                                 _cap_plan_schema(ACT_BEATS_SCHEMA, total_clips, beats=owner["clip_count"],
                                                  cast=len(bible.get("characters", [])) or None),
                                 model=_retry_model(1), ceiling=_plan_ceiling(owner["clip_count"], 1200, 16000))
            budget.charge_last_call()
            fixed_beats = retry.get("beats", [])
            if len(fixed_beats) == owner["clip_count"]:
                # a rewrite on the cheap model may change only the clips that leaked
                fixed_beats = _merge_beats(all_beats[owner["start_clip"] - 1: owner["end_clip"]], fixed_beats,
                                           {i + 1 for i, _t in leaks if owner["start_clip"] <= i + 1 <= owner["end_clip"]},
                                           owner["start_clip"])
                for offset, b in enumerate(fixed_beats):
                    b["clip_number"] = owner["start_clip"] + offset
                for note in _repair_missing_facts(fixed_beats, bible, delivery, owner["start_clip"], budget=budget,
                                                  reserved_terms=_terms_reserved_for_later_acts(acts, owner), prior_beats=head):
                    print(f"  {note}")
                all_beats = head + fixed_beats + tail

    full_data = {
        "scene_bible": bible,
        "acts": acts,
        "beats": all_beats
    }
    if delivery:
        full_data["delivery"] = delivery
    full_problems = _check_narrated_outline(full_data, total_clips)
    return full_data, full_problems


def write_narrated_outline(topic: str, duration: int, total_clips: int) -> tuple[dict, list[str]]:
    """Generates the Master Plan. Automatically switches to act-based generation for >= 30 clips."""
    if total_clips < 30:
        return _write_single_shot_outline(topic, duration, total_clips)
    return _write_act_based_outline(topic, duration, total_clips)


def write_narrated_continuation_outline(topic: str, continuation_prompt: str, bible: dict,
                                        prev_beats: list[dict], additional_clips: int,
                                        delivery: dict | None = None) -> tuple[dict, list[str]]:
    """Generates additional beats extending an existing narrated drama plan. `delivery` is the earlier plan's map: the
    continuation is told what the audience already knows and which planted questions are still open."""
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
    sys_p, usr_p = _narrated_act_beats_prompt(topic, batch, all_acts, bible, prev_beats,
                                              start_clip + additional_clips - 1, delivery=delivery)
    new_beats: list[dict] = []
    problems: list[str] = []
    base_usr, prev_new, prev_hard = usr_p, None, []
    cont_schema = _cap_plan_schema(ACT_BEATS_SCHEMA, end_clip, beats=additional_clips, cast=len(bible.get("characters", [])) or None)
    cont_ceiling = _plan_ceiling(additional_clips, 1200, 16000)
    for attempt in range(SCRIPT_RETRIES + 1):
        resp = _ask_planner(sys_p, usr_p, "narrated_continuation_beats", cont_schema, model=_retry_model(attempt),
                            ceiling=cont_ceiling)
        new_beats = resp.get("beats", [])
        if attempt and prev_new is not None:
            new_beats = _merge_beats(prev_new, new_beats, _flagged_clips(prev_hard), start_clip)
        for note in _repair_beats(new_beats, bible):
            print(f"  repaired {note}")
        problems = _check_act_beats(new_beats, bible, start_clip, end_clip, prior_beats=prev_beats, delivery=delivery,
                                    soft_delivery=True)
        hard = _hard_problems(problems)
        if not hard:
            break
        if attempt < SCRIPT_RETRIES:
            # a retry now says what was wrong (it used to re-send the same request) and runs on the cheap model
            prev_new, prev_hard = new_beats, hard
            usr_p = (base_usr + f"\n\nHere is your previous response:\n{json.dumps({'beats': new_beats})}\n\n"
                     + "It broke these rules:\n- " + "\n- ".join(hard)
                     + f"\n\nCRITICAL INSTRUCTION: Return valid JSON with 'beats' containing exactly {additional_clips} items "
                       "strictly addressing the above problems." + _scope_note(_flagged_clips(hard)))
    result = {"scene_bible": bible, "beats": new_beats}
    if delivery:
        result["delivery"] = delivery
    return result, _soften_delivery(problems)


# ---------------------------------------------------------------------------
# Plan revision: the user reads the plan and asks for changes
# ---------------------------------------------------------------------------
# After the plan is written, and before anything is paid for, the user can type a note ("Lily must never recognise Ethan
# when he comes back as Jack"). The note is split into items (a standing RULE, or a one-time FIX), the clips that must change
# are FOUND on the cheap model, the user picks which of them to change, and ONLY those clips are rewritten, on the story
# model, in place: the same clips, places and cast. Everything else in the plan stays exactly as it was. Standing rules are
# kept with the plan and reach every later stage.
#
# HOW CLIPS ARE FOUND. The splitter turns each item into a PROBE: one yes/no question that can be asked of a single clip
# ("does anything said or done here only make sense if Lily knows who Jack is?"), a few generic TELLS (the indirect ways a line
# can fail it), and the point where the item STOPS applying (read from the note or the premise: a rule that forbids what the
# premise's ending requires stops there). The scan then gives EVERY clip a score from 0 to 3 and must quote the failing words.
# Asking what a line takes for granted finds clips a "does this contradict the rule" verdict walks past ("You came back poor
# now?" says nothing about recognition and assumes all of it). The probe is generic: nothing in the scan knows about any story.
MAX_PLAN_RULES = 12
MAX_RULE_CHARS = 220
MAX_NOTE_CHARS = 3000
MAX_REVISION_ITEMS = 10
MAX_PROBE_CHARS = 300
MAX_STOP_CHARS = 200
MAX_PREMISE_CHARS = 1500                 # how much of the premise the splitter reads (it needs it to see where a rule must stop)
REVISION_REWRITE_GROUP = 12              # clips rewritten in one call
# A ceiling on one splitter reply, THINKING INCLUDED. 4,000 was enough for the usual 400-600 tokens but a longer note with two
# items once made the model think past it (2026-10-09: "reply cut off at the 4000 token limit"). On the cheap model 12,000 tokens
# cost about a cent at worst, and a reply that is still cut gets one more try with less thinking (see split_revision_note).
REVISION_SPLIT_MAX_OUTPUT = 12000
SCAN_WINDOW = 60                        # clips scanned in one call; a longer plan is scanned in windows, each with the earlier words as context
SCAN_EARLIER_CLIPS = 150                 # how many earlier clips (words only) a later window is shown
SCAN_MAX_OUTPUT = 16000                  # ceiling on one scan reply, reasoning included (a 36-clip scan at high effort used about 2,600)
PICK_SCORE = 2                           # a clip scoring this or more is ticked for rewriting; a 1 is shown as a "maybe", unticked
MAYBE_SCORE = 1
# Finding a clip that only IMPLIES the opposite is a judgement call, and one scan of it is unreliable: measured on the cheap model
# (36-clip plan, three clips that assume the character knows a secret): at its default effort one scan found all three in 1 run
# of 5; at high effort 4 of 10 (the clearest clip every time, the two subtler ones 4 and 6 times of 10); two scans together
# found all three in 67-90% of pairs. So: high effort, and SCAN_PASSES independent scans merged by the highest score. A scan is
# about 2,000 tokens in and costs a fraction of a cent on the cheap model.
SCAN_PASSES = 3
SCAN_REASONING = "high"

SPLIT_SCHEMA = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array", "maxItems": MAX_REVISION_ITEMS,
            "items": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "The item restated in ONE plain sentence, present tense, at most 200 characters. A rule is written as a rule ('Lily never ...')."},
                    "kind": {"type": "string", "enum": ["rule", "fix_now"], "description": "rule: must stay true everywhere in the story. fix_now: a one-time correction of specific moments. When unsure: fix_now."},
                    "in_scope": {"type": "boolean", "description": "true only if it can be done by rewriting what characters SAY or DO, what they KNOW, or how they REACT inside clips that already exist."},
                    "why_out_of_scope": {"type": "string", "description": "When in_scope is false: one short sentence saying why, and that it needs a new plan. Otherwise an empty string."},
                    "replaces_rule_ids": {"type": "array", "maxItems": 4, "items": {"type": "string"}, "description": "Ids of existing standing rules this item contradicts or makes obsolete. Usually none."},
                    "probe": {"type": "string", "description": "ONE yes/no question that can be asked of a single clip on its own, for example 'Does anything said or done here only make sense if X?'. It tests what a line TAKES FOR GRANTED, not only what it states. Empty when the item is out of scope."},
                    "tells": {"type": "array", "maxItems": 6, "items": {"type": "string"}, "description": "Short, GENERIC ways a line can fail the probe INDIRECTLY (kinds of words, kinds of reference). No clip numbers. Empty when out of scope."},
                    "stops_when": {"type": "string", "description": "When the item stops applying, in plain words, from the note or the premise. 'never' when it does not stop. If the premise requires, at some point, the very thing the item forbids (a reveal, an ending), the item stops there. Empty when out of scope."}
                },
                "required": ["text", "kind", "in_scope", "why_out_of_scope", "replaces_rule_ids", "probe", "tells", "stops_when"],
                "additionalProperties": False
            }
        }
    },
    "required": ["items"],
    "additionalProperties": False
}


def _scan_schema(lo: int, hi: int) -> dict:
    """The scan's answer for clips `lo` to `hi`: exactly one entry per clip, each with a score. A model that only has to LIST the
    clips that fail skips the ones that fail by implication; one that has to score every clip, and quote the words, does not."""
    n = hi - lo + 1
    return {
        "type": "object",
        "properties": {
            "clips": {
                "type": "array", "minItems": n, "maxItems": n,
                "items": {
                    "type": "object",
                    "properties": {
                        "clip": {"type": "integer"},
                        "score": {"type": "integer", "enum": [0, 1, 2, 3], "description": "0 passes the probe; 1 maybe fails; 2 probably fails; 3 certainly fails."},
                        "quote": {"type": "string", "description": "The exact words (or the action) in the clip that fail the probe. Empty when the score is 0."},
                        "why": {"type": "string", "description": "One short sentence: what the quoted words take for granted. Empty when the score is 0."}
                    },
                    "required": ["clip", "score", "quote", "why"],
                    "additionalProperties": False
                }
            }
        },
        "required": ["clips"],
        "additionalProperties": False
    }


MAX_HINT_CHARS = 400


def _never_stops(stops_when: str | None) -> bool:
    """True when an item has no end point ("never", or nothing said)."""
    s = (stops_when or "").strip().lower()
    return not s or s.startswith("never") or s.startswith("does not stop") or s.startswith("it does not stop")


def item_instruction(item: dict) -> str:
    """An item as one instruction for the rewrite: its text, and where it stops applying when it does."""
    text = str(item.get("text") or "").strip()
    stop = " ".join(str(item.get("stops_when") or "").split())
    return text if _never_stops(stop) else f"{text} (This stops applying when: {stop.rstrip('.')}.)"


def rules_block(rules: list[dict] | None) -> str:
    """The standing rules as text for a prompt; "" when there are none. A rule that ends somewhere says where, so a later
    stage is not told 'never' about something the story needs (the reveal the rule was only meant to delay)."""
    texts = [item_instruction(r) for r in (rules or []) if str(r.get("text") or "").strip()]
    if not texts:
        return ""
    return ("\n\nSTORY RULES (the user added these after reading the plan. They are true in this story, so every line, "
            "action and expression must obey them for as long as each one applies):\n" + "\n".join(f"- {t}" for t in texts))


def topic_with_rules(topic: str, rules: list[dict] | None) -> str:
    """The premise with the standing rules appended: the one place every later stage already reads, so a rule reaches the
    replanner, the continuation planner and every clip writer without touching their prompts."""
    return (topic or "") + rules_block(rules)


def clean_rules(rules: list | None) -> list[dict]:
    """Rules as [{"id", "text"}], trimmed, de-duplicated, with an id each; raises ValueError if there are too many."""
    out, seen = [], set()
    for r in rules or []:
        raw = r.get("text") if isinstance(r, dict) else r
        text = " ".join(str(raw or "").split())[:MAX_RULE_CHARS]
        if not text or text.lower() in seen:
            continue
        seen.add(text.lower())
        rid = str(r.get("id") or "").strip() if isinstance(r, dict) else ""
        hint = " ".join(str(r.get("hint") or "").split())[:MAX_HINT_CHARS] if isinstance(r, dict) else ""
        probe = " ".join(str(r.get("probe") or "").split())[:MAX_PROBE_CHARS] if isinstance(r, dict) else ""
        stop = " ".join(str(r.get("stops_when") or "").split())[:MAX_STOP_CHARS] if isinstance(r, dict) else ""
        stop = "" if _never_stops(stop) else stop
        out.append({"id": rid, "text": text, **({"hint": hint} if hint else {}), **({"probe": probe} if probe else {}),
                    **({"stops_when": stop} if stop else {})})
    used = {r["id"] for r in out if r["id"]}
    counter = 0
    for r in out:
        if not r["id"]:
            counter += 1
            while f"r{counter}" in used:
                counter += 1
            r["id"] = f"r{counter}"
            used.add(r["id"])
    if len(out) > MAX_PLAN_RULES:
        raise ValueError(f"at most {MAX_PLAN_RULES} standing rules fit; there are {len(out)}. Delete or merge some first.")
    return out


def _scan_windows(total_clips: int) -> list[tuple[int, int]]:
    """The stretches of the plan one scan call reads: the whole plan when it fits SCAN_WINDOW clips, else equal chunks (61 clips
    are two windows of 31, not 60 and 1)."""
    if total_clips <= 0:
        return []
    count = -(-total_clips // SCAN_WINDOW)
    size = -(-total_clips // count)
    return [(lo, min(lo + size - 1, total_clips)) for lo in range(1, total_clips + 1, size)]


def _clip_digest(beat: dict, n: int) -> str:
    lines = " / ".join(f'{t.get("speaker")}: "{t.get("line")}"' for t in _beat_lines(beat)) or "(no spoken words)"
    cast = ", ".join(beat.get("present_characters") or []) or "nobody"
    return (f"Clip {n} [{beat.get('delivery_mode')}] at {beat.get('location_id')}; in the scene: {cast}\n"
            f"  summary: {beat.get('summary')}\n  words: {lines}")


def _story_gist(acts: list[dict] | None) -> str:
    rows = [f"Act {a.get('act_number')} (clips {a.get('start_clip')}-{a.get('end_clip')}): {(a.get('summary') or '').strip()[:300]}"
            for a in acts or [] if (a.get("summary") or "").strip() and a.get("summary") != "The whole story."]
    return "THE STORY IN BRIEF:\n" + "\n".join(rows) + "\n" if rows else ""


def split_revision_note(note: str, rules: list[dict] | None, bible: dict, total_clips: int, premise: str = "") -> list[dict]:
    """Split a note into separate items: [{"text", "kind", "in_scope", "why_out_of_scope", "replaces_rule_ids", "probe", "tells",
    "stops_when"}]. Runs on the cheap model, which reads the premise so it can see where an item has to stop. Raises ValueError
    when the note is empty or too long."""
    note = (note or "").strip()
    if not note:
        raise ValueError("write what you want changed")
    if len(note) > MAX_NOTE_CHARS:
        raise ValueError(f"the note is too long ({len(note)} characters, at most {MAX_NOTE_CHARS}): split it into shorter notes")
    system = (
        f"You help a user revise the PLAN of a short drama that has already been written: {total_clips} clips of 5 seconds, each with "
        "a summary and spoken lines. The user wrote a note after reading the plan. Split the note into separate items, one for each "
        "distinct change, and for each decide:\n"
        "- kind: 'rule' when it states something that must stay true everywhere in the story (never / always / from now on, for example "
        "'Lily never recognises Ethan as Jack'); 'fix_now' when it corrects specific moments once. When unsure, 'fix_now'.\n"
        "- text: the item in ONE plain sentence, present tense, at most 200 characters. Keep the user's meaning exactly; add nothing they did not ask for.\n"
        "- in_scope: true ONLY if it can be done by rewriting what characters SAY or DO, what they KNOW, or how they REACT inside the "
        "clips that already exist. It is OUT of scope if it asks to add, remove, merge, split or reorder clips; change the length; add or "
        "remove a place or move a clip to another place; add or remove a character or change who is in a clip; change the genre or the "
        "ending as a whole; or change how the film looks. For an out-of-scope item, say in one short sentence why and that it needs a new plan.\n"
        "- replaces_rule_ids: ids of existing standing rules that this item contradicts or makes obsolete (usually none).\n"
        "- probe: ONE yes/no question that can be asked of a single clip on its own, for example 'Does anything said or done here only "
        "make sense if X?', where X is the opposite of what the item wants. It must test what a line TAKES FOR GRANTED (a line can "
        "break an item without stating it), not only what it states. Leave it empty for an out-of-scope item.\n"
        "- tells: up to 6 short, GENERIC ways a line can fail the probe INDIRECTLY (kinds of words, kinds of reference). No clip "
        "numbers and no quotes from the plan; you have not been shown the clips. Empty for an out-of-scope item.\n"
        "- stops_when: when the item stops applying, in plain words, taken from the note or from the premise; 'never' when it does not "
        "stop. If the premise REQUIRES, at some point, the very thing the item forbids (an ending, a reveal), the item stops at that "
        "point, so say so. Empty for an out-of-scope item."
    )
    cast = ", ".join(c["name"] for c in bible.get("characters", []))
    places = ", ".join(l["id"] for l in bible.get("locations", []))
    existing = "\n".join(f"{r['id']}: {r['text']}" for r in rules or []) or "(none)"
    story = f"The premise (what the story must contain):\n{(premise or '').strip()[:MAX_PREMISE_CHARS]}\n\n" if (premise or "").strip() else ""
    user = f"{story}Characters: {cast}\nPlaces: {places}\nExisting standing rules:\n{existing}\n\nThe user's note:\n{note}"
    def ask(**kw):
        return _ask_openai_json(system, user, "narrated_revision_split", SPLIT_SCHEMA, model=app.OPENAI_CLIP_MODEL,
                                max_completion_tokens=REVISION_SPLIT_MAX_OUTPUT, **kw)
    try:
        answer = ask()
    except app.OpenAIOutputCut:      # it thought past the ceiling: once more, thinking less, instead of failing the whole revision
        answer = ask(reasoning_effort="low")
    known = {r["id"] for r in rules or []}
    items = []
    for it in (answer or {}).get("items") or []:
        text = " ".join(str(it.get("text") or "").split())[:MAX_RULE_CHARS]
        if not text:
            continue
        in_scope = bool(it.get("in_scope"))
        items.append({
            "text": text,
            "kind": "rule" if it.get("kind") == "rule" else "fix_now",
            "in_scope": in_scope,
            "why_out_of_scope": "" if in_scope else (" ".join(str(it.get("why_out_of_scope") or "").split())
                                                     or "This changes the shape of the plan, which needs a new plan."),
            "replaces_rule_ids": [r for r in (it.get("replaces_rule_ids") or []) if r in known] if it.get("kind") == "rule" else [],
            "probe": " ".join(str(it.get("probe") or "").split())[:MAX_PROBE_CHARS] if in_scope else "",
            "tells": [" ".join(str(t).split())[:120] for t in (it.get("tells") or []) if str(t).strip()][:6] if in_scope else [],
            "stops_when": ("" if _never_stops(it.get("stops_when")) else " ".join(str(it.get("stops_when")).split())[:MAX_STOP_CHARS]) if in_scope else "",
        })
    return items[:MAX_REVISION_ITEMS]


def _words_of(beat: dict) -> str:
    return " / ".join(f'{t.get("speaker")}: "{t.get("line")}"' for t in _beat_lines(beat)) or "(no words)"


def _scan_digest(beats: list[dict], lo: int, hi: int) -> str:
    """One line per clip: its number, place, what happens and what is said. All the scan reads."""
    return "\n".join(f"{n} [{beats[n - 1].get('location_id')}] {beats[n - 1].get('summary')} | {_words_of(beats[n - 1])}"
                     for n in range(lo, hi + 1))


def _earlier_digest(beats: list[dict], lo: int) -> str:
    """What happened before a window, short: context for a later window (who has met whom, what was offered)."""
    return "\n".join(f"{n} {str(beats[n - 1].get('summary') or '')[:100]} | {_words_of(beats[n - 1])[:100]}"
                     for n in range(max(1, lo - SCAN_EARLIER_CLIPS), lo))


def _default_probe(text: str) -> str:
    return f"Does anything said or done here only make sense if this were not true: {text}?"


def _tells_text(tells) -> str:
    return "; ".join(str(t) for t in tells if str(t).strip()) if isinstance(tells, (list, tuple)) else str(tells or "")


def _scan_prompt(item: dict, beats: list[dict], lo: int, hi: int) -> tuple[str, str]:
    system = ("You check a short drama's plan against ONE rule, using the PROBE as the test. Go through every clip. Score: 0 passes; "
              "1 maybe fails; 2 probably fails; 3 certainly fails. A clip fails when something said or done in it only makes sense if the "
              "rule were broken, including indirectly (see TELLS). Think about what each line takes for granted. Clips after the rule "
              "stops applying score 0. Quote the exact failing words. Return exactly one entry per clip, numbered "
              f"{lo} to {hi}, using only those numbers.")
    stop = " ".join(str(item.get("stops_when") or "").split())
    parts = [f"RULE: {item['text']}", f"PROBE: {item.get('probe') or _default_probe(item['text'])}",
             f"TELLS: {_tells_text(item.get('tells')) or '(none given)'}", f"RULE STOPS: {'never' if _never_stops(stop) else stop}", ""]
    if lo > 1:
        parts += [f"EARLIER CLIPS (context only, do not score them):\n{_earlier_digest(beats, lo)}", ""]
    parts.append(f"THE CLIPS TO SCORE ({lo}-{hi}), one line per clip:\n{_scan_digest(beats, lo, hi)}")
    return system, "\n".join(parts)


def _scan_once(item: dict, beats: list[dict], lo: int, hi: int, name: str) -> dict[int, dict]:
    """One scan of clips `lo` to `hi` for one item: {clip: entry} for the clips scoring MAYBE_SCORE or more. The model must score
    EVERY clip and quote the failing words; a clip it leaves out is asked for once more, and one it never scores is printed,
    not guessed."""
    wanted = set(range(lo, hi + 1))
    judged: set[int] = set()
    found: dict[int, dict] = {}
    for _attempt in (1, 2):
        if judged >= wanted:
            break
        system, user = _scan_prompt(item, beats, lo, hi)
        answer = _ask_openai_json(system, user, name, _scan_schema(lo, hi), model=app.OPENAI_CLIP_MODEL,
                                  max_completion_tokens=SCAN_MAX_OUTPUT, reasoning_effort=SCAN_REASONING)
        for c in (answer or {}).get("clips") or []:
            try:
                n, score = int(c.get("clip")), c.get("score")
            except (TypeError, ValueError):
                continue
            if n not in wanted or n in judged or score not in (0, 1, 2, 3):
                continue
            judged.add(n)
            if score >= MAYBE_SCORE:
                why = " ".join(str(c.get("why") or "").split())[:240]
                quote = " ".join(str(c.get("quote") or "").split())[:240]
                found[n] = {"clip": n, "score": score, "reason": why, "quote": quote,
                            "change": f'Remove what breaks the request: "{quote}". {why}'.strip()[:480]}
    missing = sorted(wanted - judged)
    if missing:
        print(f"  the scan gave no score for clip(s) {missing[:8]}{'...' if len(missing) > 8 else ''}; they are not in the list", flush=True)
    return found


def scan_revision_clips(items: list[dict], beats: list[dict], name: str = "narrated_revision_scan") -> list[dict]:
    """Score every clip of the plan against each item: [{"clip", "score", "reason", "quote", "change"}] for the clips that score
    MAYBE_SCORE or more, in clip order. An item is {"text", "probe", "tells", "stops_when"}. The cheap model, at high reasoning
    effort, reads the whole plan in one call (SCAN_WINDOW clips; a longer plan in equal windows, each shown the earlier clips).
    Each window is scanned SCAN_PASSES times at once and the passes are merged: a clip keeps its highest score over the passes and
    over the items. A pass that fails is skipped as long as another succeeds."""
    import contextvars
    from concurrent.futures import ThreadPoolExecutor
    found: dict[int, dict] = {}
    passes = max(1, SCAN_PASSES)
    for item in items:
        for lo, hi in _scan_windows(len(beats)):
            if passes == 1:
                results: list = [_scan_once(item, beats, lo, hi, name)]
            else:
                with ThreadPoolExecutor(max_workers=passes) as pool:
                    # each pass runs in a copy of this thread's context, so its OpenAI call is still recorded under the job's trace
                    futures = [pool.submit(contextvars.copy_context().run, _scan_once, item, beats, lo, hi, name) for _ in range(passes)]
                    results = []
                    for f in futures:
                        try:
                            results.append(f.result())
                        except Exception as e:
                            results.append(e)
                if all(isinstance(r, Exception) for r in results):
                    raise results[0]
                results = [r for r in results if not isinstance(r, Exception)]
            for res in results:
                for n, entry in res.items():
                    if n not in found or entry["score"] > found[n]["score"]:
                        found[n] = entry
    return [found[n] for n in sorted(found)]


def propose_plan_revision(note: str, rules: list[dict] | None, beats: list[dict], acts: list[dict] | None, bible: dict,
                          premise: str = "") -> dict:
    """Step one of a revision, nothing is changed: split the note into items with a probe each, and scan the plan for the clips
    they touch. Returns {"items", "rules_new", "rules_new_hints", "rules_new_meta", "replaces", "clips", "blocked"}; `blocked` says why
    the rules cannot be saved (too many). `acts` is kept for the callers; the scan does not need it."""
    rules = clean_rules(rules)
    items = split_revision_note(note, rules, bible, len(beats), premise)
    in_scope = [i for i in items if i["in_scope"]]
    rule_items = [i for i in in_scope if i["kind"] == "rule"]
    new_rules = [i["text"] for i in rule_items]
    new_hints = [_tells_text(i.get("tells"))[:MAX_HINT_CHARS] for i in rule_items]
    new_meta = [{"probe": i.get("probe", ""), "stops_when": i.get("stops_when", "")} for i in rule_items]
    replaces = sorted({rid for i in rule_items for rid in i["replaces_rule_ids"]})
    final_count = len([r for r in rules if r["id"] not in replaces]) + len(new_rules)
    blocked = (f"Saving these would leave {final_count} standing rules; at most {MAX_PLAN_RULES} fit. Delete or merge some rules first."
               if final_count > MAX_PLAN_RULES else None)
    clips = scan_revision_clips(in_scope, beats) if in_scope else []
    return {"items": items, "rules_new": new_rules, "rules_new_hints": new_hints, "rules_new_meta": new_meta,
            "replaces": replaces, "clips": clips, "blocked": blocked}


REWRITE_SCHEMA_NAME = "narrated_revision_rewrite"


def _rewrite_schema(speakers: list[str], n: int) -> dict:
    speaker = {"type": "string", "enum": speakers} if speakers else {"type": "string"}
    return {
        "type": "object",
        "properties": {
            "beats": {
                "type": "array", "maxItems": n,
                "items": {
                    "type": "object",
                    "properties": {
                        "clip_number": {"type": "integer"},
                        "summary": {"type": "string", "description": "What happens, in plain literal words: who does what to whom, what a camera could film. No metaphors. One or two sentences."},
                        "turn": {"type": "string", "description": "ONE sentence: what is different after this clip."},
                        "audio_lines": {
                            "type": "array", "maxItems": MAX_VOICE_REFS,
                            "items": {"type": "object",
                                      "properties": {"speaker": speaker, "line": {"type": "string"}},
                                      "required": ["speaker", "line"], "additionalProperties": False}
                        }
                    },
                    "required": ["clip_number", "summary", "turn", "audio_lines"],
                    "additionalProperties": False
                }
            }
        },
        "required": ["beats"],
        "additionalProperties": False
    }


def _rewrite_clip_block(n: int, beats: list[dict], hint: str, delivery: dict | None, feedback: list[str] | None) -> str:
    b = beats[n - 1]
    rows = [f"=== CLIP {n} - REWRITE THIS ONE ===", _clip_digest(b, n), f"What must change: {hint or 'follow the request'}"]
    facts = [f for f in (delivery or {}).get("facts") or [] if int(f.get("deliver_at") or 0) == n and f.get("key_terms")]
    for f in facts:
        rows.append(f"Must still be said here (unless the request removes it), by {f.get('owner')}, containing {', '.join(f['key_terms'])}: {f.get('text')}")
    secret = sorted(_terms_still_secret(beats, n - 1))
    if secret:
        rows.append("The audience has NOT been told these yet; do not say them: " + ", ".join(secret))
    if feedback:
        rows.append("YOUR PREVIOUS ATTEMPT BROKE THESE RULES, fix them: " + " | ".join(feedback))
    ctx = [k for k in (n - 2, n - 1, n + 1) if 1 <= k <= len(beats)]
    rows.append("Neighbouring clips, context only, do not rewrite:\n" + "\n".join(_clip_digest(beats[k - 1], k) for k in ctx))
    return "\n".join(rows)


def rewrite_revision_clips(selected: dict[int, str], instructions: list[str], rules: list[dict] | None, beats: list[dict],
                           bible: dict, delivery: dict | None, acts: list[dict] | None = None,
                           feedback: dict[int, list[str]] | None = None, retry: bool = False) -> dict[int, dict]:
    """Rewrite ONLY the selected clips ({clip: what must change}); returns {clip: {"summary", "turn", "audio_lines"}} for
    the clips the model returned. The story model writes the words (the retry, after a broken rule, runs on the cheap one).
    A clip's place, cast and kind are never in the answer, so they cannot change."""
    protagonist = (bible.get("pov_protagonist") or "").strip()
    speakers = [c["name"] for c in bible.get("characters", [])]
    system = (
        "You revise specific clips of a short drama's plan after the user asked for a change. Rewrite ONLY the clips marked REWRITE "
        "THIS ONE; every other clip stays exactly as it is, so what you write must fit it.\n"
        "For each clip return: summary (plain and literal: who does what to whom, what a camera could film; no metaphors), turn (one "
        "sentence: what is different after the clip) and audio_lines (the exact words spoken, in order).\n"
        "RULES:\n"
        f"   - A clip keeps its place, the people in it and its kind: a dialogue clip has 1 to {MAX_VOICE_REFS} lines by the people in it; a voiceover "
        f"clip has exactly ONE line by {protagonist}, spoken as their own first-person thought; a shock_action clip has NO lines (an empty list).\n"
        f"   - Together a clip's lines are {MIN_WORDS} to {MAX_WORDS} words: it is only {CLIP_SECONDS} seconds long.\n"
        "   - Keep saying whatever the clip must still say (listed under it) unless the request itself removes it.\n"
        "   - Never say anything the audience has not been told by that clip (listed under it).\n"
        "   - The lines must follow from the clip before and lead into the clip after.\n"
        "   - Obey every standing rule for as long as it applies: do not write anything that contradicts one, and do not leave something "
        "in the clip that the request says must no longer happen.\n"
        "   - When the request is about what a character knows or believes, write that character as someone who truly does not know: "
        "nothing they say or do may take it for granted (watch for words like again, back, still, or mentions of things only the other "
        "identity did). Give them lines a person in their position would really say.\n"
        f"{_plain_language_rule()}"
    )
    chosen = sorted(selected)
    rewrites: dict[int, dict] = {}
    for g in range(0, len(chosen), REVISION_REWRITE_GROUP):
        group = chosen[g: g + REVISION_REWRITE_GROUP]
        user = "\n".join([
            "THE REQUEST:\n" + "\n".join(f"- {t}" for t in instructions),
            ("STANDING RULES:\n" + "\n".join(f"- {r['text']}" for r in rules)) if rules else "",
            f"The narrator (all voiceover is their first person): {protagonist}",
            _story_gist(acts),
            "\n\n".join(_rewrite_clip_block(n, beats, selected.get(n, ""), delivery, (feedback or {}).get(n)) for n in group),
            f"\nReturn exactly {len(group)} beats, with clip_number {', '.join(map(str, group))}.",
        ])
        answer = _ask_planner(system, user, REWRITE_SCHEMA_NAME, _rewrite_schema(speakers, len(group)),
                              model=_retry_model(1) if retry else None, ceiling=_plan_ceiling(len(group), 1200, 12000))
        for b in (answer or {}).get("beats") or []:
            try:
                n = int(b.get("clip_number"))
            except (TypeError, ValueError):
                continue
            if n in group and n not in rewrites:
                rewrites[n] = {"summary": " ".join(str(b.get("summary") or "").split()), "turn": " ".join(str(b.get("turn") or "").split()),
                               "audio_lines": [{"speaker": t.get("speaker"), "line": " ".join(str(t.get("line") or "").split())}
                                               for t in b.get("audio_lines") or [] if str(t.get("line") or "").strip()]}
    return rewrites


def _put_rewrite(beat: dict, rw: dict, bible: dict) -> dict:
    """A copy of `beat` with a rewrite put in: the summary, the turn, the words. The place, the cast and the kind of clip stay."""
    out = copy.deepcopy(beat)
    by_lower = {c["name"].lower(): c["name"] for c in bible.get("characters", [])}
    if rw.get("summary"):
        out["summary"] = rw["summary"]
        if "action" in out:        # the dashboard writes an edited description into `action`; a stale one would contradict this
            out["action"] = rw["summary"]
    if rw.get("turn") and "turn" in out:
        out["turn"] = rw["turn"]
    if out.get("delivery_mode") == "shock_action":
        out["audio_lines"] = []
    else:
        out["audio_lines"] = [{"speaker": by_lower.get(str(t.get("speaker") or "").lower(), t.get("speaker")), "line": t["line"]}
                              for t in rw.get("audio_lines") or []]
    out["speech_budget"] = _spoken_words(out["audio_lines"])
    return out


def _runs(numbers: list[int]) -> list[tuple[int, int]]:
    """[3, 4, 5, 9] -> [(3, 5), (9, 9)]"""
    runs: list[list[int]] = []
    for n in sorted(set(numbers)):
        if runs and n == runs[-1][1] + 1:
            runs[-1][1] = n
        else:
            runs.append([n, n])
    return [(a, b) for a, b in runs]


def _snapshot(beat: dict) -> dict:
    return {"summary": beat.get("summary"), "lines": [{"speaker": t.get("speaker"), "line": t.get("line")} for t in _beat_lines(beat)]}


def apply_plan_revision(selected: dict[int, str], instructions: list[str], rules: list[dict] | None, beats: list[dict],
                        bible: dict, delivery: dict | None, acts: list[dict] | None = None) -> dict:
    """Step two: rewrite the chosen clips, check them, and give back the new beats. Nothing else in the plan moves.
    Returns {"beats", "changed": [{"clip", "before", "after"}], "unresolved": [{"clip", "problems"}], "notes"}.

    A clip whose rewrite breaks a hard rule gets ONE retry on the cheap model; if it still does, the old clip is kept and the
    clip is reported, so a bad rewrite can never replace a good clip."""
    before = copy.deepcopy(beats)
    notes: list[str] = []
    unresolved: dict[int, list[str]] = {}
    old_hard = set(_hard_problems(_check_beats(before, bible)))
    rewrites = rewrite_revision_clips(selected, instructions, rules, before, bible, delivery, acts)
    for n in selected:
        if n not in rewrites or not rewrites[n].get("summary"):
            unresolved[n] = ["the model did not return a rewrite for this clip, so it is unchanged"]
    new = copy.deepcopy(before)
    for n, rw in rewrites.items():
        if n not in unresolved:
            new[n - 1] = _put_rewrite(before[n - 1], rw, bible)
    for note in _repair_beats(new, bible):
        notes.append(f"repaired {note}")

    def broken() -> dict[int, list[str]]:
        fresh = [p for p in _hard_problems(_check_beats(new, bible)) if p not in old_hard]
        if not fresh:
            return {}
        flagged = _flagged_clips(fresh)
        mine = [n for n in rewrites if n not in unresolved]
        return {n: [p for p in fresh if re.search(rf"\b(?:clip|beat)s?\s+{n}\b", p, re.I)] or fresh
                for n in (sorted(flagged & set(mine)) if flagged else mine)}

    bad = broken()
    if bad:
        again = rewrite_revision_clips({n: selected[n] for n in bad}, instructions, rules, before, bible, delivery, acts,
                                       feedback=bad, retry=True)
        for n in bad:
            new[n - 1] = _put_rewrite(before[n - 1], again[n], bible) if n in again and again[n].get("summary") else before[n - 1]
        _repair_beats(new, bible)
        for n, probs in broken().items():
            unresolved[n] = probs
            new[n - 1] = copy.deepcopy(before[n - 1])     # keep the clip that was fine
    changed_now = [n for n in selected if n not in unresolved]
    # a fact the old clip said and the new one no longer does: one small call for that clip, never a sweep over the whole plan
    if delivery and delivery.get("facts"):
        scoped = {**delivery, "facts": [f for f in delivery["facts"]
                                        if int(f.get("deliver_at") or 0) in changed_now
                                        and _terms_covered(f.get("key_terms") or [], _beat_text(before[int(f["deliver_at"]) - 1]))]}
        for note in _repair_missing_facts(new, bible, scoped, 1, budget=_RepairBudget(), prior_beats=None):
            notes.append(note)
    # plain language for every changed run (one small call each); guards keep the speaker, the budget and the reveal order
    def reserved_for(clip: int) -> set[str]:
        out: set[str] = set()
        for a in acts or []:
            if int(a.get("start_clip") or 0) > clip:
                out |= {(t or "").strip().lower() for t in (a.get("reveals") or []) if (t or "").strip()}
        return out
    for lo, hi in _runs(changed_now):
        try:
            plain_pass_beats(new[lo - 1: hi], bible, delivery, start_clip=lo, prior_beats=new[: lo - 1], reserved_for=reserved_for)
        except Exception as e:  # a review must never break a revision
            notes.append(f"plain-language review of clips {lo}-{hi} skipped: {e}")
    changed = []
    for n in changed_now:
        b4, af = _snapshot(before[n - 1]), _snapshot(new[n - 1])
        if b4 != af:
            changed.append({"clip": n, "before": b4, "after": af})
    return {"beats": new, "changed": changed, "unresolved": [{"clip": n, "problems": p} for n, p in sorted(unresolved.items())], "notes": notes}


def verify_plan_revision(rules: list[dict] | None, beats: list[dict], acts: list[dict] | None = None) -> list[dict]:
    """Clips that still fail a standing rule after a revision: [{"clip", "reason", "change", "quote"}]. The same scan that found the
    clips, with each rule's own probe, tells and stop point (a rule saved without a probe gets a plain one). Only clips the
    scan scores PICK_SCORE or more are listed. Reported to the user, never fixed automatically (no loop). `acts` is kept for the
    callers."""
    if not rules:
        return []
    items = [{"text": r["text"], "probe": r.get("probe") or "", "tells": r.get("hint", ""), "stops_when": r.get("stops_when", "")} for r in rules]
    return [{k: c[k] for k in ("clip", "reason", "change", "quote")}
            for c in scan_revision_clips(items, beats, name="narrated_revision_verify") if c["score"] >= PICK_SCORE]


# ---------------------------------------------------------------------------
# Supporting cast: find the people the plan shows but never cast, and add them
# ---------------------------------------------------------------------------
# A parent "watching silently" at a dinner who is not in the scene bible is never drawn from a reference: the clip writer is told to
# leave uncast people out, and if the video model paints her anyway she is a different stranger in every clip. These functions find
# such people (the cheap model, one read of the plan), write looks for the ones the user keeps, add them to the bible and put them in
# the on-screen list of the clips they belong in. The portraits themselves are made at render time from the bible, like everyone's.
def _clip_ranges(clips: list[int]) -> str:
    """[11, 12, 13, 15] -> '11-13, 15'"""
    return ", ".join(str(a) if a == b else f"{a}-{b}" for a, b in _runs(clips))


def _cast_gap_schema() -> dict:
    return {
        "type": "object",
        "properties": {
            "people": {
                "type": "array", "maxItems": 10,
                "items": {
                    "type": "object",
                    "properties": {
                        "label": {"type": "string", "description": "A short plain label, the SAME for the same person in every clip: 'Mike's mother', 'the waiter'."},
                        "suggested_name": {"type": "string", "description": "A first and last name that fits the story. A relative shares the family name of the person they are related to. Never the name of anyone in the cast."},
                        "relation": {"type": "string", "description": "Who they are in a few words: 'Mike's mother'."},
                        "clips": {"type": "array", "items": {"type": "integer"}, "description": "EVERY clip number in which this person is physically on screen with a part in the shot."},
                        "evidence": {"type": "string", "description": "One clip number and a short quote from the plan that puts them on screen."},
                        "speaks": {"type": "boolean", "description": "true only when the plan gives them spoken words."}
                    },
                    "required": ["label", "suggested_name", "relation", "clips", "evidence", "speaks"],
                    "additionalProperties": False
                }
            }
        },
        "required": ["people"],
        "additionalProperties": False
    }


def _gap_digest(beats: list[dict], lo: int, hi: int) -> str:
    return "\n".join(f"{n} [{beats[n - 1].get('location_id')}] cast on screen: {', '.join(beats[n - 1].get('present_characters') or []) or 'nobody'}"
                     f" | {beats[n - 1].get('summary')} | {_words_of(beats[n - 1])}" for n in range(lo, hi + 1))


def find_cast_gaps(beats: list[dict], bible: dict) -> list[dict]:
    """People the plan puts on screen who are not in the cast: [{"label", "suggested_name", "relation", "clips", "evidence",
    "speaks"}], in order of first clip. One read of the plan on the cheap model at high effort (a longer plan in windows, each
    shown the earlier clips; the same person in two windows is merged). Raises on a model error: callers decide what that costs."""
    cast = [c.get("name", "") for c in bible.get("characters", [])]
    cast_lower = {n.lower() for n in cast if n}
    cast_lines = "\n".join(f"- {c.get('name')} ({c.get('role') or 'cast'})" + (f": {c['relationships']}" if c.get("relationships") else "")
                           for c in bible.get("characters", []))
    system = (
        "You check a short drama's plan for people who must be SEEN on screen but are not in the cast. Only cast members get a portrait "
        "and a stable face. Go through every clip. A person counts when they are physically on screen with a part in the shot: they act, "
        "react, mouth words, are looked at or addressed while visible, or the plan describes them as present (relatives at a dinner "
        "table, a waiter serving). A person who is only talked about, heard on a phone, or named in a line does NOT count, and neither "
        "does anyone in the cast. A group described as present ('his silent family') counts: list each distinct person the clips need "
        "(a mother, a father...); when the plan does not say who is in the group, list the FEWEST people that make the group read as what the plan says (usually two or three, at most four in all), because every extra face in a shot is harder to keep consistent. Use the same label for the same person in every clip, and give EVERY clip where each is on screen. "
        "Return an empty list when nobody is missing."
    )
    merged: dict[str, dict] = {}
    for lo, hi in _scan_windows(len(beats)):
        parts = [f"THE CAST (only these people have a portrait):\n{cast_lines}", ""]
        if lo > 1:
            parts += [f"EARLIER CLIPS (context only):\n{_earlier_digest(beats, lo)}", ""]
        parts.append(f"THE CLIPS TO CHECK ({lo}-{hi}), one line per clip:\n{_gap_digest(beats, lo, hi)}")
        answer = _ask_openai_json(system, "\n".join(parts), "narrated_cast_gap", _cast_gap_schema(), model=app.OPENAI_CLIP_MODEL,
                                  max_completion_tokens=CAST_GAP_MAX_OUTPUT, reasoning_effort=CAST_GAP_REASONING)
        for p in (answer or {}).get("people") or []:
            label = " ".join(str(p.get("label") or "").split())[:60]
            name = " ".join(str(p.get("suggested_name") or "").split())[:MAX_CAST_NAME_CHARS] or label
            clips = sorted({int(n) for n in p.get("clips") or [] if isinstance(n, int) and lo <= n <= hi})
            if not label or not clips or label.lower() in cast_lower or name.lower() in cast_lower:
                continue
            row = merged.setdefault(label.lower(), {"label": label, "suggested_name": name, "relation": "", "clips": [], "evidence": "", "speaks": False})
            row["clips"] = sorted(set(row["clips"]) | set(clips))
            row["relation"] = row["relation"] or " ".join(str(p.get("relation") or "").split())[:80]
            row["evidence"] = row["evidence"] or " ".join(str(p.get("evidence") or "").split())[:200]
            row["speaks"] = row["speaks"] or bool(p.get("speaks"))
    return sorted(merged.values(), key=lambda r: r["clips"][0])


def _supporting_schema(names: list[str]) -> dict:
    short = {"type": "string", "description": "ONE short plain phrase."}
    return {
        "type": "object",
        "properties": {
            "characters": {
                "type": "array", "minItems": len(names), "maxItems": len(names),
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "enum": names},
                        "appearance": APPEARANCE_SCHEMA,
                        "voice": {"type": "string", "description": "The INSTRUMENT only: pitch, grain, accent ('warm alto with a soft Yorkshire lilt'). Never how it is played."},
                        "motivation": short,
                        "relationships": short,
                        "speech_style": short
                    },
                    "required": ["name", "appearance", "voice", "motivation", "relationships", "speech_style"],
                    "additionalProperties": False
                }
            }
        },
        "required": ["characters"],
        "additionalProperties": False
    }


def _write_supporting_looks(people: list[dict], bible: dict) -> dict[str, dict]:
    """Cast entries for people being added: {name: {"appearance", "voice", "motivation", "relationships", "speech_style"}}. The
    cheap model writes them knowing every look already in the cast; each is checked with the bible's own checks (every field filled,
    hair colour or style different from everyone else's), and a failed check gets one more try with the reasons."""
    names = [p["name"] for p in people]
    existing = "\n".join(
        f"- {c['name']}: {(c.get('appearance') or {}).get('casting', '')}; hair {(c.get('appearance') or {}).get('hair_color', '')}, "
        f"{(c.get('appearance') or {}).get('hair_style', '')}; {(c.get('appearance') or {}).get('distinguishing_feature', '')}; "
        f"wearing {(c.get('appearance') or {}).get('wardrobe', '')}" for c in bible.get("characters", []))
    system = (
        "You write cast entries for SUPPORTING characters being added to a short drama: people who are on screen for a scene or two. "
        "Each needs a fixed 'appearance' (what the camera sees in every clip) and must be told apart on a dim phone screen from every "
        "character already in the cast: a different hair colour or a different hair style from each of them, and a distinguishing feature "
        "visible on the face or head. Relatives need not look alike. Unless the story says otherwise, default to Western, European or British "
        "demographics. 'voice' is the instrument only (pitch, grain, accent), never how a line is played. 'motivation', 'relationships' "
        "and 'speech_style' are ONE short plain phrase each: these people are not the story."
    )
    who = "\n".join(f"- {p['name']}" + (f" ({p['relation']})" if p.get("relation") else "") for p in people)
    feedback: list[str] = []
    for _attempt in (1, 2):
        user = f"THE CAST ALREADY HERE:\n{existing}\n\nWRITE ENTRIES FOR:\n{who}"
        if feedback:
            user += "\n\nYOUR PREVIOUS ATTEMPT BROKE THESE RULES, fix them: " + " | ".join(feedback)
        answer = _ask_openai_json(system, user, "narrated_cast_looks", _supporting_schema(names), model=app.OPENAI_CLIP_MODEL,
                                  max_completion_tokens=CAST_GAP_MAX_OUTPUT, reasoning_effort=CAST_GAP_REASONING)
        got = {c.get("name"): c for c in (answer or {}).get("characters") or [] if c.get("name") in names}
        trial = copy.deepcopy(bible)
        for n in names:
            c = got.get(n) or {}
            trial.setdefault("characters", []).append({
                "name": n, "is_protagonist": False, "role": SUPPORTING_ROLE, "appearance": c.get("appearance") or {}, "voice": c.get("voice") or "",
                "motivation": c.get("motivation") or "", "relationships": c.get("relationships") or "", "speech_style": c.get("speech_style") or ""})
        feedback = [p for p in _check_scene_bible(trial) if any(n in p for n in names)]
        if len(got) == len(names) and not feedback:
            return {n: got[n] for n in names}
        if len(got) != len(names):
            feedback.append(f"return one entry for each of: {', '.join(names)}")
    raise ValueError("could not write looks that tell the new people apart from the cast: " + " | ".join(feedback[:3]))


def add_supporting_cast(people: list[dict], beats: list[dict], bible: dict) -> dict:
    """Add supporting characters to a plan: [{"name", "relation", "clips"}] -> {"bible", "beats", "added", "notes"} (copies; the
    inputs are untouched). Their looks are written and checked, they join the bible as role 'supporting', and each is put in the
    on-screen list of the clips given. No line is changed. Raises ValueError, changing nothing, for a bad name, a clip the plan does
    not have, a name already in the cast, too many supporting characters, looks that cannot be told apart, or a plan the addition
    would break."""
    total = len(beats)
    existing = {c.get("name", "").lower() for c in bible.get("characters", [])}
    cleaned: list[dict] = []
    seen: set[str] = set()
    for p in people or []:
        name = " ".join(str(p.get("name") or "").split())
        if not name:
            raise ValueError("every person added needs a name")
        if len(name) > MAX_CAST_NAME_CHARS or not name[0].isalpha() or not all(ch.isalpha() or ch in " .'-" for ch in name):
            raise ValueError(f"'{name}' cannot be a character name (letters, spaces, . ' - only, at most {MAX_CAST_NAME_CHARS} characters)")
        if name.lower() in existing:
            raise ValueError(f"'{name}' is already in the cast; choose another name")
        if name.lower() in seen:
            raise ValueError(f"'{name}' is listed twice")
        seen.add(name.lower())
        clips = sorted({int(n) for n in p.get("clips") or [] if isinstance(n, int) and 1 <= n <= total})
        if not clips:
            raise ValueError(f"{name} needs at least one clip to appear in (the plan has clips 1 to {total})")
        cleaned.append({"name": name, "relation": " ".join(str(p.get("relation") or "").split())[:80], "clips": clips})
    if not cleaned:
        raise ValueError("nobody to add")
    have = sum(1 for c in bible.get("characters", []) if _is_supporting(c))
    if have + len(cleaned) > MAX_SUPPORTING:
        raise ValueError(f"at most {MAX_SUPPORTING} supporting characters fit in one film; there are {have} and you are adding {len(cleaned)}. Untick some.")

    looks = _write_supporting_looks(cleaned, bible)
    new_bible = copy.deepcopy(bible)
    for c in cleaned:
        e = looks[c["name"]]
        new_bible.setdefault("characters", []).append({
            "name": c["name"], "is_protagonist": False, "role": SUPPORTING_ROLE, "appearance": e["appearance"], "voice": e["voice"].strip(),
            "motivation": e["motivation"], "relationships": e["relationships"], "speech_style": e["speech_style"]})
    _compile_character_visuals(new_bible)

    old_hard = set(_hard_problems(_check_beats(beats, bible)))
    new_beats = copy.deepcopy(beats)
    notes: list[str] = []
    for c in cleaned:
        for n in c["clips"]:
            present = new_beats[n - 1].get("present_characters")
            if present is None:
                present = new_beats[n - 1]["present_characters"] = []
            if c["name"] in present:
                continue
            if len([x for x in present if x]) >= MAX_ON_SCREEN:
                notes.append(f"clip {n} already has {MAX_ON_SCREEN} people on screen, so {c['name']} was not added there")
                continue
            present.append(c["name"])
    fresh = [p for p in _hard_problems(_check_beats(new_beats, new_bible)) if p not in old_hard]
    if fresh:
        raise ValueError("adding them would break the plan: " + " | ".join(fresh[:3]))
    added = [{"name": c["name"], "relation": c["relation"], "clips": c["clips"],
              "look": next(x for x in new_bible["characters"] if x["name"] == c["name"]).get("look", "")} for c in cleaned]
    return {"bible": new_bible, "beats": new_beats, "added": added, "notes": notes}


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
    """A clip's prop diary as one readable line, for the continuity history. One entry per prop: a diary a
    model once looped on (the same prop 5 times in clip 42) must not be copied into the next clip's prompt,
    where it is exactly what set the next clip off."""
    seen: set = set()
    entries = []
    for p in clip.get("prop_state", []):
        if p.get("prop_id") in seen:
            continue
        seen.add(p.get("prop_id"))
        entries.append(p)
    return "; ".join(
        f"{p.get('prop_id')} ({'held by ' + p['holder'] if p.get('holder') and p['holder'] != 'scene' else 'in the scene'}"
        f"{', in shot' if p.get('in_frame') else ', not in shot'}): {(p.get('state') or '').rstrip('. ')}"
        for p in entries
    )


def _story_so_far(beats: list[dict] | None, clip_index: int, acts: list[dict] | None = None) -> str:
    """The "story so far" block of a clip's prompt: only what exists by this clip, never what is coming.

    The last STORY_SO_FAR_WINDOW beats (this clip's own included) are listed one by one, exactly as before. Anything
    earlier is replaced by one line per FINISHED act (the plan's own summary of it) when the acts are known, plus a note
    for the clips that are not listed. An act summary is written by the planner, who knows the whole story, so it is
    dropped if it names anything the audience has not been told by now. With nothing to omit (a short plan, or the early
    clips of a long one) the text is identical to the old full list."""
    if not beats:
        return ""
    so_far = beats[: clip_index + 1]
    window = STORY_SO_FAR_WINDOW
    first_shown = 0 if not window or len(so_far) <= window else len(so_far) - window

    def line(i: int, b: dict) -> str:
        return f"{i + 1}. [{b.get('location_id')}] [{b.get('delivery_mode', '').upper()}] {b.get('speaker_or_actor')}: {b.get('summary')}"

    shown = "\n".join(line(i, b) for i, b in enumerate(so_far) if i >= first_shown)
    if first_shown == 0:
        return "\nThe story SO FAR (everything that exists; nothing beyond this has happened yet):\n" + shown

    secret = _terms_still_secret(beats, clip_index)
    for a in acts or []:
        if int(a.get("start_clip") or 0) > clip_index + 1:
            secret |= {(t or "").strip().lower() for t in (a.get("reveals") or []) if (t or "").strip()}
    # A FINISHED act is one that ended before this clip. Those with clips that fell out of the window get a line, newest
    # last, and only the last STORY_SO_FAR_ACTS of them: the oldest acts matter least, and without the cap the lines
    # would grow with the length of the story again, only more slowly.
    finished = []
    for a in acts or []:
        try:
            start, end = int(a.get("start_clip") or 0), int(a.get("end_clip") or 0)
        except (TypeError, ValueError):
            continue
        if 1 <= start <= end <= clip_index and start <= first_shown:
            finished.append((start, end, a))
    finished.sort(key=lambda t: t[0])
    earlier = []
    covered = 0   # omitted clips that an act line below accounts for
    for start, end, a in finished[-STORY_SO_FAR_ACTS:] if STORY_SO_FAR_ACTS else finished:
        text = (a.get("summary") or "").strip()
        if text and not any(_mentions(text, term) for term in secret):
            earlier.append(f"Act {a.get('act_number')} '{a.get('title')}' (clips {start}-{end}): {text}")
            covered += max(0, min(end, first_shown) - start + 1)
    parts = [f"\nThe story SO FAR (everything that exists; nothing beyond this has happened yet). The most recent clips are "
             f"listed one by one; clips 1-{first_shown} are summarised or left out, and what lasted from them is in the cast, "
             f"props and what-each-character-knew lists below:"]
    if earlier:
        parts.append("EARLIER, IN BRIEF:\n" + "\n".join(earlier))
    if covered < first_shown:
        parts.append("(Earlier clips not mentioned above are not listed.)")
    parts.append("RECENT CLIPS:\n" + shown)
    return "\n".join(parts)


def _end_state_source(prev_clips: list[dict]) -> tuple[int, dict] | None:
    """(position, clip) of the clip whose ending poses and awareness the NEXT clip has to open on.

    Normally that is simply the latest clip. A wordless establishing shot or an empty frame has no blocking, so its own
    end state says nothing about where anybody stands: with only the latest clip carrying its end state, the clip after
    it would be told "none on screen / nothing noted" and open with no idea where the cast was. So it is the most recent
    clip that had people in it, provided every clip after it is in that same location (a new place means those people
    are not standing there any more, and sending their old poses would be wrong). None when there is nothing usable."""
    if not prev_clips:
        return None
    latest = prev_clips[-1]
    if latest.get("blocking"):
        return len(prev_clips) - 1, latest
    place = latest.get("location_id")
    for pos in range(len(prev_clips) - 2, -1, -1):
        c = prev_clips[pos]
        if c.get("location_id") != place:
            return None
        if c.get("blocking"):
            return pos, c
    return None


def _narrated_chapter_prompt(
    topic: str,
    clip_index: int,
    total_clips: int,
    beat: dict,
    bible: dict,
    prev_clips: list[dict],
    beats: list[dict] | None = None,
    acts: list[dict] | None = None
) -> tuple[str, str]:
    """Builds prompt for writing an individual 5-second narrated drama clip. `acts` (the plan's act breakdown) lets the
    story-so-far block summarise finished acts instead of listing every earlier beat; it is optional."""
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
   If the beat's summary mentions people who are not in the Scene Bible (a crowd, relatives at a table), they stay off screen: do not put them in "shot", "environment" or any action. Describe only the cast.

5. CINEMATIC CAMERA POLICY ([SAME SETUP] vs [ANGLE CUT]):
   CRITICAL: Every shot description MUST explicitly begin with either "[SAME SETUP]" or "[ANGLE CUT]". [SAME SETUP] means the camera starts where the previous clip's camera ended; [ANGLE CUT] means it starts from a new position.
   THE CAMERA IS A PERSON, NOT A TRIPOD: a real operator holding a camera is never frozen. Every shot has a real, motivated camera move during its 5 seconds: a slow push-in, a gentle drift, a small pan or tilt to follow a gesture, a light handheld sway. Keep it SMALL and SMOOTH (a light handheld feel, never a shake, never a whip): faces and lips must stay readable. NEVER write "locked", "static", "frozen" or "holds still" in a shot; the video model takes those words literally and the clip looks like a camera on a tripod.
   (1) THE KIND OF CLIP DECIDES THE COVERAGE:
       A) NARRATION (voiceover) and WORDLESS ACTION clips: the camera moves FREELY, like a person holding it and filming. It walks and tracks with someone, follows a hand or a prop, drifts across the place, pushes in or pulls back. There is no dialogue geometry to protect, so it may start from any side of the place. When such a clip sits INSIDE a conversation scene (the same people are still there), it keeps to the geography already shown (see 3).
       B) DIALOGUE between TWO people: shot / reverse-shot, SPEAKER FIRST. After the scene's opening clip, nearly every clip is an [ANGLE CUT] that shows the SPEAKER'S FACE over the LISTENER'S shoulder: while Hannah speaks, the camera is behind Mike's shoulder looking at Hannah; when Mike answers, it is behind Hannah's shoulder looking at Mike. The speaker's face must always be visible, because only a visible face can move its lips. The speaker is turned THREE-QUARTER toward the lens, never in pure profile; the listener is the back or side of a shoulder in the foreground. A clip in which BOTH people speak CUTS INSIDE the clip: the first part is the over-the-shoulder shot of the first speaker, then a hard cut, timed in the gap between the two lines, to the over-the-shoulder shot of the second speaker. Write both parts in the one shot sentence with the cut time (for example: over Mike's shoulder on Hannah as she speaks, hard cut at 2.5 seconds to over Hannah's shoulder on Mike as he answers). With three lines in one clip, cut at each change of speaker, never more than twice. NEVER a profile two-shot with both faces turned toward each other. Name the scene's two shoulder angles once; every time an angle comes back, COPY the placement words of the earlier clip that used it exactly (the previous clips' shots are shown to you above), so "the same angle" really is the same.
       C) DIALOGUE with THREE OR MORE people present (a table, a group in a corridor): do NOT cut between shoulders. Open the scene with a WIDE shot that shows everyone, and come back to a wide shot only every third or fourth clip so the group reads as a group: never the same wide three-shot in two clips in a row. EVERY clip in between is an [ANGLE CUT] that moves in on the SPEAKER (a medium shot or a close-up, from the group's side), with the listeners as soft shoulders, heads or silhouettes in the foreground; when two people trade lines in one clip, hold the two of them in a medium two-shot. List as on screen (in blocking) only the speaker and the one or two listeners the shot really shows; everyone else is 'off screen' for that clip. Cut to one key listener's face for a reaction when the story calls for it.
       D) ESTABLISHING PHASE: the FIRST clip of a scene, or of a new place, is the master: a wide or medium shot that shows where everyone is, what the room looks like and each person's screen position (frame-left vs frame-right). It MOVES (a slow drift or push); it does not freeze.
       E) FRAMING WHEN SOMEONE SPEAKS: the video is VERTICAL (9:16), so frame TIGHT. The speaker is a Medium Close-Up (chest up) or a Close-Up, NEVER wider than a Medium shot (waist up): nothing below the waist is shown in a clip where someone speaks. Wide shots are only for the first clip of a scene, for group shots and for movement.
   (2) EVERY ANGLE SHOWS ITS BACKGROUND: say what is visible BEHIND the subject in that angle, taken from the place's layout (for example "behind Hannah, her front door and the rain-streaked window"). The location pictures cannot show every direction, so the shot text has to.
   (3) THE 180-DEGREE RULE & SCREEN DIRECTION: between two clips of one scene, keep the camera on the SAME SIDE of the imaginary line between the people, so each keeps their screen side: the person on frame-left stays on frame-left and looks toward screen-right. Crossing to the other side is allowed in only three cases, and then the shot MUST state the new positions in words and set "frame_position" and "screen_profile" to match (everything mirrors: who is left or right, where doors and windows are, which way people face): (a) the camera visibly travels across during the clip (an orbit, or a track past them); (b) the clip follows a wide or neutral shot, or a change of place; (c) it is a narration or action clip between scenes. The two parts of a cut inside one clip stay on the SAME side of the line. Never flip it by accident.
   (4) COVERAGE PHASE - MOTIVATED CUTS: besides the speaker shots above, use Close-Up / Extreme Close-Up on a face, trembling hands or a key prop at emotional peaks; Power Dynamics (the dominant person from a LOW angle, the vulnerable one from a HIGH angle); Reveals (open on a close detail, then pull back or tilt to show the scene). Every [ANGLE CUT] has a reason in the drama. NEVER cut in the MIDDLE of a movement: when someone walks, enters or leaves across consecutive clips, keep ONE continuous tracking shot ([SAME SETUP]) that follows them.
   (5) PEOPLE IN THE SHOT ARE NOT STATUES (KEEP IT LIGHT): do not describe anyone who is merely listening as 'frozen', a 'statue', or one who 'holds still' or 'stays still'; write what the eyes or hands do instead (a glance, a small nod, a hand shifting). Keep it small and natural, and do NOT write breaths in, sighs, exhales, gulps or a facial 'settling' before a line: a speaker simply begins on the first word of the line.
   (6) NEW PEOPLE IN THE SHOT: a person who was not in the previous clip must not simply APPEAR inside the frame of the shot that showed someone alone (do not show them 'behind' a person who was just by himself). People do not have to walk in. EITHER they enter or are revealed on screen (they walk in, a door opens, the camera turns toward their voices), OR you CUT TO THEM: this clip's shot is framed on the new people, already standing where the layout puts them, in the same space a few metres from the person who was alone, who stays visible but soft and out of focus in the distance, watching or listening (for example, the shot is on two women talking by a door, and the man who was alone a few steps away is a blurred figure behind them). Say which you chose in the shot sentence.
   (7) ONE MAIN MOMENT PER CLIP:
       Each clip captures ONE natural cinematic beat that plays out comfortably in 5 seconds. Never cram an entire scene's setup, revelation, and resolution into a single 5-second clip. Complete one beat cleanly and move on.
   (8) "shot" FORMAT (REQUIRED):
       Write the exact camera setup for this 5-second clip as a single continuous physical sentence starting with "[SAME SETUP]" or "[ANGLE CUT]". You MUST include these elements:
       - CAMERA PLACEMENT: where is the camera physically positioned, using the place's layout? (e.g. "[SAME SETUP] Camera placed at waist height two metres from the reception desk facing Clara Vance", "[ANGLE CUT] Tight over his left shoulder facing Clara")
       - CAMERA MOVEMENT: what does it physically do during the 5 seconds? (e.g. "slowly pushes in", "tracks with her as she turns", "tilts up from the desk to her face", "drifts left with a light handheld sway")
       - WHAT IT FOLLOWS: what specific body part, prop or detail does the camera stay tight on? (e.g. "locks on her eyes", "follows her trembling hand", "stays tight on his jawline")
       - ENDING FRAME: where does the shot resolve at the end of 5 seconds? (e.g. "ending on a tight close-up of her face", "resolving on an over-the-shoulder frame of the open doorway")
       - DEPTH OF FIELD: how does focus fall off? (e.g. "shallow depth of field with background lobby blurring into soft bokeh", "deep focus keeping both actors crisp")
       - BACKGROUND: what is visible behind the subject (see 2).
       NOTE: Lighting and room atmosphere belong in "environment", NOT in "shot". Do not put lighting descriptions in "shot".
       The camera placement must agree with the blocking: if the camera is behind someone's shoulder facing the door, the blocking must put that person between the camera and the door.
       - STORY-CRITICAL MOVEMENT ON CAMERA: when the story depends on where someone goes or where they come from (they hide, leave, slip away, sneak in, arrive, return), the camera must point that way and keep the start and end of the movement in frame. Never let the move that matters happen outside the frame.
       - EXITS THAT LEAVE OTHERS ALONE: when someone leaves so that others can be alone, the camera follows them until they are clearly gone (through the door, out of earshot) and the shot ends holding on the people left behind, alone, so the next clip plainly reads as a private moment.
       BAD EXAMPLE: "Wide shot, eye-level, locked static hold as he walks to the door."
       GOOD EXAMPLE: "[ANGLE CUT] Camera placed behind Mike's left shoulder at head height, looking at Hannah by the front door, slowly pushing in with a light handheld sway as she speaks, locking on her eyes, resolving on a tight medium close-up of her face; behind her, the pale front door and the rain-streaked window; shallow depth of field leaves the room in soft bokeh."
       SHOT SIZES: Extreme Wide, Wide, Medium-Wide (knees up), Medium (waist up), Medium Close-Up (chest up), Close-Up (face), Extreme Close-Up (eyes, mouth, hands, one object).
       SCREEN PLACEMENT: In "blocking", set "frame_position" for every character: 'frame left', 'left of centre', 'centre frame', 'right of centre', 'frame right', 'foreground', 'background', or 'off screen'. Set "screen_profile" so the speaker is three-quarter toward the lens; pure profile only for a deliberate confrontation.

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
   The Story Premise below describes the WHOLE story, only so that you understand the cast, the world and the tone. You are shown the story so far (the recent clips in full) and the one beat you are writing now; nothing later has happened yet. Never show, name or hint at a person, place, room number, object or event that the clips above have not already reached - not in action_steps, not in the shot, not anywhere. The spoken lines are fixed by the beat and are not yours to change or to withhold.

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
        source = _end_state_source(prev_clips)
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

            # Whose poses and knowledge the next clip opens on: this clip's own, unless this is the latest clip and it
            # shows nobody (an empty frame), in which case the last clip that did (see _end_state_source).
            pose_clip, handed_over_from = c, None
            if source is not None and c is prev_clips[-1] and source[1] is not c:
                pose_clip, handed_over_from = source[1], source[1].get("clip_number", source[0] + 1)
            blocking_state = []
            for b in pose_clip.get("blocking", []):
                if b.get("in_frame") in ON_SCREEN:
                    blocking_state.append(f"{b.get('character')}: {b.get('posture')} at {b.get('position')} ({b.get('screen_profile')})")
            block_str = "; ".join(blocking_state) or "none on screen"

            entry = (
                f"Clip {c_num} | Location: '{c_loc}' | Mode: {c_mode.upper()} | Shot: {c_shot}\n"
                f"  Visible on screen: {c_chars}\n"
                f"  Actions: {steps_line}\n"
                f"  Spoken/Internal Voice: {speech_line}"
            )
            # Only the most recent clip(s) carry their end state. The next clip opens on the LATEST clip's
            # poses, knowledge and props, and that state already contains whatever the older ones said, so
            # repeating it three times was about a third of the whole prompt.
            if idx > len(prev_clips) - HISTORY_END_STATE_CLIPS:
                if handed_over_from is not None:
                    entry += (f"\n  (This clip shows nobody. Where everyone stands and what each knows below is how Clip "
                              f"{handed_over_from} left them; nothing with people in it has happened since.)")
                entry += (
                    f"\n  Ending Pose/Blocking: {block_str}\n"
                    f"  What the place was doing: {c.get('environment') or 'still'}\n"
                    f"  What each character knew by the end: {_awareness_line(pose_clip) or 'nothing noted'}\n"
                    f"  Props at the end of the clip: {_props_line(c) or 'none yet'}"
                )
            history_lines.append(entry)
        history_summary = "\nPREVIOUS FILMED CLIPS (Direct Narrative & Spoken Continuity):\n" + "\n\n".join(history_lines) + f"\n\nStart Clip {clip_index + 1} as a direct continuous beat responding to Clip {clip_index}."

    # Only the story so far, never what is coming. Handing the whole plan to the clip writer is what let a
    # clip-2 voiceover name Room 404 a clip before the story revealed it.
    roadmap = _story_so_far(beats, clip_index, acts)

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


def _turns_too_fast(turns: list[dict]) -> bool:
    """Is any line packed into a window too short to be spoken without dropping a word?"""
    for t in turns:
        try:
            length = float(t.get("end_est", 0)) - float(t.get("start_est", 0))
        except (TypeError, ValueError):
            return True
        if length <= 0 or len(_WORD.findall(t.get("line") or "")) / length > MAX_TURN_WORDS_PER_SECOND:
            return True
    return False


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
    if turns and (not _turn_windows_valid(turns) or _turns_too_fast(turns)):
        _respace_turns(turns)
        clip["speech"] = turns
        fixed.append(f"re-spaced {len(turns)} speech window(s) so they fit the clip without overlapping or rushing a line")

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
    try:
        answer = _ask_openai_json(sys_p, usr_p, "narrated_supervisor", SUPERVISOR_SCHEMA, model=app.OPENAI_CLIP_MODEL,
                                  max_completion_tokens=SUPERVISOR_MAX_OUTPUT)
    except OpenAIOutputCut as e:
        # The supervisor only advises. A reply that ran away is not worth a failed clip: skip its notes.
        print(f"  {e}; continuity notes skipped for this clip.", flush=True)
        return []
    problems = [f"script supervisor: {p}" for p in answer.get("problems", []) if p and str(p).strip()]
    return problems


def write_narrated_chapter(
    topic: str,
    clip_index: int,
    total_clips: int,
    beats: list[dict],
    bible: dict,
    prev_clips: list[dict],
    supervise: bool = False,
    acts: list[dict] | None = None
) -> tuple[dict, list[str]]:
    """Writes an individual clip script with validation. `acts` is the plan's act breakdown (optional)."""
    beat = beats[clip_index]
    sys_p, usr_p = _narrated_chapter_prompt(topic, clip_index, total_clips, beat, bible, prev_clips, beats=beats, acts=acts)
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
        try:
            data = _ask_openai_json(sys_p, usr_p, "narrated_chapter", schema, model=app.OPENAI_CLIP_MODEL,
                                    max_completion_tokens=CLIP_MAX_OUTPUT)
        except OpenAIOutputCut as e:
            # A runaway reply, cut off at the ceiling, has no usable JSON. Count it as a failed attempt and
            # ask again; with every attempt spent the error stands and the job stops before this clip is rendered.
            if attempt == CHAPTER_RETRIES:
                raise
            print(f"  Clip {clip_index+1}: {e}; retrying ({attempt+1}/{CHAPTER_RETRIES}).", flush=True)
            usr_p = (
                base_usr
                + "\n\nYour previous answer never finished: it kept repeating itself. Write each list once. "
                  "prop_state has one entry per prop, only for props in shot or changed in this clip."
            )
            continue
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
def _timed_actions(steps: list[dict] | None, plain=lambda text: text) -> str:
    """The clip's action steps as a timeline in whole seconds, contiguous from 0 to the end of the clip.

    Seedance is prompted best with timecoded beats ("0-2s: wide shot ... 2-5s: ..."), in whole seconds with no
    gaps. Steps that start in the same second share a range, and the first range always opens at 0 (the pose
    the clip starts in holds until the first step). Returns "" when there is no timeline to give - no steps,
    or every step in the same second - so the caller falls back to the plain untimed list."""
    rows = []
    for s in steps or []:
        try:
            t = float(s.get("start_time", 0) or 0)
        except (TypeError, ValueError):
            t = 0.0
        second = min(max(int(t + 0.5), 0), CLIP_SECONDS - 1)
        text = plain(s.get("action", "")).strip().rstrip(". ")
        if text:
            rows.append((second, f"{s.get('character')}: {text}"))
    starts = sorted({sec for sec, _ in rows})
    if len(starts) < 2:
        return ""
    ranges = []
    for i, sec in enumerate(starts):
        end = starts[i + 1] if i + 1 < len(starts) else CLIP_SECONDS
        begin = 0 if i == 0 else sec
        ranges.append(f"{begin}-{end}s: " + "; ".join(txt for s2, txt in rows if s2 == sec) + ".")
    return "Action timeline (seconds into the clip): " + " ".join(ranges)


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

    timeline = _timed_actions(clip.get("action_steps"), _plain) if TIMED_ACTIONS else ""
    action_descs = [f"{s['character']}: {_plain(s['action'])}" for s in clip.get("action_steps", [])]
    if timeline:
        parts.append(timeline)
    elif action_descs:
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
                f"everyone else listens with their mouth closed. Keep {movie._join(speaking)} in the shot (at least as a shoulder), and show each speaker's face while their line is spoken; the camera may cut between them at the change of speaker."
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
    print("Step 1: Generating the Master Plan...")
    outline, problems = write_narrated_outline(topic, duration, total_clips)
    blocking, reviewable = split_plan_problems(_hard_problems(problems))
    if blocking:
        print("\n  Master Plan still breaks these rules after retries. Nothing was generated:")
        for p in blocking:
            print(f"    - {p}")
        sys.exit("Fix the premise (or rerun) - no credits were spent.")
    for p in reviewable:
        print(f"  REVIEW: {p}")
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
        ch_data, clip_problems = write_narrated_chapter(topic, i, total_clips, beats, bible, prev_clips, supervise=supervise,
                                                        acts=outline.get("acts"))
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
