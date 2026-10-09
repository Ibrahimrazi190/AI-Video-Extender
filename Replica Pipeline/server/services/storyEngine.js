/**
 * Story Engine - two-stage, server-side script writer.
 *
 *   Stage 1  PLAN   : story bible (cast, outfits, voices, locations, look) + a per-clip outline
 *   Stage 2  CLIPS  : batches of clips, each batch seeded with the previous batch's ending state
 *                     (position of every character, held props, last frame, recent dialogue)
 *
 * Every clip is validated (beat timing, dialogue length vs. clip length, known characters) and
 * repaired by re-asking the LLM with the exact error. Rendering to the final video-model prompt
 * is done separately in promptRenderer.js.
 */
import { renderClipPrompt, buildNegativePrompt } from './promptRenderer.js';

const DEFAULT_LLM = process.env.OPENAI_MODEL || 'gpt-4.1';

// ============================================================
// Helpers
// ============================================================

const arr = v => (Array.isArray(v) ? v : []);
const str = v => (typeof v === 'string' ? v.trim() : '');
const trim = (v, n = 800) => str(v).slice(0, n);
const r1 = n => Math.round(n * 10) / 10;
const r3 = n => Math.round(n * 1000) / 1000;
const wordCount = text => str(text).split(/\s+/).filter(Boolean).length;

export function formatTime(seconds) {
  const m = Math.floor(seconds / 60);
  const s = r1(seconds - m * 60);
  const whole = Math.floor(s);
  const frac = s - whole > 0 ? String(r1(s - whole)).slice(1) : '';
  return `${m}:${String(whole).padStart(2, '0')}${frac}`;
}

const formatRange = (a, b) => `${formatTime(a)}–${formatTime(b)}`;

function slotsFor(totalDuration, clipDuration) {
  const count = Math.ceil(totalDuration / clipDuration);
  return Array.from({ length: count }, (_, i) => {
    const startSec = r3(i * clipDuration);
    const endSec = r3(Math.min(totalDuration, (i + 1) * clipDuration));
    return {
      clipNumber: i + 1,
      startSec,
      endSec,
      durationSec: r3(endSec - startSec),
      timecode: formatRange(startSec, endSec)
    };
  });
}

function makeBlocks(slots, blockSize) {
  const blocks = [];
  for (let i = 0; i < slots.length; i += blockSize) {
    const g = slots.slice(i, i + blockSize);
    blocks.push({
      blockId: blocks.length + 1,
      firstClip: g[0].clipNumber,
      lastClip: g[g.length - 1].clipNumber,
      startSec: g[0].startSec,
      endSec: g[g.length - 1].endSec
    });
  }
  return blocks;
}

/**
 * What each video model can realistically do inside ONE generation.
 * "mini" models get fewer shots, fewer people and less speech so the render stays coherent.
 */
export function profileFor(modelId, durationSec) {
  const mini = /mini|lite|fast/i.test(modelId || '');
  const maxByTime = Math.max(1, Math.floor(durationSec / 2.5));
  return {
    mini,
    maxBeats: Math.min(mini ? 2 : 5, maxByTime),
    maxCast: mini ? 2 : 3,
    wordsPerSec: mini ? 2.0 : 2.3,
    minBeatSec: 1.5
  };
}

// ============================================================
// LLM transport
// ============================================================

