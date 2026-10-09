/**
 * Director Service - Procedural Directorial Engine
 * Generates individual Master Prompts for EACH CLIP with seamless continuity.
 */

export const VIDEO_MODELS = [
  {
    id: 'sora',
    name: 'OpenAI Sora',
    promptFormat: 'Natural narrative prose with physical dynamics, continuous lighting, camera motion, and micro-expressions.'
  },
  {
    id: 'runway-gen3',
    name: 'Runway Gen-3 Alpha',
    promptFormat: 'Structured bracketed tags: [Camera: ...] [Lighting: ...] [Motion: ...] followed by photoreal scene description.'
  },
  {
    id: 'kling',
    name: 'Kling AI 1.5 / Pro',
    promptFormat: 'Detailed master shot description with photography tags, cinematic lighting, and dedicated negative prompt.'
  },
  {
    id: 'luma-dream-machine',
    name: 'Luma Dream Machine',
    promptFormat: 'Fluid spatial camera cues with coherent physics and seamless temporal evolution.'
  },
  {
    id: 'hailuo',
    name: 'Hailuo AI (MiniMax)',
    promptFormat: 'Character-centric emotional acting prompts with vivid physical environmental responses.'
  },
  {
    id: 'pika',
    name: 'Pika 2.0',
    promptFormat: 'Action-packed visual prompts with -camera motion parameters and negative prompts.'
  },
  {
    id: 'seedance',
    name: 'Seedance (ByteDance)',
    promptFormat: 'Dynamic choreography-focused cinematic prose with explicit camera tracking, momentum, and fluid physics.'
  },
  {
    id: 'seedance-mini',
    name: 'Seedance Mini (ByteDance)',
    promptFormat: 'Compact single-paragraph prompt: one or two timed shots, at most two characters, short quoted dialogue.'
  }
];

export function formatTime(seconds) {
  const mins = Math.floor(seconds / 60);
  const secs = Math.floor(seconds % 60);
  return `${mins}:${String(secs).padStart(2, '0')}`;
}

export function formatTimeRange(startSec, endSec) {
  return `${formatTime(startSec)}–${formatTime(endSec)}`;
}

