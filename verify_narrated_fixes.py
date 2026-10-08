# -*- coding: utf-8 -*-
"""Offline check of the Hybrid Narrated Drama fixes. No OpenAI, no kie.ai, no credits.

Run it with:  docker-compose exec -T api python - < verify_narrated_fixes.py

It replays the real failures from job 488d9d90 against the validators, and covers the
multi-speaker clip support ported from movie_scene_multispeaker.py.
"""
import json
import hybrid_narrated_drama as hnd

ok = fail = 0


def check(label, condition, detail=""):
    global ok, fail
    if condition:
        ok += 1
        print(f"  PASS  {label}")
    else:
        fail += 1
        print(f"  FAIL  {label}  {detail}")


def say(speaker, line):
    return {"speaker": speaker, "line": line}


def turn(speaker, line, start, end, delivery="tense"):
    return {"speaker": speaker, "line": line, "delivery": delivery, "start_est": start, "end_est": end}


def appearance(**kw):
    base = {"casting": "woman in her late twenties", "hair_color": "dark brown",
            "hair_style": "tied back in a low ponytail", "build": "slim",
            "distinguishing_feature": "a scar through the left eyebrow",
            "wardrobe": "neat navy hotel uniform"}
    base.update(kw)
    return base


# ---------------------------------------------------------------- the bad plan
BAD = {
    "scene_bible": {
        "pov_protagonist": "Clara Vance",
        "characters": [
            {"name": "Clara Vance", "is_protagonist": True, "role": "night receptionist",
             "voice": "clear, light alto",
             "appearance": appearance(distinguishing_feature="anxious but determined posture")},
            {"name": "Mia Torres", "is_protagonist": False, "role": "co-worker",
             "voice": "warm, hurried mezzo",
             "appearance": appearance(hair_color="chestnut", hair_style="tied back in a bun",
                                      distinguishing_feature="none",
                                      wardrobe="matching navy hotel uniform")},
        ],
        "props": [{"id": "laundry_cart", "description": "a wheeled canvas laundry cart stacked with folded white sheets"}],
        "locations": [{"id": "lobby_front_desk", "description": "dim lobby", "layout": "desk centre",
                       "image_prompt": "a dim luxury hotel lobby at night, black marble reception desk, brass bell, lift bank at the rear",
                       "views": ["from the entrance looking at the desk", "from behind the desk looking out"]}],
    },
    "beats": [
        {"clip_number": 1, "cycle_number": 1, "delivery_mode": "voiceover", "location_id": "lobby_front_desk",
         "present_characters": ["Clara Vance"], "speaker_or_actor": "Clara Vance",
         "summary": "Clara clocks in.", "speech_budget": 9,
         "audio_lines": [say("Clara Vance", "I clocked in praying The Obsidian wouldn't betray me.")],
         "reveals": ["The Obsidian"]},
        {"clip_number": 2, "cycle_number": 1, "delivery_mode": "voiceover", "location_id": "lobby_front_desk",
         "present_characters": ["Clara Vance", "Mia Torres"], "speaker_or_actor": "Clara Vance",
         "summary": "Clara signs the ledger.", "speech_budget": 9,
         "audio_lines": [say("Clara Vance", "I needed this job, even if 404 owned midnight.")],
         "reveals": []},
        {"clip_number": 3, "cycle_number": 1, "delivery_mode": "dialogue", "location_id": "lobby_front_desk",
         "present_characters": ["Clara Vance", "Mia Torres"], "speaker_or_actor": "Mia Torres",
         "summary": "Mia warns her.", "speech_budget": 9,
         "audio_lines": [say("Mia Torres", "Clara, avoid Room 404. Julian Cross owns the night.")],
         "reveals": ["Room 404", "404", "Julian Cross"]},
        {"clip_number": 4, "cycle_number": 1, "delivery_mode": "shock_action", "location_id": "lobby_front_desk",
         "present_characters": ["Clara Vance", "Mia Torres"], "speaker_or_actor": "Mia Torres",
         "summary": "Mia grabs Clara's wrist.", "speech_budget": 0, "audio_lines": [], "reveals": []},
    ],
}

print("\n[1] The outline validator, against the real failures")
problems = hnd._check_narrated_outline(json.loads(json.dumps(BAD)), 4)
blob = " | ".join(problems)
check("a mood in appearance is rejected", "is a mood, not a permanent physical fact" in blob, blob)
check("empty distinguishing_feature is rejected", "distinguishing feature" in blob, blob)
check("Clara and Mia's identical hair is rejected", "same hair colour AND the same hair style" in blob, blob)
check("the shock beat handed to Mia is rejected", "not who the shot is about" in blob, blob)
check("the clip-2 '404' leak is caught", "404" in blob and "does not learn until clip 3" in blob, blob)

SAME_COLOUR = json.loads(json.dumps(BAD))
SAME_COLOUR["scene_bible"]["characters"][1]["appearance"]["hair_style"] = "long, worn loose"
blob2 = " | ".join(hnd._check_narrated_outline(SAME_COLOUR, 4))
check("sharing only a hair colour is rejected in a small cast", "both have brown hair" in blob2, blob2)

print("\n[2] A clean plan passes")
GOOD = json.loads(json.dumps(BAD))
gc = GOOD["scene_bible"]["characters"]
gc[0]["appearance"].update(hair_color="ash blonde", hair_style="short bob, worn loose",
                           distinguishing_feature="a scar through the left eyebrow")
gc[1]["appearance"].update(hair_color="jet black", hair_style="tied back in a bun",
                           distinguishing_feature="heavy black-framed glasses")
GOOD["beats"][1]["audio_lines"] = [say("Clara Vance", "After my firing, one mistake meant the street.")]
GOOD["beats"][3]["speaker_or_actor"] = "Clara Vance"
problems = hnd._check_narrated_outline(GOOD, 4)
check("no problems on a clean plan", not problems, " | ".join(problems))

print("\n[3] look and image_prompt are compiled from one source")
hnd._compile_character_visuals(GOOD["scene_bible"])
clara = GOOD["scene_bible"]["characters"][0]
check("look names the planned hair", "ash blonde" in clara["look"], clara["look"])
check("image_prompt names the SAME hair", "ash blonde" in clara["image_prompt"], clara["image_prompt"][:120])
check("image_prompt is a neutral lit portrait", "plain mid-grey seamless background" in clara["image_prompt"])
check("image_prompt carries photoreal keywords", "NO CGI" in clara["image_prompt"])
check("image_prompt has no scenery", "front desk" not in clara["image_prompt"].lower())

print("\n[4] The clip writer is not shown the future")
sys_p, usr_p = hnd._narrated_chapter_prompt("topic", 1, 4, GOOD["beats"][1], GOOD["scene_bible"], [],
                                            beats=GOOD["beats"])
whole = sys_p + usr_p
check("the clip-3 reveal is absent from the clip-2 prompt", "Julian Cross owns the night" not in whole)
check("beat 4 is absent from the clip-2 prompt", "grabs Clara's wrist" not in whole)
check("the story so far IS shown", "Clara clocks in" in whole)
check("the planned line is quoted as mandatory", "After my firing, one mistake meant the street." in whole)
check("the no-future rule is stated", "YOU DO NOT KNOW THE FUTURE" in sys_p)
check("the cast rule is stated", "THE BEAT'S CAST IS THE CLIP'S CAST" in sys_p)

print("\n[5] The chapter validator catches a reworded line and a dropped character")
bad_clip = {"clips": [{
    "clip_number": 2, "delivery_mode": "voiceover", "location_id": "lobby_front_desk",
    "shot": "[SAME SETUP] medium", "present_characters": ["Clara Vance"],
    "speech": [turn("Clara Vance", "I needed this job, even if 404 owned midnight.", 0.6, 4.3)],
    "action_steps": [{"start_time": 0.0, "character": "Clara Vance", "action": "stands still"}],
    "blocking": [{"character": "Clara Vance", "position": "behind the desk", "posture": "standing",
                  "screen_profile": "front", "frame_position": "centre frame", "eyeline": "down", "end_position": "behind the desk",
                  "end_posture": "standing", "end_screen_profile": "front", "end_eyeline": "down",
                  "awareness": "has not noticed the monitor", "in_frame": "visible"}],
}]}
problems = hnd._check_narrated_chapter(bad_clip, GOOD["beats"][1], GOOD["scene_bible"], None,
                                       clip_index=1, beats=GOOD["beats"])
blob = " | ".join(problems)
check("the reworded line is rejected", "the line was changed" in blob, blob)
check("Mia being dropped is rejected", "Mia Torres" in blob and "missing from blocking" in blob, blob)
check("the not-yet-revealed '404' is rejected", "has not revealed yet" in blob, blob)

print("\n[6] The Seedance prompt stops describing a face it is already showing")
clip = {"delivery_mode": "voiceover", "location_id": "lobby_front_desk", "shot": "[SAME SETUP] medium",
        "present_characters": ["Clara Vance"],
        "speech": [turn("Clara Vance", "After my firing, one mistake meant the street.", 0.6, 4.3)],
        "action_steps": [{"start_time": 0.0, "character": "Clara Vance", "action": "stands still"}],
        "blocking": [{"character": "Clara Vance", "position": "behind the desk", "posture": "standing",
                      "screen_profile": "front", "frame_position": "centre frame", "eyeline": "down", "end_position": "behind the desk",
                      "end_posture": "standing", "end_screen_profile": "front", "end_eyeline": "down",
                      "awareness": "has not noticed the monitor", "in_frame": "visible"}]}
prompt, imgs, auds = hnd.build_narrated_prompt(
    clip, GOOD["scene_bible"], {"Clara Vance": "http://img/clara.jpg"},
    {"lobby_front_desk": ["http://img/lobby.jpg"]}, {})
check("the character is tagged to their picture", "Clara Vance is @Image2" in prompt, prompt[:200])
check("the written look is NOT repeated beside it", "ash blonde" not in prompt, prompt[:300])
check("reference fidelity is demanded", "do not restyle, recolour or re-cast anyone" in prompt)

print("\n[7] Wordless beats: earned, not forced, and the camera stays with the POV")


def outline_with(beat_overrides, drop_shock=False):
    plan = json.loads(json.dumps(GOOD))
    if drop_shock:
        plan["beats"][3].update(delivery_mode="dialogue", speaker_or_actor="Mia Torres",
                                audio_lines=[say("Mia Torres", "You never listen to me, Clara. Not once.")],
                                speech_budget=8, present_characters=["Clara Vance", "Mia Torres"])
    else:
        plan["beats"][3].update(beat_overrides)
    return " | ".join(hnd._check_narrated_outline(plan, 4))


b = outline_with({"present_characters": [], "speaker_or_actor": ""})
check("an establishing shot with nobody on screen is allowed", not b, b)
b = outline_with({"present_characters": [], "speaker_or_actor": "Mia Torres"})
check("an establishing shot may not name an actor", "must be empty" in b, b)
b = outline_with({"present_characters": ["Mia Torres"], "speaker_or_actor": "Mia Torres"})
check("a reaction shot without the protagonist is rejected", "we watch from inside their head" in b, b)
b = outline_with({"present_characters": ["Clara Vance", "Mia Torres"], "speaker_or_actor": "Clara Vance"})
check("the protagonist's reaction, with others present, is allowed", not b, b)
b = outline_with({}, drop_shock=True)
check("a plan with NO wordless beat at all is allowed (no quota)", not b, b)

env_clip = {"clips": [{
    "clip_number": 4, "delivery_mode": "shock_action", "location_id": "lobby_front_desk",
    "shot": "[ANGLE CUT] The hotel seen from the rain-soaked street, every window dark but one.",
    "present_characters": [], "speech": [], "action_steps": [], "blocking": [],
}]}
env_beat = json.loads(json.dumps(GOOD["beats"][3]))
env_beat.update(present_characters=[], speaker_or_actor="")
b = " | ".join(hnd._check_narrated_chapter(env_clip, env_beat, GOOD["scene_bible"], None, clip_index=3,
                                           beats=GOOD["beats"]))
check("an empty establishing clip passes the clip validator", not b, b)
p, imgs, auds = hnd.build_narrated_prompt(env_clip["clips"][0], GOOD["scene_bible"],
                                          {"Clara Vance": "http://img/clara.jpg"},
                                          {"lobby_front_desk": ["http://img/lobby.jpg"]}, {})
check("the establishing prompt sends the place and no cast",
      "Cinematic environmental shot" in p and not auds, p[:160])

print("\n[8] Fatal vs cosmetic: what is allowed to reach kie.ai")
mixed = ["[SOFT] a line runs two words long", "the protagonist is not in the cast", "[SOFT] pacing is tight"]
check("hard problems are separated out", hnd._hard_problems(mixed) == ["the protagonist is not in the cast"])
check("soft problems keep their text, lose the marker",
      hnd._soft_problems(mixed) == ["a line runs two words long", "pacing is tight"])
check("no problems at all is handled", hnd._hard_problems([]) == [] and hnd._hard_problems(None) == [])

LONG = json.loads(json.dumps(GOOD))
LONG["beats"][1]["audio_lines"] = [say("Clara Vance",
                                       "After my firing, one single mistake meant the cold street outside tonight "
                                       "for me and for everyone who ever trusted me")]
probs = hnd._check_narrated_outline(LONG, 4)
check("an over-long line is a note, not a job-stopper", probs and not hnd._hard_problems(probs),
      f"hard={hnd._hard_problems(probs)}")

