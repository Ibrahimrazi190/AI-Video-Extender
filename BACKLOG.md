# Backlog: Not Implemented Yet

Everything we deferred, left undecided, or said we'd look at later, as of 2026-09-27. It follows `EXECUTION_GUIDE.md`'s order: deferred build steps first, then tests still owed, then `PLAN.md` Section 7's open questions, then smaller ideas and known gaps.

Nothing here is decided just because it's listed. The same rules apply as in the guide: one step at a time, anything that spends kie.ai credits is yours to run, and an open question stays open until you settle it. Details are in `PLAN.md` and `PROGRESS.md`, as referenced on each point.

---

## 1. Deferred build steps

### Prompt 11: Mid-sequence regeneration (deferred 2026-09-27, your call)
- **Now:** Regenerate Script and Regenerate Scene only work on the **last** clip. Any other clip answers 501 "mid-sequence regeneration not yet implemented".
- **The guide's gate isn't met:** Tests B (Talking Head) and D (Story Time) have to be run by hand on kie.ai first (section 2).
- **Talking Head, cheap partial option:** its clips no longer depend on each other; every clip after the first is made from the 720p master. So a middle clip (not clip 1) could be regenerated exactly like the last one, from the master, with no bridging and no Test B. It's a small change on top of the Prompt 9/10 code.
- **Story Time:** each clip is built from the muted previous clip, so changing a middle clip breaks the next one (the cascade problem, `PLAN.md` Section 5). Two options:
  - dual-reference bridging, after Test D passes;
  - the fallback: regenerating a middle clip also regenerates everything after it (costs more).
- **The 15 s reference cap:** kie.ai caps the reference videos in one request at 15 s in total, and audios too. Bridging with two 10 s clips is 20 s, so the references would have to be trimmed (about 7 s each). A 5 s test doesn't validate production.
- **Script context (`PLAN.md` question 3):** a middle clip's new line would probably need the following clip's line as context too, not only the previous one.

### Regenerating clip 1 in a multi-clip job
- **Now:** it answers 501, because it's not the last clip.
- **Talking Head:** clip 1 is the master every other clip was made from. Regenerating it would mean new anchors and, strictly, all later clips re-made.
- **Story Time:** clip 1 provides the narrator-voice and character anchors, so the same applies.
- **Needs a decision:** regenerate everything after it, or accept a mismatch.

### Prompt 13: Cost estimate on the dashboard (optional / later)
- **Not started.** The guide says to leave it until the pipeline is stable.
- **Measured billing pattern to use** (`PLAN.md` Section 2):
  - no references: 3.8 credits/s at 480p, 8.2 at 720p;
  - with a reference video: 2.4 credits/s of (output + reference video);
  - reference audio and images don't appear to be billed.
- **Talking Head estimate:** about 8.2 x clip length for the 720p first clip, plus 2.4 x (2 x clip length) per later clip.
- **Unmeasured:** later clips with 720p output; Story Time costs (assumed to follow the same pattern).
- **Would help:** recording `credits_consumed` per clip in the job store (see section 5).

---

## 2. Tests still owed (testing notes not yet run)

- **Prompt 5.6, 10-second runs:**
  - a 3-clip Story Time job at the production 10 s length (about 134 credits);
  - one 3-clip Talking Head job at 10 s on the current code (about 178). This also covers Prompt 5's own 10 s check.
  
  So far every live job has used 5 s clips.
- **Test B (Talking Head bridging)** and **Test D (Story Time bridging):** the gate for Prompt 11 (`PLAN.md` Section 8).
- **10 s specifics not yet checked live:** a 10 s master as the reference video (inside the 15 s cap), and the cost at 10 s (about 48 credits per later clip, because the whole master is billed on every clip).

---

## 3. Open questions (`PLAN.md` Section 7), still undecided

