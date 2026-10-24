"""Script mode for Hybrid Narrated Drama: from the author's story script to a directed, renderable plan.

The author's script (parsed by story_script.py) fixes every spoken word. This module adds everything else:

  1. build_bible       one AI call: the cast header + minor speakers + places -> the scene bible (structured looks, voices, places)
  2. beats_from_script no AI: the plan's beats, with the author's lines copied word for word
  3. direct_clips      the SCREENWRITER: one AI call per 3 clips -> a shot list per clip (opening pose, a shot for every line, L-cuts,
                       inserts). Code checks it; a failed clip is re-asked with the exact errors; a clip that still fails gets a plain
                       fallback shot list, flagged, so the words always survive.
  4. compile_prompt    no AI: the shot list -> the Seedance prompt, with reference-picture and voice tags and the fixed lip-sync text
  5. rewrite_clip      the plan-review instruction rewrite of ONE clip's shots
  6. apply_hand_edit   the plan-review hand edit (camera text, delivery, opening pose; the words are never editable)

Nothing here changes a word of dialogue: shots carry the script's own words, sliced at word boundaries.
"""
from __future__ import annotations

import copy
import json
import os
import re
from typing import Callable

import story_script as ss

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
SCRIPT_MODEL = os.getenv("SCRIPT_MODEL", "").strip() or "gpt-6-luna"   # every AI call of script mode
SCREENWRITER_BATCH = 3            # clips per screenwriter call (what worked by hand)
SCREENWRITER_RETRIES = 2          # re-asks for the clips that failed the checks, per batch
SCREENWRITER_MAX_OUTPUT = 20000
BIBLE_MAX_OUTPUT = 16000
BIBLE_RETRIES = 2
MAX_SHOTS = 14
MAX_SILENT_SHOTS = 3
HEAD_MIN_WORDS = 4                # a live line is on its speaker's face for at least this many words before the camera leaves
PIECE_MIN_WORDS = 3               # no piece of a split line is shorter than this
MAX_PIECES = 3                    # speaker, cut-away, back to the speaker
LIPS = ("speaker", "closed", "media")
FALLBACK_NOTE = "basic shot list (the screenwriter could not satisfy the checks): give an instruction to have it rewritten"

AskFn = Callable[..., dict]


def _default_ask(system: str, user: str, name: str, schema: dict, max_out: int) -> dict:
    import app   # lazy: app imports the hybrid module, which imports this one's siblings
    return app._ask_openai_json(system, user, name, schema, model=SCRIPT_MODEL, max_completion_tokens=max_out)


# ---------------------------------------------------------------------------
# Words
# ---------------------------------------------------------------------------
_QUOTES = str.maketrans({"’": "'", "‘": "'", "“": '"', "”": '"', "—": "-", "–": "-", "…": "..."})


def _tokens(text: str) -> list[str]:
    return (text or "").split()


def _norm_tokens(text: str) -> list[str]:
    return (text or "").translate(_QUOTES).split()


def count_words(text: str) -> int:
    return ss.count_words(text)


