# =============================================================================
# AI Video Extender — single-file backend
#
# Everything lives in this one file, organized top-to-bottom by section.
# Two processes import it:
#   API:     uvicorn app:app --host 0.0.0.0 --port 8000
#   Worker:  celery -A app.celery_app worker --loglevel=info
# =============================================================================


# --- Imports ---
import hashlib
import json
import os
import subprocess
import tempfile
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Literal, get_args

import httpx
import numpy as np
import redis
from celery import Celery
from celery.utils.log import get_task_logger
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
try:
    from langfuse.openai import OpenAI
    from langfuse import observe, get_client
except ImportError:
    from openai import OpenAI
    def observe(*args, **kwargs):
        def decorator(f):
            return f
        return decorator
    def get_client():
        return None
from pydantic import BaseModel, ConfigDict, Field, model_validator


# --- Config ---
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
KIE_API_KEY = os.getenv("KIE_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5.6")
# The pipeline asks OpenAI for two very different things, and they do not want the same model. The
# SHOWRUNNER invents the story and writes every spoken line in the film - creative writing, which is the
# cheap tiers' known weakness. The CLIP WRITER invents nothing: the lines are already written and must be
# copied verbatim, so its job is filling a strict JSON schema with camera placement, blocking and prop
# bookkeeping - structured work, which the cheap tiers are good at. On the first 5-minute run the clip
# writer was 43 of 49 calls and $6.48 of the $7.56. Unset, it follows OPENAI_MODEL and nothing changes.
OPENAI_CLIP_MODEL = os.getenv("OPENAI_CLIP_MODEL", "") or OPENAI_MODEL
LANGFUSE_PUBLIC_KEY = os.getenv("LANGFUSE_PUBLIC_KEY", "")
LANGFUSE_SECRET_KEY = os.getenv("LANGFUSE_SECRET_KEY", "")
LANGFUSE_HOST = os.getenv("LANGFUSE_HOST", os.getenv("LANGFUSE_BASE_URL", "https://cloud.langfuse.com"))
KIE_API_BASE = "https://api.kie.ai"
KIE_UPLOAD_BASE = "https://kieai.redpandaai.co"  # kie.ai's file host; uploads are deleted after 24 hours
KIE_MODEL = "bytedance/seedance-2-mini"
KIE_POLL_TIMEOUT = 15 * 60  # seconds to wait for one clip before giving up
ANCHOR_MAX_AGE = 23 * 60 * 60  # seconds; kie.ai deletes uploads after 24 hours, so older anchors are made again
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
# Downloaded clips and each job's final video (a Docker volume shared by the api and the worker). kie.ai deletes
# generated videos after 14 days, so the clips are kept here.
MEDIA_DIR = Path(os.getenv("MEDIA_DIR", "/srv/media"))

CLIP_DURATION = 10  # seconds; production clip length. A job may also use 5-second clips (testing only), see ClipDuration
# Talking Head: clip 0 is always rendered at this resolution, whatever the job's, because it is the master every later
# clip is generated from. Seedance's 720p is 720x1280 (9:16), inside kie.ai's 927,408-pixel limit for a reference video.
MASTER_RESOLUTION = "720p"


def get_langfuse_trace_url(trace_id: str) -> str | None:
    """Return the direct URL to inspect this trace in the Langfuse UI if credentials are set."""
    if not LANGFUSE_PUBLIC_KEY or not LANGFUSE_SECRET_KEY:
        return None
    try:
        return get_client().get_trace_url(trace_id=trace_id)
    except Exception:
        return None


# --- Celery App ---
celery_app = Celery("app", broker=REDIS_URL)
celery_app.conf.broker_connection_retry_on_startup = True


# --- Models ---
Resolution = Literal["480p", "720p"]
Mode = Literal["talking_head", "story_time", "story_videos", "narrated_drama"]
ClipDuration = Literal[5, 10]  # production is always 10; 5 exists only to save credits while testing
Status = Literal["pending", "generating", "plan_ready", "done", "failed"]  # shared by clips and jobs


class ClipRequest(BaseModel):
    topic: str = Field(min_length=1)
    duration: int = Field(gt=0)  # total seconds; must be a multiple of clip_duration
    resolution: Resolution = "480p"
    mode: Mode = "talking_head"
    clip_duration: ClipDuration = CLIP_DURATION
    supervise: bool = False

    @model_validator(mode="after")
    def duration_is_whole_clips(self):
        if self.duration % self.clip_duration:
            raise ValueError(f"duration must be a multiple of the clip length ({self.clip_duration} seconds)")
        return self

    @model_validator(mode="after")
    def story_videos_uses_5s_clips(self):
        if self.mode in ("story_videos", "narrated_drama") and self.clip_duration != 5:
            self.clip_duration = 5
            if self.duration % 5:
                raise ValueError(f"{self.mode} duration must be a multiple of 5 seconds")
        return self

    @property
    def num_clips(self) -> int:
        return self.duration // self.clip_duration


class EnhancePromptRequest(BaseModel):
    topic: str = Field(min_length=1)
    duration: int = 30
    clip_duration: int = 5
    mode: str = "story_videos"


class EnhancePromptResponse(BaseModel):
    enhanced_topic: str


class Clip(BaseModel):
    model_config = ConfigDict(extra="forbid")  # so update_clip() rejects misspelled field names

    index: int
    dialogue: str = ""  # Talking Head: the spoken line
    delivery: str = ""
    narration: str | None = None  # Story Time: what the narrator says
    visual: str | None = None  # Story Time: what is on screen in this clip
    resolution: Resolution | None = None  # what this clip was rendered at (Talking Head's clip 0: MASTER_RESOLUTION)
    video_url: str | None = None
    audio_url: str | None = None
    last_frame_url: str | None = None
    # A copy of video_url with its audio removed, used as a reference video so it carries pictures but no speech to leak.
    # Talking Head: only clip 0 has one (it is Job.anchor_video_url). Story Time: every clip except the last has one,
    # the next clip's video reference. video_url stays the original, and is what gets stitched into the final video.
    # Uploads expire after 24 hours; muted_video_at says when it was made.
    muted_video_url: str | None = None
    muted_video_at: float | None = None
    movie_script: dict | None = None  # Story Videos: the full clip script (location_id, shot, blocking, dialogue, etc.)
    custom_edited: bool = False       # True if the user manually edited this clip's text/prompt
    custom_prompt: str | None = None  # Direct user-edited Seedance prompt override
    status: Status = "pending"
    error: str | None = None  # why this clip failed


class ClipUpdate(BaseModel):
    dialogue: str | None = None
    delivery: str | None = None
    narration: str | None = None
    visual: str | None = None
    movie_script: dict | None = None
    custom_edited: bool | None = None
    custom_prompt: str | None = None


class PlanApprovalRequest(BaseModel):
    beats: list[dict] | None = None
    movie_bible: dict | None = None


class ReviseRequest(BaseModel):
    note: str = Field(min_length=1)


class ReviseApplyRequest(BaseModel):
    clips: list[int] = Field(default_factory=list)   # the clips to rewrite (an empty list saves the standing rules only)


class AddClipsRequest(BaseModel):
    clips: list[int] = Field(min_length=1, max_length=500)


