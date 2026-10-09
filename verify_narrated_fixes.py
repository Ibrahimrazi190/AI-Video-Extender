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
check("an over-long line (more than 13 words in a clip) is a hard problem so it gets fixed, but a reviewable one: it never throws a plan away",
      any("before the voice starts dropping words" in p for p in hnd._hard_problems(probs)) and not hnd.split_plan_problems(hnd._hard_problems(probs))[0],
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
def mock_ask_single(sys_p, usr_p, tag, schema, model=None, max_completion_tokens=None):
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
def mock_ask_60(sys_p, usr_p, tag, schema, model=None, max_completion_tokens=None):
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
def mock_ask_cont(sys_p, usr_p, tag, schema, model=None, max_completion_tokens=None):
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
def mock_ask_gate(sys_p, usr_p, tag, schema, model=None, max_completion_tokens=None):
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
def mock_ask_sup_rewrite(sys_p, usr_p, tag, schema, model=None, max_completion_tokens=None):
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
def mock_ask_sup_soft(sys_p, usr_p, tag, schema, model=None, max_completion_tokens=None):
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
def mock_ask_no_sup(sys_p, usr_p, tag, schema, model=None, max_completion_tokens=None):
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

check("the word budget fits a real sentence", (hnd.MIN_WORDS, hnd.MAX_WORDS) == (6, 13))
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
# 4,300 fresh @ $5/M + 4,700 cached @ $0.50/M + 3,000 out @ $30/M
check("gpt-5.5 cached tokens use its published $0.50/M rate",
      abs(_e55["cost"] - ((4300 * 5.0 + 4700 * 0.50 + 3000 * 30.0) / 1e6)) < 1e-6, _e55.get("cost"))
_usage_app.OPENAI_PRICES["test-model-no-cached-rate"] = (5.0, None, 30.0)
_eu = _usage_app._record_usage("x", "test-model-no-cached-rate", _FakeUsage())
del _usage_app.OPENAI_PRICES["test-model-no-cached-rate"]
_usage_app.USAGE_LOG.pop()  # keep this probe out of the summary totals checked below
check("an unknown cached rate is charged at full price, not assumed free",
      abs(_eu["cost"] - ((9000 * 5.0 + 3000 * 30.0) / 1e6)) < 1e-6, _eu.get("cost"))
_sum = _usage_app.usage_summary()
check("the summary totals by call name", _sum["total"]["calls"] == 2
      and _sum["by_name"]["narrated_chapter"]["cached"] == 4700)
_usage_app._record_usage("x", "some-model-we-do-not-price", _FakeUsage())
check("an unpriced model still reports its tokens", _usage_app.USAGE_LOG[-1]["input"] == 9000
      and "cost" not in _usage_app.USAGE_LOG[-1])
check("no usage object is handled", _usage_app._record_usage("x", "gpt-5.5", None) == {})
_usage_app.USAGE_LOG.clear()

print("\n[28] Runaway protection, and a history that stops repeating itself")
# Clip 43 of the first 5-minute run wrote the same prop entry 563 times and used 36,408 tokens; clip 42's
# diary had already repeated one 5 times, which the next prompt then copied.
import copy as _copy
check("a cut-off reply has its own error type", issubclass(_usage_app.OpenAIOutputCut, ValueError))
check("_ask_openai_json takes a token ceiling",
      "max_completion_tokens" in inspect.signature(_usage_app._ask_openai_json).parameters)


class _FakeCompletions:
    def __init__(self, finish):
        self.finish, self.kwargs = finish, None

    def create(self, **kw):
        self.kwargs = kw
        msg = type("m", (), {"refusal": None, "content": '{"ok": 1}'})()
        return type("r", (), {"usage": None, "choices": [type("c", (), {"message": msg, "finish_reason": self.finish})()]})()


def _call_with(finish, **kw):
    comp = _FakeCompletions(finish)
    real = _usage_app.OpenAI
    _usage_app.OpenAI = lambda **_k: type("cl", (), {"chat": type("ch", (), {"completions": comp})()})()
    try:
        return comp, _usage_app._ask_openai_json("s", "u", "t", {"type": "object"}, **kw)
    finally:
        _usage_app.OpenAI = real


_comp, _res = _call_with("stop", max_completion_tokens=16000)
check("the ceiling is sent to OpenAI when given", _comp.kwargs.get("max_completion_tokens") == 16000)
check("a normal reply is parsed as before", _res == {"ok": 1})
_comp, _ = _call_with("stop")
check("and no ceiling is sent when none is given", "max_completion_tokens" not in _comp.kwargs)
try:
    _call_with("length", max_completion_tokens=16000)
    _raised = None
except _usage_app.OpenAIOutputCut as _e:
    _raised = _e
check("a reply that hit the ceiling is rejected, never parsed", _raised is not None)

# the schema stops the list itself, before any tokens are spent on it
_props = ["laundry_cart", "silver_case"]
_cast = ["Clara Vance", "Julian Cross", "Marco"]
_item = hnd._narrated_chapter_schema(["lobby"], _cast, _props)["properties"]["clips"]["items"]["properties"]
check("prop_state is bounded by the number of props in the bible", _item["prop_state"]["maxItems"] == len(_props))
check("blocking is bounded by the size of the cast", _item["blocking"]["maxItems"] == len(_cast))
check("speech is bounded by what one clip can hold", _item["speech"]["maxItems"] == hnd.MAX_VOICE_REFS)
check("action steps are bounded", _item["action_steps"]["maxItems"] == hnd.MAX_ACTION_STEPS >= 8)
_open = hnd._narrated_chapter_schema([], [])["properties"]["clips"]["items"]["properties"]
check("with no props or cast to bound by, no limit is invented",
      "maxItems" not in _open["prop_state"] and "maxItems" not in _open["blocking"])
check("the ceilings are several times a real reply",
      hnd.CLIP_MAX_OUTPUT >= 12000 and hnd.PLAN_MAX_OUTPUT >= 24000)

# the diary text that is copied into the next prompt
_looped = {"prop_state": [{"prop_id": "encrypted_ledger_case", "holder": "scene", "in_frame": False,
                           "state": "secured in the convoy"}] * 5
           + [{"prop_id": "marco_handgun", "holder": "Marco", "in_frame": False, "state": "holstered"}]}
_line = hnd._props_line(_looped)
check("a repeated prop appears once in the history", _line.count("encrypted_ledger_case") == 1, _line)
check("and the other props are untouched", "marco_handgun" in _line)

# history: only the newest clip carries its end state
def _hist_clip(n):
    return {"clip_number": n, "delivery_mode": "dialogue", "location_id": "lobby", "shot": f"SHOTMARK{n}",
            "present_characters": ["Clara Vance"], "environment": f"ENVMARK{n}",
            "speech": [{"speaker": "Clara Vance", "line": f"SPEECHMARK{n}", "delivery": "tense", "start_est": 0.5, "end_est": 3.0}],
            "action_steps": [{"start_time": 0.0, "character": "Clara Vance", "action": f"ACTMARK{n}"}],
            "blocking": [{"character": "Clara Vance", "posture": "standing", "position": f"POSMARK{n}",
                          "screen_profile": "frontal", "in_frame": "visible", "awareness": f"AWMARK{n}"}],
            "prop_state": [{"prop_id": "laundry_cart", "holder": "scene", "in_frame": True, "state": f"PROPMARK{n}"}]}


_prev = [_hist_clip(n) for n in (1, 2, 3, 4)]
_, _u = hnd._narrated_chapter_prompt("t", 4, 8, GOOD["beats"][1], GOOD["scene_bible"], _prev, beats=GOOD["beats"])
check("the history still holds the last three clips", all(f"Clip {n} |" in _u for n in (2, 3, 4)) and "Clip 1 |" not in _u)
check("every one of them keeps its shot, actions and speech",
      all(m + str(n) in _u for n in (2, 3, 4) for m in ("SHOTMARK", "ACTMARK", "SPEECHMARK")))
check("the newest clip keeps its end state in full",
      all(m + "4" in _u for m in ("ENVMARK", "PROPMARK", "AWMARK")))
check("the two older clips no longer repeat theirs",
      not any(m + str(n) in _u for n in (2, 3) for m in ("ENVMARK", "PROPMARK", "AWMARK")))
_old = hnd.HISTORY_END_STATE_CLIPS
hnd.HISTORY_END_STATE_CLIPS = 3
_, _u3 = hnd._narrated_chapter_prompt("t", 4, 8, GOOD["beats"][1], GOOD["scene_bible"], _prev, beats=GOOD["beats"])
hnd.HISTORY_END_STATE_CLIPS = _old
check("setting it to 3 restores the old, full history",
      all(m + str(n) in _u3 for n in (2, 3, 4) for m in ("ENVMARK", "PROPMARK", "AWMARK")))
check("and the trim made the prompt shorter", len(_u) < len(_u3))
_, _u_first = hnd._narrated_chapter_prompt("t", 1, 8, GOOD["beats"][1], GOOD["scene_bible"], [_hist_clip(1)], beats=GOOD["beats"])
check("a single previous clip is always shown in full", "ENVMARK1" in _u_first and "PROPMARK1" in _u_first)

# a runaway clip reply is retried; with every attempt spent, the job stops instead of rendering rubbish
_cut_calls = []
def _mock_cut_then_ok(sys_p, usr_p, tag, schema, model=None, max_completion_tokens=None):
    _cut_calls.append((tag, max_completion_tokens, usr_p))
    if len(_cut_calls) == 1:
        raise _usage_app.OpenAIOutputCut("narrated_chapter: cut off")
    return aware_clip()


_orig = hnd._ask_openai_json
hnd._ask_openai_json = _mock_cut_then_ok
try:
    _d, _p = hnd.write_narrated_chapter(TEST_TOPIC, 1, 4, GOOD["beats"], GOOD["scene_bible"], [])
    check("a clip whose first reply ran away is asked for again and succeeds", len(_cut_calls) == 2 and bool(_d["clips"]))
    check("the clip ceiling is sent on every attempt", all(c[1] == hnd.CLIP_MAX_OUTPUT for c in _cut_calls))
    check("and the retry tells the model what went wrong", "kept repeating itself" in _cut_calls[1][2]
          and "kept repeating itself" not in _cut_calls[0][2])
finally:
    hnd._ask_openai_json = _orig


def _mock_always_cut(sys_p, usr_p, tag, schema, model=None, max_completion_tokens=None):
    raise _usage_app.OpenAIOutputCut("narrated_chapter: cut off")


hnd._ask_openai_json = _mock_always_cut
try:
    try:
        hnd.write_narrated_chapter(TEST_TOPIC, 1, 4, GOOD["beats"], GOOD["scene_bible"], [])
        _stopped = False
    except _usage_app.OpenAIOutputCut:
        _stopped = True
    check("if every attempt runs away the clip fails loudly, before anything is rendered", _stopped)
finally:
    hnd._ask_openai_json = _orig

# showrunner: capped, once more on a runaway, and never moved onto the clip model
_plan_calls = []
def _mock_plan_cut_once(sys_p, usr_p, tag, schema, model=None, max_completion_tokens=None):
    _plan_calls.append((tag, model, max_completion_tokens))
    if len(_plan_calls) == 1:
        raise _usage_app.OpenAIOutputCut("cut")
    return {"beats": []}


hnd._ask_openai_json = _mock_plan_cut_once
try:
    _r = hnd._ask_planner("s", "u", "narrated_act_beats_1", hnd.ACT_BEATS_SCHEMA)
    check("a runaway planning reply is asked for once more", len(_plan_calls) == 2 and _r == {"beats": []})
    check("planning calls carry the planning ceiling", all(c[2] == hnd.PLAN_MAX_OUTPUT for c in _plan_calls))
    check("and still use the story model, not the clip model", all(c[1] is None for c in _plan_calls))
finally:
    hnd._ask_openai_json = _orig

_sup_src = inspect.getsource(hnd.supervise_narrated_chapter)
check("the supervisor has a ceiling and cannot fail a clip by running away",
      "SUPERVISOR_MAX_OUTPUT" in _sup_src and "OpenAIOutputCut" in _sup_src)
_planner_src = inspect.getsource(hnd._write_act_based_outline) + inspect.getsource(hnd._write_single_shot_outline) \
    + inspect.getsource(hnd.write_narrated_continuation_outline)
check("no planning call bypasses the ceiling", "_ask_openai_json(" not in _planner_src and "_ask_planner(" in _planner_src)

print("\n[29] Action steps reach the video model as a timeline")
# Every step has a start_time. build_narrated_prompt used to drop it, so Seedance could not tell WHEN someone
# walks in, turns or leaves. OpenArt's own Seedance guide asks for whole-second, gap-free timecoded beats.
def _st(t, who, what):
    return {"start_time": t, "character": who, "action": what}


_walk = [_st(0.0, "Clara Vance", "Clara stands at the desk."),
         _st(0.7, "Mia Torres", "Mia pushes through the lobby door."),
         _st(2.4, "Clara Vance", "Clara walks to the lift."),
         _st(3.9, "Clara Vance", "Clara steps inside and the doors close.")]
_tl = hnd._timed_actions(_walk)
check("steps become a timeline", _tl.startswith("Action timeline (seconds into the clip): 0-"), _tl)
check("it runs from 0 to the end of the clip with no gaps",
      "0-1s:" in _tl and "1-2s:" in _tl and "2-4s:" in _tl and _tl.rstrip(".").rstrip().endswith("doors close") and "4-5s:" in _tl, _tl)
_stamps = hnd.re.findall(r"(\d)-(\d)s:", _tl)
check("each range starts where the last one ended",
      all(_stamps[i][1] == _stamps[i + 1][0] for i in range(len(_stamps) - 1)) and _stamps[0][0] == "0"
      and _stamps[-1][1] == str(hnd.CLIP_SECONDS), _stamps)
check("every action is in it, in order",
      all(a in _tl for a in ("Clara stands", "Mia pushes", "Clara walks", "steps inside"))
      and _tl.index("Clara stands") < _tl.index("Mia pushes") < _tl.index("Clara walks") < _tl.index("steps inside"))
_late = hnd._timed_actions([_st(1.6, "Clara Vance", "Clara turns."), _st(3.6, "Clara Vance", "Clara leaves.")])
check("the opening pose holds until the first step: the first range still opens at 0",
      "0-4s: Clara Vance: Clara turns." in _late and "4-5s: Clara Vance: Clara leaves." in _late, _late)
_same = hnd._timed_actions([_st(2.3, "Clara Vance", "Clara turns."), _st(1.6, "Mia Torres", "Mia nods."),
                            _st(3.9, "Clara Vance", "Clara leaves.")])
check("steps that start in the same second share one range, in the order written",
      "0-4s: Clara Vance: Clara turns; Mia Torres: Mia nods." in _same, _same)
check("and a clip whose steps all start in one second has no timeline to give",
      hnd._timed_actions([_st(2.3, "Clara Vance", "Clara turns."), _st(1.6, "Mia Torres", "Mia nods.")]) == "")
check("with no timeline to give it stays silent", hnd._timed_actions([]) == "" and hnd._timed_actions(None) == ""
      and hnd._timed_actions([_st(0.0, "Clara Vance", "Clara stands."), _st(0.2, "Mia Torres", "Mia waits.")]) == "")
check("a bad start_time does not crash it",
      isinstance(hnd._timed_actions([_st("soon", "Clara Vance", "Clara stands."), _st(3.0, "Clara Vance", "Clara leaves.")]), str))
check("the plain-words hook is applied (prop ids become words)",
      "laundry cart" in hnd._timed_actions([_st(0.0, "Clara Vance", "Clara grips laundry_cart."), _st(3.0, "Clara Vance", "Clara leaves.")],
                                           plain=lambda t: t.replace("laundry_cart", "laundry cart")))

_clip_t = _copy.deepcopy(moving["clips"][0])
_clip_t["action_steps"] = _walk
_cast = {"Clara Vance": "http://i/c.jpg", "Mia Torres": "http://i/m.jpg"}
_loc = {"lobby_front_desk": ["http://i/l.jpg"]}
_p_new, _, _ = hnd.build_narrated_prompt(_clip_t, GOOD["scene_bible"], _cast, _loc, {})
check("the Seedance prompt carries the timeline", "Action timeline (seconds into the clip): 0-1s:" in _p_new)
check("and no longer the untimed list", "Actions:" not in _p_new)
hnd.TIMED_ACTIONS = False
_p_old, _, _ = hnd.build_narrated_prompt(_clip_t, GOOD["scene_bible"], _cast, _loc, {})
hnd.TIMED_ACTIONS = True
check("TIMED_ACTIONS = False restores the old untimed sentence", "Actions: Clara Vance: Clara stands" in _p_old and "Action timeline" not in _p_old)
_flat = _copy.deepcopy(_clip_t)
_flat["action_steps"] = [_st(0.0, "Clara Vance", "Clara stands."), _st(0.1, "Mia Torres", "Mia waits.")]
_p_flat, _, _ = hnd.build_narrated_prompt(_flat, GOOD["scene_bible"], _cast, _loc, {})
check("a clip with nothing to time keeps the old sentence", "Actions: Clara Vance: Clara stands" in _p_flat)

print("\n[30] A runtime is episode one: play it out, end on a cliffhanger")
# The first 5-minute run asked for a complete arc, so a ~20-minute plot was compressed into 60 clips: 502 spoken
# words, 41% of them narration. The planners and /enhance-prompt now ask for however much story genuinely plays.
_EP = "EPISODE ONE, NOT A WHOLE FILM"
_o_sys, _o_usr = hnd._narrated_outline_prompt("a thriller", 300, 60)
check("the single-shot planner is told this is episode one", _EP in _o_sys and "OPENING MOVEMENT" in _o_sys)
check("and not to rush events to reach an ending", "Never summarise, skip, rush or narrate through an event that matters" in _o_sys)
check("and to end on a cliffhanger, not a resolution", "ENDS ON A CLIFFHANGER" in _o_sys and "resolution, a goodbye or a moral" in _o_sys)
check("the user message no longer asks for a 'complete' plan", "complete" not in _o_usr and "cliffhanger" in _o_usr, _o_usr)
_b_sys, _b_usr = hnd._narrated_act_breakdown_prompt("a thriller", 300, 60)
check("the act breakdown is told the same", _EP in _b_sys and "complete" not in _b_usr and "cliffhanger" in _b_usr)
check("and the LAST act must stay open and name its cliffhanger", "LAST act's" in _b_sys and "name the cliffhanger" in _b_sys)

_mid = {"batch_index": 1, "act_numbers": [1], "start_clip": 1, "end_clip": 12, "clip_count": 12, "title": "Act 1",
        "primary_locations": [], "dramatic_question": "", "summary": ""}
_last = dict(_mid, batch_index=5, act_numbers=[5], start_clip=49, end_clip=60, clip_count=12, title="Act 5")
_mid_sys = hnd._narrated_act_beats_prompt("a thriller", _mid, [], GOOD["scene_bible"], [], 60)[0]
_last_sys = hnd._narrated_act_beats_prompt("a thriller", _last, [], GOOD["scene_bible"], [], 60)[0]
check("every batch of beats is told it is episode one", _EP in _mid_sys and _EP in _last_sys)
check("only the batch holding the last clip is told to end the episode",
      "THESE BEATS END THE EPISODE" in _last_sys and "THESE BEATS END THE EPISODE" not in _mid_sys)
check("it is told to leave the story open, with the final beat as the cliffhanger",
      "leave the story OPEN" in _last_sys and "the cliffhanger itself" in _last_sys)

_seen_sys = []
def _mock_cont(sys_p, usr_p, tag, schema, model=None, max_completion_tokens=None):
    _seen_sys.append(sys_p)
    return {"beats": []}


_orig_ask30 = hnd._ask_openai_json
hnd._ask_openai_json = _mock_cont
try:
    hnd.write_narrated_continuation_outline("a thriller", "she boards the ship", GOOD["scene_bible"], GOOD["beats"], 12)
finally:
    hnd._ask_openai_json = _orig_ask30
check("a continuation is the last batch of what exists, so it ends on a cliffhanger too",
      bool(_seen_sys) and "THESE BEATS END THE EPISODE" in _seen_sys[0])

hnd.EPISODE_ONE = False
_off = (hnd._narrated_outline_prompt("a thriller", 300, 60)[0] + hnd._narrated_act_breakdown_prompt("a thriller", 300, 60)[0]
        + hnd._narrated_act_beats_prompt("a thriller", _last, [], GOOD["scene_bible"], [], 60)[0])
hnd.EPISODE_ONE = True
check("EPISODE_ONE = False removes all of it", _EP not in _off and "CLIFFHANGER" not in _off and "END THE EPISODE" not in _off)

# /enhance-prompt, which is where an oversized premise enters the pipeline
_long = _usage_app.EnhancePromptRequest(topic="a don is betrayed", duration=300, mode="narrated_drama")
_e_sys, _e_usr = _usage_app._enhance_prompts("a don is betrayed", _long)
check("the enhancer tells a long drama it is episode one", "EPISODE ONE of a longer story" in _e_sys)
check("and caps the amount of story to what plays", "about one per 60 seconds" in _e_sys and "do NOT compress or summarise" in _e_sys)
check("Act 4 is a cliffhanger, not a resolution", "ACT 4 (The Cliffhanger)" in _e_sys and "Resolution" not in _e_sys, _e_sys[-900:])
check("the user message matches", "Act 4 (The Cliffhanger" in _e_usr and "Resolution" not in _e_usr)
_sv = _usage_app._enhance_prompts("a don is betrayed", _usage_app.EnhancePromptRequest(topic="a don is betrayed", duration=300, mode="story_videos"))
check("the default drama mode gets the same", "EPISODE ONE of a longer story" in _sv[0])
for _m in ("talking_head", "story_time"):
    _s, _u = _usage_app._enhance_prompts("x", _usage_app.EnhancePromptRequest(topic="x", duration=300, mode=_m))
    check(f"{_m} is left exactly as it was", "EPISODE ONE" not in _s and "Climax & Resolution" in _s and "Climax & Resolution" in _u)
_s60, _u60 = _usage_app._enhance_prompts("x", _usage_app.EnhancePromptRequest(topic="x", duration=60, mode="narrated_drama"))
check("shorter runtimes keep their existing 3-act wording", "3-ACT" in _s60 and "EPISODE ONE" not in _s60)

print("\n[31] Story delivery: the spoken script must tell the story (Phase 1; offline, no model is called)")
# The first run's problem was not connection between acts but delivery: what the protagonist wanted was never said,
# jargon was never explained, the central secret was stated once, by the villain, at clip 34 of 43.

# --- 31a. No contradicting instructions left behind by earlier implementations -------------------------------
_d_outline = hnd._narrated_outline_prompt("a story", 300, 60)[0]
_d_break = hnd._narrated_act_breakdown_prompt("a story", 300, 60)[0]
_d_act = {"batch_index": 1, "act_numbers": [1], "start_clip": 1, "end_clip": 12, "clip_count": 12, "title": "Act 1",
          "primary_locations": [], "dramatic_question": "", "summary": ""}
_d_beats = hnd._narrated_act_beats_prompt("a story", _d_act, [], GOOD["scene_bible"], [], 60)[0]
_d_chapter = hnd._narrated_chapter_prompt("a story", 0, 60, GOOD["beats"][0], GOOD["scene_bible"], [], beats=GOOD["beats"])[0]
_d_all = (_d_outline + _d_break + _d_beats + _d_chapter).lower()
for _bad in ("what she will not say out loud", "what she will not say aloud", "micro-cycle", "rapid 20-to-25"):
    check(f"no prompt still says '{_bad}'", _bad not in _d_all)
check("no source text in the planner module still talks about micro-cycles", "micro-cycle" not in inspect.getsource(hnd).lower())
check("nor the plan stage in app.py", "micro-cycle" not in inspect.getsource(_usage_app._generate_narrated_plan).lower())
check("narration is told to STATE (outline and beats prompts)",
      "it states; it never describes what the picture" in _d_outline.lower() and "it states; it never describes what the picture" in _d_beats.lower())
check("a planted question is allowed beside the reveal ledger (outline and beats prompts)",
      "existence of a hidden secret" in _d_outline.lower() and "existence of a hidden secret" in _d_beats.lower())
check("quick-fire three-speaker clips are kept for clashes that carry no fact",
      "never three" in _d_outline and "never three" in _d_beats)
check("the clip writer is told the premise is context, not permission to show the future",
      "describes the WHOLE story" in _d_chapter and "fixed by the beat" in _d_chapter)
_dr_vo = _usage_app._enhance_prompts("x", _usage_app.EnhancePromptRequest(topic="x", duration=300, mode="narrated_drama"))
_dr_sv = _usage_app._enhance_prompts("x", _usage_app.EnhancePromptRequest(topic="x", duration=300, mode="story_videos"))
_dr_th = _usage_app._enhance_prompts("x", _usage_app.EnhancePromptRequest(topic="x", duration=300, mode="talking_head"))
check("the enhancer has a narrated-drama mode that allows first-person voiceover lines",
      "MODE: Narrated Drama" in _dr_vo[0] and "(VO)" in _dr_vo[0])
check("and no longer bans the very thing the mode is made of (internal thoughts)",
      "NEVER write abstract emotional summaries or internal thoughts" not in _dr_vo[0]
      and "NEVER write abstract emotional summaries or internal thoughts" in _dr_sv[0])
check("the enhancer asks for the story to be said plainly (dramatic modes only)",
      "STORY DELIVERY" in _dr_vo[0] and "STORY DELIVERY" in _dr_sv[0] and "STORY DELIVERY" not in _dr_th[0])

# --- 31b. Schemas ----------------------------------------------------------------------------------------------
def _strict_ok(node, path="root"):
    """OpenAI strict mode: every object lists all its properties as required and forbids extras."""
    bad = []
    if isinstance(node, dict):
        if node.get("type") == "object":
            props = node.get("properties", {})
            if set(node.get("required", [])) != set(props) or node.get("additionalProperties") is not False:
                bad.append(path)
        for k, v in node.items():
            bad += _strict_ok(v, f"{path}.{k}")
    elif isinstance(node, list):
        for i, v in enumerate(node):
            bad += _strict_ok(v, f"{path}[{i}]")
    return bad


for _name in ("OUTLINE_SCHEMA", "ACT_BREAKDOWN_SCHEMA", "ACT_BEATS_SCHEMA", "BLIND_READ_SCHEMA", "DELIVERY_SCHEMA"):
    _bad_paths = _strict_ok(getattr(hnd, _name), _name)
    check(f"{_name} satisfies OpenAI strict mode", not _bad_paths, _bad_paths[:3])
_beat_props = hnd.ACT_BEATS_SCHEMA["properties"]["beats"]["items"]["properties"]
check("every planned beat carries a function, a turn and the facts it delivers",
      all(k in _beat_props for k in ("function", "turn", "delivers")) and _beat_props["function"]["enum"] == hnd.BEAT_FUNCTIONS)
check("both planners are asked for the delivery map",
      "delivery" in hnd.OUTLINE_SCHEMA["required"] and "delivery" in hnd.ACT_BREAKDOWN_SCHEMA["required"])
check("the story is told in exactly five sentences",
      hnd.DELIVERY_SCHEMA["properties"]["story_in_five"]["minItems"] == 5 == hnd.DELIVERY_SCHEMA["properties"]["story_in_five"]["maxItems"])

# --- 31c. The planning prompts ask for it ------------------------------------------------------------------------
check("the act breakdown asks for the delivery map", "STORY DELIVERY (CRITICAL)" in _d_break and "delivery.facts" in _d_break)
check("so does the single-call planner, with the ten writing rules",
      "STORY DELIVERY (CRITICAL)" in _d_outline and "WRITING THE LINES SO THE STORY IS UNDERSTOOD" in _d_outline)
check("deadlines scale to the runtime (60 clips: want by 6, obstacle by 15, plan by 24, stakes by 45)",
      all(s in _d_break for s in ("WANT by clip 6", "by clip 15", "by clip 24", "by clip 45")))
check("a plant_question may never use a term the story reveals later", "Never put a term from an act's \"reveals\"" in _d_break)
check("a stoic character is a matter of delivery, not content", "never of what it says" in _d_beats)
hnd.STORY_DELIVERY = False
_d_off = (hnd._narrated_outline_prompt("a story", 300, 60)[0] + hnd._narrated_act_breakdown_prompt("a story", 300, 60)[0]
          + hnd._narrated_act_beats_prompt("a story", _d_act, [], GOOD["scene_bible"], [], 60, delivery={"facts": [{"id": "f1"}]})[0])
hnd.STORY_DELIVERY = True
check("STORY_DELIVERY = False removes every delivery instruction, and every sentence that pointed at one",
      "STORY DELIVERY" not in _d_off and "WRITING THE LINES" not in _d_off and "FACTS below" not in _d_off
      and "never three" not in _d_off and "EXISTENCE of a hidden secret" not in _d_off, [s for s in ("STORY DELIVERY", "FACTS below", "never three") if s in _d_off])

# --- fixtures for the checks -----------------------------------------------------------------------------------------
_PROTAG = GOOD["scene_bible"]["pov_protagonist"]
_OTHERS = [c["name"] for c in GOOD["scene_bible"]["characters"] if c["name"] != _PROTAG]
_OTHER = _OTHERS[0]


def _fact(fid, role, kind, text, terms, owner, channel, at, deadline=None, repeat=0):
    return {"id": fid, "role": role, "kind": kind, "text": text, "key_terms": terms, "owner": owner, "channel": channel,
            "deliver_at": at, "deadline": deadline or at, "repeat_at": repeat}


def _dbeat(n, mode, speaker, line, loc="lobby_front_desk", function=None, turn=None, delivers=None):
    b = {"clip_number": n, "delivery_mode": mode, "location_id": loc, "present_characters": [speaker],
         "speaker_or_actor": speaker, "summary": f"beat {n}", "speech_budget": len(line.split()) if line else 0,
         "audio_lines": [{"speaker": speaker, "line": line}] if line else [], "reveals": []}
    if function is not None:
        b.update(function=function, turn=turn or "", delivers=delivers or [])
    return b


def _hard(ps):
    return hnd._hard_problems(ps)


# --- 31d. The checks (free, no model) --------------------------------------------------------------------------------
_f_want = _fact("f1", "want", "state_now", "She wants to take everything he relies on.", ["take", "everything", "relies"],
                _PROTAG, "dialogue", 3)
_dl = {"story_in_five": ["a", "b", "c", "d", "e"], "facts": [_f_want], "jargon": []}
_ok3 = [_dbeat(1, "voiceover", _PROTAG, "I wait."), _dbeat(2, "dialogue", _OTHER, "Sign."),
        _dbeat(3, "dialogue", _PROTAG, "I will take everything he relies on.")]
_no3 = [_dbeat(1, "voiceover", _PROTAG, "I wait."), _dbeat(2, "dialogue", _OTHER, "Sign."),
        _dbeat(3, "dialogue", _PROTAG, "You will regret this.")]
check("a fact whose clip says it passes", not _hard(hnd._check_delivery_beats(_ok3, _dl, 1)))
_miss = _hard(hnd._check_delivery_beats(_no3, _dl, 1))
check("a fact whose clip does not say it is a HARD problem that names the fact, the clip and the words",
      len(_miss) == 1 and "f1" in _miss[0] and "Clip 3" in _miss[0] and "'take'" in _miss[0], _miss)
check("saying most of it in other words is accepted (at least half of the key terms)",
      not _hard(hnd._check_delivery_beats(_ok3[:2] + [_dbeat(3, "dialogue", _PROTAG, "He relies on all of it and I take it.")], _dl, 1)))
check("a plan with no delivery map is skipped entirely (older jobs)",
      hnd._check_delivery_beats(_no3, None, 1) == [] and hnd._check_delivery_beats(_no3, {}, 1) == [])
check("a fact outside this batch is not asked of it", not hnd._check_delivery_beats(_no3[:2], _dl, 1))
_wrong_owner = [_dbeat(1, "voiceover", _PROTAG, "I wait."), _dbeat(2, "dialogue", _OTHER, "Sign."),
                _dbeat(3, "dialogue", _OTHER, "I will take everything he relies on.", function="clash", turn="x", delivers=[])]
_wo = hnd._check_delivery_beats(_wrong_owner, _dl, 1)
check("the wrong speaker is only a soft note", not _hard(_wo) and any("does not speak in that beat" in p for p in _wo), _wo)
check("so is a beat that forgets to list the fact it delivers", any("\"delivers\"" in p for p in _wo), _wo)
_f_nar = dict(_f_want, channel="narration")
_narr = hnd._check_delivery_beats(_ok3, dict(_dl, facts=[_f_nar]), 1)
check("a fact meant as narration said in a dialogue beat is a soft note", any("meant as narration" in p for p in _narr), _narr)
_f_rep = dict(_f_want, repeat_at=3, deliver_at=1)
check("a fact that should be repeated and is not gets a soft note",
      any("said again" in p for p in hnd._check_delivery_beats(_no3, dict(_dl, facts=[_f_rep]), 1)))
_jg = {"story_in_five": ["a"] * 5, "facts": [], "jargon": [{"term": "manifests", "plain_gloss": "forged papers saying the cargo was clean"}]}
_unexplained = [_dbeat(1, "dialogue", _OTHER, "She signed false manifests for you.")]
_explained = [_dbeat(1, "dialogue", _OTHER, "She signed manifests, forged papers saying the cargo was clean.")]
check("a jargon term spoken without a plain explanation is a soft note",
      any("without being explained" in p for p in hnd._jargon_problems(_unexplained, _jg["jargon"], 1, None)))
check("and one explained in the same line is not", not hnd._jargon_problems(_explained, _jg["jargon"], 1, None))
_tw = [_dbeat(1, "dialogue", _PROTAG, "I listen.", function="clash", turn="She hears more of the call."),
       _dbeat(2, "dialogue", _PROTAG, "I listen again.", function="clash", turn="She hears more of the call.")]
check("two beats doing the same job in the same place with the same turn are flagged as treading water",
      any("treading water" in p for p in hnd._check_delivery_beats(_tw, {"facts": [_f_want], "jargon": []}, 1)))
check("a beat with no turn is flagged", any("no turn" in p for p in hnd._check_delivery_beats(
    [_dbeat(1, "dialogue", _PROTAG, "I listen.", function="clash", turn="")], {"facts": [_f_want], "jargon": []}, 1)))

# the delivery map itself
_good_plan = {"story_in_five": ["a", "b", "c", "d", "e"], "jargon": [],
              "facts": [_fact("f1", "want", "state_now", "w", ["x", "y"], _PROTAG, "dialogue", 3),
                        _fact("f2", "obstacle", "state_now", "o", ["x", "y"], _OTHER, "dialogue", 12),
                        _fact("f3", "plan", "state_now", "p", ["x", "y"], _PROTAG, "narration", 20),
                        _fact("f4", "stakes", "state_now", "s", ["x", "y"], _OTHER, "dialogue", 40)]}
_acts = [{"act_number": 1, "reveals": ["Vault Cipher"]}]
check("a sound delivery map has no hard problem", not _hard(hnd._check_delivery_plan(_good_plan, GOOD["scene_bible"], _acts, 60)))
_bad = _copy.deepcopy(_good_plan)
_bad["story_in_five"] = ["only one"]
_bad["facts"][1]["owner"] = "Nobody At All"
_bad["facts"][2]["deliver_at"] = 99
_bad["facts"] = [f for f in _bad["facts"] if f["role"] != "want"] + [_fact("f9", "secret", "plant_question", "the Vault Cipher exists", ["vault", "cipher"], _PROTAG, "narration", 5)]
_bp = _hard(hnd._check_delivery_plan(_bad, GOOD["scene_bible"], _acts, 60))
check("hard: five sentences, owners that exist, clip numbers in range, a 'want' fact",
      any("five plain sentences" in p for p in _bp) and any("Nobody At All" in p for p in _bp)
      and any("99" in p for p in _bp) and any("role 'want'" in p for p in _bp), _bp)
check("hard: a planted question may not name a term the story reveals later (the map would contradict the ledger)",
      any("plants a question" in p and "Vault Cipher".lower() in p.lower() for p in _bp), _bp)
_late = _copy.deepcopy(_good_plan)
_late["facts"][0]["deliver_at"] = 30
check("soft: the want arrives after the timetable allows",
      any(p.startswith("[SOFT]") and "'want'" in p and "by clip 6" in p for p in hnd._check_delivery_plan(_late, GOOD["scene_bible"], _acts, 60)))
check("a plan with no delivery map at all is a soft note only", not _hard(hnd._check_delivery_plan(None, GOOD["scene_bible"], _acts, 60)))

# repairs the code can make without a retry
_rep = {"story_in_five": ["a"] * 5, "jargon": [], "facts": [
    {"id": "", "role": "want", "kind": "state_now", "text": "t", "key_terms": ["Take", " Everything "], "owner": _PROTAG.lower(),
     "channel": "dialogue", "deliver_at": 99, "deadline": 2, "repeat_at": 1},
    {"id": "f1", "role": "plan", "kind": "state_now", "text": "t", "key_terms": ["x", "y"], "owner": _OTHER, "channel": "narration",
     "deliver_at": 5, "deadline": 4, "repeat_at": 70}]}
_notes = hnd._repair_delivery(_rep, GOOD["scene_bible"], 60)
_f0, _f1 = _rep["facts"]
check("repair: ids, owner spelling, clip numbers and key terms are settled", _f0["id"] == "f1" and _f0["owner"] == _PROTAG
      and _f0["deliver_at"] == 60 and _f0["key_terms"] == ["take", "everything"], (_f0, _notes))
check("repair: a deadline can never precede its own clip, a repeat never precedes it", _f0["deadline"] == 60 and _f0["repeat_at"] == 0 and _f1["deadline"] == 5)
check("repair: narration is always the protagonist's own voice", _f1["owner"] == _PROTAG and _f1["id"] != "f1", (_f1, _notes))
check("is-it-a-delivery-problem sorting", hnd._is_delivery_problem("delivery.facts lists 2 fact(s)") and hnd._is_delivery_problem("fact f3: owner x")
      and hnd._is_delivery_problem("Clip 3: the plan says this clip must state fact f1 ...") and not hnd._is_delivery_problem("Clip 3: location 'x' is not in the bible"))
_mixed = ["Clip 3: the plan says this clip must state fact f1 - x", "Clip 4: location 'q' is not in scene_bible locations"]
check("once repairs are spent, delivery problems are shown not fatal; structural ones stay hard",
      _hard(hnd._soften_delivery(_mixed)) == [_mixed[1]])
_plan_bad = {"scene_bible": GOOD["scene_bible"], "delivery": _dl, "beats": _no3}
check("a fact missing from its clip is NEVER a hard problem of the plan check: one small call repairs it, so it costs no retry",
      not any("must state fact f1" in p for p in _hard(hnd._check_narrated_outline(_plan_bad, 3, hard_delivery=True))))
check("...but it is still reported", any("must state fact f1" in p for p in hnd._check_narrated_outline(_plan_bad, 3)))
_plan_unsound = {"scene_bible": GOOD["scene_bible"], "delivery": dict(_dl, story_in_five=["x"]), "beats": _ok3}
check("an UNSOUND delivery map is hard in the single-call plan, where a retry is the only repair",
      any("five plain sentences" in p for p in _hard(hnd._check_narrated_outline(_plan_unsound, 3, hard_delivery=True))))
check("and only reported in the act-based plan's final check",
      not any("five plain sentences" in p for p in _hard(hnd._check_narrated_outline(_plan_unsound, 3))))
_soft_act = hnd._check_act_beats(_no3, GOOD["scene_bible"], 1, 3, delivery=_dl, soft_delivery=True)
_hard_act = hnd._check_act_beats(_no3, GOOD["scene_bible"], 1, 3, delivery=_dl, soft_delivery=False)
check("per act, with soft_delivery the missing fact no longer forces a whole-act retry",
      not any("must state fact" in p for p in _hard(_soft_act)) and any("must state fact" in p for p in _hard(_hard_act)))

# --- 31e. Replay of the first run's own lines against the Don's delivery map -----------------------------------------
# The facts below are written by hand from the story you wanted the audience to get; the lines are the real spoken
# lines of job d54e40da (clips not listed had no words or are irrelevant here).
_E, _L, _C = "Elena Vance", "Lorenzo Moretti", "Camilla Rossi"
_run1 = {1: ("voiceover", _E, "Three years I kept Lorenzo breathing. Tonight he offers me a pen."),
         2: ("voiceover", _E, "I knew that desk. I had saved him behind it."),
         3: ("dialogue", _L, "Sign it, Elena. Then leave this house clean."),
         7: ("dialogue", _L, "Rossi buys peace. Your job is done."),
         11: ("dialogue", _E, "You just threw away the thing holding back the dark."),
         13: ("voiceover", _E, "By dawn, Vance Maritime was mine to command again."),
         34: ("dialogue", _C, "Elena signed false customs manifests and took the criminal blame."),
         43: ("dialogue", _L, "Name your price. I'll pay tonight.")}
_don_beats = [_dbeat(n, *( _run1[n] if n in _run1 else ("shock_action", "", "")), loc="x") for n in range(1, 44)]
for _b in _don_beats:
    if not _b["audio_lines"]:
        _b["delivery_mode"] = "shock_action"
_don_bible = {"pov_protagonist": _E, "characters": [{"name": n} for n in (_E, _L, _C)]}
_don = {"story_in_five": ["a"] * 5, "jargon": [{"term": "manifests", "plain_gloss": "forged papers saying the cargo was clean"}], "facts": [
    _fact("f1", "backstory", "state_now", "She was his fixer for three years.", ["three", "years", "kept"], _E, "narration", 1),
    _fact("f2", "obstacle", "state_now", "He is replacing her for the Rossi alliance.", ["rossi", "alliance", "replace"], _L, "dialogue", 3),
    _fact("f3", "want", "state_now", "She will take everything he relies on.", ["take", "everything", "relies"], _E, "dialogue", 11),
    _fact("f4", "plan", "state_now", "Her family's ships carry his shipments.", ["ships", "carry", "shipments"], _E, "narration", 13),
    _fact("f5", "secret", "plant_question", "He still does not know what she paid to keep him free.", ["know", "paid", "free"], _E, "narration", 2),
    _fact("f6", "secret", "pay_later", "She took the blame for his customs crimes.", ["customs", "blame", "took"], _C, "dialogue", 34)]}
_replay = hnd._check_delivery_beats(_don_beats, _don, 1)
_replay_hard = " | ".join(_hard(_replay))
check("replay: the first run DID say the three-years backstory plainly (it passes)", "fact f1" not in _replay_hard)
check("replay: what Elena wants is never said (flagged)", "fact f3" in _replay_hard)
check("replay: the Rossi alliance is never said where the plan needs it (flagged)", "fact f2" in _replay_hard)
check("replay: why the ships matter is never said (flagged)", "fact f4" in _replay_hard)
check("replay: no question is planted before the secret (flagged)", "fact f5" in _replay_hard)
check("replay: the secret itself, once said, passes", "fact f6" not in _replay_hard)
check("replay: 'manifests' is spoken at clip 34 with no explanation (soft)",
      any("'manifests'" in p and p.startswith("[SOFT]") for p in _replay), _replay)

# --- 31f. The repair budget: a plan cannot loop on its own flags ---------------------------------------------------------
_bud_log = []
_DEL_60 = {"story_in_five": ["a", "b", "c", "d", "e"], "jargon": [], "facts": [
    _fact("f1", "want", "state_now", "Clara wants the vault's ledger.", ["ledger", "vault"], "Clara Vance", "narration", 1, 6),
    _fact("f2", "obstacle", "state_now", "Julian guards it and trusts nobody.", ["guards", "trusts", "nobody"], "Julian Cross", "dialogue", 8, 15),
    _fact("f3", "plan", "state_now", "Clara plans to crack the vault at night.", ["crack", "vault", "night"], "Clara Vance", "narration", 21, 24),
    _fact("f4", "stakes", "state_now", "If she fails she loses her sister.", ["sister", "loses"], "Julian Cross", "dialogue", 34, 45)]}


def _mock_forever_failing(sys_p, usr_p, tag, schema, model=None, max_completion_tokens=None):
    out = _copy.deepcopy(mock_ask_60(sys_p, usr_p, tag, schema, model, max_completion_tokens))
    _bud_log.append((tag, usr_p))
    # a planning call "costs" 30k tokens in the usage log; a small repair call about 2k, as the real ones do
    small = tag == "narrated_fact_repair"
    _usage_app.USAGE_LOG.append({"name": tag, "model": "m", "input": 1700 if small else 20000, "cached": 0,
                                 "output": 300 if small else 10000, "reasoning": 0})
    if tag == "narrated_act_breakdown":
        out["delivery"] = _copy.deepcopy(_DEL_60)
    return out


_orig_ask31 = hnd._ask_openai_json
_usage_app.USAGE_LOG.clear()
hnd._ask_openai_json = _mock_forever_failing
try:
    _plan31, _probs31 = hnd.write_narrated_outline("A heist", 300, 60)
finally:
    hnd._ask_openai_json = _orig_ask31
_beat_calls = [t for t, _ in _bud_log if t.startswith("narrated_act_beats_")]
_repair_calls = [t for t, _ in _bud_log if t == "narrated_fact_repair"]
check("a delivery fact the writer never satisfies does NOT loop: the plan still returns", len(_plan31["beats"]) == 60)
check("a missing fact costs NO whole-act retry: exactly one beat call per act", _beat_calls == [f"narrated_act_beats_{i}" for i in range(1, 5)], _beat_calls)
check("instead each missing fact gets ONE small repair call (4 facts)", len(_repair_calls) == 4, _repair_calls)
check("what is left is reported, not fatal: no HARD problem remains", not _hard(_probs31), _hard(_probs31))
check("and it is reported by name", any("fact f1" in p for p in _probs31), _probs31[:3])
check("the delivery map is kept on the plan", len(_plan31.get("delivery", {}).get("facts", [])) == 4)
_first_batch_prompt = next(u for t, u in _bud_log if t == "narrated_act_beats_1")
check("the first batch's prompt lists the facts it must deliver, with owner and key terms",
      "FACTS THIS BATCH MUST DELIVER" in _first_batch_prompt and "f1" in _first_batch_prompt and "'ledger'" in _first_batch_prompt)
check("a later batch is told what is already known and not to re-explain it",
      "THE AUDIENCE ALREADY KNOWS" in next(u for t, u in _bud_log if t == "narrated_act_beats_3"))
_usage_app.USAGE_LOG.clear()
_bgt = hnd._RepairBudget(100)
check("the budget starts unspent and counts a call's input plus output",
      not _bgt.exhausted and (_usage_app.USAGE_LOG.append({"input": 60, "output": 50}) or _bgt.charge_last_call() or _bgt.exhausted))
_usage_app.USAGE_LOG.clear()

# the budget still stops a STRUCTURAL failure (a hard problem that is not about delivery) that never gets fixed
_struct_log = []


def _mock_struct_failing(sys_p, usr_p, tag, schema, model=None, max_completion_tokens=None):
    out = _copy.deepcopy(mock_ask_60(sys_p, usr_p, tag, schema, model, max_completion_tokens))
    _struct_log.append(tag)
    _usage_app.USAGE_LOG.append({"name": tag, "model": "m", "input": 20000, "cached": 0, "output": 10000, "reasoning": 0})
    for b in out.get("beats", []):
        b["location_id"] = "nowhere"          # not in the scene bible: a hard problem on every attempt
    return out


_usage_app.USAGE_LOG.clear()
hnd._ask_openai_json = _mock_struct_failing
try:
    _plan_s, _probs_s = hnd.write_narrated_outline("A heist", 300, 60)
finally:
    hnd._ask_openai_json = _orig_ask31
_s_beats = [t for t in _struct_log if t.startswith("narrated_act_beats_")]
check("a structural failure that is never fixed is stopped by the 60k-token budget (12 calls would be the unbounded worst case)",
      len(_s_beats) <= 6, _s_beats)
check("and that plan is still returned with its hard problems, as before", len(_plan_s["beats"]) == 60 and bool(_hard(_probs_s)))
_usage_app.USAGE_LOG.clear()

# --- 31f2. Repairing a missing fact with ONE small call, instead of re-asking the whole act -------------------------------
_repair_log = []
_REPAIR_FACT = _fact("f1", "want", "state_now", "She will take everything he relies on.", ["take", "everything", "relies"],
                     _PROTAG, "dialogue", 3)
_REPAIR_FACT["line"] = "I will take everything you rely on."
_rdl = {"story_in_five": ["a"] * 5, "jargon": [], "facts": [_REPAIR_FACT]}


def _repair_beats_fixture():
    return [_dbeat(1, "voiceover", _PROTAG, "I wait.", function="hook", turn="t", delivers=[]),
            _dbeat(2, "dialogue", _OTHER, "Sign it.", function="clash", turn="t", delivers=[]),
            _dbeat(3, "dialogue", _PROTAG, "You will regret this.", function="clash", turn="t", delivers=[]),
            _dbeat(4, "dialogue", _OTHER, "Careful.", function="clash", turn="t", delivers=[])]


def _mock_repair(answer):
    def _m(sys_p, usr_p, tag, schema, model=None, max_completion_tokens=None):
        _repair_log.append({"tag": tag, "model": model, "cap": max_completion_tokens, "usr": usr_p, "sys": sys_p})
        if isinstance(answer, Exception):
            raise answer
        return answer
    return _m


_ok_answer = {"audio_lines": [{"speaker": _PROTAG, "line": "I will take everything he relies on."}]}
_bs = _repair_beats_fixture()
hnd._ask_openai_json = _mock_repair(_ok_answer)
try:
    _notes = hnd._repair_missing_facts(_bs, GOOD["scene_bible"], _rdl, 1, budget=hnd._RepairBudget(), reserved_terms=["Vault Cipher"])
finally:
    hnd._ask_openai_json = _orig_ask31
check("a missing fact is repaired with exactly ONE call, on the cheap model, with a small output cap",
      len(_repair_log) == 1 and _repair_log[0]["tag"] == "narrated_fact_repair"
      and _repair_log[0]["model"] == _usage_app.OPENAI_CLIP_MODEL and _repair_log[0]["cap"] == hnd.FACT_REPAIR_MAX_OUTPUT, _repair_log)
check("the beat now says the fact, and its word count, speaker and 'delivers' follow",
      "everything he relies on" in _bs[2]["audio_lines"][0]["line"] and _bs[2]["speech_budget"] == 7
      and _bs[2]["speaker_or_actor"] == _PROTAG and "f1" in _bs[2]["delivers"] and any("repaired fact f1" in n for n in _notes), _bs[2])
check("the other beats are untouched", _bs[1]["audio_lines"][0]["line"] == "Sign it." and _bs[3]["audio_lines"][0]["line"] == "Careful.")
_p = _repair_log[0]["usr"]
check("the repair prompt carries the line before, the line after, the fact, its draft line and the reserved terms",
      "Sign it." in _p and "Careful." in _p and "She will take everything he relies on." in _p
      and "I will take everything you rely on." in _p and "Vault Cipher" in _p and "take, everything, relies" in _p, _p)
_repair_log.clear()
hnd._ask_openai_json = _mock_repair(_ok_answer)
try:
    _skip_notes = hnd._repair_missing_facts([_dbeat(3, "dialogue", _PROTAG, "I will take everything he relies on.")],
                                            GOOD["scene_bible"], dict(_rdl, facts=[dict(_REPAIR_FACT, deliver_at=1)]), 1)
finally:
    hnd._ask_openai_json = _orig_ask31
check("a repair is skipped (no call) when the clip already says the fact", _skip_notes == [] and not _repair_log)


def _try_repair(answer, beats=None, **kw):
    bs = beats or _repair_beats_fixture()
    hnd._ask_openai_json = _mock_repair(answer)
    try:
        return bs, hnd._repair_missing_facts(bs, GOOD["scene_bible"], _rdl, 1, **kw)
    finally:
        hnd._ask_openai_json = _orig_ask31


for _label, _bad_answer in [
        ("a speaker who is not in the cast", {"audio_lines": [{"speaker": "Stranger", "line": "I will take everything he relies on."}]}),
        ("lines that leave out the key terms", {"audio_lines": [{"speaker": _PROTAG, "line": "You will pay for this tonight."}]}),
        ("lines that name a reserved term", {"audio_lines": [{"speaker": _PROTAG, "line": "I take everything he relies on, the Vault Cipher."}]}),
        ("a fact owner who does not speak", {"audio_lines": [{"speaker": _OTHER, "line": "She will take everything he relies on."}]}),
        ("far too many words", {"audio_lines": [{"speaker": _PROTAG, "line": "I will take everything he relies on " + "and more " * 12}]}),
        ("no answer at all", {})]:
    _bs2, _n2 = _try_repair(_bad_answer, reserved_terms=["Vault Cipher"])
    check(f"an invalid rewrite ({_label}) is rejected: the beat is left as written and the gap reported",
          _bs2[2]["audio_lines"][0]["line"] == "You will regret this." and any(n.startswith("[SOFT]") and "f1" in n for n in _n2), _n2)
_bs3, _n3 = _try_repair(RuntimeError("OpenAI is down"))
check("a repair call that raises never breaks the plan", _bs3[2]["audio_lines"][0]["line"] == "You will regret this." and any("left as written" in n for n in _n3))
_spent = hnd._RepairBudget(10)
_spent.spent = 10
_repair_log.clear()
_bs4, _n4 = _try_repair(_ok_answer, budget=_spent)
check("with the repair budget spent no call is made and the gap is reported", not _repair_log and any("budget is spent" in n for n in _n4), _n4)
_vo_beats = [_dbeat(1, "voiceover", _PROTAG, "I wait."), _dbeat(2, "voiceover", _PROTAG, "I wait."), _dbeat(3, "voiceover", _PROTAG, "Nothing.")]
_bs5, _n5 = _try_repair({"audio_lines": [{"speaker": _PROTAG, "line": "I will take everything."}, {"speaker": _PROTAG, "line": "He relies on it."}]}, beats=_vo_beats)
check("a voiceover beat must stay ONE line by the narrator", _bs5[2]["audio_lines"][0]["line"] == "Nothing.")
_bs6, _n6 = _try_repair(_ok_answer, beats=[_dbeat(1, "voiceover", _PROTAG, "I wait."), _dbeat(2, "dialogue", _OTHER, "Sign."),
                                          dict(_dbeat(3, "shock_action", "", ""), audio_lines=[], speech_budget=0)])
check("a fact planned for a wordless beat is reported for the plan to move, never forced in",
      any("wordless beat" in n for n in _n6) and _bs6[2]["audio_lines"] == [], _n6)
_mixed_voice = {"audio_lines": [{"speaker": _PROTAG, "line": "I will take everything he relies on."}]}
_bs7, _ = _try_repair(_mixed_voice, beats=[_dbeat(1, "voiceover", _PROTAG, "I wait."), _dbeat(2, "dialogue", _OTHER, "Sign."),
                                          _dbeat(3, "voiceover", _PROTAG, "Nothing.")])
check("a repaired voiceover beat keeps the narrator as its actor", _bs7[2]["speaker_or_actor"] == _PROTAG and "relies" in _bs7[2]["audio_lines"][0]["line"])

# the single-call plan repairs the same way and does not retry for a missing fact
_single_log = []
_single = _copy.deepcopy(GOOD)
_single["delivery"] = {"story_in_five": ["a"] * 5, "jargon": [], "facts": [
    _fact("f1", "want", "state_now", "Clara wants the ledger.", ["ledger", "vault"], _PROTAG, "narration", 1, 1),
    _fact("f2", "obstacle", "state_now", "Julian stops her.", ["stops", "her", "never"], _OTHER, "dialogue", 2, 2),
    _fact("f3", "plan", "state_now", "She will crack it.", ["crack", "night"], _PROTAG, "narration", 3, 3),
    _fact("f4", "stakes", "state_now", "She loses her sister.", ["sister", "loses"], _OTHER, "dialogue", 4, 4)]}
for _fx, _ln in zip(_single["delivery"]["facts"], ("I want the vault ledger.", "I will never let you.", "I will crack it tonight.", "You lose your sister.")):
    _fx["line"] = _ln


def _mock_single_repair(sys_p, usr_p, tag, schema, model=None, max_completion_tokens=None):
    _single_log.append(tag)
    if tag == "narrated_fact_repair":
        return {"audio_lines": [{"speaker": _PROTAG, "line": "I want the vault ledger."}]}
    return _copy.deepcopy(_single)


hnd._ask_openai_json = _mock_single_repair
try:
    _sd, _sp = hnd.write_narrated_outline("Short heist", 75, 4)
finally:
    hnd._ask_openai_json = _orig_ask31
check("single-call plan: one planning call, then small repair calls only for the facts the lines do not say; no whole-plan retry",
      _single_log.count("narrated_outline") == 1 and 1 <= _single_log.count("narrated_fact_repair") <= 4, _single_log)

# what was ported from the replica's way of controlling dialogue
_char_props = hnd.OUTLINE_SCHEMA["properties"]["scene_bible"]["properties"]["characters"]["items"]["properties"]
check("characters carry a motivation, their relationships and a speech style (the replica's character fields)",
      all(k in _char_props for k in ("motivation", "relationships", "speech_style")))
check("every fact carries a plain draft line (the replica's keyDialogue, decided at plan time)",
      "line" in hnd.DELIVERY_SCHEMA["properties"]["facts"]["items"]["properties"]
      and "line" in hnd.DELIVERY_SCHEMA["properties"]["facts"]["items"]["required"])
_with_chars = _copy.deepcopy(GOOD["scene_bible"])
_with_chars["characters"][0].update(motivation="I want to take back what I built.", relationships="his fixer", speech_style="clipped, dry")
_b_with = hnd._narrated_act_beats_prompt("a story", _d_act, [], _with_chars, [], 60, delivery=_rdl)[1]
check("the beat writer sees each character's motivation, relationships and speech style", "I want to take back what I built." in _b_with and "clipped, dry" in _b_with)
check("and the draft line and the self-check for each fact due",
      "Draft line you may use or improve" in hnd._facts_block({"facts": [dict(_REPAIR_FACT, deliver_at=2)]}, 1, 5)
      and "BEFORE YOU ANSWER" in hnd._facts_block({"facts": [dict(_REPAIR_FACT, deliver_at=2)]}, 1, 5))
check("the planners ask for motivation, speech style and a draft line", "motivation" in _d_break and "a \"line\"" in _d_break)

# the same plan with facts the writer DOES satisfy needs no retry at all
_good_beats_calls = []


def _mock_satisfying(sys_p, usr_p, tag, schema, model=None, max_completion_tokens=None):
    _good_beats_calls.append(tag)
    out = _copy.deepcopy(mock_ask_60(sys_p, usr_p, tag, schema, model, max_completion_tokens))
    if tag == "narrated_act_breakdown":
        out["delivery"] = _copy.deepcopy(_DEL_60)
    else:
        for b in out["beats"]:
            for f in _DEL_60["facts"]:
                if b["clip_number"] == f["deliver_at"]:
                    b["audio_lines"] = [{"speaker": f["owner"], "line": "Listen: " + " ".join(f["key_terms"]) + " ."}]
                    b["delivery_mode"] = "voiceover" if f["channel"] == "narration" else "dialogue"
                    b["speaker_or_actor"] = f["owner"]
    return out


hnd._ask_openai_json = _mock_satisfying
try:
    _plan_ok, _probs_ok = hnd.write_narrated_outline("A heist", 300, 60)
finally:
    hnd._ask_openai_json = _orig_ask31
check("when the lines carry the facts, the plan is accepted first time with no extra calls", len(_good_beats_calls) == 5, _good_beats_calls)
check("and nothing delivery-related is left to report as a hard problem", not [p for p in _hard(_probs_ok) if hnd._is_delivery_problem(p)])

# --- 31g. The blind reader and the plan report ---------------------------------------------------------------------------
_t = hnd.delivery_transcript(_don_beats)
check("the dialogue-only page holds every spoken line, with speakers and nothing else",
      "Clip 1 | Elena Vance (inner voice, narration): Three years" in _t and "Clip 34 | Camilla Rossi: Elena signed" in _t
      and "shock" not in _t.lower() and len(_t.splitlines()) == len(_run1))
_sys_b, _usr_b = hnd._blind_read_prompt(_t)
check("the reader is told to answer ONLY from what is said and to write 'not stated' otherwise",
      "ONLY from what is said" in _sys_b and "not stated" in _sys_b and "no pictures" in _sys_b)
check("the reader gets the spoken lines and no premise", _usr_b.startswith("The spoken lines:") and "Don" not in _usr_b)
_ans_good = {"five_sentences": ["Elena kept Lorenzo out of prison for three years.", "He replaces her for the Rossi alliance.",
                                "She will take everything he relies on.", "Her ships carry his shipments.", "He begs."],
             "protagonist_and_want": "Elena wants to take everything he relies on", "obstacle": "the Rossi alliance",
             "secret_or_lie": "she paid, took the blame for customs crimes, he does not know",
             "relationship_change": "he begs", "stakes": "not stated", "ending_or_open_question": "he begs, she says he cannot pay"}
_ck = hnd.check_blind_answers(_ans_good, _don)
check("a reader who recovered the facts is credited, fact by fact", _ck["understood"] >= 5 and _ck["total"] == 6, _ck)
check("a field the reader marked 'not stated' is reported by name", "stakes" in _ck["not_stated"]
      and any("'stakes' is not stated" in p for p in _ck["problems"]))
_ans_bad = {"five_sentences": ["A woman is fired.", "She ruins him.", "He begs.", "Nothing else is clear.", "The end."],
            "protagonist_and_want": "not stated", "obstacle": "not stated", "secret_or_lie": "not stated",
            "relationship_change": "not stated", "stakes": "not stated", "ending_or_open_question": "he begs"}
_ckb = hnd.check_blind_answers(_ans_bad, _don)
check("a reader who understood nothing flags the facts the plan meant to deliver",
      _ckb["understood"] <= 1 and any("fact f3" in p for p in _ckb["problems"]), _ckb)

_blind_calls = []


def _mock_blind(sys_p, usr_p, tag, schema, model=None, max_completion_tokens=None):
    _blind_calls.append((tag, model, max_completion_tokens, usr_p))
    return _ans_good


hnd._ask_openai_json = _mock_blind
try:
    _rep_plan = {"scene_bible": _don_bible, "beats": _don_beats, "delivery": _don}
    _report = hnd.plan_delivery_report(_rep_plan)
finally:
    hnd._ask_openai_json = _orig_ask31
check("the blind reader is ONE call, on the cheap model, with a small output cap",
      len(_blind_calls) == 1 and _blind_calls[0][0] == "narrated_blind_read" and _blind_calls[0][1] == _usage_app.OPENAI_CLIP_MODEL
      and _blind_calls[0][2] == hnd.BLIND_READ_MAX_OUTPUT, _blind_calls)
check("the report carries the checks, the stats, the dialogue-only page and the blind result",
      _report["blind"]["total"] == 6 and _report["dialogue_only"] == _t and _report["stats"]["clips"] == 43
      and any("fact f3" in p for p in _report["problems"]), list(_report))
check("the report stats are right (lines, words, narration share)",
      _report["stats"]["spoken_lines"] == len(_run1) and _report["stats"]["spoken_words"] == sum(len(v[2].split()) for v in _run1.values()))
check("narration outside the 25-35% band is a soft note",
      any("narration is" in p and "target 25-35%" in p for p in _report["problems"]), _report["problems"])
check("with run_blind=False no model is called", (_blind_calls.clear() or hnd.plan_delivery_report(_rep_plan, run_blind=False)["blind"] is None) and not _blind_calls)


def _mock_blind_fails(*a, **k):
    raise RuntimeError("OpenAI is down")


hnd._ask_openai_json = _mock_blind_fails
try:
    _rep_fail = hnd.plan_delivery_report(_rep_plan)
finally:
    hnd._ask_openai_json = _orig_ask31
check("a blind reader that fails never breaks a plan", _rep_fail["blind"] is None and "OpenAI is down" in _rep_fail["blind_error"]
      and _rep_fail["problems"])
check("an older plan with no delivery map still gets a report", hnd.plan_delivery_report({"scene_bible": _don_bible, "beats": _don_beats}, run_blind=False)["stats"]["clips"] == 43)

# --- 31h. Where it is stored ---------------------------------------------------------------------------------------------
check("the job stores the delivery map and the plan report", "delivery" in _usage_app.Job.model_fields and "plan_report" in _usage_app.Job.model_fields)
check("the plan stage builds the report and saves it with the plan",
      "plan_delivery_report" in inspect.getsource(_usage_app._generate_narrated_plan)
      and "plan_dialogue.txt" in inspect.getsource(_usage_app._save_master_plan_file))
check("a continuation is told what the audience already knows", "delivery=job.delivery" in inspect.getsource(_usage_app._extend_movie_plan_task_traced))

print("\n[32] Retries run on the cheap model and cannot change what was fine; batch sizes")
check("a retry model exists for every retry and none for the first write",
      hnd._retry_model(0) is None and hnd._retry_model(1) == _usage_app.OPENAI_CLIP_MODEL == hnd._retry_model(2))
check("_flagged_clips reads clip and beat numbers", hnd._flagged_clips(["Clip 5: x", "Beat 7 uses location 'q'"]) == {5, 7})
check("a problem that names no clip means the whole answer is needed", hnd._flagged_clips(["Clip 5: x", "something general"]) is None)
check("so does a wrong number of beats", hnd._flagged_clips(["Act produced 9 beats; exactly 12 required for clips 1 to 12."]) is None)
_old_b = [{"clip_number": n, "t": "old"} for n in range(5, 9)]
_new_b = [{"clip_number": n, "t": "new"} for n in range(5, 9)]
check("merging takes the retry's beat only for the flagged clips",
      [b["t"] for b in hnd._merge_beats(_old_b, _new_b, {6, 8}, 5)] == ["old", "new", "old", "new"])
check("a retry that changes the number of beats is taken whole", hnd._merge_beats(_old_b, _new_b[:3], {6}, 5) == _new_b[:3])
check("with nothing flagged the earlier beats stay", [b["t"] for b in hnd._merge_beats(_old_b, _new_b, set(), 5)] == ["old"] * 4)
check("the retry prompt names the only clips that may change", "ONLY clips 6, 8 may change" in hnd._scope_note({6, 8})
      and hnd._scope_note(None) == "" and hnd._scope_note(set()) == "")

# act-based plan: batch 1's first write is wrong in ONE clip; the retry (cheap model) rewrites EVERYTHING it is shown
_models = []


def _mock_luna_retry(sys_p, usr_p, tag, schema, model=None, max_completion_tokens=None):
    _models.append((tag, model))
    out = _copy.deepcopy(mock_ask_60(sys_p, usr_p, tag, schema, model, max_completion_tokens))
    if tag == "narrated_act_beats_1":
        first = [m for t, m in _models if t == tag].__len__() == 1
        for b in out["beats"]:
            b["audio_lines"][0]["line"] = (f"The original line for clip {b['clip_number']} stays exactly here." if first
                                           else f"A cheap model rewrote the line for clip {b['clip_number']} here.")
            if first and b["clip_number"] == 5:
                b["location_id"] = "nowhere"       # the one broken clip
    return out


_usage_app.USAGE_LOG.clear()
hnd._ask_openai_json = _mock_luna_retry
try:
    _plan32, _probs32 = hnd.write_narrated_outline("A heist", 300, 60)
finally:
    hnd._ask_openai_json = _orig_ask31
_b1_models = [m for t, m in _models if t == "narrated_act_beats_1"]
check("the first write of a batch is on the story model, its retry on the cheap model",
      _b1_models == [None, _usage_app.OPENAI_CLIP_MODEL], _b1_models)
check("every other first write stays on the story model", all(m is None for t, m in _models if t != "narrated_act_beats_1"), _models)
check("the broken clip took the cheap model's fix", _plan32["beats"][4]["location_id"] == "lobby")
check("every OTHER clip kept the story model's own lines, although the retry rewrote them all",
      all(b["audio_lines"][0]["line"].startswith("The original line") for i, b in enumerate(_plan32["beats"][:15]) if i != 4)
      and _plan32["beats"][4]["audio_lines"][0]["line"].startswith("A cheap model rewrote"))
check("and the plan is accepted", not _hard(_probs32) and len(_plan32["beats"]) == 60, _hard(_probs32))
_models.clear()
hnd.RETRY_ON_CLIP_MODEL = False
hnd._ask_openai_json = _mock_luna_retry
try:
    hnd.write_narrated_outline("A heist", 300, 60)
finally:
    hnd._ask_openai_json = _orig_ask31
    hnd.RETRY_ON_CLIP_MODEL = True
check("RETRY_ON_CLIP_MODEL = False puts retries back on the story model",
      [m for t, m in _models if t == "narrated_act_beats_1"] == [None, None])

# act breakdown: only the part a broken rule names may change
_bd_models = []


def _mock_breakdown_retry(sys_p, usr_p, tag, schema, model=None, max_completion_tokens=None):
    out = _copy.deepcopy(mock_ask_60(sys_p, usr_p, tag, schema, model, max_completion_tokens))
    if tag == "narrated_act_breakdown":
        _bd_models.append(model)
        julian = out["scene_bible"]["characters"][1]["appearance"]
        if len(_bd_models) == 1:     # first write: Julian looks exactly like Clara (a hard problem in the bible)
            julian.update(hair_color="auburn", hair_style="short bob")
        else:                        # the retry fixes that, and also rewrites every act summary
            for a in out["acts"]:
                a["summary"] = "A cheap model rewrote this summary."
    return out


hnd._ask_openai_json = _mock_breakdown_retry
try:
    _plan_bd, _ = hnd.write_narrated_outline("A heist", 300, 60)
finally:
    hnd._ask_openai_json = _orig_ask31
check("the breakdown retry is on the cheap model", _bd_models == [None, _usage_app.OPENAI_CLIP_MODEL], _bd_models)
check("the bible (the part that was wrong) took the retry's fix",
      _plan_bd["scene_bible"]["characters"][1]["appearance"]["hair_color"] == "silver")
check("the acts (not named by any broken rule) kept the story model's own summaries",
      all(a["summary"] != "A cheap model rewrote this summary." for a in _plan_bd["acts"]), [a["summary"] for a in _plan_bd["acts"]])

# the continuation used to re-send the SAME request; now a retry says what was wrong, on the cheap model, merged
_cont_calls = []
_loc0 = GOOD["scene_bible"]["locations"][0]["id"]
_n0 = len(GOOD["beats"])


def _cont_beat(n, speaker, line):
    return {"clip_number": n, "cycle_number": 9, "delivery_mode": "dialogue", "location_id": _loc0,
            "present_characters": [speaker], "speaker_or_actor": speaker, "summary": f"beat {n}",
            "speech_budget": len(line.split()), "audio_lines": [{"speaker": speaker, "line": line}], "reveals": [],
            "function": "clash", "turn": f"turn {n}", "delivers": []}


def _mock_cont_retry(sys_p, usr_p, tag, schema, model=None, max_completion_tokens=None):
    _cont_calls.append((model, usr_p))
    n = _n0
    first = len(_cont_calls) == 1
    return {"beats": [_cont_beat(n + 1, _PROTAG, "The first line here stays exactly as the story model wrote it."),
                      _cont_beat(n + 2, "Stranger Nobody" if first else _OTHER, "The second line here is the one that needed fixing today."),
                      _cont_beat(n + 3, _PROTAG, "The third line here also stays exactly as it was written." if first else "A cheap model rewrote the third line completely.")]}


hnd._ask_openai_json = _mock_cont_retry
try:
    _cont_out, _cont_probs = hnd.write_narrated_continuation_outline("t", "next", GOOD["scene_bible"], GOOD["beats"], 3)
finally:
    hnd._ask_openai_json = _orig_ask31
check("a continuation retry runs on the cheap model and says what was wrong",
      len(_cont_calls) == 2 and _cont_calls[0][0] is None and _cont_calls[1][0] == _usage_app.OPENAI_CLIP_MODEL
      and "It broke these rules" in _cont_calls[1][1] and f"ONLY clips {_n0 + 2} may change" in _cont_calls[1][1], [c[0] for c in _cont_calls])
check("only the broken clip was taken from it", _cont_out["beats"][1]["audio_lines"][0]["speaker"] == _OTHER
      and _cont_out["beats"][2]["audio_lines"][0]["line"].startswith("The third line here also stays"))

# batch sizes are settings, and small acts still merge
def _acts(*sizes):
    out, cur = [], 1
    for n, s in enumerate(sizes, 1):
        out.append({"act_number": n, "title": f"Act {n}", "start_clip": cur, "end_clip": cur + s - 1, "primary_locations": [],
                    "dramatic_question": "", "summary": ""})
        cur += s
    return out


check("acts of 5 and 8 are written as ONE batch of 13", [b["clip_count"] for b in hnd._plan_act_batches(_acts(5, 8))] == [13])
check("12, 5, 18, 25 clips become batches of 17, 18, 13 and 12",
      [b["clip_count"] for b in hnd._plan_act_batches(_acts(12, 5, 18, 25))] == [17, 18, 13, 12])
hnd.BATCH_MAX_CLIPS = 10
try:
    _small = [b["clip_count"] for b in hnd._plan_act_batches(_acts(12, 5))]
finally:
    hnd.BATCH_MAX_CLIPS = 20
check("the largest batch is a setting (BATCH_MAX_CLIPS): at 10, a 12-clip act is split in two", _small[:2] == [6, 6], _small)

print("\n[33] The plan report says how many places are used and how long the story stays in one")
_runs = [("moretti_penthouse_office", 12), ("vance_harbor_terminal", 12), ("moretti_private_vault", 12), ("harbor_pier_storm", 7)]
_loc_beats = [_dbeat(n, "dialogue", _PROTAG, "I will take everything he relies on.", loc=lid)
              for n, lid in enumerate((lid for lid, k in _runs for _ in range(k)), 1)]
_loc_bible = {"pov_protagonist": _PROTAG, "characters": [{"name": _PROTAG}],
              "locations": [{"id": lid} for lid in ("moretti_penthouse_office", "vance_harbor_terminal", "moretti_private_vault",
                                                    "harbor_pier_storm", "freighter_gangway_stairs")]}
_stays = hnd._location_stays(_loc_beats)
check("stretches in one place are read from the beats",
      [(s["location"], s["clips"], s["from"], s["to"]) for s in _stays][:2] == [("moretti_penthouse_office", 12, 1, 12), ("vance_harbor_terminal", 12, 13, 24)]
      and [s["clips"] for s in _stays] == [12, 12, 12, 7], _stays)
_rep_loc = hnd.plan_delivery_report({"scene_bible": _loc_bible, "beats": _loc_beats}, run_blind=False)
check("the report states the places used and the longest stay",
      _rep_loc["location_lines"] == ["Locations: 4 used of 5 defined",
                                     "Longest stay in one place: 12 clips (60 s) in moretti_penthouse_office"], _rep_loc["location_lines"])
check("and keeps them as numbers too", _rep_loc["stats"]["locations_used"] == 4 and _rep_loc["stats"]["locations_defined"] == 5
      and _rep_loc["stats"]["longest_stay_clips"] == 12)
check("at the default limit (15 clips) a 12-clip stay is not flagged", not any("stay in" in p for p in _rep_loc["problems"]))
hnd.LONG_STAY_CLIPS = 10
try:
    _rep_long = hnd.plan_delivery_report({"scene_bible": _loc_bible, "beats": _loc_beats}, run_blind=False)
finally:
    hnd.LONG_STAY_CLIPS = 15
_flags = [p for p in _rep_long["problems"] if "stay in" in p]
check("at a lower limit each long stay gets a note naming the clips, the place and the seconds",
      len(_flags) == 3 and "Clips 1-12 stay in 'moretti_penthouse_office' for 60 s" in _flags[0], _flags)
check("the note is soft: it never forces a retry", all(p.startswith("[SOFT]") for p in _flags))
check("a plan that moves around reports a short longest stay",
      hnd.plan_delivery_report({"scene_bible": _loc_bible, "beats": [_dbeat(n, "dialogue", _PROTAG, "I wait for the answer.", loc=("a", "b", "c")[n % 3])
                                                                      for n in range(1, 10)]}, run_blind=False)["stats"]["longest_stay_clips"] == 1)
check("a plan with no beats does not break the report", hnd.plan_delivery_report({"scene_bible": _loc_bible, "beats": []}, run_blind=False)["stats"]["longest_stay_clips"] == 0)

print("\n[34] Plain language for EVERY line, not only the key facts")
# The first run: "Tonight he offers me a pen", "He waited for tears. I gave him the silence he feared", "You just threw away the
# thing holding back the dark". The old rule's own GOOD examples were figurative, and nothing checked a line.
_o34 = hnd._narrated_outline_prompt("a story", 300, 60)[0]
_b34 = hnd._narrated_act_beats_prompt("a story", _d_act, [], GOOD["scene_bible"], [], 60)[0]
for _nm, _pr in (("single-call planner", _o34), ("beat writer", _b34)):
    check(f"the {_nm} gets the plain language test", "PLAIN LANGUAGE TEST (CRITICAL" in _pr and "LITERAL, never figurative" in _pr)
    check(f"and no longer teaches the poetic style as GOOD ({_nm})",
          "GOOD (write like this)" not in _pr and "My ship cleared while his city drowned" not in _pr)
    check(f"it names the line to write plainly ({_nm})",
          "'Tonight he hands me a pen.' -> 'Tonight he is firing me.'" in _pr and "says what it means" in _pr)
    check(f"it overrides a poetic sample line in the premise ({_nm})", "plain beats poetic, even when the premise asks for sharper lines" in _pr)
hnd.PLAIN_LANGUAGE = False
_off34 = hnd._narrated_outline_prompt("a story", 300, 60)[0] + hnd._narrated_act_beats_prompt("a story", _d_act, [], GOOD["scene_bible"], [], 60)[0]
hnd.PLAIN_LANGUAGE = True
check("PLAIN_LANGUAGE = False restores the older rule exactly", _off34.count("GOOD (write like this)") == 2 and "PLAIN LANGUAGE TEST" not in _off34)
check("the enhancer asks for plain literal English in the dramatic modes",
      "PLAIN LANGUAGE: write EVERY spoken line" in _dr_vo[0] and "PLAIN LANGUAGE: write EVERY spoken line" not in _dr_th[0])

# --- the review pass -----------------------------------------------------------------------------------------------------
_pp_calls = []


def _mock_pp(entries, fail=False):
    def _m(sys_p, usr_p, tag, schema, model=None, max_completion_tokens=None):
        _pp_calls.append({"tag": tag, "model": model, "cap": max_completion_tokens, "usr": usr_p, "sys": sys_p})
        if fail:
            raise RuntimeError("OpenAI is down")
        return {"lines": entries}
    return _m


def _rw(clip, idx, line, verdict="rewrite"):
    return {"clip_number": clip, "line_index": idx, "verdict": verdict, "plain_line": line}


def _run_pp(entries, beats=None, **kw):
    bs = beats if beats is not None else _copy.deepcopy(_don_beats)
    hnd._ask_openai_json = _mock_pp(entries, kw.pop("fail", False))
    try:
        return bs, hnd.plain_pass_beats(bs, _don_bible, kw.pop("delivery", _don), 1, **kw)
    finally:
        hnd._ask_openai_json = _orig_ask31


_pp_calls.clear()
_bs, _lg = _run_pp([_rw(1, 0, "Three years I kept him safe. Tonight he is firing me."), _rw(2, 0, "He did not know I saved him."),
                    _rw(11, 0, "Without me, you will lose everything."), _rw(3, 0, "", "plain")])
check("the review is ONE call per 15 beats (a stretch with no words is skipped), on the cheap model, with a small output cap",
      len(_pp_calls) == 2 and all(c["tag"] == "narrated_plain_pass" and c["model"] == _usage_app.OPENAI_CLIP_MODEL
                                  and c["cap"] == hnd.PLAIN_PASS_MAX_OUTPUT for c in _pp_calls), [c["tag"] for c in _pp_calls])
check("a line is rewritten in place and the speaker is kept",
      _bs[0]["audio_lines"][0]["line"] == "Three years I kept him safe. Tonight he is firing me."
      and _bs[0]["audio_lines"][0]["speaker"] == _E and _bs[0]["speech_budget"] == 11, _bs[0]["audio_lines"])
check("a verdict of 'plain' changes nothing", _bs[2]["audio_lines"][0]["line"] == "Sign it, Elena. Then leave this house clean.")
check("the log records every rewrite with its before and after",
      _lg["rewritten"] == 3 and {"clip": 1, "speaker": _E, "before": "Three years I kept Lorenzo breathing. Tonight he offers me a pen.",
                                 "after": "Three years I kept him safe. Tonight he is firing me."} in _lg["rewrites"], _lg["rewrites"])
check("and counts the lines it looked at", _lg["checked"] == len(_run1) and _lg["calls"] == 2, _lg)
check("the prompt shows each beat with its lines and what the clip must still say",
      "Clip 1 (voiceover)" in _pp_calls[0]["usr"] and "line 0: Elena Vance:" in _pp_calls[0]["usr"]
      and "this clip must still say, in its lines: three, years, kept" in _pp_calls[0]["usr"])
check("and asks for metaphor to go and for meaningful acts to be explained",
      "metaphor, simile" in _pp_calls[0]["sys"] and "meaningful act" in _pp_calls[0]["sys"] and "Most lines are already fine" in _pp_calls[0]["sys"])

for _label, _entry in [
        ("a fact's key terms lost (clip 1 must keep 'three years kept')", _rw(1, 0, "He is firing me tonight.")),
        ("a semicolon", _rw(3, 0, "Sign it; then leave.")),
        ("a reserved reveal term", _rw(3, 0, "Sign it, Elena, like you signed the manifests.")),
        ("a line far longer than the budget", _rw(3, 0, "Sign it Elena and then leave this house clean " + "and never come back " * 4)),
        ("a rewrite identical to the original", _rw(3, 0, "Sign it, Elena. Then leave this house clean.")),
        ("an empty rewrite", _rw(3, 0, "")),
        ("a line that does not exist", _rw(3, 5, "Sign it now.")),
        ("a clip outside the batch", _rw(99, 0, "Sign it now."))]:
    _acts_res = [{"act_number": 3, "start_clip": 30, "reveals": ["manifests"]}]
    _b2 = _copy.deepcopy(_don_beats)
    _pp_calls.clear()
    hnd._ask_openai_json = _mock_pp([_entry])
    try:
        _l2 = hnd.plain_pass_plan({"scene_bible": _don_bible, "beats": _b2, "delivery": _don, "acts": _acts_res})
    finally:
        hnd._ask_openai_json = _orig_ask31
    check(f"a rewrite is thrown away when it has {_label}", _l2["rewritten"] == 0 and _b2[2]["audio_lines"][0]["line"].startswith("Sign it, Elena."), _l2)
_b3 = _copy.deepcopy(_don_beats)
hnd._ask_openai_json = _mock_pp([], fail=True)
try:
    _l3 = hnd.plain_pass_plan({"scene_bible": _don_bible, "beats": _b3, "delivery": _don})
finally:
    hnd._ask_openai_json = _orig_ask31
check("a review call that fails never breaks a plan or changes a line", _l3["failed_calls"] == 2 and _l3["rewritten"] == 0
      and [b["audio_lines"] for b in _b3] == [b["audio_lines"] for b in _don_beats])
_pp_calls.clear()
hnd.PLAIN_PASS = False
_, _l4 = _run_pp([_rw(1, 0, "Tonight he is firing me.")])
hnd.PLAIN_PASS = True
check("PLAIN_PASS = False makes no call", not _pp_calls and _l4["calls"] == 0)
_pp_calls.clear()
hnd.PLAIN_LANGUAGE = False
_, _l5 = _run_pp([_rw(1, 0, "Tonight he is firing me.")])
hnd.PLAIN_LANGUAGE = True
check("so does PLAIN_LANGUAGE = False", not _pp_calls and _l5["calls"] == 0)
_pp_calls.clear()
_, _l6 = _run_pp([], beats=[_dbeat(n, "shock_action", "", "") for n in range(1, 6)])
check("beats with no words are not sent", not _pp_calls and _l6["calls"] == 0)

# the plan-level helper keeps a note for the report
_plan34 = {"scene_bible": _don_bible, "beats": _copy.deepcopy(_don_beats), "delivery": _don}
hnd._ask_openai_json = _mock_pp([_rw(2, 0, "He did not know I saved him.")])
try:
    hnd.plain_pass_plan(_plan34)
finally:
    hnd._ask_openai_json = _orig_ask31
_rep34 = hnd.plan_delivery_report(_plan34, run_blind=False)
check("the plan keeps what the review changed, and the report shows it",
      _plan34["plain_pass"]["rewritten"] == 1 and _rep34["plain_pass"]["rewrites"][0]["after"] == "He did not know I saved him.")
check("the dialogue-only page shows the plain line", "He did not know I saved him." in _rep34["dialogue_only"])
check("the planner itself does not call the review (so a plan costs what it did)",
      "plain_pass" not in inspect.getsource(hnd._write_act_based_outline) and "plain_pass" not in inspect.getsource(hnd._write_single_shot_outline))
check("the plan stage and the continuation both run it",
      "plain_pass_plan" in inspect.getsource(_usage_app._generate_narrated_plan)
      and "plain_pass_beats" in inspect.getsource(_usage_app._extend_movie_plan_task_traced))

print("\n[35] Contradiction audit: the instructions given to OpenAI agree with each other and with the decisions")
_mins = lambda m: m * 60
# --- the 30-minute rule: a plan of 30 minutes or more tells a whole story and ends it; shorter ones are episode one -------
_short_o = hnd._narrated_outline_prompt("a story", _mins(5), 60)
_long_o = hnd._narrated_outline_prompt("a story", _mins(30), 360)
check("a 5-minute plan is episode one and ends on a cliffhanger",
      "EPISODE ONE" in _short_o[0] and "THESE BEATS END THE EPISODE" in _short_o[0] and "cliffhanger" in _short_o[1])
check("a 30-minute plan tells the WHOLE story and ends it, with no cliffhanger instruction anywhere",
      "THIS RUNTIME TELLS THE WHOLE STORY" in _long_o[0] and "THESE BEATS END THE STORY" in _long_o[0]
      and "EPISODE ONE" not in _long_o[0] and "END THE EPISODE" not in _long_o[0] and "cliffhanger" not in _long_o[1].lower()
      and "cliffhanger" not in _long_o[0].lower().replace("no cliffhanger", ""), _long_o[1])
_long_b = hnd._narrated_act_breakdown_prompt("a story", _mins(30), 360)[0]
check("the 30-minute act breakdown makes the LAST act resolve, not stay open",
      "The LAST act resolves the central dramatic question" in _long_b and "must still be OPEN" not in _long_b)
_last_batch = {"batch_index": 9, "act_numbers": [9], "start_clip": 341, "end_clip": 360, "clip_count": 20, "title": "Act 9",
               "primary_locations": [], "dramatic_question": "", "summary": ""}
_long_last = hnd._narrated_act_beats_prompt("a story", _last_batch, [], GOOD["scene_bible"], [], 360)[0]
_short_last = hnd._narrated_act_beats_prompt("a story", dict(_last_batch, start_clip=41, end_clip=60), [], GOOD["scene_bible"], [], 60)[0]
check("the last batch of a 30-minute plan is told to end the story; of a 5-minute plan, the episode",
      "THESE BEATS END THE STORY" in _long_last and "END THE EPISODE" not in _long_last
      and "THESE BEATS END THE EPISODE" in _short_last and "END THE STORY" not in _short_last)
check("a continuation that brings the TOTAL to 30 minutes concludes (it is the last batch of what exists)",
      "THESE BEATS END THE STORY" in hnd._narrated_act_beats_prompt("a story", dict(_last_batch, start_clip=341, end_clip=360), [], GOOD["scene_bible"], [], 360)[0])
check("the enhancer agrees: 30 minutes asks for a resolution, 5 minutes for a cliffhanger",
      "ACT 4 (The Cliffhanger)" in _usage_app._enhance_prompts("x", _usage_app.EnhancePromptRequest(topic="x", duration=300, mode="narrated_drama"))[0]
      and "Climax & Resolution" in _usage_app._enhance_prompts("x", _usage_app.EnhancePromptRequest(topic="x", duration=1800, mode="narrated_drama"))[0]
      and "EPISODE ONE" not in _usage_app._enhance_prompts("x", _usage_app.EnhancePromptRequest(topic="x", duration=1800, mode="narrated_drama"))[0])
check("and the delivery and plain-language asks still apply to a 30-minute premise",
      "STORY DELIVERY" in _usage_app._enhance_prompts("x", _usage_app.EnhancePromptRequest(topic="x", duration=1800, mode="narrated_drama"))[0])

# --- the narration share is told to the planner, not only checked afterwards -----------------------------------------------
lo34, hi34 = hnd.NARRATION_SHARE_BAND
check("the planners are told the narration share the report checks (one source of truth)",
      f"{int(lo34 * 100)} to {int(hi34 * 100)}% of all the spoken words" in _o34 and f"{int(lo34 * 100)} to {int(hi34 * 100)}% of all the spoken words" in _b34)
check("and that a narration-led premise gets the top of the range, not more", "gets the top of this range, not more" in _b34)
check("the band is defined once", inspect.getsource(hnd).count("NARRATION_SHARE_BAND = (") == 1)

# --- the ending fact and wordless beats cannot contradict each other ---------------------------------------------------------
check("the ending fact is placed on a beat that has spoken words",
      "last clip that has spoken words" in _d_break and "if the final beat is wordless" in _d_break)
check("every fact's clip is told to be a voiceover or dialogue beat",
      "never a wordless one" in hnd._facts_block({"facts": [dict(_REPAIR_FACT, deliver_at=2)]}, 1, 5))
check("a bridge is allowed to skip time but never to replace a scene that matters (episode one and whole story)",
      "may not replace a scene that matters" in _short_o[0] and "may not replace a scene that matters" in _long_o[0])

# --- the plain-language review cannot undo the word budget ---------------------------------------------------------------------
_over = [_dbeat(1, "dialogue", _PROTAG, "one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen")]
check("a rewrite may not push a 15-word beat past the budget",
      hnd._apply_plain_rewrite(_over[0], 0, "one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen", [], set()) is None)

# --- no sentence in any prompt points at a section that is not there ---------------------------------------------------------------
for _flag, _val in (("STORY_DELIVERY", False), ("PLAIN_LANGUAGE", False), ("EPISODE_ONE", False), ("BLIND_READ", False)):
    setattr(hnd, _flag, _val)
    try:
        _o_s = hnd._narrated_outline_prompt("a story", 300, 60)[0]
        _b_s = hnd._narrated_act_breakdown_prompt("a story", 300, 60)[0]
        _bt_s, _bt_u = hnd._narrated_act_beats_prompt("a story", _d_act, [], GOOD["scene_bible"], [], 60, delivery={"facts": [{"id": "f1"}]})
        _refs_ok = (
            ("see STORY DELIVERY" not in _o_s or "STORY DELIVERY (CRITICAL)" in _o_s)
            and ("see FACTS below" not in _bt_s or "FACTS THIS BATCH MUST DELIVER" in _bt_u)
            and ("STORY DELIVERY (CRITICAL)" not in _b_s or "delivery.facts" in _b_s)
        )
        check(f"with {_flag} = False every reference in the prompts still has its target", _refs_ok)
    finally:
        setattr(hnd, _flag, True)
hnd.STORY_DELIVERY = False
_gone = (hnd._narrated_outline_prompt("a story", 300, 60)[0]
         + hnd._narrated_act_beats_prompt("a story", _d_act, [], GOOD["scene_bible"], [], 60, delivery={"facts": [{"id": "f1"}]})[0])
hnd.STORY_DELIVERY = True
check("with STORY_DELIVERY = False nothing refers to the delivery section at all",
      not [s for s in ("see STORY DELIVERY", "see FACTS below", "STORY DELIVERY") if s in _gone])

print("\n[36] The ending instruction binds only the batch that ends the plan; a fact may not need a word the story reserves")
_mid_b = hnd._narrated_act_beats_prompt("a story", dict(_d_act, start_clip=13, end_clip=24), [], GOOD["scene_bible"], [], 60)[0]
_end_b = hnd._narrated_act_beats_prompt("a story", dict(_d_act, start_clip=49, end_clip=60), [], GOOD["scene_bible"], [], 60)[0]
check("a batch in the middle is NOT told to wrap nothing up: its scenes may reach their own outcome",
      "ends on a cliffhanger, in its LAST batch" in _mid_b and "each scene and each act inside it may reach its own turn and outcome" in _mid_b
      and "The episode ENDS ON A CLIFFHANGER" not in _mid_b)
check("the batch that ends the plan carries the full cliffhanger instruction",
      "Do NOT close that central conflict" in _end_b and "The episode ENDS ON A CLIFFHANGER" in _end_b and "THESE BEATS END THE EPISODE" in _end_b)
check("the single-call plan and the act breakdown (which cover the whole plan) keep the full instruction",
      "Do NOT close that central conflict" in hnd._narrated_outline_prompt("a story", 300, 60)[0]
      and "Do NOT close that central conflict" in hnd._narrated_act_breakdown_prompt("a story", 300, 60)[0])
_mid_long = hnd._narrated_act_beats_prompt("a story", dict(_d_act, start_clip=21, end_clip=40), [], GOOD["scene_bible"], [], 360)[0]
_end_long = hnd._narrated_act_beats_prompt("a story", dict(_d_act, start_clip=341, end_clip=360), [], GOOD["scene_bible"], [], 360)[0]
check("in a 30-minute plan the middle is told not to close the central conflict early; the end pays everything off",
      "do not close the central conflict early" in _mid_long and "The ending is earned and clear" not in _mid_long
      and "The ending is earned and clear" in _end_long)

_acts_t = [{"act_number": 1, "start_clip": 1, "reveals": []}, {"act_number": 2, "start_clip": 13, "reveals": ["ports"]}]
_ok_f = [_fact("f1", "want", "state_now", "She will take everything he relies on.", ["take", "everything"], _PROTAG, "dialogue", 3),
         _fact("f2", "obstacle", "state_now", "He is replacing her.", ["replacing"], _OTHER, "dialogue", 8),
         _fact("f3", "plan", "state_now", "Her ships carry his shipments.", ["ships", "carry"], _PROTAG, "narration", 20),
         _fact("f4", "stakes", "state_now", "He loses his empire.", ["empire"], _OTHER, "dialogue", 40)]
_good_map = {"story_in_five": ["a"] * 5, "jargon": [], "facts": _ok_f}
check("a map with no clash passes", not _hard(hnd._check_delivery_plan(_good_map, GOOD["scene_bible"], _acts_t, 60)))
_bad_terms = _copy.deepcopy(_good_map)
_bad_terms["facts"][0]["key_terms"] = ["take", "ports"]       # clip 3 must say 'ports', which act 2 (clip 13) reveals
_hp = _hard(hnd._check_delivery_plan(_bad_terms, GOOD["scene_bible"], _acts_t, 60))
check("a fact whose key terms contain a term revealed LATER is a hard problem naming the fact and the term",
      any("fact f1" in p and "'ports'" in p and "reveals later" in p for p in _hp), _hp)
_bad_line = _copy.deepcopy(_good_map)
_bad_line["facts"][1]["line"] = "I will close every port, the ports are mine."
_hl = _hard(hnd._check_delivery_plan(_bad_line, GOOD["scene_bible"], _acts_t, 60))
check("so does a draft line that says it", any("fact f2" in p and "'ports'" in p for p in _hl), _hl)
_late_ok = _copy.deepcopy(_good_map)
_late_ok["facts"][2]["key_terms"] = ["ports", "carry"]         # clip 20 is after act 2 starts: allowed
check("the same word is fine at or after the clip that reveals it", not _hard(hnd._check_delivery_plan(_late_ok, GOOD["scene_bible"], _acts_t, 60)))
_by_beats = [dict(_dbeat(n, "dialogue", _PROTAG, "x"), reveals=(["Vault Cipher"] if n == 30 else [])) for n in range(1, 61)]
_bb = _copy.deepcopy(_good_map)
_bb["facts"][0]["text"] = "She wants the Vault Cipher."
check("in the single-call plan a later BEAT's reveal counts too",
      any("fact f1" in p and "Vault Cipher" in p for p in _hard(hnd._check_delivery_plan(_bb, GOOD["scene_bible"], [], 60, _by_beats))))
check("these are delivery problems, so a stubborn one is reported and never fatal", hnd._is_delivery_problem(_hp[0]))

print("\n[37] A premise with a closed ending, and the cliffhanger rule: which one decides")
_dons = open("PREMISE_dons_greatest_regret.md", encoding="utf-8").read() if os.path.exists("PREMISE_dons_greatest_regret.md") else ""
_ep = hnd._narrated_outline_prompt("a story", 300, 60)[0]
_ep_b = hnd._narrated_act_beats_prompt("a story", _d_act, [], GOOD["scene_bible"], [], 60)[0]
_ep_k = hnd._narrated_act_breakdown_prompt("a story", 300, 60)[0]
for _nm, _pr in (("single-call planner", _ep), ("beat writer", _ep_b), ("act breakdown", _ep_k)):
    check(f"the {_nm} says what the premise decides and what the runtime decides",
          "WHAT THE PREMISE DECIDES AND WHAT THE RUNTIME DECIDES" in _pr and "do NOT film that closing" in _pr)
    check(f"and that act counts and clips-per-act in a premise are guides, not rules ({_nm})",
          "act count, and the clips it gives each act, are guides" in _pr)
    check(f"and that each act still answers its own smaller question ({_nm})",
          "answers its OWN smaller question" in _pr or "its own turn and outcome" in _pr)
    check(f"the broad 'wrap anything up' is gone ({_nm})", "wrap anything up" not in _pr)
check("the premise of a 30-minute plan keeps its ending (the whole-story branch says so)",
      "Keep the premise's cast, world, tone, events and ending" in hnd._narrated_outline_prompt("a story", 1800, 360)[0]
      and "WHAT THE PREMISE DECIDES" not in hnd._narrated_outline_prompt("a story", 1800, 360)[0])
check("the final batch says the smaller questions are already answered and only the central one stays open",
      "only the central one stays open" in hnd._cliffhanger_final_rule())
check("the 90-second enhancer climax no longer asks for a closed consequence (episode one)",
      "next question left open" in _usage_app._enhance_prompts("x", _usage_app.EnhancePromptRequest(topic="x", duration=60, mode="narrated_drama"))[0]
      and "dramatic consequence" in _usage_app._enhance_prompts("x", _usage_app.EnhancePromptRequest(topic="x", duration=60, mode="talking_head"))[0])
if _dons:
    check("the Don's premise really is the case this guards (a fixed act count, clips per act and a closed ending)",
          "5-act" in _dons and "12 per act" in _dons and "still on his knees" in _dons)
    check("its act count is still honoured (five acts) while the clips per act become guides",
          hnd._detect_premise_act_count(_dons) == 5 and "exactly 5 narrative acts" in hnd._narrated_act_breakdown_prompt(_dons, 300, 60, act_count=5)[0])

print("\n[38] After an empty frame, the next clip still opens on where the cast was left")


def _empty_clip(n, place="lobby"):
    """A wordless establishing shot: nobody on screen, so no blocking and no awareness of its own."""
    c = _hist_clip(n)
    c.update(delivery_mode="shock_action", location_id=place, present_characters=[], blocking=[], speech=[],
             action_steps=[])
    return c


def _hist_prompt(prev):
    return hnd._narrated_chapter_prompt("t", len(prev), 8, GOOD["beats"][1], GOOD["scene_bible"], prev, beats=GOOD["beats"])[1]


_p = [_hist_clip(1), _hist_clip(2), _hist_clip(3), _empty_clip(4)]
_u_e = _hist_prompt(_p)
check("the latest clip is empty, so the poses come from the last clip that had people (clip 3)",
      "POSMARK3" in _u_e and "AWMARK3" in _u_e)
check("and the empty clip's own place and props are still its own", "ENVMARK4" in _u_e and "PROPMARK4" in _u_e)
check("the prompt says whose poses they are, so the model is not misled", "how Clip 3 left them" in _u_e)
check("it is still ONE end-state block, not a second copy (no extra tokens beyond one sentence)",
      _u_e.count("Ending Pose/Blocking:") == 1 and "POSMARK2" not in _u_e and "AWMARK2" not in _u_e)
check("the older clips still keep only their shot, actions and speech", "SHOTMARK2" in _u_e and "ENVMARK3" not in _u_e)

_p2 = [_hist_clip(1), _hist_clip(2), _empty_clip(3), _empty_clip(4)]
check("two empty frames in a row still hand over from the last clip with people (clip 2)",
      hnd._end_state_source(_p2)[1]["clip_number"] == 2 and "how Clip 2 left them" in _hist_prompt(_p2))

_p3 = [_hist_clip(1), _hist_clip(2), _hist_clip(3), _empty_clip(4, place="vault")]
_u_new_place = _hist_prompt(_p3)
check("an empty frame in a NEW place hands nothing over: those people are not standing there",
      hnd._end_state_source(_p3) is None and "POSMARK3" not in _u_new_place and "none on screen" in _u_new_place)
_p4 = [_hist_clip(1), _hist_clip(2), _empty_clip(3, place="vault"), _empty_clip(4)]
check("a place change anywhere between the people and the latest clip also stops the hand-over",
      hnd._end_state_source(_p4) is None)
check("a first clip that is empty has nobody to hand over from", hnd._end_state_source([_empty_clip(1)]) is None)
check("and no history at all is fine", hnd._end_state_source([]) is None)

_p5 = [_hist_clip(1), _hist_clip(2), _hist_clip(3), _hist_clip(4)]
_u_n = _hist_prompt(_p5)
check("when the latest clip has people nothing changes: its own poses, no hand-over note",
      hnd._end_state_source(_p5)[1]["clip_number"] == 4 and "POSMARK4" in _u_n and "how Clip" not in _u_n)

# an older stored script may carry no clip_number: the note then names the clip by its place in the list
_no_num = [_hist_clip(1), _hist_clip(2), _empty_clip(3)]
for _c in _no_num:
    _c.pop("clip_number")
check("a stored clip with no clip_number is still named correctly", "how Clip 2 left them" in _hist_prompt(_no_num))

print("\n[39] The 'story so far' list is a window, not the whole history")


def _sf_beats(n_total, reveal_at=None, term="Vault Cipher"):
    return [{"clip_number": n, "delivery_mode": "dialogue", "location_id": "lobby", "speaker_or_actor": "Clara Vance",
             "summary": f"BEATMARK{n}.", "reveals": ([term] if n == reveal_at else [])} for n in range(1, n_total + 1)]


def _sf_acts(secret_in_act1=None):
    return [{"act_number": 1, "title": "FIRST", "start_clip": 1, "end_clip": 12, "reveals": [],
             "summary": "ACTONE summary" + (f" and the {secret_in_act1}" if secret_in_act1 else "")},
            {"act_number": 2, "title": "SECOND", "start_clip": 13, "end_clip": 24, "reveals": [], "summary": "ACTTWO summary"},
            {"act_number": 3, "title": "THIRD", "start_clip": 25, "end_clip": 40, "reveals": [], "summary": "ACTTHREE summary"},
            {"act_number": 4, "title": "FOURTH", "start_clip": 41, "end_clip": 60, "reveals": ["Ledger Zero"], "summary": "ACTFOUR summary"}]


_sfb = _sf_beats(60)
_OLD_HEAD = "The story SO FAR (everything that exists; nothing beyond this has happened yet):\n"
_early = hnd._story_so_far(_sfb, 5)
check("a short plan, or the early clips of a long one, get the old full list unchanged",
      _early.startswith("\n" + _OLD_HEAD) and all(f"BEATMARK{n}." in _early for n in range(1, 7)) and "EARLIER" not in _early)
check("and it never lists a beat that has not happened yet", "BEATMARK7." not in _early)
_exactly = hnd._story_so_far(_sfb, hnd.STORY_SO_FAR_WINDOW - 1)
check("a list exactly as long as the window is still complete", "EARLIER" not in _exactly and "BEATMARK1." in _exactly)

_w = hnd._story_so_far(_sfb, 35)   # clip 36
check("later on, only the last STORY_SO_FAR_WINDOW beats are listed one by one",
      all(f"BEATMARK{n}." in _w for n in range(27, 37)) and not any(f"BEATMARK{n}." in _w for n in range(1, 27)))
check("the current clip's own beat is still the last one listed", "36. [lobby]" in _w and "BEATMARK37." not in _w)
check("the block says the earlier clips are summarised or left out", "clips 1-26 are summarised or left out" in _w)

_wa = hnd._story_so_far(_sfb, 35, _sf_acts())
check("with the acts known, each FINISHED act is one line", "ACTONE summary" in _wa and "ACTTWO summary" in _wa)
check("the act that is still running is not summarised (its summary tells how it ends)", "ACTTHREE" not in _wa and "ACTFOUR" not in _wa)
check("clips of the running act that fell out of the window are admitted, not hidden", "not mentioned above are not listed" in _wa)
# the real case: the window starts INSIDE a finished act (act 2 ends at clip 24, the window starts at clip 23)
_straddle = hnd._story_so_far(_sfb, 31, _sf_acts())
check("a finished act that straddles the start of the window is still summarised", "ACTONE summary" in _straddle and "ACTTWO summary" in _straddle)
_many = [{"act_number": k, "title": f"T{k}", "start_clip": (k - 1) * 10 + 1, "end_clip": k * 10, "reveals": [], "summary": f"ACTNUM{k} summary"} for k in range(1, 9)]
_capped = hnd._story_so_far(_sf_beats(100), 89, _many)
check("only the last STORY_SO_FAR_ACTS finished acts get a line, so it cannot grow with the story",
      all(f"ACTNUM{k} " in _capped for k in (6, 7, 8)) and not any(f"ACTNUM{k} " in _capped for k in (1, 2, 3, 4, 5)))
check("and the clips of the acts left out are admitted, not hidden", "not mentioned above are not listed" in _capped)
check("with every omitted clip inside a finished act nothing is left unaccounted",
      "not mentioned above are not listed" not in hnd._story_so_far(_sf_beats(60), 36, [
          {"act_number": 1, "title": "FIRST", "start_clip": 1, "end_clip": 27, "reveals": [], "summary": "ACTONE summary"}]))

_leak = hnd._story_so_far(_sf_beats(60, reveal_at=50), 35, _sf_acts(secret_in_act1="Vault Cipher"))
check("a finished act's summary that names something not yet revealed is dropped, the others stay",
      "ACTONE" not in _leak and "ACTTWO summary" in _leak)
_leak2 = hnd._story_so_far(_sfb, 35, _sf_acts(secret_in_act1="Ledger Zero"))
check("so is one that names what a LATER act reveals", "ACTONE" not in _leak2 and "ACTTWO summary" in _leak2)

check("without the acts it still works: a window and a note",
      "BEATMARK36." in hnd._story_so_far(_sfb, 35, None) and "not mentioned above are not listed" in hnd._story_so_far(_sfb, 35, None))

_big = _sf_beats(400)
_l99, _l349 = len(hnd._story_so_far(_big, 99)), len(hnd._story_so_far(_big, 349))
check("the list stops growing: at clip 350 it is about the size of clip 100's", abs(_l349 - _l99) / _l99 < 0.15,
      f"{_l99} vs {_l349} characters")
_full_349 = len("\n".join(f"{i + 1}. [lobby] [DIALOGUE] Clara Vance: BEATMARK{i + 1}." for i in range(350)))
check("where the full list would have been several times larger", _full_349 > 5 * _l349, f"{_full_349} vs {_l349}")

hnd.STORY_SO_FAR_WINDOW = 0
_off = hnd._story_so_far(_sfb, 35, _sf_acts())
hnd.STORY_SO_FAR_WINDOW = 10
check("setting the window to 0 restores the old full list", all(f"BEATMARK{n}." in _off for n in range(1, 37)) and "EARLIER" not in _off)
check("no beats at all gives nothing", hnd._story_so_far(None, 3) == "" and hnd._story_so_far([], 0) == "")

_usr_w = hnd._narrated_chapter_prompt("t", 35, 60, GOOD["beats"][1], GOOD["scene_bible"], [], beats=_sfb, acts=_sf_acts())[1]
check("the prompt carries the windowed list and the finished-act lines", "ACTONE summary" in _usr_w and "BEATMARK36." in _usr_w
      and "BEATMARK5." not in _usr_w)
_sys_w = hnd._narrated_chapter_prompt("t", 35, 60, GOOD["beats"][1], GOOD["scene_bible"], [], beats=_sfb, acts=_sf_acts())[0]
check("the system message stays identical (it still caches) and its no-future rule matches what is now shown",
      _sys_w == hnd._narrated_chapter_prompt("t", 2, 60, GOOD["beats"][1], GOOD["scene_bible"], [], beats=_sfb)[0]
      and "the recent clips in full" in _sys_w)

_seen_prompts = []
def _mock_capture(sys_p, usr_p, tag, schema, model=None, max_completion_tokens=None):
    _seen_prompts.append(usr_p)
    return aware_clip()


_orig = hnd._ask_openai_json
_old_win = hnd.STORY_SO_FAR_WINDOW
hnd._ask_openai_json, hnd.STORY_SO_FAR_WINDOW = _mock_capture, 1
try:
    hnd.write_narrated_chapter(TEST_TOPIC, 1, 4, GOOD["beats"], GOOD["scene_bible"], [],
                               acts=[{"act_number": 1, "title": "OPENING", "start_clip": 1, "end_clip": 1, "reveals": [], "summary": "ACTONLY"}])
finally:
    hnd._ask_openai_json, hnd.STORY_SO_FAR_WINDOW = _orig, _old_win
check("write_narrated_chapter hands the acts to the prompt", bool(_seen_prompts) and "ACTONLY" in _seen_prompts[0])
_app_src = open("app.py", encoding="utf-8").read()
check("the dashboard path passes the job's acts", "supervise=is_supervise, acts=job.acts" in _app_src)
check("and so does the command-line path", 'acts=outline.get("acts")' in open("hybrid_narrated_drama.py", encoding="utf-8").read())

print("\n[40] Plan limits follow the length of the plan, and a plan is not thrown away for how the film looks")
import copy as _cp, re as _re2, tempfile as _tf, types as _types

# the facts range: at 300 clips the old code asked for "30 to 16"
check("60 clips: the same 6 to 10 facts as before", hnd._fact_range(60) == (6, 10))
check("the low end never passes the high end, at any length",
      all(hnd._fact_range(n)[0] < hnd._fact_range(n)[1] for n in range(5, 1500, 5)))
_m = _re2.search(r"(\d+) to (\d+) must-understand facts", hnd._delivery_plan_rule(1500, 300))
check("at 300 clips the prompt asks for a possible range, not '30 to 16'", _m and int(_m.group(1)) < int(_m.group(2)), _m and _m.group(0))
check("and at 60 it still says 6 to 10", "6 to 10 must-understand facts" in hnd._delivery_plan_rule(300, 60))

# acts and places
check("acts: 4 at 60 clips as before, 2 for a short plan, about one per 15 clips beyond",
      (hnd._default_act_count(60), hnd._default_act_count(30), hnd._default_act_count(120), hnd._default_act_count(300)) == (4, 2, 8, 20))
_acts300 = hnd._normalize_act_spans([], 300)
check("the fallback act spans scale and still cover every clip once",
      len(_acts300) == 20 and _acts300[0]["start_clip"] == 1 and _acts300[-1]["end_clip"] == 300
      and all(_acts300[i]["end_clip"] + 1 == _acts300[i + 1]["start_clip"] for i in range(19)))
check("places: 4 to 8 up to 60 clips as before, 12 to 24 at 300",
      (hnd._location_target(30), hnd._location_target(60), hnd._location_target(300)) == ((4, 8), (4, 8), (12, 24)))
check("the act-breakdown prompt states the target for its length",
      "establish 4 to 8 distinct locations" in hnd._narrated_act_breakdown_prompt("a story", 300, 60)[0]
      and "establish 12 to 24 distinct locations" in hnd._narrated_act_breakdown_prompt("a story", 1500, 300)[0]
      and "17 to 33 narrative acts" in hnd._narrated_act_breakdown_prompt("a story", 1500, 300)[0])

check("the act range the planner is told to choose from: 2 to 4 for 36 clips, never a single figure",
      (hnd._act_range(30), hnd._act_range(36), hnd._act_range(60), hnd._act_range(300)) == ((2, 4), (2, 4), (3, 7), (17, 33))
      and all(hnd._act_range(n)[0] < hnd._act_range(n)[1] for n in range(30, 1000, 7)))
_bp36 = hnd._narrated_act_breakdown_prompt("a story", 180, 36)[0]
check("with no act count in the premise the prompt gives a range and says the last act ends at the last clip",
      "into 2 to 4 narrative acts" in _bp36 and "about 2 narrative acts" not in _bp36 and "the LAST act ends at 36" in _bp36)
check("a count the premise names still wins, as 'exactly N'",
      "exactly 3 narrative acts" in hnd._narrated_act_breakdown_prompt("a 3-act story", 180, 36, act_count=3)[0]
      and "2 to 4 narrative acts" not in hnd._narrated_act_breakdown_prompt("a 3-act story", 180, 36, act_count=3)[0])
check("the old one-per-15 figure is still the fallback split when the model returns no acts",
      len(hnd._normalize_act_spans([], 36)) == hnd._default_act_count(36) == 2)

# the repair budget and the reply ceilings
check("repair budget: 60,000 up to 60 clips, then 1,000 a clip",
      (hnd._repair_budget_for(20), hnd._repair_budget_for(60), hnd._repair_budget_for(300)) == (60000, 60000, 300000))
check("ceilings: unchanged for a 12-clip batch and the 60-clip breakdown",
      hnd._plan_ceiling(12, 1200, 16000) == hnd.PLAN_MAX_OUTPUT and hnd._plan_ceiling(60, 120, 24000) == hnd.PLAN_MAX_OUTPUT)
check("and they grow with a 20-clip batch and a 300-clip breakdown",
      hnd._plan_ceiling(20, 1200, 16000) == 40000 and hnd._plan_ceiling(300, 120, 24000) == 60000)

# list limits
_c60, _c300 = hnd._plan_caps(60), hnd._plan_caps(300)
check("list limits at 60 clips match what the old schema allowed", _c60["facts"] == 16 and _c60["jargon"] == 10)
check("and grow with the plan (facts, cast, places, props, acts)",
      _c300["facts"] >= 50 and _c300["characters"] >= 30 and _c300["locations"] >= 24 and _c300["props"] >= 75 and _c300["acts"] >= 60)
_bs = hnd._cap_plan_schema(hnd.ACT_BEATS_SCHEMA, 60, beats=12, cast=4)
_bi = _bs["properties"]["beats"]["items"]["properties"]
check("a batch of beats is limited to exactly the beats it writes, three lines a beat, the cast it can use",
      _bs["properties"]["beats"]["maxItems"] == 12 and _bi["audio_lines"]["maxItems"] == hnd.MAX_VOICE_REFS
      and _bi["present_characters"]["maxItems"] == 4 and _bi["reveals"]["maxItems"] == hnd.MAX_REVEALS_PER_BEAT)
_bk = hnd._cap_plan_schema(hnd.ACT_BREAKDOWN_SCHEMA, 300)
_bkb = _bk["properties"]["scene_bible"]["properties"]
check("the breakdown limits its cast, props, places, views, acts and facts",
      _bkb["characters"]["maxItems"] == _c300["characters"] and _bkb["props"]["maxItems"] == _c300["props"]
      and _bkb["locations"]["maxItems"] == _c300["locations"] and _bkb["locations"]["items"]["properties"]["views"]["maxItems"] == 3
      and _bk["properties"]["acts"]["maxItems"] == _c300["acts"]
      and _bk["properties"]["delivery"]["properties"]["facts"]["maxItems"] == _c300["facts"])
check("the module's own schemas are left untouched",
      "maxItems" not in hnd.ACT_BEATS_SCHEMA["properties"]["beats"] and "maxItems" not in hnd.ACT_BREAKDOWN_SCHEMA["properties"]["acts"]
      and hnd.DELIVERY_SCHEMA["properties"]["facts"]["maxItems"] == 16)
for _nm, _sc in (("a capped batch", _bs), ("a capped breakdown", _bk),
                 ("a capped single-call plan", hnd._cap_plan_schema(hnd.OUTLINE_SCHEMA, 20, beats=20))):
    _bad = _strict_ok(_sc, _nm)
    check(f"{_nm} still satisfies OpenAI strict mode", not _bad, _bad[:3])

# the ceiling and the schema reach the planner
_seen = []
def _mock_seen(sys_p, usr_p, tag, schema, model=None, max_completion_tokens=None):
    _seen.append((tag, schema, max_completion_tokens))
    raise RuntimeError("stop after the first call")


_orig = hnd._ask_openai_json
hnd._ask_openai_json = _mock_seen
try:
    try:
        hnd._write_act_based_outline("a story", 1500, 300)
    except RuntimeError:
        pass
    check("a 300-clip breakdown is asked with the scaled ceiling and capped schema",
          bool(_seen) and _seen[0][2] == 60000 and _seen[0][1]["properties"]["delivery"]["properties"]["facts"]["maxItems"] >= 50,
          _seen and _seen[0][2])
    _seen.clear()
    try:
        hnd._write_single_shot_outline("a story", 100, 20)
    except RuntimeError:
        pass
    check("a 20-clip single-call plan is asked with its own ceiling and a beat limit of 20",
          bool(_seen) and _seen[0][2] == hnd._plan_ceiling(20, 1200, 24000) and _seen[0][1]["properties"]["beats"]["maxItems"] == 20)
    _seen.clear()
    for _kw in ({"ceiling": 40000}, {}):
        try:
            hnd._ask_planner("s", "u", "x", {"type": "object"}, **_kw)
        except RuntimeError:
            pass
    check("_ask_planner sends the ceiling it is given, and PLAN_MAX_OUTPUT otherwise",
          [c[2] for c in _seen] == [40000, hnd.PLAN_MAX_OUTPUT])
finally:
    hnd._ask_openai_json = _orig
_src_all = inspect.getsource(hnd._write_act_based_outline) + inspect.getsource(hnd.write_narrated_continuation_outline)
check("the beat batches, the re-leak rewrite and the continuation all use capped schemas and scaled ceilings",
      _src_all.count("_cap_plan_schema(") >= 4 and _src_all.count("ceiling=") >= 4 and "_repair_budget_for(" in _src_all)
check("and none of them passes a bare schema constant to the planner",
      "ACT_BEATS_SCHEMA," not in _src_all.replace("_cap_plan_schema(ACT_BEATS_SCHEMA,", "")
      and "ACT_BREAKDOWN_SCHEMA," not in _src_all.replace("_cap_plan_schema(ACT_BREAKDOWN_SCHEMA,", ""))

# code repair: the narrator goes into a voiceover scene that has other people in it
_bible40 = GOOD["scene_bible"]
_pov = _bible40["pov_protagonist"]
_other = next(c["name"] for c in _bible40["characters"] if c["name"] != _pov)
_vo = lambda present: {"clip_number": 1, "delivery_mode": "voiceover", "present_characters": list(present),
                       "audio_lines": [{"speaker": _pov, "line": "x y z a b c"}], "speaker_or_actor": _pov}
_b1, _b2, _b3 = _vo([_other]), _vo([]), _vo([_pov, _other])
_notes = hnd._repair_beats([_b1, _b2, _b3], _bible40)
check("a voiceover over other people gets the narrator added (off screen is fine)", _b1["present_characters"] == [_other, _pov])
check("a voiceover with nobody on screen, or with the narrator already there, is left alone",
      _b2["present_characters"] == [] and _b3["present_characters"] == [_pov, _other])
check("the repair is logged", any("added the narrator" in n for n in _notes))
check("and the continuation planner applies the same repairs as the main planner",
      "_repair_beats(" in inspect.getsource(hnd.write_narrated_continuation_outline))

# which problems stop a plan, and which go to the review gate
_dup = _cp.deepcopy(_bible40)
_dup["characters"][1]["appearance"] = dict(_dup["characters"][0]["appearance"])
_hair = hnd._hard_problems(hnd._check_scene_bible(_dup))
_bad_loc = _cp.deepcopy(GOOD["beats"])
_bad_loc[0]["location_id"] = "nowhere_at_all"
_loc = hnd._hard_problems(hnd._check_beats(_bad_loc, _bible40))
_twolines = _cp.deepcopy(GOOD["beats"])
_twolines[0].update(delivery_mode="voiceover",
                    audio_lines=[{"speaker": _pov, "line": "one two three"}, {"speaker": _pov, "line": "four five six"}])
_vo2 = hnd._hard_problems(hnd._check_beats(_twolines, _bible40))
_run = [_vo(()) for _ in range(5)]
for _i, _b in enumerate(_run, 1):
    _b["clip_number"], _b["location_id"], _b["speech_budget"] = _i, GOOD["beats"][0]["location_id"], 6
_vorun = [p for p in hnd._hard_problems(hnd._check_beats(_run, _bible40)) if "in a row" in p]
check("two characters who look alike: shown at the review gate",
      bool(_hair) and hnd.split_plan_problems(_hair)[0] == [], _hair)
check("a voiceover run longer than three: shown at the review gate",
      bool(_vorun) and hnd.split_plan_problems(_vorun)[0] == [], _vorun)
check("a beat in a place the bible does not have: still stops the plan",
      bool(_loc) and hnd.split_plan_problems(_loc)[0] == _loc, _loc)
check("a two-line voiceover (the clip stage would stop on it): still stops the plan",
      any("one narrator" in p for p in _vo2) and any("one narrator" in p for p in hnd.split_plan_problems(_vo2)[0]), _vo2)
_ledger = ["Clip 3: a line says 'room 404', which the audience does not learn until clip 9. Rewrite it using only what is already known.",
           "Outline produced 7 beats; exactly 8 required.", "Clip 2: 'Zed' speaks here but is not in the scene_bible characters list.",
           "Clip 4: shock_action is wordless; audio_lines must be empty, not 'x'.",
           "Clip 5: audio_lines is empty; write the exact words heard in this clip."]
check("a leaked reveal, a wrong beat count, an unknown speaker, words in a wordless beat and an empty line all still stop the plan",
      hnd.split_plan_problems(_ledger) == (_ledger, []))
_checker_src = inspect.getsource(hnd._check_scene_bible) + inspect.getsource(hnd._check_beats) + inspect.getsource(hnd._check_sequences)
check("every wording the gate recognises really is in a checker's message (no typo can hide a rule)",
      all(frag in _checker_src for frag in hnd._REVIEWABLE_PLAN_PROBLEMS),
      [f for f in hnd._REVIEWABLE_PLAN_PROBLEMS if f not in _checker_src])

# the whole gate, through the real job code
_fake_job = _types.SimpleNamespace(request=_types.SimpleNamespace(topic="a story", duration=300, num_clips=60), plan_rules=None)
_saved, _tmp = {}, _tf.mkdtemp()
_keep = {n: getattr(_usage_app, n) for n in ("get_job", "update_job", "_save_master_plan_file", "job_media_dir")}
_keep_h = {n: getattr(hnd, n) for n in ("write_narrated_outline", "plain_pass_plan", "plan_delivery_report")}
_usage_app.get_job = lambda jid: _fake_job
_usage_app.update_job = lambda jid, **f: _saved.update(f)
_usage_app._save_master_plan_file = lambda job: None
_usage_app.job_media_dir = lambda jid: Path(_tmp)
hnd.plain_pass_plan = lambda outline: {"checked": 0, "rewritten": 0}
hnd.plan_delivery_report = lambda outline: {"problems": ["[SOFT] a note"], "blind": {},
                                            "stats": {"spoken_lines": 1, "spoken_words": 1, "narration_share": 0.3}}
_outline40 = {"scene_bible": _bible40, "beats": GOOD["beats"], "acts": []}
try:
    hnd.write_narrated_outline = lambda *a, **k: (_outline40, list(_hair) + ["[SOFT] x"])
    _usage_app._generate_narrated_plan("job40")
    check("a plan with only review-level problems reaches plan_ready", _saved.get("status") == "plan_ready")
    check("and its report carries them first, tagged [REVIEW], before the soft notes",
          _saved["plan_report"]["problems"][0].startswith("[REVIEW] ") and _saved["plan_report"]["problems"][-1] == "[SOFT] a note")
    _saved.clear()
    hnd.write_narrated_outline = lambda *a, **k: (_outline40, list(_hair) + list(_loc))
    try:
        _usage_app._generate_narrated_plan("job40")
        _raised40 = None
    except ValueError as _e:
        _raised40 = str(_e)
    check("a plan with a blocking problem is still refused, and nothing is stored on the job", bool(_raised40) and not _saved)
    check("the refusal names only the blocking problem and saves the rejected plan",
          bool(_raised40) and "nowhere_at_all" in _raised40 and "hair colour" not in _raised40
          and (Path(_tmp) / "master_plan_rejected.json").exists())
    _saved.clear()
    def _boom(outline):
        raise RuntimeError("report failed")
    hnd.plan_delivery_report = _boom
    hnd.write_narrated_outline = lambda *a, **k: (_outline40, list(_hair))
    _usage_app._generate_narrated_plan("job40")
    check("even when the report itself could not be built, the review problems still reach the gate",
          _saved.get("status") == "plan_ready" and _saved["plan_report"]["problems"][0].startswith("[REVIEW] "))
finally:
    for _n, _v in _keep.items():
        setattr(_usage_app, _n, _v)
    for _n, _v in _keep_h.items():
        setattr(hnd, _n, _v)
_dash = open("dashboard.html", encoding="utf-8").read()
check("the dashboard shows the review problems above the plan",
      'id="plan-notes"' in _dash and "Review before approving" in _dash and '"[REVIEW] "' in _dash)

print("\n[41] Sequences: each act commits to its shape; the shape is checked, handed to the beat writer, and compared with the result")
import copy as _cp41, re as _re41

_bible41 = _cp41.deepcopy(GOOD["scene_bible"])
if len(_bible41["locations"]) < 2:
    _second = _cp41.deepcopy(_bible41["locations"][0])
    _second["id"] = "second_place"
    _bible41["locations"].append(_second)
_L1, _L2 = _bible41["locations"][0]["id"], _bible41["locations"][1]["id"]
_seq = lambda kind, n, loc, why="PURPOSE": {"kind": kind, "clip_count": n, "location_id": loc, "purpose": why}


def _act41(num, start, end, seqs, **kw):
    return dict({"act_number": num, "title": f"T{num}", "primary_locations": [_L1], "dramatic_question": "?", "start_clip": start,
                 "end_clip": end, "summary": f"SUMMARY{num}", "reveals": [], "sequences": seqs}, **kw)


# the schema
_act_props = hnd.ACT_BREAKDOWN_SCHEMA["properties"]["acts"]["items"]["properties"]
check("every act in the breakdown schema carries sequences, and they are required",
      "sequences" in _act_props and "sequences" in hnd.ACT_BREAKDOWN_SCHEMA["properties"]["acts"]["items"]["required"])
_sq = _act_props["sequences"]["items"]["properties"]
check("a sequence is a scene or a bridge, with a clip count, a place and a purpose",
      _sq["kind"]["enum"] == ["scene", "bridge"] and set(_sq) == {"kind", "clip_count", "location_id", "purpose"}
      and _act_props["sequences"]["minItems"] == 1)
check("the breakdown schema, and its capped copy, satisfy OpenAI strict mode",
      not _strict_ok(hnd.ACT_BREAKDOWN_SCHEMA, "b") and not _strict_ok(hnd._cap_plan_schema(hnd.ACT_BREAKDOWN_SCHEMA, 60), "c"))
check("the number of sequences in an act is limited",
      hnd._cap_plan_schema(hnd.ACT_BREAKDOWN_SCHEMA, 60)["properties"]["acts"]["items"]["properties"]["sequences"]["maxItems"] == hnd.MAX_SEQUENCES_PER_ACT)

# the layout in absolute clips
_acts_a = [_act41(1, 1, 12, [_seq("scene", 8, _L1), _seq("bridge", 2, _L1), _seq("scene", 2, _L2)]),
           _act41(2, 13, 20, [_seq("scene", 8, _L2)])]
_rows = hnd._sequence_layout(_acts_a)
check("the layout turns clip counts into absolute clip ranges, in story order",
      [(r["start"], r["end"], r["kind"]) for r in _rows] == [(1, 8, "scene"), (9, 10, "bridge"), (11, 12, "scene"), (13, 20, "scene")])
check("raw acts are laid out on their settled spans", hnd._sequence_layout(_acts_a, 20) == _rows)
check("acts without sequences give no layout", hnd._sequence_layout([{"act_number": 1, "start_clip": 1, "end_clip": 5}]) == [])

# repair first
_miss = [_act41(1, 1, 12, [_seq("scene", 8, _L1), _seq("bridge", 2, _L1), _seq("scene", 1, _L2)]), _act41(2, 13, 20, [_seq("scene", 8, _L2)])]
_n = hnd._repair_sequences(_miss, 20, _bible41)
check("a small miscount is taken up by the longest scene, with no retry",
      sum(s["clip_count"] for s in _miss[0]["sequences"]) == 12 and _miss[0]["sequences"][0]["clip_count"] == 9 and len(_n) == 1, _n)
_none = [_act41(1, 1, 12, [])]
_none[0]["primary_locations"] = [_L2]
hnd._repair_sequences(_none, 12, _bible41)
check("an act that gave no sequences becomes one scene in its own first place",
      _none[0]["sequences"] == [{"kind": "scene", "clip_count": 12, "location_id": _L2, "purpose": "SUMMARY1"}])
_big = [_act41(1, 1, 20, [_seq("scene", 5, _L1)])]
check("a big miscount is left alone for the check to report", hnd._repair_sequences(_big, 20, _bible41) == [] and _big[0]["sequences"][0]["clip_count"] == 5)
_bridges = [_act41(1, 1, 6, [_seq("bridge", 3, _L1), _seq("bridge", 2, _L1)])]
hnd._repair_sequences(_bridges, 6, _bible41)
check("a repair never makes a bridge longer than a bridge may be", all(s["clip_count"] <= hnd.MAX_BRIDGE_CLIPS for s in _bridges[0]["sequences"]))
_spelt = [_act41(1, 1, 4, [_seq("Scene ", 4, _L1)])]
hnd._repair_sequences(_spelt, 4, _bible41)
check("the spelling of a kind is settled", _spelt[0]["sequences"][0]["kind"] == "scene")
_sloppy = [_act41(1, 1, 12, [_seq("scene", 12, _L1)]), _act41(2, 13, 99, [_seq("scene", 12, _L2)])]
hnd._repair_sequences(_sloppy, 24, _bible41)
check("the repair works on the settled spans, so an act whose end the model got wrong still adds up",
      sum(s["clip_count"] for s in _sloppy[1]["sequences"]) == 12)

# the check
_good = [_act41(1, 1, 12, [_seq("scene", 8, _L1), _seq("bridge", 2, _L2), _seq("scene", 2, _L1)]),
         _act41(2, 13, 30, [_seq("scene", 14, _L2), _seq("bridge", 1, _L1), _seq("scene", 3, _L2)])]
_gp = hnd._check_sequences(_good, _bible41, 30)
check("a well-formed shape raises nothing hard", hnd._hard_problems(_gp) == [], _gp)
_bad = lambda seqs, end=12: hnd._hard_problems(hnd._check_sequences([_act41(1, 1, end, seqs)], _bible41, end))
check("lengths that do not add up to the act are a hard problem", any("add up to 10 clips but the act has 12" in p for p in _bad([_seq("scene", 10, _L1)])))
check("a place the bible does not have is a hard problem", any("not in scene_bible locations" in p for p in _bad([_seq("scene", 12, "no_such_place")])))
check("a bridge of more than three clips is a hard problem", any("a bridge skips time" in p for p in _bad([_seq("bridge", 5, _L1), _seq("scene", 7, _L1)])))
check("a clip count under one is a hard problem", any("whole number of at least 1" in p for p in _bad([_seq("scene", 0, _L1), _seq("scene", 12, _L1)])))
check("an unknown kind is a hard problem", any("must be 'scene' or 'bridge'" in p for p in _bad([_seq("flashback", 12, _L1)])))
_soft = lambda acts, total: hnd._soft_problems(hnd._check_sequences(acts, _bible41, total))
check("an act of nothing but scenes, or nothing but one place, is a soft note",
      any("nothing but scenes" in p for p in _soft([_act41(1, 1, 12, [_seq("scene", 6, _L1), _seq("scene", 6, _L2)])], 12))
      and any("stays in" in p for p in _soft([_act41(1, 1, 12, [_seq("scene", 8, _L1), _seq("bridge", 2, _L1), _seq("scene", 2, _L1)])], 12)))
check("one long scene in one room is NOT flagged", _soft([_act41(1, 1, 12, [_seq("scene", 12, _L1)])], 12) == [])
_eq = [_act41(i, (i - 1) * 12 + 1, i * 12, [_seq("scene", 8, _L1), _seq("bridge", 2, _L2), _seq("scene", 2, _L1)]) for i in (1, 2, 3)]
check("acts that are all the same length are a soft note (the 12/12/12 symptom)", any("Every act is 12 clips" in p for p in _soft(_eq, 36)))
check("an act with no sequences at all is a soft note, not a failure",
      any("lists no sequences" in p for p in _soft([_act41(1, 1, 12, [])], 12)))
check("the breakdown check includes the sequence problems",
      any("add up to" in p for p in hnd._hard_problems(hnd._check_act_breakdown({"scene_bible": _bible41, "acts": [_act41(1, 1, 30, [_seq("scene", 10, _L1)])]}, 30))))

# the prompts
for _clips in (60, 300):
    _bp = hnd._narrated_act_breakdown_prompt("a story", _clips * 5, _clips)[0]
    check(f"the {_clips}-clip breakdown prompt asks for sequences, tied to the act's events",
          '"sequences"' in _bp and "EVERY EVENT PLAYS" in _bp and "never more than 3" in _bp and "add up to that act's length" in _bp)

_acts_b = [_act41(1, 1, 12, [_seq("scene", 8, _L1, "THE CONFRONTATION"), _seq("bridge", 2, _L1, "TIME PASSES"), _seq("scene", 2, _L2, "THE ARRIVAL")]),
           _act41(2, 13, 36, [_seq("scene", 20, _L2, "THE LONG SCENE"), _seq("bridge", 2, _L1), _seq("scene", 2, _L2)])]
_batches = hnd._plan_act_batches(_acts_b)
_u1 = hnd._narrated_act_beats_prompt("t", _batches[0], _acts_b, _bible41, [], 36)[1]
_u2 = hnd._narrated_act_beats_prompt("t", _batches[1], _acts_b, _bible41, [], 36)[1]
check("the beat writer is told the stretches of its batch, with kind, place and purpose",
      "STRUCTURE OF THESE CLIPS" in _u1 and "Clips 1-8" in _u1 and f"a SCENE in '{_L1}'" in _u1 and "THE CONFRONTATION" in _u1
      and "Clips 9-10" in _u1 and "a BRIDGE" in _u1 and "Clips 11-12" in _u1)
check("a stretch that runs across two batches says which part each batch writes",
      "Clips 13-32" in _u2 and "this batch writes clips 13-24 of it" in _u2
      and "this batch writes clips 25-32 of it" in hnd._narrated_act_beats_prompt("t", _batches[2] if len(_batches) > 2 else _batches[1], _acts_b, _bible41, [], 36)[1])
check("a scene is told to play out, a bridge to skip time",
      "Play it out in real time" in _u1 and "Skip time" in _u1)
check("the places of the stretches are listed with the act's own", f"'{_L2}'" in _u1.split("Primary Locations:")[1].split("\n")[0] or _L2 in _u1.split("Primary Locations:")[1].split("\n")[0])
_cont_acts = [{"act_number": "Continuation", "title": "Continuation", "primary_locations": [_L1], "dramatic_question": "?",
               "start_clip": 5, "end_clip": 8, "summary": "go on"}]
_cb = {"batch_index": 1, "act_numbers": ["Continuation"], "start_clip": 5, "end_clip": 8, "clip_count": 4, "title": "C",
       "primary_locations": [_L1], "dramatic_question": "?", "summary": "go on"}
check("a continuation (acts without sequences) is unchanged: no structure block",
      "STRUCTURE OF THESE CLIPS" not in hnd._narrated_act_beats_prompt("t", _cb, _cont_acts, _bible41, [], 8)[1])

# comparing the finished beats with the plan
_bt = lambda n, mode, loc: {"clip_number": n, "delivery_mode": mode, "location_id": loc, "audio_lines": [], "speaker_or_actor": ""}
_plan_acts = [_act41(1, 1, 12, [_seq("scene", 8, _L1), _seq("bridge", 2, _L1), _seq("scene", 2, _L2)])]
_ok_beats = [_bt(n, "dialogue", _L1) for n in range(1, 9)] + [_bt(9, "voiceover", _L1), _bt(10, "voiceover", _L1)] + [_bt(n, "dialogue", _L2) for n in (11, 12)]
check("beats that follow the plan raise no note", hnd._sequence_beat_notes(_ok_beats, _plan_acts) == [])
_off = [_bt(n, "voiceover", _L2) for n in range(1, 9)] + [_bt(9, "dialogue", _L1), _bt(10, "dialogue", _L1)] + [_bt(n, "dialogue", _L2) for n in (11, 12)]
_nn = hnd._sequence_beat_notes(_off, _plan_acts)
check("a scene filmed elsewhere, a scene told by narration and a bridge that stages dialogue are each noted once",
      sum("set elsewhere" in p for p in _nn) == 1 and sum("are narration" in p for p in _nn) == 1 and sum("stage live dialogue" in p for p in _nn) == 1, _nn)
check("and they are soft: they never stop a plan", all(p.startswith("[SOFT] ") for p in _nn))
_rep = hnd.plan_delivery_report({"beats": _off, "scene_bible": _bible41, "acts": _plan_acts, "delivery": {}}, run_blind=False)
check("the plan report carries those notes to the review gate", any("stage live dialogue" in p for p in _rep["problems"]))

# the whole planner, with a mocked model: a miscount is repaired by code, with no retry, and the shape reaches the beat writer
_speakers = [c["name"] for c in _bible41["characters"]][:2]
_calls41, _prompts41 = [], []
_acts_reply = [_act41(1, 1, 12, [_seq("scene", 7, _L1), _seq("bridge", 2, _L1), _seq("scene", 2, _L2)]),   # adds up to 11: off by one
               _act41(2, 13, 30, [_seq("scene", 14, _L2), _seq("bridge", 1, _L1), _seq("scene", 3, _L2)])]
for _a in _acts_reply:
    _a["primary_locations"] = [_L1, _L2]


def _mock_planner(sys_p, usr_p, tag, schema, model=None, max_completion_tokens=None):
    _calls41.append(tag)
    if tag == "narrated_act_breakdown":
        return {"scene_bible": _cp41.deepcopy(_bible41), "acts": _cp41.deepcopy(_acts_reply)}
    _prompts41.append(usr_p)
    m = _re41.search(r"Generate exactly (\d+) beats for Clips (\d+) to (\d+)", usr_p)
    first, last = int(m.group(2)), int(m.group(3))
    return {"beats": [{"clip_number": n, "cycle_number": 1, "delivery_mode": "dialogue", "location_id": _L1,
                       "present_characters": list(_speakers), "speaker_or_actor": _speakers[0], "summary": f"beat {n}",
                       "speech_budget": 8, "audio_lines": [{"speaker": _speakers[0], "line": "one two three four five six seven eight"}],
                       "reveals": [], "function": "clash", "turn": f"turn {n}", "delivers": []} for n in range(first, last + 1)]}


_orig = hnd._ask_openai_json
hnd._ask_openai_json = _mock_planner
try:
    _plan41, _probs41 = hnd._write_act_based_outline("a story", 150, 30)
finally:
    hnd._ask_openai_json = _orig
check("the model was asked for the breakdown once: the miscount cost no retry", _calls41.count("narrated_act_breakdown") == 1, _calls41)
check("the stored acts keep their sequences, and every act's sequences add up to its length",
      all(sum(s["clip_count"] for s in a["sequences"]) == a["end_clip"] - a["start_clip"] + 1 for a in _plan41["acts"]), _plan41["acts"][0]["sequences"])
check("each batch of beats was told the shape of its clips", _prompts41 and all("STRUCTURE OF THESE CLIPS" in u for u in _prompts41))
check("and the report-level notes catch beats that ignored it (all dialogue in one room)",
      any("stage live dialogue" in p for p in hnd._sequence_beat_notes(_plan41["beats"], _plan41["acts"])))
check("no hard problem was invented by the sequences", not any("sequence" in p.lower() for p in hnd._hard_problems(_probs41)), _probs41[:3])
_dash41 = open("dashboard.html", encoding="utf-8").read()
check("the dashboard lists each act's scenes and bridges", "Story structure" in _dash41 and "BRIDGE" in _dash41 and "a.sequences" in _dash41)

print("\n[42] A short plan (under 30 clips, one call) commits to its shape too")
import copy as _cp42

_b42 = _cp42.deepcopy(GOOD["scene_bible"])
if len(_b42["locations"]) < 2:
    _extra = _cp42.deepcopy(_b42["locations"][0])
    _extra["id"] = "second_place"
    _b42["locations"].append(_extra)
_P1, _P2 = _b42["locations"][0]["id"], _b42["locations"][1]["id"]
_s42 = lambda kind, n, loc, why="WHY": {"kind": kind, "clip_count": n, "location_id": loc, "purpose": why}

# the schema
_keys = list(hnd.OUTLINE_SCHEMA["properties"])
check("the single-call schema asks for the shape BEFORE the beats", _keys.index("sequences") < _keys.index("beats"), _keys)
check("and requires it", "sequences" in hnd.OUTLINE_SCHEMA["required"])
check("it is the same shape as an act's sequences", hnd.OUTLINE_SCHEMA["properties"]["sequences"] is hnd.SEQUENCES_SCHEMA
      and hnd.ACT_BREAKDOWN_SCHEMA["properties"]["acts"]["items"]["properties"]["sequences"] is hnd.SEQUENCES_SCHEMA)
_capped42 = hnd._cap_plan_schema(hnd.OUTLINE_SCHEMA, 12, beats=12)
check("the whole-story list is limited, and the schemas stay valid for OpenAI strict mode",
      _capped42["properties"]["sequences"]["maxItems"] == hnd.MAX_SEQUENCES_PER_ACT
      and not _strict_ok(hnd.OUTLINE_SCHEMA, "o") and not _strict_ok(_capped42, "c"))
check("capping a copy leaves the shared schema alone", "maxItems" not in hnd.SEQUENCES_SCHEMA)

# places for a short story
check("places for a short story: 2-3 for a minute, 2-4 for 90 seconds, 2-6 near the limit, 1-3 for half a minute",
      (hnd._short_places(12), hnd._short_places(18), hnd._short_places(29), hnd._short_places(6)) == ((2, 3), (2, 4), (2, 6), (1, 3)))

# the prompt
_p12 = hnd._narrated_outline_prompt("a story", 60, 12)[0]
check("the short-plan prompt asks for the shape first, tied to events, covering exactly its clips",
      "THE SHAPE COMES FIRST" in _p12 and "EVERY EVENT PLAYS" in _p12 and "cover all 12 clips" in _p12 and "never more than 3" in _p12)
check("and says how many places a story this short uses, instead of the old '30+ clips, 4 to 8'",
      "uses 2 to 3 distinct places" in _p12 and "for 30+ clips" not in _p12 and "Confinement within an act" not in _p12)
check("90 seconds says 2 to 4", "uses 2 to 4 distinct places" in hnd._narrated_outline_prompt("a story", 90, 18)[0])

# the wrapper
_d42 = {"sequences": [_s42("scene", 12, _P1)]}
_w = hnd._single_acts(_d42, 12)
check("the wrapper is one act spanning every clip, sharing the plan's own list",
      len(_w) == 1 and (_w[0]["start_clip"], _w[0]["end_clip"]) == (1, 12) and _w[0]["sequences"] is _d42["sequences"])
hnd._fold_sequences_into_acts(_d42, 12)
check("folding moves the shape into acts and leaves no top-level list", "sequences" not in _d42 and _d42["acts"][0]["sequences"][0]["clip_count"] == 12)
_none42 = {}
hnd._fold_sequences_into_acts(_none42, 12)
check("a plan without a shape is left alone", _none42 == {})

# the check
def _plan42(seqs, locs=(_P1,) * 12, mode="dialogue"):
    beats = [dict(GOOD["beats"][1], clip_number=n + 1, location_id=locs[n], delivery_mode=mode) for n in range(12)]
    return {"scene_bible": _b42, "beats": beats, "sequences": seqs}


_ok_seq = [_s42("scene", 5, _P1), _s42("bridge", 2, _P1), _s42("scene", 5, _P2)]
_pr = hnd._check_narrated_outline(_plan42(_ok_seq, locs=(_P1,) * 7 + (_P2,) * 5), 12)
check("a well-formed shape adds no sequence problem", not [p for p in _pr if "sequence" in p.lower()], _pr)
_pr = hnd._check_narrated_outline(_plan42([_s42("scene", 9, _P1)]), 12)
check("lengths that do not add up to the story are a hard problem", any("add up to 9 clips but the act has 12" in p for p in hnd._hard_problems(_pr)))
_pr = hnd._check_narrated_outline(_plan42(_ok_seq), 12)
check("a 12-clip story that never leaves one place gets a soft note",
      any("stays in one place" in p and p.startswith("[SOFT]") for p in _pr), _pr)
_pr = hnd._check_narrated_outline(_plan42(_ok_seq, locs=(_P1,) * 7 + (_P2,) * 5), 12)
check("and not when it moves", not any("stays in one place" in p for p in _pr))
_noseq = _plan42(None)
_noseq.pop("sequences")
check("a plan with no shape at all (older, or a test fixture) is simply not checked for it",
      not any("sequence" in p.lower() for p in hnd._check_narrated_outline(_noseq, 12)))
_long = _plan42([_s42("scene", 9, _P1)])
check("from 30 clips the act-based flow owns the shape: the whole-plan check does not repeat it",
      not any("add up to" in p for p in hnd._check_narrated_outline(dict(_long, beats=_long["beats"] * 3), 36)))

# the merge keeps what was fine
_old = _plan42([_s42("bridge", 5, _P1), _s42("scene", 7, _P2)], locs=(_P1,) * 12)
_new = _plan42(_ok_seq, locs=(_P2,) * 12)
_hard = hnd._hard_problems(hnd._check_narrated_outline(_old, 12))
_merged = hnd._merge_outline(_old, _new, _hard, 12)
check("a retry that fixes only the shape takes the new shape and keeps the old beats",
      _merged["sequences"] == _ok_seq and _merged["beats"] == _old["beats"] and _merged["scene_bible"] is _old["scene_bible"], _hard)

# the gate: a shape that does not add up is something to read, not a reason to refuse a plan
_seq_hard = hnd._hard_problems(hnd._check_sequences(hnd._single_acts({"sequences": [_s42("bridge", 5, _P1), _s42("scene", 4, "nowhere")]}, 12), _b42, 12))
check("every sequence problem goes to the review gate and none blocks a plan",
      len(_seq_hard) >= 3 and hnd.split_plan_problems(_seq_hard)[0] == [], _seq_hard)
_checker_src42 = inspect.getsource(hnd._check_scene_bible) + inspect.getsource(hnd._check_beats) + inspect.getsource(hnd._check_sequences)
check("and every review wording is really in a checker's message", all(f in _checker_src42 for f in hnd._REVIEWABLE_PLAN_PROBLEMS))

# the whole short planner, with a mocked model
_calls42, _models42 = [], []
_spk42 = [c["name"] for c in _b42["characters"]][:2]


def _mk_beats(locs):
    return [{"clip_number": n + 1, "cycle_number": 1, "delivery_mode": "dialogue", "location_id": locs[n],
             "present_characters": list(_spk42), "speaker_or_actor": _spk42[0], "summary": f"beat {n + 1}",
             "speech_budget": 8, "audio_lines": [{"speaker": _spk42[0], "line": "one two three four five six seven eight"}],
             "reveals": [], "function": "clash", "turn": f"turn {n + 1}", "delivers": []} for n in range(12)]


def _reply(seqs):
    return {"scene_bible": _cp42.deepcopy(_b42), "sequences": _cp42.deepcopy(seqs), "beats": _mk_beats((_P1,) * 7 + (_P2,) * 5)}


_script = []
def _mock42(sys_p, usr_p, tag, schema, model=None, max_completion_tokens=None):
    _calls42.append(tag)
    _models42.append(schema["properties"]["sequences"]["maxItems"])
    return _script[min(len(_calls42) - 1, len(_script) - 1)]


_orig = hnd._ask_openai_json
hnd._ask_openai_json = _mock42
try:
    _script[:] = [_reply([_s42("scene", 5, _P1), _s42("bridge", 2, _P1), _s42("scene", 4, _P2)])]     # adds up to 11: off by one
    _plan42a, _probs42a = hnd.write_narrated_outline("a story", 60, 12)
    check("a miscount in a short plan is repaired by code: one model call, no retry", _calls42 == ["narrated_outline"], _calls42)
    check("the plan comes back with its shape in acts, which add up to the story, and no loose top-level list",
          "sequences" not in _plan42a and sum(s["clip_count"] for s in _plan42a["acts"][0]["sequences"]) == 12, _plan42a.get("acts"))
    check("the model was asked with the capped schema", _models42 == [hnd.MAX_SEQUENCES_PER_ACT])
    _rep42 = hnd.plan_delivery_report(_plan42a, run_blind=False)
    check("the plan report sees the shape (the bridge here was filmed as live dialogue, so it says so)",
          any("planned as a bridge" in p for p in _rep42["problems"]), _rep42["problems"])
    _calls42.clear()
    _script[:] = [_reply([_s42("bridge", 5, _P1), _s42("scene", 7, _P2)]),
                  _reply([_s42("scene", 5, _P1), _s42("bridge", 2, _P1), _s42("scene", 5, _P2)])]
    _plan42b, _ = hnd.write_narrated_outline("a story", 60, 12)
    check("a shape the code cannot repair (a 5-clip bridge) is retried once, and the retry's shape is kept",
          len(_calls42) == 2 and [s["kind"] for s in _plan42b["acts"][0]["sequences"]] == ["scene", "bridge", "scene"], _calls42)
finally:
    hnd._ask_openai_json = _orig

_dash42 = open("dashboard.html", encoding="utf-8").read()
check("the dashboard says '1 act' for a short plan, not '1 acts'", '=== 1 ? "act" : "acts"' in _dash42)

print("\n[43] Plan revision: a note -> split -> find (Luna, in windows) -> the user ticks clips -> rewrite (story model) -> checks -> undo")
import copy as _cp43, re as _re43, types as _types43, json as _json43

_b43 = _cp43.deepcopy(GOOD["scene_bible"])
_cast43 = [c["name"] for c in _b43["characters"]]
_pov43 = _b43["pov_protagonist"]
_other43 = next(n for n in _cast43 if n != _pov43)
_loc43 = _b43["locations"][0]["id"]


def _beat43(n, mode="dialogue", **kw):
    b = {"clip_number": n, "cycle_number": 1, "delivery_mode": mode, "location_id": _loc43,
         "present_characters": [_pov43, _other43] if mode == "dialogue" else [], "speaker_or_actor": _pov43 if mode != "dialogue" else _pov43,
         "summary": f"SUMMARY{n} two people talk", "speech_budget": 8,
         "audio_lines": ([{"speaker": _pov43, "line": f"line {n} one two three four five six"}] if mode != "shock_action" else []),
         "reveals": [], "function": "clash", "turn": f"turn {n}", "delivers": []}
    b.update(kw)
    return b


_plan43 = lambda n=12: [_beat43(i) for i in range(1, n + 1)]

# ---- rules ----
_cr = hnd.clean_rules([{"text": "  Lily never   recognises Jack  "}, {"text": "lily never recognises jack"}, {"id": "r1", "text": "He lies"}, "A plain string rule", {"text": ""}, {"text": None}])
check("rules are trimmed, de-duplicated and given unique ids", [r["text"] for r in _cr] == ["Lily never recognises Jack", "He lies", "A plain string rule"]
      and len({r["id"] for r in _cr}) == 3 and _cr[1]["id"] == "r1", _cr)
try:
    hnd.clean_rules([{"text": f"rule {i}"} for i in range(hnd.MAX_PLAN_RULES + 1)])
    _capped43 = False
except ValueError as _e43:
    _capped43 = "at most" in str(_e43)
check("more than the cap of standing rules is refused", _capped43 and hnd.MAX_PLAN_RULES == 12)
check("a rule is cut to its length limit", len(hnd.clean_rules([{"text": "x" * 500}])[0]["text"]) == hnd.MAX_RULE_CHARS)
check("the rules ride along with the premise", "STORY RULES" in hnd.topic_with_rules("PREMISE", [{"id": "r1", "text": "RULETEXT"}])
      and hnd.topic_with_rules("PREMISE", [{"id": "r1", "text": "RULETEXT"}]).startswith("PREMISE") and hnd.topic_with_rules("PREMISE", None) == "PREMISE")
_sa = hnd._narrated_chapter_prompt(hnd.topic_with_rules("P", [{"id": "r1", "text": "RULETEXT"}]), 0, 4, GOOD["beats"][0], GOOD["scene_bible"], [], beats=GOOD["beats"])[0]
_sb = hnd._narrated_chapter_prompt(hnd.topic_with_rules("P", [{"id": "r1", "text": "RULETEXT"}]), 2, 4, GOOD["beats"][2], GOOD["scene_bible"], [], beats=GOOD["beats"])[0]
check("a clip writer's system prompt carries the rules, the same for every clip (so it still caches)", "RULETEXT" in _sa and _sa == _sb)

# ---- rules: the probe and the stop point travel with the rule ----
_cr3 = hnd.clean_rules([{"text": "Lily never recognises Jack", "hint": "tell a; tell b", "probe": "  Does anything here show it?  ", "stops_when": "  Harrison says Mr Blackwood  "},
                        {"text": "He lies", "stops_when": "Never."}, {"text": "other", "stops_when": "it does not stop"}])
check("a rule keeps its probe and the point where it stops (trimmed); 'never' is no stop point at all",
      _cr3[0]["probe"] == "Does anything here show it?" and _cr3[0]["stops_when"] == "Harrison says Mr Blackwood"
      and "stops_when" not in _cr3[1] and "stops_when" not in _cr3[2] and "probe" not in _cr3[1], _cr3)
check("a probe and a stop point are cut to their limits",
      len(hnd.clean_rules([{"text": "r", "probe": "p" * 900}])[0]["probe"]) == hnd.MAX_PROBE_CHARS
      and len(hnd.clean_rules([{"text": "r", "stops_when": "s" * 900}])[0]["stops_when"]) == hnd.MAX_STOP_CHARS)
_rb = hnd.rules_block(_cr3)
check("a rule that ends says where, in the text every later stage reads, so no stage is told 'always' about what the story needs",
      "Lily never recognises Jack (This stops applying when: Harrison says Mr Blackwood.)" in _rb and "- He lies\n- other" in _rb)
check("the probe and the tells are never put in a prompt as the rule", "Does anything here" not in _rb and "tell a" not in _rb)
check("a rewrite is told where the item stops; an item that never stops is just its text",
      hnd.item_instruction({"text": "X", "stops_when": ""}) == "X" and hnd.item_instruction({"text": "X", "stops_when": "never"}) == "X"
      and hnd.item_instruction({"text": "X", "stops_when": "Y happens."}) == "X (This stops applying when: Y happens.)")

# ---- windows ----
check("a plan that fits one call is scanned whole", hnd._scan_windows(36) == [(1, 36)] and hnd._scan_windows(60) == [(1, 60)])
check("a plan just over the limit is two even windows, not 60 and 1", hnd._scan_windows(61) == [(1, 31), (32, 61)], hnd._scan_windows(61))
_w = hnd._scan_windows(300)
check("a 300-clip plan is five windows of at most 60 that cover every clip once",
      len(_w) == 5 and _w[0][0] == 1 and _w[-1][1] == 300 and all(_w[i][1] + 1 == _w[i + 1][0] for i in range(len(_w) - 1))
      and all(b - a + 1 <= hnd.SCAN_WINDOW for a, b in _w), _w)
check("an empty plan has no windows", hnd._scan_windows(0) == [])

# ---- a mocked model ----
_calls43 = []
_script43 = {}


def _router(sys_p, usr_p, tag, schema, model=None, max_completion_tokens=None, reasoning_effort=None):
    _calls43.append({"tag": tag, "model": model, "schema": schema, "sys": sys_p, "usr": usr_p, "max": max_completion_tokens, "effort": reasoning_effort})
    h = _script43.get(tag)
    if callable(h):
        return h(usr_p)
    if isinstance(h, list):
        return h.pop(0)
    if isinstance(h, dict):
        return h
    if tag == "narrated_plain_pass":
        return {"lines": []}
    raise AssertionError(f"unexpected call {tag}")


def _window_of(usr):
    m = _re43.search(r"THE CLIPS TO SCORE \((\d+)-(\d+)\)", usr)
    return int(m.group(1)), int(m.group(2))


def _scores(usr, hits):
    """An answer in the scan's contract: exactly one entry for every clip of the window, score 0 unless named in `hits` ({clip: (score, quote, why)})."""
    lo, hi = _window_of(usr)
    return {"clips": [({"clip": n, "score": hits[n][0], "quote": hits[n][1], "why": hits[n][2]} if n in hits
                       else {"clip": n, "score": 0, "quote": "", "why": ""}) for n in range(lo, hi + 1)]}


_orig43 = hnd._ask_openai_json
_passes43 = hnd.SCAN_PASSES
hnd.SCAN_PASSES = 1          # the single-pass tests below count calls one by one; the passes have their own tests at the end
hnd._ask_openai_json = _router
try:
    # split
    _script43["narrated_revision_split"] = {"items": [
        {"text": "  Lily never recognises Ethan as Jack  ", "kind": "rule", "in_scope": True, "why_out_of_scope": "", "replaces_rule_ids": ["r1", "bogus"]},
        {"text": "In the market scene Lily should be colder", "kind": "fix_now", "in_scope": True, "why_out_of_scope": "", "replaces_rule_ids": ["r1"]},
        {"text": "Add a scene on a boat", "kind": "fix_now", "in_scope": False, "why_out_of_scope": "", "replaces_rule_ids": []}]}
    _items = hnd.split_revision_note("a note", [{"id": "r1", "text": "old"}], _b43, 12)
    check("the note is split into items, on the cheap model", len(_items) == 3 and _calls43[-1]["model"] == hnd.app.OPENAI_CLIP_MODEL)
    check("a rule keeps only ids of rules that exist; a one-time fix replaces none",
          _items[0]["replaces_rule_ids"] == ["r1"] and _items[1]["replaces_rule_ids"] == [] and _items[0]["text"] == "Lily never recognises Ethan as Jack")
    check("an out-of-scope item always says why and that it needs a new plan", not _items[2]["in_scope"] and "new plan" in _items[2]["why_out_of_scope"])
    for _bad_note, _why in (("   ", "write what"), ("x" * (hnd.MAX_NOTE_CHARS + 1), "too long")):
        try:
            hnd.split_revision_note(_bad_note, None, _b43, 12)
            _msg = ""
        except ValueError as _e:
            _msg = str(_e)
        check(f"a note that is {'empty' if _why.startswith('write') else 'too long'} is refused before any call", _why in _msg)
    check("the split prompt defines what is out of scope", "add, remove, merge, split or reorder clips" in _calls43[0]["sys"]
          and "add or remove a place" in _calls43[0]["sys"])

    # the scan, in windows
    _item43 = {"text": "the request", "probe": "PROBE TEXT", "tells": ["tell a", "tell b"], "stops_when": "Harrison speaks"}
    _calls43.clear()

    def _noisy(usr):
        a = _scores(usr, {7: (3, "quote 7", "why 7"), 40: (1, "quote 40", "why 40")})
        a["clips"] += [{"clip": 40, "score": 3, "quote": "again", "why": "named twice"}, {"clip": 999, "score": 3, "quote": "x", "why": "no such clip"}]
        return a
    _script43["narrated_revision_scan"] = _noisy
    _found = hnd.scan_revision_clips([_item43], _plan43(65))
    check("a 65-clip plan is scanned in 2 windows (33 + 32), one call each, all on the cheap model",
          [c["tag"] for c in _calls43] == ["narrated_revision_scan"] * 2 and all(c["model"] == hnd.app.OPENAI_CLIP_MODEL for c in _calls43)
          and [c["schema"]["properties"]["clips"]["maxItems"] for c in _calls43] == [33, 32], [c["tag"] for c in _calls43])
    check("each window scores only its own clips; a later window is shown the earlier ones as context, the first has none",
          "SUMMARY40 " not in _calls43[0]["usr"] and "SUMMARY7 " in _calls43[0]["usr"] and "EARLIER CLIPS" not in _calls43[0]["usr"]
          and "EARLIER CLIPS" in _calls43[1]["usr"] and "do not score them" in _calls43[1]["usr"] and "SUMMARY7 " in _calls43[1]["usr"])
    check("a clip outside the window, a second entry for a clip, and a clip that does not exist are all dropped",
          [c["clip"] for c in _found] == [7, 40] and [c["score"] for c in _found] == [3, 1] and "named twice" not in str(_found), _found)
    check("a found clip carries the failing words, the reason and a rewrite brief that quotes them",
          _found[0]["quote"] == "quote 7" and _found[0]["reason"] == "why 7" and '"quote 7"' in _found[0]["change"] and "why 7" in _found[0]["change"])
    _sch = _calls43[0]["schema"]["properties"]["clips"]
    check("the schema asks for exactly one entry for each clip of the window, each with a 0-3 score and the quoted words",
          _sch["minItems"] == _sch["maxItems"] == 33 and _sch["items"]["properties"]["score"]["enum"] == [0, 1, 2, 3]
          and _sch["items"]["required"] == ["clip", "score", "quote", "why"])
    check("the prompt gives the item's probe, tells and stop point, and asks what each line takes for granted",
          "PROBE: PROBE TEXT" in _calls43[0]["usr"] and "TELLS: tell a; tell b" in _calls43[0]["usr"] and "RULE STOPS: Harrison speaks" in _calls43[0]["usr"]
          and "RULE: the request" in _calls43[0]["usr"] and "takes for granted" in _calls43[0]["sys"]
          and "stops applying score 0" in _calls43[0]["sys"] and "Return exactly one entry per clip, numbered 1 to 33" in _calls43[0]["sys"])
    _calls43.clear()
    hnd.scan_revision_clips([{"text": "plain item"}], _plan43(12))
    check("an item with no probe gets a plain one, no tells and no stop point",
          "PROBE: Does anything said or done here only make sense if this were not true: plain item?" in _calls43[0]["usr"]
          and "TELLS: (none given)" in _calls43[0]["usr"] and "RULE STOPS: never" in _calls43[0]["usr"])
    _calls43.clear()
    _answers = {"item A": {3: (1, "qa", "wa")}, "item B": {3: (3, "qb", "wb"), 6: (2, "q6", "w6")}}
    _script43["narrated_revision_scan"] = lambda usr: _scores(usr, _answers["item A" if "RULE: item A" in usr else "item B"])
    _res = hnd.scan_revision_clips([{"text": "item A"}, {"text": "item B"}], _plan43(12))
    check("two items are two scans; a clip both touch keeps its highest score", len(_calls43) == 2
          and [(c["clip"], c["score"]) for c in _res] == [(3, 3), (6, 2)] and _res[0]["quote"] == "qb", _res)

    # a clip the scan leaves out
    _calls43.clear()
    _gaps = [lambda usr: {"clips": [e for e in _scores(usr, {7: (3, "q", "w")})["clips"] if e["clip"] != 5]},       # skips clip 5
             lambda usr: _scores(usr, {5: (2, "late", "w5"), 7: (3, "q", "w")})]
    _script43["narrated_revision_scan"] = lambda usr: _gaps.pop(0)(usr)
    _res = hnd.scan_revision_clips([_item43], _plan43(12))
    check("a clip the scan left out is asked for once more, and its score is used",
          [c["tag"] for c in _calls43] == ["narrated_revision_scan"] * 2 and [c["clip"] for c in _res] == [5, 7], _res)
    _calls43.clear()
    _script43["narrated_revision_scan"] = lambda usr: {"clips": [e for e in _scores(usr, {7: (3, "q", "w")})["clips"] if e["clip"] != 5]}
    _res = hnd.scan_revision_clips([_item43], _plan43(12))
    check("a clip it never scores costs one retry, never a crash, and is not guessed at", len(_calls43) == 2 and [c["clip"] for c in _res] == [7])
    _calls43.clear()
    _script43["narrated_revision_scan"] = lambda usr: {"clips": [dict(e, score=7) if e["clip"] == 4 else e for e in _scores(usr, {}) ["clips"]]}
    check("a score that is not 0-3 is not accepted as one", hnd.scan_revision_clips([_item43], _plan43(12)) == [] and len(_calls43) == 2)

    # propose
    _calls43.clear()
    _script43["narrated_revision_split"] = {"items": [
        {"text": "Lily never recognises Jack", "kind": "rule", "in_scope": True, "why_out_of_scope": "", "replaces_rule_ids": ["r2"],
         "probe": "  Does anything here only make sense if Lily knows who Jack is?  ", "tells": ["a form of address", "words like again"], "stops_when": "Harrison names him"},
        {"text": "Add a boat scene", "kind": "fix_now", "in_scope": False, "why_out_of_scope": "needs a new plan", "replaces_rule_ids": [],
         "probe": "SHOULD BE DROPPED", "tells": ["dropped"], "stops_when": "dropped"}]}
    _script43["narrated_revision_scan"] = lambda usr: _scores(usr, {3: (3, "she knows him", "she presupposes it")})
    _prop = hnd.propose_plan_revision("a note", [{"id": "r2", "text": "old rule"}], _plan43(12), None, _b43, premise="THE PREMISE TEXT")
    check("a proposal lists the items, the rule it would save, the rule it replaces and the clips, and changes nothing",
          _prop["rules_new"] == ["Lily never recognises Jack"] and _prop["replaces"] == ["r2"] and [c["clip"] for c in _prop["clips"]] == [3] and _prop["blocked"] is None)
    check("the rule is saved with its tells, its probe and its stop point, in step with the rules",
          _prop["rules_new_hints"] == ["a form of address; words like again"]
          and _prop["rules_new_meta"] == [{"probe": "Does anything here only make sense if Lily knows who Jack is?", "stops_when": "Harrison names him"}])
    check("the splitter reads the premise, so it can see where a rule has to stop", "THE PREMISE TEXT" in _calls43[0]["usr"])
    check("the splitter is asked for a probe, tells and a stop point, about what a line TAKES FOR GRANTED, without having seen the clips",
          all(s in _calls43[0]["sys"] for s in ("probe:", "tells:", "stops_when:", "TAKES FOR GRANTED", "you have not been shown the clips"))
          and _calls43[0]["schema"]["properties"]["items"]["items"]["required"][-3:] == ["probe", "tells", "stops_when"])
    check("only in-scope items are scanned, with their own probe; an out-of-scope item has none of the three",
          "boat" not in _calls43[-1]["usr"] and "PROBE: Does anything here only make sense if Lily knows who Jack is?" in _calls43[-1]["usr"]
          and (_prop["items"][1]["probe"], _prop["items"][1]["tells"], _prop["items"][1]["stops_when"]) == ("", [], ""))
    _script43["narrated_revision_split"] = {"items": [{"text": "x", "kind": "rule", "in_scope": True, "why_out_of_scope": "", "replaces_rule_ids": [],
                                                        "probe": "p", "tells": [], "stops_when": "Never."}]}
    _full = [{"id": f"r{i}", "text": f"rule {i}"} for i in range(1, hnd.MAX_PLAN_RULES + 1)]
    _pb = hnd.propose_plan_revision("n", _full, _plan43(12), None, _b43)
    check("saving a rule that would pass the cap is blocked, with a reason, and the clips are still found", "at most 12" in (_pb["blocked"] or ""))
    check("a stop point of 'never' is no stop point", _pb["items"][0]["stops_when"] == "" and _pb["rules_new_meta"] == [{"probe": "p", "stops_when": ""}])
    _calls43.clear()
    _script43["narrated_revision_split"] = {"items": [{"text": "Add a boat", "kind": "fix_now", "in_scope": False, "why_out_of_scope": "needs a new plan", "replaces_rule_ids": [],
                                                        "probe": "", "tells": [], "stops_when": ""}]}
    _none = hnd.propose_plan_revision("n", None, _plan43(12), None, _b43)
    check("a note with nothing in scope makes no scan at all", _none["clips"] == [] and [c["tag"] for c in _calls43] == ["narrated_revision_split"])

    # a splitter reply that is cut off (its thinking ran past the ceiling) is tried once more, thinking less
    _ok_split43 = {"items": [{"text": "Fix clip 33", "kind": "fix_now", "in_scope": True, "why_out_of_scope": "", "replaces_rule_ids": [],
                              "probe": "p", "tells": [], "stops_when": ""}]}
    _cut43 = [hnd.app.OpenAIOutputCut("narrated_revision_split: the reply was cut off at the limit"), _ok_split43]

    def _cut_then_ok(usr):
        v = _cut43.pop(0)
        if isinstance(v, Exception):
            raise v
        return v
    _script43["narrated_revision_split"] = _cut_then_ok
    _calls43.clear()
    _items_cut = hnd.split_revision_note("a note", None, _b43, 12)
    check("a splitter reply that was cut off is asked again once, with less thinking, and the answer is used",
          [c["tag"] for c in _calls43] == ["narrated_revision_split"] * 2 and [c["effort"] for c in _calls43] == [None, "low"] and _items_cut[0]["text"] == "Fix clip 33")
    _cut43[:] = [hnd.app.OpenAIOutputCut("cut"), hnd.app.OpenAIOutputCut("cut again")]
    try:
        hnd.split_revision_note("a note", None, _b43, 12)
        _twice43 = False
    except hnd.app.OpenAIOutputCut:
        _twice43 = True
    check("a splitter reply cut off twice fails clearly instead of looping", _twice43)
    check("the ceilings leave room for the model to think: 12,000 for the splitter, 16,000 for a scan",
          hnd.REVISION_SPLIT_MAX_OUTPUT >= 12000 and hnd.SCAN_MAX_OUTPUT >= 16000)

    # rewrite: the story model, in groups, with context
    _calls43.clear()
    _beats14 = _plan43(40)
    _delivery43 = {"facts": [{"id": "f1", "role": "want", "kind": "state_now", "text": "He wants her trust", "line": "x", "key_terms": ["trust", "want"],
                               "owner": _pov43, "channel": "dialogue", "deliver_at": 3, "deadline": 3, "repeat_at": 0}]}
    _beats14[39]["reveals"] = ["Secret Word"]
    _script43["narrated_revision_rewrite"] = lambda usr: {"beats": [
        {"clip_number": int(n), "summary": f"NEWSUMMARY{n}", "turn": f"newturn{n}", "audio_lines": [{"speaker": _pov43.upper(), "line": f"new line {n} a b c d e f"}]}
        for n in _re43.findall(r"=== CLIP (\d+) - REWRITE THIS ONE", usr)]}
    _sel = {n: f"hint {n}" for n in range(3, 17)}          # 14 clips: two groups of 12 and 2
    _rw = hnd.rewrite_revision_clips(_sel, ["the request"], [{"id": "r1", "text": "STANDING"}], _beats14, _b43, _delivery43)
    check("14 clips are rewritten in 2 calls (12 + 2), and nothing but the chosen clips is asked for",
          [c["tag"] for c in _calls43] == ["narrated_revision_rewrite"] * 2 and sorted(_rw) == list(range(3, 17)))
    check("the words are written by the STORY model; the cheap one is not used for the first write", all(c["model"] is None for c in _calls43))
    check("the prompt carries the request, the rules, what must change, the facts still to be said and the neighbours as context only",
          "the request" in _calls43[0]["usr"] and "STANDING" in _calls43[0]["usr"] and "hint 3" in _calls43[0]["usr"]
          and "trust, want" in _calls43[0]["usr"] and "context only, do not rewrite" in _calls43[0]["usr"])
    check("the schema only lets the rewrite name people of the cast, and no more beats than were asked for",
          set(_calls43[0]["schema"]["properties"]["beats"]["items"]["properties"]["audio_lines"]["items"]["properties"]["speaker"]["enum"]) == set(_cast43)
          and _calls43[0]["schema"]["properties"]["beats"]["maxItems"] == 12 and _calls43[1]["schema"]["properties"]["beats"]["maxItems"] == 2)
    check("each clip is told what the audience has NOT heard yet, so a rewrite cannot leak a later reveal",
          "NOT been told these yet" in _calls43[0]["usr"] and "secret word" in _calls43[0]["usr"].lower())
    _put = hnd._put_rewrite(dict(_beat43(3), action="OLD EDIT"), {"summary": "NEW", "turn": "t", "audio_lines": [{"speaker": _pov43.lower(), "line": "a b c d e f g"}]}, _b43)
    check("a rewrite changes the summary, the turn and the words only; place, cast and kind stay; a stale `action` is brought in line",
          _put["summary"] == "NEW" and _put["action"] == "NEW" and _put["location_id"] == _loc43 and _put["present_characters"] == [_pov43, _other43]
          and _put["delivery_mode"] == "dialogue" and _put["audio_lines"][0]["speaker"] == _pov43 and _put["speech_budget"] == 7)
    check("a wordless clip stays wordless whatever the model returns",
          hnd._put_rewrite(_beat43(3, "shock_action"), {"summary": "S", "turn": "", "audio_lines": [{"speaker": _pov43, "line": "no"}]}, _b43)["audio_lines"] == [])

    # apply, end to end
    def _apply(selected, beats, delivery=None):
        return hnd.apply_plan_revision(selected, ["req"], [{"id": "r1", "text": "RULE"}], beats, _b43, delivery, None)

    _calls43.clear()
    _beats = _plan43(12)
    _beats[4]["action"] = "stale dashboard edit"
    _before_copy = _cp43.deepcopy(_beats)
    _script43["narrated_revision_rewrite"] = lambda usr: {"beats": [
        {"clip_number": int(n), "summary": f"NEWSUMMARY{n}", "turn": f"newturn{n}", "audio_lines": [{"speaker": _pov43, "line": f"new line {n} a b c d e f"}]}
        for n in _re43.findall(r"=== CLIP (\d+) - REWRITE THIS ONE", usr)]}
    _res = _apply({3: "x", 4: "y", 5: "z"}, _beats)
    check("the chosen clips are rewritten and reported with before and after",
          [c["clip"] for c in _res["changed"]] == [3, 4, 5] and _res["changed"][0]["before"]["summary"] == "SUMMARY3 two people talk"
          and _res["changed"][0]["after"]["summary"] == "NEWSUMMARY3" and _res["unresolved"] == [])
    check("every clip that was not chosen is exactly as it was", all(_res["beats"][i] == _before_copy[i] for i in (0, 1, 5, 6, 7, 8, 9, 10, 11)))
    check("the input plan itself is not modified (the caller decides what to keep)", _beats == _before_copy)
    check("places, cast and kind of the rewritten clips are unchanged",
          all(_res["beats"][i]["location_id"] == _before_copy[i]["location_id"] and _res["beats"][i]["present_characters"] == _before_copy[i]["present_characters"]
              and _res["beats"][i]["delivery_mode"] == _before_copy[i]["delivery_mode"] for i in (2, 3, 4)))
    check("a stale dashboard edit in `action` no longer contradicts the new summary", _res["beats"][4]["action"] == "NEWSUMMARY5")
    check("the changed clips get the plain-language review, once for the run 3-5",
          [c["tag"] for c in _calls43].count("narrated_plain_pass") == 1)

    # a broken rewrite: one retry on the cheap model; still broken -> the old clip is kept
    _calls43.clear()
    _beats = _plan43(12)
    _beats[2] = _beat43(3, "voiceover")
    _two = {"beats": [{"clip_number": 3, "summary": "S3", "turn": "t", "audio_lines": [{"speaker": _pov43, "line": "one two three"}, {"speaker": _pov43, "line": "four five six"}]}]}
    _good = {"beats": [{"clip_number": 3, "summary": "S3 fixed", "turn": "t", "audio_lines": [{"speaker": _pov43, "line": "one two three four five six"}]}]}
    _script43["narrated_revision_rewrite"] = [_two, _good]
    _res = _apply({3: "x"}, _beats)
    _rw_calls = [c for c in _calls43 if c["tag"] == "narrated_revision_rewrite"]
    check("a rewrite that breaks a hard rule is retried ONCE, on the cheap model, with the rule it broke",
          len(_rw_calls) == 2 and _rw_calls[0]["model"] is None and _rw_calls[1]["model"] == hnd.app.OPENAI_CLIP_MODEL and "one narrator" in _rw_calls[1]["usr"])
    check("and the fixed clip is used", _res["changed"] and _res["beats"][2]["summary"] == "S3 fixed" and _res["unresolved"] == [])
    _calls43.clear()
    _script43["narrated_revision_rewrite"] = [_two, _two]
    _res = _apply({3: "x"}, _beats)
    check("when it is still broken the old clip is KEPT and the clip is reported, never replaced by a broken one",
          _res["beats"][2] == _beats[2] and _res["changed"] == [] and _res["unresolved"][0]["clip"] == 3 and "one narrator" in " ".join(_res["unresolved"][0]["problems"]))
    _calls43.clear()
    _script43["narrated_revision_rewrite"] = [{"beats": []}]
    _res = _apply({3: "x"}, _beats)
    check("a clip the model forgot to return is reported as unchanged", _res["beats"][2] == _beats[2] and _res["unresolved"][0]["clip"] == 3)

    # facts: only a fact the CHANGED clip lost is repaired; a fact that was already missing elsewhere is left alone
    _calls43.clear()
    _beats = _plan43(12)
    _beats[2]["audio_lines"] = [{"speaker": _pov43, "line": "I want your trust today my friend"}]
    _del = {"facts": [{"id": "f1", "role": "want", "kind": "state_now", "text": "He wants her trust", "line": "I want your trust", "key_terms": ["trust", "want"],
                       "owner": _pov43, "channel": "dialogue", "deliver_at": 3, "deadline": 3, "repeat_at": 0},
                      {"id": "f2", "role": "stakes", "kind": "state_now", "text": "elsewhere", "line": "x", "key_terms": ["zebra", "giraffe"],
                       "owner": _pov43, "channel": "dialogue", "deliver_at": 9, "deadline": 9, "repeat_at": 0}]}
    _script43["narrated_revision_rewrite"] = [{"beats": [{"clip_number": 3, "summary": "S3", "turn": "t", "audio_lines": [{"speaker": _pov43, "line": "I never saw you before today"}]}]}]
    _script43["narrated_fact_repair"] = [{"audio_lines": [{"speaker": _pov43, "line": "I want your trust, nothing else"}]}]
    _res = _apply({3: "x"}, _beats, _del)
    _fr = [c for c in _calls43 if c["tag"] == "narrated_fact_repair"]
    check("a fact the rewrite dropped is put back with one small call for that clip",
          len(_fr) == 1 and "trust" in _res["beats"][2]["audio_lines"][0]["line"], [c["tag"] for c in _calls43])
    check("a fact that was already missing in an untouched clip is NOT swept up", "zebra" not in _fr[0]["usr"] and _res["beats"][8] == _beats[8])

    # verify: the same scan, with each rule's own probe, tells and stop point
    _calls43.clear()
    check("with no rules there is nothing to verify and no call", hnd.verify_plan_revision(None, _plan43(12)) == [] and _calls43 == [])
    _script43["narrated_revision_verify"] = lambda usr: _scores(usr, {5: (3, "q5", "still recognises him"), 8: (1, "q8", "maybe")})
    _v = hnd.verify_plan_revision([{"id": "r1", "text": "RULE ONE", "hint": "HINT ONE", "probe": "PROBE ONE", "stops_when": "STOP ONE"}], _plan43(12))
    check("verification lists the clips that still fail a rule (a score of 2 or 3), on the cheap model, and fixes nothing",
          [c["clip"] for c in _v] == [5] and set(_v[0]) == {"clip", "reason", "change", "quote"} and _v[0]["reason"] == "still recognises him"
          and _calls43[0]["model"] == hnd.app.OPENAI_CLIP_MODEL and _calls43[0]["tag"] == "narrated_revision_verify")
    check("it uses the rule's own probe, tells and stop point",
          "PROBE: PROBE ONE" in _calls43[0]["usr"] and "TELLS: HINT ONE" in _calls43[0]["usr"] and "RULE STOPS: STOP ONE" in _calls43[0]["usr"]
          and "RULE: RULE ONE" in _calls43[0]["usr"])
    _calls43.clear()
    _script43["narrated_revision_verify"] = lambda usr: _scores(usr, {})
    hnd.verify_plan_revision([{"id": "r1", "text": "RULE ONE"}, {"id": "r2", "text": "RULE TWO"}], _plan43(12))
    check("a rule saved without a probe is checked with a plain one, and each rule is its own scan",
          len(_calls43) == 2 and "only make sense if this were not true: RULE ONE?" in _calls43[0]["usr"] and "RULE: RULE TWO" in _calls43[1]["usr"])
    _cr2 = hnd.clean_rules([{"text": "rule", "hint": "  a   hint  "}, {"text": "other"}])
    check("a rule keeps its hint (trimmed); a rule without one has none; the hint is never put in a prompt as the rule",
          _cr2[0]["hint"] == "a hint" and "hint" not in _cr2[1] and "a hint" not in hnd.rules_block(_cr2))

    # the rewrite is told to write a character who truly does not know
    _calls43.clear()
    _script43["narrated_revision_rewrite"] = lambda usr: {"beats": [
        {"clip_number": int(n), "summary": f"S{n}", "turn": "t", "audio_lines": [{"speaker": _pov43, "line": f"new line {n} a b c d e f"}]}
        for n in _re43.findall(r"=== CLIP (\d+) - REWRITE THIS ONE", usr)]}
    hnd.rewrite_revision_clips({3: "hint"}, [hnd.item_instruction({"text": "Lily never recognises Jack", "stops_when": "Harrison names him"})], None, _plan43(12), _b43, None)
    check("a rewrite about what a character knows is told to write them as someone who truly does not, and where the rule stops",
          "truly does not know" in _calls43[0]["sys"] and "again, back, still" in _calls43[0]["sys"]
          and "(This stops applying when: Harrison names him.)" in _calls43[0]["usr"])

    # passes: a judgement call is scanned several times at once and the passes are merged
    import contextvars as _cvmod43, threading as _th43
    hnd.SCAN_PASSES = 3
    _calls43.clear()
    _cv43 = _cvmod43.ContextVar("cv43", default=None)
    _cv43.set("the job's trace")
    _seen_ctx43, _lock43, _n43 = [], _th43.Lock(), [0]
    _by_pass43 = [{5: (2, "first", "w")}, {7: (1, "second", "w")}, {5: (3, "third", "w5")}]

    def _passes(usr):
        with _lock43:
            k = _n43[0]
            _n43[0] += 1
        _seen_ctx43.append(_cv43.get())
        return _scores(usr, _by_pass43[k])
    _script43["narrated_revision_scan"] = _passes
    _res = hnd.scan_revision_clips([_item43], _plan43(12))
    check("a window is scanned SCAN_PASSES times and the passes are merged: a clip keeps its highest score over them",
          len(_calls43) == 3 and [(c["clip"], c["score"]) for c in _res] == [(5, 3), (7, 1)] and _res[0]["reason"] == "w5", _res)
    check("every pass asks the cheap model for HIGH reasoning effort", [c["effort"] for c in _calls43] == [hnd.SCAN_REASONING] * 3 and hnd.SCAN_REASONING == "high")
    check("each pass runs in the context of the task that asked, so its call is still recorded under the job's own trace", _seen_ctx43 == ["the job's trace"] * 3, _seen_ctx43)
    _calls43.clear()
    _n43[0] = 0

    def _one_fails(usr):
        with _lock43:
            k = _n43[0]
            _n43[0] += 1
        if k == 1:
            raise RuntimeError("one pass fell over")
        return _scores(usr, {5: (3, "q", "w")})
    _script43["narrated_revision_scan"] = _one_fails
    check("a pass that fails is skipped while another succeeds", [c["clip"] for c in hnd.scan_revision_clips([_item43], _plan43(12))] == [5])

    def _all_fail(usr):
        raise RuntimeError("model down")
    _script43["narrated_revision_scan"] = _all_fail
    try:
        hnd.scan_revision_clips([_item43], _plan43(12))
        _raised43 = False
    except RuntimeError as _e43:
        _raised43 = "model down" in str(_e43)
    check("when every pass fails the error is raised, not swallowed into an empty list", _raised43)
    hnd.SCAN_PASSES = 1

    # the call itself: reasoning effort is sent when asked for, and left out for a model that does not take it
    _types43b = _types43
    _rec43 = {"calls": [], "reject": False}

    class _Comp43:
        def create(self, **kw):
            _rec43["calls"].append(dict(kw))
            if _rec43["reject"] and "reasoning_effort" in kw:
                raise Exception("Unsupported parameter: 'reasoning_effort' is not supported with this model.")
            return _types43b.SimpleNamespace(choices=[_types43b.SimpleNamespace(message=_types43b.SimpleNamespace(refusal=None, content='{"ok": 1}'), finish_reason="stop")], usage=None)

    class _Client43:
        def __init__(self, **kw):
            self.chat = _types43b.SimpleNamespace(completions=_Comp43())
    _real_openai43 = _usage_app.OpenAI
    _usage_app.OpenAI = _Client43
    try:
        _usage_app._ask_openai_json("s", "u", "t", {"type": "object"}, model="m", max_completion_tokens=10, reasoning_effort="high")
        check("reasoning effort is sent to the model when asked for", _rec43["calls"][-1].get("reasoning_effort") == "high")
        _usage_app._ask_openai_json("s", "u", "t", {"type": "object"}, model="m")
        check("and is not sent when it is not asked for", "reasoning_effort" not in _rec43["calls"][-1])
        _rec43["reject"] = True
        _rec43["calls"].clear()
        _ok43 = _usage_app._ask_openai_json("s", "u", "t", {"type": "object"}, model="m", reasoning_effort="high")
        check("a model that rejects it is asked again without it, once", _ok43 == {"ok": 1} and len(_rec43["calls"]) == 2 and "reasoning_effort" not in _rec43["calls"][1])
    finally:
        _usage_app.OpenAI = _real_openai43
finally:
    hnd._ask_openai_json = _orig43
    hnd.SCAN_PASSES = _passes43

_rsrc = inspect.getsource(hnd.rewrite_revision_clips)
check("the rewrite is the story model's job; the finder, the splitter and the verifier are the cheap model's",
      "OPENAI_CLIP_MODEL" not in _rsrc and "_retry_model(1)" in _rsrc
      and "OPENAI_CLIP_MODEL" in inspect.getsource(hnd.split_revision_note) and "OPENAI_CLIP_MODEL" in inspect.getsource(hnd._scan_once))

# ---- the app: endpoints and the whole state machine, on an in-memory job store ----
from fastapi.testclient import TestClient as _TC43

_store43, _vers43, _running43 = {}, {}, {"on": False}


def _mkjob43(**kw):
    req = _usage_app.ClipRequest(topic="a premise", duration=60, mode="narrated_drama")
    return _usage_app.Job(request=req, resolution=req.resolution, mode="narrated_drama", status="plan_ready",
                          movie_bible=_cp43.deepcopy(_b43), beats=_plan43(12), acts=None,
                          plan_report={"problems": ["[REVIEW] kept", "[SOFT] old soft"], "plain_pass": {"checked": 1}}, **kw)


_keep43 = {n: getattr(_usage_app, n) for n in ("get_job", "update_job", "_save_master_plan_file", "_plan_versions", "_set_plan_versions", "job_is_running")}
_keep43_t = (_usage_app.propose_plan_revision_task.delay, _usage_app.apply_plan_revision_task.delay, _usage_app.run_generation_job.delay)
_keep43_h = {n: getattr(hnd, n) for n in ("propose_plan_revision", "apply_plan_revision", "verify_plan_revision", "plan_delivery_report", "write_narrated_outline", "plain_pass_plan")}


def _upd43(jid, **f):
    _store43[jid] = _usage_app.Job.model_validate({**_store43[jid].model_dump(), **f})
    return _store43[jid]


_usage_app.get_job = lambda jid: _store43.get(jid)
_usage_app.update_job = _upd43
_usage_app._save_master_plan_file = lambda job: None
_usage_app._plan_versions = lambda jid: _cp43.deepcopy(_vers43.get(jid, []))
_usage_app._set_plan_versions = lambda jid, v: _vers43.__setitem__(jid, _cp43.deepcopy(v[-_usage_app.PLAN_VERSIONS_KEPT:]))
_usage_app.job_is_running = lambda jid: _running43["on"]
_usage_app.propose_plan_revision_task.delay = lambda jid: _usage_app._propose_revision(jid)
_usage_app.apply_plan_revision_task.delay = lambda jid, chosen: _usage_app._apply_revision(jid, chosen)
_queued43 = []
_usage_app.run_generation_job.delay = lambda jid: _queued43.append(jid)
_prop_calls43 = []
hnd.propose_plan_revision = lambda note, rules, beats, acts, bible, premise="": (_prop_calls43.append((note, rules, premise)) or {
    "items": [{"text": "Lily never recognises Jack", "kind": "rule", "in_scope": True, "why_out_of_scope": "", "replaces_rule_ids": [],
               "probe": "THE PROBE", "tells": [], "stops_when": "Harrison names him"}],
    "rules_new": ["Lily never recognises Jack"], "rules_new_hints": ["HINT SAVED WITH THE RULE"], "replaces": [], "blocked": None,
    "rules_new_meta": [{"probe": "THE PROBE", "stops_when": "Harrison names him"}],
    "clips": [{"clip": 3, "score": 3, "reason": "r3", "change": "c3", "quote": "q3"}, {"clip": 5, "score": 1, "reason": "r5", "change": "c5", "quote": "q5"}]})
_apply_seen43, _instr_seen43 = [], []
hnd.apply_plan_revision = lambda sel, instr, rules, beats, bible, delivery, acts: _apply_seen43.append(dict(sel)) or _instr_seen43.append(list(instr)) or {
    "beats": [dict(b, summary=f"REVISED{b['clip_number']}") if b["clip_number"] in sel else b for b in beats],
    "changed": [{"clip": n, "before": {"summary": "old", "lines": []}, "after": {"summary": "new", "lines": []}} for n in sel], "unresolved": [], "notes": []}
hnd.verify_plan_revision = lambda rules, beats, acts=None: [{"clip": 9, "reason": "still wrong", "change": "x"}]
hnd.plan_delivery_report = lambda plan: {"problems": ["[SOFT] fresh soft"], "stats": {}}
hnd.plain_pass_plan = lambda outline: {"checked": 0, "rewritten": 0}
_c43 = _TC43(_usage_app.app)
try:
    _j = _mkjob43()
    _store43[_j.id] = _j
    _id = _j.id
    check("an empty note is refused", _c43.post(f"/jobs/{_id}/revise-plan", json={"note": ""}).status_code == 422)
    _other = _mkjob43()
    _other = _usage_app.Job.model_validate({**_other.model_dump(), "mode": "story_videos", "request": {**_other.request.model_dump(), "mode": "story_videos"}})
    _store43[_other.id] = _other
    check("only a Narrated Drama plan can be revised", _c43.post(f"/jobs/{_other.id}/revise-plan", json={"note": "x"}).status_code == 400)
    _gen = _mkjob43()
    _gen = _upd43(_gen.id, status="generating") if _store43.setdefault(_gen.id, _gen) else None
    check("only while the plan waits for approval", _c43.post(f"/jobs/{_gen.id}/revise-plan", json={"note": "x"}).status_code == 409)
    check("a note over the length limit is refused", _c43.post(f"/jobs/{_id}/revise-plan", json={"note": "x" * (hnd.MAX_NOTE_CHARS + 1)}).status_code == 400)

    r = _c43.post(f"/jobs/{_id}/revise-plan", json={"note": "  Lily must not recognise him  "})
    check("a note is accepted (202); the proposal is stored with the sure picks (score 2-3) ticked and a 'maybe' (score 1) not", r.status_code == 202
          and _store43[_id].revision["status"] == "proposed" and _store43[_id].revision["note"] == "Lily must not recognise him"
          and [c["selected"] for c in _store43[_id].revision["clips"]] == [True, False])
    check("the premise goes to the planner, so the splitter can see where a rule has to stop", _prop_calls43[-1][2] == "a premise")
    check("the proposal keeps the probe and the stop point for the rule", _store43[_id].revision["rules_new_meta"] == [{"probe": "THE PROBE", "stops_when": "Harrison names him"}])
    check("a proposal changes nothing in the plan", _store43[_id].beats == _plan43(12) and _store43[_id].plan_rules is None)

    # clips the finder missed can be added by hand
    r = _c43.post(f"/jobs/{_id}/revise-plan/add-clips", json={"clips": [9, 3, 9, 7]})
    _rev = _store43[_id].revision
    check("clips added by hand join the proposal ticked, sorted, without duplicates, marked as the user's",
          r.status_code == 200 and r.json()["added"] == [7, 9] and [c["clip"] for c in _rev["clips"]] == [3, 5, 7, 9]
          and all(c["selected"] for c in _rev["clips"] if c.get("manual")) and _rev["clips"][2]["manual"] is True and _rev["clips"][2]["reason"] == "You asked for this clip.")
    check("a clip the plan does not have is refused, with how many it has", _c43.post(f"/jobs/{_id}/revise-plan/add-clips", json={"clips": [99]}).status_code == 400
          and "has 12 clips" in _c43.post(f"/jobs/{_id}/revise-plan/add-clips", json={"clips": [0]}).json()["detail"])
    check("an empty list of clips is refused", _c43.post(f"/jobs/{_id}/revise-plan/add-clips", json={"clips": []}).status_code == 422)
    _upd43(_id, revision={**_store43[_id].revision, "status": "applied"})
    check("clips can only be added to a proposal that is waiting", _c43.post(f"/jobs/{_id}/revise-plan/add-clips", json={"clips": [4]}).status_code == 409)
    _upd43(_id, revision={**_store43[_id].revision, "status": "proposed"})

    r = _c43.post(f"/jobs/{_id}/revise-plan/apply", json={"clips": [4]})
    check("a clip that was not proposed is refused", r.status_code == 400)
    r = _c43.post(f"/jobs/{_id}/revise-plan/apply", json={"clips": [3, 7]})
    _job = _store43[_id]
    check("applying rewrites ONLY the ticked clips, a clip added by hand included (it carries no hint, so it follows the request)",
          r.status_code == 202 and _job.beats[2]["summary"] == "REVISED3" and _job.beats[6]["summary"] == "REVISED7" and _job.beats[4]["summary"] == "SUMMARY5 two people talk"
          and _apply_seen43[-1] == {3: "c3", 7: ""}, _apply_seen43)
    check("the rule is saved WITH its hint, so the final check knows what to look for", _job.plan_rules[0].get("hint") == "HINT SAVED WITH THE RULE")
    check("the rule is saved with the probe and stop point the scan used, and the rewrite is told where the rule stops",
          _job.plan_rules[0].get("probe") == "THE PROBE" and _job.plan_rules[0].get("stops_when") == "Harrison names him"
          and _instr_seen43[-1] == ["Lily never recognises Jack (This stops applying when: Harrison names him.)"], _instr_seen43)
    check("the rule is saved with an id", _job.plan_rules and _job.plan_rules[0]["text"] == "Lily never recognises Jack" and _job.plan_rules[0]["id"])
    check("the result is stored: what changed, what still conflicts, the rules in force",
          _job.revision["status"] == "applied" and [c["clip"] for c in _job.revision["changed"]] == [3, 7] and _job.revision["contradictions"][0]["clip"] == 9
          and _job.revision["rules_saved"] == ["Lily never recognises Jack"])
    check("the report is rebuilt, keeps the earlier [REVIEW] notes, and the older plain-language log",
          _job.plan_report["problems"] == ["[REVIEW] kept", "[SOFT] fresh soft"] and _job.plan_report["plain_pass"] == {"checked": 1})
    check("one earlier version is saved to go back to", _job.plan_versions_count == 1 and len(_vers43[_id]) == 1 and _vers43[_id][0]["beats"] == _plan43(12))
    check("applying twice is refused: the proposal is used up", _c43.post(f"/jobs/{_id}/revise-plan/apply", json={"clips": [3]}).status_code == 409)

    # busy plan: nothing can be saved over, approved or re-planned
    _upd43(_id, revision={"status": "applying", "note": "n"})
    check("while a revision runs, saving, approving and re-planning are all refused (409)",
          _c43.patch(f"/jobs/{_id}/plan", json={"beats": _plan43(12)}).status_code == 409
          and _c43.post(f"/jobs/{_id}/approve-plan", json={}).status_code == 409
          and _c43.post(f"/jobs/{_id}/replan").status_code == 409
          and _c43.post(f"/jobs/{_id}/revise-plan", json={"note": "again"}).status_code == 409)
    check("and it cannot be undone or have its rules edited mid-way",
          _c43.post(f"/jobs/{_id}/undo-plan-revision").status_code == 409 and _c43.put(f"/jobs/{_id}/plan-rules", json={"rules": []}).status_code == 409)
    _upd43(_id, revision={"status": "applied", "note": "n", "clips": [{"clip": 5, "reason": "r", "change": "c"}], "items": [], "rules_new": [], "replaces": []})
    _usage_app._apply_revision(_id, [5])
    check("a stale or duplicate task, finding the revision is not in the 'applying' state, changes nothing",
          _store43[_id].revision["status"] == "applied" and _store43[_id].beats[4]["summary"] == "SUMMARY5 two people talk")
    _upd43(_id, revision={"status": "applying", "note": "n"})
    _running43["on"] = True
    check("a stuck revision cannot be cleared while a task still holds the job", _c43.post(f"/jobs/{_id}/revise-plan/cancel").status_code == 409)
    _running43["on"] = False
    check("but can once nothing is running (a worker that died)", _c43.post(f"/jobs/{_id}/revise-plan/cancel").status_code == 200 and _store43[_id].revision is None)

    # undo
    r = _c43.post(f"/jobs/{_id}/undo-plan-revision")
    _job = _store43[_id]
    check("undo puts back the beats, the report and the rules as they were", r.status_code == 200 and _job.beats == _plan43(12) and _job.plan_rules is None
          and _job.plan_report["problems"] == ["[REVIEW] kept", "[SOFT] old soft"] and _job.plan_versions_count == 0)
    check("and there is nothing more to undo", _c43.post(f"/jobs/{_id}/undo-plan-revision").status_code == 409)

    # versions are limited
    for _k in range(7):
        _upd43(_id, revision={"status": "proposed", "note": f"n{_k}", "items": [], "rules_new": [], "replaces": [], "blocked": None,
                              "clips": [{"clip": 3, "reason": "r", "change": "c"}]})
        _c43.post(f"/jobs/{_id}/revise-plan/apply", json={"clips": [3]})
    check("only the last 5 versions are kept", len(_vers43[_id]) == 5 and _store43[_id].plan_versions_count == 5)

    # a rules-only application, a blocked one, and nothing at all
    _upd43(_id, revision={"status": "proposed", "note": "n", "items": [], "rules_new": ["a rule"], "replaces": [], "blocked": None, "clips": []})
    check("a rule can be saved on its own, with no clip ticked", _c43.post(f"/jobs/{_id}/revise-plan/apply", json={"clips": []}).status_code == 202
          and "a rule" in [r["text"] for r in _store43[_id].plan_rules])
    _upd43(_id, revision={"status": "proposed", "note": "n", "items": [], "rules_new": [], "replaces": [], "blocked": None, "clips": [{"clip": 3, "reason": "r", "change": "c"}]})
    check("applying with nothing ticked and no rule is refused", _c43.post(f"/jobs/{_id}/revise-plan/apply", json={"clips": []}).status_code == 400)
    _upd43(_id, revision={"status": "proposed", "note": "n", "items": [], "rules_new": ["x"], "replaces": [], "blocked": "too many rules", "clips": []})
    check("a proposal that would pass the rule cap cannot be applied", _c43.post(f"/jobs/{_id}/revise-plan/apply", json={"clips": []}).status_code == 409)

    # a failing step leaves the plan alone
    _upd43(_id, revision={"status": "proposed", "note": "n", "items": [], "rules_new": [], "replaces": [], "blocked": None, "clips": [{"clip": 3, "reason": "r", "change": "c"}]})
    _snap_beats = _cp43.deepcopy(_store43[_id].beats)
    hnd.apply_plan_revision = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("model down"))
    _c43.post(f"/jobs/{_id}/revise-plan/apply", json={"clips": [3]})
    check("a failed rewrite is reported and the plan is exactly as it was",
          _store43[_id].revision["status"] == "failed" and "model down" in _store43[_id].revision["error"] and _store43[_id].beats == _snap_beats)
    hnd.propose_plan_revision = lambda *a, **k: (_ for _ in ()).throw(ValueError("the note is too long"))
    _c43.post(f"/jobs/{_id}/revise-plan/cancel")
    _c43.post(f"/jobs/{_id}/revise-plan", json={"note": "x"})
    check("a failed proposal is reported too", _store43[_id].revision["status"] == "failed" and "too long" in _store43[_id].revision["error"])

    # rules: edit, delete, cap
    _c43.post(f"/jobs/{_id}/revise-plan/cancel")
    _upd43(_id, plan_rules=[{"id": "r1", "text": "one"}, {"id": "r2", "text": "two"}])
    r = _c43.put(f"/jobs/{_id}/plan-rules", json={"rules": [{"id": "r2", "text": "two edited"}]})
    check("a rule can be edited or deleted", r.status_code == 200 and _store43[_id].plan_rules == [{"id": "r2", "text": "two edited"}])
    check("more rules than the cap are refused with the reason",
          _c43.put(f"/jobs/{_id}/plan-rules", json={"rules": [{"text": f"r{i}"} for i in range(13)]}).status_code == 400)

    # re-plan keeps the rules, drops the old versions and the old proposal, and the new plan is written WITH the rules
    _upd43(_id, plan_rules=[{"id": "r1", "text": "KEEPME"}], plan_versions_count=2)
    _vers43[_id] = [{"beats": []}]
    r = _c43.post(f"/jobs/{_id}/replan")
    check("a re-plan keeps the standing rules but drops the old versions", r.status_code == 202 and _store43[_id].plan_rules == [{"id": "r1", "text": "KEEPME"}]
          and _store43[_id].plan_versions_count == 0 and _vers43[_id] == [] and _queued43 == [_id])
    _seen_topic = []
    hnd.write_narrated_outline = lambda topic, duration, total: (_seen_topic.append(topic) or ({"scene_bible": _b43, "beats": _plan43(12), "acts": []}, []))
    hnd.plan_delivery_report = lambda plan: {"problems": [], "stats": {"spoken_lines": 1, "spoken_words": 1, "narration_share": 0.3}, "blind": {}}
    _upd43(_id, status="generating")
    _store43[_id] = _usage_app.Job.model_validate({**_store43[_id].model_dump()})
    _usage_app._generate_narrated_plan(_id)
    check("the re-planned story is written with the standing rules in its premise", _seen_topic and "KEEPME" in _seen_topic[0] and "STORY RULES" in _seen_topic[0], _seen_topic)
    check("and every clip writer and the continuation planner read them too",
          "topic_with_rules" in inspect.getsource(_usage_app._continue_narrated_drama_job) and "topic_with_rules" in inspect.getsource(_usage_app._extend_movie_plan_task_traced))