BROKEN = json.loads(json.dumps(GOOD))
BROKEN["beats"][0]["audio_lines"] = [say("Clara Vance", "Room 404 has been empty since the fire.")]
BROKEN["beats"][0]["reveals"] = []
BROKEN["beats"][1]["reveals"] = ["Room 404", "404"]
check("a real leak is still fatal", hnd._hard_problems(hnd._check_narrated_outline(BROKEN, 4)))

print("\n[9] Blocking continuity runs start -> end, not start -> start")


def blk(char, posture, prof, end_posture=None, end_prof=None, in_frame="visible", frame_position=None, end_fp=None):
    if frame_position is None:
        fp = "off screen" if in_frame in ("off screen", "has left") else "centre frame"
    else:
        fp = frame_position
    return {"character": char, "position": "at the desk", "posture": posture, "screen_profile": prof,
            "frame_position": fp,
            "eyeline": "forward", "end_position": "at the desk", "end_posture": end_posture or posture,
            "end_screen_profile": end_prof or prof,
            "end_frame_position": end_fp or fp, "end_eyeline": "forward",
            "awareness": "has not noticed the lift doors", "in_frame": in_frame}


def clip_with(blocking, speech=None, mode="voiceover"):
    return {"clips": [{
        "clip_number": 2, "delivery_mode": mode, "location_id": "lobby_front_desk",
        "shot": "[SAME SETUP] medium", "present_characters": [b["character"] for b in blocking],
        "speech": speech if speech is not None else [
            turn("Clara Vance", GOOD["beats"][1]["audio_lines"][0]["line"], 0.6, 4.3)],
        "action_steps": [{"start_time": 0.0, "character": "Clara Vance", "action": "lowers herself onto the stool"}],
        "blocking": blocking,
    }]}


prev = {"location_id": "lobby_front_desk",
        "blocking": [blk("Clara Vance", "standing", "front", end_posture="sitting"),
                     blk("Mia Torres", "standing", "side")]}
b = " | ".join(hnd._check_narrated_chapter(
    clip_with([blk("Clara Vance", "sitting", "front"), blk("Mia Torres", "standing", "side")]),
    GOOD["beats"][1], GOOD["scene_bible"], prev, clip_index=1, beats=GOOD["beats"]))
check("opening on the previous clip's ENDING pose is accepted", not b, b)

b = " | ".join(hnd._check_narrated_chapter(
    clip_with([blk("Clara Vance", "standing", "front"), blk("Mia Torres", "standing", "side")]),
    GOOD["beats"][1], GOOD["scene_bible"], prev, clip_index=1, beats=GOOD["beats"]))
check("opening on the previous clip's STARTING pose is now rejected",
      "the previous clip left them 'sitting'" in b, b)

moving = clip_with([blk("Clara Vance", "standing", "front", end_posture="kneeling"),
                    blk("Mia Torres", "standing", "side")])
p, _i, _a = hnd.build_narrated_prompt(moving["clips"][0], GOOD["scene_bible"],
                                      {"Clara Vance": "http://i/c.jpg", "Mia Torres": "http://i/m.jpg"},
                                      {"lobby_front_desk": ["http://i/l.jpg"]}, {})
check("a moving character is sent as an arc", "starts standing" in p and "ends kneeling" in p, p[-240:])
check("a still character is not padded with a fake arc",
      "Mia Torres: standing, screen side, held throughout" in p, p[-240:])

print("\n[10] Up to three people can speak in one clip")
TRIO = json.loads(json.dumps(GOOD))
TRIO["scene_bible"]["characters"].append(
    {"name": "Julian Cross", "is_protagonist": False, "role": "guest", "voice": "low baritone with a faint gravel",
     "appearance": appearance(casting="man in his early thirties", hair_color="jet black",
                              hair_style="short, swept back", build="tall and lean",
                              distinguishing_feature="a thin scar along the jaw",
                              wardrobe="dark tailored robe")})
TRIO["scene_bible"]["characters"][1]["appearance"]["hair_color"] = "copper red"
check("a character added without compiled visuals still renders",
      hnd.build_narrated_prompt(
          {"delivery_mode": "shock_action", "location_id": "lobby_front_desk", "shot": "[ANGLE CUT] close",
           "present_characters": ["Julian Cross"], "speech": [], "action_steps": [],
           "blocking": [blk("Julian Cross", "standing", "front")]},
          TRIO["scene_bible"], {}, {"lobby_front_desk": ["http://i/l.jpg"]}, {})[0] is not None)
hnd._compile_character_visuals(TRIO["scene_bible"])
TRIO["beats"][2].update(
    delivery_mode="dialogue", speaker_or_actor="Mia Torres", speech_budget=9,
    present_characters=["Clara Vance", "Mia Torres", "Julian Cross"],
    audio_lines=[say("Mia Torres", "Where is she?"), say("Clara Vance", "Gone."),
                 say("Julian Cross", "You are both lying.")])
probs = hnd._check_narrated_outline(TRIO, 4)
check("a three-speaker beat validates", not hnd._hard_problems(probs), " | ".join(probs))

FOUR = json.loads(json.dumps(TRIO))
FOUR["beats"][2]["audio_lines"].append(say("Clara Vance", "Stop."))
check("a four-turn beat is rejected", "at most 3 fit" in " | ".join(hnd._check_narrated_outline(FOUR, 4)),
      " | ".join(hnd._check_narrated_outline(FOUR, 4)))

TWO_VO = json.loads(json.dumps(TRIO))
TWO_VO["beats"][1]["audio_lines"] = [say("Clara Vance", "I needed the job."),
                                     say("Clara Vance", "I needed it badly.")]
check("a two-line voiceover beat is rejected",
      "takes exactly one line" in " | ".join(hnd._check_narrated_outline(TWO_VO, 4)))

GHOST = json.loads(json.dumps(TRIO))
GHOST["beats"][2]["audio_lines"] = [say("Whitlock", "Where is she?")]
check("an uncredited speaker is rejected",
      "not in the scene_bible" in " | ".join(hnd._check_narrated_outline(GHOST, 4)))

trio_blocking = [blk("Clara Vance", "standing", "front"), blk("Mia Torres", "standing", "side"),
                 blk("Julian Cross", "standing", "front")]
trio_speech = [turn("Mia Torres", "Where is she?", 0.5, 1.6),
               turn("Clara Vance", "Gone.", 1.8, 2.6),
               turn("Julian Cross", "You are both lying.", 2.9, 4.4)]
trio_clip = clip_with(trio_blocking, speech=trio_speech, mode="dialogue")
b = " | ".join(hnd._check_narrated_chapter(trio_clip, TRIO["beats"][2], TRIO["scene_bible"], None,
                                           clip_index=2, beats=TRIO["beats"]))
check("a three-turn clip matching its beat validates", not b, b)

overlap = clip_with(trio_blocking, speech=[turn("Mia Torres", "Where is she?", 0.5, 2.0),
                                           turn("Clara Vance", "Gone.", 1.5, 2.6),
                                           turn("Julian Cross", "You are both lying.", 2.9, 4.4)],
                    mode="dialogue")
check("overlapping turns are rejected",
      "Turns must not overlap" in " | ".join(hnd._check_narrated_chapter(
          overlap, TRIO["beats"][2], TRIO["scene_bible"], None, clip_index=2, beats=TRIO["beats"])))

short = clip_with(trio_blocking, speech=trio_speech[:2], mode="dialogue")
check("dropping one of the planned turns is rejected",
      "3 line(s), but you wrote 2" in " | ".join(hnd._check_narrated_chapter(
          short, TRIO["beats"][2], TRIO["scene_bible"], None, clip_index=2, beats=TRIO["beats"])))

swapped = clip_with(trio_blocking, speech=[turn("Clara Vance", "Where is she?", 0.5, 1.6),
                                           turn("Clara Vance", "Gone.", 1.8, 2.6),
                                           turn("Julian Cross", "You are both lying.", 2.9, 4.4)],
                    mode="dialogue")
check("giving a planned line to the wrong speaker is rejected",
      "gives this line to 'Mia Torres'" in " | ".join(hnd._check_narrated_chapter(
          swapped, TRIO["beats"][2], TRIO["scene_bible"], None, clip_index=2, beats=TRIO["beats"])))

print("\n[11] Three voices reach kie.ai as three references")
bank = {"Mia Torres": "http://a/mia.wav", "Clara Vance": "http://a/clara.wav",
        "Julian Cross": "http://a/julian.wav"}
p, imgs, auds = hnd.build_narrated_prompt(
    trio_clip["clips"][0], TRIO["scene_bible"],
    {c["name"]: f"http://i/{c['name'][0]}.jpg" for c in TRIO["scene_bible"]["characters"]},
    {"lobby_front_desk": ["http://i/l.jpg"]}, bank)
check("three reference audios are attached", len(auds) == 3, auds)
check("each speaker gets their own @Audio tag",
      all(f"@Audio{i}" in p for i in (1, 2, 3)), p)
check("every line is in the prompt",
      all(q in p for q in ("Where is she?", "Gone.", "You are both lying.")), p)
check("the turns carry their own windows", "[0.5s to 1.6s]" in p and "[2.9s to 4.4s]" in p, p)
check("the model is told they run back to back", "back to back in one continuous take" in p, p)
check("only the speaker's lips move", "everyone else listens with their mouth closed" in p, p)

repeat = clip_with(trio_blocking, speech=[turn("Mia Torres", "Where is she?", 0.5, 1.6),
                                          turn("Mia Torres", "Answer me.", 1.9, 3.0)], mode="dialogue")
p2, _i2, auds2 = hnd.build_narrated_prompt(
    repeat["clips"][0], TRIO["scene_bible"],
    {c["name"]: f"http://i/{c['name'][0]}.jpg" for c in TRIO["scene_bible"]["characters"]},
    {"lobby_front_desk": ["http://i/l.jpg"]}, bank)
check("one speaker twice reuses a single voice reference", len(auds2) == 1, auds2)

offscreen = clip_with([blk("Clara Vance", "standing", "front"),
                       blk("Julian Cross", "standing", "front", in_frame="off screen")],
                      speech=[turn("Julian Cross", "You come alone.", 0.6, 3.0)], mode="dialogue")
p3, _i3, _a3 = hnd.build_narrated_prompt(
    offscreen["clips"][0], TRIO["scene_bible"],
    {c["name"]: f"http://i/{c['name'][0]}.jpg" for c in TRIO["scene_bible"]["characters"]},
    {"lobby_front_desk": ["http://i/l.jpg"]}, bank)
check("an off-screen speaker comes from the receiver", "telephone receiver/off-screen" in p3, p3)
check("an on-screen speaker gets lip sync", "synchronized lip movement" in p, p)

print("\n[12] A location picture is the empty place")


def loc_plan(**over):
    plan = json.loads(json.dumps(GOOD))
    plan["scene_bible"]["locations"][0].update(over)
    return " | ".join(hnd._check_narrated_outline(plan, 4))


b = loc_plan(image_prompt="hotel doorway marked 404, heavy door cracked open, handsome dangerous man in threshold")
check("a person standing in a location plate is rejected", "describes a person" in b, b)
b = loc_plan(image_prompt="the dim lobby where Clara works the night desk")
check("a plate naming a character is rejected", "names the character" in b, b)
b = loc_plan(views=["from the entrance looking at the desk", "Clara POV through the cracked door"])
check("a viewpoint written as a character's POV is rejected", "names a person" in b, b)
b = loc_plan(views=["one view only"])
check("fewer than two viewpoints is rejected", "give 2 or 3 viewpoints" in b, b)

PLATE = json.loads(json.dumps(GOOD))
hnd._compile_bible_visuals(PLATE["scene_bible"])
plate = PLATE["scene_bible"]["locations"][0]["image_prompt"]
check("the compiled plate demands an empty room", "nobody in frame, no people at all" in plate, plate[-120:])
check("the compiled plate carries photoreal keywords", "NO CGI" in plate)
check("the writer's own description survives", "black marble reception desk" in plate)
hnd._compile_bible_visuals(PLATE["scene_bible"])
check("compiling twice does not double the wording", plate.count("NO CGI") == 1 and
      PLATE["scene_bible"]["locations"][0]["image_prompt"].count("NO CGI") == 1)
check("a compiled plate is not re-flagged by the validator",
      not [p for p in hnd._check_narrated_outline(PLATE, 4) if "image_prompt" in p],
      " | ".join(hnd._check_narrated_outline(PLATE, 4)))

print("\n[13] The prop diary")


def prop_clip(diary):
    c = clip_with([blk("Clara Vance", "standing", "front"), blk("Mia Torres", "standing", "side")])
    c["clips"][0]["prop_state"] = diary
    return c


good_diary = [{"prop_id": "laundry_cart", "holder": "scene", "in_frame": True,
               "state": "parked at the desk corner, stacked with clean linens"}]
b = " | ".join(hnd._check_narrated_chapter(prop_clip(good_diary), GOOD["beats"][1], GOOD["scene_bible"], None,
                                           clip_index=1, beats=GOOD["beats"]))
check("a valid diary entry passes", not b, b)

b = " | ".join(hnd._check_narrated_chapter(
    prop_clip([{"prop_id": "silver_case", "holder": "scene", "in_frame": True, "state": "open"}]),
    GOOD["beats"][1], GOOD["scene_bible"], None, clip_index=1, beats=GOOD["beats"]))
check("a prop that is not in the bible is rejected", "not in the Scene Bible props" in b, b)