class CastPerson(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    relation: str = Field(default="", max_length=120)
    clips: list[int] = Field(default_factory=list, max_length=500)
    include: bool = True


class CastApplyRequest(BaseModel):
    people: list[CastPerson] = Field(default_factory=list, max_length=12)


class RulesRequest(BaseModel):
    rules: list[dict] = Field(default_factory=list)


class ExtendStoryRequest(BaseModel):
    continuation_prompt: str
    duration: int = Field(default=30, description="Additional duration in seconds (must be multiple of 5)")


class Job(BaseModel):
    model_config = ConfigDict(extra="forbid")  # so update_job() rejects misspelled field names

    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    request: ClipRequest
    resolution: Resolution  # every clip's, except Talking Head's clip 0 (always MASTER_RESOLUTION)
    mode: Mode = "talking_head"
    scene_bible: str | None = None  # written once by the pipeline, reused by every clip and by regenerates
    # Taken from the first clip and reused unchanged as references for every later clip (kie.ai deletes uploaded files
    # after 24 hours, so they are re-made from the first clip's video when anchor_extracted_at is old). Talking Head
    # uses the muted video and the audio; Story Time uses the audio and the image (the first clip's last frame).
    anchor_video_url: str | None = None
    anchor_audio_url: str | None = None
    anchor_image_url: str | None = None
    anchor_extracted_at: float | None = None  # unix time the anchors were extracted
    clips: list[Clip] = Field(default_factory=list)
    status: Status = "pending"
    error: str | None = None  # why the job failed
    # Story Videos mode: the full scene bible dict, beat list, and reference banks
    movie_bible: dict | None = None
    beats: list | None = None
    acts: list | None = None           # Narrated Drama: the act breakdown long plans are built from
    delivery: dict | None = None       # Narrated Drama: story_in_five, must-understand facts and jargon (what the script must SAY)
    plan_report: dict | None = None    # Narrated Drama: delivery checks, spoken-script stats, dialogue-only page, blind reader
    plan_rules: list | None = None     # Narrated Drama: standing rules the user added while revising the plan [{"id", "text"}]
    revision: dict | None = None       # Narrated Drama: the plan revision in progress or just finished (status, note, clips, result)
    plan_versions_count: int = 0       # how many earlier versions of the plan can be restored (kept in Redis, see _plan_versions)
    cast_bank: dict | None = None      # character name -> FLUX image URL
    location_bank: dict | None = None  # location id -> list of FLUX image URLs
    voice_bank: dict | None = None     # character name -> voice sample URL
    # The joined video (final_video_path(), served at GET /jobs/{id}/video): when it was last built, or why it failed.
    final_video_at: float | None = None
    final_error: str | None = None
    # Langfuse direct trace URL for observability
    langfuse_url: str | None = None


# --- Redis Store Helpers ---
redis_client = redis.Redis.from_url(REDIS_URL, decode_responses=True)  # connects lazily


def _job_key(job_id: str) -> str:
    return f"job:{job_id}"


def save_job(job: Job) -> None:
    if not job.langfuse_url:
        job.langfuse_url = get_langfuse_trace_url(job.id)
    redis_client.set(_job_key(job.id), job.model_dump_json())


def get_job(job_id: str) -> Job | None:
    raw = redis_client.get(_job_key(job_id))
    return Job.model_validate_json(raw) if raw else None


def update_clip(job_id: str, clip_index: int, **fields) -> Job:
    """Update fields on one clip and return the saved job.

    Read-modify-write under WATCH, so two workers updating different clips of the
    same job at the same moment can't overwrite each other.
    """
    key = _job_key(job_id)

    def apply(pipe):
        raw = pipe.get(key)
        if raw is None:
            raise KeyError(f"job {job_id} not found")
        job = Job.model_validate_json(raw)
        if not 0 <= clip_index < len(job.clips):
            raise IndexError(f"job {job_id} has no clip {clip_index}")
        job.clips[clip_index] = Clip.model_validate({**job.clips[clip_index].model_dump(), **fields})
        pipe.multi()
        pipe.set(key, job.model_dump_json())
        return job

    return redis_client.transaction(apply, key, value_from_callable=True)


def update_job(job_id: str, **fields) -> Job:
    """Update job-level fields (status, error, scene_bible, clips, ...) and return the saved job.

    Same WATCH read-modify-write as update_clip(), so it can't overwrite a concurrent clip update either.
    """
    if fields.get("id", job_id) != job_id:
        raise ValueError("a job's id can't be changed")
    key = _job_key(job_id)

    def apply(pipe):
        raw = pipe.get(key)
        if raw is None:
            raise KeyError(f"job {job_id} not found")
        job = Job.model_validate({**Job.model_validate_json(raw).model_dump(), **fields})
        pipe.multi()
        pipe.set(key, job.model_dump_json())
        return job

    return redis_client.transaction(apply, key, value_from_callable=True)


# --- One running task per job ---
# The worker runs 8 tasks at once and /resume used to accept a job that was still "generating", so a second click (or a
# second queued task) ran the same job twice: every script and every kie.ai render paid for twice, by two tasks writing
# the same clips. A job's status cannot tell "running" from "the worker died" (a dead worker leaves it "generating"), so
# the running task holds a lock instead. It is renewed every JOB_LOCK_TTL / 3 seconds by a background thread and simply
# runs out if the worker dies, so a crashed job can still be resumed after at most JOB_LOCK_TTL seconds. The only job
# the lock cannot free is one whose worker is alive but stuck: restarting the worker ends its thread, and the lock
# runs out after the same JOB_LOCK_TTL.
JOB_LOCK_TTL = 90


class JobBusy(Exception):
    """Another task already holds this job."""


_RENEW_LOCK = redis_client.register_script(
    "if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('expire', KEYS[1], ARGV[2]) else return 0 end")
_RELEASE_LOCK = redis_client.register_script(
    "if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('del', KEYS[1]) else return 0 end")


def _lock_key(job_id: str) -> str:
    return f"joblock:{job_id}"


def job_is_running(job_id: str) -> bool:
    """Is a task holding this job right now?"""
    return bool(redis_client.exists(_lock_key(job_id)))


@contextmanager
def job_lock(job_id: str):
    """Hold the job for the length of the block, or raise JobBusy at once if another task has it. The lock is only ever
    renewed or released by the task that took it (compared by a private token), so it can never free someone else's."""
    key, token = _lock_key(job_id), uuid.uuid4().hex
    if not redis_client.set(key, token, nx=True, ex=JOB_LOCK_TTL):
        raise JobBusy(f"job {job_id} is already being run by another task")
    stop = threading.Event()

    def renew() -> None:
        while not stop.wait(JOB_LOCK_TTL / 3):
            try:
                _RENEW_LOCK(keys=[key], args=[token, JOB_LOCK_TTL])
            except Exception:
                pass   # a missed renewal is survivable: two more come before the lock runs out

    threading.Thread(target=renew, daemon=True, name=f"joblock-{job_id[:8]}").start()
    try:
        yield
    finally:
        stop.set()
        try:
            _RELEASE_LOCK(keys=[key], args=[token])
        except Exception:
            pass   # it runs out by itself


# --- OpenAI Helper ---
SCRIPT_SCHEMA = {  # Talking Head
    "type": "object",
    "properties": {
        "scene_bible": {"type": "string"},
        "clips": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"dialogue": {"type": "string"}, "delivery": {"type": "string"}},
                "required": ["dialogue", "delivery"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["scene_bible", "clips"],
    "additionalProperties": False,
}

STORY_SCRIPT_SCHEMA = {  # Story Time
    "type": "object",
    "properties": {
        "scene_bible": {"type": "string"},
        "clips": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "narration": {"type": "string"},
                    "visual": {"type": "string"},
                    "delivery": {"type": "string"},
                },
                "required": ["narration", "visual", "delivery"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["scene_bible", "clips"],
    "additionalProperties": False,
}


def _word_budget(clip_duration: int) -> tuple[int, int]:
    """(target, maximum) words for one clip's spoken line, at about 2.2 and 2.6 words per second."""
    return round(clip_duration * 2.2), round(clip_duration * 2.6)


def _script_system_prompt(num_clips: int, clip_duration: int = CLIP_DURATION) -> str:
    """Talking Head system prompt."""
    target_words, max_words = _word_budget(clip_duration)
    return f"""You write scripts for a short AI-generated "talking head" video: one person speaking directly to camera, split into {num_clips} consecutive clips of {clip_duration} seconds each. The user gives you the topic.

Return a JSON object with two keys.

"scene_bible": ONE fixed description of the speaker's appearance (age, build, hair, face, clothing), the setting (location, furniture, lighting, background details) and the camera framing and style. It is pasted unchanged in front of every clip's video prompt, so it must be concrete and visual, make sense on its own, and stay true for the whole video. Describe only what can be seen: no dialogue, no story events, no emotions that change over time, no mention of clip numbers.

"clips": a list of exactly {num_clips} objects, in order, each with:
- "dialogue": what the speaker says out loud in that clip. Natural spoken language, first person, addressed to the viewer. Aim for about {target_words} words and never exceed {max_words}, so it can be said comfortably within {clip_duration} seconds. Spoken words only: no stage directions, no emojis, no hashtags, no speaker labels, and no double quotation marks anywhere in the line (the line gets wrapped in double quotes later).
- "delivery": a short phrase (3-8 words) describing the tone and emotion of the delivery in that clip, for example "nervous and candid" or "voice softening, slight smile forming". It should evolve as the story does.

The dialogue lines together must form ONE continuous, coherent story with a beginning, a middle and an end. Each line picks up exactly where the previous one stopped: never restart, re-introduce the speaker, or repeat an earlier point, and let the final line bring the story to a natural close. They must never read as separate, isolated statements.

Return strictly valid JSON matching the schema, and nothing else."""


def _story_system_prompt(num_clips: int, clip_duration: int = CLIP_DURATION) -> str:
    """Story Time system prompt."""
    target_words, max_words = _word_budget(clip_duration)
    return f"""You write scripts for a short AI-generated "story time" video: a voiceover narrator tells a story over visuals that change from scene to scene. The video is split into {num_clips} consecutive clips of {clip_duration} seconds each. The user gives you the topic.

Return a JSON object with two keys.

"scene_bible": ONE fixed description that is pasted unchanged in front of every clip's video prompt. It must cover (1) the recurring characters' appearance (age, build, hair, face, clothing), (2) the overall world and visual style (era, look, color palette, lighting, camera style, for example "realistic cinematic style, soft natural morning light"), and (3) the narrator's voice (for example "a wistful female voice": describe only how the voice sounds, its age range, gender, tone and pace). Be concrete and visual. Do not describe any single scene's action and do not tie it to one room: the scenes change from clip to clip and this description must stay true for all of them. No dialogue, no story events, no mention of clip numbers.

"clips": a list of exactly {num_clips} objects, in order, each with:
- "narration": what the narrator says out loud during this clip. Natural spoken language, addressed to the viewer, in the narrator's voice. Aim for about {target_words} words and never exceed {max_words}, so it can be said comfortably within {clip_duration} seconds. Spoken words only: no stage directions, no emojis, no hashtags, no speaker labels, and no double quotation marks anywhere in the line (the line gets wrapped in double quotes later).
- "visual": what is on screen during this clip, in one or two concrete sentences: the location, who or what is visible (or "no people visible"), what they are doing, and the shot type (wide, medium, close-up). The scene should usually differ from the previous clip's, while the recurring characters and the visual style stay the same. It shows what the narration is about, but it must not contain spoken words, on-screen text or captions, and nobody on screen speaks to the camera. The FIRST clip's visual must clearly show the main recurring character on screen (face and clothing visible): this clip is used as the character's visual reference for the rest of the video. Clips after the first may or may not show the character.
- "delivery": a short phrase (3-8 words) describing the narrator's tone and emotion in this clip, for example "quiet and heavy" or "lighter, a faint smile in the voice". It should evolve as the story does.

The narration lines together must form ONE continuous, coherent story with a beginning, a middle and an end. Each line picks up exactly where the previous one stopped: never restart, re-introduce the story or repeat an earlier point, and let the final line bring the story to a natural close. They must never read as separate, isolated statements. The visuals follow the story from scene to scene.

Return strictly valid JSON matching the schema, and nothing else."""


# per mode: (system prompt builder, output schema, text fields that must be non-empty)
SCRIPT_MODES = {
    "talking_head": (_script_system_prompt, SCRIPT_SCHEMA, ("dialogue",)),
    "story_time": (_story_system_prompt, STORY_SCRIPT_SCHEMA, ("narration", "visual")),
}


def _check_script(script: dict, num_clips: int, mode: Mode = "talking_head") -> dict:
    clips = script["clips"]
    if len(clips) != num_clips:
        raise ValueError(f"expected {num_clips} clips, OpenAI returned {len(clips)}")
    text_fields = SCRIPT_MODES[mode][2]
    if not script["scene_bible"].strip() or any(not c[f].strip() for c in clips for f in text_fields):
        raise ValueError(f"OpenAI returned an empty scene_bible or an empty {' / '.join(text_fields)}")
    return script


def generate_script(topic: str, num_clips: int, mode: Mode = "talking_head", clip_duration: int = CLIP_DURATION) -> dict:
    """One OpenAI call, using the system prompt for `mode`.

    talking_head -> {"scene_bible": str, "clips": [{"dialogue": str, "delivery": str}, ...]}
    story_time   -> {"scene_bible": str, "clips": [{"narration": str, "visual": str, "delivery": str}, ...]}
    """
    if mode not in SCRIPT_MODES:
        raise ValueError(f"mode must be one of {tuple(SCRIPT_MODES)}")
    if clip_duration not in get_args(ClipDuration):
        raise ValueError(f"clip_duration must be one of {get_args(ClipDuration)}")
    if num_clips < 1:
        raise ValueError("num_clips must be at least 1")
    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY is not set")

    build_system_prompt, schema, _ = SCRIPT_MODES[mode]
    script = _ask_openai_json(build_system_prompt(num_clips, clip_duration), f"Topic: {topic}", f"{mode}_script", schema)
    return _check_script(script, num_clips, mode)


# $ per million tokens: (input, cached input, output). Used only to print a running estimate next to the
# token counts - the authoritative figure is OpenAI's own usage page. A model that is not listed still gets
# its tokens reported; only the dollar estimate is skipped.
OPENAI_PRICES = {
    "gpt-5.5":     (5.00, 0.50, 30.00),   # cached rate from OpenAI's gpt-5.5 model page, checked 2026-10-08
    "gpt-6-luna":  (0.10, 0.01, 0.50),
}
USAGE_LOG: list[dict] = []   # one entry per OpenAI call made by this process


def _price_for(model: str):
    for prefix, prices in OPENAI_PRICES.items():
        if (model or "").startswith(prefix):
            return prices
    return None


def _record_usage(name: str, model: str, usage) -> dict:
    """Keep what every OpenAI reply already tells us and we were throwing away.

    `cached_tokens` is the only way to know whether the prompt-caching prefix is actually being hit -
    Langfuse prices from its own table and will not show it. `reasoning_tokens` is the invisible thinking
    that is billed at the output rate; on the first 5-minute run it was ~85,700 tokens, about a third of
    the bill, and nothing recorded it."""
    if usage is None:
        return {}
    pt = getattr(usage, "prompt_tokens_details", None)
    ct = getattr(usage, "completion_tokens_details", None)
    entry = {
        "name": name,
        "model": model,
        "input": getattr(usage, "prompt_tokens", 0) or 0,
        "cached": getattr(pt, "cached_tokens", 0) or 0,
        "output": getattr(usage, "completion_tokens", 0) or 0,
        "reasoning": getattr(ct, "reasoning_tokens", 0) or 0,
    }
    prices = _price_for(model)
    if prices:
        p_in, p_cached, p_out = prices
        fresh = max(0, entry["input"] - entry["cached"])
        # An unknown cached rate is charged at the full input rate: over-estimating is the safe direction.
        entry["cost"] = round(
            (fresh * p_in + entry["cached"] * (p_cached if p_cached is not None else p_in) + entry["output"] * p_out)
            / 1_000_000, 6)
    USAGE_LOG.append(entry)
    hit = f" ({entry['cached']:,} cached)" if entry["cached"] else ""
    think = f", {entry['reasoning']:,} reasoning" if entry["reasoning"] else ""
    money = f"  ~${entry['cost']:.4f}" if "cost" in entry else ""
    print(f"    [openai] {name} on {model}: in {entry['input']:,}{hit}, out {entry['output']:,}{think}{money}",
          flush=True)
    return entry


def usage_summary(reset: bool = False) -> dict:
    """Totals for everything this process has asked OpenAI for, by call name."""
    by_name: dict[str, dict] = {}
    for e in USAGE_LOG:
        row = by_name.setdefault(e["name"], {"calls": 0, "input": 0, "cached": 0, "output": 0, "reasoning": 0, "cost": 0.0})
        row["calls"] += 1
        for k in ("input", "cached", "output", "reasoning"):
            row[k] += e.get(k, 0)
        row["cost"] += e.get("cost", 0.0)
    total = {"calls": len(USAGE_LOG), "cost": round(sum(e.get("cost", 0.0) for e in USAGE_LOG), 4)}
    for k in ("input", "cached", "output", "reasoning"):
        total[k] = sum(e.get(k, 0) for e in USAGE_LOG)
    if reset:
        USAGE_LOG.clear()
    return {"total": total, "by_name": by_name}


class OpenAIOutputCut(ValueError):
    """The reply hit `max_completion_tokens` and was cut off, so its JSON is unusable. A ValueError, like every
    other unusable reply, so existing handlers keep working; callers that can retry catch this one by name."""


def _ask_openai_json(system_prompt: str, user_content: str, name: str, schema: dict,
                     model: str | None = None, max_completion_tokens: int | None = None, reasoning_effort: str | None = None) -> dict:
    """One Structured Outputs call (strict JSON schema); returns the parsed JSON or raises ValueError.

    `max_completion_tokens` caps the whole reply, reasoning included, so a model stuck repeating itself costs a
    bounded amount (one clip once ran to 36,408 tokens on a repeated prop entry). Left out unless given.
    `reasoning_effort` ("low", "medium", "high") is sent only when given; a model that does not take it is asked again without it."""
    model = model or OPENAI_MODEL
    extra = {"max_completion_tokens": max_completion_tokens} if max_completion_tokens else {}
    if reasoning_effort:
        extra["reasoning_effort"] = reasoning_effort

    def _create(kw):
        return OpenAI(api_key=OPENAI_API_KEY, timeout=300).chat.completions.create(
            name=name,
            model=model,
            messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_content}],
            response_format={"type": "json_schema", "json_schema": {"name": name, "strict": True, "schema": schema}},
            **kw,
        )
    try:
        response = _create(extra)
    except Exception as e:
        if reasoning_effort and "reasoning_effort" in str(e):
            extra.pop("reasoning_effort")
            response = _create(extra)
        else:
            raise
    _record_usage(name, model, getattr(response, "usage", None))
    message = response.choices[0].message
    if message.refusal:
        raise ValueError(f"OpenAI refused to write the script: {message.refusal}")
    if getattr(response.choices[0], "finish_reason", None) == "length":
        raise OpenAIOutputCut(f"{name}: the reply was cut off at the {max_completion_tokens or 'model'} token limit")
    try:
        return json.loads(message.content)
    except (TypeError, json.JSONDecodeError) as e:
        raise ValueError(f"OpenAI did not return valid JSON: {e}") from e


def _line_schema(text_field: str) -> dict:
    return {
        "type": "object",
        "properties": {text_field: {"type": "string"}, "delivery": {"type": "string"}},
        "required": [text_field, "delivery"],
        "additionalProperties": False,
    }


def _line_system_prompt(mode: Mode, clip_duration: int, is_first: bool, is_last: bool) -> str:
    """System prompt for rewriting ONE clip's spoken line (Regenerate Script)."""
    target_words, max_words = _word_budget(clip_duration)
    where = (
        "This clip is the whole video: the new line must tell the complete story on its own."
        if is_first and is_last
        else "This is the LAST clip: the new line must bring the story to a natural close."
        if is_last
        else "The new line must pick up exactly where the previous line stopped and move the story on."
    )
    rules = (
        f"Aim for about {target_words} words and never exceed {max_words}, so it can be said comfortably within "
        f"{clip_duration} seconds. Spoken words only: no stage directions, no emojis, no hashtags, no speaker labels, and "
        "no double quotation marks anywhere in the line (the line gets wrapped in double quotes later)."
    )
    if mode == "story_time":
        return f"""You rewrite ONE clip of a short AI-generated "story time" video: a voiceover narrator tells a story over visuals that change from scene to scene, in consecutive clips of {clip_duration} seconds. The user gives you the topic, the fixed description of the characters, world and narrator (the scene bible), the narration of the clip just before this one, what is on screen in this clip (its visual, which stays unchanged), and this clip's current narration, which is being replaced.

Write NEW narration for this clip, clearly different from the current one. It continues the story from the previous clip's narration and it is about what is on screen in this clip. {where}

Return a JSON object with:
- "narration": what the narrator says out loud during this clip. Natural spoken language, addressed to the viewer, in the narrator's voice. {rules}
- "delivery": a short phrase (3-8 words) describing the narrator's tone and emotion for the new narration.

Return strictly valid JSON matching the schema, and nothing else."""
    return f"""You rewrite ONE clip of a short AI-generated "talking head" video: one person speaking directly to camera, in consecutive clips of {clip_duration} seconds. The user gives you the topic, the fixed description of the speaker and setting (the scene bible), the line spoken in the clip just before this one, and this clip's current line, which is being replaced.

Write a NEW line for this clip, clearly different from the current one. It continues the story from the previous line. {where}

Return a JSON object with:
- "dialogue": what the speaker says out loud in this clip. Natural spoken language, first person, addressed to the viewer. {rules}
- "delivery": a short phrase (3-8 words) describing the tone and emotion of the delivery for the new line.

Return strictly valid JSON matching the schema, and nothing else."""


def regenerate_line(job: Job, clip_index: int) -> dict:
    """One OpenAI call for Regenerate Script: a new spoken line for one clip, different from its current one and
    following on from the line before it (the "preceding clip as context" of Prompt 9). The scene bible is reused.

    talking_head -> {"dialogue": str, "delivery": str}
    story_time   -> {"narration": str, "delivery": str}; the clip's visual is kept, and the narration is written for it
    """
    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY is not set")
    story = job.mode == "story_time"
    text_field = "narration" if story else "dialogue"
    clip = job.clips[clip_index]
    previous = getattr(job.clips[clip_index - 1], text_field) if clip_index > 0 else None
    parts = [
        f"Topic: {job.request.topic}",
        f"Scene bible: {job.scene_bible}",
        f"Previous clip's {text_field}: {previous}" if previous else "Previous clip: none, this is the first clip.",
    ]
    if story:
        parts.append(f"This clip's visual (unchanged): {clip.visual}")
    parts.append(f"This clip's current {text_field} (to replace): {getattr(clip, text_field)}")
    system = _line_system_prompt(job.mode, job.request.clip_duration, clip_index == 0, clip_index == len(job.clips) - 1)
    line = _ask_openai_json(system, "\n".join(parts), f"{job.mode}_line", _line_schema(text_field))
    if not line[text_field].strip():
        raise ValueError(f"OpenAI returned an empty {text_field}")
    return {text_field: line[text_field].strip(), "delivery": line["delivery"].strip()}


VISUAL_SCHEMA = {
    "type": "object",
    "properties": {"visual": {"type": "string"}},
    "required": ["visual"],
    "additionalProperties": False,
}


def _visual_system_prompt(is_first: bool) -> str:
    """System prompt for giving ONE Story Time clip a new scene (Regenerate Scene)."""
    character = (
        " This is the FIRST clip: the new visual must clearly show the main recurring character on screen (face and "
        "clothing visible), because this clip is the character's visual reference for the rest of the video."
        if is_first
        else ""
    )
    return f"""You rewrite the SCENE of ONE clip of a short AI-generated "story time" video: a voiceover narrator tells a story over visuals that change from scene to scene. The user gives you the topic, the fixed description of the characters, world, visual style and narrator (the scene bible), the previous clip's narration and visual, this clip's narration (which stays exactly as it is), and this clip's current visual, which is being replaced.

Write a NEW visual for this clip: a clearly different scene from the current one (a different setting, action or shot), which still shows what this clip's narration is about, follows on from the previous clip, and keeps the recurring characters and the visual style of the scene bible.{character}

Return a JSON object with:
- "visual": what is on screen during this clip, in one or two concrete sentences: the location, who or what is visible (or "no people visible"), what they are doing, and the shot type (wide, medium, close-up). It must not contain spoken words, on-screen text or captions, and nobody on screen speaks to the camera.

Return strictly valid JSON matching the schema, and nothing else."""


def regenerate_visual(job: Job, clip_index: int) -> dict:
    """One OpenAI call for Story Time's Regenerate Scene: a NEW visual for one clip, a different scene that still fits
    the clip's narration (kept word for word) and the story. The scene bible is reused. -> {"visual": str}"""
    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY is not set")
    clip = job.clips[clip_index]
    parts = [f"Topic: {job.request.topic}", f"Scene bible: {job.scene_bible}"]
    if clip_index > 0:
        prev = job.clips[clip_index - 1]
        parts += [f"Previous clip's narration: {prev.narration}", f"Previous clip's visual: {prev.visual}"]
    else:
        parts.append("Previous clip: none, this is the first clip.")
    parts += [f"This clip's narration (unchanged): {clip.narration}", f"This clip's current visual (to replace): {clip.visual}"]
    answer = _ask_openai_json(_visual_system_prompt(clip_index == 0), "\n".join(parts), "story_time_visual", VISUAL_SCHEMA)
    if not answer["visual"].strip():
        raise ValueError("OpenAI returned an empty visual")
    return {"visual": answer["visual"].strip()}


# --- Seedance Helpers ---
def build_clip_prompt(mode: Mode, scene_bible: str, clip: Clip, is_first_clip: bool) -> str:
    """Assemble one clip's Seedance prompt from the fixed template for `mode`: a first-clip and a continuation
    template per mode. Story Time's continuation tags its three references as @Video1 / @Audio1 / @Image1 (Test S).
    """
    bible = scene_bible.strip().rstrip(".")  # the templates add their own punctuation
    if mode == "talking_head":
        if not clip.dialogue:
            raise ValueError("a talking_head clip needs dialogue")
        if is_first_clip:
            return (
                f'{bible}. The speaker speaks directly to camera, {clip.delivery}: "{clip.dialogue}" '
                "Natural lip sync to dialogue, no background music, no score."
            )
        return (
            f'Continuing directly from @Video1, {bible}, still speaking to camera, {clip.delivery}: "{clip.dialogue}" '
            "Natural lip sync to dialogue, same lighting and camera style, no background music, no score."
        )
    if mode == "story_time":
        if not (clip.narration and clip.visual):
            raise ValueError("a story_time clip needs narration and visual")
        visual = clip.visual.strip().rstrip(".")
        if is_first_clip:
            return (
                f"{visual}. {bible}. Voiceover narration only, {clip.delivery}, no visible speaker, "
                "no lip sync needed since no one is speaking on camera: "
                f'"{clip.narration}" '
                "Natural ambient sound only, no music, no score \u2014 just the voiceover."
            )
        return (
            f"Same characters, visual style and lighting as @Video1, but a new scene: {visual}. {bible}. "
            "The main character looks exactly like @Image1. Voiceover narration only, in the same narrator voice as "
            f"@Audio1, {clip.delivery}, no visible speaker, no lip sync needed since no one is speaking on camera: "
            f'"{clip.narration}" '
            "Natural ambient sound only, no music, no score \u2014 just the voiceover."
        )
    raise ValueError(f"mode must be one of {get_args(Mode)}")


class KieError(RuntimeError):
    """kie.ai rejected a request, or a generation task failed."""

    def __init__(self, message: str, fail_code: str | None = None):
        super().__init__(message)
        self.fail_code = fail_code


def _kie_client(base_url: str, timeout: float = 60) -> httpx.Client:
    if not KIE_API_KEY:
        raise RuntimeError("KIE_API_KEY is not set")
    return httpx.Client(
        base_url=base_url,
        headers={"Authorization": f"Bearer {KIE_API_KEY}"},
        timeout=timeout,
        # retries connection errors only (request never sent), so a POST can't be submitted twice
        transport=httpx.HTTPTransport(retries=3),
    )


def _unwrap(response: httpx.Response) -> dict:
    """kie.ai wraps every reply as {"code", "msg", "data"}: return data, or raise KieError."""
    try:
        body = response.json()
    except ValueError:
        raise KieError(f"kie.ai returned a non-JSON reply (HTTP {response.status_code}): {response.text[:200]}")
    if response.status_code != 200 or body.get("code") != 200:
        raise KieError(f"kie.ai error {body.get('code', response.status_code)}: {body.get('msg')}")
    return body["data"]


def _clip_input(prompt, resolution, duration, generate_audio, video_urls, audio_urls, image_urls) -> dict:
    payload = {
        "prompt": prompt,
        "resolution": resolution,
        "duration": duration,
        "aspect_ratio": "9:16",
        "nsfw_checker": False,
        "generate_audio": generate_audio,
    }
    for field, urls in (
        ("reference_video_urls", video_urls),
        ("reference_audio_urls", audio_urls),
        ("reference_image_urls", image_urls),
    ):
        if urls:  # omitted entirely when not provided
            payload[field] = list(urls)
    return payload


def _wait_for_clip(client: httpx.Client, task_id: str) -> dict:
    deadline = time.monotonic() + KIE_POLL_TIMEOUT
    delay, network_errors = 3.0, 0
    while time.monotonic() < deadline:
        time.sleep(delay)
        delay = min(delay * 1.3, 10)
        try:
            data = _unwrap(client.get("/api/v1/jobs/recordInfo", params={"taskId": task_id}))
            network_errors = 0
        except httpx.TransportError:
            network_errors += 1  # the task is already paid for, so ride out a few network blips
            if network_errors > 5:
                raise
            continue
        if data.get("state") == "success":
            urls = json.loads(data["resultJson"]).get("resultUrls") or []
            if not urls:
                raise KieError(f"task {task_id} succeeded but returned no video URL")
            return {"task_id": task_id, "video_url": urls[0], "credits_consumed": data.get("creditsConsumed")}
        if data.get("state") == "fail":
            raise KieError(
                f"task {task_id} failed ({data.get('failCode')}): {data.get('failMsg')}", data.get("failCode") or None
            )
    raise TimeoutError(f"task {task_id} did not finish within {KIE_POLL_TIMEOUT} seconds")


@observe(name="kie_generate_clip", as_type="span")
def generate_clip(
    prompt: str,
    resolution: str,
    duration: int = CLIP_DURATION,
    reference_video_urls: list[str] | None = None,
    reference_audio_urls: list[str] | None = None,
    reference_image_urls: list[str] | None = None,
    generate_audio: bool = True,
) -> dict:
    """Submit one Seedance 2.0 Mini job, poll until it finishes, and return
    {"task_id": str, "video_url": str, "credits_consumed": number}.

    Reference URLs must be publicly fetchable by kie.ai and are left out of the request if not given.
    Raises KieError if kie.ai rejects the request or the task fails (failMsg is in the message).
    """
    if resolution not in get_args(Resolution):
        raise ValueError(f"resolution must be one of {get_args(Resolution)}")
    if not 4 <= duration <= 15:
        raise ValueError("duration must be 4-15 seconds")
    body = {
        "model": KIE_MODEL,
        "input": _clip_input(
            prompt, resolution, duration, generate_audio,
            reference_video_urls, reference_audio_urls, reference_image_urls,
        ),
    }
    with _kie_client(KIE_API_BASE) as client:
        task_id = _unwrap(client.post("/api/v1/jobs/createTask", json=body))["taskId"]
        result = _wait_for_clip(client, task_id)
        try:
            get_client().update_current_span(
                metadata={
                    "task_id": task_id,
                    "credits_consumed": result.get("credits_consumed"),
                    "resolution": resolution,
                    "duration": duration,
                }
            )
        except Exception:
            pass
        return result


def _run_ffmpeg(*args: str) -> None:
    result = subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args], capture_output=True, text=True
    )
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {result.stderr.strip()[-500:]}")


