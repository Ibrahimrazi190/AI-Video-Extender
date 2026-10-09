# Chat log: OpenAI token cost and video prompting (started 2026-10-08)

A running log of everything changed, decided and found in this working session. Newest entries go at the bottom of
each section; a new dated entry is added whenever something else changes. For the project-wide history see
`PROGRESS.md`.

Files touched so far: `.env`, `app.py`, `hybrid_narrated_drama.py`, `verify_narrated_fixes.py`, `PROGRESS.md`
(and this file). Nothing has been committed from this session. The code is on GitHub from before the changes, so
`git diff` shows exactly this session's work and `git checkout -- <file>` undoes any one file.

**Status of everything below: written and tested offline only. No live run has happened since these changes.**
The containers still run the old image until `docker-compose up -d --build`.

---

## 1. Why this started

First 5-minute run (job `d54e40da…`, 43 of 60 clips) read in Langfuse:

- 465,198 input tokens across 52 OpenAI calls; the clip writer (`narrated_chapter`) was 424,725 of it over 46
  calls (43 clips + 3 retries) = **9.2k per call**.
- Cached input was only 18,432 (4%): that run pre-dated the 10/07 prompt-caching layout, which has not run live yet.
- 177,351 output tokens (91,625 visible + 85,726 reasoning), 6x the input price: output was 69% of the $7.56 bill.
- Clip 43 used **36,408 tokens against ~14k for a normal clip**: it wrote the same `prop_state` entry 563 times.
  Clip 42's diary already repeated one prop 5 times, and that was pasted into clip 43's prompt as history, so the
  loop fed itself.

## 2. Changes made

### 2.1 Models

| Change | File | Notes |
|---|---|---|
| `OPENAI_CLIP_MODEL=gpt-6-luna` | `.env` line 15 | Clip writer (`narrated_chapter`) and supervisor. Showrunner (`narrated_act_breakdown`, `narrated_act_beats_N`, `narrated_outline`, `narrated_continuation_beats`) stays on `OPENAI_MODEL` (gpt-5.5). Luna: $0.10 in / $0.01 cached / $0.50 out per M tokens (OpenAI model page). **Takes effect only after `docker-compose up -d --force-recreate`** (env_file is read at container creation). |
| gpt-5.5 cached input price $0.50/M | `app.py` `OPENAI_PRICES` | Was unknown and charged at the full $5. Source: OpenAI's gpt-5.5 model page. Cost estimate only. |

Reasoning effort: both models accept `none/low/medium/high/xhigh` (Luna also `max`), default `medium`. **No
`reasoning_effort` is sent yet.** Decision: leave gpt-5.5 alone (the showrunner writes every spoken line and is only
~$1.08/run); a Luna test at `none`/`low` is still to do.

### 2.2 Runaway protection (so a loop like clip 43 cannot run on)

| Change | File | Notes |
|---|---|---|
| `max_completion_tokens` argument, `OpenAIOutputCut` error | `app.py` `_ask_openai_json` | Cap includes reasoning tokens. A reply with `finish_reason == "length"` raises `OpenAIOutputCut` (a `ValueError` subclass). Cap is only sent when given, so every other caller is unchanged. |
| Ceilings: `CLIP_MAX_OUTPUT = 16000`, `PLAN_MAX_OUTPUT = 32000`, `SUPERVISOR_MAX_OUTPUT = 8000` | `hybrid_narrated_drama.py` | A normal clip is ~3k and a normal act of beats ~5k, so these only bite on a runaway. |
| Clip writer retries a cut-off reply | `write_narrated_chapter` | Counts as a failed attempt, retried with a note ("kept repeating itself…"). If every attempt (`CHAPTER_RETRIES`) is cut, the error stands and the job stops before the clip is rendered. |
| `_ask_planner()` wrapper | `hybrid_narrated_drama.py` | All five showrunner call sites use it: capped, asked once more on a cut-off, still on the story model. |
| Supervisor tolerates a cut-off | `supervise_narrated_chapter` | Returns no notes instead of failing a clip. |
| Schema limits: `prop_state` ≤ props in bible, `blocking` ≤ cast size, `speech` ≤ 3, `action_steps` ≤ 16 | `_narrated_chapter_schema` | Enforced by the decoder, so a repeat loop in those lists cannot start. Not added when the bible has no props/cast. Checked against all 43 stored clips: none exceeds any limit (busiest real clip: 10 props, 4 characters, 2 turns, 10 steps). `maxItems` is supported in strict mode except on fine-tuned models (OpenAI structured-outputs docs). |
| `_props_line` shows one entry per prop | `hybrid_narrated_drama.py` | Backstop: a looped diary is not copied into the next clip's prompt. |

