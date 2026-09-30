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
import time
import uuid
from pathlib import Path
from typing import Literal, get_args

import httpx
import numpy as np
import redis
from celery import Celery
from celery.utils.log import get_task_logger
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from openai import OpenAI
from pydantic import BaseModel, ConfigDict, Field, model_validator


# --- Config ---
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
KIE_API_KEY = os.getenv("KIE_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5.5")
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
# clip is generated from. Seedance's 720p is 1280x720, inside kie.ai's 927,408-pixel limit for a reference video.
MASTER_RESOLUTION = "720p"


# --- Celery App ---
celery_app = Celery("app", broker=REDIS_URL)
celery_app.conf.broker_connection_retry_on_startup = True


# --- Models ---
Resolution = Literal["480p", "720p"]
Mode = Literal["talking_head", "story_time"]
ClipDuration = Literal[5, 10]  # production is always 10; 5 exists only to save credits while testing
Status = Literal["pending", "generating", "done", "failed"]  # shared by clips and jobs


class ClipRequest(BaseModel):
    topic: str = Field(min_length=1)
    duration: int = Field(gt=0)  # total seconds; must be a multiple of clip_duration
    resolution: Resolution = "480p"
    mode: Mode = "talking_head"
    clip_duration: ClipDuration = CLIP_DURATION

    @model_validator(mode="after")
    def duration_is_whole_clips(self):
        if self.duration % self.clip_duration:
            raise ValueError(f"duration must be a multiple of the clip length ({self.clip_duration} seconds)")
        return self

    @property
    def num_clips(self) -> int:
        return self.duration // self.clip_duration


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
    status: Status = "pending"
    error: str | None = None  # why this clip failed


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
    # The joined video (final_video_path(), served at GET /jobs/{id}/video): when it was last built, or why it failed.
    final_video_at: float | None = None
    final_error: str | None = None


# --- Redis Store Helpers ---
redis_client = redis.Redis.from_url(REDIS_URL, decode_responses=True)  # connects lazily


def _job_key(job_id: str) -> str:
    return f"job:{job_id}"


def save_job(job: Job) -> None:
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