b = " | ".join(hnd._check_narrated_chapter(
    prop_clip([{"prop_id": "laundry_cart", "holder": "Whitlock", "in_frame": True, "state": "pushed"}]),
    GOOD["beats"][1], GOOD["scene_bible"], None, clip_index=1, beats=GOOD["beats"]))
check("an unknown prop holder is rejected", "who is not in the Scene Bible" in b, b)

prev_with_prop = {"location_id": "lobby_front_desk",
                  "blocking": [blk("Clara Vance", "standing", "front"), blk("Mia Torres", "standing", "side")],
                  "prop_state": good_diary}

# A clip writes only the props it SEES or MOVES; leaving one out is how it says "off camera, unchanged",
# and the repair fills it back in so the stored diary stays complete. The model writing ~2 entries instead
# of ~18 was 39% of the run's visible output.
omitted = prop_clip([])["clips"][0]
b = " | ".join(hnd._check_narrated_chapter({"clips": [omitted]}, GOOD["beats"][1], GOOD["scene_bible"],
                                           prev_with_prop, clip_index=1, beats=GOOD["beats"]))
check("omitting an off-camera prop is no longer an error", "dropped from this one" not in b, b)

notes = hnd._repair_narrated_clip(omitted, GOOD["beats"][1], GOOD["scene_bible"], prev_clip=prev_with_prop)
check("the omitted prop is carried forward instead", any("laundry_cart" in n for n in notes), notes)
carried = [p for p in omitted["prop_state"] if p["prop_id"] == "laundry_cart"][0]
check("and it is carried as off camera", carried["in_frame"] is False, carried)
check("keeping the holder it had", carried["holder"] == good_diary[0]["holder"], carried)
check("and a state, not an empty string", bool((carried.get("state") or "").strip()), carried)

check("the prompt asks only for props in shot or changed",
      "every prop the camera SEES" in hnd._narrated_chapter_prompt(
          "topic", 1, 4, GOOD["beats"][1], GOOD["scene_bible"], [], beats=GOOD["beats"])[0])

pc = prop_clip(good_diary)["clips"][0]
p, _i, _a = hnd.build_narrated_prompt(pc, GOOD["scene_bible"],
                                      {"Clara Vance": "http://i/c.jpg", "Mia Torres": "http://i/m.jpg"},
                                      {"lobby_front_desk": ["http://i/l.jpg"]}, {})
check("props in shot reach the prompt with their fixed description",
      "Props in the shot: a wheeled canvas laundry cart" in p, p[:400])
check("a prop that is not in shot is left out",
      "Props in the shot" not in hnd.build_narrated_prompt(
          prop_clip([dict(good_diary[0], in_frame=False)])["clips"][0], GOOD["scene_bible"],
          {"Clara Vance": "http://i/c.jpg", "Mia Torres": "http://i/m.jpg"},
          {"lobby_front_desk": ["http://i/l.jpg"]}, {})[0])

print("\n[14] A banked voice comes from a usable line")
short, long_ = turn("Mia Torres", "Gone.", 1.8, 2.4), turn("Mia Torres", "Clara, avoid that room tonight.", 0.5, 3.0)
later = [{"audio_lines": [say("Mia Torres", "Clara, avoid Room 404 after midnight.")]}]
check("a long line is banked straight away", hnd.should_bank_voice(long_, "Mia Torres", [], 0))
check("a two-word line waits when a longer one is coming",
      not hnd.should_bank_voice(short, "Mia Torres", [{}] + later, 0))
check("a two-word line is used when nothing better ever comes",
      hnd.should_bank_voice(short, "Mia Torres", [{}, {"audio_lines": [say("Clara Vance", "Stop.")]}], 0))

print("\n[15] Awareness and the environment field")


def aware_clip(mode="voiceover", blocking=None, env=""):
    default = [blk("Clara Vance", "standing", "front"), blk("Mia Torres", "standing", "side")]
    c = clip_with(blocking if blocking is not None else default, mode=mode)
    c["clips"][0]["environment"] = env
    c["clips"][0]["prop_state"] = []
    return c


b = " | ".join(hnd._check_narrated_chapter(
    aware_clip(blocking=[blk("Mia Torres", "standing", "side")]),
    GOOD["beats"][1], GOOD["scene_bible"], None, clip_index=1, beats=GOOD["beats"]))
check("a voiceover over a scene the narrator is absent from is rejected",
      "they are not in the clip at all" in b, b)

b = " | ".join(hnd._check_narrated_chapter(
    aware_clip(blocking=[]), GOOD["beats"][1], GOOD["scene_bible"], None, clip_index=1, beats=GOOD["beats"]))
check("narration over a shot with nobody in it is allowed", "not in the clip at all" not in b, b)

b = " | ".join(hnd._check_narrated_chapter(
    aware_clip(env="a tall figure waits under the awning outside"),
    GOOD["beats"][1], GOOD["scene_bible"], None, clip_index=1, beats=GOOD["beats"]))
check("a person in the environment field is rejected", "describes a person" in b, b)

b = " | ".join(hnd._check_narrated_chapter(
    aware_clip(env="Clara's reflection shivers in the marble"),
    GOOD["beats"][1], GOOD["scene_bible"], None, clip_index=1, beats=GOOD["beats"]))
check("a character named in the environment field is rejected", "names 'Clara Vance'" in b, b)

b = " | ".join(hnd._check_narrated_chapter(
    aware_clip(env="the storm flares at the windows and the lift indicator ticks over"),
    GOOD["beats"][1], GOOD["scene_bible"], None, clip_index=1, beats=GOOD["beats"]))
check("a clean environment line passes", not b, b)

envclip = aware_clip(env="the brass bell still trembles and the monitor flashes 2:15 AM")["clips"][0]
p, _i, _a = hnd.build_narrated_prompt(envclip, GOOD["scene_bible"], {"Clara Vance": "http://i/c.jpg"},
                                      {"lobby_front_desk": ["http://i/l.jpg"]}, {})
check("the environment reaches the prompt", "The place itself: the brass bell still trembles" in p, p[:400])
check("what each character has noticed reaches the prompt",
      "What each one has noticed: Clara Vance has not noticed the lift doors" in p, p[-320:])
check("the model is told not to react to the unnoticed",
      "Nobody reacts to anything they have not noticed" in p)

print("\n[16] Step 1: Kie.ai retry ladder and voice banking space sanitization")
import tempfile
from pathlib import Path

# 1. Copyright retry with AUDIO_RETRY_NOTE
calls = []
def mock_gen_copyright(*args, **kw):
    calls.append(kw.get("prompt", ""))
    if len(calls) == 1:
        raise hnd.KieError("Task failed: audio output may be related to copyright restrictions")
    return {"task_id": "test_c", "video_url": "http://v/c.mp4", "credits_consumed": 19}

orig_gen = hnd.generate_clip
hnd.generate_clip = mock_gen_copyright
with tempfile.TemporaryDirectory() as td:
    res = hnd.render_narrated_clip(1, "Five-second shot. No background music.", [], [], interactive=False, out_dir=Path(td))
hnd.generate_clip = orig_gen

check("copyright failure triggers retry", len(calls) == 2, f"calls={len(calls)}")
check("retried prompt uses AUDIO_RETRY_NOTE", hnd.AUDIO_RETRY_NOTE in (calls[1] if len(calls) > 1 else ""), (calls[1] if len(calls) > 1 else ""))
check("copyright retry succeeds and returns dict", isinstance(res, dict) and res.get("video_url") == "http://v/c.mp4", str(res))

# 2. TimeoutError stops immediately without retry (prevent double-billing)
timeout_calls = []
def mock_gen_timeout(*args, **kw):
    timeout_calls.append(1)
    raise TimeoutError("polling exceeded 15 minutes")

hnd.generate_clip = mock_gen_timeout
with tempfile.TemporaryDirectory() as td:
    res = hnd.render_narrated_clip(2, "Test prompt", [], [], interactive=False, out_dir=Path(td))
hnd.generate_clip = orig_gen

check("TimeoutError halts immediately without duplicate calls", len(timeout_calls) == 1, f"calls={len(timeout_calls)}")
check("TimeoutError returns 'quit'", res == "quit", str(res))

# 3. Transient error retries up to CLIP_RETRIES times then quits
transient_calls = []
def mock_gen_transient(*args, **kw):
    transient_calls.append(1)
    raise hnd.KieError("Transient 500 error from kie.ai")

orig_sleep = hnd.time.sleep
hnd.time.sleep = lambda _: None
hnd.generate_clip = mock_gen_transient
with tempfile.TemporaryDirectory() as td:
    res = hnd.render_narrated_clip(3, "Test prompt", [], [], interactive=False, out_dir=Path(td))
hnd.generate_clip = orig_gen
hnd.time.sleep = orig_sleep

check("transient error retries CLIP_RETRIES times (1 initial + 2 retries = 3)", len(transient_calls) == 1 + hnd.CLIP_RETRIES, f"calls={len(transient_calls)}")
check("exhausted retries returns 'quit'", res == "quit", str(res))

# 4. Voice filename space sanitization & job destination folder
with tempfile.TemporaryDirectory() as td:
    job_dir = Path(td)
    fake_clip = job_dir / "clips" / "clip_01.mp4"
    fake_clip.parent.mkdir(parents=True, exist_ok=True)
    fake_clip.write_text("fake video bytes", encoding="utf-8")
    
    # Test safe name formatting
    safe_name = hnd.re.sub(r"[^\w\-]+", "_", "Clara Vance".strip().lower()).strip("_")
    check("speaker name space is replaced with underscore", safe_name == "clara_vance", safe_name)

print("\n[17] Step 2: Pose continuity soft/hard split and _profiles_conflict tightening")
# 1. Phrasing variations do NOT conflict
check("three-quarter left vs left three-quarter does not conflict",
      not hnd._profiles_conflict("three-quarter left", "left three-quarter"))
check("profile facing screen left vs profile left does not conflict",
      not hnd._profiles_conflict("profile facing screen left", "profile left"))

# 2. Genuine conflicts DO conflict
check("left vs right conflicts",
      hnd._profiles_conflict("three-quarter facing screen left", "profile facing screen right"))
check("frontal vs back conflicts",
      hnd._profiles_conflict("frontal facing camera", "back facing camera"))

# 3. Posture mismatch remains HARD, profile mismatch is SOFT
prev_clip = {"location_id": "lobby_front_desk",
             "blocking": [blk("Clara Vance", "standing", "screen left", end_posture="sitting", end_prof="screen left")]}

curr_posture_mismatch = clip_with([blk("Clara Vance", "standing", "screen left")])
probs_posture = hnd._check_narrated_chapter(curr_posture_mismatch, GOOD["beats"][1], GOOD["scene_bible"], prev_clip, clip_index=1, beats=GOOD["beats"])
check("posture mismatch is hard", any("opens with posture 'standing'" in p for p in hnd._hard_problems(probs_posture)))

prev_clip_same_posture = {"location_id": "lobby_front_desk",
                          "blocking": [blk("Clara Vance", "standing", "screen left", end_posture="standing", end_prof="screen left")]}
curr_profile_mismatch = clip_with([blk("Clara Vance", "standing", "screen right")])
probs_profile = hnd._check_narrated_chapter(curr_profile_mismatch, GOOD["beats"][1], GOOD["scene_bible"], prev_clip_same_posture, clip_index=1, beats=GOOD["beats"])
check("profile mismatch is in problems", any("opens facing 'screen right'" in p for p in probs_profile))
check("profile mismatch is marked [SOFT]", any(p.startswith("[SOFT]") and "opens facing 'screen right'" in p for p in probs_profile))
check("profile mismatch is NOT in hard problems", not any("opens facing 'screen right'" in p for p in hnd._hard_problems(probs_profile)))

print("\n[18] Step 3: repair before retry")

_rbeat = {"delivery_mode": "dialogue", "location_id": "lobby_front_desk",
          "present_characters": ["Clara Vance", "Mia Torres"], "speaker_or_actor": "Mia Torres",
          "summary": "Mia warns her.", "speech_budget": 9,
          "audio_lines": [say("Mia Torres", "Clara, avoid that room tonight."),
                          say("Clara Vance", "Rich guests never scare me.")],
          "reveals": []}


def _rclip(**over):
    c = {"clip_number": 2, "delivery_mode": "dialogue", "location_id": "lobby_front_desk",
         "shot": "[SAME SETUP] two-shot", "present_characters": ["Clara Vance", "Mia Torres"],
         "speech": [turn("Mia Torres", "Clara, avoid that room tonight.", 0.5, 2.4),
                    turn("Clara Vance", "Rich guests never scare me.", 2.6, 4.4)],
         "environment": "", "prop_state": [],
         "action_steps": [{"start_time": 0.4, "character": "Mia Torres", "action": "leans in"}],
         "blocking": [blk("Clara Vance", "standing", "front"), blk("Mia Torres", "standing", "side")]}
    c.update(over)
    return c


# 1. timing is arithmetic, not a judgement call: repair it, never retry it
overlapped = _rclip(speech=[turn("Mia Torres", "Clara, avoid that room tonight.", 0.5, 3.0),
                            turn("Clara Vance", "Rich guests never scare me.", 1.2, 6.9)])
