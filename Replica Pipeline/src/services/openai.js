// import { VIDEO_MODELS } from '../constants/models';

// export function formatTime(seconds) {
//   const mins = Math.floor(seconds / 60);
//   const secs = Math.floor(seconds % 60);
//   return `${mins}:${String(secs).padStart(2, '0')}`;
// }

// export function formatTimeRange(startSec, endSec) {
//   return `${formatTime(startSec)}–${formatTime(endSec)}`;
// }

// export function generateMockClipMasterPrompts({
//   story,
//   character,
//   totalDuration = 15,
//   clipDuration = 5,
//   modelId = 'seedance',
//   style = 'Ultra-photorealistic live-action cinema',
//   aspectRatio = '16:9',
//   pacing = 'Classical Narrative'
// }) {
//   const totalClips = Math.ceil(totalDuration / clipDuration);
//   const modelInfo = VIDEO_MODELS.find(m => m.id === modelId) || VIDEO_MODELS[0];
//   const projectTitle = story ? story.split(/\s+/).slice(0, 4).join(' ').toUpperCase() : 'CINEMATIC SEQUENCE';

//   const negativePrompt = 'cuts, edits, dissolves, fades, scene transitions, time jumps, multiple shots, duplicate character, teleportation, thick aura, smoke, glowing body, CGI or plastic skin, anime rendering, blood, gore, subtitles, logos, watermark, static camera, blurry face, flickering artifacts.';

//   const cameraBeats = [
//     { cam: 'Rear over-the-shoulder low-angle pursuit. Whip-pan 25° dutch angle following kinetic momentum.', lens: 'Panavision 35mm Anamorphic, f/1.8' },
//     { cam: 'Dynamic 360-degree steadycam rotation tightening focal length, skim-tracking surfaces inches away.', lens: '50mm Cine Prime, f/1.4' },
//     { cam: 'Rapid forward tracking push-in. High kinetic velocity skimming ground level, transitioning to aerial crane rise.', lens: '28mm Wide Anamorphic, f/2.0' },
//     { cam: 'Lateral slider glide skimming water reflections and environmental dust motes, reacquiring subject at impact.', lens: '40mm Prime, f/2.0' },
//     { cam: 'Vertical crane rise tilting down into expansive vista, tracking continuous forward acceleration.', lens: 'Panavision 24mm Anamorphic, f/2.8' },
//     { cam: 'Low ground-level asphalt chase shot. Feet kick environmental wake as the camera swoops underneath.', lens: '35mm High-Speed Cine, f/1.4' }
//   ];

//   const actionPhases = [
//     {
//       title: 'THE INITIAL INFILTRATION & HOOK',
//       part1: 'Tension building, fingers tightening on grip. Sudden explosive burst of movement across the chamber as environment reacts.',
//       part2: 'Mid-air parry and deflect. Ducking under incoming hazard, vaulting across barrier with continuous forward kinetic momentum.'
//     },
//     {
//       title: 'THE COURTYARD PURSUIT & KINETIC ESCALATION',
//       part1: 'Sprinting along the perimeter, pivoting off each obstacle. A thin wake of compressed air follows feet with zero speed loss.',
//       part2: 'Leaping across physical gap, landing with heavy realistic impact and water/dust displacement, immediately rebounding upward.'
//     },
//     {
//       title: 'THE ROOFTOP CLIMAX & DECISIVE CONFRONTATION',
//       part1: 'Ascending to elevated ridge line. Fast tactical exchange against opponent, sparks and dust scattering across frame.',
//       part2: 'Supersonic clean strike slicing through target barrier. Decisive resolution pose as camera pulls back into expansive wide vista.'
//     },
//     {
//       title: 'MOMENTUM ACCELERATION & CHASE PHASE',
//       part1: 'High-speed traversal through narrow corridors. Lighting reflecting dynamically across wet surfaces and metallic gear.',
//       part2: 'Slide under incoming projectile, rising with dual kinetic swings, shattering glass and environmental debris.'
//     }
//   ];

//   const clips = [];

//   for (let i = 0; i < totalClips; i++) {
//     const startSec = i * clipDuration;
//     const endSec = Math.min((i + 1) * clipDuration, totalDuration);
//     const timecode = formatTimeRange(startSec, endSec);
//     const cameraInfo = cameraBeats[i % cameraBeats.length];
//     const actionInfo = actionPhases[i % actionPhases.length];

//     const isFirstClip = i === 0;
//     const continuityNote = isFirstClip
//       ? 'Initial establishing shot. Sets baseline lighting, character position, and initiates kinetic forward momentum.'
//       : `Picks up directly from Clip ${i}'s ending momentum frame (${formatTime(startSec)}) with matching velocity, character pose, and camera angle.`;

//     const continuityLockText = isFirstClip
//       ? `This is a single continuous ${clipDuration}-second shot. Real-time momentum, zero jump cuts, establishing initial velocity.`
//       : `CONTINUOUS MOMENTUM HANDOFF: Picks up seamlessly from Clip ${i} ending frame (${formatTime(startSec)}) as the protagonist completes the previous motion. The camera maintains continuous trajectory with zero cut reset. Real-time physics, zero teleportation.`;

//     const clipMasterPrompt = `${projectTitle} - CLIP ${i + 1} (${timecode}): ${actionInfo.title}
// Duration: ${clipDuration} seconds | Aspect Ratio: ${aspectRatio} | Target Model: ${modelInfo.name}

// SHOT & CONTINUITY LOCK:
// ${continuityLockText}

// STYLE & LENS:
// ${style}. Large-format cinema look, ${cameraInfo.lens}, natural lighting, muted earthy color palette, soft realistic shadows, no oversaturated colors, photorealistic depth of field.

// @Image1 is PROTAGONIST. Preserve exact face, attire, physical proportions, and weapons in every frame.
// ${character ? `Character continuity: ${character}` : ''}

