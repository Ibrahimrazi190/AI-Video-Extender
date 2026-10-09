# Story Delivery plan (v3)

Status: **Phase 1 (Story Delivery) is BUILT and tested offline (2026-10-08); everything else in this file is still
design.** See "Build status" below. v1 and v2 of this file were broader (Director chat, connectivity, long
form). v3 is rewritten around the problem you named: **the story was not delivered through the dialogue.** Everything
else is kept short in section 9. No OpenAI or kie.ai call was made to write this; the evidence comes from stored data
and the files you shared. Numbers marked *(est.)* are estimates.

## Decisions so far (yours)

1. Clips stay **5 seconds**. 2. First-person narration is **always on**, at **25-35%** of spoken words.
3. The story **ends automatically** (a plan concludes only if its runtime is at least 30 minutes; otherwise it ends on a
   cliffhanger). 4. The Director lives in the **Python app**. 5. **One universal engine**, no per-genre code.
6. **Pilot render agreed**: the first 2 clips at 480p, then ask. 7. Test **batched shot writing at 2 clips per call**.
8. **No tests that cost OpenAI credits** until you say so; everything below is offline until then.

---

## Build status: Phase 1, Story Delivery (built 2026-10-08, offline only)

**Nothing here has been run against OpenAI or kie.ai.** It was built and tested with mocks and with the stored first run:
471 offline checks pass (the earlier 385 untouched, plus section `[31]`). The containers mount the Python files, so a
restart picks the code up (`docker-compose restart`; a `.env` change such as `OPENAI_CLIP_MODEL` needs
`docker-compose up -d --force-recreate`).

| Piece | Where | What it does |
|---|---|---|
| Delivery map in the plan | `DELIVERY_SCHEMA`; fields added to `OUTLINE_SCHEMA` and `ACT_BREAKDOWN_SCHEMA` | `story_in_five`, up to 16 `facts` (role, kind, key terms, owner, channel, deliver_at, deadline, repeat_at), `jargon`, written in the existing planning call (no extra call). Every beat also carries `function`, `turn`, `delivers`. |
| Planning instructions | `_delivery_plan_rule`, `_DELIVERY_WRITING_RULES`, `_facts_block` | The planners are told to produce the map with deadlines scaled to the runtime; each beat-writing batch is told which facts it must deliver, what the audience already knows, which questions are still open and which jargon to explain. |
| Free checks | `_check_delivery_plan`, `_check_delivery_beats`, `_repair_delivery` | HARD only when an assigned fact's key terms are missing from its clip (and for an unsound map: five sentences, real owners, clip numbers, a `want`, no planted question that names a reserved reveal). Ownership, jargon, repeats, treading water, the timetable and the narration band are soft. A plan with no map (an older job) is skipped. |
| Repair with a hard stop | `_RepairBudget`, `PLAN_REPAIR_BUDGET_TOKENS = 60,000` | Every retry and rewrite of one plan draws on one budget. When it is spent the planner stops asking and the rest is reported (`_soften_delivery`), never fatal. Proven with a mock that fails forever. |
| Blind reader and report | `blind_read`, `check_blind_answers`, `plan_delivery_report`, `delivery_transcript` | One cheap call reads only the spoken script and retells the story; code checks which intended facts it recovered. The report also holds the stats, the notes and the **dialogue-only page**. It never raises. |
| Stored with the job | `app.py`: `Job.delivery`, `Job.plan_report`; `_generate_narrated_plan`; `_save_master_plan_file` | Saved in `master_plan.json`; the dialogue-only page is written to `plan_dialogue.txt` in the job's media folder. Continuations get the map (what is known, what is still open). |
| `/enhance-prompt` | `app.py: _enhance_prompts` | Has a real narrated-drama mode, allows first-person `(VO)` lines, and asks for the story to be said plainly (want, obstacle, stakes, backstory, secret).

