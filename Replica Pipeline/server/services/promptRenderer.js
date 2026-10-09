/**
 * Prompt Renderer - turns a validated clip (structured JSON) into the text sent to the video model.
 *
 * Seedance reads natural, concrete prose best: who/where, a timed shot list, quoted dialogue with delivery,
 * sound, and a short list of rules. So we do NOT pad prompts with boilerplate banners or long negative lists, and
 * we never hard-code an action-movie template (single protagonist, no dialogue, never-static camera...).
 */

const BASE_AVOID = [
  'face or identity drift',
  'unmotivated outfit changes',
  'extra or fused fingers and limbs',
  'duplicate or morphing characters',
  'objects appearing or vanishing',
  'plastic skin, flicker, warping',
  'lip movement from anyone who is not speaking',
  'subtitles, captions, on-screen text, logos, watermarks'
];

export function buildNegativePrompt({ clip, bible }) {
  const items = [...BASE_AVOID];
  const genre = `${bible?.genre || ''}`.toLowerCase();
  // Keep grounded stories grounded.
  if (!/sci|fantasy|cyber|horror|action|war|thriller/.test(genre)) {
    items.push('sci-fi elements, neon, futuristic tech, weapons, explosions');
  }
  if (!clip.dialogue?.length) items.push('speech, lip-sync');
  return items.join(', ');
}

