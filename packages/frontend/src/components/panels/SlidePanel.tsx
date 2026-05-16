/* FILE: src/components/panels/SlidePanel.tsx */
import React, { Component, useEffect, useState } from 'react';
import { useAppStore } from '../../stores/appStore';

class SafePanel extends Component<{ children: React.ReactNode }, { error: boolean }> {
  constructor(props: { children: React.ReactNode }) {
    super(props);
    this.state = { error: false };
  }
  static getDerivedStateFromError() { return { error: true }; }
  render() {
    if (this.state.error) {
      return (
        <div style={{ color: 'var(--color-text-dim)', textAlign: 'center', padding: 24, fontSize: 13 }}>
          面板加载失败，请关闭后重试
        </div>
      );
    }
    return this.props.children;
  }
}
import { EmotionPanel } from './EmotionPanel';
import { MemoryTimeline } from './MemoryTimeline';
import { AutobiographyPanel } from './AutobiographyPanel';
import { NotebookPanel } from './NotebookPanel';
import { AuditPanel } from './AuditPanel';
import { SettingsPanel } from './SettingsPanel';

const PANELS: Record<string, React.FC> = {
  emotion:        EmotionPanel,
  memory:         MemoryTimeline,
  autobiography:  AutobiographyPanel,
  notebook:       NotebookPanel,
  audit:          AuditPanel,
  settings:       SettingsPanel,
};

const TITLES: Record<string, string> = {
  emotion:        '情绪雷达',
  memory:         '记忆时间线',
  autobiography:  '自传体',
  notebook:       '笔记本',
  audit:          '审计日志',
  settings:       '设置',
};

export const SlidePanel: React.FC = () => {
  const activePanel = useAppStore((s) => s.activePanel);
  const setActivePanel = useAppStore((s) => s.setActivePanel);

  const [visible, setVisible] = useState(false);
  const [current, setCurrent] = useState<string | null>(null);

  useEffect(() => {
    if (activePanel) {
      // 面板切换进来
      setCurrent(activePanel);
      // 下一帧触发动画
      const raf = requestAnimationFrame(() => setVisible(true));
      return () => cancelAnimationFrame(raf);
    } else if (current) {
      // 面板关闭 · 先滑出，再卸载内容
      setVisible(false);
      const t = setTimeout(() => setCurrent(null), 400);
      return () => clearTimeout(t);
    }
  }, [activePanel, current]);

  if (!current) return null;

  const PanelComponent = PANELS[current];
  if (!PanelComponent) return null;

  return (
    <aside
      className="glass-card-strong"
      style={{
        position: 'absolute',
        top: 0,
        right: 0,
        zIndex: 15,
        width: 'var(--panel-width)',
        minWidth: 'var(--panel-width)',
        height: '100vh',
        transform: visible ? 'translateX(0)' : 'translateX(100%)',
        opacity: visible ? 1 : 0,
        transition: `all var(--duration-normal) var(--ease-spring)`,
        display: 'flex',
        flexDirection: 'column',
        borderRadius: 'var(--radius-modal) 0 0 var(--radius-modal)',
        border: '1px solid var(--glass-border)',
        borderRight: 'none',
        boxShadow: 'var(--shadow-xl)',
        overflow: 'hidden',
      }}
    >
      {/* 面板头部 */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: '16px 20px',
          borderBottom: '1px solid rgba(200, 160, 190, 0.15)',
          flexShrink: 0,
        }}
      >
        <h2 style={{ fontSize: 15, fontWeight: 600, color: 'var(--color-text)', margin: 0 }}>
          {TITLES[current] ?? current}
        </h2>

        <button
          onClick={() => setActivePanel(null)}
          aria-label="关闭面板"
          style={{
            width: 32,
            height: 32,
            borderRadius: '50%',
            border: '1px solid rgba(200, 160, 190, 0.25)',
            background: 'var(--glass-bg)',
            color: 'var(--color-text-dim)',
            fontSize: 16,
            cursor: 'pointer',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            transition: `all var(--duration-fast) var(--ease-spring)`,
          }}
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none"
            stroke="currentColor" strokeWidth="2" strokeLinecap="round">
            <line x1="18" y1="6" x2="6" y2="18" />
            <line x1="6" y1="6" x2="18" y2="18" />
          </svg>
        </button>
      </div>

      {/* 面板内容 */}
      <div style={{ flex: 1, overflowY: 'auto', padding: 16 }}>
        <SafePanel>
          <PanelComponent />
        </SafePanel>
      </div>
    </aside>
  );
};