def _download(url: str, dest: Path) -> None:
    with httpx.stream("GET", url, timeout=120, follow_redirects=True) as response:
        response.raise_for_status()
        with dest.open("wb") as f:
            for chunk in response.iter_bytes():
                f.write(chunk)


def _upload_to_kie(path: Path) -> str:
    """Upload a local file to kie.ai's file host and return a URL its models can fetch."""
    with _kie_client(KIE_UPLOAD_BASE, timeout=120) as client, path.open("rb") as f:
        data = _unwrap(
            client.post(
                "/api/file-stream-upload",
                files={"file": (path.name, f)},
                data={"uploadPath": "seedance-refs", "fileName": path.name},
            )
        )
    return data["downloadUrl"]  # the reply has no "fileUrl", despite what the docs example shows


def extract_last_frame(video_url: str) -> str:
    """Grab the final frame of a video as a PNG and return a URL for it (valid ~24 hours)."""
    with tempfile.TemporaryDirectory() as tmp:
        video, frame = Path(tmp) / "clip.mp4", Path(tmp) / f"{uuid.uuid4().hex}.png"
        _download(video_url, video)
        _run_ffmpeg("-sseof", "-1", "-i", str(video), "-an", "-update", "1", str(frame))
        return _upload_to_kie(frame)


def extract_audio(video_url: str) -> str:
    """Extract a video's audio track as a WAV and return a URL for it (valid ~24 hours)."""
    with tempfile.TemporaryDirectory() as tmp:
        video, audio = Path(tmp) / "clip.mp4", Path(tmp) / f"{uuid.uuid4().hex}.wav"
        _download(video_url, video)
        _run_ffmpeg("-i", str(video), "-vn", "-map", "0:a:0", "-c:a", "pcm_s16le", str(audio))
        return _upload_to_kie(audio)

def mute_video(video_url: str) -> str:
    """Return a URL for a copy of the video with its audio track removed (the video stream is copied untouched, so
    nothing is re-encoded). Used as a reference_video_urls entry so the reference carries pictures only and can't
    leak the clip's speech into the clips generated from it. Valid ~24 hours."""
    with tempfile.TemporaryDirectory() as tmp:
        video, muted = Path(tmp) / "clip.mp4", Path(tmp) / f"{uuid.uuid4().hex}.mp4"
        _download(video_url, video)
        _run_ffmpeg("-i", str(video), "-an", "-c:v", "copy", str(muted))
        return _upload_to_kie(muted)


# --- Final Video Assembly ---
FINAL_SIZES = {"480p": (496, 864), "720p": (720, 1280)}  # Seedance's 9:16 sizes, used if no clip shows the job's own
FADE_SECONDS = 0.02  # a tiny audio fade at both ends of every clip, so the joins can't click
# Talking Head: Seedance often starts a clip with a pause and a breath or sigh before the first word. In the final
# video, clips after the first start just before their first word instead (clip 1 keeps its opening). See _lead_in().
LEAD_IN_MAX = 1.5  # seconds; never cut more than this
LEAD_IN_MARGIN = 0.06  # seconds of quiet kept before the first word's onset
LEAD_IN_FADE = 0.03  # seconds of audio fade-in at the new start


def job_media_dir(job_id: str) -> Path:
    return MEDIA_DIR / job_id


def final_video_path(job_id: str) -> Path:
    return job_media_dir(job_id) / "final.mp4"


def _probe(path: Path) -> dict:
    """Size, frame rate and duration of a local video's picture, and whether it has an audio track."""
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,width,height,r_frame_rate,duration", "-of", "json", str(path)],
        capture_output=True, text=True,
    )
    if out.returncode != 0:
        raise RuntimeError(f"ffprobe failed on {path.name}: {out.stderr.strip()[-300:]}")
    streams = json.loads(out.stdout)["streams"]
    video = next((s for s in streams if s["codec_type"] == "video"), None)
    if video is None:
        raise RuntimeError(f"{path.name} has no video stream")
    return {
        "width": video["width"],
        "height": video["height"],
        "fps": video["r_frame_rate"],  # e.g. "24/1", as ffmpeg's fps filter takes it
        "duration": float(video["duration"]),
        "has_audio": any(s["codec_type"] == "audio" for s in streams),
    }


def _local_clip(job_id: str, clip: Clip) -> Path:
    """The clip's video, downloaded once into the job's media folder (named after its URL, so a regenerated clip is a
    new file and an unchanged one is never fetched twice). For story/narrated drama modes, check clip_NN.mp4 first."""
    movie_path = job_media_dir(job_id) / "clips" / f"clip_{clip.index + 1:02d}.mp4"
    if movie_path.exists():
        return movie_path
    path = job_media_dir(job_id) / "clips" / f"{hashlib.sha1(clip.video_url.encode()).hexdigest()[:16]}.mp4"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        part = path.with_name(path.name + ".part")
        _download(clip.video_url, part)
        part.replace(path)
    return path


def _lead_in(path: Path, fps: str) -> float:
    """Seconds of quiet lead-in (silence, a breath or a sigh) before the first word, safe to cut; 0 if unsure.

    From the first 3 seconds of audio, in 20 ms slices: the first word's first VOICED slice is loud (within 18 dB of
    the clip's loudest) and tonal (low spectral flatness; a breath or hiss is noisy). Stepping back from it while the
    sound is still at speech level (within 25 dB) keeps the word's own first consonant, like the "Sh" of "She". The
    cut is LEAD_IN_MARGIN before that, rounded down to a frame so picture and audio are cut at the same instant, and
    never more than LEAD_IN_MAX. Everything cut is at least 25 dB quieter than the voice.
    """
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-vn", "-ac", "1", "-ar", "16000", "-t", "3", "-f", "f32le", "-"],
        capture_output=True,
    ).stdout
    x = np.frombuffer(raw, dtype=np.float32)
    frame = 320  # 20 ms at 16 kHz
    n = len(x) // frame
    if n < 3:
        return 0.0
    slices = x[: n * frame].reshape(n, frame)
    level = 20 * np.log10(np.sqrt((slices ** 2).mean(axis=1)) + 1e-9)
    spectrum = np.abs(np.fft.rfft(slices * np.hanning(frame), axis=1))[:, 3:] + 1e-9  # skip DC and rumble
    flatness = np.exp(np.log(spectrum).mean(axis=1)) / spectrum.mean(axis=1)
    loudest = level.max()
    voiced = np.flatnonzero((level > loudest - 18) & (flatness < 0.2))
    if loudest < -50 or not len(voiced):
        return 0.0
    i = voiced[0]
    while i > 0 and level[i - 1] > loudest - 25:
        i -= 1
    num, den = (int(v) for v in fps.split("/"))
    frames = int(max(0.0, min(i * 0.02 - LEAD_IN_MARGIN, LEAD_IN_MAX)) * num / den)
    return frames * den / num


def _normalized(src: Path, width: int, height: int, fps: str, trim_lead_in: bool = False) -> Path:
    """`src` made ready to join: scaled to width x height at a constant frame rate, its audio cut to the length of the
    picture with tiny fades at both ends, video encoded once at high quality (x264 CRF 16) and audio kept as PCM so
    the join itself adds no audio gaps. With `trim_lead_in`, it starts just before the first word instead (see
    _lead_in()), picture and audio cut together. Cached next to the downloaded clips."""
    out = src.parent.parent / "norm" / f"{src.stem}_{width}x{height}{'_trim' if trim_lead_in else ''}.mkv"
    if out.exists():
        return out
    out.parent.mkdir(parents=True, exist_ok=True)
    info = _probe(src)
    start = _lead_in(src, info["fps"]) if trim_lead_in and info["has_audio"] else 0.0
    seconds = info["duration"] - start
    fade_in = LEAD_IN_FADE if start else FADE_SECONDS
    audio_input, audio = (["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo"], "[1:a]") if not info["has_audio"] else ([], "[0:a]")
    graph = (
        f"[0:v]scale={width}:{height}:flags=lanczos,setsar=1,fps={fps},format=yuv420p[v];"
        f"{audio}aformat=sample_fmts=s16:sample_rates=48000:channel_layouts=stereo,atrim=0:{seconds},asetpts=PTS-STARTPTS,"
        f"afade=t=in:d={fade_in},afade=t=out:st={seconds - FADE_SECONDS:.4f}:d={FADE_SECONDS}[a]"
    )
    part = out.with_name(out.stem + ".part.mkv")
    _run_ffmpeg(
        *(["-ss", f"{start:.4f}"] if start else []), "-i", str(src), *audio_input, "-filter_complex", graph,
        "-map", "[v]", "-map", "[a]", "-t", f"{seconds}",
        "-c:v", "libx264", "-preset", "medium", "-crf", "16", "-profile:v", "high", "-level", "4.1", "-c:a", "pcm_s16le",
        str(part),
    )
    part.replace(out)
    return out


def _wants_lead_in_trim(job: Job, index: int, clip: Clip) -> bool:
    """Should this clip start just before its first word?

    Clip 0 always keeps its opening. A Narrated Drama clip with no speech - a wordless shock beat, an
    establishing shot of the place - has no first word, and its opening frames are the whole point of the
    beat. _lead_in() keys on sound that is loud AND tonal, which a brass bell, a lift chime or a slammed
    door all are, so it would read the jolt as the first word and cut the build-up before it."""
    if index == 0:
        return False
    if job.mode == "talking_head":
        return True
    if job.mode != "narrated_drama":
        return False
    script = clip.movie_script or {}
    turns = script.get("speech")
    if turns is None:  # a clip planned before multi-speaker turns existed
        return bool((script.get("audio_text") or "").strip())
    return any((t.get("line") or "").strip() for t in turns)


