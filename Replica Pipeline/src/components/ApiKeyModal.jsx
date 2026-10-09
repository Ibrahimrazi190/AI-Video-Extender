import React, { useState } from 'react';
import { Key, Eye, EyeOff, ShieldCheck, Check, AlertCircle, X, Sparkles, ExternalLink, Zap } from 'lucide-react';

export function ApiKeyModal({ isOpen, onClose, apiKey, onSaveApiKey }) {
  const [inputValue, setInputValue] = useState(apiKey || '');
  const [showKey, setShowKey] = useState(false);
  const [testing, setTesting] = useState(false);
  const [testStatus, setTestStatus] = useState(null); // { success: boolean, message: string }

  if (!isOpen) return null;

  const handleTestKey = async () => {
    if (!inputValue.trim()) {
      setTestStatus({ success: false, message: 'Please enter an OpenAI API key first.' });
      return;
    }

    setTesting(true);
    setTestStatus(null);

    try {
      const res = await fetch('https://api.openai.com/v1/models', {
        headers: {
          'Authorization': `Bearer ${inputValue.trim()}`
        }
      });

      if (res.ok) {
        setTestStatus({ success: true, message: 'API Key is valid and connected!' });
      } else {
        const data = await res.json().catch(() => ({}));
        setTestStatus({
          success: false,
          message: data.error?.message || `API error: HTTP ${res.status}`
        });
      }
    } catch (err) {
      setTestStatus({
        success: false,
        message: `Connection failed: ${err.message}`
      });
    } finally {
      setTesting(false);
    }
  };

  const handleSave = () => {
    onSaveApiKey(inputValue.trim());
    onClose();
  };

  const handleClear = () => {
    setInputValue('');
    onSaveApiKey('');
    setTestStatus(null);
  };

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal-dialog" onClick={(e) => e.stopPropagation()}>
        {/* Modal Header */}
        <div className="modal-header">
          <div className="modal-title-group">
            <Key className="icon-cyan" />
            <h3>OpenAI API Configuration</h3>
          </div>
          <button className="modal-close-btn" onClick={onClose}>
            <X className="icon-sm" />
          </button>
        </div>

        {/* Modal Body */}
        <div className="modal-body">
          <div className="model-banner-info">
            <div className="banner-icon-col">
              <Zap className="icon-gold" />
            </div>
            <div className="banner-text-col">
              <strong>Powered by OpenAI gpt-4o-mini</strong>
              <p>
                OpenAI's most reliable and cost-effective model ($0.15 / 1M prompt tokens).
                A full 12-scene cinematic breakdown costs only <strong>~$0.001 USD</strong>!
              </p>
            </div>
          </div>

          <div className="form-group">
            <label className="form-label" htmlFor="api-key-input">
              Your OpenAI API Key:
            </label>
            <div className="input-with-actions">
              <input
                id="api-key-input"
                type={showKey ? 'text' : 'password'}
                className="text-input font-mono"
                placeholder="sk-proj-..."
                value={inputValue}
                onChange={(e) => setInputValue(e.target.value)}
              />
              <button
                type="button"
                className="input-adornment-btn"
                onClick={() => setShowKey(!showKey)}
                title={showKey ? 'Hide key' : 'Show key'}
              >
                {showKey ? <EyeOff className="icon-sm" /> : <Eye className="icon-sm" />}
              </button>
            </div>
            <span className="input-hint">
              Keys are stored exclusively in your browser's local storage and sent directly to OpenAI.
            </span>
          </div>

          {/* Test Status Message */}
          {testStatus && (
            <div className={`status-callout ${testStatus.success ? 'callout-success' : 'callout-error'}`}>
              {testStatus.success ? <Check className="icon-sm" /> : <AlertCircle className="icon-sm" />}
              <span>{testStatus.message}</span>
            </div>
          )}

          {/* Security & Fallback Note */}
          <div className="security-note">
            <ShieldCheck className="icon-sm text-green" />
            <div>
              <strong>No API key? No problem!</strong>
              <p>
                The app comes with an intelligent built-in Director Engine that works immediately out of the box with realistic cinematic prompts.
              </p>
            </div>
          </div>
        </div>

        {/* Modal Footer */}
        <div className="modal-footer">
          <div className="footer-left">
            {apiKey && (
              <button type="button" className="btn-danger-ghost" onClick={handleClear}>
                Remove Key
              </button>
            )}
          </div>

          <div className="footer-right">
            <button
              type="button"
              className="btn-secondary"
              onClick={handleTestKey}
              disabled={testing || !inputValue}
            >
              {testing ? 'Testing...' : 'Test Connection'}
            </button>
            <button
              type="button"
              className="btn-primary"
              onClick={handleSave}
            >
              Save Configuration
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
