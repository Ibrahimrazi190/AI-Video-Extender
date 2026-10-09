import express from 'express';
import { VIDEO_MODELS } from '../services/directorService.js';

const router = express.Router();

router.get('/health', (req, res) => {
  const hasEnvKey = Boolean(process.env.OPENAI_API_KEY && process.env.OPENAI_API_KEY.trim());
  res.json({
    status: 'online',
    service: 'VisioPrompt AI Director Engine',
    timestamp: new Date().toISOString(),
    openaiConfigured: hasEnvKey,
    defaultModel: process.env.OPENAI_MODEL || 'gpt-4.1',
    supportedVideoGenerators: VIDEO_MODELS.map(m => ({ id: m.id, name: m.name }))
  });
});

export default router;