// POSITIVE LOCKS (true for all ${clipDuration} seconds):
// - Exactly ONE protagonist, always in physical control and fully visible.
// - Face and anatomy always match @Image1.
// - Physical distance crossed with continuous body momentum, no teleportation.
// - Continuous unbroken lighting, shadows reacting physically to real sources.
// - Every fast movement leaves realistic kinetic wake that dissipates naturally.

// CAMERA (${clipDuration}s continuous pursuit):
// ${cameraInfo.cam}
// The camera moves 0.1–0.2s late, following the subject: whip-pans, overshoot, correct, reacquire at contact. Handheld kinetic energy without artificial stabilization.

// ACTION & TIME BREAKDOWN:
// (0-${Math.floor(clipDuration / 2)}s): ${actionInfo.part1}
// (${Math.floor(clipDuration / 2)}-${clipDuration}s): ${actionInfo.part2}

// AUDIO & FOLEY:
// Physical impact foley, crisp footfalls, compressed-air whooshes, atmospheric rumble. No dialogue, no intrusive music.

// HUMAN-FIRST & PHYSICS LOCK:
// Natural skin pores, real eyes, individual hair strands, believable anatomy and cloth physics. Choreography operates at peak human velocity without breaking physical plausibility.

// NEGATIVE:
// ${negativePrompt}`;

//     clips.push({
//       clipNumber: i + 1,
//       startSec,
//       endSec,
//       durationSec: endSec - startSec,
//       timecode,
//       title: actionInfo.title,
//       continuityNote,
//       camera: `${cameraInfo.cam} (${cameraInfo.lens})`,
//       masterPrompt: clipMasterPrompt
//     });
//   }

//   return {
//     id: 'proj_' + Date.now() + '_' + Math.random().toString(36).substr(2, 6),
//     createdAt: new Date().toISOString(),
//     projectTitle: `${projectTitle}: SEQUENTIAL MASTER STORYBOARD`,
//     totalDuration,
//     clipDuration,
//     clipCount: clips.length,
//     aspectRatio,
//     targetModel: modelId,
//     clips,
//     modelUsed: 'gpt-4o-mini (Director Engine)'
//   };
// }



// import { VIDEO_MODELS } from '../constants/models';

// /**
//  * AI STORYBOARD & VIDEO PROMPT GENERATOR
//  *
//  * Features:
//  * - Complete story planning
//  * - Exact clip timeline
//  * - Batch LLM generation
//  * - Detailed cinematic video prompts
//  * - Character and prop continuity
//  * - Exact dialogue and timing
//  * - First/last frame specifications
//  * - OpenAI API integration
//  * - JSON validation and retries
//  *
//  * IMPORTANT:
//  * This function is asynchronous.
//  * Use: await generateMockClipMasterPrompts(...)
//  *
//  * For Node.js:
//  * Set OPENAI_API_KEY in the server environment.
//  *
//  * For React/browser:
//  * Supply generateJSON connected to your own backend.
//  * NEVER expose API keys in frontend code.
//  */

// const NEGATIVE_PROMPT = [
//   'face or character identity drift',
//   'unexplained wardrobe changes',
//   'extra fingers or limbs',
//   'distorted anatomy',
//   'duplicate characters',
//   'objects appearing or disappearing without explanation',
//   'flicker, morphing, unnatural skin',
//   'wrong speaker lip-sync',
//   'unrequested subtitles, text, logos, or watermarks'
// ].join(', ');


// // ============================================================
// // TIME UTILITIES
// // ============================================================

// export function formatTime(seconds) {
//   const wholeMinutes = Math.floor(seconds / 60);

//   const remaining = Number(
//     (seconds - wholeMinutes * 60).toFixed(3)
//   );

//   const fractional = remaining % 1
//     ? String(
//       Number((remaining % 1).toFixed(3))
//     ).slice(1)
//     : '';

//   return (
//     `${wholeMinutes}:` +
//     `${String(Math.floor(remaining)).padStart(2, '0')}` +
//     fractional
//   );
// }

// export function formatTimeRange(startSec, endSec) {
//   return `${formatTime(startSec)}–${formatTime(endSec)}`;
// }

// const jsonText = value =>
//   JSON.stringify(value, null, 2);

// const arr = value =>
//   Array.isArray(value) ? value : [];

// const str = value =>
//   typeof value === 'string' ? value.trim() : '';

// const trim = (value, size = 800) =>
//   str(value).slice(0, size);

// const round = value =>
//   Number(value.toFixed(3));


// // ============================================================
// // CLIP TIMELINE
// // ============================================================

// function slotsFor(totalDuration, clipDuration) {
//   const count = Math.ceil(
//     totalDuration / clipDuration
//   );

//   return Array.from(
//     { length: count },
//     (_, index) => {
//       const startSec = round(
//         index * clipDuration
//       );

//       const endSec = round(
//         Math.min(
//           totalDuration,
//           (index + 1) * clipDuration
//         )
//       );

//       return {
//         clipNumber: index + 1,
//         startSec,
//         endSec,

//         durationSec: round(
//           endSec - startSec
//         ),

//         timecode: formatTimeRange(
//           startSec,
//           endSec
//         )
//       };
//     }
//   );
// }


// // ============================================================
// // STORY OUTLINE BLOCKS
// // ============================================================

// function makeBlocks(slots, blockSize) {
//   const blocks = [];

//   for (
//     let offset = 0;
//     offset < slots.length;
//     offset += blockSize
//   ) {
//     const group = slots.slice(
//       offset,
//       offset + blockSize
//     );

//     blocks.push({
//       blockId: blocks.length + 1,

//       startSec: group[0].startSec,

//       endSec:
//         group[group.length - 1].endSec,

//       firstClip:
//         group[0].clipNumber,

//       lastClip:
//         group[group.length - 1].clipNumber
//     });
//   }

//   return blocks;
// }


// // ============================================================
// // GLOBAL STORY PLANNER SYSTEM PROMPT
// // ============================================================

// const PLAN_SYSTEM = `
// You are an expert professional film screenwriter,
// narrative architect, story editor and film director.

// Return exactly ONE valid JSON object.
// Do not include markdown, comments or explanations.

