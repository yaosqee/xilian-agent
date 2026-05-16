import React from 'react';
import { Sidebar } from './Sidebar';
import { ChatView } from '../chat/ChatView';
import { useAppStore } from '../../stores/appStore';
import { EmotionPanel } from '../panels/EmotionPanel';
import { MemoryPanel } from '../panels/MemoryPanel';
import { NotebookPanel } from '../panels/NotebookPanel';
import { AuditPanel } from '../panels/AuditPanel';
import { SkillsPanel } from '../panels/SkillsPanel';
import { SettingsPanel } from '../panels/SettingsPanel';

const panels: Record<string, React.FC> = {
  emotion: EmotionPanel,
  memory: MemoryPanel,
  notebook: NotebookPanel,
  audit: AuditPanel,
  skills: SkillsPanel,
  settings: SettingsPanel,
};

const Atmosphere: React.FC = () => (
  <div className="atmosphere">
    <div className="atmosphere-orb atmosphere-orb--pink" />
    <div className="atmosphere-orb atmosphere-orb--purple" />
    <div className="atmosphere-orb atmosphere-orb--blue" />
  </div>
);

export const MainLayout: React.FC = () => {
  const activePanel = useAppStore((s) => s.activePanel);
  const setActivePanel = useAppStore((s) => s.setActivePanel);

  const PanelComponent = activePanel ? panels[activePanel] : null;

  return (
    <>
      <Atmosphere />
      <div className="app-shell">
        <Sidebar />
        <div className="main-area">
          {PanelComponent ? (
            <>
              <button className="panel-back-btn" onClick={() => setActivePanel(null)}>
                ← 返回对话
              </button>
              <div style={{ flex: 1, overflow: 'hidden' }}>
                <PanelComponent />
              </div>
            </>
          ) : (
            <ChatView />
          )}
        </div>
      </div>
    </>
  );
};
