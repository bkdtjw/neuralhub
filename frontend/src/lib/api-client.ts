import type { LogEntry, LogSearchParams, LogSearchResult, MetricDetail, MetricsSummary, Provider, Session, TokenUsage, TraceResult, WorkspaceEntry, WorkspaceList, WorkspaceValidation } from "@/types";
import { authorizedFetchJson, getApiErrorMessage } from "@/lib/api-auth";

type JsonBody = Record<string, unknown> | unknown[];

const API_BASE = import.meta.env.VITE_API_BASE || "";

interface SessionResponse {
  id: string;
  config: { model?: string; provider?: string };
  status: Session["status"];
  created_at: string;
  message_count: number;
  title?: string;
  workspace?: string;
}

interface SessionListResponse {
  sessions: SessionResponse[];
}

interface ProviderResponse {
  id: string;
  name: string;
  provider_type: string;
  base_url: string;
  api_key_preview: string;
  default_model: string;
  available_models: string[];
  is_default: boolean;
  enabled: boolean;
}

interface WorkspaceEntryResponse {
  name: string;
  path: string;
  is_directory: boolean;
  is_project: boolean;
}

interface WorkspaceRootsResponse {
  roots: WorkspaceEntryResponse[];
}

interface WorkspaceListResponse {
  root: string;
  path: string;
  parent?: string | null;
  breadcrumbs: Array<{ name: string; path: string }>;
  entries: WorkspaceEntryResponse[];
  truncated: boolean;
}

interface WorkspaceValidationResponse {
  ok: boolean;
  path: string;
  is_project: boolean;
  message: string;
}

interface MetricSeriesResponse {
  total: number;
  daily: Record<string, number>;
}

interface MetricsSummaryResponse {
  period_days: number;
  metrics: Record<string, MetricSeriesResponse>;
}

interface MetricDetailResponse {
  name: string;
  total: number;
  daily: Record<string, number>;
}

interface TokenUsageDayResponse {
  date: string;
  prompt_tokens: number;
  completion_tokens: number;
  cached_prompt_tokens: number;
  llm_calls: number;
  total_tokens: number;
}

interface TokenUsageResponse {
  period_days: number;
  total_tokens: number;
  prompt_tokens: number;
  completion_tokens: number;
  cached_prompt_tokens: number;
  llm_calls: number;
  daily: TokenUsageDayResponse[];
}

interface LogEntryResponse {
  timestamp: string;
  level: LogEntry["level"];
  event: string;
  trace_id: string;
  session_id: string;
  worker_id: string;
  component: string;
  extra: Record<string, unknown>;
}

interface LogSearchResponse {
  count: number;
  logs: LogEntryResponse[];
}

interface TraceResponse {
  trace_id: string;
  events: LogEntryResponse[];
}

const toSession = (item: SessionResponse): Session => ({
  id: item.id,
  model: item.config?.model ?? "",
  providerId: item.config?.provider,
  status: item.status,
  createdAt: item.created_at,
  messageCount: item.message_count,
  title: item.title ?? "",
  workspace: item.workspace ?? "",
});

const toProvider = (item: ProviderResponse): Provider => ({
  id: item.id,
  name: item.name,
  providerType: item.provider_type,
  baseUrl: item.base_url,
  apiKeyPreview: item.api_key_preview,
  defaultModel: item.default_model,
  availableModels: item.available_models ?? [],
  isDefault: item.is_default,
  enabled: item.enabled,
});

const toWorkspaceEntry = (item: WorkspaceEntryResponse): WorkspaceEntry => ({
  name: item.name,
  path: item.path,
  isDirectory: item.is_directory,
  isProject: item.is_project,
});

const toLogEntry = (item: LogEntryResponse): LogEntry => ({
  timestamp: item.timestamp,
  level: item.level,
  event: item.event,
  traceId: item.trace_id,
  sessionId: item.session_id,
  workerId: item.worker_id,
  component: item.component,
  extra: item.extra ?? {},
});

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const url = path.startsWith("http") ? path : `${API_BASE}${path}`;
  const { response, data } = await authorizedFetchJson(url, options);
  if (!response.ok) {
    throw new Error(getApiErrorMessage(data, response.status));
  }
  return data as T;
}

const json = (body: JsonBody): string => JSON.stringify(body);