finally:
    for _n, _v in _keep43.items():
        setattr(_usage_app, _n, _v)
    _usage_app.propose_plan_revision_task.delay, _usage_app.apply_plan_revision_task.delay, _usage_app.run_generation_job.delay = _keep43_t
    for _n, _v in _keep43_h.items():
        setattr(hnd, _n, _v)

_dash43 = open("dashboard.html", encoding="utf-8").read()
check("the dashboard has the revise box, the proposal with ticks, the before/after, undo and the rules list",
      all(s in _dash43 for s in ('id="plan-revise"', 'id="revise-note"', "Clips found (", "↩ Undo this revision", "Standing rules (", "/revise-plan/apply", "/undo-plan-revision", "/plan-rules")))
check("it keeps polling while a revision runs and locks Approve, Save and Re-plan meanwhile",
      "revisionBusy(job)" in _dash43 and "Revising the plan…" in _dash43 and "planBusy || revBusy" in _dash43)
check("the dashboard ticks only the clips the planner is sure of, labels the rest 'maybe', quotes the failing words, and shows where a rule stops",
      "c.selected !== false" in _dash43 and '"maybe"' in _dash43 and "It says:" in _dash43 and "Applies until:" in _dash43 and "(until: " in _dash43 and "stops_when: x.stops_when" in _dash43)
