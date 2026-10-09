import React from 'react';
import { HelpCircle, X, Check, Video, Clock, Film, Sparkles } from 'lucide-react';
import { VIDEO_MODELS } from '../constants/models';

export function HelpModal({ isOpen, onClose }) {
  if (!isOpen) return null;

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal-dialog modal-lg" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <div className="modal-title-group">
            <HelpCircle className="icon-cyan" />
            <h3>AI Video Prompting & Director Guide</h3>
          </div>
          <button className="modal-close-btn" onClick={onClose}>
            <X className="icon-sm" />
          </button>
        </div>

        <div className="modal-body modal-scrollable">
          {/* Section: Clip Math */}
          <div className="guide-section">
            <h4 className="guide-section-title">
              <Clock className="icon-sm text-cyan" /> How Scene Calculation Works
            </h4>
            <p className="guide-text">
              Video AI models generate clips in discreet second durations (typically 5s, 8s, 10s, or 15s).
              When you specify your total target video runtime (e.g., <strong>60 seconds</strong>) and your clip segment duration (e.g., <strong>5 seconds</strong>):
            </p>
            <div className="guide-formula-box">
              <code>Scenes = Total Duration ÷ Clip Duration</code>
              <p>Example: 60s ÷ 5s = <strong>12 Distinct Scenes</strong></p>
              <p>Each scene is assigned an exact timecode (00:00 - 00:05, 00:05 - 00:10, etc.) with progressive narrative beats.</p>
            </div>
          </div>

          {/* Section: Video Models Guide */}
          <div className="guide-section">
            <h4 className="guide-section-title">
              <Video className="icon-sm text-cyan" /> Model Prompting Best Practices
            </h4>
            <div className="model-guide-grid">
              {VIDEO_MODELS.map(m => (
                <div key={m.id} className="model-guide-card">
                  <div className="model-guide-header">
                    <strong style={{ color: m.color }}>{m.name}</strong>
                    <span className="guide-badge">{m.badge}</span>
                  </div>
                  <p className="guide-syntax-format"><em>Format:</em> {m.promptFormat}</p>
                  <ul className="guide-tips-list">
                    {m.guidelines.map((tip, idx) => (
                      <li key={idx}>{tip}</li>
                    ))}
                  </ul>
                </div>
              ))}
            </div>
          </div>

          {/* Section: Reliability & Cost */}
          <div className="guide-section">
            <h4 className="guide-section-title">
              <Sparkles className="icon-sm text-cyan" /> OpenAI gpt-4o-mini Reliability & Cost
            </h4>
            <p className="guide-text">
              We selected <strong>gpt-4o-mini</strong> as the prompt engine because:
            </p>
            <ul className="guide-benefits-list">
              <li><strong>Ultra Reliable:</strong> Strictly follows JSON schemas, ensuring all 12 scenes are generated with complete camera and audio metadata.</li>
              <li><strong>Inexpensive:</strong> At $0.150 per 1M input tokens and $0.600 per 1M output tokens, generating 12 ultra-detailed cinematic scenes costs less than <strong>$0.002 (one fifth of a penny)</strong>.</li>
              <li><strong>High Speed:</strong> Completes complex 12-scene directorial breakdowns in ~3 to 5 seconds.</li>
            </ul>
          </div>
        </div>

        <div className="modal-footer">
          <button type="button" className="btn-primary" onClick={onClose}>
            Got it, Let's Direct!
          </button>
        </div>
      </div>
    </div>
  );
}
