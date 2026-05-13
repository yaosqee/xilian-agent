import React, { useEffect, useRef } from 'react';
import type { ChatMessage } from '../../types/chat';
import { MessageBubble } from './MessageBubble';

interface Props {
  messages: ChatMessage[];
}

export const MessageList: React.FC<Props> = ({ messages }) => {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  if (messages.length === 0) {
    return (
      <div
        style={{
          flex: 1,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          color: 'rgba(255,255,255,0.2)',
          fontSize: 18,
          userSelect: 'none',
        }}
      >
        <p>昔涟在这里，伙伴想说些什么呢？ ✨</p>
      </div>
    );
  }

  return (
    <div style={{ flex: 1, overflowY: 'auto', padding: '16px 0' }}>
      {messages.map((msg) => (
        <MessageBubble key={msg.id} role={msg.role} content={msg.content} />
      ))}
      <div ref={bottomRef} />
    </div>
  );
};
