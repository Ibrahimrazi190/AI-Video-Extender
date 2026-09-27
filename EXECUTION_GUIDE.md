# AI Execution Guide — Prompt-by-Prompt Build Order

Companion document to `PLAN.md`. Give these prompts to your AI coding agent **one at a time, in order**. Don't skip ahead — each step assumes the previous one is done and working. After each prompt, run the "Testing note (just for me)" yourself before moving to the next prompt.

Where a step touches something `PLAN.md` flagged as unconfirmed/open, it's called out explicitly so you don't treat it as settled just because code got written for it.

**Modes:** from Prompt 4.6 on, the app has two content modes — **Talking Head** (default) and **Story Time** — chosen by the user on the dashboard and sent as `mode` in the job request. Each mode has its own script prompt, video prompt template and reference formula (`PLAN.md` Section 4). Every testing note from Prompt 4.6 onward says which mode to test; unless it says otherwise, **test both modes** before moving on. Story Time's reference formula for clips after the first is still untested, so it has its own manual test (Prompt 5.5) and its own build step (Prompt 5.6).

**Clip length:** production clips are always 10 seconds. From Prompt 4.6 on, a job can also use 5-second clips (`clip_duration`: `5` or `10`, default `10`) purely to save credits while testing. Never any other value.

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
>
> **Note:** this prompt builds the Talking Head script only. Story Time's script prompt is added in Prompt 4.6.

---

## Prompt 4 — Seedance Client Wrapper

**Prompt to give the agent:**
> In `app.py`'s Seedance helpers section, write a wrapper around the kie.ai Seedance 2.0 Mini API (https://kie.ai/seedance-2-0-mini) using `KIE_API_KEY`. Include: `generate_clip(prompt, resolution, duration=10, reference_video_urls=None, reference_audio_urls=None, reference_image_urls=None) -> dict` that submits the generation request and returns the resulting video URL once complete (poll or use webhook, whichever kie.ai's API supports — check their actual docs for the correct pattern, don't assume). Also write `extract_last_frame(video_url) -> str` (returns an image URL/path — use ffmpeg to grab the last frame) and `extract_audio(video_url) -> str` (returns an audio file URL/path — use ffmpeg to extract the audio track). All reference URL parameters are optional and should simply be omitted from the request payload if not provided.

**Testing note (just for me):**
Manually call `generate_clip()` with a real prompt, no references, 480p, and confirm you get back a working video URL. Then run `extract_last_frame()` and `extract_audio()` on that result and confirm both files are valid (open the image, play the audio). Do this before wiring anything else — if extraction is broken, the whole forward chain silently breaks later.

> **Note from PLAN.md:** Section 6 — confirm the actual valid duration steps and exact parameter names directly against kie.ai's own page for this call, since reseller docs elsewhere used different field names (`start_image` vs `first_frame_url`, etc.). Don't trust this document's assumed names as gospel — verify against kie.ai's live API reference while writing this wrapper.

---

## Prompt 4.5 — Story-Time Audio Test (manual — DONE 2026-09-25)

**Added after Prompt 3's output revealed the script generator was hardcoded to talking-head assumptions only.** You ran **Test C from `PLAN.md` Section 8** yourself on kie.ai, with native Seedance audio and the empty-kitchen voiceover prompt, and liked the output.

**Decision:** Story Time uses **native Seedance voiceover** (`generate_audio: true`, "voiceover narration only, no visible speaker, no lip sync" wording). The OpenAI TTS + ffmpeg mux option is dropped. Prompt 4.6 below is filled in accordingly.

---

## Prompt 4.6 — Add Mode Support and Clip-Length Option (script and first-clip prompts for both modes)

Prompt 4.5's audio decision is filled in below. This step also adds the 5-second/10-second clip-length option, and deliberately stops before Story Time's reference formula for clips after the first: that needs Test S first (Prompt 5.5) and gets built in Prompt 5.6.

