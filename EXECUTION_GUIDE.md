# AI Execution Guide — Prompt-by-Prompt Build Order

Companion document to `PLAN.md`. Give these prompts to your AI coding agent **one at a time, in order**. Don't skip ahead — each step assumes the previous one is done and working. After each prompt, run the "Testing note (just for me)" yourself before moving to the next prompt.

Where a step touches something `PLAN.md` flagged as unconfirmed/open, it's called out explicitly so you don't treat it as settled just because code got written for it.

---

## Prompt 1 — Project Scaffolding

**Prompt to give the agent:**
> Set up a new Python project for a FastAPI + Celery + Redis backend, structured as a **single file**: `app.py`, containing everything — config, Pydantic models, Redis store helpers, OpenAI helper, Seedance helpers, the Celery task, and the FastAPI app — organized top-to-bottom with clear comment-block section headers (e.g. `# --- Config ---`, `# --- Models ---`, etc.) rather than split across multiple files. Also create `dashboard.html` (empty placeholder for now — this is the one file that stays separate since it's frontend, not backend logic), `.env.example`, `requirements.txt`, and a `docker-compose.yml` with three services: `api` (FastAPI via uvicorn, importing `app.py`), `redis`, and `worker` (Celery, same image as api, running `celery -A app.celery_app worker`). No database — job state lives in Redis. No authentication, no user accounts. `app.py`'s config section should load `OPENAI_API_KEY` and `KIE_API_KEY` from env. Keep the FastAPI section minimal for now — just a health-check route (`GET /health`) — don't wire up real endpoints yet, this step is scaffolding only.

**Testing note (just for me):**
Run `docker-compose up` and confirm all three containers start without errors, both processes (uvicorn and celery) successfully import `app.py` with no errors, and `GET /health` returns 200. Don't move on until this is clean — every later step builds on this actually running.

---

## Prompt 2 — Job & Clip Data Models

**Prompt to give the agent:**
> In `app.py`'s Models section, define Pydantic models for: a `ClipRequest` (topic, duration in seconds, resolution — `"480p"` or `"720p"`), a `Clip` (index, dialogue text, delivery direction, video_url, audio_url, last_frame_url, status: pending/generating/done/failed), and a `Job` (id, original request, resolution, list of `Clip`, overall status). Then, in the Redis store helpers section (below the models), add functions `save_job(job)`, `get_job(job_id)`, `update_clip(job_id, clip_index, **fields)` — store jobs as JSON in Redis keyed by job id.

**Testing note (just for me):**
No visible behavior yet — just check the code is sane and matches what's described in `PLAN.md` Section 4 (clip has dialogue + delivery + reference fields). Sanity-check by manually calling `save_job`/`get_job` in a Python shell against your running Redis.

---

## Prompt 3 — OpenAI Script/Scene Generation

**Prompt to give the agent:**
> In `app.py`'s OpenAI helper section, write a function `generate_script(topic: str, num_clips: int) -> dict` that calls OpenAI (using `OPENAI_API_KEY`) and returns structured JSON matching: `{"scene_bible": str, "clips": [{"dialogue": str, "delivery": str}, ...]}` with exactly `num_clips` entries in `clips`. The system prompt should instruct the model to: (1) write `scene_bible` as a single fixed description of character appearance, setting, and camera framing that will be reused unchanged across every clip, (2) write natural spoken dialogue per clip meant for a person speaking directly to camera, each short enough to comfortably fit in a 10-second spoken clip, (3) ensure the dialogue lines form one continuous, coherent story across all clips, not isolated statements, (4) return strictly valid JSON, nothing else. Force JSON output mode if the OpenAI SDK version supports it.

**Testing note (just for me):**
Call `generate_script("a girl telling us her story of how she did not like her husband at first, sitting on a sofa, talking to camera", 3)` directly and read the output. Check: does `scene_bible` actually sound reusable (physical description, not vague)? Do the 3 dialogue lines read like one continuous story rather than three random statements? This is the step most worth manually reading closely — bad output here poisons everything downstream.

> **Note from PLAN.md:** Section 7, open question 3 — whether regenerating a single clip's script should pass neighboring dialogue as context is still undecided. This prompt only covers *initial* full-job generation. Don't build the regenerate-script endpoint's context-passing yet — that's Prompt 9.

---

## Prompt 4 — Seedance Client Wrapper

**Prompt to give the agent:**
> In `app.py`'s Seedance helpers section, write a wrapper around the kie.ai Seedance 2.0 Mini API (https://kie.ai/seedance-2-0-mini) using `KIE_API_KEY`. Include: `generate_clip(prompt, resolution, duration=10, reference_video_urls=None, reference_audio_urls=None, reference_image_urls=None) -> dict` that submits the generation request and returns the resulting video URL once complete (poll or use webhook, whichever kie.ai's API supports — check their actual docs for the correct pattern, don't assume). Also write `extract_last_frame(video_url) -> str` (returns an image URL/path — use ffmpeg to grab the last frame) and `extract_audio(video_url) -> str` (returns an audio file URL/path — use ffmpeg to extract the audio track). All reference URL parameters are optional and should simply be omitted from the request payload if not provided.

**Testing note (just for me):**
Manually call `generate_clip()` with a real prompt, no references, 480p, and confirm you get back a working video URL. Then run `extract_last_frame()` and `extract_audio()` on that result and confirm both files are valid (open the image, play the audio). Do this before wiring anything else — if extraction is broken, the whole forward chain silently breaks later.

> **Note from PLAN.md:** Section 6 — confirm the actual valid duration steps and exact parameter names directly against kie.ai's own page for this call, since reseller docs elsewhere used different field names (`start_image` vs `first_frame_url`, etc.). Don't trust this document's assumed names as gospel — verify against kie.ai's live API reference while writing this wrapper.

---

## Prompt 5 — Core Pipeline: Forward-Chain Generation (Celery Task)

**Prompt to give the agent:**
> In `app.py`'s Celery task section, write a Celery task `run_generation_job(job_id: str)` that: (1) loads the job from the store, (2) calls `generate_script()` to get `scene_bible` and clip dialogue, (3) loops through clips in order and generates each one using the `generate_clip()` helper, building the prompt via a small new helper `build_clip_prompt(scene_bible, delivery, dialogue, is_first_clip)` using these two fixed templates:
> - Clip 0 (first): `"{scene_bible}. She speaks directly to camera, {delivery}: \"{dialogue}\" Natural lip sync to dialogue, no background music, no score."` — no reference inputs, `generate_audio=True`.
> - Clip N (N>0): `"Continuing directly from <Video 1>, {scene_bible}, still speaking to camera, {delivery}: \"{dialogue}\" Natural lip sync to dialogue, same lighting and camera style, no background music, no score."` — `reference_video_urls=[clip N-1 video]`, `reference_audio_urls=[clip N-1 audio]`, `reference_image_urls=[clip N-1 last frame]`.
>
> After each clip generates, extract and store its last frame and audio for the next iteration to use, and update the job store so the clip's status becomes `done` (or `failed` with an error message on exception — don't let one failed clip crash the whole task, mark it failed and stop the chain there).

