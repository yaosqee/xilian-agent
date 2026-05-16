/* FILE: src/components/layout/MainLayout.tsx */
import React, { useState, useEffect } from 'react';
import { Sidebar } from './Sidebar';
import { ChatView } from '../chat/ChatView';
import { SlidePanel } from '../panels/SlidePanel';
import { BackgroundLayer } from './BackgroundLayer';
import { fetchBackground } from '../../services/api';

const Atmosphere: React.FC = () => (
  <div className="atmosphere" aria-hidden="true">
    <div className="atmosphere-orb atmosphere-orb--pink" />
    <div className="atmosphere-orb atmosphere-orb--purple" />
    <div className="atmosphere-orb atmosphere-orb--rose" />
  </div>
);

export const MainLayout: React.FC = () => {
  const [bgUrl, setBgUrl] = useState<string | null>(null);

  useEffect(() => {
    fetchBackground()
      .then((data) => {
        if (data.url) setBgUrl(data.url);
      })
      .catch(() => {});

    // 监听背景变更事件（来自 SettingsPanel 上传）
    const handler = (e: Event) => {
      const url = (e as CustomEvent).detail;
      if (url) setBgUrl(url);
    };
    window.addEventListener('background-changed', handler);
    return () => window.removeEventListener('background-changed', handler);
  }, []);

  return (
    <div
      style={{
        position: 'relative',
        display: 'flex',
        width: '100vw',
        height: '100vh',
        color: 'var(--color-text)',
        fontFamily: 'var(--font-sans)',
        overflow: 'hidden',
        background: 'var(--color-bg)', // 兜底色
      }}
    >
      {/* 背景图层 */}
      <BackgroundLayer customUrl={bgUrl} />

      {/* 弥散光氛围层 */}
      <Atmosphere />

      {/* 侧栏 */}
      <Sidebar />

      {/* 主内容区 */}
      <main
        style={{
          position: 'relative',
          zIndex: 10,
          flex: 1,
          display: 'flex',
          flexDirection: 'column',
          minWidth: 0,
          height: '100vh',
        }}
      >
        <ChatView />
      </main>

      {/* 右侧滑出面板 */}
      <SlidePanel />
    </div>
  );
};
