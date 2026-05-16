/* FILE: src/components/chat/ChatView.tsx */
import React, { useRef, useEffect, useState, useCallback } from 'react';
import { useChat } from '../../hooks/useChat';
import type { ChatMessage } from '../../types/chat';

/* ── 消息气泡 ── */
const Bubble: React.FC<{ msg: ChatMessage }> = React.memo(({ msg }) => {
  const isXilian = msg.role === 'assistant';

  const bubbleBg = isXilian
    ? 'rgba(252, 235, 240, 0.55)'
    : 'rgba(240, 236, 248, 0.45)';
  const bubbleBorder = isXilian
    ? '1px solid rgba(255, 183, 197, 0.3)'
    : '1px solid rgba(200, 175, 220, 0.25)';
  const bubbleRadius = isXilian
    ? '20px 20px 20px 6px'
    : '20px 20px 6px 20px';

  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        alignItems: isXilian ? 'flex-start' : 'flex-end',
        padding: '0 16px',
        animation: 'fadeInUp var(--duration-normal) var(--ease-spring)',
      }}
    >
      <span
        style={{
          fontSize: 11,
          fontWeight: 600,
          color: 'var(--color-text-dim)',
          marginBottom: 3,
          userSelect: 'none',
          WebkitUserSelect: 'none',
          paddingLeft: isXilian ? 4 : 0,
          paddingRight: isXilian ? 0 : 4,
        }}
      >
        {isXilian ? '昔涟' : '伙伴'}
      </span>

      <div
        style={{
          maxWidth: '75%',
          padding: '12px 18px',
          borderRadius: bubbleRadius,
          background: bubbleBg,
          backdropFilter: 'blur(16px)',
          WebkitBackdropFilter: 'blur(16px)',
          border: bubbleBorder,
          boxShadow: isXilian
            ? '0 4px 16px rgba(255, 183, 197, 0.12)'
            : '0 4px 16px rgba(180, 140, 220, 0.1)',
          fontSize: 14,
          lineHeight: 1.75,
          color: 'var(--color-text)',
          wordBreak: 'break-word',
          whiteSpace: 'pre-wrap',
          letterSpacing: '0.01em',
        }}
      >
        {msg.content || (
          <span style={{ color: 'var(--color-text-muted)', fontStyle: 'italic' }}>
            昔涟在思考...
          </span>
        )}
      </div>
    </div>
  );
});

/* ── 消息列表 ── */
const MessageList: React.FC<{ messages: ChatMessage[] }> = ({ messages }) => {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  if (messages.length === 0) {
    return (
      <div
        style={{
          flex: 1,
        }}
      />
    );
  }

  return (
    <div
      style={{
        flex: 1,
        overflowY: 'auto',
        padding: '16px 0',
        display: 'flex',
        flexDirection: 'column',
        gap: 12,
      }}
    >
      {messages.map((m) => (
        <Bubble key={m.id} msg={m} />
      ))}
      <div ref={bottomRef} />
    </div>
  );
};