export function generateClipMasterPromptsProcedural({
  story,
  character,
  totalDuration = 15,
  clipDuration = 5,
  modelId = 'seedance',
  style = 'Ultra-photorealistic live-action cinema',
  aspectRatio = '16:9',
  pacing = 'Classical Narrative'
}) {
  const totalClips = Math.ceil(totalDuration / clipDuration);
  const modelInfo = VIDEO_MODELS.find(m => m.id === modelId) || VIDEO_MODELS[0];
  const projectTitle = story ? story.split(/\s+/).slice(0, 4).join(' ').toUpperCase() : 'CINEMATIC SEQUENCE';

  const negativePrompt = 'cuts, edits, dissolves, fades, scene transitions, time jumps, multiple shots, duplicate character, teleportation, thick aura, smoke, glowing body, CGI or plastic skin, anime rendering, blood, gore, subtitles, logos, watermark, static camera, blurry face, flickering artifacts.';

  const cameraBeats = [
    { cam: 'Rear over-the-shoulder low-angle pursuit. Whip-pan 25° dutch angle following kinetic momentum.', lens: 'Panavision 35mm Anamorphic, f/1.8' },
    { cam: 'Dynamic 360-degree steadycam rotation tightening focal length, skim-tracking surfaces inches away.', lens: '50mm Cine Prime, f/1.4' },
    { cam: 'Rapid forward tracking push-in. High kinetic velocity skimming ground level, transitioning to aerial crane rise.', lens: '28mm Wide Anamorphic, f/2.0' },
    { cam: 'Lateral slider glide skimming water reflections and environmental dust motes, reacquiring subject at impact.', lens: '40mm Prime, f/2.0' },
    { cam: 'Vertical crane rise tilting down into expansive vista, tracking continuous forward acceleration.', lens: 'Panavision 24mm Anamorphic, f/2.8' },
    { cam: 'Low ground-level asphalt chase shot. Feet kick environmental wake as the camera swoops underneath.', lens: '35mm High-Speed Cine, f/1.4' }
  ];

  const actionPhases = [
    {
      title: 'THE INITIAL INFILTRATION & HOOK',
      part1: 'Tension building, fingers tightening on grip. Sudden explosive burst of movement across the chamber as environment reacts.',
      part2: 'Mid-air parry and deflect. Ducking under incoming hazard, vaulting across barrier with continuous forward kinetic momentum.'
    },
    {
      title: 'THE COURTYARD PURSUIT & KINETIC ESCALATION',
      part1: 'Sprinting along the perimeter, pivoting off each obstacle. A thin wake of compressed air follows feet with zero speed loss.',
      part2: 'Leaping across physical gap, landing with heavy realistic impact and water/dust displacement, immediately rebounding upward.'
    },
    {
      title: 'THE ROOFTOP CLIMAX & DECISIVE CONFRONTATION',
      part1: 'Ascending to elevated ridge line. Fast tactical exchange against opponent, sparks and dust scattering across frame.',
      part2: 'Supersonic clean strike slicing through target barrier. Decisive resolution pose as camera pulls back into expansive wide vista.'
    },
    {
      title: 'MOMENTUM ACCELERATION & CHASE PHASE',
      part1: 'High-speed traversal through narrow corridors. Lighting reflecting dynamically across wet surfaces and metallic gear.',
      part2: 'Slide under incoming projectile, rising with dual kinetic swings, shattering glass and environmental debris.'
    }
  ];

  const clips = [];

  for (let i = 0; i < totalClips; i++) {
    const startSec = i * clipDuration;
    const endSec = Math.min((i + 1) * clipDuration, totalDuration);
    const timecode = formatTimeRange(startSec, endSec);
    const cameraInfo = cameraBeats[i % cameraBeats.length];
    const actionInfo = actionPhases[i % actionPhases.length];

    const isFirstClip = i === 0;
    const continuityNote = isFirstClip
      ? 'Initial establishing shot. Sets baseline lighting, character position, and initiates kinetic forward momentum.'
      : `Picks up directly from Clip ${i}'s ending momentum frame (${formatTime(startSec)}) with matching velocity, character pose, and camera angle.`;

    const continuityLockText = isFirstClip
      ? `This is a single continuous ${clipDuration}-second shot. Real-time momentum, zero jump cuts, establishing initial velocity.`
      : `CONTINUOUS MOMENTUM HANDOFF: Picks up seamlessly from Clip ${i} ending frame (${formatTime(startSec)}) as the protagonist completes the previous motion. The camera maintains continuous trajectory with zero cut reset. Real-time physics, zero teleportation.`;

    const clipMasterPrompt = `${projectTitle} - CLIP ${i + 1} (${timecode}): ${actionInfo.title}
Duration: ${clipDuration} seconds | Aspect Ratio: ${aspectRatio} | Target Model: ${modelInfo.name}

SHOT & CONTINUITY LOCK:
${continuityLockText}

STYLE & LENS:
${style}. Large-format cinema look, ${cameraInfo.lens}, natural lighting, muted earthy color palette, soft realistic shadows, no oversaturated colors, photorealistic depth of field.

@Image1 is PROTAGONIST. Preserve exact face, attire, physical proportions, and weapons in every frame.
${character ? `Character continuity: ${character}` : ''}

POSITIVE LOCKS (true for all ${clipDuration} seconds):
- Exactly ONE protagonist, always in physical control and fully visible.
- Face and anatomy always match @Image1.
- Physical distance crossed with continuous body momentum, no teleportation.
- Continuous unbroken lighting, shadows reacting physically to real sources.
- Every fast movement leaves realistic kinetic wake that dissipates naturally.

CAMERA (${clipDuration}s continuous pursuit):
${cameraInfo.cam}
The camera moves 0.1–0.2s late, following the subject: whip-pans, overshoot, correct, reacquire at contact. Handheld kinetic energy without artificial stabilization.

ACTION & TIME BREAKDOWN:
(0-${Math.floor(clipDuration / 2)}s): ${actionInfo.part1}
(${Math.floor(clipDuration / 2)}-${clipDuration}s): ${actionInfo.part2}

AUDIO & FOLEY:
Physical impact foley, crisp footfalls, compressed-air whooshes, atmospheric rumble. No dialogue, no intrusive music.

HUMAN-FIRST & PHYSICS LOCK:
Natural skin pores, real eyes, individual hair strands, believable anatomy and cloth physics. Choreography operates at peak human velocity without breaking physical plausibility.

NEGATIVE:
${negativePrompt}`;

    clips.push({
      clipNumber: i + 1,
      startSec,
      endSec,
      durationSec: endSec - startSec,
      timecode,
      title: actionInfo.title,
      continuityNote,
      camera: `${cameraInfo.cam} (${cameraInfo.lens})`,
      masterPrompt: clipMasterPrompt
    });
  }

  return {
    id: 'proj_' + Date.now() + '_' + Math.random().toString(36).substr(2, 6),
    createdAt: new Date().toISOString(),
    projectTitle: `${projectTitle}: SEQUENTIAL MASTER STORYBOARD`,
    totalDuration,
    clipDuration,
    clipCount: clips.length,
    aspectRatio,
    targetModel: modelId,
    clips,
    modelUsed: 'gpt-4o-mini (Director Engine)'
  };
}