notes = hnd._repair_narrated_clip(overlapped, _rbeat, GOOD["scene_bible"])
check("overlapping windows are repaired, not retried", any("re-spaced" in n for n in notes), notes)
check("the repaired windows are valid", hnd._turn_windows_valid(overlapped["speech"]), overlapped["speech"])
check("speaker order survives the re-spacing",
      [t["speaker"] for t in overlapped["speech"]] == ["Mia Torres", "Clara Vance"])

ok_timing = _rclip()
check("valid windows are left alone", not hnd._repair_narrated_clip(ok_timing, _rbeat, GOOD["scene_bible"]))

# 2. a prop that goes unmentioned simply did not change
prev_props = {"location_id": "lobby_front_desk", "prop_state": [
    {"prop_id": "laundry_cart", "holder": "Clara Vance", "in_frame": True, "state": "stacked with linens"}]}
dropped = _rclip()
notes = hnd._repair_narrated_clip(dropped, _rbeat, GOOD["scene_bible"], prev_clip=prev_props)
check("a dropped prop is carried forward", any("laundry_cart" in n for n in notes), notes)
carried = dropped["prop_state"][0]
check("the carried prop keeps its holder and leaves the frame",
      carried["holder"] == "Clara Vance" and carried["in_frame"] is False, carried)

# 3. the model gets ONE chance at the plan's words before they are taken from it
drift = _rclip(speech=[turn("Mia Torres", "Stay away from that room, Clara.", 0.5, 2.4),
                       turn("Clara Vance", "Rich guests never scare me.", 2.6, 4.4)])
check("a drifted line is NOT repaired on the first attempt",
      not any("Master Plan" in n for n in hnd._repair_narrated_clip(drift, _rbeat, GOOD["scene_bible"], attempt=0)))

drift2 = _rclip(speech=[turn("Mia Torres", "Stay away from that room, Clara.", 0.5, 2.4),
                        turn("Clara Vance", "Rich guests never scare me.", 2.6, 4.4)])
notes = hnd._repair_narrated_clip(drift2, _rbeat, GOOD["scene_bible"], attempt=1)
check("a drifted line IS repaired on the second", any("Master Plan" in n for n in notes), notes)
check("the repaired line is the plan's, word for word",
      drift2["speech"][0]["line"] == "Clara, avoid that room tonight.", drift2["speech"][0])
check("the repaired lines get valid windows", hnd._turn_windows_valid(drift2["speech"]))

# 4. a missing cast member goes off screen only when the alternative is failing the clip
missing = _rclip(blocking=[blk("Clara Vance", "standing", "front")])
check("a missing beat character is NOT added early",
      not any("off screen" in n for n in hnd._repair_narrated_clip(missing, _rbeat, GOOD["scene_bible"], attempt=1)))

missing2 = _rclip(blocking=[blk("Clara Vance", "standing", "front")])
notes = hnd._repair_narrated_clip(missing2, _rbeat, GOOD["scene_bible"], attempt=3, final=True)
check("a missing beat character is placed off screen on the last attempt",
      any("Mia Torres" in n for n in notes), notes)
added = [b for b in missing2["blocking"] if b["character"] == "Mia Torres"][0]
check("the added character is off screen, not on it", added["in_frame"] == "off screen", added)

check("a clip script gets more retries than the outline", hnd.CHAPTER_RETRIES > hnd.SCRIPT_RETRIES,
      f"{hnd.CHAPTER_RETRIES} vs {hnd.SCRIPT_RETRIES}")

print("\n[19] Step 4: Camera directives, 180-degree rule, and audio lead-in trimming")

# 1. Schema requires frame_position and enum constraints
schema = hnd._narrated_chapter_schema(["lobby_front_desk"], ["Clara Vance"], ["laundry_cart"])
blocking_props = schema["properties"]["clips"]["items"]["properties"]["blocking"]["items"]["properties"]
blocking_req = schema["properties"]["clips"]["items"]["properties"]["blocking"]["items"]["required"]
check("frame_position is in blocking properties", "frame_position" in blocking_props)
check("frame_position is required in schema", "frame_position" in blocking_req)
check("frame_position enum matches FRAME_POSITIONS", blocking_props["frame_position"]["enum"] == hnd.FRAME_POSITIONS)

# 2. _check_narrated_chapter validates frame_position
bad_fp_clip = clip_with([blk("Clara Vance", "standing", "front", frame_position="top left")])
probs_bad_fp = hnd._check_narrated_chapter(bad_fp_clip, GOOD["beats"][1], GOOD["scene_bible"], None, clip_index=1, beats=GOOD["beats"])
check("invalid frame_position is rejected", any("must be one of" in p and "top left" in p for p in probs_bad_fp), probs_bad_fp)

missing_fp_clip = clip_with([{"character": "Clara Vance", "position": "at desk", "posture": "standing", "screen_profile": "front",
                              "eyeline": "forward", "end_position": "at desk", "end_posture": "standing", "end_screen_profile": "front",
                              "end_eyeline": "forward", "awareness": "aware", "in_frame": "visible"}])
probs_missing_fp = hnd._check_narrated_chapter(missing_fp_clip, GOOD["beats"][1], GOOD["scene_bible"], None, clip_index=1, beats=GOOD["beats"])
check("missing frame_position is rejected", any("must be one of" in p for p in probs_missing_fp), probs_missing_fp)

vis_off_clip = clip_with([blk("Clara Vance", "standing", "front", frame_position="off screen", in_frame="visible"),
                           blk("Mia Torres", "standing", "side")])
probs_vis_off = hnd._check_narrated_chapter(vis_off_clip, GOOD["beats"][1], GOOD["scene_bible"], None, clip_index=1, beats=GOOD["beats"])
check("visible character with frame_position off screen is rejected", any("cannot be 'off screen'" in p for p in probs_vis_off), probs_vis_off)

off_vis_clip = clip_with([blk("Clara Vance", "standing", "front", frame_position="frame left", in_frame="off screen"),
                          blk("Mia Torres", "standing", "side")])
probs_off_vis = hnd._check_narrated_chapter(off_vis_clip, GOOD["beats"][1], GOOD["scene_bible"], None, clip_index=1, beats=GOOD["beats"])
check("off-screen character with on-screen frame_position is rejected", any("must be 'off screen'" in p for p in probs_off_vis), probs_off_vis)

# 3. 180-degree rule soft warning
prev_left_clip = {"location_id": "lobby_front_desk",
                  "blocking": [blk("Clara Vance", "standing", "screen left", frame_position="frame left")]}
curr_right_clip = clip_with([blk("Clara Vance", "standing", "screen left", frame_position="frame right")])
probs_180 = hnd._check_narrated_chapter(curr_right_clip, GOOD["beats"][1], GOOD["scene_bible"], prev_left_clip, clip_index=1, beats=GOOD["beats"])
check("character flipping frame left to right triggers 180-degree note", any("180-degree rule" in p for p in probs_180), probs_180)
check("180-degree note is marked [SOFT]", any(p.startswith("[SOFT]") and "180-degree rule" in p for p in probs_180))
check("180-degree note is NOT in hard problems", not any("180-degree rule" in p for p in hnd._hard_problems(probs_180)))

# Moving from frame left to centre frame is allowed (no 180-degree flip)
curr_centre_clip = clip_with([blk("Clara Vance", "standing", "screen left", frame_position="centre frame")])
probs_centre = hnd._check_narrated_chapter(curr_centre_clip, GOOD["beats"][1], GOOD["scene_bible"], prev_left_clip, clip_index=1, beats=GOOD["beats"])
check("moving to centre frame does not trigger 180-degree warning", not any("180-degree rule" in p for p in probs_centre), probs_centre)

# 4. build_narrated_prompt carries frame_position in CONTINUITY ANCHOR
fp_prompt_clip = {"delivery_mode": "voiceover", "location_id": "lobby_front_desk", "shot": "[SAME SETUP] medium",
                  "present_characters": ["Clara Vance"],
                  "speech": [turn("Clara Vance", "After my firing, one mistake meant the street.", 0.6, 4.3)],
                  "action_steps": [{"start_time": 0.0, "character": "Clara Vance", "action": "stands still"}],
                  "blocking": [blk("Clara Vance", "standing", "front", frame_position="frame left")]}
fp_prompt, _, _ = hnd.build_narrated_prompt(fp_prompt_clip, GOOD["scene_bible"], {}, {}, {})
check("CONTINUITY ANCHOR carries frame_position", "frame left" in fp_prompt, fp_prompt)

# 5. Cinematic Camera Policy in prompt separates lighting into environment
sys_prompt, _ = hnd._narrated_chapter_prompt("A tense thriller", 1, 4, GOOD["beats"][1], GOOD["scene_bible"], [bad_clip["clips"][0]])
check("prompt contains CINEMATIC CAMERA POLICY", "CINEMATIC CAMERA POLICY" in sys_prompt)
check("prompt contains ESTABLISHING PHASE master shot guidance", "ESTABLISHING PHASE" in sys_prompt)
check("prompt contains COVERAGE PHASE angle cut guidance", "COVERAGE PHASE" in sys_prompt)
check("prompt explicitly delegates lighting to environment", 'Lighting and room atmosphere belong in "environment", NOT in "shot"' in sys_prompt)

# 6. Audio lead-in trimming enabled in app.py for narrated_drama
check("app trims logic trims narrated_drama on clips > 0",
      ("narrated_drama" in ("talking_head", "narrated_drama") and 1 > 0) is True and
      ("narrated_drama" in ("talking_head", "narrated_drama") and 0 > 0) is False)

# 7. Deterministic repair of missing or off-screen frame_position
rep_clip = _rclip(blocking=[{"character": "Clara Vance", "position": "at desk", "posture": "standing", "screen_profile": "front",
                             "eyeline": "forward", "end_position": "at desk", "end_posture": "standing", "end_screen_profile": "front",
                             "end_eyeline": "forward", "awareness": "aware", "in_frame": "visible", "frame_position": None}])
rep_notes = hnd._repair_narrated_clip(rep_clip, _rbeat, GOOD["scene_bible"])
check("missing frame_position is repaired to centre frame", rep_clip["blocking"][0]["frame_position"] == "centre frame")
check("repair notes record frame_position defaulted", any("defaulted frame_position" in n for n in rep_notes), rep_notes)

# 8. Camera work directives, fluid motion, and tag checks
check("prompt contains STORY-CRITICAL MOVEMENT ON CAMERA guidance", "STORY-CRITICAL MOVEMENT ON CAMERA" in sys_prompt)
check("prompt contains EXITS THAT LEAVE OTHERS ALONE guidance", "EXITS THAT LEAVE OTHERS ALONE" in sys_prompt)
check("prompt contains Fluid cinematic physical motion throughout", "Fluid cinematic physical motion throughout" in fp_prompt)

no_tag_clip = clip_with([
    blk("Clara Vance", "standing", "screen left", frame_position="frame left"),
    blk("Mia Torres", "standing", "side")
])
no_tag_clip["clips"][0]["shot"] = "Camera placed at waist height two metres from the desk"
probs_no_tag = hnd._check_narrated_chapter(no_tag_clip, GOOD["beats"][1], GOOD["scene_bible"], prev_left_clip, clip_index=1, beats=GOOD["beats"])
check("missing camera continuity tag triggers soft warning", any("camera continuity tag [SAME SETUP] or [ANGLE CUT]" in p for p in probs_no_tag), probs_no_tag)
check("missing camera continuity tag warning is [SOFT]", any(p.startswith("[SOFT]") and "camera continuity tag" in p for p in probs_no_tag))

rep_shot_clip = _rclip()
rep_shot_clip["shot"] = "Camera placed at waist height facing Clara."
rep_shot_notes = hnd._repair_narrated_clip(rep_shot_clip, _rbeat, GOOD["scene_bible"], prev_clip={"location_id": "lobby_front_desk"})
check("missing camera tag is repaired with tag prefix", rep_shot_clip["shot"].startswith("[SAME SETUP]") or rep_shot_clip["shot"].startswith("[ANGLE CUT]"))
check("repair notes record camera tag prepended", any("prepended" in n and "camera continuity tag" in n for n in rep_shot_notes), rep_shot_notes)

print("\n[20] Step 5: Long videos planned in acts & location scaling (§5 & §9)")

# 1. Detect premise act count
check("premise 'in 7 acts' detected as 7", hnd._detect_premise_act_count("A revenge thriller in 7 acts") == 7)
check("premise 'four-act drama' detected as 4", hnd._detect_premise_act_count("A four-act drama set in Paris") == 4)
check("premise 'three acts' detected as 3", hnd._detect_premise_act_count("Three acts of betrayal and deception") == 3)
check("unspecified acts returns None", hnd._detect_premise_act_count("A thrilling story about a heist") is None)
check("out-of-range act count returns None", hnd._detect_premise_act_count("A 1-act monologue") is None)

# 2. Normalize act spans
raw_acts_gap = [
    {"act_number": 1, "start_clip": 1, "end_clip": 14},
    {"act_number": 2, "start_clip": 16, "end_clip": 30},
    {"act_number": 3, "start_clip": 31, "end_clip": 45},
    {"act_number": 4, "start_clip": 46, "end_clip": 58},
]
norm_acts = hnd._normalize_act_spans(raw_acts_gap, 60)
check("normalized act 1 starts at 1", norm_acts[0]["start_clip"] == 1)
check("normalized act 2 closes the gap", norm_acts[1]["start_clip"] == 15)
check("normalized act 4 ends at total_clips 60", norm_acts[3]["end_clip"] == 60)
check("all act spans contiguous without gaps",
      all(norm_acts[i]["start_clip"] == norm_acts[i-1]["end_clip"] + 1 for i in range(1, len(norm_acts))))

