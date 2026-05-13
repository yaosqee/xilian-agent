import { create } from 'zustand';
import type { ChatMessage } from '../types/chat';

interface ChatState {
  messages: ChatMessage[];
  isLoading: boolean;
  error: string | null;
  addMessage: (msg: ChatMessage) => void;
  setLoading: (loading: boolean) => void;
  setError: (error: string | null) => void;
  clearMessages: () => void;
}

export const useChatStore = create<ChatState>((set) => ({
  messages: [],
  isLoading: false,
  error: null,
  addMessage: (msg) =>
    set((s) => ({ messages: [...s.messages, msg] })),
  setLoading: (loading) => set({ isLoading: loading }),
  setError: (error) => set({ error }),
  clearMessages: () => set({ messages: [], error: null }),
}));
