import React from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { useAppStore } from '../../stores/appStore';
import { EmotionPanel } from './EmotionPanel';
import { MemoryPanel } from './MemoryPanel';
import { MemoryTimeline } from './MemoryTimeline';
import { AutobiographyPanel } from './AutobiographyPanel';
import { SettingsPanel } from './SettingsPanel';

const panels: Record<string, React.FC> = {
  emotion: EmotionPanel,
  memory: MemoryTimeline,      // 新：记忆时间线卡片
  autobiography: AutobiographyPanel,  // 新：自传体日记
  settings: SettingsPanel,
};

export const SlidePanel: React.FC = () => {
  const activePanel = useAppStore((s) => s.activePanel);
  const setActivePanel = useAppStore((s) => s.setActivePanel);

  const PanelContent = activePanel ? panels[activePanel] : null;

  return (
    <AnimatePresence>
      {activePanel && PanelContent && (
        <motion.div
          initial={{ x: 360, opacity: 0 }}
          animate={{ x: 0, opacity: 1 }}
          exit={{ x: 360, opacity: 0 }}
          transition={{ type: 'spring', stiffness: 300, damping: 30 }}
          style={{
            width: 360,
            height: '100vh',
            background: 'rgba(18, 18, 32, 0.92)',
            backdropFilter: 'blur(20px)',
            borderLeft: '1px solid rgba(255,255,255,0.06)',
            overflow: 'hidden',
            display: 'flex',
            flexDirection: 'column',
            flexShrink: 0,
          }}
        >
          {/* Close button */}
          <div style={{ display: 'flex', justifyContent: 'flex-end', padding: '12px 16px' }}>
            <button
              onClick={() => setActivePanel(null)}
              style={{
                background: 'none',
                border: 'none',
                color: 'rgba(255,255,255,0.5)',
                fontSize: 20,
                cursor: 'pointer',
                padding: '4px 8px',
              }}
            >
              ✕
            </button>
          </div>
          <div style={{ flex: 1, overflow: 'auto', padding: '0 20px 20px' }}>
            <PanelContent />
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  );
};