**Prompt to give the agent:**
> We're adding a second content mode to the pipeline, `mode`, either `"talking_head"` (existing, default) or `"story_time"` (new), plus a clip-length option for cheaper testing. The user picks both on the dashboard later; for now they just have to flow through the backend. Update `app.py`:
> - Models: add `mode` to `ClipRequest` (default `"talking_head"`) and to `Job`. Add `clip_duration` to `ClipRequest`: only `5` or `10`, default `10` (`CLIP_DURATION`). Production is always 10; 5 exists only to save credits while testing. `ClipRequest.duration` (total video length) must be a multiple of the request's `clip_duration`, and the number of clips is `duration / clip_duration`. Add optional `narration` and `visual` string fields to `Clip` (`dialogue` stays for Talking Head).
> - Update `generate_script()` to take `mode` and `clip_duration` arguments (default `CLIP_DURATION`) and use a separate system prompt per mode. Both prompts must use the clip duration and the word budget derived from it (about `round(clip_duration * 2.2)` words, never more than `round(clip_duration * 2.6)`) instead of a hard-coded 10. Keep the existing Talking Head prompt and output otherwise unchanged. For `story_time`, script objects have `narration` + `visual` + `delivery` instead of `dialogue`, and the system prompt is this one (fill in the `{...}` values the same way the Talking Head prompt does):
>
> ```
> You write scripts for a short AI-generated "story time" video: a voiceover narrator tells a story over visuals that change from scene to scene. The video is split into {num_clips} consecutive clips of {clip_duration} seconds each. The user gives you the topic.
>
> Return a JSON object with two keys.
>
> "scene_bible": ONE fixed description that is pasted unchanged in front of every clip's video prompt. It must cover (1) the recurring characters' appearance (age, build, hair, face, clothing), (2) the overall world and visual style (era, look, color palette, lighting, camera style, for example "realistic cinematic style, soft natural morning light"), and (3) the narrator's voice (for example "a wistful female voice": describe only how the voice sounds, its age range, gender, tone and pace). Be concrete and visual. Do not describe any single scene's action and do not tie it to one room: the scenes change from clip to clip and this description must stay true for all of them. No dialogue, no story events, no mention of clip numbers.
>
> "clips": a list of exactly {num_clips} objects, in order, each with:
> - "narration": what the narrator says out loud during this clip. Natural spoken language, addressed to the viewer, in the narrator's voice. Aim for about {target_words} words and never exceed {max_words}, so it can be said comfortably within {clip_duration} seconds. Spoken words only: no stage directions, no emojis, no hashtags, no speaker labels, and no double quotation marks anywhere in the line (the line gets wrapped in double quotes later).
> - "visual": what is on screen during this clip, in one or two concrete sentences: the location, who or what is visible (or "no people visible"), what they are doing, and the shot type (wide, medium, close-up). The scene should usually differ from the previous clip's, while the recurring characters and the visual style stay the same. It shows what the narration is about, but it must not contain spoken words, on-screen text or captions, and nobody on screen speaks to the camera. The FIRST clip's visual must clearly show the main recurring character on screen (face and clothing visible): this clip is used as the character's visual reference for the rest of the video. Clips after the first may or may not show the character.
> - "delivery": a short phrase (3-8 words) describing the narrator's tone and emotion in this clip, for example "quiet and heavy" or "lighter, a faint smile in the voice". It should evolve as the story does.
>
> The narration lines together must form ONE continuous, coherent story with a beginning, a middle and an end. Each line picks up exactly where the previous one stopped: never restart, re-introduce the story or repeat an earlier point, and let the final line bring the story to a natural close. They must never read as separate, isolated statements. The visuals follow the story from scene to scene.
>
> Return strictly valid JSON matching the schema, and nothing else.
> ```
>
> - Add `build_clip_prompt(mode, scene_bible, clip, is_first_clip)` in the Seedance helpers section (Prompt 5 will use it), stripping any trailing period from `scene_bible` before inserting it. For `talking_head`, use exactly these templates: clip 0 `"{scene_bible}. She speaks directly to camera, {delivery}: \"{dialogue}\" Natural lip sync to dialogue, no background music, no score."`, and clip N>0 `"Continuing directly from <Video 1>, {scene_bible}, still speaking to camera, {delivery}: \"{dialogue}\" Natural lip sync to dialogue, same lighting and camera style, no background music, no score."`. For `story_time`, implement the **first-clip template only**: `"{visual}. {scene_bible}. Voiceover narration only, {delivery}, no visible speaker, no lip sync needed since no one is speaking on camera: \"{narration}\" Natural ambient sound only, no music, no score — just the voiceover."` (native Seedance voiceover with `generate_audio=True`, as validated in Test C). For story-time clips after the first, raise `NotImplementedError` with a clear message — their reference inputs and continuation wording are decided by Test S and built in Prompt 5.6.
> - Don't change anything else about Talking Head behavior.

