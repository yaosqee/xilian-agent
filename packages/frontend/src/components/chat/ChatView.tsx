import React from 'react';
import { useChat } from '../../hooks/useChat';
import { MessageList } from './MessageList';
import { ChatInput } from './ChatInput';

export const ChatView: React.FC = () => {
  const { messages, isLoading, send, cancel } = useChat();

  return (
    <div className="chat-area">
      <MessageList messages={messages} />
      <ChatInput onSend={send} disabled={isLoading} />
      {isLoading && (
        <div
          onClick={cancel}
          style={{
            position: 'absolute',
            bottom: 100,
            left: '50%',
            transform: 'translateX(-50%)',
            padding: '6px 18px',
            borderRadius: 16,
            background: 'rgba(255,255,255,0.6)',
            backdropFilter: 'blur(8px)',
            border: '1px solid rgba(216,180,226,0.3)',
            fontSize: 13,
            color: 'var(--color-text-sub)',
            cursor: 'pointer',
            boxShadow: 'var(--shadow-sm)',
          }}
        >
          昔涟在打字… 点此取消
        </div>
      )}
    </div>
  );
};