// Your job is to create a complete, original, cinematic
// story using the user's actual premise, characters,
// duration, genre, and visual requirements.

// IMPORTANT STORY REQUIREMENTS:

// 1. Follow the user's premise exactly.

// 2. Preserve established character identities,
// relationships, motivations, conflicts and plot twists.

// 3. Do not invent unrelated action scenes, chases,
// fights or explosions.

// 4. Build a complete narrative structure:

// - Opening hook
// - Character introduction
// - Inciting incident
// - Conflict development
// - Escalating stakes
// - Major turning point
// - Climax
// - Resolution or intended cliffhanger

// 5. Maintain chronological and causal consistency.

// 6. Every narrative block must meaningfully progress
// the story.

// 7. Eliminate filler and repeated actions.

// 8. Distribute important story events across the
// ENTIRE requested runtime.

// 9. Respect the duration and the fixed timeline blocks.

// 10. Maintain consistent locations, objects,
// character descriptions and outfits.

// 11. Use believable emotional development.

// 12. Include meaningful story revelations at
// appropriate intervals.

// 13. The outline must contain exactly one entry
// for each requested block.

// 14. Preserve the requested block IDs and ordering.

// 15. Every event must be filmable.

// 16. Keep the global story bible concise but
// sufficiently detailed to maintain continuity.

// 17. The story bible should identify important
// props and character relationships.

// 18. Do not describe generic footage that could
// belong to any unrelated story.

// REQUIRED JSON:

// {
//   "storyBible": {
//     "title": "...",
//     "genre": "...",
//     "logline": "...",
//     "ending": "...",

//     "characters": [
//       {
//         "id": "c1",
//         "name": "...",
//         "appearance": "...",
//         "outfit": "...",
//         "voice": "...",
//         "personality": "...",
//         "motivation": "...",
//         "relationships": "..."
//       }
//     ],

//     "locations": [
//       {
//         "id": "l1",
//         "description": "...",
//         "lighting": "...",
//         "spatialLayout": "..."
//       }
//     ],

//     "unchangingFacts": [
//       "..."
//     ],

//     "visualStyleRules": [
//       "..."
//     ],

//     "dialogueStyle": "..."
//   },

//   "outline": [
//     {
//       "blockId": 1,
//       "setting": "...",
//       "events": "...",
//       "emotionalShift": "...",
//       "endingHook": "..."
//     }
//   ]
// }

// Every outline entry must correspond exactly to
// one supplied timeline block.
// `;


// // ============================================================
// // CLIP WRITER SYSTEM PROMPT
// // ============================================================

// const CLIP_SYSTEM = `
// You are a senior cinematic director, screenwriter,
// cinematographer, actor performance director,
// script supervisor and expert AI video prompt engineer.

// Return exactly ONE valid JSON object.
// No markdown or explanation.

// You receive:

// - The global story bible
// - Exact timeline slots
// - Relevant narrative outline
// - The previous batch's ending state
// - Visual style
// - Character details
// - Video generation model

// Generate a uniquely written, production-quality
// video script for EVERY requested clip.

// ============================================================
// 1. STORY PROGRESSION
// ============================================================

// Every clip must advance the actual story.

// Each clip must establish, reveal, develop,
// escalate, resolve or transition an important
// narrative element.

// Do not create meaningless filler.

// Do not repeat previous actions unnecessarily.

// Do not turn romantic drama into an action movie,
// or introduce any unwanted genre elements.

// Respect the user's intended story.

// ============================================================
// 2. EXACT CLIP TIMING
// ============================================================

// Generate exactly the requested clip numbers.

// Never skip or merge clips.

// Every clip has a fixed duration.

// Create 1 to 3 precise action beats per clip.

// Action beats must cover the entire duration
// without gaps or overlaps.

// All beat timestamps start at 0 within that clip.

// For example, a five-second clip:

// 0.0–1.5 seconds:
// A woman hears the door open and slowly
// turns her head toward the doorway.

// 1.5–3.0 seconds:
// She recognizes the man entering and stops
// mid-motion. Her eyes widen.

// 3.0–5.0 seconds:
// She lowers the phone in her right hand
// and steps backward.

// Describe realistic timing.

// Do not overload five seconds with actions
// requiring ten or twenty seconds.

// ============================================================
// 3. CHARACTER IDENTITY
// ============================================================

// Keep all characters consistent.

// For each visible character, describe:

// - Identity
// - Face and appearance
// - Clothing
// - Hairstyle
// - Body position
// - Position within the environment
// - Facial expression
// - Eye direction
// - Hand movements
// - Body language
// - Current emotional state
// - Interaction with props and other characters

// Maintain the same appearance in subsequent clips.

// Do not introduce unexplained character duplication.

// Do not change clothing without a real story reason.

// ============================================================
// 4. ENVIRONMENT AND LOCATION
// ============================================================

// Describe the actual filming environment.

// Include:

// - Exact location
// - Interior or exterior
// - Time of day
// - Set layout
// - Background objects
// - Furniture
// - Visible doors and windows
// - Lighting sources
// - Weather if relevant
// - Foreground elements
// - Background details
// - Atmosphere
// - Object placement

// Preserve scene geography between continuous clips.

// A character cannot suddenly appear on the
// opposite side of a room without movement.

// ============================================================
// 5. PHYSICAL ACTIONS
// ============================================================

// Describe precise, observable actions.

// Bad:
// "The character reacts emotionally."

// Good:
// "Her eyebrows tighten, her breathing becomes
// shallow, and her right hand stops just above
// the glass she was about to pick up."

// Specify:

// - Who performs an action
// - Which body part moves
// - Where movement starts
// - Which objects are involved
// - How the action proceeds
// - What changes afterward

// Use realistic physics.

// Avoid teleportation.

// Avoid unexplained object movement.

// ============================================================
// 6. FACIAL PERFORMANCE
// ============================================================

// Create believable human acting.

// Use:

