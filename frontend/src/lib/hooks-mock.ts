// 仅供显式演示开关（VITE_HOOKS_MOCK=1）使用的本地看板数据；默认运行时不加载（见 hooksStore）。
import type { HookDraft, HookSummary, SourceHealth } from "@/types/hooks";

export const MOCK_SUMMARIES: HookSummary[] = [
  {
    hook: {
      id: "mock-fable5",
      name: "Fable5 政府解禁进展",
      twitter: { accounts: ["polymarket", "anthropicai", "sama"], keywords: ["Fable 5", "解禁", "100 机构"] },
      sources: { twitter: true, exaWeb: true, zhipuSearch: true, youtube: false },
      cadenceMinutes: 45,
      materiality: 65,
      enabled: true,
      createdAt: "2026-06-20T08:00:00Z",
    },
    state: {
      hookId: "mock-fable5",
      status: "escalating",
      summary: "美政府据传将放宽 Fable5 出口，开放约 100 家机构小范围试用；Anthropic 官方尚未确认。",
      confidence: 72,
      timeline: [
        { ts: "2026-06-27T09:12:00Z", text: "Polymarket 新开市场「Fable5 7 月前对机构开放?」当前 63%", isNew: true, source: "twitter" },
        { ts: "2026-06-26T22:40:00Z", text: "CNBC：消息人士称商务部正评估对约 100 家受信任机构的有限许可", isNew: false, source: "exa" },
        { ts: "2026-06-25T14:05:00Z", text: "@sama 转推相关报道，配文 interesting", isNew: false, source: "twitter" },
      ],
      unseenCount: 1,
      sourceHealth: [
        { source: "twitter", online: true, lastOk: "2026-06-27T09:12:00Z" },
        { source: "exa", online: true, lastOk: "2026-06-27T08:50:00Z" },
        { source: "zhipu", online: true, lastOk: "2026-06-27T08:50:00Z" },
      ],
      lastScanned: "2026-06-27T09:12:00Z",
    },
  },
  {
    hook: {
      id: "mock-nvidia",
      name: "Nvidia 下一代卡发布",
      twitter: { accounts: ["nvidia"], keywords: ["Rubin", "GB300", "发布"] },
      sources: { twitter: true, exaWeb: true, zhipuSearch: true, youtube: true },
      cadenceMinutes: 180,
      materiality: 60,
      enabled: true,
      createdAt: "2026-06-18T08:00:00Z",
    },
    state: {
      hookId: "mock-nvidia",
      status: "stable",
      summary: "暂无重大进展，等待 GTC 官方议程更新。",
      confidence: 40,
      timeline: [{ ts: "2026-06-27T06:00:00Z", text: "例行扫描：无新增重大信号", isNew: false, source: "exa" }],
      unseenCount: 0,
      sourceHealth: [
        { source: "twitter", online: true, lastOk: "2026-06-27T06:00:00Z" },
        { source: "exa", online: true, lastOk: "2026-06-27T06:00:00Z" },
        { source: "youtube", online: false, lastOk: "2026-06-26T18:00:00Z" },
      ],
      lastScanned: "2026-06-27T06:00:00Z",
    },
  },
];

// mock 模式下用草稿合成一个 summary（新建钩子时即时反馈）
export const synthSummary = (draft: HookDraft, id: string): HookSummary => {
  const health: SourceHealth[] = [];
  if (draft.twitter.accounts.length || draft.twitter.keywords.length) {
    health.push({ source: "twitter", online: false, lastOk: "" });
  }
  if (draft.sources.exaWeb) health.push({ source: "exa", online: false, lastOk: "" });
  if (draft.sources.zhipuSearch) health.push({ source: "zhipu", online: false, lastOk: "" });
  if (draft.sources.youtube) health.push({ source: "youtube", online: false, lastOk: "" });
  return {
    hook: { id, createdAt: new Date().toISOString(), ...draft },
    state: {
      hookId: id,
      status: "developing",
      summary: "尚未扫描",
      confidence: 0,
      timeline: [],
      unseenCount: 0,
      sourceHealth: health,
      lastScanned: "",
    },
  };
};