**Testing note (just for me):**
Kick off a real job for a 3-clip (30s) topic and watch it process end-to-end. Check the job store after: are all 3 clips marked `done`, do all 3 have video/audio/last-frame URLs populated? Then actually watch the 3 clips back to back — this is Test A from `PLAN.md` Section 8, now running through real code instead of manual dashboard testing on kie.ai's site.

---

## Prompt 6 — FastAPI Endpoints

**Prompt to give the agent:**
> In `app.py`'s FastAPI section, add these endpoints: `POST /jobs` (accepts a `ClipRequest`, creates a job in the store, kicks off `run_generation_job` as a Celery task, returns the job id), `GET /jobs/{job_id}` (returns full job state including all clips and their current status/URLs — used for polling from the dashboard).

**Testing note (just for me):**
Hit `POST /jobs` with a real topic via curl/Postman, grab the job id, then poll `GET /jobs/{job_id}` every few seconds and watch clip statuses flip from `pending` → `generating` → `done`. Confirm the final response includes playable video URLs for every clip.

---

## Prompt 7 — Dashboard Frontend (Single Page)

**Prompt to give the agent:**
> Build the single-page dashboard in `dashboard.html` (plain HTML/JS, no build step/framework needed for something this small) with: a text input for the topic, a duration selector (multiples of 10 seconds only, per the fixed 10s clip length), a resolution toggle (480p / 720p, defaulting to 480p), and a "Generate" button that calls `POST /jobs` and then polls `GET /jobs/{job_id}` until complete. Once complete, render a horizontal timeline with one segment per clip. No login, no navigation, no other pages. Serve this file as a static file from the FastAPI app in `app.py` (e.g. `GET /` returns `dashboard.html`).

**Testing note (just for me):**
Submit a job from the actual UI, not curl this time, and confirm the timeline renders once generation finishes and each segment corresponds to the right clip in order.

---

## Prompt 8 — Timeline Clip Interaction

**Prompt to give the agent:**
> On the dashboard timeline, clicking a clip segment should show: its dialogue/script text, and two buttons — "Regenerate Script" and "Regenerate Scene". For now, just wire the UI and have both buttons call placeholder endpoints (`POST /jobs/{job_id}/clips/{clip_index}/regenerate-script` and `.../regenerate-scene`) that don't need to be implemented yet — return a 501/"not implemented" stub from the backend for now. This step is UI wiring only.

**Testing note (just for me):**
Click a few clips, confirm the right script text shows for each, confirm both buttons fire the correct API calls (check network tab / logs), even though they don't do anything real yet.

---

## Prompt 9 — Regenerate Script (Last Clip Case Only)

**Prompt to give the agent:**
> Implement `POST /jobs/{job_id}/clips/{clip_index}/regenerate-script` for the case where `clip_index` is the **last clip** in the job. It should: generate a new dialogue line for that clip via OpenAI (reusing the existing `scene_bible`, and pass the dialogue of the preceding clip as context so the new line stays coherent with the story so far), then regenerate that clip's video using the same forward-chain approach as Prompt 5 (reference the preceding clip's video/audio/last-frame), and update the job store. If `clip_index` is **not** the last clip, return a clear error for now — 501 "mid-sequence regeneration not yet implemented" — don't attempt it here.

