# AI Video Extender — Development Plan

## 1. What This Is

A pivot from the old fact-video SaaS to an **AI video extender**: user submits a topic + target duration + resolution (480p/720p) + **mode** (Talking Head or Story Time), the system generates a continuous multi-clip AI video where each 10-second clip continues from the last — Talking Head: the same person speaking to camera; Story Time: scenes that change from clip to clip under a consistent voiceover narrator — using OpenAI for script and kie.ai's Seedance 2.0 Mini for audio+video generation.

No login, no signup, no user accounts. Single dashboard page. Backend does the heavy lifting.

---

## 2. Tech Stack

- **Backend:** FastAPI — owns all API endpoints, kicks off generation jobs
- **Queue:** Redis
- **Workers:** Celery — runs the actual pipeline steps (script gen, per-clip video gen, stitching) as background tasks so the API stays responsive
- **Frontend:** One dashboard page. Takes a topic prompt + duration + **resolution (480p or 720p)** + **mode (Talking Head or Story Time)**. The mode is chosen by the user at submission time and decides which script prompt, video template and reference formula the backend uses (Section 4). Shows a timeline of clips once generation completes.
- **External APIs:**
  - OpenAI (API key already held) — script/scene/dialogue generation
  - kie.ai Seedance 2.0 Mini (API key already held) — video + audio generation, referencing: https://kie.ai/seedance-2-0-mini

### Pricing (Seedance 2.0 Mini, per kie.ai)

| Resolution | Cost |
|---|---|
| 480p | 2.4 credits/second |
| 720p | 5 credits/second |

**Default for testing: 480p**, to conserve credits. Both options should be exposed in the dashboard so it's a toggle, not a hardcoded value — but current testing (Section 8) will run at 480p unless stated otherwise.

> **Measured 2026-09-25 (Prompt 4 test run: 480p, audio on, no references): 3.8 credits/second.** A 5-second clip cost 19 credits, not the 12 the 2.4/s above predicts; an earlier logged run of 38 credits is consistent with a 10-second clip at the same rate (duration not yet confirmed). The 720p rate, and whether reference inputs add cost, have not been measured. **Clips that use reference inputs (video + audio + image) cost 24 credits for 5 seconds, about 4.8 credits/second, measured on the two Formula B clips (2026-09-26).** Treat the table above as outdated until Prompt 13 reconciles it.

> **Billing pattern found 2026-09-26/27 (Tests G to I, Section 8):** a clip with a reference video costs **2.4 credits per second of (output + reference video)**. It fits every clip measured so far: 5 s output + 5 s reference video = 24; + 2 s = 16.8; + 2 s + 5 s = 28.8. Reference audio and image seconds don't appear to be billed. A clip with no references costs 3.8 credits/second at 480p and **8.2 credits/second at 720p (41 credits for 5 s, measured 2026-09-26)**. All clips with references so far had 480p output; 720p output with references is unmeasured.

## 3. Project Structure (single-file backend)

No large directory tree, no auth layers, no multi-service split — and now, no split between backend logic files either. All Python logic lives in **one file**, organized top-to-bottom by section, with small single-purpose helper functions rather than a few giant ones. The FastAPI app and the Celery task share this same file and same imports.

```
/app.py              # everything: config, models, Redis store helpers, OpenAI helper,
                      # Seedance helpers, the Celery orchestrator task, FastAPI app + routes
/dashboard.html       # the single-page frontend — necessarily separate, it's not Python
.env
requirements.txt
docker-compose.yml    # fastapi + redis + celery worker, both processes import app.py
```

Internal layout of `app.py`, in order:

1. Imports
2. Config — env vars (`OPENAI_API_KEY`, `KIE_API_KEY`), constants (`CLIP_DURATION=10`, per-resolution credit rates; a job may also choose 5-second clips, testing only)
3. Celery app setup — instance, Redis as broker
4. Pydantic models — `ClipRequest` (includes `mode`), `Clip`, `Job`
5. Redis store helpers — `save_job()`, `get_job()`, `update_clip()`
6. OpenAI helper — `generate_script()` (separate system prompt per mode)
7. Seedance helpers — `build_clip_prompt()` (branches on mode), `generate_clip()`, `extract_last_frame()`, `extract_audio()`, `mute_video()`
8. Celery task — `run_generation_job()` (the orchestrator — calls the helpers above in sequence, contains almost no logic of its own)
9. FastAPI app + routes — `/health`, `POST /jobs`, `GET /jobs/{id}`, regenerate endpoints

Run with two processes against the same file: `uvicorn app:app` for the API, `celery -A app.celery_app worker` for the worker.

**Escape hatch, not a rule to decide now:** if `app.py` grows past roughly 500–600 lines once regenerate logic, mid-sequence bridging, and cost estimation are all added, that's the natural trigger to peel the OpenAI/Seedance helper functions (sections 6–7 above) out into their own file. Not required today — just don't be surprised if it becomes worth doing later.

---

## 4. Core Pipeline

The user picks a **mode** on the dashboard when submitting a job (`mode` on `ClipRequest`: `"talking_head"`, the default, or `"story_time"`). The mode changes three things: the OpenAI script prompt and its output fields (Step 1), the video prompt template and which reference inputs are sent for clips after the first (Step 2), and what the timeline shows for each clip. Resolution, the clip length (10 seconds, or 5 for cheap testing), polling, frame/audio extraction and final assembly work the same in both modes.

| | Talking Head | Story Time |
|---|---|---|
| What the viewer sees | One person speaking directly to camera | Scenes that change from clip to clip (people, places, actions); nobody speaks on camera |
| Audio | Native Seedance audio, lip-synced dialogue | Native Seedance **voiceover narration** (no lip sync), natural ambient sound only |
| Script fields per clip | `dialogue`, `delivery` | `narration`, `visual` (what is on screen), `delivery` |
| `scene_bible` | Speaker + room, fixed | Characters, world and visual style, plus the narrator's voice (e.g. "wistful female voice"); fixed, but not tied to one room |
| Status | Built first; the default. Since 2026-09-27: a 720p first clip is the master for every later clip (Tests G to I) | Audio approach validated (Test C). Built 2026-09-27 (Prompt 5.6): each clip after the first gets a **muted** copy of the previous clip's video (chained), plus the first clip's audio and last frame (fixed). That is Test S's Variant 3 with muting added (Section 7, question 14, resolved). Whether a long chain (5+ clips) degrades is a watch item for the first real long job. A model-quality question on motion shots is parked (Section 7, question 12) |

Below, anything that differs by mode is labelled.

### Step 1 — Script/Scene Generation (OpenAI)

One OpenAI call per video job, using the system prompt for the selected mode. Input: topic + duration. Output: structured JSON.

