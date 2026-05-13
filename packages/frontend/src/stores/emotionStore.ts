import { create } from 'zustand';
import type { EmotionData } from '../types/emotion';

interface EmotionState {
  current: EmotionData | null;
  history: EmotionData[];
  setCurrent: (data: EmotionData | null) => void;
  setHistory: (data: EmotionData[]) => void;
}

export const useEmotionStore = create<EmotionState>((set) => ({
  current: null,
  history: [],
  setCurrent: (data) => set({ current: data }),
  setHistory: (data) => set({ history: data }),
}));