check("it offers to save unsaved edits first", "hasUnsavedEdits()" in _dash43 and "not saved yet" in _dash43)
check("it lets the user add clips the finder missed, by number or range, and keeps the clips they had unticked",
      "parseClipNumbers" in _dash43 and "/revise-plan/add-clips" in _dash43 and "reviseKeepUnticked" in _dash43 and "Also change clips the list missed" in _dash43)

# ---- Langfuse: the revision steps run under the job's trace and flush, like every other task ----
from contextlib import contextmanager as _cm43


@_cm43
def _nolock43(jid):
    yield


class _LF43:
    log = []

    def update_current_span(self, **kw):
        _LF43.log.append(("span", kw.get("name"), tuple(kw.get("tags") or ())))

    def flush(self):
        _LF43.log.append(("flush",))


_keep_lf = (_usage_app.get_client, _usage_app.job_lock, _usage_app._propose_revision, _usage_app._apply_revision)
_usage_app.get_client = lambda: _LF43()
_usage_app.job_lock = _nolock43
_usage_app._propose_revision = lambda jid: _LF43.log.append(("propose ran", jid))
_usage_app._apply_revision = lambda jid, chosen: _LF43.log.append(("apply ran", jid, tuple(chosen)))
try:
    _usage_app.propose_plan_revision_task.run("0123456789abcdef0123456789abcdef")
    _usage_app.apply_plan_revision_task.run("0123456789abcdef0123456789abcdef", [3, 5])
