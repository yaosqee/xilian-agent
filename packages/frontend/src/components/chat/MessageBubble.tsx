import React from 'react';

interface Props {
  role: 'user' | 'assistant';
  content: string;
}

export const MessageBubble: React.FC<Props> = React.memo(({ role, content }) => {
  const isXilian = role === 'assistant';
  return (
    <div className={`chat-message-row ${isXilian ? 'chat-message-row--xilian' : 'chat-message-row--partner'}`}>
      <div className={isXilian ? 'bubble-xilian' : 'bubble-partner'}>
        {content || (
          <span style={{ opacity: 0.5, fontStyle: 'italic' }}>
            人家在想呢…
          </span>
        )}
      </div>
    </div>
  );
});