/* ── 输入区 · 大 textarea 毛玻璃 ── */
const ChatInput: React.FC<{ onSend: (t: string) => void; disabled: boolean }> = ({
  onSend,
  disabled,
}) => {
  const [text, setText] = useState('');
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    if (!disabled) textareaRef.current?.focus();
  }, [disabled]);

  // 自动调整高度
  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = 'auto';
    el.style.height = `${Math.min(el.scrollHeight, 160)}px`;
  }, [text]);

  const send = useCallback(() => {
    const t = text.trim();
    if (!t || disabled) return;
    onSend(t);
    setText('');
  }, [text, disabled, onSend]);

  const onKey = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      send();
    }
  };

  const canSend = !!text.trim() && !disabled;

  return (
    <div
      style={{
        padding: '8px 20px 16px',
        display: 'flex',
        gap: 10,
        alignItems: 'flex-end',
        flexShrink: 0,
        zIndex: 10,
      }}
    >
      <div
        style={{
          flex: 1,
          display: 'flex',
          alignItems: 'flex-end',
          borderRadius: 'var(--radius-btn)',
          padding: '8px 12px 8px 16px',
          background: 'rgba(255, 255, 255, 0.35)',
          backdropFilter: 'blur(16px)',
          WebkitBackdropFilter: 'blur(16px)',
          border: '1px solid rgba(255, 255, 255, 0.5)',
          boxShadow: '0 4px 20px rgba(180, 140, 220, 0.12)',
          transition: `box-shadow var(--duration-normal) var(--ease-spring), border-color var(--duration-normal) var(--ease-spring)`,
        }}
        onFocus={(e) => {
          const target = e.currentTarget;
          target.style.boxShadow = '0 4px 24px rgba(255, 183, 197, 0.22)';
          target.style.borderColor = 'rgba(255, 183, 197, 0.6)';
        }}
        onBlur={(e) => {
          const target = e.currentTarget;
          target.style.boxShadow = '0 4px 20px rgba(180, 140, 220, 0.12)';
          target.style.borderColor = 'rgba(255, 255, 255, 0.5)';
        }}
        tabIndex={-1}
      >
        <textarea
          ref={textareaRef}
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={onKey}
          disabled={disabled}
          placeholder={disabled ? '昔涟正在整理记忆...' : '说点什么...'}
          rows={1}
          style={{
            flex: 1,
            border: 'none',
            outline: 'none',
            background: 'transparent',
            fontSize: 14,
            color: 'var(--color-text)',
            fontFamily: 'var(--font-sans)',
            padding: '4px 0',
            resize: 'none',
            lineHeight: 1.6,
            minHeight: 28,
            maxHeight: 160,
          }}
        />
      </div>

      {/* 发送按钮 */}
      <button
        onClick={send}
        disabled={!canSend}
        aria-label="发送"
        style={{
          width: 44,
          height: 44,
          minWidth: 44,
          borderRadius: 'var(--radius-btn)',
          border: 'none',
          background: canSend
            ? 'linear-gradient(135deg, var(--color-pink), var(--color-purple))'
            : 'rgba(200, 160, 190, 0.18)',
          color: canSend ? '#fff' : 'var(--color-text-muted)',
          fontSize: 16,
          cursor: canSend ? 'pointer' : 'default',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          transition: `all var(--duration-normal) var(--ease-spring)`,
          boxShadow: canSend ? '0 4px 16px rgba(255, 183, 197, 0.35)' : 'none',
          flexShrink: 0,
        }}
      >
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none"
          stroke="currentColor" strokeWidth="2" strokeLinecap="round"
          strokeLinejoin="round">
          <line x1="12" y1="19" x2="12" y2="5" />
          <polyline points="5 12 12 5 19 12" />
        </svg>
      </button>
    </div>
  );
};

/* ══════════════════════════════════════════════
   ChatView
   ══════════════════════════════════════════════ */
export const ChatView: React.FC = () => {
  const { messages, isLoading, send, cancel } = useChat();

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', position: 'relative' }}>
      {/* 头部 — 更轻盈 */}
      <header
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          padding: '14px 20px',
          flexShrink: 0,
          zIndex: 10,
        }}
      >
        <h1
          className="gradient-text"
          style={{
            fontSize: 15,
            fontWeight: 600,
            letterSpacing: 3,
            margin: 0,
            fontFamily: 'var(--font-serif)',
          }}
        >
          昔涟
        </h1>
      </header>

      {/* 消息区 — 半透玻璃底 */}
      <div
        style={{
          flex: 1,
          margin: '0 8px 8px',
          borderRadius: 'var(--radius-card)',
          background: 'transparent',
          display: 'flex',
          flexDirection: 'column',
          overflow: 'hidden',
        }}
      >
        <MessageList messages={messages} />

        {/* 加载指示 */}
        {isLoading && (
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              gap: 8,
              padding: '0 20px 8px',
            }}
          >
            {[0, 0.2, 0.4].map((delay, i) => (
              <span
                key={i}
                style={{
                  width: 6,
                  height: 6,
                  borderRadius: '50%',
                  background: i % 2 === 0 ? 'var(--color-pink)' : 'var(--color-purple)',
                  animation: `pulseGlow 0.8s var(--ease-spring) ${delay}s infinite`,
                }}
              />
            ))}
            <button
              onClick={cancel}
              style={{
                marginLeft: 8,
                padding: '4px 14px',
                borderRadius: 'var(--radius-full)',
                border: '1px solid rgba(200, 160, 190, 0.3)',
                background: 'var(--glass-bg)',
                color: 'var(--color-text-dim)',
                fontSize: 12,
                cursor: 'pointer',
                transition: `all var(--duration-fast) var(--ease-spring)`,
              }}
            >
              取消
            </button>
          </div>
        )}
      </div>

      <ChatInput onSend={send} disabled={isLoading} />
    </div>
  );
};