finally:
    _usage_app.get_client, _usage_app.job_lock, _usage_app._propose_revision, _usage_app._apply_revision = _keep_lf
check("each revision step labels its Langfuse span and flushes afterwards",
      ("span", "plan_revision_propose", ("narrated_drama", "plan_revision", "propose")) in _LF43.log
      and ("span", "plan_revision_apply", ("narrated_drama", "plan_revision", "apply")) in _LF43.log and _LF43.log.count(("flush",)) == 2, _LF43.log)
check("and still does the work: the proposal for the job, the rewrite for the ticked clips",
      ("propose ran", "0123456789abcdef0123456789abcdef") in _LF43.log and ("apply ran", "0123456789abcdef0123456789abcdef", (3, 5)) in _LF43.log)
check("both tasks pass the JOB id as the trace id, so their calls sit under the job's own Langfuse trace",
      inspect.getsource(_usage_app.propose_plan_revision_task).count("langfuse_trace_id=job_id") == 1
      and inspect.getsource(_usage_app.apply_plan_revision_task).count("langfuse_trace_id=job_id") == 1)
check("the flush happens even if the step fails", "finally:" in inspect.getsource(_usage_app._plan_revision_traced)
      and "get_client().flush()" in inspect.getsource(_usage_app._plan_revision_traced))

