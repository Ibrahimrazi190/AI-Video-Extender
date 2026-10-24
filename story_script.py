"""Story-script parser and format/word checks for the Hybrid Narrated Drama "script" input mode.

The input is a plain .txt (or pasted text) laid out like the Claude-written story scripts:

    Title
    Characters:
       ● Vivian Ashford (27): the villain stepmom ... Long dark wavy hair, blush satin gown.
       ● Theo (7): ... Rosie (5): ...

    Clip 1: Wrong Body
    [INT. ASHFORD MANSION — DAY. Extreme close-up: a manicured hand raised high.]
     THEO: Don't hit her! Hit me instead!
     VIVIAN (V.O., inner thought, lips not moving): Wait. Where am I?

This module is deterministic (no AI call). It reads the cast header (the single source of truth for names, ages and
looks), the clip blocks (locations, directions, dialogue), and checks them. It never edits, trims or rewords a line of
dialogue: the words come out exactly as they went in (only invisible characters such as zero-width spaces are removed).

Run it on a file to see the report:   python story_script.py story.txt [--start-line N] [--json out.json]
"""
from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass, field, asdict

# ---------------------------------------------------------------------------
# Limits for this mode
# ---------------------------------------------------------------------------
SCRIPT_CLIP_SECONDS = 15          # every clip of a script is a full 15-second clip
SCRIPT_MAX_WORDS_PER_CLIP = 74    # hard ceiling, inner-thought (V.O.) lines included; below it every word must play
SCRIPT_MAX_LINES_PER_CLIP = 12    # the clip schema holds at most this many spoken turns
VOICE_REF_LIMIT = 3               # kie.ai takes at most this many reference audio files per request

# ---------------------------------------------------------------------------
# Reading helpers
# ---------------------------------------------------------------------------
_INVISIBLE = dict.fromkeys(map(ord, "​‌‍⁠﻿­\x0c"), None)
_WORD = re.compile(r"[A-Za-z0-9À-ɏ]+(?:['’\-][A-Za-z0-9À-ɏ]+)*")
_CLIP_HEADER = re.compile(r"^\s*clip\s+\d+", re.I)
_CLIP_HEADER_FULL = re.compile(r"^\s*clip\s+(\d+)\s*(.*)$", re.I)
_DIALOGUE = re.compile(r"^\s*([A-Z][A-Z0-9.'’ \-]*[A-Z.])\s*(?:\(([^)]*)\))?\s*:\s*(.*)$")
_HEADING = re.compile(r"^(?:INT\./EXT|INT/EXT|INT|EXT)\.?\s+(.+?)\.(?:\s|$)", re.S)
_TIME_WORD = re.compile(
    r"^(DAY|NIGHT|MORNING|EVENING|AFTERNOON|DUSK|DAWN|SUNSET|SUNRISE|CONTINUOUS|LATER|SAME|MOMENTS LATER|NEXT)\b", re.I)
_ENTRY = re.compile(r"((?:[A-Z][\w.’']*)(?:\s+[A-Z][\w.’']*)*)\s*\((\d{1,3})\)\s*:")
_TITLES = ("Mr.", "Mrs.", "Ms.", "Miss", "Dr.", "Sir", "Lady", "Lord")
_FREEZE = re.compile(r"TO BE CONTINUED", re.I)


def count_words(text: str) -> int:
    return len(_WORD.findall(text or ""))