# 3. Plan act batches: splits > 20 and merges < 6
acts_with_large = [
    {"act_number": 1, "start_clip": 1, "end_clip": 26, "title": "Long Act 1"},
    {"act_number": 2, "start_clip": 27, "end_clip": 40, "title": "Normal Act 2"},
]
batches_large = hnd._plan_act_batches(acts_with_large)
check("act with 26 clips is split into sub-batches", len(batches_large) == 3)
check("split sub-batches are <= 20 clips", all(b["clip_count"] <= 20 for b in batches_large))

acts_with_small = [
    {"act_number": 1, "start_clip": 1, "end_clip": 4, "title": "Short Act 1"},
    {"act_number": 2, "start_clip": 5, "end_clip": 16, "title": "Normal Act 2"},
    {"act_number": 3, "start_clip": 17, "end_clip": 30, "title": "Act 3"},
]
batches_small = hnd._plan_act_batches(acts_with_small)
check("act with 4 clips merges with adjacent act", len(batches_small) == 2)
check("merged batch covers clips 1 to 16", batches_small[0]["start_clip"] == 1 and batches_small[0]["end_clip"] == 16)

# 4. Location scaling (§9) soft checks in _check_narrated_outline
loc2_beats = []
for i in range(1, 61):
    loc_id = "reception" if i <= 30 else "office"
    mode = "voiceover" if i % 4 == 1 else "dialogue"
    lines = [{"speaker": "Clara Vance", "line": "We cannot let them see."}]
    loc2_beats.append({
        "clip_number": i, "cycle_number": (i - 1) // 4 + 1, "delivery_mode": mode,
        "location_id": loc_id, "present_characters": ["Clara Vance"], "speaker_or_actor": "Clara Vance",
        "summary": f"Beat {i}", "speech_budget": 6, "audio_lines": lines, "reveals": []
    })
loc2_outline = {
    "scene_bible": GOOD["scene_bible"],
    "beats": loc2_beats
}
loc2_probs = hnd._check_narrated_outline(loc2_outline, 60)
check("fewer than 3 locations in 60 clips triggers location variety note",
      any("Only 2 distinct locations used" in p for p in loc2_probs), loc2_probs)
check("location variety note is [SOFT]",
      any("[SOFT] Location variety:" in p for p in loc2_probs))
check("location variety note is NOT in hard problems",
      not any("Location variety" in p for p in hnd._hard_problems(loc2_probs)))

# Breakdown location scaling check
few_loc_breakdown = {
    "scene_bible": {
        "pov_protagonist": "Clara Vance",
        "characters": GOOD["scene_bible"]["characters"],
        "locations": [{"id": "lobby", "description": "dim lobby", "image_prompt": "empty lobby", "views": ["a", "b"]}],
        "props": []
    },
    "acts": [
        {"act_number": 1, "start_clip": 1, "end_clip": 30, "primary_locations": ["lobby"]},
        {"act_number": 2, "start_clip": 31, "end_clip": 60, "primary_locations": ["lobby"]}
    ]
}
few_loc_probs = hnd._check_act_breakdown(few_loc_breakdown, 60)
check("breakdown with < 3 locations triggers location variety note", any("Location variety" in p for p in few_loc_probs), few_loc_probs)
check("breakdown location variety note is [SOFT]", any(p.startswith("[SOFT]") and "Location variety" in p for p in few_loc_probs))

# Dominant location (> 70% of 60 = > 42 clips)
loc_dom_beats = []
for i in range(1, 61):
    loc_id = "reception" if i <= 45 else ("office" if i <= 52 else "boardroom")
    mode = "voiceover" if i % 4 == 1 else "dialogue"
    lines = [{"speaker": "Clara Vance", "line": "We cannot let them see."}]
    loc_dom_beats.append({
        "clip_number": i, "cycle_number": (i - 1) // 4 + 1, "delivery_mode": mode,
        "location_id": loc_id if loc_id in ("reception", "office") else "reception",
        "present_characters": ["Clara Vance"], "speaker_or_actor": "Clara Vance",
        "summary": f"Beat {i}", "speech_budget": 6, "audio_lines": lines, "reveals": []
    })
loc_dom_outline = {"scene_bible": GOOD["scene_bible"], "beats": loc_dom_beats}
loc_dom_probs = hnd._check_narrated_outline(loc_dom_outline, 60)
check("dominant location covering > 70% clips triggers soft note",
      any("covers" in p and "%" in p for p in loc_dom_probs), loc_dom_probs)

# 5. Single-shot outline threshold: < 30 clips uses single shot
single_shot_called = []
def mock_ask_single(sys_p, usr_p, tag, schema, model=None):
    single_shot_called.append(tag)
    return GOOD

orig_ask = hnd._ask_openai_json
hnd._ask_openai_json = mock_ask_single
try:
    data_15, _ = hnd.write_narrated_outline("Short heist", 75, 4)
    check("< 30 clips uses single-shot outline ('narrated_outline')",
          single_shot_called == ["narrated_outline"], single_shot_called)
finally:
    hnd._ask_openai_json = orig_ask

# 6. Act-based 60-clip generation (the main test)
calls_log = []
def mock_ask_60(sys_p, usr_p, tag, schema, model=None):
    calls_log.append({"tag": tag, "sys": sys_p, "usr": usr_p})
    if tag == "narrated_act_breakdown":
        return {
            "scene_bible": {
                "pov_protagonist": "Clara Vance",
                "characters": [
                    {
                        "name": "Clara Vance", "is_protagonist": True, "role": "Lead auditor",
                        "appearance": {"casting": "British, 28", "hair_color": "auburn", "hair_style": "short bob",
                                       "build": "slim", "distinguishing_feature": "silver eyebrow stud", "wardrobe": "dark trench coat"},
                        "voice": "low smoky alto"
                    },
                    {
                        "name": "Julian Cross", "is_protagonist": False, "role": "Hotel Director",
                        "appearance": {"casting": "European, 45", "hair_color": "silver", "hair_style": "slicked back",
                                       "build": "tall", "distinguishing_feature": "thin scar on jaw", "wardrobe": "charcoal suit"},
                        "voice": "deep gravelly baritone"
                    }
                ],
                "props": [],
                "locations": [
                    {"id": "lobby", "description": "Marble lobby with revolving door.", "layout": "Main door east, desk centre.", "image_prompt": "Empty marble lobby", "views": ["from desk", "from door"]},
                    {"id": "boardroom", "description": "Glass boardroom.", "layout": "Table centre, window south.", "image_prompt": "Empty boardroom", "views": ["from table", "from window"]},
                    {"id": "vault", "description": "Steel vault.", "layout": "Vault door west.", "image_prompt": "Empty vault", "views": ["from door", "from corner"]},
                    {"id": "rooftop", "description": "Windy rooftop.", "layout": "Helipad centre.", "image_prompt": "Empty rooftop", "views": ["from helipad", "from ledge"]},
                ]
            },
            "acts": [
                {"act_number": 1, "title": "Infiltration", "primary_locations": ["lobby"], "dramatic_question": "Can Clara enter?", "start_clip": 1, "end_clip": 15, "summary": "Clara enters lobby."},
                {"act_number": 2, "title": "Confrontation", "primary_locations": ["boardroom"], "dramatic_question": "Does Julian suspect?", "start_clip": 16, "end_clip": 30, "summary": "Julian confronts Clara."},
                {"act_number": 3, "title": "The Heist", "primary_locations": ["vault"], "dramatic_question": "Can she breach vault?", "start_clip": 31, "end_clip": 45, "summary": "Clara cracks the vault."},
                {"act_number": 4, "title": "Escape", "primary_locations": ["rooftop"], "dramatic_question": "Will she escape?", "start_clip": 46, "end_clip": 60, "summary": "Rooftop escape."},
            ]
        }
    elif tag.startswith("narrated_act_beats_"):
        batch_idx = int(tag.split("_")[-1])
        start = (batch_idx - 1) * 15 + 1
        end = batch_idx * 15
        loc = ["lobby", "boardroom", "vault", "rooftop"][batch_idx - 1]
        batch_beats = []
        for i in range(start, end + 1):
            mode = "voiceover" if i % 4 == 1 else "dialogue"
            spk = "Clara Vance" if mode == "voiceover" else "Julian Cross"
            line = "I stepped silently into the cold corridor light." if mode == "voiceover" else "You are not supposed to be here tonight Clara."
            reveals = [f"Secret Code {i}"] if i % 15 == 0 else []
            batch_beats.append({
                "clip_number": i, "cycle_number": (i - 1) // 4 + 1, "delivery_mode": mode,
                "location_id": loc, "present_characters": ["Clara Vance", "Julian Cross"],
                "speaker_or_actor": spk, "summary": f"Beat {i}", "speech_budget": len(line.split()),
                "audio_lines": [{"speaker": spk, "line": line}], "reveals": reveals
            })
        return {"beats": batch_beats}
    return {}

hnd._ask_openai_json = mock_ask_60
try:
    full_60, problems_60 = hnd.write_narrated_outline("A high stakes heist across 4 acts", 300, 60)
    check("60-clip outline produces 1 breakdown call + 4 act beat calls", len(calls_log) == 5, len(calls_log))
    check("first call is narrated_act_breakdown", calls_log[0]["tag"] == "narrated_act_breakdown")
    check("subsequent calls are act beats 1 to 4", [c["tag"] for c in calls_log[1:]] == [f"narrated_act_beats_{i}" for i in range(1, 5)])

    # Prompt context check: prior beats included, future beats EXCLUDED
    act1_usr = calls_log[1]["usr"]
    act2_usr = calls_log[2]["usr"]
    act3_usr = calls_log[3]["usr"]
    act4_usr = calls_log[4]["usr"]

    check("act 1 prompt contains NO future beats", "Clip 16" not in act1_usr and "Clip 45" not in act1_usr)
    check("act 2 prompt contains prior beats from act 1", "Clip 1" in act2_usr or "Clips 1 to 15" in act2_usr)
    check("act 2 prompt contains NO future beats", "Clip 31" not in act2_usr and "Clip 46" not in act2_usr)
    check("act 3 prompt contains NO future beats", "Clip 46" not in act3_usr)
    check("act 4 prompt contains prior beats from act 3", "Clips 1 to 45" in act4_usr or "Clip 45" in act4_usr)

    check("full 60 beats returned", len(full_60["beats"]) == 60)
    check("beat numbering is continuous 1..60", [b["clip_number"] for b in full_60["beats"]] == list(range(1, 61)))
    check("acts returned in full data", len(full_60.get("acts", [])) == 4)
finally:
    hnd._ask_openai_json = orig_ask

# 7. Cross-act reveal leak rejection
leak_beats = json.loads(json.dumps(full_60["beats"]))
# Beat 2 in Act 1 mentions "Vault Cipher", which is only revealed in Beat 35 in Act 3
leak_beats[1]["audio_lines"] = [{"speaker": "Julian Cross", "line": "Do you have the Vault Cipher with you?"}]
leak_beats[34]["reveals"] = ["Vault Cipher"]
leak_outline = {"scene_bible": full_60["scene_bible"], "beats": leak_beats}
leak_probs = hnd._check_narrated_outline(leak_outline, 60)
check("cross-act reveal leak is detected",
      any("Vault Cipher" in p or "vault cipher" in p for p in leak_probs), leak_probs)
check("cross-act reveal leak is a HARD problem",
      any("vault cipher" in p.lower() for p in hnd._hard_problems(leak_probs)))

# 8. Narrated Drama continuation outline
cont_calls = []
def mock_ask_cont(sys_p, usr_p, tag, schema, model=None):
    cont_calls.append(tag)
    modes = ["voiceover", "dialogue", "dialogue", "voiceover", "dialogue"]
    return {
        "beats": [
            {
                "clip_number": 61 + i, "cycle_number": 16,
                "delivery_mode": modes[i],
                "location_id": "rooftop", "present_characters": ["Clara Vance"],
                "speaker_or_actor": "Clara Vance", "summary": f"Continuation beat {i+1}",
                "speech_budget": 7, "audio_lines": [{"speaker": "Clara Vance", "line": "The helicopter finally arrived right in time."}],
                "reveals": []
            } for i in range(5)
        ]
    }

hnd._ask_openai_json = mock_ask_cont
try:
    cont_data, cont_probs = hnd.write_narrated_continuation_outline(
        "A high stakes heist", "Escape with the loot", full_60["scene_bible"], full_60["beats"], 5
    )
    check("continuation outline generates exactly 5 new beats", len(cont_data["beats"]) == 5)
    check("continuation beats are numbered 61 to 65", [b["clip_number"] for b in cont_data["beats"]] == list(range(61, 66)))
    check("continuation outline passes hard validation", not hnd._hard_problems(cont_probs), cont_probs)
finally:
    hnd._ask_openai_json = orig_ask

# ---------------------------------------------------------------- [21] Step 6: Dashboard fields
print("\n[21] Step 6: Dashboard displays new fields and edit modal support")
from html.parser import HTMLParser
import os

dashboard_path = os.path.join(os.path.dirname(__file__), "dashboard.html")
if not os.path.exists(dashboard_path):
    # inside container working dir is /app
    dashboard_path = "dashboard.html"

try:
    with open(dashboard_path, "r", encoding="utf-8") as f:
        dash_content = f.read()

    parser = HTMLParser()
    parser.feed(dash_content)
    check("dashboard.html parses cleanly without HTMLParser errors", True)
