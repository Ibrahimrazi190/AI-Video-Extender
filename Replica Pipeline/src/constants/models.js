export const VIDEO_MODELS = [
  {
    id: 'sora',
    name: 'OpenAI Sora',
    tagline: 'Photoreal cinematic storytelling & fluid physics',
    badge: 'Flagship 4K',
    color: '#10A37F',
    bgGradient: 'linear-gradient(135deg, rgba(16, 163, 127, 0.2) 0%, rgba(13, 110, 86, 0.05) 100%)',
    borderGlow: 'rgba(16, 163, 127, 0.4)',
    promptFormat: 'Natural narrative prose with physical dynamics, continuous lighting, camera motion, and micro-expressions.',
    guidelines: [
      'Describe physics accurately (wind, liquid, reflections, cloth simulation)',
      'Specify camera trajectory (e.g. continuous slow pan, dynamic tracking)',
      'Include sensory lighting cues (volumetric rays, golden hour haze, subsurface scattering)',
      'Mention micro-facial expressions and authentic human pauses'
    ],
    promptPrefix: 'Cinematic hyper-realistic 4K footage. ',
    negativePromptSupported: false,
    recommendedClipSizes: [5, 8, 10, 15]
  },
  {
    id: 'runway-gen3',
    name: 'Runway Gen-3 Alpha',
    tagline: 'Structured director tags & cinematic motion control',
    badge: 'Industry Standard',
    color: '#00F2FE',
    bgGradient: 'linear-gradient(135deg, rgba(0, 242, 254, 0.2) 0%, rgba(79, 172, 254, 0.05) 100%)',
    borderGlow: 'rgba(0, 242, 254, 0.4)',
    promptFormat: 'Structured bracketed tags: [Camera: ...] [Lighting: ...] [Motion: ...] followed by photoreal scene description.',
    guidelines: [
      'Use camera movement tags: [Camera: FPV drone push-in], [Camera: Orbiting steadycam]',
      'Use lens and lighting tags: [Lighting: Chiaroscuro high contrast neon] [Lens: 35mm anamorphic]',
      'Describe speed and trajectory explicitly: [Motion: High dynamic speed 8/10]',
      'Avoid vague adjectives; use concrete cinematic terms'
    ],
    promptPrefix: '',
    negativePromptSupported: false,
    recommendedClipSizes: [5, 10]
  },
  {
    id: 'kling',
    name: 'Kling AI 1.5 / Pro',
    tagline: 'Hyper-detailed visuals & high prompt fidelity',
    badge: 'Ultra High Fidelity',
    color: '#FF6B6B',
    bgGradient: 'linear-gradient(135deg, rgba(255, 107, 107, 0.2) 0%, rgba(238, 90, 36, 0.05) 100%)',
    borderGlow: 'rgba(255, 107, 107, 0.4)',
    promptFormat: 'Detailed master shot description with photography tags, cinematic lighting, and dedicated negative prompt.',
    guidelines: [
      'Include photographic parameters: 8k resolution, ARRI Alexa Mini, Kodak Vision3',
      'Detail exact character attire, physical features, and motion sequences',
      'Specify environment depth of field, atmospheric particles, and reflection details',
      'Use negative prompts to prevent morphing, warping, extra limbs, and flickering'
    ],
    promptPrefix: 'Masterpiece 8K masterpiece cinematography, ',
    negativePromptSupported: true,
    recommendedClipSizes: [5, 10]
  },
  {
    id: 'luma-dream-machine',
    name: 'Luma Dream Machine',
    tagline: 'Organic spatial camera flows & smooth transitions',
    badge: 'Smooth Motion',
    color: '#A855F7',
    bgGradient: 'linear-gradient(135deg, rgba(168, 85, 247, 0.2) 0%, rgba(126, 34, 206, 0.05) 100%)',
    borderGlow: 'rgba(168, 85, 247, 0.4)',
    promptFormat: 'Fluid spatial camera cues with coherent physics and seamless temporal evolution.',
    guidelines: [
      'Focus heavily on the camera path (sweeping orbit, fly-through, crane rise)',
      'Explicitly describe smooth object transitions and subject momentum',
      'Emphasize depth layers (foreground elements passing camera, middle ground, background)'
    ],
    promptPrefix: 'Smooth cinematic camera movement, ',
    negativePromptSupported: false,
    recommendedClipSizes: [5]
  },
  {
    id: 'hailuo',
    name: 'Hailuo AI (MiniMax)',
    tagline: 'Expressive human emotions & natural organic physics',
    badge: 'Natural Physics',
    color: '#F59E0B',
    bgGradient: 'linear-gradient(135deg, rgba(245, 158, 11, 0.2) 0%, rgba(217, 119, 6, 0.05) 100%)',
    borderGlow: 'rgba(245, 158, 11, 0.4)',
    promptFormat: 'Character-centric emotional acting prompts with vivid physical environmental responses.',
    guidelines: [
      'Describe human facial expressions, eye contact, and emotional breathing',
      'Specify cloth movement, hair dynamics reacting to wind or moisture',
      'Keep subject actions physically plausible and deliberate'
    ],
    promptPrefix: 'High fidelity cinematic film, ',
    negativePromptSupported: false,
    recommendedClipSizes: [6]
  },
  {
    id: 'pika',
    name: 'Pika 2.0',
    tagline: 'Creative VFX, dynamic camera zoom & stylized animation',
    badge: 'VFX & Animation',
    color: '#EC4899',
    bgGradient: 'linear-gradient(135deg, rgba(236, 72, 153, 0.2) 0%, rgba(190, 24, 93, 0.05) 100%)',
    borderGlow: 'rgba(236, 72, 153, 0.4)',
    promptFormat: 'Action-packed visual prompts with -camera motion parameters and negative prompts.',
    guidelines: [
      'Focus on dynamic visual effects (sparks, lightning, water splashes, explosions)',
      'Specify camera zoom, pan, tilt parameters',
      'Great for stylized, sci-fi, and action-oriented clips'
    ],
    promptPrefix: 'Cinematic film shot, -camera zoom in -fps 24 ',
    negativePromptSupported: true,
    recommendedClipSizes: [5, 8]
  },
  {
    id: 'seedance',
    name: 'Seedance (ByteDance)',
    tagline: 'Ultra-fluid dynamic choreography & complex physical momentum',
    badge: 'Dynamic Motion',
    color: '#06B6D4',
    bgGradient: 'linear-gradient(135deg, rgba(6, 182, 212, 0.2) 0%, rgba(14, 116, 144, 0.05) 100%)',
    borderGlow: 'rgba(6, 182, 212, 0.4)',
    promptFormat: 'Dynamic choreography-focused cinematic prose with explicit camera tracking, momentum, and fluid physics.',
    guidelines: [
      'Describe complex continuous motion (chases, martial arts, athletic gestures, fluid momentum)',
      'Specify active camera kinematics (continuous gimbal tracking, 3D push-through, whip pans)',
      'Detail cloth drape, hair dynamics, water splashes, and physical wind reaction',
      'Maintain strong spatial depth and high dynamic range lighting consistency'
    ],
    promptPrefix: 'Cinematic dynamic masterwork, 4K UHD, ',
    negativePromptSupported: true,
    recommendedClipSizes: [5, 8, 10, 15]
  },
  {
    id: 'seedance-mini',
    name: 'Seedance Mini (ByteDance)',
    tagline: 'Fast, lightweight generations - compact prompts',
    badge: 'Fast & Light',
    color: '#14B8A6',
    bgGradient: 'linear-gradient(135deg, rgba(20, 184, 166, 0.2) 0%, rgba(15, 118, 110, 0.05) 100%)',
    borderGlow: 'rgba(20, 184, 166, 0.4)',
    promptFormat: 'Compact single-paragraph prompt: one or two timed shots, at most two characters, short quoted dialogue.',
    guidelines: [
      'Prompts stay short: one or two timed shots per clip',
      'At most two characters on screen, short dialogue lines',
      'Best for quick drafts and previews'
    ],
    promptPrefix: '',
    negativePromptSupported: false,
    recommendedClipSizes: [5, 8, 10]
  }
];

