import React from 'react';
import { Film, Zap, Key, HelpCircle, Server, FolderGit2, CheckCircle2 } from 'lucide-react';

export function Header({
  hasApiKey,
  backendConnected,
  onOpenApiKeyModal,
  onOpenHelpModal,
  onOpenHistoryModal,
  sceneCount,
  modelName
}) {
  return (
    <header className="site-header">
      <div className="header-container">
        {/* Logo and branding */}
        <div className="brand-group">
          <div className="brand-icon-wrapper">
            <Film className="brand-icon" />
            <span className="brand-glow"></span>
          </div>
          <div>
            <div className="brand-title-row">
              <h1 className="brand-title">VisioPrompt <span className="gradient-text">AI</span></h1>
              <span className="badge version-badge">v2.5 Full-Stack</span>
            </div>
            <p className="brand-subtitle">AI Video Director • Multi-Scene Prompt Extender</p>
          </div>
        </div>

        {/* Status Pills and Action Buttons */}
        <div className="header-actions">
          {/* Backend Status Pill */}
          <div
            className={`backend-status-pill ${backendConnected ? 'connected' : 'connecting'}`}
            title={backendConnected ? 'Express Backend connected on port 3001' : 'Attempting connection to Express backend'}
          >
            <Server className="pill-icon-sm" />
            <span>{backendConnected ? 'Backend Connected' : 'Connecting API...'}</span>
            <span className={`status-pulse-dot ${backendConnected ? 'dot-green' : 'dot-yellow'}`}></span>
          </div>

          {/* OpenAI Model Indicator */}
          <div className="model-indicator-pill" title="Powered by OpenAI's most cost-effective and reliable model">
            <Zap className="pill-icon text-cyan" />
            <span className="pill-label">Engine:</span>
            <span className="pill-value">gpt-4o-mini</span>
            <span className="pill-sub">($0.001/run)</span>
          </div>

          {/* Saved Projects History Button */}
          <button
            onClick={onOpenHistoryModal}
            className="history-nav-btn"
            title="Browse saved storyboards in backend database"
          >
            <FolderGit2 className="btn-icon-sm" />
            <span>Saved Projects</span>
          </button>

          {/* API Key Status Button */}
          <button
            onClick={onOpenApiKeyModal}
            className={`api-key-btn ${hasApiKey ? 'key-active' : 'key-demo'}`}
            title="Configure OpenAI API Key"
          >
            <Key className="btn-icon-sm" />
            <span>{hasApiKey ? 'API Key Active' : 'Director Demo'}</span>
            <span className="status-dot"></span>
          </button>

          {/* Quick Help / Guide */}
          <button
            onClick={onOpenHelpModal}
            className="icon-btn-ghost"
            title="How it works & Model Prompting Guide"
          >
            <HelpCircle className="btn-icon" />
          </button>
        </div>
      </div>
    </header>
  );
}
