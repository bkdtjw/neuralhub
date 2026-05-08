import { create } from "zustand";

import { api } from "@/lib/api-client";
import type { Provider } from "@/types";

interface AgentState {
  currentModel: string;
  currentProviderId: string | null;
  providers: Provider[];
  workspace: string | null;
  permissionMode: "readonly" | "auto" | "full";
  loadProviders: () => Promise<void>;
  openFolder: () => Promise<void>;
  setPermissionMode: (mode: "readonly" | "auto" | "full") => void;
  setModel: (model: string) => void;
  setProvider: (id: string) => void;
  setWorkspace: (path: string) => void;
}

export const useAgentStore = create<AgentState>((set, get) => ({
  currentModel: "",
  currentProviderId: null,
  providers: [],
  workspace: null,
  permissionMode: "auto",
  loadProviders: async () => {
    try {
      const providers = await api.listProviders();
      const selected = providers.find((item) => item.id === get().currentProviderId);
      const defaultProvider = providers.find((item) => item.isDefault) ?? providers[0];
      const provider = selected ?? defaultProvider;
      const currentModel = get().currentModel;
      const availableModels = provider?.availableModels ?? [];
      const modelIsAvailable = availableModels.length === 0 || availableModels.includes(currentModel);
      set({
        providers,
        currentProviderId: provider?.id ?? null,
        currentModel: currentModel && modelIsAvailable ? currentModel : provider?.defaultModel ?? "",
      });
    } catch (error) {
      console.error("loadProviders failed", error);
    }
  },
  openFolder: async () => {
    if (!window.electronAPI) {
      const path = window.prompt("输入项目文件夹路径：");
      if (path) set({ workspace: path.trim() });
      return;
    }
    const path = await window.electronAPI.selectFolder();
    if (path) set({ workspace: path });
  },
  setPermissionMode: (mode) => set({ permissionMode: mode }),
  setModel: (model: string) => set({ currentModel: model }),
  setProvider: (id: string) =>
    set((state) => {
      const provider = state.providers.find((item) => item.id === id);
      return { currentProviderId: id, currentModel: provider?.defaultModel ?? state.currentModel };
    }),
  setWorkspace: (path: string) => set({ workspace: path }),
}));
