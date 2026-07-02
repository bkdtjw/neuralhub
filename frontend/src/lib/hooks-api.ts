import type {
  EventHook,
  HookDraft,
  HookState,
  HookStatus,
  HookSummary,
  SourceHealth,
  TimelineEntry,
} from "@/types/hooks";
import { authorizedFetchJson, getApiErrorMessage } from "@/lib/api-auth";

const API_BASE = import.meta.env.VITE_API_BASE || "";

// ---- wire 格式（snake_case，后端真相源；与 backend 字段逐字一致） ----
interface TwitterWire {
  accounts: string[];
  keywords: string[];
}
interface SourcesWire {
  twitter?: boolean;
  exa_web: boolean;
  zhipu_search: boolean;
  youtube: boolean;
}
interface HookWire {
  id: string;
  name: string;
  twitter: TwitterWire;
  sources: SourcesWire;
  cadence_minutes: number;
  materiality: number;
  enabled: boolean;
  created_at: string;
}
interface TimelineWire {
  ts: string;
  text: string;
  is_new: boolean;
  source: string;
}
interface SourceHealthWire {
  source: string;
  online: boolean;
  last_ok: string;
}
interface StateWire {
  hook_id: string;
  status: HookStatus;
  summary: string;
  confidence: number;
  timeline: TimelineWire[];
  unseen_count: number;
  source_health: SourceHealthWire[];
  last_scanned: string;
}
interface SummaryWire {
  hook: HookWire;
  state: StateWire | null;
}

const request = async <T>(path: string, options: RequestInit = {}): Promise<T> => {
  const { response, data } = await authorizedFetchJson(`${API_BASE}${path}`, options);
  if (!response.ok) {
    throw new Error(getApiErrorMessage(data, response.status));
  }
  return data as T;
};

const json = (body: Record<string, unknown>): string => JSON.stringify(body);

const toHook = (w: HookWire): EventHook => ({
  id: w.id,
  name: w.name,
  twitter: { accounts: w.twitter?.accounts ?? [], keywords: w.twitter?.keywords ?? [] },
  sources: {
    twitter: w.sources?.twitter ?? true,
    exaWeb: w.sources?.exa_web ?? false,
    zhipuSearch: w.sources?.zhipu_search ?? false,
    youtube: w.sources?.youtube ?? false,
  },
  cadenceMinutes: w.cadence_minutes,
  materiality: w.materiality,
  enabled: w.enabled,
  createdAt: w.created_at,
});

const toTimeline = (w: TimelineWire): TimelineEntry => ({
  ts: w.ts,
  text: w.text,
  isNew: w.is_new,
  source: w.source,
});

const toHealth = (w: SourceHealthWire): SourceHealth => ({
  source: w.source,
  online: w.online,
  lastOk: w.last_ok,
});

const toState = (w: StateWire | null): HookState | null =>
  w
    ? {
        hookId: w.hook_id,
        status: w.status,
        summary: w.summary,
        confidence: w.confidence,
        timeline: (w.timeline ?? []).map(toTimeline),
        unseenCount: w.unseen_count,
        sourceHealth: (w.source_health ?? []).map(toHealth),
        lastScanned: w.last_scanned,
      }
    : null;

const toSummary = (w: SummaryWire): HookSummary => ({ hook: toHook(w.hook), state: toState(w.state) });

const draftToWire = (draft: HookDraft): Record<string, unknown> => ({
  name: draft.name,
  twitter: { accounts: draft.twitter.accounts, keywords: draft.twitter.keywords },
  sources: {
    twitter: draft.sources.twitter,
    exa_web: draft.sources.exaWeb,
    zhipu_search: draft.sources.zhipuSearch,
    youtube: draft.sources.youtube,
  },
  cadence_minutes: draft.cadenceMinutes,
  materiality: draft.materiality,
  enabled: draft.enabled,
});

export const hooksApi = {
  list: async (): Promise<HookSummary[]> => {
    const res = await request<{ hooks: SummaryWire[] }>("/api/hooks");
    return (res.hooks ?? []).map(toSummary);
  },
  get: async (id: string): Promise<HookSummary> => {
    const res = await request<SummaryWire>(`/api/hooks/${encodeURIComponent(id)}`);
    return toSummary(res);
  },
  create: async (draft: HookDraft): Promise<HookSummary> => {
    const res = await request<SummaryWire>("/api/hooks", { method: "POST", body: json(draftToWire(draft)) });
    return toSummary(res);
  },
  update: async (id: string, draft: HookDraft): Promise<HookSummary> => {
    const res = await request<SummaryWire>(`/api/hooks/${encodeURIComponent(id)}`, {
      method: "PUT",
      body: json(draftToWire(draft)),
    });
    return toSummary(res);
  },
  remove: (id: string): Promise<unknown> =>
    request(`/api/hooks/${encodeURIComponent(id)}`, { method: "DELETE" }),
  run: (id: string): Promise<unknown> =>
    request(`/api/hooks/${encodeURIComponent(id)}/run`, { method: "POST" }),
  markSeen: async (id: string): Promise<void> => {
    await request(`/api/hooks/${encodeURIComponent(id)}/seen`, { method: "POST" });
  },
  log: async (id: string): Promise<TimelineEntry[]> => {
    const res = await request<{ entries: TimelineWire[] }>(`/api/hooks/${encodeURIComponent(id)}/log`);
    return (res.entries ?? []).map(toTimeline);
  },
};