def _name_key(name: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", "", (name or "").lower().replace("’", "'")).strip()


# ---------------------------------------------------------------------------
# 1. The scene bible
# ---------------------------------------------------------------------------
_APPEARANCE = {
    "type": "object",
    "properties": {
        "casting": {"type": "string", "description": "How the character reads on screen in a few words, WITH the age: 'girl of five', 'woman in her late twenties'."},
        "hair_color": {"type": "string", "description": "One plain colour: 'jet black', 'ash blonde'."},
        "hair_style": {"type": "string", "description": "Length and how it is worn."},
        "build": {"type": "string", "description": "Height and build suited to the age."},
        "distinguishing_feature": {"type": "string", "description": "One permanent visible feature that separates them from everyone else on screen."},
        "wardrobe": {"type": "string", "description": "The fixed clothing worn throughout."},
    },
    "required": ["casting", "hair_color", "hair_style", "build", "distinguishing_feature", "wardrobe"],
    "additionalProperties": False,
}
BIBLE_SCHEMA = {
    "type": "object",
    "properties": {
        "characters": {"type": "array", "items": {"type": "object", "properties": {
            "name": {"type": "string"},
            "role": {"type": "string", "description": "Who they are in the story, a few words."},
            "appearance": _APPEARANCE,
            "voice": {"type": "string", "description": "The INSTRUMENT only: pitch, grain, accent ('light clear soprano', 'low gravelled baritone'). Never how a line is played ('calm', 'controlled', 'quiet')."},
        }, "required": ["name", "role", "appearance", "voice"], "additionalProperties": False}},
        "locations": {"type": "array", "items": {"type": "object", "properties": {
            "id": {"type": "string", "description": "Exactly the id given."},
            "description": {"type": "string", "description": "Its fixed look in one or two sentences: architecture, furniture, materials, colours, light."},
            "layout": {"type": "string", "description": "A fixed map: each door, window, staircase and the main furniture placed relative to the main entrance."},
            "image_prompt": {"type": "string", "description": "A text-to-image prompt for a wide view of the EMPTY place. No people, no story props."},
            "views": {"type": "array", "items": {"type": "string"}, "description": "2 or 3 camera viewpoints for reference pictures, all showing the place empty."},
        }, "required": ["id", "description", "layout", "image_prompt", "views"], "additionalProperties": False}},
    },
    "required": ["characters", "locations"],
    "additionalProperties": False,
}

_BIBLE_SYSTEM = """You prepare the production bible for a vertical (9:16) short drama. The author has written the story script; you do NOT change it. You turn its cast list and places into the structured descriptions the picture and video models need.

CAST - STRICT RULES:
- The author's description of each header character is the single source of truth. Put every fact it gives (hair, clothes, build, age, anything visible) into the structured fields in plain words. NEVER contradict it, NEVER change an age, a colour or a garment.
- Only fill what the description leaves out (for example a build suited to the age, or a visible distinguishing feature). Fill the gap in the most natural way; do not make a character glamorous or dramatic beyond what is written.
- "casting" always states the age ('girl of five', 'boy of seven', 'man in his early thirties').
- Characters marked MINOR have no description: invent a look from the role and from how the script shows them (clothes that fit the job and the setting). Make each minor character visually different from everyone else in hair colour or style, and give each a distinguishing feature.
- No two MAIN characters may share a hair colour unless the author's description forces it.
- "voice" is pitch, grain and accent only, suited to age and sex: never an emotion or a manner of speaking.

PLACES:
- Use EXACTLY the given ids. Describe each place from what the script's own scene notes show of it, plus sensible fixed details so it looks the same in every clip.
- Every place must be roomy enough for three people to stand apart and for a camera to stand several metres back: never cramped, narrow or tiny.
- image_prompt and views show the place EMPTY: no people, no story objects.
Return strictly valid JSON matching the schema."""


def _direction_snippets(doc: ss.ScriptDoc, needle_names: list[str], limit: int = 4) -> list[str]:
    out = []
    for c in doc.clips:
        for d in c.directions:
            if any(re.search(rf"(?<!\w){re.escape(n)}(?!\w)", d["text"], re.I) for n in needle_names):
                out.append(f"clip {c.number}: {d['text'][:220]}")
                if len(out) >= limit:
                    return out
    return out


def _protagonist(doc: ss.ScriptDoc) -> str:
    """The point-of-view character: whoever has the most inner-thought lines (else the first in the header)."""
    count: dict[str, int] = {}
    for c in doc.clips:
        for l in c.lines:
            if l.kind == "inner_thought":
                count[l.speaker] = count.get(l.speaker, 0) + 1
    if count:
        return max(count, key=lambda n: count[n])
    return doc.characters[0].name if doc.characters else ""


def _bible_prompt(doc: ss.ScriptDoc, protagonist: str) -> str:
    parts = ["CAST FROM THE AUTHOR'S HEADER (single source of truth):"]
    for c in doc.characters:
        parts.append(f"- {c.name}, age {c.age}: {c.description}" + ("  [POV protagonist]" if c.name == protagonist else ""))
    if doc.unlisted_speakers:
        parts.append("\nMINOR CHARACTERS (no description in the header; invent their look):")
        for u in doc.unlisted_speakers:
            sample = next((l.text for c in doc.clips for l in c.lines if l.speaker == u["name"]), "")
            snips = _direction_snippets(doc, [u["name"], u["name"].split()[-1]], 2)
            parts.append(f"- {u['name']}: speaks {u['lines']} time(s) in clips {', '.join(map(str, u['clips']))}. Example line: \"{sample[:120]}\""
                         + ("".join(f"\n    scene note, {s}" for s in snips)))
    parts.append("\nPLACES (use exactly these ids):")
    seen = {}
    for c in doc.clips:
        for loc in c.locations or ([{"id": c.location_id, "name": c.location_name, "time": c.time_of_day}] if c.location_id else []):
            seen.setdefault(loc["id"], loc["name"])
    for lid, name in seen.items():
        notes = []
        for c in doc.clips:
            for d in c.directions:
                if name and name.split(" — ")[0].lower() in d["text"].lower():
                    notes.append(d["text"][:200])
                    break
            if len(notes) >= 2:
                break
        parts.append(f"- id: {lid}  (named in the script as: {name})" + "".join(f"\n    scene note: {n}" for n in notes))
    return "\n".join(parts)


def _bible_problems(data: dict, doc: ss.ScriptDoc) -> list[str]:
    problems = []
    want = [c.name for c in doc.characters] + [u["name"] for u in doc.unlisted_speakers]
    got = [c.get("name", "") for c in data.get("characters", [])]
    for n in want:
        if n not in got:
            problems.append(f"character {n!r} is missing (use the exact name)")
    for n in got:
        if n not in want:
            problems.append(f"character {n!r} is not in the cast")
    ids = {l.get("id") for l in data.get("locations", [])}
    want_ids = {c.location_id for c in doc.clips if c.location_id} | {loc["id"] for c in doc.clips for loc in c.locations}
    for i in sorted(want_ids - ids):
        problems.append(f"place {i!r} is missing (use exactly the given ids)")
    for i in sorted(ids - want_ids):
        problems.append(f"place {i!r} was not asked for")
    for c in data.get("characters", []):
        if not (c.get("appearance", {}).get("hair_color") or "").strip():
            problems.append(f"{c.get('name')}: hair_color is empty")
    return problems


def build_bible(doc: ss.ScriptDoc, ask: AskFn | None = None) -> dict:
    """The scene bible in the shape the rest of the pipeline uses (characters with `appearance`, places with `layout`, `views`...)."""
    ask = ask or _default_ask
    protagonist = _protagonist(doc)
    user = _bible_prompt(doc, protagonist)
    data, problems = {}, []
    base = user
    for attempt in range(BIBLE_RETRIES + 1):
        data = ask(_BIBLE_SYSTEM, user, "script_bible", BIBLE_SCHEMA, BIBLE_MAX_OUTPUT)
        problems = _bible_problems(data, doc)
        if not problems:
            break
        user = base + "\n\nYour previous answer had these problems; fix them and return the whole bible again:\n- " + "\n- ".join(problems)
    if problems:
        raise ValueError("the scene bible could not be built: " + "; ".join(problems))
    header = {c.name: c for c in doc.characters}
    unlisted = {u["name"] for u in doc.unlisted_speakers}
    chars = []
    for c in data["characters"]:
        h = header.get(c["name"])
        chars.append({
            "name": c["name"], "is_protagonist": c["name"] == protagonist,
            "role": c["role"], "appearance": c["appearance"], "voice": c["voice"].strip(),
            "motivation": "", "relationships": "", "speech_style": "",
            "age": h.age if h else None,
            "source_look": h.description if h else "",
            "auto_look": c["name"] in unlisted,
        })
    locs = []
    for l in data["locations"]:
        loc = {k: l[k] for k in ("id", "description", "layout", "image_prompt", "views")}
        locs.append(loc)
    bible = {"pov_protagonist": protagonist, "characters": chars, "props": [], "locations": locs}
    return bible


# ---------------------------------------------------------------------------
# 2. Beats (no AI)
# ---------------------------------------------------------------------------
def estimate_windows(words: list[int], dur: int = 15) -> list[tuple[float, float]]:
    """Rough speech windows from word counts. Only used to cut a voice sample out of a rendered clip; the prompt carries no timestamps."""
    n = len(words)
    if not n:
        return []
    first, last, gap = 0.2, dur - 0.1, 0.1
    total = max(1, sum(max(1, w) for w in words))
    span = (last - first) - gap * (n - 1)
    out, cur = [], first
    for w in words:
        length = span * max(1, w) / total
        out.append((round(cur, 2), round(cur + length, 2)))
        cur += length + gap
    return out


def _clip_locations(clip: ss.Clip) -> list[str]:
    ids = []
    for loc in clip.locations or []:
        if loc["id"] not in ids:
            ids.append(loc["id"])
    if not ids and clip.location_id:
        ids = [clip.location_id]
    return ids


def beats_from_script(doc: ss.ScriptDoc, bible: dict) -> list[dict]:
    protagonist = bible.get("pov_protagonist", "")
    known = {c["name"] for c in bible["characters"]}
    beats = []
    for clip in doc.clips:
        mode = "shock_action" if not clip.lines else ("voiceover" if len(clip.lines) == 1 and clip.lines[0].is_voiceover else "dialogue")
        present = [n for n in dict.fromkeys(clip.speakers + clip.mentioned) if n in known]
        lines = [{"speaker": l.speaker, "line": l.text, "is_voiceover": l.is_voiceover, "cutaway": ""} for l in clip.lines]
        locs = _clip_locations(clip)
        beat = {
            "clip_number": clip.index, "cycle_number": clip.index, "delivery_mode": mode,
            "location_id": ", ".join(locs) if locs else "", "present_characters": present,
            "speaker_or_actor": (protagonist if mode in ("voiceover", "shock_action") else (clip.speakers[0] if clip.speakers else protagonist)) if present or mode != "shock_action" else "",
            "duration": ss.SCRIPT_CLIP_SECONDS,
            "summary": (clip.title + ": " if clip.title else "") + " ".join(d["text"] for d in clip.directions)[:420],
            "speech_budget": clip.words, "audio_lines": lines, "reveals": [],
            "function": "clash", "turn": "", "delivers": [], "script_title": clip.title, "script_clip_number": clip.number,
        }
        if len(locs) > 1:
            beat["location_ids"] = locs
        beats.append(beat)
    return beats


# ---------------------------------------------------------------------------
# 3. The screenwriter: schema, prompt, checks
# ---------------------------------------------------------------------------
SHOT_SCHEMA = {
    "type": "object",
    "properties": {
        "camera": {"type": "string", "description": "What the camera does and frames in this shot, in plain screenplay words: the cut or move (whip cut, snap zoom, push-in, tracking, over-the-shoulder, low angle, macro insert), the framing, who or what is in it, and the performer's visible expression or action. NEVER contains any spoken words."},
        "line": {"type": "integer", "description": "The 1-based number of the spoken line whose words are heard during this shot, or 0 for a silent shot."},
        "words": {"type": "string", "description": "The EXACT words of that line heard during this shot: the whole line, or one consecutive piece of it. Empty when line is 0."},
        "lips": {"type": "string", "enum": list(LIPS), "description": "speaker: the speaker is on camera speaking with moving lips. closed: nobody visible speaks (a listener's reaction, an object, an inner thought, a phone voice). media: the speaker is seen speaking from a screen."},
        "delivery": {"type": "string", "description": "How these words are said (emotion and manner, a few words). Empty when line is 0."},
        "target": {"type": "string", "description": "Who or what the shot is on. lips=speaker: the speaker's name. lips=closed with a line: the listener's name, or a short plain description of the object or detail shown. A silent shot: its subject."},
        "purpose": {"type": "string", "description": "Why this shot is in the story, one short sentence. REQUIRED for every shot on an object or detail and every silent shot; otherwise an empty string."},
    },
    "required": ["camera", "line", "words", "lips", "delivery", "target", "purpose"],
    "additionalProperties": False,
}
DIRECTED_CLIP_SCHEMA = {
    "type": "object",
    "properties": {
        "clip_number": {"type": "integer"},
        "opening_pose": {"type": "string", "description": "Frame 0.0s: where every person in the clip stands or sits, what their hands and eyes are doing, any prop in view, and the expression on each face. For a clip that continues the one before, this is exactly where that clip ended."},
        "on_screen": {"type": "array", "items": {"type": "string"}, "description": "Every cast member who is physically in the room/place during this clip (exact names). A phone caller who is not in the room is not listed."},
        "shots": {"type": "array", "items": SHOT_SCHEMA},
        "end_state": {"type": "string", "description": "Where everyone is and what the very last frame shows, in one or two sentences. The next clip opens on this."},
    },
    "required": ["clip_number", "opening_pose", "on_screen", "shots", "end_state"],
    "additionalProperties": False,
}
DIRECTED_BATCH_SCHEMA = {
    "type": "object",
    "properties": {"clips": {"type": "array", "items": DIRECTED_CLIP_SCHEMA}},
    "required": ["clips"],
    "additionalProperties": False,
}

# One worked example (clip 2 of the author's tested plan), shown to the screenwriter as the standard to reach.
EXAMPLE_LINES = [
    ("Margot", "live", "Viv, what are you doing? Why did you stop? Your stepkids are right there."),
    ("Vivian Ashford", "inner_thought", "Margot. The fake best friend who pushes Vivian off every cliff."),
    ("Margot", "live", "Don't go soft now. Make her give back the bracelet she stole from you. The one you promised me."),
    ("Vivian Ashford", "live", "Rosie, is your hand bleeding?"),
    ("Rosie", "live", "No, I didn't take anything bad. I promise."),
]
EXAMPLE_OUTPUT = {
    "clip_number": 2,
    "opening_pose": "Vivian Ashford stands by the central rug, right manicured hand already lowered at her side, fingers still trembling, staring in shock. Margot slides an arm around Vivian's shoulders from behind. Across the rug, Theo shields little Rosie as Rosie clutches a clenched fist behind her back.",
    "on_screen": ["Vivian Ashford", "Margot", "Theo", "Rosie"],
    "shots": [
        {"camera": "Whip cut: Medium close-up on Margot sliding an arm around Vivian's shoulders, right beside her", "line": 1, "words": "Viv, what are you doing? Why did you stop?", "lips": "speaker", "delivery": "whispering urgently, fake-concerned", "target": "Margot", "purpose": ""},
        {"camera": "Camera whip-pans across the rug to Theo glaring protectively in front of Rosie", "line": 1, "words": "Your stepkids are right there.", "lips": "closed", "delivery": "mocking whisper", "target": "Theo", "purpose": ""},
        {"camera": "Instant snap zoom: Extreme Close-up on Vivian's wide, calculating eyes darting sideways at Margot, dawning horror", "line": 2, "words": "Margot. The fake best friend who pushes Vivian off every cliff.", "lips": "closed", "delivery": "disgusted internal realization", "target": "Vivian Ashford", "purpose": ""},
        {"camera": "Over-the-shoulder close-up on Margot leaning right beside Vivian's ear, venomous urgency", "line": 3, "words": "Don't go soft now. Make her give back the bracelet she stole from you.", "lips": "speaker", "delivery": "whispering urgently, toxic pressure", "target": "Margot", "purpose": ""},
        {"camera": "Macro extreme close-up down on Rosie's small pale fist, a thin red cut across her knuckles and a single drop falling onto the parquet floor", "line": 3, "words": "The one you promised me.", "lips": "closed", "delivery": "insistent whisper", "target": "Rosie's clenched fist with a thin red cut across the knuckles", "purpose": "The cut fist is the answer to the clip's title."},
        {"camera": "Instant snap zoom: Close-up on Vivian's eyes widening in horror as she drops her gaze with sudden urgency", "line": 4, "words": "Rosie, is your hand bleeding?", "lips": "speaker", "delivery": "breathless shock, sudden tenderness", "target": "Vivian Ashford", "purpose": ""},
        {"camera": "Tight close-up on Rosie hiding her fist behind her back and shaking her head, tears streaming down her cheeks", "line": 5, "words": "No, I didn't take anything bad. I promise.", "lips": "speaker", "delivery": "voice breaking, tearful plea", "target": "Rosie", "purpose": ""},
    ],
    "end_state": "Vivian crouching toward Rosie, who still hides her fist behind her back; Margot behind Vivian; Theo guarding Rosie.",
}

_SCREENWRITER_SYSTEM = """You are the screenwriter, director and cinematographer of a vertical (9:16) short drama, made of consecutive 15-second clips that an AI video model films from a screenplay-style prompt. The author has already written the story and EVERY spoken word. You decide how each clip is SHOT. Your shot lists decide whether this looks like a cheap talking-heads video or a gripping, beautifully cut drama.

THE WORDS ARE LOCKED (CRITICAL)
- Each clip gives you numbered lines. Every word of every line must be heard, exactly as written, in order. You add no words, remove none, reorder none. Never put any dialogue inside "camera" or "opening_pose".
- A shot carries a piece of one line in "words": the whole line, or a consecutive piece of it, copied exactly. The pieces of a line, in shot order, must join to the full line.
- A line may be split into at most 3 pieces to make an L-cut: (1) the speaker on camera for the first words, (2) the camera cuts away to a listener's reaction or to an object/detail that MATTERS to the story while the voice carries on, (3) optionally back to the speaker. Split only at a natural break. Each piece has at least 3 words and the first piece (speaker on camera) at least 4.
- Speech is dense: a clip may hold up to 74 words in 15 seconds. Dialogue starts at once, handoffs between speakers are instant, and there are no pauses or dead air. Use L-cuts and reaction shots so the picture keeps moving while the voice keeps going. Never slow a line down.

LIP RULES (CRITICAL, the video model obeys them literally)
- lips="speaker": the speaker is on camera, speaking with moving lips. The speaker's name is the target.
- lips="closed": nobody visible speaks: a listener reacting, an object, a detail, a phone voice, or an inner thought. When the camera is on someone while another character's voice continues, that listener's mouth stays closed.
- A live line must begin with the speaker on camera (lips="speaker") for at least its first 4 words, unless that speaker has already been shown speaking earlier in this clip (then the whole line may play over a cutaway), or the speaker is not in the room.
- An INNER THOUGHT (kind inner_thought) is ONE unbroken shot on the thinker, lips="closed", target = the thinker. The face carries it through the eyes and expression. Never split it.
- phone_voice / off_screen lines: lips="closed" (the speaker is not in the room, or not seen). on_screen_media: the speaker is seen on a screen; use lips="media".

CINEMATOGRAPHY
- Think like a premium short-drama director: whip pans, snap zooms into the eyes at shock moments, slow push-ins, over-the-shoulder close-ups, low angles for power, tracking moves, macro inserts. Close-ups for emotion. Keep it 9:16.
- The author's bracketed scene notes (shown with each clip) are the minimal version of the camera work: keep every story-critical visual in them (a cut hand, a phone screen, a bracelet, a door opening, a freeze frame) as an insert or a cut-away shot, and make them richer and more cinematic. Every shot on an object or detail needs a "purpose" (why the audience must see it now).
- A shot that holds a person describes their expression and what their body does. Name people exactly as in the cast list.
- Do not use more than 14 shots in a clip, nor more than 3 silent shots (line 0), and a silent shot is only for a story-critical visual or the end-of-clip freeze frame. Prefer carrying the visual over a line as an L-cut.
- If the author's notes end the clip with a freeze frame or title card (for example TO BE CONTINUED), end the clip with a silent shot that describes it, including the text overlay.

CONTINUITY
- "opening_pose" is where everyone is at frame 0.0s. When a clip follows another in the same place, it opens exactly where the previous one ended (see PREVIOUS CLIP ENDED), unless the author's notes say time or place changes. Never film a walk-in or reposition just to bridge a gap: a cut is allowed.
- "on_screen" lists every cast member physically in the place during the clip; all live speakers must be in it. Cast looks are fixed: never describe a change of hair, clothes or age.
- "end_state" says where everyone is and what the last frame shows.

OUTPUT: strictly valid JSON matching the schema, one entry per requested clip, clip_number as given."""


def _style_example() -> str:
    lines = "\n".join(f'  line {i + 1} [{k}] {s}: "{t}"' for i, (s, k, t) in enumerate(EXAMPLE_LINES))
    return ("WORKED EXAMPLE of the standard to reach (clip 2 of an earlier story).\nIts numbered lines were:\n" + lines +
            "\nand a good shot list for it was:\n" + json.dumps(EXAMPLE_OUTPUT, indent=1, ensure_ascii=False))


def _line_digest(clip: ss.Clip) -> str:
    out = []
    for i, l in enumerate(clip.lines, 1):
        hint = f" (delivery hint: {l.delivery})" if l.delivery else ""
        out.append(f'  line {i} [{l.kind}] {l.speaker}{hint}, {l.words} words: "{l.text}"')
    return "\n".join(out) or "  (no spoken lines in this clip)"


def _cast_digest(bible: dict) -> str:
    out = []
    for c in bible["characters"]:
        a = c.get("look") or ", ".join(str(v) for v in (c.get("appearance") or {}).values())
        out.append(f"- {c['name']}" + (f" (age {c['age']})" if c.get("age") else "") + f": {a}")
    return "\n".join(out)


def _clip_block(doc: ss.ScriptDoc, clip: ss.Clip, prev: ss.Clip | None) -> str:
    place = " -> ".join(dict.fromkeys(loc["name"] for loc in clip.locations)) or clip.location_name
    same = prev is not None and prev.location_id == clip.location_id and not clip.locations
    cont = " (CONTINUOUS from the previous clip: same place)" if same else ""
    notes = "\n".join(f"    [{d['text']}]" for d in clip.directions) or "    (none)"
    return (f"CLIP {clip.index} — \"{clip.title}\"  place: {place}{cont}  ({clip.words} words, {len(clip.lines)} lines)\n"
            f"  The author's scene notes (minimal camera/action; make them cinematic):\n{notes}\n  Spoken lines:\n{_line_digest(clip)}")


def _batch_prompt(doc, bible, clips, prev_end: str, extra: str = "") -> str:
    prevs = {c.index: (doc.clips[c.index - 2] if c.index > 1 else None) for c in clips}
    parts = ["CAST (fixed looks; use exact names):", _cast_digest(bible), "",
             "PREVIOUS CLIP ENDED: " + (prev_end or "(this is the first clip: open on the establishing pose)"), ""]
    parts += [_clip_block(doc, c, prevs[c.index]) + "\n" for c in clips]
    if extra:
        parts.append(extra)
    parts.append(f"Return JSON with \"clips\": exactly {len(clips)} items for clips {', '.join(str(c.index) for c in clips)}.")
    return "\n".join(parts)


def _is_cast(name: str, cast_keys: dict[str, str]) -> str | None:
    k = _name_key(name)
    if k in cast_keys:
        return cast_keys[k]
    first = [v for kk, v in cast_keys.items() if kk.split()[0] == k.split()[0:1][0]] if k else []
    return first[0] if len(set(first)) == 1 and len(k.split()) == 1 else None


def check_directed_clip(out: dict, clip: ss.Clip, bible: dict) -> list[str]:
    """Every rule a shot list must satisfy. Empty list = the clip is good. Never trusts the model's `words`: it only checks them."""
    p: list[str] = []
    cast = {_name_key(c["name"]): c["name"] for c in bible["characters"]}
    lines = clip.lines
    shots = out.get("shots") or []
    on_screen = []
    for n in out.get("on_screen") or []:
        full = _is_cast(n, cast)
        if not full:
            p.append(f"on_screen lists {n!r}, who is not in the cast")
        elif full not in on_screen:
            on_screen.append(full)
    if len((out.get("opening_pose") or "").split()) < 5:
        p.append("opening_pose is missing or too short")
    if not (out.get("end_state") or "").strip():
        p.append("end_state is missing")
    if not shots:
        return p + ["no shots"]
    if len(shots) > MAX_SHOTS:
        p.append(f"{len(shots)} shots; at most {MAX_SHOTS}")
    silent = [s for s in shots if not s.get("line")]
    if len(silent) > MAX_SILENT_SHOTS:
        p.append(f"{len(silent)} silent shots; at most {MAX_SILENT_SHOTS}")

    quoting_keys = []
    for l in lines:
        t = _norm_tokens(l.text)
        if len(t) >= 5:
            quoting_keys.append(" ".join(t[:5]).lower())
    spoken_on_cam: set[str] = set()
    last_line = 0
    pieces: dict[int, list[dict]] = {}
    for i, s in enumerate(shots, 1):
        cam = (s.get("camera") or "").strip()
        tag = f"shot {i}"
        if len(cam.split()) < 3:
            p.append(f"{tag}: camera text is missing")
        flat = " ".join(_norm_tokens(cam)).lower()
        for key in quoting_keys:
            if key in flat:
                p.append(f"{tag}: camera text contains dialogue ('{key}...'); never put spoken words in camera text")
                break
        n = int(s.get("line") or 0)
        lips = s.get("lips")
        if lips not in LIPS:
            p.append(f"{tag}: lips must be one of {', '.join(LIPS)}")
        if n == 0:
            if (s.get("words") or "").strip():
                p.append(f"{tag}: a silent shot (line 0) has words")
            if not (s.get("purpose") or "").strip():
                p.append(f"{tag}: a silent shot needs a purpose")
            continue
        if n < 0 or n > len(lines):
            p.append(f"{tag}: line {n} does not exist (this clip has {len(lines)})")
            continue
        if n < last_line:
            p.append(f"{tag}: line {n} comes after line {last_line}; lines must be heard in order")
        last_line = max(last_line, n)
        pieces.setdefault(n, []).append(s)

    for n, l in enumerate(lines, 1):
        got = pieces.get(n)
        if not got:
            p.append(f"line {n} ({l.speaker}) is not in any shot")
            continue
        joined = [t for s in got for t in _norm_tokens(s.get("words"))]
        if joined != _norm_tokens(l.text):
            p.append(f"line {n} ({l.speaker}): the words in its shots do not equal the line exactly. The line is: \"{l.text}\"")
            continue
        if len(got) > MAX_PIECES:
            p.append(f"line {n}: split into {len(got)} pieces; at most {MAX_PIECES}")
        speaker = l.speaker
        speaker_in_room = _is_cast(speaker, cast) in on_screen if _is_cast(speaker, cast) else True
        kind = l.kind
        for k, s in enumerate(got):
            tag = f"line {n} piece {k + 1}"
            lips, target = s.get("lips"), (s.get("target") or "").strip()
            wn = len(s.get("words", "").split())
            if wn < PIECE_MIN_WORDS and len(got) > 1:
                p.append(f"{tag}: only {wn} word(s); a split piece has at least {PIECE_MIN_WORDS}")
            if not target:
                p.append(f"{tag}: target is empty")
            if kind == "inner_thought":
                if len(got) != 1:
                    p.append(f"line {n} is an inner thought: ONE unbroken shot, not {len(got)}")
                if lips != "closed":
                    p.append(f"{tag}: an inner thought has lips=closed")
                if _is_cast(speaker, cast) in on_screen and _is_cast(target, cast) != _is_cast(speaker, cast):
                    p.append(f"{tag}: an inner thought stays on the thinker ({speaker}); target must be {speaker}")
                continue
            if kind in ("phone_voice", "off_screen"):
                if lips != "closed":
                    p.append(f"{tag}: {speaker}'s voice is {kind.replace('_', ' ')}; lips=closed")
                continue
            if kind == "on_screen_media":
                if lips not in ("media", "closed"):
                    p.append(f"{tag}: {speaker} is on a screen; lips=media")
                continue
            # a live line
            if lips == "speaker":
                if _is_cast(target, cast) != _is_cast(speaker, cast):
                    p.append(f"{tag}: lips=speaker so the target must be {speaker}, not {target!r}")
                if _is_cast(speaker, cast) not in on_screen:
                    p.append(f"{tag}: {speaker} speaks on camera but is not in on_screen")
            elif lips == "closed":
                who = _is_cast(target, cast)
                if who:
                    if who == _is_cast(speaker, cast):
                        p.append(f"{tag}: a cut-away to the speaker themselves must be lips=speaker")
                    elif who not in on_screen:
                        p.append(f"{tag}: cuts to {who}, who is not in the room (on_screen)")
                elif not (s.get("purpose") or "").strip():
                    p.append(f"{tag}: a shot on an object or detail ({target!r}) needs a purpose")
            else:
                p.append(f"{tag}: a live line uses lips=speaker or lips=closed")
            if k == 0 and lips != "speaker":
                if _is_cast(speaker, cast) not in spoken_on_cam and speaker_in_room:
                    p.append(f"{tag}: {speaker} must be seen speaking (lips=speaker) before the camera leaves them; the line starts on a cut-away but {speaker} has not yet spoken on camera in this clip")
            if k == 0 and lips == "speaker" and len(got) > 1 and wn < HEAD_MIN_WORDS:
                p.append(f"{tag}: the speaker is on camera for only {wn} word(s) before the cut-away; at least {HEAD_MIN_WORDS}")
            if lips == "speaker":
                spoken_on_cam.add(_is_cast(speaker, cast) or speaker)
    for s in shots:
        if s.get("lips") == "speaker" and not int(s.get("line") or 0):
            p.append("a silent shot cannot have lips=speaker")
    for l in lines:
        if l.kind == "live" and _is_cast(l.speaker, cast) and _is_cast(l.speaker, cast) not in on_screen:
            p.append(f"{l.speaker} speaks a live line but is not in on_screen")
    return p


def normalize_directed_clip(out: dict, clip: ss.Clip, bible: dict) -> dict:
    """The model's answer, tidied into what is stored: exact cast names, and every shot's `words` replaced by the script's OWN characters
    (sliced at the same word boundaries), so a typographic variant from the model never reaches the video."""
    cast = {_name_key(c["name"]): c["name"] for c in bible["characters"]}
    res = copy.deepcopy(out)
    res["on_screen"] = list(dict.fromkeys(_is_cast(n, cast) or n for n in res.get("on_screen") or []))
    cursor: dict[int, int] = {}
    for s in res.get("shots", []):
        n = int(s.get("line") or 0)
        s["camera"] = re.sub(r"\s+", " ", (s.get("camera") or "")).strip()
        s["delivery"] = (s.get("delivery") or "").strip().strip("()").strip()
        s["purpose"] = (s.get("purpose") or "").strip()
        tgt = (s.get("target") or "").strip()
        s["target"] = _is_cast(tgt, cast) or tgt
        if n and 0 < n <= len(clip.lines):
            orig = _tokens(clip.lines[n - 1].text)
            take = len(_norm_tokens(s.get("words")))
            at = cursor.get(n, 0)
            s["words"] = " ".join(orig[at:at + take])
            cursor[n] = at + take
            if not s["delivery"] and clip.lines[n - 1].delivery:
                s["delivery"] = clip.lines[n - 1].delivery
        else:
            s["words"] = ""
    return res


def fallback_directed_clip(clip: ss.Clip, bible: dict, prev_end: str) -> dict:
    """A plain but correct shot list: every line on its speaker in close-up (a thought on the thinker). Used only when the screenwriter cannot
    satisfy the checks, and flagged to the user. It guarantees that no word is lost."""
    cast = {_name_key(c["name"]): c["name"] for c in bible["characters"]}
    on_screen = [n for n in dict.fromkeys(clip.speakers + clip.mentioned) if _is_cast(n, cast)]
    shots = []
    for i, l in enumerate(clip.lines, 1):
        if l.kind == "inner_thought":
            cam = f"Tight close-up on {l.speaker}'s face, eyes carrying the thought"
            shots.append({"camera": cam, "line": i, "words": l.text, "lips": "closed", "delivery": l.delivery or "inner thought", "target": l.speaker, "purpose": ""})
        elif l.kind in ("phone_voice", "off_screen"):
            shots.append({"camera": "Close-up on the listener, mouth closed, as the voice is heard", "line": i, "words": l.text, "lips": "closed", "delivery": l.delivery, "target": next((n for n in on_screen if n != l.speaker), l.speaker), "purpose": ""})
        elif l.kind == "on_screen_media":
            shots.append({"camera": "Close-up on the screen showing the speaker", "line": i, "words": l.text, "lips": "media", "delivery": l.delivery, "target": l.speaker, "purpose": ""})
        else:
            shots.append({"camera": "Rapid cut: Close-up on " + l.speaker, "line": i, "words": l.text, "lips": "speaker", "delivery": l.delivery, "target": l.speaker, "purpose": ""})
    if not shots:
        shots.append({"camera": "Wide establishing shot of the place", "line": 0, "words": "", "lips": "closed", "delivery": "", "target": "the place", "purpose": "No one speaks in this clip."})
    pose = prev_end or ("The characters are in their places in " + (clip.location_name or "the room") + ".")
    return {"clip_number": clip.index, "opening_pose": pose if len(pose.split()) >= 5 else pose + " Everyone in position.",
            "on_screen": on_screen, "shots": shots, "end_state": "Everyone as they were at the end of the last line."}


def _authored(out: dict, clip: ss.Clip, prev_clip: ss.Clip | None, fallback: bool = False, problems: list[str] | None = None) -> dict:
    same_place = prev_clip is not None and prev_clip.location_id == clip.location_id and not clip.locations
    return {
        "version": 1,
        "fallback": fallback,
        "problems": problems or [],
        "heading": {"location_name": clip.location_name, "time": clip.time_of_day, "continuous": bool(same_place)},
        "opening_pose": out["opening_pose"], "on_screen": out["on_screen"], "end_state": out["end_state"],
        "lines": [{"n": i, "speaker": l.speaker, "text": l.text, "kind": l.kind, "delivery": l.delivery} for i, l in enumerate(clip.lines, 1)],
        "shots": out["shots"],
    }


def clip_script_from(clip: ss.Clip, authored: dict, bible: dict, location_ids: list[str]) -> dict:
    """The clip dict the rest of the pipeline stores and renders (same shape the per-clip writer produces), plus the `authored` shot list."""
    protagonist = bible.get("pov_protagonist", "")
    wins = estimate_windows([l.words for l in clip.lines], ss.SCRIPT_CLIP_SECONDS)
    speech = []
    for l, (a, b) in zip(clip.lines, wins):
        speech.append({"speaker": l.speaker, "line": l.text, "delivery": l.delivery, "start_est": a, "end_est": b, "is_voiceover": l.is_voiceover})
    on = authored["on_screen"]
    blocking = [{
        "character": n, "position": "in the scene", "posture": "standing", "screen_profile": "", "frame_position": "centre frame", "eyeline": "",
        "end_position": "in the scene", "end_posture": "standing", "end_screen_profile": "", "end_frame_position": "centre frame", "end_eyeline": "",
        "awareness": "", "in_frame": "visible"} for n in on]
    for l in clip.lines:
        if l.kind in ("phone_voice", "off_screen") and l.speaker not in on:
            if not any(b["character"] == l.speaker for b in blocking):
                blocking.append({"character": l.speaker, "position": "remote caller on the phone", "posture": "standing", "screen_profile": "",
                                 "frame_position": "off screen", "eyeline": "", "end_position": "remote caller on the phone", "end_posture": "standing",
                                 "end_screen_profile": "", "end_frame_position": "off screen", "end_eyeline": "", "awareness": "", "in_frame": "off screen"})
    mode = "shock_action" if not clip.lines else ("voiceover" if len(clip.lines) == 1 and clip.lines[0].is_voiceover else "dialogue")
    return {
        "clip_number": clip.index, "delivery_mode": mode,
        "location_id": ", ".join(location_ids), **({"location_ids": location_ids} if len(location_ids) > 1 else {}),
        "shot": authored["shots"][0]["camera"] if authored["shots"] else "", "present_characters": list(on), "speech": speech,
        "environment": "", "prop_state": [], "action_steps": [], "blocking": blocking, "duration": ss.SCRIPT_CLIP_SECONDS,
        "fresh_opening": True, "authored": authored,
    }


def direct_clips(doc: ss.ScriptDoc, bible: dict, ask: AskFn | None = None, progress: Callable[[str], None] | None = None,
                 only: list[int] | None = None, prev_ends: dict[int, str] | None = None) -> dict[int, dict]:
    """The screenwriter pass over the script (or just the clips in `only`). Returns {clip index: authored dict}.
    One AI call per SCREENWRITER_BATCH clips, in order, each told where the previous clip ended."""
    ask = ask or _default_ask
    say = progress or (lambda m: None)
    todo = [c for c in doc.clips if only is None or c.index in only]
    results: dict[int, dict] = {}
    prev_ends = dict(prev_ends or {})
    system = _SCREENWRITER_SYSTEM + "\n\n" + _style_example()
    for b in range(0, len(todo), SCREENWRITER_BATCH):
        batch = todo[b:b + SCREENWRITER_BATCH]
        say(f"Directing clips {batch[0].index}-{batch[-1].index} of {doc.clips[-1].index}")
        first_prev = results.get(batch[0].index - 1, {}).get("end_state") or prev_ends.get(batch[0].index - 1, "")
        pending = {c.index: c for c in batch}
        good: dict[int, dict] = {}
        feedback: dict[int, list[str]] = {}
        answers: dict[int, dict] = {}
        for attempt in range(SCREENWRITER_RETRIES + 1):
            ask_clips = [c for c in batch if c.index in pending]
            extra = ""
            if attempt:
                extra = "\n".join(
                    f"CLIP {i} was rejected for these reasons; rewrite it fully and fix every one:\n  - " + "\n  - ".join(feedback[i]) for i in feedback if i in pending)
            data = ask(system, _batch_prompt(doc, bible, ask_clips, first_prev, extra), "script_screenwriter", DIRECTED_BATCH_SCHEMA, SCREENWRITER_MAX_OUTPUT)
            by_number = {int(c.get("clip_number", 0)): c for c in data.get("clips", [])}
            for c in ask_clips:
                out = by_number.get(c.index)
                if out is None:
                    feedback[c.index] = [f"clip {c.index} was missing from your answer"]
                    continue
                out = normalize_directed_clip(out, c, bible) if _shape_ok(out) else out
                problems = check_directed_clip(out, c, bible) if _shape_ok(out) else ["the answer did not follow the schema"]
                if problems:
                    feedback[c.index] = problems
                    answers[c.index] = out
                else:
                    good[c.index] = out
                    pending.pop(c.index, None)
            if not pending:
                break
        prev_clip_of = {c.index: (doc.clips[c.index - 2] if c.index > 1 else None) for c in batch}
        running_prev = first_prev
        for c in batch:
            if c.index in good:
                out, fb, probs = good[c.index], False, []
            else:
                probs = feedback.get(c.index, [])
                out = fallback_directed_clip(c, bible, running_prev)
                fb = True
                say(f"Clip {c.index}: the screenwriter could not satisfy the checks, using a basic shot list")
            results[c.index] = _authored(out, c, prev_clip_of[c.index], fallback=fb, problems=probs)
            running_prev = out["end_state"]
    return results


def _shape_ok(out: dict) -> bool:
    return isinstance(out, dict) and isinstance(out.get("shots"), list) and all(isinstance(s, dict) for s in out["shots"])


# ---------------------------------------------------------------------------
# Plan assembly
# ---------------------------------------------------------------------------
def plan_from_script(text: str, ask: AskFn | None = None, progress: Callable[[str], None] | None = None) -> dict:
    """The whole planning phase of a script job. Returns {"doc", "bible", "beats", "clip_scripts": [clip dict per clip], "report"}.
    Raises ValueError with the parser's report if the script has errors (nothing is spent)."""
    say = progress or (lambda m: None)
    doc = ss.parse_story_script(text)
    if doc.errors:
        raise ValueError("The story script has errors; nothing was generated and no credits were spent:\n- " + "\n- ".join(str(i) for i in doc.errors[:25]))
    say("Building the cast and places")
    bible = build_bible(doc, ask)
    import hybrid_narrated_drama as hnd
    hnd._compile_bible_visuals(bible)
    beats = beats_from_script(doc, bible)
    authored = direct_clips(doc, bible, ask, progress)
    scripts = []
    for clip in doc.clips:
        scripts.append(clip_script_from(clip, authored[clip.index], bible, _clip_locations(clip)))
    problems = []
    for clip in doc.clips:
        a = authored[clip.index]
        if a["fallback"]:
            problems.append(f"[REVIEW] Clip {clip.index} ({clip.title}): {FALLBACK_NOTE}. Reasons: " + "; ".join(a["problems"][:4]))
    for w in doc.warnings:
        if w.code != "clip_gap":
            problems.append(f"[SOFT] {w}")
    words = sum(c.words for c in doc.clips)
    report = {
        "script_mode": True, "problems": problems,
        "stats": {"spoken_lines": sum(len(c.lines) for c in doc.clips), "spoken_words": words,
                  "narration_share": (sum(l.words for c in doc.clips for l in c.lines if l.is_voiceover) / words) if words else 0.0},
        "words_per_clip": [{"clip": c.index, "title": c.title, "words": c.words} for c in doc.clips],
        "auto_looks": [u["name"] for u in doc.unlisted_speakers],
    }
    return {"doc": doc, "bible": bible, "beats": beats, "clip_scripts": scripts, "report": report}


# ---------------------------------------------------------------------------
# Plan review: instruction rewrite and hand edit
# ---------------------------------------------------------------------------
def doc_clip_from_script(clip_script: dict, beat: dict, bible: dict, index: int) -> ss.Clip:
    """A parser Clip rebuilt from what a job stores (the locked lines live in `authored["lines"]`), so one clip can be re-directed alone."""
    a = clip_script["authored"]
    c = ss.Clip(index=index, number=beat.get("script_clip_number", index), title=beat.get("script_title", ""), source_line=0)
    c.location_name, c.location_id = a["heading"]["location_name"], (beat.get("location_id") or "").split(",")[0].strip()
    c.time_of_day = a["heading"].get("time", "")
    for l in a["lines"]:
        c.lines.append(ss.Line(speaker=l["speaker"], speaker_raw=l["speaker"], listed=True, kind=l["kind"], qualifier="", delivery=l.get("delivery", ""),
                               text=l["text"], words=count_words(l["text"]), source_line=0))
    c.speakers = list(dict.fromkeys(l.speaker for l in c.lines))
    c.words = sum(l.words for l in c.lines)
    c.directions = [{"text": beat.get("summary", ""), "source_line": 0}] if beat.get("summary") else []
    return c


def rewrite_clip(clip_script: dict, beat: dict, bible: dict, index: int, instruction: str, prev_end: str = "", next_opening: str = "",
                 ask: AskFn | None = None) -> dict:
    """Re-direct ONE clip following the user's instruction. Returns the new `authored` dict; raises ValueError if the result cannot satisfy the checks."""
    ask = ask or _default_ask
    clip = doc_clip_from_script(clip_script, beat, bible, index)
    a = clip_script["authored"]
    cur = {"clip_number": index, "opening_pose": a["opening_pose"], "on_screen": a["on_screen"], "shots": a["shots"], "end_state": a["end_state"]}
    doc = ss.ScriptDoc(clips=[clip])
    doc.clips[0].index = 1
    clip.index = 1
    extra = ("THE AUTHOR'S INSTRUCTION for this clip (follow it; the words stay locked):\n" + instruction.strip() +
             "\n\nTHE CURRENT SHOT LIST (change only what the instruction needs, keep what already works):\n" + json.dumps(cur, ensure_ascii=False, indent=1) +
             (f"\n\nThe next clip opens with: {next_opening}" if next_opening else ""))
    system = _SCREENWRITER_SYSTEM + "\n\n" + _style_example()
    user = _batch_prompt(doc, bible, [clip], prev_end, extra)
    feedback: list[str] = []
    for attempt in range(SCREENWRITER_RETRIES + 1):
        msg = user + ("\n\nYour previous answer was rejected:\n- " + "\n- ".join(feedback) if feedback else "")
        data = ask(system, msg, "script_rewrite", DIRECTED_BATCH_SCHEMA, SCREENWRITER_MAX_OUTPUT)
        out = next((c for c in data.get("clips", [])), None)
        if out is None or not _shape_ok(out):
            feedback = ["the answer did not follow the schema"]
            continue
        out["clip_number"] = 1
        out = normalize_directed_clip(out, clip, bible)
        feedback = check_directed_clip(out, clip, bible)
        if not feedback:
            res = _authored(out, clip, None)
            res["heading"] = a["heading"]
            return res
    raise ValueError("The rewrite could not satisfy the checks: " + "; ".join(feedback[:5]))


EDITABLE_SHOT_FIELDS = ("camera", "delivery", "target", "purpose", "lips")


def apply_hand_edit(clip_script: dict, bible: dict, edit: dict) -> dict:
    """Apply a hand edit and return the new `authored` dict. `edit` = {"opening_pose"?, "end_state"?, "on_screen"?, "shots"?: [{"index", camera?, delivery?, target?, purpose?, lips?, "delete"?}]}.
    The words are not editable: `words` and `line` of a shot are kept as they are. Raises ValueError if the edited shot list fails the checks."""
    a = copy.deepcopy(clip_script["authored"])
    if "opening_pose" in edit:
        a["opening_pose"] = str(edit["opening_pose"]).strip()
    if "end_state" in edit:
        a["end_state"] = str(edit["end_state"]).strip()
    if "on_screen" in edit:
        a["on_screen"] = [str(n).strip() for n in edit["on_screen"] if str(n).strip()]
    drop = set()
    for e in edit.get("shots") or []:
        i = int(e.get("index", -1))
        if not 0 <= i < len(a["shots"]):
            raise ValueError(f"shot {i + 1} does not exist")
        if e.get("delete"):
            if a["shots"][i]["line"]:
                raise ValueError(f"shot {i + 1} carries spoken words and cannot be deleted")
            drop.add(i)
            continue
        for f in EDITABLE_SHOT_FIELDS:
            if f in e:
                a["shots"][i][f] = str(e[f]).strip()
    a["shots"] = [s for i, s in enumerate(a["shots"]) if i not in drop]
    clip = ss.Clip(index=1, number=1, title="", source_line=0)
    for l in a["lines"]:
        clip.lines.append(ss.Line(speaker=l["speaker"], speaker_raw=l["speaker"], listed=True, kind=l["kind"], qualifier="", delivery=l.get("delivery", ""),
                                  text=l["text"], words=count_words(l["text"]), source_line=0))
    out = {"clip_number": 1, "opening_pose": a["opening_pose"], "on_screen": a["on_screen"], "shots": a["shots"], "end_state": a["end_state"]}
    probs = check_directed_clip(out, clip, bible)
    if probs:
        raise ValueError("; ".join(probs[:6]))
    a["fallback"], a["problems"] = False, []
    return a


# ---------------------------------------------------------------------------
# 4. The prompt compiler (no AI)
# ---------------------------------------------------------------------------
_CLOSED_LISTENER = "{who} keeps mouth strictly closed with lips firmly motionless; zero lip movement."
_CLOSED_ANY = "Every mouth on screen stays strictly closed with lips firmly motionless; zero lip movement."
_CLOSED_THINKER = ("{who} keeps mouth strictly closed with lips pressed firmly together and motionless, showing how the thought lands only through "
                   "eye movements and facial expression; zero lip movement.")
_GUARD = ("CRITICAL OFF-SCREEN DIALOGUE & REACTION RULE: When the camera cuts, tracks, or frames a reacting character or prop while dialogue is actively "
          "concluding or spoken off-camera (L-cut reaction shots), on-screen characters MUST keep their mouths strictly closed with lips completely motionless. "
          "NEVER animate the lips or mouth of any character on screen to another character's voice, and do not alter the speaker's vocal timbre. "
          "Non-speaking listeners NEVER mouth off-screen dialogue.")


def _time_phrase(heading: dict) -> str:
    bits = [(heading.get("time") or "").strip().upper()]
    if heading.get("continuous"):
        bits.append("CONTINUOUS")
    return ", ".join(b for b in bits if b)


def compile_prompt(clip: dict, bible: dict, cast_bank: dict, location_bank: dict, voice_bank: dict,
                   prev_clip: dict | None = None) -> tuple[str, list[str], list[str]]:
    """The Seedance prompt for a directed clip: (prompt, reference image urls, reference audio urls). Same reference rules as the standard compiler."""
    import hybrid_narrated_drama as hnd
    a = clip["authored"]
    lines = {l["n"]: l for l in a["lines"]}
    on_screen = [n for n in a["on_screen"]][:hnd.MAX_ON_SCREEN]
    loc_ids = clip.get("location_ids") or [x.strip() for x in str(clip.get("location_id", "")).split(",") if x.strip()]
    faces = [n for n in on_screen if cast_bank.get(n)]
    avail = max(1, hnd.MAX_REF_IMAGES - len(faces))
    max_views = max(1, min(3, avail // max(1, len(loc_ids))))
    ref_images: list[str] = []
    loc_tags: dict[str, list[str]] = {}
    for lid in loc_ids:
        views = location_bank.get(lid, [])
        take = views[:max(1, min(len(views), max_views, avail - len(ref_images)))] if views else []
        tags = []
        for url in take:
            ref_images.append(url)
            tags.append(f"@Image{len(ref_images)}")
        loc_tags[lid] = tags
    char_tags = []
    for name in on_screen:
        info = next((c for c in bible["characters"] if c["name"].lower() == name.lower()), None)
        look = (info.get("look") or hnd._compile_look(info["appearance"])) if info and info.get("appearance") else ""
        if cast_bank.get(name) and len(ref_images) < hnd.MAX_REF_IMAGES:
            ref_images.append(cast_bank[name])
            char_tags.append(f"{name} is @Image{len(ref_images)}")
        else:
            char_tags.append(f"{name} ({look})")
    ref_audios: list[str] = []
    ref_speakers = hnd._voice_ref_speakers(clip, voice_bank)

    def voice_tag(name: str) -> str:
        url = voice_bank.get(name)
        if not url or name not in ref_speakers:
            return ""
        if url not in ref_audios:
            if len(ref_audios) >= hnd.KIE_MAX_AUDIO_REFS:
                return ""
            ref_audios.append(url)
        return f"@Audio{ref_audios.index(url) + 1}"

    def written_voice(name: str) -> str:
        info = next((c for c in bible["characters"] if c["name"].lower() == name.lower()), None)
        return (info.get("voice") or "").strip().rstrip(". ") if info else ""

    def voice_note(name: str, lead: str = " (matching {t})") -> str:
        t = voice_tag(name)
        if t:
            return lead.format(t=t)
        w = written_voice(name)
        if not w:
            return ""
        return f", in {w}" if lead.lstrip().startswith(",") else f" (in {w})"

    out: list[str] = []
    heading = a["heading"]
    tp = _time_phrase(heading)
    for idx, lid in enumerate(loc_ids, 1):
        loc = next((l for l in bible.get("locations", []) if l["id"] == lid), None)
        desc = (loc["description"] if loc else lid).rstrip(". ")
        tags = ", ".join(loc_tags.get(lid, []))
        where = f"Location matches {tags}: {desc}" if tags else f"Location: {desc}"
        label = f"SCENE {idx}" if len(loc_ids) > 1 else "SCENE"
        out.append(f"[{label}: {tp + '. ' if tp and idx == 1 else ''}{where}.]")
    out.append(f"[CAST: {'. '.join(char_tags)}. Each named character's face, hair, and clothing match their reference image exactly: do not restyle or re-cast.]"
               if char_tags else "[CAST: Cinematic environmental shot, no visible characters.]")
    out.append(f"[FRAME 0.0s OPENING POSE & BLOCKING: {a['opening_pose'].rstrip('. ')}.]")
    out.append("")

    # group the shots by line to label pieces
    by_line: dict[int, list[int]] = {}
    for i, s in enumerate(a["shots"]):
        if s["line"]:
            by_line.setdefault(s["line"], []).append(i)
    live_names, has_vo, has_off = [], False, False
    for i, s in enumerate(a["shots"]):
        cam = s["camera"].strip().rstrip(".:;, ")
        n = s["line"]
        if not n:
            out.append(f"[{cam}.]")
            out.append("")
            continue
        l = lines[n]
        spk, kind = l["speaker"], l["kind"]
        order = by_line[n]
        k, m = order.index(i), len(order)
        deliv = f"({s['delivery']}) " if s.get("delivery") else ""
        words = s["words"]
        lips, target = s["lips"], s["target"]
        target_is_cast = any(c["name"].lower() == target.lower() for c in bible["characters"])
        if kind == "inner_thought":
            has_vo = True
            out.append(f"[{cam}. The camera holds this one framing for the whole of this inner thought, with no cut away until it ends. Mouth strictly closed, lips motionless:]")
            vt = voice_tag(spk)
            vtxt = f" in {vt}'s voice" if vt else (f" in {written_voice(spk)}" if written_voice(spk) else "")
            out.append(f"{spk.upper()} (V.O. - inner thought{vtxt}): {deliv}\"{words}\"")
            out.append(f"[{_CLOSED_THINKER.format(who=spk)}]")
        elif kind == "phone_voice":
            has_off = True
            out.append(f"[{cam}, mouth closed, as {spk}'s voice comes over the phone:]")
            out.append(f"{spk.upper()} (over phone line{voice_note(spk, ' in {t}' + chr(39) + 's voice')}): {deliv}\"{words}\"")
            out.append(f"[{_CLOSED_ANY}]")
        elif kind == "on_screen_media" or lips == "media":
            out.append(f"[{cam}, {spk} speaking from the screen with animated lips:]")
            out.append(f"{spk.upper()} (on screen{voice_note(spk)}): {deliv}\"{words}\"")
        elif kind == "off_screen":
            has_off = True
            out.append(f"[{cam}. {spk} is heard from off-camera; nobody on screen speaks:]")
            out.append(f"{spk.upper()} (off-screen{voice_note(spk)}): {deliv}\"{words}\"")
            out.append(f"[{_CLOSED_ANY}]")
        elif lips == "speaker":
            live_names.append(spk)
            out.append(f"[{cam}, {spk} speaking with animated lips:]")
            out.append(f"{spk.upper()}{voice_note(spk)}: {deliv}\"{words}\"")
        else:   # a live line over a cut-away
            has_off = True
            role = "concluding line" if k == m - 1 and m > 1 else ("continuing" if m > 1 else "")
            tagtxt = f"off-screen, {role}" if role else "off-screen"
            if target_is_cast:
                out.append(f"[{cam}, {target} reacting with mouth strictly closed and lips motionless as {spk}'s voice carries on off-camera:]")
            else:
                out.append(f"[{cam}, filmed close, while {spk}'s voice carries on off-camera. Nobody on screen speaks:]")
            out.append(f"{spk.upper()} ({tagtxt}{voice_note(spk, ', matching {t}')}): {deliv}\"{words}\"")
            out.append(f"[{_CLOSED_LISTENER.format(who=target) if target_is_cast else _CLOSED_ANY}]")
        out.append("")

    live_names = list(dict.fromkeys(live_names))
    total_words = sum(len(x["words"].split()) for x in a["shots"])
    dense = total_words >= 45
    sync = (f"Synchronize lip movement exclusively onto the active live speakers on camera ({', '.join(live_names)}). " if live_names else
            "Synchronize lip movement exclusively onto characters speaking live on camera. ")
    thinkers = list(dict.fromkeys(l["speaker"] for l in a["lines"] if l["kind"] == "inner_thought"))
    vo = (f"During all (V.O. - inner thought) lines the camera stays locked on {', '.join(thinkers)}, whose mouth is strictly closed and lips completely stationary, "
          "reacting solely through eye movements and facial expression. ") if has_vo else ""
    head = "RAPID-FIRE PACING & LIP-SYNC DIRECTIVE: " + hnd._RAPID_PACING + " " if dense else "LIP-SYNC DIRECTIVE: "
    tail = " Fluid rapid-fire pacing throughout. No background music." if dense else " Fluid natural acting throughout. No background music."
    out.append(head + sync + vo + _GUARD + tail)
    return "\n".join(out), ref_images, ref_audios