async function callOpenAI({ apiKey, model, systemPrompt, userPrompt, maxOutputTokens, signal }) {
  const body = {
    model,
    messages: [
      { role: 'system', content: systemPrompt },
      { role: 'user', content: userPrompt }
    ],
    response_format: { type: 'json_object' },
    max_completion_tokens: maxOutputTokens
  };
  // Reasoning-style models reject a custom temperature.
  if (!/^(o\d|gpt-5)/i.test(model)) body.temperature = 0.85;

  const res = await fetch('https://api.openai.com/v1/chat/completions', {
    method: 'POST',
    signal,
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${apiKey}` },
    body: JSON.stringify(body)
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(`LLM HTTP ${res.status}: ${err.error?.message || res.statusText}`);
  }

  const data = await res.json();
  const choice = data.choices?.[0];
  if (!choice?.message?.content) {
    throw new Error(`LLM returned empty output (finish_reason: ${choice?.finish_reason || 'unknown'})`);
  }
  if (choice.finish_reason === 'length') {
    throw new Error('LLM output was truncated (finish_reason: length). Reduce batch size.');
  }
  return { text: choice.message.content, usage: data.usage };
}

function parseJson(text) {
  const clean = text.trim().replace(/^```(?:json)?\s*/i, '').replace(/\s*```$/, '');
  return JSON.parse(clean);
}

// ============================================================
// Stage 1 - planner prompt
// ============================================================

const PLAN_SYSTEM = `
You are a professional screenwriter and showrunner for short-form cinematic video (micro-drama, short films,
trailers). Your script will be shot by an AI video model that only understands what is VISIBLE and AUDIBLE.
Return exactly ONE valid JSON object. No markdown, no commentary.

You receive a 2-3 line story idea, a runtime split into fixed clips, and visual preferences.
Expand the idea into a complete, specific, emotionally engaging story that fills the ENTIRE runtime.

STORY RULES
1. Stay faithful to the user's premise, names, relationships, twists and genre. Never turn a drama/romance/comedy
   into an action film, and never add genre elements (sci-fi, neon, weapons, chases) the premise does not contain.
2. The user's chosen visual style is a starting point for lensing and colour grade ONLY. If it conflicts with the
   story's genre, period or setting, keep the camera/grade language and drop the incompatible world-building
   (e.g. "cyberpunk" + a London market romance = cinematic grade and contrast, but a realistic present-day London market).
3. Short-form structure: a hook inside the first 3 seconds, a new piece of information, conflict or emotional turn in
   EVERY clip, escalating stakes, a turning point near 60-70%, and a final clip that lands the climax or an intentional
   cliffhanger. No filler, no repeated beats, no clip that only "looks pretty".
4. Tell the story through people: concrete behaviour and spoken dialogue, not narration or montage. Keep the cast small
   (2-4 named speaking characters) and the locations few (reuse them) so the video model can keep identities consistent.
5. Everything must be filmable in a continuous 5-15 second clip: no time passing inside a clip, no internal monologue,
   no on-screen text.
6. Scene changes happen at clip boundaries. Plan them deliberately and say where the story moves location or time.

CHARACTER RULES
- "appearance" is the PERMANENT look (age, ethnicity/skin tone, face shape, eyes, hair colour+length+style, build,
  distinguishing marks). Be specific enough that the same person is recognisable in every clip. Never change it.
- Each character has one or more "outfits" with ids. Outfit changes must be motivated by the story (e.g. a disguise).
  Describe each outfit fully (garments, colours, fabrics, shoes, accessories).
- "voice": timbre, pitch, pace, accent, energy (e.g. "warm baritone, measured, faint London polish").
- "speechStyle": how they talk (clipped, teasing, formal, hesitant...) and 2-3 sample phrases in that voice.

OUTLINE RULES
- One outline entry per supplied block, same blockId, same order. Each entry says exactly what happens (specific
  actions and the gist of key dialogue), the emotional shift, which outfit each character wears, and the hook that pulls
  the viewer into the next block.
- Spread major events across the whole runtime. Do not rush the ending into the last block.

REQUIRED JSON
{
  "storyBible": {
    "title": "...",
    "genre": "...",
    "logline": "...",
    "ending": "...",
    "tone": "...",
    "look": {
      "grade": "colour palette + contrast + film-stock feel suited to this story",
      "lighting": "typical light quality/sources",
      "lensing": "lens + depth-of-field language"
    },
    "characters": [
      {
        "id": "c1",
        "name": "...",
        "role": "...",
        "appearance": "...",
        "outfits": [ { "id": "o1", "description": "..." } ],
        "voice": "...",
        "speechStyle": "...",
        "personality": "...",
        "motivation": "...",
        "relationships": "..."
      }
    ],
    "locations": [ { "id": "l1", "name": "...", "description": "...", "lighting": "...", "layout": "..." } ],
    "props": [ { "name": "...", "description": "..." } ],
    "unchangingFacts": [ "..." ]
  },
  "outline": [
    {
      "blockId": 1,
      "setting": "...",
      "events": "...",
      "keyDialogue": "...",
      "outfits": "who wears what",
      "emotionalShift": "...",
      "endingHook": "..."
    }
  ]
}
`;

// ============================================================
// Stage 2 - clip writer prompt
// ============================================================

const CLIP_SYSTEM = `
You are a director, cinematographer, dialogue writer and AI-video prompt engineer. Each clip you write is sent on its
own to an AI video model (Seedance family) that has NO memory of other clips and can only render what is visible and
audible. Return exactly ONE valid JSON object. No markdown, no commentary.

You receive: the story bible, the outline for the relevant part of the story, the exact clip slots (number, duration),
the previous batch's ending state, and the model profile (maxBeats, maxCast, wordsPerSec).

WRITE EACH CLIP AS A SELF-CONTAINED SHOT LIST
- Every clip must advance the outline for its time range. Respect the planned events, outfits and twists.
- Never refer to other clips ("as before", "again"). Restate who/where/what is visible.
- Turn emotion into visible behaviour: eyes, brows, jaw, breath, hands, posture, what a person does with an object.
  Bad: "she feels sad". Good: "her smile fades, eyes drop to the photo, thumb rubs its torn corner, breath catches".
- Real physics, one clear action per beat per character, no teleporting, no unexplained props.

BEATS (timed shots)
- Use between 1 and maxBeats beats. Beats are contiguous: the first starts at 0, each starts where the last ended, the last
  ends exactly at the clip duration. Each beat is at least 1.5 s.
- A beat = one camera setup. Changing framing (e.g. a reverse shot on the listener) = a new beat. Dialogue scenes
  should use shot / reverse-shot or push-ins on the speaker, not one static wide.
- For every beat give: shot framing (close-up, medium, over-the-shoulder, wide...), angle, lens (mm), camera movement
  (static, slow push-in, handheld drift, tracking, pan... ONE movement per beat), "action" (physical events, who does
  what with which body part/object) and "acting" (facial/body performance of everyone visible).
- Match the frame: for a vertical 9:16 frame favour close/medium shots, stack depth front-to-back, keep faces in the
  upper-middle third; for 16:9 use side-by-side blocking.
- Movement should serve the drama. Quiet scenes use static or very slow moves; do not force whip-pans or tracking.

DIALOGUE (this is a script writer - people TALK)
- Put spoken lines inside the beat where they are said: "dialogue": [ { "speaker": "<character id>", "text": "...",
  "delivery": "tone + physical way of speaking" } ].
- Speakers must be characters listed in this clip's "cast" and on screen (the model lip-syncs them). No narrator/voice-over.
- Lines must fit the beat: at most (beat seconds - 0.7) x wordsPerSec words IN TOTAL per beat, including every speaker
  in that beat. Short, sharp, subtext-rich lines. Lines must sound like each character's speechStyle.
- Most clips with two or more characters should contain dialogue. Use silence only when it is dramatically deliberate
  (and then show the reaction), never for more than two clips in a row.
- Never put dialogue in the "action" field. Do not repeat information the viewer already knows.

FRAMES AND CONTINUITY
- "firstFrame": a precise still-image composition for the opening frame: shot size, angle, who stands/sits where
  (screen-left/right/centre, foreground/background), poses, expressions, eyeline, props in hand, lighting, background.
- "lastFrame": the precise composition of the final frame. End each clip on a SETTLED, held pose (a held look, a
  completed gesture) rather than mid-motion blur: this frame is used as the start image of the next clip.
- transition: "opening" (first clip), "continuous" (same space and moment: firstFrame must reproduce the previous lastFrame
  composition exactly - same positions, poses, props, lighting; only a slightly different camera is allowed) or "cut"
  (new location/time: describe a fresh opening composition).
- Characters keep their appearance; outfits only change when the outline says so. Use outfit ids from the bible in "cast".

AUDIO
- "audio": ambience (location soundscape), foley (specific sounds of actions/props in this clip) and music (usually
  "none" or one short sentence about a very quiet underscore). Do not add intrusive music.

OUTPUT FIELDS
- "title": 2-4 word slugline. "storyPurpose": one sentence - what this clip changes in the story.
- "location": the location name/id + time of day. "environment": visible set dressing, light direction and quality,
  weather, background activity, depth layers.
- "cast": every character visible at any point: [ { "id": "c1", "outfitId": "o1", "state": "pose/expression at start" } ].
  Respect maxCast.
- "continuityOut": one sentence: what the next clip must inherit (positions, props, mood).

REQUIRED JSON
{
  "clips": [
    {
      "clipNumber": 1,
      "title": "...",
      "storyPurpose": "...",
      "transition": "opening",
      "location": "...",
      "environment": "...",
      "cast": [ { "id": "c1", "outfitId": "o1", "state": "..." } ],
      "firstFrame": "...",
      "beats": [
        {
          "fromSec": 0,
          "toSec": 4,
          "shot": { "framing": "...", "angle": "...", "lens": "...", "movement": "..." },
          "action": "...",
          "acting": "...",
          "dialogue": [ { "speaker": "c1", "text": "...", "delivery": "..." } ]
        }
      ],
      "audio": { "ambience": "...", "foley": "...", "music": "..." },
      "lastFrame": "...",
      "continuityOut": "..."
    }
  ],
  "endState": {
    "location": "...",
    "lighting": "...",
    "lastFrame": "...",
    "characters": { "c1": "exact position, pose, expression, outfit id" },
    "props": { "item": "who holds it / where it is" },
    "plotProgress": "...",
    "nextAction": "..."
  }
}
Return exactly the requested number of clips with the exact clipNumbers. Use "dialogue": [] when a beat has no speech.
`;

// ============================================================
// Bible / clip validation + normalisation
// ============================================================

function normalizeBible(bible) {
  const characters = arr(bible.characters).map((c, i) => {
    const id = str(c.id) || `c${i + 1}`;
    let outfits = arr(c.outfits)
      .map((o, j) => ({ id: str(o.id) || `o${j + 1}`, description: str(o.description) }))
      .filter(o => o.description);
    if (!outfits.length && str(c.outfit)) outfits = [{ id: 'o1', description: str(c.outfit) }];
    return { ...c, id, name: str(c.name) || id, outfits };
  });

  if (!characters.length) throw new Error('storyBible.characters is empty');
  for (const c of characters) {
    if (!str(c.appearance)) throw new Error(`Character ${c.name}: missing appearance`);
    if (!c.outfits.length) throw new Error(`Character ${c.name}: missing outfits`);
  }
  return { ...bible, characters };
}

function findCharacter(bible, ref) {
  const key = str(typeof ref === 'object' ? ref?.id ?? ref?.name : ref).toLowerCase();
  if (!key) return null;
  return (
    bible.characters.find(c => c.id.toLowerCase() === key) ||
    bible.characters.find(c => c.name.toLowerCase() === key) ||
    bible.characters.find(c => c.name.toLowerCase().split(/\s+/)[0] === key) ||
    null
  );
}

function normalizeClip(clip, slot, bible, profile) {
  const n = slot.clipNumber;
  if (!clip || Number(clip.clipNumber) !== n) {
    throw new Error(`Expected clip ${n}; got ${clip?.clipNumber ?? 'none'}`);
  }

  for (const f of ['storyPurpose', 'environment', 'firstFrame', 'lastFrame', 'location']) {
    if (!str(clip[f])) throw new Error(`Clip ${n}: missing ${f}`);
  }

  // ---- cast ----
  const cast = arr(clip.cast).map(entry => {
    const obj = typeof entry === 'string' ? { id: entry } : entry || {};
    const character = findCharacter(bible, obj);
    if (!character) throw new Error(`Clip ${n}: cast member "${obj.id || obj.name}" is not in the story bible`);
    const outfit = character.outfits.find(o => o.id === obj.outfitId) || character.outfits[0];
    return { id: character.id, outfitId: outfit.id, state: str(obj.state) };
  });
  if (!cast.length) throw new Error(`Clip ${n}: cast is empty`);
  if (cast.length > profile.maxCast) {
    throw new Error(`Clip ${n}: ${cast.length} characters on screen; maximum is ${profile.maxCast}`);
  }

  // ---- beats ----
  const beatsIn = arr(clip.beats);
  if (!beatsIn.length) throw new Error(`Clip ${n}: missing beats`);
  if (beatsIn.length > profile.maxBeats) {
    throw new Error(`Clip ${n}: ${beatsIn.length} beats; maximum is ${profile.maxBeats} for ${slot.durationSec}s`);
  }

  let cursor = 0;
  const beats = beatsIn.map((b, i) => {
    const from = Number(b.fromSec);
    const to = Number(b.toSec);
    if (!Number.isFinite(from) || !Number.isFinite(to)) throw new Error(`Clip ${n}: beat ${i + 1} has invalid times`);
    // Snap small drift, reject real timing errors.
    if (Math.abs(from - cursor) > 0.6) throw new Error(`Clip ${n}: beat ${i + 1} starts at ${from}s but must start at ${cursor}s`);
    const last = i === beatsIn.length - 1;
    const end = last ? slot.durationSec : to;
    if (last && Math.abs(to - slot.durationSec) > 0.6) {
      throw new Error(`Clip ${n}: last beat ends at ${to}s but the clip is ${slot.durationSec}s`);
    }
    if (end - cursor < profile.minBeatSec - 0.05) {
      throw new Error(`Clip ${n}: beat ${i + 1} is shorter than ${profile.minBeatSec}s`);
    }
    if (!str(b.action)) throw new Error(`Clip ${n}: beat ${i + 1} has no action`);

    const beat = {
      fromSec: r1(cursor),
      toSec: r1(end),
      shot: {
        framing: str(b.shot?.framing),
        angle: str(b.shot?.angle),
        lens: str(b.shot?.lens),
        movement: str(b.shot?.movement)
      },
      action: str(b.action),
      acting: str(b.acting),
      dialogue: []
    };
    cursor = end;

    // ---- dialogue in this beat ----
    const lines = arr(b.dialogue).filter(l => str(l?.text));
    let words = 0;
    for (const l of lines) {
      const speaker = findCharacter(bible, l.speaker);
      if (!speaker) throw new Error(`Clip ${n}: dialogue speaker "${l.speaker}" is not a story character`);
      if (!cast.some(c => c.id === speaker.id)) {
        throw new Error(`Clip ${n}: ${speaker.name} speaks but is not in this clip's cast`);
      }
      words += wordCount(l.text);
      beat.dialogue.push({
        speaker: speaker.id,
        speakerName: speaker.name,
        text: str(l.text),
        delivery: str(l.delivery)
      });
    }
    const budget = Math.max(0, beat.toSec - beat.fromSec - 0.7) * profile.wordsPerSec;
    if (words > budget + 1) {
      console.log(
        `Clip ${n}: beat ${i + 1} (${r1(beat.toSec - beat.fromSec)}s) has ${words} spoken words; ` +
        `maximum is ${Math.floor(budget)}. Shorten the lines or lengthen the beat.`
      );
    }
    return beat;
  });

  // ---- derive absolute dialogue timings inside the clip (natural pace, not stretched) ----
  const dialogue = [];
  for (const beat of beats) {
    let t = beat.fromSec + 0.3;
    for (const l of beat.dialogue) {
      const dur = wordCount(l.text) / (profile.wordsPerSec + 0.2) + 0.2;
      l.fromSec = r1(t);
      l.toSec = r1(Math.min(beat.toSec, t + dur));
      dialogue.push({ ...l });
      t += dur + 0.3;
    }
  }

  const audio = clip.audio || {};
  return {
    clipNumber: n,
    title: trim(clip.title, 60) || `Clip ${n}`,
    storyPurpose: trim(clip.storyPurpose, 400),
    transition: n === 1 ? 'opening' : (clip.transition === 'cut' ? 'cut' : 'continuous'),
    location: trim(clip.location, 240),
    environment: trim(clip.environment, 1200),
    cast,
    firstFrame: trim(clip.firstFrame, 1500),
    beats,
    dialogue,
    audio: {
      ambience: trim(audio.ambience, 400),
      foley: trim(audio.foley, 400),
      music: trim(audio.music, 300)
    },
    lastFrame: trim(clip.lastFrame, 1500),
    continuityOut: trim(clip.continuityOut, 500)
  };
}