def assemble_final_video(job: Job) -> Path:
    """Join every clip, in order, into the job's final video and return its path.

    Each clip is downloaded (and kept: kie.ai deletes generated videos after 14 days), then scaled to the job's
    resolution. Talking Head's clip 0 is 720p while the rest are the job's, so a plain stream-copy join can't work.
    In Talking Head, every clip after the first also starts just before its first word, without the pause and breath
    Seedance tends to open with (clip 0 keeps its opening). The prepared clips are joined without a second video
    encode; the audio is encoded once for the whole video. The finished file replaces the old one in a single step,
    so a half-written video is never served.
    """
    if not job.clips or any(c.status != "done" or not c.video_url for c in job.clips):
        raise ValueError("every clip must be done before the final video can be made")
    sources = [_local_clip(job.id, c) for c in job.clips]
    probes = [_probe(p) for p in sources]
    own = [p for p, c in zip(probes, job.clips) if (c.resolution or job.resolution) == job.resolution]
    width, height = (own[0]["width"], own[0]["height"]) if own else FINAL_SIZES[job.resolution]
    fps = (own or probes)[0]["fps"]
    trims = [_wants_lead_in_trim(job, i, c) for i, c in enumerate(job.clips)]
    parts = [_normalized(p, width, height, fps, trim) for p, trim in zip(sources, trims)]
    folder = job_media_dir(job.id)
    listing = folder / "concat.txt"
    listing.write_text("".join(f"file '{p.as_posix()}'\n" for p in parts), encoding="utf-8")
    part = folder / "final.part.mp4"
    _run_ffmpeg(
        "-f", "concat", "-safe", "0", "-i", str(listing),
        "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(part),
    )
    final = final_video_path(job.id)
    part.replace(final)
    return final


# --- Story Videos Helpers ---
import movie_scene_multispeaker as movie
def _generate_flux_images(job_id: str, bible: dict, existing_cast: dict | None = None, existing_locs: dict | None = None) -> tuple[dict, dict]:
    """Generate FLUX images for all cast and locations. Only generates images for characters/locations not already present in the banks. Returns (cast_bank, location_bank)."""
    cast_bank = dict(existing_cast or {})
    # Narrated Drama derives look/image_prompt from each character's structured "appearance"; doing it here
    # too covers a bible that reached this point without it (an older job, or a continuation's new cast).
    try:
        import hybrid_narrated_drama as _hnd
        _hnd._compile_bible_visuals(bible)
    except Exception:
        pass
    for c in bible.get("characters", []):
        if c["name"] not in cast_bank:
            url = movie.generate_flux_image(c["image_prompt"])
            if url:
                cast_bank[c["name"]] = url
                task_log.info("job %s: FLUX cast image for %s", job_id, c["name"])
            else:
                task_log.warning("job %s: FLUX cast image failed for %s", job_id, c["name"])

    location_bank = dict(existing_locs or {})
    for loc in bible.get("locations", []):
        if loc["id"] not in location_bank:
            master = movie.generate_flux_image(loc["image_prompt"])
            views = [master] if master else []
            if master:
                for view_desc in loc.get("views", [])[1:3]:  # up to 2 additional angles
                    angle = movie.generate_flux_image(movie._view_prompt(view_desc), input_image=master)
                    if angle:
                        views.append(angle)
            location_bank[loc["id"]] = views
            task_log.info("job %s: FLUX location images for %s (%d views)", job_id, loc["id"], len(views))

    return cast_bank, location_bank


def _bank_new_voices(job_id: str, clip_index: int, clip_script: dict, video_url: str,
                     voice_bank: dict) -> None:
    """After rendering a clip, extract voice samples for any character speaking for the first time."""
    clip_path = _local_clip_movie(job_id, clip_index, video_url)
    for turn_idx, d in enumerate(clip_script.get("dialogue", [])):
        speaker = d["speaker"]
        if speaker.lower() not in {k.lower() for k in voice_bank}:
            try:
                wav = movie.trim_windowed_voice(
                    clip_path, speaker, d["start_est"], d["end_est"],
                    turn_idx, clip_script["dialogue"],
                    out_dir=job_media_dir(job_id) / "voices",
                )
                if wav is not None and wav.exists():
                    voice_bank[speaker] = _upload_to_kie(wav)
                    task_log.info("job %s: banked voice for %s", job_id, speaker)
                else:
                    task_log.info("job %s: no usable voice sample for %s in this line", job_id, speaker)
            except Exception as e:
                task_log.warning("job %s: voice banking failed for %s: %s", job_id, speaker, e)


def _local_clip_movie(job_id: str, clip_index: int, video_url: str) -> Path:
    """Download a movie-mode clip to the job's media folder, named by index."""
    path = job_media_dir(job_id) / "clips" / f"clip_{clip_index + 1:02d}.mp4"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        part = path.with_name(path.name + ".part")
        _download(video_url, part)
        part.replace(path)
    return path


def _save_master_plan_file(job: Job) -> Path:
    folder = job_media_dir(job.id)
    folder.mkdir(parents=True, exist_ok=True)
    plan_path = folder / "master_plan.json"
    num = len(job.clips) if job.clips else job.request.num_clips
    clip_dur = job.request.clip_duration or 5
    data = {
        "topic": job.request.topic,
        "duration": num * clip_dur,
        "total_clips": num,
        "scene_bible": job.movie_bible,
        "acts": job.acts,
        "beats": job.beats,
    }
    if job.delivery:
        data["delivery"] = job.delivery
    if job.plan_report:
        data["plan_report"] = job.plan_report
        page = job.plan_report.get("dialogue_only")
        if page:  # the spoken script alone, to read before anything is rendered
            (folder / "plan_dialogue.txt").write_text(page + "\n", encoding="utf-8")
    plan_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return plan_path


def _generate_movie_plan(job_id: str) -> None:
    """Phase 1: Master Plan (outline) generation. Pauses with status='plan_ready' for user review."""
    job = get_job(job_id)
    topic = job.request.topic
    total_clips = job.request.num_clips

    task_log.info("job %s: generating master plan for %d clips", job_id, total_clips)
    outline, problems = movie.write_outline(topic, job.request.duration, total_clips)
    bible = outline["scene_bible"]
    beats = outline["beats"]
    update_job(job_id, movie_bible=bible, beats=beats,
               scene_bible=json.dumps(bible, ensure_ascii=False),
               status="plan_ready")
    _save_master_plan_file(get_job(job_id))
    task_log.info("job %s: master plan ready (%d characters, %d locations, %d beats) - waiting for review",
                  job_id, len(bible["characters"]), len(bible["locations"]), len(beats))


def _continue_movie_job(job_id: str) -> None:
    """Phase 1.5: FLUX images -> Phase 2: Per-clip script + render -> assemble."""
    job = get_job(job_id)
    topic = job.request.topic
    total_clips = len(job.clips)
    bible = job.movie_bible
    beats = job.beats

    # Phase 1.5: FLUX images (check and generate any missing cast/locations)
    cast_bank = job.cast_bank or {}
    location_bank = job.location_bank or {}
    task_log.info("job %s: checking/generating FLUX reference images", job_id)
    cast_bank, location_bank = _generate_flux_images(job_id, bible, cast_bank, location_bank)
    update_job(job_id, cast_bank=cast_bank, location_bank=location_bank)

    # Phase 2: Per-clip script + generate (interleaved, 1 clip at a time)
    voice_bank = job.voice_bank or {}
    prev_clips = []
    for i in range(total_clips):
        clip_obj = job.clips[i] if i < len(job.clips) else None

        # Skip clips that are already completely generated in an earlier run, keeping their script for continuity
        if clip_obj and clip_obj.status == "done" and clip_obj.video_url and clip_obj.movie_script:
            prev_clips.append(clip_obj.movie_script)
            continue

        update_clip(job_id, i, status="generating")

        # If this clip's script was already generated before an interruption, reuse it directly and skip OpenAI!
        if clip_obj and clip_obj.movie_script and isinstance(clip_obj.movie_script, dict) and clip_obj.movie_script.get("location_id"):
            task_log.info("job %s: clip %d script already exists, skipping OpenAI script generation", job_id, i + 1)
            clip_script = clip_obj.movie_script
        else:
            # Script this clip (1 clip per chapter)
            task_log.info("job %s: scripting clip %d of %d", job_id, i + 1, total_clips)
            is_supervise = getattr(job.request, "supervise", False)
            chapter_data, _ = movie.write_chapter(
                topic, i, total_clips, beats, bible, prev_clips, supervise=is_supervise
            )
            clip_script = chapter_data["clips"][0]
            movie._normalize_clips([clip_script], bible)
            update_clip(job_id, i, movie_script=clip_script)

        # Build prompt and render
        prev_clip_script = prev_clips[-1] if prev_clips else None
        prompt, image_urls, audio_urls = movie.build_multi_prompt(
            clip_script, bible, cast_bank, location_bank, voice_bank, prev_clip=prev_clip_script
        )
        task_log.info("job %s: rendering clip %d of %d (%d images, %d audios)",
                      job_id, i + 1, total_clips, len(image_urls), len(audio_urls))
        result = movie.render_clip(i + 1, prompt, image_urls, audio_urls, interactive=False)
        if result == "quit":
            raise RuntimeError(f"clip {i + 1} failed after retries")

        video_url = result["video_url"]
        update_clip(job_id, i, video_url=video_url, status="done", resolution="480p")

        # Voice banking for new speakers
        _bank_new_voices(job_id, i, clip_script, video_url, voice_bank)
        update_job(job_id, voice_bank=voice_bank)

        prev_clips.append(clip_script)
        task_log.info("job %s: clip %d done", job_id, i + 1)


def _generate_narrated_plan(job_id: str) -> None:
    """Phase 1 for Narrated Drama: the Master Plan (bible, acts, beats, and the delivery map of what the spoken script
    must make the audience understand), then a report on whether the script actually delivers it."""
    job = get_job(job_id)
    import hybrid_narrated_drama as hnd
    topic = hnd.topic_with_rules(job.request.topic, job.plan_rules)   # the standing rules ride along with the premise
    total_clips = job.request.num_clips
    task_log.info("job %s: generating narrated drama master plan for %d clips", job_id, total_clips)
    outline, problems = hnd.write_narrated_outline(topic, job.request.duration, total_clips)
    # Only a problem that would break rendering stops the plan. The rules about how the film looks or sounds go to the review
    # gate instead (split_plan_problems), where a person reads them before approving, so a plan that is nearly right is not
    # thrown away together with every planning call already paid for.
    blocking, reviewable = hnd.split_plan_problems(hnd._hard_problems(problems))
    if blocking:
        # Nothing has been paid for yet: FLUX images and clips both come after the plan is approved. Saving
        # the rejected plan for inspection and refusing it here is what keeps a broken plan from becoming a
        # paid run. It is not stored on the job, so it cannot be resumed by accident.
        folder = job_media_dir(job_id)
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "master_plan_rejected.json").write_text(json.dumps(outline, indent=2, ensure_ascii=False), encoding="utf-8")
        raise ValueError(
            "the Master Plan still breaks these rules after retries, so nothing was generated and no credits "
            "were spent (the rejected plan is saved as master_plan_rejected.json):\n- " + "\n- ".join(blocking)
        )
    for p in reviewable:
        task_log.warning("job %s: plan needs your review: %s", job_id, p)
    for p in hnd._soft_problems(problems):
        task_log.warning("job %s: plan note: %s", job_id, p)
    bible = outline["scene_bible"]
    beats = outline["beats"]
    # Every spoken line, not only the key facts, must be plain language a viewer with basic English understands at first
    # hearing: one cheap review per ~15 beats rewrites the ones that are not (and never raises).
    plain = hnd.plain_pass_plan(outline)
    task_log.info("job %s: plain-language review: %d line(s) checked, %d rewritten", job_id, plain["checked"], plain["rewritten"])
    # What the viewer will actually be told, before any credit is spent: the free checks, the spoken-script stats, the
    # dialogue-only page and one cheap blind-reader call. It never fails a plan: a report that cannot run is skipped.
    try:
        report = hnd.plan_delivery_report(outline)
    except Exception as e:
        task_log.warning("job %s: delivery report skipped: %s", job_id, e)
        report = None
    if reviewable:   # shown first in the plan review, before the soft notes
        report = report or {"problems": []}
        report["problems"] = [f"[REVIEW] {p}" for p in reviewable] + list(report.get("problems") or [])
    update_job(job_id, movie_bible=bible, beats=beats, acts=outline.get("acts"),
               delivery=outline.get("delivery"), plan_report=report,
               scene_bible=json.dumps(bible, ensure_ascii=False),
               status="plan_ready")
    _save_master_plan_file(get_job(job_id))
    if report and report.get("stats"):
        stats = report["stats"]
        blind = report.get("blind") or {}
        task_log.info("job %s: delivery report: %d lines, %d words, narration %d%%, blind reader understood %s of %s facts, "
                      "%d note(s)", job_id, stats["spoken_lines"], stats["spoken_words"], int(stats["narration_share"] * 100),
                      blind.get("understood", "-"), blind.get("total", "-"), len(report["problems"]))
    task_log.info("job %s: narrated drama master plan ready (%d beats, protagonist %s)",
                  job_id, len(beats), bible.get("pov_protagonist"))


def _continue_narrated_drama_job(job_id: str) -> None:
    """Phase 1.5: FLUX images -> Phase 2: Narrated drama per-clip (VO / Dialogue / Shock) -> assemble."""
    job = get_job(job_id)
    import hybrid_narrated_drama as hnd
    topic = hnd.topic_with_rules(job.request.topic, job.plan_rules)   # every clip writer sees the standing rules (the same text each clip, so it still caches)
    total_clips = len(job.clips)
    bible = job.movie_bible
    beats = job.beats

    # Phase 1.5: FLUX images
    cast_bank = job.cast_bank or {}
    location_bank = job.location_bank or {}
    task_log.info("job %s: checking/generating FLUX reference images", job_id)
    cast_bank, location_bank = _generate_flux_images(job_id, bible, cast_bank, location_bank)
    update_job(job_id, cast_bank=cast_bank, location_bank=location_bank)

    # Phase 2: Per-clip script + generate
    voice_bank = job.voice_bank or {}
    prev_clips = []
    for i in range(total_clips):
        clip_obj = job.clips[i] if i < len(job.clips) else None
        if clip_obj and clip_obj.status == "done" and clip_obj.video_url and clip_obj.movie_script:
            hnd._normalize_narrated_clip(clip_obj.movie_script, bible)
            prev_clips.append(clip_obj.movie_script)
            continue

        update_clip(job_id, i, status="generating")

        if clip_obj and clip_obj.movie_script and isinstance(clip_obj.movie_script, dict) and clip_obj.movie_script.get("delivery_mode"):
            task_log.info("job %s: clip %d script already exists, skipping OpenAI script generation", job_id, i + 1)
            clip_script = clip_obj.movie_script
            hnd._normalize_narrated_clip(clip_script, bible)
        else:
            task_log.info("job %s: scripting narrated clip %d of %d", job_id, i + 1, total_clips)
            is_supervise = getattr(job.request, "supervise", False)
            ch_data, clip_problems = hnd.write_narrated_chapter(
                topic, i, total_clips, beats, bible, prev_clips, supervise=is_supervise, acts=job.acts
            )
            clip_hard = hnd._hard_problems(clip_problems)
            if clip_hard:
                # Stop before rendering. Earlier clips keep their videos and the job can be resumed, so the
                # cost of stopping is one unrendered clip instead of a whole broken video.
                raise RuntimeError(
                    f"clip {i + 1}'s script still breaks these rules after retries, so it was not rendered:\n- "
                    + "\n- ".join(clip_hard)
                )
            for p in hnd._soft_problems(clip_problems):
                task_log.warning("job %s: clip %d note: %s", job_id, i + 1, p)
            clip_script = ch_data["clips"][0]
            hnd._normalize_narrated_clip(clip_script, bible)
            update_clip(job_id, i, movie_script=clip_script)

        # Build prompt & render
        prev_script = prev_clips[-1] if prev_clips else None
        prompt, img_urls, aud_urls = hnd.build_narrated_prompt(
            clip_script, bible, cast_bank, location_bank, voice_bank, prev_clip=prev_script
        )
        task_log.info("job %s: rendering narrated clip %d of %d [%s] (%d images, %d audios)",
                      job_id, i + 1, total_clips, clip_script.get("delivery_mode"), len(img_urls), len(aud_urls))
        res = hnd.render_narrated_clip(i + 1, prompt, img_urls, aud_urls, interactive=False,
                                       out_dir=job_media_dir(job_id))
        if res == "quit":
            raise RuntimeError(f"narrated clip {i + 1} failed after retries")

        video_url = res["video_url"]
        update_clip(job_id, i, video_url=video_url, status="done", resolution="480p")

        # Bank voice if speaker present
        clip_file = _local_clip_movie(job_id, i, video_url)
        clip_turns = hnd._clip_turns(clip_script)
        banked = False
        for t_idx, turn in enumerate(clip_turns):
            spk = (turn.get("speaker") or "").strip()
            if not spk or spk.lower() in {k.lower() for k in voice_bank}:
                continue
            if not hnd.should_bank_voice(turn, spk, beats, i):
                task_log.info("job %s: clip %d: '%s' line is too short to bank a voice from; waiting for a longer one",
                              job_id, i + 1, spk)
                continue
            s_est = float(turn.get("start_est", 0.5) or 0.5)
            e_est = float(turn.get("end_est", 4.5) or 4.5)
            hnd.bank_voice(clip_file, spk, voice_bank, start_est=s_est, end_est=e_est,
                           turn_index=t_idx, turns=clip_turns)
            banked = True
        if banked:
            update_job(job_id, voice_bank=voice_bank)

        prev_clips.append(clip_script)
        task_log.info("job %s: clip %d done", job_id, i + 1)


