import React, { useState } from 'react';
import {
  Copy,
  Check,
  Camera,
  Sun,
  Eye,
  Volume2,
  AlertTriangle,
  RotateCcw,
  Edit3,
  Save,
  CheckCircle2,
  ExternalLink,
  ChevronDown,
  Sparkles,
  Layers
} from 'lucide-react';
import { VIDEO_MODELS } from '../constants/models';

export function SceneCard({
  scene,
  index,
  totalScenes,
  targetModelId,
  isActive,
  onSelect,
  onUpdateScene,
  onRegenerateScene,
  isRegenerating
}) {
  const [copied, setCopied] = useState(false);
  const [isEditing, setIsEditing] = useState(false);
  const [editedPrompt, setEditedPrompt] = useState(scene.targetModelPrompt);
  const [activeTab, setActiveTab] = useState('camera'); // 'camera', 'lighting', 'action', 'audio', 'negative'

  const targetModel = VIDEO_MODELS.find(m => m.id === targetModelId) || VIDEO_MODELS[0];

  const handleCopyPrompt = async (e) => {
    e.stopPropagation();
    try {
      await navigator.clipboard.writeText(scene.targetModelPrompt);
      setCopied(true);
      setTimeout(() => setCopied(false), 2200);
    } catch (err) {
      console.error('Failed to copy', err);
    }
  };

  const handleSaveEdit = (e) => {
    e.stopPropagation();
    onUpdateScene(index, { targetModelPrompt: editedPrompt });
    setIsEditing(false);
  };

  const handleCancelEdit = (e) => {
    e.stopPropagation();
    setEditedPrompt(scene.targetModelPrompt);
    setIsEditing(false);
  };

  return (
    <div
      id={`scene-card-${index}`}
      className={`scene-card ${isActive ? 'is-active' : ''}`}
      onClick={() => onSelect(index)}
    >
      {/* Top Banner / Timecode Bar */}
      <div className="scene-card-top-bar">
        <div className="scene-num-badge">
          <span className="scene-index-pill">SCENE {String(scene.sceneNumber || index + 1).padStart(2, '0')}</span>
          <span className="scene-of-total">of {totalScenes}</span>
        </div>

        <div className="scene-timecode-badge">
          <span className="timecode-text">{scene.timecode}</span>
          <span className="duration-pill">{scene.durationSec}s cut</span>
        </div>

        <div className="scene-beat-tag">
          {scene.narrativeBeat || `Beat ${index + 1}`}
        </div>
      </div>

      {/* Title & Technical Specs Pill Row */}
      <div className="scene-title-row">
        <h3 className="scene-title">{scene.title || `Scene ${index + 1}`}</h3>
        <div className="scene-tech-specs">
          <span className="spec-pill" title="Shot Type">
            <Camera className="spec-icon" /> {scene.shotType}
          </span>
          <span className="spec-pill" title="Focal Length & Lens">
            <Layers className="spec-icon" /> {scene.focalLength}
          </span>
        </div>
      </div>

      {/* Target Model Prompt Container */}
      <div className="model-prompt-block">
        <div className="prompt-header">
          <div className="prompt-meta">
            <span className="target-model-pill" style={{ borderColor: targetModel.color, color: targetModel.color }}>
              <span className="model-bullet" style={{ background: targetModel.color }}></span>
              Ready for {targetModel.name}
            </span>
            <span className="prompt-stats">
              {scene.targetModelPrompt.length} chars • ~{Math.round(scene.targetModelPrompt.split(/\s+/).length)} words
            </span>
          </div>

          <div className="prompt-actions">
            {isEditing ? (
              <div className="edit-btn-group">
                <button
                  type="button"
                  className="save-btn"
                  onClick={handleSaveEdit}
                  title="Save edited prompt"
                >
                  <Save className="icon-sm" /> Save
                </button>
                <button
                  type="button"
                  className="cancel-btn"
                  onClick={handleCancelEdit}
                >
                  Cancel
                </button>
              </div>
            ) : (
              <button
                type="button"
                className="edit-prompt-btn"
                onClick={(e) => {
                  e.stopPropagation();
                  setEditedPrompt(scene.targetModelPrompt);
                  setIsEditing(true);
                }}
                title="Edit prompt text"
              >
                <Edit3 className="icon-sm" /> Edit
              </button>
            )}

            <button
              type="button"
              className={`copy-prompt-btn ${copied ? 'copied' : ''}`}
              onClick={handleCopyPrompt}
              title={`Copy prompt formatted for ${targetModel.name}`}
            >
              {copied ? (
                <>
                  <Check className="icon-sm" />
                  <span>Copied!</span>
                </>
              ) : (
                <>
                  <Copy className="icon-sm" />
                  <span>Copy Prompt</span>
                </>
              )}
            </button>
          </div>
        </div>

        {/* Prompt Content */}
        {isEditing ? (
          <textarea
            className="prompt-edit-textarea"
            rows={4}
            value={editedPrompt}
            onChange={(e) => setEditedPrompt(e.target.value)}
            onClick={(e) => e.stopPropagation()}
          />
        ) : (
          <div className="prompt-content-display">
            <code>{scene.targetModelPrompt}</code>
          </div>
        )}
      </div>

      {/* Breakdown Details Accordion/Tabs */}
      <div className="scene-details-tabs-container" onClick={(e) => e.stopPropagation()}>
        <div className="details-tab-nav">
          <button
            type="button"
            className={`detail-tab-btn ${activeTab === 'camera' ? 'active' : ''}`}
            onClick={() => setActiveTab('camera')}
          >
            <Camera className="icon-sm" /> Camera & Motion
          </button>
          <button
            type="button"
            className={`detail-tab-btn ${activeTab === 'lighting' ? 'active' : ''}`}
            onClick={() => setActiveTab('lighting')}
          >
            <Sun className="icon-sm" /> Lighting & Atmosphere
          </button>
          <button
            type="button"
            className={`detail-tab-btn ${activeTab === 'action' ? 'active' : ''}`}
            onClick={() => setActiveTab('action')}
          >
            <Eye className="icon-sm" /> Action & Physics
          </button>
          <button
            type="button"
            className={`detail-tab-btn ${activeTab === 'audio' ? 'active' : ''}`}
            onClick={() => setActiveTab('audio')}
          >
            <Volume2 className="icon-sm" /> Audio & Script
          </button>
          {scene.negativePrompt && (
            <button
              type="button"
              className={`detail-tab-btn ${activeTab === 'negative' ? 'active' : ''}`}
              onClick={() => setActiveTab('negative')}
            >
              <AlertTriangle className="icon-sm" /> Negative Prompt
            </button>
          )}
        </div>

        <div className="detail-tab-panel">
          {activeTab === 'camera' && (
            <div className="tab-content camera-content">
              <div className="detail-grid">
                <div className="detail-item">
                  <span className="detail-label">Camera Movement:</span>
                  <span className="detail-value">{scene.cameraMovement}</span>
                </div>
                <div className="detail-item">
                  <span className="detail-label">Shot Classification:</span>
                  <span className="detail-value">{scene.shotType}</span>
                </div>
                <div className="detail-item">
                  <span className="detail-label">Optics & Aperture:</span>
                  <span className="detail-value">{scene.focalLength}</span>
                </div>
              </div>
            </div>
          )}

          {activeTab === 'lighting' && (
            <div className="tab-content lighting-content">
              <div className="detail-item">
                <span className="detail-label">Atmospheric & Lighting Setup:</span>
                <p className="detail-paragraph">{scene.lighting}</p>
              </div>
            </div>
          )}

          {activeTab === 'action' && (
            <div className="tab-content action-content">
              <div className="detail-item">
                <span className="detail-label">Subject Choreography & Physics:</span>
                <p className="detail-paragraph">{scene.visualDescription}</p>
              </div>
              {scene.continuityNotes && (
                <div className="continuity-box">
                  <span className="continuity-label">Continuity Lock:</span>
                  <span className="continuity-value">{scene.continuityNotes}</span>
                </div>
              )}
            </div>
          )}

          {activeTab === 'audio' && (
            <div className="tab-content audio-content">
              <div className="detail-item">
                <span className="detail-label">Sound Design, Foley & Dialogue Cue:</span>
                <p className="detail-paragraph font-mono">{scene.audioScript}</p>
              </div>
            </div>
          )}

          {activeTab === 'negative' && (
            <div className="tab-content negative-content">
              <div className="detail-item">
                <span className="detail-label">Negative Prompt Filter:</span>
                <code className="negative-code">{scene.negativePrompt}</code>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Footer Bar with Re-roll Button */}
      <div className="scene-card-footer">
        <span className="scene-footer-status">
          <CheckCircle2 className="icon-sm text-green" /> Ready for video generator upload
        </span>

        <button
          type="button"
          className="reroll-scene-btn"
          onClick={(e) => {
            e.stopPropagation();
            onRegenerateScene(index);
          }}
          disabled={isRegenerating}
          title="Regenerate this specific scene with AI"
        >
          <RotateCcw className={`icon-sm ${isRegenerating ? 'spin-icon' : ''}`} />
          <span>{isRegenerating ? 'Re-rolling...' : 'Re-roll Scene'}</span>
        </button>
      </div>
    </div>
  );
}
