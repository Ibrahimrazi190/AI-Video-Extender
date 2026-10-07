# Build Progress

Running log of the build, following `EXECUTION_GUIDE.md`. One section per completed prompt, newest at the bottom. What isn't implemented yet (deferred steps, owed tests, open questions, ideas, known gaps) is collected in `BACKLOG.md`.

| Prompt | Step | Status |
|---|---|---|
| 1 | Project scaffolding | Done (2026-09-25) |
| 2 | Job & clip data models + Redis store | Done (2026-09-25) |
| 3 | OpenAI script/scene generation | Done (2026-09-25) |
| 4 | Seedance client wrapper | Done (2026-09-25) |
| 4.5 | Story-time audio test (manual) | Done (2026-09-25): native Seedance voiceover chosen |
| 4.6 | Mode support + 5 s/10 s clip-length option | Done (2026-09-26) |
| Test A | Talking Head 3-clip forward chain (manual, `PLAN.md` Section 8) | Done (2026-09-26): 2 of 3 clips run, enough to conclude. Character, voice and lip sync held up across the cut. Minor finding: a slight saturation/color shift between clip 1 and clip 2 (faint "cut" feeling). Accepted as-is, no fix pursued |
| Test E | Talking Head anchor test, Formula B (manual runner) | Done (2026-09-26): clips 2 and 3 judged very good; cost 24 credits per clip, not 19. Formula B is now the Talking Head formula and the pipeline is changed to match |
| Test F | Talking Head, all references fixed to the master (4 generations, 96 credits) | Done (2026-09-26), partly successful: video fixed (sharpness flat), audio still bad (last two clips very poor, two overlaps with the first clip's speech). My audio trim had not actually trimmed the word. Led to the muted video reference |
| Test G | Only the last 2 s of the previous clip as the video reference (standalone script, 5 clips) | Done (2026-09-26): much better than the whole-clip chain, but degradation still visible from clip 2 and building; motion "glides" more with each clip. 16.8 credits per later clip |
| Test H | 720p first clip as a fixed second video reference + the 2 s tail | Done (2026-09-26): clips 2 to 5 nearly level; the gliding remained. Clip 1 at 720p cost 41 credits, later clips 28.8 |
| Test I | The 720p master + its audio only (reused Test H's clip 1 and lines) | Done (2026-09-27): you liked the result; **adopted as the Talking Head formula**. 24 credits per clip |
| 5 | Talking Head pipeline (Celery task) | Done (2026-09-26), revised three times: Formula B, the muted video reference, and (2026-09-27) **the 720p master**: clip 0 always at 720p, every later clip generated from clip 0 (muted) + its audio only. **Not run through the worker yet** |
| Live run | 720p-master pipeline through the real worker (yours) | Ran 2026-09-27 (job `0d31615a…`, 5 clips x 5 s): finished with no errors; clip 1 at 720p, clips 2 to 5 at 480p, anchors = the muted master + its audio only. Your quality verdict not logged yet |
| 5.5 | Story-time reference test (manual, **Test S**) | Done (2026-09-26): Variant 3 won |
| 5.6 | Story-time forward chain | **Built (2026-09-27); live 5-clip x 5 s run passed.** Formula resolved (`PLAN.md` question 14): each clip after the first gets a **muted** copy of the previous clip's video (chained), plus clip 1's audio and last frame (fixed). **Still owed by the testing note:** a run at 10 s, and one Talking Head job on the current code |
| 6 | FastAPI endpoints: `POST /jobs`, `GET /jobs/{job_id}` | **Built (2026-09-27)**, verified offline (including a real Celery worker) and with non-spending checks on the real API. **Done:** its real jobs were run through the Prompt 7 dashboard (your call), in both modes with 5 s clips, 2026-09-27 |
| 7 | Dashboard (`dashboard.html`, served at `GET /`) | **Done (2026-09-27), tested by you in both modes:** Talking Head (`46957efd…`, 3 x 5 s) and Story Time (`041236d0…`, 5 x 5 s) from the dashboard, both good. That also covers Prompt 6's real `POST`/`GET` in both modes and its 5 s check. You have some Story Time points to discuss later |
| 8 | Timeline clip interaction (UI wiring + 501 placeholder endpoints) | **Done (2026-09-27)**: built and verified against a throwaway API and on the real stack; you tested it on the dashboard and it works |
| 9 | Regenerate Script (last clip only) | **Done (2026-09-27)**: built and verified offline, and tested by you live ("it works good") |
| 10 | Regenerate Scene (last clip only) | **Done (2026-09-27)**: built and verified offline, and tested by you live |
| 11 | Mid-sequence regeneration (dual-reference bridging) | **Deferred (your call, 2026-09-27)**: skipped for now, to come back to after Prompt 12. Its gate isn't met (Tests B and D haven't been run). Middle clips keep answering 501. Cheap partial option noted for later: in Talking Head a middle clip (not clip 1) can be regenerated like the last one, from the master, with no bridging |
| 12 | Final video assembly | **Built (2026-09-27)**, verified offline (real ffmpeg on Seedance-shaped clips) and on the dashboard with a throwaway API. Your testing note next (no credits): press "Build final video" on one of your existing jobs per mode, then download and watch it |
| Watch | Story Time quality over a long chain (5+ clips) | **Watch item, not a blocker.** First data point (2026-09-27, 5 clips x 5 s): quality fell a bit down the chain; you're accepting it for now |
| Movie Mode | Multi-Speaker Dramatic Scene Pipeline (`movie_scene_multispeaker.py`) | **Built & Completed (2026-10-01)**: 60-clip (5-minute) thriller fully generated, verified, and seamlessly assembled via `app.py` lead-in audio trimming and Lanczos normalization. Permanent pipeline integration completed. |

---

## How to run (current state)

1. `cp .env.example .env`, then put real `OPENAI_API_KEY` / `KIE_API_KEY` in `.env` only (`.env` is git-ignored; `.env.example` stays blank).
2. `docker-compose up --build` (rebuild after every code change: there are no bind mounts, `app.py` is baked into the image). Downloaded clips and final videos live in the `media` volume (`/srv/media` in the api and worker); `docker-compose down -v` would delete them along with the jobs in Redis.
3. Dashboard: http://localhost:8001/ (API on the same port; health: http://localhost:8001/health). Redis from the host: `localhost:6380`.
4. Python shell inside the stack: `docker-compose exec api python`.
5. **kie.ai calls are yours to run.** Anything that generates video, or otherwise calls kie.ai live, costs credits: the assistant writes the code and gives you a paste-in command, and never runs it itself (standing rule, saved as a memory note).

### Start a job through the API (Prompt 6; yours to run, it costs credits)

Runs on the host, no container needed. Set the six values at the top (topic in plain ASCII) and paste the whole block into PowerShell; it refuses to send anything until the topic is changed. It calls `POST /jobs`, then polls `GET /jobs/{id}` every 10 s and prints each status change and the video URLs at the end.

```powershell
& {
$topic = "YOUR TOPIC"
$mode = "story_time"      # or "talking_head"
$clips = 3
$clipSeconds = 10         # 10 (production) or 5 (cheaper testing)
$resolution = "480p"

if ($topic -eq "YOUR TOPIC") { "put your topic in first (nothing was sent)"; return }
$body = @{ topic = $topic; mode = $mode; duration = $clips * $clipSeconds; clip_duration = $clipSeconds; resolution = $resolution } | ConvertTo-Json
$id = (Invoke-RestMethod -Method Post -Uri "http://localhost:8001/jobs" -ContentType "application/json" -Body $body).job_id
"job id: $id ($mode, $clips x $clipSeconds s, $resolution)"
$last = ""
do {
    Start-Sleep -Seconds 10
    $j = Invoke-RestMethod "http://localhost:8001/jobs/$id"
    $now = "$($j.status) | " + (($j.clips | ForEach-Object { "[$($_.index):$($_.status)]" }) -join " ")
    if ($now -ne $last) { "$(Get-Date -Format HH:mm:ss) $now"; $last = $now }
} while ($j.status -notin @("done", "failed"))
"`nJOB $($j.status) | error: $($j.error)"
$j.clips | ForEach-Object { "clip $($_.index + 1) [$($_.status)] $($_.resolution)  $($_.video_url)" }
}
```

### Run a job through the pipeline directly (without the API; yours to run, it costs credits)

Paste this in PowerShell from the project folder. Put your topic in (plain ASCII, no curly quotes or accents) and change the settings if you like; it refuses to start until the topic is changed. It sends the job to the real worker (`run_generation_job.delay`), prints each status change, and prints the results at the end.

```powershell
@'
import time
from app import ClipRequest, Job, save_job, get_job, run_generation_job

TOPIC = "PUT YOUR TOPIC HERE"
MODE = "talking_head"  # or "story_time"
CLIPS = 5              # number of clips
CLIP_SECONDS = 5       # 5 (cheaper testing) or 10 (production length)
RESOLUTION = "480p"    # Talking Head: clips 2 onward (clip 1 is always 720p); Story Time: every clip

assert TOPIC != "PUT YOUR TOPIC HERE", "put your topic in first (nothing was generated)"
req = ClipRequest(topic=TOPIC, duration=CLIPS * CLIP_SECONDS, clip_duration=CLIP_SECONDS, resolution=RESOLUTION, mode=MODE)
job = Job(request=req, resolution=req.resolution, mode=req.mode)
save_job(job)
run_generation_job.delay(job.id)
print("job id:", job.id, "|", req.mode, "|", req.num_clips, "clips x", CLIP_SECONDS, "s |", req.resolution,
      "(clip 1 at 720p)" if req.mode == "talking_head" else "", flush=True)

last = None
while True:
    j = get_job(job.id)
    snap = (j.status, tuple((c.status, bool(c.video_url)) for c in j.clips))
    if snap != last:
        print(time.strftime("%H:%M:%S"), "job:", j.status, "|", " ".join(f"[{c.index}:{c.status}]" for c in j.clips) or "(no clips yet)", flush=True)
        last = snap
    if j.status in ("done", "failed"):
        break
    time.sleep(10)

print("\nJOB", j.status.upper(), "| error:", j.error)
print("anchors: video", bool(j.anchor_video_url), "| audio", bool(j.anchor_audio_url), "| image", bool(j.anchor_image_url))
for c in j.clips:
    print(f"\nclip {c.index + 1} [{c.status}] {c.resolution or ''} {c.error or ''}")
    if j.mode == "story_time":
        print(f"  visual    : {c.visual}")
        print(f"  narration : {c.narration}")
        print(f"  muted copy: {'yes (the next clip reference)' if c.muted_video_url else '-'}")
    else:
        print(f"  line  : {c.dialogue}")
    print(f"  video : {c.video_url}")
'@ | docker-compose exec -T api python -
```

- **Cost, Talking Head:** 5 clips of 5 s is about 137 credits (about 41 for the 720p first clip, 24 for each later one). At 10 s, about 82 for the first clip and about 48 for each later one, because the whole 10 s master is billed on every clip (`PLAN.md` Section 2).
- **Cost, Story Time** (not measured in this mode yet; same billing pattern assumed): 5 clips of 5 s at 480p is about 115 credits (19 for the first clip, 24 for each later one: 2.4 x (5 s + the previous clip's 5 s)). At 10 s, about 38 + 48 per later clip.
- **Watch progress** in a second terminal: `docker-compose logs -f worker`.
- **Check when it finishes (Talking Head):** does quality hold level from clip 2 to the last clip; is there any of the first clip's speech ghosting into later clips; the small pose reset at each cut is expected (every clip starts from the master).
- **Check when it finishes (Story Time):** does the scene change from clip to clip; do the character and style hold; is the narrator's voice the same throughout; any lip-sync attempt or leaked music; and, on a 5+ clip run, does quality fall off down the chain (the open watch item).

### What is sent for each clip after the first (as of 2026-09-27)

Both modes send the model `bytedance/seedance-2-mini`, `generate_audio: true` and the job's clip length. Aspect ratio is not sent (kie.ai's 16:9 default).

| | **Talking Head** (built, run live) | **Story Time** (built 2026-09-27, not run live yet) |
|---|---|---|
| Resolution | the job's (480p or 720p); clip 0, the master, is always 720p | the job's, for every clip |
| Video reference | a **muted copy of clip 0** (the 720p master), the same file for every clip | a **muted copy of the previous clip** (chained) |
| Audio reference | **clip 0's audio**, fixed for the job (untrimmed) | **clip 0's audio**, fixed for the job |
| Image reference | none | **clip 0's last frame** as a fixed character image |
| From the previous clip | nothing | its video, muted |
| Prompt | "Continuing directly from `<Video 1>`, {scene bible}, still speaking to camera, {delivery}: "{dialogue}" Natural lip sync..." | "Same characters, visual style and lighting as `@Video1`, but a new scene: {visual}. {scene bible}. The main character looks exactly like `@Image1`. Voiceover narration only, in the same narrator voice as `@Audio1`, {delivery}, no visible speaker, no lip sync needed...: "{narration}"..." |
| Made after clip 0 | its audio + a muted copy (`anchor_audio_url`, `anchor_video_url`) | its audio + last frame (`anchor_audio_url`, `anchor_image_url`) + a muted copy |
| Made after each later clip | nothing | a muted copy (not after the last clip) |

The original unmuted videos stay in `Clip.video_url` and are what gets stitched into the final video.

**Port notes (this machine):** Windows reserves host port 8000 (and 8080), so the API is published on **8001** (container still listens on 8000). Another project's Redis (`backend-redis-1`) holds host port 6379, so ours is published on **6380**. Containers talk to each other on the internal network (`redis:6379`), which these mappings don't affect.

---

## Prompt 1: Project scaffolding (done)

**Built:** `app.py` (single file, sectioned: Imports, Config, Celery App, Models, Redis Store Helpers, OpenAI Helper, Seedance Helpers, Celery Task, FastAPI App & Routes), `dashboard.html` (placeholder), `.env.example`, `requirements.txt`, `docker-compose.yml` (`api`, `worker`, `redis`), plus `Dockerfile`, `.dockerignore`, `.gitignore`.

**Verified:** all three containers up; `GET /health` returns 200 at `localhost:8001`; worker logs `Connected to redis://redis:6379/0` and `ready`; no import errors in either process.

**Decisions / deviations from the prompt:**
- Added a `Dockerfile` (needed for the shared api/worker image; `python:3.12-slim`), and `.dockerignore` / `.gitignore` so `.env` stays out of the image and git.
- `requirements.txt` pins `fastapi==0.141.1`, `uvicorn[standard]==0.53.0`, `celery[redis]==5.6.3`, `redis==6.4.0`. `redis` is held at 6.4.0 because `celery[redis]` (kombu) only supports redis-py `<6.5`, not the newest 8.x.
- API keys default to empty strings if unset (no startup failure); a missing key only surfaces when OpenAI/kie.ai is first called.
- Redis has a named volume (`redis-data`) so job state survives `docker-compose down`.
- Host ports changed to 8001 / 6380 (see port notes above).

**Known / cosmetic:** worker prints a Celery `SecurityWarning` about running as root. Harmless for local dev; not addressed. The worker's `[tasks]` list is empty until Prompt 5.

---

## Prompt 2: Job & clip data models + Redis store (done)

**Built (in `app.py`):**
- Models: `ClipRequest` (`topic`, `duration`, `resolution` = `"480p"`/`"720p"`, default 480p), `Clip` (`index`, `dialogue`, `delivery`, `video_url`, `audio_url`, `last_frame_url`, `status`), `Job` (`id`, `request`, `resolution`, `clips`, `status`).
- Store helpers: `save_job(job)`, `get_job(job_id)` (returns `None` if missing), `update_clip(job_id, clip_index, **fields)`. Jobs are stored as one JSON string per job under the Redis key `job:<id>`.

**Verified** (test script run inside the `api` container against the live Redis, test data deleted afterward):
- `save_job` / `get_job` round-trip returns an identical job; raw JSON in Redis inspected and matches the models.
- `update_clip` changes only the target clip's fields.
- Rejected with the right error and no change to the stored job: missing job (`KeyError`), out-of-range or negative index (`IndexError`), bad status value or misspelled field name (validation error).
- `ClipRequest` rejects `duration=25`, `duration=0`, `resolution="1080p"`, and an empty topic.
- Concurrency: 200 trials of 3 simultaneous `update_clip` calls on different clips of one job lost 0 updates. A control run of a plain read-modify-write lost updates in 200/200 trials, so the test does detect the problem.
- Checked against `PLAN.md` Section 4: clip has `dialogue` + `delivery`, and the reference inputs for clip N come from clip N-1's `video_url` / `audio_url` / `last_frame_url`, so no separate reference fields are needed.

**Decisions beyond the prompt text:**
- One shared `Status` type (`pending` / `generating` / `done` / `failed`) for both clips and jobs, since job statuses weren't specified.
- `ClipRequest.duration` must be > 0 and a multiple of `CLIP_DURATION` (10), so clip count is always a whole number; `topic` must be non-empty.
- `Job.id` defaults to a random hex UUID.
- `Clip` uses `extra="forbid"` so a misspelled field passed to `update_clip` raises instead of being silently dropped.
- `update_clip` is a Redis WATCH transaction (safe under concurrent workers).

---

## Prompt 3: OpenAI script/scene generation (done)

**Built (in `app.py`):** `generate_script(topic, num_clips) -> {"scene_bible": str, "clips": [{"dialogue": str, "delivery": str}, ...]}`, with helpers `SCRIPT_SCHEMA`, `_script_system_prompt(num_clips)` and `_check_script(...)`. New config `OPENAI_MODEL` (default `gpt-5.5`; override in `.env`, documented in `.env.example`). `openai==3.19.2` added to `requirements.txt`.

**Verified:**
- You ran the testing note (`generate_script("a girl telling us her story of how she did not like her husband at first, sitting on a sofa, talking to camera", 3)`) and approved the output: `scene_bible` is a concrete, reusable physical description, and the 3 lines read as one continuous story.
- Exact clip count holds at `num_clips` = 1, 3 and 6 (the 6-clip story stayed coherent).
- Failure paths raise the right error: `num_clips=0`, missing `OPENAI_API_KEY`, model refusal, truncated JSON, wrong clip count, blank `scene_bible` (the last four via a stubbed client, so no API cost).
- Model comparison on the test topic: `gpt-5.5` (~10 s) gave the clearest story arc and most specific detail; `gpt-5.4-mini` (~4 s) was fine but had an odd detail; `gpt-4.1` (~2.4 s) was valid but most generic and used curly quotes / an em dash. Kept `gpt-5.5` as default since it is one call per job and script quality feeds everything downstream.