**Retries (added after your question): a missing fact never costs a whole-act retry.** The facts due in a batch are listed
in the prompt with their key terms, a draft line and a self-check. If a clip still does not say its fact, that is a SOFT
note for the batch and `_repair_missing_facts` rewrites just that beat with **one small call on the cheap model**
(about 2k tokens, a fraction of a cent), given the line before, the line after, the fact and its draft line. The rewrite
is accepted only if it keeps the speakers in the cast, a voiceover beat to one narrator line, one or two lines for a
dialogue beat, a sane word count, the key terms, no reserved reveal term, and the fact's owner speaking. If it does not,
the beat is left as written and the gap is reported. Whole-act retries now happen only for structural problems (as
before), still capped by the repair budget. Not measured on a real model.

**Plain language for EVERY line, not only the key facts (added after your examples from clips 1, 9, 10 and 11).** The delivery
map covers 6-10 facts; the other 70-90 lines were still poetic. Cause found: the old "plain words" rule's own GOOD examples were
figurative ("Tonight he hands me a pen" was one of them, "My ship cleared while his city drowned" another), the Don's premise
asked for "sharper" lines and gave the pen line as a sample, and nothing checked a line. Now: (1) a **PLAIN LANGUAGE TEST** in the
planner and beat-writer prompts (a viewer with basic English, with no picture, must understand each line at first hearing;
literal, never figurative; say who and what; say what a meaningful act means, such as returning a ring; plain beats poetic even
when the premise asks for sharper lines) with BAD -> GOOD examples taken from your own examples; (2) `plain_pass_plan`: after the
plan, **one cheap Luna review per 15 beats** reads every spoken line and rewrites those that are not plain, keeping the speaker, the
meaning and the attitude, and a rewrite is thrown away if it loses a fact's key terms, uses a reserved reveal term, adds a
semicolon or grows past the word budget; (3) the plan report lists every rewrite with its before and after (`plain_pass`) and the
dialogue-only page shows the plain lines; (4) the `/enhance-prompt` premise is asked for plain literal English too. Switches:
`PLAIN_LANGUAGE`, `PLAIN_PASS`. About 4-5 small calls (a few cents at most). Not measured on a real model: it can over-simplify,
which is why every rewrite is shown to you.

**Retries run on the cheap model (Luna) and cannot change what was fine.** The first write of every plan part stays on
`gpt-5.5` (it invents the story and every spoken line). Every retry (act breakdown, beat batches, the single-call plan, the
reveal-leak rewrite, the continuation) runs on `OPENAI_CLIP_MODEL`, and its answer is **merged in code**: only the clips (or
the part of the plan: bible, delivery map, acts) that a broken rule names are taken from it; every other beat is kept exactly
as `gpt-5.5` wrote it, even if the cheap model rewrote it. A retry costs about half a cent instead of about $0.27 for a
17-clip batch. A re-run after a cut-off reply is the first write again, not a repair, so it stays on `gpt-5.5`.
`RETRY_ON_CLIP_MODEL = False` puts retries back on the story model. The continuation retry used to re-send an identical
request; it now says what was wrong. Batch sizes are settings (`BATCH_MAX_CLIPS = 20`, `BATCH_MIN_CLIPS = 6`).

**Taken from the replica (its dialogue control):** per-clip key dialogue decided at plan time (our `line` per fact),
character `motivation`, `relationships` and `speech_style` (the beat writer now sees them), "something new in every clip"
(our `function` and `turn`) and a per-clip purpose. Not taken: its no-narration rule (our mode is narration-styled by
decision), its `endingHook` per clip, and its "last 8 lines" hand-off (ours passes the last 4 beats).

**Switches:** `STORY_DELIVERY = False` removes every delivery instruction and check (and every older sentence that
pointed at one); `BLIND_READ = False` skips the one cheap call; the older prompts' behaviour is otherwise unchanged.

**Contradictions found and removed** (the prompts had drifted across earlier implementations): stale "micro-cycle"
wording (docstrings, a print, and a retry instruction that contradicted "scenes play"); narration told to say what she
"will not say aloud" while delivery needs her to say it; "short, hard lines" with a three-speaker quick-fire example while
delivery needs one or two plain lines; "a line may only use what the audience already knows" while a question must be
planted; the clip writer told "you do not know the future" while its premise describes the whole story; and
`/enhance-prompt` banning internal thoughts for a mode made of them. A test now keeps these out.

