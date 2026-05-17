import { create } from 'zustand';
import type { ChatMessage } from '../types/chat';

interface ChatState {
  messages: ChatMessage[];
  isLoading: boolean;
  error: string | null;
  // 历史分页
  historyCursor: number | null;
  hasMore: boolean;
  isLoadingMore: boolean;
  loadedRounds: number;

  addMessage: (msg: ChatMessage) => void;
  prependMessages: (msgs: ChatMessage[]) => void;
  setLoading: (loading: boolean) => void;
  setError: (error: string | null) => void;
  clearMessages: () => void;
  setHistoryMeta: (meta: { cursor: number | null; hasMore: boolean; loadedRounds: number }) => void;
  setLoadingMore: (loading: boolean) => void;
}

const MAX_ROUNDS = 40;

export const useChatStore = create<ChatState>((set) => ({
  messages: [],
  isLoading: false,
  error: null,
  historyCursor: null,
  hasMore: true,
  isLoadingMore: false,
  loadedRounds: 0,

  addMessage: (msg) =>
    set((s) => ({ messages: [...s.messages, msg] })),

  prependMessages: (msgs) =>
    set((s) => ({ messages: [...msgs, ...s.messages] })),

  setLoading: (loading) => set({ isLoading: loading }),
  setError: (error) => set({ error }),

  clearMessages: () => set({
    messages: [], error: null,
    historyCursor: null, hasMore: true, loadedRounds: 0,
  }),

  setHistoryMeta: (meta) => set({
    historyCursor: meta.cursor,
    hasMore: meta.hasMore && meta.loadedRounds < MAX_ROUNDS,
    loadedRounds: meta.loadedRounds,
  }),

  setLoadingMore: (loading) => set({ isLoadingMore: loading }),
}));