**Decisions beyond the prompt text:**
- Uses Structured Outputs (`response_format` `json_schema`, strict), which is stricter than plain JSON mode. Uses Chat Completions (still supported in openai 3.x).
- Model is configurable (`OPENAI_MODEL`); no `temperature` or token-limit params are set, so the same code works across model families.
- Word budget in the system prompt is derived from `CLIP_DURATION` (target `round(CLIP_DURATION * 2.2)` = 22 words, cap `round(CLIP_DURATION * 2.6)` = 26). It is prompt-guided only; word count is not validated in code. Observed lines ran 19 to 26 words.
- The prompt forbids double quotation marks inside dialogue, because the Seedance template wraps each line in double quotes.
- Validation but no retry: one bad response raises `ValueError` (missing key raises `RuntimeError`). Whether to add a retry is not decided.
- `generate_script` covers the initial full-job script only. Regenerate-script with neighbouring-dialogue context is Prompt 9 (`PLAN.md` Section 7, question 3 still open).

---

## Prompt 4: Seedance client wrapper (done)

**Built (in `app.py`):**
- `generate_clip(prompt, resolution, duration=10, reference_video_urls=None, reference_audio_urls=None, reference_image_urls=None, generate_audio=True) -> {"task_id", "video_url", "credits_consumed"}`. Reference lists that are empty or `None` are left out of the request.
- `extract_last_frame(video_url)` (PNG) and `extract_audio(video_url)` (WAV): download the video, run ffmpeg, upload the result to kie.ai's file host and return a public URL.
- Helpers and config: `KieError` (carries `fail_code` and kie.ai's failure message), `_kie_client`, `_unwrap`, `_clip_input`, `_wait_for_clip`, `_run_ffmpeg`, `_download`, `_upload_to_kie`; `KIE_API_BASE`, `KIE_UPLOAD_BASE`, `KIE_MODEL` (`bytedance/seedance-2-mini`), `KIE_POLL_TIMEOUT` (15 min).
- ffmpeg added to the `Dockerfile`; `httpx==0.28.1` added to `requirements.txt`.

**How it talks to kie.ai (checked against kie.ai's own docs):** `POST https://api.kie.ai/api/v1/jobs/createTask`, then polls `GET /api/v1/jobs/recordInfo?taskId=` (states waiting / queuing / generating / success / fail; the video URL is in `resultJson.resultUrls`). Polling was chosen over webhooks because kie.ai cannot reach localhost. Uploads go to `https://kieai.redpandaai.co/api/file-stream-upload`.

**Verified:**
- Offline, against a fake kie.ai server (no credits): exact request body with references omitted when empty; polling success, task failure, rejected request, non-JSON reply, network blips, timeout, argument validation, missing key.
- Extraction on a Seedance-shaped local test video: the frame is pixel-identical to the true last frame; the WAV is valid, 10.01 s, not silent, 1.83 MB; a video with no audio track and a 404 URL fail cleanly; no temp files left behind.
- Live, run by you: a real 5-second 480p generation returned a video URL, `credits_consumed` 19.0, in 157 s; the last-frame and audio extraction returned working public URLs; you watched the video, opened the frame and played the audio and confirmed all three look fine. An earlier interactive attempt (default 10 s) logged 38 credits on kie.ai's dashboard.
- Bug found by a live upload test and fixed: the upload reply contains `downloadUrl`, not the `fileUrl` shown in the docs.

**Findings that change the plan (all recorded in `PLAN.md`):**
- Real price: **3.8 credits/second at 480p** (audio on, no references), not the plan's 2.4. 720p is not measured yet.
- Duration: kie.ai accepts any integer 4 to 15 (or -1), not discrete steps. Decision: production clips are always 10 s, with a 5 s option for testing only.
- Reference limits: each 2 to 15 s, max 3, and the **total is capped at 15 s** for videos and again for audios, so dual bridging with two 10 s clips (20 s) would be rejected.
- Retention: files uploaded to kie.ai's host last 24 hours; generated videos last 14 days.
- Render time: about 2.5 minutes for a 5 s clip.

**Decisions beyond the prompt text:**
- Extracted files are uploaded to kie.ai's file host, because reference URLs must be publicly fetchable (a local path would not work). PNG for frames, WAV for audio.
- Extra optional `generate_audio=True` argument (matches Prompt 5's wording). `aspect_ratio` is not sent, so kie.ai's default 16:9 applies.
- Retries cover connection errors only (the request was never sent, so a POST cannot be submitted twice); polling tolerates up to 5 consecutive network errors because the task is already paid for.
- The wrapper still accepts 4 to 15 s so short manual tests work; the pipeline will always pass the job's clip length.
- No retry on generation failure (copyright-filter handling is still open question 4).

**Standing rule (set during this step):** the assistant never makes live kie.ai calls itself. Before the rule, it made one read-only credit-balance call (balance was about 9,958 credits) and a few free test-file uploads.

---

## Design decision: content modes and clip length (decided 2026-09-25; script prompts and first-clip templates built in Prompt 4.6, Story Time chain comes in 5.6)

**Issue:** Prompt 3's `generate_script`, Prompt 5's clip templates and the Prompt 7 dashboard assumed one video type: a person speaking to camera with lip sync. `PLAN.md` promised "talking-head or narrative style" and said the two modes behave differently.

**Decisions:**
- A user-selectable `mode` on the dashboard and job request: `talking_head` (default) and `story_time` (voiceover over changing scenes), each with its own script prompt, video template and reference formula.
- **Story-time audio: native Seedance voiceover.** You tested it manually (Test C, empty-kitchen prompt) and liked the output. The OpenAI TTS + ffmpeg mux option is dropped.
- **Clip length:** production is always 10 s. A job may also use 5 s clips (`clip_duration` of 5 or 10, default 10) purely to save credits while testing. No other values.

**What differs per mode:**
- Script fields per clip: talking head = `dialogue` + `delivery`; story time = `narration` + `visual` (what is on screen) + `delivery`.
- `scene_bible`: talking head = speaker + room; story time = characters, world, visual style and the narrator's voice, true across changing scenes.
- Video prompt: talking head = "speaks to camera, natural lip sync"; story time = voiceover only, no visible speaker, no lip sync, ambient sound only (template drafted from your Test C prompt).
- Reference inputs for clips after the first: talking head = previous clip's video + audio + last frame; story time = **decided by Test S (Variant 3, fixed anchors)**: the previous clip's video, plus the first clip's audio and last frame reused unchanged for every later clip, and the prompt sentence "The main character looks exactly like @Image1."

**Docs updated:**
- `PLAN.md`: Sections 1, 2, 4 (mode table, both schemas, both template sets, Story Time reference hypotheses, draft continuation template), 5, 6, 7 (open questions 7 to 11), 8 (Test C marked done; new Test S and Test D).
- `EXECUTION_GUIDE.md`: Prompt 4.5 marked done; Prompt 4.6 rewritten (mode, `clip_duration`, per-mode script prompts with the full Story Time system prompt, `build_clip_prompt`); new Prompt 5.5 (manual Test S) and 5.6 (Story Time chain, gated); Prompts 5 to 12 updated so every step from 4.6 on is tested in both modes; the dashboard (Prompt 7) gets a mode selector and a clip-length toggle.

**Test S result (2026-09-26): Variant 3 won.** Previous clip's video + clip 1's audio (fixed) + clip 1's last frame as a fixed character image, with "The main character looks exactly like @Image1." in the prompt. All three variants performed similarly well at 5 seconds and 3 clips on scene change, style consistency, narrator voice and audio bleed; Variant 3 was chosen because re-anchoring every clip to clip 1's audio and image (not the previous clip's) should stop identity drift compounding over longer videos, which this short test couldn't surface. The lip-sync check was not part of the logged summary. Recorded in `PLAN.md` (Section 4, Section 7 question 7, Test S) and filled into Prompt 5.6.

**Tag syntax (2026-09-26):** reference tags are `@Video1`, `@Audio1`, `@Image1` (kie.ai's own product-page examples confirm the image and video form; `@Audio1` is third-party only). Story Time's templates and Test S use them; Talking Head keeps `<Video 1>` / `<Audio 1>` because those worked in real generations.

**Parked finding (2026-09-26):** face distortion in a walking, motion-heavy shot (Variants 2 and 3, clip 3) at 480p and 720p on `bytedance/seedance-2-mini`. Isolated playground testing showed a model limitation, not the formula or the resolution; the same shot on `seedance-2-5` rendered cleanly. Whether to use `seedance-2-5` for Story Time motion shots is a separate later question (cost and model id not checked); no action now (`PLAN.md` Section 7, question 12).

---

## Prompt 4.6: Mode support and clip-length option (done)

**Built (in `app.py`):**
- Models: `Mode` and `ClipDuration` (5 or 10) types. `ClipRequest` gains `mode` (default `talking_head`) and `clip_duration` (default 10), a validator that `duration` is a multiple of `clip_duration`, and a `num_clips` property. `Clip` gains optional `narration` and `visual`. `Job` gains `mode`.
- `generate_script(topic, num_clips, mode="talking_head", clip_duration=10)`: a separate system prompt and JSON schema per mode (`SCRIPT_SCHEMA` for Talking Head, `STORY_SCRIPT_SCHEMA` for Story Time; `SCRIPT_MODES` maps a mode to its prompt builder, schema and required fields). The word budget comes from `_word_budget(clip_duration)` at about 2.2 / 2.6 words per second: 22 / 26 at 10 s, 11 / 13 at 5 s. The Story Time system prompt is the one in the guide, including the rule that the first clip's `visual` must clearly show the main character.
- `build_clip_prompt(mode, scene_bible, clip, is_first_clip)`: the Talking Head first-clip and continuation templates, and the Story Time first-clip template. Story Time clips after the first raise `NotImplementedError` (built in 5.6).

**Verified** (offline inside the api container, plus real OpenAI output as noted):
- The Talking Head system prompt is byte-identical to the saved baseline at 10 s (3 and 6 clips).
- `ClipRequest`: defaults; `clip_duration` 5 and 10 accepted, 4, 7 and 15 rejected; `duration` must be a multiple of the clip length; bad `mode` rejected; the old checks still hold. The Prompt 2 test suite passes unchanged on the new code, and a job stored before this change loads with the new defaults.
- Templates: Talking Head clip 0 and clip N and Story Time clip 0 match the spec strings exactly; a trailing period on `scene_bible` or `visual` no longer produces `..`; missing fields and an unknown mode raise.
- `generate_script` request wiring with a stubbed OpenAI: the right prompt, schema and word budget per mode and clip length; an empty field, wrong clip count, bad mode, bad `clip_duration` and missing key all raise.
- Real OpenAI output read in both modes (about five calls, no kie.ai): Talking Head unchanged at 10 s (19 to 23 words) and 10 to 12 words at 5 s; Story Time 19 to 22 words at 10 s and 11 to 12 at 5 s, scenes change every clip, the narrator's voice is in the scene bible, and clip 0's `visual` showed the main character in every run, including a lighthouse topic that would naturally open on scenery.

**Decisions beyond the prompt text:**
- The trailing period is stripped from `visual` as well as from `scene_bible`, otherwise the Story Time template's `{visual}.` gives `..`.
- Added `ClipRequest.num_clips` (Prompts 5 and 6 need the clip count).
- `generate_script` keeps its old call shape (`generate_script(topic, n)` still means Talking Head at 10 s).
- The Story Time first-clip rule is enforced by the prompt only; nothing checks it in code.

**Notes:** `Job.mode` duplicates `request.mode`, as `Job.resolution` duplicates `request.resolution` (whatever creates the job must keep them in sync). Cosmetic, per the spec'd template: Talking Head clip N prompts read "Continuing directly from <Video 1>, A young woman...", with a capital letter after the comma. Left as is.

---

## Prompt 5: Talking Head pipeline as a Celery task (done, revised to the 720p master)

**Built (in `app.py`):** `run_generation_job(job_id)`, registered with Celery as `app.run_generation_job` (the worker lists it under `[tasks]`).
- It checked `job.mode` first: a `story_time` job failed at once with "story_time pipeline not implemented yet", spending nothing (replaced by Prompt 5.6).
- It sets the job `generating`, calls `generate_script` (a failure marks the job failed with the message and stops), then saves `scene_bible` and the script's clips on the job.
- It generates the clips in order with `build_clip_prompt` and `generate_clip(duration=job.request.clip_duration)`, saving each clip's `video_url` the moment it exists so a failure later in the same clip can't lose a paid video. Any failure marks the clip and the job failed with the error and stops the chain; a failure never raises. When every clip finishes the job becomes `done`.
- Every write goes through `update_job()` / `update_clip()` (never `get_job()` then `save_job()`). New: `update_job()` (the same locking as `update_clip`), `Job.scene_bible`, `Job.error`, `Clip.error`, and, with the Formula B revision, `Job.anchor_audio_url`, `Job.anchor_image_url`, `Job.anchor_extracted_at`. `Job` now rejects unknown field names, like `Clip`.

**Verified offline** (fake OpenAI and kie.ai, real Redis): exact clip 0 / clip N prompts; the store shows each clip `generating` while it renders; the task reads the job once and never calls `save_job`; the `story_time` check spends nothing; script failure, first-clip failure, mid-chain failure and a clip-0 extraction failure all mark the job failed and stop (the paid `video_url` is kept); placeholder clips and a wrong-sized clip list both work; 200 trials of `update_job` plus two `update_clip` calls at the same instant lost no updates; the earlier suites still pass.

**Live run (yours):** a 3-clip, 5-second, 480p job through the worker finished, about 2.5 minutes per clip. You found the face changed slightly by clip 3 and the audio degraded at the end of the last clip. The stored job showed nothing wrong mechanically: clip 3's line was 10 words (under the 13-word cap) but its delivery was slow and emotional. My read: the first version chained all three references from the previous clip, so drift compounded.

**Revision (Formula B, 2026-09-26):** A one-off runner script (since deleted) regenerated clips 2 and 3 of that job with the previous clip's video + the first clip's audio and last frame (fixed). You judged both very good. The pipeline now does the same: only clip 0's audio and last frame are extracted (stored on the job as anchors); every later clip uses the previous clip's video plus those anchors, and later clips have no audio or last-frame URLs of their own. Recorded in `PLAN.md` (Section 4, Section 6, question 13, Test E). Confirmed on one 3-clip chain only.

**Revision 2 (muted video reference, 2026-09-26):** after a 5-clip run showed video quality falling off down the chain and the first clip's last word leaking into later clips, Test F found the audio leak stays even with all references fixed to the master, and that reference audio is copied time-aligned into later clips. The reference video's own soundtrack is a second copy of the same speech, so the pipeline now mutes it. New: `mute_video()` (`ffmpeg -an -c:v copy`, video stream untouched, uploaded to kie.ai's file host), and `Clip.muted_video_url` / `Clip.muted_video_at`. `run_generation_job` mutes every clip's video except the last (it is only ever the next clip's video reference); the original unmuted video stays in `video_url` and is what gets stitched. The audio and last-frame anchors are unchanged. Verified offline (fake OpenAI and kie.ai, real Redis and real ffmpeg): each later clip's video reference is the muted copy of the previous clip, the originals are untouched, the last clip is never muted, every failure path keeps the paid `video_url`, and the real helper's output has no audio stream and a byte-identical video stream. **Not run live.**

**Tests G to I (2026-09-26/27, standalone runner `tail_ref_test.py`, rewritten for each test, deleted 2026-09-27; results in `test_results/tail_ref_test/`, details in `PLAN.md` Section 8):**
- **Test G:** only the last 2 s of the previous clip (muted) as the video reference, all 480p (`run_20260926_114533`). Much better to your eye, but degradation still visible from clip 2 and building (edge energy 23.49 to 27.18). You also noticed the motion "gliding" more with each clip. A frame-exact 2 s cut needed care: without a constant output frame rate, ffmpeg 7.1 dropped the frame durations after the trim and decoders lost the last frame (caught offline, fixed before the run).
- **Test H:** clip 1 at 720p, clips 2 to 5 at 480p with the 2 s tail plus the whole muted 720p clip 1 (`master720_20260926_233941`). Clips 2 to 5 nearly level (28.36 to 28.73); the gliding remained.
- **Test I:** reused Test H's clip 1, its muted copy, audio and lines; clips 2 to 5 regenerated with only the muted 720p clip 1 and its audio (`reuse_master_only_20260927_003850`). Flat (28.17 to 28.41), and you liked the result.
- **Billing pattern** from these runs: a clip with a reference video costs 2.4 credits per second of (output + reference video): 16.8 (5 + 2 s), 28.8 (5 + 2 + 5 s), 24 (5 + 5 s). A 720p clip with no references cost 41 for 5 s (8.2 credits/s).

**Revision 3 (720p master, 2026-09-27):** the pipeline now does what Test I did. New config `MASTER_RESOLUTION = "720p"`, `Job.anchor_video_url` and `Clip.resolution`.
- Clip 0 is always rendered at 720p, whatever the job's resolution. Right after it, the pipeline extracts its audio and makes a muted copy, and stores them on the job (`anchor_audio_url`, `anchor_video_url`, `anchor_extracted_at`) and on clip 0 (`audio_url`, `muted_video_url`, `muted_video_at`).
- Every later clip is rendered at the job's resolution with exactly those two references. Nothing comes from the previous clip, there's no image, and no per-clip muting or extraction.
- Talking Head no longer extracts a last frame. `anchor_image_url` stays on `Job` for Story Time.
- The prompts are unchanged.

Verified offline on an internal Docker network with a throwaway Redis (fake OpenAI and kie.ai generation and uploads; real ffmpeg, `extract_audio` and `mute_video`):
- clip 0 at 720p, the rest at the job's resolution, and a 720p job all at 720p;
- every later clip gets exactly [muted clip 0] + [clip 0's audio];
- `mute_video` and `extract_audio` are called once each, on clip 0 only, and the job makes only two uploads;
- the master is 1280x720 (inside kie.ai's 927,408-pixel limit) with a byte-identical video stream;
- the store shows each clip `generating` with its resolution while it renders;
- 10 s clips and 1-clip jobs work;
- a clip 0 failure, a mute failure after clip 0 was paid for (its `video_url` is kept), a mid-job failure, a script failure and a Story Time job all behave as before;
- a job saved before the change still loads.

The Docker stack was rebuilt, and the worker lists the task.

**Live run through the worker (yours, 2026-09-27):** job `0d31615ad62541ba807b138709d1e8b6`, 5 clips x 5 s ("A young women talk about her experience with her last boyfriend"). It finished in about 10 minutes with no errors. In the store, clip 1 is 720p with its muted copy and audio, clips 2 to 5 are 480p with nothing of their own, and the job anchors are the video and audio only (no image), all as designed. Your quality verdict isn't logged yet.

**Live runs so far** (all yours): (1) 3 clips, everything chained from the previous clip: face changed slightly by clip 3, audio degraded at the end of the last clip. (2) Test E, Formula B on clips 2 and 3: very good. (3) 5 clips, Formula B: video quality fell off by clips 4 and 5, and the first clip's last word ("oment" from "disappointment") leaked into the end of later clips. (4) Test F, all references fixed to the master: video clean, audio still bad. (5) Tests G to I above. (6) The 720p-master pipeline through the worker, 5 clips x 5 s: finished as designed (above).

**Cost finding:** the two Formula B clips cost 24 credits each (48 for the run), against 19 for a clip with no references. Reference inputs add about 1 credit per second (about 4.8 credits/s against 3.8), so the first clip of a job is cheaper than the rest. I had estimated 38 credits for the test, which was too low.

**Decisions and gaps:**
- An extraction or mute failure on clip 0 fails that clip and the job (there would be no master), but keeps its `video_url`.
- The clips after the first no longer depend on each other, so they could be generated in parallel (much faster for long videos). Not wanted for now (your call, 2026-09-27); they are still generated one at a time and a failure stops the job.
- The task creates or replaces the job's clip list from the script, so it works whether or not `POST /jobs` pre-creates placeholder clips.
- Nothing stops the same job being started twice, which would spend credits twice.
- If the worker dies mid-job the job stays `generating` forever.
- The job store does not record credits per clip.

---

## Prompt 5.6: Story Time forward chain (done)

**Decision first (2026-09-27, `PLAN.md` Section 7, question 14, resolved):** Story Time keeps its chained video reference, because Test S showed it doesn't block scene progression across a real 3-scene sequence. The reference is muted as a precaution carried over from Talking Head: a video reference silently carries its own audio track, which competed with the fixed voice anchor. Whether a long Story Time chain (5+ clips) degrades the way Talking Head's did is a watch item for the first real long run, not pre-tested.

**Built (in `app.py`):**
- `run_generation_job` now runs Story Time jobs instead of failing them. Every clip is rendered at the job's resolution; there is no 720p master in this mode.
- Clip 0 uses the Story Time first-clip template with no references. Right after it: `extract_audio` and `extract_last_frame` become the job's fixed anchors (`anchor_audio_url`, `anchor_image_url`, `anchor_extracted_at`; also `audio_url` and `last_frame_url` on clip 0).
- Every clip except the last gets a muted copy right after it generates (`mute_video`, stored as `muted_video_url` / `muted_video_at`). That copy is the next clip's video reference.
- Every later clip is sent `reference_video_urls=[muted previous clip]`, `reference_audio_urls=[clip 0's audio]` and `reference_image_urls=[clip 0's last frame]`.
- `build_clip_prompt`'s Story Time continuation template is Test S's Variant 3 wording: `@Video1` / `@Audio1` / `@Image1`, "The main character looks exactly like @Image1."
- Clips are built from the script's `narration`, `visual` and `delivery`.
- New `_fresh_story_anchors()` and `ANCHOR_MAX_AGE` (23 h), from the guide's code note. Before each later Story Time clip, if the anchors are older than 23 hours, they are re-extracted from clip 0's video (kept 14 days), since kie.ai deletes uploads after 24 hours.
- Talking Head is unchanged.

**Verified offline** (internal Docker network, throwaway Redis, fake OpenAI and kie.ai generation and uploads, real ffmpeg with the real `extract_audio`, `extract_last_frame` and `mute_video`):
- a 5-clip Story Time job at 480p: every clip at the job's resolution, and clip 0 with no references;
- audio and last frame are extracted once, from clip 0;
- clips 0 to 3 are muted right after they generate, and the last clip is not;
- each later clip's video reference is the previous clip with no audio and a byte-identical video stream;
- the audio and image references are the same clip-0 files for every later clip: the audio is clip 0's original (unmuted) audio, and the image its last frame;
- clip 1's prompt matches Test S's Variant 3 wording exactly;
- narration and visual are stored per clip, and `video_url` stays the original with sound;
- 720p jobs, 10 s clips and 1-clip jobs work (a 1-clip job mutes nothing);
- anchors made to look 25 hours old are re-extracted before the next clip, and later clips use the new ones;
- clip 0, mute, mid-chain and script failures behave like Talking Head's, and a paid `video_url` is kept;
- missing narration or visual raises an error, and trailing periods are stripped;
- every Talking Head check from Revision 3 still passes, and a job saved before these changes still loads.

The Docker stack was rebuilt after your Talking Head run had finished (the worker was idle), and the worker lists the task.

**Live run (yours, 2026-09-27):** job `4770cfcf94054250bfb91fe1e48ba6e1`, 5 clips x 5 s at 480p ("How I survived a toxic boyfriend"). It finished in about 14 minutes with no errors.
- **Your checks:** the scene changes from clip to clip, the character and style hold, the narrator's voice stays the same, there's no lip-sync attempt, and the original clips play with sound.
- **Quality fell a bit down the chain;** you're accepting it for now. That's the first data point on the long-chain watch item.
- **The store, as designed:** the anchors (clip 1's audio and last frame) were set once after clip 1 and never refreshed, clips 1 to 4 each have a muted copy and clip 5 doesn't, and the later clips have no audio or last frame of their own.

**Still owed by the testing note:**
- a run at the production 10 s length (3 clips, about 134 credits, estimated);
- one Talking Head job on the current code. Your Talking Head run finished before the Prompt 5.6 rebuild. A 3-clip Talking Head job at 10 s (about 178 credits) would also cover Prompt 5's own 10 s check.

**Decisions and gaps:**
- Only clip 0's audio and last frame are extracted; later clips get just their muted copy, because only clip 0's audio and frame are ever referenced.
- The last clip isn't muted, because nothing references it. A later regenerate of the last clip (Prompt 9) needs the muted copy of the clip before it, which exists; if it is older than 23 hours it has to be re-muted from that clip's `video_url`.
- The anchor refresh runs only during a job, for Story Time. Talking Head's master isn't refreshed mid-job; a 23-hour job is far off. Regenerates (Prompt 9) are told to refresh both modes' anchors.
- The first clip must show the main character for the image anchor to make sense: the script prompt requires it, but it isn't checked in code.

---

## Prompt 6: FastAPI endpoints (done)

**Built (in `app.py`):**
- **`POST /jobs`** (201) takes a `ClipRequest` (`topic`, `duration`, `resolution`, `mode`, `clip_duration`), stores a new `Job` and queues `run_generation_job`. It returns `{"job_id": ...}`.
  - `Job.mode` and `Job.resolution` are copied from the request, so they're always in sync.
  - The job starts with one pending placeholder clip per clip, so the dashboard can show them before the script exists; the task then replaces them with the scripted clips.
  - An invalid request (bad mode, clip length other than 5 or 10, duration not a multiple of it, empty topic, bad resolution) gets a 422 before anything is stored or queued.
  - If the queue refuses the job, it's marked failed and the call returns 503, instead of the job sitting "pending" forever.
- **`GET /jobs/{job_id}`** returns the whole stored job: status, error, scene bible, anchors, and every clip with its status, resolution and URLs. An unknown id gets a 404.

**Verified offline** (internal Docker network, throwaway Redis, FastAPI test client):
- the defaults, and Story Time at 720p with 5 s clips (30 s gives 6 placeholders), are stored with the request's settings and queued once;
- seven kinds of invalid request get a 422 and store and queue nothing;
- `GET` returns the full job and reflects updates as they happen;
- an unknown id gets a 404;
- a queue failure gives a 503 and a failed job;
- end to end with a real Celery worker that had no API keys: `POST /jobs` put the job on the queue, the worker ran it, and `GET` showed it failed at "OPENAI_API_KEY is not set", with nothing spent.

**On the real stack after the rebuild:** health 200, `GET` of your Story Time job 200, an unknown id 404. Posts with a bad `mode` and with `clip_duration: 7` got 422, stored nothing (still 5 jobs in Redis) and queued nothing. The API command above was checked the same way: the placeholder guard sends nothing, an invalid mode is rejected with the right field named, and the polling part prints a finished job correctly.

**Testing note: done 2026-09-27 through the Prompt 7 dashboard, in both modes with 5 s clips (Talking Head `46957efd…`, Story Time `041236d0…`).** As written, it asked for real jobs through `POST /jobs`, once per mode, polled to `done`, with playable video URLs, plus one job with `clip_duration: 5`. These can double as the runs still owed from Prompt 5.6:
- a 3-clip Story Time job at 10 s (about 134 credits);
- a 3-clip Talking Head job at 10 s (about 178), which also covers Prompt 5's 10 s check;
- for the 5 s check, a cheap 2-clip job, for example Story Time at about 43.

**Decisions and gaps:**
- `POST` returns 201 and only the job id; the dashboard polls `GET` for everything else.
- Nothing stops the same request being submitted twice: each `POST` is a new job and a new spend. The dashboard (Prompt 7) should disable the button while a job is being sent.
- A job whose worker dies mid-run still stays `generating` forever (unchanged from Prompt 5).

---

## Prompt 7: Dashboard (done)

**Built:**
- **`dashboard.html`:** plain HTML/JS, no build step, light and dark themes, works at phone width. It's served by a new `GET /` route in `app.py` (`FileResponse`). The page has:
  - a topic box;
  - a mode choice (Talking Head: "one person speaking to camera" / Story Time: "changing scenes with a voiceover narrator"; Talking Head is the default);
  - a clip length choice (10 seconds by default / 5 seconds "testing — cheaper");
  - a duration list whose options are whole numbers of clips (1 to 60) and follow the clip length (switching 10 s to 5 s keeps the same number of clips);
  - a resolution choice (480p default / 720p), with a note in Talking Head that clip 1 is always 720p;
  - a Generate button.
- **Generate** sends `POST /jobs`, then polls `GET /jobs/{id}` every 4 s. The timeline appears straight away (one card per clip, with the placeholders showing "Waiting for the script…") and fills in as the job runs.
  - Each card shows its status and resolution, plus the spoken line (Talking Head) or the narration and a short, clipped visual description (Story Time).
  - A finished clip gets a video player, and a failed clip shows its error. A failed job shows the job's error.
- **Other behaviour:**
  - Generate is disabled from the moment you press it until the job finishes, so a double click can't start (and pay for) two jobs.
  - The last job id is kept in the browser, so a reload picks the job up again and keeps following it.
  - A 422 shows the API's reason. If the server can't be reached, the page shows "Lost contact… retrying" and keeps polling.
  - All script text is inserted as plain text, never as HTML.
  - **Fix after your first dashboard run (2026-09-27):** the page used to rebuild the whole timeline on every 4 s check, recreating the video players. They flickered, a playing clip restarted, and each video's details were fetched from kie.ai again every time. Now a check that brings nothing new changes nothing; only the cards that changed are rebuilt; and a card keeps its existing player when its video link hasn't changed. Verified on a throwaway copy of the API: over a full simulated run the timeline was redrawn only on real status changes, and clip 1's player stayed the same element and never reloaded while clips 2 and 3 updated.
- **Pipeline error messages** now number clips from 1, like the dashboard: "clip 2 of 5 failed: …" instead of "clip 1 failed". The pipeline tests were updated and all pass.

**Verified** in the built-in browser against a throwaway copy of the API on port 8011 (its own Redis, no API keys, no worker, so nothing could run or spend). Progress was simulated by writing to that Redis:
- The mode, clip length, duration and resolution controls work: 5 s keeps 3 clips as 15 s, Story Time hides the 720p note, and an empty topic is blocked.
- A double click sent exactly one POST, and its body was stored exactly (Story Time, 3 x 5 s, 480p).
- Pending placeholders turned into scripted cards, then generating, then done, with real videos playing (your earlier Story Time clips as stand-in links). The button came back at the end.
- A Talking Head job at 720p failing at clip 2 showed the failed badge, the job error and the clip's error.
- A reload brought the last job back.
- A 422 showed "mode: Input should be…".
- With the API stopped mid-poll, the page showed "Lost contact… retrying" and followed the job to done once the API was back.
- At phone width (375 px) nothing scrolls sideways; the timeline scrolls inside its panel.
- The only console errors were the deliberate 422 and outage.

**On the real stack** (rebuilt; the container's `app.py` and `dashboard.html` match): `GET /` 200, and the dashboard shows your Talking Head job `0d31615a…` correctly (clip 1 at 720p, clips 2 to 5 at 480p, all five lines and videos). Only a `GET` was made, no job was created (still 5 in Redis) and the worker received nothing.

**Your test (2026-09-27):** a Talking Head job from the dashboard (`46957efd643943c89c7dfa5ced315d9b`, "A young woman fell in love with a guy after her marriage", 3 x 5 s at 480p). You report it all worked correctly: the job was sent, progress showed, and the timeline and videos appeared. In the store, clip 1 is 720p and clips 2 and 3 are 480p. The page's constant flicker you noticed during it was fixed the same day (above). Then a Story Time job from the dashboard (`041236d09b10407eaf91c6d3264aa2fb`, "A young woman talks about how she fell in love with a guy", 5 x 5 s): done, and the result is good. You have some points about it to discuss later (not logged yet). **Prompt 7 is complete.**

**The testing note as written:** from http://localhost:8001/, submit a job in each mode, watch the timeline, and check in the browser's network tab that `mode` in the POST body follows the selector. One job with 5 s clips covers Prompt 6's `clip_duration: 5` check. The 10 s runs still owed from Prompt 5.6 (Story Time 3 x 10 s, about 134 credits; Talking Head 3 x 10 s, about 178) can be these jobs.

**Decisions and gaps:**
- The duration list stops at 60 clips (10 minutes at 10 s, about 2,900 credits in Talking Head) to keep an accidental huge spend one extra step away. It's easy to extend when long videos are wanted. The cost estimate comes in Prompt 13.
- Clicking a clip does nothing yet (Prompt 8), and there's no final stitched video yet (Prompt 12).
- The browser keeps only the last job; there's no job list (not asked for, and "no other pages").

---

## Prompt 8: Timeline clip interaction (done, UI wiring only)

**Built:**
- **Clickable cards.** Clicking a clip card, or focusing it with Tab and pressing Enter/Space, selects it (the card is outlined). A panel under the timeline then shows "Clip N of M" and the clip's script: the spoken line (Talking Head), or the narration plus the full "On screen:" visual (Story Time), with the delivery for both.
  - Clicks on a clip's video player only play the video; they don't select the card.
  - The selection survives the page's progress updates and is cleared when a new job starts.
- **Two buttons, Regenerate Script and Regenerate Scene.** They call `POST /jobs/{job_id}/clips/{clip_index}/regenerate-script` and `…/regenerate-scene` (`clip_index` is 0-based, as in `Job.clips`) and show the reply under the buttons, e.g. "Not available yet: Regenerate Script for clip 2 is not implemented yet".
  - They're disabled while the job is still pending or generating (with a note saying so), while the clip has no script yet, and while a request is in flight.
- **Backend (`app.py`).** The two endpoints are placeholders. They check that the job and clip exist (404 "job not found", or "no clip at index N: the job has clips 0 to M"), then return 501 with a "not implemented yet" message. A shared `_require_clip()` helper does the check, ready for Prompts 9 and 10.
- **Also:** `color-scheme: light dark` on the page, so the browser's own scrollbars and dropdown match the dark theme; the job panel is no longer one big live region (only the status badge and messages announce changes).

**Verified** on a throwaway copy of the API (its own Redis, no keys, no worker), with simulated jobs:
- **Endpoints:** 501 with the right clip number for a real clip; 404 for an unknown job, for index 3 of 3 and for -1; 422 for a non-number; 405 for GET.
- **Story Time job:** selecting Clip 2 mid-run showed its narration, full visual and delivery, with both buttons disabled and the note. After the job finished, the selection was still there and the buttons were enabled. Each button sent exactly `POST …/clips/1/regenerate-script` or `…/regenerate-scene` (Clip 2 is index 1) and showed the 501 message. Enter on Clip 3 selected it, and clicking Clip 1's video didn't change the selection.
- **Talking Head job:** starting it cleared the old selection. Clip 1 showed its spoken line and delivery (no "On screen" line), and its button reached the placeholder.
- No script errors in the console.

**On the real stack** (rebuilt; the container's files match): the page has the new panel. Both placeholders on your Story Time job's clip 2 answered 501, and nothing was created or queued (7 jobs before and after; the worker received nothing).

**Your testing note: done (2026-09-27).** You clicked through clips on the dashboard and report it works. The note asked for a few clips on one job from each mode, the right script for each, and both buttons firing the right calls (two POSTs returning 501). **Prompt 8 is complete.**

**Decisions:**
- The regenerate buttons are disabled until the job has finished. Regenerating while the job is still generating would collide with the running job; what Prompts 9 and 10 do mid-job is theirs to decide.
- The panel shows the delivery as well as the line; the prompt only asked for the line (Talking Head) or the narration and visual (Story Time).

---

## Prompt 9: Regenerate Script, last clip only (done)

**Your decisions first (2026-09-27):**
- Middle clips and the cascade problem are set aside: only the last clip can be regenerated, and any other clip gets a 501 "mid-sequence regeneration not yet implemented".
- Story Time's Regenerate Script writes new narration only, keeps the `visual`, and renders the clip again. Regenerate Scene (Prompt 10) keeps the narration word for word and changes the scene: OpenAI writes a new `visual` that fits the same narration, and the clip is rendered from it. It isn't a new take of the old `visual` (clarified by you the same day).
- Recorded in `PLAN.md` (questions 1, 3 and 8) and in the guide.

**Built (in `app.py`):**
- **`POST /jobs/{job_id}/clips/{clip_index}/regenerate-script`** returns 202 `{"job_id", "clip_index"}` and does the work in a new Celery task, `regenerate_script_task`. The dashboard follows it by polling as usual.
  - Other responses: 501 for any clip but the last; 404 for an unknown job or clip; 409 if the job is still pending or generating, or a clip before this one isn't done; 503 if the queue refuses it (the job is then put back as it was).
  - Before queuing, `_claim_for_regeneration()` (since Prompt 12: `_claim_job()`) marks the job and the clip "generating" in one Redis transaction, so a double click gets a 409 instead of a second paid run.
- **`regenerate_line()` (OpenAI):** one Structured Outputs call per mode for a new line plus its delivery.
  - It's given the topic, the scene bible, the preceding clip's line, the line being replaced and, in Story Time, the kept visual.
  - It's told this is the last clip (or the whole video for a 1-clip job), uses the same word budget and rules as the script prompt, and has to write something clearly different.
  - The existing script call now shares its request code (`_ask_openai_json()`).
- **The regeneration itself:**
  - Talking Head: at the job's resolution, from the job's master video and audio.
  - Story Time: from the preceding clip's muted copy plus the job's audio and image anchors.
  - A 1-clip job's clip 1 is the master: it's regenerated with no references (Talking Head at 720p), then its anchors are made again from the new video.
  - Anchors older than 23 hours are made again from clip 1's video first, and so is a stale muted copy of the preceding clip (Story Time).
- **Nothing is lost on failure.** The clip keeps its old line and video until the new video exists; the new line and the new video are stored together. If anything fails (OpenAI, kie.ai, extraction), the clip keeps what it has and the error goes on the clip and the job; the job goes back to "done" (or "failed" if a clip still has no video). A later success clears the error, and a job whose last clip had failed becomes "done".
- **Refactor.** The pipeline's per-clip code (references, generating, storing, anchors, muting) moved into shared helpers (`_render_clip`, `_make_anchors`, `_fresh_anchors`, `_fresh_muted_copy`), used by both the pipeline and the regeneration. Anchors older than 23 hours are now refreshed in both modes, not only Story Time.
- **Dashboard.** A 202 shows "Regenerate Script started for clip N…" and starts following the job again. The Generate and regenerate buttons stay disabled until it ends, and the page then says "…finished: clip N is updated", or shows the error and that the clip kept its previous version. A middle clip shows the 501 message.

**Verified offline** (internal Docker network, throwaway Redis, fake OpenAI and kie.ai, real ffmpeg with the real extraction and muting), 39 checks:
- **The OpenAI request:** it carries the right context, schema and word budget in each mode.
- **What gets generated:** each case sends exactly the right references and resolution:
  - the last clip of 3 in both modes;
  - both 1-clip cases;
  - stale anchors, and a stale muted copy.
- **What gets stored:** the new line and video; the visual unchanged; the untouched clips identical.
- **Failures:** kie.ai and OpenAI failures keep the old clip, a retry of a failed last clip works, and the errors clear on success.
- **Endpoint rules:** 501, 404, 409 for a double click and for a pending job or unfinished earlier clip, and 503 with the job put back.
- **Regressions:** the full pipeline suite still passes (67 checks) after the refactor.
- **End to end with a real Celery worker that had no API keys:** `POST` returned 202, the worker ran `regenerate_script_task`, it failed at "OPENAI_API_KEY is not set", and the old clip and line were kept.

**On the dashboard** (throwaway API, no worker, completion simulated):
- A middle clip showed the 501 message.
- The last clip went to "generating", with all buttons disabled.
- The new line appeared on the card and in the panel, with "finished".
- A failure showed the error and kept the clip.

**On the real stack** (rebuilt; the worker lists `app.regenerate_script_task`): a middle clip of your Story Time job got the 501, Regenerate Scene is still the 501 placeholder, and index 9 got a 404. Nothing was created or queued. A last clip wasn't pressed, because that spends credits.

**Your test (2026-09-27): done, "it works good". Prompt 9 is complete.** The testing note: on a finished job in each mode, select the **last** clip and press Regenerate Script. Check that the new line differs but fits the story, and that the new video still looks and sounds like the clip before it. One 5 s clip costs about 24 credits plus a small OpenAI call. Your 3-clip Talking Head job and 5-clip Story Time job both work.

**Decisions and gaps:**
- The new line comes with a new delivery (tone), written for it; the prompt only mentioned the line.
- The replaced video's link isn't kept (kie.ai still has the file for 14 days, but the job no longer points to it).
- In Talking Head, regenerating the last clip is a new take from the master, so it lines up with the clip before it the way every clip does (the usual small pose reset at the cut).

---

## Prompt 10: Regenerate Scene, last clip only (done)

**Built (in `app.py`):**
- **`POST /jobs/{job_id}/clips/{clip_index}/regenerate-scene`** returns 202, with the same rules as Regenerate Script: last clip only (501 "mid-sequence regeneration not yet implemented" otherwise), 404, 409 while anything runs on the job (a Script click during a Scene run is refused too), and 503 with the job put back. Both endpoints now share `_start_regeneration()`.
- **New Celery task `regenerate_scene_task`.** It and `regenerate_script_task` both call one shared `_regenerate(job_id, clip_index, action)`, which keeps the "nothing lost on failure" rules. Errors are labelled "Regenerate Scene for clip N failed: …".
- **Talking Head:** the same line and delivery, rendered again from the same prompt and references (the master video and audio). No OpenAI call. It's a new take.
- **Story Time:** the narration and delivery stay word for word. `regenerate_visual()` asks OpenAI for a **new** `visual`, a clearly different scene that still shows what the narration is about, follows the previous clip and keeps the characters and style. It's given the topic, the scene bible, the previous clip's narration and visual, this clip's narration and its current visual. The clip is then rendered from the new visual with the Story Time references. The new visual is stored only together with its new video, so a failure keeps the old visual and video.
- **A 1-clip job:** the only clip is the master or character reference. Story Time's new visual must clearly show the main character (as the script prompt requires for clip 1), and the anchors are made again from the new video; Talking Head is re-rendered at 720p.
- **Dashboard:** no change needed. Its Regenerate Scene button already follows a 202 and reports "Regenerate Scene started / finished / failed".

**Verified offline** (internal Docker network, throwaway Redis, fake OpenAI and kie.ai, real ffmpeg), 18 new checks, all passing:
- Talking Head last clip: no OpenAI call, one generation from the identical prompt with the master references, same line, new video.
- Talking Head 1-clip job: 720p, no references, anchors made again.
- Story Time last clip: one OpenAI call for a visual only, with the right context; a new visual stored with the same narration; rendered from the new visual with the muted previous clip, audio and image.
- Story Time 1-clip job: the first-clip rule is in the system prompt; the first-clip template from the new visual; anchors made again.
- OpenAI and kie.ai failures keep the old visual and video.
- Endpoint rules: 501, 404, 409 for scene-then-scene and scene-then-script, and 503 with the job put back.

All 38 Regenerate Script checks and the full pipeline suite (67) still pass.

**End to end with a real Celery worker that had no API keys:**
- Talking Head got as far as kie.ai ("KIE_API_KEY is not set"); Story Time stopped at OpenAI ("OPENAI_API_KEY is not set").
- Both kept the old clip.

**On the dashboard** (throwaway API, completion simulated): Regenerate Scene on Story Time's last clip showed "started", and the buttons were disabled. Then Clip 3 had the same narration and a new "On screen" scene, with "finished".

**On the real stack** (rebuilt; the worker lists `app.regenerate_scene_task`): a middle clip got the 501 and index 9 got a 404, with nothing created or queued. A last clip wasn't pressed, because that spends credits.

**Your test (2026-09-27): done; you report it all works. Prompt 10 is complete.** The testing note: on a finished job in each mode, select the **last** clip and press Regenerate Scene.
- Talking Head: the line on the dashboard is unchanged, and the video is a new take.
- Story Time: the narration is unchanged, and the scene (the "On screen" text and the video) is different.

About 24 credits per 5 s clip, plus a small OpenAI call in Story Time.

---

## Prompt 11: deferred

Skipped for now at your request (2026-09-27), to come back to after Prompt 12. Its gate (Tests B and D, run by hand on kie.ai) isn't met, and you had set the hard case aside. Middle clips keep answering 501. When we come back to it:
- Talking Head can regenerate a middle clip (not clip 1) exactly like the last one, from the master, with no bridging.
- Story Time needs either Test D plus bridging, or the fallback of regenerating everything after the clip.

---

## Prompt 12: Final video assembly (done)

**Where and when:**
- **Automatically** in the worker, at the end of every job, and again after every successful regeneration, so the download always matches the current clips. The job stays "generating" until it's ready; a failed build never fails the job.
- **On demand:** `POST /jobs/{job_id}/assemble` (202; 409 while the job is generating or if a clip isn't done; 404; 503 put back), via a new `assemble_task`. It's for jobs finished before this existed and for a retry. The claim step is shared with the regenerate buttons (`_claim_job()`, formerly `_claim_for_regeneration()`).
- **Served** at `GET /jobs/{job_id}/video` (MP4, with byte ranges so the player can seek; 404 until built). The job's id is checked against Redis before it's used in a file path.
- **Files** live in a new Docker volume, `media` (mounted at `/srv/media` in the api and the worker; `MEDIA_DIR`), one folder per job:
  - `clips/`: every clip downloaded once and kept (kie.ai deletes its copies after 14 days), named after its URL, so a regenerated clip is a new file and an unchanged one is never fetched twice;
  - `norm/`: the clips prepared for joining (cached);
  - `final.mp4`.
- **New job fields:** `final_video_at` (when it was built) and `final_error`.

**How it joins (`assemble_final_video()`):**
- **Size:** every clip is scaled to the job's resolution, the size of a clip rendered at it (864x496 at 480p), since Talking Head's clip 1 is 720p. It uses a constant frame rate (24).
- **Audio:** cut to the length of the picture (Seedance's audio runs about 46 ms past the last frame), with 20 ms fades at both ends of each clip so the joins can't click, and kept as PCM in the prepared file.
- **Encoding:** the video is encoded once at high quality (x264 CRF 16). The prepared clips are then joined without a second video encode, and the audio is encoded once (AAC 192k) for the whole video. A clip with no audio track gets silence.
- **Safe replacement:** the finished file replaces the old one in one step, so a half-written video is never served. A failed build removes an older final (it would no longer match the clips) and records the error.

**Verified offline** (internal Docker network, throwaway Redis, real ffmpeg on synthetic clips shaped like Seedance's), 23 checks:
- **Talking Head, 720p clip 1 plus three 480p clips:** one 864x496, 24 fps video with all 484 frames. Audio and picture are the same length (20.165 vs 20.167 s). No black frames and no audio dropouts at the joins. The first frame matches clip 1 scaled down.
- **Rebuilding:** nothing is downloaded again (1.3 s instead of 8.1 s). After a clip changes, only the new clip is downloaded, and the final ends with it.
- **A 720p Story Time job** stays 1280x720, and a clip with no audio gets silence with sync intact.
- **Refused:** an unfinished job.
- **Through the worker code:**
  - a finished job builds its final by itself while still "generating";
  - a regeneration rebuilds it;
  - the endpoint claims the job, a second click gets a 409, and the task puts it back to done;
  - 409 for an unfinished job, 404 for an unknown one;
  - the video is served, including byte ranges; a job without a final and a path-like id both get a 404;
  - a failed build records the error, removes the stale final and keeps the job done, and "Try again" clears it.
- **Regressions:** the pipeline suite (67) and the regenerate suite (56) still pass.

**Dashboard** (tested on a throwaway API with a scratch media folder and synthetic clips):
- A "Final video" block above the timeline.
- An older job shows "This job finished before final videos were made automatically" with a **Build final video** button. Pressing it showed "Joining the clips into the final video…".
- Then a player loaded the result (864x496, 15.1 s), with a **Download video** link named after the topic (`a-young-woman-tells-her-breakup-story.mp4`) and "3 clips joined at 480p · built …".
- A failed build shows the error and **Try again**.
- A new job shows "Joining…" before it finishes. The player's address changes with every build, so the browser never plays an old copy.

**On the real stack** (rebuilt; the `media` volume was created, the worker can write to it and the api sees the files, and the worker lists `app.assemble_task`): your existing jobs have no final yet (`GET …/video` 404), so the page offers "Build final video" for them. I didn't press it, because it downloads your clips from kie.ai's storage (free, but kie.ai is yours to touch).

**Your testing note (no credits needed):**
- Open one of your finished jobs in each mode and press **Build final video**.
- Then download and watch it straight through: no stutter, black-frame gap or audio pop at the joins (separate from the AI seams you already know).
- For Story Time, also check that the audio level and the ambient sound stay steady across the joins.
- New jobs build their final video by themselves.

---

## Talking Head: the breath before each clip's first word, cut in the final video (2026-09-27)

**What you noticed:** in Talking Head the speaker takes a breath or sighs at the start of every clip.

**What the analysis showed** (your job `4ac3f6cb…`, 4 x 5 s, clips analysed locally from the media volume):
- 3 of 4 clips open with silence and/or a breath before the first word: clip 1 waits about 1 s (faint inhale near the end), clips 2 and 3 about 0.2–0.35 s. Clip 4 ("gentle and hopeful") starts speaking at once.
- It is **not** clip 1's reference audio leaking into the others (the Test F problem): each later clip's opening is no more similar to clip 1's opening than unrelated audio is. Seedance simply opens each take with a breath; emotional delivery words seem to invite it.

**Your decision:**
- Don't touch the prompt. Words like "no breath, no pause" could make the delivery flat and rushed.
- Cut the breath in the final video instead, in **Talking Head only**, and keep clip 1's opening (the breath there reads as her settling in).
- You compared three prototype versions of your job: untouched, all clips trimmed, and clip 1 whole with the rest trimmed. You chose the last.

**Built (in `app.py`, final-video step only; generation and the clips themselves are untouched):**
- **`_lead_in()`** reads the first 3 s of a clip's audio in 20 ms slices:
  - it finds the first **voiced** slice (within 18 dB of the clip's loudest, and tonal: low spectral flatness, since breath and hiss are noisy);
  - it steps back while the sound is still at speech level (within 25 dB), so the first word's own consonant, like the "Sh" of "She", is kept;
  - it cuts 60 ms before that, rounded down to a whole frame so picture and audio are cut at the same instant (lip sync holds), and never more than 1.5 s;
  - if there's no voice in the first 3 s, it cuts nothing.
  
  Everything cut is at least 25 dB quieter than the voice.
- **`_normalized()`** takes `trim_lead_in`. The clip then starts at the cut, with a 30 ms audio fade-in, and is cached as `<clip>_<size>_trim.mkv`.
- **`assemble_final_video()`** applies it to Talking Head clips 2 onward. Story Time is unchanged.
- **`numpy==2.5.3`** is added to `requirements.txt` (the image was rebuilt).
- **Visible effect:** a Talking Head final video is now slightly shorter than clips x clip length, by the lead-ins removed.

**Verified:**
- **Your 4 real clips:** the production detector gives the same cuts as the prototype you approved (0.96 s, 0.25 s, 0.17 s, 0 s; clip 1's is not applied).
- **Synthetic clips** shaped like a real take (silence, a faint breath about 32 dB under the voice, a loud "Sh"-like consonant, then voice):
  - the cut lands 60 ms before the consonant;
  - speech from the first frame isn't cut;
  - a 2.7 s lead-in is cut by at most 1.5 s;
  - no voice in the first 3 s, or no voice at all: nothing is cut.
- **In a Talking Head final:** clip 1 is kept whole with its breath; clips 2 and 3 start with only a faint breath tail (under -40 dB), then the whole consonant; audio and picture are the same length.
- **In Story Time:** nothing is trimmed.
- **Regressions:** the assembly (23), pipeline (67) and regenerate (56) suites still pass.

**Live:** deployed. Your job `4ac3f6cb…`'s final video was rebuilt with the new rule, from the clips already in the media volume (no downloads, 5 s). It's now 19.75 s: clip 1 whole, 0.25 s and 0.17 s cut from clips 2 and 3, clip 4 unchanged. Every new Talking Head job gets this automatically, as does every rebuild after a regeneration.

**Not done:**
- Story Time, whose narrator may also breathe in at the start of a clip. Your call to leave it for now.
- Breaths between sentences are left alone on purpose.

---

## Movie Mode: Multi-Speaker Dramatic Scene Pipeline (`movie_scene_multispeaker.py`) (2026-10-01)

### 1. What Movie Mode Does
Movie Mode (`movie_scene_multispeaker.py`) is the multi-character dramatic storytelling pipeline designed to scale AI video generation across long, continuous multi-clip narratives (proven up to 60 clips / 5+ minutes). Unlike single-character Talking Head or single-narrator Story Time, Movie Mode orchestrates:
- **Multiple simultaneous characters:** Independent visual identities, physical blocking, spatial proximities, and conversational dialogue with dynamic lip sync.
- **Strict continuity tracking:** A persistent **Scene Bible** and **Prop Diary** that track character health/injury states, exact physical positions, props, and ammunition counts across every cut.
- **Actor voice persistence:** Automatic harvesting of voice samples from the characters' first spoken lines, reused across all subsequent clips as `@Audio1+` reference tracks to keep voices identical throughout the film.
- **Interactive Terminal Workflow:** Generates and validates each 3-clip chapter with OpenAI, displays the compiled Seedance prompt in the terminal for human review, and supports hot-reloading (`r`) directly from the script JSON without restarting the run.

---

### 2. Architecture & How It Works

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│ 1. User Story Input (e.g. story.txt psychological thriller)                     │
└──────────────────────────────────────┬──────────────────────────────────────────┘
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│ 2. Outline & Master Beats: 60 timed beats (5 seconds each)                      │
└──────────────────────────────────────┬──────────────────────────────────────────┘
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│ 3. Scene Bible Generation: Characters (looks/voices), Locations & Props         │
└──────────────────────────────────────┬──────────────────────────────────────────┘
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│ 4. Phase 1.5 (FLUX 1 Kontext): 25 Reference Images Cached                       │
│    • 3 Cast Reference Portraits (text-to-image)                                 │
│    • 8 Location Master Pictures (text-to-image)                                 │
│    • 14 Location Angle Variations (Kontext image-to-image edit mode)            │
└──────────────────────────────────────┬──────────────────────────────────────────┘
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│ 5. Chapter-by-Chapter Scripting (OpenAI, 3 clips/chapter):                      │
│    • Strict validation (_check_chapter): movement bounds, dialogue word count,  │
│      speaker visibility, prop consistency, timeline continuity                  │
└──────────────────────────────────────┬──────────────────────────────────────────┘
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│ 6. Prompt Compiler (build_multi_prompt):                                        │
│    Compiles structured chapter JSON into dense, highly-specific prompts         │
│    formatted for Seedance-2-mini / Seedance-2-fast on kie.ai                    │
└──────────────────────────────────────┬──────────────────────────────────────────┘
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│ 7. Interactive Execution Loop (Terminal 1):                                     │
│    Prompt Review ──► [y = generate | r = reload from script json | q = quit]    │
└──────────────────────────────────────┬──────────────────────────────────────────┘
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│ 8. Smooth Video Assembly (Permanently integrated with app.py):                  │
│    • app._lead_in(): Spectral audio onset detection trims dead silence          │
│    • app._normalized(): Lanczos scaling, SAR=1, 24 fps, boundary micro-fades   │
│    • Final Concatenation: Seamless, broadcast-ready mastercut                   │
└─────────────────────────────────────────────────────────────────────────────────┘
```

---

### 3. Detailed Anatomy of the Prompts We Give to Seedance

Everything Seedance sees must be completely self-contained within each clip's compiled prompt (`build_multi_prompt`). Seedance has zero memory between requests; prompt precision is the only mechanism that prevents character drifting, hallucinated props, and floating cameras.

#### A. Camera Angle, Lens & Lighting Prompts
- **Lens & Perspective:** Specifies exact camera placement, height, and angle relative to the action (e.g., *"Camera placed low at mud level framing Clara crouched on frame left directly adjacent to Marcus pinned beneath the fallen log on frame right"* or *"Extreme Close-Up of his rain-slick face and slowly zooming inward while locking on his steel-blue eyes, resolving with both unblinking eyes filling the entire frame"*).
- **Camera Movement:** Dictates precise camera motivation rather than random drifting (e.g., *"the camera pans and jerks dynamically as Julian emerges..."* vs. *"slow, creeping, continuous push-in"*).
- **Dual Lighting & Tone:** Directs contrasting light sources to maintain cinematic mood (e.g., *"warm amber light from the glowing oil lantern in the foreground mud warms the rain and fallen timber, while cold pale moonlight rims Julian's dark jacket against the dark misty pine forest"*).
- **Depth of Field:** Explicitly defines focal plane and background falloff (e.g., *"the clearing behind him dissolves into deep soft bokeh with an extremely shallow depth of field"*).

#### B. Character Blocking & Spatial Coordinates
To prevent characters from teleporting, changing clothes, or switching positions across cuts, every character has structured blocking rules:
- **`position` & `posture` (Start):** Where the character begins (e.g., *"crouched on frame left less than a foot from Marcus, lowering the smoking, empty revolver in shock and despair"*).
- **`end_position` & `end_posture` (Finish):** Where the character ends the 5-second take (e.g., *"lying flat on her back in the mud directly alongside Marcus beneath the fallen trunk, stunned, breathless, and motionless"*).
- **`facing`:** Eye-line and body orientation (e.g., *"directly toward the camera with an unblinking, pitiless stare"*).
- **`awareness`:** Psychological state and perception (e.g., *"Locks his unblinking stare into the lens, knowing his ruthless vengeance is complete"*).

#### C. The Prop Diary (`prop_state`)
Every physical object is tracked continuously across the entire film:
- **Holder:** Identifies who holds the prop (`"Julian Vale"`, `"Clara Whitmore"`, or `"scene"` when resting on the ground/table).
- **In-Frame:** `true` only when the camera clearly frames it, preventing the model from drawing background props into tight close-ups.
- **Physical State & Ammo Tracking:** Exact condition (e.g., the revolver is tracked clip-by-clip from 6 loaded brass cartridges -> 5 -> 4 -> 3 -> 2 -> 1 -> strictly 0 rounds empty after firing into the water reflection; the oil lantern tracked as glowing with warm amber light; the tactical flashlight tracked as half-submerged in mud).

#### D. Micro-Timed Action Steps (`[0.0s to 1.4s]`, etc.)
Rather than a vague sentence, action within the 5-second window is broken down into timed choreography:
```text
[0.0s to 1.4s] Clara crouches on frame left less than a foot from Marcus, lowering the smoking empty revolver in shock; Julian emerges silently from the dark pine shadows directly behind Clara, stepping onto the wet mud.
[1.4s to 2.8s] Julian brings his gloved right hand down in a hard chop across Clara's wrists, knocking the empty revolver spinning into the mud puddle beside the glowing lantern, and seizes Clara's coat shoulders as she gasps in terror.
[2.8s to 5.0s] Julian forcefully drives Clara backward over the slick ravine lip; Clara's boots slip on the wet mud and she tumbles backward onto her back, landing breathless and motionless in the mud right beside Marcus as Julian steps up to tower over both of them.
```

#### E. Dialogue, Word Budget & Voice Matching
- **Word Budget:** Enforces `MIN_WORDS = 8` to `MAX_WORDS = 16` per speech clip (calculated at ~2.5 words/second). Prevents rushed or clipped dialogue.
- **Voice Mapping:** References the actor's verified audio sample (e.g., `Julian Vale speaks in the voice of @Audio1, Cold, quiet, and ruthless with chilling finality: "You chose this ending. Those who betray must die."`).
- **Lip Sync Rules:** Directs Seedance to animate natural lip movements matching the line only for the visible speaker, while ensuring non-speaking characters keep their mouths closed.

---

### 4. Smooth Video Assembly Integration (`app.py` Integration)

#### The Problem Discovered:
When `movie_scene_multispeaker.py` originally generated `master_final.mp4`, it used a naive `ffmpeg -c:v copy` concat. Seedance-2 naturally injects **0.5s to 1.5s of dead air, silence, and breathing** before speech or action. Glued together raw, these pauses caused jarring hard cuts and stuttered pacing.

#### The Permanent Upgrade:
We upgraded `assemble_test_video()` inside `movie_scene_multispeaker.py` to directly invoke the core `app.py` video assembly engine:
1. **Spectral Voice Onset Detection (`app._lead_in`):** Uses Fourier-transform audio analysis in 20 ms slices to detect tonal voice onset and trim away the dead silence and hesitation before speech.
2. **Audio Micro-Fades:** Applies subtle fade-ins and fade-outs (20–30 ms) at each cut boundary to eliminate audio clicks, pops, and room-tone drops.
3. **Lanczos Video Normalization (`app._normalized`):** Standardizes all clips to constant 24.0 fps, SAR=1, Lanczos scaling, and x264 CRF 16 with uncompressed PCM audio before joining.

#### Results on the 60-Clip Master:
- **Raw Concat Duration:** `305.34 s` (5.09 min)
- **Smooth Assembly Duration:** `269.06 s` (4.48 min)
- **Dead air / awkward hesitation trimmed:** **`36.28 seconds`** across the 60 clips!
- **Outcome:** The mastercut plays with continuous, tight, television-grade cinematic pacing.

---

### 5. 60-Clip Project Milestone Summary

- **Production Status:** 60 / 60 clips completed and verified with zero validation errors.
- **FLUX Reference Images:** 25 total generations (3 cast portraits + 22 location views across 8 settings).
- **Seedance Image Injections:** 305 reference image injections (~5.1 per clip) ensuring perfect character and set continuity.
- **Archival Package:** All 60 `.mp4` video clips, 62 Seedance `.json` request blocks, 40 quality-check inspection frames, the master script, and both master cuts are stored in [`Majore 5 minute Project/`](file:///e:/AI%20Video%20Extender/AI%20Video%20Extender/Majore%205%20minute%20Project).

---

### 6. Full End-to-End Pipeline Automation (2026-10-02)

- **Interleaved Execution (`CLIPS_PER_CHAPTER = 1` default):** Rather than generating 3 clips of script at once, the pipeline now automatically interleaves clip-by-clip:
  1. Master plan generated (Outline, Scene Bible, Beats, FLUX images).
  2. Clip 1 script generated by OpenAI -> Clip 1 video generated on kie.ai -> Voice samples harvested.
  3. Clip 2 script generated with Clip 1 continuity context and banked voice reference -> Clip 2 video generated.
  4. Continues automatically for all clips.
  5. Final mastercut video (`master_final.mp4`) automatically assembled with audio onset trimming and Lanczos normalization.
- **Zero-Touch Automation:** Eliminated all mandatory terminal `[y]` input pauses (prompt review confirmation, per-clip continuation pauses, chapter review pauses, non-critical warnings).
- **Optional Interactive Mode:** Kept `--interactive` CLI flag for when a human director wants manual review and JSON hot-reloading (`r`) between clips.

---

### 7. Story Videos Frontend & Pipeline Integration (2026-10-02)

- **Third Mode ("Story Videos"):** Fully integrated alongside "Talking Head" and "Story Time" in `dashboard.html` and `app.py`.
- **Backend Architecture (`app.py`):**
  - Updated `Mode` type to include `"story_videos"`.
  - Added `movie_script: dict | None` to the `Clip` model to store rich screenplay data (blocking, dialogue array, actions, shot descriptions).
  - Added `movie_bible`, `beats`, `cast_bank`, `location_bank`, and `voice_bank` to the `Job` model.
  - Added `story_videos_uses_5s_clips` validator to `ClipRequest` to guarantee 5-second clips.
  - Linked Celery `run_generation_job` task to `_run_movie_job`:
    1. Phase 1: Master plan generation via OpenAI (`movie.write_outline`).
    2. Phase 1.5: FLUX image generation for cast portraits and Kontext viewpoint angles.
    3. Phase 2: Interleaved clip scripting (`movie.write_chapter`) and rendering (`movie.render_clip`), with automatic voice banking for newly introduced speakers.
    4. Phase 3: Automated final assembly (`_assemble`).
- **Validation & Retry Decoupling (`movie_scene_multispeaker.py`):**
  - Decoupled soft warnings (`[SOFT]`) from hard validation errors.
  - Word count fluctuations, speech tempo checks, and semicolons are treated as informational warnings and do not trigger OpenAI retries.
  - Visual, spatial, and blocking continuity violations (teleportation, character placements, prop errors) strictly trigger OpenAI self-correction loops.
- **Frontend UI (`dashboard.html`):**
  - Added "Story Videos" mode radio option (`story_videos`).
  - Added auto-selection of 5s clip duration when "Story Videos" is selected.
  - Timeline cards render first dialogue line and location pin emoji.
  - Detail inspection panel shows full multi-turn dialogue, shot setup, and location.

---

### 8. Prompt Inspection Hover Cards & Interactive Parameter Editor (2026-10-02)

- **Hover Inspection on "Regenerate Script":**
  - Floating card displaying human-comprehensible components: mode directive, story beat, preceding clip continuity, current line to replace, delivery guidance, Scene Bible world summary, and timing word budget.
- **Hover Inspection on "Regenerate Scene":**
  - Floating card displaying what is sent to the AI video model: visual framing & shot setup, spoken line with delivery, reference inputs (`@Video1`, `@Audio1`, `@Image1..N`), audio bed directives, and the full compiled Seedance prompt string.
- **Interactive Parameter & Prompt Editor Modal:**
  - Added **"✏️ Edit & Customize"** button in clip details.
  - Modal with tabs for **Video Scene Input** and **Script & Dialogue**.
  - Direct form controls for dialogue lines, emotional delivery, visual scene description, camera shot, and action steps.
  - **Live Prompt Compiler:** Monospace preview box that dynamically updates as the user types, showing the exact prompt Seedance will receive.
  - **Save vs. Regenerate:**
    - `💾 Save Edits`: Updates clip via new `PATCH /jobs/{job_id}/clips/{clip_index}` without triggering video generation.
    - `✨ Regenerate with Edits`: Dispatches regeneration with the custom parameters applied.
  - **Custom Edit Protection & Bypass Logic:**
    - If a clip has been custom-edited (even a single character in Dialogue, Delivery, Visual, or Compiled Prompt Preview), `clip.custom_edited` is marked `True`.
    - Regenerating a custom-edited clip strictly bypasses OpenAI (`regenerate_line` and `regenerate_visual` are bypassed), rendering the video directly with the user's exact customized text.
    - If a clip is untouched, standard automated OpenAI rewriting occurs.
    - Added `↺ Reset to AI Auto` option in the editor to revert a clip back to automated AI generation if desired.
- **Backend Regeneration Support Across All Modes:**
  - Updated `_regenerate` and Celery tasks to accept custom field overrides.
  - Added `_render_movie_clip_at` enabling Story Videos clip regeneration as well.

---

## Carried forward (do not lose)

**Parked (no action now)**
- Model for Story Time motion shots: `seedance-2-5` rendered a walking shot cleanly where `seedance-2-mini` distorted faces. Check its cost, kie.ai model id and reference support when this is picked up (`PLAN.md` Section 7, question 12).

**Prompt 5 (done): what is still open**
- **The 720p-master pipeline at 10 s** (yours): the 5 s run through the worker finished as designed; a run at the production 10 s length is still to do (about 82 + 48 per later clip).
- **Cost at 10 s clips:** each later clip bills the whole 10 s master, about 48 credits, and the 720p first clip about 82. A shorter excerpt of the master as the reference would cut that; untested whether quality holds.
- The accepted trade-off: every clip starts from the master, so each cut has a small pose reset rather than continuous motion.
- Word budget: at about 2.2 words/s a 22-word line (10 s clips; 11 words at 5 s) is roughly the whole clip of speech with little room for pauses. The live run's last line was 10 words, so the budget was not exceeded, and the audio problem is now attributed to the reference chain, not the word count. Keep an eye on clipped endings; if they appear, lower the 2.2 factor in `_word_budget` (try 1.8 to 2.0).
- Live runs have shown that kie.ai accepts our uploaded audio, frames and muted videos as references, including the 1280x720 master (kie.ai requires 409,600 to 927,408 total pixels and 24 to 60 fps). Not yet checked: a 10 s master as the reference (inside the 15 s limit).
- Talking Head template says "She speaks directly to camera", but `scene_bible` follows the topic, so a male or non-binary speaker contradicts it (`PLAN.md` Section 7, question 11).
- Known limitation (Test A, accepted): a slight saturation/color shift at the seam between Talking Head clips gives a faint "cut" feeling. Not a character or lip-sync problem; no fix pursued. Logged in `PLAN.md` Section 6.
- The audio reference is still the untrimmed first-clip audio. You consider the audio settled for now; if ghosting ever comes back, the untested options are a properly trimmed or much shorter reference (never its ending), or none at all.
- The job store does not record credits per clip; adding a `credits` field to `Clip` would help the Prompt 13 estimate.
- The master's muted copy and audio expire after 24 hours. Since Prompt 9, `_fresh_anchors()` re-makes them from clip 0's `video_url` (valid 14 days) when `anchor_extracted_at` is older than 23 hours, before every later clip and every regeneration. `_fresh_muted_copy()` does the same for a Story Time clip's muted copy.

**Prompt 5.6 (done): what is still open**
- **The 10 s Story Time run and a Talking Head job on the current code** (yours): use the run command above with `CLIPS = 3` and `CLIP_SECONDS = 10`, once with `MODE = "story_time"` and once with `MODE = "talking_head"`.
- **Watch item, not a blocker:** quality falling off down a long Story Time chain, as Talking Head's chained video did (Test G). The first 5-clip run showed a slight fall-off, accepted for now; keep an eye on it on longer jobs.
- The formula needs the first clip to show the main character: the Story Time script prompt (built in 4.6) requires it, and it held in every real script so far, but it is enforced by the prompt only, not checked in code.

**Later prompts**
- `Job.resolution` and `Job.mode` duplicate `request.resolution` and `request.mode`; `POST /jobs` (Prompt 6) keeps them in sync, and anything else that ever creates a job must too.
- Prompt 7 (done): the Generate button is disabled from the first click until the job finishes.
- Concurrency: once tasks run concurrently, change clips with `update_clip`, not `get_job` then `save_job`, which overwrites the whole job.
- Retention: extracted frame/audio URLs expire after 24 hours, so a regenerate done later must re-extract them from the clip's video URL. Generated videos expire after 14 days, so Prompt 12 must download the clips.
- Prompts 9 to 11: in Talking Head no clip depends on the one before it any more, so the cascade problem (and the bridging in Prompt 11) may not apply there, except for clip 0, the master. Undecided (`PLAN.md` Section 7, question 1); the guide keeps the last-clip-only limit until you decide.
- Prompt 11: the 15 s total cap on reference videos and audios breaks dual bridging at 10 s clips. A pass with 5 s clips does not validate production; the guide requires a final test at 10 s with trimmed references.
- Prompt 12: Talking Head's clip 0 is 720p and the rest are the job's resolution, so assembly must scale every clip to one size and re-encode (a plain stream-copy join fails). Each clip's `resolution` is stored.
- Prompt 13: use the measured billing pattern (`PLAN.md` Section 2): 3.8 credits/s at 480p and 8.2 at 720p with no references; with a reference video, 2.4 credits/s of (output + reference video). Later clips at 720p output are unmeasured. The guide's Prompt 13 has a note.

**Environment**
- Host-side Python: `app.py` defaults `REDIS_URL` to `localhost:6379`, which on this machine is the other project's Redis. Run shells via `docker-compose exec api python`, or set `REDIS_URL=redis://localhost:6380/0` first.
- The one-off experiment runners (Test S, the Formula B test and Test F) were deleted on 2026-09-26, and `tail_ref_test.py` (Tests G to I) on 2026-09-27; nothing depends on them. Their results are recorded in this file and in `PLAN.md`, and the videos and measurements are in `test_results/` (not git-ignored yet).
- Docker Desktop does not start with Windows on this machine: after a restart, start it before `docker-compose` commands. This project's containers have no restart policy, so they stay stopped until `docker-compose up`.
- Webhooks instead of polling are possible later (you have ngrok); it needs a public callback route and polling kept as a backup (`PLAN.md` Section 7, question 10).

**Still open (`PLAN.md` Section 7):** script context on regenerate, copyright-filter retry, mid-clip bridging quality, what the regenerate buttons mean in Story Time, webhooks, cost estimation, the pronoun in the Talking Head template, and the parked model question for motion shots. Resolved on 2026-09-27: question 13 (Talking Head references on longer chains, by the 720p master) and question 14 (Story Time keeps a chained, now muted, video reference; its long-chain quality is a watch item). Resolved on 2026-10-02: Aspect ratio set to 9:16 vertical and NSFW filter disabled across all generations.

---

## Update: 9:16 Aspect Ratio and NSFW Filter Disabled (2026-10-02)

- **9:16 Vertical Framing:**
  - `app.py`: `_clip_input` now includes `"aspect_ratio": "9:16"` on every Seedance clip creation request.
  - `movie_scene_multispeaker.py`: `generate_flux_image` now sends `"aspect_ratio": "9:16"` for `flux1-kontext` character portraits and location master/angle generations.
  - `FINAL_SIZES` in `app.py` updated to 9:16 portrait dimensions: `{"480p": (496, 864), "720p": (720, 1280)}`.
- **NSFW Checker Disabled:**
  - `_clip_input` in `app.py` sets `"nsfw_checker": False`.
  - `generate_flux_image` in `movie_scene_multispeaker.py` sets `"nsfw_checker": False`.
- **UI & Dashboard Updates:**
  - `dashboard.html`: `.seg video` and `.final video` updated with `aspect-ratio: 9/16` and `object-fit: contain` for vertical display.
---

## Update: Master Plan Review & Story Progression Approval (2026-10-03)

- **Two-Phase Story Videos Pipeline:**
  - **Phase 1 (Master Plan Generation):** When a Story Videos job starts, `run_generation_job` asks OpenAI for the outline (`scene_bible` + `beats`), writes `master_plan.json` to the job's media directory, saves the plan to Redis, and pauses with `status="plan_ready"`. No FLUX images or video clips are rendered yet, avoiding unwanted credit consumption.
  - **Phase 2 (Approval & Execution):** When the user approves the plan on the dashboard, `POST /jobs/{id}/approve-plan` saves any edited beats/bible, updates `master_plan.json`, marks `status="generating"`, and enqueues Celery task `execute_movie_job`. This proceeds with FLUX cast/location image generation and per-clip scripting and rendering.
- **Master Plan Review & Editing UI (`dashboard.html`):**
  - Dedicated **Story Progression & Master Plan Review** card appears when `status === "plan_ready"` (with purple `Plan Ready for Review` badge).
  - Displays each planned beat with editable **Action text area**, **Location ID input**, and **Dialogue / Silent beat toggle**.
  - Includes collapsible **Scene Bible Overview** showing generated characters (looks, voices) and locations.
  - Actions: **"▶ Approve & Start Video Generation"**, **"💾 Save Edits"**, and **"🔄 Re-plan Story"**.
- **Backend Endpoints:**
  - `GET /jobs/{id}/plan`: Returns the master plan JSON.
  - `PATCH /jobs/{id}/plan`: Saves user edits to beats and bible without triggering generation.
  - `POST /jobs/{id}/approve-plan`: Saves plan edits and triggers video generation (`execute_movie_job`).
  - `POST /jobs/{id}/replan`: Re-runs OpenAI outline generation for a fresh take.

---

## Update: Character Direction & Head Orientation Continuity System (2026-10-03)

Implemented the 4-Pillar Architectural Solution documented in `Fix character directions inconsistences.md` to permanently eliminate "jump-cut orientation snaps" and "puff switches" between consecutive clips in Story Videos mode:

1. **Pillar 1: Cinematic Camera Policy (`[SAME SETUP]` vs `[ANGLE CUT]`):**
   - In `_chapter_prompt()`, established strict camera continuity rules: Continuous scenes and multi-speaker exchanges default to locked camera setups (`[SAME SETUP]`) holding identical camera placement, focal length, lens aim, and 2D frame composition for up to 3 clips.
   - Any angle cut (`[ANGLE CUT]`) must be motivated by cinema grammar and strictly preserve the 180-degree rule so character screen directions and eye-lines match.
2. **Pillar 2: Head Pose & Screen Direction Schema & Memory:**
   - Extended `_chapter_schema()`'s `blocking` properties with:
     - `screen_profile`: 2D screen-relative profile at clip start (0.0s) (e.g. `three_quarter_facing_screen_right`, `profile_facing_screen_left`, `frontal_facing_camera`).
     - `head_tilt`: Head tilt angle at clip start (0.0s) (e.g. `tilted slightly left`, `upright neutral`, `chin raised`, `chin down`).
     - `eyeline`: Eye gaze direction at clip start (0.0s).
     - `end_screen_profile`, `end_head_tilt`, and `end_eyeline`: State at clip end (5.0s).
   - Enhanced `_state_so_far()` to report previous clip's ending camera setup, `end_screen_profile`, `end_head_tilt`, and `end_eyeline` to OpenAI.
   - Enforced the Golden Continuity Rule: The starting posture, `screen_profile`, `head_tilt`, and `eyeline` of Clip $N+1$ at 0.0s must be an exact 1:1 match to Clip $N$'s ending state.
3. **Pillar 3: Smooth Animated Motion (No 0.0s Snapping):**
   - Instructed OpenAI that head turns, shifts in gaze, or posture changes cannot occur at frame 0.0s.
   - All head turns or posture adjustments must be written as explicit timed action steps (e.g. `[1.5s to 3.0s] Elena smoothly rotates her head toward screen-left...`).
4. **Pillar 4: Seedance Temporal Continuity Anchor Directives:**
   - In `build_multi_prompt()`, dynamically compiles and injects a temporal continuity anchor into every Seedance prompt:
     `"CONTINUITY ANCHOR: At 0.0s cut, character body posture, head tilt, and screen direction strictly match the preceding shot: [{name}: {posture}, {screen_profile}, head {head_tilt}, eyeline {eyeline}]. STRICT RULE: No sudden snapping, jump-cut warping, or mirroring of face or body direction across the cut. Any change in gaze, head orientation, or posture must occur as a smooth, continuous physical movement during the action timeline."`
   - For Clip 1, injects a corresponding `STARTING POSE ANCHOR` to prevent initial frame hallucinations.
5. **Supervisor & Code Validation:**
   - In `_check_chapter()`, added strict posture, `screen_profile`, and `head_tilt` continuity verification between consecutive clips. Any unmotivated 180° flip or head tilt mismatch is caught as a hard problem, triggering OpenAI automatic retries before rendering.
   - Updated `_supervisor_prompt()` rules 2 and 8 to inspect blocking orientation continuity and camera setup holds across cuts.

---

## Update: Airborne Entity Mechanics & Vertical Pitch Continuity (2026-10-03)

Implemented airborne entity mechanics and vertical head pitch continuity in `movie_scene_multispeaker.py` to fix character elevation issues (e.g., fairies/spirits spawning on the floor instead of hovering in mid-air, causing human characters' heads to tilt downward toward the ground across cuts):

1. **Airborne Posture Support (`POSTURES` Enum):**
   - Added `"hovering"` and `"floating"` to `POSTURES` in `movie_scene_multispeaker.py`.
   - Propagated automatically to `_chapter_schema()`'s `posture` and `end_posture` enums.
2. **Vertical Head Pitch & Gaze Schema & Prompting:**
   - Updated `head_tilt` and `end_head_tilt` descriptions in `_chapter_schema()` to explicitly require vertical pitch: `'tilted upward (chin raised, looking up at mid-air)'`, `'level at eye height'`, `'tilted downward (chin down, looking down at floor)'`, or lateral roll `'tilted slightly left'`.
   - Updated `_chapter_prompt()` with strict directives for airborne entities:
     - Airborne characters (fairies, spirits, floating lights) must use posture `"hovering"` or `"floating"` (never `"standing"` or `"walking"`).
     - Must explicitly record 3D vertical elevation in mid-air in `position` and `end_position` (e.g. `'hovering mid-air 1.5m above the floorboards, suspended at eye level with Elena'`).
     - Entities must emerge directly from their mid-air light/cloud and NEVER spawn on or from the floorboards/ground.
     - On-ground characters interacting with airborne entities must gaze UP or level at mid-air elevation, never down at the floor.
   - Enforced vertical pitch continuity across cuts: if a character ended clip $N$ looking UP at a hovering entity, they must start clip $N+1$ at 0.0s looking UP with chin raised.
3. **Enhanced Pitch Conflict Detection (`_tilts_conflict`):**
   - Implemented regex word-boundary detection (`\bup\b`, `\bupward\b`, `\braised\b` vs `\bdown\b`, `\blowered\b` vs `\blevel\b`, `\bneutral\b`, `\bupright\b` vs `\bleft\b`, `\bright\b`).
   - Detects all conflicting vertical pitch combinations (`upward` vs `downward`, `upward` vs `level`, `downward` vs `level`) and lateral roll discrepancies (`left` vs `right`, `lateral` vs `level`) across consecutive clips.
   - Accurately distinguishes neutral upright poses from upward tilts without false substring collisions (`"up"` vs `"upright"`).
4. **Automated Airborne Blocking Checks (`_check_chapter`):**
   - Added validation detecting if any character described as airborne/hovering/floating in their position text is erroneously assigned posture `"standing"` or `"walking"`, triggering automatic OpenAI retry.
   - Added validation detecting if any airborne entity is mistakenly positioned on the floor or groundboards.
5. **Prompt Injection (`AIRBORNE DIRECTIVE` & Anchors):**
   - Updated `build_multi_prompt()` to include `f"{cname}: {post} in mid-air (airborne)"` in continuity anchors.
   - Injects explicit directive whenever airborne characters are present:
     `"AIRBORNE DIRECTIVE: [Names] is/are completely airborne in mid-air (hovering/floating), suspended above the floorboards with feet off the ground; do NOT ground their feet, stand them on the floor, or spawn them from the floorboards. Their elevation must remain strictly suspended in mid-air."`
6. **Docker Containers Synchronized:**
   - Successfully verified against comprehensive unit tests in Docker.
   - Restarted `aivideoextender-api-1` and `aivideoextender-worker-1`.

---

## Update: Dynamic Acting Mandate & Kinetic Physics (2026-10-03)

Implemented active physicality and kinetic physics directives in `movie_scene_multispeaker.py` to eliminate mannequin/frozen acting and static visual effects:

1. **Active Physicality & Dynamic Acting Mandate:**
   - In `_chapter_prompt()`, added `STRICT RULE: NO MANNEQUIN ACTING` explicitly forbidding passive, frozen verbs (`staring blankly`, `remains rigidly upright`, `holds breath without moving`, `stares without blinking`, `watches motionless`).
   - Mandated multi-phase dynamic bodily reactions for human characters (e.g. flinching, jolting, leaning in, clutching items, shielding eyes, gesturing, or trembling).
   - Enforced emotional and postural progression within every 5-second clip (e.g. initial startle/recoil -> followed by leaning forward in wonder or clutching chest).
2. **Kinetic Physics for Effects & Phenomena:**
   - In `_chapter_prompt()`, added `KINETIC PHYSICS FOR EFFECTS, LIGHTS & PHENOMENA`: magical lights, energy swirls, sparks, fire, and supernatural phenomena must never be described as static or merely spinning in place.
   - Mandated active spatial trajectory & velocity (arcs, zipping, dipping, soaring, vibration), dynamic light-casting & moving shadows across faces/walls, and environmental physical disturbances (billowing curtains, stirring hair).
3. **Seedance Motion Prompt Directive:**
   - In `build_multi_prompt()`, injected a global cinematic motion directive:
     `"Fluid cinematic physical motion throughout: render active character bodily reactions, natural momentum, and dynamic responsive lighting; characters must not freeze or remain static."`
4. **Verification & Synchronization:**
   - Syntax compiled cleanly and all unit tests passed in Docker.
   - Restarted `aivideoextender-api-1` and `aivideoextender-worker-1`.

---

## Update: "✨ Enhance Story" Duration-Adaptive Prompt Expansion (2026-10-03)

Implemented an intelligent LLM-powered prompt enhancer enabling users to turn brief one-liner premises into rich, cinematic screenplays calibrated specifically to their chosen duration (e.g. 15s/30s/60s):

1. **Backend Endpoint (`POST /enhance-prompt`):**
   - Added `EnhancePromptRequest` (`topic`, `duration`, `clip_duration`, `mode`) and `EnhancePromptResponse` (`original_topic`, `enhanced_topic`, `duration`, `num_clips`) models in `app.py`.
   - Structured prompt for OpenAI (`OPENAI_MODEL` / `gpt-5.6`):
     - **Duration-Calibrated Story Arc:**
       - Micro (15–30s): Focused single-scene confrontation with immediate hook, rising pressure, and a punchy turn/cliffhanger.
       - Medium (45–90s): Escalating multi-phase drama with clear inciting event, tactical pushback, climax, and aftermath.
       - Long (2m+): Multi-sequence story with distinct locations and character arcs.
     - **Cinematic Specificity:** Concrete sensory details, character motivations, physical setting, lighting, and explicit conflict.
     - Kept output as a clean synopsis ready to be planned by the Master Plan without token-wasting meta-chatter.
   - Fixed `gpt-5.6` compatibility: omitted `temperature` and `max_tokens` (unsupported on this model) to prevent HTTP 500 errors.
2. **Frontend UI Integration (`dashboard.html`):**
   - Converted the topic `<input>` into an expandable, auto-resizing `<textarea id="topic">`.
   - Added prominent **"✨ Enhance Story"** button with a status indicator (`✨ Expanding for [duration]s...`, `✅ Enhanced for [duration]s!`).
   - Dynamically fills the textarea with glowing blue visual feedback, allowing the user to review or edit the expanded story before submitting the job.
3. **Verification & Synchronization:**
   - Verified via automated HTTP tests on port 8001; validated 30s vs 60s outputs.
   - Docker containers synchronized and restarted.

---

## Update: Master Plan Adaptive Act Planner & Anti-Stagnation Engine (2026-10-03)

Implemented the duration-adaptive sequence scaling architecture and Universal Law of State Changes in `movie_scene_multispeaker.py` to prevent narrative stagnation, scene dragging, and repetitive dialogue:

1. **Duration-Adaptive Sequence Scaling (`_outline_prompt`):**
   - **Micro-Drama ($<= 6$ clips / 15–30s):** High-density single-scene progression with immediate *in medias res* hook $\to$ rapid friction/tactical counter-moves $\to$ decisive climax, turning point, or cliffhanger punchline. Eliminates generic setup or wandering.
   - **Medium Drama (7–18 clips / 35–90s):** Defined three-phase dramatic escalation:
     - Phase 1 (First 25%): Inciting disruption & immediate friction.
     - Phase 2 (Middle 50%): Deepening stakes, tactical maneuvers, secrets/leverage exposed, escalating obstacles.
     - Phase 3 (Final 25%): Breaking point, climax, and irreversible consequence/resolution.
   - **Cinematic Multi-Sequence Epics ($> 18$ clips / 2m–10m):** Modular sequence architecture dividing total clips into sequences of 6–10 clips each across varied locations (e.g. Discovery $\to$ Confrontation & Flight $\to$ Kinetic Pursuit $\to$ Cornered Standoff $\to$ Climax). Mandates location transitions and exterior establishing shots.
2. **The Universal Law of State Changes (Anti-Stagnation Mandate):**
   - Mandated that every single 5-second beat must produce an explicit, observable state change:
     - **Emotional Shift:** Character's psychological state visibly transforms (denial $\to$ rage; disbelief $\to$ dread; shock $\to$ defiance).
     - **Informational Turn:** A secret is spoken, a lie is exposed, an ultimatum is delivered, or leverage alters power dynamics.
     - **Physical / Spatial Turn:** Physical relationship shifts (closing distance, drawing weapons, slamming doors, entities materializing, flight/pursuit).
3. **Strict Anti-Dilution Rule (No Event Stretching):**
   - Forbade diluting a single physical or magical emergence across multiple beats (e.g., banned "Beat 1: light appears, Beat 2: light glows brighter, Beat 3: fairy steps out").
   - Mandated that any physical appearance, transformation, or entrance completes its emergence within ONE clip, allowing subsequent clips to immediately advance into dialogue and dramatic interaction.
4. **Conversational Momentum (No Echo Chambers):**
   - Forbade consecutive dialogue beats repeating identical opinions or circling around the same debate. Every turn must escalate: Proposition $\to$ Objection $\to$ Leverage $\to$ Counter-Tactic $\to$ Ultimatum $\to$ Decision.
5. **Outline Validation & Guardrails (`_check_outline` & `_check_continuation_outline`):**
   - Added validation detecting overly brief beat actions ($< 4$ words) and consecutive duplicate actions, triggering automatic OpenAI retries before rendering.
6. **Verification & Synchronization:**
   - Unit tests covering 6, 12, and 30 clip prompts and beat check validation passed cleanly.
   - Recompiled and restarted `aivideoextender-api-1` and `aivideoextender-worker-1`.

---

## Update: Prompt Enhancer Overhaul — Concrete Filmable Physics & Exact Dialogue (2026-10-04)

Overhauled the `POST /enhance-prompt` endpoint in `app.py` to eliminate novelistic fluff, abstract summaries, and flowery marketing prose, replacing it with concrete physical details calibrated for AI video generation:

1. **Strict Prohibition on Novelistic Fluff & Inner States:**
   - Banned unfilmable emotional summaries (e.g., *"she feels devastated"*, *"a heartbreaking truth"*, *"every relationship is doomed to slip away"*, *"leaving her alone with a reality she must escape"*).
   - Enforced that everything described must be physically visible to the camera or audible to the microphone.
2. **Concrete Filmable Reality & Staging:**
   - **Specific Setting & Starting State:** Mandated tangible room details and character activity at second 0 (e.g., fastening a silver necklace before a mirror, sitting at a wooden desk with tea).
   - **Kinetic Inciting Emergence:** Physical disruption with tangible physics (e.g., fairy bursts from jewelry box scattering perfume bottles, wings crackling with blue light).
   - **Exact Quoted Dialogue:** Requires 2 to 3 punchy spoken lines in quotation marks instead of summarized speech.
   - **Tangible Physical Proof:** Mandated concrete visual proof of the conflict on screen (e.g., date's photo blackens on phone, thorn mark burns red into skin, identical scar revealed).
3. **Mode-Tailored Directives:**
   - Dynamic prompt directives customized for `story_videos` (dramatic staging, blocking, props), `talking_head` (character persona, continuous spoken monologue, personal anecdotes), and `story_time` (changing visual scenes, visual actions, voiceover text).
4. **Verification:**
   - Validated via live HTTP API call (`POST /enhance-prompt`). The test fairy prompt generated rich, sequential, filmable beats with exact dialogue, tangible props, and physical proof.

---

## Update: Full Forensic Harmonization of OpenAI Instructions & Feature Scaling (2026-10-04)

Conducted a full audit across `movie_scene_multispeaker.py` and `app.py` to eliminate contradictory instructions and calibrate the engine for long-form (5m, 10m, and beyond) cinematic outputs:

1. **Pacing & Beat Harmonization:**
   - Replaced old legacy 3-clip arrival examples with active two-speaker arrival/revelation beats, aligning with the Anti-Dilution and Anti-Stagnation rules.
2. **Word Count & Mathematical Calibration:**
   - Adjusted `MIN_WORDS, MAX_WORDS = 6, 12` (previously 8, 16) to ensure spoken lines mathematically fit a 5-second window at 2.5 words/second while allowing natural gaps between speakers.
3. **Voice Banking & Ping-Pong Dialogue Calibration:**
   - Updated dialogue example timings to `0.2s to 2.3s` (2.1s span) and `2.6s to 4.8s` (2.2s span), guaranteeing that any character's first line meets the mandatory 2.0s voice-banking threshold.
4. **Unified Camera Hierarchy:**
   - Unified camera rules into a 3-phase progression: Locked Master Shot `[SAME SETUP]` for the first 1-2 clips to establish geography, followed by motivated `[ANGLE CUT]` (OTS, Close-Up, Profile) for dramatic turns, strictly adhering to the 180-degree rule.
5. **Feature-Length Structure Directive:**
   - Enhanced the multi-sequence structure directive for long-duration videos ($>18$ clips, 2m–10m+) to generate complete feature narrative arcs (Opening Sequence $\to$ Rising Stakes & Movement across progressive locations $\to$ Climax & Resolution) with mandatory exterior establishing shots for new locations.

---

## Update: Prompt & Syntax Harmonization for Findings 2, 3, 4, 5 (2026-10-04)

Applied targeted fixes to eliminate subtle contradictions and reference mismatches across modes:

1. **Finding 2 (Talking Head Gender Generalization):**
   - Replaced hardcoded `"She speaks directly to camera"` in `app.py` line 503 with `"The speaker speaks directly to camera"`, ensuring gender-neutral versatility for male, female, or non-binary speakers.
2. **Finding 3 (Seedance Reference Syntax Standardization):**
   - Standardized Talking Head continuation prompt from `<Video 1>` to `@Video1` in `app.py` line 507, matching Kie.ai Seedance's official reference tagging syntax used across Story Time and Story Videos.
3. **Finding 4 (Audio Foley Explicit Restriction):**
   - Restricted ambient sound directives in `movie_scene_multispeaker.py` to physical room tone, foley, and environmental sound cues only (e.g. footsteps, ticking clocks, rain, distant traffic, keys, floorboards). Explicitly banned musical instruments, score, melodies, humming, or synth drones to prevent triggering Kie.ai's automated audio copyright filter.
4. **Finding 5 (Continuation Generator Anti-Stagnation & Dialogue Density):**
   - Copied the High-Density Dialogue and No-Dead-Air directives into `_continuation_outline_prompt` in `movie_scene_multispeaker.py`, ensuring extended movie sequences maintain rapid dialogue pacing.
5. **Finding 1 Preserved:**
   - Per user instruction, left `[SAME SETUP]` and `[ANGLE CUT]` camera tracking tags untouched.

---

## Update: Universal Rich Act Structure Across All Durations (2026-10-04)

Overhauled `POST /enhance-prompt` in `app.py` to completely eliminate robotic pre-chopped `Clip 1:`, `Clip 2:` output and enforce rich dramatic Act structures regardless of duration:

1. **Duration-Calibrated Universal Act Hierarchy:**
   - **15s – 45s:** 2 High-Stakes Acts (Act 1: The Disruption $\to$ Act 2: The Confrontation & Climax).
   - **50s – 90s:** 3 Dynamic Acts (Act 1: The Inciting Disruption $\to$ Act 2: The Rising Conflict & Tangible Proof $\to$ Act 3: The Climax & Irreversible Turn).
   - **100s – 300s+:** 4 Full Feature Acts (Act 1: Inciting Disruption $\to$ Act 2: Escalation across locations $\to$ Act 3: Key Discovery/Confrontation $\to$ Act 4: Climax & Resolution).
2. **Strict Ban on Clip Lists:**
   - Strictly prohibited outputting `Clip 1:`, `Clip 2:` or shot boundaries in the screenwriter premise. Everything is formatted into immersive dramatic paragraphs under clear Act headings.
3. **High Dialogue & Content Richness:**
   - Enforced 2 to 4 exact quoted dialogue lines in every Act.
   - Enforced strict chronological progression (no repeated phone buzzes, arrivals, or actions).
4. **Live Verification:**
   - Verified via live HTTP call with the 60s fairy prompt. Generated a rich 3-Act cinematic screenplay premise (0–20s, 20–40s, 40–60s) with intense dialogue, physical manifestations, and zero clip-fragmentation.

---

## Update: Universal "No Re-Takeoff / No Re-Emergence" Rule (2026-10-04)

Added genre-agnostic continuity rules to prevent video models from re-rendering takeoff flashes, launches, or re-emergence eruptions across consecutive cuts:

1. **Genre-Agnostic Scripting Rule (`_chapter_prompt`):**
   - Applies to all drones, spirits, airborne creatures, floating lights, or aerial entities.
   - Once an entity completes its arrival, emergence, or ascent to its destination flight elevation in clip $N$ (e.g. hovering at eye level in mid-air): in all subsequent clips ($N+1$ onward), OpenAI is strictly forbidden from re-describing them launching, taking off, rising upward, emerging, or flying up from their origin point, container, or floor/ground again.
   - The entity must start the clip ALREADY suspended and cruising/hovering in mid-air at its established elevation.
   - Strictly forbidden from re-focusing the camera on the floor or origin container as a launchpad.
2. **Supervisor Continuity Verification (`_supervisor_prompt`):**
   - Script supervisor verifies that once an entity has completed its arrival/ascent in a previous clip, it does not re-takeoff or emerge again.
3. **Explicit Negative Constraint in Seedance Prompt (`build_multi_prompt`):**
   - Added explicit prompt directive: *"If already airborne in the scene, they are ALREADY hovering in mid-air at second 0.0; do NOT render another takeoff, eruption, or launch from the ground."*

---

## Update: Langfuse Observability & Tracing Integration (2026-10-04)

Integrated **Langfuse** (free cloud tier) across the FastAPI backend, Celery workers, movie scene generation pipeline, and frontend dashboard for full observability into prompts, token usage, validation retries, Kie.ai calls, and latency:

1. **Environment & Dependency:**
   - Added `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, and `LANGFUSE_HOST` to `.env` and `.env.example`.
   - Added `langfuse==4.16.0` to `requirements.txt` and baked into Docker image.
2. **Backend Tracing (`app.py`):**
   - Wrapped `OpenAI` client with `langfuse.openai.OpenAI` for automatic LLM call tracing, token tracking, and structured output capture.
   - Preserved 32-character lowercase hex trace IDs (`job.id`) for 1:1 mapping with OpenTelemetry trace specs.
   - Added `langfuse_url` to `Job` model, dynamically populated with direct link to project trace in Langfuse Cloud (`https://cloud.langfuse.com/project/{id}/traces/{job_id}`).
   - Decorated Celery tasks (`_run_generation_job_traced`, `_execute_movie_job_traced`, `_extend_movie_plan_task_traced`, `_regenerate`) and pipeline steps (`generate_clip`, `_assemble`, `assemble_task`, `enhance_prompt_endpoint`) with `@observe`.
   - Added automatic `get_client().flush()` on Celery task completion to ensure background worker events are immediately dispatched.
3. **Movie Scene Observability (`movie_scene_multispeaker.py`):**
   - Added `@observe` decorators to `generate_flux_image`, `supervise_chapter`, `write_outline`, `write_continuation_outline`, and `write_chapter`.
   - Instrumented `_ask_checked` to log validation retries and rule violation details as Langfuse events (`{what}_validation_retry`).
   - Instrumented `supervise_chapter` to record continuity critique problems as Langfuse events (`supervisor_detected_issues`).
   - Wrapped CLI `main()` entrypoint with a `try/finally` block that flushes events before process exit.
4. **Dashboard Link (`dashboard.html`):**
   - Added a prominent `🔍 Langfuse Trace` button in the job header (`.job-head`) next to the job status badge.
   - Automatically displays and links directly to the job's live Langfuse Cloud trace when a job is active or reviewed.
5. **Verification:**
   - Docker containers rebuilt (`docker-compose up -d --build`); verified `Auth check: True` against project `cmutnqefz145pad0ciyejp4q3`.
   - Tested live `POST /enhance-prompt` and verified generation/span observations ingested into Langfuse Cloud API.
   - Verified test job serialization and trace URL creation.

---

## Hybrid Narrated Drama — Audio & Visual Consistency Safeguards (2026-10-04)

### Context & Diagnosis
- Initial 15-clip (75s) run (`job: 535f163bf60746feabd9698d19ba6b19`) revealed two core categories of problems:
  1. **Audio Issues:** Missing syllables ("remembered" -> "membered"), stuttering ("hesitated" -> "hesitated-ed"), and speech clipping caused by unwindowed voice banking and lack of explicit timeline timestamps.
  2. **Visual Inconsistencies:** Characters teleporting to unlisted rooms (`same_office_corridor`, `loc_city_archive_hallway`), uncredited characters hallucinated into dialogue ("Whitlock"), and remote telephone callers rendered physically inside the protagonist's room.

### Audio Safeguards Implemented
1. **Explicit Timeline Timestamping `[start_est to end_est]`:**
   - Seedance prompt directives for both Voiceover and Live Dialogue now include explicit start/end markers (e.g. `[0.5s to 4.5s]`) ensuring speech begins after video establishing frames and completes prior to clip boundaries.
2. **Intelligent RMS-Energy Waveform Voice Banking:**
   - Replaced fixed naive `ffmpeg` cuts with NumPy RMS-energy waveform voice trimming via `movie.trim_windowed_voice()`, eliminating noisy room hiss and silence that corrupted Seedance speaker embeddings.
3. **Acoustic Redundancy Stripping & Music Suppression:**
   - Stripped vocal timbre adjectives from Seedance text prompts when reference audio `@Audio1` is present via `movie._delivery_only()`.
   - Appended `No background music.` directive to prevent Seedance from generating loud music beds that mask or distort voices.

### Visual Safeguards Implemented
1. **Dynamic Schema Enum Locking (`_narrated_chapter_schema`):**
   - Locked `location_id`, `character`, `present_characters`, `speaker`, and `posture` (`POSTURES`) to strict JSON schema `enum` arrays dynamically generated from `scene_bible["locations"]` and `scene_bible["characters"]`.
   - Guaranteed that OpenAI physically cannot output unlisted locations or hallucinated characters.
2. **Context & Scene Bible Injection (`_narrated_chapter_prompt`):**
   - Injected full Story Premise (`topic`), Scene Bible locations with spatial layouts, character descriptions, and full Master Plan beat roadmaps.
   - Injected rich recent clip history bridge (last 3 clips) containing previous dialogue lines, speaker names, physical action steps, and character postures/orientations across cuts.
   - Enforced `MANDATORY LOCATION: Clip N MUST be set in location '{beat['location_id']}'`.
3. **Remote Phone Call & Telephone Receiver Directive:**
   - Added explicit rule: when a remote caller speaks over telephone, intercom, or communicator, they MUST be set to `in_frame: "off screen"`.
   - Updated `build_narrated_prompt` to direct Seedance that the remote voice emerges from the telephone receiver/off-screen while visible characters listen attentively with lips closed.
4. **Strict Programmatic Continuity Validation (`_check_narrated_chapter`):**
   - Validates `clip["location_id"] == beat["location_id"]` (rejects teleportation).
   - Validates that all characters in `present_characters`, `blocking`, `action_steps`, and `speaker` exist in `scene_bible["characters"]`.
   - Validates posture and screen profile continuity at `0.0s` cuts for same-location transitions.
   - Enforces `in_frame: "off screen"` for remote phone callers.
   - Keeps word count (6-12 words) checks as soft warnings (`[SOFT]`) without triggering OpenAI retries.
5. **Gender & Name Neutrality:**
   - Completely agnostic: zero hardcoded character names or gendered pronouns in code directives or prompt templates. All variables dynamically populated from `bible["pov_protagonist"]`, `bible["characters"]`, and `bible["locations"]`.
6. **Clip Normalization (`_normalize_narrated_clip`):**
   - Derives on-screen characters from blocking where `in_frame in ON_SCREEN` and standardizes character name casing across `hybrid_narrated_drama.py` and `app.py`.
















---

## Hybrid Narrated Drama — Character Identity & Reveal Order (2026-10-05)

### Diagnosis (job `488d9d903db841dc8e86d67567794769`, 15 clips x 5 s)

Verified against the saved request JSONs (`/srv/media/hybrid_narrated_drama/requests/clip_NN.json`), the master plan, the job's Redis state, the FLUX reference images and frames pulled from the rendered clips. The **story logic was sound** — Clara was the protagonist in every beat, the location lock held, and the off-screen rule for the phone caller worked. Two things failed:

1. **Character identity collapsed.**
   - `look` and `image_prompt` were two independent free-text fields. Clara's `look` said *"tidy dark-blonde bob"*; her `image_prompt` named no hair at all, and FLUX drew a **brown ponytail**. Every Seedance prompt therefore shipped `Clara Vance is @Image4 (…tidy dark-blonde bob…)` — a picture and a caption describing different people. The model picked a different winner per clip: blonde bob (c2), dark bob (c3, c8), mid-tone (c6), brown ponytail (c10), blonde pulled back (c13).
   - Clara's and Mia's `image_prompt`s were near-identical ("female hotel receptionist in navy uniform behind a dim luxury front desk"), so the two references were interchangeable. Once Clara's hair went dark the audience could not tell them apart.
   - Clara's `look` ended with *"anxious but determined posture"* — a mood shipped as a permanent physical trait. `movie_scene_multispeaker.py` forbids this (STATIC BIBLE RULE); hybrid had no equivalent.
   - Cast images were atmospheric in-scene shots with half the face in shadow — weak identity anchors carrying their own lighting into every clip.
   - **Clip 10:** beat 10 named `speaker_or_actor: Mia Torres` (shock_action validated nothing but `speech_budget == 0`), and the clip writer then dropped Mia from the clip entirely and reassigned her action to Clara. Nothing checked either. The result read as Mia becoming the lead.

2. **The story leaked ahead of itself.** Beat 2's planned V.O. was *"After my wrongful firing, one mistake meant homelessness."* The clip writer replaced it with *"I needed this job, even if 404 owned midnight."* — naming Room 404 one clip before Mia reveals it. Cause: the **entire 15-beat roadmap** was injected into every clip's prompt, and nothing compared the clip's `audio_text` to the beat it came from.

### Identity fixes

1. **One structured `appearance` per character** (`casting`, `hair_color`, `hair_style`, `build`, `distinguishing_feature`, `wardrobe`) replaces the two free-text fields. `_compile_character_visuals()` writes both `look` and `image_prompt` from it, so the picture and the caption cannot describe different people. `voice` was also added — `build_narrated_prompt` already read it, but the schema never produced it.
2. **The picture is the description.** When a character has a reference image, the prompt now says `Clara Vance is @Image2` and nothing more; the written look is sent only when there is no image. Same principle as `movie._delivery_only()` for voices. A fidelity line was added: *"Each named character's face, hair colour, hairstyle and clothing match their reference image exactly."*
3. **Cast portraits are clean references** — front-facing head-and-shoulders, even studio light, plain mid-grey background, no scenery, plus photoreal keywords (the REALISM RULE hybrid had dropped). The same discipline the locations already get.
4. **Visual separation is validated.** Hair is compared by coarse family (`_HAIR_COLORS`, `_HAIR_STYLES`): two characters sharing a colour *and* a style is always rejected; in a cast of five or fewer, sharing a colour alone is rejected. Every character needs a real `distinguishing_feature`.
5. **Moods are rejected from appearance** (`_MOOD_IN_LOOK`) — the STATIC BIBLE RULE, now enforced in code rather than only asked for.
6. **The beat's cast is the clip's cast.** `_check_narrated_chapter` rejects any character the beat lists who is missing from the clip's blocking (off screen is allowed; dropped is not), and any beat actor who does not appear. `shock_action` beats must belong to the POV protagonist — first person means the shockwave is theirs.

### Reveal-order fixes

7. **The Master Plan writes the lines.** New `audio_line` on every beat: the exact words heard in that clip, decided once by the only writer that sees the whole story. The clip writer is given it verbatim and may not reword it; `_check_narrated_chapter` rejects any change, and if retries run out `write_narrated_chapter` overwrites the line so a reworded or leaking one can never reach kie.ai.
8. **No future knowledge.** The roadmap handed to the clip writer now stops at the current beat — "the story SO FAR" — plus an explicit rule that nothing later exists yet.
9. **A reveal ledger.** New `reveals` on every beat lists the terms that beat discloses first. `_terms_still_secret()` builds what is not yet known at clip N, and both validators reject a line that speaks one. This catches the exact failure: *404* is revealed in beat 3, so a beat-2 line naming it is refused.

### Verification (offline, no credits)

`verify_narrated_fixes.py` replays the real failures from job `488d9d90…` against the new validators — **84 checks, all passing**: the mood word, the empty feature, the matching hair (both the colour+style and the colour-only rule), the 404 leak, the Mia shock beat, a clean plan passing, `look`/`image_prompt` agreeing, the clip-2 prompt containing no beat-3 or beat-4 content, the mandatory line quoted, a reworded line rejected, a dropped character rejected, and the Seedance prompt no longer captioning a face it is already showing. A separate check confirms both JSON schemas still satisfy OpenAI strict mode (every property in `required`, `additionalProperties: false`).

### Wordless beats: earned, not forced (same day, after review)

The first pass made every `shock_action` beat require the protagonist on screen. That was too strict in one
direction and the quota behind it was wrong in the other:

- **Establishing shots are now allowed.** A wordless beat with `present_characters` empty and no actor is an
  establishing or atmospheric shot - the building from the street, a lift door opening, rain on a window -
  exactly the "overview of a building" case you asked for. The clip writer is told to leave
  `blocking` and `action_steps` empty and put the whole description in `shot`; `build_narrated_prompt`
  already handled an empty cast ("Cinematic environmental shot").
- **The POV rule narrowed to what it was for.** When a wordless beat *does* have people in it, the
  protagonist must be among them and be the beat's actor. Everyone else present still reacts inside the clip
  - the rule only decides who the shot is *about*, which is what clip 10 got wrong.
- **The cycle is no longer a quota.** Phase 3 is now "0 or 1 clip", with an explicit instruction never to
  invent a jolt to fill the slot and to skip it when the story provides none. The forced slot is what
  manufactured clip 10's wrist-grab in the first place: the premise supplied two jolts (the bell, the door)
  and three cycles needed three. A plan with no wordless beat at all now validates cleanly.
- A run of more than 3 dialogue clips is still broken up, but the message now asks for a **voiceover** beat -
  the protagonist's inner reaction - rather than suggesting a shock beat first.

### A failed check no longer becomes a paid run (2026-10-05)

Both validators could be fully satisfied and still be ignored: `_generate_narrated_plan` assigned `problems`
and never read it, and `_continue_narrated_drama_job` discarded the clip's with `ch_data, _ =`. After the
retries were spent, a plan or clip that broke its own rules was rendered anyway. Adding rules made this
worse, not better, so the gate was closed:

- **`_hard_problems()` / `_soft_problems()`** split the lists in one place. Hard = anything not marked
  `[SOFT]`; soft = cosmetic (a line a word or two long, tight pacing) - logged, never fatal. The audio_line
  word-count check was downgraded to `[SOFT]`; everything about identity, cast, location and reveal order
  stays fatal.
- **Plan gate:** hard problems after retries raise before anything is paid for. FLUX images and clips both
  come after plan approval, so nothing has been spent. The rejected plan is written to
  `master_plan_rejected.json` in the job folder for inspection, and deliberately **not** stored on the job,
  so the dashboard's Resume cannot pick a broken plan back up.
- **Clip gate:** hard problems on a clip's script raise *before* `render_narrated_clip`, so the bad clip
  costs nothing. Earlier clips keep their videos and the job resumes from where it stopped.
- Both raise into the existing `try/except` that calls `_fail_job`, so the dashboard shows the rule that
  could not be satisfied. The CLI stops the same way with the same message.
- `write_narrated_outline` now retries on hard problems only, and both writers return the full problem list
  with `[SOFT]` markers intact so callers can judge for themselves.

### Blocking continuity, and two smaller gaps (2026-10-05)

- **Blocking now has an end state**, ported from movie mode (`end_position`, `end_posture`,
  `end_screen_profile`, `end_eyeline`). Hybrid had only one snapshot per clip, so `_check_narrated_chapter`
  compared clip N's opening pose against clip N-1's *opening* pose and forced every clip in a location to
  start identically - which is why clips 2 to 9 of job `488d9d90…` all carried the same CONTINUITY ANCHOR
  and the scene looked frozen. It now compares clip N's start against clip N-1's **end**, as
  `movie_scene_multispeaker.py:833` does, so a character who sits down during a clip is sitting when the
  next one opens.
- **The anchor sent to Seedance is an arc**: "starts standing, screen front, ends kneeling, screen left" when
  a character moves, and "standing, screen front, held throughout" when they do not - instead of a single
  frozen pose in both cases.
- **Wordless beats name their own audio.** Seedance invents this track, so the directive now lists what may
  be invented (room tone, footsteps, a door, rain, a caught breath) and bans voices, humming and "any musical
  score, sting, drone or soundtrack", rather than relying on the generic "No background music." line.
- **Request logs are per job.** `render_narrated_clip` takes `out_dir`; `app.py` passes the job folder.
  Previously every job wrote to one shared path and concurrent jobs overwrote each other's record of what was
  sent. The record now also stores the reference image and audio URLs, which had to be reconstructed by hand
  when diagnosing this run.

### Up to three speakers in one clip (2026-10-05)

The last structural gap against `movie_scene_multispeaker.py`. Hybrid allowed exactly one speaker and one
line per 5-second clip, so a confrontation could only ever be one line per cut and `MAX_VOICE_REFS = 3` was
dead code. Movie mode's turn list was ported:

- **Beats plan the whole exchange.** `audio_line` (one string) became `audio_lines`, a list of
  `{speaker, line}`. A dialogue beat holds one to three lines, a voiceover beat exactly one, a shock beat
  none. `speech_budget` is the TOTAL words across the turns, still 6-12, so three speakers means about four
  words each - which is the format: "Where is she?" / "Gone." / "You are both lying."
- **Clips carry `speech`**, a list of turns with their own `speaker`, `line`, `delivery`, `start_est` and
  `end_est`, replacing the flat `audio_text`/`speaker`/`delivery`/`start_est`/`end_est` fields.
- **The prompt builder emits one directive per turn**, each with its own window and its own `@AudioN`, up to
  the three kie.ai accepts. A speaker heard twice in a clip reuses their single reference rather than
  burning a second slot. On-screen speakers get lip sync, off-screen ones come "from the telephone
  receiver". Multi-turn clips also get: the lines run back to back in one take, never at the same time,
  only the current speaker's lips move, and hold everyone who speaks in frame together.
- **Voice banking is per turn.** `bank_voice` takes `turn_index` and the full turn list, so
  `movie.trim_windowed_voice`'s energy search stays inside that speaker's own window instead of wandering
  into the line before or after it. `app.py` and the CLI both bank every new speaker in a clip.
- **Validation covers it**: turn count per mode, at most 3 distinct speakers, speakers in the bible, total
  word budget (soft), and windows that are ordered, non-overlapping and inside the clip. Clip turns must
  match the plan's turns one for one - same count, same order, same speaker, same words.
- `_beat_lines()` / `_clip_turns()` read the older single-line shape too, so a job planned before this can
  still be resumed, and the dashboard's `clipTurns`/`clipSpeech` helpers render either shape.

Two robustness fixes found while testing: `build_narrated_prompt` raised `KeyError: 'look'` for a character
whose visuals had never been compiled (an older bible, or a cast member added by a continuation) - it now
derives the look on the spot - and `_generate_flux_images` compiles the bible's visuals before use.

### The physical world: location plates and the prop diary (2026-10-05)

The last area where hybrid was behind movie mode. The evidence was in job `488d9d90…`'s own plan: the
Room 404 location reference prompt read *"...heavy dark wood door cracked open, **handsome dangerous man in
threshold**, laundry cart outside, **dark crimson stained sheets and silver case barely visible**"*. A
character was painted into the place plate used for every clip filmed there, and the story's final reveal
(beat 15) sat in the reference from clip 11 onward. Movie mode forbids exactly this
(`movie_scene_multispeaker.py:383`: "NO PEOPLE, and none of the story's props"); hybrid had no such rule.

**Locations**
- Ported movie mode's LOCATIONS / LAYOUT / VIEWS / REALISM rules into the showrunner prompt, including that
  a viewpoint is *a place to stand in the empty room*, never a shot from the story (the run's views were
  "Clara POV through cracked door" and "insert of crimson sheets and silver case").
- `_compile_location_visuals()` appends the empty-room and photorealism wording to every plate in code, so
  it cannot be forgotten; it is idempotent, so recompiling a bible does not stack the text.
- Validated: a plate may not describe a person (`_PERSON_IN_PLATE`) or name a cast member, viewpoints may
  not either, and there must be 2 or 3 of them.

**Props**
- `props` added to the scene bible (snake_case `id` + fixed `description`), and `prop_state` to every clip:
  the diary movie mode keeps - one entry per prop from its first appearance onward, with `holder`,
  `in_frame` and `state`, carried in the clip prompt's history so state continues across cuts.
- The Seedance prompt now names the props the camera can see, with the bible's fixed description, and
  `_plain()` expands snake_case ids that leak into action text.
- Validated: props exist in the bible, holders are a real character or `scene`, and a prop that appeared in
  the previous clip's diary cannot be dropped from this one.

**A voice-sample guard, needed because of the multi-speaker change**
Three speakers sharing 6-12 words means a turn can be two words long, and hybrid banks a character's voice
from their first line and reuses it for the whole video - so "Gone." would have become that character's
voice forever. `should_bank_voice()` now banks a short line only when the plan has nothing longer coming
for that speaker, and the showrunner prompt asks for a character's first line to carry at least
`VOICE_SAMPLE_MIN_WORDS` words. Movie mode has the same rule as prompt text only.

### Awareness and environment (2026-10-05)

Two of movie mode's four remaining fields were taken; two were deliberately left.

**Taken — `awareness`** (per character, in blocking): what they have noticed so far and what they have not.
It carries forward in the clip history and reaches Seedance as "What each one has noticed: ... Nobody reacts
to anything they have not noticed." Two reasons it earns its place here rather than being parity-chasing:
the reveal ledger guards what the *audience* knows, not what a *character* knows; and the multi-speaker port
made it newly relevant, because characters move through visible/partly visible/off screen/has left and up to
three speak per clip, so "answers a question asked while they had left" is now possible.
It also brought one mechanical POV check: a `voiceover` clip whose blocking has people in it must include the
protagonist. The voiceover is their first-person thought, so narrating a scene they are not in makes their
inner voice an all-seeing narrator. A clip with nobody on screen is exempt - narration over an establishing
shot is normal.

**Taken — `environment`** (per clip): one sentence of what the PLACE does, with no people in it. This filled
a real hole rather than copying movie mode's `others`: `action_steps` requires a `character` from the cast
enum, so non-human motion - the bell ringing by itself, a lift door opening, the storm at the windows - had
nowhere to live and was being smuggled into the `shot` string. For a wordless establishing beat it now
carries the whole motion of the clip. Validated to name no character and describe no person, so it cannot
become a backdoor for the uncredited extras the cast rules exist to prevent. (Movie mode's `others` includes
background people; that framing was not taken.)

**Left — `head_tilt`**: it exists in movie mode for the 2026-10-03 airborne-entity work (chin raised at
something hovering, vertical pitch continuity). This is grounded human drama in rooms, `eyeline` already
carries where someone looks, and every required field costs a retry risk per clip.

**Left — `facing`**: room-relative orientation, largely covered by `screen_profile` (camera-relative),
`eyeline` and `position`, now that blocking also carries the `end_*` arc.

**Not yet run:** a live job. Nothing here has been confirmed on rendered video — the next 15-clip run is the real test, and it is yours to start.

### Hardening & Production Fixes for 5-Minute Run (Steps 1–5, 2026-10-06)

Following `HYBRID_PRE_RUN_FIXES.md`, hardened the Narrated Drama pipeline offline before the 60-clip production run:
- **Step 1 (Kie.ai Retry & Voice Banking Ladder):** Automatic retry on audio copyright filter rejection with `AUDIO_RETRY_NOTE`; polling `TimeoutError` (15 min) halts immediately to prevent double billing; transient failures retry up to `CLIP_RETRIES = 2` (3 total attempts) with backoff; speaker voice filenames space-sanitized into per-job `voices/` folders.
- **Step 2 (Pose Continuity Soft/Hard Split):** `posture` equality check remains hard; tightened `_profiles_conflict` to eliminate false positives on phrasing variations ("three-quarter left" vs "left three-quarter"); downgraded screen profile mismatches to `[SOFT]` warnings.
- **Step 3 (Retry Ladder: Repair First, Retry Second, Fail Last):** Added deterministic `_repair_narrated_clip` that re-spaces speech windows evenly, carries forward unmentioned props with `in_frame: False`, force-replaces drifted lines with Master Plan words after 1 retry, and adds missing beat characters as `in_frame: "off screen"` on the final attempt. Raised `CHAPTER_RETRIES = 3`.
- **Step 4 (Camera Directives, 180-Degree Rule & Audio Lead-In Trimming, §8):**
  - Added `frame_position` to blocking schema constrained to `FRAME_POSITIONS` enum (`frame left`, `left of centre`, `centre frame`, `right of centre`, `frame right`, `foreground`, `background`, `off screen`).
  - Added mechanical 180-degree rule continuity check (`_frame_positions_flip`) flagging screen direction flips across consecutive clips in the same scene as `[SOFT]` notes.
  - Expanded Rule 5 in `_narrated_chapter_prompt` into the full Cinematic Camera Policy (Establishing Phase locked master shots, Coverage Phase motivated angle cuts, 180-degree rule, one main moment per clip, 5 shot elements with lighting delegated exclusively to `environment`, story-critical movement on camera, exits leaving others alone, and good/bad examples).
  - Added fluid cinematic physical motion directive in `build_narrated_prompt` ensuring active character bodily reactions, natural momentum, and responsive dynamic lighting to prevent frozen mannequin posture during multi-second dialogue.
  - Added camera continuity tag check (`[SAME SETUP]` / `[ANGLE CUT]`) as a `[SOFT]` note in `_check_narrated_chapter` and auto-prefix repair in `_repair_narrated_clip`.
  - Included `frame_position` in the Seedance prompt `Frame positions: [...]` block.
  - Enabled audio lead-in trimming in `assemble_narrated_video()` and `app.py:868` (`job.mode in ("talking_head", "narrated_drama") and i > 0`), stripping dead air hesitation on speech cuts.
- **Step 5 (Long Videos Planned in Acts & Location Scaling, §§5 & 9):**
  - **Act-based Planning for 30+ Clips:** Kept single-shot outline generation for `< 30` clips. For `>= 30` clips, decomposed planning into Call 1 (Scene Bible + Act Roadmap via `ACT_BREAKDOWN_SCHEMA`) followed by Calls 2..N (`ACT_BEATS_SCHEMA`) generating beats act-by-act.
  - **Act Count Detection & Normalization:** `_detect_premise_act_count(topic)` detects explicit user act counts (e.g., "7 acts", "four-act drama") with a 4-act default for 60 clips (~15 clips per act). `_normalize_act_spans` guarantees contiguous `1..total_clips` coverage without gaps.
  - **Decoupled Batching Guard:** `_plan_act_batches` splits acts `> 20` clips into sub-batches and merges short acts `< 6` clips.
  - **Strict Information Barrier & Cross-Act Reveal Ledger:** Beat prompts see the Scene Bible, full Act Roadmap, prior filmed beats, and revealed terms, but crucially **never see future beats**. End-to-end secret ledger validation runs over the completed sequence, rejecting cross-act leaks as hard errors.
  - **Location Scaling (§9):** Showrunner prompts demand confinement within an act and progression between acts (aiming for 4–8 locations across 60 clips). Added `[SOFT]` warnings in both `_check_narrated_outline` and `_check_act_breakdown` if `< 3` distinct locations are used or if a single location dominates `> 70%` of clips.
  - **Continuation Planning:** Implemented `write_narrated_continuation_outline` and unlocked `extend_movie_plan_task` in `app.py` for `narrated_drama` jobs.
- **Step 6 (Dashboard Display of New Fields, §6):**
  - Added responsive styling for props state tables (`.prop-table`, `.prop-tag-in`, `.prop-tag-out`) and reusable `renderPropTableHtml(propState)`.
  - **Master Plan Review (`renderPlanReview`):** Displays complete character appearances (`appearance` or `look`), `POV Lead` tags, full story props catalog with descriptions, and beat-level audio lines and secret reveal tags.
  - **Timeline Clip Detail Panel (`renderDetail`):** Displays ambient `Environment`, blocking with `start → end` pose arcs and frame position, `🧠 Knows: ...` character awareness, and formatted props table.
  - **Prompt Inspection Card (`getScenePromptData`):** Dedicated breakdown cards for `Environment (Ambient Atmosphere)`, `Characters & Blocking (Start → End Arc & Awareness)`, and `Props in This Clip`.
  - **Edit Modal (`populateModalFields`, `updateCompiledPreview`, `getModalOverrides`):** Added editable `modal-environment`, live compiled prompt preview reflecting environment atmosphere, and full override persistence for `narrated_drama` mode. Wired `Resume Generation` button for paused jobs.
  - 178 offline unit tests in `verify_narrated_fixes.py` all passing with 0 failures. Containers restarted.
- **Step 7 (Residual Risks Hardened, §7):**
  - **Pre-Run Cost & Duration Estimates (§7.4):** Added dynamic live cost estimation badge on the dashboard generation form computing credit cost and wall time based on selected mode, clip duration, and clip count (e.g., displaying `~1,140 credits • ~3.5 hrs` for 60 clips).
  - **Execution Confirmation Dialogs:** Added prompt in `#approve-plan` detailing total clip count, estimated Kie credits, runtime in hours, and a warning to keep the machine awake before initiating paid generation. Added direct-mode confirmation for long runs.
  - **Banked Voice Isolation & Space Sanitization (§§7.1 & 7.6):** Updated `trim_windowed_voice` in both `movie_scene_multispeaker.py` and `app.py` to write to per-job `voices/` directories and sanitize spaces (`replace(" ", "_")`), ensuring clean Kie.ai upload URLs without encoded spaces.
  - **Timeout Double-Billing Guard (§7.2):** Unified `TimeoutError` handling across all pipelines so that polling exceeding 15 minutes halts immediately with a clear resume message rather than consuming a second paid generation.
  - 184 offline unit tests in `verify_narrated_fixes.py` all passing with 0 failures. Containers restarted.
- **Step 8 (Script Supervisor for Hybrid Narrated Drama, §4):**
  - **Scoped Prompt & Context:** Implemented `_narrated_supervisor_prompt` and `supervise_narrated_chapter` covering 7 scoped continuity areas: (1) Beat fidelity, (2) Blocking and position continuity (including 180-degree rule and camera placement), (3) Knowledge & awareness, (4) First-person POV (narration strictly limited to protagonist's witnessed experience), (5) Props honesty & continuity, (6) Space & layout adherence, (7) Packing & pacing (5s dialogue and action limits). Scoped context sends only the current clip, up to 2 previous clips (`prev_clips[-2:]`), the scene bible, and the current beat.
  - **Mechanical Gating:** Supervisor runs strictly only after mechanical code checks pass (`if not hard and supervise`). Zero OpenAI supervisor calls are wasted on drafts failing mechanical checks.
  - **One Rewrite, Then Soft:** Supervisor notes trigger exactly one rewrite attempt with continuity critique injected into the prompt. If notes persist after the rewrite (or on subsequent attempts), they are downgraded to `[SOFT]`, logged as warnings, and the clip renders without stopping the paid run.
  - **Per-Job Switch & UI:** Added `supervise: bool = False` to `ClipRequest` in `app.py`, passed `supervise=is_supervise` in `_generate_narrated_clips()` and `_generate_movie_clips()`, and added a dashboard checkbox `Script Supervisor` (off by default).
  - 210 offline unit tests in `verify_narrated_fixes.py` passing with 0 failures. Containers restarted.

### Known, not changed


- `movie_scene_multispeaker.py` has the **same** `look`/`image_prompt` split ([:196](movie_scene_multispeaker.py:196)) and the same caption-beside-the-picture call ([:1138](movie_scene_multispeaker.py:1138)). The failure is latent there too; left alone for now so this mode can be judged on its own.

---

## Hybrid Narrated Drama — audit of steps 4-9, and three fixes (2026-10-06)

Reviewed the camera, location, act-planning, supervisor and dashboard work against
`HYBRID_PRE_RUN_FIXES.md`. The implementations match the agreed design and the offline suite passes. Three
loopholes were found and fixed; the suite is now **224 checks**.

**1. `frame_position` had no end state.** Every other blocking dimension gained an `end_*` counterpart, so
the 180-degree check was comparing clip N's opening frame side against clip N-1's *opening* side - the
start-vs-start bug already diagnosed and fixed for posture. It both flagged a character who legitimately
crossed the frame during a clip, and stayed silent on the genuine flip (walked to frame right in clip N,
opens clip N+1 at frame left). Added `end_frame_position` to the blocking schema with the same enum, the
check now reads `end_frame_position or frame_position`, and the continuity anchor sends the move
("crossing to frame right") while the existing `Frame positions:` line keeps carrying the opening state.

**2. The lead-in trim was cutting wordless beats.** `assemble_final_video` had been extended to
`job.mode in ("talking_head", "narrated_drama")`, which trims every clip after the first - including shock
beats and establishing shots. `_lead_in()` keys on sound that is loud AND tonal, and a brass bell, a lift
chime or a slammed door is both, so it would read the jolt as the first word and cut up to 1.5 s of the
build-up before it. New `_wants_lead_in_trim()` skips any Narrated Drama clip whose `speech` is empty, reads
the pre-turns `audio_text` shape for older jobs, and leaves Talking Head and Story Videos exactly as they
were.

**3. The act breakdown was being thrown away.** `_write_act_based_outline` returns
`{scene_bible, acts, beats}`, but `_generate_narrated_plan` stored only the bible and beats, `Job` had no
`acts` field, and `_save_master_plan_file` rebuilds from the job - so `master_plan.json` carried no acts and
the dashboard had none to show. Since the review gate before a paid run is reading the plan, and act spans
are the first thing to check, this removed the point of planning in acts. `Job.acts` added, stored on
approval, and included in both the saved plan file and the `/jobs/{id}/plan` fallback.

**Still open from the audit:** a cross-act reveal leak has no retry path. `_check_act_beats` sees only prior
beats, so only the final whole-plan `_check_narrated_outline` can catch an early beat naming a later reveal -
and that result is returned without a retry, so one leak discards every planning call and fails the job. The
act-beats prompt deliberately passes `all_acts`, which is what makes the leak possible. Worth either
repairing the offending line or retrying just the batch that owns it.

---

## Hybrid Narrated Drama — cross-act reveal leaks (2026-10-06)

The last item from the audit. Long plans are written act by act, and `_check_act_beats` sees only the beats
already written, so a line in Act 1 naming something Act 3 discloses was invisible to it. Only the final
whole-plan `_check_narrated_outline` could catch it - and that ran with no retry, so a single leak discarded
every planning call and failed the job. Fixed in two layers.

**Prevention: the acts declare what they disclose.** `ACT_BREAKDOWN_SCHEMA` gained `reveals` per act - the
terms that act is the first to disclose - and the breakdown prompt now explains that each term belongs to
exactly one act, because the later beat-writing passes cannot see the acts after them and these lists are how
they know what they may not say. `_terms_reserved_for_later_acts()` turns that into the set a given batch
must keep back, which is used twice: `_narrated_act_beats_prompt` prints it as a RESERVED FOR LATER ACTS
block naming the exact terms, and `_check_act_beats` rejects any line that speaks one. The leak is now caught
inside the batch loop, where a retry costs one call and nothing else is thrown away.

**Backstop: one leak no longer costs the plan.** `_leaking_beats()` reports every beat whose line speaks a
term the story reveals later, judged against the finished beat list rather than the declared acts - which is
the part only visible once every act exists. When it finds one, `_write_act_based_outline` rewrites just the
batch that owns the offending beat, quoting the leak and instructing it to keep the same beats, locations and
rhythm, then re-assembles and runs the whole-plan check. One call instead of the entire plan.

A deliberate limit worth knowing: only the owning batch is rewritten, not the batches generated after it,
which were conditioned on its earlier text. A leak fix is normally a small change to one line, and the
whole-plan check still runs afterwards, so the trade is one cheap call against regenerating the tail of the
plan.

Suite: **237 checks**, all passing; both JSON schemas still satisfy OpenAI strict mode.