def _clean_line(line: str) -> str:
    return line.translate(_INVISIBLE).replace(" ", " ").rstrip()


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def _norm_name(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", "", text.lower().replace("’", "'")).strip()


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------
@dataclass
class Issue:
    level: str            # "error" | "warning"
    line: int | None      # 1-based line in the file the user gave
    clip: int | None
    code: str
    message: str

    def __str__(self) -> str:
        where = f"line {self.line}" if self.line else "file"
        clip = f", clip {self.clip}" if self.clip else ""
        return f"[{self.level.upper()}] {where}{clip}: {self.message}"


@dataclass
class Character:
    name: str
    age: int
    description: str
    line: int


@dataclass
class Line:
    speaker: str            # the header name when it is listed, else the name as the script wrote it
    speaker_raw: str
    listed: bool            # is the speaker in the cast header?
    kind: str               # live | inner_thought | phone_voice | on_screen_media | off_screen
    qualifier: str
    delivery: str
    text: str               # the words, exactly as written (no cleaning of any kind)
    words: int
    source_line: int

    @property
    def is_voiceover(self) -> bool:
        return self.kind == "inner_thought"


@dataclass
class Clip:
    index: int                      # 1..N in file order
    number: int                     # the number the script gave it
    title: str
    source_line: int
    location_name: str = ""
    location_id: str = ""
    time_of_day: str = ""
    locations: list = field(default_factory=list)       # every place the clip's directions name, in order
    directions: list = field(default_factory=list)      # [{"text", "source_line"}]
    lines: list = field(default_factory=list)           # list[Line]
    speakers: list = field(default_factory=list)
    mentioned: list = field(default_factory=list)       # cast named in directions or lines but not speaking
    words: int = 0
    ends_with_to_be_continued: bool = False


@dataclass
class ScriptDoc:
    title: str = ""
    characters: list = field(default_factory=list)      # list[Character]
    clips: list = field(default_factory=list)           # list[Clip]
    issues: list = field(default_factory=list)          # list[Issue]
    unlisted_speakers: list = field(default_factory=list)

    @property
    def errors(self) -> list:
        return [i for i in self.issues if i.level == "error"]

    @property
    def warnings(self) -> list:
        return [i for i in self.issues if i.level == "warning"]

    @property
    def ok(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "characters": [asdict(c) for c in self.characters],
            "clips": [asdict(c) for c in self.clips],
            "issues": [asdict(i) for i in self.issues],
            "unlisted_speakers": self.unlisted_speakers,
            "limits": {"max_words": SCRIPT_MAX_WORDS_PER_CLIP, "clip_seconds": SCRIPT_CLIP_SECONDS,
                       "max_lines": SCRIPT_MAX_LINES_PER_CLIP},
        }


# ---------------------------------------------------------------------------
# Cast header
# ---------------------------------------------------------------------------
def _parse_header(lines: list[tuple[int, str]], doc: ScriptDoc) -> None:
    """`lines` are (line_number, text) between "Characters:" and the first clip."""
    first_no = lines[0][0] if lines else None
    joined, offsets = "", []
    for no, text in lines:
        t = re.sub(r"^[\s●•*\-]+", " ", text).strip()
        if not t:
            continue
        offsets.append((len(joined), no))
        joined += (" " if joined else "") + t
    matches = list(_ENTRY.finditer(joined))
    if not matches:
        doc.issues.append(Issue("error", first_no, None, "header_empty",
                                "No characters found in the header. Each one must look like 'Name (age): description'."))
        return

    def line_at(pos: int) -> int:
        no = offsets[0][1]
        for start, n in offsets:
            if start <= pos:
                no = n
        return no

    starts = []
    for m in matches:
        words = m.group(1).split()
        # a name never starts after a sentence end, except a title like "Mrs."
        keep = len(words)
        for k in range(len(words) - 1, 0, -1):
            if words[k - 1].endswith(".") and words[k - 1] not in _TITLES:
                keep = len(words) - k
                break
        words = words[len(words) - keep:]
        name = " ".join(words)
        name_start = m.end(1) - len(name)
        starts.append((name, int(m.group(2)), name_start, m.end()))
    seen = set()
    for i, (name, age, name_start, desc_start) in enumerate(starts):
        desc_end = starts[i + 1][2] if i + 1 < len(starts) else len(joined)
        desc = re.sub(r"\s+", " ", joined[desc_start:desc_end]).strip()
        key = _norm_name(name)
        if key in seen:
            doc.issues.append(Issue("error", line_at(name_start), None, "header_duplicate",
                                    f"'{name}' is listed twice in the cast header."))
            continue
        seen.add(key)
        if not desc:
            doc.issues.append(Issue("error", line_at(name_start), None, "header_no_look",
                                    f"'{name}' has no description. The header is the only source of looks for the cast pictures."))
        doc.characters.append(Character(name, age, desc, line_at(name_start)))


def _resolve_speaker(raw: str, characters: list[Character]) -> Character | None:
    key = _norm_name(raw)
    if not key:
        return None
    for c in characters:
        if _norm_name(c.name) == key:
            return c
    first_hits = [c for c in characters if _norm_name(c.name).split()[0:1] == key.split()[0:1] and len(key.split()) == 1]
    if len(first_hits) == 1:
        return first_hits[0]
    if len(key.split()) == 1:
        last_hits = [c for c in characters if _norm_name(c.name).split()[-1:] == [key]]
        if len(last_hits) == 1:
            return last_hits[0]
    return None


def _kind(qualifier: str) -> str:
    q = (qualifier or "").lower()
    if "phone" in q:
        return "phone_voice"
    if "on screen" in q or "on-screen" in q:
        return "on_screen_media"
    if "off-screen" in q or "off screen" in q or "o.s." in q:
        return "off_screen"
    if "inner" in q or "v.o" in q or "voice" in q or "thought" in q:
        return "inner_thought"
    return "live"


def _heading(direction: str) -> tuple[str, str] | None:
    m = _HEADING.match(direction.strip())
    if not m:
        return None
    parts = [p.strip() for p in re.split(r"\s+[—–-]\s+", m.group(1).strip()) if p.strip()]
    place, time_parts = [], []
    for p in parts:
        (time_parts if _TIME_WORD.match(p) else place).append(p)
    return " — ".join(place), ", ".join(time_parts)


def _mentions(text: str, characters: list[Character]) -> list[str]:
    firsts: dict[str, int] = {}
    for c in characters:
        f = c.name.split()[0]
        firsts[f] = firsts.get(f, 0) + 1
    found = []
    for c in characters:
        names = [c.name]
        f = c.name.split()[0]
        if f not in _TITLES and firsts[f] == 1:
            names.append(f)
        for n in names:
            if re.search(rf"(?<![\w]){re.escape(n)}(?![\w])", text):
                found.append(c.name)
                break
    return found


# ---------------------------------------------------------------------------
# Main parse
# ---------------------------------------------------------------------------
def parse_story_script(text: str, start_line: int = 1, allow_unlisted: bool = False) -> ScriptDoc:
    """Parse and check a story script. `start_line` (1-based) skips everything above it, for a file that holds extra material."""
    doc = ScriptDoc()
    raw_lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    lines = [(i + 1, _clean_line(l)) for i, l in enumerate(raw_lines)]
    lines = [(n, l) for n, l in lines if n >= start_line]

    # --- split the file: title, header, clips -------------------------------------------------------------------
    header_at = clip_first = None
    for idx, (no, l) in enumerate(lines):
        if header_at is None and re.match(r"^\s*characters\s*:\s*$", l, re.I):
            header_at = idx
        if _CLIP_HEADER.match(l) and clip_first is None:
            clip_first = idx
    if clip_first is None:
        doc.issues.append(Issue("error", None, None, "no_clips", "No 'Clip N: Title' blocks were found."))
        return doc
    if header_at is None or header_at > clip_first:
        doc.issues.append(Issue("error", None, None, "no_header",
                                "No 'Characters:' header before the first clip. The header is the only source of names, ages and looks."))
        header_lines: list = []
    else:
        header_lines = lines[header_at + 1:clip_first]
        for no, l in lines[:header_at]:
            if l.strip():
                doc.title = l.strip()
                break
        _parse_header(header_lines, doc)
    # a second cast header (or title) after the clips begin means two scripts were pasted into one file
    for no, l in lines[clip_first:]:
        if re.match(r"^\s*characters\s*:\s*$", l, re.I):
            doc.issues.append(Issue("error", no, None, "second_header",
                                    "A second 'Characters:' header appears here: the file looks like two scripts pasted together. "
                                    "Remove one of them (or run with a start line)."))
            break

    # --- group the clip blocks --------------------------------------------------------------------------------------
    blocks: list[tuple[int, str, list]] = []
    for no, l in lines[clip_first:]:
        if _CLIP_HEADER.match(l):
            blocks.append((no, l, []))
        elif blocks:
            blocks[-1][2].append((no, l))

    last_number = 0
    seen_numbers: set[int] = set()
    carry_loc = ("", "", "")      # (name, id, time)
    for header_no, header_text, body in blocks:
        m = _CLIP_HEADER_FULL.match(header_text)
        number = int(m.group(1))
        rest = m.group(2).strip()
        merged = bool(re.match(r"^(?:&|and\b|,|[–—-]\s*\d)", rest)) or "combined" in rest.lower().split(":")[0]
        title = re.sub(r"^[:\-–—.\s]+", "", rest) if not merged else rest
        clip = Clip(index=len(doc.clips) + 1, number=number, title=title, source_line=header_no)
        if merged:
            doc.issues.append(Issue("error", header_no, number, "merged_clip",
                                    f"'{header_text.strip()}' joins several clips. Give each clip its own 'Clip N:' block."))
        if number in seen_numbers:
            doc.issues.append(Issue("error", header_no, number, "duplicate_clip",
                                    f"Clip {number} appears more than once. If the file holds two versions of the story, remove one."))
        elif number < last_number:
            doc.issues.append(Issue("error", header_no, number, "clip_order",
                                    f"Clip {number} comes after clip {last_number}: clips must run in order."))
        elif number != last_number + 1 and doc.clips:
            doc.issues.append(Issue("warning", header_no, number, "clip_gap",
                                    f"Clip numbers jump from {last_number} to {number}."))
        seen_numbers.add(number)
        last_number = max(last_number, number)
        _parse_clip(clip, body, doc)
        if not clip.location_name:
            clip.location_name, clip.location_id, clip.time_of_day = carry_loc
            if not clip.location_name and doc.clips == []:
                doc.issues.append(Issue("error", header_no, number, "no_location",
                                        "The first clip has no '[INT. PLACE — TIME.' heading, so its place is unknown."))
        else:
            carry_loc = (clip.location_name, clip.location_id, clip.time_of_day)
        if clip.locations:
            last = clip.locations[-1]
            carry_loc = (last["name"], last["id"], last["time"])
        doc.clips.append(clip)

    # --- checks across the clip -----------------------------------------------------------------------------------
    unlisted: dict[str, int] = {}
    many_voices: list[int] = []
    for clip in doc.clips:
        clip.words = sum(l.words for l in clip.lines)
        if clip.words > SCRIPT_MAX_WORDS_PER_CLIP:
            over = clip.words - SCRIPT_MAX_WORDS_PER_CLIP
            doc.issues.append(Issue("error", clip.source_line, clip.number, "over_word_ceiling",
                                    f"{clip.words} words, {over} over the {SCRIPT_MAX_WORDS_PER_CLIP}-word ceiling "
                                    f"(inner-thought lines count). Nothing is trimmed automatically."))
        if len(clip.lines) > SCRIPT_MAX_LINES_PER_CLIP:
            doc.issues.append(Issue("error", clip.source_line, clip.number, "too_many_lines",
                                    f"{len(clip.lines)} spoken lines; a clip holds at most {SCRIPT_MAX_LINES_PER_CLIP}."))
        for l in clip.lines:
            if not l.listed:
                unlisted[l.speaker_raw] = unlisted.get(l.speaker_raw, 0) + 1
        voices = {l.speaker for l in clip.lines if l.kind in ("live", "off_screen")}
        if len(voices) > VOICE_REF_LIMIT:
            many_voices.append(clip.number)
        if not clip.lines:
            doc.issues.append(Issue("warning", clip.source_line, clip.number, "silent_clip",
                                    "No spoken lines in this clip (fine for a wordless beat)."))
    if many_voices:
        doc.issues.append(Issue("warning", None, None, "voice_refs",
                                f"{len(many_voices)} clip(s) have more than {VOICE_REF_LIMIT} different live voices "
                                f"(clips {', '.join(map(str, many_voices))}); kie.ai accepts only {VOICE_REF_LIMIT} reference voice "
                                f"samples per request, so the others are voiced from their written voice description."))
    doc.unlisted_speakers = sorted(unlisted)
    if unlisted:
        level = "warning" if allow_unlisted else "error"
        for name, n in sorted(unlisted.items()):
            first = next((c for c in doc.clips for l in c.lines if l.speaker_raw == name), None)
            doc.issues.append(Issue(level, first.source_line if first else None, first.number if first else None,
                                    "speaker_not_in_header",
                                    f"'{name}' speaks {n} time(s) but is not in the cast header, so there is no look for them."))
    return doc


_MARKER = re.compile(
    r"(?<![^\s\]\x00])((?:[A-Z][A-Z0-9.'\u2019\-]*)(?: [A-Z0-9][A-Z0-9.'\u2019\-]*){0,3})\s*(?:\(([^)]*)\))?\s*:(?!\d)")
_BOUNDARY = re.compile(
    r"\[|\x00|(?<![^\s\]\x00])(?:[A-Z][A-Z0-9.'\u2019\-]*)(?: [A-Z0-9][A-Z0-9.'\u2019\-]*){0,3}\s*(?:\([^)]*\))?\s*:(?!\d)")


def _parse_clip(clip: Clip, body: list[tuple[int, str]], doc: ScriptDoc) -> None:
    """Fill a clip from its body. The body is read as one stream, so a line may wrap anywhere and a paragraph may hold several
    lines of dialogue and [directions] one after the other; a blank line ends the dialogue line being read."""
    import bisect
    chars = doc.characters
    stream, starts, line_nos = "", [], []
    for no, l in body:
        if not l.strip():
            if stream and not stream.endswith("\x00"):
                stream += "\x00"
            continue
        starts.append(len(stream) + (1 if stream and not stream.endswith("\x00") else 0))
        line_nos.append(no)
        stream += (" " if stream and not stream.endswith("\x00") else "") + l.strip()

    def line_of(offset: int) -> int:
        i = bisect.bisect_right(starts, offset) - 1
        return line_nos[max(i, 0)] if line_nos else 0

    pending: list[dict] = []

    def add_direction(text: str, no: int) -> None:
        text = re.sub(r"\s+", " ", text.replace("\x00", " ")).strip()
        clip.directions.append({"text": text, "source_line": no})
        h = _heading(text)
        if h:
            name, tod = h
            loc = {"name": name, "id": _slug(name), "time": tod, "source_line": no}
            clip.locations.append(loc)
            if not clip.location_name:
                clip.location_name, clip.location_id, clip.time_of_day = name, loc["id"], tod
        if _FREEZE.search(text):
            clip.ends_with_to_be_continued = True

    pos, n = 0, len(stream)
    while pos < n:
        ch = stream[pos]
        if ch in " \x00":
            pos += 1
            continue
        if ch == "[":
            end = stream.find("]", pos)
            if end == -1:
                doc.issues.append(Issue("error", line_of(pos), clip.number, "unclosed_direction",
                                        "A '[' direction is never closed with ']'."))
                break
            add_direction(stream[pos + 1:end], line_of(pos))
            pos = end + 1
            continue
        m = _MARKER.match(stream, pos)
        nxt = _BOUNDARY.search(stream, (m.end() if m else pos) + (0 if m else 1))
        seg_end = nxt.start() if nxt else n
        if m:
            pending.append({"speaker_raw": m.group(1).strip(), "qualifier": (m.group(2) or "").strip(),
                            "text": re.sub(r"\s+", " ", stream[m.end():seg_end]).strip(), "line": line_of(pos)})
        else:
            stray = re.sub(r"\s+", " ", stream[pos:seg_end]).strip()
            if _WORD.search(stray):
                doc.issues.append(Issue("warning", line_of(pos), clip.number, "unrecognized_line",
                                        f"Text outside any 'NAME:' line or [direction] was ignored: '{stray[:70]}'"))
        pos = seg_end

    mention_text = " ".join(d["text"] for d in clip.directions)
    for p in pending:
        text, delivery = p["text"], []
        while True:
            m = re.match(r"^\(([^)]*)\)\s*(.*)$", text)
            if not m or not m.group(2).strip():
                break
            delivery.append(m.group(1).strip())
            text = m.group(2).strip()
        char = _resolve_speaker(p["speaker_raw"], chars)
        speaker = char.name if char else p["speaker_raw"].title()
        clip.lines.append(Line(
            speaker=speaker, speaker_raw=p["speaker_raw"], listed=char is not None, kind=_kind(p["qualifier"]),
            qualifier=p["qualifier"], delivery="; ".join(delivery), text=text, words=count_words(text),
            source_line=p["line"],
        ))
        if not text.strip():
            doc.issues.append(Issue("error", p["line"], clip.number, "empty_line",
                                    f"{p['speaker_raw']} has a line with no words."))
    clip.speakers = []
    for l in clip.lines:
        if l.speaker not in clip.speakers:
            clip.speakers.append(l.speaker)
    named = _mentions(mention_text + " " + " ".join(l.text for l in clip.lines), chars)
    clip.mentioned = [nm for nm in named if nm not in clip.speakers]


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------
def format_report(doc: ScriptDoc) -> str:
    out = []
    out.append(f"Script: {doc.title or '(no title)'}")
    out.append(f"Cast ({len(doc.characters)}): " + "; ".join(f"{c.name} ({c.age})" for c in doc.characters))
    total = sum(c.words for c in doc.clips)
    over = [c for c in doc.clips if c.words > SCRIPT_MAX_WORDS_PER_CLIP]
    out.append(f"Clips: {len(doc.clips)}   words: {total}   over the {SCRIPT_MAX_WORDS_PER_CLIP}-word ceiling: {len(over)}")
    out.append("")
    out.append(f"{'#':>3}  {'words':>5}  {'lines':>5}  {'V.O.':>4}  {'place':<34} title")
    for c in doc.clips:
        vo = sum(1 for l in c.lines if l.is_voiceover)
        flag = "  <-- OVER" if c.words > SCRIPT_MAX_WORDS_PER_CLIP else ""
        out.append(f"{c.number:>3}  {c.words:>5}  {len(c.lines):>5}  {vo:>4}  {c.location_name[:33]:<34} {c.title}{flag}")
    if doc.unlisted_speakers:
        out.append("")
        out.append("Speakers missing from the cast header: " + ", ".join(doc.unlisted_speakers))
    out.append("")
    if doc.errors:
        out.append(f"ERRORS ({len(doc.errors)}):")
        out.extend("  " + str(i) for i in doc.errors)
    else:
        out.append("No errors.")
    if doc.warnings:
        out.append(f"WARNINGS ({len(doc.warnings)}):")
        out.extend("  " + str(i) for i in doc.warnings)
    return "\n".join(out)


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    path, start, json_out, allow = argv[1], 1, None, "--allow-unlisted" in argv
    if "--start-line" in argv:
        start = int(argv[argv.index("--start-line") + 1])
    if "--json" in argv:
        json_out = argv[argv.index("--json") + 1]
    with open(path, encoding="utf-8-sig") as f:
        doc = parse_story_script(f.read(), start_line=start, allow_unlisted=allow)
    print(format_report(doc))
    if json_out:
        with open(json_out, "w", encoding="utf-8") as f:
            json.dump(doc.to_dict(), f, indent=2, ensure_ascii=False)
    return 1 if doc.errors else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