def _ask_openai_json(system_prompt: str, user_content: str, name: str, schema: dict) -> dict:
    """One Structured Outputs call (strict JSON schema); returns the parsed JSON or raises ValueError."""
    response = OpenAI(api_key=OPENAI_API_KEY, timeout=300).chat.completions.create(
        model=OPENAI_MODEL,
        messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_content}],
        response_format={"type": "json_schema", "json_schema": {"name": name, "strict": True, "schema": schema}},
    )
    message = response.choices[0].message
    if message.refusal:
        raise ValueError(f"OpenAI refused to write the script: {message.refusal}")
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
                f'{bible}. She speaks directly to camera, {clip.delivery}: "{clip.dialogue}" '
                "Natural lip sync to dialogue, no background music, no score."
            )
        return (
            f'Continuing directly from <Video 1>, {bible}, still speaking to camera, {clip.delivery}: "{clip.dialogue}" '
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
    payload = {"prompt": prompt, "resolution": resolution, "duration": duration, "generate_audio": generate_audio}
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
        return _wait_for_clip(client, task_id)


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
FINAL_SIZES = {"480p": (864, 496), "720p": (1280, 720)}  # Seedance's 16:9 sizes, used if no clip shows the job's own
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
    new file and an unchanged one is never fetched twice)."""
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
    trims = [job.mode == "talking_head" and i > 0 for i in range(len(sources))]
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


# --- Celery Task ---
task_log = get_task_logger(__name__)


def _fail_job(job_id: str, message: str) -> None:
    task_log.error("job %s failed: %s", job_id, message)
    update_job(job_id, status="failed", error=message)


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


@celery_app.task
def assemble_task(job_id: str) -> None:
    """POST /jobs/{job_id}/assemble: build the final video on demand (the endpoint has marked the job generating)."""
    _assemble(job_id)
    update_job(job_id, status="done")


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
    result = generate_clip(
        build_clip_prompt(job.mode, job.scene_bible, clip, is_first_clip=(i == 0)),
        resolution,
        duration=job.request.clip_duration,
        generate_audio=True,
        **refs,
    )
    video_url = result["video_url"]
    update_clip(job_id, i, video_url=video_url, **{f: getattr(clip, f) for f in SCRIPT_FIELDS})
    if i == 0:
        _make_anchors(job_id, story, video_url)
    if story and i < len(job.clips) - 1:  # the muted copy is only ever the NEXT clip's video reference
        update_clip(job_id, i, muted_video_url=mute_video(video_url), muted_video_at=time.time())


@celery_app.task
def run_generation_job(job_id: str) -> None:
    """Write the script, then generate each clip in order. What a clip after the first is generated from depends on
    the mode.

    Talking Head: clip 0 is the master, always rendered at MASTER_RESOLUTION (720p) whatever the job's resolution.
    Every later clip is rendered at the job's resolution from exactly two references, the same two for the whole job:
      - video: clip 0's video with its audio REMOVED (muted so it carries pictures only and can't leak clip 0's speech),
      - audio: clip 0's audio.
    Nothing is taken from the previous clip, so quality can't compound down the chain however long the video is.

    Story Time: every clip is rendered at the job's resolution. Every later clip gets three references:
      - video: the PREVIOUS clip's video with its audio removed (chained so the scene can move on; muted so its
        soundtrack can't compete with the narrator's voice anchor),
      - audio: clip 0's audio (the narrator's voice), fixed for the whole job,
      - image: clip 0's last frame (the main character), fixed for the whole job.
    Whether this chain degrades over long jobs the way Talking Head's did is still to be observed (PLAN.md question 14).

    The original, unmuted videos stay in Clip.video_url and are what gets stitched into the final video. Every outcome
    is written to the job in Redis (status and error). A failure marks the job failed and stops the chain; it never
    raises. All writes go through update_job() / update_clip().
    """
    job = get_job(job_id)
    if job is None:
        raise KeyError(f"job {job_id} not found")
    story = job.mode == "story_time"

    update_job(job_id, status="generating")
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


REGENERATE_LABELS = {"script": "Regenerate Script", "scene": "Regenerate Scene"}


@celery_app.task
def regenerate_script_task(job_id: str, clip_index: int) -> None:
    """Regenerate Script (Prompt 9): a new line for the clip (Talking Head: dialogue and delivery; Story Time:
    narration and delivery, keeping its visual), then the clip rendered again from it. See _regenerate()."""
    _regenerate(job_id, clip_index, "script")


@celery_app.task
def regenerate_scene_task(job_id: str, clip_index: int) -> None:
    """Regenerate Scene (Prompt 10): the clip's words stay as they are. Talking Head: a new take of the clip from the
    same line. Story Time: a new visual (a different scene for the same narration), then the clip rendered from it.
    See _regenerate()."""
    _regenerate(job_id, clip_index, "scene")


def _regenerate(job_id: str, clip_index: int, action: str) -> None:
    """Regenerate one clip (the LAST clip only for now), with the same references as run_generation_job.

    The endpoint has already marked the job and the clip "generating". The clip keeps its old script and video until
    the new video exists; if anything fails, it keeps whatever it has and the error is recorded on the clip and the
    job, which goes back to "done" (or "failed" if a clip still has no video). After a success the final video is
    built again. Never raises.
    """
    job = get_job(job_id)
    label = REGENERATE_LABELS[action]
    try:
        clip = job.clips[clip_index]
        if action == "script":
            clip = clip.model_copy(update=regenerate_line(job, clip_index))
        elif job.mode == "story_time":
            clip = clip.model_copy(update=regenerate_visual(job, clip_index))
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


# --- FastAPI App & Routes ---
app = FastAPI(title="AI Video Extender")
DASHBOARD = Path(__file__).with_name("dashboard.html")


@app.get("/", include_in_schema=False)
def dashboard() -> FileResponse:
    """The single-page dashboard (plain HTML/JS); it talks to POST /jobs and GET /jobs/{job_id}."""
    return FileResponse(DASHBOARD, media_type="text/html")


@app.get("/health")
def health():
    return {"status": "ok"}


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
    save_job(job)
    try:
        run_generation_job.delay(job.id)
    except Exception as e:  # the broker didn't take it: without this the job would sit "pending" forever
        _fail_job(job.id, f"could not queue the job: {type(e).__name__}: {e}")
        raise HTTPException(status_code=503, detail="could not queue the job; try again") from e
    return {"job_id": job.id}


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


def _start_regeneration(job_id: str, clip_index: int, task) -> dict:
    """Shared by both regenerate endpoints: only the LAST clip for now (501 for any other), claim the job, queue the
    task, and return 202's body. Poll GET /jobs/{job_id}: the job and the clip show "generating", then "done" with
    the new clip (or the error, with the old clip kept)."""
    job = _require_clip(job_id, clip_index)
    if clip_index != len(job.clips) - 1:
        raise HTTPException(status_code=501, detail="mid-sequence regeneration not yet implemented")
    before = _claim_job(job_id, clip_index)
    try:
        task.delay(job_id, clip_index)
    except Exception as e:  # the broker didn't take it: put the job back as it was
        old = before.clips[clip_index]
        update_clip(job_id, clip_index, status=old.status, error=old.error)
        update_job(job_id, status=before.status, error=before.error)
        raise HTTPException(status_code=503, detail="could not queue the regeneration; try again") from e
    return {"job_id": job_id, "clip_index": clip_index}


@app.post("/jobs/{job_id}/clips/{clip_index}/regenerate-script", status_code=202)
def regenerate_script(job_id: str, clip_index: int) -> dict:
    """Regenerate Script (Prompt 9), in the background: a new line for the clip, then the clip rendered again from
    it. Talking Head writes a new spoken line; Story Time writes new narration and keeps the clip's visual."""
    return _start_regeneration(job_id, clip_index, regenerate_script_task)


@app.post("/jobs/{job_id}/clips/{clip_index}/regenerate-scene", status_code=202)
def regenerate_scene(job_id: str, clip_index: int) -> dict:
    """Regenerate Scene (Prompt 10), in the background; the clip's words stay as they are. Talking Head renders the
    clip again from the same line (a new take); Story Time asks OpenAI for a new visual (a different scene that still
    fits the same narration) and renders the clip from it."""
    return _start_regeneration(job_id, clip_index, regenerate_scene_task)


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
