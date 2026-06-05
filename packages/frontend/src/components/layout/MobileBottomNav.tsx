/* FILE: src/components/layout/MobileBottomNav.tsx */
import React, { useCallback } from 'react';
import { useAppStore, type PanelType } from '../../stores/appStore';

/* ── 精简图标（复用 Sidebar 同款 SVG）── */

const ChatIcon = () => (
  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor"
    strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
    <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2v10z" />
  </svg>
);

const HeartIcon = () => (
  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor"
    strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
    <path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z" />
  </svg>
);

const ClockIcon = () => (
  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor"
    strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
    <circle cx="12" cy="12" r="10" />
    <polyline points="12 6 12 12 16 14" />
  </svg>
);

const PenIcon = () => (
  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor"
    strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
    <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7" />
    <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z" />
  </svg>
);

const GearIcon = () => (
  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor"
    strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
    <circle cx="12" cy="12" r="3" />
    <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
  </svg>
);

/* ── 5 主标签 ── */

interface TabItem {
  key: PanelType;
  label: string;
  icon: React.ReactNode;
}

const TABS: TabItem[] = [
  { key: null,       label: '对话', icon: <ChatIcon /> },
  { key: 'emotion',  label: '情绪', icon: <HeartIcon /> },
  { key: 'memory',   label: '记忆', icon: <ClockIcon /> },
  { key: 'notebook', label: '笔记', icon: <PenIcon /> },
  { key: 'settings', label: '设置', icon: <GearIcon /> },
];

/* ══════════════════════════════════════════════
   移动端底部导航栏
   ══════════════════════════════════════════════ */
export const MobileBottomNav: React.FC = React.memo(() => {
  const activePanel = useAppStore((s) => s.activePanel);
  const setActivePanel = useAppStore((s) => s.setActivePanel);

  const handleClick = useCallback((key: PanelType) => {
    if (key === null) {
      setActivePanel(null);
    } else {
      setActivePanel(activePanel === key ? null : key);
    }
  }, [activePanel, setActivePanel]);

  return (
    <nav
      style={{
        position: 'fixed',
        bottom: 0,
        left: 0,
        right: 0,
        zIndex: 50,
        display: 'flex',
        justifyContent: 'space-around',
        alignItems: 'center',
        height: 'var(--bottom-nav-height)',
        paddingBottom: 'var(--safe-bottom)',
        background: 'rgba(255, 255, 255, 0.78)',
        backdropFilter: 'blur(20px)',
        WebkitBackdropFilter: 'blur(20px)',
        borderTop: '1px solid rgba(200, 175, 220, 0.18)',
        boxShadow: '0 -2px 20px rgba(180, 140, 220, 0.1)',
      }}
    >
      {TABS.map(({ key, label, icon }) => {
        const active = key === activePanel || (key === null && activePanel === null);
        return (
          <button
            key={label}
            onClick={() => handleClick(key)}
            aria-label={label}
            style={{
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              justifyContent: 'center',
              gap: 2,
              flex: 1,
              maxWidth: 80,
              padding: '4px 0',
              border: 'none',
              background: 'transparent',
              color: active ? 'var(--color-pink-dark)' : 'var(--color-text-muted)',
              cursor: 'pointer',
              transition: 'color var(--duration-fast) var(--ease-spring)',
              WebkitTapHighlightColor: 'transparent',
              position: 'relative',
            }}
          >
            {/* 活跃指示点 */}
            {active && (
              <span
                style={{
                  position: 'absolute',
                  top: 0,
                  left: '50%',
                  transform: 'translateX(-50%)',
                  width: 4,
                  height: 4,
                  borderRadius: '50%',
                  background: 'var(--color-pink)',
                }}
              />
            )}
            {icon}
            <span style={{
              fontSize: 10,
              fontWeight: active ? 600 : 400,
              lineHeight: 1.2,
              letterSpacing: '0.03em',
            }}>
              {label}
            </span>
          </button>
        );
      })}
    </nav>
  );
});
