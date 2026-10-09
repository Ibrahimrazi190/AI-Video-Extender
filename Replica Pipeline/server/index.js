import express from 'express';
import cors from 'cors';
import dotenv from 'dotenv';
import path from 'path';
import { fileURLToPath } from 'url';

import generateRoutes from './routes/generate.js';
import projectRoutes from './routes/projects.js';
import healthRoutes from './routes/health.js';

// Load .env
dotenv.config();

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const app = express();
const PORT = process.env.PORT || 3001;

// Middleware
app.use(cors());
app.use(express.json({ limit: '10mb' }));
app.use(express.urlencoded({ extended: true, limit: '10mb' }));

// Request Logging
app.use((req, res, next) => {
  const start = Date.now();
  res.on('finish', () => {
    const duration = Date.now() - start;
    if (req.originalUrl.startsWith('/api')) {
      console.log(`[${req.method}] ${req.originalUrl} -> ${res.statusCode} (${duration}ms)`);
    }
  });
  next();
});

// API Routes
app.use('/api', healthRoutes);
app.use('/api', generateRoutes);
app.use('/api/projects', projectRoutes);

// Error Handling Middleware
app.use((err, req, res, next) => {
  console.error('Unhandled server error:', err);
  res.status(500).json({
    success: false,
    error: err.message || 'Internal server error.'
  });
});

app.listen(PORT, () => {
  console.log(`\n======================================================`);
  console.log(`🎬 VisioPrompt AI Backend Server Online`);
  console.log(`📡 URL: http://localhost:${PORT}`);
  console.log(`🤖 Engine: OpenAI ${process.env.OPENAI_MODEL || 'gpt-4.1'} (set OPENAI_MODEL to change)`);
  console.log(`🔑 OPENAI_API_KEY: ${process.env.OPENAI_API_KEY ? 'Configured in .env' : 'Not set (a key must be supplied from the UI)'}`);
  console.log(`======================================================\n`);
});

export default app;