// - Eye movements
// - Subtle facial muscle changes
// - Blinking
// - Breathing
// - Lip movement
// - Facial tension
// - Posture
// - Hand gestures
// - Small reaction pauses

// Emotional intensity should suit the scene.

// A quiet emotional moment does not require
// exaggerated dramatic gestures.

// ============================================================
// 7. DIALOGUE
// ============================================================

// Write exact spoken dialogue when needed.

// For every line include:

// - Speaker identity
// - Exact words
// - Starting time
// - Ending time
// - Emotional delivery

// Dialogue must fit inside the clip duration.

// Do not exceed approximately 2.3 spoken
// words per second.

// Avoid long exposition in a five-second clip.

// Allow natural breathing and reaction pauses.

// If silence is more appropriate, return
// an empty dialogue array.

// Do not invent unnecessary voice-over narration.

// Only the speaking character should lip-sync.

// ============================================================
// 8. CINEMATOGRAPHY
// ============================================================

// Choose the correct shot for the story.

// Specify:

// - Framing
// - Camera angle
// - Lens
// - Camera movement
// - Camera distance
// - Depth of field
// - Focus behavior

// Possible shots include:

// - Close-up
// - Extreme close-up
// - Medium close-up
// - Medium shot
// - Over-the-shoulder
// - Wide shot
// - Establishing shot
// - Point-of-view

// Possible movements include:

// - Static shot
// - Slow push-in
// - Dolly
// - Tracking
// - Pan
// - Tilt
// - Handheld
// - Crane
// - Orbit

// Do not force movement into every scene.

// Emotional drama may use a static camera.

// Action scenes may need kinetic movement.

// Prefer one coherent camera shot per clip.

// Scene cuts can happen at clip boundaries.

// ============================================================
// 9. FIRST FRAME
// ============================================================

// Every clip must define its EXACT first frame.

// Describe:

// - Camera perspective
// - Shot framing
// - Character positions
// - Character body poses
// - Visible objects
// - Background
// - Lighting
// - Facial expressions
// - Main action starting position

// This must be a visual composition, not a
// general description of the scene.

// ============================================================
// 10. LAST FRAME
// ============================================================

// Every clip must define its EXACT ending frame.

// Include:

// - Final character positions
// - Body poses
// - Facial expressions
// - Prop placement
// - Camera perspective
// - Lighting
// - Background
// - Motion state

// The ending frame must be detailed enough
// to become the reference image for the next clip.

// ============================================================
// 11. CROSS-CLIP CONTINUITY
// ============================================================

// Continuous clips must share compatible
// ending and starting frames.

// Preserve:

// - Character identities
// - Body positions
// - Movement direction
// - Clothing
// - Props
// - Object ownership
// - Lighting
// - Camera orientation
// - Spatial geography

// For intentional scene changes,
// use transition="cut".

// For uninterrupted continuation,
// use transition="continuous".

// Do not incorrectly require continuous
// camera movement across legitimate scene cuts.

// ============================================================
// 12. AUDIO
// ============================================================

// Describe appropriate:

// - Ambient sound
// - Footsteps
// - Clothing movement
// - Doors
// - Object interaction
// - Breathing
// - Weather
// - Environmental effects
// - Music if appropriate

// Do not add unwanted music.

// Audio instructions are production guidance.
// Some video generation models require separate
// audio generation or post-production.

// ============================================================
// 13. CONTINUITY STATE
// ============================================================

// At the end of the batch, return endState.

// It must include:

// - Current location
// - Current lighting
// - Final composition
// - Character positions
// - Current emotions
// - Outfits
// - Character-held objects
// - Prop locations
// - Latest narrative developments
// - Immediate next action

// Keep plotProgress concise.

// Do not return the entire previous transcript.

// The endState must describe the ENDING
// of the FINAL clip in this batch.

// ============================================================
// 14. PROMPT DETAIL REQUIREMENTS
// ============================================================

// Every visual description must be specific.

// Do not write generic statements such as:

// "Make it cinematic."
// "The woman feels emotional."
// "The scene continues."

// Replace them with visible instructions.

// Every generated clip should feel like
// a real production shot description.

// Do not invent new characters or locations
// without narrative justification.

// ============================================================
// REQUIRED JSON
// ============================================================

// {
//   "clips": [
//     {
//       "clipNumber": 1,

//       "title": "...",

//       "storyPurpose": "...",

//       "transition": "opening",

//       "location": "...",

//       "visualEnvironment": "...",

//       "visibleCharacters": [
//         "c1"
//       ],

//       "characterActing": "...",

//       "firstFrame": "...",

//       "camera": {
//         "framing": "...",
//         "angle": "...",
//         "lens": "...",
//         "movement": "...",
//         "focus": "..."
//       },

//       "beats": [
//         {
//           "fromSec": 0,
//           "toSec": 2.5,
//           "action": "...",
//           "acting": "...",
//           "camera": "..."
//         }
//       ],

//       "dialogue": [
//         {
//           "speaker": "c1",
//           "fromSec": 0.5,
//           "toSec": 2.0,
//           "text": "...",
//           "delivery": "..."
//         }
//       ],

//       "audio": {
//         "ambience": "...",
//         "foley": "...",
//         "music": "..."
//       },

//       "lastFrame": "...",

//       "continuityOut": "...",

//       "negativePrompt": "..."
//     }
//   ],

//   "endState": {
//     "location": "...",
//     "lighting": "...",
//     "lastFrame": "...",

//     "characters": {
//       "c1": "..."
//     },

//     "props": {
//       "item": "..."
//     },

//     "plotProgress": "...",

//     "nextAction": "..."
//   }
// }

// Use empty arrays when dialogue or characters
// are not present.

// All clip numbers and timing must exactly match
// the supplied fixed timeline.

// Write highly specific, original scene details.
// `;


// // ============================================================
// // OPENAI API INTEGRATION
// // ============================================================

// async function openAIJson(
//   {
//     systemPrompt,
//     userPrompt,
//     maxOutputTokens
//   },
//   options
// ) {
//   const {
//     apiKey,
//     llmModel,
//     apiBaseUrl,
//     signal
//   } = options;