export const api = {
  createSession: async (data: Record<string, unknown>): Promise<Session> => {
    const res = await request<SessionResponse>("/api/sessions", { method: "POST", body: json(data) });
    return toSession(res);
  },
  listSessions: async (): Promise<Session[]> => {
    const res = await request<SessionListResponse>("/api/sessions");
    return (res.sessions ?? []).map(toSession);
  },
  getSession: (id: string): Promise<Record<string, unknown>> => request(`/api/sessions/${id}`),
  updateSessionTitle: async (id: string, title: string): Promise<Session> => {
    const res = await request<SessionResponse>(`/api/sessions/${id}/title`, { method: "PUT", body: json({ title }) });
    return toSession(res);
  },
  deleteSession: (id: string): Promise<{ ok: boolean; message: string }> => request(`/api/sessions/${id}`, { method: "DELETE" }),
  listProviders: async (): Promise<Provider[]> => {
    const res = await request<ProviderResponse[]>("/api/providers");
    return (res ?? []).map(toProvider);
  },
  addProvider: async (data: Record<string, unknown>): Promise<Provider> => {
    const res = await request<ProviderResponse>("/api/providers", { method: "POST", body: json(data) });
    return toProvider(res);
  },
  updateProvider: async (id: string, data: Record<string, unknown>): Promise<Provider> => {
    const res = await request<ProviderResponse>(`/api/providers/${id}`, { method: "PUT", body: json(data) });
    return toProvider(res);
  },
  deleteProvider: (id: string): Promise<{ ok: boolean; message: string }> => request(`/api/providers/${id}`, { method: "DELETE" }),
  testProvider: (id: string): Promise<{ ok: boolean; message: string; latency_ms: number }> => request(`/api/providers/${id}/test`, { method: "POST" }),
  detectModels: (data: Record<string, unknown>): Promise<{ ok: boolean; models: string[]; message: string }> => request("/api/providers/detect-models", { method: "POST", body: json(data) }),
  setDefault: async (id: string): Promise<Provider> => {
    const res = await request<ProviderResponse>(`/api/providers/${id}/default`, { method: "PUT" });
    return toProvider(res);
  },
  listWorkspaceRoots: async (): Promise<WorkspaceEntry[]> => {
    const res = await request<WorkspaceRootsResponse>("/api/workspaces/roots");
    return (res.roots ?? []).map(toWorkspaceEntry);
  },
  listWorkspaceDirectory: async (path?: string): Promise<WorkspaceList> => {
    const search = path ? `?path=${encodeURIComponent(path)}` : "";
    const res = await request<WorkspaceListResponse>(`/api/workspaces/list${search}`);
    return {
      root: res.root,
      path: res.path,
      parent: res.parent ?? null,
      breadcrumbs: res.breadcrumbs ?? [],
      entries: (res.entries ?? []).map(toWorkspaceEntry),
      truncated: Boolean(res.truncated),
    };
  },
  validateWorkspace: async (path: string): Promise<WorkspaceValidation> => {
    const res = await request<WorkspaceValidationResponse>(`/api/workspaces/validate?path=${encodeURIComponent(path)}`);
    return {
      ok: res.ok,
      path: res.path,
      isProject: res.is_project,
      message: res.message,
    };
  },
  getMetricsSummary: async (days = 7): Promise<MetricsSummary> => {
    const res = await request<MetricsSummaryResponse>(`/api/metrics/summary?days=${days}`);
    return {
      periodDays: res.period_days,
      metrics: res.metrics as MetricsSummary["metrics"],
    };
  },
  getMetricDetail: async (name: string, days = 30): Promise<MetricDetail> => {
    const res = await request<MetricDetailResponse>(`/api/metrics/metric/${encodeURIComponent(name)}?days=${days}`);
    return res;
  },
  getTokenUsage: async (days = 90): Promise<TokenUsage> => {
    const res = await request<TokenUsageResponse>(`/api/metrics/tokens?days=${days}`);
    return {
      periodDays: res.period_days,
      totalTokens: res.total_tokens,
      promptTokens: res.prompt_tokens,
      completionTokens: res.completion_tokens,
      cachedPromptTokens: res.cached_prompt_tokens,
      llmCalls: res.llm_calls,
      daily: (res.daily ?? []).map((item) => ({
        date: item.date,
        promptTokens: item.prompt_tokens,
        completionTokens: item.completion_tokens,
        cachedPromptTokens: item.cached_prompt_tokens,
        llmCalls: item.llm_calls,
        totalTokens: item.total_tokens,
      })),
    };
  },
  searchLogs: async (params: LogSearchParams): Promise<LogSearchResult> => {
    const search = new URLSearchParams();
    if (params.traceId) search.set("trace_id", params.traceId);
    if (params.sessionId) search.set("session_id", params.sessionId);
    if (params.level) search.set("level", params.level);
    if (params.event) search.set("event", params.event);
    if (params.component) search.set("component", params.component);
    if (params.workerId) search.set("worker_id", params.workerId);
    if (params.errorCode) search.set("error_code", params.errorCode);
    if (params.limit) search.set("limit", String(params.limit));
    if (params.minutes) search.set("minutes", String(params.minutes));
    const res = await request<LogSearchResponse>(`/api/logs/search?${search.toString()}`);
    return { count: res.count, logs: (res.logs ?? []).map(toLogEntry) };
  },
  getTrace: async (traceId: string): Promise<TraceResult> => {
    const res = await request<TraceResponse>(`/api/logs/trace/${encodeURIComponent(traceId)}`);
    return { traceId: res.trace_id, events: (res.events ?? []).map(toLogEntry) };
  },
};
