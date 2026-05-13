import React from 'react';
import { useAppStore, type PanelType } from '../../stores/appStore';

const icons: { key: PanelType; emoji: string; label: string }[] = [
  { key: null, emoji: '💭', label: '对话' },
  { key: 'emotion', emoji: '📊', label: '情绪' },
  { key: 'memory', emoji: '📖', label: '记忆' },
  { key: 'settings', emoji: '⚙️', label: '设置' },
];

export const IconStrip: React.FC = React.memo(() => {
  const activePanel = useAppStore((s) => s.activePanel);
  const expanded = useAppStore((s) => s.iconExpanded);
  const setActivePanel = useAppStore((s) => s.setActivePanel);
  const setExpanded = useAppStore((s) => s.setIconExpanded);

  return (
    <div
      style={{
        width: expanded ? 120 : 40,
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        paddingTop: 20,
        gap: 8,
        transition: 'width 200ms ease',
        background: 'rgba(15, 15, 25, 0.85)',
        borderRight: '1px solid rgba(255,255,255,0.06)',
        overflow: 'hidden',
        flexShrink: 0,
      }}
      onMouseEnter={() => setExpanded(true)}
      onMouseLeave={() => setExpanded(false)}
    >
      {icons.map(({ key, emoji, label }) => {
        const isActive = activePanel === key || (key === null && activePanel === null);
        return (
          <button
            key={label}
            onClick={() => setActivePanel(key === null ? null : key)}
            title={label}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 10,
              width: '100%',
              padding: '8px 10px',
              border: 'none',
              background: isActive ? 'rgba(255,255,255,0.08)' : 'transparent',
              borderRadius: 8,
              cursor: 'pointer',
              color: isActive ? '#e0e0e0' : 'rgba(255,255,255,0.4)',
              fontSize: 20,
              transition: 'color 150ms, background 150ms',
              whiteSpace: 'nowrap',
            }}
          >
            <span style={{ fontSize: 22, flexShrink: 0 }}>{emoji}</span>
            {expanded && (
              <span style={{ fontSize: 13, fontWeight: 500 }}>{label}</span>
            )}
          </button>
        );
      })}
    </div>
  );
});