//   // Never send API keys directly from a browser.

//   if (typeof window !== 'undefined') {
//     throw new Error(
//       'OpenAI API keys must remain on the server. ' +
//       'For browser usage provide generateJSON ' +
//       'connected to your backend.'
//     );
//   }

//   const key =
//     apiKey ||
//     (
//       typeof process !== 'undefined'
//         ? process.env.OPENAI_API_KEY
//         : ''
//     );

//   if (!key) {
//     throw new Error(
//       'Missing OPENAI_API_KEY. Set it on your Node server ' +
//       'or provide the generateJSON callback.'
//     );
//   }

//   const response = await fetch(
//     `${apiBaseUrl.replace(/\/$/, '')}/chat/completions`,
//     {
//       method: 'POST',

//       signal,

//       headers: {
//         Authorization: `Bearer ${key}`,

//         'Content-Type':
//           'application/json'
//       },

//       body: JSON.stringify({
//         model: llmModel,

//         messages: [
//           {
//             role: 'system',
//             content: systemPrompt
//           },

//           {
//             role: 'user',
//             content: userPrompt
//           }
//         ],

//         response_format: {
//           type: 'json_object'
//         },

//         max_completion_tokens:
//           maxOutputTokens
//       })
//     }
//   );

//   if (!response.ok) {
//     const errorText =
//       await response.text();

//     throw new Error(
//       `LLM HTTP ${response.status}: ` +
//       errorText.slice(0, 400)
//     );
//   }

//   const result =
//     await response.json();

//   const choice =
//     result.choices?.[0];

//   if (!choice?.message?.content) {
//     throw new Error(
//       'LLM returned empty or truncated output. ' +
//       `Finish reason: ${choice?.finish_reason || 'unknown'}`
//     );
//   }

//   return choice.message.content;
// }


// // ============================================================
// // PARSE LLM JSON
// // ============================================================

// function parseObject(output) {
//   if (
//     output &&
//     typeof output === 'object'
//   ) {
//     if (
//       output.choices?.[0]?.message?.content
//     ) {
//       return parseObject(
//         output.choices[0].message.content
//       );
//     }

//     return output;
//   }

//   if (typeof output !== 'string') {
//     throw new Error(
//       'LLM must return a JSON object or JSON string.'
//     );
//   }

//   const clean = output
//     .trim()
//     .replace(/^```(?:json)?\s*/i, '')
//     .replace(/\s*```$/, '');

//   return JSON.parse(clean);
// }


// // ============================================================
// // CLIP CONTENT AND TIMING VALIDATION
// // ============================================================

// function validateClip(clip, slot) {
//   if (
//     !clip ||
//     clip.clipNumber !== slot.clipNumber
//   ) {
//     throw new Error(
//       `Expected clip ${slot.clipNumber}; ` +
//       `got ${clip?.clipNumber ?? 'none'}`
//     );
//   }

//   const requiredFields = [
//     'firstFrame',
//     'lastFrame',
//     'storyPurpose',
//     'visualEnvironment',
//     'characterActing'
//   ];

//   for (const field of requiredFields) {
//     if (!str(clip[field])) {
//       throw new Error(
//         `Clip ${slot.clipNumber}: ` +
//         `missing ${field}`
//       );
//     }
//   }

//   if (!arr(clip.beats).length) {
//     throw new Error(
//       `Clip ${slot.clipNumber}: ` +
//       'missing action beats'
//     );
//   }

//   let cursor = 0;

//   for (const beat of clip.beats) {
//     const from =
//       Number(beat.fromSec);

//     const to =
//       Number(beat.toSec);

//     if (
//       !Number.isFinite(from) ||
//       !Number.isFinite(to) ||
//       Math.abs(from - cursor) > 0.12 ||
//       to <= from ||
//       to > slot.durationSec + 0.12
//     ) {
//       throw new Error(
//         `Clip ${slot.clipNumber}: ` +
//         `invalid action beat ${from}-${to}`
//       );
//     }

//     cursor = to;
//   }

//   if (
//     Math.abs(
//       cursor - slot.durationSec
//     ) > 0.12
//   ) {
//     throw new Error(
//       `Clip ${slot.clipNumber}: ` +
//       `action ends at ${cursor}, ` +
//       `not ${slot.durationSec}`
//     );
//   }

//   for (
//     const line of arr(clip.dialogue)
//   ) {
//     const from =
//       Number(line.fromSec);

//     const to =
//       Number(line.toSec);

//     const words = str(line.text)
//       .split(/\s+/)
//       .filter(Boolean)
//       .length;

//     if (
//       !Number.isFinite(from) ||
//       !Number.isFinite(to) ||
//       from < 0 ||
//       to > slot.durationSec + 0.12 ||
//       to <= from ||
//       words > (to - from) * 2.3 + 1.1
//     ) {
//       throw new Error(
//         `Clip ${slot.clipNumber}: ` +
//         `dialogue does not fit ${from}-${to}s`
//       );
//     }
//   }
// }


// // ============================================================
// // CHARACTER REFERENCE BUILDER
// // ============================================================

// function castDescription(
//   bible,
//   characterIds
// ) {
//   return arr(bible.characters)
//     .filter(
//       person =>
//         arr(characterIds).includes(
//           person.id
//         ) ||
//         arr(characterIds).includes(
//           person.name
//         )
//     )

//     .map(
//       person =>
//         `${person.name || person.id} ` +
//         `(${person.id}): ` +
//         `${person.appearance}; ` +
//         `COSTUME: ${person.outfit}; ` +
//         `VOICE: ${person.voice}; ` +
//         `PERSONALITY: ${person.personality}`
//     )

//     .join('\n');
// }


// // ============================================================
// // FINAL VIDEO MODEL MASTER PROMPT
// // ============================================================

// function renderPrompt({
//   slot,
//   clip,
//   bible,
//   style,
//   aspectRatio,
//   modelName,
//   character,
//   references
// }) {
//   const cam =
//     clip.camera || {};

