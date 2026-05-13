import React from 'react';
import { IconStrip } from './IconStrip';
import { ChatView } from '../chat/ChatView';
import { SlidePanel } from '../panels/SlidePanel';
import { EncodingStatusBar } from '../status/EncodingStatusBar';

export const MainLayout: React.FC = () => {
  return (
    <div
      style={{
        display: 'flex',
        width: '100vw',
        height: '100vh',
        overflow: 'hidden',
        background: '#0a0a14',
        color: '#e0e0e0',
        fontFamily: "'Inter', 'Noto Sans SC', sans-serif",
      }}
    >
      <IconStrip />
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', position: 'relative' }}>
        <ChatView />
        <EncodingStatusBar />
      </div>
      <SlidePanel />
    </div>
  );
};