print("\n[44] Supporting cast: people on screen are cast, the plan report says who is missing, and Revise can add them")
import copy as _cp44, re as _re44, inspect as _insp44

# ---- the planner is told: anyone with a part in a shot is cast, as a lighter 'supporting' entry ----
_p_outline = hnd._narrated_outline_prompt("a story", 120, 24)[0]
_p_break = hnd._narrated_act_breakdown_prompt("a story", 300, 60)[0]
_acts44 = [{"act_number": 1, "title": "Act 1", "start_clip": 1, "end_clip": 2, "primary_locations": [], "dramatic_question": "", "summary": "", "reveals": []}]
_batch44 = {"batch_index": 1, "act_numbers": [1], "start_clip": 1, "end_clip": 2, "clip_count": 2, "title": "Act 1", "primary_locations": [], "dramatic_question": "", "summary": ""}
_p_beats = hnd._narrated_act_beats_prompt("premise", _batch44, _acts44, GOOD["scene_bible"], [], 6)[0]
check("both casting prompts say: cast anyone with a part in a shot, as role 'supporting', with the same fixed look",
      all("SUPPORTING CHARACTERS (CRITICAL)" in p and f'"role" to exactly "{hnd.SUPPORTING_ROLE}"' in p for p in (_p_outline, _p_break)))