# --- Celery Task ---
task_log = get_task_logger(__name__)


def _fail_job(job_id: str, message: str) -> None:
    task_log.error("job %s failed: %s", job_id, message)
    update_job(job_id, status="failed", error=message)


@observe(name="assemble_final_video", as_type="span")
def _assemble(job_id: str) -> None:
    """Build (or rebuild) the job's final video and record it on the job. A failure goes in final_error and removes
    any older final video, which no longer matches the clips; it never fails the job, whose clips are fine. Never
    raises."""
    task_log.info("job %s: joining the clips into the final video", job_id)
    try:
        assemble_final_video(get_job(job_id))
        update_job(job_id, final_video_at=time.time(), final_error=None)
    except Exception as e:
        message = f"{type(e).__name__}: {e}"
        task_log.error("job %s: the final video failed: %s", job_id, message)
        final_video_path(job_id).unlink(missing_ok=True)
        update_job(job_id, final_video_at=None, final_error=message)


@observe(name="assemble_task")
def _assemble_task_traced(job_id: str, **kwargs) -> None:
    try:
        _assemble(job_id)
        update_job(job_id, status="done")
    finally:
        try:
            get_client().flush()
        except Exception:
            pass


@celery_app.task
def assemble_task(job_id: str) -> None:
    """POST /jobs/{job_id}/assemble: build the final video on demand (the endpoint has marked the job generating)."""
    _assemble_task_traced(job_id, langfuse_trace_id=job_id)


def _make_anchors(job_id: str, story: bool, video_url: str) -> None:
    """Store what every later clip is generated from, taken from clip 0's video (see run_generation_job).
    Talking Head: its audio and a muted copy. Story Time: its audio (the narrator's voice) and last frame (the
    main character)."""
    audio = extract_audio(video_url)
    if story:
        image = extract_last_frame(video_url)
        update_job(job_id, anchor_audio_url=audio, anchor_image_url=image, anchor_extracted_at=time.time())
        update_clip(job_id, 0, audio_url=audio, last_frame_url=image)
    else:
        video = mute_video(video_url)
        now = time.time()
        update_job(job_id, anchor_video_url=video, anchor_audio_url=audio, anchor_extracted_at=now)
        update_clip(job_id, 0, audio_url=audio, muted_video_url=video, muted_video_at=now)


def _fresh_anchors(job_id: str) -> Job:
    """The job, with its anchors made again from clip 0's video (which kie.ai keeps 14 days) when they are older than
    ANCHOR_MAX_AGE, since kie.ai deletes uploaded files after 24 hours."""
    job = get_job(job_id)
    if time.time() - (job.anchor_extracted_at or 0) > ANCHOR_MAX_AGE:
        _make_anchors(job_id, job.mode == "story_time", job.clips[0].video_url)
        job = get_job(job_id)
    return job


def _fresh_muted_copy(job_id: str, clip: Clip) -> str:
    """A muted copy of `clip`'s video that kie.ai's file host still has: made again when missing or older than
    ANCHOR_MAX_AGE."""
    if clip.muted_video_url and time.time() - (clip.muted_video_at or 0) <= ANCHOR_MAX_AGE:
        return clip.muted_video_url
    muted = mute_video(clip.video_url)
    update_clip(job_id, clip.index, muted_video_url=muted, muted_video_at=time.time())
    return muted


SCRIPT_FIELDS = ("dialogue", "narration", "visual", "delivery")


def _render_clip(job_id: str, clip: Clip) -> None:
    """Generate one clip from `clip`'s script, with the references its mode uses (see run_generation_job), and
    store the result: the video_url together with the script it was made from, clip 0's anchors, and in Story Time
    a muted copy for the next clip. The video_url is stored the moment it exists, so a failure after that can't lose
    a paid clip. Raises on failure."""
    i = clip.index
    job = get_job(job_id) if i == 0 else _fresh_anchors(job_id)
    story = job.mode == "story_time"
    resolution = job.resolution if story or i > 0 else MASTER_RESOLUTION
    update_clip(job_id, i, resolution=resolution)
    task_log.info("job %s: generating clip %d of %d at %s", job_id, i + 1, len(job.clips), resolution)
    refs = {}
    if i > 0 and story:
        refs = {
            "reference_video_urls": [_fresh_muted_copy(job_id, job.clips[i - 1])],
            "reference_audio_urls": [job.anchor_audio_url],
            "reference_image_urls": [job.anchor_image_url],
        }
    elif i > 0:
        refs = {"reference_video_urls": [job.anchor_video_url], "reference_audio_urls": [job.anchor_audio_url]}
    prompt = clip.custom_prompt or build_clip_prompt(job.mode, job.scene_bible, clip, is_first_clip=(i == 0))
    result = generate_clip(
        prompt,
        resolution,
        duration=job.request.clip_duration,
        generate_audio=True,
        **refs,
    )
    video_url = result["video_url"]
    update_clip(
        job_id, i, video_url=video_url,
        custom_edited=clip.custom_edited,
        custom_prompt=clip.custom_prompt,
        **{f: getattr(clip, f) for f in SCRIPT_FIELDS}
    )
    if i == 0:
        _make_anchors(job_id, story, video_url)
    if story and i < len(job.clips) - 1:  # the muted copy is only ever the NEXT clip's video reference
        update_clip(job_id, i, muted_video_url=mute_video(video_url), muted_video_at=time.time())


@observe(name="generation_job")
def _run_generation_job_traced(job_id: str, **kwargs) -> None:
    job = get_job(job_id)
    if job is None:
        raise KeyError(f"job {job_id} not found")
    try:
        client = get_client()
        client.update_current_span(
            name=f"{job.mode}_generation",
            metadata={
                "job_id": job.id,
                "topic": job.request.topic,
                "duration": job.request.duration,
                "clip_duration": job.request.clip_duration,
                "resolution": job.resolution,
                "mode": job.mode,
            },
            tags=[job.mode, job.resolution],
        )
    except Exception:
        pass

    try:
        story = job.mode == "story_time"

        update_job(job_id, status="generating")
        if job.mode == "narrated_drama":
            try:
                _generate_narrated_plan(job_id)
            except Exception as e:
                _fail_job(job_id, f"Narrated Drama planning failed: {type(e).__name__}: {e}")
            return
        if job.mode == "story_videos":
            try:
                _generate_movie_plan(job_id)
            except Exception as e:
                _fail_job(job_id, f"Story Videos planning failed: {type(e).__name__}: {e}")
            return
        try:
            script = generate_script(job.request.topic, job.request.num_clips, job.mode, job.request.clip_duration)
        except Exception as e:
            _fail_job(job_id, f"script generation failed: {type(e).__name__}: {e}")
            return

        scene_bible = script["scene_bible"]
        if story:
            clips = [
                Clip(index=i, narration=c["narration"], visual=c["visual"], delivery=c["delivery"])
                for i, c in enumerate(script["clips"])
            ]
        else:
            clips = [Clip(index=i, dialogue=c["dialogue"], delivery=c["delivery"]) for i, c in enumerate(script["clips"])]
        update_job(job_id, scene_bible=scene_bible, clips=clips)

        for i, clip in enumerate(clips):
            update_clip(job_id, i, status="generating")
            try:
                _render_clip(job_id, clip)
                update_clip(job_id, i, status="done")
            except Exception as e:
                message = f"{type(e).__name__}: {e}"
                update_clip(job_id, i, status="failed", error=message)
                _fail_job(job_id, f"clip {i + 1} of {len(clips)} failed: {message}")  # numbered from 1, as on the dashboard
                return

        _assemble(job_id)  # the job stays "generating" until the final video is ready (or has failed)
        update_job(job_id, status="done")
        task_log.info("job %s done", job_id)
    finally:
        try:
            get_client().flush()
        except Exception:
            pass


@celery_app.task
def run_generation_job(job_id: str) -> None:
    """Write the script, then generate each clip in order. Traced with Langfuse."""
    _run_generation_job_traced(job_id, langfuse_trace_id=job_id)


@observe(name="execute_movie_job")
def _execute_movie_job_traced(job_id: str, **kwargs) -> None:
    job = get_job(job_id)
    if job is None:
        raise KeyError(f"job {job_id} not found")
    try:
        client = get_client()
        client.update_current_span(
            name="story_videos_execution",
            metadata={
                "job_id": job.id,
                "topic": job.request.topic,
                "duration": job.request.duration,
                "mode": job.mode,
            },
            tags=[job.mode, "execution"],
        )
    except Exception:
        pass
    try:
        if job.mode == "narrated_drama":
            _continue_narrated_drama_job(job_id)
        else:
            _continue_movie_job(job_id)
        _assemble(job_id)
        update_job(job_id, status="done")
        task_log.info("job %s done", job_id)
    except Exception as e:
        _fail_job(job_id, f"{'Narrated Drama' if job.mode == 'narrated_drama' else 'Story Videos'} generation failed: {type(e).__name__}: {e}")
    finally:
        try:
            get_client().flush()
        except Exception:
            pass


@celery_app.task
def execute_movie_job(job_id: str) -> None:
    """Execute the Story Videos / Narrated Drama pipeline after Master Plan approval. Traced with Langfuse.

    One task per job: if another task already holds it (a second Resume, or a second queued copy), this one stops at once
    without touching the job, its status or its clips."""
    try:
        with job_lock(job_id):
            _execute_movie_job_traced(job_id, langfuse_trace_id=job_id)
    except JobBusy:
        task_log.warning("job %s: another task is already running it; this one stops without changing anything", job_id)


@observe(name="extend_movie_plan")
def _extend_movie_plan_task_traced(job_id: str, continuation_prompt: str, additional_duration: int, **kwargs) -> None:
    job = get_job(job_id)
    if job is None or job.mode not in ("story_videos", "narrated_drama"):
        return
    additional_clips = additional_duration // (job.request.clip_duration or 5)
    bible = job.movie_bible or (json.loads(job.scene_bible) if job.scene_bible else {})

    task_log.info("job %s: generating continuation outline for %d new clips", job_id, additional_clips)
    try:
        if job.mode == "narrated_drama":
            import hybrid_narrated_drama as hybrid
            prev_beats = job.beats or []
            outline, problems = hybrid.write_narrated_continuation_outline(
                hybrid.topic_with_rules(job.request.topic, job.plan_rules), continuation_prompt, bible, prev_beats, additional_clips, delivery=job.delivery
            )
            try:  # the new lines get the same plain-language review as the first plan's (never raises)
                hybrid.plain_pass_beats(outline.get("beats", []), bible, job.delivery, start_clip=len(prev_beats) + 1,
                                        prior_beats=prev_beats)
            except Exception as e:
                task_log.warning("job %s: plain-language review of the continuation skipped: %s", job_id, e)
        else:
            prev_clips = [c.movie_script for c in job.clips if c.movie_script]
            outline, problems = movie.write_continuation_outline(
                job.request.topic, continuation_prompt, bible, prev_clips, additional_clips
            )
    except Exception as e:
        task_log.error("job %s: continuation outline failed: %s", job_id, e)
        update_job(job_id, status="done", error=f"Continuation planning failed: {e}")
        return

    updated_bible = outline.get("scene_bible", bible)
    new_beats = outline.get("beats", [])

    all_beats = list(job.beats or [])
    all_beats.extend(new_beats)

    existing_count = len(job.clips)
    clips = list(job.clips)
    for idx in range(len(new_beats)):
        clips.append(Clip(index=existing_count + idx, status="pending"))

    update_job(
        job_id,
        beats=all_beats,
        movie_bible=updated_bible,
        scene_bible=json.dumps(updated_bible, ensure_ascii=False),
        clips=clips,
        status="plan_ready",
        error=None,
    )
    _save_master_plan_file(get_job(job_id))
    task_log.info("job %s: continuation plan ready (%d total beats) - waiting for review", job_id, len(all_beats))
    try:
        get_client().flush()
    except Exception:
        pass


@celery_app.task
def extend_movie_plan_task(job_id: str, continuation_prompt: str, additional_duration: int) -> None:
    """Analyze previous story, generate continuation outline/beats. Traced with Langfuse."""
    _extend_movie_plan_task_traced(job_id, continuation_prompt, additional_duration, langfuse_trace_id=job_id)


# --- Plan revision (Narrated Drama): the user reads the plan and asks for changes before approving it ---
def _versions_key(job_id: str) -> str:
    return f"jobplanv:{job_id}"


def _plan_versions(job_id: str) -> list[dict]:
    """Earlier versions of the plan, newest last (at most PLAN_VERSIONS_KEPT). Kept beside the job, not in it, so the dashboard's
    polling does not carry copies of every plan on each request."""
    raw = redis_client.get(_versions_key(job_id))
    return json.loads(raw) if raw else []


def _set_plan_versions(job_id: str, versions: list[dict]) -> None:
    if versions:
        redis_client.set(_versions_key(job_id), json.dumps(versions[-PLAN_VERSIONS_KEPT:], ensure_ascii=False))
    else:
        redis_client.delete(_versions_key(job_id))


PLAN_VERSIONS_KEPT = 5


def _revision_busy(job: Job) -> bool:
    return bool(job.revision and job.revision.get("status") in ("proposing", "applying"))


def _fail_revision(job_id: str, note: str, error: str) -> None:
    task_log.error("job %s: plan revision failed: %s", job_id, error)
    update_job(job_id, revision={"status": "failed", "note": note, "error": error, "at": time.time()})


def _propose_revision(job_id: str) -> None:
    """Step one: split the note and find the clips it touches. Changes nothing in the plan."""
    import hybrid_narrated_drama as hnd
    job = get_job(job_id)
    rev = (job.revision if job else None) or {}
    if job is None or rev.get("status") != "proposing" or job.status != "plan_ready":
        return
    try:
        result = hnd.propose_plan_revision(rev.get("note", ""), job.plan_rules, job.beats or [], job.acts, job.movie_bible or {},
                                           premise=job.request.topic)
        update_job(job_id, revision={
            "status": "proposed", "note": rev.get("note", ""), "items": result["items"], "rules_new": result["rules_new"],
            "replaces": result["replaces"], "blocked": result["blocked"], "rules_new_hints": result.get("rules_new_hints", []),
            "rules_new_meta": result.get("rules_new_meta", []),
            # a clip the scan is sure of (score 2 or 3) comes ticked; a "maybe" (1) is listed unticked for the user to decide
            "clips": [{**c, "selected": c.get("score", hnd.PICK_SCORE) >= hnd.PICK_SCORE} for c in result["clips"]], "at": time.time(),
        })
        task_log.info("job %s: plan revision proposed: %d item(s), %d clip(s) to change", job_id, len(result["items"]), len(result["clips"]))
    except Exception as e:
        _fail_revision(job_id, rev.get("note", ""), f"{type(e).__name__}: {e}")