Honest note on the cap: with a cap alone, a loop costs up to 16k per attempt and can stop the job; the real fix is
the schema limit. The cap is a backstop against an unbounded call (up to 128k tokens on Luna, ~$3.84 on gpt-5.5).

### 2.3 Shorter history (input tokens)

| Change | File | Notes |
|---|---|---|
| `HISTORY_END_STATE_CLIPS = 1` | `hybrid_narrated_drama.py`, `_narrated_chapter_prompt` | Of the last 3 clips in the history, only the newest keeps its end state (poses, what each character knew, environment, prop diary). The older two keep shot, actions and speech. **Set it to 3 to restore the old behaviour.** On the stored run: ~449k → ~396k input tokens (-12%, approximate: counts use chars/3.6 and run ~15% high). |

Left alone on purpose: the "story so far" summary list, the rulebook, the 3-clip history window.
Considered and not done: cutting the summary list to 5 beats; dropping the whole-story premise from the clip
writer's system prompt (~1k tokens, and it contradicts rule 10 "you do not know the future"); shortening the camera
rule; a "delta" design where code carries continuity state. Revisit after the next real run.

### 2.4 Video prompting (what Seedance is sent)

| Change | File | Notes |
|---|---|---|
| Action steps sent as a timeline | `hybrid_narrated_drama.py`: `TIMED_ACTIONS = True`, `_timed_actions()`, `build_narrated_prompt` | Every step already had a `start_time` that was dropped when the prompt was built. The prompt now carries `Action timeline (seconds into the clip): 0-1s: … 1-2s: … 2-4s: … 4-5s: …`: whole seconds, contiguous from 0 to the clip end, steps in the same second share a range, the first range always opens at 0. Falls back to the old untimed `Actions:` sentence when there is nothing to time. **`TIMED_ACTIONS = False` restores the old behaviour.** On the stored run 39 of 43 clips get a timeline (4 have no steps); the prompt grows by ~50 characters. **Not yet rendered: whether it improves the video is unknown.** |

### 2.5 Tests and logs

| Change | File | Notes |
|---|---|---|
| New sections `[28]` (runaway protection, shorter history) and `[29]` (timeline) | `verify_narrated_fixes.py` | Suite went 321 → 352 → 366 → **385 checks, all passing** (by the end of 2.6). Run offline in a throwaway container: `docker run --rm -e REDIS_URL=redis://localhost:1/0 --env-file .env -v "<project>:/work" -w /work ai-video-extender python verify_narrated_fixes.py`. |
| Seven mocks widened for the `max_completion_tokens` keyword; the gpt-5.5 cost check updated for its cached rate | `verify_narrated_fixes.py` | |
| Entry "runaway protection and a shorter history" | `PROGRESS.md` | The timeline change is logged here, in this file. |

### 2.6 Episode one: play it out, end on a cliffhanger (A2 Part 2 from `FIRST_PRIORITY_IMPLEMENT.md`)

Why: the first run asked for a *complete* arc in 60 clips, so a ~20-minute plot was compressed (502 spoken words,
41% narration) and the middle act was unwatchable. The runtime is now treated as the opening movement of a longer
story, not a whole film squeezed to fit.

