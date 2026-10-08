# First Priority: Implement

**Status: not built. Agreed 2026-10-07, deferred so token-saving work can go first.**

This is "A2" — the unfinished half of the planner redesign. A1 (the caps, the word budget, scenes-play /
bridges-skip, dramatise-don't-report, uneven acts) **is already built**; see `PROGRESS.md`,
"Hybrid Narrated Drama — the OpenAI bill, and why the film sounded dead (2026-10-07)". Do not redo it.

Everything here lives in `hybrid_narrated_drama.py` unless stated otherwise.

---

## Why this is first priority

From watching the first 5-minute run (job `d54e40da…`), in the viewer's own words:

- clips 13–24 — *"super super unclear what she is doing... I didn't get a single thing"*
- the whole thing — *"the story feels hollow and not well given to a normal watcher"*

The measured causes, and which part fixes each:

| what went wrong | evidence from the run | fixed by |
|---|---|---|
| an act of montage material inflated into 12 clips | 11 of 12 clips showed exactly one person, on a phone | Part 1 |
| the vault reveal crushed into 12 clips | the whole backstory, the banishment and the order to the harbour in one act | Part 1 |
| every act identical | 12/12/12/12/12, one room each, exactly 60s apiece | Part 1 |
| the film reports instead of plays | 502 spoken words total, **41% of them narration** | Part 2 |
| a 20-minute plot squeezed into 5 minutes | 6 major events, 5 locations, 4 characters, a ledger, forged manifests, an off-screen ambush | Part 2 |

A1 makes a varied shape *possible*. This makes the planner *commit* to one, and stops it writing more story
than the runtime can hold.

---

## Part 1 — sequences become a field, not a hope

**The problem A1 leaves open.** A1 teaches "a SCENE plays out, a BRIDGE skips time" in prose. Nothing records
which is which, so nothing can check it, and we only find out by reading 60 beats after paying for them.
Models default to uniform blocks — that is exactly what produced 12/12/12/12/12 — so prose guidance alone
will drift back.

**The change.** Add `sequences` to each act in `ACT_BREAKDOWN_SCHEMA`:

```jsonc
{
  "act_number": 2,
  "title": "Act 2: His Empire Crumbles",
  "sequences": [
    { "kind": "bridge", "clip_count": 2,  "location_id": "vance_harbor_terminal",
      "purpose": "the ports close overnight; his routes die on the screens" },
    { "kind": "scene",  "clip_count": 12, "location_id": "terminal_control_room",
      "purpose": "Lorenzo comes to her in person and is refused to his face" }
  ]
}
```

- `kind`: enum `["scene", "bridge"]`
- `clip_count`: integer — **the planner decides it; do not hardcode ranges in code.** The prompt teaches
  "length follows content"; only the mechanical bounds below are enforced.
- `location_id`: must exist in `scene_bible.locations`. Sequences in one act may use *different* locations —
  that is the point.
- `purpose`: one line, what this stretch is for.

**Validation, in `_check_act_breakdown`:**

- every sequence's `clip_count` sums to exactly that act's `end_clip - start_clip + 1` — **hard**
- `location_id` exists in the bible — **hard**
- a `bridge` never exceeds `MAX_CONSECUTIVE_VO` (3) clips — **hard**; it is 1–2 by design
- an act whose sequences are all one location, or all the same kind, raises a **`[SOFT]`** note
- acts of identical length across the whole plan raise a **`[SOFT]`** note (the 12/12/12/12/12 symptom)

**Prompt, in `_narrated_act_beats_prompt`:** tell the writer which sequence each clip belongs to —
*"clips 15–26 are a SCENE in `terminal_control_room`: play it in real time, do not cut away"* — instead of
leaving it to infer. This is also where a bridge gets told it has 2 clips and must land somewhere new.

**Already compatible, do not re-engineer:**

- `_normalize_act_spans` honours whatever spans the model returns (it only clamps for contiguity), so uneven
  acts already flow through.
- `_plan_act_batches` splits acts over 20 clips and merges acts under 6 **for generation batching only** —
  that is about OpenAI call size, not story shape. A deliberate 3-clip bridge act will be batched with its
  neighbour and still keep its own act entry. Leave it alone.
- `Job.acts` is stored and saved into `master_plan.json` (fixed 2026-10-06), so the dashboard can render
  sequences once they exist.

---

## Part 2 — plan a runtime's worth of story, not a whole arc

**The problem.** The showrunner is told to fit a *complete* story into N clips. At 60 clips that means
compressing roughly a 20-minute plot, so every beat reports rather than plays — 502 words of dialogue for a
five-minute film, 41% of it narration. This is the single biggest cause of "hollow".

**The change.** Ask for however much story genuinely *plays* in the runtime, ending on a cliffhanger rather
than a resolution. The opening acts get room to breathe; the rest is left for the continuation.

- `_narrated_act_breakdown_prompt` and `_narrated_outline_prompt`: stop demanding a full arc. Demand the
  story's opening movement, played properly, ending on an unresolved turn. A 5-minute piece is **episode
  one**, not a feature in miniature — which is the ReelShort / DramaBox format this mode was built for.
- `/enhance-prompt` in `app.py`: it currently scales the number of **acts** to runtime but not the number of
  **plot events** — it will write a 5-act epic for a 60-second video. It must scale the *amount of story*:
  fewer events, each given room. This is where the oversized premise enters the pipeline.
- Continuation already works for `narrated_drama` — `write_narrated_continuation_outline` is wired to
  `extend_movie_plan_task` at [app.py:1458](app.py:1458), verified 2026-10-07. Nothing new needed there.

**Known limitation to keep in mind:** `write_narrated_continuation_outline` loops `SCRIPT_RETRIES + 1` times
but never rewrites its user prompt between attempts, so a retry re-sends an identical request. Worth fixing
while in this area.

---

## How to tell it worked

Generate a plan (no clips) and read `master_plan.json`:

1. Are the acts **different lengths**, and does each length obviously match what the act has to do?
2. Does at least one act contain **more than one location**?
3. Is there a **bridge of 1–2 clips** somewhere, doing the work that clips 13–24 took twelve clips to fail at?
4. Is there a **scene running 10+ unbroken dialogue clips**? (Impossible before A1 — the old cap was 3.)
5. Does the plan **end on a cliffhanger** rather than tying everything off?
6. Read the beats of the longest scene: does each turn move, or do they circle?

## Cost

Planning only, no clips, no FLUX: **~6 OpenAI calls, about $1.10** (measured: 1 act breakdown at ~$0.12 plus
5 act-beats calls at ~$0.16 each). Nothing is spent on kie.ai until a plan is approved.

## Order

Part 1 and Part 2 both touch the act breakdown prompt and schema — build them together, in one pass, and
validate with a single plan generation.