//   const audio =
//     clip.audio || {};

//   // Timed physical actions

//   const beatText = arr(clip.beats)
//     .map(
//       beat =>
//         `[${beat.fromSec}–${beat.toSec} seconds]\n` +
//         `ACTION: ${beat.action}\n` +
//         `ACTING: ${beat.acting}\n` +
//         `CAMERA: ${beat.camera}`
//     )
//     .join('\n\n');

//   // Exact dialogue

//   const dialogueText =
//     arr(clip.dialogue).length
//       ? clip.dialogue
//         .map(
//           line =>
//             `[${line.fromSec}–${line.toSec}s] ` +
//             `${line.speaker}, ` +
//             `${line.delivery}: ` +
//             `"${line.text}"`
//         )
//         .join('\n')

//       : 'No spoken dialogue. Use visual acting, ' +
//       'ambient sound and physical foley.';

//   // Explicit reference images only

//   const refText =
//     arr(references).length
//       ? references
//         .map(
//           ref =>
//             `${ref.token}: ` +
//             `${ref.description || ref.name || ref.id}`
//         )
//         .join('\n')

//       : 'No image reference tokens provided.';

//   return `
// ${bible.title || 'FILM'} — CLIP ${slot.clipNumber}
// TIME: ${slot.timecode}

// ============================================================
// VIDEO GENERATION SPECIFICATIONS
// ============================================================

// DURATION:
// EXACTLY ${slot.durationSec} seconds.

// ASPECT RATIO:
// ${aspectRatio}

// TARGET MODEL:
// ${modelName}

// VISUAL STYLE:
// ${style}

// GENRE:
// ${bible.genre || 'As established in story'}


// ============================================================
// NARRATIVE OBJECTIVE
// ============================================================

// ${clip.storyPurpose}

// Every visual action in this clip must serve
// this specific part of the story.


// ============================================================
// CHARACTER IDENTITY AND IMAGE REFERENCE LOCK
// ============================================================

// REFERENCE IMAGES:

// ${refText}

// CHARACTER PROFILES:

// ${castDescription(
//     bible,
//     clip.visibleCharacters
//   )}

// ${character
//       ? `USER CHARACTER REQUIREMENTS:\n${character}`
//       : ''}

// Maintain identical:

// - Facial features
// - Body proportions
// - Hair
// - Skin appearance
// - Clothing
// - Accessories
// - Character identity
// - Established voice characteristics

// No unexplained changes.


// ============================================================
// SCENE AND ENVIRONMENT
// ============================================================

// LOCATION:

// ${clip.location}

// DETAILED ENVIRONMENT:

// ${clip.visualEnvironment}

// Preserve the scene's established geometry,
// lighting and visible objects.


// ============================================================
// CHARACTER PERFORMANCE AND BLOCKING
// ============================================================

// ${clip.characterActing}

// Every expression and body movement must
// have a believable motivation.


// ============================================================
// OPENING FRAME AND CONTINUITY
// ============================================================

// TRANSITION:
// ${clip.transition || 'continuous'}

// EXACT FIRST FRAME:

// ${clip.firstFrame}

// When continuing the previous shot, preserve
// the matching character poses, props, lighting
// and physical positions.


// ============================================================
// CAMERA AND CINEMATOGRAPHY
// ============================================================

// SHOT FRAMING:
// ${cam.framing || 'Natural cinematic framing'}

// CAMERA ANGLE:
// ${cam.angle || 'Eye level'}

// LENS:
// ${cam.lens || 'Cinema prime'}

// CAMERA MOVEMENT:
// ${cam.movement || 'Motivated by the scene'}

// FOCUS:
// ${cam.focus || 'Natural selective focus'}

// The camera must support the dramatic intent.

// Avoid arbitrary movements.

// Maintain coherent spatial geography.


// ============================================================
// EXACT ACTION AND TIME BREAKDOWN
// ============================================================

// ${beatText}

// Perform all actions sequentially.

// Use realistic motion.

// Do not skip actions.

// Maintain natural interaction between
// characters, clothing and objects.


// ============================================================
// DIALOGUE AND LIP SYNC
// ============================================================

// ${dialogueText}

// Preserve exact words.

// Match dialogue timing where supported.

// Only the identified speaker moves their lips.

// Allow natural breathing, pauses
// and listening reactions.

// No additional dialogue.


// ============================================================
// AUDIO AND SOUND DESIGN
// ============================================================

// AMBIENT AUDIO:
// ${audio.ambience || 'Natural location ambience'}

// PHYSICAL SOUND EFFECTS:
// ${audio.foley || 'Natural movement sounds'}

// BACKGROUND MUSIC:
// ${audio.music || 'None'}

// Generate synchronized sound only when
// supported by the selected video model.

// Otherwise use these directions during
// separate audio post-production.


// ============================================================
// REQUIRED ENDING FRAME
// ============================================================

// ${clip.lastFrame}

// This is the exact visual composition required
// at the end of the clip.

// It must remain physically compatible with
// the next continuous clip.


// ============================================================
// CONTINUITY HANDOFF
// ============================================================

// ${clip.continuityOut ||
//     'Preserve established character and prop states.'}

// Maintain the same:

// - Character identities
// - Wardrobe
// - Physical positions
// - Props
// - Lighting
// - Environment
// - Motion direction

// Unless the next clip intentionally
// changes scenes.


// ============================================================
// NEGATIVE PROMPT
// ============================================================

// ${NEGATIVE_PROMPT}

// ${clip.negativePrompt || ''}

// No unexplained teleportation.

// No unwanted scene transition inside this clip.

// No sudden character or object changes.

// No incorrect lip sync.

// The generated video must communicate this
// specific part of the planned narrative.
// `.trim();
// }


// // ============================================================
// // MAIN AI STORY GENERATOR
// // ============================================================

// export async function generateMockClipMasterPrompts({
//   story,

//   character = '',

//   totalDuration = 15,

//   clipDuration = 5,

//   modelId = 'seedance',