| Change | File | Notes |
|---|---|---|
| `EPISODE_ONE = True`, `_episode_one_rule()`, `_cliffhanger_final_rule()` | `hybrid_narrated_drama.py` | One shared rule in all three planners (single-shot outline, act breakdown, act beats): tell only as much story as will genuinely play in real time; never summarise, skip or rush events to reach an ending; if the premise holds more than fits, play the earlier events in full and stop at the strongest unresolved turn; end on a cliffhanger, not a resolution, goodbye or moral. **`EPISODE_ONE = False` restores the old prompts.** |
| Last act must stay open | `_narrated_act_breakdown_prompt` | The last act's `dramatic_question` must still be open at its end and its `summary` must name the cliffhanger. |
| The batch with the last clip ends the episode | `_narrated_act_beats_prompt` | Only the batch whose `end_clip` is the last clip gets "THESE BEATS END THE EPISODE": the last two beats leave the story open and the final beat is the cliffhanger itself. A continuation is the last batch of what exists, so it ends on a cliffhanger too. |
| "Generate the complete …" → "Generate the … for these N clips - episode one, ending on a cliffhanger" | the planners' user messages | |
| `/enhance-prompt` writes episode one for the dramatic modes | `app.py`: new pure `_enhance_prompts()`, endpoint calls it | For runtimes ≥ 100 s and every mode except Talking Head and Story Time: "EPISODE ONE of a longer story", about one major event per 60 seconds, no compressing further events, and Act 4 is "The Cliffhanger" (open, no resolution) instead of "The Climax & Resolution". Talking Head, Story Time and the ≤ 90 s branches are unchanged. The prompt building was moved into a function only so it can be tested without calling OpenAI. |
| New section `[30]` (19 checks) | `verify_narrated_fixes.py` | Suite now **385 checks, all passing**. |

**Not verified:** this is prompt wording only. Whether a real plan now plays out and ends on a cliffhanger needs one
plan generation to read (OpenAI only, about a dollar, no kie.ai). Known tension: a premise that itself prescribes
five acts of 12 clips and a closed ending (like "The Don's Greatest Regret") will pull against the new rule; the
enhancer is where an oversized premise is meant to be fixed, so enhance first, then read the plan.
Not built: A2 Part 1 (sequences as a validated `scene` / `bridge` field in the act breakdown).

### 2.7 Design document: Vibe Director, v2 (no code)

`VIBE_DIRECTOR_PLAN.md` was written from your example script (`script.pdf`, "A Market for Hearts"), then revised (v2)
after your decisions and after reading the replica pipeline (`Replica Pipeline/`, read-only; `.env` not opened).
Nothing in it is built, and no OpenAI or kie.ai call was made.

**Your decisions (2026-10-08):** clips stay 5 s; first-person narration is always on (the mode is narration-styled);
the story ends automatically but must be connected and end well; the Director lives in the Python app; the replica is a
reference for story logic only; no OpenAI-credit tests for now (offline checks only).

**What the replica showed (from its code and `server/data/projects.json`):**
- It plans the **whole runtime in one call** (a bible plus one outline entry per clip, each with an `endingHook`), then
  writes clips **4-6 per call**, each batch seeded with the outline slice, a compact end-state (`plotProgress`,
  `nextAction`, positions, props) and the last 8 dialogue lines. That is why its batches connect.
- The "A Market for Hearts" script cost **4 LLM calls and 33,521 tokens** on gpt-4.1 (our first run: ~640k tokens for
  3.6 minutes, about 16x more per second of film).
- For a Seedance Mini clip it allows at most **2 shots, 2 characters, 2.0 words/s**.
- Its weaknesses: no reference images (hence the poor consistency), the user's style preset pasted verbatim into the
  look while a separate rule bans neon (the contradiction in the PDF), a leftover hard-coded action template.
- The premise is not stored, but an older run of the same story already has the same 12-beat skeleton, so the story
  very likely came in with the premise (your Claude-developed story); the engine expanded it. Inference, not proof.

**What v2 adds:** a **connectivity contract** for the "second batch does not follow" problem (whole-story skeleton first,
batches that expand whole sequences, a recap block written by each batch, code validators at every seam including a
hook pick-up check, one whole-story review before rendering with targeted rewrites, an ending contract with a bookend
rule); **batch shot writing** (~4 clips per call, ~3-4x fewer clip-writer input tokens, est.); **two timed shots per
5 s clip**; an automatic **narration policy** (adds what the picture cannot, share cap 25-35%, dramatic irony,
bookends); look profiles; and a roadmap in which phases 1-5 are fully offline.

**Decided after v2:** narration share 25-35% of spoken words; pilot render = the first 2 clips at 480p, then ask before
continuing (optional, started by you); test batched shot writing at **2 clips per call**, behind a switch, offline
first; **one universal engine for all short-drama types** (no per-genre code; tone, look and beat emphasis inferred from
the premise and editable), checked on "A Market for Hearts" (romance), "The Don's Greatest Regret" (revenge/crime) and
one different third premise; **pilot render agreed** (first 2 clips at 480p, then ask). **Waiting for your green light
before starting Phase 1.** No code changed in this step.

