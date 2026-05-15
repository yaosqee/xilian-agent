import { create } from 'zustand';
import type { AutonomyStatus, PendingGreeting } from '../types/autonomy';
import {
  fetchAutonomyStatus,
  fetchPendingGreeting,
  ackGreeting,
  pauseAutonomy,
  resumeAutonomy,
  updateAutonomySettings,
} from '../services/api';

interface AutonomyState {
  status: AutonomyStatus | null;
  greeting: PendingGreeting | null;
  loading: boolean;
  error: string | null;

  refreshStatus: () => Promise<void>;
  checkGreeting: () => Promise<PendingGreeting | null>;
  doAckGreeting: (id: string) => Promise<boolean>;
  doPause: () => Promise<void>;
  doResume: () => Promise<void>;
  updateSettings: (patch: Record<string, any>) => Promise<void>;
}

export const useAutonomyStore = create<AutonomyState>((set, get) => ({
  status: null,
  greeting: null,
  loading: false,
  error: null,

  refreshStatus: async () => {
    try {
      const data = await fetchAutonomyStatus();
      if (!data.error) set({ status: data });
    } catch {
      // silent
    }
  },

  checkGreeting: async () => {
    try {
      const data = await fetchPendingGreeting();
      set({ greeting: data });
      return data;
    } catch {
      return null;
    }
  },

  doAckGreeting: async (id: string) => {
    try {
      const data = await ackGreeting(id);
      if (data.status === 'ok') {
        set({ greeting: null });
        return true;
      }
      return false;
    } catch {
      return false;
    }
  },

  doPause: async () => {
    try {
      await pauseAutonomy();
      await get().refreshStatus();
    } catch {
      set({ error: '暂停失败' });
    }
  },

  doResume: async () => {
    try {
      await resumeAutonomy();
      await get().refreshStatus();
    } catch {
      set({ error: '恢复失败' });
    }
  },

  updateSettings: async (patch) => {
    try {
      await updateAutonomySettings(patch);
      await get().refreshStatus();
    } catch {
      set({ error: '设置更新失败' });
    }
  },
}));
