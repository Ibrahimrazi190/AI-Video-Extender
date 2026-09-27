# Movie Scene Mode — Findings Log (exploratory, not yet built)

This is a working notes file for a proposed third mode, alongside Talking Head and Story Time. Nothing here is built into `app.py` yet — everything below is from manual playground testing on kie.ai. Once testing concludes, this file becomes the basis for a real `PLAN.md`/`EXECUTION_GUIDE.md` addition, the same way Test S became Story Time's build spec.

## 1. The concept

Multiple characters in one setting, talking to each other (not to camera, not narrated) — e.g. a woman telling her friends about a toxic marriage over coffee. A drama scene, not a monologue or a voiceover.

## 2. Why the existing modes don't fit

| | Talking Head | Story Time | Movie Scene (proposed) |
|---|---|---|---|
| Who's on screen | one person | changing scenes | several characters, one setting |
| Who speaks | to the camera | nobody (voiceover narrator) | characters to each other, nobody looks at camera |
| Script per clip | line + delivery | narration + visual + delivery | shot + per-line speaker + line + delivery + what others do |
| Scene bible | speaker + room | characters + world + narrator voice | every character (look + voice) + room + props + style |
| Consistency mechanism | fixed 720p master | chained muted video + fixed anchors | under test — see Section 4 |
| Cuts | small pose reset | scene changes | shot changes (wide / close-up / reaction) — normal in film |

## 3. Models considered