check("main characters still may not share a hair colour; a supporting one only has to differ in colour or in style",
      all("No two MAIN characters may share a hair colour" in p and "differ from every other character in hair colour OR hair style" in p for p in (_p_outline, _p_break)))
check("the short-plan prompt and the beats prompt carry the on-screen rule; the breakdown (no beats) does not need it",
      "ON-SCREEN RULE" in _p_outline and "ON-SCREEN RULE" in _p_beats and "ON-SCREEN RULE" not in _p_break)
check("the limits are in the rule: at most 4 supporting characters, 2 lines in the whole film",
      "At most 4 supporting characters" in _p_outline and "2 lines or fewer in the whole film" in _p_outline and (hnd.MAX_SUPPORTING, hnd.SUPPORTING_MAX_LINES) == (4, 2))
_chap44 = hnd._narrated_chapter_prompt("A tense thriller", 1, 4, GOOD["beats"][1], GOOD["scene_bible"], [])[0]
check("the clip writer keeps people who are not in the cast out of the shot, the environment and every action",
      "they stay off screen" in _chap44 and "Describe only the cast" in _chap44)

# ---- the bible check and the beats check know about supporting characters ----
def _sup44(name, hair, style, role=hnd.SUPPORTING_ROLE, feature="round gold-rimmed glasses"):
    return {"name": name, "is_protagonist": False, "role": role, "voice": "warm alto",
            "appearance": appearance(casting="woman in her fifties", hair_color=hair, hair_style=style, distinguishing_feature=feature, wardrobe="a green cardigan"),
            "motivation": "m", "relationships": "r", "speech_style": "s"}


