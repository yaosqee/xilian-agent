import { create } from 'zustand';

export type PanelType = 'emotion' | 'memory' | 'memories' | 'autobiography' | 'settings' | null;

interface AppState {
  activePanel: PanelType;
  iconExpanded: boolean;
  setActivePanel: (panel: PanelType) => void;
  togglePanel: (panel: PanelType) => void;
  setIconExpanded: (expanded: boolean) => void;
}

export const useAppStore = create<AppState>((set) => ({
  activePanel: null,
  iconExpanded: false,
  setActivePanel: (panel) => set({ activePanel: panel }),
  togglePanel: (panel) =>
    set((s) => ({ activePanel: s.activePanel === panel ? null : panel })),
  setIconExpanded: (expanded) => set({ iconExpanded: expanded }),
}));
