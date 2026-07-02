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
// 请求序号：每次 refresh 开始时 ++ 并快照；create/update/delete 成功写入时也 ++，
// 使此前发出的在途 refresh 全部失效，避免旧响应晚到覆盖刚提交的新数据（缺陷 3）。
let refreshSeq = 0;

const pickCurrent = (items: HookSummary[], id: string): string =>
  items.some((s) => s.hook.id === id) ? id : items[0]?.hook.id ?? "";

// 把某钩子标记为已读：summaries 中该项 unseenCount 清零、timeline 各项 isNew=false。
// 纯本地乐观更新，不触网；未命中 id 时原样返回（引用不变，避免无谓重渲染）。
const clearSeen = (items: HookSummary[], id: string): HookSummary[] => {
  let changed = false;
  const next = items.map((it) => {
    if (it.hook.id !== id || !it.state || it.state.unseenCount === 0) return it;
    changed = true;
    return {
      ...it,
      state: { ...it.state, unseenCount: 0, timeline: it.state.timeline.map((e) => (e.isNew ? { ...e, isNew: false } : e)) },
    };
  });
  return changed ? next : items;
};

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
    const seq = ++refreshSeq;
    try {
      const fetched = await hooksApi.list();
      // 在途期间有更新的请求/写入发生（序号变了）：本次结果已过时，整体丢弃，绝不覆盖新数据。
      if (seq !== refreshSeq) return;
      set((s) => {
        const currentId = pickCurrent(fetched, s.currentId);
        // 详情页正展示的钩子若本轮带回新未读，等同于用户已看见：本地即时清零并异步标已读。
        const shown = fetched.find((it) => it.hook.id === currentId);
        const shouldSeen = !MOCK_ENABLED && !!shown && !!shown.state && shown.state.unseenCount > 0;
        const summaries = shouldSeen ? clearSeen(fetched, currentId) : fetched;
        if (shouldSeen) void hooksApi.markSeen(currentId).catch(() => {});
        return { summaries, currentId, error: "" };
      });
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
  selectHook: (currentId) => {
    // 同步签名：先切换选中并清空扫描提示；若该钩子有未读且非演示模式，
    // 乐观本地清零并 fire-and-forget 标已读（失败静默，下轮 refresh 会带回真值）。
    set((s) => {
      const target = s.summaries.find((it) => it.hook.id === currentId);
      const shouldSeen = !MOCK_ENABLED && !!target?.state && target.state.unseenCount > 0;
      if (shouldSeen) void hooksApi.markSeen(currentId).catch(() => {});
      return { currentId, scanNote: "", summaries: shouldSeen ? clearSeen(s.summaries, currentId) : s.summaries };
    });
  },
  createHook: async (draft) => {
    if (get().usingMock) {
      const summary = synthSummary(draft, `mock-${Date.now()}`);
      set((s) => ({ summaries: [...s.summaries, summary], currentId: summary.hook.id }));
      return;
    }
    const summary = await hooksApi.create(draft);
    refreshSeq++; // 使此前在途的 refresh 失效，防止旧列表覆盖掉刚建的钩子（缺陷 3）
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
    refreshSeq++; // 使此前在途的 refresh 失效，防止旧数据覆盖刚更新的钩子（缺陷 3）
    set((s) => ({ summaries: s.summaries.map((it) => (it.hook.id === id ? summary : it)) }));
  },
  deleteHook: async (id) => {
    try {
      if (!get().usingMock) await hooksApi.remove(id);
    } catch (error) {
      // 删除失败：入 error 通道（页面 rose 横幅显示），不动列表，避免 unhandled rejection。
      set({ error: error instanceof Error ? `删除失败：${error.message}` : "删除失败" });
      return;
    }
    refreshSeq++; // 使此前在途的 refresh 失效，防止旧列表把已删钩子“复活”（缺陷 3）
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
      // 扫描失败走 error 通道（rose 横幅）；scanNote 仅承载成功信息。
      set({ error: error instanceof Error ? `扫描失败：${error.message}` : "扫描失败" });
    } finally {
      // 仅当仍是本次扫描时才解锁：A 扫描中切到 B 再扫，A 的 finally 不得清空 B 的 scanningId（缺陷 4）。
      set((s) => (s.scanningId === id ? { scanningId: "" } : {}));
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