//   style =
//   'Ultra-photorealistic live-action cinema',

//   aspectRatio = '16:9',

//   pacing = 'Classical Narrative',

//   references = [],

//   batchSize = 6,

//   outlineBlockClips = 12,

//   llmModel = 'gpt-4.1-mini',

//   apiKey,

//   apiBaseUrl =
//   'https://api.openai.com/v1',

//   generateJSON,

//   onProgress,

//   signal,

//   retries = 2
// } = {}) {

//   // ---------------------------------------------------------
//   // 1. INPUT VALIDATION
//   // ---------------------------------------------------------

//   if (!str(story)) {
//     throw new Error(
//       'story must be a nonempty string'
//     );
//   }

//   if (
//     !Number.isFinite(totalDuration) ||
//     totalDuration <= 0 ||
//     !Number.isFinite(clipDuration) ||
//     clipDuration <= 0
//   ) {
//     throw new Error(
//       'totalDuration and clipDuration must ' +
//       'be positive numbers of seconds'
//     );
//   }

//   if (
//     !Number.isInteger(batchSize) ||
//     batchSize < 1 ||
//     batchSize > 10
//   ) {
//     throw new Error(
//       'batchSize must be between 1 and 10'
//     );
//   }

//   if (
//     !Number.isInteger(outlineBlockClips) ||
//     outlineBlockClips < 1
//   ) {
//     throw new Error(
//       'outlineBlockClips must be a positive integer'
//     );
//   }

//   if (
//     !Number.isInteger(retries) ||
//     retries < 0 ||
//     retries > 5
//   ) {
//     throw new Error(
//       'retries must be between 0 and 5'
//     );
//   }

//   // ---------------------------------------------------------
//   // 2. CALCULATE EXACT TIMELINE
//   // ---------------------------------------------------------

//   const slots = slotsFor(
//     totalDuration,
//     clipDuration
//   );

//   if (slots.length > 1000) {
//     throw new Error(
//       'Maximum 1000 clips per project'
//     );
//   }

//   const blocks = makeBlocks(
//     slots,
//     outlineBlockClips
//   );

//   const videoModel =
//     VIDEO_MODELS.find(
//       m => m.id === modelId
//     ) || VIDEO_MODELS[0];

//   if (!videoModel) {
//     throw new Error(
//       'VIDEO_MODELS is empty'
//     );
//   }

//   // ---------------------------------------------------------
//   // 3. CONFIGURE LLM TRANSPORT
//   // ---------------------------------------------------------

//   const options = {
//     apiKey,
//     llmModel,
//     apiBaseUrl,
//     signal
//   };

//   let llmCallCount = 0;

//   const requestJSON = async (
//     systemPrompt,
//     payload,
//     budget,
//     check
//   ) => {
//     let lastError;

//     for (
//       let attempt = 0;
//       attempt <= retries;
//       attempt++
//     ) {
//       try {
//         if (signal?.aborted) {
//           throw new Error(
//             'Generation cancelled'
//           );
//         }

//         llmCallCount++;

//         const userPrompt = jsonText({
//           ...payload,

//           ...(lastError
//             ? {
//               repairInstruction:
//                 'Correct this specific error ' +
//                 'and return a complete JSON answer: ' +
//                 lastError.message
//             }
//             : {})
//         });

//         const raw = generateJSON
//           ? await generateJSON({
//             systemPrompt,
//             userPrompt,
//             maxOutputTokens: budget
//           })

//           : await openAIJson(
//             {
//               systemPrompt,
//               userPrompt,
//               maxOutputTokens: budget
//             },
//             options
//           );

//         const object =
//           parseObject(raw);

//         check(object);

//         return object;

//       } catch (err) {
//         lastError = err;

//         // Do not retry unauthorized or
//         // unsafe browser-side API calls.

//         if (
//           signal?.aborted ||
//           /HTTP 401|HTTP 403|Missing OPENAI_API_KEY|browser, pass a generateJSON/i
//             .test(err.message)
//         ) {
//           throw err;
//         }
//       }
//     }

//     throw new Error(
//       'Unable to generate valid storyboard JSON ' +
//       `after ${retries + 1} attempt(s): ` +
//       lastError.message
//     );
//   };

//   // ---------------------------------------------------------
//   // 4. GLOBAL STORY PLANNING
//   // ---------------------------------------------------------

//   onProgress?.({
//     phase: 'planning',
//     completed: 0,
//     total: slots.length
//   });

//   const plan = await requestJSON(
//     PLAN_SYSTEM,

//     {
//       goal:
//         'Plan the complete film across the ' +
//         'EXACT fixed outline blocks.',

//       story,
//       character,
//       pacing,
//       style,
//       aspectRatio,

//       totalDuration,
//       clipDuration,

//       targetVideoModel:
//         videoModel.name,

//       references,

//       requiredBlocks: blocks
//     },

//     Math.min(
//       14000,
//       2500 + blocks.length * 240
//     ),

//     result => {
//       if (
//         !result.storyBible ||
//         !Array.isArray(result.outline)
//       ) {
//         throw new Error(
//           'Missing storyBible or outline array'
//         );
//       }

//       if (
//         result.outline.length !==
//         blocks.length ||

//         blocks.some(
//           (block, index) =>
//             result.outline[index]?.blockId !==
//             block.blockId
//         )
//       ) {
//         throw new Error(
//           'Outline must contain exactly ' +
//           'one ordered item for each block'
//         );
//       }
//     }
//   );

//   const bible =
//     plan.storyBible;

//   const outline = plan.outline.map(
//     (entry, index) => ({
//       ...entry,
//       ...blocks[index]
//     })
//   );

//   // ---------------------------------------------------------
//   // 5. INITIALIZE CONTINUITY STATE
//   // ---------------------------------------------------------

//   const clips = [];

//   let state = {
//     location:
//       'Story opening',

//     lighting:
//       'Not yet established',

//     lastFrame:
//       'First frame has not happened',

//     characters: {},

//     props: {},

