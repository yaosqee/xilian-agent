import React from 'react';

interface Props {
  role: 'user' | 'assistant';
  content: string;
}

export const MessageBubble: React.FC<Props> = React.memo(({ role, content }) => {
  const isUser = role === 'user';
  return (
    <div
      style={{
        display: 'flex',
        justifyContent: isUser ? 'flex-end' : 'flex-start',
        padding: '4px 16px',
        animation: 'fadeIn 300ms ease',
      }}
    >
      <div
        style={{
          maxWidth: '70%',
          padding: '12px 18px',
          borderRadius: isUser ? '18px 18px 4px 18px' : '18px 18px 18px 4px',
          background: isUser
            ? 'rgba(100, 140, 220, 0.25)'
            : 'rgba(255, 255, 255, 0.06)',
          color: isUser ? '#c8d8f8' : '#e0e0e0',
          fontSize: 15,
          lineHeight: 1.65,
          whiteSpace: 'pre-wrap',
          wordBreak: 'break-word',
          border: isUser
            ? '1px solid rgba(100, 140, 220, 0.2)'
            : '1px solid rgba(255, 255, 255, 0.05)',
        }}
      >
        {content || (
          <span style={{ opacity: 0.5, fontStyle: 'italic' }}>
            人家在想呢…
          </span>
        )}
      </div>
    </div>
  );
});
