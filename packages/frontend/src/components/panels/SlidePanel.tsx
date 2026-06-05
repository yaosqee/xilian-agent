/* FILE: src/components/panels/SlidePanel.tsx */
import React, { Component, useEffect, useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
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
import { SkillsPanel } from './SkillsPanel';
import { SettingsPanel } from './SettingsPanel';
import { PortraitPanel } from './PortraitPanel';

const PANELS: Record<string, React.FC> = {
  emotion:        EmotionPanel,
  memory:         MemoryTimeline,
  autobiography:  AutobiographyPanel,
  notebook:       NotebookPanel,
  audit:          AuditPanel,
  skills:         SkillsPanel,
  settings:       SettingsPanel,
  portrait:       PortraitPanel,
};

const TITLES: Record<string, string> = {
  emotion:        '情绪雷达',
  memory:         '记忆时间线',
  autobiography:  '自传体',
  notebook:       '笔记本',
  audit:          '审计日志',
  skills:         '技能管理',
  settings:       '设置',
  portrait:       '伙伴印象',
};

export const SlidePanel: React.FC<{ isMobile?: boolean }> = ({ isMobile = false }) => {
  const activePanel = useAppStore((s) => s.activePanel);
  const setActivePanel = useAppStore((s) => s.setActivePanel);

  const [visible, setVisible] = useState(false);
  const [current, setCurrent] = useState<string | null>(null);

  useEffect(() => {
    if (activePanel) {
      setCurrent(activePanel);
      const raf = requestAnimationFrame(() => setVisible(true));
      return () => cancelAnimationFrame(raf);
    } else if (current) {
      setVisible(false);
      const t = setTimeout(() => setCurrent(null), 400);
      return () => clearTimeout(t);
    }
  }, [activePanel, current]);

  if (!current) return null;

  const PanelComponent = PANELS[current];
  if (!PanelComponent) return null;

  const title = TITLES[current] ?? current;

  /* ─── 移动端：全屏覆盖 + 底部滑入 ─── */
  if (isMobile) {
    return (
      <AnimatePresence>
        {visible && (
          <motion.aside
            className="glass-card-strong"
            initial={{ y: '100%' }}
            animate={{ y: 0 }}
            exit={{ y: '100%' }}
            transition={{ duration: 0.4, ease: [0.4, 0, 0.2, 1] }}
            style={{
              position: 'fixed',
              inset: 0,
              zIndex: 40,
              display: 'flex',
              flexDirection: 'column',
              borderRadius: 'var(--radius-modal) var(--radius-modal) 0 0',
              boxShadow: 'var(--shadow-xl)',
              overflow: 'hidden',
              paddingTop: 'var(--safe-top)',
            }}
          >
            {/* 顶部栏 */}
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
              <h2 style={{ fontSize: 16, fontWeight: 600, color: 'var(--color-text)', margin: 0 }}>
                {title}
              </h2>
              <button
                onClick={() => setActivePanel(null)}
                aria-label="关闭面板"
                style={{
                  width: 36,
                  height: 36,
                  borderRadius: '50%',
                  border: '1px solid rgba(200, 160, 190, 0.25)',
                  background: 'var(--glass-bg)',
                  color: 'var(--color-text-dim)',
                  fontSize: 16,
                  cursor: 'pointer',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                }}
              >
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none"
                  stroke="currentColor" strokeWidth="2" strokeLinecap="round">
                  <line x1="18" y1="6" x2="6" y2="18" />
                  <line x1="6" y1="6" x2="18" y2="18" />
                </svg>
              </button>
            </div>
            {/* 内容 */}
            <div style={{ flex: 1, overflowY: 'auto', padding: 16, paddingBottom: 'calc(var(--bottom-nav-height) + var(--safe-bottom) + 16px)' }}>
              <SafePanel>
                <PanelComponent />
              </SafePanel>
            </div>
          </motion.aside>
        )}
      </AnimatePresence>
    );
  }

  /* ─── 桌面端：右侧滑入（无改动）─── */
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
          {title}
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
      <div style={{ flex: 1, overflowY: 'auto', padding: 16 }}>
        <SafePanel>
          <PanelComponent />
        </SafePanel>
      </div>
    </aside>
  );
};
