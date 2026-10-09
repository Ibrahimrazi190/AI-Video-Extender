/**
 * OpenAI Service - entry point used by POST /api/generate.
 * The real work lives in storyEngine.js (planning + batched clip writing + validation)
 * and promptRenderer.js (model-specific prompt text).
 */
import { VIDEO_MODELS } from './directorService.js';
import { generateProject } from './storyEngine.js';

export async function generateClipMasterPromptsOpenAI({ apiKey, modelId = 'seedance', ...rest }) {
  const activeKey = (apiKey || process.env.OPENAI_API_KEY || '').trim();
  if (!activeKey) throw new Error('NO_API_KEY');

  const videoModel = VIDEO_MODELS.find(m => m.id === modelId) || VIDEO_MODELS[0];
  return generateProject({ apiKey: activeKey, modelId: videoModel.id, videoModel, ...rest });
}
