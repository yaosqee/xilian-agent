/* FILE: src/components/layout/Sidebar.tsx */
import React, { useCallback } from 'react';
import { useAppStore, type PanelType } from '../../stores/appStore';

interface NavItem {
  key: PanelType;
  label: string;
  icon: React.ReactNode;
}

const ChatIcon = () => (
  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor"
    strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
    <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2v10z" />
  </svg>
);

const HeartIcon = () => (
  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor"
    strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
    <path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z" />
  </svg>
);

const ClockIcon = () => (
  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor"
    strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
    <circle cx="12" cy="12" r="10" />
    <polyline points="12 6 12 12 16 14" />
  </svg>
);

const PenIcon = () => (
  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor"
    strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
    <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7" />
    <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z" />
  </svg>
);

const ShieldIcon = () => (
  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor"
    strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
    <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
  </svg>
);

const BookIcon = () => (
  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor"
    strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
    <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20" />
    <path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z" />
  </svg>
);

const CodeIcon = () => (
  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor"
    strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
    <polyline points="16 18 22 12 16 6" />
    <polyline points="8 6 2 12 8 18" />
  </svg>
);

const GearIcon = () => (
  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor"
    strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
    <circle cx="12" cy="12" r="3" />
    <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
  </svg>
);

const SparkleIcon = () => (
  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor"
    strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
    <polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2" />
  </svg>
);

const ITEMS: NavItem[] = [
  { key: null,            label: '对话',   icon: <ChatIcon /> },
  { key: 'portrait',      label: '印象',   icon: <SparkleIcon /> },
  { key: 'emotion',       label: '情绪',   icon: <HeartIcon /> },
  { key: 'memory',        label: '记忆',   icon: <ClockIcon /> },
  { key: 'autobiography', label: '自传',   icon: <BookIcon /> },
  { key: 'notebook',      label: '笔记',   icon: <PenIcon /> },
  { key: 'audit',         label: '审计',   icon: <ShieldIcon /> },
  { key: 'skills',        label: '技能',   icon: <CodeIcon /> },
  { key: 'settings',      label: '设置',   icon: <GearIcon /> },
];

export const Sidebar: React.FC = React.memo(() => {
  const activePanel = useAppStore((s) => s.activePanel);
  const expanded = useAppStore((s) => s.sidebarExpanded);
  const locked = useAppStore((s) => s.sidebarLocked);
  const setActivePanel = useAppStore((s) => s.setActivePanel);
  const setExpanded = useAppStore((s) => s.setSidebarExpanded);
  const setLocked = useAppStore((s) => s.setSidebarLocked);

  const handleClick = useCallback((key: PanelType) => {
    if (key === null) {
      setActivePanel(null);
    } else {
      setActivePanel(activePanel === key ? null : key);
    }
    setLocked(true);
  }, [activePanel, setActivePanel, setLocked]);

  const handleMouseEnter = useCallback(() => {
    if (!locked) setExpanded(true);
  }, [locked, setExpanded]);

  const handleMouseLeave = useCallback(() => {
    if (!locked) setExpanded(false);
  }, [locked, setExpanded]);

  const isOpen = expanded || locked;
  const width = isOpen ? 'var(--sidebar-expanded)' : 'var(--sidebar-collapsed)';

  return (
    <nav
      className="glass-card-strong"
      onMouseEnter={handleMouseEnter}
      onMouseLeave={handleMouseLeave}
      style={{
        position: 'relative',
        zIndex: 20,
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        width,
        minWidth: width,
        height: '100vh',
        paddingTop: 18,
        paddingBottom: 18,
        gap: 2,
        transition: `width var(--duration-normal) var(--ease-spring)`,
        borderRadius: '0 var(--radius-card) var(--radius-card) 0',
        boxShadow: 'var(--shadow-md)',
        overflow: 'hidden',
        userSelect: 'none',
        WebkitUserSelect: 'none',
      }}
    >
      {/* 品牌标识 */}
      <div
        style={{
          width: '100%',
          display: 'flex',
          justifyContent: 'center',
          alignItems: 'center',
          padding: '8px 0 20px',
        }}
      >
        <span
          className="gradient-text"
          style={{
            fontSize: isOpen ? 20 : 14,
            fontWeight: 700,
            letterSpacing: 2,
            transition: `font-size var(--duration-normal) var(--ease-spring)`,
            fontFamily: 'var(--font-serif)',
          }}
        >
          {isOpen ? '昔涟' : '昔'}
        </span>
      </div>

      {/* 导航项 */}
      {ITEMS.map(({ key, label, icon }) => {
        const active = key === activePanel || (key === null && activePanel === null);
        return (
          <button
            key={label}
            onClick={() => handleClick(key)}
            title={label}
            style={{
              width: isOpen ? 'calc(100% - 10px)' : 36,
              height: 38,
              display: 'flex',
              alignItems: 'center',
              justifyContent: isOpen ? 'flex-start' : 'center',
              gap: 10,
              padding: isOpen ? '0 12px' : 0,
              marginBottom: 2,
              border: 'none',
              borderRadius: 'var(--radius-btn)',
              background: active
                ? 'rgba(255, 183, 197, 0.18)'
                : 'transparent',
              color: active ? 'var(--color-pink-dark)' : 'var(--color-text-muted)',
              fontSize: 13,
              fontWeight: active ? 600 : 400,
              cursor: 'pointer',
              transition: `all var(--duration-normal) var(--ease-spring)`,
              whiteSpace: 'nowrap',
              overflow: 'hidden',
              position: 'relative',
            }}
          >
            {/* 图标 */}
            <span
              style={{
                minWidth: 20,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                flexShrink: 0,
                opacity: active ? 1 : 0.65,
                transition: `opacity var(--duration-normal) var(--ease-spring)`,
              }}
            >
              {icon}
            </span>

            {/* 标签 · 展开时可见 */}
            <span
              style={{
                opacity: isOpen ? 1 : 0,
                transform: isOpen ? 'translateX(0)' : 'translateX(-8px)',
                transition: `all var(--duration-normal) var(--ease-spring)`,
                fontSize: 12,
                fontWeight: active ? 600 : 400,
              }}
            >
              {label}
            </span>

            {/* 活跃指示条 */}
            {active && (
              <span
                style={{
                  position: 'absolute',
                  left: 0,
                  top: '50%',
                  transform: 'translateY(-50%)',
                  width: 3,
                  height: 18,
                  borderRadius: '0 3px 3px 0',
                  background: 'linear-gradient(180deg, var(--color-pink), var(--color-purple))',
                }}
              />
            )}
          </button>
        );
      })}

      {/* 底部锁定指示 */}
      {isOpen && (
        <button
          onClick={() => setLocked(!locked)}
          title={locked ? '解锁侧栏' : '锁定侧栏'}
          style={{
            marginTop: 'auto',
            padding: '4px 10px',
            border: 'none',
            borderRadius: 'var(--radius-btn)',
            background: locked ? 'rgba(255, 183, 197, 0.2)' : 'transparent',
            color: locked ? 'var(--color-pink-dark)' : 'var(--color-text-muted)',
            fontSize: 11,
            cursor: 'pointer',
            transition: `all var(--duration-normal) var(--ease-spring)`,
          }}
        >
          {locked ? '🔒 已固定' : '🔓 悬浮'}
        </button>
      )}
    </nav>
  );
});
