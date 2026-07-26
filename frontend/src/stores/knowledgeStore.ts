import { create } from "zustand";

import { knowledgeApi } from "@/lib/knowledge-api";
import type { KnowledgeBase, KnowledgeDocument, KnowledgeMode, KnowledgeSystemStatus } from "@/types/knowledge";

interface KnowledgeState {
  mode: KnowledgeMode;
  bases: KnowledgeBase[];
  currentKbId: string;
  documents: KnowledgeDocument[];
  status: KnowledgeSystemStatus | null;
  loading: boolean;
  uploading: boolean;
  error: string;
  loadAll: () => Promise<void>;
  loadBases: (silent?: boolean) => Promise<void>;
  loadDocuments: (kbId?: string) => Promise<void>;
  stopPolling: () => void;
  createBase: (name: string) => Promise<void>;
  renameCurrentBase: (name: string) => Promise<void>;
  uploadDocuments: (files: File[]) => Promise<void>;
  setMode: (mode: KnowledgeMode) => void;
  setCurrentKbId: (id: string) => void;
}

interface StoredPrefs { mode?: KnowledgeMode; currentKbId?: string }

const STORAGE_KEY = "agent-studio:knowledge-preferences";
const modes: KnowledgeMode[] = ["direct", "project", "knowledge"];

const readPrefs = (): StoredPrefs => {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    return raw ? (JSON.parse(raw) as StoredPrefs) : {};
  } catch {
    return {};
  }
};

const remember = (patch: StoredPrefs) => {
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify({ ...readPrefs(), ...patch }));
  } catch {
    // Local storage can be unavailable in restricted webviews.
  }
};

// 文档新鲜度轮询：存在 processing 文档时每 4s 刷新文档与库统计，全部到达终态即停表。
const DOC_POLL_MS = 4000;
let docPollTimer: number | undefined;

const stopDocPolling = (): void => {
  if (docPollTimer !== undefined) {
    window.clearInterval(docPollTimer);
    docPollTimer = undefined;
  }
};

const syncDocPolling = (get: () => KnowledgeState): void => {
  const processing = get().documents.some((doc) => doc.status === "processing");
  if (!processing) {
    stopDocPolling();
    return;
  }
  if (docPollTimer !== undefined) return; // 已在走表，避免重复起表
  docPollTimer = window.setInterval(() => {
    void get().loadDocuments();
    void get().loadBases(true);
  }, DOC_POLL_MS);
};

const stored = readPrefs();
const storedMode = modes.includes(stored.mode as KnowledgeMode) ? (stored.mode as KnowledgeMode) : "direct";
const resolveKbId = (bases: KnowledgeBase[], id: string): string => (bases.some((item) => item.id === id) ? id : bases[0]?.id ?? "");

export const useKnowledgeStore = create<KnowledgeState>((set, get) => ({
  mode: storedMode,
  bases: [],
  currentKbId: stored.currentKbId ?? "",
  documents: [],
  status: null,
  loading: false,
  uploading: false,
  error: "",
  loadAll: async () => {
    await Promise.all([get().loadBases(), _loadStatus(set)]);
    if (get().currentKbId) await get().loadDocuments();
  },
  loadBases: async (silent = false) => {
    // silent：后台轮询刷新时不置 loading，避免页面骨架屏反复闪烁。
    if (!silent) set({ loading: true });
    set({ error: "" });
    try {
      const bases = await knowledgeApi.listBases();
      const currentKbId = resolveKbId(bases, get().currentKbId);
      set({ bases, currentKbId, loading: false });
      remember({ currentKbId });
    } catch (error) {
      set({ loading: false, error: error instanceof Error ? error.message : "知识库加载失败" });
    }
  },
  loadDocuments: async (kbId) => {
    const id = kbId ?? get().currentKbId;
    if (!id) return;
    try {
      set({ error: "" });
      set({ documents: await knowledgeApi.listDocuments(id) });
      syncDocPolling(get);
    } catch (error) {
      set({ error: error instanceof Error ? error.message : "文档加载失败" });
    }
  },
  stopPolling: () => stopDocPolling(),
  createBase: async (name) => {
    const base = await knowledgeApi.createBase(name);
    // 先清空上一个库的文档列表再拉新库，杜绝新建库瞬间渲染旧库残留。
    set((state) => ({ bases: [...state.bases, base], currentKbId: base.id, documents: [] }));
    remember({ currentKbId: base.id, mode: "knowledge" });
    await get().loadDocuments(base.id);
  },
  renameCurrentBase: async (name) => {
    const id = get().currentKbId;
    if (!id) return;
    const base = await knowledgeApi.renameBase(id, name);
    set((state) => ({ bases: state.bases.map((item) => (item.id === id ? { ...item, ...base } : item)) }));
  },
  uploadDocuments: async (files) => {
    const id = get().currentKbId;
    if (!id || !files.length) return;
    set({ uploading: true, error: "" });
    try {
      await knowledgeApi.uploadDocuments(id, files);
      await get().loadDocuments(id);
      await get().loadBases();
    } catch (error) {
      set({ error: error instanceof Error ? error.message : "上传失败" });
    } finally {
      set({ uploading: false });
    }
  },
  setMode: (mode) => {
    set({ mode });
    remember({ mode });
  },
  setCurrentKbId: (currentKbId) => {
    set({ currentKbId });
    remember({ currentKbId });
    void get().loadDocuments(currentKbId);
  },
}));

const _loadStatus = async (set: (patch: Partial<KnowledgeState>) => void) => {
  try {
    set({ status: await knowledgeApi.getStatus() });
  } catch {
    set({ status: { queueReady: false, feishuConfigured: false, knowledgeReady: false } });
  }
};