const clean = s => (s || '').replace(/\s+/g, ' ').trim();
const sentence = s => {
  const t = clean(s);
  if (!t) return t;
  const cased = t[0].toUpperCase() + t.slice(1);
  return /[.!?"]$/.test(cased) ? cased : `${cased}.`;
};
const secs = n => (Number.isInteger(n) ? `${n}` : n.toFixed(1));

function referenceToken(character, references = []) {
  const name = character.name.toLowerCase();
  const first = name.split(/\s+/)[0];
  const hit = references.find(r => {
    const n = (r.name || '').toLowerCase();
    return n && (n === name || n === first || name.includes(n));
  });
  return hit?.token || null;
}

function castLine(entry, bible, references) {
  const ch = bible.characters.find(c => c.id === entry.id);
  if (!ch) return '';
  const outfit = ch.outfits.find(o => o.id === entry.outfitId) || ch.outfits[0];
  const token = referenceToken(ch, references);
  const head = token ? `${token} is ${ch.name}` : ch.name;
  const start = entry.state ? ` Starts: ${clean(entry.state)}.` : '';
  return (
    `- ${head}: ${sentence(ch.appearance)} Wearing ${clean(outfit.description).replace(/\.$/, '')}.` +
    `${start} Voice: ${clean(ch.voice).replace(/\.$/, '')}.`
  );
}

function shotLabel(shot) {
  return [shot.framing, shot.angle, shot.lens, shot.movement].map(clean).filter(Boolean).join(', ');
}

function dialogueLine(l) {
  const how = clean(l.delivery);
  return `${l.speakerName}${how ? ` (${how})` : ''} says: "${l.text}"`;
}

function startFrameBlock(clip, slot) {
  if (clip.transition === 'continuous') {
    return (
      `START FRAME (use the final frame of the previous clip as the first-frame image): ${sentence(clip.firstFrame)}\n` +
      'Continue the same moment with identical positions, poses, props and lighting - no reset.'
    );
  }
  if (clip.transition === 'cut') {
    return `START FRAME (new scene - hard cut from the previous clip): ${sentence(clip.firstFrame)}`;
  }
  return `START FRAME (opening shot): ${sentence(clip.firstFrame)}`;
}

// ------------------------------------------------------------
// Seedance (full): timed shot list with inline dialogue
// ------------------------------------------------------------
function renderSeedance({ slot, clip, bible, style, aspectRatio, references, totalClips }) {
  const look = bible.look || {};
  const lookLine = [
    style && `Base look: ${clean(style)}`,
    look.grade && `Grade: ${clean(look.grade)}`,
    look.lighting && `Light: ${clean(look.lighting)}`,
    look.lensing && `Lens: ${clean(look.lensing)}`
  ].filter(Boolean).join('. ');

  const refLines = (references || []).length
    ? 'REFERENCES:\n' + references.map(r => `- ${r.token}: ${clean(r.description || r.name)}`).join('\n') + '\n\n'
    : '';

  const shots = clip.beats.map(b => {
    const lines = [
      `[${secs(b.fromSec)}–${secs(b.toSec)}s] ${shotLabel(b.shot)}.`,
      `Action: ${sentence(b.action)}`
    ];
    if (b.acting) lines.push(`Performance: ${sentence(b.acting)}`);
    for (const l of b.dialogue) lines.push(dialogueLine(l));
    return lines.join('\n');
  }).join('\n\n');

  const speaks = clip.dialogue.length > 0;
  const audio = [
    clip.audio.ambience && `Ambience: ${sentence(clip.audio.ambience)}`,
    clip.audio.foley && `Foley: ${sentence(clip.audio.foley)}`,
    `Music: ${clean(clip.audio.music) || 'none'}.`
  ].filter(Boolean).join(' ');

  const rules = [
    `Exactly ${slot.durationSec} seconds, ${aspectRatio}, photorealistic live-action footage.`,
    'Keep every character\'s face, hair, body and outfit identical in every frame.',
    speaks
      ? 'Only the character currently speaking moves their lips, in sync with the quoted words; say the words exactly as written.'
      : 'No one speaks in this clip.',
    'Natural skin texture, believable hand and cloth physics, no morphing.',
    'No subtitles, captions, text or logos.'
  ].join(' ');

  return [
    `${bible.title || 'Film'} — Clip ${slot.clipNumber} of ${totalClips} (${slot.timecode})`,
    '',
    refLines + startFrameBlock(clip, slot),
    '',
    `SETTING: ${sentence(clip.location)} ${sentence(clip.environment)}`,
    '',
    'CAST (identical in every frame):',
    clip.cast.map(c => castLine(c, bible, references)).filter(Boolean).join('\n'),
    '',
    'SHOT LIST:',
    shots,
    '',
    `AUDIO: ${audio}`,
    '',
    `END FRAME (hold this composition for the last half second): ${sentence(clip.lastFrame)}`,
    '',
    `LOOK: ${lookLine}.`,
    `RULES: ${rules}`,
    `AVOID: ${buildNegativePrompt({ clip, bible })}.`
  ].join('\n').replace(/\n{3,}/g, '\n\n').trim();
}

// ------------------------------------------------------------
// Seedance Mini: compact single-paragraph prompt
// ------------------------------------------------------------
function renderSeedanceMini({ slot, clip, bible, style, aspectRatio, references }) {
  const look = bible.look || {};
  const cast = clip.cast.map(entry => {
    const ch = bible.characters.find(c => c.id === entry.id);
    if (!ch) return '';
    const outfit = ch.outfits.find(o => o.id === entry.outfitId) || ch.outfits[0];
    const token = referenceToken(ch, references);
    return `${token ? `${token} (${ch.name})` : ch.name}, ${clean(ch.appearance).replace(/\.$/, '')}, wearing ${clean(outfit.description).replace(/\.$/, '')}`;
  }).filter(Boolean).join('; ');

  const timeline = clip.beats.map(b => {
    const spoken = b.dialogue.map(dialogueLine).join(' ');
    return (
      `${secs(b.fromSec)}-${secs(b.toSec)}s: ${shotLabel(b.shot)}. ${sentence(b.action)} ${sentence(b.acting)}` +
      `${spoken ? ` ${spoken}` : ''}`
    ).replace(/\s+/g, ' ');
  }).join(' ');

  const sound = [clip.audio.ambience, clip.audio.foley].map(clean).filter(Boolean).join('; ');

  return [
    `${slot.durationSec}s ${aspectRatio} photorealistic cinematic shot. ${[look.grade, look.lighting].map(clean).filter(Boolean).join(', ') || clean(style)}.`,
    clip.transition === 'continuous'
      ? `Continue from the previous clip's final frame (use it as first frame): ${sentence(clip.firstFrame)}`
      : `Opening frame: ${sentence(clip.firstFrame)}`,
    `Setting: ${sentence(clip.location)} ${sentence(clip.environment)}`,
    `Cast: ${cast}.`,
    timeline,
    sound ? `Sound: ${sentence(sound)}` : '',
    `Ends on: ${sentence(clip.lastFrame)}`,
    'Keep faces and outfits identical throughout; only the speaker moves their lips, matching the quoted words exactly; no subtitles, text or logos.'
  ].filter(Boolean).join(' ');
}

// ------------------------------------------------------------
// Generic fallback for other video models
// ------------------------------------------------------------
function renderGeneric(args) {
  const { videoModel } = args;
  const prefix = videoModel?.promptPrefix || '';
  return `${prefix}${renderSeedance(args)}`.trim();
}

export function renderClipPrompt(args) {
  const id = args.modelId || '';
  if (id === 'seedance-mini') return renderSeedanceMini(args);
  if (id === 'seedance') return renderSeedance(args);
  return renderGeneric(args);
}
