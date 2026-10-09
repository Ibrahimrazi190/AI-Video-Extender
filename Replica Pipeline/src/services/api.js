const API_BASE = '/api';

/**
 * Check backend connection and status
 */
export async function checkBackendHealth() {
  try {
    const res = await fetch(`${API_BASE}/health`, { signal: AbortSignal.timeout(3000) });
    if (res.ok) {
      return await res.json();
    }
    return null;
  } catch (err) {
    console.warn('Backend not responding to health check:', err.message);
    return null;
  }
}

/**
 * Generate sequential Clip Master Prompts maintaining continuity
 */
export async function generateStoryboard({
  apiKey,
  story,
  character,
  totalDuration,
  clipDuration,
  modelId,
  style,
  aspectRatio,
  pacing
}) {
  try {
    const headers = { 'Content-Type': 'application/json' };
    if (apiKey && apiKey.trim()) {
      headers['x-openai-api-key'] = apiKey.trim();
    }

    const response = await fetch(`${API_BASE}/generate`, {
      method: 'POST',
      headers,
      body: JSON.stringify({
        apiKey,
        story,
        character,
        totalDuration,
        clipDuration,
        modelId,
        style,
        aspectRatio,
        pacing
      })
    });

    if (response.ok) {
      const json = await response.json();
      if (json.success && json.data) {
        return {
          ...json.data,
          source: json.source
        };
      }
    }
    const errData = await response.json().catch(() => ({}));
    throw new Error(errData.error || `Server HTTP ${response.status}`);
  } catch (err) {
    if (err instanceof TypeError) {
      throw new Error('Cannot reach the backend. Start it with `npm run dev` (server on port 3001).');
    }
    throw err;
  }
}

/**
 * Fetch saved projects list from backend
 */
export async function fetchProjectsList() {
  try {
    const res = await fetch(`${API_BASE}/projects`);
    if (res.ok) {
      const json = await res.json();
      return json.data || [];
    }
    return [];
  } catch (err) {
    console.warn('Failed to fetch projects list:', err.message);
    return [];
  }
}

/**
 * Fetch a specific project by ID
 */
export async function fetchProjectDetails(id) {
  try {
    const res = await fetch(`${API_BASE}/projects/${id}`);
    if (res.ok) {
      const json = await res.json();
      return json.data || null;
    }
    return null;
  } catch (err) {
    console.warn('Failed to fetch project details:', err.message);
    return null;
  }
}

/**
 * Delete a project by ID
 */
export async function deleteProject(id) {
  try {
    const res = await fetch(`${API_BASE}/projects/${id}`, { method: 'DELETE' });
    return res.ok;
  } catch (err) {
    console.warn('Failed to delete project:', err.message);
    return false;
  }
}