- **Clip length is 10 seconds in production, always.** For cheaper testing a job can use **5-second** clips instead (`clip_duration` on `ClipRequest`: `5` or `10`, default `10`; no other values). `duration` is the total video length and must be a multiple of the clip length. Number of clips = `duration / clip_duration`. The script prompt's word budget scales with the clip length (about 2.2 words per second).
- Output schema, **Talking Head** (roughly):

```json
{
  "scene_bible": "Fixed description of character, setting, framing, style — reused unchanged in every clip's prompt",
  "clips": [
    { "dialogue": "...", "delivery": "tone/emotion direction for this line" },
    { "dialogue": "...", "delivery": "..." }
  ]
}
```

- Output schema, **Story Time** (roughly):

```json
{
  "scene_bible": "Fixed description of the characters, world, visual style and the narrator's voice — reused unchanged in every clip's prompt",
  "clips": [
    { "narration": "...", "visual": "what is on screen in this clip", "delivery": "tone/emotion direction for the narrator" },
    { "narration": "...", "visual": "...", "delivery": "..." }
  ]
}
```

- `scene_bible` generated **once**, reused verbatim across every clip's prompt template — this is what keeps character/setting consistent, not manual prompt writing. (In Story Time the `visual` is what changes per clip, so the `scene_bible` has to stay true across all of those scenes.)
- `delivery` is generated by OpenAI per clip, not hand-written.

### Step 2 — Per-Clip Video+Audio Generation (kie.ai Seedance 2.0 Mini)

Loop through clips in order. Every clip in a given job uses the same `resolution` value (`480p` or `720p`) — chosen once by the user at job submission time on the dashboard, not per clip — and the same `mode`. **Exception (since 2026-09-27): in Talking Head the first clip is always rendered at 720p**, because it is the master every later clip is generated from; the rest use the job's resolution. Each clip records the resolution it was rendered at (`Clip.resolution`). Prompt is assembled from a **fixed code template** for that mode, not written by a human per request:

#### Talking Head

**Clip 1 (first in sequence) = the master:**
- No reference inputs.
- `generate_audio: true`.
- `resolution`: **always 720p** (`MASTER_RESOLUTION`), whatever the job's resolution.
- Prompt: `"{scene_bible}. She speaks directly to camera, {delivery}: \"{dialogue}\" Natural lip sync to dialogue, no background music, no score."`