**On your real first run** (stored beats, the Don's facts written by hand): the checks flag 4 undelivered facts (the Rossi
alliance, what Elena wants, why the ships matter, no planted question), 2 unexplained terms ("Rossi", "manifests") and
narration at 39% against the 25-35% target.

**Ending rule (built at prompt level):** under 30 minutes a plan is episode one and ends on a cliffhanger; from 30 minutes (`CONCLUDE_AT_SECONDS = 1800`) it is told to tell a whole story and end it. Not built: a code check that every thread is paid.

**Not yet done:** a real plan run (needs your OK, about $1-3), the dashboard view of the report, function/turn
enforcement beyond soft notes, and Phases 2-7 below.

---

## 0. The problem in one page

You said it plainly: the Don's run did not make clear *what the story was*, while the replica's dialogue made the story
obvious: the girl thinks all rich men are trash; a rich man disguises himself as a poor labourer; she teaches him to
work; they fall in love. I tested that against the data.

**The first run's spoken lines, read as a stranger would** (43 rendered clips: 56 lines, 355 words, 38% narration, 6
clips with no words). A stranger gets "a woman is fired by a mobster for a rival, then ruins him." They do not get:

| What the audience must understand | Where it is first said, and how |
|---|---|
| She served him for three years | clip 1, narration: **clear** |
| He is firing her to please a rival family | clip 7, "Rossi buys peace. Your job is done." (Who is Rossi? never said): **partial** |
| **What Elena wants** | **never said**; only shown |
| Why the ports and "Vance Maritime" hurt him | clips 13-18, "Vance Maritime was mine to command again" / "I used phone calls": **never explained** |
| The secret: she took the blame for him | clip 34 of 43, from the *villain*, as "false customs manifests": **jargon, once** |
| Marco is secretly hers | "Still fetching for her?", "Not without her clearance": **never plain** |
| What Lorenzo stands to lose | clip 43: "Name your price." / "You can't.": **cryptic** |

Compare the replica's script, where every fact is said out loud, plainly, in a clash, by the person who has the stake:

- "Not to men who think they can buy everything." (her stance)
- "Why does that market girl hate rich people so much?" (the hook question)
- "A wealthy developer took her father's farm. He died of heartbreak." (the cause)
- "Then she'll never meet Ethan Blackwood." (his plan, said aloud)
- "Rich people never see us, Jack... All of them." / "Not all of them are like that." (the wound, and the irony)

Both scripts use short lines (about 6 words ours, 8 theirs). **The difference is not length, it is what each line is
for.** Ours are comebacks and mood. Theirs state wants, stakes, history and the lie.

---

## 1. What "story delivery" means

A viewer who sees only the **spoken script** (no pictures) should be able to say, in five sentences:

1. **Who** the protagonist is and **what they want.**
2. **What stands in the way.**
3. **What they do about it** (the plan, the lie, the choice).
4. **What it costs / what is at stake.**
5. **Where it stands now** (or the open question the episode ends on).

Every fact behind those five sentences is a **must-understand fact**. There are three kinds, and the third resolves
the tension with secrets and reveal order:

| Kind | Rule | Example (the Don) |
|---|---|---|
| **State now** | said plainly, early, by the person with the stake | "Three years I kept you out of prison." |
| **Plant the question** | the audience is told *that* a secret exists, in plain words, but not the answer | "He still doesn't know what I paid to keep him free." |
| **Pay later** | the answer is said plainly at its planned beat | Camilla, clip 34: "She forged the customs papers and took the charge for you." |

**Say the question early, delay the answer.** Delivery never means spoiling a twist; it means the audience always
knows what is at stake and what they are waiting to learn.

### 1.1 A delivery timetable (universal; starting values)

Derived from the example (want by clip 2-4 of 12, the lie at clip 5, the wound at clip 9) and scaled to any runtime.
For 60 clips the clip numbers are in brackets. **Calibrate on real plans.**