**Testing note (just for me):**
Call `generate_script()` in both modes with a topic that suits each (the sofa story for Talking Head; something that naturally moves through several scenes for Story Time) and read the output closely, like Prompt 3. For Story Time check: does `scene_bible` include the narrator's voice and stay true across different scenes; does each `visual` describe a different, concrete scene; do the narration lines read as one continuous story; and does the first clip's `visual` clearly show the main character on screen (also try a topic that would naturally open on scenery, to see whether it still does)? Call it once with `clip_duration=5` and confirm the lines drop to roughly 11 words. Then check `ClipRequest`: `clip_duration` 5 and 10 are accepted, 7 is rejected, and `duration=30` with `clip_duration=5` gives 6 clips. Print the built prompt for a Talking Head clip 0 and clip 1 and confirm they match the two templates above, and print a Story Time clip 0 prompt and compare it with your Test C prompt. No video generation in this step — the pipeline that calls these doesn't exist until Prompt 5.

---

## Prompt 5 — Core Pipeline: Forward-Chain Generation, Talking Head (Celery Task)

**Note:** this prompt builds the **Talking Head** chain. `build_clip_prompt()` already exists from Prompt 4.6, so use it instead of writing a new helper. Story Time's chain comes later, after Test S (Prompts 5.5–5.6).

**Revised 2026-09-26 ("Formula B"):** the first version of this prompt chained all three references from the previous clip. A real 3-clip job then showed the face drifting by clip 3 and the audio degrading at the end of the last clip (`PLAN.md` Test E). Formula B kept only the previous clip's *video* chained (later muted, after Test F) and fixed the audio and last-frame references to the **first** clip's.

**Revised again 2026-09-27 ("720p master", built):** on 5 clips any video reference chained from the previous clip still compounded quality loss, and so did the last 2 seconds of it, along with a growing "gliding" motion. A fixed 720p first clip plus its audio, with nothing from the previous clip, came out best (`PLAN.md` Tests G to I). The prompt below is the current version.