### 2.8 Design document v3: Story Delivery (no code)

You told me the real problem: the Don's run did not make clear *what the story was*, while the replica's dialogue made
it obvious. I tested that against the data and **rewrote `VIBE_DIRECTOR_PLAN.md` (v3) around it**; connectivity,
batching, look and the Director chat were cut down to a short section.

**Evidence (offline, from the stored first run):** 43 clips, 56 spoken lines, 355 words, 38% narration, 6 wordless
clips. Read as a stranger: what Elena wants is never said; "Rossi", "manifests", "the ports" are never explained; the
central secret (she took the blame for him) is stated once at clip 34 of 43, by the villain, as jargon. The replica's
lines say each key fact plainly, in conflict, by the person with the stake. Word count is not the cause (ours is 99
words/min, the example 80).

**Correction:** I had overstated "batches don't follow from each other". Your clip-17 trace shows the clip writer already
gets the whole premise, a summary of every earlier beat and the last 3 clips. Only the beat-planning calls see just the
last 4 written beats. Connectivity is now a smaller, later phase.

**The v3 design (Phase 1, offline-buildable):** a Story Card with the story in five sentences; must-understand facts of
three kinds (state now, plant the question, pay later) with an owner, a beat and a deadline, plus a jargon-gloss list,
written in the existing act-breakdown call; ten dialogue writing rules (exposition through conflict, say the want, gloss
terms, a comeback must carry information, say key facts twice, narration states motive instead of describing the
picture); free code checks; a **blind-reader test** (a cheap model reads only the spoken script and writes the story back;
code checks the intended facts appear) plus a dialogue-only page for you to read; repair capped at one rewrite per
flagged batch and a ~60k-token budget per plan. Estimated cost ~$0.1-0.5 per plan. The Don's facts are mapped as an
example in the doc (illustrative lines, not pipeline output).

(Built afterwards: see 2.9. No OpenAI or kie.ai call was made.)

### 2.9 Phase 1 BUILT: Story Delivery (offline only, 2026-10-08)

Your green light, with one extra instruction: *make sure the codebase has no contradicting instructions for OpenAI left
by earlier implementations.* No OpenAI or kie.ai call was made; everything was built and checked with mocks and the
stored first run. **471 offline checks pass** (385 before, plus section `[31]`).

**Built (`hybrid_narrated_drama.py`, `app.py`):** a delivery map in the planning call (`story_in_five`, up to 16 facts
with role/kind/key terms/owner/channel/deadline/repeat, jargon) and `function`/`turn`/`delivers` on every beat; the
planner instructions and ten dialogue writing rules; per-batch instructions listing the facts due, what the audience
already knows, open questions and jargon to explain; free checks (HARD only for a fact missing from its clip or an
unsound map, everything else soft; older plans skipped); a repair budget of 60,000 tokens per plan with a hard stop
(`_RepairBudget`, proven with a mock that fails forever); the blind reader (one cheap call), `plan_delivery_report`
(checks, stats, the dialogue-only page), saved as `Job.delivery`, `Job.plan_report`, `master_plan.json` and
`plan_dialogue.txt`; continuations are told what is known and what is still open. Switches: `STORY_DELIVERY`, `BLIND_READ`.

**Contradiction audit, fixed:** (1) stale "micro-cycle" wording, including a retry instruction that contradicted
"scenes play"; (2) narration told to say what she "will not say aloud" vs delivery needing her to say it; (3) "short,
hard lines" and a 3-speaker quick-fire example vs one-or-two plain lines on delivery beats; (4) "a line may only use what
the audience knows" vs planting a question; (5) the clip writer told "you do not know the future" while its premise
describes the whole story; (6) `/enhance-prompt` banning internal thoughts for a mode made of them, and having no
narrated-drama mode. The suite caught one more of my own: with delivery switched off, two sentences still said "see
STORY DELIVERY" / "see FACTS below"; they are now conditional.

**On the real first run** the new checks flag the four facts that never reach the audience, two unexplained terms and
narration at 39% (target 25-35%). **Not done:** a real plan run (needs your OK), the dashboard view of the report.

