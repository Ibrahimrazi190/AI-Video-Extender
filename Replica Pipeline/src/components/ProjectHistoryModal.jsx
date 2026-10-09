import React, { useState, useEffect } from 'react';
import { FolderGit2, X, Clock, Film, Trash2, ArrowRight, Video, Sparkles } from 'lucide-react';
import { fetchProjectsList, fetchProjectDetails, deleteProject } from '../services/api';

export function ProjectHistoryModal({ isOpen, onClose, onLoadProject }) {
  const [projects, setProjects] = useState([]);
  const [loading, setLoading] = useState(false);
  const [selectedId, setSelectedId] = useState(null);

  useEffect(() => {
    if (isOpen) {
      loadList();
    }
  }, [isOpen]);

  const loadList = async () => {
    setLoading(true);
    const list = await fetchProjectsList();
    setProjects(list);
    setLoading(false);
  };

  const handleSelect = async (id) => {
    setSelectedId(id);
    const project = await fetchProjectDetails(id);
    if (project) {
      onLoadProject(project);
      onClose();
    }
  };

  const handleDelete = async (e, id) => {
    e.stopPropagation();
    if (confirm('Delete this saved storyboard?')) {
      await deleteProject(id);
      setProjects(prev => prev.filter(p => p.id !== id));
    }
  };

  if (!isOpen) return null;

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal-dialog modal-lg" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <div className="modal-title-group">
            <FolderGit2 className="icon-cyan" />
            <h3>Saved Storyboard History (Backend Database)</h3>
          </div>
          <button className="modal-close-btn" onClick={onClose}>
            <X className="icon-sm" />
          </button>
        </div>

        <div className="modal-body modal-scrollable">
          {loading ? (
            <div className="history-empty-state">
              <span className="spin-icon">⏳</span> Loading saved projects from backend...
            </div>
          ) : projects.length === 0 ? (
            <div className="history-empty-state">
              <Film className="icon-lg text-dim" />
              <h4>No Saved Storyboards Yet</h4>
              <p>Every time you generate a storyboard, the backend automatically persists it here.</p>
            </div>
          ) : (
            <div className="history-projects-grid">
              {projects.map((p) => (
                <div
                  key={p.id}
                  className={`history-project-card ${selectedId === p.id ? 'active' : ''}`}
                  onClick={() => handleSelect(p.id)}
                >
                  <div className="history-card-top">
                    <span className="history-time-tag">
                      <Clock className="icon-sm" />
                      {new Date(p.createdAt || Date.now()).toLocaleDateString()}
                    </span>
                    <button
                      className="history-delete-btn"
                      onClick={(e) => handleDelete(e, p.id)}
                      title="Delete saved project"
                    >
                      <Trash2 className="icon-sm" />
                    </button>
                  </div>

                  <h4 className="history-title">{p.projectTitle || 'Untitled Storyboard'}</h4>
                  <p className="history-synopsis">{p.synopsis}...</p>

                  <div className="history-meta-row">
                    <span className="history-badge">
                      <Film className="icon-sm" /> {p.sceneCount} Scenes
                    </span>
                    <span className="history-badge">
                      <Clock className="icon-sm" /> {p.totalDuration}s Total
                    </span>
                    <span className="history-badge text-cyan">
                      <Video className="icon-sm" /> {p.targetModel}
                    </span>
                  </div>

                  <div className="history-card-footer">
                    <span className="load-action-text">
                      Load Storyboard <ArrowRight className="icon-sm" />
                    </span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        <div className="modal-footer">
          <span className="footer-note-text">
            Stored persistently in <code>server/data/projects.json</code>
          </span>
          <button type="button" className="btn-secondary" onClick={onClose}>
            Close
          </button>
        </div>
      </div>
    </div>
  );
}
