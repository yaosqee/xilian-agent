import { useCallback, useRef, useEffect } from 'react';
import { useChatStore } from '../stores/chatStore';
import { postChat, postChatStream, fetchConversationHistory } from '../services/api';
import type { ChatMessage } from '../types/chat';

let msgId = 0;
function nextId() { return `msg-${Date.now()}-${++msgId}`; }

export function useChat() {
  const {
    messages, isLoading, error, historyCursor, hasMore, isLoadingMore, loadedRounds,
    addMessage, prependMessages, setLoading, setError, setHistoryMeta, setLoadingMore,
  } = useChatStore();
  const abortRef = useRef<AbortController | null>(null);
  const initialLoaded = useRef(false);

  // 自动加载最近 10 轮历史
  const loadHistory = useCallback(async () => {
    if (isLoadingMore || !hasMore) return;
    setLoadingMore(true);
    try {
      const res = await fetchConversationHistory(historyCursor ?? undefined, 10);
      const msgs: ChatMessage[] = [];
      for (const item of res.items) {
        msgs.push({
          id: `hist-${item.id}-u`,
          role: 'user',
          content: item.user_message,
          timestamp: item.timestamp * 1000,
        });
        msgs.push({
          id: `hist-${item.id}-a`,
          role: 'assistant',
          content: item.assistant_reply,
          timestamp: item.timestamp * 1000,
        });
      }
      if (msgs.length > 0) prependMessages(msgs);
      const newLoadedRounds = loadedRounds + res.items.length;
      setHistoryMeta({
        cursor: res.oldest_id,
        hasMore: res.has_more,
        loadedRounds: newLoadedRounds,
      });
    } catch (err) {
      console.error('Failed to load history:', err);
    } finally {
      setLoadingMore(false);
    }
  }, [historyCursor, hasMore, isLoadingMore, loadedRounds, prependMessages, setHistoryMeta, setLoadingMore]);

  // 首次挂载时自动加载
  useEffect(() => {
    if (!initialLoaded.current) {
      initialLoaded.current = true;
      loadHistory();
    }
  }, [loadHistory]);

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

  return { messages, isLoading, error, send, cancel, loadHistory, hasMore, isLoadingMore };
}