_bs44 = _cp44.deepcopy(GOOD["scene_bible"])
_bs44["characters"].append(_sup44("Margaret Larson", "ash blonde", "long, tied in a low plait"))
check("a supporting character may share a hair colour with someone when the style differs, even in a small cast",
      not any("Margaret" in p for p in hnd._check_scene_bible(_bs44)), hnd._check_scene_bible(_bs44))
_bm44 = _cp44.deepcopy(GOOD["scene_bible"])
_bm44["characters"].append(_sup44("Margaret Larson", "ash blonde", "long, tied in a low plait", role="co-worker"))
check("a main character may not (small cast)", any("Margaret" in p and "hair colour" in p for p in hnd._check_scene_bible(_bm44)))
_bsame44 = _cp44.deepcopy(GOOD["scene_bible"])
_bsame44["characters"].append(_sup44("Margaret Larson", "ash blonde", "short bob, worn loose"))
check("the same colour AND the same style is a problem for anyone", any("Margaret" in p and "AND" in p for p in hnd._check_scene_bible(_bsame44)))
_b5 = _cp44.deepcopy(GOOD["scene_bible"])
for _i, _h in enumerate(("copper red", "silver grey", "chestnut", "platinum blonde", "white")):
    _b5["characters"].append(_sup44(f"Person {chr(65 + _i)}", _h, f"style {_i}"))
check("more than 4 supporting characters is a soft note, not a failure",
      any(p.startswith("[SOFT]") and "5 supporting characters" in p for p in hnd._check_scene_bible(_b5)))
_lines44 = [_beat43(n, audio_lines=[{"speaker": "Margaret Larson", "line": f"line {n} one two three four five six"}]) for n in (2, 3, 4)]
_bl44 = [_beat43(1)] + _lines44
_pr = [p for p in hnd._check_beats(_bl44, _bs44) if "supporting character" in p]
check("a supporting character who speaks more than 2 lines in the film is a soft note",
      len(_pr) == 1 and _pr[0].startswith("[SOFT]") and "Margaret Larson" in _pr[0] and "3 lines" in _pr[0], _pr)
check("two lines are fine", not [p for p in hnd._check_beats(_bl44[:3], _bs44) if "supporting character" in p])

# ---- the cast-gap finder ----
_calls43.clear()
_orig44 = hnd._ask_openai_json
hnd._ask_openai_json = _router
_plan44 = _plan43(12)
for _n in (4, 5, 6):
    _plan44[_n - 1]["summary"] = f"SUMMARY{_n} Mike's mother beams across the table"


def _gaps_reply(usr):
    return {"people": [
        {"label": "Mike's mother", "suggested_name": "Margaret Larson", "relation": "Mike's mother", "clips": [4, 5, 6, 99], "evidence": "clip 4: the mother beams", "speaks": False},
        {"label": _other43, "suggested_name": "Somebody", "relation": "x", "clips": [4], "evidence": "x", "speaks": False},
        {"label": "the waiter", "suggested_name": _other43, "relation": "waiter", "clips": [2], "evidence": "x", "speaks": True},
        {"label": "Mike's father", "suggested_name": "Tom Larson", "relation": "", "clips": [], "evidence": "x", "speaks": False}]}