| By | The audience must know |
|---|---|
| ~10% [clip 6] | who the protagonist is, what they want, what is threatened, the inciting problem |
| ~25% [clip 15] | what stands in the way, and that there is a secret or a lie (planted as a question if hidden) |
| ~40% [clip 24] | what the protagonist is doing about it, the premise engine said aloud |
| ~75% [clip 45] | the stakes restated in new words, the wound or the cost |
| 100% [clip 60] | the ending state, or the exact open question for the next episode |

And **say it twice, two ways, about 15 clips apart.** A fact heard once at clip 7 is gone by clip 30.

---

## 2. Why our pipeline does not deliver (from the code and the data)

1. **Nothing in the plan says what the audience must understand.** The planner is asked for beats, modes and speech
   budgets. There is no list of facts, no owner, no deadline, so nothing can be checked.
2. **The prompts reward oblique lines.** The beat writer is told narration "says what she wants, what it costs, what
   she will not say out loud" and that "short, hard lines land". The Don's premise adds "quiet, controlled, nothing
   shouted". The model obeyed: stoic *delivery* became cryptic *content*.
3. **Narration reports.** 38% of the words, mostly describing the picture ("Camilla watched like she had already
   bought the room"; "I heard her laugh, and knew she was cornered").
4. **Jargon is never glossed.** "Rossi", "manifests", "ledgers", "the ports", "the dark" are used as if known.
5. **Reveals are delivered once, by the wrong person.** The key backstory is stated at clip 34 by the antagonist in one
   line, and the audience never heard the question before it.
6. **Our checks cover everything except this.** There are validators for continuity, reveal order, speakers and
   props; none asks "did a character say what the story is?"

Not the cause: word budget. Ours is 99 words/min against the example's 80, and the cap is 15 words per 5 s clip. We have
room to say more.

---

## 3. How the example and the replica deliver

- The replica's plan prompt requires "a new piece of information, conflict or emotional turn in **every** clip" and
  "tell it through people, not narration"; each outline entry has `events`, `keyDialogue` and an `endingHook`.
- Its clip writer is told "this is a script writer: people TALK" and "do not repeat information the viewer already
  knows".
- The story itself very likely arrived already structured (an older run of the same story has the same twelve-beat
  skeleton; the premise was probably developed with Claude, as you remember). So the Director's first job is to *build
  that structure with you*, and the pipeline's job is to make sure it reaches the audience as speech.
- Its limits: no reference images (poor consistency), no check that facts reach the dialogue. It got lucky because the
  premise was already built on plain conflict.

---

## 4. The design

### 4.1 Story Card (new, a short call or part of an existing one)

Fields: `logline`, `story_in_five` (the five sentences of section 1), `tone`, `ending` (cliffhanger or resolution by the
runtime rule), `look`. The Director shows it at the first gate. **Tone note:** if the premise says "quiet, controlled",
the Card records that as *delivery* ("low-voiced, never shouting") and states explicitly that the *content* of every key
line is plain.

### 4.2 Must-understand facts and the delivery map (new)

```
fact:   { id, kind: state_now | plant_question | pay_later, text, key_terms[], owner (speaker),
          deliver_at (beat), deadline (beat), repeat_at (beat), channel: dialogue | narration }
jargon: [{ term, plain_gloss }]      # words the audience will not know: "manifests", "Rossi alliance"
```

Written in the **act-breakdown call** (so no extra call): 6-10 facts for a 5-minute film (~600-900 output tokens). The
Don, respecting your reveal order, would map like this (**the lines are my illustrations, not pipeline output**):

| Fact | Kind | Owner, channel | Beat | Illustrative plain line |
|---|---|---|---|---|
| Three years as his fixer | state now | Elena, narration | 1 | "For three years I cleaned up his mess. Tonight he hands me a pen." |
| He is replacing her for the Rossi alliance | state now | Lorenzo, dialogue | 3-4 | "The Rossis want you gone. Their alliance is worth more than you." |
| What she wants: take from him everything he relies on | state now | Elena, dialogue | 10-12 | "You're cutting loose a cost. You've cut the only wall between you and your enemies. Watch." |
| Her power: her family's ships carry his shipments | state now | Elena, narration | 13 | "Every load he owns crosses water my family controls. I only had to say so." |
| A secret he never knew | plant question | Elena, narration | 12 | "He still doesn't know what I paid to keep him free." |
| Marco is secretly hers | state now | Elena, narration | 25 | "Marco has been my man inside his house for two years." |
| What she did, and who set the ambush | pay later | Camilla, dialogue | 34-35 | "She forged the customs papers and took the charge for you. And I sold your route to the men who ambushed you." |
| His regret, her answer | pay later | Lorenzo / Elena | 55-58 | "I can't rule without you." / "You ruled by fear. Fear can't buy me back." |

### 4.3 Writing rules (added to the beat-writing prompts; all genre-neutral)

1. **Exposition through conflict.** Facts are demanded, refused, accused, confessed: never announced to nobody.
2. **Say the want.** The protagonist states what they want and what it costs them, plainly, once early.
3. **Name the stakes aloud** whenever they change.
4. **Gloss every term on first use**, in one plain phrase, spoken (the jargon list).
5. **A comeback must also carry information** (an answer plus a new fact). A line that only sounds sharp is rewritten.
6. **One new fact per line, at most two per clip.**
7. **Plant questions, delay answers.**
8. **Repeat the key facts** once more in different words (the `repeat_at`).
9. **Subtext comes after text:** oblique lines are allowed once the fact is established.
10. **Narration states motive, fear, decision, backstory.** It never describes what the picture shows. It is the cheapest
    channel for early backstory in a few plain words, and the home of dramatic irony.

### 4.4 Code checks (no model; free)

- every fact has `deliver_at <= deadline`, an owner who exists, and is placed in a beat whose speaker is that owner;
- the beat's spoken lines contain the fact's `key_terms` (a fact assigned to a beat that never says it is flagged);
- every jargon term is glossed in the same or the previous line on its first spoken use;
- a `plant_question` precedes its `pay_later` by at least N beats (never the same clip);
- a `repeat_at` exists for every fact that is needed after the 60% mark;
- the timetable of 1.1 is met (a soft warning, with the missing fact named);
- narration share and "describes the picture" heuristics feed the pacing report (soft).

### 4.5 The blind-reader test (the real measure of delivery)

Before any clip script or render, the Director builds a **dialogue-only transcript** (speaker and line, in order; no
visuals, no premise) and asks a cheap model to:

1. write the story in **five sentences**, and
2. answer six fixed questions: *Who is the protagonist and what do they want? What stands in the way? What is the secret
   or lie, if any? What changes between the two main characters? What is at stake? How does it end or what is left
   open?*

Code then checks that each intended fact's `key_terms` appear in the reader's answers. Missing facts are flagged by
name, e.g. "reader did not learn what Elena wants". The transcript itself is also shown to you as a page to read. **If
you can follow the story from that page alone, a viewer can.** The reader is deliberately a *less informed* reader than
the writer, which is the point. Cost: about 1k tokens in and 0.4k out: roughly a cent *(est.)*.

### 4.6 Repair, with a hard stop

Failed checks name the fact and the beat; the beat writer is re-asked **only for those beats**, with the fact, its
`key_terms` and the rule it broke. **Each flagged batch is rewritten at most once**, the blind-reader runs at most
twice in total, and a **repair budget of about 60k tokens per plan** (about $1 on the story model) ends the loop: what
is still wrong is shown to you at the gate. We already log every call, so the budget is simple to enforce, and an
offline mock that fails every attempt will prove it stops.

### 4.7 Where it plugs into the code

- `ACT_BREAKDOWN_SCHEMA` and `_narrated_act_breakdown_prompt`: add `story_in_five`, `facts[]`, `jargon[]`.
- `OUTLINE_SCHEMA` beats: add `delivers[]` (fact ids), `function`, `turn` (section 8).
- `_narrated_act_beats_prompt`: pass the facts due in this batch with owner, channel, key terms, and the writing rules
  of 4.3; keep the existing reveal-order reservation (it is the "pay later" lock).
- `_check_beats` / `_check_act_beats`: add the checks of 4.4 (hard only for missing delivery and unglossed jargon).
- new `blind_read(transcript)` and `check_delivery(plan)` functions; a `plan_report` the dashboard shows at the gate.
- `/enhance-prompt` writes `story_in_five` and the facts when the premise is short.

### 4.8 What you see

1. **Story Card** with the five sentences (approve or edit).
2. **Delivery map** (who says which fact, when) in plain language (approve or edit).
3. **Blind-reader result** and the **dialogue-only page** before anything is rendered.
4. **Pilot render** of the first 2 clips only after 1-3 pass.

---

## 5. Cost and tokens *(est.)*

| Addition | Tokens | Story-model cost |
|---|---|---|
| facts + jargon + story_in_five in the breakdown call | ~0.8k out | ~$0.03 |
| facts passed into each beat call | ~0.3k in per call | ~$0.01 |
| function/turn labels (section 8) | ~1.5k out | ~$0.05 |
| blind reader | ~1.4k total | ~$0.01 |
| targeted rewrites (0-2 batches) | ~11k each | $0-0.4 |
| **Per plan** | **~5k + rewrites** | **~$0.1-0.5** |

Against a first-run OpenAI bill of $7.56 this is small; against the cost of rendering a story nobody can follow, it is
negligible.

---

## 6. How we will know it worked (acceptance)

**Offline, free (can be done now once you give the green light):**
1. A replay of the stored first-run lines through the new checks **flags** the gaps in the table of section 0 (want
   never said, jargon unglossed, secret delivered once by the antagonist).
2. Unit tests for every check in 4.4, with mocks; a mock that fails forever proves the repair budget stops.
3. The Don's delivery map (section 4.2) validates against the stored beats' structure.

**Needs OpenAI credits (only when you say so; one plan-only run, about $1-3):**
4. On the Don's premise, a new plan passes every code check and the blind reader recovers at least 80% of the facts.
5. **You** read the dialogue-only page and can follow the story (the test that matters).
6. A different premise (family betrayal or comedy) passes the same checks, to prove the engine is universal.

**Needs kie.ai credits (yours):** the pilot render of 2 clips confirms look, faces and voices.

**No guarantee** that the model writes great dialogue. What this gives you is a **measurable gate before any render**:
facts that never reach the audience are found in a plan, not in a finished video.

---

## 7. Narration, tone and your premise style

- Narration stays always-on at 25-35% of spoken words, but its job changes from describing to **delivering**: motive,
  decision, backstory, the plan, dramatic irony. A narration line that merely restates the picture is flagged.
- A stoic premise ("quiet, controlled") is respected as *how lines are said*, never *what they say*.
- First and last voiceover lines answer each other (the bookend), which also helps closure.

---

## 8. Drag and hollow (the second delivery problem), kept small

Two short labels per beat, written at planning time: **function** (hook, clash, reversal, reveal, bonding, wound,
promise, collision, cost, aftermath, escalation, cliffhanger, resolution) and **turn** (one sentence: what is different
afterwards). Code flags a beat with no turn, and runs of beats with the same function, place and speakers and
near-identical turns (the 12 clips of one person on a phone). This is the replica's "something new in every clip" rule,
made checkable. It is cheap and supports delivery: a beat with a turn is a beat with something to say.

---

## 9. Other workstreams (kept short, lower priority than delivery)

| Topic | Where it stands |
|---|---|
| **Connectivity between batches** | **Smaller than I first claimed.** The clip writer already sees the whole premise, a summary of every earlier beat and the last 3 clips (your clip-17 trace). The beat-planning calls see the premise and act summaries but only the last 4 beats of what was written. Worth doing: a compact recap of every earlier beat for the beat writer, free code checks at the seams, the thread ledger, and an ending contract for final episodes (every opened thread paid; a cliffhanger episode names the threads it leaves open). Whole-story model review: off by default, run only when code checks warn. |
| **Ending rule** | A plan concludes only if its runtime is at least 30 minutes; otherwise a cliffhanger. Extensions: the dashboard suggests concluding after 30 minutes total; an explicit "final episode" overrides. 30 minutes = 360 clips; defaults (4 acts, 4-8 locations, cast size) and the hierarchy must scale; render time ~15 h *(est.)*. |
| **Batched shot writing** | Test at **2 clips per call** (two Seedance prompts per call), behind a switch, offline first. Raw input per clip ~40% lower, full-price part ~20% lower *(est.)*. |
| **Two timed shots per 5 s clip** | The replica gives Seedance Mini at most 2 shots, 2 characters, 2.0 words/s. Our action timeline (`TIMED_ACTIONS`) is the first step. Needs a kie.ai test (yours). |
| **Look profiles** | The user's style choice feeds grade and lensing only; the avoid-list is generated from the look so it never contradicts it (the PDF's "neon banned, neon required" bug). |
| **Director chat** | Typed operations (edit a line, a beat, the camera, the look, recast, regenerate, extend) over the existing plan/approve/replan/extend/regenerate routes, local edits only, stale-marking. Python app. |
| **Replica notes** | It plans the whole runtime in one call (a bible plus one outline entry per clip with an `endingHook`) and writes clips 4-6 per call with a compact end-state; the 3-minute script cost 4 calls and 33.5k tokens on gpt-4.1. Its look comes from a pasted style preset that its own avoid-list contradicts. Reference only. |
| **Already built this session** | token and cost cuts, loop protection, action timeline, "episode one" planner prompts (`CHAT_LOG_token_cost_and_video_prompting.md`). |