// ============================================================
// Main entry
// ============================================================

export async function generateProject({
  apiKey,
  story,
  character = '',
  totalDuration = 15,
  clipDuration = 5,
  modelId = 'seedance',
  videoModel,
  style = 'Ultra-photorealistic live-action cinema',
  aspectRatio = '16:9',
  pacing = 'Classical Narrative',
  references = [],
  llmModel = DEFAULT_LLM,
  batchSize,
  retries = 2,
  signal,
  onProgress
}) {
  if (!str(story)) throw new Error('Story premise is required.');
  if (!(totalDuration > 0) || !(clipDuration > 0)) throw new Error('Durations must be positive numbers.');

  const slots = slotsFor(totalDuration, clipDuration);
  if (slots.length > 120) throw new Error('Maximum 120 clips per project.');

  const profile = profileFor(modelId, clipDuration);
  // Longer clips carry more text; keep batches small enough to stay precise and inside token limits.
  const perBatch = batchSize || (clipDuration >= 10 ? 4 : 6);
  const blocks = makeBlocks(slots, Math.max(1, Math.ceil(slots.length / 40)));
  const startedAt = Date.now();
  const usage = { prompt_tokens: 0, completion_tokens: 0, total_tokens: 0 };
  let llmCalls = 0;

  const ask = async (systemPrompt, payload, maxOutputTokens, check) => {
    let lastError;
    for (let attempt = 0; attempt <= retries; attempt++) {
      try {
        llmCalls++;
        const userPrompt = JSON.stringify(
          lastError
            ? { ...payload, repairInstruction: `Your previous answer was rejected: ${lastError.message}. Fix this and return the complete JSON again.` }
            : payload,
          null,
          1
        );
        const { text, usage: u } = await callOpenAI({
          apiKey, model: llmModel, systemPrompt, userPrompt, maxOutputTokens, signal
        });
        for (const k of Object.keys(usage)) usage[k] += u?.[k] || 0;
        return check(parseJson(text));
      } catch (err) {
        lastError = err;
        if (signal?.aborted || /HTTP 4(01|03|04|29)/.test(err.message)) throw err;
      }
    }
    throw new Error(`Could not get valid output from the LLM after ${retries + 1} attempts: ${lastError.message}`);
  };

  // ---------------- Stage 1: plan ----------------
  onProgress?.({ phase: 'planning', completed: 0, total: slots.length });

  const { bible, outline } = await ask(
    PLAN_SYSTEM,
    {
      goal: 'Plan the complete story across the fixed blocks.',
      story,
      characterNotesFromUser: character,
      pacing,
      userVisualStyle: style,
      aspectRatio,
      totalDurationSec: totalDuration,
      clipDurationSec: clipDuration,
      clipCount: slots.length,
      targetVideoModel: videoModel?.name || modelId,
      references,
      requiredBlocks: blocks
    },
    Math.min(14000, 3500 + blocks.length * 320),
    result => {
      if (!result.storyBible || !Array.isArray(result.outline)) throw new Error('Missing storyBible or outline');
      if (
        result.outline.length !== blocks.length ||
        blocks.some((b, i) => Number(result.outline[i]?.blockId) !== b.blockId)
      ) {
        throw new Error(`Outline must contain exactly ${blocks.length} ordered entries with blockId 1..${blocks.length}`);
      }
      return {
        bible: normalizeBible(result.storyBible),
        outline: result.outline.map((o, i) => ({ ...o, ...blocks[i] }))
      };
    }
  );

  // ---------------- Stage 2: clips ----------------
  const clips = [];
  const recentDialogue = [];
  let state = {
    location: 'Story opening',
    lighting: 'Not yet established',
    lastFrame: 'Nothing has been shot yet',
    characters: {},
    props: {},
    plotProgress: 'The story has not started',
    nextAction: 'Open on the hook'
  };

  for (let offset = 0; offset < slots.length; offset += perBatch) {
    const batch = slots.slice(offset, offset + perBatch);
    const first = batch[0];
    const last = batch[batch.length - 1];
    const relevantOutline = outline.filter(b => b.endSec > first.startSec && b.startSec < last.endSec);

    const { written, endState } = await ask(
      CLIP_SYSTEM,
      {
        task: `Write exactly ${batch.length} clips with clipNumbers ${batch.map(s => s.clipNumber).join(', ')}.`,
        storyBible: bible,
        outline: relevantOutline,
        userVisualStyle: style,
        pacing,
        aspectRatio,
        targetVideoModel: videoModel?.name || modelId,
        modelProfile: {
          maxBeats: profile.maxBeats,
          maxCast: profile.maxCast,
          wordsPerSec: profile.wordsPerSec
        },
        totalClips: slots.length,
        previousEndingState: state,
        recentDialogue,
        requiredClipSlots: batch.map(s => ({
          clipNumber: s.clipNumber,
          durationSec: s.durationSec,
          timecode: s.timecode,
          isFinalClip: s.clipNumber === slots.length
        }))
      },
      Math.min(16000, 2000 + batch.length * (1100 + profile.maxBeats * 250)),
      result => {
        if (!Array.isArray(result.clips) || result.clips.length !== batch.length) {
          throw new Error(`Expected ${batch.length} clips, got ${result.clips?.length}`);
        }
        if (!result.endState || !str(result.endState.lastFrame)) throw new Error('Missing endState.lastFrame');
        return {
          written: batch.map((slot, i) => normalizeClip(result.clips[i], slot, bible, profile)),
          endState: result.endState
        };
      }
    );

    written.forEach((clip, i) => {
      const slot = batch[i];
      const masterPrompt = renderClipPrompt({
        modelId, videoModel, slot, clip, bible, style, aspectRatio, references,
        totalClips: slots.length
      });
      const cam = clip.beats[0].shot;

      clips.push({
        ...slot,
        title: clip.title,
        continuityNote:
          clip.transition === 'continuous'
            ? `Continuous - start this clip from the last frame of Clip ${slot.clipNumber - 1}.`
            : clip.transition === 'cut'
              ? `Hard cut - new scene. Generate a fresh start frame (see Start Frame).`
              : 'Opening shot - generate or upload the start frame.',
        camera: clip.beats
          .map(b => [b.shot.framing, b.shot.movement, b.shot.lens].filter(Boolean).join(', '))
          .join('  →  ') || [cam.framing, cam.movement].filter(Boolean).join(', '),
        transition: clip.transition,
        storyPurpose: clip.storyPurpose,
        location: clip.location,
        firstFrame: clip.firstFrame,
        lastFrame: clip.lastFrame,
        beats: clip.beats,
        dialogue: clip.dialogue,
        cast: clip.cast.map(c => ({ ...c, name: bible.characters.find(x => x.id === c.id)?.name })),
        audio: clip.audio,
        negativePrompt: buildNegativePrompt({ clip, bible }),
        masterPrompt
      });

      for (const l of clip.dialogue) recentDialogue.push(`${l.speakerName}: "${l.text}"`);
    });
    recentDialogue.splice(0, Math.max(0, recentDialogue.length - 8));

    const lastClip = written[written.length - 1];
    state = {
      location: trim(endState.location, 240),
      lighting: trim(endState.lighting, 300),
      lastFrame: lastClip.lastFrame,
      characters: endState.characters || {},
      props: endState.props || {},
      plotProgress: trim(endState.plotProgress, 800),
      nextAction: trim(endState.nextAction, 400)
    };

    onProgress?.({ phase: 'clips', completed: clips.length, total: slots.length });
  }

  return {
    id: `proj_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`,
    createdAt: new Date().toISOString(),
    projectTitle: bible.title || str(story).split(/\s+/).slice(0, 5).join(' '),
    totalDuration,
    clipDuration,
    clipCount: clips.length,
    targetModel: modelId,
    aspectRatio,
    storyBible: bible,
    outline,
    clips,
    finalState: state,
    modelUsed: llmModel,
    usage,
    llmCalls,
    latencyMs: Date.now() - startedAt
  };
}
