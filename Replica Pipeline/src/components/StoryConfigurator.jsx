import React, { useState } from 'react';
import {
  Sparkles,
  Sliders,
  Clock,
  Scissors,
  Video,
  Palette,
  Ratio,
  User,
  Wand2,
  RefreshCw,
  Compass,
  Check,
  ChevronDown,
  Info
} from 'lucide-react';
import { VIDEO_MODELS, CLIP_DURATIONS, TOTAL_DURATIONS, ASPECT_RATIOS, CINEMATIC_STYLES, PACING_OPTIONS } from '../constants/models';
import { STORY_TEMPLATES } from '../constants/presets';

export function StoryConfigurator({
  story,
  setStory,
  character,
  setCharacter,
  totalDuration,
  setTotalDuration,
  clipDuration,
  setClipDuration,
  selectedModel,
  setSelectedModel,
  style,
  setStyle,
  aspectRatio,
  setAspectRatio,
  pacing,
  setPacing,
  onGenerate,
  isGenerating,
  generationProgress
}) {
  const [showAdvanced, setShowAdvanced] = useState(false);

  // Calculate scenes dynamically
  const sceneCount = Math.ceil(totalDuration / clipDuration);
  const activeModel = VIDEO_MODELS.find(m => m.id === selectedModel) || VIDEO_MODELS[0];

  const handleApplyTemplate = (template) => {
    setStory(template.story);
    setCharacter(template.character);
    setTotalDuration(template.duration);
    setClipDuration(template.clipSize);
    setSelectedModel(template.model);
    setStyle(template.style);
    setAspectRatio(template.aspectRatio);
  };

  const handleCustomDurationChange = (e) => {
    const val = parseInt(e.target.value, 10);
    if (!isNaN(val) && val >= 5 && val <= 600) {
      setTotalDuration(val);
    }
  };

  return (
    <section className="configurator-card">
      {/* Section Header */}
      <div className="card-header-bar">
        <div className="card-header-title">
          <Sliders className="icon-cyan" />
          <h2>Director's Production Studio</h2>
        </div>
        <div className="template-pills-row">
          <span className="template-label">
            <Compass className="icon-sm" /> Premise Presets:
          </span>
          <div className="template-chips">
            {STORY_TEMPLATES.map(tpl => (
              <button
                key={tpl.id}
                type="button"
                className="template-chip-btn"
                onClick={() => handleApplyTemplate(tpl)}
                title={`Load: ${tpl.title} (${tpl.genre})`}
              >
                {tpl.title}
              </button>
            ))}
          </div>
        </div>
      </div>

      <div className="configurator-grid">
        {/* Left Column: Story & Narrative Anchors */}
        <div className="grid-col narrative-col">
          {/* Story Premise Textarea */}
          <div className="form-group">
            <div className="label-row">
              <label htmlFor="story-input" className="form-label">
                Initial Story Premise & Scene Concept <span className="req-star">*</span>
              </label>
              <span className="char-counter">{story.length} chars</span>
            </div>
            <div className="textarea-container">
              <textarea
                id="story-input"
                className="story-textarea"
                rows={5}
                placeholder="Describe your story idea, mood, key actions, visual world, and cinematic moments... (e.g. A cybernetic detective in rain-soaked Neo-Tokyo pursuing a rogue android across neon rooftops during a lightning storm)"
                value={story}
                onChange={(e) => setStory(e.target.value)}
              />
            </div>
          </div>

          {/* Character Consistency Anchor */}
          <div className="form-group">
            <div className="label-row">
              <label htmlFor="character-input" className="form-label flex-label">
                <User className="icon-sm text-cyan" />
                Protagonist & Continuity Lock <span className="opt-tag">(Optional)</span>
              </label>
              <span className="help-hint">Ensures face, clothes, and colors stay identical across all scenes</span>
            </div>
            <input
              id="character-input"
              type="text"
              className="text-input"
              placeholder="e.g., Maya: 26yo female cyborg, neon blue hair streak, weathered black duster coat, chrome cyber-arm"
              value={character}
              onChange={(e) => setCharacter(e.target.value)}
            />
          </div>

          {/* Target AI Video Generation Model Selector */}
          <div className="form-group">
            <div className="label-row">
              <label className="form-label flex-label">
                <Video className="icon-sm text-cyan" />
                Target AI Video Generation Model <span className="req-star">*</span>
              </label>
              <span className="help-hint">Formats prompt syntax specifically for this model</span>
            </div>
            <div className="model-cards-grid">
              {VIDEO_MODELS.map(model => {
                const isSelected = selectedModel === model.id;
                return (
                  <div
                    key={model.id}
                    className={`model-card ${isSelected ? 'selected' : ''}`}
                    onClick={() => setSelectedModel(model.id)}
                    style={{
                      '--model-color': model.color,
                      '--model-glow': model.borderGlow
                    }}
                  >
                    <div className="model-card-header">
                      <div className="model-title-block">
                        <span className="model-name">{model.name}</span>
                        <span className="model-badge">{model.badge}</span>
                      </div>
                      {isSelected && (
                        <div className="model-check-badge">
                          <Check className="check-icon" />
                        </div>
                      )}
                    </div>
                    <p className="model-tagline">{model.tagline}</p>
                    <div className="model-format-spec">
                      <span className="format-label">Syntax:</span> {model.promptFormat.slice(0, 65)}...
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        </div>

        {/* Right Column: Timing, Math Calculation & Aesthetics */}
        <div className="grid-col settings-col">
          {/* Dynamic Scene Calculation Highlight Card */}
          <div className="math-highlight-card">
            <div className="math-header">
              <span className="math-badge">Live Director Calculation</span>
              <span className="math-model-tag">Target: {activeModel.name}</span>
            </div>
            <div className="math-equation-row">
              <div className="math-pill">
                <span className="math-label">Total Duration</span>
                <span className="math-number">{totalDuration}s</span>
                <span className="math-unit">({(totalDuration / 60).toFixed(1)}m)</span>
              </div>
              <div className="math-operator">÷</div>
              <div className="math-pill">
                <span className="math-label">Segment Clip</span>
                <span className="math-number">{clipDuration}s</span>
                <span className="math-unit">per cut</span>
              </div>
              <div className="math-operator">=</div>
              <div className="math-pill highlight-pill">
                <span className="math-label">Generated Scenes</span>
                <span className="math-number glow-number">{sceneCount}</span>
                <span className="math-unit">Cinematic Cuts</span>
              </div>
            </div>
            <div className="math-footer-note">
              <span>⚡ Cost via gpt-4o-mini: <strong>~${(sceneCount * 0.00015).toFixed(4)} USD</strong></span>
              <span>• Complete Camera & Script Breakdown</span>
            </div>
          </div>

          {/* Total Duration Selector */}
          <div className="form-group">
            <div className="label-row">
              <label className="form-label flex-label">
                <Clock className="icon-sm text-cyan" />
                Total Story Duration
              </label>
              <span className="active-val-badge">{totalDuration}s ({Math.floor(totalDuration / 60)}m {totalDuration % 60}s)</span>
            </div>
            <div className="preset-buttons-row">
              {TOTAL_DURATIONS.map(dur => (
                <button
                  key={dur.value}
                  type="button"
                  className={`preset-btn ${totalDuration === dur.value ? 'active' : ''}`}
                  onClick={() => setTotalDuration(dur.value)}
                >
                  <span className="preset-val">{dur.value}s</span>
                  <span className="preset-badge">{dur.badge}</span>
                </button>
              ))}
            </div>
            {/* Custom Duration Slider */}
            <div className="custom-duration-slider-row">
              <span className="slider-label">Custom:</span>
              <input
                type="range"
                min="10"
                max="180"
                step="5"
                value={totalDuration}
                onChange={(e) => setTotalDuration(Number(e.target.value))}
                className="duration-range-slider"
              />
              <input
                type="number"
                min="5"
                max="600"
                value={totalDuration}
                onChange={handleCustomDurationChange}
                className="slider-num-input"
              />
              <span className="sec-label">seconds</span>
            </div>
          </div>

          {/* Segment Clip Duration (5, 8, 10, 15) */}
          <div className="form-group">
            <div className="label-row">
              <label className="form-label flex-label">
                <Scissors className="icon-sm text-cyan" />
                Clip Segment Size (Cut Length) <span className="req-star">*</span>
              </label>
              <span className="help-hint">Determines video generation cut duration</span>
            </div>
            <div className="clip-buttons-grid">
              {CLIP_DURATIONS.map(clip => (
                <button
                  key={clip.value}
                  type="button"
                  className={`clip-select-card ${clipDuration === clip.value ? 'active' : ''}`}
                  onClick={() => setClipDuration(clip.value)}
                >
                  <div className="clip-sec-number">{clip.value}s</div>
                  <div className="clip-card-details">
                    <span className="clip-label">{clip.label}</span>
                    <span className="clip-desc">{clip.description}</span>
                  </div>
                </button>
              ))}
            </div>
          </div>

          {/* Aspect Ratio & Cinematic Style */}
          <div className="style-aspect-row">
            {/* Aspect Ratio */}
            <div className="form-group flex-1">
              <label className="form-label flex-label">
                <Ratio className="icon-sm text-cyan" />
                Aspect Ratio
              </label>
              <div className="aspect-ratio-selector">
                {ASPECT_RATIOS.map(ar => (
                  <button
                    key={ar.id}
                    type="button"
                    className={`aspect-btn ${aspectRatio === ar.id ? 'active' : ''}`}
                    onClick={() => setAspectRatio(ar.id)}
                    title={ar.desc}
                  >
                    <span className="aspect-icon-box" data-ratio={ar.id}></span>
                    <span className="aspect-text">{ar.id}</span>
                  </button>
                ))}
              </div>
            </div>

            {/* Cinematic Style */}
            <div className="form-group flex-2">
              <label className="form-label flex-label">
                <Palette className="icon-sm text-cyan" />
                Cinematic Visual Aesthetic
              </label>
              <select
                className="select-input"
                value={style}
                onChange={(e) => setStyle(e.target.value)}
              >
                {CINEMATIC_STYLES.map((st, i) => (
                  <option key={i} value={st}>{st}</option>
                ))}
              </select>
            </div>
          </div>

          {/* Advanced Pacing Collapsible */}
          <div className="advanced-toggle-bar">
            <button
              type="button"
              className="advanced-toggle-btn"
              onClick={() => setShowAdvanced(!showAdvanced)}
            >
              <span>Narrative Pacing & Dynamics</span>
              <ChevronDown className={`icon-sm chevron ${showAdvanced ? 'open' : ''}`} />
            </button>
          </div>

          {showAdvanced && (
            <div className="advanced-options-drawer">
              <div className="form-group">
                <label className="form-label">Narrative Arc Rhythm:</label>
                <select
                  className="select-input"
                  value={pacing}
                  onChange={(e) => setPacing(e.target.value)}
                >
                  {PACING_OPTIONS.map((p, idx) => (
                    <option key={idx} value={p}>{p}</option>
                  ))}
                </select>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Primary Action Button */}
      <div className="configurator-action-bar">
        <div className="action-info">
          <Sparkles className="icon-cyan" />
          <span>
            Ready to generate <strong>{sceneCount} detailed scene prompts</strong> tailored for <strong>{activeModel.name}</strong>
          </span>
        </div>

        <button
          type="button"
          className="generate-primary-btn"
          onClick={onGenerate}
          disabled={isGenerating || !story.trim()}
        >
          {isGenerating ? (
            <>
              <RefreshCw className="spin-icon" />
              <span>Generating {sceneCount} Scenes with gpt-4o-mini...</span>
            </>
          ) : (
            <>
              <Wand2 className="btn-icon" />
              <span>Direct & Generate {sceneCount} Cinematic Scenes</span>
            </>
          )}
          <span className="btn-shine"></span>
        </button>
      </div>

      {/* Progress Bar when Generating */}
      {isGenerating && (
        <div className="generation-progress-container">
          <div className="progress-status-row">
            <span>Directing scene angles, lighting, lens specs & model syntax...</span>
            <span>{generationProgress || 'Crafting screenplay prompts'}</span>
          </div>
          <div className="progress-track">
            <div className="progress-bar-fill animated-glow"></div>
          </div>
        </div>
      )}
    </section>
  );
}