- **Q1, mid-clip bridging quality:** set aside with Prompt 11. Possibly moot for Talking Head (see above).
- **Q3, script context for regenerating a middle clip:** only matters once middle clips exist.
- **Q4, copyright-filter retries:** a clip that hits Seedance's audio copyright filter just fails; there's no automatic retry with stricter "no music" wording. Undecided.
- **Q9, aspect ratio:** never chosen. Nothing is sent, so kie.ai's 16:9 default applies. Decide whether to offer 9:16 (phone-style) or fix it. The final-video sizes and kie.ai's reference pixel limit depend on it.
- **Q10, webhooks instead of polling:** kie.ai supports a `callBackUrl`; polling is used because kie.ai can't reach localhost. It's possible later with ngrok; it needs a public callback route, with polling kept as a backup.
- **Q11, the pronoun in the Talking Head template:** the prompts always say "She speaks directly to camera", so a male speaker in the scene bible contradicts it. Make it neutral, or accept that.
- **Q12, a better model for Story Time motion shots (parked):** `seedance-2-5` rendered a walking shot cleanly where `seedance-2-mini` distorted faces. You noted early on that 2-5 may be needed for videos where faces matter. Not checked: its kie.ai model id, cost and reference limits. The code uses one model (`KIE_MODEL`) for everything.
- **Q14 watch item, Story Time quality over long chains:** the first 5-clip run showed a slight fall-off down the chain, which you accepted for now. Keep watching it on longer jobs; if it gets worse, revisit the chained (muted) video reference.

---

## 4. Ideas we said we'd look at later

- **Your Story Time points:** you said you had "some things to discuss later" after the dashboard test.
- **Breath trim for Story Time:** the final-video trim of the breath before the first word is Talking Head only. Story Time's narrator may also breathe in at the start of a clip. Your call to leave it for now.
- **Parallel generation:** Talking Head clips after the first don't depend on each other, so they could all generate at once, which would be much faster for long videos. Not wanted for now (your call).
- **A shorter master reference to cut cost:** at 10 s clips the whole 10 s master is billed on every later clip (about 48 credits each). A 3–5 s excerpt of the master might keep quality at lower cost. Untested.
- **Talking Head "Regenerate Scene" with a different framing:** today it's a plain new take. Varying the camera framing (for example close-up instead of medium) while keeping the room and person would make the cuts feel deliberate. An option only.
- **Word budget:** lines aim for about 2.2 words per second, which is nearly the whole clip. If endings ever sound clipped or rushed, lower the factor in `_word_budget` to 1.8–2.0.

---

## 5. Known gaps and limitations

- **Double submission through the API:** each `POST /jobs` is a new, paid job. The dashboard disables its button, but the API itself doesn't catch duplicates.
- **A worker that dies mid-job** leaves the job "generating" forever. There's no timeout, recovery or resume, and a clip kie.ai was rendering may be paid for but never collected. Keep the laptop awake during a job.
- **Credits per clip aren't recorded** in the job store (kie.ai returns them). Useful for Prompt 13.
- **A regenerated clip's old video link isn't kept** (kie.ai keeps the file for 14 days, but the job no longer points to it).
- **The dashboard shows only the last job:** there's no job list or history (not asked for; "no other pages").
- **The duration list stops at 60 clips** (10 min; about 2,900 credits in Talking Head at 10 s) so a huge spend isn't one click away. Extend it when long videos are wanted.
- **Story Time's first clip must show the main character** (its last frame is the character reference). This is enforced by the script prompt only, not checked in code.
- **Accepted limitations:**
  - a slight color/saturation shift at Talking Head seams (Test A);
  - a small pose reset at every Talking Head cut (every clip starts from the master);
  - the audio reference is the untrimmed first-clip audio (you consider the audio settled).

---

## 6. Housekeeping

- **The dashboard is reachable from your network:** port 8001 is published on all network interfaces, and there's no login, so anyone on the same Wi-Fi/LAN who can reach it could start paid jobs. To keep it local, change the mapping to `127.0.0.1:8001:8000` in `docker-compose.yml`.
- **Nothing starts on its own after a reboot:** Docker Desktop doesn't start with Windows, and the containers have no restart policy. `restart: unless-stopped` in `docker-compose.yml`, plus Docker Desktop's "Start when you sign in", would make the dashboard come back by itself.
- **The media volume only grows:** every downloaded clip, prepared clip and final video is kept, with no clean-up of old jobs or replaced clips.
- **`test_results/` isn't git-ignored** (test videos and measurements).