def _apply_revision(job_id: str, chosen: list[int]) -> None:
    """Step two: rewrite the clips the user ticked (story model), check them, save a version to undo to, and report what changed."""
    import hybrid_narrated_drama as hnd
    job = get_job(job_id)
    rev = (job.revision if job else None) or {}
    if job is None or rev.get("status") != "applying" or job.status != "plan_ready":
        return
    note = rev.get("note", "")
    try:
        proposal = {c["clip"]: c for c in rev.get("clips") or []}
        selected = {n: proposal[n].get("change", "") for n in chosen if n in proposal}
        replaces = set(rev.get("replaces") or [])
        new_texts = rev.get("rules_new") or []
        new_hints = list(rev.get("rules_new_hints") or []) + [""] * len(new_texts)   # a rule keeps the tells, the probe and the stop point the scan used
        new_meta = list(rev.get("rules_new_meta") or []) + [{}] * len(new_texts)
        final_rules = hnd.clean_rules([r for r in hnd.clean_rules(job.plan_rules) if r["id"] not in replaces]
                                      + [{"text": t, "hint": new_hints[i], "probe": new_meta[i].get("probe", ""),
                                          "stops_when": new_meta[i].get("stops_when", "")} for i, t in enumerate(new_texts)])
        instructions = [hnd.item_instruction(i) for i in rev.get("items") or [] if i.get("in_scope")]
        if selected:
            result = hnd.apply_plan_revision(selected, instructions, final_rules, job.beats, job.movie_bible, job.delivery, job.acts)
        else:
            result = {"beats": job.beats, "changed": [], "unresolved": [], "notes": []}
        new_beats = result["beats"]
        try:   # what still contradicts a rule: reported, never fixed on its own
            contradictions = hnd.verify_plan_revision(final_rules, new_beats, job.acts)
        except Exception as e:
            task_log.warning("job %s: the final rule check could not run: %s", job_id, e)
            contradictions = []
        report = job.plan_report
        if result["changed"]:
            try:
                fresh = hnd.plan_delivery_report({"scene_bible": job.movie_bible, "acts": job.acts, "beats": new_beats, "delivery": job.delivery})
                kept = [p for p in ((job.plan_report or {}).get("problems") or []) if p.startswith("[REVIEW] ") and not p.startswith("[REVIEW] Cast: ")]
                fresh["problems"] = kept + list(fresh.get("problems") or [])
                fresh["plain_pass"] = (job.plan_report or {}).get("plain_pass")
                report = fresh
            except Exception as e:
                task_log.warning("job %s: the plan report could not be rebuilt: %s", job_id, e)
        versions = _plan_versions(job_id) + [{"id": uuid.uuid4().hex[:8], "at": time.time(), "label": note[:100], "beats": job.beats,
                                              "plan_report": job.plan_report, "plan_rules": job.plan_rules, "movie_bible": job.movie_bible}]
        _set_plan_versions(job_id, versions)
        update_job(job_id, beats=new_beats, plan_report=report, plan_rules=final_rules,
                   plan_versions_count=min(len(versions), PLAN_VERSIONS_KEPT),
                   revision={"status": "applied", "note": note, "changed": result["changed"], "unresolved": result["unresolved"],
                             "notes": result["notes"], "contradictions": contradictions, "rules_saved": [r["text"] for r in final_rules],
                             "at": time.time()})
        _save_master_plan_file(get_job(job_id))
        task_log.info("job %s: plan revision applied: %d clip(s) changed, %d unresolved, %d still contradicting a rule",
                      job_id, len(result["changed"]), len(result["unresolved"]), len(contradictions))
    except Exception as e:
        _fail_revision(job_id, note, f"{type(e).__name__}: {e}")


def _propose_cast(job_id: str) -> None:
    """Cast check, step one: who does the plan show on screen without casting them? Changes nothing in the plan."""
    import hybrid_narrated_drama as hnd
    job = get_job(job_id)
    rev = (job.revision if job else None) or {}
    if job is None or rev.get("kind") != "cast" or rev.get("status") != "proposing" or job.status != "plan_ready":
        return
    try:
        gaps = hnd.find_cast_gaps(job.beats or [], job.movie_bible or {})
        update_job(job_id, revision={
            "kind": "cast", "status": "proposed", "people": [{**g, "include": True} for g in gaps],
            "supporting_now": sum(1 for c in (job.movie_bible or {}).get("characters", []) if hnd._is_supporting(c)),
            "max_supporting": hnd.MAX_SUPPORTING, "at": time.time(),
        })
        task_log.info("job %s: cast check found %d person(s) shown on screen without being cast", job_id, len(gaps))
    except Exception as e:
        _fail_revision(job_id, "cast check", f"{type(e).__name__}: {e}")


def _apply_cast(job_id: str, people: list[dict]) -> None:
    """Cast check, step two: write looks for the people the user kept, add them to the cast, put them in the clips they belong in,
    save a version to undo to (it carries the old cast), and rebuild the plan report."""
    import hybrid_narrated_drama as hnd
    job = get_job(job_id)
    rev = (job.revision if job else None) or {}
    if job is None or rev.get("kind") != "cast" or rev.get("status") != "applying" or job.status != "plan_ready":
        return
    try:
        result = hnd.add_supporting_cast(people, job.beats, job.movie_bible)
        report = job.plan_report
        try:
            fresh = hnd.plan_delivery_report({"scene_bible": result["bible"], "acts": job.acts, "beats": result["beats"], "delivery": job.delivery})
            kept = [p for p in ((job.plan_report or {}).get("problems") or []) if p.startswith("[REVIEW] ") and not p.startswith("[REVIEW] Cast: ")]
            fresh["problems"] = kept + list(fresh.get("problems") or [])
            fresh["plain_pass"] = (job.plan_report or {}).get("plain_pass")
            report = fresh
        except Exception as e:
            task_log.warning("job %s: the plan report could not be rebuilt: %s", job_id, e)
        label = "Added to the cast: " + ", ".join(a["name"] for a in result["added"])
        versions = _plan_versions(job_id) + [{"id": uuid.uuid4().hex[:8], "at": time.time(), "label": label[:100], "beats": job.beats,
                                              "plan_report": job.plan_report, "plan_rules": job.plan_rules, "movie_bible": job.movie_bible}]
        _set_plan_versions(job_id, versions)
        update_job(job_id, movie_bible=result["bible"], scene_bible=json.dumps(result["bible"], ensure_ascii=False), beats=result["beats"],
                   plan_report=report, plan_versions_count=min(len(versions), PLAN_VERSIONS_KEPT),
                   revision={"kind": "cast", "status": "applied", "added": result["added"], "notes": result["notes"], "at": time.time()})
        _save_master_plan_file(get_job(job_id))
        task_log.info("job %s: %d supporting character(s) added to the cast", job_id, len(result["added"]))
    except Exception as e:
        _fail_revision(job_id, "cast check", f"{type(e).__name__}: {e}")


@observe(name="plan_revision")
def _plan_revision_traced(job_id: str, step: str, chosen: list[int] | None = None, people: list[dict] | None = None, **kwargs) -> None:
    """Run one step of a plan revision under the JOB's Langfuse trace (the trace id is the job id, as for every other task), so
    its calls sit with the planning and clip-scripting calls of the same job, and flush before the worker moves on: the Celery
    child processes would otherwise keep the events in a buffer."""
    try:
        get_client().update_current_span(
            name=f"plan_revision_{step}",
            metadata={"job_id": job_id, "step": step, "clips": chosen or []},
            tags=["narrated_drama", "plan_revision", step],
        )
    except Exception:
        pass
    try:
        if step == "propose":
            _propose_revision(job_id)
        elif step == "cast_propose":
            _propose_cast(job_id)
        elif step == "cast_apply":
            _apply_cast(job_id, people or [])
        else:
            _apply_revision(job_id, chosen or [])
    finally:
        try:
            get_client().flush()
        except Exception:
            pass


@celery_app.task
def propose_plan_revision_task(job_id: str) -> None:
    """Find the clips a revision note touches (cheap model, in windows). One task per job (see job_lock). Traced with Langfuse."""
    try:
        with job_lock(job_id):
            _plan_revision_traced(job_id, "propose", langfuse_trace_id=job_id)
    except JobBusy:
        task_log.warning("job %s: another task holds this job; the revision proposal stops without changing anything", job_id)


@celery_app.task
def propose_cast_additions_task(job_id: str) -> None:
    """Find the people the plan shows on screen without casting them (cheap model). One task per job (see job_lock). Traced with Langfuse."""
    try:
        with job_lock(job_id):
            _plan_revision_traced(job_id, "cast_propose", langfuse_trace_id=job_id)
    except JobBusy:
        task_log.warning("job %s: another task holds this job; the cast check stops without changing anything", job_id)


@celery_app.task
def apply_cast_additions_task(job_id: str, people: list) -> None:
    """Add the chosen people to the cast and to their clips. One task per job (see job_lock). Traced with Langfuse."""
    try:
        with job_lock(job_id):
            _plan_revision_traced(job_id, "cast_apply", people=people, langfuse_trace_id=job_id)
    except JobBusy:
        task_log.warning("job %s: another task holds this job; the cast change stops without changing anything", job_id)


@celery_app.task
def apply_plan_revision_task(job_id: str, chosen: list[int]) -> None:
    """Rewrite the ticked clips (story model) and check them. One task per job (see job_lock). Traced with Langfuse."""
    try:
        with job_lock(job_id):
            _plan_revision_traced(job_id, "apply", chosen, langfuse_trace_id=job_id)
    except JobBusy:
        task_log.warning("job %s: another task holds this job; the revision stops without changing anything", job_id)


REGENERATE_LABELS = {"script": "Regenerate Script", "scene": "Regenerate Scene"}


def _render_movie_clip_at(job_id: str, clip: Clip) -> None:
    job = get_job(job_id)
    bible = job.movie_bible or (json.loads(job.scene_bible) if job.scene_bible else {})
    cast_bank = job.cast_bank or {}
    location_bank = job.location_bank or {}
    voice_bank = job.voice_bank or {}
    clip_script = clip.movie_script
    prev_clip_script = job.clips[clip.index - 1].movie_script if (clip.index > 0 and clip.index - 1 < len(job.clips)) else None
    prompt, image_urls, audio_urls = movie.build_multi_prompt(
        clip_script, bible, cast_bank, location_bank, voice_bank, prev_clip=prev_clip_script
    )
    if clip.custom_prompt:
        prompt = clip.custom_prompt
    result = movie.render_clip(clip.index + 1, prompt, image_urls, audio_urls, interactive=False)
    if result == "quit":
        raise RuntimeError(f"clip {clip.index + 1} failed after retries")
    video_url = result["video_url"]
    update_clip(
        job_id, clip.index, video_url=video_url, resolution="480p",
        movie_script=clip_script,
        custom_edited=clip.custom_edited,
        custom_prompt=clip.custom_prompt
    )
    _bank_new_voices(job_id, clip.index, clip_script, video_url, voice_bank)
    update_job(job_id, voice_bank=voice_bank)


@celery_app.task
def regenerate_script_task(job_id: str, clip_index: int, overrides: dict | None = None) -> None:
    """Regenerate Script (Prompt 9): a new line for the clip (Talking Head: dialogue and delivery; Story Time:
    narration and delivery, keeping its visual), then the clip rendered again from it. See _regenerate()."""
    _regenerate(job_id, clip_index, "script", overrides, langfuse_trace_id=job_id)


@celery_app.task
def regenerate_scene_task(job_id: str, clip_index: int, overrides: dict | None = None) -> None:
    """Regenerate Scene (Prompt 10): the clip's words stay as they are. Talking Head: a new take of the clip from the
    same line. Story Time: a new visual (a different scene for the same narration), then the clip rendered from it.
    See _regenerate()."""
    _regenerate(job_id, clip_index, "scene", overrides, langfuse_trace_id=job_id)


@observe(name="regenerate_clip")
def _regenerate(job_id: str, clip_index: int, action: str, overrides: dict | None = None, **kwargs) -> None:
    """Regenerate one clip (the LAST clip only for now), with the same references as run_generation_job.

    The endpoint has already marked the job and the clip "generating". The clip keeps its old script and video until
    the new video exists; if anything fails, it keeps whatever it has and the error is recorded on the clip and the
    job, which goes back to "done" (or "failed" if a clip still has no video). After a success the final video is
    built again. Never raises.
    """
    job = get_job(job_id)
    label = REGENERATE_LABELS[action]
    try:
        client = get_client()
        client.update_current_span(
            name=f"regenerate_{action}_clip_{clip_index + 1}",
            metadata={"job_id": job_id, "clip_index": clip_index, "action": action},
            tags=[job.mode if job else "unknown", f"regenerate_{action}"],
        )
    except Exception:
        pass
    try:
        clip = job.clips[clip_index]
        if overrides:
            fields = {k: v for k, v in overrides.items() if hasattr(clip, k) and v is not None}
            if fields:
                clip = clip.model_copy(update=fields)

        is_custom = clip.custom_edited or bool(clip.custom_prompt) or bool(overrides)

        if is_custom:
            task_log.info("job %s: clip %d is custom edited — preserving user text without OpenAI rewrite", job_id, clip_index + 1)
        else:
            if action == "script":
                if job.mode == "story_videos":
                    chapter_data, _ = movie.write_chapter(
                        job.request.topic, clip_index, job.request.num_clips, job.beats, job.movie_bible,
                        [c.movie_script for c in job.clips[:clip_index] if c.movie_script], supervise=False
                    )
                    new_script = chapter_data["clips"][0]
                    movie._normalize_clips([new_script], job.movie_bible)
                    clip = clip.model_copy(update={"movie_script": new_script})
                else:
                    clip = clip.model_copy(update=regenerate_line(job, clip_index))
            elif action == "scene":
                if job.mode == "story_time":
                    clip = clip.model_copy(update=regenerate_visual(job, clip_index))

        if job.mode == "story_videos":
            _render_movie_clip_at(job_id, clip)
        else:
            _render_clip(job_id, clip)
        update_clip(job_id, clip_index, status="done", error=None)
        _assemble(job_id)  # the final video now has to show the new clip
        update_job(job_id, status="done", error=None)
        task_log.info("job %s: %s finished for clip %d", job_id, label, clip_index + 1)
    except Exception as e:
        message = f"{label} for clip {clip_index + 1} failed: {type(e).__name__}: {e}"
        task_log.error("job %s: %s", job_id, message)
        has_video = bool(get_job(job_id).clips[clip_index].video_url)
        job = update_clip(job_id, clip_index, status="done" if has_video else "failed", error=message)
        update_job(job_id, status="done" if all(c.status == "done" for c in job.clips) else "failed", error=message)
    finally:
        try:
            get_client().flush()
        except Exception:
            pass


# --- FastAPI App & Routes ---
app = FastAPI(title="AI Video Extender")
DASHBOARD = Path(__file__).with_name("dashboard.html")


@app.get("/", include_in_schema=False)
def dashboard() -> FileResponse:
    """The single-page dashboard (plain HTML/JS); it talks to POST /jobs and GET /jobs/{job_id}."""
    return FileResponse(
        DASHBOARD,
        media_type="text/html",
        headers={"Cache-Control": "no-cache, no-store, must-revalidate, max-age=0"},
    )


@app.get("/health")
def health():
    return {"status": "ok"}


