import { create } from 'zustand';
import { fetchAffection } from '../services/api';

export interface AffectionData {
  score: number;
  level: number;
  level_label: string;
  total_conversations: number;
  updated_at: number;
}

interface AffectionState {
  data: AffectionData | null;
  loading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
}

export const useAffectionStore = create<AffectionState>((set) => ({
  data: null,
  loading: false,
  error: null,

  refresh: async () => {
    try {
      const data = await fetchAffection();
      if (!data.error) set({ data, error: null });
      else set({ error: data.error });
    } catch {
      // silent — keep last known data
    }
  },
}));
