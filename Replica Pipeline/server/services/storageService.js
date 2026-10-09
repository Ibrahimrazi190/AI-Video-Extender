/**
 * Storage Service - JSON File-Based Persistent Project Store
 * Saves generated storyboards to server/data/projects.json
 */
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const DATA_DIR = path.resolve(__dirname, '../data');
const DATA_FILE = path.join(DATA_DIR, 'projects.json');

// Ensure data directory and file exist
function initStorage() {
  try {
    if (!fs.existsSync(DATA_DIR)) {
      fs.mkdirSync(DATA_DIR, { recursive: true });
    }
    if (!fs.existsSync(DATA_FILE)) {
      fs.writeFileSync(DATA_FILE, JSON.stringify([], null, 2), 'utf-8');
    }
  } catch (err) {
    console.error('Failed to initialize storage directory:', err);
  }
}

initStorage();

export function getAllProjects() {
  try {
    if (!fs.existsSync(DATA_FILE)) return [];
    const content = fs.readFileSync(DATA_FILE, 'utf-8');
    return JSON.parse(content || '[]');
  } catch (err) {
    console.error('Error reading projects:', err);
    return [];
  }
}

export function getProjectById(id) {
  const projects = getAllProjects();
  return projects.find(p => p.id === id) || null;
}

export function saveProject(projectData) {
  try {
    const projects = getAllProjects();
    const id = projectData.id || ('proj_' + Date.now() + '_' + Math.random().toString(36).substr(2, 6));
    const record = {
      ...projectData,
      id,
      updatedAt: new Date().toISOString(),
      createdAt: projectData.createdAt || new Date().toISOString()
    };

    const existingIndex = projects.findIndex(p => p.id === id);
    if (existingIndex >= 0) {
      projects[existingIndex] = record;
    } else {
      projects.unshift(record); // Add to beginning of history
    }

    // Keep max 50 recent projects
    const trimmed = projects.slice(0, 50);
    fs.writeFileSync(DATA_FILE, JSON.stringify(trimmed, null, 2), 'utf-8');
    return record;
  } catch (err) {
    console.error('Error saving project:', err);
    throw err;
  }
}

export function deleteProject(id) {
  try {
    const projects = getAllProjects();
    const filtered = projects.filter(p => p.id !== id);
    fs.writeFileSync(DATA_FILE, JSON.stringify(filtered, null, 2), 'utf-8');
    return true;
  } catch (err) {
    console.error('Error deleting project:', err);
    return false;
  }
}