**Prompt to give the agent:**
> In `app.py`'s Celery task section, write a Celery task `run_generation_job(job_id: str)` that: (1) loads the job from the store, (2) calls `generate_script()` to get `scene_bible` and clip dialogue, (3) loops through clips in order and generates each one using the `generate_clip()` helper (passing the job's `clip_duration` as `duration`), building the prompt via the existing `build_clip_prompt()` (from Prompt 4.6, `talking_head` mode), which uses these two fixed templates:
> - Clip 0 (first, the master): `"{scene_bible}. She speaks directly to camera, {delivery}: \"{dialogue}\" Natural lip sync to dialogue, no background music, no score."` — no reference inputs, `generate_audio=True`, and **always rendered at 720p** (`MASTER_RESOLUTION`), whatever the job's resolution.
> - Clip N (N>0): `"Continuing directly from <Video 1>, {scene_bible}, still speaking to camera, {delivery}: \"{dialogue}\" Natural lip sync to dialogue, same lighting and camera style, no background music, no score."` — rendered at the job's resolution, with exactly two references, the same two files for every later clip: `reference_video_urls=[a MUTED copy of clip 0's video]` and `reference_audio_urls=[clip 0's audio]`. No image reference, and nothing from the previous clip.
>
> After clip 0 generates, extract its audio and make a muted copy of its video (add a `mute_video(video_url)` helper: `ffmpeg -i in.mp4 -an -c:v copy out.mp4`, the video stream copied untouched, uploaded to kie.ai's file host like the extracted files), and store both on the job as fixed anchors for the whole job (`anchor_video_url`, `anchor_audio_url`, `anchor_extracted_at` on `Job`) and on clip 0 (`audio_url`, `muted_video_url`, `muted_video_at`). Later clips need no processing of their own. Record each clip's rendered resolution on the clip (`Clip.resolution`). The original videos stay in `video_url` for the final stitch. Update the job store so each clip's status becomes `done` (or `failed` with an error message on exception — don't let one failed clip crash the whole task, mark it failed and stop the chain there). Also save the `scene_bible` on the job (add a `scene_bible` field to `Job`) so later regenerate steps can reuse it, and add an `error` field to `Clip` to hold the failure message. If the job's `mode` is `story_time`, mark the job failed with the message "story_time pipeline not implemented yet" instead of running it (until Prompt 5.6, which replaced this).

**Testing note (just for me):**
Kick off a real job for a 5-clip topic and watch it process end-to-end. Run it first with 5-second clips to save credits (about 137 credits: clip 0 at 720p about 41, each later clip about 24), then once at the production 10-second length (clip 0 about 82 and each later clip about 48, since the 10 s master is billed on every clip). Check the job store after: are all clips marked `done` with a video URL, is clip 0's `resolution` 720p and the rest the job's, does the job have `anchor_video_url` and `anchor_audio_url` set (and clip 0 its `muted_video_url` and `audio_url`), and do the later clips have no muted copy, audio or last frame of their own? Does `video_url` still play WITH sound? Watch for quality staying level from clip 2 to the last clip, for the first clip's speech ghosting into later clips, and for the expected small pose reset at each cut. The 720p-master formula was tested through a standalone script (Test I), not yet through the worker. This step covers Talking Head only; Story Time's chain comes after Test S.

---

## Prompt 5.5 — Story-Time Reference Test (manual — DONE 2026-09-26)

You ran **Test S from `PLAN.md` Section 8** yourself: 7 clips at 5 seconds, 480p, comparing three reference formulas on a small story with three different scenes.

**Result:** **Variant 3 won** — the previous clip's video + the first clip's audio (fixed) + the first clip's last frame as a fixed character image, with "The main character looks exactly like @Image1." in the prompt. All three variants performed similarly well at 5 seconds and 3 clips on scene change, style consistency, narrator voice and audio bleed. Variant 3 was chosen anyway because its fixed anchors (every clip re-anchored to the first clip's audio and image, not to the immediately preceding clip) should stop identity drift from compounding over longer videos, a failure mode this short test couldn't surface but which matters for production-length Story Time videos with many clips. Prompt 5.6 below is filled in with this formula.

**Separate finding (parked, `PLAN.md` Section 7, question 12):** face distortion in a walking, motion-heavy shot on `bytedance/seedance-2-mini`, shown by isolated playground testing to be a model limitation (the same shot on `seedance-2-5` rendered cleanly). Not part of Test S's conclusion, and no action now.

---

## Prompt 5.6 — Story-Time Forward Chain (built 2026-09-27)

Test S's winning formula (Variant 3, fixed anchors) is filled in below, with one addition decided on 2026-09-27 (`PLAN.md` Section 7, question 14): the chained video reference is a **muted** copy of the previous clip.

