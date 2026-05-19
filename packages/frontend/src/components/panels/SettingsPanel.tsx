import React, { useEffect, useState, useRef } from 'react';
import { resetSession, fetchBackground, uploadBackground } from '../../services/api';
import { useChatStore } from '../../stores/chatStore';
import { useAutonomyStore } from '../../stores/autonomyStore';

export const SettingsPanel: React.FC = () => {
  const clearMessages = useChatStore((s) => s.clearMessages);
  const {
    status, loading, refreshStatus,
    doPause, doResume, updateSettings,
  } = useAutonomyStore();

  const [thresholdInput, setThresholdInput] = useState('6.0');
  const [bgFilename, setBgFilename] = useState('xilian.png');
  const [uploading, setUploading] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    refreshStatus();
    fetchBackground()
      .then((d) => setBgFilename(d.filename))
      .catch(() => {});
  }, []);

  useEffect(() => {
    if (status) {
      setThresholdInput(String(status.threshold));
    }
  }, [status]);

  const handleReset = async () => {
    if (!window.confirm(
      '确定要重置当前会话吗？\n\n' +
      '这将清空所有对话记录，开始一段全新的对话。\n' +
      '昔涟对你的印象、记忆、笔记和好感度不会丢失。'
    )) return;
    try {
      await resetSession();
      clearMessages();
      alert('会话已重置 —— 所有对话记录已清空，开始新对话吧 ♪');
    } catch {
      alert('重置失败，请稍后再试');
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

  const handleUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploading(true);
    try {
      const result = await uploadBackground(file);
      setBgFilename(result.filename);
      // 刷新页面背景：触发 MainLayout 重新获取
      window.dispatchEvent(new CustomEvent('background-changed', { detail: result.url }));
    } catch {
      alert('上传失败，请检查文件格式和大小（<10MB）');
    } finally {
      setUploading(false);
      if (fileRef.current) fileRef.current.value = '';
    }
  };

  const isPaused = status?.do_not_disturb;

  const sectionStyle: React.CSSProperties = {
    background: 'rgba(255, 255, 255, 0.45)',
    backdropFilter: 'blur(12px)',
    WebkitBackdropFilter: 'blur(12px)',
    borderRadius: 'var(--radius-card)',
    padding: 16,
    marginBottom: 14,
    border: '1px solid rgba(255, 255, 255, 0.6)',
    boxShadow: '0 4px 16px rgba(180, 140, 220, 0.1)',
  };

  return (
    <div>
      <h3 style={{ fontSize: 18, fontWeight: 600, marginBottom: 2, color: 'var(--color-text)' }}>
        设置
      </h3>
      <p style={{ fontSize: 13, color: 'var(--color-text-dim)', marginBottom: 18 }}>
        调整昔涟的行为与外观
      </p>

      {/* ── 背景图片 ── */}
      <div style={sectionStyle}>
        <div style={{ fontSize: 14, fontWeight: 600, color: 'var(--color-text)', marginBottom: 10 }}>
          背景图片
        </div>
        <div style={{ fontSize: 12, color: 'var(--color-text-dim)', marginBottom: 10 }}>
          当前：{bgFilename}
        </div>
        <input
          ref={fileRef}
          type="file"
          accept="image/png,image/jpeg,image/webp,image/gif"
          onChange={handleUpload}
          style={{ display: 'none' }}
          id="bg-upload"
        />
        <label
          htmlFor="bg-upload"
          style={{
            display: 'inline-block',
            padding: '8px 18px',
            borderRadius: 'var(--radius-btn)',
            background: uploading
              ? 'rgba(200, 180, 200, 0.3)'
              : 'linear-gradient(135deg, var(--color-pink), var(--color-purple))',
            color: '#fff',
            fontSize: 13,
            fontWeight: 500,
            cursor: uploading ? 'default' : 'pointer',
            boxShadow: '0 2px 10px rgba(255, 183, 197, 0.3)',
            transition: `all var(--duration-normal) var(--ease-spring)`,
          }}
        >
          {uploading ? '上传中...' : '选择图片上传'}
        </label>
        <span style={{ fontSize: 11, color: 'var(--color-text-muted)', marginLeft: 10 }}>
          支持 png/jpg/webp，&le;10MB
        </span>
      </div>

      {/* ── 自主问候 ── */}
      <div style={sectionStyle}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12 }}>
          <span style={{ fontSize: 14, fontWeight: 600, color: 'var(--color-text)' }}>
            自主问候
          </span>
          {status && (
            <span style={{
              fontSize: 10,
              padding: '2px 8px',
              borderRadius: 8,
              background: isPaused
                ? 'rgba(100, 140, 200, 0.12)'
                : 'rgba(255, 183, 197, 0.15)',
              color: isPaused ? 'var(--color-ice-dark)' : 'var(--color-pink-dark)',
            }}>
              {isPaused ? '已暂停' : '运行中'}
            </span>
          )}
        </div>

        {status && (
          <div style={{ fontSize: 12, color: 'var(--color-text-dim)', marginBottom: 12 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
              <span>想念值</span>
              <span style={{
                color: status.missing_value >= (status.threshold || 6)
                  ? 'var(--color-pink-dark)'
                  : 'var(--color-text-dim)',
                fontWeight: 500,
              }}>
                {status.missing_value?.toFixed(1)} / {status.threshold}
              </span>
            </div>
            <div style={{
              height: 4, borderRadius: 2,
              background: 'rgba(200, 180, 210, 0.2)',
              overflow: 'hidden',
            }}>
              <div style={{
                height: '100%',
                width: `${Math.min(100, ((status.missing_value || 0) / 10) * 100)}%`,
                background: 'linear-gradient(90deg, var(--color-pink), var(--color-purple))',
                borderRadius: 2,
                transition: 'width 0.5s var(--ease-spring)',
              }} />
            </div>
            <div style={{
              display: 'flex', justifyContent: 'space-between',
              marginTop: 6, fontSize: 11, color: 'var(--color-text-muted)',
            }}>
              <span>令牌余量</span>
              <span>{status.bucket_tokens?.toFixed(1)} / {status.bucket_capacity}</span>
            </div>
          </div>
        )}

        <div style={{ marginBottom: 12 }}>
          <label style={{ fontSize: 12, color: 'var(--color-text-dim)', display: 'block', marginBottom: 4 }}>
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
              style={{ flex: 1, accentColor: 'var(--color-pink)' }}
            />
            <button
              onClick={handleThresholdSave}
              style={{
                padding: '4px 12px', borderRadius: 8, border: 'none',
                background: 'rgba(255, 183, 197, 0.18)',
                color: 'var(--color-pink-dark)', cursor: 'pointer', fontSize: 12,
              }}
            >
              保存
            </button>
          </div>
        </div>

        <button
          onClick={() => isPaused ? doResume() : doPause()}
          style={{
            width: '100%', padding: '8px 12px', borderRadius: 8,
            border: isPaused
              ? '1px solid rgba(162, 196, 230, 0.25)'
              : '1px solid rgba(255, 183, 197, 0.2)',
            background: isPaused
              ? 'rgba(162, 196, 230, 0.08)'
              : 'rgba(255, 183, 197, 0.06)',
            color: isPaused ? 'var(--color-ice-dark)' : 'var(--color-pink-dark)',
            cursor: 'pointer', fontSize: 13,
            transition: `all var(--duration-normal) var(--ease-spring)`,
          }}
        >
          {isPaused ? '恢复自主问候' : '暂停自主问候'}
        </button>
      </div>

      {/* ── 会话重置 ── */}
      <div>
        <button
          onClick={handleReset}
          style={{
            width: '100%',
            padding: '10px 16px',
            borderRadius: 'var(--radius-btn)',
            border: '1px solid rgba(200, 100, 120, 0.15)',
            background: 'rgba(200, 100, 120, 0.05)',
            color: 'var(--color-text-dim)',
            cursor: 'pointer',
            fontSize: 13,
            transition: `all var(--duration-normal) var(--ease-spring)`,
          }}
        >
          重置当前会话
        </button>
      </div>
    </div>
  );
};