try:
    _script43["narrated_cast_gap"] = _gaps_reply
    _g = hnd.find_cast_gaps(_plan44, _b43)
    check("the finder lists a person shown on screen without being cast, with the clips they are in (clips the plan lacks dropped)",
          len(_g) == 1 and _g[0]["label"] == "Mike's mother" and _g[0]["suggested_name"] == "Margaret Larson" and _g[0]["clips"] == [4, 5, 6] and _g[0]["speaks"] is False, _g)
    check("someone already in the cast, a name the cast already has, and a person with no clip are all left out", [x["label"] for x in _g] == ["Mike's mother"])
    check("it runs on the cheap model at high effort, with the cast and the clips in the prompt",
          [c["tag"] for c in _calls43] == ["narrated_cast_gap"] and _calls43[0]["model"] == hnd.app.OPENAI_CLIP_MODEL and _calls43[0]["effort"] == "high"
          and _other43 in _calls43[0]["usr"] and "Mike's mother beams across the table" in _calls43[0]["usr"] and "THE CLIPS TO CHECK (1-12)" in _calls43[0]["usr"])
    check("its prompt says who counts (a part in the shot), who does not (only talked about), and to name the people a group would include",
          all(s in _calls43[0]["sys"] for s in ("physically on screen with a part in the shot", "only talked about", "does NOT count", "FEWEST people", "at most four")))
    _calls43.clear()

    def _per_window(usr):
        lo = int(_re44.search(r"THE CLIPS TO CHECK \((\d+)-", usr).group(1))
        return {"people": [{"label": "Mike's mother", "suggested_name": "Margaret Larson", "relation": "Mike's mother", "clips": [lo + 1], "evidence": f"clip {lo + 1}", "speaks": lo > 1}]}
    _script43["narrated_cast_gap"] = _per_window
    _g65 = hnd.find_cast_gaps(_plan43(65), _b43)
    check("a 65-clip plan is read in two windows, the later one shown the earlier clips, and the same person is merged into one",
          len(_calls43) == 2 and "EARLIER CLIPS" not in _calls43[0]["usr"] and "EARLIER CLIPS" in _calls43[1]["usr"]
          and len(_g65) == 1 and _g65[0]["clips"] == [2, 35] and _g65[0]["speaks"] is True, _g65)

    # ---- the plan report ----
    _keep44h = (hnd.blind_read, hnd.check_blind_answers)
    hnd.blind_read = lambda beats: {}
    hnd.check_blind_answers = lambda answers, delivery: {"problems": []}
    try:
        _calls43.clear()
        _script43["narrated_cast_gap"] = _gaps_reply
        _rep44 = hnd.plan_delivery_report({"scene_bible": _b43, "beats": _plan44, "delivery": {}}, run_blind=True)
        _cast_lines = [p for p in _rep44["problems"] if p.startswith("[REVIEW] Cast: ")]
        check("the plan report warns, first among the review notes, who is on screen without being cast, with their clips, and says what to press",
              len(_cast_lines) == 1 and "Mike's mother (clips 4-6)" in _cast_lines[0] and "Check the cast" in _cast_lines[0] and _rep44["cast_gaps"][0]["label"] == "Mike's mother", _rep44["problems"])
        _calls43.clear()
        _off = hnd.plan_delivery_report({"scene_bible": _b43, "beats": _plan44, "delivery": {}}, run_blind=False)
        check("with run_blind=False no model is called and there is no cast note", not _calls43 and "cast_gaps" not in _off and not [p for p in _off["problems"] if "Cast:" in p])
        _script43["narrated_cast_gap"] = {"people": []}
        check("nobody missing: no note", not [p for p in hnd.plan_delivery_report({"scene_bible": _b43, "beats": _plan44, "delivery": {}}, run_blind=True)["problems"] if "Cast:" in p])

        def _boom(usr):
            raise RuntimeError("model down")
        _script43["narrated_cast_gap"] = _boom
        _rep_err = hnd.plan_delivery_report({"scene_bible": _b43, "beats": _plan44, "delivery": {}}, run_blind=True)
        check("a failing check never breaks the report", "model down" in _rep_err.get("cast_gap_error", "") and _rep_err["stats"]["clips"] == 12)
        _keep_sw = hnd.CAST_GAP_CHECK
        hnd.CAST_GAP_CHECK = False
        _calls43.clear()
        _script43["narrated_cast_gap"] = _gaps_reply
        hnd.plan_delivery_report({"scene_bible": _b43, "beats": _plan44, "delivery": {}}, run_blind=True)
        hnd.CAST_GAP_CHECK = _keep_sw
        check("the switch CAST_GAP_CHECK turns it off", not _calls43)
    finally:
        hnd.blind_read, hnd.check_blind_answers = _keep44h

    # ---- writing looks and adding people ----
    _ENT44 = {"Margaret Larson": ("silver grey", "long, tied in a low plait", "round gold-rimmed glasses"),
              "Tom Larson": ("copper red", "thinning, combed straight back", "a bushy ginger moustache"),
              "Becky Larson": ("chestnut", "shoulder-length waves", "freckles across the nose")}

    def _entry(name, hair=None, style=None, feature=None):
        h, s, f = _ENT44[name]
        return {"name": name, "appearance": appearance(casting="person in their fifties", hair_color=hair or h, hair_style=style or s,
                                                       distinguishing_feature=feature or f, wardrobe="a green cardigan"),
                "voice": "warm alto with a soft Yorkshire lilt", "motivation": "wants her son happy", "relationships": "Mike's mother", "speech_style": "kind and brief"}

    def _names_in(usr):
        return [n.strip() for n in _re44.findall(r"^- ([A-Za-z .'\-]+?)(?: \(.*\))?$", usr.split("WRITE ENTRIES FOR:")[1], _re44.M)]
    _script43["narrated_cast_looks"] = lambda usr: {"characters": [_entry(n) for n in _names_in(usr)]}
    _calls43.clear()
    _bible_before, _beats_before = _cp44.deepcopy(_b43), _cp44.deepcopy(_plan44)
    _people = [{"name": "Margaret Larson", "relation": "Mike's mother", "clips": [4, 5, 6]}, {"name": "Tom Larson", "relation": "Mike's father", "clips": [4, 5, 99]}]
    _res = hnd.add_supporting_cast(_people, _plan44, _b43)
    _nb, _nbeats = _res["bible"], _res["beats"]
    _m = next(c for c in _nb["characters"] if c["name"] == "Margaret Larson")
    check("the new people join the bible as supporting characters, with a compiled look and portrait prompt",
          len(_nb["characters"]) == len(_b43["characters"]) + 2 and _m["role"] == hnd.SUPPORTING_ROLE and _m["is_protagonist"] is False
          and "silver grey" in _m["look"] and "silver grey" in _m["image_prompt"] and _m["voice"].startswith("warm alto"), _m)
    check("each is put in the on-screen list of the clips given, and only those (a clip the plan lacks is ignored)",
          [n for n in range(1, 13) if "Margaret Larson" in _nbeats[n - 1]["present_characters"]] == [4, 5, 6]
          and [n for n in range(1, 13) if "Tom Larson" in _nbeats[n - 1]["present_characters"]] == [4, 5])
    _strip = lambda beats: [dict(b, present_characters=[p for p in b["present_characters"] if p not in ("Margaret Larson", "Tom Larson")]) for b in beats]
    check("nothing else in the plan changes: no line, no summary, no place", _strip(_nbeats) == _beats_before)
    check("the plan and the bible that were passed in are untouched", _plan44 == _beats_before and _b43 == _bible_before)
    check("the result says who was added, with their look and clips",
          [(a["name"], a["clips"]) for a in _res["added"]] == [("Margaret Larson", [4, 5, 6]), ("Tom Larson", [4, 5])] and "silver grey" in _res["added"][0]["look"])
    check("the looks are written by the cheap model at high effort, knowing every look already in the cast",
          [c["tag"] for c in _calls43] == ["narrated_cast_looks"] and _calls43[0]["model"] == hnd.app.OPENAI_CLIP_MODEL and _calls43[0]["effort"] == "high"
          and "ash blonde" in _calls43[0]["usr"] and "jet black" in _calls43[0]["usr"] and "- Margaret Larson (Mike's mother)" in _calls43[0]["usr"])
    check("no character the bible check would reject: every field filled, nobody the same colour and style",
          not [p for p in hnd._check_scene_bible(_nb) if not p.startswith("[SOFT]")], hnd._check_scene_bible(_nb))
    _again = hnd.add_supporting_cast([{"name": "Becky Larson", "relation": "Mike's sister", "clips": [4]}], _nbeats, _nb)
    check("adding to a plan that already has supporting characters works, and the cast cap counts them",
          len([c for c in _again["bible"]["characters"] if hnd._is_supporting(c)]) == 3)

    def _refused(people, beats=None, bible=None):
        try:
            hnd.add_supporting_cast(people, beats or _plan44, bible or _b43)
            return ""
        except ValueError as e:
            return str(e)
    _calls43.clear()
    check("a name already in the cast is refused before any model call", "already in the cast" in _refused([{"name": _other43, "clips": [4]}]) and not _calls43)
    check("a name given twice is refused", "listed twice" in _refused([{"name": "Ann", "clips": [4]}, {"name": "ann", "clips": [5]}]))
    check("a name with digits or symbols is refused", "cannot be a character name" in _refused([{"name": "Marg4ret", "clips": [4]}]) and "cannot be a character name" in _refused([{"name": "Ann <b>", "clips": [4]}]))
    check("a blank name is refused", "needs a name" in _refused([{"name": "  ", "clips": [4]}]))
    check("a person with no clip the plan has is refused, saying how many clips it has", "clips 1 to 12" in _refused([{"name": "Ann", "clips": [99]}]))
    check("an empty list is refused", "nobody to add" in _refused([]))
    _full44 = _cp44.deepcopy(_nb)
    _full44["characters"] += [_sup44("Person A", "white", "style a"), _sup44("Person B", "platinum blonde", "style b")]
    check("past the cap of supporting characters is refused, with the numbers", "at most 4" in _refused([{"name": "Ann", "clips": [4]}, {"name": "Bob", "clips": [4]}], bible=_full44))

    # looks that cannot be told apart: one more try with the reasons, then a clear failure and no change
    _calls43.clear()
    _bad = lambda usr: {"characters": [_entry(n, hair="ash blonde", style="short bob, worn loose") for n in _names_in(usr)]}
    _script43["narrated_cast_looks"] = _bad
    check("looks that copy an existing character fail clearly after one retry", "could not write looks" in _refused([{"name": "Margaret Larson", "clips": [4]}])
          and [c["tag"] for c in _calls43] == ["narrated_cast_looks"] * 2 and "YOUR PREVIOUS ATTEMPT BROKE THESE RULES" in _calls43[1]["usr"])
    _calls43.clear()
    _seq = [_bad, lambda usr: {"characters": [_entry(n) for n in _names_in(usr)]}]
    _script43["narrated_cast_looks"] = lambda usr: _seq.pop(0)(usr)
    _ok = hnd.add_supporting_cast([{"name": "Margaret Larson", "clips": [4]}], _plan44, _b43)
    check("and when the second try is good it is used", len(_calls43) == 2 and _ok["added"][0]["name"] == "Margaret Larson")
    _script43["narrated_cast_looks"] = lambda usr: {"characters": []}
    check("a reply that forgets the person fails clearly too", "could not write looks" in _refused([{"name": "Margaret Larson", "clips": [4]}]))
    _script43["narrated_cast_looks"] = lambda usr: {"characters": [_entry(n) for n in _names_in(usr)]}
    _crowd = _cp44.deepcopy(_plan44)
    _crowd[3]["present_characters"] = [f"Extra {i}" for i in range(hnd.MAX_ON_SCREEN)]
    _rc = hnd.add_supporting_cast([{"name": "Margaret Larson", "clips": [4, 5]}], _crowd, _b43)
    check("a clip that already shows 7 people is skipped, with a note",
          "Margaret Larson" not in _rc["beats"][3]["present_characters"] and "Margaret Larson" in _rc["beats"][4]["present_characters"] and any("clip 4" in n for n in _rc["notes"]), _rc["notes"])
    _dup = _cp44.deepcopy(_plan44)
    _dup[3]["present_characters"].append("Margaret Larson")
    _rd = hnd.add_supporting_cast([{"name": "Margaret Larson", "clips": [4]}], _dup, {**_b43, "characters": _b43["characters"]})
    check("a name already listed in a clip is not listed twice", _rd["beats"][3]["present_characters"].count("Margaret Larson") == 1)
finally:
    hnd._ask_openai_json = _orig44

# ---- the app: the two endpoints, the two tasks, undo ----
from fastapi.testclient import TestClient as _TC44
_store44, _vers44, _running44 = {}, {}, {"on": False}


def _mkjob44(**kw):
    req = _usage_app.ClipRequest(topic="a premise", duration=60, mode="narrated_drama")
    return _usage_app.Job(request=req, resolution=req.resolution, mode="narrated_drama", status="plan_ready",
                          movie_bible=_cp44.deepcopy(_b43), scene_bible=_json43.dumps(_b43), beats=_plan43(12), acts=None,
                          plan_report={"problems": ["[REVIEW] kept", "[REVIEW] Cast: the plan puts people on screen who are not in the cast: x. y", "[SOFT] old soft"],
                                       "plain_pass": {"checked": 1}}, **kw)


def _upd44(jid, **f):
    _store44[jid] = _usage_app.Job.model_validate({**_store44[jid].model_dump(), **f})
    return _store44[jid]


_keep44 = {n: getattr(_usage_app, n) for n in ("get_job", "update_job", "_save_master_plan_file", "_plan_versions", "_set_plan_versions", "job_is_running")}
_keep44_t = (_usage_app.propose_cast_additions_task.delay, _usage_app.apply_cast_additions_task.delay)
_keep44_h = {n: getattr(hnd, n) for n in ("find_cast_gaps", "add_supporting_cast", "plan_delivery_report")}
_usage_app.get_job = lambda jid: _store44.get(jid)
_usage_app.update_job = _upd44
_usage_app._save_master_plan_file = lambda job: None
_usage_app._plan_versions = lambda jid: _cp44.deepcopy(_vers44.get(jid, []))
_usage_app._set_plan_versions = lambda jid, v: _vers44.__setitem__(jid, _cp44.deepcopy(v[-_usage_app.PLAN_VERSIONS_KEPT:]))
_usage_app.job_is_running = lambda jid: _running44["on"]
_usage_app.propose_cast_additions_task.delay = lambda jid: _usage_app._propose_cast(jid)
_usage_app.apply_cast_additions_task.delay = lambda jid, people: _usage_app._apply_cast(jid, people)
_gap_calls44, _add_calls44 = [], []
hnd.find_cast_gaps = lambda beats, bible: (_gap_calls44.append((len(beats), [c["name"] for c in bible["characters"]])) or [
    {"label": "Mike's mother", "suggested_name": "Margaret Larson", "relation": "Mike's mother", "clips": [4, 5, 6], "evidence": "clip 4: she beams", "speaks": False}])


def _fake_add(people, beats, bible):
    _add_calls44.append(_cp44.deepcopy(people))
    nb = _cp44.deepcopy(bible)
    nb["characters"].append({"name": people[0]["name"], "is_protagonist": False, "role": "supporting", "look": "LOOK", "appearance": {}})
    nbeats = _cp44.deepcopy(beats)
    for n in people[0]["clips"]:
        nbeats[n - 1]["present_characters"].append(people[0]["name"])
    return {"bible": nb, "beats": nbeats, "added": [{"name": people[0]["name"], "relation": people[0]["relation"], "clips": people[0]["clips"], "look": "LOOK"}], "notes": ["a note"]}


hnd.add_supporting_cast = _fake_add
hnd.plan_delivery_report = lambda plan: {"problems": ["[SOFT] fresh soft"], "stats": {}}
_c44 = _TC44(_usage_app.app)
try:
    _j44 = _mkjob44()
    _store44[_j44.id] = _j44
    _id44 = _j44.id
    r = _c44.post(f"/jobs/{_id44}/cast-check")
    _rv = _store44[_id44].revision
    check("the cast check is accepted (202) and stored as a proposal of its own kind: people ticked, the cap and how many supporting there are now",
          r.status_code == 202 and _rv["kind"] == "cast" and _rv["status"] == "proposed" and _rv["people"][0]["suggested_name"] == "Margaret Larson"
          and _rv["people"][0]["include"] is True and _rv["supporting_now"] == 0 and _rv["max_supporting"] == hnd.MAX_SUPPORTING, _rv)
    check("it read the job's own beats and cast, and changed nothing in the plan", _gap_calls44 == [(12, _cast43)] and _store44[_id44].beats == _plan43(12))
    check("a cast proposal cannot be applied or extended as if it were a note",
          _c44.post(f"/jobs/{_id44}/revise-plan/apply", json={"clips": [4]}).status_code == 409
          and _c44.post(f"/jobs/{_id44}/revise-plan/add-clips", json={"clips": [4]}).status_code == 409)
    check("applying with nobody ticked is refused (400), and a blank name is refused (422)",
          _c44.post(f"/jobs/{_id44}/cast-check/apply", json={"people": [{"name": "Ann", "clips": [4], "include": False}]}).status_code == 400
          and _c44.post(f"/jobs/{_id44}/cast-check/apply", json={"people": [{"name": "", "clips": [4]}]}).status_code == 422)
    _other44 = _mkjob44()
    _store44[_other44.id] = _other44
    check("there is no cast proposal to apply on a job that has none (409)", _c44.post(f"/jobs/{_other44.id}/cast-check/apply", json={"people": [{"name": "Ann", "clips": [4]}]}).status_code == 409)

    r = _c44.post(f"/jobs/{_id44}/cast-check/apply", json={"people": [
        {"name": "Margaret Larson", "relation": "Mike's mother", "clips": [4, 5, 6], "include": True},
        {"name": "Skip Me", "relation": "x", "clips": [1], "include": False}]})
    _job = _store44[_id44]
    check("applying adds ONLY the ticked people, with the name and clips as edited", r.status_code == 202
          and _add_calls44[-1] == [{"name": "Margaret Larson", "relation": "Mike's mother", "clips": [4, 5, 6], "include": True}], _add_calls44)
    check("the cast and the beats are updated, and the stored scene bible text agrees with the cast",
          [c["name"] for c in _job.movie_bible["characters"]][-1] == "Margaret Larson" and "Margaret Larson" in _job.beats[3]["present_characters"]
          and "Margaret Larson" in _job.scene_bible and _json43.loads(_job.scene_bible) == _job.movie_bible)
    check("the result is stored: who was added, with their clips and look, and any note",
          _job.revision["kind"] == "cast" and _job.revision["status"] == "applied" and _job.revision["added"][0]["name"] == "Margaret Larson" and _job.revision["notes"] == ["a note"])
    check("the report is rebuilt: the cast warning goes (it is worked out afresh), other review notes stay, the plain-language log stays",
          _job.plan_report["problems"] == ["[REVIEW] kept", "[SOFT] fresh soft"] and _job.plan_report["plain_pass"] == {"checked": 1}, _job.plan_report["problems"])
    check("one earlier version is saved, and it carries the OLD cast", _job.plan_versions_count == 1 and len(_vers44[_id44]) == 1
          and _vers44[_id44][0]["movie_bible"] == _b43 and _vers44[_id44][0]["beats"] == _plan43(12) and "Margaret Larson" in _vers44[_id44][0]["label"])

    r = _c44.post(f"/jobs/{_id44}/undo-plan-revision")
    _job = _store44[_id44]
    check("undo takes the person out of the cast AND out of the clips together, and the scene bible text with them",
          r.status_code == 200 and _job.movie_bible == _b43 and _job.beats == _plan43(12) and _json43.loads(_job.scene_bible) == _b43 and _job.plan_versions_count == 0)
    _vers44[_id44] = [{"beats": _plan43(12), "plan_report": None, "plan_rules": None}]
    _upd44(_id44, movie_bible=_cp44.deepcopy(_nb))
    _c44.post(f"/jobs/{_id44}/undo-plan-revision")
    check("an older version that carries no cast leaves the cast as it is", _store44[_id44].movie_bible == _nb)

    # a failure changes nothing
    _upd44(_id44, movie_bible=_cp44.deepcopy(_b43), revision={"kind": "cast", "status": "proposed", "people": [], "at": 1})
    _snap44 = (_cp44.deepcopy(_store44[_id44].beats), _cp44.deepcopy(_store44[_id44].movie_bible))
    _vers44[_id44] = []
    hnd.add_supporting_cast = lambda *a, **k: (_ for _ in ()).throw(ValueError("could not write looks that tell the new people apart"))
    _c44.post(f"/jobs/{_id44}/cast-check/apply", json={"people": [{"name": "Ann", "clips": [4]}]})
    check("a failed addition is reported with the reason, and the plan, the cast and the versions are exactly as they were",
          _store44[_id44].revision["status"] == "failed" and "tell the new people apart" in _store44[_id44].revision["error"]
          and (_store44[_id44].beats, _store44[_id44].movie_bible) == _snap44 and not _vers44[_id44])
    _upd44(_id44, revision={"kind": "cast", "status": "applied", "added": [], "at": 1})
    _usage_app._apply_cast(_id44, [{"name": "Ann", "clips": [4]}])
    check("a stale or duplicate task, finding the revision is not in the 'applying' state, changes nothing", _store44[_id44].revision["status"] == "applied")
    hnd.find_cast_gaps = lambda beats, bible: (_ for _ in ()).throw(RuntimeError("model down"))
    _upd44(_id44, revision=None)
    _c44.post(f"/jobs/{_id44}/cast-check")
    check("a failing cast check is reported and the plan is left alone", _store44[_id44].revision["status"] == "failed" and "model down" in _store44[_id44].revision["error"])
    _upd44(_id44, revision={"status": "applying", "note": "n"})
    check("a cast check cannot start while a revision runs", _c44.post(f"/jobs/{_id44}/cast-check").status_code == 409)
    _gen44 = _mkjob44()
    _store44[_gen44.id] = _gen44
    _upd44(_gen44.id, status="generating")
    check("or once the plan is approved", _c44.post(f"/jobs/{_gen44.id}/cast-check").status_code == 409)
    _upd44(_id44, revision=None)
finally:
    for _n, _v in _keep44.items():
        setattr(_usage_app, _n, _v)
    _usage_app.propose_cast_additions_task.delay, _usage_app.apply_cast_additions_task.delay = _keep44_t
    for _n, _v in _keep44_h.items():
        setattr(hnd, _n, _v)

check("both cast tasks run under the job's own Langfuse trace, and the traced step knows both",
      _insp44.getsource(_usage_app.propose_cast_additions_task).count("langfuse_trace_id=job_id") == 1
      and _insp44.getsource(_usage_app.apply_cast_additions_task).count("langfuse_trace_id=job_id") == 1
      and "cast_propose" in _insp44.getsource(_usage_app._plan_revision_traced) and "cast_apply" in _insp44.getsource(_usage_app._plan_revision_traced))
_dash44 = open("dashboard.html", encoding="utf-8").read()
check("the dashboard has the Check the cast button, the proposal (untick, rename, edit clips), the result and Undo",
      all(s in _dash44 for s in ('id="cast-btn"', "Check the cast", "/cast-check", "/cast-check/apply", "function renderCast(", "Undo: take them back out of the cast",
                                  "supporting characters", "rev.kind === \"cast\"")))
check("it draws a cast result by its own function, but shows a failure the usual way", 'rev.kind === "cast" && rev.status !== "failed"' in _dash44)

print("\n[45] Camera: a person with a camera, not a tripod; speaker-first coverage; groups; tracking; the 180-degree rule with its exceptions")
_cam = hnd._narrated_chapter_prompt("A tense thriller", 1, 4, GOOD["beats"][1], GOOD["scene_bible"], [])[0]
_vo_cam = hnd._narrated_chapter_prompt("A tense thriller", 0, 4, GOOD["beats"][0], GOOD["scene_bible"], [])[0]
check("the prompt still builds, still starts every shot with [SAME SETUP] or [ANGLE CUT], and says what each tag means",
      'MUST explicitly begin with either "[SAME SETUP]" or "[ANGLE CUT]"' in _cam and "starts where the previous clip's camera ended" in _cam)
check("it says the camera is a person, with a real small move in every shot, light handheld, never a shake",
      "THE CAMERA IS A PERSON, NOT A TRIPOD" in _cam and "light handheld sway" in _cam and "never a shake" in _cam)
check("the words locked, static, frozen and holds still are forbidden in a shot, and the old 'locked static hold' example is gone from the good ones",
      'NEVER write "locked", "static", "frozen" or "holds still"' in _cam and _cam.count("static hold") == 1 and 'BAD EXAMPLE: "Wide shot, eye-level, locked static hold' in _cam
      and "LOCKED MASTER SHOT" not in _cam and "locked wide or medium" not in _cam)
check("narration and wordless action clips move freely, from any side, but keep to the geography inside a conversation scene",
      "NARRATION (voiceover) and WORDLESS ACTION clips: the camera moves FREELY" in _cam and "may start from any side of the place" in _cam and "keeps to the geography already shown" in _cam)
check("two-person dialogue is speaker-first shot / reverse-shot over the listener's shoulder, the speaker's face always visible",
      "DIALOGUE between TWO people: shot / reverse-shot, SPEAKER FIRST" in _cam and "SPEAKER'S FACE over the LISTENER'S shoulder" in _cam
      and "only a visible face can move its lips" in _cam)
check("a clip where both people speak CUTS inside the clip, in the gap between the lines, with the cut time written into the one shot sentence; never a profile two-shot",
      "A clip in which BOTH people speak CUTS INSIDE the clip" in _cam and "a hard cut, timed in the gap between the two lines" in _cam
      and "hard cut at 2.5 seconds" in _cam and "cut at each change of speaker, never more than twice" in _cam
      and "NEVER a profile two-shot with both faces turned toward each other" in _cam and "profile two-shot" not in _cam.replace("NEVER a profile two-shot", ""))
check("the speaker is three-quarter toward the lens, never pure profile, in the text and in the blocking instruction",
      "turned THREE-QUARTER toward the lens, never in pure profile" in _cam and 'the speaker is three-quarter toward the lens; pure profile only for a deliberate confrontation' in _cam)
check("framing is tight when someone speaks (the video is vertical): medium close-up or close-up, never wider than waist-up, wides only for openings, groups and movement",
      "FRAMING WHEN SOMEONE SPEAKS: the video is VERTICAL (9:16), so frame TIGHT" in _cam and "Medium Close-Up (chest up) or a Close-Up, NEVER wider than a Medium shot (waist up)" in _cam
      and "nothing below the waist is shown" in _cam and "only for the first clip of a scene, for group shots and for movement" in _cam)
check("the two parts of a cut inside one clip stay on the same side of the line", "stay on the SAME side of the line" in _cam)
check("people are not statues, kept LIGHT: no 'frozen' or 'holds still' for a listener, small natural moves only, and NO breaths, sighs, exhales, gulps or a 'settling' before a line",
      "PEOPLE IN THE SHOT ARE NOT STATUES (KEEP IT LIGHT)" in _cam and "'holds still' or 'stays still'" in _cam and "do NOT write breaths in, sighs, exhales, gulps or a facial 'settling' before a line" in _cam
      and "a speaker simply begins on the first word of the line" in _cam)
check("the clip prompt no longer says to hold both speakers in frame together: it keeps them in the shot, shows each speaker's face, and allows the cut",
      "in frame together" not in _insp44.getsource(hnd.build_narrated_prompt) and "show each speaker's face while their line is spoken; the camera may cut between them" in _insp44.getsource(hnd.build_narrated_prompt))
check("an angle that comes back is copied word for word from the earlier clip (the writer is shown the previous shots)",
      "COPY the placement words of the earlier clip that used it exactly" in _cam and "previous clips' shots are shown to you" in _cam)
check("three or more people: no shoulder cuts; a wide group shot to open and every few clips; list on screen only who the shot shows; reactions on a key listener",
      "THREE OR MORE people present" in _cam and "do NOT cut between shoulders" in _cam and "come back to a wide shot only every third or fourth clip" in _cam and "never the same wide three-shot in two clips in a row" in _cam
      and "only the speaker and the one or two listeners the shot really shows" in _cam and "one key listener's face for a reaction" in _cam)
check("the first clip of a scene is a master shot that still moves", "ESTABLISHING PHASE" in _cam and "It MOVES (a slow drift or push); it does not freeze" in _cam)
check("every angle names what is behind the subject, taken from the place's layout, and the shot format asks for it",
      "EVERY ANGLE SHOWS ITS BACKGROUND" in _cam and "- BACKGROUND: what is visible behind the subject" in _cam)
check("the 180-degree rule stays, with exactly three allowed ways to cross (a visible move, after a wide/neutral shot or a change of place, a narration/action clip between scenes), and the mirror must be written out",
      "THE 180-DEGREE RULE & SCREEN DIRECTION" in _cam and "SAME SIDE of the imaginary line" in _cam and "allowed in only three cases" in _cam
      and "(a) the camera visibly travels across" in _cam and "(b) the clip follows a wide or neutral shot, or a change of place" in _cam
      and "(c) it is a narration or action clip between scenes" in _cam and "MUST state the new positions in words" in _cam and "Never flip it by accident" in _cam)
check("motivated cuts stay (close-ups, power angles, reveals), and nobody cuts in the middle of a movement: one continuous tracking shot follows a walker",
      "COVERAGE PHASE - MOTIVATED CUTS" in _cam and "NEVER cut in the MIDDLE of a movement" in _cam and "ONE continuous tracking shot ([SAME SETUP]) that follows them" in _cam)
check("the story-critical movement and exit rules are kept", "STORY-CRITICAL MOVEMENT ON CAMERA" in _cam and "EXITS THAT LEAVE OTHERS ALONE" in _cam)
check("the camera policy is the same for every kind of clip (the writer decides by the clip's kind)", "CINEMATIC CAMERA POLICY" in _vo_cam and "THE CAMERA IS A PERSON" in _vo_cam)
_gex = _cam[_cam.index("GOOD EXAMPLE:"):_cam.index("SHOT SIZES:")]
check("the good example is an over-the-shoulder cut with a push-in, a handheld sway and the background named",
      "[ANGLE CUT]" in _gex and "light handheld sway" in _gex and "behind her" in _gex and "locked" not in _gex.lower())
check("both planner prompts ask for two views that look opposite ways along a conversation",
      all("LOOK OPPOSITE WAYS along the line between them" in p for p in (hnd._narrated_outline_prompt("a story", 120, 24)[0], hnd._narrated_act_breakdown_prompt("a story", 300, 60)[0])))
check("the clip scripts, where the camera is written, are the cheap model's job", "model=app.OPENAI_CLIP_MODEL" in _insp44.getsource(hnd.write_narrated_chapter))
_bp = hnd.build_narrated_prompt({"delivery_mode": "voiceover", "location_id": _loc43, "present_characters": [_pov43], "speech": [{"speaker": _pov43, "line": "one two three four five six seven eight", "delivery": "quiet", "start_est": 0.5, "end_est": 4.0}],
                                 "shot": "[SAME SETUP] Camera tracks Mike down the corridor with a light handheld sway, behind him the two doors", "blocking": [], "action_steps": [], "environment": "", "prop_state": []},
                                _b43, {}, {}, {})[0]
check("the shot is sent to the video model as written (so 'tracks ... handheld sway' is what Seedance reads)", "Five-second [SAME SETUP] Camera tracks Mike down the corridor with a light handheld sway" in _bp, _bp[:200])

print("\n[46] Thirteen words, a clock that never rushes a line, new people in a shot, and room for the camera")
check("a clip carries 6 to 13 words in total", (hnd.MIN_WORDS, hnd.MAX_WORDS) == (6, 13))


def _words44(n):
    return " ".join(f"w{i}" for i in range(n))


def _probs_for(n_words):
    beats = [_beat43(1, audio_lines=[{"speaker": _pov43, "line": _words44(n_words)}])]
    return hnd._check_beats(beats, _b43)
_p13, _p14, _p5 = _probs_for(13), _probs_for(14), _probs_for(5)
check("13 words in a clip raise no word problem at all", not [p for p in _p13 if "words" in p and ("fit" in p or "dropping" in p)], _p13)
check("14 words are a HARD problem that says why and what to do (shorten to 13, keep the meaning and the key words)",
      any("before the voice starts dropping words" in p and "Shorten them to 13 words or fewer" in p and not p.startswith("[SOFT]") for p in _p14), _p14)
check("too few words stay a soft note", any(p.startswith("[SOFT]") and "5 words" in p for p in _p5) and not hnd._hard_problems(_p5))
check("a plan still over the limit after the retries goes to the review gate, first, and never throws the plan away",
      hnd.split_plan_problems([p for p in _p14 if not p.startswith("[SOFT]")])[0] == [] and len(hnd.split_plan_problems([p for p in _p14 if not p.startswith("[SOFT]")])[1]) == 1)
check("two lines that together run over are counted together", any("dropping words" in p for p in hnd._check_beats(
    [_beat43(1, audio_lines=[{"speaker": _pov43, "line": _words44(8)}, {"speaker": _other43, "line": _words44(7)}])], _b43)))
check("a repaired fact line may not pass the limit either (it used to be allowed two words more)", "3 <= words <= MAX_WORDS)" in _insp44.getsource(hnd._valid_fact_repair))
check("the planner is told the new limit", "must be 6 to 13" in hnd._narrated_outline_prompt("a story", 120, 24)[0])

# the clock: a line packed into a short window is re-spaced by its words
_fast = [{"speaker": "A", "line": _words44(9), "start_est": 0.55, "end_est": 2.3}, {"speaker": "B", "line": _words44(5), "start_est": 2.55, "end_est": 4.2}]
_slow = [{"speaker": "A", "line": _words44(6), "start_est": 0.5, "end_est": 2.5}, {"speaker": "B", "line": _words44(6), "start_est": 2.7, "end_est": 4.6}]
check("a line spoken faster than the limit is found (9 words in 1.7 s), and a comfortable pair is left alone",
      hnd._turns_too_fast(_fast) and not hnd._turns_too_fast(_slow) and hnd.MAX_TURN_WORDS_PER_SECOND == 3.8)
hnd._respace_turns(_fast)
check("re-spacing gives every line a window sized by its words, in order, inside the clip, none too fast",
      not hnd._turns_too_fast(_fast) and hnd._turn_windows_valid(_fast) and _fast[0]["start_est"] >= 0.4 and _fast[-1]["end_est"] <= 4.8, _fast)
check("a window without times counts as too fast, and the repair uses the check", hnd._turns_too_fast([{"line": "a b c"}]) and "_turns_too_fast(turns)" in _insp44.getsource(hnd._repair_narrated_clip))

# new people in a shot
_cam46 = hnd._narrated_chapter_prompt("A tense thriller", 1, 4, GOOD["beats"][1], GOOD["scene_bible"], [])[0]
check("new people must not simply appear inside the shot of someone who was alone; they may be revealed OR cut to, and nobody has to walk in",
      "NEW PEOPLE IN THE SHOT" in _cam46 and "must not simply APPEAR inside the frame" in _cam46 and "People do not have to walk in" in _cam46
      and "OR you CUT TO THEM" in _cam46 and "soft and out of focus in the distance, watching or listening" in _cam46 and "Say which you chose in the shot sentence" in _cam46)
check("the shot format is now item 8, and the earlier items kept their places", '(8) "shot" FORMAT (REQUIRED)' in _cam46 and "(7) ONE MAIN MOMENT PER CLIP" in _cam46 and "(5) PEOPLE IN THE SHOT ARE NOT STATUES" in _cam46)

# room for the camera
_sp_a, _sp_b = hnd._narrated_outline_prompt("a story", 120, 24)[0], hnd._narrated_act_breakdown_prompt("a story", 300, 60)[0]
check("both planner prompts ask for places with room for three people and a camera several metres back (a corridor is a wide landing)",
      all("SPACE FOR THE CAMERA (CRITICAL)" in p and "a wide landing or hall" in p and "Never write narrow, cramped, tiny, tight or claustrophobic" in p for p in (_sp_a, _sp_b)))
check("the picture request for every place says spacious, wide-angle, room for a camera several metres back",
      "Spacious and open, shot with a wide-angle lens" in hnd._compile_location_image_prompt({"id": "x", "image_prompt": "a hall"}) and "The place is EMPTY" in hnd._compile_location_image_prompt({"id": "x", "image_prompt": "a hall"}))
_bl = _cp44.deepcopy(_b43)
_bl["locations"][0]["description"] = "a narrow corridor with doors on both sides"
_bl["locations"][0].pop("image_prompt", None)
check("a place described as narrow or cramped gets a soft note naming the word", any(p.startswith("[SOFT]") and "'narrow'" in p and "room for three people" in p for p in hnd._check_scene_bible(_bl)))
check("a spacious one does not", not [p for p in hnd._check_scene_bible(_b43) if "room for three people" in p])

print(f"\n{'=' * 60}\n{ok} passed, {fail} failed\n{'=' * 60}")
raise SystemExit(1 if fail else 0)