- **`bytedance/seedance-2-mini`** — works, but visibly strains on a 5-person scene (expected: Test S already showed mini struggling under demanding conditions on a single character; a 5-person dialogue scene is a harder version of that same limitation).
- **`bytedance/seedance-2-fast`** — **parked, not a formula problem.** Re-tested and failed again: `"duration must be between 1.8 to 32.2 seconds"` (didn't match the actual 5s request sent) followed by `"failed to validate attached media"` on retry. This looks like a platform-side bug on kie.ai's `seedance-2-fast` right now, not an incompatibility with this mode's reference formula. No further credits spent chasing it; revisit later by checking whether it's since been fixed, rather than debugging further now.
- **`seedance-1-5-pro`** — a separate ByteDance model line (Dec 2025), explicitly documented elsewhere as supporting "multi-character dialogue" and "character consistency across shots" — sounded like the best fit on paper. **Ruled out for now**: kie.ai's page for this model doesn't expose `reference_audio_urls`, and audio referencing is central to this whole approach.
- **`seedance-2-5`** — not yet tested on a multi-character clip. Next test to run (Section 6).

## 4. Reference formula — what's been tested

**Decision: no `reference_video_urls`.** Based on every prior lesson from Talking Head/Story Time (video references cost quality and carry embedded audio that can compete with voice references), video reference was deliberately skipped from the start rather than tested and rejected.

**Clip 1 (bootstrap, no prior clip exists):** zero references. Character identity and voice both came from **text description alone** in the scene bible (name, appearance, and an explicit voice description like "a low, measured voice"). This worked: correct speaker's mouth moved for each line, no cross-talk, and Daniel/Priya sounded distinct from text alone with zero audio anchor.

**Clip 2 onward — the tested, working formula:**
- `reference_image_urls = [clip 1's last frame]`, tagged `@Image1` — carries overall identity/style for the whole group in one shot.
- `reference_audio_urls = [speaker A's trimmed voice, speaker B's trimmed voice, ...]`, tagged `@Audio1`, `@Audio2`, etc., **in upload order** — this is positional, not content-aware. Whichever file is uploaded first becomes `@Audio1` regardless of whose voice is actually in it. Confirmed via the same mechanism already validated for images in Test S.
- Prompt explicitly maps each tag to a named speaker: *"Daniel, in the voice of `@Audio1`, says: '...' Priya, in the voice of `@Audio2`, replies: '...'"*

**Result: confirmed working**, on `seedance-2-mini` (quality strained but the core mechanism held) — correct voice stayed mapped to the correct character, and the group's identity/style matched the previous clip closely. This validates the hardest open question from Section 2's original list: **yes, per-speaker audio tagging works**, at least on mini.

**Hard cap discovered:** kie.ai's 2.0/mini tier accepts **at most 3 reference audios per request**. Fine for a 2-speaker clip; a real problem if more than 3 characters need distinct voice anchors in one clip. `seedance-2-5` reportedly allows up to 10 — relevant if this mode needs to scale past 3 simultaneous named voices.

## 5. Open problems

**5.1 — Per-speaker timestamping — RESOLVED (hybrid approach decided, not yet built).**

Isolating a character's voice for use as a future reference requires trimming their exact spoken segment out of the clip's full audio track. So far this has been done by **manually eyeballing/guessing timestamps by ear** — workable for a one-off test, not reliable for a real pipeline. This also caused a second problem: vague prompt phrasing like "a beat later" produced awkward, uncontrolled pacing between lines (Section 5.4, now folded into this decision).

**Decided approach — an estimate for the prompt, a real detector for the trim, not either alone:**
- **OpenAI's script-generation step estimates per-speaker timestamps** for each line, the same way clip word budgets are already estimated from a words-per-second pace (`_word_budget`). These estimates get inserted into the Seedance prompt as explicit timing brackets (e.g. `[0 to 1.5s] Daniel says... [3.8 to 5s] Priya replies...`), which also fixes the pacing/timing-control problem — the model is told exactly when each line should land, instead of interpreting "a beat later."
- **The estimate is not trusted as the literal audio trim point.** OpenAI writes the script before any audio exists, so it can only predict roughly how long a line will take to say — actual pacing, pauses, and emphasis are decided by Seedance at generation time and can run longer or shorter than predicted. Trusting the estimate blindly for the real trim risks repeating the original chopped-word bug (a corrupted reference audio propagating into every later clip).
- **The actual trim boundary is found by analyzing the real generated audio**, reusing the silence/energy-threshold detector logic already built for Talking Head's lead-in trimming. That tool finds where speech actually starts/stops by measuring the waveform, not by trusting a prediction — point it at the estimated window (rather than scanning the whole clip blind) to find the real, accurate cut point quickly.

**Not yet built:** this is a decision, not code. Needs a standalone test script (outside the main pipeline) before this goes anywhere near `app.py`.

**5.2 — Face visibility isn't guaranteed by a single last-frame extraction.** In the actual Clip 1 generated, two of the five characters were not clearly visible (one turned away, hair covering her face). Decided for now: **ignore this for testing purposes**, but it's a real gap to solve before real use.
  - **Proposed fix (not built): a "face bank" requirement**, not a "show everyone every clip" requirement. Each character needs *one* clean, unobstructed face moment banked *somewhere* early in the sequence before later clips are allowed to rely on referencing their identity — after that, they can be shot from any angle. This generalizes Story Time's existing "first clip must show the main character" rule (built in Prompt 4.6) to N characters, spread across the first few clips instead of forced into clip 1 alone.
  - **Known weakness to design around this time:** Story Time's equivalent rule is enforced by prompt wording only, with no code-level check — flagged in its own docs as a gap. If Movie Scene mode gets built for real, this should get an actual verification step (even a simple one), not the same prompt-only trust again.

**5.3 — `seedance-2-fast`'s validation error is unexplained.** Worth a small isolated test later (does it reject *any* reference audio under some duration, or was it something specific to this request) before ruling the model out entirely.

**5.4 — Dialogue pacing/timing control — folded into 5.1's resolution.** The original "a beat later" pacing problem and the timestamping problem turned out to be the same fix: explicit timing brackets in the prompt, driven by OpenAI's per-line timestamp estimates. See Section 5.1.

## 6. Next test to run

Same Clip 2 setup (image + 2 tagged audio references, same prompt) on **`seedance-2-mini`** isolates whether a stronger model renders the same working formula at real quality. 
## 7. Not decided / not started

- Real script-generation design for this mode (per-clip: shot type, speaker(s), line(s), delivery, what non-speakers do) — nothing drafted yet.
- How the "face bank" and per-speaker voice bank would actually be tracked and stored across a job in code.
- Cost implications: more reference inputs per clip (image + up to 3 audio) than either existing mode, plus the extra processing step of trimming per-speaker audio.
- Whether/how this mode's regenerate-clip logic would need to differ (e.g. regenerating a clip with new dialogue for an already-banked character vs. a not-yet-banked one).