except Exception as e:
    check("dashboard.html parses cleanly without HTMLParser errors", False, str(e))
    dash_content = ""

check("dashboard renders prop table CSS (.prop-table)", ".prop-table" in dash_content)
check("dashboard renders prop in/out tags (.prop-tag-in)", ".prop-tag-in" in dash_content and ".prop-tag-out" in dash_content)
check("dashboard defines renderPropTableHtml helper", "function renderPropTableHtml" in dash_content)
check("dashboard inspect popover contains Environment card", "Environment (Ambient Atmosphere)" in dash_content)
check("dashboard inspect popover contains Blocking Arc & Awareness card", "Characters & Blocking (Start" in dash_content and "Arc & Awareness)" in dash_content)
check("dashboard inspect popover contains Props in This Clip card", "Props in This Clip" in dash_content)
check("dashboard edit modal contains modal-environment", "modal-environment" in dash_content)
check("dashboard edit modal contains modal-delivery-mode", "modal-delivery-mode" in dash_content)
check("dashboard edit modal overrides save narrated_drama movie_script", 'job.mode === "narrated_drama"' in dash_content and "ms.environment" in dash_content)
check("dashboard resume button listener wired", "resume-job-btn" in dash_content and "/jobs/${encodeURIComponent(job.id)}/resume" in dash_content)

# ---------------------------------------------------------------- [22] Step 7: Residual risks
print("\n[22] Step 7: Residual risks (cost estimation, voice banking paths, timeout halt)")
import movie_scene_multispeaker as msm
from pathlib import Path

check("dashboard renders live cost estimate badge", 'id="cost-estimate"' in dash_content)
check("dashboard implements updateCostEstimate helper", "function updateCostEstimate" in dash_content)
check("dashboard approve-plan prompts credit cost and keep-awake confirmation", "Approve Master Plan and start live video generation" in dash_content and "Keep this machine awake" in dash_content)

# Movie mode voice banking space sanitization and custom out_dir
import inspect
sig = inspect.signature(msm.trim_windowed_voice)
check("movie trim_windowed_voice accepts out_dir parameter", "out_dir" in sig.parameters)

# Check app.py passes out_dir to trim_windowed_voice
with open(os.path.join(os.path.dirname(__file__), "app.py"), "r", encoding="utf-8") as f:
    app_src = f.read()
check("app.py passes job voices dir to movie.trim_windowed_voice", "out_dir=job_media_dir(job_id) / \"voices\"" in app_src)

# Check TimeoutError halt in render_clip
orig_gen = msm.generate_clip
try:
    def mock_timeout(**kw):
        raise TimeoutError("polling exceeded 15 minutes")
    msm.generate_clip = mock_timeout
    out = msm.render_clip(1, "Five-second shot.", [], [], False)
    check("movie render_clip halts on TimeoutError without retries", out == "quit")
finally:
    msm.generate_clip = orig_gen

# ---------------------------------------------------------------- [23] Step 4: Script Supervisor
print("\n[23] Step 4: Script Supervisor (supervise_narrated_chapter)")
check("SUPERVISOR_SCHEMA requires problems", hnd.SUPERVISOR_SCHEMA["required"] == ["problems"])
check("SUPERVISOR_SCHEMA problems is array of strings", hnd.SUPERVISOR_SCHEMA["properties"]["problems"]["type"] == "array")

TEST_TOPIC = "A tense dramatic thriller where Clara Vance takes a night shift at the Obsidian Hotel."

# 1. Scoped prompt inspection
prev_sample = [
    dict(aware_clip()["clips"][0], clip_number=101),
    dict(aware_clip()["clips"][0], clip_number=102),
    dict(aware_clip()["clips"][0], clip_number=103),
]
s_sys, s_usr = hnd._narrated_supervisor_prompt(
    TEST_TOPIC, GOOD["scene_bible"], GOOD["beats"][1], prev_sample, aware_clip()["clips"][0]
)
check("supervisor prompt contains 7 core critique areas",
      all(area in s_sys for area in [
          "BEAT FIDELITY", "BLOCKING & POSITION CONTINUITY", "KNOWLEDGE & AWARENESS",
          "FIRST-PERSON POV", "PROPS HONESTY & CONTINUITY", "SPACE & LAYOUT ADHERENCE",
          "PACKING & PACING"
      ]))
check("supervisor user prompt scopes previous clips to max 2",
      "101" not in s_usr and "102" in s_usr and "103" in s_usr)
check("supervisor prompt contains protagonist name", GOOD["scene_bible"]["pov_protagonist"] in s_sys)


# 2. Gating: Mechanical code check failure gates supervisor call
gate_calls = []
def mock_ask_gate(sys_p, usr_p, tag, schema, model=None):
    gate_calls.append(tag)
    if tag == "narrated_chapter":
        if len(gate_calls) == 1:
            bad = aware_clip()
            bad["clips"][0]["location_id"] = "hallway_invalid"
            return bad
        return aware_clip()
    elif tag == "narrated_supervisor":
        return {"problems": []}
    return {}

orig_ask = hnd._ask_openai_json
hnd._ask_openai_json = mock_ask_gate
try:
    data_out, probs_out = hnd.write_narrated_chapter(
        TEST_TOPIC, 1, 4, GOOD["beats"], GOOD["scene_bible"], [], supervise=True
    )
    check("supervisor was not called on attempt 0 with mechanical error",
          gate_calls == ["narrated_chapter", "narrated_chapter", "narrated_supervisor"],
          gate_calls)
finally:
    hnd._ask_openai_json = orig_ask

# 3. One rewrite trigger: Supervisor notes trigger exactly one rewrite attempt
sup_rewrite_calls = []
def mock_ask_sup_rewrite(sys_p, usr_p, tag, schema, model=None):
    sup_rewrite_calls.append(tag)
    if tag == "narrated_chapter":
        return aware_clip()
    elif tag == "narrated_supervisor":
        if sup_rewrite_calls.count("narrated_supervisor") == 1:
            return {"problems": ["clip 2: Clara should look at reception counter instead of window"]}
        else:
            return {"problems": []}
    return {}

hnd._ask_openai_json = mock_ask_sup_rewrite
try:
    data_out, probs_out = hnd.write_narrated_chapter(
        TEST_TOPIC, 1, 4, GOOD["beats"], GOOD["scene_bible"], [], supervise=True
    )
    check("supervisor notes trigger exactly 1 rewrite attempt",
          sup_rewrite_calls == ["narrated_chapter", "narrated_supervisor", "narrated_chapter", "narrated_supervisor"],
          sup_rewrite_calls)
    check("resolved supervisor notes leave no hard problems", not hnd._hard_problems(probs_out), probs_out)
finally:
    hnd._ask_openai_json = orig_ask

# 4. Surviving supervisor notes downgraded to [SOFT]
sup_soft_calls = []
def mock_ask_sup_soft(sys_p, usr_p, tag, schema, model=None):
    sup_soft_calls.append(tag)
    if tag == "narrated_chapter":
        return aware_clip()
    elif tag == "narrated_supervisor":
        return {"problems": ["clip 2: Clara should not turn around"]}
    return {}

hnd._ask_openai_json = mock_ask_sup_soft
try:
    data_out, probs_out = hnd.write_narrated_chapter(
        TEST_TOPIC, 1, 4, GOOD["beats"], GOOD["scene_bible"], [], supervise=True
    )
    check("supervisor makes only 2 calls when notes persist (1 critique + 1 re-check)",
          sup_soft_calls == ["narrated_chapter", "narrated_supervisor", "narrated_chapter", "narrated_supervisor"],
          sup_soft_calls)
    check("surviving supervisor notes are downgraded to [SOFT]",
          any(p.startswith("[SOFT]") and "script supervisor:" in p for p in probs_out), probs_out)
    check("surviving supervisor notes are NOT in hard problems",
          not hnd._hard_problems(probs_out), probs_out)
finally:
    hnd._ask_openai_json = orig_ask

# 5. Switch bypass (supervise=False)
no_sup_calls = []
def mock_ask_no_sup(sys_p, usr_p, tag, schema, model=None):
    no_sup_calls.append(tag)
    return aware_clip()

hnd._ask_openai_json = mock_ask_no_sup
try:
    data_out, probs_out = hnd.write_narrated_chapter(
        TEST_TOPIC, 1, 4, GOOD["beats"], GOOD["scene_bible"], [], supervise=False
    )
    check("supervise=False never calls supervisor", "narrated_supervisor" not in no_sup_calls, no_sup_calls)
finally:
    hnd._ask_openai_json = orig_ask


# 6. App and Dashboard integrations
import app
check("ClipRequest default supervise is False", app.ClipRequest(topic="Test", duration=30).supervise is False)
check("ClipRequest accepts supervise=True", app.ClipRequest(topic="Test", duration=30, supervise=True).supervise is True)
with open(os.path.join(os.path.dirname(__file__), "app.py"), "r", encoding="utf-8") as f:
    app_text = f.read()
check("app.py passes supervise to write_narrated_chapter", "supervise=is_supervise" in app_text)

with open(dashboard_path, "r", encoding="utf-8") as f:
    dash_text = f.read()
check("dashboard.html renders Script Supervisor checkbox", 'id="supervise"' in dash_text)
check("dashboard.html includes supervise in job request payload", 'supervise: $("supervise")' in dash_text or "supervise: document.getElementById" in dash_text)

print("\n[19] Audit fixes: frame-position end state, wordless trim, acts persisted")

# 1. the 180-degree check must read the previous clip's CLOSING frame side
prev_crossed = {"location_id": "lobby_front_desk", "blocking": [
    blk("Clara Vance", "standing", "front", in_frame="visible"),
    blk("Mia Torres", "standing", "side", in_frame="visible")]}
prev_crossed["blocking"][0]["frame_position"] = "frame left"
prev_crossed["blocking"][0]["end_frame_position"] = "frame right"   # she walked across during that clip

moved_on = clip_with([blk("Clara Vance", "standing", "front"), blk("Mia Torres", "standing", "side")])
moved_on["clips"][0]["blocking"][0]["frame_position"] = "frame right"   # opens where she finished
moved_on["clips"][0]["environment"] = ""
moved_on["clips"][0]["prop_state"] = []
b = " | ".join(hnd._check_narrated_chapter(moved_on, GOOD["beats"][1], GOOD["scene_bible"], prev_crossed,
                                           clip_index=1, beats=GOOD["beats"]))
check("opening on the side the previous clip ENDED on is accepted", "180-degree" not in b, b)

flipped = clip_with([blk("Clara Vance", "standing", "front"), blk("Mia Torres", "standing", "side")])
flipped["clips"][0]["blocking"][0]["frame_position"] = "frame left"    # back to where she started: a real flip
flipped["clips"][0]["environment"] = ""
flipped["clips"][0]["prop_state"] = []
b = " | ".join(hnd._check_narrated_chapter(flipped, GOOD["beats"][1], GOOD["scene_bible"], prev_crossed,
                                           clip_index=1, beats=GOOD["beats"]))
check("a genuine screen-side flip is caught", "180-degree" in b, b)
check("the flip note stays soft", not [p for p in hnd._hard_problems(
    hnd._check_narrated_chapter(flipped, GOOD["beats"][1], GOOD["scene_bible"], prev_crossed,
                                clip_index=1, beats=GOOD["beats"])) if "180-degree" in p])

crossing = clip_with([blk("Clara Vance", "standing", "front", end_fp="frame right"),
                      blk("Mia Torres", "standing", "side")])
crossing["clips"][0]["blocking"][0]["frame_position"] = "frame left"
p, _i, _a = hnd.build_narrated_prompt(crossing["clips"][0], GOOD["scene_bible"],
                                      {"Clara Vance": "http://i/c.jpg", "Mia Torres": "http://i/m.jpg"},
                                      {"lobby_front_desk": ["http://i/l.jpg"]}, {})
check("a character crossing the frame is sent as a move", "crossing to frame right" in p, p[-320:])
check("the opening frame positions are still listed once", p.count("Frame positions:") == 1)

# 2. a wordless beat keeps its opening frames
import app as _app


class _C:
    def __init__(self, script):
        self.movie_script = script


_job = type("J", (), {"mode": "narrated_drama"})()
spoken = _C({"speech": [{"line": "Clara, avoid that room."}]})
silent = _C({"speech": []})
check("a speaking clip is trimmed to its first word", _app._wants_lead_in_trim(_job, 1, spoken))
check("a wordless clip keeps its opening frames", not _app._wants_lead_in_trim(_job, 1, silent))
check("clip 0 is never trimmed", not _app._wants_lead_in_trim(_job, 0, spoken))
check("a pre-turns clip still reads its old field",
      _app._wants_lead_in_trim(_job, 1, _C({"audio_text": "a line"})))
check("talking head is unaffected",
      _app._wants_lead_in_trim(type("J", (), {"mode": "talking_head"})(), 1, _C({})))
check("story videos are unaffected",
      not _app._wants_lead_in_trim(type("J", (), {"mode": "story_videos"})(), 1, _C({})))

# 3. the act breakdown survives planning
check("the Job model carries acts", "acts" in _app.Job.model_fields)
check("the saved plan includes acts", "job.acts" in inspect.getsource(_app._save_master_plan_file))
check("the narrated plan stores the acts it planned from",
      "acts=outline.get(\"acts\")" in inspect.getsource(_app._generate_narrated_plan))

