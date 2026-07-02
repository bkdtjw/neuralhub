import { create } from "zustand";

import { hooksApi } from "@/lib/hooks-api";
import { MOCK_SUMMARIES, synthSummary } from "@/lib/hooks-mock";
import type { HookDraft, HookSummary } from "@/types/hooks";

interface HooksState {
  summaries: HookSummary[];
  currentId: string;
  loading: boolean;
  error: string;
  scanningId: string;
  scanNote: string;
  usingMock: boolean;
  poller: number | null;
  loadAll: () => Promise<void>;
  refresh: () => Promise<void>;
  selectHook: (id: string) => void;
  createHook: (draft: HookDraft) => Promise<void>;
  updateHook: (id: string, draft: HookDraft) => Promise<void>;
  deleteHook: (id: string) => Promise<void>;
  runHook: (id: string) => Promise<void>;
  startPolling: () => void;
  stopPolling: () => void;
}

const POLL_MS = 20000;
// mock 仅作显式开发开关：VITE_HOOKS_MOCK=1 时才用演示数据，初始化判定一次即固定。
// 后端已上线，默认（未设该变量）彻底禁用自动降级——refresh 失败就报错并自愈，绝不覆盖真实数据。
const MOCK_ENABLED = import.meta.env.VITE_HOOKS_MOCK === "1";
const pickCurrent = (items: HookSummary[], id: string): string =>
  items.some((s) => s.hook.id === id) ? id : items[0]?.hook.id ?? "";

export const useHooksStore = create<HooksState>((set, get) => ({
  summaries: [],
  currentId: "",
  loading: false,
  error: "",
  scanningId: "",
  scanNote: "",
  usingMock: MOCK_ENABLED,
  poller: null,
  loadAll: async () => {
    set({ loading: true });
    await get().refresh();
    set({ loading: false });
  },
  refresh: async () => {
    try {
      const summaries = await hooksApi.list();
      set((s) => ({ summaries, currentId: pickCurrent(summaries, s.currentId), error: "" }));
    } catch (error) {
      if (MOCK_ENABLED) {
        // 显式演示模式：首次空载才注入演示数据，已有内存编辑则保留，不报错。
        set((s) => {
          if (s.summaries.length) return {} as Partial<HooksState>;
          return { summaries: MOCK_SUMMARIES, currentId: pickCurrent(MOCK_SUMMARIES, s.currentId) };
        });
        return;
      }
      // 真实模式：失败就是失败——保留已加载数据不覆盖，只置 error（下轮成功自动清空自愈）。
      set({ error: error instanceof Error ? `加载失败：${error.message}` : "加载失败，将自动重试" });
    }
  },
  selectHook: (currentId) => set({ currentId, scanNote: "" }),
  createHook: async (draft) => {
    if (get().usingMock) {
      const summary = synthSummary(draft, `mock-${Date.now()}`);
      set((s) => ({ summaries: [...s.summaries, summary], currentId: summary.hook.id }));
      return;
    }
    const summary = await hooksApi.create(draft);
    set((s) => ({ summaries: [...s.summaries, summary], currentId: summary.hook.id }));
  },
  updateHook: async (id, draft) => {
    if (get().usingMock) {
      set((s) => ({
        summaries: s.summaries.map((it) => (it.hook.id === id ? { ...it, hook: { ...it.hook, ...draft } } : it)),
      }));
      return;
    }
    const summary = await hooksApi.update(id, draft);
    set((s) => ({ summaries: s.summaries.map((it) => (it.hook.id === id ? summary : it)) }));
  },
  deleteHook: async (id) => {
    if (!get().usingMock) await hooksApi.remove(id);
    set((s) => {
      const summaries = s.summaries.filter((it) => it.hook.id !== id);
      return { summaries, currentId: pickCurrent(summaries, s.currentId) };
    });
  },
  runHook: async (id) => {
    if (get().usingMock) return;
    const before = get().summaries.find((s) => s.hook.id === id)?.state?.timeline.length ?? 0;
    set({ scanningId: id, scanNote: "", error: "" });
    try {
      await hooksApi.run(id);
      await get().refresh();
      const after = get().summaries.find((s) => s.hook.id === id)?.state?.timeline.length ?? 0;
      const delta = after - before;
      set({ scanNote: delta > 0 ? `扫描完成：新增 ${delta} 条动态` : "扫描完成：本轮无新进展" });
    } catch (error) {
      set({ scanNote: error instanceof Error ? `扫描失败：${error.message}` : "扫描失败" });
    } finally {
      set({ scanningId: "" });
    }
  },
  startPolling: () => {
    if (get().poller !== null) return;
    // 显式演示模式无需轮询（避免打扰开发后端、覆盖内存编辑）；真实模式必须轮询以自愈。
    if (MOCK_ENABLED) return;
    const poller = window.setInterval(() => void get().refresh(), POLL_MS);
    set({ poller });
  },
  stopPolling: () => {
    const poller = get().poller;
    if (poller !== null) window.clearInterval(poller);
    set({ poller: null });
  },
}));
