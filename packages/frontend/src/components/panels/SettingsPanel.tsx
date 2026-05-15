import React, { useEffect, useState } from 'react';
import { resetSession } from '../../services/api';
import { useChatStore } from '../../stores/chatStore';
import { useAutonomyStore } from '../../stores/autonomyStore';

export const SettingsPanel: React.FC = () => {
  const clearMessages = useChatStore((s) => s.clearMessages);
  const {
    status, loading, refreshStatus,
    doPause, doResume, updateSettings,
  } = useAutonomyStore();

  const [thresholdInput, setThresholdInput] = useState('6.0');

  useEffect(() => {
    refreshStatus();
  }, []);

  useEffect(() => {
    if (status) {
      setThresholdInput(String(status.threshold));
    }
  }, [status]);

  const handleReset = async () => {
    try {
      await resetSession();
      clearMessages();
      alert('会话已重置 ✨');
    } catch {
      alert('重置失败，请稍后再试 💧');
    }
  };

  const handleThresholdSave = () => {
    const val = parseFloat(thresholdInput);
    if (isNaN(val) || val < 1 || val > 10) {
      alert('阈值需在 1-10 之间');
      return;
    }
    updateSettings({ greeting_threshold: val });
  };

  const isPaused = status?.do_not_disturb;

  return (
    <div>
      <h3 style={{ fontSize: 18, fontWeight: 600, marginBottom: 4 }}>⚙️ 设置</h3>
      <p style={{ fontSize: 13, color: 'rgba(255,255,255,0.4)', marginBottom: 20 }}>
        调整昔涟的行为
      </p>

      {/* ── 自主生命节律（阶段6）── */}
      <div style={{
        background: 'rgba(255,255,255,0.04)',
        borderRadius: 12,
        padding: 16,
        marginBottom: 16,
        border: '1px solid rgba(255,105,180,0.15)',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12 }}>
          <span style={{ fontSize: 14, fontWeight: 600 }}>💌 自主问候</span>
          {status && (
            <span style={{
              fontSize: 10,
              padding: '2px 8px',
              borderRadius: 8,
              background: isPaused
                ? 'rgba(255,150,150,0.15)'
                : 'rgba(100,255,150,0.15)',
              color: isPaused ? '#e08080' : '#80e080',
            }}>
              {isPaused ? '已暂停' : '运行中'}
            </span>
          )}
        </div>

        {/* 想念值 & 令牌 */}
        {status && (
          <div style={{ fontSize: 12, color: 'rgba(255,255,255,0.5)', marginBottom: 12 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
              <span>想念值</span>
              <span style={{ color: status.missing_value >= (status.threshold || 6)
                ? '#ff69b4' : 'rgba(255,255,255,0.3)'
              }}>
                {status.missing_value?.toFixed(1)} / {status.threshold}
              </span>
            </div>
            {/* 想念值进度条 */}
            <div style={{
              height: 4, borderRadius: 2,
              background: 'rgba(255,255,255,0.08)',
              overflow: 'hidden',
            }}>
              <div style={{
                height: '100%',
                width: `${Math.min(100, ((status.missing_value || 0) / 10) * 100)}%`,
                background: 'linear-gradient(90deg, #ff69b4, #ff8dc7)',
                borderRadius: 2,
                transition: 'width 0.5s ease',
              }} />
            </div>

            <div style={{
              display: 'flex', justifyContent: 'space-between',
              marginTop: 6, fontSize: 11, color: 'rgba(255,255,255,0.3)',
            }}>
              <span>令牌余量</span>
              <span>{status.bucket_tokens?.toFixed(1)} / {status.bucket_capacity}</span>
            </div>
          </div>
        )}

        {/* 阈值滑块 */}
        <div style={{ marginBottom: 12 }}>
          <label style={{ fontSize: 12, color: 'rgba(255,255,255,0.5)', display: 'block', marginBottom: 4 }}>
            触发阈值：{thresholdInput}
          </label>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            <input
              type="range"
              min="1"
              max="10"
              step="0.5"
              value={thresholdInput}
              onChange={(e) => setThresholdInput(e.target.value)}
              onMouseUp={handleThresholdSave}
              onTouchEnd={handleThresholdSave}
              style={{ flex: 1, accentColor: '#ff69b4' }}
            />
            <button
              onClick={handleThresholdSave}
              style={{
                padding: '4px 10px', borderRadius: 6, border: 'none',
                background: 'rgba(255,105,180,0.2)',
                color: '#ff69b4', cursor: 'pointer', fontSize: 12,
              }}
            >
              保存
            </button>
          </div>
        </div>

        {/* 暂停/恢复 */}
        <button
          onClick={() => isPaused ? doResume() : doPause()}
          style={{
            width: '100%', padding: '8px 12px', borderRadius: 8,
            border: isPaused
              ? '1px solid rgba(100,255,150,0.2)'
              : '1px solid rgba(255,150,150,0.2)',
            background: isPaused
              ? 'rgba(100,255,150,0.08)'
              : 'rgba(255,150,150,0.08)',
            color: isPaused ? '#80e080' : '#e08080',
            cursor: 'pointer', fontSize: 13,
          }}
        >
          {isPaused ? '▶ 恢复自主问候' : '⏸ 暂停自主问候'}
        </button>
      </div>

      {/* ── 会话重置 ── */}
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
      </div>
    </div>
  );
};