def _enhance_prompts(topic: str, req: EnhancePromptRequest) -> tuple[str, str]:
    """The (system, user) messages for /enhance-prompt. A pure function, so the wording can be checked without
    calling OpenAI.

    The dramatic modes (everything except Talking Head and Story Time) are told the runtime is EPISODE ONE of a
    longer story: write only as many events as will genuinely play, and end on a cliffhanger. Writing a complete
    arc with a resolution is how a 20-minute plot ended up squeezed into 5 minutes, and "reported" instead of played."""
    duration = req.duration or 30
    clip_duration = req.clip_duration or 5
    num_clips = max(1, duration // clip_duration)
    import hybrid_narrated_drama as _hnd  # lazy: it imports this module
    dramatic = req.mode not in ("talking_head", "story_time")
    # A plan of CONCLUDE_AT_SECONDS (30 minutes) or more tells a whole story and ends it; a shorter one is episode one.
    episode_one = dramatic and duration < _hnd.CONCLUDE_AT_SECONDS

    if req.mode == "talking_head":
        mode_directive = (
            "- MODE: Talking Head video (one person speaking directly to camera with natural lip sync).\n"
            "Establish the speaker's name, personality/costume, specific indoor setting, and write their continuous spoken monologue "
            "with natural emotion, vivid personal anecdotes, and exact spoken words in quotes."
        )
    elif req.mode == "story_time":
        mode_directive = (
            "- MODE: Story Time video (dynamic changing scenes guided by voiceover narration).\n"
            "Establish character visual appearance, specific physical environments across cuts, concrete visual actions, "
            "and the voiceover narrative text."
        )
    elif req.mode == "narrated_drama":
        mode_directive = (
            "- MODE: Narrated Drama (the protagonist's first-person voiceover over live dramatic scenes with spoken dialogue).\n"
            "Establish the protagonist and their voice. Focus on physical staging, character interactions, tangible environmental props, "
            "exact spoken dialogue in quotes, and the protagonist's own first-person voiceover lines in quotes, each marked (VO)."
        )
    else:  # story_videos (default)
        mode_directive = (
            "- MODE: Story Videos cinematic drama (multi-character dramatic scenes with physical acting, blocking, props, and dialogue).\n"
            "Focus on physical staging, character interactions, tangible environmental props, and exact spoken dialogue."
        )

    # The planner that reads this premise must be able to make the audience UNDERSTAND the story from the spoken script
    # alone, so the premise states what the story is in plain spoken terms (not only moods and images).
    if req.mode == "narrated_drama":
        thoughts_rule = (
            "   - NEVER write abstract emotional summaries (e.g. BANNED: 'she feels heartbroken', 'a devastating truth', 'every relationship is doomed to slip away'). "
            "The protagonist's inner thoughts may appear ONLY as first-person voiceover lines in quotes marked (VO): plain words that state a want, a decision, a cost or a secret. "
            "An AI camera still films only physical things.\n"
        )
    else:
        thoughts_rule = (
            "   - NEVER write abstract emotional summaries or internal thoughts (e.g. BANNED: 'she feels heartbroken', 'a devastating truth', 'wonders if it is a dream', 'every relationship is doomed to slip away'). "
            "An AI camera CANNOT film internal thoughts or generic summaries!\n"
        )
    delivery_rule = (
        "   - STORY DELIVERY: a viewer who only HEARS the film must be able to retell it. In quotes, have the characters state plainly - inside the conflict - "
        "what the protagonist wants, what stands in the way, what is at stake, the key backstory, and any lie or secret (say THAT a secret exists early; reveal WHAT it is later). "
        "Explain any special term (a family name, a legal word, a place) in plain words the first time it is spoken. Quiet or stoic characters still say what the story is; only HOW they say it is restrained.\n"
        "   - PLAIN LANGUAGE: write EVERY spoken line and voiceover line in plain, literal English that a viewer with basic English understands the first time they hear it: "
        "no metaphors, similes, idioms or poetic images, and no sample line should be copied if it is poetic (say its meaning plainly). Sharp or witty lines are welcome as long as they are literal and plain. When a character does something meaningful "
        "(returns a ring, signs, hands something over, walks out), have a line say what it means.\n"
        if dramatic else ""
    )

    if duration <= 45:
        p1_end = max(10, round(duration * 0.5))
        pacing_directive = (
            f"6. DURATION-CALIBRATED 2-ACT PROGRESSION ({num_clips} CLIPS, {duration}s):\n"
            f"   Even in a compact {duration}s scene, write rich cinematic drama with concrete staging, tangible props, and exact spoken dialogue in quotes.\n"
            f"   Structure into exactly 2 high-impact Acts:\n"
            f"   * ACT 1: THE DISRUPTION (0–{p1_end}s): Second-0 physical staging and action, sudden catalyst/arrival, initial shock, and sharp spoken confrontation in quotes.\n"
            f"   * ACT 2: THE CONFRONTATION & CLIMAX ({p1_end}–{duration}s): Escalating tension, tangible physical proof, sharp retort/ultimatum in quotes, and a decisive turning point or cliffhanger.\n"
            f"7. FORMAT & DIALOGUE DENSITY:\n"
            f"   - Format with clear Act headings: 'ACT 1: ...', 'ACT 2: ...'.\n"
            f"   - STRICT BAN ON CLIP LISTS: NEVER output 'Clip 1:', 'Clip 2:', or pre-chopped clip lists! Write immersive narrative paragraphs under each Act heading.\n"
            f"   - DIALOGUE IN QUOTES: Every Act MUST contain 2 to 4 exact, punchy spoken lines of dialogue in quotation marks."
        )
    elif duration <= 90:
        p1_end = max(15, round(duration * 0.33))
        p2_end = max(p1_end + 15, round(duration * 0.67))
        pacing_directive = (
            f"6. DURATION-CALIBRATED 3-ACT PROGRESSION ({num_clips} CLIPS, {duration}s):\n"
            f"   Develop an escalating dramatic sequence across 3 defined Acts with rich physical staging, tangible props, and dense dialogue in quotes:\n"
            f"   * ACT 1: THE INCITING DISRUPTION (0–{p1_end}s): Concrete physical staging at second 0, sudden catalyst/arrival, initial shock, and opening dialogue clash in quotes.\n"
            f"   * ACT 2: THE RISING CONFLICT & TANGIBLE PROOF ({p1_end}–{p2_end}s): Deepening stakes, tactical pushback, discovery of physical evidence or proof, and high-density verbal sparring in quotes.\n"
            f"   * ACT 3: THE CLIMAX & IRREVERSIBLE TURN ({p2_end}–{duration}s): The confrontation reaches its peak, decisive physical/dramatic action, irreversible choice, and " + ("a consequence that is only beginning, with the next question left open" if episode_one else "dramatic consequence") + ".\n"
            f"7. FORMAT & DIALOGUE DENSITY:\n"
            f"   - Format with clear Act headings: 'ACT 1: ...', 'ACT 2: ...', 'ACT 3: ...'.\n"
            f"   - STRICT BAN ON CLIP LISTS: NEVER output 'Clip 1:', 'Clip 2:', or pre-chopped clip lists! Write immersive narrative paragraphs under each Act heading.\n"
            f"   - DIALOGUE IN QUOTES: Every Act MUST contain 2 to 4 exact, punchy spoken lines of dialogue in quotation marks."
        )
    else:
        if episode_one:
            progression = (
                "You MUST advance the story across progressive locations through a 4-Act progression - but this runtime is EPISODE ONE of a longer story, "
                "NOT a whole film. Write only as many major events as can genuinely PLAY in the runtime (about one per 60 seconds, each staged between people "
                "in a room with room for its dialogue), and do NOT compress or summarise further events to reach an ending. Whatever does not fit belongs to the next episode:\n"
            )
            act4 = ("     * ACT 4 (The Cliffhanger): The episode's strongest turn lands and is left OPEN - a reveal, a threat arriving, an arrival or a choice "
                    "still undecided. NO resolution, no wrap-up, no closing line, no moral.\n")
        else:
            progression = "You MUST advance the story into a complete 4-Act cinematic progression across progressive locations that fills the entire runtime:\n"
            act4 = "     * ACT 4 (The Climax & Resolution): High-stakes physical confrontation, decisive turning point, and a satisfying, memorable resolution.\n"
        pacing_directive = (
            f"6. DURATION-CALIBRATED 4-ACT MULTI-SEQUENCE STRUCTURE ({num_clips} CLIPS, {duration}s):\n"
            f"   - DO NOT trap characters in one room or stretch the opening scene! The user premise is ONLY the opening incident (Act 1). "
            f"{progression}"
            f"     * ACT 1 (The Inciting Disruption): The opening catalyst, immediate tension, and dramatic hook.\n"
            f"     * ACT 2 (The Escalation / Rising Stakes): Moving to a new location, uncovering new complications, facing escalating pressure or pursuit.\n"
            f"     * ACT 3 (The Discovery / Key Confrontation): Interacting with an ally, rival, or key figure, packed with sharp, snappy back-and-forth dialogue in quotes!\n"
            f"{act4}"
            f"7. FORMAT & DIALOGUE DENSITY:\n"
            f"   - Format with clear Act headings: 'ACT 1: ...', 'ACT 2: ...', 'ACT 3: ...', 'ACT 4: ...' (300 to 500 words).\n"
            f"   - STRICT BAN ON CLIP LISTS: NEVER output 'Clip 1:', 'Clip 2:', or pre-chopped clip lists! Write immersive narrative paragraphs under each Act heading.\n"
            f"   - DIALOGUE IN QUOTES: Across every act (especially Act 3), include frequent, sharp, witty or intense dialogue lines in quotation marks so there is zero dead-air or dragging!"
        )

    system_prompt = (
        f"You are an expert cinematic screenwriter converting a raw user story idea into a concrete, production-ready screenplay premise for an AI video generator.\n"
        f"The resulting video is exactly {duration} seconds long ({num_clips} clips of {clip_duration}s each).\n"
        f"{mode_directive}\n\n"
        f"CRITICAL DIRECTIVES FOR ADDING REAL CINEMATIC DETAILS:\n"
        f"1. CONCRETE FILMABLE REALITY ONLY (STRICTLY BAN NOVELISTIC FLUFF):\n"
        f"{thoughts_rule}"
        f"   - EVERYTHING MUST BE PHYSICALLY VISIBLE OR AUDIBLE: Describe physical actions, bodily reactions, tangible props, and environmental details that an actor can perform and a camera can capture.\n"
        f"2. SPECIFIC CHARACTER NAMES & STARTING ACTION:\n"
        f"   - Assign concrete, realistic names to unnamed characters.\n"
        f"   - Establish the specific physical setting and what the character is physically doing at second 0 based on the user's premise.\n"
        f"3. EXACT SPOKEN DIALOGUE IN QUOTES (HIGH DENSITY):\n"
        f"   - Include snappy, dramatic lines of spoken dialogue in quotation marks matching the genre and characters. In dialogue scenes, write sharp back-and-forth lines between characters so the scene is alive with speech.\n"
        f"{delivery_rule}"
        f"4. TANGIBLE PROPS & PHYSICAL PROOF:\n"
        f"   - Include real physical props and visible manifestations of the conflict that fit the user's world (e.g. dropped objects, slammed doors, drawn tools, cracked screens, glowing artifacts).\n"
        f"5. STRICT CHRONOLOGICAL CONTINUITY (NO EVENT REPETITION):\n"
        f"   - Every action, arrival, phone alert, and physical event MUST occur in strict chronological sequence. NEVER repeat the same arrival, same notification buzz, or same action across different acts.\n"
        f"{pacing_directive}\n"
        f"   - Do NOT use technical script headers like 'INT./EXT.' or camera instructions like 'the camera pans' or 'we see'."
    )

    user_content = f"User Premise: {topic}\nTarget Runtime: {duration} seconds ({num_clips} clips)"
    if duration >= 100:
        last_act = ("Act 4 (The Cliffhanger - the episode's strongest turn, left OPEN, with no resolution)" if episode_one
                    else "Act 4 (The Climax & Resolution)")
        user_content += (
            f"\n\nCRITICAL MULTI-ACT DIRECTIVE: The user premise above is ONLY the opening inciting incident (Act 1)! "
            f"Because the target duration is {duration} seconds ({num_clips} clips), you MUST actively continue the story forward across all acts. "
            f"Do NOT stop at the opening scene! Progress the narrative through Act 2 (The Escalation), Act 3 (The Discovery/Confrontation with rapid snappy dialogue), "
            f"and {last_act}, introducing where the characters go next, who they encounter, and exact spoken dialogue lines in quotes. "
            f"STRICTLY format with clear Act headings ('ACT 1: ...', 'ACT 2: ...', 'ACT 3: ...', 'ACT 4: ...') — NEVER output 'Clip 1:', 'Clip 2:' lists!"
        )
    else:
        user_content += (
            f"\n\nCRITICAL DIRECTIVE: Format strictly with clear Act headings ('ACT 1: ...', 'ACT 2: ...'). "
            f"NEVER output 'Clip 1:', 'Clip 2:', or numbered clip lists! Write rich narrative paragraphs with exact quoted dialogue."
        )

    return system_prompt, user_content


@app.post("/enhance-prompt", response_model=EnhancePromptResponse)
@observe(name="enhance_prompt")
def enhance_prompt_endpoint(req: EnhancePromptRequest) -> EnhancePromptResponse:
    """Enhance and expand a short story premise into a rich, cinematic screenplay synopsis tailored to the selected duration."""
    topic = req.topic.strip()
    if not topic:
        raise HTTPException(status_code=400, detail="topic cannot be empty")
    if not OPENAI_API_KEY:
        raise HTTPException(status_code=500, detail="OPENAI_API_KEY is not configured")
    system_prompt, user_content = _enhance_prompts(topic, req)

    try:
        client = OpenAI(api_key=OPENAI_API_KEY, timeout=60)
        response = client.chat.completions.create(
            name="enhance_prompt",
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content}
            ],
        )
        enhanced = response.choices[0].message.content.strip()
        if enhanced.startswith('"') and enhanced.endswith('"'):
            enhanced = enhanced[1:-1].strip()
        return EnhancePromptResponse(enhanced_topic=enhanced)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"OpenAI enhancement failed: {e}")
    finally:
        try:
            get_client().flush()
        except Exception:
            pass


@app.post("/jobs", status_code=201)
def create_job(request: ClipRequest) -> dict:
    """Store a new job (mode, resolution and clip length from the request) and start generating it in the background.

    Returns the job id to poll with GET /jobs/{job_id}. The job starts with one pending placeholder clip per clip in
    the request, so the dashboard can show them before the script exists; the task fills them in. An invalid request
    is rejected with a 422 before anything is stored.
    """
    job = Job(
        request=request,
        resolution=request.resolution,
        mode=request.mode,
        clips=[Clip(index=i) for i in range(request.num_clips)],
    )
    job.langfuse_url = get_langfuse_trace_url(job.id)
    save_job(job)
    try:
        run_generation_job.delay(job.id)
    except Exception as e:  # the broker didn't take it: without this the job would sit "pending" forever
        _fail_job(job.id, f"could not queue the job: {type(e).__name__}: {e}")
        raise HTTPException(status_code=503, detail="could not queue the job; try again") from e
    return {"job_id": job.id, "langfuse_url": job.langfuse_url}


@app.get("/jobs/{job_id}")
def read_job(job_id: str) -> Job:
    """The job's full current state: status, error, scene bible, anchors, and every clip with its status and URLs."""
    job = get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return job


def _require_clip(job_id: str, clip_index: int) -> Job:
    """The job, or a 404 if it or its clip `clip_index` (0-based, as in Job.clips) doesn't exist."""
    job = get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    if not 0 <= clip_index < len(job.clips):
        raise HTTPException(status_code=404, detail=f"no clip at index {clip_index}: the job has clips 0 to {len(job.clips) - 1}")
    return job


def _claim_job(job_id: str, clip_index: int | None = None) -> Job:
    """Mark the job "generating" in one step (and the clip too, for a regeneration), so a second click can't start a
    second run, or raise 409 if the job is still generating or a clip it needs isn't done: the clips before
    `clip_index` for a regeneration, every clip for the final video. Returns the job as it was."""
    key = _job_key(job_id)

    def apply(pipe):
        before = Job.model_validate_json(pipe.get(key))
        if before.status in ("pending", "generating"):
            raise HTTPException(status_code=409, detail="the job is still generating; wait until it has finished")
        if clip_index is None and any(c.status != "done" for c in before.clips):
            raise HTTPException(status_code=409, detail="every clip must be done before the final video can be made")
        if clip_index is not None and any(c.status != "done" for c in before.clips[:clip_index]):
            raise HTTPException(status_code=409, detail="an earlier clip isn't done, so this one can't be regenerated")
        job = before.model_copy(deep=True)
        job.status = "generating"
        if clip_index is not None:
            job.error = None
            job.clips[clip_index].status, job.clips[clip_index].error = "generating", None
        pipe.multi()
        pipe.set(key, job.model_dump_json())
        return before

    return redis_client.transaction(apply, key, value_from_callable=True)


def _start_regeneration(job_id: str, clip_index: int, task, overrides: dict | None = None) -> dict:
    """Shared by both regenerate endpoints: only the LAST clip for now (501 for any other), claim the job, queue the
    task, and return 202's body. Poll GET /jobs/{job_id}: the job and the clip show "generating", then "done" with
    the new clip (or the error, with the old clip kept)."""
    job = _require_clip(job_id, clip_index)
    if job.mode in ("story_videos", "narrated_drama"):
        raise HTTPException(status_code=501, detail=f"regeneration is not yet available for {job.mode.replace('_', ' ')}")
    if clip_index != len(job.clips) - 1:
        raise HTTPException(status_code=501, detail="mid-sequence regeneration not yet implemented")
    if overrides:
        fields = {k: v for k, v in overrides.items() if hasattr(job.clips[clip_index], k) and v is not None}
        if fields:
            update_clip(job_id, clip_index, **fields)
    before = _claim_job(job_id, clip_index)
    try:
        task.delay(job_id, clip_index, overrides)
    except Exception as e:  # the broker didn't take it: put the job back as it was
        old = before.clips[clip_index]
        update_clip(job_id, clip_index, status=old.status, error=old.error)
        update_job(job_id, status=before.status, error=before.error)
        raise HTTPException(status_code=503, detail="could not queue the regeneration; try again") from e
    return {"job_id": job_id, "clip_index": clip_index}


