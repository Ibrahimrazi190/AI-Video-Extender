import React, { useState } from 'react';
import {
  Copy,
  Check,
  Download,
  FileText,
  Edit3,
  Save,
  RotateCcw,
  Sparkles,
  Film,
  Clock,
  Video,
  CheckCircle2,
  ChevronRight,
  ChevronLeft,
  ArrowRight,
  Link2,
  Layers,
  List
} from 'lucide-react';
import { VIDEO_MODELS } from '../constants/models';

export function ClipMasterPromptsView({
  projectData,
  onUpdateClipPrompt
}) {
  const [activeClipIndex, setActiveClipIndex] = useState(0);
  const [copiedClipIndex, setCopiedClipIndex] = useState(null);
  const [copiedAll, setCopiedAll] = useState(false);
  const [isEditing, setIsEditing] = useState(false);
  const [viewMode, setViewMode] = useState('focus'); // 'focus' (single clip inspector) or 'all' (all clips sequential)
  const [editedPromptText, setEditedPromptText] = useState('');

  if (!projectData || !projectData.clips || projectData.clips.length === 0) return null;

  const {
    projectTitle,
    totalDuration,
    clipDuration,
    clipCount,
    targetModel,
    aspectRatio,
    clips = []
  } = projectData;

  const currentModel = VIDEO_MODELS.find(m => m.id === targetModel) || VIDEO_MODELS[0];
  const activeClip = clips[activeClipIndex] || clips[0];

  // Copy individual clip master prompt
  const handleCopySingleClip = async (clip, index) => {
    try {
      await navigator.clipboard.writeText(clip.masterPrompt);
      setCopiedClipIndex(index);
      setTimeout(() => setCopiedClipIndex(null), 2200);
    } catch (err) {
      console.error('Failed to copy clip', err);
    }
  };

  // Copy all clip master prompts formatted sequentially
  const handleCopyAllClips = async () => {
    const formattedAll = clips.map((clip) => {
      return `=======================================================\nCLIP ${clip.clipNumber} (${clip.timecode}) - ${clip.title}\n=======================================================\n\n${clip.masterPrompt}\n`;
    }).join('\n\n');

    try {
      await navigator.clipboard.writeText(formattedAll);
      setCopiedAll(true);
      setTimeout(() => setCopiedAll(false), 2500);
    } catch (err) {
      console.error('Failed to copy all', err);
    }
  };

  const handleStartEdit = () => {
    setEditedPromptText(activeClip.masterPrompt);
    setIsEditing(true);
  };

  const handleSaveEdit = () => {
    onUpdateClipPrompt(activeClipIndex, editedPromptText);
    setIsEditing(false);
  };

  const handleCancelEdit = () => {
    setIsEditing(false);
  };

  const handleDownloadTxt = () => {
    const formattedAll = clips.map((clip) => {
      return `=== CLIP ${clip.clipNumber} (${clip.timecode}): ${clip.title} ===\n\n${clip.masterPrompt}\n`;
    }).join('\n\n');

    const element = document.createElement('a');
    const file = new Blob([formattedAll], { type: 'text/plain' });
    element.href = URL.createObjectURL(file);
    element.download = `${(projectTitle || 'storyboard').replace(/[^a-z0-9]/gi, '_').toLowerCase()}_master_prompts.txt`;
    document.body.appendChild(element);
    element.click();
    element.remove();
  };

  const handleDownloadMd = () => {
    let md = `# ${projectTitle}\n\n`;
    md += `**Total Duration:** ${totalDuration}s | **Clip Length:** ${clipDuration}s | **Clips Count:** ${clips.length} | **Target Model:** ${currentModel.name}\n\n---\n\n`;
    clips.forEach(clip => {
      md += `## Clip ${clip.clipNumber}: ${clip.title} (${clip.timecode})\n`;
      md += `**Continuity Hand-off:** *${clip.continuityNote}*\n\n`;
      md += `\`\`\`\n${clip.masterPrompt}\n\`\`\`\n\n---\n\n`;
    });

    const element = document.createElement('a');
    const file = new Blob([md], { type: 'text/markdown' });
    element.href = URL.createObjectURL(file);
    element.download = `${(projectTitle || 'storyboard').replace(/[^a-z0-9]/gi, '_').toLowerCase()}_prompts.md`;
    document.body.appendChild(element);
    element.click();
    element.remove();
  };

  return (
    <section className="clip-master-section">
      {/* Top Banner / Hero Card */}
      <div className="clip-master-header-card">
        <div className="header-meta-left">
          <div className="header-title-row">
            <h2 className="project-heading">{projectTitle || 'Sequential Master Video Storyboard'}</h2>
            <span className="continuity-locked-badge">
              <Link2 className="icon-sm" /> CONTINUITY LOCKED
            </span>
          </div>
          <div className="header-tags-row">
            <span className="meta-pill text-cyan">
              <Video className="icon-sm" /> Target: <strong>{currentModel.name}</strong>
            </span>
            <span className="meta-pill">
              <Clock className="icon-sm" /> Total: <strong>{totalDuration}s</strong>
            </span>
            <span className="meta-pill">
              <Film className="icon-sm" /> Clip Size: <strong>{clipDuration}s cuts</strong>
            </span>
            <span className="meta-pill highlight-pill">
              ✨ <strong>{clips.length} Master Prompts</strong> (One for each scene)
            </span>
          </div>
        </div>

        {/* Global Batch Actions */}
        <div className="header-actions-right">
          <button
            type="button"
            className={`copy-all-btn ${copiedAll ? 'is-copied' : ''}`}
            onClick={handleCopyAllClips}
            title="Copy all clip master prompts formatted with sequential headers"
          >
            {copiedAll ? (
              <>
                <Check className="btn-icon" />
                <span>All {clips.length} Prompts Copied!</span>
              </>
            ) : (
              <>
                <Copy className="btn-icon" />
                <span>Copy All {clips.length} Prompts</span>
              </>
            )}
            <span className="btn-shine"></span>
          </button>

          <div className="export-btn-group">
            <button type="button" className="ghost-btn" onClick={handleDownloadTxt} title="Download .txt">
              <Download className="icon-sm" /> .TXT
            </button>
            <button type="button" className="ghost-btn" onClick={handleDownloadMd} title="Download .md">
              <FileText className="icon-sm" /> .MD
            </button>
          </div>
        </div>
      </div>

      {/* View Mode & Sequential Timeline Bar */}
      <div className="continuity-timeline-card">
        <div className="continuity-timeline-top">
          <div className="timeline-title-group">
            <Film className="icon-cyan" />
            <span className="timeline-heading">Sequential Continuity Chain ({clips.length} Scenes):</span>
            <span className="timeline-subtext">Each clip picks up exactly where the previous frame ended</span>
          </div>

          <div className="view-mode-switch">
            <button
              type="button"
              className={`mode-btn ${viewMode === 'focus' ? 'active' : ''}`}
              onClick={() => setViewMode('focus')}
            >
              <Layers className="icon-sm" /> Single Clip Focus
            </button>
            <button
              type="button"
              className={`mode-btn ${viewMode === 'all' ? 'active' : ''}`}
              onClick={() => setViewMode('all')}
            >
              <List className="icon-sm" /> View All ({clips.length})
            </button>
          </div>
        </div>

        {/* Sequential Timeline Filmstrip Chips */}
        <div className="continuity-chips-track">
          {clips.map((c, idx) => {
            const isActive = activeClipIndex === idx;
            return (
              <React.Fragment key={c.clipNumber || idx}>
                <button
                  type="button"
                  className={`clip-chain-pill ${isActive ? 'active' : ''}`}
                  onClick={() => {
                    setActiveClipIndex(idx);
                    setViewMode('focus');
                  }}
                >
                  <div className="pill-top-row">
                    <span className="pill-num">Clip {c.clipNumber}</span>
                    <span className="pill-time">{c.timecode}</span>
                  </div>
                  <span className="pill-title">{c.title?.slice(0, 24)}...</span>
                </button>

                {idx < clips.length - 1 && (
                  <div className="continuity-chain-connector" title="Continuous physical momentum & lighting hand-off">
                    <div className="chain-line"></div>
                    <Link2 className="chain-icon" />
                    <div className="chain-line"></div>
                  </div>
                )}
              </React.Fragment>
            );
          })}
        </div>
      </div>

      {/* MODE 1: SINGLE CLIP FOCUS INSPECTOR */}
      {viewMode === 'focus' && (
        <div className="active-clip-inspector">
          {/* Active Clip Header Bar */}
          <div className="clip-inspector-header">
            <div className="inspector-title-block">
              <div className="clip-id-pill">
                <span>CLIP {activeClip.clipNumber} OF {clips.length}</span>
                <span className="clip-time-tag">{activeClip.timecode} ({activeClip.durationSec || clipDuration}s cut)</span>
              </div>
              <h3 className="inspector-clip-title">{activeClip.title}</h3>
            </div>

            <div className="inspector-actions">
              {isEditing ? (
                <div className="edit-btn-group">
                  <button type="button" className="save-btn" onClick={handleSaveEdit}>
                    <Save className="icon-sm" /> Save Changes
                  </button>
                  <button type="button" className="cancel-btn" onClick={handleCancelEdit}>
                    Cancel
                  </button>
                </div>
              ) : (
                <button type="button" className="ghost-btn" onClick={handleStartEdit}>
                  <Edit3 className="icon-sm" /> Edit Prompt
                </button>
              )}

              <button
                type="button"
                className={`single-clip-copy-btn ${copiedClipIndex === activeClipIndex ? 'copied' : ''}`}
                onClick={() => handleCopySingleClip(activeClip, activeClipIndex)}
              >
                {copiedClipIndex === activeClipIndex ? (
                  <>
                    <Check className="icon-sm" />
                    <span>Copied Clip {activeClip.clipNumber}!</span>
                  </>
                ) : (
                  <>
                    <Copy className="icon-sm" />
                    <span>Copy Clip {activeClip.clipNumber} Master Prompt</span>
                  </>
                )}
              </button>
            </div>
          </div>

          {/* Continuity Hand-off Callout */}
          <div className="continuity-handoff-banner">
            <div className="handoff-icon-wrap">
              <Link2 className="icon-cyan" />
            </div>
            <div className="handoff-text-wrap">
              <strong>Seamless Continuity Hand-off:</strong>
              <p>{activeClip.continuityNote}</p>
            </div>
          </div>

          {/* Script panel: dialogue + start/end frames */}
          {(activeClip.dialogue?.length > 0 || activeClip.firstFrame || activeClip.lastFrame) && (
            <div className="clip-script-panel">
              <div className="clip-script-col">
                <strong>Dialogue</strong>
                {activeClip.dialogue?.length > 0 ? (
                  activeClip.dialogue.map((line, i) => (
                    <p key={i} className="clip-script-line">
                      <span className="clip-script-time">{line.fromSec}–{line.toSec}s</span>{' '}
                      <b>{line.speakerName || line.speaker}</b>
                      {line.delivery ? <em> ({line.delivery})</em> : null}: “{line.text}”
                    </p>
                  ))
                ) : (
                  <p className="clip-script-line"><em>No spoken dialogue in this clip.</em></p>
                )}
              </div>
              <div className="clip-script-col">
                <strong>Start frame</strong>
                <p className="clip-script-line">{activeClip.firstFrame}</p>
                <strong>End frame</strong>
                <p className="clip-script-line">{activeClip.lastFrame}</p>
              </div>
            </div>
          )}

          {/* Master Prompt Terminal Canvas */}
          <div className="clip-prompt-canvas">
            <div className="canvas-header-bar">
              <div className="mac-dots">
                <span className="dot dot-r"></span>
                <span className="dot dot-y"></span>
                <span className="dot dot-g"></span>
                <span className="canvas-name">CLIP_{activeClip.clipNumber}_MASTER_PROMPT.TXT</span>
              </div>
              <span className="canvas-model-badge">Direct Model: {currentModel.name}</span>
            </div>

            <div className="canvas-content-box">
              {isEditing ? (
                <textarea
                  className="clip-prompt-textarea font-mono"
                  rows={20}
                  value={editedPromptText}
                  onChange={(e) => setEditedPromptText(e.target.value)}
                />
              ) : (
                <pre className="clip-prompt-pre font-mono">
                  {activeClip.masterPrompt}
                </pre>
              )}
            </div>

            <div className="canvas-footer-bar">
              <div className="footer-nav-left">
                <button
                  type="button"
                  className="nav-btn"
                  disabled={activeClipIndex === 0}
                  onClick={() => setActiveClipIndex(prev => Math.max(0, prev - 1))}
                >
                  <ChevronLeft className="icon-sm" /> Previous Clip
                </button>
              </div>

              <span className="canvas-stats">
                {activeClip.masterPrompt.trim().split(/\s+/).length} words • {activeClip.masterPrompt.length} chars
              </span>

              <div className="footer-nav-right">
                <button
                  type="button"
                  className="nav-btn"
                  disabled={activeClipIndex === clips.length - 1}
                  onClick={() => setActiveClipIndex(prev => Math.min(clips.length - 1, prev + 1))}
                >
                  Next Clip <ChevronRight className="icon-sm" />
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* MODE 2: VIEW ALL CLIPS SEQUENTIAL */}
      {viewMode === 'all' && (
        <div className="all-clips-sequential-container">
          {clips.map((clip, idx) => (
            <div key={clip.clipNumber || idx} className="sequential-clip-card">
              <div className="sequential-clip-header">
                <div className="sequential-title-group">
                  <span className="clip-seq-badge">CLIP {clip.clipNumber} OF {clips.length}</span>
                  <span className="clip-seq-time">{clip.timecode}</span>
                  <h4 className="clip-seq-title">{clip.title}</h4>
                </div>

                <button
                  type="button"
                  className={`seq-copy-btn ${copiedClipIndex === idx ? 'copied' : ''}`}
                  onClick={() => handleCopySingleClip(clip, idx)}
                >
                  {copiedClipIndex === idx ? (
                    <>
                      <Check className="icon-sm" /> Copied!
                    </>
                  ) : (
                    <>
                      <Copy className="icon-sm" /> Copy Clip {clip.clipNumber} Prompt
                    </>
                  )}
                </button>
              </div>

              <div className="sequential-continuity-note">
                <Link2 className="icon-sm text-cyan" />
                <span><strong>Continuity Handoff:</strong> {clip.continuityNote}</span>
              </div>

              <div className="sequential-prompt-box">
                <pre className="sequential-pre font-mono">{clip.masterPrompt}</pre>
              </div>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