//     plotProgress:
//       'Story has not started',

//     nextAction:
//       'Establish first location and begin story'
//   };

//   // ---------------------------------------------------------
//   // 6. GENERATE CLIPS IN BATCHES
//   // ---------------------------------------------------------

//   for (
//     let offset = 0;
//     offset < slots.length;
//     offset += batchSize
//   ) {
//     const batchSlots = slots.slice(
//       offset,
//       offset + batchSize
//     );

//     const first =
//       batchSlots[0];

//     const last =
//       batchSlots[batchSlots.length - 1];

//     // Only relevant story sections
//     // are sent to the current batch.

//     const relevantOutline =
//       outline.filter(
//         block =>
//           block.endSec > first.startSec &&
//           block.startSec < last.endSec
//       );

//     // -------------------------------------------------------
//     // 7. CALL LLM FOR CURRENT CLIPS
//     // -------------------------------------------------------

//     const result = await requestJSON(
//       CLIP_SYSTEM,

//       {
//         task:
//           `Write precisely ${batchSlots.length} ` +
//           'chronological, filmable video clips.',

//         storyBible:
//           bible,

//         style,
//         pacing,
//         aspectRatio,

//         targetVideoModel:
//           videoModel.name,

//         characterInstruction:
//           character,

//         references,

//         relevantOutline,

//         previousEndingState:
//           state,

//         requiredClipSlots:
//           batchSlots
//       },

//       Math.min(
//         15500,
//         1800 + batchSlots.length * 2050
//       ),

//       result => {
//         if (
//           !Array.isArray(result.clips) ||
//           result.clips.length !==
//           batchSlots.length
//         ) {
//           throw new Error(
//             `Expected ${batchSlots.length} clips, ` +
//             `got ${result.clips?.length}`
//           );
//         }

//         if (
//           !result.endState ||
//           !str(result.endState.lastFrame)
//         ) {
//           throw new Error(
//             'Missing endState.lastFrame'
//           );
//         }

//         batchSlots.forEach(
//           (slot, index) =>
//             validateClip(
//               result.clips[index],
//               slot
//             )
//         );
//       }
//     );

//     // -------------------------------------------------------
//     // 8. BUILD FULL MASTER PROMPT FOR EACH CLIP
//     // -------------------------------------------------------

//     batchSlots.forEach(
//       (slot, index) => {
//         const clip =
//           result.clips[index];

//         const cam =
//           clip.camera || {};

//         const masterPrompt =
//           renderPrompt({
//             slot,
//             clip,
//             bible,
//             style,
//             aspectRatio,

//             modelName:
//               videoModel.name,

//             character,

//             references
//           });

//         clips.push({
//           ...slot,

//           title:
//             clip.title ||
//             `Clip ${slot.clipNumber}`,

//           continuityNote:
//             clip.transition === 'cut'
//               ? 'Intentional scene cut at clip boundary'

//               : 'Continuous handoff: ' +
//               clip.firstFrame,

//           camera: [
//             cam.framing,
//             cam.angle,
//             cam.movement,
//             cam.lens
//           ]
//             .filter(Boolean)
//             .join(' | '),

//           transition:
//             clip.transition ||
//             (
//               slot.clipNumber === 1
//                 ? 'opening'
//                 : 'continuous'
//             ),

//           storyPurpose:
//             clip.storyPurpose,

//           location:
//             clip.location,

//           firstFrame:
//             clip.firstFrame,

//           lastFrame:
//             clip.lastFrame,

//           dialogue:
//             arr(clip.dialogue),

//           beats:
//             clip.beats,

//           structuredPrompt:
//             clip,

//           masterPrompt
//         });
//       }
//     );

//     // -------------------------------------------------------
//     // 9. UPDATE CONTINUITY WITHOUT FULL HISTORY
//     // -------------------------------------------------------

//     const lastClip =
//       result.clips[
//       result.clips.length - 1
//       ];

//     // Take the authoritative ending frame
//     // from the actual final clip of this batch.

//     state = {
//       location:
//         trim(
//           result.endState.location,
//           240
//         ),

//       lighting:
//         trim(
//           result.endState.lighting,
//           300
//         ),

//       lastFrame:
//         trim(
//           lastClip.lastFrame,
//           2000
//         ),

//       characters:
//         result.endState.characters || {},

//       props:
//         result.endState.props || {},

//       plotProgress:
//         trim(
//           result.endState.plotProgress,
//           750
//         ),

//       nextAction:
//         trim(
//           result.endState.nextAction,
//           400
//         )
//     };

//     // -------------------------------------------------------
//     // 10. PROGRESS CALLBACK
//     // -------------------------------------------------------

//     onProgress?.({
//       phase: 'clips',

//       completed:
//         clips.length,

//       total:
//         slots.length
//     });
//   }

//   // ---------------------------------------------------------
//   // 11. RETURN COMPLETE PROJECT
//   // ---------------------------------------------------------

//   return {
//     id:
//       `proj_${Date.now()}_` +
//       Math.random()
//         .toString(36)
//         .slice(2, 8),

//     createdAt:
//       new Date().toISOString(),

//     projectTitle:
//       `${bible.title || 'CINEMATIC STORY'}: ` +
//       'SEQUENTIAL MASTER STORYBOARD',

//     totalDuration,

//     clipDuration,

//     clipCount:
//       clips.length,

//     aspectRatio,

//     targetModel:
//       modelId,

//     modelUsed:
//       llmModel,

//     storyBible:
//       bible,

//     outline,

//     clips,

//     finalState:
//       state,

//     llmCallCount
//   };
// }


// // ============================================================
// // ADDITIONAL EXPORT
// // ============================================================

// export const generateClipMasterPrompts =
//   generateMockClipMasterPrompts;


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
      // throw new Error(
      //   `Clip ${n}: beat ${i + 1} (${r1(beat.toSec - beat.fromSec)}s) has ${words} spoken words; ` +
      //   `maximum is ${Math.floor(budget)}. Shorten the lines or lengthen the beat.`
      // );
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
