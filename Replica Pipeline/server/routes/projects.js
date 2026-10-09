import express from 'express';
import { getAllProjects, getProjectById, saveProject, deleteProject } from '../services/storageService.js';
import { VIDEO_MODELS } from '../services/directorService.js';

const router = express.Router();

/**
 * GET /api/projects
 * Get list of all saved storyboards
 */
router.get('/', (req, res) => {
  try {
    const projects = getAllProjects();
    // Return lightweight summary for list
    const summaries = projects.map(p => ({
      id: p.id,
      projectTitle: p.projectTitle,
      synopsis: p.synopsis?.slice(0, 120),
      totalDuration: p.totalDuration,
      clipDuration: p.clipDuration,
      sceneCount: p.sceneCount || p.scenes?.length || 0,
      targetModel: p.targetModel,
      createdAt: p.createdAt,
      updatedAt: p.updatedAt
    }));
    res.json({ success: true, count: summaries.length, data: summaries });
  } catch (error) {
    res.status(500).json({ success: false, error: error.message });
  }
});

/**
 * GET /api/projects/:id
 * Get single project with all scene details
 */
router.get('/:id', (req, res) => {
  try {
    const project = getProjectById(req.params.id);
    if (!project) {
      return res.status(404).json({ success: false, error: 'Project not found.' });
    }
    res.json({ success: true, data: project });
  } catch (error) {
    res.status(500).json({ success: false, error: error.message });
  }
});

/**
 * POST /api/projects
 * Save or update a project
 */
router.post('/', (req, res) => {
  try {
    const projectData = req.body;
    if (!projectData || !projectData.scenes) {
      return res.status(400).json({ success: false, error: 'Invalid project payload.' });
    }
    const saved = saveProject(projectData);
    res.json({ success: true, data: saved });
  } catch (error) {
    res.status(500).json({ success: false, error: error.message });
  }
});

/**
 * DELETE /api/projects/:id
 * Delete a saved project
 */
router.delete('/:id', (req, res) => {
  try {
    const success = deleteProject(req.params.id);
    res.json({ success });
  } catch (error) {
    res.status(500).json({ success: false, error: error.message });
  }
});

export default router;
