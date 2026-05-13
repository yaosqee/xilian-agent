import { useCallback, useRef } from 'react';
import { useChatStore } from '../stores/chatStore';
import { postChat, postChatStream } from '../services/api';
import type { ChatMessage } from '../types/chat';

let msgId = 0;
function nextId() { return `msg-${Date.now()}-${++msgId}`; }

export function useChat() {
  const { messages, isLoading, error, addMessage, setLoading, setError } = useChatStore();
  const abortRef = useRef<AbortController | null>(null);

  const send = useCallback((text: string, stream: boolean = true) => {
    const userMsg: ChatMessage = {
      id: nextId(), role: 'user', content: text, timestamp: Date.now(),
    };
    addMessage(userMsg);
    setLoading(true);
    setError(null);

    if (stream) {
      let partial = '';
      const controller = postChatStream(
        text,
        (token) => {
          partial += token;
          // Update the assistant message in-place
          const existing = useChatStore.getState().messages;
          const lastIdx = existing.length - 1;
          if (lastIdx >= 0 && existing[lastIdx].role === 'assistant') {
            const updated = [...existing];
            updated[lastIdx] = { ...updated[lastIdx], content: partial };
            useChatStore.setState({ messages: updated });
          } else {
            addMessage({ id: nextId(), role: 'assistant', content: partial, timestamp: Date.now() });
          }
        },
        () => {
          setLoading(false);
        },
        (err) => {
          setError(err.message);
          setLoading(false);
        },
      );
      abortRef.current = controller;
      // Add placeholder assistant message
      addMessage({ id: nextId(), role: 'assistant', content: '', timestamp: Date.now() });
    } else {
      postChat(text)
        .then((reply) => {
          addMessage({ id: nextId(), role: 'assistant', content: reply, timestamp: Date.now() });
          setLoading(false);
        })
        .catch((err) => {
          setError(err.message);
          setLoading(false);
        });
    }
  }, [addMessage, setLoading, setError]);

  const cancel = useCallback(() => {
    abortRef.current?.abort();
    setLoading(false);
  }, [setLoading]);

  return { messages, isLoading, error, send, cancel };
}