export const CLIP_DURATIONS = [
  { value: 5, label: '5s Clips', description: 'Fast-paced, dynamic cuts, social video' },
  { value: 8, label: '8s Clips', description: 'Balanced pacing, cinematic shots' },
  { value: 10, label: '10s Clips', description: 'Slow burn, narrative depth, complex motion' },
  { value: 15, label: '15s Clips', description: 'Extended master shots, documentary, ambient' }
];

export const TOTAL_DURATIONS = [
  { value: 15, label: '15 Seconds', badge: 'Short' },
  { value: 30, label: '30 Seconds', badge: 'Commercial' },
  { value: 45, label: '45 Seconds', badge: 'Teaser' },
  { value: 60, label: '1 Minute (60s)', badge: 'Recommended' },
  { value: 90, label: '1.5 Minutes (90s)', badge: 'Trailer' },
  { value: 120, label: '2 Minutes (120s)', badge: 'Short Film' },
  { value: 180, label: '3 Minutes (180s)', badge: 'Cinematic Story' }
];

export const ASPECT_RATIOS = [
  { id: '16:9', label: '16:9 Widescreen', desc: 'YouTube, Cinema, Desktop', icon: 'landscape' },
  { id: '9:16', label: '9:16 Vertical', desc: 'TikTok, Reels, Shorts', icon: 'portrait' },
  { id: '2.39:1', label: '2.39:1 Anamorphic', desc: 'Ultra-wide Cinematic Scope', icon: 'ultrawide' },
  { id: '1:1', label: '1:1 Square', desc: 'Instagram Feed, Square Video', icon: 'square' },
  { id: '4:3', label: '4:3 Academy', desc: 'Vintage & Classic Film', icon: 'classic' }
];

export const CINEMATIC_STYLES = [
  'Cinematic 35mm Panavision (Kodak 5219 Film Stock)',
  'Anamorphic Sci-Fi Cyberpunk (Blade Runner / Denis Villeneuve)',
  'IMAX 70mm Photorealistic Documentary (Natural Light, High Dynamic Range)',
  'Moody Neo-Noir (High Contrast Chiaroscuro & Rain Reflections)',
  'Studio Ghibli Lush Hand-Painted Anime Aesthetic',
  '1970s Vintage 16mm Kodachrome Retro Camcorder',
  'Dark Fantasy Epic (Unreal Engine 5 Photoreal Lumen)',
  'Glossy Luxury Commercial (Slow-Motion, Macro Textures, Pristine Lighting)'
];

export const PACING_OPTIONS = [
  'Dynamic & Fast-Paced (Action cuts, rising velocity)',
  'Classical Narrative (Hook, Rising Tension, Climax, Resolution)',
  'Slow-Burn Contemplative (Atmospheric, lingering camera, poetic)',
  'Music Video Beat-Synced (Rhythmic camera swings, bold transitions)'
];
