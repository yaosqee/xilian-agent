import React from 'react';
import { resetSession } from '../../services/api';
import { useChatStore } from '../../stores/chatStore';

export const SettingsPanel: React.FC = () => {
  const clearMessages = useChatStore((s) => s.clearMessages);

  const handleReset = async () => {
    try {
      await resetSession();
      clearMessages();
      alert('会话已重置 ✨');
    } catch {
      alert('重置失败，请稍后再试 💧');
    }
  };

  return (
    <div>
      <h3 style={{ fontSize: 18, fontWeight: 600, marginBottom: 4 }}>⚙️ 设置</h3>
      <p style={{ fontSize: 13, color: 'rgba(255,255,255,0.4)', marginBottom: 20 }}>
        调整昔涟的行为
      </p>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
        <button
          onClick={handleReset}
          style={{
            padding: '12px 16px',
            borderRadius: 10,
            border: '1px solid rgba(255,100,100,0.2)',
            background: 'rgba(255,100,100,0.08)',
            color: '#e0a0a0',
            cursor: 'pointer',
            fontSize: 14,
          }}
        >
          🔄 重置当前会话
        </button>
        <p style={{ fontSize: 12, color: 'rgba(255,255,255,0.25)', lineHeight: 1.6 }}>
          更多设置项将在后续版本中开放
        </p>
      </div>
    </div>
  );
};