### 2.10 Retries, and the replica's dialogue control (offline, 498 checks pass)

You asked how the replica made its dialogue carry the story, whether we took ideas from it, whether narration stays, what
`story_delivery` and `blind_read` are, and how to stop the new checks causing 2-3 OpenAI retries.

- **The replica's dialogue control** (its `storyEngine.js`): key dialogue planned per clip in the one planning call that
  knows the whole story (`keyDialogue`), character `motivation`, `relationships` and `speechStyle` with sample phrases,
  "a new piece of information, conflict or emotional turn in EVERY clip", a `storyPurpose` and `endingHook` per clip, "do
  not repeat information the viewer already knows", a small cast, and no narration. **Ported now:** a plain draft `line`
  per fact (our `keyDialogue`), `motivation`, `relationships` and `speech_style` on every character (shown to the beat
  writer), a self-check in each batch's fact list. Already ported: function/turn. **Not ported:** no-narration (your
  decision keeps narration, so narration stays and becomes a delivery channel), `endingHook`, its 8-line hand-off.
- **Retries:** a fact missing from its clip no longer causes a whole-act retry (about 11k tokens on the story model).
  It is a soft note, and `_repair_missing_facts` rewrites only that beat with one small cheap-model call (about 2k
  tokens), validated before it is accepted (speakers, line counts, word count, key terms, no reserved term, owner
  speaks); otherwise the beat is left as written and reported. Whole-act retries remain for structural problems only,
  still bounded by the 60k-token budget. The single-call plan does the same.
- Tests: 498 checks, now run with **no network and a blank API key** so a stray real call is impossible.

### 2.11 Retries on Luna, with a merge so nothing good is overwritten (offline, 520 checks pass)

You asked whether a 17-clip batch is safe and for every retry to run on Luna, not gpt-5.5.

