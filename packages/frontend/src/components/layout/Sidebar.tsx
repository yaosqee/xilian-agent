import React, { useCallback } from 'react';
import { useAppStore, type PanelType } from '../../stores/appStore';

interface NavItem {
  key: PanelType;
  label: string;
}

const items: NavItem[] = [
  { key: null, label: '对话' },
  { key: 'emotion', label: '情绪' },
  { key: 'memory', label: '记忆' },
  { key: 'notebook', label: '笔记' },
  { key: 'audit', label: '审计' },
  { key: 'settings', label: '设置' },
];

export const Sidebar: React.FC = React.memo(() => {
  const activePanel = useAppStore((s) => s.activePanel);
  const expanded = useAppStore((s) => s.sidebarExpanded);
  const locked = useAppStore((s) => s.sidebarLocked);
  const setActivePanel = useAppStore((s) => s.setActivePanel);
  const setExpanded = useAppStore((s) => s.setSidebarExpanded);
  const setLocked = useAppStore((s) => s.setSidebarLocked);

  const handleClick = useCallback((key: PanelType) => {
    setActivePanel(key === activePanel ? null : key);
    setLocked(true);
  }, [activePanel, setActivePanel, setLocked]);

  const handleMouseEnter = useCallback(() => {
    if (!locked) setExpanded(true);
  }, [locked, setExpanded]);

  const handleMouseLeave = useCallback(() => {
    if (!locked) setExpanded(false);
  }, [locked, setExpanded]);

  const width = expanded || locked ? 120 : 44;

  return (
    <div
      className="sidebar"
      style={{ width }}
      onMouseEnter={handleMouseEnter}
      onMouseLeave={handleMouseLeave}
    >
      {items.map(({ key, label }) => {
        const isActive = activePanel === key || (key === null && activePanel === null);
        return (
          <button
            key={label}
            className={`sidebar-item ${isActive ? 'sidebar-item--active' : ''}`}
            onClick={() => handleClick(key)}
            title={label}
          >
            <span className="sidebar-dot" />
            {(expanded || locked) && <span>{label}</span>}
          </button>
        );
      })}
    </div>
  );
});