**Clip N (N > 1): the 720p master and its audio, nothing else (since 2026-09-27, Tests G to I):**
- `resolution`: the job's (480p or 720p).
- `reference_video_urls`: [a **muted copy** of the first clip's video] — the same file for every later clip. Muted so it carries pictures only and cannot leak the first clip's speech.
- `reference_audio_urls`: [the **first** clip's extracted audio] — the same file for every later clip.
- No image reference, and **nothing from the previous clip**.
- Prompt: unchanged, `"Continuing directly from <Video 1>, {scene_bible}, still speaking to camera, {delivery}: \"{dialogue}\" Natural lip sync to dialogue, same lighting and camera style, no background music, no score."` (`<Video 1>` is now the master).

Only the **first** clip is processed after it generates: its audio is extracted and a muted copy is made, stored on the job as `anchor_audio_url`, `anchor_video_url` and `anchor_extracted_at` (and on clip 1 as `audio_url` and `muted_video_url`). Later clips need no processing of their own. Those uploads expire after 24 hours (Section 6), so a later regenerate re-extracts and re-mutes them from the first clip's video when `anchor_extracted_at` is old. The original, unmuted videos stay in `video_url` and are what gets stitched into the final video; the first clip is 720p and the rest are the job's resolution, so assembly (Prompt 12) has to scale them to one size. The 720p master is 1280x720, inside kie.ai's 927,408-pixel limit for a reference video, and a 10-second master is inside its 15-second limit.

**Why the 720p master:** any chain in which a clip copies pixels from the clip before it compounds: each clip is rebuilt from an already-compressed, re-rendered copy, so errors add up down the chain. The history:
- Everything chained from the previous clip: the face changed by clip 3 and the audio degraded (first live run).
- "Formula B" (previous clip's video + first clip's audio and last frame, Test E): very good on 3 clips, but on 5 clips the video fell off badly by clips 4 and 5, and the first clip's last word leaked into later clips.
- Test F (every reference fixed to the first clip): video quality stayed flat; the audio leak led to muting the reference video.
- Test G (only the last 2 s of the previous clip as the video reference): much better, but degradation was still visible from clip 2 and kept building, and the motion took on a smooth "gliding" feel that grew from clip to clip.
- Test H (a 720p first clip as a second, fixed video reference, plus the 2 s tail): clips 2 to 5 held nearly level.
- Test I (the 720p master and its audio only, no tail, no image): the user liked the result, and it became the formula.

With every later clip exactly one generation away from the same master, clip 180 is no worse than clip 2, however long the video is. The trade-off: each clip starts from the master, not from where the previous clip ended, so the cuts are cuts (a small reset in pose), not continuous motion.

**Cost:** clip 1 costs 8.2 credits/second at 720p. Every later clip bills its own seconds plus the master's (Section 2): about 24 credits for a 5 s clip, and probably about 48 for a 10 s clip, since the whole 10 s master is billed on every clip. A shorter excerpt of the master would cut that, but whether quality holds with one is untested.

#### Story Time

**Clip 1 (first in sequence):**
- No reference inputs.
- `generate_audio: true` (native Seedance voiceover — validated in Test C).
- Prompt template (draft, built from the prompt the user tested in Test C): `"{visual}. {scene_bible}. Voiceover narration only, {delivery}, no visible speaker, no lip sync needed since no one is speaking on camera: \"{narration}\" Natural ambient sound only, no music, no score — just the voiceover."`
- Test S's first clip had a person visible on screen while the narration played. The logged Test S summary covered scene change, style consistency, narrator voice and audio bleed; it did not mention whether the model tried to lip-sync (move the mouth) in that shot.

**Clip N (N > 1): DECIDED by Test S (2026-09-26): Variant 3, fixed anchors; the video reference muted since 2026-09-27; built (Prompt 5.6).**
- `reference_video_urls`: [a **muted copy** of the previous clip's video] — the only input that chains from clip to clip. Every clip except the last gets its muted copy right after it generates (`muted_video_url`); the original, unmuted video stays in `video_url` for the final stitch.
- `reference_audio_urls`: [the **first** clip's audio] — a fixed narrator-voice anchor, the same file for every later clip in the job (not the previous clip's audio).
- `reference_image_urls`: [the **first** clip's last frame] — a fixed character image, the same file for every later clip (not the previous clip's last frame).
- Prompt: `"Same characters, visual style and lighting as @Video1, but a new scene: {visual}. {scene_bible}. The main character looks exactly like @Image1. Voiceover narration only, in the same narrator voice as @Audio1, {delivery}, no visible speaker, no lip sync needed since no one is speaking on camera: \"{narration}\" Natural ambient sound only, no music, no score — just the voiceover."` This is Variant 3's prompt from Test S with the `{...}` values filled from the script; the "looks exactly like @Image1" sentence sits after the scene bible, where it was tested. One of each reference is sent per request, so every tag is number 1.

**Why Variant 3:** all three variants performed similarly well at 5 seconds and 3 clips on scene change, style consistency, narrator voice and audio bleed. Variant 3 was chosen anyway because its fixed anchors (every clip re-anchored to the first clip's audio and image, not to the immediately preceding clip) should stop identity drift from compounding over longer videos, a failure mode this short test couldn't surface but which matters for production-length Story Time videos with many clips. The choice rests on that design reasoning, not on Variant 3 measurably beating the others in Test S.

**Muted chained video (Section 7, question 14, resolved 2026-09-27):** Story Time keeps its chained video reference, because Test S already showed it doesn't block scene progression across a real 3-scene sequence. The reference is muted as a precaution carried over from Talking Head's diagnosed fix: a video reference silently carries its own audio track, which competed with the fixed voice anchor. Whether a long Story Time chain (5+ clips) still degrades in quality the way Talking Head's did (Test G) is left open, to be observed the first time a longer Story Time job runs, not pre-tested.

**What feeds each Story Time clip after the first:**
- From the OpenAI script: the fixed `scene_bible` (characters, world, style, narrator voice) plus this clip's own `narration`, `visual` and `delivery`.
- From the job: the previous clip's muted video URL, and two anchors taken from the first clip, its audio and its last frame. Every later clip needs the anchors (not just clip 2), so they must be stored on the job and stay usable for the whole job. Files uploaded to kie.ai's host expire after 24 hours (Section 6), so a later regenerate re-extracts them from the first clip's video.
- Extraction: only the first clip's audio and last frame are extracted and stored; they are re-extracted from the first clip's video when they are older than about 23 hours. Every clip except the last also gets a muted copy of its video, for the next clip.
- Requirement: the fixed image is only useful if the first clip shows the main character on screen (Test S's first clip did). The Story Time script prompt therefore requires the first clip's `visual` to clearly show the main character (Prompt 4.6 in `EXECUTION_GUIDE.md`); clips after the first may or may not show the character. It is enforced by the prompt only, not checked in code.

**Tag syntax (resolved 2026-09-26):** references are written as `@` + type + number (`@Video1`, `@Audio1`, `@Image1`), numbered separately per type. Evidence: kie.ai's own product-page examples pair `@video1`, `@image1` and `@image2` in the prompt with `reference_video_urls` (1 item) and `reference_image_urls` (4 items), where `@image2` is the second array entry, and its default prompt uses `@Image1 @Image2 … @Image3 @Image4`; its mini page shows `@Image 1`. Casing and spacing vary across those examples. So `@Image1` and `@Video1` are confirmed by kie.ai's own examples. `@Audio1` is confirmed only by third-party guides (kie.ai shows no audio example), so if Story Time's narrator voice doesn't anchor as expected, check this first. kie.ai's API docs (docs.kie.ai) don't define the syntax, and angle-bracket tags (`<Video 1>`) appear nowhere in kie.ai's pages; Talking Head keeps them because they worked in real generations (Tests A and B).

**Story Time script prompt:** drafted in full in Prompt 4.6 of `EXECUTION_GUIDE.md`; you read its output closely, as with Prompt 3.

### Step 3 — Assembly

Stitch/concatenate the clip videos into one continuous final video for the timeline preview / download. (ffmpeg, straightforward concat since clips are already audio-synced individually.) Same in both modes. kie.ai deletes generated videos after 14 days, so the clips must be downloaded and kept, not just linked.

**Built 2026-09-27 (Prompt 12):**
- **When:** the worker builds the final video at the end of every job and again after every successful regeneration; `POST /jobs/{id}/assemble` builds it on demand. It's served at `GET /jobs/{id}/video`.
- **Where:** clips are downloaded once into a `media` Docker volume and kept.
- **How:**
  - Every clip is scaled to the job's resolution (Talking Head's 720p first clip included) at a constant 24 fps.
  - Each clip's audio is cut to its picture, with 20 ms fades against clicks.
  - In Talking Head, every clip after the first starts just before its first word, without the breath Seedance tends to open with.
  - The video is encoded once at high quality and joined without a second encode; the audio is encoded once.
- Details in `PROGRESS.md`.

---

## 5. Regenerate Logic

Two buttons per clip on the timeline: **Regenerate Script** and **Regenerate Scene**.

- **Regenerate Script** — new dialogue (and consequently new scene) for that one clip, same `scene_bible`.
- **Regenerate Scene** — same dialogue, new video generation for that clip only.

**Per mode:** in Talking Head, Regenerate Script is the one people will use (the visual barely changes). In Story Time, `narration` and `visual` replace `dialogue`, and Regenerate Scene becomes the main action. **Decided 2026-09-27 (Section 7, question 8):** in Story Time, Regenerate Script writes new narration only and keeps the clip's `visual` (the clip is rendered again with the new narration); Regenerate Scene keeps the narration word for word and changes the scene: OpenAI writes a new `visual` that fits the same narration, and the clip is rendered again from it.

**Built so far (Prompt 9, 2026-09-27):** Regenerate Script for the **last** clip, in both modes. Any other clip gets a 501 "mid-sequence regeneration not yet implemented": middle clips and the cascade problem below are set aside for now (your call, 2026-09-27).

### The cascade problem (why this isn't trivial)

Clip N+1 was generated using clip N's *original* video as its chained reference (its audio and last-frame references come from the first clip and don't change). If clip N is regenerated, clip N+1 no longer matches what actually precedes it — the chain breaks downstream.

**Talking Head since 2026-09-27:** no clip depends on the one before it any more (every later clip is generated from the first clip only), so regenerating a middle clip no longer breaks anything downstream, and the bridging below may not be needed in this mode. Regenerating the **first** clip would still invalidate every later clip, since it is their master. Not decided (Section 7, question 1). Story Time's planned formula still chains, so the problem stands there.

### Solved approach — dual video/audio bridging

When regenerating a **middle clip** (one that has both a preceding and a following clip already generated):

- `reference_video_urls`: [clip N-1's video, clip N+1's video] → tagged `<Video 1>`, `<Video 2>` in the prompt
- `reference_audio_urls`: [clip N-1's audio, clip N+1's audio] → tagged `<Audio 1>`, `<Audio 2>`
- Prompt: `"Generate a clip that begins matching the character, setting, and motion in <Video 1>, speaking with the vocal timbre in <Audio 1>, and transitions naturally into a state consistent with <Video 2> and <Audio 2> by the end. {dialogue instruction}"`

If regenerating the **last clip** in the sequence (no N+1 exists), fall back to the normal Talking Head approach (since 2026-09-27: the job's muted 720p master video and its audio; re-extract and re-mute them from the first clip's video first if they are older than about 23 hours).

**Status: partially tested, not fully validated.** Confirmed working: forward-chain (`reference_video` + `reference_audio` + `reference_image` from the single preceding clip) produces strong consistency, no more "decade jump" drift seen with image-only referencing. Later testing (2026-09-26) showed that chaining the audio and last frame from the previous clip too lets drift compound over 3 clips, so those two references are now fixed to the first clip (Section 4, Test E). **Not yet tested:** the dual-reference bridging approach for mid-sequence regeneration — this is the next test (see Section 7).

**Constraint found in kie.ai's docs (2026-09-25, while building Prompt 4):** all reference videos in one request must total **15 seconds or less** (each 2–15 s, max 3), and the same limit applies to reference audios. Two 10-second clips is 20 seconds, so the bridging request above would be rejected at production clip length. Test B as written uses short test clips (two 5-second clips is 10 seconds total), which fits, so it would not have shown this. See the note under Test B.

**UI safety net:** after a mid-clip regeneration, show the user a preview of the new seam into the existing next clip before committing, with an option to also regenerate the next clip if the bridge looks off. Don't assume the dual-reference trick is airtight — give the user an escape hatch rather than silently accepting a bad seam.

---

## 6. Known Issues Already Solved (for reference — don't re-debug these)

| Problem | Resolution |
|---|---|
| `first_frame`/`last_frame` + `reference_audio_urls` together → validation error | These are mutually exclusive modes on Seedance. Use `reference_video_urls` + `reference_audio_urls` + `reference_image_urls` together instead — this combo is supported and is the actual forward-chain method now. |
| `reference_image_urls` alone caused visible character/era drift between clips (e.g. 1800s → 2020s look) | Image-only reference is loose style guidance, not a hard lock. Adding `reference_video_urls` alongside it fixed this — video reference carries motion/subject/style more reliably. |
| Voice changed between clips when generating audio fresh each call | Solved via `reference_audio_urls` as a "vocal timbre donor" — confirmed by kie.ai docs as the intended use case, not a workaround. |
| Copyright-related generation failure ("output audio may be related to copyright restrictions") | This is Seedance's own audio-output content-matching filter, most commonly triggered by generated background music/score resembling known copyrighted material. Mitigation: explicitly add "no background music, no score" to every prompt. Dialogue-only audio has tested clean so far, but this is a content-matching system — **not guaranteed to never fire again**, just meaningfully reduced. |
| Lip-sync concerns with separate TTS | Native Seedance audio generation handles lip-sync automatically since video+audio are generated together. Decoupling audio to OpenAI TTS was considered and rejected for talking-head content specifically because it breaks lip-sync; native audio + reference_audio_urls for consistency is the current approach. For Story Time, where nobody speaks on camera, that objection doesn't apply, but native voiceover was tested and chosen anyway (see the Story-time audio row below). |
| Valid duration values | **Corrected 2026-09-25 (checked against kie.ai's own docs while building Prompt 4):** `duration` is an integer from 4 to 15, or -1 — not the discrete steps (4, 6, 8, 10, 12, 15) that reseller docs suggested. **Decision: production clips are always 10 seconds.** A 5-second option exists for cheap testing only (`clip_duration` of 5 or 10 on the job request, default 10); no other values. Number of clips = duration / clip length. |
| Story-time audio (voiceover, nobody on camera) | Tested manually (Test C): native Seedance voiceover with "voiceover narration only, no visible speaker, no lip sync" wording gave an output the user liked. **Decision: use native audio for Story Time; TTS + mux is not needed.** Not yet tested with a person visible on screen during the narration — see Test S. |
| Asset retention on kie.ai | Per kie.ai's docs (not yet observed): generated videos are kept 14 days; files uploaded to kie.ai's file host (used for the extracted last frame and audio) are kept 24 hours. So a regenerate done more than a day later has to re-extract the frame/audio from the clip's video URL, and clips must be downloaded and kept (Prompt 12) before the 14 days run out. |
| Faint saturation/color shift at the seam between Talking Head clips | **Known limitation, accepted as-is (2026-09-26); not urgent, no action item.** Found in Test A (Talking Head forward chain, 2 of 3 clips run): character, voice and lip sync held up well across the cut; the only issue was a slight saturation/color-grading shift between clip 1 and clip 2 that gives a faint "cut" feeling. Alternative considered and rejected: OpenAI TTS + separate lip-sync tooling (same reasoning as the native-audio decision: extra pipeline complexity and a new failure surface, and it would not solve ambient-audio continuity either). |
| Face drift and end-of-clip audio degradation by clip 3 of a Talking Head chain | **Fixed with the 720p master (2026-09-27).** Found in a real 3-clip job (5 s, 480p) where every reference (video, audio, last frame) was chained from the previous clip. Formula B (previous clip's video + the first clip's audio and last frame) looked very good on 3 clips (Test E), but on 5 clips the video fell off down the chain and the first clip's last word leaked into later clips. Test F led to the muted reference video. Now every later clip uses only the muted 720p first clip and its audio (Section 4, Tests G to I). |
| A breath or sigh (and sometimes a pause) before the first word of each Talking Head clip | **Handled in the final video (2026-09-27), Talking Head only.** Seedance opens most takes with a breath; it is not clip 1's reference audio leaking (the openings don't resemble clip 1's). Changing the prompt was rejected (it could make the delivery flat and rushed). Instead, when the final video is joined, every clip after the first starts just before its first word: the quiet lead-in (at least 25 dB under the voice) is cut from picture and audio together, keeping the first consonant, at most 1.5 s. Clip 1 keeps its opening. Details in `PROGRESS.md`. |
| Quality loss down any chain of clips (generation loss), and a growing "gliding" motion | **Fixed for Talking Head with the 720p master (2026-09-27).** Any clip built from pixels of the clip before it inherits that clip's compression and rendering errors, so they add up: sending only the last 2 s of the previous clip slowed it but did not stop it (Test G), and the motion took on a smooth, floaty feel that grew from clip to clip. A Reddit thread on another model (MiniMax H3) reported the same quality loss when chaining; its only real fix, passing the model's latents between clips, isn't possible through kie.ai's API. Generating every later clip from one fixed master keeps quality level however long the video is. Story Time deliberately keeps a chained (muted) video reference so its scenes can move on; whether it degrades over 5+ clips is a watch item for its first long real job (Section 7, question 14). |

---

## 7. Open Questions / Things Still To Test

1. **Mid-clip regeneration bridging quality (dual video/audio reference)** — untested at time of writing. Real risk: with a hard "must end resembling clip N+1" target inside a fixed clip duration, the model might visibly rush or compress motion to hit that end-state rather than feeling like a natural continuation. Needs a real test (see Section 8) before this becomes the trusted default regenerate-middle-clip method. **Set aside for now (user, 2026-09-27):** only the last clip can be regenerated; a middle clip gets a 501, and the cascade problem is left for later. **Since 2026-09-27, possibly moot for Talking Head:** its clips no longer depend on the previous clip (Section 5), so a middle clip could be regenerated like the last one, from the master. Regenerating the first clip is the exception: every later clip was made from it. Undecided; Story Time still chains.
2. **Two content modes need distinct handling, not one shared template — this was found during implementation, not just theorized.** The user chooses the mode on the dashboard, and each mode has its own script prompt, video template and reference formula (Section 4 has the side-by-side):
   - **Talking-head mode** (built first, default): one person speaking directly to camera. Script fields: `dialogue` + `delivery`. Video prompt includes "natural lip sync to dialogue." `scene_bible` = speaker + room, held fixed. "Regenerate Scene" is low-value here since the visual barely changes clip to clip.
   - **Story-time mode** (not yet built): voiceover narration over visuals that change scene-to-scene — no on-camera speaker, so no lip sync. Script fields would need to be `narration` + `visual` (what's happening on screen) + `delivery`, not `dialogue`. `scene_bible` would describe characters/world/style broadly, not a fixed room. The continuation prompt wording ("Continuing directly from <Video 1>...") also needs to change, since talking-head's version implicitly forces the same scene/framing — story-time needs scenes to be able to change while character/style stays consistent. "Regenerate Scene" becomes the main feature here, not an edge case.
   - **Story-time audio — RESOLVED (2026-09-25):** the user tested native Seedance voiceover manually (Test C) and liked the output. Decision: Story Time uses native Seedance audio (`generate_audio: true`) with "voiceover narration only, no visible speaker, no lip sync" wording. The OpenAI TTS + ffmpeg mux alternative is dropped.
   - **Reference formula — RESOLVED (2026-09-26):** Test S chose Variant 3 (question 7).
   - **Still open for Story Time:** what the two regenerate buttons change (question 8), and the parked model question for motion shots (question 12). Its chained video reference is settled (question 14); how it holds up over a long chain is a watch item.
   - **Decision for now:** `mode` is a field on the job request and a selector on the dashboard. Talking Head is the default. Story Time gets built in steps (Prompts 4.6 and 5.6, with manual tests before each), and every step from 4.6 on is tested in both modes.
3. **Script coherence across clips during regeneration** — when regenerating a single clip's script, does OpenAI need the surrounding clips' dialogue as context to keep the new line coherent with the story, or is each clip's dialogue regenerated in isolation? Leaning toward: yes, pass neighboring dialogue as context in the regenerate-script call. **Prompt 9 (2026-09-27)** passes the topic, the scene bible, the preceding clip's line and the line being replaced (plus the kept `visual` in Story Time), as the guide says. That's enough for the last clip, which has nothing after it. Whether a middle clip also needs the following line is for when middle clips are built.
4. **Retry/fallback behavior for the copyright-filter error** — right now it's handled by prompt phrasing alone. Decide later whether to add automatic retry logic (e.g., re-attempt with an even more explicit "dialogue only, absolutely no music" instruction) if this error still surfaces occasionally in production.
5. **Cost estimation in the UI** — at 2.4 credits/sec (480p) or 5 credits/sec (720p), plus multiple reference inputs per clip, cost adds up fast, especially at 720p. Dashboard should eventually show an estimated credit cost before the user commits to a generation (resolution × duration = clear estimate to surface), especially for longer durations. Not needed for the current testing phase, but flag for later. **Measured 2026-09-25:** 480p actually costs 3.8 credits/second (audio on, no references), not 2.4; 720p is still unmeasured. **Clips with video + audio + image references cost 24 credits per 5 s clip (about 4.8 credits/second, measured 2026-09-26), against 19 for a clip without references, so reference inputs do add cost and a video's first clip is cheaper than the rest.** **Update 2026-09-27:** the measured pattern is 2.4 credits/second of (output + reference video), and 8.2 credits/second for a 720p clip with no references (Section 2). With the 720p master, a Talking Head job costs about 8.2 × clip length for the first clip, plus 2.4 × (2 × clip length) for each later clip at 480p.
6. **Exact valid duration steps and parameter names** — confirm directly against kie.ai's own Seedance 2.0 Mini page rather than trusting third-party reseller docs, since parameter naming (`first_frame_url` vs `start_image`, etc.) varies between resellers of the same underlying model. **Answered 2026-09-25 (Prompt 4):** per kie.ai's own docs, `duration` is an integer 4–15 (or -1), and the wrapper's parameter names (`reference_video_urls`, `reference_audio_urls`, `reference_image_urls`, `generate_audio`, `resolution`, `duration`) match kie.ai's schema; a live 5-second generation with them succeeded.
7. **Story Time reference formula for clips after the first** — **RESOLVED 2026-09-26 by Test S:** Variant 3 (the previous clip's video, plus the first clip's audio and last frame as fixed anchors, with the "looks exactly like @Image1" sentence). See Section 4 (Story Time, Clip N) and Test S in Section 8.
8. **What the regenerate buttons mean in Story Time** — **RESOLVED 2026-09-27 (user's decision):**
   - **Regenerate Script:** new `narration` only; the `visual` is kept and the clip is rendered again with the new narration (built in Prompt 9).
   - **Regenerate Scene:** the narration is kept word for word and the scene changes to something else. OpenAI writes a **new** `visual` (a different scene that still fits the same narration and the story), and the clip is rendered again from it. It is not a new take of the same `visual`. Talking Head's Regenerate Scene stays as the guide says: same line, new video.
   - **Dual-reference bridging for Story Time:** set aside with question 1.
9. **Aspect ratio** — not chosen anywhere in the plan. kie.ai's default is `16:9`, which is what the app currently gets (nothing is sent). Decide whether to expose it (e.g. `9:16` for phone-style talking heads) or fix it.
10. **Webhooks instead of polling** — kie.ai supports a `callBackUrl`. Polling is used now because kie.ai can't reach localhost. The user has ngrok, so webhooks are possible later; that needs a public callback route, matching callbacks to job/clip, and polling kept as a backup. Not decided.
11. **Pronoun in the Talking Head template** — the fixed template says "She speaks directly to camera" while `scene_bible` follows the topic, so a male or non-binary speaker would contradict it. Make the template pronoun-neutral or accept the limitation. (The Story Time template doesn't have this problem.)
12. **Model for Story Time motion shots — PARKED (2026-09-26); not urgent, no decision needed now.** In Test S, face distortion appeared in Variants 2 and 3's clip 3 (a walking, motion-heavy shot) at both 480p and 720p on `bytedance/seedance-2-mini`. Isolated testing on the kie.ai playground showed this is a model limitation, not a problem with the reference formula or the resolution: the same shot on `seedance-2-5` rendered cleanly with the same references. Open: whether to use `seedance-2-5` for Story Time motion shots (or for Story Time altogether). Not yet checked: its cost per second, its exact kie.ai model id and parameters, and whether it accepts the same reference inputs and limits. This is separate from Test S's conclusion and nothing is being acted on; the code uses one model (`KIE_MODEL`) for everything.
13. **Talking Head references on longer chains — RESOLVED 2026-09-27 (Tests G to I).** Every clip after the first now uses only the muted 720p first clip and its audio, nothing from the previous clip and no image (Section 4). It is built into the pipeline. The accepted trade-off is a small pose reset at every cut. The audio reference is still the untrimmed first-clip audio; the user was happy with the result and considers the audio settled for now. Not yet run through the real worker, and not yet run with 10-second clips. The history: chaining the previous clip's video let quality fall off (5-clip run, Test G), a fixed first-clip video kept it flat (Test F), and the first clip's audio leaked into later clips before the reference video was muted.
14. **Story Time reference formula after Tests G to I — RESOLVED 2026-09-27.** Story Time keeps its chained video reference (Test S's Variant 3), because Test S already showed it doesn't block scene progression across a real 3-scene sequence. Muting is added as a precaution carried over from Talking Head's diagnosed fix: a video reference silently carries its own audio track, which competed with the fixed voice anchor. So every clip after the first gets a muted copy of the previous clip's video, plus the first clip's audio and last frame (Section 4), built in Prompt 5.6. **Left genuinely open:** whether a long Story Time chain (5+ clips) still degrades in quality over the chain, as Talking Head's did (Test G). It is to be observed the first time a longer Story Time job actually runs, not pre-tested now. It is a watch item, not a blocker. **First observation (2026-09-27, a live 5-clip x 5 s run):** the scenes changed, the character, style and narrator's voice held, and there was no lip-sync attempt. Quality fell a bit down the chain; the user is accepting it for now.

---

## 8. Immediate Test Plan (before further pipeline build-out)

Test at **5 seconds per clip** (the testing option; production is always 10) and **480p** to conserve credits during testing. Theme: girl sitting on a sofa, talking directly to camera about not liking her husband at first.

Test A (done 2026-09-26) and Test B are **Talking Head**, and so are Tests E to I (done 2026-09-26/27), which settled the Talking Head reference formula (the 720p master, Section 4). Test C (done) validated Story Time's audio. Test S (done 2026-09-26) and Test D are the **Story Time** equivalents; Test S gated Prompt 5.6 and Test D gates Prompt 11 — the two modes must be tested separately, one passing doesn't validate the other.

### Test A — Talking Head: normal 3-clip forward chain (DONE 2026-09-26)

**Result:** 2 of the 3 clips were run, enough to conclude. Character, voice and lip-sync quality all held up well across the cut. One minor finding: a slight saturation/color shift between clip 1 and clip 2 that gives a faint "cut" feeling despite otherwise good continuity. It is not a character-drift or lip-sync problem, just a subtle color-grading inconsistency at the seam. Accepted as-is and logged as a known limitation in Section 6; no fix pursued.

**Clip 1 (0–5s)** — no references, `generate_audio: true`:
> Medium shot, a young woman sits on a grey sofa in a softly lit living room, phone-camera framing as if recording a confession video, speaking directly to camera. Nervous, candid energy. She speaks directly to camera: "Okay, so people keep asking why I didn't love him at first." Natural lip sync to dialogue, slight handheld movement, warm indoor lighting, no background music, no score.

**Clip 2 (5–10s)** — `reference_video_urls` = [clip 1], `reference_audio_urls` = [clip 1 audio], `reference_image_urls` = [clip 1 last frame]:
> Continuing directly from <Video 1>, same woman, same sofa, same framing, still speaking to camera, tone shifting more reflective: "Every night, he'd just... sit there, saying nothing." Natural lip sync to dialogue, same lighting and camera style, no background music, no score.

**Clip 3 (10–15s)** — `reference_video_urls` = [clip 2], `reference_audio_urls` = [clip 2 audio], `reference_image_urls` = [clip 2 last frame]:
> Continuing directly from <Video 1>, same woman, same sofa, same framing, still speaking to camera, voice softening, slight smile forming: "But then one day, everything changed." Natural lip sync to dialogue, same lighting and camera style, no background music, no score.

**Check:** face/character consistency across all 3, voice consistency, lip sync quality, seam smoothness at each cut.

### Test B — Talking Head: regenerate middle clip with dual bridging

Using the Test A output as the base: regenerate **Clip 2** with a *different* line, but bridging between the already-existing Clip 1 and Clip 3.

- `reference_video_urls`: [Clip 1's video, Clip 3's video] → `<Video 1>`, `<Video 2>`
- `reference_audio_urls`: [Clip 1's audio, Clip 3's audio] → `<Audio 1>`, `<Audio 2>`

**New Clip 2 prompt:**
> Generate a clip that begins matching the character, setting, and motion in <Video 1>, speaking with the vocal timbre in <Audio 1>, and transitions naturally into a state consistent with <Video 2> and <Audio 2> by the end. Same woman, same sofa, still speaking to camera: "He never once raised his voice, not even when I did." Natural lip sync to dialogue, no background music, no score.

**Check specifically:**
- Does the seam from Clip 1 → new Clip 2 still look clean?
- Does the seam from new Clip 2 → existing Clip 3 look clean, or does the motion look rushed/compressed trying to "arrive" at Clip 3's opening state?
- Does this hold up differently for a talking-head test (this one) vs. a more dynamic scene-change test — worth repeating Test B later with non-talking-head content once this pipeline is otherwise stable (that is Test D).

**Reference length limit:** kie.ai caps all reference videos in a request at 15 seconds total, and reference audios too. This test uses 5-second clips (10 seconds each of video and audio), which fits. Production clips are 10 seconds, so the same request would carry 20 seconds and be rejected — which means **a pass at 5 seconds does not validate bridging for production.** Before Prompt 11 is used, run Test B again at 10 seconds with each reference trimmed with ffmpeg to 7 seconds or less, and see whether the bridge still works.

### Test C — Story-time mode audio (DONE 2026-09-25)

Question: does native Seedance audio behave sensibly when nobody is speaking on camera (no mouth to sync to), or should Story Time use OpenAI TTS + an ffmpeg mux?

**Result:** the user ran this manually on kie.ai with native Seedance audio and this prompt, and liked the output:

> Wide shot of an empty kitchen at dawn, steam gently rising from a kettle on the stove, soft morning light through a window, no people visible on screen. Calm, quiet, reflective atmosphere. Voiceover narration only, spoken in a wistful female voice, no visible speaker, no lip sync needed since no one is on camera: "She used to make his coffee every morning. That morning, she didn't." Ambient kitchen room tone only, no music, no score — just the voiceover.

**Decision:** Story Time uses native Seedance voiceover (`generate_audio: true`). The TTS + mux alternative was not pursued and is dropped. This prompt is the basis for the Story Time Clip 1 template in Section 4. **Not covered by this test:** a person visible on screen while the narration plays, and any clip after the first — that is Test S.

### Test S — Story Time reference formula for clips after the first (DONE 2026-09-26)

**Result: Variant 3 won** — the previous clip's video (forward-chaining) + the first clip's audio (fixed) + the first clip's last frame as a fixed character image, with "The main character looks exactly like @Image1." in the prompt. Reasoning: all three variants performed similarly well at 5 seconds and 3 clips on scene change, style consistency, narrator voice and audio bleed. Variant 3 was chosen anyway because its fixed anchors (every clip re-anchored to the first clip's audio and image, not to the immediately preceding clip) should stop identity drift from compounding over longer videos, a failure mode this short test couldn't surface but which matters for production-length Story Time videos with many clips. The choice rests on that design reasoning, not on a measured win in this test. The logged results covered the first four checks below (scene change, style consistency, narrator voice, audio bleed); the lip-sync check was not part of the summary.

**Separate finding (parked, see Section 7, question 12):** face distortion appeared in Variants 2 and 3's clip 3 (a walking, motion-heavy shot) at both 480p and 720p on `bytedance/seedance-2-mini`. Isolated playground testing showed it is a model limitation, not the reference formula or the resolution: the same shot on `seedance-2-5` rendered cleanly with the same references. Not acted on now, and not part of Test S's conclusion.

The plan as it was run:

Test manually on kie.ai, not through the app yet. Run it at **5 seconds per clip, 480p**: about 19 credits each at the measured 3.8 credits/second, 7 clips in total (1 + 3 variants × 2), so roughly 133 credits. Prompt 5.6's real-code run then confirms the winning formula at the production length of 10 seconds. The narration lines below are short enough for both lengths.

Theme: one woman's morning, told across three different scenes with the same narrator ("wistful female voice") and the same visual style:
1. **Clip 1** — no references: she makes coffee in a kitchen at dawn, **visible on screen** while the narration plays (checks for unwanted lip-sync when a person is on camera).
2. **Clip 2** — the same kitchen, **empty**: steam rising, her chair vacant (the Test C clip). Scenery only, no character.
3. **Clip 3** — she walks through a park in the morning: a **new scene where the character returns** after a scenery-only clip.

Generate clips 2 and 3 once with **each** of these reference setups, chaining from the previous clip each time (write the continuation wording so it says what to keep — the character, the visual style, the narrator's voice — and that the scene is new; do not use "Continuing directly from <Video 1>"):
- **Variant 1** — the Talking Head formula: previous clip's video + previous clip's audio + previous clip's last frame.
- **Variant 2** — previous clip's video + previous clip's audio only (no image).
- **Variant 3** — previous clip's video + **clip 1's audio** (a fixed voice anchor) + a **fixed character/style image** (a frame from clip 1 where she is visible) instead of the last frame.

**Draft prompts** (the `scene_bible` here is: "a woman in her thirties with shoulder-length dark curly hair and a cream cardigan; realistic cinematic style, soft natural morning light; the narrator has a wistful female voice"). Variants 1 and 2 leave out the `The main character looks exactly like @Image1.` sentence; only Variant 3 includes it.

**Tag syntax:** Test S refers to the references as `@Video1`, `@Audio1` and `@Image1` (one of each per request, so the number is always 1), following the `@image1`/`@video1` style in kie.ai's own examples (kie.ai/seedance-2-0). kie.ai's API docs don't specify the syntax and show no audio example; `@Audio1` comes from third-party guides. Talking Head Tests A and B keep `<Video 1>`/`<Audio 1>` because those worked in real generations; if Test S shows the `@` tags behave better, that is a reason to revisit them later, not a change made now.

**Clip 1** — no references, `generate_audio: true`:
> Medium shot of a woman in her thirties with shoulder-length dark curly hair and a cream cardigan, pouring coffee into a mug at a kitchen counter at dawn, soft morning light through the window. She looks down at the mug and never looks at the camera. Realistic cinematic style. Calm, quiet, reflective atmosphere. Voiceover narration only, in a wistful female voice, no lip sync needed since she is not speaking: "She used to make his coffee every morning." Natural ambient sound only, no music, no score — just the voiceover.

**Clip 2** — references per variant (previous video = clip 1):
> Same characters, visual style and lighting as @Video1, but a new scene: wide shot of the same kitchen, empty, steam rising from a kettle on the stove, a vacant chair at the table, no people visible on screen. A woman in her thirties with shoulder-length dark curly hair and a cream cardigan; realistic cinematic style, soft natural morning light; the narrator has a wistful female voice. [Variant 3 only: The main character looks exactly like @Image1.] Voiceover narration only, in the same narrator voice as @Audio1, quiet and heavy, no visible speaker, no lip sync needed since no one is speaking on camera: "That morning, she didn't." Natural ambient sound only, no music, no score — just the voiceover.

**Clip 3** — references per variant (previous video = clip 2, the empty kitchen):
> Same characters, visual style and lighting as @Video1, but a new scene: the woman in the cream cardigan walking along a tree-lined park path in the early morning, mist between the trees, seen from a distance, she does not look at the camera. A woman in her thirties with shoulder-length dark curly hair and a cream cardigan; realistic cinematic style, soft natural morning light; the narrator has a wistful female voice. [Variant 3 only: The main character looks exactly like @Image1.] Voiceover narration only, in the same narrator voice as @Audio1, lighter, a faint smile in the voice, no visible speaker, no lip sync needed since no one is speaking on camera: "She stepped outside, and the morning finally felt like hers." Natural ambient sound only, no music, no score — just the voiceover.

In Variant 3, the fixed image is a frame from clip 1 where she is visible, and the audio reference is clip 1's audio for both clips 2 and 3. In Variants 1 and 2 the audio reference is the previous clip's audio.

**Check, for each variant:**
- Does the scene actually change, or does it stick to the previous location and composition?
- Do the character and visual style stay consistent, including when she returns in clip 3 after the empty scene in clip 2?
- Is the narrator's voice the same in all three clips?
- Is there any mouth movement or lip-sync attempt when she is on screen (clips 1 and 3)?
- Does ambient sound or music from the previous scene leak into the next one?

The variant that does best becomes the Story Time forward-chain formula. Log the result (and the winning continuation wording) before Prompt 5.6. If none works, the fallback is to drop the video reference for Story Time and rely on the `scene_bible` text plus a fixed character image — test that as a Variant 4.

### Test D — Story Time: regenerate a middle clip (manual — gates Prompt 11 for Story Time)

Section 7 says to test the two modes separately. Once Test S has settled the Story Time chain, repeat Test B with Story Time clips: three different scenes, regenerate the middle one, bridging to the clips on both sides. Watch the seam into the next clip when the scenes are supposed to differ, and keep to the 15-second total limit on reference videos and audios (5-second clips fit; at 10 seconds, trim the references). If bridging doesn't hold up for Story Time, the fallback is the same as Prompt 11's: regenerating a middle clip also regenerates everything after it.

### Test E — Talking Head anchor test, "Formula B" (DONE 2026-09-26)

**Why:** a real 3-clip job through the Prompt 5 pipeline (5 s, 480p, every reference chained from the previous clip) showed the face changing slightly by clip 3 and the audio quality degrading at the end of the last clip.

**What was run** (a one-off runner script, since deleted; 2 generations): the first clip of that job reused as the master; clips 2 and 3 regenerated with the same scene bible, the same lines and the pipeline's own prompts, but with references = the previous clip's video + the first clip's audio + the first clip's last frame (fixed). The old chained clips 2 and 3 were saved next to them for comparison.

**Result:** clips 2 and 3 were judged very good, so Formula B became the Talking Head formula (Section 4) and the pipeline was changed to match. Objective checks of the files (same resolution and bitrates, no clipping, flat average saturation) found no difference between the two runs and did not detect the earlier audio problem, so the evidence is the eye and ear test on one chain. **Cost:** 24 credits per clip (48 for the run), not the 19 a clip without references costs: reference inputs add about 1 credit per second.

**Still to confirm:** a longer chain (5+ clips) and 10-second clips (Section 7, question 13).

### Test F — Talking Head, all references fixed to the master (DONE 2026-09-26, partly successful)

**Why:** a 5-clip job (5 s, 480p, Formula B) showed the video quality falling off by clips 4 and 5, and the first clip's last word ("oment" from "disappointment") overlapping the end of every later clip.

**What was run** (a one-off runner script, since deleted; 4 generations, 96 credits): clips 2 to 5 of that job regenerated with the same lines and prompts, every one with video = the first clip's video, audio = the first clip's audio (intended to be trimmed), image = the first clip's last frame. Nothing chained through another generated clip.

**Video: fixed.** Average edge strength (a rough sharpness proxy) stayed flat on the new clips 2 to 5 (25.0 to 25.3, the master 24.3) while the old chained clips climbed (25.3, 26.3, 27.2, 28.3), which fits added artifacts, and no video complaint was reported on the new version.

**Audio: still bad.** The last two clips had very poor audio and two clips overlapped with the first clip's speech. The trim did not do its job: the master's last word fades out, the silence detector read the fade as silence, and it cut only 0.35 s of near-silence, so the reference still held the whole line. A waveform-match check found the master's ending copied into clip 4 at the same timestamp (match 0.61 against about 0.3 for unrelated clips) and a broader match to the whole line (0.42); clip 4's second half was weak (-35 to -40 dB against -21 to -28 dB) and clip 5 had a dropout. So reference audio content leaks in time-aligned form. The check only finds near-copies of the waveform.

**Consequence:** the pipeline then muted reference videos, since the video's own soundtrack is a second copy of the same speech (Section 4). The follow-up video tests are G to I below.

Tests G to I were run with a one-off runner script, `tail_ref_test.py`, rewritten for each test and deleted on 2026-09-27. Each used the pipeline's own functions and prompts on `bytedance/seedance-2-mini`, with 5-second clips, 5 clips per run. Results, videos and per-clip measurements are in `test_results/tail_ref_test/`. "Edge energy" below is mean Sobel edge strength per clip, a rough sharpness and artifact proxy. It is comparable within a run: on the 5-clip Formula B run it climbed 20.65, 21.63, 22.47, 23.25 as quality fell, and with Test F's fixed references it stayed flat, 20.51 to 20.56.

### Test G — Talking Head, only the last 2 s of the previous clip as the video reference (DONE 2026-09-26)

**Why:** a Reddit thread on chaining clips with another model (MiniMax H3) suggested passing only the last 2 seconds of the previous clip, not the whole clip. Its top comment warned that any chain of already-compressed video degrades, and that the only real fix is passing latents, which kie.ai's API can't do.

**What was run** (`run_20260926_114533`): the Talking Head pipeline, all 480p, with one change. The video reference was the last 2 seconds of the previous clip, muted, plus one frame (49 frames, 2.04 s, because kie.ai rejects reference videos under 2 s). The audio and last-frame references were the first clip's, as in Formula B.

**Result:** much better to the eye than the whole-clip chain, but degradation was still visible from clip 2 and kept building. Edge energy went 23.49, 24.94, 25.95, 26.66, 27.18. The user also noticed that across the chained runs the motion becomes smooth and floaty ("gliding"), growing from clip to clip. **Cost:** 16.8 credits per later clip, against 24 with the whole clip as the reference. This led to the billing pattern in Section 2.

### Test H — Talking Head, a 720p first clip as a fixed second video reference (DONE 2026-09-26)

**What was run** (`master720_20260926_233941`): clip 1 at 720p (1280x720, cost 41 credits). Clips 2 to 5 were at 480p, each with two video references: the last 2 s of the previous clip (muted) and the whole 720p clip 1 (muted, the same file every time). Clip 1's audio and last frame were also sent.

**Result:** clips 2 to 5 held nearly level: edge energy 28.36, 28.54, 28.73, 28.59, measured at 480p size. The user thought the quality was perhaps better, and still saw the gliding. **Cost:** 28.8 credits per later clip (2.4 × (5 + 2 + 5)).

### Test I — Talking Head, the 720p master and its audio only (DONE 2026-09-27) — adopted

**What was run** (`reuse_master_only_20260927_003850`): Test H's clip 1, its muted copy, its audio and its script were reused, so nothing was generated again for clip 1. Clips 2 to 5 were regenerated at 480p with the same lines and prompts, each with exactly two references: the muted 720p clip 1 and its audio. There was nothing from the previous clip and no image.

**Result:** the user liked it, and it became the Talking Head formula (Section 4, built into the pipeline on 2026-09-27). Edge energy was 28.17, 28.24, 28.41, 28.21 (flat), slightly lower than the same clips in Test H. **Cost:** 24 credits per clip (2.4 × (5 + 5)), 96 for the run.

**Still to confirm:** a run through the real worker, a run with 10-second clips (a 10 s master is billed on every later clip: about 48 credits per clip), and a longer job.

---

## 9. Not In Scope For Now

- User accounts, login, signup
- Multi-user job isolation / permissions
- Payment/credit purchasing flow
- Anything beyond a single dashboard page + timeline view
