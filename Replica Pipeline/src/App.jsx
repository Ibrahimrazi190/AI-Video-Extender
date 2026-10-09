import React, { useState, useEffect } from 'react';
import { Header } from './components/Header';
import { StoryConfigurator } from './components/StoryConfigurator';
import { ClipMasterPromptsView } from './components/ClipMasterPromptsView';
import { ApiKeyModal } from './components/ApiKeyModal';
import { HelpModal } from './components/HelpModal';
import { ProjectHistoryModal } from './components/ProjectHistoryModal';
import { checkBackendHealth, generateStoryboard } from './services/api';
import { STORY_TEMPLATES } from './constants/presets';
import { VIDEO_MODELS } from './constants/models';

export function App() {
  const defaultTemplate = STORY_TEMPLATES[0];

  // Default to 15s total duration and 5s clip size = 3 clips with continuity as requested!
  const [story, setStory] = useState(defaultTemplate.story);
  const [character, setCharacter] = useState(defaultTemplate.character);
  const [totalDuration, setTotalDuration] = useState(15);
  const [clipDuration, setClipDuration] = useState(5);
  const [selectedModel, setSelectedModel] = useState('seedance'); // Seedance (ByteDance)
  const [style, setStyle] = useState(defaultTemplate.style);
  const [aspectRatio, setAspectRatio] = useState('16:9');
  const [pacing, setPacing] = useState('Classical Narrative (Hook, Rising Tension, Climax, Resolution)');

  // Backend connection state
  const [backendConnected, setBackendConnected] = useState(false);

  // API Key State
  const [apiKey, setApiKey] = useState(() => {
    return localStorage.getItem('visioprompt_openai_key') || '';
  });

  // Generated Project State
  const [projectData, setProjectData] = useState(null);

  const [isGenerating, setIsGenerating] = useState(false);
  const [generationProgress, setGenerationProgress] = useState('');

  // Modals
  const [isApiKeyModalOpen, setIsApiKeyModalOpen] = useState(false);
  const [isHelpModalOpen, setIsHelpModalOpen] = useState(false);
  const [isHistoryModalOpen, setIsHistoryModalOpen] = useState(false);

  // Check backend health on mount and periodically
  useEffect(() => {
    let mounted = true;
    const testHealth = async () => {
      const status = await checkBackendHealth();
      if (mounted) {
        setBackendConnected(Boolean(status && status.status === 'online'));
      }
    };
    testHealth();
    const interval = setInterval(testHealth, 10000);
    return () => {
      mounted = false;
      clearInterval(interval);
    };
  }, []);

  // Save API key
  const handleSaveApiKey = (newKey) => {
    setApiKey(newKey);
    if (newKey) {
      localStorage.setItem('visioprompt_openai_key', newKey);
    } else {
      localStorage.removeItem('visioprompt_openai_key');
    }
  };

  // Generate sequential clip master prompts
  const handleGenerate = async () => {
    if (!story.trim()) return;

    setIsGenerating(true);
    setGenerationProgress(`Planning the story, then writing ${Math.ceil(totalDuration / clipDuration)} scripted clips with dialogue (can take 1-3 min)...`);

    try {
      const result = await generateStoryboard({
        apiKey,
        story,
        character,
        totalDuration,
        clipDuration,
        modelId: selectedModel,
        style,
        aspectRatio,
        pacing
      });

      setProjectData(result);

      // Smooth scroll to results
      setTimeout(() => {
        const resultSection = document.querySelector('.clip-master-section');
        if (resultSection) {
          resultSection.scrollIntoView({ behavior: 'smooth', block: 'start' });
        }
      }, 100);
    } catch (err) {
      console.error('Generation error:', err);
      alert(`Generation Error: ${err.message}`);
    } finally {
      setIsGenerating(false);
      setGenerationProgress('');
    }
  };

  // Update a single clip's prompt text
  const handleUpdateClipPrompt = (clipIndex, newText) => {
    if (!projectData || !projectData.clips) return;
    const updatedClips = [...projectData.clips];
    updatedClips[clipIndex] = {
      ...updatedClips[clipIndex],
      masterPrompt: newText
    };
    setProjectData({
      ...projectData,
      clips: updatedClips
    });
  };

  // Load project from history
  const handleLoadProjectFromHistory = (savedProject) => {
    if (!savedProject) return;
    setProjectData(savedProject);
    setStory(savedProject.projectTitle || savedProject.summary || '');
    if (savedProject.totalDuration) setTotalDuration(savedProject.totalDuration);
    if (savedProject.clipDuration) setClipDuration(savedProject.clipDuration);
    if (savedProject.targetModel) setSelectedModel(savedProject.targetModel);
    if (savedProject.aspectRatio) setAspectRatio(savedProject.aspectRatio);
  };

  const activeModelInfo = VIDEO_MODELS.find(m => m.id === selectedModel) || VIDEO_MODELS[0];

  return (
    <div className="app-container">
      {/* Top Header */}
      <Header
        hasApiKey={Boolean(apiKey)}
        backendConnected={backendConnected}
        onOpenApiKeyModal={() => setIsApiKeyModalOpen(true)}
        onOpenHelpModal={() => setIsHelpModalOpen(true)}
        onOpenHistoryModal={() => setIsHistoryModalOpen(true)}
        sceneCount={projectData?.clips?.length || Math.ceil(totalDuration / clipDuration)}
        modelName={activeModelInfo.name}
      />

      <main className="main-content">
        {/* Story, Duration, Clip & Model Configurator */}
        <StoryConfigurator
          story={story}
          setStory={setStory}
          character={character}
          setCharacter={setCharacter}
          totalDuration={totalDuration}
          setTotalDuration={setTotalDuration}
          clipDuration={clipDuration}
          setClipDuration={setClipDuration}
          selectedModel={selectedModel}
          setSelectedModel={setSelectedModel}
          style={style}
          setStyle={setStyle}
          aspectRatio={aspectRatio}
          setAspectRatio={setAspectRatio}
          pacing={pacing}
          setPacing={setPacing}
          onGenerate={handleGenerate}
          isGenerating={isGenerating}
          generationProgress={generationProgress}
        />

        {/* SEQUENTIAL CLIP MASTER PROMPTS SHOWCASE */}
        {projectData && (
          <ClipMasterPromptsView
            projectData={projectData}
            onUpdateClipPrompt={handleUpdateClipPrompt}
          />
        )}
      </main>

      {/* Footer */}
      <footer className="site-footer">
        <div className="footer-content">
          <div>
            <span className="footer-brand">VisioPrompt AI</span> • Multi-Clip Master Prompt Studio (Continuous Physical & Camera Momentum)
          </div>
          <div>
            Target Model: <strong>{activeModelInfo.name}</strong> • Engine: <strong>OpenAI gpt-4o-mini</strong> ($0.15/1M tokens)
          </div>
        </div>
      </footer>

      {/* API Key Modal */}
      <ApiKeyModal
        isOpen={isApiKeyModalOpen}
        onClose={() => setIsApiKeyModalOpen(false)}
        apiKey={apiKey}
        onSaveApiKey={handleSaveApiKey}
      />

      {/* Guide & Help Modal */}
      <HelpModal
        isOpen={isHelpModalOpen}
        onClose={() => setIsHelpModalOpen(false)}
      />

      {/* Saved Projects History Modal */}
      <ProjectHistoryModal
        isOpen={isHistoryModalOpen}
        onClose={() => setIsHistoryModalOpen(false)}
        onLoadProject={handleLoadProjectFromHistory}
      />
    </div>
  );
}

export default App;
