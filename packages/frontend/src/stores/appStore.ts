import { create } from 'zustand';

export type PanelType = 'emotion' | 'memory' | 'autobiography' | 'notebook' | 'audit' | 'skills' | 'settings' | null;

interface AppState {
  activePanel: PanelType;
  sidebarExpanded: boolean;
  sidebarLocked: boolean;
  setActivePanel: (panel: PanelType) => void;
  setSidebarExpanded: (expanded: boolean) => void;
  setSidebarLocked: (locked: boolean) => void;
}

export const useAppStore = create<AppState>((set) => ({
  activePanel: null,
  sidebarExpanded: false,
  sidebarLocked: false,
  setActivePanel: (panel) => set({ activePanel: panel }),
  setSidebarExpanded: (expanded) => set({ sidebarExpanded: expanded }),
  setSidebarLocked: (locked) => set({ sidebarLocked: locked }),
}));