- **Batch size:** acts under 6 clips merge into the previous batch if the total is 20 or less (5 + 8 = one batch of 13;
  12 + 5 = 17). By the measured act-beats calls (about 450 output tokens per clip including reasoning, +25 for the new
  fields) a 17-clip batch is about 8k output and 6.5k input tokens, against a 32k output cap. Whether quality holds at 17
  is **not measured** (the first run's batches were about 12). Now settings: `BATCH_MAX_CLIPS`, `BATCH_MIN_CLIPS`.
- **Every retry is on `OPENAI_CLIP_MODEL`** (act breakdown, beat batches, single-call plan, reveal-leak rewrite,
  continuation). First writes stay on gpt-5.5, and so does a re-run after a cut-off reply (it is the first write again).
- **Merge protection:** a Luna retry returns the whole JSON, but code takes from it only the clips a broken rule names
  (or, for the breakdown, only the part named: bible, delivery map or acts). Everything else stays exactly as gpt-5.5
  wrote it. A wrong number of beats, or a problem naming no clip, takes the whole answer.
- The continuation's "retry" used to re-send the identical request; it now says what was wrong.
- `RETRY_ON_CLIP_MODEL = False` restores retries on the story model.

### 2.12 Plan report: places used and the longest stay (offline, 528 checks pass)

You asked whether a 25-clip act would mean only four locations for 60 clips. It does not: nothing ties a location to an
act. The first run had one location per act because the Don's premise said "five locations, one per act" (stretches of 12,
12, 12 and 7 clips). The prompts ask for 4-8 locations and "locations move within an act"; `primary_locations` per act is
only advice, and the only check was a global soft one. Added: `plan_delivery_report` now returns `location_lines` ("Locations:
4 used of 5 defined" / "Longest stay in one place: 12 clips (60 s) in moretti_penthouse_office"), the stretches, and a soft
note for any stay longer than `LONG_STAY_CLIPS` (15 clips = 75 s). Never a retry. A per-sequence location plan is still the
real fix and is not built.

### 2.13 Plain language for every line (offline, 561 checks pass)

You pointed out that fixing 6-10 key facts leaves 70-90 lines poetic ("Tonight he offers me a pen", "He waited for tears. I gave him
the silence he feared", "You just threw away the thing holding back the dark", and the unexplained ring). You were right. **Cause:**
the old plain-words rule's own GOOD examples were figurative (it literally listed "Tonight he hands me a pen" as good), the premise
asked for lines "sharper than mine" and supplied the pen line, and nothing checked individual lines. **Fix:** a PLAIN LANGUAGE TEST
in the planner and beat-writer prompts (literal, no metaphor, say who and what, say what a meaningful act means, plain beats poetic
even over the premise) with examples from your lines; a Luna **plain-language review of every line** (`plain_pass_plan`, one call
per 15 beats, no retries) that rewrites non-plain lines with guards (speaker, meaning, a fact's key terms, reveal order, no
semicolon, word budget) and logs every before/after in the plan report; the same ask in `/enhance-prompt`. Not built into the clip
writer (the lines are locked by then). Switches `PLAIN_LANGUAGE`, `PLAIN_PASS`. Unmeasured on a real model.

### 2.14 Contradiction audit before the first real run (offline)

You asked for confirmation that PROGRESS.md, `app.py` and `hybrid_narrated_drama.py` do not contradict each other or what was
injected this session. I read the prompts as the model sees them (the act breakdown, the beat writer with a facts block, the
single-call planner, the clip writer, the supervisor, the plain-language review, the blind reader, the repair prompts, and
`/enhance-prompt`), grepped for conflicting phrases, and checked every documented decision against the code. **Found and fixed:**
1. The **30-minute rule was documented but not in the code** (every plan was told to end on a cliffhanger). Now a plan of 1800 s or more
   (and a continuation that brings the total there) is told to tell a whole story and end it; the enhancer agrees. Thread-payoff
   *checking* is still not built.
2. The **25-35% narration band was checked in the report but never told to the planner**, and the Don's premise asks for the upper end
   of the voiceover range. Rule 11 now tells the planner the band (one constant), and that a narration-led premise gets the top, not more.
3. The **ending fact vs a wordless final beat**: the plan asked for the ending to be said at clip 60 while the cliffhanger rule suggests a
   wordless last beat. The ending fact now goes on the last beat that has words, and every fact's clip must be a voiceover or dialogue beat.
4. **"Episode ends on a cliffhanger; wrap nothing up" was sent to EVERY batch**, including Act 1. It now binds only the last batch; the others
   are told scenes may reach their own outcomes.
5. **A fact could require a word the reveal ledger forbids** (for example "ports" in Act 1). Any fact whose words, draft line or key terms
   include a term revealed later is now a hard problem of the delivery map.
6. **"Never narrate through events" vs bridges**: bridges (1-2 voiceover clips that skip time) are now explicitly allowed.
7. The plain-language review could push a 15-word beat past the word budget; it can no longer.
8. Earlier in the session: stale "micro-cycle" wording, narration told to say what she "will not say aloud", poetic GOOD examples, "you do not
   know the future" vs a premise describing the whole story, and `/enhance-prompt` banning internal thoughts for a mode made of them.
Confirmed clean: no other path writes narrated-drama lines (regenerating a narrated-drama clip returns 501 today); prompts never point at a
section that a switch removed (tested for each switch). **Not audited:** `movie_scene_multispeaker.py` and the Talking Head / Story Time prompts.

### 2.15 "Ending on a cliffhanger" vs a premise that ends (offline, 607 checks pass)

You asked whether ending on a cliffhanger and never completing a story contradicts anything. **Yes, two real contradictions, now fixed:**
1. **A premise with a closed ending.** The Don's premise says "a 5-act crime drama, 60 clips, 12 per act" and ends Act 5 with the ship leaving
   and him on his knees. The prompts said "exactly 5 acts as requested in the premise", also "acts are NOT equal lengths", and also "do not
   close or wrap anything up". Nothing said which won. **Now:** for a plan under 30 minutes the premise decides cast, world, tone, events and
   their order; its act count and clips-per-act are guides; a closing the premise gives is NOT filmed as an ending but belongs to the next
   episode, and the earlier events are zoomed to fill the runtime. From 30 minutes the premise's ending is kept.
2. **"Wrap anything up" was too broad**: it would stop an episode answering even its own small questions, leaving it feeling unfinished.
   **Now:** each act answers its own smaller question; only the ONE central question stays open (as in the example script, where "will she
   hire him" is answered and "will she forgive him" is not).
Also: the 90-second enhancer climax asked for a closed "dramatic consequence"; for episode one it now leaves the next question open.
**Remaining limits, by your decision:** there is no manual "final episode" switch (a story ends only when its total reaches 30 minutes), and a
code check that every opened thread is paid off at a final ending is not built.

## 3. Findings and decisions (no code)

- **Per-call anatomy (clip writer, stored run, approximate):** system prompt 5.2k (identical every clip, cached),
  history of last 3 clips ~3.4k, story-so-far list ~0.9k (1.8k by clip 43), mode rules + location + beat ~0.9k;
  output median ~1.7k visible, reasoning roughly 1–2k more.
- **The number that matters is billed tokens, not raw.** If the cache hits, ~5.2k of each call is billed at ~10%,
  so full-price-equivalent input is already ~3.4k per call. Unverified until a real run shows `cached` in the log.
- **Worst-case estimate, 60 clips (extrapolated from gpt-5.5 token counts, Luna unmeasured):** normal ~$1.25;
  every retry used ~$4.40, of which ~$3 is gpt-5.5 showrunner output.
- **Muted tail of the previous clip as a video reference** (continuity idea): you tested it and quality degrades
  on Seedance; matches Tests G to I in `PLAN.md`. Dropped.
- **OpenArt (public sources only; its internals are not published):** script → storyboard images → image-to-video
  per shot, characters/locations as saved references, Smart Shot plans 3–5 shots with system-chosen camera moves,
  and its own FAQ says continuity is not guaranteed. Its Seedance prompt guide asks for whole-second timecoded
  beats, one named camera move per beat, and narrowly-scoped labelled references.
- **Why our video can feel locked and static (from our own code, inference not proof):** rule 5(1) tells the clip
  writer to re-state the same camera across consecutive `[SAME SETUP]` clips, with "locked static hold" as an
  example; each clip is generated separately from text + cast/location images, with no first frame, previous clip
  or last frame; render model is `seedance-2-mini` at 480p. First/last frames cannot be combined with reference
  audio, which the voice bank needs.

## 4. Not done yet / open

- A real run to measure: cached tokens, Luna's first-pass validator rate, prop and pose consistency with the
  shorter history, and whether the action timeline changes the video.
- Luna `reasoning_effort` test (`none` / `low`) on a replay of the stored beats (OpenAI only, a few cents).
- Walking, entering and leaving scenes: camera timing. The clip writer is already told to keep story-critical
  movement in frame (rule 5, "STORY-CRITICAL MOVEMENT ON CAMERA" and "EXITS THAT LEAVE OTHERS ALONE"), but the
  camera move itself is one untimed sentence in `shot`. Ideas: a timed `camera` field next to the action steps;
  an exit-right / enter-left rule across a location cut; relaxing the locked `[SAME SETUP]` policy to allow one
  named, motivated move per clip.
- Larger Seedance model or 720p for a few beats (costs kie.ai credits; yours to run).
- Known gaps noticed while reading, not touched: the voice-sample thresholds differ (1.5 s in
  `_is_good_voice_sample`, 2.0 s in `trim_windowed_voice`) and the fallback in `bank_voice` has no length check;
  the reveal-leak backstop rewrites only the first leaking act; the continuation retry loop re-sends an identical
  prompt; the clip-level speech-timing check reads fields that are no longer in the schema.

## 5. To make it live

```
docker-compose up -d --force-recreate
```

**Correction (2026-10-08):** an earlier version of this log said the code is baked into the image and needs a rebuild.
That is wrong: `docker-compose.yml` bind-mounts `app.py`, `dashboard.html`, `movie_scene_multispeaker.py` and
`hybrid_narrated_drama.py`, so the containers already *see* the edited files. A running process keeps the old code in
memory, though, and a worker that has an old `app` loaded would fail to import the new `hybrid_narrated_drama`
(it imports `OpenAIOutputCut` from `app`). So **restart both containers before any run**. `--force-recreate` is needed
only because `.env` (the Luna setting) is read when a container is created; a plain `docker-compose restart` is enough
for code alone. Do it when the worker is idle. Afterwards the `[openai]` log lines show input, cached tokens,
reasoning tokens and an estimated cost per call.

## 6. Housekeeping

- During this session a check command printed the OpenAI API key from `.env` into the session output. The key is
  not written in any file. If that output could be seen by anyone else, rotate the key.
