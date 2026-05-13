import React from 'react';
import { useChat } from '../../hooks/useChat';
import { MessageList } from './MessageList';
import { ChatInput } from './ChatInput';

export const ChatView: React.FC = () => {
  const { messages, isLoading, send, cancel } = useChat();

  return (
    <>
      <MessageList messages={messages} />
      <ChatInput onSend={send} disabled={isLoading} />
      {isLoading && (
        <div
          onClick={cancel}
          style={{
            position: 'absolute',
            bottom: 80,
            left: '50%',
            transform: 'translateX(-50%)',
            padding: '6px 16px',
            borderRadius: 16,
            background: 'rgba(255,255,255,0.08)',
            fontSize: 12,
            color: 'rgba(255,255,255,0.5)',
            cursor: 'pointer',
          }}
        >
          昔涟在打字… 点此取消
        </div>
      )}
    </>
  );
};