**Testing note (just for me):**
Regenerate the last clip's script on a completed job. Confirm the new dialogue is different but still fits the story, and that the new video still visually/vocally matches the clip before it.

> **Note from PLAN.md:** this only handles the *easy* case (last clip, no downstream clip to break). The harder case — regenerating a middle clip without breaking the clip after it — is intentionally deferred to Prompt 11, because `PLAN.md` Section 5/7 flags the bridging approach as **not yet validated**. Don't let the agent quietly extend this same logic to middle clips; it will produce a broken chain if it does.

---

## Prompt 10 — Regenerate Scene (Last Clip Case Only)

**Prompt to give the agent:**
> Implement `POST /jobs/{job_id}/clips/{clip_index}/regenerate-scene` for the last-clip case, mirroring Prompt 9 but keeping the existing dialogue unchanged — only regenerate the video (same forward-chain referencing). Same 501 stub for non-last clips as in Prompt 9.

**Testing note (just for me):**
Regenerate the last clip's scene only, confirm the dialogue text on the dashboard is unchanged, but the video content is a new take.

---

## Prompt 11 — Mid-Sequence Regeneration (Dual Reference Bridging) — EXPERIMENTAL

**Do not give this prompt until you've manually run Test B from `PLAN.md` Section 8 yourself on kie.ai's site first**, and confirmed the dual-reference bridging approach actually produces an acceptable result. This step assumes that's already validated — if it wasn't, stop and re-test manually before writing code around it.

**Prompt to give the agent:**
> Extend `regenerate-script` and `regenerate-scene` to handle the case where `clip_index` has both a preceding and a following clip already generated. Use dual reference bridging: `reference_video_urls=[preceding clip video, following clip video]` tagged `<Video 1>`/`<Video 2>`, `reference_audio_urls=[preceding clip audio, following clip audio]` tagged `<Audio 1>`/`<Audio 2>`, and a prompt template of the form: `"Generate a clip that begins matching the character, setting, and motion in <Video 1>, speaking with the vocal timbre in <Audio 1>, and transitions naturally into a state consistent with <Video 2> and <Audio 2> by the end. {dialogue instruction}"`. After generating, do **not** automatically overwrite the clip in the timeline — return the result as a preview alongside a confirm/discard choice in the UI, since bridging quality isn't guaranteed to be seamless.

**Testing note (just for me):**
This is the riskiest step in the whole build. Test on a real mid-sequence clip and watch both seams (into it, and out of it into the next clip) closely — specifically watch for the "rushed motion trying to arrive somewhere" artifact flagged in `PLAN.md` Section 7. If it looks off on multiple tries, don't force this into production — fall back to "regenerating a middle clip also regenerates everything after it" as a simpler, more reliable (if more expensive) alternative, and tell your agent to build that fallback path instead.

---

## Prompt 12 — Final Video Assembly

**Prompt to give the agent:**
> Add a step (either as part of `run_generation_job` after all clips finish, or a separate endpoint `POST /jobs/{job_id}/assemble`) that concatenates all clip videos in order into a single final video file using ffmpeg, and stores/serves the result so the dashboard can offer a download link.

**Testing note (just for me):**
Download the assembled final video and actually watch it straight through — confirm there's no visible stutter, black-frame gap, or audio pop at the clip boundaries from the concat itself (separate from the AI-generation seam quality you already checked).

---

## Prompt 13 — Cost Estimate Display (Optional / Later)

`PLAN.md` Section 7 flags this as "not needed for the current testing phase" — don't do this until the rest of the pipeline is stable and you're ready to move toward something less purely experimental.

**Prompt to give the agent (when ready):**
> On the dashboard, before a job is submitted, show an estimated credit cost based on duration × resolution rate (480p: 2.4 credits/sec, 720p: 5 credits/sec) × number of clips, accounting for the fact that reference-heavy clips (clip 2 onward) may cost the same per-second rate but worth confirming with kie.ai whether reference inputs add any extra cost on top of the base per-second rate before finalizing this calculation.

**Testing note (just for me):**
Compare the dashboard's estimate against your actual kie.ai billing/credit deduction after a real job completes, and adjust the formula if they don't match.

---

## Summary — Order of Operations

1. Scaffolding → 2. Data models → 3. OpenAI script gen → 4. Seedance wrapper → 5. Forward-chain pipeline → 6. API endpoints → 7. Dashboard UI → 8. Timeline interaction (stubbed) → 9. Regenerate script (last clip) → 10. Regenerate scene (last clip) → 11. Mid-sequence bridging (only after manual validation) → 12. Final assembly → 13. Cost estimate (later, optional).

Don't let the agent jump ahead or bundle steps — each one has its own testing note for a reason, and catching a bad output early (especially Prompts 3, 4, and 5) is much cheaper than discovering it after the whole pipeline is wired together.
