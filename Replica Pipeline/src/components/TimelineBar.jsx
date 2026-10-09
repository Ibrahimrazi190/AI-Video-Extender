import React from 'react';
import { Film, Play, Clock, Sparkles } from 'lucide-react';

export function TimelineBar({
  scenes,
  totalDuration,
  activeSceneIndex,
  onSelectScene
}) {
  if (!scenes || scenes.length === 0) return null;

  return (
    <div className="timeline-container">
      <div className="timeline-header">
        <div className="timeline-title-group">
          <Film className="icon-cyan" />
          <h3>Interactive Storyboard Timeline</h3>
          <span className="timeline-meta-badge">
            {scenes.length} Clips • Total: {totalDuration}s
          </span>
        </div>
        <div className="timeline-legend">
          <span className="legend-item"><span className="legend-dot active"></span> Selected Clip</span>
          <span className="legend-item"><span className="legend-dot ready"></span> Ready for AI</span>
        </div>
      </div>

      {/* Visual Timeline Track */}
      <div className="timeline-track-wrapper">
        <div className="timeline-segments-track">
          {scenes.map((scene, idx) => {
            const widthPercent = (scene.durationSec / totalDuration) * 100;
            const isActive = activeSceneIndex === idx;

            return (
              <div
                key={scene.sceneNumber || idx}
                className={`timeline-clip-segment ${isActive ? 'active' : ''}`}
                style={{ width: `${widthPercent}%` }}
                onClick={() => onSelectScene(idx)}
                title={`Scene ${idx + 1}: ${scene.timecode} (${scene.durationSec}s)\n${scene.shotType}`}
              >
                <div className="segment-number">#{String(idx + 1).padStart(2, '0')}</div>
                <div className="segment-time">{scene.timecode}</div>
                <div className="segment-bar-fill"></div>
              </div>
            );
          })}
        </div>

        {/* Timeline Timecode Markers */}
        <div className="timeline-time-ruler">
          <span>00:00</span>
          <span>{Math.floor(totalDuration / 2 / 60)}:{String(Math.floor((totalDuration / 2) % 60)).padStart(2, '0')}</span>
          <span>{Math.floor(totalDuration / 60)}:{String(totalDuration % 60).padStart(2, '0')}</span>
        </div>
      </div>
    </div>
  );
}