print("\n[20] Cross-act reveal leaks")

_acts = [
    {"act_number": 1, "title": "Act 1", "start_clip": 1, "end_clip": 2, "primary_locations": [],
     "dramatic_question": "", "summary": "", "reveals": ["The Obsidian"]},
    {"act_number": 2, "title": "Act 2", "start_clip": 3, "end_clip": 4, "primary_locations": [],
     "dramatic_question": "", "summary": "", "reveals": ["Room 404", "404"]},
    {"act_number": 3, "title": "Act 3", "start_clip": 5, "end_clip": 6, "primary_locations": [],
     "dramatic_question": "", "summary": "", "reveals": ["the silver case"]},
]
_batch1 = {"batch_index": 1, "act_numbers": [1], "start_clip": 1, "end_clip": 2, "clip_count": 2,
           "title": "Act 1", "primary_locations": [], "dramatic_question": "", "summary": ""}
_batch3 = {"batch_index": 3, "act_numbers": [3], "start_clip": 5, "end_clip": 6, "clip_count": 2,
           "title": "Act 3", "primary_locations": [], "dramatic_question": "", "summary": ""}

reserved1 = hnd._terms_reserved_for_later_acts(_acts, _batch1)
check("act 1 must keep back what acts 2 and 3 reveal",
      set(reserved1) == {"room 404", "404", "the silver case"}, reserved1)
check("act 1's own reveal is not reserved from it", "the obsidian" not in reserved1, reserved1)
check("the last act has nothing reserved from it",
      hnd._terms_reserved_for_later_acts(_acts, _batch3) == [], hnd._terms_reserved_for_later_acts(_acts, _batch3))
check("a term claimed by an earlier act is never reserved later",
      "the obsidian" not in hnd._terms_reserved_for_later_acts(_acts, _batch3))


def _beat(n, line, reveals=None):
    return {"clip_number": n, "cycle_number": 1, "delivery_mode": "dialogue",
            "location_id": "lobby_front_desk", "present_characters": ["Clara Vance", "Mia Torres"],
            "speaker_or_actor": "Mia Torres", "summary": "s", "speech_budget": 7,
            "audio_lines": [say("Mia Torres", line)], "reveals": reveals or []}


# a batch-1 beat naming an act-2 term is caught while a local retry is still cheap
leaky = [_beat(1, "Clara, stay out of Room 404 tonight."), _beat(2, "I mean it, every single night.")]
probs = hnd._check_act_beats(leaky, GOOD["scene_bible"], 1, 2, prior_beats=[], reserved_terms=reserved1)
check("a leak into a later act is caught per batch",
      any("a LATER act is the one to reveal" in p for p in probs), probs)
check("that leak is fatal, so the batch is retried", hnd._hard_problems(probs))

clean = [_beat(1, "Clara, the night shift here is brutal."), _beat(2, "Keep your head down and survive.")]
check("a clean batch passes",
      not any("LATER act" in p for p in hnd._check_act_beats(
          clean, GOOD["scene_bible"], 1, 2, prior_beats=[], reserved_terms=reserved1)))

# the beat writer is told what it may not say
_sys, _usr = hnd._narrated_act_beats_prompt("premise", _batch1, _acts, GOOD["scene_bible"], [], 6)
check("reserved terms are named in the prompt", "RESERVED FOR LATER ACTS" in _sys, _sys[-200:])
check("the actual terms are listed", "'room 404'" in _sys.lower(), _sys[-300:])
check("the last act gets no reserved block",
      "RESERVED FOR LATER ACTS" not in hnd._narrated_act_beats_prompt(
          "premise", _batch3, _acts, GOOD["scene_bible"], [], 6)[0])

# the whole-plan backstop finds what the per-batch pass could not
spilled = [_beat(1, "Clara, stay out of Room 404 tonight."),
           _beat(2, "The night shift here is brutal."),
           _beat(3, "Avoid it.", reveals=["Room 404", "404"]),
           _beat(4, "I hear you loud and clear.")]
found = hnd._leaking_beats(spilled)
check("the backstop finds the leaking beat", found and found[0][0] == 0, found)
check("the backstop names the term", found and "404" in found[0][1], found)
check("a clean plan leaks nothing", hnd._leaking_beats(
    [_beat(1, "The night shift here is brutal."), _beat(2, "Avoid it.", reveals=["Room 404"])]) == [])

print("\n[21] The written voice shapes the take that gets banked")

VOICED = json.loads(json.dumps(GOOD))
VOICED["scene_bible"]["characters"][0]["voice"] = "a low alto with a cracked, smoky edge"
VOICED["scene_bible"]["characters"][1]["voice"] = "a bright, hurried mezzo that cracks when frightened"
hnd._compile_bible_visuals(VOICED["scene_bible"])
_cast = {c["name"]: f"http://i/{c['name'][0]}.jpg" for c in VOICED["scene_bible"]["characters"]}
_locs = {"lobby_front_desk": ["http://i/l.jpg"]}


def _voiced_clip(mode="voiceover", speaker="Clara Vance", in_frame="visible"):
    c = clip_with([blk("Clara Vance", "standing", "front"),
                   blk("Mia Torres", "standing", "side", in_frame=in_frame)], mode=mode)
    c["clips"][0]["speech"] = [turn(speaker, "Three years I kept him breathing here.", 0.6, 4.3)]
    c["clips"][0]["environment"] = ""
    c["clips"][0]["prop_state"] = []
    return c["clips"][0]


# nothing banked: the description is the only thing shaping the voice Seedance invents
p, _i, auds = hnd.build_narrated_prompt(_voiced_clip(), VOICED["scene_bible"], _cast, _locs, {})
check("an unbanked voiceover carries the written voice", "cracked, smoky edge" in p, p[:300])
check("no audio reference is sent when none exists", not auds, auds)

# once banked, the sample replaces the description
p2, _i2, auds2 = hnd.build_narrated_prompt(_voiced_clip(), VOICED["scene_bible"], _cast, _locs,
                                           {"Clara Vance": "http://a/c.wav"})
check("a banked voiceover points at the sample instead", "@Audio1's voice" in p2, p2[:300])
check("the description is dropped once a sample exists", "cracked, smoky edge" not in p2, p2[:300])

# the same on both dialogue paths
d = _voiced_clip(mode="dialogue", speaker="Mia Torres")
p3, _i3, _a3 = hnd.build_narrated_prompt(d, VOICED["scene_bible"], _cast, _locs, {})
check("an unbanked on-camera speaker carries their written voice", "bright, hurried mezzo" in p3, p3[:400])
check("lip sync is still demanded", "synchronized lip movement" in p3)

off = _voiced_clip(mode="dialogue", speaker="Mia Torres", in_frame="off screen")
p4, _i4, _a4 = hnd.build_narrated_prompt(off, VOICED["scene_bible"], _cast, _locs, {})
check("an unbanked remote speaker carries it too", "bright, hurried mezzo" in p4, p4[:400])
check("the remote speaker still comes from the receiver", "telephone receiver/off-screen" in p4)

# a character with no written voice must not produce a dangling phrase
BARE = json.loads(json.dumps(VOICED))
BARE["scene_bible"]["characters"][0]["voice"] = ""
p5, _i5, _a5 = hnd.build_narrated_prompt(_voiced_clip(), BARE["scene_bible"], _cast, _locs, {})
check("no written voice leaves the sentence clean", "narrates this scene," in p5, p5[:300])

print("\n[22] The POV rule is checked when the plan is written, not only when the clip is")

POV = json.loads(json.dumps(GOOD))
POV["beats"][1]["present_characters"] = ["Mia Torres"]          # Clara narrates, Clara absent
b = " | ".join(hnd._check_narrated_outline(POV, 4))
check("a voiceover beat without its narrator is caught at plan time",
      "narrates this beat but is not among its present_characters" in b, b)
check("and it is fatal, so the plan retries rather than the clip",
      [p for p in hnd._hard_problems(hnd._check_narrated_outline(POV, 4)) if "narrates this beat" in p])

POV2 = json.loads(json.dumps(GOOD))
POV2["beats"][1]["present_characters"] = ["Clara Vance", "Mia Torres"]
check("the narrator present among others is fine",
      not [p for p in hnd._check_narrated_outline(POV2, 4) if "narrates this beat" in p])

POV3 = json.loads(json.dumps(GOOD))
POV3["beats"][1]["present_characters"] = []                      # narration over an establishing shot
check("narration over a shot with nobody in it stays exempt",
      not [p for p in hnd._check_narrated_outline(POV3, 4) if "narrates this beat" in p])

print("\n[23] A prop the action moves cannot be left out of the diary")

# Since omission now means "off camera, unchanged", a prop that MOVES here but goes unlisted would be
# frozen at its old holder and state by the carry-forward, and that wrong state follows it for the rest
# of the story. Anything the action handles must therefore be listed.
def _action_clip(action, diary):
    c = prop_clip(diary)["clips"][0]
    c["action_steps"] = [{"start_time": 1.0, "character": "Clara Vance", "action": action}]
    return {"clips": [c]}


moved = _action_clip("Clara drags the laundry cart away from the desk", [])
b = " | ".join(hnd._check_narrated_chapter(moved, GOOD["beats"][1], GOOD["scene_bible"], None,
                                           clip_index=1, beats=GOOD["beats"]))
check("a prop the action moves but never lists is caught", "an action step handles" in b, b[:140])
check("and it is fatal, so the clip is rewritten",
      any("an action step handles" in p for p in hnd._hard_problems(
          hnd._check_narrated_chapter(moved, GOOD["beats"][1], GOOD["scene_bible"], None,
                                      clip_index=1, beats=GOOD["beats"]))))

listed = _action_clip("Clara drags the laundry cart away from the desk", good_diary)
check("listing the prop clears it",
      "an action step handles" not in " | ".join(hnd._check_narrated_chapter(
          listed, GOOD["beats"][1], GOOD["scene_bible"], None, clip_index=1, beats=GOOD["beats"])))

untouched = _action_clip("Clara turns away from the key wall without a word", [])
check("a prop nobody touches raises nothing",
      "an action step handles" not in " | ".join(hnd._check_narrated_chapter(
          untouched, GOOD["beats"][1], GOOD["scene_bible"], None, clip_index=1, beats=GOOD["beats"])))

# the real-run false positive: "radio" matched car_radio_mic, but the room's layout has a radio console.
# A word that also names scenery is not that prop's name, so only the whole name may match.
SCENERY = json.loads(json.dumps(GOOD))
SCENERY["scene_bible"]["locations"][0]["layout"] = "a laundry chute runs down the west wall beside the desk"
near = _action_clip("Clara glances at the laundry chute on the west wall", [])
check("a word that also names scenery does not trip it",
      "an action step handles" not in " | ".join(hnd._check_narrated_chapter(
          near, SCENERY["beats"][1], SCENERY["scene_bible"], None, clip_index=1, beats=SCENERY["beats"])),
      "scenery word matched as a prop")
still = _action_clip("Clara drags the laundry cart past the chute", [])
check("but the prop's whole name still does",
      "an action step handles" in " | ".join(hnd._check_narrated_chapter(
          still, SCENERY["beats"][1], SCENERY["scene_bible"], None, clip_index=1, beats=SCENERY["beats"])))

print("\n[24] The clip writer's system message is the same bytes on every clip")
# OpenAI discounts the longest common PREFIX of a request, automatically, above 1024 tokens. That only pays
# if nothing clip-specific sits in front of the rulebook. It used to: the system message opened with
# "Clip N of M" and this clip's own quoted lines, so across a real 43-clip run the common prefix measured
# 6 tokens and ~3,400 tokens of rules were billed at full rate 43 times over. These checks keep it that way.
_beats = GOOD["beats"]
_bible = GOOD["scene_bible"]
_sys_a, _usr_a = hnd._narrated_chapter_prompt("A tense thriller", 0, len(_beats), _beats[0], _bible, [], beats=_beats)
_sys_b, _usr_b = hnd._narrated_chapter_prompt("A tense thriller", 1, len(_beats), _beats[1], _bible, [], beats=_beats)
# beat 0 is a voiceover and beat 2 a wordless shock_action - the two furthest apart, since the mode
# instructions and the quoted lines were what used to put different text at the top of every request.
_sys_c, _ = hnd._narrated_chapter_prompt("A tense thriller", 2, len(_beats), _beats[2], _bible, [], beats=_beats)
check("two clips of the same delivery mode share one system message", _sys_a == _sys_b,
      "the system message still varies per clip, so nothing caches")
check("and so do two clips of different delivery modes", _sys_a == _sys_c,
      f"{_beats[0]['delivery_mode']} and {_beats[2]['delivery_mode']} still produce different system messages")
check("and it is long enough to be cached at all", len(_sys_a) / 4 >= 1024,
      f"only about {len(_sys_a) / 4:.0f} tokens, under OpenAI's 1024-token floor")
check("the clip number is not in it", "Clip 1 of" not in _sys_a and "Clip 2 of" not in _sys_a)
check("nor the delivery mode", "Delivery Mode for this clip" not in _sys_a)
check("nor this clip's own spoken lines",
      all(t["line"] not in _sys_a for t in hnd._beat_lines(_beats[1]) if t.get("line")))
