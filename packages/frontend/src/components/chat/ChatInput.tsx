import React, { useState, useRef } from 'react';

interface Props {
  onSend: (text: string) => void;
  disabled: boolean;
}

export const ChatInput: React.FC<Props> = ({ onSend, disabled }) => {
  const [text, setText] = useState('');
  const inputRef = useRef<HTMLInputElement>(null);

  const handleSend = () => {
    const trimmed = text.trim();
    if (!trimmed || disabled) return;
    onSend(trimmed);
    setText('');
    inputRef.current?.focus();
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 12,
        padding: '16px 24px',
        borderTop: '1px solid rgba(255,255,255,0.06)',
      }}
    >
      <input
        ref={inputRef}
        type="text"
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={handleKeyDown}
        placeholder={disabled ? '昔涟正在整理记忆…' : '和昔涟说说话吧…'}
        disabled={disabled}
        autoFocus
        style={{
          flex: 1,
          padding: '12px 18px',
          borderRadius: 24,
          border: '1px solid rgba(255,255,255,0.1)',
          background: 'rgba(255,255,255,0.04)',
          color: '#e0e0e0',
          fontSize: 15,
          outline: 'none',
          transition: 'border-color 200ms',
        }}
        onFocus={(e) => {
          e.currentTarget.style.borderColor = 'rgba(100,140,220,0.4)';
        }}
        onBlur={(e) => {
          e.currentTarget.style.borderColor = 'rgba(255,255,255,0.1)';
        }}
      />
      <button
        onClick={handleSend}
        disabled={disabled || !text.trim()}
        style={{
          width: 44,
          height: 44,
          borderRadius: '50%',
          border: 'none',
          background:
            disabled || !text.trim()
              ? 'rgba(255,255,255,0.06)'
              : 'rgba(100,140,220,0.3)',
          color:
            disabled || !text.trim()
              ? 'rgba(255,255,255,0.25)'
              : '#fff',
          fontSize: 20,
          cursor: disabled || !text.trim() ? 'default' : 'pointer',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          transition: 'background 200ms, color 200ms',
        }}
      >
        ✦
      </button>
    </div>
  );
};
