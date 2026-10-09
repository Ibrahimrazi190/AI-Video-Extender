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
  Eye,
  SlidersHorizontal,
  Share2
} from 'lucide-react';
import { VIDEO_MODELS } from '../constants/models';

export function MasterPromptView({
  projectData,
  onUpdateMasterPrompt,
  onRegenerate
}) {
  const [copied, setCopied] = useState(false);
  const [copiedNegative, setCopiedNegative] = useState(false);
  const [isEditing, setIsEditing] = useState(false);
  const [editedText, setEditedText] = useState(projectData?.masterPrompt || '');
  const [activeTimeRange, setActiveTimeRange] = useState(null);

  if (!projectData || !projectData.masterPrompt) return null;

  const {
    title,
    totalDuration,
    clipDuration,
    aspectRatio,
    targetModel,
    masterPrompt,
    timeSegments = [],
    negativePrompt,
    modelUsed
  } = projectData;

  const currentModel = VIDEO_MODELS.find(m => m.id === targetModel) || VIDEO_MODELS[0];
  const wordCount = masterPrompt.trim().split(/\s+/).filter(Boolean).length;
  const charCount = masterPrompt.length;

  const handleCopyFull = async () => {
    try {
      await navigator.clipboard.writeText(masterPrompt);
      setCopied(true);
      setTimeout(() => setCopied(false), 2500);
    } catch (err) {
      console.error('Failed to copy', err);
    }
  };

  const handleCopyNegative = async () => {
    if (!negativePrompt) return;
    try {
      await navigator.clipboard.writeText(negativePrompt);
      setCopiedNegative(true);
      setTimeout(() => setCopiedNegative(false), 2000);
    } catch (err) {
      console.error('Failed to copy negative prompt', err);
    }
  };

  const handleSaveEdit = () => {
    onUpdateMasterPrompt(editedText);
    setIsEditing(false);
  };

  const handleCancelEdit = () => {
    setEditedText(masterPrompt);
    setIsEditing(false);
  };

  const handleDownloadTxt = () => {
    const element = document.createElement('a');
    const file = new Blob([masterPrompt], { type: 'text/plain' });
    element.href = URL.createObjectURL(file);
    element.download = `${(title || 'video_prompt').replace(/[^a-z0-9]/gi, '_').toLowerCase()}.txt`;
    document.body.appendChild(element);
    element.click();
    element.remove();
  };

  const handleDownloadMd = () => {
    const mdContent = `# ${title}\n\n**Duration:** ${totalDuration}s | **Aspect Ratio:** ${aspectRatio} | **Model:** ${currentModel.name}\n\n\`\`\`\n${masterPrompt}\n\`\`\`\n`;
    const element = document.createElement('a');
    const file = new Blob([mdContent], { type: 'text/markdown' });
    element.href = URL.createObjectURL(file);
    element.download = `${(title || 'video_prompt').replace(/[^a-z0-9]/gi, '_').toLowerCase()}.md`;
    document.body.appendChild(element);
    element.click();
    element.remove();
  };

  const handleSegmentClick = (segment) => {
    setActiveTimeRange(segment.range);
    // Find text in textarea/pre and focus
    const promptArea = document.getElementById('master-prompt-code');
    if (promptArea) {
      promptArea.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }
  };

  return (
    <section className="master-result-section">
      {/* Top Banner / Hero Bar */}
      <div className="master-header-card">
        <div className="master-meta-left">
          <div className="master-title-row">
            <h2 className="master-prompt-title">{title || 'Cinematic Master Video Sequence'}</h2>
            <span className="master-one-result-badge">
              <CheckCircle2 className="icon-sm" /> ONE UNIFIED MASTER PROMPT
            </span>
          </div>
          <div className="master-tags-row">
            <span className="meta-pill text-cyan">
              <Video className="icon-sm" /> Ready for: <strong>{currentModel.name}</strong>
            </span>
            <span className="meta-pill">
              <Clock className="icon-sm" /> Total: <strong>{totalDuration}s</strong>
            </span>
            <span className="meta-pill">
              <Film className="icon-sm" /> Segment Step: <strong>{clipDuration}s cuts</strong> ({timeSegments.length || Math.ceil(totalDuration / clipDuration)} phases)
            </span>
            <span className="meta-pill">
              Ratio: <strong>{aspectRatio}</strong>
            </span>
            <span className="meta-pill font-mono">
              {wordCount} words • {charCount} chars
            </span>
          </div>
        </div>

        {/* Primary Copy Button */}
        <div className="master-actions-right">
          <button
            type="button"
            className={`master-copy-primary-btn ${copied ? 'is-copied' : ''}`}
            onClick={handleCopyFull}
            title={`Copy the complete prompt ready to paste directly into ${currentModel.name}`}
          >
            {copied ? (
              <>
                <Check className="btn-icon" />
                <span>Copied Full Master Prompt!</span>
              </>
            ) : (
              <>
                <Copy className="btn-icon" />
                <span>Copy Full Master Prompt</span>
              </>
            )}
            <span className="btn-shine"></span>
          </button>
        </div>
      </div>

      {/* Interactive Chronological Timeline Ruler */}
      {timeSegments.length > 0 && (
        <div className="master-timeline-bar">
          <div className="master-timeline-header">
            <span className="timeline-title">
              <Clock className="icon-sm text-cyan" /> Chronological Timeline Cues ({timeSegments.length} Segments):
            </span>
            <span className="timeline-hint">Click a segment to inspect that part of the prompt</span>
          </div>
          <div className="master-timeline-track">
            {timeSegments.map((seg, idx) => (
              <button
                key={idx}
                type="button"
                className={`master-timeline-chip ${activeTimeRange === seg.range ? 'active' : ''}`}
                onClick={() => handleSegmentClick(seg)}
                title={`${seg.range}: ${seg.camera || seg.label}`}
              >
                <span className="chip-time">{seg.range}</span>
                <span className="chip-sub">{seg.label || `Cut ${idx + 1}`}</span>
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Main Unified Prompt Canvas / Box */}
      <div className="master-prompt-canvas-card">
        {/* Canvas Toolbar */}
        <div className="canvas-toolbar">
          <div className="canvas-toolbar-left">
            <span className="terminal-dot red"></span>
            <span className="terminal-dot yellow"></span>
            <span className="terminal-dot green"></span>
            <span className="canvas-label">MASTER_PROMPT.TXT</span>
            <span className="canvas-model-indicator">Direct Target: {currentModel.name}</span>
          </div>

          <div className="canvas-toolbar-right">
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
              <button
                type="button"
                className="edit-prompt-btn"
                onClick={() => {
                  setEditedText(masterPrompt);
                  setIsEditing(true);
                }}
                title="Edit the prompt text inline"
              >
                <Edit3 className="icon-sm" /> Edit Prompt
              </button>
            )}

            {negativePrompt && (
              <button
                type="button"
                className="toolbar-ghost-btn"
                onClick={handleCopyNegative}
                title="Copy negative prompt only"
              >
                {copiedNegative ? <Check className="icon-sm text-green" /> : <Copy className="icon-sm" />}
                <span>{copiedNegative ? 'Negative Copied' : 'Copy Negative'}</span>
              </button>
            )}

            <button
              type="button"
              className="toolbar-ghost-btn"
              onClick={handleDownloadTxt}
              title="Download as .txt file"
            >
              <Download className="icon-sm" /> .TXT
            </button>

            <button
              type="button"
              className="toolbar-ghost-btn"
              onClick={handleDownloadMd}
              title="Download as Markdown"
            >
              <FileText className="icon-sm" /> .MD
            </button>
          </div>
        </div>

        {/* Prompt Content */}
        <div className="canvas-body">
          {isEditing ? (
            <textarea
              className="master-prompt-textarea font-mono"
              rows={24}
              value={editedText}
              onChange={(e) => setEditedText(e.target.value)}
            />
          ) : (
            <pre id="master-prompt-code" className="master-prompt-display font-mono">
              {masterPrompt}
            </pre>
          )}
        </div>

        {/* Footer Quick Action Bar */}
        <div className="canvas-footer">
          <div className="canvas-footer-left">
            <span className="format-hint">
              ✨ Formatted for single continuous generation: <strong>Zero cuts, unbroken camera flow, complete audio & negative locks.</strong>
            </span>
          </div>

          <div className="canvas-footer-right">
            <button
              type="button"
              className="footer-copy-btn"
              onClick={handleCopyFull}
            >
              <Copy className="icon-sm" /> {copied ? 'Copied to Clipboard!' : 'Copy Entire Prompt'}
            </button>
          </div>
        </div>
      </div>
    </section>
  );
}