check("the premise rides along in it, since it never changes either", "A tense thriller" in _sys_a)
check("the rulebook is in it", "ABSOLUTE SPATIAL & CONTINUITY RULES" in _sys_a)
# and everything clip-specific still reaches the model, in the user message
check("the user message carries the clip number", "Clip 2 of" in _usr_b)
check("and the delivery mode", "Delivery Mode for this clip" in _usr_b)
check("and the mandatory location anchor", _beats[1]["location_id"] in _usr_b
      and "MANDATORY LOCATION ANCHOR" in _usr_b)
check("and the lines the Master Plan locked",
      all(t["line"] in _usr_b for t in hnd._beat_lines(_beats[1]) if t.get("line")))
# a retry must add to the user message, never replace it: the beat and history are what it needs to fix
_src = inspect.getsource(hnd.write_narrated_chapter)
check("a retry builds on the original user message", "base_usr" in _src and _src.count("base_usr") >= 3,
      "a retry still replaces the user message, dropping the beat and the clip history")
check("and shows the model the answer that was rejected", "Here is your previous answer" in _src)

print("\n[25] The film is allowed to raise its voice")
# The first 5-minute run asked for restraint in 39 of its 56 spoken turns and for heat in 2. The model was
# never the limit - the two heated clips carry real anger. The flatness came from our own wording, in three
# places: the delivery examples we show, the `voice` field holding a performance note, and nothing noticing
# a long restrained run.
_VB = json.loads(json.dumps(GOOD))
_VB["scene_bible"]["characters"][0]["voice"] = "low, controlled alto with precise diction"
check("a performance word in `voice` is rejected",
      any("how a line is PERFORMED" in p for p in hnd._check_scene_bible(_VB["scene_bible"])),
      "a permanent 'controlled' still reaches every delivery in the film")
# ...but it should almost never fire, because the word is struck before validation ever runs. A hard
# problem here costs a planning retry, and one that survived the retries would fail the plan at the final
# whole-plan check with all six planning calls already paid for.
_RB = json.loads(json.dumps(GOOD))
_RB["scene_bible"]["characters"][0]["voice"] = "low, controlled alto with precise diction"
_RB["scene_bible"]["characters"][1]["voice"] = "quiet, flat bass"
_voice_notes = hnd._clean_voices(_RB["scene_bible"])
check("the performance word is struck, not re-asked",
      _RB["scene_bible"]["characters"][0]["voice"] == "low, alto with precise diction",
      _RB["scene_bible"]["characters"][0]["voice"])
check("two of them in one voice are both struck",
      _RB["scene_bible"]["characters"][1]["voice"] == "bass",
      _RB["scene_bible"]["characters"][1]["voice"])
check("the repair reports what it changed", len(_voice_notes) == 2, _voice_notes)
check("so the plan no longer has a hard problem to retry",
      not any("how a line is PERFORMED" in p for p in hnd._check_scene_bible(_RB["scene_bible"])))
_THIN = json.loads(json.dumps(GOOD))
_THIN["scene_bible"]["characters"][0]["voice"] = "quiet and controlled"
hnd._clean_voices(_THIN["scene_bible"])
check("a voice that would be left as garbage is kept intact for the validator",
      _THIN["scene_bible"]["characters"][0]["voice"] == "quiet and controlled")
check("and the validator still catches that one",
      any("how a line is PERFORMED" in p for p in hnd._check_scene_bible(_THIN["scene_bible"])))
check("a clean voice is untouched",
      not hnd._clean_voices({"characters": [{"name": "X", "voice": "gravelled baritone"}]}))

_VB["scene_bible"]["characters"][0]["voice"] = "smoky alto with a faint Irish lilt"
check("a real vocal identity passes",
      not any("how a line is PERFORMED" in p for p in hnd._check_scene_bible(_VB["scene_bible"])))
# the examples we hand the clip writer decide the register it writes in
_, _usr_vo = hnd._narrated_chapter_prompt("t", 0, 3, _VB["beats"][0], _VB["scene_bible"], [])
check("the voiceover examples are no longer all hushed",
      any(w in _usr_vo.lower() for w in ("rage", "bitter", "accuse", "seethe")),
      "every delivery example is still a whisper, so the model writes whispers")
check("the schema offers the hot end of the range",
      any(w in json.dumps(hnd._narrated_chapter_schema([], [])).lower()
          for w in ("roared", "shouted", "clenched teeth")))
check("the showrunner is told `voice` is the instrument, not the performance",
      "INSTRUMENT, NOT THE PERFORMANCE" in hnd._narrated_outline_prompt("t", 60, 12)[0]
      and "INSTRUMENT, NOT THE PERFORMANCE" in hnd._narrated_act_breakdown_prompt("t", 300, 60)[0])
# a delivery that cancels itself, and a restrained run
_LINE = GOOD["beats"][1]["audio_lines"][0]["line"]
def _delivery_clip(d):
    return clip_with([blk("Clara Vance", "standing", "front"), blk("Mia Torres", "standing", "side")],
                     speech=[turn("Clara Vance", _LINE, 0.6, 4.3, delivery=d)])
def _notes(clip, prev=None):
    return hnd._check_narrated_chapter(clip, GOOD["beats"][1], GOOD["scene_bible"], prev,
                                       clip_index=1, beats=GOOD["beats"])

_cancels = _delivery_clip("low, controlled accusation without raised volume")
check("a delivery that cancels its own emotion is flagged",
      any("cancels its own emotion" in p for p in _notes(_cancels)))
check("and only as a soft note, never failing a paid run",
      not any("cancels its own emotion" in p for p in hnd._hard_problems(_notes(_cancels))))

# the real clip 4: "low, controlled counterstrike without heat" is cut back to a usable instruction,
# deterministically, before validation - no retry, no OpenAI call.
_real = _delivery_clip("low, controlled counterstrike without heat")
_notes_fixed = hnd._repair_narrated_clip(_real["clips"][0], GOOD["beats"][1], GOOD["scene_bible"], None)
check("the cancelling clause is cut, not merely logged",
      hnd._clip_turns(_real["clips"][0])[0]["delivery"] == "low, controlled counterstrike",
      hnd._clip_turns(_real["clips"][0])[0]["delivery"])
check("and the repair says what it did",
      any("cancelled its own emotion" in n for n in _notes_fixed), _notes_fixed)
check("a delivery with nothing to cut is left alone",
      hnd._clip_turns(_delivery_clip("roared, furious")["clips"][0])[0]["delivery"] == "roared, furious")
check("a reply is told to react to the line before it",
      "A REPLY REACTS" in hnd._narrated_chapter_prompt(
          "t", 1, 4, TRIO["beats"][2], TRIO["scene_bible"], [])[1])

_quiet_prev = _delivery_clip("hushed, controlled reply")["clips"][0]
_quiet_prev["location_id"] = "lobby_front_desk"
check("two restrained clips in a row are noted",
      any("temperature move" in p for p in _notes(_delivery_clip("quiet, measured warning"), _quiet_prev)))
check("a clip that raises its voice clears it",
      not any("temperature move" in p for p in _notes(_delivery_clip("roared, furious, voice breaking"), _quiet_prev)))

print("\n[26] Scenes are allowed to play, narration stays rationed")
# The old rule capped dialogue at 3 clips in a row, so no confrontation could ever play out and the planner
# had to wedge voiceover in as spacer - which is how Act 2 of the 5-minute run ended up narrating a phone
# call that was still happening. Narration is the asymmetric one: it compresses, so it stays short.
def _run_of(mode, n, start=1):
    beats = []
    for i in range(n):
        b = json.loads(json.dumps(GOOD["beats"][1 if mode == "voiceover" else 2]))
        b["clip_number"] = start + i
        b["delivery_mode"] = mode
        if mode == "voiceover":
            b["audio_lines"] = [say("Clara Vance", "I kept the ledger quiet for three long years")]
            b["present_characters"] = ["Clara Vance"]
            b["speaker_or_actor"] = "Clara Vance"
        else:
            b["audio_lines"] = [say("Clara Vance", "You signed it yourself"), say("Mia Torres", "I had no choice")]
            b["present_characters"] = ["Clara Vance", "Mia Torres"]
            b["speaker_or_actor"] = "Clara Vance"
        b["speech_budget"] = sum(len(w["line"].split()) for w in b["audio_lines"])
        beats.append(b)
    return beats

_long_scene = hnd._check_beats(_run_of("dialogue", 12), GOOD["scene_bible"])
check("a 12-clip confrontation is no longer rejected",
      not any("consecutive dialogue" in p for p in hnd._hard_problems(_long_scene)),
      [p for p in hnd._hard_problems(_long_scene) if "dialogue" in p])
check("but a very long one is noted, softly",
      any("unbroken" in p for p in hnd._soft_problems(_long_scene)), hnd._soft_problems(_long_scene))

check("two voiceover clips in a row are silent, the normal case",
      not any("voiceover clips in a row" in p for p in hnd._check_beats(_run_of("voiceover", 2), GOOD["scene_bible"])))
_three_vo = hnd._check_beats(_run_of("voiceover", 3), GOOD["scene_bible"])
check("three are allowed but called out",
      not any("voiceover clips in a row" in p for p in hnd._hard_problems(_three_vo))
      and any("three voiceover clips" in p.lower() for p in hnd._soft_problems(_three_vo)),
      hnd._soft_problems(_three_vo))
check("four are rejected outright",
      any("voiceover clips in a row" in p for p in hnd._hard_problems(
          hnd._check_beats(_run_of("voiceover", 4), GOOD["scene_bible"]))))

check("the word budget fits a real sentence", (hnd.MIN_WORDS, hnd.MAX_WORDS) == (6, 15))
_bd = hnd._narrated_act_breakdown_prompt("a thriller", 300, 60)[0]
check("the planner is told length follows content", "LENGTH FOLLOWS CONTENT" in _bd)
check("and that equal acts are a symptom", "12/12/12/12/12" in _bd)
check("and that locations move inside an act", "LOCATIONS MOVE WITHIN AN ACT" in _bd)
check("and not to build an act out of things the camera cannot see", "DRAMATISE, DO NOT REPORT" in _bd)
check("a character alone on a phone is named as the failure", "holding a receiver is not a scene" in _bd)
_ab = hnd._narrated_act_beats_prompt("a thriller", {"batch_index": 1, "act_numbers": [1], "start_clip": 1,
                                                    "end_clip": 12, "clip_count": 12, "title": "Act 1",
                                                    "primary_locations": [], "dramatic_question": "", "summary": ""},
                                     [], GOOD["scene_bible"], [], 60)[0]
check("the beat writer gets the same two kinds", "SCENES PLAY, BRIDGES SKIP" in _ab)
check("and is told dialogue is not capped", "NOT capped" in _ab)

print("\n[27] Per-call model, and the usage numbers we were throwing away")
import app as _usage_app
check("the clip writer has its own model setting", hasattr(_usage_app, "OPENAI_CLIP_MODEL"))
check("which follows OPENAI_MODEL when unset",
      _usage_app.OPENAI_CLIP_MODEL == _usage_app.OPENAI_MODEL or bool(os.getenv("OPENAI_CLIP_MODEL")))
check("_ask_openai_json takes a model", "model" in inspect.signature(_usage_app._ask_openai_json).parameters)
_cw = inspect.getsource(hnd.write_narrated_chapter)
check("the clip writer passes it", "model=app.OPENAI_CLIP_MODEL" in _cw)
check("and so does the supervisor",
      "model=app.OPENAI_CLIP_MODEL" in inspect.getsource(hnd.supervise_narrated_chapter))
_plan_src = inspect.getsource(hnd._write_act_based_outline) + inspect.getsource(hnd._write_single_shot_outline)
check("but the showrunner does NOT - the story stays on the better model",
      "OPENAI_CLIP_MODEL" not in _plan_src)

class _FakeUsage:                      # the shape the OpenAI client returns
    prompt_tokens, completion_tokens = 9000, 3000
    prompt_tokens_details = type("d", (), {"cached_tokens": 4700})()
    completion_tokens_details = type("d", (), {"reasoning_tokens": 1500})()

_usage_app.USAGE_LOG.clear()
_e = _usage_app._record_usage("narrated_chapter", "gpt-6-luna", _FakeUsage())
check("cached tokens are captured - the only proof the prefix cache is hitting", _e["cached"] == 4700)
check("reasoning tokens are captured", _e["reasoning"] == 1500)
# 4,300 fresh @ $0.10/M + 4,700 cached @ $0.01/M + 3,000 out @ $0.50/M
check("the cost estimate uses the cached rate", abs(_e["cost"] - 0.00197) < 1e-5, _e.get("cost"))
_e55 = _usage_app._record_usage("narrated_act_breakdown", "gpt-5.5", _FakeUsage())
check("an unknown cached rate is charged at full price, not assumed free",
      abs(_e55["cost"] - ((9000 * 5.0 + 3000 * 30.0) / 1e6)) < 1e-6, _e55.get("cost"))
_sum = _usage_app.usage_summary()
check("the summary totals by call name", _sum["total"]["calls"] == 2
      and _sum["by_name"]["narrated_chapter"]["cached"] == 4700)
_usage_app._record_usage("x", "some-model-we-do-not-price", _FakeUsage())
check("an unpriced model still reports its tokens", _usage_app.USAGE_LOG[-1]["input"] == 9000
      and "cost" not in _usage_app.USAGE_LOG[-1])
check("no usage object is handled", _usage_app._record_usage("x", "gpt-5.5", None) == {})
_usage_app.USAGE_LOG.clear()

print(f"\n{'=' * 60}\n{ok} passed, {fail} failed\n{'=' * 60}")
raise SystemExit(1 if fail else 0)