**Prompt to give the agent:**
> Extend `run_generation_job` so jobs with `mode == "story_time"` run instead of failing. Clip 0 (the first clip) uses the story-time first-clip template from Prompt 4.6 (no references, `generate_audio=True`). As soon as clip 0 finishes, extract its audio (`extract_audio`) and its last frame (`extract_last_frame`) and store both URLs on the job as fixed anchors for the whole job (the `Job` already has `anchor_audio_url`, `anchor_image_url` and `anchor_extracted_at`; since 2026-09-27 Talking Head fills `anchor_audio_url` and `anchor_video_url` but not `anchor_image_url`, so Story Time sets the image itself; reuse the fields, and keep clip 0's video URL as well). For every clip after the first, send: `reference_video_urls=[a MUTED copy of the previous clip's video]` (the only reference that chains from clip to clip; reuse the existing `mute_video()` helper). Every clip except the last becomes the next clip's video reference, so each one needs its own muted copy made right after it generates, not just clip 0 as in Talking Head. Add this to the per-clip loop, store it on the clip (`muted_video_url`, `muted_video_at`), and keep it for the following iteration to use. The original, unmuted video stays in `video_url` for the final stitch. Also send `reference_audio_urls=[the job's anchor audio, i.e. clip 0's audio, the same URL for every later clip, NOT the previous clip's audio]`, and `reference_image_urls=[the job's anchor image, i.e. clip 0's last frame, the same URL for every later clip]`, with `generate_audio=True`. Later clips need no audio or last-frame extraction of their own in this mode. Implement the story-time continuation template in `build_clip_prompt()` (it currently raises `NotImplementedError`) as: `"Same characters, visual style and lighting as @Video1, but a new scene: {visual}. {scene_bible}. The main character looks exactly like @Image1. Voiceover narration only, in the same narrator voice as @Audio1, {delivery}, no visible speaker, no lip sync needed since no one is speaking on camera: \"{narration}\" Natural ambient sound only, no music, no score — just the voiceover."`, stripping the trailing period from `scene_bible` like the other templates. `@Video1`, `@Audio1` and `@Image1` are correct as written (validated in Test S): exactly one of each is sent per request, so the number is always 1. Keep the same failure handling as Prompt 5 (mark the clip failed with an error message and stop the chain there). Don't change Talking Head behavior.

**Code notes (flags for this step):**
- **Resolved 2026-09-27 (`PLAN.md` Section 7, question 14): Story Time keeps its chained video reference, now muted.** Test S already showed that a chained video reference doesn't block scene progression across a real 3-scene sequence. Muting is a precaution carried over from Talking Head's diagnosed fix: a video reference silently carries its own audio track, which competed with the fixed voice anchor. **Left open on purpose:** whether a long Story Time chain (5+ clips) still degrades in quality the way Talking Head's did (`PLAN.md` Test G). It is to be observed the first time a real longer job runs, not pre-tested now.
- **The anchors must live for the whole job.** Like Talking Head since 2026-09-27, this formula needs clip 0's audio URL and last-frame URL when generating **every** later clip, not just clip 2. Store them on the job when clip 0 finishes (not only in the task's local variables) and reuse them unchanged for all later clips.
- **They expire.** Both files are uploaded to kie.ai's file host, which deletes uploads after 24 hours (per its docs). One job's chain finishes well inside that (about 2.5 minutes per 5-second clip), but a regenerate done later (Prompts 9–10), or a very long job, can find them dead. Because clip 0's video URL lasts 14 days, add a small helper that re-runs `extract_audio` / `extract_last_frame` on clip 0's video and refreshes the stored anchors when `anchor_extracted_at` is older than about 23 hours (or when kie.ai rejects a reference URL), and use it before every Story Time generation.
- **The formula needs clip 0 to show the main character on screen.** The fixed image is clip 0's last frame, and "looks exactly like @Image1" only makes sense if that frame shows the character. Prompt 4.6's Story Time script prompt now requires the first clip's `visual` to clearly show the main character, but that is enforced only by the prompt, not checked in code. If a first clip still comes back without the character, the anchor image is wrong for the whole job; a code-level check is possible later but is not part of this step.

