import React, { useState } from 'react';
import {
  Copy,
  Check,
  Download,
  FileText,
  FileCode,
  Table,
  LayoutGrid,
  List,
  Sparkles,
  RotateCcw,
  Film,
  Camera,
  Layers,
  Search,
  ExternalLink
} from 'lucide-react';
import { SceneCard } from './SceneCard';
import { VIDEO_MODELS } from '../constants/models';

export function StoryboardView({
  projectData,
  activeSceneIndex,
  onSelectScene,
  onUpdateScene,
  onRegenerateScene,
  regeneratingIndex,
  onRegenerateAll
}) {
  const [viewMode, setViewMode] = useState('cards'); // 'cards', 'compact', 'batch', 'screenplay'
  const [copiedAll, setCopiedAll] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');

  if (!projectData || !projectData.scenes || projectData.scenes.length === 0) {
    return null;
  }

  const { scenes, totalDuration, clipDuration, targetModel, projectTitle, synopsis } = projectData;
  const targetModelInfo = VIDEO_MODELS.find(m => m.id === targetModel) || VIDEO_MODELS[0];

  // Filter scenes if search query exists
  const filteredScenes = scenes.filter(s => {
    if (!searchQuery) return true;
    const q = searchQuery.toLowerCase();
    return (
      s.title?.toLowerCase().includes(q) ||
      s.targetModelPrompt?.toLowerCase().includes(q) ||
      s.shotType?.toLowerCase().includes(q) ||
      s.cameraMovement?.toLowerCase().includes(q)
    );
  });

  // Batch copy all prompts
  const handleCopyAllPrompts = async () => {
    const formatted = scenes.map(s => {
      return `--- SCENE ${s.sceneNumber} (${s.timecode} | ${s.shotType}) ---\n${s.targetModelPrompt}\n`;
    }).join('\n');

    try {
      await navigator.clipboard.writeText(formatted);
      setCopiedAll(true);
      setTimeout(() => setCopiedAll(false), 2500);
    } catch (err) {
      console.error('Failed to copy all', err);
    }
  };

  // Export JSON file
  const handleExportJSON = () => {
    const dataStr = 'data:text/json;charset=utf-8,' + encodeURIComponent(JSON.stringify(projectData, null, 2));
    const downloadAnchor = document.createElement('a');
    downloadAnchor.setAttribute('href', dataStr);
    downloadAnchor.setAttribute('download', `${projectTitle.replace(/[^a-z0-9]/gi, '_').toLowerCase()}_storyboard.json`);
    document.body.appendChild(downloadAnchor);
    downloadAnchor.click();
    downloadAnchor.remove();
  };

  // Export Markdown Screenplay
  const handleExportMarkdown = () => {
    let md = `# ${projectTitle}\n\n`;
    md += `**Target Model:** ${targetModelInfo.name}\n`;
    md += `**Total Duration:** ${totalDuration}s (${Math.floor(totalDuration / 60)}m ${totalDuration % 60}s)\n`;
    md += `**Clip Size:** ${clipDuration}s per cut\n`;
    md += `**Total Scenes:** ${scenes.length}\n\n`;
    md += `## Synopsis\n${synopsis}\n\n`;
    md += `---\n\n## Scene Breakdown & AI Video Prompts\n\n`;

    scenes.forEach(s => {
      md += `### Scene ${s.sceneNumber}: ${s.title} (${s.timecode})\n`;
      md += `- **Shot Type:** ${s.shotType}\n`;
      md += `- **Camera Movement:** ${s.cameraMovement}\n`;
      md += `- **Lens / Optics:** ${s.focalLength}\n`;
      md += `- **Lighting:** ${s.lighting}\n`;
      md += `- **Action & Physics:** ${s.visualDescription}\n`;
      md += `\n**Target AI Model Prompt (${targetModelInfo.name}):**\n\`\`\`\n${s.targetModelPrompt}\n\`\`\`\n\n`;
      if (s.negativePrompt) {
        md += `**Negative Prompt:** \`${s.negativePrompt}\`\n\n`;
      }
      md += `**Audio & Voiceover Cue:** *${s.audioScript}*\n\n`;
      md += `---\n\n`;
    });

    const dataStr = 'data:text/markdown;charset=utf-8,' + encodeURIComponent(md);
    const downloadAnchor = document.createElement('a');
    downloadAnchor.setAttribute('href', dataStr);
    downloadAnchor.setAttribute('download', `${projectTitle.replace(/[^a-z0-9]/gi, '_').toLowerCase()}_screenplay.md`);
    document.body.appendChild(downloadAnchor);
    downloadAnchor.click();
    downloadAnchor.remove();
  };

  // Export CSV
  const handleExportCSV = () => {
    const headers = ['Scene Number', 'Timecode', 'Duration (s)', 'Shot Type', 'Camera Movement', 'Lighting', 'Prompt for ' + targetModelInfo.name, 'Audio Cue'];
    const rows = scenes.map(s => [
      s.sceneNumber,
      `"${s.timecode}"`,
      s.durationSec,
      `"${(s.shotType || '').replace(/"/g, '""')}"`,
      `"${(s.cameraMovement || '').replace(/"/g, '""')}"`,
      `"${(s.lighting || '').replace(/"/g, '""')}"`,
      `"${(s.targetModelPrompt || '').replace(/"/g, '""')}"`,
      `"${(s.audioScript || '').replace(/"/g, '""')}"`
    ]);

    const csvContent = 'data:text/csv;charset=utf-8,' + [headers.join(','), ...rows.map(r => r.join(','))].join('\n');
    const downloadAnchor = document.createElement('a');
    downloadAnchor.setAttribute('href', encodeURI(csvContent));
    downloadAnchor.setAttribute('download', `${projectTitle.replace(/[^a-z0-9]/gi, '_').toLowerCase()}_prompts.csv`);
    document.body.appendChild(downloadAnchor);
    downloadAnchor.click();
    downloadAnchor.remove();
  };

  return (
    <section className="storyboard-section">
      {/* Storyboard Top Control Bar */}
      <div className="storyboard-control-bar">
        {/* Left: Summary Metrics */}
        <div className="storyboard-metrics">
          <div className="metric-badge">
            <Film className="icon-cyan" />
            <span className="metric-val">{scenes.length}</span>
            <span className="metric-desc">Scenes</span>
          </div>
          <div className="metric-badge">
            <span className="metric-val">{totalDuration}s</span>
            <span className="metric-desc">Total Runtime</span>
          </div>
          <div className="metric-badge model-spec-badge">
            <span className="metric-desc">Model:</span>
            <span className="metric-val text-cyan">{targetModelInfo.name}</span>
          </div>
        </div>

        {/* Center: Search / Filter */}
        <div className="search-filter-box">
          <Search className="search-icon" />
          <input
            type="text"
            placeholder="Search scenes by lens, action, lighting..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="search-input"
          />
          {searchQuery && (
            <button className="clear-search-btn" onClick={() => setSearchQuery('')}>×</button>
          )}
        </div>

        {/* Right: View Mode Toggle & Batch Exports */}
        <div className="storyboard-actions-group">
          {/* View Mode Buttons */}
          <div className="view-mode-toggle">
            <button
              className={`view-mode-btn ${viewMode === 'cards' ? 'active' : ''}`}
              onClick={() => setViewMode('cards')}
              title="Full Director Cards View"
            >
              <Layers className="icon-sm" /> Cards
            </button>
            <button
              className={`view-mode-btn ${viewMode === 'compact' ? 'active' : ''}`}
              onClick={() => setViewMode('compact')}
              title="Compact Scene Grid"
            >
              <LayoutGrid className="icon-sm" /> Grid
            </button>
            <button
              className={`view-mode-btn ${viewMode === 'batch' ? 'active' : ''}`}
              onClick={() => setViewMode('batch')}
              title="Batch Prompt List"
            >
              <List className="icon-sm" /> Batch Prompts
            </button>
            <button
              className={`view-mode-btn ${viewMode === 'screenplay' ? 'active' : ''}`}
              onClick={() => setViewMode('screenplay')}
              title="Screenplay Script View"
            >
              <FileText className="icon-sm" /> Script
            </button>
          </div>

          {/* Batch Actions */}
          <div className="export-actions-dropdown">
            <button
              type="button"
              className={`batch-copy-btn ${copiedAll ? 'copied' : ''}`}
              onClick={handleCopyAllPrompts}
              title="Copy all scene prompts to clipboard"
            >
              {copiedAll ? (
                <>
                  <Check className="icon-sm" />
                  <span>All Copied!</span>
                </>
              ) : (
                <>
                  <Copy className="icon-sm" />
                  <span>Copy All ({scenes.length})</span>
                </>
              )}
            </button>

            <div className="export-buttons-group">
              <button
                type="button"
                className="export-btn"
                onClick={handleExportJSON}
                title="Download JSON Production File"
              >
                <FileCode className="icon-sm" /> JSON
              </button>
              <button
                type="button"
                className="export-btn"
                onClick={handleExportMarkdown}
                title="Download Screenplay Markdown"
              >
                <FileText className="icon-sm" /> Markdown
              </button>
              <button
                type="button"
                className="export-btn"
                onClick={handleExportCSV}
                title="Download CSV Spreadsheet"
              >
                <Table className="icon-sm" /> CSV
              </button>
            </div>
          </div>
        </div>
      </div>

      {/* VIEW MODE 1: Full Director Cards */}
      {viewMode === 'cards' && (
        <div className="scenes-list">
          {filteredScenes.map((scene, idx) => {
            const actualIndex = scenes.findIndex(s => s.sceneNumber === scene.sceneNumber);
            return (
              <SceneCard
                key={scene.sceneNumber || idx}
                scene={scene}
                index={actualIndex >= 0 ? actualIndex : idx}
                totalScenes={scenes.length}
                targetModelId={targetModel}
                isActive={activeSceneIndex === (actualIndex >= 0 ? actualIndex : idx)}
                onSelect={onSelectScene}
                onUpdateScene={onUpdateScene}
                onRegenerateScene={onRegenerateScene}
                isRegenerating={regeneratingIndex === (actualIndex >= 0 ? actualIndex : idx)}
              />
            );
          })}
        </div>
      )}

      {/* VIEW MODE 2: Compact Grid */}
      {viewMode === 'compact' && (
        <div className="compact-grid">
          {filteredScenes.map((scene, idx) => {
            const actualIndex = scenes.findIndex(s => s.sceneNumber === scene.sceneNumber);
            return (
              <div
                key={scene.sceneNumber || idx}
                className="compact-scene-card"
                onClick={() => {
                  onSelectScene(actualIndex);
                  setViewMode('cards');
                }}
              >
                <div className="compact-card-header">
                  <span className="compact-scene-num">#{String(scene.sceneNumber).padStart(2, '0')}</span>
                  <span className="compact-timecode">{scene.timecode}</span>
                  <span className="compact-dur">{scene.durationSec}s</span>
                </div>
                <h4 className="compact-title">{scene.title}</h4>
                <p className="compact-shot-type">{scene.shotType}</p>
                <p className="compact-prompt-preview">{scene.targetModelPrompt.slice(0, 140)}...</p>
                <div className="compact-card-footer">
                  <span className="compact-lens">{scene.focalLength}</span>
                  <span className="click-view-hint">Click to expand</span>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* VIEW MODE 3: Batch Prompts List */}
      {viewMode === 'batch' && (
        <div className="batch-prompts-view">
          <div className="batch-view-header">
            <h3>Sequential Prompt Queue ({scenes.length} Prompts for {targetModelInfo.name})</h3>
            <p>Formatted for rapid copy-pasting into video generation queues, Discord bots, or batch APIs.</p>
          </div>
          <div className="batch-prompts-container">
            {scenes.map((scene, idx) => (
              <div key={scene.sceneNumber || idx} className="batch-prompt-row">
                <div className="batch-row-header">
                  <span className="batch-scene-tag">Clip {scene.sceneNumber} • {scene.timecode} ({scene.durationSec}s)</span>
                  <button
                    className="batch-copy-single-btn"
                    onClick={() => navigator.clipboard.writeText(scene.targetModelPrompt)}
                  >
                    <Copy className="icon-sm" /> Copy
                  </button>
                </div>
                <pre className="batch-prompt-text">{scene.targetModelPrompt}</pre>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* VIEW MODE 4: Director's Screenplay View */}
      {viewMode === 'screenplay' && (
        <div className="screenplay-view-container">
          <div className="screenplay-page">
            <div className="screenplay-header-block">
              <h2 className="screenplay-title">{projectTitle.toUpperCase()}</h2>
              <p className="screenplay-meta">A {totalDuration}-Second Cinematic Video Sequence</p>
              <p className="screenplay-meta">Target AI Generator: {targetModelInfo.name} | Ratio: {projectData.aspectRatio || '16:9'}</p>
            </div>

            <div className="screenplay-synopsis-block">
              <strong>SYNOPSIS:</strong>
              <p>{synopsis}</p>
            </div>

            <hr className="screenplay-divider" />

            <div className="screenplay-scenes-body">
              {scenes.map((scene) => (
                <div key={scene.sceneNumber} className="screenplay-scene-entry">
                  <h3 className="screenplay-slugline">
                    SCENE {scene.sceneNumber} - {scene.timecode} - {scene.shotType.toUpperCase()}
                  </h3>
                  <div className="screenplay-optics-note">
                    [LENS: {scene.focalLength} | CAMERA: {scene.cameraMovement} | LIGHTING: {scene.lighting}]
                  </div>
                  <div className="screenplay-action-text">
                    {scene.visualDescription}
                  </div>
                  {scene.audioScript && (
                    <div className="screenplay-audio-dialogue">
                      <div className="audio-character">SOUND DESIGN & AUDIO</div>
                      <div className="audio-parenthetical">(over {scene.durationSec} seconds)</div>
                      <div className="audio-dialogue-line">{scene.audioScript}</div>
                    </div>
                  )}
                  <div className="screenplay-prompt-box">
                    <span className="screenplay-prompt-tag">AI VIDEO GENERATOR PROMPT:</span>
                    <p>{scene.targetModelPrompt}</p>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
    </section>
  );
}