@app.get("/jobs/{job_id}/plan")
def get_job_plan(job_id: str) -> dict:
    """Return the Master Plan file contents or Redis state for this job."""
    job = get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    plan_path = job_media_dir(job_id) / "master_plan.json"
    if plan_path.is_file():
        try:
            return json.loads(plan_path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {
        "topic": job.request.topic,
        "duration": job.request.duration,
        "total_clips": job.request.num_clips,
        "scene_bible": job.movie_bible,
        "acts": job.acts,
        "beats": job.beats,
    }


@app.patch("/jobs/{job_id}/plan")
def save_plan(job_id: str, request: PlanApprovalRequest) -> Job:
    """Save user edits to the story progression / master plan (beats or bible) without triggering video generation."""
    job = get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    if job.status not in ("plan_ready", "pending"):
        raise HTTPException(status_code=409, detail=f"cannot edit plan when job status is '{job.status}'")
    if _revision_busy(job):
        raise HTTPException(status_code=409, detail="the plan is being revised; wait for it to finish")
    fields = {}
    if request.beats is not None:
        fields["beats"] = request.beats
    if request.movie_bible is not None:
        fields["movie_bible"] = request.movie_bible
        fields["scene_bible"] = json.dumps(request.movie_bible, ensure_ascii=False)
    if fields:
        job = update_job(job_id, **fields)
        _save_master_plan_file(job)
    return job


@app.post("/jobs/{job_id}/approve-plan", status_code=202)
def approve_plan(job_id: str, request: PlanApprovalRequest | None = None) -> dict:
    """Approve the story progression / master plan, apply any edits, and start video generation."""
    job = get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    if job.status != "plan_ready":
        raise HTTPException(status_code=409, detail=f"cannot approve plan when job status is '{job.status}' (expected 'plan_ready')")
    if _revision_busy(job):
        raise HTTPException(status_code=409, detail="the plan is being revised; wait for it to finish, then approve")
    fields = {}
    if request:
        if request.beats is not None:
            fields["beats"] = request.beats
        if request.movie_bible is not None:
            fields["movie_bible"] = request.movie_bible
            fields["scene_bible"] = json.dumps(request.movie_bible, ensure_ascii=False)
    if fields:
        job = update_job(job_id, **fields)
    _save_master_plan_file(job)
    update_job(job_id, status="generating", error=None)
    try:
        execute_movie_job.delay(job_id)
    except Exception as e:
        update_job(job_id, status="plan_ready")
        raise HTTPException(status_code=503, detail=f"could not queue video generation: {e}") from e
    return {"job_id": job_id, "status": "generating"}


def _revisable_job(job_id: str) -> Job:
    """The job, if its plan may be revised now (a Narrated Drama plan waiting for approval); raises the HTTP error otherwise."""
    job = get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    if job.mode != "narrated_drama":
        raise HTTPException(status_code=400, detail="plan revision is only available for Narrated Drama")
    if job.status != "plan_ready":
        raise HTTPException(status_code=409, detail=f"the plan can only be revised while it waits for approval, not when the job is '{job.status}'")
    if not job.beats or not job.movie_bible:
        raise HTTPException(status_code=400, detail="job has no plan to revise")
    return job


@app.post("/jobs/{job_id}/revise-plan", status_code=202)
def revise_plan(job_id: str, request: ReviseRequest) -> dict:
    """Step one of a revision: split the note and find the clips it touches. Nothing in the plan changes yet."""
    import hybrid_narrated_drama as hnd
    job = _revisable_job(job_id)
    if _revision_busy(job):
        raise HTTPException(status_code=409, detail="a revision is already running")
    note = request.note.strip()
    if not note:
        raise HTTPException(status_code=400, detail="write what you want changed")
    if len(note) > hnd.MAX_NOTE_CHARS:
        raise HTTPException(status_code=400, detail=f"the note is too long ({len(note)} characters, at most {hnd.MAX_NOTE_CHARS}): split it into shorter notes")
    update_job(job_id, revision={"status": "proposing", "note": note, "at": time.time()})
    try:
        propose_plan_revision_task.delay(job_id)
    except Exception as e:
        update_job(job_id, revision=None)
        raise HTTPException(status_code=503, detail=f"could not queue the revision: {e}") from e
    return {"job_id": job_id, "status": "proposing"}


@app.post("/jobs/{job_id}/revise-plan/apply", status_code=202)
def apply_revision(job_id: str, request: ReviseApplyRequest) -> dict:
    """Step two: rewrite the clips the user ticked, and save the standing rules."""
    job = _revisable_job(job_id)
    rev = job.revision or {}
    if rev.get("status") != "proposed" or rev.get("kind") == "cast":
        raise HTTPException(status_code=409, detail="there is no proposal to apply; write a note first")
    if rev.get("blocked"):
        raise HTTPException(status_code=409, detail=rev["blocked"])
    offered = {c["clip"] for c in rev.get("clips") or []}
    chosen = sorted(set(request.clips))
    stray = [n for n in chosen if n not in offered]
    if stray:
        raise HTTPException(status_code=400, detail=f"clip(s) {stray} were not in the proposal")
    if not chosen and not rev.get("rules_new") and not rev.get("replaces"):
        raise HTTPException(status_code=400, detail="nothing to apply: tick at least one clip")
    update_job(job_id, revision={**rev, "status": "applying", "at": time.time()})
    try:
        apply_plan_revision_task.delay(job_id, chosen)
    except Exception as e:
        update_job(job_id, revision=rev)
        raise HTTPException(status_code=503, detail=f"could not queue the revision: {e}") from e
    return {"job_id": job_id, "status": "applying"}


@app.post("/jobs/{job_id}/revise-plan/add-clips")
def add_revision_clips(job_id: str, request: AddClipsRequest) -> dict:
    """Add clips the finder missed to the proposal (the user knows which ones); they come ticked. Changes nothing in the plan."""
    job = _revisable_job(job_id)
    rev = job.revision or {}
    if rev.get("status") != "proposed" or rev.get("kind") == "cast":
        raise HTTPException(status_code=409, detail="there is no proposal to add clips to; write a note first")
    total = len(job.beats or [])
    wrong = sorted({n for n in request.clips if not 1 <= n <= total})
    if wrong:
        raise HTTPException(status_code=400, detail=f"clip(s) {wrong[:10]} do not exist: the plan has {total} clips")
    have = {c["clip"] for c in rev.get("clips") or []}
    added = [n for n in sorted(set(request.clips)) if n not in have]
    clips = sorted((rev.get("clips") or []) + [{"clip": n, "reason": "You asked for this clip.", "change": "", "selected": True, "manual": True} for n in added],
                   key=lambda c: c["clip"])
    update_job(job_id, revision={**rev, "clips": clips, "at": time.time()})
    return {"job_id": job_id, "added": added}


@app.post("/jobs/{job_id}/cast-check", status_code=202)
def cast_check(job_id: str) -> dict:
    """Step one of adding people to the cast: find who the plan shows on screen without casting them. Nothing in the plan changes yet."""
    job = _revisable_job(job_id)
    if _revision_busy(job):
        raise HTTPException(status_code=409, detail="a revision is already running")
    update_job(job_id, revision={"kind": "cast", "status": "proposing", "at": time.time()})
    try:
        propose_cast_additions_task.delay(job_id)
    except Exception as e:
        update_job(job_id, revision=None)
        raise HTTPException(status_code=503, detail=f"could not queue the cast check: {e}") from e
    return {"job_id": job_id, "status": "proposing"}


@app.post("/jobs/{job_id}/cast-check/apply", status_code=202)
def cast_check_apply(job_id: str, request: CastApplyRequest) -> dict:
    """Step two: add the people the user kept (named, with their clips) to the cast, as supporting characters."""
    job = _revisable_job(job_id)
    rev = job.revision or {}
    if rev.get("kind") != "cast" or rev.get("status") != "proposed":
        raise HTTPException(status_code=409, detail="there is no cast proposal to apply; press 'Check the cast' first")
    chosen = [p.model_dump() for p in request.people if p.include]
    if not chosen:
        raise HTTPException(status_code=400, detail="tick at least one person to add")
    update_job(job_id, revision={**rev, "status": "applying", "at": time.time()})
    try:
        apply_cast_additions_task.delay(job_id, chosen)
    except Exception as e:
        update_job(job_id, revision=rev)
        raise HTTPException(status_code=503, detail=f"could not queue the cast change: {e}") from e
    return {"job_id": job_id, "status": "applying"}


@app.post("/jobs/{job_id}/revise-plan/cancel")
def cancel_revision(job_id: str) -> dict:
    """Throw a proposal, a failure or a finished revision's report away. Also frees a revision whose worker died."""
    job = get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    if job_is_running(job_id):
        raise HTTPException(status_code=409, detail="the revision is still working; it can be cancelled once it stops")
    update_job(job_id, revision=None)
    return {"job_id": job_id, "ok": True}


@app.post("/jobs/{job_id}/undo-plan-revision")
def undo_plan_revision(job_id: str) -> dict:
    """Put the plan back as it was before the last applied revision (up to PLAN_VERSIONS_KEPT steps back)."""
    job = _revisable_job(job_id)
    if _revision_busy(job) or job_is_running(job_id):
        raise HTTPException(status_code=409, detail="a revision is running; wait for it to finish")
    versions = _plan_versions(job_id)
    if not versions:
        raise HTTPException(status_code=409, detail="there is no earlier version to go back to")
    last = versions.pop()
    _set_plan_versions(job_id, versions)
    restored = {}
    if last.get("movie_bible"):   # versions made before the cast could change carry none: the cast stays as it is
        restored = {"movie_bible": last["movie_bible"], "scene_bible": json.dumps(last["movie_bible"], ensure_ascii=False)}
    update_job(job_id, beats=last["beats"], plan_report=last.get("plan_report"), plan_rules=last.get("plan_rules"),
               plan_versions_count=len(versions), revision=None, **restored)
    _save_master_plan_file(get_job(job_id))
    return {"job_id": job_id, "ok": True, "restored": last.get("label", "")}


@app.put("/jobs/{job_id}/plan-rules")
def put_plan_rules(job_id: str, request: RulesRequest) -> dict:
    """Replace the standing rules (the dashboard uses this to edit or delete one)."""
    import hybrid_narrated_drama as hnd
    job = _revisable_job(job_id)
    if _revision_busy(job):
        raise HTTPException(status_code=409, detail="a revision is running; wait for it to finish")
    try:
        rules = hnd.clean_rules(request.rules)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    update_job(job_id, plan_rules=rules)
    return {"job_id": job_id, "rules": rules}


@app.post("/jobs/{job_id}/replan", status_code=202)
def replan_story(job_id: str) -> dict:
    """Ask OpenAI to re-generate a new Master Plan outline for this job."""
    job = get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    if job.status not in ("plan_ready", "failed"):
        raise HTTPException(status_code=409, detail=f"cannot replan when job status is '{job.status}'")
    if _revision_busy(job):
        raise HTTPException(status_code=409, detail="the plan is being revised; wait for it to finish")
    _set_plan_versions(job_id, [])   # a new plan: the old versions no longer apply (the standing rules stay, and shape the new plan)
    update_job(job_id, status="generating", error=None, revision=None, plan_versions_count=0)
    try:
        run_generation_job.delay(job_id)
    except Exception as e:
        update_job(job_id, status="plan_ready")
        raise HTTPException(status_code=503, detail=f"could not queue replanning: {e}") from e
    return {"job_id": job_id, "status": "generating"}


@app.post("/jobs/{job_id}/resume", status_code=202)
def resume_job(job_id: str) -> dict:
    """Resume an interrupted or failed Story Videos job from the first unrendered clip."""
    job = get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    if job.mode not in ("story_videos", "narrated_drama"):
        raise HTTPException(status_code=400, detail="resume is only supported for Story Videos and Narrated Drama modes")
    if job.status not in ("failed", "generating"):
        raise HTTPException(status_code=409, detail=f"cannot resume job when status is '{job.status}'")
    if not job.movie_bible or not job.beats:
        raise HTTPException(status_code=400, detail="job has no master plan to resume")
    if job_is_running(job_id):
        # A second run would script and render every clip again, paid for twice. A job whose worker died is not
        # "running": its lock runs out within JOB_LOCK_TTL seconds and it can then be resumed.
        raise HTTPException(status_code=409, detail=f"this job is still running, so it cannot be resumed yet. If the worker has "
                                                    f"crashed, try again in {JOB_LOCK_TTL} seconds.")
    update_job(job_id, status="generating", error=None)
    try:
        execute_movie_job.delay(job_id)
    except Exception as e:
        update_job(job_id, status="failed", error=f"could not queue resume: {e}")
        raise HTTPException(status_code=503, detail=f"could not queue resume: {e}") from e
    return {"job_id": job_id, "status": "generating"}


@app.post("/jobs/{job_id}/extend", status_code=202)
def extend_story(job_id: str, req: ExtendStoryRequest) -> dict:
    """Extend a completed Story Videos job with a continuation scene/chapter."""
    job = get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    if job.mode != "story_videos":
        raise HTTPException(status_code=400, detail="continuation is only supported for Story Videos mode")
    if job.status not in ("done", "plan_ready"):
        raise HTTPException(status_code=409, detail=f"cannot extend story while job status is '{job.status}'")
    if req.duration % 5 != 0:
        raise HTTPException(status_code=400, detail="duration must be a multiple of 5 seconds")
    if not req.continuation_prompt.strip():
        raise HTTPException(status_code=400, detail="continuation_prompt is required")

    update_job(job_id, status="generating", error=None)
    try:
        extend_movie_plan_task.delay(job_id, req.continuation_prompt.strip(), req.duration)
    except Exception as e:
        update_job(job_id, status="done")
        raise HTTPException(status_code=503, detail=f"could not queue continuation planning: {e}") from e
    return {"job_id": job_id, "status": "generating"}


@app.delete("/jobs/{job_id}")
def delete_job(job_id: str) -> dict:
    """Cancel / discard a job, remove its local media files, and delete its Redis record.
    If the job has finished clips and was only in plan_ready for a continuation, roll back
    the continuation so completed clips and video are preserved."""
    job = get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    done_clips = [c for c in job.clips if c.status == "done"]
    if done_clips and job.status == "plan_ready":
        kept_clips = done_clips
        kept_beats = (job.beats or [])[:len(kept_clips)]
        update_job(job_id, clips=kept_clips, beats=kept_beats, status="done", error=None)
        _save_master_plan_file(get_job(job_id))
        return {"ok": True, "job_id": job_id, "action": "rolled_back_to_done"}

    media_dir = job_media_dir(job_id)
    if media_dir.exists():
        import shutil
        shutil.rmtree(media_dir, ignore_errors=True)
    redis_client.delete(f"job:{job_id}")
    redis_client.delete(_versions_key(job_id))
    return {"ok": True, "job_id": job_id, "action": "deleted"}


@app.patch("/jobs/{job_id}/clips/{clip_index}")
def update_clip_fields(job_id: str, clip_index: int, update: ClipUpdate) -> Job:
    """Save user edits to a clip's script or scene parameters without triggering video generation."""
    job = _require_clip(job_id, clip_index)
    fields = {k: v for k, v in update.model_dump().items() if v is not None}
    if fields:
        job = update_clip(job_id, clip_index, **fields)
    return job


@app.post("/jobs/{job_id}/clips/{clip_index}/regenerate-script", status_code=202)
def regenerate_script(job_id: str, clip_index: int, update: ClipUpdate | None = None) -> dict:
    """Regenerate Script (Prompt 9), in the background: a new line for the clip, then the clip rendered again from
    it. Talking Head writes a new spoken line; Story Time writes new narration and keeps the clip's visual."""
    overrides = {k: v for k, v in update.model_dump().items() if v is not None} if update else None
    return _start_regeneration(job_id, clip_index, regenerate_script_task, overrides)


@app.post("/jobs/{job_id}/clips/{clip_index}/regenerate-scene", status_code=202)
def regenerate_scene(job_id: str, clip_index: int, update: ClipUpdate | None = None) -> dict:
    """Regenerate Scene (Prompt 10), in the background; the clip's words stay as they are. Talking Head renders the
    clip again from the same line (a new take); Story Time asks OpenAI for a new visual (a different scene that still
    fits the same narration) and renders the clip from it."""
    overrides = {k: v for k, v in update.model_dump().items() if v is not None} if update else None
    return _start_regeneration(job_id, clip_index, regenerate_scene_task, overrides)


@app.post("/jobs/{job_id}/assemble", status_code=202)
def assemble(job_id: str) -> dict:
    """Build the final video again, in the background (Prompt 12). Jobs build it by themselves when they finish and
    after every regeneration; this is for jobs made before that existed, and for a retry after a failure. 409 while
    the job is generating or if a clip isn't done. Poll GET /jobs/{job_id} for final_video_at or final_error."""
    if get_job(job_id) is None:
        raise HTTPException(status_code=404, detail="job not found")
    before = _claim_job(job_id)
    try:
        assemble_task.delay(job_id)
    except Exception as e:  # the broker didn't take it: put the job back as it was
        update_job(job_id, status=before.status)
        raise HTTPException(status_code=503, detail="could not queue the final video; try again") from e
    return {"job_id": job_id}


@app.get("/jobs/{job_id}/video")
def final_video(job_id: str) -> FileResponse:
    """The job's final video (MP4), for the dashboard's player and download link. 404 until it has been built."""
    if get_job(job_id) is None:  # checked first: job_id becomes part of a file path
        raise HTTPException(status_code=404, detail="job not found")
    path = final_video_path(job_id)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="the final video hasn't been made yet")
    return FileResponse(path, media_type="video/mp4")