**Testing note (just for me):**
Run a full 3-clip Story Time job at the production 10-second clip length (this confirms Test S's 5-second winner at real length, now through real code; you can do a 5-second run first to save credits) and check: does the scene change from clip to clip, do the character and style stay consistent, is the narrator's voice the same in all three clips, and is there any lip-sync attempt or leaked music/ambient sound? Then check the job store: `anchor_audio_url` and `anchor_image_url` were set once after clip 0 and never change, every clip except the last has a `muted_video_url`, `video_url` still plays WITH sound, and the later clips have no extracted audio or last frame of their own (expected in this mode). The first time a longer Story Time job (5+ clips) runs, watch whether quality falls off down the chain, as Talking Head's did; this is a watch item, not a blocker. Then run one Talking Head job and confirm nothing regressed from Prompt 5.

---

## Prompt 6 — FastAPI Endpoints

**Prompt to give the agent:**
> In `app.py`'s FastAPI section, add these endpoints: `POST /jobs` (accepts a `ClipRequest` — including `mode` and `clip_duration` — creates a job in the store with those settings, kicks off `run_generation_job` as a Celery task, returns the job id), `GET /jobs/{job_id}` (returns full job state including all clips and their current status/URLs — used for polling from the dashboard).

**Testing note (just for me):**
Hit `POST /jobs` with a real topic via curl/Postman — once with `mode: talking_head` and once with `mode: story_time` — grab each job id, then poll `GET /jobs/{job_id}` every few seconds and watch clip statuses flip from `pending` → `generating` → `done`. Confirm the final response includes playable video URLs for every clip in both modes, and that an invalid `mode` value is rejected with a 422. Try one job with `clip_duration: 5` as well, and confirm a `clip_duration` of 7 is rejected.

---

## Prompt 7 — Dashboard Frontend (Single Page)

**Prompt to give the agent:**
> Build the single-page dashboard in `dashboard.html` (plain HTML/JS, no build step/framework needed for something this small) with: a text input for the topic, a clip-length toggle (10 seconds by default, sent as `clip_duration`; a second option, 5 seconds, labelled "testing — cheaper"), a duration selector (multiples of the chosen clip length, so the total video length follows it), a resolution toggle (480p / 720p, defaulting to 480p), a **mode selector** (Talking Head / Story Time, defaulting to Talking Head, with a one-line description under each — Talking Head: "one person speaking to camera"; Story Time: "changing scenes with a voiceover narrator") that is sent as `mode` in the request, and a "Generate" button that calls `POST /jobs` and then polls `GET /jobs/{job_id}` until complete. Once complete, render a horizontal timeline with one segment per clip, labelled to match the mode (the spoken line for Talking Head; the narration plus a short visual description for Story Time). No login, no navigation, no other pages. Serve this file as a static file from the FastAPI app in `app.py` (e.g. `GET /` returns `dashboard.html`).

**Testing note (just for me):**
Submit a job from the actual UI, not curl this time, and confirm the timeline renders once generation finishes and each segment corresponds to the right clip in order. Do this once in each mode: confirm the selector really changes the `mode` sent to `POST /jobs` (check the network tab), and that each mode's timeline shows the right fields.

---

## Prompt 8 — Timeline Clip Interaction

**Prompt to give the agent:**
> On the dashboard timeline, clicking a clip segment should show: its script text (the `dialogue` in Talking Head; the `narration` and `visual` in Story Time), and two buttons — "Regenerate Script" and "Regenerate Scene". For now, just wire the UI and have both buttons call placeholder endpoints (`POST /jobs/{job_id}/clips/{clip_index}/regenerate-script` and `.../regenerate-scene`) that don't need to be implemented yet — return a 501/"not implemented" stub from the backend for now. This step is UI wiring only.

**Testing note (just for me):**
Click a few clips, confirm the right script text shows for each, confirm both buttons fire the correct API calls (check network tab / logs), even though they don't do anything real yet. Do this on one job from each mode.

---

## Prompt 9 — Regenerate Script (Last Clip Case Only) (built 2026-09-27)

**Prompt to give the agent:**
> Implement `POST /jobs/{job_id}/clips/{clip_index}/regenerate-script` for the case where `clip_index` is the **last clip** in the job. It should: generate a new dialogue line for that clip via OpenAI (reusing the existing `scene_bible`, and pass the dialogue of the preceding clip as context so the new line stays coherent with the story so far), then regenerate that clip's video using the same approach as Prompt 5 (at the job's resolution, with the job's fixed anchors: `anchor_video_url`, the muted 720p first clip, as `reference_video_urls` and `anchor_audio_url` as `reference_audio_urls`, and no image; if `anchor_extracted_at` is older than about 23 hours, re-extract the audio and re-mute the video from the first clip's `video_url` first, since kie.ai deletes uploads after 24 hours), and update the job store. If the last clip is clip 0 (a 1-clip job), it is the master: regenerate it at 720p with no references, then re-make the anchors from the new video. For a `story_time` job, do the same with the clip's `narration` (keeping its existing `visual`) and use the Story Time forward-chain formula from Prompt 5.6 instead of the Talking Head one: the preceding clip's `muted_video_url` (re-mute it from that clip's `video_url` if `muted_video_at` is older than about 23 hours), plus the job's `anchor_audio_url` and `anchor_image_url` (refreshed with `_fresh_story_anchors()`). If `clip_index` is **not** the last clip, return a clear error for now — 501 "mid-sequence regeneration not yet implemented" — don't attempt it here.

**Testing note (just for me):**
Regenerate the last clip's script on a completed job. Confirm the new dialogue is different but still fits the story, and that the new video still visually/vocally matches the clip before it. Do this once per mode.

> **Note from PLAN.md:** this only handles the *easy* case (last clip, no downstream clip to break). The harder case — regenerating a middle clip without breaking the clip after it — is intentionally deferred to Prompt 11, because `PLAN.md` Section 5/7 flags the bridging approach as **not yet validated**. Don't let the agent quietly extend this same logic to middle clips; it will produce a broken chain if it does.
>
> **Decided 2026-09-27 (`PLAN.md` Section 7, question 8):** in Story Time, Regenerate Script writes new narration only and keeps the clip's `visual`, as this prompt says. Middle clips and the cascade problem are set aside for now.
>
> **Note (2026-09-27):** in Talking Head, no clip depends on the one before it any more (every later clip is made from the first clip only), so the cascade problem behind the last-clip-only limit no longer applies there, except for clip 0, which every later clip was made from. Whether to let Talking Head regenerate any clip after the first this way is undecided (`PLAN.md` Section 7, question 1); until it is decided, keep the limit.

---

## Prompt 10 — Regenerate Scene (Last Clip Case Only) (built 2026-09-27)

**Prompt to give the agent:**
> Implement `POST /jobs/{job_id}/clips/{clip_index}/regenerate-scene` for the last-clip case, mirroring Prompt 9 but keeping the existing dialogue unchanged — only regenerate the video (same references as Prompt 9). For a `story_time` job, keep the `narration` word for word and change the scene (decided 2026-09-27, `PLAN.md` Section 7, question 8): ask OpenAI for a **new** `visual`, a different scene that still fits the same narration and the story, then render the clip again from it with the Story Time references. It is not a new take of the old `visual`. Same 501 stub for non-last clips as in Prompt 9. Prompt 9's `regenerate_script_task`, `_render_clip()` and `_claim_for_regeneration()` (renamed `_claim_job()` in Prompt 12) can be reused.

**Testing note (just for me):**
Regenerate the last clip's scene only, confirm the dialogue text on the dashboard is unchanged, but the video content is a new take. Do this once per mode.

---

## Prompt 11 — Mid-Sequence Regeneration (Dual Reference Bridging) — EXPERIMENTAL

**Do not give this prompt until you've manually run Test B (Talking Head) and Test D (Story Time) from `PLAN.md` Section 8 yourself on kie.ai's site first**, and confirmed the dual-reference bridging approach actually produces an acceptable result in each mode you plan to support — the two modes can behave differently, so one passing doesn't validate the other. This step assumes that's already validated — if it wasn't, stop and re-test manually before writing code around it.

**Possibly not needed for Talking Head (2026-09-27):** its clips no longer depend on the previous clip, so a middle clip may be regenerated like the last one, from the master, with no bridging. Decide this (`PLAN.md` Section 7, question 1) before running Test B or giving this prompt for Talking Head. Story Time's planned formula still chains, so this prompt still applies there.

**Known constraint:** kie.ai caps all reference videos in one request at 15 seconds total, and reference audios at 15 seconds total. Two 10-second clips is 20 seconds, so the request below would be rejected at production clip length. Decide how to fit it before giving this prompt (for example, trim each reference to 7 seconds or less with ffmpeg) and tell the agent. For Story Time, also replace the "speaking with the vocal timbre in <Audio 1>" part of the template with the wording that worked in Test D. Also note that later clips no longer have their own extracted audio or last frame (only the first clip's are stored, on the job), so bridging must extract the following clip's audio from its video on demand. Reference videos should be muted copies too (`mute_video`).

**Prompt to give the agent:**
> Extend `regenerate-script` and `regenerate-scene` to handle the case where `clip_index` has both a preceding and a following clip already generated. Use dual reference bridging: `reference_video_urls=[preceding clip video, following clip video]` tagged `<Video 1>`/`<Video 2>`, `reference_audio_urls=[preceding clip audio, following clip audio]` tagged `<Audio 1>`/`<Audio 2>`, and a prompt template of the form: `"Generate a clip that begins matching the character, setting, and motion in <Video 1>, speaking with the vocal timbre in <Audio 1>, and transitions naturally into a state consistent with <Video 2> and <Audio 2> by the end. {dialogue instruction}"`. After generating, do **not** automatically overwrite the clip in the timeline — return the result as a preview alongside a confirm/discard choice in the UI, since bridging quality isn't guaranteed to be seamless.

**Testing note (just for me):**
This is the riskiest step in the whole build. Test on a real mid-sequence clip (once per mode) and watch both seams (into it, and out of it into the next clip) closely — specifically watch for the "rushed motion trying to arrive somewhere" artifact flagged in `PLAN.md` Section 7. If it looks off on multiple tries, don't force this into production — fall back to "regenerating a middle clip also regenerates everything after it" as a simpler, more reliable (if more expensive) alternative, and tell your agent to build that fallback path instead.

---

## Prompt 12 — Final Video Assembly (built 2026-09-27; Prompt 11 deferred until after it)

**Prompt to give the agent:**
> Add a step (either as part of `run_generation_job` after all clips finish, or a separate endpoint `POST /jobs/{job_id}/assemble`) that first downloads all clip videos from kie.ai (kie.ai deletes generated videos after 14 days), then concatenates them in order into a single final video file using ffmpeg, and stores/serves the result so the dashboard can offer a download link. In Talking Head the first clip is always 720p (1280x720) while the rest are the job's resolution (864x496 at 480p), so a plain stream-copy join won't work: scale every clip to the job's resolution (each clip's `resolution` is on the `Clip`) and re-encode at high quality.

**Testing note (just for me):**
Download the assembled final video and actually watch it straight through — confirm there's no visible stutter, black-frame gap, or audio pop at the clip boundaries from the concat itself (separate from the AI-generation seam quality you already checked). Do this for a job from each mode; Story Time clips have different scenes, so also check that the audio level and ambient sound stay steady across the joins.

---

## Prompt 13 — Cost Estimate Display (Optional / Later)

`PLAN.md` Section 7 flags this as "not needed for the current testing phase" — don't do this until the rest of the pipeline is stable and you're ready to move toward something less purely experimental.

**Measured since this prompt was written (`PLAN.md` Section 2):** a clip with a reference video costs 2.4 credits per second of (output + reference video). Reference audio and images don't appear to be billed. A clip with no references costs 3.8 credits/s at 480p and 8.2 credits/s at 720p. So a Talking Head job costs about 8.2 × clip length for the 720p first clip, plus 2.4 × (2 × clip length) for each later clip. That's 41 + 24 per later clip at 5 s, and about 82 + 48 per later clip at 10 s. Later clips at 720p output are unmeasured. Update the prompt below with this before giving it.

**Prompt to give the agent (when ready):**
> On the dashboard, before a job is submitted, show an estimated credit cost based on duration × resolution rate (480p: 3.8 credits/sec as measured on 2026-09-25, since `PLAN.md` Section 2's 2.4 turned out to be wrong; 720p: not measured yet, so check it before trusting `PLAN.md`'s 5) × number of clips, accounting for the fact that reference-heavy clips (clip 2 onward) may cost the same per-second rate but worth confirming with kie.ai whether reference inputs add any extra cost on top of the base per-second rate before finalizing this calculation.

**Testing note (just for me):**
Compare the dashboard's estimate against your actual kie.ai billing/credit deduction after a real job completes, and adjust the formula if they don't match. Measure a 720p clip's real cost once, and check whether clips with references cost more than a first clip. The cost should be the same in both modes, but confirm it.

---

## Summary — Order of Operations

1. Scaffolding → 2. Data models → 3. OpenAI script gen (Talking Head) → 4. Seedance wrapper → 4.5. Story-time audio test (manual, done) → 4.6. Mode support (script + first-clip prompts for both modes) → 5. Talking Head pipeline (720p master) → 5.5. Story-time reference test (manual, Test S) → 5.6. Story-time forward chain (after Test S) → 6. API endpoints → 7. Dashboard UI (with mode selector) → 8. Timeline interaction (stubbed) → 9. Regenerate script (last clip) → 10. Regenerate scene (last clip) → 11. Mid-sequence bridging (only after manual validation in each mode) → 12. Final assembly → 13. Cost estimate (later, optional).

From 4.6 on, every step is tested in both modes unless its testing note says otherwise.

Don't let the agent jump ahead or bundle steps — each one has its own testing note for a reason, and catching a bad output early (especially Prompts 3, 4, and 5) is much cheaper than discovering it after the whole pipeline is wired together.