---

## 10. Roadmap

| Phase | What | Offline? | Spend later |
|---|---|---|---|
| **1: Story Delivery** | **BUILT 2026-10-08 (offline).** Delivery map, facts and jargon, writing rules, code checks 4.4, blind reader and dialogue-only page, repair budget, plan report, function/turn labels, prompt contradictions removed. Not built from 4.1: a separate Story Card call (the five sentences live in the delivery map) | **Yes**, built and tested with mocks and a replay of stored lines | one real plan, ~$1-3 (needs your OK) |
| 2: Connectivity (small) | recap of all earlier beats for the beat writer, seam checks, thread ledger, ending contract | yes | none |
| 3: Batched shots (2 clips) + state not history | behind a switch | yes | a replay, cents |
| 4: Look profiles | generated avoid-list, validator | yes | none |
| 5: Director backend and chat | typed operations, gates | yes | cents |
| 6: Two-shot 5 s clips and join modes | compiler, schema | prompt diffs | kie.ai credits (yours) |
| 7: Long form | hierarchical plan, episodes, checkpoints | yes | OpenAI, then credits |

---

## 11. Risks and open decisions

**Risks:** the model may state facts plainly but flatly (the rules must keep it dramatic: facts live inside conflict);
over-explaining can feel on-the-nose (the check is "delivered once, plainly", not "said constantly"); the timetable is
calibrated on one example; a blind reader can pass a script that a human finds dull (hence your read of the page); a
premise that is itself oblique will resist (the Director flags it at the Story Card).

