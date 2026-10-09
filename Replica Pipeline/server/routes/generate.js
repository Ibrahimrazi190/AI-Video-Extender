import express from 'express';
import { generateClipMasterPromptsOpenAI } from '../services/openaiService.js';
import { saveProject } from '../services/storageService.js';

const router = express.Router();

/**
 * POST /api/generate
 * Plans the story, then writes one production-ready prompt per clip (with dialogue, shot list,
 * first/last frames) while keeping characters and continuity consistent.
 */
router.post('/generate', async (req, res) => {
  try {
    const {
      story,
      character,
      totalDuration = 15,
      clipDuration = 5,
      modelId = 'seedance',
      style,
      aspectRatio = '16:9',
      pacing,
      references
    } = req.body;

    if (!story || !story.trim()) {
      return res.status(400).json({ success: false, error: 'Story premise is required.' });
    }

    const apiKey = (req.headers['x-openai-api-key'] || req.body.apiKey || process.env.OPENAI_API_KEY || '').trim();
    if (!apiKey) {
      return res.status(400).json({
        success: false,
        error: 'An OpenAI API key is required. Add it in the UI or set OPENAI_API_KEY in .env.'
      });
    }

    const result = await generateClipMasterPromptsOpenAI({
      apiKey,
      story,
      character,
      totalDuration: Number(totalDuration),
      clipDuration: Number(clipDuration),
      modelId,
      style,
      aspectRatio,
      pacing,
      references: Array.isArray(references) ? references : []
    });

    try {
      saveProject(result);
    } catch (saveErr) {
      console.error('Failed to auto-save project:', saveErr);
    }

    res.json({ success: true, source: `openai-${result.modelUsed}`, data: result });
  } catch (error) {
    console.error('API /generate error:', error);
    res.status(502).json({
      success: false,
      error: error.message || 'Script generation failed.'
    });
  }
});

export default router;