**Decisions for you:**
1. Is the five-sentence **Story Card** plus the **delivery map** the right gate for you to approve before anything is
   written?
2. Should the **dialogue-only page** be part of every plan (my suggestion), or only when you ask?
3. May I start **Phase 1** (offline only: no OpenAI or kie.ai calls)? I would wait for your green light.

---

## Appendix. Evidence

- First run (job `d54e40da`), 43 rendered clips: 56 spoken lines, 355 words, 38% narration, 6 wordless clips; first
  plain statement of each fact as in section 0 (my reading of the stored lines).
- `script.pdf` ("A Market for Hearts"): 31 lines, 240 words, 0 narration, 46 shots.
- Replica (`Replica Pipeline/server/services/storyEngine.js`, `promptRenderer.js`, saved projects): planning and clip
  prompts quoted in section 3; "A Market for Hearts" project on gpt-4.1: 4 calls, 33,521 tokens.
- Code references: `_narrated_outline_prompt` and `_narrated_act_beats_prompt` (section 5 "THE SPOKEN WORD IS DECIDED
  HERE", "PLAIN, SPEAKABLE WORDS", narration "says what she wants... what she will not say out loud"),
  `MIN_WORDS`/`MAX_WORDS` (6-15 per clip), `_check_beats`, the reveal ledger.
- Your clip-17 trace: the clip writer already receives the full premise, a one-line summary of every earlier beat and
  the last 3 clips in detail.
